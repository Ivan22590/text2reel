from fastapi import APIRouter

from app import __version__
from app.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "env": settings.app_env,
        "llm_model": settings.llm_model,
        "image_provider": settings.image_provider,
    }
