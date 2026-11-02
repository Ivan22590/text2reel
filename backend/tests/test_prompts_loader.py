import pytest

from app.prompts.loader import PromptError, load_prompt, parse_prompt


def test_scene_split_prompt_renders():
    prompt = load_prompt("scene_split")
    assert prompt.id == "scene_split"
    assert prompt.version >= 1
    user = prompt.render(
        "user",
        language="ru",
        style_name="watercolor",
        format="9:16",
        target_scene_count=5,
        script="Лиса жила на краю леса.",
    )
    assert "Лиса жила на краю леса." in user
    system = prompt.render("system", target_scene_count=5, format="9:16")
    assert "{{" not in system


@pytest.mark.parametrize(
    "prompt_id",
    ["scene_split", "scene_regenerate", "image_prompt", "style_presets", "music_mood", "smoke_llm"],
)
def test_all_prompt_files_parse(prompt_id):
    assert load_prompt(prompt_id).id == prompt_id


def test_missing_variable_raises():
    prompt = parse_prompt("---\nid: t\n---\n## user\nHello {{name}}\n")
    with pytest.raises(PromptError):
        prompt.render("user")
