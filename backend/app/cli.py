"""Command-line tools.

python -m app.cli llm-models [--filter haiku]    # list model ids available in ProxyAPI
python -m app.cli smoke-llm                      # one cheap request to primary + fallback
python -m app.cli scenes script.txt --style anime --format 9:16 --out storyboard.json
python -m app.cli images storyboard.json --style anime --format 9:16 --out-dir out/
python -m app.cli tts storyboard.json --voice ru-RU-SvetlanaNeural --format 9:16 --out-dir out/
python -m app.cli compose --storyboard storyboard.json --images out/ --narration out/narration.json
python -m app.cli render script.txt --style anime --format 9:16 --out-dir out/   # everything
"""

import argparse
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.prompts.loader import load_prompt
from app.services.compositor import RenderScene, render_video
from app.services.images import get_provider
from app.services.images.crop import OUTPUT_SIZES
from app.services.images.generator import generate_images
from app.services.images.prompting import build_prompts
from app.services.llm.client import LLMClient, LLMError
from app.services.pipeline import PipelineError, run_pipeline
from app.services.scenes import FORMATS, Storyboard, split_script
from app.services.styles import get_style, load_style_presets
from app.services.subtitles import STYLE_DEFAULTS, build_cues, place_on_timeline, to_ass, to_srt
from app.services.tts import VOICES, read_manifest, synthesize_scenes, write_manifest


def cmd_llm_models(args: argparse.Namespace) -> int:
    models = sorted(m.id for m in LLMClient().client.models.list())
    for model_id in models:
        if not args.filter or args.filter.lower() in model_id.lower():
            print(model_id)
    return 0


def cmd_smoke_llm(_: argparse.Namespace) -> int:
    llm = LLMClient()
    prompt = load_prompt("smoke_llm")
    messages = [
        {"role": "system", "content": prompt.render("system")},
        {"role": "user", "content": prompt.render("user")},
    ]
    failed = False
    for model in (llm.primary_model, llm.fallback_model):
        started = time.monotonic()
        try:
            result = llm.complete(messages, model=model, max_tokens=50, use_fallback=False)
        except LLMError as exc:
            print(f"FAIL {model}: {exc}")
            failed = True
            continue
        print(
            f"OK   {model}: {result.content.strip()} | tokens {result.usage.tokens_in}/"
            f"{result.usage.tokens_out} | {result.usage.cost_rub:.4f} RUB | "
            f"{time.monotonic() - started:.1f}s"
        )
    return 1 if failed else 0


def cmd_scenes(args: argparse.Namespace) -> int:
    script = Path(args.script).read_text(encoding="utf-8")
    cache_dir = None if args.no_cache else get_settings().storage_dir / "cache" / "llm"
    started = time.monotonic()
    result = split_script(
        script, style=args.style, format=args.format, language=args.language, cache_dir=cache_dir
    )
    output = result.storyboard.model_dump_json(indent=2)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        print(output)
    usage = result.usage
    print(
        f"scenes: {len(result.storyboard.scenes)} | cached: {result.cached} | "
        f"attempts: {result.attempts} | tokens {usage.tokens_in}/{usage.tokens_out} | "
        f"{usage.cost_rub:.4f} RUB | {time.monotonic() - started:.1f}s",
        file=sys.stderr,
    )
    return 0


def cmd_images(args: argparse.Namespace) -> int:
    settings = get_settings()
    storyboard = Storyboard.model_validate_json(Path(args.storyboard).read_text(encoding="utf-8"))
    prompts, negative = build_prompts(storyboard, get_style(args.style))
    started = time.monotonic()
    results = generate_images(
        prompts,
        negative_prompt=negative,
        format=args.format,
        seed=args.seed,
        out_dir=Path(args.out_dir),
        provider=get_provider(settings),
        cache_dir=None if args.no_cache else settings.storage_dir / "cache" / "images",
        concurrency=settings.image_concurrency,
        fit=args.fit or settings.image_fit,
    )
    for item in results:
        status = f"OK {item.path}" + (" (cache)" if item.cached else "") if item.ok else item.error
        print(f"scene {item.index:02d}: {status}")
    failed = sum(not item.ok for item in results)
    total = sum(item.cost_rub for item in results)
    print(
        f"images: {len(results) - failed}/{len(results)} | {total:.2f} RUB | "
        f"{time.monotonic() - started:.1f}s",
        file=sys.stderr,
    )
    return 1 if failed else 0


def cmd_tts(args: argparse.Namespace) -> int:
    settings = get_settings()
    storyboard = Storyboard.model_validate_json(Path(args.storyboard).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    texts = [scene.narration for scene in storyboard.scenes]
    started = time.monotonic()
    results = synthesize_scenes(
        texts,
        voice=args.voice,
        rate=args.rate or settings.tts_rate,
        pitch=args.pitch or settings.tts_pitch,
        out_dir=out_dir,
        cache_dir=None if args.no_cache else settings.storage_dir / "cache" / "tts",
        concurrency=settings.tts_concurrency,
    )
    for item in results:
        status = f"OK {item.path} {item.duration:.2f}s" if item.ok else item.error
        print(f"scene {item.index:02d}: {status}")
    if any(not item.ok for item in results):
        return 1

    # Preview timeline: scenes back to back with a pause; the compositor (stage 4)
    # computes the final offsets including transitions.
    offset, placed = 0.0, []
    for item, text in zip(results, texts, strict=True):
        placed.append((offset, item.words, text))
        offset += item.duration + settings.tts_scene_pause_sec
    style = STYLE_DEFAULTS[args.format]
    cues = build_cues(place_on_timeline(placed), max_chars=style.max_chars)
    (out_dir / "subtitles.srt").write_text(to_srt(cues), encoding="utf-8")
    (out_dir / "subtitles.ass").write_text(
        to_ass(cues, *OUTPUT_SIZES[args.format], style), encoding="utf-8"
    )
    write_manifest(results, out_dir / "narration.json")
    print(
        f"narration: {offset:.1f}s total | cues: {len(cues)} | {time.monotonic() - started:.1f}s",
        file=sys.stderr,
    )
    return 0


def cmd_compose(args: argparse.Namespace) -> int:
    """Re-renders a video from existing images and narration (no paid calls)."""
    settings = get_settings()
    storyboard = Storyboard.model_validate_json(Path(args.storyboard).read_text(encoding="utf-8"))
    narrations = read_manifest(Path(args.narration))
    images = Path(args.images)
    scenes = [
        RenderScene(images / f"scene_{n.index:02d}.png", n.path, n.duration, n.words,
                    sc.narration, sc.camera)
        for n, sc in zip(narrations, storyboard.scenes, strict=True)
    ]  # fmt: skip
    result = render_video(
        scenes, Path(args.out_dir), args.format,
        music=Path(args.music) if args.music else None, music_volume=settings.music_volume,
        transition_sec=settings.transition_sec, pause=settings.tts_scene_pause_sec,
        fps=settings.render_fps, preset=settings.ffmpeg_preset,
        concurrency=settings.render_concurrency,
    )  # fmt: skip
    steps = " | ".join(f"{name} {sec:.1f}s" for name, sec in result.timings.items())
    print(f"{result.video} ({result.duration:.1f}s) | {steps}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    settings = get_settings()

    def on_progress(step: str, percent: float, message: str) -> None:
        print(f"[{percent:5.1f}%] {step}: {message}", file=sys.stderr)

    try:
        result = run_pipeline(
            Path(args.script).read_text(encoding="utf-8"),
            style=args.style, format=args.format, voice=args.voice, seed=args.seed,
            out_dir=Path(args.out_dir), music=Path(args.music) if args.music else None,
            use_cache=not args.no_cache, on_progress=on_progress, settings=settings,
        )  # fmt: skip
    except PipelineError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    for step in result.steps:
        print(f"{step.name:7s} {step.seconds:6.1f}s {step.cost_rub:7.2f} RUB")
    print(
        f"video: {result.video} ({result.duration:.1f}s) | total {result.seconds:.1f}s, "
        f"{result.cost_rub:.2f} RUB | report: {result.report}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    models = sub.add_parser("llm-models", help="list ProxyAPI model ids")
    models.add_argument("--filter", default="")
    models.set_defaults(func=cmd_llm_models)

    smoke = sub.add_parser("smoke-llm", help="cheap request to primary and fallback models")
    smoke.set_defaults(func=cmd_smoke_llm)

    scenes = sub.add_parser("scenes", help="split a script file into scenes")
    scenes.add_argument("script")
    scenes.add_argument("--style", default="realism", choices=sorted(load_style_presets()))
    scenes.add_argument("--format", default="9:16", choices=FORMATS)
    scenes.add_argument("--language", default=None, help="ru | en (auto-detected by default)")
    scenes.add_argument("--out", default=None, help="write JSON to file instead of stdout")
    scenes.add_argument("--no-cache", action="store_true")
    scenes.set_defaults(func=cmd_scenes)

    images = sub.add_parser("images", help="generate one image per scene of a storyboard JSON")
    images.add_argument("storyboard", help="JSON produced by `scenes --out`")
    images.add_argument("--style", default="realism", choices=sorted(load_style_presets()))
    images.add_argument("--format", default="9:16", choices=FORMATS)
    images.add_argument("--seed", type=int, default=42)
    images.add_argument("--out-dir", default="out")
    images.add_argument("--fit", choices=("cover", "blur"), default=None)
    images.add_argument("--no-cache", action="store_true")
    images.set_defaults(func=cmd_images)

    tts = sub.add_parser("tts", help="narrate every scene and build SRT/ASS subtitles")
    tts.add_argument("storyboard", help="JSON produced by `scenes --out`")
    tts.add_argument("--voice", default=get_settings().tts_voice, choices=sorted(VOICES))
    tts.add_argument("--rate", default=None, help="e.g. +10%% or -5%%")
    tts.add_argument("--pitch", default=None, help="e.g. +2Hz")
    tts.add_argument("--format", default="9:16", choices=FORMATS)
    tts.add_argument("--out-dir", default="out")
    tts.add_argument("--no-cache", action="store_true")
    tts.set_defaults(func=cmd_tts)

    compose = sub.add_parser("compose", help="render video from existing images + narration")
    compose.add_argument("--storyboard", required=True)
    compose.add_argument("--images", required=True, help="dir with scene_XX.png")
    compose.add_argument("--narration", required=True, help="narration.json from `tts`")
    compose.add_argument("--format", default="9:16", choices=FORMATS)
    compose.add_argument("--music", default=None, help="background music file")
    compose.add_argument("--out-dir", default="out")
    compose.set_defaults(func=cmd_compose)

    render = sub.add_parser("render", help="full pipeline: script file -> MP4")
    render.add_argument("script")
    render.add_argument("--style", default="realism", choices=sorted(load_style_presets()))
    render.add_argument("--format", default="9:16", choices=FORMATS)
    render.add_argument("--voice", default=get_settings().tts_voice, choices=sorted(VOICES))
    render.add_argument("--seed", type=int, default=42)
    render.add_argument("--music", default=None, help="background music file")
    render.add_argument("--out-dir", default="out")
    render.add_argument("--no-cache", action="store_true")
    render.set_defaults(func=cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
