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


class _Scroll:
    def __init__(self):
        self.visible = []

    def ensureWidgetVisible(self, widget):
        self.visible.append(widget)


def _window():
    win = app.MainWindow.__new__(app.MainWindow)
    win._uid = 0
    win._segment_order = 0
    win._rows = []
    win._segs_layout = _Layout()
    win._speed_input = _Speed()
    win._waveform_panel = app.WaveformPanel()
    win._scroll = _Scroll()
    win._selected_segment_uid = ""
    win._hovered_segment_uid = ""
    win._auto_sort_enabled = False
    win._sort_mode = "manual"
    win._refresh_seg_header = lambda: None
    win._schedule_segment_time_validation = lambda: None
    win._schedule_arc_cut_warning_refresh = lambda: None
    win._mark_current_export_dirty = lambda *args: None
    return win


class SegmentSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def test_segment_row_hover_select_and_leave_update_waveform_state(self):
        win = _window()
        app.MainWindow._add_segment(win, 1000, 2000, None)
        row = win._rows[0]

        app.MainWindow._on_segment_row_hovered(win, row)
        self.assertEqual(win._hovered_segment_uid, row.uid)
        self.assertTrue(row._is_hovered)
        self.assertEqual(win._waveform_panel._hovered_segment_uid, row.uid)

        app.MainWindow._on_segment_row_selected(win, row)
        self.assertEqual(win._selected_segment_uid, row.uid)
        self.assertTrue(row._is_selected)
        self.assertEqual(win._waveform_panel._selected_segment_uid, row.uid)

        app.MainWindow._on_segment_row_unhovered(win, row)
        self.assertEqual(win._hovered_segment_uid, "")
        self.assertFalse(row._is_hovered)

    def test_waveform_hover_select_keeps_page_viewport_and_empty_clear_selection(self):
        win = _window()
        app.MainWindow._add_segment(win, 1000, 2000, None)
        row = win._rows[0]

        app.MainWindow._on_waveform_segment_hovered(win, row.uid)
        self.assertEqual(win._hovered_segment_uid, row.uid)
        self.assertTrue(row._is_hovered)

        app.MainWindow._on_waveform_segment_selected(win, row.uid)
        self.assertEqual(win._selected_segment_uid, row.uid)
        self.assertEqual(win._scroll.visible, [])

        app.MainWindow._clear_selected_segment(win)
        self.assertEqual(win._selected_segment_uid, "")
        self.assertFalse(row._is_selected)

    def test_selected_uid_scrolls_timeline_lane_into_view(self):
        win = _window()
        for index in range(8):
            app.MainWindow._add_segment(win, index * 1000, index * 1000 + 800, None)
        panel = win._waveform_panel
        panel.set_timeline_expanded(False)
        panel.resize(1024, panel.sizeHint().height())
        panel._set_timeline_scroll_offset(0)
        target = win._rows[-1]

        app.MainWindow._set_selected_segment_uid(win, target.uid)

        self.assertEqual(win._selected_segment_uid, target.uid)
        self.assertGreater(panel._timeline_scroll_offset, 0)
        self.assertLessEqual(panel._lane_rect(7).bottom(), panel._timeline_area_rect().bottom())

    def test_deleting_selected_row_selects_next_and_clears_hovered_uid(self):
        win = _window()
        app.MainWindow._add_segment(win, 1000, 2000, None)
        app.MainWindow._add_segment(win, 3000, 4000, None)
        row = win._rows[0]
        win._selected_segment_uid = row.uid
        win._hovered_segment_uid = row.uid

        app.MainWindow._remove_segment(win, row)

        self.assertEqual(win._selected_segment_uid, win._rows[0].uid)
        self.assertEqual(win._hovered_segment_uid, "")

    def test_waveform_panel_emits_hover_select_and_empty_click(self):
        panel = app.WaveformPanel()
        panel.resize(1024, 150)
        panel.set_waveform(app.WaveformData(duration_ms=10000, samples_per_second=100, peaks=[(-0.2, 0.2)] * 20))
        panel.set_segments([(1000, 3000, "seg_a", (1000, 3000))])
        hovered = []
        emptied = []
        panel.segmentHovered.connect(lambda uid: hovered.append(uid))
        panel.emptySelected.connect(lambda: emptied.append(True))

        x_clip = panel._waveform_rect().left() + panel.time_ms_to_x(2000)
        y_clip = panel._lane_rect(0).top() + 6
        self.assertFalse(panel._begin_interaction_at_pos(x_clip, y_clip))
        self.assertEqual(panel._selected_segment_uid, "seg_a")
        panel._update_hover_at_pos(x_clip, y_clip)
        self.assertEqual(panel._hovered_segment_uid, "seg_a")

        x_empty = panel._waveform_rect().left() + panel.time_ms_to_x(8000)
        panel._begin_interaction_at_pos(x_empty, y_clip)
        self.assertEqual(panel._selected_segment_uid, "")

    def test_waveform_area_click_does_not_select_or_create_segment(self):
        panel = app.WaveformPanel()
        panel.resize(1024, 220)
        panel.set_waveform(app.WaveformData(duration_ms=10000, samples_per_second=100, peaks=[(-0.2, 0.2)] * 20))
        panel.set_segments([(1000, 3000, "seg_a", (1000, 3000))])

        x_clip = panel._waveform_rect().left() + panel.time_ms_to_x(2000)
        y_waveform = panel._waveform_area_rect().top() + 10

        self.assertFalse(panel._begin_interaction_at_pos(x_clip, y_waveform))
        self.assertEqual(panel._selected_segment_uid, "")
        self.assertIsNone(panel._drag_mode)

        panel._update_hover_at_pos(x_clip, y_waveform)
        self.assertEqual(panel.current_hover_time_ms(), 2000)
        self.assertEqual(panel._hovered_segment_uid, "")

    def test_waveform_lane_hit_test_uses_y_position_for_overlapping_clips(self):
        panel = app.WaveformPanel()
        panel.resize(1024, 150)
        panel.set_waveform(app.WaveformData(duration_ms=10000, samples_per_second=100, peaks=[(-0.2, 0.2)] * 20))
        panel.set_segments([
            (1000, 3000, "seg_a", (1000, 3000)),
            (1000, 3000, "seg_b", (1000, 3000)),
        ])
        x_clip = panel._waveform_rect().left() + panel.time_ms_to_x(2000)
        y_second_lane = panel._lane_rect(1).top() + 6

        self.assertEqual(panel._hit_segment_body(x_clip, y_second_lane), 1)
        panel._begin_interaction_at_pos(x_clip, y_second_lane)

        self.assertEqual(panel._selected_segment_uid, "seg_b")


if __name__ == "__main__":
    unittest.main()
