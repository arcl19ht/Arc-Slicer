"""Run UI clarity assertions in a real, isolated Qt process."""
import subprocess
import sys
import unittest


_SCRIPT = r'''
import os, tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
import app
from arc_slicer.ui.main_window import MainWindowDependencies
from arc_slicer.ui.styles import application_qss

qapp = QApplication([])
root = Path(tempfile.mkdtemp())
deps = MainWindowDependencies(config_path=root / "config.json", slides_path=root / "slides.json", out_dir=root / "out", default_songs_dir=root / "songs")
window = app.MainWindow(dependencies=deps)
assert window._song_box.objectName() == "comboInput"
assert window._play_pause_button.objectName() == "btnPlayback"
assert window._btn_run.objectName() == "btnRun"
assert [window._sort_mode_box.itemData(i) for i in range(window._sort_mode_box.count())] == ["time", "speed"]
assert window._btn_external_confirm.objectName() == "btnPrimary"
assert window._songlist_panel._pack_section.objectName() == "comboInput"
window._auto_sort_check.setChecked(False)
window._on_auto_sort_changed()
assert not window._auto_sort_enabled and not window._sort_mode_box.isEnabled()
window._apply_slides({"sort_mode": "manual", "segments": []})
assert not window._auto_sort_enabled and not window._auto_sort_check.isChecked()
assert not window._sort_mode_box.isEnabled() and window._sort_mode_box.currentData() == "time"
qss = application_qss()
assert "QLabel { background: transparent; border: none; }" in qss
assert "QComboBox::down-arrow" not in qss and "width: 0; height: 0" not in qss
assert "QPushButton#btnPlayback" in qss and "QPushButton#btnRun:disabled" in qss
window.close()
'''


class UiClarityTests(unittest.TestCase):
    def test_real_qt_controls_express_their_interaction_semantics(self):
        env = dict(__import__("os").environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, env=env)
        output = (result.stderr or result.stdout).decode("utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, output)


if __name__ == "__main__":
    unittest.main()
