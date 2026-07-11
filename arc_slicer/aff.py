"""Pure AFF slicing helpers."""
from __future__ import annotations

import math
import re
from decimal import Decimal

from arc_slicer.segments import validate_speed_value

_TIMING_RE = re.compile(
    r"^\s*timing\(([+-]?\d+),([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?)\);\s*$",
    re.IGNORECASE,
)
_AUDIO_OFFSET_RE = re.compile(r"^\s*AudioOffset\s*:\s*([+-]?\d+)\s*$", re.IGNORECASE)
CAMERA_SCENE_WARNING = (
    "????????????????? Camera/Scenecontrol ??????????????"
    "????????????"
)
AUDIO_OFFSET_WARNING = (
    "????? AudioOffset?????????????? AFF Offset ??????"
    "???????????????"
)
NONLINEAR_ARC_EASINGS = {"b", "si", "so", "sisi", "siso", "sosi", "soso"}
ARC_CUT_EASING_ORDER = ("si", "so", "b", "sisi", "siso", "sosi", "soso")
_ARC_LINE_RE = re.compile(
    r"\s*arc\(([+-]?\d+),([+-]?\d+),(.*)\)\s*(\[(.*)\])?;\s*$",
    re.IGNORECASE,
)

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
