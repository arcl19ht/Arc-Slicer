from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BLOCKER = "blocker"
WARNING = "warning"

_IGNORED_SONGS_DIRS = {"pack", "unlock", "unlocks"}
_RESERVED_SONG_IDS = {"pack", "unlock", "unlocks", "songlist", "packlist"}
_WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
_SAFE_SONG_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class MergeIssue:
    severity: str
    code: str
    message: str
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class MergeAction:
    kind: str
    operation: str
    identifier: str
    source_path: str | None = None
    target_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExternalMergePlan:
    current_songs_dir: Path
    target_songs_dir: Path
    song_actions: list[MergeAction] = field(default_factory=list)
    pack_actions: list[MergeAction] = field(default_factory=list)
    pack_image_actions: list[MergeAction] = field(default_factory=list)
    blockers: list[MergeIssue] = field(default_factory=list)
    warnings: list[MergeIssue] = field(default_factory=list)
    merged_songlist_data: dict[str, Any] | None = None
    merged_packlist_data: dict[str, Any] | None = None
    snapshot_fingerprint: str = ""

    @property
    def is_ready(self) -> bool:
        return not self.blockers

    @property
    def summary(self) -> dict[str, int]:
        actions = self.song_actions + self.pack_actions + self.pack_image_actions
        return {
            "song_add": _count(self.song_actions, "add"),
            "song_update": _count(self.song_actions, "update"),
            "pack_add": _count(self.pack_actions, "add"),
            "pack_update": _count(self.pack_actions, "update"),
            "pack_image_add": _count(self.pack_image_actions, "add"),
            "pack_image_reuse": _count(self.pack_image_actions, "reuse"),
            "pack_image_replace": _count(self.pack_image_actions, "replace"),
            "actions": len(actions),
            "blockers": len(self.blockers),
            "warnings": len(self.warnings),
        }


@dataclass
class ExternalMergeResult:
    success: bool
    status: str
    plan: ExternalMergePlan
    backup_dir: Path | None = None
    message: str = ""
    changed_paths: list[str] = field(default_factory=list)
    rollback_errors: list[str] = field(default_factory=list)
    execution_issues: list[MergeIssue] = field(default_factory=list)


def _count(actions: list[MergeAction], operation: str) -> int:
    return sum(1 for action in actions if action.operation == operation)


def _has_root_blocker(plan: ExternalMergePlan) -> bool:
    unsafe_root_codes = {
        "current_songs_dir_is_link",
        "target_songs_dir_is_link",
        "current_songs_dir_missing",
        "target_songs_dir_missing",
        "current_songs_dir_not_dir",
        "target_songs_dir_not_dir",
        "current_songs_dir_not_directory",
        "target_songs_dir_not_directory",
    }
    return any(issue.code in unsafe_root_codes for issue in plan.blockers)


def build_external_merge_plan(current_songs_dir: Path, target_songs_dir: Path) -> ExternalMergePlan:
    current_songs_dir = Path(current_songs_dir)
    target_songs_dir = Path(target_songs_dir)
    plan = ExternalMergePlan(current_songs_dir=current_songs_dir, target_songs_dir=target_songs_dir)

    _validate_root(plan, current_songs_dir, "current", "current_songs_dir")
    _validate_root(plan, target_songs_dir, "target", "target_songs_dir")
    if _has_root_blocker(plan):
        return _finalize_plan(plan)
    if _is_library_export_songs_dir(current_songs_dir):
        _block(plan, "current_is_library_export", "library_export/songs must not be used as external merge input.", current_songs_dir)
    if _same_path(current_songs_dir, target_songs_dir):
        _block(plan, "target_equals_current_input", "target songs directory must not equal current input.", target_songs_dir)
    if _is_tool_export_songs_dir(target_songs_dir):
        _block(plan, "target_is_tool_export", "target directory must not be the tool current_export or library_export.", target_songs_dir)

    input_songlist = _read_songlist(plan, current_songs_dir / "songlist", "input")
    target_songlist = _read_songlist(plan, target_songs_dir / "songlist", "target")
    input_packlist = _read_packlist(plan, current_songs_dir / "packlist", "input", required=False)
    target_packlist = _read_packlist(plan, target_songs_dir / "packlist", "target", required=True)

    if input_songlist is None or target_songlist is None:
        return _finalize_plan(plan)

    input_songs = input_songlist["songs"]
    target_songs = target_songlist["songs"]
    input_song_ids = _index_entries(plan, input_songs, "song", "input")
    target_song_ids = _index_entries(plan, target_songs, "song", "target")
    if input_song_ids is None or target_song_ids is None:
        return _finalize_plan(plan)
    _validate_song_ids(plan, input_song_ids, "input", set(input_song_ids))
    _validate_song_ids(plan, target_song_ids, "target", set(input_song_ids))

    _validate_current_song_dirs(plan, current_songs_dir, input_song_ids)
    _plan_song_actions(plan, current_songs_dir, target_songs_dir, input_songs, target_songs, input_song_ids, target_song_ids)

    if target_packlist is None:
        return _finalize_plan(plan)

    target_packs = target_packlist["packs"]
    target_pack_ids = _index_entries(plan, target_packs, "pack", "target")
    if target_pack_ids is None:
        return _finalize_plan(plan)

    input_pack_ids: dict[str, dict[str, Any]] = {}
    if input_packlist is not None:
        input_pack_ids_maybe = _index_entries(plan, input_packlist["packs"], "pack", "input")
        if input_pack_ids_maybe is None:
            return _finalize_plan(plan)
        input_pack_ids = input_pack_ids_maybe
        _validate_input_pack_images(plan, current_songs_dir, input_packlist["packs"])
        _plan_pack_actions(plan, input_packlist["packs"], target_packs, input_pack_ids, target_pack_ids)
        _plan_pack_image_actions(plan, current_songs_dir, target_songs_dir, input_packlist["packs"], target_packs, target_pack_ids)
        plan.merged_packlist_data = {"packs": _merge_entries(target_packs, input_packlist["packs"])}
    else:
        plan.merged_packlist_data = {"packs": json.loads(json.dumps(target_packs, ensure_ascii=False))}

    _validate_input_song_sets(plan, input_songs, input_pack_ids, target_pack_ids)
    plan.merged_songlist_data = {"songs": _merge_entries(target_songs, input_songs)}
    return _finalize_plan(plan)


def execute_external_merge(plan: ExternalMergePlan, *, backup_root: Path) -> ExternalMergeResult:
    if not isinstance(plan, ExternalMergePlan):
        raise TypeError("plan must be an ExternalMergePlan")
    backup_root = Path(backup_root)
    if plan.blockers:
        return ExternalMergeResult(
            success=False,
            status="rejected",
            plan=plan,
            message="merge plan has blockers; no writes were performed.",
            execution_issues=list(plan.blockers),
        )

    fresh = build_external_merge_plan(plan.current_songs_dir, plan.target_songs_dir)
    if fresh.blockers:
        return ExternalMergeResult(
            success=False,
            status="rejected",
            plan=fresh,
            message="fresh merge plan has blockers; no writes were performed.",
            execution_issues=list(fresh.blockers),
        )
    if fresh.snapshot_fingerprint != plan.snapshot_fingerprint:
        return ExternalMergeResult(
            success=False,
            status="stale_plan",
            plan=fresh,
            message="external target or current export changed after plan check.",
        )

    safety_issues = _execution_safety_issues(fresh, backup_root)
    if safety_issues:
        return ExternalMergeResult(
            success=False,
            status="rejected",
            plan=fresh,
            message="execution path safety check failed; no writes were performed.",
            execution_issues=safety_issues,
        )

    backup_dir: Path | None = None
    stage_dir: Path | None = None
    manifest: dict[str, Any] | None = None
    ctx: dict[str, Any] = {
        "backed_up_items": [],
        "created_target_items": [],
        "changed_paths": [],
        "rollback_errors": [],
        "swaps": [],
        "checkpoints": [],
    }
    try:
        backup_dir = _create_backup_dir(backup_root)
        manifest = _base_manifest(fresh, backup_dir, "in_progress")
        _write_manifest(backup_dir, manifest)
        _checkpoint(backup_dir, manifest, ctx, "manifest_created")
        _backup_affected_items(fresh, backup_dir, ctx, lambda label: _checkpoint(backup_dir, manifest, ctx, label))

        refreshed = build_external_merge_plan(plan.current_songs_dir, plan.target_songs_dir)
        if refreshed.snapshot_fingerprint != fresh.snapshot_fingerprint or refreshed.blockers:
            manifest_issues = _try_write_manifest_status(backup_dir, manifest, ctx, "stale_no_write")
            return ExternalMergeResult(
                success=False,
                status="stale_plan",
                plan=refreshed,
                backup_dir=backup_dir,
                message="stale plan detected after backup; no target writes were performed.",
                changed_paths=[],
                execution_issues=manifest_issues,
            )

        stage_dir = _create_staging_dir(fresh.target_songs_dir)
        _stage_inputs(fresh, stage_dir)
        _checkpoint(backup_dir, manifest, ctx, "staging_completed")

        final = build_external_merge_plan(plan.current_songs_dir, plan.target_songs_dir)
        if final.snapshot_fingerprint != fresh.snapshot_fingerprint or final.blockers:
            _cleanup_temp_path(stage_dir)
            manifest_issues = _try_write_manifest_status(backup_dir, manifest, ctx, "stale_no_write")
            return ExternalMergeResult(
                success=False,
                status="stale_plan",
                plan=final,
                backup_dir=backup_dir,
                message="stale plan detected after staging; no target writes were performed.",
                changed_paths=[],
                execution_issues=manifest_issues,
            )

        _install_song_directories(fresh, stage_dir, ctx, lambda label: _checkpoint(backup_dir, manifest, ctx, label))
        _install_pack_images(fresh, stage_dir, ctx, lambda label: _checkpoint(backup_dir, manifest, ctx, label))
        _write_json_atomic(fresh.target_songs_dir / "songlist", fresh.merged_songlist_data)
        ctx["changed_paths"].append("songlist")
        _checkpoint(backup_dir, manifest, ctx, "songlist_written")
        if fresh.pack_actions:
            _write_json_atomic(fresh.target_songs_dir / "packlist", fresh.merged_packlist_data)
            ctx["changed_paths"].append("packlist")
            _checkpoint(backup_dir, manifest, ctx, "packlist_written")

        _cleanup_swaps(ctx)
        _cleanup_temp_path(stage_dir)
        _checkpoint(backup_dir, manifest, ctx, "temporary_paths_cleaned")
        manifest_issues = _try_write_manifest_status(backup_dir, manifest, ctx, "completed")
        return ExternalMergeResult(
            success=True,
            status="completed",
            plan=fresh,
            backup_dir=backup_dir,
            message="external merge completed.",
            changed_paths=list(ctx["changed_paths"]),
            execution_issues=manifest_issues,
        )
    except Exception as ex:
        manifest_errors: list[str] = []

        def rollback_checkpoint(label: str) -> None:
            if backup_dir is None or manifest is None:
                return
            try:
                _checkpoint(backup_dir, manifest, ctx, label)
            except Exception as manifest_ex:
                manifest_errors.append(f"manifest checkpoint {label}: {manifest_ex}")

        rollback_errors = _rollback(
            fresh,
            backup_dir,
            ctx,
            rollback_checkpoint if backup_dir is not None and manifest is not None else None,
        ) if backup_dir is not None else [str(ex)]
        rollback_errors.extend(manifest_errors)
        if stage_dir is not None:
            try:
                _cleanup_temp_path(stage_dir)
            except Exception as cleanup_ex:
                rollback_errors.append(f"cleanup staging failed: {cleanup_ex}")
        status = "failed_rollback_incomplete" if rollback_errors else "failed_rolled_back"
        if backup_dir is not None:
            final_manifest = _base_manifest(fresh, backup_dir, "rollback_incomplete" if rollback_errors else "rolled_back")
            ctx["rollback_errors"] = rollback_errors
            final_manifest_issues = _try_write_manifest_status(backup_dir, final_manifest, ctx, final_manifest["status"])
            if final_manifest_issues:
                rollback_errors.extend(issue.message for issue in final_manifest_issues)
                ctx["rollback_errors"] = rollback_errors
                status = "failed_rollback_incomplete"
        return ExternalMergeResult(
            success=False,
            status=status,
            plan=fresh,
            backup_dir=backup_dir,
            message=f"merge failed; {'rollback incomplete' if rollback_errors else 'rolled back'}: {ex}",
            changed_paths=list(ctx["changed_paths"]),
            rollback_errors=rollback_errors,
            execution_issues=[MergeIssue(BLOCKER, "execution_failed", str(ex))],
        )


def _finalize_plan(plan: ExternalMergePlan) -> ExternalMergePlan:
    plan.snapshot_fingerprint = _compute_snapshot_fingerprint(plan)
    return plan


def _compute_snapshot_fingerprint(plan: ExternalMergePlan) -> str:
    h = hashlib.sha256()
    _fingerprint_path(h, "current/songlist", plan.current_songs_dir / "songlist")
    _fingerprint_path(h, "current/packlist", plan.current_songs_dir / "packlist")
    _fingerprint_path(h, "target/songlist", plan.target_songs_dir / "songlist")
    _fingerprint_path(h, "target/packlist", plan.target_songs_dir / "packlist")
    for action in sorted(plan.song_actions, key=lambda a: (a.kind, a.operation, a.identifier)):
        if action.source_path:
            _fingerprint_path(h, f"song/source/{action.identifier}", Path(action.source_path))
        if action.target_path:
            _fingerprint_path(h, f"song/target/{action.identifier}", Path(action.target_path))
    for action in sorted(plan.pack_image_actions, key=lambda a: (a.kind, a.operation, a.identifier)):
        if action.source_path:
            _fingerprint_path(h, f"pack_image/source/{action.identifier}", Path(action.source_path))
        if action.target_path:
            _fingerprint_path(h, f"pack_image/target/{action.identifier}", Path(action.target_path))
    return h.hexdigest()


def _fingerprint_path(h: "hashlib._Hash", label: str, path: Path) -> None:
    h.update(f"LABEL\0{label}\0".encode())
    if is_link_or_junction(path):
        h.update(b"LINK\0")
        return
    if not path_exists_lexically(path):
        h.update(b"MISSING\0")
        return
    if path.is_file():
        h.update(b"FILE\0")
        h.update(_sha256(path).encode())
        return
    if path.is_dir():
        h.update(b"DIR\0")
        for item in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
            rel = item.relative_to(path).as_posix()
            h.update(f"ITEM\0{rel}\0".encode())
            if is_link_or_junction(item):
                h.update(b"LINK\0")
            elif item.is_file():
                h.update(b"FILE\0")
                h.update(_sha256(item).encode())
            elif item.is_dir():
                h.update(b"DIR\0")
            else:
                h.update(b"OTHER\0")
        return
    h.update(b"OTHER\0")


def _execution_safety_issues(plan: ExternalMergePlan, backup_root: Path) -> list[MergeIssue]:
    issues: list[MergeIssue] = []
    target = plan.target_songs_dir
    current = plan.current_songs_dir
    backup_root = Path(backup_root)

    if _path_contains_or_equals(target, backup_root):
        issues.append(MergeIssue(BLOCKER, "backup_root_inside_target", "backup root must not be inside target songs.", (str(backup_root), str(target))))
    if _path_contains_or_equals(current, backup_root) or _same_path(current, backup_root):
        issues.append(MergeIssue(BLOCKER, "backup_root_inside_current", "backup root must not be inside current export.", (str(backup_root), str(current))))
    if _same_path(current, target):
        issues.append(MergeIssue(BLOCKER, "target_equals_current_input", "target songs directory must not equal current input.", (str(target),)))
    for parent in _existing_parents(backup_root):
        if is_link_or_junction(parent):
            issues.append(MergeIssue(BLOCKER, "backup_parent_is_link", "backup parent must not be a link or Junction.", (str(parent),)))
            break
    for path in _write_candidate_paths(plan):
        if not _path_contains_or_equals(target, path):
            issues.append(MergeIssue(BLOCKER, "write_path_escape", "candidate write path escapes target songs root.", (str(path), str(target))))
    for action in plan.pack_image_actions:
        if not _is_safe_file_name(action.identifier):
            issues.append(MergeIssue(BLOCKER, "pack_image_name_unsafe_at_execute", "pack image filename is unsafe.", (action.identifier,)))
    if is_link_or_junction(target):
        issues.append(MergeIssue(BLOCKER, "target_songs_dir_is_link_at_execute", "target songs directory must not be a link or Junction.", (str(target),)))
    pack_dir = target / "pack"
    if any(action.operation != "reuse" for action in plan.pack_image_actions) and is_link_or_junction(pack_dir):
        issues.append(MergeIssue(BLOCKER, "target_pack_dir_is_link_at_execute", "target pack directory must not be a link or Junction.", (str(pack_dir),)))
    for action in plan.song_actions:
        if action.target_path and is_link_or_junction(Path(action.target_path)):
            issues.append(MergeIssue(BLOCKER, "target_song_dir_is_link_at_execute", "affected song directory must not be a link or Junction.", (action.target_path,)))
    for action in plan.pack_image_actions:
        if action.operation != "reuse" and action.target_path and is_link_or_junction(Path(action.target_path)):
            issues.append(MergeIssue(BLOCKER, "target_pack_image_is_link_at_execute", "affected pack image must not be a link or Junction.", (action.target_path,)))
    return issues


def _write_candidate_paths(plan: ExternalMergePlan) -> list[Path]:
    paths = [plan.target_songs_dir / "songlist"]
    if plan.pack_actions:
        paths.append(plan.target_songs_dir / "packlist")
    for action in plan.song_actions:
        if action.target_path:
            paths.append(Path(action.target_path))
    for action in plan.pack_image_actions:
        if action.operation in {"add", "replace"} and action.target_path:
            paths.append(Path(action.target_path))
    return paths


def _create_backup_dir(backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        candidate = backup_root / f"{stamp}_{uuid.uuid4().hex[:8]}"
        try:
            candidate.mkdir()
            (candidate / "before").mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("鏃犳硶鍒涘缓鍞竴澶囦唤鐩綍")


def _base_manifest(plan: ExternalMergePlan, backup_dir: Path, status: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "current_songs_dir": str(plan.current_songs_dir),
        "target_songs_dir": str(plan.target_songs_dir),
        "snapshot_fingerprint": plan.snapshot_fingerprint,
        "plan_summary": plan.summary,
        "actions": [_action_to_json(action) for action in plan.song_actions + plan.pack_actions + plan.pack_image_actions],
        "backup_dir": str(backup_dir),
        "backed_up_items": [],
        "created_target_items": [],
        "changed_paths": [],
        "rollback_errors": [],
        "checkpoints": [],
    }


def _manifest_runtime_fields(ctx: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "status": status,
        "backed_up_items": list(ctx.get("backed_up_items", [])),
        "created_target_items": list(ctx.get("created_target_items", [])),
        "changed_paths": list(ctx.get("changed_paths", [])),
        "rollback_errors": list(ctx.get("rollback_errors", [])),
        "checkpoints": list(ctx.get("checkpoints", [])),
    }


def _checkpoint(backup_dir: Path, manifest: dict[str, Any], ctx: dict[str, Any], label: str) -> None:
    ctx.setdefault("checkpoints", []).append(label)
    manifest.update(_manifest_runtime_fields(ctx, "in_progress"))
    _write_manifest(backup_dir, manifest)


def _try_write_manifest_status(
    backup_dir: Path,
    manifest: dict[str, Any],
    ctx: dict[str, Any],
    status: str,
) -> list[MergeIssue]:
    manifest.update(_manifest_runtime_fields(ctx, status))
    try:
        _write_manifest(backup_dir, manifest)
        return []
    except Exception as ex:
        return [MergeIssue(WARNING, "manifest_write_failed", f"manifest write failed: {ex}", (str(backup_dir / "manifest.json"),))]


def _action_to_json(action: MergeAction) -> dict[str, Any]:
    return {
        "kind": action.kind,
        "operation": action.operation,
        "identifier": action.identifier,
        "source_path": action.source_path,
        "target_path": action.target_path,
        "details": action.details,
    }


def _write_manifest(backup_dir: Path, manifest: dict[str, Any]) -> None:
    _write_json_atomic(backup_dir / "manifest.json", manifest)


def _backup_affected_items(plan: ExternalMergePlan, backup_dir: Path, ctx: dict[str, Any], checkpoint) -> None:
    before = backup_dir / "before"
    _backup_file(plan.target_songs_dir / "songlist", before / "songlist", "songlist", ctx)
    checkpoint("backup:songlist")
    if plan.pack_actions:
        _backup_file(plan.target_songs_dir / "packlist", before / "packlist", "packlist", ctx)
        checkpoint("backup:packlist")
    for action in plan.song_actions:
        if action.operation == "update" and action.target_path:
            rel = f"songs/{action.identifier}"
            _backup_dir(Path(action.target_path), before / rel, rel, ctx)
            checkpoint(f"backup:{rel}")
    for action in plan.pack_image_actions:
        target = Path(action.target_path) if action.target_path else None
        if action.operation == "replace" and target is not None:
            rel = f"pack/{action.identifier}"
            _backup_file(target, before / rel, rel, ctx)
            checkpoint(f"backup:{rel}")


def _backup_file(source: Path, dest: Path, rel: str, ctx: dict[str, Any]) -> None:
    if not source.exists():
        return
    if is_link_or_junction(source):
        raise RuntimeError(f"refusing to back up link or Junction: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    ctx["backed_up_items"].append(rel)


def _backup_dir(source: Path, dest: Path, rel: str, ctx: dict[str, Any]) -> None:
    if not source.exists():
        return
    nested = find_nested_link_or_junction(source)
    if nested is not None:
        raise RuntimeError(f"refusing to back up directory containing link or Junction: {nested}")
    if dest.exists():
        raise RuntimeError(f"澶囦唤璺緞宸插瓨鍦細{dest}")
    shutil.copytree(source, dest, symlinks=False)
    ctx["backed_up_items"].append(rel)


def _create_staging_dir(target_songs_dir: Path) -> Path:
    parent = target_songs_dir.parent
    if is_link_or_junction(parent):
        raise RuntimeError("鐩爣 songs 鐖剁洰褰曚笉鑳芥槸閾炬帴鎴?Junction")
    for _ in range(100):
        candidate = parent / f".arc_slicer_merge_stage_{uuid.uuid4().hex[:8]}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("鏃犳硶鍒涘缓 staging 鐩綍")


def _stage_inputs(plan: ExternalMergePlan, stage_dir: Path) -> None:
    for action in plan.song_actions:
        source = Path(action.source_path) if action.source_path else None
        if source is None:
            continue
        dest = stage_dir / "songs" / action.identifier
        _copy_dir_and_verify(source, dest)
    for action in plan.pack_image_actions:
        if action.operation == "reuse" or not action.source_path:
            continue
        source = Path(action.source_path)
        if is_link_or_junction(source):
            raise RuntimeError(f"input pack image is link or Junction: {source}")
        dest = stage_dir / "pack" / action.identifier
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        if _sha256(source) != _sha256(dest):
            raise RuntimeError(f"staging pack image verification failed: {action.identifier}")


def _copy_dir_and_verify(source: Path, dest: Path) -> None:
    if dest.exists():
        raise RuntimeError(f"staging directory already exists: {dest}")
    nested = find_nested_link_or_junction(source)
    if nested is not None:
        raise RuntimeError(f"input song directory contains link or Junction: {nested}")
    shutil.copytree(source, dest, symlinks=False)
    nested = find_nested_link_or_junction(dest)
    if nested is not None:
        raise RuntimeError(f"staging song directory contains link or Junction: {nested}")
    if _directory_digest(source) != _directory_digest(dest):
        raise RuntimeError(f"staging directory verification failed: {source}")

def _install_song_directories(plan: ExternalMergePlan, stage_dir: Path, ctx: dict[str, Any], checkpoint) -> None:
    for action in plan.song_actions:
        source = stage_dir / "songs" / action.identifier
        target = Path(action.target_path) if action.target_path else plan.target_songs_dir / action.identifier
        rel = _rel_to_target(target, plan.target_songs_dir)
        if action.operation == "add":
            _install_song_directory(source, target, None, ctx)
            ctx["created_target_items"].append(rel)
            ctx["changed_paths"].append(rel)
            checkpoint(f"song_added:{rel}")
        elif action.operation == "update":
            swap = target.parent / f".arc_slicer_swap_{target.name}_{uuid.uuid4().hex[:8]}"
            _install_song_directory(source, target, swap, ctx)
            ctx["changed_paths"].append(rel)
            checkpoint(f"song_updated:{rel}")


def _install_song_directory(staged_source: Path, target: Path, swap: Path | None, ctx: dict[str, Any] | None = None) -> None:
    if swap is None and path_exists_lexically(target):
        raise RuntimeError(f"target song directory appeared before add install: {target}")
    if swap is not None:
        if swap.exists():
            raise RuntimeError(f"swap directory already exists: {swap}")
        target.rename(swap)
        if ctx is not None:
            ctx.setdefault("swaps", []).append(str(swap))
    try:
        staged_source.rename(target)
    except Exception:
        if swap is not None and swap.exists() and not target.exists():
            try:
                swap.rename(target)
                if ctx is not None and str(swap) in ctx.get("swaps", []):
                    ctx["swaps"].remove(str(swap))
            except Exception:
                pass
        raise


def _install_pack_images(plan: ExternalMergePlan, stage_dir: Path, ctx: dict[str, Any], checkpoint) -> None:
    for action in plan.pack_image_actions:
        if action.operation == "reuse":
            continue
        source = stage_dir / "pack" / action.identifier
        target = Path(action.target_path) if action.target_path else plan.target_songs_dir / "pack" / action.identifier
        _install_pack_image(source, target, replace=action.operation == "replace")
        rel = _rel_to_target(target, plan.target_songs_dir)
        if action.operation == "add":
            ctx["created_target_items"].append(rel)
        ctx["changed_paths"].append(rel)
        checkpoint(f"pack_image_{action.operation}:{rel}")


def _install_pack_image(staged_source: Path, target: Path, *, replace: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".arc_slicer_tmp_{target.name}_{uuid.uuid4().hex[:8]}")
    created_target = False
    try:
        shutil.copy2(staged_source, tmp)
        if replace:
            if is_link_or_junction(target):
                raise RuntimeError(f"target pack image is link or Junction: {target}")
            os.replace(tmp, target)
        else:
            if path_exists_lexically(target):
                raise FileExistsError(f"target pack image appeared before add install: {target}")
            with tmp.open("rb") as src, target.open("xb") as dst:
                created_target = True
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            tmp.unlink()
    except Exception:
        try:
            if tmp.exists():
                _remove_tree_or_file(tmp)
        except Exception:
            pass
        if not replace and created_target and target.exists():
            try:
                _remove_tree_or_file(target)
            except Exception:
                pass
        raise

def _write_json_atomic(path: Path, data: dict[str, Any] | None) -> None:
    if data is None:
        raise RuntimeError(f"no JSON data to write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".arc_slicer_tmp_{path.name}_{uuid.uuid4().hex[:8]}")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                _remove_tree_or_file(tmp)
        except Exception:
            pass
        raise


def _rollback(plan: ExternalMergePlan, backup_dir: Path | None, ctx: dict[str, Any], checkpoint=None) -> list[str]:
    errors: list[str] = []
    if backup_dir is None:
        return ["backup directory is missing; cannot restore"]
    before = backup_dir / "before"

    for rel in ("songlist", "packlist"):
        backup = before / rel
        if backup.exists():
            _restore_file(backup, plan.target_songs_dir / rel, rel, errors)
            if checkpoint is not None:
                checkpoint(f"rollback:{rel}")
    for action in plan.pack_image_actions:
        if action.operation == "replace":
            rel = f"pack/{action.identifier}"
            _restore_file(before / rel, plan.target_songs_dir / rel, rel, errors)
            if checkpoint is not None:
                checkpoint(f"rollback:{rel}")
    for action in plan.song_actions:
        if action.operation == "update":
            rel = f"songs/{action.identifier}"
            _restore_dir(before / rel, plan.target_songs_dir / action.identifier, rel, errors)
            if checkpoint is not None:
                checkpoint(f"rollback:{rel}")
    for rel in reversed(ctx.get("created_target_items", [])):
        _delete_target_item(plan.target_songs_dir / rel, rel, errors)
        if checkpoint is not None:
            checkpoint(f"rollback_delete:{rel}")
    for swap in list(ctx.get("swaps", [])):
        _cleanup_temp_path(Path(swap), errors)
        if checkpoint is not None:
            checkpoint(f"rollback_cleanup:{swap}")
    ctx["rollback_errors"] = errors
    return errors


def _restore_file(backup: Path, target: Path, rel: str, errors: list[str]) -> None:
    tmp = target.with_name(f".arc_slicer_tmp_restore_{target.name}_{uuid.uuid4().hex[:8]}")
    try:
        if backup.exists():
            if is_link_or_junction(backup):
                raise RuntimeError(f"backup is link or Junction: {backup}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, tmp)
            with tmp.open("rb+") as f:
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
    except Exception as ex:
        try:
            if tmp.exists():
                _remove_tree_or_file(tmp)
        except Exception:
            pass
        errors.append(f"{rel}: {ex}")


def _restore_dir(backup: Path, target: Path, rel: str, errors: list[str]) -> None:
    try:
        if backup.exists():
            nested = find_nested_link_or_junction(backup)
            if nested is not None:
                raise RuntimeError(f"backup directory contains link or Junction: {nested}")
        if target.exists():
            _remove_tree_or_file(target)
        if backup.exists():
            shutil.copytree(backup, target, symlinks=False)
    except Exception as ex:
        errors.append(f"{rel}: {ex}")

def _delete_target_item(path: Path, rel: str, errors: list[str]) -> None:
    try:
        if path.exists():
            _remove_tree_or_file(path)
    except Exception as ex:
        errors.append(f"{rel}: {ex}")


def _cleanup_swaps(ctx: dict[str, Any]) -> None:
    for swap in list(ctx.get("swaps", [])):
        _cleanup_temp_path(Path(swap))
        ctx["swaps"].remove(swap)


def _cleanup_temp_path(path: Path, errors: list[str] | None = None) -> None:
    try:
        if path.exists():
            _remove_tree_or_file(path)
    except Exception as ex:
        if errors is not None:
            errors.append(f"{path}: {ex}")
        else:
            raise


def _remove_tree_or_file(path: Path) -> None:
    if is_link_or_junction(path):
        raise RuntimeError(f"refusing to delete link or Junction: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _directory_digest(path: Path) -> str:
    h = hashlib.sha256()
    _fingerprint_path(h, "dir", path)
    return h.hexdigest()


def _rel_to_target(path: Path, target_songs_dir: Path) -> str:
    try:
        return path.relative_to(target_songs_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _path_contains_or_equals(parent: Path, child: Path) -> bool:
    parent_s = _norm_abs(parent)
    child_s = _norm_abs(child)
    try:
        common = os.path.commonpath([parent_s, child_s])
    except ValueError:
        return False
    return common == parent_s


def _same_path(a: Path, b: Path) -> bool:
    return _norm_abs(a) == _norm_abs(b)


def _norm_abs(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


def path_exists_lexically(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return Path(path).exists()


def _existing_parents(path: Path) -> list[Path]:
    out = []
    cur = Path(path)
    while not cur.exists() and cur.parent != cur:
        cur = cur.parent
    while cur.parent != cur:
        out.append(cur)
        cur = cur.parent
    out.append(cur)
    return out


def find_nested_link_or_junction(root: Path) -> Path | None:
    if is_link_or_junction(root):
        return root
    if not root.is_dir():
        return None
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    child = Path(entry.path)
                    if is_link_or_junction(child):
                        return child
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(child)
                    except OSError:
                        return child
        except OSError:
            return current
    return None


def is_link_or_junction(path: Path) -> bool:
    try:
        if Path(path).is_symlink():
            return True
        st = os.lstat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _validate_root(plan: ExternalMergePlan, path: Path, role: str, code_prefix: str) -> None:
    if is_link_or_junction(path):
        _block(plan, f"{code_prefix}_is_link", f"{role} songs directory must not be a link or Junction.", path)
        return
    if not path_exists_lexically(path):
        _block(plan, f"{code_prefix}_missing", f"{role} songs directory is missing.", path)
        return
    if not path.is_dir():
        _block(plan, f"{code_prefix}_not_dir", f"{role} songs path is not a directory.", path)
        return
    if is_link_or_junction(path):
        _block(plan, f"{code_prefix}_is_link", f"{role} songs directory must not be a link or Junction.", path)


def _read_songlist(plan: ExternalMergePlan, path: Path, role: str) -> dict[str, Any] | None:
    return _read_json_document(plan, path, role, "songlist", "songs", required=True)


def _read_packlist(plan: ExternalMergePlan, path: Path, role: str, required: bool) -> dict[str, Any] | None:
    return _read_json_document(plan, path, role, "packlist", "packs", required=required)


def _read_json_document(
    plan: ExternalMergePlan,
    path: Path,
    role: str,
    doc_name: str,
    array_key: str,
    required: bool,
) -> dict[str, Any] | None:
    if is_link_or_junction(path):
        _block(plan, f"{role}_{doc_name}_is_link", f"{role} {doc_name} must not be a link or Junction.", path)
        return None
    if not path_exists_lexically(path):
        if required:
            _block(plan, f"{role}_{doc_name}_missing", f"{role} {doc_name} is missing.", path)
        return None
    if not path.is_file():
        _block(plan, f"{role}_{doc_name}_not_file", f"{role} {doc_name} is not a file.", path)
        return None
    if is_link_or_junction(path):
        _block(plan, f"{role}_{doc_name}_is_link", f"{role} {doc_name} must not be a link or Junction.", path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        _block(plan, f"{role}_{doc_name}_invalid_json", f"{role} {doc_name} cannot be parsed: {ex}", path)
        return None
    if not isinstance(data, dict) or not isinstance(data.get(array_key), list):
        _block(plan, f"{role}_{doc_name}_invalid_shape", f"{role} {doc_name} must contain a top-level {array_key} array.", path)
        return None
    return data


def _index_entries(
    plan: ExternalMergePlan,
    entries: list[Any],
    entry_kind: str,
    role: str,
) -> dict[str, dict[str, Any]] | None:
    indexed: dict[str, dict[str, Any]] = {}
    ok = True
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            _block(plan, f"{role}_{entry_kind}_entry_invalid", f"{role} {entry_kind} entry is not an object.", str(idx))
            ok = False
            continue
        ident = entry.get("id")
        if not isinstance(ident, str) or not ident.strip():
            _block(plan, f"{role}_{entry_kind}_id_missing", f"{role} {entry_kind} entry is missing id.", str(idx))
            ok = False
            continue
        if ident in indexed:
            _block(plan, f"{role}_{entry_kind}_id_duplicate", f"{role} {entry_kind} has duplicate id: {ident}", ident)
            ok = False
            continue
        indexed[ident] = entry
    return indexed if ok else None


def is_safe_song_id(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if not _SAFE_SONG_ID_RE.fullmatch(value):
        return False
    lowered = value.lower()
    if lowered in _RESERVED_SONG_IDS or lowered in _WINDOWS_RESERVED_NAMES:
        return False
    if Path(value).name != value or Path(value).drive or Path(value).is_absolute():
        return False
    return True


def _validate_song_ids(
    plan: ExternalMergePlan,
    song_ids: dict[str, dict[str, Any]],
    role: str,
    ids_to_validate: set[str],
) -> None:
    for song_id in sorted(set(song_ids) & ids_to_validate):
        if not is_safe_song_id(song_id):
            _block(plan, f"{role}_song_id_unsafe", f"{role} song id is not a safe single directory name: {song_id}", song_id)


def _validate_current_song_dirs(plan: ExternalMergePlan, current_songs_dir: Path, input_song_ids: dict[str, dict[str, Any]]) -> None:
    expected = set(input_song_ids)
    for song_id in expected:
        if not is_safe_song_id(song_id):
            continue
        song_dir = current_songs_dir / song_id
        if is_link_or_junction(song_dir):
            _block(plan, "input_song_dir_is_link", f"input song directory must not be a link or Junction: {song_id}", song_dir)
        elif not path_exists_lexically(song_dir):
            _block(plan, "input_song_dir_missing", f"input song directory is missing: {song_id}", song_dir)
        elif not song_dir.is_dir():
            _block(plan, "input_song_dir_not_dir", f"input song path is not a directory: {song_id}", song_dir)
        else:
            nested = find_nested_link_or_junction(song_dir)
            if nested is not None:
                _block(plan, "input_song_dir_contains_link", "input song directory contains a symlink or Junction.", nested)

    for item in current_songs_dir.iterdir() if current_songs_dir.is_dir() else []:
        if item.name in _IGNORED_SONGS_DIRS or not item.is_dir():
            continue
        if item.name not in expected:
            _block(plan, "input_unlisted_song_dir", f"input songs root contains a directory not listed in songlist: {item.name}", item)

    pack_dir = current_songs_dir / "pack"
    if is_link_or_junction(pack_dir):
        _block(plan, "input_pack_dir_is_link", "input pack directory must not be a link or Junction.", pack_dir)

def _plan_song_actions(
    plan: ExternalMergePlan,
    current_songs_dir: Path,
    target_songs_dir: Path,
    input_songs: list[dict[str, Any]],
    target_songs: list[dict[str, Any]],
    input_song_ids: dict[str, dict[str, Any]],
    target_song_ids: dict[str, dict[str, Any]],
) -> None:
    del target_songs
    target_id_set = set(target_song_ids)
    for song in input_songs:
        song_id = song["id"]
        if not is_safe_song_id(song_id):
            continue
        source_dir = current_songs_dir / song_id
        target_dir = target_songs_dir / song_id
        target_has_meta = song_id in target_id_set
        target_has_dir = path_exists_lexically(target_dir)
        if is_link_or_junction(target_dir):
            _block(plan, "target_song_dir_is_link", f"target song directory must not be a link or Junction: {song_id}", target_dir)
            continue
        if target_has_dir and target_dir.is_dir():
            nested = find_nested_link_or_junction(target_dir)
            if nested is not None:
                _block(plan, "target_song_dir_contains_link", "target song directory contains a symlink or Junction.", nested)
                continue
        if not target_has_meta and not target_has_dir:
            plan.song_actions.append(_action("song", "add", song_id, source_dir, target_dir))
        elif target_has_meta and target_has_dir and target_dir.is_dir():
            plan.song_actions.append(_action("song", "update", song_id, source_dir, target_dir))
        elif target_has_meta and not target_has_dir:
            _block(plan, "target_song_metadata_without_dir", f"target songlist has id but directory is missing: {song_id}", target_dir)
        elif not target_has_meta and target_has_dir:
            _block(plan, "target_song_dir_without_metadata", f"target has song directory without songlist id: {song_id}", target_dir)
        else:
            _block(plan, "target_song_dir_invalid", f"target song path is invalid: {song_id}", target_dir)

def _validate_input_song_sets(
    plan: ExternalMergePlan,
    input_songs: list[dict[str, Any]],
    input_pack_ids: dict[str, dict[str, Any]],
    target_pack_ids: dict[str, dict[str, Any]],
) -> None:
    available = set(input_pack_ids) | set(target_pack_ids)
    for song in input_songs:
        song_id = str(song.get("id", ""))
        set_id = song.get("set")
        if not isinstance(set_id, str) or not set_id.strip():
            _block(plan, "input_song_set_missing", f"input song is missing set: {song_id}", song_id)
        elif set_id not in available:
            _block(plan, "input_song_set_missing_pack", f"input song set has no matching pack: {song_id} -> {set_id}", song_id, set_id)


def _plan_pack_actions(
    plan: ExternalMergePlan,
    input_packs: list[dict[str, Any]],
    target_packs: list[dict[str, Any]],
    input_pack_ids: dict[str, dict[str, Any]],
    target_pack_ids: dict[str, dict[str, Any]],
) -> None:
    del input_pack_ids, target_packs
    for pack in input_packs:
        pack_id = pack["id"]
        operation = "update" if pack_id in target_pack_ids else "add"
        plan.pack_actions.append(_action("pack", operation, pack_id, None, None, {"img": pack.get("img")}))


def _validate_input_pack_images(plan: ExternalMergePlan, current_songs_dir: Path, input_packs: list[dict[str, Any]]) -> None:
    for pack in input_packs:
        pack_id = str(pack.get("id", ""))
        img = pack.get("img")
        if not _is_safe_file_name(img):
            _block(plan, "input_pack_img_invalid", f"pack.img must be a safe filename: {pack_id}", pack_id, str(img))
            continue
        source = current_songs_dir / "pack" / img
        if is_link_or_junction(source):
            _block(plan, "input_pack_image_is_link", f"input pack image must not be a link or Junction: {img}", source)
        elif not path_exists_lexically(source):
            _block(plan, "input_pack_image_missing", f"input pack image is missing: {img}", source)
        elif not source.is_file():
            _block(plan, "input_pack_image_not_file", f"input pack image is not a file: {img}", source)


def _plan_pack_image_actions(
    plan: ExternalMergePlan,
    current_songs_dir: Path,
    target_songs_dir: Path,
    input_packs: list[dict[str, Any]],
    target_packs: list[dict[str, Any]],
    target_pack_ids: dict[str, dict[str, Any]],
) -> None:
    target_pack_dir = target_songs_dir / "pack"
    if is_link_or_junction(target_pack_dir):
        _block(plan, "target_pack_dir_is_link", "target pack directory must not be a link or Junction.", target_pack_dir)
        return
    if not path_exists_lexically(target_pack_dir):
        _block(plan, "target_pack_dir_missing", "target pack directory is missing.", target_pack_dir)
        return
    if not target_pack_dir.is_dir():
        _block(plan, "target_pack_dir_not_dir", "target pack path is not a directory.", target_pack_dir)
        return

    img_to_pack_ids: dict[str, set[str]] = {}
    for pack in target_packs:
        img = pack.get("img")
        pack_id = pack.get("id")
        if isinstance(img, str) and isinstance(pack_id, str):
            img_to_pack_ids.setdefault(img, set()).add(pack_id)

    input_by_img: dict[str, list[dict[str, Any]]] = {}
    for pack in input_packs:
        img = pack.get("img")
        if not _is_safe_file_name(img):
            continue
        input_by_img.setdefault(img, []).append(pack)

    for img in sorted(input_by_img):
        packs = input_by_img[img]
        referenced_pack_ids = sorted({pack["id"] for pack in packs})
        source = current_songs_dir / "pack" / img
        target = target_pack_dir / img
        if not source.is_file() or is_link_or_junction(source):
            continue
        if is_link_or_junction(target):
            _block(plan, "target_pack_image_is_link", f"target pack image must not be a link or Junction: {img}", target)
            continue
        target_referenced_pack_ids = sorted(img_to_pack_ids.get(img, set()))
        source_hash = _sha256(source)
        target_hash = _sha256(target) if path_exists_lexically(target) and target.is_file() else None
        details: dict[str, Any] = {
            "referenced_pack_ids": referenced_pack_ids,
            "target_referenced_pack_ids": target_referenced_pack_ids,
            "source_hash": source_hash,
        }
        if len(referenced_pack_ids) == 1:
            details["pack_id"] = referenced_pack_ids[0]
        if target_hash is not None:
            details["target_hash"] = target_hash

        same_img_existing_ids = sorted(
            pack["id"]
            for pack in packs
            if pack["id"] in target_pack_ids and target_pack_ids[pack["id"]].get("img") == img
        )
        old_imgs = {
            pack["id"]: target_pack_ids[pack["id"]].get("img")
            for pack in packs
            if pack["id"] in target_pack_ids and target_pack_ids[pack["id"]].get("img") != img
        }
        if old_imgs:
            details["old_imgs"] = old_imgs
            if len(old_imgs) == 1:
                details["old_img"] = next(iter(old_imgs.values()))
        if same_img_existing_ids:
            details["same_img_existing_pack_ids"] = same_img_existing_ids

        if not path_exists_lexically(target):
            if same_img_existing_ids:
                _block(plan, "target_pack_image_missing_for_update", f"target pack image is missing for existing pack update: {img}", target)
            else:
                plan.pack_image_actions.append(_action("pack_image", "add", img, source, target, details))
            continue
        if not target.is_file():
            _block(plan, "target_pack_image_not_file", f"target pack image path is not a file: {img}", target)
            continue
        if source_hash == target_hash:
            plan.pack_image_actions.append(_action("pack_image", "reuse", img, source, target, details))
            continue

        other_refs = sorted(set(target_referenced_pack_ids) - set(same_img_existing_ids))
        if same_img_existing_ids and not other_refs:
            plan.pack_image_actions.append(_action("pack_image", "replace", img, source, target, details))
        elif same_img_existing_ids:
            _block(
                plan,
                "pack_image_shared_update_conflict",
                f"鏇存柊 pack 浼氭敼鍙樺叾浠?pack 鍏辩敤鐨勫浘鐗囷細{img}",
                img,
                *other_refs,
            )
        else:
            _block(plan, "pack_image_name_conflict", f"pack image filename is already occupied by different content: {img}", source, target)


def _merge_entries(target_entries: list[dict[str, Any]], input_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    input_by_id = {entry["id"]: entry for entry in input_entries}
    used: set[str] = set()
    merged: list[dict[str, Any]] = []
    for target_entry in target_entries:
        ident = target_entry.get("id")
        if ident in input_by_id:
            merged.append(json.loads(json.dumps(input_by_id[ident], ensure_ascii=False)))
            used.add(ident)
        else:
            merged.append(json.loads(json.dumps(target_entry, ensure_ascii=False)))
    for input_entry in input_entries:
        ident = input_entry["id"]
        if ident not in used:
            merged.append(json.loads(json.dumps(input_entry, ensure_ascii=False)))
    return merged


def _same_file_content(a: Path, b: Path) -> bool:
    return _sha256(a) == _sha256(b)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_safe_file_name(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value in {".", ".."} or ".." in Path(value).parts:
        return False
    if Path(value).name != value:
        return False
    if any(sep and sep in value for sep in (os.sep, os.altsep)):
        return False
    if Path(value).drive:
        return False
    return True


def _is_tool_export_songs_dir(path: Path) -> bool:
    parts = [p.lower() for p in Path(_norm_abs(path)).parts]
    if len(parts) < 4 or parts[-1] != "songs":
        return False
    return parts[-4:-1] == ["arcslicerdata", "out", "current_export"] or parts[-4:-1] == [
        "arcslicerdata",
        "out",
        "library_export",
    ]


def _is_library_export_songs_dir(path: Path) -> bool:
    parts = [p.lower() for p in Path(_norm_abs(path)).parts]
    return len(parts) >= 4 and parts[-1] == "songs" and parts[-4:-1] == ["arcslicerdata", "out", "library_export"]


def _action(
    kind: str,
    operation: str,
    identifier: str,
    source_path: Path | None,
    target_path: Path | None,
    details: dict[str, Any] | None = None,
) -> MergeAction:
    return MergeAction(
        kind=kind,
        operation=operation,
        identifier=identifier,
        source_path=str(source_path) if source_path is not None else None,
        target_path=str(target_path) if target_path is not None else None,
        details=details or {},
    )


def _block(plan: ExternalMergePlan, code: str, message: str, *paths: object) -> None:
    plan.blockers.append(
        MergeIssue(
            severity=BLOCKER,
            code=code,
            message=message,
            paths=tuple(str(path) for path in paths),
        )
    )
