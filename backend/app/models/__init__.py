"""Data model, see docs/ARCHITECTURE.md §3."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class ProjectStatus(StrEnum):
    draft = "draft"
    analyzing = "analyzing"
    scenes_ready = "scenes_ready"
    generating = "generating"
    assets_ready = "assets_ready"
    rendering = "rendering"
    done = "done"
    failed = "failed"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    script: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="ru")
    style: Mapped[str] = mapped_column(String(32), default="realism")
    format: Mapped[str] = mapped_column(String(8), default="9:16")
    voice: Mapped[str] = mapped_column(String(64), default="ru-RU-SvetlanaNeural")
    music_track_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branding_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=ProjectStatus.draft)
    style_bible: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    # Progress of the running job, polled by the SSE endpoint.
    step: Mapped[str] = mapped_column(String(32), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_rub: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    scenes: Mapped[list["Scene"]] = relationship(
        back_populates="project", order_by="Scene.index", cascade="all, delete-orphan"
    )
    render_jobs: Mapped[list["RenderJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    index: Mapped[int] = mapped_column(Integer)
    narration: Mapped[str] = mapped_column(Text)
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    mood: Mapped[str] = mapped_column(String(16), default="calm")
    camera: Mapped[str] = mapped_column(String(16), default="zoom_in")
    image_seed: Mapped[int] = mapped_column(Integer, default=0)  # +1 on every regeneration
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    words_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="scenes")


class RenderJob(Base):
    __tablename__ = "render_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    format: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    step: Mapped[str] = mapped_column(String(32), default="")
    output_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    srt_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    images_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_rub: Mapped[float] = mapped_column(Float, default=0.0)

    project: Mapped[Project] = relationship(back_populates="render_jobs")
