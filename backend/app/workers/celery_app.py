"""Celery app with two queues: `ai` (LLM, images, TTS) and `render` (FFmpeg).

See docs/ARCHITECTURE.md §1–2.
"""

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "text2reel",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_default_queue="ai",
    task_routes={
        "app.workers.tasks.ai.*": {"queue": "ai"},
        "app.workers.tasks.render.*": {"queue": "render"},
    },
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=settings.celery_eager,
    task_eager_propagates=True,
)


@celery_app.task(name="app.workers.tasks.ai.ping")
def ping() -> str:
    return "pong"
