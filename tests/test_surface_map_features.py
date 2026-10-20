"""Regression tests for scientific 2D-map rendering and analysis tools."""

from __future__ import annotations

import os
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QVBoxLayout

from core.workspace import Workspace
from ui.plot_canvas import PlotCanvas, PlotSeries
from ui.plot_tab import PlotTab


FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "Test_Data"


class SurfaceMapFeatureTests(unittest.TestCase):
    """Exercise native/interpolated rendering, annotations, and data products."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.workspace = Workspace()
        frame = pd.read_csv(FIXTURE_DIRECTORY / "SurfaceMap_RegularGrid.csv")
        self.dataset = self.workspace.add_dataset("regular_map", frame)
        self.series = PlotSeries(
            self.dataset.name,
            "X_mm",
            self.dataset.name,
            "Y_mm",
            z_dataset=self.dataset.name,
            z_column="Signal_V",
            plot_type="heatmap",
        )
        self.canvas = PlotCanvas()

    def tearDown(self) -> None:
        self.canvas.deleteLater()

    def test_auto_mode_preserves_complete_native_grid(self) -> None:
        surface = self.canvas._surface_values(
            self.workspace, self.series, "linear", "linear"
        )
        grid_x, grid_y, grid_z = self.canvas._interpolated_surface_grid(surface)

        self.assertEqual(grid_z.shape, (5, 5))
        np.testing.assert_allclose(grid_x[0], [-2, -1, 0, 1, 2])
        np.testing.assert_allclose(grid_y[:, 0], [-2, -1, 0, 1, 2])
        self.assertEqual(float(grid_z[1, 3]), 10.0)
        self.assertEqual(float(grid_z[4, 0]), -8.0)

    def test_irregular_grid_interpolates_and_masks_outside_convex_hull(self) -> None:
        irregular = self.workspace.add_dataset(
            "irregular_map",
            pd.read_csv(FIXTURE_DIRECTORY / "SurfaceMap_Irregular.csv"),
        )
        series = replace(
            self.series,
            x_dataset=irregular.name,
            y_dataset=irregular.name,
            z_dataset=irregular.name,
            surface_render_mode="interpolated",
            grid_resolution=40,
        )
        surface = self.canvas._surface_values(
            self.workspace, series, "linear", "linear"
        )
        _grid_x, _grid_y, grid_z = self.canvas._interpolated_surface_grid(surface)

        self.assertEqual(grid_z.shape, (40, 40))
        self.assertGreater(int(np.ma.getmaskarray(grid_z).sum()), 0)
        with self.assertRaisesRegex(ValueError, "Native grid mode"):
            self.canvas._interpolated_surface_grid(
                replace(surface, series=replace(series, surface_render_mode="native"))
            )

    def test_colour_ranges_and_contour_levels_are_explicit(self) -> None:
        grid = np.ma.masked_invalid(np.asarray([[-8.0, 0.0], [5.0, 10.0]]))
        manual = replace(
            self.series,
            color_scale_mode="manual",
            color_minimum="-10",
            color_maximum="12",
            color_normalization="centered",
            color_center=0.0,
        )
        norm, minimum, maximum = self.canvas._surface_normalization(manual, grid)
        self.assertEqual((minimum, maximum), (-10.0, 12.0))
        self.assertEqual(norm.vcenter, 0.0)

        levels = self.canvas._surface_contour_levels(
            replace(
                self.series,
                contour_level_mode="custom",
                contour_custom_levels="-3, 0; 5 10",
            ),
            -8.0,
            10.0,
        )
        np.testing.assert_allclose(levels, [-3.0, 0.0, 5.0, 10.0])
        with self.assertRaisesRegex(ValueError, "positive Z"):
            self.canvas._surface_normalization(
                replace(self.series, color_normalization="log"),
                np.ma.masked_invalid(np.asarray([[-2.0, -1.0]])),
            )

    def test_measured_global_extrema_are_exact_and_identified_as_measured(self) -> None:
        annotated = replace(
            self.series,
            show_global_maximum=True,
            show_global_minimum=True,
            extrema_source="measured",
        )
        surface = self.canvas._surface_values(
            self.workspace, annotated, "linear", "linear"
        )
        grid_x, grid_y, grid_z = self.canvas._interpolated_surface_grid(surface)
        extrema = self.canvas.surface_extrema(
            surface, grid_x, grid_y, grid_z, annotated
        )

        by_kind = {item.kind: item for item in extrema}
        self.assertEqual(
            (by_kind["maximum"].x_value, by_kind["maximum"].y_value, by_kind["maximum"].z_value),
            (1.0, -1.0, 10.0),
        )
        self.assertEqual(
            (by_kind["minimum"].x_value, by_kind["minimum"].y_value, by_kind["minimum"].z_value),
            (-2.0, 2.0, -8.0),
        )
        self.assertTrue(all(item.source == "measured" for item in extrema))

    def test_render_draws_extrema_and_validity_overlays(self) -> None:
        annotated = replace(
            self.series,
            show_global_maximum=True,
            show_global_minimum=True,
            show_data_points=True,
            show_boundary=True,
            surface_aspect="equal",
            color_normalization="centered",
        )
        result = self.canvas.plot_series(self.workspace, [annotated])

        self.assertEqual(result.plotted_count, 1)
        self.assertFalse(result.skipped_messages)
        labels = "\n".join(text.get_text() for text in self.canvas.axes.texts)
        self.assertIn("Max (measured)", labels)
        self.assertIn("Min (measured)", labels)
        self.assertEqual(float(self.canvas.axes.get_aspect()), 1.0)

    def test_canvas_mouse_cut_uses_two_clicks_and_keeps_visible_overlay(self) -> None:
        self.canvas.plot_series(self.workspace, [self.series])
        selected: list[tuple[float, float, float, float]] = []
        self.canvas.surface_cut_selected.connect(
            lambda x1, y1, x2, y2: selected.append((x1, y1, x2, y2))
        )

        self.canvas.begin_surface_cut_selection()
        self.canvas._handle_canvas_button_press(SimpleNamespace(
            inaxes=self.canvas.axes,
            button=1,
            xdata=-1.5,
            ydata=-1.0,
            dblclick=False,
        ))
        self.canvas._handle_canvas_motion(SimpleNamespace(
            inaxes=self.canvas.axes,
            xdata=0.5,
            ydata=0.75,
        ))
        self.assertTrue(self.canvas.surface_cut_selection_active())
        self.assertEqual(len(self.canvas._surface_cut_artists), 2)

        self.canvas._handle_canvas_button_press(SimpleNamespace(
            inaxes=self.canvas.axes,
            button=1,
            xdata=1.5,
            ydata=1.0,
            dblclick=False,
        ))

        self.assertEqual(selected, [(-1.5, -1.0, 1.5, 1.0)])
        self.assertFalse(self.canvas.surface_cut_selection_active())
        self.assertEqual(len(self.canvas._surface_cut_artists), 2)

    def test_surface_controls_use_settings_row_then_action_row(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        layout = tab._surface_options_panel.layout()

        self.assertIsInstance(layout, QVBoxLayout)
        self.assertIsNotNone(layout.itemAt(0).layout())
        self.assertIsNotNone(layout.itemAt(1).layout())
        button_texts = {
            button.text()
            for button in tab._surface_options_panel.findChildren(QPushButton)
        }
        self.assertEqual(
            button_texts,
            {"Map Details...", "Analyse Map...", "Pick Cut Line..."},
        )
        tab.deleteLater()

    def test_grid_profiles_and_roi_statistics_create_reusable_frames(self) -> None:
        grid = self.canvas.surface_grid_frame(self.workspace, self.series)
        horizontal = self.canvas.surface_profile_frame(
            self.workspace, self.series, "horizontal", -1.0
        )
        diagonal = self.canvas.surface_line_profile_frame(
            self.workspace, self.series, -2.0, -1.0, 2.0, -1.0, 9
        )
        roi = self.canvas.surface_roi_summary_frame(
            self.workspace, self.series, -2.0, 2.0, -2.0, 2.0
        ).set_index("metric")["value"]

        self.assertEqual(len(grid), 25)
        np.testing.assert_allclose(horizontal["z"], [1, 6, 9, 10, 9])
        self.assertEqual(len(diagonal), 9)
        self.assertAlmostEqual(float(diagonal.iloc[0]["z"]), 1.0)
        self.assertAlmostEqual(float(diagonal.iloc[-1]["z"]), 9.0)
        self.assertEqual(roi["cell_count"], 25.0)
        self.assertEqual(roi["minimum"], -8.0)
        self.assertEqual(roi["maximum"], 10.0)
        self.assertAlmostEqual(roi["mean"], 4.0)
        self.assertAlmostEqual(roi["integrated_z_dx_dy"], 100.0)

    def test_contour_vertices_are_exported_as_tidy_data(self) -> None:
        contour_series = replace(
            self.series,
            contour_level_mode="custom",
            contour_custom_levels="-3 0 5 9",
        )
        contours = self.canvas.surface_contours_frame(
            self.workspace, contour_series
        )

        self.assertEqual(
            set(contours.columns),
            {"level", "segment", "vertex", "x", "y", "enclosed_area"},
        )
        self.assertTrue(set(contours["level"]).issubset({-3.0, 0.0, 5.0, 9.0}))
        self.assertGreater(len(contours), 4)

    def test_generated_grid_receives_heatmap_ready_column_roles(self) -> None:
        output = self.workspace.add_dataset(
            "rendered_grid",
            self.canvas.surface_grid_frame(self.workspace, self.series),
        )
        PlotTab._annotate_surface_analysis_dataset(output, "grid", self.series)

        self.assertEqual(output.metadata_for_column("x").role, "x")
        self.assertEqual(output.metadata_for_column("y").role, "y")
        self.assertEqual(output.metadata_for_column("z").role, "z")
        self.assertIn("regular_map:Signal_V", output.metadata_for_column("z").comment)

    def test_mouse_cut_creates_worksheet_and_profile_plot(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_plot_series(
            [self.series],
            title="Surface",
            selected_dataset_name=self.dataset.name,
        )
        tab._pending_surface_cut = (self.series, (-2.0, 2.0, -2.0, 2.0))

        class AcceptedCutDialog:
            def __init__(self, *_args: object) -> None:
                self.endpoints: tuple[float, float, float, float] | None = None

            def configure_line_profile(
                self,
                x1: float,
                y1: float,
                x2: float,
                y2: float,
            ) -> None:
                self.endpoints = (x1, y1, x2, y2)

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def output_name() -> str:
                return "mouse_cut"

            @staticmethod
            def line_profile() -> tuple[float, float, float, float, int]:
                return (-2.0, -1.0, 2.0, -1.0, 9)

        with (
            patch("ui.plot_tab.SurfaceAnalysisDialog", AcceptedCutDialog),
            patch.object(tab, "_show_surface_profile") as show_profile,
        ):
            tab._handle_surface_cut_selected(-2.0, -1.0, 2.0, -1.0)

        output = self.workspace.get_dataset("mouse_cut")
        self.assertEqual(len(output.frame), 9)
        self.assertEqual(output.metadata_for_column("distance").role, "x")
        self.assertEqual(output.metadata_for_column("z").role, "y")
        show_profile.assert_called_once()
        tab.deleteLater()

    def test_cut_profile_window_is_non_modal_and_zoomable(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        output = self.workspace.add_dataset(
            "cut_profile",
            self.canvas.surface_line_profile_frame(
                self.workspace, self.series, -2.0, -1.0, 2.0, -1.0, 9
            ),
        )

        tab._show_surface_profile(output, "line", self.series)
        self.app.processEvents()

        self.assertEqual(len(tab._surface_profile_windows), 1)
        window = tab._surface_profile_windows[0]
        self.assertFalse(window.isModal())
        profile_canvas = window._profile_canvas
        self.assertGreaterEqual(len(profile_canvas.axes.lines), 1)
        self.assertEqual(profile_canvas.axes.get_xlabel(), "Distance along cut")
        window.close()
        self.app.processEvents()
        tab.deleteLater()

    def test_advanced_surface_state_round_trips_and_malformed_values_clamp(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        configured = replace(
            self.series,
            surface_render_mode="native",
            color_scale_mode="percentile",
            color_percentile_low=5.0,
            color_percentile_high=95.0,
            contour_level_mode="interval",
            contour_interval=2.5,
            show_global_maximum=True,
            extrema_source="interpolated",
        )
        restored = tab._plot_series_from_state(asdict(configured))
        self.assertEqual(restored, configured)

        malformed = asdict(configured)
        malformed.update({
            "surface_render_mode": "unknown",
            "surface_alpha": 9.0,
            "contour_level_count": -2,
            "local_extrema_count": 500,
            "show_boundary": "yes",
        })
        restored = tab._plot_series_from_state(malformed)
        self.assertEqual(restored.surface_render_mode, "auto")
        self.assertEqual(restored.surface_alpha, 1.0)
        self.assertEqual(restored.contour_level_count, 2)
        self.assertEqual(restored.local_extrema_count, 100)
        self.assertTrue(restored.show_boundary)
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
