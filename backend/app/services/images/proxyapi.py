"""ProxyAPI image generation via the OpenAI-compatible Images API.

Model ids and per-image price are set in .env after the stage 2 comparison
(docs/MODELS_AND_COSTS.md §3).
"""

import base64

import httpx
import openai

from app.config import Settings
from app.services.images.base import ImageError, ImageRequest, ImageResult


class ProxyAPIImageProvider:
    name = "proxyapi"

    def __init__(self, settings: Settings, client: openai.OpenAI | None = None):
        if not settings.proxyapi_key:
            raise ImageError("PROXYAPI_KEY is not set (see .env.example)")
        if not settings.proxyapi_image_model:
            raise ImageError("PROXYAPI_IMAGE_MODEL is not set (see .env.example)")
        self.settings = settings
        self.model = settings.proxyapi_image_model
        self.client = client or openai.OpenAI(
            api_key=settings.proxyapi_key,
            base_url=settings.proxyapi_base_url,
            timeout=settings.image_timeout_sec,
        )

    def generate(self, request: ImageRequest) -> ImageResult:
        try:
            resp = self.client.images.generate(
                model=self.model,
                prompt=f"{request.prompt}\nAvoid: {request.negative_prompt}",
                size=f"{request.width}x{request.height}",
                n=1,
            )
        except openai.APIError as exc:
            raise ImageError(f"ProxyAPI image request failed: {exc}") from exc
        if not resp.data:
            raise ImageError("ProxyAPI returned no images")

        item = resp.data[0]
        if item.b64_json:
            data = base64.b64decode(item.b64_json)
        elif item.url:
            try:
                download = httpx.get(item.url, timeout=self.settings.image_timeout_sec)
                download.raise_for_status()
            except httpx.HTTPError as exc:
                raise ImageError(f"image download failed: {exc}") from exc
            data = download.content
        else:
            raise ImageError("ProxyAPI image has neither b64_json nor url")
        return ImageResult(data, self.name, self.model, self.settings.proxyapi_image_cost_rub)
