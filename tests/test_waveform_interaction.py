import unittest

import app


class _Layout:
    def __init__(self):
        self.widgets = []

    def addWidget(self, widget):
        self.widgets.append(widget)

    def insertWidget(self, index, widget):
        self.widgets.insert(index, widget)

    def removeWidget(self, widget):
        self.widgets.remove(widget)


class _CaptureSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


class WaveformInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def _panel(self, duration_ms=100000):
        panel = app.WaveformPanel()
        panel.resize(1024, 150)
        panel.set_waveform(
            app.WaveformData(
                duration_ms=duration_ms,
                samples_per_second=100,
                peaks=[(-0.2, 0.2)] * 100,
            )
        )
        return panel

    def _widget_x_for_time(self, panel, time_ms):
        return panel._waveform_rect().left() + panel.time_ms_to_x(time_ms)

    def _capture_signal(self, owner, name, callback):
        signal = getattr(owner, name)
        if type(signal).__name__ == "_FakeSignal":
            signal = _CaptureSignal()
            setattr(owner, name, signal)
        signal.connect(callback)

    def test_time_coordinate_mapping_clamps_and_round_trips(self):
        panel = self._panel(100000)

        self.assertEqual(panel._waveform_rect().width(), 1000)
        self.assertEqual(panel.x_to_time_ms(0), 0)
        self.assertEqual(panel.x_to_time_ms(500), 50000)
        self.assertEqual(panel.x_to_time_ms(1000), 100000)
        self.assertEqual(panel.x_to_time_ms(-50), 0)
        self.assertEqual(panel.x_to_time_ms(1200), 100000)

        self.assertEqual(panel.time_ms_to_x(0), 0)
        self.assertEqual(panel.time_ms_to_x(50000), 500)
        self.assertEqual(panel.time_ms_to_x(100000), 1000)
        self.assertEqual(panel.time_ms_to_x(-1), 0)
        self.assertEqual(panel.time_ms_to_x(120000), 1000)

    def test_drag_blank_area_creates_segment_in_either_direction(self):
        panel = self._panel()
        created = []
        self._capture_signal(panel, "segmentCreated", lambda start, end: created.append((start, end)))

        panel._begin_interaction_at_widget_x(self._widget_x_for_time(panel, 10000))
        panel._finish_interaction_at_widget_x(self._widget_x_for_time(panel, 20000))
        self.assertEqual(created[-1], (10000, 20000))

        panel._begin_interaction_at_widget_x(self._widget_x_for_time(panel, 20000))
        panel._finish_interaction_at_widget_x(self._widget_x_for_time(panel, 10000))
        self.assertEqual(created[-1], (10000, 20000))
        self.assertEqual(len(created), 2)

    def test_drag_shorter_than_minimum_is_cancelled(self):
        panel = self._panel()
        created = []
        self._capture_signal(panel, "segmentCreated", lambda start, end: created.append((start, end)))

        panel._begin_interaction_at_widget_x(self._widget_x_for_time(panel, 10000))
        panel._finish_interaction_at_widget_x(self._widget_x_for_time(panel, 10050))

        self.assertEqual(created, [])

    def test_endpoint_drag_updates_and_clamps(self):
        panel = self._panel()
        changed = []
        self._capture_signal(
            panel,
            "segmentEndpointChanged",
            lambda index, start, end: changed.append((index, start, end)),
        )

        panel.set_segments([(10000, 20000)])
        panel._begin_interaction_at_widget_x(self._widget_x_for_time(panel, 10000))
        panel._update_interaction_at_widget_x(self._widget_x_for_time(panel, 12000))
        self.assertEqual(changed[-1], (0, 12000, 20000))

        panel.set_segments([(10000, 20000)])
        panel._begin_interaction_at_widget_x(self._widget_x_for_time(panel, 20000))
        panel._update_interaction_at_widget_x(self._widget_x_for_time(panel, 25000))
        self.assertEqual(changed[-1], (0, 10000, 25000))

        panel.set_segments([(10000, 20000)])
        panel._begin_interaction_at_widget_x(self._widget_x_for_time(panel, 10000))
        panel._update_interaction_at_widget_x(self._widget_x_for_time(panel, 30000))
        self.assertEqual(changed[-1], (0, 19900, 20000))

        panel.set_segments([(10000, 20000)])
        panel._begin_interaction_at_widget_x(self._widget_x_for_time(panel, 20000))
        panel._update_interaction_at_widget_x(self._widget_x_for_time(panel, 0))
        self.assertEqual(changed[-1], (0, 10000, 10100))

    def test_hit_priority_endpoint_then_body_then_blank(self):
        panel = self._panel()
        panel.set_segments([(10000, 20000)])
        created = []
        changed = []
        self._capture_signal(panel, "segmentCreated", lambda start, end: created.append((start, end)))
        self._capture_signal(
            panel,
            "segmentEndpointChanged",
            lambda index, start, end: changed.append((index, start, end)),
        )

        self.assertFalse(panel._begin_interaction_at_widget_x(self._widget_x_for_time(panel, 15000)))
        panel._finish_interaction_at_widget_x(self._widget_x_for_time(panel, 18000))
        self.assertEqual(created, [])
        self.assertEqual(changed, [])

        self.assertTrue(panel._begin_interaction_at_widget_x(self._widget_x_for_time(panel, 10000)))
        panel._update_interaction_at_widget_x(self._widget_x_for_time(panel, 12000))
        self.assertEqual(changed[-1], (0, 12000, 20000))

    def test_main_window_waveform_create_and_endpoint_update(self):
        win = app.MainWindow.__new__(app.MainWindow)
        win._rows = []
        win._segs_layout = _Layout()
        win._speed_input = type("Speed", (), {"text": lambda self: "1.5"})()
        win._waveform_panel = app.WaveformPanel()
        win._refresh_seg_header = lambda: None
        win._schedule_segment_time_validation = lambda: setattr(win, "_validated", True)
        win._schedule_arc_cut_warning_refresh = lambda: setattr(win, "_arc_refreshed", True)
        win._invalidate_external_merge_plan = lambda message="": setattr(win, "_invalidated", message)
        win._suppress_source_reset = False
        win._current_export_dirty = False
        win._validated = False
        win._arc_refreshed = False

        app.MainWindow._add_waveform_segment(win, 10000, 20000)

        self.assertEqual(len(win._rows), 1)
        self.assertEqual(win._rows[0].to_dict(), {"s": 10000, "e": 20000, "speed_override": None})
        self.assertEqual(win._waveform_panel.segment_ranges(), [(10000, 20000)])
        self.assertTrue(win._current_export_dirty)
        self.assertIn("当前配置尚未导出", win._invalidated)
        self.assertTrue(win._validated)
        self.assertTrue(win._arc_refreshed)

        win._rows[0]._speed_override.setText("2")
        app.MainWindow._update_waveform_segment_endpoint(win, 0, 12000, 21000)

        self.assertEqual(win._rows[0].to_dict(), {"s": 12000, "e": 21000, "speed_override": 2.0})
        self.assertEqual(win._waveform_panel.segment_ranges(), [(12000, 21000)])


if __name__ == "__main__":
    unittest.main()
