import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsBuildEntryTests(unittest.TestCase):
    def test_build_batch_is_repository_venv_only_and_noninteractive(self):
        text = (ROOT / "build.bat").read_text(encoding="utf-8").lower()

        self.assertIn(r".venv\scripts\python.exe", text)
        self.assertIn(r'"%python%" -c "import pyqt6, pyinstaller"', text)
        self.assertIn(r'"%python%" -m pyinstaller', text)
        self.assertIn("--clean --noconfirm", text)

        for forbidden in (
            "where python",
            "pip install",
            "rmdir",
            "__pycache__",
            "explorer",
            "pause",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_spec_builds_the_windowed_one_file_app_with_bundled_ffmpeg(self):
        text = (ROOT / "build.spec").read_text(encoding="utf-8")

        self.assertIn('HERE / "app.py"', text)
        self.assertIn('HERE / "ffmpeg.exe"', text)
        self.assertIn('datas.append((str(FFMPEG), "."))', text)
        self.assertIn('name="ArcSlicer"', text)
        self.assertIn("a.binaries", text)
        self.assertIn("a.datas", text)
        self.assertIn("console=False", text)
        self.assertNotIn("COLLECT(", text)


if __name__ == "__main__":
    unittest.main()
