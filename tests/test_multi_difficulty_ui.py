"""Real Qt coverage for the V2.5-B song-level difficulty controls."""
import subprocess
import sys
import unittest


_SCRIPT = r'''
import json, os, tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
import app
from arc_slicer.ui.main_window import MainWindowDependencies

root = Path(tempfile.mkdtemp())
songs = root / "songs"
song = songs / "multi"
song.mkdir(parents=True)
for name in ("base.ogg", "0.aff", "2.aff", "3.aff", "3.ogg", "bonus.aff", "4.ogg"):
    (song / name).write_bytes(b"x")
(root / "config.json").write_text(json.dumps({"songs_dir": str(songs)}), encoding="utf-8")
qapp = QApplication([])
app.MainWindow._request_waveform_for_current_song = lambda self: None
app.MainWindow._refresh_current_audio_duration = lambda self: None
deps = MainWindowDependencies(config_path=root / "config.json", slides_path=root / "slides.json", out_dir=root / "out", default_songs_dir=songs)
window = app.MainWindow(dependencies=deps)
window.show(); qapp.processEvents()
assert window._difficulty_panel.objectName() == "difficultyPanel"
assert window._difficulty_panel.parentWidget() is window._scroll.widget()
assert [window.findChild(type(window._difficulty_panel), f"difficultyRow{i}") is not None for i in (0, 2, 3)] == [True, True, True]
assert window.findChild(type(window._difficulty_panel), "difficultyRow1") is None
assert window.findChild(type(window._difficulty_panel), "difficultyRow4") is None
assert window.findChild(type(window._difficulty_panel), "difficultyAudioBadge3") is not None
assert "未知 AFF" in window._difficulty_notice.text() and "孤立" in window._difficulty_notice.text()
assert window._preview_audio_box.isVisible()
assert [window._preview_audio_box.itemData(i) for i in range(window._preview_audio_box.count())] == ["base.ogg", "3.ogg"]
for rating_class in (0, 2, 3):
    window.findChild(type(window._current_export_check), f"difficultyCheck{rating_class}").setChecked(False)
    qapp.processEvents()
assert not window._selected_difficulties and not window._btn_run.isEnabled(), (window._selected_difficulties, window._btn_run.isEnabled())
assert "至少需要" in window._difficulty_notice.text()
window.close()
'''


class MultiDifficultyUiTests(unittest.TestCase):
    def test_real_qt_panel_uses_discovery_and_prevents_empty_export_selection(self):
        result = subprocess.run(
            [sys.executable, "-c", _SCRIPT],
            capture_output=True,
            env=dict(__import__("os").environ, QT_QPA_PLATFORM="offscreen"),
        )
        output = (result.stderr or result.stdout).decode("utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, output)

    def test_missing_saved_selection_can_be_cleared_without_losing_metadata(self):
        script = r'''
import json, os, tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
import app
from arc_slicer.difficulties import DifficultyMetadata
from arc_slicer.ui.main_window import MainWindowDependencies
root = Path(tempfile.mkdtemp()); songs = root / "songs"; song = songs / "multi"; song.mkdir(parents=True)
for name in ("base.ogg", "2.aff"): (song / name).write_bytes(b"x")
(root / "config.json").write_text(json.dumps({"songs_dir": str(songs)}), encoding="utf-8")
qapp = QApplication([])
app.MainWindow._request_waveform_for_current_song = lambda self: None
app.MainWindow._refresh_current_audio_duration = lambda self: None
deps = MainWindowDependencies(config_path=root / "config.json", slides_path=root / "slides.json", out_dir=root / "out", default_songs_dir=songs)
window = app.MainWindow(dependencies=deps)
window._selected_difficulties = (3,)
window._difficulty_metadata[3] = DifficultyMetadata(3, 10, chart_designer="Keep")
window._refresh_difficulty_panel(); qapp.processEvents()
button = window.findChild(type(window._btn_run), "clearMissingDifficultySelection")
assert "3.aff" in window._difficulty_notice.text() and not button.isHidden()
assert button.accessibleName() and button.focusPolicy().name == "StrongFocus"
button.click(); qapp.processEvents()
assert window._selected_difficulties == () and 3 in window._difficulty_metadata and not window._btn_run.isEnabled()
window.close()
'''
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True,
            env=dict(__import__("os").environ, QT_QPA_PLATFORM="offscreen"),
        )
        output = (result.stderr or result.stdout).decode("utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, output)
