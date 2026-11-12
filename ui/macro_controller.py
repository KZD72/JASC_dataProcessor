"""Macro menu, recording hooks, and GUI-thread publication of detached runs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json
import weakref

import pandas as pd
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

from core.macro_jobs import MacroRun, MacroSource, preflight_macro, run_macro, export_macro_tables
from core.macro_recording import MacroRecorder
from core.api_recording import ApiRecording
from core.workspace import Dataset
from models.macro import Macro
from ui.background_jobs import JobProgressWidget
from ui.macro_dialog import MacroDialog
from ui.recording_feedback import RecordingFeedback


class MacroController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self._window_ref = weakref.ref(window)
        self.recorder: MacroRecorder | None = None
        self.macro = Macro()
        self.recorded_workspace = None
        self.initial_plots: dict[str, dict] = {}
        self.progress = None
        self._before_ok = False
        self._saved_state = self.macro.to_state()
        self.api_recording: ApiRecording | None = None
        self._saved_api_source: str | None = None
        self._api_view = None
        self._capturing_api_plot = False
        self._model_edit_depth = 0
        menu = window.menuBar().addMenu("&Macros")
        self.record_action = menu.addAction("Record Macro…", self.start_recording)
        self.stop_action = menu.addAction("Stop Recording", self.stop_recording)
        self.stop_action.setEnabled(False)
        self.recording_feedback = RecordingFeedback(window, self.stop_action)
        menu.addSeparator()
        menu.addAction("View Recorded API Calls…", self.view_api_calls)
        menu.addAction("Save Python API Script…", self.save_api_script)
        from ui.script_controller import ScriptController
        self.script_player = ScriptController(window, menu)
        menu.addSeparator()
        menu.addAction("Review / Run Batch Recipe…", self.show)
        menu.addAction("Load Batch Recipe…", self.load)
        menu.addAction("Save Batch Recipe…", self.save)
        window._jobs.progress.connect(self.update_progress)
        window._plot_tab_widget.documents_changed.connect(self.capture_api_plot)
        window._plot_tab_widget.plot_exported.connect(self.api_export_plot)
        window._plot_tab_widget.analysis_created.connect(self.api_map_analysis)
        window._dataset_model.operation_started.connect(self._edit_started)
        window._dataset_model.operation_finished.connect(self._edit_finished)

    @property
    def window(self):
        return self._window_ref()

    def _capture_error(self, operation) -> None:
        if self.recorder is not None:
            try:
                operation(self.recorder)
            except Exception as exc:
                self.recorder.gap(str(exc))

    def _record_api(self, operation) -> None:
        if self.recorder is not None and self.api_recording is not None:
            try:
                operation(self.api_recording)
            except Exception as exc:
                self.api_recording.gap(str(exc))
            self._refresh_api_view()

    def api_before(self, dataset: Dataset) -> None:
        self._record_api(lambda recording: recording.before(dataset))

    def _edit_started(self, source: Dataset) -> None:
        if self.recorder is not None:
            self._model_edit_depth += 1
            self.api_before(source)

    def _edit_finished(self, source: Dataset, operation: str, parameters: object, success: bool) -> None:
        if self.recorder is not None:
            try:
                if success:
                    self._record_api(lambda recording: recording.edited(source, operation, parameters))
            finally:
                self._model_edit_depth = max(0, self._model_edit_depth-1)
            self.capture_api_plot()

    def api_result(self, method: str, source: Dataset, settings: dict[str, object], output: Dataset,
                   other_inputs: dict[str, Dataset] | None = None) -> None:
        self._record_api(lambda recording: recording.result(method, source, settings, output, other_inputs))

    def api_summary_row(self, helper: str, parameters: dict[str, object], value: object) -> None:
        self._record_api(lambda recording: recording.summary_row(helper, parameters, value))

    def api_collect_rows(self, output: Dataset, rows: list[dict], wide: bool = False) -> None:
        self._record_api(lambda recording: recording.collected(output, rows, wide))

    def api_spectrum(self, source, dialog, baseline_only, detail, published) -> None:
        def record(recording):
            from core.api_spectral import spectrum_settings
            recording.spectral("spectrum", [source], spectrum_settings(dialog, baseline_only, detail),
                               published.sheets, published.analysis)
        self._record_api(record)

    def api_spectral_batch(self, started_recording, sources, request, outputs, analysis) -> None:
        if self.api_recording is not started_recording:
            return
        def record(recording):
            # Never serialize the detached source arrays in the settings file.
            from dataclasses import fields
            settings = {field.name: deepcopy(getattr(request, field.name)) for field in fields(request) if field.name != "sources"}
            for key in ("baseline", "detection", "fit"):
                settings[key] = asdict(settings[key])
            settings["components"] = [asdict(item) for item in settings["components"]]
            recording.spectral("spectral_batch", sources, settings, outputs, analysis)
        self._record_api(record)

    def api_analysis_table(self, analysis, table, output) -> None:
        self._record_api(lambda recording: recording.analysis_table(analysis, table, output))

    def api_duplicate_analysis(self, source, output) -> None:
        def record(recording):
            expression = recording.variable("analysis")
            recording.call("duplicate_analysis", [recording.analysis_ref(source)], assign_to=expression)
            recording.analysis_bindings[id(output)] = expression
            recording.known_analyses.add(id(output))
        self._record_api(record)

    def api_delete_analysis(self, source) -> None:
        self._record_api(lambda recording: recording.call("delete_analysis", [recording.analysis_ref(source)]))

    def api_new_sheet(self, source: Dataset) -> None:
        self._record_api(lambda recording: recording.new_sheet(source))

    def api_excel(self, source: Dataset, worksheet: str, has_header: bool) -> None:
        def record(recording):
            expression = recording.variable("sheet")
            recording.call("load_excel", [str(source.source_path)], assign_to=expression,
                           worksheet=worksheet, has_header=has_header, name=source.name)
            recording.bindings[id(source)] = expression
            recording.remember(source)
        self._record_api(record)

    def api_large_import(self, source, options) -> None:
        def record(recording):
            expression = recording.variable("large")
            recording.call("load_large", [str(source.source_path)], assign_to=expression, **asdict(options))
            recording.large_bindings[id(source)] = expression
            recording.known_large.add(id(source))
        self._record_api(record)

    def api_large_extract(self, source, page, output) -> None:
        def record(recording):
            expression = recording.variable("sheet")
            recording.call("extract_window", [recording.large_ref(source)], assign_to=expression, name=output.name,
                           row_start=page.row_start, row_count=len(output.frame),
                           column_start=page.column_start, column_count=len(output.frame.columns))
            recording.bindings[id(output)] = expression
            recording.remember(output)
        self._record_api(record)

    def api_large_delete(self, source) -> None:
        def record(recording):
            recording.call("delete_large", [recording.large_ref(source)])
            recording.known_large.discard(id(source))
        self._record_api(record)

    def api_renamed_sheet(self, source: Dataset, old_name: str) -> None:
        self._record_api(lambda recording: recording.renamed_sheet(source, old_name))

    def api_deleted_sheet(self, source: Dataset) -> None:
        self._record_api(lambda recording: recording.deleted_sheet(source))

    def api_duplicate_sheet(self, source: Dataset, output: Dataset) -> None:
        def duplicate(recording):
            recording.before(source)
            expression = recording.variable("sheet")
            recording.call("duplicate_sheet", [recording.ref(source)], assign_to=expression)
            recording.bindings[id(output)] = expression
            recording.remember(output)
        self._record_api(duplicate)

    def api_column_math(self, source: Dataset, operation: str, x: str, y: str, method: str, column: str, initial: float | None) -> None:
        self._record_api(lambda recording: recording.column_math(source, operation, x, y, method, column, initial))

    def api_formula(self, source: Dataset, column: str, expression: str, rows: list[int] | None) -> None:
        self._record_api(lambda recording: recording.formula(source, column, expression, rows))

    def api_transform(self, source: Dataset, operation: str, settings: dict[str, object], output: Dataset) -> None:
        self._record_api(lambda recording: recording.transformed(source, operation, settings, output))

    def api_export_data(self, source: Dataset, path: Path, delimiter: str) -> None:
        def exported(recording):
            recording.before(source)
            recording.call("export_data", [recording.ref(source), str(path)], delimiter=delimiter)
        self._record_api(exported)

    def api_project_saved(self, path: Path, *, protected: bool = False) -> None:
        def record(recording):
            if protected:
                recording.gap("Encrypted/signed project saving needs runtime credentials; it cannot be captured in a Python recording.")
            else:
                recording.call("save_project", [str(path)])
        self._record_api(record)

    def api_export_plot(self, identity: str, path: str) -> None:
        plot = next((item for item in self.window._workspace.list_plots() if item.plot_id == identity), None)
        if plot is not None:
            self._record_api(lambda recording: recording.exported_plot(plot, self.window._workspace, path))

    def api_map_analysis(self, output, state, operation, parameters) -> None:
        def record(recording):
            expression = recording.variable("sheet")
            source = recording.series_expression(state, self.window._workspace)
            recording.call("map_analysis", [source], assign_to=expression, operation=operation,
                           parameters=parameters, name=output.name)
            recording.bindings[id(output)] = expression
            recording.remember(output)
        self._record_api(record)

    def capture_api_plot(self) -> None:
        if self._capturing_api_plot or self._model_edit_depth or self.recorder is None:
            return
        self._record_api(lambda recording: recording.plot_deletions(self.window._workspace))
        plot = self.window._plot_tab_widget.active_document
        if plot is not None:
            self._capturing_api_plot = True
            try:
                self._record_api(lambda recording: recording.plotted(plot, self.window._workspace))
            finally:
                self._capturing_api_plot = False

    def _refresh_api_view(self) -> None:
        editor = self._api_view() if self._api_view is not None else None
        if editor is not None and self.api_recording is not None:
            try:
                editor.setPlainText(self.api_recording.source())
            except RuntimeError:
                self._api_view = None

    def view_api_calls(self) -> None:
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QPushButton
        if self.api_recording is None:
            QMessageBox.information(self.window, "API Recording", "Choose Record Macro and perform operations to capture Python API calls.")
            return
        dialog = QDialog(self.window)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowTitle("Recorded Python API Calls")
        dialog.resize(1000, 720)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        layout = QVBoxLayout(dialog)
        layout.addWidget(editor)
        save = QPushButton("Save Python Script…")
        save.clicked.connect(self.save_api_script)
        layout.addWidget(save)
        self._api_view = weakref.ref(editor)
        self._refresh_api_view()
        dialog.show()

    def save_api_script(self) -> bool:
        if self.recorder is not None:
            self.stop_recording()
        if self.api_recording is None:
            QMessageBox.information(self.window, "API Recording", "Record some operations first.")
            return False
        path, _ = QFileDialog.getSaveFileName(self.window, "Save Python API Recording", self.api_recording.name+".py", "Python Script (*.py)")
        if not path:
            return False
        try:
            self.api_recording.save(path)
            self._saved_api_source = self.api_recording.source()
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.window, "Save API Script", str(exc))
            return False

    def start_recording(self, _checked: bool = False, *, name: str | None = None) -> None:
        if self.window._jobs.is_running:
            QMessageBox.information(self.window, "Record Macro", "Wait for the current background operation to finish.")
            return
        if name is None:
            if not self.confirm_saved():
                return
            name, ok = QInputDialog.getText(self.window, "Record Macro", "Macro name:")
            if not ok or not name.strip():
                return
        self.window._plot_tab_widget.flush()
        self.recorded_workspace = self.window._workspace
        self.recorder = MacroRecorder(name, self.window._current_dataset())
        self.api_recording = ApiRecording(name, self.recorded_workspace)
        self.window._dataset_model._record_api_edits = True
        self._saved_api_source = None
        self.initial_plots = {plot.plot_id: deepcopy(plot.state) for plot in self.recorded_workspace.list_plots()}
        self.record_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.recording_feedback.set_recording(True)
        self.window.statusBar().showMessage("Recording Python API calls. Use View Recorded API Calls to inspect the live script.")

    def before(self, dataset: Dataset, targets: list[str], columns: list[str]) -> None:
        self._before_ok = False
        if self.recorder is None:
            return
        if self.recorded_workspace is not self.window._workspace:
            self.recorder.gap("The project changed during recording. Start a new recording.")
            return
        self._capture_error(lambda recorder: recorder.check(dataset))
        if targets != [dataset.name] or len(columns) != 1:
            self.recorder.gap("Demonstrate each recorded operation on one datasheet and one Y column; choose replay targets afterward.")
            return
        self._before_ok = True

    def smoothed(self, dataset, x, y, method, parameters, column) -> None:
        self._record_api(lambda recording: recording.smoothed(dataset, x, y, method, parameters, column))
        if self._before_ok:
            self._capture_error(lambda recorder: recorder.smooth(dataset, x, y, method, parameters, column))

    def fitted(self, source, inputs, settings, fit, residuals, engine_result=None) -> None:
        self._record_api(lambda recording: recording.fitted(source, inputs, settings, fit, residuals, engine_result))
        if self._before_ok:
            self._capture_error(lambda recorder: recorder.fit(source, inputs, settings, fit, residuals))

    def imported(self, dataset: Dataset, options: object | None, *, imported_datasets: list[Dataset] | None = None,
                 pattern_choice: str = "keep") -> None:
        if options is not None:
            for source in imported_datasets or [dataset]:
                self._record_api(lambda recording, item=source: recording.imported(item, options, pattern_choice))
        if self.recorder is not None:
            if options is not None:
                self.recorder.macro.import_options = asdict(options)
            if not self.recorder.macro.steps:
                self.recorder.root = None
                self.recorder.bindings.clear()
                self.recorder.snapshots.clear()
            else:
                self.recorder.gap("Import inputs before recording analysis steps. Start a fresh recording to change the reference input.")
            self.recorder.adopt(dataset)

    def stop_recording(self) -> None:
        if self.recorder is None:
            return
        if self.recorded_workspace is self.window._workspace:
            if self.api_recording is not None:
                self._record_api(lambda recording: recording.finish(self.window._workspace))
            for name in list(self.recorder.snapshots):
                if name in self.window._workspace.dataset_names():
                    self._capture_error(lambda recorder, data=self.window._workspace.get_dataset(name): recorder.check(data))
                else:
                    self.recorder.gap(f"Recorded dataset '{name}' was removed or renamed.")
            self.window._plot_tab_widget.flush()
            for plot in self.window._workspace.list_plots():
                if self.initial_plots.get(plot.plot_id) != plot.state:
                    self._capture_error(lambda recorder, item=plot: recorder.plot(item))
                    self._record_api(lambda recording, item=plot: recording.plotted(item, self.window._workspace))
        else:
            self.recorder.gap("The project changed during recording. Start a new recording.")
            self._record_api(lambda recording: recording.gap("The project changed during recording."))
        self.macro = self.recorder.macro
        self.recorder = None
        self.window._dataset_model._record_api_edits = False
        self.record_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.recording_feedback.set_recording(False)
        if self.api_recording is not None:
            self.window.statusBar().showMessage(f"Recorded {len(self.api_recording.calls)} Python API calls; {len(self.api_recording.issues)} recording gaps. Save Python API Script to keep the recording.")

    def load(self) -> None:
        if not self.confirm_saved():
            return
        path, _ = QFileDialog.getOpenFileName(self.window, "Load Macro", "", "JASC Macro (*.jasc-macro.json);;JSON (*.json)")
        if path:
            try:
                self.macro = Macro.load(path)
                self.api_recording = None
                self._saved_api_source = None
                self._saved_state = self.macro.to_state()
                self.show()
            except (ValueError, KeyError, TypeError, OSError) as exc:
                QMessageBox.warning(self.window, "Load Macro", str(exc))

    def save(self) -> bool:
        if self.recorder is not None:
            self.stop_recording()
        path, _ = QFileDialog.getSaveFileName(self.window, "Save Macro", self.macro.name+".jasc-macro.json", "JASC Macro (*.jasc-macro.json)")
        if path:
            try:
                self.macro.save(path)
                self._saved_state = self.macro.to_state()
                return True
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self.window, "Save Macro", str(exc))
        return False

    def confirm_saved(self) -> bool:
        """Protect a recorded routine independently of the project's plot save guard."""
        if self.recorder is not None:
            self.stop_recording()
        if self.api_recording is not None and (self.api_recording.calls or self.api_recording.issues):
            if self.api_recording.source() == self._saved_api_source:
                return True
            choice = QMessageBox.question(self.window, "Unsaved API Recording", "Save the recorded Python API script before continuing?",
                                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if choice == QMessageBox.Save:
                return self.save_api_script()
            if choice == QMessageBox.Discard:
                self._saved_api_source = self.api_recording.source()
                return True
            return False
        if not (self.macro.steps or self.macro.issues) or self.macro.to_state() == self._saved_state:
            return True
        choice = QMessageBox.question(self.window, "Unsaved Macro", "Save the recorded macro before continuing?",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if choice == QMessageBox.Save:
            return self.save()
        if choice == QMessageBox.Discard:
            self._saved_state = self.macro.to_state()
            return True
        return False

    def show(self) -> None:
        if self.window._jobs.is_running:
            QMessageBox.information(self.window, "Run Macro", "Wait for the current background operation to finish.")
            return
        if self.recorder is not None:
            self.stop_recording()
        dialog = MacroDialog(self.macro, self.window._workspace.dataset_names(), self.window)
        dialog.preview_requested.connect(lambda: self.preview(dialog))
        dialog.cancel_preview.connect(self.window._jobs.cancel)
        accepted = dialog.exec() == QDialog.Accepted
        dialog.macro.name = dialog.name.text().strip() or dialog.macro.name
        if dialog.saved_state is not None:
            self._saved_state = dialog.saved_state
        if accepted:
            self.macro = dialog.macro
            self.start_run(deepcopy(dialog.macro), dialog.ready_sources, open_first=dialog.open_first.isChecked(),
                           export_folder=Path(dialog.export_folder.text()) if dialog.export_folder.text() else None)
        else:
            self.macro = dialog.macro
        dialog.deleteLater()

    def sources(self, dialog: MacroDialog) -> list[MacroSource]:
        sources = []
        for index in range(dialog.targets.count()):
            item = dialog.targets.item(index)
            if item.checkState() != Qt.Checked:
                continue
            kind, key = item.data(Qt.UserRole)
            if kind == "workspace":
                original = self.window._workspace.get_dataset(key)
                sources.append(MacroSource(key, original.name, dataset=deepcopy(original)))
            else:
                sources.append(dialog.file_sources[key])
        return sources

    def preview(self, dialog: MacroDialog) -> None:
        try:
            dialog.macro.name = dialog.name.text().strip()
            dialog.macro.validate(runnable=True)
            sources = self.sources(dialog)
            if not sources:
                raise ValueError("Choose at least one input datasheet or file.")
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(dialog, "Macro Preview", str(exc))
            return
        fingerprint = dialog.macro.to_state()
        dialog.set_busy(True)
        self.begin_progress("Checking macro inputs")

        def finish(rows):
            self.finish_progress()
            dialog.set_busy(False)
            if dialog.macro.to_state() != fingerprint:
                return
            dialog.preview.setPlainText("\n".join(f"{row['source']}: {row['status']} — {row['details']}" for row in rows))
            ready = {row["key"] for row in rows if row["status"] == "ready"}
            dialog.ready_sources = [source for source in sources if source.key in ready]
            dialog.run_button.setEnabled(bool(dialog.ready_sources))

        def failed(message):
            self.finish_progress()
            dialog.set_busy(False)
            dialog.preview.setPlainText(message)

        captured_macro = deepcopy(dialog.macro)
        self.window._jobs.start(lambda context: preflight_macro(context, captured_macro, sources),
                                on_success=finish, on_error=failed, on_cancelled=lambda: failed("Preview cancelled."))

    def begin_progress(self, label: str) -> None:
        self.progress = JobProgressWidget(self.window)
        self.progress.setLabelText(label)
        self.progress.canceled.connect(self.window._jobs.cancel)
        self.window.statusBar().addPermanentWidget(self.progress, 1)

    def update_progress(self, progress) -> None:
        if self.progress is not None:
            self.progress.setLabelText(progress.message)
            self.progress.setRange(0, progress.total)
            self.progress.setValue(progress.completed)

    def finish_progress(self) -> None:
        if self.progress is not None:
            self.window.statusBar().removeWidget(self.progress)
            self.progress.deleteLater()
            self.progress = None

    def workspace_replaced(self) -> None:
        if self.progress is not None:
            self.window._jobs.cancel()

    def start_run(self, macro: Macro, sources: list[MacroSource], *, open_first: bool = True, export_folder: Path | None = None) -> None:
        macro = deepcopy(macro)
        macro.validate(runnable=True)
        if not sources or self.window._jobs.is_running:
            return
        workspace = self.window._workspace
        originals = {source.key: workspace.get_dataset(source.key) for source in sources if source.dataset is not None}
        sources = deepcopy(sources)
        result = MacroRun()
        self.begin_progress("Running macro")

        def completed(_result=None):
            self.finish_progress()
            if workspace is not self.window._workspace or self.window._closing_when_idle:
                return
            self.publish(macro, result, originals, open_first=open_first)
            if export_folder is not None:
                self.begin_progress("Exporting macro tables")
                def exported(path):
                    self.finish_progress()
                    self.window.statusBar().showMessage(f"Macro tables exported to {path}")
                self.window._jobs.start(lambda context: export_macro_tables(context, macro, result, export_folder),
                                        on_success=exported, on_error=failed,
                                        on_cancelled=lambda: (self.finish_progress(), self.window.statusBar().showMessage("Table export cancelled; project results are retained.")))

        def failed(message):
            self.finish_progress()
            QMessageBox.warning(self.window, "Macro Failed", message)

        def cancelled():
            result.cancelled = True
            completed()
        self.window._jobs.start(lambda context: run_macro(context, macro, sources, result),
                                on_success=completed, on_error=failed, on_cancelled=cancelled)

    def publish(self, macro: Macro, result: MacroRun, originals: dict[str, Dataset], *, open_first: bool = True) -> None:
        workspace = self.window._workspace
        first_plot = None
        for output in result.outputs:
            source = output.source
            if source.dataset is not None:
                current = workspace.get_dataset(source.key) if source.key in workspace.dataset_names() else None
                original = originals.get(source.key)
                if current is not original or not current.frame.equals(source.dataset.frame) or current.column_metadata != source.dataset.column_metadata:
                    for row in output.rows:
                        row.update(status="stale", details="Source changed or was removed; results discarded.")
                    continue
            datasets, plots = [], []
            try:
                names = {}
                for alias, table in output.tables.items():
                    if alias == "source" and source.dataset is not None:
                        names[alias] = source.key
                        continue
                    created = workspace.add_dataset(table.name if alias != "source" else source.name, table.frame,
                                                    source_path=table.source_path, copy_frame=False)
                    datasets.append(created)
                    created.column_metadata = deepcopy(table.column_metadata)
                    created.worksheet_metadata = deepcopy(table.worksheet_metadata)
                    created.sync_column_metadata_attrs()
                    names[alias] = created.name
                for key, state in output.plots:
                    state = deepcopy(state)
                    for series in state["series"]:
                        for axis in ("x", "y"):
                            series[axis+"_dataset"] = names[series[axis+"_dataset"]]
                    name = f"{source.name} — {next(step.settings.get('name', key) for step in macro.steps if step.key == key)}"
                    plots.append(workspace.add_plot(name, state))
                if plots and first_plot is None:
                    first_plot = plots[0]
            except Exception as exc:
                for plot in plots:
                    workspace.remove_plot(plot.name)
                for dataset in reversed(datasets):
                    workspace.remove_dataset(dataset.name)
                for row in output.rows:
                    row.update(status="failed", details=f"Publication failed: {exc}")
        summary = workspace.add_dataset(f"{macro.name}_run_summary", pd.DataFrame(result.rows))
        summary.worksheet_metadata.fields.append(("Macro definition", json.dumps(macro.to_state())))
        self.window._macro_outputs_dirty = True
        self.window._refresh_dataset_list(summary.name)
        self.window._refresh_plot_list()
        self.window._plot_tab_widget.refresh_controls()
        if open_first and first_plot is not None:
            self.window._plot_tab_widget.open_plot(first_plot.name)
            self.window._tabs.setCurrentWidget(self.window._plot_tab_widget)
        self.window._set_project_window_title()
        success = sum(row["status"] == "ok" for row in result.rows)
        self.window.statusBar().showMessage(f"Macro {'cancelled' if result.cancelled else 'finished'}: {success} completed steps. See {summary.name}.")
