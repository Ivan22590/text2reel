"""Storage housekeeping (FR-7.6): expired projects, old cache files, stuck jobs.

Run daily by Celery beat (workers/tasks.py::cleanup) or by hand: `python -m app.cli cleanup`.
"""

import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Project, ProjectStatus
from app.services.project_jobs import RUNNING, project_dir

log = logging.getLogger(__name__)

CACHE_DIRS = ("llm", "images", "tts")
STUCK_AFTER = timedelta(hours=2)  # a running job that did not touch its project for this long


@dataclass
class CleanupReport:
    projects: int = 0
    cache_files: int = 0
    freed_bytes: int = 0
    recovered: int = 0  # stuck jobs put back into a usable state


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def _recover_stuck(db: Session, now: datetime) -> int:
    """A worker that died mid-job leaves the project `running` forever (and every action
    answers 409). Put such projects back to the last stable state."""
    stuck = db.scalars(
        select(Project).where(
            Project.status.in_([s.value for s in RUNNING]), Project.updated_at < now - STUCK_AFTER
        )
    ).all()
    for project in stuck:
        if not project.scenes:
            project.status = ProjectStatus.draft
        elif all(s.image_path and s.audio_path for s in project.scenes):
            project.status = ProjectStatus.assets_ready
        else:
            project.status = ProjectStatus.scenes_ready
        project.error = "Задача прервана: сервер перезапускался или не отвечал. Запустите её снова."
        project.message = "Прервано"
        project.updated_at = now  # touched now: it must not be deleted in the same run
        for job in project.render_jobs:
            if job.status in ("queued", "running"):
                job.status, job.error, job.finished_at = "failed", "прервано", now
    return len(stuck)


def cleanup_expired(
    db: Session, *, ttl_days: int | None = None, now: datetime | None = None
) -> CleanupReport:
    settings = get_settings()
    ttl_days = settings.storage_ttl_days if ttl_days is None else ttl_days
    now = now or datetime.now(UTC)
    report = CleanupReport(recovered=_recover_stuck(db, now))
    if ttl_days <= 0:  # cleanup switched off
        db.commit()
        return report

    cutoff = now - timedelta(days=ttl_days)
    expired = db.scalars(
        select(Project).where(
            Project.updated_at < cutoff, Project.status.notin_([s.value for s in RUNNING])
        )
    ).all()
    for project in expired:
        directory = project_dir(project.id)
        report.freed_bytes += _dir_size(directory)
        shutil.rmtree(directory, ignore_errors=True)
        db.delete(project)
        report.projects += 1
    db.commit()

    for name in CACHE_DIRS:
        for file in (settings.storage_dir / "cache" / name).glob("*"):
            if file.is_file() and file.stat().st_mtime < cutoff.timestamp():
                report.freed_bytes += file.stat().st_size
                file.unlink()
                report.cache_files += 1
    log.info("cleanup: %s", report)
    return report
