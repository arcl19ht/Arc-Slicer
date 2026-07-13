"""Painted square checkbox for form and export choices."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from arc_slicer.theme import C_ACCENT, C_ACCENT_H, C_MUTED


class SemanticCheckBox(QWidget):
    """A checkbox with a guaranteed visible square and check mark."""

    toggled = pyqtSignal(bool)
    clicked = pyqtSignal(bool)
    BOX_SIZE = 17

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = str(text)
        self._checked = False
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(self._text)
        self.setMinimumHeight(24)

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
            width = self.fontMetrics().horizontalAdvance(self._text)
        except Exception:
            width = max(48, len(self._text) * 14)
        return QSize(self.BOX_SIZE + 8 + width, 24)

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
        y = max(2, (rect.height() - self.BOX_SIZE) // 2)
        box = rect.adjusted(0, y, -(rect.width() - self.BOX_SIZE), -(y + 1))
        if not self.isEnabled():
            fill, border, text = "#EAECF0", "#98A2B3", "#667085"
        elif self._checked:
            fill, border, text = C_ACCENT, C_ACCENT_H, "#344054"
        else:
            fill, border, text = "#FFFFFF", (C_ACCENT if self._hovered else C_MUTED), "#344054"
        painter.setBrush(QColor(fill))
        painter.setPen(QPen(QColor(border), 2 if self.hasFocus() else 1))
        painter.drawRoundedRect(box, 3, 3)
        if self._checked:
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.drawLine(box.left() + 4, box.center().y(), box.left() + 7, box.bottom() - 4)
            painter.drawLine(box.left() + 7, box.bottom() - 4, box.right() - 3, box.top() + 4)
        painter.setPen(QColor(text))
        painter.drawText(self.BOX_SIZE + 8, 0, max(1, rect.width() - self.BOX_SIZE - 8), rect.height(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
