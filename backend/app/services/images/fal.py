"""Fal.ai provider (FLUX.1 schnell by default), synchronous REST endpoint https://fal.run/<model>."""

import httpx

from app.config import Settings
from app.services.images.base import ImageError, ImageRequest, ImageResult

FAL_URL = "https://fal.run"


class FalProvider:
    name = "fal"

    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        if not settings.fal_key:
            raise ImageError("FAL_KEY is not set (see .env.example)")
        self.settings = settings
        self.model = settings.fal_model
        self.http = http or httpx.Client(timeout=settings.image_timeout_sec)

    def generate(self, request: ImageRequest) -> ImageResult:
        # FLUX schnell has no negative prompt; it is used only by providers that support it.
        payload = {
            "prompt": request.prompt,
            "image_size": {"width": request.width, "height": request.height},
            "seed": request.seed,
            "num_images": 1,
            "num_inference_steps": 4,
            "enable_safety_checker": True,
        }
        headers = {"Authorization": f"Key {self.settings.fal_key}"}
        try:
            resp = self.http.post(f"{FAL_URL}/{self.model}", json=payload, headers=headers)
            resp.raise_for_status()
            images = resp.json().get("images") or []
            if not images:
                raise ImageError("Fal.ai returned no images")
            image = self.http.get(images[0]["url"])
            image.raise_for_status()
        except httpx.HTTPError as exc:
            raise ImageError(f"Fal.ai request failed: {exc}") from exc

        megapixels = request.width * request.height / 1_000_000
        cost = megapixels * self.settings.fal_cost_usd_per_mp * self.settings.usd_rub
        return ImageResult(image.content, self.name, self.model, cost)
