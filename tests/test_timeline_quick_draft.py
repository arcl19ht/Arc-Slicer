import unittest

import app
from arc_slicer.ui.segment_history import QUndoStack


class _Layout:
    def __init__(self): self.widgets = []
    def addWidget(self, widget): self.widgets.append(widget)
    def insertWidget(self, index, widget): self.widgets.insert(index, widget)
    def removeWidget(self, widget):
        if widget in self.widgets: self.widgets.remove(widget)


class _Speed:
    def text(self): return "1.0"


class _Scroll:
    def ensureWidgetVisible(self, _widget): pass


class _MousePress:
    def __init__(self, x, y, modifiers):
        self._point = type("Point", (), {"x": lambda _self: x, "y": lambda _self: y})()
        self._modifiers = modifiers
        self.accepted = False

    def button(self): return app.Qt.MouseButton.LeftButton
    def modifiers(self): return self._modifiers
    def position(self): return self._point
    def accept(self): self.accepted = True


class _CaptureSignal:
    def __init__(self): self._callbacks = []
    def connect(self, callback): self._callbacks.append(callback)
    def emit(self, *args):
        for callback in list(self._callbacks): callback(*args)


def _window():
    win = app.MainWindow.__new__(app.MainWindow)
    win._uid = 0; win._segment_order = 0; win._rows = []
    win._segs_layout = _Layout(); win._speed_input = _Speed(); win._scroll = _Scroll()
    win._waveform_panel = app.WaveformPanel(); win._waveform_panel.resize(1024, 220)
    win._waveform_panel.set_waveform(app.WaveformData(100000, 100, [(-0.2, 0.2)] * 100))
    win._selected_segment_uid = ""; win._hovered_segment_uid = ""; win._join_preview_uid = ""
    win._timeline_quick_draft_anchor_ms = None
    win._auto_sort_enabled = False; win._sort_mode = "manual"; win._audio_duration_ms = 100000
    win._refresh_seg_header = lambda: None; win._schedule_segment_time_validation = lambda: None
    win._schedule_arc_cut_warning_refresh = lambda: None
    win._dirty_marked = False; win._invalidated = False
    win._mark_current_export_dirty = lambda *args: (setattr(win, "_dirty_marked", True), setattr(win, "_invalidated", True))
    win._current_source_id = "song_a"; win._segment_history_suspended = False
    win._segment_history_transactions = {}; win._segment_restore_in_progress = False
    win._segment_edit_display_snapshots = {}; win._segment_undo_stack = QUndoStack(); win._segment_undo_stack.setClean()
    return win


class TimelineQuickDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def _timeline_event(self, panel, time_ms, modifiers):
        return _MousePress(
            panel._timeline_area_rect().left() + panel.time_ms_to_x(time_ms),
            panel._timeline_area_rect().top() + 5,
            modifiers,
        )

    @staticmethod
    def _connect_quick_draft(panel, callback):
        signal = panel.timeline_quick_draft_requested
        if type(signal).__name__ == "_FakeSignal":
            signal = _CaptureSignal()
            panel.timeline_quick_draft_requested = signal
        signal.connect(callback)
        return signal

    def test_mouse_ctrl_click_signal_drives_anchor_create_undo_redo_and_escape(self):
        win = _window(); panel = win._waveform_panel
        signal = self._connect_quick_draft(panel,
            lambda time_ms: app.MainWindow._on_timeline_quick_draft_requested(win, time_ms)
        )

        first = self._timeline_event(panel, 50000, app.Qt.KeyboardModifier.ControlModifier)
        if type(signal).__name__ == "_CaptureSignal" and type(app.Qt).__name__ == "_Fake":
            panel._request_timeline_quick_draft(first.position().x(), first.position().y())
        else:
            panel.mousePressEvent(first)
        if type(app.Qt).__name__ != "_Fake":
            self.assertTrue(first.accepted)
        self.assertEqual(win._timeline_quick_draft_anchor_ms, 50000)
        self.assertEqual(panel.quick_draft_anchor_ms(), 50000)
        self.assertEqual(len(win._rows), 0); self.assertFalse(win._dirty_marked)
        self.assertEqual(win._segment_undo_stack.count(), 0)

        second = self._timeline_event(panel, 60000, app.Qt.KeyboardModifier.ControlModifier)
        if type(signal).__name__ == "_CaptureSignal" and type(app.Qt).__name__ == "_Fake":
            panel._request_timeline_quick_draft(second.position().x(), second.position().y())
        else:
            panel.mousePressEvent(second)
        self.assertEqual(win._timeline_quick_draft_anchor_ms, None)
        self.assertEqual(len(win._rows), 1); created = win._rows[0]
        self.assertEqual((created.s_val, created.e_val, created.speed_override_value(), created.link_group_id), (50000, 60000, None, None))
        self.assertEqual(win._selected_segment_uid, created.uid)
        self.assertTrue(win._dirty_marked); self.assertTrue(win._invalidated)
        self.assertEqual(win._segment_undo_stack.count(), 1)
        win._segment_undo_stack.undo(); self.assertEqual(len(win._rows), 0)
        win._segment_undo_stack.redo(); self.assertEqual((win._rows[0].uid, win._rows[0].s_val, win._rows[0].e_val), (created.uid, 50000, 60000))

        app.MainWindow._on_timeline_quick_draft_requested(win, 70000)
        app.MainWindow._handle_escape_shortcut(win)
        self.assertIsNone(win._timeline_quick_draft_anchor_ms)

    def test_reverse_short_invalid_click_and_escape_preserve_expected_state(self):
        win = _window(); app.MainWindow._add_segment(win, 1000, 2000, None)
        selected = win._rows[0].uid; win._selected_segment_uid = selected
        app.MainWindow._on_timeline_quick_draft_requested(win, 60000)
        app.MainWindow._on_timeline_quick_draft_requested(win, 50000)
        self.assertEqual((win._rows[-1].s_val, win._rows[-1].e_val), (50000, 60000))
        selected = win._selected_segment_uid

        win._dirty_marked = False; win._segment_undo_stack.clear(); win._segment_undo_stack.setClean()
        app.MainWindow._on_timeline_quick_draft_requested(win, 50000)
        app.MainWindow._on_timeline_quick_draft_requested(win, 50050)
        self.assertEqual(win._timeline_quick_draft_anchor_ms, 50000)
        self.assertEqual(len(win._rows), 2); self.assertFalse(win._dirty_marked)
        self.assertEqual(win._segment_undo_stack.count(), 0)
        self.assertEqual(win._selected_segment_uid, selected)

        app.MainWindow._handle_escape_shortcut(win)
        self.assertIsNone(win._timeline_quick_draft_anchor_ms)
        self.assertEqual(win._selected_segment_uid, selected)
        app.MainWindow._handle_escape_shortcut(win)
        self.assertEqual(win._selected_segment_uid, "")

    def test_panel_rejects_non_blank_or_non_ctrl_quick_draft_requests(self):
        panel = _window()._waveform_panel; requested = []
        self._connect_quick_draft(panel, requested.append)
        timeline = panel._timeline_area_rect()
        self.assertFalse(panel._request_timeline_quick_draft(timeline.left() + 20, panel._waveform_area_rect().top() + 5))
        panel.set_segments([(10000, 20000, "segment", (10000, 20000))])
        lane_y = panel._lane_rect(0).top() + 5
        self.assertFalse(panel._request_timeline_quick_draft(panel._timeline_area_rect().left() + panel.time_ms_to_x(15000), lane_y))
        self.assertFalse(panel._request_timeline_quick_draft(panel._timeline_area_rect().left() + panel.time_ms_to_x(10000), lane_y))
        self.assertEqual(requested, [])

        panel.set_segments([])
        if type(app.Qt).__name__ != "_Fake":
            for modifiers in (
                app.Qt.KeyboardModifier.NoModifier,
                app.Qt.KeyboardModifier.ControlModifier | app.Qt.KeyboardModifier.ShiftModifier,
                app.Qt.KeyboardModifier.ControlModifier | app.Qt.KeyboardModifier.AltModifier,
            ):
                panel.mousePressEvent(self._timeline_event(panel, 25000, modifiers))
                panel._cancel_drag()
        self.assertEqual(requested, [])

    def test_unknown_duration_is_ignored_and_scroll_keeps_time_mapping(self):
        panel = app.WaveformPanel(); panel.resize(1024, 220); requested = []
        self._connect_quick_draft(panel, requested.append)
        timeline = panel._timeline_area_rect()
        self.assertFalse(panel._request_timeline_quick_draft(timeline.left() + 100, timeline.top() + 5))

        panel = _window()._waveform_panel
        panel.set_segments([(1000, 3000, f"seg_{index}", (1000, 3000)) for index in range(7)])
        panel.set_timeline_expanded(False); panel.ensure_segment_uid_visible("seg_6")
        requested = []; self._connect_quick_draft(panel, requested.append)
        timeline = panel._timeline_area_rect()
        self.assertTrue(panel._request_timeline_quick_draft(timeline.left() + panel.time_ms_to_x(50000), timeline.top() + 5))
        self.assertEqual(requested, [50000])


if __name__ == "__main__":
    unittest.main()
