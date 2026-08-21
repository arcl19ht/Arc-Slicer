import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import external_merge


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _song(song_id: str, set_id: str = "pack_a", title: str | None = None) -> dict:
    return {
        "id": song_id,
        "title_localized": {"en": title or song_id},
        "set": set_id,
        "difficulties": [{"ratingClass": 2, "rating": 9}],
    }


def _pack(pack_id: str, img: str = "select_pack_a.png") -> dict:
    return {
        "id": pack_id,
        "section": "collab",
        "name_localized": {"en": pack_id},
        "img": img,
    }


def _make_song_dir(root: Path, song_id: str):
    song_dir = root / song_id
    song_dir.mkdir(parents=True, exist_ok=True)
    (song_dir / "2.aff").write_text("-\n", encoding="utf-8")
    (song_dir / "base.ogg").write_bytes(b"ogg")


def _make_pack_image(root: Path, img: str, content: bytes):
    pack_dir = root / "pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / img).write_bytes(content)


def _setup_current(root: Path, songs: list[dict], packs: list[dict] | None = None):
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "songlist", {"songs": songs})
    for song in songs:
        _make_song_dir(root, song["id"])
    if packs is not None:
        _write_json(root / "packlist", {"packs": packs})
        for pack in packs:
            _make_pack_image(root, pack["img"], f"current:{pack['id']}:{pack['img']}".encode())


def _setup_target(root: Path, songs: list[dict], packs: list[dict]):
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "songlist", {"songs": songs})
    _write_json(root / "packlist", {"packs": packs})
    for song in songs:
        _make_song_dir(root, song["id"])
    (root / "pack").mkdir(parents=True, exist_ok=True)
    for pack in packs:
        _make_pack_image(root, pack["img"], f"target:{pack['id']}:{pack['img']}".encode())


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    out = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        out[str(path.relative_to(root))] = path.read_bytes()
    return out


def _codes(plan: external_merge.ExternalMergePlan) -> set[str]:
    return {issue.code for issue in plan.blockers}


def _actions(plan, kind: str, operation: str | None = None):
    all_actions = plan.song_actions + plan.pack_actions + plan.pack_image_actions
    return [
        action for action in all_actions
        if action.kind == kind and (operation is None or action.operation == operation)
    ]


class ExternalMergePlanTests(unittest.TestCase):
    def test_root_link_blocker_short_circuits_document_reads(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current = root / "current" / "songs"
            target = root / "target" / "songs"
            current.mkdir(parents=True)
            target.mkdir(parents=True)

            def fake_link(path):
                return Path(path) == current

            with mock.patch("external_merge.is_link_or_junction", side_effect=fake_link), \
                 mock.patch("external_merge._read_songlist") as read_songlist, \
                 mock.patch("external_merge._read_packlist") as read_packlist, \
                 mock.patch("external_merge._compute_snapshot_fingerprint") as compute_fingerprint, \
                 mock.patch("external_merge._fingerprint_path") as fingerprint_path:
                plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("current_songs_dir_is_link", _codes(plan))
            read_songlist.assert_not_called()
            read_packlist.assert_not_called()
            compute_fingerprint.assert_not_called()
            fingerprint_path.assert_not_called()
            self.assertTrue(plan.snapshot_fingerprint)

    def test_new_song_and_pack_plan_does_not_write_target(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("new_song")], [_pack("pack_a")])
            _setup_target(target, [_song("old_song", "pack_old")], [_pack("pack_old", "old.png")])
            before = _tree_snapshot(target)

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertTrue(plan.is_ready, plan.blockers)
            self.assertEqual(before, _tree_snapshot(target))
            self.assertEqual(_actions(plan, "song", "add")[0].identifier, "new_song")
            self.assertEqual(_actions(plan, "pack", "add")[0].identifier, "pack_a")
            self.assertEqual(_actions(plan, "pack_image", "add")[0].identifier, "select_pack_a.png")
            self.assertEqual([s["id"] for s in plan.merged_songlist_data["songs"]], ["old_song", "new_song"])
            self.assertEqual([p["id"] for p in plan.merged_packlist_data["packs"]], ["pack_old", "pack_a"])

    def test_update_song_keeps_target_position_and_unrelated_order(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_b", title="new")], None)
            _setup_target(
                target,
                [_song("song_a"), _song("song_b", title="old"), _song("song_c")],
                [_pack("pack_a")],
            )

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertTrue(plan.is_ready, plan.blockers)
            self.assertEqual(_actions(plan, "song", "update")[0].identifier, "song_b")
            self.assertEqual([s["id"] for s in plan.merged_songlist_data["songs"]], ["song_a", "song_b", "song_c"])
            self.assertEqual(plan.merged_songlist_data["songs"][1]["title_localized"]["en"], "new")

    def test_new_song_with_existing_target_dir_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("ghost")], None)
            _setup_target(target, [], [_pack("pack_a")])
            _make_song_dir(target, "ghost")

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("target_song_dir_without_metadata", _codes(plan))

    def test_target_songlist_entry_missing_directory_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_x")], None)
            _setup_target(target, [_song("song_x")], [_pack("pack_a")])
            shutil_path = target / "song_x"
            for child in shutil_path.iterdir():
                child.unlink()
            shutil_path.rmdir()

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("target_song_metadata_without_dir", _codes(plan))

    def test_input_songlist_references_missing_directory_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("missing")], None)
            for child in (current / "missing").iterdir():
                child.unlink()
            (current / "missing").rmdir()
            _setup_target(target, [], [_pack("pack_a")])

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("input_song_dir_missing", _codes(plan))

    def test_duplicate_ids_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            current.mkdir()
            _write_json(current / "songlist", {"songs": [_song("dup"), _song("dup")]})
            _make_song_dir(current, "dup")
            _write_json(current / "packlist", {"packs": [_pack("pack_a"), _pack("pack_a")]})
            _make_pack_image(current, "select_pack_a.png", b"a")
            _setup_target(target, [_song("dup")], [_pack("pack_a")])
            _write_json(target / "songlist", {"songs": [_song("dup"), _song("dup")]})

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("input_song_id_duplicate", _codes(plan))
            self.assertIn("target_song_id_duplicate", _codes(plan))

    def test_input_packlist_duplicate_id_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            current.mkdir()
            _write_json(current / "songlist", {"songs": [_song("song_a")]})
            _make_song_dir(current, "song_a")
            _write_json(current / "packlist", {"packs": [_pack("pack_a"), _pack("pack_a", "other.png")]})
            _make_pack_image(current, "select_pack_a.png", b"a")
            _make_pack_image(current, "other.png", b"b")
            _setup_target(target, [], [_pack("pack_a")])

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("input_pack_id_duplicate", _codes(plan))

    def test_without_input_packlist_song_set_must_exist_in_target_packlist(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_a", "missing_pack")], None)
            _setup_target(target, [], [_pack("pack_a")])

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("input_song_set_missing_pack", _codes(plan))

    def test_new_pack_image_same_name_same_content_reuses_and_different_content_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_a")], [_pack("pack_a")])
            _setup_target(target, [], [_pack("pack_b", "select_pack_a.png")])

            (target / "pack" / "select_pack_a.png").write_bytes((current / "pack" / "select_pack_a.png").read_bytes())
            reuse_plan = external_merge.build_external_merge_plan(current, target)
            self.assertTrue(reuse_plan.is_ready, reuse_plan.blockers)
            self.assertEqual(_actions(reuse_plan, "pack_image")[0].operation, "reuse")

            (target / "pack" / "select_pack_a.png").write_bytes(b"different")
            block_plan = external_merge.build_external_merge_plan(current, target)
            self.assertIn("pack_image_name_conflict", _codes(block_plan))

    def test_new_packs_sharing_new_pack_image_are_aggregated(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(
                current,
                [_song("song_a", "pack_a"), _song("song_b", "pack_b")],
                [_pack("pack_a", "shared.png"), _pack("pack_b", "shared.png")],
            )
            _make_pack_image(current, "shared.png", b"shared")
            _setup_target(target, [_song("old_song", "pack_old")], [_pack("pack_old", "old.png")])

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertTrue(plan.is_ready, plan.blockers)
            actions = _actions(plan, "pack_image")
            self.assertEqual(len(actions), 1)
            action = actions[0]
            self.assertEqual(action.identifier, "shared.png")
            self.assertEqual(action.operation, "add")
            self.assertEqual(action.details["referenced_pack_ids"], ["pack_a", "pack_b"])
            self.assertEqual(action.details["target_referenced_pack_ids"], [])
            self.assertIn("source_hash", action.details)

    def test_shared_pack_image_update_and_add_are_aggregated(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(
                current,
                [_song("song_a", "pack_a"), _song("song_b", "pack_b")],
                [_pack("pack_a", "shared.png"), _pack("pack_b", "shared.png")],
            )
            _make_pack_image(current, "shared.png", b"same")
            _setup_target(target, [_song("song_a", "pack_a")], [_pack("pack_a", "shared.png")])
            _make_pack_image(target, "shared.png", b"same")

            reuse_plan = external_merge.build_external_merge_plan(current, target)

            self.assertTrue(reuse_plan.is_ready, reuse_plan.blockers)
            actions = _actions(reuse_plan, "pack_image")
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0].operation, "reuse")
            self.assertEqual(actions[0].details["referenced_pack_ids"], ["pack_a", "pack_b"])
            self.assertEqual(actions[0].details["target_referenced_pack_ids"], ["pack_a"])

            _make_pack_image(current, "shared.png", b"different")
            replace_plan = external_merge.build_external_merge_plan(current, target)

            self.assertTrue(replace_plan.is_ready, replace_plan.blockers)
            actions = _actions(replace_plan, "pack_image")
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0].operation, "replace")
            self.assertEqual(actions[0].details["same_img_existing_pack_ids"], ["pack_a"])

            _write_json(target / "packlist", {"packs": [_pack("pack_a", "shared.png"), _pack("pack_c", "shared.png")]})
            shared_block = external_merge.build_external_merge_plan(current, target)
            self.assertIn("pack_image_shared_update_conflict", _codes(shared_block))
            self.assertEqual(_actions(shared_block, "pack_image"), [])

    def test_update_same_pack_same_img_replace_or_block_when_shared(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_a")], [_pack("pack_a")])
            _setup_target(target, [], [_pack("pack_a")])
            (target / "pack" / "select_pack_a.png").write_bytes(b"old")

            replace_plan = external_merge.build_external_merge_plan(current, target)
            self.assertTrue(replace_plan.is_ready, replace_plan.blockers)
            self.assertEqual(_actions(replace_plan, "pack_image")[0].operation, "replace")

            _write_json(target / "packlist", {"packs": [_pack("pack_a"), _pack("pack_b")]})
            shared_plan = external_merge.build_external_merge_plan(current, target)
            self.assertIn("pack_image_shared_update_conflict", _codes(shared_plan))

    def test_update_pack_with_new_img_never_deletes_old_image(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_a")], [_pack("pack_a", "new.png")])
            _setup_target(target, [], [_pack("pack_a", "old.png")])
            before_files = set(_tree_snapshot(target))

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertTrue(plan.is_ready, plan.blockers)
            action = _actions(plan, "pack_image")[0]
            self.assertEqual(action.operation, "add")
            self.assertEqual(action.details["old_img"], "old.png")
            self.assertEqual(before_files, set(_tree_snapshot(target)))

    def test_missing_pack_image_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_a")], [_pack("pack_a")])
            (current / "pack" / "select_pack_a.png").unlink()
            _setup_target(target, [], [_pack("pack_a")])

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("input_pack_image_missing", _codes(plan))

    def test_symlink_paths_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            real_current = base / "real_current"
            link_current = base / "link_current"
            real_target = base / "real_target"
            link_target = base / "link_target"
            _setup_current(real_current, [_song("song_a")], None)
            _setup_target(real_target, [], [_pack("pack_a")])
            try:
                os.symlink(real_current, link_current, target_is_directory=True)
                os.symlink(real_target, link_target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")

            plan = external_merge.build_external_merge_plan(link_current, link_target)

            self.assertIn("current_songs_dir_is_link", _codes(plan))
            self.assertIn("target_songs_dir_is_link", _codes(plan))

    def test_reparse_point_detection_uses_file_attributes(self):
        class FakeStat:
            st_file_attributes = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

        with mock.patch("pathlib.Path.is_symlink", return_value=False), mock.patch("external_merge.os.lstat", return_value=FakeStat()):
            self.assertTrue(external_merge.is_link_or_junction(Path("junction-like")))

    def test_tool_export_target_paths_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "ArcSlicerData" / "out" / "current_export" / "songs"
            target = base / "ArcSlicerData" / "out" / "library_export" / "songs"
            _setup_current(current, [_song("song_a")], None)
            _setup_target(target, [], [_pack("pack_a")])

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("target_is_tool_export", _codes(plan))

    def test_library_export_alias_with_dotdot_is_blocked_before_reads(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            library = base / "ArcSlicerData" / "out" / "library_export" / "songs"
            target = base / "target"
            library.mkdir(parents=True)
            _setup_target(target, [], [_pack("pack_a")])
            alias = base / "ArcSlicerData" / "out" / "current_export" / ".." / "library_export" / "songs"

            with mock.patch("external_merge._read_songlist") as read_songlist, \
                 mock.patch("external_merge._read_packlist") as read_packlist:
                plan = external_merge.build_external_merge_plan(alias, target)

            self.assertIn("current_is_library_export", _codes(plan))
            self.assertNotIn("current_songs_dir_missing", _codes(plan))
            read_songlist.assert_not_called()
            read_packlist.assert_not_called()

            backup_root = base / "backup"
            result = external_merge.execute_external_merge(plan, backup_root=backup_root)
            self.assertEqual(result.status, "rejected")
            self.assertFalse(backup_root.exists())

    def test_invalid_json_and_shapes_return_blockers_not_exceptions(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            current.mkdir()
            target.mkdir()
            (current / "songlist").write_text("{bad", encoding="utf-8")
            _write_json(target / "songlist", {"songs": []})
            _write_json(target / "packlist", {"packs": []})

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("input_songlist_invalid_json", _codes(plan))
            self.assertFalse(plan.is_ready)

    def test_unsafe_input_song_ids_are_blocked_without_path_reads(self):
        unsafe_ids = ["../escape", "a\\b", "C:\\escape", "\\\\server\\share", ".", "..", "pack", "unlock", "songlist", "CON"]
        for song_id in unsafe_ids:
            with self.subTest(song_id=song_id):
                with tempfile.TemporaryDirectory() as td:
                    base = Path(td)
                    current = base / "current"
                    target = base / "target"
                    current.mkdir()
                    _write_json(current / "songlist", {"songs": [_song(song_id)]})
                    _setup_target(target, [], [_pack("pack_a")])

                    plan = external_merge.build_external_merge_plan(current, target)

                    self.assertIn("input_song_id_unsafe", _codes(plan))
                    self.assertFalse((base / "escape").exists())

    def test_target_equals_current_and_tool_export_aliases_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "ArcSlicerData" / "out" / "current_export" / "songs"
            library = base / "ArcSlicerData" / "out" / "library_export" / "songs"
            _setup_current(current, [_song("song_a")], None)
            _setup_target(library, [], [_pack("pack_a")])

            same_plan = external_merge.build_external_merge_plan(current, current / ".." / "songs")
            self.assertIn("target_equals_current_input", _codes(same_plan))

            current_alias = base / "ArcSlicerData" / "out" / "library_export" / ".." / "current_export" / "songs"
            current_alias_plan = external_merge.build_external_merge_plan(current, current_alias)
            self.assertIn("target_is_tool_export", _codes(current_alias_plan))

            library_alias = base / "ArcSlicerData" / "out" / "current_export" / ".." / "library_export" / "songs"
            library_alias_plan = external_merge.build_external_merge_plan(current, library_alias)
            self.assertIn("target_is_tool_export", _codes(library_alias_plan))

    def test_library_export_input_is_blocked_even_with_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "ArcSlicerData" / "out" / "library_export" / "songs"
            target = base / "target"
            _setup_current(current, [_song("song_a")], None)
            _setup_target(target, [], [_pack("pack_a")])

            plan = external_merge.build_external_merge_plan(current, target)
            self.assertIn("current_is_library_export", _codes(plan))
            self.assertFalse(plan.is_ready)

            alias = base / "ArcSlicerData" / "out" / "current_export" / ".." / "library_export" / "songs"
            alias_plan = external_merge.build_external_merge_plan(alias, target)
            self.assertIn("current_is_library_export", _codes(alias_plan))

    def test_update_same_pack_same_img_missing_target_image_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_a")], [_pack("pack_a")])
            _setup_target(target, [], [_pack("pack_a")])
            (target / "pack" / "select_pack_a.png").unlink()

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("target_pack_image_missing_for_update", _codes(plan))

    def test_nested_symlink_in_song_dirs_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            outside = base / "outside"
            outside.mkdir()
            _setup_current(current, [_song("song_a")], None)
            _setup_target(target, [_song("song_a")], [_pack("pack_a")])
            try:
                os.symlink(outside, current / "song_a" / "nested_link", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")

            input_plan = external_merge.build_external_merge_plan(current, target)
            self.assertIn("input_song_dir_contains_link", _codes(input_plan))

            (current / "song_a" / "nested_link").unlink()
            os.symlink(outside, target / "song_a" / "nested_link", target_is_directory=True)
            target_plan = external_merge.build_external_merge_plan(current, target)
            self.assertIn("target_song_dir_contains_link", _codes(target_plan))

    def test_target_pack_image_symlink_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            outside = base / "outside.png"
            outside.write_bytes(b"outside")
            _setup_current(current, [_song("song_a")], [_pack("pack_a")])
            _setup_target(target, [], [_pack("pack_a")])
            (target / "pack" / "select_pack_a.png").unlink()
            try:
                os.symlink(outside, target / "pack" / "select_pack_a.png")
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("target_pack_image_is_link", _codes(plan))

    def test_broken_target_song_symlink_is_blocked_as_link(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_a")], None)
            _setup_target(target, [_song("old_song", "pack_a")], [_pack("pack_a")])
            try:
                os.symlink(base / "missing_song_target", target / "song_a", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("target_song_dir_is_link", _codes(plan))
            self.assertEqual(_actions(plan, "song", "add"), [])

    def test_broken_target_pack_image_symlink_is_blocked_as_link(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current = base / "current"
            target = base / "target"
            _setup_current(current, [_song("song_a")], [_pack("pack_a", "shared.png")])
            _setup_target(target, [_song("old_song", "pack_old")], [_pack("pack_old", "old.png")])
            try:
                os.symlink(base / "missing_image_target", target / "pack" / "shared.png")
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")

            plan = external_merge.build_external_merge_plan(current, target)

            self.assertIn("target_pack_image_is_link", _codes(plan))
            self.assertEqual(_actions(plan, "pack_image", "add"), [])


if __name__ == "__main__":
    unittest.main()
