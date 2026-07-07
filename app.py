"""
Arc Slicer — PyQt6 独立桌面应用
切片逻辑全部内嵌；ffmpeg 打包；原生拖拽谱面文件夹；PyInstaller 单文件打包。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QMimeData,
    QPoint, QRect, QEvent,
)
from PyQt6.QtGui import (
    QColor, QFont, QPalette, QPainter, QPainterPath, QPen, QLinearGradient,
    QDragEnterEvent, QDropEvent, QDragLeaveEvent, QMouseEvent,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
    QScrollArea, QFrame, QFileDialog, QSizePolicy, QSpacerItem,
    QCheckBox, QGridLayout, QGraphicsDropShadowEffect,
)

import external_merge

# ─── 路径 ─────────────────────────────────────────────────────────────────────

APP_DATA_DIRNAME = "ArcSlicerData"

def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _res_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def _data_root_for_app_dir(app_dir: Path, frozen: bool | None = None) -> Path:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen and app_dir.name.lower() == "dist":
        return app_dir.parent / APP_DATA_DIRNAME
    return app_dir / APP_DATA_DIRNAME


def resolve_runtime_paths(
    app_file: Path | None = None,
    executable_path: Path | None = None,
    frozen: bool | None = None,
) -> dict[str, Path]:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        app_dir = Path(executable_path or sys.executable).parent
    else:
        app_dir = Path(app_file or __file__).parent
    res_dir = _res_dir() if app_file is None and executable_path is None else app_dir
    data_root = _data_root_for_app_dir(app_dir, frozen)
    return {
        "app_dir": app_dir,
        "res_dir": res_dir,
        "data_root": data_root,
        "songs_dir": data_root / "songs",
        "out_dir": data_root / "out",
        "config_path": data_root / "config.json",
        "slides_path": data_root / "slides.json",
    }


APP_DIR     = _app_dir()
BASE_DIR    = APP_DIR
RES_DIR     = _res_dir()
DATA_ROOT   = _data_root_for_app_dir(APP_DIR)
DEFAULT_SONGS_DIR = DATA_ROOT / "songs"
OUT_DIR     = DATA_ROOT / "out"
CURRENT_EXPORT_ROOT = OUT_DIR / "current_export"
CURRENT_EXPORT_SONGS_DIR = CURRENT_EXPORT_ROOT / "songs"
LIBRARY_EXPORT_ROOT = OUT_DIR / "library_export"
LIBRARY_EXPORT_SONGS_DIR = LIBRARY_EXPORT_ROOT / "songs"
EXTERNAL_MERGE_BACKUP_ROOT = DATA_ROOT / "backups" / "external_merge"
EXTERNAL_MERGE_TARGET_CONFIG_KEY = "external_merge_target_songs_dir"
CONFIG_PATH = DATA_ROOT / "config.json"
SLIDES_PATH = DATA_ROOT / "slides.json"
SONGLIST_EXAMPLE_PATH = APP_DIR / "songlist_example.json"
_FFMPEG_BUNDLED = RES_DIR / "ffmpeg.exe"
_AUTO_SEGMENT = object()

# ─── 颜色常量 ─────────────────────────────────────────────────────────────────

C_BG       = "#EDE9DF"
C_CARD     = "#FAF9F5"
C_CARD2    = "#F2EFE7"
C_BORDER   = "#E9E5DA"
C_BORDER2  = "#E7E3D8"
C_ACCENT   = "#C96442"
C_ACCENT_H = "#B5573A"
C_TEXT     = "#23211E"
C_TEXT2    = "#3A372F"
C_MUTED    = "#6E6B63"
C_LABEL    = "#9A968C"
C_INPUT_BG = "#F7F5EE"
C_INPUT_BD = "#E4DFD2"
C_OK       = "#5E7A52"
C_ERR      = "#C1573F"
C_BADGE_BG = "#F6E9E2"

# ─── AFF 切片逻辑 ─────────────────────────────────────────────────────────────

_TIMING_RE = re.compile(
    r"^\s*timing\(([+-]?\d+),([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?)\);\s*$",
    re.IGNORECASE,
)
_AUDIO_OFFSET_RE = re.compile(r"^\s*AudioOffset\s*:\s*([+-]?\d+)\s*$", re.IGNORECASE)
CAMERA_SCENE_WARNING = (
    "当前切片已缩放事件起始时间，但部分 Camera/Scenecontrol 持续时间参数尚未随倍速缩放，"
    "演出效果可能不完全一致。"
)
AUDIO_OFFSET_WARNING = (
    "检测到非零 AudioOffset；当前版本未对音频裁切时间与 AFF Offset 做专门换算，"
    "切片边界可能需要后续人工核验。"
)
NONLINEAR_ARC_EASINGS = {"b", "si", "so", "sisi", "siso", "sosi", "soso"}
ARC_CUT_EASING_ORDER = ("si", "so", "b", "sisi", "siso", "sosi", "soso")
_ARC_LINE_RE = re.compile(
    r"\s*arc\(([+-]?\d+),([+-]?\d+),(.*)\)\s*(\[(.*)\])?;\s*$",
    re.IGNORECASE,
)


def parse_speed_text(text: str) -> float:
    raw = text.strip()
    if not raw:
        raise ValueError("速度不能为空")
    try:
        speed = float(raw)
    except ValueError as ex:
        raise ValueError("速度必须是数字") from ex
    return validate_speed_value(speed)


def validate_speed_value(speed: float) -> float:
    if not math.isfinite(speed):
        raise ValueError("速度必须是有限数字")
    if speed <= 0:
        raise ValueError("速度必须大于 0")
    return speed


def is_sliceable_song_dir(path: Path) -> bool:
    return path.is_dir() and (path / "base.ogg").is_file() and (path / "2.aff").is_file()


def _extract_header_and_body(text: str) -> tuple[list[str], list[str]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    header, body, found = [], [], False
    for line in lines:
        if not found and line.strip() == "-":
            found = True
            header.append("-")
        elif not found:
            header.append(line)
        else:
            body.append(line)
    return (header, body) if found else (["-"], lines)


def _parse_timings(lines: list[str]) -> list[tuple[int, float, float]]:
    out = []
    for ln in lines:
        parsed = _parse_timing_line(ln)
        if parsed:
            out.append(parsed)
    out.sort(key=lambda x: x[0])
    return out


def _parse_timing_line(line: str) -> tuple[int, float, float] | None:
    m = _TIMING_RE.match(line.replace(" ", ""))
    if not m:
        return None
    return int(m.group(1)), float(m.group(2)), float(m.group(3))


def _parse_outer_timings(lines: list[str]) -> list[tuple[int, float, float]]:
    out, i = [], 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.lower().startswith("timinggroup"):
            hdr = stripped
            if "{" not in hdr and i + 1 < len(lines) and "{" in lines[i + 1]:
                i += 1
                hdr = hdr + " " + lines[i].strip()
            if "{" in hdr:
                brace = hdr.count("{") - hdr.count("}")
                i += 1
                while i < len(lines) and brace > 0:
                    brace += lines[i].count("{") - lines[i].count("}")
                    i += 1
                continue
        parsed = _parse_timing_line(stripped)
        if parsed:
            out.append(parsed)
        i += 1
    out.sort(key=lambda x: x[0])
    return out


def _choose_effective_timing(timings: list[tuple[int, float, float]], start_ms: int) -> tuple[int, float, float] | None:
    if not timings:
        return None
    chosen = None
    for timing in timings:
        if timing[0] <= start_ms:
            chosen = timing
        else:
            break
    return chosen or timings[0]


def _timing_line(t: int, bpm: float, beats: float, speed: float) -> str:
    # Gate 0 rule: event time scales by 1/speed, Timing BPM scales by speed.
    return f"timing({t},{bpm * speed:.2f},{beats:.2f});"


def _has_timing_zero(lines: list[str]) -> bool:
    return any(re.match(r"\s*timing\(0,", ln.replace(" ", ""), re.IGNORECASE) for ln in lines)


def _has_outer_timing_zero(lines: list[str]) -> bool:
    return any(timing[0] == 0 for timing in _parse_outer_timings(lines))


def _has_nonempty_statement(lines: list[str]) -> bool:
    return any(ln.strip() for ln in lines)


def _audio_offset_value(header: list[str]) -> int | None:
    for line in header:
        m = _AUDIO_OFFSET_RE.match(line)
        if m:
            return int(m.group(1))
    return None


def _linear(p: float) -> float:
    return p


def _sine_out(p: float) -> float:
    return math.sin(math.pi * p / 2.0)


def _sine_in(p: float) -> float:
    return 1.0 - math.cos(math.pi * p / 2.0)


def _bezier(p: float) -> float:
    return 3.0 * p * p - 2.0 * p * p * p


def _axis_easing(easing: str):
    # AFF shorthand is axis-specific: si=(Sine Out, Linear), so=(Sine In, Linear).
    table = {
        "b": (_bezier, _bezier),
        "s": (_linear, _linear),
        "si": (_sine_out, _linear),
        "so": (_sine_in, _linear),
        "sisi": (_sine_out, _sine_out),
        "siso": (_sine_out, _sine_in),
        "sosi": (_sine_in, _sine_out),
        "soso": (_sine_in, _sine_in),
    }
    return table.get(easing.lower(), (_linear, _linear))


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def arc_position_at(
    t: float,
    t1: float,
    t2: float,
    x1: float,
    x2: float,
    y1: float,
    y2: float,
    easing: str,
) -> tuple[float, float]:
    if t1 == t2:
        raise ValueError("zero-duration Arc has no continuous progress")
    # Preserve declared direction. For t1 > t2 this denominator is negative by design.
    p = _clamp01((t - t1) / (t2 - t1))
    fx, fy = _axis_easing(easing)
    return x1 + (x2 - x1) * fx(p), y1 + (y2 - y1) * fy(p)


def _fmt_float(v: float) -> str:
    if abs(v) < 0.0000005:
        v = 0.0
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def _fmt_arc_coord(v: float) -> str:
    if abs(v) < 0.0000005:
        v = 0.0
    return f"{v:.6f}"


def _split_arc_fields(body_inside: str) -> list[str]:
    return [part.strip() for part in body_inside.split(",")]


def _scale_bpm_string(value: str, speed: float) -> str:
    # Only scale a single numeric display BPM. Ranges like "120-180" stay untouched.
    raw = value.strip()
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
        return value
    scaled = round(float(raw) * speed, 2)
    return str(int(scaled) if scaled == int(scaled) else scaled)


def _tt(t: int, start: int, speed: float) -> int:
    return int(round((t - start) / speed))


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _overlap(t1: int, t2: int, s: int, e: int) -> bool:
    a, b = (t1, t2) if t1 <= t2 else (t2, t1)
    return not (b < s or a > e)


def _parse_arc_cut_candidate(line: str) -> dict | None:
    m = _ARC_LINE_RE.match(line.strip())
    if not m:
        return None

    t1, t2 = int(m.group(1)), int(m.group(2))
    if t1 == t2:
        return None

    fields = _split_arc_fields(m.group(3))
    if len(fields) < 5:
        return None

    easing = fields[2].strip().lower()
    if easing not in NONLINEAR_ARC_EASINGS:
        return None

    low, high = min(t1, t2), max(t1, t2)
    return {"t1": t1, "t2": t2, "low": low, "high": high, "easing": easing}


def find_nonlinear_arc_cut_warnings(aff_text: str, segments: list[dict]) -> dict[int, dict[str, list[dict]]]:
    _, body = _extract_header_and_body(aff_text)
    arcs = []
    for line in body:
        arc = _parse_arc_cut_candidate(line)
        if arc:
            arcs.append(arc)

    warnings: dict[int, dict[str, list[dict]]] = {}
    for index, seg in enumerate(segments):
        warnings[index] = {"start": [], "end": []}
        try:
            start_ms = int(seg["s"])
            end_ms = int(seg["e"])
        except (KeyError, TypeError, ValueError):
            continue

        for arc in arcs:
            # Boundary equality is intentionally not a warning; only mid-arc cuts are approximate.
            if arc["low"] < start_ms < arc["high"]:
                warnings[index]["start"].append(dict(arc))
            if arc["low"] < end_ms < arc["high"]:
                warnings[index]["end"].append(dict(arc))
    return warnings


def _arc_cut_easing_summary(hits: list[dict]) -> str:
    counts: dict[str, int] = {}
    for hit in hits:
        easing = str(hit.get("easing", "?"))
        counts[easing] = counts.get(easing, 0) + 1

    ordered = [easing for easing in ARC_CUT_EASING_ORDER if easing in counts]
    ordered.extend(sorted(easing for easing in counts if easing not in ARC_CUT_EASING_ORDER))
    return " · ".join(f"{easing} × {counts[easing]}" for easing in ordered)


def _arc_cut_info_content(hits: list[dict], boundary: str) -> dict[str, str]:
    if boundary == "start":
        return {
            "title": f"起点截断 · {len(hits)} 条",
            "body": (
                "当前片段从非线性 Arc 的中间开始。\n"
                "切片器已按原谱缓动计算新的起点坐标，\n"
                "因此切片边界不会突跳。\n\n"
                "但 AFF 无法表示被截取后的局部缓动曲线，\n"
                "所以 Arc 在片段内部只能近似原谱，\n"
                "可能存在轻微轨迹偏差。"
            ),
            "summary": _arc_cut_easing_summary(hits),
            "footer": "线性 s Arc 不受此限制，因此不会显示该标记。",
        }
    else:
        return {
            "title": f"终点截断 · {len(hits)} 条",
            "body": (
                "当前片段在非线性 Arc 的中间结束。\n"
                "切片器已按原谱缓动计算新的终点坐标，\n"
                "因此切片边界不会突跳。\n\n"
                "但 AFF 无法表示被截取后的局部缓动曲线，\n"
                "所以 Arc 在片段内部只能近似原谱，\n"
                "可能存在轻微轨迹偏差。"
            ),
            "summary": _arc_cut_easing_summary(hits),
            "footer": "线性 s Arc 不受此限制，因此不会显示该标记。",
        }


def _slice_arc_line(stripped: str, s: int, e: int, start: int, speed: float) -> str | None:
    m = _ARC_LINE_RE.match(stripped)
    if not m:
        return None

    t1, t2 = int(m.group(1)), int(m.group(2))
    low, high = min(t1, t2), max(t1, t2)
    if not _overlap(t1, t2, s, e):
        return ""

    fields = _split_arc_fields(m.group(3))
    if len(fields) < 8:
        return stripped

    if t1 == t2:
        if not (s <= t1 <= e):
            return ""
        ot = _tt(t1, start, speed)
        try:
            new_fields = [
                _fmt_arc_coord(float(fields[0])),
                _fmt_arc_coord(float(fields[1])),
                fields[2],
                _fmt_arc_coord(float(fields[3])),
                _fmt_arc_coord(float(fields[4])),
                *fields[5:],
            ]
        except (ValueError, IndexError):
            return stripped
        result = f"arc({ot},{ot},{','.join(new_fields)})"
    else:
        try:
            x1, x2 = float(fields[0]), float(fields[1])
            easing = fields[2]
            y1, y2 = float(fields[3]), float(fields[4])
        except (ValueError, IndexError):
            return stripped

        # Clamp each declared endpoint independently to keep t1 > t2 direction intact.
        nt1, nt2 = _clamp(t1, s, e), _clamp(t2, s, e)
        nx1, ny1 = arc_position_at(nt1, t1, t2, x1, x2, y1, y2, easing)
        nx2, ny2 = arc_position_at(nt2, t1, t2, x1, x2, y1, y2, easing)
        new_fields = [
            _fmt_arc_coord(nx1),
            _fmt_arc_coord(nx2),
            fields[2],
            _fmt_arc_coord(ny1),
            _fmt_arc_coord(ny2),
            *fields[5:],
        ]
        result = f"arc({_tt(nt1,start,speed)},{_tt(nt2,start,speed)},{','.join(new_fields)})"

    taps_blob = m.group(5)
    if taps_blob:
        kept = [
            f"arctap({_tt(int(tm.group(1)),start,speed)})"
            for tm in re.finditer(r"arctap\(([+-]?\d+)\)", taps_blob, re.IGNORECASE)
            if max(low, s) <= int(tm.group(1)) <= min(high, e)
        ]
        result += ("[" + ",".join(kept) + "]") if kept else "[]"
    return result + ";"


def _slice_line(line: str, s: int, e: int, start: int, speed: float, warnings: set[str] | None = None) -> str | None:
    stripped = line.strip()
    if not stripped:
        return ""

    # timing
    m = re.match(
        r"timing\(([+-]?\d+),([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?)\);\s*$",
        stripped, re.IGNORECASE,
    )
    if m:
        t = int(m.group(1))
        if not (s <= t <= e):
            return None
        return _timing_line(_tt(t, start, speed), float(m.group(2)), float(m.group(3)), speed)

    for pat, prefix in [
        (r"\s*camera\((\d+),(.*)\);\s*", "camera"),
        (r"\s*scenecontrol\((\d+),(.*)\);\s*", "scenecontrol"),
    ]:
        m = re.match(pat, stripped, re.IGNORECASE)
        if m:
            if warnings is not None:
                warnings.add(CAMERA_SCENE_WARNING)
            t = int(m.group(1))
            if not (s <= t <= e):
                return None
            return re.sub(rf"{prefix}\(\d+,", f"{prefix}({_tt(t,start,speed)},", stripped, flags=re.IGNORECASE)

    m = re.match(r"\s*\((\d+),(.*)\);\s*", stripped)
    if m:
        t = int(m.group(1))
        if not (s <= t <= e):
            return None
        return re.sub(r"\(\d+,", f"({_tt(t,start,speed)},", stripped)

    m = re.match(r"\s*hold\((\d+),(\d+),(.*)\);\s*", stripped, re.IGNORECASE)
    if m:
        t1, t2 = int(m.group(1)), int(m.group(2))
        if not _overlap(t1, t2, s, e):
            return None
        nt1, nt2 = _clamp(t1, s, e), _clamp(t2, s, e)
        return re.sub(r"hold\(\d+,\d+,", f"hold({_tt(nt1,start,speed)},{_tt(nt2,start,speed)},", stripped, flags=re.IGNORECASE)

    sliced_arc = _slice_arc_line(stripped, s, e, start, speed)
    if sliced_arc == "":
        return None
    if sliced_arc is not None:
        return sliced_arc

    return stripped


def _slice_block(lines: list[str], s: int, e: int, start: int, speed: float, warnings: set[str] | None = None) -> list[str]:
    out, i = [], 0
    while i < len(lines):
        line    = lines[i]
        stripped = line.strip()
        if stripped.lower().startswith("timinggroup"):
            hdr = stripped
            if "{" not in hdr and i + 1 < len(lines) and "{" in lines[i + 1]:
                i += 1
                hdr = hdr + " " + lines[i].strip()
            if "{" in hdr:
                brace, inner = hdr.count("{") - hdr.count("}"), []
                i += 1
                while i < len(lines) and brace > 0:
                    l2 = lines[i]
                    brace += l2.count("{") - l2.count("}")
                    if brace > 0:
                        inner.append(l2)
                    i += 1
                inner_timings = _parse_timings(inner)
                sliced_inner = _slice_block(inner, s, e, start, speed, warnings)
                if _has_nonempty_statement(sliced_inner):
                    if not _has_timing_zero(sliced_inner):
                        chosen = _choose_effective_timing(inner_timings, s)
                        if chosen:
                            sliced_inner.insert(0, _timing_line(0, chosen[1], chosen[2], speed))
                    out.append(hdr.split("{", 1)[0].rstrip() + "{")
                    out.extend(sliced_inner)
                    out.append("};")
                continue
        sliced = _slice_line(line, s, e, start, speed, warnings)
        if sliced is not None:
            out.append(sliced)
        i += 1
    while out and out[-1] == "":
        out.pop()
    return out


def slice_aff(aff_text: str, start_ms: int, end_ms: int, speed: float, warnings: list[str] | None = None) -> str:
    validate_speed_value(speed)
    header, body = _extract_header_and_body(aff_text)
    warning_set: set[str] = set()
    audio_offset = _audio_offset_value(header)
    if audio_offset not in (None, 0):
        # AudioOffset is intentionally preserved for Gate 0; no timing conversion is applied yet.
        warning_set.add(AUDIO_OFFSET_WARNING)

    timings = _parse_outer_timings(body)
    base_line: str | None = None
    chosen = _choose_effective_timing(timings, start_ms)
    if chosen:
        base_line = _timing_line(0, chosen[1], chosen[2], speed)

    out_body = _slice_block(body, start_ms, end_ms, start_ms, speed, warning_set)
    if base_line:
        if not _has_outer_timing_zero(out_body):
            out_body.insert(0, base_line)
    if warnings is not None:
        warnings.extend(sorted(warning_set))
    return "\n".join(header + out_body).rstrip() + "\n"


# ─── ffmpeg ───────────────────────────────────────────────────────────────────

def _get_ffmpeg() -> str:
    if _FFMPEG_BUNDLED.exists():
        return str(_FFMPEG_BUNDLED)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError(
        "找不到 ffmpeg。请将 ffmpeg.exe 放在应用同目录，或将其加入系统 PATH。"
    )


TIME_INPUT_PATTERN = r"^-?\d*$"
_TIME_INPUT_RE = re.compile(r"^-?\d*$")
_FFMPEG_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


@dataclass
class SegmentValidationResult:
    start_error: str = ""
    end_error: str = ""
    end_cap_ms: int | None = None
    first_field: str | None = None
    first_message: str = ""

    @property
    def ok(self) -> bool:
        return not self.start_error and not self.end_error


def is_time_input_text_allowed(text: str) -> bool:
    return bool(_TIME_INPUT_RE.fullmatch(str(text)))


def parse_duration_to_ms(value: str | int | float | Decimal) -> int:
    try:
        duration = Decimal(str(value).strip())
    except Exception as ex:
        raise ValueError("invalid duration") from ex
    if not duration.is_finite() or duration < 0:
        raise ValueError("invalid duration")
    return int((duration * Decimal(1000)).to_integral_value(rounding=ROUND_FLOOR))


def parse_ffmpeg_duration_to_ms(text: str) -> int:
    m = _FFMPEG_DURATION_RE.search(text or "")
    if not m:
        raise ValueError("ffmpeg duration not found")
    hours = int(m.group(1))
    minutes = int(m.group(2))
    seconds = Decimal(m.group(3))
    total = Decimal(hours * 3600 + minutes * 60) + seconds
    return parse_duration_to_ms(total)


def format_duration_ms(duration_ms: int) -> str:
    duration_ms = max(0, int(duration_ms))
    total_seconds, ms = divmod(duration_ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}.{ms:03d}"
    return f"{minutes}:{seconds:02d}.{ms:03d}"


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
    raise RuntimeError("找不到 ffprobe")


def _subprocess_no_window_flag() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def probe_audio_duration_ms(audio_path: Path) -> int:
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise RuntimeError(f"音频文件不存在: {audio_path}")

    errors: list[str] = []
    try:
        ffprobe = _get_ffprobe()
        cp = subprocess.run(
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
        errors.append((cp.stderr or "ffprobe 未返回时长").strip())
    except Exception as ex:
        errors.append(f"ffprobe: {ex}")

    try:
        ffmpeg = _get_ffmpeg()
        cp = subprocess.run(
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

    raise RuntimeError("; ".join(err for err in errors if err) or "无法读取音频时长")


def _parse_non_negative_time_text(text: str, field_name: str) -> tuple[int | None, str]:
    raw = str(text)
    if raw == "":
        return None, f"{field_name}不能为空"
    if not is_time_input_text_allowed(raw) or raw == "-":
        return None, f"{field_name}必须为非负整数毫秒"
    value = int(raw)
    if value < 0:
        return None, f"{field_name}必须为非负整数毫秒"
    return value, ""


def validate_segment_bounds(
    start_text: str,
    end_text: str,
    audio_duration_ms: int | None,
) -> SegmentValidationResult:
    start, start_error = _parse_non_negative_time_text(start_text, "起点")
    end, end_error = _parse_non_negative_time_text(end_text, "终点")
    result = SegmentValidationResult(start_error=start_error, end_error=end_error)

    if result.start_error:
        result.first_field = "start"
        result.first_message = result.start_error
        return result
    if result.end_error:
        result.first_field = "end"
        result.first_message = result.end_error
        return result

    assert start is not None and end is not None
    if end <= start:
        result.end_error = "终点必须大于起点"
    elif audio_duration_ms is None:
        result.end_error = "无法读取当前曲目的音频时长"
    elif start >= audio_duration_ms:
        result.start_error = f"起点不能超过音频时长：{format_duration_ms(audio_duration_ms)}"
    elif end > audio_duration_ms:
        result.end_error = f"终点不能超过音频时长：{format_duration_ms(audio_duration_ms)}"
        result.end_cap_ms = int(audio_duration_ms)

    if result.start_error:
        result.first_field = "start"
        result.first_message = result.start_error
    elif result.end_error:
        result.first_field = "end"
        result.first_message = result.end_error
    return result


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


def slice_ogg(in_path: Path, out_path: Path, start_ms: int, end_ms: int, speed: float) -> None:
    validate_speed_value(speed)
    ffmpeg = _get_ffmpeg()
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start_ms/1000:.3f}", "-t", f"{(end_ms-start_ms)/1000:.3f}",
        "-i", str(in_path),
    ]
    if abs(speed - 1.0) > 1e-9:
        cmd += ["-filter:a", _atempo(speed)]
    cmd += ["-c:a", "libvorbis", "-q:a", "6", str(out_path)]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.run(cmd, check=True, creationflags=flags)


# ─── V2.1 导出路径底座 ───────────────────────────────────────────────────────

JACKET_FILENAMES = ("1080_base.jpg", "base.jpg", "1080_base_256.jpg")
PACK_COVER_SIZE = (374, 750)
PACK_COVER_UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg"}
PACK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def current_export_root(out_dir: Path | None = None) -> Path:
    return Path(out_dir or OUT_DIR) / "current_export"


def current_export_songs_dir(out_dir: Path | None = None) -> Path:
    return current_export_root(out_dir) / "songs"


def library_export_root(out_dir: Path | None = None) -> Path:
    return Path(out_dir or OUT_DIR) / "library_export"


def library_export_songs_dir(out_dir: Path | None = None) -> Path:
    return library_export_root(out_dir) / "songs"


def _speed_text(speed: float) -> str:
    speed = validate_speed_value(float(speed))
    text = format(speed, ".12g")
    decimal = Decimal(text).normalize()
    out = format(decimal, "f")
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return out or "0"


def normalize_speed_token(speed: float) -> str:
    return _speed_text(speed).replace(".", "p")


def build_segment_id(source_id: str, start_ms: int, end_ms: int, speed: float) -> str:
    if not source_id:
        raise ValueError("source_id 不能为空")
    return f"{source_id}_{int(start_ms)}_{int(end_ms)}_x{normalize_speed_token(speed)}"


def build_segment_display_title(source_title: str, start_ms: int, end_ms: int, speed: float) -> str:
    title = str(source_title or "").strip() or "Untitled"
    return f"{title} [{int(start_ms)}–{int(end_ms)}ms · {_speed_text(speed)}×]"


def copy_song_jackets(source_dir: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in JACKET_FILENAMES:
        src = Path(source_dir) / name
        if src.is_file():
            dest = Path(out_dir) / name
            shutil.copy2(src, dest)
            copied.append(dest)
    return copied


def create_current_export_stage(out_dir: Path | None = None) -> Path:
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        stage = out_dir / f".current_export_staging_{uuid.uuid4().hex}"
        try:
            (stage / "songs").mkdir(parents=True)
            return stage
        except FileExistsError:
            continue
    raise RuntimeError("无法创建 current_export staging 目录")


def _resolved(path: Path) -> Path:
    return Path(path).resolve(strict=False)


def _is_direct_child(child: Path, parent: Path) -> bool:
    return _resolved(child).parent == _resolved(parent)


def _path_is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(getattr(os.path, "isjunction", lambda _p: False)(path))
    except OSError:
        return False


def _assert_safe_current_export_path(path: Path, out_dir: Path) -> None:
    path = Path(path)
    out_dir = Path(out_dir)
    expected = current_export_root(out_dir)
    if _resolved(path) != _resolved(expected):
        raise RuntimeError(f"拒绝操作非 current_export 路径: {path}")
    if _resolved(path) in {_resolved(out_dir), _resolved(DATA_ROOT), _resolved(library_export_root(out_dir))}:
        raise RuntimeError(f"拒绝操作危险路径: {path}")


def _assert_safe_stage_path(stage_root: Path, out_dir: Path) -> None:
    stage_root = Path(stage_root)
    out_dir = Path(out_dir)
    if not _is_direct_child(stage_root, out_dir):
        raise RuntimeError(f"staging 目录必须位于 OUT_DIR 下: {stage_root}")
    if not stage_root.name.startswith(".current_export_staging_"):
        raise RuntimeError(f"非法 staging 目录名: {stage_root.name}")
    if _resolved(stage_root) in {
        _resolved(out_dir),
        _resolved(current_export_root(out_dir)),
        _resolved(library_export_root(out_dir)),
        _resolved(DATA_ROOT),
    }:
        raise RuntimeError(f"拒绝操作危险 staging 路径: {stage_root}")


def cleanup_current_export_stage(stage_root: Path, out_dir: Path | None = None) -> None:
    out_dir = Path(out_dir or OUT_DIR)
    _assert_safe_stage_path(stage_root, out_dir)
    stage_root = Path(stage_root)
    if stage_root.exists():
        if _path_is_link_or_junction(stage_root):
            raise RuntimeError(f"拒绝删除链接 staging 目录: {stage_root}")
        shutil.rmtree(stage_root)


def publish_current_export_stage(
    stage_root: Path,
    out_dir: Path | None = None,
    rename_fn=None,
    rmtree_fn=shutil.rmtree,
) -> None:
    out_dir = Path(out_dir or OUT_DIR)
    stage_root = Path(stage_root)
    current = current_export_root(out_dir)
    backup = out_dir / f".current_export_backup_{uuid.uuid4().hex}"
    rename_fn = rename_fn or (lambda src, dest: Path(src).rename(dest))

    _assert_safe_stage_path(stage_root, out_dir)
    _assert_safe_current_export_path(current, out_dir)
    if not stage_root.is_dir():
        raise RuntimeError(f"staging 目录不存在: {stage_root}")
    if current.exists() and _path_is_link_or_junction(current):
        raise RuntimeError("current_export 是符号链接或 Junction，拒绝发布以避免误删目标")

    def move_dir(src: Path, dest: Path, allow_copy_fallback: bool = False) -> None:
        try:
            rename_fn(src, dest)
            return
        except Exception:
            if not allow_copy_fallback:
                raise
            if not Path(src).is_dir() or _path_is_link_or_junction(src):
                raise
            shutil.copytree(src, dest)
            rmtree_fn(src)

    def restore_backup() -> None:
        if not backup.exists() or current.exists():
            return
        try:
            rename_fn(backup, current)
        except Exception:
            shutil.copytree(backup, current)
            rmtree_fn(backup)

    moved_old = False
    published = False
    try:
        if current.exists():
            move_dir(current, backup, allow_copy_fallback=True)
            moved_old = True
        move_dir(stage_root, current, allow_copy_fallback=True)
        published = True
        if backup.exists():
            rmtree_fn(backup)
    except Exception as ex:
        if moved_old and not published and current.exists():
            try:
                if current.is_dir() and not _path_is_link_or_junction(current):
                    rmtree_fn(current)
            except Exception:
                pass
        if moved_old and backup.exists() and not current.exists():
            try:
                restore_backup()
            except Exception:
                pass
        if not moved_old and backup.exists():
            try:
                rmtree_fn(backup)
            except Exception:
                pass
        if stage_root.exists() and stage_root.name.startswith(".current_export_staging_"):
            try:
                if not _path_is_link_or_junction(stage_root):
                    rmtree_fn(stage_root)
            except Exception:
                pass
        raise RuntimeError(f"发布 current_export 失败: {ex}") from ex


# ─── songlist ─────────────────────────────────────────────────────────────────

def make_songlist_fragment(new_id: str, start_ms: int, end_ms: int, speed: float) -> dict | None:
    """旧兼容函数：V2.1 正式导出流程不再调用 songlist_fragment.json 路径。"""
    if not SONGLIST_EXAMPLE_PATH.exists():
        return None
    try:
        songs = json.loads(SONGLIST_EXAMPLE_PATH.read_text(encoding="utf-8")).get("songs", [])
        if not songs or not isinstance(songs[0], dict):
            return None
        out = json.loads(json.dumps(songs[0], ensure_ascii=False))
    except Exception:
        return None

    out["id"]  = new_id
    h = hashlib.sha1(new_id.encode()).digest()
    out["idx"] = int.from_bytes(h[:4], "big", signed=False) & 0x7FFFFFFF

    tl = out.get("title_localized")
    title_en = str(tl.get("en", "")) if isinstance(tl, dict) else ""
    out["title_localized"] = {"en": f"{title_en} [{start_ms}-{end_ms}]".strip()}
    out.pop("search_title", None)
    out.pop("search_artist", None)

    clip_ms = int(round((end_ms - start_ms) / speed))
    out["audioPreview"]    = 0
    out["audioPreviewEnd"] = min(30000, max(0, clip_ms))

    if speed != 1.0:
        for k in ("bpm_base", "baseBpm", "base_bpm"):
            if k in out and isinstance(out[k], (int, float)):
                out[k] = round(out[k] * speed, 2)
        if "bpm" in out and isinstance(out["bpm"], str):
            out["bpm"] = _scale_bpm_string(out["bpm"], speed)
    return {"songs": [out]}


def song_template_from_form(data: dict) -> SongTemplate:
    if not isinstance(data, dict):
        raise ValueError("Songlist 表单无效")
    try:
        return SongTemplate(
            title_base=str(data.get("title_base", "")).strip(),
            artist=str(data.get("artist", "")).strip(),
            bpm=str(data.get("bpm", "")).strip(),
            bpm_base=float(data.get("bpm_base", 0) or 0),
            set=str(data.get("set", "")).strip() or "single",
            purchase=str(data.get("purchase", "")).strip(),
            side=int(data.get("side", 0) or 0),
            bg=str(data.get("bg", "")).strip(),
            version=str(data.get("version", "")).strip(),
            chart_designer=str(data.get("chart_designer", "")).strip(),
            jacket_designer=str(data.get("jacket_designer", "")).strip(),
            rating=int(data.get("rating", 9) or 9),
            rating_plus=bool(data.get("rating_plus", False)),
        )
    except (TypeError, ValueError) as ex:
        raise ValueError(f"Songlist 表单字段格式无效: {ex}") from ex


def _song_meta_value(meta, key: str):
    if hasattr(meta, key):
        return getattr(meta, key)
    return meta[key]


def build_ftr_compat_difficulties(meta) -> list[dict]:
    chart_designer = _song_meta_value(meta, "chart_designer")
    jacket_designer = _song_meta_value(meta, "jacket_designer")
    rating = int(_song_meta_value(meta, "rating"))
    rating_plus = bool(_song_meta_value(meta, "rating_plus"))
    return [
        {
            "ratingClass": 0,
            "chartDesigner": chart_designer,
            "jacketDesigner": jacket_designer,
            "rating": -1,
            "ratingPlus": False,
        },
        {
            "ratingClass": 1,
            "chartDesigner": chart_designer,
            "jacketDesigner": jacket_designer,
            "rating": -1,
            "ratingPlus": False,
        },
        {
            "ratingClass": 2,
            "chartDesigner": chart_designer,
            "jacketDesigner": jacket_designer,
            "rating": rating,
            "ratingPlus": rating_plus,
        },
    ]


def build_songlist_entry(
    template: SongTemplate,
    segment_id: str,
    display_title: str,
    start_ms: int,
    end_ms: int,
    speed: float,
) -> dict:
    validate_speed_value(speed)
    clip_ms = int(round((end_ms - start_ms) / speed))
    bpm_base = round(template.bpm_base * speed, 2) if abs(speed - 1.0) > 1e-9 else template.bpm_base
    bpm = _scale_bpm_string(template.bpm, speed) if abs(speed - 1.0) > 1e-9 else template.bpm
    return {
        "id": segment_id,
        "title_localized": {"en": display_title},
        "artist": template.artist,
        "bpm": bpm,
        "bpm_base": bpm_base,
        "set": template.set or "single",
        "purchase": template.purchase,
        "audioPreview": 0,
        "audioPreviewEnd": min(30000, max(0, clip_ms)),
        "side": int(template.side),
        "bg": template.bg,
        "date": int(time.time()),
        "version": template.version,
        "difficulties": build_ftr_compat_difficulties(template),
    }


def build_songlist_document(entries: list[dict]) -> dict:
    return {"songs": list(entries)}


def effective_packlist_export_enabled(packlist_enabled: bool, songlist_enabled: bool) -> bool:
    return bool(packlist_enabled and songlist_enabled)


def default_pack_img_name(pack_id: str) -> str:
    return f"select_{pack_id}.png"


def pack_description_placeholder(pack_id: str) -> str:
    pack_id = str(pack_id or "").strip()
    if pack_id:
        return f"{pack_id} practice clips generated by Arc Slicer."
    return "Practice clips generated by Arc Slicer."


def default_pack_form_for_song(source_id: str) -> dict:
    source_id = str(source_id or "").strip()
    return {
        "pack_id": source_id,
        "pack_name": source_id,
        "pack_description": "",
        "pack_img": default_pack_img_name(source_id) if source_id else "",
        "pack_cover_source": "auto",
        "pack_cover_path": "",
    }


def _safe_pack_img_filename(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("pack img 文件名不能为空")
    if Path(name).name != name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("pack img 必须是安全的单一文件名")
    if Path(name).drive:
        raise ValueError("pack img 不得包含盘符")
    if Path(name).suffix.lower() != ".png":
        raise ValueError("pack img 必须以 .png 结尾")
    return name


def pack_template_from_form(data: dict, source_id: str) -> PackTemplate:
    if not isinstance(data, dict):
        raise ValueError("Packlist 表单无效")
    defaults = default_pack_form_for_song(source_id)
    pack_id = str(data.get("pack_id") or defaults["pack_id"]).strip()
    if not pack_id:
        raise ValueError("pack_id 不能为空")
    if not PACK_ID_RE.fullmatch(pack_id):
        raise ValueError("pack_id 仅允许 ASCII 字母、数字、下划线、连字符")

    img = _safe_pack_img_filename(data.get("pack_img") or default_pack_img_name(pack_id))
    cover_source = str(data.get("pack_cover_source") or "auto").strip().lower()
    if cover_source not in ("auto", "upload"):
        raise ValueError("曲包封面来源无效")
    cover_path = str(data.get("pack_cover_path") or "").strip()
    if cover_source == "upload":
        if not cover_path:
            raise ValueError("上传曲包封面路径不能为空")
        src = Path(cover_path)
        if src.suffix.lower() not in PACK_COVER_UPLOAD_SUFFIXES:
            raise ValueError("上传曲包封面仅支持 PNG / JPG / JPEG")
        if not src.is_file():
            raise ValueError("上传曲包封面文件不存在")

    return PackTemplate(
        pack_id=pack_id,
        name=str(data.get("pack_name") or defaults["pack_name"]).strip(),
        description=str(data.get("pack_description", "")).strip(),
        img=img,
        cover_source=cover_source,
        cover_path=cover_path,
    )


def build_packlist_entry(template: PackTemplate) -> dict:
    return {
        "id": template.pack_id,
        "section": "collab",
        "plus_character": -1,
        "name_localized": {"en": template.name},
        "description_localized": {"en": template.description},
        "img": template.img,
    }


def build_packlist_document(entries: list[dict]) -> dict:
    return {"packs": list(entries)}


def _load_packlist_document(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        raise ValueError(f"无法读取 packlist JSON: {ex}") from ex
    if not isinstance(data, dict) or not isinstance(data.get("packs"), list):
        raise ValueError("packlist 顶层必须为 {\"packs\": [...]}")
    for item in data["packs"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("packlist 中每个条目必须包含非空字符串 id")
        if "img" in item:
            _safe_pack_img_filename(str(item["img"]))
    return data


def merge_packlist_entries(existing_entries: list[dict], new_entries: list[dict]) -> list[dict]:
    new_by_id: dict[str, dict] = {}
    new_order: list[str] = []
    for entry in new_entries:
        pack_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(pack_id, str) or not pack_id:
            raise ValueError("本次 packlist 条目缺少有效 id")
        if pack_id not in new_by_id:
            new_order.append(pack_id)
        new_by_id[pack_id] = entry

    merged: list[dict] = []
    seen: set[str] = set()
    for entry in existing_entries:
        pack_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(pack_id, str) or not pack_id or pack_id in seen:
            continue
        merged.append(new_by_id.get(pack_id, entry))
        seen.add(pack_id)

    for pack_id in new_order:
        if pack_id not in seen:
            merged.append(new_by_id[pack_id])
            seen.add(pack_id)
    return merged


def _select_auto_pack_cover_source(source_dir: Path) -> Path | None:
    for name in JACKET_FILENAMES:
        candidate = Path(source_dir) / name
        if candidate.is_file():
            return candidate
    return None


def _cover_crop_geometry(src_w: int, src_h: int, target_w: int = PACK_COVER_SIZE[0], target_h: int = PACK_COVER_SIZE[1]) -> tuple[int, int, int, int]:
    if src_w <= 0 or src_h <= 0:
        raise ValueError("图片尺寸无效")
    scale = max(target_w / src_w, target_h / src_h)
    scaled_w = max(target_w, int(math.ceil(src_w * scale)))
    scaled_h = max(target_h, int(math.ceil(src_h * scale)))
    x = max(0, (scaled_w - target_w) // 2)
    y = max(0, (scaled_h - target_h) // 2)
    return scaled_w, scaled_h, x, y


def render_pack_cover(source_path: Path, out_path: Path, log_fn=None) -> None:
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QImageReader

    source_path = Path(source_path)
    out_path = Path(out_path)
    reader = QImageReader(str(source_path))
    image = reader.read()
    if image.isNull():
        raise RuntimeError(f"曲包封面图片不可读: {source_path}")
    target_w, target_h = PACK_COVER_SIZE
    if (image.width() < target_w or image.height() < target_h) and log_fn:
        log_fn("  曲包封面源图可能清晰度不足。", "muted")
    scaled = image.scaled(
        target_w,
        target_h,
        _Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        _Qt.TransformationMode.SmoothTransformation,
    )
    crop_x = max(0, (scaled.width() - target_w) // 2)
    crop_y = max(0, (scaled.height() - target_h) // 2)
    cropped = scaled.copy(crop_x, crop_y, target_w, target_h)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not cropped.save(str(out_path), "PNG"):
        raise RuntimeError(f"曲包封面写入失败: {out_path}")


def write_pack_resources_to_stage(
    source_song_dir: Path,
    stage_songs_dir: Path,
    template: PackTemplate,
    log_fn=None,
    cover_renderer=None,
) -> dict:
    cover_renderer = cover_renderer or render_pack_cover
    if template.cover_source == "upload":
        cover_source = Path(template.cover_path)
    else:
        cover_source = _select_auto_pack_cover_source(source_song_dir)
        if cover_source is None:
            raise RuntimeError("找不到可用于生成曲包封面的歌曲曲绘")

    pack_dir = Path(stage_songs_dir) / "pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    cover_renderer(cover_source, pack_dir / template.img, log_fn)
    entry = build_packlist_entry(template)
    (Path(stage_songs_dir) / "packlist").write_text(
        json.dumps(build_packlist_document([entry]), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return entry


def _bool_pref(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in ("true", "1", "yes", "on"):
            return True
        if raw in ("false", "0", "no", "off"):
            return False
    return default


def effective_library_export_enabled(library_export_enabled: bool, songlist_enabled: bool) -> bool:
    return bool(library_export_enabled and songlist_enabled)


def _load_songlist_document(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        raise ValueError(f"无法读取 songlist JSON: {ex}") from ex
    if not isinstance(data, dict) or not isinstance(data.get("songs"), list):
        raise ValueError("songlist 顶层必须为 {\"songs\": [...]}")
    for item in data["songs"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("songlist 中每个条目必须包含非空字符串 id")
    return data


def merge_songlist_entries(existing_entries: list[dict], new_entries: list[dict]) -> list[dict]:
    new_by_id: dict[str, dict] = {}
    new_order: list[str] = []
    for entry in new_entries:
        song_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(song_id, str) or not song_id:
            raise ValueError("本次 songlist 条目缺少有效 id")
        if song_id not in new_by_id:
            new_order.append(song_id)
        new_by_id[song_id] = entry

    merged: list[dict] = []
    seen: set[str] = set()
    for entry in existing_entries:
        song_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(song_id, str) or not song_id or song_id in seen:
            continue
        if song_id in new_by_id:
            merged.append(new_by_id[song_id])
        else:
            merged.append(entry)
        seen.add(song_id)

    for song_id in new_order:
        if song_id not in seen:
            merged.append(new_by_id[song_id])
            seen.add(song_id)
    return merged


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp_{uuid.uuid4().hex}"
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _files_identical(a: Path, b: Path) -> bool:
    if not Path(a).is_file() or not Path(b).is_file():
        return False
    return hashlib.sha256(Path(a).read_bytes()).digest() == hashlib.sha256(Path(b).read_bytes()).digest()


def _backup_file(path: Path, backup: Path) -> bool:
    had_file = path.exists()
    if had_file:
        if path.is_dir() or _path_is_link_or_junction(path):
            raise RuntimeError(f"拒绝替换非普通文件: {path}")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    return had_file


def _restore_file_backup(path: Path, backup: Path, had_file: bool) -> None:
    if path.exists():
        if path.is_dir() or _path_is_link_or_junction(path):
            return
        path.unlink()
    if had_file and backup.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, path)
        backup.unlink()


def _copy_replace_dir_with_backup(src: Path, target: Path, backup: Path) -> bool:
    had_target = target.exists()
    if had_target:
        if _path_is_link_or_junction(target):
            raise RuntimeError(f"目标歌曲目录是符号链接或 Junction，拒绝替换: {target}")
        try:
            target.rename(backup)
        except Exception:
            shutil.copytree(target, backup)
            shutil.rmtree(target)
    shutil.copytree(src, target)
    return had_target


def _restore_dir_backup(target: Path, backup: Path, had_target: bool) -> None:
    if target.exists() and not _path_is_link_or_junction(target):
        shutil.rmtree(target)
    if had_target and backup.exists():
        try:
            backup.rename(target)
        except Exception:
            shutil.copytree(backup, target)
            shutil.rmtree(backup)


def merge_staging_into_library_export(
    stage_root: Path,
    out_dir: Path | None = None,
    fail_after_dirs: bool = False,
) -> None:
    out_dir = Path(out_dir or OUT_DIR)
    stage_root = Path(stage_root)
    staging_songs = stage_root / "songs"
    staging_songlist = staging_songs / "songlist"
    staging_packlist = staging_songs / "packlist"
    staging_pack_dir = staging_songs / "pack"
    if not staging_songlist.is_file():
        raise RuntimeError("更新总导出包需要 staging/songs/songlist")

    staging_doc = _load_songlist_document(staging_songlist)
    new_entries = staging_doc["songs"]
    song_ids = [entry["id"] for entry in new_entries]
    if len(song_ids) != len(set(song_ids)):
        raise RuntimeError("本次 songlist 含有重复 id，拒绝更新总导出包")

    for song_id in song_ids:
        src_dir = staging_songs / song_id
        if not src_dir.is_dir():
            raise RuntimeError(f"staging 缺少歌曲目录: {song_id}")

    library_songs = library_export_songs_dir(out_dir)
    library_songlist = library_songs / "songlist"
    library_packlist = library_songs / "packlist"
    library_pack_dir = library_songs / "pack"
    existing_entries: list[dict] = []
    if library_songlist.exists():
        existing_entries = _load_songlist_document(library_songlist)["songs"]

    has_packlist = staging_packlist.is_file()
    new_pack_entries: list[dict] = []
    merged_pack_doc: dict | None = None
    pack_images: list[tuple[str, str]] = []
    if has_packlist:
        staging_pack_doc = _load_packlist_document(staging_packlist)
        new_pack_entries = staging_pack_doc["packs"]
        pack_ids = [entry["id"] for entry in new_pack_entries]
        if len(pack_ids) != len(set(pack_ids)):
            raise RuntimeError("本次 packlist 含有重复 id，拒绝更新总导出包")
        existing_pack_entries: list[dict] = []
        if library_packlist.exists():
            existing_pack_entries = _load_packlist_document(library_packlist)["packs"]
        merged_pack_doc = build_packlist_document(merge_packlist_entries(existing_pack_entries, new_pack_entries))

        existing_img_owner: dict[str, str] = {}
        for entry in existing_pack_entries:
            img = entry.get("img")
            pack_id = entry.get("id")
            if isinstance(img, str) and isinstance(pack_id, str):
                existing_img_owner.setdefault(img, pack_id)

        for entry in new_pack_entries:
            img = _safe_pack_img_filename(entry.get("img", ""))
            pack_id = entry["id"]
            src_img = staging_pack_dir / img
            if not src_img.is_file():
                raise RuntimeError(f"staging 缺少曲包封面: {img}")
            target_img = library_pack_dir / img
            owner = existing_img_owner.get(img)
            if owner and owner != pack_id and target_img.exists() and not _files_identical(src_img, target_img):
                raise RuntimeError(f"曲包封面文件名冲突: {img} 已被 pack {owner} 使用")
            pack_images.append((pack_id, img))

    for song_id in song_ids:
        target_dir = library_songs / song_id
        if target_dir.exists() and _path_is_link_or_junction(target_dir):
            raise RuntimeError(f"目标歌曲目录是符号链接或 Junction，拒绝替换: {target_dir}")

    merged_doc = build_songlist_document(merge_songlist_entries(existing_entries, new_entries))
    library_songs.mkdir(parents=True, exist_ok=True)

    backups: list[tuple[Path, Path, bool]] = []
    file_backups: list[tuple[Path, Path, bool]] = []
    try:
        for path in (library_songlist, library_packlist if has_packlist else None):
            if path is None:
                continue
            backup = path.parent / f".{path.name}_backup_{uuid.uuid4().hex}"
            file_backups.append((path, backup, _backup_file(path, backup)))

        for song_id in song_ids:
            src_dir = staging_songs / song_id
            target_dir = library_songs / song_id
            backup = library_songs / f".{song_id}_backup_{uuid.uuid4().hex}"
            had_target = _copy_replace_dir_with_backup(src_dir, target_dir, backup)
            backups.append((target_dir, backup, had_target))

        if has_packlist:
            library_pack_dir.mkdir(parents=True, exist_ok=True)
            for _pack_id, img in pack_images:
                src_img = staging_pack_dir / img
                target_img = library_pack_dir / img
                backup = library_pack_dir / f".{img}_backup_{uuid.uuid4().hex}"
                file_backups.append((target_img, backup, _backup_file(target_img, backup)))
                shutil.copy2(src_img, target_img)

        if fail_after_dirs:
            raise RuntimeError("测试注入：歌曲目录替换后失败")

        _atomic_write_json(library_songlist, merged_doc)
        if has_packlist and merged_pack_doc is not None:
            _atomic_write_json(library_packlist, merged_pack_doc)
    except Exception:
        for target_dir, backup, had_target in reversed(backups):
            try:
                _restore_dir_backup(target_dir, backup, had_target)
            except Exception:
                pass
        for path, backup, had_file in reversed(file_backups):
            try:
                _restore_file_backup(path, backup, had_file)
            except Exception:
                pass
        raise
    else:
        for _target_dir, backup, _had_target in backups:
            if backup.exists() and not _path_is_link_or_junction(backup):
                shutil.rmtree(backup)
        for _path, backup, _had_file in file_backups:
            if backup.exists():
                try:
                    backup.unlink()
                except OSError:
                    pass


# ─── 核心切片 ─────────────────────────────────────────────────────────────────

def make_songlist_entry(
    folder_name: str,
    seg_index: int,
    start_ms: int,
    end_ms: int,
    speed: float,
    meta: dict,
) -> dict:
    """根据用户填写的 meta 生成单段 songlist JSON（{"songs": [...]}）。"""
    clip_ms = int(round((end_ms - start_ms) / speed))
    bpm_base = round(meta["bpm_base"] * speed, 2) if abs(speed - 1.0) > 1e-9 else meta["bpm_base"]
    bpm = _scale_bpm_string(meta["bpm"], speed) if abs(speed - 1.0) > 1e-9 else meta["bpm"]
    title = f"{meta['title_base']} {seg_index + 1:02d}".strip()
    return {
        "songs": [{
            "id": folder_name,
            "title_localized": {"en": title},
            "artist": meta["artist"],
            "bpm": bpm,
            "bpm_base": bpm_base,
            "set": meta["set"] or "single",
            "purchase": meta["purchase"],
            "audioPreview": 0,
            "audioPreviewEnd": min(30000, max(0, clip_ms)),
            "side": int(meta["side"]),
            "bg": meta["bg"],
            "date": int(time.time()),
            "version": meta["version"],
            "difficulties": build_ftr_compat_difficulties(meta),
        }]
    }


def do_slice(
    songs_dir: Path,
    song_id: str,
    segments: list[dict],
    speed: float,
    log_fn,
    songlist_meta: dict | None = None,
    songlist_enabled: bool = False,
    song_template: SongTemplate | None = None,
    current_export_enabled: bool = True,
    library_export_enabled: bool = True,
    packlist_enabled: bool = False,
    pack_template: PackTemplate | None = None,
) -> int:
    try:
        validate_speed_value(speed)
    except ValueError as ex:
        log_fn(f"✗ 速度无效: {ex}", "err")
        return 1

    try:
        ffp = _get_ffmpeg()
        log_fn(f"  ffmpeg: {ffp}", "muted")
    except RuntimeError as ex:
        log_fn(f"✗ {ex}", "err")
        return 1

    if songlist_enabled:
        if song_template is None:
            try:
                song_template = song_template_from_form(songlist_meta or {})
            except ValueError as ex:
                log_fn(f"✗ Songlist 信息无效: {ex}", "err")
                return 1

    effective_packlist = effective_packlist_export_enabled(packlist_enabled, songlist_enabled)
    if packlist_enabled and not songlist_enabled:
        log_fn("  生成 packlist 需要启用 songlist；本次不会输出 packlist。", "muted")

    effective_library = effective_library_export_enabled(library_export_enabled, songlist_enabled)
    if library_export_enabled and not songlist_enabled:
        log_fn("  更新总导出包需要启用 songlist；本次不会修改 library_export。", "muted")
    if not current_export_enabled and not effective_library:
        log_fn("✗ 至少需要选择一个有效导出目标。", "err")
        return 1

    in_dir = songs_dir / song_id
    in_aff, in_ogg = in_dir / "2.aff", in_dir / "base.ogg"

    for p in (in_aff, in_ogg):
        if not p.exists():
            log_fn(f"✗ 找不到文件: {p}", "err")
            return 1

    if effective_packlist:
        try:
            if pack_template is None:
                pack_template = pack_template_from_form(songlist_meta or {}, song_id)
            if song_template is not None:
                song_template = replace(song_template, set=pack_template.pack_id)
        except ValueError as ex:
            log_fn(f"✗ Packlist 信息无效: {ex}", "err")
            return 1

    try:
        stage_root = create_current_export_stage()
    except RuntimeError as ex:
        log_fn(f"✗ {ex}", "err")
        return 1

    out_root = stage_root / "songs"
    all_song_entries: list[dict] = []

    try:
        for i, seg in enumerate(segments):
            s, e = int(seg["s"]), int(seg["e"])
            if e <= s:
                log_fn(f"✗ 无效时间段 s={s} e={e}", "err")
                cleanup_current_export_stage(stage_root)
                return 1

            new_id   = build_segment_id(song_id, s, e, speed)
            out_dir  = out_root / new_id
            out_dir.mkdir(parents=True, exist_ok=True)

            copy_song_jackets(in_dir, out_dir)

            log_fn(f"  ♪ 音频 {s}ms – {e}ms  speed={speed}…", "stage")
            try:
                slice_ogg(in_ogg, out_dir / "base.ogg", s, e, speed)
            except subprocess.CalledProcessError as ex:
                log_fn(f"✗ ffmpeg 失败: {ex}", "err")
                cleanup_current_export_stage(stage_root)
                return 1

            log_fn(f"  ✎ 谱面 {s}ms – {e}ms…", "stage")
            aff_warnings: list[str] = []
            new_aff = slice_aff(in_aff.read_text(encoding="utf-8", errors="replace"), s, e, speed, aff_warnings)
            for warning in aff_warnings:
                log_fn(f"  ⚠ {warning}", "warn")
            (out_dir / "2.aff").write_text(new_aff, encoding="utf-8")

            if songlist_enabled and song_template:
                display_title = build_segment_display_title(song_template.title_base or song_id, s, e, speed)
                entry = build_songlist_entry(song_template, new_id, display_title, s, e, speed)
                all_song_entries.append(entry)
                log_fn(f"  ✎ songlist → {new_id}", "stage")

            log_fn(f"✓ 输出 → out/current_export/songs/{new_id}/", "ok")

        if songlist_enabled:
            merged_path = out_root / "songlist"
            merged_path.write_text(
                json.dumps(build_songlist_document(all_song_entries), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log_fn(f"✓ 合并 songlist → out/current_export/songs/songlist（共 {len(all_song_entries)} 首）", "ok")

        if effective_packlist and pack_template:
            write_pack_resources_to_stage(in_dir, out_root, pack_template, log_fn)
            log_fn(f"✓ packlist → {pack_template.pack_id} ({pack_template.img})", "ok")

        library_ok = True
        if effective_library:
            try:
                merge_staging_into_library_export(stage_root)
                log_fn("✓ 更新总导出包 → out/library_export/songs/", "ok")
            except Exception as ex:
                library_ok = False
                log_fn(f"✗ 更新总导出包失败: {ex}", "err")

        current_ok = True
        if current_export_enabled:
            try:
                publish_current_export_stage(stage_root)
                log_fn("✓ 生成本次导出包 → out/current_export/songs/", "ok")
            except RuntimeError as ex:
                current_ok = False
                log_fn(f"✗ {ex}", "err")
        else:
            cleanup_current_export_stage(stage_root)
            log_fn("  本次导出包：未启用，已清理临时 staging。", "muted")

        if not library_ok or not current_ok:
            if current_ok and not library_ok:
                log_fn("⚠ 本次导出包已完成，但总导出包更新失败。", "err")
            elif library_ok and not current_ok:
                log_fn("⚠ 总导出包已完成，但本次导出包发布失败。", "err")
            return 1
    except Exception as ex:
        try:
            cleanup_current_export_stage(stage_root)
        except Exception as cleanup_ex:
            log_fn(f"✗ 清理 staging 失败: {cleanup_ex}", "err")
        log_fn(f"✗ 切片失败: {ex}", "err")
        return 1

    return 0


# ─── 运行数据迁移 / 配置 ─────────────────────────────────────────────────────

@dataclass
class MigrationReport:
    songs: int = 0
    out: bool = False
    config: bool = False
    slides: bool = False
    failures: list[str] = field(default_factory=list)

    def has_activity(self) -> bool:
        return bool(self.songs or self.out or self.config or self.slides or self.failures)

    def message(self) -> str:
        parts = []
        if self.songs:
            parts.append(f"songs {self.songs} 项")
        if self.out:
            parts.append("out 已迁移")
        if self.config:
            parts.append("config 已迁移")
        if self.slides:
            parts.append("slides 已迁移")
        if self.failures:
            parts.append(f"失败 {len(self.failures)} 项")
        return "已迁移运行数据至 ArcSlicerData：" + "，".join(parts) + "。"


@dataclass
class SongTemplate:
    title_base: str
    artist: str
    bpm: str
    bpm_base: float
    set: str
    purchase: str
    side: int
    bg: str
    version: str
    chart_designer: str
    jacket_designer: str
    rating: int
    rating_plus: bool


@dataclass
class PackTemplate:
    pack_id: str
    name: str
    description: str
    img: str
    cover_source: str
    cover_path: str = ""


def _norm_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _same_path(a: Path, b: Path) -> bool:
    return _norm_path(a) == _norm_path(b)


def _legacy_runtime_roots(app_dir: Path = APP_DIR, data_root: Path = DATA_ROOT) -> list[Path]:
    roots = []
    base = data_root.parent
    for candidate in (base, base / "dist", app_dir):
        if candidate != data_root and candidate not in roots:
            roots.append(candidate)
    return roots


def _rewrite_legacy_config_songs_dir(cfg: dict, legacy_roots: list[Path], new_songs_dir: Path) -> dict:
    if not isinstance(cfg, dict):
        return cfg
    current = cfg.get("songs_dir")
    if not isinstance(current, str) or not current:
        return cfg
    current_path = Path(current)
    for root in legacy_roots:
        if _same_path(current_path, root / "songs"):
            cfg = dict(cfg)
            cfg["songs_dir"] = str(new_songs_dir)
            return cfg
    return cfg


def _is_dir_link(path: Path, is_junction_fn=None) -> bool:
    if path.is_symlink():
        return True
    if is_junction_fn is None:
        is_junction_fn = getattr(os.path, "isjunction", lambda _p: False)
    try:
        return bool(is_junction_fn(path))
    except OSError:
        return False


def _create_dir_link(target: Path, link_path: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
            check=True, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.symlink(target, link_path, target_is_directory=True)


def migrate_legacy_runtime_data(
    data_root: Path = DATA_ROOT,
    legacy_roots: list[Path] | None = None,
    copytree_fn=shutil.copytree,
    copy2_fn=shutil.copy2,
    link_fn=_create_dir_link,
    is_junction_fn=None,
) -> MigrationReport:
    data_root = Path(data_root)
    songs_target = data_root / "songs"
    out_target = data_root / "out"
    config_target = data_root / "config.json"
    slides_target = data_root / "slides.json"
    legacy_roots = legacy_roots or _legacy_runtime_roots(data_root=data_root)
    report = MigrationReport()

    data_root.mkdir(parents=True, exist_ok=True)

    for root in legacy_roots:
        root = Path(root)
        old_songs = root / "songs"
        if old_songs.is_dir() and not _same_path(old_songs, songs_target):
            songs_target.mkdir(parents=True, exist_ok=True)
            for item in old_songs.iterdir():
                dest = songs_target / item.name
                if dest.exists() or dest.is_symlink():
                    continue
                try:
                    if _is_dir_link(item, is_junction_fn):
                        link_fn(item.resolve(strict=False), dest)
                    elif item.is_dir():
                        copytree_fn(item, dest)
                    elif item.is_file():
                        copy2_fn(item, dest)
                    else:
                        continue
                    report.songs += 1
                except Exception as ex:
                    report.failures.append(f"songs/{item.name}: {ex}")

        old_out = root / "out"
        if old_out.is_dir() and not out_target.exists() and not _same_path(old_out, out_target):
            try:
                copytree_fn(old_out, out_target)
                report.out = True
            except Exception as ex:
                report.failures.append(f"out: {ex}")

        old_config = root / "config.json"
        if old_config.is_file() and not config_target.exists() and not _same_path(old_config, config_target):
            try:
                cfg = json.loads(old_config.read_text(encoding="utf-8"))
                cfg = _rewrite_legacy_config_songs_dir(cfg, legacy_roots, songs_target)
                config_target.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
                report.config = True
            except Exception as ex:
                report.failures.append(f"config.json: {ex}")

        old_slides = root / "slides.json"
        if old_slides.is_file() and not slides_target.exists() and not _same_path(old_slides, slides_target):
            try:
                copy2_fn(old_slides, slides_target)
                report.slides = True
            except Exception as ex:
                report.failures.append(f"slides.json: {ex}")

    return report


def prepare_runtime_data() -> MigrationReport:
    report = migrate_legacy_runtime_data()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DEFAULT_SONGS_DIR.mkdir(parents=True, exist_ok=True)
    return report


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"songs_dir": str(DEFAULT_SONGS_DIR)}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def import_song_folder(src: Path, songs_dir: Path) -> tuple[bool, str, str | None]:
    if not src.exists():
        return False, "目录不存在", None
    if not src.is_dir():
        return False, "请拖入歌曲文件夹，而不是单个文件。", None

    songs_dir.mkdir(parents=True, exist_ok=True)
    dest = songs_dir / src.name

    if dest.resolve() == src.resolve():
        return True, f"文件夹已在 songs 目录中: {src.name}", src.name
    if dest.exists():
        return True, f"songs 目录中已有同名文件夹: {src.name}", src.name

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dest), str(src)],
                check=True, capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.symlink(src, dest)
        return True, f"已添加 {src.name}（快捷方式）", src.name
    except Exception:
        try:
            shutil.copytree(src, dest)
            return True, f"已复制 {src.name}", src.name
        except Exception as ex:
            return False, f"添加失败: {ex}", None


# ─── Worker 线程 ──────────────────────────────────────────────────────────────

def external_merge_action_count(plan: external_merge.ExternalMergePlan | None) -> int:
    if plan is None:
        return 0
    return int(plan.summary.get("actions", 0))


def external_merge_backup_count(plan: external_merge.ExternalMergePlan | None) -> int:
    if plan is None or not plan.is_ready or external_merge_action_count(plan) <= 0:
        return 0
    count = 1
    if plan.pack_actions:
        count += 1
    count += sum(1 for action in plan.song_actions if action.operation == "update")
    count += sum(1 for action in plan.pack_image_actions if action.operation == "replace")
    return count


def external_merge_can_check(
    target_songs_dir: Path | str | None,
    *,
    busy: bool = False,
    slicing: bool = False,
) -> bool:
    return bool(target_songs_dir) and not busy and not slicing


def external_merge_can_confirm(
    plan: external_merge.ExternalMergePlan | None,
    *,
    busy: bool = False,
) -> bool:
    return bool(plan and plan.is_ready and external_merge_action_count(plan) > 0 and not busy)


def _external_merge_target_status(value: object) -> tuple[Path | None, str]:
    if not isinstance(value, str) or not value.strip():
        return None, "上次目标目录不可用，请重新选择。"
    path = Path(value).expanduser()
    try:
        if not path.exists():
            return None, "上次目标目录不可用，请重新选择。"
        if not path.is_dir():
            return None, "上次目标目录不可用，请重新选择。"
        if _path_is_link_or_junction(path):
            return None, "上次目标目录不可用，请重新选择。"
    except OSError:
        return None, "上次目标目录不可用，请重新选择。"

    resolved = _resolved(path)
    if resolved in {_resolved(CURRENT_EXPORT_SONGS_DIR), _resolved(LIBRARY_EXPORT_SONGS_DIR)}:
        return None, "上次目标目录不可用，请重新选择。"
    return path.absolute(), ""


def external_merge_dirty_view_model(
    target_songs_dir: Path | str | None = None,
    *,
    backup_root: Path = EXTERNAL_MERGE_BACKUP_ROOT,
) -> dict:
    target_text = str(target_songs_dir) if target_songs_dir else "未选择"
    return {
        "state": "dirty",
        "ready": False,
        "can_confirm": False,
        "title": "外部目标壳合并：需要先运行切片",
        "detail": (
            "⚠ 当前配置尚未导出，请先运行切片。\n"
            "导出成功后可检查合并计划。\n"
            f"目标壳 songs 目录: {target_text}\n"
            f"备份根目录: {backup_root}"
        ),
    }


def _external_merge_issue_lines(label: str, issues: list[external_merge.MergeIssue]) -> list[str]:
    if not issues:
        return []
    lines = [f"{label}:"]
    for issue in issues:
        path_text = f" ({'; '.join(issue.paths)})" if issue.paths else ""
        lines.append(f"- {issue.code}: {issue.message}{path_text}")
    return lines


def external_merge_plan_view_model(
    plan: external_merge.ExternalMergePlan | None,
    *,
    target_songs_dir: Path | str | None = None,
    backup_root: Path = EXTERNAL_MERGE_BACKUP_ROOT,
) -> dict:
    if plan is None:
        target_text = str(target_songs_dir) if target_songs_dir else "未选择"
        return {
            "state": "unchecked" if target_songs_dir else "no_target",
            "ready": False,
            "can_confirm": False,
            "title": "外部目标壳合并：未检查",
            "detail": f"目标壳 songs 目录: {target_text}\n请先选择目标并检查合并计划。",
        }

    summary = plan.summary
    lines = [
        f"来源: {plan.current_songs_dir}",
        f"目标: {plan.target_songs_dir}",
        f"备份根目录: {backup_root}",
        (
            "变更: "
            f"歌曲新增 {summary.get('song_add', 0)} / 更新 {summary.get('song_update', 0)}; "
            f"曲包新增 {summary.get('pack_add', 0)} / 更新 {summary.get('pack_update', 0)}; "
            f"曲包图新增 {summary.get('pack_image_add', 0)} / 复用 {summary.get('pack_image_reuse', 0)} / 替换 {summary.get('pack_image_replace', 0)}"
        ),
        f"预计备份项: {external_merge_backup_count(plan)}",
    ]
    lines.extend(_external_merge_issue_lines("阻止项", plan.blockers))
    lines.extend(_external_merge_issue_lines("警告", plan.warnings))

    actions = external_merge_action_count(plan)
    if plan.blockers:
        title = "外部目标壳合并：不可执行"
        state = "blocked"
    elif actions <= 0:
        title = "外部目标壳合并：无差异"
        state = "empty"
        lines.append("当前导出包与目标壳没有需要写入的差异。")
    else:
        title = "外部目标壳合并：计划就绪"
        state = "ready"
    return {
        "state": state,
        "ready": plan.is_ready,
        "can_confirm": external_merge_can_confirm(plan),
        "title": title,
        "detail": "\n".join(lines),
        "summary": dict(summary),
        "backup_count": external_merge_backup_count(plan),
    }


def external_merge_result_view_model(result: external_merge.ExternalMergeResult) -> dict:
    backup_text = str(result.backup_dir) if result.backup_dir else "未创建"
    lines = [
        f"状态: {result.status}",
        f"变更路径数: {len(result.changed_paths)}",
        f"备份目录: {backup_text}",
    ]
    if result.status == "failed_rollback_incomplete":
        lines.insert(0, "合并失败，且自动恢复不完整。")
        lines.insert(1, "请立即停止继续操作目标壳。")
        lines.insert(2, f"请保留并检查以下备份目录: {backup_text}")
    if result.message:
        lines.append(result.message)
    if result.execution_issues:
        lines.extend(_external_merge_issue_lines("执行问题", result.execution_issues))
    if result.rollback_errors:
        lines.append("回滚问题:")
        lines.extend(f"- {item}" for item in result.rollback_errors)

    completed_title = (
        "外部目标壳合并：合并完成，但备份记录存在提示"
        if result.status == "completed" and result.execution_issues
        else "外部目标壳合并：合并完成"
    )
    titles = {
        "completed": completed_title,
        "stale_plan": "外部目标壳合并：计划已过期",
        "rejected": "外部目标壳合并：已拒绝",
        "failed_rolled_back": "外部目标壳合并：失败，已恢复",
        "failed_rollback_incomplete": "外部目标壳合并：恢复不完整，请立即停止继续操作目标壳",
    }
    return {
        "state": result.status,
        "title": titles.get(result.status, "外部目标壳合并：执行结束"),
        "detail": "\n".join(lines),
        "can_confirm": False,
    }


def external_merge_confirmation_text(
    plan: external_merge.ExternalMergePlan,
    backup_root: Path = EXTERNAL_MERGE_BACKUP_ROOT,
) -> str:
    summary = plan.summary
    return (
        "即将把 current_export/songs 合并到外部目标壳 songs 目录。\n\n"
        f"目标: {plan.target_songs_dir}\n"
        f"歌曲新增 {summary.get('song_add', 0)} / 更新 {summary.get('song_update', 0)}\n"
        f"曲包新增 {summary.get('pack_add', 0)} / 更新 {summary.get('pack_update', 0)}\n"
        f"曲包图新增 {summary.get('pack_image_add', 0)} / 复用 {summary.get('pack_image_reuse', 0)} / 替换 {summary.get('pack_image_replace', 0)}\n"
        f"预计备份项: {external_merge_backup_count(plan)}\n"
        f"备份根目录: {backup_root}\n\n"
        "此操作会修改目标 songs 目录。\n"
        "执行时会在备份根目录下创建一个时间戳子目录。\n"
        "工具会先备份受影响项目；无关资源不会被主动清理。\n"
        "请确认目标是测试壳副本。"
    )


def external_merge_log_line(result: external_merge.ExternalMergeResult) -> tuple[str, str]:
    backup_text = str(result.backup_dir) if result.backup_dir else "未创建"
    if result.status == "completed":
        return (
            f"[外部合并] 完成：修改 {len(result.changed_paths)} 项；备份：{backup_text}",
            "ok" if not result.execution_issues else "muted",
        )
    if result.status == "stale_plan":
        return ("[外部合并] 未执行：检查后内容发生变化，请重新检查。", "muted")
    if result.status == "failed_rolled_back":
        return (f"[外部合并] 失败，但已自动恢复；备份：{backup_text}", "err")
    if result.status == "failed_rollback_incomplete":
        return (f"[外部合并] 恢复不完整，请立即停止继续操作目标壳；备份：{backup_text}", "err")
    return (f"[外部合并] 未执行：{result.status}", "err")


class ExternalMergeWorker(QThread):
    done_signal = pyqtSignal(str, int, object, str)

    def __init__(
        self,
        mode: str,
        generation: int,
        current_songs_dir: Path,
        target_songs_dir: Path,
        backup_root: Path | None = None,
        plan: external_merge.ExternalMergePlan | None = None,
    ):
        super().__init__()
        self.mode = mode
        self.generation = int(generation)
        self.current_songs_dir = Path(current_songs_dir)
        self.target_songs_dir = Path(target_songs_dir)
        self.backup_root = Path(backup_root or EXTERNAL_MERGE_BACKUP_ROOT)
        self.plan = plan

    def run(self):
        try:
            if self.mode == "check":
                payload = external_merge.build_external_merge_plan(self.current_songs_dir, self.target_songs_dir)
            elif self.mode == "execute":
                if self.plan is None:
                    raise RuntimeError("missing external merge plan")
                payload = external_merge.execute_external_merge(self.plan, backup_root=self.backup_root)
            else:
                raise RuntimeError(f"unknown external merge worker mode: {self.mode}")
            self.done_signal.emit(self.mode, self.generation, payload, "")
        except Exception as ex:
            self.done_signal.emit(self.mode, self.generation, None, str(ex))


class SlicerWorker(QThread):
    log_signal  = pyqtSignal(str, str)  # text, kind
    done_signal = pyqtSignal(int)       # return code

    def __init__(
        self, songs_dir: Path, song_id: str, segments: list,
        speed: float, songlist_meta: dict | None = None,
        songlist_enabled: bool = False,
        song_template: SongTemplate | None = None,
        current_export_enabled: bool = True,
        library_export_enabled: bool = True,
        packlist_enabled: bool = False,
        pack_template: PackTemplate | None = None,
    ):
        super().__init__()
        self.songs_dir     = songs_dir
        self.song_id       = song_id
        self.segments      = segments
        self.speed         = speed
        self.songlist_meta = songlist_meta
        self.songlist_enabled = songlist_enabled
        self.song_template = song_template
        self.current_export_enabled = current_export_enabled
        self.library_export_enabled = library_export_enabled
        self.packlist_enabled = packlist_enabled
        self.pack_template = pack_template

    def run(self):
        def log(text, kind="normal"):
            self.log_signal.emit(text, kind)

        log(f"  songs 目录: {self.songs_dir}", "muted")
        log(f"  曲目: {self.song_id}  速度: {self.speed}  段数: {len(self.segments)}", "muted")
        if self.songlist_enabled:
            log("  songlist 生成: 开启", "muted")
        if effective_packlist_export_enabled(self.packlist_enabled, self.songlist_enabled):
            log("  packlist 生成: 开启", "muted")
        log(
            f"  导出目标: current={'开' if self.current_export_enabled else '关'} "
            f"library={'开' if effective_library_export_enabled(self.library_export_enabled, self.songlist_enabled) else '关'}",
            "muted",
        )
        code = do_slice(
            self.songs_dir, self.song_id, self.segments, self.speed, log,
            self.songlist_meta, self.songlist_enabled, self.song_template,
            self.current_export_enabled, self.library_export_enabled,
            self.packlist_enabled, self.pack_template,
        )
        if code == 0:
            log("✓ 全部完成！输出目录: out/current_export/songs/", "ok")
        self.done_signal.emit(code)


# ─── 样式表 ───────────────────────────────────────────────────────────────────

QSS = f"""
QWidget {{
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 14px;
    color: {C_TEXT};
}}
QMainWindow, #root {{
    background-color: {C_BG};
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #C9C4B8;
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QComboBox {{
    background: #FFFFFF;
    border: 1px solid {C_INPUT_BD};
    border-radius: 9px;
    padding: 9px 30px 9px 12px;
    font-size: 14px;
    font-weight: 500;
    min-width: 120px;
}}
QComboBox:focus {{
    border-color: {C_ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {C_LABEL};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background: #FFFFFF;
    border: 1px solid {C_INPUT_BD};
    border-radius: 8px;
    selection-background-color: {C_CARD2};
    selection-color: {C_TEXT};
    padding: 4px;
}}
QLineEdit {{
    background: {C_INPUT_BG};
    border: 1px solid {C_INPUT_BD};
    border-radius: 9px;
    padding: 9px 11px;
    font-size: 14px;
    font-family: "Consolas", "Courier New", monospace;
}}
QLineEdit:focus {{
    border-color: {C_ACCENT};
}}
QPushButton {{
    font-family: "Segoe UI", sans-serif;
    font-weight: 600;
    border-radius: 11px;
    cursor: pointer;
}}
QPushButton#btnRun {{
    background: {C_ACCENT};
    color: #211A16;
    border: 1px solid {C_ACCENT_H};
    padding: 12px 22px;
    font-size: 14px;
    font-weight: 750;
}}
QPushButton#btnRun:hover {{
    background: {C_ACCENT_H};
    color: #FFFFFF;
}}
QPushButton#btnRun:disabled {{
    background: #D8CEC1;
    color: #5D554B;
    border: 1px solid #BFB4A6;
}}
QPushButton#btnSec {{
    background: #EEE9DE;
    color: {C_TEXT2};
    border: 1px solid #D8D0C2;
    padding: 11px 16px;
    font-size: 14px;
}}
QPushButton#btnSec:hover {{
    background: #E3DED2;
    border-color: #C9BFAF;
}}
QPushButton#btnSec:disabled {{
    background: #E1DBD0;
    color: #7F776B;
    border: 1px solid #C9C0B2;
}}
QPushButton#btnAdd {{
    background: #FBFAF6;
    color: {C_LABEL};
    border: 1.5px dashed #D8D2C4;
    border-radius: 12px;
    padding: 13px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#btnAdd:hover {{
    border-color: {C_ACCENT};
    color: {C_ACCENT};
    background: #FBF1EC;
}}
QPushButton#btnDir {{
    background: {C_CARD};
    color: {C_TEXT2};
    border: 1px solid #D8D2C4;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#btnDir:hover {{
    background: #F0ECE2;
    border-color: {C_ACCENT};
    color: {C_ACCENT};
}}
QPushButton#btnDel {{
    background: {C_INPUT_BG};
    color: #B0584A;
    border: 1px solid #EAE6DC;
    border-radius: 8px;
    padding: 0;
    font-size: 12px;
    font-weight: 600;
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
}}
QPushButton#btnDel:hover {{
    background: #FBECE8;
    border-color: #E6907A;
}}
QTextEdit#log {{
    background: #1F1E1B;
    color: #E0D8C9;
    border: none;
    border-radius: 12px;
    padding: 14px 16px;
    font-family: "Consolas", "JetBrains Mono", monospace;
    font-size: 12px;
    line-height: 1.75;
}}
"""


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def make_label(text: str, size: int = 14, weight: int = 400, color: str = C_TEXT) -> QLabel:
    lbl = QLabel(text)
    f = lbl.font()
    f.setPointSize(size)
    f.setWeight(QFont.Weight(weight))
    lbl.setFont(f)
    lbl.setStyleSheet(f"color: {color}; background: transparent;")
    return lbl


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size: 11px; font-weight: 600; letter-spacing: 1px; "
        f"color: {C_LABEL}; background: transparent;"
    )
    return lbl


def metadata_field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size: 11px; font-weight: 650; letter-spacing: 0.5px; "
        f"color: {C_MUTED}; background: transparent; border: none; padding: 0;"
    )
    return lbl


def section_title(text: str, subtitle: str = "") -> QLabel:
    full_text = text if not subtitle else f"{text}  {subtitle}"
    lbl = QLabel(full_text)
    lbl.setStyleSheet(
        f"font-size: 13px; font-weight: 750; letter-spacing: 0.2px; "
        f"color: {C_TEXT2}; background: transparent; border: none; padding: 2px 0 4px 0;"
    )
    return lbl


def card_frame(bg: str = C_CARD, border: str = C_BORDER) -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        f"background: {bg}; border: 1px solid {border}; "
        f"border-radius: 12px;"
    )
    return f


# ─── DropZone ─────────────────────────────────────────────────────────────────

class CollapsibleHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_style()

    def _refresh_style(self):
        bg = "#EFE6D9" if self._hover else "#F2EBDF"
        border = "#D3C7B7" if self._hover else "#DDD3C3"
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border}; border-radius: 9px; }}"
        )

    def enterEvent(self, event: QEvent):
        self._hover = True
        self._refresh_style()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        self._hover = False
        self._refresh_style()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DropZone(QFrame):
    folder_dropped = pyqtSignal(str)
    invalid_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._over = False
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()
        self._update_style()

    def _setup_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 13, 18, 13)
        lay.setSpacing(14)

        icon = QLabel("📂")
        icon.setStyleSheet("font-size: 20px; background: transparent; border: none;")
        icon.setFixedWidth(28)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self._main_lbl = QLabel("将谱面文件夹拖入此处，或点击选择")
        self._main_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {C_MUTED}; background: transparent; border: none;"
        )
        sub_lbl = QLabel("选中的文件夹以快捷方式链接到 songs 目录，无需复制文件")
        sub_lbl.setStyleSheet(
            f"font-size: 11px; color: {C_LABEL}; background: transparent; border: none;"
        )
        text_col.addWidget(self._main_lbl)
        text_col.addWidget(sub_lbl)

        lay.addWidget(icon)
        lay.addLayout(text_col)

    def _update_style(self):
        if self._over:
            self.setStyleSheet(
                f"QFrame {{ background: #FBF1EC; border: 1.5px dashed {C_ACCENT}; border-radius: 12px; }}"
            )
            self._main_lbl.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {C_ACCENT}; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                "QFrame { background: #FBFAF6; border: 1.5px dashed #D8D2C4; border-radius: 12px; }"
            )
            self._main_lbl.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {C_MUTED}; background: transparent; border: none;"
            )

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            path = QFileDialog.getExistingDirectory(self, "选择谱面文件夹")
            if path:
                self.folder_dropped.emit(path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._over = True
            self._update_style()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._over = False
        self._update_style()

    def dropEvent(self, event: QDropEvent):
        self._over = False
        self._update_style()
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self.folder_dropped.emit(path)
                break
            if path:
                self.invalid_dropped.emit("请拖入歌曲文件夹，而不是单个文件。")
                break


# ─── SegmentRow ───────────────────────────────────────────────────────────────

class ArcCutIndicator(QWidget):
    def __init__(self, side: str, parent=None):
        super().__init__(parent)
        self.side = side
        self.setFixedSize(26, 22)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#B06A3C")
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        path = QPainterPath()
        if self.side == "start":
            painter.drawLine(8, 5, 8, 17)
            path.moveTo(8, 14)
            path.cubicTo(11, 7, 16, 7, 20, 11)
        else:
            painter.drawLine(18, 5, 18, 17)
            path.moveTo(6, 11)
            path.cubicTo(10, 7, 15, 7, 18, 14)
        painter.drawPath(path)


class ArcCutInfoCard(QFrame):
    def __init__(self, owner, boundary: str, hits: list[dict]):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("arcCutInfoCard")
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedWidth(300)
        self.setStyleSheet(
            f"QFrame#arcCutInfoCard {{ background: #FFFDF8; border: 1px solid #D8D2C4; "
            f"border-radius: 8px; }}"
            f"QLabel {{ color: {C_TEXT}; background: transparent; border: none; }}"
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(80, 65, 45, 36))
        self.setGraphicsEffect(shadow)

        content = _arc_cut_info_content(hits, boundary)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 11, 12, 11)
        outer.setSpacing(8)

        title = QLabel(content["title"])
        title.setStyleSheet("font-size: 13px; font-weight: 700;")
        outer.addWidget(title)

        body = QLabel(content["body"])
        body.setWordWrap(True)
        body.setStyleSheet("font-size: 12px; line-height: 1.45;")
        outer.addWidget(body)

        hit_title = QLabel("本次命中")
        hit_title.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {C_MUTED};")
        outer.addWidget(hit_title)

        summary = QLabel(content["summary"])
        summary.setWordWrap(True)
        summary.setStyleSheet("font-size: 12px; font-weight: 600;")
        outer.addWidget(summary)

        footer = QLabel(content["footer"])
        footer.setWordWrap(True)
        footer.setStyleSheet(f"font-size: 11px; color: {C_MUTED}; line-height: 1.35;")
        outer.addWidget(footer)
        self.adjustSize()

    def enterEvent(self, event):
        self.owner.cancel_hide_card()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.owner.schedule_hide_card()
        super().leaveEvent(event)


class ArcCutStatus(QFrame):
    def __init__(self, boundary: str, hits: list[dict], parent=None):
        super().__init__(parent)
        self.boundary = boundary
        self.hits = list(hits)
        self._card: ArcCutInfoCard | None = None
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self.show_card)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_card)

        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent; border: none;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.indicator = ArcCutIndicator(boundary, self)
        self.label = QLabel("起点截断" if boundary == "start" else "终点截断")
        self.label.setStyleSheet(
            "font-size: 11px; font-weight: 600; color: #B06A3C; "
            "background: transparent; border: none;"
        )
        lay.addWidget(self.indicator)
        lay.addWidget(self.label)

        for widget in (self, self.indicator, self.label):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Enter:
            self.schedule_show_card()
        elif event.type() == QEvent.Type.Leave:
            self.schedule_hide_card()
        return super().eventFilter(obj, event)

    def schedule_show_card(self):
        self._hide_timer.stop()
        self._show_timer.start(100)

    def schedule_hide_card(self):
        self._show_timer.stop()
        self._hide_timer.start(420)

    def cancel_hide_card(self):
        self._hide_timer.stop()

    def show_card(self):
        if self._card is None:
            self._card = ArcCutInfoCard(self, self.boundary, self.hits)
        self._position_card()
        self._card.show()
        self._card.raise_()

    def hide_card(self):
        if self._card is not None:
            self._card.hide()

    def deleteLater(self):
        self.hide_card()
        if self._card is not None:
            self._card.deleteLater()
            self._card = None
        super().deleteLater()

    def _position_card(self):
        if self._card is None:
            return
        self._card.adjustSize()
        card_w = self._card.width() or self._card.sizeHint().width()
        card_h = self._card.height() or self._card.sizeHint().height()
        top_left = self.mapToGlobal(QPoint(0, 0))
        status_rect = QRect(top_left, self.size())

        screen = self.screen() or QApplication.screenAt(status_rect.center()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        margin = 10

        x = status_rect.left() - card_w - margin
        if x < available.left():
            x = status_rect.right() + margin
        if x + card_w > available.right():
            x = available.right() - card_w

        y = status_rect.top()
        if y + card_h > available.bottom():
            y = status_rect.top() - card_h - margin
        y = max(available.top(), min(y, available.bottom() - card_h))
        x = max(available.left(), min(x, available.right() - card_w))
        self._card.move(x, y)


class SegmentRow(QFrame):
    deleted = pyqtSignal(object)   # emits self
    changed = pyqtSignal()
    end_cap_requested = pyqtSignal(object)

    def __init__(self, index: int, s: int | None, e: int | None, parent=None):
        super().__init__(parent)
        self.s_val = s
        self.e_val = e
        self.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid #EAE6DC; border-radius: 12px; }"
        )
        self._setup_ui(index, s, e)

    def _setup_ui(self, index: int, s: int | None, e: int | None):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(8)

        badge = QLabel(str(index))
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {C_BADGE_BG}; color: {C_ACCENT}; "
            f"font-weight: 700; font-size: 13px; border-radius: 8px; border: none;"
        )
        self._badge = badge

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(9)
        title_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

        title_box = QWidget()
        title_box.setStyleSheet("background: transparent; border: none;")
        title_lay = QHBoxLayout(title_box)
        title_lay.setContentsMargins(0, 0, 0, 0)
        title_lay.setSpacing(6)
        self._interval_label = QLabel("片段区间（ms）")
        self._interval_label.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {C_TEXT2}; background: transparent; border: none;"
        )
        self._interval_unit_label = QLabel("AFF 整数毫秒")
        self._interval_unit_label.setStyleSheet(
            f"font-size: 11px; font-weight: 500; color: {C_LABEL}; background: transparent; border: none;"
        )
        title_lay.addWidget(self._interval_label)
        title_lay.addWidget(self._interval_unit_label)
        title_lay.addStretch()
        title_row.addWidget(title_box, 1)

        self._dur = QLabel()
        self._dur.setStyleSheet(
            f"font-family: 'Consolas','Courier New',monospace; font-size: 13px; "
            f"font-weight: 500; color: {C_LABEL}; background: transparent; border: none;"
        )
        self._dur.setMinimumWidth(72)
        self._dur.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self._dur, 0, Qt.AlignmentFlag.AlignVCenter)

        btn_del = QPushButton("✕")
        btn_del.setObjectName("btnDel")
        title_row.addWidget(btn_del, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(title_row)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(36, 0, 0, 0)
        input_row.setSpacing(10)

        start_col = QWidget()
        start_col.setStyleSheet("background: transparent; border: none;")
        start_lay = QVBoxLayout(start_col)
        start_lay.setContentsMargins(0, 0, 0, 0)
        start_lay.setSpacing(5)
        start_label_row = QHBoxLayout()
        start_label_row.setContentsMargins(0, 0, 0, 0)
        start_label_row.setSpacing(4)
        self._start_sub_label = self._make_segment_field_label("起点")
        self._start_unit_label = self._make_segment_unit_label("ms")
        start_label_row.addWidget(self._start_sub_label)
        start_label_row.addWidget(self._start_unit_label)
        start_label_row.addStretch()
        start_lay.addLayout(start_label_row)
        self._start = QLineEdit("" if s is None else str(s))
        self._start.setPlaceholderText("输入起点")
        self._start.setMinimumWidth(132)
        self._start.setStyleSheet(self._segment_time_input_qss())
        self._install_time_validator(self._start)
        start_lay.addWidget(self._start)
        input_row.addWidget(start_col, 1)

        arrow = QLabel("→")
        arrow.setStyleSheet(f"color: #C9C4B8; font-size: 15px; background: transparent; border: none;")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        input_row.addWidget(arrow, 0, Qt.AlignmentFlag.AlignBottom)

        end_col = QWidget()
        end_col.setStyleSheet("background: transparent; border: none;")
        end_lay = QVBoxLayout(end_col)
        end_lay.setContentsMargins(0, 0, 0, 0)
        end_lay.setSpacing(5)
        end_label_row = QHBoxLayout()
        end_label_row.setContentsMargins(0, 0, 0, 0)
        end_label_row.setSpacing(4)
        self._end_sub_label = self._make_segment_field_label("终点")
        self._end_unit_label = self._make_segment_unit_label("ms")
        end_label_row.addWidget(self._end_sub_label)
        end_label_row.addWidget(self._end_unit_label)
        end_label_row.addStretch()
        end_lay.addLayout(end_label_row)
        self._end = QLineEdit("" if e is None else str(e))
        self._end.setPlaceholderText("输入终点")
        self._end.setMinimumWidth(132)
        self._end.setStyleSheet(self._segment_time_input_qss())
        self._install_time_validator(self._end)
        end_lay.addWidget(self._end)
        input_row.addWidget(end_col, 1)
        input_row.addStretch(1)
        lay.addLayout(input_row)

        self._start_error = self._make_time_error_label()
        self._end_error = self._make_time_error_label()
        self._end_cap_btn = QPushButton("")
        self._end_cap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._end_cap_btn.setFixedHeight(20)
        self._end_cap_btn.setStyleSheet(
            "QPushButton {"
            "background: #FFF3EA; "
            f"border: 1px solid {C_ACCENT}; "
            "border-radius: 6px; "
            f"color: {C_ACCENT_H}; "
            "font-size: 10px; "
            "font-weight: 700; "
            "padding: 1px 7px;"
            "}"
            "QPushButton:hover {"
            "background: #FBE2D5; "
            f"border-color: {C_ACCENT_H}; "
            f"color: {C_ACCENT_H};"
            "}"
        )
        self._end_cap_btn.hide()
        self._end_cap_btn.clicked.connect(lambda: self.end_cap_requested.emit(self))

        status_row = QHBoxLayout()
        status_row.setContentsMargins(36, 0, 0, 0)
        status_row.setSpacing(10)
        status_row.addWidget(self._start_error)
        status_row.addWidget(self._end_error)
        status_row.addWidget(self._end_cap_btn)

        self._arc_indicator_box = QWidget()
        self._arc_indicator_box.setStyleSheet("background: transparent; border: none;")
        self._arc_status_layout = QHBoxLayout(self._arc_indicator_box)
        self._arc_status_layout.setContentsMargins(0, 0, 0, 0)
        self._arc_status_layout.setSpacing(12)
        self._arc_statuses: list[ArcCutStatus] = []
        status_row.addWidget(self._arc_indicator_box)
        status_row.addStretch()
        lay.addLayout(status_row)
        self.set_arc_cut_warnings([], [])

        self._update_dur()
        self._start.textChanged.connect(self._on_change)
        self._end.textChanged.connect(self._on_change)
        btn_del.clicked.connect(lambda: self.deleted.emit(self))

    def _make_segment_field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 11px; font-weight: 650; letter-spacing: 0.3px; "
            f"color: {C_MUTED}; background: transparent; border: none; padding: 0;"
        )
        return label

    def _make_segment_unit_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 10px; font-weight: 500; color: {C_LABEL}; "
            f"background: transparent; border: none; padding: 0;"
        )
        return label

    def _segment_time_input_qss(self) -> str:
        return (
            "QLineEdit {"
            f"background: {C_INPUT_BG}; "
            f"border: 1px solid {C_INPUT_BD}; "
            "border-radius: 8px; "
            f"color: {C_TEXT}; "
            "font-size: 13px; "
            "padding: 7px 9px;"
            "}"
            "QLineEdit:focus {"
            f"border-color: {C_ACCENT}; "
            "background: #FFFDF8;"
            "}"
        )

    def _install_time_validator(self, field: QLineEdit) -> None:
        try:
            from PyQt6.QtCore import QRegularExpression
            from PyQt6.QtGui import QRegularExpressionValidator

            field.setValidator(QRegularExpressionValidator(QRegularExpression(TIME_INPUT_PATTERN), field))
        except Exception:
            pass

    def _make_time_error_label(self) -> QLabel:
        label = QLabel("")
        label.setStyleSheet(
            f"font-size: 10px; font-weight: 600; color: {C_ERR}; "
            f"background: transparent; border: none;"
        )
        label.hide()
        return label

    def _on_change(self):
        try:
            self.s_val = int(self._start.text())
        except ValueError:
            self.s_val = None
        try:
            self.e_val = int(self._end.text())
        except ValueError:
            self.e_val = None
        self._update_dur()
        self.changed.emit()

    def _update_dur(self):
        if self.s_val is None or self.e_val is None:
            self._dur.setText("—")
            self._dur.setStyleSheet(
                f"font-family: 'Consolas','Courier New',monospace; font-size: 13px; "
                f"color: {C_LABEL}; background: transparent; border: none;"
            )
            return
        d = self.e_val - self.s_val
        if d < 0:
            self._dur.setText("⚠ 负数")
            self._dur.setStyleSheet(
                f"font-family: 'Consolas','Courier New',monospace; font-size: 13px; "
                f"color: {C_ERR}; background: transparent; border: none;"
            )
            self.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #E6B5A8; border-radius: 12px; }")
        else:
            self._dur.setText(f"{d/1000:.2f}s")
            self._dur.setStyleSheet(
                f"font-family: 'Consolas','Courier New',monospace; font-size: 13px; "
                f"color: {C_LABEL}; background: transparent; border: none;"
            )
            self.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #EAE6DC; border-radius: 12px; }")

    def update_index(self, index: int):
        self._badge.setText(str(index))

    def start_text(self) -> str:
        return self._start.text()

    def end_text(self) -> str:
        return self._end.text()

    def set_time_errors(
        self,
        start_error: str = "",
        end_error: str = "",
        end_cap_ms: int | None = None,
    ) -> None:
        for label, message in ((self._start_error, start_error), (self._end_error, end_error)):
            label.setText(message)
            label.setToolTip(message)
            label.setVisible(bool(message))
        if end_cap_ms is None:
            self._end_cap_btn.setText("")
            self._end_cap_btn.setToolTip("")
            self._end_cap_btn.hide()
        else:
            text = f"设为上限 {int(end_cap_ms)} ms"
            self._end_cap_btn.setText(text)
            self._end_cap_btn.setToolTip(text)
            self._end_cap_btn.show()

    def clear_time_errors(self) -> None:
        self.set_time_errors("", "")

    def focus_time_field(self, field: str | None) -> None:
        widget = self._start if field == "start" else self._end
        widget.setFocus()
        widget.selectAll()

    def set_end_text(self, end_ms: int) -> None:
        self._end.setText(str(int(end_ms)))
        self._on_change()

    def set_arc_cut_indicators(self, start_hits: list[dict], end_hits: list[dict]) -> None:
        for status in self._arc_statuses:
            self._arc_status_layout.removeWidget(status)
            status.deleteLater()
        self._arc_statuses = []

        if start_hits:
            status = ArcCutStatus("start", start_hits, self._arc_indicator_box)
            self._arc_status_layout.addWidget(status)
            self._arc_statuses.append(status)
        if end_hits:
            status = ArcCutStatus("end", end_hits, self._arc_indicator_box)
            self._arc_status_layout.addWidget(status)
            self._arc_statuses.append(status)

        self._arc_indicator_box.setVisible(bool(self._arc_statuses))

    def set_arc_cut_warnings(self, start_hits: list[dict], end_hits: list[dict]) -> None:
        self.set_arc_cut_indicators(start_hits, end_hits)

    def to_dict(self) -> dict | None:
        if self.s_val is None or self.e_val is None:
            return None
        return {"s": self.s_val, "e": self.e_val}


# ─── Songlist 配置面板 ────────────────────────────────────────────────────────

class SonglistPanel(QFrame):
    """可折叠的 Songlist 元数据配置面板。"""

    enabled_changed = pyqtSignal()
    metadata_changed = pyqtSignal()

    # 字段定义：(显示标签, key, 占位提示)
    _FIELDS = [
        ("曲名基础 TITLE BASE",          "title_base",      "e.g. Fractureray"),
        ("作曲者 ARTIST",                "artist",          "e.g. xi"),
        ("BPM 字符串",                   "bpm",             "e.g. 228"),
        ("基准 BPM (bpm_base)",          "bpm_base",        "e.g. 228.0"),
        ("曲包 ID (set)",                "set",             "e.g. single"),
        ("购买方式 (purchase)",           "purchase",        "留空即可"),
        ("Side  0光/1纷/2消/3Lephon",    "side",            "0"),
        ("背景图 (bg)",                  "bg",              "e.g. base_light"),
        ("游戏版本 (version)",            "version",         "e.g. 5.0"),
        ("谱师 (chartDesigner)",         "chart_designer",  ""),
        ("封面画师 (jacketDesigner)",     "jacket_designer", ""),
        ("定数 RATING",                  "rating",          "9"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._pack_expanded = False
        self._syncing_shared_pack_id = False
        self._resetting_source = False
        self._last_shared_pack_id = ""
        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        outer.addWidget(section_title("元数据导出"))

        self._songlist_item = QFrame()
        self._songlist_item.setStyleSheet(
            f"QFrame {{ background: #F6F1E8; border: 1px solid #DED4C5; border-radius: 12px; }}"
        )
        songlist_lay = QVBoxLayout(self._songlist_item)
        songlist_lay.setContentsMargins(14, 11, 14, 11)
        songlist_lay.setSpacing(8)
        self._songlist_header = CollapsibleHeader()
        self._songlist_header.clicked.connect(self._toggle)
        songlist_head = QHBoxLayout(self._songlist_header)
        songlist_head.setContentsMargins(10, 7, 10, 7)
        songlist_head.setSpacing(10)
        self._enabled = QCheckBox("生成 songlist")
        self._enabled.setChecked(False)
        self._enabled.setStyleSheet(
            f"color: {C_TEXT2}; font-size: 13px; font-weight: 650; background: transparent; border: none;"
        )
        self._enabled.clicked.connect(self._on_songlist_enabled_changed)
        songlist_head.addWidget(self._enabled)
        songlist_head.addStretch()
        self._toggle_btn = QPushButton("▸")
        self._toggle_btn.clicked.connect(self._toggle)
        songlist_head.addWidget(self._toggle_btn)
        songlist_lay.addWidget(self._songlist_header)
        self._songlist_hint = QLabel("勾选后可填写 songlist 元数据")
        self._songlist_hint.setStyleSheet(
            f"font-size: 12px; color: {C_LABEL}; background: transparent; border: none;"
        )
        songlist_lay.addWidget(self._songlist_hint)
        outer.addWidget(self._songlist_item)

        self._packlist_item = QFrame()
        self._packlist_item.setStyleSheet(
            f"QFrame {{ background: #F6F1E8; border: 1px solid #DED4C5; border-radius: 12px; }}"
        )
        pack_item_lay = QVBoxLayout(self._packlist_item)
        pack_item_lay.setContentsMargins(14, 11, 14, 11)
        pack_item_lay.setSpacing(8)
        self._packlist_header = CollapsibleHeader()
        self._packlist_header.clicked.connect(self._toggle_pack)
        pack_head = QHBoxLayout(self._packlist_header)
        pack_head.setContentsMargins(10, 7, 10, 7)
        pack_head.setSpacing(10)
        self._packlist_enabled = QCheckBox("生成 packlist 与曲包资源")
        self._packlist_enabled.setChecked(False)
        self._packlist_enabled.setStyleSheet(
            f"color: {C_TEXT2}; font-size: 13px; font-weight: 650; background: transparent; border: none;"
        )
        self._packlist_enabled.clicked.connect(self._on_packlist_enabled_changed)
        pack_head.addWidget(self._packlist_enabled)
        pack_head.addStretch()
        self._pack_toggle_btn = QPushButton("▸")
        self._pack_toggle_btn.clicked.connect(self._toggle_pack)
        pack_head.addWidget(self._pack_toggle_btn)
        pack_item_lay.addWidget(self._packlist_header)
        self._packlist_hint = QLabel("勾选后可填写曲包信息")
        self._packlist_hint.setStyleSheet(
            f"font-size: 12px; color: {C_LABEL}; background: transparent; border: none;"
        )
        pack_item_lay.addWidget(self._packlist_hint)
        outer.addWidget(self._packlist_item)

        # 面板主体
        self._body = QFrame()
        self._body.setObjectName("songlistBody")
        self._body.setStyleSheet(
            f"QFrame#songlistBody {{ background: {C_CARD}; border: 1px solid {C_BORDER};"
            f" border-radius: 14px; }}"
        )
        self._body.hide()
        songlist_lay.addWidget(self._body)

        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(22, 18, 22, 18)
        body_lay.setSpacing(14)

        # 说明文字
        note = QLabel(
            "以下信息对所有切片段共用。曲名自动加 01 / 02… 编号，"
            "id 自动取文件夹名，audioPreview/End 自动计算。"
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"font-size: 12px; color: {C_MUTED}; background: transparent; border: none;")
        body_lay.addWidget(note)

        # 字段网格（2 列）
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(12)
        self._inputs: dict[str, QLineEdit] = {}

        for i, (label_text, key, placeholder) in enumerate(self._FIELDS):
            row, col = divmod(i, 2)
            col_lay = QVBoxLayout()
            col_lay.setSpacing(5)
            col_lay.addWidget(metadata_field_label(label_text))
            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            if key == "set":
                inp.setText("single")
            elif key == "side":
                inp.setText("0")
            elif key == "rating":
                inp.setText("9")
            col_lay.addWidget(inp)
            grid.addLayout(col_lay, row, col)
            self._inputs[key] = inp
            if key != "set":
                inp.textChanged.connect(self._emit_metadata_changed)

        body_lay.addLayout(grid)

        # Rating Plus 行
        rp_row = QHBoxLayout()
        rp_row.setSpacing(10)
        self._rating_plus = QCheckBox("有 +（ratingPlus）")
        self._rating_plus.setStyleSheet(
            f"color: {C_TEXT2}; font-size: 13px; background: transparent; border: none;"
        )
        rp_row.addWidget(self._rating_plus)
        rp_row.addStretch()
        body_lay.addLayout(rp_row)

        self._pack_body = QFrame()
        self._pack_body.setObjectName("packlistBody")
        self._pack_body.setStyleSheet(
            f"QFrame#packlistBody {{ background: {C_CARD}; border: 1px solid {C_BORDER};"
            f" border-radius: 14px; }}"
        )
        self._pack_body.hide()
        pack_item_lay.addWidget(self._pack_body)
        pack_body_lay = QVBoxLayout(self._pack_body)
        pack_body_lay.setContentsMargins(0, 0, 0, 0)
        pack_body_lay.setSpacing(0)

        pack_frame = QFrame()
        pack_frame.setStyleSheet(
            f"QFrame {{ background: {C_CARD2}; border: 1px solid {C_BORDER2}; border-radius: 12px; }}"
        )
        pack_lay = QVBoxLayout(pack_frame)
        pack_lay.setContentsMargins(14, 12, 14, 12)
        pack_lay.setSpacing(10)
        pack_lay.addWidget(field_label("PACKLIST"))
        self._pack_inputs: dict[str, QLineEdit] = {}
        pack_fields = [
            ("曲包 ID PACK ID", "pack_id", ""),
            ("曲包显示名 PACK NAME", "pack_name", ""),
            ("曲包描述 DESCRIPTION", "pack_description", pack_description_placeholder("")),
            ("曲包封面文件名 IMG", "pack_img", "select_<pack_id>.png"),
        ]
        pack_grid = QGridLayout()
        pack_grid.setHorizontalSpacing(20)
        pack_grid.setVerticalSpacing(10)
        for i, (label_text, key, placeholder) in enumerate(pack_fields):
            row, col = divmod(i, 2)
            col_lay = QVBoxLayout()
            col_lay.setSpacing(5)
            col_lay.addWidget(metadata_field_label(label_text))
            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            col_lay.addWidget(inp)
            pack_grid.addLayout(col_lay, row, col)
            self._pack_inputs[key] = inp
            if key != "pack_id":
                inp.textChanged.connect(self._emit_metadata_changed)
        pack_lay.addLayout(pack_grid)

        cover_row = QHBoxLayout()
        cover_row.setSpacing(10)
        self._pack_upload_check = QCheckBox("使用上传图片")
        self._pack_upload_check.setStyleSheet(
            f"color: {C_TEXT2}; font-size: 13px; background: transparent; border: none;"
        )
        self._pack_upload_check.clicked.connect(self._emit_metadata_changed)
        self._pack_cover_path = QLineEdit()
        self._pack_cover_path.setPlaceholderText("PNG / JPG / JPEG")
        self._pack_cover_path.textChanged.connect(self._emit_metadata_changed)
        btn_cover = QPushButton("选择图片")
        btn_cover.setObjectName("btnSec")
        btn_cover.clicked.connect(self._browse_pack_cover)
        cover_row.addWidget(self._pack_upload_check)
        cover_row.addWidget(self._pack_cover_path, 1)
        cover_row.addWidget(btn_cover)
        pack_lay.addLayout(cover_row)
        self._pack_controls = [pack_frame, *self._pack_inputs.values(), self._pack_upload_check, self._pack_cover_path, btn_cover]
        self._last_pack_default_source = ""
        self._inputs["set"].textChanged.connect(self._on_set_pack_id_changed)
        self._pack_inputs["pack_id"].textChanged.connect(self._on_pack_id_changed)
        self._update_pack_description_placeholder("")
        pack_body_lay.addWidget(pack_frame)
        self._refresh_packlist_state()

    # ── 折叠 / 展开 ───────────────────────────────────────────────────────────

    def _toggle(self):
        if not self._enabled.isChecked():
            return
        self._expanded = not self._expanded
        self._refresh_packlist_state()

    def _toggle_pack(self):
        if not (self._enabled.isChecked() and self._packlist_enabled.isChecked()):
            return
        self._pack_expanded = not self._pack_expanded
        self._refresh_packlist_state()

    def _on_songlist_enabled_changed(self):
        if not self._enabled.isChecked():
            self._expanded = False
            self._pack_expanded = False
        self._refresh_packlist_state()
        self.enabled_changed.emit()

    def _on_packlist_enabled_changed(self):
        if not self._packlist_enabled.isChecked():
            self._pack_expanded = False
        self._refresh_packlist_state()
        self.enabled_changed.emit()
        self._emit_metadata_changed()

    def _emit_metadata_changed(self, *_args):
        if not getattr(self, "_resetting_source", False) and not getattr(self, "_syncing_shared_pack_id", False):
            self.metadata_changed.emit()

    def _sync_shared_pack_id(self, value: str, target: QLineEdit):
        if target.text() == value:
            return
        self._syncing_shared_pack_id = True
        try:
            target.setText(value)
        finally:
            self._syncing_shared_pack_id = False

    def _update_pack_img_for_shared_pack_id(self, old_pack_id: str, new_pack_id: str):
        img_input = self._pack_inputs["pack_img"]
        current_img = img_input.text().strip()
        old_default = default_pack_img_name(old_pack_id) if old_pack_id else ""
        if not current_img or current_img == old_default:
            self._syncing_shared_pack_id = True
            try:
                img_input.setText(default_pack_img_name(new_pack_id) if new_pack_id else "")
            finally:
                self._syncing_shared_pack_id = False

    def _update_pack_description_placeholder(self, pack_id: str | None = None):
        if not hasattr(self, "_pack_inputs") or "pack_description" not in self._pack_inputs:
            return
        target = self._pack_inputs["pack_description"]
        if not hasattr(target, "setPlaceholderText"):
            return
        value = str(pack_id if pack_id is not None else self._pack_inputs["pack_id"].text()).strip()
        target.setPlaceholderText(pack_description_placeholder(value))

    def _on_set_pack_id_changed(self, text: str):
        if self._syncing_shared_pack_id:
            return
        value = str(text).strip()
        old_pack_id = self._last_shared_pack_id
        self._sync_shared_pack_id(value, self._pack_inputs["pack_id"])
        self._update_pack_img_for_shared_pack_id(old_pack_id, value)
        self._last_shared_pack_id = value
        self._update_pack_description_placeholder(value)
        self._emit_metadata_changed()

    def _on_pack_id_changed(self, text: str):
        if self._syncing_shared_pack_id:
            return
        value = str(text).strip()
        old_pack_id = self._last_shared_pack_id
        self._sync_shared_pack_id(value, self._inputs["set"])
        self._update_pack_img_for_shared_pack_id(old_pack_id, value)
        self._last_shared_pack_id = value
        self._update_pack_description_placeholder(value)
        self._emit_metadata_changed()

    def _set_section_button_state(self, button: QPushButton, active: bool, expanded: bool):
        button.setEnabled(bool(active))
        button.setText("▾" if expanded and active else "▸")
        color = C_TEXT2 if active else C_LABEL
        button.setStyleSheet(
            f"background: transparent; border: 1px solid transparent; color: {color}; "
            f"font-size: 18px; font-weight: 800; padding: 1px 7px; border-radius: 8px;"
        )

    # ── 读 / 写 ───────────────────────────────────────────────────────────────

    def is_songlist_enabled(self) -> bool:
        return self._enabled.isChecked()

    def set_songlist_enabled(self, enabled: bool):
        self._enabled.setChecked(bool(enabled))
        if not enabled:
            self._expanded = False
            self._pack_expanded = False
        self._refresh_packlist_state()

    def is_packlist_enabled(self) -> bool:
        return self._packlist_enabled.isChecked()

    def set_packlist_enabled(self, enabled: bool):
        self._packlist_enabled.setChecked(bool(enabled))
        if not enabled:
            self._pack_expanded = False
        self._refresh_packlist_state()

    def _refresh_packlist_state(self):
        songlist_enabled = self._enabled.isChecked()
        packlist_checked = self._packlist_enabled.isChecked()
        packlist_enabled = packlist_checked and songlist_enabled
        self._expanded = bool(self._expanded and songlist_enabled)
        self._pack_expanded = bool(self._pack_expanded and packlist_enabled)
        if hasattr(self, "_body"):
            self._body.setVisible(self._expanded)
        if hasattr(self, "_pack_body"):
            self._pack_body.setVisible(self._pack_expanded)
        if hasattr(self, "_packlist_item"):
            self._packlist_item.setVisible(songlist_enabled)
        if hasattr(self, "_songlist_hint"):
            self._songlist_hint.setVisible(not songlist_enabled)
        if hasattr(self, "_packlist_hint"):
            self._packlist_hint.setVisible(songlist_enabled and not packlist_checked)
        if hasattr(self, "_toggle_btn"):
            self._set_section_button_state(self._toggle_btn, songlist_enabled, self._expanded)
        if hasattr(self, "_pack_toggle_btn"):
            self._set_section_button_state(self._pack_toggle_btn, packlist_enabled, self._pack_expanded)
        self._packlist_enabled.setEnabled(songlist_enabled)
        for widget in getattr(self, "_pack_controls", []):
            widget.setEnabled(packlist_enabled)

    def _browse_pack_cover(self):
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择曲包封面图片",
            "",
            "Images (*.png *.jpg *.jpeg)",
        )
        if path:
            self._pack_cover_path.setText(path)
            self._pack_upload_check.setChecked(True)
            self._refresh_packlist_state()
            self._emit_metadata_changed()

    def update_pack_defaults(self, source_id: str):
        source_id = str(source_id or "").strip()
        if not source_id or "目录为空" in source_id:
            return
        old_defaults = default_pack_form_for_song(self._last_pack_default_source)
        new_defaults = default_pack_form_for_song(source_id)
        mapping = {
            "pack_id": "pack_id",
            "pack_name": "pack_name",
            "pack_description": "pack_description",
            "pack_img": "pack_img",
        }
        for key, field in mapping.items():
            inp = self._pack_inputs[field]
            current = inp.text().strip()
            if not current or current == old_defaults.get(key, ""):
                inp.setText(new_defaults[key])
        self._last_pack_default_source = source_id
        self._update_pack_description_placeholder(new_defaults["pack_id"])

    def reset_for_source(self, source_id: str):
        source_id = str(source_id or "").strip()
        if not source_id or "目录为空" in source_id:
            return
        defaults = default_pack_form_for_song(source_id)
        self._resetting_source = True
        try:
            for key in ("artist", "bpm", "bpm_base", "purchase", "bg", "version",
                        "chart_designer", "jacket_designer", "rating"):
                self._inputs[key].setText("")
            self._inputs["side"].setText("0")
            self._inputs["title_base"].setText(source_id)
            self._inputs["set"].setText(defaults["pack_id"])
            self._pack_inputs["pack_id"].setText(defaults["pack_id"])
            self._pack_inputs["pack_name"].setText(defaults["pack_name"])
            self._pack_inputs["pack_description"].setText("")
            self._pack_inputs["pack_img"].setText(defaults["pack_img"])
            self._rating_plus.setChecked(False)
            self._pack_upload_check.setChecked(False)
            self._pack_cover_path.setText("")
            self._last_pack_default_source = source_id
            self._last_shared_pack_id = defaults["pack_id"]
            self._update_pack_description_placeholder(defaults["pack_id"])
        finally:
            self._resetting_source = False
        self._refresh_packlist_state()

    def get_form_data(self) -> dict:
        data = {key: self._inputs[key].text().strip() for _label, key, _placeholder in self._FIELDS}
        set_value = data.get("set", "")
        pack_value = self._pack_inputs["pack_id"].text().strip()
        shared_pack_id = pack_value if pack_value and set_value in ("", "single") else (set_value or pack_value)
        data["set"] = shared_pack_id
        data["rating_plus"] = self._rating_plus.isChecked()
        for key, inp in self._pack_inputs.items():
            data[key] = inp.text().strip()
        data["pack_id"] = shared_pack_id
        pack_id = data.get("pack_id") or ""
        if not data.get("pack_img") and pack_id:
            data["pack_img"] = default_pack_img_name(pack_id)
        data["pack_description"] = data.get("pack_description", "")
        data["pack_cover_source"] = "upload" if self._pack_upload_check.isChecked() else "auto"
        data["pack_cover_path"] = self._pack_cover_path.text().strip()
        return data

    def get_meta(self) -> dict | None:
        """返回兼容旧调用的已校验配置字典；V2.1 导出使用 SongTemplate。"""
        if not self._expanded:
            return None
        try:
            return {
                "title_base":      self._inputs["title_base"].text().strip(),
                "artist":          self._inputs["artist"].text().strip(),
                "bpm":             self._inputs["bpm"].text().strip(),
                "bpm_base":        float(self._inputs["bpm_base"].text() or "0"),
                "set":             self._inputs["set"].text().strip() or "single",
                "purchase":        self._inputs["purchase"].text().strip(),
                "side":            int(self._inputs["side"].text() or "0"),
                "bg":              self._inputs["bg"].text().strip(),
                "version":         self._inputs["version"].text().strip(),
                "chart_designer":  self._inputs["chart_designer"].text().strip(),
                "jacket_designer": self._inputs["jacket_designer"].text().strip(),
                "rating":          int(self._inputs["rating"].text() or "9"),
                "rating_plus":     self._rating_plus.isChecked(),
            }
        except ValueError:
            return None

    def set_meta(self, meta: dict):
        """从保存的数据恢复面板内容。"""
        if not meta:
            return
        self._resetting_source = True
        if "songlist_enabled" in meta:
            self.set_songlist_enabled(bool(meta["songlist_enabled"]))
        if "packlist_enabled" in meta:
            self.set_packlist_enabled(_bool_pref(meta.get("packlist_enabled"), False))
        str_keys = ("title_base", "artist", "bpm", "set", "purchase", "bg", "version",
                    "chart_designer", "jacket_designer")
        for k in str_keys:
            if k in meta:
                self._inputs[k].setText(str(meta[k]))
        for k, inp in self._pack_inputs.items():
            if k in meta:
                inp.setText(str(meta[k]))
        if "pack_cover_source" in meta:
            self._pack_upload_check.setChecked(str(meta.get("pack_cover_source")).lower() == "upload")
        if "pack_cover_path" in meta:
            self._pack_cover_path.setText(str(meta["pack_cover_path"]))
        for k in ("bpm_base", "side", "rating"):
            if k in meta:
                self._inputs[k].setText(str(meta[k]))
        if "rating_plus" in meta:
            self._rating_plus.setChecked(bool(meta["rating_plus"]))
        set_value = self._inputs["set"].text().strip()
        pack_value = self._pack_inputs["pack_id"].text().strip()
        shared_pack_id = pack_value if pack_value and set_value in ("", "single") else (set_value or pack_value)
        self._inputs["set"].setText(shared_pack_id)
        self._pack_inputs["pack_id"].setText(shared_pack_id)
        self._last_shared_pack_id = shared_pack_id
        self._update_pack_description_placeholder(shared_pack_id)
        self._resetting_source = False
        self._refresh_packlist_state()


# ─── 主窗口 ───────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._migration_report = prepare_runtime_data()
        self._cfg    = load_config()
        self._rows: list[SegmentRow] = []
        self._worker: SlicerWorker | None = None
        self._external_merge_worker: ExternalMergeWorker | None = None
        self._external_merge_target: Path | None = None
        self._external_merge_plan: external_merge.ExternalMergePlan | None = None
        self._external_merge_phase = "idle"
        self._external_merge_generation = 0
        self._external_merge_restore_message = ""
        self._slicer_running = False
        self._current_export_dirty = True
        self._last_run_current_export_enabled = True
        self._current_source_id = ""
        self._suppress_source_reset = False
        self._uid    = 0
        self._arc_warning_timer = QTimer(self)
        self._arc_warning_timer.setSingleShot(True)
        self._arc_warning_timer.timeout.connect(self._refresh_arc_cut_warnings)
        self._segment_validation_timer = QTimer(self)
        self._segment_validation_timer.setSingleShot(True)
        self._segment_validation_timer.timeout.connect(self._refresh_segment_time_validation)
        self._audio_duration_ms: int | None = None
        self._audio_duration_error = ""

        self.setWindowTitle("Arc Slicer")
        self.setMinimumSize(620, 580)
        self.resize(760, 900)
        self.setAcceptDrops(True)

        self._setup_ui()
        self._restore_external_merge_target_from_config()
        if self._migration_report.has_activity():
            self._push_log(self._migration_report.message(), "muted")
        self._suppress_source_reset = True
        try:
            self._load_initial_data()
        finally:
            self._suppress_source_reset = False
            self._current_source_id = self._song_box.currentText()
        if self._current_export_dirty:
            self._invalidate_external_merge_plan()

    # ── UI 构建 ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("root")
        central.setAutoFillBackground(True)
        _pal = central.palette()
        _pal.setColor(QPalette.ColorRole.Window, QColor(C_BG))
        central.setPalette(_pal)
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self._scroll)

        content = QWidget()
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setStyleSheet(f"QWidget {{ background: {C_BG}; }}")
        self._scroll.setWidget(content)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(0)

        # ── 标题
        h1 = make_label("准备切片", size=22, weight=600)
        h1.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(h1)

        sub = make_label("选择曲目，标记想保留的时间段，然后运行切片器。", size=13, color=C_MUTED)
        sub.setContentsMargins(0, 0, 0, 20)
        lay.addWidget(sub)

        # ── songs 目录行
        dir_frame = QFrame()
        dir_frame.setStyleSheet(
            f"QFrame {{ background: {C_CARD2}; border: 1px solid {C_BORDER2}; border-radius: 12px; }}"
        )
        dir_lay = QHBoxLayout(dir_frame)
        dir_lay.setContentsMargins(14, 10, 14, 10)
        dir_lay.setSpacing(10)
        dir_lbl = field_label("SONGS 目录")
        dir_lbl.setStyleSheet(f"font-size: 11px; font-weight: 600; letter-spacing: 1px; color: {C_LABEL}; background: transparent; border: none;")
        dir_lay.addWidget(dir_lbl)
        self._dir_path = QLabel()
        self._dir_path.setStyleSheet(
            f"font-family: 'Consolas','Courier New',monospace; font-size: 12px; "
            f"color: {C_TEXT2}; background: transparent; border: none;"
        )
        self._dir_path.setMinimumWidth(80)
        dir_lay.addWidget(self._dir_path, 1)
        btn_dir = QPushButton("更改")
        btn_dir.setObjectName("btnDir")
        btn_dir.clicked.connect(self._browse_songs_dir)
        dir_lay.addWidget(btn_dir)
        dir_frame.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(dir_frame)
        lay.addSpacing(12)

        # ── 拖放区
        self._drop_zone = DropZone()
        self._drop_zone.folder_dropped.connect(self._add_song_folder)
        self._drop_zone.invalid_dropped.connect(lambda msg: self._push_log(f"✗ {msg}", "err"))
        lay.addWidget(self._drop_zone)
        lay.addSpacing(18)

        # ── 曲目 + 速度 topbar
        topbar = QFrame()
        topbar.setStyleSheet(
            f"QFrame {{ background: {C_CARD2}; border: 1px solid {C_BORDER2}; border-radius: 14px; }}"
        )
        tb_lay = QHBoxLayout(topbar)
        tb_lay.setContentsMargins(13, 13, 13, 13)
        tb_lay.setSpacing(12)

        song_col = QVBoxLayout()
        song_col.setSpacing(7)
        song_col.addWidget(field_label("曲目 SONG ID"))
        self._song_box = QComboBox()
        self._song_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._song_box.currentTextChanged.connect(self._on_song_changed)
        song_col.addWidget(self._song_box)
        tb_lay.addLayout(song_col, 1)

        speed_col = QVBoxLayout()
        speed_col.setSpacing(7)
        speed_col.addWidget(field_label("速度 SPEED"))
        self._speed_input = QLineEdit("1.0")
        self._speed_input.setFixedWidth(124)
        self._speed_input.textChanged.connect(self._mark_current_export_dirty)
        speed_col.addWidget(self._speed_input)
        tb_lay.addLayout(speed_col)

        lay.addWidget(topbar)
        lay.addSpacing(22)

        # ── 段落标题
        seg_head = QHBoxLayout()
        seg_head.setContentsMargins(0, 0, 0, 12)
        self._seg_header = make_label("时间段 · 0 段 · 共 0.0s", size=13, weight=700, color=C_TEXT2)
        seg_head.addWidget(self._seg_header)
        seg_head.addStretch()
        self._audio_duration_label = make_label("音频时长：—", size=12, color=C_LABEL)
        seg_head.addWidget(self._audio_duration_label)
        seg_head.addSpacing(14)
        seg_head.addWidget(make_label("毫秒 · 对应 .aff 整数时间", size=12, color=C_LABEL))
        lay.addLayout(seg_head)

        # ── 段落列表
        self._segs_widget = QWidget()
        self._segs_widget.setStyleSheet("background: transparent;")
        self._segs_layout = QVBoxLayout(self._segs_widget)
        self._segs_layout.setContentsMargins(0, 0, 0, 0)
        self._segs_layout.setSpacing(11)
        lay.addWidget(self._segs_widget)
        lay.addSpacing(10)

        # ── 添加按钮
        btn_add = QPushButton("＋ 添加时间段")
        btn_add.setObjectName("btnAdd")
        btn_add.clicked.connect(lambda: self._add_segment())
        lay.addWidget(btn_add)
        lay.addSpacing(20)

        # ── Songlist 配置面板
        self._songlist_panel = SonglistPanel()
        self._songlist_panel.enabled_changed.connect(self._refresh_export_target_state)
        self._songlist_panel.enabled_changed.connect(self._mark_current_export_dirty)
        self._songlist_panel.metadata_changed.connect(self._mark_current_export_dirty)
        lay.addWidget(self._songlist_panel)
        lay.addSpacing(16)

        # ── 导出目标
        lay.addWidget(section_title("导出目标", "EXPORT TARGETS"))
        target_frame = QFrame()
        target_frame.setStyleSheet(
            f"QFrame {{ background: #F4EEE3; border: 1px solid #DED4C5; border-radius: 12px; }}"
        )
        target_lay = QVBoxLayout(target_frame)
        target_lay.setContentsMargins(14, 10, 14, 10)
        target_lay.setSpacing(7)
        target_row = QHBoxLayout()
        target_row.setSpacing(18)
        self._current_export_check = QCheckBox("生成本次导出包")
        self._current_export_check.setChecked(True)
        self._library_export_check = QCheckBox("更新总导出包")
        self._library_export_check.setChecked(True)
        self._current_export_check.clicked.connect(self._mark_current_export_dirty)
        self._library_export_check.clicked.connect(self._mark_current_export_dirty)
        for box in (self._current_export_check, self._library_export_check):
            box.setStyleSheet(
                f"color: {C_TEXT2}; font-size: 13px; background: transparent; border: none;"
            )
        target_row.addWidget(self._current_export_check)
        target_row.addWidget(self._library_export_check)
        target_row.addStretch()
        target_lay.addLayout(target_row)
        self._library_export_note = make_label("需启用 songlist 后才能更新总导出包。", size=12, color=C_LABEL)
        target_lay.addWidget(self._library_export_note)
        lay.addWidget(target_frame)
        lay.addSpacing(16)

        # ── 外部目标壳合并
        # 外部目标壳合并 EXTERNAL MERGE
        lay.addWidget(section_title("外部目标壳合并", "EXTERNAL MERGE"))
        external_frame = QFrame()
        external_frame.setStyleSheet(
            f"QFrame {{ background: #F4EEE3; border: 1px solid #DED4C5; border-radius: 12px; }}"
        )
        external_lay = QVBoxLayout(external_frame)
        external_lay.setContentsMargins(14, 11, 14, 11)
        external_lay.setSpacing(8)

        external_target_row = QHBoxLayout()
        external_target_row.setSpacing(10)
        external_target_row.addWidget(make_label("目标壳 songs 目录", size=12, color=C_LABEL))
        self._external_merge_target_label = QLabel("未选择")
        self._external_merge_target_label.setStyleSheet(
            f"font-family: 'Consolas','Courier New',monospace; font-size: 12px; "
            f"color: {C_TEXT2}; background: transparent; border: none;"
        )
        self._external_merge_target_label.setMinimumWidth(80)
        external_target_row.addWidget(self._external_merge_target_label, 1)
        self._btn_external_choose = QPushButton("选择")
        self._btn_external_choose.setObjectName("btnDir")
        self._btn_external_choose.clicked.connect(self._browse_external_merge_target)
        external_target_row.addWidget(self._btn_external_choose)
        external_lay.addLayout(external_target_row)

        external_actions = QHBoxLayout()
        external_actions.setSpacing(10)
        self._btn_external_check = QPushButton("检查合并计划")
        self._btn_external_check.setObjectName("btnSec")
        self._btn_external_check.clicked.connect(self._check_external_merge_plan)
        external_actions.addWidget(self._btn_external_check)
        self._btn_external_confirm = QPushButton("确认合并")
        self._btn_external_confirm.setObjectName("btnSec")
        self._btn_external_confirm.clicked.connect(self._confirm_external_merge)
        external_actions.addWidget(self._btn_external_confirm)
        external_actions.addStretch()
        external_lay.addLayout(external_actions)

        self._external_merge_status_label = make_label("外部目标壳合并：未检查", size=13, weight=700, color=C_TEXT2)
        external_lay.addWidget(self._external_merge_status_label)
        self._external_merge_detail_label = QLabel()
        self._external_merge_detail_label.setWordWrap(True)
        self._external_merge_detail_label.setStyleSheet(
            f"font-size: 12px; color: {C_MUTED}; background: transparent; border: none; line-height: 1.35;"
        )
        external_lay.addWidget(self._external_merge_detail_label)

        lay.addWidget(external_frame)
        lay.addSpacing(16)

        # ── 操作行
        action_frame = QFrame()
        action_frame.setStyleSheet(
            f"QFrame {{ background: #F4EEE3; border: 1px solid #DED4C5; border-radius: 12px; }}"
        )
        actions = QHBoxLayout(action_frame)
        actions.setContentsMargins(12, 10, 12, 10)
        actions.setSpacing(10)
        self._btn_run = QPushButton("▶  运行切片")
        self._btn_run.setObjectName("btnRun")
        self._btn_run.clicked.connect(self._run_slicer)
        actions.addWidget(self._btn_run)

        btn_save = QPushButton("保存")
        btn_save.setObjectName("btnSec")
        btn_save.clicked.connect(self._save_slides)
        actions.addWidget(btn_save)

        btn_open = QPushButton("打开输出")
        btn_open.setObjectName("btnSec")
        btn_open.clicked.connect(self._open_out)
        actions.addWidget(btn_open)

        self._saved_lbl = make_label("✓ 已保存", size=13, weight=600, color=C_OK)
        self._saved_lbl.hide()
        actions.addWidget(self._saved_lbl)
        actions.addStretch()
        lay.addWidget(action_frame)
        lay.addSpacing(16)

        # ── 日志
        self._log_widget = QTextEdit()
        self._log_widget.setObjectName("log")
        self._log_widget.setReadOnly(True)
        self._log_widget.setMinimumHeight(180)
        self._log_widget.setMaximumHeight(260)
        self._log_widget.hide()
        lay.addWidget(self._log_widget)

        lay.addStretch()

        # 更新目录显示
        self._refresh_dir_label()
        self._refresh_export_target_state()
        self._update_external_merge_controls()

    # ── 初始数据 ──────────────────────────────────────────────────────────────

    def _load_initial_data(self):
        songs = self._get_songs()
        self._populate_songs(songs)

        if SLIDES_PATH.exists():
            try:
                data = json.loads(SLIDES_PATH.read_text(encoding="utf-8"))
                self._apply_slides(data)
                return
            except Exception:
                pass
        self._add_segment(None, None)

    def _get_songs(self) -> list[str]:
        d = Path(self._cfg.get("songs_dir", ""))
        if not d.is_dir():
            return []
        return sorted(item for item in os.listdir(d) if is_sliceable_song_dir(d / item))

    def _populate_songs(self, songs: list[str]):
        current = self._song_box.currentText()
        self._song_box.clear()
        if not songs:
            self._song_box.addItem("（songs 目录为空）")
            self._refresh_current_audio_duration()
            self._schedule_arc_cut_warning_refresh()
            return
        for s in songs:
            self._song_box.addItem(s)
        if current in songs:
            self._song_box.setCurrentText(current)
        self._refresh_current_audio_duration()
        self._schedule_arc_cut_warning_refresh()

    def _apply_slides(self, data: dict):
        if data.get("speed") is not None:
            self._speed_input.setText(str(data["speed"]))
        if data.get("song_id"):
            idx = self._song_box.findText(data["song_id"])
            if idx >= 0:
                self._song_box.setCurrentIndex(idx)
        added_segment = False
        for seg in data.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            try:
                s, e = int(seg["s"]), int(seg["e"])
            except (KeyError, TypeError, ValueError):
                continue
            self._add_segment(s, e)
            added_segment = True
        if not added_segment:
            self._add_segment(None, None)
        if hasattr(self._songlist_panel, "set_songlist_enabled"):
            self._songlist_panel.set_songlist_enabled(bool(data.get("songlist_enabled", False)))
        if hasattr(self._songlist_panel, "set_packlist_enabled"):
            self._songlist_panel.set_packlist_enabled(_bool_pref(data.get("packlist_enabled"), False))
        if data.get("songlist"):
            self._songlist_panel.set_meta(data["songlist"])
        if hasattr(self._songlist_panel, "update_pack_defaults"):
            self._songlist_panel.update_pack_defaults(self._song_box.currentText())
        if hasattr(self, "_current_export_check"):
            self._current_export_check.setChecked(_bool_pref(data.get("current_export_enabled"), True))
        if hasattr(self, "_library_export_check"):
            self._library_export_check.setChecked(_bool_pref(data.get("library_export_enabled"), True))
            self._refresh_export_target_state()
        self._refresh_current_audio_duration()
        self._schedule_arc_cut_warning_refresh()

    # ── 目录操作 ──────────────────────────────────────────────────────────────

    def _refresh_dir_label(self):
        p = self._cfg.get("songs_dir", "")
        self._dir_path.setText(p)
        self._dir_path.setToolTip(p)

    def _refresh_export_target_state(self):
        songlist_enabled = (
            self._songlist_panel.is_songlist_enabled()
            if hasattr(self._songlist_panel, "is_songlist_enabled")
            else False
        )
        self._library_export_check.setEnabled(bool(songlist_enabled))
        self._library_export_note.setVisible(not songlist_enabled)
        if hasattr(self._songlist_panel, "_refresh_packlist_state"):
            self._songlist_panel._refresh_packlist_state()

    def _on_song_changed(self, song_id: str):
        song_id = str(song_id or "").strip()
        if getattr(self, "_suppress_source_reset", False):
            return
        if song_id == self._current_source_id:
            self._refresh_current_audio_duration()
            self._schedule_arc_cut_warning_refresh()
            return
        self._current_source_id = song_id
        if hasattr(self._songlist_panel, "reset_for_source"):
            self._songlist_panel.reset_for_source(song_id)
        self._clear_segments()
        self._add_segment(None, None)
        self._refresh_current_audio_duration()
        self._schedule_arc_cut_warning_refresh()
        self._mark_current_export_dirty()

    def _mark_current_export_dirty(self, *_args):
        if getattr(self, "_suppress_source_reset", False):
            return
        self._current_export_dirty = True
        self._invalidate_external_merge_plan("当前配置尚未导出，请先运行切片。")

    def _slicer_is_running(self) -> bool:
        return bool(self.__dict__.get("_slicer_running", False))

    def _external_merge_is_busy(self) -> bool:
        return self.__dict__.get("_external_merge_phase", "idle") in {"checking", "executing"}

    def _set_external_merge_view(self, view: dict) -> None:
        if hasattr(self, "_external_merge_status_label"):
            self._external_merge_status_label.setText(view.get("title", "外部目标壳合并"))
            status_color = C_ACCENT if view.get("state") == "dirty" else C_TEXT2
            self._external_merge_status_label.setStyleSheet(
                f"font-size: 13px; font-weight: 700; color: {status_color}; background: transparent;"
            )
        if hasattr(self, "_external_merge_detail_label"):
            self._external_merge_detail_label.setText(view.get("detail", ""))
            self._external_merge_detail_label.setVisible(bool(view.get("detail")))
            if view.get("state") == "dirty":
                self._external_merge_detail_label.setStyleSheet(
                    "font-size: 12px; color: #6B4A2A; background: #FFF4E6; "
                    "border: 1px solid #E5C79D; border-radius: 8px; padding: 8px;"
                )
            else:
                self._external_merge_detail_label.setStyleSheet(
                    f"font-size: 12px; color: {C_MUTED}; background: transparent; border: none;"
                )
        self._update_external_merge_controls()

    def _update_external_merge_controls(self) -> None:
        if not hasattr(self, "_btn_external_check"):
            return
        busy = self._external_merge_is_busy()
        slicing = self._slicer_is_running()
        dirty = bool(getattr(self, "_current_export_dirty", False))
        if hasattr(self, "_btn_run"):
            self._btn_run.setEnabled(not busy and not slicing)
        self._btn_external_choose.setEnabled(not busy and not slicing)
        self._btn_external_check.setEnabled(
            external_merge_can_check(self._external_merge_target, busy=busy, slicing=slicing) and not dirty
        )
        self._btn_external_confirm.setEnabled(
            external_merge_can_confirm(self._external_merge_plan, busy=busy) and not slicing and not dirty
        )

    def _set_external_merge_target_path(self, path: Path | str) -> None:
        path = Path(path)
        self._external_merge_target = path
        if hasattr(self, "_external_merge_target_label"):
            text = str(path)
            self._external_merge_target_label.setText(text)
            self._external_merge_target_label.setToolTip(text)

    def _restore_external_merge_target_from_config(self) -> None:
        target, message = _external_merge_target_status(
            self._cfg.get(EXTERNAL_MERGE_TARGET_CONFIG_KEY)
        )
        self._external_merge_plan = None
        if target is not None:
            self._set_external_merge_target_path(target)
            self._external_merge_restore_message = "已恢复上次目标目录，请检查合并计划。"
            self._invalidate_external_merge_plan(self._external_merge_restore_message)
            return
        if EXTERNAL_MERGE_TARGET_CONFIG_KEY in self._cfg:
            self._external_merge_restore_message = message
            self._invalidate_external_merge_plan(message)

    def _invalidate_external_merge_plan(self, message: str = "") -> None:
        self._external_merge_plan = None
        if bool(getattr(self, "_current_export_dirty", False)):
            self._set_external_merge_view(
                external_merge_dirty_view_model(
                    self._external_merge_target,
                    backup_root=EXTERNAL_MERGE_BACKUP_ROOT,
                )
            )
            return
        view = external_merge_plan_view_model(
            None,
            target_songs_dir=self._external_merge_target,
            backup_root=EXTERNAL_MERGE_BACKUP_ROOT,
        )
        if not message and self._external_merge_restore_message:
            message = self._external_merge_restore_message
        if message:
            view["detail"] = view["detail"] + "\n" + message
        self._set_external_merge_view(view)

    def _browse_external_merge_target(self) -> None:
        if self._external_merge_is_busy() or self._slicer_is_running():
            return
        start = str(self._external_merge_target or DATA_ROOT)
        path = QFileDialog.getExistingDirectory(self, "选择目标壳 songs 目录", start)
        if not path:
            return
        target, message = _external_merge_target_status(path)
        if target is None:
            self._invalidate_external_merge_plan(message)
            return
        self._external_merge_restore_message = ""
        self._set_external_merge_target_path(target)
        self._cfg[EXTERNAL_MERGE_TARGET_CONFIG_KEY] = str(target)
        save_config(self._cfg)
        self._invalidate_external_merge_plan("目标路径已变更，请重新检查合并计划。")

    def _check_external_merge_plan(self) -> None:
        if self._external_merge_is_busy() or self._slicer_is_running():
            return
        if not external_merge_can_check(
            self._external_merge_target,
            busy=self._external_merge_is_busy(),
            slicing=self._slicer_is_running(),
        ):
            return
        self._external_merge_generation += 1
        generation = self._external_merge_generation
        self._external_merge_phase = "checking"
        self._external_merge_plan = None
        self._external_merge_status_label.setText("外部目标壳合并：检查中")
        self._external_merge_detail_label.setText("正在读取 current_export/songs 与目标壳 songs 目录；此步骤不会写入目标。")
        self._external_merge_detail_label.show()
        self._update_external_merge_controls()
        self._external_merge_worker = ExternalMergeWorker(
            "check",
            generation,
            CURRENT_EXPORT_SONGS_DIR,
            self._external_merge_target,
            EXTERNAL_MERGE_BACKUP_ROOT,
        )
        self._external_merge_worker.done_signal.connect(self._on_external_merge_done)
        self._external_merge_worker.start()

    def _confirm_external_merge(self) -> None:
        if self._external_merge_is_busy() or self._slicer_is_running():
            return
        if not external_merge_can_confirm(self._external_merge_plan, busy=self._external_merge_is_busy()):
            return
        from PyQt6.QtWidgets import QMessageBox

        text = external_merge_confirmation_text(self._external_merge_plan, EXTERNAL_MERGE_BACKUP_ROOT)
        answer = QMessageBox.question(
            self,
            "确认合并到外部目标壳",
            text,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        self._external_merge_generation += 1
        generation = self._external_merge_generation
        self._external_merge_phase = "executing"
        self._external_merge_status_label.setText("外部目标壳合并：执行中")
        self._external_merge_detail_label.setText("正在备份受影响项目并执行合并。")
        self._external_merge_detail_label.show()
        self._update_external_merge_controls()
        self._external_merge_worker = ExternalMergeWorker(
            "execute",
            generation,
            CURRENT_EXPORT_SONGS_DIR,
            self._external_merge_target or Path(),
            EXTERNAL_MERGE_BACKUP_ROOT,
            self._external_merge_plan,
        )
        self._external_merge_worker.done_signal.connect(self._on_external_merge_done)
        self._external_merge_worker.start()

    def _on_external_merge_done(self, mode: str, generation: int, payload: object, error: str) -> None:
        if generation != self._external_merge_generation:
            return
        self._external_merge_phase = "idle"
        self._external_merge_worker = None
        if error:
            self._external_merge_plan = None
            self._set_external_merge_view({
                "title": "外部目标壳合并：失败",
                "detail": f"{mode} 失败: {error}",
                "can_confirm": False,
            })
            label = "检查失败" if mode == "check" else "执行失败"
            self._push_log(f"[外部合并] {label}：{error}", "err")
            return

        if mode == "check":
            self._external_merge_plan = payload
            self._set_external_merge_view(
                external_merge_plan_view_model(
                    self._external_merge_plan,
                    backup_root=EXTERNAL_MERGE_BACKUP_ROOT,
                )
            )
            return

        result = payload
        self._external_merge_plan = None
        self._set_external_merge_view(external_merge_result_view_model(result))
        text, kind = external_merge_log_line(result)
        self._push_log(text, kind)

    def _browse_songs_dir(self):
        d = self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR))
        path = QFileDialog.getExistingDirectory(self, "选择 songs 根目录", d)
        if path:
            self._cfg["songs_dir"] = path
            save_config(self._cfg)
            self._refresh_dir_label()
            self._populate_songs(self._get_songs())
            self._refresh_current_audio_duration()
            self._schedule_arc_cut_warning_refresh()
            self._push_log(f"✓ songs 目录 → {path}", "ok")

    def _add_song_folder(self, src_path: str):
        src = Path(src_path)
        songs_dir = Path(self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR)))

        ok, msg, song_id = import_song_folder(src, songs_dir)
        if ok and song_id == src.name and (songs_dir / src.name).resolve() == src.resolve():
            self._push_log(f"  {msg}", "muted")
        elif ok and song_id == src.name and (songs_dir / src.name).exists():
            self._push_log(f"✓ {msg}", "ok")
        else:
            self._push_log(f"✗ {msg}", "err")
            return

        self._populate_songs(self._get_songs())
        idx = self._song_box.findText(song_id or src.name)
        if idx >= 0:
            self._song_box.setCurrentIndex(idx)
        self._clear_segments()
        self._add_segment(None, None)
        self._refresh_current_audio_duration()
        self._schedule_arc_cut_warning_refresh()

    # ── 段落管理 ──────────────────────────────────────────────────────────────

    def _clear_segments(self):
        while self._rows:
            row = self._rows.pop()
            self._segs_layout.removeWidget(row)
            row.deleteLater()

    def _add_segment(self, s=_AUTO_SEGMENT, e=_AUTO_SEGMENT):
        if s is _AUTO_SEGMENT and e is _AUTO_SEGMENT:
            s = None
            e = None
        elif s is _AUTO_SEGMENT or e is _AUTO_SEGMENT:
            raise ValueError("s and e must be provided together")

        row = SegmentRow(len(self._rows) + 1, s, e)
        row.deleted.connect(self._remove_segment)
        row.changed.connect(self._refresh_seg_header)
        row.changed.connect(self._schedule_arc_cut_warning_refresh)
        row.changed.connect(self._schedule_segment_time_validation)
        row.changed.connect(self._mark_current_export_dirty)
        row.end_cap_requested.connect(self._set_row_end_to_audio_duration)
        self._rows.append(row)
        self._segs_layout.addWidget(row)
        self._refresh_seg_header()
        self._schedule_segment_time_validation()
        self._schedule_arc_cut_warning_refresh()

    def _remove_segment(self, row: SegmentRow):
        self._rows.remove(row)
        self._segs_layout.removeWidget(row)
        row.deleteLater()
        for i, r in enumerate(self._rows):
            r.update_index(i + 1)
        if not self._rows:
            self._add_segment(None, None)
            return
        self._refresh_seg_header()
        self._schedule_segment_time_validation()
        self._schedule_arc_cut_warning_refresh()
        self._mark_current_export_dirty()

    def _refresh_seg_header(self):
        total = 0
        for r in self._rows:
            if r.s_val is not None and r.e_val is not None:
                d = r.e_val - r.s_val
                if d > 0:
                    total += d
        self._seg_header.setText(
            f"时间段 · {len(self._rows)} 段 · 共 {total/1000:.1f}s"
        )

    def _schedule_arc_cut_warning_refresh(self):
        self._arc_warning_timer.start(200)

    def _schedule_segment_time_validation(self):
        self._segment_validation_timer.start(120)

    def _current_audio_path(self) -> Path | None:
        song_id = self._song_box.currentText()
        if not isinstance(song_id, str) or not song_id or "目录为空" in song_id:
            return None
        cfg = getattr(self, "_cfg", {})
        raw_songs_dir = cfg.get("songs_dir", str(DEFAULT_SONGS_DIR)) if isinstance(cfg, dict) else str(DEFAULT_SONGS_DIR)
        if not isinstance(raw_songs_dir, (str, os.PathLike)):
            return None
        songs_dir = Path(raw_songs_dir)
        return songs_dir / song_id / "base.ogg"

    def _refresh_current_audio_duration(self):
        audio_path = self._current_audio_path()
        if audio_path is None or not audio_path.is_file():
            self._audio_duration_ms = None
            self._audio_duration_error = ""
            if hasattr(self, "_audio_duration_label"):
                self._audio_duration_label.setText("音频时长：—")
                self._audio_duration_label.setToolTip("")
            self._refresh_segment_time_validation()
            return

        try:
            self._audio_duration_ms = probe_audio_duration_ms(audio_path)
            self._audio_duration_error = ""
            text = f"音频时长：{format_duration_ms(self._audio_duration_ms)}（终点上限：{self._audio_duration_ms} ms）"
            self._audio_duration_label.setText(text)
            self._audio_duration_label.setToolTip(str(audio_path))
        except Exception as ex:
            self._audio_duration_ms = None
            self._audio_duration_error = str(ex)
            self._audio_duration_label.setText("音频时长：无法读取")
            self._audio_duration_label.setToolTip(str(ex))
            self._push_log(f"⚠ 无法读取当前曲目的音频时长: {ex}", "muted")
        self._refresh_segment_time_validation()

    def _refresh_segment_time_validation(self):
        duration_ms = self._audio_duration_ms
        for row in self._rows:
            if not row.start_text() and not row.end_text():
                row.clear_time_errors()
                continue
            result = validate_segment_bounds(row.start_text(), row.end_text(), duration_ms)
            row.set_time_errors(result.start_error, result.end_error, result.end_cap_ms)

    def _first_segment_validation_error(self) -> tuple[int, SegmentRow, SegmentValidationResult] | None:
        duration_ms = self._audio_duration_ms
        for index, row in enumerate(self._rows):
            result = validate_segment_bounds(row.start_text(), row.end_text(), duration_ms)
            row.set_time_errors(result.start_error, result.end_error, result.end_cap_ms)
            if not result.ok:
                return index, row, result
        return None

    def _set_row_end_to_audio_duration(self, row: SegmentRow):
        if self._audio_duration_ms is None:
            return
        row.set_end_text(self._audio_duration_ms)
        self._refresh_seg_header()
        self._refresh_segment_time_validation()
        self._schedule_arc_cut_warning_refresh()

    def _show_segment_validation_error(self, index: int, row: SegmentRow, result: SegmentValidationResult):
        title = "时间段无效"
        message = f"第 {index + 1} 个时间段：{result.first_message}"
        try:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(self, title, message)
        except Exception:
            self._push_log(f"✗ {message}", "err")
        try:
            self._scroll.ensureWidgetVisible(row)
        except Exception:
            pass
        row.focus_time_field(result.first_field)

    def _clear_arc_cut_warnings(self):
        for row in self._rows:
            row.set_arc_cut_warnings([], [])

    def _refresh_arc_cut_warnings(self):
        try:
            song_id = self._song_box.currentText()
            songs_dir = Path(self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR)))
            aff_path = songs_dir / song_id / "2.aff"
            if not song_id or not aff_path.is_file():
                self._clear_arc_cut_warnings()
                return

            segment_rows: list[SegmentRow] = []
            segments: list[dict] = []
            for row in self._rows:
                if row.s_val is None or row.e_val is None or row.e_val <= row.s_val:
                    row.set_arc_cut_warnings([], [])
                    continue
                segment_rows.append(row)
                segments.append({"s": row.s_val, "e": row.e_val})

            if not segments:
                self._clear_arc_cut_warnings()
                return

            aff_text = aff_path.read_text(encoding="utf-8", errors="replace")
            warnings = find_nonlinear_arc_cut_warnings(aff_text, segments)
            for index, row in enumerate(segment_rows):
                hits = warnings.get(index, {"start": [], "end": []})
                row.set_arc_cut_warnings(hits["start"], hits["end"])
        except Exception:
            self._clear_arc_cut_warnings()

    def _collect(self, speed: float | None = None) -> dict:
        songlist_enabled = (
            bool(self._songlist_panel.is_songlist_enabled())
            if hasattr(self._songlist_panel, "is_songlist_enabled")
            else False
        )
        packlist_enabled = (
            bool(self._songlist_panel.is_packlist_enabled())
            if hasattr(self._songlist_panel, "is_packlist_enabled")
            else False
        )
        if hasattr(self._songlist_panel, "get_form_data"):
            songlist_form = self._songlist_panel.get_form_data()
        else:
            songlist_form = self._songlist_panel.get_meta() or {}
        current_export_enabled = (
            bool(self._current_export_check.isChecked())
            if hasattr(self, "_current_export_check")
            else True
        )
        library_export_enabled = (
            bool(self._library_export_check.isChecked())
            if hasattr(self, "_library_export_check")
            else True
        )
        data: dict = {
            "song_id":  self._song_box.currentText(),
            "speed":    parse_speed_text(self._speed_input.text()) if speed is None else speed,
            "segments": [r.to_dict() for r in self._rows if r.to_dict()],
            "songlist_enabled": songlist_enabled,
            "packlist_enabled": packlist_enabled,
            "current_export_enabled": current_export_enabled,
            "library_export_enabled": library_export_enabled,
            "songlist": songlist_form,
        }
        return data

    # ── 保存 / 运行 / 打开 ────────────────────────────────────────────────────

    def _save_slides(self):
        try:
            data = self._collect()
            SLIDES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self._push_log(f"💾 已保存 → {SLIDES_PATH}", "ok")
            self._saved_lbl.show()
            QTimer.singleShot(1900, self._saved_lbl.hide)
        except ValueError as ex:
            self._push_log(f"✗ 保存失败：速度无效: {ex}", "err")
        except Exception as ex:
            self._push_log(f"✗ 保存失败: {ex}", "err")

    def _run_slicer(self):
        if self._slicer_is_running():
            return
        if self._external_merge_is_busy():
            return
        try:
            speed = parse_speed_text(self._speed_input.text())
        except ValueError as ex:
            self._push_log(f"✗ 速度无效: {ex}", "err")
            return
        song_id = self._song_box.currentText()
        if not isinstance(song_id, str) or not song_id or "目录为空" in song_id:
            self._push_log("✗ 请先选择曲目 Song ID", "err")
            return
        self._refresh_current_audio_duration()
        segment_error = self._first_segment_validation_error()
        if segment_error:
            self._show_segment_validation_error(*segment_error)
            return
        data = self._collect(speed)
        self._last_run_current_export_enabled = bool(data.get("current_export_enabled", True))
        if not data["song_id"] or "目录为空" in data["song_id"]:
            self._push_log("✗ 请先选择曲目 Song ID", "err")
            return
        if not data["segments"]:
            self._push_log("✗ 至少需要一个时间段", "err")
            return
        songlist_template = None
        packlist_template = None
        if data.get("songlist_enabled"):
            try:
                songlist_template = song_template_from_form(data.get("songlist") or {})
            except ValueError as ex:
                self._push_log(f"✗ Songlist 信息无效: {ex}", "err")
                return
            if data.get("packlist_enabled"):
                try:
                    packlist_template = pack_template_from_form(data.get("songlist") or {}, data["song_id"])
                    songlist_template = replace(songlist_template, set=packlist_template.pack_id)
                except ValueError as ex:
                    self._push_log(f"✗ Packlist 信息无效: {ex}", "err")
                    return
        effective_library = effective_library_export_enabled(
            bool(data.get("library_export_enabled", True)),
            bool(data.get("songlist_enabled", False)),
        )
        if not data.get("current_export_enabled", True) and not effective_library:
            self._push_log("✗ 至少需要选择一个有效导出目标", "err")
            return

        self._save_slides()
        self._log_widget.clear()
        self._log_widget.show()
        self._set_running(True)
        self._push_log("▶ 开始切片…", "stage")

        songs_dir     = Path(self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR)))
        songlist_meta = data.get("songlist") or {}
        self._worker = SlicerWorker(
            songs_dir, data["song_id"], data["segments"], data["speed"],
            songlist_meta, bool(data.get("songlist_enabled")), songlist_template,
            bool(data.get("current_export_enabled", True)),
            bool(data.get("library_export_enabled", True)),
            bool(data.get("packlist_enabled", False)),
            packlist_template,
        )
        self._worker.log_signal.connect(self._push_log)
        self._worker.done_signal.connect(self._on_done)
        self._worker.start()

    def _on_done(self, code: int):
        self._set_running(False)
        if code == 0:
            if getattr(self, "_last_run_current_export_enabled", True):
                self._current_export_dirty = False
                self._invalidate_external_merge_plan("current_export 已更新，请重新检查外部合并计划。")
            else:
                self._mark_current_export_dirty()

    def _set_running(self, on: bool):
        self._slicer_running = bool(on)
        self._btn_run.setEnabled(not on)
        self._btn_run.setText("▶  运行中…" if on else "▶  运行切片")
        self._update_external_merge_controls()

    def _open_out(self):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(OUT_DIR)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(OUT_DIR)])
            else:
                subprocess.run(["xdg-open", str(OUT_DIR)])
        except Exception as ex:
            self._push_log(f"✗ 无法打开目录: {ex}", "err")

    # ── 日志输出 ──────────────────────────────────────────────────────────────

    LOG_COLORS = {
        "ok":     "#BDE0A8",
        "err":    "#F0A08D",
        "warn":   "#E6B36A",
        "stage":  "#F0E7D8",
        "muted":  "#B9B0A2",
        "normal": "#DED5C7",
    }
    LOG_WEIGHTS = {
        "ok": "700",
        "err": "700",
        "warn": "700",
        "stage": "650",
    }

    def _push_log(self, text: str, kind: str = "normal"):
        self._log_widget.show()
        color = self.LOG_COLORS.get(kind, self.LOG_COLORS["normal"])
        # Use HTML for colored lines
        import html as _html
        escaped = _html.escape(text)
        weight = self.LOG_WEIGHTS.get(kind, "400")
        self._log_widget.append(f'<span style="color:{color}; font-weight:{weight};">{escaped}</span>')
        self._log_widget.moveCursor(QTextCursor.MoveOperation.End)

    # ── 窗口级拖放（从 Explorer 直接拖到窗口任意位置）─────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self._add_song_folder(path)
                break
            if path:
                self._push_log("✗ 请拖入歌曲文件夹，而不是单个文件。", "err")
                break


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Arc Slicer")
    app.setStyleSheet(QSS)

    # 设置全局调色板背景
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C_TEXT))
    app.setPalette(palette)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
