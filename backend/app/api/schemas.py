from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.branding import Branding, logo_path
from app.services.project_jobs import project_branding, project_dir, project_music
from app.services.scenes import FORMATS, MAX_SCRIPT_CHARS

Format = Literal[FORMATS]


def file_url(path: str | None) -> str | None:
    """Public URL for a file under storage_dir, with an mtime-based cache buster."""
    if not path:
        return None
    file = Path(path)
    try:
        rel = file.resolve().relative_to(get_settings().storage_dir.resolve())
    except ValueError:
        return None
    version = int(file.stat().st_mtime) if file.exists() else 0
    return f"/api/files/{rel.as_posix()}?v={version}"


class ProjectCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    script: str = Field(min_length=1, max_length=MAX_SCRIPT_CHARS)
    style: str = "realism"
    format: Format = "9:16"
    voice: str = "ru-RU-SvetlanaNeural"
    music: str = "auto"  # auto | none | track id
    branding: Branding | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    script: str | None = Field(default=None, min_length=1, max_length=MAX_SCRIPT_CHARS)
    style: str | None = None
    format: Format | None = None
    voice: str | None = None
    music: str | None = None
    branding: Branding | None = None


class SceneUpdate(BaseModel):
    narration: str | None = Field(default=None, min_length=1, max_length=1000)
    visual_prompt: str | None = Field(default=None, min_length=10, max_length=1000)
    camera: str | None = None


class RegenerateRequest(BaseModel):
    target: Literal["image", "audio", "all"] = "image"
    hint: str = Field(default="", max_length=300)


class RenderRequest(BaseModel):
    format: Format | None = None
    draft: bool = False  # fast 480p preview


class SceneOut(BaseModel):
    id: int
    index: int
    narration: str
    visual_prompt: str
    mood: str
    camera: str
    status: str
    error: str | None
    duration: float | None
    image_url: str | None
    audio_url: str | None


class RenderJobOut(BaseModel):
    id: int
    format: str
    draft: bool
    status: str
    error: str | None
    video_url: str | None
    srt_url: str | None
    started_at: datetime | None
    finished_at: datetime | None
    cost_rub: float


class BrandingOut(Branding):
    has_logo: bool = False
    logo_url: str | None = None


class TrackBrief(BaseModel):
    id: str
    title: str
    artist: str


class ProjectOut(BaseModel):
    id: int
    title: str
    script: str
    style: str
    format: str
    voice: str
    music: str
    music_track: TrackBrief | None  # the track that will play (the pick in `auto` mode)
    branding: BrandingOut
    status: str
    step: str
    progress: float
    message: str
    error: str | None
    cost_rub: float
    created_at: datetime
    scenes: list[SceneOut] = []
    renders: list[RenderJobOut] = []


def scene_out(s) -> SceneOut:
    return SceneOut(
        id=s.id, index=s.index, narration=s.narration, visual_prompt=s.visual_prompt,
        mood=s.mood, camera=s.camera, status=s.status, error=s.error, duration=s.duration_sec,
        image_url=file_url(s.image_path), audio_url=file_url(s.audio_path),
    )  # fmt: skip


def job_out(j) -> RenderJobOut:
    return RenderJobOut(
        id=j.id, format=j.format, draft=j.draft, status=j.status, error=j.error,
        video_url=file_url(j.output_path), srt_url=file_url(j.srt_path),
        started_at=j.started_at, finished_at=j.finished_at, cost_rub=j.cost_rub,
    )  # fmt: skip


def branding_out(p) -> BrandingOut:
    logo = logo_path(project_dir(p.id))
    return BrandingOut(
        **project_branding(p).model_dump(),
        has_logo=logo.exists(),
        logo_url=file_url(str(logo)) if logo.exists() else None,
    )


def project_out(p, with_details: bool = True) -> ProjectOut:
    track = project_music(p) if p.scenes else None
    return ProjectOut(
        id=p.id, title=p.title, script=p.script, style=p.style, format=p.format, voice=p.voice,
        music=p.music_track_id or "auto",
        music_track=TrackBrief(id=track.id, title=track.title, artist=track.artist)
        if track else None,
        branding=branding_out(p),
        status=p.status, step=p.step, progress=p.progress, message=p.message, error=p.error,
        cost_rub=round(p.cost_rub, 2), created_at=p.created_at,
        scenes=[scene_out(s) for s in p.scenes] if with_details else [],
        renders=[job_out(j) for j in sorted(p.render_jobs, key=lambda j: -j.id)]
        if with_details else [],
    )  # fmt: skip
