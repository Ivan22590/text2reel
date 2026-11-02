import io
from pathlib import Path

import pytest
from PIL import Image

from app.config import Settings
from app.services.branding import Branding, logo_path, save_logo
from app.services.cards import build_card_scenes
from app.services.compositor import (
    RenderScene,
    audio_cmd,
    compose_cmd,
    compute_timeline,
    encode_options,
    kenburns_cmd,
    logo_overlay,
    render_video,
)
from app.services.images.crop import DRAFT_SIZES, OUTPUT_SIZES
from app.services.templates import get_template
from tests.media import fake_words, make_image, make_tone, probe, requires_ffmpeg


def arg_after(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_timeline_keeps_voice_out_of_transitions():
    tl = compute_timeline([2.0, 3.0, 1.5], pause=0.4, transition=0.4)
    assert tl.clip_durations == pytest.approx([2.8, 3.8, 1.9])
    assert tl.starts == pytest.approx([0.0, 2.4, 5.8])
    assert tl.total == pytest.approx(7.7)
    # narration i ends (start_i + d_i) before the transition into scene i+1 begins
    for start, nxt, d in zip(tl.starts, tl.starts[1:], [2.0, 3.0], strict=False):
        assert start + d <= nxt


def test_timeline_single_scene_and_empty():
    assert compute_timeline([2.0], 0.4, 0.4).total == pytest.approx(2.4)
    with pytest.raises(ValueError):
        compute_timeline([], 0.4, 0.4)


def test_kenburns_cmd_golden(tmp_path):
    cmd = kenburns_cmd(tmp_path / "a.png", tmp_path / "c.mp4", 2.0, (1080, 1920), "zoom_in")
    assert cmd[:2] == ["ffmpeg", "-y"]
    assert arg_after(cmd, "-vf") == (
        "scale=2160:3840,zoompan=z='1+0.15*on/60':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d=60:s=1080x1920:fps=30,format=yuv420p"
    )
    assert arg_after(cmd, "-frames:v") == "60"
    assert arg_after(cmd, "-preset") == "veryfast"


@pytest.mark.parametrize(
    "camera, fragment",
    [
        ("zoom_out", "z='1.15-0.15*on/30'"),
        ("pan_left", "x='(iw-iw/zoom)*(1-on/30)'"),
        ("pan_right", "x='(iw-iw/zoom)*on/30'"),
        ("static", "z='1.03'"),
        ("unknown", "z='1.03'"),
    ],
)
def test_kenburns_cameras(tmp_path, camera, fragment):
    cmd = kenburns_cmd(tmp_path / "a.png", tmp_path / "c.mp4", 1.0, (320, 180), camera)
    assert fragment in arg_after(cmd, "-vf")


def test_audio_cmd_delays_and_loudnorm(tmp_path):
    cmd = audio_cmd([tmp_path / "a.mp3", tmp_path / "b.mp3"], [0.0, 2.4], 5.0, tmp_path / "o.m4a")
    graph = arg_after(cmd, "-filter_complex")
    assert "adelay=0:all=1[a0]" in graph and "adelay=2400:all=1[a1]" in graph
    assert "amix=inputs=2:normalize=0" in graph and "loudnorm=I=-16" in graph
    assert "atrim=0:5.000" in graph
    assert arg_after(cmd, "-map") == "[voice]"
    assert "-stream_loop" not in cmd


def test_audio_cmd_with_music_ducking(tmp_path):
    cmd = audio_cmd(
        [tmp_path / "a.mp3"],
        [0.0],
        3.0,
        tmp_path / "o.m4a",
        music=tmp_path / "m.mp3",
        music_volume=0.2,
    )
    graph = arg_after(cmd, "-filter_complex")
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"
    assert "[1:a]" in graph and "volume=0.2" in graph and "sidechaincompress" in graph
    assert arg_after(cmd, "-map") == "[mix]"


def test_compose_cmd_xfade_offsets_and_subtitles(tmp_path):
    tl = compute_timeline([2.0, 3.0, 1.5], 0.4, 0.4)
    clips = [tmp_path / f"c{i}.mp4" for i in range(3)]
    cmd = compose_cmd(
        clips,
        tl,
        tmp_path / "a.m4a",
        "subtitles.ass",
        tmp_path / "v.mp4",
        transition="slideleft",
        fontsdir=tmp_path / "fonts",
    )
    graph = arg_after(cmd, "-filter_complex")
    assert "[0:v][1:v]xfade=transition=slideleft:duration=0.4:offset=2.400[x1]" in graph
    assert "[x1][2:v]xfade=transition=slideleft:duration=0.4:offset=5.800[x2]" in graph
    assert "[x2]ass=subtitles.ass:fontsdir=" in graph
    assert cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "3:a"
    assert "+faststart" in cmd and arg_after(cmd, "-t") == "7.700"


def test_compose_cmd_single_clip_has_no_xfade(tmp_path):
    tl = compute_timeline([2.0], 0.4, 0.4)
    cmd = compose_cmd([tmp_path / "c.mp4"], tl, tmp_path / "a.m4a", "s.ass", tmp_path / "v.mp4")
    assert arg_after(cmd, "-filter_complex") == "[0:v]ass=s.ass[v]"


SMALL = {"9:16": (180, 320), "16:9": (320, 180), "1:1": (240, 240)}


def make_scenes(tmp_path, durations):
    texts = ["Первая сцена истории.", "Вторая сцена, продолжение.", "Финал."]
    scenes = []
    for i, (seconds, text) in enumerate(zip(durations, texts, strict=False)):
        image = make_image(tmp_path / f"img{i}.png", (360, 640), (60 * i, 120, 200))
        audio = make_tone(tmp_path / f"voice{i}.mp3", seconds, 300 + 100 * i)
        scenes.append(
            RenderScene(
                image,
                audio,
                seconds,
                fake_words(text, seconds),
                text,
                ["zoom_in", "pan_left", "zoom_out"][i],
            )
        )
    return scenes


@requires_ffmpeg
@pytest.mark.ffmpeg
@pytest.mark.parametrize("fmt", list(SMALL))
def test_render_video_end_to_end(tmp_path, fmt):
    scenes = make_scenes(tmp_path, [1.2, 1.0, 0.8])
    result = render_video(scenes, tmp_path / "out", fmt, size=SMALL[fmt], fps=15)
    info = probe(result.video)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == SMALL[fmt]
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert float(info["format"]["duration"]) == pytest.approx(result.duration, abs=0.3)
    assert result.srt.read_text(encoding="utf-8").startswith("1\n00:00:00,000")
    assert "Вторая" in result.ass.read_text(encoding="utf-8")


@requires_ffmpeg
@pytest.mark.ffmpeg
def test_render_video_with_music(tmp_path):
    scenes = make_scenes(tmp_path, [1.0, 1.0])
    music = make_tone(tmp_path / "music.mp3", 0.7, 220)  # shorter than video: must loop
    result = render_video(scenes, tmp_path / "out", "16:9", size=SMALL["16:9"], fps=15, music=music)
    assert float(probe(result.video)["format"]["duration"]) == pytest.approx(
        result.duration, abs=0.3
    )


def test_timeline_with_cards_has_no_pause_around_them():
    # intro card (2.2 s, no pause), one scene (3 s + 0.4 pause), outro card (2.6 s)
    tl = compute_timeline([2.2, 3.0, 2.6], 0.4, 0.4, pauses=[0.0, 0.4, 0.0])
    assert tl.clip_durations == pytest.approx([2.6, 3.8, 2.6])
    assert tl.starts == pytest.approx([0.0, 2.2, 5.6])  # narration starts when the intro ends
    assert tl.total == pytest.approx(8.2)


def test_audio_cmd_music_fades_in_and_out(tmp_path):
    cmd = audio_cmd([tmp_path / "a.mp3"], [0.0], 3.0, tmp_path / "o.m4a", music=tmp_path / "m.ogg")
    graph = arg_after(cmd, "-filter_complex")
    assert "afade=t=in:st=0:d=0.8,afade=t=out:st=1.500:d=1.500[music]" in graph
    assert "atrim=0:3.000,afade" in graph  # trimmed first, then faded


def test_kenburns_uses_template_zoom(tmp_path):
    cmd = kenburns_cmd(tmp_path / "a.png", tmp_path / "c.mp4", 2.0, (320, 180), "zoom_in", zoom=0.3)
    assert "z='1+0.3*on/60'" in arg_after(cmd, "-vf")


def test_logo_overlay_respects_safe_zones():
    shorts = logo_overlay(
        Path("logo.png"), "top-right", 0.16, 0.9, (1080, 1920), 0.12, 0.2, 2.2, 9.0
    )
    assert (shorts.width, shorts.x, shorts.y) == (173, "W-w-43", "230")  # below the top UI band
    wide = logo_overlay(Path("l.png"), "bottom-left", 0.12, 1.0, (1920, 1080), 0.05, 0.08, 0, 5)
    assert (wide.x, wide.y) == ("77", "H-h-86")


def test_compose_cmd_adds_logo_for_narrated_scenes_only(tmp_path):
    tl = compute_timeline([2.0, 3.0], 0.4, 0.4)
    logo = logo_overlay(tmp_path / "logo.png", "top-right", 0.16, 0.85, (1080, 1920),
                        0.12, 0.2, 0.4, 2.8)  # fmt: skip
    cmd = compose_cmd([tmp_path / "c0.mp4", tmp_path / "c1.mp4"], tl, tmp_path / "a.m4a",
                      "s.ass", tmp_path / "v.mp4", logo=logo)  # fmt: skip
    graph = arg_after(cmd, "-filter_complex")
    assert cmd.count("-i") == 4  # two clips, audio, logo
    assert cmd.index(str(tmp_path / "logo.png")) == cmd.index(str(tmp_path / "a.m4a")) + 2
    assert "[3:v]scale=173:-1,format=rgba,colorchannelmixer=aa=0.85[lg]" in graph
    assert "[x1][lg]overlay=x=W-w-43:y=230:enable='between(t,0.400,2.800)'[vl]" in graph
    assert graph.endswith("[vl]ass=s.ass[v]")  # subtitles are drawn above the logo
    assert [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-map"] == ["[v]", "2:a"]


@requires_ffmpeg
@pytest.mark.ffmpeg
def test_render_with_branding_cards_logo_and_music(tmp_path):
    size = (180, 320)
    scenes = make_scenes(tmp_path, [1.2, 1.0])
    template = get_template("9:16")
    branding = Branding(intro_text="Привет, мир!", outro_text="Подписывайтесь!", font="Lobster",
                        subtitle_color="#FFFF00")  # fmt: skip
    logo = logo_path(tmp_path / "project")
    save_logo(_png(60, 60), logo)
    out_dir = tmp_path / "out"
    intro, outro = build_card_scenes(branding, template, size, out_dir / "work", logo)
    music = make_tone(tmp_path / "music.mp3", 0.7, 220)

    result = render_video(scenes, out_dir, "9:16", size=size, template=template, branding=branding,
                          logo=logo, intro=intro, outro=outro, music=music, fps=15)  # fmt: skip

    narrated = 1.2 + 1.0 + 2 * 0.4
    cards = template.intro_seconds + template.outro_seconds
    # every transition overlaps the clips: total = sum(d + p) of all scenes
    assert result.duration == pytest.approx(narrated + cards, abs=0.01)
    info = probe(result.video)
    assert float(info["format"]["duration"]) == pytest.approx(result.duration, abs=0.3)
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}

    srt = result.srt.read_text(encoding="utf-8")
    first_cue = srt.splitlines()[1]
    assert first_cue.startswith("00:00:02,200")  # narration waits for the intro card
    assert "Привет" not in srt and "Подписывайтесь" not in srt  # cards carry no subtitles
    ass = result.ass.read_text(encoding="utf-8")
    assert "Style: Default,Lobster," in ass and "&H0000FFFF" in ass  # brand font and colour


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), (0, 160, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_kenburns_upscale_factor(tmp_path):
    cmd = kenburns_cmd(tmp_path / "a.png", tmp_path / "c.mp4", 1.0, (1080, 1920), "zoom_in",
                       upscale=1.5)  # fmt: skip
    assert arg_after(cmd, "-vf").startswith("scale=1620:2880,zoompan")


def test_draft_profile_is_much_cheaper_than_final():
    settings = Settings()
    final, draft = encode_options(settings), encode_options(settings, draft=True)
    assert (
        final["preset"] == settings.ffmpeg_preset and final["clip_crf"] == settings.ffmpeg_clip_crf
    )
    assert draft["preset"] == draft["clip_preset"] == "ultrafast"
    assert (
        draft["fps"] == 24 and draft["crf"] > final["crf"] and draft["upscale"] < final["upscale"]
    )


def test_draft_sizes_keep_the_aspect_ratio_and_are_even():
    for fmt, (w, h) in DRAFT_SIZES.items():
        fw, fh = OUTPUT_SIZES[fmt]
        assert w % 2 == 0 and h % 2 == 0 and min(w, h) == 480
        assert abs(w / h - fw / fh) < 0.01
