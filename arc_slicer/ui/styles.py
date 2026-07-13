"""Single authoritative application stylesheet for Arc Slicer."""
from __future__ import annotations

from arc_slicer.theme import (
    C_ACCENT, C_ACCENT_H, C_ACCENT_P, C_ACCENT_SOFT, C_BG, C_BORDER,
    C_BORDER2, C_CARD, C_CARD2, C_ERR, C_INPUT_BD, C_INPUT_BG, C_LABEL,
    C_MUTED, C_TEXT, C_TEXT2,
)


def application_qss() -> str:
    """Return QSS that distinguishes data, inputs, actions, and states."""
    return f"""
QWidget {{ font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; color: {C_TEXT}; }}
QMainWindow, QWidget#root {{ background: {C_BG}; }}
QLabel {{ background: transparent; border: none; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #98A2B3; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #667085; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QLineEdit, QComboBox {{ background: {C_INPUT_BG}; border: 1px solid {C_INPUT_BD}; border-radius: 7px; color: {C_TEXT}; min-height: 20px; padding: 7px 10px; }}
QLineEdit:hover, QComboBox:hover {{ border-color: #667085; }}
QLineEdit:focus, QComboBox:focus {{ border: 2px solid {C_ACCENT}; padding: 6px 9px; }}
QLineEdit:disabled, QComboBox:disabled {{ background: #F2F4F7; color: {C_MUTED}; border-color: {C_BORDER}; }}
QComboBox {{ padding-right: 30px; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{ background: {C_CARD}; border: 1px solid {C_INPUT_BD}; selection-background-color: {C_ACCENT_SOFT}; selection-color: {C_TEXT}; padding: 4px; outline: none; }}

QPushButton {{ background: #F2F4F7; color: {C_TEXT2}; border: 1px solid {C_INPUT_BD}; border-radius: 7px; font-weight: 650; min-height: 22px; padding: 7px 12px; }}
QPushButton:hover {{ background: #EAECF0; border-color: #667085; }}
QPushButton:pressed {{ background: #D0D5DD; }}
QPushButton:focus {{ border: 2px solid {C_ACCENT}; padding: 6px 11px; }}
QPushButton:disabled {{ background: #EAECF0; color: #667085; border-color: #98A2B3; }}
QPushButton#btnRun, QPushButton#btnPrimary, QPushButton#btnPlayback {{ background: {C_ACCENT}; color: white; border-color: {C_ACCENT}; }}
QPushButton#btnRun:hover, QPushButton#btnPrimary:hover, QPushButton#btnPlayback:hover {{ background: {C_ACCENT_H}; border-color: {C_ACCENT_H}; }}
QPushButton#btnRun:pressed, QPushButton#btnPrimary:pressed, QPushButton#btnPlayback:pressed {{ background: {C_ACCENT_P}; border-color: {C_ACCENT_P}; }}
QPushButton#btnRun:disabled, QPushButton#btnPrimary:disabled, QPushButton#btnPlayback:disabled {{ background: #B2CCFF; color: #FFFFFF; border-color: #98A2B3; }}
QPushButton#btnAdd, QPushButton#btnAddSegment {{ background: {C_ACCENT_SOFT}; color: {C_ACCENT}; border-color: #84ADFF; min-height: 30px; }}
QPushButton#btnAdd:hover, QPushButton#btnAddSegment:hover {{ background: #DCE8FF; border-color: {C_ACCENT}; }}
QPushButton#btnDel, QPushButton#btnDanger {{ background: #FEF3F2; color: {C_ERR}; border-color: #FDA29B; }}
QPushButton#btnDel:hover, QPushButton#btnDanger:hover {{ background: #FEE4E2; border-color: {C_ERR}; }}
QPushButton#btnDir, QPushButton#btnSecondary, QPushButton#btnSec, QPushButton#btnSegCopy {{ background: {C_CARD}; color: {C_TEXT2}; border-color: {C_INPUT_BD}; }}

QCheckBox {{ color: {C_TEXT2}; font-weight: 600; spacing: 8px; }}
QCheckBox::indicator {{ width: 34px; height: 18px; border-radius: 9px; background: #98A2B3; border: 1px solid #667085; }}
QCheckBox::indicator:checked {{ background: {C_ACCENT}; border-color: {C_ACCENT}; }}
QCheckBox::indicator:hover {{ border: 2px solid {C_TEXT2}; }}
QCheckBox::indicator:checked:hover {{ border-color: {C_ACCENT_P}; }}
QCheckBox::indicator:disabled {{ background: #D0D5DD; border-color: #98A2B3; }}
QCheckBox::indicator:focus {{ border: 2px solid {C_ACCENT}; }}

QFrame#songTopbar, QFrame#exportCard, QFrame#externalMergeCard, QFrame#actionBar, QFrame#directoryDisplay {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px; }}
QFrame#playbackToolbar {{ background: {C_CARD2}; border: 1px solid {C_BORDER}; border-radius: 8px; }}
QFrame#pathDisplay {{ background: {C_CARD2}; border: 1px solid {C_BORDER}; border-radius: 6px; }}
QFrame#segmentCard {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px; }}
QTextEdit#log {{ background: #101828; color: #EAECF0; border: 1px solid #344054; border-radius: 8px; padding: 12px; font-family: Consolas, monospace; }}
"""


# Backwards-compatible public alias used by the facade and legacy tests.
QSS = application_qss()
