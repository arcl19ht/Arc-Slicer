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


def _window(auto_sort=False, sort_mode="manual"):
    win = app.MainWindow.__new__(app.MainWindow)
    win._uid = 0
    win._segment_order = 0
    win._rows = []
    win._segs_layout = _Layout()
    win._speed_input = _Speed("1.0")
    win._waveform_panel = app.WaveformPanel()
    win._selected_segment_uid = ""
    win._hovered_segment_uid = ""
    win._join_preview_uid = ""
    win._cascade_edit_enabled = True
    win._audio_duration_ms = 200000
    win._auto_sort_enabled = auto_sort
    win._sort_mode = sort_mode
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


class SegmentLinkGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def test_link_group_id_compatibility_and_export_ids_ignore_it(self):
        self.assertIsNone(app.normalize_link_group_id(None))
        self.assertIsNone(app.normalize_link_group_id(""))
        self.assertIsNone(app.normalize_link_group_id(123))
        self.assertEqual(app.normalize_link_group_id(" grp_a "), "grp_a")

        row = app.SegmentRow(1, 1000, 2000, link_group_id=123)
        self.assertIsNone(row.link_group_id)
        row.link_group_id = "grp_a"
        self.assertEqual(row.to_dict()["link_group_id"], "grp_a")

        first = {"s": 1000, "e": 2000, "speed_override": 0.5, "link_group_id": "grp_a"}
        second = {"s": 1000, "e": 2000, "speed_override": 0.75, "link_group_id": "grp_a"}
        plan = app.build_segment_export_plan("song", [first, second], 1.0)
        self.assertEqual([item["id"] for item in plan], ["song_1000_2000_x0p5", "song_1000_2000_x0p75"])
        with self.assertRaises(ValueError):
            app.build_segment_export_plan("song", [first, dict(first, link_group_id="grp_b")], 1.0)

    def test_copy_creates_or_reuses_link_group_without_copying_speed(self):
        win = _window()
        app.MainWindow._add_segment(win, 1000, 2000, 1.5)
        app.MainWindow._copy_segment(win, win._rows[0])

        group_id = win._rows[0].link_group_id
        self.assertTrue(group_id)
        self.assertEqual(win._rows[1].link_group_id, group_id)
        self.assertNotEqual(win._rows[0].uid, win._rows[1].uid)
        self.assertEqual(win._rows[0].speed_override_value(), 1.5)
        self.assertIsNone(win._rows[1].speed_override_value())
        self.assertTrue(win._dirty_marked)
        self.assertTrue(win._invalidated)

        app.MainWindow._copy_segment(win, win._rows[0])
        self.assertEqual(win._rows[2].link_group_id, group_id)
        self.assertEqual(len(app.MainWindow._valid_link_groups(win)[group_id]), 3)

    def test_unlink_clears_current_and_single_remaining_member(self):
        win = _window()
        group_id = "grp_a"
        for speed in (None, 0.8, 0.9):
            app.MainWindow._add_segment(win, 1000, 2000, speed, link_group_id=group_id)
        selected_uid = win._rows[1].uid
        win._selected_segment_uid = selected_uid

        app.MainWindow._unlink_segment_group(win, win._rows[1])

        self.assertIsNone(win._rows[1].link_group_id)
        self.assertEqual(win._rows[0].link_group_id, group_id)
        self.assertEqual(win._rows[2].link_group_id, group_id)
        self.assertEqual(win._selected_segment_uid, selected_uid)
        self.assertTrue(win._dirty_marked)

        app.MainWindow._unlink_segment_group(win, win._rows[0])
        self.assertIsNone(win._rows[0].link_group_id)
        self.assertIsNone(win._rows[2].link_group_id)

    def test_join_uses_first_matching_valid_group_and_preview_is_clean(self):
        win = _window()
        app.MainWindow._add_segment(win, 1000, 2000, None, link_group_id="grp_a")
        app.MainWindow._add_segment(win, 1000, 2000, 0.8, link_group_id="grp_a")
        app.MainWindow._add_segment(win, 1000, 2000, 0.9)
        candidate = win._rows[2]

        self.assertEqual(app.MainWindow._row_join_target_group_id(win, candidate), "grp_a")
        app.MainWindow._on_join_group_previewed(win, candidate)
        self.assertEqual(win._join_preview_uid, candidate.uid)
        self.assertIsNone(candidate.link_group_id)
        self.assertFalse(win._dirty_marked)

        app.MainWindow._join_segment_group(win, candidate)
        self.assertEqual(candidate.link_group_id, "grp_a")
        self.assertTrue(win._dirty_marked)

        app.MainWindow._add_segment(win, 3000, 4000, None)
        self.assertIsNone(app.MainWindow._row_join_target_group_id(win, win._rows[-1]))

    def test_group_aware_sorting_keeps_link_group_contiguous(self):
        win = _window(auto_sort=True, sort_mode="speed")
        app.MainWindow._add_segment(win, 3000, 4000, 0.9)
        app.MainWindow._add_segment(win, 1000, 2000, 1.0, link_group_id="grp_a")
        app.MainWindow._add_segment(win, 2000, 3000, 0.7)
        app.MainWindow._add_segment(win, 1000, 2000, 0.6, link_group_id="grp_a")
        app.MainWindow._maybe_auto_sort_segments(win, force=True)

        group_positions = [index for index, row in enumerate(win._rows) if row.link_group_id == "grp_a"]
        self.assertEqual(group_positions, list(range(min(group_positions), max(group_positions) + 1)))
        self.assertEqual([row.effective_speed() for row in win._rows if row.link_group_id == "grp_a"], [0.6, 1.0])


if __name__ == "__main__":
    unittest.main()
