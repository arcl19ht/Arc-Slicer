"""Waveform and timeline panel widget."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QRect
from PyQt6.QtGui import QColor, QPainter, QPen, QMouseEvent
from PyQt6.QtWidgets import QFrame
try:
    from PyQt6.QtWidgets import QScrollBar
except ImportError:
    QScrollBar = None

from arc_slicer.segments import format_duration_ms, normalize_link_group_id
from arc_slicer.theme import (
    C_ACCENT, C_BORDER, C_BORDER2, C_CARD2, C_DRAFT_END, C_DRAFT_START, C_HOVERED,
    C_LABEL, C_LANE_SEPARATOR, C_MUTED, C_SEGMENT_ALT_FILL, C_SEGMENT_BORDER,
    C_SEGMENT_FILL, C_SELECTED, C_TEXT, C_TEXT2, C_TIMELINE_BG,
    C_TIMELINE_TRACK, C_WAVEFORM,
)
from arc_slicer.waveform import WAVEFORM_HANDLE_PX, WAVEFORM_MIN_SEGMENT_MS, WaveformData

class _SimpleWaveformPoint:
    def __init__(self, y: int, x: int = 0):
        self._y = int(y)
        self._x = int(x)

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y


class _SimpleWaveformSize:
    def __init__(self, width: int, height: int):
        self._width = int(width)
        self._height = int(height)

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _SimpleWaveformRect:
    def __init__(self, left: int, top: int, width: int, height: int):
        self._left = int(left)
        self._top = int(top)
        self._width = max(1, int(width))
        self._height = max(1, int(height))

    def left(self) -> int:
        return self._left

    def top(self) -> int:
        return self._top

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def right(self) -> int:
        return self._left + self._width

    def bottom(self) -> int:
        return self._top + self._height

    def contains(self, x: int, y: int) -> bool:
        return self.left() <= int(x) <= self.right() and self.top() <= int(y) <= self.bottom()

    def center(self) -> _SimpleWaveformPoint:
        return _SimpleWaveformPoint(self._top + self._height // 2, self._left + self._width // 2)

    def adjusted(self, left: int, top: int, right: int, bottom: int):
        return _SimpleWaveformRect(
            self._left + int(left),
            self._top + int(top),
            self._width - int(left) + int(right),
            self._height - int(top) + int(bottom),
        )


class WaveformPanel(QFrame):
    segmentCreated = pyqtSignal(int, int)
    segmentEndpointChanged = pyqtSignal(int, int, int)
    segmentEndpointCommitted = pyqtSignal()
    segmentEndpointDragStarted = pyqtSignal(str, str)
    segmentEndpointDragFinished = pyqtSignal(str, str)
    segmentHovered = pyqtSignal(str)
    segmentSelected = pyqtSignal(str)
    emptySelected = pyqtSignal()
    timeline_quick_draft_requested = pyqtSignal(int)
    TIMELINE_LANE_HEIGHT = 28
    TIMELINE_LANE_GAP = 2
    TIMELINE_PADDING = 6
    TIMELINE_SCROLLBAR_WIDTH = 10
    TIMELINE_COLLAPSED_LANES = 3
    TIMELINE_MAX_EXPANDED_LANES = 10
    TIMELINE_GRIP_HEIGHT = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "empty"
        self._message = "选择源曲后显示波形"
        self._waveform: WaveformData | None = None
        self._segments: list[tuple[int, int]] = []
        self._segment_items: list[dict] = []
        self._draft_segments: list[dict] = []
        self._quick_draft_anchor_ms: int | None = None
        self._playback_position_ms: int | None = None
        self._hover_time_ms: int | None = None
        self._hovered_segment_uid = ""
        self._selected_segment_uid = ""
        self._drag_mode: str | None = None
        self._drag_index: int | None = None
        self._drag_anchor_ms: int | None = None
        self._drag_preview: tuple[int, int] | None = None
        self._last_endpoint_emit: tuple[int, int, int] | None = None
        self._fallback_width = 1000
        self._fallback_height = 130
        self._timeline_expanded = True
        self._timeline_visible_lanes = self.TIMELINE_COLLAPSED_LANES
        self._timeline_user_height: int | None = None
        self._timeline_scroll_offset = 0
        self._timeline_resize_active = False
        self._timeline_resize_start_y = 0
        self._timeline_resize_start_height = 0
        self._timeline_grip_hover = False
        self._timeline_scrollbar = None
        if QScrollBar is not None:
            try:
                self._timeline_scrollbar = QScrollBar(Qt.Orientation.Vertical, self)
                self._timeline_scrollbar.valueChanged.connect(self._on_timeline_scrollbar_value_changed)
                self._timeline_scrollbar.setVisible(False)
                self._timeline_scrollbar.setStyleSheet(
                    "QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }"
                    "QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 5px; min-height: 24px; }"
                    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
                    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
                )
            except Exception:
                self._timeline_scrollbar = None
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self.setMaximumHeight(460)
        self.setStyleSheet(
            f"QFrame {{ background: {C_TIMELINE_BG}; border: 1px solid {C_BORDER}; border-radius: 10px; }}"
        )

    def status_text(self) -> str:
        return self._message

    def waveform_data(self) -> WaveformData | None:
        return self._waveform

    def segment_ranges(self) -> list[tuple[int, int]]:
        return list(self._segments)

    def segment_items(self) -> list[dict]:
        return [dict(item) for item in self._segment_items]

    def draft_segments(self) -> list[dict]:
        return [dict(item) for item in self._draft_segments]

    def current_hover_time_ms(self) -> int | None:
        return self._hover_time_ms

    def quick_draft_anchor_ms(self) -> int | None:
        return self._quick_draft_anchor_ms

    def playback_position_ms(self) -> int | None: return self._playback_position_ms
    def set_playback_position_ms(self, position_ms: int | None) -> None:
        duration = self._duration_ms()
        value = None if position_ms is None or duration <= 0 else max(0, min(duration, int(position_ms)))
        if value != self._playback_position_ms: self._playback_position_ms = value; self.update()

    def set_quick_draft_anchor(self, time_ms: int | None) -> None:
        if time_ms is None:
            anchor = None
        elif self._duration_ms() > 0:
            anchor = max(0, min(self._duration_ms(), int(time_ms)))
        else:
            anchor = None
        if anchor != self._quick_draft_anchor_ms:
            self._quick_draft_anchor_ms = anchor
            self.update()

    def resize(self, width: int, height: int) -> None:
        try:
            self._fallback_width = max(1, int(width) - 24)
            self._fallback_height = max(1, int(height) - 20)
        except (TypeError, ValueError):
            pass
        try:
            super().resize(width, height)
        except Exception:
            pass
        self._update_timeline_scrollbar()

    def sizeHint(self) -> QSize:
        content_h = (
            24
            + self._waveform_area_preferred_height()
            + 18
            + self._preferred_timeline_viewport_height()
            + self.TIMELINE_GRIP_HEIGHT
        )
        width = 720
        height = max(220, min(460, int(content_h)))
        try:
            size = QSize(width, height)
            if type(size.width()) is int and type(size.height()) is int:
                return size
        except Exception:
            pass
        return _SimpleWaveformSize(width, height)

    def minimumSizeHint(self) -> QSize:
        try:
            size = QSize(520, 220)
            if type(size.width()) is int and type(size.height()) is int:
                return size
        except Exception:
            pass
        return _SimpleWaveformSize(520, 220)

    def resizeEvent(self, event) -> None:
        self._update_timeline_scrollbar()
        try:
            super().resizeEvent(event)
        except Exception:
            pass

    def _rect_is_usable(self, rect) -> bool:
        try:
            values = (rect.left(), rect.top(), rect.width(), rect.height(), rect.right(), rect.bottom())
        except Exception:
            return False
        return all(type(value) in (int, float) for value in values)

    def _make_rect(self, left: int, top: int, width: int, height: int):
        try:
            rect = QRect(int(left), int(top), max(1, int(width)), max(1, int(height)))
            if self._rect_is_usable(rect):
                return rect
        except Exception:
            pass
        return _SimpleWaveformRect(int(left), int(top), max(1, int(width)), max(1, int(height)))

    def _content_rect(self) -> QRect:
        try:
            rect = self.rect().adjusted(12, 10, -12, -10)
            if self._rect_is_usable(rect):
                return rect
        except Exception:
            pass
        return _SimpleWaveformRect(12, 10, self._fallback_width, self._fallback_height)

    def _waveform_area_rect(self) -> QRect:
        rect = self._content_rect()
        height = max(54, min(88, int(rect.height() * 0.52)))
        return self._make_rect(rect.left(), rect.top(), rect.width(), min(height, rect.height()))

    def _ruler_rect(self) -> QRect:
        rect = self._content_rect()
        waveform = self._waveform_area_rect()
        top = waveform.bottom() + 1
        height = min(20, max(14, rect.bottom() - top + 1))
        return self._make_rect(rect.left(), top, rect.width(), max(1, height))

    def _timeline_area_rect(self) -> QRect:
        outer = self._timeline_outer_rect()
        width = max(1, outer.width() - self._timeline_scrollbar_reserved_width())
        return self._make_rect(outer.left(), outer.top(), width, outer.height())

    def _timeline_outer_rect(self) -> QRect:
        rect = self._content_rect()
        ruler = self._ruler_rect()
        top = ruler.bottom() + 1
        available = max(1, rect.bottom() - top + 1 - self.TIMELINE_GRIP_HEIGHT)
        height = max(self._timeline_min_viewport_height(), min(available, self._timeline_viewport_height()))
        return self._make_rect(rect.left(), top, rect.width(), height)

    def _timeline_grip_rect(self) -> QRect:
        outer = self._timeline_outer_rect()
        top = outer.bottom() + 1
        return self._make_rect(outer.left(), top, outer.width(), self.TIMELINE_GRIP_HEIGHT)

    def _hit_timeline_grip(self, x: int, y: int) -> bool:
        try:
            return self._timeline_grip_rect().contains(int(x), int(y))
        except Exception:
            return False

    def _waveform_rect(self) -> QRect:
        return self._waveform_area_rect()

    def _waveform_area_preferred_height(self) -> int:
        return 88

    def _timeline_lane_count(self) -> int:
        return max(1, len(self._segment_items))

    def _timeline_content_height(self) -> int:
        count = self._timeline_lane_count()
        return (
            self.TIMELINE_PADDING * 2
            + count * self.TIMELINE_LANE_HEIGHT
            + max(0, count - 1) * self.TIMELINE_LANE_GAP
        )

    def _timeline_min_viewport_height(self) -> int:
        visible = max(1, self.TIMELINE_COLLAPSED_LANES)
        return (
            self.TIMELINE_PADDING * 2
            + visible * self.TIMELINE_LANE_HEIGHT
            + max(0, visible - 1) * self.TIMELINE_LANE_GAP
        )

    def _timeline_auto_viewport_height(self) -> int:
        visible = min(self._timeline_lane_count(), self.TIMELINE_MAX_EXPANDED_LANES)
        return (
            self.TIMELINE_PADDING * 2
            + visible * self.TIMELINE_LANE_HEIGHT
            + max(0, visible - 1) * self.TIMELINE_LANE_GAP
        )

    def _preferred_timeline_viewport_height(self) -> int:
        return self._timeline_viewport_height()

    def _timeline_viewport_height(self) -> int:
        auto_height = self._timeline_auto_viewport_height()
        if self._timeline_user_height is None:
            return auto_height
        return max(self._timeline_min_viewport_height(), min(int(self._timeline_user_height), auto_height))

    def _set_timeline_user_height(self, height: int | None) -> None:
        if height is None:
            new_height = None
        else:
            new_height = max(self._timeline_min_viewport_height(), min(int(height), self._timeline_auto_viewport_height()))
            if new_height >= self._timeline_auto_viewport_height():
                new_height = None
        if self._timeline_user_height == new_height:
            return
        self._timeline_user_height = new_height
        self._timeline_expanded = new_height is None
        self._update_timeline_scrollbar()
        self.updateGeometry()
        self.update()

    def _timeline_scroll_max_for_rect(self, rect) -> int:
        return max(0, self._timeline_content_height() - max(1, rect.height()))

    def _timeline_scroll_max(self) -> int:
        return self._timeline_scroll_max_for_rect(self._timeline_outer_rect())

    def _timeline_scrollbar_reserved_width(self) -> int:
        return self.TIMELINE_SCROLLBAR_WIDTH + 4 if self._timeline_scroll_max_for_rect(self._timeline_outer_rect()) > 0 else 0

    def _clamp_timeline_scroll(self) -> None:
        self._timeline_scroll_offset = max(0, min(int(self._timeline_scroll_offset), self._timeline_scroll_max()))

    def _set_timeline_scroll_offset(self, value: int) -> bool:
        old = self._timeline_scroll_offset
        self._timeline_scroll_offset = max(0, min(int(value), self._timeline_scroll_max()))
        changed = self._timeline_scroll_offset != old
        if changed:
            self.update()
        self._update_timeline_scrollbar()
        return changed

    def _scroll_timeline_by(self, delta: int) -> bool:
        return self._set_timeline_scroll_offset(self._timeline_scroll_offset + int(delta))

    def _on_timeline_scrollbar_value_changed(self, value: int) -> None:
        self._timeline_scroll_offset = max(0, min(int(value), self._timeline_scroll_max()))
        self.update()

    def _update_timeline_scrollbar(self) -> None:
        self._clamp_timeline_scroll()
        bar = self._timeline_scrollbar
        if bar is None:
            return
        outer = self._timeline_outer_rect()
        scroll_max = self._timeline_scroll_max_for_rect(outer)
        try:
            bar.setGeometry(
                outer.right() - self.TIMELINE_SCROLLBAR_WIDTH + 1,
                outer.top(),
                self.TIMELINE_SCROLLBAR_WIDTH,
                outer.height(),
            )
            old_block = bar.blockSignals(True)
            bar.setRange(0, scroll_max)
            bar.setPageStep(max(1, outer.height()))
            bar.setSingleStep(self.TIMELINE_LANE_HEIGHT + self.TIMELINE_LANE_GAP)
            bar.setValue(self._timeline_scroll_offset)
            bar.blockSignals(old_block)
            bar.setVisible(scroll_max > 0)
        except Exception:
            pass

    def timeline_expanded(self) -> bool:
        return self._timeline_user_height is None

    def set_timeline_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded:
            self._set_timeline_user_height(None)
        else:
            self._set_timeline_user_height(self._timeline_min_viewport_height())
        self._set_timeline_scroll_offset(0)
        self.updateGeometry()
        self.update()

    def set_timeline_visible_lanes(self, count: int) -> None:
        try:
            value = int(count)
        except (TypeError, ValueError):
            value = self.TIMELINE_COLLAPSED_LANES
        self._timeline_visible_lanes = max(1, value)
        if self._timeline_user_height is not None:
            visible = max(1, self._timeline_visible_lanes)
            height = (
                self.TIMELINE_PADDING * 2
                + visible * self.TIMELINE_LANE_HEIGHT
                + max(0, visible - 1) * self.TIMELINE_LANE_GAP
            )
            self._set_timeline_user_height(height)
        self._update_timeline_scrollbar()
        self.updateGeometry()
        self.update()

    def toggle_timeline_expanded(self) -> None:
        self.set_timeline_expanded(self._timeline_user_height is not None)

    def ensure_segment_uid_visible(self, uid: str) -> bool:
        uid = str(uid or "")
        if not uid:
            return False
        index = next((i for i, item in enumerate(self._segment_items) if item.get("uid") == uid), None)
        if index is None:
            return False
        lane_top = self.TIMELINE_PADDING + index * (self.TIMELINE_LANE_HEIGHT + self.TIMELINE_LANE_GAP)
        lane_bottom = lane_top + self.TIMELINE_LANE_HEIGHT
        viewport_h = max(1, self._timeline_outer_rect().height())
        offset = self._timeline_scroll_offset
        if lane_top < offset:
            return self._set_timeline_scroll_offset(lane_top)
        if lane_bottom > offset + viewport_h:
            return self._set_timeline_scroll_offset(lane_bottom - viewport_h)
        return False

    def _duration_ms(self) -> int:
        data = self._waveform
        if self._state != "ready" or data is None:
            return 0
        try:
            return max(0, int(data.duration_ms))
        except (TypeError, ValueError):
            return 0

    def _can_interact(self) -> bool:
        return self._duration_ms() > 0 and bool(self._waveform and self._waveform.peaks)

    def time_ms_to_x(self, time_ms) -> int:
        rect = self._waveform_rect()
        width = max(1, rect.width())
        duration_ms = self._duration_ms()
        if duration_ms <= 0:
            return 0
        try:
            value = int(time_ms)
        except (TypeError, ValueError):
            value = 0
        value = max(0, min(duration_ms, value))
        return int(round(width * value / duration_ms))

    def x_to_time_ms(self, x) -> int:
        rect = self._waveform_rect()
        width = max(1, rect.width())
        duration_ms = self._duration_ms()
        if duration_ms <= 0:
            return 0
        try:
            value = float(x)
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(float(width), value))
        return int(round(duration_ms * value / width))

    def set_empty(self) -> None:
        self._state = "empty"
        self._message = "选择源曲后显示波形"
        self._waveform = None
        self._quick_draft_anchor_ms = None
        self._segment_items = []
        self._segments = []
        self._draft_segments = []
        self._hover_time_ms = None
        self._set_timeline_scroll_offset(0)
        self._cancel_drag()
        self.update()

    def set_loading(self) -> None:
        self._state = "loading"
        self._message = "正在生成波形…"
        self._waveform = None
        self._quick_draft_anchor_ms = None
        self._segment_items = []
        self._segments = []
        self._draft_segments = []
        self._hover_time_ms = None
        self._set_timeline_scroll_offset(0)
        self._cancel_drag()
        self.update()

    def set_error(self) -> None:
        self._state = "error"
        self._message = "波形生成失败，不影响切片。"
        self._waveform = None
        self._quick_draft_anchor_ms = None
        self._segment_items = []
        self._segments = []
        self._draft_segments = []
        self._hover_time_ms = None
        self._set_timeline_scroll_offset(0)
        self._cancel_drag()
        self.update()

    def set_waveform(self, data: WaveformData) -> None:
        self._state = "ready"
        self._message = ""
        self._waveform = data
        self._hover_time_ms = None
        self._cancel_drag()
        self.update()

    def set_segments(self, segments: list[tuple[int, int]]) -> None:
        cleaned: list[tuple[int, int]] = []
        items: list[dict] = []
        for index, item in enumerate(segments):
            try:
                start = item[0]
                end = item[1]
                s = int(start)
                e = int(end)
                uid = str(item[2]) if len(item) >= 3 else str(index)
                group_key = tuple(item[3]) if len(item) >= 4 and item[3] is not None else (s, e)
                link_group_id = normalize_link_group_id(item[4]) if len(item) >= 5 else None
                join_available = bool(item[5]) if len(item) >= 6 else False
                join_mode = str(item[6] or "") if len(item) >= 7 else ("join_existing" if join_available else "")
            except (TypeError, ValueError, IndexError):
                continue
            if e > s:
                cleaned.append((s, e))
                items.append({
                    "index": len(items),
                    "uid": uid,
                    "start": s,
                    "end": e,
                    "group_key": group_key,
                    "link_group_id": link_group_id,
                    "join_available": join_available,
                    "join_mode": join_mode,
                })
        self._segments = cleaned
        self._segment_items = items
        self._update_timeline_scrollbar()
        self.updateGeometry()
        self.update()

    def set_selection_state(self, selected_uid: str = "", hovered_uid: str = "") -> None:
        self._selected_segment_uid = str(selected_uid or "")
        self._hovered_segment_uid = str(hovered_uid or "")
        self.update()

    def set_draft_segments(self, drafts: list[dict]) -> None:
        cleaned: list[dict] = []
        for item in drafts:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            if kind not in {"start", "end"}:
                continue
            try:
                index = int(item.get("index", len(cleaned)))
                time_ms = int(item["time_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            if time_ms < 0:
                continue
            cleaned.append({"index": index, "kind": kind, "time_ms": time_ms})
        self._draft_segments = cleaned
        self._update_timeline_scrollbar()
        self.updateGeometry()
        self.update()

    def _local_x_from_widget_x(self, widget_x) -> float:
        return float(widget_x) - float(self._waveform_rect().left())

    def _segment_widget_edges(self) -> list[tuple[int, int, int, int, int]]:
        rect = self._timeline_area_rect()
        edges: list[tuple[int, int, int, int, int]] = []
        if not self._can_interact():
            return edges
        for index, item in enumerate(self._segment_items):
            start_ms = item["start"]
            end_ms = item["end"]
            start_x = rect.left() + self.time_ms_to_x(start_ms)
            end_x = rect.left() + self.time_ms_to_x(end_ms)
            if end_x <= start_x:
                end_x = start_x + 1
            edges.append((index, start_x, end_x, start_ms, end_ms))
        return edges

    def _lane_rect(self, index: int) -> QRect:
        rect = self._timeline_area_rect()
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = 0
        top = (
            rect.top()
            + self.TIMELINE_PADDING
            + index * (self.TIMELINE_LANE_HEIGHT + self.TIMELINE_LANE_GAP)
            - self._timeline_scroll_offset
        )
        return self._make_rect(rect.left(), int(top), rect.width(), self.TIMELINE_LANE_HEIGHT)

    def _segment_lane_rect(self, _rect, index: int) -> QRect:
        return self._lane_rect(index)

    def _segment_clip_rect(self, rect, index: int, start_ms: int, end_ms: int) -> QRect:
        lane_rect = self._lane_rect(index)
        start_x = rect.left() + self.time_ms_to_x(start_ms)
        end_x = rect.left() + self.time_ms_to_x(end_ms)
        if end_x <= start_x:
            end_x = start_x + 1
        return self._make_rect(int(start_x), lane_rect.top(), max(1, int(end_x - start_x)), lane_rect.height())

    def _hit_endpoint(self, widget_x, widget_y: float | None = None) -> tuple[int, str] | None:
        x = float(widget_x)
        for index, start_x, end_x, _start_ms, _end_ms in reversed(self._segment_widget_edges()):
            if widget_y is not None and not self._lane_rect(index).contains(int(x), int(widget_y)):
                continue
            left_distance = abs(x - start_x)
            right_distance = abs(x - end_x)
            if left_distance <= WAVEFORM_HANDLE_PX or right_distance <= WAVEFORM_HANDLE_PX:
                if left_distance <= right_distance:
                    return index, "start"
                return index, "end"
        return None

    def _hit_segment_body(self, widget_x, widget_y: float | None = None) -> int | None:
        x = float(widget_x)
        for index, start_x, end_x, _start_ms, _end_ms in reversed(self._segment_widget_edges()):
            if widget_y is not None and not self._lane_rect(index).contains(int(x), int(widget_y)):
                continue
            if start_x < x < end_x:
                return index
        return None

    def _event_widget_x(self, event: QMouseEvent) -> float:
        if hasattr(event, "position"):
            return float(event.position().x())
        return float(event.pos().x())

    def _event_widget_y(self, event: QMouseEvent) -> float:
        if hasattr(event, "position"):
            return float(event.position().y())
        return float(event.pos().y())

    def _update_hover_at_widget_x(self, widget_x: float) -> None:
        self._update_hover_at_pos(widget_x, None)

    def _update_hover_at_pos(self, widget_x: float, widget_y: float | None) -> None:
        if not self._can_interact():
            self._hover_time_ms = None
            if self._hovered_segment_uid:
                self._hovered_segment_uid = ""
                self.segmentHovered.emit("")
            self.update()
            return
        hover_time = self.x_to_time_ms(self._local_x_from_widget_x(widget_x))
        body_index = self._hit_segment_body(widget_x, widget_y)
        hover_uid = ""
        if body_index is not None and 0 <= body_index < len(self._segment_items):
            hover_uid = self._segment_items[body_index]["uid"]
        if hover_uid != self._hovered_segment_uid:
            self._hovered_segment_uid = hover_uid
            self.segmentHovered.emit(hover_uid)
        if hover_time != self._hover_time_ms:
            self._hover_time_ms = hover_time
            self.update()

    def _clear_hover(self) -> None:
        self._hover_time_ms = None
        if self._hovered_segment_uid:
            self._hovered_segment_uid = ""
            self.segmentHovered.emit("")
        self.unsetCursor()
        self.update()

    def _cancel_drag(self) -> None:
        self._drag_mode = None
        self._drag_index = None
        self._drag_anchor_ms = None
        self._drag_preview = None
        self._last_endpoint_emit = None
        self._timeline_resize_active = False

    def _begin_interaction_at_widget_x(self, widget_x: float) -> bool:
        return self._begin_interaction_at_pos(widget_x, None)

    def _begin_interaction_at_pos(self, widget_x: float, widget_y: float | None) -> bool:
        if widget_y is not None and self._hit_timeline_grip(int(widget_x), int(widget_y)):
            self._drag_mode = "timeline_resize"
            self._timeline_resize_active = True
            self._timeline_resize_start_y = int(widget_y)
            self._timeline_resize_start_height = self._timeline_outer_rect().height()
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            return True
        if not self._can_interact():
            return False
        if widget_y is not None and not self._timeline_area_rect().contains(int(widget_x), int(widget_y)):
            self._cancel_drag()
            return False
        endpoint = self._hit_endpoint(widget_x, widget_y)
        if endpoint is not None:
            index, side = endpoint
            if not (0 <= index < len(self._segments)):
                return False
            start_ms, end_ms = self._segments[index]
            if end_ms <= start_ms:
                return False
            self._drag_mode = side
            self._drag_index = index
            self._drag_preview = None
            self._last_endpoint_emit = None
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self.segmentEndpointDragStarted.emit(self._segment_items[index]["uid"], side)
            return True
        if self._hit_segment_body(widget_x, widget_y) is not None:
            self._cancel_drag()
            index = self._hit_segment_body(widget_x, widget_y)
            if index is not None and 0 <= index < len(self._segment_items):
                uid = self._segment_items[index]["uid"]
                self._selected_segment_uid = uid
                self.segmentSelected.emit(uid)
            return False
        if self._selected_segment_uid:
            self._selected_segment_uid = ""
            self.emptySelected.emit()
        self._drag_mode = "create"
        self._drag_index = None
        self._drag_anchor_ms = self.x_to_time_ms(self._local_x_from_widget_x(widget_x))
        self._drag_preview = None
        self._last_endpoint_emit = None
        return True

    def _is_quick_draft_event(self, event: QMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        try:
            return event.modifiers() == Qt.KeyboardModifier.ControlModifier
        except Exception:
            return False

    def _request_timeline_quick_draft(self, widget_x: float, widget_y: float) -> bool:
        if not self._can_interact() or not self._timeline_area_rect().contains(int(widget_x), int(widget_y)):
            return False
        if self._hit_endpoint(widget_x, widget_y) is not None:
            return False
        if self._hit_segment_body(widget_x, widget_y) is not None:
            return False
        self.timeline_quick_draft_requested.emit(self.x_to_time_ms(self._local_x_from_widget_x(widget_x)))
        return True

    def _update_interaction_at_widget_x(self, widget_x: float) -> None:
        self._update_interaction_at_pos(widget_x, None)

    def _update_interaction_at_pos(self, widget_x: float, _widget_y: float | None) -> None:
        if not self._can_interact() or self._drag_mode is None:
            if self._drag_mode == "timeline_resize" and _widget_y is not None:
                dy = int(_widget_y) - int(self._timeline_resize_start_y)
                self._set_timeline_user_height(self._timeline_resize_start_height + dy)
            return
        if self._drag_mode == "timeline_resize":
            if _widget_y is not None:
                dy = int(_widget_y) - int(self._timeline_resize_start_y)
                self._set_timeline_user_height(self._timeline_resize_start_height + dy)
            return
        current_ms = self.x_to_time_ms(self._local_x_from_widget_x(widget_x))
        if self._drag_mode == "create":
            anchor = self._drag_anchor_ms
            if anchor is None:
                return
            start_ms = min(anchor, current_ms)
            end_ms = max(anchor, current_ms)
            self._drag_preview = (start_ms, end_ms) if end_ms > start_ms else None
            self.update()
            return
        if self._drag_mode in ("start", "end") and self._drag_index is not None:
            self._apply_endpoint_drag(current_ms)

    def _finish_interaction_at_widget_x(self, widget_x: float) -> None:
        self._finish_interaction_at_pos(widget_x, None)

    def _finish_interaction_at_pos(self, widget_x: float, widget_y: float | None) -> None:
        if self._drag_mode == "timeline_resize":
            self._update_interaction_at_pos(widget_x, widget_y)
            self._cancel_drag()
            self.unsetCursor()
            self.update()
            return
        if not self._can_interact() or self._drag_mode is None:
            self._cancel_drag()
            self.unsetCursor()
            self.update()
            return
        self._update_interaction_at_pos(widget_x, widget_y)
        commit_endpoint = self._drag_mode in ("start", "end")
        if self._drag_mode == "create" and self._drag_preview is not None:
            start_ms, end_ms = self._drag_preview
            if end_ms - start_ms >= WAVEFORM_MIN_SEGMENT_MS:
                self.segmentCreated.emit(int(start_ms), int(end_ms))
        elif commit_endpoint:
            self.segmentEndpointCommitted.emit()
            if self._drag_index is not None and self._drag_index < len(self._segment_items):
                self.segmentEndpointDragFinished.emit(self._segment_items[self._drag_index]["uid"], self._drag_mode)
        self._cancel_drag()
        self.unsetCursor()
        self.update()

    def _apply_endpoint_drag(self, current_ms: int) -> None:
        index = self._drag_index
        if index is None or not (0 <= index < len(self._segments)):
            return
        start_ms, end_ms = self._segments[index]
        duration_ms = self._duration_ms()
        if self._drag_mode == "start":
            new_start = max(0, min(int(current_ms), int(end_ms) - WAVEFORM_MIN_SEGMENT_MS))
            new_end = int(end_ms)
        else:
            new_start = int(start_ms)
            new_end = min(duration_ms, max(int(current_ms), int(start_ms) + WAVEFORM_MIN_SEGMENT_MS))
        if new_end - new_start < WAVEFORM_MIN_SEGMENT_MS:
            return
        self._segments[index] = (new_start, new_end)
        emitted = (index, new_start, new_end)
        if emitted != self._last_endpoint_emit:
            self._last_endpoint_emit = emitted
            self.segmentEndpointChanged.emit(index, new_start, new_end)
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        widget_x = self._event_widget_x(event)
        widget_y = self._event_widget_y(event)
        if event.button() == Qt.MouseButton.LeftButton and self._hit_timeline_grip(int(widget_x), int(widget_y)):
            if self._begin_interaction_at_pos(widget_x, widget_y):
                event.accept()
                return
        if self._is_quick_draft_event(event):
            # Existing handles and blocks retain their normal interaction semantics.
            if self._hit_endpoint(widget_x, widget_y) is not None or self._hit_segment_body(widget_x, widget_y) is not None:
                self._begin_interaction_at_pos(widget_x, widget_y)
                event.accept()
                return
            elif self._request_timeline_quick_draft(widget_x, widget_y):
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton and self._begin_interaction_at_pos(widget_x, widget_y):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_mode is not None:
            self._update_interaction_at_pos(self._event_widget_x(event), self._event_widget_y(event))
            event.accept()
            return
        if self._hit_timeline_grip(int(self._event_widget_x(event)), int(self._event_widget_y(event))):
            self._timeline_grip_hover = True
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            self.update()
        elif self._can_interact() and self._hit_endpoint(self._event_widget_x(event), self._event_widget_y(event)) is not None:
            self._timeline_grip_hover = False
            self._update_hover_at_pos(self._event_widget_x(event), self._event_widget_y(event))
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self._timeline_grip_hover = False
            self._update_hover_at_pos(self._event_widget_x(event), self._event_widget_y(event))
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._timeline_grip_hover = False
        self._clear_hover()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode is not None:
            self._finish_interaction_at_pos(self._event_widget_x(event), self._event_widget_y(event))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._hit_timeline_grip(int(self._event_widget_x(event)), int(self._event_widget_y(event))):
            self.toggle_timeline_expanded()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        try:
            x = self._event_widget_x(event)
            y = self._event_widget_y(event)
        except Exception:
            try:
                x = float(event.position().x())
                y = float(event.position().y())
            except Exception:
                x = 0.0
                y = 0.0
        if self._timeline_outer_rect().contains(int(x), int(y)) and self._timeline_scroll_max() > 0:
            delta_y = 0
            try:
                pixel_delta = event.pixelDelta()
                delta_y = int(pixel_delta.y())
            except Exception:
                delta_y = 0
            if not delta_y:
                try:
                    angle_delta = event.angleDelta()
                    delta_y = int(angle_delta.y())
                except Exception:
                    delta_y = 0
            step = self.TIMELINE_LANE_HEIGHT + self.TIMELINE_LANE_GAP
            amount = -delta_y if abs(delta_y) < step else int(round(-delta_y / 120.0 * step))
            if amount == 0:
                amount = step if delta_y < 0 else -step
            if self._scroll_timeline_by(amount):
                try:
                    event.accept()
                except Exception:
                    pass
                return
        super().wheelEvent(event)

    def _draw_waveform_background(self, painter: QPainter, rect) -> None:
        painter.fillRect(rect, QColor(C_TIMELINE_BG))
        painter.setPen(QPen(QColor(C_BORDER), 1))
        painter.drawRect(rect)

        mid_y = rect.center().y()
        painter.setPen(QPen(QColor(C_LANE_SEPARATOR), 1))
        painter.drawLine(rect.left(), mid_y, rect.right(), mid_y)

    def _draw_ruler(self, painter: QPainter, rect, duration_ms: int) -> None:
        painter.fillRect(rect, QColor(C_CARD2))
        painter.setPen(QPen(QColor(C_LANE_SEPARATOR), 1))
        painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        painter.setPen(QColor(C_SEGMENT_BORDER))
        painter.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "0.000s")
        painter.drawText(
            rect.adjusted(6, 0, -6, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            format_duration_ms(duration_ms),
        )

    def _draw_timeline_background(self, painter: QPainter, rect) -> None:
        painter.fillRect(rect, QColor(C_TIMELINE_TRACK))
        painter.setPen(QPen(QColor(C_LANE_SEPARATOR), 1))
        painter.drawRect(rect)
        lane_count = max(1, len(self._segment_items))
        for index in range(lane_count):
            lane_rect = self._lane_rect(index)
            painter.fillRect(lane_rect, QColor(C_TIMELINE_BG) if index % 2 == 0 else QColor(C_CARD2))
            painter.setPen(QPen(QColor(C_LANE_SEPARATOR), 1))
            painter.drawLine(lane_rect.left(), lane_rect.bottom(), lane_rect.right(), lane_rect.bottom())

    def _draw_timeline_grip(self, painter: QPainter) -> None:
        grip = self._timeline_grip_rect()
        painter.fillRect(grip, QColor("#D1D5DB" if self._timeline_grip_hover or self._timeline_resize_active else C_BORDER2))
        painter.setPen(QPen(QColor(C_BORDER), 1))
        painter.drawLine(grip.left(), grip.top(), grip.right(), grip.top())
        center_x = grip.center().x()
        center_y = grip.center().y()
        painter.setPen(QPen(QColor(C_MUTED), 2))
        for offset in (-10, 0, 10):
            painter.drawLine(center_x + offset - 3, center_y, center_x + offset + 3, center_y)

    def _draw_waveform(self, painter: QPainter, rect, data: WaveformData) -> None:
        peaks = data.peaks
        mid_y = rect.center().y()
        painter.setPen(QPen(QColor(C_WAVEFORM), 1))
        height_half = max(1, rect.height() // 2 - 8)
        width = max(1, rect.width())
        for x_offset in range(width):
            index = min(len(peaks) - 1, int(x_offset * len(peaks) / width))
            lo, hi = peaks[index]
            y1 = mid_y - int(max(0.0, hi) * height_half)
            y2 = mid_y - int(min(0.0, lo) * height_half)
            if y2 < y1:
                y1, y2 = y2, y1
            painter.drawLine(rect.left() + x_offset, y1, rect.left() + x_offset, y2)

    def _draw_complete_segments(self, painter: QPainter, rect) -> None:
        group_colors = (C_SEGMENT_FILL, C_SEGMENT_ALT_FILL, "#CCFBF1", "#EDE9FE")
        group_index: dict[tuple, int] = {}
        link_index: dict[str, int] = {}
        for item in self._segment_items:
            group_key = item.get("group_key")
            if group_key not in group_index:
                group_index[group_key] = len(group_index)
            link_group_id = str(item.get("link_group_id") or "")
            if link_group_id and link_group_id not in link_index:
                link_index[link_group_id] = len(link_index)
            color = QColor(group_colors[group_index[group_key] % len(group_colors)])
            start_ms = item["start"]
            end_ms = item["end"]
            clip_rect = self._segment_clip_rect(rect, int(item.get("index", 0)), start_ms, end_ms)
            uid = item["uid"]
            selected = uid == self._selected_segment_uid
            hovered = uid == self._hovered_segment_uid
            fill_alpha = 98 if selected else 82 if hovered else 64
            if selected:
                border_color = QColor(C_SELECTED)
            elif hovered:
                border_color = QColor(C_HOVERED)
            elif link_group_id:
                link_colors = ("#2563EB", "#0F766E", "#7C3AED", "#0369A1")
                border_color = QColor(link_colors[link_index[link_group_id] % len(link_colors)])
            elif item.get("join_available"):
                border_color = QColor("#38BDF8")
            else:
                border_color = QColor(C_SEGMENT_BORDER)
            border_width = 3 if selected else 2 if hovered else 1
            painter.fillRect(clip_rect.adjusted(1, 2, -1, -2), QColor(color.red(), color.green(), color.blue(), fill_alpha))
            painter.setPen(QPen(border_color, border_width))
            painter.drawRect(clip_rect.adjusted(1, 2, -2, -3))
            if link_group_id:
                painter.fillRect(QRect(clip_rect.left() + 2, clip_rect.top() + 2, 5, max(4, clip_rect.height() - 5)), border_color)
            elif item.get("join_available"):
                painter.setPen(QPen(border_color, 1))
                painter.drawLine(clip_rect.left() + 6, clip_rect.top() + 4, clip_rect.left() + 18, clip_rect.top() + 4)
            handle_w = 4
            painter.fillRect(QRect(clip_rect.left() + 2, clip_rect.top() + 4, handle_w, max(4, clip_rect.height() - 8)), border_color)
            painter.fillRect(QRect(clip_rect.right() - handle_w - 1, clip_rect.top() + 4, handle_w, max(4, clip_rect.height() - 8)), border_color)
            label = f"{int(item.get('index', 0)) + 1}  {format_duration_ms(start_ms)}-{format_duration_ms(end_ms)}"
            painter.setPen(QColor(C_TEXT))
            painter.drawText(clip_rect.adjusted(10, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

    def _draw_drag_preview(self, painter: QPainter, rect) -> None:
        if self._drag_preview is None:
            return
        start_ms, end_ms = self._drag_preview
        start_x = rect.left() + self.time_ms_to_x(start_ms)
        end_x = rect.left() + self.time_ms_to_x(end_ms)
        if end_x <= start_x:
            return
        painter.fillRect(
            QRect(start_x, rect.top() + 4, end_x - start_x, max(6, rect.height() - 8)),
            QColor(37, 99, 235, 70),
        )
        painter.setPen(QPen(QColor(C_SELECTED), 2))
        painter.drawLine(start_x, rect.top() + 2, start_x, rect.bottom() - 2)
        painter.drawLine(end_x, rect.top() + 2, end_x, rect.bottom() - 2)

    def _draw_draft_label(self, painter: QPainter, rect, anchor_x: int, text: str, color: QColor, side: str) -> None:
        label_w = 104
        label_h = 20
        if side == "right":
            label_x = min(max(anchor_x + 8, rect.left() + 4), rect.right() - label_w)
        else:
            label_x = max(min(anchor_x - label_w - 8, rect.right() - label_w), rect.left() + 4)
        label_rect = QRect(int(label_x), rect.top() + 7, label_w, label_h)
        painter.fillRect(label_rect, QColor(color.red(), color.green(), color.blue(), 218))
        painter.setPen(QPen(QColor("#FFFFFF"), 1))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_draft_segments(self, painter: QPainter, rect) -> None:
        if not self._draft_segments:
            return
        mid_y = rect.center().y()
        guide_len = max(72, rect.width() // 5)
        for draft in self._draft_segments:
            anchor_x = rect.left() + self.time_ms_to_x(draft["time_ms"])
            is_start = draft["kind"] == "start"
            color = QColor(C_DRAFT_START) if is_start else QColor(C_DRAFT_END)
            fill = QColor(color.red(), color.green(), color.blue(), 30)
            guide_pen = QPen(QColor(color.red(), color.green(), color.blue(), 210), 2)
            try:
                guide_pen.setStyle(Qt.PenStyle.DashLine)
            except Exception:
                pass

            if is_start:
                guide_end = min(rect.right(), anchor_x + guide_len)
                if guide_end > anchor_x:
                    painter.fillRect(QRect(anchor_x, rect.top(), guide_end - anchor_x, rect.height()), fill)
                arrow_x = max(anchor_x, guide_end)
                label_text = f"起点 {format_duration_ms(draft['time_ms'])}"
                label_side = "right"
                painter.setPen(guide_pen)
                painter.drawLine(anchor_x, mid_y, guide_end, mid_y)
                painter.drawLine(arrow_x - 9, mid_y - 6, arrow_x, mid_y)
                painter.drawLine(arrow_x - 9, mid_y + 6, arrow_x, mid_y)
            else:
                guide_start = max(rect.left(), anchor_x - guide_len)
                if anchor_x > guide_start:
                    painter.fillRect(QRect(guide_start, rect.top(), anchor_x - guide_start, rect.height()), fill)
                arrow_x = min(anchor_x, guide_start)
                label_text = f"终点 {format_duration_ms(draft['time_ms'])}"
                label_side = "left"
                painter.setPen(guide_pen)
                painter.drawLine(guide_start, mid_y, anchor_x, mid_y)
                painter.drawLine(arrow_x + 9, mid_y - 6, arrow_x, mid_y)
                painter.drawLine(arrow_x + 9, mid_y + 6, arrow_x, mid_y)

            painter.setPen(QPen(color, 3))
            painter.drawLine(anchor_x, rect.top() + 2, anchor_x, rect.bottom() - 2)
            try:
                painter.setBrush(color)
            except Exception:
                pass
            painter.drawEllipse(QPoint(anchor_x, mid_y), 5, 5)
            try:
                painter.setBrush(Qt.BrushStyle.NoBrush)
            except Exception:
                pass
            self._draw_draft_label(painter, rect, anchor_x, label_text, color, label_side)

    def _draw_quick_draft_anchor(self, painter: QPainter, rect) -> None:
        anchor = self._quick_draft_anchor_ms
        if anchor is None:
            return
        anchor_x = rect.left() + self.time_ms_to_x(anchor)
        color = QColor(C_DRAFT_START)
        pen = QPen(color, 2)
        try:
            pen.setStyle(Qt.PenStyle.DashLine)
        except Exception:
            pass
        painter.setPen(pen)
        painter.drawLine(anchor_x, rect.top() + 2, anchor_x, rect.bottom() - 2)
        self._draw_draft_label(
            painter,
            rect,
            anchor_x,
            f"快速起点 {format_duration_ms(anchor)}",
            color,
            "right",
        )
        painter.setPen(QPen(QColor(C_MUTED), 1))
        painter.drawText(
            rect.adjusted(6, max(28, rect.height() - 24), -6, -4),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            "Ctrl+单击设置终点 · Esc取消",
        )

    def _draw_hover_cursor(self, painter: QPainter, rect) -> None:
        if self._hover_time_ms is None:
            return
        hover_x = rect.left() + self.time_ms_to_x(self._hover_time_ms)
        painter.setPen(QPen(QColor(C_TEXT2), 1))
        painter.drawLine(hover_x, rect.top(), hover_x, rect.bottom())
        painter.drawText(
            rect.adjusted(6, 4, -6, -4),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
            format_duration_ms(self._hover_time_ms),
        )

    def _draw_playback_head(self, painter: QPainter, waveform_rect, timeline_rect) -> None:
        if self._playback_position_ms is None: return
        x = waveform_rect.left() + self.time_ms_to_x(self._playback_position_ms)
        painter.setPen(QPen(QColor(C_ACCENT), 2))
        painter.drawLine(x, waveform_rect.top(), x, waveform_rect.bottom())
        painter.drawLine(x, timeline_rect.top(), x, timeline_rect.bottom())

    def _draw_duration_label(self, painter: QPainter, rect, duration_ms: int) -> None:
        painter.setPen(QColor(C_LABEL))
        painter.drawText(
            rect.adjusted(6, 4, -6, -4),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
            format_duration_ms(duration_ms),
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        waveform_rect = self._waveform_area_rect()
        ruler_rect = self._ruler_rect()
        timeline_rect = self._timeline_area_rect()
        if waveform_rect.width() <= 0 or waveform_rect.height() <= 0:
            return

        self._draw_waveform_background(painter, waveform_rect)
        try:
            painter.save()
            painter.setClipRect(timeline_rect)
        except Exception:
            pass
        self._draw_timeline_background(painter, timeline_rect)
        try:
            painter.restore()
        except Exception:
            pass
        self._draw_timeline_grip(painter)

        data = self._waveform
        if self._state != "ready" or data is None or not data.peaks or data.duration_ms <= 0:
            painter.setPen(QColor(C_MUTED))
            painter.drawText(waveform_rect, Qt.AlignmentFlag.AlignCenter, self._message)
            return

        duration_ms = max(1, int(data.duration_ms))
        self._draw_waveform(painter, waveform_rect, data)
        self._draw_ruler(painter, ruler_rect, duration_ms)
        try:
            painter.save()
            painter.setClipRect(timeline_rect)
        except Exception:
            pass
        self._draw_complete_segments(painter, timeline_rect)
        self._draw_drag_preview(painter, timeline_rect)
        self._draw_draft_segments(painter, timeline_rect)
        self._draw_quick_draft_anchor(painter, timeline_rect)
        try:
            painter.restore()
        except Exception:
            pass
        self._draw_hover_cursor(painter, waveform_rect)
        self._draw_playback_head(painter, waveform_rect, timeline_rect)
        self._draw_duration_label(painter, waveform_rect, duration_ms)
