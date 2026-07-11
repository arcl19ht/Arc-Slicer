import unittest

import app


class AppFacadeTests(unittest.TestCase):
    def test_core_names_remain_available_from_app(self):
        self.assertTrue(callable(app.slice_aff))
        self.assertTrue(callable(app.validate_segment_bounds))
        self.assertTrue(callable(app.normalize_link_group_id))
        self.assertTrue(hasattr(app, "WaveformData"))
        self.assertTrue(hasattr(app, "MainWindow"))
        self.assertTrue(hasattr(app, "SegmentRow"))
        self.assertTrue(hasattr(app, "WaveformPanel"))


if __name__ == "__main__":
    unittest.main()
