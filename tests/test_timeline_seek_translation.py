import os
import subprocess
import sys
import unittest

import app
from arc_slicer.ui.segment_history import QUndoStack

Qt = app.Qt


class _Layout:
    def __init__(self): self.widgets = []
    def addWidget(self, widget): self.widgets.append(widget)
    def insertWidget(self, index, widget): self.widgets.insert(index, widget)
    def removeWidget(self, widget): self.widgets.remove(widget)


class _Speed:
    def text(self): return "1.0"


class _Scroll:
    def __init__(self): self.value = 211; self.calls = []
    def ensureWidgetVisible(self, row): self.calls.append(row.uid); self.value = 0


class _Controller:
    def __init__(self):
        self.calls = []
        self._range = None
    def is_available(self): return True
    def has_source(self): return True
    def audition_range(self): return self._range
    def stop(self, **_kwargs): self.calls.append(("stop",))
    def set_audition_range(self, start, end, speed):
        self._range = (start, end); self.calls.append(("range", start, end, speed))
    def clear_audition_range(self): self._range = None; self.calls.append(("clear",))
    def cancel_pending_auto_play(self): self.calls.append(("cancel",))
    def seek_ms(self, position): self.calls.append(("seek", position))
    def play(self): self.calls.append(("play",)); return True
    def schedule_auto_play(self): self.calls.append(("schedule",)); return True


class _Mouse:
    def __init__(self, x, y, button, modifiers=Qt.KeyboardModifier.NoModifier):
        self._point = type("Point", (), {"x": lambda _self: x, "y": lambda _self: y})()
        self._button = button
        self._modifiers = modifiers
        self.accepted = False

    def button(self): return self._button
    def modifiers(self): return self._modifiers
    def position(self): return self._point
    def accept(self): self.accepted = True


def _mouse(_event_type, x, y, *, button, buttons=Qt.MouseButton.NoButton):
    return _Mouse(x, y, button)


class _TimelineSeekAndTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = app.QApplication.instance() or app.QApplication([])

    def _panel(self, duration_ms=100000):
        panel = app.WaveformPanel()
        panel.resize(1024, 220)
        panel.set_waveform(app.WaveformData(duration_ms, 100, [(-0.2, 0.2)] * 100))
        return panel

    def _point(self, panel, time_ms, lane=0):
        return (
            panel._waveform_rect().left() + panel.time_ms_to_x(time_ms),
            panel._lane_rect(lane).top() + 8,
        )

    def _window(self, panel, *, auto_audition=False):
        win = app.MainWindow.__new__(app.MainWindow)
        win._uid = 0; win._segment_order = 1; win._rows = [app.SegmentRow(0, 10000, 20000, uid="a")]
        win._segs_layout = _Layout(); win._segs_layout.addWidget(win._rows[0]); win._speed_input = _Speed(); win._audio_duration_ms = 100000
        win._selected_segment_uid = "a"; win._hovered_segment_uid = ""; win._join_preview_uid = ""
        win._waveform_panel = panel; win._scroll = _Scroll(); win._playback_controller = _Controller()
        win._play_pause_button = app.QPushButton(); win._audition_time_label = app.QLabel()
        win._audition_speed_label = app.QLabel(); win._audition_status_label = app.QLabel()
        win._auto_audition_enabled = auto_audition; win._auto_sort_enabled = False; win._sort_mode = "manual"
        win._current_source_id = "song"; win._segment_edit_display_snapshots = {}; win._segment_history_transactions = {}
        win._segment_history_suspended = False; win._segment_restore_in_progress = False
        win._segment_undo_stack = QUndoStack(); win._segment_undo_stack.setClean()
        win._refresh_seg_header = lambda: None; win._refresh_segment_interaction_state = lambda: panel.set_selection_state("a", "")
        win._validation_calls = []; win._arc_calls = []; win._dirty_calls = []
        win._schedule_segment_time_validation = lambda: win._validation_calls.append(True)
        win._schedule_arc_cut_warning_refresh = lambda: win._arc_calls.append(True)
        win._mark_current_export_dirty = lambda *args: win._dirty_calls.append(True)
        app.MainWindow._refresh_waveform_segments(win)
        panel.set_selection_state("a", "")
        win._waveform_test_connections = [
            lambda uid: app.MainWindow._on_waveform_segment_selected(win, uid),
            lambda uid, position: app.MainWindow._on_waveform_segment_seek_requested(win, uid, position),
            lambda index, start, end: app.MainWindow._update_waveform_segment_endpoint(win, index, start, end),
            lambda: app.MainWindow._on_waveform_endpoint_committed(win),
            lambda uid, side: app.MainWindow._on_waveform_endpoint_drag_started(win, uid, side),
            lambda uid, side: app.MainWindow._on_waveform_endpoint_drag_finished(win, uid, side),
        ]
        panel.segmentSelected.connect(win._waveform_test_connections[0])
        panel.segmentSeekRequested.connect(win._waveform_test_connections[1])
        panel.segmentEndpointChanged.connect(win._waveform_test_connections[2])
        panel.segmentEndpointCommitted.connect(win._waveform_test_connections[3])
        panel.segmentEndpointDragStarted.connect(win._waveform_test_connections[4])
        panel.segmentEndpointDragFinished.connect(win._waveform_test_connections[5])
        return win

    def test_unselected_body_only_selects_and_selected_body_click_seeks_without_scrolling(self):
        panel = self._panel()
        panel.set_segments([(10000, 20000, "a", (10000, 20000)), (30000, 40000, "b", (30000, 40000))])
        selected, seeks = [], []
        panel.segmentSelected.connect(selected.append)
        panel.segmentSeekRequested.connect(lambda uid, position: seeks.append((uid, position)))
        x, y = self._point(panel, 35000, 1)
        panel._begin_interaction_at_pos(x, y)
        self.assertEqual(selected, ["b"])
        self.assertEqual(seeks, [])

        panel.set_selection_state("b", "")
        x, y = self._point(panel, 36000, 1)
        panel.mousePressEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton))
        panel.mouseReleaseEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton))
        self.assertEqual(seeks, [("b", 36000)])
        self.assertEqual(panel.segment_ranges()[1], (30000, 40000))

    def test_endpoint_has_priority_over_selected_body_seek(self):
        panel = self._panel(); panel.set_segments([(10000, 20000, "a", (10000, 20000))]); panel.set_selection_state("a", "")
        seeks, changed = [], []
        panel.segmentSeekRequested.connect(lambda uid, position: seeks.append((uid, position)))
        panel.segmentEndpointChanged.connect(lambda *args: changed.append(args))
        x, y = self._point(panel, 10000)
        panel.mousePressEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton))
        panel.mouseReleaseEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton))
        self.assertEqual(seeks, [])
        self.assertEqual(changed, [(0, 10000, 20000)])

    def test_selected_body_drag_translates_once_and_clamps_without_seek(self):
        panel = self._panel(); win = self._window(panel, auto_audition=True)
        x, y = self._point(panel, 15000)
        panel.mousePressEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton))
        move_x, _ = self._point(panel, 18000)
        panel.mouseMoveEvent(_mouse(None, move_x, y, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton))
        panel.mouseReleaseEvent(_mouse(None, move_x, y, button=Qt.MouseButton.LeftButton))
        row = win._rows[0]
        self.assertEqual((row.s_val, row.e_val), (13000, 23000))
        self.assertEqual(row.e_val - row.s_val, 10000)
        self.assertEqual(win._segment_undo_stack.count(), 1)
        self.assertEqual(len(win._dirty_calls), 1)
        self.assertEqual(len(win._validation_calls), 1)
        self.assertEqual(len(win._arc_calls), 1)
        self.assertEqual([call[0] for call in win._playback_controller.calls].count("schedule"), 1)
        self.assertNotIn("seek", [call[0] for call in win._playback_controller.calls])
        self.assertEqual(win._scroll.value, 211)
        self.assertEqual(win._scroll.calls, [])
        win._segment_undo_stack.undo()
        self.assertEqual((win._rows[0].s_val, win._rows[0].e_val), (10000, 20000))
        win._segment_undo_stack.redo()
        self.assertEqual((win._rows[0].s_val, win._rows[0].e_val), (13000, 23000))

        panel.set_selection_state("a", "")
        x, y = self._point(panel, 15000)
        panel.mousePressEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton))
        left_x, _ = self._point(panel, 0)
        panel.mouseMoveEvent(_mouse(None, left_x, y, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton))
        panel.mouseReleaseEvent(_mouse(None, left_x, y, button=Qt.MouseButton.LeftButton))
        self.assertEqual((win._rows[0].s_val, win._rows[0].e_val), (0, 10000))

        panel.set_selection_state("a", "")
        x, y = self._point(panel, 5000)
        panel.mousePressEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton))
        right_x, _ = self._point(panel, 99999)
        panel.mouseMoveEvent(_mouse(None, right_x, y, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton))
        panel.mouseReleaseEvent(_mouse(None, right_x, y, button=Qt.MouseButton.LeftButton))
        self.assertEqual((win._rows[0].s_val, win._rows[0].e_val), (90000, 100000))

    def test_linked_body_drag_moves_the_full_group_with_one_history_command(self):
        panel = self._panel(); win = self._window(panel)
        first = win._rows[0]
        first.link_group_id = "grp_a"; first._speed_override.setText("0.8")
        second = app.SegmentRow(1, 10000, 20000, speed_override=1.2, uid="b", link_group_id="grp_a")
        second.created_order = 2
        win._rows.append(second); win._segs_layout.addWidget(second); win._segment_order = 2
        app.MainWindow._refresh_waveform_segments(win)
        panel.set_selection_state("a", "")
        x, y = self._point(panel, 15000, 0)
        panel.mousePressEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton))
        move_x, _ = self._point(panel, 18000, 0)
        panel.mouseMoveEvent(_mouse(None, move_x, y, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton))
        panel.mouseReleaseEvent(_mouse(None, move_x, y, button=Qt.MouseButton.LeftButton))
        self.assertEqual([(row.s_val, row.e_val) for row in win._rows], [(13000, 23000), (13000, 23000)])
        self.assertEqual([row.link_group_id for row in win._rows], ["grp_a", "grp_a"])
        self.assertEqual([row.speed_override_text() for row in win._rows], ["0.8", "1.2"])
        self.assertEqual(win._segment_undo_stack.count(), 1)
        win._segment_undo_stack.undo()
        self.assertEqual([(row.s_val, row.e_val) for row in win._rows], [(10000, 20000), (10000, 20000)])
        win._segment_undo_stack.redo()
        self.assertEqual([(row.s_val, row.e_val) for row in win._rows], [(13000, 23000), (13000, 23000)])

    def test_selected_body_click_cancels_auto_play_then_seeks_and_plays(self):
        panel = self._panel(); win = self._window(panel, auto_audition=True)
        win._playback_controller._range = (10000, 20000)
        x, y = self._point(panel, 16000)
        panel.mousePressEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton))
        panel.mouseReleaseEvent(_mouse(None, x, y, button=Qt.MouseButton.LeftButton))
        self.assertEqual(win._playback_controller.calls[-3:], [("cancel",), ("seek", 16000), ("play",)])
        self.assertEqual((win._rows[0].s_val, win._rows[0].e_val), (10000, 20000))
        self.assertEqual(win._segment_undo_stack.count(), 0)
        self.assertEqual(win._dirty_calls, [])
        self.assertEqual(win._scroll.value, 211)


_TimelineSeekAndTranslationTests.__test__ = os.environ.get("ARC_SLICER_TIMELINE_GESTURE_CHILD") == "1"

if os.environ.get("ARC_SLICER_TIMELINE_GESTURE_CHILD") == "1":
    TimelineSeekAndTranslationTests = _TimelineSeekAndTranslationTests
else:
    class TimelineSeekAndTranslationTests(unittest.TestCase):
        def test_real_qt_gesture_suite_runs_in_clean_process(self):
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["ARC_SLICER_TIMELINE_GESTURE_CHILD"] = "1"
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", __file__],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
