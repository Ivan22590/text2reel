import base64
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.services.images import ImageError, ImageRequest, ImageResult, get_provider
from app.services.images.crop import GENERATION_SIZES, OUTPUT_SIZES, fit_image
from app.services.images.fal import FalProvider
from app.services.images.generator import generate_images
from app.services.images.prompting import build_prompts
from app.services.images.proxyapi import ProxyAPIImageProvider
from app.services.scenes import Storyboard
from app.services.styles import get_style

STORYBOARD = Storyboard.model_validate(
    {
        "style_bible": {
            "characters": [{"name": "the fox", "appearance": "small red fox, amber eyes"}],
            "setting": "pine forest",
            "palette": "warm orange",
        },
        "scenes": [
            {"narration": "Лиса жила на краю леса.", "visual_prompt": "the fox sits at the edge."},
            {"narration": "Она нашла камень.", "visual_prompt": "the fox finds a glowing stone"},
        ],
    }
)


def png_bytes(width: int, height: int, color=(200, 80, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, fail_times: int = 0, fail_if: str | None = None):
        self.requests: list[ImageRequest] = []
        self.fail_times = fail_times
        self.fail_if = fail_if

    def generate(self, request: ImageRequest) -> ImageResult:
        self.requests.append(request)
        if self.fail_if and self.fail_if in request.prompt:
            raise ImageError("moderation rejected")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ImageError("temporary error")
        return ImageResult(png_bytes(request.width, request.height), self.name, self.model, 0.5)


def test_prompts_share_style_and_bible():
    positives, negative = build_prompts(STORYBOARD, get_style("watercolor"))
    assert len(positives) == 2
    for prompt in positives:
        assert prompt.startswith("soft watercolor painting")
        assert "the fox: small red fox, amber eyes" in prompt
        assert "palette: warm orange" in prompt
        assert "hand-painted" in prompt
    assert "edge.." not in positives[0]
    assert "\n" not in negative and "watermark" in negative


@pytest.mark.parametrize("mode", ["cover", "blur"])
@pytest.mark.parametrize("fmt", list(OUTPUT_SIZES))
def test_fit_image_produces_output_size(mode, fmt):
    width, height = OUTPUT_SIZES[fmt]
    frame = fit_image(png_bytes(1024, 1024), width, height, mode)
    assert frame.size == (width, height)


def test_generate_images_writes_frames_with_shared_seed(tmp_path):
    provider = FakeProvider()
    prompts = ["first prompt", "second prompt", "third prompt"]
    results = generate_images(
        prompts,
        negative_prompt="text",
        format="9:16",
        seed=7,
        out_dir=tmp_path / "out",
        provider=provider,
    )
    assert all(item.ok for item in results)
    assert [item.index for item in results] == [0, 1, 2]
    assert Image.open(results[0].path).size == OUTPUT_SIZES["9:16"]
    assert {r.seed for r in provider.requests} == {7}
    assert {(r.width, r.height) for r in provider.requests} == {GENERATION_SIZES["9:16"]}
    assert sum(item.cost_rub for item in results) == pytest.approx(1.5)


def test_cache_avoids_second_generation(tmp_path):
    provider = FakeProvider()
    kwargs = dict(
        negative_prompt="text",
        format="1:1",
        seed=1,
        out_dir=tmp_path / "out",
        provider=provider,
        cache_dir=tmp_path / "cache",
    )
    generate_images(["a prompt"], **kwargs)
    again = generate_images(["a prompt"], **kwargs)
    assert again[0].cached and again[0].cost_rub == 0
    assert len(provider.requests) == 1


def test_failed_scene_does_not_break_others(tmp_path):
    provider = FakeProvider(fail_if="forbidden")
    results = generate_images(
        ["ok one", "forbidden two", "ok three"],
        negative_prompt="",
        format="16:9",
        seed=1,
        out_dir=tmp_path,
        provider=provider,
        concurrency=1,
    )
    assert [item.ok for item in results] == [True, False, True]
    assert results[1].error == "moderation rejected"


def test_temporary_error_is_retried(tmp_path):
    provider = FakeProvider(fail_times=1)
    results = generate_images(
        ["prompt"], negative_prompt="", format="9:16", seed=1, out_dir=tmp_path, provider=provider
    )
    assert results[0].ok and len(provider.requests) == 2


def test_fal_provider_request_and_cost():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["url"] = str(request.url)
            seen["auth"] = request.headers["Authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"images": [{"url": "https://cdn.test/img.png"}]})
        return httpx.Response(200, content=png_bytes(8, 8))

    settings = Settings(fal_key="secret", usd_rub=100)
    provider = FalProvider(settings, http=httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.generate(ImageRequest("a fox", "text", 1000, 1000, 5))
    assert seen["url"] == "https://fal.run/fal-ai/flux/schnell"
    assert seen["auth"] == "Key secret"
    assert seen["body"]["seed"] == 5
    assert seen["body"]["image_size"] == {"width": 1000, "height": 1000}
    assert result.cost_rub == pytest.approx(0.3)  # 1 MP * $0.003 * 100


def test_fal_http_error_becomes_image_error():
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    provider = FalProvider(Settings(fal_key="k"), http=httpx.Client(transport=transport))
    with pytest.raises(ImageError):
        provider.generate(ImageRequest("p", "", 64, 64, 1))


def test_proxyapi_provider_decodes_b64():
    payload = base64.b64encode(png_bytes(4, 4)).decode()
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=payload, url=None)])

    client = SimpleNamespace(images=SimpleNamespace(generate=generate))
    settings = Settings(
        proxyapi_key="k", proxyapi_image_model="flux-klein", proxyapi_image_cost_rub=1.2
    )
    result = ProxyAPIImageProvider(settings, client=client).generate(
        ImageRequest("a fox", "text", 768, 1344, 3)
    )
    assert result.data.startswith(b"\x89PNG") and result.cost_rub == 1.2
    assert calls[0]["size"] == "768x1344" and calls[0]["model"] == "flux-klein"


def test_provider_selection_errors():
    with pytest.raises(ImageError, match="unknown IMAGE_PROVIDER"):
        get_provider(Settings(image_provider="other"))
    with pytest.raises(ImageError, match="FAL_KEY"):
        get_provider(Settings(image_provider="fal", fal_key=""))
    with pytest.raises(ImageError, match="PROXYAPI_IMAGE_MODEL"):
        get_provider(Settings(image_provider="proxyapi", proxyapi_key="k"))
