import unittest
from pathlib import Path

import app


class _Row:
    def __init__(self, s, e, speed=1.0, uid="row"):
        self.s_val = s
        self.e_val = e
        self._speed = speed
        self.uid = uid

    def effective_speed(self):
        return self._speed


class _TextRow:
    def __init__(self, start_text, end_text):
        self._start_text = start_text
        self._end_text = end_text
        try:
            self.s_val = int(start_text)
        except ValueError:
            self.s_val = None
        try:
            self.e_val = int(end_text)
        except ValueError:
            self.e_val = None

    def start_text(self):
        return self._start_text

    def end_text(self):
        return self._end_text


class WaveformUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def test_waveform_panel_states(self):
        panel = app.WaveformPanel()
        panel.set_draft_segments([{"index": 0, "kind": "start", "time_ms": 1000}])

        self.assertEqual(panel.status_text(), "选择源曲后显示波形")
        self.assertIsNone(panel.waveform_data())

        panel.set_loading()
        self.assertEqual(panel.status_text(), "正在生成波形…")
        self.assertIsNone(panel.waveform_data())
        self.assertEqual(panel.draft_segments(), [])

        panel.set_draft_segments([{"index": 1, "kind": "end", "time_ms": 2000}])
        data = app.WaveformData(duration_ms=4000, samples_per_second=100, peaks=[(-0.1, 0.2)])
        panel.set_waveform(data)
        self.assertEqual(panel.status_text(), "")
        self.assertIs(panel.waveform_data(), data)
        self.assertEqual(panel.draft_segments(), [{"index": 1, "kind": "end", "time_ms": 2000}])

        panel.set_error()
        self.assertEqual(panel.status_text(), "波形生成失败，不影响切片。")
        self.assertIsNone(panel.waveform_data())
        self.assertEqual(panel.draft_segments(), [])

        panel.set_draft_segments([{"index": 2, "kind": "start", "time_ms": 3000}])
        panel.set_empty()
        self.assertEqual(panel.draft_segments(), [])

    def test_theme_constants_are_neutral_not_warm_legacy_colors(self):
        self.assertEqual(app.C_BG, "#F4F6FB")
        self.assertEqual(app.C_CARD, "#FFFFFF")
        self.assertEqual(app.C_ACCENT, "#005BFF")
        self.assertNotIn(app.C_BG, {"#EDE9DF", "#FAF9F5", "#F2EFE7"})
        self.assertNotIn(app.C_CARD, {"#FAF9F5", "#F2EFE7"})
        self.assertNotIn(app.C_ACCENT, {"#C96442", "#B5573A"})

    def test_app_py_no_longer_contains_legacy_warm_theme_hexes(self):
        source = Path(app.__file__).read_text(encoding="utf-8")
        legacy = {
            "#EDE9DF", "#FAF9F5", "#F2EFE7", "#C96442", "#B5573A", "#F6E9E2",
            "#F7F1E7", "#E1D6C5", "#F1E6D7", "#D0BDA5", "#DED4C5", "#F4EEE3",
            "#FFF3EA", "#FBE2D5", "#D8CEC1", "#BFB4A6",
        }
        for color in legacy:
            self.assertNotIn(color, source)

    def test_waveform_panel_segment_ranges_are_cleaned(self):
        panel = app.WaveformPanel()

        panel.set_segments([(1000, 2000), (5000, 3000), ("bad", 7000), (3000, 5000)])
        panel.set_draft_segments([
            {"index": 0, "kind": "start", "time_ms": 6000},
            {"index": 1, "kind": "end", "time_ms": 7000},
        ])

        self.assertEqual(panel.segment_ranges(), [(1000, 2000), (3000, 5000)])
        self.assertEqual(
            panel.draft_segments(),
            [
                {"index": 0, "kind": "start", "time_ms": 6000},
                {"index": 1, "kind": "end", "time_ms": 7000},
            ],
        )

    def test_waveform_panel_splits_waveform_ruler_and_timeline_areas(self):
        panel = app.WaveformPanel()
        panel.resize(1024, 220)
        panel.set_waveform(app.WaveformData(duration_ms=10000, samples_per_second=100, peaks=[(-0.1, 0.2)]))

        waveform = panel._waveform_area_rect()
        ruler = panel._ruler_rect()
        timeline = panel._timeline_area_rect()

        self.assertGreater(waveform.height(), 0)
        self.assertGreater(ruler.height(), 0)
        self.assertGreater(timeline.height(), 0)
        self.assertLess(waveform.bottom(), ruler.top())
        self.assertLess(ruler.bottom(), timeline.top())
        self.assertEqual(panel._waveform_rect().top(), waveform.top())
        self.assertEqual(panel._waveform_rect().height(), waveform.height())
        self.assertEqual(panel.x_to_time_ms(panel.time_ms_to_x(5000)), 5000)

    def test_playback_head_position_clamps_and_uses_existing_time_mapping(self):
        panel = app.WaveformPanel()
        panel.resize(1024, 220)
        panel.set_waveform(app.WaveformData(duration_ms=10000, samples_per_second=100, peaks=[(-0.1, 0.2)]))
        panel.set_quick_draft_anchor(3000)
        panel.set_playback_position_ms(12000)
        self.assertEqual(panel.playback_position_ms(), 10000)
        self.assertEqual(panel.x_to_time_ms(panel.time_ms_to_x(panel.playback_position_ms())), 10000)
        self.assertEqual(panel.quick_draft_anchor_ms(), 3000)
        panel.set_playback_position_ms(None)
        self.assertIsNone(panel.playback_position_ms())

    def test_timeline_expanded_prefers_enough_height_for_five_lanes(self):
        panel = app.WaveformPanel()
        panel.set_segments([
            (1000, 2000, "seg_1", (1000, 2000)),
            (2000, 3000, "seg_2", (2000, 3000)),
            (3000, 4000, "seg_3", (3000, 4000)),
            (4000, 5000, "seg_4", (4000, 5000)),
            (5000, 6000, "seg_5", (5000, 6000)),
        ])
        self.assertTrue(panel.timeline_expanded())
        panel.resize(1024, panel.sizeHint().height())

        timeline = panel._timeline_area_rect()
        fifth_lane = panel._lane_rect(4)
        self.assertGreaterEqual(fifth_lane.top(), timeline.top())
        self.assertLessEqual(fifth_lane.bottom(), timeline.bottom())
        self.assertEqual(panel._timeline_scroll_max(), 0)

    def test_timeline_uses_resize_grip_instead_of_text_toggle(self):
        panel = app.WaveformPanel()
        panel.set_segments([(i * 1000, i * 1000 + 800, f"seg_{i}", (i, i + 1)) for i in range(1, 6)])
        panel.resize(1024, panel.sizeHint().height())

        self.assertNotIn("_timeline_toggle_rect", app.WaveformPanel.__dict__)
        self.assertTrue(hasattr(panel, "_timeline_grip_rect"))
        timeline = panel._timeline_area_rect()
        grip = panel._timeline_grip_rect()
        self.assertGreater(grip.height(), 0)
        self.assertGreaterEqual(grip.top(), timeline.bottom())
        self.assertTrue(panel._hit_timeline_grip(grip.center().x(), grip.center().y()))
        self.assertFalse(panel._hit_timeline_grip(timeline.left() + 4, timeline.top() + 4))

    def test_timeline_grip_drag_shrinks_viewport_and_enables_scroll(self):
        panel = app.WaveformPanel()
        panel.set_segments([(i * 1000, i * 1000 + 800, f"seg_{i}", (i, i + 1)) for i in range(1, 7)])
        panel.resize(1024, panel.sizeHint().height())
        original_height = panel._timeline_outer_rect().height()
        grip = panel._timeline_grip_rect()

        self.assertTrue(panel._begin_interaction_at_pos(grip.center().x(), grip.center().y()))
        panel._update_interaction_at_pos(grip.center().x(), grip.center().y() - 70)
        panel._finish_interaction_at_pos(grip.center().x(), grip.center().y() - 70)

        self.assertIsNotNone(panel._timeline_user_height)
        self.assertLess(panel._timeline_outer_rect().height(), original_height)
        self.assertGreater(panel._timeline_scroll_max(), 0)
        self.assertLess(panel._lane_rect(5).bottom(), panel._timeline_area_rect().bottom() + panel._timeline_content_height())

    def test_timeline_collapsed_scrolls_and_expanded_restores_lanes(self):
        panel = app.WaveformPanel()
        panel.set_segments([(i * 1000, i * 1000 + 800, f"seg_{i}", (i, i + 1)) for i in range(1, 7)])
        panel.set_timeline_expanded(False)
        panel.resize(1024, panel.sizeHint().height())

        self.assertFalse(panel.timeline_expanded())
        self.assertGreater(panel._timeline_scroll_max(), 0)
        before = panel._lane_rect(5).top()
        self.assertTrue(panel._scroll_timeline_by(panel.TIMELINE_LANE_HEIGHT * 2))
        self.assertLess(panel._lane_rect(5).top(), before)

        panel.set_timeline_expanded(True)
        panel.resize(1024, panel.sizeHint().height())
        self.assertTrue(panel.timeline_expanded())
        self.assertEqual(panel._timeline_scroll_max(), 0)
        self.assertLessEqual(panel._lane_rect(5).bottom(), panel._timeline_area_rect().bottom())

    def test_main_window_waveform_segment_ranges_ignore_speed(self):
        window = app.MainWindow.__new__(app.MainWindow)
        window._rows = [
            _Row(1000, 2000, speed=0.5, uid="a"),
            _Row(3000, 5000, speed=2.0, uid="b"),
            _Row(None, 6000, uid="draft"),
        ]
        window._waveform_panel = app.WaveformPanel()

        ranges = app.MainWindow._waveform_segment_ranges(window)
        self.assertEqual([item[:4] for item in ranges], [(1000, 2000, "a", (1000, 2000)), (3000, 5000, "b", (3000, 5000))])

        app.MainWindow._refresh_waveform_segments(window)
        self.assertEqual(window._waveform_panel.segment_ranges(), [(1000, 2000), (3000, 5000)])

        window._rows[0]._speed = 3.0
        app.MainWindow._refresh_waveform_segments(window)
        self.assertEqual(window._waveform_panel.segment_ranges(), [(1000, 2000), (3000, 5000)])

    def test_main_window_waveform_drafts_are_separate_from_complete_segments(self):
        window = app.MainWindow.__new__(app.MainWindow)
        window._rows = [
            _TextRow("1000", ""),
            _TextRow("", "2000"),
            _TextRow("3000", "4000"),
        ]
        window._waveform_panel = app.WaveformPanel()

        self.assertEqual([item[:4] for item in app.MainWindow._waveform_segment_ranges(window)], [(3000, 4000, "0", (3000, 4000))])
        self.assertEqual(
            app.MainWindow._waveform_draft_segments(window),
            [
                {"index": 0, "kind": "start", "time_ms": 1000},
                {"index": 1, "kind": "end", "time_ms": 2000},
            ],
        )

        app.MainWindow._refresh_waveform_segments(window)
        self.assertEqual(window._waveform_panel.segment_ranges(), [(3000, 4000)])
        self.assertEqual(
            window._waveform_panel.draft_segments(),
            [
                {"index": 0, "kind": "start", "time_ms": 1000},
                {"index": 1, "kind": "end", "time_ms": 2000},
            ],
        )


if __name__ == "__main__":
    unittest.main()
