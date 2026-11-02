"""Single entry point for all LLM calls, via ProxyAPI (OpenAI-compatible API).

See docs/MODELS_AND_COSTS.md. Network errors, 429 and 5xx are retried with exponential
backoff; when the model keeps failing, the fallback model is used.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import openai

from app.config import Settings, get_settings
from app.services.llm.pricing import cost_rub

log = logging.getLogger(__name__)

RETRYABLE_ERRORS = (
    openai.APIConnectionError,  # includes APITimeoutError
    openai.RateLimitError,
    openai.InternalServerError,
)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMUsage:
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_rub: float = 0.0

    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            model=other.model,
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            cost_rub=self.cost_rub + other.cost_rub,
        )


@dataclass
class LLMResult:
    content: str
    usage: LLMUsage


class LLMClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: openai.OpenAI | None = None,
        max_retries: int = 3,
        backoff_sec: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings or get_settings()
        self._client = client
        self.max_retries = max_retries
        self.backoff_sec = backoff_sec
        self._sleep = sleep

    @property
    def client(self) -> openai.OpenAI:
        if self._client is None:
            if not self.settings.proxyapi_key:
                raise LLMError("PROXYAPI_KEY is not set (see .env.example)")
            self._client = openai.OpenAI(
                api_key=self.settings.proxyapi_key,
                base_url=self.settings.proxyapi_base_url,
                timeout=self.settings.llm_timeout_sec,
                max_retries=0,  # retries are handled here, with model fallback
            )
        return self._client

    @property
    def primary_model(self) -> str:
        return self.settings.llm_model

    @property
    def fallback_model(self) -> str:
        return self.settings.llm_fallback_model

    def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.4,
        json_mode: bool = True,
        use_fallback: bool = True,
    ) -> LLMResult:
        models = [model or self.primary_model]
        if use_fallback and self.fallback_model and self.fallback_model not in models:
            models.append(self.fallback_model)

        last_error: Exception | None = None
        for current in models:
            try:
                return self._complete_with_retries(
                    current, messages, max_tokens, temperature, json_mode
                )
            except (LLMError, openai.APIError) as exc:
                log.warning("LLM model %s failed: %s", current, exc)
                last_error = exc
        raise LLMError(f"all LLM models failed: {last_error}") from last_error

    def _complete_with_retries(
        self, model: str, messages: list[dict], max_tokens: int, temperature: float, json_mode: bool
    ) -> LLMResult:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(self.max_retries):
            try:
                resp = self.client.chat.completions.create(**kwargs)
            except RETRYABLE_ERRORS as exc:
                if attempt == self.max_retries - 1:
                    raise
                delay = self.backoff_sec * 2**attempt
                log.info("LLM %s retry %d in %.1fs: %s", model, attempt + 1, delay, exc)
                self._sleep(delay)
                continue
            return self._to_result(model, resp)
        raise LLMError("unreachable")

    @staticmethod
    def _to_result(model: str, resp) -> LLMResult:
        if not resp.choices or resp.choices[0].message.content is None:
            raise LLMError(f"empty response from {model}")
        tokens_in = getattr(resp.usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(resp.usage, "completion_tokens", 0) or 0
        usage = LLMUsage(model, tokens_in, tokens_out, cost_rub(model, tokens_in, tokens_out))
        return LLMResult(content=resp.choices[0].message.content, usage=usage)
