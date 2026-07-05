import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path


class _Fake:
    def __init__(self, *args, **kwargs):
        self._text = str(args[0]) if args else ""
        self._visible = True
        self._children = []

    def __call__(self, *args, **kwargs):
        return _Fake()

    def __getattr__(self, name):
        if name in ("textChanged", "clicked", "timeout", "enabled_changed", "currentTextChanged"):
            return _FakeSignal()
        return _Fake()

    def __or__(self, other):
        return self

    def addWidget(self, widget, *args, **kwargs):
        self._children.append(widget)

    def addLayout(self, layout, *args, **kwargs):
        self._children.append(layout)

    def addStretch(self, *args, **kwargs):
        pass

    def setText(self, text):
        self._text = str(text)

    def text(self):
        return self._text

    def currentText(self):
        return self._text

    def setToolTip(self, text):
        self._tooltip = str(text)

    def setVisible(self, visible):
        self._visible = bool(visible)

    def isVisible(self):
        return self._visible

    def hide(self):
        self._visible = False

    def show(self):
        self._visible = True

    def selectAll(self):
        self._selected = True

    def setFocus(self):
        self._focused = True

    def deleteLater(self):
        pass


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


class _Row:
    def __init__(self, start, end):
        self._start = str(start)
        self._end = str(end)
        self.errors = None
        self.end_cap_ms = None
        self.focused = None

    def start_text(self):
        return self._start

    def end_text(self):
        return self._end

    def set_time_errors(self, start_error="", end_error="", end_cap_ms=None):
        self.errors = (start_error, end_error)
        self.end_cap_ms = end_cap_ms

    def focus_time_field(self, field):
        self.focused = field

    def clear_time_errors(self):
        self.errors = ("", "")
        self.end_cap_ms = None


class SegmentDurationFunctionTests(unittest.TestCase):
    def test_parse_duration_to_ms_uses_floor_milliseconds(self):
        self.assertEqual(app.parse_duration_to_ms("222.5189"), 222518)
        self.assertEqual(app.parse_duration_to_ms("0.0009"), 0)

    def test_parse_ffmpeg_duration_line(self):
        text = "Input #0\n  Duration: 00:03:42.518, start: 0.000000, bitrate: 128 kb/s"
        self.assertEqual(app.parse_ffmpeg_duration_to_ms(text), 222518)

    def test_format_duration_ms(self):
        self.assertEqual(app.format_duration_ms(0), "0:00.000")
        self.assertEqual(app.format_duration_ms(222518), "3:42.518")
        self.assertEqual(app.format_duration_ms(3723456), "1:02:03.456")

    def test_time_input_regex_allows_only_integer_editing_states(self):
        allowed = ["", "-", "-123", "0", "123"]
        rejected = ["1.0", " 1", "1 ", "1e3", "abc", "一百"]
        for value in allowed:
            with self.subTest(value=value):
                self.assertTrue(app.is_time_input_text_allowed(value))
        for value in rejected:
            with self.subTest(value=value):
                self.assertFalse(app.is_time_input_text_allowed(value))


class SegmentBoundsValidationTests(unittest.TestCase):
    def test_valid_segment_inside_audio(self):
        result = app.validate_segment_bounds("0", "1000", 1000)
        self.assertTrue(result.ok)

    def test_empty_and_negative_inputs_are_owned_by_field(self):
        start_missing = app.validate_segment_bounds("", "100", 1000)
        self.assertEqual(start_missing.first_field, "start")
        self.assertIn("不能为空", start_missing.start_error)

        end_missing = app.validate_segment_bounds("0", "", 1000)
        self.assertEqual(end_missing.first_field, "end")
        self.assertIn("不能为空", end_missing.end_error)

        negative = app.validate_segment_bounds("-1", "100", 1000)
        self.assertEqual(negative.first_field, "start")
        self.assertIn("非负整数", negative.start_error)

    def test_relationship_error_belongs_to_end(self):
        result = app.validate_segment_bounds("1000", "1000", 2000)
        self.assertEqual(result.first_field, "end")
        self.assertEqual(result.end_error, "终点必须大于起点")

    def test_audio_bounds_errors_belong_to_matching_field(self):
        start = app.validate_segment_bounds("1000", "1001", 1000)
        self.assertEqual(start.first_field, "start")
        self.assertIn("起点不能超过音频时长：0:01.000", start.start_error)
        self.assertIsNone(start.end_cap_ms)

        end = app.validate_segment_bounds("0", "1001", 1000)
        self.assertEqual(end.first_field, "end")
        self.assertIn("终点不能超过音频时长：0:01.000", end.end_error)
        self.assertEqual(end.end_cap_ms, 1000)

    def test_unknown_duration_blocks_semantically_valid_segment(self):
        result = app.validate_segment_bounds("0", "1000", None)
        self.assertEqual(result.first_field, "end")
        self.assertEqual(result.end_error, "无法读取当前曲目的音频时长")
        self.assertIsNone(result.end_cap_ms)

    def test_end_cap_is_only_available_for_integer_end_over_audio_duration(self):
        equal = app.validate_segment_bounds("0", "1000", 1000)
        self.assertTrue(equal.ok)
        self.assertIsNone(equal.end_cap_ms)

        below = app.validate_segment_bounds("0", "999", 1000)
        self.assertTrue(below.ok)
        self.assertIsNone(below.end_cap_ms)

        invalid_end = app.validate_segment_bounds("0", "-", 1000)
        self.assertIsNone(invalid_end.end_cap_ms)

        start_over = app.validate_segment_bounds("1000", "2000", 1000)
        self.assertEqual(start_over.first_field, "start")
        self.assertIsNone(start_over.end_cap_ms)


class AudioProbeTests(unittest.TestCase):
    class _Completed:
        def __init__(self, stdout="", stderr=""):
            self.stdout = stdout
            self.stderr = stderr

    def test_probe_uses_ffprobe_duration(self):
        with tempfile.TemporaryDirectory() as td:
            audio = Path(td) / "base.ogg"
            audio.write_bytes(b"ogg")
            old_ffprobe, old_run = app._get_ffprobe, app.subprocess.run
            try:
                app._get_ffprobe = lambda: "ffprobe"
                app.subprocess.run = lambda *args, **kwargs: self._Completed(stdout="12.3459\n")
                self.assertEqual(app.probe_audio_duration_ms(audio), 12345)
            finally:
                app._get_ffprobe, app.subprocess.run = old_ffprobe, old_run

    def test_probe_falls_back_to_ffmpeg_duration_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            audio = Path(td) / "base.ogg"
            audio.write_bytes(b"ogg")
            old_ffprobe, old_ffmpeg, old_run = app._get_ffprobe, app._get_ffmpeg, app.subprocess.run
            calls = []

            def fake_run(cmd, *args, **kwargs):
                calls.append(cmd[0])
                return self._Completed(stderr="Duration: 00:03:42.518, start: 0.000000")

            try:
                app._get_ffprobe = lambda: (_ for _ in ()).throw(RuntimeError("missing"))
                app._get_ffmpeg = lambda: "ffmpeg"
                app.subprocess.run = fake_run
                self.assertEqual(app.probe_audio_duration_ms(audio), 222518)
                self.assertEqual(calls, ["ffmpeg"])
            finally:
                app._get_ffprobe, app._get_ffmpeg, app.subprocess.run = old_ffprobe, old_ffmpeg, old_run


class SegmentValidationUiFlowTests(unittest.TestCase):
    def test_segmentrow_time_errors_toggle_without_arc_state(self):
        row = app.SegmentRow(1, None, None)
        row.set_time_errors("起点不能为空", "")
        self.assertEqual(row._start_error.text(), "起点不能为空")
        self.assertTrue(row._start_error.isVisible())
        self.assertFalse(row._end_error.isVisible())
        self.assertFalse(row._end_cap_btn.isVisible())

        row.clear_time_errors()
        self.assertEqual(row._start_error.text(), "")
        self.assertFalse(row._start_error.isVisible())
        self.assertFalse(row._end_cap_btn.isVisible())

    def test_segmentrow_shows_end_cap_button_only_when_requested(self):
        row = app.SegmentRow(1, 0, 2000)
        row.set_time_errors("", "终点不能超过音频时长：0:01.000", 1000)

        self.assertTrue(row._end_error.isVisible())
        self.assertEqual(row._end_cap_btn.text(), "设为上限 1000 ms")
        self.assertTrue(row._end_cap_btn.isVisible())

        row.set_time_errors("", "")
        self.assertFalse(row._end_cap_btn.isVisible())

    def test_refresh_skips_completely_blank_row_until_export(self):
        win = object.__new__(app.MainWindow)
        row = _Row("", "")
        win._rows = [row]
        win._audio_duration_ms = 1000
        app.MainWindow._refresh_segment_time_validation(win)
        self.assertEqual(row.errors, ("", ""))

    def test_run_slicer_blocks_before_collect_and_worker(self):
        win = object.__new__(app.MainWindow)
        row = _Row("0", "2000")
        shown = []
        logs = []
        win._worker = None
        win._speed_input = _Fake("1.0")
        win._song_box = _Fake("song")
        win._rows = [row]
        win._audio_duration_ms = 1000
        win._push_log = lambda text, kind="normal": logs.append((text, kind))
        win._refresh_current_audio_duration = lambda: None
        win._show_segment_validation_error = lambda index, row, result: shown.append((index, result.first_field, result.first_message))
        win._collect = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("_collect should not run"))

        app.MainWindow._run_slicer(win)

        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0][1], "end")
        self.assertIn("终点不能超过音频时长", shown[0][2])

    def test_refresh_current_audio_duration_updates_label_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            song = root / "song"
            song.mkdir()
            (song / "base.ogg").write_bytes(b"ogg")
            win = object.__new__(app.MainWindow)
            win._cfg = {"songs_dir": str(root)}
            win._song_box = _Fake("song")
            win._audio_duration_label = _Fake()
            win._rows = [_Row("0", "1500")]
            win._push_log = lambda *args, **kwargs: None
            old_probe = app.probe_audio_duration_ms
            try:
                app.probe_audio_duration_ms = lambda path: 1234
                app.MainWindow._refresh_current_audio_duration(win)
                self.assertEqual(win._audio_duration_ms, 1234)
                self.assertIn("0:01.234", win._audio_duration_label.text())
                self.assertIn("终点上限：1234 ms", win._audio_duration_label.text())
                self.assertIn("终点不能超过音频时长", win._rows[0].errors[1])
                self.assertEqual(win._rows[0].end_cap_ms, 1234)
            finally:
                app.probe_audio_duration_ms = old_probe

    def test_set_end_to_audio_duration_requires_explicit_action(self):
        win = object.__new__(app.MainWindow)
        row = app.SegmentRow(1, 0, 2000)
        win._rows = [row]
        win._audio_duration_ms = 1000
        win._refresh_seg_header = lambda: None
        win._schedule_arc_cut_warning_refresh = lambda: None

        app.MainWindow._refresh_segment_time_validation(win)
        self.assertEqual(row.end_text(), "2000")
        self.assertTrue(row._end_cap_btn.isVisible())

        app.MainWindow._set_row_end_to_audio_duration(win, row)
        self.assertEqual(row.end_text(), "1000")
        self.assertEqual(row.e_val, 1000)
        self.assertFalse(row._end_cap_btn.isVisible())
        self.assertEqual(row._end_error.text(), "")

    def test_refresh_does_not_silently_clamp_timeout_end(self):
        win = object.__new__(app.MainWindow)
        row = app.SegmentRow(1, 0, 2000)
        win._rows = [row]
        win._audio_duration_ms = 1000

        app.MainWindow._refresh_segment_time_validation(win)

        self.assertEqual(row.end_text(), "2000")
        self.assertTrue(row._end_cap_btn.isVisible())


if __name__ == "__main__":
    unittest.main()
