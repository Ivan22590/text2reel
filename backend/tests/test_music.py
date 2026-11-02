import hashlib

from app.config import get_settings
from app.services.music import (
    Track,
    dominant_mood,
    get_track,
    is_valid_choice,
    load_catalog,
    pick_track,
    resolve_music,
)

MOODS = {"calm", "happy", "epic", "sad", "tense", "corporate", "mysterious"}


def track(track_id: str, *moods: str) -> Track:
    return Track(
        id=track_id, title=track_id, artist="x", file=f"{track_id}.ogg", duration=100,
        moods=list(moods), license="CC0 1.0", source="https://example.test", size=1, sha256="0",
    )  # fmt: skip


def test_library_has_enough_licensed_tracks():
    catalog = load_catalog()
    assert 10 <= len(catalog) <= 15
    ids = [t.id for t in catalog]
    assert len(set(ids)) == len(ids)
    for t in catalog:
        assert t.path.is_file(), t.id
        assert t.license.startswith("CC0"), t.id
        assert t.source.startswith("https://commons.wikimedia.org/wiki/File:"), t.id
        assert t.moods and set(t.moods) <= MOODS, t.id
        assert t.duration > 30, t.id


def test_files_match_catalog_checksums():
    for t in load_catalog():
        data = t.path.read_bytes()
        assert data[:4] == b"OggS", t.id
        assert len(data) == t.size and hashlib.sha256(data).hexdigest() == t.sha256, t.id


def test_every_mood_is_covered():
    assert {m for t in load_catalog() for m in t.moods} == MOODS


def test_license_file_lists_every_track():
    text = (get_settings().assets_dir / "music" / "LICENSES.md").read_text(encoding="utf-8")
    for t in load_catalog():
        assert f"`{t.file}`" in text and t.source in text


def test_dominant_mood_is_weighted_by_duration_and_ties_use_priority():
    assert dominant_mood([("calm", 3.0), ("epic", 2.0), ("calm", 2.0)]) == "calm"
    assert dominant_mood([("calm", 5.0), ("epic", 5.0)]) == "epic"  # tie -> priority order
    assert dominant_mood([("sad", 0.0), ("sad", 0.0), ("happy", 0.0)]) == "sad"  # no lengths yet
    assert dominant_mood([]) == "calm"


def test_pick_is_deterministic_and_prefers_main_tag():
    catalog = [track("a", "calm"), track("b", "calm"), track("c", "epic", "calm")]
    assert pick_track("calm", 0, catalog).id == "a"
    assert pick_track("calm", 1, catalog).id == "b"
    assert pick_track("calm", 2, catalog).id == "a"  # wraps around
    assert pick_track("calm", 7, catalog) == pick_track("calm", 7, catalog)
    # "c" has calm only as a secondary tag, so it is never chosen while main-tag tracks exist
    assert {pick_track("calm", s, catalog).id for s in range(10)} == {"a", "b"}


def test_missing_mood_falls_back_to_a_related_one():
    catalog = [track("t", "tense"), track("c", "calm")]
    assert pick_track("mysterious", 0, catalog).id == "t"  # mysterious -> tense
    assert pick_track("sad", 0, catalog).id == "c"  # sad -> calm
    assert pick_track("happy", 0, [track("only", "epic")]).id == "only"  # anything beats silence
    assert pick_track("calm", 0, []) is None


def test_resolve_music_modes():
    scenes = [("epic", 4.0)]
    assert resolve_music("none", scenes, 1) is None
    assert resolve_music("auto", scenes, 1).moods[0] == "epic"
    assert resolve_music(None, scenes, 1).moods[0] == "epic"
    assert resolve_music("calm-blue-whale", scenes, 1).id == "calm-blue-whale"
    assert resolve_music("deleted-track", scenes, 1).moods[0] == "epic"  # unknown id -> auto


def test_choice_validation():
    assert is_valid_choice("auto") and is_valid_choice("none")
    assert is_valid_choice(load_catalog()[0].id)
    assert not is_valid_choice("nope")
    assert get_track("nope") is None
