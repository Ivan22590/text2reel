"""Fake OpenAI client: no network, no paid calls."""

from types import SimpleNamespace

import httpx
import openai


def connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=httpx.Request("POST", "https://example.test"))


def completion(content: str, tokens_in: int = 100, tokens_out: int = 200) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )


class FakeOpenAI:
    """Returns (or raises) queued responses per model; records every call."""

    def __init__(self, responses: dict[str, list]):
        self.responses = {model: list(items) for model, items in responses.items()}
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        queue = self.responses.get(kwargs["model"], [])
        if not queue:
            raise AssertionError(f"unexpected call for model {kwargs['model']}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return completion(item) if isinstance(item, str) else item

    def models_called(self) -> list[str]:
        return [call["model"] for call in self.calls]
