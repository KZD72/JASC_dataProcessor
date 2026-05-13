"""Plot tab widget extracted from main_window for modularity."""

from __future__ import annotations

from dataclasses import asdict, fields

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.workspace import Dataset, Workspace
from ui.plot_canvas import LocatedPoint, PlotCanvas, PlotLocator, PlotSeries

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
_PLOT_SERIES_FIELDS = {field.name for field in fields(PlotSeries)}
_PLOT_LOCATOR_FIELDS = {field.name for field in fields(PlotLocator)}


class PlotTab(QWidget):
    """Self-contained plot tab with series management, locators, and rendering."""

    status_message = Signal(str)
    plot_rendered = Signal()

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workspace = workspace
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
        self._update_column_combo(self._x_dataset_combo, self._x_column_combo)
        self._update_column_combo(self._y_dataset_combo, self._y_column_combo)
        self._set_controls_enabled(bool(names))

    def has_plot_series(self) -> bool:
        """Return whether the plot tab has a restorable plot definition."""
        return bool(self._plot_series)

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
            },
        }

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
    ) -> None:
        """Replace the current series queue with a data-vs-fit overlay."""
        fit_lower = "fit_lower" if "fit_lower" in fit_dataset.frame.columns else ""
        fit_upper = "fit_upper" if "fit_upper" in fit_dataset.frame.columns else ""
        self._plot_series = [
            PlotSeries(
                x_dataset=source_dataset.name, x_column=x_column,
                y_dataset=source_dataset.name, y_column=y_column,
                color="tab:blue", line_style="", marker="o",
                custom_label=f"{source_dataset.name}: {y_column}",
            ),
            PlotSeries(
                x_dataset=fit_dataset.name, x_column="fit_x",
                y_dataset=fit_dataset.name, y_column="fit_y",
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
        self._x_dataset_combo = QComboBox()
        self._x_column_combo = QComboBox()
        self._y_dataset_combo = QComboBox()
        self._y_column_combo = QComboBox()

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

        self._grid_checkbox = QCheckBox("Grid")
        self._grid_checkbox.setChecked(True)

        self._locator_series_combo = QComboBox()
        self._locator_x_edit = QLineEdit()
        self._locator_x_edit.setPlaceholderText("X value")

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

        scatter_btn = QPushButton("Scatter")
        scatter_btn.clicked.connect(self._set_scatter_only)

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
        sf.addRow("X dataset", self._x_dataset_combo)
        sf.addRow("X column", self._x_column_combo)
        sf.addRow("Y dataset", self._y_dataset_combo)
        sf.addRow("Y column", self._y_column_combo)
        sf.addRow("Y axis", self._y_axis_combo)
        sf.addRow("Label", self._series_label_edit)
        sf.addRow("Line", self._line_style_combo)
        sf.addRow("Line width", self._line_width_spin)
        sf.addRow("Marker", self._marker_combo)
        sf.addRow("Marker size", self._marker_size_spin)
        sf.addRow("Color", self._color_combo)
        sb = QHBoxLayout()
        sb.addWidget(add_btn); sb.addWidget(update_btn); sb.addWidget(rm_btn); sb.addWidget(clr_btn); sb.addWidget(scatter_btn)
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
        af.addRow("", self._grid_checkbox)
        af.addRow(self._legend_checkbox, self._legend_pos_combo)
        af.addRow("Width", self._width_spin)
        af.addRow("Height", self._height_spin)

        locator_group = QGroupBox("Data Location")
        lf = QFormLayout(locator_group)
        lf.addRow("Series", self._locator_series_combo)
        lf.addRow("X value", self._locator_x_edit)
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
        cl = QVBoxLayout(ctrl_panel)
        cl.addWidget(ctrl_tabs)
        cl.addStretch(1)
        cl.addWidget(self._render_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(ctrl_panel)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(self._plot_canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 760])

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self._x_dataset_combo.currentTextChanged.connect(
            lambda: self._update_column_combo(self._x_dataset_combo, self._x_column_combo)
        )
        self._y_dataset_combo.currentTextChanged.connect(
            lambda: self._update_column_combo(self._y_dataset_combo, self._y_column_combo)
        )
        self.refresh_controls()

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _range_row(min_edit: QLineEdit, max_edit: QLineEdit) -> QWidget:
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

    def _update_column_combo(self, ds_combo: QComboBox, col_combo: QComboBox) -> None:
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

    @staticmethod
    def _set_combo_items(combo: QComboBox, items: list[str], preferred: str | None = None) -> None:
        cur = preferred or combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if cur and cur in items:
            combo.setCurrentText(cur)
        combo.blockSignals(False)

    def _set_controls_enabled(self, has_data: bool) -> None:
        can_add = has_data and self._x_column_combo.count() > 0 and self._y_column_combo.count() > 0
        self._add_series_button.setEnabled(can_add)
        self._update_series_button.setEnabled(can_add and self._selected_series_row() is not None)
        self._remove_series_button.setEnabled(bool(self._series_list.selectedItems()))
        self._clear_series_button.setEnabled(bool(self._plot_series))
        self._render_button.setEnabled(bool(self._plot_series))
        self._add_locator_button.setEnabled(bool(self._plot_series))
        self._remove_locator_button.setEnabled(bool(self._locator_list.selectedItems()))
        self._clear_locators_button.setEnabled(bool(self._plot_locators))

    def _refresh_series_list(self) -> None:
        self._series_list.clear()
        for series in self._plot_series:
            self._series_list.addItem(self._series_text(series))

    def _select_first_series_for_editing(self) -> None:
        if not self._plot_series:
            return

        self._series_list.setCurrentRow(0)
        self._load_series_controls(self._plot_series[0])
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    def _plot_series_from_state(self, state: dict[str, object]) -> PlotSeries:
        clean_state = {key: value for key, value in state.items() if key in _PLOT_SERIES_FIELDS}
        return PlotSeries(**clean_state)

    def _plot_locator_from_state(self, state: dict[str, object]) -> PlotLocator:
        clean_state = {key: value for key, value in state.items() if key in _PLOT_LOCATOR_FIELDS}
        return PlotLocator(**clean_state)

    def _apply_plot_settings(self, state: object) -> None:
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

    @staticmethod
    def _setting_text(state: dict[str, object], key: str) -> str:
        value = state.get(key, "")
        return "" if value is None else str(value)

    @staticmethod
    def _setting_float(state: dict[str, object], key: str, fallback: float) -> float:
        try:
            return float(state.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _set_combo_text(combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    # -- series management --------------------------------------------------

    def _add_series(self) -> None:
        if self._x_column_combo.count() == 0 or self._y_column_combo.count() == 0:
            QMessageBox.information(self, "Add Series", "Import or create a dataset before adding a series.")
            return
        series = self._series_from_controls()
        self._plot_series.append(series)
        self._series_list.addItem(self._series_text(series))
        self._refresh_locator_series_combo()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot()

    def _series_from_controls(self) -> PlotSeries:
        line_style_data = self._line_style_combo.currentData()
        return PlotSeries(
            x_dataset=self._x_dataset_combo.currentText(),
            x_column=self._x_column_combo.currentText(),
            y_dataset=self._y_dataset_combo.currentText(),
            y_column=self._y_column_combo.currentText(),
            color=str(self._color_combo.currentData() or ""),
            line_style=str(line_style_data) if line_style_data is not None else "-",
            marker=str(self._marker_combo.currentData() or ""),
            y_axis=str(self._y_axis_combo.currentData() or "left"),
            custom_label=self._series_label_edit.text().strip(),
            line_width=self._line_width_spin.value(),
            marker_size=self._marker_size_spin.value(),
        )

    def _update_selected_series(self) -> None:
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
        rows = sorted({index.row() for index in self._series_list.selectedIndexes()})
        return rows[0] if rows else None

    def _handle_series_selection_changed(self) -> None:
        row = self._selected_series_row()
        if row is not None and 0 <= row < len(self._plot_series):
            self._load_series_controls(self._plot_series[row])
        self._set_controls_enabled(bool(self._workspace.dataset_names()))

    def _load_series_controls(self, series: PlotSeries) -> None:
        self._x_dataset_combo.setCurrentText(series.x_dataset)
        self._update_column_combo(self._x_dataset_combo, self._x_column_combo)
        self._x_column_combo.setCurrentText(series.x_column)
        self._y_dataset_combo.setCurrentText(series.y_dataset)
        self._update_column_combo(self._y_dataset_combo, self._y_column_combo)
        self._y_column_combo.setCurrentText(series.y_column)
        self._set_combo_data(self._y_axis_combo, series.y_axis)
        self._series_label_edit.setText(series.custom_label)
        self._set_combo_data(self._line_style_combo, series.line_style)
        self._set_combo_data(self._marker_combo, series.marker)
        self._set_combo_data(self._color_combo, series.color)
        self._line_width_spin.setValue(series.line_width)
        self._marker_size_spin.setValue(series.marker_size)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _remove_selected_series(self) -> None:
        rows = sorted({i.row() for i in self._series_list.selectedIndexes()}, reverse=True)
        for r in rows:
            self._plot_series.pop(r)
            self._series_list.takeItem(r)
        self._reindex_locators_after_removal(rows)
        self._refresh_locator_series_combo()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _clear_series(self) -> None:
        self._plot_series.clear()
        self._series_list.clear()
        self._plot_locators.clear()
        self._locator_list.clear()
        self._refresh_locator_series_combo()
        self._plot_canvas.clear_plot()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self.status_message.emit("Cleared plot series")
        self.plot_rendered.emit()

    def _set_scatter_only(self) -> None:
        none_index = self._line_style_combo.findData("")
        if none_index >= 0:
            self._line_style_combo.setCurrentIndex(none_index)
        if self._marker_combo.currentText() == "None":
            self._marker_combo.setCurrentText("Circle")

    # -- locator management -------------------------------------------------

    def _add_locator(self) -> None:
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
        loc = PlotLocator(
            series_index=idx, x_value=x_val,
            marker=str(self._locator_marker_combo.currentData() or "o"),
            size=self._locator_size_spin.value(),
            color=str(self._locator_color_combo.currentData() or "tab:red"),
        )
        self._plot_locators.append(loc)
        self._locator_list.addItem(self._locator_text(loc))
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot()

    def _remove_selected_locator(self) -> None:
        rows = sorted({i.row() for i in self._locator_list.selectedIndexes()}, reverse=True)
        for r in rows:
            self._plot_locators.pop(r)
            self._locator_list.takeItem(r)
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _clear_locators(self) -> None:
        self._plot_locators.clear()
        self._locator_list.clear()
        self._set_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _refresh_locator_series_combo(self) -> None:
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
        removed_set = set(removed)
        new: list[PlotLocator] = []
        for loc in self._plot_locators:
            if loc.series_index in removed_set:
                continue
            shift = sum(1 for r in removed_set if r < loc.series_index)
            new.append(PlotLocator(
                series_index=loc.series_index - shift,
                x_value=loc.x_value, marker=loc.marker,
                size=loc.size, color=loc.color,
            ))
        self._plot_locators = new
        self._refresh_locator_list()

    def _refresh_locator_list(self, located: list[LocatedPoint] | None = None) -> None:
        by_idx = {lp.locator_index: lp for lp in located or []}
        self._locator_list.clear()
        for i, loc in enumerate(self._plot_locators):
            self._locator_list.addItem(self._locator_text(loc, by_idx.get(i)))

    # -- rendering ----------------------------------------------------------

    def _render_plot(self, silent_if_empty: bool = False) -> None:
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
            x_label = x_label or s0.x_column
            if s0.y_axis == "right":
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
        bits = [
            _LINE_LABELS.get(series.line_style, series.line_style or "None"),
            _MARKER_LABELS.get(series.marker, series.marker or "None"),
            _COLOR_LABELS.get(series.color, series.color or "Auto"),
            f"{series.y_axis} axis",
        ]
        return f"{series.label} ({', '.join(bits)})"

    def _locator_text(self, loc: PlotLocator, pt: LocatedPoint | None = None) -> str:
        label = self._plot_series[loc.series_index].label
        if pt is not None:
            return f"{label}: x={pt.x_value:g}, y={pt.y_value:g} ({pt.y_axis})"
        return f"{label}: x={loc.x_value:g} (pending)"

    # -- input parsing ------------------------------------------------------

    def _plot_inputs(self) -> tuple[dict[str, object], list[str]]:
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
            },
            errors,
        )

    def _parse_range(
        self, min_edit: QLineEdit, max_edit: QLineEdit, label: str,
    ) -> tuple[tuple[float | None, float | None], list[str]]:
        lo, lo_err = self._parse_optional_float(min_edit.text(), f"{label} minimum")
        hi, hi_err = self._parse_optional_float(max_edit.text(), f"{label} maximum")
        errors = lo_err + hi_err
        if lo is not None and hi is not None and lo >= hi:
            errors.append(f"{label}: minimum must be smaller than maximum.")
        return (lo, hi), errors

    @staticmethod
    def _parse_optional_float(text: str, label: str) -> tuple[float | None, list[str]]:
        stripped = text.strip()
        if not stripped:
            return None, []
        try:
            return float(stripped), []
        except ValueError:
            return None, [f"{label} must be numeric."]
