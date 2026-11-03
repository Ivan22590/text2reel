"""Image provider interface (FR-2.1). Providers: `fal` (Fal.ai FLUX) and `proxyapi`."""

from dataclasses import dataclass, field
from typing import Protocol


class ImageError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    seed: int


@dataclass
class ImageResult:
    data: bytes  # encoded image (PNG/JPEG/WebP)
    provider: str
    model: str
    cost_rub: float = 0.0
    info: dict = field(default_factory=dict)  # what the provider reports: size, tokens, ...


class ImageProvider(Protocol):
    name: str
    model: str

    def generate(self, request: ImageRequest) -> ImageResult: ...
