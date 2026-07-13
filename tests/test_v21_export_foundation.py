import os
import shutil
import tempfile
import types
import unittest
from pathlib import Path


class _Fake:
    def __init__(self, *args, **kwargs):
        self._text = str(args[0]) if args else ""
        self._visible = True

    def __call__(self, *args, **kwargs):
        return _Fake()

    def __getattr__(self, name):
        if name in ("textChanged", "clicked", "timeout"):
            return _FakeSignal()
        return _Fake()

    def __or__(self, other):
        return self

    def setText(self, text):
        self._text = str(text)

    def text(self):
        return self._text

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


class V21NamingTests(unittest.TestCase):
    def test_normalize_speed_token(self):
        cases = {
            1.0: "1",
            1.00: "1",
            1.25: "1p25",
            0.75: "0p75",
            2.50: "2p5",
            1.2000000000000002: "1p2",
        }
        for speed, expected in cases.items():
            with self.subTest(speed=speed):
                token = app.normalize_speed_token(speed)
                self.assertEqual(token, expected)
                self.assertNotIn("e", token.lower())
                self.assertNotIn("0000000000000002", token)

    def test_build_segment_id(self):
        self.assertEqual(
            app.build_segment_id("prelude_heavensdoor", 21000, 22000, 1.25),
            "prelude_heavensdoor_21000_22000_x1p25",
        )

    def test_build_segment_display_title(self):
        title = app.build_segment_display_title("Prelude", 21000, 22000, 1.25)
        self.assertEqual(title, "Prelude [21000–22000ms · 1.25×]")


class V21ExportPathTests(unittest.TestCase):
    def test_path_model_does_not_create_library_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"

            self.assertEqual(app.current_export_songs_dir(out), out / "current_export" / "songs")
            self.assertEqual(app.library_export_songs_dir(out), out / "library_export" / "songs")
            self.assertFalse((out / "library_export").exists())

    def test_publish_current_export_stage_replaces_current_only(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            current = app.current_export_root(out)
            library = app.library_export_root(out)
            (current / "songs" / "old_song").mkdir(parents=True)
            (current / "songs" / "old_song" / "old.txt").write_text("old", encoding="utf-8")
            library.mkdir(parents=True)
            (library / "sentinel.txt").write_text("keep", encoding="utf-8")

            stage = app.create_current_export_stage(out)
            (stage / "songs" / "new_song").mkdir()
            (stage / "songs" / "new_song" / "new.txt").write_text("new", encoding="utf-8")

            app.publish_current_export_stage(stage, out)

            self.assertTrue((current / "songs" / "new_song" / "new.txt").exists())
            self.assertFalse((current / "songs" / "old_song").exists())
            self.assertEqual((library / "sentinel.txt").read_text(encoding="utf-8"), "keep")
            self.assertFalse(stage.exists())
            self.assertEqual(list(out.glob(".current_export_backup_*")), [])

    def test_publish_rejects_library_as_stage(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            library = app.library_export_root(out)
            library.mkdir(parents=True)
            (library / "sentinel.txt").write_text("keep", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                app.publish_current_export_stage(library, out)

            self.assertEqual((library / "sentinel.txt").read_text(encoding="utf-8"), "keep")

    def test_publish_failure_restores_old_current(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            current = app.current_export_root(out)
            (current / "songs" / "old_song").mkdir(parents=True)
            (current / "songs" / "old_song" / "old.txt").write_text("old", encoding="utf-8")
            stage = app.create_current_export_stage(out)
            (stage / "songs" / "new_song").mkdir()

            def rename_fn(src, dest):
                src = Path(src)
                if src == stage:
                    raise OSError("boom")
                return src.rename(dest)

            def rmtree_fn(path):
                path = Path(path)
                if path == stage:
                    raise OSError("stage cleanup failed")
                return shutil.rmtree(path)

            with self.assertRaises(RuntimeError):
                app.publish_current_export_stage(stage, out, rename_fn=rename_fn, rmtree_fn=rmtree_fn)

            self.assertTrue((current / "songs" / "old_song" / "old.txt").exists())

    def test_publish_first_rename_failure_keeps_old_current(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            current = app.current_export_root(out)
            (current / "songs" / "old_song").mkdir(parents=True)
            (current / "songs" / "old_song" / "old.txt").write_text("old", encoding="utf-8")
            stage = app.create_current_export_stage(out)
            (stage / "songs" / "new_song").mkdir()

            def rename_fn(src, dest):
                src = Path(src)
                if src == current:
                    raise OSError("locked")
                return src.rename(dest)

            def rmtree_fn(path):
                path = Path(path)
                if path == current:
                    raise OSError("locked")
                return shutil.rmtree(path)

            with self.assertRaises(RuntimeError):
                app.publish_current_export_stage(stage, out, rename_fn=rename_fn, rmtree_fn=rmtree_fn)

            self.assertTrue((current / "songs" / "old_song" / "old.txt").exists())
            self.assertFalse((current / "songs" / "new_song").exists())
            self.assertFalse(stage.exists())


class V21JacketCopyTests(unittest.TestCase):
    def test_copy_all_existing_jackets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src"
            dest = root / "dest"
            src.mkdir()
            for name in app.JACKET_FILENAMES:
                (src / name).write_text(name, encoding="utf-8")

            copied = app.copy_song_jackets(src, dest)

            self.assertEqual({p.name for p in copied}, set(app.JACKET_FILENAMES))
            for name in app.JACKET_FILENAMES:
                self.assertEqual((dest / name).read_text(encoding="utf-8"), name)

    def test_copy_only_present_jackets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src"
            dest = root / "dest"
            src.mkdir()
            (src / "1080_base_256.jpg").write_text("thumb", encoding="utf-8")

            copied = app.copy_song_jackets(src, dest)

            self.assertEqual([p.name for p in copied], ["1080_base_256.jpg"])
            self.assertTrue((dest / "1080_base_256.jpg").exists())
            self.assertFalse((dest / "base.jpg").exists())


class V21DoSliceFoundationTests(unittest.TestCase):
    def test_do_slice_writes_current_export_and_not_legacy_root(self):
        old_out_dir = app.OUT_DIR
        old_get_ffmpeg = app._get_ffmpeg
        old_slice_ogg = app.slice_ogg
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app.OUT_DIR = root / "out"
            songs_dir = root / "songs"
            song = songs_dir / "prelude_heavensdoor"
            song.mkdir(parents=True)
            (song / "base.ogg").write_bytes(b"audio")
            (song / "2.aff").write_text("AudioOffset:0\n-\ntiming(0,100.00,4.00);\n", encoding="utf-8")
            for name in app.JACKET_FILENAMES:
                (song / name).write_text(name, encoding="utf-8")
            legacy_root = app.OUT_DIR / "songs"
            legacy_root.mkdir(parents=True)
            (legacy_root / "sentinel.txt").write_text("old", encoding="utf-8")

            app._get_ffmpeg = lambda: "ffmpeg"

            def fake_slice_ogg(_in_path, out_path, _start_ms, _end_ms, _speed):
                Path(out_path).write_bytes(b"ogg")

            app.slice_ogg = fake_slice_ogg
            logs = []
            try:
                code = app.do_slice(
                    songs_dir,
                    "prelude_heavensdoor",
                    [{"s": 21000, "e": 22000}],
                    1.25,
                    lambda text, kind="normal": logs.append((text, kind)),
                    duration_getter=lambda _path: 120_000,
                )
            finally:
                app.OUT_DIR = old_out_dir
                app._get_ffmpeg = old_get_ffmpeg
                app.slice_ogg = old_slice_ogg

            segment_id = "prelude_heavensdoor_21000_22000_x1p25"
            out_song = root / "out" / "current_export" / "songs" / segment_id
            self.assertEqual(code, 0, logs)
            self.assertTrue((out_song / "base.ogg").exists())
            self.assertTrue((out_song / "2.aff").exists())
            for name in app.JACKET_FILENAMES:
                self.assertTrue((out_song / name).exists())
            self.assertEqual((legacy_root / "sentinel.txt").read_text(encoding="utf-8"), "old")
            self.assertFalse((legacy_root / segment_id).exists())
            self.assertFalse((root / "out" / "library_export").exists())
            self.assertFalse((out_song / "songlist_fragment.json").exists())


if __name__ == "__main__":
    unittest.main()
