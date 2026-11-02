"""Fit generated images to the output frame (FR-2.3): `cover` crop or `blur` fill."""

import io

from PIL import Image, ImageFilter

# Output frame per format, and the ~1 MP size requested from the generator
# (multiples of 64, close to the target aspect ratio).
OUTPUT_SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}
GENERATION_SIZES = {"9:16": (768, 1344), "16:9": (1344, 768), "1:1": (1024, 1024)}


def _cover(img: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / img.width, height / img.height)
    resized = img.resize(
        (round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _blur_fill(img: Image.Image, width: int, height: int) -> Image.Image:
    background = _cover(img, width, height).filter(ImageFilter.GaussianBlur(40))
    scale = min(width / img.width, height / img.height)
    fg = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
    background.paste(fg, ((width - fg.width) // 2, (height - fg.height) // 2))
    return background


def fit_image(data: bytes, width: int, height: int, mode: str = "cover") -> Image.Image:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if mode == "cover":
        return _cover(img, width, height)
    if mode == "blur":
        return _blur_fill(img, width, height)
    raise ValueError(f"unknown fit mode {mode!r} (cover | blur)")
