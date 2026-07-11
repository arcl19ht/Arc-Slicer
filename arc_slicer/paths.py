"""Runtime path helpers for Arc Slicer."""
from __future__ import annotations

import sys
from pathlib import Path

APP_DATA_DIRNAME = "ArcSlicerData"

def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _res_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def _data_root_for_app_dir(app_dir: Path, frozen: bool | None = None) -> Path:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen and app_dir.name.lower() == "dist":
        return app_dir.parent / APP_DATA_DIRNAME
    return app_dir / APP_DATA_DIRNAME


def resolve_runtime_paths(
    app_file: Path | None = None,
    executable_path: Path | None = None,
    frozen: bool | None = None,
) -> dict[str, Path]:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        app_dir = Path(executable_path or sys.executable).parent
    else:
        app_dir = Path(app_file or __file__).parent
    res_dir = _res_dir() if app_file is None and executable_path is None else app_dir
    data_root = _data_root_for_app_dir(app_dir, frozen)
    return {
        "app_dir": app_dir,
        "res_dir": res_dir,
        "data_root": data_root,
        "songs_dir": data_root / "songs",
        "out_dir": data_root / "out",
        "config_path": data_root / "config.json",
        "slides_path": data_root / "slides.json",
    }

APP_DIR     = _app_dir()
BASE_DIR    = APP_DIR
RES_DIR     = _res_dir()
DATA_ROOT   = _data_root_for_app_dir(APP_DIR)
DEFAULT_SONGS_DIR = DATA_ROOT / "songs"
OUT_DIR     = DATA_ROOT / "out"
CURRENT_EXPORT_ROOT = OUT_DIR / "current_export"
CURRENT_EXPORT_SONGS_DIR = CURRENT_EXPORT_ROOT / "songs"
LIBRARY_EXPORT_ROOT = OUT_DIR / "library_export"
LIBRARY_EXPORT_SONGS_DIR = LIBRARY_EXPORT_ROOT / "songs"
EXTERNAL_MERGE_BACKUP_ROOT = DATA_ROOT / "backups" / "external_merge"
EXTERNAL_MERGE_TARGET_CONFIG_KEY = "external_merge_target_songs_dir"
WAVEFORM_CACHE_DIR = DATA_ROOT / "cache" / "waveforms"
CONFIG_PATH = DATA_ROOT / "config.json"
SLIDES_PATH = DATA_ROOT / "slides.json"
SONGLIST_EXAMPLE_PATH = APP_DIR / "songlist_example.json"
_FFMPEG_BUNDLED = RES_DIR / "ffmpeg.exe"

def current_export_root(out_dir: Path | None = None) -> Path:
    return Path(out_dir or OUT_DIR) / "current_export"


def current_export_songs_dir(out_dir: Path | None = None) -> Path:
    return current_export_root(out_dir) / "songs"


def library_export_root(out_dir: Path | None = None) -> Path:
    return Path(out_dir or OUT_DIR) / "library_export"


def library_export_songs_dir(out_dir: Path | None = None) -> Path:
    return library_export_root(out_dir) / "songs"
