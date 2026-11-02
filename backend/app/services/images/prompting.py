"""Builds image prompts from template `image_prompt` (FR-2.2: style consistency).

Every frame gets the same style prefix/suffix and the same character/setting/palette
description from the style bible, plus a shared seed (see generator).
"""

from app.prompts.loader import load_prompt
from app.services.scenes import Storyboard, StyleBible
from app.services.styles import StylePreset


def style_bible_short(bible: StyleBible) -> str:
    parts = [f"{c.name}: {c.appearance}" for c in bible.characters]
    if bible.setting:
        parts.append(f"setting: {bible.setting}")
    if bible.palette:
        parts.append(f"palette: {bible.palette}")
    return "; ".join(parts)


def build_prompts(storyboard: Storyboard, preset: StylePreset) -> tuple[list[str], str]:
    """Returns (positive prompt per scene, shared negative prompt)."""
    template = load_prompt("image_prompt")
    bible = style_bible_short(storyboard.style_bible)
    positives = [
        template.render(
            "positive",
            style_prefix=preset.prefix,
            visual_prompt=scene.visual_prompt.rstrip(". "),
            style_bible_short=bible,
            style_suffix=preset.suffix,
        )
        for scene in storyboard.scenes
    ]
    negative = " ".join(template.render("negative").split())
    return positives, negative
