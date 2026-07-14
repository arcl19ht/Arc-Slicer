import os
import subprocess
import sys
import unittest


_SCRIPT = r'''
from PyQt6.QtWidgets import QApplication, QLineEdit
from arc_slicer.difficulties import DifficultyMetadata, STANDARD_DIFFICULTIES
from arc_slicer.ui.metadata_panel import SonglistPanel

app = QApplication([])
panel = SonglistPanel(); panel.set_songlist_enabled(True)
metadata = {2: DifficultyMetadata(2, 9, False, "Common", "Jacket", ""), 3: DifficultyMetadata(3, 10, True, "", "", "Last | Moment")}
panel.set_difficulty_context(STANDARD_DIFFICULTIES, {2, 3}, metadata, {3: "3.ogg"})
assert panel.findChild(QLineEdit, "songlistDifficultyRating2") is not None
assert panel.findChild(QLineEdit, "songlistDifficultyRating3") is not None
assert panel.findChild(QLineEdit, "songlistDifficultyRating0") is None
assert panel.findChild(QLineEdit, "difficultyRating2") is None
assert panel.findChild(QLineEdit, "rating") is None
seen=[]; panel.difficulty_metadata_changed.connect(lambda rc, data: seen.append((rc, data)))
card = panel.findChild(QLineEdit, "songlistDifficultyRating3"); card.setText("11"); card.editingFinished.emit()
assert seen and seen[-1][0] == 3 and seen[-1][1]["rating"] == 11
panel.set_difficulty_context(STANDARD_DIFFICULTIES, {3}, metadata, {3: "3.ogg"})
assert panel.findChild(QLineEdit, "songlistDifficultyRating2") is None
assert panel.findChild(QLineEdit, "songlistDifficultyRating3") is not None
'''


class DifficultyMetadataUiTests(unittest.TestCase):
    def test_selected_difficulties_render_only_songlist_metadata_cards(self):
        env = os.environ.copy(); env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run([sys.executable, "-c", _SCRIPT], text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
