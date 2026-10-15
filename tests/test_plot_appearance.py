"""Tests for versioned plot settings and configurable legend rendering."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core import project_io
from core.workspace import Workspace
from models.plot_settings import (
    AxisSettings,
    FigureSettings,
    LegendSettings,
    PLOT_STATE_VERSION,
    PlotSettings,
)
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
        self.assertEqual(settings.figure.size_mode, "figure")
        self.assertEqual(settings.style.preset, "science")
        self.assertIn("axes", settings.to_state())
        self.assertIn("legend", settings.to_state())

    def test_malformed_new_settings_fall_back_and_clamp(self) -> None:
        settings = PlotSettings.from_state({
            "axes": {
                "x": {
                    "scale": "invalid",
                    "label_font_size": -1,
                    "tick_font_size": 1000,
                }
            },
            "legend": {"font_size": -2, "columns": 500, "location": "invalid"},
            "figure": {"width": "bad", "height": 1000},
        })
        self.assertEqual(settings.x_axis.scale, "linear")
        self.assertEqual(settings.x_axis.label_font_size, 0.0)
        self.assertEqual(settings.x_axis.tick_font_size, 72.0)
        self.assertEqual(settings.legend.font_size, 5.0)
        self.assertEqual(settings.legend.columns, 20)
        self.assertEqual(settings.legend.location, "best")
        self.assertEqual(settings.figure.width, 7.0)
        self.assertEqual(settings.figure.height, 15.0)

    def test_current_plot_settings_survive_project_round_trip(self) -> None:
        workspace = Workspace()
        state = {
            "version": PLOT_STATE_VERSION,
            "series": [],
            "locators": [],
            "settings": PlotSettings(
                title="Publication plot",
                x_axis=AxisSettings(label="Time", label_font_size=13.0, tick_font_size=9.5),
                legend=LegendSettings(
                    location="outside right",
                    font_size=13.0,
                    title="Legend",
                    columns=2,
                ),
                figure=FigureSettings(width=6.0, height=4.0, size_mode="plot_area"),
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

    def test_axis_label_and_tick_sizes_render_on_live_canvas(self) -> None:
        canvas = PlotCanvas()
        result = canvas.plot_series(
            self.workspace,
            [
                PlotSeries("signals", "x", "signals", "left"),
                PlotSeries(
                    "signals", "x", "signals", "right", y_axis="right"
                ),
            ],
            x_label="Time",
            y_label="Left signal",
            right_y_label="Right signal",
            x_label_font_size=15.0,
            x_tick_font_size=9.0,
            y_label_font_size=14.0,
            y_tick_font_size=8.0,
            right_y_label_font_size=13.0,
            right_y_tick_font_size=7.0,
        )
        self.assertEqual(result.plotted_count, 2)
        self.assertEqual(canvas.axes.xaxis.label.get_fontsize(), 15.0)
        self.assertEqual(canvas.axes.yaxis.label.get_fontsize(), 14.0)
        self.assertEqual(canvas.axes.get_xticklabels()[0].get_fontsize(), 9.0)
        self.assertEqual(canvas.axes.get_yticklabels()[0].get_fontsize(), 8.0)
        self.assertIsNotNone(canvas.right_axes)
        self.assertEqual(canvas.right_axes.yaxis.label.get_fontsize(), 13.0)
        self.assertEqual(canvas.right_axes.get_yticklabels()[0].get_fontsize(), 7.0)
        canvas.deleteLater()

    def test_copy_to_clipboard_uses_live_canvas_size(self) -> None:
        canvas = PlotCanvas()
        canvas.canvas.resize(640, 360)
        canvas.plot_series(
            self.workspace,
            [PlotSeries("signals", "x", "signals", "left")],
        )
        canvas.set_export_size(12.0, 9.0, "figure")

        self.assertTrue(canvas.copy_to_clipboard())
        copied = QApplication.clipboard().pixmap()
        self.assertFalse(copied.isNull())
        self.assertEqual(copied.size(), canvas.canvas.size())
        canvas.deleteLater()

    def test_export_controls_do_not_resize_interactive_canvas_when_style_changes(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_single_series_plot(self.dataset, "x", "left", "Signal")
        initial_size = tuple(tab._plot_canvas.figure.get_size_inches())

        tab._width_spin.setValue(14.0)
        tab._height_spin.setValue(9.0)
        tab._set_combo_data(tab._style_preset_combo, "science")
        tab._render_plot()

        self.assertEqual(tuple(tab._plot_canvas.figure.get_size_inches()), initial_size)
        self.assertEqual(tab._preview_status_label.text(), "Preview current")
        self.assertEqual(tab._plot_canvas._export_width, 14.0)
        self.assertEqual(tab._plot_canvas._export_height, 9.0)
        tab.deleteLater()

    def test_full_image_export_uses_requested_size_and_restores_canvas(self) -> None:
        canvas = PlotCanvas()
        canvas.plot_series(
            self.workspace,
            [PlotSeries("signals", "x", "signals", "left")],
        )
        original_size = tuple(canvas.figure.get_size_inches())
        canvas.set_export_size(4.0, 3.0, "figure")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "full-image.png"
            canvas.export_figure(str(path))
            data = path.read_bytes()
        pixel_width, pixel_height = struct.unpack(">II", data[16:24])

        self.assertEqual(pixel_width, round(4.0 * canvas.figure.dpi))
        self.assertEqual(pixel_height, round(3.0 * canvas.figure.dpi))
        self.assertEqual(tuple(canvas.figure.get_size_inches()), original_size)
        canvas.deleteLater()

    def test_plot_area_export_calculates_larger_complete_image(self) -> None:
        canvas = PlotCanvas()
        canvas.plot_series(
            self.workspace,
            [PlotSeries("signals", "x", "signals", "left")],
            x_label="Time",
            y_label="Amplitude",
        )
        canvas.set_export_size(5.0, 3.0, "plot_area")
        figure_width, figure_height = canvas._export_figure_dimensions()
        axes_position = canvas.axes.get_position()

        self.assertAlmostEqual(figure_width * axes_position.width, 5.0, places=8)
        self.assertAlmostEqual(figure_height * axes_position.height, 3.0, places=8)
        self.assertGreater(figure_width, 5.0)
        self.assertGreater(figure_height, 3.0)
        measured_axes_sizes: list[tuple[float, float]] = []

        def record_export(*_args: object, **_kwargs: object) -> None:
            saved_width, saved_height = canvas.figure.get_size_inches()
            saved_position = canvas.axes.get_position()
            measured_axes_sizes.append(
                (saved_width * saved_position.width, saved_height * saved_position.height)
            )

        with patch.object(canvas.figure, "savefig", side_effect=record_export):
            canvas.export_figure("unused.png")
        self.assertAlmostEqual(measured_axes_sizes[0][0], 5.0, places=6)
        self.assertAlmostEqual(measured_axes_sizes[0][1], 3.0, places=6)
        canvas.deleteLater()

    def test_canvas_hit_testing_finds_title_axes_and_legend_entry(self) -> None:
        canvas = PlotCanvas()
        canvas.plot_series(
            self.workspace,
            [PlotSeries("signals", "x", "signals", "left", custom_label="Signal")],
            title="Measurements",
            x_label="Time",
            y_label="Amplitude",
        )
        canvas.canvas.draw()
        renderer = canvas.canvas.get_renderer()

        def center(artist: object) -> tuple[float, float]:
            bounds = artist.get_window_extent(renderer)
            return (bounds.x0 + bounds.x1) / 2.0, (bounds.y0 + bounds.y1) / 2.0

        title_center = center(canvas.axes.title)
        self.assertEqual(canvas.editable_element_at(*title_center), ("title", None))
        self.assertEqual(
            canvas.editable_element_at(*center(canvas.axes.xaxis.label)),
            ("x_axis", None),
        )
        self.assertEqual(
            canvas.editable_element_at(*center(canvas.axes.yaxis.label)),
            ("left_y_axis", None),
        )
        legend_text = canvas.axes.get_legend().get_texts()[0]
        self.assertEqual(
            canvas.editable_element_at(*center(legend_text)),
            ("legend_entry", "Signal"),
        )
        emitted: list[tuple[str, object]] = []
        canvas.element_double_clicked.connect(lambda kind, value: emitted.append((kind, value)))
        canvas._handle_canvas_button_press(
            SimpleNamespace(dblclick=True, button=1, x=title_center[0], y=title_center[1])
        )
        self.assertEqual(emitted, [("title", None)])
        canvas.deleteLater()

    def test_canvas_hit_testing_maps_line_and_scatter_artists_to_series(self) -> None:
        for plot_type in ("line", "scatter"):
            with self.subTest(plot_type=plot_type):
                canvas = PlotCanvas()
                canvas.plot_series(
                    self.workspace,
                    [PlotSeries(
                        "signals", "x", "signals", "left", plot_type=plot_type,
                    )],
                    legend_settings=LegendSettings(enabled=False),
                )
                canvas.canvas.draw()
                display_point = canvas.axes.transData.transform((2.0, 3.0))
                self.assertEqual(
                    canvas.editable_element_at(*display_point),
                    ("series", 0),
                )
                canvas.deleteLater()

    def test_direct_title_and_axis_edits_sync_inspector_and_canvas(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_single_series_plot(self.dataset, "x", "left", "Signal")

        class FakeTitleDialog:
            def __init__(self, *_args: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def text_value() -> str:
                return "Edited on canvas"

        class FakeAxisDialog:
            def __init__(self, *_args: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def axis_settings() -> AxisSettings:
                return AxisSettings(
                    label="Frequency",
                    scale="log",
                    minimum="1",
                    maximum="100",
                    label_font_size=16.0,
                    tick_font_size=11.0,
                )

            @staticmethod
            def grid_enabled() -> bool:
                return False

        with patch("ui.plot_tab.PlotTextEditDialog", FakeTitleDialog):
            tab._edit_rendered_plot_element("title")
        with patch("ui.plot_tab.PlotAxisEditDialog", FakeAxisDialog):
            tab._edit_rendered_plot_element("x_axis")

        self.assertEqual(tab._title_edit.text(), "Edited on canvas")
        self.assertEqual(tab._plot_canvas.axes.get_title(), "Edited on canvas")
        self.assertEqual(tab._x_label_edit.text(), "Frequency")
        self.assertEqual(tab._x_scale_combo.currentText(), "log")
        self.assertEqual(tab._x_min_edit.text(), "1")
        self.assertEqual(tab._x_max_edit.text(), "100")
        self.assertEqual(tab._x_label_size_spin.value(), 16.0)
        self.assertEqual(tab._x_tick_size_spin.value(), 11.0)
        self.assertEqual(tab._plot_canvas.axes.get_xlabel(), "Frequency")
        self.assertEqual(tab._plot_canvas.axes.xaxis.label.get_fontsize(), 16.0)
        self.assertEqual(tab._plot_canvas.axes.get_xticklabels()[0].get_fontsize(), 11.0)
        self.assertEqual(tab._plot_canvas.axes.get_xscale(), "log")
        self.assertFalse(tab._grid_checkbox.isChecked())
        tab.deleteLater()

    def test_direct_legend_and_entry_edits_sync_committed_state(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_single_series_plot(self.dataset, "x", "left", "Signal")
        original_label = tab._plot_series[0].label

        class FakeLegendDialog:
            def __init__(self, *_args: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def legend_settings() -> LegendSettings:
                return LegendSettings(
                    location="upper left",
                    font_size=13.0,
                    title="Channels",
                    frame_enabled=False,
                )

        class FakeEntryDialog:
            def __init__(self, *_args: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def entry_label() -> str:
                return "Renamed signal"

            @staticmethod
            def entry_shown() -> bool:
                return True

        with patch("ui.plot_tab.PlotLegendEditDialog", FakeLegendDialog):
            tab._edit_rendered_plot_element("legend")
        with patch("ui.plot_tab.PlotLegendEntryEditDialog", FakeEntryDialog):
            tab._edit_rendered_plot_element("legend_entry", original_label)

        self.assertEqual(tab._legend_title_edit.text(), "Channels")
        self.assertEqual(tab._legend_font_size_spin.value(), 13.0)
        self.assertFalse(tab._legend_frame_checkbox.isChecked())
        self.assertEqual(tab._plot_series[0].custom_label, "Renamed signal")
        self.assertIn("Renamed signal", tab._series_list.item(0).text())
        legend = tab._plot_canvas.axes.get_legend()
        self.assertEqual(legend.get_title().get_text(), "Channels")
        self.assertEqual(legend.get_texts()[0].get_text(), "Renamed signal")
        tab.deleteLater()

    def test_direct_series_edit_changes_graph_type_and_representation(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_single_series_plot(self.dataset, "x", "left", "Signal")

        class FakeSeriesDialog:
            def __init__(self, *_args: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def series_updates() -> dict[str, object]:
                return {
                    "plot_type": "scatter",
                    "custom_label": "Direct scatter",
                    "show_in_legend": True,
                    "line_style": "--",
                    "line_width": 2.6,
                    "marker": "*",
                    "marker_size": 9.0,
                    "color": "#ff00aa",
                    "fill_alpha": 0.4,
                    "bar_width": 0.7,
                }

        with patch("ui.plot_tab.PlotSeriesAppearanceDialog", FakeSeriesDialog):
            tab._edit_rendered_plot_element("series", 0)

        series = tab._plot_series[0]
        self.assertEqual(series.plot_type, "scatter")
        self.assertEqual(series.marker, "*")
        self.assertEqual(series.color, "#ff00aa")
        self.assertEqual(series.custom_label, "Direct scatter")
        self.assertEqual(tab._plot_type_combo.currentData(), "scatter")
        self.assertEqual(tab._marker_combo.currentData(), "*")
        self.assertEqual(tab._color_combo.currentData(), "#ff00aa")
        self.assertEqual(len(tab._plot_canvas.axes.collections), 1)
        self.assertEqual(
            tab._plot_canvas.axes.get_legend().get_texts()[0].get_text(),
            "Direct scatter",
        )
        tab.deleteLater()

    def test_direct_series_edit_does_not_overwrite_unapplied_inspector_edits(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_single_series_plot(self.dataset, "x", "left", "Signal")
        original = tab._plot_series[0]
        tab._series_label_edit.setText("Still staged")

        with (
            patch.object(QMessageBox, "information") as information,
            patch("ui.plot_tab.PlotSeriesAppearanceDialog") as dialog,
        ):
            tab._edit_rendered_plot_element("series", 0)

        self.assertEqual(tab._plot_series[0], original)
        self.assertTrue(tab.has_unapplied_series_edits())
        information.assert_called_once()
        dialog.assert_not_called()
        tab.deleteLater()

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

        self.assertFalse(tab._auto_preview_checkbox.isChecked())
        tab._auto_preview_checkbox.setChecked(True)
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
        tab._auto_preview_checkbox.setChecked(True)
        with patch.object(QMessageBox, "warning") as warning:
            tab._x_min_edit.setText("not-a-number")
            QTest.qWait(250)
            self.app.processEvents()
        warning.assert_not_called()
        self.assertTrue(tab._preview_dirty)
        self.assertEqual(tab._preview_status_label.text(), "Fix invalid plot settings")
        tab.deleteLater()

    def test_selected_series_changes_are_staged_until_explicit_update(self) -> None:
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
                tab._auto_preview_checkbox.setChecked(True)
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

                self.assertEqual(tab._plot_series[0].plot_type, "line")
                self.assertEqual(tab._plot_series[0].z_column, "")
                self.assertTrue(tab._series_editor_dirty)
                self.assertEqual(
                    tab._series_editor_status_label.text(),
                    "Series 1 has unapplied edits",
                )

                tab._commit_series_editor()
                self.assertEqual(tab._plot_series[0].plot_type, subtype)
                self.assertEqual(tab._plot_series[0].z_column, "z")
                self.assertGreater(len(tab._plot_canvas.axes.collections), 0)
                self.assertEqual(tab._preview_status_label.text(), "Preview current")
                tab.deleteLater()

    def test_new_series_mode_adds_without_changing_existing_series(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_single_series_plot(self.dataset, "x", "left", "Signals")
        original = tab._plot_series[0]

        tab._start_new_series()
        self.assertIsNone(tab._selected_series_row())
        self.assertEqual(tab._commit_series_button.text(), "Add Series")
        tab._y_column_combo.setCurrentText("right")
        tab._series_label_edit.setText("Right signal")
        tab._commit_series_editor()

        self.assertEqual(len(tab._plot_series), 2)
        self.assertEqual(tab._plot_series[0], original)
        self.assertEqual(tab._plot_series[1].y_column, "right")
        self.assertEqual(tab._plot_series[1].custom_label, "Right signal")
        self.assertEqual(tab._commit_series_button.text(), "Update Series")
        tab.deleteLater()

    def test_selection_change_cannot_silently_discard_staged_edits(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_plot_series(
            [
                PlotSeries("signals", "x", "signals", "left"),
                PlotSeries("signals", "x", "signals", "right"),
            ],
            title="Signals",
        )
        tab._series_label_edit.setText("Staged label")

        with patch.object(QMessageBox, "information") as information:
            tab._series_list.setCurrentRow(1)

        self.assertEqual(tab._selected_series_row(), 0)
        self.assertTrue(tab.has_unapplied_series_edits())
        self.assertEqual(tab._plot_series[0].custom_label, "")
        information.assert_called_once()

        tab._discard_series_edits()
        tab._series_list.setCurrentRow(1)
        self.assertEqual(tab._selected_series_row(), 1)
        tab.deleteLater()

    def test_series_and_locator_context_menus_expose_common_actions(self) -> None:
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_single_series_plot(self.dataset, "x", "left", "Signal")
        series_menu, _series_actions = tab._build_series_context_menu()
        locator_menu, _locator_actions = tab._build_locator_context_menu()
        series_texts = [action.text() for action in series_menu.actions() if action.text()]
        locator_texts = [action.text() for action in locator_menu.actions() if action.text()]

        self.assertTrue({
            "New Series",
            "Update Series",
            "Revert Edits",
            "Duplicate Series",
            "Remove Series",
            "Clear All Series",
        }.issubset(set(series_texts)))
        self.assertEqual(
            locator_texts,
            ["Add Locator", "Remove Locator", "Clear All Locators"],
        )

        original = tab._plot_series[0]
        self.assertFalse(tab.has_unapplied_series_edits())
        with patch.object(QMessageBox, "information") as information:
            tab._duplicate_selected_series()
        information.assert_not_called()
        self.assertEqual(tab._plot_series, [original, original])
        self.assertEqual(tab._selected_series_row(), 1)
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

    def test_2d_map_palette_and_mouse_reader_include_z_value(self) -> None:
        mapped = self.workspace.add_dataset(
            "mapped",
            pd.DataFrame({
                "x": [0.0, 0.0, 1.0, 1.0],
                "y": [0.0, 1.0, 0.0, 1.0],
                "z": [0.0, 2.0, 1.0, 3.0],
            }),
        )
        canvas = PlotCanvas()
        result = canvas.plot_series(
            self.workspace,
            [PlotSeries(
                mapped.name,
                "x",
                mapped.name,
                "y",
                z_dataset=mapped.name,
                z_column="z",
                plot_type="heatmap",
                color_map="coolwarm",
            )],
        )

        self.assertEqual(result.plotted_count, 1)
        self.assertEqual(canvas.axes.collections[0].get_cmap().name, "coolwarm")
        coordinate_text = canvas.axes.format_coord(0.5, 0.5)
        self.assertIn("x=0.5", coordinate_text)
        self.assertIn("y=0.5", coordinate_text)
        self.assertIn("z=1.5", coordinate_text)
        canvas.canvas.draw()
        label_artist = canvas._colorbar_labels[0][1]
        label_bounds = label_artist.get_window_extent(canvas.canvas.get_renderer())
        self.assertEqual(
            canvas.editable_element_at(
                (label_bounds.x0 + label_bounds.x1) / 2.0,
                (label_bounds.y0 + label_bounds.y1) / 2.0,
            ),
            ("colorbar_label", 0),
        )
        canvas.deleteLater()

    def test_double_click_colour_bar_label_updates_surface_series(self) -> None:
        mapped = self.workspace.add_dataset(
            "editable_map",
            pd.DataFrame({
                "x": [0.0, 0.0, 1.0, 1.0],
                "y": [0.0, 1.0, 0.0, 1.0],
                "z": [0.0, 2.0, 1.0, 3.0],
            }),
        )
        tab = PlotTab(self.workspace, external_options=False)
        tab.queue_plot_series(
            [PlotSeries(
                mapped.name,
                "x",
                mapped.name,
                "y",
                z_dataset=mapped.name,
                z_column="z",
                plot_type="heatmap",
            )],
            title="Map",
            selected_dataset_name=mapped.name,
        )

        class FakeColourBarDialog:
            def __init__(self, *_args: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def text_value() -> str:
                return "Intensity (counts)"

        with patch("ui.plot_tab.PlotTextEditDialog", FakeColourBarDialog):
            tab._edit_rendered_plot_element("colorbar_label", 0)

        self.assertEqual(tab._plot_series[0].colorbar_label, "Intensity (counts)")
        self.assertEqual(tab._colorbar_label_edit.text(), "Intensity (counts)")
        self.assertEqual(
            tab._plot_canvas._colorbar_labels[0][1].get_text(),
            "Intensity (counts)",
        )
        tab.deleteLater()

    def test_spectral_map_samples_nearest_or_interpolated_intensity(self) -> None:
        spectral = self.workspace.add_dataset(
            "raman_map",
            pd.DataFrame({
                "X": np.repeat([0.0, 0.0, 1.0, 1.0], 2),
                "Y": np.repeat([0.0, 1.0, 0.0, 1.0], 2),
                "Raman Shift": np.tile([100.0, 200.0], 4),
                "Intensity": [0.0, 100.0, 1.0, 101.0, 10.0, 110.0, 11.0, 111.0],
            }),
        )
        canvas = PlotCanvas()
        common = dict(
            x_dataset=spectral.name,
            x_column="X",
            y_dataset=spectral.name,
            y_column="Y",
            z_dataset=spectral.name,
            z_column="Intensity",
            spectral_column="Raman Shift",
            spectral_center=160.0,
            plot_type="spectra_heatmap",
            color_map="plasma",
        )

        nearest = canvas._surface_values(
            self.workspace,
            PlotSeries(**common, spectral_sampling="nearest"),
            x_scale="linear",
            y_scale="linear",
        )
        interpolated = canvas._surface_values(
            self.workspace,
            PlotSeries(**common, spectral_sampling="linear"),
            x_scale="linear",
            y_scale="linear",
        )

        np.testing.assert_allclose(np.sort(nearest.z_values), [100.0, 101.0, 110.0, 111.0])
        np.testing.assert_allclose(np.sort(interpolated.z_values), [60.0, 61.0, 70.0, 71.0])
        for subtype in ("spectra_heatmap", "spectra_contour", "spectra_contourf"):
            with self.subTest(subtype=subtype):
                result = canvas.plot_series(
                    self.workspace,
                    [PlotSeries(**{**common, "plot_type": subtype}, spectral_sampling="linear")],
                )
                self.assertEqual(result.plotted_count, 1)
                self.assertFalse(result.skipped_messages)
                self.assertIn("Intensity=", canvas.axes.format_coord(0.5, 0.5))
                self.assertEqual(canvas.axes.collections[0].get_cmap().name, "plasma")
                canvas._handle_canvas_motion(
                    SimpleNamespace(inaxes=canvas.axes, xdata=0.5, ydata=0.5)
                )
                self.assertFalse(canvas.coordinate_readout.isHidden())
                self.assertIn("x=0.5", canvas.coordinate_readout.text())
                self.assertIn("y=0.5", canvas.coordinate_readout.text())
                self.assertIn("Intensity=", canvas.coordinate_readout.text())
        canvas.deleteLater()

    def test_spectra_plot_family_auto_maps_columns_and_persists_sampling(self) -> None:
        spectral = self.workspace.add_dataset(
            "spectral_map",
            pd.DataFrame({
                "X": np.repeat([0.0, 0.0, 1.0, 1.0], 2),
                "Y": np.repeat([0.0, 1.0, 0.0, 1.0], 2),
                "Raman Shift": np.tile([100.0, 200.0], 4),
                "Intensity": np.arange(8, dtype=float),
            }),
        )
        tab = PlotTab(self.workspace, external_options=False)
        tab._set_combo_data(tab._plot_family_combo, "spectra")
        tab._spectral_dataset_combo.setCurrentText(spectral.name)

        self.assertEqual(tab._x_column_combo.currentText(), "X")
        self.assertEqual(tab._y_column_combo.currentText(), "Y")
        self.assertEqual(tab._spectral_column_combo.currentText(), "Raman Shift")
        self.assertEqual(tab._z_column_combo.currentText(), "Intensity")
        self.assertFalse(tab._surface_options_panel.isAncestorOf(tab._color_map_combo))

        tab._spectral_center_spin.setValue(150.0)
        tab._set_combo_data(tab._spectral_sampling_combo, "linear")
        tab._set_combo_data(tab._color_map_combo, "magma")
        tab._colorbar_label_edit.setText("Raman intensity (counts)")
        tab._commit_series_editor()

        self.assertEqual(len(tab._plot_series), 1)
        series = tab._plot_series[0]
        self.assertEqual(series.plot_type, "spectra_heatmap")
        self.assertEqual(series.spectral_column, "Raman Shift")
        self.assertEqual(series.spectral_center, 150.0)
        self.assertEqual(series.spectral_sampling, "linear")
        self.assertEqual(series.color_map, "magma")
        self.assertEqual(series.colorbar_label, "Raman intensity (counts)")
        state = tab.current_plot_state()
        self.assertEqual(state["series"][0]["spectral_sampling"], "linear")
        self.assertEqual(state["series"][0]["color_map"], "magma")
        self.assertEqual(state["series"][0]["colorbar_label"], "Raman intensity (counts)")
        self.assertGreater(len(tab._plot_canvas.axes.collections), 0)

        restored = PlotTab(self.workspace, external_options=False)
        restored.load_plot_state(state)
        restored_series = restored._plot_series[0]
        self.assertEqual(restored_series.spectral_column, "Raman Shift")
        self.assertEqual(restored_series.spectral_center, 150.0)
        self.assertEqual(restored_series.spectral_sampling, "linear")
        self.assertEqual(restored_series.color_map, "magma")
        self.assertEqual(restored_series.colorbar_label, "Raman intensity (counts)")
        self.assertEqual(
            restored._spectral_column_combo.currentText(),
            "Raman Shift",
        )
        restored.deleteLater()
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
