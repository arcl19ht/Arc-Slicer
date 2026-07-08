import unittest

import app


class SegmentRowUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            try:
                cls._qapp = app.QApplication([])
            except Exception:
                cls._qapp = None

    def test_blank_segment_keeps_input_placeholders_and_no_export_data(self):
        row = app.SegmentRow(3, None, None)

        self.assertEqual(row._badge.text(), "3")
        self.assertEqual(row._interval_label.text(), "片段区间（ms）")
        self.assertEqual(row._start_sub_label.text(), "起点")
        self.assertEqual(row._end_sub_label.text(), "终点")
        start_placeholder = row._start.placeholderText()
        end_placeholder = row._end.placeholderText()
        if isinstance(start_placeholder, str) and isinstance(end_placeholder, str):
            self.assertEqual(start_placeholder, "输入起点")
            self.assertEqual(end_placeholder, "输入终点")
        self.assertEqual(row.start_text(), "")
        self.assertEqual(row.end_text(), "")
        self.assertEqual(row._dur.text(), "—")
        self.assertIsNone(row.to_dict())
        self.assertFalse(row._arc_indicator_box.isVisible())
        self.assertEqual(row._speed_override.text(), "")
        speed_placeholder = row._speed_override.placeholderText()
        if isinstance(speed_placeholder, str):
            self.assertIn("留空继承默认", speed_placeholder)

    def test_validation_cap_and_arc_state_survive_segment_layout(self):
        row = app.SegmentRow(1, 0, 2000)
        row.show()
        row.set_time_errors("起点不能为空", "终点不能超过音频时长：0:01.000", 1000)

        self.assertTrue(row._start_error.isVisible())
        self.assertTrue(row._end_error.isVisible())
        self.assertTrue(row._end_cap_btn.isVisible())
        self.assertEqual(row._end_cap_btn.text(), "设为上限 1000 ms")

        row.set_arc_cut_warnings([{"easing": "si"}], [{"easing": "so"}])
        self.assertTrue(row._arc_indicator_box.isVisible())
        self.assertEqual([status.boundary for status in row._arc_statuses], ["start", "end"])

        row.set_end_text(1000)
        self.assertEqual(row.end_text(), "1000")
        self.assertEqual(row.e_val, 1000)
        self.assertEqual(row.to_dict(), {"s": 0, "e": 1000, "speed_override": None})

    def test_speed_override_blank_inherits_default_and_updates_duration(self):
        row = app.SegmentRow(1, 0, 2000, default_speed=1.0)

        self.assertEqual(row.effective_speed(), 1.0)
        self.assertEqual(row._dur.text(), "2.00s")

        row.set_default_speed(0.5)
        self.assertEqual(row.effective_speed(), 0.5)
        speed_placeholder = row._speed_override.placeholderText()
        if isinstance(speed_placeholder, str):
            self.assertIn("0.5×", speed_placeholder)
        self.assertEqual(row._dur.text(), "4.00s")

        row._speed_override.setText("2")
        row._on_change()
        self.assertEqual(row.effective_speed(), 2.0)
        self.assertEqual(row._dur.text(), "1.00s")
        self.assertEqual(row.to_dict()["speed_override"], 2.0)

        row.set_default_speed(0.25)
        self.assertEqual(row.effective_speed(), 2.0)
        self.assertEqual(row._dur.text(), "1.00s")

    def test_copy_segment_request_signal_exists_and_copy_does_not_copy_override(self):
        class _Layout:
            def __init__(self):
                self.widgets = []

            def addWidget(self, widget):
                self.widgets.append(widget)

            def insertWidget(self, index, widget):
                self.widgets.insert(index, widget)

            def removeWidget(self, widget):
                self.widgets.remove(widget)

        win = app.MainWindow.__new__(app.MainWindow)
        win._rows = []
        win._segs_layout = _Layout()
        win._speed_input = type("Speed", (), {"text": lambda self: "0.75"})()
        win._refresh_seg_header = lambda: None
        win._schedule_segment_time_validation = lambda: None
        win._schedule_arc_cut_warning_refresh = lambda: None
        win._mark_current_export_dirty = lambda *args: setattr(win, "_dirty_marked", True)
        win._dirty_marked = False

        app.MainWindow._add_segment(win, 1000, 2000, 2.0)
        app.MainWindow._copy_segment(win, win._rows[0])

        self.assertEqual(len(win._rows), 2)
        self.assertEqual(win._rows[0].to_dict(), {"s": 1000, "e": 2000, "speed_override": 2.0})
        self.assertEqual(win._rows[1].to_dict(), {"s": 1000, "e": 2000, "speed_override": None})
        self.assertEqual(win._rows[1]._badge.text(), "2")
        self.assertTrue(win._dirty_marked)

    def test_soft_validation_allows_start_and_end_drafts_until_hard_validation(self):
        win = app.MainWindow.__new__(app.MainWindow)
        win._audio_duration_ms = 10000

        start_draft = app.SegmentRow(1, None, None)
        start_draft.show()
        start_draft._start.setText("1000")
        win._rows = [start_draft]
        app.MainWindow._refresh_segment_time_validation(win)
        self.assertFalse(start_draft._end_error.isVisible())

        app.MainWindow._validate_segment_row_hard(win, start_draft)
        self.assertTrue(start_draft._end_error.isVisible())
        self.assertIn("终点不能为空", start_draft._end_error.text())

        end_draft = app.SegmentRow(2, None, None)
        end_draft.show()
        end_draft._end.setText("2000")
        win._rows = [end_draft]
        app.MainWindow._refresh_segment_time_validation(win)
        self.assertFalse(end_draft._start_error.isVisible())

        app.MainWindow._validate_segment_row_hard(win, end_draft)
        self.assertTrue(end_draft._start_error.isVisible())
        self.assertIn("起点不能为空", end_draft._start_error.text())

    def test_enter_navigation_moves_to_next_useful_input_and_blocks_invalid_current_field(self):
        win = app.MainWindow.__new__(app.MainWindow)
        win._audio_duration_ms = 10000
        first = app.SegmentRow(1, None, None)
        second = app.SegmentRow(2, None, None)
        first.show()
        second.show()
        win._rows = [first, second]
        focused = []
        first.focus_time_field = lambda field: focused.append(("first", field))
        second.focus_time_field = lambda field: focused.append(("second", field))

        first._start.setText("1000")
        app.MainWindow._on_segment_enter_pressed(win, first, "start")
        self.assertEqual(focused[-1], ("first", "end"))

        first._end.setText("2000")
        app.MainWindow._on_segment_enter_pressed(win, first, "end")
        self.assertEqual(focused[-1], ("first", "speed"))

        first._speed_override.setText("1.5")
        app.MainWindow._on_segment_enter_pressed(win, first, "speed")
        self.assertEqual(focused[-1], ("second", "start"))

        focused.clear()
        first._start.setText("-")
        app.MainWindow._on_segment_enter_pressed(win, first, "start")
        self.assertEqual(focused[-1], ("first", "start"))
        self.assertTrue(first._start_error.isVisible())

    def test_run_slicing_hard_validation_still_blocks_start_and_end_drafts(self):
        win = app.MainWindow.__new__(app.MainWindow)
        win._audio_duration_ms = 10000

        start_draft = app.SegmentRow(1, None, None)
        start_draft.show()
        start_draft._start.setText("1000")
        win._rows = [start_draft]
        error = app.MainWindow._first_segment_validation_error(win)
        self.assertIsNotNone(error)
        self.assertEqual(error[2].first_field, "end")
        self.assertTrue(start_draft._end_error.isVisible())

        end_draft = app.SegmentRow(1, None, None)
        end_draft.show()
        end_draft._end.setText("2000")
        win._rows = [end_draft]
        error = app.MainWindow._first_segment_validation_error(win)
        self.assertIsNotNone(error)
        self.assertEqual(error[2].first_field, "start")
        self.assertTrue(end_draft._start_error.isVisible())


if __name__ == "__main__":
    unittest.main()
