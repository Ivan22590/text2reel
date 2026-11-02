"""Brand settings (FR-6.4): subtitle font and colours, logo, intro/outro cards.

Logo files are stored per project; cards are drawn with Pillow in the brand colours.
"""

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings

LogoPosition = Literal["top-left", "top-right", "bottom-left", "bottom-right"]
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_LOGO_BYTES = 2_000_000
MAX_LOGO_SIDE = 800


class BrandingError(ValueError):
    pass


@dataclass(frozen=True)
class FontSpec:
    family: str  # name inside the font file; used by ASS styles
    file: str
    bold: bool  # request the bold face in ASS (only for families shipped as Bold)


FONTS: dict[str, FontSpec] = {
    spec.family: spec
    for spec in (
        FontSpec("PT Sans", "PT_Sans-Web-Bold.ttf", True),
        FontSpec("Fira Sans", "FiraSans-Bold.ttf", True),
        FontSpec("Lobster", "Lobster-Regular.ttf", False),
        FontSpec("Russo One", "RussoOne-Regular.ttf", False),
    )
}


def fonts_dir() -> Path:
    return get_settings().assets_dir / "fonts"


def font_file(family: str) -> Path:
    return fonts_dir() / FONTS[family].file


def hex_to_ass(color: str) -> str:
    """#RRGGBB -> ASS &H00BBGGRR."""
    r, g, b = color[1:3], color[3:5], color[5:7]
    return f"&H00{b}{g}{r}".upper()


class Branding(BaseModel):
    """Per-project brand settings; stored in Project.branding_json. Empty = template defaults."""

    font: str | None = None
    subtitle_color: str | None = None
    highlight_color: str | None = None
    accent_color: str = "#4F6BED"
    background_color: str = "#101820"
    logo_position: LogoPosition | None = None
    logo_opacity: float | None = Field(default=None, ge=0.1, le=1.0)
    intro_text: str = Field(default="", max_length=80)
    outro_text: str = Field(default="", max_length=80)

    @field_validator("font")
    @classmethod
    def _font(cls, value: str | None) -> str | None:
        if value is not None and value not in FONTS:
            raise ValueError(f"unknown font {value!r}, expected one of {sorted(FONTS)}")
        return value

    @field_validator("subtitle_color", "highlight_color", "accent_color", "background_color")
    @classmethod
    def _color(cls, value: str | None) -> str | None:
        if value is not None and not HEX_COLOR.match(value):
            raise ValueError("color must look like #RRGGBB")
        return value.upper() if value else value


def logo_path(project_dir: Path) -> Path:
    return project_dir / "branding" / "logo.png"


def save_logo(data: bytes, dest: Path) -> None:
    """Validates an uploaded image and stores it as a PNG with alpha, at most 800 px a side."""
    if len(data) > MAX_LOGO_BYTES:
        raise BrandingError("Логотип больше 2 МБ")
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()  # detects truncated/corrupted files
        image = Image.open(io.BytesIO(data)).convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise BrandingError("Не удалось прочитать изображение (PNG, JPG или WebP)") from exc
    image.thumbnail((MAX_LOGO_SIDE, MAX_LOGO_SIDE), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, "PNG")


def _gradient(size: tuple[int, int], top: str, bottom: str) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    c1 = tuple(int(top[i : i + 2], 16) for i in (1, 3, 5))
    c2 = tuple(int(bottom[i : i + 2], 16) for i in (1, 3, 5))
    for y in range(height):
        k = y / max(1, height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(round(a + (b - a) * k) for a, b in zip(c1, c2, strict=True)),
        )
    return image


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int):
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def make_card(
    size: tuple[int, int], text: str, branding: Branding, font_family: str,
    logo: Path | None, out: Path,
) -> Path:  # fmt: skip
    """Intro/outro card: gradient background, optional logo on top, centred title."""
    width, height = size
    image = _gradient(size, branding.background_color, branding.accent_color)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_file(font_family)), max(12, round(width * 0.085)))
    lines = _wrap(draw, text, font, round(width * 0.82))
    line_height = round(font.size * 1.25)
    text_height = line_height * len(lines)

    logo_image = None
    gap = round(height * 0.04)
    if logo is not None and logo.exists():
        logo_image = Image.open(logo).convert("RGBA")
        scale = min(width * 0.4 / logo_image.width, height * 0.2 / logo_image.height)
        logo_image = logo_image.resize(
            (max(1, round(logo_image.width * scale)), max(1, round(logo_image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    block = text_height + (logo_image.height + gap if logo_image else 0)
    y = (height - block) // 2
    if logo_image is not None:
        image.paste(logo_image, ((width - logo_image.width) // 2, y), logo_image)
        y += logo_image.height + gap
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((width - w) / 2, y), line, font=font, fill="#FFFFFF",
                  stroke_width=max(1, width // 360), stroke_fill="#000000")  # fmt: skip
        y += line_height
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out
