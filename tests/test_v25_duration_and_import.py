import tempfile
import unittest
from pathlib import Path

import app


class MultiDifficultyDurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.songs = self.root / "songs"
        self.song = self.songs / "song"
        self.song.mkdir(parents=True)
        for name in ("base.ogg", "2.aff", "3.aff", "3.ogg", "4.ogg"):
            (self.song / name).write_text("-\n", encoding="utf-8")
        self.out = self.root / "out"
        self.old_out, self.old_ffmpeg = app.OUT_DIR, app._get_ffmpeg
        app.OUT_DIR, app._get_ffmpeg = self.out, lambda: "ffmpeg"
        self.calls = []
        self.old_ogg, self.old_aff = app.slice_ogg, app.slice_aff
        app.slice_ogg = lambda *args: self.calls.append(("ogg", Path(args[0]).name))
        app.slice_aff = lambda *args, **_kwargs: self.calls.append(("aff",)) or "-\n"

    def tearDown(self):
        app.OUT_DIR, app._get_ffmpeg = self.old_out, self.old_ffmpeg
        app.slice_ogg, app.slice_aff = self.old_ogg, self.old_aff
        self.temp.cleanup()

    def _run(self, selected, duration_getter, segments=None):
        logs = []
        return app.do_slice(
            self.songs, "song", segments or [{"s": 100, "e": 900}], 1.0,
            lambda text, kind="normal": logs.append((text, kind)),
            current_export_enabled=True, library_export_enabled=False,
            selected_difficulties=selected, duration_getter=duration_getter,
        ), logs

    def test_short_selected_override_blocks_before_staging_or_slice(self):
        probes = []
        def probe(path):
            probes.append(Path(path).name)
            return 800 if Path(path).name == "3.ogg" else 1_000
        code, logs = self._run([2, 3], probe)
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.out.exists())
        self.assertEqual(probes, ["base.ogg", "3.ogg"])
        self.assertIn("3.ogg", "\n".join(text for text, _kind in logs))

    def test_short_base_blocks_before_staging_or_slice(self):
        code, _logs = self._run([2], lambda _path: 800)
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.out.exists())

    def test_unused_and_orphan_short_override_do_not_block_and_sources_probe_once(self):
        probes = []
        code, _logs = self._run(
            [2], lambda path: probes.append(Path(path).name) or 1_000,
            [{"s": 100, "e": 900}, {"s": 100, "e": 800}],
        )
        self.assertEqual(code, 0)
        self.assertEqual(probes, ["base.ogg"])
        self.assertEqual([call for call in self.calls if call[0] == "ogg"], [("ogg", "base.ogg"), ("ogg", "base.ogg")])

    def test_second_audio_or_chart_failure_cleans_staging(self):
        audio_calls = []
        def fail_second_audio(source, *_args):
            audio_calls.append(Path(source).name)
            if len(audio_calls) == 2:
                raise app.subprocess.CalledProcessError(1, "ffmpeg")
        old_ogg = app.slice_ogg
        app.slice_ogg = fail_second_audio
        try:
            code, _logs = self._run([2, 3], lambda _path: 1_000)
        finally:
            app.slice_ogg = old_ogg
        self.assertEqual(code, 1)
        self.assertEqual(audio_calls, ["base.ogg", "3.ogg"])
        self.assertFalse(app.current_export_root(self.out).exists())

        old_aff = app.slice_aff
        app.slice_aff = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad aff"))
        try:
            code, _logs = self._run([2], lambda _path: 1_000)
        finally:
            app.slice_aff = old_aff
        self.assertEqual(code, 1)
        self.assertFalse(app.current_export_root(self.out).exists())


class ImportValidationTests(unittest.TestCase):
    def test_import_accepts_standard_subsets_and_rejects_invalid_before_target_creation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            songs = root / "songs"
            valid = root / "byd"
            valid.mkdir()
            (valid / "base.ogg").write_bytes(b"audio")
            (valid / "3.aff").write_text("-\n", encoding="utf-8")
            ok, _msg, song_id = app.import_song_folder(valid, songs)
            self.assertTrue(ok)
            self.assertEqual(song_id, "byd")

            invalid = root / "invalid"
            invalid.mkdir()
            (invalid / "base.ogg").write_bytes(b"audio")
            (invalid / "unknown.aff").write_text("-\n", encoding="utf-8")
            absent_target = root / "other_songs"
            ok, _msg, song_id = app.import_song_folder(invalid, absent_target)
            self.assertFalse(ok)
            self.assertIsNone(song_id)
            self.assertFalse(absent_target.exists())
