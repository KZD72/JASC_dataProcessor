"""GUI ownership and atomic adoption of isolated recording results."""
from __future__ import annotations
import weakref

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from core.script_jobs import ScriptRequest, run_script, snapshot_workspace, workspace_stamp
from core.script_language import ScriptError, Program
from ui.background_jobs import JobProgressWidget
from ui.script_dialog import ScriptDialog


class ScriptController(QObject):
    def __init__(self, window: object, menu: object) -> None:
        super().__init__(window)
        self._window = weakref.ref(window)
        self.progress = None
        self.action = menu.addAction("Run Python API Script…", self.show)
        window._jobs.progress.connect(self.update_progress)

    @property
    def window(self):
        return self._window()

    def error(self, message: str) -> None:
        box = QMessageBox(QMessageBox.Warning, "API Recording", "", parent=self.window)
        box.setTextFormat(Qt.PlainText)
        box.setText(message)
        box.exec()

    def show(self) -> None:
        if not self.available():
            return
        dialog = ScriptDialog(self.window)
        try:
            if dialog.exec() == QDialog.Accepted:
                self.start(dialog.request())
        finally:
            dialog.deleteLater()

    def available(self) -> bool:
        window = self.window
        if window._jobs.is_running or window._closing_when_idle:
            window.statusBar().showMessage("Wait for the current background operation to finish")
            return False
        if window._macros.recorder is not None:
            self.error("Stop recording before replaying a Python API script.")
            return False
        return True

    def start(self, request: ScriptRequest) -> bool:
        if not self.available():
            return False
        window = self.window
        try:
            Program.parse(request.source)
            window._plot_tab_widget.flush()
            original = window._workspace
            stamp = workspace_stamp(original)
            snapshot = snapshot_workspace(original)
        except Exception as exc:
            self.error(str(exc))
            return False
        holder = []
        self.action.setEnabled(False)
        self.progress = JobProgressWidget(window)
        self.progress.setLabelText("Preparing restricted script playback…")
        self.progress.canceled.connect(window._jobs.cancel)
        window.statusBar().addPermanentWidget(self.progress)

        def operation(context):
            result = run_script(context, request, workspace=snapshot, publish=False)
            holder.append(result)
            return result

        def discard() -> None:
            for result in holder:
                result.discard()

        def finished(result) -> None:
            self.finish_progress()
            current = self.window
            if current._closing_when_idle or current._workspace is not original:
                discard()
                return
            current._plot_tab_widget.flush()
            if workspace_stamp(original) != stamp:
                discard()
                current.statusBar().showMessage("Script results discarded because the workspace changed during playback")
                return
            was_dirty = current._macro_outputs_dirty
            try:
                self.adopt(result.workspace)
                result.commit()
                current._macro_outputs_dirty = True
                current._set_project_window_title()
            except Exception as exc:
                self.adopt(original)
                current._macro_outputs_dirty = was_dirty
                discard()
                self.error(str(exc))
                return
            current.statusBar().showMessage(f"Completed {result.calls} recorded commands. Results saved in {result.folder}")

        def failed(message: str) -> None:
            self.finish_progress()
            discard()
            if not self.window._closing_when_idle:
                self.error(message)

        def cancelled() -> None:
            self.finish_progress()
            discard()
            self.window.statusBar().showMessage("Script playback cancelled; results were discarded")

        try:
            window._jobs.start(operation, on_success=finished, on_error=failed, on_cancelled=cancelled)
        except Exception:
            self.finish_progress()
            discard()
            raise
        return True

    def adopt(self, workspace: object) -> None:
        window = self.window
        window._large_data_view.set_source(None)
        window._workspace = workspace
        window._macros.workspace_replaced()
        window._active_plot_name = None
        window._active_plot_baseline = None
        window._large_dataset_warning_names.clear()
        window._plot_tab_widget.set_workspace(workspace)
        window._refresh_dataset_list()
        window._refresh_large_dataset_list()
        window._refresh_plot_list()
        window._refresh_spectral_analysis_list()
        window._hide_spectral_analysis_tab()

    def update_progress(self, progress: object) -> None:
        if self.progress is not None:
            self.progress.setLabelText(progress.message)
            self.progress.setRange(0, progress.total)
            self.progress.setValue(progress.completed)

    def finish_progress(self) -> None:
        if self.progress is not None:
            self.window.statusBar().removeWidget(self.progress)
            self.progress.deleteLater()
            self.progress = None
        self.action.setEnabled(True)
