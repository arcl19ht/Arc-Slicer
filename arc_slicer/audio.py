"""Audio probing and ffmpeg slicing helpers."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Callable

from arc_slicer.paths import RES_DIR, _FFMPEG_BUNDLED
from arc_slicer.segments import parse_duration_to_ms, validate_speed_value

_FFMPEG_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


def _get_ffmpeg() -> str:
    if _FFMPEG_BUNDLED.exists():
        return str(_FFMPEG_BUNDLED)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError("ffmpeg not found")


def parse_ffmpeg_duration_to_ms(text: str) -> int:
    m = _FFMPEG_DURATION_RE.search(text or "")
    if not m:
        raise ValueError("ffmpeg duration not found")
    hours = int(m.group(1))
    minutes = int(m.group(2))
    seconds = Decimal(m.group(3))
    total = Decimal(hours * 3600 + minutes * 60) + seconds
    return parse_duration_to_ms(total)


def _get_ffprobe() -> str:
    candidates = []
    bundled = RES_DIR / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    candidates.append(bundled)
    try:
        ffmpeg_path = Path(_get_ffmpeg())
        candidates.append(ffmpeg_path.with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe"))
    except RuntimeError:
        pass
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    found = shutil.which("ffprobe")
    if found:
        return found
    raise RuntimeError("ffprobe not found")


def _subprocess_no_window_flag() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def probe_audio_duration_ms(
    audio_path: Path,
    *,
    ffprobe_getter: Callable[[], str] | None = None,
    ffmpeg_getter: Callable[[], str] | None = None,
    run=None,
) -> int:
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise RuntimeError(f"audio file does not exist: {audio_path}")

    run = subprocess.run if run is None else run
    ffprobe_getter = _get_ffprobe if ffprobe_getter is None else ffprobe_getter
    ffmpeg_getter = _get_ffmpeg if ffmpeg_getter is None else ffmpeg_getter
    errors: list[str] = []
    try:
        ffprobe = ffprobe_getter()
        cp = run(
            [
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_subprocess_no_window_flag(),
        )
        if cp.stdout.strip():
            return parse_duration_to_ms(cp.stdout.strip().splitlines()[0])
        errors.append((cp.stderr or "ffprobe returned no duration").strip())
    except Exception as ex:
        errors.append(f"ffprobe: {ex}")

    try:
        ffmpeg = ffmpeg_getter()
        cp = run(
            [ffmpeg, "-hide_banner", "-i", str(audio_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_subprocess_no_window_flag(),
        )
        return parse_ffmpeg_duration_to_ms((cp.stderr or "") + "\n" + (cp.stdout or ""))
    except Exception as ex:
        errors.append(f"ffmpeg: {ex}")

    raise RuntimeError("; ".join(err for err in errors if err) or "unable to read audio duration")


def _atempo(speed: float) -> str:
    validate_speed_value(speed)
    parts, rem = [], speed
    while rem > 2.0:
        parts.append(2.0)
        rem /= 2.0
    while rem < 0.5:
        parts.append(0.5)
        rem /= 0.5
    parts.append(rem)
    return ",".join(f"atempo={p:.6f}" for p in parts)


def slice_ogg(
    in_path: Path,
    out_path: Path,
    start_ms: int,
    end_ms: int,
    speed: float,
    *,
    ffmpeg_getter: Callable[[], str] | None = None,
    run=None,
) -> None:
    validate_speed_value(speed)
    ffmpeg_getter = _get_ffmpeg if ffmpeg_getter is None else ffmpeg_getter
    run = subprocess.run if run is None else run
    ffmpeg = ffmpeg_getter()
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start_ms/1000:.3f}", "-t", f"{(end_ms-start_ms)/1000:.3f}",
        "-i", str(in_path),
    ]
    if abs(speed - 1.0) > 1e-9:
        cmd += ["-filter:a", _atempo(speed)]
    cmd += ["-c:a", "libvorbis", "-q:a", "6", str(out_path)]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    run(cmd, check=True, creationflags=flags)
