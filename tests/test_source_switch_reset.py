import sys
import types
import unittest


class _Fake:
    def __init__(self, *args, **kwargs):
        self._text = str(args[0]) if args else ""

    def __call__(self, *args, **kwargs):
        return _Fake()

    def __getattr__(self, name):
        if name in ("textChanged", "clicked", "timeout", "enabled_changed", "metadata_changed", "currentTextChanged"):
            return _FakeSignal()
        return _Fake()

    def __or__(self, other):
        return self


class _FakeSignal:
    def connect(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass


def _install_fake_pyqt():
    if "PyQt6" in sys.modules:
        return
    pyqt = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtgui = types.ModuleType("PyQt6.QtGui")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")

    qtcore.Qt = _Fake()
    qtcore.QThread = _Fake
    qtcore.pyqtSignal = lambda *args, **kwargs: _FakeSignal()
    for name in ("QTimer", "QSize", "QMimeData", "QPoint", "QRect", "QEvent"):
        setattr(qtcore, name, _Fake)
    for name in (
        "QColor", "QFont", "QPalette", "QPainter", "QLinearGradient",
        "QPainterPath", "QPen", "QDragEnterEvent", "QDropEvent",
        "QDragLeaveEvent", "QMouseEvent", "QTextCursor",
    ):
        setattr(qtgui, name, _Fake)
    for name in (
        "QApplication", "QMainWindow", "QWidget", "QVBoxLayout", "QHBoxLayout",
        "QLabel", "QPushButton", "QComboBox", "QLineEdit", "QTextEdit",
        "QScrollArea", "QFrame", "QFileDialog", "QSizePolicy", "QSpacerItem",
        "QCheckBox", "QGridLayout", "QGraphicsDropShadowEffect",
    ):
        setattr(qtwidgets, name, _Fake)

    sys.modules["PyQt6"] = pyqt
    sys.modules["PyQt6.QtCore"] = qtcore
    sys.modules["PyQt6.QtGui"] = qtgui
    sys.modules["PyQt6.QtWidgets"] = qtwidgets


_install_fake_pyqt()

import app


class _Panel:
    def __init__(self):
        self.reset_source = None

    def reset_for_source(self, source_id):
        self.reset_source = source_id


class _Window:
    def __init__(self):
        self._current_source_id = "old_song"
        self._suppress_source_reset = False
        self._rows = ["old_segment"]
        self._songlist_panel = _Panel()
        self.dirty = False
        self.audio_refreshed = False
        self.arc_refreshed = False

    def _clear_segments(self):
        self._rows.clear()

    def _add_segment(self, s=None, e=None):
        self._rows.append((s, e))

    def _refresh_current_audio_duration(self):
        self.audio_refreshed = True

    def _schedule_arc_cut_warning_refresh(self):
        self.arc_refreshed = True

    def _mark_current_export_dirty(self):
        self.dirty = True


class SourceSwitchResetTests(unittest.TestCase):
    def test_switching_source_resets_metadata_segments_and_marks_dirty(self):
        win = _Window()

        app.MainWindow._on_song_changed(win, "tempestissimo")

        self.assertEqual(win._current_source_id, "tempestissimo")
        self.assertEqual(win._songlist_panel.reset_source, "tempestissimo")
        self.assertEqual(win._rows, [(None, None)])
        self.assertTrue(win.audio_refreshed)
        self.assertTrue(win.arc_refreshed)
        self.assertTrue(win.dirty)

    def test_initial_load_suppression_does_not_reset_old_segments(self):
        win = _Window()
        win._suppress_source_reset = True

        app.MainWindow._on_song_changed(win, "tempestissimo")

        self.assertEqual(win._current_source_id, "old_song")
        self.assertIsNone(win._songlist_panel.reset_source)
        self.assertEqual(win._rows, ["old_segment"])
        self.assertFalse(win.dirty)


if __name__ == "__main__":
    unittest.main()
