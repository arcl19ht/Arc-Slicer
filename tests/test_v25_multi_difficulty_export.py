import json
import tempfile
import unittest
from pathlib import Path

import app


class MultiDifficultyFormalExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.songs = self.root / "songs"
        self.song = self.songs / "multi"
        self.song.mkdir(parents=True)
        (self.song / "base.ogg").write_bytes(b"base")
        (self.song / "2.aff").write_text("AudioOffset:0\n-\n", encoding="utf-8")
        (self.song / "3.aff").write_text("AudioOffset:0\n-\n", encoding="utf-8")
        (self.song / "3.ogg").write_bytes(b"byd")
        self.out = self.root / "out"
        self.old_out, self.old_ffmpeg = app.OUT_DIR, app._get_ffmpeg
        self.old_ogg, self.old_aff = app.slice_ogg, app.slice_aff
        app.OUT_DIR = self.out
        app._get_ffmpeg = lambda: "ffmpeg"
        self.audio_calls, self.chart_calls, self.logs = [], [], []

        def fake_ogg(source, destination, start, end, speed):
            self.audio_calls.append((Path(source).name, Path(destination).name, start, end, speed))
            Path(destination).write_bytes(b"sliced")

        def fake_aff(source_text, start, end, speed, warnings=None):
            self.chart_calls.append((source_text, start, end, speed))
            if warnings is not None and "3" in source_text:
                warnings.append("chart warning")
            return "AudioOffset:0\n-\n"

        app.slice_ogg, app.slice_aff = fake_ogg, fake_aff

    def tearDown(self):
        app.OUT_DIR, app._get_ffmpeg = self.old_out, self.old_ffmpeg
        app.slice_ogg, app.slice_aff = self.old_ogg, self.old_aff
        self.temp.cleanup()

    def _log(self, text, kind="normal"):
        self.logs.append((text, kind))

    def _run(self, *, selected=None, songlist=False, metadata=None):
        return app.do_slice(
            self.songs, "multi", [{"s": 1000, "e": 2000}], 1.0, self._log,
            {
                "title_base": "Multi", "artist": "Artist", "bpm": "120", "bpm_base": "120",
                "set": "single", "purchase": "", "side": "0", "bg": "", "version": "",
                "chart_designer": "Chart", "jacket_designer": "Jacket", "rating": "9",
            },
            songlist, None, True, False, False, None, selected, metadata,
        )

    def test_ftr_only_legacy_call_keeps_base_and_two_aff(self):
        self.assertEqual(self._run(), 0, self.logs)
        target = app.current_export_songs_dir(self.out) / "multi_1000_2000_x1"
        self.assertTrue((target / "base.ogg").is_file())
        self.assertTrue((target / "2.aff").is_file())
        self.assertFalse((target / "3.aff").exists())
        self.assertEqual([item[:2] for item in self.audio_calls], [("base.ogg", "base.ogg")])

    def test_selected_charts_and_override_audio_share_one_segment_directory_and_song_entry(self):
        metadata = {
            2: {"rating": 9, "chart_designer": "FTR", "jacket_designer": "Jacket"},
            3: {"rating": 10, "chart_designer": "BYD", "jacket_designer": "Jacket"},
        }
        self.assertEqual(self._run(selected=[2, 3], songlist=True, metadata=metadata), 0, self.logs)
        target = app.current_export_songs_dir(self.out) / "multi_1000_2000_x1"
        self.assertTrue((target / "base.ogg").is_file())
        self.assertTrue((target / "3.ogg").is_file())
        self.assertTrue((target / "2.aff").is_file())
        self.assertTrue((target / "3.aff").is_file())
        self.assertEqual([item[:2] for item in self.audio_calls], [("base.ogg", "base.ogg"), ("3.ogg", "3.ogg")])
        songlist = json.loads((app.current_export_songs_dir(self.out) / "songlist").read_text(encoding="utf-8"))["songs"]
        self.assertEqual(len(songlist), 1)
        self.assertEqual([item["ratingClass"] for item in songlist[0]["difficulties"]], [0, 1, 2, 3])
        self.assertTrue(songlist[0]["difficulties"][3]["audioOverride"])

    def test_unselected_override_audio_is_not_sliced(self):
        self.assertEqual(self._run(selected=[2]), 0, self.logs)
        self.assertEqual([item[0] for item in self.audio_calls], ["base.ogg"])

    def test_invalid_songlist_metadata_fails_before_publication(self):
        self.assertEqual(self._run(selected=[2, 3], songlist=True, metadata={2: {"rating": 9}}), 1)
        self.assertFalse(app.current_export_root(self.out).exists())
        self.assertEqual(self.audio_calls, [])

