"""Real recording hooks, worker replay, plot publication, persistence, and guards."""

from copy import deepcopy
import gc
import os
from pathlib import Path
import tempfile
import time
from threading import Event, get_ident
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import pandas as pd

from core import project_io
from core.macro_jobs import MacroRun, MacroSource, run_macro
from core.workspace import Workspace
from tests.test_macros import context, data, macro
from ui.dialogs import FitDialog, SmoothingDialog, select_list_items
from ui.macro_dialog import MacroDialog
from ui.main_window import MainWindow


class MacroUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.source = self.window._workspace.add_dataset("source", data().frame)
        self.window._refresh_dataset_list(self.source.name)

    def wait(self):
        limit = time.monotonic()+15
        while self.window._jobs.is_running and time.monotonic() < limit:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.window._jobs.is_running)

    def tearDown(self):
        self.window._jobs.cancel()
        self.wait()
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def record(self):
        controller = self.window._macros
        controller.start_recording(name="Recorded example")
        dialog = SmoothingDialog(self.source.frame, list(self.source.frame), "x", [self.source.name], self.source.name, self.window)
        select_list_items(dialog._y_column_list, ["y"])
        dialog._method_combo.setCurrentIndex(dialog._method_combo.findData("savgol"))
        self.window._run_smoothing_batch(self.source, dialog)
        dialog.deleteLater()
        fit = FitDialog(list(self.source.frame), self.source.name, default_x_column="x", parent=self.window)
        select_list_items(fit._y_column_list, ["y_smoothed"])
        fit._model_combo.setCurrentIndex(fit._model_combo.findData("linear"))
        with patch("ui.main_window.FitReportDialog.exec", return_value=QDialog.Accepted):
            self.window._run_curve_fit_batch(self.source, fit, [1., 0.], [None, None], [None, None], [False, False])
        fit.deleteLater()
        controller.stop_recording()
        return controller.macro

    def test_real_dialog_recording_replays_derived_fit_and_styles(self):
        routine = self.record()
        self.assertFalse(routine.issues)
        self.assertEqual([step.operation for step in routine.steps[:2]], ["smooth", "fit"])
        self.assertEqual(routine.steps[1].inputs["y"].table, routine.steps[0].key)
        self.assertEqual(sum(step.operation == "plot" for step in routine.steps), 2)
        target = self.window._workspace.add_dataset("target", data(slope=4.).frame)
        original = target.frame.copy()
        self.window._macros.start_run(routine, [MacroSource(target.name, target.name, deepcopy(target))], open_first=True)
        self.wait()
        pd.testing.assert_frame_equal(target.frame, original)
        self.assertTrue(self.window._macro_outputs_dirty)
        generated = self.window._plot_tab_widget.active_document
        self.assertIn("target", generated.name)
        for series in generated.state["series"]:
            self.assertIn(series["y_dataset"], self.window._workspace.dataset_names())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"results.jasc"
            self.window._plot_tab_widget.flush()
            project_io.save_project(self.window._workspace, path)
            loaded = project_io.load_project(path)
            self.assertEqual(len(loaded.list_plots()), len(self.window._workspace.list_plots()))

    def test_publication_failure_rolls_back_one_source_without_touching_existing(self):
        source = MacroSource(self.source.name, self.source.name, deepcopy(self.source))
        result = run_macro(context(), macro(), [source], MacroRun())
        original = self.source.frame.copy()
        with patch.object(self.window._workspace, "add_plot", side_effect=RuntimeError("plot failure")):
            self.window._macros.publish(macro(), result, {self.source.name: self.source}, open_first=False)
        self.assertEqual(len(self.window._workspace.list_datasets()), 2)  # input + audit
        self.assertEqual(self.window._workspace.list_plots(), [])
        pd.testing.assert_frame_equal(original, self.source.frame)
        self.assertTrue(all(row["status"] == "failed" for row in result.rows))

    def test_changed_source_is_rejected_before_gui_publication(self):
        source = MacroSource(self.source.name, self.source.name, deepcopy(self.source))
        result = run_macro(context(), macro(), [source], MacroRun())
        self.source.frame.loc[0, "y"] = 555
        self.window._macros.publish(macro(), result, {self.source.name: self.source}, open_first=False)
        self.assertEqual(len(self.window._workspace.list_datasets()), 2)
        self.assertTrue(all(row["status"] == "stale" for row in result.rows))

    def test_project_replacement_rejects_running_results(self):
        self.window._macros.start_run(macro(), [MacroSource(self.source.name, self.source.name, deepcopy(self.source))])
        replacement = Workspace()
        self.window._workspace = replacement
        self.window._plot_tab_widget.set_workspace(replacement)
        self.wait()
        self.assertFalse(replacement.dataset_names())
        self.assertFalse(replacement.plot_names())

    def test_cancelled_run_keeps_only_complete_sources(self):
        from core import macro_jobs
        original = macro_jobs.smooth_column
        count = 0
        def cancel_second(*args, **kwargs):
            nonlocal count
            count += 1
            value = original(*args, **kwargs)
            if count == 2:
                self.window._jobs.cancel()
            return value
        sources = [MacroSource(str(i), str(i), path=None, dataset=data(str(i))) for i in range(3)]
        # Adopt originals so stale-source checks exercise actual workspace identities.
        for source in sources:
            adopted = self.window._workspace.add_dataset(source.key, source.dataset.frame)
            source.dataset = deepcopy(adopted)
        with patch.object(macro_jobs, "smooth_column", cancel_second):
            self.window._macros.start_run(macro(), sources, open_first=False)
            self.wait()
        self.assertEqual(len(self.window._workspace.list_plots()), 1)
        summary = self.window._workspace.list_datasets()[-1].frame
        self.assertEqual(sum(summary.status == "cancelled"), 2)

    def test_review_preview_and_edit_dependency_controls(self):
        dialog = MacroDialog(macro(), [self.source.name], self.window)
        dialog.select_all(True)
        dialog.cancel_preview.connect(self.window._jobs.cancel)
        self.window._macros.preview(dialog)
        self.wait()
        self.assertTrue(dialog.run_button.isEnabled())
        self.assertEqual(len(dialog.ready_sources), 1)
        dialog.steps.setCurrentRow(0)
        with patch("ui.macro_dialog.QMessageBox.warning") as warning:
            dialog.remove()
        warning.assert_called_once()
        self.assertEqual(len(dialog.macro.steps), 3)
        dialog.name.setText("Changed")
        self.assertFalse(dialog.run_button.isEnabled())
        dialog.deleteLater()

    def test_mixed_folder_and_workspace_run_creates_independent_saved_plots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"source.csv"
            data(slope=4.).frame.to_csv(path, index=False)
            sources = [MacroSource(self.source.name, self.source.name, deepcopy(self.source)),
                       MacroSource(str(path), path.stem, path=path)]
            self.window._macros.start_run(macro(), sources, open_first=False, export_folder=Path(directory))
            self.wait()
            plots = self.window._workspace.list_plots()
            self.assertEqual(len(plots), 2)
            self.assertNotEqual(plots[0].plot_id, plots[1].plot_id)
            self.assertNotEqual(plots[0].state["series"][0]["y_dataset"], plots[1].state["series"][0]["y_dataset"])
            self.assertEqual(self.window._plot_tab_widget.tabs.count(), 1)  # Only the original placeholder.
            self.assertTrue(list(Path(directory).glob("jasc_macro_run_*/run_summary.csv")))

    def test_unsaved_macro_save_cancel_and_discard_guard(self):
        controller = self.window._macros
        controller.macro = macro()
        with patch("ui.macro_controller.QMessageBox.question", return_value=QMessageBox.Cancel):
            self.assertFalse(controller.confirm_saved())
        with patch("ui.macro_controller.QMessageBox.question", return_value=QMessageBox.Save), \
             patch("ui.macro_controller.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertFalse(controller.confirm_saved())
        with patch("ui.macro_controller.QMessageBox.question", return_value=QMessageBox.Discard):
            self.assertTrue(controller.confirm_saved())

    def test_worker_affinity_heartbeat_and_safe_parent_close(self):
        from core import macro_jobs
        entered, release = Event(), Event()
        worker_threads, ticks = [], []
        original = macro_jobs.smooth_column
        def slow(*args, **kwargs):
            worker_threads.append(get_ident())
            entered.set()
            release.wait(5)
            return original(*args, **kwargs)
        timer = QTimer(self.window)
        timer.setInterval(1)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        try:
            with patch.object(macro_jobs, "smooth_column", slow):
                self.window._macros.start_run(macro(), [MacroSource(self.source.name, self.source.name, deepcopy(self.source))])
                limit = time.monotonic()+5
                while not entered.is_set() and time.monotonic() < limit:
                    QTest.qWait(5)
                self.assertTrue(entered.is_set())
                heartbeat_limit = time.monotonic()+1
                while len(ticks) < 3 and time.monotonic() < heartbeat_limit:
                    QTest.qWait(5)
                self.assertGreater(len(ticks), 2)
                self.assertNotEqual(worker_threads[0], get_ident())
                with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
                    self.window.close()
                self.assertTrue(self.window._jobs.is_running)
                release.set()
                self.wait()
                self.assertEqual(self.window._workspace.dataset_names(), [self.source.name])
                self.assertFalse(self.window._workspace.plot_names())
        finally:
            release.set()
            timer.stop()


if __name__ == "__main__":
    unittest.main()
