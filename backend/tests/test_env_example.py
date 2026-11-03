"""`.env.example` is read by python-dotenv (pydantic-settings) and by docker compose."""

import re
from pathlib import Path

from dotenv import dotenv_values

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def test_no_inline_comments_after_values():
    # compose and python-dotenv disagree about `KEY=   # comment`: keep comments on own lines
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            assert not re.search(r"\s#", line), f"inline comment: {line}"


def test_secrets_are_empty_and_every_key_is_a_known_setting():
    values = dotenv_values(ENV_EXAMPLE)
    assert values["PROXYAPI_KEY"] == "" and values["FAL_KEY"] == ""
    known = {name.upper() for name in Settings.model_fields} | {"POSTGRES_PASSWORD", "DOMAIN"}
    unknown = set(values) - known
    assert not unknown, f"keys without a setting in app/config.py: {unknown}"


def test_example_loads_into_settings(monkeypatch):
    for key, value in dotenv_values(ENV_EXAMPLE).items():
        monkeypatch.setenv(key, value or "")
    settings = Settings(_env_file=None)
    assert settings.proxyapi_key == "" and settings.storage_ttl_days == 7
    assert settings.ffmpeg_upscale == 2.0 and settings.auto_migrate is True


def test_example_models_are_the_defaults_and_are_priced():
    """Model ids must carry the vendor prefix (ProxyAPI catalog) and have a price."""
    from app.services.images.pricing import PRICES_RUB_PER_1M as IMAGE_PRICES
    from app.services.llm.pricing import PRICES_RUB_PER_1M as LLM_PRICES

    values, defaults = dotenv_values(ENV_EXAMPLE), Settings()
    assert values["LLM_MODEL"] == defaults.llm_model in LLM_PRICES
    assert values["LLM_FALLBACK_MODEL"] == defaults.llm_fallback_model in LLM_PRICES
    assert values["PROXYAPI_IMAGE_MODEL"] == defaults.proxyapi_image_model in IMAGE_PRICES
    assert values["PROXYAPI_IMAGE_SIZES"] == defaults.proxyapi_image_sizes
    assert values["IMAGE_PROVIDER"] == defaults.image_provider == "proxyapi"
    for model in (defaults.llm_model, defaults.llm_fallback_model, defaults.proxyapi_image_model):
        assert "/" in model, f"{model}: ProxyAPI ids have a vendor prefix"
