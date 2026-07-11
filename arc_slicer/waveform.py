"""Waveform generation and cache helpers."""
from __future__ import annotations

import array
import hashlib
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from arc_slicer.audio import _get_ffmpeg, _subprocess_no_window_flag
from arc_slicer.paths import WAVEFORM_CACHE_DIR

WAVEFORM_CACHE_VERSION = 1
WAVEFORM_DECODE_SAMPLE_RATE = 8000
DEFAULT_WAVEFORM_SAMPLES_PER_SECOND = 100
WAVEFORM_MIN_SEGMENT_MS = 100
WAVEFORM_HANDLE_PX = 8

@dataclass
class WaveformData:
    duration_ms: int
    samples_per_second: int
    peaks: list[tuple[float, float]]


def aggregate_pcm_waveform(
    pcm_bytes: bytes,
    sample_rate: int = WAVEFORM_DECODE_SAMPLE_RATE,
    samples_per_second: int = DEFAULT_WAVEFORM_SAMPLES_PER_SECOND,
) -> WaveformData:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if samples_per_second <= 0:
        raise ValueError("samples_per_second must be positive")
    if not pcm_bytes:
        return WaveformData(duration_ms=0, samples_per_second=int(samples_per_second), peaks=[])

    sample_count = len(pcm_bytes) // 2
    if sample_count <= 0:
        return WaveformData(duration_ms=0, samples_per_second=int(samples_per_second), peaks=[])

    samples = array.array("h")
    samples.frombytes(pcm_bytes[: sample_count * 2])
    if sys.byteorder != "little":
        samples.byteswap()

    samples_per_bucket = max(1, int(round(sample_rate / samples_per_second)))
    peaks: list[tuple[float, float]] = []
    for start in range(0, sample_count, samples_per_bucket):
        bucket = samples[start:start + samples_per_bucket]
        if not bucket:
            continue
        min_amp = max(-1.0, min(1.0, min(bucket) / 32768.0))
        max_amp = max(-1.0, min(1.0, max(bucket) / 32767.0))
        peaks.append((float(min_amp), float(max_amp)))

    duration_ms = int(round(sample_count * 1000 / sample_rate))
    return WaveformData(
        duration_ms=duration_ms,
        samples_per_second=int(samples_per_second),
        peaks=peaks,
    )


def waveform_cache_key(audio_path: Path, samples_per_second: int = DEFAULT_WAVEFORM_SAMPLES_PER_SECOND) -> str:
    path = Path(audio_path)
    stat = path.stat()
    payload = json.dumps(
        {
            "path": str(path.resolve(strict=False)),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "samples_per_second": int(samples_per_second),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def waveform_cache_path(
    audio_path: Path,
    samples_per_second: int = DEFAULT_WAVEFORM_SAMPLES_PER_SECOND,
    cache_dir: Path | None = None,
) -> Path:
    return Path(cache_dir or WAVEFORM_CACHE_DIR) / f"{waveform_cache_key(audio_path, samples_per_second)}.json"


def _coerce_waveform_peaks(raw_peaks) -> list[tuple[float, float]]:
    if not isinstance(raw_peaks, list):
        raise ValueError("invalid peaks")
    peaks: list[tuple[float, float]] = []
    for item in raw_peaks:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("invalid peak")
        lo = max(-1.0, min(1.0, float(item[0])))
        hi = max(-1.0, min(1.0, float(item[1])))
        peaks.append((lo, hi))
    return peaks


def read_waveform_cache(path: Path) -> WaveformData | None:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != WAVEFORM_CACHE_VERSION:
            return None
        duration_ms = int(raw.get("duration_ms", 0))
        samples_per_second = int(raw.get("samples_per_second", 0))
        if duration_ms < 0 or samples_per_second <= 0:
            return None
        return WaveformData(
            duration_ms=duration_ms,
            samples_per_second=samples_per_second,
            peaks=_coerce_waveform_peaks(raw.get("peaks")),
        )
    except Exception:
        return None


def write_waveform_cache(path: Path, data: WaveformData) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp_{uuid.uuid4().hex}"
    payload = {
        "version": WAVEFORM_CACHE_VERSION,
        "duration_ms": int(data.duration_ms),
        "samples_per_second": int(data.samples_per_second),
        "peaks": [[float(lo), float(hi)] for lo, hi in data.peaks],
    }
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def decode_audio_waveform(
    audio_path: Path,
    samples_per_second: int = DEFAULT_WAVEFORM_SAMPLES_PER_SECOND,
    *,
    ffmpeg_getter: Callable[[], str] | None = None,
    run=None,
) -> WaveformData:
    ffmpeg_getter = _get_ffmpeg if ffmpeg_getter is None else ffmpeg_getter
    run = subprocess.run if run is None else run
    ffmpeg = ffmpeg_getter()
    cp = run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            str(WAVEFORM_DECODE_SAMPLE_RATE),
            "-f",
            "s16le",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
        creationflags=_subprocess_no_window_flag(),
    )
    return aggregate_pcm_waveform(cp.stdout or b"", WAVEFORM_DECODE_SAMPLE_RATE, samples_per_second)


def load_or_generate_waveform(
    audio_path: Path,
    samples_per_second: int = DEFAULT_WAVEFORM_SAMPLES_PER_SECOND,
    cache_dir: Path | None = None,
    *,
    ffmpeg_getter: Callable[[], str] | None = None,
    run=None,
) -> WaveformData:
    cache_path = waveform_cache_path(audio_path, samples_per_second, cache_dir)
    cached = read_waveform_cache(cache_path)
    if cached is not None:
        return cached
    data = decode_audio_waveform(audio_path, samples_per_second, ffmpeg_getter=ffmpeg_getter, run=run)
    try:
        write_waveform_cache(cache_path, data)
    except Exception:
        pass
    return data
