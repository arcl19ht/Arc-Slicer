"""Combo box with a reliable, theme-coloured disclosure chevron."""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QComboBox

from arc_slicer.theme import C_MUTED, C_TEXT2


class VisualComboBox(QComboBox):
    """Keep the native combo behavior while drawing a visible chevron."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = C_TEXT2 if self.isEnabled() else C_MUTED
        painter.setPen(QPen(QColor(color), 1.6))
        center_x = self.width() - 15
        center_y = self.height() // 2
        painter.drawLine(center_x - 4, center_y - 2, center_x, center_y + 2)
        painter.drawLine(center_x, center_y + 2, center_x + 4, center_y - 2)
