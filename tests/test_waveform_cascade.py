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
        if widget in self.widgets:
            self.widgets.remove(widget)


class _Speed:
    def text(self):
        return "1.0"


def _window(cascade=True):
    win = app.MainWindow.__new__(app.MainWindow)
    win._uid = 0
    win._segment_order = 0
    win._rows = []
    win._segs_layout = _Layout()
    win._speed_input = _Speed()
    win._waveform_panel = app.WaveformPanel()
    win._waveform_panel.set_waveform(app.WaveformData(duration_ms=200000, samples_per_second=100, peaks=[(-0.2, 0.2)] * 100))
    win._selected_segment_uid = ""
    win._hovered_segment_uid = ""
    win._join_preview_uid = ""
    win._cascade_edit_enabled = cascade
    win._audio_duration_ms = 200000
    win._auto_sort_enabled = False
    win._sort_mode = "manual"
    win._refresh_seg_header = lambda: None
    win._schedule_segment_time_validation = lambda: None
    win._schedule_arc_cut_warning_refresh = lambda: None
    win._dirty_marked = False
    win._invalidated = False
    win._mark_current_export_dirty = lambda *args: (
        setattr(win, "_dirty_marked", True),
        setattr(win, "_invalidated", True),
    )
    return win


class WaveformCascadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def _add_fixture_rows(self, win):
        app.MainWindow._add_segment(win, 20000, 140000, None, link_group_id="grp_a")
        app.MainWindow._add_segment(win, 20000, 140000, 0.8, link_group_id="grp_a")
        app.MainWindow._add_segment(win, 20000, 140000, 0.7)
        app.MainWindow._refresh_waveform_segments(win)

    def test_cascade_endpoint_drag_updates_linked_members_only(self):
        win = _window(cascade=True)
        self._add_fixture_rows(win)

        app.MainWindow._update_waveform_segment_endpoint(win, 0, 20000, 139500)

        self.assertEqual(win._rows[0].e_val, 139500)
        self.assertEqual(win._rows[1].e_val, 139500)
        self.assertEqual(win._rows[2].e_val, 140000)
        self.assertIsNone(win._rows[0].speed_override_value())
        self.assertEqual(win._rows[1].speed_override_value(), 0.8)
        self.assertEqual(win._rows[2].speed_override_value(), 0.7)
        self.assertTrue(win._dirty_marked)
        self.assertTrue(win._invalidated)

    def test_cascade_off_updates_only_dragged_member(self):
        win = _window(cascade=False)
        self._add_fixture_rows(win)

        app.MainWindow._update_waveform_segment_endpoint(win, 0, 20000, 139500)

        self.assertEqual(win._rows[0].e_val, 139500)
        self.assertEqual(win._rows[1].e_val, 140000)

    def test_cascade_left_endpoint_uses_common_clamp(self):
        win = _window(cascade=True)
        app.MainWindow._add_segment(win, 20000, 21050, None, link_group_id="grp_a")
        app.MainWindow._add_segment(win, 20000, 22000, 0.8, link_group_id="grp_a")
        app.MainWindow._refresh_waveform_segments(win)

        app.MainWindow._update_waveform_segment_endpoint(win, 0, 21000, 21050)

        self.assertEqual(win._rows[0].s_val, 20950)
        self.assertEqual(win._rows[1].s_val, 20950)

    def test_timeline_metadata_keeps_resize_scroll_and_selection_available(self):
        win = _window(cascade=True)
        self._add_fixture_rows(win)
        panel = win._waveform_panel
        panel.set_timeline_expanded(False)
        panel.resize(1024, panel.sizeHint().height())

        items = panel.segment_items()
        self.assertEqual(items[0]["link_group_id"], "grp_a")
        self.assertTrue(items[2]["join_available"])
        self.assertEqual(items[2]["join_mode"], "join_existing")
        self.assertTrue(panel._timeline_grip_rect().height() > 0)

        panel.ensure_segment_uid_visible(win._rows[2].uid)
        x_clip = panel._waveform_rect().left() + panel.time_ms_to_x(100000)
        y_lane = panel._lane_rect(2).top() + 6
        self.assertEqual(panel._hit_segment_body(x_clip, y_lane), 2)

        x_wave = panel._waveform_area_rect().left() + panel.time_ms_to_x(100000)
        y_wave = panel._waveform_area_rect().top() + 5
        self.assertFalse(panel._begin_interaction_at_pos(x_wave, y_wave))

    def test_same_interval_unlinked_rows_are_hint_not_active_group(self):
        win = _window(cascade=True)
        app.MainWindow._add_segment(win, 1000, 3000, None)
        app.MainWindow._add_segment(win, 1000, 3000, 0.8)
        app.MainWindow._refresh_waveform_segments(win)

        items = win._waveform_panel.segment_items()
        self.assertIsNone(items[0]["link_group_id"])
        self.assertTrue(items[0]["join_available"])
        self.assertEqual(items[0]["join_mode"], "create_same_interval")


if __name__ == "__main__":
    unittest.main()
