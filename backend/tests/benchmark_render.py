"""Render benchmark: how long does a ~1 minute 1080p video take with different settings?

    python -m tests.benchmark_render [--scenes 10] [--seconds 6] [--out benchmark.md]

Needs ffmpeg; no network, no paid calls (Pillow images, tone audio, a library track). Compares
encode settings by time, file size and SSIM against the baseline, then runs several renders in
parallel (KPI K6). Run in CI via the `benchmark` workflow (4 vCPU, like the target VPS).
"""

import argparse
import platform
import random
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.services.compositor import DRAFT_ENCODE, RenderScene, render_video
from app.services.images.crop import DRAFT_SIZES, OUTPUT_SIZES
from app.services.music import get_track
from tests.media import fake_words, make_tone

FORMAT = "9:16"
TEXT = "Лиса жила на краю леса и каждое утро встречала рассвет на старом холме у реки."

BASELINE = dict(clip_preset="veryfast", clip_crf=20, upscale=2.0, preset="veryfast", crf=21)
VARIANTS: dict[str, dict] = {
    "baseline (veryfast clips, 2x upscale)": {**BASELINE, "concurrency": 2},
    "clips ultrafast crf18": {
        **BASELINE,
        "clip_preset": "ultrafast",
        "clip_crf": 18,
        "concurrency": 2,
    },
    "clips ultrafast + upscale 1.5": {
        **BASELINE,
        "clip_preset": "ultrafast",
        "clip_crf": 18,
        "upscale": 1.5,
        "concurrency": 2,
    },
    "clips ultrafast + upscale 1.25": {
        **BASELINE,
        "clip_preset": "ultrafast",
        "clip_crf": 18,
        "upscale": 1.25,
        "concurrency": 2,
    },
    "... + final ultrafast": {
        **BASELINE,
        "clip_preset": "ultrafast",
        "clip_crf": 18,
        "upscale": 1.5,
        "preset": "ultrafast",
        "concurrency": 2,
    },
    "... concurrency 1": {
        **BASELINE,
        "clip_preset": "ultrafast",
        "clip_crf": 18,
        "upscale": 1.5,
        "concurrency": 1,
    },
    "... concurrency 4": {
        **BASELINE,
        "clip_preset": "ultrafast",
        "clip_crf": 18,
        "upscale": 1.5,
        "concurrency": 4,
    },
}


def detailed_image(path: Path, size: tuple[int, int], seed: int) -> Path:
    """Not a flat gradient: blurred noise with shapes, closer to a generated picture."""
    rng = random.Random(seed)
    small = Image.new("RGB", (36, 64))
    small.putdata([tuple(rng.randrange(40, 230) for _ in range(3)) for _ in range(36 * 64)])
    image = small.resize(size, Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(6))
    draw = ImageDraw.Draw(image)
    for _ in range(25):
        x, y, r = rng.randrange(size[0]), rng.randrange(size[1]), rng.randrange(40, 260)
        color = tuple(rng.randrange(255) for _ in range(3))
        draw.ellipse([x - r, y - r, x + r, y + r], outline=color, width=rng.randrange(2, 10))
    image.save(path)
    return path


def make_scenes(work: Path, count: int, seconds: float, size: tuple[int, int]) -> list[RenderScene]:
    work.mkdir(parents=True, exist_ok=True)
    cameras = ["zoom_in", "pan_left", "zoom_out", "pan_right"]
    return [
        RenderScene(
            detailed_image(work / f"img{i}.png", size, i),
            make_tone(work / f"voice{i}.mp3", seconds, 220 + 20 * i),
            seconds, fake_words(TEXT, seconds), TEXT, cameras[i % 4],
        )
        for i in range(count)
    ]  # fmt: skip


def ssim(video: Path, reference: Path) -> float | None:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video), "-i", str(reference), "-lavfi", "ssim",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )  # fmt: skip
    match = re.search(r"All:([0-9.]+)", out.stderr)
    return float(match.group(1)) if match else None


def timed_render(scenes, out_dir: Path, size, music: Path, options: dict) -> tuple[float, Path]:
    started = time.monotonic()
    result = render_video(scenes, out_dir, FORMAT, size=size, music=music, **options)
    return time.monotonic() - started, result.video


def main(args: argparse.Namespace) -> None:
    work = Path(args.work)
    size = OUTPUT_SIZES[FORMAT]
    scenes = make_scenes(work / "assets", args.scenes, args.seconds, size)
    music = get_track("happy-badinerie").path
    narration = args.scenes * args.seconds
    lines = [
        f"### Render benchmark: {args.scenes} scenes x {args.seconds:g} s of narration "
        f"({narration:.0f} s) at {size[0]}x{size[1]}, 30 fps, music + karaoke subtitles",
        f"`{platform.processor() or platform.machine()}`, {_cpu_count()} CPUs, {_ffmpeg_version()}",
        "",
        "| Variant | Render time, s | x realtime | File, MB | SSIM vs baseline |",
        "|---|---:|---:|---:|---:|",
    ]

    reference = None
    for name, options in VARIANTS.items():
        seconds, video = timed_render(
            scenes, work / f"v-{len(lines)}", size, music, {"fps": 30, **options}
        )
        if reference is None:
            reference = video
        quality = "baseline" if video == reference else f"{ssim(video, reference):.4f}"
        lines.append(
            f"| {name} | {seconds:.1f} | {narration / seconds:.2f} | "
            f"{video.stat().st_size / 1e6:.1f} | {quality} |"
        )
        print(lines[-1], flush=True)

    draft_size = DRAFT_SIZES[FORMAT]
    seconds, video = timed_render(
        scenes, work / "v-draft", draft_size, music, dict(DRAFT_ENCODE, concurrency=2)
    )
    lines.append(
        f"| draft 480p preview | {seconds:.1f} | {narration / seconds:.2f} | "
        f"{video.stat().st_size / 1e6:.1f} | n/a (other size) |"
    )
    print(lines[-1], flush=True)

    best = {**BASELINE, "clip_preset": "ultrafast", "clip_crf": 18, "upscale": 1.5, "fps": 30}
    lines += ["", f"### {args.parallel} renders at the same time (KPI K6)", "",
              "| Per-render concurrency | Wall time, s | Slowest render, s | Fastest render, s |",
              "|---|---:|---:|---:|"]  # fmt: skip
    for concurrency in (1, 2):
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = [
                pool.submit(timed_render, scenes, work / f"p-{concurrency}-{i}", size, music,
                            {**best, "concurrency": concurrency})
                for i in range(args.parallel)
            ]  # fmt: skip
            times = [f.result()[0] for f in futures]
        lines.append(
            f"| {concurrency} | {time.monotonic() - started:.1f} | "
            f"{max(times):.1f} | {min(times):.1f} |"
        )
        print(lines[-1], flush=True)

    report = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    print("\n" + report)


def _cpu_count() -> int:
    import os

    return os.cpu_count() or 0


def _ffmpeg_version() -> str:
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
    return out.splitlines()[0] if out else "ffmpeg ?"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenes", type=int, default=10)
    parser.add_argument("--seconds", type=float, default=6.0, help="narration length per scene")
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--work", default="benchmark-work")
    parser.add_argument("--out", default="benchmark.md")
    main(parser.parse_args())
