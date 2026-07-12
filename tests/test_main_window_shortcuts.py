import unittest

import app
from arc_slicer.ui.main_window import QKeySequence


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


class _SongBox:
    def currentText(self):
        return "song"


class _Scroll:
    def ensureWidgetVisible(self, _widget):
        return None


def _window(auto_sort=False, sort_mode="manual"):
    win = app.MainWindow.__new__(app.MainWindow)
    win._uid = 0
    win._segment_order = 0
    win._rows = []
    win._segs_layout = _Layout()
    win._speed_input = _Speed()
    win._waveform_panel = app.WaveformPanel()
    win._scroll = _Scroll()
    win._selected_segment_uid = ""
    win._hovered_segment_uid = ""
    win._join_preview_uid = ""
    win._auto_sort_enabled = auto_sort
    win._sort_mode = sort_mode
    win._audio_duration_ms = 200000
    win._refresh_seg_header = lambda: None
    win._schedule_segment_time_validation = lambda: None
    win._schedule_arc_cut_warning_refresh = lambda: None
    win._dirty_marked = False
    win._invalidated = False
    win._mark_current_export_dirty = lambda *args: (
        setattr(win, "_dirty_marked", True),
        setattr(win, "_invalidated", True),
    )
    return win


class MainWindowShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        instance = getattr(app.QApplication, "instance", None)
        cls._qapp = instance() if callable(instance) else None
        if cls._qapp is None:
            cls._qapp = app.QApplication([])

    @staticmethod
    def _supports_real_focus() -> bool:
        return callable(getattr(app.QApplication, "focusWidget", None))

    def _add_three_rows(self, win):
        for start in (1000, 3000, 5000):
            app.MainWindow._add_segment(win, start, start + 500, None)

    def test_card_selected_delete_removes_uid_and_selects_next_row(self):
        win = _window()
        self._add_three_rows(win)
        first, selected, third = win._rows

        app.MainWindow._on_segment_row_selected(win, selected)
        app.MainWindow._delete_selected_segment_from_shortcut(win)

        self.assertEqual([row.uid for row in win._rows], [first.uid, third.uid])
        self.assertEqual(win._selected_segment_uid, third.uid)
        self.assertTrue(win._dirty_marked)
        self.assertTrue(win._invalidated)

    def test_timeline_selected_delete_uses_the_same_uid_path(self):
        win = _window()
        self._add_three_rows(win)
        first, selected, third = win._rows

        app.MainWindow._on_waveform_segment_selected(win, selected.uid)
        app.MainWindow._delete_selected_segment_from_shortcut(win)

        self.assertEqual([row.uid for row in win._rows], [first.uid, third.uid])
        self.assertEqual(win._selected_segment_uid, third.uid)

    def test_backspace_deletes_selected_row_when_focus_is_not_text_editing(self):
        win = _window()
        self._add_three_rows(win)
        selected = win._rows[1]
        win._selected_segment_uid = selected.uid

        app.MainWindow._delete_selected_segment_from_shortcut(win)

        self.assertNotIn(selected, win._rows)
        self.assertTrue(win._dirty_marked)

    def test_empty_and_stale_selection_do_not_mutate_rows_or_dirty_state(self):
        win = _window()
        self._add_three_rows(win)
        original_uids = [row.uid for row in win._rows]

        app.MainWindow._delete_selected_segment_from_shortcut(win)
        self.assertEqual([row.uid for row in win._rows], original_uids)
        self.assertFalse(win._dirty_marked)

        win._selected_segment_uid = "missing"
        app.MainWindow._delete_selected_segment_from_shortcut(win)
        self.assertEqual([row.uid for row in win._rows], original_uids)
        self.assertEqual(win._selected_segment_uid, "")
        self.assertFalse(win._dirty_marked)

    def test_delete_cleans_single_member_group_but_keeps_larger_group(self):
        win = _window()
        app.MainWindow._add_segment(win, 1000, 2000, None, link_group_id="pair")
        app.MainWindow._add_segment(win, 1000, 2000, 0.8, link_group_id="pair")
        win._selected_segment_uid = win._rows[0].uid

        app.MainWindow._delete_selected_segment_from_shortcut(win)

        self.assertEqual(len(win._rows), 1)
        self.assertIsNone(win._rows[0].link_group_id)

        win = _window()
        for speed in (None, 0.8, 0.9):
            app.MainWindow._add_segment(win, 1000, 2000, speed, link_group_id="trio")
        win._selected_segment_uid = win._rows[1].uid
        app.MainWindow._delete_selected_segment_from_shortcut(win)

        self.assertEqual([row.link_group_id for row in win._rows], ["trio", "trio"])

    def test_repeated_delete_follows_selection_fallback_with_auto_sort(self):
        win = _window(auto_sort=True, sort_mode="time")
        for start in (3000, 1000, 5000):
            app.MainWindow._add_segment(win, start, start + 500, None)
        app.MainWindow._maybe_auto_sort_segments(win, force=True)
        selected = win._rows[1]
        win._selected_segment_uid = selected.uid

        app.MainWindow._delete_selected_segment_from_shortcut(win)
        next_uid = win._selected_segment_uid
        app.MainWindow._delete_selected_segment_from_shortcut(win)

        self.assertNotIn(selected.uid, [row.uid for row in win._rows])
        self.assertNotIn(next_uid, [row.uid for row in win._rows])
        self.assertEqual(len(win._rows), 1)

    def test_text_focus_protects_delete_and_backspace_with_real_qt_focus(self):
        win = _window()
        self._add_three_rows(win)
        selected = win._rows[1]
        win._selected_segment_uid = selected.uid

        if not self._supports_real_focus():
            original = getattr(app.QApplication, "focusWidget", None)
            app.QApplication.focusWidget = staticmethod(lambda: selected._start)
            try:
                app.MainWindow._delete_selected_segment_from_shortcut(win)
                self.assertIn(selected, win._rows)
                self.assertFalse(win._dirty_marked)
            finally:
                if original is None:
                    delattr(app.QApplication, "focusWidget")
                else:
                    app.QApplication.focusWidget = original
            return

        host = app.QWidget()
        layout = app.QVBoxLayout(host)
        fields = [app.QLineEdit(), app.QLineEdit(), app.QLineEdit(), app.QTextEdit()]
        for field in fields:
            layout.addWidget(field)
        host.show()
        try:
            for field in fields:
                field.setFocus()
                self._qapp.processEvents()
                self.assertIs(app.QApplication.focusWidget(), field)
                app.MainWindow._delete_selected_segment_from_shortcut(win)
                self.assertIn(selected, win._rows)
                self.assertFalse(win._dirty_marked)
        finally:
            host.close()

    def test_ctrl_s_reuses_save_handler_and_reads_unfinished_row_text(self):
        win = _window()
        app.MainWindow._add_segment(win, 1000, 2000, None)
        row = win._rows[0]
        win._songlist_panel = _SonglistPanel()
        win._current_export_check = _Check()
        win._library_export_check = _Check()
        win._song_box = _SongBox()
        saved = []
        win._save_slides = lambda: saved.append(app.MainWindow._collect(win))

        host = app.QWidget()
        layout = app.QVBoxLayout(host)
        layout.addWidget(row)
        host.show()
        try:
            row._start.setText("1234")
            if not self._supports_real_focus():
                row._on_change()
            row._start.setFocus()
            self._qapp.processEvents()
            app.MainWindow._save_from_shortcut(win)

            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["segments"][0]["s"], 1234)
            if self._supports_real_focus():
                self.assertIs(app.QApplication.focusWidget(), row._start)
        finally:
            host.close()

    def test_real_window_installs_window_scoped_shortcuts(self):
        if not self._supports_real_focus():
            self.assertEqual(QKeySequence(QKeySequence.StandardKey.Save), QKeySequence(QKeySequence.StandardKey.Save))
            return
        win = app.MainWindow()
        try:
            context = app.Qt.ShortcutContext.WidgetWithChildrenShortcut
            self.assertEqual(win._save_shortcut.context(), context)
            self.assertEqual(win._delete_shortcut.context(), context)
            self.assertEqual(win._backspace_shortcut.context(), context)
            self.assertEqual(win._save_shortcut.key(), QKeySequence(QKeySequence.StandardKey.Save))
            self.assertEqual(win._delete_shortcut.key(), QKeySequence(app.Qt.Key.Key_Delete))
            self.assertEqual(win._backspace_shortcut.key(), QKeySequence(app.Qt.Key.Key_Backspace))
            self.assertFalse(win._save_shortcut.autoRepeat())
            self.assertFalse(win._delete_shortcut.autoRepeat())
            self.assertFalse(win._backspace_shortcut.autoRepeat())
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
