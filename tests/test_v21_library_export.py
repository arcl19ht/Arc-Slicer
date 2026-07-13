import json
import shutil
import tempfile
import types
import unittest
from pathlib import Path


class _Fake:
    def __init__(self, *args, **kwargs):
        self._text = str(args[0]) if args else ""
        self._checked = False
        self._enabled = True
        self._visible = True
        self._children = []

    def __call__(self, *args, **kwargs):
        return _Fake()

    def __getattr__(self, name):
        if name in ("textChanged", "clicked", "timeout", "enabled_changed"):
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

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def isEnabled(self):
        return self._enabled

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


def _form(**overrides):
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


def _write_songlist(path: Path, entries: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"songs": entries}, ensure_ascii=False, indent=2), encoding="utf-8")


class _ExportCase(unittest.TestCase):
    def setUp(self):
        self.old_out_dir = app.OUT_DIR
        self.old_get_ffmpeg = app._get_ffmpeg
        self.old_slice_ogg = app.slice_ogg
        self.old_slice_aff = app.slice_aff
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        app.OUT_DIR = self.root / "out"
        app._get_ffmpeg = lambda: "ffmpeg"
        self.slice_ogg_calls = []
        self.slice_aff_calls = []

        def fake_slice_ogg(_in_path, out_path, start, end, speed):
            self.slice_ogg_calls.append((start, end, speed))
            Path(out_path).write_bytes(f"ogg-{start}-{end}-{speed}".encode())

        def fake_slice_aff(text, start, end, speed, warnings=None):
            self.slice_aff_calls.append((start, end, speed))
            return f"AudioOffset:0\n-\ntiming(0,{100 * speed:.2f},4.00);\n"

        app.slice_ogg = fake_slice_ogg
        app.slice_aff = fake_slice_aff
        app._get_ffmpeg = lambda: "ffmpeg"
        self.songs_dir = self.root / "songs"
        song = self.songs_dir / "prelude_heavensdoor"
        song.mkdir(parents=True)
        (song / "base.ogg").write_bytes(b"audio")
        (song / "2.aff").write_text("AudioOffset:0\n-\ntiming(0,100.00,4.00);\n", encoding="utf-8")
        self.logs = []

    def tearDown(self):
        app.OUT_DIR = self.old_out_dir
        app._get_ffmpeg = self.old_get_ffmpeg
        app.slice_ogg = self.old_slice_ogg
        app.slice_aff = self.old_slice_aff
        self.td.cleanup()

    def log(self, text, kind="normal"):
        self.logs.append((text, kind))

    def do_slice(self, segments, *, songlist=True, current=True, library=True, form=None):
        return app.do_slice(
            self.songs_dir,
            "prelude_heavensdoor",
            segments,
            1.0,
            self.log,
            form or _form(),
            songlist,
            None,
            current,
            library,
            duration_getter=lambda _path: 120_000,
        )


class V21LibraryDoSliceTests(_ExportCase):
    def test_songlist_disabled_does_not_create_library_even_if_checked(self):
        code = self.do_slice([{"s": 21000, "e": 22000}], songlist=False, current=True, library=True)

        self.assertEqual(code, 0, self.logs)
        self.assertTrue(app.current_export_root(app.OUT_DIR).exists())
        self.assertFalse(app.library_export_root(app.OUT_DIR).exists())

    def test_current_only_preserves_library_sentinel(self):
        library = app.library_export_songs_dir(app.OUT_DIR)
        library.mkdir(parents=True)
        (library / "sentinel.txt").write_text("keep", encoding="utf-8")

        code = self.do_slice([{"s": 21000, "e": 22000}], songlist=True, current=True, library=False)

        self.assertEqual(code, 0, self.logs)
        self.assertTrue(app.current_export_root(app.OUT_DIR).exists())
        self.assertEqual((library / "sentinel.txt").read_text(encoding="utf-8"), "keep")
        self.assertFalse((library / "songlist").exists())

    def test_library_only_updates_library_and_preserves_current(self):
        current = app.current_export_songs_dir(app.OUT_DIR)
        current.mkdir(parents=True)
        (current / "old_current.txt").write_text("keep", encoding="utf-8")

        code = self.do_slice([{"s": 21000, "e": 22000}], songlist=True, current=False, library=True)

        self.assertEqual(code, 0, self.logs)
        library_songlist = app.library_export_songs_dir(app.OUT_DIR) / "songlist"
        self.assertTrue(library_songlist.exists())
        self.assertEqual((current / "old_current.txt").read_text(encoding="utf-8"), "keep")
        self.assertEqual(list((app.current_export_songs_dir(app.OUT_DIR)).glob("prelude_*")), [])

    def test_library_reexport_replaces_entry_with_ftr_compat_difficulties(self):
        library = app.library_export_songs_dir(app.OUT_DIR)
        library.mkdir(parents=True)
        segment_id = "prelude_heavensdoor_21000_22000_x1"
        _write_songlist(library / "songlist", [{
            "id": segment_id,
            "title_localized": {"en": "Old"},
            "difficulties": [{"ratingClass": 2, "rating": 7}],
        }])
        (library / segment_id).mkdir()
        (library / segment_id / "old.txt").write_text("old", encoding="utf-8")

        code = self.do_slice(
            [{"s": 21000, "e": 22000}],
            songlist=True,
            current=False,
            library=True,
            form=_form(rating="10", rating_plus=True),
        )

        self.assertEqual(code, 0, self.logs)
        song = json.loads((library / "songlist").read_text(encoding="utf-8"))["songs"][0]
        self.assertEqual(song["id"], segment_id)
        self.assertEqual([d["ratingClass"] for d in song["difficulties"]], [0, 1, 2])
        self.assertEqual([d["rating"] for d in song["difficulties"]], [-1, -1, 10])
        self.assertEqual([d["ratingPlus"] for d in song["difficulties"]], [False, False, True])
        self.assertFalse((library / segment_id / "old.txt").exists())

    def test_both_targets_use_one_slice_pass(self):
        code = self.do_slice(
            [{"s": 21000, "e": 22000}, {"s": 23000, "e": 24000}],
            songlist=True,
            current=True,
            library=True,
        )

        self.assertEqual(code, 0, self.logs)
        self.assertEqual(len(self.slice_ogg_calls), 2)
        self.assertEqual(len(self.slice_aff_calls), 2)
        self.assertTrue((app.current_export_songs_dir(app.OUT_DIR) / "songlist").exists())
        self.assertTrue((app.library_export_songs_dir(app.OUT_DIR) / "songlist").exists())

    def test_no_effective_target_is_rejected_before_slicing(self):
        code = self.do_slice([{"s": 21000, "e": 22000}], songlist=False, current=False, library=True)

        self.assertEqual(code, 1)
        self.assertEqual(self.slice_ogg_calls, [])
        self.assertFalse(app.current_export_root(app.OUT_DIR).exists())
        self.assertFalse(app.library_export_root(app.OUT_DIR).exists())
        self.assertTrue(any("至少需要选择一个有效导出目标" in text for text, _ in self.logs))


class V21LibraryMergeTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.out = self.root / "out"

    def tearDown(self):
        self.td.cleanup()

    def _stage(self, entries: list[dict]) -> Path:
        stage = app.create_current_export_stage(self.out)
        songs = stage / "songs"
        _write_songlist(songs / "songlist", entries)
        for entry in entries:
            song_dir = songs / entry["id"]
            song_dir.mkdir()
            (song_dir / "2.aff").write_text(entry["id"], encoding="utf-8")
        return stage

    def test_new_library_is_created(self):
        stage = self._stage([{"id": "song_a", "title_localized": {"en": "A"}}])

        app.merge_staging_into_library_export(stage, self.out)

        songs = app.library_export_songs_dir(self.out)
        self.assertTrue((songs / "songlist").exists())
        self.assertTrue((songs / "song_a" / "2.aff").exists())

    def test_merge_appends_new_id_and_preserves_old(self):
        songs = app.library_export_songs_dir(self.out)
        _write_songlist(songs / "songlist", [{"id": "old_song", "title_localized": {"en": "Old"}}])
        (songs / "old_song").mkdir(parents=True)
        (songs / "old_song" / "2.aff").write_text("old", encoding="utf-8")
        stage = self._stage([{"id": "new_song", "title_localized": {"en": "New"}}])

        app.merge_staging_into_library_export(stage, self.out)

        doc = json.loads((songs / "songlist").read_text(encoding="utf-8"))
        self.assertEqual([entry["id"] for entry in doc["songs"]], ["old_song", "new_song"])
        self.assertEqual((songs / "old_song" / "2.aff").read_text(encoding="utf-8"), "old")
        self.assertEqual((songs / "new_song" / "2.aff").read_text(encoding="utf-8"), "new_song")

    def test_merge_replaces_existing_id_in_place_and_directory(self):
        songs = app.library_export_songs_dir(self.out)
        _write_songlist(songs / "songlist", [
            {"id": "old_song", "title_localized": {"en": "Old"}},
            {"id": "same_song", "title_localized": {"en": "Old Same"}},
            {"id": "tail_song", "title_localized": {"en": "Tail"}},
        ])
        for name in ("old_song", "same_song", "tail_song"):
            (songs / name).mkdir(parents=True, exist_ok=True)
            (songs / name / "2.aff").write_text(f"old-{name}", encoding="utf-8")
        stage = self._stage([{"id": "same_song", "title_localized": {"en": "New Same"}}])

        app.merge_staging_into_library_export(stage, self.out)

        doc = json.loads((songs / "songlist").read_text(encoding="utf-8"))
        self.assertEqual([entry["id"] for entry in doc["songs"]], ["old_song", "same_song", "tail_song"])
        self.assertEqual(doc["songs"][1]["title_localized"]["en"], "New Same")
        self.assertEqual((songs / "same_song" / "2.aff").read_text(encoding="utf-8"), "same_song")
        self.assertEqual((songs / "tail_song" / "2.aff").read_text(encoding="utf-8"), "old-tail_song")

    def test_packlist_pack_and_unlock_are_preserved(self):
        songs = app.library_export_songs_dir(self.out)
        songs.mkdir(parents=True)
        (songs / "packlist").write_text("packlist", encoding="utf-8")
        (songs / "unlock").write_text("unlock", encoding="utf-8")
        (songs / "pack").mkdir()
        (songs / "pack" / "sentinel.png").write_text("pack", encoding="utf-8")
        stage = self._stage([{"id": "song_a"}])

        app.merge_staging_into_library_export(stage, self.out)

        self.assertEqual((songs / "packlist").read_text(encoding="utf-8"), "packlist")
        self.assertEqual((songs / "unlock").read_text(encoding="utf-8"), "unlock")
        self.assertEqual((songs / "pack" / "sentinel.png").read_text(encoding="utf-8"), "pack")

    def test_damaged_library_songlist_fails_without_changes(self):
        songs = app.library_export_songs_dir(self.out)
        songs.mkdir(parents=True)
        (songs / "songlist").write_text("{broken", encoding="utf-8")
        (songs / "old_song").mkdir()
        (songs / "old_song" / "2.aff").write_text("old", encoding="utf-8")
        stage = self._stage([{"id": "new_song"}])

        with self.assertRaises(ValueError):
            app.merge_staging_into_library_export(stage, self.out)

        self.assertEqual((songs / "songlist").read_text(encoding="utf-8"), "{broken")
        self.assertFalse((songs / "new_song").exists())
        self.assertEqual((songs / "old_song" / "2.aff").read_text(encoding="utf-8"), "old")

    def test_target_song_link_is_rejected_without_deleting_target(self):
        songs = app.library_export_songs_dir(self.out)
        _write_songlist(songs / "songlist", [{"id": "same_song"}])
        target = songs / "same_song"
        target.mkdir(parents=True)
        (target / "2.aff").write_text("old", encoding="utf-8")
        stage = self._stage([{"id": "same_song"}])
        old_check = app._path_is_link_or_junction
        app._path_is_link_or_junction = lambda path: Path(path) == target
        try:
            with self.assertRaises(RuntimeError):
                app.merge_staging_into_library_export(stage, self.out)
        finally:
            app._path_is_link_or_junction = old_check

        self.assertEqual((target / "2.aff").read_text(encoding="utf-8"), "old")

    def test_failure_after_directory_replace_restores_old_library(self):
        songs = app.library_export_songs_dir(self.out)
        _write_songlist(songs / "songlist", [{"id": "same_song", "title_localized": {"en": "Old"}}])
        (songs / "same_song").mkdir(parents=True)
        (songs / "same_song" / "2.aff").write_text("old", encoding="utf-8")
        stage = self._stage([{"id": "same_song", "title_localized": {"en": "New"}}])

        with self.assertRaises(RuntimeError):
            app.merge_staging_into_library_export(stage, self.out, fail_after_dirs=True)

        doc = json.loads((songs / "songlist").read_text(encoding="utf-8"))
        self.assertEqual(doc["songs"][0]["title_localized"]["en"], "Old")
        self.assertEqual((songs / "same_song" / "2.aff").read_text(encoding="utf-8"), "old")


class V21ExportTargetUiTests(unittest.TestCase):
    class _SongBox:
        def findText(self, _text):
            return -1

        def currentText(self):
            return "song"

    class _Speed:
        def __init__(self):
            self.value = "1.0"

        def setText(self, text):
            self.value = str(text)

        def text(self):
            return self.value

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

        def set_meta(self, meta):
            self.meta = dict(meta)

    class _Check:
        def __init__(self, checked=True):
            self.checked = checked
            self.enabled = True

        def setChecked(self, checked):
            self.checked = bool(checked)

        def isChecked(self):
            return self.checked

        def setEnabled(self, enabled):
            self.enabled = bool(enabled)

        def isEnabled(self):
            return self.enabled

    class _Layout:
        def addWidget(self, *_args, **_kwargs):
            pass

        def removeWidget(self, *_args, **_kwargs):
            pass

    def _window(self):
        win = object.__new__(app.MainWindow)
        win._song_box = self._SongBox()
        win._speed_input = self._Speed()
        win._rows = []
        win._songlist_panel = self._Panel()
        win._current_export_check = self._Check(True)
        win._library_export_check = self._Check(True)
        win._library_export_note = _Fake()
        win._segs_layout = self._Layout()
        win._refresh_seg_header = lambda: None
        win._schedule_arc_cut_warning_refresh = lambda: None
        return win

    def test_old_slides_defaults_export_targets_true_and_songlist_false(self):
        win = self._window()

        app.MainWindow._apply_slides(win, {"segments": [], "songlist": {"title_base": "Old"}})

        self.assertFalse(win._songlist_panel.enabled)
        self.assertTrue(win._current_export_check.isChecked())
        self.assertTrue(win._library_export_check.isChecked())
        self.assertFalse(win._library_export_check.isEnabled())

    def test_collect_saves_export_target_preferences(self):
        win = self._window()
        win._songlist_panel.enabled = True
        win._current_export_check.setChecked(False)
        win._library_export_check.setChecked(True)

        data = app.MainWindow._collect(win)

        self.assertTrue(data["songlist_enabled"])
        self.assertFalse(data["current_export_enabled"])
        self.assertTrue(data["library_export_enabled"])

    def test_library_checkbox_reenabled_when_songlist_enabled(self):
        win = self._window()
        win._songlist_panel.enabled = False
        app.MainWindow._refresh_export_target_state(win)
        self.assertFalse(win._library_export_check.isEnabled())

        win._songlist_panel.enabled = True
        app.MainWindow._refresh_export_target_state(win)
        self.assertTrue(win._library_export_check.isEnabled())


if __name__ == "__main__":
    unittest.main()
