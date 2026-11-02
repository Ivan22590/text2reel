import pytest

from app.services.compositor import (
    RenderScene,
    audio_cmd,
    compose_cmd,
    compute_timeline,
    kenburns_cmd,
    render_video,
)
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
