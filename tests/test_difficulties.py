from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arc_slicer.difficulties import (
    DIFFICULTY_SELECTION_FIELD, STANDARD_DIFFICULTIES, default_selected_difficulties,
    difficulty_for_rating_class, discover_song_difficulties, is_multi_difficulty_song_dir,
    normalize_selected_difficulties, restore_selected_difficulties, serialize_selected_difficulties,
    validate_selected_difficulties,
)
from arc_slicer.exports import build_multi_difficulty_export_plan


class DifficultyDefinitionTests(unittest.TestCase):
    def test_standard_definitions_are_stably_ordered(self):
        self.assertEqual([item.rating_class for item in STANDARD_DIFFICULTIES], [0, 1, 2, 3, 4])
        self.assertEqual([item.aff_filename for item in STANDARD_DIFFICULTIES], ["0.aff", "1.aff", "2.aff", "3.aff", "4.aff"])
        self.assertEqual([item.display_name for item in STANDARD_DIFFICULTIES], ["Past", "Present", "Future", "Beyond", "Eternal"])
        self.assertEqual([item.abbreviation for item in STANDARD_DIFFICULTIES], ["PST", "PRS", "FTR", "BYD", "ETR"])
        self.assertEqual(difficulty_for_rating_class(4).aff_filename, "4.aff")


class DifficultyDiscoveryTests(unittest.TestCase):
    def _song(self, difficulties=(), *, unknown=(), directory_difficulty=None):
        temp_dir = tempfile.TemporaryDirectory()
        song = Path(temp_dir.name)
        (song / "base.ogg").write_bytes(b"audio")
        for rating_class in difficulties:
            (song / f"{rating_class}.aff").write_text("-\n", encoding="utf-8")
        for name in unknown:
            (song / name).write_text("-\n", encoding="utf-8")
        if directory_difficulty is not None:
            (song / f"{directory_difficulty}.aff").mkdir()
        self.addCleanup(temp_dir.cleanup)
        return song

    def test_discovers_any_standard_subset_without_inventing_charts(self):
        for values in ((0,), (2,), (3,), (4,), (0, 2), (1, 4), (0, 3, 4), (3, 4), (0, 1, 2, 3, 4)):
            with self.subTest(values=values):
                discovery = discover_song_difficulties(self._song(values))
                self.assertEqual(discovery.available_rating_classes, values)
                self.assertEqual(discovery.invalid, ())

    def test_unknown_aff_does_not_become_a_standard_difficulty(self):
        discovery = discover_song_difficulties(self._song((2,), unknown=("custom.aff", "unknown.AFF")))
        self.assertEqual(discovery.available_rating_classes, (2,))
        self.assertEqual(discovery.unknown_aff_filenames, ("custom.aff", "unknown.AFF"))

    def test_missing_and_non_regular_standard_files_are_reported(self):
        discovery = discover_song_difficulties(self._song((2,), directory_difficulty=3))
        self.assertEqual(discovery.available_rating_classes, (2,))
        self.assertIn(0, [item.rating_class for item in discovery.missing])
        self.assertEqual([(item.rating_class, item.reason) for item in discovery.invalid], [(3, "not_regular_file")])

    def test_multi_difficulty_song_validity_requires_audio_and_one_chart(self):
        song = self._song((3,))
        self.assertTrue(is_multi_difficulty_song_dir(song))
        (song / "base.ogg").unlink()
        self.assertFalse(is_multi_difficulty_song_dir(song))


class DifficultySelectionTests(unittest.TestCase):
    def test_normalizes_deduplicates_and_preserves_all_legal_combinations(self):
        self.assertEqual(normalize_selected_difficulties([4, 3, 0, 3]), (0, 3, 4))
        self.assertEqual(normalize_selected_difficulties([3, 4]), (3, 4))

    def test_rejects_empty_non_integer_boolean_and_out_of_range_values(self):
        for values in ([], [-1], [5], ["2"], [True]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    normalize_selected_difficulties(values)

    def test_validation_reports_selected_files_missing_from_directory(self):
        validation = validate_selected_difficulties([0, 2, 4], [0, 2])
        self.assertEqual(validation.selected, (0, 2, 4))
        self.assertEqual(validation.missing, (4,))
        self.assertFalse(validation.ok)

    def test_new_and_legacy_selection_defaults_are_distinct(self):
        self.assertEqual(default_selected_difficulties([1, 2, 4]), (1, 2, 4))
        self.assertEqual(restore_selected_difficulties({}, [1, 2, 4], is_new_song=True).selected, (1, 2, 4))
        self.assertEqual(restore_selected_difficulties({"song_id": "legacy"}, [1, 2, 4]).selected, (2,))
        self.assertEqual(restore_selected_difficulties({"song_id": "legacy"}, [3]).selected, (3,))

    def test_saved_selection_round_trips_and_does_not_add_new_charts(self):
        saved = serialize_selected_difficulties({"song_id": "a"}, [4, 1, 1])
        self.assertEqual(saved[DIFFICULTY_SELECTION_FIELD], [1, 4])
        restored = restore_selected_difficulties(saved, [0, 1, 2, 3, 4])
        self.assertEqual(restored.selected, (1, 4))
        self.assertTrue(restored.ok)

    def test_saved_empty_and_missing_selection_remain_visible_errors(self):
        empty = restore_selected_difficulties({DIFFICULTY_SELECTION_FIELD: []}, [2])
        self.assertIn("至少需要选择", empty.error)
        missing = restore_selected_difficulties({DIFFICULTY_SELECTION_FIELD: [2, 4]}, [2])
        self.assertEqual(missing.selected, (2, 4))
        self.assertEqual(missing.missing, (4,))
        self.assertIn("4.aff", missing.error)

    def test_each_song_payload_keeps_its_own_selection(self):
        first = serialize_selected_difficulties({}, [0, 2])
        second = serialize_selected_difficulties({}, [3])
        self.assertEqual(restore_selected_difficulties(first, [0, 2, 3]).selected, (0, 2))
        self.assertEqual(restore_selected_difficulties(second, [0, 2, 3]).selected, (3,))


class MultiDifficultyExportPlanTests(unittest.TestCase):
    def test_plan_has_one_audio_operation_per_segment_and_one_chart_per_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            for rating_class in (0, 3, 4):
                (source / f"{rating_class}.aff").write_text("-\n", encoding="utf-8")
            plan = build_multi_difficulty_export_plan(
                source, "song", [{"s": 100, "e": 500}, {"s": 800, "e": 1200, "speed_override": 1.5}], 1.0, [4, 0, 3],
            )

        self.assertEqual(plan.selected_difficulties, (0, 3, 4))
        self.assertEqual(plan.audio_operation_count, 2)
        self.assertEqual(plan.chart_operation_count, 6)
        self.assertEqual([item.segment["id"] for item in plan.segments], ["song_100_500_x1", "song_800_1200_x1p5"])
        for item in plan.segments:
            self.assertEqual(item.audio_output_filename, "base.ogg")
            self.assertEqual([chart.output_filename for chart in item.chart_operations], ["0.aff", "3.aff", "4.aff"])
            self.assertEqual([chart.difficulty.rating_class for chart in item.chart_operations], [0, 3, 4])

    def test_plan_rejects_empty_or_missing_selected_difficulties_and_ignores_unknown_aff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            (source / "2.aff").write_text("-\n", encoding="utf-8")
            (source / "custom.aff").write_text("-\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_multi_difficulty_export_plan(source, "song", [{"s": 0, "e": 100}], 1.0, [])
            with self.assertRaises(ValueError):
                build_multi_difficulty_export_plan(source, "song", [{"s": 0, "e": 100}], 1.0, [2, 4])
            plan = build_multi_difficulty_export_plan(source, "song", [{"s": 0, "e": 100}], 1.0, [2])
        self.assertEqual([chart.output_filename for chart in plan.segments[0].chart_operations], ["2.aff"])
