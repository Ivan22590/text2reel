"""Format templates (FR-6.3): subtitle look, transitions, logo, safe zones per platform.

Loaded from backend/templates/*.json. A project picks the template by its format.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.config import get_settings
from app.services.branding import FONTS, Branding, LogoPosition, hex_to_ass
from app.services.subtitles import SubtitleStyle


class SafeArea(BaseModel):
    top: float
    bottom: float


class SubtitleSpec(BaseModel):
    mode: Literal["phrase", "karaoke"]
    size: int
    alignment: int
    margin_v: int
    max_chars: int
    outline: int = 4
    color: str = "#FFFFFF"
    highlight: str = "#FFD700"


class TransitionSpec(BaseModel):
    type: str
    duration: float


class LogoSpec(BaseModel):
    position: LogoPosition
    scale: float  # logo width as a fraction of the frame width
    opacity: float


class Template(BaseModel):
    id: str
    name: str
    format: str
    font: str
    safe_area: SafeArea
    subtitles: SubtitleSpec
    transition: TransitionSpec
    ken_burns_zoom: float
    music_volume: float
    logo: LogoSpec
    intro_seconds: float
    outro_seconds: float

    def subtitle_style(self, branding: Branding | None = None) -> SubtitleStyle:
        branding = branding or Branding()
        spec = self.subtitles
        family = branding.font or self.font
        return SubtitleStyle(
            font=family,
            size=spec.size,
            bold=FONTS[family].bold,
            primary=hex_to_ass(branding.subtitle_color or spec.color),
            highlight=hex_to_ass(branding.highlight_color or spec.highlight),
            outline=spec.outline,
            alignment=spec.alignment,
            margin_v=spec.margin_v,
            mode=spec.mode,
            max_chars=spec.max_chars,
        )


@lru_cache
def _load(directory: Path) -> dict[str, Template]:
    templates = {}
    for path in sorted(directory.glob("*.json")):
        template = Template.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if template.format in templates:
            raise ValueError(f"two templates for format {template.format}: {path.name}")
        templates[template.format] = template
    return templates


def list_templates() -> list[Template]:
    return list(_load(get_settings().templates_dir).values())


def get_template(format: str) -> Template:
    templates = _load(get_settings().templates_dir)
    if format not in templates:
        raise ValueError(f"no template for format {format!r}, available: {sorted(templates)}")
    return templates[format]
