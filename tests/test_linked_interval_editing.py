import json
import tempfile
import unittest
from pathlib import Path

import app
from arc_slicer.segments import find_inconsistent_link_groups
from arc_slicer.ui.segment_history import QUndoStack


class _Layout:
    def __init__(self):
        self.widgets = []

    def addWidget(self, widget):
        self.widgets.append(widget)

    def insertWidget(self, index, widget):
        self.widgets.insert(index, widget)

    def removeWidget(self, widget):
        if widget in self.widgets:
            self.widgets.remove(widget)


class _Speed:
    def text(self):
        return "1.0"


class _Scroll:
    def ensureWidgetVisible(self, _widget):
        pass


class _SongBox:
    def currentText(self):
        return "song"


class _SonglistPanel:
    def is_songlist_enabled(self):
        return False

    def is_packlist_enabled(self):
        return False

    def get_form_data(self):
        return {}


class _Check:
    def isChecked(self):
        return True


class _SavedLabel:
    def show(self):
        pass

    def hide(self):
        pass


def _window():
    win = app.MainWindow.__new__(app.MainWindow)
    win._uid = 0
    win._segment_order = 0
    win._rows = []
    win._segs_layout = _Layout()
    win._speed_input = _Speed()
    win._scroll = _Scroll()
    win._waveform_panel = app.WaveformPanel()
    win._selected_segment_uid = ""
    win._hovered_segment_uid = ""
    win._join_preview_uid = ""
    win._current_source_id = "song_a"
    win._audio_duration_ms = 200000
    win._auto_sort_enabled = False
    win._sort_mode = "manual"
    win._refresh_seg_header = lambda: None
    win._schedule_segment_time_validation = lambda: None
    win._schedule_arc_cut_warning_refresh = lambda: None
    win._mark_current_export_dirty = lambda *args: None
    win._segment_history_suspended = False
    win._segment_history_transactions = {}
    win._segment_restore_in_progress = False
    win._segment_edit_display_snapshots = {}
    win._segment_undo_stack = QUndoStack()
    win._song_box = _SongBox()
    win._songlist_panel = _SonglistPanel()
    win._current_export_check = _Check()
    win._library_export_check = _Check()
    win._saved_lbl = _SavedLabel()
    win._push_log = lambda *_args: None
    return win


class LinkedIntervalEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    def _trio(self, win):
        for speed in (0.8, 0.9, 1.0):
            app.MainWindow._add_segment(win, 41011, 59394, speed, link_group_id="trio")
        win._segment_undo_stack.clear()
        return win._rows

    def _assert_interval_invariant(self, rows):
        by_group = {}
        for row in rows:
            if row.link_group_id:
                by_group.setdefault(row.link_group_id, set()).add((row.s_val, row.e_val))
        self.assertTrue(all(len(intervals) == 1 for intervals in by_group.values()))

    def test_linked_start_commit_syncs_once_and_keeps_speeds(self):
        win = _window()
        rows = self._trio(win)
        speeds = [row.speed_override_text() for row in rows]

        app.MainWindow._on_segment_edit_started(win, rows[1], "start")
        rows[1]._start.setText("42000")
        app.MainWindow._on_segment_field_committed(win, rows[1], "start")

        self.assertEqual([(row.s_val, row.e_val) for row in rows], [(42000, 59394)] * 3)
        self.assertEqual([row.speed_override_text() for row in rows], speeds)
        self.assertEqual(win._segment_undo_stack.count(), 1)
        self._assert_interval_invariant(rows)

    def test_linked_end_commit_undo_and_redo_restore_the_whole_group(self):
        win = _window()
        rows = self._trio(win)
        uids = [row.uid for row in rows]
        speeds = [row.speed_override_text() for row in rows]

        app.MainWindow._on_segment_edit_started(win, rows[0], "end")
        rows[0]._end.setText("59000")
        app.MainWindow._on_segment_field_committed(win, rows[0], "end")
        self.assertEqual([(row.s_val, row.e_val) for row in rows], [(41011, 59000)] * 3)

        win._segment_undo_stack.undo()
        self.assertEqual([(row.s_val, row.e_val) for row in win._rows], [(41011, 59394)] * 3)
        win._segment_undo_stack.redo()
        self.assertEqual([(row.s_val, row.e_val) for row in win._rows], [(41011, 59000)] * 3)
        self.assertEqual([row.uid for row in win._rows], uids)
        self.assertEqual([row.speed_override_text() for row in win._rows], speeds)

    def test_speed_edit_remains_independent(self):
        win = _window()
        rows = self._trio(win)

        app.MainWindow._on_segment_edit_started(win, rows[1], "speed")
        rows[1]._speed_override.setText("1.2")
        app.MainWindow._on_segment_field_committed(win, rows[1], "speed")

        self.assertEqual([row.speed_override_text() for row in rows], ["0.8", "1.2", "1"])
        self.assertEqual([(row.s_val, row.e_val) for row in rows], [(41011, 59394)] * 3)

    def test_unlinked_same_interval_card_edit_changes_only_the_current_row(self):
        win = _window()
        for speed in (0.8, 0.9, 1.0):
            app.MainWindow._add_segment(win, 41011, 59394, speed)
        rows = win._rows

        app.MainWindow._on_segment_edit_started(win, rows[0], "end")
        rows[0]._end.setText("59000")
        app.MainWindow._on_segment_field_committed(win, rows[0], "end")

        self.assertEqual([(row.s_val, row.e_val) for row in rows], [
            (41011, 59000), (41011, 59394), (41011, 59394),
        ])

    def test_invalid_linked_edit_is_not_propagated_or_recorded(self):
        win = _window()
        rows = self._trio(win)

        app.MainWindow._on_segment_edit_started(win, rows[0], "end")
        rows[0]._end.setText("41011")
        app.MainWindow._on_segment_field_committed(win, rows[0], "end")

        self.assertEqual([(row.s_val, row.e_val) for row in rows[1:]], [(41011, 59394)] * 2)
        self.assertEqual(win._segment_undo_stack.count(), 0)
        self.assertIn(rows[0].uid, win._segment_edit_display_snapshots)

    def test_legacy_inconsistent_group_is_flagged_and_valid_edit_repairs_it(self):
        win = _window()
        rows = self._trio(win)
        rows[1].restore_history_texts("41010", "59394", rows[1].speed_override_text())
        self.assertIn("trio", find_inconsistent_link_groups(rows))
        app.MainWindow._refresh_visual_groups(win)
        self.assertIn("级联异常", rows[0]._group_label.text())

        app.MainWindow._on_segment_edit_started(win, rows[0], "end")
        rows[0]._end.setText("59000")
        app.MainWindow._on_segment_field_committed(win, rows[0], "end")

        self.assertEqual([(row.s_val, row.e_val) for row in rows], [(41011, 59000)] * 3)
        self.assertNotIn("trio", find_inconsistent_link_groups(rows))

    def test_save_rejects_legacy_inconsistent_group_without_collecting(self):
        win = _window()
        rows = self._trio(win)
        rows[2].restore_history_texts("41010", "59394", rows[2].speed_override_text())
        logs = []
        win._collect = lambda: self.fail("inconsistent groups must not be collected for saving")
        win._push_log = lambda message, kind: logs.append((message, kind))

        app.MainWindow._save_slides(win)

        self.assertEqual(len(logs), 1)
        self.assertIn("级联异常", logs[0][0])

    def test_copy_repairs_a_legacy_inconsistent_group_from_the_source_row(self):
        win = _window()
        rows = self._trio(win)
        rows[1].restore_history_texts("41010", "59394", rows[1].speed_override_text())

        app.MainWindow._copy_segment(win, rows[0])

        self.assertEqual([(row.s_val, row.e_val) for row in win._rows], [(41011, 59394)] * 4)
        self._assert_interval_invariant(win._rows)

    def test_ctrl_s_commits_active_linked_end_once_and_saves_the_group(self):
        win = _window()
        rows = self._trio(win)
        refreshes = []
        win._refresh_waveform_segments = lambda: refreshes.append("waveform")
        host = app.QWidget()
        layout = app.QVBoxLayout(host)
        for row in rows:
            layout.addWidget(row)

        with tempfile.TemporaryDirectory() as td:
            slides_path = Path(td) / "slides.json"
            logs = []
            win._push_log = lambda message, kind: logs.append((message, kind))
            save_globals = app.MainWindow._save_slides.__globals__
            old_slides_path = save_globals["SLIDES_PATH"]
            save_globals["SLIDES_PATH"] = slides_path
            host.show()
            try:
                rows[0]._end.setFocus()
                self._qapp.processEvents()
                app.MainWindow._on_segment_edit_started(win, rows[0], "end")
                rows[0]._end.setText("59000")
                self.assertIn(f"input:{rows[0].uid}:end", win._segment_history_transactions)
                app.MainWindow._save_from_shortcut(win)

                self.assertTrue(slides_path.exists(), logs)
                saved = json.loads(slides_path.read_text(encoding="utf-8"))
                self.assertEqual([(row.s_val, row.e_val) for row in rows], [(41011, 59000)] * 3)
                self.assertEqual([item["e"] for item in saved["segments"]], [59000] * 3)
                self.assertEqual([row.speed_override_text() for row in rows], ["0.8", "0.9", "1"])
                self.assertEqual(win._segment_undo_stack.count(), 1)
                self.assertTrue(win._segment_undo_stack.isClean())
                self.assertEqual(refreshes, ["waveform"])
                if callable(getattr(app.QApplication, "focusWidget", None)) and app.QApplication.focusWidget() is rows[0]._end:
                    self.assertIs(app.QApplication.focusWidget(), rows[0]._end)

                rows[0]._end.clearFocus()
                self._qapp.processEvents()
                self.assertEqual(win._segment_undo_stack.count(), 1)
                self.assertEqual(refreshes, ["waveform"])
            finally:
                host.close()
                save_globals["SLIDES_PATH"] = old_slides_path

    def test_ctrl_s_pipeline_syncs_linked_start_and_keeps_speeds_independent(self):
        win = _window()
        rows = self._trio(win)
        app.MainWindow._on_segment_edit_started(win, rows[1], "start")
        rows[1]._start.setText("42000")

        self.assertTrue(app.MainWindow._commit_active_segment_edits_for_save(win))
        self.assertEqual([(row.s_val, row.e_val) for row in rows], [(42000, 59394)] * 3)
        self.assertEqual([row.speed_override_text() for row in rows], ["0.8", "0.9", "1"])
        self.assertEqual(win._segment_undo_stack.count(), 1)

    def test_ctrl_s_pipeline_keeps_linked_speed_local(self):
        win = _window()
        rows = self._trio(win)
        app.MainWindow._on_segment_edit_started(win, rows[0], "speed")
        rows[0]._speed_override.setText("0.75")

        self.assertTrue(app.MainWindow._commit_active_segment_edits_for_save(win))
        self.assertEqual([row.speed_override_text() for row in rows], ["0.75", "0.9", "1"])
        self.assertEqual([(row.s_val, row.e_val) for row in rows], [(41011, 59394)] * 3)

    def test_ctrl_s_invalid_linked_edit_blocks_save_and_keeps_transaction(self):
        win = _window()
        rows = self._trio(win)
        app.MainWindow._on_segment_edit_started(win, rows[0], "end")
        rows[0]._end.setText("41011")
        win._collect = lambda: self.fail("invalid linked edit must not be saved")

        self.assertFalse(app.MainWindow._save_slides(win))
        self.assertEqual([(row.s_val, row.e_val) for row in rows[1:]], [(41011, 59394)] * 2)
        self.assertIn(f"input:{rows[0].uid}:end", win._segment_history_transactions)
        self.assertIn(rows[0].uid, win._segment_edit_display_snapshots)


if __name__ == "__main__":
    unittest.main()
