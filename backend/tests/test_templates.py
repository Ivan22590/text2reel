import pytest

from app.services.branding import FONTS, Branding, font_file, hex_to_ass
from app.services.images.crop import OUTPUT_SIZES
from app.services.subtitles import Cue, to_ass
from app.services.templates import get_template, list_templates
from app.services.tts import Word


def test_one_template_per_format():
    templates = list_templates()
    assert {t.format for t in templates} == set(OUTPUT_SIZES)
    assert len({t.id for t in templates}) == 3


@pytest.mark.parametrize("fmt", list(OUTPUT_SIZES))
def test_template_values_are_usable(fmt):
    t = get_template(fmt)
    assert t.font in FONTS and font_file(t.font).is_file()
    assert t.transition.type in {"fade", "slideleft", "wipeleft", "circleopen"}
    assert 0.1 <= t.transition.duration <= 1.0
    assert 0 < t.safe_area.top < 0.3 and 0 < t.safe_area.bottom < 0.3
    assert t.subtitles.alignment in range(1, 10) and t.subtitles.size > 20
    assert 0.05 <= t.music_volume <= 0.5 and t.intro_seconds >= 1 and t.outro_seconds >= 1


def test_unknown_format_is_rejected():
    with pytest.raises(ValueError, match="no template"):
        get_template("4:3")


def test_hex_to_ass_is_bgr():
    assert hex_to_ass("#FFD700") == "&H0000D7FF"
    assert hex_to_ass("#ff0000") == "&H000000FF"
    assert hex_to_ass("#123456") == "&H00563412"


def test_template_style_and_branding_override():
    template = get_template("9:16")
    default = template.subtitle_style()
    assert default.font == "Fira Sans" and default.bold and default.mode == "karaoke"
    assert default.primary == "&H00FFFFFF" and default.highlight == "&H0000D7FF"

    branded = template.subtitle_style(
        Branding(font="Lobster", subtitle_color="#00FF00", highlight_color="#FF0000")
    )
    assert branded.font == "Lobster" and not branded.bold  # single-weight family: no fake bold
    assert branded.primary == "&H0000FF00" and branded.highlight == "&H000000FF"


def test_ass_uses_template_font():
    cue = Cue(0.0, 1.0, [Word("Привет", 0.0, 0.5)])
    ass = to_ass([cue], 1080, 1920, get_template("9:16").subtitle_style(Branding(font="PT Sans")))
    style = next(line for line in ass.splitlines() if line.startswith("Style:"))
    assert style.startswith("Style: Default,PT Sans,78,")
