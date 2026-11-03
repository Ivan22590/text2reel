import base64
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.config import Settings
from app.services.images import ImageError, ImageRequest, get_provider
from app.services.images.proxyapi import ProxyAPIImageProvider, closest_size, parse_sizes
from tests.test_images import png_bytes

REQUEST = ImageRequest("a red fox", "text, watermark", 768, 1344, seed=7)  # 9:16
PNG_B64 = base64.b64encode(png_bytes(4, 4)).decode()


def ok(usage=None):
    return SimpleNamespace(data=[SimpleNamespace(b64_json=PNG_B64, url=None)], usage=usage)


def bad_request(message: str) -> openai.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.test/v1/images"))
    return openai.BadRequestError(message, response=response, body=None)


class FakeImages:
    """Returns / raises queued answers; records every request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []
        self.images = SimpleNamespace(generate=self._generate)

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def make(*answers, **settings) -> tuple[ProxyAPIImageProvider, FakeImages]:
    fake = FakeImages(*(answers or (ok(),)))
    return ProxyAPIImageProvider(Settings(proxyapi_key="k", **settings), client=fake), fake


def test_defaults_work_out_of_the_box():
    settings = Settings(proxyapi_key="k")
    assert settings.image_provider == "proxyapi"
    assert get_provider(settings).model == "openai/gpt-image-1-mini"


def test_sizes_are_parsed_and_the_closest_aspect_wins():
    sizes = parse_sizes("1024x1024, 1024x1536,1536x1024")
    assert closest_size(768, 1344, sizes) == (1024, 1536)  # 9:16 -> 2:3
    assert closest_size(1344, 768, sizes) == (1536, 1024)  # 16:9 -> 3:2
    assert closest_size(1024, 1024, sizes) == (1024, 1024)
    assert closest_size(900, 900, [(512, 512), (1024, 1024)]) == (1024, 1024)  # tie: the larger
    for bad in ("", "1024", "axb", "0x512", "1024x1024x3"):
        with pytest.raises(ImageError, match="PROXYAPI_IMAGE_SIZES"):
            parse_sizes(bad)


def test_request_uses_documented_parameters_only():
    provider, fake = make()
    provider.generate(REQUEST)
    assert fake.calls == [
        {
            "model": "openai/gpt-image-1-mini",
            "prompt": "a red fox",
            "n": 1,
            "size": "1024x1536",
            "quality": "low",
        }
    ]  # fmt: skip  (no seed, no negative prompt: undocumented, a 400 is likely)


def test_optional_parameters():
    provider, fake = make(
        proxyapi_image_negative="append", proxyapi_image_send_seed=True,
        proxyapi_image_quality="", proxyapi_image_sizes="768x1344,1344x768",
    )  # fmt: skip
    provider.generate(REQUEST)
    call = fake.calls[0]
    assert call["prompt"] == "a red fox\nAvoid: text, watermark"
    assert call["extra_body"] == {"seed": 7} and "quality" not in call
    assert call["size"] == "768x1344"


def test_returns_image_and_cost_from_token_usage():
    usage = SimpleNamespace(input_tokens=100, output_tokens=200)
    provider, _ = make(
        ok(usage), proxyapi_image_price_in_rub=1000, proxyapi_image_price_out_rub=2000
    )
    result = provider.generate(REQUEST)
    assert result.data.startswith(b"\x89PNG")
    assert result.cost_rub == pytest.approx(0.5)  # (100*1000 + 200*2000) / 1e6
    assert result.info == {"tokens_in": 100, "tokens_out": 200, "size": "1024x1536"}


def test_cost_falls_back_to_the_flat_price_then_to_zero():
    flat, _ = make(proxyapi_image_cost_rub=1.2)
    assert flat.generate(REQUEST).cost_rub == 1.2
    # tokens are reported but no price list is configured: the flat price still applies
    priced_by_flat, _ = make(
        ok(SimpleNamespace(input_tokens=5, output_tokens=5)), proxyapi_image_cost_rub=0.8
    )
    assert priced_by_flat.generate(REQUEST).cost_rub == 0.8
    unknown, _ = make()
    assert unknown.generate(REQUEST).cost_rub == 0.0


def test_refused_size_falls_back_to_1024_and_is_remembered():
    provider, fake = make(bad_request("Invalid value for size: 1024x1536"), ok(), ok())
    provider.generate(REQUEST)
    provider.generate(REQUEST)
    assert [c["size"] for c in fake.calls] == ["1024x1536", "1024x1024", "1024x1024"]


def test_model_without_quality_gets_none():
    provider, fake = make(bad_request("Unknown parameter: 'quality'"), ok(), ok())
    provider.generate(REQUEST)
    provider.generate(REQUEST)
    assert ["quality" in c for c in fake.calls] == [True, False, False]


def test_errors_are_reported_clearly():
    moderated, _ = make(bad_request("Your request was rejected by the safety system"))
    with pytest.raises(ImageError, match="moderation"):
        moderated.generate(REQUEST)
    other, _ = make(bad_request("model not found"))
    with pytest.raises(ImageError, match="rejected the request: .*model not found"):
        other.generate(REQUEST)
    down, _ = make(openai.APIConnectionError(request=httpx.Request("POST", "https://api.test")))
    with pytest.raises(ImageError, match="failed"):
        down.generate(REQUEST)
    stubborn, fake = make(
        bad_request("bad size"), bad_request("bad quality"), bad_request("bad size")
    )
    with pytest.raises(ImageError):
        stubborn.generate(REQUEST)
    assert len(fake.calls) <= 3  # never loops forever


def _answer(b64=None, url=None, empty=False):
    items = [] if empty else [SimpleNamespace(b64_json=b64, url=url)]
    return SimpleNamespace(data=items, usage=None)


@pytest.mark.parametrize(
    "answer", [_answer(empty=True), _answer(b64="@@@"), _answer()],
    ids=["no images", "invalid base64", "neither b64 nor url"],
)  # fmt: skip
def test_empty_or_broken_answers(answer):
    provider, _ = make(answer)
    with pytest.raises(ImageError):
        provider.generate(REQUEST)


def test_link_answer_is_downloaded(monkeypatch):
    answer = SimpleNamespace(
        data=[SimpleNamespace(b64_json=None, url="https://cdn.test/x.png")], usage=None
    )
    response = SimpleNamespace(content=b"\x89PNG-data", raise_for_status=lambda: None)
    monkeypatch.setattr(httpx, "get", lambda url, timeout: response)
    provider, _ = make(answer)
    assert provider.generate(REQUEST).data == b"\x89PNG-data"


def test_bad_settings_are_refused():
    with pytest.raises(ImageError, match="PROXYAPI_KEY"):
        ProxyAPIImageProvider(Settings(proxyapi_key=""))
    with pytest.raises(ImageError, match="NEGATIVE"):
        ProxyAPIImageProvider(Settings(proxyapi_key="k", proxyapi_image_negative="maybe"))
