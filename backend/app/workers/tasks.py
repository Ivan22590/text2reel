"""Celery tasks: thin wrappers over app.services.project_jobs.

Queues are chosen by name prefix (celery_app.py): `tasks.ai.*` → ai, `tasks.render.*` → render.
"""

from dataclasses import asdict

from app.db import SessionLocal
from app.services import project_jobs
from app.services.cleanup import cleanup_expired
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.ai.analyze")
def analyze(project_id: int) -> None:
    with SessionLocal() as db:
        project_jobs.analyze_project(db, project_id)


@celery_app.task(name="app.workers.tasks.ai.generate")
def generate(project_id: int, scene_ids: list[int] | None = None) -> None:
    with SessionLocal() as db:
        project_jobs.generate_assets(db, project_id, scene_ids)


@celery_app.task(name="app.workers.tasks.ai.regenerate_scene")
def regenerate_scene(scene_id: int, target: str, hint: str = "") -> None:
    with SessionLocal() as db:
        project_jobs.regenerate_scene(db, scene_id, target, hint)


@celery_app.task(name="app.workers.tasks.render.render")
def render(job_id: int, size: tuple[int, int] | None = None) -> None:
    with SessionLocal() as db:
        project_jobs.render_project(db, job_id, tuple(size) if size else None)


@celery_app.task(name="app.workers.tasks.ai.cleanup")
def cleanup() -> dict:
    """Daily housekeeping, scheduled by Celery beat (celery_app.py)."""
    with SessionLocal() as db:
        return asdict(cleanup_expired(db))
