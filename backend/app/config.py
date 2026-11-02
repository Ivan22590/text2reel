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
    fal_cost_usd_per_mp: float = 0.003
    proxyapi_image_model: str = ""
    proxyapi_image_cost_rub: float = 0.0  # per image, fill in after the stage 2 comparison
    image_concurrency: int = 4
    image_timeout_sec: int = 90
    image_fit: str = "cover"  # cover | blur
    usd_rub: float = 100.0  # for cost reporting of USD-priced providers

    tts_provider: str = "edge"
    tts_voice: str = "ru-RU-SvetlanaNeural"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"
    tts_scene_pause_sec: float = 0.4  # silence between scenes (FR-3.3)
    tts_concurrency: int = 4

    redis_url: str = "redis://redis:6379/0"
    database_url: str = "sqlite:///./storage/app.db"
    storage_dir: Path = Path("./storage")
    storage_ttl_days: int = 7
    render_concurrency: int = 2
    ffmpeg_preset: str = "veryfast"
    render_fps: int = 30

    # Run Celery tasks inline (no broker); used in tests.
    celery_eager: bool = False

    prompts_dir: Path = BACKEND_DIR / "prompts"
    assets_dir: Path = BACKEND_DIR / "assets"  # music/, fonts/
    templates_dir: Path = BACKEND_DIR / "templates"


@lru_cache
def get_settings() -> Settings:
    return Settings()
