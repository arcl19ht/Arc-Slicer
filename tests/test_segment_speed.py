import tempfile
import unittest
from pathlib import Path

import app


class SegmentSpeedPlanTests(unittest.TestCase):
    def test_speed_override_none_inherits_default(self):
        plan = app.build_segment_export_plan(
            "song",
            [{"s": 1000, "e": 3000, "speed_override": None}],
            0.75,
        )

        self.assertEqual(plan[0]["speed"], 0.75)
        self.assertEqual(plan[0]["id"], "song_1000_3000_x0p75")

    def test_old_segment_without_speed_override_inherits_default(self):
        plan = app.build_segment_export_plan("song", [{"s": 1000, "e": 3000}], 1.25)

        self.assertEqual(plan[0]["speed"], 1.25)
        self.assertEqual(plan[0]["id"], "song_1000_3000_x1p25")

    def test_explicit_override_wins_over_default(self):
        plan = app.build_segment_export_plan(
            "song",
            [{"s": 1000, "e": 3000, "speed_override": 0.5}],
            1.25,
        )

        self.assertEqual(plan[0]["speed"], 0.5)
        self.assertEqual(plan[0]["id"], "song_1000_3000_x0p5")

    def test_same_time_different_effective_speed_is_allowed(self):
        plan = app.build_segment_export_plan(
            "song",
            [
                {"s": 1000, "e": 3000, "speed_override": 0.5},
                {"s": 1000, "e": 3000, "speed_override": 0.75},
            ],
            1.0,
        )

        self.assertEqual([item["id"] for item in plan], ["song_1000_3000_x0p5", "song_1000_3000_x0p75"])

    def test_same_time_same_effective_speed_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "第 1 与第 2 个时间段输出 ID 重复: song_1000_3000_x0p75"):
            app.build_segment_export_plan(
                "song",
                [
                    {"s": 1000, "e": 3000, "speed_override": None},
                    {"s": 1000, "e": 3000},
                ],
                0.75,
            )

    def test_invalid_override_is_rejected_before_staging(self):
        old_out_dir = app.OUT_DIR
        old_get_ffmpeg = app._get_ffmpeg
        old_stage = app.create_current_export_stage
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app.OUT_DIR = root / "out"
                songs_dir = root / "songs"
                song_dir = songs_dir / "song"
                song_dir.mkdir(parents=True)
                (song_dir / "base.ogg").write_bytes(b"audio")
                (song_dir / "2.aff").write_text("-\n", encoding="utf-8")
                app._get_ffmpeg = lambda: "ffmpeg"
                app.create_current_export_stage = lambda *args, **kwargs: (_ for _ in ()).throw(
                    AssertionError("staging should not be created")
                )
                logs = []

                code = app.do_slice(
                    songs_dir,
                    "song",
                    [{"s": 1000, "e": 3000, "speed_override": -1}],
                    1.0,
                    lambda text, kind="normal": logs.append((text, kind)),
                    current_export_enabled=True,
                    library_export_enabled=False,
                )

                self.assertEqual(code, 1)
                self.assertTrue(any("倍速无效" in text for text, _kind in logs))
        finally:
            app.OUT_DIR = old_out_dir
            app._get_ffmpeg = old_get_ffmpeg
            app.create_current_export_stage = old_stage

    def test_duplicate_effective_id_is_rejected_before_staging(self):
        old_out_dir = app.OUT_DIR
        old_get_ffmpeg = app._get_ffmpeg
        old_stage = app.create_current_export_stage
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app.OUT_DIR = root / "out"
                songs_dir = root / "songs"
                song_dir = songs_dir / "song"
                song_dir.mkdir(parents=True)
                (song_dir / "base.ogg").write_bytes(b"audio")
                (song_dir / "2.aff").write_text("-\n", encoding="utf-8")
                app._get_ffmpeg = lambda: "ffmpeg"
                app.create_current_export_stage = lambda *args, **kwargs: (_ for _ in ()).throw(
                    AssertionError("staging should not be created")
                )
                logs = []

                code = app.do_slice(
                    songs_dir,
                    "song",
                    [
                        {"s": 1000, "e": 3000, "speed_override": 0.75},
                        {"s": 1000, "e": 3000, "speed_override": 0.75},
                    ],
                    1.0,
                    lambda text, kind="normal": logs.append((text, kind)),
                    current_export_enabled=True,
                    library_export_enabled=False,
                )

                self.assertEqual(code, 1)
                self.assertTrue(any("输出 ID 重复" in text for text, _kind in logs))
        finally:
            app.OUT_DIR = old_out_dir
            app._get_ffmpeg = old_get_ffmpeg
            app.create_current_export_stage = old_stage


if __name__ == "__main__":
    unittest.main()
