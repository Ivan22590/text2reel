import json

import pytest

from app.config import Settings
from app.services.llm.client import LLMClient
from app.services.scenes import (
    SceneSplitError,
    detect_language,
    parse_storyboard,
    split_script,
    target_scene_count,
)
from app.services.styles import get_style, load_style_presets
from tests.fakes import FakeOpenAI, connection_error

SCRIPT = (
    "Лиса жила на краю леса. Каждое утро она встречала рассвет на старом холме. "
    "Однажды она нашла там светящийся камень."
)
SETTINGS = Settings(proxyapi_key="test", llm_model="primary", llm_fallback_model="fallback")


def storyboard_json(narrations: list[str], **scene_overrides) -> str:
    return json.dumps(
        {
            "style_bible": {
                "characters": [{"name": "the fox", "appearance": "small red fox, amber eyes"}],
                "setting": "edge of a pine forest",
                "palette": "warm orange, soft green",
            },
            "scenes": [
                {
                    "narration": text,
                    "visual_prompt": f"the fox, small red fox with amber eyes, scene {i}",
                    "mood": "calm",
                    "camera": "zoom_in",
                    **scene_overrides,
                }
                for i, text in enumerate(narrations)
            ],
        },
        ensure_ascii=False,
    )


GOOD = storyboard_json(
    [
        "Лиса жила на краю леса.",
        "Каждое утро она встречала рассвет на старом холме.",
        "Однажды она нашла там светящийся камень.",
    ]
)
REWRITTEN = storyboard_json(["Жила-была лиса.", "Она любила рассветы.", "И нашла камень."])


def make_llm(responses: dict) -> tuple[LLMClient, FakeOpenAI]:
    fake = FakeOpenAI(responses)
    return LLMClient(settings=SETTINGS, client=fake, sleep=lambda _: None), fake


def test_split_returns_validated_storyboard():
    llm, fake = make_llm({"primary": [GOOD]})
    result = split_script(SCRIPT, style="watercolor", format="9:16", llm=llm)
    assert len(result.storyboard.scenes) == 3
    assert result.storyboard.style_bible.characters[0].name == "the fox"
    assert result.attempts == 1
    user_prompt = fake.calls[0]["messages"][1]["content"]
    assert "Акварель" in user_prompt and SCRIPT in user_prompt


def test_rewritten_narration_is_retried_with_feedback():
    llm, fake = make_llm({"primary": [REWRITTEN, GOOD]})
    result = split_script(SCRIPT, style="anime", format="16:9", llm=llm)
    assert result.attempts == 2
    feedback = fake.calls[1]["messages"][-1]["content"]
    assert "word for word" in feedback


def test_invalid_json_then_fallback_model():
    llm, fake = make_llm({"primary": ["not json"] * 3, "fallback": [GOOD]})
    result = split_script(SCRIPT, style="anime", format="1:1", llm=llm)
    assert fake.models_called() == ["primary"] * 3 + ["fallback"]
    assert result.attempts == 4
    assert result.usage.tokens_in == 400  # usage summed over all attempts


def test_primary_unavailable_goes_straight_to_fallback():
    llm, fake = make_llm({"primary": [connection_error()] * 3, "fallback": [GOOD]})
    split_script(SCRIPT, style="anime", format="9:16", llm=llm)
    assert fake.models_called() == ["primary"] * 3 + ["fallback"]


def test_gives_up_after_all_attempts():
    llm, _ = make_llm({"primary": [REWRITTEN] * 3, "fallback": [REWRITTEN] * 2})
    with pytest.raises(SceneSplitError, match="5 attempts"):
        split_script(SCRIPT, style="anime", format="9:16", llm=llm)


def test_cache_hit_skips_llm(tmp_path):
    llm, fake = make_llm({"primary": [GOOD]})
    split_script(SCRIPT, style="comic", format="9:16", llm=llm, cache_dir=tmp_path)
    again = split_script(SCRIPT, style="comic", format="9:16", llm=llm, cache_dir=tmp_path)
    assert again.cached
    assert len(fake.calls) == 1


def test_parse_strips_code_fence_and_normalizes_enums():
    content = "```json\n" + storyboard_json([SCRIPT], mood="Joyful", camera="Pan Left") + "\n```"
    scene = parse_storyboard(content, SCRIPT).scenes[0]
    assert scene.mood == "calm"  # unknown mood -> default
    assert scene.camera == "pan_left"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"style": "unknown", "format": "9:16"}, "unknown style"),
        ({"style": "anime", "format": "4:3"}, "unknown format"),
    ],
)
def test_input_validation(kwargs, message):
    with pytest.raises(ValueError, match=message):
        split_script(SCRIPT, **kwargs)


def test_too_long_script_rejected():
    with pytest.raises(ValueError, match="longer than"):
        split_script("слово " * 2000, style="anime", format="9:16")


def test_helpers():
    assert detect_language(SCRIPT) == "ru"
    assert detect_language("The fox lived at the edge of the forest.") == "en"
    assert target_scene_count("word " * 150) == 10  # ~60 s of speech
    assert target_scene_count("one") == 1


def test_style_presets_loaded():
    presets = load_style_presets()
    assert set(presets) == {"realism", "anime", "watercolor", "comic", "render3d", "minimal"}
    assert get_style("watercolor").name == "Акварель"
