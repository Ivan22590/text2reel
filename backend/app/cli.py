"""Command-line tools.

python -m app.cli llm-models [--filter haiku]    # list model ids available in ProxyAPI
python -m app.cli smoke-llm                      # one cheap request to primary + fallback
python -m app.cli image-models                   # image model ids available in ProxyAPI
python -m app.cli smoke-image [--model ID]       # one image: size, time, tokens, cost (~1 RUB)
python -m app.cli scenes script.txt --style anime --format 9:16 --out storyboard.json
python -m app.cli images storyboard.json --style anime --format 9:16 --out-dir out/
python -m app.cli tts storyboard.json --voice ru-RU-SvetlanaNeural --format 9:16 --out-dir out/
python -m app.cli compose --storyboard storyboard.json --images out/ --narration out/narration.json
python -m app.cli render script.txt --style anime --format 9:16 --out-dir out/   # everything
python -m app.cli music                          # background music library
python -m app.cli cleanup                        # delete expired projects and old cache
python -m app.cli stats [--json]                 # KPI report from the database
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.db import SessionLocal
from app.prompts.loader import load_prompt
from app.services.branding import FONTS, Branding
from app.services.cards import build_card_scenes
from app.services.cleanup import cleanup_expired
from app.services.compositor import RenderScene, encode_options, render_video
from app.services.images import ImageError, ImageRequest, get_provider
from app.services.images.crop import DRAFT_SIZES, GENERATION_SIZES, OUTPUT_SIZES
from app.services.images.generator import generate_images
from app.services.images.prompting import build_prompts
from app.services.llm.client import LLMClient, LLMError
from app.services.music import is_valid_choice, load_catalog, resolve_music
from app.services.pipeline import PipelineError, run_pipeline
from app.services.scenes import FORMATS, Storyboard, split_script
from app.services.stats import compute_stats
from app.services.styles import get_style, load_style_presets
from app.services.subtitles import build_cues, place_on_timeline, to_ass, to_srt
from app.services.templates import get_template
from app.services.tts import VOICES, read_manifest, synthesize_scenes, write_manifest


def _music_arg(value: str) -> str | Path:
    """`auto`, `none`, a library track id (see `music`) or a path to an audio file."""
    if Path(value).is_file():
        return Path(value)
    if not is_valid_choice(value):
        raise SystemExit(f"unknown --music {value!r}: use auto, none, a track id or a file path")
    return value


def _branding_args(args: argparse.Namespace) -> tuple[Branding, Path | None]:
    data = {}
    if args.branding:
        data = json.loads(Path(args.branding).read_text(encoding="utf-8"))
    for key in ("intro_text", "outro_text", "font"):
        if getattr(args, key, None):
            data[key] = getattr(args, key)
    return Branding.model_validate(data), Path(args.logo) if args.logo else None


def cmd_music(_: argparse.Namespace) -> int:
    for track in load_catalog():
        mins, secs = divmod(int(track.duration), 60)
        moods = ",".join(track.moods)
        print(f"{track.id:28} {mins}:{secs:02d}  {moods:20} {track.title} - {track.artist}")
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        report = cleanup_expired(db, ttl_days=args.ttl_days)
    print(
        f"projects deleted: {report.projects} | cache files: {report.cache_files} | "
        f"freed: {report.freed_bytes / 1e6:.1f} MB | stuck jobs recovered: {report.recovered}"
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        stats = compute_stats(db)
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    final, spread = stats["render_final"], stats["pipeline_seconds"]
    print(f"projects: {stats['projects']['total']} {stats['projects']['by_status']}")
    print(
        f"final renders: {final['done']} done, {final['failed']} failed, "
        f"success rate {final['success_rate']}"
    )
    print(f"  render seconds: {final['seconds']}")
    print(f"K1 pipeline seconds (scenes+images+render): {spread}")
    print(f"K2 cost, RUB: {stats['cost_rub']}")
    return 0


IMAGE_MODEL_HINTS = (
    "image",
    "flux",
    "seedream",
    "qwen",
    "banana",
    "dall",
    "imagen",
    "recraft",
    "sd",
)


def cmd_image_models(_: argparse.Namespace) -> int:
    """Ids from ProxyAPI's /v1/models that look like image generators (prices: ProxyAPI catalog)."""
    for model_id in sorted(m.id for m in LLMClient().client.models.list()):
        if any(hint in model_id.lower() for hint in IMAGE_MODEL_HINTS):
            print(model_id)
    return 0


def cmd_smoke_image(args: argparse.Namespace) -> int:
    """Generates one image with the configured provider and reports what it really costs."""
    updates = {}
    if args.provider:
        updates["image_provider"] = args.provider
    if args.model:
        updates["fal_model" if (args.provider or get_settings().image_provider) == "fal"
                else "proxyapi_image_model"] = args.model  # fmt: skip
    settings = get_settings().model_copy(update=updates)
    try:
        provider = get_provider(settings)
        width, height = GENERATION_SIZES[args.format]
        started = time.monotonic()
        result = provider.generate(ImageRequest(args.prompt, "", width, height, seed=42))
    except ImageError as exc:
        print(f"FAIL: {exc}")
        return 1
    Path(args.out).write_bytes(result.data)
    with Image.open(io.BytesIO(result.data)) as image:
        got = image.size
    print(
        f"OK {provider.name}/{provider.model} | wanted {width}x{height}, asked "
        f"{result.info.get('size', '?')}, got {got[0]}x{got[1]} | "
        f"{time.monotonic() - started:.1f}s | "
        f"tokens {result.info.get('tokens_in', '?')}/{result.info.get('tokens_out', '?')} | "
        f"{result.cost_rub:.2f} RUB | saved {args.out}"
    )
    return 0


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
    style = get_template(args.format).subtitle_style()
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
    template = get_template(args.format)
    branding, logo = _branding_args(args)
    out_dir = Path(args.out_dir)
    size = DRAFT_SIZES[args.format] if args.draft else OUTPUT_SIZES[args.format]
    intro, outro = build_card_scenes(branding, template, size, out_dir / "work", logo)
    music = _music_arg(args.music)
    if isinstance(music, Path):
        music_file = music
    else:
        moods = [(sc.mood, n.duration) for sc, n in zip(storyboard.scenes, narrations, strict=True)]
        track = resolve_music(music, moods, args.seed)
        music_file = track.path if track else None
    result = render_video(
        scenes, out_dir, args.format, size=size, template=template, branding=branding, logo=logo,
        intro=intro, outro=outro, music=music_file, pause=settings.tts_scene_pause_sec,
        **encode_options(settings, draft=args.draft),
    )  # fmt: skip
    steps = " | ".join(f"{name} {sec:.1f}s" for name, sec in result.timings.items())
    print(f"{result.video} ({result.duration:.1f}s) | {steps}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    settings = get_settings()

    def on_progress(step: str, percent: float, message: str) -> None:
        print(f"[{percent:5.1f}%] {step}: {message}", file=sys.stderr)

    branding, logo = _branding_args(args)
    try:
        result = run_pipeline(
            Path(args.script).read_text(encoding="utf-8"),
            style=args.style, format=args.format, voice=args.voice, seed=args.seed,
            out_dir=Path(args.out_dir), music=_music_arg(args.music), branding=branding,
            logo=logo, use_cache=not args.no_cache, on_progress=on_progress, settings=settings,
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


def _add_music_and_branding_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--music", default="auto", help="auto | none | track id | audio file")
    parser.add_argument("--branding", default=None, help="JSON with brand settings")
    parser.add_argument("--logo", default=None, help="logo image (PNG with alpha is best)")
    parser.add_argument("--intro-text", dest="intro_text", default=None, help="intro card title")
    parser.add_argument("--outro-text", dest="outro_text", default=None, help="outro card title")
    parser.add_argument("--font", default=None, choices=sorted(FONTS), help="subtitle/card font")


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

    cleanup = sub.add_parser("cleanup", help="delete expired projects and old cache files")
    cleanup.add_argument("--ttl-days", type=int, default=None, help="default: STORAGE_TTL_DAYS")
    cleanup.set_defaults(func=cmd_cleanup)

    stats = sub.add_parser("stats", help="KPI report (time, cost, success rate) from the database")
    stats.add_argument("--json", action="store_true")
    stats.set_defaults(func=cmd_stats)

    image_models = sub.add_parser("image-models", help="image model ids in ProxyAPI")
    image_models.set_defaults(func=cmd_image_models)

    smoke_image = sub.add_parser("smoke-image", help="one test image: size, time, tokens, cost")
    smoke_image.add_argument("--provider", choices=("proxyapi", "fal"), default=None)
    smoke_image.add_argument("--model", default=None, help="override the configured model id")
    smoke_image.add_argument("--format", default="9:16", choices=FORMATS)
    smoke_image.add_argument("--out", default="smoke-image.png")
    smoke_image.add_argument(
        "--prompt",
        default="a small red fox sitting on a hill at sunrise, watercolor painting, "
        "vertical composition, no text",
    )
    smoke_image.set_defaults(func=cmd_smoke_image)

    music = sub.add_parser("music", help="list the background music library")
    music.set_defaults(func=cmd_music)

    compose = sub.add_parser("compose", help="render video from existing images + narration")
    compose.add_argument("--storyboard", required=True)
    compose.add_argument("--images", required=True, help="dir with scene_XX.png")
    compose.add_argument("--narration", required=True, help="narration.json from `tts`")
    compose.add_argument("--format", default="9:16", choices=FORMATS)
    compose.add_argument("--seed", type=int, default=42, help="seed for the automatic music pick")
    compose.add_argument("--draft", action="store_true", help="fast 480p preview")
    _add_music_and_branding_args(compose)
    compose.add_argument("--out-dir", default="out")
    compose.set_defaults(func=cmd_compose)

    render = sub.add_parser("render", help="full pipeline: script file -> MP4")
    render.add_argument("script")
    render.add_argument("--style", default="realism", choices=sorted(load_style_presets()))
    render.add_argument("--format", default="9:16", choices=FORMATS)
    render.add_argument("--voice", default=get_settings().tts_voice, choices=sorted(VOICES))
    render.add_argument("--seed", type=int, default=42)
    _add_music_and_branding_args(render)
    render.add_argument("--out-dir", default="out")
    render.add_argument("--no-cache", action="store_true")
    render.set_defaults(func=cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
