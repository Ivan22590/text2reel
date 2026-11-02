"""Stage 3: narration with Edge TTS and word timings (FR-3.1–FR-3.4).

Adapted from MoneyPrinterTurbo (https://github.com/harry0703/MoneyPrinterTurbo,
app/services/voice.py, MIT License, (c) harry0703 and contributors): edge-tts 7
streaming with `boundary="WordBoundary"`, writing to a temp file that replaces the
target only after a complete attempt, retries. See NOTICE.

Edge TTS no longer accepts custom SSML, so pauses between scenes are added as silence
by the compositor (`TTS_SCENE_PAUSE_SEC`); pauses inside a scene come from punctuation.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

# Voices offered in the UI (FR-3.1): id -> label.
VOICES = {
    "ru-RU-SvetlanaNeural": "Светлана (RU, женский)",
    "ru-RU-DmitryNeural": "Дмитрий (RU, мужской)",
    "en-US-AriaNeural": "Aria (EN, female)",
    "en-US-GuyNeural": "Guy (EN, male)",
    "en-US-JennyNeural": "Jenny (EN, female)",
}
EDGE_TICKS_PER_SECOND = 10_000_000  # edge-tts offsets are in 100 ns units
EDGE_MP3_BITRATE = 48_000  # audio-24khz-48kbitrate-mono-mp3
ATTEMPTS = 3


class TTSError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    start: float  # seconds from the start of the scene audio
    end: float


@dataclass
class Narration:
    index: int
    path: Path | None = None
    duration: float = 0.0
    words: list[Word] | None = None
    cached: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.path is not None


class TTSEngine(Protocol):
    name: str

    def synthesize(self, text: str, voice: str, rate: str, pitch: str, out: Path) -> list[Word]:
        """Writes audio to `out` and returns word timings."""
        ...


class EdgeTTSEngine:
    name = "edge"

    def synthesize(self, text: str, voice: str, rate: str, pitch: str, out: Path) -> list[Word]:
        import edge_tts

        communicate = edge_tts.Communicate(
            text, voice, rate=rate, pitch=pitch, boundary="WordBoundary"
        )
        words: list[Word] = []
        out.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_path = tempfile.mkstemp(prefix=".tts-", suffix=out.suffix, dir=out.parent)
        try:
            with os.fdopen(descriptor, "wb") as file:
                for chunk in communicate.stream_sync():
                    if chunk["type"] == "audio":
                        file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        start = chunk["offset"] / EDGE_TICKS_PER_SECOND
                        end = (chunk["offset"] + chunk["duration"]) / EDGE_TICKS_PER_SECOND
                        words.append(Word(chunk["text"], start, end))
            # Edge can finish a stream with timing events but no audio payload.
            if os.path.getsize(temp_path) == 0:
                raise TTSError("Edge TTS returned no audio")
            if not words:
                raise TTSError("Edge TTS returned no word boundaries")
            os.replace(temp_path, out)
            temp_path = None
        finally:
            if temp_path is not None and os.path.exists(temp_path):
                os.remove(temp_path)
        return words


def prepare_text(text: str) -> str:
    """Normalizes narration for TTS: single spaces, final punctuation for a falling intonation."""
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?…":
        text += "."
    return text


def probe_duration(path: Path) -> float:
    """Audio duration via ffprobe; falls back to the constant Edge MP3 bitrate."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return float(out.stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return path.stat().st_size * 8 / EDGE_MP3_BITRATE


def _cache_key(engine: str, text: str, voice: str, rate: str, pitch: str) -> str:
    raw = json.dumps([engine, text, voice, rate, pitch], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def synthesize_scene(
    index: int,
    text: str,
    *,
    voice: str,
    rate: str,
    pitch: str,
    out_dir: Path,
    engine: TTSEngine,
    cache_dir: Path | None = None,
    duration_fn: Callable[[Path], float] = probe_duration,
) -> Narration:
    text = prepare_text(text)
    result = Narration(index)
    out = out_dir / f"scene_{index:02d}.mp3"
    out_dir.mkdir(parents=True, exist_ok=True)

    key = _cache_key(engine.name, text, voice, rate, pitch)
    cached_audio = cache_dir / f"{key}.mp3" if cache_dir else None
    cached_words = cache_dir / f"{key}.json" if cache_dir else None
    if cached_audio and cached_audio.exists() and cached_words.exists():
        out.write_bytes(cached_audio.read_bytes())
        words = [Word(**w) for w in json.loads(cached_words.read_text(encoding="utf-8"))]
        result.cached = True
    else:
        words = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                words = engine.synthesize(text, voice, rate, pitch, out)
                result.error = None
                break
            except Exception as exc:  # edge-tts raises various network/protocol errors
                log.warning("scene %d TTS attempt %d failed: %s", index, attempt, exc)
                result.error = f"TTS failed: {exc}"
        if words is None:
            return result
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_audio.write_bytes(out.read_bytes())
            cached_words.write_text(json.dumps([asdict(w) for w in words]), encoding="utf-8")

    result.path = out
    result.words = words
    # The audio may end a bit after the last word; never report less than the words span.
    result.duration = max(duration_fn(out), words[-1].end if words else 0.0)
    return result


def synthesize_scenes(
    texts: list[str],
    *,
    voice: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    out_dir: Path,
    engine: TTSEngine | None = None,
    cache_dir: Path | None = None,
    concurrency: int = 4,
    duration_fn: Callable[[Path], float] = probe_duration,
) -> list[Narration]:
    if voice not in VOICES:
        raise ValueError(f"unknown voice {voice!r}, expected one of {sorted(VOICES)}")
    engine = engine or EdgeTTSEngine()
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [
            pool.submit(
                synthesize_scene,
                index,
                text,
                voice=voice,
                rate=rate,
                pitch=pitch,
                out_dir=out_dir,
                engine=engine,
                cache_dir=cache_dir,
                duration_fn=duration_fn,
            )
            for index, text in enumerate(texts)
        ]
        return [future.result() for future in futures]
