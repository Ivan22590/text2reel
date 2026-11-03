"""ProxyAPI image generation: OpenAI-compatible `POST /v1/images/generations`.

What the ProxyAPI docs (proxyapi.ru/docs/image-generation) say, and what the adapter does:
- JSON with `model`, `prompt` and optional `size`, `quality`, `n`; the image comes back as
  base64 in `data[0].b64_json`, there is no URL.
- Not every model accepts every parameter and an unsupported one is a 400. `seed` and a
  negative prompt are not documented, so they are off by default (settings).
- The catalog and the model pages do not say which sizes a model accepts (the page of FLUX 3
  Image Klein shows `model` and `prompt` only). The adapter tries the configured sizes, closest
  aspect ratio first (the generator crops the rest); a size the API refuses is dropped, then
  1024x1024 (the only size in the docs), and finally no `size` at all (the model's default).
- Prices are per million tokens (app/services/images/pricing.py, from the catalog), so the cost
  comes from the token usage in the response.
"""

import base64
import logging
import math

import httpx
import openai

from app.config import Settings
from app.services.images.base import ImageError, ImageRequest, ImageResult
from app.services.images.pricing import prices_for

log = logging.getLogger(__name__)

SAFE_SIZE = "1024x1024"  # the only size shown in the ProxyAPI docs
SIZE_WORDS = ("size", "dimension", "resolution", "aspect")  # what a size complaint talks about


def parse_sizes(text: str) -> list[tuple[int, int]]:
    try:
        sizes = [tuple(int(v) for v in item.lower().split("x")) for item in text.split(",")]
    except ValueError as exc:
        raise ImageError(
            f"PROXYAPI_IMAGE_SIZES must look like 1024x1024,1024x1536: {text!r}"
        ) from exc
    if not sizes or any(len(s) != 2 or min(s) <= 0 for s in sizes):
        raise ImageError(f"PROXYAPI_IMAGE_SIZES must look like 1024x1024,1024x1536: {text!r}")
    return sizes


def closest_size(width: int, height: int, sizes: list[tuple[int, int]]) -> tuple[int, int]:
    """The allowed size whose aspect ratio is nearest to width:height (larger one on ties)."""
    wanted = math.log(width / height)
    return min(sizes, key=lambda s: (abs(math.log(s[0] / s[1]) - wanted), -s[0] * s[1]))


class ProxyAPIImageProvider:
    name = "proxyapi"

    def __init__(self, settings: Settings, client: openai.OpenAI | None = None):
        if not settings.proxyapi_key:
            raise ImageError("PROXYAPI_KEY is not set (see .env.example)")
        if not settings.proxyapi_image_model:
            raise ImageError("PROXYAPI_IMAGE_MODEL is not set: `python -m app.cli image-models`")
        if settings.proxyapi_image_negative not in ("ignore", "append"):
            raise ImageError("PROXYAPI_IMAGE_NEGATIVE must be ignore or append")
        self.settings = settings
        self.model = settings.proxyapi_image_model
        self.sizes = parse_sizes(settings.proxyapi_image_sizes)
        self.client = client or openai.OpenAI(
            api_key=settings.proxyapi_key,
            base_url=settings.proxyapi_base_url,
            timeout=settings.image_timeout_sec,
            max_retries=2,  # connection errors, 408/409/429 and 5xx, with backoff
        )
        # Learned from 400 answers, so the next images do not repeat the failed attempt.
        self._refused_sizes: set[str] = set()
        self._drop_quality = False

    def _prompt(self, request: ImageRequest) -> str:
        if self.settings.proxyapi_image_negative == "append" and request.negative_prompt:
            return f"{request.prompt}\nAvoid: {request.negative_prompt}"
        return request.prompt

    def _size(self, request: ImageRequest) -> str | None:
        """Best remaining size; None = send no `size` and let the model use its default."""
        allowed = [s for s in self.sizes if f"{s[0]}x{s[1]}" not in self._refused_sizes]
        if allowed:
            width, height = closest_size(request.width, request.height, allowed)
            return f"{width}x{height}"
        return SAFE_SIZE if SAFE_SIZE not in self._refused_sizes else None

    def _params(self, request: ImageRequest) -> dict:
        params: dict = {"model": self.model, "prompt": self._prompt(request), "n": 1}
        if size := self._size(request):
            params["size"] = size
        if self.settings.proxyapi_image_quality and not self._drop_quality:
            params["quality"] = self.settings.proxyapi_image_quality
        if self.settings.proxyapi_image_send_seed:
            params["extra_body"] = {"seed": request.seed}
        return params

    def generate(self, request: ImageRequest) -> ImageResult:
        for _ in range(len(self.sizes) + 3):  # every refusal removes one option
            params = self._params(request)
            try:
                resp = self.client.images.generate(**params)
                break
            except openai.BadRequestError as exc:
                message = str(exc).lower()
                if "size" in params and any(word in message for word in SIZE_WORDS):
                    log.warning("ProxyAPI refused size %s, trying another", params["size"])
                    self._refused_sizes.add(params["size"])
                elif "quality" in message and "quality" in params:
                    log.warning("ProxyAPI model has no `quality`, not sending it")
                    self._drop_quality = True
                elif any(w in message for w in ("moderation", "safety", "policy")):
                    raise ImageError(f"ProxyAPI declined the prompt (moderation): {exc}") from exc
                else:
                    raise ImageError(f"ProxyAPI rejected the request: {exc}") from exc
            except openai.APIError as exc:
                raise ImageError(f"ProxyAPI image request failed: {exc}") from exc
        else:
            raise ImageError("ProxyAPI keeps refusing the request parameters")

        if not resp.data:
            raise ImageError("ProxyAPI returned no images")
        data = self._image_bytes(resp.data[0])
        cost, info = self._cost(resp)
        info["size"] = params.get("size", "model default")
        return ImageResult(data, self.name, self.model, cost, info)

    def _image_bytes(self, item) -> bytes:
        if getattr(item, "b64_json", None):
            try:  # validate=True: by default garbage characters are silently dropped
                data = base64.b64decode(item.b64_json, validate=True)
            except ValueError as exc:
                raise ImageError(f"ProxyAPI sent invalid base64: {exc}") from exc
            if not data:
                raise ImageError("ProxyAPI sent an empty image")
            return data
        if getattr(item, "url", None):  # not in the docs, but some models answer with a link
            try:
                download = httpx.get(item.url, timeout=self.settings.image_timeout_sec)
                download.raise_for_status()
            except httpx.HTTPError as exc:
                raise ImageError(f"image download failed: {exc}") from exc
            return download.content
        raise ImageError("ProxyAPI image has neither b64_json nor url")

    def _cost(self, resp) -> tuple[float, dict]:
        """Rubles for one image: token usage x the model's price, else the flat per-image price."""
        s = self.settings
        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)
        tokens_out = getattr(usage, "output_tokens", None) or getattr(
            usage, "completion_tokens", None
        )
        tokens_in, tokens_out = tokens_in or 0, tokens_out or 0
        info = {"tokens_in": tokens_in, "tokens_out": tokens_out}
        price_in, price_out = prices_for(
            self.model, s.proxyapi_image_price_in_rub, s.proxyapi_image_price_out_rub
        )
        if (tokens_in or tokens_out) and (price_in or price_out):
            return (tokens_in * price_in + tokens_out * price_out) / 1e6, info
        if s.proxyapi_image_cost_rub == 0:
            log.warning(
                "image cost is unknown: no usage in the answer or no price for %s", self.model
            )
        return s.proxyapi_image_cost_rub, info
