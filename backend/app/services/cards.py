"""Intro / outro cards as extra scenes without narration (FR-6.4)."""

from pathlib import Path

from app.services.branding import Branding, make_card
from app.services.compositor import RenderScene
from app.services.templates import Template


def build_card_scenes(
    branding: Branding,
    template: Template,
    size: tuple[int, int],
    work_dir: Path,
    logo: Path | None = None,
) -> tuple[RenderScene | None, RenderScene | None]:
    """(intro, outro); a card exists only when its text is not empty."""
    font = branding.font or template.font

    def card(kind: str, text: str, seconds: float) -> RenderScene | None:
        if not text.strip():
            return None
        image = make_card(size, text.strip(), branding, font, logo, work_dir / f"{kind}.png")
        # No narration, so no pause either: the card lasts exactly `seconds`.
        return RenderScene(image, None, seconds, [], "", camera="static", pause=0.0)

    return (
        card("intro", branding.intro_text, template.intro_seconds),
        card("outro", branding.outro_text, template.outro_seconds),
    )
