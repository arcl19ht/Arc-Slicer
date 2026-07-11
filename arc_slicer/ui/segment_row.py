"""Segment card widget."""
from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt, QEvent, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from arc_slicer.segments import (
    TIME_INPUT_PATTERN, _speed_text, effective_segment_speed, normalize_link_group_id,
    normalize_speed_override_value, validate_speed_value,
)
from arc_slicer.aff import _arc_cut_info_content
from arc_slicer.theme import (
    C_ACCENT, C_ACCENT_H, C_BADGE_BG, C_BORDER, C_BORDER2, C_CARD, C_CARD2,
    C_ERR, C_HOVERED, C_INPUT_BD, C_INPUT_BG, C_LABEL, C_MUTED,
    C_SEGMENT_BORDER, C_SELECTED, C_TEXT, C_TEXT2,
)

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
            f"QFrame#arcCutInfoCard {{ background: {C_CARD}; border: 1px solid {C_BORDER}; "
            f"border-radius: 8px; }}"
            f"QLabel {{ color: {C_TEXT}; background: transparent; border: none; }}"
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(31, 41, 55, 32))
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
    copy_requested = pyqtSignal(object)
    field_committed = pyqtSignal(object, str)
    enter_pressed = pyqtSignal(object, str)
    hovered = pyqtSignal(object)
    unhovered = pyqtSignal(object)
    selected = pyqtSignal(object)
    unlink_requested = pyqtSignal(object)
    join_requested = pyqtSignal(object)
    join_previewed = pyqtSignal(object)
    join_unpreviewed = pyqtSignal(object)

    def __init__(
        self,
        index: int,
        s: int | None,
        e: int | None,
        parent=None,
        speed_override: float | None = None,
        default_speed: float = 1.0,
        uid: str | None = None,
        link_group_id=None,
    ):
        super().__init__(parent)
        self.s_val = s
        self.e_val = e
        self.uid = str(uid or f"seg_{uuid.uuid4().hex[:10]}")
        self.link_group_id = normalize_link_group_id(link_group_id)
        self.created_order = 0
        self._is_hovered = False
        self._is_selected = False
        self._group_index = 0
        self._group_count = 1
        self._link_group_active = False
        self._join_group_available = False
        self._join_preview = False
        self._default_speed = validate_speed_value(float(default_speed))
        self._initial_speed_override = normalize_speed_override_value(speed_override)
        self._setup_ui(index, s, e)
        self._refresh_card_style()

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

        btn_copy = QPushButton("复制此片段")
        btn_copy.setObjectName("btnSegCopy")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.setStyleSheet(
            "QPushButton {"
            f"background: {C_CARD2}; border: 1px solid {C_BORDER2}; border-radius: 7px; "
            f"color: {C_TEXT2}; font-size: 11px; font-weight: 650; padding: 4px 8px;"
            "}"
            f"QPushButton:hover {{ background: #EFF6FF; border-color: {C_ACCENT}; }}"
        )
        title_row.addWidget(btn_copy, 0, Qt.AlignmentFlag.AlignVCenter)

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
        arrow.setStyleSheet(f"color: {C_LABEL}; font-size: 15px; background: transparent; border: none;")
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

        speed_col = QWidget()
        speed_col.setStyleSheet("background: transparent; border: none;")
        speed_lay = QVBoxLayout(speed_col)
        speed_lay.setContentsMargins(0, 0, 0, 0)
        speed_lay.setSpacing(5)
        speed_label_row = QHBoxLayout()
        speed_label_row.setContentsMargins(0, 0, 0, 0)
        speed_label_row.setSpacing(4)
        self._speed_sub_label = self._make_segment_field_label("倍速")
        self._speed_unit_label = self._make_segment_unit_label("override")
        speed_label_row.addWidget(self._speed_sub_label)
        speed_label_row.addWidget(self._speed_unit_label)
        speed_label_row.addStretch()
        speed_lay.addLayout(speed_label_row)
        self._speed_override = QLineEdit("" if self._initial_speed_override is None else _speed_text(self._initial_speed_override))
        self._speed_override.setPlaceholderText(self._speed_placeholder())
        self._speed_override.setMinimumWidth(132)
        self._speed_override.setStyleSheet(self._segment_time_input_qss())
        speed_lay.addWidget(self._speed_override)
        input_row.addWidget(speed_col, 1)
        input_row.addStretch(1)
        lay.addLayout(input_row)

        self._start_error = self._make_time_error_label()
        self._end_error = self._make_time_error_label()
        self._speed_error = self._make_time_error_label()
        self._group_label = QLabel("")
        self._group_label.setStyleSheet(
            f"font-size: 10px; font-weight: 700; color: {C_SEGMENT_BORDER}; "
            f"background: {C_CARD2}; border: 1px solid {C_BORDER2}; border-radius: 6px; padding: 2px 7px;"
        )
        self._group_label.hide()
        self._link_action_btn = QPushButton("")
        self._link_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._link_action_btn.setFixedHeight(20)
        self._link_action_btn.setStyleSheet(
            "QPushButton {"
            "background: #F8FAFC; "
            f"border: 1px solid {C_BORDER2}; "
            "border-radius: 6px; "
            f"color: {C_TEXT2}; "
            "font-size: 10px; "
            "font-weight: 700; "
            "padding: 1px 7px;"
            "}"
            f"QPushButton:hover {{ background: #EFF6FF; border-color: {C_ACCENT}; color: {C_ACCENT_H}; }}"
        )
        self._link_action_btn.hide()
        self._link_action_btn.clicked.connect(self._on_link_action_clicked)
        self._link_action_btn.enterEvent = self._link_action_enter
        self._link_action_btn.leaveEvent = self._link_action_leave
        self._end_cap_btn = QPushButton("")
        self._end_cap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._end_cap_btn.setFixedHeight(20)
        self._end_cap_btn.setStyleSheet(
            "QPushButton {"
            "background: #EFF6FF; "
            f"border: 1px solid {C_ACCENT}; "
            "border-radius: 6px; "
            f"color: {C_ACCENT_H}; "
            "font-size: 10px; "
            "font-weight: 700; "
            "padding: 1px 7px;"
            "}"
            "QPushButton:hover {"
            "background: #DBEAFE; "
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
        status_row.addWidget(self._speed_error)
        status_row.addWidget(self._group_label)
        status_row.addWidget(self._link_action_btn)

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
        self._speed_override.textChanged.connect(self._on_change)
        self._start.editingFinished.connect(lambda: self.field_committed.emit(self, "start"))
        self._end.editingFinished.connect(lambda: self.field_committed.emit(self, "end"))
        self._speed_override.editingFinished.connect(lambda: self.field_committed.emit(self, "speed"))
        self._start.returnPressed.connect(lambda: self.enter_pressed.emit(self, "start"))
        self._end.returnPressed.connect(lambda: self.enter_pressed.emit(self, "end"))
        self._speed_override.returnPressed.connect(lambda: self.enter_pressed.emit(self, "speed"))
        btn_copy.clicked.connect(lambda: self.copy_requested.emit(self))
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
            f"background: {C_CARD2};"
            "}"
        )

    def _speed_placeholder(self) -> str:
        return f"留空继承默认 {_speed_text(self._default_speed)}×"

    def _refresh_card_style(self) -> None:
        if getattr(self, "_is_selected", False):
            bg = "#EFF6FF"
            border = C_SELECTED
            width = 2
        elif getattr(self, "_is_hovered", False):
            bg = "#F8FAFC"
            border = C_HOVERED
            width = 1
        elif getattr(self, "_group_count", 1) > 1:
            bg = "#F8FAFC"
            border = C_BORDER
            width = 1
        elif getattr(self, "_link_group_active", False):
            bg = "#F8FAFC"
            border = C_ACCENT
            width = 1
        elif getattr(self, "_join_preview", False):
            bg = "#F0F9FF"
            border = C_HOVERED
            width = 1
        else:
            bg = C_CARD
            border = C_BORDER2
            width = 1
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; border: {width}px solid {border}; border-radius: 12px; }}"
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
        self._speed_override.setPlaceholderText(self._speed_placeholder())
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
            try:
                speed = self.effective_speed()
                self._dur.setText(f"{d / speed / 1000:.2f}s")
            except ValueError:
                self._dur.setText(f"{d/1000:.2f}s")
            self._dur.setStyleSheet(
                f"font-family: 'Consolas','Courier New',monospace; font-size: 13px; "
                f"color: {C_LABEL}; background: transparent; border: none;"
            )
            self._refresh_card_style()

    def update_index(self, index: int):
        self._badge.setText(str(index))

    def set_interaction_state(self, selected: bool = False, hovered: bool = False) -> None:
        self._is_selected = bool(selected)
        self._is_hovered = bool(hovered)
        self._refresh_card_style()

    def set_visual_group(self, group_index: int = 0, group_count: int = 1) -> None:
        self._group_index = int(group_index)
        self._group_count = max(1, int(group_count))
        if self._group_count > 1:
            self._group_label.setText(f"同区间 · {self._group_count} 个速度")
            self._group_label.show()
        else:
            self._group_label.hide()
        self._refresh_card_style()

    def set_link_group_state(
        self,
        active: bool = False,
        member_count: int = 1,
        join_available: bool = False,
        join_preview: bool = False,
        join_mode: str = "",
    ) -> None:
        self._link_group_active = bool(active)
        self._join_group_available = bool(join_available)
        self._join_preview = bool(join_preview)
        self._join_mode = str(join_mode or "")
        if self._link_group_active:
            self._group_label.setText(f"已级联 · {max(2, int(member_count))} 个")
            self._group_label.show()
            self._link_action_btn.setText("断开")
            self._link_action_btn.setToolTip("从当前级联组断开")
            self._link_action_btn.show()
        elif self._join_group_available:
            if self._join_mode == "create_same_interval":
                self._link_action_btn.setText("级联同区间")
                self._link_action_btn.setToolTip("将同区间未级联片段组成新的级联组")
            else:
                self._link_action_btn.setText("加入级联")
                self._link_action_btn.setToolTip("加入相同起止时间的已有级联组")
            self._link_action_btn.show()
        else:
            self._link_action_btn.setText("")
            self._link_action_btn.setToolTip("")
            self._link_action_btn.hide()
        self._refresh_card_style()

    def _on_link_action_clicked(self) -> None:
        if getattr(self, "_link_group_active", False):
            self.unlink_requested.emit(self)
        elif getattr(self, "_join_group_available", False):
            self.join_requested.emit(self)

    def _link_action_enter(self, event) -> None:
        if getattr(self, "_join_group_available", False):
            self._join_preview = True
            self._refresh_card_style()
            self.join_previewed.emit(self)
        try:
            QPushButton.enterEvent(self._link_action_btn, event)
        except Exception:
            pass

    def _link_action_leave(self, event) -> None:
        if getattr(self, "_join_group_available", False):
            self._join_preview = False
            self._refresh_card_style()
            self.join_unpreviewed.emit(self)
        try:
            QPushButton.leaveEvent(self._link_action_btn, event)
        except Exception:
            pass

    def start_text(self) -> str:
        return self._start.text()

    def end_text(self) -> str:
        return self._end.text()

    def speed_override_text(self) -> str:
        return self._speed_override.text()

    def speed_override_value(self) -> float | None:
        return normalize_speed_override_value(self._speed_override.text())

    def effective_speed(self) -> float:
        return effective_segment_speed(self._default_speed, self.speed_override_value())

    def set_default_speed(self, default_speed: float) -> None:
        self._default_speed = validate_speed_value(float(default_speed))
        self._speed_override.setPlaceholderText(self._speed_placeholder())
        self._update_dur()

    def set_speed_error(self, message: str = "") -> None:
        self._speed_error.setText(message)
        self._speed_error.setToolTip(message)
        self._speed_error.setVisible(bool(message))

    def clear_speed_error(self) -> None:
        self.set_speed_error("")

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
        if field == "speed":
            widget = self._speed_override
        else:
            widget = self._start if field == "start" else self._end
        widget.setFocus()
        widget.selectAll()

    def set_end_text(self, end_ms: int) -> None:
        self._end.setText(str(int(end_ms)))
        self._on_change()

    def set_time_range(self, start_ms: int, end_ms: int) -> None:
        self._start.setText(str(int(start_ms)))
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
        override = self.speed_override_value()
        return {
            "uid": self.uid,
            "s": self.s_val,
            "e": self.e_val,
            "speed_override": override,
            "link_group_id": normalize_link_group_id(getattr(self, "link_group_id", None)),
        }

    def enterEvent(self, event):
        self.hovered.emit(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.unhovered.emit(self)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        self.selected.emit(self)
        super().mousePressEvent(event)
