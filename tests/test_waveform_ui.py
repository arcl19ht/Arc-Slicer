import unittest

import app


class _Row:
    def __init__(self, s, e, speed=1.0):
        self.s_val = s
        self.e_val = e
        self._speed = speed

    def effective_speed(self):
        return self._speed


class WaveformUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def test_waveform_panel_states(self):
        panel = app.WaveformPanel()

        self.assertEqual(panel.status_text(), "选择源曲后显示波形")
        self.assertIsNone(panel.waveform_data())

        panel.set_loading()
        self.assertEqual(panel.status_text(), "正在生成波形…")
        self.assertIsNone(panel.waveform_data())

        data = app.WaveformData(duration_ms=4000, samples_per_second=100, peaks=[(-0.1, 0.2)])
        panel.set_waveform(data)
        self.assertEqual(panel.status_text(), "")
        self.assertIs(panel.waveform_data(), data)

        panel.set_error()
        self.assertEqual(panel.status_text(), "波形生成失败，不影响切片。")
        self.assertIsNone(panel.waveform_data())

    def test_waveform_panel_segment_ranges_are_cleaned(self):
        panel = app.WaveformPanel()

        panel.set_segments([(1000, 2000), (5000, 3000), ("bad", 7000), (3000, 5000)])

        self.assertEqual(panel.segment_ranges(), [(1000, 2000), (3000, 5000)])

    def test_main_window_waveform_segment_ranges_ignore_speed(self):
        window = app.MainWindow.__new__(app.MainWindow)
        window._rows = [_Row(1000, 2000, speed=0.5), _Row(3000, 5000, speed=2.0), _Row(None, 6000)]
        window._waveform_panel = app.WaveformPanel()

        ranges = app.MainWindow._waveform_segment_ranges(window)
        self.assertEqual(ranges, [(1000, 2000), (3000, 5000)])

        app.MainWindow._refresh_waveform_segments(window)
        self.assertEqual(window._waveform_panel.segment_ranges(), [(1000, 2000), (3000, 5000)])

        window._rows[0]._speed = 3.0
        app.MainWindow._refresh_waveform_segments(window)
        self.assertEqual(window._waveform_panel.segment_ranges(), [(1000, 2000), (3000, 5000)])


if __name__ == "__main__":
    unittest.main()
