"""Qt Multimedia backed audition playback for one selected segment."""
from __future__ import annotations

import math
from pathlib import Path

try:
    from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
except ImportError:
    from PyQt6.QtCore import QTimer, pyqtSignal
    class QObject:
        def __init__(self, *_args, **_kwargs): pass
    class QUrl:
        @staticmethod
        def fromLocalFile(path): return path

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    QT_MULTIMEDIA_AVAILABLE = True
except ImportError:
    QAudioOutput = None
    QMediaPlayer = None
    QT_MULTIMEDIA_AVAILABLE = False


class AudioPlaybackController(QObject):
    position_changed = pyqtSignal(int)
    state_changed = pyqtSignal(str)
    availability_changed = pyqtSignal(bool)
    error_changed = pyqtSignal(str)
    range_finished = pyqtSignal()

    def __init__(self, parent=None, *, media_player=None, audio_output=None, boundary_timer=None):
        super().__init__(parent)
        self._player = media_player
        self._output = audio_output
        self._timer = boundary_timer or QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._check_boundary)
        self._range: tuple[int, int] | None = None
        self._rate = 1.0
        self._loop = True
        self._state = "unavailable" if not QT_MULTIMEDIA_AVAILABLE and media_player is None else "idle"
        self._error = "当前环境不支持音频播放" if self._state == "unavailable" else ""
        self._handling_boundary = False
        if self._player is None and QT_MULTIMEDIA_AVAILABLE:
            self._player = QMediaPlayer(self)
        if self._output is None and QT_MULTIMEDIA_AVAILABLE:
            self._output = QAudioOutput(self)
        if self._player is not None and self._output is not None and hasattr(self._player, "setAudioOutput"):
            self._player.setAudioOutput(self._output)
        if self._player is not None:
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.playbackStateChanged.connect(self._on_playback_state_changed)
            self._player.errorOccurred.connect(self._on_error)
        self.availability_changed.emit(self.is_available())
        self.state_changed.emit(self._state)

    def is_available(self) -> bool: return self._player is not None and self._state != "unavailable"
    def error_text(self) -> str: return self._error
    def audition_range(self): return self._range
    def playback_rate(self) -> float: return self._rate
    def is_playing(self) -> bool: return self._state == "playing"
    def position_ms(self) -> int: return int(self._player.position()) if self._player is not None else 0

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state; self.state_changed.emit(state)

    def set_source(self, path: Path | None) -> None:
        self.stop(reset_to_start=False); self.clear_audition_range()
        if not self.is_available(): return
        path = Path(path) if path else None
        if path is None or not path.is_file():
            self._set_state("idle"); return
        self._player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self._set_state("ready")

    def set_audition_range(self, start_ms: int, end_ms: int, speed: float) -> None:
        if not self.is_available() or start_ms < 0 or end_ms - start_ms < 100 or not math.isfinite(speed) or speed <= 0:
            self.clear_audition_range(); return
        self.stop(reset_to_start=False); self._range = (int(start_ms), int(end_ms)); self._rate = float(speed)
        self._player.setPlaybackRate(self._rate); self._player.setPosition(self._range[0]); self._set_state("ready")

    def clear_audition_range(self) -> None:
        self.stop(reset_to_start=False); self._range = None
        if self.is_available(): self._set_state("idle")

    def set_loop_enabled(self, enabled: bool) -> None: self._loop = bool(enabled)
    def play(self) -> bool:
        if not self.is_available() or self._range is None: return False
        start, end = self._range
        if not start <= self.position_ms() < end: self._player.setPosition(start)
        self._player.setPlaybackRate(self._rate); self._player.play(); self._timer.start(); self._set_state("playing"); return True
    def pause(self) -> None:
        if self._player is not None: self._player.pause()
        self._timer.stop()
        if self._range is not None: self._set_state("paused")
    def toggle_play_pause(self) -> bool:
        if self.is_playing(): self.pause(); return False
        return self.play()
    def stop(self, *, reset_to_start: bool = True) -> None:
        self._timer.stop()
        if self._player is not None: self._player.pause()
        if reset_to_start and self._range is not None and self._player is not None: self._player.setPosition(self._range[0])
        if self.is_available() and self._range is not None: self._set_state("ready")
    def seek_ms(self, position_ms: int) -> None:
        if self._player is not None: self._player.setPosition(int(position_ms))

    def _on_position_changed(self, position: int) -> None:
        self.position_changed.emit(int(position))
    def _on_playback_state_changed(self, state) -> None:
        if self._state == "playing" and int(state) == 0: self._timer.stop(); self._set_state("paused")
    def _on_error(self, *_args) -> None:
        self._timer.stop(); self._error = self._player.errorString() if self._player is not None else "音频播放失败"
        self.error_changed.emit(self._error); self._set_state("error")
    def _check_boundary(self) -> None:
        if self._handling_boundary or self._range is None or self.position_ms() < self._range[1]: return
        self._handling_boundary = True
        try:
            start, _ = self._range
            if self._loop: self._player.setPosition(start)
            else:
                self._player.pause(); self._player.setPosition(start); self._timer.stop(); self._set_state("ready"); self.range_finished.emit()
        finally: self._handling_boundary = False
