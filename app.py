"""
Arc Slicer — PyQt6 独立桌面应用
切片逻辑全部内嵌；ffmpeg 打包；原生拖拽谱面文件夹；PyInstaller 单文件打包。
"""
from __future__ import annotations

import hashlib
import array
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
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QMimeData,
    QPoint, QRect, QEvent,
)
from PyQt6.QtGui import (
    QColor, QFont, QPalette, QPainter, QPainterPath, QPen, QLinearGradient,
    QDragEnterEvent, QDropEvent, QDragLeaveEvent, QMouseEvent,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
    QScrollArea, QFrame, QFileDialog, QSizePolicy, QSpacerItem,
    QCheckBox, QGridLayout, QGraphicsDropShadowEffect,
)
try:
    from PyQt6.QtWidgets import QScrollBar
except ImportError:  # Older headless tests install a small fake PyQt surface.
    QScrollBar = None

import external_merge

# ----- Extracted core modules -------------------------------------------------
from arc_slicer import aff as _aff_core
from arc_slicer import audio as _audio_core
from arc_slicer import waveform as _waveform_core
from arc_slicer.paths import (
    APP_DATA_DIRNAME, APP_DIR, BASE_DIR, RES_DIR, DATA_ROOT, DEFAULT_SONGS_DIR,
    OUT_DIR, CURRENT_EXPORT_ROOT, CURRENT_EXPORT_SONGS_DIR, LIBRARY_EXPORT_ROOT,
    LIBRARY_EXPORT_SONGS_DIR, EXTERNAL_MERGE_BACKUP_ROOT,
    EXTERNAL_MERGE_TARGET_CONFIG_KEY, WAVEFORM_CACHE_DIR, CONFIG_PATH,
    SLIDES_PATH, SONGLIST_EXAMPLE_PATH, _FFMPEG_BUNDLED,
    _app_dir, _res_dir, _data_root_for_app_dir, resolve_runtime_paths,
)
from arc_slicer.theme import (
    C_BG, C_CARD, C_CARD2, C_BORDER, C_BORDER2, C_ACCENT, C_ACCENT_H, C_TEXT,
    C_TEXT2, C_MUTED, C_LABEL, C_INPUT_BG, C_INPUT_BD, C_OK, C_ERR,
    C_BADGE_BG, C_WAVEFORM, C_TIMELINE_BG, C_TIMELINE_TRACK, C_LANE_SEPARATOR,
    C_SEGMENT_FILL, C_SEGMENT_ALT_FILL, C_SEGMENT_BORDER, C_SELECTED,
    C_HOVERED, C_DRAFT_START, C_DRAFT_END,
)
from arc_slicer.segments import (
    TIME_INPUT_PATTERN, SegmentValidationResult, effective_segment_speed,
    format_duration_ms, is_time_input_text_allowed, new_link_group_id,
    normalize_link_group_id, normalize_speed_override_value, normalize_speed_token,
    parse_duration_to_ms, parse_speed_text, validate_segment_bounds,
    validate_speed_value, _parse_non_negative_time_text,
)
from arc_slicer.aff import (
    AUDIO_OFFSET_WARNING, ARC_CUT_EASING_ORDER, CAMERA_SCENE_WARNING,
    NONLINEAR_ARC_EASINGS, arc_position_at, _arc_cut_info_content,
    _extract_header_and_body, _parse_outer_timings, _scale_bpm_string,
)
from arc_slicer.waveform import (
    DEFAULT_WAVEFORM_SAMPLES_PER_SECOND, WAVEFORM_CACHE_VERSION,
    WAVEFORM_DECODE_SAMPLE_RATE, WAVEFORM_HANDLE_PX, WAVEFORM_MIN_SEGMENT_MS,
    WaveformData, aggregate_pcm_waveform, read_waveform_cache,
    waveform_cache_key, waveform_cache_path, write_waveform_cache,
)
from arc_slicer.ui.metadata_panel import (
    CollapsibleHeader, DropZone, SonglistPanel, card_frame, field_label,
    make_label, metadata_field_label, section_title,
)
from arc_slicer.ui.segment_row import ArcCutIndicator, ArcCutInfoCard, ArcCutStatus, SegmentRow
from arc_slicer.ui.waveform_panel import WaveformPanel

_AUTO_SEGMENT = object()


def current_export_root(out_dir: Path | None = None) -> Path:
    return Path(out_dir or OUT_DIR) / "current_export"


def current_export_songs_dir(out_dir: Path | None = None) -> Path:
    return current_export_root(out_dir) / "songs"


def library_export_root(out_dir: Path | None = None) -> Path:
    return Path(out_dir or OUT_DIR) / "library_export"


def library_export_songs_dir(out_dir: Path | None = None) -> Path:
    return library_export_root(out_dir) / "songs"


def _get_ffmpeg() -> str:
    return _audio_core._get_ffmpeg()


def _get_ffprobe() -> str:
    return _audio_core._get_ffprobe()


def _subprocess_no_window_flag() -> int:
    return _audio_core._subprocess_no_window_flag()


def parse_ffmpeg_duration_to_ms(text: str) -> int:
    return _audio_core.parse_ffmpeg_duration_to_ms(text)


def _atempo(speed: float) -> str:
    return _audio_core._atempo(speed)


def probe_audio_duration_ms(audio_path: Path) -> int:
    return _audio_core.probe_audio_duration_ms(
        audio_path,
        ffprobe_getter=_get_ffprobe,
        ffmpeg_getter=_get_ffmpeg,
        run=subprocess.run,
    )


def slice_ogg(in_path: Path, out_path: Path, start_ms: int, end_ms: int, speed: float) -> None:
    return _audio_core.slice_ogg(
        in_path,
        out_path,
        start_ms,
        end_ms,
        speed,
        ffmpeg_getter=_get_ffmpeg,
        run=subprocess.run,
    )


def decode_audio_waveform(
    audio_path: Path,
    samples_per_second: int = DEFAULT_WAVEFORM_SAMPLES_PER_SECOND,
) -> WaveformData:
    return _waveform_core.decode_audio_waveform(
        audio_path,
        samples_per_second,
        ffmpeg_getter=_get_ffmpeg,
        run=subprocess.run,
    )


def load_or_generate_waveform(
    audio_path: Path,
    samples_per_second: int = DEFAULT_WAVEFORM_SAMPLES_PER_SECOND,
    cache_dir: Path | None = None,
) -> WaveformData:
    return _waveform_core.load_or_generate_waveform(
        audio_path,
        samples_per_second,
        cache_dir,
        ffmpeg_getter=_get_ffmpeg,
        run=subprocess.run,
    )


def find_nonlinear_arc_cut_warnings(aff_text: str, segments: list[dict]) -> dict[int, dict[str, list[dict]]]:
    return _aff_core.find_nonlinear_arc_cut_warnings(aff_text, segments)


def slice_aff(aff_text: str, start_ms: int, end_ms: int, speed: float, warnings: list[str] | None = None) -> str:
    return _aff_core.slice_aff(aff_text, start_ms, end_ms, speed, warnings)











def is_sliceable_song_dir(path: Path) -> bool:
    return path.is_dir() and (path / "base.ogg").is_file() and (path / "2.aff").is_file()

































































# ─── ffmpeg ───────────────────────────────────────────────────────────────────



TIME_INPUT_PATTERN = r"^-?\d*$"
_TIME_INPUT_RE = re.compile(r"^-?\d*$")
_FFMPEG_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")










































# ─── V2.1 导出路径底座 ───────────────────────────────────────────────────────

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


# ─── songlist ─────────────────────────────────────────────────────────────────

def make_songlist_fragment(new_id: str, start_ms: int, end_ms: int, speed: float) -> dict | None:
    """旧兼容函数：V2.1 正式导出流程不再调用 songlist_fragment.json 路径。"""
    if not SONGLIST_EXAMPLE_PATH.exists():
        return None
    try:
        songs = json.loads(SONGLIST_EXAMPLE_PATH.read_text(encoding="utf-8")).get("songs", [])
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


# ─── 核心切片 ─────────────────────────────────────────────────────────────────

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
) -> int:
    try:
        validate_speed_value(speed)
    except ValueError as ex:
        log_fn(f"✗ 速度无效: {ex}", "err")
        return 1

    try:
        ffp = _get_ffmpeg()
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
        stage_root = create_current_export_stage()
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
                slice_ogg(in_ogg, out_dir / "base.ogg", s, e, segment_speed)
            except subprocess.CalledProcessError as ex:
                log_fn(f"✗ ffmpeg 失败: {ex}", "err")
                cleanup_current_export_stage(stage_root)
                return 1

            log_fn(f"  ✎ 谱面 {s}ms – {e}ms…", "stage")
            aff_warnings: list[str] = []
            new_aff = slice_aff(in_aff.read_text(encoding="utf-8", errors="replace"), s, e, segment_speed, aff_warnings)
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
            write_pack_resources_to_stage(in_dir, out_root, pack_template, log_fn)
            log_fn(f"✓ packlist → {pack_template.pack_id} ({pack_template.img})", "ok")

        library_ok = True
        if effective_library:
            try:
                merge_staging_into_library_export(stage_root)
                log_fn("✓ 更新总导出包 → out/library_export/songs/", "ok")
            except Exception as ex:
                library_ok = False
                log_fn(f"✗ 更新总导出包失败: {ex}", "err")

        current_ok = True
        if current_export_enabled:
            try:
                publish_current_export_stage(stage_root)
                log_fn("✓ 生成本次导出包 → out/current_export/songs/", "ok")
            except RuntimeError as ex:
                current_ok = False
                log_fn(f"✗ {ex}", "err")
        else:
            cleanup_current_export_stage(stage_root)
            log_fn("  本次导出包：未启用，已清理临时 staging。", "muted")

        if not library_ok or not current_ok:
            if current_ok and not library_ok:
                log_fn("⚠ 本次导出包已完成，但总导出包更新失败。", "err")
            elif library_ok and not current_ok:
                log_fn("⚠ 总导出包已完成，但本次导出包发布失败。", "err")
            return 1
    except Exception as ex:
        try:
            cleanup_current_export_stage(stage_root)
        except Exception as cleanup_ex:
            log_fn(f"✗ 清理 staging 失败: {cleanup_ex}", "err")
        log_fn(f"✗ 切片失败: {ex}", "err")
        return 1

    return 0


# ─── 运行数据迁移 / 配置 ─────────────────────────────────────────────────────

@dataclass
class MigrationReport:
    songs: int = 0
    out: bool = False
    config: bool = False
    slides: bool = False
    failures: list[str] = field(default_factory=list)

    def has_activity(self) -> bool:
        return bool(self.songs or self.out or self.config or self.slides or self.failures)

    def message(self) -> str:
        parts = []
        if self.songs:
            parts.append(f"songs {self.songs} 项")
        if self.out:
            parts.append("out 已迁移")
        if self.config:
            parts.append("config 已迁移")
        if self.slides:
            parts.append("slides 已迁移")
        if self.failures:
            parts.append(f"失败 {len(self.failures)} 项")
        return "已迁移运行数据至 ArcSlicerData：" + "，".join(parts) + "。"


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


def _norm_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _same_path(a: Path, b: Path) -> bool:
    return _norm_path(a) == _norm_path(b)


def _legacy_runtime_roots(app_dir: Path = APP_DIR, data_root: Path = DATA_ROOT) -> list[Path]:
    roots = []
    base = data_root.parent
    for candidate in (base, base / "dist", app_dir):
        if candidate != data_root and candidate not in roots:
            roots.append(candidate)
    return roots


def _rewrite_legacy_config_songs_dir(cfg: dict, legacy_roots: list[Path], new_songs_dir: Path) -> dict:
    if not isinstance(cfg, dict):
        return cfg
    current = cfg.get("songs_dir")
    if not isinstance(current, str) or not current:
        return cfg
    current_path = Path(current)
    for root in legacy_roots:
        if _same_path(current_path, root / "songs"):
            cfg = dict(cfg)
            cfg["songs_dir"] = str(new_songs_dir)
            return cfg
    return cfg


def _is_dir_link(path: Path, is_junction_fn=None) -> bool:
    if path.is_symlink():
        return True
    if is_junction_fn is None:
        is_junction_fn = getattr(os.path, "isjunction", lambda _p: False)
    try:
        return bool(is_junction_fn(path))
    except OSError:
        return False


def _create_dir_link(target: Path, link_path: Path) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
            check=True, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.symlink(target, link_path, target_is_directory=True)


def migrate_legacy_runtime_data(
    data_root: Path = DATA_ROOT,
    legacy_roots: list[Path] | None = None,
    copytree_fn=shutil.copytree,
    copy2_fn=shutil.copy2,
    link_fn=_create_dir_link,
    is_junction_fn=None,
) -> MigrationReport:
    data_root = Path(data_root)
    songs_target = data_root / "songs"
    out_target = data_root / "out"
    config_target = data_root / "config.json"
    slides_target = data_root / "slides.json"
    legacy_roots = legacy_roots or _legacy_runtime_roots(data_root=data_root)
    report = MigrationReport()

    data_root.mkdir(parents=True, exist_ok=True)

    for root in legacy_roots:
        root = Path(root)
        old_songs = root / "songs"
        if old_songs.is_dir() and not _same_path(old_songs, songs_target):
            songs_target.mkdir(parents=True, exist_ok=True)
            for item in old_songs.iterdir():
                dest = songs_target / item.name
                if dest.exists() or dest.is_symlink():
                    continue
                try:
                    if _is_dir_link(item, is_junction_fn):
                        link_fn(item.resolve(strict=False), dest)
                    elif item.is_dir():
                        copytree_fn(item, dest)
                    elif item.is_file():
                        copy2_fn(item, dest)
                    else:
                        continue
                    report.songs += 1
                except Exception as ex:
                    report.failures.append(f"songs/{item.name}: {ex}")

        old_out = root / "out"
        if old_out.is_dir() and not out_target.exists() and not _same_path(old_out, out_target):
            try:
                copytree_fn(old_out, out_target)
                report.out = True
            except Exception as ex:
                report.failures.append(f"out: {ex}")

        old_config = root / "config.json"
        if old_config.is_file() and not config_target.exists() and not _same_path(old_config, config_target):
            try:
                cfg = json.loads(old_config.read_text(encoding="utf-8"))
                cfg = _rewrite_legacy_config_songs_dir(cfg, legacy_roots, songs_target)
                config_target.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
                report.config = True
            except Exception as ex:
                report.failures.append(f"config.json: {ex}")

        old_slides = root / "slides.json"
        if old_slides.is_file() and not slides_target.exists() and not _same_path(old_slides, slides_target):
            try:
                copy2_fn(old_slides, slides_target)
                report.slides = True
            except Exception as ex:
                report.failures.append(f"slides.json: {ex}")

    return report


def prepare_runtime_data() -> MigrationReport:
    report = migrate_legacy_runtime_data()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DEFAULT_SONGS_DIR.mkdir(parents=True, exist_ok=True)
    return report


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"songs_dir": str(DEFAULT_SONGS_DIR)}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def import_song_folder(src: Path, songs_dir: Path) -> tuple[bool, str, str | None]:
    if not src.exists():
        return False, "目录不存在", None
    if not src.is_dir():
        return False, "请拖入歌曲文件夹，而不是单个文件。", None

    songs_dir.mkdir(parents=True, exist_ok=True)
    dest = songs_dir / src.name

    if dest.resolve() == src.resolve():
        return True, f"文件夹已在 songs 目录中: {src.name}", src.name
    if dest.exists():
        return True, f"songs 目录中已有同名文件夹: {src.name}", src.name

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dest), str(src)],
                check=True, capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.symlink(src, dest)
        return True, f"已添加 {src.name}（快捷方式）", src.name
    except Exception:
        try:
            shutil.copytree(src, dest)
            return True, f"已复制 {src.name}", src.name
        except Exception as ex:
            return False, f"添加失败: {ex}", None


# ─── Worker 线程 ──────────────────────────────────────────────────────────────

def external_merge_action_count(plan: external_merge.ExternalMergePlan | None) -> int:
    if plan is None:
        return 0
    return int(plan.summary.get("actions", 0))


def external_merge_backup_count(plan: external_merge.ExternalMergePlan | None) -> int:
    if plan is None or not plan.is_ready or external_merge_action_count(plan) <= 0:
        return 0
    count = 1
    if plan.pack_actions:
        count += 1
    count += sum(1 for action in plan.song_actions if action.operation == "update")
    count += sum(1 for action in plan.pack_image_actions if action.operation == "replace")
    return count


def external_merge_can_check(
    target_songs_dir: Path | str | None,
    *,
    busy: bool = False,
    slicing: bool = False,
) -> bool:
    return bool(target_songs_dir) and not busy and not slicing


def external_merge_can_confirm(
    plan: external_merge.ExternalMergePlan | None,
    *,
    busy: bool = False,
) -> bool:
    return bool(plan and plan.is_ready and external_merge_action_count(plan) > 0 and not busy)


def _external_merge_target_status(value: object) -> tuple[Path | None, str]:
    if not isinstance(value, str) or not value.strip():
        return None, "上次目标目录不可用，请重新选择。"
    path = Path(value).expanduser()
    try:
        if not path.exists():
            return None, "上次目标目录不可用，请重新选择。"
        if not path.is_dir():
            return None, "上次目标目录不可用，请重新选择。"
        if _path_is_link_or_junction(path):
            return None, "上次目标目录不可用，请重新选择。"
    except OSError:
        return None, "上次目标目录不可用，请重新选择。"

    resolved = _resolved(path)
    if resolved in {_resolved(CURRENT_EXPORT_SONGS_DIR), _resolved(LIBRARY_EXPORT_SONGS_DIR)}:
        return None, "上次目标目录不可用，请重新选择。"
    return path.absolute(), ""


def external_merge_dirty_view_model(
    target_songs_dir: Path | str | None = None,
    *,
    backup_root: Path = EXTERNAL_MERGE_BACKUP_ROOT,
    extra_message: str = "",
) -> dict:
    target_text = str(target_songs_dir) if target_songs_dir else "未选择"
    detail = (
        "⚠ 当前配置尚未导出，请先运行切片。\n"
        "导出成功后可检查合并计划。\n"
        f"目标壳 songs 目录: {target_text}\n"
        f"备份根目录: {backup_root}"
    )
    if extra_message:
        detail += f"\n{extra_message}"
    return {
        "state": "dirty",
        "ready": False,
        "can_confirm": False,
        "title": "外部目标壳合并：需要先运行切片",
        "detail": detail,
    }


def _external_merge_issue_lines(label: str, issues: list[external_merge.MergeIssue]) -> list[str]:
    if not issues:
        return []
    lines = [f"{label}:"]
    for issue in issues:
        path_text = f" ({'; '.join(issue.paths)})" if issue.paths else ""
        lines.append(f"- {issue.code}: {issue.message}{path_text}")
    return lines


def external_merge_plan_view_model(
    plan: external_merge.ExternalMergePlan | None,
    *,
    target_songs_dir: Path | str | None = None,
    backup_root: Path = EXTERNAL_MERGE_BACKUP_ROOT,
) -> dict:
    if plan is None:
        target_text = str(target_songs_dir) if target_songs_dir else "未选择"
        return {
            "state": "unchecked" if target_songs_dir else "no_target",
            "ready": False,
            "can_confirm": False,
            "title": "外部目标壳合并：未检查",
            "detail": f"目标壳 songs 目录: {target_text}\n请先选择目标并检查合并计划。",
        }

    summary = plan.summary
    lines = [
        f"来源: {plan.current_songs_dir}",
        f"目标: {plan.target_songs_dir}",
        f"备份根目录: {backup_root}",
        (
            "变更: "
            f"歌曲新增 {summary.get('song_add', 0)} / 更新 {summary.get('song_update', 0)}; "
            f"曲包新增 {summary.get('pack_add', 0)} / 更新 {summary.get('pack_update', 0)}; "
            f"曲包图新增 {summary.get('pack_image_add', 0)} / 复用 {summary.get('pack_image_reuse', 0)} / 替换 {summary.get('pack_image_replace', 0)}"
        ),
        f"预计备份项: {external_merge_backup_count(plan)}",
    ]
    lines.extend(_external_merge_issue_lines("阻止项", plan.blockers))
    lines.extend(_external_merge_issue_lines("警告", plan.warnings))

    actions = external_merge_action_count(plan)
    if plan.blockers:
        title = "外部目标壳合并：不可执行"
        state = "blocked"
    elif actions <= 0:
        title = "外部目标壳合并：无差异"
        state = "empty"
        lines.append("当前导出包与目标壳没有需要写入的差异。")
    else:
        title = "外部目标壳合并：计划就绪"
        state = "ready"
    return {
        "state": state,
        "ready": plan.is_ready,
        "can_confirm": external_merge_can_confirm(plan),
        "title": title,
        "detail": "\n".join(lines),
        "summary": dict(summary),
        "backup_count": external_merge_backup_count(plan),
    }


def external_merge_result_view_model(result: external_merge.ExternalMergeResult) -> dict:
    backup_text = str(result.backup_dir) if result.backup_dir else "未创建"
    lines = [
        f"状态: {result.status}",
        f"变更路径数: {len(result.changed_paths)}",
        f"备份目录: {backup_text}",
    ]
    if result.status == "failed_rollback_incomplete":
        lines.insert(0, "合并失败，且自动恢复不完整。")
        lines.insert(1, "请立即停止继续操作目标壳。")
        lines.insert(2, f"请保留并检查以下备份目录: {backup_text}")
    if result.message:
        lines.append(result.message)
    if result.execution_issues:
        lines.extend(_external_merge_issue_lines("执行问题", result.execution_issues))
    if result.rollback_errors:
        lines.append("回滚问题:")
        lines.extend(f"- {item}" for item in result.rollback_errors)

    completed_title = (
        "外部目标壳合并：合并完成，但备份记录存在提示"
        if result.status == "completed" and result.execution_issues
        else "外部目标壳合并：合并完成"
    )
    titles = {
        "completed": completed_title,
        "stale_plan": "外部目标壳合并：计划已过期",
        "rejected": "外部目标壳合并：已拒绝",
        "failed_rolled_back": "外部目标壳合并：失败，已恢复",
        "failed_rollback_incomplete": "外部目标壳合并：恢复不完整，请立即停止继续操作目标壳",
    }
    return {
        "state": result.status,
        "title": titles.get(result.status, "外部目标壳合并：执行结束"),
        "detail": "\n".join(lines),
        "can_confirm": False,
    }


def external_merge_confirmation_text(
    plan: external_merge.ExternalMergePlan,
    backup_root: Path = EXTERNAL_MERGE_BACKUP_ROOT,
) -> str:
    summary = plan.summary
    return (
        "即将把 current_export/songs 合并到外部目标壳 songs 目录。\n\n"
        f"目标: {plan.target_songs_dir}\n"
        f"歌曲新增 {summary.get('song_add', 0)} / 更新 {summary.get('song_update', 0)}\n"
        f"曲包新增 {summary.get('pack_add', 0)} / 更新 {summary.get('pack_update', 0)}\n"
        f"曲包图新增 {summary.get('pack_image_add', 0)} / 复用 {summary.get('pack_image_reuse', 0)} / 替换 {summary.get('pack_image_replace', 0)}\n"
        f"预计备份项: {external_merge_backup_count(plan)}\n"
        f"备份根目录: {backup_root}\n\n"
        "此操作会修改目标 songs 目录。\n"
        "执行时会在备份根目录下创建一个时间戳子目录。\n"
        "工具会先备份受影响项目；无关资源不会被主动清理。\n"
        "请确认目标是测试壳副本。"
    )


def external_merge_log_line(result: external_merge.ExternalMergeResult) -> tuple[str, str]:
    backup_text = str(result.backup_dir) if result.backup_dir else "未创建"
    if result.status == "completed":
        return (
            f"[外部合并] 完成：修改 {len(result.changed_paths)} 项；备份：{backup_text}",
            "ok" if not result.execution_issues else "muted",
        )
    if result.status == "stale_plan":
        return ("[外部合并] 未执行：检查后内容发生变化，请重新检查。", "muted")
    if result.status == "failed_rolled_back":
        return (f"[外部合并] 失败，但已自动恢复；备份：{backup_text}", "err")
    if result.status == "failed_rollback_incomplete":
        return (f"[外部合并] 恢复不完整，请立即停止继续操作目标壳；备份：{backup_text}", "err")
    return (f"[外部合并] 未执行：{result.status}", "err")


class ExternalMergeWorker(QThread):
    done_signal = pyqtSignal(str, int, object, str)

    def __init__(
        self,
        mode: str,
        generation: int,
        current_songs_dir: Path,
        target_songs_dir: Path,
        backup_root: Path | None = None,
        plan: external_merge.ExternalMergePlan | None = None,
    ):
        super().__init__()
        self.mode = mode
        self.generation = int(generation)
        self.current_songs_dir = Path(current_songs_dir)
        self.target_songs_dir = Path(target_songs_dir)
        self.backup_root = Path(backup_root or EXTERNAL_MERGE_BACKUP_ROOT)
        self.plan = plan

    def run(self):
        try:
            if self.mode == "check":
                payload = external_merge.build_external_merge_plan(self.current_songs_dir, self.target_songs_dir)
            elif self.mode == "execute":
                if self.plan is None:
                    raise RuntimeError("missing external merge plan")
                payload = external_merge.execute_external_merge(self.plan, backup_root=self.backup_root)
            else:
                raise RuntimeError(f"unknown external merge worker mode: {self.mode}")
            self.done_signal.emit(self.mode, self.generation, payload, "")
        except Exception as ex:
            self.done_signal.emit(self.mode, self.generation, None, str(ex))


class WaveformWorker(QThread):
    done_signal = pyqtSignal(int, str, object, str)

    def __init__(
        self,
        generation: int,
        audio_path: Path,
        samples_per_second: int = DEFAULT_WAVEFORM_SAMPLES_PER_SECOND,
        cache_dir: Path | None = None,
    ):
        super().__init__()
        self.generation = int(generation)
        self.audio_path = Path(audio_path)
        self.samples_per_second = int(samples_per_second)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None

    def run(self):
        try:
            data = load_or_generate_waveform(
                self.audio_path,
                self.samples_per_second,
                self.cache_dir,
            )
            self.done_signal.emit(self.generation, str(self.audio_path), data, "")
        except Exception as ex:
            self.done_signal.emit(self.generation, str(self.audio_path), None, str(ex))


class SlicerWorker(QThread):
    log_signal  = pyqtSignal(str, str)  # text, kind
    done_signal = pyqtSignal(int)       # return code

    def __init__(
        self, songs_dir: Path, song_id: str, segments: list,
        speed: float, songlist_meta: dict | None = None,
        songlist_enabled: bool = False,
        song_template: SongTemplate | None = None,
        current_export_enabled: bool = True,
        library_export_enabled: bool = True,
        packlist_enabled: bool = False,
        pack_template: PackTemplate | None = None,
    ):
        super().__init__()
        self.songs_dir     = songs_dir
        self.song_id       = song_id
        self.segments      = segments
        self.speed         = speed
        self.songlist_meta = songlist_meta
        self.songlist_enabled = songlist_enabled
        self.song_template = song_template
        self.current_export_enabled = current_export_enabled
        self.library_export_enabled = library_export_enabled
        self.packlist_enabled = packlist_enabled
        self.pack_template = pack_template

    def run(self):
        def log(text, kind="normal"):
            self.log_signal.emit(text, kind)

        log(f"  songs 目录: {self.songs_dir}", "muted")
        log(f"  曲目: {self.song_id}  默认速度: {self.speed}  段数: {len(self.segments)}", "muted")
        if self.songlist_enabled:
            log("  songlist 生成: 开启", "muted")
        if effective_packlist_export_enabled(self.packlist_enabled, self.songlist_enabled):
            log("  packlist 生成: 开启", "muted")
        log(
            f"  导出目标: current={'开' if self.current_export_enabled else '关'} "
            f"library={'开' if effective_library_export_enabled(self.library_export_enabled, self.songlist_enabled) else '关'}",
            "muted",
        )
        code = do_slice(
            self.songs_dir, self.song_id, self.segments, self.speed, log,
            self.songlist_meta, self.songlist_enabled, self.song_template,
            self.current_export_enabled, self.library_export_enabled,
            self.packlist_enabled, self.pack_template,
        )
        if code == 0:
            log("✓ 全部完成！输出目录: out/current_export/songs/", "ok")
        self.done_signal.emit(code)


# ─── 样式表 ───────────────────────────────────────────────────────────────────

QSS = f"""
QWidget {{
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 14px;
    color: {C_TEXT};
}}
QMainWindow, #root {{
    background-color: {C_BG};
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #CBD5E1;
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QComboBox {{
    background: #FFFFFF;
    border: 1px solid {C_INPUT_BD};
    border-radius: 9px;
    padding: 9px 30px 9px 12px;
    font-size: 14px;
    font-weight: 500;
    min-width: 120px;
}}
QComboBox:focus {{
    border-color: {C_ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {C_LABEL};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background: #FFFFFF;
    border: 1px solid {C_INPUT_BD};
    border-radius: 8px;
    selection-background-color: {C_CARD2};
    selection-color: {C_TEXT};
    padding: 4px;
}}
QLineEdit {{
    background: {C_INPUT_BG};
    border: 1px solid {C_INPUT_BD};
    border-radius: 9px;
    padding: 9px 11px;
    font-size: 14px;
    font-family: "Consolas", "Courier New", monospace;
}}
QLineEdit:focus {{
    border-color: {C_ACCENT};
}}
QPushButton {{
    font-family: "Segoe UI", sans-serif;
    font-weight: 600;
    border-radius: 11px;
    cursor: pointer;
}}
QPushButton#btnRun {{
    background: {C_ACCENT};
    color: #FFFFFF;
    border: 1px solid {C_ACCENT_H};
    padding: 12px 22px;
    font-size: 14px;
    font-weight: 750;
}}
QPushButton#btnRun:hover {{
    background: {C_ACCENT_H};
    color: #FFFFFF;
}}
QPushButton#btnRun:disabled {{
    background: #E5E7EB;
    color: #6B7280;
    border: 1px solid #D1D5DB;
}}
QPushButton#btnSec {{
    background: #F9FAFB;
    color: {C_TEXT2};
    border: 1px solid {C_BORDER};
    padding: 11px 16px;
    font-size: 14px;
}}
QPushButton#btnSec:hover {{
    background: #FFFFFF;
    border-color: {C_BORDER};
}}
QPushButton#btnSec:disabled {{
    background: #E5E7EB;
    color: #6B7280;
    border: 1px solid #D1D5DB;
}}
QPushButton#btnAdd {{
    background: {C_CARD2};
    color: {C_LABEL};
    border: 1.5px dashed {C_BORDER};
    border-radius: 12px;
    padding: 13px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#btnAdd:hover {{
    border-color: {C_ACCENT};
    color: {C_ACCENT};
    background: #EFF6FF;
}}
QPushButton#btnDir {{
    background: {C_CARD};
    color: {C_TEXT2};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#btnDir:hover {{
    background: {C_CARD2};
    border-color: {C_ACCENT};
    color: {C_ACCENT};
}}
QPushButton#btnDel {{
    background: {C_INPUT_BG};
    color: {C_ERR};
    border: 1px solid {C_BORDER2};
    border-radius: 8px;
    padding: 0;
    font-size: 12px;
    font-weight: 600;
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
}}
QPushButton#btnDel:hover {{
    background: #FEF2F2;
    border-color: #FCA5A5;
}}
QTextEdit#log {{
    background: #111827;
    color: #E5E7EB;
    border: none;
    border-radius: 12px;
    padding: 14px 16px;
    font-family: "Consolas", "JetBrains Mono", monospace;
    font-size: 12px;
    line-height: 1.75;
}}
"""


# ─── 工具函数 ─────────────────────────────────────────────────────────────────











# ─── DropZone ─────────────────────────────────────────────────────────────────





# ─── SegmentRow ───────────────────────────────────────────────────────────────

















# ─── Songlist 配置面板 ────────────────────────────────────────────────────────



# ─── 主窗口 ───────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._migration_report = prepare_runtime_data()
        self._cfg    = load_config()
        self._rows: list[SegmentRow] = []
        self._worker: SlicerWorker | None = None
        self._waveform_worker: WaveformWorker | None = None
        self._waveform_workers: list[WaveformWorker] = []
        self._waveform_generation = 0
        self._waveform_audio_path = ""
        self._external_merge_worker: ExternalMergeWorker | None = None
        self._external_merge_target: Path | None = None
        self._external_merge_plan: external_merge.ExternalMergePlan | None = None
        self._external_merge_phase = "idle"
        self._external_merge_generation = 0
        self._external_merge_restore_message = ""
        self._external_merge_restore_invalid = False
        self._slicer_running = False
        self._current_export_dirty = True
        self._last_run_current_export_enabled = True
        self._current_source_id = ""
        self._suppress_source_reset = False
        self._uid    = 0
        self._segment_order = 0
        self._selected_segment_uid = ""
        self._hovered_segment_uid = ""
        self._auto_sort_enabled = True
        self._sort_mode = "time"
        self._cascade_edit_enabled = True
        self._join_preview_uid = ""
        self._arc_warning_timer = QTimer(self)
        self._arc_warning_timer.setSingleShot(True)
        self._arc_warning_timer.timeout.connect(self._refresh_arc_cut_warnings)
        self._segment_validation_timer = QTimer(self)
        self._segment_validation_timer.setSingleShot(True)
        self._segment_validation_timer.timeout.connect(self._refresh_segment_time_validation)
        self._audio_duration_ms: int | None = None
        self._audio_duration_error = ""

        self.setWindowTitle("Arc Slicer")
        self.setMinimumSize(620, 580)
        self.resize(760, 900)
        self.setAcceptDrops(True)

        self._setup_ui()
        self._restore_external_merge_target_from_config()
        if self._migration_report.has_activity():
            self._push_log(self._migration_report.message(), "muted")
        self._suppress_source_reset = True
        try:
            self._load_initial_data()
        finally:
            self._suppress_source_reset = False
            self._current_source_id = self._song_box.currentText()
        self._request_waveform_for_current_song()
        if self._current_export_dirty:
            self._invalidate_external_merge_plan()

    # ── UI 构建 ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("root")
        central.setAutoFillBackground(True)
        _pal = central.palette()
        _pal.setColor(QPalette.ColorRole.Window, QColor(C_BG))
        central.setPalette(_pal)
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self._scroll)

        content = QWidget()
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setStyleSheet(f"QWidget {{ background: {C_BG}; }}")
        self._scroll.setWidget(content)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(0)

        # ── 标题
        h1 = make_label("准备切片", size=22, weight=600)
        h1.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(h1)

        sub = make_label("选择曲目，标记想保留的时间段，然后运行切片器。", size=13, color=C_MUTED)
        sub.setContentsMargins(0, 0, 0, 20)
        lay.addWidget(sub)

        # ── songs 目录行
        dir_frame = QFrame()
        dir_frame.setStyleSheet(
            f"QFrame {{ background: {C_CARD2}; border: 1px solid {C_BORDER2}; border-radius: 12px; }}"
        )
        dir_lay = QHBoxLayout(dir_frame)
        dir_lay.setContentsMargins(14, 10, 14, 10)
        dir_lay.setSpacing(10)
        dir_lbl = field_label("SONGS 目录")
        dir_lbl.setStyleSheet(f"font-size: 11px; font-weight: 600; letter-spacing: 1px; color: {C_LABEL}; background: transparent; border: none;")
        dir_lay.addWidget(dir_lbl)
        self._dir_path = QLabel()
        self._dir_path.setStyleSheet(
            f"font-family: 'Consolas','Courier New',monospace; font-size: 12px; "
            f"color: {C_TEXT2}; background: transparent; border: none;"
        )
        self._dir_path.setMinimumWidth(80)
        dir_lay.addWidget(self._dir_path, 1)
        btn_dir = QPushButton("更改")
        btn_dir.setObjectName("btnDir")
        btn_dir.clicked.connect(self._browse_songs_dir)
        dir_lay.addWidget(btn_dir)
        dir_frame.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(dir_frame)
        lay.addSpacing(12)

        # ── 拖放区
        self._drop_zone = DropZone()
        self._drop_zone.folder_dropped.connect(self._add_song_folder)
        self._drop_zone.invalid_dropped.connect(lambda msg: self._push_log(f"✗ {msg}", "err"))
        lay.addWidget(self._drop_zone)
        lay.addSpacing(18)

        # ── 曲目 + 速度 topbar
        topbar = QFrame()
        topbar.setStyleSheet(
            f"QFrame {{ background: {C_CARD2}; border: 1px solid {C_BORDER2}; border-radius: 14px; }}"
        )
        tb_lay = QHBoxLayout(topbar)
        tb_lay.setContentsMargins(13, 13, 13, 13)
        tb_lay.setSpacing(12)

        song_col = QVBoxLayout()
        song_col.setSpacing(7)
        song_col.addWidget(field_label("曲目 SONG ID"))
        self._song_box = QComboBox()
        self._song_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._song_box.currentTextChanged.connect(self._on_song_changed)
        song_col.addWidget(self._song_box)
        tb_lay.addLayout(song_col, 1)

        speed_col = QVBoxLayout()
        speed_col.setSpacing(7)
        speed_col.addWidget(field_label("默认速度 DEFAULT SPEED"))
        self._speed_input = QLineEdit("1.0")
        self._speed_input.setFixedWidth(124)
        self._speed_input.textChanged.connect(self._on_default_speed_changed)
        self._speed_input.editingFinished.connect(self._on_default_speed_committed)
        speed_col.addWidget(self._speed_input)
        tb_lay.addLayout(speed_col)

        lay.addWidget(topbar)
        lay.addSpacing(22)

        # ── 段落标题
        seg_head = QHBoxLayout()
        seg_head.setContentsMargins(0, 0, 0, 12)
        self._seg_header = make_label("时间段 · 0 段 · 共 0.0s", size=13, weight=700, color=C_TEXT2)
        seg_head.addWidget(self._seg_header)
        seg_head.addStretch()
        self._audio_duration_label = make_label("音频时长：—", size=12, color=C_LABEL)
        seg_head.addWidget(self._audio_duration_label)
        seg_head.addSpacing(14)
        self._auto_sort_check = QCheckBox("自动排序")
        self._auto_sort_check.setChecked(True)
        self._auto_sort_check.setStyleSheet(f"color: {C_TEXT2}; font-size: 12px; background: transparent; border: none;")
        self._auto_sort_check.clicked.connect(self._on_auto_sort_changed)
        seg_head.addWidget(self._auto_sort_check)
        self._cascade_edit_check = QCheckBox("级联编辑")
        self._cascade_edit_check.setChecked(True)
        self._cascade_edit_check.setStyleSheet(f"color: {C_TEXT2}; font-size: 12px; background: transparent; border: none;")
        self._cascade_edit_check.clicked.connect(self._on_cascade_edit_changed)
        seg_head.addWidget(self._cascade_edit_check)
        self._sort_mode_box = QComboBox()
        self._sort_mode_box.addItem("时间优先", "time")
        self._sort_mode_box.addItem("倍速优先", "speed")
        self._sort_mode_box.addItem("手动顺序", "manual")
        self._sort_mode_box.currentIndexChanged.connect(self._on_sort_mode_changed)
        seg_head.addWidget(self._sort_mode_box)
        seg_head.addSpacing(14)
        seg_head.addWidget(make_label("毫秒 · 对应 .aff 整数时间", size=12, color=C_LABEL))
        lay.addLayout(seg_head)

        self._waveform_panel = WaveformPanel()
        self._waveform_panel.segmentCreated.connect(self._add_waveform_segment)
        self._waveform_panel.segmentEndpointChanged.connect(self._update_waveform_segment_endpoint)
        self._waveform_panel.segmentEndpointCommitted.connect(self._on_waveform_endpoint_committed)
        self._waveform_panel.segmentHovered.connect(self._on_waveform_segment_hovered)
        self._waveform_panel.segmentSelected.connect(self._on_waveform_segment_selected)
        self._waveform_panel.emptySelected.connect(self._clear_selected_segment)
        lay.addWidget(self._waveform_panel)
        lay.addSpacing(12)

        # ── 段落列表
        self._segs_widget = QWidget()
        self._segs_widget.setStyleSheet("background: transparent;")
        self._segs_layout = QVBoxLayout(self._segs_widget)
        self._segs_layout.setContentsMargins(0, 0, 0, 0)
        self._segs_layout.setSpacing(11)
        lay.addWidget(self._segs_widget)
        lay.addSpacing(10)

        # ── 添加按钮
        btn_add = QPushButton("＋ 添加时间段")
        btn_add.setObjectName("btnAdd")
        btn_add.clicked.connect(lambda: self._add_segment())
        lay.addWidget(btn_add)
        lay.addSpacing(20)

        # ── Songlist 配置面板
        self._songlist_panel = SonglistPanel()
        self._songlist_panel.enabled_changed.connect(self._refresh_export_target_state)
        self._songlist_panel.enabled_changed.connect(self._mark_current_export_dirty)
        self._songlist_panel.metadata_changed.connect(self._mark_current_export_dirty)
        lay.addWidget(self._songlist_panel)
        lay.addSpacing(16)

        # ── 导出目标
        lay.addWidget(section_title("导出目标", "EXPORT TARGETS"))
        target_frame = QFrame()
        target_frame.setStyleSheet(
            f"QFrame {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 12px; }}"
        )
        target_lay = QVBoxLayout(target_frame)
        target_lay.setContentsMargins(14, 10, 14, 10)
        target_lay.setSpacing(7)
        target_row = QHBoxLayout()
        target_row.setSpacing(18)
        self._current_export_check = QCheckBox("生成本次导出包")
        self._current_export_check.setChecked(True)
        self._library_export_check = QCheckBox("更新总导出包")
        self._library_export_check.setChecked(True)
        self._current_export_check.clicked.connect(self._mark_current_export_dirty)
        self._library_export_check.clicked.connect(self._mark_current_export_dirty)
        for box in (self._current_export_check, self._library_export_check):
            box.setStyleSheet(
                f"color: {C_TEXT2}; font-size: 13px; background: transparent; border: none;"
            )
        target_row.addWidget(self._current_export_check)
        target_row.addWidget(self._library_export_check)
        target_row.addStretch()
        target_lay.addLayout(target_row)
        self._library_export_note = make_label("需启用 songlist 后才能更新总导出包。", size=12, color=C_LABEL)
        target_lay.addWidget(self._library_export_note)
        lay.addWidget(target_frame)
        lay.addSpacing(16)

        # ── 外部目标壳合并
        # 外部目标壳合并 EXTERNAL MERGE
        lay.addWidget(section_title("外部目标壳合并", "EXTERNAL MERGE"))
        external_frame = QFrame()
        external_frame.setStyleSheet(
            f"QFrame {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 12px; }}"
        )
        external_lay = QVBoxLayout(external_frame)
        external_lay.setContentsMargins(14, 11, 14, 11)
        external_lay.setSpacing(8)

        external_target_row = QHBoxLayout()
        external_target_row.setSpacing(10)
        external_target_row.addWidget(make_label("目标壳 songs 目录", size=12, color=C_LABEL))
        self._external_merge_target_label = QLabel("未选择")
        self._external_merge_target_label.setStyleSheet(
            f"font-family: 'Consolas','Courier New',monospace; font-size: 12px; "
            f"color: {C_TEXT2}; background: transparent; border: none;"
        )
        self._external_merge_target_label.setMinimumWidth(80)
        external_target_row.addWidget(self._external_merge_target_label, 1)
        self._btn_external_choose = QPushButton("选择")
        self._btn_external_choose.setObjectName("btnDir")
        self._btn_external_choose.clicked.connect(self._browse_external_merge_target)
        external_target_row.addWidget(self._btn_external_choose)
        external_lay.addLayout(external_target_row)

        external_actions = QHBoxLayout()
        external_actions.setSpacing(10)
        self._btn_external_check = QPushButton("检查合并计划")
        self._btn_external_check.setObjectName("btnSec")
        self._btn_external_check.clicked.connect(self._check_external_merge_plan)
        external_actions.addWidget(self._btn_external_check)
        self._btn_external_confirm = QPushButton("确认合并")
        self._btn_external_confirm.setObjectName("btnSec")
        self._btn_external_confirm.clicked.connect(self._confirm_external_merge)
        external_actions.addWidget(self._btn_external_confirm)
        external_actions.addStretch()
        external_lay.addLayout(external_actions)

        self._external_merge_status_label = make_label("外部目标壳合并：未检查", size=13, weight=700, color=C_TEXT2)
        external_lay.addWidget(self._external_merge_status_label)
        self._external_merge_detail_label = QLabel()
        self._external_merge_detail_label.setWordWrap(True)
        self._external_merge_detail_label.setStyleSheet(
            f"font-size: 12px; color: {C_MUTED}; background: transparent; border: none; line-height: 1.35;"
        )
        external_lay.addWidget(self._external_merge_detail_label)

        lay.addWidget(external_frame)
        lay.addSpacing(16)

        # ── 操作行
        action_frame = QFrame()
        action_frame.setStyleSheet(
            f"QFrame {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 12px; }}"
        )
        actions = QHBoxLayout(action_frame)
        actions.setContentsMargins(12, 10, 12, 10)
        actions.setSpacing(10)
        self._btn_run = QPushButton("▶  运行切片")
        self._btn_run.setObjectName("btnRun")
        self._btn_run.clicked.connect(self._run_slicer)
        actions.addWidget(self._btn_run)

        btn_save = QPushButton("保存")
        btn_save.setObjectName("btnSec")
        btn_save.clicked.connect(self._save_slides)
        actions.addWidget(btn_save)

        btn_open = QPushButton("打开输出")
        btn_open.setObjectName("btnSec")
        btn_open.clicked.connect(self._open_out)
        actions.addWidget(btn_open)

        self._saved_lbl = make_label("✓ 已保存", size=13, weight=600, color=C_OK)
        self._saved_lbl.hide()
        actions.addWidget(self._saved_lbl)
        actions.addStretch()
        lay.addWidget(action_frame)
        lay.addSpacing(16)

        # ── 日志
        self._log_widget = QTextEdit()
        self._log_widget.setObjectName("log")
        self._log_widget.setReadOnly(True)
        self._log_widget.setMinimumHeight(180)
        self._log_widget.setMaximumHeight(260)
        self._log_widget.hide()
        lay.addWidget(self._log_widget)

        lay.addStretch()

        # 更新目录显示
        self._refresh_dir_label()
        self._refresh_export_target_state()
        self._update_external_merge_controls()

    # ── 初始数据 ──────────────────────────────────────────────────────────────

    def _next_segment_uid(self) -> str:
        self._uid = int(self.__dict__.get("_uid", 0)) + 1
        return f"seg_{self._uid:04d}_{uuid.uuid4().hex[:6]}"

    def _next_segment_order(self) -> int:
        self._segment_order = int(self.__dict__.get("_segment_order", 0)) + 1
        return self._segment_order

    def _connect_segment_row(self, row: SegmentRow) -> None:
        row.deleted.connect(self._remove_segment)
        row.changed.connect(self._refresh_seg_header)
        row.changed.connect(self._refresh_waveform_segments)
        row.changed.connect(self._schedule_arc_cut_warning_refresh)
        if hasattr(self, "_schedule_segment_time_validation"):
            row.changed.connect(self._schedule_segment_time_validation)
        row.changed.connect(self._mark_current_export_dirty)
        row.end_cap_requested.connect(self._set_row_end_to_audio_duration)
        row.copy_requested.connect(self._copy_segment)
        row.field_committed.connect(self._on_segment_field_committed)
        row.enter_pressed.connect(self._on_segment_enter_pressed)
        row.hovered.connect(self._on_segment_row_hovered)
        row.unhovered.connect(self._on_segment_row_unhovered)
        row.selected.connect(self._on_segment_row_selected)
        row.unlink_requested.connect(self._unlink_segment_group)
        row.join_requested.connect(self._join_segment_group)
        row.join_previewed.connect(self._on_join_group_previewed)
        row.join_unpreviewed.connect(self._on_join_group_unpreviewed)

    def _row_by_uid(self, uid: str) -> SegmentRow | None:
        for row in self._rows:
            if getattr(row, "uid", "") == uid:
                return row
        return None

    def _row_time_values(self, row) -> tuple[int | None, int | None]:
        s_val = getattr(row, "s_val", None)
        e_val = getattr(row, "e_val", None)
        if s_val is None and hasattr(row, "start_text"):
            try:
                s_val = int(row.start_text())
            except (TypeError, ValueError):
                s_val = None
        if e_val is None and hasattr(row, "end_text"):
            try:
                e_val = int(row.end_text())
            except (TypeError, ValueError):
                e_val = None
        return s_val, e_val

    def _set_selected_segment_uid(self, uid: str = "", *, scroll: bool = False) -> None:
        self._selected_segment_uid = str(uid or "")
        self._refresh_segment_interaction_state()
        panel = self.__dict__.get("_waveform_panel")
        if self._selected_segment_uid and panel is not None and hasattr(panel, "ensure_segment_uid_visible"):
            try:
                panel.ensure_segment_uid_visible(self._selected_segment_uid)
            except Exception:
                pass
        if scroll and self._selected_segment_uid:
            row = self._row_by_uid(self._selected_segment_uid)
            if row is not None:
                try:
                    self._scroll.ensureWidgetVisible(row)
                except Exception:
                    pass

    def _set_hovered_segment_uid(self, uid: str = "") -> None:
        self._hovered_segment_uid = str(uid or "")
        self._refresh_segment_interaction_state()

    def _clear_selected_segment(self) -> None:
        self._set_selected_segment_uid("")

    def _on_segment_row_hovered(self, row: SegmentRow) -> None:
        self._set_hovered_segment_uid(row.uid if row in self._rows else "")

    def _on_segment_row_unhovered(self, row: SegmentRow) -> None:
        if self._hovered_segment_uid == row.uid:
            self._set_hovered_segment_uid("")

    def _on_segment_row_selected(self, row: SegmentRow) -> None:
        if row in self._rows:
            self._set_selected_segment_uid(row.uid)

    def _on_waveform_segment_hovered(self, uid: str) -> None:
        self._set_hovered_segment_uid(uid)

    def _on_waveform_segment_selected(self, uid: str) -> None:
        self._set_selected_segment_uid(uid, scroll=True)

    def _on_join_group_previewed(self, row: SegmentRow) -> None:
        if row in self._rows and self._row_join_mode(row):
            self._join_preview_uid = row.uid
            self._refresh_visual_groups()

    def _on_join_group_unpreviewed(self, row: SegmentRow) -> None:
        if self.__dict__.get("_join_preview_uid", "") == getattr(row, "uid", ""):
            self._join_preview_uid = ""
            self._refresh_visual_groups()

    def _unlink_segment_group(self, row: SegmentRow) -> None:
        if row not in self._rows:
            return
        if not normalize_link_group_id(getattr(row, "link_group_id", None)):
            return
        row.link_group_id = None
        self._cleanup_single_member_link_groups()
        self._set_selected_segment_uid(row.uid)
        self._join_preview_uid = ""
        self._refresh_visual_groups()
        self._maybe_auto_sort_segments()
        self._mark_current_export_dirty()

    def _join_segment_group(self, row: SegmentRow) -> None:
        if row not in self._rows:
            return
        group_id = self._row_join_target_group_id(row)
        target_rows = [row]
        if not group_id:
            target_rows = self._same_interval_unlinked_rows(row)
            if not target_rows:
                return
            group_id = new_link_group_id()
        for target in target_rows:
            target.link_group_id = group_id
        self._set_selected_segment_uid(row.uid)
        self._join_preview_uid = ""
        self._refresh_visual_groups()
        self._maybe_auto_sort_segments()
        self._mark_current_export_dirty()

    def _refresh_segment_interaction_state(self) -> None:
        selected = self.__dict__.get("_selected_segment_uid", "")
        hovered = self.__dict__.get("_hovered_segment_uid", "")
        for row in getattr(self, "_rows", []):
            row.set_interaction_state(selected=row.uid == selected, hovered=row.uid == hovered)
        panel = self.__dict__.get("_waveform_panel")
        if panel is not None and hasattr(panel, "set_selection_state"):
            panel.set_selection_state(selected, hovered)

    def _complete_visual_groups(self) -> dict[tuple[int, int], list[SegmentRow]]:
        groups: dict[tuple[int, int], list[SegmentRow]] = {}
        for row in getattr(self, "_rows", []):
            s_val, e_val = self._row_time_values(row)
            if s_val is None or e_val is None or e_val <= s_val:
                continue
            groups.setdefault((int(s_val), int(e_val)), []).append(row)
        return groups

    def _complete_link_groups(self) -> dict[str, list[SegmentRow]]:
        groups: dict[str, list[SegmentRow]] = {}
        for row in getattr(self, "_rows", []):
            group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
            if not group_id:
                continue
            s_val, e_val = self._row_time_values(row)
            if s_val is None or e_val is None or e_val <= s_val:
                continue
            groups.setdefault(group_id, []).append(row)
        return groups

    def _valid_link_groups(self) -> dict[str, list[SegmentRow]]:
        return {group_id: members for group_id, members in self._complete_link_groups().items() if len(members) >= 2}

    def _row_join_target_group_id(self, row: SegmentRow) -> str | None:
        if normalize_link_group_id(getattr(row, "link_group_id", None)):
            return None
        s_val, e_val = self._row_time_values(row)
        if s_val is None or e_val is None or e_val <= s_val:
            return None
        valid_groups = self._valid_link_groups()
        for candidate in getattr(self, "_rows", []):
            group_id = normalize_link_group_id(getattr(candidate, "link_group_id", None))
            if not group_id or group_id not in valid_groups:
                continue
            c_s, c_e = self._row_time_values(candidate)
            if c_s == s_val and c_e == e_val:
                return group_id
        return None

    def _same_interval_unlinked_rows(self, row: SegmentRow) -> list[SegmentRow]:
        if normalize_link_group_id(getattr(row, "link_group_id", None)):
            return []
        s_val, e_val = self._row_time_values(row)
        if s_val is None or e_val is None or e_val <= s_val:
            return []
        rows: list[SegmentRow] = []
        for candidate in getattr(self, "_rows", []):
            if normalize_link_group_id(getattr(candidate, "link_group_id", None)):
                continue
            c_s, c_e = self._row_time_values(candidate)
            if c_s == s_val and c_e == e_val:
                rows.append(candidate)
        return rows if len(rows) >= 2 else []

    def _row_join_mode(self, row: SegmentRow) -> str:
        if self._row_join_target_group_id(row):
            return "join_existing"
        if self._same_interval_unlinked_rows(row):
            return "create_same_interval"
        return ""

    def _cleanup_single_member_link_groups(self) -> bool:
        changed = False
        groups = self._complete_link_groups()
        for group_id, members in groups.items():
            if len(members) == 1:
                members[0].link_group_id = None
                changed = True
        return changed

    def _refresh_visual_groups(self) -> None:
        groups = self._complete_visual_groups()
        link_groups = self._valid_link_groups()
        group_index = {key: idx for idx, key in enumerate(groups)}
        for row in getattr(self, "_rows", []):
            s_val, e_val = self._row_time_values(row)
            key = (int(s_val), int(e_val)) if s_val is not None and e_val is not None and e_val > s_val else None
            members = groups.get(key, []) if key is not None else []
            if hasattr(row, "set_visual_group"):
                row.set_visual_group(group_index.get(key, 0), len(members) if len(members) > 1 else 1)
            group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
            link_members = link_groups.get(group_id or "", [])
            join_mode = self._row_join_mode(row)
            if hasattr(row, "set_link_group_state"):
                row.set_link_group_state(
                    active=bool(group_id and link_members),
                    member_count=len(link_members) if link_members else 1,
                    join_available=bool(join_mode),
                    join_preview=self.__dict__.get("_join_preview_uid", "") == getattr(row, "uid", ""),
                    join_mode=join_mode,
                )

    def _row_sort_key(self, row: SegmentRow):
        s_val = getattr(row, "s_val", None)
        e_val = getattr(row, "e_val", None)
        if s_val is None and hasattr(row, "start_text"):
            try:
                s_val = int(row.start_text())
            except (TypeError, ValueError):
                s_val = None
        if e_val is None and hasattr(row, "end_text"):
            try:
                e_val = int(row.end_text())
            except (TypeError, ValueError):
                e_val = None
        complete = s_val is not None and e_val is not None and e_val > s_val
        order = int(getattr(row, "created_order", 0))
        if not complete:
            return (1, order)
        speed = row.effective_speed() if hasattr(row, "effective_speed") else self._current_default_speed()
        if self.__dict__.get("_sort_mode", "time") == "speed":
            return (0, speed, int(s_val), int(e_val), order)
        return (0, int(s_val), int(e_val), speed, order)

    def _row_effective_speed(self, row) -> float:
        if hasattr(row, "effective_speed"):
            return row.effective_speed()
        if hasattr(row, "speed_override_value"):
            return effective_segment_speed(self._current_default_speed(), row.speed_override_value())
        return self._current_default_speed()

    def _group_aware_sorted_rows(self) -> list[SegmentRow]:
        valid_groups = self._valid_link_groups()
        seen_groups: set[str] = set()
        blocks: list[list[SegmentRow]] = []
        for row in self._rows:
            group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
            if group_id and group_id in valid_groups:
                if group_id in seen_groups:
                    continue
                seen_groups.add(group_id)
                members = list(valid_groups[group_id])
                members.sort(key=lambda item: (self._row_effective_speed(item), int(getattr(item, "created_order", 0))))
                blocks.append(members)
            else:
                blocks.append([row])

        def block_key(block: list[SegmentRow]):
            complete_rows = []
            for item in block:
                s_val, e_val = self._row_time_values(item)
                if s_val is not None and e_val is not None and e_val > s_val:
                    complete_rows.append((item, int(s_val), int(e_val)))
            if not complete_rows:
                return (1, min(int(getattr(item, "created_order", 0)) for item in block))
            start = min(s for _item, s, _e in complete_rows)
            end = max(e for _item, _s, e in complete_rows)
            min_speed = min(self._row_effective_speed(item) for item, _s, _e in complete_rows)
            order = min(int(getattr(item, "created_order", 0)) for item in block)
            if self.__dict__.get("_sort_mode", "time") == "speed":
                return (0, min_speed, start, end, order)
            return (0, start, end, min_speed, order)

        sorted_rows: list[SegmentRow] = []
        for block in sorted(blocks, key=block_key):
            sorted_rows.extend(block)
        return sorted_rows

    def _auto_sort_active(self) -> bool:
        return bool(self.__dict__.get("_auto_sort_enabled", True)) and self.__dict__.get("_sort_mode", "time") != "manual"

    def _reorder_rows(self, rows: list[SegmentRow]) -> None:
        self._rows = list(rows)
        for row in self._rows:
            try:
                self._segs_layout.removeWidget(row)
            except Exception:
                pass
        for index, row in enumerate(self._rows):
            if hasattr(self._segs_layout, "insertWidget"):
                self._segs_layout.insertWidget(index, row)
            else:
                self._segs_layout.addWidget(row)
            row.update_index(index + 1)
        self._refresh_visual_groups()
        self._refresh_segment_interaction_state()
        self._refresh_seg_header()
        self._refresh_waveform_segments()

    def _maybe_auto_sort_segments(self, *, force: bool = False) -> None:
        if not force and not self._auto_sort_active():
            self._refresh_visual_groups()
            self._refresh_waveform_segments()
            return
        if self.__dict__.get("_sort_mode", "time") == "manual":
            self._refresh_visual_groups()
            self._refresh_waveform_segments()
            return
        sorted_rows = self._group_aware_sorted_rows()
        if sorted_rows != self._rows:
            self._reorder_rows(sorted_rows)
        else:
            self._refresh_visual_groups()
            self._refresh_waveform_segments()

    def _on_auto_sort_changed(self, *_args) -> None:
        self._auto_sort_enabled = bool(self._auto_sort_check.isChecked())
        if self._auto_sort_enabled:
            self._maybe_auto_sort_segments(force=True)

    def _on_sort_mode_changed(self, *_args) -> None:
        self._sort_mode = self._sort_mode_box.currentData() or "time"
        if self._sort_mode == "manual":
            self._auto_sort_enabled = False
            self._auto_sort_check.setChecked(False)
        elif self._auto_sort_check.isChecked():
            self._auto_sort_enabled = True
            self._maybe_auto_sort_segments(force=True)

    def _on_cascade_edit_changed(self, *_args) -> None:
        self._cascade_edit_enabled = bool(self._cascade_edit_check.isChecked())

    def _load_initial_data(self):
        songs = self._get_songs()
        self._populate_songs(songs)

        if SLIDES_PATH.exists():
            try:
                data = json.loads(SLIDES_PATH.read_text(encoding="utf-8"))
                self._apply_slides(data)
                return
            except Exception:
                pass
        self._add_segment(None, None)

    def _get_songs(self) -> list[str]:
        d = Path(self._cfg.get("songs_dir", ""))
        if not d.is_dir():
            return []
        return sorted(item for item in os.listdir(d) if is_sliceable_song_dir(d / item))

    def _populate_songs(self, songs: list[str]):
        current = self._song_box.currentText()
        self._song_box.clear()
        if not songs:
            self._song_box.addItem("（songs 目录为空）")
            self._refresh_current_audio_duration()
            self._schedule_arc_cut_warning_refresh()
            self._request_waveform_for_current_song()
            return
        for s in songs:
            self._song_box.addItem(s)
        if current in songs:
            self._song_box.setCurrentText(current)
        self._refresh_current_audio_duration()
        self._schedule_arc_cut_warning_refresh()
        self._request_waveform_for_current_song()

    def _apply_slides(self, data: dict):
        if data.get("speed") is not None:
            self._speed_input.setText(str(data["speed"]))
        if data.get("song_id"):
            idx = self._song_box.findText(data["song_id"])
            if idx >= 0:
                self._song_box.setCurrentIndex(idx)
        added_segment = False
        for seg in data.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            try:
                s, e = int(seg["s"]), int(seg["e"])
            except (KeyError, TypeError, ValueError):
                continue
            try:
                speed_override = normalize_speed_override_value(seg.get("speed_override"))
            except (TypeError, ValueError):
                speed_override = None
            uid = str(seg.get("uid") or "") or None
            link_group_id = normalize_link_group_id(seg.get("link_group_id"))
            self._add_segment(s, e, speed_override, uid=uid, link_group_id=link_group_id)
            added_segment = True
        if not added_segment:
            self._add_segment(None, None)
        if hasattr(self._songlist_panel, "set_songlist_enabled"):
            self._songlist_panel.set_songlist_enabled(bool(data.get("songlist_enabled", False)))
        if hasattr(self._songlist_panel, "set_packlist_enabled"):
            self._songlist_panel.set_packlist_enabled(_bool_pref(data.get("packlist_enabled"), False))
        if data.get("songlist"):
            self._songlist_panel.set_meta(data["songlist"])
        if hasattr(self._songlist_panel, "update_pack_defaults"):
            self._songlist_panel.update_pack_defaults(self._song_box.currentText())
        if hasattr(self, "_current_export_check"):
            self._current_export_check.setChecked(_bool_pref(data.get("current_export_enabled"), True))
        if hasattr(self, "_library_export_check"):
            self._library_export_check.setChecked(_bool_pref(data.get("library_export_enabled"), True))
            self._refresh_export_target_state()
        self._refresh_current_audio_duration()
        self._schedule_arc_cut_warning_refresh()

    # ── 目录操作 ──────────────────────────────────────────────────────────────

    def _refresh_dir_label(self):
        p = self._cfg.get("songs_dir", "")
        self._dir_path.setText(p)
        self._dir_path.setToolTip(p)

    def _refresh_export_target_state(self):
        songlist_enabled = (
            self._songlist_panel.is_songlist_enabled()
            if hasattr(self._songlist_panel, "is_songlist_enabled")
            else False
        )
        self._library_export_check.setEnabled(bool(songlist_enabled))
        self._library_export_note.setVisible(not songlist_enabled)
        if hasattr(self._songlist_panel, "_refresh_packlist_state"):
            self._songlist_panel._refresh_packlist_state()

    def _on_song_changed(self, song_id: str):
        song_id = str(song_id or "").strip()
        if getattr(self, "_suppress_source_reset", False):
            return
        if song_id == self._current_source_id:
            self._refresh_current_audio_duration()
            self._schedule_arc_cut_warning_refresh()
            if hasattr(self, "_request_waveform_for_current_song"):
                self._request_waveform_for_current_song()
            return
        self._current_source_id = song_id
        if hasattr(self._songlist_panel, "reset_for_source"):
            self._songlist_panel.reset_for_source(song_id)
        self._clear_segments()
        self._add_segment(None, None)
        self._refresh_current_audio_duration()
        self._schedule_arc_cut_warning_refresh()
        if hasattr(self, "_request_waveform_for_current_song"):
            self._request_waveform_for_current_song()
        self._mark_current_export_dirty()

    def _current_default_speed(self, fallback: float = 1.0) -> float:
        try:
            return parse_speed_text(self._speed_input.text())
        except Exception:
            return fallback

    def _on_default_speed_changed(self, *_args):
        default_speed = self._current_default_speed()
        for row in getattr(self, "_rows", []):
            try:
                row.set_default_speed(default_speed)
            except Exception:
                pass
        if hasattr(self, "_refresh_seg_header"):
            self._refresh_seg_header()
        if hasattr(self, "_refresh_waveform_segments"):
            self._refresh_waveform_segments()
        self._mark_current_export_dirty()

    def _on_default_speed_committed(self, *_args) -> None:
        try:
            parse_speed_text(self._speed_input.text())
        except ValueError:
            return
        self._maybe_auto_sort_segments()

    def _mark_current_export_dirty(self, *_args):
        if getattr(self, "_suppress_source_reset", False):
            return
        self._current_export_dirty = True
        self._invalidate_external_merge_plan("当前配置尚未导出，请先运行切片。")

    def _slicer_is_running(self) -> bool:
        return bool(self.__dict__.get("_slicer_running", False))

    def _external_merge_is_busy(self) -> bool:
        return self.__dict__.get("_external_merge_phase", "idle") in {"checking", "executing"}

    def _set_external_merge_view(self, view: dict) -> None:
        if hasattr(self, "_external_merge_status_label"):
            self._external_merge_status_label.setText(view.get("title", "外部目标壳合并"))
            status_color = C_ACCENT if view.get("state") == "dirty" else C_TEXT2
            self._external_merge_status_label.setStyleSheet(
                f"font-size: 13px; font-weight: 700; color: {status_color}; background: transparent;"
            )
        if hasattr(self, "_external_merge_detail_label"):
            self._external_merge_detail_label.setText(view.get("detail", ""))
            self._external_merge_detail_label.setVisible(bool(view.get("detail")))
            if view.get("state") == "dirty":
                self._external_merge_detail_label.setStyleSheet(
                    "font-size: 12px; color: #92400E; background: #FFFFFF; "
                    "border: 1px solid #F59E0B; border-left: 4px solid #F59E0B; "
                    "border-radius: 8px; padding: 8px;"
                )
            else:
                self._external_merge_detail_label.setStyleSheet(
                    f"font-size: 12px; color: {C_MUTED}; background: transparent; border: none;"
                )
        self._update_external_merge_controls()

    def _update_external_merge_controls(self) -> None:
        if not hasattr(self, "_btn_external_check"):
            return
        busy = self._external_merge_is_busy()
        slicing = self._slicer_is_running()
        dirty = bool(getattr(self, "_current_export_dirty", False))
        if hasattr(self, "_btn_run"):
            self._btn_run.setEnabled(not busy and not slicing)
        self._btn_external_choose.setEnabled(not busy and not slicing)
        self._btn_external_check.setEnabled(
            external_merge_can_check(self._external_merge_target, busy=busy, slicing=slicing) and not dirty
        )
        self._btn_external_confirm.setEnabled(
            external_merge_can_confirm(self._external_merge_plan, busy=busy) and not slicing and not dirty
        )

    def _set_external_merge_target_path(self, path: Path | str) -> None:
        path = Path(path)
        self._external_merge_target = path
        if hasattr(self, "_external_merge_target_label"):
            text = str(path)
            self._external_merge_target_label.setText(text)
            self._external_merge_target_label.setToolTip(text)

    def _restore_external_merge_target_from_config(self) -> None:
        target, message = _external_merge_target_status(
            self._cfg.get(EXTERNAL_MERGE_TARGET_CONFIG_KEY)
        )
        self._external_merge_plan = None
        if target is not None:
            self._set_external_merge_target_path(target)
            self._external_merge_restore_message = "已恢复上次目标目录，请检查合并计划。"
            self._external_merge_restore_invalid = False
            self._invalidate_external_merge_plan(self._external_merge_restore_message)
            return
        if EXTERNAL_MERGE_TARGET_CONFIG_KEY in self._cfg:
            self._external_merge_restore_message = message
            self._external_merge_restore_invalid = bool(message)
            self._invalidate_external_merge_plan(message)

    def _invalidate_external_merge_plan(self, message: str = "") -> None:
        self._external_merge_plan = None
        if bool(getattr(self, "_current_export_dirty", False)):
            self._set_external_merge_view(
                external_merge_dirty_view_model(
                    self._external_merge_target,
                    backup_root=EXTERNAL_MERGE_BACKUP_ROOT,
                    extra_message=(
                        self._external_merge_restore_message
                        if self._external_merge_restore_invalid
                        else ""
                    ),
                )
            )
            return
        view = external_merge_plan_view_model(
            None,
            target_songs_dir=self._external_merge_target,
            backup_root=EXTERNAL_MERGE_BACKUP_ROOT,
        )
        if not message and self._external_merge_restore_message:
            message = self._external_merge_restore_message
        if message:
            view["detail"] = view["detail"] + "\n" + message
        self._set_external_merge_view(view)

    def _browse_external_merge_target(self) -> None:
        if self._external_merge_is_busy() or self._slicer_is_running():
            return
        start = str(self._external_merge_target or DATA_ROOT)
        path = QFileDialog.getExistingDirectory(self, "选择目标壳 songs 目录", start)
        if not path:
            return
        target, message = _external_merge_target_status(path)
        if target is None:
            self._invalidate_external_merge_plan(message)
            return
        self._external_merge_restore_message = ""
        self._set_external_merge_target_path(target)
        self._cfg[EXTERNAL_MERGE_TARGET_CONFIG_KEY] = str(target)
        save_config(self._cfg)
        self._invalidate_external_merge_plan("目标路径已变更，请重新检查合并计划。")

    def _check_external_merge_plan(self) -> None:
        if self._external_merge_is_busy() or self._slicer_is_running():
            return
        if not external_merge_can_check(
            self._external_merge_target,
            busy=self._external_merge_is_busy(),
            slicing=self._slicer_is_running(),
        ):
            return
        self._external_merge_generation += 1
        generation = self._external_merge_generation
        self._external_merge_phase = "checking"
        self._external_merge_plan = None
        self._external_merge_status_label.setText("外部目标壳合并：检查中")
        self._external_merge_detail_label.setText("正在读取 current_export/songs 与目标壳 songs 目录；此步骤不会写入目标。")
        self._external_merge_detail_label.show()
        self._update_external_merge_controls()
        self._external_merge_worker = ExternalMergeWorker(
            "check",
            generation,
            CURRENT_EXPORT_SONGS_DIR,
            self._external_merge_target,
            EXTERNAL_MERGE_BACKUP_ROOT,
        )
        self._external_merge_worker.done_signal.connect(self._on_external_merge_done)
        self._external_merge_worker.start()

    def _confirm_external_merge(self) -> None:
        if self._external_merge_is_busy() or self._slicer_is_running():
            return
        if not external_merge_can_confirm(self._external_merge_plan, busy=self._external_merge_is_busy()):
            return
        from PyQt6.QtWidgets import QMessageBox

        text = external_merge_confirmation_text(self._external_merge_plan, EXTERNAL_MERGE_BACKUP_ROOT)
        answer = QMessageBox.question(
            self,
            "确认合并到外部目标壳",
            text,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        self._external_merge_generation += 1
        generation = self._external_merge_generation
        self._external_merge_phase = "executing"
        self._external_merge_status_label.setText("外部目标壳合并：执行中")
        self._external_merge_detail_label.setText("正在备份受影响项目并执行合并。")
        self._external_merge_detail_label.show()
        self._update_external_merge_controls()
        self._external_merge_worker = ExternalMergeWorker(
            "execute",
            generation,
            CURRENT_EXPORT_SONGS_DIR,
            self._external_merge_target or Path(),
            EXTERNAL_MERGE_BACKUP_ROOT,
            self._external_merge_plan,
        )
        self._external_merge_worker.done_signal.connect(self._on_external_merge_done)
        self._external_merge_worker.start()

    def _on_external_merge_done(self, mode: str, generation: int, payload: object, error: str) -> None:
        if generation != self._external_merge_generation:
            return
        self._external_merge_phase = "idle"
        self._external_merge_worker = None
        if error:
            self._external_merge_plan = None
            self._set_external_merge_view({
                "title": "外部目标壳合并：失败",
                "detail": f"{mode} 失败: {error}",
                "can_confirm": False,
            })
            label = "检查失败" if mode == "check" else "执行失败"
            self._push_log(f"[外部合并] {label}：{error}", "err")
            return

        if mode == "check":
            self._external_merge_plan = payload
            self._set_external_merge_view(
                external_merge_plan_view_model(
                    self._external_merge_plan,
                    backup_root=EXTERNAL_MERGE_BACKUP_ROOT,
                )
            )
            return

        result = payload
        self._external_merge_plan = None
        self._set_external_merge_view(external_merge_result_view_model(result))
        text, kind = external_merge_log_line(result)
        self._push_log(text, kind)

    def _browse_songs_dir(self):
        d = self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR))
        path = QFileDialog.getExistingDirectory(self, "选择 songs 根目录", d)
        if path:
            self._cfg["songs_dir"] = path
            save_config(self._cfg)
            self._refresh_dir_label()
            self._populate_songs(self._get_songs())
            self._refresh_current_audio_duration()
            self._schedule_arc_cut_warning_refresh()
            self._push_log(f"✓ songs 目录 → {path}", "ok")

    def _add_song_folder(self, src_path: str):
        src = Path(src_path)
        songs_dir = Path(self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR)))

        ok, msg, song_id = import_song_folder(src, songs_dir)
        if ok and song_id == src.name and (songs_dir / src.name).resolve() == src.resolve():
            self._push_log(f"  {msg}", "muted")
        elif ok and song_id == src.name and (songs_dir / src.name).exists():
            self._push_log(f"✓ {msg}", "ok")
        else:
            self._push_log(f"✗ {msg}", "err")
            return

        self._populate_songs(self._get_songs())
        idx = self._song_box.findText(song_id or src.name)
        if idx >= 0:
            self._song_box.setCurrentIndex(idx)
        self._clear_segments()
        self._add_segment(None, None)
        self._refresh_current_audio_duration()
        self._schedule_arc_cut_warning_refresh()
        self._request_waveform_for_current_song()

    # ── 段落管理 ──────────────────────────────────────────────────────────────

    def _clear_segments(self):
        while self._rows:
            row = self._rows.pop()
            self._segs_layout.removeWidget(row)
            row.deleteLater()
        self._selected_segment_uid = ""
        self._hovered_segment_uid = ""
        if hasattr(self, "_refresh_waveform_segments"):
            self._refresh_waveform_segments()

    def _add_segment(
        self,
        s=_AUTO_SEGMENT,
        e=_AUTO_SEGMENT,
        speed_override=None,
        uid: str | None = None,
        link_group_id=None,
    ):
        if s is _AUTO_SEGMENT and e is _AUTO_SEGMENT:
            s = None
            e = None
        elif s is _AUTO_SEGMENT or e is _AUTO_SEGMENT:
            raise ValueError("s and e must be provided together")

        row = SegmentRow(
            len(self._rows) + 1,
            s,
            e,
            speed_override=speed_override,
            default_speed=self._current_default_speed() if hasattr(self, "_speed_input") else 1.0,
            uid=uid or self._next_segment_uid(),
            link_group_id=link_group_id,
        )
        row.created_order = self._next_segment_order()
        self._connect_segment_row(row)
        self._rows.append(row)
        self._segs_layout.addWidget(row)
        if hasattr(self, "_refresh_seg_header"):
            self._refresh_seg_header()
        if hasattr(self, "_refresh_waveform_segments"):
            self._refresh_waveform_segments()
        if hasattr(self, "_schedule_segment_time_validation"):
            self._schedule_segment_time_validation()
        if hasattr(self, "_schedule_arc_cut_warning_refresh"):
            self._schedule_arc_cut_warning_refresh()
        self._maybe_auto_sort_segments()

    def _remove_segment(self, row: SegmentRow):
        self._rows.remove(row)
        self._segs_layout.removeWidget(row)
        row.deleteLater()
        self._cleanup_single_member_link_groups()
        if self._selected_segment_uid == row.uid:
            self._selected_segment_uid = ""
        if self._hovered_segment_uid == row.uid:
            self._hovered_segment_uid = ""
        for i, r in enumerate(self._rows):
            r.update_index(i + 1)
        if not self._rows:
            self._add_segment(None, None)
            return
        self._refresh_seg_header()
        self._refresh_waveform_segments()
        if hasattr(self, "_schedule_segment_time_validation"):
            self._schedule_segment_time_validation()
        if hasattr(self, "_schedule_arc_cut_warning_refresh"):
            self._schedule_arc_cut_warning_refresh()
        self._maybe_auto_sort_segments()
        self._mark_current_export_dirty()

    def _copy_segment(self, row: SegmentRow):
        if row not in self._rows:
            return
        source_group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
        if source_group_id:
            link_group_id = source_group_id
        else:
            link_group_id = new_link_group_id()
            row.link_group_id = link_group_id
        new_row = SegmentRow(
            self._rows.index(row) + 2,
            row.s_val,
            row.e_val,
            speed_override=None,
            default_speed=self._current_default_speed() if hasattr(self, "_speed_input") else 1.0,
            uid=self._next_segment_uid(),
            link_group_id=link_group_id,
        )
        new_row.created_order = self._next_segment_order()
        self._connect_segment_row(new_row)
        insert_at = self._rows.index(row) + 1
        self._rows.insert(insert_at, new_row)
        if hasattr(self._segs_layout, "insertWidget"):
            self._segs_layout.insertWidget(insert_at, new_row)
        else:
            self._segs_layout.addWidget(new_row)
        for i, r in enumerate(self._rows):
            r.update_index(i + 1)
        self._refresh_seg_header()
        self._refresh_waveform_segments()
        if hasattr(self, "_schedule_segment_time_validation"):
            self._schedule_segment_time_validation()
        if hasattr(self, "_schedule_arc_cut_warning_refresh"):
            self._schedule_arc_cut_warning_refresh()
        self._maybe_auto_sort_segments()
        self._mark_current_export_dirty()

    def _refresh_seg_header(self):
        total = 0
        for r in self._rows:
            if r.s_val is not None and r.e_val is not None:
                d = r.e_val - r.s_val
                if d > 0:
                    try:
                        total += d / r.effective_speed()
                    except ValueError:
                        total += d
        self._seg_header.setText(
            f"时间段 · {len(self._rows)} 段 · 共 {total/1000:.1f}s"
        )

    def _schedule_arc_cut_warning_refresh(self):
        self._arc_warning_timer.start(200)

    def _schedule_segment_time_validation(self):
        self._segment_validation_timer.start(120)

    def _current_audio_path(self) -> Path | None:
        song_id = self._song_box.currentText()
        if not isinstance(song_id, str) or not song_id or "目录为空" in song_id:
            return None
        cfg = getattr(self, "_cfg", {})
        raw_songs_dir = cfg.get("songs_dir", str(DEFAULT_SONGS_DIR)) if isinstance(cfg, dict) else str(DEFAULT_SONGS_DIR)
        if not isinstance(raw_songs_dir, (str, os.PathLike)):
            return None
        songs_dir = Path(raw_songs_dir)
        return songs_dir / song_id / "base.ogg"

    def _waveform_segment_ranges(self) -> list[tuple]:
        ranges: list[tuple] = []
        valid_groups = self._valid_link_groups()
        for row in getattr(self, "_rows", []):
            if row.s_val is None or row.e_val is None or row.e_val <= row.s_val:
                continue
            start = int(row.s_val)
            end = int(row.e_val)
            group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
            is_linked = bool(group_id and group_id in valid_groups)
            join_mode = self._row_join_mode(row)
            can_join = bool(join_mode)
            ranges.append((
                start,
                end,
                str(getattr(row, "uid", len(ranges))),
                (group_id if is_linked else None) or (start, end),
                group_id if is_linked else None,
                can_join,
                join_mode,
            ))
        return ranges

    def _waveform_draft_segments(self) -> list[dict]:
        drafts: list[dict] = []
        for index, row in enumerate(getattr(self, "_rows", [])):
            start_text = row.start_text() if hasattr(row, "start_text") else ("" if row.s_val is None else str(row.s_val))
            end_text = row.end_text() if hasattr(row, "end_text") else ("" if row.e_val is None else str(row.e_val))
            if bool(start_text) == bool(end_text):
                continue
            value_text = start_text or end_text
            field_name = "起点" if start_text else "终点"
            value, error = _parse_non_negative_time_text(value_text, field_name)
            if error or value is None:
                continue
            drafts.append({
                "index": index,
                "kind": "start" if start_text else "end",
                "time_ms": int(value),
            })
        return drafts

    def _refresh_waveform_segments(self) -> None:
        panel = self.__dict__.get("_waveform_panel")
        if panel is None:
            return
        if hasattr(panel, "set_segments"):
            panel.set_segments(self._waveform_segment_ranges())
        if hasattr(panel, "set_draft_segments"):
            panel.set_draft_segments(self._waveform_draft_segments())

    def _validate_segment_row_hard(self, row: SegmentRow) -> SegmentValidationResult:
        result = validate_segment_bounds(row.start_text(), row.end_text(), self.__dict__.get("_audio_duration_ms", None))
        row.set_time_errors(result.start_error, result.end_error, result.end_cap_ms)
        if hasattr(row, "set_speed_error"):
            row.set_speed_error(self._segment_speed_error(row))
        return result

    def _on_segment_field_committed(self, row: SegmentRow, field: str) -> None:
        if row not in self._rows:
            return
        if field == "speed":
            if hasattr(row, "set_speed_error"):
                speed_error = self._segment_speed_error(row)
                row.set_speed_error(speed_error)
                if not speed_error:
                    self._maybe_auto_sort_segments()
            return
        result = self._validate_segment_row_hard(row)
        if result.ok:
            self._maybe_auto_sort_segments()

    def _first_empty_field_after(self, row_index: int) -> tuple[SegmentRow, str] | None:
        for row in self._rows[row_index + 1:]:
            if not row.start_text():
                return row, "start"
            if not row.end_text():
                return row, "end"
            if not row.speed_override_text():
                return row, "speed"
        return None

    def _focus_next_segment_field(self, row: SegmentRow, field: str) -> None:
        try:
            index = self._rows.index(row)
        except ValueError:
            return

        target: tuple[SegmentRow, str] | None = None
        if field == "start":
            if not row.end_text():
                target = (row, "end")
            elif not row.speed_override_text():
                target = (row, "speed")
            else:
                target = self._first_empty_field_after(index)
        elif field == "end":
            if not row.speed_override_text():
                target = (row, "speed")
            else:
                target = self._first_empty_field_after(index)
        elif field == "speed":
            target = self._first_empty_field_after(index)

        if target is not None:
            target_row, target_field = target
            target_row.focus_time_field(target_field)

    def _on_segment_enter_pressed(self, row: SegmentRow, field: str) -> None:
        if row not in self._rows:
            return
        if field == "speed":
            speed_error = self._segment_speed_error(row)
            row.set_speed_error(speed_error)
            if speed_error:
                row.focus_time_field("speed")
                return
            self._maybe_auto_sort_segments()
        else:
            result = self._validate_segment_row_hard(row)
            if result.first_field == field:
                row.focus_time_field(field)
                return
            if field == "end" and result.first_field == "start":
                row.focus_time_field("start")
                return
            if result.ok:
                self._maybe_auto_sort_segments()
        self._focus_next_segment_field(row, field)

    def _add_waveform_segment(self, start_ms: int, end_ms: int) -> None:
        try:
            start = int(start_ms)
            end = int(end_ms)
        except (TypeError, ValueError):
            return
        if end - start < WAVEFORM_MIN_SEGMENT_MS:
            return
        self._add_segment(start, end, None)
        self._mark_current_export_dirty()

    def _cascade_edit_active(self) -> bool:
        if "_cascade_edit_check" in self.__dict__:
            try:
                return bool(self._cascade_edit_check.isChecked())
            except Exception:
                pass
        return bool(self.__dict__.get("_cascade_edit_enabled", True))

    def _cascade_rows_for_endpoint_drag(self, row: SegmentRow) -> list[SegmentRow]:
        group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
        valid_groups = self._valid_link_groups()
        if self._cascade_edit_active() and group_id and group_id in valid_groups:
            return list(valid_groups[group_id])
        return [row]

    def _update_waveform_segment_endpoint(self, index: int, start_ms: int, end_ms: int) -> None:
        try:
            item = self._waveform_panel.segment_items()[int(index)]
            row = self._row_by_uid(str(item.get("uid", "")))
            start = int(start_ms)
            end = int(end_ms)
        except (AttributeError, IndexError, TypeError, ValueError):
            return
        if row is None:
            return
        old_start, old_end = self._row_time_values(row)
        start_changed = old_start is not None and start != int(old_start)
        end_changed = old_end is not None and end != int(old_end)
        cascade_rows = self._cascade_rows_for_endpoint_drag(row)
        if start_changed and end_changed:
            if end - start < WAVEFORM_MIN_SEGMENT_MS:
                return
            for member in cascade_rows:
                member.set_time_range(start, end)
        elif start_changed:
            limit = min(int(member.e_val) - WAVEFORM_MIN_SEGMENT_MS for member in cascade_rows if member.e_val is not None)
            start = max(0, min(start, limit))
            for member in cascade_rows:
                member.set_time_range(start, int(member.e_val))
        else:
            duration_ms = int(self.__dict__.get("_audio_duration_ms") or 0)
            if duration_ms <= 0 and hasattr(self._waveform_panel, "_duration_ms"):
                duration_ms = int(self._waveform_panel._duration_ms())
            limit = max(int(member.s_val) + WAVEFORM_MIN_SEGMENT_MS for member in cascade_rows if member.s_val is not None)
            end = max(limit, end)
            if duration_ms > 0:
                end = min(duration_ms, end)
            for member in cascade_rows:
                member.set_time_range(int(member.s_val), end)
        self._set_selected_segment_uid(row.uid)
        self._refresh_waveform_segments()
        self._schedule_segment_time_validation()
        self._schedule_arc_cut_warning_refresh()
        self._mark_current_export_dirty()

    def _on_waveform_endpoint_committed(self) -> None:
        self._maybe_auto_sort_segments()

    def _request_waveform_for_current_song(self) -> None:
        panel = getattr(self, "_waveform_panel", None)
        if panel is None:
            return
        self._waveform_generation += 1
        generation = self._waveform_generation
        self._refresh_waveform_segments()
        audio_path = self._current_audio_path()
        if audio_path is None or not audio_path.is_file():
            self._waveform_audio_path = ""
            panel.set_empty()
            return

        self._waveform_audio_path = str(audio_path)
        panel.set_loading()
        worker = WaveformWorker(generation, audio_path)
        self._waveform_worker = worker
        self._waveform_workers.append(worker)
        worker.done_signal.connect(self._on_waveform_done)
        worker.start()

    def _on_waveform_done(self, generation: int, audio_path: str, data, error: str):
        try:
            sender = self.sender()
            if sender in self._waveform_workers:
                self._waveform_workers.remove(sender)
        except Exception:
            pass
        if generation != getattr(self, "_waveform_generation", 0):
            return
        if audio_path != getattr(self, "_waveform_audio_path", ""):
            return
        panel = getattr(self, "_waveform_panel", None)
        if panel is None:
            return
        if error or not isinstance(data, WaveformData):
            panel.set_error()
            if error:
                self._push_log(f"⚠ 波形生成失败，不影响切片: {error}", "muted")
            return
        panel.set_waveform(data)
        self._refresh_waveform_segments()

    def _refresh_current_audio_duration(self):
        audio_path = self._current_audio_path()
        if audio_path is None or not audio_path.is_file():
            self._audio_duration_ms = None
            self._audio_duration_error = ""
            if hasattr(self, "_audio_duration_label"):
                self._audio_duration_label.setText("音频时长：—")
                self._audio_duration_label.setToolTip("")
            self._refresh_segment_time_validation()
            return

        try:
            self._audio_duration_ms = probe_audio_duration_ms(audio_path)
            self._audio_duration_error = ""
            text = f"音频时长：{format_duration_ms(self._audio_duration_ms)}（终点上限：{self._audio_duration_ms} ms）"
            self._audio_duration_label.setText(text)
            self._audio_duration_label.setToolTip(str(audio_path))
        except Exception as ex:
            self._audio_duration_ms = None
            self._audio_duration_error = str(ex)
            self._audio_duration_label.setText("音频时长：无法读取")
            self._audio_duration_label.setToolTip(str(ex))
            self._push_log(f"⚠ 无法读取当前曲目的音频时长: {ex}", "muted")
        self._refresh_segment_time_validation()

    def _refresh_segment_time_validation(self):
        duration_ms = self._audio_duration_ms
        for row in self._rows:
            if not row.start_text() and not row.end_text():
                row.clear_time_errors()
                if hasattr(row, "clear_speed_error"):
                    row.clear_speed_error()
                continue
            result = validate_segment_bounds(row.start_text(), row.end_text(), duration_ms, allow_draft=True)
            row.set_time_errors(result.start_error, result.end_error, result.end_cap_ms)
            if hasattr(row, "set_speed_error"):
                speed_error = self._segment_speed_error(row)
                row.set_speed_error(speed_error)

    def _first_segment_validation_error(self) -> tuple[int, SegmentRow, SegmentValidationResult] | None:
        duration_ms = self._audio_duration_ms
        for index, row in enumerate(self._rows):
            result = validate_segment_bounds(row.start_text(), row.end_text(), duration_ms)
            row.set_time_errors(result.start_error, result.end_error, result.end_cap_ms)
            if not result.ok:
                return index, row, result
        return None

    def _segment_speed_error(self, row: SegmentRow) -> str:
        if not hasattr(row, "speed_override_text"):
            return ""
        if not row.speed_override_text().strip():
            return ""
        try:
            row.speed_override_value()
        except ValueError as ex:
            return f"倍速无效：{ex}"
        return ""

    def _first_segment_speed_error(self) -> tuple[int, SegmentRow, str] | None:
        for index, row in enumerate(self._rows):
            message = self._segment_speed_error(row)
            row.set_speed_error(message)
            if message:
                return index, row, message
        return None

    def _first_duplicate_segment_id_error(self, song_id: str, default_speed: float) -> tuple[str, str] | None:
        segments = [row.to_dict() for row in self._rows if row.to_dict()]
        try:
            build_segment_export_plan(song_id, segments, default_speed)
        except ValueError as ex:
            message = str(ex)
            if "输出 ID 重复" in message:
                return "输出 ID 重复", message
            return "时间段无效", message
        return None

    def _show_segment_speed_error(self, index: int, row: SegmentRow, message: str):
        title = "片段倍速无效"
        full = f"第 {index + 1} 个时间段：{message}"
        try:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(self, title, full)
        except Exception:
            self._push_log(f"✗ {full}", "err")
        try:
            self._scroll.ensureWidgetVisible(row)
        except Exception:
            pass
        row.focus_time_field("speed")

    def _show_duplicate_segment_id_error(self, title: str, message: str):
        try:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(self, title, message)
        except Exception:
            self._push_log(f"✗ {message}", "err")

    def _set_row_end_to_audio_duration(self, row: SegmentRow):
        if self._audio_duration_ms is None:
            return
        row.set_end_text(self._audio_duration_ms)
        self._refresh_seg_header()
        self._refresh_waveform_segments()
        self._refresh_segment_time_validation()
        self._schedule_arc_cut_warning_refresh()

    def _show_segment_validation_error(self, index: int, row: SegmentRow, result: SegmentValidationResult):
        title = "时间段无效"
        message = f"第 {index + 1} 个时间段：{result.first_message}"
        try:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(self, title, message)
        except Exception:
            self._push_log(f"✗ {message}", "err")
        try:
            self._scroll.ensureWidgetVisible(row)
        except Exception:
            pass
        row.focus_time_field(result.first_field)

    def _clear_arc_cut_warnings(self):
        for row in self._rows:
            row.set_arc_cut_warnings([], [])

    def _refresh_arc_cut_warnings(self):
        try:
            song_id = self._song_box.currentText()
            songs_dir = Path(self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR)))
            aff_path = songs_dir / song_id / "2.aff"
            if not song_id or not aff_path.is_file():
                self._clear_arc_cut_warnings()
                return

            segment_rows: list[SegmentRow] = []
            segments: list[dict] = []
            for row in self._rows:
                if row.s_val is None or row.e_val is None or row.e_val <= row.s_val:
                    row.set_arc_cut_warnings([], [])
                    continue
                segment_rows.append(row)
                segments.append({"s": row.s_val, "e": row.e_val})

            if not segments:
                self._clear_arc_cut_warnings()
                return

            aff_text = aff_path.read_text(encoding="utf-8", errors="replace")
            warnings = find_nonlinear_arc_cut_warnings(aff_text, segments)
            for index, row in enumerate(segment_rows):
                hits = warnings.get(index, {"start": [], "end": []})
                row.set_arc_cut_warnings(hits["start"], hits["end"])
        except Exception:
            self._clear_arc_cut_warnings()

    def _collect(self, speed: float | None = None) -> dict:
        songlist_enabled = (
            bool(self._songlist_panel.is_songlist_enabled())
            if hasattr(self._songlist_panel, "is_songlist_enabled")
            else False
        )
        packlist_enabled = (
            bool(self._songlist_panel.is_packlist_enabled())
            if hasattr(self._songlist_panel, "is_packlist_enabled")
            else False
        )
        if hasattr(self._songlist_panel, "get_form_data"):
            songlist_form = self._songlist_panel.get_form_data()
        else:
            songlist_form = self._songlist_panel.get_meta() or {}
        current_export_enabled = (
            bool(self._current_export_check.isChecked())
            if hasattr(self, "_current_export_check")
            else True
        )
        library_export_enabled = (
            bool(self._library_export_check.isChecked())
            if hasattr(self, "_library_export_check")
            else True
        )
        segments = []
        for row in self._rows:
            item = row.to_dict()
            if item:
                segments.append(item)
        data: dict = {
            "song_id":  self._song_box.currentText(),
            "speed":    parse_speed_text(self._speed_input.text()) if speed is None else speed,
            "segments": segments,
            "songlist_enabled": songlist_enabled,
            "packlist_enabled": packlist_enabled,
            "current_export_enabled": current_export_enabled,
            "library_export_enabled": library_export_enabled,
            "songlist": songlist_form,
        }
        return data

    # ── 保存 / 运行 / 打开 ────────────────────────────────────────────────────

    def _save_slides(self):
        try:
            data = self._collect()
            SLIDES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self._push_log(f"💾 已保存 → {SLIDES_PATH}", "ok")
            self._saved_lbl.show()
            QTimer.singleShot(1900, self._saved_lbl.hide)
        except ValueError as ex:
            self._push_log(f"✗ 保存失败：速度无效: {ex}", "err")
        except Exception as ex:
            self._push_log(f"✗ 保存失败: {ex}", "err")

    def _run_slicer(self):
        if self._slicer_is_running():
            return
        if self._external_merge_is_busy():
            return
        try:
            speed = parse_speed_text(self._speed_input.text())
        except ValueError as ex:
            self._push_log(f"✗ 速度无效: {ex}", "err")
            return
        song_id = self._song_box.currentText()
        if not isinstance(song_id, str) or not song_id or "目录为空" in song_id:
            self._push_log("✗ 请先选择曲目 Song ID", "err")
            return
        self._refresh_current_audio_duration()
        self._maybe_auto_sort_segments(force=True)
        segment_error = self._first_segment_validation_error()
        if segment_error:
            self._show_segment_validation_error(*segment_error)
            return
        speed_error = self._first_segment_speed_error()
        if speed_error:
            self._show_segment_speed_error(*speed_error)
            return
        duplicate_error = self._first_duplicate_segment_id_error(song_id, speed)
        if duplicate_error:
            self._show_duplicate_segment_id_error(*duplicate_error)
            return
        data = self._collect(speed)
        self._last_run_current_export_enabled = bool(data.get("current_export_enabled", True))
        if not data["song_id"] or "目录为空" in data["song_id"]:
            self._push_log("✗ 请先选择曲目 Song ID", "err")
            return
        if not data["segments"]:
            self._push_log("✗ 至少需要一个时间段", "err")
            return
        songlist_template = None
        packlist_template = None
        if data.get("songlist_enabled"):
            try:
                songlist_template = song_template_from_form(data.get("songlist") or {})
            except ValueError as ex:
                self._push_log(f"✗ Songlist 信息无效: {ex}", "err")
                return
            if data.get("packlist_enabled"):
                try:
                    packlist_template = pack_template_from_form(data.get("songlist") or {}, data["song_id"])
                    songlist_template = replace(songlist_template, set=packlist_template.pack_id)
                except ValueError as ex:
                    self._push_log(f"✗ Packlist 信息无效: {ex}", "err")
                    return
        effective_library = effective_library_export_enabled(
            bool(data.get("library_export_enabled", True)),
            bool(data.get("songlist_enabled", False)),
        )
        if not data.get("current_export_enabled", True) and not effective_library:
            self._push_log("✗ 至少需要选择一个有效导出目标", "err")
            return

        self._save_slides()
        self._log_widget.clear()
        self._log_widget.show()
        self._set_running(True)
        self._push_log("▶ 开始切片…", "stage")

        songs_dir     = Path(self._cfg.get("songs_dir", str(DEFAULT_SONGS_DIR)))
        songlist_meta = data.get("songlist") or {}
        self._worker = SlicerWorker(
            songs_dir, data["song_id"], data["segments"], data["speed"],
            songlist_meta, bool(data.get("songlist_enabled")), songlist_template,
            bool(data.get("current_export_enabled", True)),
            bool(data.get("library_export_enabled", True)),
            bool(data.get("packlist_enabled", False)),
            packlist_template,
        )
        self._worker.log_signal.connect(self._push_log)
        self._worker.done_signal.connect(self._on_done)
        self._worker.start()

    def _on_done(self, code: int):
        self._set_running(False)
        if code == 0:
            if getattr(self, "_last_run_current_export_enabled", True):
                self._current_export_dirty = False
                self._invalidate_external_merge_plan("current_export 已更新，请重新检查外部合并计划。")
            else:
                self._mark_current_export_dirty()

    def _set_running(self, on: bool):
        self._slicer_running = bool(on)
        self._btn_run.setEnabled(not on)
        self._btn_run.setText("▶  运行中…" if on else "▶  运行切片")
        self._update_external_merge_controls()

    def _open_out(self):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(OUT_DIR)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(OUT_DIR)])
            else:
                subprocess.run(["xdg-open", str(OUT_DIR)])
        except Exception as ex:
            self._push_log(f"✗ 无法打开目录: {ex}", "err")

    # ── 日志输出 ──────────────────────────────────────────────────────────────

    LOG_COLORS = {
        "ok":     "#34D399",
        "err":    "#FCA5A5",
        "warn":   "#FBBF24",
        "stage":  "#BFDBFE",
        "muted":  "#9CA3AF",
        "normal": "#E5E7EB",
    }
    LOG_WEIGHTS = {
        "ok": "700",
        "err": "700",
        "warn": "700",
        "stage": "650",
    }

    def _push_log(self, text: str, kind: str = "normal"):
        self._log_widget.show()
        color = self.LOG_COLORS.get(kind, self.LOG_COLORS["normal"])
        # Use HTML for colored lines
        import html as _html
        escaped = _html.escape(text)
        weight = self.LOG_WEIGHTS.get(kind, "400")
        self._log_widget.append(f'<span style="color:{color}; font-weight:{weight};">{escaped}</span>')
        self._log_widget.moveCursor(QTextCursor.MoveOperation.End)

    def closeEvent(self, event):
        self._waveform_generation += 1
        for worker in list(getattr(self, "_waveform_workers", [])):
            try:
                if worker.isRunning():
                    worker.quit()
                    worker.wait(500)
            except Exception:
                pass
        super().closeEvent(event)

    # ── 窗口级拖放（从 Explorer 直接拖到窗口任意位置）─────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self._add_song_folder(path)
                break
            if path:
                self._push_log("✗ 请拖入歌曲文件夹，而不是单个文件。", "err")
                break


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Arc Slicer")
    app.setStyleSheet(QSS)

    # 设置全局调色板背景
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C_TEXT))
    app.setPalette(palette)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
