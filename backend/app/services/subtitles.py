"""Subtitles from TTS word timings: SRT file and styled ASS for burning in (FR-3.4, FR-4.3, FR-4.4).

`srt_timestamp` rounds to milliseconds before splitting into h/m/s, as in
MoneyPrinterTurbo's `mktimestamp` (app/services/voice.py, MIT License), so 59.9996 s
never becomes `00:00:60,000`. See NOTICE.
"""

import re
from dataclasses import dataclass, field, replace

from app.services.tts import Word

SENTENCE_END = (".", "!", "?", "…")
MAX_CUE_SECONDS = 3.5
MAX_WORD_GAP = 0.6  # longer silence (e.g. between scenes) always starts a new cue
LINGER_SECONDS = 0.25  # keep a cue on screen a bit after the last word


@dataclass
class Cue:
    start: float
    end: float
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass(frozen=True)
class SubtitleStyle:
    font: str = "DejaVu Sans"
    size: int = 60
    bold: bool = True
    primary: str = "&H00FFFFFF"  # ASS colours are &HAABBGGRR
    highlight: str = "&H0000D7FF"  # gold, current word in karaoke mode
    outline_color: str = "&H00000000"
    outline: int = 4
    shadow: int = 0
    alignment: int = 2  # numpad layout: 2 = bottom centre, 5 = middle centre
    margin_v: int = 120
    mode: str = "phrase"  # phrase | karaoke
    max_chars: int = 36


# Defaults per format; stage 6 templates (templates/*.json) override them.
STYLE_DEFAULTS = {
    "9:16": SubtitleStyle(size=78, alignment=5, margin_v=0, mode="karaoke", max_chars=22),
    "16:9": SubtitleStyle(size=56, alignment=2, margin_v=80, mode="phrase", max_chars=42),
    "1:1": SubtitleStyle(size=62, alignment=2, margin_v=110, mode="phrase", max_chars=30),
}


def _norm(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())


def attach_punctuation(words: list[Word], narration: str) -> list[Word]:
    """Edge TTS boundaries carry bare words; take the display text (with punctuation)
    from the original narration, matching tokens in order."""
    tokens = narration.split()
    result: list[Word] = []
    pos = 0
    for word in words:
        target = _norm(word.text)
        for look_ahead in range(pos, min(pos + 3, len(tokens))):
            if target and _norm(tokens[look_ahead]).startswith(target):
                result.append(replace(word, text=tokens[look_ahead]))
                pos = look_ahead + 1
                break
        else:
            result.append(word)
    return result


def place_on_timeline(scenes: list[tuple[float, list[Word], str]]) -> list[Word]:
    """(scene start on the video timeline, scene words, scene narration) -> absolute words."""
    timeline: list[Word] = []
    for offset, words, narration in scenes:
        for word in attach_punctuation(words, narration):
            timeline.append(Word(word.text, word.start + offset, word.end + offset))
    return timeline


def build_cues(words: list[Word], max_chars: int = 36) -> list[Cue]:
    cues: list[Cue] = []
    current: Cue | None = None
    for word in words:
        if current is not None:
            prev = current.words[-1]
            too_long = len(current.text) + 1 + len(word.text) > max_chars
            too_slow = word.end - current.start > MAX_CUE_SECONDS
            pause = word.start - prev.end > MAX_WORD_GAP
            sentence = prev.text.endswith(SENTENCE_END)
            clause = prev.text.endswith((",", ";", ":")) and len(current.text) > max_chars // 2
            if too_long or too_slow or pause or sentence or clause:
                cues.append(current)
                current = None
        if current is None:
            current = Cue(word.start, word.end, [word])
        else:
            current.words.append(word)
            current.end = word.end
    if current is not None:
        cues.append(current)

    for this, nxt in zip(cues, cues[1:], strict=False):
        this.end = min(this.end + LINGER_SECONDS, nxt.start)
    if cues:
        cues[-1].end += LINGER_SECONDS
    return cues


def srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def ass_timestamp(seconds: float) -> str:
    total_cs = int(round(seconds * 100))
    hours, rest = divmod(total_cs, 360_000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{srt_timestamp(c.start)} --> {srt_timestamp(c.end)}\n{c.text}\n"
        for i, c in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def _karaoke_line(cue: Cue) -> str:
    parts = []
    for word, nxt in zip(cue.words, [*cue.words[1:], None], strict=True):
        until = nxt.start if nxt is not None else cue.end
        centis = max(1, round((until - word.start) * 100))
        parts.append(f"{{\\kf{centis}}}{_ass_escape(word.text)}")
    # Leading gap between cue start and the first word is zero by construction.
    return " ".join(parts)


def to_ass(cues: list[Cue], width: int, height: int, style: SubtitleStyle) -> str:
    karaoke = style.mode == "karaoke"
    # In karaoke, PrimaryColour is the "already spoken" fill, SecondaryColour the rest.
    primary, secondary = (style.highlight, style.primary) if karaoke else (style.primary,) * 2
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style.font},{style.size},{primary},{secondary},{style.outline_color},"
        f"&H80000000,{-1 if style.bold else 0},0,0,0,100,100,0,0,1,{style.outline},"
        f"{style.shadow},{style.alignment},60,60,{style.margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{ass_timestamp(c.start)},{ass_timestamp(c.end)},Default,,0,0,0,,"
        + (_karaoke_line(c) if karaoke else _ass_escape(c.text))
        for c in cues
    ]
    return header + "\n".join(lines) + "\n"
