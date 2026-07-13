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
from contextlib import contextmanager
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
    from PyQt6.QtGui import QKeySequence, QShortcut
except ImportError:  # Older headless tests expose a deliberately small Qt surface.
    class QKeySequence:
        class StandardKey:
            Save = "Ctrl+S"

        def __init__(self, value):
            self.value = value

        def __eq__(self, other):
            return isinstance(other, QKeySequence) and self.value == other.value

    class _ShortcutSignal:
        def connect(self, callback):
            self.callback = callback

    class QShortcut:
        def __init__(self, key, _parent=None):
            self._key = key
            self._context = None
            self._auto_repeat = True
            self.activated = _ShortcutSignal()

        def setContext(self, context):
            self._context = context

        def context(self):
            return self._context

        def key(self):
            return self._key

        def setAutoRepeat(self, value):
            self._auto_repeat = bool(value)

        def autoRepeat(self):
            return self._auto_repeat

try:
    from PyQt6.QtWidgets import QPlainTextEdit, QAbstractSpinBox
except ImportError:  # Keep text-focus checks importable under the same test surface.
    class QPlainTextEdit:
        pass

    class QAbstractSpinBox:
        pass
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
    find_inconsistent_link_groups, format_duration_ms, is_time_input_text_allowed, new_link_group_id,
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
from arc_slicer.playback import AudioPlaybackController
from arc_slicer.ui.segment_history import (
    QUndoStack, SegmentHistoryItem, SegmentHistoryState, SegmentSnapshotCommand,
)
from arc_slicer.ui.styles import QSS as _APP_QSS
from arc_slicer.ui.check_box import SemanticCheckBox
from arc_slicer.ui.combo_box import VisualComboBox
from arc_slicer.ui.toggle_switch import ToggleSwitch

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
    return path.is_dir() and (path / "base.ogg").is_file() and (path / "2.aff").is_file()

































































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
        ffmpeg_getter=_get_ffmpeg,
        slice_ogg_fn=slice_ogg,
        slice_aff_fn=slice_aff,
        stage_creator=create_current_export_stage,
        stage_cleanup=cleanup_current_export_stage,
        stage_publisher=publish_current_export_stage,
        library_merger=merge_staging_into_library_export,
        cover_renderer=render_pack_cover,
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


def _external_merge_target_status(
    value: object,
    *,
    current_export_songs_dir: Path = CURRENT_EXPORT_SONGS_DIR,
    library_export_songs_dir: Path = LIBRARY_EXPORT_SONGS_DIR,
) -> tuple[Path | None, str]:
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
    if resolved in {_resolved(current_export_songs_dir), _resolved(library_export_songs_dir)}:
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
        )


# Kept as a public compatibility alias; the facade applies the shared stylesheet.
QSS = _APP_QSS


# ─── 工具函数 ─────────────────────────────────────────────────────────────────











# ─── DropZone ─────────────────────────────────────────────────────────────────





# ─── SegmentRow ───────────────────────────────────────────────────────────────

















# ─── Songlist 配置面板 ────────────────────────────────────────────────────────



# ─── 主窗口 ───────────────────────────────────────────────────────────────────

@dataclass
class MainWindowDependencies:
    config_path: Path = CONFIG_PATH
    slides_path: Path = SLIDES_PATH
    out_dir: Path = OUT_DIR
    current_export_songs_dir: Path = CURRENT_EXPORT_SONGS_DIR
    library_export_songs_dir: Path = LIBRARY_EXPORT_SONGS_DIR
    external_merge_backup_root: Path = EXTERNAL_MERGE_BACKUP_ROOT
    default_songs_dir: Path = DEFAULT_SONGS_DIR
    slicer_worker_cls: type = SlicerWorker
    waveform_worker_cls: type = WaveformWorker
    external_merge_worker_cls: type = ExternalMergeWorker
    slice_aff_func: object = slice_aff
    slice_ogg_func: object = slice_ogg
    waveform_loader_func: object = load_or_generate_waveform
    duration_probe_func: object = probe_audio_duration_ms
    find_arc_warnings_func: object = find_nonlinear_arc_cut_warnings
    file_dialog_cls: type = QFileDialog
    message_box_cls: object = QMessageBox


def default_main_window_dependencies() -> MainWindowDependencies:
    return MainWindowDependencies()


def _window_dep(owner, name: str, fallback=None):
    deps = getattr(owner, "_deps", None)
    if deps is None:
        return fallback
    return getattr(deps, name, fallback)


@dataclass(frozen=True)
class SegmentEditDisplaySnapshot:
    uid: str
    start_value: int | None
    end_value: int | None
    speed_override_text: str
    effective_speed: float
    was_complete: bool


class MainWindow(QMainWindow):
    def __init__(self, dependencies: MainWindowDependencies | None = None):
        super().__init__()
        self._deps = dependencies or default_main_window_dependencies()
        self._migration_report = prepare_runtime_data()
        self._cfg    = load_config(_window_dep(self, "config_path", CONFIG_PATH))
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
        self._timeline_quick_draft_anchor_ms: int | None = None
        self._auto_sort_enabled = True
        self._sort_mode = "time"
        self._join_preview_uid = ""
        self._segment_history_suspended = False
        self._segment_restore_in_progress = False
        self._segment_edit_display_snapshots: dict[str, SegmentEditDisplaySnapshot] = {}
        self._segment_history_transactions: dict[str, tuple[str, SegmentHistoryState]] = {}
        self._segment_undo_stack = QUndoStack(self)
        self._segment_undo_stack.setUndoLimit(100)
        self._segment_preview_refresh_timer = QTimer(self)
        self._segment_preview_refresh_timer.setSingleShot(True)
        self._segment_preview_refresh_timer.setInterval(100)
        self._segment_preview_refresh_timer.timeout.connect(self._flush_segment_preview_refresh)
        self._arc_warning_timer = QTimer(self)
        self._arc_warning_timer.setSingleShot(True)
        self._arc_warning_timer.timeout.connect(self._refresh_arc_cut_warnings)
        self._segment_validation_timer = QTimer(self)
        self._segment_validation_timer.setSingleShot(True)
        self._segment_validation_timer.timeout.connect(self._refresh_segment_time_validation)
        self._audio_duration_ms: int | None = None
        self._audio_duration_error = ""
        self._playback_controller = AudioPlaybackController(self)
        self._auto_audition_enabled = False

        self.setWindowTitle("Arc Slicer")
        self.setMinimumSize(620, 580)
        self.resize(760, 900)
        self.setAcceptDrops(True)

        self._setup_ui()
        self._install_shortcuts()
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
        reset_history = getattr(self, "_reset_segment_history", None)
        if callable(reset_history):
            reset_history()

    # ── UI 构建 ───────────────────────────────────────────────────────────────

    def _dep(self, name: str, fallback=None):
        deps = getattr(self, "_deps", None)
        if deps is None:
            return fallback
        return getattr(deps, name, fallback)

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
        self._scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self._scroll)

        content = QWidget()
        content.setObjectName("contentRoot")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setAutoFillBackground(True)
        content_palette = content.palette()
        content_palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
        content.setPalette(content_palette)
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
        dir_frame.setObjectName("directoryDisplay")
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
        btn_dir = QPushButton("更改目录")
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
        topbar.setObjectName("songTopbar")
        tb_lay = QHBoxLayout(topbar)
        tb_lay.setContentsMargins(13, 13, 13, 13)
        tb_lay.setSpacing(12)

        song_col = QVBoxLayout()
        song_col.setSpacing(7)
        song_col.addWidget(field_label("曲目 SONG ID"))
        self._song_box = VisualComboBox()
        self._song_box.setObjectName("comboInput")
        self._song_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._song_box.currentTextChanged.connect(self._on_song_changed)
        song_col.addWidget(self._song_box)
        tb_lay.addLayout(song_col, 1)

        speed_col = QVBoxLayout()
        speed_col.setSpacing(7)
        speed_col.addWidget(field_label("默认速度 DEFAULT SPEED"))
        self._speed_input = QLineEdit("1.0")
        self._speed_input.setObjectName("speedInput")
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
        self._auto_sort_check = ToggleSwitch("自动排序")
        self._auto_sort_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._auto_sort_check.setChecked(True)
        self._auto_sort_check.setStyleSheet(f"color: {C_TEXT2}; font-size: 12px; background: transparent; border: none;")
        self._auto_sort_check.clicked.connect(self._on_auto_sort_changed)
        seg_head.addWidget(self._auto_sort_check)
        seg_head.addWidget(make_label("排序规则", size=12, color=C_MUTED))
        self._sort_mode_box = VisualComboBox()
        self._sort_mode_box.addItem("时间优先", "time")
        self._sort_mode_box.addItem("倍速优先", "speed")
        self._sort_mode_box.setObjectName("comboInput")
        self._sort_mode_box.currentIndexChanged.connect(self._on_sort_mode_changed)
        self._sort_mode_box.setCursor(Qt.CursorShape.PointingHandCursor)
        seg_head.addWidget(self._sort_mode_box)
        seg_head.addSpacing(14)
        seg_head.addWidget(make_label("毫秒 · 对应 .aff 整数时间", size=12, color=C_LABEL))
        lay.addLayout(seg_head)

        self._waveform_panel = WaveformPanel()
        self._waveform_panel.segmentCreated.connect(self._add_waveform_segment)
        self._waveform_panel.segmentEndpointChanged.connect(self._update_waveform_segment_endpoint)
        self._waveform_panel.segmentEndpointCommitted.connect(self._on_waveform_endpoint_committed)
        self._waveform_panel.segmentEndpointDragStarted.connect(self._on_waveform_endpoint_drag_started)
        self._waveform_panel.segmentEndpointDragFinished.connect(self._on_waveform_endpoint_drag_finished)
        self._waveform_panel.segmentHovered.connect(self._on_waveform_segment_hovered)
        self._waveform_panel.segmentSelected.connect(self._on_waveform_segment_selected)
        self._waveform_panel.emptySelected.connect(self._clear_selected_segment)
        self._waveform_panel.timeline_quick_draft_requested.connect(self._on_timeline_quick_draft_requested)
        lay.addWidget(self._waveform_panel)
        playback_toolbar = QFrame()
        playback_toolbar.setObjectName("playbackToolbar")
        audition = QHBoxLayout(playback_toolbar)
        audition.setContentsMargins(10, 8, 10, 8)
        audition.setSpacing(10)
        self._play_pause_button = QPushButton("▶ 播放片段")
        self._play_pause_button.setObjectName("btnPlayback")
        self._play_pause_button.clicked.connect(self._toggle_selected_segment_playback)
        self._loop_check = ToggleSwitch("循环")
        self._loop_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._loop_check.setChecked(True)
        self._loop_check.toggled.connect(self._playback_controller.set_loop_enabled)
        self._auto_audition_check = ToggleSwitch("自动试听")
        self._auto_audition_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._auto_audition_check.setChecked(False)
        self._auto_audition_check.toggled.connect(self._set_auto_audition_enabled)
        self._audition_time_label = make_label("0:00.000 / 0:00.000", size=12, color=C_MUTED)
        self._audition_speed_label = make_label("1×", size=12, color=C_MUTED)
        self._audition_status_label = make_label("请选择完整片段", size=12, color=C_LABEL)
        for label in (self._audition_time_label, self._audition_speed_label, self._audition_status_label):
            label.setObjectName("statusChip")
        audition.addWidget(self._play_pause_button); audition.addWidget(self._loop_check); audition.addWidget(self._auto_audition_check); audition.addWidget(self._audition_time_label); audition.addWidget(self._audition_speed_label); audition.addWidget(self._audition_status_label); audition.addStretch()
        lay.addWidget(playback_toolbar)
        self._playback_controller.position_changed.connect(self._on_playback_position_changed)
        self._playback_controller.state_changed.connect(self._on_playback_state_changed)
        self._playback_controller.error_changed.connect(self._on_playback_error)
        self._refresh_selected_segment_audition()
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
        btn_add.setObjectName("btnAddSegment")
        btn_add.clicked.connect(self._on_add_segment_clicked)
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
        target_frame.setObjectName("exportCard")
        target_lay = QVBoxLayout(target_frame)
        target_lay.setContentsMargins(14, 10, 14, 10)
        target_lay.setSpacing(7)
        target_row = QHBoxLayout()
        target_row.setSpacing(18)
        self._current_export_check = SemanticCheckBox("生成本次导出包")
        self._current_export_check.setChecked(True)
        self._library_export_check = SemanticCheckBox("更新总导出包")
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
        external_frame.setObjectName("externalMergeCard")
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
        self._btn_external_choose = QPushButton("选择目录")
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
        self._btn_external_confirm.setObjectName("btnPrimary")
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
        action_frame.setObjectName("actionBar")
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

    def _install_shortcuts(self) -> None:
        context = Qt.ShortcutContext.WidgetWithChildrenShortcut
        self._save_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        self._save_shortcut.setContext(context)
        self._save_shortcut.setAutoRepeat(False)
        self._save_shortcut.activated.connect(self._save_from_shortcut)

        self._delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        self._delete_shortcut.setContext(context)
        self._delete_shortcut.setAutoRepeat(False)
        self._delete_shortcut.activated.connect(self._delete_selected_segment_from_shortcut)

        self._backspace_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self)
        self._backspace_shortcut.setContext(context)
        self._backspace_shortcut.setAutoRepeat(False)
        self._backspace_shortcut.activated.connect(self._delete_selected_segment_from_shortcut)

        self._duplicate_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
        self._duplicate_shortcut.setContext(context)
        self._duplicate_shortcut.setAutoRepeat(False)
        self._duplicate_shortcut.activated.connect(self._duplicate_selected_segment_from_shortcut)

        self._play_pause_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._play_pause_shortcut.setContext(context)
        self._play_pause_shortcut.setAutoRepeat(False)
        self._play_pause_shortcut.activated.connect(self._toggle_selected_segment_playback)

        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape_shortcut.setContext(context)
        self._escape_shortcut.setAutoRepeat(False)
        self._escape_shortcut.activated.connect(self._handle_escape_shortcut)

        self._undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._undo_shortcut.setContext(context)
        self._undo_shortcut.activated.connect(self._route_undo_shortcut)
        self._redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._redo_shortcut.setContext(context)
        self._redo_shortcut.activated.connect(self._route_redo_shortcut)
        self._alternate_redo_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self._alternate_redo_shortcut.setContext(context)
        self._alternate_redo_shortcut.activated.connect(self._route_redo_shortcut)

    def _segment_history_source_key(self) -> str:
        return str(getattr(self, "_current_source_id", "") or "")

    def _capture_segment_history_state(self) -> SegmentHistoryState:
        return SegmentHistoryState(
            self._segment_history_source_key(),
            tuple(SegmentHistoryItem(
                str(row.uid), int(getattr(row, "created_order", 0)), row.start_text(),
                row.end_text(), row.speed_override_text(),
                normalize_link_group_id(getattr(row, "link_group_id", None)),
            ) for row in self._rows),
            str(getattr(self, "_selected_segment_uid", "") or ""),
        )

    @contextmanager
    def _suspend_segment_history(self):
        previous = self._segment_history_suspended
        self._segment_history_suspended = True
        try:
            yield
        finally:
            self._segment_history_suspended = previous

    def _restore_segment_history_state(self, state: SegmentHistoryState) -> None:
        if state.source_key != self._segment_history_source_key():
            return
        with self._batch_restore_segment_history():
            self._move_focus_from_segment_rows()
            timer = self.__dict__.get("_segment_preview_refresh_timer")
            if timer is not None:
                timer.stop()
            self._clear_segments(refresh=False)
            self._uid = 0
            self._segment_order = 0
            for item in state.rows:
                row = self._add_segment(
                    None, None, None, uid=item.uid, link_group_id=item.link_group_id,
                    created_order=item.created_order, refresh=False, sort=False,
                )
                row.restore_history_texts(item.start_text, item.end_text, item.speed_override_text)
            self._cleanup_single_member_link_groups()
            self._maybe_auto_sort_segments()
            self._set_selected_segment_uid(state.selected_uid)
            self._hovered_segment_uid = ""
            self._join_preview_uid = ""
            self._refresh_seg_header()
            self._schedule_segment_time_validation()
            self._schedule_arc_cut_warning_refresh()
        self._mark_current_export_dirty()
        self._refresh_selected_segment_audition()
        self._schedule_selected_segment_auto_audition()

    @contextmanager
    def _batch_restore_segment_history(self):
        previous = self.__dict__.get("_segment_restore_in_progress", False)
        self._segment_restore_in_progress = True
        try:
            with self._suspend_segment_history():
                yield
        finally:
            self._segment_restore_in_progress = previous

    def _segment_row_ancestor(self, widget):
        current = widget
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            if isinstance(current, SegmentRow):
                return current
            parent = getattr(current, "parentWidget", None)
            current = parent() if callable(parent) else None
        return None

    def _move_focus_from_segment_rows(self) -> None:
        focus_getter = getattr(QApplication, "focusWidget", None)
        focused = focus_getter() if callable(focus_getter) else None
        if self._segment_row_ancestor(focused) not in self.__dict__.get("_rows", []):
            return
        try:
            focused.clearFocus()
        except (AttributeError, RuntimeError):
            pass
        try:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        except RuntimeError:
            pass

    def _push_segment_history_command(self, text: str, before: SegmentHistoryState, after: SegmentHistoryState) -> None:
        if self.__dict__.get("_segment_undo_stack") is not None and not self.__dict__.get("_segment_history_suspended", False) and before != after:
            self._segment_undo_stack.push(SegmentSnapshotCommand(text, before, after, self._restore_segment_history_state))

    def _run_segment_history_action(self, text: str, callback):
        if self.__dict__.get("_segment_undo_stack") is None or self.__dict__.get("_segment_history_suspended", False):
            return callback()
        before = self._capture_segment_history_state()
        result = callback()
        self._push_segment_history_command(text, before, self._capture_segment_history_state())
        return result

    def _begin_segment_history_transaction(self, key: str, text: str) -> None:
        if hasattr(self, "_segment_history_transactions") and not self._segment_history_suspended and key not in self._segment_history_transactions:
            self._segment_history_transactions[key] = (text, self._capture_segment_history_state())

    def _commit_segment_history_transaction(self, key: str) -> None:
        transaction = self.__dict__.get("_segment_history_transactions", {}).pop(key, None)
        if transaction:
            text, before = transaction
            self._push_segment_history_command(text, before, self._capture_segment_history_state())

    def _reset_segment_history(self) -> None:
        self._segment_history_transactions.clear()
        self._segment_undo_stack.clear()
        self._segment_undo_stack.setClean()

    def _focused_text_editor(self):
        focus_getter = getattr(QApplication, "focusWidget", None)
        widget = focus_getter() if callable(focus_getter) else None
        while widget is not None:
            if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)) and hasattr(widget, "undo"):
                row = self._segment_row_ancestor(widget)
                if row is not None and row not in self.__dict__.get("_rows", []):
                    return None
                return widget
            if isinstance(widget, QComboBox) and widget.isEditable() and hasattr(widget, "lineEdit"):
                return widget.lineEdit()
            parent = getattr(widget, "parentWidget", None)
            widget = parent() if callable(parent) else None
        return None

    def _route_undo_shortcut(self) -> None:
        editor = self._focused_text_editor()
        if editor is not None: editor.undo()
        else: self._segment_undo_stack.undo()

    def _route_redo_shortcut(self) -> None:
        editor = self._focused_text_editor()
        if editor is not None: editor.redo()
        else: self._segment_undo_stack.redo()

    # ── 初始数据 ──────────────────────────────────────────────────────────────

    def _next_segment_uid(self) -> str:
        self._uid = int(self.__dict__.get("_uid", 0)) + 1
        return f"seg_{self._uid:04d}_{uuid.uuid4().hex[:6]}"

    def _next_segment_order(self) -> int:
        self._segment_order = int(self.__dict__.get("_segment_order", 0)) + 1
        return self._segment_order

    def _connect_segment_row(self, row: SegmentRow) -> None:
        row.deleted.connect(self._remove_segment)
        row.changed.connect(lambda row=row: self._on_segment_row_changed(row))
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
        row.segment_edit_started.connect(self._on_segment_edit_started)
        row.segment_edit_committed.connect(self._on_segment_edit_committed)

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

    def _row_display_snapshot(self, row) -> SegmentEditDisplaySnapshot | None:
        uid = str(getattr(row, "uid", "") or "")
        return self.__dict__.get("_segment_edit_display_snapshots", {}).get(uid)

    def _row_visual_time_values(self, row) -> tuple[int | None, int | None]:
        snapshot = self._row_display_snapshot(row)
        if snapshot is not None:
            return snapshot.start_value, snapshot.end_value
        return self._row_time_values(row)

    def _row_visual_effective_speed(self, row) -> float:
        snapshot = self._row_display_snapshot(row)
        if snapshot is not None:
            return snapshot.effective_speed
        return self._row_effective_speed(row)

    def _capture_segment_edit_display_snapshot(self, row) -> None:
        uid = str(getattr(row, "uid", "") or "")
        snapshots = self.__dict__.setdefault("_segment_edit_display_snapshots", {})
        if not uid or uid in snapshots:
            return
        start, end = self._row_time_values(row)
        try:
            effective_speed = self._row_effective_speed(row)
        except ValueError:
            effective_speed = self._current_default_speed()
        snapshots[uid] = SegmentEditDisplaySnapshot(
            uid=uid,
            start_value=start,
            end_value=end,
            speed_override_text=row.speed_override_text() if hasattr(row, "speed_override_text") else "",
            effective_speed=effective_speed,
            was_complete=bool(start is not None and end is not None and end > start),
        )

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
        self._refresh_selected_segment_audition()

    def _select_segment_for_user(self, uid: str, *, scroll: bool = False) -> None:
        """Apply an explicit user selection, then schedule its refreshed range."""
        self._set_selected_segment_uid(uid, scroll=scroll)
        self._schedule_selected_segment_auto_audition()

    def _refresh_selected_segment_audition(self) -> None:
        controller = self.__dict__.get("_playback_controller")
        if controller is None: return
        row = self._row_by_uid(self.__dict__.get("_selected_segment_uid", ""))
        start, end = self._row_time_values(row) if row is not None else (None, None)
        try: speed = effective_segment_speed(self._current_default_speed(), row.speed_override_value()) if row is not None else 0
        except (TypeError, ValueError): speed = 0
        duration = self.__dict__.get("_audio_duration_ms")
        valid = start is not None and end is not None and end - start >= WAVEFORM_MIN_SEGMENT_MS and (duration is None or end <= duration) and speed > 0
        if not valid:
            controller.clear_audition_range(); self._waveform_panel.set_playback_position_ms(None)
            if hasattr(self, "_play_pause_button"): self._play_pause_button.setEnabled(False); self._audition_status_label.setText("请选择完整片段")
            return
        controller.stop(); controller.set_audition_range(start, end, speed)
        if hasattr(self, "_play_pause_button"):
            self._play_pause_button.setEnabled(controller.is_available() and controller.has_source()); self._audition_speed_label.setText(f"{speed:g}×"); self._audition_time_label.setText(f"{format_duration_ms(0)} / {format_duration_ms(end-start)}"); self._audition_status_label.setText("就绪")
        self._waveform_panel.set_playback_position_ms(start)

    def _auto_audition_is_enabled(self) -> bool:
        return bool(self.__dict__.get("_auto_audition_enabled", False))

    def _cancel_selected_segment_auto_audition(self) -> None:
        cancel = getattr(self.__dict__.get("_playback_controller"), "cancel_pending_auto_play", None)
        if callable(cancel):
            cancel()

    def _schedule_selected_segment_auto_audition(self) -> bool:
        if not self._auto_audition_is_enabled():
            return False
        controller = self.__dict__.get("_playback_controller")
        schedule = getattr(controller, "schedule_auto_play", None)
        row = self._row_by_uid(self.__dict__.get("_selected_segment_uid", ""))
        start, end = self._row_time_values(row) if row is not None else (None, None)
        try:
            speed = effective_segment_speed(self._current_default_speed(), row.speed_override_value()) if row is not None else 0
        except (TypeError, ValueError):
            speed = 0
        duration = self.__dict__.get("_audio_duration_ms")
        is_available = getattr(controller, "is_available", None)
        has_source = getattr(controller, "has_source", None)
        if (
            not callable(schedule)
            or start is None
            or end is None
            or end - start < WAVEFORM_MIN_SEGMENT_MS
            or (duration is not None and end > duration)
            or speed <= 0
            or not callable(is_available)
            or not is_available()
            or not callable(has_source)
            or not has_source()
        ):
            self._cancel_selected_segment_auto_audition()
            return False
        return bool(schedule())

    def _set_auto_audition_enabled(self, enabled: bool) -> None:
        self._auto_audition_enabled = bool(enabled)
        if not self._auto_audition_enabled:
            self._cancel_selected_segment_auto_audition()
            return
        self._refresh_selected_segment_audition()
        self._schedule_selected_segment_auto_audition()

    def _toggle_selected_segment_playback(self) -> None:
        if self._is_text_editing_focus(): return
        self._cancel_selected_segment_auto_audition()
        controller = self.__dict__.get("_playback_controller")
        if controller and controller.toggle_play_pause(): pass

    def _on_playback_position_changed(self, position: int) -> None:
        if hasattr(self, "_waveform_panel"): self._waveform_panel.set_playback_position_ms(position)
        audition = self._playback_controller.audition_range()
        if audition and hasattr(self, "_audition_time_label"): self._audition_time_label.setText(f"{format_duration_ms(max(0, position-audition[0]))} / {format_duration_ms(audition[1]-audition[0])}")

    def _on_playback_state_changed(self, state: str) -> None:
        if hasattr(self, "_play_pause_button"):
            self._play_pause_button.setText("Ⅱ 暂停" if state == "playing" else "▶ 播放片段")

    def _on_playback_error(self, text: str) -> None:
        if hasattr(self, "_audition_status_label"): self._audition_status_label.setText(text or "音频播放失败")

    def _set_hovered_segment_uid(self, uid: str = "") -> None:
        self._hovered_segment_uid = str(uid or "")
        self._refresh_segment_interaction_state()

    def _clear_selected_segment(self) -> None:
        self._set_selected_segment_uid("")

    def _set_timeline_quick_draft_anchor(self, time_ms: int | None) -> None:
        anchor = None if time_ms is None else int(time_ms)
        self._timeline_quick_draft_anchor_ms = anchor
        panel = self.__dict__.get("_waveform_panel")
        if panel is not None and hasattr(panel, "set_quick_draft_anchor"):
            panel.set_quick_draft_anchor(anchor)

    def _cancel_timeline_quick_draft(self) -> None:
        self._set_timeline_quick_draft_anchor(None)

    def _handle_escape_shortcut(self) -> None:
        if self.__dict__.get("_timeline_quick_draft_anchor_ms") is not None:
            self._cancel_timeline_quick_draft()
            return
        focus_getter = getattr(QApplication, "focusWidget", None)
        focus_widget = focus_getter() if callable(focus_getter) else None
        if self._is_text_editing_focus(focus_widget):
            return
        if not self.__dict__.get("_selected_segment_uid", ""):
            return
        self._set_selected_segment_uid("")
        self._set_hovered_segment_uid("")
        self._join_preview_uid = ""
        self._refresh_visual_groups()

    def _on_segment_row_hovered(self, row: SegmentRow) -> None:
        self._set_hovered_segment_uid(row.uid if row in self._rows else "")

    def _on_segment_row_unhovered(self, row: SegmentRow) -> None:
        if self._hovered_segment_uid == row.uid:
            self._set_hovered_segment_uid("")

    def _on_segment_row_selected(self, row: SegmentRow) -> None:
        if row in self._rows:
            self._select_segment_for_user(row.uid)

    def _on_waveform_segment_hovered(self, uid: str) -> None:
        self._set_hovered_segment_uid(uid)

    def _on_waveform_segment_selected(self, uid: str) -> None:
        self._select_segment_for_user(uid)

    def _on_join_group_previewed(self, row: SegmentRow) -> None:
        if row in self._rows and self._row_join_mode(row):
            self._join_preview_uid = row.uid
            self._refresh_visual_groups()

    def _on_join_group_unpreviewed(self, row: SegmentRow) -> None:
        if self.__dict__.get("_join_preview_uid", "") == getattr(row, "uid", ""):
            self._join_preview_uid = ""
            self._refresh_visual_groups()

    def _unlink_segment_group(self, row: SegmentRow, record_history: bool = True) -> None:
        if record_history:
            return self._run_segment_history_action("断开级联", lambda: self._unlink_segment_group(row, False))
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

    def _join_segment_group(self, row: SegmentRow, record_history: bool = True) -> None:
        if record_history:
            return self._run_segment_history_action("加入级联", lambda: self._join_segment_group(row, False))
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
            s_val, e_val = self._row_visual_time_values(row)
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
            s_val, e_val = self._row_visual_time_values(row)
            if s_val is None or e_val is None or e_val <= s_val:
                continue
            groups.setdefault(group_id, []).append(row)
        return groups

    def _valid_link_groups(self) -> dict[str, list[SegmentRow]]:
        inconsistent = self._inconsistent_link_groups()
        return {
            group_id: members for group_id, members in self._complete_link_groups().items()
            if len(members) >= 2 and group_id not in inconsistent
        }

    def _inconsistent_link_groups(self) -> dict[str, dict]:
        return find_inconsistent_link_groups(getattr(self, "_rows", []))

    def _linked_interval_rows(self, row: SegmentRow) -> list[SegmentRow]:
        group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
        if not group_id:
            return [row]
        members = self._complete_link_groups().get(group_id, [])
        return list(members) if row in members else [row]

    def _row_join_target_group_id(self, row: SegmentRow) -> str | None:
        if normalize_link_group_id(getattr(row, "link_group_id", None)):
            return None
        s_val, e_val = self._row_visual_time_values(row)
        if s_val is None or e_val is None or e_val <= s_val:
            return None
        valid_groups = self._valid_link_groups()
        for candidate in getattr(self, "_rows", []):
            group_id = normalize_link_group_id(getattr(candidate, "link_group_id", None))
            if not group_id or group_id not in valid_groups:
                continue
            c_s, c_e = self._row_visual_time_values(candidate)
            if c_s == s_val and c_e == e_val:
                return group_id
        return None

    def _same_interval_unlinked_rows(self, row: SegmentRow) -> list[SegmentRow]:
        if normalize_link_group_id(getattr(row, "link_group_id", None)):
            return []
        s_val, e_val = self._row_visual_time_values(row)
        if s_val is None or e_val is None or e_val <= s_val:
            return []
        rows: list[SegmentRow] = []
        for candidate in getattr(self, "_rows", []):
            if normalize_link_group_id(getattr(candidate, "link_group_id", None)):
                continue
            c_s, c_e = self._row_visual_time_values(candidate)
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
        inconsistent_groups = self._inconsistent_link_groups()
        group_index = {key: idx for idx, key in enumerate(groups)}
        for row in getattr(self, "_rows", []):
            s_val, e_val = self._row_visual_time_values(row)
            key = (int(s_val), int(e_val)) if s_val is not None and e_val is not None and e_val > s_val else None
            members = groups.get(key, []) if key is not None else []
            if hasattr(row, "set_visual_group"):
                row.set_visual_group(group_index.get(key, 0), len(members) if len(members) > 1 else 1)
            group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
            link_members = link_groups.get(group_id or "", [])
            inconsistent = inconsistent_groups.get(group_id or "")
            inconsistent_members = self._complete_link_groups().get(group_id or "", [])
            join_mode = self._row_join_mode(row)
            if hasattr(row, "set_link_group_state"):
                row.set_link_group_state(
                    active=bool(group_id and link_members),
                    member_count=len(link_members) if link_members else len(inconsistent_members) or 1,
                    inconsistent=bool(inconsistent),
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
        valid_groups = self._complete_link_groups()
        seen_groups: set[str] = set()
        blocks: list[list[SegmentRow]] = []
        for row in self._rows:
            group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
            if group_id and group_id in valid_groups:
                if group_id in seen_groups:
                    continue
                seen_groups.add(group_id)
                members = list(valid_groups[group_id])
                members.sort(key=lambda item: (self._row_visual_effective_speed(item), int(getattr(item, "created_order", 0))))
                blocks.append(members)
            else:
                blocks.append([row])

        def block_key(block: list[SegmentRow]):
            complete_rows = []
            for item in block:
                s_val, e_val = self._row_visual_time_values(item)
                if s_val is not None and e_val is not None and e_val > s_val:
                    complete_rows.append((item, int(s_val), int(e_val)))
            if not complete_rows:
                return (1, min(int(getattr(item, "created_order", 0)) for item in block))
            start = min(s for _item, s, _e in complete_rows)
            end = max(e for _item, _s, e in complete_rows)
            min_speed = min(self._row_visual_effective_speed(item) for item, _s, _e in complete_rows)
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
        self._sort_mode_box.setEnabled(self._auto_sort_enabled)
        if self._auto_sort_enabled:
            self._maybe_auto_sort_segments(force=True)

    def _on_sort_mode_changed(self, *_args) -> None:
        self._sort_mode = self._sort_mode_box.currentData() or "time"
        # Old persisted "manual" values mean that automatic ordering is off.
        if self._sort_mode == "manual":
            self._sort_mode = "time"
            self._auto_sort_enabled = False
            self._auto_sort_check.setChecked(False)
            self._sort_mode_box.setCurrentIndex(0)
            self._sort_mode_box.setEnabled(False)
        elif self._auto_sort_check.isChecked():
            self._auto_sort_enabled = True
            self._sort_mode_box.setEnabled(True)
            self._maybe_auto_sort_segments(force=True)

    def _load_initial_data(self):
        songs = self._get_songs()
        self._populate_songs(songs)

        slides_path = _window_dep(self, "slides_path", SLIDES_PATH)
        if slides_path.exists():
            try:
                data = json.loads(slides_path.read_text(encoding="utf-8"))
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
        self._cancel_timeline_quick_draft()
        # V2.3 persisted manual ordering as a sort mode. The refreshed UI models
        # it as the automatic-sort switch being off while preserving row order.
        legacy_sort_mode = str(data.get("sort_mode") or "").strip().lower()
        if legacy_sort_mode == "manual":
            self._auto_sort_enabled = False
            self._auto_sort_check.setChecked(False)
            self._sort_mode_box.setCurrentIndex(0)
            self._sort_mode_box.setEnabled(False)
        elif legacy_sort_mode in {"time", "speed"}:
            self._auto_sort_enabled = True
            self._auto_sort_check.setChecked(True)
            self._sort_mode_box.setCurrentIndex(0 if legacy_sort_mode == "time" else 1)
            self._sort_mode_box.setEnabled(True)
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
        self._cancel_timeline_quick_draft()
        if hasattr(self._songlist_panel, "reset_for_source"):
            self._songlist_panel.reset_for_source(song_id)
        self._clear_segments()
        self._add_segment(None, None)
        self._refresh_current_audio_duration()
        self._schedule_arc_cut_warning_refresh()
        if hasattr(self, "_request_waveform_for_current_song"):
            self._request_waveform_for_current_song()
        self._mark_current_export_dirty()
        reset_history = getattr(self, "_reset_segment_history", None)
        if callable(reset_history):
            reset_history()

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
        row = self._row_by_uid(self.__dict__.get("_selected_segment_uid", ""))
        if row is not None and row.speed_override_value() is None:
            self._refresh_selected_segment_audition()
            self._schedule_selected_segment_auto_audition()

    def _mark_current_export_dirty(self, *_args):
        if self.__dict__.get("_suppress_source_reset", False) or self.__dict__.get("_segment_restore_in_progress", False):
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
            self._cfg.get(EXTERNAL_MERGE_TARGET_CONFIG_KEY),
            current_export_songs_dir=_window_dep(self, "current_export_songs_dir", CURRENT_EXPORT_SONGS_DIR),
            library_export_songs_dir=_window_dep(self, "library_export_songs_dir", LIBRARY_EXPORT_SONGS_DIR),
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
        backup_root = _window_dep(self, "external_merge_backup_root", EXTERNAL_MERGE_BACKUP_ROOT)
        if bool(getattr(self, "_current_export_dirty", False)):
            self._set_external_merge_view(
                external_merge_dirty_view_model(
                    self._external_merge_target,
                    backup_root=backup_root,
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
            backup_root=backup_root,
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
        file_dialog = _window_dep(self, "file_dialog_cls", QFileDialog)
        path = file_dialog.getExistingDirectory(self, "选择目标壳 songs 目录", start)
        if not path:
            return
        target, message = _external_merge_target_status(
            path,
            current_export_songs_dir=_window_dep(self, "current_export_songs_dir", CURRENT_EXPORT_SONGS_DIR),
            library_export_songs_dir=_window_dep(self, "library_export_songs_dir", LIBRARY_EXPORT_SONGS_DIR),
        )
        if target is None:
            self._invalidate_external_merge_plan(message)
            return
        self._external_merge_restore_message = ""
        self._set_external_merge_target_path(target)
        self._cfg[EXTERNAL_MERGE_TARGET_CONFIG_KEY] = str(target)
        save_config(self._cfg, _window_dep(self, "config_path", CONFIG_PATH))
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
        worker_cls = _window_dep(self, "external_merge_worker_cls", ExternalMergeWorker)
        self._external_merge_worker = worker_cls(
            "check",
            generation,
            _window_dep(self, "current_export_songs_dir", CURRENT_EXPORT_SONGS_DIR),
            self._external_merge_target,
            _window_dep(self, "external_merge_backup_root", EXTERNAL_MERGE_BACKUP_ROOT),
        )
        self._external_merge_worker.done_signal.connect(self._on_external_merge_done)
        self._external_merge_worker.start()

    def _confirm_external_merge(self) -> None:
        if self._external_merge_is_busy() or self._slicer_is_running():
            return
        if not external_merge_can_confirm(self._external_merge_plan, busy=self._external_merge_is_busy()):
            return
        message_box = _window_dep(self, "message_box_cls", QMessageBox)
        backup_root = _window_dep(self, "external_merge_backup_root", EXTERNAL_MERGE_BACKUP_ROOT)
        text = external_merge_confirmation_text(self._external_merge_plan, backup_root)
        answer = message_box.question(
            self,
            "确认合并到外部目标壳",
            text,
            message_box.StandardButton.Ok | message_box.StandardButton.Cancel,
            message_box.StandardButton.Cancel,
        )
        if answer != message_box.StandardButton.Ok:
            return
        self._external_merge_generation += 1
        generation = self._external_merge_generation
        self._external_merge_phase = "executing"
        self._external_merge_status_label.setText("外部目标壳合并：执行中")
        self._external_merge_detail_label.setText("正在备份受影响项目并执行合并。")
        self._external_merge_detail_label.show()
        self._update_external_merge_controls()
        worker_cls = _window_dep(self, "external_merge_worker_cls", ExternalMergeWorker)
        self._external_merge_worker = worker_cls(
            "execute",
            generation,
            _window_dep(self, "current_export_songs_dir", CURRENT_EXPORT_SONGS_DIR),
            self._external_merge_target or Path(),
            backup_root,
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
                    backup_root=_window_dep(self, "external_merge_backup_root", EXTERNAL_MERGE_BACKUP_ROOT),
                )
            )
            return

        result = payload
        self._external_merge_plan = None
        self._set_external_merge_view(external_merge_result_view_model(result))
        text, kind = external_merge_log_line(result)
        self._push_log(text, kind)

    def _browse_songs_dir(self):
        d = self._cfg.get("songs_dir", str(_window_dep(self, "default_songs_dir", DEFAULT_SONGS_DIR)))
        file_dialog = _window_dep(self, "file_dialog_cls", QFileDialog)
        path = file_dialog.getExistingDirectory(self, "选择 songs 根目录", d)
        if path:
            self._cfg["songs_dir"] = path
            save_config(self._cfg, _window_dep(self, "config_path", CONFIG_PATH))
            self._refresh_dir_label()
            self._populate_songs(self._get_songs())
            self._refresh_current_audio_duration()
            self._schedule_arc_cut_warning_refresh()
            self._push_log(f"✓ songs 目录 → {path}", "ok")

    def _add_song_folder(self, src_path: str):
        src = Path(src_path)
        songs_dir = Path(self._cfg.get("songs_dir", str(_window_dep(self, "default_songs_dir", DEFAULT_SONGS_DIR))))

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

    def _clear_segments(self, *, refresh: bool = True):
        self._cancel_timeline_quick_draft()
        self.__dict__.get("_segment_edit_display_snapshots", {}).clear()
        while self._rows:
            row = self._rows.pop()
            self._segs_layout.removeWidget(row)
            row.deleteLater()
        self._selected_segment_uid = ""
        self._hovered_segment_uid = ""
        self._refresh_selected_segment_audition()
        if refresh and hasattr(self, "_refresh_waveform_segments"):
            self._refresh_waveform_segments()

    def _on_add_segment_clicked(self) -> None:
        self._run_segment_history_action("新增片段", lambda: self._add_segment())

    def _create_user_segment(self, start_ms: int, end_ms: int) -> SegmentRow | None:
        created: SegmentRow | None = None

        def create() -> None:
            nonlocal created
            created = self._add_segment(start_ms, end_ms, None)
            if created is not None:
                self._set_selected_segment_uid(created.uid, scroll="_scroll" in self.__dict__)

        self._run_segment_history_action("新增片段", create)
        if created is not None:
            self._mark_current_export_dirty()
            self._schedule_selected_segment_auto_audition()
        return created

    def _add_segment(
        self,
        s=_AUTO_SEGMENT,
        e=_AUTO_SEGMENT,
        speed_override=None,
        uid: str | None = None,
        link_group_id=None,
        created_order: int | None = None,
        refresh: bool = True,
        sort: bool = True,
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
        row.created_order = self._next_segment_order() if created_order is None else int(created_order)
        self._segment_order = max(self._segment_order, row.created_order)
        self._connect_segment_row(row)
        self._rows.append(row)
        self._segs_layout.addWidget(row)
        if refresh:
            self._refresh_seg_header()
            self._flush_segment_preview_refresh()
            self._schedule_segment_time_validation()
            self._schedule_arc_cut_warning_refresh()
        if sort:
            self._maybe_auto_sort_segments()
        return row

    def _remove_segment(self, row: SegmentRow) -> None:
        """Keep the card action on the same uid-based deletion path as shortcuts."""
        self._delete_segment_by_uid(getattr(row, "uid", ""))

    def _delete_segment_by_uid(self, uid: str, record_history: bool = True) -> None:
        if record_history:
            return self._run_segment_history_action("删除片段", lambda: self._delete_segment_by_uid(uid, False))
        uid = str(uid or "")
        if uid == self.__dict__.get("_selected_segment_uid", ""):
            self._cancel_selected_segment_auto_audition()
        row = self._row_by_uid(uid)
        if row is None:
            if self.__dict__.get("_selected_segment_uid", "") == uid:
                self._set_selected_segment_uid("")
            return

        row_index = self._rows.index(row)
        self._rows.remove(row)
        self._segs_layout.removeWidget(row)
        row.deleteLater()
        self._cleanup_single_member_link_groups()
        if self.__dict__.get("_hovered_segment_uid", "") == uid:
            self._hovered_segment_uid = ""
        if self.__dict__.get("_join_preview_uid", "") == uid:
            self._join_preview_uid = ""

        selection_row = None
        if self._rows:
            selection_row = self._rows[row_index] if row_index < len(self._rows) else self._rows[-1]
        for index, remaining_row in enumerate(self._rows):
            remaining_row.update_index(index + 1)
        if not self._rows:
            self._add_segment(None, None)

        self._maybe_auto_sort_segments()
        if hasattr(self, "_schedule_segment_time_validation"):
            self._schedule_segment_time_validation()
        if hasattr(self, "_schedule_arc_cut_warning_refresh"):
            self._schedule_arc_cut_warning_refresh()
        self._set_selected_segment_uid(selection_row.uid if selection_row is not None else "")
        self._mark_current_export_dirty()

    def _is_text_editing_focus(self, widget: QWidget | None = None) -> bool:
        if widget is None:
            focus_getter = getattr(QApplication, "focusWidget", None)
            current = focus_getter() if callable(focus_getter) else None
        else:
            current = widget
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            if isinstance(current, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                return True
            if isinstance(current, QComboBox) and current.isEditable():
                return True
            parent_getter = getattr(current, "parentWidget", None)
            current = parent_getter() if callable(parent_getter) else None
        return False

    def _delete_selected_segment_from_shortcut(self) -> None:
        focus_getter = getattr(QApplication, "focusWidget", None)
        focus_widget = focus_getter() if callable(focus_getter) else None
        if self._is_text_editing_focus(focus_widget):
            return
        uid = self.__dict__.get("_selected_segment_uid", "")
        if uid:
            self._delete_segment_by_uid(uid)

    def _duplicate_selected_segment_from_shortcut(self) -> None:
        focus_getter = getattr(QApplication, "focusWidget", None)
        focus_widget = focus_getter() if callable(focus_getter) else None
        if self._is_text_editing_focus(focus_widget):
            return
        uid = self.__dict__.get("_selected_segment_uid", "")
        if not uid:
            return
        row = self._row_by_uid(uid)
        if row is None:
            self._set_selected_segment_uid("")
            return
        self._copy_segment(row)

    def _save_from_shortcut(self) -> None:
        self._save_slides()

    def _copy_segment(self, row: SegmentRow, record_history: bool = True):
        if record_history:
            return self._run_segment_history_action("复制片段", lambda: self._copy_segment(row, False))
        if row not in self._rows:
            return
        source_group_id = normalize_link_group_id(getattr(row, "link_group_id", None))
        if source_group_id:
            if source_group_id in self._inconsistent_link_groups():
                start, end = self._row_time_values(row)
                if start is not None and end is not None and end > start:
                    self._set_linked_interval_values(self._linked_interval_rows(row), start, end)
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

    def _on_segment_row_changed(self, row: SegmentRow) -> None:
        if row not in getattr(self, "_rows", []):
            return
        self._mark_current_export_dirty()
        self._schedule_segment_time_validation()
        snapshot = self._row_display_snapshot(row)
        if snapshot is None or not snapshot.was_complete:
            self._schedule_segment_preview_refresh(row)

    def _schedule_segment_preview_refresh(self, row: SegmentRow | None = None) -> None:
        if self.__dict__.get("_segment_restore_in_progress", False):
            return
        snapshot = self._row_display_snapshot(row) if row is not None else None
        if snapshot is not None and snapshot.was_complete:
            return
        timer = self.__dict__.get("_segment_preview_refresh_timer")
        if timer is None:
            self._flush_segment_preview_refresh()
            return
        timer.start()

    def _flush_segment_preview_refresh(self) -> None:
        if self.__dict__.get("_segment_restore_in_progress", False):
            return
        self._refresh_seg_header()
        self._refresh_waveform_segments()

    def _schedule_arc_cut_warning_refresh(self):
        self._arc_warning_timer.start(200)

    def _schedule_segment_time_validation(self):
        self._segment_validation_timer.start(120)

    def _current_audio_path(self) -> Path | None:
        song_id = self._song_box.currentText()
        if not isinstance(song_id, str) or not song_id or "目录为空" in song_id:
            return None
        cfg = getattr(self, "_cfg", {})
        default_songs_dir = _window_dep(self, "default_songs_dir", DEFAULT_SONGS_DIR)
        raw_songs_dir = cfg.get("songs_dir", str(default_songs_dir)) if isinstance(cfg, dict) else str(default_songs_dir)
        if not isinstance(raw_songs_dir, (str, os.PathLike)):
            return None
        songs_dir = Path(raw_songs_dir)
        return songs_dir / song_id / "base.ogg"

    def _waveform_segment_ranges(self) -> list[tuple]:
        ranges: list[tuple] = []
        valid_groups = self._complete_link_groups()
        for row in getattr(self, "_rows", []):
            start_value, end_value = self._row_visual_time_values(row)
            if start_value is None or end_value is None or end_value <= start_value:
                continue
            start = int(start_value)
            end = int(end_value)
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
            snapshot = self._row_display_snapshot(row)
            if snapshot is not None and snapshot.was_complete:
                continue
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

    def _on_segment_field_committed(self, row: SegmentRow, field: str) -> bool:
        if row not in self._rows:
            return False
        if field == "speed":
            if hasattr(row, "set_speed_error"):
                speed_error = self._segment_speed_error(row)
                row.set_speed_error(speed_error)
                if speed_error:
                    self._refresh_selected_segment_audition()
                    return False
        else:
            if not self._commit_linked_interval_field(row, field):
                self._refresh_selected_segment_audition()
                return False
        self._commit_segment_edit(row, field)
        return True

    def _set_linked_interval_values(self, rows: list[SegmentRow], start: int, end: int) -> None:
        for member in rows:
            member.restore_history_texts(str(start), str(end), member.speed_override_text())

    def _commit_linked_interval_field(self, row: SegmentRow, field: str) -> bool:
        sync_values = getattr(row, "_sync_values_from_inputs", None)
        if callable(sync_values):
            sync_values()
        result = self._validate_segment_row_hard(row)
        if not result.ok:
            return False
        start, end = self._row_time_values(row)
        if start is None or end is None:
            return False
        if end - start < WAVEFORM_MIN_SEGMENT_MS:
            row.set_time_errors("", f"片段至少需要 {WAVEFORM_MIN_SEGMENT_MS}ms")
            return False

        # A valid edit of a legacy inconsistent group adopts this row's full interval.
        if field in {"start", "end"}:
            self._set_linked_interval_values(self._linked_interval_rows(row), int(start), int(end))
        return True

    def _commit_segment_edit(self, row: SegmentRow, field: str) -> None:
        if row not in self._rows:
            return
        uid = str(getattr(row, "uid", "") or "")
        snapshots = self.__dict__.setdefault("_segment_edit_display_snapshots", {})
        snapshot = snapshots.pop(uid, None)
        transactions = self.__dict__.get("_segment_history_transactions", {})
        has_transaction = f"input:{uid}:{field}" in transactions
        self._commit_segment_history_transaction(f"input:{uid}:{field}")
        if snapshot is None and has_transaction is False:
            self._maybe_auto_sort_segments()
            return
        self._maybe_auto_sort_segments()
        self._set_selected_segment_uid(uid, scroll=True)
        self._schedule_segment_time_validation()
        self._schedule_arc_cut_warning_refresh()
        self._schedule_selected_segment_auto_audition()

    def _pending_segment_edit_fields(self) -> list[tuple[SegmentRow, str]]:
        transactions = self.__dict__.get("_segment_history_transactions", {})
        pending: list[tuple[SegmentRow, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in getattr(self, "_rows", []):
            uid = str(getattr(row, "uid", "") or "")
            for field in ("start", "end", "speed"):
                key = (uid, field)
                if f"input:{uid}:{field}" in transactions:
                    pending.append((row, field))
                    seen.add(key)

        focus_getter = getattr(QApplication, "focusWidget", None)
        focused = focus_getter() if callable(focus_getter) else None
        row = self._segment_row_ancestor(focused)
        if row in getattr(self, "_rows", []):
            field = row.active_field_name() if hasattr(row, "active_field_name") else ""
            key = (str(getattr(row, "uid", "") or ""), field)
            if field and key not in seen and self._row_display_snapshot(row) is not None:
                pending.append((row, field))
        return pending

    def _commit_active_segment_edits_for_save(self) -> bool:
        for row, field in self._pending_segment_edit_fields():
            if row in getattr(self, "_rows", []) and not self._on_segment_field_committed(row, field):
                return False
        return True

    def _on_segment_edit_started(self, row: SegmentRow, field: str) -> None:
        if row in self._rows:
            if row.uid == self.__dict__.get("_selected_segment_uid", ""):
                self._cancel_selected_segment_auto_audition()
                controller = self.__dict__.get("_playback_controller")
                if controller is not None:
                    controller.stop(reset_to_start=False)
            self._capture_segment_edit_display_snapshot(row)
            self._begin_segment_history_transaction(f"input:{row.uid}:{field}", f"修改{field}")

    def _on_segment_edit_committed(self, row: SegmentRow, field: str) -> None:
        uid = str(getattr(row, "uid", "") or "")
        transactions = self.__dict__.get("_segment_history_transactions", {})
        if self._row_display_snapshot(row) is not None or f"input:{uid}:{field}" in transactions:
            self._on_segment_field_committed(row, field)

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
        self._on_segment_field_committed(row, field)
        if field == "speed":
            speed_error = self._segment_speed_error(row)
            row.set_speed_error(speed_error)
            if speed_error:
                row.focus_time_field("speed")
                return
        else:
            result = self._validate_segment_row_hard(row)
            if result.first_field == field:
                row.focus_time_field(field)
                return
            if field == "end" and result.first_field == "start":
                row.focus_time_field("start")
                return
        self._focus_next_segment_field(row, field)

    def _add_waveform_segment(self, start_ms: int, end_ms: int) -> None:
        try:
            start = int(start_ms)
            end = int(end_ms)
        except (TypeError, ValueError):
            return
        if end - start < WAVEFORM_MIN_SEGMENT_MS:
            return
        self._create_user_segment(start, end)

    def _on_timeline_quick_draft_requested(self, time_ms: int) -> None:
        try:
            point = int(time_ms)
        except (TypeError, ValueError):
            return
        panel = self.__dict__.get("_waveform_panel")
        duration = int(panel._duration_ms()) if panel is not None and hasattr(panel, "_duration_ms") else 0
        if duration <= 0:
            return
        point = max(0, min(duration, point))
        anchor = self.__dict__.get("_timeline_quick_draft_anchor_ms")
        if anchor is None:
            self._set_timeline_quick_draft_anchor(point)
            return
        start, end = sorted((int(anchor), point))
        if end - start < WAVEFORM_MIN_SEGMENT_MS:
            if "_log_widget" in self.__dict__:
                self._push_log(f"片段长度至少为 {WAVEFORM_MIN_SEGMENT_MS}ms", "muted")
            return
        if self._create_user_segment(start, end) is not None:
            self._cancel_timeline_quick_draft()

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
        cascade_rows = self._linked_interval_rows(row)
        if start_changed and end_changed:
            if end - start < WAVEFORM_MIN_SEGMENT_MS:
                return
            self._set_linked_interval_values(cascade_rows, start, end)
        elif start_changed:
            limit = int(old_end) - WAVEFORM_MIN_SEGMENT_MS
            start = max(0, min(start, limit))
            self._set_linked_interval_values(cascade_rows, start, int(old_end))
        else:
            duration_ms = int(self.__dict__.get("_audio_duration_ms") or 0)
            if duration_ms <= 0 and hasattr(self._waveform_panel, "_duration_ms"):
                duration_ms = int(self._waveform_panel._duration_ms())
            limit = int(old_start) + WAVEFORM_MIN_SEGMENT_MS
            end = max(limit, end)
            if duration_ms > 0:
                end = min(duration_ms, end)
            self._set_linked_interval_values(cascade_rows, int(old_start), end)
        self._set_selected_segment_uid(row.uid)
        self._refresh_waveform_segments()
        self._schedule_segment_time_validation()
        self._schedule_arc_cut_warning_refresh()
        self._mark_current_export_dirty()

    def _on_waveform_endpoint_committed(self) -> None:
        self._maybe_auto_sort_segments()
        self._refresh_selected_segment_audition()
        self._schedule_selected_segment_auto_audition()

    def _on_waveform_endpoint_drag_started(self, _uid: str, side: str) -> None:
        self._cancel_selected_segment_auto_audition()
        controller = self.__dict__.get("_playback_controller")
        if controller is not None:
            controller.stop(reset_to_start=False)
        self._begin_segment_history_transaction("timeline_endpoint_drag", f"拖动片段{side}")

    def _on_waveform_endpoint_drag_finished(self, _uid: str, _side: str) -> None:
        self._commit_segment_history_transaction("timeline_endpoint_drag")

    def _request_waveform_for_current_song(self) -> None:
        panel = getattr(self, "_waveform_panel", None)
        if panel is None:
            return
        self._cancel_timeline_quick_draft()
        self._waveform_generation += 1
        generation = self._waveform_generation
        self._refresh_waveform_segments()
        audio_path = self._current_audio_path()
        self._playback_controller.set_source(audio_path if audio_path is not None and audio_path.is_file() else None)
        self._refresh_selected_segment_audition()
        if audio_path is None or not audio_path.is_file():
            self._waveform_audio_path = ""
            panel.set_empty()
            return

        self._waveform_audio_path = str(audio_path)
        panel.set_loading()
        worker_cls = _window_dep(self, "waveform_worker_cls", WaveformWorker)
        worker = worker_cls(generation, audio_path)
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
            duration_probe = _window_dep(self, "duration_probe_func", probe_audio_duration_ms)
            self._audio_duration_ms = duration_probe(audio_path)
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
            message_box = _window_dep(self, "message_box_cls", QMessageBox)
            message_box.warning(self, title, full)
        except Exception:
            self._push_log(f"✗ {full}", "err")
        try:
            self._scroll.ensureWidgetVisible(row)
        except Exception:
            pass
        row.focus_time_field("speed")

    def _show_duplicate_segment_id_error(self, title: str, message: str):
        try:
            message_box = _window_dep(self, "message_box_cls", QMessageBox)
            message_box.warning(self, title, message)
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
            message_box = _window_dep(self, "message_box_cls", QMessageBox)
            message_box.warning(self, title, message)
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
            songs_dir = Path(self._cfg.get("songs_dir", str(_window_dep(self, "default_songs_dir", DEFAULT_SONGS_DIR))))
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
            find_warnings = _window_dep(self, "find_arc_warnings_func", find_nonlinear_arc_cut_warnings)
            warnings = find_warnings(aff_text, segments)
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
            if not self._commit_active_segment_edits_for_save():
                return False
            segment_error = self._first_segment_validation_error()
            if segment_error:
                _index, _row, result = segment_error
                raise ValueError(result.first_message)
            inconsistent = self._inconsistent_link_groups()
            if inconsistent:
                group_id = next(iter(inconsistent))
                raise ValueError(f"级联异常：组 {group_id} 的区间不一致，请先同步或断开。")
            data = self._collect()
            slides_path = _window_dep(self, "slides_path", SLIDES_PATH)
            slides_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self._segment_undo_stack.setClean()
            self._push_log(f"💾 已保存 → {slides_path}", "ok")
            self._saved_lbl.show()
            QTimer.singleShot(1900, self._saved_lbl.hide)
            return True
        except ValueError as ex:
            prefix = "速度无效: " if str(ex).startswith("速度") else ""
            self._push_log(f"✗ 保存失败：{prefix}{ex}", "err")
            return False
        except Exception as ex:
            self._push_log(f"✗ 保存失败: {ex}", "err")
            return False

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

        songs_dir     = Path(self._cfg.get("songs_dir", str(_window_dep(self, "default_songs_dir", DEFAULT_SONGS_DIR))))
        songlist_meta = data.get("songlist") or {}
        worker_cls = _window_dep(self, "slicer_worker_cls", SlicerWorker)
        self._worker = worker_cls(
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
        out_dir = _window_dep(self, "out_dir", OUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(out_dir)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(out_dir)])
            else:
                subprocess.run(["xdg-open", str(out_dir)])
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
        self._cancel_selected_segment_auto_audition()
        self._playback_controller.stop(reset_to_start=False)
        self._playback_controller.clear_audition_range()
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
