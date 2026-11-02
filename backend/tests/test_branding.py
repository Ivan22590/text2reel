import io

import pytest
from PIL import Image
from pydantic import ValidationError

from app.services.branding import (
    FONTS,
    Branding,
    BrandingError,
    font_file,
    logo_path,
    make_card,
    save_logo,
)
from app.services.cards import build_card_scenes
from app.services.templates import get_template


def image_bytes(fmt: str, size=(40, 20), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def test_branding_defaults_mean_template_look():
    b = Branding()
    assert b.font is None and b.subtitle_color is None and b.logo_position is None
    assert b.intro_text == "" and b.outro_text == ""


@pytest.mark.parametrize(
    "data",
    [
        {"font": "Comic Sans"},
        {"subtitle_color": "red"},
        {"accent_color": "#12345"},
        {"logo_opacity": 0.0},
        {"logo_opacity": 1.5},
        {"logo_position": "center"},
        {"intro_text": "x" * 81},
    ],
)
def test_branding_rejects_bad_values(data):
    with pytest.raises(ValidationError):
        Branding(**data)


def test_branding_normalizes_colors():
    assert Branding(subtitle_color="#aabbcc").subtitle_color == "#AABBCC"


def test_save_logo_converts_to_rgba_png_and_limits_size(tmp_path):
    dest = logo_path(tmp_path)
    save_logo(image_bytes("JPEG", size=(2000, 1000)), dest)
    with Image.open(dest) as logo:
        assert logo.format == "PNG" and logo.mode == "RGBA"
        assert max(logo.size) == 800 and logo.size == (800, 400)


def test_save_logo_rejects_garbage_and_huge_files(tmp_path):
    with pytest.raises(BrandingError, match="прочитать"):
        save_logo(b"definitely not an image", logo_path(tmp_path))
    with pytest.raises(BrandingError, match="2 МБ"):
        save_logo(b"0" * 2_000_001, logo_path(tmp_path))
    assert not logo_path(tmp_path).exists()


@pytest.mark.parametrize("family", list(FONTS))
def test_card_is_drawn_with_every_font(tmp_path, family):
    out = make_card((270, 480), "Подписывайтесь на канал!", Branding(), family, None,
                    tmp_path / "card.png")  # fmt: skip
    with Image.open(out) as card:
        assert card.size == (270, 480)
        assert len(set(card.getdata())) > 50  # gradient plus text, not a flat fill


def test_card_with_logo_and_long_text_wraps(tmp_path):
    save_logo(image_bytes("PNG", size=(300, 300), color=(0, 200, 0)), logo_path(tmp_path))
    text = "Очень длинный заголовок, который обязательно должен перенестись на несколько строк"
    out = make_card((540, 960), text, Branding(accent_color="#FF0000"), "PT Sans",
                    logo_path(tmp_path), tmp_path / "c.png")  # fmt: skip
    with Image.open(out) as card:
        rgb = card.convert("RGB")
        assert rgb.getpixel((270, 100)) != rgb.getpixel((270, 900))  # vertical gradient
        # the green logo is somewhere in the upper half of the frame
        assert any(
            rgb.getpixel((x, y))[1] > 150 and rgb.getpixel((x, y))[0] < 80
            for x in range(200, 340, 10) for y in range(150, 450, 10)
        )  # fmt: skip


def test_font_files_exist():
    for family in FONTS:
        assert font_file(family).is_file()


def test_cards_exist_only_for_non_empty_text(tmp_path):
    template = get_template("16:9")
    intro, outro = build_card_scenes(Branding(), template, (320, 180), tmp_path)
    assert intro is None and outro is None

    intro, outro = build_card_scenes(
        Branding(intro_text="Привет!", outro_text="  "), template, (320, 180), tmp_path
    )
    assert intro is not None and outro is None
    assert intro.audio is None and intro.pause == 0.0 and intro.words == []
    assert intro.duration == template.intro_seconds and intro.image.is_file()
