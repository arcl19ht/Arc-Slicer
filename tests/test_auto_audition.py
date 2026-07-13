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

class Scroll:
    def __init__(self): self.value=173; self.calls=[]
    def ensureWidgetVisible(self, row): self.calls.append(row.uid); self.value=0

qapp=app.QApplication.instance() or app.QApplication([])
w=app.MainWindow.__new__(app.MainWindow); w._uid=0; w._segment_order=0; w._rows=[]; w._segment_edit_display_snapshots={}
w._speed_input=Speed(); w._audio_duration_ms=10000; w._selected_segment_uid=""; w._hovered_segment_uid=""; w._join_preview_uid=""
w._waveform_panel=app.WaveformPanel(); w._scroll=Scroll(); w._playback_controller=Controller(); w._play_pause_button=app.QPushButton(); w._audition_time_label=app.QLabel(); w._audition_speed_label=app.QLabel(); w._audition_status_label=app.QLabel(); w._refresh_segment_interaction_state=lambda:None
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
elif mode=="card":
    w._auto_audition_enabled=True; w._playback_controller.calls.clear()
    app.MainWindow._on_segment_row_selected(w,w._rows[0])
    assert w._selected_segment_uid=="selected"
    assert [call[0] for call in w._playback_controller.calls]==["stop","range","schedule"]
elif mode=="timeline":
    w._auto_audition_enabled=True; w._playback_controller.calls.clear()
    app.MainWindow._on_waveform_segment_selected(w,"selected")
    assert w._selected_segment_uid=="selected"
    assert [call[0] for call in w._playback_controller.calls]==["stop","range","schedule"]
    assert w._scroll.value==173 and not w._scroll.calls
elif mode=="off":
    w._auto_audition_enabled=False; w._playback_controller.calls.clear()
    app.MainWindow._on_waveform_segment_selected(w,"selected")
    assert [call[0] for call in w._playback_controller.calls]==["stop","range"]
    assert w._scroll.value==173 and not w._scroll.calls
elif mode=="reselect":
    w._auto_audition_enabled=True; w._playback_controller.calls.clear()
    app.MainWindow._on_segment_row_selected(w,w._rows[0]); app.MainWindow._on_segment_row_selected(w,w._rows[0])
    assert [call[0] for call in w._playback_controller.calls]==["stop","range","schedule","stop","range","schedule"]
elif mode=="rapid":
    w._auto_audition_enabled=True; w._rows=[app.SegmentRow(0,1000,3000,uid="a"),app.SegmentRow(1,4000,6000,uid="b"),app.SegmentRow(2,7000,9000,uid="c")]
    w._playback_controller.calls.clear()
    for row in w._rows: app.MainWindow._on_waveform_segment_selected(w,row.uid)
    assert w._selected_segment_uid=="c"
    assert w._playback_controller.calls[-2:]==[("range",(7000,9000,1.0)),("schedule",)]
    assert w._scroll.value==173 and not w._scroll.calls
elif mode=="selected_draft":
    w._auto_audition_enabled=True; draft=app.SegmentRow(0,1000,None,uid="draft"); w._rows=[draft]; w._playback_controller.calls.clear()
    app.MainWindow._on_waveform_segment_selected(w,"draft")
    assert ("schedule",) not in w._playback_controller.calls and ("cancel",) in w._playback_controller.calls
    assert w._scroll.value==173 and not w._scroll.calls
elif mode=="unavailable":
    w._auto_audition_enabled=True; w._playback_controller.source=False; w._playback_controller.calls.clear()
    app.MainWindow._on_segment_row_selected(w,w._rows[0])
    assert ("schedule",) not in w._playback_controller.calls and ("cancel",) in w._playback_controller.calls
elif mode=="out_of_bounds":
    w._auto_audition_enabled=True; w._rows=[app.SegmentRow(0,9000,11000,uid="late")]; w._playback_controller.calls.clear()
    app.MainWindow._on_segment_row_selected(w,w._rows[0])
    assert ("schedule",) not in w._playback_controller.calls and ("cancel",) in w._playback_controller.calls
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
    def test_card_selection_refreshes_then_schedules(self): self._run("card")
    def test_timeline_selection_refreshes_then_schedules(self): self._run("timeline")
    def test_selection_does_not_schedule_when_disabled(self): self._run("off")
    def test_reselecting_the_same_segment_reschedules(self): self._run("reselect")
    def test_rapid_selection_ends_with_the_last_range_scheduled(self): self._run("rapid")
    def test_draft_card_selection_cancels_without_scheduling(self): self._run("selected_draft")
    def test_missing_source_cancels_without_scheduling(self): self._run("unavailable")
    def test_out_of_bounds_selection_cancels_without_scheduling(self): self._run("out_of_bounds")
