"""Tests for versioned plot settings and configurable legend rendering."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from core import project_io
from core.workspace import Workspace
from models.plot_settings import LegendSettings, PLOT_STATE_VERSION, PlotSettings
from ui.plot_canvas import PlotCanvas, PlotLocator, PlotSeries
from ui.plot_tab import PlotTab


class PlotSettingsTests(unittest.TestCase):
    """Verify migration and canonical serialization independently of Qt widgets."""

    def test_flat_version_two_settings_migrate_to_typed_state(self) -> None:
        settings = PlotSettings.from_state({
            "title": "Legacy",
            "x_label": "Time",
            "x_scale": "log",
            "x_min": "1",
            "legend_enabled": False,
            "legend_position": "lower left",
            "figure_width": 8.5,
            "plot_style_preset": "science",
        })
        self.assertEqual(settings.title, "Legacy")
        self.assertEqual(settings.x_axis.label, "Time")
        self.assertEqual(settings.x_axis.scale, "log")
        self.assertFalse(settings.legend.enabled)
        self.assertEqual(settings.legend.location, "lower left")
        self.assertEqual(settings.figure.width, 8.5)
        self.assertEqual(settings.style.preset, "science")
        self.assertIn("axes", settings.to_state())
        self.assertIn("legend", settings.to_state())

    def test_malformed_new_settings_fall_back_and_clamp(self) -> None:
        settings = PlotSettings.from_state({
            "axes": {"x": {"scale": "invalid"}},
            "legend": {"font_size": -2, "columns": 500, "location": "invalid"},
            "figure": {"width": "bad", "height": 1000},
        })
        self.assertEqual(settings.x_axis.scale, "linear")
        self.assertEqual(settings.legend.font_size, 5.0)
        self.assertEqual(settings.legend.columns, 20)
        self.assertEqual(settings.legend.location, "best")
        self.assertEqual(settings.figure.width, 7.0)
        self.assertEqual(settings.figure.height, 15.0)

    def test_version_three_plot_settings_survive_project_round_trip(self) -> None:
        workspace = Workspace()
        state = {
            "version": PLOT_STATE_VERSION,
            "series": [],
            "locators": [],
            "settings": PlotSettings(
                title="Publication plot",
                legend=LegendSettings(
                    location="outside right",
                    font_size=13.0,
                    title="Legend",
                    columns=2,
                ),
            ).to_state(),
        }
        workspace.add_plot("Figure 1", state)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "appearance.jasc"
            project_io.save_project(workspace, path)
            loaded = project_io.load_project(path)
        self.assertEqual(loaded.get_plot("Figure 1").state, state)


class PlotAppearanceGuiTests(unittest.TestCase):
    """Exercise legend artists, ordering, persistence, and debounced preview."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.workspace = Workspace()
        self.dataset = self.workspace.add_dataset(
            "signals",
            pd.DataFrame({
                "x": [1.0, 2.0, 3.0],
                "left": [2.0, 3.0, 5.0],
                "right": [7.0, 6.0, 8.0],
            }),
        )

    def test_combined_legend_follows_series_order_and_applies_typography(self) -> None:
        canvas = PlotCanvas()
        series = [
            PlotSeries(
                "signals", "x", "signals", "right",
                y_axis="right", custom_label="Right first",
            ),
            PlotSeries(
                "signals", "x", "signals", "left",
                y_axis="left", custom_label="Left second",
            ),
        ]
        result = canvas.plot_series(
            self.workspace,
            series,
            legend_settings=LegendSettings(
                location="outside right",
                font_size=14.0,
                title="Measurements",
                title_font_size=12.0,
                columns=2,
                frame_enabled=False,
            ),
        )
        self.assertEqual(result.plotted_count, 2)
        legend = canvas.axes.get_legend()
        self.assertIsNotNone(legend)
        self.assertEqual([text.get_text() for text in legend.get_texts()], [
            "Right first", "Left second",
        ])
        self.assertEqual(legend.get_texts()[0].get_fontsize(), 14.0)
        self.assertEqual(legend.get_title().get_text(), "Measurements")
        self.assertEqual(legend.get_title().get_fontsize(), 12.0)
        self.assertFalse(legend.get_frame_on())
        self.assertEqual(legend._ncols, 2)
        self.assertAlmostEqual(canvas.figure.subplotpars.right, 0.75)
        canvas.deleteLater()

    def test_locator_can_be_excluded_from_legend_without_disabling_lookup(self) -> None:
        canvas = PlotCanvas()
        series = [PlotSeries("signals", "x", "signals", "left", custom_label="Signal")]
        result = canvas.plot_series(
            self.workspace,
            series,
            locators=[PlotLocator(series_index=0, x_value=2.0)],
            legend_settings=LegendSettings(include_locators=False),
        )
        self.assertEqual(len(result.located_points), 1)
        legend = canvas.axes.get_legend()
        self.assertEqual([text.get_text() for text in legend.get_texts()], ["Signal"])
        canvas.deleteLater()

    def test_series_can_be_excluded_from_combined_legend(self) -> None:
        canvas = PlotCanvas()
        canvas.plot_series(
            self.workspace,
            [
                PlotSeries(
                    "signals", "x", "signals", "left",
                    custom_label="Hidden", show_in_legend=False,
                ),
                PlotSeries(
                    "signals", "x", "signals", "right",
                    custom_label="Visible", y_axis="right",
                ),
            ],
            legend_settings=LegendSettings(),
        )
        legend = canvas.axes.get_legend()
        self.assertEqual([text.get_text() for text in legend.get_texts()], ["Visible"])
        canvas.deleteLater()

    def test_plot_tab_migrates_legacy_state_and_debounces_preview(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.load_plot_state({
            "version": 2,
            "series": [{
                "x_dataset": "signals",
                "x_column": "x",
                "y_dataset": "signals",
                "y_column": "left",
            }],
            "locators": [],
            "settings": {
                "title": "Legacy plot",
                "legend_position": "upper left",
                "figure_width": 8.0,
            },
        })
        state = tab.current_plot_state()
        self.assertEqual(state["version"], PLOT_STATE_VERSION)
        self.assertEqual(state["settings"]["legend"]["location"], "upper left")
        self.assertEqual(state["settings"]["figure"]["width"], 8.0)

        tab._legend_font_size_spin.setValue(15.0)
        self.assertTrue(tab._preview_dirty)
        QTest.qWait(250)
        self.app.processEvents()
        legend = tab._plot_canvas.axes.get_legend()
        self.assertEqual(legend.get_texts()[0].get_fontsize(), 15.0)
        self.assertFalse(tab._preview_dirty)
        tab.deleteLater()

    def test_live_preview_reports_invalid_range_without_modal_dialog(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_single_series_plot(self.dataset, "x", "left", "Signal")
        with patch.object(QMessageBox, "warning") as warning:
            tab._x_min_edit.setText("not-a-number")
            QTest.qWait(250)
            self.app.processEvents()
        warning.assert_not_called()
        self.assertTrue(tab._preview_dirty)
        self.assertEqual(tab._preview_status_label.text(), "Fix invalid plot settings")
        tab.deleteLater()

    def test_selected_series_can_be_changed_to_every_2d_map_subtype(self) -> None:
        grid_x, grid_y = np.meshgrid(
            np.linspace(-2.0, 2.0, 8),
            np.linspace(-1.0, 1.0, 7),
        )
        map_dataset = self.workspace.add_dataset(
            "map",
            pd.DataFrame({
                "x": grid_x.ravel(),
                "y": grid_y.ravel(),
                "z": (np.sin(grid_x) * np.cos(2.0 * grid_y)).ravel(),
            }),
        )
        for subtype in ("heatmap", "contour", "contourf"):
            with self.subTest(subtype=subtype):
                tab = PlotTab(self.workspace, external_options=False)
                tab.queue_single_series_plot(self.dataset, "x", "left", "Initial line")
                tab._set_combo_data(tab._plot_family_combo, "surface")
                tab._set_combo_data(tab._plot_type_combo, subtype)
                tab._x_dataset_combo.setCurrentText(map_dataset.name)
                tab._x_column_combo.setCurrentText("x")
                tab._y_dataset_combo.setCurrentText(map_dataset.name)
                tab._y_column_combo.setCurrentText("y")
                tab._z_dataset_combo.setCurrentText(map_dataset.name)
                tab._z_column_combo.setCurrentText("z")
                QTest.qWait(250)
                self.app.processEvents()

                self.assertEqual(tab._plot_series[0].plot_type, subtype)
                self.assertEqual(tab._plot_series[0].z_column, "z")
                self.assertGreater(len(tab._plot_canvas.axes.collections), 0)
                self.assertEqual(tab._preview_status_label.text(), "Preview current")
                tab.deleteLater()

    def test_invalid_2d_map_shows_canvas_error_instead_of_white_plot(self) -> None:
        collinear = self.workspace.add_dataset(
            "collinear",
            pd.DataFrame({
                "x": [0.0, 1.0, 2.0, 3.0],
                "y": [0.0, 1.0, 2.0, 3.0],
                "z": [1.0, 2.0, 1.5, 3.0],
            }),
        )
        canvas = PlotCanvas()
        result = canvas.plot_series(
            self.workspace,
            [PlotSeries(
                collinear.name,
                "x",
                collinear.name,
                "y",
                z_dataset=collinear.name,
                z_column="z",
                plot_type="heatmap",
            )],
        )
        self.assertEqual(result.plotted_count, 0)
        self.assertTrue(result.skipped_messages)
        self.assertEqual(canvas.axes.get_title(), "Plot could not be rendered")
        self.assertTrue(canvas.axes.texts[0].get_text())
        canvas.deleteLater()


if __name__ == "__main__":
    unittest.main()
