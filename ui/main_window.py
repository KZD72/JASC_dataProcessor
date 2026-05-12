"""Main application window for the JASC Data Processor."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.file_io import export_tabular_file, read_tabular_file
from core.operations import ExpressionError
from core.workspace import Dataset, Workspace
from ui.data_table import DataTableWidget
from ui.dataframe_model import DataFrameTableModel
from ui.dialogs import ColumnExpressionDialog, ImportOptionsDialog
from ui.plot_canvas import PlotCanvas, PlotSeries


class MainWindow(QMainWindow):
    """Primary application shell for data ingestion, editing, and plotting workflows."""

    def __init__(self) -> None:
        super().__init__()
        self._workspace = Workspace()

        self.setWindowTitle("JASC Data Processor")
        self.resize(1100, 720)

        self._dataset_list = QListWidget()
        self._dataset_list.currentTextChanged.connect(self._show_dataset_editor)

        self._dataset_model = DataFrameTableModel(self)
        self._dataset_table = QTableView()
        self._dataset_table.setModel(self._dataset_model)
        self._dataset_table.setAlternatingRowColors(True)
        self._dataset_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._dataset_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._dataset_table.setSortingEnabled(False)
        self._dataset_table.doubleClicked.connect(self._edit_dataset_cell)
        self._dataset_summary = QLabel("No dataset selected")

        self._plot_series: list[PlotSeries] = []
        self._plot_canvas = PlotCanvas()

        self._manual_table = DataTableWidget()
        self._manual_table.dataset_submitted.connect(self._add_manual_dataset)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_dataset_editor(), "Data Editor")
        self._tabs.addTab(self._build_plot_tab(), "Plot")
        self._tabs.addTab(self._manual_table, "Manual Entry")

        sidebar = self._build_sidebar()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 840])

        self.setCentralWidget(splitter)
        self._create_actions()
        self.statusBar().showMessage("Ready")

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)
        layout.addWidget(QLabel("Workspace Datasets"))
        layout.addWidget(self._dataset_list)
        return sidebar

    def _build_dataset_editor(self) -> QWidget:
        editor = QWidget()

        add_column_button = QPushButton("Add Column")
        add_column_button.clicked.connect(self._add_empty_column)

        apply_formula_button = QPushButton("Apply Formula")
        apply_formula_button.clicked.connect(self._apply_column_formula)

        delete_rows_button = QPushButton("Delete Selected Rows")
        delete_rows_button.clicked.connect(self._delete_selected_rows)

        export_button = QPushButton("Export Sheet")
        export_button.clicked.connect(self._export_current_dataset)

        controls = QHBoxLayout()
        controls.addWidget(self._dataset_summary)
        controls.addStretch(1)
        controls.addWidget(add_column_button)
        controls.addWidget(apply_formula_button)
        controls.addWidget(delete_rows_button)
        controls.addWidget(export_button)

        layout = QVBoxLayout(editor)
        layout.addLayout(controls)
        layout.addWidget(self._dataset_table)
        return editor

    def _build_plot_tab(self) -> QWidget:
        plot_tab = QWidget()
        self._plot_tab = plot_tab

        self._plot_x_dataset_combo = QComboBox()
        self._plot_x_column_combo = QComboBox()
        self._plot_y_dataset_combo = QComboBox()
        self._plot_y_column_combo = QComboBox()

        self._plot_y_axis_combo = QComboBox()
        self._plot_y_axis_combo.addItem("Left", "left")
        self._plot_y_axis_combo.addItem("Right", "right")

        self._plot_line_style_combo = QComboBox()
        self._plot_line_style_combo.addItem("Solid", "-")
        self._plot_line_style_combo.addItem("Dashed", "--")
        self._plot_line_style_combo.addItem("Dotted", ":")
        self._plot_line_style_combo.addItem("Dash-dot", "-.")

        self._plot_marker_combo = QComboBox()
        self._plot_marker_combo.addItem("None", "")
        self._plot_marker_combo.addItem("Circle", "o")
        self._plot_marker_combo.addItem("Square", "s")
        self._plot_marker_combo.addItem("Triangle", "^")
        self._plot_marker_combo.addItem("Diamond", "D")
        self._plot_marker_combo.addItem("Cross", "x")
        self._plot_marker_combo.addItem("Dot", ".")

        self._plot_color_combo = QComboBox()
        self._plot_color_combo.addItem("Auto", "")
        self._plot_color_combo.addItem("Blue", "tab:blue")
        self._plot_color_combo.addItem("Orange", "tab:orange")
        self._plot_color_combo.addItem("Green", "tab:green")
        self._plot_color_combo.addItem("Red", "tab:red")
        self._plot_color_combo.addItem("Purple", "tab:purple")
        self._plot_color_combo.addItem("Black", "black")

        self._plot_title_edit = QLineEdit()
        self._plot_x_label_edit = QLineEdit()
        self._plot_y_label_edit = QLineEdit()
        self._plot_right_y_label_edit = QLineEdit()

        self._plot_x_scale_combo = QComboBox()
        self._plot_x_scale_combo.addItems(["linear", "log"])

        self._plot_y_scale_combo = QComboBox()
        self._plot_y_scale_combo.addItems(["linear", "log"])

        self._plot_right_y_scale_combo = QComboBox()
        self._plot_right_y_scale_combo.addItems(["linear", "log"])

        self._plot_x_min_edit = QLineEdit()
        self._plot_x_max_edit = QLineEdit()
        self._plot_y_min_edit = QLineEdit()
        self._plot_y_max_edit = QLineEdit()
        self._plot_right_y_min_edit = QLineEdit()
        self._plot_right_y_max_edit = QLineEdit()

        self._plot_grid_checkbox = QCheckBox("Grid")
        self._plot_grid_checkbox.setChecked(True)

        self._plot_x_guides_edit = QLineEdit()
        self._plot_y_guides_edit = QLineEdit()
        self._plot_right_y_guides_edit = QLineEdit()

        self._plot_width_spin = QDoubleSpinBox()
        self._plot_width_spin.setRange(3.0, 20.0)
        self._plot_width_spin.setSingleStep(0.5)
        self._plot_width_spin.setValue(7.0)
        self._plot_width_spin.setSuffix(" in")

        self._plot_height_spin = QDoubleSpinBox()
        self._plot_height_spin.setRange(2.0, 15.0)
        self._plot_height_spin.setSingleStep(0.5)
        self._plot_height_spin.setValue(4.8)
        self._plot_height_spin.setSuffix(" in")

        self._plot_series_list = QListWidget()
        self._plot_series_list.itemSelectionChanged.connect(
            lambda: self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        )

        self._add_series_button = QPushButton("Add Series")
        self._add_series_button.clicked.connect(self._add_plot_series)

        self._remove_series_button = QPushButton("Remove Series")
        self._remove_series_button.clicked.connect(self._remove_selected_plot_series)

        self._clear_series_button = QPushButton("Clear")
        self._clear_series_button.clicked.connect(self._clear_plot_series)

        self._render_plot_button = QPushButton("Plot")
        self._render_plot_button.clicked.connect(self._render_plot)

        series_group = QGroupBox("Series")
        series_form = QFormLayout(series_group)
        series_form.addRow("X dataset", self._plot_x_dataset_combo)
        series_form.addRow("X column", self._plot_x_column_combo)
        series_form.addRow("Y dataset", self._plot_y_dataset_combo)
        series_form.addRow("Y column", self._plot_y_column_combo)
        series_form.addRow("Y axis", self._plot_y_axis_combo)
        series_form.addRow("Line", self._plot_line_style_combo)
        series_form.addRow("Marker", self._plot_marker_combo)
        series_form.addRow("Color", self._plot_color_combo)

        series_buttons = QHBoxLayout()
        series_buttons.addWidget(self._add_series_button)
        series_buttons.addWidget(self._remove_series_button)
        series_buttons.addWidget(self._clear_series_button)
        series_form.addRow(series_buttons)
        series_form.addRow("Queued", self._plot_series_list)

        labels_group = QGroupBox("Axes")
        labels_form = QFormLayout(labels_group)
        labels_form.addRow("Title", self._plot_title_edit)
        labels_form.addRow("X label", self._plot_x_label_edit)
        labels_form.addRow("Left Y label", self._plot_y_label_edit)
        labels_form.addRow("Right Y label", self._plot_right_y_label_edit)
        labels_form.addRow("X scale", self._plot_x_scale_combo)
        labels_form.addRow("Left Y scale", self._plot_y_scale_combo)
        labels_form.addRow("Right Y scale", self._plot_right_y_scale_combo)
        labels_form.addRow("X range", self._range_row(self._plot_x_min_edit, self._plot_x_max_edit))
        labels_form.addRow("Left Y range", self._range_row(self._plot_y_min_edit, self._plot_y_max_edit))
        labels_form.addRow(
            "Right Y range",
            self._range_row(self._plot_right_y_min_edit, self._plot_right_y_max_edit),
        )
        labels_form.addRow("", self._plot_grid_checkbox)
        labels_form.addRow("Width", self._plot_width_spin)
        labels_form.addRow("Height", self._plot_height_spin)
        labels_form.addRow("", self._render_plot_button)

        guides_group = QGroupBox("Guides")
        guides_form = QFormLayout(guides_group)
        guides_form.addRow("X guides", self._plot_x_guides_edit)
        guides_form.addRow("Left Y guides", self._plot_y_guides_edit)
        guides_form.addRow("Right Y guides", self._plot_right_y_guides_edit)

        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        control_layout.addWidget(series_group)
        control_layout.addWidget(labels_group)
        control_layout.addWidget(guides_group)
        control_layout.addStretch(1)

        control_scroll = QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setWidget(control_panel)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(control_scroll)
        splitter.addWidget(self._plot_canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 760])

        layout = QVBoxLayout(plot_tab)
        layout.addWidget(splitter)

        self._plot_x_dataset_combo.currentTextChanged.connect(
            lambda: self._update_plot_column_combo(
                self._plot_x_dataset_combo,
                self._plot_x_column_combo,
            )
        )
        self._plot_y_dataset_combo.currentTextChanged.connect(
            lambda: self._update_plot_column_combo(
                self._plot_y_dataset_combo,
                self._plot_y_column_combo,
            )
        )
        self._refresh_plot_controls()
        return plot_tab

    def _range_row(self, minimum_edit: QLineEdit, maximum_edit: QLineEdit) -> QWidget:
        minimum_edit.setPlaceholderText("min")
        maximum_edit.setPlaceholderText("max")
        minimum_edit.setMaximumWidth(90)
        maximum_edit.setMaximumWidth(90)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(minimum_edit)
        layout.addWidget(maximum_edit)
        layout.addStretch(1)
        return row

    def _create_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        import_action = file_menu.addAction("&Import Data...")
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self._import_data_file)

        export_action = file_menu.addAction("&Export Sheet...")
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._export_current_dataset)

        edit_menu = self.menuBar().addMenu("&Edit")
        delete_rows_action = edit_menu.addAction("&Delete Selected Rows")
        delete_rows_action.setShortcut("Del")
        delete_rows_action.triggered.connect(self._delete_selected_rows)

        data_menu = self.menuBar().addMenu("&Data")
        add_column_action = data_menu.addAction("&Add Column...")
        add_column_action.triggered.connect(self._add_empty_column)

        apply_formula_action = data_menu.addAction("&Apply Formula...")
        apply_formula_action.setShortcut("Ctrl+Shift+F")
        apply_formula_action.triggered.connect(self._apply_column_formula)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.addAction(import_action)
        toolbar.addAction(export_action)
        toolbar.addAction(add_column_action)
        toolbar.addAction(apply_formula_action)
        toolbar.addAction(delete_rows_action)
        self.addToolBar(toolbar)

        self._export_action = export_action
        self._delete_rows_action = delete_rows_action
        self._add_column_action = add_column_action
        self._apply_formula_action = apply_formula_action
        self._update_dataset_summary()

    def _import_data_file(self) -> None:
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Data File",
            "",
            "Data Files (*.csv *.txt);;CSV Files (*.csv);;Text Files (*.txt);;All Files (*)",
        )
        if not file_name:
            return

        dialog = ImportOptionsDialog(self)
        if dialog.exec() != ImportOptionsDialog.Accepted:
            return

        path = Path(file_name)
        try:
            frame = read_tabular_file(path, dialog.options())
            dataset = self._workspace.add_dataset(path.stem, frame, source_path=path)
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", str(exc))
            self.statusBar().showMessage("Import failed")
            return

        self._refresh_dataset_list(dataset.name)
        self.statusBar().showMessage(
            f"Imported {dataset.name}: {len(dataset.frame)} rows, {len(dataset.frame.columns)} columns"
        )

    def _add_manual_dataset(self, name: str, frame: object) -> None:
        if not isinstance(frame, pd.DataFrame):
            QMessageBox.critical(self, "Manual Entry Error", "Manual entry did not produce a DataFrame.")
            return

        try:
            dataset = self._workspace.add_dataset(name, frame)
        except Exception as exc:
            QMessageBox.critical(self, "Manual Entry Error", str(exc))
            return

        self._refresh_dataset_list(dataset.name)
        self.statusBar().showMessage(
            f"Saved {dataset.name}: {len(dataset.frame)} rows, {len(dataset.frame.columns)} columns"
        )

    def _refresh_plot_controls(self, selected_dataset: str | None = None) -> None:
        if not hasattr(self, "_plot_x_dataset_combo"):
            return

        dataset_names = self._workspace.dataset_names()
        self._set_combo_items(self._plot_x_dataset_combo, dataset_names, selected_dataset)
        self._set_combo_items(self._plot_y_dataset_combo, dataset_names, selected_dataset)
        self._update_plot_column_combo(self._plot_x_dataset_combo, self._plot_x_column_combo)
        self._update_plot_column_combo(self._plot_y_dataset_combo, self._plot_y_column_combo)
        self._set_plot_controls_enabled(bool(dataset_names))

    def _update_plot_column_combo(self, dataset_combo: QComboBox, column_combo: QComboBox) -> None:
        dataset_name = dataset_combo.currentText()
        column_names: list[str] = []

        if dataset_name:
            try:
                dataset = self._workspace.get_dataset(dataset_name)
            except KeyError:
                dataset = None
            if dataset is not None:
                column_names = [str(column) for column in dataset.frame.columns]

        self._set_combo_items(column_combo, column_names)
        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))

    def _set_combo_items(
        self,
        combo: QComboBox,
        items: list[str],
        preferred_item: str | None = None,
    ) -> None:
        current_text = preferred_item or combo.currentText()

        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if current_text and current_text in items:
            combo.setCurrentText(current_text)
        combo.blockSignals(False)

    def _set_plot_controls_enabled(self, has_datasets: bool) -> None:
        has_x_column = self._plot_x_column_combo.count() > 0
        has_y_column = self._plot_y_column_combo.count() > 0
        can_add_series = has_datasets and has_x_column and has_y_column

        self._add_series_button.setEnabled(can_add_series)
        self._remove_series_button.setEnabled(bool(self._plot_series_list.selectedItems()))
        self._clear_series_button.setEnabled(bool(self._plot_series))
        self._render_plot_button.setEnabled(bool(self._plot_series))

    def _add_plot_series(self) -> None:
        if self._plot_x_column_combo.count() == 0 or self._plot_y_column_combo.count() == 0:
            QMessageBox.information(self, "Add Series", "Import or create a dataset before adding a series.")
            return

        series = PlotSeries(
            x_dataset=self._plot_x_dataset_combo.currentText(),
            x_column=self._plot_x_column_combo.currentText(),
            y_dataset=self._plot_y_dataset_combo.currentText(),
            y_column=self._plot_y_column_combo.currentText(),
            color=str(self._plot_color_combo.currentData() or ""),
            line_style=str(self._plot_line_style_combo.currentData() or "-"),
            marker=str(self._plot_marker_combo.currentData() or ""),
            y_axis=str(self._plot_y_axis_combo.currentData() or "left"),
        )
        self._plot_series.append(series)
        self._plot_series_list.addItem(self._plot_series_text(series))
        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot()

    def _remove_selected_plot_series(self) -> None:
        selected_rows = sorted(
            {index.row() for index in self._plot_series_list.selectedIndexes()},
            reverse=True,
        )
        for row_index in selected_rows:
            self._plot_series.pop(row_index)
            self._plot_series_list.takeItem(row_index)

        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _clear_plot_series(self) -> None:
        self._plot_series.clear()
        self._plot_series_list.clear()
        self._plot_canvas.clear_plot()
        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        self.statusBar().showMessage("Cleared plot series")

    def _render_plot(self, silent_if_empty: bool = False) -> None:
        if not self._plot_series:
            self._plot_canvas.clear_plot()
            self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
            if not silent_if_empty:
                QMessageBox.information(self, "Plot", "Add at least one series before plotting.")
            return

        x_label = self._plot_x_label_edit.text().strip()
        y_label = self._plot_y_label_edit.text().strip()
        right_y_label = self._plot_right_y_label_edit.text().strip()
        if len(self._plot_series) == 1:
            x_label = x_label or self._plot_series[0].x_column
            if self._plot_series[0].y_axis == "right":
                right_y_label = right_y_label or self._plot_series[0].y_column
            else:
                y_label = y_label or self._plot_series[0].y_column

        parsed_inputs, input_errors = self._plot_inputs()
        if input_errors:
            QMessageBox.warning(self, "Plot Settings", "\n".join(input_errors))
            return

        result = self._plot_canvas.plot_series(
            workspace=self._workspace,
            series_list=self._plot_series,
            title=self._plot_title_edit.text().strip(),
            x_label=x_label,
            y_label=y_label,
            right_y_label=right_y_label,
            **parsed_inputs,
            figure_width=self._plot_width_spin.value(),
            figure_height=self._plot_height_spin.value(),
        )

        if result.skipped_messages and result.plotted_count == 0:
            QMessageBox.warning(self, "Plot Failed", "\n".join(result.skipped_messages[:5]))
        elif result.skipped_messages:
            self.statusBar().showMessage(
                f"Plotted {result.plotted_count} series; skipped {len(result.skipped_messages)}"
            )
        else:
            self.statusBar().showMessage(f"Plotted {result.plotted_count} series")

        self._tabs.setCurrentWidget(self._plot_tab)

    def _plot_series_text(self, series: PlotSeries) -> str:
        style_bits = [
            self._plot_line_style_combo.currentText(),
            self._plot_marker_combo.currentText(),
            self._plot_color_combo.currentText(),
            f"{series.y_axis} axis",
        ]
        return f"{series.label} ({', '.join(style_bits)})"

    def _plot_inputs(self) -> tuple[dict[str, object], list[str]]:
        errors: list[str] = []
        x_limits, x_errors = self._parse_range(
            self._plot_x_min_edit,
            self._plot_x_max_edit,
            "X range",
        )
        y_limits, y_errors = self._parse_range(
            self._plot_y_min_edit,
            self._plot_y_max_edit,
            "Left Y range",
        )
        right_y_limits, right_y_errors = self._parse_range(
            self._plot_right_y_min_edit,
            self._plot_right_y_max_edit,
            "Right Y range",
        )
        errors.extend(x_errors)
        errors.extend(y_errors)
        errors.extend(right_y_errors)

        vertical_guides, guide_errors = self._parse_float_list(
            self._plot_x_guides_edit.text(),
            "X guides",
        )
        y_guides, left_guide_errors = self._parse_float_list(
            self._plot_y_guides_edit.text(),
            "Left Y guides",
        )
        right_y_guides, right_guide_errors = self._parse_float_list(
            self._plot_right_y_guides_edit.text(),
            "Right Y guides",
        )
        errors.extend(guide_errors)
        errors.extend(left_guide_errors)
        errors.extend(right_guide_errors)

        return (
            {
                "x_scale": self._plot_x_scale_combo.currentText(),
                "y_scale": self._plot_y_scale_combo.currentText(),
                "right_y_scale": self._plot_right_y_scale_combo.currentText(),
                "x_limits": x_limits,
                "y_limits": y_limits,
                "right_y_limits": right_y_limits,
                "grid_enabled": self._plot_grid_checkbox.isChecked(),
                "vertical_guides": vertical_guides,
                "y_guides": y_guides,
                "right_y_guides": right_y_guides,
            },
            errors,
        )

    def _parse_range(
        self,
        minimum_edit: QLineEdit,
        maximum_edit: QLineEdit,
        label: str,
    ) -> tuple[tuple[float | None, float | None], list[str]]:
        minimum, minimum_errors = self._parse_optional_float(minimum_edit.text(), f"{label} minimum")
        maximum, maximum_errors = self._parse_optional_float(maximum_edit.text(), f"{label} maximum")
        errors = minimum_errors + maximum_errors

        if minimum is not None and maximum is not None and minimum >= maximum:
            errors.append(f"{label}: minimum must be smaller than maximum.")

        return (minimum, maximum), errors

    def _parse_optional_float(self, text: str, label: str) -> tuple[float | None, list[str]]:
        stripped = text.strip()
        if not stripped:
            return None, []

        try:
            return float(stripped), []
        except ValueError:
            return None, [f"{label} must be numeric."]

    def _parse_float_list(self, text: str, label: str) -> tuple[list[float], list[str]]:
        stripped = text.strip()
        if not stripped:
            return [], []

        values: list[float] = []
        errors: list[str] = []
        for item in stripped.split(","):
            clean_item = item.strip()
            if not clean_item:
                continue
            try:
                values.append(float(clean_item))
            except ValueError:
                errors.append(f"{label}: '{clean_item}' is not numeric.")

        return values, errors

    def _export_current_dataset(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Export Sheet", "Select a dataset before exporting.")
            return

        default_name = f"{dataset.name}.csv"
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Sheet",
            default_name,
            "CSV Files (*.csv);;Tab-delimited Text Files (*.txt);;All Files (*)",
        )
        if not file_name:
            return

        path = self._path_with_export_suffix(Path(file_name), selected_filter)
        delimiter = "\t" if path.suffix.lower() == ".txt" else ","

        try:
            export_tabular_file(dataset.frame, path, delimiter=delimiter)
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            self.statusBar().showMessage("Export failed")
            return

        self.statusBar().showMessage(f"Exported {dataset.name} to {path}")

    def _add_empty_column(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Add Column", "Select a dataset before adding a column.")
            return

        column_name, accepted = QInputDialog.getText(
            self,
            "Add Column",
            "Column name",
            text="New Column",
        )
        if not accepted:
            return

        try:
            final_name = self._dataset_model.add_empty_column(column_name)
        except Exception as exc:
            QMessageBox.critical(self, "Add Column Failed", str(exc))
            return

        self._refresh_plot_controls(dataset.name)
        self._update_dataset_summary()
        self._select_column(final_name)
        self.statusBar().showMessage(f"Added column '{final_name}' to {dataset.name}")

    def _apply_column_formula(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Apply Formula", "Select a dataset before applying a formula.")
            return

        selected_rows = self._selected_dataset_rows()
        dialog = ColumnExpressionDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            selected_rows_available=bool(selected_rows),
            default_target=self._default_formula_target(dataset),
            column_formulas=dataset.formulas,
            parent=self,
        )
        if dialog.exec() != ColumnExpressionDialog.Accepted:
            return

        row_positions = selected_rows if dialog.apply_selected_rows_only() else None

        try:
            result = self._dataset_model.apply_expression(
                target_column=dialog.target_column(),
                expression=dialog.expression(),
                row_positions=row_positions,
            )
        except ExpressionError as exc:
            QMessageBox.warning(self, "Formula Error", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Formula Failed", str(exc))
            return

        self._dataset_table.resizeColumnsToContents()
        self._refresh_plot_controls(dataset.name)
        self._update_dataset_summary()
        self._select_column(result.target_column)
        self.statusBar().showMessage(
            f"Updated {result.updated_rows} row(s) in '{result.target_column}'"
        )

    def _delete_selected_rows(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Delete Rows", "Select a dataset before deleting rows.")
            return

        selected_rows = self._selected_dataset_rows()
        if not selected_rows:
            QMessageBox.information(self, "Delete Rows", "Select one or more cells in the rows to delete.")
            return

        reply = QMessageBox.question(
            self,
            "Delete Rows",
            f"Delete {len(selected_rows)} selected row(s) from '{dataset.name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        deleted_count = self._dataset_model.delete_rows(selected_rows)
        self._update_dataset_summary()
        self.statusBar().showMessage(f"Deleted {deleted_count} row(s) from {dataset.name}")

    def _refresh_dataset_list(self, selected_name: str | None = None) -> None:
        self._dataset_list.blockSignals(True)
        self._dataset_list.clear()
        self._dataset_list.addItems(self._workspace.dataset_names())
        self._dataset_list.blockSignals(False)

        if selected_name:
            matches = self._dataset_list.findItems(selected_name, Qt.MatchExactly)
            if matches:
                self._dataset_list.setCurrentItem(matches[0])
                self._show_dataset_editor(selected_name)

        self._refresh_plot_controls(selected_name)

    def _show_dataset_editor(self, dataset_name: str) -> None:
        if not dataset_name:
            self._dataset_model.set_dataset(None)
            self._update_dataset_summary()
            return

        dataset = self._workspace.get_dataset(dataset_name)
        self._dataset_model.set_dataset(dataset)
        self._dataset_table.resizeColumnsToContents()
        self._update_dataset_summary()
        self._tabs.setCurrentIndex(0)

    def _edit_dataset_cell(self, index: QModelIndex) -> None:
        self._dataset_table.edit(index)

    def _current_dataset(self) -> Dataset | None:
        current_item = self._dataset_list.currentItem()
        if current_item is None:
            return None

        try:
            return self._workspace.get_dataset(current_item.text())
        except KeyError:
            return None

    def _selected_dataset_rows(self) -> list[int]:
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return []

        return sorted({index.row() for index in selection_model.selectedIndexes()})

    def _update_dataset_summary(self) -> None:
        dataset = self._dataset_model.dataset
        has_dataset = dataset is not None

        if not has_dataset:
            self._dataset_summary.setText("No dataset selected")
        else:
            formula_count = len(dataset.formulas)
            formula_text = f", {formula_count} formula column(s)" if formula_count else ""
            self._dataset_summary.setText(
                f"{dataset.name}: {len(dataset.frame)} rows, {len(dataset.frame.columns)} columns{formula_text}"
            )

        self._export_action.setEnabled(has_dataset)
        self._delete_rows_action.setEnabled(has_dataset)
        self._add_column_action.setEnabled(has_dataset)
        self._apply_formula_action.setEnabled(has_dataset)

    def _path_with_export_suffix(self, path: Path, selected_filter: str) -> Path:
        if path.suffix:
            return path

        if "Text" in selected_filter:
            return path.with_suffix(".txt")
        return path.with_suffix(".csv")

    def _default_formula_target(self, dataset: Dataset) -> str:
        selected_columns = self._selected_dataset_columns()
        if len(selected_columns) == 1:
            return str(dataset.frame.columns[selected_columns[0]])
        return "Result"

    def _selected_dataset_columns(self) -> list[int]:
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return []

        return sorted({index.column() for index in selection_model.selectedIndexes()})

    def _select_column(self, column_name: str) -> None:
        dataset = self._current_dataset()
        if dataset is None or column_name not in dataset.frame.columns:
            return

        column_index = list(dataset.frame.columns).index(column_name)
        if len(dataset.frame) == 0:
            return

        self._dataset_table.clearSelection()
        target_index = self._dataset_model.index(0, column_index)
        self._dataset_table.setCurrentIndex(target_index)
        self._dataset_table.selectColumn(column_index)
