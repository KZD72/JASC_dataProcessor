"""Plot tab widget extracted from main_window for modularity."""

from __future__ import annotations

from dataclasses import asdict, fields

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
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
from models.plot_types import PLOT_TYPES, plot_type_label
from ui.plot_canvas import SCIENCEPLOTS_AVAILABLE, LocatedPoint, PlotCanvas, PlotLocator, PlotSeries

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
_SURFACE_PLOT_TYPES = {"heatmap", "contour", "contourf"}
_INTERPOLATION_LABELS: dict[str, str] = {
    "linear": "Linear",
    "cubic_spline": "Cubic spline",
    "piecewise_cubic": "Piecewise cubic",
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
        self._plot_canvas = PlotCanvas()
        self._build_ui()

    # -- public API for MainWindow -----------------------------------------

    def set_workspace(self, workspace: Workspace) -> None:
        """Attach a new workspace and clear plot state tied to the old one."""
        self._workspace = workspace
        self.clear_plot_state()
        self.refresh_controls()

    def clear_plot_state(self) -> None:
        """Clear queued series, locators, and the current plot canvas."""
        self._plot_series.clear()
        self._plot_locators.clear()
        self._series_list.clear()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._plot_canvas.clear_plot()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self.plot_rendered.emit()

    def refresh_controls(self, selected_dataset: str | None = None) -> None:
        """Repopulate dataset/column combos from the workspace."""
        names = self._workspace.dataset_names()
        self._set_combo_items(self._x_dataset_combo, names, selected_dataset)
        self._set_combo_items(self._y_dataset_combo, names, selected_dataset)
        self._set_combo_items(self._z_dataset_combo, names, selected_dataset)
        self._update_column_combo(self._x_dataset_combo, self._x_column_combo)
        self._update_error_column_combo(self._x_dataset_combo, self._x_err_column_combo)
        self._update_column_combo(self._y_dataset_combo, self._y_column_combo)
        self._update_error_column_combo(self._y_dataset_combo, self._y_err_column_combo)
        self._update_column_combo(self._z_dataset_combo, self._z_column_combo)
        self._update_distribution_columns_list()
        self._set_controls_enabled(bool(names))

    def has_plot_series(self) -> bool:
        """Return whether the plot tab has a restorable plot definition."""
        return bool(self._plot_series)

    def set_active_plot_name(self, name: str | None) -> None:
        """Update the plot header with the active saved plot name."""
        self._active_plot_label.setText(name or "Unsaved plot")

    def set_plot_actions_enabled(self, can_save: bool, can_load: bool, can_remove: bool) -> None:
        """Set enabled state for plot-level header actions."""
        self._save_plot_button.setEnabled(can_save)
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
            "version": 1,
            "series": [asdict(series) for series in self._plot_series],
            "locators": [asdict(locator) for locator in self._plot_locators],
            "settings": {
                "title": self._title_edit.text(),
                "x_label": self._x_label_edit.text(),
                "y_label": self._y_label_edit.text(),
                "right_y_label": self._right_y_label_edit.text(),
                "x_scale": self._x_scale_combo.currentText(),
                "y_scale": self._y_scale_combo.currentText(),
                "right_y_scale": self._right_y_scale_combo.currentText(),
                "x_min": self._x_min_edit.text(),
                "x_max": self._x_max_edit.text(),
                "y_min": self._y_min_edit.text(),
                "y_max": self._y_max_edit.text(),
                "right_y_min": self._right_y_min_edit.text(),
                "right_y_max": self._right_y_max_edit.text(),
                "grid_enabled": self._grid_checkbox.isChecked(),
                "legend_enabled": self._legend_checkbox.isChecked(),
                "legend_position": self._legend_pos_combo.currentText(),
                "figure_width": self._width_spin.value(),
                "figure_height": self._height_spin.value(),
                "plot_style_preset": str(self._style_preset_combo.currentData() or ""),
                "plot_style_cycle": str(self._style_cycle_combo.currentData() or ""),
                "plot_style_use_latex": self._style_latex_checkbox.isChecked(),
                "plot_style_custom": self._style_custom_edit.text(),
            },
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
        self._x_label_edit.setText(x_column)
        self._y_label_edit.setText(y_column)
        self._right_y_label_edit.setText("Residual" if residual_dataset is not None and show_residuals else "")
        self.refresh_controls(fit_dataset.name)
        self._select_first_series_for_editing()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

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
        self._x_label_edit.setText(x_column)
        self._y_label_edit.setText(source_column)
        self._right_y_label_edit.setText(result_column)
        self.refresh_controls(dataset.name)
        self._select_first_series_for_editing()
        self._render_plot(silent_if_empty=True)

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
        self._x_label_edit.setText(x_column)
        self._y_label_edit.setText(y_column)
        self._right_y_label_edit.clear()
        self.refresh_controls(dataset.name)
        self._select_first_series_for_editing()
        self._render_plot(silent_if_empty=True)

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

        self._plot_type_combo = QComboBox()
        for plot_type in PLOT_TYPES.values():
            self._plot_type_combo.addItem(plot_type.label, plot_type.key)

        self._y_axis_combo = QComboBox()
        self._y_axis_combo.addItem("Left", "left")
        self._y_axis_combo.addItem("Right", "right")

        self._line_style_combo = QComboBox()
        for label, data in [("Solid", "-"), ("Dashed", "--"), ("Dotted", ":"), ("Dash-dot", "-."), ("None", "")]:
            self._line_style_combo.addItem(label, data)

        self._marker_combo = QComboBox()
        for label, data in [("None",""), ("Circle","o"), ("Square","s"),
                            ("Triangle","^"), ("Diamond","D"), ("Cross","x"), ("Dot",".")]:
            self._marker_combo.addItem(label, data)

        self._color_combo = QComboBox()
        for label, data in [("Auto",""), ("Blue","tab:blue"), ("Orange","tab:orange"),
                            ("Green","tab:green"), ("Red","tab:red"),
                            ("Purple","tab:purple"), ("Black","black")]:
            self._color_combo.addItem(label, data)

        self._series_label_edit = QLineEdit()

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

        self._title_edit = QLineEdit()
        self._x_label_edit = QLineEdit()
        self._y_label_edit = QLineEdit()
        self._right_y_label_edit = QLineEdit()

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
        self._legend_pos_combo.addItems([
            "best", "upper right", "upper left", "lower left", "lower right", 
            "right", "center left", "center right", "lower center", "upper center", "center"
        ])

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

        self._series_list = QListWidget()
        self._series_list.itemSelectionChanged.connect(self._handle_series_selection_changed)

        self._locator_list = QListWidget()
        self._locator_list.itemSelectionChanged.connect(
            lambda: self._set_controls_enabled(bool(self._workspace.dataset_names()))
        )

        add_btn = QPushButton("Add Series")
        add_btn.clicked.connect(self._add_series)
        self._add_series_button = add_btn

        update_btn = QPushButton("Update Series")
        update_btn.clicked.connect(self._update_selected_series)
        self._update_series_button = update_btn

        rm_btn = QPushButton("Remove Series")
        rm_btn.clicked.connect(self._remove_selected_series)
        self._remove_series_button = rm_btn

        clr_btn = QPushButton("Clear")
        clr_btn.clicked.connect(self._clear_series)
        self._clear_series_button = clr_btn


        self._render_button = QPushButton("Plot")
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
        self._add_series_row(sf, "plot_type", "Plot type", self._plot_type_combo)
        self._add_series_row(sf, "x_dataset", "X dataset", self._x_dataset_combo)
        self._add_series_row(sf, "x_column", "X column", self._x_column_combo)
        self._add_series_row(sf, "x_error", "X error", self._x_err_column_combo)
        self._add_series_row(sf, "y_dataset", "Y dataset", self._y_dataset_combo)
        self._add_series_row(sf, "y_column", "Y column", self._y_column_combo)
        self._add_series_row(sf, "z_dataset", "Z dataset", self._z_dataset_combo)
        self._add_series_row(sf, "z_column", "Z column", self._z_column_combo)
        self._add_series_row(sf, "distribution_columns", "Columns", self._distribution_columns_list)
        self._add_series_row(sf, "y_error", "Y error", self._y_err_column_combo)
        self._add_series_row(sf, "y_axis", "Y axis", self._y_axis_combo)
        self._add_series_row(sf, "label", "Label", self._series_label_edit)
        self._add_series_row(sf, "line", "Line", self._line_style_combo)
        self._add_series_row(sf, "line_width", "Line width", self._line_width_spin)
        self._add_series_row(sf, "marker", "Marker", self._marker_combo)
        self._add_series_row(sf, "marker_size", "Marker size", self._marker_size_spin)
        self._add_series_row(sf, "color", "Color", self._color_combo)
        self._add_series_row(sf, "bar_options", None, self._bar_options_panel)
        self._add_series_row(sf, "fill_options", None, self._fill_options_panel)
        self._add_series_row(sf, "histogram_options", None, self._histogram_options_panel)
        self._add_series_row(sf, "distribution_options", None, self._distribution_options_panel)
        self._add_series_row(sf, "surface_options", None, self._surface_options_panel)
        sb = QHBoxLayout()
        sb.addWidget(add_btn); sb.addWidget(update_btn); sb.addWidget(rm_btn); sb.addWidget(clr_btn)
        sf.addRow(sb)
        sf.addRow("Queued", self._series_list)

        axes_group = QGroupBox("Axes")
        af = QFormLayout(axes_group)
        af.addRow("Title", self._title_edit)
        af.addRow("X label", self._x_label_edit)
        af.addRow("Left Y label", self._y_label_edit)
        af.addRow("Right Y label", self._right_y_label_edit)
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
        af.addRow(self._legend_checkbox, self._legend_pos_combo)
        af.addRow("Width", self._width_spin)
        af.addRow("Height", self._height_spin)

        locator_group = QGroupBox("Data Location")
        lf = QFormLayout(locator_group)
        lf.addRow("Series", self._locator_series_combo)
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
        ctrl_tabs.addTab(locator_group, "Locator")

        ctrl_panel = QWidget()
        ctrl_panel.setMinimumWidth(420)
        cl = QVBoxLayout(ctrl_panel)
        cl.addWidget(ctrl_tabs)
        cl.addStretch(1)
        cl.addWidget(self._render_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(440)
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
        self._load_plot_button = QPushButton("Load Selected")
        self._load_plot_button.clicked.connect(self.load_plot_requested.emit)
        self._remove_plot_button = QPushButton("Remove Saved")
        self._remove_plot_button.clicked.connect(self.remove_plot_requested.emit)

        self._toggle_options_button = QPushButton("Hide Inspector" if self._external_options else "Hide Options")
        self._toggle_options_button.clicked.connect(self._toggle_plot_options)
        top_row = QHBoxLayout()
        top_row.addWidget(self._active_plot_label)
        top_row.addStretch(1)
        top_row.addWidget(self._save_plot_button)
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
            lambda: self._update_column_combo(self._x_dataset_combo, self._x_column_combo)
        )
        self._x_dataset_combo.currentTextChanged.connect(
            lambda: self._update_error_column_combo(self._x_dataset_combo, self._x_err_column_combo)
        )
        self._y_dataset_combo.currentTextChanged.connect(
            lambda: self._update_column_combo(self._y_dataset_combo, self._y_column_combo)
        )
        self._y_dataset_combo.currentTextChanged.connect(
            lambda: self._update_error_column_combo(self._y_dataset_combo, self._y_err_column_combo)
        )
        self._y_dataset_combo.currentTextChanged.connect(self._update_distribution_columns_list)
        self._z_dataset_combo.currentTextChanged.connect(
            lambda: self._update_column_combo(self._z_dataset_combo, self._z_column_combo)
        )
        self._plot_type_combo.currentIndexChanged.connect(self._apply_plot_type_defaults)
        self._style_preset_combo.currentIndexChanged.connect(self._render_plot_if_possible)
        self._style_cycle_combo.currentIndexChanged.connect(self._render_plot_if_possible)
        self._style_latex_checkbox.toggled.connect(self._render_plot_if_possible)
        self._style_custom_edit.editingFinished.connect(self._render_plot_if_possible)
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

    def _update_column_combo(self, ds_combo: QComboBox, col_combo: QComboBox) -> None:
        """Refresh a column combo from the dataset currently selected beside it."""
        name = ds_combo.currentText()
        cols: list[str] = []
        if name:
            try:
                ds = self._workspace.get_dataset(name)
                cols = [str(c) for c in ds.frame.columns]
            except KeyError:
                pass
        self._set_combo_items(col_combo, cols)
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

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

    def _update_error_column_combo(self, ds_combo: QComboBox, col_combo: QComboBox) -> None:
        """Refresh an error column combo, allowing a blank 'no error' selection."""
        name = ds_combo.currentText()
        cols: list[str] = [""]
        if name:
            try:
                ds = self._workspace.get_dataset(name)
                cols.extend([str(c) for c in ds.frame.columns])
            except KeyError:
                pass
        self._set_combo_items(col_combo, cols)

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
            )
        else:
            can_add = has_data and self._x_column_combo.count() > 0 and self._y_column_combo.count() > 0
        self._add_series_button.setEnabled(can_add)
        self._update_series_button.setEnabled(can_add and self._selected_series_row() is not None)
        self._remove_series_button.setEnabled(bool(self._series_list.selectedItems()))
        self._clear_series_button.setEnabled(bool(self._plot_series))
        self._render_button.setEnabled(bool(self._plot_series))
        self._add_locator_button.setEnabled(bool(self._plot_series))
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
        clean_state["interpolation_method"] = str(
            clean_state.get("interpolation_method", "linear") or "linear"
        )
        try:
            clean_state["grid_resolution"] = int(clean_state.get("grid_resolution", 120))
        except (TypeError, ValueError):
            clean_state["grid_resolution"] = 120
        return PlotSeries(**clean_state)

    def _plot_locator_from_state(self, state: dict[str, object]) -> PlotLocator:
        """Deserialize one saved locator dictionary into a PlotLocator."""
        clean_state = {key: value for key, value in state.items() if key in _PLOT_LOCATOR_FIELDS}
        if clean_state.get("y_value") in ("", None):
            clean_state["y_value"] = None
        elif "y_value" in clean_state:
            try:
                clean_state["y_value"] = float(clean_state["y_value"])
            except (TypeError, ValueError):
                clean_state["y_value"] = None
        return PlotLocator(**clean_state)

    def _apply_plot_settings(self, state: object) -> None:
        """Apply saved axis, legend, range, and figure settings."""
        if not isinstance(state, dict):
            state = {}

        self._title_edit.setText(self._setting_text(state, "title"))
        self._x_label_edit.setText(self._setting_text(state, "x_label"))
        self._y_label_edit.setText(self._setting_text(state, "y_label"))
        self._right_y_label_edit.setText(self._setting_text(state, "right_y_label"))
        self._set_combo_text(self._x_scale_combo, str(state.get("x_scale", "linear")))
        self._set_combo_text(self._y_scale_combo, str(state.get("y_scale", "linear")))
        self._set_combo_text(self._right_y_scale_combo, str(state.get("right_y_scale", "linear")))
        self._x_min_edit.setText(self._setting_text(state, "x_min"))
        self._x_max_edit.setText(self._setting_text(state, "x_max"))
        self._y_min_edit.setText(self._setting_text(state, "y_min"))
        self._y_max_edit.setText(self._setting_text(state, "y_max"))
        self._right_y_min_edit.setText(self._setting_text(state, "right_y_min"))
        self._right_y_max_edit.setText(self._setting_text(state, "right_y_max"))
        self._grid_checkbox.setChecked(bool(state.get("grid_enabled", True)))
        self._legend_checkbox.setChecked(bool(state.get("legend_enabled", True)))
        self._set_combo_text(self._legend_pos_combo, str(state.get("legend_position", "best")))
        self._width_spin.setValue(self._setting_float(state, "figure_width", 7.0))
        self._height_spin.setValue(self._setting_float(state, "figure_height", 4.8))
        self._set_combo_data(self._style_preset_combo, str(state.get("plot_style_preset", "")))
        self._set_combo_data(self._style_cycle_combo, str(state.get("plot_style_cycle", "")))
        self._style_latex_checkbox.setChecked(bool(state.get("plot_style_use_latex", False)))
        self._style_custom_edit.setText(self._setting_text(state, "plot_style_custom"))

    @staticmethod
    def _setting_text(state: dict[str, object], key: str) -> str:
        """Return a text setting, treating None as blank."""
        value = state.get(key, "")
        return "" if value is None else str(value)

    @staticmethod
    def _setting_float(state: dict[str, object], key: str, fallback: float) -> float:
        """Return a numeric setting with a fallback for malformed state."""
        try:
            return float(state.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _set_combo_text(combo: QComboBox, value: str) -> None:
        """Set combo selection by display text when present."""
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    # -- series management --------------------------------------------------

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
        ):
            QMessageBox.information(
                self,
                "Add Series",
                "Choose X, Y, and Z columns before adding a 2D map.",
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
        self._refresh_locator_series_combo()
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
                if plot_type in ({"box", "violin"} | _SURFACE_PLOT_TYPES)
                else str(self._y_axis_combo.currentData() or "left")
            ),
            custom_label=self._series_label_edit.text().strip(),
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
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot()

    def _selected_series_row(self) -> int | None:
        """Return the selected queued-series row, if any."""
        rows = sorted({index.row() for index in self._series_list.selectedIndexes()})
        return rows[0] if rows else None

    def _handle_series_selection_changed(self) -> None:
        """Load selected queued series details into the edit controls."""
        row = self._selected_series_row()
        if row is not None and 0 <= row < len(self._plot_series):
            self._load_series_controls(self._plot_series[row])
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    def _load_series_controls(self, series: PlotSeries) -> None:
        """Populate series edit controls from a PlotSeries."""
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
        self._set_distribution_column_selection(
            list(series.distribution_columns) or ([series.y_column] if series.plot_type in {"box", "violin"} else [])
        )
        self._set_combo_data(self._plot_type_combo, series.plot_type)
        self._set_combo_data(self._y_axis_combo, series.y_axis)
        self._series_label_edit.setText(series.custom_label)
        self._set_combo_data(self._line_style_combo, series.line_style)
        self._set_combo_data(self._marker_combo, series.marker)
        self._set_combo_data(self._color_combo, series.color)
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
        self._update_plot_type_option_visibility()

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

    def _apply_plot_type_defaults(self) -> None:
        """Apply practical line/marker defaults when the user changes plot type."""
        plot_type = str(self._plot_type_combo.currentData() or "line")
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
        elif plot_type in {"bar", "barh"}:
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
        x_y_types = {"line", "scatter", "line_marker", "errorbar", "bar", "barh", "area"}
        line_types = {"line", "line_marker", "errorbar", "area"}
        marker_types = {"scatter", "line_marker", "errorbar"}
        distribution_types = {"box", "violin"}
        coordinate_types = x_y_types | _SURFACE_PLOT_TYPES

        self._set_series_row_visible("x_dataset", plot_type in coordinate_types)
        self._set_series_row_visible("x_column", plot_type in coordinate_types)
        self._set_series_row_visible("x_error", plot_type == "errorbar")
        self._set_series_row_visible("y_error", plot_type == "errorbar")
        self._set_series_row_visible("y_column", plot_type not in distribution_types)
        self._set_series_row_visible("z_dataset", plot_type in _SURFACE_PLOT_TYPES)
        self._set_series_row_visible("z_column", plot_type in _SURFACE_PLOT_TYPES)
        self._set_series_row_visible("distribution_columns", plot_type in distribution_types)
        self._set_series_row_visible("y_axis", plot_type in {"line", "scatter", "line_marker", "errorbar", "bar", "area"})
        self._set_series_row_visible("line", plot_type in line_types)
        self._set_series_row_visible("line_width", plot_type in line_types)
        self._set_series_row_visible("marker", plot_type in marker_types)
        self._set_series_row_visible("marker_size", plot_type in marker_types)
        self._set_series_row_visible("bar_options", plot_type in {"bar", "barh"})
        self._set_series_row_visible("fill_options", plot_type in {"area", "histogram"})
        self._set_series_row_visible("histogram_options", plot_type == "histogram")
        self._set_series_row_visible("distribution_options", plot_type in distribution_types)
        self._set_series_row_visible("surface_options", plot_type in _SURFACE_PLOT_TYPES)

        if plot_type == "histogram":
            self._set_series_row_label("y_dataset", "Value dataset")
            self._set_series_row_label("y_column", "Value column")
        elif plot_type in distribution_types:
            self._set_series_row_label("y_dataset", "Data dataset")
            self._set_series_row_label("distribution_columns", "Value columns")
        elif plot_type in _SURFACE_PLOT_TYPES:
            self._set_series_row_label("x_dataset", "X dataset")
            self._set_series_row_label("x_column", "X coordinate")
            self._set_series_row_label("y_dataset", "Y dataset")
            self._set_series_row_label("y_column", "Y coordinate")
            self._set_series_row_label("z_dataset", "Z dataset")
            self._set_series_row_label("z_column", "Z value")
        elif plot_type == "barh":
            self._set_series_row_label("x_dataset", "Position dataset")
            self._set_series_row_label("x_column", "Position column")
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
        for r in rows:
            self._plot_series.pop(r)
            self._series_list.takeItem(r)
        self._reindex_locators_after_removal(rows)
        self._refresh_locator_series_combo()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _clear_series(self) -> None:
        """Clear all queued series, locators, and rendered plot content."""
        self._plot_series.clear()
        self._series_list.clear()
        self._plot_locators.clear()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._plot_canvas.clear_plot()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self.status_message.emit("Cleared plot series")
        self.plot_rendered.emit()


    # -- locator management -------------------------------------------------

    def _add_locator(self) -> None:
        """Add an interpolation locator for the selected queued series."""
        if not self._plot_series:
            QMessageBox.information(self, "Add Locator", "Add a plotted series before locating data.")
            return
        x_val, errs = self._parse_optional_float(self._locator_x_edit.text(), "Locator X value")
        if errs or x_val is None:
            QMessageBox.warning(self, "Add Locator", "\n".join(errs or ["Locator X value is required."]))
            return
        idx = self._locator_series_combo.currentData()
        if not isinstance(idx, int) or not 0 <= idx < len(self._plot_series):
            QMessageBox.warning(self, "Add Locator", "Choose a valid queued series.")
            return
        y_val: float | None = None
        if self._plot_series[idx].plot_type in _SURFACE_PLOT_TYPES:
            y_val, y_errs = self._parse_optional_float(
                self._locator_y_edit.text(),
                "Locator Y value",
            )
            if y_errs or y_val is None:
                QMessageBox.warning(
                    self,
                    "Add Locator",
                    "\n".join(y_errs or ["Locator Y value is required for 2D maps."]),
                )
                return
        loc = PlotLocator(
            series_index=idx, x_value=x_val,
            y_value=y_val,
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
                x_value=loc.x_value, y_value=loc.y_value, marker=loc.marker,
                size=loc.size, color=loc.color,
            ))
        self._plot_locators = new
        self._refresh_locator_list()

    def _refresh_locator_list(self, located: list[LocatedPoint] | None = None) -> None:
        """Refresh locator list text, including computed values when available."""
        by_idx = {lp.locator_index: lp for lp in located or []}
        self._locator_list.clear()
        for i, loc in enumerate(self._plot_locators):
            self._locator_list.addItem(self._locator_text(loc, by_idx.get(i)))

    # -- rendering ----------------------------------------------------------

    def _render_plot_if_possible(self) -> None:
        """Refresh the visible plot after a style-control change."""
        if self._plot_series:
            self._render_plot(silent_if_empty=True)

    def _render_plot(self, silent_if_empty: bool = False) -> None:
        """Render queued series and locators to the Matplotlib canvas."""
        if not self._plot_series:
            self._plot_canvas.clear_plot()
            self._set_controls_enabled(bool(self._workspace.dataset_names()))
            if not silent_if_empty:
                QMessageBox.information(self, "Plot", "Add at least one series before plotting.")
            return

        x_label = self._x_label_edit.text().strip()
        y_label = self._y_label_edit.text().strip()
        ry_label = self._right_y_label_edit.text().strip()
        if len(self._plot_series) == 1:
            s0 = self._plot_series[0]
            if s0.plot_type == "histogram":
                x_label = x_label or s0.y_column
                y_label = y_label or ("Density" if s0.histogram_density else "Count")
            elif s0.plot_type in {"box", "violin"}:
                x_label = x_label or "Column"
                y_label = y_label or "Value"
            elif s0.plot_type in _SURFACE_PLOT_TYPES:
                x_label = x_label or s0.x_column
                y_label = y_label or s0.y_column
            elif s0.plot_type == "barh":
                x_label = x_label or s0.y_column
                y_label = y_label or s0.x_column
            else:
                x_label = x_label or s0.x_column
            non_y_axis_types = {"histogram", "barh", "box", "violin"} | _SURFACE_PLOT_TYPES
            if s0.plot_type in non_y_axis_types:
                pass
            elif s0.y_axis == "right":
                ry_label = ry_label or s0.y_column
            else:
                y_label = y_label or s0.y_column

        inputs, errors = self._plot_inputs()
        if errors:
            QMessageBox.warning(self, "Plot Settings", "\n".join(errors))
            return

        result = self._plot_canvas.plot_series(
            workspace=self._workspace,
            series_list=self._plot_series,
            title=self._title_edit.text().strip(),
            x_label=x_label, y_label=y_label, right_y_label=ry_label,
            **inputs,
            figure_width=self._width_spin.value(),
            figure_height=self._height_spin.value(),
        )
        self._refresh_locator_list(result.located_points)

        if result.skipped_messages and result.plotted_count == 0:
            QMessageBox.warning(self, "Plot Failed", "\n".join(result.skipped_messages[:5]))
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

        self.plot_rendered.emit()

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
                f"{series.grid_resolution} grid",
            ])
        else:
            bits.extend([
                _LINE_LABELS.get(series.line_style, series.line_style or "None"),
                _MARKER_LABELS.get(series.marker, series.marker or "None"),
                _COLOR_LABELS.get(series.color, series.color or "Auto"),
                f"{series.y_axis} axis",
            ])
        return f"{series.label} ({', '.join(bits)})"

    def _locator_text(self, loc: PlotLocator, pt: LocatedPoint | None = None) -> str:
        """Return locator list text before or after interpolation."""
        label = self._plot_series[loc.series_index].label
        if pt is not None:
            if pt.z_value is not None:
                return (
                    f"{label}: x={pt.x_value:g}, y={pt.y_value:g}, "
                    f"z={pt.z_value:g}"
                )
            return f"{label}: x={pt.x_value:g}, y={pt.y_value:g} ({pt.y_axis})"
        if loc.y_value is not None:
            return f"{label}: x={loc.x_value:g}, y={loc.y_value:g} (pending)"
        return f"{label}: x={loc.x_value:g} (pending)"

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
                "x_limits": xl, "y_limits": yl, "right_y_limits": rl,
                "grid_enabled": self._grid_checkbox.isChecked(),
                "legend_enabled": self._legend_checkbox.isChecked(),
                "legend_position": self._legend_pos_combo.currentText(),
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
