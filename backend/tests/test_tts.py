import sys
from types import SimpleNamespace

import pytest

from app.services.tts import (
    EdgeTTSEngine,
    TTSError,
    Word,
    prepare_text,
    probe_duration,
    synthesize_scenes,
)


class FakeEngine:
    name = "fake"

    def __init__(self, fail_times: int = 0):
        self.calls: list[tuple] = []
        self.fail_times = fail_times

    def synthesize(self, text, voice, rate, pitch, out):
        self.calls.append((text, voice, rate, pitch))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("network down")
        out.write_bytes(b"ID3" + b"\0" * 100)
        words = text.rstrip(".").split()
        return [Word(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate(words)]


def fixed_duration(_path):
    return 2.0


def test_prepare_text_adds_final_punctuation():
    assert prepare_text("  Лиса   жила\nв лесу ") == "Лиса жила в лесу."
    assert prepare_text("Правда?") == "Правда?"


def test_synthesize_scenes_returns_audio_words_duration(tmp_path):
    engine = FakeEngine()
    results = synthesize_scenes(
        ["Лиса жила в лесу", "Она нашла камень."],
        voice="ru-RU-SvetlanaNeural",
        rate="+10%",
        out_dir=tmp_path,
        engine=engine,
        duration_fn=fixed_duration,
    )
    assert [r.ok for r in results] == [True, True]
    assert results[0].path.name == "scene_00.mp3"
    assert [w.text for w in results[0].words] == ["Лиса", "жила", "в", "лесу"]
    assert results[0].duration == 2.0
    assert ("Лиса жила в лесу.", "ru-RU-SvetlanaNeural", "+10%", "+0Hz") in engine.calls


def test_duration_never_shorter_than_words(tmp_path):
    results = synthesize_scenes(
        ["one two three four five six seven"],
        voice="en-US-AriaNeural",
        out_dir=tmp_path,
        engine=FakeEngine(),
        duration_fn=lambda _: 0.1,
    )
    assert results[0].duration == pytest.approx(6 * 0.4 + 0.35)


def test_cache_reuses_audio_and_words(tmp_path):
    engine = FakeEngine()
    kwargs = dict(
        voice="en-US-GuyNeural",
        engine=engine,
        cache_dir=tmp_path / "cache",
        duration_fn=fixed_duration,
    )
    synthesize_scenes(["Hello world"], out_dir=tmp_path / "a", **kwargs)
    again = synthesize_scenes(["Hello world"], out_dir=tmp_path / "b", **kwargs)
    assert again[0].cached and again[0].path.exists()
    assert [w.text for w in again[0].words] == ["Hello", "world"]
    assert len(engine.calls) == 1


def test_retries_then_reports_error(tmp_path):
    ok = synthesize_scenes(
        ["Hi there"],
        voice="en-US-GuyNeural",
        out_dir=tmp_path,
        engine=FakeEngine(fail_times=2),
        duration_fn=fixed_duration,
    )
    assert ok[0].ok
    failed = synthesize_scenes(
        ["Hi there"],
        voice="en-US-GuyNeural",
        out_dir=tmp_path,
        engine=FakeEngine(fail_times=5),
        duration_fn=fixed_duration,
    )
    assert not failed[0].ok and "network down" in failed[0].error


def test_unknown_voice_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown voice"):
        synthesize_scenes(["x"], voice="xx-XX-Nobody", out_dir=tmp_path, engine=FakeEngine())


def fake_edge_module(chunks):
    class Communicate:
        def __init__(self, text, voice, **kwargs):
            self.kwargs = kwargs

        def stream_sync(self):
            yield from chunks

    return SimpleNamespace(Communicate=Communicate)


def test_edge_engine_parses_stream(tmp_path, monkeypatch):
    chunks = [
        {"type": "WordBoundary", "offset": 1_000_000, "duration": 4_000_000, "text": "Привет"},
        {"type": "audio", "data": b"mp3data"},
        {"type": "WordBoundary", "offset": 6_000_000, "duration": 3_000_000, "text": "мир"},
    ]
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_module(chunks))
    out = tmp_path / "a.mp3"
    words = EdgeTTSEngine().synthesize("Привет, мир.", "ru-RU-DmitryNeural", "+0%", "+0Hz", out)
    assert out.read_bytes() == b"mp3data"
    assert words[0] == Word("Привет", 0.1, 0.5)
    assert words[1].start == pytest.approx(0.6) and words[1].end == pytest.approx(0.9)
    assert not list(tmp_path.glob(".tts-*"))  # temp file replaced


def test_edge_engine_rejects_empty_audio(tmp_path, monkeypatch):
    chunks = [{"type": "WordBoundary", "offset": 0, "duration": 10, "text": "x"}]
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_module(chunks))
    out = tmp_path / "a.mp3"
    with pytest.raises(TTSError, match="no audio"):
        EdgeTTSEngine().synthesize("x", "en-US-GuyNeural", "+0%", "+0Hz", out)
    assert not out.exists() and not list(tmp_path.glob(".tts-*"))


def test_probe_duration_falls_back_to_bitrate(tmp_path, monkeypatch):
    path = tmp_path / "a.mp3"
    path.write_bytes(b"\0" * 6000)  # 6000 bytes at 48 kbit/s = 1 s
    monkeypatch.setenv("PATH", "")  # no ffprobe
    assert probe_duration(path) == pytest.approx(1.0)
