import pytest

from app.config import Settings
from app.services.llm.client import LLMClient, LLMError
from app.services.llm.pricing import cost_rub
from tests.fakes import FakeOpenAI, connection_error

SETTINGS = Settings(
    proxyapi_key="test", llm_model="primary-model", llm_fallback_model="fallback-model"
)


def make_client(responses: dict) -> tuple[LLMClient, FakeOpenAI]:
    fake = FakeOpenAI(responses)
    return LLMClient(settings=SETTINGS, client=fake, sleep=lambda _: None), fake


def test_returns_content_and_usage():
    llm, fake = make_client({"primary-model": ['{"ok": true}']})
    result = llm.complete([{"role": "user", "content": "hi"}])
    assert result.content == '{"ok": true}'
    assert (result.usage.tokens_in, result.usage.tokens_out) == (100, 200)
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_retries_network_errors_then_succeeds():
    llm, fake = make_client({"primary-model": [connection_error(), connection_error(), "{}"]})
    assert llm.complete([]).content == "{}"
    assert fake.models_called() == ["primary-model"] * 3


def test_falls_back_when_primary_keeps_failing():
    llm, fake = make_client(
        {"primary-model": [connection_error()] * 3, "fallback-model": ['{"from": "fallback"}']}
    )
    result = llm.complete([])
    assert result.usage.model == "fallback-model"
    assert fake.models_called() == ["primary-model"] * 3 + ["fallback-model"]


def test_no_fallback_when_disabled():
    llm, _ = make_client({"primary-model": [connection_error()] * 3})
    with pytest.raises(LLMError):
        llm.complete([], use_fallback=False)


def test_missing_key_is_reported():
    llm = LLMClient(settings=Settings(proxyapi_key=""))
    with pytest.raises(LLMError, match="PROXYAPI_KEY"):
        llm.complete([])


def test_cost_for_known_model():
    # Claude Haiku 5.5: 30 / 150 RUB per 1M tokens
    assert cost_rub("claude-haiku-5-5", 2000, 3000) == pytest.approx(0.51)
