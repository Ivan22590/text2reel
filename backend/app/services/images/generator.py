"""Generates one image per scene: parallel, cached, failures isolated per scene (FR-2.1–2.4)."""

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.services.images.base import ImageError, ImageProvider, ImageRequest
from app.services.images.crop import GENERATION_SIZES, OUTPUT_SIZES, fit_image

log = logging.getLogger(__name__)

ATTEMPTS_PER_IMAGE = 2


@dataclass
class SceneImage:
    index: int
    path: Path | None = None
    error: str | None = None
    cached: bool = False
    cost_rub: float = 0.0

    @property
    def ok(self) -> bool:
        return self.path is not None


def _cache_key(provider: ImageProvider, request: ImageRequest) -> str:
    raw = json.dumps(
        [
            provider.name,
            provider.model,
            request.prompt,
            request.negative_prompt,
            request.width,
            request.height,
            request.seed,
        ],
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_scene_image(
    index: int,
    prompt: str,
    *,
    negative_prompt: str,
    format: str,
    seed: int,
    out_dir: Path,
    provider: ImageProvider,
    cache_dir: Path | None = None,
    fit: str = "cover",
) -> SceneImage:
    gen_w, gen_h = GENERATION_SIZES[format]
    request = ImageRequest(prompt, negative_prompt, gen_w, gen_h, seed)
    result = SceneImage(index)

    cache_file = cache_dir / f"{_cache_key(provider, request)}.img" if cache_dir else None
    if cache_file is not None and cache_file.exists():
        data = cache_file.read_bytes()
        result.cached = True
    else:
        data = None
        for attempt in range(1, ATTEMPTS_PER_IMAGE + 1):
            try:
                generated = provider.generate(request)
            except ImageError as exc:
                log.warning("scene %d image attempt %d failed: %s", index, attempt, exc)
                result.error = str(exc)
                continue
            data = generated.data
            result.cost_rub += generated.cost_rub
            result.error = None
            break
        if data is None:
            return result
        if cache_file is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(data)

    out_w, out_h = OUTPUT_SIZES[format]
    try:
        frame = fit_image(data, out_w, out_h, fit)
    except OSError as exc:  # corrupted or non-image payload
        result.error = f"cannot decode image: {exc}"
        return result
    out_dir.mkdir(parents=True, exist_ok=True)
    result.path = out_dir / f"scene_{index:02d}.png"
    frame.save(result.path)
    return result


def generate_images(
    prompts: list[str],
    *,
    negative_prompt: str,
    format: str,
    seed: int,
    out_dir: Path,
    provider: ImageProvider,
    cache_dir: Path | None = None,
    concurrency: int = 4,
    fit: str = "cover",
) -> list[SceneImage]:
    if format not in OUTPUT_SIZES:
        raise ValueError(f"unknown format {format!r}")
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [
            pool.submit(
                generate_scene_image,
                index,
                prompt,
                negative_prompt=negative_prompt,
                format=format,
                seed=seed,
                out_dir=out_dir,
                provider=provider,
                cache_dir=cache_dir,
                fit=fit,
            )
            for index, prompt in enumerate(prompts)
        ]
        return [future.result() for future in futures]
