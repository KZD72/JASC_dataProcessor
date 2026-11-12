"""Worksheet choice and persistent/exportable curve-fit reports in real GUI paths."""
from __future__ import annotations

from copy import deepcopy
import gc
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from core import project_io
from math_engine.calculus import MathOperationError
from tests.test_api_recording import replay, methods
from ui.dialogs import FitDialog, select_list_items
from ui.main_window import MainWindow


ROOT = Path(__file__).resolve().parents[1]


class FitWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()
        self.other = self.window._workspace.add_dataset("Other", pd.DataFrame({"time": range(6), "response": np.arange(6)*4 + 1}))
        self.data = self.window._workspace.add_dataset("Measurements", pd.read_csv(
            ROOT/"Test_Data/Feature_Examples/09_Asymmetric_Uncertainty/input/percentiles.csv"))
        self.other.metadata_for_column("time").role = "x"
        self.window._refresh_dataset_list(self.other.name)

    def tearDown(self) -> None:
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def dialog(self) -> FitDialog:
        return FitDialog(list(self.data.frame), self.data.name, default_x_column="x", parent=self.window,
                         dataset_columns={self.data.name: list(self.data.frame), self.other.name: list(self.other.frame)},
                         dataset_x_columns={self.other.name: "time"})

    @staticmethod
    def choose_percentile_fit(dialog: FitDialog) -> int:
        dialog._source_dataset_combo.setCurrentText("Measurements")
        select_list_items(dialog._y_column_list, ["y"])
        dialog._model_combo.setCurrentIndex(dialog._model_combo.findData("linear"))
        dialog._y_bounds_editor.enabled_check.setChecked(True)
        dialog._y_bounds_editor.lower_combo.setCurrentText("y_p16")
        dialog._y_bounds_editor.upper_combo.setCurrentText("y_p84")
        dialog.accept()
        return dialog.result()

    def test_switching_worksheet_rebuilds_all_column_mappings_and_default_names(self) -> None:
        dialog = self.dialog()
        self.choose_percentile_fit(dialog)
        dialog._source_dataset_combo.setCurrentText(self.other.name)
        self.assertEqual(dialog.source_dataset_name(), "Other")
        self.assertEqual(dialog.x_column(), "time")
        self.assertEqual(dialog.y_columns(), [])
        self.assertEqual(dialog.weight_columns(), [])
        self.assertIsNone(dialog.x_weight_column())
        self.assertIsNone(dialog.y_bounds())
        self.assertEqual(dialog._y_bounds_editor.lower_combo.findText("y_p16"), -1)
        self.assertNotEqual(dialog._y_bounds_editor.lower_combo.findText("response"), -1)
        self.assertEqual(dialog.method(), "trf")
        self.assertEqual(dialog.target_dataset_names(), ["Other"])
        self.assertEqual(dialog.target_dataset_name(), "Other_fit")
        self.assertEqual(dialog.residual_dataset_name(), "Other_residuals")
        dialog._target_dataset_edit.setText("My chosen result")
        select_list_items(dialog._dataset_list, ["Other", "Measurements"])
        dialog._source_dataset_combo.setCurrentText("Measurements")
        self.assertEqual(dialog.target_dataset_name(), "My chosen result")
        self.assertCountEqual(dialog.target_dataset_names(), ["Other", "Measurements"])
        dialog.deleteLater()

    def test_main_entry_point_uses_the_selected_source_instead_of_the_sidebar(self) -> None:
        with patch("ui.main_window.FitDialog.exec", self.choose_percentile_fit), \
             patch.object(self.window, "_run_curve_fit_batch") as run:
            self.window._run_curve_fit()
        self.assertIs(run.call_args.kwargs["current_dataset"], self.data)
        self.assertEqual(run.call_args.kwargs["dialog"].target_dataset_names(), [self.data.name])

    def test_dialog_can_open_with_loaded_sheets_when_sidebar_has_no_current_sheet(self) -> None:
        with patch.object(self.window, "_current_dataset", return_value=None), \
             patch("ui.main_window.FitDialog.exec", self.choose_percentile_fit), \
             patch.object(self.window, "_run_curve_fit_batch") as run:
            self.window._run_curve_fit()
        self.assertIs(run.call_args.kwargs["current_dataset"], self.data)

    def test_single_percentile_report_exports_persists_and_replays_from_selected_worksheet(self) -> None:
        starting = deepcopy(self.window._workspace)
        controller = self.window._macros
        controller.start_recording(name="Persistent percentile report")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            exported = folder/"report.csv"

            def inspect_report(viewer) -> int:
                self.assertTrue(viewer._report_edit.isReadOnly())
                self.assertIn("quantile_normal", viewer._report_edit.toPlainText())
                viewer._copy_button.click()
                self.assertEqual(self.app.clipboard().text(), viewer._report_edit.toPlainText())
                viewer._export_button.click()
                viewer._open_button.click()
                return QDialog.Accepted

            with patch("ui.main_window.FitDialog.exec", self.choose_percentile_fit), \
                 patch("ui.main_window.FitReportDialog.exec", inspect_report), \
                 patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(str(exported), "CSV Files (*.csv)")), \
                 patch("ui.main_window.QMessageBox.warning") as warning, \
                 patch("ui.main_window.QMessageBox.critical") as critical:
                self.window._run_curve_fit()
            warning.assert_not_called()
            critical.assert_not_called()
            report_sheet = self.window._workspace.get_dataset("Measurements_fit_report")
            report = report_sheet.frame.iloc[0]
            self.assertEqual(report.source_sheet, self.data.name)
            self.assertEqual(report.point_count, len(self.data.frame))
            self.assertEqual(report.method, "percentile")
            self.assertAlmostEqual(report.param_a, 1.7, delta=.15)
            self.assertAlmostEqual(report.param_b, 2., delta=.15)
            self.assertTrue(np.isfinite(report.stderr_a))
            self.assertEqual(json.loads(report.y_percentile_bounds)["lower_probability"], .16)
            self.assertEqual(pd.read_csv(exported).report_text.iloc[0], report.report_text)
            self.assertIs(self.window._current_dataset(), report_sheet)
            self.assertIs(self.window._tabs.currentWidget(), self.window._data_tab_widget)
            self.window._plot_tab_widget.flush()
            path = folder/"saved.jasc"
            project_io.save_project(self.window._workspace, path)
            restored = project_io.load_project(path)
            self.assertEqual(restored.get_dataset(report_sheet.name).frame.report_text.iloc[0], report.report_text)
            controller.stop_recording()
            recording = controller.api_recording
            self.assertEqual(recording.issues, [])
            self.assertIn("result_row", methods(recording))
            self.assertIn("collect_rows", methods(recording))
            self.assertIn("export_data", methods(recording))
            output = folder/"replayed"
            output.mkdir()
            replay(recording.source(), starting, output_root=output)
            replayed = starting.get_dataset(report_sheet.name).frame.iloc[0]
            self.assertEqual(replayed.report_text, report.report_text)
            self.assertAlmostEqual(replayed.param_a, report.param_a)
            self.assertEqual(pd.read_csv(output/"report.csv").report_text.iloc[0], report.report_text)

    def test_repeated_fits_keep_separate_reports_without_residual_sheets(self) -> None:
        dialog = FitDialog(list(self.other.frame), self.other.name, default_x_column="time", parent=self.window)
        dialog._model_combo.setCurrentIndex(dialog._model_combo.findData("linear"))
        select_list_items(dialog._y_column_list, ["response"])
        dialog._residual_sheet_checkbox.setChecked(False)
        dialog._plot_residuals_checkbox.setChecked(False)
        with patch("ui.main_window.FitReportDialog.exec", return_value=QDialog.Accepted), \
             patch("ui.main_window.QMessageBox.warning") as warning:
            for slope, intercept in ((4., 1.), (5., -1.)):
                self.other.frame["response"] = self.other.frame.time*slope + intercept
                self.window._run_curve_fit_batch(self.other, dialog, [1., 0.], [None, None], [None, None], [False, False])
        warning.assert_not_called()
        reports = [sheet for sheet in self.window._workspace.list_datasets() if "report_text" in sheet.frame]
        self.assertEqual(len(reports), 2)
        self.assertNotEqual(reports[0].name, reports[1].name)
        self.assertAlmostEqual(reports[0].frame.param_a.iloc[0], 4.)
        self.assertAlmostEqual(reports[0].frame.param_b.iloc[0], 1.)
        self.assertAlmostEqual(reports[1].frame.param_a.iloc[0], 5.)
        self.assertAlmostEqual(reports[1].frame.param_b.iloc[0], -1.)
        self.assertFalse(any("residuals" in name for name in self.window._workspace.dataset_names()))
        dialog.deleteLater()

    def test_failed_fit_does_not_create_a_success_report(self) -> None:
        dialog = self.dialog()
        self.choose_percentile_fit(dialog)
        with patch("ui.main_window.fit_curve", side_effect=MathOperationError("Invalid measurement")), \
             patch("ui.main_window.QMessageBox.warning") as warning, \
             patch("ui.main_window.FitReportDialog.exec") as viewer:
            self.window._run_curve_fit_batch(self.data, dialog, [1., 0.], [None, None], [None, None], [False, False])
        warning.assert_called_once()
        viewer.assert_not_called()
        self.assertEqual(self.window._workspace.dataset_names(), ["Other", "Measurements"])
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
