import unittest

import app
from arc_slicer.ui.segment_history import QUndoStack, SegmentHistoryState


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


def _window():
    win = app.MainWindow.__new__(app.MainWindow)
    win._uid = 0; win._segment_order = 0; win._rows = []
    win._segs_layout = _Layout(); win._speed_input = _Speed(); win._scroll = _Scroll()
    win._waveform_panel = app.WaveformPanel(); win._selected_segment_uid = ""; win._hovered_segment_uid = ""
    win._join_preview_uid = ""; win._current_source_id = "song_a"; win._auto_sort_enabled = False; win._sort_mode = "manual"
    win._cascade_edit_enabled = True; win._audio_duration_ms = 200000
    win._refresh_seg_header = lambda: None; win._schedule_segment_time_validation = lambda: None
    win._schedule_arc_cut_warning_refresh = lambda: None; win._mark_current_export_dirty = lambda *args: None
    win._segment_history_suspended = False; win._segment_history_transactions = {}
    win._segment_restore_in_progress = False
    win._segment_edit_display_snapshots = {}
    win._segment_undo_stack = QUndoStack(); win._segment_undo_stack.setUndoLimit(100); win._segment_undo_stack.setClean()
    return win


class SegmentHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def test_add_undo_redo_preserves_uid_and_only_adds_once(self):
        win = _window()
        app.MainWindow._on_add_segment_clicked(win)
        uid = win._rows[0].uid
        self.assertEqual(len(win._rows), 1); self.assertEqual(win._segment_undo_stack.count(), 1)
        win._segment_undo_stack.undo()
        self.assertEqual(len(win._rows), 0)
        win._segment_undo_stack.redo()
        self.assertEqual([row.uid for row in win._rows], [uid])

    def _require_real_qt(self):
        if not callable(getattr(app.QApplication, "instance", None)):
            self.skipTest("requires real Qt widget state")

    def test_delete_undo_restores_position_uid_order_and_selection(self):
        win = _window()
        for start in (1000, 3000, 5000): app.MainWindow._add_segment(win, start, start + 500, None)
        win._segment_undo_stack.clear(); win._segment_undo_stack.setClean()
        original = list(win._rows); win._selected_segment_uid = original[1].uid
        app.MainWindow._delete_segment_by_uid(win, original[1].uid)
        self.assertEqual(win._segment_undo_stack.count(), 1)
        win._segment_undo_stack.undo()
        self.assertEqual([row.uid for row in win._rows], [row.uid for row in original])
        self.assertEqual(win._rows[1].created_order, original[1].created_order)
        self.assertEqual(win._selected_segment_uid, original[1].uid)

    def test_input_transaction_is_one_command_and_restores_raw_text(self):
        win = _window(); app.MainWindow._add_segment(win, 120000, 140000, None)
        row = win._rows[0]; win._segment_undo_stack.clear()
        app.MainWindow._on_segment_edit_started(win, row, "start")
        row._start.setText("125000"); row._start.setText("125000")
        app.MainWindow._on_segment_edit_committed(win, row, "start")
        self.assertEqual(win._segment_undo_stack.count(), 1)
        win._segment_undo_stack.undo(); self.assertEqual(win._rows[0].start_text(), "120000")
        win._segment_undo_stack.redo(); self.assertEqual(win._rows[0].start_text(), "125000")

    def test_copy_group_and_redo_branch_restore_the_same_identifiers(self):
        win = _window(); app.MainWindow._add_segment(win, 1000, 2000, None)
        source = win._rows[0]; win._segment_undo_stack.clear()
        app.MainWindow._copy_segment(win, source)
        copy_uid, group_id = win._rows[1].uid, win._rows[0].link_group_id
        win._segment_undo_stack.undo()
        self.assertIsNone(win._rows[0].link_group_id)
        win._segment_undo_stack.redo()
        self.assertEqual((win._rows[1].uid, win._rows[1].link_group_id), (copy_uid, group_id))
        win._segment_undo_stack.undo()
        app.MainWindow._on_add_segment_clicked(win)
        self.assertFalse(win._segment_undo_stack.canRedo())

    def test_source_mismatch_restore_is_rejected_without_mutation(self):
        win = _window(); app.MainWindow._add_segment(win, 1000, 2000, None)
        before = [row.uid for row in win._rows]
        app.MainWindow._restore_segment_history_state(win, SegmentHistoryState("other", (), ""))
        self.assertEqual([row.uid for row in win._rows], before)

    def test_three_member_cascade_restore_preserves_full_snapshot(self):
        win = _window()
        for speed in (0.8, 0.9, 1.0):
            app.MainWindow._add_segment(win, 1000, 2000, speed, link_group_id="trio")
        win._selected_segment_uid = win._rows[1].uid
        before = app.MainWindow._capture_segment_history_state(win)

        app.MainWindow._delete_segment_by_uid(win, win._rows[1].uid)
        win._segment_undo_stack.undo()
        win._segment_undo_stack.redo()
        win._segment_undo_stack.undo()

        after = app.MainWindow._capture_segment_history_state(win)
        self.assertEqual(after, before)
        self.assertEqual([row.link_group_id for row in win._rows], ["trio", "trio", "trio"])

    def test_delete_middle_cascade_member_undo_redo_preserves_group(self):
        win = _window()
        for speed in (0.8, 0.9, 1.0):
            app.MainWindow._add_segment(win, 1000, 2000, speed, link_group_id="trio")
        middle_uid = win._rows[1].uid
        win._segment_undo_stack.clear(); win._segment_undo_stack.setClean()

        app.MainWindow._delete_segment_by_uid(win, middle_uid)
        after_delete_uids = [row.uid for row in win._rows]
        self.assertEqual([row.speed_override_text() for row in win._rows], ["0.8", "1"])
        self.assertEqual([row.link_group_id for row in win._rows], ["trio", "trio"])

        win._segment_undo_stack.undo()
        self.assertEqual([row.speed_override_text() for row in win._rows], ["0.8", "0.9", "1"])
        self.assertEqual([row.link_group_id for row in win._rows], ["trio", "trio", "trio"])

        win._segment_undo_stack.redo()
        self.assertEqual([row.uid for row in win._rows], after_delete_uids)
        self.assertEqual([row.link_group_id for row in win._rows], ["trio", "trio"])

    def test_copy_undo_redo_reuses_first_generated_uid_and_group(self):
        win = _window()
        app.MainWindow._add_segment(win, 1000, 2000, None)
        win._segment_undo_stack.clear(); win._segment_undo_stack.setClean()

        app.MainWindow._copy_segment(win, win._rows[0])
        copied_uid = win._rows[1].uid
        group_id = win._rows[0].link_group_id
        win._segment_undo_stack.undo()
        self.assertEqual(len(win._rows), 1)
        self.assertIsNone(win._rows[0].link_group_id)

        win._segment_undo_stack.redo()
        self.assertEqual((win._rows[1].uid, win._rows[0].link_group_id, win._rows[1].link_group_id),
                         (copied_uid, group_id, group_id))

    def test_unlink_and_rejoin_restore_exact_snapshots(self):
        win = _window()
        for speed in (0.8, 0.9, 1.0):
            app.MainWindow._add_segment(win, 1000, 2000, speed, link_group_id="trio")
        win._segment_undo_stack.clear(); win._segment_undo_stack.setClean()
        before = app.MainWindow._capture_segment_history_state(win)

        target = win._rows[1]
        app.MainWindow._unlink_segment_group(win, target)
        unlinked = app.MainWindow._capture_segment_history_state(win)
        win._segment_undo_stack.undo()
        self.assertEqual(app.MainWindow._capture_segment_history_state(win), before)
        win._segment_undo_stack.redo()
        self.assertEqual(app.MainWindow._capture_segment_history_state(win), unlinked)

        app.MainWindow._join_segment_group(win, win._rows[1])
        rejoined = app.MainWindow._capture_segment_history_state(win)
        win._segment_undo_stack.undo()
        self.assertEqual(app.MainWindow._capture_segment_history_state(win), unlinked)
        win._segment_undo_stack.redo()
        self.assertEqual(app.MainWindow._capture_segment_history_state(win), rejoined)

    def test_restore_clears_old_text_focus_before_routing_redo(self):
        win = _window()
        for speed in (0.8, 0.9, 1.0):
            app.MainWindow._add_segment(win, 1000, 2000, speed, link_group_id="trio")
        win._segment_undo_stack.clear(); win._segment_undo_stack.setClean()
        old_field = win._rows[1]._start
        host = app.QWidget()
        layout = app.QVBoxLayout(host)
        for row in win._rows:
            layout.addWidget(row)
        host.show()
        try:
            old_field.setFocus()
            self._qapp.processEvents()
            app.MainWindow._delete_segment_by_uid(win, win._rows[1].uid)
            win._segment_undo_stack.undo()
            self.assertEqual(len(win._rows), 3)
            app.MainWindow._route_redo_shortcut(win)
            self.assertEqual(len(win._rows), 2)
            self.assertFalse(win._segment_undo_stack.canRedo())
        finally:
            host.close()

    def test_preview_refresh_is_debounced_and_commit_flushes_once(self):
        win = _window()
        refreshes = []
        win._refresh_seg_header = lambda: refreshes.append("header")
        win._refresh_waveform_segments = lambda: refreshes.append("waveform")
        win._segment_preview_refresh_timer = app.QTimer()
        win._segment_preview_refresh_timer.setSingleShot(True)
        win._segment_preview_refresh_timer.timeout.connect(win._flush_segment_preview_refresh)
        row = app.MainWindow._add_segment(win, 1000, 2000, None)
        refreshes.clear()
        win._segment_undo_stack.clear()

        app.MainWindow._on_segment_edit_started(win, row, "start")
        for value in ("1", "12", "123", "1234", "12345", "123456"):
            row._start.setText(value)
            app.MainWindow._schedule_segment_preview_refresh(win)
        self.assertEqual(refreshes, [])
        self.assertTrue(win._segment_preview_refresh_timer.isActive())
        app.MainWindow._flush_segment_preview_refresh(win)
        self.assertEqual(refreshes, ["header", "waveform"])

        app.MainWindow._on_segment_edit_committed(win, row, "start")
        self.assertEqual(refreshes, ["header", "waveform", "waveform"])
        self.assertEqual(row.start_text(), "123456")
        self.assertEqual(win._segment_undo_stack.count(), 1)

    def test_complete_start_and_end_edits_keep_timeline_values_until_commit(self):
        self._require_real_qt()
        win = _window()
        app.MainWindow._add_segment(win, 120000, 140000, None)
        row = win._rows[0]
        win._segment_undo_stack.clear()
        refreshes = []
        win._refresh_waveform_segments = lambda: refreshes.append(tuple(app.MainWindow._waveform_segment_ranges(win)))

        app.MainWindow._on_segment_edit_started(win, row, "start")
        for value in ("1", "12", "120", "1200", "12000", "125000"):
            row._start.setText(value)
            app.MainWindow._on_segment_row_changed(win, row)
            self._qapp.processEvents()
            self.assertEqual(app.MainWindow._waveform_segment_ranges(win)[0][:2], (120000, 140000))
            self.assertEqual(row.start_text(), value)
            self.assertEqual(win._segment_undo_stack.count(), 0)
        self.assertEqual(refreshes, [])

        app.MainWindow._on_segment_field_committed(win, row, "start")
        self.assertEqual(app.MainWindow._waveform_segment_ranges(win)[0][:2], (125000, 140000))
        self.assertEqual(len(refreshes), 1)
        self.assertEqual(win._segment_undo_stack.count(), 1)

        app.MainWindow._on_segment_edit_started(win, row, "end")
        row._end.setText("145000")
        app.MainWindow._on_segment_row_changed(win, row)
        self.assertEqual(app.MainWindow._waveform_segment_ranges(win)[0][:2], (125000, 140000))
        app.MainWindow._on_segment_field_committed(win, row, "end")
        self.assertEqual(app.MainWindow._waveform_segment_ranges(win)[0][:2], (125000, 145000))

    def test_speed_edit_freezes_sort_and_timeline_until_atomic_commit(self):
        self._require_real_qt()
        win = _window()
        win._auto_sort_enabled = True; win._sort_mode = "speed"
        for speed in (0.8, 0.9, 1.0):
            app.MainWindow._add_segment(win, 1000, 2000, speed)
        target = next(row for row in win._rows if row.speed_override_text() == "0.9")
        original_order = [row.uid for row in win._rows]
        original_lanes = [item[2] for item in app.MainWindow._waveform_segment_ranges(win)]
        app.MainWindow._set_selected_segment_uid(win, target.uid)
        win._segment_undo_stack.clear()

        app.MainWindow._on_segment_edit_started(win, target, "speed")
        target._speed_override.setText("1.2")
        app.MainWindow._on_segment_row_changed(win, target)
        self.assertEqual([row.uid for row in win._rows], original_order)
        self.assertEqual([item[2] for item in app.MainWindow._waveform_segment_ranges(win)], original_lanes)
        self.assertEqual(win._segment_undo_stack.count(), 0)

        app.MainWindow._on_segment_field_committed(win, target, "speed")
        self.assertEqual([row.speed_override_text() for row in win._rows], ["0.8", "1", "1.2"])
        self.assertEqual(win._selected_segment_uid, target.uid)
        self.assertEqual(win._segment_undo_stack.count(), 1)

    def test_draft_input_keeps_anchor_without_creating_formal_segment(self):
        self._require_real_qt()
        win = _window()
        row = app.MainWindow._add_segment(win, None, None, None)
        app.MainWindow._on_segment_edit_started(win, row, "start")
        row._start.setText("120000")
        app.MainWindow._on_segment_row_changed(win, row)

        self.assertEqual(app.MainWindow._waveform_segment_ranges(win), [])
        self.assertEqual(app.MainWindow._waveform_draft_segments(win), [{"index": 0, "kind": "start", "time_ms": 120000}])

        row._end.setText("140000")
        app.MainWindow._on_segment_field_committed(win, row, "start")
        self.assertEqual(app.MainWindow._waveform_segment_ranges(win)[0][:2], (120000, 140000))
        self.assertEqual(win._segment_undo_stack.count(), 1)

    def test_save_commit_path_finishes_active_edit_once_without_clearing_focus(self):
        self._require_real_qt()
        win = _window()
        row = app.MainWindow._add_segment(win, 120000, 140000, None)
        win._segment_undo_stack.clear()
        host = app.QWidget()
        layout = app.QVBoxLayout(host)
        layout.addWidget(row)
        host.show()
        try:
            row._start.setFocus()
            self._qapp.processEvents()
            app.MainWindow._on_segment_edit_started(win, row, "start")
            row._start.setText("125000")
            app.MainWindow._on_segment_row_changed(win, row)

            app.MainWindow._commit_active_segment_edits_for_save(win)
            self.assertEqual(app.MainWindow._waveform_segment_ranges(win)[0][:2], (125000, 140000))
            self.assertEqual(win._segment_undo_stack.count(), 1)
            self.assertEqual(win._segment_edit_display_snapshots, {})

            app.MainWindow._commit_active_segment_edits_for_save(win)
            self.assertEqual(win._segment_undo_stack.count(), 1)
            app.MainWindow._on_segment_edit_committed(win, row, "start")
            self.assertEqual(win._segment_undo_stack.count(), 1)
        finally:
            host.close()


if __name__ == "__main__":
    unittest.main()
