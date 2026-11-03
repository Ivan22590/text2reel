"""ProxyAPI image generation: OpenAI-compatible `POST /v1/images/generations`.

What the ProxyAPI docs (proxyapi.ru/docs/image-generation) say, and what the adapter does:
- JSON with `model`, `prompt` and optional `size`, `quality`, `n`; the image comes back as
  base64 in `data[0].b64_json`, there is no URL.
- Not every model accepts every parameter and an unsupported one is a 400. `seed` and a
  negative prompt are not documented, so they are off by default (settings).
- Sizes differ per model: the documented one is 1024x1024, OpenAI-style models also take
  1024x1536 and 1536x1024. The adapter asks for the allowed size closest to the wanted aspect
  ratio (the generator crops the rest) and falls back to 1024x1024 if the API refuses the size.
- Prices are per million tokens, so the cost comes from the token usage in the response.
"""

import base64
import logging
import math

import httpx
import openai

from app.config import Settings
from app.services.images.base import ImageError, ImageRequest, ImageResult

log = logging.getLogger(__name__)

SAFE_SIZE = "1024x1024"  # the only size shown in the ProxyAPI docs


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
        self._force_safe_size = False
        self._drop_quality = False

    def _prompt(self, request: ImageRequest) -> str:
        if self.settings.proxyapi_image_negative == "append" and request.negative_prompt:
            return f"{request.prompt}\nAvoid: {request.negative_prompt}"
        return request.prompt

    def _params(self, request: ImageRequest) -> dict:
        width, height = (1024, 1024) if self._force_safe_size else closest_size(
            request.width, request.height, self.sizes
        )  # fmt: skip
        params: dict = {
            "model": self.model, "prompt": self._prompt(request), "n": 1,
            "size": f"{width}x{height}",
        }  # fmt: skip
        if self.settings.proxyapi_image_quality and not self._drop_quality:
            params["quality"] = self.settings.proxyapi_image_quality
        if self.settings.proxyapi_image_send_seed:
            params["extra_body"] = {"seed": request.seed}
        return params

    def generate(self, request: ImageRequest) -> ImageResult:
        for _ in range(3):  # the original request plus at most two adjustments
            params = self._params(request)
            try:
                resp = self.client.images.generate(**params)
                break
            except openai.BadRequestError as exc:
                message = str(exc).lower()
                if "size" in message and params["size"] != SAFE_SIZE:
                    log.warning("ProxyAPI refused size %s, using %s", params["size"], SAFE_SIZE)
                    self._force_safe_size = True
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
        info["size"] = params["size"]
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
        """Rubles for one image: token usage x the price list, else the flat per-image price."""
        s = self.settings
        usage = getattr(resp, "usage", None)
        tokens_in = (
            getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None) or 0
        )
        tokens_out = (
            getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None) or 0
        )
        info = {"tokens_in": tokens_in, "tokens_out": tokens_out}
        if (tokens_in or tokens_out) and (
            s.proxyapi_image_price_in_rub or s.proxyapi_image_price_out_rub
        ):
            cost = (
                tokens_in * s.proxyapi_image_price_in_rub
                + tokens_out * s.proxyapi_image_price_out_rub
            ) / 1e6
            return cost, info
        if s.proxyapi_image_cost_rub == 0:
            log.warning(
                "image cost is unknown: set PROXYAPI_IMAGE_PRICE_* or PROXYAPI_IMAGE_COST_RUB"
            )
        return s.proxyapi_image_cost_rub, info
