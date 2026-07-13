from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arc_slicer.difficulties import (
    difficulty_metadata_from_legacy, discover_song_difficulties,
    normalize_difficulty_metadata_map, serialize_difficulty_metadata_map,
)
from arc_slicer.exports import (
    SongTemplate, build_multi_difficulty_export_plan,
    build_multi_difficulty_songlist_entries,
)


def _template(title="Song"):
    return SongTemplate(title, "Artist", "180", 180, "single", "", 0, "", "1.0", "Chart", "Jacket", 9, False)


class DifficultyOverrideAudioTests(unittest.TestCase):
    def _source(self, charts=(), overrides=(), *, orphan_dirs=(), unknown=()):
        temp_dir = tempfile.TemporaryDirectory()
        source = Path(temp_dir.name)
        (source / "base.ogg").write_bytes(b"base")
        for rating_class in charts:
            (source / f"{rating_class}.aff").write_text("-\n", encoding="utf-8")
        for rating_class in overrides:
            (source / f"{rating_class}.ogg").write_bytes(b"override")
        for rating_class in orphan_dirs:
            (source / f"{rating_class}.ogg").mkdir()
        for name in unknown:
            (source / name).write_bytes(b"unknown")
        self.addCleanup(temp_dir.cleanup)
        return source

    def test_asset_discovery_keeps_override_audio_specific_to_each_chart(self):
        source = self._source((3, 4), (3, 4), unknown=("custom.ogg",))
        discovery = discover_song_difficulties(source)
        self.assertEqual(discovery.available_rating_classes, (3, 4))
        self.assertEqual([(item.rating_class, item.filename) for item in discovery.usable_override_audio], [(3, "3.ogg"), (4, "4.ogg")])
        self.assertEqual(discovery.unknown_audio_filenames, ("custom.ogg",))

    def test_orphan_and_invalid_override_audio_are_reported_but_not_available(self):
        source = self._source((2,), (3,), orphan_dirs=(4,))
        discovery = discover_song_difficulties(source)
        self.assertEqual(discovery.available_rating_classes, (2,))
        self.assertEqual([(item.rating_class, item.filename) for item in discovery.orphan_override_audio], [(3, "3.ogg"), (4, "4.ogg")])
        self.assertFalse(discovery.override_audio_for(4).usable)
        self.assertIn("孤立专属音源，不参与导出: 3.ogg", discovery.warnings)

    def test_audio_plan_has_base_plus_only_selected_usable_overrides(self):
        source = self._source((0, 2, 3, 4), (3, 4))
        plan = build_multi_difficulty_export_plan(
            source, "song", [{"s": 100, "e": 500}, {"s": 600, "e": 1000, "speed_override": 1.5}], 1.0, [0, 3],
        )
        self.assertEqual(plan.audio_operation_count, 4)
        self.assertEqual(plan.chart_operation_count, 4)
        for segment in plan.segments:
            self.assertEqual([item.output_filename for item in segment.audio_operations], ["base.ogg", "3.ogg"])
            self.assertEqual([item.rating_class for item in segment.audio_operations], [None, 3])
            self.assertEqual([item.output_filename for item in segment.chart_operations], ["0.aff", "3.aff"])
            self.assertEqual([item.audio_override for item in segment.chart_operations], [False, True])
            self.assertEqual({(item.start_ms, item.end_ms, item.speed) for item in (*segment.audio_operations, *segment.chart_operations)}, {
                (segment.segment["s"], segment.segment["e"], segment.segment["speed"]),
            })

    def test_invalid_selected_override_audio_blocks_plan_without_base_fallback(self):
        source = self._source((3,), orphan_dirs=(3,))
        with self.assertRaisesRegex(ValueError, "3.ogg"):
            build_multi_difficulty_export_plan(source, "song", [{"s": 0, "e": 100}], 1.0, [3])

    def test_orphan_override_never_enters_audio_plan(self):
        source = self._source((2,), (3,))
        plan = build_multi_difficulty_export_plan(source, "song", [{"s": 0, "e": 100}], 1.0, [2])
        self.assertEqual([item.output_filename for item in plan.segments[0].audio_operations], ["base.ogg"])


class DifficultyMetadataAndAggregationTests(unittest.TestCase):
    def _plan(self, charts=(2,), overrides=(), selected=None, segments=None):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        source = Path(temp_dir.name)
        (source / "base.ogg").write_bytes(b"base")
        for rating_class in charts:
            (source / f"{rating_class}.aff").write_text("-\n", encoding="utf-8")
        for rating_class in overrides:
            (source / f"{rating_class}.ogg").write_bytes(b"override")
        return build_multi_difficulty_export_plan(
            source, "song", segments or [{"s": 100, "e": 500}], 1.0, selected or list(charts),
        )

    def test_legacy_ftr_metadata_maps_to_rating_class_two_and_round_trips(self):
        legacy = {"rating": 10, "ratingPlus": True, "chartDesigner": "C", "jacketDesigner": "J"}
        metadata = difficulty_metadata_from_legacy(legacy)
        self.assertEqual((metadata.rating_class, metadata.rating, metadata.rating_plus), (2, 10, True))
        normalized = normalize_difficulty_metadata_map({}, legacy_ftr_data=legacy)
        self.assertEqual(normalized[2], metadata)
        self.assertEqual(normalize_difficulty_metadata_map(serialize_difficulty_metadata_map(normalized))[2], metadata)

    def test_aggregates_multiple_real_difficulties_into_one_song_entry(self):
        plan = self._plan((0, 2, 3, 4), (3, 4), [0, 2, 3, 4])
        metadata = {
            0: {"rating": 4, "chart_designer": "P", "jacket_designer": "J"},
            2: {"rating": 9, "chart_designer": "F", "jacket_designer": "J"},
            3: {"rating": 10, "chart_designer": "B", "jacket_designer": "J", "title_override_base": "Beyond title"},
            4: {"rating": 11, "chart_designer": "E", "jacket_designer": "J"},
        }
        entries = build_multi_difficulty_songlist_entries(_template(), plan, metadata)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "song_100_500_x1")
        difficulties = entries[0]["difficulties"]
        self.assertEqual([item["ratingClass"] for item in difficulties], [0, 1, 2, 3, 4])
        self.assertEqual([item["rating"] for item in difficulties], [4, -1, 9, 10, 11])
        self.assertNotIn("audioOverride", difficulties[2])
        self.assertTrue(difficulties[3]["audioOverride"])
        self.assertTrue(difficulties[4]["audioOverride"])
        self.assertEqual(difficulties[3]["title_localized"]["en"], "Beyond title [100–500ms · 1×]")
        self.assertNotIn("jacketOverride", difficulties[3])

    def test_placeholder_and_optional_title_rules(self):
        plan = self._plan((2, 3), (), [2, 3])
        entries = build_multi_difficulty_songlist_entries(_template("Song"), plan, {
            2: {"rating": 9},
            3: {"rating": 10, "title_override_base": " Song "},
        })
        difficulties = entries[0]["difficulties"]
        self.assertEqual([item["rating"] for item in difficulties], [-1, -1, 9, 10])
        self.assertNotIn("title_localized", difficulties[3])
        self.assertNotIn("audioOverride", difficulties[3])
        self.assertNotIn("title_localized", difficulties[2])

    def test_missing_real_metadata_rating_is_rejected_but_chart_plan_is_still_valid(self):
        plan = self._plan((3,), (), [3])
        with self.assertRaisesRegex(ValueError, "ratingClass 3"):
            build_multi_difficulty_songlist_entries(_template(), plan, {3: {"rating": None}})
        self.assertEqual(plan.chart_operation_count, 1)

    def test_multiple_segments_remain_one_entry_each_without_duplicate_ids(self):
        plan = self._plan((2, 3), (3,), [2, 3], [{"s": 0, "e": 100}, {"s": 200, "e": 400}])
        entries = build_multi_difficulty_songlist_entries(_template(), plan, {2: {"rating": 9}, 3: {"rating": 10}})
        self.assertEqual(len(entries), 2)
        self.assertEqual(len({item["id"] for item in entries}), 2)
        self.assertEqual([item["difficulties"][-1]["ratingClass"] for item in entries], [3, 3])
