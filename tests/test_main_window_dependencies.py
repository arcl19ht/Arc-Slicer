import tempfile
import unittest
from pathlib import Path

import app
from arc_slicer.ui.main_window import MainWindowDependencies


class _FakeFileDialog:
    @staticmethod
    def getExistingDirectory(*_args, **_kwargs):
        return ""


class _FakeMessageBox:
    class StandardButton:
        Ok = 1
        Cancel = 2

    @staticmethod
    def question(*_args, **_kwargs):
        return _FakeMessageBox.StandardButton.Cancel

    @staticmethod
    def warning(*_args, **_kwargs):
        return None


class _FakeWorker:
    pass


class _Target:
    pass


class MainWindowDependencyTests(unittest.TestCase):
    def test_dependency_object_exposes_facade_sensitive_symbols(self):
        deps = MainWindowDependencies()
        self.assertTrue(hasattr(deps, "config_path"))
        self.assertTrue(hasattr(deps, "slides_path"))
        self.assertTrue(hasattr(deps, "external_merge_worker_cls"))
        self.assertTrue(hasattr(deps, "file_dialog_cls"))
        self.assertTrue(hasattr(deps, "message_box_cls"))

    def test_app_facade_injects_current_monkeypatched_symbols_for_uninitialized_targets(self):
        target = _Target()
        old_values = {
            "CONFIG_PATH": app.CONFIG_PATH,
            "SLIDES_PATH": app.SLIDES_PATH,
            "OUT_DIR": app.OUT_DIR,
            "ExternalMergeWorker": app.ExternalMergeWorker,
            "SlicerWorker": app.SlicerWorker,
            "WaveformWorker": app.WaveformWorker,
            "QFileDialog": app.QFileDialog,
            "QMessageBox": app.QMessageBox,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            try:
                app.CONFIG_PATH = root / "config.json"
                app.SLIDES_PATH = root / "slides.json"
                app.OUT_DIR = root / "out"
                app.ExternalMergeWorker = _FakeWorker
                app.SlicerWorker = _FakeWorker
                app.WaveformWorker = _FakeWorker
                app.QFileDialog = _FakeFileDialog
                app.QMessageBox = _FakeMessageBox

                app.MainWindow._ensure_facade_dependencies(target)
            finally:
                for name, value in old_values.items():
                    setattr(app, name, value)

        self.assertEqual(target._deps.config_path, root / "config.json")
        self.assertEqual(target._deps.slides_path, root / "slides.json")
        self.assertEqual(target._deps.out_dir, root / "out")
        self.assertIs(target._deps.external_merge_worker_cls, _FakeWorker)
        self.assertIs(target._deps.slicer_worker_cls, _FakeWorker)
        self.assertIs(target._deps.waveform_worker_cls, _FakeWorker)
        self.assertIs(target._deps.file_dialog_cls, _FakeFileDialog)
        self.assertIs(target._deps.message_box_cls, _FakeMessageBox)


if __name__ == "__main__":
    unittest.main()
