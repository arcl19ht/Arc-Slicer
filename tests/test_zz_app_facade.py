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
        self.assertTrue(callable(app.build_segment_id))
        self.assertTrue(callable(app.build_segment_export_plan))
        self.assertTrue(callable(app.build_packlist_entry))
        self.assertTrue(callable(app.build_packlist_document))
        self.assertTrue(callable(app.default_pack_form_for_song))
        self.assertTrue(callable(app.do_slice))
        self.assertTrue(callable(app.load_config))


if __name__ == "__main__":
    unittest.main()
