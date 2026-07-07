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

    def setPlaceholderText(self, text):
        self._placeholder = str(text)

    def placeholderText(self):
        return getattr(self, "_placeholder", "")

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
        "QCheckBox", "QGridLayout", "QGraphicsDropShadowEffect", "QMessageBox",
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


def _songlist_panel_for_pack_placeholder(pack_id="source_song"):
    panel = object.__new__(app.SonglistPanel)
    panel._inputs = {"set": _Fake(pack_id)}
    panel._pack_inputs = {
        "pack_id": _Fake(pack_id),
        "pack_name": _Fake(pack_id),
        "pack_description": _Fake(""),
        "pack_img": _Fake(app.default_pack_img_name(pack_id)),
    }
    panel._last_shared_pack_id = pack_id
    panel._syncing_shared_pack_id = False
    panel._resetting_source = False
    panel.metadata_changed = _FakeSignal()
    return panel


class _Panel:
    def __init__(self):
        self._external_merge_plan = _plan()
        self._external_merge_target = Path("target/songs")
        self._external_merge_worker = None
        self._external_merge_phase = "idle"
        self._external_merge_generation = 0
        self._current_export_dirty = False
        self._last_run_current_export_enabled = True
        self._worker = None
        self._slicer_running = False
        self.logs = []
        self._btn_external_choose = _Fake()
        self._btn_external_check = _Fake()
        self._btn_external_confirm = _Fake()
        self._btn_run = _Fake()
        self._external_merge_status_label = _Fake()
        self._external_merge_detail_label = _Fake()

    def _external_merge_is_busy(self):
        return app.MainWindow._external_merge_is_busy(self)

    def _slicer_is_running(self):
        return app.MainWindow._slicer_is_running(self)

    def _update_external_merge_controls(self):
        return app.MainWindow._update_external_merge_controls(self)

    def _set_external_merge_view(self, view):
        return app.MainWindow._set_external_merge_view(self, view)

    def _invalidate_external_merge_plan(self, message=""):
        return app.MainWindow._invalidate_external_merge_plan(self, message)

    def _mark_current_export_dirty(self, *args):
        return app.MainWindow._mark_current_export_dirty(self, *args)

    def _set_running(self, on):
        return app.MainWindow._set_running(self, on)

    def _on_external_merge_done(self, mode, generation, payload, error):
        return app.MainWindow._on_external_merge_done(self, mode, generation, payload, error)

    def _push_log(self, text, kind="normal"):
        self.logs.append((text, kind))


class _WorkerSignal:
    def __init__(self, worker):
        self.worker = worker

    def connect(self, callback):
        self.worker.callback = callback


class _FakeWorker:
    created = []

    def __init__(self, mode, generation, current_songs_dir, target_songs_dir, backup_root=None, plan=None):
        self.mode = mode
        self.generation = generation
        self.current_songs_dir = current_songs_dir
        self.target_songs_dir = target_songs_dir
        self.backup_root = backup_root
        self.plan = plan
        self.started = False
        self.callback = None
        self.done_signal = _WorkerSignal(self)
        _FakeWorker.created.append(self)

    def isRunning(self):
        return False

    def start(self):
        self.started = True


class _MessageBoxOk:
    class StandardButton:
        Ok = 1
        Cancel = 2

    @staticmethod
    def question(*_args, **_kwargs):
        return _MessageBoxOk.StandardButton.Ok


class _RaisingFileDialog:
    @staticmethod
    def getExistingDirectory(*_args, **_kwargs):
        raise AssertionError("file dialog should not open")


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

    def test_external_merge_card_is_before_run_and_log_sections(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertLess(
            source.index("外部目标壳合并 EXTERNAL MERGE"),
            source.index("self._btn_run = QPushButton"),
        )
        self.assertLess(
            source.index("外部目标壳合并 EXTERNAL MERGE"),
            source.index("self._log_widget = QTextEdit"),
        )

    def test_confirmation_text_mentions_backup_and_unrelated_resources(self):
        text = app.external_merge_confirmation_text(_plan(), Path("backup/root"))
        self.assertIn("此操作会修改目标 songs 目录", text)
        self.assertIn("执行时会在备份根目录下创建一个时间戳子目录", text)
        self.assertIn("工具会先备份受影响项目", text)
        self.assertIn("无关资源不会被主动清理", text)
        self.assertIn("backup", text)

    def test_external_merge_actions_return_immediately_when_busy_or_slicing(self):
        panel = _Panel()
        _FakeWorker.created = []
        old_dialog = app.QFileDialog
        old_worker = app.ExternalMergeWorker
        widgets = sys.modules["PyQt6.QtWidgets"]
        had_msg = hasattr(widgets, "QMessageBox")
        old_msg = getattr(widgets, "QMessageBox", None)
        try:
            app.QFileDialog = _RaisingFileDialog
            app.ExternalMergeWorker = _FakeWorker
            widgets.QMessageBox = _MessageBoxOk

            panel._external_merge_phase = "checking"
            old_target = panel._external_merge_target
            app.MainWindow._browse_external_merge_target(panel)
            app.MainWindow._check_external_merge_plan(panel)
            app.MainWindow._confirm_external_merge(panel)
            self.assertEqual(panel._external_merge_target, old_target)
            self.assertEqual(panel._external_merge_generation, 0)
            self.assertEqual(_FakeWorker.created, [])

            panel._external_merge_phase = "idle"
            panel._slicer_running = True
            app.MainWindow._browse_external_merge_target(panel)
            app.MainWindow._check_external_merge_plan(panel)
            app.MainWindow._confirm_external_merge(panel)
            self.assertEqual(panel._external_merge_target, old_target)
            self.assertEqual(panel._external_merge_generation, 0)
            self.assertEqual(_FakeWorker.created, [])
        finally:
            app.QFileDialog = old_dialog
            app.ExternalMergeWorker = old_worker
            if had_msg:
                widgets.QMessageBox = old_msg
            else:
                delattr(widgets, "QMessageBox")

    def test_check_phase_disables_controls_before_worker_running(self):
        panel = _Panel()
        _FakeWorker.created = []
        old_worker = app.ExternalMergeWorker
        try:
            app.ExternalMergeWorker = _FakeWorker
            app.MainWindow._check_external_merge_plan(panel)
        finally:
            app.ExternalMergeWorker = old_worker

        self.assertEqual(panel._external_merge_phase, "checking")
        self.assertEqual(panel._external_merge_generation, 1)
        self.assertTrue(_FakeWorker.created[0].started)
        self.assertFalse(panel._btn_external_choose.isEnabled())
        self.assertFalse(panel._btn_external_check.isEnabled())
        self.assertFalse(panel._btn_external_confirm.isEnabled())
        self.assertFalse(panel._btn_run.isEnabled())

    def test_execute_phase_disables_controls_before_worker_running(self):
        panel = _Panel()
        _FakeWorker.created = []
        old_worker = app.ExternalMergeWorker
        widgets = sys.modules["PyQt6.QtWidgets"]
        had_msg = hasattr(widgets, "QMessageBox")
        old_msg = getattr(widgets, "QMessageBox", None)
        try:
            app.ExternalMergeWorker = _FakeWorker
            widgets.QMessageBox = _MessageBoxOk
            app.MainWindow._confirm_external_merge(panel)
        finally:
            app.ExternalMergeWorker = old_worker
            if had_msg:
                widgets.QMessageBox = old_msg
            else:
                delattr(widgets, "QMessageBox")

        self.assertEqual(panel._external_merge_phase, "executing")
        self.assertEqual(panel._external_merge_generation, 1)
        self.assertTrue(_FakeWorker.created[0].started)
        self.assertFalse(panel._btn_external_choose.isEnabled())
        self.assertFalse(panel._btn_external_check.isEnabled())
        self.assertFalse(panel._btn_external_confirm.isEnabled())
        self.assertFalse(panel._btn_run.isEnabled())

    def test_stale_worker_callback_does_not_overwrite_new_state_or_log(self):
        panel = _Panel()
        newer = _plan()
        panel._external_merge_generation = 2
        panel._external_merge_phase = "checking"
        panel._external_merge_plan = newer
        panel._external_merge_status_label.setText("newer")

        app.MainWindow._on_external_merge_done(panel, "check", 1, _plan(actions=False), "")

        self.assertIs(panel._external_merge_plan, newer)
        self.assertEqual(panel._external_merge_phase, "checking")
        self.assertEqual(panel._external_merge_status_label.text(), "newer")
        self.assertEqual(panel.logs, [])

        app.MainWindow._on_external_merge_done(panel, "check", 2, _plan(actions=False), "")
        self.assertEqual(panel._external_merge_phase, "idle")
        self.assertEqual(panel._external_merge_plan.summary["actions"], 0)

    def test_path_change_clears_plan_and_disables_confirm(self):
        panel = _Panel()
        panel._external_merge_target = Path("new/target/songs")
        app.MainWindow._invalidate_external_merge_plan(panel, "changed")
        self.assertIsNone(panel._external_merge_plan)
        self.assertFalse(panel._btn_external_confirm.isEnabled())
        self.assertIn("changed", panel._external_merge_detail_label.text())

    def test_dirty_current_export_disables_external_merge_until_successful_slice(self):
        panel = _Panel()
        panel._external_merge_target = Path("target/songs")
        app.MainWindow._update_external_merge_controls(panel)
        self.assertTrue(panel._btn_external_check.isEnabled())
        self.assertTrue(panel._btn_external_confirm.isEnabled())

        app.MainWindow._mark_current_export_dirty(panel)
        self.assertIsNone(panel._external_merge_plan)
        self.assertFalse(panel._btn_external_check.isEnabled())
        self.assertFalse(panel._btn_external_confirm.isEnabled())
        self.assertIn("需要先运行切片", panel._external_merge_status_label.text())
        self.assertIn("当前配置尚未导出", panel._external_merge_detail_label.text())
        self.assertIn("#FFF4E6", panel._external_merge_detail_label._stylesheet)

        app.MainWindow._invalidate_external_merge_plan(panel, "目标路径已变更")
        self.assertIn("需要先运行切片", panel._external_merge_status_label.text())
        self.assertIn("当前配置尚未导出", panel._external_merge_detail_label.text())
        self.assertNotIn("目标路径已变更", panel._external_merge_detail_label.text())

        app.MainWindow._on_done(panel, 0)
        self.assertFalse(panel._current_export_dirty)
        self.assertTrue(panel._btn_external_check.isEnabled())
        self.assertFalse(panel._btn_external_confirm.isEnabled())
        self.assertNotIn("当前配置尚未导出", panel._external_merge_detail_label.text())

    def test_dirty_external_merge_view_model_is_not_confirmable(self):
        view = app.external_merge_dirty_view_model(Path("target/songs"), backup_root=Path("backup/root"))
        self.assertEqual(view["state"], "dirty")
        self.assertFalse(view["can_confirm"])
        self.assertIn("需要先运行切片", view["title"])
        self.assertIn("当前配置尚未导出", view["detail"])
        self.assertIn(str(Path("target/songs")), view["detail"])

    def test_pack_description_placeholder_follows_pack_id_without_form_fallback(self):
        self.assertEqual(
            app.pack_description_placeholder("prelude_heavensdoor"),
            "prelude_heavensdoor practice clips generated by Arc Slicer.",
        )
        self.assertEqual(
            app.pack_template_from_form(
                {
                    "pack_id": "prelude_heavensdoor",
                    "pack_name": "prelude_heavensdoor",
                    "pack_description": "",
                    "pack_img": "select_prelude_heavensdoor.png",
                    "pack_cover_source": "auto",
                },
                "prelude_heavensdoor",
            ).description,
            "",
        )

        panel = _songlist_panel_for_pack_placeholder("prelude_heavensdoor")
        app.SonglistPanel._update_pack_description_placeholder(panel)
        self.assertEqual(
            panel._pack_inputs["pack_description"].placeholderText(),
            "prelude_heavensdoor practice clips generated by Arc Slicer.",
        )

        panel._pack_inputs["pack_id"].setText("new_pack")
        app.SonglistPanel._on_pack_id_changed(panel, "new_pack")
        self.assertEqual(panel._inputs["set"].text(), "new_pack")
        self.assertEqual(panel._pack_inputs["pack_img"].text(), "select_new_pack.png")
        self.assertEqual(
            panel._pack_inputs["pack_description"].placeholderText(),
            "new_pack practice clips generated by Arc Slicer.",
        )

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

    def test_result_view_models_for_warning_and_incomplete_rollback(self):
        plan = _plan()
        issue = external_merge.MergeIssue(external_merge.WARNING, "manifest_warning", "manifest warning")
        completed = external_merge.ExternalMergeResult(
            success=True,
            status="completed",
            plan=plan,
            backup_dir=Path("backup/dir"),
            changed_paths=["songlist"],
            execution_issues=[issue],
        )
        completed_view = app.external_merge_result_view_model(completed)
        self.assertIn("备份记录存在提示", completed_view["title"])
        self.assertIn("manifest_warning", completed_view["detail"])

        failed = external_merge.ExternalMergeResult(
            success=False,
            status="failed_rollback_incomplete",
            plan=plan,
            backup_dir=Path("backup/dir"),
            rollback_errors=["rollback broke"],
            execution_issues=[external_merge.MergeIssue(external_merge.BLOCKER, "execution_failed", "boom")],
        )
        failed_view = app.external_merge_result_view_model(failed)
        self.assertIn("立即停止继续操作目标壳", failed_view["title"])
        self.assertIn("合并失败，且自动恢复不完整", failed_view["detail"])
        self.assertIn("rollback broke", failed_view["detail"])
        self.assertIn("execution_failed", failed_view["detail"])

    def test_external_merge_result_logs_are_written_for_current_generation_only(self):
        panel = _Panel()
        result = external_merge.ExternalMergeResult(
            success=True,
            status="completed",
            plan=_plan(),
            backup_dir=Path("backup/dir"),
            changed_paths=["songlist", "packlist"],
        )

        panel._external_merge_generation = 2
        panel._external_merge_phase = "executing"
        app.MainWindow._on_external_merge_done(panel, "execute", 1, result, "")
        self.assertEqual(panel.logs, [])
        self.assertEqual(panel._external_merge_phase, "executing")

        app.MainWindow._on_external_merge_done(panel, "execute", 2, result, "")
        self.assertEqual(panel._external_merge_phase, "idle")
        self.assertEqual(len(panel.logs), 1)
        self.assertIn("[外部合并] 完成", panel.logs[0][0])

    def test_external_merge_worker_errors_log_only_for_current_generation(self):
        panel = _Panel()
        panel._external_merge_generation = 2
        panel._external_merge_phase = "checking"

        app.MainWindow._on_external_merge_done(panel, "check", 1, None, "old boom")
        self.assertEqual(panel.logs, [])
        self.assertEqual(panel._external_merge_phase, "checking")

        app.MainWindow._on_external_merge_done(panel, "check", 2, None, "read boom")
        self.assertEqual(panel._external_merge_phase, "idle")
        self.assertEqual(len(panel.logs), 1)
        self.assertIn("[外部合并] 检查失败", panel.logs[0][0])
        self.assertIn("read boom", panel.logs[0][0])

        panel._external_merge_generation = 3
        panel._external_merge_phase = "executing"
        app.MainWindow._on_external_merge_done(panel, "execute", 3, None, "write boom")
        self.assertEqual(len(panel.logs), 2)
        self.assertIn("[外部合并] 执行失败", panel.logs[1][0])
        self.assertIn("write boom", panel.logs[1][0])

    def test_slicing_and_external_merge_mutual_exclusion(self):
        panel = _Panel()
        panel._external_merge_phase = "checking"
        app.MainWindow._update_external_merge_controls(panel)
        self.assertFalse(panel._btn_run.isEnabled())

        panel._external_merge_phase = "idle"
        app.MainWindow._set_running(panel, True)
        self.assertFalse(panel._btn_external_choose.isEnabled())
        self.assertFalse(panel._btn_external_check.isEnabled())
        self.assertFalse(panel._btn_external_confirm.isEnabled())

        app.MainWindow._set_running(panel, False)
        self.assertTrue(panel._btn_external_choose.isEnabled())


if __name__ == "__main__":
    unittest.main()
