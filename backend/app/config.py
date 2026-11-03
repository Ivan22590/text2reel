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
    # ProxyAPI ids carry the vendor prefix (https://proxyapi.ru/models/browse).
    llm_model: str = "anthropic/claude-haiku-5-5"
    llm_fallback_model: str = "deepseek/deepseek-v4.1-flash"
    llm_timeout_sec: int = 60

    image_provider: str = "proxyapi"  # proxyapi | fal
    fal_key: str = ""
    fal_model: str = "fal-ai/flux/schnell"
    fal_cost_usd_per_mp: float = 0.003
    # ProxyAPI Images API (docs/MODELS_AND_COSTS.md §3). FLUX 3 Image Klein is the cheapest
    # non-preview model of the catalog; `python -m app.cli image-models` lists the others.
    proxyapi_image_model: str = "black-forest-labs/flux-3-image-klein"
    # Sizes to try, best aspect-ratio match first; a size the model refuses is dropped. The
    # catalog does not say which sizes a model accepts. OpenAI-style models take the last three.
    proxyapi_image_sizes: str = "768x1344,1344x768,1024x1024,1024x1536,1536x1024"
    proxyapi_image_quality: str = (
        ""  # low | medium | high for OpenAI-style models; empty = not sent
    )
    proxyapi_image_negative: str = "ignore"  # ignore | append ("Avoid: ..." added to the prompt)
    proxyapi_image_send_seed: bool = False  # `seed` is undocumented: off, a 400 is likely
    # Rubles per 1M tokens. 0 = take the model's price from the table in
    # app/services/images/pricing.py; set both only for a model that is not in the table.
    proxyapi_image_price_in_rub: float = 0.0
    proxyapi_image_price_out_rub: float = 0.0
    proxyapi_image_cost_rub: float = 0.0  # flat per image, used when the response has no usage
    image_concurrency: int = 4
    image_timeout_sec: int = 120
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
    storage_ttl_days: int = 7  # 0 turns the cleanup off (e.g. while the demo must stay)
    auto_migrate: bool = True  # api applies migrations at start; off in prod (`migrate` service)
    render_concurrency: int = 2
    ffmpeg_preset: str = "veryfast"  # final encode (xfade + subtitles + mux)
    ffmpeg_crf: int = 21
    # Per-scene Ken Burns clips are re-encoded in the final pass, so a fast preset with a low
    # crf costs almost no quality (SSIM 0.986) and saves ~20% of the render time
    # (docs/METRICS.md, benchmark workflow).
    ffmpeg_clip_preset: str = "ultrafast"
    ffmpeg_clip_crf: int = 18
    ffmpeg_upscale: float = 2.0  # zoompan works on frames upscaled by this factor
    render_fps: int = 30

    # Run Celery tasks inline (no broker); used in tests.
    celery_eager: bool = False

    prompts_dir: Path = BACKEND_DIR / "prompts"
    assets_dir: Path = BACKEND_DIR / "assets"  # music/, fonts/
    templates_dir: Path = BACKEND_DIR / "templates"


@lru_cache
def get_settings() -> Settings:
    return Settings()
