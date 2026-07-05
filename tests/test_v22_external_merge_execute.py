import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import external_merge


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _song(song_id: str, set_id: str = "pack_a", title: str | None = None) -> dict:
    return {
        "id": song_id,
        "title_localized": {"en": title or song_id},
        "set": set_id,
        "difficulties": [{"ratingClass": 2, "rating": 9}],
    }


def _pack(pack_id: str, img: str = "select_pack_a.png") -> dict:
    return {"id": pack_id, "section": "collab", "name_localized": {"en": pack_id}, "img": img}


def _make_song_dir(root: Path, song_id: str, content: bytes | None = None):
    song_dir = root / song_id
    song_dir.mkdir(parents=True, exist_ok=True)
    (song_dir / "2.aff").write_text("-\n", encoding="utf-8")
    (song_dir / "base.ogg").write_bytes(content or f"ogg:{song_id}".encode())


def _make_pack_image(root: Path, img: str, content: bytes):
    pack_dir = root / "pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / img).write_bytes(content)


def _setup_current(root: Path, songs: list[dict], packs: list[dict] | None = None):
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "songlist", {"songs": songs})
    for song in songs:
        _make_song_dir(root, song["id"], f"current:{song['id']}".encode())
    if packs is not None:
        _write_json(root / "packlist", {"packs": packs})
        for pack in packs:
            _make_pack_image(root, pack["img"], f"current:{pack['id']}:{pack['img']}".encode())


def _setup_target(root: Path, songs: list[dict], packs: list[dict]):
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "songlist", {"songs": songs})
    _write_json(root / "packlist", {"packs": packs})
    for song in songs:
        _make_song_dir(root, song["id"], f"target:{song['id']}".encode())
    (root / "pack").mkdir(parents=True, exist_ok=True)
    for pack in packs:
        _make_pack_image(root, pack["img"], f"target:{pack['id']}:{pack['img']}".encode())
    (root / "unlock").mkdir()
    (root / "unlock" / "sentinel").write_text("keep", encoding="utf-8")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _plan(current: Path, target: Path):
    plan = external_merge.build_external_merge_plan(current, target)
    assert plan.is_ready, plan.blockers
    return plan


class ExternalMergeExecuteTests(unittest.TestCase):
    def test_execute_adds_song_and_pack_with_backup_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("new_song")], [_pack("pack_a")])
            _setup_target(target, [_song("old_song", "pack_old")], [_pack("pack_old", "old.png")])
            before_unlock = (target / "unlock" / "sentinel").read_text(encoding="utf-8")

            result = external_merge.execute_external_merge(_plan(current, target), backup_root=backup_root)

            self.assertTrue(result.success, result)
            self.assertEqual(result.status, "completed")
            self.assertTrue((target / "new_song" / "base.ogg").exists())
            self.assertEqual((target / "new_song" / "base.ogg").read_bytes(), b"current:new_song")
            self.assertTrue((target / "pack" / "select_pack_a.png").exists())
            self.assertEqual([s["id"] for s in _read_json(target / "songlist")["songs"]], ["old_song", "new_song"])
            self.assertEqual([p["id"] for p in _read_json(target / "packlist")["packs"]], ["pack_old", "pack_a"])
            self.assertEqual((target / "unlock" / "sentinel").read_text(encoding="utf-8"), before_unlock)
            self.assertFalse(list(target.parent.glob(".arc_slicer_merge_stage_*")))
            manifest = _read_json(result.backup_dir / "manifest.json")
            self.assertEqual(manifest["status"], "completed")
            self.assertIn("songlist", manifest["backed_up_items"])
            self.assertIn("new_song", manifest["created_target_items"])
            self.assertNotIn("old_song", "".join(manifest["backed_up_items"]))

    def test_execute_updates_song_in_place_and_backs_up_old_directory(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("song_b", title="new")], None)
            _setup_target(target, [_song("song_a"), _song("song_b", title="old"), _song("song_c")], [_pack("pack_a")])

            result = external_merge.execute_external_merge(_plan(current, target), backup_root=backup_root)

            self.assertTrue(result.success, result)
            songs = _read_json(target / "songlist")["songs"]
            self.assertEqual([s["id"] for s in songs], ["song_a", "song_b", "song_c"])
            self.assertEqual(songs[1]["title_localized"]["en"], "new")
            self.assertEqual((target / "song_b" / "base.ogg").read_bytes(), b"current:song_b")
            self.assertTrue((result.backup_dir / "before" / "songs" / "song_b" / "base.ogg").exists())

    def test_without_input_packlist_keeps_target_packlist_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("new_song")], None)
            _setup_target(target, [], [_pack("pack_a")])
            before_packlist = (target / "packlist").read_bytes()

            result = external_merge.execute_external_merge(_plan(current, target), backup_root=backup_root)

            self.assertTrue(result.success, result)
            self.assertEqual((target / "packlist").read_bytes(), before_packlist)
            self.assertFalse((result.backup_dir / "before" / "packlist").exists())

    def test_execute_replaces_same_pack_image_and_backs_up_old_image(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("song_a")], [_pack("pack_a")])
            _setup_target(target, [], [_pack("pack_a")])
            old_bytes = b"old image bytes"
            (target / "pack" / "select_pack_a.png").write_bytes(old_bytes)

            result = external_merge.execute_external_merge(_plan(current, target), backup_root=backup_root)

            self.assertTrue(result.success, result)
            self.assertEqual((result.backup_dir / "before" / "pack" / "select_pack_a.png").read_bytes(), old_bytes)
            self.assertEqual((target / "pack" / "select_pack_a.png").read_bytes(), (current / "pack" / "select_pack_a.png").read_bytes())

    def test_stale_plan_after_target_songlist_change_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("new_song")], None)
            _setup_target(target, [], [_pack("pack_a")])
            plan = _plan(current, target)
            before = _snapshot(target)
            _write_json(target / "songlist", {"songs": [_song("other")]})

            result = external_merge.execute_external_merge(plan, backup_root=backup_root)

            self.assertFalse(result.success)
            self.assertEqual(result.status, "stale_plan")
            self.assertFalse(backup_root.exists())
            self.assertEqual(_snapshot(target), {**before, "songlist": (target / "songlist").read_bytes()})

    def test_stale_plan_after_current_pack_image_change_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("song_a")], [_pack("pack_a")])
            _setup_target(target, [], [_pack("pack_old", "old.png")])
            plan = _plan(current, target)
            before = _snapshot(target)
            (current / "pack" / "select_pack_a.png").write_bytes(b"changed")

            result = external_merge.execute_external_merge(plan, backup_root=backup_root)

            self.assertFalse(result.success)
            self.assertEqual(result.status, "stale_plan")
            self.assertFalse(backup_root.exists())
            self.assertEqual(_snapshot(target), before)

    def test_plan_with_blocker_is_rejected_without_backup(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("song_a", "missing_pack")], None)
            _setup_target(target, [], [_pack("pack_a")])
            plan = external_merge.build_external_merge_plan(current, target)

            result = external_merge.execute_external_merge(plan, backup_root=backup_root)

            self.assertFalse(result.success)
            self.assertEqual(result.status, "rejected")
            self.assertFalse(backup_root.exists())

    def test_failure_after_partial_writes_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("song_b", title="new"), _song("new_song")], [_pack("pack_a")])
            _setup_target(target, [_song("song_b", title="old")], [_pack("pack_a")])
            old_snapshot = _snapshot(target)
            original_install_pack = external_merge._install_pack_image

            def failing_install_pack(source, target_path):
                original_install_pack(source, target_path)
                raise OSError("boom after pack image")

            with mock.patch("external_merge._install_pack_image", side_effect=failing_install_pack):
                result = external_merge.execute_external_merge(_plan(current, target), backup_root=backup_root)

            self.assertFalse(result.success)
            self.assertEqual(result.status, "failed_rolled_back")
            self.assertEqual(result.rollback_errors, [])
            self.assertEqual(_snapshot(target), old_snapshot)
            self.assertFalse(list(target.parent.glob(".arc_slicer_merge_stage_*")))
            manifest = _read_json(result.backup_dir / "manifest.json")
            self.assertEqual(manifest["status"], "rolled_back")

    def test_rollback_failure_reports_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("song_b", title="new")], None)
            _setup_target(target, [_song("song_b", title="old")], [_pack("pack_a")])
            original_install_song = external_merge._install_song_directory

            def failing_install_song(source, target_path, swap):
                original_install_song(source, target_path, swap)
                raise OSError("song install fail")

            with mock.patch("external_merge._install_song_directory", side_effect=failing_install_song), \
                    mock.patch("external_merge._restore_dir", side_effect=lambda backup, target_path, rel, errors: errors.append(f"{rel}: restore fail")):
                result = external_merge.execute_external_merge(_plan(current, target), backup_root=backup_root)

            self.assertFalse(result.success)
            self.assertEqual(result.status, "failed_rollback_incomplete")
            self.assertTrue(result.rollback_errors)
            manifest = _read_json(result.backup_dir / "manifest.json")
            self.assertEqual(manifest["status"], "rollback_incomplete")

    def test_backup_root_inside_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target = base / "current", base / "target"
            _setup_current(current, [_song("new_song")], None)
            _setup_target(target, [], [_pack("pack_a")])

            result = external_merge.execute_external_merge(_plan(current, target), backup_root=target / "backups")

            self.assertFalse(result.success)
            self.assertEqual(result.status, "rejected")
            self.assertIn("backup_root_inside_target", {issue.code for issue in result.execution_issues})

    def test_execution_safety_detects_write_path_escape(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            current, target, backup_root = base / "current", base / "target", base / "backups"
            _setup_current(current, [_song("new_song")], None)
            _setup_target(target, [], [_pack("pack_a")])
            plan = _plan(current, target)
            plan.song_actions[0] = external_merge.MergeAction(
                kind="song",
                operation="add",
                identifier="new_song",
                source_path=plan.song_actions[0].source_path,
                target_path=str(base / "escape"),
            )

            issues = external_merge._execution_safety_issues(plan, backup_root)

            self.assertIn("write_path_escape", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
