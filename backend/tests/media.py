"""Helpers that create real media files with ffmpeg / Pillow for end-to-end tests."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.services.tts import Word

requires_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed"
)


def make_image(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def make_tone(path: Path, seconds: float, freq: int = 440) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:duration={seconds}", "-ac", "1", "-b:a", "48k", str(path)],
        check=True,
    )  # fmt: skip
    return path


def fake_words(text: str, seconds: float) -> list[Word]:
    tokens = [t.strip(".,!?") for t in text.split()]
    step = seconds / len(tokens)
    return [Word(t, i * step, (i + 0.9) * step) for i, t in enumerate(tokens)]


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(out.stdout)


class ToneTTSEngine:
    """TTS stand-in that writes a real MP3 tone: 0.3 s per word."""

    name = "tone"

    def synthesize(self, text, voice, rate, pitch, out):
        seconds = 0.3 * len(text.split())
        make_tone(out, seconds)
        return fake_words(text, seconds)
