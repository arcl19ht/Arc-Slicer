"""Run UI clarity assertions in a real, isolated Qt process."""
import subprocess
import sys
import unittest


_SCRIPT = r'''
import os, tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication
import app
from arc_slicer.ui.main_window import MainWindowDependencies
from arc_slicer.ui.styles import application_qss

qapp = QApplication([])
qapp.setStyleSheet(app.QSS)
root = Path(tempfile.mkdtemp())
deps = MainWindowDependencies(config_path=root / "config.json", slides_path=root / "slides.json", out_dir=root / "out", default_songs_dir=root / "songs")
window = app.MainWindow(dependencies=deps)
window.resize(1200, 1200)
window.show()
qapp.processEvents()
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

def rgb(widget, x, y):
    qapp.processEvents()
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    widget.render(painter)
    painter.end()
    color = image.pixelColor(x, y)
    return color.red(), color.green(), color.blue()

# Sample padded button backgrounds instead of text pixels. The local content
# root must no longer flatten either primary button into the page background.
window._btn_run.setEnabled(True)
window._play_pause_button.setEnabled(True)
qapp.processEvents()
run_enabled = rgb(window._btn_run, 5, window._btn_run.height() // 2)
play_enabled = rgb(window._play_pause_button, 5, window._play_pause_button.height() // 2)
assert run_enabled[2] > run_enabled[0] + 80 and play_enabled[2] > play_enabled[0] + 80
window._btn_run.setEnabled(False)
window._play_pause_button.setEnabled(False)
qapp.processEvents()
run_disabled = rgb(window._btn_run, 5, window._btn_run.height() // 2)
play_disabled = rgb(window._play_pause_button, 5, window._play_pause_button.height() // 2)
assert run_disabled != run_enabled and play_disabled != play_enabled
assert max(run_disabled) - min(run_disabled) < 35 and max(play_disabled) - min(play_disabled) < 35

# Toggle thumbs travel across the painted track; export controls remain square
# checkboxes and expose a visible check stroke when checked.
toggle = window._auto_sort_check
toggle.setChecked(False)
left_thumb = rgb(toggle, 11, toggle.height() // 2)
right_track = rgb(toggle, 30, toggle.height() // 2)
toggle.setChecked(True)
right_thumb = rgb(toggle, 30, toggle.height() // 2)
left_track = rgb(toggle, 11, toggle.height() // 2)
assert min(left_thumb) > 220 and min(right_thumb) > 220
assert left_thumb != left_track and right_track != right_thumb
checkbox = window._current_export_check
checkbox.setChecked(False)
unchecked_box = rgb(checkbox, 3, checkbox.height() // 2)
checkbox.setChecked(True)
checked_box = rgb(checkbox, 3, checkbox.height() // 2)
assert unchecked_box != checked_box
assert checked_box[2] > checked_box[0] + 80
assert any(
    min(rgb(checkbox, x, y)) > 220
    for x in range(3, 15)
    for y in range(3, min(16, checkbox.height()))
)
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
