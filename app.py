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
from dataclasses import dataclass, field
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


# ─── songlist ─────────────────────────────────────────────────────────────────

def make_songlist_fragment(new_id: str, start_ms: int, end_ms: int, speed: float) -> dict | None:
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
            "difficulties": [{
                "ratingClass": 2,
                "chartDesigner": meta["chart_designer"],
                "jacketDesigner": meta["jacket_designer"],
                "rating": int(meta["rating"]),
                "ratingPlus": bool(meta["rating_plus"]),
            }],
        }]
    }


def do_slice(
    songs_dir: Path,
    song_id: str,
    segments: list[dict],
    speed: float,
    log_fn,
    songlist_meta: dict | None = None,
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

    in_dir = songs_dir / song_id
    in_aff, in_ogg, in_jpg = in_dir / "2.aff", in_dir / "base.ogg", in_dir / "base.jpg"

    for p in (in_aff, in_ogg):
        if not p.exists():
            log_fn(f"✗ 找不到文件: {p}", "err")
            return 1

    out_root = OUT_DIR / "songs"
    out_root.mkdir(parents=True, exist_ok=True)
    all_song_entries: list[dict] = []

    for i, seg in enumerate(segments):
        s, e = int(seg["s"]), int(seg["e"])
        if e <= s:
            log_fn(f"✗ 无效时间段 s={s} e={e}", "err")
            return 1

        new_id   = f"{song_id}_{s}_{e}"
        out_dir  = out_root / new_id
        out_dir.mkdir(parents=True, exist_ok=True)

        if in_jpg.exists():
            shutil.copy2(in_jpg, out_dir / "base.jpg")

        log_fn(f"  ♪ 音频 {s}ms – {e}ms  speed={speed}…", "normal")
        try:
            slice_ogg(in_ogg, out_dir / "base.ogg", s, e, speed)
        except subprocess.CalledProcessError as ex:
            log_fn(f"✗ ffmpeg 失败: {ex}", "err")
            return 1

        log_fn(f"  ✎ 谱面 {s}ms – {e}ms…", "normal")
        aff_warnings: list[str] = []
        new_aff = slice_aff(in_aff.read_text(encoding="utf-8", errors="replace"), s, e, speed, aff_warnings)
        for warning in aff_warnings:
            log_fn(f"  ⚠ {warning}", "muted")
        (out_dir / "2.aff").write_text(new_aff, encoding="utf-8")

        frag = make_songlist_fragment(new_id, s, e, speed)
        if frag:
            (out_dir / "songlist_fragment.json").write_text(
                json.dumps(frag, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        if songlist_meta:
            entry = make_songlist_entry(new_id, i, s, e, speed, songlist_meta)
            (out_dir / "songlist").write_text(
                json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            all_song_entries.append(entry["songs"][0])
            log_fn(f"  ✎ songlist → {new_id}", "muted")

        log_fn(f"✓ 输出 → out/songs/{new_id}/", "ok")

    # 合并 songlist 输出到 out/ 根目录
    if songlist_meta and all_song_entries:
        merged_path = OUT_DIR / "songlist"
        merged_path.write_text(
            json.dumps({"songs": all_song_entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log_fn(f"✓ 合并 songlist → out/songlist（共 {len(all_song_entries)} 首）", "ok")

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

class SlicerWorker(QThread):
    log_signal  = pyqtSignal(str, str)  # text, kind
    done_signal = pyqtSignal(int)       # return code

    def __init__(
        self, songs_dir: Path, song_id: str, segments: list,
        speed: float, songlist_meta: dict | None = None,
    ):
        super().__init__()
        self.songs_dir     = songs_dir
        self.song_id       = song_id
        self.segments      = segments
        self.speed         = speed
        self.songlist_meta = songlist_meta

    def run(self):
        def log(text, kind="normal"):
            self.log_signal.emit(text, kind)

        log(f"  songs 目录: {self.songs_dir}", "muted")
        log(f"  曲目: {self.song_id}  速度: {self.speed}  段数: {len(self.segments)}", "muted")
        if self.songlist_meta:
            log("  songlist 生成: 开启", "muted")
        code = do_slice(self.songs_dir, self.song_id, self.segments, self.speed, log, self.songlist_meta)
        if code == 0:
            log("✓ 全部完成！输出目录: out/songs/", "ok")
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
    color: #FFFFFF;
    border: none;
    padding: 12px 22px;
    font-size: 14px;
}}
QPushButton#btnRun:hover {{
    background: {C_ACCENT_H};
}}
QPushButton#btnRun:disabled {{
    opacity: 0.8;
    background: {C_ACCENT};
}}
QPushButton#btnSec {{
    background: {C_CARD2};
    color: {C_TEXT2};
    border: 1px solid {C_INPUT_BD};
    padding: 11px 16px;
    font-size: 14px;
}}
QPushButton#btnSec:hover {{
    background: #EAE6DB;
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
    color: #CDC8BC;
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


def card_frame(bg: str = C_CARD, border: str = C_BORDER) -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        f"background: {bg}; border: 1px solid {border}; "
        f"border-radius: 12px;"
    )
    return f


# ─── DropZone ─────────────────────────────────────────────────────────────────

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

    def __init__(self, index: int, s: int | None, e: int | None, parent=None):
        super().__init__(parent)
        self.s_val = s
        self.e_val = e
        self.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid #EAE6DC; border-radius: 12px; }"
        )
        self._setup_ui(index, s, e)

    def _setup_ui(self, index: int, s: int | None, e: int | None):
        lay = QGridLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(5)

        badge = QLabel(str(index))
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {C_BADGE_BG}; color: {C_ACCENT}; "
            f"font-weight: 700; font-size: 13px; border-radius: 8px; border: none;"
        )
        lay.addWidget(badge, 1, 0, Qt.AlignmentFlag.AlignVCenter)
        self._badge = badge

        lay.addWidget(field_label("开始 START"), 0, 1)
        self._start = QLineEdit("" if s is None else str(s))
        self._start.setFixedWidth(110)
        lay.addWidget(self._start, 1, 1, Qt.AlignmentFlag.AlignVCenter)

        arrow = QLabel("→")
        arrow.setStyleSheet(f"color: #C9C4B8; font-size: 15px; background: transparent; border: none;")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(arrow, 1, 2, Qt.AlignmentFlag.AlignVCenter)

        lay.addWidget(field_label("结束 END"), 0, 3)
        self._end = QLineEdit("" if e is None else str(e))
        self._end.setFixedWidth(110)
        lay.addWidget(self._end, 1, 3, Qt.AlignmentFlag.AlignVCenter)

        self._dur = QLabel()
        self._dur.setStyleSheet(
            f"font-family: 'Consolas','Courier New',monospace; font-size: 13px; "
            f"font-weight: 500; color: {C_LABEL}; background: transparent; border: none;"
        )
        self._dur.setMinimumWidth(60)
        self._dur.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._dur, 1, 4, Qt.AlignmentFlag.AlignVCenter)

        spacer = QWidget()
        spacer.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(spacer, 1, 5)
        lay.setColumnStretch(5, 1)

        self._arc_indicator_box = QWidget()
        self._arc_indicator_box.setStyleSheet("background: transparent; border: none;")
        self._arc_status_layout = QHBoxLayout(self._arc_indicator_box)
        self._arc_status_layout.setContentsMargins(0, 0, 0, 0)
        self._arc_status_layout.setSpacing(12)
        self._arc_statuses: list[ArcCutStatus] = []
        lay.addWidget(self._arc_indicator_box, 1, 6, Qt.AlignmentFlag.AlignVCenter)
        self.set_arc_cut_warnings([], [])

        btn_del = QPushButton("✕")
        btn_del.setObjectName("btnDel")
        lay.addWidget(btn_del, 1, 7, Qt.AlignmentFlag.AlignVCenter)

        self._update_dur()
        self._start.textChanged.connect(self._on_change)
        self._end.textChanged.connect(self._on_change)
        btn_del.clicked.connect(lambda: self.deleted.emit(self))

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
        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 折叠按钮（复用 btnAdd 样式）
        self._toggle_btn = QPushButton("▶  Songlist 生成配置（可选，点击展开）")
        self._toggle_btn.setObjectName("btnAdd")
        self._toggle_btn.clicked.connect(self._toggle)
        outer.addWidget(self._toggle_btn)

        # 面板主体
        self._body = QFrame()
        self._body.setObjectName("songlistBody")
        self._body.setStyleSheet(
            f"QFrame#songlistBody {{ background: {C_CARD}; border: 1px solid {C_BORDER};"
            f" border-radius: 14px; }}"
        )
        self._body.hide()
        outer.addWidget(self._body)

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
            col_lay.addWidget(field_label(label_text))
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

    # ── 折叠 / 展开 ───────────────────────────────────────────────────────────

    def _toggle(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._toggle_btn.setText(
            "▼  Songlist 生成配置（点击收起）" if self._expanded
            else "▶  Songlist 生成配置（可选，点击展开）"
        )

    # ── 读 / 写 ───────────────────────────────────────────────────────────────

    def get_meta(self) -> dict | None:
        """返回配置字典，面板未展开时返回 None（不生成 songlist）。"""
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
        str_keys = ("title_base", "artist", "bpm", "set", "purchase", "bg", "version",
                    "chart_designer", "jacket_designer")
        for k in str_keys:
            if k in meta:
                self._inputs[k].setText(str(meta[k]))
        for k in ("bpm_base", "side", "rating"):
            if k in meta:
                self._inputs[k].setText(str(meta[k]))
        if "rating_plus" in meta:
            self._rating_plus.setChecked(bool(meta["rating_plus"]))
        # 有保存数据时自动展开
        if any(meta.get(k) for k in ("title_base", "artist")):
            if not self._expanded:
                self._toggle()


# ─── 主窗口 ───────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._migration_report = prepare_runtime_data()
        self._cfg    = load_config()
        self._rows: list[SegmentRow] = []
        self._worker: SlicerWorker | None = None
        self._uid    = 0
        self._arc_warning_timer = QTimer(self)
        self._arc_warning_timer.setSingleShot(True)
        self._arc_warning_timer.timeout.connect(self._refresh_arc_cut_warnings)

        self.setWindowTitle("Arc Slicer")
        self.setMinimumSize(620, 580)
        self.resize(760, 900)
        self.setAcceptDrops(True)

        self._setup_ui()
        if self._migration_report.has_activity():
            self._push_log(self._migration_report.message(), "muted")
        self._load_initial_data()

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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)

        content = QWidget()
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setStyleSheet(f"QWidget {{ background: {C_BG}; }}")
        scroll.setWidget(content)

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
        self._song_box.currentTextChanged.connect(lambda _text: self._schedule_arc_cut_warning_refresh())
        song_col.addWidget(self._song_box)
        tb_lay.addLayout(song_col, 1)

        speed_col = QVBoxLayout()
        speed_col.setSpacing(7)
        speed_col.addWidget(field_label("速度 SPEED"))
        self._speed_input = QLineEdit("1.0")
        self._speed_input.setFixedWidth(124)
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

        # ── 操作行
        actions = QHBoxLayout()
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
        lay.addLayout(actions)
        lay.addSpacing(16)

        # ── Songlist 配置面板
        self._songlist_panel = SonglistPanel()
        lay.addWidget(self._songlist_panel)
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
            self._schedule_arc_cut_warning_refresh()
            return
        for s in songs:
            self._song_box.addItem(s)
        if current in songs:
            self._song_box.setCurrentText(current)
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
        if data.get("songlist"):
            self._songlist_panel.set_meta(data["songlist"])
        self._schedule_arc_cut_warning_refresh()

    # ── 目录操作 ──────────────────────────────────────────────────────────────

    def _refresh_dir_label(self):
        p = self._cfg.get("songs_dir", "")
        self._dir_path.setText(p)
        self._dir_path.setToolTip(p)

    def _browse_songs_dir(self):
        d = self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR))
        path = QFileDialog.getExistingDirectory(self, "选择 songs 根目录", d)
        if path:
            self._cfg["songs_dir"] = path
            save_config(self._cfg)
            self._refresh_dir_label()
            self._populate_songs(self._get_songs())
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
        self._rows.append(row)
        self._segs_layout.addWidget(row)
        self._refresh_seg_header()
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
        self._schedule_arc_cut_warning_refresh()

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
        data: dict = {
            "song_id":  self._song_box.currentText(),
            "speed":    parse_speed_text(self._speed_input.text()) if speed is None else speed,
            "segments": [r.to_dict() for r in self._rows if r.to_dict()],
        }
        meta = self._songlist_panel.get_meta()
        if meta is not None:
            data["songlist"] = meta
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
        if self._worker and self._worker.isRunning():
            return
        try:
            speed = parse_speed_text(self._speed_input.text())
        except ValueError as ex:
            self._push_log(f"✗ 速度无效: {ex}", "err")
            return
        data = self._collect(speed)
        if not data["song_id"] or "目录为空" in data["song_id"]:
            self._push_log("✗ 请先选择曲目 Song ID", "err")
            return
        if not data["segments"]:
            self._push_log("✗ 至少需要一个时间段", "err")
            return

        self._save_slides()
        self._log_widget.clear()
        self._log_widget.show()
        self._set_running(True)
        self._push_log("▶ 开始切片…", "muted")

        songs_dir     = Path(self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR)))
        songlist_meta = self._songlist_panel.get_meta()
        self._worker = SlicerWorker(
            songs_dir, data["song_id"], data["segments"], data["speed"], songlist_meta
        )
        self._worker.log_signal.connect(self._push_log)
        self._worker.done_signal.connect(self._on_done)
        self._worker.start()

    def _on_done(self, code: int):
        self._set_running(False)

    def _set_running(self, on: bool):
        self._btn_run.setEnabled(not on)
        self._btn_run.setText("▶  运行中…" if on else "▶  运行切片")

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
        "ok":     "#A6C293",
        "err":    "#E6907A",
        "muted":  "#8A857A",
        "normal": "#CDC8BC",
    }

    def _push_log(self, text: str, kind: str = "normal"):
        self._log_widget.show()
        color = self.LOG_COLORS.get(kind, self.LOG_COLORS["normal"])
        # Use HTML for colored lines
        import html as _html
        escaped = _html.escape(text)
        self._log_widget.append(f'<span style="color:{color};">{escaped}</span>')
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
