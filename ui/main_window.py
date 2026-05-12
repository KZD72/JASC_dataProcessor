"""Main application window for the JASC Data Processor."""

from __future__ import annotations

import re
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
from math_engine.calculus import (
    DERIVATIVE_METHODS,
    INTEGRATION_METHODS,
    MathOperationError,
    derivative_column,
    fft_dataset,
    ifft_dataset,
    integral_column,
)
from math_engine.curve_fitting import fit_curve
from ui.data_table import DataTableWidget
from ui.dataframe_model import DataFrameTableModel
from ui.dialogs import (
    ColumnExpressionDialog,
    ColumnMathDialog,
    FFTDialog,
    FitDialog,
    FitReportDialog,
    IFFTDialog,
    ImportOptionsDialog,
)
from ui.plot_canvas import LocatedPoint, PlotCanvas, PlotLocator, PlotSeries


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
        self._plot_locators: list[PlotLocator] = []
        self._plot_canvas = PlotCanvas()

        self._manual_table = DataTableWidget()
        self._manual_table.dataset_submitted.connect(self._add_manual_dataset)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_dataset_editor(), "Data Editor")
        self._tabs.addTab(self._build_plot_tab(), "Plot")

        sidebar = self._build_sidebar()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 720])

        self.setCentralWidget(splitter)
        self._create_actions()
        self.statusBar().showMessage("Ready")

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setMinimumWidth(320)

        self._data_input_tabs = QTabWidget()
        self._data_input_tabs.addTab(self._build_import_panel(), "Import")
        self._data_input_tabs.addTab(self._manual_table, "Manual Entry")

        layout = QVBoxLayout(sidebar)
        layout.addWidget(QLabel("Workspace Datasheets"))
        layout.addWidget(self._dataset_list, 2)
        layout.addWidget(self._data_input_tabs, 3)
        return sidebar

    def _build_import_panel(self) -> QWidget:
        panel = QWidget()

        import_button = QPushButton("Import Data...")
        import_button.clicked.connect(self._import_data_file)

        hint = QLabel("Load CSV or TXT files into the workspace.")
        hint.setWordWrap(True)

        layout = QVBoxLayout(panel)
        layout.addWidget(import_button)
        layout.addWidget(hint)
        layout.addStretch(1)
        return panel

    def _build_dataset_editor(self) -> QWidget:
        editor = QWidget()

        add_column_button = QPushButton("Add Column")
        add_column_button.clicked.connect(self._add_empty_column)

        apply_formula_button = QPushButton("Apply Formula")
        apply_formula_button.clicked.connect(self._apply_column_formula)

        self._derivative_button = QPushButton("Derivative")
        self._derivative_button.clicked.connect(self._run_derivative)

        self._integral_button = QPushButton("Integral")
        self._integral_button.clicked.connect(self._run_integral)

        self._fft_button = QPushButton("FFT")
        self._fft_button.clicked.connect(self._run_fft)

        self._ifft_button = QPushButton("iFFT")
        self._ifft_button.clicked.connect(self._run_ifft)

        self._fit_button = QPushButton("Fit Curve")
        self._fit_button.clicked.connect(self._run_curve_fit)

        self._delete_rows_button = QPushButton("Delete Selected Rows")
        self._delete_rows_button.clicked.connect(self._delete_selected_rows)

        self._delete_columns_button = QPushButton("Delete Selected Columns")
        self._delete_columns_button.clicked.connect(self._delete_selected_columns)

        export_button = QPushButton("Export Sheet")
        export_button.clicked.connect(self._export_current_dataset)

        controls = QHBoxLayout()
        controls.addWidget(self._dataset_summary)
        controls.addStretch(1)
        controls.addWidget(add_column_button)
        controls.addWidget(apply_formula_button)
        controls.addWidget(self._derivative_button)
        controls.addWidget(self._integral_button)
        controls.addWidget(self._fft_button)
        controls.addWidget(self._ifft_button)
        controls.addWidget(self._fit_button)
        controls.addWidget(self._delete_rows_button)
        controls.addWidget(self._delete_columns_button)
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

        self._plot_locator_series_combo = QComboBox()
        self._plot_locator_x_edit = QLineEdit()
        self._plot_locator_x_edit.setPlaceholderText("X value")

        self._plot_locator_marker_combo = QComboBox()
        self._plot_locator_marker_combo.addItem("Circle", "o")
        self._plot_locator_marker_combo.addItem("Square", "s")
        self._plot_locator_marker_combo.addItem("Triangle", "^")
        self._plot_locator_marker_combo.addItem("Diamond", "D")
        self._plot_locator_marker_combo.addItem("Cross", "x")
        self._plot_locator_marker_combo.addItem("Plus", "+")
        self._plot_locator_marker_combo.addItem("Star", "*")
        self._plot_locator_marker_combo.addItem("Dot", ".")

        self._plot_locator_color_combo = QComboBox()
        self._plot_locator_color_combo.addItem("Red", "tab:red")
        self._plot_locator_color_combo.addItem("Blue", "tab:blue")
        self._plot_locator_color_combo.addItem("Orange", "tab:orange")
        self._plot_locator_color_combo.addItem("Green", "tab:green")
        self._plot_locator_color_combo.addItem("Purple", "tab:purple")
        self._plot_locator_color_combo.addItem("Black", "black")

        self._plot_locator_size_spin = QDoubleSpinBox()
        self._plot_locator_size_spin.setRange(10.0, 500.0)
        self._plot_locator_size_spin.setSingleStep(10.0)
        self._plot_locator_size_spin.setValue(80.0)
        self._plot_locator_size_spin.setSuffix(" pt")

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

        self._plot_locator_list = QListWidget()
        self._plot_locator_list.itemSelectionChanged.connect(
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

        self._add_locator_button = QPushButton("Add Locator")
        self._add_locator_button.clicked.connect(self._add_plot_locator)

        self._remove_locator_button = QPushButton("Remove Locator")
        self._remove_locator_button.clicked.connect(self._remove_selected_plot_locator)

        self._clear_locators_button = QPushButton("Clear")
        self._clear_locators_button.clicked.connect(self._clear_plot_locators)

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

        locator_group = QGroupBox("Data Location")
        locator_form = QFormLayout(locator_group)
        locator_form.addRow("Series", self._plot_locator_series_combo)
        locator_form.addRow("X value", self._plot_locator_x_edit)
        locator_form.addRow("Marker", self._plot_locator_marker_combo)
        locator_form.addRow("Size", self._plot_locator_size_spin)
        locator_form.addRow("Color", self._plot_locator_color_combo)

        locator_buttons = QHBoxLayout()
        locator_buttons.addWidget(self._add_locator_button)
        locator_buttons.addWidget(self._remove_locator_button)
        locator_buttons.addWidget(self._clear_locators_button)
        locator_form.addRow(locator_buttons)
        locator_form.addRow("Located", self._plot_locator_list)

        self._plot_control_tabs = QTabWidget()
        self._plot_control_tabs.addTab(series_group, "Series")
        self._plot_control_tabs.addTab(labels_group, "Axes")
        self._plot_control_tabs.addTab(locator_group, "Locator")

        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        control_layout.addWidget(self._plot_control_tabs)
        control_layout.addStretch(1)
        control_layout.addWidget(self._render_plot_button)

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

        delete_columns_action = edit_menu.addAction("Delete Selected &Columns")
        delete_columns_action.triggered.connect(self._delete_selected_columns)

        data_menu = self.menuBar().addMenu("&Data")
        add_column_action = data_menu.addAction("&Add Column...")
        add_column_action.triggered.connect(self._add_empty_column)

        apply_formula_action = data_menu.addAction("&Apply Formula...")
        apply_formula_action.setShortcut("Ctrl+Shift+F")
        apply_formula_action.triggered.connect(self._apply_column_formula)

        analysis_menu = self.menuBar().addMenu("&Analysis")
        derivative_action = analysis_menu.addAction("&Derivative...")
        derivative_action.triggered.connect(self._run_derivative)

        integral_action = analysis_menu.addAction("&Integral...")
        integral_action.triggered.connect(self._run_integral)

        fft_action = analysis_menu.addAction("&FFT...")
        fft_action.triggered.connect(self._run_fft)

        ifft_action = analysis_menu.addAction("&Inverse FFT...")
        ifft_action.triggered.connect(self._run_ifft)

        fit_action = analysis_menu.addAction("&Curve Fit...")
        fit_action.setShortcut("Ctrl+Shift+C")
        fit_action.triggered.connect(self._run_curve_fit)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.addAction(export_action)
        toolbar.addAction(add_column_action)
        toolbar.addAction(apply_formula_action)
        toolbar.addAction(derivative_action)
        toolbar.addAction(integral_action)
        toolbar.addAction(fft_action)
        toolbar.addAction(ifft_action)
        toolbar.addAction(fit_action)
        toolbar.addAction(delete_rows_action)
        toolbar.addAction(delete_columns_action)
        self.addToolBar(toolbar)

        self._export_action = export_action
        self._delete_rows_action = delete_rows_action
        self._delete_columns_action = delete_columns_action
        self._add_column_action = add_column_action
        self._apply_formula_action = apply_formula_action
        self._derivative_action = derivative_action
        self._integral_action = integral_action
        self._fft_action = fft_action
        self._ifft_action = ifft_action
        self._fit_action = fit_action
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
        self._add_locator_button.setEnabled(bool(self._plot_series))
        self._remove_locator_button.setEnabled(bool(self._plot_locator_list.selectedItems()))
        self._clear_locators_button.setEnabled(bool(self._plot_locators))

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
        self._refresh_locator_series_combo()
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

        self._reindex_plot_locators_after_series_removal(selected_rows)
        self._refresh_locator_series_combo()
        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _clear_plot_series(self) -> None:
        self._plot_series.clear()
        self._plot_series_list.clear()
        self._plot_locators.clear()
        self._plot_locator_list.clear()
        self._refresh_locator_series_combo()
        self._plot_canvas.clear_plot()
        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        self.statusBar().showMessage("Cleared plot series")

    def _add_plot_locator(self) -> None:
        if not self._plot_series:
            QMessageBox.information(self, "Add Locator", "Add a plotted series before locating data.")
            return

        x_value, errors = self._parse_optional_float(self._plot_locator_x_edit.text(), "Locator X value")
        if errors or x_value is None:
            QMessageBox.warning(self, "Add Locator", "\n".join(errors or ["Locator X value is required."]))
            return

        series_index = self._plot_locator_series_combo.currentData()
        if not isinstance(series_index, int) or not 0 <= series_index < len(self._plot_series):
            QMessageBox.warning(self, "Add Locator", "Choose a valid queued series.")
            return

        locator = PlotLocator(
            series_index=series_index,
            x_value=x_value,
            marker=str(self._plot_locator_marker_combo.currentData() or "o"),
            size=self._plot_locator_size_spin.value(),
            color=str(self._plot_locator_color_combo.currentData() or "tab:red"),
        )
        self._plot_locators.append(locator)
        self._plot_locator_list.addItem(self._plot_locator_text(locator))
        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot()

    def _remove_selected_plot_locator(self) -> None:
        selected_rows = sorted(
            {index.row() for index in self._plot_locator_list.selectedIndexes()},
            reverse=True,
        )
        for row_index in selected_rows:
            self._plot_locators.pop(row_index)
            self._plot_locator_list.takeItem(row_index)

        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _clear_plot_locators(self) -> None:
        self._plot_locators.clear()
        self._plot_locator_list.clear()
        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

    def _refresh_locator_series_combo(self) -> None:
        if not hasattr(self, "_plot_locator_series_combo"):
            return

        current_index = self._plot_locator_series_combo.currentData()
        self._plot_locator_series_combo.blockSignals(True)
        self._plot_locator_series_combo.clear()
        for series_index, series in enumerate(self._plot_series):
            self._plot_locator_series_combo.addItem(
                f"{series_index + 1}: {series.label}",
                series_index,
            )
        if isinstance(current_index, int):
            combo_index = self._plot_locator_series_combo.findData(current_index)
            if combo_index >= 0:
                self._plot_locator_series_combo.setCurrentIndex(combo_index)
        self._plot_locator_series_combo.blockSignals(False)

    def _reindex_plot_locators_after_series_removal(self, removed_rows: list[int]) -> None:
        removed = set(removed_rows)
        reindexed_locators: list[PlotLocator] = []

        for locator in self._plot_locators:
            if locator.series_index in removed:
                continue

            shift = sum(1 for removed_index in removed if removed_index < locator.series_index)
            reindexed_locators.append(
                PlotLocator(
                    series_index=locator.series_index - shift,
                    x_value=locator.x_value,
                    marker=locator.marker,
                    size=locator.size,
                    color=locator.color,
                )
            )

        self._plot_locators = reindexed_locators
        self._refresh_locator_list()

    def _refresh_locator_list(self, located_points: list[LocatedPoint] | None = None) -> None:
        located_by_index = {
            located_point.locator_index: located_point for located_point in located_points or []
        }

        self._plot_locator_list.clear()
        for locator_index, locator in enumerate(self._plot_locators):
            self._plot_locator_list.addItem(
                self._plot_locator_text(locator, located_by_index.get(locator_index))
            )

    def _plot_locator_text(
        self,
        locator: PlotLocator,
        located_point: LocatedPoint | None = None,
    ) -> str:
        series_label = self._plot_series[locator.series_index].label
        if located_point is not None:
            return (
                f"{series_label}: x={located_point.x_value:g}, "
                f"y={located_point.y_value:g} ({located_point.y_axis})"
            )

        return f"{series_label}: x={locator.x_value:g} (pending)"

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
        self._refresh_locator_list(result.located_points)

        if result.skipped_messages and result.plotted_count == 0:
            QMessageBox.warning(self, "Plot Failed", "\n".join(result.skipped_messages[:5]))
        elif result.skipped_messages:
            self.statusBar().showMessage(
                f"Plotted {result.plotted_count} series; skipped {len(result.skipped_messages)}"
            )
        elif result.located_points:
            self.statusBar().showMessage(
                f"Plotted {result.plotted_count} series; located {len(result.located_points)} point(s)"
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

        return (
            {
                "x_scale": self._plot_x_scale_combo.currentText(),
                "y_scale": self._plot_y_scale_combo.currentText(),
                "right_y_scale": self._plot_right_y_scale_combo.currentText(),
                "x_limits": x_limits,
                "y_limits": y_limits,
                "right_y_limits": right_y_limits,
                "grid_enabled": self._plot_grid_checkbox.isChecked(),
                "locators": self._plot_locators,
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

    def _parse_float_sequence(self, text: str, label: str) -> tuple[list[float] | None, list[str]]:
        stripped = text.strip()
        if not stripped:
            return None, []

        values: list[float] = []
        for token in re.split(r"[\s,;]+", stripped):
            if not token:
                continue
            try:
                values.append(float(token))
            except ValueError:
                return None, [f"{label} contains a non-numeric value: {token}"]

        if not values:
            return None, []
        return values, []

    def _queue_fit_plot(
        self,
        source_dataset: Dataset,
        fit_dataset: Dataset,
        x_column: str,
        y_column: str,
        model_name: str,
    ) -> None:
        self._plot_series = [
            PlotSeries(
                x_dataset=source_dataset.name,
                x_column=x_column,
                y_dataset=source_dataset.name,
                y_column=y_column,
                color="tab:blue",
                line_style="",
                marker="o",
            ),
            PlotSeries(
                x_dataset=fit_dataset.name,
                x_column="fit_x",
                y_dataset=fit_dataset.name,
                y_column="fit_y",
                color="tab:red",
                line_style="-",
                marker="",
            ),
        ]
        self._plot_locators.clear()
        self._plot_series_list.clear()
        self._plot_locator_list.clear()
        for series in self._plot_series:
            self._plot_series_list.addItem(self._plot_series_text(series))
        self._refresh_locator_series_combo()
        self._plot_title_edit.setText(f"{model_name} fit")
        self._plot_x_label_edit.setText(x_column)
        self._plot_y_label_edit.setText(y_column)
        self._refresh_plot_controls(fit_dataset.name)
        self._set_plot_controls_enabled(bool(self._workspace.dataset_names()))
        self._render_plot(silent_if_empty=True)

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

    def _run_derivative(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Derivative", "Select a dataset before calculating a derivative.")
            return

        dialog = ColumnMathDialog(
            operation_name="Derivative",
            column_names=[str(column) for column in dataset.frame.columns],
            methods=DERIVATIVE_METHODS,
            default_target="Derivative",
            parent=self,
        )
        if dialog.exec() != ColumnMathDialog.Accepted:
            return

        try:
            result = derivative_column(
                dataset.frame,
                x_column=dialog.x_column(),
                y_column=dialog.y_column(),
                method=dialog.method(),
                target_column=dialog.target_column(),
            )
        except MathOperationError as exc:
            QMessageBox.warning(self, "Derivative Failed", str(exc))
            return

        self._refresh_dataset_after_analysis(dataset, result.column_name)
        self.statusBar().showMessage(
            f"Derivative saved to '{result.column_name}' ({result.values_written} values)"
        )

    def _run_integral(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Integral", "Select a dataset before calculating an integral.")
            return

        dialog = ColumnMathDialog(
            operation_name="Integral",
            column_names=[str(column) for column in dataset.frame.columns],
            methods=INTEGRATION_METHODS,
            default_target="Integral",
            include_initial_value=True,
            parent=self,
        )
        if dialog.exec() != ColumnMathDialog.Accepted:
            return

        initial_value, initial_errors = self._parse_optional_float(
            dialog.initial_value_text(),
            "Integral initial value",
        )
        if initial_errors:
            QMessageBox.warning(self, "Integral Failed", "\n".join(initial_errors))
            return

        try:
            result = integral_column(
                dataset.frame,
                x_column=dialog.x_column(),
                y_column=dialog.y_column(),
                method=dialog.method(),
                target_column=dialog.target_column(),
                initial_value=initial_value or 0.0,
            )
        except MathOperationError as exc:
            QMessageBox.warning(self, "Integral Failed", str(exc))
            return

        self._refresh_dataset_after_analysis(dataset, result.column_name)
        self.statusBar().showMessage(
            f"Integral saved to '{result.column_name}' ({result.values_written} values)"
        )

    def _run_fft(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "FFT", "Select a dataset before running FFT.")
            return

        dialog = FFTDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_dataset_name=dataset.name,
            parent=self,
        )
        if dialog.exec() != FFTDialog.Accepted:
            return

        try:
            result_frame = fft_dataset(
                dataset.frame,
                signal_column=dialog.signal_column(),
                x_column=dialog.x_column(),
                window_method=dialog.window_method(),
            )
            result_dataset = self._workspace.add_dataset(
                dialog.target_dataset_name() or f"{dataset.name}_FFT",
                result_frame,
            )
        except MathOperationError as exc:
            QMessageBox.warning(self, "FFT Failed", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "FFT Failed", str(exc))
            return

        self._refresh_dataset_list(result_dataset.name)
        self.statusBar().showMessage(
            f"FFT saved as '{result_dataset.name}' ({len(result_dataset.frame)} rows)"
        )

    def _run_ifft(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Inverse FFT", "Select a dataset before running inverse FFT.")
            return

        dialog = IFFTDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_dataset_name=dataset.name,
            parent=self,
        )
        if dialog.exec() != IFFTDialog.Accepted:
            return

        try:
            result_frame = ifft_dataset(
                dataset.frame,
                real_column=dialog.real_column(),
                imaginary_column=dialog.imaginary_column(),
            )
            result_dataset = self._workspace.add_dataset(
                dialog.target_dataset_name() or f"{dataset.name}_iFFT",
                result_frame,
            )
        except MathOperationError as exc:
            QMessageBox.warning(self, "Inverse FFT Failed", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Inverse FFT Failed", str(exc))
            return

        self._refresh_dataset_list(result_dataset.name)
        self.statusBar().showMessage(
            f"Inverse FFT saved as '{result_dataset.name}' ({len(result_dataset.frame)} rows)"
        )

    def _run_curve_fit(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Curve Fit", "Select a dataset before fitting a curve.")
            return

        dialog = FitDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_dataset_name=dataset.name,
            parent=self,
        )
        if dialog.exec() != FitDialog.Accepted:
            return

        initial_parameters, parameter_errors = self._parse_float_sequence(
            dialog.initial_parameters_text(),
            "Initial parameters",
        )
        if parameter_errors:
            QMessageBox.warning(self, "Curve Fit Failed", "\n".join(parameter_errors))
            return

        try:
            result = fit_curve(
                dataset.frame,
                x_column=dialog.x_column(),
                y_column=dialog.y_column(),
                model_key=dialog.model_key(),
                method=dialog.method(),
                initial_parameters=initial_parameters,
                fit_points=dialog.fit_points(),
            )
            result_dataset = self._workspace.add_dataset(
                dialog.target_dataset_name() or f"{dataset.name}_fit",
                result.fit_frame,
            )
        except MathOperationError as exc:
            QMessageBox.warning(self, "Curve Fit Failed", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Curve Fit Failed", str(exc))
            return

        self._refresh_dataset_list(result_dataset.name)
        self._queue_fit_plot(
            source_dataset=dataset,
            fit_dataset=result_dataset,
            x_column=dialog.x_column(),
            y_column=dialog.y_column(),
            model_name=result.report.model_name,
        )
        FitReportDialog(result.report.to_text(), self).exec()
        self.statusBar().showMessage(
            f"Fit saved as '{result_dataset.name}' with R^2={result.report.r_squared:.5g}"
        )

    def _refresh_dataset_after_analysis(self, dataset: Dataset, selected_column: str) -> None:
        self._dataset_model.set_dataset(dataset)
        self._dataset_table.resizeColumnsToContents()
        self._refresh_plot_controls(dataset.name)
        self._update_dataset_summary()
        self._select_column(selected_column)

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

    def _delete_selected_columns(self) -> None:
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Delete Columns", "Select a dataset before deleting columns.")
            return

        selected_columns = self._selected_dataset_columns()
        if not selected_columns:
            QMessageBox.information(self, "Delete Columns", "Select one or more cells in the columns to delete.")
            return

        column_names = [str(dataset.frame.columns[column]) for column in selected_columns]
        shown_columns = ", ".join(column_names[:6])
        if len(column_names) > 6:
            shown_columns += ", ..."

        reply = QMessageBox.question(
            self,
            "Delete Columns",
            f"Delete {len(selected_columns)} selected column(s) from '{dataset.name}'?\n\n{shown_columns}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        deleted_columns = self._dataset_model.delete_columns(selected_columns)
        self._dataset_table.resizeColumnsToContents()
        self._refresh_plot_controls(dataset.name)
        self._update_dataset_summary()
        self.statusBar().showMessage(
            f"Deleted {len(deleted_columns)} column(s) from {dataset.name}"
        )

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
        self._delete_columns_action.setEnabled(has_dataset)
        self._add_column_action.setEnabled(has_dataset)
        self._apply_formula_action.setEnabled(has_dataset)
        self._derivative_action.setEnabled(has_dataset)
        self._integral_action.setEnabled(has_dataset)
        self._fft_action.setEnabled(has_dataset)
        self._ifft_action.setEnabled(has_dataset)
        self._fit_action.setEnabled(has_dataset)
        self._derivative_button.setEnabled(has_dataset)
        self._integral_button.setEnabled(has_dataset)
        self._fft_button.setEnabled(has_dataset)
        self._ifft_button.setEnabled(has_dataset)
        self._fit_button.setEnabled(has_dataset)
        self._delete_rows_button.setEnabled(has_dataset)
        self._delete_columns_button.setEnabled(has_dataset)

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
