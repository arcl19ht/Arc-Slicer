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


class _Point:
    def __init__(self, x=0, y=0):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y


class _WheelEvent:
    def __init__(self, x, y, delta_y):
        self._pos = _Point(x, y)
        self._delta = _Point(0, delta_y)
        self.accepted = False

    def position(self):
        return self._pos

    def angleDelta(self):
        return self._delta

    def pixelDelta(self):
        return _Point(0, 0)

    def accept(self):
        self.accepted = True


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

    def test_hover_time_tracks_mouse_and_leave_clears_without_segment_signals(self):
        panel = self._panel(100000)
        created = []
        changed = []
        self._capture_signal(panel, "segmentCreated", lambda start, end: created.append((start, end)))
        self._capture_signal(
            panel,
            "segmentEndpointChanged",
            lambda index, start, end: changed.append((index, start, end)),
        )

        panel._update_hover_at_widget_x(self._widget_x_for_time(panel, 25000))
        self.assertEqual(panel.current_hover_time_ms(), 25000)

        panel._update_hover_at_widget_x(panel._waveform_rect().left() - 100)
        self.assertEqual(panel.current_hover_time_ms(), 0)

        panel._clear_hover()
        self.assertIsNone(panel.current_hover_time_ms())
        self.assertEqual(created, [])
        self.assertEqual(changed, [])

    def test_hover_time_is_empty_without_ready_waveform(self):
        panel = app.WaveformPanel()
        panel._update_hover_at_widget_x(500)
        self.assertIsNone(panel.current_hover_time_ms())

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

    def test_endpoint_drag_requires_timeline_lane_handle_when_y_is_provided(self):
        panel = self._panel()
        changed = []
        self._capture_signal(
            panel,
            "segmentEndpointChanged",
            lambda index, start, end: changed.append((index, start, end)),
        )
        panel.set_segments([(10000, 20000, "seg_a", (10000, 20000))])
        x_start = self._widget_x_for_time(panel, 10000)
        y_waveform = panel._waveform_area_rect().top() + 8
        y_lane = panel._lane_rect(0).top() + 6

        self.assertFalse(panel._begin_interaction_at_pos(x_start, y_waveform))
        self.assertIsNone(panel._drag_mode)

        self.assertTrue(panel._begin_interaction_at_pos(x_start, y_lane))
        panel._update_interaction_at_pos(self._widget_x_for_time(panel, 12000), y_lane)
        self.assertEqual(changed[-1], (0, 12000, 20000))

    def test_timeline_scroll_offset_updates_lane_hit_testing(self):
        panel = self._panel(10000)
        panel.set_segments([(1000, 3000, f"seg_{i}", (1000, 3000)) for i in range(6)])
        panel.set_timeline_expanded(False)
        panel.resize(1024, panel.sizeHint().height())
        panel.ensure_segment_uid_visible("seg_5")

        x_clip = self._widget_x_for_time(panel, 2000)
        y_lane = panel._lane_rect(5).top() + 6
        self.assertEqual(panel._hit_segment_body(x_clip, y_lane), 5)
        self.assertFalse(panel._begin_interaction_at_pos(x_clip, y_lane))
        self.assertEqual(panel._selected_segment_uid, "seg_5")

    def test_timeline_wheel_scrolls_without_segment_signals(self):
        panel = self._panel(10000)
        panel.set_segments([(1000, 3000, f"seg_{i}", (1000, 3000)) for i in range(7)])
        panel.set_timeline_expanded(False)
        panel.resize(1024, panel.sizeHint().height())
        created = []
        changed = []
        committed = []
        self._capture_signal(panel, "segmentCreated", lambda start, end: created.append((start, end)))
        self._capture_signal(
            panel,
            "segmentEndpointChanged",
            lambda index, start, end: changed.append((index, start, end)),
        )
        self._capture_signal(panel, "segmentEndpointCommitted", lambda: committed.append(True))

        timeline = panel._timeline_area_rect()
        event = _WheelEvent(timeline.left() + 10, timeline.top() + 10, -120)
        panel.wheelEvent(event)

        self.assertTrue(event.accepted)
        self.assertGreater(panel._timeline_scroll_offset, 0)
        self.assertEqual(created, [])
        self.assertEqual(changed, [])
        self.assertEqual(committed, [])

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
        self.assertEqual(
            {k: win._rows[0].to_dict()[k] for k in ("s", "e", "speed_override")},
            {"s": 10000, "e": 20000, "speed_override": None},
        )
        self.assertEqual(win._waveform_panel.segment_ranges(), [(10000, 20000)])
        self.assertTrue(win._current_export_dirty)
        self.assertIn("当前配置尚未导出", win._invalidated)
        self.assertTrue(win._validated)
        self.assertTrue(win._arc_refreshed)

        win._rows[0]._speed_override.setText("2")
        app.MainWindow._update_waveform_segment_endpoint(win, 0, 12000, 21000)

        self.assertEqual(
            {k: win._rows[0].to_dict()[k] for k in ("s", "e", "speed_override")},
            {"s": 12000, "e": 21000, "speed_override": 2.0},
        )
        self.assertEqual(win._waveform_panel.segment_ranges(), [(12000, 21000)])

    def test_waveform_endpoint_update_uses_uid_not_row_index(self):
        win = app.MainWindow.__new__(app.MainWindow)
        win._rows = []
        win._segs_layout = _Layout()
        win._speed_input = type("Speed", (), {"text": lambda self: "1.0"})()
        win._waveform_panel = app.WaveformPanel()
        win._auto_sort_enabled = False
        win._sort_mode = "manual"
        win._selected_segment_uid = ""
        win._hovered_segment_uid = ""
        win._refresh_seg_header = lambda: None
        win._schedule_segment_time_validation = lambda: setattr(win, "_validated", True)
        win._schedule_arc_cut_warning_refresh = lambda: setattr(win, "_arc_refreshed", True)
        win._mark_current_export_dirty = lambda *args: setattr(win, "_dirty_marked", True)

        app.MainWindow._add_segment(win, None, None, None)
        app.MainWindow._add_segment(win, 10000, 20000, None)
        draft_uid = win._rows[0].uid
        complete_uid = win._rows[1].uid
        app.MainWindow._refresh_waveform_segments(win)

        app.MainWindow._update_waveform_segment_endpoint(win, 0, 12000, 21000)

        self.assertEqual(win._rows[0].uid, draft_uid)
        self.assertIsNone(win._rows[0].s_val)
        self.assertIsNone(win._rows[0].e_val)
        self.assertEqual(win._rows[1].uid, complete_uid)
        self.assertEqual((win._rows[1].s_val, win._rows[1].e_val), (12000, 21000))


if __name__ == "__main__":
    unittest.main()
