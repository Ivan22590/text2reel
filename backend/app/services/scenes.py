"""Stage 1: split a script into scenes with visual prompts (FR-1.1–FR-1.5).

Flow: render prompt `scene_split` → LLM (JSON) → Pydantic validation → check that the
narration matches the original script → cache. Invalid answers are retried with the
validation error fed back to the model; then the fallback model is tried.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.prompts.loader import load_prompt
from app.services.llm.client import LLMClient, LLMError, LLMUsage
from app.services.styles import get_style

log = logging.getLogger(__name__)

MAX_SCRIPT_CHARS = 5000
FORMATS = ("9:16", "16:9", "1:1")
MOODS = ("calm", "happy", "epic", "sad", "tense", "corporate", "mysterious")
CAMERAS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "static")
NARRATION_MIN_SIMILARITY = 0.97
WORDS_PER_SECOND = 2.5  # ~150 words per minute of speech
SECONDS_PER_SCENE = 6
PRIMARY_ATTEMPTS = 3  # first try + 2 retries (FR-1.4)
FALLBACK_ATTEMPTS = 2


class Character(BaseModel):
    name: str
    appearance: str


class StyleBible(BaseModel):
    characters: list[Character] = Field(default_factory=list)
    setting: str = ""
    palette: str = ""


class SceneDraft(BaseModel):
    narration: str = Field(min_length=1)
    visual_prompt: str = Field(min_length=10)
    mood: Literal[MOODS] = "calm"
    camera: Literal[CAMERAS] = "zoom_in"

    # Unknown mood/camera values are not worth a paid retry: fall back to defaults.
    @field_validator("mood", mode="before")
    @classmethod
    def _mood(cls, value: object) -> str:
        value = str(value or "").strip().lower()
        return value if value in MOODS else "calm"

    @field_validator("camera", mode="before")
    @classmethod
    def _camera(cls, value: object) -> str:
        value = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        return value if value in CAMERAS else "zoom_in"


class Storyboard(BaseModel):
    style_bible: StyleBible
    scenes: list[SceneDraft] = Field(min_length=1)


@dataclass
class SceneSplitResult:
    storyboard: Storyboard
    usage: LLMUsage
    cached: bool = False
    attempts: int = 0


class SceneSplitError(RuntimeError):
    pass


def detect_language(text: str) -> str:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "en"
    cyrillic = sum(1 for ch in letters if "Ѐ" <= ch <= "ӿ")
    return "ru" if cyrillic / len(letters) > 0.3 else "en"


def target_scene_count(script: str) -> int:
    seconds = len(script.split()) / WORDS_PER_SECOND
    return max(1, min(30, round(seconds / SECONDS_PER_SCENE)))


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def narration_similarity(script: str, storyboard: Storyboard) -> float:
    joined = " ".join(scene.narration for scene in storyboard.scenes)
    return SequenceMatcher(None, _words(script), _words(joined), autojunk=False).ratio()


def parse_storyboard(content: str, script: str) -> Storyboard:
    """Parse and validate an LLM answer. Raises ValueError with a model-readable reason."""
    content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"answer is not valid JSON: {exc}") from exc
    try:
        storyboard = Storyboard.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"JSON does not match the schema: {exc}") from exc
    similarity = narration_similarity(script, storyboard)
    if similarity < NARRATION_MIN_SIMILARITY:
        raise ValueError(
            "narration texts must reproduce the script word for word "
            f"(similarity {similarity:.2f} < {NARRATION_MIN_SIMILARITY})"
        )
    return storyboard


def _cache_key(model: str, prompt_version: int, **inputs: object) -> str:
    raw = json.dumps({"model": model, "v": prompt_version, **inputs}, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def split_script(
    script: str,
    *,
    style: str,
    format: str,
    language: str | None = None,
    llm: LLMClient | None = None,
    cache_dir: Path | None = None,
) -> SceneSplitResult:
    script = script.strip()
    if not script:
        raise ValueError("script is empty")
    if len(script) > MAX_SCRIPT_CHARS:
        raise ValueError(f"script is longer than {MAX_SCRIPT_CHARS} characters")
    if format not in FORMATS:
        raise ValueError(f"unknown format {format!r}, expected one of {FORMATS}")

    preset = get_style(style)
    language = language or detect_language(script)
    llm = llm or LLMClient()
    prompt = load_prompt("scene_split")
    scenes_target = target_scene_count(script)

    cache_file = None
    if cache_dir is not None:
        key = _cache_key(
            llm.primary_model,
            prompt.version,
            script=script,
            style=style,
            format=format,
            language=language,
        )
        cache_file = cache_dir / f"{key}.json"
        if cache_file.exists():
            storyboard = Storyboard.model_validate_json(cache_file.read_text(encoding="utf-8"))
            return SceneSplitResult(storyboard, LLMUsage(llm.primary_model), cached=True)

    messages = [
        {
            "role": "system",
            "content": prompt.render("system", target_scene_count=scenes_target, format=format),
        },
        {
            "role": "user",
            "content": prompt.render(
                "user", style_name=preset.name, format=format, language=language, script=script
            ),
        },
    ]
    temperature = float(prompt.meta.get("temperature", 0.4))
    max_tokens = min(8000, 600 + 350 * scenes_target)

    usage = LLMUsage(llm.primary_model)
    attempts = 0
    last_error = "no attempts made"
    plan = [(llm.primary_model, PRIMARY_ATTEMPTS)]
    if llm.fallback_model and llm.fallback_model != llm.primary_model:
        plan.append((llm.fallback_model, FALLBACK_ATTEMPTS))

    for model, tries in plan:
        conversation = list(messages)
        for _ in range(tries):
            attempts += 1
            try:
                result = llm.complete(
                    conversation,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    use_fallback=False,
                )
            except LLMError as exc:
                last_error = str(exc)
                break  # model unavailable: go to the next one
            usage = usage + result.usage
            try:
                storyboard = parse_storyboard(result.content, script)
            except ValueError as exc:
                last_error = str(exc)
                log.info("scene_split attempt %d with %s rejected: %s", attempts, model, exc)
                conversation = conversation + [
                    {"role": "assistant", "content": result.content},
                    {"role": "user", "content": prompt.render("retry", error=exc)},
                ]
                continue
            if cache_file is not None:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(storyboard.model_dump_json(indent=2), encoding="utf-8")
            return SceneSplitResult(storyboard, usage, attempts=attempts)

    raise SceneSplitError(f"scene split failed after {attempts} attempts: {last_error}")


def regenerate_visual_prompt(
    style_bible: StyleBible,
    narration: str,
    previous_prompt: str,
    *,
    hint: str = "",
    llm: LLMClient | None = None,
) -> tuple[str, LLMUsage]:
    """New visual prompt for one scene (FR-2.5), prompt `scene_regenerate`."""
    llm = llm or LLMClient()
    prompt = load_prompt("scene_regenerate")
    variables = {
        "style_bible_json": style_bible.model_dump_json(),
        "narration": narration,
        "previous_prompt": previous_prompt,
        "user_hint": hint,
    }
    result = llm.complete(
        [
            {"role": "system", "content": prompt.render("system")},
            {"role": "user", "content": prompt.render("user", **variables)},
        ],
        max_tokens=400,
        temperature=float(prompt.meta.get("temperature", 0.7)),
    )
    content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", result.content)
    try:
        new_prompt = str(json.loads(content)["visual_prompt"]).strip()
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SceneSplitError(f"invalid scene_regenerate answer: {exc}") from exc
    if len(new_prompt) < 10:
        raise SceneSplitError("scene_regenerate returned an empty prompt")
    return new_prompt, result.usage
