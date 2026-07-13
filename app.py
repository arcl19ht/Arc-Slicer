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
    Qt, QTimer, QSize, QMimeData,
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
try:
    from PyQt6.QtWidgets import QMessageBox
except ImportError:  # Older headless tests install a small fake PyQt surface.
    class QMessageBox:
        class StandardButton:
            Ok = 1
            Cancel = 2

        @staticmethod
        def question(*_args, **_kwargs):
            return QMessageBox.StandardButton.Cancel

        @staticmethod
        def warning(*_args, **_kwargs):
            return None

import external_merge
from arc_slicer.difficulties import is_multi_difficulty_song_dir
from arc_slicer.ui.styles import QSS as _APP_QSS

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

from arc_slicer import exports as _exports_core
from arc_slicer import persistence as _persistence_core
from arc_slicer import workers as _workers_core
from arc_slicer.exports import (
    JACKET_FILENAMES, PACK_COVER_SIZE, PACK_COVER_UPLOAD_SUFFIXES, PACK_DEFAULT_SECTION,
    PACK_ID_RE, PACK_SECTION_OPTIONS, PackTemplate, SongTemplate, build_ftr_compat_difficulties,
    build_packlist_document, build_packlist_entry, build_segment_display_title,
    build_segment_export_plan, build_segment_id, build_songlist_document, build_songlist_entry,
    copy_song_jackets, default_pack_form_for_song, default_pack_img_name,
    effective_library_export_enabled, effective_packlist_export_enabled, make_songlist_entry,
    make_songlist_fragment, merge_packlist_entries, merge_songlist_entries, normalize_pack_section,
    pack_description_placeholder, pack_template_from_form, render_pack_cover, song_template_from_form,
    write_pack_resources_to_stage,
)
from arc_slicer.persistence import (
    MigrationReport, _create_dir_link, _is_dir_link, _legacy_runtime_roots, _norm_path,
    _rewrite_legacy_config_songs_dir, _same_path, import_song_folder,
    migrate_legacy_runtime_data,
)

_exports_path_is_link_or_junction = _exports_core._path_is_link_or_junction

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
    return is_multi_difficulty_song_dir(path)

































































# ─── ffmpeg ───────────────────────────────────────────────────────────────────



TIME_INPUT_PATTERN = r"^-?\d*$"
_TIME_INPUT_RE = re.compile(r"^-?\d*$")
_FFMPEG_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")










































# ─── V2.1 导出路径底座 ───────────────────────────────────────────────────────



def create_current_export_stage(out_dir: Path | None = None) -> Path:
    return _exports_core.create_current_export_stage(OUT_DIR if out_dir is None else out_dir)


def cleanup_current_export_stage(stage_root: Path, out_dir: Path | None = None) -> None:
    return _exports_core.cleanup_current_export_stage(stage_root, OUT_DIR if out_dir is None else out_dir)


def publish_current_export_stage(
    stage_root: Path,
    out_dir: Path | None = None,
    rename_fn=None,
    rmtree_fn=shutil.rmtree,
) -> None:
    return _exports_core.publish_current_export_stage(
        stage_root,
        OUT_DIR if out_dir is None else out_dir,
        rename_fn=rename_fn,
        rmtree_fn=rmtree_fn,
    )


def current_export_root(out_dir: Path | None = None) -> Path:
    return _exports_core.current_export_root(OUT_DIR if out_dir is None else out_dir)


def current_export_songs_dir(out_dir: Path | None = None) -> Path:
    return _exports_core.current_export_songs_dir(OUT_DIR if out_dir is None else out_dir)


def library_export_root(out_dir: Path | None = None) -> Path:
    return _exports_core.library_export_root(OUT_DIR if out_dir is None else out_dir)


def library_export_songs_dir(out_dir: Path | None = None) -> Path:
    return _exports_core.library_export_songs_dir(OUT_DIR if out_dir is None else out_dir)


def _resolved(path: Path) -> Path:
    return _exports_core._resolved(path)


def _is_direct_child(child: Path, parent: Path) -> bool:
    return _exports_core._is_direct_child(child, parent)


def _path_is_link_or_junction(path: Path) -> bool:
    return _exports_path_is_link_or_junction(path)


def _assert_safe_current_export_path(path: Path, out_dir: Path) -> None:
    return _exports_core._assert_safe_current_export_path(path, out_dir)


def _assert_safe_stage_path(stage_root: Path, out_dir: Path) -> None:
    return _exports_core._assert_safe_stage_path(stage_root, out_dir)


def _load_packlist_document(path: Path) -> dict:
    return _exports_core._load_packlist_document(path)


def make_songlist_fragment(new_id: str, start_ms: int, end_ms: int, speed: float) -> dict | None:
    return _exports_core.make_songlist_fragment(new_id, start_ms, end_ms, speed, SONGLIST_EXAMPLE_PATH)


def _select_auto_pack_cover_source(song_dir: Path) -> Path | None:
    return _exports_core._select_auto_pack_cover_source(song_dir)


def _cover_crop_geometry(width: int, height: int, target_ratio: float = 374 / 750) -> tuple[int, int, int, int]:
    if abs(float(target_ratio) - (374 / 750)) < 1e-12:
        return _exports_core._cover_crop_geometry(width, height)
    target_h = PACK_COVER_SIZE[1]
    target_w = int(round(target_h * float(target_ratio)))
    return _exports_core._cover_crop_geometry(width, height, target_w=target_w, target_h=target_h)


def _load_songlist_document(path: Path) -> dict:
    return _exports_core._load_songlist_document(path)


def _bool_pref(value, default: bool) -> bool:
    return _exports_core._bool_pref(value, default)


def render_pack_cover(source_path: Path, out_path: Path, log_fn=None) -> None:
    return _exports_core.render_pack_cover(source_path, out_path, log_fn)


def merge_staging_into_library_export(
    stage_root: Path,
    out_dir: Path | None = None,
    fail_after_dirs: bool = False,
) -> None:
    old_link_checker = _exports_core._path_is_link_or_junction
    _exports_core._path_is_link_or_junction = _path_is_link_or_junction
    try:
        return _exports_core.merge_staging_into_library_export(
            stage_root,
            OUT_DIR if out_dir is None else out_dir,
            fail_after_dirs=fail_after_dirs,
        )
    finally:
        _exports_core._path_is_link_or_junction = old_link_checker


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
    selected_difficulties=None,
    difficulty_metadata=None,
    *,
    duration_getter=None,
) -> int:
    return _exports_core.do_slice(
        songs_dir,
        song_id,
        segments,
        speed,
        log_fn,
        songlist_meta,
        songlist_enabled,
        song_template,
        current_export_enabled,
        library_export_enabled,
        packlist_enabled,
        pack_template,
        selected_difficulties,
        difficulty_metadata,
        ffmpeg_getter=_get_ffmpeg,
        slice_ogg_fn=slice_ogg,
        slice_aff_fn=slice_aff,
        stage_creator=create_current_export_stage,
        stage_cleanup=cleanup_current_export_stage,
        stage_publisher=publish_current_export_stage,
        library_merger=merge_staging_into_library_export,
        cover_renderer=render_pack_cover,
        duration_getter=duration_getter or probe_audio_duration_ms,
    )


def prepare_runtime_data() -> MigrationReport:
    report = _persistence_core.migrate_legacy_runtime_data(data_root=DATA_ROOT)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DEFAULT_SONGS_DIR.mkdir(parents=True, exist_ok=True)
    return report


def load_config(path: Path | None = None) -> dict:
    return _persistence_core.load_config(CONFIG_PATH if path is None else path)


def save_config(cfg: dict, path: Path | None = None) -> None:
    return _persistence_core.save_config(cfg, CONFIG_PATH if path is None else path)





































# ─── songlist ─────────────────────────────────────────────────────────────────

































































# ─── 核心切片 ─────────────────────────────────────────────────────────────────





# ─── 运行数据迁移 / 配置 ─────────────────────────────────────────────────────





























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


ExternalMergeWorker = _workers_core.ExternalMergeWorker


class WaveformWorker(_workers_core.WaveformWorker):
    def __init__(
        self,
        generation: int,
        audio_path: Path,
        samples_per_second: int = DEFAULT_WAVEFORM_SAMPLES_PER_SECOND,
        cache_dir: Path | None = None,
    ):
        super().__init__(
            generation,
            audio_path,
            samples_per_second,
            cache_dir,
            waveform_loader=load_or_generate_waveform,
        )


class SlicerWorker(_workers_core.SlicerWorker):
    def __init__(
        self, songs_dir: Path, song_id: str, segments: list,
        speed: float, songlist_meta: dict | None = None,
        songlist_enabled: bool = False,
        song_template: SongTemplate | None = None,
        current_export_enabled: bool = True,
        library_export_enabled: bool = True,
        packlist_enabled: bool = False,
        pack_template: PackTemplate | None = None,
        *,
        selected_difficulties=None,
        difficulty_metadata=None,
    ):
        super().__init__(
            songs_dir,
            song_id,
            segments,
            speed,
            songlist_meta,
            songlist_enabled,
            song_template,
            current_export_enabled,
            library_export_enabled,
            packlist_enabled,
            pack_template,
            slice_fn=do_slice,
            packlist_enabled_fn=effective_packlist_export_enabled,
            library_enabled_fn=effective_library_export_enabled,
            selected_difficulties=selected_difficulties,
            difficulty_metadata=difficulty_metadata,
        )


# Public compatibility alias. QApplication receives the shared stylesheet only.
QSS = _APP_QSS


# ─── 工具函数 ─────────────────────────────────────────────────────────────────











# ─── DropZone ─────────────────────────────────────────────────────────────────





# ─── SegmentRow ───────────────────────────────────────────────────────────────

















# ─── Songlist 配置面板 ────────────────────────────────────────────────────────



# ─── 主窗口 ───────────────────────────────────────────────────────────────────

from arc_slicer.ui.main_window import MainWindow as _MainWindow, MainWindowDependencies


def _main_window_dependencies() -> MainWindowDependencies:
    return MainWindowDependencies(
        config_path=CONFIG_PATH,
        slides_path=SLIDES_PATH,
        out_dir=OUT_DIR,
        current_export_songs_dir=CURRENT_EXPORT_SONGS_DIR,
        library_export_songs_dir=LIBRARY_EXPORT_SONGS_DIR,
        external_merge_backup_root=EXTERNAL_MERGE_BACKUP_ROOT,
        default_songs_dir=DEFAULT_SONGS_DIR,
        slicer_worker_cls=SlicerWorker,
        waveform_worker_cls=WaveformWorker,
        external_merge_worker_cls=ExternalMergeWorker,
        slice_aff_func=slice_aff,
        slice_ogg_func=slice_ogg,
        waveform_loader_func=load_or_generate_waveform,
        duration_probe_func=probe_audio_duration_ms,
        find_arc_warnings_func=find_nonlinear_arc_cut_warnings,
        file_dialog_cls=QFileDialog,
        message_box_cls=QMessageBox,
    )


class MainWindow(_MainWindow):
    def __init__(self, *args, dependencies: MainWindowDependencies | None = None, **kwargs):
        if dependencies is None:
            dependencies = _main_window_dependencies()
        super().__init__(*args, dependencies=dependencies, **kwargs)

    @staticmethod
    def _ensure_facade_dependencies(target) -> None:
        try:
            current = getattr(target, "_deps", None)
            from_facade = bool(getattr(target, "_deps_from_app_facade", False))
        except RuntimeError:
            current = None
            from_facade = False
        if current is None or from_facade:
            target._deps = _main_window_dependencies()
            target._deps_from_app_facade = True

    def _load_initial_data(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._load_initial_data(self, *args, **kwargs)

    def _invalidate_external_merge_plan(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._invalidate_external_merge_plan(self, *args, **kwargs)

    def _restore_external_merge_target_from_config(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._restore_external_merge_target_from_config(self, *args, **kwargs)

    def _browse_external_merge_target(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._browse_external_merge_target(self, *args, **kwargs)

    def _check_external_merge_plan(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._check_external_merge_plan(self, *args, **kwargs)

    def _confirm_external_merge(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._confirm_external_merge(self, *args, **kwargs)

    def _on_external_merge_done(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._on_external_merge_done(self, *args, **kwargs)

    def _browse_songs_dir(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._browse_songs_dir(self, *args, **kwargs)

    def _add_song_folder(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._add_song_folder(self, *args, **kwargs)

    def _current_audio_path(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._current_audio_path(self, *args, **kwargs)

    def _request_waveform_for_current_song(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._request_waveform_for_current_song(self, *args, **kwargs)

    def _refresh_current_audio_duration(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._refresh_current_audio_duration(self, *args, **kwargs)

    def _show_segment_speed_error(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._show_segment_speed_error(self, *args, **kwargs)

    def _show_duplicate_segment_id_error(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._show_duplicate_segment_id_error(self, *args, **kwargs)

    def _show_segment_validation_error(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._show_segment_validation_error(self, *args, **kwargs)

    def _refresh_arc_cut_warnings(self, *args, **kwargs):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._refresh_arc_cut_warnings(self, *args, **kwargs)

    def _save_slides(self):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._save_slides(self)

    def _run_slicer(self):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._run_slicer(self)

    def _open_out(self):
        MainWindow._ensure_facade_dependencies(self)
        return _MainWindow._open_out(self)



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
