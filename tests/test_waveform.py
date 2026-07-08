import array
import json
import os
import tempfile
import unittest
from pathlib import Path

import app


def _pcm(values):
    samples = array.array("h", values)
    return samples.tobytes()


class WaveformDataTests(unittest.TestCase):
    def test_pcm_aggregation_normalizes_min_max_and_bucket_count(self):
        data = app.aggregate_pcm_waveform(
            _pcm([-32768, -16384, 0, 16384, 32767, 0, -8192, 8192]),
            sample_rate=8,
            samples_per_second=2,
        )

        self.assertEqual(data.duration_ms, 1000)
        self.assertEqual(data.samples_per_second, 2)
        self.assertEqual(len(data.peaks), 2)
        self.assertAlmostEqual(data.peaks[0][0], -1.0)
        self.assertAlmostEqual(data.peaks[0][1], 16384 / 32767.0)
        self.assertAlmostEqual(data.peaks[1][0], -8192 / 32768.0)
        self.assertAlmostEqual(data.peaks[1][1], 1.0)

    def test_empty_pcm_returns_empty_waveform(self):
        data = app.aggregate_pcm_waveform(b"", sample_rate=8000, samples_per_second=100)

        self.assertEqual(data.duration_ms, 0)
        self.assertEqual(data.samples_per_second, 100)
        self.assertEqual(data.peaks, [])

    def test_waveform_cache_key_uses_path_size_mtime_and_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            audio = Path(td) / "base.ogg"
            audio.write_bytes(b"abc")
            os.utime(audio, ns=(1_000_000_000, 1_000_000_000))

            key1 = app.waveform_cache_key(audio, 100)
            self.assertEqual(key1, app.waveform_cache_key(audio, 100))

            self.assertNotEqual(key1, app.waveform_cache_key(audio, 80))

            audio.write_bytes(b"abcd")
            os.utime(audio, ns=(1_000_000_000, 1_000_000_000))
            self.assertNotEqual(key1, app.waveform_cache_key(audio, 100))

            audio.write_bytes(b"abc")
            os.utime(audio, ns=(2_000_000_000, 2_000_000_000))
            self.assertNotEqual(key1, app.waveform_cache_key(audio, 100))

    def test_waveform_cache_read_write_and_corrupt_json(self):
        with tempfile.TemporaryDirectory() as td:
            cache_path = Path(td) / "wave.json"
            data = app.WaveformData(
                duration_ms=1234,
                samples_per_second=100,
                peaks=[(-0.25, 0.5), (-1.0, 1.0)],
            )

            app.write_waveform_cache(cache_path, data)
            loaded = app.read_waveform_cache(cache_path)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.duration_ms, 1234)
            self.assertEqual(loaded.samples_per_second, 100)
            self.assertEqual(loaded.peaks, data.peaks)

            cache_path.write_text("{bad json", encoding="utf-8")
            self.assertIsNone(app.read_waveform_cache(cache_path))

            cache_path.write_text(json.dumps({"version": 999}), encoding="utf-8")
            self.assertIsNone(app.read_waveform_cache(cache_path))


if __name__ == "__main__":
    unittest.main()
