"""Export planning and songlist/packlist helpers."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Callable

from arc_slicer.aff import _scale_bpm_string, slice_aff as default_slice_aff
from arc_slicer.audio import _get_ffmpeg as default_get_ffmpeg, slice_ogg as default_slice_ogg
from arc_slicer.difficulties import (
    DifficultyDefinition, discover_song_difficulties, validate_selected_difficulties,
)
from arc_slicer.paths import DATA_ROOT, OUT_DIR, SONGLIST_EXAMPLE_PATH
from arc_slicer.segments import effective_segment_speed, normalize_speed_token, validate_speed_value

JACKET_FILENAMES = ("1080_base.jpg", "base.jpg", "1080_base_256.jpg")
PACK_COVER_SIZE = (374, 750)
PACK_COVER_UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg"}
PACK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
PACK_DEFAULT_SECTION = "collab"
PACK_SECTION_OPTIONS = (
    "collab",
    "arcaea",
    "mainstory",
    "mainstory2",
    "sidestory",
    "archive",
    "free",
)

@dataclass
class SongTemplate:
    title_base: str
    artist: str
    bpm: str
    bpm_base: float
    set: str
    purchase: str
    side: int
    bg: str
    version: str
    chart_designer: str
    jacket_designer: str
    rating: int
    rating_plus: bool


@dataclass
class PackTemplate:
    pack_id: str
    name: str
    description: str
    img: str
    cover_source: str
    cover_path: str = ""
    section: str = PACK_DEFAULT_SECTION


def _speed_text(speed: float) -> str:
    speed = validate_speed_value(float(speed))
    text = format(speed, ".12g")
    decimal = Decimal(text).normalize()
    out = format(decimal, "f")
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return out or "0"


def build_segment_id(source_id: str, start_ms: int, end_ms: int, speed: float) -> str:
    if not source_id:
        raise ValueError("source_id 不能为空")
    return f"{source_id}_{int(start_ms)}_{int(end_ms)}_x{normalize_speed_token(speed)}"


def build_segment_display_title(source_title: str, start_ms: int, end_ms: int, speed: float) -> str:
    title = str(source_title or "").strip() or "Untitled"
    return f"{title} [{int(start_ms)}–{int(end_ms)}ms · {_speed_text(speed)}×]"


def build_segment_export_plan(source_id: str, segments: list[dict], default_speed: float) -> list[dict]:
    default_speed = validate_speed_value(float(default_speed))
    plan: list[dict] = []
    seen: dict[str, int] = {}
    for index, seg in enumerate(segments):
        try:
            start_ms = int(seg["s"])
            end_ms = int(seg["e"])
        except (KeyError, TypeError, ValueError) as ex:
            raise ValueError(f"第 {index + 1} 个时间段无效") from ex
        if end_ms <= start_ms:
            raise ValueError(f"第 {index + 1} 个时间段无效: s={start_ms} e={end_ms}")
        try:
            speed = effective_segment_speed(default_speed, seg.get("speed_override"))
        except (TypeError, ValueError) as ex:
            raise ValueError(f"第 {index + 1} 个时间段倍速无效: {ex}") from ex
        segment_id = build_segment_id(source_id, start_ms, end_ms, speed)
        if segment_id in seen:
            raise ValueError(
                f"第 {seen[segment_id] + 1} 与第 {index + 1} 个时间段输出 ID 重复: {segment_id}"
            )
        seen[segment_id] = index
        plan.append({
            "index": index,
            "s": start_ms,
            "e": end_ms,
            "speed": speed,
            "id": segment_id,
        })
    return plan


@dataclass(frozen=True)
class ChartExportOperation:
    difficulty: DifficultyDefinition
    source_path: Path
    output_filename: str


@dataclass(frozen=True)
class MultiDifficultySegmentExportPlan:
    segment: dict
    audio_output_filename: str
    chart_operations: tuple[ChartExportOperation, ...]


@dataclass(frozen=True)
class MultiDifficultyExportPlan:
    selected_difficulties: tuple[int, ...]
    segments: tuple[MultiDifficultySegmentExportPlan, ...]

    @property
    def audio_operation_count(self) -> int:
        return len(self.segments)

    @property
    def chart_operation_count(self) -> int:
        return sum(len(item.chart_operations) for item in self.segments)


def build_multi_difficulty_export_plan(
    source_dir: Path,
    source_id: str,
    segments: list[dict],
    default_speed: float,
    selected_difficulties,
) -> MultiDifficultyExportPlan:
    """Build the V2.5-B operation order without invoking ffmpeg or writing output."""
    source_dir = Path(source_dir)
    discovery = discover_song_difficulties(source_dir)
    validation = validate_selected_difficulties(selected_difficulties, discovery.available)
    if validation.missing:
        names = "、".join(str(item) + ".aff" for item in validation.missing)
        raise ValueError(f"选中的难度文件不存在: {names}")

    definitions = tuple(
        item for item in discovery.available if item.rating_class in validation.selected
    )
    segment_plan = build_segment_export_plan(source_id, segments, default_speed)
    return MultiDifficultyExportPlan(
        selected_difficulties=validation.selected,
        segments=tuple(
            MultiDifficultySegmentExportPlan(
                segment=dict(item),
                audio_output_filename="base.ogg",
                chart_operations=tuple(
                    ChartExportOperation(definition, source_dir / definition.aff_filename, definition.aff_filename)
                    for definition in definitions
                ),
            )
            for item in segment_plan
        ),
    )


def copy_song_jackets(source_dir: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in JACKET_FILENAMES:
        src = Path(source_dir) / name
        if src.is_file():
            dest = Path(out_dir) / name
            shutil.copy2(src, dest)
            copied.append(dest)
    return copied


def current_export_root(out_dir: Path | None = None) -> Path:
    return Path(out_dir or OUT_DIR) / "current_export"


def current_export_songs_dir(out_dir: Path | None = None) -> Path:
    return current_export_root(out_dir) / "songs"


def library_export_root(out_dir: Path | None = None) -> Path:
    return Path(out_dir or OUT_DIR) / "library_export"


def library_export_songs_dir(out_dir: Path | None = None) -> Path:
    return library_export_root(out_dir) / "songs"


def create_current_export_stage(out_dir: Path | None = None) -> Path:
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        stage = out_dir / f".current_export_staging_{uuid.uuid4().hex}"
        try:
            (stage / "songs").mkdir(parents=True)
            return stage
        except FileExistsError:
            continue
    raise RuntimeError("无法创建 current_export staging 目录")


def _resolved(path: Path) -> Path:
    return Path(path).resolve(strict=False)


def _is_direct_child(child: Path, parent: Path) -> bool:
    return _resolved(child).parent == _resolved(parent)


def _path_is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(getattr(os.path, "isjunction", lambda _p: False)(path))
    except OSError:
        return False


def _assert_safe_current_export_path(path: Path, out_dir: Path) -> None:
    path = Path(path)
    out_dir = Path(out_dir)
    expected = current_export_root(out_dir)
    if _resolved(path) != _resolved(expected):
        raise RuntimeError(f"拒绝操作非 current_export 路径: {path}")
    if _resolved(path) in {_resolved(out_dir), _resolved(DATA_ROOT), _resolved(library_export_root(out_dir))}:
        raise RuntimeError(f"拒绝操作危险路径: {path}")


def _assert_safe_stage_path(stage_root: Path, out_dir: Path) -> None:
    stage_root = Path(stage_root)
    out_dir = Path(out_dir)
    if not _is_direct_child(stage_root, out_dir):
        raise RuntimeError(f"staging 目录必须位于 OUT_DIR 下: {stage_root}")
    if not stage_root.name.startswith(".current_export_staging_"):
        raise RuntimeError(f"非法 staging 目录名: {stage_root.name}")
    if _resolved(stage_root) in {
        _resolved(out_dir),
        _resolved(current_export_root(out_dir)),
        _resolved(library_export_root(out_dir)),
        _resolved(DATA_ROOT),
    }:
        raise RuntimeError(f"拒绝操作危险 staging 路径: {stage_root}")


def cleanup_current_export_stage(stage_root: Path, out_dir: Path | None = None) -> None:
    out_dir = Path(out_dir or OUT_DIR)
    _assert_safe_stage_path(stage_root, out_dir)
    stage_root = Path(stage_root)
    if stage_root.exists():
        if _path_is_link_or_junction(stage_root):
            raise RuntimeError(f"拒绝删除链接 staging 目录: {stage_root}")
        shutil.rmtree(stage_root)


def publish_current_export_stage(
    stage_root: Path,
    out_dir: Path | None = None,
    rename_fn=None,
    rmtree_fn=shutil.rmtree,
) -> None:
    out_dir = Path(out_dir or OUT_DIR)
    stage_root = Path(stage_root)
    current = current_export_root(out_dir)
    backup = out_dir / f".current_export_backup_{uuid.uuid4().hex}"
    rename_fn = rename_fn or (lambda src, dest: Path(src).rename(dest))

    _assert_safe_stage_path(stage_root, out_dir)
    _assert_safe_current_export_path(current, out_dir)
    if not stage_root.is_dir():
        raise RuntimeError(f"staging 目录不存在: {stage_root}")
    if current.exists() and _path_is_link_or_junction(current):
        raise RuntimeError("current_export 是符号链接或 Junction，拒绝发布以避免误删目标")

    def move_dir(src: Path, dest: Path, allow_copy_fallback: bool = False) -> None:
        try:
            rename_fn(src, dest)
            return
        except Exception:
            if not allow_copy_fallback:
                raise
            if not Path(src).is_dir() or _path_is_link_or_junction(src):
                raise
            shutil.copytree(src, dest)
            rmtree_fn(src)

    def restore_backup() -> None:
        if not backup.exists() or current.exists():
            return
        try:
            rename_fn(backup, current)
        except Exception:
            shutil.copytree(backup, current)
            rmtree_fn(backup)

    moved_old = False
    published = False
    try:
        if current.exists():
            move_dir(current, backup, allow_copy_fallback=True)
            moved_old = True
        move_dir(stage_root, current, allow_copy_fallback=True)
        published = True
        if backup.exists():
            rmtree_fn(backup)
    except Exception as ex:
        if moved_old and not published and current.exists():
            try:
                if current.is_dir() and not _path_is_link_or_junction(current):
                    rmtree_fn(current)
            except Exception:
                pass
        if moved_old and backup.exists() and not current.exists():
            try:
                restore_backup()
            except Exception:
                pass
        if not moved_old and backup.exists():
            try:
                rmtree_fn(backup)
            except Exception:
                pass
        if stage_root.exists() and stage_root.name.startswith(".current_export_staging_"):
            try:
                if not _path_is_link_or_junction(stage_root):
                    rmtree_fn(stage_root)
            except Exception:
                pass
        raise RuntimeError(f"发布 current_export 失败: {ex}") from ex


def make_songlist_fragment(
    new_id: str,
    start_ms: int,
    end_ms: int,
    speed: float,
    template_path: Path = SONGLIST_EXAMPLE_PATH,
) -> dict | None:
    """旧兼容函数：V2.1 正式导出流程不再调用 songlist_fragment.json 路径。"""
    template_path = Path(template_path)
    if not template_path.exists():
        return None
    try:
        songs = json.loads(template_path.read_text(encoding="utf-8")).get("songs", [])
        if not songs or not isinstance(songs[0], dict):
            return None
        out = json.loads(json.dumps(songs[0], ensure_ascii=False))
    except Exception:
        return None

    out["id"]  = new_id
    h = hashlib.sha1(new_id.encode()).digest()
    out["idx"] = int.from_bytes(h[:4], "big", signed=False) & 0x7FFFFFFF

    tl = out.get("title_localized")
    title_en = str(tl.get("en", "")) if isinstance(tl, dict) else ""
    out["title_localized"] = {"en": f"{title_en} [{start_ms}-{end_ms}]".strip()}
    out.pop("search_title", None)
    out.pop("search_artist", None)

    clip_ms = int(round((end_ms - start_ms) / speed))
    out["audioPreview"]    = 0
    out["audioPreviewEnd"] = min(30000, max(0, clip_ms))

    if speed != 1.0:
        for k in ("bpm_base", "baseBpm", "base_bpm"):
            if k in out and isinstance(out[k], (int, float)):
                out[k] = round(out[k] * speed, 2)
        if "bpm" in out and isinstance(out["bpm"], str):
            out["bpm"] = _scale_bpm_string(out["bpm"], speed)
    return {"songs": [out]}


def song_template_from_form(data: dict) -> SongTemplate:
    if not isinstance(data, dict):
        raise ValueError("Songlist 表单无效")
    try:
        return SongTemplate(
            title_base=str(data.get("title_base", "")).strip(),
            artist=str(data.get("artist", "")).strip(),
            bpm=str(data.get("bpm", "")).strip(),
            bpm_base=float(data.get("bpm_base", 0) or 0),
            set=str(data.get("set", "")).strip() or "single",
            purchase=str(data.get("purchase", "")).strip(),
            side=int(data.get("side", 0) or 0),
            bg=str(data.get("bg", "")).strip(),
            version=str(data.get("version", "")).strip(),
            chart_designer=str(data.get("chart_designer", "")).strip(),
            jacket_designer=str(data.get("jacket_designer", "")).strip(),
            rating=int(data.get("rating", 9) or 9),
            rating_plus=bool(data.get("rating_plus", False)),
        )
    except (TypeError, ValueError) as ex:
        raise ValueError(f"Songlist 表单字段格式无效: {ex}") from ex


def _song_meta_value(meta, key: str):
    if hasattr(meta, key):
        return getattr(meta, key)
    return meta[key]


def build_ftr_compat_difficulties(meta) -> list[dict]:
    chart_designer = _song_meta_value(meta, "chart_designer")
    jacket_designer = _song_meta_value(meta, "jacket_designer")
    rating = int(_song_meta_value(meta, "rating"))
    rating_plus = bool(_song_meta_value(meta, "rating_plus"))
    return [
        {
            "ratingClass": 0,
            "chartDesigner": chart_designer,
            "jacketDesigner": jacket_designer,
            "rating": -1,
            "ratingPlus": False,
        },
        {
            "ratingClass": 1,
            "chartDesigner": chart_designer,
            "jacketDesigner": jacket_designer,
            "rating": -1,
            "ratingPlus": False,
        },
        {
            "ratingClass": 2,
            "chartDesigner": chart_designer,
            "jacketDesigner": jacket_designer,
            "rating": rating,
            "ratingPlus": rating_plus,
        },
    ]


def build_songlist_entry(
    template: SongTemplate,
    segment_id: str,
    display_title: str,
    start_ms: int,
    end_ms: int,
    speed: float,
) -> dict:
    validate_speed_value(speed)
    clip_ms = int(round((end_ms - start_ms) / speed))
    bpm_base = round(template.bpm_base * speed, 2) if abs(speed - 1.0) > 1e-9 else template.bpm_base
    bpm = _scale_bpm_string(template.bpm, speed) if abs(speed - 1.0) > 1e-9 else template.bpm
    return {
        "id": segment_id,
        "title_localized": {"en": display_title},
        "artist": template.artist,
        "bpm": bpm,
        "bpm_base": bpm_base,
        "set": template.set or "single",
        "purchase": template.purchase,
        "audioPreview": 0,
        "audioPreviewEnd": min(30000, max(0, clip_ms)),
        "side": int(template.side),
        "bg": template.bg,
        "date": int(time.time()),
        "version": template.version,
        "difficulties": build_ftr_compat_difficulties(template),
    }


def build_songlist_document(entries: list[dict]) -> dict:
    return {"songs": list(entries)}


def effective_packlist_export_enabled(packlist_enabled: bool, songlist_enabled: bool) -> bool:
    return bool(packlist_enabled and songlist_enabled)


def default_pack_img_name(pack_id: str) -> str:
    return f"select_{pack_id}.png"


def normalize_pack_section(value) -> str:
    raw = str(value or "").strip()
    if raw in PACK_SECTION_OPTIONS:
        return raw
    return PACK_DEFAULT_SECTION


def pack_description_placeholder(pack_id: str) -> str:
    pack_id = str(pack_id or "").strip()
    if pack_id:
        return f"{pack_id} practice clips generated by Arc Slicer."
    return "Practice clips generated by Arc Slicer."


def default_pack_form_for_song(source_id: str) -> dict:
    source_id = str(source_id or "").strip()
    return {
        "pack_id": source_id,
        "pack_name": source_id,
        "pack_description": "",
        "pack_section": PACK_DEFAULT_SECTION,
        "pack_img": default_pack_img_name(source_id) if source_id else "",
        "pack_cover_source": "auto",
        "pack_cover_path": "",
    }


def _safe_pack_img_filename(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("pack img 文件名不能为空")
    if Path(name).name != name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("pack img 必须是安全的单一文件名")
    if Path(name).drive:
        raise ValueError("pack img 不得包含盘符")
    if Path(name).suffix.lower() != ".png":
        raise ValueError("pack img 必须以 .png 结尾")
    return name


def pack_template_from_form(data: dict, source_id: str) -> PackTemplate:
    if not isinstance(data, dict):
        raise ValueError("Packlist 表单无效")
    defaults = default_pack_form_for_song(source_id)
    pack_id = str(data.get("pack_id") or defaults["pack_id"]).strip()
    if not pack_id:
        raise ValueError("pack_id 不能为空")
    if not PACK_ID_RE.fullmatch(pack_id):
        raise ValueError("pack_id 仅允许 ASCII 字母、数字、下划线、连字符")

    img = _safe_pack_img_filename(data.get("pack_img") or default_pack_img_name(pack_id))
    cover_source = str(data.get("pack_cover_source") or "auto").strip().lower()
    if cover_source not in ("auto", "upload"):
        raise ValueError("曲包封面来源无效")
    cover_path = str(data.get("pack_cover_path") or "").strip()
    if cover_source == "upload":
        if not cover_path:
            raise ValueError("上传曲包封面路径不能为空")
        src = Path(cover_path)
        if src.suffix.lower() not in PACK_COVER_UPLOAD_SUFFIXES:
            raise ValueError("上传曲包封面仅支持 PNG / JPG / JPEG")
        if not src.is_file():
            raise ValueError("上传曲包封面文件不存在")

    return PackTemplate(
        pack_id=pack_id,
        name=str(data.get("pack_name") or defaults["pack_name"]).strip(),
        description=str(data.get("pack_description", "")).strip(),
        section=normalize_pack_section(data.get("pack_section", defaults["pack_section"])),
        img=img,
        cover_source=cover_source,
        cover_path=cover_path,
    )


def build_packlist_entry(template: PackTemplate) -> dict:
    return {
        "id": template.pack_id,
        "section": template.section,
        "plus_character": -1,
        "name_localized": {"en": template.name},
        "description_localized": {"en": template.description},
        "img": template.img,
    }


def build_packlist_document(entries: list[dict]) -> dict:
    return {"packs": list(entries)}


def _load_packlist_document(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        raise ValueError(f"无法读取 packlist JSON: {ex}") from ex
    if not isinstance(data, dict) or not isinstance(data.get("packs"), list):
        raise ValueError("packlist 顶层必须为 {\"packs\": [...]}")
    for item in data["packs"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("packlist 中每个条目必须包含非空字符串 id")
        if "img" in item:
            _safe_pack_img_filename(str(item["img"]))
    return data


def merge_packlist_entries(existing_entries: list[dict], new_entries: list[dict]) -> list[dict]:
    new_by_id: dict[str, dict] = {}
    new_order: list[str] = []
    for entry in new_entries:
        pack_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(pack_id, str) or not pack_id:
            raise ValueError("本次 packlist 条目缺少有效 id")
        if pack_id not in new_by_id:
            new_order.append(pack_id)
        new_by_id[pack_id] = entry

    merged: list[dict] = []
    seen: set[str] = set()
    for entry in existing_entries:
        pack_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(pack_id, str) or not pack_id or pack_id in seen:
            continue
        merged.append(new_by_id.get(pack_id, entry))
        seen.add(pack_id)

    for pack_id in new_order:
        if pack_id not in seen:
            merged.append(new_by_id[pack_id])
            seen.add(pack_id)
    return merged


def _select_auto_pack_cover_source(source_dir: Path) -> Path | None:
    for name in JACKET_FILENAMES:
        candidate = Path(source_dir) / name
        if candidate.is_file():
            return candidate
    return None


def _cover_crop_geometry(src_w: int, src_h: int, target_w: int = PACK_COVER_SIZE[0], target_h: int = PACK_COVER_SIZE[1]) -> tuple[int, int, int, int]:
    if src_w <= 0 or src_h <= 0:
        raise ValueError("图片尺寸无效")
    scale = max(target_w / src_w, target_h / src_h)
    scaled_w = max(target_w, int(math.ceil(src_w * scale)))
    scaled_h = max(target_h, int(math.ceil(src_h * scale)))
    x = max(0, (scaled_w - target_w) // 2)
    y = max(0, (scaled_h - target_h) // 2)
    return scaled_w, scaled_h, x, y


def render_pack_cover(source_path: Path, out_path: Path, log_fn=None) -> None:
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QImageReader

    source_path = Path(source_path)
    out_path = Path(out_path)
    reader = QImageReader(str(source_path))
    image = reader.read()
    if image.isNull():
        raise RuntimeError(f"曲包封面图片不可读: {source_path}")
    target_w, target_h = PACK_COVER_SIZE
    if (image.width() < target_w or image.height() < target_h) and log_fn:
        log_fn("  曲包封面源图可能清晰度不足。", "muted")
    scaled = image.scaled(
        target_w,
        target_h,
        _Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        _Qt.TransformationMode.SmoothTransformation,
    )
    crop_x = max(0, (scaled.width() - target_w) // 2)
    crop_y = max(0, (scaled.height() - target_h) // 2)
    cropped = scaled.copy(crop_x, crop_y, target_w, target_h)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not cropped.save(str(out_path), "PNG"):
        raise RuntimeError(f"曲包封面写入失败: {out_path}")


def write_pack_resources_to_stage(
    source_song_dir: Path,
    stage_songs_dir: Path,
    template: PackTemplate,
    log_fn=None,
    cover_renderer=None,
) -> dict:
    cover_renderer = cover_renderer or render_pack_cover
    if template.cover_source == "upload":
        cover_source = Path(template.cover_path)
    else:
        cover_source = _select_auto_pack_cover_source(source_song_dir)
        if cover_source is None:
            raise RuntimeError("找不到可用于生成曲包封面的歌曲曲绘")

    pack_dir = Path(stage_songs_dir) / "pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    cover_renderer(cover_source, pack_dir / template.img, log_fn)
    entry = build_packlist_entry(template)
    (Path(stage_songs_dir) / "packlist").write_text(
        json.dumps(build_packlist_document([entry]), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return entry


def _bool_pref(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in ("true", "1", "yes", "on"):
            return True
        if raw in ("false", "0", "no", "off"):
            return False
    return default


def effective_library_export_enabled(library_export_enabled: bool, songlist_enabled: bool) -> bool:
    return bool(library_export_enabled and songlist_enabled)


def _load_songlist_document(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        raise ValueError(f"无法读取 songlist JSON: {ex}") from ex
    if not isinstance(data, dict) or not isinstance(data.get("songs"), list):
        raise ValueError("songlist 顶层必须为 {\"songs\": [...]}")
    for item in data["songs"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("songlist 中每个条目必须包含非空字符串 id")
    return data


def merge_songlist_entries(existing_entries: list[dict], new_entries: list[dict]) -> list[dict]:
    new_by_id: dict[str, dict] = {}
    new_order: list[str] = []
    for entry in new_entries:
        song_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(song_id, str) or not song_id:
            raise ValueError("本次 songlist 条目缺少有效 id")
        if song_id not in new_by_id:
            new_order.append(song_id)
        new_by_id[song_id] = entry

    merged: list[dict] = []
    seen: set[str] = set()
    for entry in existing_entries:
        song_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(song_id, str) or not song_id or song_id in seen:
            continue
        if song_id in new_by_id:
            merged.append(new_by_id[song_id])
        else:
            merged.append(entry)
        seen.add(song_id)

    for song_id in new_order:
        if song_id not in seen:
            merged.append(new_by_id[song_id])
            seen.add(song_id)
    return merged


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp_{uuid.uuid4().hex}"
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _files_identical(a: Path, b: Path) -> bool:
    if not Path(a).is_file() or not Path(b).is_file():
        return False
    return hashlib.sha256(Path(a).read_bytes()).digest() == hashlib.sha256(Path(b).read_bytes()).digest()


def _backup_file(path: Path, backup: Path) -> bool:
    had_file = path.exists()
    if had_file:
        if path.is_dir() or _path_is_link_or_junction(path):
            raise RuntimeError(f"拒绝替换非普通文件: {path}")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    return had_file


def _restore_file_backup(path: Path, backup: Path, had_file: bool) -> None:
    if path.exists():
        if path.is_dir() or _path_is_link_or_junction(path):
            return
        path.unlink()
    if had_file and backup.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, path)
        backup.unlink()


def _copy_replace_dir_with_backup(src: Path, target: Path, backup: Path) -> bool:
    had_target = target.exists()
    if had_target:
        if _path_is_link_or_junction(target):
            raise RuntimeError(f"目标歌曲目录是符号链接或 Junction，拒绝替换: {target}")
        try:
            target.rename(backup)
        except Exception:
            shutil.copytree(target, backup)
            shutil.rmtree(target)
    shutil.copytree(src, target)
    return had_target


def _restore_dir_backup(target: Path, backup: Path, had_target: bool) -> None:
    if target.exists() and not _path_is_link_or_junction(target):
        shutil.rmtree(target)
    if had_target and backup.exists():
        try:
            backup.rename(target)
        except Exception:
            shutil.copytree(backup, target)
            shutil.rmtree(backup)


def merge_staging_into_library_export(
    stage_root: Path,
    out_dir: Path | None = None,
    fail_after_dirs: bool = False,
) -> None:
    out_dir = Path(out_dir or OUT_DIR)
    stage_root = Path(stage_root)
    staging_songs = stage_root / "songs"
    staging_songlist = staging_songs / "songlist"
    staging_packlist = staging_songs / "packlist"
    staging_pack_dir = staging_songs / "pack"
    if not staging_songlist.is_file():
        raise RuntimeError("更新总导出包需要 staging/songs/songlist")

    staging_doc = _load_songlist_document(staging_songlist)
    new_entries = staging_doc["songs"]
    song_ids = [entry["id"] for entry in new_entries]
    if len(song_ids) != len(set(song_ids)):
        raise RuntimeError("本次 songlist 含有重复 id，拒绝更新总导出包")

    for song_id in song_ids:
        src_dir = staging_songs / song_id
        if not src_dir.is_dir():
            raise RuntimeError(f"staging 缺少歌曲目录: {song_id}")

    library_songs = library_export_songs_dir(out_dir)
    library_songlist = library_songs / "songlist"
    library_packlist = library_songs / "packlist"
    library_pack_dir = library_songs / "pack"
    existing_entries: list[dict] = []
    if library_songlist.exists():
        existing_entries = _load_songlist_document(library_songlist)["songs"]

    has_packlist = staging_packlist.is_file()
    new_pack_entries: list[dict] = []
    merged_pack_doc: dict | None = None
    pack_images: list[tuple[str, str]] = []
    if has_packlist:
        staging_pack_doc = _load_packlist_document(staging_packlist)
        new_pack_entries = staging_pack_doc["packs"]
        pack_ids = [entry["id"] for entry in new_pack_entries]
        if len(pack_ids) != len(set(pack_ids)):
            raise RuntimeError("本次 packlist 含有重复 id，拒绝更新总导出包")
        existing_pack_entries: list[dict] = []
        if library_packlist.exists():
            existing_pack_entries = _load_packlist_document(library_packlist)["packs"]
        merged_pack_doc = build_packlist_document(merge_packlist_entries(existing_pack_entries, new_pack_entries))

        existing_img_owner: dict[str, str] = {}
        for entry in existing_pack_entries:
            img = entry.get("img")
            pack_id = entry.get("id")
            if isinstance(img, str) and isinstance(pack_id, str):
                existing_img_owner.setdefault(img, pack_id)

        for entry in new_pack_entries:
            img = _safe_pack_img_filename(entry.get("img", ""))
            pack_id = entry["id"]
            src_img = staging_pack_dir / img
            if not src_img.is_file():
                raise RuntimeError(f"staging 缺少曲包封面: {img}")
            target_img = library_pack_dir / img
            owner = existing_img_owner.get(img)
            if owner and owner != pack_id and target_img.exists() and not _files_identical(src_img, target_img):
                raise RuntimeError(f"曲包封面文件名冲突: {img} 已被 pack {owner} 使用")
            pack_images.append((pack_id, img))

    for song_id in song_ids:
        target_dir = library_songs / song_id
        if target_dir.exists() and _path_is_link_or_junction(target_dir):
            raise RuntimeError(f"目标歌曲目录是符号链接或 Junction，拒绝替换: {target_dir}")

    merged_doc = build_songlist_document(merge_songlist_entries(existing_entries, new_entries))
    library_songs.mkdir(parents=True, exist_ok=True)

    backups: list[tuple[Path, Path, bool]] = []
    file_backups: list[tuple[Path, Path, bool]] = []
    try:
        for path in (library_songlist, library_packlist if has_packlist else None):
            if path is None:
                continue
            backup = path.parent / f".{path.name}_backup_{uuid.uuid4().hex}"
            file_backups.append((path, backup, _backup_file(path, backup)))

        for song_id in song_ids:
            src_dir = staging_songs / song_id
            target_dir = library_songs / song_id
            backup = library_songs / f".{song_id}_backup_{uuid.uuid4().hex}"
            had_target = _copy_replace_dir_with_backup(src_dir, target_dir, backup)
            backups.append((target_dir, backup, had_target))

        if has_packlist:
            library_pack_dir.mkdir(parents=True, exist_ok=True)
            for _pack_id, img in pack_images:
                src_img = staging_pack_dir / img
                target_img = library_pack_dir / img
                backup = library_pack_dir / f".{img}_backup_{uuid.uuid4().hex}"
                file_backups.append((target_img, backup, _backup_file(target_img, backup)))
                shutil.copy2(src_img, target_img)

        if fail_after_dirs:
            raise RuntimeError("测试注入：歌曲目录替换后失败")

        _atomic_write_json(library_songlist, merged_doc)
        if has_packlist and merged_pack_doc is not None:
            _atomic_write_json(library_packlist, merged_pack_doc)
    except Exception:
        for target_dir, backup, had_target in reversed(backups):
            try:
                _restore_dir_backup(target_dir, backup, had_target)
            except Exception:
                pass
        for path, backup, had_file in reversed(file_backups):
            try:
                _restore_file_backup(path, backup, had_file)
            except Exception:
                pass
        raise
    else:
        for _target_dir, backup, _had_target in backups:
            if backup.exists() and not _path_is_link_or_junction(backup):
                shutil.rmtree(backup)
        for _path, backup, _had_file in file_backups:
            if backup.exists():
                try:
                    backup.unlink()
                except OSError:
                    pass


def make_songlist_entry(
    folder_name: str,
    seg_index: int,
    start_ms: int,
    end_ms: int,
    speed: float,
    meta: dict,
) -> dict:
    """根据用户填写的 meta 生成单段 songlist JSON（{"songs": [...]}）。"""
    clip_ms = int(round((end_ms - start_ms) / speed))
    bpm_base = round(meta["bpm_base"] * speed, 2) if abs(speed - 1.0) > 1e-9 else meta["bpm_base"]
    bpm = _scale_bpm_string(meta["bpm"], speed) if abs(speed - 1.0) > 1e-9 else meta["bpm"]
    title = f"{meta['title_base']} {seg_index + 1:02d}".strip()
    return {
        "songs": [{
            "id": folder_name,
            "title_localized": {"en": title},
            "artist": meta["artist"],
            "bpm": bpm,
            "bpm_base": bpm_base,
            "set": meta["set"] or "single",
            "purchase": meta["purchase"],
            "audioPreview": 0,
            "audioPreviewEnd": min(30000, max(0, clip_ms)),
            "side": int(meta["side"]),
            "bg": meta["bg"],
            "date": int(time.time()),
            "version": meta["version"],
            "difficulties": build_ftr_compat_difficulties(meta),
        }]
    }


def do_slice(
    songs_dir: Path,
    song_id: str,
    segments: list[dict],
    speed: float,
    log_fn,
    songlist_meta: dict | None = None,
    songlist_enabled: bool = False,
    song_template: SongTemplate | None = None,
    current_export_enabled: bool = True,
    library_export_enabled: bool = True,
    packlist_enabled: bool = False,
    pack_template: PackTemplate | None = None,
    *,
    ffmpeg_getter=default_get_ffmpeg,
    slice_ogg_fn=default_slice_ogg,
    slice_aff_fn=default_slice_aff,
    stage_creator=create_current_export_stage,
    stage_cleanup=cleanup_current_export_stage,
    stage_publisher=publish_current_export_stage,
    library_merger=merge_staging_into_library_export,
    cover_renderer=render_pack_cover,
) -> int:
    try:
        validate_speed_value(speed)
    except ValueError as ex:
        log_fn(f"✗ 速度无效: {ex}", "err")
        return 1

    try:
        ffp = ffmpeg_getter()
        log_fn(f"  ffmpeg: {ffp}", "muted")
    except RuntimeError as ex:
        log_fn(f"✗ {ex}", "err")
        return 1

    if songlist_enabled:
        if song_template is None:
            try:
                song_template = song_template_from_form(songlist_meta or {})
            except ValueError as ex:
                log_fn(f"✗ Songlist 信息无效: {ex}", "err")
                return 1

    effective_packlist = effective_packlist_export_enabled(packlist_enabled, songlist_enabled)
    if packlist_enabled and not songlist_enabled:
        log_fn("  生成 packlist 需要启用 songlist；本次不会输出 packlist。", "muted")

    effective_library = effective_library_export_enabled(library_export_enabled, songlist_enabled)
    if library_export_enabled and not songlist_enabled:
        log_fn("  更新总导出包需要启用 songlist；本次不会修改 library_export。", "muted")
    if not current_export_enabled and not effective_library:
        log_fn("✗ 至少需要选择一个有效导出目标。", "err")
        return 1

    in_dir = songs_dir / song_id
    in_aff, in_ogg = in_dir / "2.aff", in_dir / "base.ogg"

    for p in (in_aff, in_ogg):
        if not p.exists():
            log_fn(f"✗ 找不到文件: {p}", "err")
            return 1

    try:
        segment_plan = build_segment_export_plan(song_id, segments, speed)
    except ValueError as ex:
        log_fn(f"✗ {ex}", "err")
        return 1

    if effective_packlist:
        try:
            if pack_template is None:
                pack_template = pack_template_from_form(songlist_meta or {}, song_id)
            if song_template is not None:
                song_template = replace(song_template, set=pack_template.pack_id)
        except ValueError as ex:
            log_fn(f"✗ Packlist 信息无效: {ex}", "err")
            return 1

    try:
        stage_root = stage_creator()
    except RuntimeError as ex:
        log_fn(f"✗ {ex}", "err")
        return 1

    out_root = stage_root / "songs"
    all_song_entries: list[dict] = []

    try:
        for item in segment_plan:
            s, e = item["s"], item["e"]
            segment_speed = item["speed"]
            new_id = item["id"]
            out_dir  = out_root / new_id
            out_dir.mkdir(parents=True, exist_ok=True)

            copy_song_jackets(in_dir, out_dir)

            log_fn(f"  ♪ 音频 {s}ms – {e}ms  speed={segment_speed}…", "stage")
            try:
                slice_ogg_fn(in_ogg, out_dir / "base.ogg", s, e, segment_speed)
            except subprocess.CalledProcessError as ex:
                log_fn(f"✗ ffmpeg 失败: {ex}", "err")
                stage_cleanup(stage_root)
                return 1

            log_fn(f"  ✎ 谱面 {s}ms – {e}ms…", "stage")
            aff_warnings: list[str] = []
            new_aff = slice_aff_fn(in_aff.read_text(encoding="utf-8", errors="replace"), s, e, segment_speed, aff_warnings)
            for warning in aff_warnings:
                log_fn(f"  ⚠ {warning}", "warn")
            (out_dir / "2.aff").write_text(new_aff, encoding="utf-8")

            if songlist_enabled and song_template:
                display_title = build_segment_display_title(song_template.title_base or song_id, s, e, segment_speed)
                entry = build_songlist_entry(song_template, new_id, display_title, s, e, segment_speed)
                all_song_entries.append(entry)
                log_fn(f"  ✎ songlist → {new_id}", "stage")

            log_fn(f"✓ 输出 → out/current_export/songs/{new_id}/", "ok")

        if songlist_enabled:
            merged_path = out_root / "songlist"
            merged_path.write_text(
                json.dumps(build_songlist_document(all_song_entries), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log_fn(f"✓ 合并 songlist → out/current_export/songs/songlist（共 {len(all_song_entries)} 首）", "ok")

        if effective_packlist and pack_template:
            write_pack_resources_to_stage(in_dir, out_root, pack_template, log_fn, cover_renderer=cover_renderer)
            log_fn(f"✓ packlist → {pack_template.pack_id} ({pack_template.img})", "ok")

        library_ok = True
        if effective_library:
            try:
                library_merger(stage_root)
                log_fn("✓ 更新总导出包 → out/library_export/songs/", "ok")
            except Exception as ex:
                library_ok = False
                log_fn(f"✗ 更新总导出包失败: {ex}", "err")

        current_ok = True
        if current_export_enabled:
            try:
                stage_publisher(stage_root)
                log_fn("✓ 生成本次导出包 → out/current_export/songs/", "ok")
            except RuntimeError as ex:
                current_ok = False
                log_fn(f"✗ {ex}", "err")
        else:
            stage_cleanup(stage_root)
            log_fn("  本次导出包：未启用，已清理临时 staging。", "muted")

        if not library_ok or not current_ok:
            if current_ok and not library_ok:
                log_fn("⚠ 本次导出包已完成，但总导出包更新失败。", "err")
            elif library_ok and not current_ok:
                log_fn("⚠ 总导出包已完成，但本次导出包发布失败。", "err")
            return 1
    except Exception as ex:
        try:
            stage_cleanup(stage_root)
        except Exception as cleanup_ex:
            log_fn(f"✗ 清理 staging 失败: {cleanup_ex}", "err")
        log_fn(f"✗ 切片失败: {ex}", "err")
        return 1

    return 0
