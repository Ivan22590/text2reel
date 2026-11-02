from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """App settings loaded from environment / `.env` (see `.env.example`)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: str = "dev"
    secret_key: str = "change-me"
    demo_user: str = "demo"
    demo_password: str = "change-me"
    demo_max_projects_per_day: int = 20

    proxyapi_key: str = ""
    proxyapi_base_url: str = "https://api.proxyapi.ru/v1"
    llm_model: str = "claude-haiku-5-5"
    llm_fallback_model: str = "deepseek-v4.1-flash"
    llm_timeout_sec: int = 60

    image_provider: str = "fal"
    fal_key: str = ""
    fal_model: str = "fal-ai/flux/schnell"
    proxyapi_image_model: str = ""
    image_concurrency: int = 4

    tts_provider: str = "edge"
    tts_voice: str = "ru-RU-SvetlanaNeural"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"

    redis_url: str = "redis://redis:6379/0"
    database_url: str = "sqlite:///./storage/app.db"
    storage_dir: Path = Path("./storage")
    storage_ttl_days: int = 7
    render_concurrency: int = 2
    ffmpeg_preset: str = "veryfast"

    # Run Celery tasks inline (no broker); used in tests.
    celery_eager: bool = False

    prompts_dir: Path = BACKEND_DIR / "prompts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
