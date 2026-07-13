"""QThread worker implementations for Arc Slicer."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

import external_merge
from arc_slicer.exports import effective_library_export_enabled, effective_packlist_export_enabled
from arc_slicer.paths import EXTERNAL_MERGE_BACKUP_ROOT
from arc_slicer.waveform import DEFAULT_WAVEFORM_SAMPLES_PER_SECOND


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
        waveform_loader=None,
    ):
        super().__init__()
        self.generation = int(generation)
        self.audio_path = Path(audio_path)
        self.samples_per_second = int(samples_per_second)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.waveform_loader = waveform_loader

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            if self.waveform_loader is None:
                from arc_slicer.waveform import load_or_generate_waveform

                self.waveform_loader = load_or_generate_waveform
            data = self.waveform_loader(self.audio_path, self.samples_per_second, self.cache_dir)
            if self.isInterruptionRequested():
                return
            self.done_signal.emit(self.generation, str(self.audio_path), data, "")
        except Exception as ex:
            if self.isInterruptionRequested():
                return
            self.done_signal.emit(self.generation, str(self.audio_path), None, str(ex))


class SlicerWorker(QThread):
    log_signal = pyqtSignal(str, str)
    done_signal = pyqtSignal(int)

    def __init__(
        self,
        songs_dir: Path,
        song_id: str,
        segments: list,
        speed: float,
        songlist_meta: dict | None = None,
        songlist_enabled: bool = False,
        song_template=None,
        current_export_enabled: bool = True,
        library_export_enabled: bool = True,
        packlist_enabled: bool = False,
        pack_template=None,
        slice_fn=None,
        packlist_enabled_fn=effective_packlist_export_enabled,
        library_enabled_fn=effective_library_export_enabled,
        *,
        selected_difficulties=None,
        difficulty_metadata=None,
    ):
        super().__init__()
        self.songs_dir = songs_dir
        self.song_id = song_id
        self.segments = segments
        self.speed = speed
        self.songlist_meta = songlist_meta
        self.songlist_enabled = songlist_enabled
        self.song_template = song_template
        self.current_export_enabled = current_export_enabled
        self.library_export_enabled = library_export_enabled
        self.packlist_enabled = packlist_enabled
        self.pack_template = pack_template
        self.selected_difficulties = selected_difficulties
        self.difficulty_metadata = difficulty_metadata
        self.slice_fn = slice_fn
        self.packlist_enabled_fn = packlist_enabled_fn
        self.library_enabled_fn = library_enabled_fn

    def run(self):
        def log(text, kind="normal"):
            self.log_signal.emit(text, kind)

        if self.slice_fn is None:
            from arc_slicer.exports import do_slice

            self.slice_fn = do_slice

        log(f"  songs dir: {self.songs_dir}", "muted")
        log(f"  song: {self.song_id}  default speed: {self.speed}  segments: {len(self.segments)}", "muted")
        if self.songlist_enabled:
            log("  songlist export: enabled", "muted")
        if self.packlist_enabled_fn(self.packlist_enabled, self.songlist_enabled):
            log("  packlist export: enabled", "muted")
        log(
            f"  export targets: current={'on' if self.current_export_enabled else 'off'} "
            f"library={'on' if self.library_enabled_fn(self.library_export_enabled, self.songlist_enabled) else 'off'}",
            "muted",
        )
        code = self.slice_fn(
            self.songs_dir,
            self.song_id,
            self.segments,
            self.speed,
            log,
            self.songlist_meta,
            self.songlist_enabled,
            self.song_template,
            self.current_export_enabled,
            self.library_export_enabled,
            self.packlist_enabled,
            self.pack_template,
            self.selected_difficulties,
            self.difficulty_metadata,
        )
        if code == 0:
            log("all done: out/current_export/songs/", "ok")
        self.done_signal.emit(code)
