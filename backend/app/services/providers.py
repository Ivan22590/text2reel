"""Factories for external providers used by background jobs.

Tests replace them via `overrides` (no network, no paid calls).
"""

from collections.abc import Callable

from app.config import get_settings
from app.services.images import ImageProvider, get_provider
from app.services.llm.client import LLMClient
from app.services.tts import EdgeTTSEngine, TTSEngine

overrides: dict[str, Callable[[], object]] = {}


def llm() -> LLMClient:
    return overrides["llm"]() if "llm" in overrides else LLMClient(get_settings())


def image_provider() -> ImageProvider:
    if "image_provider" in overrides:
        return overrides["image_provider"]()
    return get_provider(get_settings())


def tts_engine() -> TTSEngine:
    return overrides["tts_engine"]() if "tts_engine" in overrides else EdgeTTSEngine()
