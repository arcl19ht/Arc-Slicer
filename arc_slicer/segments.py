"""Pure segment validation and naming helpers."""
from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

TIME_INPUT_PATTERN = r"^-?\d*$"
_TIME_INPUT_RE = re.compile(r"^-?\d*$")

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


def normalize_speed_override_value(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        return parse_speed_text(value)
    return validate_speed_value(float(value))


def effective_segment_speed(default_speed: float, speed_override=None) -> float:
    default_speed = validate_speed_value(float(default_speed))
    override = normalize_speed_override_value(speed_override)
    return override if override is not None else default_speed
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


def format_duration_ms(duration_ms: int) -> str:
    duration_ms = max(0, int(duration_ms))
    total_seconds, ms = divmod(duration_ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}.{ms:03d}"
    return f"{minutes}:{seconds:02d}.{ms:03d}"


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
    *,
    allow_draft: bool = False,
) -> SegmentValidationResult:
    if allow_draft:
        start_raw = str(start_text)
        end_raw = str(end_text)
        if not start_raw and not end_raw:
            return SegmentValidationResult()
        if not start_raw or not end_raw:
            value_text = start_raw or end_raw
            field_name = "起点" if start_raw else "终点"
            value, error = _parse_non_negative_time_text(value_text, field_name)
            result = SegmentValidationResult(
                start_error=error if start_raw else "",
                end_error=error if end_raw else "",
            )
            if error:
                result.first_field = "start" if start_raw else "end"
                result.first_message = error
                return result
            if value is not None and audio_duration_ms is not None:
                if start_raw and value >= audio_duration_ms:
                    result.start_error = f"起点不能超过音频时长：{format_duration_ms(audio_duration_ms)}"
                elif end_raw and value > audio_duration_ms:
                    result.end_error = f"终点不能超过音频时长：{format_duration_ms(audio_duration_ms)}"
                    result.end_cap_ms = int(audio_duration_ms)
            if result.start_error:
                result.first_field = "start"
                result.first_message = result.start_error
            elif result.end_error:
                result.first_field = "end"
                result.first_message = result.end_error
            return result

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


def normalize_link_group_id(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def new_link_group_id() -> str:
    return f"grp_{uuid.uuid4().hex[:10]}"


def find_inconsistent_link_groups(rows) -> dict[str, dict]:
    """Return complete link groups whose members do not share one interval."""
    groups: dict[str, list[tuple[str, int, int]]] = {}
    for row in rows:
        if isinstance(row, dict):
            group_id = normalize_link_group_id(row.get("link_group_id"))
            uid = str(row.get("uid", ""))
            start, end = row.get("s"), row.get("e")
        else:
            group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
            uid = str(getattr(row, "uid", ""))
            start, end = getattr(row, "s_val", None), getattr(row, "e_val", None)
        if not group_id:
            continue
        try:
            start, end = int(start), int(end)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        groups.setdefault(group_id, []).append((uid, start, end))

    inconsistent: dict[str, dict] = {}
    for group_id, members in groups.items():
        intervals = {(start, end) for _uid, start, end in members}
        if len(members) >= 2 and len(intervals) > 1:
            inconsistent[group_id] = {
                "member_uids": tuple(uid for uid, _start, _end in members),
                "intervals": frozenset(intervals),
            }
    return inconsistent
