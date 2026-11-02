"""Visual style presets, read from backend/prompts/style_presets.md (markdown table)."""

from dataclasses import dataclass
from functools import lru_cache

from app.prompts.loader import load_prompt


@dataclass(frozen=True)
class StylePreset:
    id: str
    name: str
    prefix: str
    suffix: str


@lru_cache
def load_style_presets() -> dict[str, StylePreset]:
    prompt = load_prompt("style_presets")
    presets: dict[str, StylePreset] = {}
    for line in prompt.body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in ("id", "") or set(cells[0]) <= {"-"}:
            continue
        presets[cells[0]] = StylePreset(*cells)
    return presets


def get_style(style_id: str) -> StylePreset:
    presets = load_style_presets()
    if style_id not in presets:
        raise ValueError(f"unknown style {style_id!r}, expected one of {sorted(presets)}")
    return presets[style_id]
