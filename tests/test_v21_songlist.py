import json
import tempfile
import types
import unittest
from pathlib import Path


class _Fake:
    def __init__(self, *args, **kwargs):
        self._text = str(args[0]) if args else ""
        self._checked = False
        self._visible = True
        self._children = []

    def __call__(self, *args, **kwargs):
        return _Fake()

    def __getattr__(self, name):
        if name in ("textChanged", "clicked", "timeout"):
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

    def setChecked(self, checked):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setVisible(self, visible):
        self._visible = bool(visible)

    def isVisible(self):
        return self._visible

    def hide(self):
        self._visible = False

    def show(self):
        self._visible = True

    def deleteLater(self):
        pass


class _FakeSignal:
    def connect(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass


def _install_fake_pyqt():
    import sys

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


def _valid_form(**overrides):
    data = {
        "title_base": "Prelude",
        "artist": "Artist",
        "bpm": "180",
        "bpm_base": "180.0",
        "set": "single",
        "purchase": "",
        "side": "0",
        "bg": "base_light",
        "version": "1.0",
        "chart_designer": "Chart",
        "jacket_designer": "Jacket",
        "rating": "9",
        "rating_plus": False,
    }
    data.update(overrides)
    return data


def _assert_ftr_compat_difficulties(testcase, song, rating=9, rating_plus=False):
    difficulties = song["difficulties"]
    testcase.assertEqual(len(difficulties), 3)
    testcase.assertEqual([d["ratingClass"] for d in difficulties], [0, 1, 2])
    testcase.assertEqual([d["rating"] for d in difficulties], [-1, -1, rating])
    testcase.assertEqual([d["ratingPlus"] for d in difficulties], [False, False, rating_plus])
    for diff in difficulties:
        testcase.assertEqual(diff["chartDesigner"], "Chart")
        testcase.assertEqual(diff["jacketDesigner"], "Jacket")


class _ExportCase(unittest.TestCase):
    def setUp(self):
        self._old_out_dir = app.OUT_DIR
        self._old_get_ffmpeg = app._get_ffmpeg
        self._old_slice_ogg = app.slice_ogg
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        app.OUT_DIR = self.root / "out"
        app._get_ffmpeg = lambda: "ffmpeg"

        def fake_slice_ogg(_in_path, out_path, _start_ms, _end_ms, _speed):
            Path(out_path).write_bytes(b"ogg")

        app.slice_ogg = fake_slice_ogg
        self.songs_dir = self.root / "songs"
        song = self.songs_dir / "prelude_heavensdoor"
        song.mkdir(parents=True)
        (song / "base.ogg").write_bytes(b"audio")
        (song / "2.aff").write_text("AudioOffset:0\n-\ntiming(0,100.00,4.00);\n", encoding="utf-8")
        (song / "base.jpg").write_text("base", encoding="utf-8")
        self.legacy_out_songs = app.OUT_DIR / "songs"
        self.legacy_out_songs.mkdir(parents=True)
        (self.legacy_out_songs / "sentinel.txt").write_text("old", encoding="utf-8")
        (app.OUT_DIR / "songlist").write_text("legacy", encoding="utf-8")
        self.logs = []

    def tearDown(self):
        app.OUT_DIR = self._old_out_dir
        app._get_ffmpeg = self._old_get_ffmpeg
        app.slice_ogg = self._old_slice_ogg
        self.td.cleanup()

    def _log(self, text, kind="normal"):
        self.logs.append((text, kind))

    def _do_slice(self, segments, speed=1.0, enabled=False, form=None):
        return app.do_slice(
            self.songs_dir,
            "prelude_heavensdoor",
            segments,
            speed,
            self._log,
            form or {},
            enabled,
            None,
            True,
            False,
        )


class V21SonglistOutputTests(_ExportCase):
    def test_songlist_disabled_writes_no_songlist_files(self):
        code = self._do_slice([{"s": 21000, "e": 22000}], enabled=False, form=_valid_form())
        segment_id = "prelude_heavensdoor_21000_22000_x1"
        root_songlist = app.current_export_songs_dir(app.OUT_DIR) / "songlist"
        segment_dir = app.current_export_songs_dir(app.OUT_DIR) / segment_id

        self.assertEqual(code, 0, self.logs)
        self.assertTrue(segment_dir.exists())
        self.assertFalse(root_songlist.exists())
        self.assertFalse((segment_dir / "songlist").exists())
        self.assertFalse((segment_dir / "songlist_fragment.json").exists())
        self.assertEqual((app.OUT_DIR / "songlist").read_text(encoding="utf-8"), "legacy")
        self.assertEqual((self.legacy_out_songs / "sentinel.txt").read_text(encoding="utf-8"), "old")
        self.assertFalse(app.library_export_root(app.OUT_DIR).exists())

    def test_songlist_enabled_writes_only_root_songlist(self):
        code = self._do_slice(
            [{"s": 21000, "e": 22000}, {"s": 23000, "e": 24000}],
            speed=1.25,
            enabled=True,
            form=_valid_form(),
        )
        songs_root = app.current_export_songs_dir(app.OUT_DIR)
        doc = json.loads((songs_root / "songlist").read_text(encoding="utf-8"))
        segment_dirs = sorted(p.name for p in songs_root.iterdir() if p.is_dir())

        self.assertEqual(code, 0, self.logs)
        self.assertEqual(list(doc.keys()), ["songs"])
        self.assertEqual(len(doc["songs"]), 2)
        self.assertEqual(segment_dirs, [
            "prelude_heavensdoor_21000_22000_x1p25",
            "prelude_heavensdoor_23000_24000_x1p25",
        ])
        self.assertEqual([song["id"] for song in doc["songs"]], segment_dirs)
        for segment_id in segment_dirs:
            self.assertFalse((songs_root / segment_id / "songlist").exists())
            self.assertFalse((songs_root / segment_id / "songlist_fragment.json").exists())
        self.assertFalse(app.library_export_root(app.OUT_DIR).exists())

    def test_songlist_entry_fields_and_speed_scaling(self):
        self._do_slice([{"s": 21000, "e": 22000}], speed=2.0, enabled=True, form=_valid_form())
        song = json.loads((app.current_export_songs_dir(app.OUT_DIR) / "songlist").read_text(encoding="utf-8"))["songs"][0]

        self.assertEqual(song["id"], "prelude_heavensdoor_21000_22000_x2")
        self.assertIn("21000–22000ms", song["title_localized"]["en"])
        self.assertIn("2×", song["title_localized"]["en"])
        self.assertNotIn("idx", song)
        self.assertEqual(song["bpm_base"], 360.0)
        self.assertEqual(song["bpm"], "360")
        _assert_ftr_compat_difficulties(self, song)

    def test_complex_bpm_string_is_preserved(self):
        self._do_slice([{"s": 21000, "e": 22000}], speed=2.0, enabled=True, form=_valid_form(bpm="120-180"))
        song = json.loads((app.current_export_songs_dir(app.OUT_DIR) / "songlist").read_text(encoding="utf-8"))["songs"][0]

        self.assertEqual(song["bpm_base"], 360.0)
        self.assertEqual(song["bpm"], "120-180")

    def test_current_export_all_segments_have_ftr_compat_difficulties(self):
        self._do_slice(
            [{"s": 21000, "e": 22000}, {"s": 23000, "e": 24000}],
            enabled=True,
            form=_valid_form(rating="10", rating_plus=True),
        )
        songs = json.loads((app.current_export_songs_dir(app.OUT_DIR) / "songlist").read_text(encoding="utf-8"))["songs"]

        for song in songs:
            self.assertNotIn("idx", song)
            _assert_ftr_compat_difficulties(self, song, rating=10, rating_plus=True)

    def test_enabled_invalid_form_fails_and_preserves_current_export(self):
        current_song = app.current_export_songs_dir(app.OUT_DIR) / "old_segment"
        current_song.mkdir(parents=True)
        (current_song / "base.ogg").write_bytes(b"old")

        code = self._do_slice(
            [{"s": 21000, "e": 22000}],
            enabled=True,
            form=_valid_form(bpm_base="not-a-number"),
        )

        self.assertEqual(code, 1)
        self.assertTrue((current_song / "base.ogg").exists())
        self.assertFalse((app.current_export_songs_dir(app.OUT_DIR) / "songlist").exists())
        self.assertFalse(app.library_export_root(app.OUT_DIR).exists())


class V21SongTemplateTests(unittest.TestCase):
    def test_build_ftr_compat_difficulties_shape(self):
        template = app.song_template_from_form(_valid_form(rating="8", rating_plus=True))
        difficulties = app.build_ftr_compat_difficulties(template)

        self.assertEqual(len(difficulties), 3)
        self.assertEqual([d["ratingClass"] for d in difficulties], [0, 1, 2])
        self.assertEqual([d["rating"] for d in difficulties], [-1, -1, 8])
        self.assertEqual([d["ratingPlus"] for d in difficulties], [False, False, True])
        for diff in difficulties:
            self.assertEqual(diff["chartDesigner"], "Chart")
            self.assertEqual(diff["jacketDesigner"], "Jacket")

    def test_build_songlist_document_shape(self):
        template = app.song_template_from_form(_valid_form())
        entry = app.build_songlist_entry(
            template,
            "prelude_heavensdoor_21000_22000_x1",
            "Prelude [21000–22000ms · 1×]",
            21000,
            22000,
            1.0,
        )
        self.assertEqual(app.build_songlist_document([entry]), {"songs": [entry]})


class V21SlidesCompatibilityTests(unittest.TestCase):
    class _SongBox:
        def __init__(self):
            self._text = "song"

        def currentText(self):
            return self._text

        def findText(self, text):
            return -1

    class _SpeedInput:
        def __init__(self):
            self._text = "1.0"

        def text(self):
            return self._text

        def setText(self, text):
            self._text = str(text)

    class _Panel:
        def __init__(self):
            self.enabled = False
            self.meta = {}

        def is_songlist_enabled(self):
            return self.enabled

        def set_songlist_enabled(self, enabled):
            self.enabled = bool(enabled)

        def get_form_data(self):
            return dict(self.meta)

        def get_meta(self):
            return dict(self.meta)

        def set_meta(self, meta):
            self.meta = dict(meta)

    class _Layout:
        def addWidget(self, *_args, **_kwargs):
            pass

        def removeWidget(self, *_args, **_kwargs):
            pass

    def _window(self):
        win = object.__new__(app.MainWindow)
        win._song_box = self._SongBox()
        win._speed_input = self._SpeedInput()
        win._rows = []
        win._songlist_panel = self._Panel()
        win._segs_layout = self._Layout()
        win._refresh_seg_header = lambda: None
        win._schedule_arc_cut_warning_refresh = lambda: None
        return win

    def test_collect_defaults_songlist_disabled_and_saves_form(self):
        win = self._window()
        win._songlist_panel.meta = _valid_form(title_base="Saved")
        data = app.MainWindow._collect(win)

        self.assertFalse(data["songlist_enabled"])
        self.assertFalse(data["packlist_enabled"])
        self.assertEqual(data["songlist"]["title_base"], "Saved")

    def test_apply_old_slides_missing_enabled_defaults_false(self):
        win = self._window()
        app.MainWindow._apply_slides(win, {"speed": 1.5, "segments": [], "songlist": {"bpm_base": "bad"}})

        self.assertFalse(win._songlist_panel.enabled)
        self.assertEqual(win._songlist_panel.meta["bpm_base"], "bad")
        self.assertEqual(len(win._rows), 1)
        self.assertIsNone(win._rows[0].to_dict())


if __name__ == "__main__":
    unittest.main()
