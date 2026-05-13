"""Main application window for the JASC Data Processor."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core import project_io
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
from ui.plot_tab import PlotTab


class MainWindow(QMainWindow):
    """Primary application shell for data ingestion, editing, and plotting workflows."""

    def __init__(self) -> None:
        """Create the main window, shared workspace, and primary UI regions."""
        super().__init__()
        self._workspace = Workspace()

        self.setWindowTitle("JASC Data Processor")
        icon_path = Path(__file__).parent.parent / "resources" / "logo.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1100, 720)

        self._dataset_list = QListWidget()
        self._dataset_list.currentTextChanged.connect(self._show_dataset_editor)
        self._dataset_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._dataset_list.customContextMenuRequested.connect(self._show_dataset_context_menu)

        self._plot_list = QListWidget()
        self._plot_list.itemDoubleClicked.connect(lambda _item: self._load_selected_plot())
        self._plot_list.currentTextChanged.connect(self._handle_saved_plot_selection)
        self._plot_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._plot_list.customContextMenuRequested.connect(self._show_plot_context_menu)

        self._dataset_model = DataFrameTableModel(self)
        self._dataset_table = QTableView()
        self._dataset_table.setModel(self._dataset_model)
        self._dataset_table.setAlternatingRowColors(True)
        self._dataset_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._dataset_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._dataset_table.setSortingEnabled(False)
        self._dataset_table.doubleClicked.connect(self._edit_dataset_cell)
        self._dataset_summary = QLabel("No dataset selected")

        # Plot state moved to PlotTab

        self._manual_table = DataTableWidget()
        self._manual_table.dataset_submitted.connect(self._add_manual_dataset)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_dataset_editor(), "Data Editor")
        self._plot_tab_widget = PlotTab(self._workspace, parent=self)
        self._plot_tab_widget.status_message.connect(self.statusBar().showMessage)
        self._plot_tab_widget.plot_rendered.connect(self._update_plot_action_state)
        self._plot_tab_widget.save_plot_requested.connect(self._save_current_plot)
        self._plot_tab_widget.load_plot_requested.connect(self._load_selected_plot)
        self._plot_tab_widget.remove_plot_requested.connect(self._delete_selected_plot)
        self._plot_tab_widget.options_visibility_changed.connect(self._sync_plot_options_action)
        self._tabs.addTab(self._plot_tab_widget, "Plot")

        sidebar = self._build_sidebar()
        self._sidebar = sidebar
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 720])
        self._main_splitter = splitter

        self.setCentralWidget(splitter)
        self._create_actions()
        self._apply_visual_style()
        self.statusBar().showMessage("Ready")

    def _build_sidebar(self) -> QWidget:
        """Build the left navigation and manual data-entry sidebar."""
        sidebar = QWidget()
        sidebar.setMinimumWidth(320)

        datasheet_label = QLabel("Workspace Datasheets")
        datasheet_label.setObjectName("SectionLabel")
        plots_label = QLabel("Saved Plots")
        plots_label.setObjectName("SectionLabel")
        manual_label = QLabel("Manual Entry")
        manual_label.setObjectName("SectionLabel")

        layout = QVBoxLayout(sidebar)
        datasheet_header = QHBoxLayout()
        datasheet_header.addWidget(datasheet_label)
        datasheet_header.addStretch(1)
        self._workspace_toggle_button = QPushButton("Hide")
        self._workspace_toggle_button.clicked.connect(self._toggle_workspace_section)
        datasheet_header.addWidget(self._workspace_toggle_button)
        layout.addLayout(datasheet_header)
        layout.addWidget(self._dataset_list, 2)
        self._dataset_buttons_panel = QWidget()
        dataset_buttons = QHBoxLayout(self._dataset_buttons_panel)
        dataset_buttons.setContentsMargins(0, 0, 0, 0)
        self._rename_dataset_button = QPushButton("Rename")
        self._rename_dataset_button.clicked.connect(self._rename_current_dataset)
        self._remove_dataset_button = QPushButton("Remove")
        self._remove_dataset_button.clicked.connect(self._delete_current_dataset)
        dataset_buttons.addWidget(self._rename_dataset_button)
        dataset_buttons.addWidget(self._remove_dataset_button)
        layout.addWidget(self._dataset_buttons_panel)
        plots_header = QHBoxLayout()
        plots_header.addWidget(plots_label)
        plots_header.addStretch(1)
        self._plots_toggle_button = QPushButton("Hide")
        self._plots_toggle_button.clicked.connect(self._toggle_plots_section)
        plots_header.addWidget(self._plots_toggle_button)
        layout.addLayout(plots_header)
        layout.addWidget(self._plot_list, 1)
        layout.addWidget(manual_label)
        layout.addWidget(self._manual_table, 3)
        return sidebar

    def _build_dataset_editor(self) -> QWidget:
        """Build the central dataset table editor and local action header."""
        editor = QWidget()

        self._editor_add_row_button = QPushButton("Add Row")
        self._editor_add_row_button.clicked.connect(self._add_empty_row)
        self._editor_add_column_button = QPushButton("Add Column")
        self._editor_add_column_button.clicked.connect(self._add_empty_column)
        self._editor_delete_rows_button = QPushButton("Delete Rows")
        self._editor_delete_rows_button.clicked.connect(self._delete_selected_rows)
        self._editor_delete_columns_button = QPushButton("Delete Columns")
        self._editor_delete_columns_button.clicked.connect(self._delete_selected_columns)
        self._editor_rename_button = QPushButton("Rename")
        self._editor_rename_button.clicked.connect(self._rename_current_dataset)
        self._editor_remove_button = QPushButton("Remove")
        self._editor_remove_button.clicked.connect(self._delete_current_dataset)
        self._editor_export_button = QPushButton("Export")
        self._editor_export_button.clicked.connect(self._export_current_dataset)

        action_row = QHBoxLayout()
        action_row.addWidget(self._dataset_summary, 1)
        action_row.addWidget(self._editor_add_row_button)
        action_row.addWidget(self._editor_add_column_button)
        action_row.addWidget(self._editor_delete_rows_button)
        action_row.addWidget(self._editor_delete_columns_button)
        action_row.addWidget(self._editor_rename_button)
        action_row.addWidget(self._editor_remove_button)
        action_row.addWidget(self._editor_export_button)

        layout = QVBoxLayout(editor)
        layout.addLayout(action_row)
        layout.addWidget(self._dataset_table)
        return editor

    def _create_actions(self) -> None:
        """Create menus, toolbar actions, and long-lived action references."""
        file_menu = self.menuBar().addMenu("&File")

        open_project_action = file_menu.addAction("&Open Project...")
        open_project_action.setShortcut("Ctrl+O")
        open_project_action.triggered.connect(self._open_project)

        save_project_action = file_menu.addAction("&Save Project...")
        save_project_action.setShortcut("Ctrl+S")
        save_project_action.triggered.connect(self._save_project)

        file_menu.addSeparator()

        close_project_action = file_menu.addAction("&Close Project")
        close_project_action.setShortcut("Ctrl+W")
        close_project_action.triggered.connect(self._close_project)

        file_menu.addSeparator()

        import_action = file_menu.addAction("&Import Data...")
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self._import_data_file)

        export_action = file_menu.addAction("&Export Dataset...")
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._export_current_dataset)

        edit_menu = self.menuBar().addMenu("&Edit")
        delete_rows_action = edit_menu.addAction("&Delete Selected Rows")
        delete_rows_action.setShortcut("Del")
        delete_rows_action.triggered.connect(self._delete_selected_rows)

        delete_columns_action = edit_menu.addAction("Delete Selected &Columns")
        delete_columns_action.triggered.connect(self._delete_selected_columns)

        view_menu = self.menuBar().addMenu("&View")
        show_sidebar_action = view_menu.addAction("Show &Sidebar")
        show_sidebar_action.setCheckable(True)
        show_sidebar_action.setChecked(True)
        show_sidebar_action.toggled.connect(self._set_sidebar_visible)

        show_workspace_action = view_menu.addAction("Show &Workspace Datasheets")
        show_workspace_action.setCheckable(True)
        show_workspace_action.setChecked(True)
        show_workspace_action.toggled.connect(self._set_workspace_section_visible)

        show_plots_action = view_menu.addAction("Show Saved &Plots")
        show_plots_action.setCheckable(True)
        show_plots_action.setChecked(True)
        show_plots_action.toggled.connect(self._set_plots_section_visible)

        show_plot_options_action = view_menu.addAction("Show Plot &Options")
        show_plot_options_action.setCheckable(True)
        show_plot_options_action.setChecked(True)
        show_plot_options_action.toggled.connect(self._set_plot_options_visible_from_action)

        view_menu.addSeparator()
        reset_view_action = view_menu.addAction("&Reset View to Default")
        reset_view_action.setShortcut("Ctrl+Shift+R")
        reset_view_action.triggered.connect(self._reset_view_to_default)

        data_menu = self.menuBar().addMenu("&Data")
        rename_dataset_action = data_menu.addAction("&Rename Dataset...")
        rename_dataset_action.triggered.connect(self._rename_current_dataset)

        delete_dataset_action = data_menu.addAction("Remo&ve Dataset...")
        delete_dataset_action.triggered.connect(self._delete_current_dataset)

        data_menu.addSeparator()

        add_column_action = data_menu.addAction("&Add Column...")
        add_column_action.triggered.connect(self._add_empty_column)

        add_row_action = data_menu.addAction("Add &Row")
        add_row_action.triggered.connect(self._add_empty_row)

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

        plot_menu = self.menuBar().addMenu("&Plot")
        save_plot_action = plot_menu.addAction("&Save Current Plot...")
        save_plot_action.setShortcut("Ctrl+Shift+S")
        save_plot_action.triggered.connect(self._save_current_plot)

        load_plot_action = plot_menu.addAction("&Load Selected Plot")
        load_plot_action.triggered.connect(self._load_selected_plot)

        delete_plot_action = plot_menu.addAction("&Remove Selected Plot")
        delete_plot_action.triggered.connect(self._delete_selected_plot)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.addAction(open_project_action)
        toolbar.addAction(save_project_action)
        toolbar.addAction(close_project_action)
        toolbar.addSeparator()
        toolbar.addAction(import_action)
        
        toolbar.addSeparator()

        toolbar.addAction(apply_formula_action)
        toolbar.addAction(derivative_action)
        toolbar.addAction(integral_action)
        toolbar.addAction(fft_action)
        toolbar.addAction(ifft_action)
        toolbar.addAction(fit_action)
        self.addToolBar(toolbar)

        self._export_action = export_action
        self._delete_rows_action = delete_rows_action
        self._delete_columns_action = delete_columns_action
        self._rename_dataset_action = rename_dataset_action
        self._delete_dataset_action = delete_dataset_action
        self._add_column_action = add_column_action
        self._apply_formula_action = apply_formula_action
        self._derivative_action = derivative_action
        self._integral_action = integral_action
        self._fft_action = fft_action
        self._ifft_action = ifft_action
        self._fit_action = fit_action
        self._close_project_action = close_project_action
        self._save_plot_action = save_plot_action
        self._load_plot_action = load_plot_action
        self._delete_plot_action = delete_plot_action
        self._add_row_action = add_row_action
        self._show_sidebar_action = show_sidebar_action
        self._show_workspace_action = show_workspace_action
        self._show_plots_action = show_plots_action
        self._show_plot_options_action = show_plot_options_action
        self._update_dataset_summary()

    def _apply_visual_style(self) -> None:
        """Apply the application-wide Qt stylesheet."""
        self.setStyleSheet("""
            QMainWindow {
                background: #f4f7fa;
            }
            QMenuBar {
                background: #ffffff;
                border-bottom: 1px solid #c7d0da;
                padding: 2px 4px;
            }
            QMenuBar::item:selected, QMenu::item:selected {
                background: #d8e8ff;
                color: #102a43;
            }
            QToolBar {
                background: #edf2f7;
                border-bottom: 1px solid #c7d0da;
                spacing: 4px;
                padding: 4px;
            }
            QToolButton, QPushButton {
                background: #ffffff;
                border: 1px solid #aeb9c5;
                border-radius: 4px;
                color: #182430;
                padding: 5px 10px;
            }
            QToolButton:hover, QPushButton:hover {
                background: #eaf3ff;
                border-color: #5c8fc7;
            }
            QToolButton:pressed, QPushButton:pressed {
                background: #cfe3fb;
                border-color: #2f6fae;
                padding-top: 6px;
                padding-bottom: 4px;
            }
            QToolButton:disabled, QPushButton:disabled {
                background: #eef1f4;
                border-color: #d2d8de;
                color: #8b98a5;
            }
            QLabel#SectionLabel {
                color: #263747;
                font-weight: 700;
                padding: 8px 2px 3px 2px;
            }
            QListWidget, QTableView, QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
                background: #ffffff;
                border: 1px solid #b7c1cc;
                border-radius: 4px;
                selection-background-color: #2f77bc;
                selection-color: #ffffff;
            }
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QListWidget:focus, QTableView:focus {
                border: 1px solid #2f77bc;
            }
            QListWidget::item {
                padding: 4px 6px;
                border-radius: 3px;
            }
            QListWidget::item:selected {
                background: #2f77bc;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background: #e7f1fc;
                color: #182430;
            }
            QTabWidget::pane {
                border: 1px solid #c7d0da;
                background: #ffffff;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #e6ebf1;
                border: 1px solid #c7d0da;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 6px 12px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #174f86;
                font-weight: 700;
            }
            QGroupBox {
                border: 1px solid #c3ccd6;
                border-radius: 5px;
                margin-top: 10px;
                padding: 8px;
                background: #fbfcfe;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: #263747;
                font-weight: 700;
            }
            QHeaderView::section {
                background: #edf2f7;
                border: 1px solid #c7d0da;
                padding: 4px;
                font-weight: 700;
            }
            QStatusBar {
                background: #ffffff;
                border-top: 1px solid #c7d0da;
            }
        """)

    def _import_data_file(self) -> None:
        """Open a delimited file and add it to the workspace."""
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
        """Add a manually-entered DataFrame to the workspace."""
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

    def _parse_optional_float(self, text: str, label: str) -> tuple[float | None, list[str]]:
        """Parse optional numeric dialog text and return validation errors."""
        stripped = text.strip()
        if not stripped:
            return None, []

        try:
            return float(stripped), []
        except ValueError:
            return None, [f"{label} must be numeric."]

    def _parse_float_sequence(self, text: str, label: str) -> tuple[list[float] | None, list[str]]:
        """Parse comma/space/semicolon-separated floats from dialog text."""
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

    def _export_current_dataset(self) -> None:
        """Export the selected dataset to CSV or tab-delimited text."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Export Dataset", "Select a dataset before exporting.")
            return

        default_name = f"{dataset.name}.csv"
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Dataset",
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
        """Prompt for and append an empty column to the selected dataset."""
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

        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        self._select_column(final_name)
        self.statusBar().showMessage(f"Added column '{final_name}' to {dataset.name}")

    def _add_empty_row(self) -> None:
        """Append an empty row to the selected dataset."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Add Row", "Select a dataset before adding a row.")
            return

        self._dataset_model.add_row()
        self._update_dataset_summary()
        self.statusBar().showMessage(f"Added empty row to {dataset.name}")

    def _apply_column_formula(self) -> None:
        """Apply a safe expression to all or selected rows in a column."""
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
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        self._select_column(result.target_column)
        self.statusBar().showMessage(
            f"Updated {result.updated_rows} row(s) in '{result.target_column}'"
        )

    def _run_derivative(self) -> None:
        """Run the derivative workflow for the selected dataset."""
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
        if dialog.plot_result_immediately():
            self._plot_tab_widget.queue_analysis_plot(
                dataset=dataset,
                x_column=dialog.x_column(),
                source_column=dialog.y_column(),
                result_column=result.column_name,
                title="Derivative",
            )
            self._tabs.setCurrentWidget(self._plot_tab_widget)
        self.statusBar().showMessage(
            f"Derivative saved to '{result.column_name}' ({result.values_written} values)"
        )

    def _run_integral(self) -> None:
        """Run the cumulative integration workflow for the selected dataset."""
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
        if dialog.plot_result_immediately():
            self._plot_tab_widget.queue_analysis_plot(
                dataset=dataset,
                x_column=dialog.x_column(),
                source_column=dialog.y_column(),
                result_column=result.column_name,
                title="Integral",
            )
            self._tabs.setCurrentWidget(self._plot_tab_widget)
        self.statusBar().showMessage(
            f"Integral saved to '{result.column_name}' ({result.values_written} values)"
        )

    def _run_fft(self) -> None:
        """Run the FFT workflow and create a frequency-domain dataset."""
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
        if dialog.plot_result_immediately():
            self._plot_tab_widget.queue_single_series_plot(
                dataset=result_dataset,
                x_column="frequency",
                y_column="magnitude",
                title="FFT magnitude",
                label="Magnitude",
            )
            self._tabs.setCurrentWidget(self._plot_tab_widget)
        self.statusBar().showMessage(
            f"FFT saved as '{result_dataset.name}' ({len(result_dataset.frame)} rows)"
        )

    def _run_ifft(self) -> None:
        """Run the inverse FFT workflow and create a reconstructed dataset."""
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
        if dialog.plot_result_immediately():
            self._plot_tab_widget.queue_single_series_plot(
                dataset=result_dataset,
                x_column="sample",
                y_column="real",
                title="Inverse FFT",
                label="Reconstructed real",
            )
            self._tabs.setCurrentWidget(self._plot_tab_widget)
        self.statusBar().showMessage(
            f"Inverse FFT saved as '{result_dataset.name}' ({len(result_dataset.frame)} rows)"
        )

    def _run_curve_fit(self) -> None:
        """Run the curve-fitting workflow and plot/save fit outputs."""
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

        try:
            initial_parameters = dialog.initial_parameters()
            lower_bounds = dialog.lower_bounds()
            upper_bounds = dialog.upper_bounds()
            fixed_parameters = dialog.fixed_parameters()
        except ValueError as exc:
            QMessageBox.warning(self, "Curve Fit Failed", str(exc))
            return

        try:
            result = fit_curve(
                dataset.frame,
                x_column=dialog.x_column(),
                y_column=dialog.y_column(),
                model_key=dialog.model_key(),
                method=dialog.method(),
                initial_parameters=initial_parameters,
                lower_bounds=lower_bounds,
                upper_bounds=upper_bounds,
                fixed_parameters=fixed_parameters,
                weight_column=dialog.weight_column(),
                weight_mode=dialog.weight_mode(),
                absolute_sigma=dialog.absolute_sigma(),
                include_confidence_band=dialog.include_confidence_band(),
                confidence_level=dialog.confidence_level(),
                fit_points=dialog.fit_points(),
            )
            result_dataset = self._workspace.add_dataset(
                dialog.target_dataset_name() or f"{dataset.name}_fit",
                result.fit_frame,
            )
            residual_dataset = None
            if dialog.create_residual_sheet() or dialog.plot_residuals():
                residual_dataset = self._workspace.add_dataset(
                    dialog.residual_dataset_name() or f"{dataset.name}_residuals",
                    result.residual_frame,
                )
        except MathOperationError as exc:
            QMessageBox.warning(self, "Curve Fit Failed", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Curve Fit Failed", str(exc))
            return

        self._refresh_dataset_list(result_dataset.name)
        self._plot_tab_widget.queue_fit_plot(
            source_dataset=dataset,
            fit_dataset=result_dataset,
            x_column=dialog.x_column(),
            y_column=dialog.y_column(),
            model_name=result.report.model_name,
            residual_dataset=residual_dataset,
            show_residuals=dialog.plot_residuals(),
        )
        self._tabs.setCurrentWidget(self._plot_tab_widget)
        FitReportDialog(result.report.to_text(), self).exec()
        self.statusBar().showMessage(
            f"Fit saved as '{result_dataset.name}' with R^2={result.report.r_squared:.5g}"
        )

    def _refresh_dataset_after_analysis(self, dataset: Dataset, selected_column: str) -> None:
        """Refresh editor and plot controls after an in-place analysis column edit."""
        self._dataset_model.set_dataset(dataset)
        self._dataset_table.resizeColumnsToContents()
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        self._select_column(selected_column)

    def _delete_selected_rows(self) -> None:
        """Delete rows represented by the current table selection."""
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
        """Delete columns represented by the current table selection."""
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
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        self.statusBar().showMessage(
            f"Deleted {len(deleted_columns)} column(s) from {dataset.name}"
        )

    def _refresh_dataset_list(self, selected_name: str | None = None) -> None:
        """Refresh dataset navigation and keep a valid selection."""
        dataset_names = self._workspace.dataset_names()
        target_name = selected_name if selected_name in dataset_names else None
        if target_name is None and dataset_names:
            target_name = dataset_names[0]

        self._dataset_list.blockSignals(True)
        self._dataset_list.clear()
        self._dataset_list.addItems(dataset_names)
        self._dataset_list.blockSignals(False)

        if target_name:
            matches = self._dataset_list.findItems(target_name, Qt.MatchExactly)
            if matches:
                self._dataset_list.setCurrentItem(matches[0])
                self._show_dataset_editor(target_name)
        else:
            self._dataset_model.set_dataset(None)
            self._dataset_table.clearSelection()
            self._update_dataset_summary()

        self._plot_tab_widget.refresh_controls(target_name)

    def _show_dataset_editor(self, dataset_name: str) -> None:
        """Load a dataset into the central editor by workspace name."""
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
        """Start editing the double-clicked table cell."""
        self._dataset_table.edit(index)

    def _current_dataset(self) -> Dataset | None:
        """Return the dataset currently selected in the sidebar."""
        current_item = self._dataset_list.currentItem()
        if current_item is None:
            return None

        try:
            return self._workspace.get_dataset(current_item.text())
        except KeyError:
            return None

    def _selected_dataset_rows(self) -> list[int]:
        """Return sorted row indexes touched by the table selection."""
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return []

        return sorted({index.row() for index in selection_model.selectedIndexes()})

    def _update_dataset_summary(self) -> None:
        """Update dataset summary text and action enabled states."""
        dataset = self._dataset_model.dataset
        has_dataset = dataset is not None
        has_project_content = self._has_project_content()

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
        self._rename_dataset_action.setEnabled(has_dataset)
        self._delete_dataset_action.setEnabled(has_dataset)
        self._add_column_action.setEnabled(has_dataset)
        self._add_row_action.setEnabled(has_dataset)
        self._apply_formula_action.setEnabled(has_dataset)
        self._derivative_action.setEnabled(has_dataset)
        self._integral_action.setEnabled(has_dataset)
        self._fft_action.setEnabled(has_dataset)
        self._ifft_action.setEnabled(has_dataset)
        self._fit_action.setEnabled(has_dataset)
        self._rename_dataset_button.setEnabled(has_dataset)
        self._remove_dataset_button.setEnabled(has_dataset)
        self._editor_add_row_button.setEnabled(has_dataset)
        self._editor_add_column_button.setEnabled(has_dataset)
        self._editor_delete_rows_button.setEnabled(has_dataset)
        self._editor_delete_columns_button.setEnabled(has_dataset)
        self._editor_rename_button.setEnabled(has_dataset)
        self._editor_remove_button.setEnabled(has_dataset)
        self._editor_export_button.setEnabled(has_dataset)
        self._close_project_action.setEnabled(has_project_content)
        self._update_plot_action_state()

    def _set_sidebar_visible(self, visible: bool) -> None:
        """Show or hide the full left sidebar."""
        self._sidebar.setVisible(visible)
        if hasattr(self, "_show_sidebar_action"):
            self._sync_checkable_action(self._show_sidebar_action, visible)

    def _toggle_workspace_section(self) -> None:
        """Toggle visibility of the workspace dataset section."""
        self._set_workspace_section_visible(self._dataset_list.isHidden())

    def _toggle_plots_section(self) -> None:
        """Toggle visibility of the saved plots section."""
        self._set_plots_section_visible(self._plot_list.isHidden())

    def _set_workspace_section_visible(self, visible: bool) -> None:
        """Show or hide workspace dataset navigation controls."""
        self._dataset_list.setVisible(visible)
        self._dataset_buttons_panel.setVisible(visible)
        self._workspace_toggle_button.setText("Hide" if visible else "Show")
        if hasattr(self, "_show_workspace_action"):
            self._sync_checkable_action(self._show_workspace_action, visible)

    def _set_plots_section_visible(self, visible: bool) -> None:
        """Show or hide saved plot navigation controls."""
        self._plot_list.setVisible(visible)
        self._plots_toggle_button.setText("Hide" if visible else "Show")
        if hasattr(self, "_show_plots_action"):
            self._sync_checkable_action(self._show_plots_action, visible)

    def _set_plot_options_visible_from_action(self, visible: bool) -> None:
        """Apply the View menu plot-options visibility state."""
        self._plot_tab_widget.set_plot_options_visible(visible)

    def _sync_plot_options_action(self, visible: bool) -> None:
        """Synchronize the View menu with plot-tab option visibility."""
        if hasattr(self, "_show_plot_options_action"):
            self._sync_checkable_action(self._show_plot_options_action, visible)

    @staticmethod
    def _sync_checkable_action(action: QAction, checked: bool) -> None:
        """Set a checkable action without emitting its toggled signal."""
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)

    def _reset_view_to_default(self) -> None:
        """Restore default sidebar and plot-option visibility/layout."""
        self._set_sidebar_visible(True)
        self._set_workspace_section_visible(True)
        self._set_plots_section_visible(True)
        self._main_splitter.setSizes([380, 720])
        self._plot_tab_widget.reset_view_to_default()
        self.statusBar().showMessage("Reset view to default")

    def _path_with_export_suffix(self, path: Path, selected_filter: str) -> Path:
        """Append an export extension when the user omitted one."""
        if path.suffix:
            return path

        if "Text" in selected_filter:
            return path.with_suffix(".txt")
        return path.with_suffix(".csv")

    def _default_formula_target(self, dataset: Dataset) -> str:
        """Return the default formula target from current column selection."""
        selected_columns = self._selected_dataset_columns()
        if len(selected_columns) == 1:
            return str(dataset.frame.columns[selected_columns[0]])
        return "Result"

    def _selected_dataset_columns(self) -> list[int]:
        """Return sorted column indexes touched by the table selection."""
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return []

        return sorted({index.column() for index in selection_model.selectedIndexes()})

    def _select_column(self, column_name: str) -> None:
        """Select a named column in the data editor if it exists."""
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

    def _has_project_content(self) -> bool:
        """Return whether the current workspace has datasets or saved plots."""
        return bool(self._workspace.dataset_names() or self._workspace.plot_names())

    def _open_project(self) -> None:
        """Open a `.jasc` project, replacing the current workspace."""
        if self._has_project_content():
            reply = QMessageBox.question(
                self, "Open Project",
                "Opening a project will replace your current workspace. Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "JASC Projects (*.jasc);;All Files (*)")
        if not file_name:
            return
            
        try:
            self._workspace = project_io.load_project(file_name)
            self._plot_tab_widget.set_workspace(self._workspace)
            self._refresh_dataset_list()
            self._refresh_plot_list()
            self.statusBar().showMessage(f"Opened project {Path(file_name).name}")
        except Exception as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))

    def _save_project(self) -> None:
        """Save the current workspace to a `.jasc` project file."""
        if not self._has_project_content():
            QMessageBox.information(self, "Save Project", "The workspace is empty.")
            return
            
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Project", "workspace.jasc", "JASC Projects (*.jasc)")
        if not file_name:
            return

        path = Path(file_name)
        if not path.suffix:
            path = path.with_suffix(project_io.PROJECT_EXTENSION)

        try:
            project_io.save_project(self._workspace, path)
            self.statusBar().showMessage(f"Saved project {path.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _close_project(self) -> None:
        """Clear the current project without closing the application."""
        if not self._has_project_content():
            self.statusBar().showMessage("No project is open")
            return

        reply = QMessageBox.question(
            self,
            "Close Project",
            "Close the current project? Unsaved changes will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._workspace = Workspace()
        self._plot_tab_widget.set_workspace(self._workspace)
        self._refresh_dataset_list()
        self._refresh_plot_list()
        self._tabs.setCurrentIndex(0)
        self.statusBar().showMessage("Closed project")

    def _show_dataset_context_menu(self, pos) -> None:
        """Show dataset rename/delete actions for a sidebar item."""
        item = self._dataset_list.itemAt(pos)
        if not item:
            return
            
        dataset_name = item.text()
        menu = QMenu(self)
        rename_action = menu.addAction("Rename...")
        delete_action = menu.addAction("Delete")
        
        action = menu.exec(self._dataset_list.mapToGlobal(pos))
        if action == rename_action:
            self._rename_dataset(dataset_name)
        elif action == delete_action:
            self._delete_dataset(dataset_name)

    def _refresh_plot_list(self, selected_name: str | None = None) -> None:
        """Refresh saved plot navigation and optionally reselect one plot."""
        plot_names = self._workspace.plot_names()
        target_name = selected_name if selected_name in plot_names else None

        self._plot_list.blockSignals(True)
        self._plot_list.clear()
        self._plot_list.addItems(plot_names)
        self._plot_list.blockSignals(False)

        if target_name:
            matches = self._plot_list.findItems(target_name, Qt.MatchExactly)
            if matches:
                self._plot_list.setCurrentItem(matches[0])
        self._update_plot_action_state()

    def _current_plot_name(self) -> str | None:
        """Return the selected saved plot name, if any."""
        current_item = self._plot_list.currentItem()
        return current_item.text() if current_item is not None else None

    def _handle_saved_plot_selection(self, plot_name: str) -> None:
        """Load a selected saved plot into the editable Plot tab."""
        self._update_plot_action_state()
        if plot_name:
            self._load_plot_by_name(plot_name, show_message=False)

    def _save_current_plot(self) -> None:
        """Save or overwrite the current plot definition in the workspace."""
        if not self._plot_tab_widget.has_plot_series():
            QMessageBox.information(self, "Save Plot", "Create a plot before saving it.")
            return

        selected_name = self._current_plot_name()
        default_name = selected_name or self._plot_tab_widget.suggested_plot_name()
        plot_name, accepted = QInputDialog.getText(
            self,
            "Save Plot",
            "Plot name:",
            text=default_name,
        )
        if not accepted:
            return

        clean_name = plot_name.strip() or "Plot"
        state = self._plot_tab_widget.current_plot_state()

        try:
            if clean_name in self._workspace.plot_names():
                reply = QMessageBox.question(
                    self,
                    "Save Plot",
                    f"Replace saved plot '{clean_name}'?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply != QMessageBox.Yes:
                    return
                saved_plot = self._workspace.update_plot(clean_name, state)
            else:
                saved_plot = self._workspace.add_plot(clean_name, state)
        except Exception as exc:
            QMessageBox.critical(self, "Save Plot Failed", str(exc))
            return

        self._refresh_plot_list(saved_plot.name)
        self.statusBar().showMessage(f"Saved plot '{saved_plot.name}'")

    def _load_selected_plot(self) -> None:
        """Load the currently selected saved plot with user feedback."""
        plot_name = self._current_plot_name()
        if plot_name is None:
            QMessageBox.information(self, "Load Plot", "Select a saved plot before loading it.")
            return

        self._load_plot_by_name(plot_name, show_message=True)

    def _load_plot_by_name(self, plot_name: str, show_message: bool) -> None:
        """Load a saved plot by name into the Plot tab."""
        if plot_name not in self._workspace.plot_names():
            self._update_plot_action_state()
            return

        try:
            saved_plot = self._workspace.get_plot(plot_name)
            self._plot_tab_widget.load_plot_state(saved_plot.state)
        except Exception as exc:
            QMessageBox.critical(self, "Load Plot Failed", str(exc))
            return

        self._tabs.setCurrentWidget(self._plot_tab_widget)
        if show_message:
            self.statusBar().showMessage(f"Loaded plot '{plot_name}'")
        else:
            self.statusBar().showMessage(f"Selected saved plot '{plot_name}' for editing")

    def _delete_selected_plot(self) -> None:
        """Remove the currently selected saved plot from the workspace."""
        plot_name = self._current_plot_name()
        if plot_name is None:
            QMessageBox.information(self, "Remove Plot", "Select a saved plot before removing it.")
            return

        reply = QMessageBox.question(
            self,
            "Remove Plot",
            f"Remove saved plot '{plot_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self._workspace.remove_plot(plot_name)
        except Exception as exc:
            QMessageBox.critical(self, "Remove Plot Failed", str(exc))
            return

        self._refresh_plot_list()
        self.statusBar().showMessage(f"Removed plot '{plot_name}'")

    def _show_plot_context_menu(self, pos) -> None:
        """Show saved-plot load/remove actions for a sidebar item."""
        item = self._plot_list.itemAt(pos)
        if not item:
            return
        self._plot_list.setCurrentItem(item)

        menu = QMenu(self)
        load_action = menu.addAction("Load")
        delete_action = menu.addAction("Remove")

        action = menu.exec(self._plot_list.mapToGlobal(pos))
        if action == load_action:
            self._load_selected_plot()
        elif action == delete_action:
            self._delete_selected_plot()

    def _update_plot_action_state(self) -> None:
        """Update plot menu and header action enabled states."""
        has_saved_plot = self._current_plot_name() is not None
        has_current_plot = self._plot_tab_widget.has_plot_series()

        if hasattr(self, "_save_plot_action"):
            self._save_plot_action.setEnabled(has_current_plot)
            self._load_plot_action.setEnabled(has_saved_plot)
            self._delete_plot_action.setEnabled(has_saved_plot)

        self._plot_tab_widget.set_plot_actions_enabled(
            can_save=has_current_plot,
            can_load=has_saved_plot,
            can_remove=has_saved_plot,
        )
        self._plot_tab_widget.set_active_plot_name(self._current_plot_name())

    def _rename_dataset(self, old_name: str) -> None:
        """Prompt for and apply a dataset rename."""
        new_name, ok = QInputDialog.getText(self, "Rename Dataset", "New name:", text=old_name)
        if ok and new_name and new_name != old_name:
            try:
                final_name = self._workspace.rename_dataset(old_name, new_name)
                self._plot_tab_widget.clear_plot_state()
                self._refresh_plot_list()
                self._refresh_dataset_list(final_name)
                self.statusBar().showMessage(f"Renamed '{old_name}' to '{final_name}'")
            except Exception as exc:
                QMessageBox.critical(self, "Rename Failed", str(exc))

    def _rename_current_dataset(self) -> None:
        """Rename the currently selected dataset."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Rename Dataset", "Select a dataset before renaming it.")
            return
        self._rename_dataset(dataset.name)

    def _delete_dataset(self, name: str) -> None:
        """Delete a named dataset after confirmation."""
        reply = QMessageBox.question(
            self, "Delete Dataset",
            f"Are you sure you want to delete '{name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self._workspace.remove_dataset(name)
                self._plot_tab_widget.clear_plot_state()
                self._refresh_dataset_list()
                self.statusBar().showMessage(f"Deleted dataset '{name}'")
            except Exception as exc:
                QMessageBox.critical(self, "Delete Failed", str(exc))

    def _delete_current_dataset(self) -> None:
        """Delete the currently selected dataset."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Remove Dataset", "Select a dataset before removing it.")
            return
        self._delete_dataset(dataset.name)
