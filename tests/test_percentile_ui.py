"""Asymmetric bound selection, real rendering, persistence, and fitting workflows."""

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
from PySide6.QtWidgets import QTabWidget
from PySide6.QtTest import QTest

from core import project_io
from models.uncertainty import PercentileBounds
from ui.dialogs import FigureDigitizerDialog, FitDialog, select_list_items
from ui.main_window import MainWindow
from ui.plot_canvas import PlotSeries


class PercentileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        gc.collect()
        self.window = MainWindow()
        self.manager = self.window._plot_tab_widget
        x = np.linspace(1, 8, 35)
        y = 2*x + 3 + np.random.default_rng(3).normal(0, .2, len(x))
        self.data = self.window._workspace.add_dataset("signal", pd.DataFrame({
            "x": x, "y": y, "xl": x-.1, "xh": x+.3, "yl": y-.3, "yh": y+.6}))
        self.window._refresh_dataset_list(self.data.name)

    def tearDown(self) -> None:
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def plot(self) -> object:
        self.manager.queue_plot_series([PlotSeries(self.data.name, "x", self.data.name, "y", plot_type="errorbar",
                                                  x_bounds=PercentileBounds("xl", "xh"),
                                                  y_bounds=PercentileBounds("yl", "yh", .05, .95))], "Intervals")
        return self.manager.active_document

    def dialog(self) -> FitDialog:
        dialog = FitDialog(list(self.data.frame.columns), self.data.name, default_x_column="x",
                           dataset_names=[self.data.name], current_dataset_name=self.data.name, parent=self.window)
        select_list_items(dialog._y_column_list, ["y"])
        dialog._model_combo.setCurrentIndex(dialog._model_combo.findData("linear"))
        dialog._y_bounds_editor.enabled_check.setChecked(True)
        dialog._y_bounds_editor.lower_combo.setCurrentText("yl")
        dialog._y_bounds_editor.upper_combo.setCurrentText("yh")
        return dialog

    def test_native_errorbars_keep_separate_x_y_lower_and_upper_values(self) -> None:
        self.plot()
        editor = self.manager._active_editor
        series = editor._plot_series[0]
        _, _, xerr, yerr = editor._plot_canvas._series_values(self.window._workspace, series, "linear", "linear")
        np.testing.assert_allclose(xerr, np.vstack((np.full(35, .1), np.full(35, .3))))
        np.testing.assert_allclose(yerr, np.vstack((np.full(35, .3), np.full(35, .6))))
        collections = editor._plot_canvas.axes.collections
        self.assertEqual(len(collections), 2)
        segment = collections[1].get_segments()[0]
        np.testing.assert_allclose(segment[:, 1], [self.data.frame.yl.iloc[0], self.data.frame.yh.iloc[0]])
        self.assertEqual(series.y_bounds.lower_probability, .05)

    def test_applied_and_pending_probability_fields_survive_tab_and_project_reopen(self) -> None:
        plot = self.plot()
        editor = self.manager._active_editor
        editor._y_bounds_editor.lower_probability_spin.setValue(10.)
        editor._y_bounds_editor.upper_probability_spin.setValue(90.)
        editor._y_bounds_editor.centre_combo.setCurrentIndex(1)
        self.assertTrue(editor.has_unapplied_series_edits())
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.manager.open_plot(plot.name)
        self.assertEqual(self.manager._active_editor._y_bounds_editor.lower_probability_spin.value(), 10.)
        self.assertEqual(self.manager._active_editor._plot_series[0].y_bounds.lower_probability, .05)
        self.manager.flush()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"intervals.jasc"
            project_io.save_project(self.window._workspace, path)
            loaded = project_io.load_project(path)
        self.window._workspace = loaded
        self.manager.set_workspace(loaded)
        self.manager.open_plot(plot.name)
        self.assertEqual(self.manager._active_editor._y_bounds_editor.upper_probability_spin.value(), 90.)
        self.assertTrue(self.manager.has_unapplied_series_edits())
        self.assertEqual(self.manager._active_editor._y_bounds_editor.centre_combo.currentData(), "mean")
        self.assertFalse(self.manager.is_dirty())

    def test_column_renames_retarget_applied_and_pending_bounds(self) -> None:
        plot = self.plot()
        self.manager._active_editor._y_bounds_editor.upper_probability_spin.setValue(90.)
        mapping = {"yl": "lower", "yh": "upper", "xl": "xlow"}
        self.data.frame.rename(columns=mapping, inplace=True)
        self.window._workspace.rename_column_references_in_plots(self.data.name, mapping)
        self.manager.rename_column_references(self.data.name, mapping)
        self.assertEqual(self.manager._active_editor._plot_series[0].y_bounds.lower_column, "lower")
        self.assertEqual(self.manager._active_editor._y_bounds_editor.upper_combo.currentText(), "upper")
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.manager.open_plot(plot.name)
        self.assertEqual(self.manager._active_editor._plot_series[0].x_bounds.lower_column, "xlow")

    def test_partial_selection_stays_a_draft_and_validation_is_visible(self) -> None:
        self.manager.queue_single_series_plot(self.data, "x", "y", "Draft")
        editor = self.manager._active_editor
        editor._set_combo_data(editor._plot_type_combo, "errorbar")
        editor._y_bounds_editor.enabled_check.setChecked(True)
        self.assertTrue(editor.has_unapplied_series_edits())
        with patch("ui.plot_tab.QMessageBox.warning") as warning:
            editor._update_selected_series()
        warning.assert_called_once()
        self.assertIsNone(editor._plot_series[0].y_bounds)
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.manager.open_plot("Draft")
        self.assertTrue(self.manager._active_editor._y_bounds_editor.enabled_check.isChecked())

    def test_curve_fit_dialog_runs_and_generated_plot_preserves_bound_mapping(self) -> None:
        dialog = self.dialog()
        self.assertEqual(dialog.method(), "percentile")
        with patch("ui.main_window.FitReportDialog.exec", lambda _dialog: QDialog.Accepted), \
             patch("ui.main_window.QMessageBox.warning") as warning:
            self.window._run_curve_fit_batch(self.data, dialog, [1., 1.], [None, None], [None, None], [False, False])
        warning.assert_not_called()
        editor = self.manager._active_editor
        self.assertEqual(editor._plot_series[0].y_bounds.lower_column, "yl")
        self.assertTrue(editor._plot_canvas.axes.collections)
        fit_data = self.window._workspace.get_dataset("signal_fit")
        fields = dict(fit_data.worksheet_metadata.fields)
        details = json.loads(fields["Percentile uncertainty"])
        self.assertEqual(details["y"]["distribution"], "quantile_normal")
        self.assertEqual(details["y"]["lower_probability"], .16)
        residuals = self.window._workspace.get_dataset("signal_residuals").frame
        self.assertIn("y_lower_bound", residuals)
        dialog.deleteLater()

    def test_dialog_rejects_posterior_fitting_and_ambiguous_multi_y_mapping(self) -> None:
        dialog = self.dialog()
        dialog._y_bounds_editor.origin_combo.setCurrentIndex(1)
        with patch("ui.dialogs.QMessageBox.warning") as warning:
            dialog.accept()
        self.assertIn("Posterior", warning.call_args.args[2])
        dialog._y_bounds_editor.origin_combo.setCurrentIndex(0)
        dialog._y_bounds_editor.centre_combo.setCurrentIndex(1)
        with patch("ui.dialogs.QMessageBox.warning") as warning:
            dialog.accept()
        self.assertIn("median", warning.call_args.args[2])
        dialog._y_bounds_editor.centre_combo.setCurrentIndex(0)
        select_list_items(dialog._y_column_list, ["y", "yh"])
        with patch("ui.dialogs.QMessageBox.warning") as warning:
            dialog.accept()
        self.assertIn("one Y", warning.call_args.args[2])
        dialog.deleteLater()

    def test_exact_probability_levels_do_not_become_dirty_from_display_rounding(self) -> None:
        from scipy.special import ndtr
        spec = PercentileBounds("yl", "yh", float(ndtr(-1)), float(ndtr(1)))
        self.manager.queue_plot_series([PlotSeries(self.data.name, "x", self.data.name, "y", plot_type="errorbar",
                                                  y_bounds=spec)], "Exact coverage")
        editor = self.manager._active_editor
        self.assertEqual(editor._y_bounds_editor.specification(), spec)
        self.assertFalse(editor.has_unapplied_series_edits())
        self.manager.mark_saved()
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.manager.open_plot("Exact coverage")
        self.assertEqual(self.manager._active_editor._y_bounds_editor.specification(), spec)
        self.assertFalse(self.manager.is_dirty())

    def test_percentile_editors_scroll_instead_of_collapsing_in_fit_dialog(self) -> None:
        dialog = self.dialog()
        dialog._x_bounds_editor.enabled_check.setChecked(True)
        dialog._x_bounds_editor.lower_combo.setCurrentText("xl")
        dialog._x_bounds_editor.upper_combo.setCurrentText("xh")
        dialog.resize(950, 700)
        dialog.show()
        for tabs in dialog.findChildren(QTabWidget):
            for index in range(tabs.count()):
                if tabs.tabText(index) == "Uncertainty":
                    tabs.setCurrentIndex(index)
        QTest.qWait(20)
        self.assertGreater(dialog._uncertainty_scroll.verticalScrollBar().maximum(), 0)
        self.assertGreaterEqual(dialog._x_bounds_editor.lower_combo.height(), 16)
        self.assertGreaterEqual(dialog._y_bounds_editor.upper_combo.height(), 16)
        for editor in (dialog._x_bounds_editor, dialog._y_bounds_editor):
            self.assertGreaterEqual(editor._note.height(), editor._note.heightForWidth(editor._note.width()))
        dialog._uncertainty_scroll.ensureWidgetVisible(dialog._y_bounds_editor.upper_combo)
        self.assertGreater(dialog._uncertainty_scroll.verticalScrollBar().value(), 0)
        dialog.hide()
        dialog.deleteLater()

    def test_digitizer_retains_four_asymmetric_graphical_endpoints(self) -> None:
        dialog = FigureDigitizerDialog(parent=self.window)
        point = {"pixel_x": 50., "pixel_y": 80.}
        dialog._manual_points = [point]
        dialog._manual_error_target_index = 0
        with patch.object(dialog, "_set_click_target"), \
             patch.object(dialog, "_pixel_to_data", side_effect=lambda x, y: (x/10, 20-y/10)):
            for x, y in ((40., 80.), (70., 80.), (50., 60.), (50., 90.)):
                dialog._add_manual_four_point_uncertainty(x, y)
            row = dialog.extracted_rows()[0]
        self.assertEqual((row["x_lower_bound"], row["x_upper_bound"]), (4., 7.))
        self.assertEqual((row["y_lower_bound"], row["y_upper_bound"]), (11., 14.))
        frame = self.window._figure_extraction_frame((row,))
        self.assertIn("x_lower_bound", frame)
        self.assertEqual(point["uncertainty_source"], "four-point")
        dialog.deleteLater()

    def test_comparisons_keep_asymmetric_errorbars_independent(self) -> None:
        first = self.plot()
        second = self.window._workspace.duplicate_plot(first.name)
        from core.plot_comparison import comparison_state
        before = deepcopy(first.state)
        self.manager.new_comparison("Bound comparison", comparison_state([first.plot_id, second.plot_id], 1, 2))
        for _, canvas in self.manager._active_editor._panels:
            self.assertEqual(len(canvas.axes.collections), 2)
        self.assertEqual(first.state, before)


if __name__ == "__main__":
    unittest.main()
