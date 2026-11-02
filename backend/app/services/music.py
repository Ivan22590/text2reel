"""Background music library (FR-6.1, FR-6.2): catalog and automatic choice by scene mood.

Tracks live in backend/assets/music with `catalog.json` (see LICENSES.md there). A project
stores its choice in `music_track_id`: `auto` (or empty), `none`, or a track id.
"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings

AUTO = "auto"
NONE = "none"

# Tie-break between equally frequent moods (docs: backend/prompts/music_mood.md).
MOOD_PRIORITY = ["epic", "tense", "happy", "calm", "corporate", "sad", "mysterious"]
# Moods to try, in order, when the library has no track for the wanted one.
FALLBACKS = {
    "epic": ["tense", "happy"],
    "tense": ["mysterious", "epic"],
    "happy": ["corporate", "calm"],
    "calm": ["corporate", "sad"],
    "corporate": ["calm", "happy"],
    "sad": ["calm"],
    "mysterious": ["tense", "calm"],
}


class Track(BaseModel):
    id: str
    title: str
    artist: str
    file: str
    duration: float
    moods: list[str]  # the first one is the main mood
    license: str
    source: str
    size: int
    sha256: str

    @property
    def path(self) -> Path:
        return get_settings().assets_dir / "music" / self.file


@lru_cache
def _load(directory: Path) -> tuple[Track, ...]:
    raw = json.loads((directory / "catalog.json").read_text(encoding="utf-8"))
    return tuple(Track.model_validate(item) for item in raw)


def load_catalog() -> list[Track]:
    return list(_load(get_settings().assets_dir / "music"))


def get_track(track_id: str) -> Track | None:
    return next((t for t in load_catalog() if t.id == track_id), None)


def is_valid_choice(choice: str) -> bool:
    return choice in (AUTO, NONE) or get_track(choice) is not None


def dominant_mood(scenes: list[tuple[str, float]]) -> str:
    """Most common mood weighted by scene length; ties go to MOOD_PRIORITY order."""
    weights: dict[str, float] = {}
    for mood, seconds in scenes:
        weights[mood] = weights.get(mood, 0.0) + (seconds or 1.0)
    if not weights:
        return "calm"
    rank = {m: i for i, m in enumerate(MOOD_PRIORITY)}
    return max(weights, key=lambda m: (weights[m], -rank.get(m, len(rank))))


def pick_track(mood: str, seed: int, catalog: list[Track] | None = None) -> Track | None:
    """Deterministic choice for a mood: tracks where it is the main tag come first."""
    catalog = load_catalog() if catalog is None else catalog
    if not catalog:
        return None
    for wanted in [mood, *FALLBACKS.get(mood, [])]:
        matching = [t for t in catalog if wanted in t.moods]
        if matching:
            best = min(t.moods.index(wanted) for t in matching)
            pool = sorted(
                (t for t in matching if t.moods.index(wanted) == best), key=lambda t: t.id
            )
            return pool[seed % len(pool)]
    return sorted(catalog, key=lambda t: t.id)[seed % len(catalog)]


def resolve_music(choice: str | None, scenes: list[tuple[str, float]], seed: int) -> Track | None:
    """choice: None/`auto` -> by mood, `none` -> no music, otherwise a track id.

    An unknown id (e.g. a track removed from the library) falls back to `auto`."""
    if choice == NONE:
        return None
    if choice not in (None, AUTO) and (track := get_track(choice)) is not None:
        return track
    return pick_track(dominant_mood(scenes), seed)
