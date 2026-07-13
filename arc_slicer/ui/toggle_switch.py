"""A small, accessible toggle for immediate runtime behaviors."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from arc_slicer.theme import C_ACCENT, C_ACCENT_H, C_BORDER, C_MUTED


class ToggleSwitch(QWidget):
    """Clickable label plus a painted track and moving thumb.

    It intentionally mirrors the QCheckBox subset used by MainWindow so the
    surrounding playback and sorting behavior remains unchanged.
    """

    toggled = pyqtSignal(bool)
    clicked = pyqtSignal(bool)

    TRACK_WIDTH = 40
    TRACK_HEIGHT = 22
    THUMB_SIZE = 16

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = str(text)
        self._checked = False
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(self._text)
        self.setToolTip(self._text)
        self.setMinimumHeight(self.TRACK_HEIGHT + 4)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = str(text)
        self.setAccessibleName(self._text)
        self.updateGeometry()
        self.update()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.toggled.emit(checked)
        self.update()

    def sizeHint(self) -> QSize:
        try:
            text_width = self.fontMetrics().horizontalAdvance(self._text)
        except Exception:
            text_width = max(48, len(self._text) * 14)
        return QSize(self.TRACK_WIDTH + 8 + text_width, self.TRACK_HEIGHT + 4)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)
            self.clicked.emit(self._checked)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select) and self.isEnabled():
            self.setChecked(not self._checked)
            self.clicked.emit(self._checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        track_y = max(2, (rect.height() - self.TRACK_HEIGHT) // 2)
        track = rect.adjusted(0, track_y, -(rect.width() - self.TRACK_WIDTH), -(track_y + 1))
        if not self.isEnabled():
            track_color, border_color, thumb_color = "#D0D5DD", "#98A2B3", "#F2F4F7"
        elif self._checked:
            track_color, border_color, thumb_color = C_ACCENT, C_ACCENT_H, "#FFFFFF"
        else:
            track_color, border_color, thumb_color = "#98A2B3", C_MUTED, "#FFFFFF"
        painter.setBrush(QColor(track_color))
        painter.setPen(QPen(QColor(border_color), 2 if self.hasFocus() else 1))
        painter.drawRoundedRect(track, self.TRACK_HEIGHT // 2, self.TRACK_HEIGHT // 2)
        margin = 3
        thumb_x = track.right() - margin - self.THUMB_SIZE + 1 if self._checked else track.left() + margin
        thumb_y = track.top() + (self.TRACK_HEIGHT - self.THUMB_SIZE) // 2
        painter.setBrush(QColor(thumb_color))
        painter.setPen(QPen(QColor("#667085" if not self._checked else "#FFFFFF"), 1))
        painter.drawEllipse(thumb_x, thumb_y, self.THUMB_SIZE, self.THUMB_SIZE)
        painter.setPen(QColor("#344054" if self.isEnabled() else "#667085"))
        painter.drawText(self.TRACK_WIDTH + 8, 0, max(1, rect.width() - self.TRACK_WIDTH - 8), rect.height(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
