from app.config import Settings, get_settings
from app.services.images.base import ImageError, ImageProvider, ImageRequest, ImageResult

__all__ = ["ImageError", "ImageProvider", "ImageRequest", "ImageResult", "get_provider"]


def get_provider(settings: Settings | None = None) -> ImageProvider:
    settings = settings or get_settings()
    if settings.image_provider == "fal":
        from app.services.images.fal import FalProvider

        return FalProvider(settings)
    if settings.image_provider == "proxyapi":
        from app.services.images.proxyapi import ProxyAPIImageProvider

        return ProxyAPIImageProvider(settings)
    raise ImageError(f"unknown IMAGE_PROVIDER {settings.image_provider!r} (fal | proxyapi)")
