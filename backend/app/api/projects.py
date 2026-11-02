"""Projects, scenes, jobs, progress (SSE) and files. See docs/ARCHITECTURE.md §4."""

import asyncio
import io
import json
import random
import re
import zipfile
from datetime import UTC, datetime, time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas
from app.api.auth import require_user
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import Project, ProjectStatus, RenderJob, Scene
from app.services.compositor import DEFAULT_TRANSITIONS
from app.services.project_jobs import RUNNING, build_timeline
from app.services.scenes import CAMERAS
from app.services.styles import load_style_presets
from app.services.tts import VOICES
from app.workers import tasks

router = APIRouter(dependencies=[Depends(require_user)])

MAX_UPLOAD_BYTES = 1_000_000


def _project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Проект не найден")
    return project


def _scene(db: Session, scene_id: int) -> Scene:
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Сцена не найдена")
    return scene


def _ensure_idle(project: Project) -> None:
    if project.status in RUNNING:
        raise HTTPException(409, "Проект уже обрабатывается, дождитесь окончания")


def _validate_choices(style: str | None, voice: str | None) -> None:
    if style is not None and style not in load_style_presets():
        raise HTTPException(422, f"Неизвестный стиль: {style}")
    if voice is not None and voice not in VOICES:
        raise HTTPException(422, f"Неизвестный голос: {voice}")


# --- Reference data ----------------------------------------------------------------------


@router.get("/meta")
def meta() -> dict:
    return {
        "styles": [{"id": p.id, "name": p.name} for p in load_style_presets().values()],
        "formats": [
            {"id": "9:16", "name": "Shorts / Reels / TikTok"},
            {"id": "16:9", "name": "YouTube"},
            {"id": "1:1", "name": "Instagram"},
        ],
        "voices": [{"id": k, "name": v} for k, v in VOICES.items()],
        "cameras": list(CAMERAS),
        "transitions": DEFAULT_TRANSITIONS,
    }


@router.post("/scripts/parse")
async def parse_script(file: UploadFile = File(...)) -> dict:
    """Extracts text from an uploaded .txt or .docx file (FR-5.1)."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Файл больше 1 МБ")
    name = (file.filename or "").lower()
    if name.endswith(".txt"):
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                return {"text": data.decode(encoding).strip()}
            except UnicodeDecodeError:
                continue
        raise HTTPException(422, "Не удалось определить кодировку файла")
    if name.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as docx:
                xml = docx.read("word/document.xml").decode("utf-8")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise HTTPException(422, "Файл .docx повреждён") from exc
        paragraphs = [
            "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
            for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.DOTALL)
        ]
        text = "\n".join(p for p in paragraphs if p.strip())
        return {"text": text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")}
    raise HTTPException(415, "Поддерживаются файлы .txt и .docx")


# --- Projects ----------------------------------------------------------------------------


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)) -> list[schemas.ProjectOut]:
    projects = db.scalars(select(Project).order_by(Project.id.desc())).all()
    return [schemas.project_out(p, with_details=False) for p in projects]


@router.post("/projects", status_code=201)
def create_project(body: schemas.ProjectCreate, db: Session = Depends(get_db)):
    _validate_choices(body.style, body.voice)
    today = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    created_today = db.scalar(select(func.count(Project.id)).where(Project.created_at >= today))
    if created_today >= get_settings().demo_max_projects_per_day:
        raise HTTPException(429, "Достигнут дневной лимит проектов демо-доступа")
    title = body.title or body.script.strip().split("\n")[0][:60]
    project = Project(
        title=title, script=body.script.strip(), style=body.style, format=body.format,
        voice=body.voice, seed=random.randint(1, 2**31 - 1),
    )  # fmt: skip
    db.add(project)
    db.commit()
    return schemas.project_out(project)


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)) -> schemas.ProjectOut:
    return schemas.project_out(_project(db, project_id))


@router.patch("/projects/{project_id}")
def update_project(
    project_id: int, body: schemas.ProjectUpdate, db: Session = Depends(get_db)
) -> schemas.ProjectOut:
    project = _project(db, project_id)
    _ensure_idle(project)
    _validate_choices(body.style, body.voice)
    changes = body.model_dump(exclude_none=True)
    if "script" in changes and changes["script"] != project.script:
        project.scenes.clear()  # scenes no longer match the text
        project.status = ProjectStatus.draft
    for scene in project.scenes:
        # Frames are generated for a style and an aspect ratio; narration depends on the voice.
        if any(k in changes and changes[k] != getattr(project, k) for k in ("style", "format")):
            scene.image_path = None
        if "voice" in changes and changes["voice"] != project.voice:
            scene.audio_path = None
    for key, value in changes.items():
        setattr(project, key, value)
    if project.scenes and any(not (s.image_path and s.audio_path) for s in project.scenes):
        project.status = ProjectStatus.scenes_ready
    db.commit()
    return schemas.project_out(project)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> None:
    project = _project(db, project_id)
    _ensure_idle(project)
    db.delete(project)
    db.commit()


@router.post("/projects/{project_id}/analyze", status_code=202)
def analyze(project_id: int, db: Session = Depends(get_db)) -> schemas.ProjectOut:
    project = _project(db, project_id)
    _ensure_idle(project)
    project.status, project.step, project.progress = ProjectStatus.analyzing, "scenes", 0
    db.commit()
    tasks.analyze.delay(project_id)
    db.expire_all()  # an eager (inline) task may have changed scenes in another session
    return schemas.project_out(project)


@router.post("/projects/{project_id}/generate", status_code=202)
def generate(project_id: int, db: Session = Depends(get_db)) -> schemas.ProjectOut:
    project = _project(db, project_id)
    _ensure_idle(project)
    if not project.scenes:
        raise HTTPException(409, "Сначала разбейте сценарий на сцены")
    project.status, project.step, project.progress = ProjectStatus.generating, "images", 0
    db.commit()
    tasks.generate.delay(project_id)
    db.expire_all()  # an eager (inline) task may have changed scenes in another session
    return schemas.project_out(project)


@router.post("/projects/{project_id}/render", status_code=202)
def render(
    project_id: int, body: schemas.RenderRequest, db: Session = Depends(get_db)
) -> schemas.RenderJobOut:
    project = _project(db, project_id)
    _ensure_idle(project)
    if not project.scenes or any(not (s.image_path and s.audio_path) for s in project.scenes):
        raise HTTPException(409, "Не у всех сцен есть картинка и озвучка")
    if body.format and body.format != project.format:
        raise HTTPException(409, "Смените формат проекта и перегенерируйте кадры")
    job = RenderJob(project_id=project.id, format=project.format)
    db.add(job)
    project.status, project.step, project.progress = ProjectStatus.rendering, "render", 0
    db.commit()
    tasks.render.delay(job.id)
    db.expire_all()
    return schemas.job_out(job)


@router.get("/projects/{project_id}/timeline")
def timeline(project_id: int, db: Session = Depends(get_db)) -> dict:
    project = _project(db, project_id)
    data = build_timeline(project)
    by_id = {s.id: s for s in project.scenes}
    for item in data["scenes"]:
        scene = by_id[item["id"]]
        item["image_url"] = schemas.file_url(scene.image_path)
        item["narration"] = scene.narration
    return data


@router.get("/projects/{project_id}/events")
async def events(project_id: int) -> StreamingResponse:
    """Server-Sent Events with job progress (FR-5.4). Polls the project row until the job
    is no longer running."""

    def snapshot() -> dict | None:
        with SessionLocal() as db:
            project = db.get(Project, project_id)
            if project is None:
                return None
            return {
                "status": project.status, "step": project.step, "progress": project.progress,
                "message": project.message, "error": project.error,
            }  # fmt: skip

    async def stream():
        last = None
        for _ in range(int(20 * 60 / 0.7)):  # 20 minutes max
            state = await asyncio.to_thread(snapshot)
            if state is None:
                yield "event: error\ndata: {}\n\n"
                return
            if state != last:
                yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
                last = state
            if state["status"] not in RUNNING:
                return
            await asyncio.sleep(0.7)

    return StreamingResponse(stream(), media_type="text/event-stream")


# --- Scenes ------------------------------------------------------------------------------


@router.patch("/scenes/{scene_id}")
def update_scene(
    scene_id: int, body: schemas.SceneUpdate, db: Session = Depends(get_db)
) -> schemas.SceneOut:
    scene = _scene(db, scene_id)
    _ensure_idle(scene.project)
    if body.narration is not None and body.narration != scene.narration:
        scene.narration, scene.audio_path = body.narration.strip(), None
    if body.visual_prompt is not None and body.visual_prompt != scene.visual_prompt:
        scene.visual_prompt, scene.image_path = body.visual_prompt.strip(), None
    if body.camera is not None:
        if body.camera not in CAMERAS:
            raise HTTPException(422, f"Неизвестная камера: {body.camera}")
        scene.camera = body.camera
    if not (scene.image_path and scene.audio_path):
        scene.status = "pending"
        scene.project.status = ProjectStatus.scenes_ready
    db.commit()
    return schemas.scene_out(scene)


@router.post("/scenes/{scene_id}/regenerate", status_code=202)
def regenerate(
    scene_id: int, body: schemas.RegenerateRequest, db: Session = Depends(get_db)
) -> schemas.ProjectOut:
    scene = _scene(db, scene_id)
    project = scene.project
    _ensure_idle(project)
    project.status, project.step, project.progress = ProjectStatus.generating, "images", 0
    db.commit()
    tasks.regenerate_scene.delay(scene_id, body.target, body.hint)
    db.expire_all()  # an eager (inline) task may have changed scenes in another session
    return schemas.project_out(project)


# --- Files -------------------------------------------------------------------------------


@router.get("/files/{path:path}")
def files(path: str) -> FileResponse:
    """Serves images, audio and video from storage (Range requests are supported)."""
    root = get_settings().storage_dir.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file() or "cache" in target.parts:
        raise HTTPException(404, "Файл не найден")
    return FileResponse(target)
