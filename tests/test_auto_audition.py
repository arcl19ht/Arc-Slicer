"""V2.4-B coordination tests without waiting for real wall-clock timers."""
import os
import subprocess
import sys
import unittest


_SCRIPT = r'''
import sys
import app

class Controller:
    def __init__(self): self.calls=[]; self.available=True; self.source=True
    def is_available(self): return self.available
    def has_source(self): return self.source
    def stop(self, **kwargs): self.calls.append(("stop", kwargs))
    def set_audition_range(self, *args): self.calls.append(("range", args))
    def clear_audition_range(self): self.calls.append(("clear",))
    def audition_range(self): return (1000, 3000)
    def schedule_auto_play(self): self.calls.append(("schedule",)); return self.available and self.source
    def cancel_pending_auto_play(self): self.calls.append(("cancel",))
    def toggle_play_pause(self): self.calls.append(("toggle",)); return True

class Speed:
    def text(self): return "1.0"

qapp=app.QApplication.instance() or app.QApplication([])
w=app.MainWindow.__new__(app.MainWindow); w._uid=0; w._segment_order=0; w._rows=[]; w._segment_edit_display_snapshots={}
w._speed_input=Speed(); w._audio_duration_ms=10000; w._selected_segment_uid=""; w._hovered_segment_uid=""; w._join_preview_uid=""
w._waveform_panel=app.WaveformPanel(); w._playback_controller=Controller(); w._play_pause_button=app.QPushButton(); w._audition_time_label=app.QLabel(); w._audition_speed_label=app.QLabel(); w._audition_status_label=app.QLabel(); w._refresh_segment_interaction_state=lambda:None
w._segment_history_transactions={}; w._segment_history_suspended=False; w._segment_restore_in_progress=False
w._capture_segment_history_state=lambda: None
w._auto_audition_enabled=False
w._rows=[app.SegmentRow(0,1000,3000,uid="selected")]; w._selected_segment_uid="selected"
mode=sys.argv[1]
if mode=="toggle":
    assert not app.MainWindow._auto_audition_is_enabled(w)
    app.MainWindow._set_auto_audition_enabled(w, True); assert ("schedule",) in w._playback_controller.calls
    w._playback_controller.calls.clear(); app.MainWindow._set_auto_audition_enabled(w, False); assert ("cancel",) in w._playback_controller.calls and not w._auto_audition_enabled
elif mode=="edit":
    w._auto_audition_enabled=True; app.MainWindow._on_segment_edit_started(w,w._rows[0],"start")
    assert ("cancel",) in w._playback_controller.calls and any(c[0]=="stop" for c in w._playback_controller.calls)
elif mode=="manual":
    w._auto_audition_enabled=True; app.MainWindow._toggle_selected_segment_playback(w)
    assert w._playback_controller.calls[0]==("cancel",) and ("toggle",) in w._playback_controller.calls
elif mode=="invalid":
    w._auto_audition_enabled=True; w._rows=[app.SegmentRow(0,1000,None,uid="draft")]; w._selected_segment_uid="draft"
    assert not app.MainWindow._schedule_selected_segment_auto_audition(w)
    assert ("cancel",) in w._playback_controller.calls
'''


class AutoAuditionTests(unittest.TestCase):
    def _run(self, scenario):
        env = os.environ.copy(); env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run([sys.executable, "-c", _SCRIPT, scenario], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_toggle_schedules_and_disabling_cancels(self): self._run("toggle")
    def test_edit_start_cancels_pending_and_stops_playback(self): self._run("edit")
    def test_manual_toggle_cancels_pending_first(self): self._run("manual")
    def test_draft_segment_is_not_scheduled(self): self._run("invalid")
