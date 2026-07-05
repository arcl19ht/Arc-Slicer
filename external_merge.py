from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BLOCKER = "blocker"
WARNING = "warning"

_IGNORED_SONGS_DIRS = {"pack", "unlock", "unlocks"}


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


def _count(actions: list[MergeAction], operation: str) -> int:
    return sum(1 for action in actions if action.operation == operation)


def build_external_merge_plan(current_songs_dir: Path, target_songs_dir: Path) -> ExternalMergePlan:
    current_songs_dir = Path(current_songs_dir)
    target_songs_dir = Path(target_songs_dir)
    plan = ExternalMergePlan(current_songs_dir=current_songs_dir, target_songs_dir=target_songs_dir)

    _validate_root(plan, current_songs_dir, "current", "current_songs_dir")
    _validate_root(plan, target_songs_dir, "target", "target_songs_dir")
    if _is_tool_export_songs_dir(target_songs_dir):
        _block(plan, "target_is_tool_export", "目标目录不能是工具自己的 current_export 或 library_export。", target_songs_dir)

    input_songlist = _read_songlist(plan, current_songs_dir / "songlist", "input")
    target_songlist = _read_songlist(plan, target_songs_dir / "songlist", "target")
    input_packlist = _read_packlist(plan, current_songs_dir / "packlist", "input", required=False)
    target_packlist = _read_packlist(plan, target_songs_dir / "packlist", "target", required=True)

    if input_songlist is None or target_songlist is None:
        return plan

    input_songs = input_songlist["songs"]
    target_songs = target_songlist["songs"]
    input_song_ids = _index_entries(plan, input_songs, "song", "input")
    target_song_ids = _index_entries(plan, target_songs, "song", "target")
    if input_song_ids is None or target_song_ids is None:
        return plan

    _validate_current_song_dirs(plan, current_songs_dir, input_song_ids)
    _plan_song_actions(plan, current_songs_dir, target_songs_dir, input_songs, target_songs, input_song_ids, target_song_ids)

    if target_packlist is None:
        return plan

    target_packs = target_packlist["packs"]
    target_pack_ids = _index_entries(plan, target_packs, "pack", "target")
    if target_pack_ids is None:
        return plan

    input_pack_ids: dict[str, dict[str, Any]] = {}
    if input_packlist is not None:
        input_pack_ids_maybe = _index_entries(plan, input_packlist["packs"], "pack", "input")
        if input_pack_ids_maybe is None:
            return plan
        input_pack_ids = input_pack_ids_maybe
        _validate_input_pack_images(plan, current_songs_dir, input_packlist["packs"])
        _plan_pack_actions(plan, input_packlist["packs"], target_packs, input_pack_ids, target_pack_ids)
        _plan_pack_image_actions(plan, current_songs_dir, target_songs_dir, input_packlist["packs"], target_packs, target_pack_ids)
        plan.merged_packlist_data = {"packs": _merge_entries(target_packs, input_packlist["packs"])}
    else:
        plan.merged_packlist_data = {"packs": json.loads(json.dumps(target_packs, ensure_ascii=False))}

    _validate_input_song_sets(plan, input_songs, input_pack_ids, target_pack_ids)
    plan.merged_songlist_data = {"songs": _merge_entries(target_songs, input_songs)}
    return plan


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
    if not path.exists():
        _block(plan, f"{code_prefix}_missing", f"{role} songs 目录不存在。", path)
        return
    if not path.is_dir():
        _block(plan, f"{code_prefix}_not_dir", f"{role} songs 路径不是目录。", path)
        return
    if is_link_or_junction(path):
        _block(plan, f"{code_prefix}_is_link", f"{role} songs 目录不能是链接或 Junction。", path)


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
    if not path.exists():
        if required:
            _block(plan, f"{role}_{doc_name}_missing", f"{role} {doc_name} 不存在。", path)
        return None
    if not path.is_file():
        _block(plan, f"{role}_{doc_name}_not_file", f"{role} {doc_name} 不是文件。", path)
        return None
    if is_link_or_junction(path):
        _block(plan, f"{role}_{doc_name}_is_link", f"{role} {doc_name} 不能是链接或 Junction。", path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        _block(plan, f"{role}_{doc_name}_invalid_json", f"{role} {doc_name} 无法解析：{ex}", path)
        return None
    if not isinstance(data, dict) or not isinstance(data.get(array_key), list):
        _block(plan, f"{role}_{doc_name}_invalid_shape", f"{role} {doc_name} 顶层必须包含 {array_key} 数组。", path)
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
            _block(plan, f"{role}_{entry_kind}_entry_invalid", f"{role} {entry_kind} 条目不是对象。", str(idx))
            ok = False
            continue
        ident = entry.get("id")
        if not isinstance(ident, str) or not ident.strip():
            _block(plan, f"{role}_{entry_kind}_id_missing", f"{role} {entry_kind} 条目缺少 id。", str(idx))
            ok = False
            continue
        if ident in indexed:
            _block(plan, f"{role}_{entry_kind}_id_duplicate", f"{role} {entry_kind} 存在重复 id：{ident}", ident)
            ok = False
            continue
        indexed[ident] = entry
    return indexed if ok else None


def _validate_current_song_dirs(plan: ExternalMergePlan, current_songs_dir: Path, input_song_ids: dict[str, dict[str, Any]]) -> None:
    expected = set(input_song_ids)
    for song_id in expected:
        song_dir = current_songs_dir / song_id
        if not song_dir.exists():
            _block(plan, "input_song_dir_missing", f"输入 songlist 引用的歌曲目录不存在：{song_id}", song_dir)
        elif not song_dir.is_dir():
            _block(plan, "input_song_dir_not_dir", f"输入歌曲路径不是目录：{song_id}", song_dir)
        elif is_link_or_junction(song_dir):
            _block(plan, "input_song_dir_is_link", f"输入歌曲目录不能是链接或 Junction：{song_id}", song_dir)

    for item in current_songs_dir.iterdir() if current_songs_dir.is_dir() else []:
        if item.name in _IGNORED_SONGS_DIRS or not item.is_dir():
            continue
        if item.name not in expected:
            _block(plan, "input_unlisted_song_dir", f"输入 songs 根下存在未列入 songlist 的歌曲目录：{item.name}", item)

    pack_dir = current_songs_dir / "pack"
    if pack_dir.exists() and is_link_or_junction(pack_dir):
        _block(plan, "input_pack_dir_is_link", "输入 pack 目录不能是链接或 Junction。", pack_dir)


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
        source_dir = current_songs_dir / song_id
        target_dir = target_songs_dir / song_id
        target_has_meta = song_id in target_id_set
        target_has_dir = target_dir.exists()
        if target_has_dir and is_link_or_junction(target_dir):
            _block(plan, "target_song_dir_is_link", f"受影响的目标歌曲目录不能是链接或 Junction：{song_id}", target_dir)
            continue
        if not target_has_meta and not target_has_dir:
            plan.song_actions.append(_action("song", "add", song_id, source_dir, target_dir))
        elif target_has_meta and target_has_dir and target_dir.is_dir():
            plan.song_actions.append(_action("song", "update", song_id, source_dir, target_dir))
        elif target_has_meta and not target_has_dir:
            _block(plan, "target_song_metadata_without_dir", f"目标 songlist 存在 id 但歌曲目录缺失：{song_id}", target_dir)
        elif not target_has_meta and target_has_dir:
            _block(plan, "target_song_dir_without_metadata", f"目标存在同名歌曲目录但 songlist 无对应 id：{song_id}", target_dir)
        else:
            _block(plan, "target_song_dir_invalid", f"目标歌曲路径异常：{song_id}", target_dir)


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
            _block(plan, "input_song_set_missing", f"输入歌曲缺少 set：{song_id}", song_id)
        elif set_id not in available:
            _block(plan, "input_song_set_missing_pack", f"输入歌曲 set 没有对应 pack：{song_id} -> {set_id}", song_id, set_id)


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
            _block(plan, "input_pack_img_invalid", f"pack.img 必须是安全文件名：{pack_id}", pack_id, str(img))
            continue
        source = current_songs_dir / "pack" / img
        if not source.exists():
            _block(plan, "input_pack_image_missing", f"输入 pack 图片缺失：{img}", source)
        elif not source.is_file():
            _block(plan, "input_pack_image_not_file", f"输入 pack 图片不是文件：{img}", source)
        elif is_link_or_junction(source):
            _block(plan, "input_pack_image_is_link", f"输入 pack 图片不能是链接或 Junction：{img}", source)


def _plan_pack_image_actions(
    plan: ExternalMergePlan,
    current_songs_dir: Path,
    target_songs_dir: Path,
    input_packs: list[dict[str, Any]],
    target_packs: list[dict[str, Any]],
    target_pack_ids: dict[str, dict[str, Any]],
) -> None:
    target_pack_dir = target_songs_dir / "pack"
    if not target_pack_dir.exists():
        _block(plan, "target_pack_dir_missing", "目标 pack 目录不存在。", target_pack_dir)
        return
    if not target_pack_dir.is_dir():
        _block(plan, "target_pack_dir_not_dir", "目标 pack 路径不是目录。", target_pack_dir)
        return
    if is_link_or_junction(target_pack_dir):
        _block(plan, "target_pack_dir_is_link", "目标 pack 目录不能是链接或 Junction。", target_pack_dir)
        return

    img_to_pack_ids: dict[str, set[str]] = {}
    for pack in target_packs:
        img = pack.get("img")
        pack_id = pack.get("id")
        if isinstance(img, str) and isinstance(pack_id, str):
            img_to_pack_ids.setdefault(img, set()).add(pack_id)

    for pack in input_packs:
        pack_id = pack["id"]
        img = pack.get("img")
        if not _is_safe_file_name(img):
            continue
        source = current_songs_dir / "pack" / img
        target = target_pack_dir / img
        if not source.is_file():
            continue
        if is_link_or_junction(target):
            _block(plan, "target_pack_image_is_link", f"目标 pack 图片不能是链接或 Junction：{img}", target)
            continue
        target_pack = target_pack_ids.get(pack_id)
        if target_pack is None:
            _plan_new_pack_image(plan, pack_id, img, source, target)
        else:
            _plan_update_pack_image(plan, pack_id, img, source, target, target_pack, img_to_pack_ids)


def _plan_new_pack_image(plan: ExternalMergePlan, pack_id: str, img: str, source: Path, target: Path) -> None:
    if not target.exists():
        plan.pack_image_actions.append(_action("pack_image", "add", img, source, target, {"pack_id": pack_id}))
    elif not target.is_file():
        _block(plan, "target_pack_image_not_file", f"目标 pack 图片路径不是文件：{img}", target)
    elif _same_file_content(source, target):
        plan.pack_image_actions.append(_action("pack_image", "reuse", img, source, target, {"pack_id": pack_id}))
    else:
        _block(plan, "pack_image_name_conflict", f"新 pack 的图片文件名已被不同内容占用：{img}", source, target)


def _plan_update_pack_image(
    plan: ExternalMergePlan,
    pack_id: str,
    img: str,
    source: Path,
    target: Path,
    target_pack: dict[str, Any],
    img_to_pack_ids: dict[str, set[str]],
) -> None:
    old_img = target_pack.get("img")
    if old_img == img:
        if not target.exists():
            plan.pack_image_actions.append(_action("pack_image", "add", img, source, target, {"pack_id": pack_id}))
        elif not target.is_file():
            _block(plan, "target_pack_image_not_file", f"目标 pack 图片路径不是文件：{img}", target)
        elif _same_file_content(source, target):
            plan.pack_image_actions.append(_action("pack_image", "reuse", img, source, target, {"pack_id": pack_id}))
        else:
            other_refs = sorted(img_to_pack_ids.get(img, set()) - {pack_id})
            if other_refs:
                _block(
                    plan,
                    "pack_image_shared_update_conflict",
                    f"更新 pack 会改变其他 pack 共用的图片：{img}",
                    img,
                    *other_refs,
                )
            else:
                plan.pack_image_actions.append(_action("pack_image", "replace", img, source, target, {"pack_id": pack_id}))
        return

    if not target.exists():
        plan.pack_image_actions.append(
            _action("pack_image", "add", img, source, target, {"pack_id": pack_id, "old_img": old_img})
        )
    elif not target.is_file():
        _block(plan, "target_pack_image_not_file", f"目标 pack 图片路径不是文件：{img}", target)
    elif _same_file_content(source, target):
        plan.pack_image_actions.append(
            _action("pack_image", "reuse", img, source, target, {"pack_id": pack_id, "old_img": old_img})
        )
    else:
        _block(plan, "pack_image_name_conflict", f"更新 pack 的新图片文件名已被不同内容占用：{img}", source, target)


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
    parts = [p.lower() for p in path.parts]
    if len(parts) < 4 or parts[-1] != "songs":
        return False
    return parts[-4:-1] == ["arcslicerdata", "out", "current_export"] or parts[-4:-1] == [
        "arcslicerdata",
        "out",
        "library_export",
    ]


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
