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
    def __init__(self, text="1.0"):
        self._text = text

    def text(self):
        return self._text


def _window(auto_sort=True, sort_mode="time"):
    win = app.MainWindow.__new__(app.MainWindow)
    win._uid = 0
    win._segment_order = 0
    win._rows = []
    win._segs_layout = _Layout()
    win._speed_input = _Speed("1.0")
    win._waveform_panel = app.WaveformPanel()
    win._selected_segment_uid = ""
    win._hovered_segment_uid = ""
    win._audio_duration_ms = 10000
    win._auto_sort_enabled = auto_sort
    win._sort_mode = sort_mode
    win._refresh_seg_header = lambda: None
    win._schedule_segment_time_validation = lambda: None
    win._schedule_arc_cut_warning_refresh = lambda: None
    win._mark_current_export_dirty = lambda *args: None
    return win


class SegmentSortingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def _row_summary(self, win):
        return [(row.s_val, row.e_val, row.effective_speed()) for row in win._rows]

    def test_time_first_sort_uses_effective_speed_and_keeps_uid_stable(self):
        win = _window(auto_sort=True, sort_mode="time")
        app.MainWindow._add_segment(win, 3000, 4000, None)
        app.MainWindow._add_segment(win, 1000, 2000, 0.9)
        app.MainWindow._add_segment(win, 1000, 2000, 0.7)
        uids = {row.uid for row in win._rows}

        self.assertEqual(
            self._row_summary(win),
            [(1000, 2000, 0.7), (1000, 2000, 0.9), (3000, 4000, 1.0)],
        )
        self.assertEqual({row.uid for row in win._rows}, uids)
        self.assertEqual([row._badge.text() for row in win._rows], ["1", "2", "3"])

    def test_speed_first_sort_groups_speed_before_time(self):
        win = _window(auto_sort=True, sort_mode="speed")
        app.MainWindow._add_segment(win, 3000, 4000, 0.9)
        app.MainWindow._add_segment(win, 1000, 2000, 0.7)
        app.MainWindow._add_segment(win, 2000, 3000, 0.7)

        self.assertEqual(
            self._row_summary(win),
            [(1000, 2000, 0.7), (2000, 3000, 0.7), (3000, 4000, 0.9)],
        )

    def test_manual_order_disables_automatic_reorder_for_add_and_copy(self):
        win = _window(auto_sort=False, sort_mode="manual")
        app.MainWindow._add_segment(win, 3000, 4000, None)
        app.MainWindow._add_segment(win, 1000, 2000, None)
        app.MainWindow._copy_segment(win, win._rows[0])

        self.assertEqual(
            [(row.s_val, row.e_val) for row in win._rows],
            [(3000, 4000), (3000, 4000), (1000, 2000)],
        )
        self.assertNotEqual(win._rows[0].uid, win._rows[1].uid)

    def test_text_changed_does_not_sort_until_field_commit(self):
        win = _window(auto_sort=False, sort_mode="time")
        app.MainWindow._add_segment(win, 3000, 4000, None)
        app.MainWindow._add_segment(win, 1000, 2000, None)
        win._auto_sort_enabled = True

        win._rows[0]._start.setText("500")
        win._rows[0]._on_change()
        self.assertEqual([(row.s_val, row.e_val) for row in win._rows], [(500, 4000), (1000, 2000)])

        app.MainWindow._on_segment_field_committed(win, win._rows[0], "start")
        self.assertEqual([(row.s_val, row.e_val) for row in win._rows], [(500, 4000), (1000, 2000)])

        win._rows[0]._start.setText("3000")
        win._rows[0]._on_change()
        app.MainWindow._on_segment_field_committed(win, win._rows[0], "start")
        self.assertEqual([(row.s_val, row.e_val) for row in win._rows], [(1000, 2000), (3000, 4000)])

    def test_visual_groups_are_complete_segment_only_and_not_link_groups(self):
        win = _window(auto_sort=True, sort_mode="time")
        app.MainWindow._add_segment(win, 1000, 2000, 0.7)
        app.MainWindow._add_segment(win, 1000, 2000, 0.9)
        app.MainWindow._add_segment(win, 1000, 2000, None)
        app.MainWindow._add_segment(win, 3000, 4000, None)
        app.MainWindow._add_segment(win, 5000, None, None)

        groups = app.MainWindow._complete_visual_groups(win)
        self.assertEqual(len(groups[(1000, 2000)]), 3)
        self.assertEqual(len(groups[(3000, 4000)]), 1)
        self.assertNotIn((5000, None), groups)
        for row in groups[(1000, 2000)]:
            self.assertEqual(row._group_count, 3)
            self.assertNotIn("link_group_id", row.__dict__)

    def test_waveform_lane_order_matches_sorted_rows(self):
        win = _window(auto_sort=True, sort_mode="time")
        app.MainWindow._add_segment(win, 3000, 4000, None)
        selected_uid = win._rows[0].uid
        app.MainWindow._set_selected_segment_uid(win, selected_uid)
        app.MainWindow._add_segment(win, 1000, 2000, None)

        self.assertEqual([item["uid"] for item in win._waveform_panel.segment_items()], [row.uid for row in win._rows])
        self.assertEqual(win._selected_segment_uid, selected_uid)
        self.assertEqual(win._waveform_panel._selected_segment_uid, selected_uid)


if __name__ == "__main__":
    unittest.main()
