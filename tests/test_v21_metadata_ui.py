import sys
import types
import unittest


class _Fake:
    def __init__(self, *args, **kwargs):
        self._text = str(args[0]) if args else ""
        self._checked = False
        self._enabled = True
        self._visible = True
        self._children = []

    def __call__(self, *args, **kwargs):
        return _Fake()

    def __getattr__(self, name):
        if name in ("textChanged", "clicked", "timeout", "enabled_changed", "currentTextChanged"):
            return _FakeSignal()
        return _Fake()

    def __or__(self, other):
        return self

    def addWidget(self, widget, *args, **kwargs):
        self._children.append(widget)

    def addLayout(self, layout, *args, **kwargs):
        self._children.append(layout)

    def addStretch(self, *args, **kwargs):
        pass

    def setText(self, text):
        self._text = str(text)

    def text(self):
        return self._text

    def setChecked(self, checked):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def isEnabled(self):
        return self._enabled

    def setVisible(self, visible):
        self._visible = bool(visible)

    def isVisible(self):
        return self._visible

    def hide(self):
        self._visible = False

    def show(self):
        self._visible = True

    def setToolTip(self, text):
        self._tooltip = str(text)

    def selectAll(self):
        self._selected = True

    def setFocus(self):
        self._focused = True

    def deleteLater(self):
        pass


class _FakeSignal:
    def connect(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass


def _install_fake_pyqt():
    if "PyQt6" in sys.modules:
        return
    pyqt = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtgui = types.ModuleType("PyQt6.QtGui")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")

    qtcore.Qt = _Fake()
    qtcore.QThread = _Fake
    qtcore.pyqtSignal = lambda *args, **kwargs: _FakeSignal()
    for name in ("QTimer", "QSize", "QMimeData", "QPoint", "QRect", "QEvent"):
        setattr(qtcore, name, _Fake)
    for name in (
        "QColor", "QFont", "QPalette", "QPainter", "QLinearGradient",
        "QPainterPath", "QPen", "QDragEnterEvent", "QDropEvent",
        "QDragLeaveEvent", "QMouseEvent", "QTextCursor",
    ):
        setattr(qtgui, name, _Fake)
    for name in (
        "QApplication", "QMainWindow", "QWidget", "QVBoxLayout", "QHBoxLayout",
        "QLabel", "QPushButton", "QComboBox", "QLineEdit", "QTextEdit",
        "QScrollArea", "QFrame", "QFileDialog", "QSizePolicy", "QSpacerItem",
        "QCheckBox", "QGridLayout", "QGraphicsDropShadowEffect",
    ):
        setattr(qtwidgets, name, _Fake)

    sys.modules["PyQt6"] = pyqt
    sys.modules["PyQt6.QtCore"] = qtcore
    sys.modules["PyQt6.QtGui"] = qtgui
    sys.modules["PyQt6.QtWidgets"] = qtwidgets


_install_fake_pyqt()

import app


def _visible(widget):
    try:
        hidden = widget.isHidden()
        if isinstance(hidden, bool):
            return not hidden
    except Exception:
        pass
    return widget.isVisible()


class V21MetadataPanelUiTests(unittest.TestCase):
    def test_initial_state_songlist_collapsed_and_packlist_hidden(self):
        panel = app.SonglistPanel()

        self.assertFalse(panel.is_songlist_enabled())
        self.assertFalse(panel._expanded)
        self.assertFalse(_visible(panel._body))
        self.assertFalse(panel._toggle_btn.isEnabled())
        self.assertFalse(_visible(panel._packlist_item))

        panel._toggle()
        self.assertFalse(panel._expanded)
        self.assertFalse(_visible(panel._body))

    def test_enabling_songlist_reveals_collapsed_packlist_item(self):
        panel = app.SonglistPanel()

        panel.set_songlist_enabled(True)

        self.assertTrue(_visible(panel._packlist_item))
        self.assertTrue(panel._toggle_btn.isEnabled())
        self.assertFalse(_visible(panel._body))
        self.assertFalse(panel.is_packlist_enabled())
        self.assertTrue(panel._packlist_enabled.isEnabled())
        self.assertFalse(panel._pack_toggle_btn.isEnabled())
        self.assertFalse(_visible(panel._pack_body))

        panel._toggle()
        self.assertTrue(_visible(panel._body))

    def test_packlist_has_independent_expand_and_preserves_songlist_data(self):
        panel = app.SonglistPanel()
        panel.set_songlist_enabled(True)
        panel._inputs["title_base"].setText("Title")
        panel.set_packlist_enabled(True)
        panel._toggle_pack()

        self.assertTrue(_visible(panel._pack_body))
        self.assertEqual(panel.get_form_data()["title_base"], "Title")

    def test_disabling_songlist_hides_packlist_without_losing_pack_data(self):
        panel = app.SonglistPanel()
        panel.set_songlist_enabled(True)
        panel.set_packlist_enabled(True)
        panel._pack_inputs["pack_id"].setText("manual_pack")
        panel._toggle_pack()
        self.assertTrue(_visible(panel._pack_body))

        panel.set_songlist_enabled(False)

        self.assertFalse(_visible(panel._packlist_item))
        self.assertFalse(_visible(panel._pack_body))
        self.assertFalse(panel._pack_expanded)
        self.assertEqual(panel.get_form_data()["pack_id"], "manual_pack")
        self.assertFalse(app.effective_packlist_export_enabled(panel.is_packlist_enabled(), panel.is_songlist_enabled()))

        panel.set_songlist_enabled(True)
        self.assertTrue(_visible(panel._packlist_item))
        self.assertEqual(panel.get_form_data()["pack_id"], "manual_pack")
        self.assertFalse(_visible(panel._pack_body))

    def test_set_meta_restores_pack_data_without_auto_expanding(self):
        panel = app.SonglistPanel()
        panel.set_meta({
            "title_base": "Saved",
            "pack_id": "saved_pack",
            "pack_name": "Saved Pack",
            "pack_img": "saved.png",
            "packlist_enabled": True,
        })

        self.assertFalse(panel.is_songlist_enabled())
        self.assertFalse(_visible(panel._packlist_item))
        self.assertFalse(_visible(panel._body))
        self.assertEqual(panel.get_form_data()["pack_id"], "saved_pack")

        panel.set_songlist_enabled(True)
        self.assertTrue(_visible(panel._packlist_item))
        self.assertTrue(panel.is_packlist_enabled())
        self.assertFalse(_visible(panel._pack_body))


class V21SegmentIntervalUiTests(unittest.TestCase):
    def test_segment_row_uses_interval_group_labels_and_keeps_independent_states(self):
        row = app.SegmentRow(1, None, None)

        self.assertEqual(row._interval_label.text(), "片段区间（ms）")
        self.assertEqual(row._start_sub_label.text(), "起点")
        self.assertEqual(row._end_sub_label.text(), "终点")
        self.assertEqual(row.start_text(), "")
        self.assertEqual(row.end_text(), "")

        row.set_time_errors("起点不能为空", "终点不能为空")
        self.assertEqual(row._start_error.text(), "起点不能为空")
        self.assertEqual(row._end_error.text(), "终点不能为空")
        self.assertFalse(_visible(row._arc_indicator_box))

        row.set_arc_cut_warnings([{"easing": "si"}], [])
        self.assertTrue(_visible(row._arc_indicator_box))
        self.assertEqual(row._start_error.text(), "起点不能为空")
        self.assertEqual(row._end_error.text(), "终点不能为空")

        row._end.setText("123")
        row.focus_time_field("end")
        focused = getattr(row._end, "_focused", False)
        if not focused and hasattr(row._end, "hasFocus"):
            focused = row._end.hasFocus() or row._end.hasSelectedText()
        self.assertTrue(focused)

        selected = getattr(row._end, "_selected", False)
        if not selected and hasattr(row._end, "selectedText"):
            selected = row._end.selectedText() == "123"
        self.assertTrue(selected)


if __name__ == "__main__":
    unittest.main()
