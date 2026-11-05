"""Persistence and workspace tests for first-class spectral analyses."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import pandas as pd
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core import project_io
from core.spectral_analysis import SpectralAnalysisSession
from core.workspace import Workspace
from ui.main_window import MainWindow
from ui.spectral_analysis_viewer import SpectralAnalysisViewer


class SpectralAnalysisSessionTests(unittest.TestCase):
    """Keep analysis results separate, reproducible, and openly persisted."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def session() -> SpectralAnalysisSession:
        return SpectralAnalysisSession(
            name="Raman map fit",
            source_dataset="Map",
            analysis_kind="raman_map",
            x_column="Raman Shift",
            y_column="Intensity",
            coordinate_columns=("X", "Y"),
            profile={"baseline": {"method": "arpls"}, "fit": {"loss": "linear"}},
            metrics_frame=pd.DataFrame({
                "X": [0.0, 1.0, 0.0, 1.0],
                "Y": [0.0, 0.0, 1.0, 1.0],
                "peak_1_area": [12.5, 13.0, 11.5, 12.0],
                "fit_success": [1.0, 1.0, 1.0, 1.0],
            }),
            curves_frame=pd.DataFrame({
                "source_sheet": ["Map.csv", "Map.csv", "Map.csv"],
                "X": [0.0, 0.0, 0.0],
                "Y": [0.0, 0.0, 0.0],
                "x": [519.0, 520.0, 521.0],
                "raw": [2.0, 9.0, 2.0],
                "preprocessing_baseline": [1.0, 1.0, 1.0],
                "corrected": [1.0, 8.0, 1.0],
                "observed": [1.0, 8.0, 1.0],
                "fit_baseline": [0.0, 0.0, 0.0],
                "total_fit": [1.1, 7.9, 1.1],
                "residual": [-0.1, 0.1, -0.1],
                "peak_1": [1.1, 7.9, 1.1],
            }),
            parameters_frame=pd.DataFrame({"parameter": ["center"], "value": [520.0]}),
            peaks_frame=pd.DataFrame({"center": [520.1], "enabled": [True]}),
        )

    def test_raman_cut_creates_saved_plot_without_exporting_internal_tables(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from ui.plot_element_dialogs import SurfaceAnalysisDialog

        window = MainWindow()
        viewer = window._spectral_analysis_viewer
        window._show_spectral_analysis(self.session())
        metric = viewer._metric_selector.findData("peak_1_area")
        viewer._metric_selector.setCurrentIndex(metric)
        original = viewer.selected_spectrum_key()
        try:
            def accept(dialog):
                dialog._line_samples.setValue(3)
                return QDialog.Accepted
            viewer._start_map_cut()
            viewer._map_clicked(SimpleNamespace(
                button=1, inaxes=viewer._map_axis, xdata=0.0, ydata=0.0,
            ))
            with patch.object(SurfaceAnalysisDialog, "exec", accept):
                viewer._map_clicked(SimpleNamespace(
                    button=1, inaxes=viewer._map_axis, xdata=1.0, ydata=0.0,
                ))
            self.assertIs(window._tabs.currentWidget(), viewer)
            self.assertEqual(viewer.selected_spectrum_key(), original)
            self.assertEqual(len(window._workspace.dataset_names()), 1)
            self.assertEqual(len(window._workspace.plot_names()), 1)
            dataset = window._workspace.list_datasets()[0]
            self.assertEqual(dataset.metadata_for_column("z").role, "y")
            self.assertIn("Raman map fit:peak_1_area", dataset.metadata_for_column("z").comment)
            self.assertEqual(dataset.frame.z.tolist(), [12.5, 12.75, 13.0])
            self.assertEqual(window._plot_list.count(), 2)
            self.assertIsNone(viewer._cut_points)
            saved = window._workspace.list_plots()[0]
            window._plot_tab_widget.load_plot_state(saved.state)
            self.assertEqual(len(window._plot_tab_widget._plot_canvas.axes.lines), 1)
        finally:
            with patch.object(window, "_confirm_project_plot_changes", return_value=True):
                window.close()
            window.deleteLater()

    def test_raman_horizontal_and_vertical_cuts_use_selected_metric(self) -> None:
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from ui.plot_element_dialogs import SurfaceAnalysisDialog

        viewer = SpectralAnalysisViewer()
        viewer.set_analysis(self.session())
        viewer._metric_selector.setCurrentIndex(viewer._metric_selector.findData("peak_1_area"))
        created = []
        viewer.map_analysis_created.connect(lambda *args: created.append(args))
        try:
            for operation, expected in (("horizontal", [12.5, 13.0]),
                                        ("vertical", [12.5, 11.5])):
                def accept(dialog):
                    dialog._operation.setCurrentIndex(dialog._operation.findData(operation))
                    dialog._coordinate.setValue(0.0)
                    return QDialog.Accepted
                with patch.object(SurfaceAnalysisDialog, "exec", accept):
                    viewer._create_map_cut()
                series, result_operation, _name, frame = created[-1]
                self.assertEqual(result_operation, operation)
                self.assertEqual(series.z_column, "peak_1_area")
                self.assertEqual(frame.z.tolist(), expected)
            self.assertEqual(len(created), 2)
        finally:
            viewer.deleteLater()

    def test_map_cut_cancels_on_escape_metric_change_and_dialog_cancel(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from ui.plot_element_dialogs import SurfaceAnalysisDialog

        viewer = SpectralAnalysisViewer()
        viewer.set_analysis(self.session())
        created = []
        viewer.map_analysis_created.connect(lambda *args: created.append(args))
        try:
            viewer._start_map_cut()
            viewer._cut_key_pressed(SimpleNamespace(key="escape"))
            self.assertIsNone(viewer._cut_points)
            viewer._start_map_cut()
            viewer._metric_selector.setCurrentIndex(1)
            self.assertIsNone(viewer._cut_points)
            with patch.object(SurfaceAnalysisDialog, "exec", return_value=QDialog.Rejected):
                viewer._create_map_cut((0.0, 0.0, 1.0, 1.0))
            self.assertEqual(created, [])
            viewer.set_analysis(None)
            self.assertFalse(viewer._map_cuts.isEnabled())
            self.assertFalse(viewer._pick_cut.isEnabled())
        finally:
            viewer.deleteLater()

    def test_workspace_keeps_analyses_outside_dataset_registry(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("Map", pd.DataFrame({"X": [0.0], "Y": [1.0]}))
        analysis = workspace.add_spectral_analysis(self.session())
        self.assertEqual(workspace.dataset_names(), ["Map"])
        self.assertEqual(workspace.spectral_analysis_names(), [analysis.name])
        duplicate = workspace.duplicate_spectral_analysis(analysis.name)
        self.assertNotEqual(duplicate.name, analysis.name)
        duplicate.metrics_frame.loc[0, "peak_1_area"] = 99.0
        self.assertEqual(analysis.metrics_frame.loc[0, "peak_1_area"], 12.5)

    def test_project_round_trip_writes_readable_analysis_csv_members(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("Map", pd.DataFrame({"X": [0.0], "Y": [1.0]}))
        workspace.add_spectral_analysis(self.session())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "analysis.jasc"
            project_io.save_project(workspace, path)
            loaded = project_io.load_project(path)
        analysis = loaded.get_spectral_analysis("Raman map fit")
        self.assertEqual(analysis.coordinate_columns, ("X", "Y"))
        self.assertEqual(analysis.profile["baseline"]["method"], "arpls")
        pd.testing.assert_frame_equal(
            analysis.metrics_frame,
            workspace.get_spectral_analysis("Raman map fit").metrics_frame,
        )

    def test_viewer_links_metric_map_spectrum_residual_and_distribution(self) -> None:
        viewer = SpectralAnalysisViewer()
        try:
            viewer.set_analysis(self.session())
            self.assertEqual(viewer.analysis.name, "Raman map fit")
            self.assertEqual(viewer.selected_metric(), "peak_1_area")
            self.assertEqual(
                dict(viewer.selected_spectrum_key()),
                {"source_sheet": "Map.csv", "X": 0.0, "Y": 0.0},
            )
            self.assertEqual(len(viewer._figure.axes), 3)  # map, linked fit, and colour bar
            self.assertEqual(len(viewer._residual_figure.axes), 1)
            self.assertEqual(len(viewer._distribution_figure.axes), 1)
            self.assertEqual(viewer._detail_tabs.count(), 3)
            self.assertTrue(viewer._detail_tabs.isHidden())
            viewer._show_diagnostics.setChecked(True)
            self.assertFalse(viewer._detail_tabs.isHidden())
            self.assertEqual(viewer._spectrum_axis.get_title(), "X=0.0 · Y=0.0")
        finally:
            viewer.deleteLater()

    def test_viewer_direct_edit_targets_and_curve_visibility(self) -> None:
        viewer = SpectralAnalysisViewer()
        try:
            viewer.resize(1200, 700)
            viewer.set_analysis(self.session())
            viewer.show()
            self.app.processEvents()
            viewer._canvas.draw()

            x_label_bounds = viewer._spectrum_axis.xaxis.label.get_window_extent(
                viewer._canvas.get_renderer()
            )
            target = viewer._editable_element_at(
                (x_label_bounds.x0 + x_label_bounds.x1) / 2.0,
                (x_label_bounds.y0 + x_label_bounds.y1) / 2.0,
            )
            self.assertEqual(target, ("spectrum", "x"))

            legend_bounds = viewer._spectrum_axis.get_legend().get_window_extent(
                viewer._canvas.get_renderer()
            )
            target = viewer._editable_element_at(
                (legend_bounds.x0 + legend_bounds.x1) / 2.0,
                (legend_bounds.y0 + legend_bounds.y1) / 2.0,
            )
            self.assertEqual(target, ("spectrum", "legend"))

            viewer._curve_visibility["raw"] = False
            viewer._curve_visibility["preprocessing_baseline"] = False
            viewer._redraw()
            displayed_columns = {line.get_gid() for line in viewer._spectrum_axis.lines}
            self.assertNotIn("raw", displayed_columns)
            self.assertNotIn("preprocessing_baseline", displayed_columns)
            self.assertIn("corrected", displayed_columns)
            self.assertIn("total_fit", displayed_columns)
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_raman_results_tab_is_contextual_and_analysis_navigation_tracks_content(self) -> None:
        window = MainWindow()
        try:
            self.assertEqual(
                [window._tabs.tabText(index) for index in range(window._tabs.count())],
                ["Data", "Plots"],
            )
            self.assertEqual(window._tabs.indexOf(window._spectral_analysis_viewer), -1)
            analysis_nav_index = window._workspace_nav_tabs.indexOf(
                window._analysis_nav_page
            )
            self.assertFalse(window._workspace_nav_tabs.isTabVisible(analysis_nav_index))

            analysis = window._workspace.add_spectral_analysis(self.session())
            window._refresh_spectral_analysis_list(analysis.name)
            self.assertTrue(window._workspace_nav_tabs.isTabVisible(analysis_nav_index))
            self.assertEqual(window._tabs.indexOf(window._spectral_analysis_viewer), -1)

            window._load_selected_spectral_analysis()
            result_index = window._tabs.indexOf(window._spectral_analysis_viewer)
            self.assertGreaterEqual(result_index, 0)
            self.assertEqual(window._tabs.tabText(result_index), "Raman Results")
            self.assertIs(window._tabs.currentWidget(), window._spectral_analysis_viewer)
            self.assertIs(
                window._workspace_nav_tabs.currentWidget(), window._analysis_nav_page
            )

            window._hide_spectral_analysis_tab()
            self.assertEqual(window._tabs.indexOf(window._spectral_analysis_viewer), -1)
            self.assertIs(window._tabs.currentWidget(), window._data_tab_widget)
        finally:
            with patch.object(window, "_confirm_project_plot_changes", return_value=True):
                window.close()
