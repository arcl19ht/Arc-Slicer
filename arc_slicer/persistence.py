"""Runtime persistence and legacy data migration helpers."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from arc_slicer.paths import APP_DIR, CONFIG_PATH, DATA_ROOT, DEFAULT_SONGS_DIR, SLIDES_PATH

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


def load_config(path: Path = CONFIG_PATH) -> dict:
    path = Path(path)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"songs_dir": str(DEFAULT_SONGS_DIR)}


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> None:
    Path(path).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


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


def load_json_file(path: Path, default):
    path = Path(path)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def save_json_file(path: Path, data) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_slides(path: Path, default=None):
    return load_json_file(path, [] if default is None else default)


def save_slides(path: Path, data) -> None:
    save_json_file(path, data)


def normalize_loaded_segment(data: dict) -> dict:
    item = dict(data or {})
    if "uid" not in item or not item.get("uid"):
        item["uid"] = f"seg_{uuid.uuid4().hex[:10]}"
    if "speed_override" not in item:
        item["speed_override"] = None
    if not item.get("link_group_id"):
        item["link_group_id"] = None
    return item
