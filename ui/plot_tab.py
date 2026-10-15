"""Plot tab widget extracted from main_window for modularity."""

from __future__ import annotations

from dataclasses import asdict, fields, replace

import numpy as np
import pandas as pd
from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.workspace import Dataset, Workspace
from models.plot_settings import (
    PLOT_STATE_VERSION,
    AxisSettings,
    FigureSettings,
    LegendSettings,
    PlotSettings,
    StyleSettings,
)
from models.plot_types import PLOT_TYPES, plot_type_label
from ui.plot_canvas import SCIENCEPLOTS_AVAILABLE, LocatedPoint, PlotCanvas, PlotLocator, PlotSeries
from ui.plot_element_dialogs import (
    PlotAxisEditDialog,
    PlotLegendEditDialog,
    PlotLegendEntryEditDialog,
    PlotSeriesAppearanceDialog,
    PlotTextEditDialog,
)

_LINE_LABELS: dict[str, str] = {
    "-": "Solid", "--": "Dashed", ":": "Dotted", "-.": "Dash-dot", "": "None",
}
_MARKER_LABELS: dict[str, str] = {
    "": "None", "o": "Circle", "s": "Square", "^": "Triangle",
    "D": "Diamond", "x": "Cross", ".": "Dot",
}
_COLOR_LABELS: dict[str, str] = {
    "": "Auto", "tab:blue": "Blue", "tab:orange": "Orange",
    "tab:green": "Green", "tab:red": "Red", "tab:purple": "Purple",
    "black": "Black",
}
_PLOT_STYLE_PRESETS: list[tuple[str, str]] = [
    ("Matplotlib default", ""),
    ("Science", "science"),
    ("IEEE", "science,ieee"),
    ("Nature", "science,nature"),
    ("Notebook", "science,notebook"),
]
_PLOT_STYLE_CYCLES: list[tuple[str, str]] = [
    ("Default", ""),
    ("Bright", "bright"),
    ("High visibility", "high-vis"),
]
_SCIENCEPLOTS_STYLE_NAMES = {
    "science", "ieee", "nature", "notebook", "bright", "high-vis", "no-latex",
}
_SPECTRAL_PLOT_TYPES = {"spectra_heatmap", "spectra_contour", "spectra_contourf"}
_SURFACE_PLOT_TYPES = {"heatmap", "contour", "contourf"} | _SPECTRAL_PLOT_TYPES
_PIE_PLOT_TYPES = {"pie", "donut"}
_VORONOI_PLOT_TYPES = {"voronoi"}
_COMPOSITION_PLOT_TYPES = _PIE_PLOT_TYPES | _VORONOI_PLOT_TYPES
_PLOT_FAMILIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("xy", "XY / Categorical", ("line", "scatter", "line_marker", "errorbar", "bar", "barh", "area")),
    ("distribution", "Distribution", ("histogram", "box", "violin")),
    ("composition", "Composition", ("pie", "donut", "voronoi")),
    ("surface", "2D Maps", ("heatmap", "contour", "contourf")),
    ("spectra", "Spectra Plot", ("spectra_heatmap", "spectra_contour", "spectra_contourf")),
]
_PLOT_FAMILY_TYPES = {key: plot_types for key, _label, plot_types in _PLOT_FAMILIES}
_PLOT_TYPE_TO_FAMILY = {
    plot_type: family_key
    for family_key, _label, plot_types in _PLOT_FAMILIES
    for plot_type in plot_types
}
_VORONOI_SHAPES: list[tuple[str, str]] = [
    ("Circular", "circle"),
    ("Rectangular", "rectangle"),
    ("Polygonal", "polygon"),
]
_VORONOI_SHAPE_LABELS = {data: label for label, data in _VORONOI_SHAPES}
_INTERPOLATION_LABELS: dict[str, str] = {
    "linear": "Linear",
    "cubic_spline": "Cubic spline",
    "piecewise_cubic": "Piecewise cubic",
}
_SPECTRAL_SAMPLING_LABELS: dict[str, str] = {
    "nearest": "Closest measured shift",
    "linear": "Linear spectral interpolation",
}
_COLOR_MAP_LABELS: dict[str, str] = {
    "viridis": "Viridis",
    "plasma": "Plasma",
    "inferno": "Inferno",
    "magma": "Magma",
    "cividis": "Cividis",
    "turbo": "Turbo",
    "gray": "Grayscale",
    "hot": "Hot",
    "coolwarm": "Cool-Warm",
    "RdBu_r": "Red-Blue",
    "Spectral_r": "Spectral",
    "terrain": "Terrain",
    "ocean": "Ocean",
    "jet": "Jet (legacy)",
}
_PLOT_SERIES_FIELDS = {field.name for field in fields(PlotSeries)}
_PLOT_LOCATOR_FIELDS = {field.name for field in fields(PlotLocator)}


class PlotTab(QWidget):
    """Self-contained plot tab with series management, locators, and rendering."""

    status_message = Signal(str)
    plot_rendered = Signal()
    save_plot_requested = Signal()
    load_plot_requested = Signal()
    remove_plot_requested = Signal()
    new_plot_requested = Signal()
    plot_draft_replaced = Signal()
    options_visibility_changed = Signal(bool)

    def __init__(
        self,
        workspace: Workspace,
        parent: QWidget | None = None,
        external_options: bool = False,
    ) -> None:
        """Create a plot editor bound to a workspace."""
        super().__init__(parent)
        self._workspace = workspace
        self._external_options = external_options
        self._plot_series: list[PlotSeries] = []
        self._plot_locators: list[PlotLocator] = []
        self._auto_axis_labels: dict[str, str] = {"x": "", "y": "", "right_y": ""}
        self._loading_plot_settings = False
        self._loading_series_controls = False
        self._series_editor_dirty = False
        self._editing_series_row: int | None = None
        self._preview_dirty = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._render_scheduled_preview)
        self._plot_canvas = PlotCanvas()
        self._plot_canvas.element_double_clicked.connect(self._edit_rendered_plot_element)
        self._build_ui()

    # -- public API for MainWindow -----------------------------------------

    def set_workspace(self, workspace: Workspace) -> None:
        """Attach a new workspace and clear plot state tied to the old one."""
        self._workspace = workspace
        self.clear_plot_state()
        self.refresh_controls()

    def clear_plot_state(self) -> None:
        """Clear queued series, locators, and the current plot canvas."""
        self._series_editor_dirty = False
        self._editing_series_row = None
        self._plot_series.clear()
        self._plot_locators.clear()
        self._series_list.clear()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._plot_canvas.clear_plot()
        self._update_series_editor_state()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self.plot_rendered.emit()

    def reset_plot_draft(self) -> None:
        """Start a completely fresh unsaved plot using application defaults."""
        self._series_editor_dirty = False
        self._editing_series_row = None
        self._plot_series.clear()
        self._plot_locators.clear()
        self._series_list.clear()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._apply_plot_settings({})
        self._series_label_edit.clear()
        self._series_legend_checkbox.setChecked(True)
        self._set_combo_data(self._plot_family_combo, "xy")
        self._refresh_plot_type_combo("line")
        self._set_combo_data(self._y_axis_combo, "left")
        self._set_combo_data(self._line_style_combo, "-")
        self._set_combo_data(self._marker_combo, "")
        self._set_combo_data(self._color_combo, "")
        self._line_width_spin.setValue(1.8)
        self._marker_size_spin.setValue(6.0)
        self._plot_canvas.clear_plot()
        self._update_series_editor_state()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self.plot_rendered.emit()

    def refresh_controls(self, selected_dataset: str | None = None) -> None:
        """Repopulate dataset/column combos from the workspace."""
        names = self._workspace.dataset_names()
        self._set_combo_items(self._x_dataset_combo, names, selected_dataset)
        self._set_combo_items(self._y_dataset_combo, names, selected_dataset)
        self._set_combo_items(self._z_dataset_combo, names, selected_dataset)
        self._set_combo_items(self._spectral_dataset_combo, names, selected_dataset)
        self._update_column_combo(self._x_dataset_combo, self._x_column_combo, ("x",))
        self._update_error_column_combo(self._x_dataset_combo, self._x_err_column_combo, ("x_error", "error"))
        self._update_column_combo(self._y_dataset_combo, self._y_column_combo, ("y",))
        self._update_error_column_combo(self._y_dataset_combo, self._y_err_column_combo, ("y_error", "error"))
        self._update_column_combo(self._z_dataset_combo, self._z_column_combo, ("z",))
        self._update_spectral_column_combos()
        self._update_distribution_columns_list()
        self._set_controls_enabled(bool(names))
        self._prefill_axis_labels_from_plot_context()

    def has_plot_series(self) -> bool:
        """Return whether the plot tab has a restorable plot definition."""
        return bool(self._plot_series)

    def has_unapplied_series_edits(self) -> bool:
        """Return whether selected-series controls differ from the queued series."""
        return self._series_editor_dirty

    def copy_plot_to_clipboard(self) -> bool:
        """Copy the current live plot visualization to the system clipboard."""
        if not self._plot_series:
            QMessageBox.information(
                self,
                "Copy Plot",
                "Create or load a plot before copying it.",
            )
            return False
        copied = self._plot_canvas.copy_to_clipboard()
        if copied:
            self.status_message.emit("Copied current plot visualization to the clipboard")
        else:
            QMessageBox.warning(self, "Copy Plot", "The plot image could not be copied.")
        return copied

    def set_active_plot_name(self, name: str | None) -> None:
        """Update the plot header with the active saved plot name."""
        self._active_plot_label.setText(name or "Unsaved plot")

    def rename_column_references(self, dataset_name: str, rename_map: dict[str, str]) -> None:
        """Update queued series when a dataset column is renamed."""
        if not rename_map:
            return

        changed = False
        updated_series: list[PlotSeries] = []
        for series in self._plot_series:
            updates: dict[str, object] = {}
            if series.x_dataset == dataset_name:
                updates["x_column"] = rename_map.get(series.x_column, series.x_column)
                updates["x_err_column"] = rename_map.get(series.x_err_column, series.x_err_column)
            if series.y_dataset == dataset_name:
                updates["y_column"] = rename_map.get(series.y_column, series.y_column)
                updates["y_err_column"] = rename_map.get(series.y_err_column, series.y_err_column)
                updates["lower_column"] = rename_map.get(series.lower_column, series.lower_column)
                updates["upper_column"] = rename_map.get(series.upper_column, series.upper_column)
                updates["distribution_columns"] = tuple(
                    rename_map.get(column, column)
                    for column in series.distribution_columns
                )
            if series.z_dataset == dataset_name:
                updates["z_column"] = rename_map.get(series.z_column, series.z_column)
                updates["spectral_column"] = rename_map.get(
                    series.spectral_column,
                    series.spectral_column,
                )

            clean_updates = {
                key: value
                for key, value in updates.items()
                if getattr(series, key) != value
            }
            if clean_updates:
                updated_series.append(replace(series, **clean_updates))
                changed = True
            else:
                updated_series.append(series)

        if not changed:
            return

        selected_row = self._selected_series_row()
        self._plot_series = updated_series
        self._refresh_series_list()
        self._refresh_locator_series_combo()
        self.refresh_controls(dataset_name)
        if selected_row is not None and 0 <= selected_row < len(self._plot_series):
            self._series_list.setCurrentRow(selected_row)
            self._load_series_controls(self._plot_series[selected_row])
        if self._plot_series:
            self._render_plot(silent_if_empty=True)

    def set_plot_actions_enabled(self, can_save: bool, can_load: bool, can_remove: bool) -> None:
        """Set enabled state for plot-level header actions."""
        self._save_plot_button.setEnabled(can_save)
        self._copy_plot_button.setEnabled(can_save)
        self._load_plot_button.setEnabled(can_load)
        self._remove_plot_button.setEnabled(can_remove)

    def suggested_plot_name(self) -> str:
        """Return a practical default name for saving the current plot."""
        title = self._title_edit.text().strip()
        if title:
            return title
        if self._plot_series:
            return self._plot_series[0].label
        return "Plot"

    def current_plot_state(self) -> dict[str, object]:
        """Return the current plot definition as JSON-friendly state."""
        return {
            "version": PLOT_STATE_VERSION,
            "series": [asdict(series) for series in self._plot_series],
            "locators": [asdict(locator) for locator in self._plot_locators],
            "settings": self._settings_from_controls().to_state(),
        }

    def options_widget(self) -> QWidget:
        """Return the plot controls widget for placement in an external inspector."""
        return self._plot_options_scroll

    def load_plot_state(self, state: dict[str, object]) -> None:
        """Load a saved plot definition into the tab and render it."""
        series_list = state.get("series", [])
        locator_list = state.get("locators", [])
        if not isinstance(series_list, list):
            raise ValueError("Saved plot series data is invalid.")
        if not isinstance(locator_list, list):
            raise ValueError("Saved plot locator data is invalid.")

        self._series_editor_dirty = False
        self._editing_series_row = None
        self._plot_series = [
            self._plot_series_from_state(item)
            for item in series_list
            if isinstance(item, dict)
        ]
        self._plot_locators = [
            locator
            for locator in (
                self._plot_locator_from_state(item)
                for item in locator_list
                if isinstance(item, dict)
            )
            if 0 <= locator.series_index < len(self._plot_series)
        ]
        self._apply_plot_settings(state.get("settings", {}))
        self._refresh_series_list()
        self._refresh_locator_series_combo()
        self.refresh_controls()
        self._select_first_series_for_editing()
        self._prefill_axis_labels_from_plot_context()
        self._render_plot(silent_if_empty=True)

    def queue_fit_plot(
        self,
        source_dataset: Dataset,
        fit_dataset: Dataset,
        x_column: str,
        y_column: str,
        model_name: str,
        residual_dataset: Dataset | None = None,
        show_residuals: bool = False,
        x_err_column: str = "",
        y_err_column: str = "",
    ) -> None:
        """Replace the current series queue with a data-vs-fit overlay."""
        fit_lower = "fit_lower" if "fit_lower" in fit_dataset.frame.columns else ""
        fit_upper = "fit_upper" if "fit_upper" in fit_dataset.frame.columns else ""
        self._plot_series = [
            PlotSeries(
                x_dataset=source_dataset.name, x_column=x_column,
                y_dataset=source_dataset.name, y_column=y_column,
                x_err_column=x_err_column,
                y_err_column=y_err_column,
                plot_type="errorbar" if x_err_column or y_err_column else "scatter",
                color="tab:blue", line_style="", marker="o",
                custom_label=f"{source_dataset.name}: {y_column}",
            ),
            PlotSeries(
                x_dataset=fit_dataset.name, x_column="fit_x",
                y_dataset=fit_dataset.name, y_column="fit_y",
                plot_type="line",
                color="tab:red", line_style="-", marker="",
                custom_label=f"{model_name} fit",
                lower_column=fit_lower,
                upper_column=fit_upper,
            ),
        ]
        if residual_dataset is not None and show_residuals:
            self._plot_series.append(
                PlotSeries(
                    x_dataset=residual_dataset.name,
                    x_column="x",
                    y_dataset=residual_dataset.name,
                    y_column="residual",
                    plot_type="scatter",
                    color="tab:green",
                    line_style="",
                    marker=".",
                    y_axis="right",
                    custom_label="Residuals",
                )
            )
        self._plot_locators.clear()
        self._refresh_series_list()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._title_edit.setText(f"{model_name} fit")
        self._set_axis_label_text("x", self._column_axis_label(source_dataset.name, x_column))
        self._set_axis_label_text("y", self._column_axis_label(source_dataset.name, y_column))
        self._right_y_label_edit.setText("Residual" if residual_dataset is not None and show_residuals else "")
        self._auto_axis_labels["right_y"] = self._right_y_label_edit.text().strip()
        self.refresh_controls(fit_dataset.name)
        self._select_first_series_for_editing()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)
        self.plot_draft_replaced.emit()

    def queue_analysis_plot(
        self,
        dataset: Dataset,
        x_column: str,
        source_column: str,
        result_column: str,
        title: str,
    ) -> None:
        """Plot a source column and an analysis result column against the same X data."""
        self._plot_series = [
            PlotSeries(
                x_dataset=dataset.name,
                x_column=x_column,
                y_dataset=dataset.name,
                y_column=source_column,
                plot_type="line",
                color="tab:blue",
                line_style="-",
                marker="",
                custom_label=source_column,
            ),
            PlotSeries(
                x_dataset=dataset.name,
                x_column=x_column,
                y_dataset=dataset.name,
                y_column=result_column,
                plot_type="line",
                color="tab:red",
                line_style="-",
                marker="",
                y_axis="right",
                custom_label=result_column,
            ),
        ]
        self._plot_locators.clear()
        self._refresh_series_list()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._title_edit.setText(title)
        self._set_axis_label_text("x", self._column_axis_label(dataset.name, x_column))
        self._set_axis_label_text("y", self._column_axis_label(dataset.name, source_column))
        self._set_axis_label_text("right_y", self._column_axis_label(dataset.name, result_column))
        self.refresh_controls(dataset.name)
        self._select_first_series_for_editing()
        self._render_plot(silent_if_empty=True)
        self.plot_draft_replaced.emit()

    def queue_single_series_plot(
        self,
        dataset: Dataset,
        x_column: str,
        y_column: str,
        title: str,
        label: str | None = None,
    ) -> None:
        """Replace the plot queue with one series."""
        self._plot_series = [
            PlotSeries(
                x_dataset=dataset.name,
                x_column=x_column,
                y_dataset=dataset.name,
                y_column=y_column,
                plot_type="line",
                color="tab:blue",
                line_style="-",
                marker="",
                custom_label=label or y_column,
            )
        ]
        self._plot_locators.clear()
        self._refresh_series_list()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._title_edit.setText(title)
        self._prefill_axis_labels_for_series(self._plot_series[0], force=True)
        self.refresh_controls(dataset.name)
        self._select_first_series_for_editing()
        self._render_plot(silent_if_empty=True)
        self.plot_draft_replaced.emit()

    def queue_plot_series(
        self,
        series: list[PlotSeries],
        title: str,
        x_label: str = "",
        y_label: str = "",
        right_y_label: str = "",
        selected_dataset_name: str | None = None,
    ) -> None:
        """Replace the plot queue with prebuilt series and axis labels."""
        self._plot_series = list(series)
        self._plot_locators.clear()
        self._refresh_series_list()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._title_edit.setText(title)
        self._set_axis_label_text("x", x_label)
        self._set_axis_label_text("y", y_label)
        self._set_axis_label_text("right_y", right_y_label)
        self.refresh_controls(selected_dataset_name)
        self._select_first_series_for_editing()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)
        self.plot_draft_replaced.emit()

    # -- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        """Build plot controls, option tabs, header actions, and canvas."""
        self._x_dataset_combo = QComboBox()
        self._x_column_combo = QComboBox()
        self._x_err_column_combo = QComboBox()
        self._y_dataset_combo = QComboBox()
        self._y_column_combo = QComboBox()
        self._y_err_column_combo = QComboBox()
        self._z_dataset_combo = QComboBox()
        self._z_column_combo = QComboBox()
        self._spectral_dataset_combo = QComboBox()
        self._spectral_column_combo = QComboBox()

        self._plot_family_combo = QComboBox()
        for family_key, family_label, _plot_types in _PLOT_FAMILIES:
            self._plot_family_combo.addItem(family_label, family_key)

        self._plot_type_combo = QComboBox()
        self._refresh_plot_type_combo("line")

        self._y_axis_combo = QComboBox()
        self._y_axis_combo.addItem("Left", "left")
        self._y_axis_combo.addItem("Right", "right")

        self._line_style_combo = QComboBox()
        for label, data in [("Solid", "-"), ("Dashed", "--"), ("Dotted", ":"), ("Dash-dot", "-."), ("None", "")]:
            self._line_style_combo.addItem(label, data)

        self._marker_combo = QComboBox()
        for label, data in [("None",""), ("Circle","o"), ("Square","s"),
                            ("Triangle","^"), ("Diamond","D"), ("Cross","x"),
                            ("Plus","+"), ("Star","*"), ("Dot",".")]:
            self._marker_combo.addItem(label, data)

        self._color_combo = QComboBox()
        for label, data in [("Auto",""), ("Blue","tab:blue"), ("Orange","tab:orange"),
                            ("Green","tab:green"), ("Red","tab:red"),
                            ("Purple","tab:purple"), ("Black","black")]:
            self._color_combo.addItem(label, data)

        self._series_label_edit = QLineEdit()
        self._colorbar_label_edit = QLineEdit()
        self._colorbar_label_edit.setPlaceholderText("Automatic from intensity/Z column")
        self._series_legend_checkbox = QCheckBox("Show this series in legend")
        self._series_legend_checkbox.setChecked(True)

        self._line_width_spin = QDoubleSpinBox()
        self._line_width_spin.setRange(0.0, 10.0)
        self._line_width_spin.setSingleStep(0.2)
        self._line_width_spin.setValue(1.8)

        self._marker_size_spin = QDoubleSpinBox()
        self._marker_size_spin.setRange(1.0, 30.0)
        self._marker_size_spin.setSingleStep(1.0)
        self._marker_size_spin.setValue(6.0)

        self._bar_width_spin = QDoubleSpinBox()
        self._bar_width_spin.setRange(0.01, 1000.0)
        self._bar_width_spin.setSingleStep(0.1)
        self._bar_width_spin.setValue(0.8)

        self._fill_alpha_spin = QDoubleSpinBox()
        self._fill_alpha_spin.setRange(0.0, 1.0)
        self._fill_alpha_spin.setSingleStep(0.05)
        self._fill_alpha_spin.setValue(0.25)

        self._histogram_bins_spin = QSpinBox()
        self._histogram_bins_spin.setRange(1, 1000)
        self._histogram_bins_spin.setValue(20)

        self._histogram_density_checkbox = QCheckBox("Density")
        self._histogram_cumulative_checkbox = QCheckBox("Cumulative")

        self._distribution_columns_list = QListWidget()
        self._distribution_columns_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._distribution_columns_list.setMaximumHeight(130)
        self._distribution_columns_list.itemSelectionChanged.connect(
            lambda: self._set_controls_enabled(bool(self._workspace.dataset_names()))
        )
        self._distribution_mean_checkbox = QCheckBox("Mean")
        self._distribution_median_checkbox = QCheckBox("Median")
        self._distribution_median_checkbox.setChecked(True)
        self._distribution_outliers_checkbox = QCheckBox("Outliers/extrema")
        self._distribution_outliers_checkbox.setChecked(True)

        self._interpolation_method_combo = QComboBox()
        self._interpolation_method_combo.addItem("Linear", "linear")
        self._interpolation_method_combo.addItem("Cubic spline", "cubic_spline")
        self._interpolation_method_combo.addItem("Piecewise cubic", "piecewise_cubic")

        self._surface_resolution_spin = QSpinBox()
        self._surface_resolution_spin.setRange(10, 500)
        self._surface_resolution_spin.setValue(120)

        self._color_map_combo = QComboBox()
        for color_map, label in _COLOR_MAP_LABELS.items():
            self._color_map_combo.addItem(label, color_map)

        self._spectral_center_spin = QDoubleSpinBox()
        self._spectral_center_spin.setRange(-1.0e12, 1.0e12)
        self._spectral_center_spin.setDecimals(8)
        self._spectral_center_spin.setSingleStep(1.0)

        self._spectral_sampling_combo = QComboBox()
        for key, label in _SPECTRAL_SAMPLING_LABELS.items():
            self._spectral_sampling_combo.addItem(label, key)

        self._voronoi_shape_combo = QComboBox()
        for label, data in _VORONOI_SHAPES:
            self._voronoi_shape_combo.addItem(label, data)

        self._title_edit = QLineEdit()
        self._x_label_edit = QLineEdit()
        self._y_label_edit = QLineEdit()
        self._right_y_label_edit = QLineEdit()

        self._x_label_size_spin = self._axis_font_size_spin()
        self._x_tick_size_spin = self._axis_font_size_spin()
        self._y_label_size_spin = self._axis_font_size_spin()
        self._y_tick_size_spin = self._axis_font_size_spin()
        self._right_y_label_size_spin = self._axis_font_size_spin()
        self._right_y_tick_size_spin = self._axis_font_size_spin()

        self._x_scale_combo = QComboBox()
        self._x_scale_combo.addItems(["linear", "log"])
        self._y_scale_combo = QComboBox()
        self._y_scale_combo.addItems(["linear", "log"])
        self._right_y_scale_combo = QComboBox()
        self._right_y_scale_combo.addItems(["linear", "log"])

        self._x_min_edit = QLineEdit()
        self._x_max_edit = QLineEdit()
        self._y_min_edit = QLineEdit()
        self._y_max_edit = QLineEdit()
        self._right_y_min_edit = QLineEdit()
        self._right_y_max_edit = QLineEdit()

        self._style_preset_combo = QComboBox()
        for label, data in _PLOT_STYLE_PRESETS:
            self._style_preset_combo.addItem(label, data)

        self._style_cycle_combo = QComboBox()
        for label, data in _PLOT_STYLE_CYCLES:
            self._style_cycle_combo.addItem(label, data)

        self._style_latex_checkbox = QCheckBox("Use LaTeX text")
        self._style_latex_checkbox.setChecked(False)
        self._style_custom_edit = QLineEdit()
        self._style_custom_edit.setPlaceholderText("e.g. science,nature,no-latex,bright")

        self._grid_checkbox = QCheckBox("Grid")
        self._grid_checkbox.setChecked(True)

        self._locator_series_combo = QComboBox()
        self._locator_mode_combo = QComboBox()
        self._locator_mode_combo.addItem("Find Y from X", "x_to_y")
        self._locator_mode_combo.addItem("Find X from Y", "y_to_x")
        self._locator_x_edit = QLineEdit()
        self._locator_x_edit.setPlaceholderText("X value")
        self._locator_y_edit = QLineEdit()
        self._locator_y_edit.setPlaceholderText("Y coordinate")

        self._locator_marker_combo = QComboBox()
        for label, data in [("Circle","o"), ("Square","s"), ("Triangle","^"),
                            ("Diamond","D"), ("Cross","x"), ("Plus","+"),
                            ("Star","*"), ("Dot",".")]:
            self._locator_marker_combo.addItem(label, data)

        self._locator_color_combo = QComboBox()
        for label, data in [("Red","tab:red"), ("Blue","tab:blue"), ("Orange","tab:orange"),
                            ("Green","tab:green"), ("Purple","tab:purple"), ("Black","black")]:
            self._locator_color_combo.addItem(label, data)

        self._locator_size_spin = QDoubleSpinBox()
        self._locator_size_spin.setRange(10.0, 500.0)
        self._locator_size_spin.setSingleStep(10.0)
        self._locator_size_spin.setValue(80.0)
        self._locator_size_spin.setSuffix(" pt")

        self._legend_checkbox = QCheckBox("Show Legend")
        self._legend_checkbox.setChecked(True)
        self._legend_pos_combo = QComboBox()
        for label, location in (
            ("Automatic", "best"),
            ("Upper right", "upper right"),
            ("Upper left", "upper left"),
            ("Lower left", "lower left"),
            ("Lower right", "lower right"),
            ("Center right", "center right"),
            ("Center left", "center left"),
            ("Upper center", "upper center"),
            ("Lower center", "lower center"),
            ("Center", "center"),
            ("Outside right", "outside right"),
            ("Outside top", "outside top"),
            ("Outside bottom", "outside bottom"),
        ):
            self._legend_pos_combo.addItem(label, location)

        self._legend_font_size_spin = QDoubleSpinBox()
        self._legend_font_size_spin.setRange(5.0, 72.0)
        self._legend_font_size_spin.setSingleStep(0.5)
        self._legend_font_size_spin.setValue(10.0)
        self._legend_font_size_spin.setSuffix(" pt")
        self._legend_title_edit = QLineEdit()
        self._legend_title_edit.setPlaceholderText("Optional")
        self._legend_title_size_spin = QDoubleSpinBox()
        self._legend_title_size_spin.setRange(5.0, 72.0)
        self._legend_title_size_spin.setSingleStep(0.5)
        self._legend_title_size_spin.setValue(10.0)
        self._legend_title_size_spin.setSuffix(" pt")
        self._legend_columns_spin = QSpinBox()
        self._legend_columns_spin.setRange(1, 20)
        self._legend_columns_spin.setValue(1)
        self._legend_frame_checkbox = QCheckBox("Show frame")
        self._legend_frame_checkbox.setChecked(True)
        self._legend_frame_alpha_spin = QDoubleSpinBox()
        self._legend_frame_alpha_spin.setRange(0.0, 1.0)
        self._legend_frame_alpha_spin.setSingleStep(0.05)
        self._legend_frame_alpha_spin.setValue(0.8)
        self._legend_marker_scale_spin = QDoubleSpinBox()
        self._legend_marker_scale_spin.setRange(0.1, 10.0)
        self._legend_marker_scale_spin.setSingleStep(0.1)
        self._legend_marker_scale_spin.setValue(1.0)
        self._legend_handle_length_spin = QDoubleSpinBox()
        self._legend_handle_length_spin.setRange(0.0, 20.0)
        self._legend_handle_length_spin.setSingleStep(0.25)
        self._legend_handle_length_spin.setValue(2.0)
        self._legend_include_locators_checkbox = QCheckBox("Include locator markers")
        self._legend_include_locators_checkbox.setChecked(True)
        self._legend_include_bands_checkbox = QCheckBox("Include confidence bands")
        self._legend_include_bands_checkbox.setChecked(True)

        self._export_size_mode_combo = QComboBox()
        self._export_size_mode_combo.addItem("Full exported image", "figure")
        self._export_size_mode_combo.addItem("Plotting area (axes box)", "plot_area")
        self._export_size_mode_combo.setToolTip(
            "Choose whether Width/Height describe the complete exported image or only "
            "the inner box bounded by the X and Y axes."
        )

        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(3.0, 20.0)
        self._width_spin.setSingleStep(0.5)
        self._width_spin.setValue(7.0)
        self._width_spin.setSuffix(" in")

        self._height_spin = QDoubleSpinBox()
        self._height_spin.setRange(2.0, 15.0)
        self._height_spin.setSingleStep(0.5)
        self._height_spin.setValue(4.8)
        self._height_spin.setSuffix(" in")
        self._export_size_help_label = QLabel()
        self._export_size_help_label.setWordWrap(True)
        self._export_size_help_label.setObjectName("MutedLabel")

        self._auto_preview_checkbox = QCheckBox("Live preview")
        self._auto_preview_checkbox.setChecked(False)
        self._auto_preview_checkbox.setToolTip(
            "When enabled, plot-wide Axes and Legend changes redraw automatically. "
            "Series edits always wait for Add Series or Update Series."
        )
        self._preview_status_label = QLabel("Preview current")
        self._preview_status_label.setObjectName("MutedLabel")

        self._series_editor_status_label = QLabel(
            "New series - choose the mapping, then click Add Series"
        )
        self._series_editor_status_label.setObjectName("MutedLabel")
        self._series_editor_status_label.setWordWrap(True)

        self._series_list = QListWidget()
        self._series_list.itemSelectionChanged.connect(self._handle_series_selection_changed)
        self._series_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._series_list.customContextMenuRequested.connect(
            self._show_series_context_menu
        )

        self._locator_list = QListWidget()
        self._locator_list.itemSelectionChanged.connect(
            lambda: self._set_controls_enabled(bool(self._workspace.dataset_names()))
        )
        self._locator_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._locator_list.customContextMenuRequested.connect(
            self._show_locator_context_menu
        )

        new_series_btn = QPushButton("New Series")
        new_series_btn.setToolTip(
            "Leave queued series unchanged and prepare the editor for another series."
        )
        new_series_btn.clicked.connect(self._start_new_series)
        self._new_series_button = new_series_btn

        commit_series_btn = QPushButton("Add Series")
        commit_series_btn.setToolTip(
            "Add a new series, or explicitly update the selected queued series."
        )
        commit_series_btn.clicked.connect(self._commit_series_editor)
        self._commit_series_button = commit_series_btn

        discard_edits_btn = QPushButton("Revert Edits")
        discard_edits_btn.setToolTip(
            "Reload the selected queued series and discard uncommitted editor changes."
        )
        discard_edits_btn.clicked.connect(self._discard_series_edits)
        self._discard_series_edits_button = discard_edits_btn

        rm_btn = QPushButton("Remove Selected")
        rm_btn.clicked.connect(self._remove_selected_series)
        self._remove_series_button = rm_btn

        clr_btn = QPushButton("Clear All")
        clr_btn.clicked.connect(self._clear_series)
        self._clear_series_button = clr_btn


        self._render_button = QPushButton("Refresh Plot")
        self._render_button.setToolTip(
            "Redraw the canvas using committed series and the current plot-wide settings."
        )
        self._render_button.clicked.connect(self._render_plot)

        add_loc = QPushButton("Add Locator")
        add_loc.clicked.connect(self._add_locator)
        self._add_locator_button = add_loc

        rm_loc = QPushButton("Remove Locator")
        rm_loc.clicked.connect(self._remove_selected_locator)
        self._remove_locator_button = rm_loc

        clr_loc = QPushButton("Clear")
        clr_loc.clicked.connect(self._clear_locators)
        self._clear_locators_button = clr_loc

        # --- layout groups ---
        series_group = QGroupBox("Series")
        sf = QFormLayout(series_group)
        self._series_rows: dict[str, tuple[QWidget | None, QWidget]] = {}
        self._bar_options_panel = self._build_bar_options_panel()
        self._fill_options_panel = self._build_fill_options_panel()
        self._histogram_options_panel = self._build_histogram_options_panel()
        self._distribution_options_panel = self._build_distribution_options_panel()
        self._surface_options_panel = self._build_surface_options_panel()
        self._voronoi_options_panel = self._build_voronoi_options_panel()
        self._add_series_row(sf, "plot_family", "Plot family", self._plot_family_combo)
        self._add_series_row(sf, "plot_type", "Subtype", self._plot_type_combo)
        self._add_series_row(
            sf,
            "spectral_dataset",
            "Spectral map dataset",
            self._spectral_dataset_combo,
        )
        self._add_series_row(sf, "x_dataset", "X dataset", self._x_dataset_combo)
        self._add_series_row(sf, "x_column", "X column", self._x_column_combo)
        self._add_series_row(sf, "x_error", "X error", self._x_err_column_combo)
        self._add_series_row(sf, "y_dataset", "Y dataset", self._y_dataset_combo)
        self._add_series_row(sf, "y_column", "Y column", self._y_column_combo)
        self._add_series_row(sf, "z_dataset", "Z dataset", self._z_dataset_combo)
        self._add_series_row(sf, "z_column", "Z column", self._z_column_combo)
        self._add_series_row(
            sf,
            "spectral_column",
            "Raman shift / frequency",
            self._spectral_column_combo,
        )
        self._add_series_row(
            sf,
            "spectral_center",
            "Target center",
            self._spectral_center_spin,
        )
        self._add_series_row(
            sf,
            "spectral_sampling",
            "Spectral sampling",
            self._spectral_sampling_combo,
        )
        self._add_series_row(sf, "distribution_columns", "Columns", self._distribution_columns_list)
        self._add_series_row(sf, "y_error", "Y error", self._y_err_column_combo)
        self._add_series_row(sf, "y_axis", "Y axis", self._y_axis_combo)
        self._add_series_row(sf, "label", "Label", self._series_label_edit)
        self._add_series_row(
            sf,
            "colorbar_label",
            "Colour-bar label",
            self._colorbar_label_edit,
        )
        self._add_series_row(sf, "show_in_legend", None, self._series_legend_checkbox)
        self._add_series_row(sf, "line", "Line", self._line_style_combo)
        self._add_series_row(sf, "line_width", "Line width", self._line_width_spin)
        self._add_series_row(sf, "marker", "Marker", self._marker_combo)
        self._add_series_row(sf, "marker_size", "Marker size", self._marker_size_spin)
        self._add_series_row(sf, "color", "Color", self._color_combo)
        self._add_series_row(sf, "bar_options", None, self._bar_options_panel)
        self._add_series_row(sf, "fill_options", None, self._fill_options_panel)
        self._add_series_row(sf, "histogram_options", None, self._histogram_options_panel)
        self._add_series_row(sf, "distribution_options", None, self._distribution_options_panel)
        self._add_series_row(sf, "color_map", "Palette", self._color_map_combo)
        self._add_series_row(sf, "surface_options", None, self._surface_options_panel)
        self._add_series_row(sf, "voronoi_options", None, self._voronoi_options_panel)
        sb = QVBoxLayout()
        sb.addWidget(self._series_editor_status_label)
        series_add_row = QHBoxLayout()
        series_add_row.addWidget(new_series_btn)
        series_add_row.addWidget(commit_series_btn)
        series_remove_row = QHBoxLayout()
        series_remove_row.addWidget(discard_edits_btn)
        series_remove_row.addWidget(rm_btn)
        series_remove_row.addWidget(clr_btn)
        sb.addLayout(series_add_row)
        sb.addLayout(series_remove_row)
        sf.addRow(sb)
        sf.addRow("Queued", self._series_list)

        axes_group = QGroupBox("Axes")
        af = QFormLayout(axes_group)
        af.addRow("Title", self._title_edit)
        af.addRow("X label", self._x_label_edit)
        af.addRow("Left Y label", self._y_label_edit)
        af.addRow("Right Y label", self._right_y_label_edit)
        af.addRow(
            "X text sizes",
            self._axis_font_size_row(self._x_label_size_spin, self._x_tick_size_spin),
        )
        af.addRow(
            "Left Y text sizes",
            self._axis_font_size_row(self._y_label_size_spin, self._y_tick_size_spin),
        )
        af.addRow(
            "Right Y text sizes",
            self._axis_font_size_row(
                self._right_y_label_size_spin,
                self._right_y_tick_size_spin,
            ),
        )
        af.addRow("X scale", self._x_scale_combo)
        af.addRow("Left Y scale", self._y_scale_combo)
        af.addRow("Right Y scale", self._right_y_scale_combo)
        af.addRow("X range", self._range_row(self._x_min_edit, self._x_max_edit))
        af.addRow("Left Y range", self._range_row(self._y_min_edit, self._y_max_edit))
        af.addRow("Right Y range", self._range_row(self._right_y_min_edit, self._right_y_max_edit))
        af.addRow("Style", self._style_preset_combo)
        af.addRow("Color cycle", self._style_cycle_combo)
        af.addRow("", self._style_latex_checkbox)
        af.addRow("Custom styles", self._style_custom_edit)
        af.addRow("", self._grid_checkbox)
        af.addRow("Export size basis", self._export_size_mode_combo)
        af.addRow("Export width", self._width_spin)
        af.addRow("Export height", self._height_spin)
        af.addRow("", self._export_size_help_label)

        legend_group = QGroupBox("Legend")
        legend_form = QFormLayout(legend_group)
        legend_form.addRow("", self._legend_checkbox)
        legend_form.addRow("Location", self._legend_pos_combo)
        legend_form.addRow("Text size", self._legend_font_size_spin)
        legend_form.addRow("Title", self._legend_title_edit)
        legend_form.addRow("Title size", self._legend_title_size_spin)
        legend_form.addRow("Columns", self._legend_columns_spin)
        legend_form.addRow("", self._legend_frame_checkbox)
        legend_form.addRow("Frame opacity", self._legend_frame_alpha_spin)
        legend_form.addRow("Marker scale", self._legend_marker_scale_spin)
        legend_form.addRow("Handle length", self._legend_handle_length_spin)
        legend_form.addRow("", self._legend_include_locators_checkbox)
        legend_form.addRow("", self._legend_include_bands_checkbox)
        legend_help = QLabel(
            "Legend entries follow queued-series order across left and right axes. "
            "Outside positions reserve figure space for export."
        )
        legend_help.setWordWrap(True)
        legend_form.addRow("", legend_help)

        locator_group = QGroupBox("Data Location")
        lf = QFormLayout(locator_group)
        lf.addRow("Series", self._locator_series_combo)
        lf.addRow("Lookup", self._locator_mode_combo)
        lf.addRow("X value", self._locator_x_edit)
        lf.addRow("Y value", self._locator_y_edit)
        lf.addRow("Marker", self._locator_marker_combo)
        lf.addRow("Size", self._locator_size_spin)
        lf.addRow("Color", self._locator_color_combo)
        lb = QHBoxLayout()
        lb.addWidget(add_loc); lb.addWidget(rm_loc); lb.addWidget(clr_loc)
        lf.addRow(lb)
        lf.addRow("Located", self._locator_list)

        ctrl_tabs = QTabWidget()
        ctrl_tabs.addTab(series_group, "Series")
        ctrl_tabs.addTab(axes_group, "Axes")
        ctrl_tabs.addTab(legend_group, "Legend")
        ctrl_tabs.addTab(locator_group, "Locator")

        ctrl_panel = QWidget()
        ctrl_panel.setMinimumWidth(330)
        cl = QVBoxLayout(ctrl_panel)
        cl.addWidget(ctrl_tabs)
        cl.addStretch(1)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self._auto_preview_checkbox)
        preview_row.addStretch(1)
        preview_row.addWidget(self._preview_status_label)
        cl.addLayout(preview_row)
        cl.addWidget(self._render_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(350)
        scroll.setWidget(ctrl_panel)
        self._plot_options_scroll = scroll

        if self._external_options:
            self._plot_splitter = None
        else:
            splitter = QSplitter(Qt.Horizontal)
            splitter.addWidget(scroll)
            splitter.addWidget(self._plot_canvas)
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([460, 760])
            self._plot_splitter = splitter

        self._active_plot_label = QLabel("Unsaved plot")
        self._active_plot_label.setObjectName("SectionLabel")

        self._save_plot_button = QPushButton("Save Plot")
        self._save_plot_button.clicked.connect(self.save_plot_requested.emit)
        self._copy_plot_button = QPushButton("Copy Plot")
        self._copy_plot_button.setToolTip(
            "Copy the current on-screen plot visualization to the clipboard"
        )
        self._copy_plot_button.clicked.connect(self.copy_plot_to_clipboard)
        self._new_plot_button = QPushButton("New Plot")
        self._new_plot_button.clicked.connect(self.new_plot_requested.emit)
        self._load_plot_button = QPushButton("Load Selected")
        self._load_plot_button.clicked.connect(self.load_plot_requested.emit)
        self._remove_plot_button = QPushButton("Remove Saved")
        self._remove_plot_button.clicked.connect(self.remove_plot_requested.emit)

        self._toggle_options_button = QPushButton("Hide Inspector" if self._external_options else "Hide Options")
        self._toggle_options_button.clicked.connect(self._toggle_plot_options)
        top_row = QHBoxLayout()
        top_row.addWidget(self._active_plot_label)
        top_row.addStretch(1)
        top_row.addWidget(self._new_plot_button)
        top_row.addWidget(self._save_plot_button)
        top_row.addWidget(self._copy_plot_button)
        top_row.addWidget(self._load_plot_button)
        top_row.addWidget(self._remove_plot_button)
        top_row.addWidget(self._toggle_options_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        if self._external_options:
            layout.addWidget(self._plot_canvas)
        else:
            layout.addWidget(self._plot_splitter)

        self._x_dataset_combo.currentTextChanged.connect(
            lambda: self._update_column_combo(self._x_dataset_combo, self._x_column_combo, ("x",))
        )
        self._x_dataset_combo.currentTextChanged.connect(
            lambda: self._update_error_column_combo(
                self._x_dataset_combo,
                self._x_err_column_combo,
                ("x_error", "error"),
            )
        )
        self._y_dataset_combo.currentTextChanged.connect(
            lambda: self._update_column_combo(self._y_dataset_combo, self._y_column_combo, ("y",))
        )
        self._y_dataset_combo.currentTextChanged.connect(
            lambda: self._update_error_column_combo(
                self._y_dataset_combo,
                self._y_err_column_combo,
                ("y_error", "error"),
            )
        )
        self._y_dataset_combo.currentTextChanged.connect(self._update_distribution_columns_list)
        self._z_dataset_combo.currentTextChanged.connect(
            lambda: self._update_column_combo(self._z_dataset_combo, self._z_column_combo, ("z",))
        )
        self._spectral_dataset_combo.currentTextChanged.connect(
            self._sync_spectral_dataset_mapping
        )
        self._spectral_column_combo.currentTextChanged.connect(
            self._update_spectral_center_range
        )
        self._plot_family_combo.currentIndexChanged.connect(self._handle_plot_family_changed)
        self._plot_type_combo.currentIndexChanged.connect(self._apply_plot_type_defaults)
        self._locator_series_combo.currentIndexChanged.connect(self._update_locator_mode_controls)
        self._locator_mode_combo.currentIndexChanged.connect(self._update_locator_mode_controls)
        self._connect_axis_label_prefill_signals()
        self._connect_series_editor_signals()
        self._connect_global_preview_signals()
        self._legend_checkbox.toggled.connect(self._update_legend_controls_enabled)
        self._legend_frame_checkbox.toggled.connect(self._update_legend_controls_enabled)
        self._auto_preview_checkbox.toggled.connect(self._handle_auto_preview_toggled)
        self._export_size_mode_combo.currentIndexChanged.connect(self._sync_export_size)
        self._width_spin.valueChanged.connect(self._sync_export_size)
        self._height_spin.valueChanged.connect(self._sync_export_size)
        self._update_legend_controls_enabled()
        self._sync_export_size()
        self._update_plot_type_option_visibility()
        self.refresh_controls()

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _range_row(min_edit: QLineEdit, max_edit: QLineEdit) -> QWidget:
        """Return a compact min/max row for axis range controls."""
        min_edit.setPlaceholderText("min")
        max_edit.setPlaceholderText("max")
        min_edit.setMaximumWidth(90)
        max_edit.setMaximumWidth(90)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(min_edit)
        h.addWidget(max_edit)
        h.addStretch(1)
        return row

    @staticmethod
    def _axis_font_size_spin() -> QDoubleSpinBox:
        """Return an axis-font control where zero follows the active style."""
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 72.0)
        spin.setSingleStep(0.5)
        spin.setSuffix(" pt")
        spin.setSpecialValueText("Style default")
        return spin

    @staticmethod
    def _axis_font_size_row(
        label_spin: QDoubleSpinBox,
        tick_spin: QDoubleSpinBox,
    ) -> QWidget:
        """Return compact label/tick typography controls for one axis."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Label"))
        layout.addWidget(label_spin)
        layout.addWidget(QLabel("Numbers"))
        layout.addWidget(tick_spin)
        return row

    def _build_bar_options_panel(self) -> QWidget:
        """Return bar-specific series controls."""
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Bar width"))
        layout.addWidget(self._bar_width_spin)
        layout.addStretch(1)
        return panel

    def _build_fill_options_panel(self) -> QWidget:
        """Return fill/alpha series controls."""
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Fill alpha"))
        layout.addWidget(self._fill_alpha_spin)
        layout.addStretch(1)
        return panel

    def _build_histogram_options_panel(self) -> QWidget:
        """Return histogram-specific series controls."""
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Bins"))
        layout.addWidget(self._histogram_bins_spin)
        layout.addWidget(self._histogram_density_checkbox)
        layout.addWidget(self._histogram_cumulative_checkbox)
        layout.addStretch(1)
        return panel

    def _build_distribution_options_panel(self) -> QWidget:
        """Return box/violin distribution controls."""
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._distribution_mean_checkbox)
        layout.addWidget(self._distribution_median_checkbox)
        layout.addWidget(self._distribution_outliers_checkbox)
        layout.addStretch(1)
        return panel

    def _build_surface_options_panel(self) -> QWidget:
        """Return 2D interpolated map controls."""
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Interpolation"))
        layout.addWidget(self._interpolation_method_combo)
        layout.addWidget(QLabel("Grid"))
        layout.addWidget(self._surface_resolution_spin)
        layout.addStretch(1)
        return panel

    def _build_voronoi_options_panel(self) -> QWidget:
        """Return Voronoi composition controls."""
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Container"))
        layout.addWidget(self._voronoi_shape_combo)
        layout.addStretch(1)
        return panel

    def _add_series_row(
        self,
        form: QFormLayout,
        key: str,
        label: str | None,
        field: QWidget,
    ) -> None:
        """Add a Series form row and remember its label/widget pair for visibility updates."""
        if label is None:
            form.addRow(field)
            label_widget = None
        else:
            form.addRow(label, field)
            label_widget = form.labelForField(field)
        self._series_rows[key] = (label_widget, field)

    def _connect_axis_label_prefill_signals(self) -> None:
        """Refresh axis-label suggestions when series controls change."""
        for combo in (
            self._plot_family_combo,
            self._plot_type_combo,
            self._x_dataset_combo,
            self._x_column_combo,
            self._y_dataset_combo,
            self._y_column_combo,
            self._z_dataset_combo,
            self._z_column_combo,
            self._spectral_dataset_combo,
            self._spectral_column_combo,
            self._spectral_sampling_combo,
            self._y_axis_combo,
        ):
            combo.currentIndexChanged.connect(
                lambda _index=0: self._prefill_axis_labels_from_plot_context()
            )
            combo.currentTextChanged.connect(
                lambda _text="": self._prefill_axis_labels_from_plot_context()
            )
        self._histogram_density_checkbox.toggled.connect(
            lambda _checked=False: self._prefill_axis_labels_from_plot_context()
        )
        self._distribution_columns_list.itemSelectionChanged.connect(
            self._prefill_axis_labels_from_plot_context
        )

    def _connect_global_preview_signals(self) -> None:
        """Debounce redraws for global appearance controls."""
        for combo in (
            self._x_scale_combo,
            self._y_scale_combo,
            self._right_y_scale_combo,
            self._style_preset_combo,
            self._style_cycle_combo,
            self._legend_pos_combo,
        ):
            combo.currentIndexChanged.connect(self._schedule_preview)
        for edit in (
            self._title_edit,
            self._x_label_edit,
            self._y_label_edit,
            self._right_y_label_edit,
            self._x_min_edit,
            self._x_max_edit,
            self._y_min_edit,
            self._y_max_edit,
            self._right_y_min_edit,
            self._right_y_max_edit,
            self._style_custom_edit,
            self._legend_title_edit,
        ):
            edit.textChanged.connect(self._schedule_preview)
        for checkbox in (
            self._grid_checkbox,
            self._style_latex_checkbox,
            self._legend_checkbox,
            self._legend_frame_checkbox,
            self._legend_include_locators_checkbox,
            self._legend_include_bands_checkbox,
        ):
            checkbox.toggled.connect(self._schedule_preview)
        for spin in (
            self._x_label_size_spin,
            self._x_tick_size_spin,
            self._y_label_size_spin,
            self._y_tick_size_spin,
            self._right_y_label_size_spin,
            self._right_y_tick_size_spin,
            self._legend_font_size_spin,
            self._legend_title_size_spin,
            self._legend_columns_spin,
            self._legend_frame_alpha_spin,
            self._legend_marker_scale_spin,
            self._legend_handle_length_spin,
        ):
            spin.valueChanged.connect(self._schedule_preview)

    def _connect_series_editor_signals(self) -> None:
        """Track staged editor changes without mutating queued series."""
        for combo in (
            self._plot_family_combo,
            self._plot_type_combo,
            self._x_dataset_combo,
            self._x_column_combo,
            self._x_err_column_combo,
            self._y_dataset_combo,
            self._y_column_combo,
            self._y_err_column_combo,
            self._z_dataset_combo,
            self._z_column_combo,
            self._spectral_dataset_combo,
            self._spectral_column_combo,
            self._spectral_sampling_combo,
            self._y_axis_combo,
            self._line_style_combo,
            self._marker_combo,
            self._color_combo,
            self._color_map_combo,
            self._interpolation_method_combo,
            self._voronoi_shape_combo,
        ):
            combo.currentIndexChanged.connect(self._handle_series_editor_changed)
        self._series_label_edit.textChanged.connect(self._handle_series_editor_changed)
        self._colorbar_label_edit.textChanged.connect(self._handle_series_editor_changed)
        for spin in (
            self._line_width_spin,
            self._marker_size_spin,
            self._bar_width_spin,
            self._fill_alpha_spin,
            self._histogram_bins_spin,
            self._surface_resolution_spin,
            self._spectral_center_spin,
        ):
            spin.valueChanged.connect(self._handle_series_editor_changed)
        for checkbox in (
            self._series_legend_checkbox,
            self._histogram_density_checkbox,
            self._histogram_cumulative_checkbox,
            self._distribution_mean_checkbox,
            self._distribution_median_checkbox,
            self._distribution_outliers_checkbox,
        ):
            checkbox.toggled.connect(self._handle_series_editor_changed)
        self._distribution_columns_list.itemSelectionChanged.connect(
            self._handle_series_editor_changed
        )

    def _handle_series_editor_changed(self, _value: object = None) -> None:
        """Mark selected-series controls as staged until explicitly committed."""
        if self._loading_series_controls:
            return
        self._update_series_editor_state()

    def _schedule_preview(self, _value: object = None) -> None:
        """Mark the canvas stale and schedule one redraw when live preview is enabled."""
        if self._loading_plot_settings or not self._plot_series:
            return
        self._preview_dirty = True
        self._preview_status_label.setText("Preview out of date")
        if self._auto_preview_checkbox.isChecked():
            self._preview_status_label.setText("Preview pending")
            self._preview_timer.start()

    def _render_scheduled_preview(self) -> None:
        """Render the latest coalesced appearance state."""
        if self._auto_preview_checkbox.isChecked() and self._plot_series:
            self._render_plot(silent_if_empty=True, show_validation_messages=False)

    def _handle_auto_preview_toggled(self, enabled: bool) -> None:
        """Render pending changes when automatic preview is switched back on."""
        if enabled and self._preview_dirty:
            self._schedule_preview()

    def _update_legend_controls_enabled(self, _checked: bool = False) -> None:
        """Enable legend detail fields only when their parent option is active."""
        enabled = self._legend_checkbox.isChecked()
        for widget in (
            self._legend_pos_combo,
            self._legend_font_size_spin,
            self._legend_title_edit,
            self._legend_title_size_spin,
            self._legend_columns_spin,
            self._legend_frame_checkbox,
            self._legend_marker_scale_spin,
            self._legend_handle_length_spin,
            self._legend_include_locators_checkbox,
            self._legend_include_bands_checkbox,
        ):
            widget.setEnabled(enabled)
        self._legend_frame_alpha_spin.setEnabled(
            enabled and self._legend_frame_checkbox.isChecked()
        )

    def _sync_export_size(self, _value: object = None) -> None:
        """Update export-only geometry without marking or resizing the canvas preview."""
        size_mode = str(self._export_size_mode_combo.currentData() or "figure")
        self._plot_canvas.set_export_size(
            self._width_spin.value(),
            self._height_spin.value(),
            size_mode,
        )
        if size_mode == "plot_area":
            self._export_size_help_label.setText(
                "Width and height describe the inner plotting box bounded by the X and Y "
                "axes. JASC calculates the larger complete image needed for labels and margins."
            )
        else:
            self._export_size_help_label.setText(
                "Width and height describe the complete exported image. They do not resize "
                "the interactive canvas."
            )

    def _refresh_plot_type_combo(self, preferred: str | None = None) -> None:
        """Populate the subtype selector with plot types from the selected family."""
        family_key = str(self._plot_family_combo.currentData() or "xy")
        plot_types = _PLOT_FAMILY_TYPES.get(family_key, _PLOT_FAMILY_TYPES["xy"])
        selected = preferred or str(self._plot_type_combo.currentData() or "")
        if selected not in plot_types:
            selected = plot_types[0]

        self._plot_type_combo.blockSignals(True)
        self._plot_type_combo.clear()
        for plot_type_key in plot_types:
            self._plot_type_combo.addItem(plot_type_label(plot_type_key), plot_type_key)
            plot_type = PLOT_TYPES.get(plot_type_key)
            if plot_type is not None:
                self._plot_type_combo.setItemData(
                    self._plot_type_combo.count() - 1,
                    plot_type.description,
                    Qt.ToolTipRole,
                )
        index = self._plot_type_combo.findData(selected)
        if index >= 0:
            self._plot_type_combo.setCurrentIndex(index)
        self._plot_type_combo.blockSignals(False)
        current_type = PLOT_TYPES.get(str(self._plot_type_combo.currentData() or ""))
        self._plot_type_combo.setToolTip(current_type.description if current_type else "")

    def _handle_plot_family_changed(self, _index: int = 0) -> None:
        """Refresh subtype choices after changing the plot family."""
        current_type = str(self._plot_type_combo.currentData() or "")
        self._refresh_plot_type_combo(current_type)
        if str(self._plot_family_combo.currentData() or "") == "spectra":
            self._sync_spectral_dataset_mapping()
        self._apply_plot_type_defaults()
        self._prefill_axis_labels_from_plot_context()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    def _update_column_combo(
        self,
        ds_combo: QComboBox,
        col_combo: QComboBox,
        preferred_roles: tuple[str, ...] = (),
    ) -> None:
        """Refresh a column combo from the dataset currently selected beside it."""
        name = ds_combo.currentText()
        cols: list[str] = []
        preferred: str | None = None
        if name:
            try:
                ds = self._workspace.get_dataset(name)
                cols = [str(c) for c in ds.frame.columns]
                current = col_combo.currentText()
                if current and current in cols:
                    preferred = current
                else:
                    preferred = self._preferred_column_for_roles(ds, preferred_roles)
            except KeyError:
                pass
        self._set_combo_items(col_combo, cols, preferred)
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    def _sync_spectral_dataset_mapping(self, _name: str = "") -> None:
        """Use one long-form spectral-map dataset for all four required columns."""
        name = self._spectral_dataset_combo.currentText()
        for combo in (
            self._x_dataset_combo,
            self._y_dataset_combo,
            self._z_dataset_combo,
        ):
            if combo.currentText() != name:
                combo.setCurrentText(name)
        self._update_spectral_column_combos()

    def _update_spectral_column_combos(self) -> None:
        """Populate and sensibly preselect long-form spectral-map columns."""
        name = self._spectral_dataset_combo.currentText()
        columns: list[str] = []
        if name:
            try:
                columns = [
                    str(column)
                    for column in self._workspace.get_dataset(name).frame.columns
                ]
            except KeyError:
                pass

        x_column = self._named_column(
            columns,
            ("x", "x_coord", "x coordinate", "map x coordinate"),
        )
        y_column = self._named_column(
            columns,
            ("y", "y_coord", "y coordinate", "map y coordinate"),
        )
        spectral_column = self._named_column(
            columns,
            ("raman shift", "wavenumber", "wave number", "frequency", "wavelength"),
        )
        intensity_column = self._named_column(
            columns,
            ("intensity", "raman intensity", "signal", "counts", "count"),
        )

        self._set_combo_items(self._x_column_combo, columns, x_column)
        self._set_combo_items(self._y_column_combo, columns, y_column)
        self._set_combo_items(self._z_column_combo, columns, intensity_column)
        self._set_combo_items(
            self._spectral_column_combo,
            columns,
            spectral_column,
        )
        self._update_spectral_center_range()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    @staticmethod
    def _named_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
        """Return an exact, then substring, case-insensitive column-name match."""
        normalized = {column.strip().casefold(): column for column in columns}
        for candidate in candidates:
            if candidate in normalized:
                return normalized[candidate]
        for candidate in candidates:
            for normalized_name, column in normalized.items():
                if candidate in normalized_name:
                    return column
        return None

    def _update_spectral_center_range(self, _column: str = "") -> None:
        """Constrain the target-center editor to the selected measured spectral axis."""
        name = self._spectral_dataset_combo.currentText()
        column = self._spectral_column_combo.currentText()
        if not name or not column:
            return
        try:
            dataset = self._workspace.get_dataset(name)
            values = pd.to_numeric(
                dataset.frame[column],
                errors="coerce",
            ).dropna()
        except (KeyError, TypeError):
            return
        finite = np.sort(values[np.isfinite(values)].unique())
        if finite.size == 0:
            return

        old_value = self._spectral_center_spin.value()
        minimum = float(finite[0])
        maximum = float(finite[-1])
        suggested = float(finite[finite.size // 2])
        if minimum <= old_value <= maximum:
            suggested = old_value
        step = 1.0
        if finite.size > 1:
            positive_steps = np.diff(finite)
            positive_steps = positive_steps[positive_steps > 0]
            if positive_steps.size:
                step = float(np.median(positive_steps))

        self._spectral_center_spin.blockSignals(True)
        self._spectral_center_spin.setRange(minimum, maximum)
        self._spectral_center_spin.setSingleStep(step)
        self._spectral_center_spin.setValue(suggested)
        metadata = dataset.column_metadata.get(column)
        unit = metadata.unit if metadata is not None else ""
        self._spectral_center_spin.setSuffix(f" {unit}" if unit else "")
        self._spectral_center_spin.blockSignals(False)

    def _update_distribution_columns_list(self) -> None:
        """Refresh the multi-column selector used by distribution plots."""
        previous = set(self._selected_distribution_columns())
        preferred = self._y_column_combo.currentText()
        self._distribution_columns_list.blockSignals(True)
        self._distribution_columns_list.clear()

        name = self._y_dataset_combo.currentText()
        columns: list[str] = []
        if name:
            try:
                dataset = self._workspace.get_dataset(name)
                columns = [str(column) for column in dataset.frame.columns]
            except KeyError:
                pass

        for column in columns:
            self._distribution_columns_list.addItem(column)

        selected = previous.intersection(columns)
        if not selected and preferred in columns:
            selected = {preferred}
        for row in range(self._distribution_columns_list.count()):
            item = self._distribution_columns_list.item(row)
            item.setSelected(item.text() in selected)

        self._distribution_columns_list.blockSignals(False)
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    def _update_error_column_combo(
        self,
        ds_combo: QComboBox,
        col_combo: QComboBox,
        preferred_roles: tuple[str, ...] = (),
    ) -> None:
        """Refresh an error column combo, allowing a blank 'no error' selection."""
        name = ds_combo.currentText()
        cols: list[str] = [""]
        preferred: str | None = None
        if name:
            try:
                ds = self._workspace.get_dataset(name)
                dataset_columns = [str(c) for c in ds.frame.columns]
                cols.extend(dataset_columns)
                current = col_combo.currentText()
                if current and current in cols:
                    preferred = current
                else:
                    preferred = self._preferred_column_for_roles(ds, preferred_roles)
            except KeyError:
                pass
        self._set_combo_items(col_combo, cols, preferred)

    @staticmethod
    def _preferred_column_for_roles(dataset: Dataset, roles: tuple[str, ...]) -> str | None:
        """Return the first column tagged with any preferred role."""
        if not roles:
            return None
        wanted = set(roles)
        for column in dataset.frame.columns:
            column_name = str(column)
            metadata = dataset.column_metadata.get(column_name)
            if metadata is not None and metadata.role in wanted:
                return column_name
        return None

    @staticmethod
    def _set_combo_items(combo: QComboBox, items: list[str], preferred: str | None = None) -> None:
        """Replace combo items while preserving a preferred/current value."""
        cur = preferred or combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if cur and cur in items:
            combo.setCurrentText(cur)
        combo.blockSignals(False)

    def _set_controls_enabled(self, has_data: bool) -> None:
        """Enable or disable plot controls based on data and selection state."""
        plot_type = str(self._plot_type_combo.currentData() or "line")
        if plot_type in {"box", "violin"}:
            can_add = has_data and bool(self._selected_distribution_columns())
        elif plot_type == "histogram":
            can_add = has_data and self._y_column_combo.count() > 0
        elif plot_type in _SURFACE_PLOT_TYPES:
            can_add = (
                has_data
                and self._x_column_combo.count() > 0
                and self._y_column_combo.count() > 0
                and self._z_column_combo.count() > 0
                and (
                    plot_type not in _SPECTRAL_PLOT_TYPES
                    or self._spectral_column_combo.count() > 0
                )
            )
        else:
            can_add = has_data and self._x_column_combo.count() > 0 and self._y_column_combo.count() > 0
        selected_row = self._selected_series_row()
        self._commit_series_button.setEnabled(
            can_add and (selected_row is None or self._series_editor_dirty)
        )
        self._new_series_button.setEnabled(has_data)
        self._discard_series_edits_button.setEnabled(
            selected_row is not None and self._series_editor_dirty
        )
        self._remove_series_button.setEnabled(bool(self._series_list.selectedItems()))
        self._clear_series_button.setEnabled(bool(self._plot_series))
        self._render_button.setEnabled(bool(self._plot_series))
        locator_compatible = any(series.plot_type not in _COMPOSITION_PLOT_TYPES for series in self._plot_series)
        self._add_locator_button.setEnabled(locator_compatible)
        self._remove_locator_button.setEnabled(bool(self._locator_list.selectedItems()))
        self._clear_locators_button.setEnabled(bool(self._plot_locators))

    def _toggle_plot_options(self) -> None:
        """Toggle the plot options panel from the Plot tab header."""
        self.set_plot_options_visible(self._plot_options_scroll.isHidden())

    def set_plot_options_visible(self, visible: bool) -> None:
        """Show or hide the plot options panel."""
        self._plot_options_scroll.setVisible(visible)
        if self._external_options:
            self._toggle_options_button.setText("Hide Inspector" if visible else "Show Inspector")
        else:
            self._toggle_options_button.setText("Hide Options" if visible else "Show Options")
        if self._plot_splitter is None:
            pass
        elif visible:
            self._plot_splitter.setSizes([460, 760])
        else:
            self._plot_splitter.setSizes([0, 1])
        self.options_visibility_changed.emit(visible)

    def plot_options_visible(self) -> bool:
        """Return whether the plot options panel is currently visible."""
        return self._plot_options_scroll.isVisible()

    def reset_view_to_default(self) -> None:
        """Restore plot-panel visibility and splitter sizing."""
        self.set_plot_options_visible(True)

    def _refresh_series_list(self) -> None:
        """Rebuild the queued-series list from current series state."""
        self._series_editor_dirty = False
        self._editing_series_row = None
        self._series_list.clear()
        for series in self._plot_series:
            self._series_list.addItem(self._series_text(series))

    def _select_first_series_for_editing(self) -> None:
        """Select and load the first queued series into edit controls."""
        if not self._plot_series:
            return

        self._series_list.setCurrentRow(0)
        self._load_series_controls(self._plot_series[0])
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    def _plot_series_from_state(self, state: dict[str, object]) -> PlotSeries:
        """Deserialize one saved series dictionary into a PlotSeries."""
        clean_state = {key: value for key, value in state.items() if key in _PLOT_SERIES_FIELDS}
        columns = clean_state.get("distribution_columns", ())
        if isinstance(columns, str):
            clean_state["distribution_columns"] = (columns,)
        elif isinstance(columns, (list, tuple)):
            clean_state["distribution_columns"] = tuple(str(column) for column in columns)
        else:
            clean_state["distribution_columns"] = ()
        clean_state["z_dataset"] = str(clean_state.get("z_dataset", "") or "")
        clean_state["z_column"] = str(clean_state.get("z_column", "") or "")
        clean_state["spectral_column"] = str(
            clean_state.get("spectral_column", "") or ""
        )
        try:
            clean_state["spectral_center"] = float(
                clean_state.get("spectral_center", 0.0)
            )
        except (TypeError, ValueError):
            clean_state["spectral_center"] = 0.0
        spectral_sampling = str(
            clean_state.get("spectral_sampling", "nearest") or "nearest"
        )
        clean_state["spectral_sampling"] = (
            spectral_sampling if spectral_sampling in _SPECTRAL_SAMPLING_LABELS else "nearest"
        )
        clean_state["interpolation_method"] = str(
            clean_state.get("interpolation_method", "linear") or "linear"
        )
        color_map = str(clean_state.get("color_map", "viridis") or "viridis")
        clean_state["color_map"] = (
            color_map if color_map in _COLOR_MAP_LABELS else "viridis"
        )
        clean_state["colorbar_label"] = str(
            clean_state.get("colorbar_label", "") or ""
        )
        clean_state["voronoi_shape"] = self._normalized_voronoi_shape(
            str(clean_state.get("voronoi_shape", "circle") or "circle")
        )
        try:
            clean_state["grid_resolution"] = int(clean_state.get("grid_resolution", 120))
        except (TypeError, ValueError):
            clean_state["grid_resolution"] = 120
        return PlotSeries(**clean_state)

    @staticmethod
    def _plot_locator_from_state(state: dict[str, object]) -> PlotLocator:
        """Deserialize one saved locator dictionary into a PlotLocator."""
        clean_state = {key: value for key, value in state.items() if key in _PLOT_LOCATOR_FIELDS}
        for key in ("x_value", "y_value"):
            if clean_state.get(key) in ("", None):
                clean_state[key] = None
            elif key in clean_state:
                try:
                    clean_state[key] = float(clean_state[key])
                except (TypeError, ValueError):
                    clean_state[key] = None
        if clean_state.get("lookup_mode") not in {"x_to_y", "y_to_x", "xy_to_z"}:
            clean_state["lookup_mode"] = "x_to_y"
        return PlotLocator(**clean_state)

    def _apply_plot_settings(self, state: object) -> None:
        """Apply saved axis, legend, range, and figure settings."""
        settings = PlotSettings.from_state(state)
        self._preview_timer.stop()
        self._loading_plot_settings = True
        try:
            self._title_edit.setText(settings.title)
            self._x_label_edit.setText(settings.x_axis.label)
            self._y_label_edit.setText(settings.left_y_axis.label)
            self._right_y_label_edit.setText(settings.right_y_axis.label)
            self._set_combo_text(self._x_scale_combo, settings.x_axis.scale)
            self._set_combo_text(self._y_scale_combo, settings.left_y_axis.scale)
            self._set_combo_text(self._right_y_scale_combo, settings.right_y_axis.scale)
            self._x_min_edit.setText(settings.x_axis.minimum)
            self._x_max_edit.setText(settings.x_axis.maximum)
            self._y_min_edit.setText(settings.left_y_axis.minimum)
            self._y_max_edit.setText(settings.left_y_axis.maximum)
            self._right_y_min_edit.setText(settings.right_y_axis.minimum)
            self._right_y_max_edit.setText(settings.right_y_axis.maximum)
            self._x_label_size_spin.setValue(settings.x_axis.label_font_size)
            self._x_tick_size_spin.setValue(settings.x_axis.tick_font_size)
            self._y_label_size_spin.setValue(settings.left_y_axis.label_font_size)
            self._y_tick_size_spin.setValue(settings.left_y_axis.tick_font_size)
            self._right_y_label_size_spin.setValue(
                settings.right_y_axis.label_font_size
            )
            self._right_y_tick_size_spin.setValue(
                settings.right_y_axis.tick_font_size
            )
            self._grid_checkbox.setChecked(settings.grid_enabled)
            self._legend_checkbox.setChecked(settings.legend.enabled)
            self._set_combo_data(self._legend_pos_combo, settings.legend.location)
            self._legend_font_size_spin.setValue(settings.legend.font_size)
            self._legend_title_edit.setText(settings.legend.title)
            self._legend_title_size_spin.setValue(settings.legend.title_font_size)
            self._legend_columns_spin.setValue(settings.legend.columns)
            self._legend_frame_checkbox.setChecked(settings.legend.frame_enabled)
            self._legend_frame_alpha_spin.setValue(settings.legend.frame_alpha)
            self._legend_marker_scale_spin.setValue(settings.legend.marker_scale)
            self._legend_handle_length_spin.setValue(settings.legend.handle_length)
            self._legend_include_locators_checkbox.setChecked(
                settings.legend.include_locators
            )
            self._legend_include_bands_checkbox.setChecked(
                settings.legend.include_confidence_bands
            )
            self._set_combo_data(self._export_size_mode_combo, settings.figure.size_mode)
            self._width_spin.setValue(settings.figure.width)
            self._height_spin.setValue(settings.figure.height)
            self._set_combo_data(self._style_preset_combo, settings.style.preset)
            self._set_combo_data(self._style_cycle_combo, settings.style.cycle)
            self._style_latex_checkbox.setChecked(settings.style.use_latex)
            self._style_custom_edit.setText(settings.style.custom)
            self._auto_axis_labels = {"x": "", "y": "", "right_y": ""}
            self._preview_dirty = False
            self._preview_status_label.setText("Preview current")
        finally:
            self._loading_plot_settings = False
        self._update_legend_controls_enabled()
        self._sync_export_size()

    def _settings_from_controls(self) -> PlotSettings:
        """Return typed global settings from the current inspector controls."""
        return PlotSettings(
            title=self._title_edit.text(),
            x_axis=AxisSettings(
                label=self._x_label_edit.text(),
                scale=self._x_scale_combo.currentText(),
                minimum=self._x_min_edit.text(),
                maximum=self._x_max_edit.text(),
                label_font_size=self._x_label_size_spin.value(),
                tick_font_size=self._x_tick_size_spin.value(),
            ),
            left_y_axis=AxisSettings(
                label=self._y_label_edit.text(),
                scale=self._y_scale_combo.currentText(),
                minimum=self._y_min_edit.text(),
                maximum=self._y_max_edit.text(),
                label_font_size=self._y_label_size_spin.value(),
                tick_font_size=self._y_tick_size_spin.value(),
            ),
            right_y_axis=AxisSettings(
                label=self._right_y_label_edit.text(),
                scale=self._right_y_scale_combo.currentText(),
                minimum=self._right_y_min_edit.text(),
                maximum=self._right_y_max_edit.text(),
                label_font_size=self._right_y_label_size_spin.value(),
                tick_font_size=self._right_y_tick_size_spin.value(),
            ),
            grid_enabled=self._grid_checkbox.isChecked(),
            legend=LegendSettings(
                enabled=self._legend_checkbox.isChecked(),
                location=str(self._legend_pos_combo.currentData() or "best"),
                font_size=self._legend_font_size_spin.value(),
                title=self._legend_title_edit.text(),
                title_font_size=self._legend_title_size_spin.value(),
                columns=self._legend_columns_spin.value(),
                frame_enabled=self._legend_frame_checkbox.isChecked(),
                frame_alpha=self._legend_frame_alpha_spin.value(),
                marker_scale=self._legend_marker_scale_spin.value(),
                handle_length=self._legend_handle_length_spin.value(),
                include_locators=self._legend_include_locators_checkbox.isChecked(),
                include_confidence_bands=self._legend_include_bands_checkbox.isChecked(),
            ),
            figure=FigureSettings(
                width=self._width_spin.value(),
                height=self._height_spin.value(),
                size_mode=str(self._export_size_mode_combo.currentData() or "figure"),
            ),
            style=StyleSettings(
                preset=str(self._style_preset_combo.currentData() or ""),
                cycle=str(self._style_cycle_combo.currentData() or ""),
                use_latex=self._style_latex_checkbox.isChecked(),
                custom=self._style_custom_edit.text(),
            ),
        )

    @staticmethod
    def _set_combo_text(combo: QComboBox, value: str) -> None:
        """Set combo selection by display text when present."""
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    # -- series management --------------------------------------------------

    def _commit_series_editor(self) -> None:
        """Add a new series or explicitly update the selected queued series."""
        if self._selected_series_row() is None:
            self._add_series()
        else:
            self._update_selected_series()

    def _start_new_series(self) -> None:
        """Switch the editor to create mode without changing the queued plot."""
        if self._series_editor_dirty:
            QMessageBox.information(
                self,
                "Unapplied Series Edits",
                "Update or revert the selected series before creating another one.",
            )
            return
        self._editing_series_row = None
        self._series_list.clearSelection()
        self._series_label_edit.clear()
        self._update_series_editor_state()
        self._series_label_edit.setFocus()

    def _discard_series_edits(self) -> None:
        """Restore controls from the selected queued series."""
        row = self._selected_series_row()
        if row is None or not 0 <= row < len(self._plot_series):
            return
        self._load_series_controls(self._plot_series[row])
        self._update_series_editor_state()

    def _duplicate_selected_series(self) -> None:
        """Append a copy of the selected committed series and render it."""
        row = self._selected_series_row()
        if row is None or not 0 <= row < len(self._plot_series):
            return
        if self._series_editor_dirty:
            QMessageBox.information(
                self,
                "Unapplied Series Edits",
                "Update or revert the selected series before duplicating it.",
            )
            return
        duplicate = self._plot_series[row]
        self._plot_series.append(duplicate)
        self._series_list.addItem(self._series_text(duplicate))
        self._series_list.setCurrentRow(len(self._plot_series) - 1)
        self._refresh_locator_series_combo()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot()

    def _show_series_context_menu(self, pos) -> None:
        """Show common queued-series operations at the pointer."""
        item = self._series_list.itemAt(pos)
        if item is not None:
            target_row = self._series_list.row(item)
            self._series_list.setCurrentRow(target_row)
            if self._selected_series_row() != target_row:
                return

        menu, actions = self._build_series_context_menu()
        action = menu.exec(self._series_list.mapToGlobal(pos))
        if action == actions["new"]:
            self._start_new_series()
        elif action == actions["update"]:
            self._update_selected_series()
        elif action == actions["revert"]:
            self._discard_series_edits()
        elif action == actions["duplicate"]:
            self._duplicate_selected_series()
        elif action == actions["remove"]:
            self._remove_selected_series()
        elif action == actions["clear"]:
            self._clear_series()

    def _build_series_context_menu(self) -> tuple[QMenu, dict[str, object]]:
        """Build the queued-series menu and return its named actions."""
        has_selection = self._selected_series_row() is not None
        menu = QMenu(self)
        new_action = menu.addAction("New Series")
        new_action.setEnabled(not self._series_editor_dirty)
        update_action = menu.addAction("Update Series")
        update_action.setEnabled(has_selection and self._series_editor_dirty)
        revert_action = menu.addAction("Revert Edits")
        revert_action.setEnabled(has_selection and self._series_editor_dirty)
        menu.addSeparator()
        duplicate_action = menu.addAction("Duplicate Series")
        duplicate_action.setEnabled(has_selection and not self._series_editor_dirty)
        remove_action = menu.addAction("Remove Series")
        remove_action.setEnabled(has_selection)
        clear_action = menu.addAction("Clear All Series")
        clear_action.setEnabled(bool(self._plot_series))
        return menu, {
            "new": new_action,
            "update": update_action,
            "revert": revert_action,
            "duplicate": duplicate_action,
            "remove": remove_action,
            "clear": clear_action,
        }

    def _show_locator_context_menu(self, pos) -> None:
        """Show common locator operations at the pointer."""
        item = self._locator_list.itemAt(pos)
        if item is not None:
            self._locator_list.setCurrentItem(item)

        menu, actions = self._build_locator_context_menu()
        action = menu.exec(self._locator_list.mapToGlobal(pos))
        if action == actions["add"]:
            self._add_locator()
        elif action == actions["remove"]:
            self._remove_selected_locator()
        elif action == actions["clear"]:
            self._clear_locators()

    def _build_locator_context_menu(self) -> tuple[QMenu, dict[str, object]]:
        """Build the locator menu and return its named actions."""
        has_selection = bool(self._locator_list.selectedItems())
        menu = QMenu(self)
        add_action = menu.addAction("Add Locator")
        add_action.setEnabled(
            any(
                series.plot_type not in _COMPOSITION_PLOT_TYPES
                for series in self._plot_series
            )
        )
        remove_action = menu.addAction("Remove Locator")
        remove_action.setEnabled(has_selection)
        clear_action = menu.addAction("Clear All Locators")
        clear_action.setEnabled(bool(self._plot_locators))
        return menu, {
            "add": add_action,
            "remove": remove_action,
            "clear": clear_action,
        }

    def _update_series_editor_state(self) -> None:
        """Refresh create/edit mode, dirty feedback, and contextual actions."""
        row = self._selected_series_row()
        if row is None or not 0 <= row < len(self._plot_series):
            self._series_editor_dirty = False
            self._commit_series_button.setText("Add Series")
            self._series_editor_status_label.setText(
                "New series - choose the mapping, then click Add Series"
            )
        else:
            self._series_editor_dirty = (
                self._series_from_controls() != self._plot_series[row]
            )
            self._commit_series_button.setText("Update Series")
            if self._series_editor_dirty:
                self._series_editor_status_label.setText(
                    f"Series {row + 1} has unapplied edits"
                )
            else:
                self._series_editor_status_label.setText(
                    f"Editing queued series {row + 1}"
                )
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    def _add_series(self) -> None:
        """Append a series from the current controls and render the plot."""
        plot_type = str(self._plot_type_combo.currentData() or "line")
        if plot_type in {"box", "violin"} and not self._selected_distribution_columns():
            QMessageBox.information(self, "Add Series", "Select one or more columns for the distribution plot.")
            return
        if plot_type in _SURFACE_PLOT_TYPES and (
            self._x_column_combo.count() == 0
            or self._y_column_combo.count() == 0
            or self._z_column_combo.count() == 0
            or (
                plot_type in _SPECTRAL_PLOT_TYPES
                and self._spectral_column_combo.count() == 0
            )
        ):
            QMessageBox.information(
                self,
                "Add Series",
                (
                    "Choose X, Y, Raman shift/frequency, and intensity columns "
                    "before adding a spectra plot."
                    if plot_type in _SPECTRAL_PLOT_TYPES
                    else "Choose X, Y, and Z columns before adding a 2D map."
                ),
            )
            return
        non_xy_types = {"box", "violin", "histogram"} | _SURFACE_PLOT_TYPES
        if plot_type not in non_xy_types and (
            self._x_column_combo.count() == 0 or self._y_column_combo.count() == 0
        ):
            QMessageBox.information(self, "Add Series", "Import or create a dataset before adding a series.")
            return
        series = self._series_from_controls()
        self._plot_series.append(series)
        self._series_list.addItem(self._series_text(series))
        self._series_list.setCurrentRow(len(self._plot_series) - 1)
        self._refresh_locator_series_combo()
        self._series_editor_dirty = False
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot()

    def _series_from_controls(self) -> PlotSeries:
        """Create a PlotSeries from current series control values."""
        line_style_data = self._line_style_combo.currentData()
        plot_type = str(self._plot_type_combo.currentData() or "line")
        distribution_columns = tuple(self._selected_distribution_columns())
        y_dataset = self._y_dataset_combo.currentText()
        y_column = self._y_column_combo.currentText()
        z_dataset = self._z_dataset_combo.currentText()
        z_column = self._z_column_combo.currentText()
        if plot_type in {"box", "violin"}:
            y_column = distribution_columns[0] if distribution_columns else y_column
        return PlotSeries(
            x_dataset=y_dataset if plot_type in {"box", "violin"} else self._x_dataset_combo.currentText(),
            x_column="" if plot_type in {"box", "violin"} else self._x_column_combo.currentText(),
            x_err_column=self._x_err_column_combo.currentText() if plot_type == "errorbar" else "",
            y_dataset=y_dataset,
            y_column=y_column,
            z_dataset=z_dataset if plot_type in _SURFACE_PLOT_TYPES else "",
            z_column=z_column if plot_type in _SURFACE_PLOT_TYPES else "",
            y_err_column=self._y_err_column_combo.currentText() if plot_type == "errorbar" else "",
            plot_type=plot_type,
            color=str(self._color_combo.currentData() or ""),
            line_style=str(line_style_data) if line_style_data is not None else "-",
            marker=str(self._marker_combo.currentData() or ""),
            y_axis=(
                "left"
                if plot_type in ({"box", "violin"} | _SURFACE_PLOT_TYPES | _COMPOSITION_PLOT_TYPES)
                else str(self._y_axis_combo.currentData() or "left")
            ),
            custom_label=self._series_label_edit.text().strip(),
            show_in_legend=self._series_legend_checkbox.isChecked(),
            line_width=self._line_width_spin.value(),
            marker_size=self._marker_size_spin.value(),
            fill_alpha=self._fill_alpha_spin.value(),
            bar_width=self._bar_width_spin.value(),
            histogram_bins=self._histogram_bins_spin.value(),
            histogram_density=self._histogram_density_checkbox.isChecked(),
            histogram_cumulative=self._histogram_cumulative_checkbox.isChecked(),
            distribution_columns=distribution_columns,
            distribution_show_mean=self._distribution_mean_checkbox.isChecked(),
            distribution_show_median=self._distribution_median_checkbox.isChecked(),
            distribution_show_outliers=self._distribution_outliers_checkbox.isChecked(),
            interpolation_method=str(self._interpolation_method_combo.currentData() or "linear"),
            grid_resolution=self._surface_resolution_spin.value(),
            color_map=(
                str(self._color_map_combo.currentData() or "viridis")
                if plot_type in _SURFACE_PLOT_TYPES
                else "viridis"
            ),
            colorbar_label=(
                self._colorbar_label_edit.text().strip()
                if plot_type in _SURFACE_PLOT_TYPES
                else ""
            ),
            spectral_column=(
                self._spectral_column_combo.currentText()
                if plot_type in _SPECTRAL_PLOT_TYPES
                else ""
            ),
            spectral_center=(
                self._spectral_center_spin.value()
                if plot_type in _SPECTRAL_PLOT_TYPES
                else 0.0
            ),
            spectral_sampling=(
                str(self._spectral_sampling_combo.currentData() or "nearest")
                if plot_type in _SPECTRAL_PLOT_TYPES
                else "nearest"
            ),
            voronoi_shape=str(self._voronoi_shape_combo.currentData() or "circle"),
        )

    def _update_selected_series(self) -> None:
        """Replace the selected queued series from current controls."""
        row = self._selected_series_row()
        if row is None:
            QMessageBox.information(self, "Update Series", "Select a queued series before updating it.")
            return

        series = self._series_from_controls()
        self._plot_series[row] = series
        self._series_list.item(row).setText(self._series_text(series))
        self._refresh_locator_series_combo()
        self._series_editor_dirty = False
        self._update_series_editor_state()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot()

    def _selected_series_row(self) -> int | None:
        """Return the selected queued-series row, if any."""
        rows = sorted({index.row() for index in self._series_list.selectedIndexes()})
        return rows[0] if rows else None

    def _handle_series_selection_changed(self) -> None:
        """Load selected queued series details into the edit controls."""
        row = self._selected_series_row()
        if (
            self._series_editor_dirty
            and self._editing_series_row is not None
            and row != self._editing_series_row
        ):
            self._series_list.blockSignals(True)
            self._series_list.setCurrentRow(self._editing_series_row)
            self._series_list.blockSignals(False)
            QMessageBox.information(
                self,
                "Unapplied Series Edits",
                "Click Update Series or Revert Edits before selecting another series.",
            )
            return
        self._editing_series_row = row
        if row is not None and 0 <= row < len(self._plot_series):
            self._load_series_controls(self._plot_series[row])
        self._update_series_editor_state()

    def _load_series_controls(self, series: PlotSeries) -> None:
        """Populate series edit controls from a PlotSeries."""
        self._loading_series_controls = True
        self._x_dataset_combo.setCurrentText(series.x_dataset)
        self._update_column_combo(self._x_dataset_combo, self._x_column_combo)
        self._update_error_column_combo(self._x_dataset_combo, self._x_err_column_combo)
        self._x_column_combo.setCurrentText(series.x_column)
        self._x_err_column_combo.setCurrentText(series.x_err_column)
        
        self._y_dataset_combo.setCurrentText(series.y_dataset)
        self._update_column_combo(self._y_dataset_combo, self._y_column_combo)
        self._update_error_column_combo(self._y_dataset_combo, self._y_err_column_combo)
        self._y_column_combo.setCurrentText(series.y_column)
        self._y_err_column_combo.setCurrentText(series.y_err_column)
        self._z_dataset_combo.setCurrentText(series.z_dataset or series.y_dataset)
        self._update_column_combo(self._z_dataset_combo, self._z_column_combo)
        self._z_column_combo.setCurrentText(series.z_column)
        if series.plot_type in _SPECTRAL_PLOT_TYPES:
            self._spectral_dataset_combo.setCurrentText(
                series.z_dataset or series.y_dataset
            )
            self._update_spectral_column_combos()
            self._x_column_combo.setCurrentText(series.x_column)
            self._y_column_combo.setCurrentText(series.y_column)
            self._z_column_combo.setCurrentText(series.z_column)
            self._spectral_column_combo.setCurrentText(series.spectral_column)
            self._update_spectral_center_range()
            self._spectral_center_spin.setValue(series.spectral_center)
            self._set_combo_data(
                self._spectral_sampling_combo,
                series.spectral_sampling,
            )
        self._set_distribution_column_selection(
            list(series.distribution_columns) or ([series.y_column] if series.plot_type in {"box", "violin"} else [])
        )
        family_key = _PLOT_TYPE_TO_FAMILY.get(series.plot_type, "xy")
        self._set_combo_data(self._plot_family_combo, family_key)
        self._refresh_plot_type_combo(series.plot_type)
        self._set_combo_data(self._plot_type_combo, series.plot_type)
        self._set_combo_data(self._y_axis_combo, series.y_axis)
        self._series_label_edit.setText(series.custom_label)
        self._colorbar_label_edit.setText(series.colorbar_label)
        self._series_legend_checkbox.setChecked(series.show_in_legend)
        self._set_combo_data(self._line_style_combo, series.line_style)
        self._set_combo_data_or_add(self._marker_combo, series.marker, "Custom symbol")
        self._set_combo_data_or_add(self._color_combo, series.color, "Custom colour")
        self._line_width_spin.setValue(series.line_width)
        self._marker_size_spin.setValue(series.marker_size)
        self._fill_alpha_spin.setValue(series.fill_alpha)
        self._bar_width_spin.setValue(series.bar_width)
        self._histogram_bins_spin.setValue(series.histogram_bins)
        self._histogram_density_checkbox.setChecked(series.histogram_density)
        self._histogram_cumulative_checkbox.setChecked(series.histogram_cumulative)
        self._distribution_mean_checkbox.setChecked(series.distribution_show_mean)
        self._distribution_median_checkbox.setChecked(series.distribution_show_median)
        self._distribution_outliers_checkbox.setChecked(series.distribution_show_outliers)
        self._set_combo_data(self._interpolation_method_combo, series.interpolation_method)
        self._surface_resolution_spin.setValue(series.grid_resolution)
        self._set_combo_data(self._color_map_combo, series.color_map)
        self._set_combo_data(
            self._voronoi_shape_combo,
            self._normalized_voronoi_shape(series.voronoi_shape),
        )
        self._update_plot_type_option_visibility()
        self._loading_series_controls = False

    def _selected_distribution_columns(self) -> list[str]:
        """Return selected distribution columns from the multi-select list."""
        return [item.text() for item in self._distribution_columns_list.selectedItems()]

    def _set_distribution_column_selection(self, columns: list[str]) -> None:
        """Select distribution columns by name when they are present."""
        wanted = set(columns)
        self._distribution_columns_list.blockSignals(True)
        for row in range(self._distribution_columns_list.count()):
            item = self._distribution_columns_list.item(row)
            item.setSelected(item.text() in wanted)
        self._distribution_columns_list.blockSignals(False)
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        """Set combo selection by item data when present."""
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _set_combo_data_or_add(combo: QComboBox, value: str, label: str) -> None:
        """Select item data, adding a readable entry for a custom value when needed."""
        index = combo.findData(value)
        if index < 0 and value:
            combo.addItem(f"{label} ({value})", value)
            index = combo.count() - 1
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _normalized_voronoi_shape(shape: str) -> str:
        """Return the UI-supported Voronoi container shape key."""
        key = str(shape or "circle").strip().lower()
        if key in {"rect", "rectangle", "rectangular"}:
            return "rectangle"
        if key in {"polygon", "polygonal", "poly", "hexagon", "hexagonal"}:
            return "polygon"
        return "circle"

    def _apply_plot_type_defaults(self) -> None:
        """Apply practical line/marker defaults when the user changes plot type."""
        plot_type = str(self._plot_type_combo.currentData() or "line")
        plot_type_info = PLOT_TYPES.get(plot_type)
        self._plot_type_combo.setToolTip(
            plot_type_info.description if plot_type_info is not None else ""
        )
        self._update_plot_type_option_visibility()
        if plot_type == "scatter":
            self._set_combo_data(self._line_style_combo, "")
            self._set_combo_data(self._marker_combo, "o")
        elif plot_type == "line_marker":
            self._set_combo_data(self._line_style_combo, "-")
            self._set_combo_data(self._marker_combo, "o")
        elif plot_type == "errorbar":
            self._set_combo_data(self._line_style_combo, "-")
            self._set_combo_data(self._marker_combo, "o")
        elif plot_type in ({"bar", "barh"} | _COMPOSITION_PLOT_TYPES):
            self._set_combo_data(self._line_style_combo, "")
            self._set_combo_data(self._marker_combo, "")
        elif plot_type == "area":
            self._set_combo_data(self._line_style_combo, "-")
            self._set_combo_data(self._marker_combo, "")
        elif plot_type == "histogram":
            self._set_combo_data(self._line_style_combo, "")
            self._set_combo_data(self._marker_combo, "")
        elif plot_type in {"box", "violin"}:
            self._set_combo_data(self._line_style_combo, "")
            self._set_combo_data(self._marker_combo, "")
            if not self._selected_distribution_columns():
                self._set_distribution_column_selection([self._y_column_combo.currentText()])
        elif plot_type in _SURFACE_PLOT_TYPES:
            self._set_combo_data(self._line_style_combo, "")
            self._set_combo_data(self._marker_combo, "")
        else:
            self._set_combo_data(self._line_style_combo, "-")
            self._set_combo_data(self._marker_combo, "")

    def _update_plot_type_option_visibility(self) -> None:
        """Show only the option rows relevant to the selected plot type."""
        plot_type = str(self._plot_type_combo.currentData() or "line")
        self._set_series_row_label("line_width", "Line width")
        x_y_types = {
            "line",
            "scatter",
            "line_marker",
            "errorbar",
            "bar",
            "barh",
            "area",
        } | _COMPOSITION_PLOT_TYPES
        line_types = {"line", "line_marker", "errorbar", "area"}
        marker_types = {"scatter", "line_marker", "errorbar"}
        distribution_types = {"box", "violin"}
        coordinate_types = x_y_types | _SURFACE_PLOT_TYPES
        is_spectral = plot_type in _SPECTRAL_PLOT_TYPES

        self._set_series_row_visible("spectral_dataset", is_spectral)
        self._set_series_row_visible("x_dataset", plot_type in coordinate_types and not is_spectral)
        self._set_series_row_visible("x_column", plot_type in coordinate_types)
        self._set_series_row_visible("x_error", plot_type == "errorbar")
        self._set_series_row_visible("y_error", plot_type == "errorbar")
        self._set_series_row_visible("y_dataset", not is_spectral)
        self._set_series_row_visible("y_column", plot_type not in distribution_types)
        self._set_series_row_visible("z_dataset", plot_type in _SURFACE_PLOT_TYPES and not is_spectral)
        self._set_series_row_visible("z_column", plot_type in _SURFACE_PLOT_TYPES)
        self._set_series_row_visible("spectral_column", is_spectral)
        self._set_series_row_visible("spectral_center", is_spectral)
        self._set_series_row_visible("spectral_sampling", is_spectral)
        self._set_series_row_visible("colorbar_label", plot_type in _SURFACE_PLOT_TYPES)
        self._set_series_row_visible("distribution_columns", plot_type in distribution_types)
        self._set_series_row_visible("y_axis", plot_type in {"line", "scatter", "line_marker", "errorbar", "bar", "area"})
        self._set_series_row_visible("line", plot_type in line_types)
        self._set_series_row_visible("line_width", plot_type in (line_types | {"violin"}))
        self._set_series_row_visible("marker", plot_type in marker_types)
        self._set_series_row_visible("marker_size", plot_type in marker_types)
        self._set_series_row_visible(
            "color",
            plot_type not in (_SURFACE_PLOT_TYPES | _COMPOSITION_PLOT_TYPES),
        )
        self._set_series_row_visible(
            "show_in_legend",
            plot_type not in (_SURFACE_PLOT_TYPES | _COMPOSITION_PLOT_TYPES),
        )
        self._set_series_row_visible("bar_options", plot_type in {"bar", "barh"})
        self._set_series_row_visible(
            "fill_options",
            plot_type in ({"area", "histogram", "bar", "barh"} | distribution_types),
        )
        self._set_series_row_visible("histogram_options", plot_type == "histogram")
        self._set_series_row_visible("distribution_options", plot_type in distribution_types)
        self._set_series_row_visible("color_map", plot_type in _SURFACE_PLOT_TYPES)
        self._set_series_row_visible("surface_options", plot_type in _SURFACE_PLOT_TYPES)
        self._set_series_row_visible("voronoi_options", plot_type == "voronoi")

        if plot_type == "histogram":
            self._set_series_row_label("y_dataset", "Value dataset")
            self._set_series_row_label("y_column", "Value column")
        elif plot_type in distribution_types:
            self._set_series_row_label("y_dataset", "Data dataset")
            self._set_series_row_label("distribution_columns", "Value columns")
            self._set_series_row_label(
                "line_width",
                "Statistic line width" if plot_type == "violin" else "Line width",
            )
        elif is_spectral:
            self._set_series_row_label("x_column", "X coordinate")
            self._set_series_row_label("y_column", "Y coordinate")
            self._set_series_row_label("z_column", "Intensity")
        elif plot_type in _SURFACE_PLOT_TYPES:
            self._set_series_row_label("x_dataset", "X dataset")
            self._set_series_row_label("x_column", "X coordinate")
            self._set_series_row_label("y_dataset", "Y dataset")
            self._set_series_row_label("y_column", "Y coordinate")
            self._set_series_row_label("z_dataset", "Z dataset")
            self._set_series_row_label("z_column", "Z value")
        elif plot_type == "barh":
            self._set_series_row_label("x_dataset", "Label/position dataset")
            self._set_series_row_label("x_column", "Label/position column")
            self._set_series_row_label("y_dataset", "Value dataset")
            self._set_series_row_label("y_column", "Value column")
        elif plot_type == "bar":
            self._set_series_row_label("x_dataset", "X/label dataset")
            self._set_series_row_label("x_column", "X/label column")
            self._set_series_row_label("y_dataset", "Y/value dataset")
            self._set_series_row_label("y_column", "Y/value column")
        elif plot_type in _COMPOSITION_PLOT_TYPES:
            self._set_series_row_label("x_dataset", "Label dataset")
            self._set_series_row_label("x_column", "Label column")
            self._set_series_row_label("y_dataset", "Value dataset")
            self._set_series_row_label("y_column", "Value column")
        else:
            self._set_series_row_label("x_dataset", "X dataset")
            self._set_series_row_label("x_column", "X column")
            self._set_series_row_label("y_dataset", "Y dataset")
            self._set_series_row_label("y_column", "Y column")

    def _set_series_row_visible(self, key: str, visible: bool) -> None:
        """Show or hide one remembered Series form row."""
        row = self._series_rows.get(key)
        if row is None:
            return
        label, field = row
        if label is not None:
            label.setVisible(visible)
        field.setVisible(visible)

    def _set_series_row_label(self, key: str, text: str) -> None:
        """Update the label text for one remembered Series form row."""
        row = self._series_rows.get(key)
        if row is None:
            return
        label, _field = row
        if isinstance(label, QLabel):
            label.setText(text)

    def _remove_selected_series(self) -> None:
        """Remove selected series and reindex locators that remain."""
        rows = sorted({i.row() for i in self._series_list.selectedIndexes()}, reverse=True)
        self._series_editor_dirty = False
        self._editing_series_row = None
        for r in rows:
            self._plot_series.pop(r)
            self._series_list.takeItem(r)
        self._reindex_locators_after_removal(rows)
        self._refresh_locator_series_combo()
        self._update_series_editor_state()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _clear_series(self) -> None:
        """Clear all queued series, locators, and rendered plot content."""
        self._series_editor_dirty = False
        self._editing_series_row = None
        self._plot_series.clear()
        self._series_list.clear()
        self._plot_locators.clear()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._plot_canvas.clear_plot()
        self._update_series_editor_state()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self.status_message.emit("Cleared plot series")
        self.plot_rendered.emit()


    # -- locator management -------------------------------------------------

    def _add_locator(self) -> None:
        """Add an interpolation locator for the selected queued series."""
        if not self._plot_series:
            QMessageBox.information(self, "Add Locator", "Add a plotted series before locating data.")
            return
        idx = self._locator_series_combo.currentData()
        if not isinstance(idx, int) or not 0 <= idx < len(self._plot_series):
            QMessageBox.warning(self, "Add Locator", "Choose a valid queued series.")
            return
        is_surface = self._plot_series[idx].plot_type in _SURFACE_PLOT_TYPES
        lookup_mode = "xy_to_z" if is_surface else str(self._locator_mode_combo.currentData() or "x_to_y")
        x_val: float | None = None
        y_val: float | None = None
        if lookup_mode in {"x_to_y", "xy_to_z"}:
            x_val, errs = self._parse_optional_float(self._locator_x_edit.text(), "Locator X value")
            if errs or x_val is None:
                QMessageBox.warning(self, "Add Locator", "\n".join(errs or ["Locator X value is required."]))
                return
        if lookup_mode in {"y_to_x", "xy_to_z"}:
            y_val, y_errs = self._parse_optional_float(
                self._locator_y_edit.text(),
                "Locator Y value",
            )
            if y_errs or y_val is None:
                QMessageBox.warning(
                    self,
                    "Add Locator",
                    "\n".join(y_errs or ["Locator Y value is required."]),
                )
                return
        loc = PlotLocator(
            series_index=idx, x_value=x_val,
            y_value=y_val, lookup_mode=lookup_mode,
            marker=str(self._locator_marker_combo.currentData() or "o"),
            size=self._locator_size_spin.value(),
            color=str(self._locator_color_combo.currentData() or "tab:red"),
        )
        self._plot_locators.append(loc)
        self._locator_list.addItem(self._locator_text(loc))
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot()

    def _remove_selected_locator(self) -> None:
        """Remove selected locators from the current plot definition."""
        rows = sorted({i.row() for i in self._locator_list.selectedIndexes()}, reverse=True)
        for r in rows:
            self._plot_locators.pop(r)
            self._locator_list.takeItem(r)
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _clear_locators(self) -> None:
        """Remove all locators from the current plot definition."""
        self._plot_locators.clear()
        self._locator_list.clear()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _refresh_locator_series_combo(self) -> None:
        """Refresh the locator target-series combo from queued series."""
        cur = self._locator_series_combo.currentData()
        self._locator_series_combo.blockSignals(True)
        self._locator_series_combo.clear()
        for i, s in enumerate(self._plot_series):
            self._locator_series_combo.addItem(f"{i + 1}: {s.label}", i)
        if isinstance(cur, int):
            ci = self._locator_series_combo.findData(cur)
            if ci >= 0:
                self._locator_series_combo.setCurrentIndex(ci)
        self._locator_series_combo.blockSignals(False)
        self._update_locator_mode_controls()

    def _update_locator_mode_controls(self) -> None:
        """Enable the coordinates required by the selected locator lookup mode."""
        index = self._locator_series_combo.currentData()
        is_surface = (
            isinstance(index, int)
            and 0 <= index < len(self._plot_series)
            and self._plot_series[index].plot_type in _SURFACE_PLOT_TYPES
        )
        self._locator_mode_combo.setEnabled(not is_surface)
        mode = "xy_to_z" if is_surface else str(self._locator_mode_combo.currentData() or "x_to_y")
        self._locator_x_edit.setEnabled(mode in {"x_to_y", "xy_to_z"})
        self._locator_y_edit.setEnabled(mode in {"y_to_x", "xy_to_z"})
        self._locator_x_edit.setPlaceholderText("X coordinate" if is_surface else "X value")
        self._locator_y_edit.setPlaceholderText("Y coordinate" if is_surface else "Y value")

    def _reindex_locators_after_removal(self, removed: list[int]) -> None:
        """Drop or shift locators after series rows have been removed."""
        removed_set = set(removed)
        new: list[PlotLocator] = []
        for loc in self._plot_locators:
            if loc.series_index in removed_set:
                continue
            shift = sum(1 for r in removed_set if r < loc.series_index)
            new.append(PlotLocator(
                series_index=loc.series_index - shift,
                x_value=loc.x_value, y_value=loc.y_value, lookup_mode=loc.lookup_mode, marker=loc.marker,
                size=loc.size, color=loc.color,
            ))
        self._plot_locators = new
        self._refresh_locator_list()

    def _refresh_locator_list(self, located: list[LocatedPoint] | None = None) -> None:
        """Refresh locator list text, including computed values when available."""
        by_idx: dict[int, list[LocatedPoint]] = {}
        for point in located or []:
            by_idx.setdefault(point.locator_index, []).append(point)
        self._locator_list.clear()
        for i, loc in enumerate(self._plot_locators):
            self._locator_list.addItem(self._locator_text(loc, by_idx.get(i)))

    # -- axis label prefill -------------------------------------------------

    def _prefill_axis_labels_from_plot_context(self) -> None:
        """Fill blank/auto axis-label fields from metadata-visible plot context."""
        if len(self._plot_series) == 1:
            self._prefill_axis_labels_for_series(self._plot_series[0])
        elif not self._plot_series and self._workspace.dataset_names():
            self._prefill_axis_labels_for_series(self._series_from_controls())

    def _prefill_axis_labels_for_series(
        self,
        series: PlotSeries,
        force: bool = False,
    ) -> None:
        """Fill axis labels from one series without overwriting manual edits."""
        x_label, y_label, right_y_label = self._suggested_axis_labels_for_series(series)
        self._set_axis_label_if_auto("x", x_label, force=force)
        self._set_axis_label_if_auto("y", y_label, force=force)
        self._set_axis_label_if_auto("right_y", right_y_label, force=force)

    def _suggested_axis_labels_for_series(self, series: PlotSeries) -> tuple[str, str, str]:
        """Return X, left-Y, and right-Y axis labels suggested by metadata."""
        x_label = ""
        y_label = ""
        right_y_label = ""

        if series.plot_type == "histogram":
            x_label = self._column_axis_label(series.y_dataset, series.y_column)
            y_label = "Density" if series.histogram_density else "Count"
        elif series.plot_type in {"box", "violin"}:
            x_label = "Column"
            y_label = "Value"
        elif series.plot_type in _SURFACE_PLOT_TYPES:
            x_label = self._column_axis_label(series.x_dataset, series.x_column)
            y_label = self._column_axis_label(series.y_dataset, series.y_column)
        elif series.plot_type in _COMPOSITION_PLOT_TYPES:
            x_label = self._column_axis_label(series.x_dataset, series.x_column)
            y_label = self._column_axis_label(series.y_dataset, series.y_column)
        elif series.plot_type == "barh":
            x_label = self._column_axis_label(series.y_dataset, series.y_column)
            y_label = self._column_axis_label(series.x_dataset, series.x_column)
        else:
            x_label = self._column_axis_label(series.x_dataset, series.x_column)
            if series.y_axis == "right":
                right_y_label = self._column_axis_label(series.y_dataset, series.y_column)
            else:
                y_label = self._column_axis_label(series.y_dataset, series.y_column)

        return x_label, y_label, right_y_label

    def _set_axis_label_text(self, key: str, text: str) -> None:
        """Force an axis-label field and remember it as an automatic label."""
        edit = self._axis_label_edit(key)
        edit.setText(text)
        edit.setPlaceholderText(text)
        self._auto_axis_labels[key] = text.strip()

    def _set_axis_label_if_auto(
        self,
        key: str,
        suggested_text: str,
        force: bool = False,
    ) -> None:
        """Set an axis label only when the field is blank or still auto-filled."""
        edit = self._axis_label_edit(key)
        suggested = suggested_text.strip()
        current = edit.text().strip()
        previous_auto = self._auto_axis_labels.get(key, "")
        edit.setPlaceholderText(suggested)

        if force:
            edit.setText(suggested)
            self._auto_axis_labels[key] = suggested
            return

        if not suggested:
            if previous_auto and current == previous_auto:
                edit.clear()
            self._auto_axis_labels[key] = ""
            return

        if not current or current == previous_auto:
            edit.setText(suggested)
        self._auto_axis_labels[key] = suggested

    def _axis_label_edit(self, key: str) -> QLineEdit:
        """Return the QLineEdit backing an axis label key."""
        if key == "x":
            return self._x_label_edit
        if key == "y":
            return self._y_label_edit
        if key == "right_y":
            return self._right_y_label_edit
        raise KeyError(f"Unknown axis label key: {key}")

    # -- direct canvas editing --------------------------------------------

    def _edit_rendered_plot_element(self, element: str, payload: object = None) -> None:
        """Open the focused editor associated with a double-clicked canvas element."""
        if not self._plot_series:
            return
        if element == "series" and isinstance(payload, int):
            self._edit_series_appearance_from_canvas(payload)
            return
        if element == "colorbar_label" and isinstance(payload, int):
            self._edit_colorbar_label_from_canvas(payload)
            return
        if element == "title":
            self._edit_plot_title_from_canvas()
            return
        if element in {"x_axis", "left_y_axis", "right_y_axis"}:
            self._edit_axis_from_canvas(element)
            return
        if element == "legend_entry" and isinstance(payload, str):
            if self._edit_legend_entry_from_canvas(payload):
                return
        if element in {"legend", "legend_entry"}:
            self._edit_legend_from_canvas()

    def _edit_series_appearance_from_canvas(self, row: int) -> None:
        """Edit one plotted series and synchronize the committed series inspector."""
        if not 0 <= row < len(self._plot_series):
            return
        if self._series_editor_dirty:
            QMessageBox.information(
                self,
                "Unapplied Series Edits",
                "Update or revert the selected series before editing plotted data on the canvas.",
            )
            return
        series = self._plot_series[row]
        family_key = _PLOT_TYPE_TO_FAMILY.get(series.plot_type, "xy")
        plot_types = [
            (plot_type_label(plot_type), plot_type)
            for plot_type in _PLOT_FAMILY_TYPES.get(family_key, _PLOT_FAMILY_TYPES["xy"])
        ]
        dialog = PlotSeriesAppearanceDialog(series, plot_types, self)
        if dialog.exec() != QDialog.Accepted:
            return
        updated = replace(series, **dialog.series_updates())
        self._plot_series[row] = updated
        item = self._series_list.item(row)
        if item is not None:
            item.setText(self._series_text(updated))
        self._series_list.blockSignals(True)
        self._series_list.setCurrentRow(row)
        self._series_list.blockSignals(False)
        self._editing_series_row = row
        self._load_series_controls(updated)
        self._update_series_editor_state()
        self._refresh_locator_series_combo()
        self._render_plot(silent_if_empty=True)
        self.status_message.emit(f"Series '{updated.label}' updated from the canvas")

    def _edit_colorbar_label_from_canvas(self, row: int) -> None:
        """Edit one surface colour-bar label and synchronize its series state."""
        if not 0 <= row < len(self._plot_series):
            return
        if self._series_editor_dirty:
            QMessageBox.information(
                self,
                "Unapplied Series Edits",
                "Update or revert the selected series before editing the colour bar on the canvas.",
            )
            return
        series = self._plot_series[row]
        dialog = PlotTextEditDialog(
            "Edit Colour-Bar Label",
            "Label",
            series.colorbar_label or PlotCanvas.default_colorbar_label(series),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        updated = replace(series, colorbar_label=dialog.text_value().strip())
        self._plot_series[row] = updated
        item = self._series_list.item(row)
        if item is not None:
            item.setText(self._series_text(updated))
        self._series_list.blockSignals(True)
        self._series_list.setCurrentRow(row)
        self._series_list.blockSignals(False)
        self._editing_series_row = row
        self._load_series_controls(updated)
        self._update_series_editor_state()
        self._render_plot(silent_if_empty=True)
        self.status_message.emit("Colour-bar label updated from the canvas")

    def _edit_plot_title_from_canvas(self) -> None:
        """Edit the figure title and immediately synchronize the inspector."""
        dialog = PlotTextEditDialog(
            "Edit Plot Title",
            "Title",
            self._title_edit.text(),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._loading_plot_settings = True
        try:
            self._title_edit.setText(dialog.text_value())
        finally:
            self._loading_plot_settings = False
        self._render_plot(silent_if_empty=True)
        self.status_message.emit("Plot title updated from the canvas")

    def _edit_axis_from_canvas(self, element: str) -> None:
        """Edit one rendered axis and write the result into inspector controls."""
        settings = self._settings_from_controls()
        axis_map = {
            "x_axis": (
                "X",
                settings.x_axis,
                self._x_label_edit,
                self._x_scale_combo,
                self._x_min_edit,
                self._x_max_edit,
                self._x_label_size_spin,
                self._x_tick_size_spin,
                "x",
            ),
            "left_y_axis": (
                "Left Y",
                settings.left_y_axis,
                self._y_label_edit,
                self._y_scale_combo,
                self._y_min_edit,
                self._y_max_edit,
                self._y_label_size_spin,
                self._y_tick_size_spin,
                "y",
            ),
            "right_y_axis": (
                "Right Y",
                settings.right_y_axis,
                self._right_y_label_edit,
                self._right_y_scale_combo,
                self._right_y_min_edit,
                self._right_y_max_edit,
                self._right_y_label_size_spin,
                self._right_y_tick_size_spin,
                "right_y",
            ),
        }
        (
            axis_name,
            current,
            label_edit,
            scale_combo,
            minimum_edit,
            maximum_edit,
            label_size_spin,
            tick_size_spin,
            auto_key,
        ) = axis_map[element]
        dialog = PlotAxisEditDialog(axis_name, current, settings.grid_enabled, self)
        if dialog.exec() != QDialog.Accepted:
            return
        updated = dialog.axis_settings()
        self._loading_plot_settings = True
        try:
            label_edit.setText(updated.label)
            self._set_combo_text(scale_combo, updated.scale)
            minimum_edit.setText(updated.minimum)
            maximum_edit.setText(updated.maximum)
            label_size_spin.setValue(updated.label_font_size)
            tick_size_spin.setValue(updated.tick_font_size)
            self._grid_checkbox.setChecked(dialog.grid_enabled())
            self._auto_axis_labels[auto_key] = ""
        finally:
            self._loading_plot_settings = False
        self._render_plot(silent_if_empty=True)
        self.status_message.emit(f"{axis_name} axis updated from the canvas")

    def _edit_legend_from_canvas(self) -> None:
        """Edit global legend settings and synchronize all inspector controls."""
        dialog = PlotLegendEditDialog(self._settings_from_controls().legend, self)
        if dialog.exec() != QDialog.Accepted:
            return
        settings = dialog.legend_settings()
        self._loading_plot_settings = True
        try:
            self._legend_checkbox.setChecked(settings.enabled)
            self._set_combo_data(self._legend_pos_combo, settings.location)
            self._legend_font_size_spin.setValue(settings.font_size)
            self._legend_title_edit.setText(settings.title)
            self._legend_title_size_spin.setValue(settings.title_font_size)
            self._legend_columns_spin.setValue(settings.columns)
            self._legend_frame_checkbox.setChecked(settings.frame_enabled)
            self._legend_frame_alpha_spin.setValue(settings.frame_alpha)
            self._legend_marker_scale_spin.setValue(settings.marker_scale)
            self._legend_handle_length_spin.setValue(settings.handle_length)
            self._legend_include_locators_checkbox.setChecked(settings.include_locators)
            self._legend_include_bands_checkbox.setChecked(settings.include_confidence_bands)
        finally:
            self._loading_plot_settings = False
        self._update_legend_controls_enabled()
        self._render_plot(silent_if_empty=True)
        self.status_message.emit("Legend settings updated from the canvas")

    def _edit_legend_entry_from_canvas(self, label: str) -> bool:
        """Edit one committed series label; return whether the entry was handled."""
        matching_rows = [
            row
            for row, series in enumerate(self._plot_series)
            if series.label == label
        ]
        if not matching_rows:
            return False
        if self._series_editor_dirty:
            QMessageBox.information(
                self,
                "Unapplied Series Edits",
                "Update or revert the selected series before editing a legend entry on the canvas.",
            )
            return True
        row = matching_rows[0]
        series = self._plot_series[row]
        dialog = PlotLegendEntryEditDialog(series.label, series.show_in_legend, self)
        if dialog.exec() != QDialog.Accepted:
            return True
        updated = replace(
            series,
            custom_label=dialog.entry_label(),
            show_in_legend=dialog.entry_shown(),
        )
        self._plot_series[row] = updated
        item = self._series_list.item(row)
        if item is not None:
            item.setText(self._series_text(updated))
        if self._selected_series_row() == row:
            self._load_series_controls(updated)
            self._update_series_editor_state()
        self._refresh_locator_series_combo()
        self._render_plot(silent_if_empty=True)
        self.status_message.emit(f"Legend entry '{label}' updated from the canvas")
        return True

    # -- rendering ----------------------------------------------------------

    def _render_plot_if_possible(self) -> None:
        """Refresh the visible plot after a style-control change."""
        if self._plot_series:
            self._render_plot(silent_if_empty=True)

    def _render_plot(
        self,
        silent_if_empty: bool = False,
        show_validation_messages: bool = True,
    ) -> None:
        """Render queued series and locators to the Matplotlib canvas."""
        self._preview_timer.stop()
        if not self._plot_series:
            self._plot_canvas.clear_plot()
            self._set_controls_enabled(bool(self._workspace.dataset_names()))
            if not silent_if_empty:
                QMessageBox.information(self, "Plot", "Add at least one series before plotting.")
            return

        self._prefill_axis_labels_from_plot_context()
        x_label = self._x_label_edit.text().strip()
        y_label = self._y_label_edit.text().strip()
        ry_label = self._right_y_label_edit.text().strip()
        if len(self._plot_series) == 1:
            s0 = self._plot_series[0]
            if s0.plot_type == "histogram":
                x_label = x_label or self._column_axis_label(s0.y_dataset, s0.y_column)
                y_label = y_label or ("Density" if s0.histogram_density else "Count")
            elif s0.plot_type in {"box", "violin"}:
                x_label = x_label or "Column"
                y_label = y_label or "Value"
            elif s0.plot_type in _SURFACE_PLOT_TYPES:
                x_label = x_label or self._column_axis_label(s0.x_dataset, s0.x_column)
                y_label = y_label or self._column_axis_label(s0.y_dataset, s0.y_column)
            elif s0.plot_type in _COMPOSITION_PLOT_TYPES:
                x_label = x_label or self._column_axis_label(s0.x_dataset, s0.x_column)
                y_label = y_label or self._column_axis_label(s0.y_dataset, s0.y_column)
            elif s0.plot_type == "barh":
                x_label = x_label or self._column_axis_label(s0.y_dataset, s0.y_column)
                y_label = y_label or self._column_axis_label(s0.x_dataset, s0.x_column)
            else:
                x_label = x_label or self._column_axis_label(s0.x_dataset, s0.x_column)
            non_y_axis_types = (
                {"histogram", "barh", "box", "violin"}
                | _SURFACE_PLOT_TYPES
                | _COMPOSITION_PLOT_TYPES
            )
            if s0.plot_type in non_y_axis_types:
                pass
            elif s0.y_axis == "right":
                ry_label = ry_label or self._column_axis_label(s0.y_dataset, s0.y_column)
            else:
                y_label = y_label or self._column_axis_label(s0.y_dataset, s0.y_column)

        inputs, errors = self._plot_inputs()
        if errors:
            self._preview_dirty = True
            self._preview_status_label.setText("Fix invalid plot settings")
            if show_validation_messages:
                QMessageBox.warning(self, "Plot Settings", "\n".join(errors))
            else:
                self.status_message.emit(errors[0])
            return

        result = self._plot_canvas.plot_series(
            workspace=self._workspace,
            series_list=self._plot_series,
            title=self._title_edit.text().strip(),
            x_label=x_label, y_label=y_label, right_y_label=ry_label,
            **inputs,
        )
        self._refresh_locator_list(result.located_points)

        if result.skipped_messages and result.plotted_count == 0:
            if show_validation_messages:
                QMessageBox.warning(
                    self,
                    "Plot Failed",
                    "\n".join(result.skipped_messages[:5]),
                )
            else:
                self.status_message.emit(result.skipped_messages[0])
        elif result.skipped_messages:
            self.status_message.emit(
                f"Plotted {result.plotted_count} series; skipped {len(result.skipped_messages)}"
            )
        elif result.located_points:
            self.status_message.emit(
                f"Plotted {result.plotted_count} series; located {len(result.located_points)} point(s)"
            )
        else:
            self.status_message.emit(f"Plotted {result.plotted_count} series")

        if result.plotted_count:
            self._preview_dirty = False
            self._preview_status_label.setText("Preview current")
        else:
            self._preview_dirty = True
            self._preview_status_label.setText("Preview failed")
        self.plot_rendered.emit()

    def _column_axis_label(self, dataset_name: str, column_name: str) -> str:
        """Return a plot label using long-name/unit metadata when available."""
        label = column_name
        try:
            dataset = self._workspace.get_dataset(dataset_name)
        except KeyError:
            return label

        metadata = dataset.column_metadata.get(column_name)
        if metadata is None:
            return label
        if metadata.long_name:
            label = metadata.long_name
        if metadata.unit:
            label = f"{label} ({metadata.unit})"
        return label

    # -- label helpers (bug fix: reads from series data, not combo state) ---

    @staticmethod
    def _series_text(series: PlotSeries) -> str:
        """Return readable queued-series text for the list widget."""
        bits = [plot_type_label(series.plot_type)]
        if series.plot_type in {"box", "violin"}:
            column_count = len(series.distribution_columns) or (1 if series.y_column else 0)
            bits.append(f"{column_count} column{'s' if column_count != 1 else ''}")
            if series.distribution_show_mean:
                bits.append("mean")
            if series.distribution_show_median:
                bits.append("median")
            if series.distribution_show_outliers:
                bits.append("outliers")
        elif series.plot_type in _SURFACE_PLOT_TYPES:
            bits.extend([
                f"Z: {series.z_column}",
                _INTERPOLATION_LABELS.get(series.interpolation_method, series.interpolation_method),
                _COLOR_MAP_LABELS.get(series.color_map, series.color_map),
                f"{series.grid_resolution} grid",
            ])
            if series.plot_type in _SPECTRAL_PLOT_TYPES:
                bits.insert(1, f"{series.spectral_column}: {series.spectral_center:g}")
                bits.insert(
                    2,
                    _SPECTRAL_SAMPLING_LABELS.get(
                        series.spectral_sampling,
                        series.spectral_sampling,
                    ),
                )
        elif series.plot_type in _COMPOSITION_PLOT_TYPES:
            bits.extend([
                f"labels: {series.x_column}",
                f"values: {series.y_column}",
            ])
            if series.plot_type == "voronoi":
                shape = _VORONOI_SHAPE_LABELS.get(series.voronoi_shape, series.voronoi_shape)
                bits.append(f"{shape} container")
        else:
            bits.extend([
                _LINE_LABELS.get(series.line_style, series.line_style or "None"),
                _MARKER_LABELS.get(series.marker, series.marker or "None"),
                _COLOR_LABELS.get(series.color, series.color or "Auto"),
                f"{series.y_axis} axis",
            ])
        return f"{series.label} ({', '.join(bits)})"

    def _locator_text(self, loc: PlotLocator, points: list[LocatedPoint] | None = None) -> str:
        """Return locator list text before or after interpolation."""
        label = self._plot_series[loc.series_index].label
        if points:
            pt = points[0]
            if pt.z_value is not None:
                return (
                    f"{label}: x={pt.x_value:g}, y={pt.y_value:g}, "
                    f"z={pt.z_value:g}"
                )
            if loc.lookup_mode == "y_to_x":
                x_text = ", ".join(f"{point.x_value:g}" for point in points)
                return f"{label}: y={pt.y_value:g} -> x={x_text} ({pt.y_axis})"
            return f"{label}: x={pt.x_value:g}, y={pt.y_value:g} ({pt.y_axis})"
        if loc.lookup_mode == "y_to_x" and loc.y_value is not None:
            return f"{label}: y={loc.y_value:g} -> x (pending)"
        if loc.y_value is not None:
            return f"{label}: x={loc.x_value:g}, y={loc.y_value:g} (pending)"
        if loc.x_value is not None:
            return f"{label}: x={loc.x_value:g} (pending)"
        return f"{label}: incomplete locator"

    # -- input parsing ------------------------------------------------------

    def _plot_inputs(self) -> tuple[dict[str, object], list[str]]:
        """Collect validated plot options for PlotCanvas."""
        errors: list[str] = []
        xl, xe = self._parse_range(self._x_min_edit, self._x_max_edit, "X range")
        yl, ye = self._parse_range(self._y_min_edit, self._y_max_edit, "Left Y range")
        rl, re = self._parse_range(self._right_y_min_edit, self._right_y_max_edit, "Right Y range")
        errors.extend(xe); errors.extend(ye); errors.extend(re)
        return (
            {
                "x_scale": self._x_scale_combo.currentText(),
                "y_scale": self._y_scale_combo.currentText(),
                "right_y_scale": self._right_y_scale_combo.currentText(),
                "x_label_font_size": self._x_label_size_spin.value(),
                "x_tick_font_size": self._x_tick_size_spin.value(),
                "y_label_font_size": self._y_label_size_spin.value(),
                "y_tick_font_size": self._y_tick_size_spin.value(),
                "right_y_label_font_size": self._right_y_label_size_spin.value(),
                "right_y_tick_font_size": self._right_y_tick_size_spin.value(),
                "x_limits": xl, "y_limits": yl, "right_y_limits": rl,
                "grid_enabled": self._grid_checkbox.isChecked(),
                "legend_settings": self._settings_from_controls().legend,
                "locators": self._plot_locators,
                "style_names": self._style_names(),
            },
            errors,
        )

    def _style_names(self) -> list[str]:
        """Return Matplotlib/SciencePlots style names for the current plot."""
        names: list[str] = []
        for token in str(self._style_preset_combo.currentData() or "").split(","):
            clean = token.strip()
            if clean:
                names.append(clean)

        cycle = str(self._style_cycle_combo.currentData() or "").strip()
        if cycle:
            names.append(cycle)

        for token in self._style_custom_edit.text().split(","):
            clean = token.strip()
            if clean and clean not in names:
                names.append(clean)

        uses_science_style = any(name == "science" for name in names)
        if uses_science_style and not self._style_latex_checkbox.isChecked() and "no-latex" not in names:
            names.append("no-latex")

        if any(name in _SCIENCEPLOTS_STYLE_NAMES for name in names) and not SCIENCEPLOTS_AVAILABLE:
            self.status_message.emit("SciencePlots is not installed; style rendering may be unavailable.")

        return names

    def _parse_range(
        self, min_edit: QLineEdit, max_edit: QLineEdit, label: str,
    ) -> tuple[tuple[float | None, float | None], list[str]]:
        """Parse and validate one optional min/max range pair."""
        lo, lo_err = self._parse_optional_float(min_edit.text(), f"{label} minimum")
        hi, hi_err = self._parse_optional_float(max_edit.text(), f"{label} maximum")
        errors = lo_err + hi_err
        if lo is not None and hi is not None and lo >= hi:
            errors.append(f"{label}: minimum must be smaller than maximum.")
        return (lo, hi), errors

    @staticmethod
    def _parse_optional_float(text: str, label: str) -> tuple[float | None, list[str]]:
        """Parse optional float text and return validation errors."""
        stripped = text.strip()
        if not stripped:
            return None, []
        try:
            return float(stripped), []
        except ValueError:
            return None, [f"{label} must be numeric."]
