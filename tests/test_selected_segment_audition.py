"""Exercise real MainWindow audition coordination in isolated Qt processes."""
import subprocess
import sys
import unittest
import os


_SCRIPT = r'''
import sys
import app
class Controller:
    def __init__(self): self.calls=[]; self.available=True; self.source=True
    def is_available(self): return self.available
    def has_source(self): return self.source
    def stop(self, **kwargs): self.calls.append(("stop",kwargs))
    def set_audition_range(self,*args): self.calls.append(("range",args))
    def clear_audition_range(self): self.calls.append(("clear",))
    def audition_range(self):
        for call in reversed(self.calls):
            if call[0]=="range": return call[1][:2]
        return None
    def cancel_pending_auto_play(self): self.calls.append(("cancel",))
    def schedule_auto_play(self): self.calls.append(("schedule",)); return True
    def toggle_play_pause(self): self.calls.append(("toggle",)); return True
    def seek_ms(self, position): self.calls.append(("seek", position))
    def play(self): self.calls.append(("play",)); return True
class Speed:
    def text(self): return "1.0"
def window():
    w=app.MainWindow.__new__(app.MainWindow); w._uid=0; w._segment_order=0; w._rows=[]; w._segment_edit_display_snapshots={}
    w._speed_input=Speed(); w._audio_duration_ms=10000; w._selected_segment_uid=""; w._hovered_segment_uid=""; w._join_preview_uid=""
    w._waveform_panel=app.WaveformPanel(); w._playback_controller=Controller(); w._play_pause_button=app.QPushButton(); w._audition_time_label=app.QLabel(); w._audition_speed_label=app.QLabel(); w._audition_status_label=app.QLabel(); w._refresh_segment_interaction_state=lambda:None
    return w
qapp=app.QApplication.instance() or app.QApplication([])
mode=sys.argv[1]; w=window()
if mode=="complete":
    w._rows=[app.SegmentRow(0,1000,3000,speed_override=1.5,uid="a")]; app.MainWindow._set_selected_segment_uid(w,"a")
    assert ("range",(1000,3000,1.5)) in w._playback_controller.calls and w._play_pause_button.isEnabled() and w._audition_speed_label.text()=="1.5×"
elif mode=="invalid":
    w._rows=[app.SegmentRow(0,1000,None,uid="draft")]; w._selected_segment_uid="draft"; app.MainWindow._refresh_selected_segment_audition(w)
    assert ("clear",) in w._playback_controller.calls and not w._play_pause_button.isEnabled()
    w._rows=[app.SegmentRow(0,1000,3000,uid="a")]; w._selected_segment_uid="a"; w._playback_controller.source=False; app.MainWindow._refresh_selected_segment_audition(w); assert not w._play_pause_button.isEnabled()
elif mode=="switch":
    w._rows=[app.SegmentRow(0,1000,3000,uid="a"),app.SegmentRow(1,4000,6000,speed_override=.75,uid="b")]; app.MainWindow._set_selected_segment_uid(w,"a"); w._playback_controller.calls.clear(); app.MainWindow._set_selected_segment_uid(w,"b")
    assert w._playback_controller.calls[0][0]=="stop" and ("range",(4000,6000,.75)) in w._playback_controller.calls and not any(c[0]=="play" for c in w._playback_controller.calls)
elif mode=="short_preview":
    w._preview_audio_filename="3.ogg"; w._preview_audio_duration_ms=2000; w._rows=[app.SegmentRow(0,1000,3000,uid="a")]; w._selected_segment_uid="a"
    app.MainWindow._refresh_selected_segment_audition(w)
    assert ("clear",) in w._playback_controller.calls and "3.ogg" in w._audition_status_label.text() and not w._play_pause_button.isEnabled()
    w._auto_audition_enabled=True; w._playback_controller.calls.clear(); assert not app.MainWindow._schedule_selected_segment_auto_audition(w); assert ("cancel",) in w._playback_controller.calls
    app.MainWindow._on_waveform_segment_seek_requested(w,"a",1500); assert not any(c[0] in {"seek","play"} for c in w._playback_controller.calls)
elif mode=="base_restored":
    w._audio_duration_ms=10000; w._preview_audio_filename="base.ogg"; w._preview_audio_duration_ms=10000; w._rows=[app.SegmentRow(0,1000,3000,uid="a")]; w._selected_segment_uid="a"
    app.MainWindow._refresh_selected_segment_audition(w)
    assert ("range",(1000,3000,1.0)) in w._playback_controller.calls and w._audio_duration_ms==10000
'''


class SelectedSegmentAuditionTests(unittest.TestCase):
    def _run(self, scenario):
        env = os.environ.copy(); env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run([sys.executable, "-c", _SCRIPT, scenario], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_complete_selected_segment_uses_effective_speed(self): self._run("complete")
    def test_draft_or_missing_source_disables_audition(self): self._run("invalid")
    def test_selection_change_stops_and_replaces_range(self): self._run("switch")
    def test_short_preview_blocks_manual_auto_and_timeline_seek(self): self._run("short_preview")
    def test_base_preview_restores_range_without_changing_canonical_duration(self): self._run("base_restored")


if __name__ == "__main__":
    unittest.main()
