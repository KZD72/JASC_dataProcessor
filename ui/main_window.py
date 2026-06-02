"""Main application window for the JASC Data Processor."""

from __future__ import annotations

import csv
import json
import re
import time
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import (
    QByteArray,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QMimeData,
    Qt,
)
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core import project_io
from core.batch_processing import (
    BatchExecutionDecision,
    FormulaBatchTask,
    FormulaBatchWorkerResult,
    resolve_formula_batch_execution,
    run_formula_batch_parallel,
)
from core.data_backends import (
    DEFAULT_LARGE_DATASET_COLUMN_WIDTH,
    PANDAS_BACKEND,
    format_bytes,
    file_size_bytes,
    profile_dataframe,
    should_warn_for_large_file,
)
from core.file_io import export_tabular_file, read_tabular_file
from core.operations import ExpressionError, ExpressionResult, apply_column_expression
from core.workspace import (
    ColumnMetadata,
    Dataset,
    Workspace,
    set_column_operation_comment,
    set_dataset_operation_comments,
)
from math_engine.calculus import (
    DERIVATIVE_METHODS,
    INTEGRATION_METHODS,
    MathOperationError,
    WINDOW_METHODS,
    derivative_column,
    fft_dataset,
    ifft_dataset,
    integral_column,
)
from math_engine.curve_fitting import fit_curve
from math_engine.interpolation import (
    generated_query_points,
    interpolate_dataset,
    query_points_from_columns,
    query_points_from_text,
)
from math_engine.statistics import (
    STATISTIC_OPERATIONS,
    run_multicolumn_statistical_analysis,
    run_statistical_analysis,
)
from ui.data_table import DataTableWidget
from ui.dataframe_model import DataFrameTableModel
from ui.dialogs import (
    ColumnExpressionDialog,
    ColumnMathDialog,
    ColumnMetadataDialog,
    CustomFitModelsDialog,
    FFTDialog,
    FitDialog,
    FitReportDialog,
    IFFTDialog,
    ImportOptionsDialog,
    InterpolationDialog,
    StatisticsDialog,
)
from ui.plot_canvas import PlotSeries
from ui.plot_tab import PlotTab


_DATASET_COLUMNS_MIME = "application/x-jasc-dataframe-columns"


class MainWindow(QMainWindow):
    """Primary application shell for data ingestion, editing, and plotting workflows."""

    def __init__(self) -> None:
        """Create the main window, shared workspace, and primary UI regions."""
        super().__init__()
        self._workspace = Workspace()
        self._project_path: Path | None = None
        self._large_dataset_warning_names: set[str] = set()

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
        self._dataset_model.history_changed.connect(self._handle_dataset_history_changed)
        self._dataset_model.columns_renamed.connect(self._handle_dataset_columns_renamed)
        self._dataset_table = QTableView()
        self._dataset_table.setModel(self._dataset_model)
        self._dataset_table.setAlternatingRowColors(True)
        self._dataset_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._dataset_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._dataset_table.setSortingEnabled(False)
        self._dataset_table.doubleClicked.connect(self._edit_dataset_cell)
        self._install_dataset_clipboard_shortcuts()
        self._install_dataset_context_menu()
        self._dataset_summary = QLabel("No dataset selected")

        # Plot state moved to PlotTab

        self._manual_table = DataTableWidget()
        self._manual_table.dataset_submitted.connect(self._add_manual_dataset)

        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._sync_inspector_to_current_tab)
        self._tabs.addTab(self._build_dataset_editor(), "Data")
        self._plot_tab_widget = PlotTab(self._workspace, parent=self, external_options=True)
        self._plot_tab_widget.status_message.connect(self.statusBar().showMessage)
        self._plot_tab_widget.plot_rendered.connect(self._update_plot_action_state)
        self._plot_tab_widget.save_plot_requested.connect(self._save_current_plot)
        self._plot_tab_widget.load_plot_requested.connect(self._load_selected_plot)
        self._plot_tab_widget.remove_plot_requested.connect(self._delete_selected_plot)
        self._plot_tab_widget.options_visibility_changed.connect(self._handle_plot_options_visibility_changed)
        self._tabs.addTab(self._plot_tab_widget, "Plot")

        self.setCentralWidget(self._tabs)
        self._build_workspace_dock()
        self._build_inspector_dock()
        self._create_actions()
        self._apply_visual_style()
        self._sync_inspector_to_current_tab()
        self.statusBar().showMessage("Ready")

    def _build_workspace_dock(self) -> None:
        """Build the docked workspace navigator for datasets and saved plots."""
        dock = QDockWidget("Workspace", self)
        dock.setObjectName("WorkspaceDock")
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock.setMinimumWidth(240)

        self._workspace_nav_tabs = QTabWidget()

        dataset_page = QWidget()
        self._dataset_nav_page = dataset_page
        dataset_layout = QVBoxLayout(dataset_page)
        dataset_layout.addWidget(self._dataset_list)
        self._dataset_buttons_panel = QWidget()
        dataset_buttons = QHBoxLayout(self._dataset_buttons_panel)
        dataset_buttons.setContentsMargins(0, 0, 0, 0)
        self._rename_dataset_button = QPushButton("Rename")
        self._rename_dataset_button.clicked.connect(self._rename_current_dataset)
        self._remove_dataset_button = QPushButton("Remove")
        self._remove_dataset_button.clicked.connect(self._delete_current_dataset)
        dataset_buttons.addWidget(self._rename_dataset_button)
        dataset_buttons.addWidget(self._remove_dataset_button)
        dataset_layout.addWidget(self._dataset_buttons_panel)

        plot_page = QWidget()
        self._plot_nav_page = plot_page
        plot_layout = QVBoxLayout(plot_page)
        plot_layout.addWidget(self._plot_list)

        self._workspace_nav_tabs.addTab(dataset_page, "Datasets")
        self._workspace_nav_tabs.addTab(plot_page, "Plots")
        dock.setWidget(self._workspace_nav_tabs)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self._workspace_dock = dock

    def _build_inspector_dock(self) -> None:
        """Build the context-sensitive inspector dock."""
        dock = QDockWidget("Inspector", self)
        dock.setObjectName("InspectorDock")
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock.setMinimumWidth(360)

        self._inspector_stack = QStackedWidget()
        self._data_inspector = self._build_data_inspector()
        self._plot_inspector = self._plot_tab_widget.options_widget()
        self._inspector_stack.addWidget(self._data_inspector)
        self._inspector_stack.addWidget(self._plot_inspector)
        dock.setWidget(self._inspector_stack)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._inspector_dock = dock

    def _build_data_inspector(self) -> QWidget:
        """Build the Data-mode inspector with sheet actions, analysis, and manual entry."""
        inspector_tabs = QTabWidget()
        inspector_tabs.addTab(self._build_sheet_actions_panel(), "Sheet")
        inspector_tabs.addTab(self._build_analysis_actions_panel(), "Analysis")
        inspector_tabs.addTab(self._manual_table, "Manual Entry")
        return inspector_tabs

    def _build_sheet_actions_panel(self) -> QWidget:
        """Build compact dataset-editing actions for the inspector."""
        panel = QWidget()
        self._dataset_summary.setWordWrap(True)

        self._editor_add_row_button = QPushButton("Add Row")
        self._editor_add_row_button.clicked.connect(self._add_empty_row)
        self._editor_insert_row_button = QPushButton("Insert Row")
        self._editor_insert_row_button.clicked.connect(self._insert_empty_row)
        self._editor_add_column_button = QPushButton("Add Column")
        self._editor_add_column_button.clicked.connect(self._add_empty_column)
        self._editor_insert_column_button = QPushButton("Insert Column")
        self._editor_insert_column_button.clicked.connect(self._insert_empty_column)
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
        self._editor_metadata_button = QPushButton("Column Metadata")
        self._editor_metadata_button.clicked.connect(self._edit_column_metadata)

        layout = QVBoxLayout(panel)
        layout.addWidget(self._dataset_summary)
        layout.addLayout(self._button_row(self._editor_add_row_button, self._editor_insert_row_button))
        layout.addLayout(self._button_row(self._editor_delete_rows_button, self._editor_delete_columns_button))
        layout.addLayout(self._button_row(self._editor_add_column_button, self._editor_insert_column_button))
        layout.addLayout(self._button_row(self._editor_rename_button, self._editor_remove_button))
        layout.addLayout(self._button_row(self._editor_export_button, self._editor_metadata_button))
        layout.addStretch(1)
        return panel

    def _build_analysis_actions_panel(self) -> QWidget:
        """Build grouped analysis launch buttons for the inspector."""
        panel = QWidget()
        formula_button = QPushButton("Apply Formula")
        formula_button.clicked.connect(self._apply_column_formula)
        derivative_button = QPushButton("Derivative")
        derivative_button.clicked.connect(self._run_derivative)
        integral_button = QPushButton("Integral")
        integral_button.clicked.connect(self._run_integral)
        interpolation_button = QPushButton("Interpolation")
        interpolation_button.clicked.connect(self._run_interpolation)
        fft_button = QPushButton("FFT")
        fft_button.clicked.connect(self._run_fft)
        ifft_button = QPushButton("Inverse FFT")
        ifft_button.clicked.connect(self._run_ifft)
        statistics_button = QPushButton("Statistics")
        statistics_button.clicked.connect(self._run_statistics)
        fit_button = QPushButton("Curve Fit")
        fit_button.clicked.connect(self._run_curve_fit)
        custom_models_button = QPushButton("Custom Fit Models")
        custom_models_button.clicked.connect(self._manage_custom_fit_models)

        self._analysis_buttons = [
            formula_button,
            derivative_button,
            integral_button,
            interpolation_button,
            fft_button,
            ifft_button,
            statistics_button,
            fit_button,
        ]

        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("Column Math"))
        layout.addWidget(formula_button)
        layout.addLayout(self._button_row(derivative_button, integral_button))
        layout.addWidget(interpolation_button)
        layout.addWidget(QLabel("Signal"))
        layout.addLayout(self._button_row(fft_button, ifft_button))
        layout.addWidget(QLabel("Statistics and Fitting"))
        layout.addWidget(statistics_button)
        layout.addWidget(fit_button)
        layout.addWidget(custom_models_button)
        layout.addStretch(1)
        return panel

    @staticmethod
    def _button_row(left_button: QPushButton, right_button: QPushButton) -> QHBoxLayout:
        """Return a two-button row with stable button widths."""
        left_button.setMinimumWidth(120)
        right_button.setMinimumWidth(120)
        row = QHBoxLayout()
        row.addWidget(left_button)
        row.addWidget(right_button)
        return row

    def _install_dataset_clipboard_shortcuts(self) -> None:
        """Bind spreadsheet-style copy/paste shortcuts for the dataset editor."""
        self._dataset_copy_shortcut = QShortcut(QKeySequence.Copy, self._dataset_table)
        self._dataset_copy_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._dataset_copy_shortcut.activated.connect(self._copy_dataset_selection)

        self._dataset_paste_shortcut = QShortcut(QKeySequence.Paste, self._dataset_table)
        self._dataset_paste_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._dataset_paste_shortcut.activated.connect(self._paste_dataset_clipboard)

    def _install_dataset_context_menu(self) -> None:
        """Bind right-click menus for dataset value and column editing."""
        self._dataset_table.viewport().setContextMenuPolicy(Qt.CustomContextMenu)
        self._dataset_table.viewport().customContextMenuRequested.connect(
            self._show_dataset_table_context_menu
        )
        self._dataset_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self._dataset_table.horizontalHeader().customContextMenuRequested.connect(
            self._show_dataset_header_context_menu
        )
        self._dataset_table.horizontalHeader().sectionDoubleClicked.connect(
            self._edit_column_metadata_for_column
        )

    def _build_dataset_editor(self) -> QWidget:
        """Build the central dataset table editor."""
        editor = QWidget()

        layout = QVBoxLayout(editor)
        layout.addWidget(self._dataset_table)
        return editor

    def _create_actions(self) -> None:
        """Create menus, toolbar actions, and long-lived action references."""
        file_menu = self.menuBar().addMenu("&File")

        open_project_action = file_menu.addAction("&Open Project...")
        open_project_action.setShortcut("Ctrl+O")
        open_project_action.triggered.connect(self._open_project)

        save_project_action = file_menu.addAction("&Save Project")
        save_project_action.setShortcut("Ctrl+S")
        save_project_action.triggered.connect(self._save_project)

        save_project_as_action = file_menu.addAction("Save Project &As...")
        save_project_as_action.setShortcut("Ctrl+Shift+S")
        save_project_as_action.triggered.connect(self._save_project_as)

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
        undo_action = edit_menu.addAction("&Undo")
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self._undo_dataset_edit)

        redo_action = edit_menu.addAction("&Redo")
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self._redo_dataset_edit)

        edit_menu.addSeparator()

        delete_rows_action = edit_menu.addAction("&Delete Selected Rows")
        delete_rows_action.setShortcut("Del")
        delete_rows_action.triggered.connect(self._delete_selected_rows)

        delete_columns_action = edit_menu.addAction("Delete Selected &Columns")
        delete_columns_action.triggered.connect(self._delete_selected_columns)

        view_menu = self.menuBar().addMenu("&View")
        show_sidebar_action = view_menu.addAction("Show &Workspace Navigator")
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

        show_plot_options_action = view_menu.addAction("Show &Inspector")
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

        insert_column_action = data_menu.addAction("&Insert Column...")
        insert_column_action.triggered.connect(self._insert_empty_column)

        add_row_action = data_menu.addAction("Add &Row")
        add_row_action.triggered.connect(self._add_empty_row)

        insert_row_action = data_menu.addAction("&Insert Row")
        insert_row_action.triggered.connect(self._insert_empty_row)

        data_menu.addSeparator()

        column_metadata_action = data_menu.addAction("Column &Metadata...")
        column_metadata_action.triggered.connect(self._edit_column_metadata)

        apply_formula_action = data_menu.addAction("&Apply Formula...")
        apply_formula_action.setShortcut("Ctrl+Shift+F")
        apply_formula_action.triggered.connect(self._apply_column_formula)

        analysis_menu = self.menuBar().addMenu("&Analysis")
        derivative_action = analysis_menu.addAction("&Derivative...")
        derivative_action.triggered.connect(self._run_derivative)

        integral_action = analysis_menu.addAction("&Integral...")
        integral_action.triggered.connect(self._run_integral)

        interpolation_action = analysis_menu.addAction("Inter&polation...")
        interpolation_action.triggered.connect(self._run_interpolation)

        fft_action = analysis_menu.addAction("&FFT...")
        fft_action.triggered.connect(self._run_fft)

        ifft_action = analysis_menu.addAction("&Inverse FFT...")
        ifft_action.triggered.connect(self._run_ifft)

        statistics_action = analysis_menu.addAction("&Statistics...")
        statistics_action.triggered.connect(self._run_statistics)

        custom_models_action = analysis_menu.addAction("Custom Fit &Models...")
        custom_models_action.triggered.connect(self._manage_custom_fit_models)

        fit_action = analysis_menu.addAction("&Curve Fit...")
        fit_action.setShortcut("Ctrl+Shift+C")
        fit_action.triggered.connect(self._run_curve_fit)

        plot_menu = self.menuBar().addMenu("&Plot")
        save_plot_action = plot_menu.addAction("&Save Current Plot...")
        save_plot_action.setShortcut("Ctrl+Alt+S")
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
        toolbar.addAction(save_project_as_action)
        toolbar.addAction(close_project_action)
        toolbar.addSeparator()
        toolbar.addAction(import_action)
        toolbar.addAction(export_action)
        self.addToolBar(toolbar)

        self._export_action = export_action
        self._save_project_action = save_project_action
        self._save_project_as_action = save_project_as_action
        self._undo_action = undo_action
        self._redo_action = redo_action
        self._delete_rows_action = delete_rows_action
        self._delete_columns_action = delete_columns_action
        self._rename_dataset_action = rename_dataset_action
        self._delete_dataset_action = delete_dataset_action
        self._add_column_action = add_column_action
        self._insert_column_action = insert_column_action
        self._column_metadata_action = column_metadata_action
        self._apply_formula_action = apply_formula_action
        self._derivative_action = derivative_action
        self._integral_action = integral_action
        self._interpolation_action = interpolation_action
        self._fft_action = fft_action
        self._ifft_action = ifft_action
        self._statistics_action = statistics_action
        self._custom_models_action = custom_models_action
        self._fit_action = fit_action
        self._close_project_action = close_project_action
        self._save_plot_action = save_plot_action
        self._load_plot_action = load_plot_action
        self._delete_plot_action = delete_plot_action
        self._add_row_action = add_row_action
        self._insert_row_action = insert_row_action
        self._show_sidebar_action = show_sidebar_action
        self._show_workspace_action = show_workspace_action
        self._show_plots_action = show_plots_action
        self._show_plot_options_action = show_plot_options_action
        self._workspace_dock.visibilityChanged.connect(
            lambda visible: self._sync_checkable_action(self._show_sidebar_action, visible)
        )
        self._inspector_dock.visibilityChanged.connect(self._sync_plot_options_action)
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
            QDockWidget {
                font-weight: 700;
            }
            QDockWidget::title {
                background: #edf2f7;
                border: 1px solid #c7d0da;
                padding: 6px;
                text-align: left;
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

    def _confirm_large_file_import(self, path: Path) -> bool:
        """Ask before reading a very large delimited text file into memory."""
        file_size = file_size_bytes(path)
        if not should_warn_for_large_file(path):
            return True

        reply = QMessageBox.question(
            self,
            "Large File",
            (
                f"'{path.name}' is {format_bytes(file_size)} on disk.\n\n"
                "Delimited files can require several times their file size in memory once "
                "loaded into pandas, and large sheets may make editing, undo, plotting, and "
                "analysis slower.\n\n"
                "Continue importing this file?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _confirm_large_dataset(self, frame: pd.DataFrame, title: str, source_label: str) -> bool:
        """Ask before adding a large DataFrame to the workspace."""
        profile = profile_dataframe(frame, source_label)
        if not profile.is_large:
            return True

        reply = QMessageBox.question(
            self,
            title,
            (
                f"'{source_label}' contains {profile.dimensions_text()}.\n"
                f"Estimated DataFrame memory: {format_bytes(profile.memory_bytes)}.\n\n"
                "This should still load, but full-sheet edits and undo snapshots can duplicate "
                "the data in memory. Some analysis operations may take noticeable time. "
                "The data editor will skip full column auto-sizing for responsiveness.\n\n"
                "Keep this dataset in the workspace?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _resize_dataset_columns_to_contents(self, dataset: Dataset | None = None) -> None:
        """Resize table columns, skipping expensive full auto-sizing for large sheets."""
        target_dataset = dataset or self._dataset_model.dataset
        if target_dataset is None:
            return

        profile = profile_dataframe(target_dataset.frame, target_dataset.name)
        if profile.should_skip_full_auto_resize:
            self._dataset_table.horizontalHeader().setDefaultSectionSize(
                DEFAULT_LARGE_DATASET_COLUMN_WIDTH
            )
            if target_dataset.name not in self._large_dataset_warning_names:
                self._large_dataset_warning_names.add(target_dataset.name)
                self.statusBar().showMessage(
                    f"{target_dataset.name} is large; skipped full column auto-sizing for responsiveness"
                )
            return

        self._dataset_table.resizeColumnsToContents()

    def _warn_about_large_workspace_datasets(self, source_label: str) -> None:
        """Show a post-load notice when a project contains large sheets."""
        large_datasets: list[str] = []
        for dataset in self._workspace.list_datasets():
            profile = profile_dataframe(dataset.frame, dataset.name)
            if profile.is_large:
                large_datasets.append(
                    f"{dataset.name}: {profile.dimensions_text()}, "
                    f"{format_bytes(profile.memory_bytes)}"
                )

        if not large_datasets:
            return

        shown = "\n".join(large_datasets[:8])
        if len(large_datasets) > 8:
            shown += f"\n... and {len(large_datasets) - 8} more"
        QMessageBox.warning(
            self,
            "Large Project Datasets",
            (
                f"'{source_label}' contains large dataset(s):\n\n"
                f"{shown}\n\n"
                "They can be kept in the project, but editing, undo snapshots, plotting, "
                "and analysis may be slower. The data editor will skip full column "
                "auto-sizing for large sheets."
            ),
        )

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
        if not self._confirm_large_file_import(path):
            self.statusBar().showMessage("Import cancelled")
            return

        try:
            frame = read_tabular_file(path, dialog.options())
            if not self._confirm_large_dataset(
                frame,
                title="Large Dataset",
                source_label=path.name,
            ):
                self.statusBar().showMessage("Import cancelled")
                return
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

        if not self._confirm_large_dataset(
            frame,
            title="Large Manual Dataset",
            source_label=name,
        ):
            self.statusBar().showMessage("Manual dataset cancelled")
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

    def _insert_empty_column(self) -> None:
        """Prompt for and insert an empty column before the current selection."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Insert Column", "Select a dataset before inserting a column.")
            return

        selected_columns = self._selected_dataset_columns()
        insert_position = selected_columns[0] if selected_columns else len(dataset.frame.columns)
        column_name, accepted = QInputDialog.getText(
            self,
            "Insert Column",
            "Column name",
            text="New Column",
        )
        if not accepted:
            return

        try:
            final_name = self._dataset_model.insert_empty_column(insert_position, column_name)
        except Exception as exc:
            QMessageBox.critical(self, "Insert Column Failed", str(exc))
            return

        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        self._select_column(final_name)
        self.statusBar().showMessage(
            f"Inserted column '{final_name}' in {dataset.name}"
        )

    def _edit_column_metadata(self, focus_column: str | int | None = None) -> None:
        """Open the column metadata editor for the selected dataset."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(
                self,
                "Column Metadata",
                "Select a dataset before editing column metadata.",
            )
            return

        focus_column_name: str | None = None
        if isinstance(focus_column, bool):
            focus_column_name = None
        elif isinstance(focus_column, int):
            if 0 <= focus_column < len(dataset.frame.columns):
                focus_column_name = str(dataset.frame.columns[focus_column])
        elif isinstance(focus_column, str):
            focus_column_name = focus_column

        dialog = ColumnMetadataDialog(
            dataset_name=dataset.name,
            column_names=[str(column) for column in dataset.frame.columns],
            column_metadata=dataset.column_metadata,
            focus_column=focus_column_name,
            parent=self,
        )
        if dialog.exec() != ColumnMetadataDialog.Accepted:
            return

        try:
            renamed_columns = self._dataset_model.apply_column_metadata(
                column_names=dialog.column_names(),
                metadata=dialog.column_metadata(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Column Metadata Failed", str(exc))
            return

        rename_map = dict(renamed_columns)
        if rename_map:
            self._workspace.rename_column_references_in_plots(dataset.name, rename_map)
            self._plot_tab_widget.rename_column_references(dataset.name, rename_map)
        else:
            self._plot_tab_widget.refresh_controls(dataset.name)

        selected_column = (
            rename_map.get(focus_column_name, focus_column_name)
            if focus_column_name is not None
            else None
        )
        if selected_column:
            self._select_column(selected_column)

        self._resize_dataset_columns_to_contents()
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        rename_text = f", renamed {len(renamed_columns)} column(s)" if renamed_columns else ""
        self.statusBar().showMessage(
            f"Updated metadata for {len(dataset.column_metadata)} column(s) in {dataset.name}{rename_text}"
        )

    def _edit_column_metadata_for_column(self, column_index: int) -> None:
        """Open column metadata focused on the double-clicked header column."""
        self._edit_column_metadata(column_index)

    def _add_empty_row(self) -> None:
        """Append an empty row to the selected dataset."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Add Row", "Select a dataset before adding a row.")
            return

        insert_position = len(dataset.frame)
        self._dataset_model.add_row()
        self._update_dataset_summary()
        if len(dataset.frame.columns) > 0:
            self._select_dataset_range(insert_position, 0, 1, len(dataset.frame.columns))
        self.statusBar().showMessage(f"Added empty row to {dataset.name}")

    def _insert_empty_row(self) -> None:
        """Insert an empty row before the current row selection."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Insert Row", "Select a dataset before inserting a row.")
            return

        selected_rows = self._selected_dataset_rows()
        insert_position = selected_rows[0] if selected_rows else len(dataset.frame)
        inserted_row = self._dataset_model.insert_row(insert_position)
        self._update_dataset_summary()
        if inserted_row >= 0 and len(dataset.frame.columns) > 0:
            self._select_dataset_range(inserted_row, 0, 1, len(dataset.frame.columns))
        self.statusBar().showMessage(f"Inserted empty row in {dataset.name}")

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
            dataset_names=[
                candidate.name
                for candidate in self._workspace.list_datasets()
                if len(candidate.frame.columns) > 0
            ],
            current_dataset_name=dataset.name,
            parent=self,
        )
        if dialog.exec() != ColumnExpressionDialog.Accepted:
            return

        row_positions = selected_rows if dialog.apply_selected_rows_only() else None
        target_dataset_names = dialog.target_dataset_names()
        expression = dialog.expression()
        target_column = dialog.target_column()
        conflict_policy = dialog.target_conflict_policy()
        requested_execution_mode = dialog.batch_execution_mode()
        max_workers = dialog.batch_max_workers()
        target_plan = self._formula_batch_target_plan(
            target_dataset_names=target_dataset_names,
            target_column=target_column,
            conflict_policy=conflict_policy,
        )
        if not self._confirm_formula_batch_target_plan(target_plan, conflict_policy):
            return

        execution_decision, parallel_plan_rows = self._formula_batch_execution_decision(
            target_plan=target_plan,
            current_dataset_name=dataset.name,
            row_positions=row_positions,
            requested_mode=requested_execution_mode,
            max_workers=max_workers,
        )
        if execution_decision.uses_parallel:
            self.statusBar().showMessage(
                f"Formula batch running with {execution_decision.worker_count} worker processes..."
            )
            QApplication.processEvents()
        elif requested_execution_mode == "parallel" and execution_decision.reason:
            self.statusBar().showMessage(execution_decision.reason)

        results_by_sheet: dict[str, dict[str, object]] = {}
        current_result_target = ""
        parallel_sheet_names = {str(row["source_sheet"]) for row in parallel_plan_rows}
        for plan_row in target_plan:
            target_dataset_name = str(plan_row["source_sheet"])
            if target_dataset_name in parallel_sheet_names:
                continue

            started = time.perf_counter()
            try:
                target_dataset = self._workspace.get_dataset(target_dataset_name)
                use_visible_model = target_dataset.name == dataset.name
                result = self._apply_expression_to_dataset(
                    dataset=target_dataset,
                    target_column=str(plan_row["target_column"]),
                    expression=expression,
                    row_positions=row_positions if use_visible_model else None,
                    use_visible_model=use_visible_model,
                )
                if use_visible_model:
                    current_result_target = result.target_column
                results_by_sheet[target_dataset_name] = (
                    self._formula_batch_summary_row(
                        dataset=target_dataset,
                        result_target_column=result.target_column,
                        updated_rows=result.updated_rows,
                        status="ok",
                        error="",
                        requested_target_column=target_column,
                        output_action=str(plan_row["output_action"]),
                        target_existed_before=bool(plan_row["target_existed_before"]),
                        execution_mode="sequential",
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            except ExpressionError as exc:
                results_by_sheet[target_dataset_name] = (
                    self._formula_batch_summary_row(
                        dataset_name=target_dataset_name,
                        result_target_column=str(plan_row["target_column"]),
                        updated_rows=0,
                        status="failed",
                        error=str(exc),
                        requested_target_column=target_column,
                        output_action=str(plan_row["output_action"]),
                        target_existed_before=bool(plan_row["target_existed_before"]),
                        execution_mode="sequential",
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            except Exception as exc:
                results_by_sheet[target_dataset_name] = (
                    self._formula_batch_summary_row(
                        dataset_name=target_dataset_name,
                        result_target_column=str(plan_row["target_column"]),
                        updated_rows=0,
                        status="failed",
                        error=str(exc),
                        requested_target_column=target_column,
                        output_action=str(plan_row["output_action"]),
                        target_existed_before=bool(plan_row["target_existed_before"]),
                        execution_mode="sequential",
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )

        if parallel_plan_rows:
            parallel_results = self._run_parallel_formula_batch_rows(
                plan_rows=parallel_plan_rows,
                expression=expression,
                requested_target_column=target_column,
                execution_decision=execution_decision,
            )
            results_by_sheet.update(parallel_results)

        results = [
            results_by_sheet[str(row["source_sheet"])]
            for row in target_plan
            if str(row["source_sheet"]) in results_by_sheet
        ]
        success_count = sum(1 for row in results if row["status"] == "ok")
        failure_rows = [row for row in results if row["status"] != "ok"]
        if success_count == 0:
            message = "\n".join(f"{row['source_sheet']}: {row['error']}" for row in failure_rows[:8])
            QMessageBox.warning(self, "Formula Error", message or "Formula failed on every selected sheet.")
            return

        summary_dataset = None
        if len(target_dataset_names) > 1:
            summary_dataset = self._workspace.add_dataset(
                f"{dataset.name}_formula_batch_summary",
                pd.DataFrame(results),
            )
            self._dataset_list.addItem(summary_dataset.name)

        self._resize_dataset_columns_to_contents()
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        if current_result_target:
            self._select_column(current_result_target)
        if failure_rows:
            detail = "\n".join(f"{row['source_sheet']}: {row['error']}" for row in failure_rows[:8])
            QMessageBox.warning(
                self,
                "Formula Batch",
                f"Applied formula to {success_count} sheet(s); {len(failure_rows)} failed.\n\n{detail}",
            )
        self.statusBar().showMessage(
            self._formula_batch_status_message(
                success_count=success_count,
                failure_count=len(failure_rows),
                summary_dataset_name=summary_dataset.name if summary_dataset else "",
            )
        )

    def _apply_expression_to_dataset(
        self,
        dataset: Dataset,
        target_column: str,
        expression: str,
        row_positions: list[int] | None,
        use_visible_model: bool,
    ) -> ExpressionResult:
        """Apply a formula to one dataset, using the visible model when possible."""
        if use_visible_model:
            return self._dataset_model.apply_expression(
                target_column=target_column,
                expression=expression,
                row_positions=row_positions,
            )

        result = apply_column_expression(
            dataset.frame,
            target_column=target_column,
            expression=expression,
            row_positions=row_positions,
        )
        dataset.formulas[result.target_column] = expression.strip()
        set_column_operation_comment(
            dataset,
            result.target_column,
            f"Formula = {expression.strip()}",
        )
        dataset.prune_column_metadata()
        return result

    def _formula_batch_target_plan(
        self,
        target_dataset_names: list[str],
        target_column: str,
        conflict_policy: str,
    ) -> list[dict[str, object]]:
        """Resolve formula output columns before any target sheet is modified."""
        plan_rows: list[dict[str, object]] = []
        requested_target = target_column.strip()
        for target_dataset_name in target_dataset_names:
            target_dataset = self._workspace.get_dataset(target_dataset_name)
            existing_columns = {str(column) for column in target_dataset.frame.columns}
            target_exists = requested_target in existing_columns
            final_target = requested_target
            output_action = "create"
            if target_exists and conflict_policy == "unique":
                final_target = self._unique_batch_column_name(requested_target, existing_columns)
                output_action = "create_unique"
            elif target_exists and conflict_policy == "stop":
                output_action = "blocked"
            elif target_exists:
                output_action = "overwrite"
            plan_rows.append(
                {
                    "source_sheet": target_dataset.name,
                    "requested_target_column": requested_target,
                    "target_column": final_target,
                    "target_existed_before": target_exists,
                    "output_action": output_action,
                }
            )
        return plan_rows

    def _confirm_formula_batch_target_plan(
        self,
        plan_rows: list[dict[str, object]],
        conflict_policy: str,
    ) -> bool:
        """Warn or confirm before a formula batch can touch existing columns."""
        blocked_rows = [row for row in plan_rows if row["output_action"] == "blocked"]
        if blocked_rows:
            detail = self._formula_batch_plan_detail(blocked_rows)
            QMessageBox.warning(
                self,
                "Formula Output Conflict",
                (
                    "The target column already exists in one or more selected sheets.\n\n"
                    f"{detail}\n\n"
                    "Choose a different target column or change the target-exists policy."
                ),
            )
            return False

        conflict_rows = [row for row in plan_rows if row["target_existed_before"]]
        if not conflict_rows:
            return True

        detail = self._formula_batch_plan_detail(conflict_rows)
        if conflict_policy == "overwrite":
            reply = QMessageBox.question(
                self,
                "Confirm Formula Overwrite",
                (
                    "This formula will overwrite or update existing target columns.\n"
                    "Non-visible batch target sheets do not yet have worksheet-level undo.\n\n"
                    f"{detail}\n\n"
                    "Continue?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return reply == QMessageBox.Yes

        reply = QMessageBox.question(
            self,
            "Formula Output Names",
            (
                "The requested target column already exists in one or more selected sheets.\n"
                "JASC will create unique new columns instead of overwriting data.\n\n"
                f"{detail}\n\n"
                "Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        return reply == QMessageBox.Yes

    @staticmethod
    def _formula_batch_plan_detail(plan_rows: list[dict[str, object]], limit: int = 12) -> str:
        """Return a compact user-facing description of formula output targets."""
        lines: list[str] = []
        for row in plan_rows[:limit]:
            source_sheet = row["source_sheet"]
            requested_target = row["requested_target_column"]
            final_target = row["target_column"]
            action = row["output_action"]
            if action == "create_unique":
                lines.append(f"{source_sheet}: {requested_target} -> {final_target}")
            elif action == "overwrite":
                lines.append(f"{source_sheet}: overwrite/update {requested_target}")
            elif action == "blocked":
                lines.append(f"{source_sheet}: {requested_target} already exists")
            else:
                lines.append(f"{source_sheet}: create {final_target}")
        if len(plan_rows) > limit:
            lines.append(f"... and {len(plan_rows) - limit} more sheet(s)")
        return "\n".join(lines)

    @staticmethod
    def _unique_batch_column_name(base_name: str, existing_columns: set[str]) -> str:
        """Return a non-colliding column name for formula batch outputs."""
        if base_name not in existing_columns:
            return base_name
        counter = 2
        while f"{base_name} ({counter})" in existing_columns:
            counter += 1
        return f"{base_name} ({counter})"

    def _formula_batch_summary_row(
        self,
        result_target_column: str,
        updated_rows: int,
        status: str,
        error: str,
        dataset: Dataset | None = None,
        dataset_name: str = "",
        requested_target_column: str = "",
        output_action: str = "",
        target_existed_before: bool = False,
        execution_mode: str = "",
        elapsed_seconds: float = 0.0,
    ) -> dict[str, object]:
        """Return one formula batch summary row."""
        source_sheet = dataset.name if dataset is not None else dataset_name
        row: dict[str, object] = {
            "source_sheet": source_sheet,
            "requested_target_column": requested_target_column or result_target_column,
            "target_column": result_target_column,
            "output_action": output_action,
            "target_existed_before": target_existed_before,
            "updated_rows": updated_rows,
            "status": status,
            "error": error,
            "execution_mode": execution_mode,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
            "row_count": len(dataset.frame) if dataset is not None else 0,
            "finite_count": np.nan,
            "missing_or_non_numeric": np.nan,
            "minimum": np.nan,
            "maximum": np.nan,
            "mean": np.nan,
        }
        if dataset is None or result_target_column not in dataset.frame.columns:
            return row

        values = pd.to_numeric(dataset.frame[result_target_column], errors="coerce")
        values = values.replace([np.inf, -np.inf], np.nan)
        finite_values = values.dropna()
        row["finite_count"] = int(len(finite_values))
        row["missing_or_non_numeric"] = int(len(values) - len(finite_values))
        if not finite_values.empty:
            row["minimum"] = float(finite_values.min())
            row["maximum"] = float(finite_values.max())
            row["mean"] = float(finite_values.mean())
        return row

    def _formula_batch_execution_decision(
        self,
        target_plan: list[dict[str, object]],
        current_dataset_name: str,
        row_positions: list[int] | None,
        requested_mode: str,
        max_workers: int,
    ) -> tuple[BatchExecutionDecision, list[dict[str, object]]]:
        """Return the execution decision and rows eligible for worker processes."""
        parallel_plan_rows: list[dict[str, object]] = []
        if row_positions is None:
            parallel_plan_rows = [
                row
                for row in target_plan
                if str(row["source_sheet"]) != current_dataset_name
            ]

        total_cells = 0
        for plan_row in parallel_plan_rows:
            target_dataset = self._workspace.get_dataset(str(plan_row["source_sheet"]))
            total_cells += int(target_dataset.frame.shape[0] * target_dataset.frame.shape[1])

        decision = resolve_formula_batch_execution(
            requested_mode=requested_mode,
            task_count=len(parallel_plan_rows),
            total_cells=total_cells,
            max_workers=max_workers,
        )
        return decision, parallel_plan_rows if decision.uses_parallel else []

    def _run_parallel_formula_batch_rows(
        self,
        plan_rows: list[dict[str, object]],
        expression: str,
        requested_target_column: str,
        execution_decision: BatchExecutionDecision,
    ) -> dict[str, dict[str, object]]:
        """Run formula batch rows in worker processes and apply successful outputs."""
        results_by_sheet: dict[str, dict[str, object]] = {}
        tasks = [
            FormulaBatchTask(
                source_sheet=str(plan_row["source_sheet"]),
                target_column=str(plan_row["target_column"]),
                expression=expression,
                frame=self._workspace.get_dataset(str(plan_row["source_sheet"])).frame,
            )
            for plan_row in plan_rows
        ]

        try:
            worker_results = run_formula_batch_parallel(
                tasks,
                max_workers=execution_decision.worker_count,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Formula Batch",
                (
                    "Parallel execution could not start, so the remaining sheets will run "
                    f"sequentially.\n\n{exc}"
                ),
            )
            return self._run_sequential_formula_batch_rows(
                plan_rows=plan_rows,
                expression=expression,
                requested_target_column=requested_target_column,
                execution_mode="sequential_fallback",
            )

        plan_by_sheet = {str(row["source_sheet"]): row for row in plan_rows}
        for worker_result in worker_results:
            plan_row = plan_by_sheet[worker_result.source_sheet]
            if worker_result.status != "ok":
                results_by_sheet[worker_result.source_sheet] = self._formula_batch_summary_row(
                    dataset_name=worker_result.source_sheet,
                    result_target_column=str(plan_row["target_column"]),
                    updated_rows=0,
                    status="failed",
                    error=worker_result.error,
                    requested_target_column=requested_target_column,
                    output_action=str(plan_row["output_action"]),
                    target_existed_before=bool(plan_row["target_existed_before"]),
                    execution_mode="parallel",
                    elapsed_seconds=worker_result.elapsed_seconds,
                )
                continue

            started = time.perf_counter()
            try:
                target_dataset = self._workspace.get_dataset(worker_result.source_sheet)
                result = self._apply_formula_worker_result_to_dataset(
                    dataset=target_dataset,
                    worker_result=worker_result,
                    expression=expression,
                )
                results_by_sheet[worker_result.source_sheet] = self._formula_batch_summary_row(
                    dataset=target_dataset,
                    result_target_column=result.target_column,
                    updated_rows=result.updated_rows,
                    status="ok",
                    error="",
                    requested_target_column=requested_target_column,
                    output_action=str(plan_row["output_action"]),
                    target_existed_before=bool(plan_row["target_existed_before"]),
                    execution_mode="parallel",
                    elapsed_seconds=worker_result.elapsed_seconds + time.perf_counter() - started,
                )
            except Exception as exc:
                results_by_sheet[worker_result.source_sheet] = self._formula_batch_summary_row(
                    dataset_name=worker_result.source_sheet,
                    result_target_column=str(plan_row["target_column"]),
                    updated_rows=0,
                    status="failed",
                    error=str(exc),
                    requested_target_column=requested_target_column,
                    output_action=str(plan_row["output_action"]),
                    target_existed_before=bool(plan_row["target_existed_before"]),
                    execution_mode="parallel",
                    elapsed_seconds=worker_result.elapsed_seconds + time.perf_counter() - started,
                )
        return results_by_sheet

    def _run_sequential_formula_batch_rows(
        self,
        plan_rows: list[dict[str, object]],
        expression: str,
        requested_target_column: str,
        execution_mode: str,
    ) -> dict[str, dict[str, object]]:
        """Run formula batch rows sequentially after a parallel fallback."""
        results_by_sheet: dict[str, dict[str, object]] = {}
        for plan_row in plan_rows:
            target_dataset_name = str(plan_row["source_sheet"])
            started = time.perf_counter()
            try:
                target_dataset = self._workspace.get_dataset(target_dataset_name)
                result = self._apply_expression_to_dataset(
                    dataset=target_dataset,
                    target_column=str(plan_row["target_column"]),
                    expression=expression,
                    row_positions=None,
                    use_visible_model=False,
                )
                results_by_sheet[target_dataset_name] = self._formula_batch_summary_row(
                    dataset=target_dataset,
                    result_target_column=result.target_column,
                    updated_rows=result.updated_rows,
                    status="ok",
                    error="",
                    requested_target_column=requested_target_column,
                    output_action=str(plan_row["output_action"]),
                    target_existed_before=bool(plan_row["target_existed_before"]),
                    execution_mode=execution_mode,
                    elapsed_seconds=time.perf_counter() - started,
                )
            except Exception as exc:
                results_by_sheet[target_dataset_name] = self._formula_batch_summary_row(
                    dataset_name=target_dataset_name,
                    result_target_column=str(plan_row["target_column"]),
                    updated_rows=0,
                    status="failed",
                    error=str(exc),
                    requested_target_column=requested_target_column,
                    output_action=str(plan_row["output_action"]),
                    target_existed_before=bool(plan_row["target_existed_before"]),
                    execution_mode=execution_mode,
                    elapsed_seconds=time.perf_counter() - started,
                )
        return results_by_sheet

    def _apply_formula_worker_result_to_dataset(
        self,
        dataset: Dataset,
        worker_result: FormulaBatchWorkerResult,
        expression: str,
    ) -> ExpressionResult:
        """Apply a successful process-worker formula result to a workspace dataset."""
        if worker_result.values is None:
            raise ExpressionError("Worker did not return formula values.")

        dataset.frame[worker_result.target_column] = worker_result.values.reindex(dataset.frame.index)
        dataset.formulas[worker_result.target_column] = expression.strip()
        set_column_operation_comment(
            dataset,
            worker_result.target_column,
            f"Formula = {expression.strip()}",
        )
        dataset.prune_column_metadata()
        return ExpressionResult(
            target_column=worker_result.target_column,
            updated_rows=worker_result.updated_rows,
        )

    @staticmethod
    def _formula_batch_status_message(
        success_count: int,
        failure_count: int,
        summary_dataset_name: str,
    ) -> str:
        """Return a concise status-bar message for a formula batch."""
        if summary_dataset_name:
            return (
                f"Formula applied to {success_count} sheet(s), "
                f"{failure_count} failed; summary saved as '{summary_dataset_name}'"
            )
        if failure_count:
            return f"Formula applied to {success_count} sheet(s), {failure_count} failed"
        return f"Formula applied to {success_count} sheet(s)"

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
            default_x_column=self._preferred_dataset_column(dataset, ("x",), fallback_index=0),
            default_y_column=self._preferred_dataset_column(dataset, ("y",), fallback_index=1),
            dataset_names=[
                candidate.name
                for candidate in self._workspace.list_datasets()
                if len(candidate.frame.columns) > 0
            ],
            current_dataset_name=dataset.name,
            parent=self,
        )
        if dialog.exec() != ColumnMathDialog.Accepted:
            return

        self._run_column_math_batch(
            current_dataset=dataset,
            dialog=dialog,
            operation_key="derivative",
            operation_title="Derivative",
            methods=DERIVATIVE_METHODS,
            initial_value=None,
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
            default_x_column=self._preferred_dataset_column(dataset, ("x",), fallback_index=0),
            default_y_column=self._preferred_dataset_column(dataset, ("y",), fallback_index=1),
            dataset_names=[
                candidate.name
                for candidate in self._workspace.list_datasets()
                if len(candidate.frame.columns) > 0
            ],
            current_dataset_name=dataset.name,
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

        self._run_column_math_batch(
            current_dataset=dataset,
            dialog=dialog,
            operation_key="integral",
            operation_title="Integral",
            methods=INTEGRATION_METHODS,
            initial_value=initial_value or 0.0,
        )

    def _run_column_math_batch(
        self,
        current_dataset: Dataset,
        dialog: ColumnMathDialog,
        operation_key: str,
        operation_title: str,
        methods: dict[str, str],
        initial_value: float | None,
    ) -> None:
        """Run a derivative/integral operation on one or more worksheets."""
        target_dataset_names = dialog.target_dataset_names()
        target_plan = self._formula_batch_target_plan(
            target_dataset_names=target_dataset_names,
            target_column=dialog.target_column(),
            conflict_policy=dialog.target_conflict_policy(),
        )
        if not self._confirm_column_math_batch_target_plan(
            target_plan,
            dialog.target_conflict_policy(),
            operation_title,
        ):
            return

        results: list[dict[str, object]] = []
        current_result_target = ""
        for plan_row in target_plan:
            target_dataset_name = str(plan_row["source_sheet"])
            started = time.perf_counter()
            try:
                target_dataset = self._workspace.get_dataset(target_dataset_name)
                use_visible_model = target_dataset.name == current_dataset.name
                result = self._apply_column_math_to_dataset(
                    dataset=target_dataset,
                    operation_key=operation_key,
                    x_column=dialog.x_column(),
                    y_column=dialog.y_column(),
                    method=dialog.method(),
                    target_column=str(plan_row["target_column"]),
                    initial_value=initial_value,
                    use_visible_model=use_visible_model,
                    methods=methods,
                    operation_title=operation_title,
                )
                if use_visible_model:
                    current_result_target = result.column_name
                results.append(
                    self._column_math_batch_summary_row(
                        dataset=target_dataset,
                        operation_title=operation_title,
                        x_column=dialog.x_column(),
                        y_column=dialog.y_column(),
                        method=dialog.method(),
                        method_label=methods.get(dialog.method(), dialog.method()),
                        initial_value=initial_value,
                        result_column=result.column_name,
                        values_written=result.values_written,
                        status="ok",
                        error="",
                        requested_target_column=dialog.target_column(),
                        output_action=str(plan_row["output_action"]),
                        target_existed_before=bool(plan_row["target_existed_before"]),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            except MathOperationError as exc:
                results.append(
                    self._column_math_batch_summary_row(
                        dataset_name=target_dataset_name,
                        operation_title=operation_title,
                        x_column=dialog.x_column(),
                        y_column=dialog.y_column(),
                        method=dialog.method(),
                        method_label=methods.get(dialog.method(), dialog.method()),
                        initial_value=initial_value,
                        result_column=str(plan_row["target_column"]),
                        values_written=0,
                        status="failed",
                        error=str(exc),
                        requested_target_column=dialog.target_column(),
                        output_action=str(plan_row["output_action"]),
                        target_existed_before=bool(plan_row["target_existed_before"]),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            except Exception as exc:
                results.append(
                    self._column_math_batch_summary_row(
                        dataset_name=target_dataset_name,
                        operation_title=operation_title,
                        x_column=dialog.x_column(),
                        y_column=dialog.y_column(),
                        method=dialog.method(),
                        method_label=methods.get(dialog.method(), dialog.method()),
                        initial_value=initial_value,
                        result_column=str(plan_row["target_column"]),
                        values_written=0,
                        status="failed",
                        error=str(exc),
                        requested_target_column=dialog.target_column(),
                        output_action=str(plan_row["output_action"]),
                        target_existed_before=bool(plan_row["target_existed_before"]),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )

        success_count = sum(1 for row in results if row["status"] == "ok")
        failure_rows = [row for row in results if row["status"] != "ok"]
        summary_dataset = None
        if len(target_dataset_names) > 1:
            summary_dataset = self._workspace.add_dataset(
                f"{current_dataset.name}_{operation_key}_batch_summary",
                pd.DataFrame(results),
            )
            self._dataset_list.addItem(summary_dataset.name)

        self._dataset_model.set_dataset(current_dataset)
        self._resize_dataset_columns_to_contents(current_dataset)
        self._plot_tab_widget.refresh_controls(current_dataset.name)
        self._update_dataset_summary()
        if current_result_target:
            self._select_column(current_result_target)

        if success_count == 0:
            message = "\n".join(f"{row['source_sheet']}: {row['error']}" for row in failure_rows[:8])
            if summary_dataset is not None:
                message = f"{message}\n\nSummary saved as '{summary_dataset.name}'."
            QMessageBox.warning(self, f"{operation_title} Failed", message or f"{operation_title} failed.")
            return

        if current_result_target and dialog.plot_result_immediately():
            self._plot_tab_widget.queue_analysis_plot(
                dataset=current_dataset,
                x_column=dialog.x_column(),
                source_column=dialog.y_column(),
                result_column=current_result_target,
                title=operation_title,
            )
            self._tabs.setCurrentWidget(self._plot_tab_widget)

        if failure_rows:
            detail = "\n".join(f"{row['source_sheet']}: {row['error']}" for row in failure_rows[:8])
            QMessageBox.warning(
                self,
                f"{operation_title} Batch",
                f"Applied {operation_title.lower()} to {success_count} sheet(s); "
                f"{len(failure_rows)} failed.\n\n{detail}",
            )
        self.statusBar().showMessage(
            self._column_math_batch_status_message(
                operation_title=operation_title,
                success_count=success_count,
                failure_count=len(failure_rows),
                summary_dataset_name=summary_dataset.name if summary_dataset else "",
            )
        )

    def _apply_column_math_to_dataset(
        self,
        dataset: Dataset,
        operation_key: str,
        x_column: str,
        y_column: str,
        method: str,
        target_column: str,
        initial_value: float | None,
        use_visible_model: bool,
        methods: dict[str, str],
        operation_title: str,
    ):
        """Apply a derivative/integral operation to one dataset."""
        if use_visible_model:
            self._dataset_model.capture_undo_state()
        try:
            if operation_key == "derivative":
                result = derivative_column(
                    dataset.frame,
                    x_column=x_column,
                    y_column=y_column,
                    method=method,
                    target_column=target_column,
                )
            elif operation_key == "integral":
                result = integral_column(
                    dataset.frame,
                    x_column=x_column,
                    y_column=y_column,
                    method=method,
                    target_column=target_column,
                    initial_value=initial_value or 0.0,
                )
            else:
                raise MathOperationError(f"Unsupported column math operation: {operation_key}")
        except Exception:
            if use_visible_model:
                self._dataset_model.discard_latest_undo_state()
            raise

        set_column_operation_comment(
            dataset,
            result.column_name,
            self._column_math_operation_comment(
                operation_title=operation_title,
                x_column=x_column,
                y_column=y_column,
                method=method,
                method_label=methods.get(method, method),
                initial_value=initial_value,
            ),
        )
        dataset.prune_column_metadata()
        if use_visible_model:
            self._dataset_model.history_changed.emit()
        return result

    @staticmethod
    def _column_math_operation_comment(
        operation_title: str,
        x_column: str,
        y_column: str,
        method: str,
        method_label: str,
        initial_value: float | None,
    ) -> str:
        """Return a provenance comment for derivative/integral output columns."""
        comment = f"{operation_title}: y={y_column}, x={x_column}, method={method_label or method}"
        if initial_value is not None:
            comment = f"{comment}, initial={initial_value:g}"
        return comment

    def _confirm_column_math_batch_target_plan(
        self,
        plan_rows: list[dict[str, object]],
        conflict_policy: str,
        operation_title: str,
    ) -> bool:
        """Confirm derivative/integral target-column conflicts."""
        blocked_rows = [row for row in plan_rows if row["output_action"] == "blocked"]
        if blocked_rows:
            detail = self._formula_batch_plan_detail(blocked_rows)
            QMessageBox.warning(
                self,
                f"{operation_title} Output Conflict",
                (
                    "The target column already exists in one or more selected sheets.\n\n"
                    f"{detail}\n\n"
                    "Choose a different target column or change the target-exists policy."
                ),
            )
            return False

        conflict_rows = [row for row in plan_rows if row["target_existed_before"]]
        if not conflict_rows:
            return True

        detail = self._formula_batch_plan_detail(conflict_rows)
        if conflict_policy == "overwrite":
            reply = QMessageBox.question(
                self,
                f"Confirm {operation_title} Overwrite",
                (
                    f"This {operation_title.lower()} batch will overwrite or update existing "
                    "target columns.\n"
                    "Non-visible batch target sheets do not yet have worksheet-level undo.\n\n"
                    f"{detail}\n\n"
                    "Continue?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return reply == QMessageBox.Yes

        reply = QMessageBox.question(
            self,
            f"{operation_title} Output Names",
            (
                "The requested target column already exists in one or more selected sheets.\n"
                "JASC will create unique new columns instead of overwriting data.\n\n"
                f"{detail}\n\n"
                "Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        return reply == QMessageBox.Yes

    def _column_math_batch_summary_row(
        self,
        operation_title: str,
        x_column: str,
        y_column: str,
        method: str,
        method_label: str,
        initial_value: float | None,
        result_column: str,
        values_written: int,
        status: str,
        error: str,
        dataset: Dataset | None = None,
        dataset_name: str = "",
        requested_target_column: str = "",
        output_action: str = "",
        target_existed_before: bool = False,
        elapsed_seconds: float = 0.0,
    ) -> dict[str, object]:
        """Return one derivative/integral batch summary row."""
        source_sheet = dataset.name if dataset is not None else dataset_name
        row: dict[str, object] = {
            "source_sheet": source_sheet,
            "operation": operation_title,
            "x_column": x_column,
            "y_column": y_column,
            "method": method,
            "method_label": method_label,
            "initial_value": np.nan if initial_value is None else initial_value,
            "requested_target_column": requested_target_column or result_column,
            "target_column": result_column,
            "output_action": output_action,
            "target_existed_before": target_existed_before,
            "values_written": values_written,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
            "row_count": len(dataset.frame) if dataset is not None else 0,
            "finite_count": np.nan,
            "missing_or_non_numeric": np.nan,
            "minimum": np.nan,
            "maximum": np.nan,
            "mean": np.nan,
        }
        if dataset is None or result_column not in dataset.frame.columns:
            return row

        values = pd.to_numeric(dataset.frame[result_column], errors="coerce")
        values = values.replace([np.inf, -np.inf], np.nan)
        finite_values = values.dropna()
        row["finite_count"] = int(len(finite_values))
        row["missing_or_non_numeric"] = int(len(values) - len(finite_values))
        if not finite_values.empty:
            row["minimum"] = float(finite_values.min())
            row["maximum"] = float(finite_values.max())
            row["mean"] = float(finite_values.mean())
        return row

    @staticmethod
    def _column_math_batch_status_message(
        operation_title: str,
        success_count: int,
        failure_count: int,
        summary_dataset_name: str,
    ) -> str:
        """Return a concise derivative/integral batch status message."""
        if summary_dataset_name:
            return (
                f"{operation_title} applied to {success_count} sheet(s), "
                f"{failure_count} failed; summary saved as '{summary_dataset_name}'"
            )
        if failure_count:
            return f"{operation_title} applied to {success_count} sheet(s), {failure_count} failed"
        return f"{operation_title} saved for {success_count} sheet(s)"

    def _run_interpolation(self) -> None:
        """Run the interpolation workflow and create a prediction dataset."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Interpolation", "Select a dataset before interpolating.")
            return

        default_x = self._preferred_dataset_column(dataset, ("x",), fallback_index=0)
        default_y = self._preferred_dataset_column(dataset, ("y",), fallback_index=1)
        default_z = self._preferred_dataset_column(dataset, ("z",), fallback_index=2)
        dialog = InterpolationDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_dataset_name=dataset.name,
            column_ranges=self._numeric_column_ranges(dataset),
            default_x_column=default_x,
            default_y_column=default_y,
            default_z_column=default_z,
            default_value_column=default_y,
            parent=self,
        )
        if dialog.exec() != InterpolationDialog.Accepted:
            return

        try:
            if dialog.query_mode() == "generated":
                query_points = generated_query_points(
                    dialog.generated_ranges(),
                    mesh=dialog.mode() == "2d",
                )
            elif dialog.query_mode() == "columns":
                query_points = query_points_from_columns(dataset.frame, dialog.query_columns())
            else:
                query_points = query_points_from_text(
                    dialog.manual_points_text(),
                    dimension=len(dialog.coordinate_columns()),
                )

            result_frame = interpolate_dataset(
                dataset.frame,
                coordinate_columns=dialog.coordinate_columns(),
                value_column=dialog.value_column(),
                query_points=query_points,
                method=dialog.method_key(),
                fill_policy=dialog.fill_policy(),
                smoothing=dialog.smoothing(),
                epsilon=dialog.epsilon(),
            )
            result_dataset = self._workspace.add_dataset(
                dialog.target_dataset_name() or f"{dataset.name}_interpolation",
                result_frame,
            )
            self._apply_interpolation_metadata(
                source_dataset=dataset,
                result_dataset=result_dataset,
                coordinate_columns=dialog.coordinate_columns(),
                value_column=dialog.value_column(),
            )
            prediction_column = f"{dialog.value_column()}_interpolated"
            set_dataset_operation_comments(
                result_dataset,
                (
                    f"Interpolation: value={dialog.value_column()}, "
                    f"coordinates={', '.join(dialog.coordinate_columns())}, "
                    f"method={dialog.method_key()}, query={dialog.query_mode()}, "
                    f"outside={dialog.fill_policy()}"
                ),
                (prediction_column,),
            )
        except MathOperationError as exc:
            QMessageBox.warning(self, "Interpolation Failed", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Interpolation Failed", str(exc))
            return

        self._refresh_dataset_list(result_dataset.name)
        self.statusBar().showMessage(
            f"Interpolation saved as '{result_dataset.name}' ({len(result_dataset.frame)} row(s))"
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
            default_signal_column=self._preferred_dataset_column(dataset, ("y", "z"), fallback_index=1),
            default_x_column=self._preferred_dataset_column(dataset, ("x",), fallback_index=0),
            dataset_names=[
                candidate.name
                for candidate in self._workspace.list_datasets()
                if len(candidate.frame.columns) > 0
            ],
            current_dataset_name=dataset.name,
            parent=self,
        )
        if dialog.exec() != FFTDialog.Accepted:
            return

        self._run_fft_batch(dataset, dialog)

    def _run_ifft(self) -> None:
        """Run the inverse FFT workflow and create a reconstructed dataset."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Inverse FFT", "Select a dataset before running inverse FFT.")
            return

        dialog = IFFTDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_dataset_name=dataset.name,
            dataset_names=[
                candidate.name
                for candidate in self._workspace.list_datasets()
                if len(candidate.frame.columns) > 0
            ],
            current_dataset_name=dataset.name,
            parent=self,
        )
        if dialog.exec() != IFFTDialog.Accepted:
            return

        self._run_ifft_batch(dataset, dialog)

    def _run_fft_batch(self, current_dataset: Dataset, dialog: FFTDialog) -> None:
        """Run FFT on one or more worksheets and create result sheets."""
        target_dataset_names = dialog.target_dataset_names()
        result_datasets: list[Dataset] = []
        current_result_dataset: Dataset | None = None
        results: list[dict[str, object]] = []

        for source_name in target_dataset_names:
            started = time.perf_counter()
            result_dataset_name = self._batch_result_dataset_name(
                source_name=source_name,
                requested_name=dialog.target_dataset_name(),
                current_dataset_name=current_dataset.name,
                default_suffix="FFT",
            )
            try:
                source_dataset = self._workspace.get_dataset(source_name)
                result_frame = fft_dataset(
                    source_dataset.frame,
                    signal_column=dialog.signal_column(),
                    x_column=dialog.x_column(),
                    window_method=dialog.window_method(),
                )
                result_dataset = self._workspace.add_dataset(result_dataset_name, result_frame)
                result_datasets.append(result_dataset)
                if source_dataset.name == current_dataset.name:
                    current_result_dataset = result_dataset
                set_dataset_operation_comments(
                    result_dataset,
                    self._fft_operation_comment(
                        signal_column=dialog.signal_column(),
                        x_column=dialog.x_column(),
                        window_method=dialog.window_method(),
                    ),
                )
                results.append(
                    self._fft_batch_summary_row(
                        source_dataset=source_dataset,
                        operation="FFT",
                        signal_column=dialog.signal_column(),
                        x_column=dialog.x_column(),
                        window_method=dialog.window_method(),
                        requested_result_sheet=result_dataset_name,
                        output_sheet=result_dataset.name,
                        result_frame=result_frame,
                        status="ok",
                        error="",
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            except MathOperationError as exc:
                results.append(
                    self._fft_batch_summary_row(
                        source_sheet=source_name,
                        operation="FFT",
                        signal_column=dialog.signal_column(),
                        x_column=dialog.x_column(),
                        window_method=dialog.window_method(),
                        requested_result_sheet=result_dataset_name,
                        output_sheet="",
                        status="failed",
                        error=str(exc),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            except Exception as exc:
                results.append(
                    self._fft_batch_summary_row(
                        source_sheet=source_name,
                        operation="FFT",
                        signal_column=dialog.signal_column(),
                        x_column=dialog.x_column(),
                        window_method=dialog.window_method(),
                        requested_result_sheet=result_dataset_name,
                        output_sheet="",
                        status="failed",
                        error=str(exc),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )

        summary_dataset = self._add_signal_batch_summary_dataset(
            current_dataset=current_dataset,
            operation_key="FFT",
            target_dataset_names=target_dataset_names,
            results=results,
        )
        self._finish_signal_batch(
            operation_title="FFT",
            target_dataset_names=target_dataset_names,
            result_datasets=result_datasets,
            current_result_dataset=current_result_dataset,
            summary_dataset=summary_dataset,
            results=results,
            plot_result=dialog.plot_result_immediately(),
            plot_x_column="frequency",
            plot_y_column="magnitude",
            plot_title="FFT magnitude",
            plot_label="Magnitude",
        )

    def _run_ifft_batch(self, current_dataset: Dataset, dialog: IFFTDialog) -> None:
        """Run inverse FFT on one or more worksheets and create result sheets."""
        target_dataset_names = dialog.target_dataset_names()
        result_datasets: list[Dataset] = []
        current_result_dataset: Dataset | None = None
        results: list[dict[str, object]] = []

        for source_name in target_dataset_names:
            started = time.perf_counter()
            result_dataset_name = self._batch_result_dataset_name(
                source_name=source_name,
                requested_name=dialog.target_dataset_name(),
                current_dataset_name=current_dataset.name,
                default_suffix="iFFT",
            )
            try:
                source_dataset = self._workspace.get_dataset(source_name)
                result_frame = ifft_dataset(
                    source_dataset.frame,
                    real_column=dialog.real_column(),
                    imaginary_column=dialog.imaginary_column(),
                )
                result_dataset = self._workspace.add_dataset(result_dataset_name, result_frame)
                result_datasets.append(result_dataset)
                if source_dataset.name == current_dataset.name:
                    current_result_dataset = result_dataset
                set_dataset_operation_comments(
                    result_dataset,
                    self._ifft_operation_comment(
                        real_column=dialog.real_column(),
                        imaginary_column=dialog.imaginary_column(),
                    ),
                )
                results.append(
                    self._ifft_batch_summary_row(
                        source_dataset=source_dataset,
                        real_column=dialog.real_column(),
                        imaginary_column=dialog.imaginary_column(),
                        requested_result_sheet=result_dataset_name,
                        output_sheet=result_dataset.name,
                        result_frame=result_frame,
                        status="ok",
                        error="",
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            except MathOperationError as exc:
                results.append(
                    self._ifft_batch_summary_row(
                        source_sheet=source_name,
                        real_column=dialog.real_column(),
                        imaginary_column=dialog.imaginary_column(),
                        requested_result_sheet=result_dataset_name,
                        output_sheet="",
                        status="failed",
                        error=str(exc),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            except Exception as exc:
                results.append(
                    self._ifft_batch_summary_row(
                        source_sheet=source_name,
                        real_column=dialog.real_column(),
                        imaginary_column=dialog.imaginary_column(),
                        requested_result_sheet=result_dataset_name,
                        output_sheet="",
                        status="failed",
                        error=str(exc),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )

        summary_dataset = self._add_signal_batch_summary_dataset(
            current_dataset=current_dataset,
            operation_key="iFFT",
            target_dataset_names=target_dataset_names,
            results=results,
        )
        self._finish_signal_batch(
            operation_title="Inverse FFT",
            target_dataset_names=target_dataset_names,
            result_datasets=result_datasets,
            current_result_dataset=current_result_dataset,
            summary_dataset=summary_dataset,
            results=results,
            plot_result=dialog.plot_result_immediately(),
            plot_x_column="sample",
            plot_y_column="real",
            plot_title="Inverse FFT",
            plot_label="Reconstructed real",
        )

    def _add_signal_batch_summary_dataset(
        self,
        current_dataset: Dataset,
        operation_key: str,
        target_dataset_names: list[str],
        results: list[dict[str, object]],
    ) -> Dataset | None:
        """Create a cumulative FFT/iFFT batch summary when multiple sheets were selected."""
        if len(target_dataset_names) <= 1:
            return None
        return self._workspace.add_dataset(
            f"{current_dataset.name}_{operation_key}_batch_summary",
            pd.DataFrame(results),
        )

    def _finish_signal_batch(
        self,
        operation_title: str,
        target_dataset_names: list[str],
        result_datasets: list[Dataset],
        current_result_dataset: Dataset | None,
        summary_dataset: Dataset | None,
        results: list[dict[str, object]],
        plot_result: bool,
        plot_x_column: str,
        plot_y_column: str,
        plot_title: str,
        plot_label: str,
    ) -> None:
        """Refresh UI, plot the active result, and report FFT/iFFT batch status."""
        success_count = sum(1 for row in results if row["status"] == "ok")
        failure_rows = [row for row in results if row["status"] != "ok"]
        selected_name = ""
        if current_result_dataset is not None:
            selected_name = current_result_dataset.name
        elif result_datasets:
            selected_name = result_datasets[0].name
        elif summary_dataset is not None:
            selected_name = summary_dataset.name

        if selected_name:
            self._refresh_dataset_list(selected_name)
        else:
            self._update_dataset_summary()

        if success_count == 0:
            message = "\n".join(f"{row['source_sheet']}: {row['error']}" for row in failure_rows[:8])
            if summary_dataset is not None:
                message = f"{message}\n\nSummary saved as '{summary_dataset.name}'."
            QMessageBox.warning(
                self,
                f"{operation_title} Failed",
                message or f"{operation_title} failed on every selected sheet.",
            )
            return

        if current_result_dataset is not None and plot_result:
            self._plot_tab_widget.queue_single_series_plot(
                dataset=current_result_dataset,
                x_column=plot_x_column,
                y_column=plot_y_column,
                title=plot_title,
                label=plot_label,
            )
            self._tabs.setCurrentWidget(self._plot_tab_widget)

        if failure_rows:
            detail = "\n".join(f"{row['source_sheet']}: {row['error']}" for row in failure_rows[:8])
            QMessageBox.warning(
                self,
                f"{operation_title} Batch",
                f"Created {success_count} result sheet(s); {len(failure_rows)} failed.\n\n{detail}",
            )
        self.statusBar().showMessage(
            self._signal_batch_status_message(
                operation_title=operation_title,
                success_count=success_count,
                failure_count=len(failure_rows),
                summary_dataset_name=summary_dataset.name if summary_dataset else "",
            )
        )

    @staticmethod
    def _batch_result_dataset_name(
        source_name: str,
        requested_name: str,
        current_dataset_name: str,
        default_suffix: str,
    ) -> str:
        """Return a per-source result-sheet name for batch-created datasets."""
        clean_requested = requested_name.strip()
        default_current_name = f"{current_dataset_name}_{default_suffix}"
        if not clean_requested:
            return f"{source_name}_{default_suffix}"
        if "{source}" in clean_requested:
            return clean_requested.replace("{source}", source_name)
        if source_name == current_dataset_name:
            return clean_requested
        if clean_requested == default_current_name:
            return f"{source_name}_{default_suffix}"
        return f"{source_name}_{clean_requested}"

    @staticmethod
    def _fft_operation_comment(
        signal_column: str,
        x_column: str | None,
        window_method: str,
    ) -> str:
        """Return a compact provenance comment for FFT result sheets."""
        return f"FFT: signal={signal_column}, x={x_column or 'sample index'}, window={window_method}"

    @staticmethod
    def _ifft_operation_comment(real_column: str, imaginary_column: str | None) -> str:
        """Return a compact provenance comment for inverse FFT result sheets."""
        return f"Inverse FFT: real={real_column}, imaginary={imaginary_column or '0'}"

    def _fft_batch_summary_row(
        self,
        operation: str,
        signal_column: str,
        x_column: str | None,
        window_method: str,
        requested_result_sheet: str,
        output_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        result_frame: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        """Return one FFT batch summary row."""
        metrics = self._fft_result_metrics(source_dataset, result_frame, signal_column, x_column)
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": operation,
            "signal_column": signal_column,
            "x_column": x_column or "sample index",
            "window": window_method,
            "window_label": WINDOW_METHODS.get(window_method, window_method),
            "requested_result_sheet": requested_result_sheet,
            "output_sheet": output_sheet,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
        }
        row.update(metrics)
        return row

    @staticmethod
    def _fft_result_metrics(
        source_dataset: Dataset | None,
        result_frame: pd.DataFrame | None,
        signal_column: str,
        x_column: str | None,
    ) -> dict[str, object]:
        """Return quality metrics for one FFT result."""
        metrics: dict[str, object] = {
            "source_row_count": len(source_dataset.frame) if source_dataset is not None else 0,
            "sample_count": len(result_frame) if result_frame is not None else 0,
            "sample_spacing": np.nan,
            "dominant_frequency": np.nan,
            "dominant_amplitude": np.nan,
            "total_spectral_power": np.nan,
        }
        if source_dataset is not None:
            metrics["sample_spacing"] = MainWindow._estimate_fft_sample_spacing(
                source_dataset,
                signal_column,
                x_column,
            )
        if result_frame is None or result_frame.empty or "magnitude" not in result_frame:
            return metrics

        magnitudes = pd.to_numeric(result_frame["magnitude"], errors="coerce")
        magnitudes = magnitudes.replace([np.inf, -np.inf], np.nan).dropna()
        if magnitudes.empty:
            return metrics

        dominant_index = magnitudes.idxmax()
        metrics["dominant_amplitude"] = float(magnitudes.loc[dominant_index])
        if "frequency" in result_frame:
            frequency = pd.to_numeric(result_frame.loc[[dominant_index], "frequency"], errors="coerce")
            if not frequency.empty and pd.notna(frequency.iloc[0]):
                metrics["dominant_frequency"] = float(frequency.iloc[0])
        metrics["total_spectral_power"] = float(np.square(magnitudes.to_numpy(dtype=float)).sum())
        return metrics

    @staticmethod
    def _estimate_fft_sample_spacing(
        source_dataset: Dataset,
        signal_column: str,
        x_column: str | None,
    ) -> float:
        """Estimate sample spacing for the FFT batch summary."""
        if not x_column:
            return 1.0
        if x_column not in source_dataset.frame.columns or signal_column not in source_dataset.frame.columns:
            return float("nan")
        x_values = pd.to_numeric(source_dataset.frame[x_column], errors="coerce")
        y_values = pd.to_numeric(source_dataset.frame[signal_column], errors="coerce")
        aligned = pd.DataFrame({"x": x_values, "y": y_values}).dropna()
        if len(aligned) < 2:
            return float("nan")
        spacing = np.diff(aligned["x"].to_numpy(dtype=float))
        if len(spacing) == 0:
            return float("nan")
        return float(np.median(np.abs(spacing)))

    def _ifft_batch_summary_row(
        self,
        real_column: str,
        imaginary_column: str | None,
        requested_result_sheet: str,
        output_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        result_frame: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        """Return one inverse FFT batch summary row."""
        metrics = self._ifft_result_metrics(source_dataset, result_frame)
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": "Inverse FFT",
            "real_column": real_column,
            "imaginary_column": imaginary_column or "0",
            "requested_result_sheet": requested_result_sheet,
            "output_sheet": output_sheet,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
        }
        row.update(metrics)
        return row

    @staticmethod
    def _ifft_result_metrics(
        source_dataset: Dataset | None,
        result_frame: pd.DataFrame | None,
    ) -> dict[str, object]:
        """Return quality metrics for one inverse FFT result."""
        metrics: dict[str, object] = {
            "source_row_count": len(source_dataset.frame) if source_dataset is not None else 0,
            "reconstruction_count": len(result_frame) if result_frame is not None else 0,
            "finite_real_count": np.nan,
            "real_minimum": np.nan,
            "real_maximum": np.nan,
            "real_mean": np.nan,
            "maximum_magnitude": np.nan,
            "reconstructed_power": np.nan,
        }
        if result_frame is None or result_frame.empty:
            return metrics

        if "real" in result_frame:
            real_values = pd.to_numeric(result_frame["real"], errors="coerce")
            real_values = real_values.replace([np.inf, -np.inf], np.nan).dropna()
            metrics["finite_real_count"] = int(len(real_values))
            if not real_values.empty:
                real_array = real_values.to_numpy(dtype=float)
                metrics["real_minimum"] = float(real_values.min())
                metrics["real_maximum"] = float(real_values.max())
                metrics["real_mean"] = float(real_values.mean())
                metrics["reconstructed_power"] = float(np.square(real_array).sum())

        if "magnitude" in result_frame:
            magnitudes = pd.to_numeric(result_frame["magnitude"], errors="coerce")
            magnitudes = magnitudes.replace([np.inf, -np.inf], np.nan).dropna()
            if not magnitudes.empty:
                metrics["maximum_magnitude"] = float(magnitudes.max())
        return metrics

    @staticmethod
    def _signal_batch_status_message(
        operation_title: str,
        success_count: int,
        failure_count: int,
        summary_dataset_name: str,
    ) -> str:
        """Return a concise FFT/iFFT batch status message."""
        if summary_dataset_name:
            return (
                f"{operation_title} created {success_count} result sheet(s), "
                f"{failure_count} failed; summary saved as '{summary_dataset_name}'"
            )
        if failure_count:
            return f"{operation_title} created {success_count} result sheet(s), {failure_count} failed"
        return f"{operation_title} created {success_count} result sheet(s)"

    def _run_statistics(self) -> None:
        """Run a statistics workflow and create a result dataset."""
        selected_dataset = self._current_dataset()
        dataset_columns = {
            dataset.name: [str(column) for column in dataset.frame.columns]
            for dataset in self._workspace.list_datasets()
            if len(dataset.frame.columns) > 0
        }
        if not dataset_columns:
            QMessageBox.information(self, "Statistics", "Load or create a dataset before running statistics.")
            return

        default_dataset_name = (
            selected_dataset.name
            if selected_dataset is not None and selected_dataset.name in dataset_columns
            else next(iter(dataset_columns))
        )
        dialog = StatisticsDialog(
            dataset_columns=dataset_columns,
            default_dataset_name=default_dataset_name,
            parent=self,
        )
        if dialog.exec() != StatisticsDialog.Accepted:
            return

        secondary_dataset = None
        secondary_column = ""
        multi_columns: list[str] = []
        try:
            primary_dataset = self._workspace.get_dataset(dialog.primary_dataset_name())
            primary_column = dialog.primary_column()
            if dialog.operation_scope() == "multi":
                multi_columns = dialog.multi_columns()
                column_labels = {
                    column: self._statistics_column_label(primary_dataset, column)
                    for column in multi_columns
                }
                result_frame = run_multicolumn_statistical_analysis(
                    frame=primary_dataset.frame[multi_columns],
                    column_labels=column_labels,
                    operation_key=dialog.operation_key(),
                )
            else:
                secondary_series = None
                secondary_label = ""
                if dialog.requires_secondary_column():
                    secondary_dataset = self._workspace.get_dataset(dialog.secondary_dataset_name())
                    secondary_column = dialog.secondary_column()
                    secondary_series = secondary_dataset.frame[secondary_column]
                    secondary_label = f"{secondary_dataset.name}: {secondary_column}"

                primary_series = primary_dataset.frame[primary_column]
                result_frame = run_statistical_analysis(
                    primary=primary_series,
                    primary_label=f"{primary_dataset.name}: {primary_column}",
                    operation_key=dialog.operation_key(),
                    secondary=secondary_series,
                    secondary_label=secondary_label,
                )
            result_dataset = self._workspace.add_dataset(
                dialog.target_dataset_name() or f"{primary_dataset.name}_statistics",
                result_frame,
            )
            set_dataset_operation_comments(
                result_dataset,
                self._statistics_operation_comment(
                    operation_key=dialog.operation_key(),
                    primary_dataset=primary_dataset,
                    primary_column=primary_column,
                    secondary_dataset=secondary_dataset,
                    secondary_column=secondary_column,
                    multi_columns=multi_columns,
                ),
            )
        except KeyError as exc:
            QMessageBox.warning(self, "Statistics Failed", f"Selected data is no longer available: {exc}")
            return
        except MathOperationError as exc:
            QMessageBox.warning(self, "Statistics Failed", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Statistics Failed", str(exc))
            return

        self._refresh_dataset_list(result_dataset.name)
        if dialog.plot_result_immediately():
            try:
                self._queue_statistics_companion_plot(
                    primary_dataset=primary_dataset,
                    primary_column=primary_column,
                    secondary_dataset=secondary_dataset,
                    secondary_column=secondary_column,
                    result_dataset=result_dataset,
                    operation_key=dialog.operation_key(),
                    plot_kind=dialog.statistics_plot_kind(),
                    multi_columns=multi_columns,
                )
                self._refresh_dataset_list(result_dataset.name)
                self._tabs.setCurrentWidget(self._plot_tab_widget)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Statistics Plot",
                    f"Statistics results were saved, but the companion plot could not be created:\n{exc}",
                )
        self.statusBar().showMessage(
            f"Statistics saved as '{result_dataset.name}' ({len(result_dataset.frame)} rows)"
        )

    @staticmethod
    def _statistics_operation_comment(
        operation_key: str,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset | None,
        secondary_column: str,
        multi_columns: list[str],
    ) -> str:
        """Return a compact provenance comment for a statistics result sheet."""
        operation_label = STATISTIC_OPERATIONS[operation_key].label
        if multi_columns:
            inputs = f"{primary_dataset.name}: {', '.join(multi_columns)}"
        else:
            inputs = f"{primary_dataset.name}: {primary_column}"
            if secondary_dataset is not None and secondary_column:
                inputs = f"{inputs}; secondary={secondary_dataset.name}: {secondary_column}"
        return f"Statistics: operation={operation_label}, inputs={inputs}"

    def _queue_statistics_companion_plot(
        self,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset | None,
        secondary_column: str,
        result_dataset: Dataset,
        operation_key: str,
        plot_kind: str,
        multi_columns: list[str] | None = None,
    ) -> None:
        """Create an editable plot queue for a statistics result."""
        operation_scope = STATISTIC_OPERATIONS[operation_key].scope
        resolved_kind = self._resolve_statistics_plot_kind(
            operation_key,
            plot_kind,
            operation_scope=operation_scope,
        )
        operation_label = STATISTIC_OPERATIONS[operation_key].label
        title = f"Statistics: {operation_label}"
        primary_label = self._statistics_column_label(primary_dataset, primary_column)

        if operation_scope == "multi":
            selected_columns = multi_columns or []
            if len(selected_columns) < 2:
                raise ValueError("Choose at least two columns for multi-column statistics plots.")
            if resolved_kind in {"box", "violin"}:
                self._plot_tab_widget.queue_plot_series(
                    [
                        PlotSeries(
                            x_dataset=primary_dataset.name,
                            x_column="",
                            y_dataset=primary_dataset.name,
                            y_column=selected_columns[0],
                            plot_type=resolved_kind,
                            color="tab:blue",
                            fill_alpha=0.35,
                            distribution_columns=tuple(selected_columns),
                            distribution_show_mean=True,
                            distribution_show_median=True,
                            distribution_show_outliers=True,
                        )
                    ],
                    title=title,
                    x_label="Column",
                    y_label="Value",
                    selected_dataset_name=primary_dataset.name,
                )
                return
            if resolved_kind == "correlation_heatmap":
                heatmap_dataset = self._statistics_correlation_heatmap_dataset(
                    primary_dataset,
                    selected_columns,
                    result_dataset.name,
                )
                self._plot_tab_widget.queue_plot_series(
                    [
                        PlotSeries(
                            x_dataset=heatmap_dataset.name,
                            x_column="column_index",
                            y_dataset=heatmap_dataset.name,
                            y_column="row_index",
                            z_dataset=heatmap_dataset.name,
                            z_column="pearson_r",
                            plot_type="heatmap",
                            color="tab:blue",
                            interpolation_method="linear",
                            grid_resolution=max(40, min(160, len(selected_columns) * 24)),
                        )
                    ],
                    title=f"Correlation Heatmap: {primary_dataset.name}",
                    x_label="Column index",
                    y_label="Column index",
                    selected_dataset_name=heatmap_dataset.name,
                )
                return
            if resolved_kind == "pca_variance":
                pca_dataset = self._statistics_pca_variance_dataset(result_dataset)
                self._plot_tab_widget.queue_plot_series(
                    [
                        PlotSeries(
                            x_dataset=pca_dataset.name,
                            x_column="component",
                            y_dataset=pca_dataset.name,
                            y_column="explained_variance_ratio",
                            plot_type="bar",
                            color="tab:green",
                            fill_alpha=0.55,
                            custom_label="Explained variance ratio",
                        )
                    ],
                    title=f"PCA Explained Variance: {primary_dataset.name}",
                    x_label="Principal component",
                    y_label="Explained variance ratio",
                    selected_dataset_name=pca_dataset.name,
                )
                return
            raise ValueError("Unsupported multi-column statistics companion plot.")

        if operation_scope == "group":
            if secondary_dataset is None or not secondary_column:
                raise ValueError("Choose a group column for grouped statistics plots.")
            if resolved_kind not in {"box", "violin"}:
                raise ValueError("Grouped statistics companion plots support box or violin plots.")
            group_plot_dataset = self._statistics_group_distribution_dataset(
                primary_dataset,
                primary_column,
                secondary_dataset,
                secondary_column,
                result_dataset.name,
            )
            distribution_columns = tuple(str(column) for column in group_plot_dataset.frame.columns)
            self._plot_tab_widget.queue_plot_series(
                [
                    PlotSeries(
                        x_dataset=group_plot_dataset.name,
                        x_column="",
                        y_dataset=group_plot_dataset.name,
                        y_column=distribution_columns[0],
                        plot_type=resolved_kind,
                        color="tab:blue",
                        fill_alpha=0.35,
                        distribution_columns=distribution_columns,
                        distribution_show_mean=True,
                        distribution_show_median=True,
                        distribution_show_outliers=True,
                    )
                ],
                title=title,
                x_label="Group",
                y_label=primary_label,
                selected_dataset_name=group_plot_dataset.name,
            )
            return

        if resolved_kind == "result_series":
            result_column = "z_score" if operation_key == "single_zscore" else "cumulative_mean"
            if "row_index" not in result_dataset.frame.columns or result_column not in result_dataset.frame.columns:
                raise ValueError("This statistics result does not contain a plottable result series.")
            self._plot_tab_widget.queue_plot_series(
                [
                    PlotSeries(
                        x_dataset=result_dataset.name,
                        x_column="row_index",
                        y_dataset=result_dataset.name,
                        y_column=result_column,
                        plot_type="line",
                        color="tab:blue",
                        line_style="-",
                        marker="",
                        custom_label=result_column,
                    )
                ],
                title=title,
                x_label="Row index",
                y_label=result_column.replace("_", " ").title(),
                selected_dataset_name=result_dataset.name,
            )
            return

        if resolved_kind == "histogram":
            series = [
                PlotSeries(
                    x_dataset=primary_dataset.name,
                    x_column="",
                    y_dataset=primary_dataset.name,
                    y_column=primary_column,
                    plot_type="histogram",
                    color="tab:blue",
                    fill_alpha=0.35,
                    histogram_bins=30,
                    histogram_density=True,
                    custom_label=primary_label,
                )
            ]
            normal_dataset = self._statistics_normal_curve_dataset(primary_dataset, primary_column)
            if normal_dataset is not None:
                series.append(
                    PlotSeries(
                        x_dataset=normal_dataset.name,
                        x_column="value",
                        y_dataset=normal_dataset.name,
                        y_column="normal_density",
                        plot_type="line",
                        color="tab:red",
                        line_style="-",
                        marker="",
                        custom_label="Normal curve",
                    )
                )
            self._plot_tab_widget.queue_plot_series(
                series,
                title=title,
                x_label=primary_label,
                y_label="Density",
                selected_dataset_name=primary_dataset.name,
            )
            return

        if resolved_kind in {"box", "violin"}:
            plot_dataset = primary_dataset
            distribution_columns = (primary_column,)
            if secondary_dataset is not None and secondary_column:
                plot_dataset = self._statistics_comparison_dataset(
                    primary_dataset,
                    primary_column,
                    secondary_dataset,
                    secondary_column,
                    result_dataset.name,
                )
                distribution_columns = tuple(str(column) for column in plot_dataset.frame.columns)
            self._plot_tab_widget.queue_plot_series(
                [
                    PlotSeries(
                        x_dataset=plot_dataset.name,
                        x_column="",
                        y_dataset=plot_dataset.name,
                        y_column=distribution_columns[0],
                        plot_type=resolved_kind,
                        color="tab:blue",
                        fill_alpha=0.35,
                        distribution_columns=distribution_columns,
                        distribution_show_mean=True,
                        distribution_show_median=True,
                        distribution_show_outliers=True,
                    )
                ],
                title=title,
                x_label="Column",
                y_label="Value",
                selected_dataset_name=plot_dataset.name,
            )
            return

        if secondary_dataset is None or not secondary_column:
            raise ValueError("Choose a two-column statistics operation for this plot type.")

        secondary_label = self._statistics_column_label(secondary_dataset, secondary_column)
        if resolved_kind == "bland_altman":
            bland_dataset = self._statistics_bland_altman_dataset(
                primary_dataset,
                primary_column,
                secondary_dataset,
                secondary_column,
                result_dataset.name,
            )
            self._plot_tab_widget.queue_plot_series(
                [
                    PlotSeries(
                        x_dataset=bland_dataset.name,
                        x_column="mean",
                        y_dataset=bland_dataset.name,
                        y_column="difference",
                        plot_type="scatter",
                        color="tab:purple",
                        line_style="",
                        marker="o",
                        custom_label="Difference vs mean",
                    )
                ],
                title=f"Bland-Altman: {primary_label} vs {secondary_label}",
                x_label="Mean of paired values",
                y_label="Primary - secondary",
                selected_dataset_name=bland_dataset.name,
            )
            return

        series = [
            PlotSeries(
                x_dataset=primary_dataset.name,
                x_column=primary_column,
                y_dataset=secondary_dataset.name,
                y_column=secondary_column,
                plot_type="scatter",
                color="tab:blue",
                line_style="",
                marker="o",
                custom_label=f"{secondary_label} vs {primary_label}",
            )
        ]
        selected_dataset_name = primary_dataset.name
        if resolved_kind == "regression":
            regression_dataset = self._statistics_regression_line_dataset(
                primary_dataset,
                primary_column,
                secondary_dataset,
                secondary_column,
                result_dataset,
            )
            series.append(
                PlotSeries(
                    x_dataset=regression_dataset.name,
                    x_column="x",
                    y_dataset=regression_dataset.name,
                    y_column="fit",
                    plot_type="line",
                    color="tab:red",
                    line_style="-",
                    marker="",
                    custom_label="Regression line",
                )
            )
            selected_dataset_name = regression_dataset.name
        self._plot_tab_widget.queue_plot_series(
            series,
            title=title,
            x_label=primary_label,
            y_label=secondary_label,
            selected_dataset_name=selected_dataset_name,
        )

    @staticmethod
    def _resolve_statistics_plot_kind(
        operation_key: str,
        plot_kind: str,
        operation_scope: str,
    ) -> str:
        """Return a concrete companion plot kind for a statistics operation."""
        if plot_kind != "auto":
            return plot_kind
        if operation_scope == "group":
            return "box"
        if operation_scope == "multi":
            if operation_key == "multi_pca":
                return "pca_variance"
            if operation_key in {"multi_complete", "multi_correlations"}:
                return "correlation_heatmap"
            return "box"
        if operation_scope == "single":
            if operation_key in {"single_zscore", "single_cumulative"}:
                return "result_series"
            return "histogram"
        if operation_key == "pair_bland_altman":
            return "bland_altman"
        if operation_key == "pair_linear_regression":
            return "regression"
        if operation_key in {"pair_welch_ttest", "pair_mann_whitney", "pair_ks", "pair_variance_tests"}:
            return "box"
        return "scatter"

    def _statistics_normal_curve_dataset(self, dataset: Dataset, column: str) -> Dataset | None:
        """Create a normal PDF overlay dataset for a histogram when possible."""
        values = self._statistics_numeric_values(dataset, column)
        if len(values) < 2:
            return None
        mean = float(values.mean())
        std = float(values.std(ddof=1))
        if not np.isfinite(std) or std <= 0:
            return None
        x_min = float(values.min())
        x_max = float(values.max())
        if x_min == x_max:
            return None
        x_values = np.linspace(x_min, x_max, 200)
        density = np.exp(-0.5 * ((x_values - mean) / std) ** 2) / (std * np.sqrt(2 * np.pi))
        return self._workspace.add_dataset(
            f"{dataset.name}_{column}_normal_curve",
            pd.DataFrame({"value": x_values, "normal_density": density}),
        )

    def _statistics_comparison_dataset(
        self,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset,
        secondary_column: str,
        result_name: str,
    ) -> Dataset:
        """Create a two-column dataset suitable for box/violin comparisons."""
        primary_values = self._statistics_numeric_values(primary_dataset, primary_column).reset_index(drop=True)
        secondary_values = self._statistics_numeric_values(secondary_dataset, secondary_column).reset_index(drop=True)
        row_count = max(len(primary_values), len(secondary_values))
        primary_label = self._statistics_column_label(primary_dataset, primary_column)
        secondary_label = self._statistics_column_label(secondary_dataset, secondary_column)
        if primary_label == secondary_label:
            secondary_label = f"{secondary_label} 2"
        frame = pd.DataFrame(
            {
                primary_label: primary_values.reindex(range(row_count)),
                secondary_label: secondary_values.reindex(range(row_count)),
            }
        )
        return self._workspace.add_dataset(f"{result_name}_plot_data", frame)

    def _statistics_group_distribution_dataset(
        self,
        value_dataset: Dataset,
        value_column: str,
        group_dataset: Dataset,
        group_column: str,
        result_name: str,
    ) -> Dataset:
        """Create a wide dataset with one numeric column per group."""
        values = self._statistics_numeric_series(value_dataset, value_column)
        if group_column not in group_dataset.frame.columns:
            raise ValueError(f"Column '{group_column}' is no longer available.")
        groups = group_dataset.frame[group_column].reset_index(drop=True)
        paired = pd.DataFrame(
            {
                "value": values.reset_index(drop=True),
                "group": groups,
            }
        ).dropna(subset=["value", "group"])
        paired["group"] = paired["group"].astype(str).str.strip()
        paired = paired[paired["group"] != ""]
        if paired.empty:
            raise ValueError("No complete numeric/group rows are available for the grouped plot.")

        grouped_values: dict[str, pd.Series] = {}
        for group_name, group_frame in paired.groupby("group", sort=True):
            column_name = self._unique_plot_data_column(str(group_name), grouped_values)
            grouped_values[column_name] = group_frame["value"].astype(float).reset_index(drop=True)
        if len(grouped_values) < 2:
            raise ValueError("Grouped plots require at least two groups.")

        row_count = max(len(values) for values in grouped_values.values())
        frame = pd.DataFrame(
            {
                column_name: values.reindex(range(row_count))
                for column_name, values in grouped_values.items()
            }
        )
        return self._workspace.add_dataset(f"{result_name}_group_plot_data", frame)

    @staticmethod
    def _unique_plot_data_column(base_name: str, columns: dict[str, pd.Series]) -> str:
        """Return a unique column name for generated plot-helper datasets."""
        clean_name = base_name.strip() or "Group"
        if clean_name not in columns:
            return clean_name
        suffix = 2
        while f"{clean_name} {suffix}" in columns:
            suffix += 1
        return f"{clean_name} {suffix}"

    def _statistics_correlation_heatmap_dataset(
        self,
        dataset: Dataset,
        columns: list[str],
        result_name: str,
    ) -> Dataset:
        """Create X/Y/Z helper data for a Pearson correlation heatmap."""
        numeric = pd.DataFrame(
            {
                column: self._statistics_numeric_series(dataset, column)
                for column in columns
            }
        )
        correlation = numeric.corr(method="pearson", min_periods=2)
        rows: list[dict[str, object]] = []
        has_off_diagonal_value = False
        for row_index, row_column in enumerate(columns):
            for column_index, column in enumerate(columns):
                value = correlation.loc[row_column, column]
                if pd.isna(value):
                    continue
                if row_index != column_index:
                    has_off_diagonal_value = True
                rows.append(
                    {
                        "column_index": float(column_index),
                        "row_index": float(row_index),
                        "pearson_r": float(value),
                        "column": column,
                        "row": row_column,
                    }
                )
        if not rows or not has_off_diagonal_value:
            raise ValueError("Correlation heatmap requires at least two aligned numeric values.")
        return self._workspace.add_dataset(
            f"{result_name}_correlation_heatmap",
            pd.DataFrame(rows),
        )

    def _statistics_pca_variance_dataset(self, result_dataset: Dataset) -> Dataset:
        """Create component/variance helper data from a PCA statistics result."""
        required_columns = {"metric", "value"}
        if not required_columns.issubset(result_dataset.frame.columns):
            raise ValueError("PCA variance plot requires a statistics result with metric and value columns.")

        rows: list[dict[str, float]] = []
        for _index, row in result_dataset.frame.iterrows():
            metric = str(row.get("metric", ""))
            match = re.fullmatch(r"pc(\d+)_explained_variance_ratio", metric)
            if match is None:
                continue
            value = pd.to_numeric(pd.Series([row.get("value")]), errors="coerce").iloc[0]
            if pd.isna(value):
                continue
            rows.append(
                {
                    "component": float(match.group(1)),
                    "explained_variance_ratio": float(value),
                }
            )
        if not rows:
            raise ValueError("This statistics result does not contain PCA explained-variance rows.")
        return self._workspace.add_dataset(
            f"{result_dataset.name}_pca_variance",
            pd.DataFrame(rows),
        )

    def _statistics_bland_altman_dataset(
        self,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset,
        secondary_column: str,
        result_name: str,
    ) -> Dataset:
        """Create paired mean/difference data for a Bland-Altman companion plot."""
        paired = self._statistics_aligned_pair(
            primary_dataset,
            primary_column,
            secondary_dataset,
            secondary_column,
            minimum_points=2,
        )
        mean_values = paired.mean(axis=1)
        difference_values = paired["primary"] - paired["secondary"]
        frame = pd.DataFrame(
            {
                "mean": mean_values.to_numpy(dtype=float),
                "difference": difference_values.to_numpy(dtype=float),
            }
        )
        return self._workspace.add_dataset(f"{result_name}_bland_altman", frame)

    def _statistics_regression_line_dataset(
        self,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset,
        secondary_column: str,
        result_dataset: Dataset,
    ) -> Dataset:
        """Create an OLS regression line dataset from aligned numeric pairs."""
        paired = self._statistics_aligned_pair(
            primary_dataset,
            primary_column,
            secondary_dataset,
            secondary_column,
            minimum_points=2,
        )
        x_min = float(paired["primary"].min())
        x_max = float(paired["primary"].max())
        if x_min == x_max:
            raise ValueError("Regression companion plot needs non-constant primary X values.")
        slope, intercept = np.polyfit(
            paired["primary"].to_numpy(dtype=float),
            paired["secondary"].to_numpy(dtype=float),
            1,
        )
        x_values = np.linspace(x_min, x_max, 200)
        frame = pd.DataFrame({"x": x_values, "fit": slope * x_values + intercept})
        return self._workspace.add_dataset(f"{result_dataset.name}_regression_line", frame)

    @staticmethod
    def _statistics_numeric_values(dataset: Dataset, column: str) -> pd.Series:
        """Return finite numeric values for one dataset column."""
        if column not in dataset.frame.columns:
            raise ValueError(f"Column '{column}' is no longer available.")
        values = pd.to_numeric(dataset.frame[column], errors="coerce")
        values = values[
            values.notna()
            & (values != float("inf"))
            & (values != float("-inf"))
        ]
        if values.empty:
            raise ValueError(f"{dataset.name}: {column} has no numeric values to plot.")
        return values.astype(float)

    def _statistics_aligned_pair(
        self,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset,
        secondary_column: str,
        minimum_points: int,
    ) -> pd.DataFrame:
        """Return row-position-aligned numeric values for two columns."""
        primary_values = self._statistics_numeric_series(primary_dataset, primary_column)
        secondary_values = self._statistics_numeric_series(secondary_dataset, secondary_column)
        paired = pd.DataFrame(
            {
                "primary": primary_values.reset_index(drop=True),
                "secondary": secondary_values.reset_index(drop=True),
            }
        ).dropna()
        if len(paired) < minimum_points:
            raise ValueError(f"Need at least {minimum_points} aligned numeric pair(s) to plot this statistic.")
        return paired

    @staticmethod
    def _statistics_numeric_series(dataset: Dataset, column: str) -> pd.Series:
        """Return a numeric series preserving blanks as NaN for alignment."""
        if column not in dataset.frame.columns:
            raise ValueError(f"Column '{column}' is no longer available.")
        return pd.to_numeric(dataset.frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)

    @staticmethod
    def _statistics_column_label(dataset: Dataset, column: str) -> str:
        """Return a compact label for statistics companion plots."""
        metadata = dataset.column_metadata.get(column)
        label = metadata.long_name if metadata is not None and metadata.long_name else column
        if metadata is not None and metadata.unit:
            label = f"{label} ({metadata.unit})"
        return f"{dataset.name}: {label}"

    def _manage_custom_fit_models(self) -> None:
        """Open the project custom fit model manager."""
        dialog = CustomFitModelsDialog(
            models=self._workspace.list_custom_fit_models(),
            parent=self,
        )
        if dialog.exec() != CustomFitModelsDialog.Accepted:
            return
        self._workspace.set_custom_fit_models(dialog.custom_models())
        self._update_dataset_summary()
        self.statusBar().showMessage(
            f"Custom fit models updated ({len(self._workspace.list_custom_fit_models())})"
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
            custom_models=self._workspace.list_custom_fit_models(),
            default_x_column=self._preferred_dataset_column(dataset, ("x",), fallback_index=0),
            default_y_column=self._preferred_dataset_column(dataset, ("y",), fallback_index=1),
            default_x_weight_column=self._preferred_dataset_column(dataset, ("x_error",), fallback_index=None),
            default_y_weight_column=self._preferred_dataset_column(dataset, ("y_error", "error"), fallback_index=None),
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
                x_weight_column=dialog.x_weight_column(),
                custom_models=self._workspace.list_custom_fit_models(),
            )
            result_dataset = self._workspace.add_dataset(
                dialog.target_dataset_name() or f"{dataset.name}_fit",
                result.fit_frame,
            )
            fit_operation_comment = (
                f"Curve fit: y={dialog.y_column()}, x={dialog.x_column()}, "
                f"model={result.report.model_name}, method={dialog.method()}"
            )
            set_dataset_operation_comments(result_dataset, fit_operation_comment)
            residual_dataset = None
            if dialog.create_residual_sheet() or dialog.plot_residuals():
                residual_dataset = self._workspace.add_dataset(
                    dialog.residual_dataset_name() or f"{dataset.name}_residuals",
                    result.residual_frame,
                )
                set_dataset_operation_comments(residual_dataset, f"Fit residuals: {fit_operation_comment}")
        except MathOperationError as exc:
            QMessageBox.warning(self, "Curve Fit Failed", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Curve Fit Failed", str(exc))
            return

        self._refresh_dataset_list(result_dataset.name)
        x_error_column = dialog.x_weight_column() if dialog.weight_mode() == "sigma" else ""
        y_error_column = dialog.weight_column() if dialog.weight_mode() == "sigma" else ""
        self._plot_tab_widget.queue_fit_plot(
            source_dataset=dataset,
            fit_dataset=result_dataset,
            x_column=dialog.x_column(),
            y_column=dialog.y_column(),
            model_name=result.report.model_name,
            residual_dataset=residual_dataset,
            show_residuals=dialog.plot_residuals(),
            x_err_column=x_error_column or "",
            y_err_column=y_error_column or "",
        )
        self._tabs.setCurrentWidget(self._plot_tab_widget)
        FitReportDialog(result.report.to_text(), self).exec()
        self.statusBar().showMessage(
            f"Fit saved as '{result_dataset.name}' with R^2={result.report.r_squared:.5g}"
        )

    def _refresh_dataset_after_analysis(self, dataset: Dataset, selected_column: str) -> None:
        """Refresh editor and plot controls after an in-place analysis column edit."""
        self._dataset_model.set_dataset(dataset)
        self._resize_dataset_columns_to_contents(dataset)
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
        self._resize_dataset_columns_to_contents(dataset)
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
        self._resize_dataset_columns_to_contents(dataset)
        self._update_dataset_summary()
        self._tabs.setCurrentIndex(0)

    def _edit_dataset_cell(self, index: QModelIndex) -> None:
        """Start editing the double-clicked table cell."""
        self._dataset_table.edit(index)

    def _show_dataset_table_context_menu(self, pos) -> None:
        """Show edit actions for the dataset table body."""
        index = self._dataset_table.indexAt(pos)
        self._prepare_dataset_context_cell(index)
        context_column = index.column() if index.isValid() else None
        self._show_dataset_editor_context_menu(
            self._dataset_table.viewport().mapToGlobal(pos),
            context_column,
        )

    def _show_dataset_header_context_menu(self, pos) -> None:
        """Show edit actions for the dataset table header."""
        header = self._dataset_table.horizontalHeader()
        column_index = header.logicalIndexAt(pos)
        if column_index >= 0:
            self._prepare_dataset_context_column(column_index)
        context_column = column_index if column_index >= 0 else None
        self._show_dataset_editor_context_menu(header.mapToGlobal(pos), context_column)

    def _show_dataset_editor_context_menu(
        self,
        global_pos,
        context_column: int | None = None,
    ) -> None:
        """Show undo/redo and clipboard actions for the dataset editor."""
        dataset = self._current_dataset()
        has_dataset = dataset is not None
        has_selection = bool(self._selected_dataset_indexes())
        has_columns = bool(self._selected_dataset_columns())
        has_clipboard_text = bool(
            self._parse_clipboard_text(QApplication.clipboard().text())
        )

        menu = QMenu(self)
        undo_action = menu.addAction("Undo")
        undo_action.setEnabled(self._dataset_model.can_undo())
        redo_action = menu.addAction("Redo")
        redo_action.setEnabled(self._dataset_model.can_redo())
        menu.addSeparator()
        copy_values_action = menu.addAction("Copy Values")
        copy_values_action.setEnabled(has_dataset and has_selection)
        paste_values_action = menu.addAction("Paste Values")
        paste_values_action.setEnabled(has_dataset and has_clipboard_text)
        menu.addSeparator()
        copy_columns_action = menu.addAction("Copy Column(s)")
        copy_columns_action.setEnabled(has_dataset and has_columns)
        paste_columns_action = menu.addAction("Paste Column(s)")
        paste_columns_action.setEnabled(
            has_dataset and self._clipboard_has_dataset_columns()
        )
        menu.addSeparator()
        metadata_action = menu.addAction("Column Metadata...")
        metadata_action.setEnabled(has_dataset)

        action = menu.exec(global_pos)
        if action == undo_action:
            self._undo_dataset_edit()
        elif action == redo_action:
            self._redo_dataset_edit()
        elif action == copy_values_action:
            self._copy_dataset_selection()
        elif action == paste_values_action:
            self._paste_dataset_clipboard()
        elif action == copy_columns_action:
            self._copy_dataset_columns()
        elif action == paste_columns_action:
            self._paste_dataset_columns(context_column)
        elif action == metadata_action:
            self._edit_column_metadata()

    def _prepare_dataset_context_cell(self, index: QModelIndex) -> None:
        """Make an unselected right-clicked cell the active selection."""
        if not index.isValid():
            return

        selection_model = self._dataset_table.selectionModel()
        if selection_model is None or selection_model.isSelected(index):
            return

        self._dataset_table.setCurrentIndex(index)
        selection_model.select(index, QItemSelectionModel.ClearAndSelect)

    def _prepare_dataset_context_column(self, column_index: int) -> None:
        """Make an unselected right-clicked header column the active selection."""
        selected_columns = self._selected_dataset_columns()
        if column_index in selected_columns:
            return

        self._dataset_table.clearSelection()
        self._dataset_table.selectColumn(column_index)
        if self._dataset_model.rowCount() > 0:
            self._dataset_table.setCurrentIndex(
                self._dataset_model.index(0, column_index)
            )

    def _copy_dataset_selection(self) -> None:
        """Copy selected dataset cells as tab-delimited clipboard text."""
        dataset = self._current_dataset()
        if dataset is None:
            return

        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return

        selected_indexes = selection_model.selectedIndexes()
        if not selected_indexes:
            return

        selected_cells = {(index.row(), index.column()) for index in selected_indexes}
        min_row = min(row for row, _column in selected_cells)
        max_row = max(row for row, _column in selected_cells)
        min_column = min(column for _row, column in selected_cells)
        max_column = max(column for _row, column in selected_cells)

        output = StringIO()
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        for row_index in range(min_row, max_row + 1):
            row_values: list[str] = []
            for column_index in range(min_column, max_column + 1):
                if (row_index, column_index) not in selected_cells:
                    row_values.append("")
                    continue
                value = dataset.frame.iat[row_index, column_index]
                row_values.append("" if pd.isna(value) else str(value))
            writer.writerow(row_values)

        QApplication.clipboard().setText(output.getvalue().rstrip("\n"))
        self.statusBar().showMessage(
            f"Copied {len(selected_cells)} cell(s) from {dataset.name}"
        )

    def _paste_dataset_clipboard(self) -> None:
        """Paste tab-delimited clipboard text into the selected dataset editor cell."""
        dataset = self._current_dataset()
        if dataset is None:
            return

        rows = self._parse_clipboard_text(QApplication.clipboard().text())
        if not rows:
            return

        current_index = self._dataset_table.currentIndex()
        start_row = current_index.row() if current_index.isValid() else 0
        start_column = current_index.column() if current_index.isValid() else 0

        try:
            pasted_rows, pasted_columns = self._dataset_model.paste_block(
                start_row=start_row,
                start_column=start_column,
                rows=rows,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Paste Failed", str(exc))
            return

        self._resize_dataset_columns_to_contents(dataset)
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        if pasted_rows and pasted_columns:
            self._select_dataset_range(
                start_row=max(start_row, 0),
                start_column=max(start_column, 0),
                row_count=pasted_rows,
                column_count=pasted_columns,
            )
            self.statusBar().showMessage(
                f"Pasted {pasted_rows} row(s) x {pasted_columns} column(s) into {dataset.name}"
            )

    def _copy_dataset_columns(self) -> None:
        """Copy complete selected dataset columns, including their headers."""
        dataset = self._current_dataset()
        if dataset is None:
            return

        selected_columns = self._selected_dataset_columns()
        if not selected_columns:
            return

        column_names = [str(dataset.frame.columns[column]) for column in selected_columns]
        rows: list[list[str]] = []
        for row_index in range(len(dataset.frame)):
            row_values: list[str] = []
            for column_index in selected_columns:
                value = dataset.frame.iat[row_index, column_index]
                row_values.append("" if pd.isna(value) else str(value))
            rows.append(row_values)

        output = StringIO()
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(column_names)
        writer.writerows(rows)

        metadata_payload = [
            dataset.column_metadata[column_name].to_metadata()
            if column_name in dataset.column_metadata
            else {}
            for column_name in column_names
        ]
        payload = {"headers": column_names, "rows": rows, "metadata": metadata_payload}
        mime_data = QMimeData()
        mime_data.setText(output.getvalue().rstrip("\n"))
        mime_data.setData(
            _DATASET_COLUMNS_MIME,
            QByteArray(json.dumps(payload).encode("utf-8")),
        )
        QApplication.clipboard().setMimeData(mime_data)
        self.statusBar().showMessage(
            f"Copied {len(selected_columns)} column(s) from {dataset.name}"
        )

    def _paste_dataset_columns(self, preferred_position: int | None = None) -> None:
        """Paste clipboard data as new whole columns before the current column."""
        dataset = self._current_dataset()
        if dataset is None:
            return

        column_names, rows, column_metadata = self._clipboard_dataset_columns()
        if not column_names and not rows:
            return

        selected_columns = self._selected_dataset_columns()
        current_index = self._dataset_table.currentIndex()
        if selected_columns:
            insert_position = selected_columns[0]
        elif preferred_position is not None:
            insert_position = preferred_position
        elif current_index.isValid():
            insert_position = current_index.column()
        else:
            insert_position = len(dataset.frame.columns)

        try:
            inserted_columns = self._dataset_model.insert_columns(
                position=insert_position,
                column_names=column_names,
                rows=rows,
                column_metadata=column_metadata,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Paste Columns Failed", str(exc))
            return

        if not inserted_columns:
            return

        self._resize_dataset_columns_to_contents(dataset)
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        self._select_dataset_column_range(insert_position, len(inserted_columns))
        self.statusBar().showMessage(
            f"Pasted {len(inserted_columns)} column(s) into {dataset.name}"
        )

    def _clipboard_has_dataset_columns(self) -> bool:
        """Return whether the clipboard can be pasted as one or more columns."""
        column_names, rows, _metadata = self._clipboard_dataset_columns()
        return bool(column_names or rows)

    def _clipboard_dataset_columns(self) -> tuple[list[str], list[list[str]], list[ColumnMetadata | None]]:
        """Return clipboard content as column headers and row values."""
        mime_data = QApplication.clipboard().mimeData()
        if mime_data is not None and mime_data.hasFormat(_DATASET_COLUMNS_MIME):
            try:
                payload = json.loads(
                    bytes(mime_data.data(_DATASET_COLUMNS_MIME)).decode("utf-8")
                )
            except (TypeError, UnicodeDecodeError, ValueError):
                payload = {}

            if isinstance(payload, dict):
                headers = payload.get("headers", [])
                rows = payload.get("rows", [])
                metadata_entries = payload.get("metadata", [])
            else:
                headers = []
                rows = []
                metadata_entries = []

            if isinstance(headers, list) and isinstance(rows, list):
                column_names = [str(header) for header in headers]
                parsed_rows: list[list[str]] = []
                for row in rows:
                    if isinstance(row, list):
                        parsed_rows.append(
                            ["" if value is None else str(value) for value in row]
                        )
                parsed_metadata: list[ColumnMetadata | None] = []
                if isinstance(metadata_entries, list):
                    for entry in metadata_entries:
                        metadata = ColumnMetadata.from_metadata(entry)
                        parsed_metadata.append(None if metadata.is_empty() else metadata)
                if column_names or parsed_rows:
                    return column_names, parsed_rows, parsed_metadata

        rows = self._parse_clipboard_text(QApplication.clipboard().text())
        if not rows:
            return [], [], []

        column_count = max((len(row) for row in rows), default=0)
        column_names = [f"Pasted Column {index + 1}" for index in range(column_count)]
        return column_names, rows, []

    def _parse_clipboard_text(self, text: str) -> list[list[str]]:
        """Parse tab-delimited clipboard text into rows and cells."""
        cleaned_text = text.rstrip("\r\n")
        if not cleaned_text:
            return []

        reader = csv.reader(StringIO(cleaned_text), delimiter="\t")
        return [row for row in reader]

    def _select_dataset_range(
        self,
        start_row: int,
        start_column: int,
        row_count: int,
        column_count: int,
    ) -> None:
        """Select a rectangular range in the dataset editor."""
        if row_count <= 0 or column_count <= 0:
            return

        self._dataset_table.clearSelection()
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return

        top_left = self._dataset_model.index(start_row, start_column)
        bottom_right = self._dataset_model.index(
            start_row + row_count - 1,
            start_column + column_count - 1,
        )
        if not top_left.isValid() or not bottom_right.isValid():
            return

        self._dataset_table.setCurrentIndex(top_left)
        selection = QItemSelection(top_left, bottom_right)
        selection_model.select(selection, QItemSelectionModel.ClearAndSelect)

    def _select_dataset_column_range(self, start_column: int, column_count: int) -> None:
        """Select contiguous columns in the dataset editor."""
        if column_count <= 0 or self._dataset_model.rowCount() <= 0:
            return

        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return

        self._dataset_table.clearSelection()
        end_column = min(start_column + column_count, self._dataset_model.columnCount())
        for offset, column_index in enumerate(range(start_column, end_column)):
            top_left = self._dataset_model.index(0, column_index)
            bottom_right = self._dataset_model.index(
                self._dataset_model.rowCount() - 1,
                column_index,
            )
            if not top_left.isValid() or not bottom_right.isValid():
                continue

            command = (
                QItemSelectionModel.ClearAndSelect
                if offset == 0
                else QItemSelectionModel.Select
            )
            selection_model.select(QItemSelection(top_left, bottom_right), command)

        first_index = self._dataset_model.index(0, start_column)
        if first_index.isValid():
            self._dataset_table.setCurrentIndex(first_index)

    def _current_dataset(self) -> Dataset | None:
        """Return the dataset currently selected in the sidebar."""
        current_item = self._dataset_list.currentItem()
        if current_item is None:
            return None

        try:
            return self._workspace.get_dataset(current_item.text())
        except KeyError:
            return None

    def _selected_dataset_indexes(self) -> list[QModelIndex]:
        """Return selected dataset table indexes."""
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return []

        return selection_model.selectedIndexes()

    def _selected_dataset_rows(self) -> list[int]:
        """Return sorted row indexes touched by the table selection."""
        return sorted({index.row() for index in self._selected_dataset_indexes()})

    def _update_dataset_summary(self) -> None:
        """Update dataset summary text and action enabled states."""
        dataset = self._dataset_model.dataset
        has_dataset = dataset is not None
        has_project_content = self._has_project_content()

        if not has_dataset:
            self._dataset_summary.setText("No dataset selected")
        else:
            dataset.prune_column_metadata()
            formula_count = len(dataset.formulas)
            formula_text = f", {formula_count} formula column(s)" if formula_count else ""
            metadata_count = len(dataset.column_metadata)
            role_count = sum(1 for entry in dataset.column_metadata.values() if entry.role)
            metadata_bits: list[str] = []
            if metadata_count:
                metadata_bits.append(f"{metadata_count} metadata column(s)")
            if role_count:
                metadata_bits.append(f"{role_count} role(s)")
            metadata_text = f", {', '.join(metadata_bits)}" if metadata_bits else ""
            backend_text = f", backend={dataset.backend}" if dataset.backend != PANDAS_BACKEND else ""
            self._dataset_summary.setText(
                f"{dataset.name}: {len(dataset.frame)} rows, "
                f"{len(dataset.frame.columns)} columns{formula_text}{metadata_text}{backend_text}"
            )

        self._export_action.setEnabled(has_dataset)
        self._delete_rows_action.setEnabled(has_dataset)
        self._delete_columns_action.setEnabled(has_dataset)
        self._rename_dataset_action.setEnabled(has_dataset)
        self._delete_dataset_action.setEnabled(has_dataset)
        self._add_column_action.setEnabled(has_dataset)
        self._add_row_action.setEnabled(has_dataset)
        self._insert_column_action.setEnabled(has_dataset)
        self._column_metadata_action.setEnabled(has_dataset)
        self._insert_row_action.setEnabled(has_dataset)
        self._apply_formula_action.setEnabled(has_dataset)
        self._derivative_action.setEnabled(has_dataset)
        self._integral_action.setEnabled(has_dataset)
        self._interpolation_action.setEnabled(has_dataset)
        self._fft_action.setEnabled(has_dataset)
        self._ifft_action.setEnabled(has_dataset)
        self._statistics_action.setEnabled(has_dataset)
        self._fit_action.setEnabled(has_dataset)
        self._rename_dataset_button.setEnabled(has_dataset)
        self._remove_dataset_button.setEnabled(has_dataset)
        self._editor_add_row_button.setEnabled(has_dataset)
        self._editor_insert_row_button.setEnabled(has_dataset)
        self._editor_add_column_button.setEnabled(has_dataset)
        self._editor_insert_column_button.setEnabled(has_dataset)
        self._editor_delete_rows_button.setEnabled(has_dataset)
        self._editor_delete_columns_button.setEnabled(has_dataset)
        self._editor_rename_button.setEnabled(has_dataset)
        self._editor_remove_button.setEnabled(has_dataset)
        self._editor_export_button.setEnabled(has_dataset)
        self._editor_metadata_button.setEnabled(has_dataset)
        for button in getattr(self, "_analysis_buttons", []):
            button.setEnabled(has_dataset)
        self._undo_action.setEnabled(self._dataset_model.can_undo())
        self._redo_action.setEnabled(self._dataset_model.can_redo())
        self._save_project_action.setEnabled(has_project_content)
        self._save_project_as_action.setEnabled(has_project_content)
        self._close_project_action.setEnabled(has_project_content)
        self._update_plot_action_state()

    def _handle_dataset_history_changed(self) -> None:
        """Refresh controls after an undoable dataset edit changes history."""
        dataset = self._dataset_model.dataset
        if dataset is not None and hasattr(self, "_plot_tab_widget"):
            self._resize_dataset_columns_to_contents(dataset)
            self._plot_tab_widget.refresh_controls(dataset.name)
        if hasattr(self, "_undo_action"):
            self._update_dataset_summary()

    def _handle_dataset_columns_renamed(self, rename_map: dict[str, str]) -> None:
        """Retarget plots after undo/redo restores renamed dataset columns."""
        dataset = self._dataset_model.dataset
        if dataset is None or not rename_map:
            return
        self._workspace.rename_column_references_in_plots(dataset.name, rename_map)
        self._plot_tab_widget.rename_column_references(dataset.name, rename_map)

    def _undo_dataset_edit(self) -> None:
        """Undo the most recent editable dataset operation."""
        if not self._dataset_model.undo():
            return
        self.statusBar().showMessage("Undid dataset edit")

    def _redo_dataset_edit(self) -> None:
        """Redo the most recently undone dataset operation."""
        if not self._dataset_model.redo():
            return
        self.statusBar().showMessage("Redid dataset edit")

    def _set_sidebar_visible(self, visible: bool) -> None:
        """Show or hide the workspace navigator dock."""
        self._workspace_dock.setVisible(visible)
        if hasattr(self, "_show_sidebar_action"):
            self._sync_checkable_action(self._show_sidebar_action, visible)

    def _sync_inspector_to_current_tab(self, _index: int | None = None) -> None:
        """Show the inspector page that matches the active work area tab."""
        if not hasattr(self, "_inspector_stack"):
            return

        if self._tabs.currentWidget() is self._plot_tab_widget:
            self._inspector_stack.setCurrentWidget(self._plot_inspector)
            self._inspector_dock.setWindowTitle("Plot Inspector")
        else:
            self._inspector_stack.setCurrentWidget(self._data_inspector)
            self._inspector_dock.setWindowTitle("Data Inspector")

    def _toggle_workspace_section(self) -> None:
        """Toggle visibility of the workspace dataset section."""
        self._set_workspace_section_visible(self._dataset_list.isHidden())

    def _toggle_plots_section(self) -> None:
        """Toggle visibility of the saved plots section."""
        self._set_plots_section_visible(self._plot_list.isHidden())

    def _set_workspace_section_visible(self, visible: bool) -> None:
        """Show or hide workspace dataset navigation controls."""
        dataset_tab_index = self._workspace_nav_tabs.indexOf(self._dataset_nav_page)
        if dataset_tab_index >= 0:
            self._workspace_nav_tabs.setTabEnabled(dataset_tab_index, visible)
        self._dataset_list.setVisible(visible)
        self._dataset_buttons_panel.setVisible(visible)
        if visible:
            self._workspace_nav_tabs.setCurrentWidget(self._dataset_nav_page)
        if hasattr(self, "_show_workspace_action"):
            self._sync_checkable_action(self._show_workspace_action, visible)

    def _set_plots_section_visible(self, visible: bool) -> None:
        """Show or hide saved plot navigation controls."""
        plot_tab_index = self._workspace_nav_tabs.indexOf(self._plot_nav_page)
        if plot_tab_index >= 0:
            self._workspace_nav_tabs.setTabEnabled(plot_tab_index, visible)
        self._plot_nav_page.setVisible(visible)
        if visible:
            self._workspace_nav_tabs.setCurrentWidget(self._plot_nav_page)
        if hasattr(self, "_show_plots_action"):
            self._sync_checkable_action(self._show_plots_action, visible)

    def _set_plot_options_visible_from_action(self, visible: bool) -> None:
        """Apply the View menu inspector visibility state."""
        self._inspector_dock.setVisible(visible)
        self._plot_tab_widget.set_plot_options_visible(visible)

    def _handle_plot_options_visibility_changed(self, visible: bool) -> None:
        """Apply plot-tab option visibility to the external inspector dock."""
        if self._tabs.currentWidget() is self._plot_tab_widget:
            self._inspector_dock.setVisible(visible)
        self._sync_plot_options_action(visible)

    def _sync_plot_options_action(self, visible: bool) -> None:
        """Synchronize the View menu with inspector visibility."""
        if hasattr(self, "_show_plot_options_action"):
            self._sync_checkable_action(self._show_plot_options_action, visible)

    @staticmethod
    def _sync_checkable_action(action: QAction, checked: bool) -> None:
        """Set a checkable action without emitting its toggled signal."""
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)

    def _reset_view_to_default(self) -> None:
        """Restore default workspace and inspector dock visibility/layout."""
        self._set_sidebar_visible(True)
        self._inspector_dock.setVisible(True)
        self._set_workspace_section_visible(True)
        self._set_plots_section_visible(True)
        self._plot_tab_widget.reset_view_to_default()
        self._sync_inspector_to_current_tab()
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

    @staticmethod
    def _preferred_dataset_column(
        dataset: Dataset,
        roles: tuple[str, ...],
        fallback_index: int | None = 0,
    ) -> str | None:
        """Return the first column tagged with a role, then an optional fallback position."""
        wanted = set(roles)
        for column in dataset.frame.columns:
            column_name = str(column)
            metadata = dataset.column_metadata.get(column_name)
            if metadata is not None and metadata.role in wanted:
                return column_name

        if fallback_index is None:
            return None
        if 0 <= fallback_index < len(dataset.frame.columns):
            return str(dataset.frame.columns[fallback_index])
        return None

    @staticmethod
    def _numeric_column_ranges(dataset: Dataset) -> dict[str, tuple[float, float]]:
        """Return finite numeric min/max ranges for dataset columns."""
        ranges: dict[str, tuple[float, float]] = {}
        for column in dataset.frame.columns:
            column_name = str(column)
            values = pd.to_numeric(dataset.frame[column], errors="coerce")
            values = values[
                values.notna()
                & (values != float("inf"))
                & (values != float("-inf"))
            ]
            if values.empty:
                continue
            ranges[column_name] = (float(values.min()), float(values.max()))
        return ranges

    @staticmethod
    def _apply_interpolation_metadata(
        source_dataset: Dataset,
        result_dataset: Dataset,
        coordinate_columns: list[str],
        value_column: str,
    ) -> None:
        """Copy useful source metadata onto interpolation result columns."""
        for column_name in coordinate_columns:
            if column_name not in result_dataset.frame.columns:
                continue
            source_metadata = source_dataset.column_metadata.get(column_name)
            if source_metadata is None:
                continue
            result_dataset.column_metadata[column_name] = ColumnMetadata(
                role=source_metadata.role,
                unit=source_metadata.unit,
                long_name=source_metadata.long_name,
                comment=source_metadata.comment,
            )

        prediction_column = f"{value_column}_interpolated"
        if prediction_column not in result_dataset.frame.columns:
            return
        value_metadata = source_dataset.column_metadata.get(value_column, ColumnMetadata())
        result_dataset.column_metadata[prediction_column] = ColumnMetadata(
            role=value_metadata.role or ("y" if len(coordinate_columns) == 1 else "z"),
            unit=value_metadata.unit,
            long_name=f"Interpolated {value_metadata.long_name or value_column}",
            comment=value_metadata.comment,
        )

    def _selected_dataset_columns(self) -> list[int]:
        """Return sorted column indexes touched by the table selection."""
        return sorted({index.column() for index in self._selected_dataset_indexes()})

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
        return bool(
            self._workspace.dataset_names()
            or self._workspace.plot_names()
            or self._workspace.custom_fit_model_names()
        )

    def _set_project_window_title(self) -> None:
        """Refresh the main window title with the current project file."""
        if self._project_path is None:
            self.setWindowTitle("JASC Data Processor")
        else:
            self.setWindowTitle(f"JASC Data Processor - {self._project_path.name}")

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
            self._project_path = Path(file_name)
            self._large_dataset_warning_names.clear()
            self._plot_tab_widget.set_workspace(self._workspace)
            self._refresh_dataset_list()
            self._refresh_plot_list()
            self._set_project_window_title()
            self._warn_about_large_workspace_datasets(Path(file_name).name)
            self.statusBar().showMessage(f"Opened project {Path(file_name).name}")
        except Exception as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))

    def _save_project(self) -> None:
        """Save the current workspace to its project path, or prompt for one."""
        if not self._has_project_content():
            QMessageBox.information(self, "Save Project", "The workspace is empty.")
            return

        if self._project_path is None:
            self._save_project_as()
            return

        try:
            project_io.save_project(self._workspace, self._project_path)
            self.statusBar().showMessage(f"Saved project {self._project_path.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _save_project_as(self) -> None:
        """Prompt for a project path and save the current workspace there."""
        if not self._has_project_content():
            QMessageBox.information(self, "Save Project", "The workspace is empty.")
            return

        default_name = str(self._project_path) if self._project_path else "workspace.jasc"
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Project", default_name, "JASC Projects (*.jasc)")
        if not file_name:
            return

        path = Path(file_name)
        if not path.suffix:
            path = path.with_suffix(project_io.PROJECT_EXTENSION)

        try:
            project_io.save_project(self._workspace, path)
            self._project_path = path
            self._set_project_window_title()
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
        self._project_path = None
        self._large_dataset_warning_names.clear()
        self._plot_tab_widget.set_workspace(self._workspace)
        self._refresh_dataset_list()
        self._refresh_plot_list()
        self._tabs.setCurrentIndex(0)
        self._set_project_window_title()
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
