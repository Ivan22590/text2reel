import pytest

from app.services.subtitles import (
    attach_punctuation,
    build_cues,
    place_on_timeline,
    srt_timestamp,
    to_ass,
    to_srt,
)
from app.services.templates import get_template
from app.services.tts import Word


def words_from(text: str, step: float = 0.4) -> list[Word]:
    bare = [w.strip(".,!?") for w in text.split()]
    return [Word(w, i * step, i * step + step * 0.9) for i, w in enumerate(bare)]


def test_srt_timestamp_rounds_without_overflow():
    assert srt_timestamp(0) == "00:00:00,000"
    assert srt_timestamp(59.9996) == "00:01:00,000"
    assert srt_timestamp(3725.5) == "01:02:05,500"


def test_attach_punctuation_from_narration():
    narration = "Лиса жила, на краю леса."
    words = attach_punctuation(words_from(narration), narration)
    assert [w.text for w in words] == ["Лиса", "жила,", "на", "краю", "леса."]


def test_place_on_timeline_offsets_scenes():
    placed = place_on_timeline(
        [(0.0, words_from("One two."), "One two."), (5.0, words_from("Three."), "Three.")]
    )
    assert placed[2].text == "Three." and placed[2].start == pytest.approx(5.0)


def test_cues_break_on_sentence_length_and_pause():
    text = "Короткая фраза. А это предложение заметно длиннее чем лимит символов строки"
    cues = build_cues(place_on_timeline([(0, words_from(text), text)]), max_chars=24)
    assert cues[0].text == "Короткая фраза."
    assert all(len(c.text) <= 24 for c in cues)
    # cue ends never overlap the next cue
    assert all(a.end <= b.start for a, b in zip(cues, cues[1:], strict=False))

    gap = place_on_timeline([(0, words_from("Один"), "Один"), (3, words_from("Два"), "Два")])
    assert len(build_cues(gap, max_chars=40)) == 2


def test_srt_format():
    cues = build_cues(place_on_timeline([(0, words_from("Привет мир."), "Привет мир.")]))
    srt = to_srt(cues)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,010\n")
    assert "Привет мир." in srt


def test_ass_phrase_and_karaoke():
    cues = build_cues(
        place_on_timeline([(1.0, words_from("Hello {big} world."), "Hello {big} world.")])
    )
    phrase = to_ass(cues, 1920, 1080, get_template("16:9").subtitle_style())
    assert "PlayResX: 1920" in phrase and "PlayResY: 1080" in phrase
    assert "Dialogue: 0,0:00:01.00," in phrase
    assert "(big)" in phrase and "{big}" not in phrase  # braces would be override tags

    karaoke = to_ass(cues, 1080, 1920, get_template("9:16").subtitle_style())
    assert "{\\kf40}Hello" in karaoke
    style_line = next(line for line in karaoke.splitlines() if line.startswith("Style:"))
    assert ",5,60,60,0,1" in style_line  # middle-centre alignment for vertical video
