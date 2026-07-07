import json
import unittest

import app


class PackSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            try:
                cls._qapp = app.QApplication([])
            except Exception:
                cls._qapp = None

    def test_pack_section_options_are_stable_and_defaulted(self):
        self.assertEqual(app.PACK_SECTION_OPTIONS[0], "collab")
        self.assertIn("collab", app.PACK_SECTION_OPTIONS)
        self.assertEqual(len(app.PACK_SECTION_OPTIONS), len(set(app.PACK_SECTION_OPTIONS)))
        self.assertTrue(app.PACK_SECTION_OPTIONS)
        self.assertEqual(app.default_pack_form_for_song("song")["pack_section"], "collab")

    def test_pack_template_section_fallbacks_are_safe(self):
        base = app.default_pack_form_for_song("song")
        for value in (None, "", "unknown_value"):
            with self.subTest(value=value):
                data = dict(base)
                if value is None:
                    data.pop("pack_section", None)
                else:
                    data["pack_section"] = value
                template = app.pack_template_from_form(data, "song")
                entry = app.build_packlist_entry(template)
                self.assertEqual(template.section, "collab")
                self.assertEqual(entry["section"], "collab")
                self.assertNotEqual(entry["section"], "unknown_value")

    def test_pack_template_section_flows_to_packlist_json(self):
        data = app.default_pack_form_for_song("song")
        data["pack_section"] = "archive"

        template = app.pack_template_from_form(data, "song")
        document = app.build_packlist_document([app.build_packlist_entry(template)])

        encoded = json.loads(json.dumps(document, ensure_ascii=False))
        self.assertEqual(template.section, "archive")
        self.assertEqual(encoded["packs"][0]["section"], "archive")

    def test_section_combo_is_not_editable_and_emits_metadata_changed(self):
        panel = app.SonglistPanel()
        calls = []
        original_emit = panel._emit_metadata_changed

        def wrapped_emit():
            calls.append("changed")
            original_emit()

        panel._emit_metadata_changed = wrapped_emit

        editable = panel._pack_section.isEditable()
        if isinstance(editable, bool):
            self.assertFalse(editable)
        panel.set_songlist_enabled(True)
        panel.set_packlist_enabled(True)
        panel._on_pack_section_changed("archive")

        self.assertEqual(panel.get_form_data()["pack_section"], "archive")
        self.assertTrue(calls)

    def test_set_meta_restores_section_and_unknown_values_fallback(self):
        panel = app.SonglistPanel()
        panel.set_meta({"pack_section": "archive"})
        self.assertEqual(panel.get_form_data()["pack_section"], "archive")

        panel.set_meta({"pack_section": "unknown_value"})
        self.assertEqual(panel.get_form_data()["pack_section"], "collab")

    def test_reset_for_new_source_resets_section_to_collab(self):
        panel = app.SonglistPanel()
        panel.set_meta({"pack_section": "archive"})
        self.assertEqual(panel.get_form_data()["pack_section"], "archive")

        panel.reset_for_source("new_song")

        self.assertEqual(panel.get_form_data()["pack_section"], "collab")


if __name__ == "__main__":
    unittest.main()
