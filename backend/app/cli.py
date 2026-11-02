"""Command-line tools.

python -m app.cli llm-models [--filter haiku]    # list model ids available in ProxyAPI
python -m app.cli smoke-llm                      # one cheap request to primary + fallback
python -m app.cli scenes script.txt --style anime --format 9:16
"""

import argparse
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.prompts.loader import load_prompt
from app.services.llm.client import LLMClient, LLMError
from app.services.scenes import FORMATS, split_script
from app.services.styles import load_style_presets


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
