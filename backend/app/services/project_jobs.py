"""Project-level jobs on top of the stage 1–4 services, run by Celery workers.

Files live in `storage/projects/{id}/` (images/, audio/, renders/{job_id}/). Progress of
the running job is stored on the Project row (step, progress, message); the SSE endpoint
polls it, so no extra message bus is needed.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Project, ProjectStatus, RenderJob, Scene
from app.services import providers
from app.services.compositor import RenderScene, compute_timeline, render_video
from app.services.images.generator import generate_scene_image
from app.services.images.prompting import build_prompts
from app.services.scenes import (
    SceneDraft,
    Storyboard,
    StyleBible,
    regenerate_visual_prompt,
    split_script,
)
from app.services.styles import get_style
from app.services.subtitles import STYLE_DEFAULTS, build_cues, place_on_timeline
from app.services.tts import Word, synthesize_scene

log = logging.getLogger(__name__)

RUNNING = {ProjectStatus.analyzing, ProjectStatus.generating, ProjectStatus.rendering}


class JobError(RuntimeError):
    pass


def project_dir(project_id: int) -> Path:
    return get_settings().storage_dir / "projects" / str(project_id)


def _cache(name: str) -> Path:
    return get_settings().storage_dir / "cache" / name


def set_progress(
    db: Session, project: Project, step: str, percent: float, message: str, status: str = ""
) -> None:
    project.step, project.progress, project.message = step, round(percent, 1), message
    if status:
        project.status = status
    db.commit()


def _fail(db: Session, project: Project, error: str, status: str) -> None:
    project.error = error
    set_progress(db, project, project.step, project.progress, "Ошибка", status)


def _storyboard(project: Project, scenes: list[Scene] | None = None) -> Storyboard:
    scenes = project.scenes if scenes is None else scenes
    return Storyboard(
        style_bible=StyleBible.model_validate(project.style_bible or {}),
        scenes=[
            SceneDraft(
                narration=s.narration, visual_prompt=s.visual_prompt, mood=s.mood, camera=s.camera
            )
            for s in scenes
        ],
    )


# --- Stage 1 -----------------------------------------------------------------------------


def analyze_project(db: Session, project_id: int) -> None:
    project = db.get(Project, project_id)
    project.error = None
    set_progress(db, project, "scenes", 2, "Разбиваем сценарий на сцены", ProjectStatus.analyzing)
    try:
        result = split_script(
            project.script, style=project.style, format=project.format,
            llm=providers.llm(), cache_dir=_cache("llm"),
        )  # fmt: skip
    except Exception as exc:  # LLM down, invalid answers, bad input
        log.exception("analyze failed for project %s", project_id)
        _fail(db, project, f"Не удалось разбить сценарий: {exc}", ProjectStatus.draft)
        return

    project.scenes.clear()
    db.flush()
    for i, draft in enumerate(result.storyboard.scenes):
        project.scenes.append(
            Scene(
                index=i, narration=draft.narration, visual_prompt=draft.visual_prompt,
                mood=draft.mood, camera=draft.camera,
            )
        )  # fmt: skip
    project.style_bible = result.storyboard.style_bible.model_dump()
    project.cost_rub += result.usage.cost_rub
    count = len(result.storyboard.scenes)
    set_progress(db, project, "scenes", 100, f"Сцен: {count}", ProjectStatus.scenes_ready)


# --- Stages 2–3 --------------------------------------------------------------------------


def _generate_image(project: Project, scene: Scene, provider) -> str | None:
    prompts, negative = build_prompts(_storyboard(project, [scene]), get_style(project.style))
    result = generate_scene_image(
        scene.index, prompts[0], negative_prompt=negative, format=project.format,
        seed=project.seed + scene.image_seed, out_dir=project_dir(project.id) / "images",
        provider=provider, cache_dir=_cache("images"), fit=get_settings().image_fit,
    )  # fmt: skip
    if not result.ok:
        return result.error
    scene.image_path = str(result.path)
    project.cost_rub += result.cost_rub
    return None


def _generate_audio(project: Project, scene: Scene, engine) -> str | None:
    settings = get_settings()
    result = synthesize_scene(
        scene.index, scene.narration, voice=project.voice, rate=settings.tts_rate,
        pitch=settings.tts_pitch, out_dir=project_dir(project.id) / "audio",
        engine=engine, cache_dir=_cache("tts"),
    )  # fmt: skip
    if not result.ok:
        return result.error
    scene.audio_path = str(result.path)
    scene.duration_sec = result.duration
    scene.words_json = [w.__dict__ for w in result.words]
    return None


def generate_assets(db: Session, project_id: int, scene_ids: list[int] | None = None) -> None:
    """Images and/or narration for scenes that miss them (optionally only `scene_ids`)."""
    project = db.get(Project, project_id)
    project.error = None
    targets = [
        s for s in project.scenes
        if (not scene_ids or s.id in scene_ids) and not (s.image_path and s.audio_path)
    ]  # fmt: skip
    set_progress(db, project, "images", 0, "Готовим сцены", ProjectStatus.generating)
    provider, engine = providers.image_provider(), providers.tts_engine()
    failed = []
    for n, scene in enumerate(targets, start=1):
        set_progress(db, project, "images", 100 * (n - 1) / len(targets),
                     f"Сцена {scene.index + 1} из {len(project.scenes)}")  # fmt: skip
        # Only what is missing: regenerate_scene() clears exactly the parts to redo.
        errors = []
        if not scene.image_path:
            errors.append(_generate_image(project, scene, provider))
        if not scene.audio_path:
            errors.append(_generate_audio(project, scene, engine))
        errors = [e for e in errors if e]
        scene.error = "; ".join(errors) or None
        scene.status = "failed" if errors else "ready"
        if errors:
            failed.append(f"сцена {scene.index + 1}: {scene.error}")
        db.commit()

    if failed:
        _fail(db, project, "Не все сцены готовы — " + "; ".join(failed), ProjectStatus.scenes_ready)
    else:
        set_progress(db, project, "images", 100, "Сцены готовы", ProjectStatus.assets_ready)


def regenerate_scene(db: Session, scene_id: int, target: str, hint: str = "") -> None:
    """target: image | audio | all. For images a new seed is used; with `hint` the LLM
    writes a new visual prompt first."""
    scene = db.get(Scene, scene_id)
    project = scene.project
    if target in ("image", "all"):
        scene.image_seed += 1
        if hint:
            try:
                scene.visual_prompt, usage = regenerate_visual_prompt(
                    StyleBible.model_validate(project.style_bible or {}), scene.narration,
                    scene.visual_prompt, hint=hint, llm=providers.llm(),
                )  # fmt: skip
                project.cost_rub += usage.cost_rub
            except Exception as exc:
                _fail(db, project, f"Не удалось обновить промпт: {exc}", project.status)
                return
        scene.image_path = None
    if target in ("audio", "all"):
        scene.audio_path = None
    db.commit()
    generate_assets(db, project.id, scene_ids=[scene.id])


# --- Stage 4 -----------------------------------------------------------------------------


def _render_scenes(project: Project) -> list[RenderScene]:
    missing = [s.index + 1 for s in project.scenes if not (s.image_path and s.audio_path)]
    if missing or not project.scenes:
        raise JobError(f"нет картинки или озвучки у сцен: {missing}")
    return [
        RenderScene(
            Path(s.image_path), Path(s.audio_path), s.duration_sec or 0.0,
            [Word(**w) for w in s.words_json or []], s.narration, s.camera,
        )
        for s in project.scenes
    ]  # fmt: skip


def render_project(db: Session, job_id: int, size: tuple[int, int] | None = None) -> None:
    settings = get_settings()
    job = db.get(RenderJob, job_id)
    project = job.project
    project.error = None
    job.status, job.started_at = "running", datetime.now(UTC)
    set_progress(db, project, "render", 5, "Монтируем видео", ProjectStatus.rendering)
    try:
        scenes = _render_scenes(project)
        result = render_video(
            scenes, project_dir(project.id) / "renders" / str(job.id), job.format, size=size,
            music_volume=settings.music_volume, transition_sec=settings.transition_sec,
            pause=settings.tts_scene_pause_sec, fps=settings.render_fps,
            preset=settings.ffmpeg_preset, concurrency=settings.render_concurrency,
        )  # fmt: skip
    except Exception as exc:
        log.exception("render job %s failed", job_id)
        job.status, job.error, job.finished_at = "failed", str(exc), datetime.now(UTC)
        _fail(db, project, f"Ошибка монтажа: {exc}", ProjectStatus.assets_ready)
        return
    job.status, job.progress, job.finished_at = "done", 100.0, datetime.now(UTC)
    job.output_path, job.srt_path = str(result.video), str(result.srt)
    job.images_count = len(scenes)
    job.cost_rub = project.cost_rub
    set_progress(db, project, "render", 100, "Видео готово", ProjectStatus.done)


# --- Timeline preview (FR-5.3) -----------------------------------------------------------


def build_timeline(project: Project) -> dict:
    """Scene/narration/subtitle tracks as the compositor will lay them out."""
    settings = get_settings()
    scenes = project.scenes
    durations = [s.duration_sec or 0.0 for s in scenes]
    if not scenes or not all(durations):
        return {"ready": False, "total": 0.0, "scenes": [], "cues": []}
    timeline = compute_timeline(durations, settings.tts_scene_pause_sec, settings.transition_sec)
    words = place_on_timeline(
        [
            (start, [Word(**w) for w in s.words_json or []], s.narration)
            for start, s in zip(timeline.starts, scenes, strict=True)
        ]
    )
    cues = build_cues(words, max_chars=STYLE_DEFAULTS[project.format].max_chars)
    return {
        "ready": True,
        "total": timeline.total,
        "transition": settings.transition_sec,
        "scenes": [
            {"id": s.id, "index": s.index, "start": start, "clip": clip, "voice": s.duration_sec}
            for s, start, clip in zip(scenes, timeline.starts, timeline.clip_durations, strict=True)
        ],
        "cues": [{"start": c.start, "end": c.end, "text": c.text} for c in cues],
    }
