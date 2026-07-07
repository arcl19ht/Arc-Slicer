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
        self.assertEqual(row.to_dict(), {"s": 0, "e": 1000})


if __name__ == "__main__":
    unittest.main()
