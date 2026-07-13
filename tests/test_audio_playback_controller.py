"""Run QtMultimedia controller fakes out of process to preserve legacy fake-Qt tests."""
import subprocess
import sys
import unittest


_SCRIPT = r'''
import math, sys, tempfile
from pathlib import Path
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtMultimedia import QMediaPlayer
from arc_slicer.playback import AudioPlaybackController
class Signal:
    def __init__(self): self.slots=[]
    def connect(self, slot): self.slots.append(slot)
    def emit(self,*args):
        for slot in list(self.slots): slot(*args)
class Timer:
    def __init__(self): self.timeout=Signal(); self.running=False
    def setInterval(self, value): self.interval=value
    def start(self): self.running=True
    def stop(self): self.running=False
class Player:
    def __init__(self):
        self.positionChanged=Signal(); self.playbackStateChanged=Signal(); self.errorOccurred=Signal()
        self.source=None; self.rate=1.; self.pos=0; self.play_calls=0; self.pause_calls=0
    def setAudioOutput(self, output): self.output=output
    def setSource(self, source): self.source=source
    def setPlaybackRate(self, rate): self.rate=rate
    def setPosition(self, position): self.pos=int(position); self.positionChanged.emit(self.pos)
    def position(self): return self.pos
    def play(self): self.play_calls+=1; self.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PlayingState)
    def pause(self): self.pause_calls+=1; self.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PausedState)
    def errorString(self): return "fake playback error"
class Output: pass
QCoreApplication.instance() or QCoreApplication([])
p=Player(); timer=Timer(); c=AudioPlaybackController(media_player=p,audio_output=Output(),boundary_timer=timer)
with tempfile.TemporaryDirectory() as root:
    audio=Path(root)/"base.ogg"; audio.touch(); c.set_source(audio)
    mode=sys.argv[1]
    if mode == "source":
        assert c.has_source(); c.set_source(Path(root)/"missing.ogg"); assert not c.has_source(); c.set_source(None); assert not c.has_source()
    elif mode == "range":
        c.set_audition_range(1000,2600,1.25); assert c.audition_range()==(1000,2600) and c.playback_rate()==1.25 and p.pos==1000
        for speed in (0,float("inf"),float("nan")): c.set_audition_range(1000,2600,speed); assert c.audition_range() is None
        c.set_audition_range(1000,1050,1); assert c.audition_range() is None
    elif mode == "play":
        c.set_audition_range(1000,2600,1.5); assert c.play() and p.pos==1000 and p.rate==1.5 and timer.running
        p.setPosition(1400); c.pause(); assert p.pos==1400 and not timer.running
        assert c.play() and p.pos==1400; p.setPosition(2800); c.pause(); assert c.play() and p.pos==1000
    elif mode == "nonloop":
        c.set_audition_range(1000,2000,1); c.set_loop_enabled(False); c.play(); done=[]; c.range_finished.connect(lambda:done.append(True))
        p.setPosition(2000); timer.timeout.emit(); assert p.pos==1000 and not timer.running and done==[True]
        timer.timeout.emit(); assert done==[True]
    elif mode == "loop":
        c.set_audition_range(1000,2000,1); c.play(); p.setPosition(2000); timer.timeout.emit(); assert p.pos==1000 and timer.running and c.is_playing()
    elif mode == "error":
        c.set_audition_range(1000,2000,1); c.clear_audition_range(); assert not c.play() and not timer.running
        errors=[]; c.error_changed.connect(errors.append); p.errorOccurred.emit(QMediaPlayer.Error.ResourceError,"ignored"); assert c.error_text()=="fake playback error" and errors==["fake playback error"] and not timer.running
    elif mode == "enums":
        c.set_audition_range(1000,2000,1); c._on_playback_state_changed(QMediaPlayer.PlaybackState.PlayingState); assert c.is_playing() and timer.running
        p.setPosition(1400); c._on_playback_state_changed(QMediaPlayer.PlaybackState.PausedState); assert c._state=="paused" and not timer.running and p.pos==1400
        c._on_playback_state_changed(QMediaPlayer.PlaybackState.StoppedState); assert c._state=="ready" and not timer.running and p.pos==1400
'''


class AudioPlaybackControllerTests(unittest.TestCase):
    def _run(self, scenario):
        result = subprocess.run([sys.executable, "-c", _SCRIPT, scenario], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_source_and_clear_source(self): self._run("source")
    def test_audition_range_validation(self): self._run("range")
    def test_play_pause_and_resume(self): self._run("play")
    def test_non_loop_boundary_finishes_once(self): self._run("nonloop")
    def test_loop_boundary_avoids_reentry(self): self._run("loop")
    def test_clear_range_and_player_error(self): self._run("error")
    def test_real_pyqt_playback_state_enums(self): self._run("enums")


if __name__ == "__main__":
    unittest.main()
