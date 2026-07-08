import unittest

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

    def test_main_window_waveform_segment_ranges_ignore_speed(self):
        window = app.MainWindow.__new__(app.MainWindow)
        window._rows = [
            _Row(1000, 2000, speed=0.5, uid="a"),
            _Row(3000, 5000, speed=2.0, uid="b"),
            _Row(None, 6000, uid="draft"),
        ]
        window._waveform_panel = app.WaveformPanel()

        ranges = app.MainWindow._waveform_segment_ranges(window)
        self.assertEqual(ranges, [(1000, 2000, "a", (1000, 2000)), (3000, 5000, "b", (3000, 5000))])

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

        self.assertEqual(app.MainWindow._waveform_segment_ranges(window), [(3000, 4000, "0", (3000, 4000))])
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
