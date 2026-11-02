"""Video assembly with FFmpeg (FR-4.1–FR-4.6, FR-6.3, FR-6.4). See docs/ARCHITECTURE.md §6.

One image per scene becomes a Ken Burns clip (`zoompan`); clips are joined with `xfade`,
the logo and subtitles are burned in during the same encode, narration is placed with
`adelay`, normalized with `loudnorm` and mixed with optional background music that is
ducked under the voice. Look and timing come from the format template (templates/*.json).

Timeline (T = transition, p_i = silence after scene i, d_i = its length):
    clip_i  = d_i + p_i + T   (the last clip has no T)
    start_0 = 0, start_{i+1} = start_i + clip_i - T   (= xfade offset)
Narration of scene i+1 starts at start_{i+1}, i.e. p_i seconds after the previous one
ended, exactly when the crossfade into scene i+1 begins: no voice is ever cut. Intro and
outro cards are scenes without narration (and p = 0).
"""

import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.config import Settings
from app.services.branding import Branding, fonts_dir
from app.services.images.crop import OUTPUT_SIZES
from app.services.subtitles import (
    SubtitleStyle,
    build_cues,
    place_on_timeline,
    to_ass,
    to_srt,
)
from app.services.templates import Template, get_template
from app.services.tts import Word

log = logging.getLogger(__name__)

ZOOM = 0.15  # default Ken Burns zoom amount (templates override it)
MUSIC_FADE_IN = 0.8
MUSIC_FADE_OUT = 1.5


class CompositorError(RuntimeError):
    pass


@dataclass
class RenderScene:
    image: Path
    audio: Path | None  # None for intro/outro cards
    duration: float  # narration length (card length for cards), seconds
    words: list[Word]
    narration: str
    camera: str = "zoom_in"
    pause: float | None = None  # silence after the scene; None = the default pause


@dataclass
class Timeline:
    clip_durations: list[float]
    starts: list[float]
    total: float


@dataclass
class LogoOverlay:
    path: Path
    width: int
    x: str  # ffmpeg overlay expressions
    y: str
    opacity: float
    start: float  # visible only while narrated scenes play
    end: float


@dataclass
class RenderResult:
    video: Path
    srt: Path
    ass: Path
    duration: float
    timings: dict[str, float] = field(default_factory=dict)


def compute_timeline(
    durations: list[float], pause: float, transition: float, pauses: list[float] | None = None
) -> Timeline:
    if not durations:
        raise ValueError("no scenes to render")
    pauses = pauses or [pause] * len(durations)
    last = len(durations) - 1
    clips = [d + pauses[i] + (transition if i < last else 0.0) for i, d in enumerate(durations)]
    starts = [0.0]
    for clip in clips[:-1]:
        starts.append(starts[-1] + clip - transition)
    return Timeline(clips, starts, starts[-1] + clips[-1])


def _zoompan(camera: str, frames: int, zoom: float) -> str:
    progress = f"on/{frames}"
    center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    expressions = {
        "zoom_in": (f"1+{zoom:g}*{progress}", center_x, center_y),
        "zoom_out": (f"{1 + zoom:g}-{zoom:g}*{progress}", center_x, center_y),
        "pan_right": ("1.12", f"(iw-iw/zoom)*{progress}", center_y),
        "pan_left": ("1.12", f"(iw-iw/zoom)*(1-{progress})", center_y),
        "static": ("1.03", center_x, center_y),
    }
    z, x, y = expressions.get(camera, expressions["static"])
    return f"zoompan=z='{z}':x='{x}':y='{y}'"


def kenburns_cmd(
    image: Path,
    out: Path,
    duration: float,
    size: tuple[int, int],
    camera: str,
    *,
    zoom: float = ZOOM,
    fps: int = 30,
    preset: str = "veryfast",
    crf: int = 20,
    upscale: float = 2.0,
) -> list[str]:
    width, height = size
    frames = max(1, round(duration * fps))
    # Upscale first: zoompan rounds coordinates to whole pixels, which jitters otherwise.
    vf = (
        f"scale={round(upscale * width)}:{round(upscale * height)},"
        f"{_zoompan(camera, frames, zoom)}:d={frames}:s={width}x{height}:fps={fps},format=yuv420p"
    )
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(image), "-vf", vf, "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf), str(out),
    ]  # fmt: skip


def audio_cmd(
    voices: list[Path],
    starts: list[float],
    total: float,
    out: Path,
    *,
    music: Path | None = None,
    music_volume: float = 0.25,
) -> list[str]:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for voice in voices:
        cmd += ["-i", str(voice)]
    parts = []
    for i, start in enumerate(starts):
        delay = round(start * 1000)
        parts.append(
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={delay}:all=1[a{i}]"
        )
    labels = "".join(f"[a{i}]" for i in range(len(voices)))
    # loudnorm resamples to 192 kHz internally, so resample back afterwards.
    parts.append(
        f"{labels}amix=inputs={len(voices)}:normalize=0:duration=longest,"
        f"apad,atrim=0:{total:.3f},loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[voice]"
    )
    if music is None:
        out_label = "[voice]"
    else:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        m = len(voices)
        fade_out = min(MUSIC_FADE_OUT, total)
        parts.append("[voice]asplit=2[vmix][vkey]")
        parts.append(
            f"[{m}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume={music_volume:g},atrim=0:{total:.3f},"
            f"afade=t=in:st=0:d={MUSIC_FADE_IN},"
            f"afade=t=out:st={total - fade_out:.3f}:d={fade_out:.3f}[music]"
        )
        parts.append(
            "[music][vkey]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400[ducked]"
        )
        parts.append("[vmix][ducked]amix=inputs=2:normalize=0:duration=first[mix]")
        out_label = "[mix]"
    cmd += [
        "-filter_complex", ";".join(parts), "-map", out_label,
        "-c:a", "aac", "-b:a", "160k", str(out),
    ]  # fmt: skip
    return cmd


def logo_overlay(
    path: Path,
    position: str,
    scale: float,
    opacity: float,
    size: tuple[int, int],
    safe_top: float,
    safe_bottom: float,
    start: float,
    end: float,
) -> LogoOverlay:
    """Places the logo in a corner, outside the platform UI safe zones (top/bottom bands)."""
    width, height = size
    margin_x = round(0.04 * width)
    margin_top = max(margin_x, round(safe_top * height))
    margin_bottom = max(margin_x, round(safe_bottom * height))
    vertical, horizontal = position.split("-")
    x = f"{margin_x}" if horizontal == "left" else f"W-w-{margin_x}"
    y = f"{margin_top}" if vertical == "top" else f"H-h-{margin_bottom}"
    return LogoOverlay(path, round(scale * width), x, y, opacity, start, end)


def _filter_path(path: Path) -> str:
    """Escape a path for use inside a filtergraph option value."""
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def compose_cmd(
    clips: list[Path],
    timeline: Timeline,
    audio: Path,
    ass_name: str,
    out: Path,
    *,
    transition: str = "fade",
    transition_sec: float = 0.4,
    logo: LogoOverlay | None = None,
    fontsdir: Path | None = None,
    preset: str = "veryfast",
    crf: int = 21,
) -> list[str]:
    """Joins clips with xfade, adds the logo, burns subtitles and muxes audio in one encode.

    `ass_name` must be relative to the working directory ffmpeg runs in.
    """
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for clip in clips:
        cmd += ["-i", str(clip)]
    cmd += ["-i", str(audio)]
    if logo is not None:
        cmd += ["-i", str(logo.path)]

    parts, current = [], "[0:v]"
    for i in range(1, len(clips)):
        label = f"[x{i}]"
        parts.append(
            f"{current}[{i}:v]xfade=transition={transition}:duration={transition_sec}:"
            f"offset={timeline.starts[i]:.3f}{label}"
        )
        current = label
    if logo is not None:
        parts.append(
            f"[{len(clips) + 1}:v]scale={logo.width}:-1,format=rgba,"
            f"colorchannelmixer=aa={logo.opacity:g}[lg]"
        )
        parts.append(
            f"{current}[lg]overlay=x={logo.x}:y={logo.y}:"
            f"enable='between(t,{logo.start:.3f},{logo.end:.3f})'[vl]"
        )
        current = "[vl]"
    ass = f"ass={ass_name}"
    if fontsdir is not None:
        ass += f":fontsdir={_filter_path(fontsdir)}"
    parts.append(f"{current}{ass}[v]")

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[v]", "-map", f"{len(clips)}:a",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-t", f"{timeline.total:.3f}", "-movflags", "+faststart", str(out),
    ]  # fmt: skip
    return cmd


def run_ffmpeg(cmd: list[str], cwd: Path | None = None) -> None:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise CompositorError("ffmpeg is not installed") from exc
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise CompositorError(f"ffmpeg failed ({proc.returncode}): {tail}")


# 480p preview (FR-7.5): speed over quality; no paid calls either way.
DRAFT_ENCODE = {
    "fps": 24, "preset": "ultrafast", "clip_preset": "ultrafast",
    "clip_crf": 28, "crf": 30, "upscale": 1.25,
}  # fmt: skip


def encode_options(settings: Settings, draft: bool = False) -> dict:
    """FFmpeg quality/speed knobs for `render_video`, from settings (or the draft profile)."""
    if draft:
        return {**DRAFT_ENCODE, "fps": min(settings.render_fps, 24),
                "concurrency": settings.render_concurrency}  # fmt: skip
    return {
        "fps": settings.render_fps,
        "preset": settings.ffmpeg_preset,
        "crf": settings.ffmpeg_crf,
        "clip_preset": settings.ffmpeg_clip_preset,
        "clip_crf": settings.ffmpeg_clip_crf,
        "upscale": settings.ffmpeg_upscale,
        "concurrency": settings.render_concurrency,
    }


def _scaled_style(style: SubtitleStyle, height: int, full_height: int) -> SubtitleStyle:
    if height == full_height:
        return style
    k = height / full_height
    return replace(
        style,
        size=max(8, round(style.size * k)),
        margin_v=round(style.margin_v * k),
        outline=max(1, round(style.outline * k)),
    )


def render_video(
    scenes: list[RenderScene],
    out_dir: Path,
    format: str,
    *,
    size: tuple[int, int] | None = None,
    template: Template | None = None,
    branding: Branding | None = None,
    logo: Path | None = None,
    intro: RenderScene | None = None,
    outro: RenderScene | None = None,
    music: Path | None = None,
    music_volume: float | None = None,
    pause: float = 0.4,
    fps: int = 30,
    preset: str = "veryfast",
    crf: int = 21,
    clip_preset: str | None = None,
    clip_crf: int = 20,
    upscale: float = 2.0,
    concurrency: int = 2,
    subtitle_style: SubtitleStyle | None = None,
    fontsdir: Path | None = None,
) -> RenderResult:
    if format not in OUTPUT_SIZES:
        raise ValueError(f"unknown format {format!r}")
    template = template or get_template(format)
    branding = branding or Branding()
    fontsdir = fontsdir or (fonts_dir() if fonts_dir().is_dir() else None)
    out_dir = out_dir.resolve()
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    full_w, full_h = OUTPUT_SIZES[format]
    width, height = size or (full_w, full_h)

    sequence = [s for s in (intro, *scenes, outro) if s is not None]
    pauses = [pause if s.pause is None else s.pause for s in sequence]
    transition_sec = template.transition.duration
    timeline = compute_timeline([s.duration for s in sequence], pause, transition_sec, pauses)
    timings: dict[str, float] = {}

    started = time.monotonic()
    clips = [work / f"clip_{i:02d}.mp4" for i in range(len(sequence))]
    commands = [
        kenburns_cmd(
            scene.image.resolve(), clip, duration, (width, height), scene.camera,
            zoom=template.ken_burns_zoom, fps=fps, preset=clip_preset or preset, crf=clip_crf,
            upscale=upscale,
        )
        for scene, clip, duration in zip(sequence, clips, timeline.clip_durations, strict=True)
    ]  # fmt: skip
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        list(pool.map(run_ffmpeg, commands))
    timings["clips"] = time.monotonic() - started

    started = time.monotonic()
    style = _scaled_style(subtitle_style or template.subtitle_style(branding), height, full_h)
    words = place_on_timeline(
        [(start, s.words, s.narration) for start, s in zip(timeline.starts, sequence, strict=True)]
    )
    cues = build_cues(words, max_chars=style.max_chars)
    srt = out_dir / "subtitles.srt"
    ass = out_dir / "subtitles.ass"
    srt.write_text(to_srt(cues), encoding="utf-8")
    ass.write_text(to_ass(cues, width, height, style), encoding="utf-8")
    timings["subtitles"] = time.monotonic() - started

    started = time.monotonic()
    narrated = [(s, start) for s, start in zip(sequence, timeline.starts, strict=True) if s.audio]
    audio = work / "audio.m4a"
    run_ffmpeg(
        audio_cmd(
            [s.audio.resolve() for s, _ in narrated], [start for _, start in narrated],
            timeline.total, audio, music=music.resolve() if music else None,
            music_volume=template.music_volume if music_volume is None else music_volume,
        )
    )  # fmt: skip
    timings["audio"] = time.monotonic() - started

    started = time.monotonic()
    overlay = None
    if logo is not None:
        first = 1 if intro is not None else 0
        end = timeline.starts[len(sequence) - 1] if outro is not None else timeline.total
        spec = template.logo
        overlay = logo_overlay(
            logo.resolve(), branding.logo_position or spec.position, spec.scale,
            branding.logo_opacity or spec.opacity, (width, height),
            template.safe_area.top, template.safe_area.bottom, timeline.starts[first], end,
        )  # fmt: skip
    video = out_dir / "video.mp4"
    run_ffmpeg(
        compose_cmd(
            clips, timeline, audio, ass.name, video, transition=template.transition.type,
            transition_sec=transition_sec, logo=overlay, fontsdir=fontsdir, preset=preset, crf=crf,
        ),
        cwd=out_dir,
    )  # fmt: skip
    timings["compose"] = time.monotonic() - started
    return RenderResult(video, srt, ass, timeline.total, timings)
