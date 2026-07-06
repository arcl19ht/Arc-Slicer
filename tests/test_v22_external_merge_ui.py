import sys
import types
import unittest
from pathlib import Path

import external_merge


class _Fake:
    def __init__(self, *args, **kwargs):
        self._text = str(args[0]) if args else ""
        self._visible = True
        self._enabled = True

    def __call__(self, *args, **kwargs):
        return _Fake()

    def __getattr__(self, name):
        if name in ("clicked", "timeout", "done_signal", "currentTextChanged", "enabled_changed"):
            return _FakeSignal()
        return _Fake()

    def __or__(self, other):
        return self

    def setText(self, text):
        self._text = str(text)

    def text(self):
        return self._text

    def setVisible(self, visible):
        self._visible = bool(visible)

    def isVisible(self):
        return self._visible

    def show(self):
        self._visible = True

    def hide(self):
        self._visible = False

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def isEnabled(self):
        return self._enabled

    def setToolTip(self, text):
        self._tooltip = str(text)

    def setStyleSheet(self, text):
        self._stylesheet = str(text)

    def setWordWrap(self, *_args, **_kwargs):
        pass

    def addWidget(self, *_args, **_kwargs):
        pass

    def addLayout(self, *_args, **_kwargs):
        pass

    def addStretch(self, *_args, **_kwargs):
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
        "QColor", "QFont", "QPalette", "QPainter", "QPainterPath", "QPen",
        "QLinearGradient", "QDragEnterEvent", "QDropEvent", "QDragLeaveEvent",
        "QMouseEvent", "QTextCursor",
    ):
        setattr(qtgui, name, _Fake)
    for name in (
        "QApplication", "QMainWindow", "QWidget", "QVBoxLayout", "QHBoxLayout",
        "QLabel", "QPushButton", "QComboBox", "QLineEdit", "QTextEdit",
        "QScrollArea", "QFrame", "QFileDialog", "QSizePolicy", "QSpacerItem",
        "QCheckBox", "QGridLayout", "QGraphicsDropShadowEffect", "QMessageBox", "QMessageBox",
    ):
        setattr(qtwidgets, name, _Fake)
    qtwidgets.QMessageBox.StandardButton = _Fake()

    sys.modules["PyQt6"] = pyqt
    sys.modules["PyQt6.QtCore"] = qtcore
    sys.modules["PyQt6.QtGui"] = qtgui
    sys.modules["PyQt6.QtWidgets"] = qtwidgets


_install_fake_pyqt()

import app


def _action(kind, operation, identifier):
    return external_merge.MergeAction(
        kind=kind,
        operation=operation,
        identifier=identifier,
        source_path=f"src/{identifier}",
        target_path=f"dst/{identifier}",
    )


def _plan(*, blockers=None, warnings=None, actions=True):
    plan = external_merge.ExternalMergePlan(
        current_songs_dir=Path("current_export/songs"),
        target_songs_dir=Path("target/songs"),
    )
    plan.blockers.extend(blockers or [])
    plan.warnings.extend(warnings or [])
    if actions:
        plan.song_actions.extend([
            _action("song", "add", "song_new"),
            _action("song", "update", "song_old"),
        ])
        plan.pack_actions.extend([
            _action("pack", "add", "pack_new"),
            _action("pack", "update", "pack_old"),
        ])
        plan.pack_image_actions.extend([
            _action("pack_image", "add", "new.png"),
            _action("pack_image", "reuse", "same.png"),
            _action("pack_image", "replace", "old.png"),
        ])
    return plan


class _Panel:
    def __init__(self):
        self._external_merge_plan = _plan()
        self._external_merge_target = Path("target/songs")
        self._external_merge_worker = None
        self._worker = None
        self._btn_external_choose = _Fake()
        self._btn_external_check = _Fake()
        self._btn_external_confirm = _Fake()
        self._btn_run = _Fake()
        self._external_merge_status_label = _Fake()
        self._external_merge_detail_label = _Fake()

    def _external_merge_is_busy(self):
        return False

    def _slicer_is_running(self):
        return False

    def _update_external_merge_controls(self):
        return app.MainWindow._update_external_merge_controls(self)

    def _set_external_merge_view(self, view):
        return app.MainWindow._set_external_merge_view(self, view)

    def _invalidate_external_merge_plan(self, message=""):
        return app.MainWindow._invalidate_external_merge_plan(self, message)

    def _set_running(self, on):
        return app.MainWindow._set_running(self, on)


class ExternalMergeUiStateTests(unittest.TestCase):
    def test_no_target_or_unchecked_plan_cannot_confirm(self):
        self.assertFalse(app.external_merge_can_check(None))
        self.assertFalse(app.external_merge_can_confirm(None))
        self.assertTrue(app.external_merge_can_check(Path("target/songs")))

    def test_ready_plan_with_actions_can_confirm(self):
        plan = _plan()
        self.assertTrue(app.external_merge_can_confirm(plan))
        view = app.external_merge_plan_view_model(plan, backup_root=Path("backup"))
        self.assertEqual(view["state"], "ready")
        self.assertTrue(view["can_confirm"])

    def test_ready_plan_without_actions_cannot_confirm(self):
        plan = _plan(actions=False)
        view = app.external_merge_plan_view_model(plan, backup_root=Path("backup"))
        self.assertEqual(view["state"], "empty")
        self.assertFalse(view["can_confirm"])
        self.assertEqual(view["summary"]["actions"], 0)

    def test_blocker_plan_cannot_confirm_and_keeps_blocker_text(self):
        issue = external_merge.MergeIssue(
            external_merge.BLOCKER,
            "target_songs_dir_is_link",
            "target is a link",
            ("target/songs",),
        )
        plan = _plan(blockers=[issue])
        view = app.external_merge_plan_view_model(plan, backup_root=Path("backup"))
        self.assertEqual(view["state"], "blocked")
        self.assertFalse(view["can_confirm"])
        self.assertIn("target_songs_dir_is_link", view["detail"])

    def test_summary_and_backup_count_are_displayed(self):
        plan = _plan()
        view = app.external_merge_plan_view_model(plan, backup_root=Path("backup/root"))
        self.assertEqual(view["summary"]["song_add"], 1)
        self.assertEqual(view["summary"]["song_update"], 1)
        self.assertEqual(view["summary"]["pack_add"], 1)
        self.assertEqual(view["summary"]["pack_update"], 1)
        self.assertEqual(view["summary"]["pack_image_add"], 1)
        self.assertEqual(view["summary"]["pack_image_reuse"], 1)
        self.assertEqual(view["summary"]["pack_image_replace"], 1)
        self.assertEqual(view["backup_count"], 4)
        self.assertIn(str(Path("backup/root")), view["detail"])

    def test_path_change_clears_plan_and_disables_confirm(self):
        panel = _Panel()
        panel._external_merge_target = Path("new/target/songs")
        app.MainWindow._invalidate_external_merge_plan(panel, "changed")
        self.assertIsNone(panel._external_merge_plan)
        self.assertFalse(panel._btn_external_confirm.isEnabled())
        self.assertIn("changed", panel._external_merge_detail_label.text())

    def test_slicing_done_clears_external_plan(self):
        panel = _Panel()
        app.MainWindow._on_done(panel, 0)
        self.assertIsNone(panel._external_merge_plan)
        self.assertFalse(panel._btn_external_confirm.isEnabled())
        self.assertIn("current_export", panel._external_merge_detail_label.text())

    def test_result_statuses_map_to_non_confirmable_views(self):
        plan = _plan()
        statuses = [
            "completed",
            "stale_plan",
            "rejected",
            "failed_rolled_back",
            "failed_rollback_incomplete",
        ]
        for status in statuses:
            with self.subTest(status=status):
                result = external_merge.ExternalMergeResult(
                    success=status == "completed",
                    status=status,
                    plan=plan,
                    backup_dir=Path("backup/dir"),
                    message="message",
                    changed_paths=["songlist"],
                )
                view = app.external_merge_result_view_model(result)
                self.assertFalse(view["can_confirm"])
                self.assertIn(status, view["detail"])
                self.assertIn(str(Path("backup/dir")), view["detail"])


if __name__ == "__main__":
    unittest.main()
