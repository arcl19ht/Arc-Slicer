import tempfile
import unittest
from pathlib import Path

try:
    from PyQt6.QtCore import QMimeData, QUrl
    from PyQt6.QtWidgets import QApplication
except ImportError:
    QMimeData = QUrl = QApplication = None

from arc_slicer.ui.metadata_panel import DropZone


class _DropEvent:
    def __init__(self, mime_data):
        self._mime_data = mime_data

    def mimeData(self):
        return self._mime_data


@unittest.skipIf(QUrl is None, "requires the real PyQt drag-and-drop surface")
class MetadataPanelDropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = QApplication.instance() or QApplication([])

    @staticmethod
    def _event_for(path: Path) -> _DropEvent:
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(path))])
        return _DropEvent(mime_data)

    def test_directory_drop_emits_folder_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zone = DropZone()
            folders = []
            invalid = []
            zone.folder_dropped.connect(folders.append)
            zone.invalid_dropped.connect(invalid.append)

            zone.dropEvent(self._event_for(Path(temp_dir)))

            self.assertEqual([Path(path) for path in folders], [Path(temp_dir)])
            self.assertEqual(invalid, [])

    def test_file_drop_remains_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "not-a-folder.aff"
            file_path.write_text("-\n", encoding="utf-8")
            zone = DropZone()
            folders = []
            invalid = []
            zone.folder_dropped.connect(folders.append)
            zone.invalid_dropped.connect(invalid.append)

            zone.dropEvent(self._event_for(file_path))

            self.assertEqual(folders, [])
            self.assertEqual(invalid, ["请拖入歌曲文件夹，而不是单个文件。"])


if __name__ == "__main__":
    unittest.main()
