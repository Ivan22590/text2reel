"""Renders sample videos and saves still frames, to look at the result with your own eyes.

    python -m tests.sample_frames OUT_DIR

Needs ffmpeg. Used by CI (frames are uploaded as an artifact) and handy locally after changing
templates, fonts or branding. No network and no paid calls: images are drawn with Pillow and the
voice is a tone.
"""

import io
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from app.services.branding import Branding, logo_path, save_logo
from app.services.cards import build_card_scenes
from app.services.compositor import RenderScene, compute_timeline, render_video
from app.services.music import get_track
from app.services.templates import get_template
from tests.media import fake_words, make_tone

NARRATION = [
    "Лиса жила на краю леса, и каждое утро она встречала рассвет.",
    "Однажды на старом холме она нашла светящийся камень!",
    "Камень шептал: «Добро пожаловать домой».",
]
COLORS = [
    ((250, 190, 110), (90, 40, 120)),
    ((110, 200, 250), (20, 60, 110)),
    ((150, 230, 150), (20, 90, 60)),
]


def scene_image(path: Path, size: tuple[int, int], index: int) -> Path:
    top, bottom = COLORS[index % len(COLORS)]
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        k = y / size[1]
        draw.line(
            [(0, y), (size[0], y)],
            fill=tuple(round(a + (b - a) * k) for a, b in zip(top, bottom, strict=True)),
        )
    draw.ellipse(
        [size[0] * 0.3, size[1] * 0.3, size[0] * 0.7, size[1] * 0.3 + size[0] * 0.4],
        fill=(255, 255, 255),
    )
    image.save(path)
    return path


def make_logo(path: Path) -> Path:
    image = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([10, 10, 290, 290], fill=(255, 60, 90, 255))
    draw.rectangle([110, 90, 190, 210], fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    save_logo(buf.getvalue(), path)
    return path


def frame(video: Path, at: float, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video),
         "-frames:v", "1", str(out)],
        check=True,
    )  # fmt: skip


def render_sample(
    out: Path, name: str, fmt: str, size: tuple[int, int], branding: Branding
) -> None:
    work = out / name
    work.mkdir(parents=True, exist_ok=True)
    template = get_template(fmt)
    scenes = []
    for i, text in enumerate(NARRATION):
        seconds = 0.32 * len(text.split())
        scenes.append(
            RenderScene(
                scene_image(work / f"img{i}.png", size, i),
                make_tone(work / f"voice{i}.mp3", seconds, 300 + 80 * i),
                seconds, fake_words(text, seconds), text, ["zoom_in", "pan_left", "zoom_out"][i],
            )
        )  # fmt: skip
    logo = make_logo(logo_path(work))
    intro, outro = build_card_scenes(branding, template, size, work / "cards", logo)
    music = get_track("happy-badinerie").path
    result = render_video(scenes, work, fmt, size=size, template=template, branding=branding,
                          logo=logo, intro=intro, outro=outro, music=music, fps=15)  # fmt: skip

    durations = [s.duration for s in [intro, *scenes, outro] if s]
    pauses = [0.0 if s.pause == 0.0 else 0.4 for s in [intro, *scenes, outro] if s]
    starts = compute_timeline(durations, 0.4, template.transition.duration, pauses).starts
    frame(result.video, starts[0] + 1.0, out / f"{name}-1-intro.png")
    frame(result.video, starts[1] + durations[1] * 0.45, out / f"{name}-2-scene.png")
    frame(result.video, starts[2] + durations[2] * 0.55, out / f"{name}-3-scene.png")
    frame(result.video, starts[-1] + 1.0, out / f"{name}-4-outro.png")
    print(f"{name}: {result.duration:.1f}s, {result.video.stat().st_size // 1024} KB")


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    brand = Branding(intro_text="Лисья история", outro_text="Подписывайтесь на канал!")
    render_sample(out, "shorts", "9:16", (540, 960), brand)
    render_sample(out, "youtube", "16:9", (960, 540), brand.model_copy(update={"font": "PT Sans"}))
    render_sample(
        out, "instagram-lobster", "1:1", (600, 600),
        brand.model_copy(update={"font": "Lobster", "subtitle_color": "#FFFF66",
                                 "accent_color": "#D6336C", "logo_position": "bottom-left"}),
    )  # fmt: skip
    render_sample(out, "shorts-russo", "9:16", (540, 960),
                  brand.model_copy(update={"font": "Russo One", "background_color": "#0B3D2E",
                                           "accent_color": "#1B998B"}))  # fmt: skip


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "sample-frames"))
