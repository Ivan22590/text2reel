"""End-to-end pipeline: script → scenes → images → narration → video (stages 1–4).

Every step is cached by input hash, so re-running after a failure only pays for what
is missing. Progress is reported through `on_progress(step, percent, message)`; the
Celery worker (stage 5) forwards it to the UI.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import Settings, get_settings
from app.services.branding import Branding
from app.services.cards import build_card_scenes
from app.services.compositor import RenderScene, render_video
from app.services.images import ImageProvider, get_provider
from app.services.images.crop import OUTPUT_SIZES
from app.services.images.generator import generate_images
from app.services.images.prompting import build_prompts
from app.services.llm.client import LLMClient
from app.services.music import resolve_music
from app.services.scenes import Storyboard, split_script
from app.services.styles import get_style
from app.services.templates import get_template
from app.services.tts import TTSEngine, probe_duration, synthesize_scenes, write_manifest

ProgressFn = Callable[[str, float, str], None]

# Share of total progress per step: (start %, end %).
PROGRESS = {"scenes": (0, 10), "images": (10, 50), "tts": (50, 60), "render": (60, 100)}


class PipelineError(RuntimeError):
    pass


@dataclass
class StepReport:
    name: str
    seconds: float
    cost_rub: float = 0.0
    detail: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    video: Path
    srt: Path
    duration: float
    storyboard: Storyboard
    steps: list[StepReport]
    report: Path

    @property
    def cost_rub(self) -> float:
        return sum(step.cost_rub for step in self.steps)

    @property
    def seconds(self) -> float:
        return sum(step.seconds for step in self.steps)


def run_pipeline(
    script: str,
    *,
    style: str,
    format: str,
    voice: str,
    out_dir: Path,
    seed: int = 42,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    image_provider: ImageProvider | None = None,
    tts_engine: TTSEngine | None = None,
    music: str | Path | None = "auto",
    branding: Branding | None = None,
    logo: Path | None = None,
    size: tuple[int, int] | None = None,
    use_cache: bool = True,
    on_progress: ProgressFn | None = None,
    duration_fn: Callable[[Path], float] = probe_duration,
) -> PipelineResult:
    settings = settings or get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = settings.storage_dir / "cache" if use_cache else None
    steps: list[StepReport] = []

    def progress(step: str, fraction: float, message: str) -> None:
        if on_progress is not None:
            start, end = PROGRESS[step]
            on_progress(step, start + (end - start) * fraction, message)

    # 1. Scenes
    progress("scenes", 0, "Разбиваем сценарий на сцены")
    started = time.monotonic()
    split = split_script(
        script, style=style, format=format, llm=llm or LLMClient(settings),
        cache_dir=cache / "llm" if cache else None,
    )  # fmt: skip
    storyboard = split.storyboard
    (out_dir / "storyboard.json").write_text(storyboard.model_dump_json(indent=2), "utf-8")
    steps.append(
        StepReport(
            "scenes", time.monotonic() - started, split.usage.cost_rub,
            {"scenes": len(storyboard.scenes), "cached": split.cached,
             "tokens_in": split.usage.tokens_in, "tokens_out": split.usage.tokens_out},
        )
    )  # fmt: skip

    # 2. Images
    progress("images", 0, f"Генерируем {len(storyboard.scenes)} изображений")
    started = time.monotonic()
    prompts, negative = build_prompts(storyboard, get_style(style))
    images = generate_images(
        prompts, negative_prompt=negative, format=format, seed=seed,
        out_dir=out_dir / "images", provider=image_provider or get_provider(settings),
        cache_dir=cache / "images" if cache else None,
        concurrency=settings.image_concurrency, fit=settings.image_fit,
    )  # fmt: skip
    steps.append(
        StepReport(
            "images", time.monotonic() - started, sum(i.cost_rub for i in images),
            {"cached": sum(i.cached for i in images)},
        )
    )  # fmt: skip

    # 3. Narration
    progress("tts", 0, "Озвучиваем сцены")
    started = time.monotonic()
    narrations = synthesize_scenes(
        [scene.narration for scene in storyboard.scenes], voice=voice,
        rate=settings.tts_rate, pitch=settings.tts_pitch, out_dir=out_dir / "audio",
        engine=tts_engine, cache_dir=cache / "tts" if cache else None,
        concurrency=settings.tts_concurrency, duration_fn=duration_fn,
    )  # fmt: skip
    steps.append(StepReport("tts", time.monotonic() - started, 0.0))

    failed = [f"сцена {i.index + 1}: {i.error}" for i in images if not i.ok]
    failed += [f"сцена {n.index + 1}: {n.error}" for n in narrations if not n.ok]
    if failed:
        _write_report(out_dir, steps, error="; ".join(failed))
        raise PipelineError("не удалось подготовить сцены — " + "; ".join(failed))
    write_manifest(narrations, out_dir / "audio" / "narration.json")

    # 4. Render
    progress("render", 0, "Монтируем видео")
    started = time.monotonic()
    template = get_template(format)
    branding = branding or Branding()
    if isinstance(music, Path):  # an explicit file
        music_file = music
    else:  # `auto`, `none` or a library track id
        moods = [
            (sc.mood, nar.duration) for sc, nar in zip(storyboard.scenes, narrations, strict=True)
        ]
        track = resolve_music(music, moods, seed)
        music_file = track.path if track else None
    scenes = [
        RenderScene(img.path, nar.path, nar.duration, nar.words, sc.narration, sc.camera)
        for img, nar, sc in zip(images, narrations, storyboard.scenes, strict=True)
    ]
    intro, outro = build_card_scenes(
        branding, template, size or OUTPUT_SIZES[format], out_dir / "work", logo
    )
    rendered = render_video(
        scenes, out_dir, format, size=size, template=template, branding=branding, logo=logo,
        intro=intro, outro=outro, music=music_file, pause=settings.tts_scene_pause_sec,
        fps=settings.render_fps, preset=settings.ffmpeg_preset,
        concurrency=settings.render_concurrency,
    )  # fmt: skip
    steps.append(
        StepReport(
            "render", time.monotonic() - started, 0.0,
            {"duration": rendered.duration, "music": music_file.name if music_file else None,
             **rendered.timings},
        )
    )  # fmt: skip
    progress("render", 1, "Готово")

    report = _write_report(out_dir, steps, video=str(rendered.video), duration=rendered.duration)
    return PipelineResult(
        rendered.video, rendered.srt, rendered.duration, storyboard, steps, report
    )


def _write_report(out_dir: Path, steps: list[StepReport], **extra) -> Path:
    path = out_dir / "report.json"
    data = {
        **extra,
        "cost_rub": round(sum(s.cost_rub for s in steps), 4),
        "seconds": round(sum(s.seconds for s in steps), 2),
        "steps": [asdict(s) for s in steps],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
