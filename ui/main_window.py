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
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QMimeData,
    Qt,
)
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
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
    AUTO_RESIZE_ROW_SAMPLE,
    DEFAULT_LARGE_DATASET_COLUMN_WIDTH,
    LARGE_AUTO_RESIZE_ROW_SAMPLE,
    PANDAS_BACKEND,
    format_bytes,
    file_size_bytes,
    profile_dataframe,
    should_warn_for_large_file,
)
from core.clipboard_io import parse_tabular_clipboard
from core.data_prep import FILTER_OPERATORS, DataPrepError, FilterCondition, apply_filter_condition
from core.data_prep import (
    bin_dataframe,
    clean_missing_values,
    group_aggregate_dataframe,
    merge_join_dataframes,
    reshape_dataframe,
    remove_duplicate_rows,
    sort_dataframe,
)
from core.file_io import (
    SUPPORTED_EXCEL_EXTENSIONS,
    export_tabular_file,
    inspect_excel_workbook,
    read_excel_sheets,
    read_tabular_file,
)
from core.operations import ExpressionError, ExpressionResult, apply_column_expression
from core.workspace import (
    COLUMN_NUMERIC_TYPES,
    ColumnMetadata,
    Dataset,
    column_type_label,
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
    validate_numeric_column_metadata,
)
from math_engine.curve_fitting import FIT_METHODS, FitResult, fit_curve
from math_engine.interpolation import (
    INTERPOLATION_METHODS,
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
from math_engine.smoothing import (
    SMOOTHING_METHODS,
    SmoothingParameters,
    smooth_column,
    smoothing_operation_text,
)
from ui.data_table import RangeFillDialog, TableSizeDialog
from ui.dataframe_model import DataFrameTableModel
from ui.dialogs import (
    BATCH_COLUMN_BINDING_NAME,
    BATCH_COLUMN_BINDING_POSITION,
    BatchPreviewDialog,
    BinningDialog,
    ColumnExpressionDialog,
    ColumnMathDialog,
    ColumnMetadataDialog,
    ColorPlotDigitizerDialog,
    CustomFitModelsDialog,
    DataFilterDialog,
    FFTDialog,
    FigureDigitizerDialog,
    FigureExtractionResult,
    FigureExtractionModeDialog,
    FitDialog,
    FitReportDialog,
    GroupAggregateDialog,
    IFFTDialog,
    ExcelImportDialog,
    ImportOptionsDialog,
    InterpolationDialog,
    MergeJoinDialog,
    MissingValuesDialog,
    ReshapeDialog,
    RemoveDuplicatesDialog,
    DataSortDialog,
    StatisticsDialog,
    SmoothingDialog,
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
        self._applying_visual_style = False
        self._active_plot_name: str | None = None
        self._active_plot_baseline: str | None = None
        self._plot_inspector_enabled = True

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
        self._plot_list.currentItemChanged.connect(self._handle_saved_plot_selection)
        self._plot_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._plot_list.customContextMenuRequested.connect(self._show_plot_context_menu)

        self._dataset_model = DataFrameTableModel(self)
        self._dataset_model.history_changed.connect(self._handle_dataset_history_changed)
        self._dataset_model.history_warning.connect(self.statusBar().showMessage)
        self._dataset_model.columns_renamed.connect(self._handle_dataset_columns_renamed)
        self._dataset_model.edit_rejected.connect(self._handle_dataset_edit_rejected)
        self._dataset_table = QTableView()
        self._dataset_table.setModel(self._dataset_model)
        self._dataset_table.setAlternatingRowColors(True)
        self._dataset_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._dataset_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._dataset_table.setSortingEnabled(False)
        self._dataset_table.horizontalHeader().setResizeContentsPrecision(
            AUTO_RESIZE_ROW_SAMPLE
        )
        self._dataset_table.doubleClicked.connect(self._edit_dataset_cell)
        self._install_dataset_clipboard_shortcuts()
        self._install_dataset_context_menu()
        self._dataset_summary = QLabel("No dataset selected")

        # Plot state moved to PlotTab

        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._sync_inspector_to_current_tab)
        self._data_tab_widget = self._build_dataset_editor()
        self._tabs.addTab(self._data_tab_widget, "Data")
        self._plot_tab_widget = PlotTab(self._workspace, parent=self, external_options=True)
        self._plot_tab_widget.status_message.connect(self.statusBar().showMessage)
        self._plot_tab_widget.plot_rendered.connect(self._update_plot_action_state)
        self._plot_tab_widget.save_plot_requested.connect(self._save_current_plot)
        self._plot_tab_widget.new_plot_requested.connect(self._start_new_plot)
        self._plot_tab_widget.plot_draft_replaced.connect(self._mark_plot_as_unsaved)
        self._plot_tab_widget.load_plot_requested.connect(self._load_selected_plot)
        self._plot_tab_widget.remove_plot_requested.connect(self._delete_selected_plot)
        self._plot_tab_widget.options_visibility_changed.connect(self._handle_plot_options_visibility_changed)
        self._tabs.addTab(self._plot_tab_widget, "Plot")

        self.setCentralWidget(self._tabs)
        self._build_workspace_dock()
        self._build_inspector_dock()
        self._create_actions()
        self._refresh_plot_list()
        self._apply_visual_style()
        self._sync_inspector_to_current_tab()
        self._update_dataset_summary()
        self.statusBar().showMessage("Ready")

    def changeEvent(self, event: QEvent) -> None:
        """Refresh theme-aware styling when Qt reports a palette change."""
        super().changeEvent(event)
        if not getattr(self, "_applying_visual_style", False) and event.type() in self._palette_change_event_types():
            self._apply_visual_style()

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
        dataset_buttons = QVBoxLayout(self._dataset_buttons_panel)
        dataset_buttons.setContentsMargins(0, 0, 0, 0)
        self._new_dataset_button = QPushButton("New Sheet")
        self._new_dataset_button.clicked.connect(self._create_blank_sheet)
        self._duplicate_dataset_button = QPushButton("Duplicate Sheet")
        self._duplicate_dataset_button.clicked.connect(self._duplicate_current_dataset)
        self._rename_dataset_button = QPushButton("Rename")
        self._rename_dataset_button.clicked.connect(self._rename_current_dataset)
        self._remove_dataset_button = QPushButton("Remove")
        self._remove_dataset_button.clicked.connect(self._delete_current_dataset)
        dataset_buttons.addWidget(self._new_dataset_button)
        dataset_buttons.addWidget(self._duplicate_dataset_button)
        dataset_buttons.addLayout(self._button_row(self._rename_dataset_button, self._remove_dataset_button))
        dataset_layout.addWidget(self._dataset_buttons_panel)

        plot_page = QWidget()
        self._plot_nav_page = plot_page
        plot_layout = QVBoxLayout(plot_page)
        plot_layout.addWidget(self._plot_list)
        self._duplicate_plot_button = QPushButton("Duplicate Saved Plot")
        self._duplicate_plot_button.clicked.connect(self._duplicate_selected_plot)
        plot_layout.addWidget(self._duplicate_plot_button)

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
        """Build the Data-mode inspector with sheet editing and analysis actions."""
        inspector_tabs = QTabWidget()
        inspector_tabs.addTab(self._build_sheet_actions_panel(), "Sheet")
        inspector_tabs.addTab(self._build_data_prep_actions_panel(), "Data Prep")
        inspector_tabs.addTab(self._build_analysis_actions_panel(), "Analysis")
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
        self._editor_delete_rows_button.setToolTip("Shortcut: Shift+Delete")
        self._editor_delete_rows_button.clicked.connect(self._delete_selected_rows)
        self._editor_delete_columns_button = QPushButton("Delete Columns")
        self._editor_delete_columns_button.setToolTip("Shortcut: Ctrl+Delete")
        self._editor_delete_columns_button.clicked.connect(self._delete_selected_columns)
        self._editor_resize_sheet_button = QPushButton("Resize Sheet")
        self._editor_resize_sheet_button.setToolTip(
            "Set the worksheet row and column counts together"
        )
        self._editor_resize_sheet_button.clicked.connect(self._resize_current_sheet)
        self._editor_rename_button = QPushButton("Rename")
        self._editor_rename_button.clicked.connect(self._rename_current_dataset)
        self._editor_remove_button = QPushButton("Remove")
        self._editor_remove_button.clicked.connect(self._delete_current_dataset)
        self._editor_export_button = QPushButton("Export")
        self._editor_export_button.clicked.connect(self._export_current_dataset)
        self._editor_fill_range_button = QPushButton("Fill Range")
        self._editor_fill_range_button.clicked.connect(self._fill_dataset_range)
        self._editor_metadata_button = QPushButton("Column Metadata")
        self._editor_metadata_button.clicked.connect(self._edit_column_metadata)

        layout = QVBoxLayout(panel)
        layout.addLayout(self._button_row(self._editor_add_row_button, self._editor_insert_row_button))
        layout.addLayout(self._button_row(self._editor_delete_rows_button, self._editor_delete_columns_button))
        layout.addLayout(self._button_row(self._editor_add_column_button, self._editor_insert_column_button))
        layout.addWidget(self._editor_resize_sheet_button)
        layout.addLayout(self._button_row(self._editor_rename_button, self._editor_remove_button))
        layout.addLayout(self._button_row(self._editor_fill_range_button, self._editor_metadata_button))
        layout.addWidget(self._editor_export_button)
        layout.addStretch(1)
        return panel

    def _build_data_prep_actions_panel(self) -> QWidget:
        """Build data-preparation launch buttons for the Data inspector."""
        panel = QWidget()
        filter_button = QPushButton("Filter / Query")
        filter_button.clicked.connect(self._run_filter_query)
        sort_button = QPushButton("Sort")
        sort_button.clicked.connect(self._run_sort)
        missing_button = QPushButton("Missing Values")
        missing_button.clicked.connect(self._run_missing_values)
        duplicates_button = QPushButton("Remove Duplicates")
        duplicates_button.clicked.connect(self._run_remove_duplicates)
        bin_button = QPushButton("Bin / Average")
        bin_button.clicked.connect(self._run_binning)
        group_button = QPushButton("Group / Aggregate")
        group_button.clicked.connect(self._run_group_aggregate)
        join_button = QPushButton("Merge / Join")
        join_button.clicked.connect(self._run_merge_join)
        reshape_button = QPushButton("Reshape")
        reshape_button.clicked.connect(self._run_reshape)

        self._data_prep_buttons = [
            filter_button,
            sort_button,
            missing_button,
            duplicates_button,
            bin_button,
            group_button,
            join_button,
            reshape_button,
        ]

        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("Clean and Shape"))
        layout.addWidget(filter_button)
        layout.addLayout(self._button_row(sort_button, missing_button))
        layout.addWidget(duplicates_button)
        layout.addWidget(bin_button)
        layout.addWidget(QLabel("Combine and Summarize"))
        layout.addWidget(group_button)
        layout.addWidget(join_button)
        layout.addWidget(reshape_button)
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
        """Bind right-click menus across cells, headers, and table chrome."""
        self._dataset_table.viewport().setContextMenuPolicy(Qt.CustomContextMenu)
        self._dataset_table.viewport().customContextMenuRequested.connect(
            self._show_dataset_table_context_menu
        )
        self._dataset_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._dataset_table.customContextMenuRequested.connect(
            self._show_dataset_table_frame_context_menu
        )
        self._dataset_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self._dataset_table.horizontalHeader().customContextMenuRequested.connect(
            self._show_dataset_header_context_menu
        )
        self._dataset_table.verticalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self._dataset_table.verticalHeader().customContextMenuRequested.connect(
            self._show_dataset_row_header_context_menu
        )
        self._dataset_table.horizontalHeader().sectionDoubleClicked.connect(
            self._edit_column_metadata_for_column
        )

    def _build_dataset_editor(self) -> QWidget:
        """Build the central dataset table editor."""
        editor = QWidget()

        layout = QVBoxLayout(editor)
        layout.addWidget(self._dataset_summary)
        layout.addWidget(self._dataset_table)
        return editor

    def _create_blank_sheet(self) -> None:
        """Create a normal editable blank worksheet in the Data tab."""
        frame = pd.DataFrame(
            {
                "x": pd.Series([float("nan")] * 25, dtype="float64"),
                "y": pd.Series([float("nan")] * 25, dtype="float64"),
            }
        )
        try:
            dataset = self._workspace.add_dataset("Sheet", frame)
        except Exception as exc:
            QMessageBox.critical(self, "New Sheet Failed", str(exc))
            return

        dataset.metadata_for_column("x").role = "x"
        dataset.metadata_for_column("x").value_type = "numeric"
        dataset.metadata_for_column("x").comment = "Default X column for a blank worksheet."
        dataset.metadata_for_column("y").role = "y"
        dataset.metadata_for_column("y").value_type = "numeric"
        dataset.metadata_for_column("y").comment = "Default Y column for a blank worksheet."
        dataset.sync_column_metadata_attrs()

        self._tabs.setCurrentWidget(self._data_tab_widget)
        self._workspace_dock.setVisible(True)
        self._set_workspace_section_visible(True)
        self._inspector_dock.setVisible(True)
        self._sync_plot_options_action(True)
        self._sync_inspector_to_current_tab()
        self._refresh_dataset_list(dataset.name)
        self._select_dataset_range(0, 0, min(25, len(dataset.frame)), min(2, len(dataset.frame.columns)))
        self.statusBar().showMessage(f"Created blank sheet {dataset.name}")

    def _fill_dataset_range(self) -> None:
        """Fill or create a dataset column with an arithmetic sequence."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Fill Range", "Select a dataset before filling a range.")
            return

        selected_columns = self._selected_dataset_columns()
        selected_rows = self._selected_dataset_rows()
        default_column = "x"
        if selected_columns:
            default_column = str(dataset.frame.columns[selected_columns[0]])
        elif "x" in dataset.frame.columns:
            default_column = "x"
        elif len(dataset.frame.columns) > 0:
            default_column = str(dataset.frame.columns[0])

        default_start_row = selected_rows[0] + 1 if selected_rows else 1
        default_count = len(selected_rows) if selected_rows else max(len(dataset.frame), 25)
        dialog = RangeFillDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_column=default_column,
            default_start_row=default_start_row,
            default_count=default_count,
            parent=self,
        )
        if dialog.exec() != RangeFillDialog.Accepted:
            return

        try:
            column_name = self._dataset_model.fill_range(
                target_column=dialog.target_column(),
                start_row=dialog.start_row(),
                count=dialog.count(),
                start_value=dialog.start_value(),
                step=dialog.step(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Fill Range Failed", str(exc))
            return

        if column_name.lower() in {"x", "time", "t"}:
            dataset.metadata_for_column(column_name).role = "x"
        dataset.metadata_for_column(column_name).value_type = "numeric"
        dataset.prune_column_metadata()
        self._resize_dataset_columns_to_contents(dataset)
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        column_index = list(dataset.frame.columns).index(column_name)
        self._select_dataset_range(dialog.start_row() - 1, column_index, dialog.count(), 1)
        self.statusBar().showMessage(f"Filled {dialog.count()} value(s) in {dataset.name}.{column_name}")

    def _run_filter_query(self) -> None:
        """Create a filtered copy of a dataset from one simple condition."""
        dataset_columns = self._data_prep_dataset_columns()
        if not dataset_columns:
            QMessageBox.information(self, "Filter / Query", "Load or create a dataset before filtering.")
            return

        default_dataset_name = self._default_data_prep_dataset_name(dataset_columns)
        dialog = DataFilterDialog(
            dataset_columns=dataset_columns,
            default_dataset_name=default_dataset_name,
            parent=self,
        )
        if dialog.exec() != DataFilterDialog.Accepted:
            return

        try:
            source_dataset = self._workspace.get_dataset(dialog.dataset_name())
            condition = FilterCondition(
                column=dialog.column_name(),
                operator=dialog.operator_key(),
                value=dialog.value_text(),
                value2=dialog.value2_text(),
            )
            result_frame = apply_filter_condition(source_dataset.frame, condition)
        except (KeyError, DataPrepError) as exc:
            QMessageBox.warning(self, "Filter / Query Failed", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Filter / Query Failed", str(exc))
            return

        operation = (
            f"Filter {source_dataset.name}.{condition.column} "
            f"{FILTER_OPERATORS.get(condition.operator, condition.operator)} {condition.value}"
        )
        if condition.operator == "between":
            operation = f"{operation} and {condition.value2}"
        self._create_data_prep_result(
            title="Filter / Query",
            output_name=dialog.output_name(),
            result_frame=result_frame,
            source_datasets=[source_dataset],
            operation=operation.strip(),
            status_message=(
                f"Filtered {source_dataset.name}: {len(result_frame)} of {len(source_dataset.frame)} rows"
            ),
        )

    def _run_sort(self) -> None:
        """Create a sorted copy of the current dataset."""
        dataset = self._current_data_prep_source("Sort")
        if dataset is None:
            return
        dialog = DataSortDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_output_name=f"{dataset.name}_sorted",
            parent=self,
        )
        if dialog.exec() != DataSortDialog.Accepted:
            return
        try:
            result_frame = sort_dataframe(dataset.frame, dialog.selected_columns(), dialog.ascending())
        except DataPrepError as exc:
            QMessageBox.warning(self, "Sort Failed", str(exc))
            return
        self._create_data_prep_result(
            title="Sort",
            output_name=dialog.output_name(),
            result_frame=result_frame,
            source_datasets=[dataset],
            operation=(
                f"Sort {dataset.name} by {', '.join(dialog.selected_columns())} "
                f"({'ascending' if dialog.ascending() else 'descending'})"
            ),
            status_message=f"Sorted {dataset.name} into {len(result_frame)} rows",
        )

    def _run_remove_duplicates(self) -> None:
        """Create a copy with duplicate rows removed using selected key columns."""
        dataset = self._current_data_prep_source("Remove Duplicates")
        if dataset is None:
            return
        dialog = RemoveDuplicatesDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_output_name=f"{dataset.name}_unique",
            parent=self,
        )
        if dialog.exec() != RemoveDuplicatesDialog.Accepted:
            return
        try:
            result_frame = remove_duplicate_rows(
                dataset.frame,
                columns=dialog.columns(),
                keep=dialog.keep_policy(),
            )
        except DataPrepError as exc:
            QMessageBox.warning(self, "Remove Duplicates Failed", str(exc))
            return
        removed_count = len(dataset.frame) - len(result_frame)
        self._create_data_prep_result(
            title="Remove Duplicates",
            output_name=dialog.output_name(),
            result_frame=result_frame,
            source_datasets=[dataset],
            operation=(
                f"Remove duplicates from {dataset.name}; keys={', '.join(dialog.columns())}; "
                f"keep={dialog.keep_policy()}"
            ),
            status_message=(
                f"Removed {removed_count} duplicate row(s) from {dataset.name}; "
                f"{len(result_frame)} row(s) remain"
            ),
        )

    def _run_missing_values(self) -> None:
        """Create a cleaned copy of the current dataset after missing-value handling."""
        dataset = self._current_data_prep_source("Missing Values")
        if dataset is None:
            return
        dialog = MissingValuesDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_output_name=f"{dataset.name}_cleaned",
            parent=self,
        )
        if dialog.exec() != MissingValuesDialog.Accepted:
            return
        try:
            result_frame = clean_missing_values(
                dataset.frame,
                columns=dialog.selected_columns(),
                strategy=dialog.strategy(),
                fill_value=dialog.fill_value(),
            )
        except DataPrepError as exc:
            QMessageBox.warning(self, "Missing Values Failed", str(exc))
            return
        self._create_data_prep_result(
            title="Missing Values",
            output_name=dialog.output_name(),
            result_frame=result_frame,
            source_datasets=[dataset],
            operation=(
                f"Missing values {dialog.strategy()} on {dataset.name}: "
                + ", ".join(dialog.selected_columns())
            ),
            status_message=f"Cleaned missing values in {dataset.name}",
        )

    def _run_binning(self) -> None:
        """Create binned averages and dispersion columns from the current dataset."""
        dataset = self._current_data_prep_source("Bin / Average")
        if dataset is None:
            return
        dialog = BinningDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_output_name=f"{dataset.name}_binned",
            parent=self,
        )
        if dialog.exec() != BinningDialog.Accepted:
            return
        try:
            result_frame = bin_dataframe(
                dataset.frame,
                bin_column=dialog.bin_column(),
                value_columns=dialog.value_columns(),
                bin_count=dialog.bin_count(),
            )
        except DataPrepError as exc:
            QMessageBox.warning(self, "Bin / Average Failed", str(exc))
            return
        self._create_data_prep_result(
            title="Bin / Average",
            output_name=dialog.output_name(),
            result_frame=result_frame,
            source_datasets=[dataset],
            operation=(
                f"Bin {dataset.name} by {dialog.bin_column()} into {dialog.bin_count()} bins; "
                f"values={', '.join(dialog.value_columns())}; outputs mean/std/sem/min/max"
            ),
            status_message=f"Binned {dataset.name} into {len(result_frame)} bin row(s)",
        )

    def _run_group_aggregate(self) -> None:
        """Create grouped aggregate values from the current dataset."""
        dataset = self._current_data_prep_source("Group / Aggregate")
        if dataset is None:
            return
        dialog = GroupAggregateDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_output_name=f"{dataset.name}_grouped",
            parent=self,
        )
        if dialog.exec() != GroupAggregateDialog.Accepted:
            return
        try:
            result_frame = group_aggregate_dataframe(
                dataset.frame,
                group_columns=dialog.group_columns(),
                value_columns=dialog.value_columns(),
                aggregations=dialog.aggregations(),
            )
        except DataPrepError as exc:
            QMessageBox.warning(self, "Group / Aggregate Failed", str(exc))
            return
        self._create_data_prep_result(
            title="Group / Aggregate",
            output_name=dialog.output_name(),
            result_frame=result_frame,
            source_datasets=[dataset],
            operation=(
                f"Group {dataset.name} by {', '.join(dialog.group_columns())}; "
                f"values={', '.join(dialog.value_columns())}; "
                f"aggregations={', '.join(dialog.aggregations())}"
            ),
            status_message=f"Grouped {dataset.name} into {len(result_frame)} row(s)",
        )

    def _run_merge_join(self) -> None:
        """Create a merged dataset from two source datasets."""
        dataset_columns = self._data_prep_dataset_columns()
        if len(dataset_columns) < 2:
            QMessageBox.information(self, "Merge / Join", "Load or create at least two datasets before merging.")
            return
        dialog = MergeJoinDialog(
            dataset_columns=dataset_columns,
            default_dataset_name=self._default_data_prep_dataset_name(dataset_columns),
            parent=self,
        )
        if dialog.exec() != MergeJoinDialog.Accepted:
            return
        try:
            left_dataset = self._workspace.get_dataset(dialog.left_dataset_name())
            right_dataset = self._workspace.get_dataset(dialog.right_dataset_name())
            result_frame = merge_join_dataframes(
                left_dataset.frame,
                right_dataset.frame,
                left_key=dialog.left_key(),
                right_key=dialog.right_key(),
                how=dialog.join_mode(),
            )
        except (KeyError, DataPrepError) as exc:
            QMessageBox.warning(self, "Merge / Join Failed", str(exc))
            return
        self._create_data_prep_result(
            title="Merge / Join",
            output_name=dialog.output_name(),
            result_frame=result_frame,
            source_datasets=[left_dataset, right_dataset],
            operation=(
                f"Merge {left_dataset.name}.{dialog.left_key()} "
                f"with {right_dataset.name}.{dialog.right_key()} ({dialog.join_mode()})"
            ),
            status_message=f"Merged {left_dataset.name} and {right_dataset.name} into {len(result_frame)} row(s)",
        )

    def _run_reshape(self) -> None:
        """Create a reshaped copy of the current dataset."""
        dataset = self._current_data_prep_source("Reshape")
        if dataset is None:
            return
        dialog = ReshapeDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_output_name=f"{dataset.name}_reshaped",
            parent=self,
        )
        if dialog.exec() != ReshapeDialog.Accepted:
            return
        try:
            result_frame = reshape_dataframe(
                dataset.frame,
                mode=dialog.mode(),
                id_columns=dialog.id_columns(),
                value_columns=dialog.value_columns(),
            )
        except DataPrepError as exc:
            QMessageBox.warning(self, "Reshape Failed", str(exc))
            return
        self._create_data_prep_result(
            title="Reshape",
            output_name=dialog.output_name(),
            result_frame=result_frame,
            source_datasets=[dataset],
            operation=f"Reshape {dataset.name} using mode {dialog.mode()}",
            status_message=f"Reshaped {dataset.name} into {len(result_frame)} row(s)",
        )

    def _create_data_prep_result(
        self,
        title: str,
        output_name: str,
        result_frame: pd.DataFrame,
        source_datasets: list[Dataset],
        operation: str,
        status_message: str,
    ) -> Dataset | None:
        """Create a Data Prep result sheet, preserving metadata where possible."""
        if result_frame.empty:
            reply = QMessageBox.question(
                self,
                title,
                "The operation produced an empty sheet. Create it anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return None

        result_dataset = self._workspace.add_dataset(output_name, result_frame)
        result_metadata: dict[str, ColumnMetadata] = {}
        for source_dataset in source_datasets:
            for column, metadata in source_dataset.column_metadata.items():
                if column in result_dataset.frame.columns and column not in result_metadata:
                    result_metadata[column] = metadata
        result_dataset.set_column_metadata(result_metadata)
        set_dataset_operation_comments(result_dataset, operation)
        self._refresh_dataset_list(result_dataset.name)
        self._tabs.setCurrentWidget(self._data_tab_widget)
        self.statusBar().showMessage(status_message)
        return result_dataset

    def _current_data_prep_source(self, title: str) -> Dataset | None:
        """Return the active source dataset for a Data Prep operation."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, title, "Select a dataset before running this Data Prep operation.")
            return None
        if dataset.frame.empty or len(dataset.frame.columns) == 0:
            QMessageBox.information(self, title, "The selected dataset has no data columns.")
            return None
        return dataset

    def _data_prep_dataset_columns(self) -> dict[str, list[str]]:
        """Return dataset-to-column choices for Data Prep dialogs."""
        return {
            dataset.name: [str(column) for column in dataset.frame.columns]
            for dataset in self._workspace.list_datasets()
            if len(dataset.frame.columns) > 0
        }

    def _default_data_prep_dataset_name(self, dataset_columns: dict[str, list[str]]) -> str:
        """Return the selected dataset name or the first available Data Prep dataset."""
        current_dataset = self._current_dataset()
        if current_dataset is not None and current_dataset.name in dataset_columns:
            return current_dataset.name
        return next(iter(dataset_columns))

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

        new_sheet_action = file_menu.addAction("New &Blank Sheet")
        new_sheet_action.setShortcut("Ctrl+N")
        new_sheet_action.triggered.connect(self._create_blank_sheet)

        file_menu.addSeparator()

        close_project_action = file_menu.addAction("&Close Project")
        close_project_action.setShortcut("Ctrl+W")
        close_project_action.triggered.connect(self._close_project)

        file_menu.addSeparator()

        import_action = file_menu.addAction("&Import Data...")
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self._import_data_file)

        import_figure_action = file_menu.addAction("Import From &Figure...")
        import_figure_action.triggered.connect(self._import_from_figure)

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

        delete_cells_action = QAction("&Clear Selected Cell Values", self._dataset_table)
        delete_cells_action.setShortcut(QKeySequence.Delete)
        delete_cells_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        delete_cells_action.triggered.connect(self._clear_selected_dataset_cells)
        self._dataset_table.addAction(delete_cells_action)
        edit_menu.addAction(delete_cells_action)

        delete_rows_action = QAction("&Delete Selected Rows", self._dataset_table)
        delete_rows_action.setShortcut(QKeySequence("Shift+Del"))
        delete_rows_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        delete_rows_action.triggered.connect(self._delete_selected_rows)
        self._dataset_table.addAction(delete_rows_action)
        edit_menu.addAction(delete_rows_action)

        delete_columns_action = QAction("Delete Selected &Columns", self._dataset_table)
        delete_columns_action.setShortcut(QKeySequence("Ctrl+Del"))
        delete_columns_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        delete_columns_action.triggered.connect(self._delete_selected_columns)
        self._dataset_table.addAction(delete_columns_action)
        edit_menu.addAction(delete_columns_action)

        edit_menu.addSeparator()
        paste_transposed_action = QAction("Paste Values &Transposed", self._dataset_table)
        paste_transposed_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
        paste_transposed_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        paste_transposed_action.triggered.connect(
            lambda: self._paste_dataset_clipboard(transpose=True)
        )
        self._dataset_table.addAction(paste_transposed_action)
        edit_menu.addAction(paste_transposed_action)

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

        show_plot_options_action = view_menu.addAction("Show Plot &Inspector")
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

        duplicate_dataset_action = data_menu.addAction("D&uplicate Dataset")
        duplicate_dataset_action.triggered.connect(self._duplicate_current_dataset)

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

        resize_sheet_action = data_menu.addAction("Resize &Sheet...")
        resize_sheet_action.triggered.connect(self._resize_current_sheet)

        data_menu.addSeparator()

        fill_range_action = data_menu.addAction("&Fill Range...")
        fill_range_action.triggered.connect(self._fill_dataset_range)

        data_menu.addSeparator()

        filter_query_action = data_menu.addAction("Filter / &Query...")
        filter_query_action.triggered.connect(self._run_filter_query)

        sort_action = data_menu.addAction("&Sort...")
        sort_action.triggered.connect(self._run_sort)

        remove_duplicates_action = data_menu.addAction("Remove &Duplicates...")
        remove_duplicates_action.triggered.connect(self._run_remove_duplicates)

        missing_values_action = data_menu.addAction("&Missing Values...")
        missing_values_action.triggered.connect(self._run_missing_values)

        bin_action = data_menu.addAction("&Bin / Average...")
        bin_action.triggered.connect(self._run_binning)

        group_aggregate_action = data_menu.addAction("&Group / Aggregate...")
        group_aggregate_action.triggered.connect(self._run_group_aggregate)

        merge_join_action = data_menu.addAction("Merge / &Join...")
        merge_join_action.triggered.connect(self._run_merge_join)

        reshape_action = data_menu.addAction("Res&hape...")
        reshape_action.triggered.connect(self._run_reshape)

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

        smoothing_action = analysis_menu.addAction("&Smoothing...")
        smoothing_action.triggered.connect(self._run_smoothing)

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
        new_plot_action = plot_menu.addAction("&New Empty Plot")
        new_plot_action.setShortcut("Ctrl+Alt+N")
        new_plot_action.triggered.connect(self._start_new_plot)

        save_plot_action = plot_menu.addAction("&Save Current Plot...")
        save_plot_action.setShortcut("Ctrl+Alt+S")
        save_plot_action.triggered.connect(self._save_current_plot)

        copy_plot_action = plot_menu.addAction("&Copy Current Plot to Clipboard")
        copy_plot_action.setShortcut("Ctrl+Alt+C")
        copy_plot_action.triggered.connect(
            self._plot_tab_widget.copy_plot_to_clipboard
        )

        load_plot_action = plot_menu.addAction("&Load Selected Plot")
        load_plot_action.triggered.connect(self._load_selected_plot)

        duplicate_plot_action = plot_menu.addAction("&Duplicate Selected Plot")
        duplicate_plot_action.triggered.connect(self._duplicate_selected_plot)

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
        toolbar.addAction(new_sheet_action)
        toolbar.addAction(import_action)
        toolbar.addAction(import_figure_action)
        toolbar.addAction(export_action)
        self.addToolBar(toolbar)

        self._export_action = export_action
        self._save_project_action = save_project_action
        self._save_project_as_action = save_project_as_action
        self._new_sheet_action = new_sheet_action
        self._undo_action = undo_action
        self._redo_action = redo_action
        self._delete_cells_action = delete_cells_action
        self._delete_rows_action = delete_rows_action
        self._delete_columns_action = delete_columns_action
        self._paste_transposed_action = paste_transposed_action
        self._rename_dataset_action = rename_dataset_action
        self._duplicate_dataset_action = duplicate_dataset_action
        self._delete_dataset_action = delete_dataset_action
        self._add_column_action = add_column_action
        self._insert_column_action = insert_column_action
        self._fill_range_action = fill_range_action
        self._column_metadata_action = column_metadata_action
        self._remove_duplicates_action = remove_duplicates_action
        self._apply_formula_action = apply_formula_action
        self._import_figure_action = import_figure_action
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
        self._copy_plot_action = copy_plot_action
        self._load_plot_action = load_plot_action
        self._duplicate_plot_action = duplicate_plot_action
        self._delete_plot_action = delete_plot_action
        self._add_row_action = add_row_action
        self._insert_row_action = insert_row_action
        self._resize_sheet_action = resize_sheet_action
        self._show_sidebar_action = show_sidebar_action
        self._show_workspace_action = show_workspace_action
        self._show_plots_action = show_plots_action
        self._show_plot_options_action = show_plot_options_action
        self._workspace_dock.visibilityChanged.connect(
            lambda visible: self._sync_checkable_action(self._show_sidebar_action, visible)
        )
        self._inspector_dock.visibilityChanged.connect(
            self._handle_inspector_dock_visibility_changed
        )
        self._update_dataset_summary()

    def _apply_visual_style(self) -> None:
        """Apply a polished style matched to the active Qt palette."""
        if self._applying_visual_style:
            return

        self._applying_visual_style = True
        try:
            try:
                palette = QApplication.instance().palette() if QApplication.instance() else self.palette()
                style_sheet = (
                    self._dark_visual_style(palette)
                    if self._is_dark_palette(palette)
                    else self._light_visual_style()
                )
            except Exception as exc:
                print(f"Theme styling disabled during startup: {exc}")
                style_sheet = ""

            try:
                self.setStyleSheet(style_sheet)
            except Exception as exc:
                print(f"Qt stylesheet application failed; falling back to defaults: {exc}")
                self.setStyleSheet("")
        finally:
            self._applying_visual_style = False

    @staticmethod
    def _is_dark_palette(palette: QPalette) -> bool:
        """Return whether the active Qt palette is visually dark."""
        return palette.color(MainWindow._palette_role("Window")).lightness() < 128

    @classmethod
    def _dark_visual_style(cls, palette: QPalette) -> str:
        """Return a dark-theme stylesheet derived from the active Qt palette."""
        window = palette.color(cls._palette_role("Window"))
        text = palette.color(cls._palette_role("Text"))
        base = cls._dark_safe_color(palette.color(cls._palette_role("Base")), window, text, 0.08)
        button = cls._dark_safe_color(palette.color(cls._palette_role("Button")), window, text, 0.10)
        button_text = palette.color(cls._palette_role("ButtonText"))
        highlight = palette.color(cls._palette_role("Highlight"))
        highlighted_text = palette.color(cls._palette_role("HighlightedText"))
        border = cls._mix_colors(window, text, 0.28)
        soft_border = cls._mix_colors(window, text, 0.18)
        panel = cls._mix_colors(window, base, 0.45)
        raised = cls._mix_colors(button, text, 0.06)
        hover = cls._mix_colors(button, highlight, 0.30)
        pressed = cls._mix_colors(button, highlight, 0.45)
        disabled_bg = cls._mix_colors(button, window, 0.55)
        disabled_text = cls._mix_colors(text, window, 0.50)
        selected_tab_text = cls._mix_colors(text, highlight, 0.18)
        table_alternate = cls._mix_colors(base, text, 0.05)

        colors = {
            "window": cls._qss_color(window),
            "base": cls._qss_color(base),
            "button": cls._qss_color(button),
            "raised": cls._qss_color(raised),
            "text": cls._qss_color(text),
            "button_text": cls._qss_color(button_text),
            "highlight": cls._qss_color(highlight),
            "highlighted_text": cls._qss_color(highlighted_text),
            "border": cls._qss_color(border),
            "soft_border": cls._qss_color(soft_border),
            "panel": cls._qss_color(panel),
            "hover": cls._qss_color(hover),
            "pressed": cls._qss_color(pressed),
            "disabled_bg": cls._qss_color(disabled_bg),
            "disabled_text": cls._qss_color(disabled_text),
            "selected_tab_text": cls._qss_color(selected_tab_text),
            "table_alternate": cls._qss_color(table_alternate),
        }
        return """
            QMainWindow {{
                background: {window};
                color: {text};
            }}
            QMenuBar {{
                background: {base};
                color: {text};
                border-bottom: 1px solid {border};
                padding: 2px 4px;
            }}
            QMenuBar::item:selected, QMenu::item:selected {{
                background: {highlight};
                color: {highlighted_text};
            }}
            QToolBar {{
                background: {panel};
                border-bottom: 1px solid {border};
                spacing: 4px;
                padding: 4px;
            }}
            QDockWidget {{
                color: {text};
                font-weight: 700;
            }}
            QDockWidget::title {{
                background: {panel};
                border: 1px solid {border};
                padding: 6px;
                text-align: left;
            }}
            QToolButton, QPushButton {{
                background: {button};
                border: 1px solid {border};
                border-radius: 4px;
                color: {button_text};
                padding: 5px 10px;
            }}
            QToolButton:hover, QPushButton:hover {{
                background: {hover};
                border-color: {highlight};
            }}
            QToolButton:pressed, QPushButton:pressed {{
                background: {pressed};
                border-color: {highlight};
                padding-top: 6px;
                padding-bottom: 4px;
            }}
            QToolButton:disabled, QPushButton:disabled {{
                background: {disabled_bg};
                border-color: {soft_border};
                color: {disabled_text};
            }}
            QLabel#SectionLabel {{
                color: {text};
                font-weight: 700;
                padding: 8px 2px 3px 2px;
            }}
            QListWidget, QTableView, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
                background: {base};
                border: 1px solid {border};
                border-radius: 4px;
                color: {text};
                selection-background-color: {highlight};
                selection-color: {highlighted_text};
            }}
            QSpinBox, QDoubleSpinBox {{
                padding-right: 24px;
            }}
            QSpinBox::up-button, QDoubleSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 20px;
            }}
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 20px;
            }}
            QTableView {{
                alternate-background-color: {table_alternate};
                gridline-color: {soft_border};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QListWidget:focus, QTableView:focus {{
                border: 1px solid {highlight};
            }}
            QListWidget::item {{
                padding: 4px 6px;
                border-radius: 3px;
            }}
            QListWidget::item:selected {{
                background: {highlight};
                color: {highlighted_text};
            }}
            QListWidget::item:hover {{
                background: {hover};
                color: {button_text};
            }}
            QTabWidget::pane {{
                border: 1px solid {border};
                background: {base};
                border-radius: 4px;
            }}
            QTabBar::tab {{
                background: {raised};
                border: 1px solid {border};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                color: {text};
                padding: 6px 12px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {base};
                color: {selected_tab_text};
                font-weight: 700;
            }}
            QGroupBox {{
                border: 1px solid {border};
                border-radius: 5px;
                margin-top: 10px;
                padding: 8px;
                background: {panel};
                color: {text};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: {text};
                font-weight: 700;
            }}
            QHeaderView::section {{
                background: {panel};
                border: 1px solid {border};
                color: {text};
                padding: 4px;
                font-weight: 700;
            }}
            QStatusBar {{
                background: {base};
                border-top: 1px solid {border};
                color: {text};
            }}
        """.format(**colors)

    @staticmethod
    def _light_visual_style() -> str:
        """Return the polished light stylesheet used for non-dark palettes."""
        return """
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
            QListWidget, QTableView, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
                background: #ffffff;
                border: 1px solid #b7c1cc;
                border-radius: 4px;
                selection-background-color: #2f77bc;
                selection-color: #ffffff;
            }
            QSpinBox, QDoubleSpinBox {
                padding-right: 24px;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 20px;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 20px;
            }
            QTableView {
                alternate-background-color: #f7fbff;
                gridline-color: #dbe3ec;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QListWidget:focus, QTableView:focus {
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
        """

    @staticmethod
    def _qss_color(color: QColor) -> str:
        """Return a QColor as a stylesheet-safe hex color."""
        return color.name()

    @staticmethod
    def _palette_role(role_name: str) -> QPalette.ColorRole:
        """Return a QPalette role using old or new PySide enum layouts."""
        color_role = getattr(QPalette, "ColorRole", None)
        role = getattr(color_role, role_name, None) if color_role is not None else None
        if role is None:
            role = getattr(QPalette, role_name)
        return role

    @staticmethod
    def _palette_change_event_types() -> set[QEvent.Type]:
        """Return available Qt palette-change event constants."""
        event_type = getattr(QEvent, "Type", None)
        names = ("ApplicationPaletteChange", "PaletteChange")
        values: set[QEvent.Type] = set()
        for name in names:
            value = getattr(event_type, name, None) if event_type is not None else None
            if value is None:
                value = getattr(QEvent, name, None)
            if value is not None:
                values.add(value)
        return values

    @staticmethod
    def _mix_colors(first: QColor, second: QColor, second_weight: float) -> QColor:
        """Blend two colors and return the resulting QColor."""
        weight = max(0.0, min(1.0, second_weight))
        first_weight = 1.0 - weight
        return QColor(
            round(first.red() * first_weight + second.red() * weight),
            round(first.green() * first_weight + second.green() * weight),
            round(first.blue() * first_weight + second.blue() * weight),
        )

    @classmethod
    def _dark_safe_color(
        cls,
        candidate: QColor,
        fallback_base: QColor,
        text: QColor,
        text_weight: float,
    ) -> QColor:
        """Return a dark color even when a dark OS palette exposes a light base role."""
        if candidate.lightness() < 150:
            return candidate
        return cls._mix_colors(fallback_base, text, text_weight)

    def _confirm_large_file_import(self, path: Path) -> bool:
        """Ask before reading a very large source file into memory."""
        file_size = file_size_bytes(path)
        if not should_warn_for_large_file(path):
            return True

        reply = QMessageBox.question(
            self,
            "Large File",
            (
                f"'{path.name}' is {format_bytes(file_size)} on disk.\n\n"
                "Source files can require several times their on-disk size in memory once "
                "expanded into pandas, and large sheets may make editing, undo, plotting, "
                "and analysis slower.\n\n"
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
        """Resize columns from a bounded row sample instead of scanning full sheets."""
        target_dataset = dataset or self._dataset_model.dataset
        if target_dataset is None:
            return

        profile = profile_dataframe(target_dataset.frame, target_dataset.name)
        header = self._dataset_table.horizontalHeader()
        sample_rows = (
            LARGE_AUTO_RESIZE_ROW_SAMPLE
            if profile.should_skip_full_auto_resize
            else AUTO_RESIZE_ROW_SAMPLE
        )
        header.setResizeContentsPrecision(sample_rows)
        header.setDefaultSectionSize(DEFAULT_LARGE_DATASET_COLUMN_WIDTH)
        self._dataset_table.resizeColumnsToContents()
        if profile.should_skip_full_auto_resize:
            if target_dataset.name not in self._large_dataset_warning_names:
                self._large_dataset_warning_names.add(target_dataset.name)
                self.statusBar().showMessage(
                    f"{target_dataset.name} is large; column widths used a {sample_rows}-row sample"
                )

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
        """Open a delimited file or modern Excel workbook."""
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Data File",
            "",
            "Data Files (*.csv *.txt *.xlsx *.xlsm);;Excel Workbooks (*.xlsx *.xlsm);;"
            "CSV Files (*.csv);;Text Files (*.txt);;All Files (*)",
        )
        if not file_name:
            return

        path = Path(file_name)
        if path.suffix.lower() in SUPPORTED_EXCEL_EXTENSIONS:
            self._import_excel_workbook(path)
            return
        if path.suffix.lower() in {".xls", ".xlsb"}:
            QMessageBox.warning(
                self,
                "Unsupported Excel Format",
                "JASC currently imports modern .xlsx and .xlsm workbooks only. "
                "Open this file in Excel or another compatible application and save it as .xlsx.",
            )
            self.statusBar().showMessage("Unsupported Excel format")
            return

        dialog = ImportOptionsDialog(self)
        if dialog.exec() != ImportOptionsDialog.Accepted:
            return

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
            dataset = self._workspace.add_dataset(
                path.stem,
                frame,
                source_path=path,
                copy_frame=False,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", str(exc))
            self.statusBar().showMessage("Import failed")
            return

        self._refresh_dataset_list(dataset.name)
        self.statusBar().showMessage(
            f"Imported {dataset.name}: {len(dataset.frame)} rows, {len(dataset.frame.columns)} columns"
        )

    def _import_excel_workbook(self, path: Path) -> None:
        """Import selected worksheet tabs as independent value-only datasets."""
        if not self._confirm_large_file_import(path):
            self.statusBar().showMessage("Excel import cancelled")
            return

        try:
            inspection = inspect_excel_workbook(path)
        except Exception as exc:
            QMessageBox.critical(self, "Excel Import Failed", str(exc))
            self.statusBar().showMessage("Excel import failed")
            return

        dialog = ExcelImportDialog(inspection, self)
        if dialog.exec() != QDialog.Accepted:
            self.statusBar().showMessage("Excel import cancelled")
            return

        try:
            result = read_excel_sheets(
                path,
                dialog.selected_sheet_names(),
                has_header=dialog.has_header(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Excel Import Failed", str(exc))
            self.statusBar().showMessage("Excel import failed")
            return

        imported: list[Dataset] = []
        skipped: list[str] = []
        for sheet_name in dialog.selected_sheet_names():
            frame = result.frames.get(sheet_name)
            if frame is None:
                continue
            if frame.empty and len(frame.columns) == 0:
                skipped.append(f"{sheet_name}: worksheet contains no data cells")
                continue
            if not self._confirm_large_dataset(
                frame,
                title="Large Excel Worksheet",
                source_label=f"{path.name} / {sheet_name}",
            ):
                skipped.append(f"{sheet_name}: skipped after large-dataset warning")
                continue
            imported.append(
                self._workspace.add_dataset(
                    f"{path.stem} - {sheet_name}",
                    frame,
                    source_path=path,
                    copy_frame=False,
                )
            )

        skipped.extend(f"{name}: {message}" for name, message in result.errors.items())
        if not imported:
            detail = "\n".join(skipped[:12]) or "No worksheet data was imported."
            QMessageBox.warning(self, "Excel Import", detail)
            self.statusBar().showMessage("Excel import produced no datasets")
            return

        self._refresh_dataset_list(imported[-1].name)
        total_rows = sum(len(dataset.frame) for dataset in imported)
        self.statusBar().showMessage(
            f"Imported {len(imported)} Excel worksheet(s), {total_rows} total row(s)"
        )
        if skipped:
            detail = "\n".join(f"• {message}" for message in skipped[:12])
            if len(skipped) > 12:
                detail += f"\n• ... and {len(skipped) - 12} more"
            QMessageBox.warning(
                self,
                "Excel Import Completed with Skipped Sheets",
                f"Imported {len(imported)} worksheet(s).\n\n{detail}",
            )

    def _import_from_figure(self) -> None:
        """Open a raster digitizer and add every saved curve as a dataset."""
        mode_dialog = FigureExtractionModeDialog(self)
        if mode_dialog.exec() != QDialog.Accepted:
            self.statusBar().showMessage("Figure import cancelled")
            return
        extraction_mode = mode_dialog.extraction_mode()

        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Figure Image",
            "",
            FigureDigitizerDialog.image_file_filter(),
        )
        if not file_name:
            return

        dialog_class = ColorPlotDigitizerDialog if extraction_mode == "colorplot" else FigureDigitizerDialog
        dialog = dialog_class(file_name, self)
        if dialog.exec() != QDialog.Accepted:
            self.statusBar().showMessage("Figure import cancelled")
            return

        if hasattr(dialog, "extraction_results"):
            results = dialog.extraction_results()
        else:
            rows = dialog.extracted_rows()
            results = [
                FigureExtractionResult(
                    dataset_name=dialog.dataset_name(),
                    rows=tuple(dict(row) for row in rows),
                    source_path=dialog.source_path(),
                    extraction_kind=getattr(dialog, "extraction_kind", lambda: extraction_mode)(),
                    calibration_summary=dialog.calibration_summary(),
                    extraction_summary=dialog.extraction_summary(),
                )
            ] if rows else []
        if not results:
            QMessageBox.information(self, "Import From Figure", "No extracted points were created.")
            return

        imported: list[Dataset] = []
        skipped: list[str] = []
        for result in results:
            frame = self._figure_extraction_frame(result.rows)
            if not self._confirm_large_dataset(
                frame,
                title="Large Figure Extraction",
                source_label=result.dataset_name,
            ):
                skipped.append(f"{result.dataset_name}: skipped after large-dataset warning")
                continue
            try:
                dataset = self._workspace.add_dataset(
                    result.dataset_name,
                    frame,
                    source_path=result.source_path or None,
                    copy_frame=False,
                )
                self._apply_figure_extraction_metadata(dataset, result)
                imported.append(dataset)
            except Exception as exc:
                skipped.append(f"{result.dataset_name}: {exc}")

        if not imported:
            detail = "\n".join(skipped) or "No extracted curves were imported."
            QMessageBox.warning(self, "Import From Figure Failed", detail)
            self.statusBar().showMessage("Figure import failed")
            return

        self._refresh_dataset_list(imported[-1].name)
        total_points = sum(len(dataset.frame) for dataset in imported)
        self.statusBar().showMessage(
            f"Imported {len(imported)} figure curve(s), {total_points} total point(s)"
        )
        if skipped:
            QMessageBox.warning(
                self,
                "Figure Import Completed with Skipped Curves",
                f"Imported {len(imported)} curve(s).\n\n" + "\n".join(skipped),
            )

    @staticmethod
    def _figure_extraction_frame(rows: tuple[dict[str, object], ...]) -> pd.DataFrame:
        """Create a consistently ordered DataFrame for one digitized curve."""
        columns = [
            "x",
            "y",
            "z",
            "x_uncertainty",
            "y_uncertainty",
            "pixel_x",
            "pixel_y",
            "pixel_x_uncertainty",
            "pixel_y_uncertainty",
            "method",
            "trace_mode",
            "trace_color",
            "roi_marks",
            "symbol_id",
            "symbol_area",
            "symbol_width",
            "symbol_height",
            "symbol_score",
            "symbol_template_width",
            "symbol_template_height",
            "red",
            "green",
            "blue",
            "palette_position",
            "color_distance",
            "color_confidence",
            "color_ambiguous",
            "color_valid",
            "patch_radius",
            "source_image",
        ]
        frame = pd.DataFrame(rows)
        return frame[[column for column in columns if column in frame.columns]]

    @staticmethod
    def _apply_figure_extraction_metadata(
        dataset: Dataset,
        result: FigureExtractionResult,
    ) -> None:
        """Assign column roles and captured provenance to one digitized result."""
        if "x" in dataset.frame.columns:
            x_metadata = dataset.metadata_for_column("x")
            x_metadata.role = "x"
            x_metadata.value_type = "numeric"
            x_metadata.long_name = "Digitized X"
        if "y" in dataset.frame.columns:
            y_metadata = dataset.metadata_for_column("y")
            y_metadata.role = "y"
            y_metadata.value_type = "numeric"
            y_metadata.long_name = "Digitized Y"
        if "z" in dataset.frame.columns:
            z_metadata = dataset.metadata_for_column("z")
            z_metadata.role = "z"
            z_metadata.value_type = "numeric"
            z_metadata.long_name = "Digitized colour value"
            z_metadata.comment = (
                "Estimated from rendered image colours; compression, anti-aliasing, resizing, "
                "overlays, and limited palette resolution may introduce error."
            )
        for column_name in ("pixel_x", "pixel_y"):
            if column_name in dataset.frame.columns:
                metadata = dataset.metadata_for_column(column_name)
                metadata.value_type = "numeric"
                metadata.comment = "Source pixel coordinate from figure digitization."
        for column_name in ("trace_mode", "trace_color", "roi_marks"):
            if column_name in dataset.frame.columns:
                metadata = dataset.metadata_for_column(column_name)
                metadata.comment = "Automatic figure-trace provenance."
        for column_name in (
            "red",
            "green",
            "blue",
            "palette_position",
            "color_distance",
            "color_confidence",
            "patch_radius",
        ):
            if column_name in dataset.frame.columns:
                metadata = dataset.metadata_for_column(column_name)
                metadata.value_type = "numeric"
                metadata.comment = "Colour-plot raster matching diagnostic."
        for column_name in ("color_ambiguous", "color_valid"):
            if column_name in dataset.frame.columns:
                dataset.metadata_for_column(column_name).comment = (
                    "Colour-plot match quality flag; review before using the estimated Z value."
                )
        for column_name in (
            "symbol_id",
            "symbol_area",
            "symbol_width",
            "symbol_height",
            "symbol_score",
            "symbol_template_width",
            "symbol_template_height",
            "pixel_x_uncertainty",
            "pixel_y_uncertainty",
            "x_uncertainty",
            "y_uncertainty",
        ):
            if column_name in dataset.frame.columns:
                metadata = dataset.metadata_for_column(column_name)
                metadata.value_type = "numeric"
                metadata.comment = "Detected symbol-center diagnostics from figure digitization."
                if column_name == "x_uncertainty":
                    metadata.role = "x_error"
                    metadata.comment = "Estimated digitized X uncertainty from manual error picks or symbol/template size and calibration."
                elif column_name == "y_uncertainty":
                    metadata.role = "y_error"
                    metadata.comment = "Estimated digitized Y uncertainty from manual error picks or symbol/template size and calibration."
                elif column_name in {"pixel_x_uncertainty", "pixel_y_uncertainty"}:
                    metadata.comment = "Estimated manual or symbol-center uncertainty in source-image pixels."
        operation = (
            f"Figure digitization from {Path(result.source_path).name}; "
            f"{result.calibration_summary}; {result.extraction_summary}"
        )
        set_dataset_operation_comments(dataset, operation)
        dataset.sync_column_metadata_attrs()

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

        edited_column_names = dialog.column_names()
        edited_metadata = dialog.column_metadata()
        validation_errors = self._validate_column_metadata_types(
            dataset=dataset,
            edited_column_names=edited_column_names,
            metadata=edited_metadata,
        )
        if validation_errors:
            QMessageBox.warning(
                self,
                "Column Metadata",
                "\n".join(validation_errors[:8]),
            )
            return

        try:
            renamed_columns = self._dataset_model.apply_column_metadata(
                column_names=edited_column_names,
                metadata=edited_metadata,
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

    @staticmethod
    def _validate_column_metadata_types(
        dataset: Dataset,
        edited_column_names: list[str],
        metadata: dict[str, ColumnMetadata],
    ) -> list[str]:
        """Return metadata type validation errors before applying metadata edits."""
        errors: list[str] = []
        numeric_roles = {"y", "z", "error", "x_error", "y_error", "weight"}
        for column_index, edited_name in enumerate(edited_column_names):
            entry = metadata.get(edited_name)
            if entry is None:
                continue

            if entry.value_type == "text" and entry.role in numeric_roles:
                errors.append(
                    f"Column '{edited_name}' is marked Text but role "
                    f"'{entry.role}' requires numeric values."
                )
                continue

            if entry.value_type not in COLUMN_NUMERIC_TYPES:
                continue
            if column_index >= len(dataset.frame.columns):
                continue

            values = dataset.frame.iloc[:, column_index]
            meaningful = values.notna() & (values.astype(str).str.strip() != "")
            if not meaningful.any():
                continue
            numeric_values = pd.to_numeric(values[meaningful], errors="coerce")
            invalid = numeric_values.isna()
            if invalid.any():
                example = str(values[meaningful][invalid].iloc[0])
                errors.append(
                    f"Column '{edited_name}' is marked "
                    f"{column_type_label(entry.value_type)} but contains non-numeric text "
                    f"such as '{example}'."
                )
        return errors

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

    @staticmethod
    def _batch_column_binding_label(binding_mode: str) -> str:
        """Return a readable label for a batch column binding mode."""
        if binding_mode == BATCH_COLUMN_BINDING_POSITION:
            return "column_position"
        return "exact_column_name"

    @staticmethod
    def _column_position_label(position: int) -> str:
        """Return the 1-based colN label for a zero-based column position."""
        return f"col{position + 1}"

    def _show_batch_preview(
        self,
        title: str,
        rows: list[dict[str, object]],
        columns: list[tuple[str, str]],
    ) -> bool:
        """Show a batch preflight preview and return whether to continue."""
        if not rows:
            QMessageBox.warning(self, title, "No batch jobs were prepared.")
            return False
        dialog = BatchPreviewDialog(title, rows, columns, self)
        return dialog.exec() == BatchPreviewDialog.Accepted

    def _batch_progress_dialog(self, title: str, total_jobs: int) -> QProgressDialog | None:
        """Return a progress dialog for multi-job batch runs."""
        if total_jobs <= 1:
            return None
        progress = QProgressDialog("Preparing batch...", "Cancel", 0, total_jobs, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()
        return progress

    @staticmethod
    def _batch_progress_canceled(
        progress: QProgressDialog | None,
        completed_jobs: int,
        message: str,
    ) -> bool:
        """Advance progress and return whether the user canceled."""
        if progress is None:
            return False
        progress.setLabelText(message)
        progress.setValue(completed_jobs)
        QApplication.processEvents()
        return progress.wasCanceled()

    def _resolve_batch_column(
        self,
        reference_dataset: Dataset,
        target_dataset: Dataset,
        source_column: str | None,
        binding_mode: str,
        field_label: str,
    ) -> str | None:
        """Resolve one source column against a target worksheet using the requested binding."""
        if source_column is None:
            return None

        clean_source = str(source_column)
        if binding_mode != BATCH_COLUMN_BINDING_POSITION:
            if clean_source not in target_dataset.frame.columns:
                raise MathOperationError(
                    f"{field_label} column '{clean_source}' does not exist in '{target_dataset.name}'."
                )
            return clean_source

        reference_columns = [str(column) for column in reference_dataset.frame.columns]
        try:
            source_position = reference_columns.index(clean_source)
        except ValueError as exc:
            raise MathOperationError(
                f"{field_label} source column '{clean_source}' no longer exists in '{reference_dataset.name}'."
            ) from exc

        target_columns = [str(column) for column in target_dataset.frame.columns]
        if source_position >= len(target_columns):
            raise MathOperationError(
                f"{field_label} source column '{clean_source}' is {self._column_position_label(source_position)}, "
                f"but '{target_dataset.name}' has only {len(target_columns)} column(s)."
            )
        return target_columns[source_position]

    def _resolve_batch_columns(
        self,
        reference_dataset: Dataset,
        target_dataset: Dataset,
        source_columns: list[str],
        binding_mode: str,
        field_label: str,
    ) -> list[str]:
        """Resolve multiple source columns against a target worksheet."""
        resolved_columns: list[str] = []
        for index, source_column in enumerate(source_columns, start=1):
            resolved = self._resolve_batch_column(
                reference_dataset=reference_dataset,
                target_dataset=target_dataset,
                source_column=source_column,
                binding_mode=binding_mode,
                field_label=f"{field_label} {index}",
            )
            if resolved is not None:
                resolved_columns.append(resolved)
        return resolved_columns

    def _formula_evaluation_frame(
        self,
        reference_dataset: Dataset,
        target_dataset: Dataset,
        binding_mode: str,
    ) -> pd.DataFrame:
        """Return the DataFrame used to evaluate a formula under the selected binding mode."""
        if binding_mode != BATCH_COLUMN_BINDING_POSITION or reference_dataset.name == target_dataset.name:
            return target_dataset.frame

        evaluation_frame = target_dataset.frame.copy()
        reference_columns = [str(column) for column in reference_dataset.frame.columns]
        renamed_columns = [
            reference_columns[index] if index < len(reference_columns) else str(column)
            for index, column in enumerate(evaluation_frame.columns)
        ]
        evaluation_frame.columns = renamed_columns
        return evaluation_frame

    @staticmethod
    def _batch_output_column_name(base_name: str, source_column: str, multiple_columns: bool) -> str:
        """Return an output column name for single- or multi-source-column batches."""
        clean_base = base_name.strip() or "Result"
        if "{column}" in clean_base:
            return clean_base.replace("{column}", str(source_column))
        if multiple_columns:
            return f"{clean_base}_{source_column}"
        return clean_base

    def _batch_output_target_plan(
        self,
        target_requests: list[dict[str, object]],
        conflict_policy: str,
    ) -> list[dict[str, object]]:
        """Resolve output target columns for pre-expanded batch requests."""
        planned_columns_by_sheet: dict[str, set[str]] = {}
        existing_columns_by_sheet: dict[str, set[str]] = {}
        plan_rows: list[dict[str, object]] = []
        for request in target_requests:
            target_dataset_name = str(request["source_sheet"])
            if target_dataset_name not in planned_columns_by_sheet:
                target_dataset = self._workspace.get_dataset(target_dataset_name)
                existing_columns = {str(column) for column in target_dataset.frame.columns}
                existing_columns_by_sheet[target_dataset_name] = set(existing_columns)
                planned_columns_by_sheet[target_dataset_name] = set(existing_columns)

            requested_target = str(request["requested_target_column"]).strip()
            existing_columns = existing_columns_by_sheet[target_dataset_name]
            planned_columns = planned_columns_by_sheet[target_dataset_name]
            target_existed_before = requested_target in existing_columns
            target_exists = requested_target in planned_columns
            final_target = requested_target
            output_action = "create"
            if target_exists and conflict_policy == "unique":
                final_target = self._unique_batch_column_name(requested_target, planned_columns)
                output_action = "create_unique"
            elif target_exists and conflict_policy == "stop":
                output_action = "blocked"
            elif target_exists:
                output_action = "overwrite"
            planned_columns.add(final_target)
            row = dict(request)
            row.update(
                {
                    "requested_target_column": requested_target,
                    "target_column": final_target,
                    "target_existed_before": target_existed_before,
                    "output_action": output_action,
                }
            )
            plan_rows.append(row)
        return plan_rows

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
        column_binding_mode = dialog.column_binding_mode()
        target_plan = self._formula_batch_target_plan(
            target_dataset_names=target_dataset_names,
            target_column=target_column,
            conflict_policy=conflict_policy,
        )
        if (len(target_plan) > 1 or any(row["output_action"] == "blocked" for row in target_plan)) and not (
            self._show_batch_preview(
                "Formula Batch Preview",
                self._formula_batch_preview_rows(target_plan, column_binding_mode),
                [
                    ("Sheet", "source_sheet"),
                    ("Status", "status"),
                    ("Target", "target_column"),
                    ("Action", "output_action"),
                    ("Binding", "column_binding"),
                    ("Details", "error"),
                ],
            )
        ):
            return
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
        sequential_plan_rows = [
            row
            for row in target_plan
            if str(row["source_sheet"]) not in parallel_sheet_names
        ]
        progress = self._batch_progress_dialog("Formula Batch", len(sequential_plan_rows))
        completed_jobs = 0
        canceled = False
        for plan_row in target_plan:
            target_dataset_name = str(plan_row["source_sheet"])
            if target_dataset_name in parallel_sheet_names:
                continue

            if self._batch_progress_canceled(
                progress,
                completed_jobs,
                f"Formula: {target_dataset_name}",
            ):
                canceled = True
                break
            started = time.perf_counter()
            try:
                target_dataset = self._workspace.get_dataset(target_dataset_name)
                use_visible_model = target_dataset.name == dataset.name
                evaluation_frame = self._formula_evaluation_frame(
                    reference_dataset=dataset,
                    target_dataset=target_dataset,
                    binding_mode=column_binding_mode,
                )
                result = self._apply_expression_to_dataset(
                    dataset=target_dataset,
                    target_column=str(plan_row["target_column"]),
                    expression=expression,
                    row_positions=row_positions if use_visible_model else None,
                    use_visible_model=use_visible_model,
                    evaluation_frame=evaluation_frame,
                    column_binding_mode=column_binding_mode,
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
                        column_binding_mode=column_binding_mode,
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
                        column_binding_mode=column_binding_mode,
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
                        column_binding_mode=column_binding_mode,
                        execution_mode="sequential",
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            completed_jobs += 1

        if progress is not None:
            progress.setValue(completed_jobs)
        if canceled:
            for plan_row in sequential_plan_rows[completed_jobs:]:
                target_dataset_name = str(plan_row["source_sheet"])
                results_by_sheet[target_dataset_name] = self._formula_batch_summary_row(
                    dataset_name=target_dataset_name,
                    result_target_column=str(plan_row["target_column"]),
                    updated_rows=0,
                    status="canceled",
                    error="Canceled by user before this sheet was processed.",
                    requested_target_column=target_column,
                    output_action=str(plan_row["output_action"]),
                    target_existed_before=bool(plan_row["target_existed_before"]),
                    column_binding_mode=column_binding_mode,
                    execution_mode="sequential",
                    elapsed_seconds=0.0,
                )

        if parallel_plan_rows and not canceled:
            parallel_results = self._run_parallel_formula_batch_rows(
                plan_rows=parallel_plan_rows,
                expression=expression,
                requested_target_column=target_column,
                execution_decision=execution_decision,
                reference_dataset=dataset,
                column_binding_mode=column_binding_mode,
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
        evaluation_frame: pd.DataFrame | None = None,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
    ) -> ExpressionResult:
        """Apply a formula to one dataset, using the visible model when possible."""
        operation_comment = (
            f"Formula = {expression.strip()} "
            f"({self._batch_column_binding_label(column_binding_mode)})"
        )
        if use_visible_model:
            result = self._dataset_model.apply_expression(
                target_column=target_column,
                expression=expression,
                row_positions=row_positions,
            )
            set_column_operation_comment(dataset, result.target_column, operation_comment)
            return result

        target_frame = evaluation_frame if evaluation_frame is not None else dataset.frame
        result = apply_column_expression(
            target_frame,
            target_column=target_column,
            expression=expression,
            row_positions=row_positions,
        )
        if target_frame is not dataset.frame:
            dataset.frame[result.target_column] = target_frame[result.target_column].reindex(dataset.frame.index)
        dataset.formulas[result.target_column] = expression.strip()
        set_column_operation_comment(
            dataset,
            result.target_column,
            operation_comment,
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

    def _formula_batch_preview_rows(
        self,
        plan_rows: list[dict[str, object]],
        column_binding_mode: str,
    ) -> list[dict[str, object]]:
        """Return preview rows for formula output targets."""
        rows: list[dict[str, object]] = []
        for row in plan_rows:
            output_action = str(row["output_action"])
            status = "blocked" if output_action == "blocked" else "ready"
            error = "Target exists and the selected policy is Stop." if status == "blocked" else ""
            rows.append(
                {
                    "source_sheet": row["source_sheet"],
                    "status": status,
                    "target_column": row["target_column"],
                    "output_action": output_action,
                    "column_binding": self._batch_column_binding_label(column_binding_mode),
                    "error": error,
                }
            )
        return rows

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
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
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
            "column_binding": self._batch_column_binding_label(column_binding_mode),
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
        reference_dataset: Dataset,
        column_binding_mode: str,
    ) -> dict[str, dict[str, object]]:
        """Run formula batch rows in worker processes and apply successful outputs."""
        results_by_sheet: dict[str, dict[str, object]] = {}
        tasks: list[FormulaBatchTask] = []
        for plan_row in plan_rows:
            target_dataset = self._workspace.get_dataset(str(plan_row["source_sheet"]))
            tasks.append(
                FormulaBatchTask(
                    source_sheet=str(plan_row["source_sheet"]),
                    target_column=str(plan_row["target_column"]),
                    expression=expression,
                    frame=self._formula_evaluation_frame(
                        reference_dataset=reference_dataset,
                        target_dataset=target_dataset,
                        binding_mode=column_binding_mode,
                    ),
                )
            )

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
                reference_dataset=reference_dataset,
                column_binding_mode=column_binding_mode,
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
                    column_binding_mode=column_binding_mode,
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
                    column_binding_mode=column_binding_mode,
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
                    column_binding_mode=column_binding_mode,
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
                    column_binding_mode=column_binding_mode,
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
        reference_dataset: Dataset,
        column_binding_mode: str,
    ) -> dict[str, dict[str, object]]:
        """Run formula batch rows sequentially after a parallel fallback."""
        results_by_sheet: dict[str, dict[str, object]] = {}
        for plan_row in plan_rows:
            target_dataset_name = str(plan_row["source_sheet"])
            started = time.perf_counter()
            try:
                target_dataset = self._workspace.get_dataset(target_dataset_name)
                evaluation_frame = self._formula_evaluation_frame(
                    reference_dataset=reference_dataset,
                    target_dataset=target_dataset,
                    binding_mode=column_binding_mode,
                )
                result = self._apply_expression_to_dataset(
                    dataset=target_dataset,
                    target_column=str(plan_row["target_column"]),
                    expression=expression,
                    row_positions=None,
                    use_visible_model=False,
                    evaluation_frame=evaluation_frame,
                    column_binding_mode=column_binding_mode,
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
                    column_binding_mode=column_binding_mode,
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
                    column_binding_mode=column_binding_mode,
                    execution_mode=execution_mode,
                    elapsed_seconds=time.perf_counter() - started,
                )
        return results_by_sheet

    def _apply_formula_worker_result_to_dataset(
        self,
        dataset: Dataset,
        worker_result: FormulaBatchWorkerResult,
        expression: str,
        column_binding_mode: str,
    ) -> ExpressionResult:
        """Apply a successful process-worker formula result to a workspace dataset."""
        if worker_result.values is None:
            raise ExpressionError("Worker did not return formula values.")

        dataset.frame[worker_result.target_column] = worker_result.values.reindex(dataset.frame.index)
        dataset.formulas[worker_result.target_column] = expression.strip()
        set_column_operation_comment(
            dataset,
            worker_result.target_column,
            (
                f"Formula = {expression.strip()} "
                f"({self._batch_column_binding_label(column_binding_mode)})"
            ),
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

    def _run_smoothing(self) -> None:
        """Run the smoothing workbench for one or more worksheet signals."""
        current_dataset = self._current_dataset()
        if current_dataset is None:
            QMessageBox.information(self, "Smoothing", "Select a dataset before smoothing data.")
            return

        dialog = SmoothingDialog(
            frame=current_dataset.frame,
            column_names=[str(column) for column in current_dataset.frame.columns],
            default_x_column=self._preferred_dataset_column(current_dataset, ("x",), fallback_index=0),
            dataset_names=[
                candidate.name
                for candidate in self._workspace.list_datasets()
                if len(candidate.frame.columns) > 0
            ],
            current_dataset_name=current_dataset.name,
            parent=self,
        )
        if dialog.exec() != SmoothingDialog.Accepted:
            return
        self._run_smoothing_batch(current_dataset, dialog)

    def _run_smoothing_batch(self, current_dataset: Dataset, dialog: SmoothingDialog) -> None:
        """Validate and apply smoothing jobs using existing batch conventions."""
        requested_x = dialog.x_column()
        requested_y_columns = dialog.y_columns()
        binding_mode = dialog.column_binding_mode()
        multiple_y = len(requested_y_columns) > 1
        requests: list[dict[str, object]] = []
        results: list[dict[str, object]] = []

        for dataset_name in dialog.target_dataset_names():
            try:
                dataset = self._workspace.get_dataset(dataset_name)
                resolved_x = self._resolve_batch_column(
                    current_dataset, dataset, requested_x, binding_mode, "X"
                )
                if resolved_x is None:
                    raise MathOperationError("Choose an X column.")
            except Exception as exc:
                for requested_y in requested_y_columns:
                    results.append({
                        "source_sheet": dataset_name,
                        "requested_x_column": requested_x,
                        "requested_y_column": requested_y,
                        "x_column": "",
                        "y_column": "",
                        "method": dialog.method(),
                        "method_label": SMOOTHING_METHODS.get(dialog.method(), dialog.method()),
                        "target_column": "",
                        "values_written": 0,
                        "status": "failed",
                        "error": str(exc),
                        "elapsed_seconds": 0.0,
                    })
                continue

            for requested_y in requested_y_columns:
                try:
                    resolved_y = self._resolve_batch_column(
                        current_dataset, dataset, requested_y, binding_mode, "Y"
                    )
                    if resolved_y is None:
                        raise MathOperationError("Choose a Y column.")
                    requests.append({
                        "source_sheet": dataset.name,
                        "requested_x_column": requested_x,
                        "requested_y_column": requested_y,
                        "x_column": resolved_x,
                        "y_column": resolved_y,
                        "requested_target_column": self._batch_output_column_name(
                            dialog.target_column(), resolved_y, multiple_y
                        ),
                    })
                except Exception as exc:
                    results.append({
                        "source_sheet": dataset_name,
                        "requested_x_column": requested_x,
                        "requested_y_column": requested_y,
                        "x_column": resolved_x,
                        "y_column": "",
                        "method": dialog.method(),
                        "method_label": SMOOTHING_METHODS.get(dialog.method(), dialog.method()),
                        "target_column": "",
                        "values_written": 0,
                        "status": "failed",
                        "error": str(exc),
                        "elapsed_seconds": 0.0,
                    })

        plan = self._batch_output_target_plan(requests, dialog.target_conflict_policy())
        preview_rows = [
            {
                "source_sheet": row["source_sheet"],
                "status": "blocked" if row["output_action"] == "blocked" else "ready",
                "x_column": row["x_column"],
                "y_column": row["y_column"],
                "target_column": row["target_column"],
                "method": SMOOTHING_METHODS.get(dialog.method(), dialog.method()),
                "output_action": row["output_action"],
                "error": "Target exists and policy is Stop." if row["output_action"] == "blocked" else "",
            }
            for row in plan
        ]
        preview_rows.extend({
            "source_sheet": row["source_sheet"],
            "status": "failed",
            "x_column": row["requested_x_column"],
            "y_column": row["requested_y_column"],
            "target_column": "",
            "method": row["method_label"],
            "output_action": "input_error",
            "error": row["error"],
        } for row in results)
        if (len(preview_rows) > 1 or any(row["status"] != "ready" for row in preview_rows)) and not self._show_batch_preview(
            "Smoothing Batch Preview",
            preview_rows,
            [
                ("Sheet", "source_sheet"),
                ("Status", "status"),
                ("X", "x_column"),
                ("Y", "y_column"),
                ("Method", "method"),
                ("Target", "target_column"),
                ("Action", "output_action"),
                ("Details", "error"),
            ],
        ):
            return
        if not plan:
            QMessageBox.warning(self, "Smoothing Failed", results[0]["error"] if results else "No smoothing jobs were created.")
            return
        if not self._confirm_column_math_batch_target_plan(
            plan, dialog.target_conflict_policy(), "Smoothing"
        ):
            return

        parameters = dialog.parameters()
        progress = self._batch_progress_dialog("Smoothing Batch", len(plan))
        active_plot: tuple[str, str, str] | None = None
        completed = 0
        canceled = False
        for row in plan:
            dataset_name = str(row["source_sheet"])
            if self._batch_progress_canceled(
                progress, completed, f"Smoothing: {dataset_name} / {row['y_column']}"
            ):
                canceled = True
                break
            started = time.perf_counter()
            dataset = self._workspace.get_dataset(dataset_name)
            use_visible_model = dataset.name == current_dataset.name
            if use_visible_model:
                self._dataset_model.capture_undo_state()
            try:
                result = smooth_column(
                    dataset.frame,
                    x_column=str(row["x_column"]),
                    y_column=str(row["y_column"]),
                    method=dialog.method(),
                    target_column=str(row["target_column"]),
                    parameters=parameters,
                )
                self._apply_smoothing_metadata(
                    dataset,
                    source_column=str(row["y_column"]),
                    result_column=result.column_name,
                    operation_text=smoothing_operation_text(
                        str(row["x_column"]),
                        str(row["y_column"]),
                        dialog.method(),
                        parameters,
                    ),
                )
                if use_visible_model:
                    self._dataset_model.history_changed.emit()
                    if active_plot is None:
                        active_plot = (
                            str(row["x_column"]), str(row["y_column"]), result.column_name
                        )
                results.append(self._smoothing_summary_row(
                    row, dialog.method(), result.column_name, result.values_written,
                    "ok", "", time.perf_counter() - started,
                ))
            except Exception as exc:
                if use_visible_model:
                    self._dataset_model.discard_latest_undo_state()
                results.append(self._smoothing_summary_row(
                    row, dialog.method(), str(row["target_column"]), 0,
                    "failed", str(exc), time.perf_counter() - started,
                ))
            completed += 1

        if progress is not None:
            progress.setValue(completed)
        if canceled:
            for row in plan[completed:]:
                results.append(self._smoothing_summary_row(
                    row, dialog.method(), str(row["target_column"]), 0,
                    "canceled", "Canceled by user before processing.", 0.0,
                ))

        success_count = sum(row["status"] == "ok" for row in results)
        failures = [row for row in results if row["status"] != "ok"]
        summary_dataset = None
        if len(results) > 1:
            summary_dataset = self._workspace.add_dataset(
                f"{current_dataset.name}_smoothing_batch_summary", pd.DataFrame(results)
            )
            self._dataset_list.addItem(summary_dataset.name)

        self._dataset_model.set_dataset(current_dataset)
        self._resize_dataset_columns_to_contents(current_dataset)
        self._plot_tab_widget.refresh_controls(current_dataset.name)
        self._update_dataset_summary()
        if active_plot is not None:
            self._select_column(active_plot[2])

        if active_plot is not None and dialog.plot_result_immediately():
            x_column, source_column, result_column = active_plot
            self._plot_tab_widget.queue_plot_series(
                [
                    PlotSeries(
                        x_dataset=current_dataset.name, x_column=x_column,
                        y_dataset=current_dataset.name, y_column=source_column,
                        plot_type="line", color="0.55", custom_label=source_column,
                    ),
                    PlotSeries(
                        x_dataset=current_dataset.name, x_column=x_column,
                        y_dataset=current_dataset.name, y_column=result_column,
                        plot_type="line", color="tab:red", custom_label=result_column,
                    ),
                ],
                title=f"{SMOOTHING_METHODS.get(dialog.method(), dialog.method())}: {source_column}",
                selected_dataset_name=current_dataset.name,
            )
            self._tabs.setCurrentWidget(self._plot_tab_widget)

        if success_count == 0:
            detail = "\n".join(f"{row['source_sheet']}: {row['error']}" for row in failures[:8])
            QMessageBox.warning(self, "Smoothing Failed", detail or "Smoothing failed.")
        elif failures:
            QMessageBox.warning(
                self, "Smoothing Batch",
                f"Created {success_count} smoothed result(s); {len(failures)} did not complete."
            )
        summary_text = f"; summary saved as '{summary_dataset.name}'" if summary_dataset else ""
        self.statusBar().showMessage(
            f"Created {success_count} smoothed result(s), {len(failures)} incomplete{summary_text}"
        )

    @staticmethod
    def _apply_smoothing_metadata(
        dataset: Dataset,
        source_column: str,
        result_column: str,
        operation_text: str,
    ) -> None:
        """Copy signal metadata to a smoothed output and append provenance."""
        source = dataset.column_metadata.get(source_column, ColumnMetadata())
        existing = dataset.column_metadata.get(result_column, ColumnMetadata())
        dataset.column_metadata[result_column] = ColumnMetadata(
            role=source.role,
            unit=source.unit,
            long_name=f"Smoothed {source.long_name or source_column}",
            comment=existing.comment or source.comment,
            value_type=source.value_type,
            display_precision=source.display_precision,
        )
        set_column_operation_comment(dataset, result_column, operation_text)
        dataset.prune_column_metadata()

    @staticmethod
    def _smoothing_summary_row(
        plan_row: dict[str, object],
        method: str,
        result_column: str,
        values_written: int,
        status: str,
        error: str,
        elapsed_seconds: float,
    ) -> dict[str, object]:
        """Return one tidy smoothing batch result row."""
        return {
            "source_sheet": plan_row["source_sheet"],
            "requested_x_column": plan_row["requested_x_column"],
            "requested_y_column": plan_row["requested_y_column"],
            "x_column": plan_row["x_column"],
            "y_column": plan_row["y_column"],
            "method": method,
            "method_label": SMOOTHING_METHODS.get(method, method),
            "requested_target_column": plan_row["requested_target_column"],
            "target_column": result_column,
            "output_action": plan_row["output_action"],
            "values_written": values_written,
            "status": status,
            "error": error,
            "elapsed_seconds": elapsed_seconds,
        }

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
        column_binding_mode = dialog.column_binding_mode()
        requested_x_column = dialog.x_column()
        requested_y_columns = dialog.y_columns()
        multiple_y_columns = len(requested_y_columns) > 1
        target_requests: list[dict[str, object]] = []
        preflight_results: list[dict[str, object]] = []
        for target_dataset_name in target_dataset_names:
            try:
                target_dataset = self._workspace.get_dataset(target_dataset_name)
            except Exception as exc:
                started = time.perf_counter()
                for requested_y_column in requested_y_columns:
                    requested_target_column = self._batch_output_column_name(
                        dialog.target_column(),
                        requested_y_column,
                        multiple_y_columns,
                    )
                    preflight_results.append(
                        self._column_math_batch_summary_row(
                            dataset_name=target_dataset_name,
                            operation_title=operation_title,
                            x_column=requested_x_column,
                            y_column=requested_y_column,
                            requested_x_column=requested_x_column,
                            requested_y_column=requested_y_column,
                            column_binding_mode=column_binding_mode,
                            method=dialog.method(),
                            method_label=methods.get(dialog.method(), dialog.method()),
                            initial_value=initial_value,
                            result_column="",
                            values_written=0,
                            status="failed",
                            error=str(exc),
                            requested_target_column=requested_target_column,
                            output_action="input_error",
                            target_existed_before=False,
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                continue

            for requested_y_column in requested_y_columns:
                started = time.perf_counter()
                try:
                    y_column = self._resolve_batch_column(
                        reference_dataset=current_dataset,
                        target_dataset=target_dataset,
                        source_column=requested_y_column,
                        binding_mode=column_binding_mode,
                        field_label="Y",
                    )
                    if y_column is None:
                        raise MathOperationError("Choose at least one Y column.")
                    target_requests.append(
                        {
                            "source_sheet": target_dataset.name,
                            "requested_x_column": requested_x_column,
                            "requested_y_column": requested_y_column,
                            "y_column": y_column,
                            "requested_target_column": self._batch_output_column_name(
                                dialog.target_column(),
                                y_column,
                                multiple_y_columns,
                            ),
                        }
                    )
                except MathOperationError as exc:
                    requested_target_column = self._batch_output_column_name(
                        dialog.target_column(),
                        requested_y_column,
                        multiple_y_columns,
                    )
                    preflight_results.append(
                        self._column_math_batch_summary_row(
                            dataset_name=target_dataset_name,
                            operation_title=operation_title,
                            x_column=requested_x_column,
                            y_column=requested_y_column,
                            requested_x_column=requested_x_column,
                            requested_y_column=requested_y_column,
                            column_binding_mode=column_binding_mode,
                            method=dialog.method(),
                            method_label=methods.get(dialog.method(), dialog.method()),
                            initial_value=initial_value,
                            result_column="",
                            values_written=0,
                            status="failed",
                            error=str(exc),
                            requested_target_column=requested_target_column,
                            output_action="input_error",
                            target_existed_before=False,
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                except Exception as exc:
                    requested_target_column = self._batch_output_column_name(
                        dialog.target_column(),
                        requested_y_column,
                        multiple_y_columns,
                    )
                    preflight_results.append(
                        self._column_math_batch_summary_row(
                            dataset_name=target_dataset_name,
                            operation_title=operation_title,
                            x_column=requested_x_column,
                            y_column=requested_y_column,
                            requested_x_column=requested_x_column,
                            requested_y_column=requested_y_column,
                            column_binding_mode=column_binding_mode,
                            method=dialog.method(),
                            method_label=methods.get(dialog.method(), dialog.method()),
                            initial_value=initial_value,
                            result_column="",
                            values_written=0,
                            status="failed",
                            error=str(exc),
                            requested_target_column=requested_target_column,
                            output_action="input_error",
                            target_existed_before=False,
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
        target_plan = self._batch_output_target_plan(
            target_requests=target_requests,
            conflict_policy=dialog.target_conflict_policy(),
        )
        preview_rows = self._column_math_batch_preview_rows(
            target_plan=target_plan,
            preflight_results=preflight_results,
            column_binding_mode=column_binding_mode,
        )
        if (len(preview_rows) > 1 or any(row["status"] in {"failed", "blocked"} for row in preview_rows)) and not (
            self._show_batch_preview(
                f"{operation_title} Batch Preview",
                preview_rows,
                [
                    ("Sheet", "source_sheet"),
                    ("Status", "status"),
                    ("X", "x_column"),
                    ("Y", "y_column"),
                    ("Target", "target_column"),
                    ("Action", "output_action"),
                    ("Binding", "column_binding"),
                    ("Details", "error"),
                ],
            )
        ):
            return
        if not self._confirm_column_math_batch_target_plan(
            target_plan,
            dialog.target_conflict_policy(),
            operation_title,
        ):
            return

        results: list[dict[str, object]] = list(preflight_results)
        current_result_target = ""
        progress = self._batch_progress_dialog(f"{operation_title} Batch", len(target_plan))
        completed_jobs = 0
        canceled = False
        for plan_row in target_plan:
            target_dataset_name = str(plan_row["source_sheet"])
            requested_y_column = str(plan_row["requested_y_column"])
            planned_y_column = str(plan_row["y_column"])
            if self._batch_progress_canceled(
                progress,
                completed_jobs,
                f"{operation_title}: {target_dataset_name} / {requested_y_column}",
            ):
                canceled = True
                break
            started = time.perf_counter()
            try:
                target_dataset = self._workspace.get_dataset(target_dataset_name)
                use_visible_model = target_dataset.name == current_dataset.name
                x_column = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=target_dataset,
                    source_column=requested_x_column,
                    binding_mode=column_binding_mode,
                    field_label="X",
                )
                if x_column is None or not planned_y_column:
                    raise MathOperationError("Choose X and Y columns.")
                result = self._apply_column_math_to_dataset(
                    dataset=target_dataset,
                    operation_key=operation_key,
                    x_column=x_column,
                    y_column=planned_y_column,
                    method=dialog.method(),
                    target_column=str(plan_row["target_column"]),
                    initial_value=initial_value,
                    use_visible_model=use_visible_model,
                    methods=methods,
                    operation_title=operation_title,
                    column_binding_mode=column_binding_mode,
                )
                if use_visible_model and not current_result_target:
                    current_result_target = result.column_name
                results.append(
                    self._column_math_batch_summary_row(
                        dataset=target_dataset,
                        operation_title=operation_title,
                        x_column=x_column,
                        y_column=planned_y_column,
                        requested_x_column=requested_x_column,
                        requested_y_column=requested_y_column,
                        column_binding_mode=column_binding_mode,
                        method=dialog.method(),
                        method_label=methods.get(dialog.method(), dialog.method()),
                        initial_value=initial_value,
                        result_column=result.column_name,
                        values_written=result.values_written,
                        status="ok",
                        error="",
                        requested_target_column=str(plan_row["requested_target_column"]),
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
                        x_column=requested_x_column,
                        y_column=requested_y_column,
                        requested_x_column=requested_x_column,
                        requested_y_column=requested_y_column,
                        column_binding_mode=column_binding_mode,
                        method=dialog.method(),
                        method_label=methods.get(dialog.method(), dialog.method()),
                        initial_value=initial_value,
                        result_column=str(plan_row["target_column"]),
                        values_written=0,
                        status="failed",
                        error=str(exc),
                        requested_target_column=str(plan_row["requested_target_column"]),
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
                        x_column=requested_x_column,
                        y_column=requested_y_column,
                        requested_x_column=requested_x_column,
                        requested_y_column=requested_y_column,
                        column_binding_mode=column_binding_mode,
                        method=dialog.method(),
                        method_label=methods.get(dialog.method(), dialog.method()),
                        initial_value=initial_value,
                        result_column=str(plan_row["target_column"]),
                        values_written=0,
                        status="failed",
                        error=str(exc),
                        requested_target_column=str(plan_row["requested_target_column"]),
                        output_action=str(plan_row["output_action"]),
                        target_existed_before=bool(plan_row["target_existed_before"]),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            completed_jobs += 1

        if progress is not None:
            progress.setValue(completed_jobs)
        if canceled:
            for plan_row in target_plan[completed_jobs:]:
                results.append(
                    self._column_math_batch_summary_row(
                        dataset_name=str(plan_row["source_sheet"]),
                        operation_title=operation_title,
                        x_column=requested_x_column,
                        y_column=str(plan_row["requested_y_column"]),
                        requested_x_column=requested_x_column,
                        requested_y_column=str(plan_row["requested_y_column"]),
                        column_binding_mode=column_binding_mode,
                        method=dialog.method(),
                        method_label=methods.get(dialog.method(), dialog.method()),
                        initial_value=initial_value,
                        result_column=str(plan_row["target_column"]),
                        values_written=0,
                        status="canceled",
                        error="Canceled by user before this job was processed.",
                        requested_target_column=str(plan_row["requested_target_column"]),
                        output_action=str(plan_row["output_action"]),
                        target_existed_before=bool(plan_row["target_existed_before"]),
                        elapsed_seconds=0.0,
                    )
                )

        success_count = sum(1 for row in results if row["status"] == "ok")
        failure_rows = [row for row in results if row["status"] != "ok"]
        summary_dataset = None
        if len(results) > 1:
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
                x_column=requested_x_column,
                source_column=requested_y_columns[0],
                result_column=current_result_target,
                title=operation_title,
            )
            self._tabs.setCurrentWidget(self._plot_tab_widget)

        if failure_rows:
            detail = "\n".join(f"{row['source_sheet']}: {row['error']}" for row in failure_rows[:8])
            QMessageBox.warning(
                self,
                f"{operation_title} Batch",
                f"Applied {operation_title.lower()} to {success_count} result(s); "
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
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
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
                column_binding_mode=column_binding_mode,
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
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
    ) -> str:
        """Return a provenance comment for derivative/integral output columns."""
        comment = (
            f"{operation_title}: y={y_column}, x={x_column}, "
            f"method={method_label or method}, "
            f"binding={MainWindow._batch_column_binding_label(column_binding_mode)}"
        )
        if initial_value is not None:
            comment = f"{comment}, initial={initial_value:g}"
        return comment

    def _column_math_batch_preview_rows(
        self,
        target_plan: list[dict[str, object]],
        preflight_results: list[dict[str, object]],
        column_binding_mode: str,
    ) -> list[dict[str, object]]:
        """Return preview rows for derivative/integral batch jobs."""
        rows: list[dict[str, object]] = []
        for row in preflight_results:
            rows.append(
                {
                    "source_sheet": row.get("source_sheet", ""),
                    "status": "failed",
                    "x_column": row.get("requested_x_column", row.get("x_column", "")),
                    "y_column": row.get("requested_y_column", row.get("y_column", "")),
                    "target_column": row.get("requested_target_column", ""),
                    "output_action": row.get("output_action", "input_error"),
                    "column_binding": row.get("column_binding", self._batch_column_binding_label(column_binding_mode)),
                    "error": row.get("error", ""),
                }
            )
        for row in target_plan:
            output_action = str(row["output_action"])
            status = "blocked" if output_action == "blocked" else "ready"
            rows.append(
                {
                    "source_sheet": row["source_sheet"],
                    "status": status,
                    "x_column": row.get("requested_x_column", ""),
                    "y_column": row.get("y_column", row.get("requested_y_column", "")),
                    "target_column": row.get("target_column", ""),
                    "output_action": output_action,
                    "column_binding": self._batch_column_binding_label(column_binding_mode),
                    "error": "Target exists and the selected policy is Stop." if status == "blocked" else "",
                }
            )
        return rows

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
        requested_x_column: str = "",
        requested_y_column: str = "",
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
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
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_x_column": requested_x_column or x_column,
            "requested_y_column": requested_y_column or y_column,
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
                f"{operation_title} applied to {success_count} result(s), "
                f"{failure_count} failed; summary saved as '{summary_dataset_name}'"
            )
        if failure_count:
            return f"{operation_title} applied to {success_count} result(s), {failure_count} failed"
        return f"{operation_title} saved for {success_count} result(s)"

    def _run_interpolation(self) -> None:
        """Run the interpolation workflow and create a prediction dataset."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "Interpolation", "Select a dataset before interpolating.")
            return

        default_x = self._preferred_dataset_column(dataset, ("x",), fallback_index=0)
        default_y = self._preferred_dataset_column(dataset, ("y",), fallback_index=1)
        dialog = InterpolationDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_dataset_name=dataset.name,
            column_ranges=self._numeric_column_ranges(dataset),
            default_x_column=default_x,
            default_y_column=default_y,
            dataset_names=[
                candidate.name
                for candidate in self._workspace.list_datasets()
                if len(candidate.frame.columns) > 0
            ],
            current_dataset_name=dataset.name,
            parent=self,
        )
        if dialog.exec() != InterpolationDialog.Accepted:
            return

        self._run_interpolation_batch(dataset, dialog)

    def _run_interpolation_batch(self, current_dataset: Dataset, dialog: InterpolationDialog) -> None:
        """Run interpolation on one or more worksheets and create prediction sheets."""
        target_dataset_names = dialog.target_dataset_names()
        column_binding_mode = dialog.column_binding_mode()
        requested_coordinate_columns = dialog.coordinate_columns()
        requested_value_columns = dialog.value_columns()
        multiple_value_columns = len(requested_value_columns) > 1
        requested_query_columns = dialog.query_columns() if dialog.query_mode() == "columns" else []
        result_datasets: list[Dataset] = []
        current_result_dataset: Dataset | None = None
        results: list[dict[str, object]] = []

        try:
            shared_query_points = self._shared_interpolation_query_points(dialog)
        except MathOperationError as exc:
            QMessageBox.warning(self, "Interpolation Failed", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Interpolation Failed", str(exc))
            return

        preview_rows = self._interpolation_batch_preview_rows(
            current_dataset=current_dataset,
            dialog=dialog,
            target_dataset_names=target_dataset_names,
            requested_coordinate_columns=requested_coordinate_columns,
            requested_value_columns=requested_value_columns,
            requested_query_columns=requested_query_columns,
            multiple_value_columns=multiple_value_columns,
            column_binding_mode=column_binding_mode,
        )
        if (len(preview_rows) > 1 or any(row["status"] == "failed" for row in preview_rows)) and not (
            self._show_batch_preview(
                "Interpolation Batch Preview",
                preview_rows,
                [
                    ("Sheet", "source_sheet"),
                    ("Status", "status"),
                    ("Coordinates", "coordinate_columns"),
                    ("Value", "value_column"),
                    ("Query", "query_columns"),
                    ("Result Sheet", "result_sheet"),
                    ("Binding", "column_binding"),
                    ("Details", "error"),
                ],
            )
        ):
            return

        total_jobs = len(target_dataset_names) * len(requested_value_columns)
        progress = self._batch_progress_dialog("Interpolation Batch", total_jobs)
        completed_jobs = 0

        for source_name in target_dataset_names:
            try:
                source_dataset = self._workspace.get_dataset(source_name)
                coordinate_columns = self._resolve_batch_columns(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_columns=requested_coordinate_columns,
                    binding_mode=column_binding_mode,
                    field_label="Coordinate",
                )
                query_columns = (
                    self._resolve_batch_columns(
                        reference_dataset=current_dataset,
                        target_dataset=source_dataset,
                        source_columns=requested_query_columns,
                        binding_mode=column_binding_mode,
                        field_label="Query",
                    )
                    if dialog.query_mode() == "columns"
                    else []
                )
                query_points = (
                    query_points_from_columns(source_dataset.frame, query_columns)
                    if dialog.query_mode() == "columns"
                    else shared_query_points
                )
                if query_points is None:
                    raise MathOperationError("Query coordinates could not be prepared.")
            except MathOperationError as exc:
                for requested_value_column in requested_value_columns:
                    result_dataset_name = self._batch_result_dataset_name(
                        source_name=source_name,
                        requested_name=dialog.target_dataset_name(),
                        current_dataset_name=current_dataset.name,
                        default_suffix="interpolation",
                        source_column=requested_value_column,
                        multiple_columns=multiple_value_columns,
                    )
                    results.append(
                        self._interpolation_batch_summary_row(
                            source_sheet=source_name,
                            dialog=dialog,
                            requested_coordinate_columns=requested_coordinate_columns,
                            requested_value_column=requested_value_column,
                            requested_query_columns=requested_query_columns,
                            column_binding_mode=column_binding_mode,
                            requested_result_sheet=result_dataset_name,
                            output_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=0.0,
                        )
                    )
                completed_jobs += len(requested_value_columns)
                continue
            except Exception as exc:
                for requested_value_column in requested_value_columns:
                    result_dataset_name = self._batch_result_dataset_name(
                        source_name=source_name,
                        requested_name=dialog.target_dataset_name(),
                        current_dataset_name=current_dataset.name,
                        default_suffix="interpolation",
                        source_column=requested_value_column,
                        multiple_columns=multiple_value_columns,
                    )
                    results.append(
                        self._interpolation_batch_summary_row(
                            source_sheet=source_name,
                            dialog=dialog,
                            requested_coordinate_columns=requested_coordinate_columns,
                            requested_value_column=requested_value_column,
                            requested_query_columns=requested_query_columns,
                            column_binding_mode=column_binding_mode,
                            requested_result_sheet=result_dataset_name,
                            output_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=0.0,
                        )
                    )
                completed_jobs += len(requested_value_columns)
                continue

            for requested_value_column in requested_value_columns:
                if self._batch_progress_canceled(
                    progress,
                    completed_jobs,
                    f"Interpolation: {source_name} / {requested_value_column}",
                ):
                    result_dataset_name = self._batch_result_dataset_name(
                        source_name=source_name,
                        requested_name=dialog.target_dataset_name(),
                        current_dataset_name=current_dataset.name,
                        default_suffix="interpolation",
                        source_column=requested_value_column,
                        multiple_columns=multiple_value_columns,
                    )
                    results.append(
                        self._interpolation_batch_summary_row(
                            source_sheet=source_name,
                            dialog=dialog,
                            requested_coordinate_columns=requested_coordinate_columns,
                            requested_value_column=requested_value_column,
                            requested_query_columns=requested_query_columns,
                            column_binding_mode=column_binding_mode,
                            requested_result_sheet=result_dataset_name,
                            output_sheet="",
                            status="canceled",
                            error="Canceled by user before this job was processed.",
                            elapsed_seconds=0.0,
                        )
                    )
                    completed_jobs += 1
                    continue
                started = time.perf_counter()
                result_dataset_name = self._batch_result_dataset_name(
                    source_name=source_name,
                    requested_name=dialog.target_dataset_name(),
                    current_dataset_name=current_dataset.name,
                    default_suffix="interpolation",
                    source_column=requested_value_column,
                    multiple_columns=multiple_value_columns,
                )
                try:
                    value_column = self._resolve_batch_column(
                        reference_dataset=current_dataset,
                        target_dataset=source_dataset,
                        source_column=requested_value_column,
                        binding_mode=column_binding_mode,
                        field_label="Value",
                    )
                    if value_column is None:
                        raise MathOperationError("Choose a value column to interpolate.")

                    result_frame = interpolate_dataset(
                        source_dataset.frame,
                        coordinate_columns=coordinate_columns,
                        value_column=value_column,
                        query_points=query_points,
                        method=dialog.method_key(),
                        fill_policy=dialog.fill_policy(),
                        smoothing=dialog.smoothing(),
                        epsilon=dialog.epsilon(),
                    )
                    result_dataset = self._workspace.add_dataset(result_dataset_name, result_frame)
                    result_datasets.append(result_dataset)
                    if source_dataset.name == current_dataset.name and current_result_dataset is None:
                        current_result_dataset = result_dataset
                    self._apply_interpolation_metadata(
                        source_dataset=source_dataset,
                        result_dataset=result_dataset,
                        coordinate_columns=coordinate_columns,
                        value_column=value_column,
                    )
                    set_dataset_operation_comments(
                        result_dataset,
                        self._interpolation_operation_comment(
                            dialog=dialog,
                            coordinate_columns=coordinate_columns,
                            value_column=value_column,
                            column_binding_mode=column_binding_mode,
                        ),
                        (self._interpolation_prediction_column(value_column),),
                    )
                    results.append(
                        self._interpolation_batch_summary_row(
                            source_dataset=source_dataset,
                            dialog=dialog,
                            coordinate_columns=coordinate_columns,
                            value_column=value_column,
                            query_columns=query_columns,
                            requested_coordinate_columns=requested_coordinate_columns,
                            requested_value_column=requested_value_column,
                            requested_query_columns=requested_query_columns,
                            column_binding_mode=column_binding_mode,
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
                        self._interpolation_batch_summary_row(
                            source_sheet=source_name,
                            dialog=dialog,
                            requested_coordinate_columns=requested_coordinate_columns,
                            requested_value_column=requested_value_column,
                            requested_query_columns=requested_query_columns,
                            column_binding_mode=column_binding_mode,
                            requested_result_sheet=result_dataset_name,
                            output_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                except Exception as exc:
                    results.append(
                        self._interpolation_batch_summary_row(
                            source_sheet=source_name,
                            dialog=dialog,
                            requested_coordinate_columns=requested_coordinate_columns,
                            requested_value_column=requested_value_column,
                            requested_query_columns=requested_query_columns,
                            column_binding_mode=column_binding_mode,
                            requested_result_sheet=result_dataset_name,
                            output_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                completed_jobs += 1

        if progress is not None:
            progress.setValue(completed_jobs)

        summary_dataset = self._add_interpolation_batch_summary_dataset(
            current_dataset=current_dataset,
            target_dataset_names=target_dataset_names,
            results=results,
        )
        self._finish_interpolation_batch(
            result_datasets=result_datasets,
            current_result_dataset=current_result_dataset,
            summary_dataset=summary_dataset,
            results=results,
        )

    def _interpolation_batch_preview_rows(
        self,
        current_dataset: Dataset,
        dialog: InterpolationDialog,
        target_dataset_names: list[str],
        requested_coordinate_columns: list[str],
        requested_value_columns: list[str],
        requested_query_columns: list[str],
        multiple_value_columns: bool,
        column_binding_mode: str,
    ) -> list[dict[str, object]]:
        """Return preflight preview rows for interpolation jobs."""
        rows: list[dict[str, object]] = []
        for source_name in target_dataset_names:
            coordinate_columns: list[str] = []
            query_columns: list[str] = []
            source_error = ""
            try:
                source_dataset = self._workspace.get_dataset(source_name)
                coordinate_columns = self._resolve_batch_columns(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_columns=requested_coordinate_columns,
                    binding_mode=column_binding_mode,
                    field_label="Coordinate",
                )
                query_columns = (
                    self._resolve_batch_columns(
                        reference_dataset=current_dataset,
                        target_dataset=source_dataset,
                        source_columns=requested_query_columns,
                        binding_mode=column_binding_mode,
                        field_label="Query",
                    )
                    if dialog.query_mode() == "columns"
                    else []
                )
                if dialog.query_mode() == "columns":
                    query_points_from_columns(source_dataset.frame, query_columns)
            except Exception as exc:
                source_error = str(exc)

            for requested_value_column in requested_value_columns:
                result_dataset_name = self._batch_result_dataset_name(
                    source_name=source_name,
                    requested_name=dialog.target_dataset_name(),
                    current_dataset_name=current_dataset.name,
                    default_suffix="interpolation",
                    source_column=requested_value_column,
                    multiple_columns=multiple_value_columns,
                )
                value_column = requested_value_column
                status = "ready"
                error = source_error
                try:
                    if source_error:
                        raise MathOperationError(source_error)
                    source_dataset = self._workspace.get_dataset(source_name)
                    resolved_value = self._resolve_batch_column(
                        reference_dataset=current_dataset,
                        target_dataset=source_dataset,
                        source_column=requested_value_column,
                        binding_mode=column_binding_mode,
                        field_label="Value",
                    )
                    value_column = resolved_value or ""
                    if not value_column:
                        raise MathOperationError("Choose a value column to interpolate.")
                except Exception as exc:
                    status = "failed"
                    error = str(exc)
                rows.append(
                    {
                        "source_sheet": source_name,
                        "status": status,
                        "coordinate_columns": ", ".join(coordinate_columns or requested_coordinate_columns),
                        "value_column": value_column,
                        "query_columns": ", ".join(query_columns or requested_query_columns),
                        "result_sheet": result_dataset_name,
                        "column_binding": self._batch_column_binding_label(column_binding_mode),
                        "error": error,
                    }
                )
        return rows

    @staticmethod
    def _shared_interpolation_query_points(dialog: InterpolationDialog) -> np.ndarray | None:
        """Return shared query points for generated/manual interpolation batches."""
        if dialog.query_mode() == "generated":
            return generated_query_points(
                dialog.generated_ranges(),
                mesh=dialog.mode() == "2d",
            )
        if dialog.query_mode() == "manual":
            return query_points_from_text(
                dialog.manual_points_text(),
                dimension=len(dialog.coordinate_columns()),
            )
        return None

    @staticmethod
    def _interpolation_prediction_column(value_column: str) -> str:
        """Return the generated interpolation prediction column name."""
        return f"{value_column}_interpolated"

    def _interpolation_operation_comment(
        self,
        dialog: InterpolationDialog,
        coordinate_columns: list[str],
        value_column: str,
        column_binding_mode: str,
    ) -> str:
        """Return a compact provenance comment for interpolation result sheets."""
        return (
            f"Interpolation: value={value_column}, "
            f"coordinates={', '.join(coordinate_columns)}, "
            f"method={dialog.method_key()}, query={dialog.query_mode()}, "
            f"outside={dialog.fill_policy()}, "
            f"binding={self._batch_column_binding_label(column_binding_mode)}"
        )

    def _interpolation_batch_summary_row(
        self,
        dialog: InterpolationDialog,
        requested_result_sheet: str,
        output_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        coordinate_columns: list[str] | None = None,
        value_column: str = "",
        query_columns: list[str] | None = None,
        requested_coordinate_columns: list[str] | None = None,
        requested_value_column: str = "",
        requested_query_columns: list[str] | None = None,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        result_frame: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        """Return one interpolation batch summary row."""
        resolved_value_column = value_column or requested_value_column or dialog.value_column()
        resolved_coordinate_columns = coordinate_columns or dialog.coordinate_columns()
        resolved_query_columns = query_columns or []
        requested_coordinates = requested_coordinate_columns or resolved_coordinate_columns
        requested_queries = requested_query_columns or resolved_query_columns
        prediction_column = self._interpolation_prediction_column(resolved_value_column)
        metrics = self._interpolation_result_metrics(
            source_dataset=source_dataset,
            result_frame=result_frame,
            prediction_column=prediction_column,
        )
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": "Interpolation",
            "mode": dialog.mode(),
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_coordinate_columns": ", ".join(requested_coordinates),
            "coordinate_columns": ", ".join(resolved_coordinate_columns),
            "requested_value_column": requested_value_column or resolved_value_column,
            "value_column": resolved_value_column,
            "query_mode": dialog.query_mode(),
            "requested_query_columns": (
                ", ".join(requested_queries) if dialog.query_mode() == "columns" else ""
            ),
            "query_columns": (
                ", ".join(resolved_query_columns) if dialog.query_mode() == "columns" else ""
            ),
            "method": dialog.method_key(),
            "method_label": self._interpolation_method_label(dialog.mode(), dialog.method_key()),
            "fill_policy": dialog.fill_policy(),
            "smoothing": dialog.smoothing(),
            "epsilon": np.nan if dialog.epsilon() is None else dialog.epsilon(),
            "requested_result_sheet": requested_result_sheet,
            "output_sheet": output_sheet,
            "prediction_column": prediction_column,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
        }
        row.update(metrics)
        return row

    @staticmethod
    def _interpolation_method_label(mode: str, method_key: str) -> str:
        """Return a display label for an interpolation method."""
        method = INTERPOLATION_METHODS.get(mode, {}).get(method_key)
        return method.label if method is not None else method_key

    @staticmethod
    def _interpolation_result_metrics(
        source_dataset: Dataset | None,
        result_frame: pd.DataFrame | None,
        prediction_column: str,
    ) -> dict[str, object]:
        """Return quality metrics for one interpolation result."""
        metrics: dict[str, object] = {
            "source_row_count": len(source_dataset.frame) if source_dataset is not None else 0,
            "query_count": len(result_frame) if result_frame is not None else 0,
            "finite_prediction_count": np.nan,
            "missing_prediction_count": np.nan,
            "prediction_minimum": np.nan,
            "prediction_maximum": np.nan,
            "prediction_mean": np.nan,
        }
        if result_frame is None or prediction_column not in result_frame.columns:
            return metrics

        predictions = pd.to_numeric(result_frame[prediction_column], errors="coerce")
        predictions = predictions.replace([np.inf, -np.inf], np.nan)
        finite_predictions = predictions.dropna()
        metrics["finite_prediction_count"] = int(len(finite_predictions))
        metrics["missing_prediction_count"] = int(len(predictions) - len(finite_predictions))
        if not finite_predictions.empty:
            metrics["prediction_minimum"] = float(finite_predictions.min())
            metrics["prediction_maximum"] = float(finite_predictions.max())
            metrics["prediction_mean"] = float(finite_predictions.mean())
        return metrics

    def _add_interpolation_batch_summary_dataset(
        self,
        current_dataset: Dataset,
        target_dataset_names: list[str],
        results: list[dict[str, object]],
    ) -> Dataset | None:
        """Create a cumulative interpolation batch summary when needed."""
        if len(results) <= 1:
            return None
        return self._workspace.add_dataset(
            f"{current_dataset.name}_interpolation_batch_summary",
            pd.DataFrame(results),
        )

    def _finish_interpolation_batch(
        self,
        result_datasets: list[Dataset],
        current_result_dataset: Dataset | None,
        summary_dataset: Dataset | None,
        results: list[dict[str, object]],
    ) -> None:
        """Refresh UI and report interpolation batch status."""
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
                "Interpolation Failed",
                message or "Interpolation failed on every selected sheet.",
            )
            return

        if failure_rows:
            detail = "\n".join(f"{row['source_sheet']}: {row['error']}" for row in failure_rows[:8])
            QMessageBox.warning(
                self,
                "Interpolation Batch",
                f"Created {success_count} prediction sheet(s); {len(failure_rows)} failed.\n\n{detail}",
            )
        self.statusBar().showMessage(
            self._interpolation_batch_status_message(
                success_count=success_count,
                failure_count=len(failure_rows),
                summary_dataset_name=summary_dataset.name if summary_dataset else "",
            )
        )

    @staticmethod
    def _interpolation_batch_status_message(
        success_count: int,
        failure_count: int,
        summary_dataset_name: str,
    ) -> str:
        """Return a concise interpolation batch status message."""
        suffixes: list[str] = []
        if summary_dataset_name:
            suffixes.append(f"summary saved as '{summary_dataset_name}'")
        suffix = "; " + "; ".join(suffixes) if suffixes else ""
        if failure_count:
            return f"Interpolation created {success_count} prediction sheet(s), {failure_count} failed{suffix}"
        return f"Interpolation created {success_count} prediction sheet(s){suffix}"

    def _run_fft(self) -> None:
        """Run the FFT workflow and create a frequency-domain dataset."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "FFT", "Select a dataset before running FFT.")
            return

        dialog = FFTDialog(
            column_names=[str(column) for column in dataset.frame.columns],
            default_dataset_name=dataset.name,
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
        column_binding_mode = dialog.column_binding_mode()
        requested_signal_columns = dialog.signal_columns()
        requested_x_column = dialog.x_column()
        multiple_signal_columns = len(requested_signal_columns) > 1
        result_datasets: list[Dataset] = []
        current_result_dataset: Dataset | None = None
        results: list[dict[str, object]] = []
        jobs = [
            (source_name, requested_signal_column)
            for source_name in target_dataset_names
            for requested_signal_column in requested_signal_columns
        ]
        preview_rows = self._fft_batch_preview_rows(
            current_dataset=current_dataset,
            jobs=jobs,
            requested_x_column=requested_x_column,
            requested_result_sheet=dialog.target_dataset_name(),
            multiple_signal_columns=multiple_signal_columns,
            column_binding_mode=column_binding_mode,
        )
        if (len(preview_rows) > 1 or any(row["status"] == "failed" for row in preview_rows)) and not (
            self._show_batch_preview(
                "FFT Batch Preview",
                preview_rows,
                [
                    ("Sheet", "source_sheet"),
                    ("Status", "status"),
                    ("Signal", "signal_column"),
                    ("X/time", "x_column"),
                    ("Result Sheet", "result_sheet"),
                    ("Binding", "column_binding"),
                    ("Details", "error"),
                ],
            )
        ):
            return

        progress = self._batch_progress_dialog("FFT Batch", len(jobs))
        completed_jobs = 0
        canceled = False
        for source_name, requested_signal_column in jobs:
            if self._batch_progress_canceled(
                progress,
                completed_jobs,
                f"FFT: {source_name} / {requested_signal_column}",
            ):
                canceled = True
                break
            started = time.perf_counter()
            result_dataset_name = self._batch_result_dataset_name(
                source_name=source_name,
                requested_name=dialog.target_dataset_name(),
                current_dataset_name=current_dataset.name,
                default_suffix="FFT",
                source_column=requested_signal_column,
                multiple_columns=multiple_signal_columns,
            )
            try:
                source_dataset = self._workspace.get_dataset(source_name)
                signal_column = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_signal_column,
                    binding_mode=column_binding_mode,
                    field_label="Signal",
                )
                x_column = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_x_column,
                    binding_mode=column_binding_mode,
                    field_label="X/time",
                )
                if signal_column is None:
                    raise MathOperationError("Choose a signal column.")
                result_frame = fft_dataset(
                    source_dataset.frame,
                    signal_column=signal_column,
                    x_column=x_column,
                    window_method=dialog.window_method(),
                )
                result_dataset = self._workspace.add_dataset(result_dataset_name, result_frame)
                result_datasets.append(result_dataset)
                if source_dataset.name == current_dataset.name and current_result_dataset is None:
                    current_result_dataset = result_dataset
                set_dataset_operation_comments(
                    result_dataset,
                    self._fft_operation_comment(
                        signal_column=signal_column,
                        x_column=x_column,
                        window_method=dialog.window_method(),
                        column_binding_mode=column_binding_mode,
                    ),
                )
                results.append(
                    self._fft_batch_summary_row(
                        source_dataset=source_dataset,
                        operation="FFT",
                        signal_column=signal_column,
                        x_column=x_column,
                        requested_signal_column=requested_signal_column,
                        requested_x_column=requested_x_column,
                        column_binding_mode=column_binding_mode,
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
                        signal_column=requested_signal_column,
                        x_column=requested_x_column,
                        requested_signal_column=requested_signal_column,
                        requested_x_column=requested_x_column,
                        column_binding_mode=column_binding_mode,
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
                        signal_column=requested_signal_column,
                        x_column=requested_x_column,
                        requested_signal_column=requested_signal_column,
                        requested_x_column=requested_x_column,
                        column_binding_mode=column_binding_mode,
                        window_method=dialog.window_method(),
                        requested_result_sheet=result_dataset_name,
                        output_sheet="",
                        status="failed",
                        error=str(exc),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            completed_jobs += 1

        if progress is not None:
            progress.setValue(completed_jobs)
        if canceled:
            for source_name, requested_signal_column in jobs[completed_jobs:]:
                result_dataset_name = self._batch_result_dataset_name(
                    source_name=source_name,
                    requested_name=dialog.target_dataset_name(),
                    current_dataset_name=current_dataset.name,
                    default_suffix="FFT",
                    source_column=requested_signal_column,
                    multiple_columns=multiple_signal_columns,
                )
                results.append(
                    self._fft_batch_summary_row(
                        source_sheet=source_name,
                        operation="FFT",
                        signal_column=requested_signal_column,
                        x_column=requested_x_column,
                        requested_signal_column=requested_signal_column,
                        requested_x_column=requested_x_column,
                        column_binding_mode=column_binding_mode,
                        window_method=dialog.window_method(),
                        requested_result_sheet=result_dataset_name,
                        output_sheet="",
                        status="canceled",
                        error="Canceled by user before this job was processed.",
                        elapsed_seconds=0.0,
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
        column_binding_mode = dialog.column_binding_mode()
        requested_real_columns = dialog.real_columns()
        requested_imaginary_columns = dialog.imaginary_columns()
        multiple_real_columns = len(requested_real_columns) > 1
        result_datasets: list[Dataset] = []
        current_result_dataset: Dataset | None = None
        results: list[dict[str, object]] = []
        jobs: list[tuple[str, int, str, str | None]] = []
        for source_name in target_dataset_names:
            for index, requested_real_column in enumerate(requested_real_columns):
                requested_imaginary_column = None
                if len(requested_imaginary_columns) == 1:
                    requested_imaginary_column = requested_imaginary_columns[0]
                elif requested_imaginary_columns:
                    requested_imaginary_column = requested_imaginary_columns[index]
                jobs.append((source_name, index, requested_real_column, requested_imaginary_column))
        preview_rows = self._ifft_batch_preview_rows(
            current_dataset=current_dataset,
            jobs=jobs,
            requested_result_sheet=dialog.target_dataset_name(),
            multiple_real_columns=multiple_real_columns,
            column_binding_mode=column_binding_mode,
        )
        if (len(preview_rows) > 1 or any(row["status"] == "failed" for row in preview_rows)) and not (
            self._show_batch_preview(
                "Inverse FFT Batch Preview",
                preview_rows,
                [
                    ("Sheet", "source_sheet"),
                    ("Status", "status"),
                    ("Real", "real_column"),
                    ("Imaginary", "imaginary_column"),
                    ("Result Sheet", "result_sheet"),
                    ("Binding", "column_binding"),
                    ("Details", "error"),
                ],
            )
        ):
            return

        progress = self._batch_progress_dialog("Inverse FFT Batch", len(jobs))
        completed_jobs = 0
        canceled = False
        for source_name, _index, requested_real_column, requested_imaginary_column in jobs:
            if self._batch_progress_canceled(
                progress,
                completed_jobs,
                f"Inverse FFT: {source_name} / {requested_real_column}",
            ):
                canceled = True
                break
            started = time.perf_counter()
            result_dataset_name = self._batch_result_dataset_name(
                source_name=source_name,
                requested_name=dialog.target_dataset_name(),
                current_dataset_name=current_dataset.name,
                default_suffix="iFFT",
                source_column=requested_real_column,
                multiple_columns=multiple_real_columns,
            )
            try:
                source_dataset = self._workspace.get_dataset(source_name)
                real_column = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_real_column,
                    binding_mode=column_binding_mode,
                    field_label="Real",
                )
                imaginary_column = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_imaginary_column,
                    binding_mode=column_binding_mode,
                    field_label="Imaginary",
                )
                if real_column is None:
                    raise MathOperationError("Choose a real spectrum column.")
                result_frame = ifft_dataset(
                    source_dataset.frame,
                    real_column=real_column,
                    imaginary_column=imaginary_column,
                )
                result_dataset = self._workspace.add_dataset(result_dataset_name, result_frame)
                result_datasets.append(result_dataset)
                if source_dataset.name == current_dataset.name and current_result_dataset is None:
                    current_result_dataset = result_dataset
                set_dataset_operation_comments(
                    result_dataset,
                    self._ifft_operation_comment(
                        real_column=real_column,
                        imaginary_column=imaginary_column,
                        column_binding_mode=column_binding_mode,
                    ),
                )
                results.append(
                    self._ifft_batch_summary_row(
                        source_dataset=source_dataset,
                        real_column=real_column,
                        imaginary_column=imaginary_column,
                        requested_real_column=requested_real_column,
                        requested_imaginary_column=requested_imaginary_column,
                        column_binding_mode=column_binding_mode,
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
                        real_column=requested_real_column,
                        imaginary_column=requested_imaginary_column,
                        requested_real_column=requested_real_column,
                        requested_imaginary_column=requested_imaginary_column,
                        column_binding_mode=column_binding_mode,
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
                        real_column=requested_real_column,
                        imaginary_column=requested_imaginary_column,
                        requested_real_column=requested_real_column,
                        requested_imaginary_column=requested_imaginary_column,
                        column_binding_mode=column_binding_mode,
                        requested_result_sheet=result_dataset_name,
                        output_sheet="",
                        status="failed",
                        error=str(exc),
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
            completed_jobs += 1

        if progress is not None:
            progress.setValue(completed_jobs)
        if canceled:
            for source_name, _index, requested_real_column, requested_imaginary_column in jobs[completed_jobs:]:
                result_dataset_name = self._batch_result_dataset_name(
                    source_name=source_name,
                    requested_name=dialog.target_dataset_name(),
                    current_dataset_name=current_dataset.name,
                    default_suffix="iFFT",
                    source_column=requested_real_column,
                    multiple_columns=multiple_real_columns,
                )
                results.append(
                    self._ifft_batch_summary_row(
                        source_sheet=source_name,
                        real_column=requested_real_column,
                        imaginary_column=requested_imaginary_column,
                        requested_real_column=requested_real_column,
                        requested_imaginary_column=requested_imaginary_column,
                        column_binding_mode=column_binding_mode,
                        requested_result_sheet=result_dataset_name,
                        output_sheet="",
                        status="canceled",
                        error="Canceled by user before this job was processed.",
                        elapsed_seconds=0.0,
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

    def _fft_batch_preview_rows(
        self,
        current_dataset: Dataset,
        jobs: list[tuple[str, str]],
        requested_x_column: str | None,
        requested_result_sheet: str,
        multiple_signal_columns: bool,
        column_binding_mode: str,
    ) -> list[dict[str, object]]:
        """Return preview rows for FFT jobs."""
        rows: list[dict[str, object]] = []
        for source_name, requested_signal_column in jobs:
            result_dataset_name = self._batch_result_dataset_name(
                source_name=source_name,
                requested_name=requested_result_sheet,
                current_dataset_name=current_dataset.name,
                default_suffix="FFT",
                source_column=requested_signal_column,
                multiple_columns=multiple_signal_columns,
            )
            status = "ready"
            error = ""
            signal_column = requested_signal_column
            x_column = requested_x_column or "sample index"
            try:
                source_dataset = self._workspace.get_dataset(source_name)
                resolved_signal = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_signal_column,
                    binding_mode=column_binding_mode,
                    field_label="Signal",
                )
                resolved_x = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_x_column,
                    binding_mode=column_binding_mode,
                    field_label="X/time",
                )
                signal_column = resolved_signal or ""
                x_column = resolved_x or "sample index"
                if not signal_column:
                    raise MathOperationError("Choose a signal column.")
            except Exception as exc:
                status = "failed"
                error = str(exc)
            rows.append(
                {
                    "source_sheet": source_name,
                    "status": status,
                    "signal_column": signal_column,
                    "x_column": x_column,
                    "result_sheet": result_dataset_name,
                    "column_binding": self._batch_column_binding_label(column_binding_mode),
                    "error": error,
                }
            )
        return rows

    def _ifft_batch_preview_rows(
        self,
        current_dataset: Dataset,
        jobs: list[tuple[str, int, str, str | None]],
        requested_result_sheet: str,
        multiple_real_columns: bool,
        column_binding_mode: str,
    ) -> list[dict[str, object]]:
        """Return preview rows for inverse FFT jobs."""
        rows: list[dict[str, object]] = []
        for source_name, _index, requested_real_column, requested_imaginary_column in jobs:
            result_dataset_name = self._batch_result_dataset_name(
                source_name=source_name,
                requested_name=requested_result_sheet,
                current_dataset_name=current_dataset.name,
                default_suffix="iFFT",
                source_column=requested_real_column,
                multiple_columns=multiple_real_columns,
            )
            status = "ready"
            error = ""
            real_column = requested_real_column
            imaginary_column = requested_imaginary_column or "0"
            try:
                source_dataset = self._workspace.get_dataset(source_name)
                resolved_real = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_real_column,
                    binding_mode=column_binding_mode,
                    field_label="Real",
                )
                resolved_imaginary = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_imaginary_column,
                    binding_mode=column_binding_mode,
                    field_label="Imaginary",
                )
                real_column = resolved_real or ""
                imaginary_column = resolved_imaginary or "0"
                if not real_column:
                    raise MathOperationError("Choose a real spectrum column.")
            except Exception as exc:
                status = "failed"
                error = str(exc)
            rows.append(
                {
                    "source_sheet": source_name,
                    "status": status,
                    "real_column": real_column,
                    "imaginary_column": imaginary_column,
                    "result_sheet": result_dataset_name,
                    "column_binding": self._batch_column_binding_label(column_binding_mode),
                    "error": error,
                }
            )
        return rows

    def _add_signal_batch_summary_dataset(
        self,
        current_dataset: Dataset,
        operation_key: str,
        target_dataset_names: list[str],
        results: list[dict[str, object]],
    ) -> Dataset | None:
        """Create a cumulative FFT/iFFT batch summary when multiple result rows exist."""
        if len(results) <= 1:
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
        source_column: str = "",
        multiple_columns: bool = False,
    ) -> str:
        """Return a per-source result-sheet name for batch-created datasets."""
        clean_requested = requested_name.strip()
        default_current_name = f"{current_dataset_name}_{default_suffix}"
        column_name = str(source_column).strip()
        append_column = bool(multiple_columns and column_name and "{column}" not in clean_requested)

        def with_column(name: str) -> str:
            """Apply column placeholder or suffix rules to one dataset name."""
            if "{column}" in name:
                return name.replace("{column}", column_name)
            if append_column:
                return f"{name}_{column_name}"
            return name

        if not clean_requested:
            return with_column(f"{source_name}_{default_suffix}")
        if "{source}" in clean_requested:
            return with_column(clean_requested.replace("{source}", source_name))
        if source_name == current_dataset_name:
            return with_column(clean_requested)
        if clean_requested == default_current_name:
            return with_column(f"{source_name}_{default_suffix}")
        return with_column(f"{source_name}_{clean_requested}")

    @staticmethod
    def _fft_operation_comment(
        signal_column: str,
        x_column: str | None,
        window_method: str,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
    ) -> str:
        """Return a compact provenance comment for FFT result sheets."""
        return (
            f"FFT: signal={signal_column}, x={x_column or 'sample index'}, "
            f"window={window_method}, "
            f"binding={MainWindow._batch_column_binding_label(column_binding_mode)}"
        )

    @staticmethod
    def _ifft_operation_comment(
        real_column: str,
        imaginary_column: str | None,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
    ) -> str:
        """Return a compact provenance comment for inverse FFT result sheets."""
        return (
            f"Inverse FFT: real={real_column}, imaginary={imaginary_column or '0'}, "
            f"binding={MainWindow._batch_column_binding_label(column_binding_mode)}"
        )

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
        requested_signal_column: str = "",
        requested_x_column: str | None = None,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        result_frame: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        """Return one FFT batch summary row."""
        metrics = self._fft_result_metrics(source_dataset, result_frame, signal_column, x_column)
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": operation,
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_signal_column": requested_signal_column or signal_column,
            "signal_column": signal_column,
            "requested_x_column": requested_x_column or "sample index",
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
        requested_real_column: str = "",
        requested_imaginary_column: str | None = None,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        result_frame: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        """Return one inverse FFT batch summary row."""
        metrics = self._ifft_result_metrics(source_dataset, result_frame)
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": "Inverse FFT",
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_real_column": requested_real_column or real_column,
            "real_column": real_column,
            "requested_imaginary_column": requested_imaginary_column or "0",
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

        self._run_statistics_batch(dialog)

    def _run_statistics_batch(self, dialog: StatisticsDialog) -> None:
        """Run statistics once or as an expanded worksheet/column batch."""
        try:
            primary_reference = self._workspace.get_dataset(dialog.primary_dataset_name())
            secondary_reference = (
                self._workspace.get_dataset(dialog.secondary_dataset_name())
                if dialog.requires_secondary_column()
                else None
            )
        except KeyError as exc:
            QMessageBox.warning(self, "Statistics Failed", f"Selected data is no longer available: {exc}")
            return

        operation_key = dialog.operation_key()
        operation = STATISTIC_OPERATIONS[operation_key]
        operation_scope = operation.scope
        target_dataset_names = dialog.target_dataset_names()
        column_binding_mode = dialog.column_binding_mode()
        requested_primary_columns = dialog.primary_columns()
        requested_secondary_columns = dialog.secondary_columns()
        requested_multi_columns = dialog.multi_columns()
        expected_job_count = (
            len(target_dataset_names)
            if operation_scope == "multi"
            else len(target_dataset_names) * len(requested_primary_columns)
        )
        multiple_primary_jobs = expected_job_count > len(target_dataset_names)
        preview_rows = self._statistics_batch_preview_rows(
            primary_reference=primary_reference,
            secondary_reference=secondary_reference,
            target_dataset_names=target_dataset_names,
            operation_scope=operation_scope,
            requested_primary_columns=requested_primary_columns,
            requested_secondary_columns=requested_secondary_columns,
            requested_multi_columns=requested_multi_columns,
            requested_result_sheet=dialog.target_dataset_name(),
            column_binding_mode=column_binding_mode,
            multiple_primary_jobs=multiple_primary_jobs,
        )
        if (len(preview_rows) > 1 or any(row["status"] == "failed" for row in preview_rows)) and not (
            self._show_batch_preview(
                "Statistics Batch Preview",
                preview_rows,
                [
                    ("Sheet", "source_sheet"),
                    ("Status", "status"),
                    ("Primary", "primary_column"),
                    ("Secondary/Group", "secondary_column"),
                    ("Columns", "columns"),
                    ("Result Sheet", "result_sheet"),
                    ("Binding", "column_binding"),
                    ("Details", "error"),
                ],
            )
        ):
            return

        result_datasets: list[Dataset] = []
        summary_rows: list[dict[str, object]] = []
        plot_created = False
        progress = self._batch_progress_dialog("Statistics Batch", expected_job_count)
        completed_jobs = 0

        for source_name in target_dataset_names:
            try:
                source_dataset = self._workspace.get_dataset(source_name)
            except KeyError as exc:
                summary_rows.extend(
                    self._statistics_batch_result_rows(
                        operation_key=operation_key,
                        operation_scope=operation_scope,
                        column_binding_mode=column_binding_mode,
                        source_sheet=source_name,
                        secondary_sheet="",
                        requested_result_sheet="",
                        output_sheet="",
                        status="failed",
                        error=f"Selected data is no longer available: {exc}",
                        elapsed_seconds=0.0,
                    )
                )
                continue

            if operation_scope == "multi":
                started = time.perf_counter()
                requested_result_sheet = self._batch_result_dataset_name(
                    source_name=source_dataset.name,
                    requested_name=dialog.target_dataset_name(),
                    current_dataset_name=primary_reference.name,
                    default_suffix="statistics",
                )
                if self._batch_progress_canceled(
                    progress,
                    completed_jobs,
                    f"Statistics: {source_dataset.name}",
                ):
                    summary_rows.extend(
                        self._statistics_batch_result_rows(
                            operation_key=operation_key,
                            operation_scope=operation_scope,
                            column_binding_mode=column_binding_mode,
                            source_sheet=source_dataset.name,
                            secondary_sheet="",
                            requested_columns=requested_multi_columns,
                            requested_result_sheet=requested_result_sheet,
                            output_sheet="",
                            status="canceled",
                            error="Canceled by user before this job was processed.",
                            elapsed_seconds=0.0,
                        )
                    )
                    completed_jobs += 1
                    continue
                try:
                    multi_columns = self._resolve_batch_columns(
                        reference_dataset=primary_reference,
                        target_dataset=source_dataset,
                        source_columns=requested_multi_columns,
                        binding_mode=column_binding_mode,
                        field_label="Statistics column",
                    )
                    if len(multi_columns) < 2:
                        raise MathOperationError("Choose at least two columns for a multiple-column operation.")
                    column_labels = {
                        column: self._statistics_column_label(source_dataset, column)
                        for column in multi_columns
                    }
                    source_dataset.sync_column_metadata_attrs()
                    multi_frame = source_dataset.frame[multi_columns].copy()
                    multi_frame.attrs.update(source_dataset.frame.attrs)
                    result_frame = run_multicolumn_statistical_analysis(
                        frame=multi_frame,
                        column_labels=column_labels,
                        operation_key=operation_key,
                    )
                    result_dataset = self._workspace.add_dataset(requested_result_sheet, result_frame)
                    result_datasets.append(result_dataset)
                    set_dataset_operation_comments(
                        result_dataset,
                        self._statistics_operation_comment(
                            operation_key=operation_key,
                            primary_dataset=source_dataset,
                            primary_column="",
                            secondary_dataset=None,
                            secondary_column="",
                            multi_columns=multi_columns,
                            column_binding_mode=column_binding_mode,
                        ),
                    )
                    summary_rows.extend(
                        self._statistics_batch_result_rows(
                            operation_key=operation_key,
                            operation_scope=operation_scope,
                            column_binding_mode=column_binding_mode,
                            source_sheet=source_dataset.name,
                            secondary_sheet="",
                            requested_columns=requested_multi_columns,
                            columns=multi_columns,
                            requested_result_sheet=requested_result_sheet,
                            output_sheet=result_dataset.name,
                            result_frame=result_frame,
                            status="ok",
                            error="",
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                    plot_created = self._queue_statistics_batch_plot(
                        dialog=dialog,
                        plot_created=plot_created,
                        primary_reference=primary_reference,
                        primary_dataset=source_dataset,
                        primary_column="",
                        secondary_dataset=None,
                        secondary_column="",
                        result_dataset=result_dataset,
                        multi_columns=multi_columns,
                    )
                except (KeyError, MathOperationError, ValueError) as exc:
                    summary_rows.extend(
                        self._statistics_batch_result_rows(
                            operation_key=operation_key,
                            operation_scope=operation_scope,
                            column_binding_mode=column_binding_mode,
                            source_sheet=source_dataset.name,
                            secondary_sheet="",
                            requested_columns=requested_multi_columns,
                            columns=[],
                            requested_result_sheet=requested_result_sheet,
                            output_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                except Exception as exc:
                    summary_rows.extend(
                        self._statistics_batch_result_rows(
                            operation_key=operation_key,
                            operation_scope=operation_scope,
                            column_binding_mode=column_binding_mode,
                            source_sheet=source_dataset.name,
                            secondary_sheet="",
                            requested_columns=requested_multi_columns,
                            columns=[],
                            requested_result_sheet=requested_result_sheet,
                            output_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                completed_jobs += 1
                continue

            for primary_index, requested_primary_column in enumerate(requested_primary_columns):
                started = time.perf_counter()
                requested_secondary_column = ""
                if operation_scope in {"pair", "group"}:
                    requested_secondary_column = (
                        requested_secondary_columns[0]
                        if len(requested_secondary_columns) == 1
                        else requested_secondary_columns[primary_index]
                    )
                requested_result_sheet = self._batch_result_dataset_name(
                    source_name=source_dataset.name,
                    requested_name=dialog.target_dataset_name(),
                    current_dataset_name=primary_reference.name,
                    default_suffix="statistics",
                    source_column=requested_primary_column,
                    multiple_columns=multiple_primary_jobs,
                )
                secondary_dataset = None
                secondary_column = ""
                if self._batch_progress_canceled(
                    progress,
                    completed_jobs,
                    f"Statistics: {source_dataset.name} / {requested_primary_column}",
                ):
                    summary_rows.extend(
                        self._statistics_batch_result_rows(
                            operation_key=operation_key,
                            operation_scope=operation_scope,
                            column_binding_mode=column_binding_mode,
                            source_sheet=source_dataset.name,
                            secondary_sheet="",
                            requested_primary_column=requested_primary_column,
                            requested_secondary_column=requested_secondary_column,
                            requested_result_sheet=requested_result_sheet,
                            output_sheet="",
                            status="canceled",
                            error="Canceled by user before this job was processed.",
                            elapsed_seconds=0.0,
                        )
                    )
                    completed_jobs += 1
                    continue
                try:
                    primary_column = self._resolve_batch_column(
                        reference_dataset=primary_reference,
                        target_dataset=source_dataset,
                        source_column=requested_primary_column,
                        binding_mode=column_binding_mode,
                        field_label="Primary",
                    )
                    if primary_column is None:
                        raise MathOperationError("Choose a primary column.")
                    primary_values = pd.to_numeric(source_dataset.frame[primary_column], errors="coerce")
                    validate_numeric_column_metadata(source_dataset.frame, primary_column, primary_values)

                    secondary_series = None
                    secondary_label = ""
                    if secondary_reference is not None:
                        secondary_dataset = self._statistics_secondary_source_dataset(
                            primary_reference=primary_reference,
                            secondary_reference=secondary_reference,
                            source_dataset=source_dataset,
                            target_dataset_names=target_dataset_names,
                        )
                        secondary_column = self._resolve_batch_column(
                            reference_dataset=secondary_reference,
                            target_dataset=secondary_dataset,
                            source_column=requested_secondary_column,
                            binding_mode=column_binding_mode,
                            field_label="Secondary/group",
                        ) or ""
                        if not secondary_column:
                            raise MathOperationError("Choose a secondary or group column.")
                        secondary_series = secondary_dataset.frame[secondary_column]
                        secondary_label = f"{secondary_dataset.name}: {secondary_column}"
                        if operation_scope != "group":
                            secondary_values = pd.to_numeric(secondary_series, errors="coerce")
                            validate_numeric_column_metadata(
                                secondary_dataset.frame,
                                secondary_column,
                                secondary_values,
                            )

                    result_frame = run_statistical_analysis(
                        primary=source_dataset.frame[primary_column],
                        primary_label=f"{source_dataset.name}: {primary_column}",
                        operation_key=operation_key,
                        secondary=secondary_series,
                        secondary_label=secondary_label,
                    )
                    result_dataset = self._workspace.add_dataset(requested_result_sheet, result_frame)
                    result_datasets.append(result_dataset)
                    set_dataset_operation_comments(
                        result_dataset,
                        self._statistics_operation_comment(
                            operation_key=operation_key,
                            primary_dataset=source_dataset,
                            primary_column=primary_column,
                            secondary_dataset=secondary_dataset,
                            secondary_column=secondary_column,
                            multi_columns=[],
                            column_binding_mode=column_binding_mode,
                        ),
                    )
                    summary_rows.extend(
                        self._statistics_batch_result_rows(
                            operation_key=operation_key,
                            operation_scope=operation_scope,
                            column_binding_mode=column_binding_mode,
                            source_sheet=source_dataset.name,
                            secondary_sheet=secondary_dataset.name if secondary_dataset is not None else "",
                            requested_primary_column=requested_primary_column,
                            primary_column=primary_column,
                            requested_secondary_column=requested_secondary_column,
                            secondary_column=secondary_column,
                            requested_result_sheet=requested_result_sheet,
                            output_sheet=result_dataset.name,
                            result_frame=result_frame,
                            status="ok",
                            error="",
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                    plot_created = self._queue_statistics_batch_plot(
                        dialog=dialog,
                        plot_created=plot_created,
                        primary_reference=primary_reference,
                        primary_dataset=source_dataset,
                        primary_column=primary_column,
                        secondary_dataset=secondary_dataset,
                        secondary_column=secondary_column,
                        result_dataset=result_dataset,
                        multi_columns=[],
                    )
                except (KeyError, MathOperationError, ValueError) as exc:
                    summary_rows.extend(
                        self._statistics_batch_result_rows(
                            operation_key=operation_key,
                            operation_scope=operation_scope,
                            column_binding_mode=column_binding_mode,
                            source_sheet=source_dataset.name,
                            secondary_sheet=secondary_dataset.name if secondary_dataset is not None else "",
                            requested_primary_column=requested_primary_column,
                            primary_column="",
                            requested_secondary_column=requested_secondary_column,
                            secondary_column=secondary_column,
                            requested_result_sheet=requested_result_sheet,
                            output_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                except Exception as exc:
                    summary_rows.extend(
                        self._statistics_batch_result_rows(
                            operation_key=operation_key,
                            operation_scope=operation_scope,
                            column_binding_mode=column_binding_mode,
                            source_sheet=source_dataset.name,
                            secondary_sheet=secondary_dataset.name if secondary_dataset is not None else "",
                            requested_primary_column=requested_primary_column,
                            primary_column="",
                            requested_secondary_column=requested_secondary_column,
                            secondary_column=secondary_column,
                            requested_result_sheet=requested_result_sheet,
                            output_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                completed_jobs += 1

        if progress is not None:
            progress.setValue(completed_jobs)

        summary_dataset = None
        if expected_job_count > 1 or any(row.get("status") != "ok" for row in summary_rows):
            summary_dataset = self._workspace.add_dataset(
                f"{primary_reference.name}_statistics_batch_summary",
                pd.DataFrame(summary_rows),
            )
            set_dataset_operation_comments(
                summary_dataset,
                f"Statistics batch summary: operation={operation.label}",
            )
        wide_summary_dataset = self._statistics_batch_wide_summary_dataset(
            primary_reference=primary_reference,
            summary_rows=summary_rows,
        )

        success_count = len(result_datasets)
        failure_rows = [row for row in summary_rows if row.get("status") != "ok"]
        selected_name = (
            result_datasets[0].name
            if result_datasets
            else summary_dataset.name if summary_dataset is not None else ""
        )
        if selected_name:
            self._refresh_dataset_list(selected_name)
        else:
            self._update_dataset_summary()

        if success_count == 0:
            detail = "\n".join(
                f"{row.get('source_sheet', '')}: {row.get('error', '')}"
                for row in failure_rows[:8]
            )
            if summary_dataset is not None:
                detail = f"{detail}\n\nSummary saved as '{summary_dataset.name}'."
            QMessageBox.warning(
                self,
                "Statistics Failed",
                detail or "Statistics failed on every selected sheet/column.",
            )
            return

        if failure_rows:
            detail = "\n".join(
                f"{row.get('source_sheet', '')}: {row.get('error', '')}"
                for row in failure_rows[:8]
            )
            QMessageBox.warning(
                self,
                "Statistics Batch",
                f"Created {success_count} result sheet(s); {len(failure_rows)} job(s) failed.\n\n{detail}",
            )
        if summary_dataset is not None:
            wide_text = (
                f"; wide summary saved as '{wide_summary_dataset.name}'"
                if wide_summary_dataset is not None
                else ""
            )
            self.statusBar().showMessage(
                f"Statistics created {success_count} result sheet(s); "
                f"summary saved as '{summary_dataset.name}'{wide_text}"
            )
        else:
            self.statusBar().showMessage(
                f"Statistics saved as '{result_datasets[0].name}' ({len(result_datasets[0].frame)} rows)"
            )

    def _statistics_secondary_source_dataset(
        self,
        primary_reference: Dataset,
        secondary_reference: Dataset,
        source_dataset: Dataset,
        target_dataset_names: list[str],
    ) -> Dataset:
        """Return the secondary/group data source for one statistics job."""
        if (
            len(target_dataset_names) == 1
            and source_dataset.name == primary_reference.name
            and secondary_reference.name != primary_reference.name
        ):
            return secondary_reference
        return source_dataset

    def _statistics_batch_preview_rows(
        self,
        primary_reference: Dataset,
        secondary_reference: Dataset | None,
        target_dataset_names: list[str],
        operation_scope: str,
        requested_primary_columns: list[str],
        requested_secondary_columns: list[str],
        requested_multi_columns: list[str],
        requested_result_sheet: str,
        column_binding_mode: str,
        multiple_primary_jobs: bool,
    ) -> list[dict[str, object]]:
        """Return preflight preview rows for statistics batch jobs."""
        rows: list[dict[str, object]] = []
        for source_name in target_dataset_names:
            try:
                source_dataset = self._workspace.get_dataset(source_name)
            except Exception as exc:
                rows.append(
                    {
                        "source_sheet": source_name,
                        "status": "failed",
                        "primary_column": "",
                        "secondary_column": "",
                        "columns": "",
                        "result_sheet": "",
                        "column_binding": self._batch_column_binding_label(column_binding_mode),
                        "error": str(exc),
                    }
                )
                continue

            if operation_scope == "multi":
                result_sheet = self._batch_result_dataset_name(
                    source_name=source_dataset.name,
                    requested_name=requested_result_sheet,
                    current_dataset_name=primary_reference.name,
                    default_suffix="statistics",
                )
                status = "ready"
                error = ""
                resolved_columns: list[str] = []
                try:
                    resolved_columns = self._resolve_batch_columns(
                        reference_dataset=primary_reference,
                        target_dataset=source_dataset,
                        source_columns=requested_multi_columns,
                        binding_mode=column_binding_mode,
                        field_label="Statistics column",
                    )
                    if len(resolved_columns) < 2:
                        raise MathOperationError("Choose at least two columns for a multiple-column operation.")
                except Exception as exc:
                    status = "failed"
                    error = str(exc)
                rows.append(
                    {
                        "source_sheet": source_dataset.name,
                        "status": status,
                        "primary_column": "",
                        "secondary_column": "",
                        "columns": ", ".join(resolved_columns or requested_multi_columns),
                        "result_sheet": result_sheet,
                        "column_binding": self._batch_column_binding_label(column_binding_mode),
                        "error": error,
                    }
                )
                continue

            for primary_index, requested_primary_column in enumerate(requested_primary_columns):
                requested_secondary_column = ""
                if operation_scope in {"pair", "group"}:
                    requested_secondary_column = (
                        requested_secondary_columns[0]
                        if len(requested_secondary_columns) == 1
                        else requested_secondary_columns[primary_index]
                    )
                result_sheet = self._batch_result_dataset_name(
                    source_name=source_dataset.name,
                    requested_name=requested_result_sheet,
                    current_dataset_name=primary_reference.name,
                    default_suffix="statistics",
                    source_column=requested_primary_column,
                    multiple_columns=multiple_primary_jobs,
                )
                status = "ready"
                error = ""
                primary_column = requested_primary_column
                secondary_column = requested_secondary_column
                try:
                    resolved_primary = self._resolve_batch_column(
                        reference_dataset=primary_reference,
                        target_dataset=source_dataset,
                        source_column=requested_primary_column,
                        binding_mode=column_binding_mode,
                        field_label="Primary",
                    )
                    primary_column = resolved_primary or ""
                    if not primary_column:
                        raise MathOperationError("Choose a primary column.")
                    if secondary_reference is not None:
                        secondary_dataset = self._statistics_secondary_source_dataset(
                            primary_reference=primary_reference,
                            secondary_reference=secondary_reference,
                            source_dataset=source_dataset,
                            target_dataset_names=target_dataset_names,
                        )
                        resolved_secondary = self._resolve_batch_column(
                            reference_dataset=secondary_reference,
                            target_dataset=secondary_dataset,
                            source_column=requested_secondary_column,
                            binding_mode=column_binding_mode,
                            field_label="Secondary/group",
                        )
                        secondary_column = resolved_secondary or ""
                        if not secondary_column:
                            raise MathOperationError("Choose a secondary or group column.")
                except Exception as exc:
                    status = "failed"
                    error = str(exc)
                rows.append(
                    {
                        "source_sheet": source_dataset.name,
                        "status": status,
                        "primary_column": primary_column,
                        "secondary_column": secondary_column,
                        "columns": "",
                        "result_sheet": result_sheet,
                        "column_binding": self._batch_column_binding_label(column_binding_mode),
                        "error": error,
                    }
                )
        return rows

    def _queue_statistics_batch_plot(
        self,
        dialog: StatisticsDialog,
        plot_created: bool,
        primary_reference: Dataset,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset | None,
        secondary_column: str,
        result_dataset: Dataset,
        multi_columns: list[str],
    ) -> bool:
        """Create at most one companion plot for a statistics batch."""
        if plot_created or not dialog.plot_result_immediately():
            return plot_created
        if primary_dataset.name != primary_reference.name:
            return plot_created
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
            self._tabs.setCurrentWidget(self._plot_tab_widget)
            return True
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Statistics Plot",
                f"Statistics results were saved, but the companion plot could not be created:\n{exc}",
            )
            return True

    def _statistics_batch_result_rows(
        self,
        operation_key: str,
        operation_scope: str,
        column_binding_mode: str,
        source_sheet: str,
        secondary_sheet: str,
        requested_result_sheet: str,
        output_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        result_frame: pd.DataFrame | None = None,
        requested_primary_column: str = "",
        primary_column: str = "",
        requested_secondary_column: str = "",
        secondary_column: str = "",
        requested_columns: list[str] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Return annotated cumulative statistics rows for one batch job."""
        operation = STATISTIC_OPERATIONS[operation_key]
        base: dict[str, object] = {
            "source_sheet": source_sheet,
            "secondary_sheet": secondary_sheet,
            "operation_key": operation_key,
            "operation_label": operation.label,
            "operation_scope": operation_scope,
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_primary_column": requested_primary_column,
            "primary_column": primary_column,
            "requested_secondary_column": requested_secondary_column,
            "secondary_column": secondary_column,
            "requested_columns": ", ".join(requested_columns or []),
            "columns": ", ".join(columns or []),
            "requested_result_sheet": requested_result_sheet,
            "output_sheet": output_sheet,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
        }
        if result_frame is None or result_frame.empty:
            row = dict(base)
            row["result_row"] = np.nan
            return [row]

        if operation_key in {"single_zscore", "single_cumulative"}:
            row = dict(base)
            row.update(self._statistics_rowwise_result_metrics(result_frame))
            return [row]

        rows: list[dict[str, object]] = []
        for result_index, result_row in result_frame.reset_index(drop=True).iterrows():
            row = dict(base)
            row["result_row"] = int(result_index)
            for column_name, value in result_row.items():
                clean_name = str(column_name)
                if clean_name in row:
                    clean_name = f"result_{clean_name}"
                row[clean_name] = value
            rows.append(row)
        return rows

    @staticmethod
    def _statistics_rowwise_result_metrics(result_frame: pd.DataFrame) -> dict[str, object]:
        """Return compact batch-summary metrics for row-wise statistics outputs."""
        metrics: dict[str, object] = {
            "result_row": "compact",
            "result_row_count": len(result_frame),
        }
        for column_name in [
            "value",
            "z_score",
            "cumulative_count",
            "cumulative_sum",
            "cumulative_mean",
            "cumulative_std",
            "cumulative_min",
            "cumulative_max",
        ]:
            if column_name not in result_frame:
                continue
            values = pd.to_numeric(result_frame[column_name], errors="coerce")
            values = values.replace([np.inf, -np.inf], np.nan).dropna()
            metrics[f"{column_name}_finite_count"] = int(len(values))
            if values.empty:
                continue
            metrics[f"{column_name}_first"] = float(values.iloc[0])
            metrics[f"{column_name}_last"] = float(values.iloc[-1])
            metrics[f"{column_name}_minimum"] = float(values.min())
            metrics[f"{column_name}_maximum"] = float(values.max())
            metrics[f"{column_name}_mean"] = float(values.mean())
        if "z_score" in result_frame:
            z_values = pd.to_numeric(result_frame["z_score"], errors="coerce")
            z_values = z_values.replace([np.inf, -np.inf], np.nan).dropna()
            metrics["absolute_z_gt_3_count"] = int((np.abs(z_values) > 3).sum())
        return metrics

    def _statistics_batch_wide_summary_dataset(
        self,
        primary_reference: Dataset,
        summary_rows: list[dict[str, object]],
    ) -> Dataset | None:
        """Create a compact wide statistics summary from long metric rows when useful."""
        if len(summary_rows) <= 1:
            return None
        frame = pd.DataFrame(summary_rows)
        if "metric" not in frame.columns or "value" not in frame.columns:
            return None
        metric_rows = frame[
            (frame.get("status", "") == "ok")
            & frame["metric"].notna()
            & (frame["metric"].astype(str) != "")
        ].copy()
        if metric_rows.empty:
            return None

        index_columns = [
            column
            for column in [
                "source_sheet",
                "primary_column",
                "secondary_sheet",
                "secondary_column",
                "columns",
                "operation_key",
                "operation_label",
            ]
            if column in metric_rows.columns
        ]
        if not index_columns:
            return None
        value_wide = (
            metric_rows.groupby(index_columns + ["metric"], dropna=False)["value"]
            .first()
            .unstack("metric")
            .reset_index()
        )
        if "p_value" in metric_rows.columns:
            p_wide = (
                metric_rows.groupby(index_columns + ["metric"], dropna=False)["p_value"]
                .first()
                .unstack("metric")
                .add_suffix("_p_value")
                .reset_index()
            )
            value_wide = value_wide.merge(p_wide, on=index_columns, how="left")
        dataset = self._workspace.add_dataset(
            f"{primary_reference.name}_statistics_batch_wide_summary",
            value_wide,
        )
        set_dataset_operation_comments(dataset, "Statistics batch wide/pivot summary")
        return dataset

    @staticmethod
    def _statistics_operation_comment(
        operation_key: str,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset | None,
        secondary_column: str,
        multi_columns: list[str],
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
    ) -> str:
        """Return a compact provenance comment for a statistics result sheet."""
        operation_label = STATISTIC_OPERATIONS[operation_key].label
        if multi_columns:
            inputs = f"{primary_dataset.name}: {', '.join(multi_columns)}"
        else:
            inputs = f"{primary_dataset.name}: {primary_column}"
            if secondary_dataset is not None and secondary_column:
                inputs = f"{inputs}; secondary={secondary_dataset.name}: {secondary_column}"
        return (
            f"Statistics: operation={operation_label}, inputs={inputs}, "
            f"binding={MainWindow._batch_column_binding_label(column_binding_mode)}"
        )

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
        validate_numeric_column_metadata(dataset.frame, column, values)
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
        values = pd.to_numeric(dataset.frame[column], errors="coerce")
        validate_numeric_column_metadata(dataset.frame, column, values)
        return values.replace([np.inf, -np.inf], np.nan)

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
            dataset_names=[
                candidate.name
                for candidate in self._workspace.list_datasets()
                if len(candidate.frame.columns) > 0
            ],
            current_dataset_name=dataset.name,
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

        self._run_curve_fit_batch(
            current_dataset=dataset,
            dialog=dialog,
            initial_parameters=initial_parameters,
            lower_bounds=lower_bounds,
            upper_bounds=upper_bounds,
            fixed_parameters=fixed_parameters,
        )

    def _run_curve_fit_batch(
        self,
        current_dataset: Dataset,
        dialog: FitDialog,
        initial_parameters: list[float],
        lower_bounds: list[float | None],
        upper_bounds: list[float | None],
        fixed_parameters: list[bool],
    ) -> None:
        """Run curve fitting on one or more worksheets and response columns."""
        target_dataset_names = dialog.target_dataset_names()
        column_binding_mode = dialog.column_binding_mode()
        requested_x_column = dialog.x_column()
        requested_y_columns = dialog.y_columns()
        requested_x_weight_column = dialog.x_weight_column()
        requested_weight_columns = dialog.weight_columns()
        multiple_y_columns = len(requested_y_columns) > 1
        residual_needed = dialog.create_residual_sheet() or dialog.plot_residuals()
        custom_models = self._workspace.list_custom_fit_models()

        fit_datasets: list[Dataset] = []
        current_fit_dataset: Dataset | None = None
        current_residual_dataset: Dataset | None = None
        current_fit_source: Dataset | None = None
        current_fit_result: FitResult | None = None
        current_fit_x_column = ""
        current_fit_y_column = ""
        current_fit_x_weight_column: str | None = None
        current_fit_weight_column: str | None = None
        first_fit_result: FitResult | None = None
        results: list[dict[str, object]] = []
        parameter_correlation_rows: list[dict[str, object]] = []
        fit_report_rows: list[dict[str, object]] = []
        jobs: list[tuple[str, int, str, str | None]] = []
        for source_name in target_dataset_names:
            for index, requested_y_column in enumerate(requested_y_columns):
                requested_weight_column = None
                if len(requested_weight_columns) == 1:
                    requested_weight_column = requested_weight_columns[0]
                elif requested_weight_columns:
                    requested_weight_column = requested_weight_columns[index]
                jobs.append((source_name, index, requested_y_column, requested_weight_column))
        preview_rows = self._fit_batch_preview_rows(
            current_dataset=current_dataset,
            dialog=dialog,
            jobs=jobs,
            requested_x_column=requested_x_column,
            requested_x_weight_column=requested_x_weight_column,
            multiple_y_columns=multiple_y_columns,
            residual_needed=residual_needed,
            column_binding_mode=column_binding_mode,
        )
        if (len(preview_rows) > 1 or any(row["status"] == "failed" for row in preview_rows)) and not (
            self._show_batch_preview(
                "Curve Fit Batch Preview",
                preview_rows,
                [
                    ("Sheet", "source_sheet"),
                    ("Status", "status"),
                    ("X", "x_column"),
                    ("Y", "y_column"),
                    ("Y Weight", "weight_column"),
                    ("Fit Sheet", "fit_sheet"),
                    ("Residual Sheet", "residual_sheet"),
                    ("Binding", "column_binding"),
                    ("Details", "error"),
                ],
            )
        ):
            return
        progress = self._batch_progress_dialog("Curve Fit Batch", len(jobs))
        completed_jobs = 0

        for source_name, _index, requested_y_column, requested_weight_column in jobs:
                if self._batch_progress_canceled(
                    progress,
                    completed_jobs,
                    f"Curve Fit: {source_name} / {requested_y_column}",
                ):
                    requested_fit_sheet = self._batch_result_dataset_name(
                        source_name=source_name,
                        requested_name=dialog.target_dataset_name(),
                        current_dataset_name=current_dataset.name,
                        default_suffix="fit",
                        source_column=requested_y_column,
                        multiple_columns=multiple_y_columns,
                    )
                    requested_residual_sheet = (
                        self._batch_result_dataset_name(
                            source_name=source_name,
                            requested_name=dialog.residual_dataset_name(),
                            current_dataset_name=current_dataset.name,
                            default_suffix="residuals",
                            source_column=requested_y_column,
                            multiple_columns=multiple_y_columns,
                        )
                        if residual_needed
                        else ""
                    )
                    results.append(
                        self._fit_batch_summary_row(
                            source_sheet=source_name,
                            requested_x_column=requested_x_column,
                            x_column=requested_x_column,
                            requested_y_column=requested_y_column,
                            y_column=requested_y_column,
                            requested_x_weight_column=requested_x_weight_column,
                            x_weight_column=requested_x_weight_column,
                            requested_weight_column=requested_weight_column,
                            weight_column=requested_weight_column,
                            column_binding_mode=column_binding_mode,
                            requested_fit_sheet=requested_fit_sheet,
                            output_fit_sheet="",
                            requested_residual_sheet=requested_residual_sheet,
                            output_residual_sheet="",
                            status="canceled",
                            error="Canceled by user before this job was processed.",
                            elapsed_seconds=0.0,
                            dialog=dialog,
                        )
                    )
                    completed_jobs += 1
                    continue
                started = time.perf_counter()
                requested_fit_sheet = self._batch_result_dataset_name(
                    source_name=source_name,
                    requested_name=dialog.target_dataset_name(),
                    current_dataset_name=current_dataset.name,
                    default_suffix="fit",
                    source_column=requested_y_column,
                    multiple_columns=multiple_y_columns,
                )
                requested_residual_sheet = (
                    self._batch_result_dataset_name(
                        source_name=source_name,
                        requested_name=dialog.residual_dataset_name(),
                        current_dataset_name=current_dataset.name,
                        default_suffix="residuals",
                        source_column=requested_y_column,
                        multiple_columns=multiple_y_columns,
                    )
                    if residual_needed
                    else ""
                )
                try:
                    source_dataset = self._workspace.get_dataset(source_name)
                    x_column = self._resolve_batch_column(
                        reference_dataset=current_dataset,
                        target_dataset=source_dataset,
                        source_column=requested_x_column,
                        binding_mode=column_binding_mode,
                        field_label="X",
                    )
                    y_column = self._resolve_batch_column(
                        reference_dataset=current_dataset,
                        target_dataset=source_dataset,
                        source_column=requested_y_column,
                        binding_mode=column_binding_mode,
                        field_label="Y",
                    )
                    x_weight_column = self._resolve_batch_column(
                        reference_dataset=current_dataset,
                        target_dataset=source_dataset,
                        source_column=requested_x_weight_column,
                        binding_mode=column_binding_mode,
                        field_label="X weight/sigma",
                    )
                    weight_column = self._resolve_batch_column(
                        reference_dataset=current_dataset,
                        target_dataset=source_dataset,
                        source_column=requested_weight_column,
                        binding_mode=column_binding_mode,
                        field_label="Y weight/sigma",
                    )
                    if x_column is None or y_column is None:
                        raise MathOperationError("Choose X and at least one Y column.")

                    fit_result = fit_curve(
                        source_dataset.frame,
                        x_column=x_column,
                        y_column=y_column,
                        model_key=dialog.model_key(),
                        method=dialog.method(),
                        initial_parameters=initial_parameters,
                        lower_bounds=lower_bounds,
                        upper_bounds=upper_bounds,
                        fixed_parameters=fixed_parameters,
                        weight_column=weight_column,
                        weight_mode=dialog.weight_mode(),
                        absolute_sigma=dialog.absolute_sigma(),
                        include_confidence_band=dialog.include_confidence_band(),
                        confidence_level=dialog.confidence_level(),
                        fit_points=dialog.fit_points(),
                        x_weight_column=x_weight_column,
                        custom_models=custom_models,
                    )
                    fit_dataset = self._workspace.add_dataset(requested_fit_sheet, fit_result.fit_frame)
                    fit_datasets.append(fit_dataset)
                    fit_operation_comment = self._fit_operation_comment(
                        x_column=x_column,
                        y_column=y_column,
                        model_name=fit_result.report.model_name,
                        method=fit_result.report.method,
                        x_weight_column=x_weight_column,
                        weight_column=weight_column,
                        weight_mode=dialog.weight_mode(),
                        column_binding_mode=column_binding_mode,
                    )
                    set_dataset_operation_comments(fit_dataset, fit_operation_comment)

                    residual_dataset = None
                    if residual_needed:
                        residual_dataset = self._workspace.add_dataset(
                            requested_residual_sheet,
                            fit_result.residual_frame,
                        )
                        set_dataset_operation_comments(
                            residual_dataset,
                            f"Fit residuals: {fit_operation_comment}",
                        )

                    if first_fit_result is None:
                        first_fit_result = fit_result
                    if source_dataset.name == current_dataset.name and current_fit_dataset is None:
                        current_fit_dataset = fit_dataset
                        current_residual_dataset = residual_dataset
                        current_fit_source = source_dataset
                        current_fit_result = fit_result
                        current_fit_x_column = x_column
                        current_fit_y_column = y_column
                        current_fit_x_weight_column = x_weight_column
                        current_fit_weight_column = weight_column

                    if dialog.create_parameter_correlation_sheet():
                        parameter_correlation_rows.extend(
                            self._fit_parameter_correlation_rows(
                                source_dataset=source_dataset,
                                result=fit_result,
                                requested_x_column=requested_x_column,
                                x_column=x_column,
                                requested_y_column=requested_y_column,
                                y_column=y_column,
                                column_binding_mode=column_binding_mode,
                                output_fit_sheet=fit_dataset.name,
                            )
                        )
                    fit_report_rows.append(
                        {
                            "source_sheet": source_dataset.name,
                            "requested_y_column": requested_y_column,
                            "y_column": y_column,
                            "output_fit_sheet": fit_dataset.name,
                            "model_name": fit_result.report.model_name,
                            "method": fit_result.report.method,
                            "r_squared": fit_result.report.r_squared,
                            "rmse": fit_result.report.rmse,
                            "report_text": fit_result.report.to_text(),
                        }
                    )

                    results.append(
                        self._fit_batch_summary_row(
                            source_dataset=source_dataset,
                            result=fit_result,
                            requested_x_column=requested_x_column,
                            x_column=x_column,
                            requested_y_column=requested_y_column,
                            y_column=y_column,
                            requested_x_weight_column=requested_x_weight_column,
                            x_weight_column=x_weight_column,
                            requested_weight_column=requested_weight_column,
                            weight_column=weight_column,
                            column_binding_mode=column_binding_mode,
                            requested_fit_sheet=requested_fit_sheet,
                            output_fit_sheet=fit_dataset.name,
                            requested_residual_sheet=requested_residual_sheet,
                            output_residual_sheet=residual_dataset.name if residual_dataset else "",
                            status="ok",
                            error="",
                            elapsed_seconds=time.perf_counter() - started,
                        )
                    )
                except MathOperationError as exc:
                    results.append(
                        self._fit_batch_summary_row(
                            source_sheet=source_name,
                            requested_x_column=requested_x_column,
                            x_column=requested_x_column,
                            requested_y_column=requested_y_column,
                            y_column=requested_y_column,
                            requested_x_weight_column=requested_x_weight_column,
                            x_weight_column=requested_x_weight_column,
                            requested_weight_column=requested_weight_column,
                            weight_column=requested_weight_column,
                            column_binding_mode=column_binding_mode,
                            requested_fit_sheet=requested_fit_sheet,
                            output_fit_sheet="",
                            requested_residual_sheet=requested_residual_sheet,
                            output_residual_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=time.perf_counter() - started,
                            dialog=dialog,
                        )
                    )
                except Exception as exc:
                    results.append(
                        self._fit_batch_summary_row(
                            source_sheet=source_name,
                            requested_x_column=requested_x_column,
                            x_column=requested_x_column,
                            requested_y_column=requested_y_column,
                            y_column=requested_y_column,
                            requested_x_weight_column=requested_x_weight_column,
                            x_weight_column=requested_x_weight_column,
                            requested_weight_column=requested_weight_column,
                            weight_column=requested_weight_column,
                            column_binding_mode=column_binding_mode,
                            requested_fit_sheet=requested_fit_sheet,
                            output_fit_sheet="",
                            requested_residual_sheet=requested_residual_sheet,
                            output_residual_sheet="",
                            status="failed",
                            error=str(exc),
                            elapsed_seconds=time.perf_counter() - started,
                            dialog=dialog,
                        )
                    )
                completed_jobs += 1

        if progress is not None:
            progress.setValue(completed_jobs)

        summary_dataset = None
        if len(results) > 1:
            summary_dataset = self._workspace.add_dataset(
                f"{current_dataset.name}_fit_batch_summary",
                pd.DataFrame(results),
            )
        parameter_correlation_dataset = None
        if parameter_correlation_rows:
            correlation_name = (
                f"{fit_datasets[0].name}_parameter_correlations"
                if len(results) == 1 and fit_datasets
                else f"{current_dataset.name}_fit_parameter_correlations"
            )
            parameter_correlation_dataset = self._workspace.add_dataset(
                correlation_name,
                pd.DataFrame(parameter_correlation_rows),
            )
            set_dataset_operation_comments(
                parameter_correlation_dataset,
                "Fit parameter covariance/correlation pairs",
            )
        report_export_dataset = None
        if fit_report_rows and len(results) > 1:
            report_export_dataset = self._workspace.add_dataset(
                f"{current_dataset.name}_fit_reports",
                pd.DataFrame(fit_report_rows),
            )
            set_dataset_operation_comments(report_export_dataset, "Curve fit text report exports")

        success_count = sum(1 for row in results if row["status"] == "ok")
        failure_rows = [row for row in results if row["status"] != "ok"]
        selected_name = ""
        if current_fit_dataset is not None:
            selected_name = current_fit_dataset.name
        elif fit_datasets:
            selected_name = fit_datasets[0].name
        elif summary_dataset is not None:
            selected_name = summary_dataset.name

        if selected_name:
            self._refresh_dataset_list(selected_name)
        else:
            self._update_dataset_summary()

        if success_count == 0:
            message = "\n".join(
                f"{row['source_sheet']} / {row['requested_y_column']}: {row['error']}"
                for row in failure_rows[:8]
            )
            if summary_dataset is not None:
                message = f"{message}\n\nSummary saved as '{summary_dataset.name}'."
            QMessageBox.warning(
                self,
                "Curve Fit Failed",
                message or "Curve fitting failed on every selected sheet/column.",
            )
            return

        if current_fit_dataset is not None and current_fit_source is not None and current_fit_result is not None:
            x_error_column = current_fit_x_weight_column if dialog.weight_mode() == "sigma" else ""
            y_error_column = current_fit_weight_column if dialog.weight_mode() == "sigma" else ""
            self._plot_tab_widget.queue_fit_plot(
                source_dataset=current_fit_source,
                fit_dataset=current_fit_dataset,
                x_column=current_fit_x_column,
                y_column=current_fit_y_column,
                model_name=current_fit_result.report.model_name,
                residual_dataset=current_residual_dataset,
                show_residuals=dialog.plot_residuals(),
                x_err_column=x_error_column or "",
                y_err_column=y_error_column or "",
            )
            self._tabs.setCurrentWidget(self._plot_tab_widget)

        if len(results) == 1 and first_fit_result is not None:
            FitReportDialog(first_fit_result.report.to_text(), self).exec()

        if failure_rows:
            detail = "\n".join(
                f"{row['source_sheet']} / {row['requested_y_column']}: {row['error']}"
                for row in failure_rows[:8]
            )
            QMessageBox.warning(
                self,
                "Curve Fit Batch",
                f"Created {success_count} fit result(s); {len(failure_rows)} failed.\n\n{detail}",
            )

        self.statusBar().showMessage(
            self._fit_batch_status_message(
                success_count=success_count,
                failure_count=len(failure_rows),
                summary_dataset_name=summary_dataset.name if summary_dataset else "",
                parameter_correlation_dataset_name=(
                    parameter_correlation_dataset.name if parameter_correlation_dataset else ""
                ),
                first_result=first_fit_result,
                first_fit_dataset_name=fit_datasets[0].name if fit_datasets else "",
            )
        )

    def _fit_batch_preview_rows(
        self,
        current_dataset: Dataset,
        dialog: FitDialog,
        jobs: list[tuple[str, int, str, str | None]],
        requested_x_column: str,
        requested_x_weight_column: str | None,
        multiple_y_columns: bool,
        residual_needed: bool,
        column_binding_mode: str,
    ) -> list[dict[str, object]]:
        """Return preflight preview rows for curve-fit jobs."""
        rows: list[dict[str, object]] = []
        for source_name, _index, requested_y_column, requested_weight_column in jobs:
            fit_sheet = self._batch_result_dataset_name(
                source_name=source_name,
                requested_name=dialog.target_dataset_name(),
                current_dataset_name=current_dataset.name,
                default_suffix="fit",
                source_column=requested_y_column,
                multiple_columns=multiple_y_columns,
            )
            residual_sheet = (
                self._batch_result_dataset_name(
                    source_name=source_name,
                    requested_name=dialog.residual_dataset_name(),
                    current_dataset_name=current_dataset.name,
                    default_suffix="residuals",
                    source_column=requested_y_column,
                    multiple_columns=multiple_y_columns,
                )
                if residual_needed
                else ""
            )
            status = "ready"
            error = ""
            x_column = requested_x_column
            y_column = requested_y_column
            weight_column = requested_weight_column or ""
            try:
                source_dataset = self._workspace.get_dataset(source_name)
                resolved_x = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_x_column,
                    binding_mode=column_binding_mode,
                    field_label="X",
                )
                resolved_y = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_y_column,
                    binding_mode=column_binding_mode,
                    field_label="Y",
                )
                self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_x_weight_column,
                    binding_mode=column_binding_mode,
                    field_label="X weight/sigma",
                )
                resolved_weight = self._resolve_batch_column(
                    reference_dataset=current_dataset,
                    target_dataset=source_dataset,
                    source_column=requested_weight_column,
                    binding_mode=column_binding_mode,
                    field_label="Y weight/sigma",
                )
                x_column = resolved_x or ""
                y_column = resolved_y or ""
                weight_column = resolved_weight or ""
                if not x_column or not y_column:
                    raise MathOperationError("Choose X and at least one Y column.")
            except Exception as exc:
                status = "failed"
                error = str(exc)
            rows.append(
                {
                    "source_sheet": source_name,
                    "status": status,
                    "x_column": x_column,
                    "y_column": y_column,
                    "weight_column": weight_column,
                    "fit_sheet": fit_sheet,
                    "residual_sheet": residual_sheet,
                    "column_binding": self._batch_column_binding_label(column_binding_mode),
                    "error": error,
                }
            )
        return rows

    @staticmethod
    def _fit_operation_comment(
        x_column: str,
        y_column: str,
        model_name: str,
        method: str,
        x_weight_column: str | None,
        weight_column: str | None,
        weight_mode: str,
        column_binding_mode: str,
    ) -> str:
        """Return a provenance comment for fit output datasets."""
        comment = (
            f"Curve fit: y={y_column}, x={x_column}, model={model_name}, "
            f"method={FIT_METHODS.get(method, method)}, "
            f"binding={MainWindow._batch_column_binding_label(column_binding_mode)}"
        )
        if x_weight_column or weight_column:
            comment = (
                f"{comment}, x_weight={x_weight_column or 'None'}, "
                f"y_weight={weight_column or 'None'}, weight_mode={weight_mode}"
            )
        return comment

    def _fit_batch_summary_row(
        self,
        requested_x_column: str,
        x_column: str | None,
        requested_y_column: str,
        y_column: str | None,
        requested_x_weight_column: str | None,
        x_weight_column: str | None,
        requested_weight_column: str | None,
        weight_column: str | None,
        column_binding_mode: str,
        requested_fit_sheet: str,
        output_fit_sheet: str,
        requested_residual_sheet: str,
        output_residual_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        result: FitResult | None = None,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        dialog: FitDialog | None = None,
    ) -> dict[str, object]:
        """Return one curve-fit batch summary row."""
        report = result.report if result is not None else None
        method_key = report.method if report is not None else (dialog.method() if dialog is not None else "")
        model_key = report.model_key if report is not None else (dialog.model_key() if dialog is not None else "")
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": "Curve Fit",
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_x_column": requested_x_column,
            "x_column": x_column or "",
            "requested_y_column": requested_y_column,
            "y_column": y_column or "",
            "requested_x_weight_column": requested_x_weight_column or "",
            "x_weight_column": x_weight_column or "",
            "requested_y_weight_column": requested_weight_column or "",
            "y_weight_column": weight_column or "",
            "weight_mode": report.weight_mode if report is not None else (dialog.weight_mode() if dialog else ""),
            "absolute_sigma": report.absolute_sigma if report is not None else (dialog.absolute_sigma() if dialog else False),
            "model_key": model_key,
            "model_name": report.model_name if report is not None else model_key,
            "method": method_key,
            "method_label": FIT_METHODS.get(method_key, method_key),
            "fit_points": dialog.fit_points() if dialog is not None else (len(result.fit_frame) if result is not None else 0),
            "confidence_level": (
                report.confidence_level
                if report is not None
                else (dialog.confidence_level() if dialog is not None and dialog.include_confidence_band() else 0.0)
            ),
            "requested_fit_sheet": requested_fit_sheet,
            "output_fit_sheet": output_fit_sheet,
            "requested_residual_sheet": requested_residual_sheet,
            "output_residual_sheet": output_residual_sheet,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
            "point_count": report.point_count if report is not None else 0,
            "r_squared": report.r_squared if report is not None else np.nan,
            "adjusted_r_squared": report.adjusted_r_squared if report is not None else np.nan,
            "rmse": report.rmse if report is not None else np.nan,
            "mae": report.mae if report is not None else np.nan,
            "residual_mean": report.residual_mean if report is not None else np.nan,
            "residual_std": report.residual_std if report is not None else np.nan,
            "covariance_available": False,
            "warnings": "",
        }
        if report is None:
            return row

        covariance = np.asarray(report.covariance, dtype=float)
        row["covariance_available"] = bool(covariance.size and np.isfinite(covariance).any())
        row["warnings"] = "; ".join(report.warnings)
        for name, value, standard_error, lower, upper, fixed in zip(
            report.parameter_names,
            report.parameters,
            report.standard_errors,
            report.lower_bounds,
            report.upper_bounds,
            report.fixed_parameters,
        ):
            key = self._fit_summary_key(name)
            row[f"param_{key}"] = value
            row[f"stderr_{key}"] = standard_error
            row[f"lower_{key}"] = lower
            row[f"upper_{key}"] = upper
            row[f"fixed_{key}"] = fixed
        return row

    def _fit_parameter_correlation_rows(
        self,
        source_dataset: Dataset,
        result: FitResult,
        requested_x_column: str,
        x_column: str,
        requested_y_column: str,
        y_column: str,
        column_binding_mode: str,
        output_fit_sheet: str,
    ) -> list[dict[str, object]]:
        """Return long-format covariance/correlation rows for one fit report."""
        report = result.report
        parameter_names = list(report.parameter_names)
        covariance = np.asarray(report.covariance, dtype=float)
        if covariance.shape != (len(parameter_names), len(parameter_names)):
            return []
        if not np.isfinite(covariance).any():
            return []

        variances = np.diag(covariance)
        rows: list[dict[str, object]] = []
        for first_index, first_name in enumerate(parameter_names):
            for second_index in range(first_index, len(parameter_names)):
                second_name = parameter_names[second_index]
                covariance_value = float(covariance[first_index, second_index])
                first_variance = float(variances[first_index])
                second_variance = float(variances[second_index])
                correlation = np.nan
                if (
                    np.isfinite(covariance_value)
                    and np.isfinite(first_variance)
                    and np.isfinite(second_variance)
                    and first_variance > 0
                    and second_variance > 0
                ):
                    correlation = float(covariance_value / np.sqrt(first_variance * second_variance))

                rows.append(
                    {
                        "source_sheet": source_dataset.name,
                        "output_fit_sheet": output_fit_sheet,
                        "model_key": report.model_key,
                        "model_name": report.model_name,
                        "method": report.method,
                        "method_label": FIT_METHODS.get(report.method, report.method),
                        "column_binding": self._batch_column_binding_label(column_binding_mode),
                        "requested_x_column": requested_x_column,
                        "x_column": x_column,
                        "requested_y_column": requested_y_column,
                        "y_column": y_column,
                        "parameter_1": first_name,
                        "parameter_2": second_name,
                        "parameter_1_index": first_index,
                        "parameter_2_index": second_index,
                        "pair_type": "variance" if first_index == second_index else "cross",
                        "covariance": covariance_value,
                        "correlation": correlation,
                    }
                )
        return rows

    @staticmethod
    def _fit_summary_key(parameter_name: str) -> str:
        """Return a stable summary-column suffix for a fit parameter."""
        clean = re.sub(r"\W+", "_", str(parameter_name).strip()).strip("_")
        return clean or "parameter"

    @staticmethod
    def _fit_batch_status_message(
        success_count: int,
        failure_count: int,
        summary_dataset_name: str,
        parameter_correlation_dataset_name: str,
        first_result: FitResult | None,
        first_fit_dataset_name: str,
    ) -> str:
        """Return a concise curve-fit batch status message."""
        if summary_dataset_name:
            message = (
                f"Curve Fit created {success_count} fit result(s), "
                f"{failure_count} failed; summary saved as '{summary_dataset_name}'"
            )
            if parameter_correlation_dataset_name:
                message = f"{message}; parameter correlations saved as '{parameter_correlation_dataset_name}'"
            return message
        if failure_count:
            message = f"Curve Fit created {success_count} fit result(s), {failure_count} failed"
            if parameter_correlation_dataset_name:
                message = f"{message}; parameter correlations saved as '{parameter_correlation_dataset_name}'"
            return message
        if first_result is not None and first_fit_dataset_name:
            message = f"Fit saved as '{first_fit_dataset_name}' with R^2={first_result.report.r_squared:.5g}"
            if parameter_correlation_dataset_name:
                message = f"{message}; parameter correlations saved as '{parameter_correlation_dataset_name}'"
            return message
        message = f"Curve Fit created {success_count} fit result(s)"
        if parameter_correlation_dataset_name:
            message = f"{message}; parameter correlations saved as '{parameter_correlation_dataset_name}'"
        return message

    def _refresh_dataset_after_analysis(self, dataset: Dataset, selected_column: str) -> None:
        """Refresh editor and plot controls after an in-place analysis column edit."""
        self._dataset_model.set_dataset(dataset)
        self._resize_dataset_columns_to_contents(dataset)
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        self._select_column(selected_column)

    def _clear_selected_dataset_cells(self) -> None:
        """Clear selected worksheet values without deleting rows or columns."""
        dataset = self._current_dataset()
        if dataset is None:
            return

        selection_ranges = self._selected_dataset_ranges()
        if not selection_ranges:
            return

        cleared_count = self._dataset_model.clear_cells(selection_ranges)
        if not cleared_count:
            self.statusBar().showMessage("Selected cells are already empty")
            return

        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        self.statusBar().showMessage(
            f"Cleared {cleared_count} selected cell value(s) in {dataset.name}"
        )

    def _resize_current_sheet(self) -> None:
        """Set worksheet row and column counts together in one undoable edit."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(
                self,
                "Resize Sheet",
                "Select a dataset before resizing the worksheet.",
            )
            return

        old_rows, old_columns = dataset.frame.shape
        dialog = TableSizeDialog(old_rows, old_columns, self)
        dialog.setWindowTitle("Resize Worksheet")
        if dialog.exec() != QDialog.Accepted:
            return

        new_rows = dialog.row_count()
        new_columns = dialog.column_count()
        if (new_rows, new_columns) == (old_rows, old_columns):
            self.statusBar().showMessage("Worksheet size is unchanged")
            return

        if new_rows < old_rows or new_columns < old_columns:
            reply = QMessageBox.question(
                self,
                "Shrink Worksheet?",
                (
                    f"Resize '{dataset.name}' from {old_rows} row(s) x {old_columns} column(s) "
                    f"to {new_rows} row(s) x {new_columns} column(s)?\n\n"
                    "Values, formulas, and column metadata outside the new limits will be removed. "
                    "The change can be undone."
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            self._dataset_model.resize_sheet(new_rows, new_columns)
        except Exception as exc:
            QMessageBox.critical(self, "Resize Sheet Failed", str(exc))
            return

        self._resize_dataset_columns_to_contents(dataset)
        self._plot_tab_widget.refresh_controls(dataset.name)
        self._update_dataset_summary()
        self.statusBar().showMessage(
            f"Resized {dataset.name} to {new_rows} row(s) x {new_columns} column(s)"
        )

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
        try:
            self._dataset_list.clear()
            self._dataset_list.addItems(dataset_names)
            if target_name:
                matches = self._dataset_list.findItems(target_name, Qt.MatchExactly)
                if matches:
                    self._dataset_list.setCurrentItem(matches[0])
        finally:
            self._dataset_list.blockSignals(False)

        if target_name:
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

    def _show_dataset_table_frame_context_menu(self, pos) -> None:
        """Show the worksheet menu on table chrome not owned by the viewport."""
        self._show_dataset_editor_context_menu(self._dataset_table.mapToGlobal(pos))

    def _show_dataset_header_context_menu(self, pos) -> None:
        """Show edit actions for the dataset table header."""
        header = self._dataset_table.horizontalHeader()
        column_index = header.logicalIndexAt(pos)
        if column_index >= 0:
            self._prepare_dataset_context_column(column_index)
        context_column = column_index if column_index >= 0 else None
        self._show_dataset_editor_context_menu(header.mapToGlobal(pos), context_column)

    def _show_dataset_row_header_context_menu(self, pos) -> None:
        """Select a right-clicked row header and show the worksheet menu."""
        header = self._dataset_table.verticalHeader()
        row_index = header.logicalIndexAt(pos)
        if row_index >= 0:
            self._prepare_dataset_context_row(row_index)
        context_row = row_index if row_index >= 0 else None
        self._show_dataset_editor_context_menu(
            header.mapToGlobal(pos),
            context_row=context_row,
        )

    def _show_dataset_editor_context_menu(
        self,
        global_pos,
        context_column: int | None = None,
        context_row: int | None = None,
    ) -> None:
        """Show common editing, preparation, analysis, and plotting actions."""
        dataset = self._current_dataset()
        has_dataset = dataset is not None
        has_selection = self._dataset_has_selection()
        has_columns = has_dataset and (
            context_column is not None or has_selection
        )
        has_rows = has_dataset and (context_row is not None or has_selection)
        clipboard_mime = QApplication.clipboard().mimeData()
        has_clipboard_text = bool(clipboard_mime is not None and clipboard_mime.hasText())

        menu = QMenu()
        undo_action = menu.addAction("Undo")
        undo_action.setEnabled(self._dataset_model.can_undo())
        redo_action = menu.addAction("Redo")
        redo_action.setEnabled(self._dataset_model.can_redo())
        menu.addSeparator()
        copy_values_action = menu.addAction("Copy Values")
        copy_values_action.setEnabled(has_dataset and has_selection)
        copy_rows_action = menu.addAction("Copy Row(s)")
        copy_rows_action.setEnabled(has_rows)
        copy_columns_action = menu.addAction("Copy Column(s)")
        copy_columns_action.setEnabled(has_columns)
        paste_values_action = menu.addAction("Paste Values")
        paste_values_action.setEnabled(has_dataset and has_clipboard_text)
        paste_transposed_action = menu.addAction("Paste Values Transposed")
        paste_transposed_action.setEnabled(has_dataset and has_clipboard_text)
        paste_columns_action = menu.addAction("Paste Column(s)")
        paste_columns_action.setEnabled(
            has_dataset and self._clipboard_has_dataset_columns()
        )
        clear_cells_action = menu.addAction("Clear Selected Cell Values")
        clear_cells_action.setEnabled(has_dataset and has_selection)
        menu.addSeparator()
        edit_actions = self._add_dataset_edit_submenus(
            menu,
            has_dataset=has_dataset,
            has_selection=has_selection,
            has_columns=has_columns,
        )

        menu.addSeparator()
        plot_action = menu.addAction("Create Plot from Dataset")
        plot_action.setEnabled(has_dataset)
        self._add_dataset_workflow_submenus(menu, enabled=has_dataset)

        action = menu.exec(global_pos)
        if action == undo_action:
            self._undo_dataset_edit()
        elif action == redo_action:
            self._redo_dataset_edit()
        elif action == copy_values_action:
            self._copy_dataset_selection()
        elif action == copy_rows_action:
            self._copy_dataset_rows()
        elif action == paste_values_action:
            self._paste_dataset_clipboard()
        elif action == paste_transposed_action:
            self._paste_dataset_clipboard(transpose=True)
        elif action == copy_columns_action:
            self._copy_dataset_columns()
        elif action == paste_columns_action:
            self._paste_dataset_columns(context_column)
        elif action == clear_cells_action:
            self._clear_selected_dataset_cells()
        elif action == edit_actions["add_row"]:
            self._add_empty_row()
        elif action == edit_actions["insert_row"]:
            self._insert_empty_row()
        elif action == edit_actions["delete_rows"]:
            self._delete_selected_rows()
        elif action == edit_actions["add_column"]:
            self._add_empty_column()
        elif action == edit_actions["insert_column"]:
            self._insert_empty_column()
        elif action == edit_actions["delete_columns"]:
            self._delete_selected_columns()
        elif action == edit_actions["resize_sheet"]:
            self._resize_current_sheet()
        elif action == edit_actions["fill_range"]:
            self._fill_dataset_range()
        elif action == edit_actions["metadata"]:
            self._edit_column_metadata()
        elif action == plot_action:
            self._start_plot_for_current_dataset()

    def _add_dataset_edit_submenus(
        self,
        menu: QMenu,
        has_dataset: bool,
        has_selection: bool,
        has_columns: bool,
    ) -> dict[str, object]:
        """Add row and column operations to a worksheet context menu."""
        rows_menu = menu.addMenu("Rows")
        add_row_action = rows_menu.addAction("Add Row")
        add_row_action.setEnabled(has_dataset)
        insert_row_action = rows_menu.addAction("Insert Row")
        insert_row_action.setEnabled(has_dataset)
        delete_rows_action = rows_menu.addAction("Delete Selected Rows")
        delete_rows_action.setEnabled(has_dataset and has_selection)

        columns_menu = menu.addMenu("Columns")
        add_column_action = columns_menu.addAction("Add Column...")
        add_column_action.setEnabled(has_dataset)
        insert_column_action = columns_menu.addAction("Insert Column...")
        insert_column_action.setEnabled(has_dataset)
        delete_columns_action = columns_menu.addAction("Delete Selected Columns")
        delete_columns_action.setEnabled(has_dataset and has_columns)
        columns_menu.addSeparator()
        fill_range_action = columns_menu.addAction("Fill Range...")
        fill_range_action.setEnabled(has_dataset)
        metadata_action = columns_menu.addAction("Column Metadata...")
        metadata_action.setEnabled(has_dataset)
        menu.addSeparator()
        resize_sheet_action = menu.addAction("Resize Sheet...")
        resize_sheet_action.setEnabled(has_dataset)
        return {
            "add_row": add_row_action,
            "insert_row": insert_row_action,
            "delete_rows": delete_rows_action,
            "add_column": add_column_action,
            "insert_column": insert_column_action,
            "delete_columns": delete_columns_action,
            "fill_range": fill_range_action,
            "metadata": metadata_action,
            "resize_sheet": resize_sheet_action,
        }

    def _add_dataset_workflow_submenus(self, menu: QMenu, enabled: bool = True) -> None:
        """Add reusable Data Prep and Analysis launchers to a context menu."""
        data_prep_menu = menu.addMenu("Data Preparation")
        data_prep_actions = (
            ("Filter / Query...", self._run_filter_query),
            ("Sort...", self._run_sort),
            ("Missing Values...", self._run_missing_values),
            ("Remove Duplicates...", self._run_remove_duplicates),
            ("Bin / Average...", self._run_binning),
            ("Group / Aggregate...", self._run_group_aggregate),
            ("Merge / Join...", self._run_merge_join),
            ("Reshape...", self._run_reshape),
        )
        for label, callback in data_prep_actions:
            action = data_prep_menu.addAction(label)
            action.setEnabled(enabled)
            action.triggered.connect(callback)

        analysis_menu = menu.addMenu("Analysis")
        analysis_actions = (
            ("Apply Formula...", self._apply_column_formula),
            ("Derivative...", self._run_derivative),
            ("Integral...", self._run_integral),
            ("Smoothing...", self._run_smoothing),
            ("Interpolation...", self._run_interpolation),
            ("FFT...", self._run_fft),
            ("Inverse FFT...", self._run_ifft),
            ("Statistics...", self._run_statistics),
            ("Curve Fit...", self._run_curve_fit),
        )
        for label, callback in analysis_actions:
            action = analysis_menu.addAction(label)
            action.setEnabled(enabled)
            action.triggered.connect(callback)

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
        if self._dataset_selection_contains_column(column_index):
            return

        self._dataset_table.clearSelection()
        if self._dataset_model.rowCount() > 0:
            self._dataset_table.setCurrentIndex(
                self._dataset_model.index(0, column_index)
            )
        self._dataset_table.selectColumn(column_index)

    def _prepare_dataset_context_row(self, row_index: int) -> None:
        """Make an unselected right-clicked row header the active row selection."""
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return
        if any(
            selection_range.top() <= row_index <= selection_range.bottom()
            and selection_range.left() == 0
            and selection_range.right() == self._dataset_model.columnCount() - 1
            for selection_range in selection_model.selection()
        ):
            return

        self._dataset_table.clearSelection()
        if self._dataset_model.columnCount() > 0:
            self._dataset_table.setCurrentIndex(self._dataset_model.index(row_index, 0))
        self._dataset_table.selectRow(row_index)

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

    def _copy_dataset_rows(self) -> None:
        """Copy every cell from worksheet rows touched by the selection."""
        dataset = self._current_dataset()
        if dataset is None:
            return

        selected_rows = self._selected_dataset_rows()
        if not selected_rows:
            return

        output = StringIO()
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        for row_index in selected_rows:
            writer.writerow(
                "" if pd.isna(value) else str(value)
                for value in dataset.frame.iloc[row_index, :]
            )
        QApplication.clipboard().setText(output.getvalue().rstrip("\n"))
        self.statusBar().showMessage(
            f"Copied {len(selected_rows)} complete row(s) from {dataset.name}"
        )

    def _paste_dataset_clipboard(self, transpose: bool = False) -> None:
        """Paste clipboard values, optionally transposing the complete matrix."""
        dataset = self._current_dataset()
        if dataset is None:
            return

        current_index = self._dataset_table.currentIndex()
        start_row = current_index.row() if current_index.isValid() else 0
        start_column = current_index.column() if current_index.isValid() else 0
        if transpose:
            rows = parse_tabular_clipboard(
                QApplication.clipboard().text(),
                preserve_all_text=True,
            ).transpose().copy().reset_index(drop=True)
            rows.columns = range(len(rows.columns))
        else:
            text_columns = self._clipboard_text_column_offsets(dataset, start_column)
            rows = self._parse_clipboard_text(
                QApplication.clipboard().text(),
                text_columns=text_columns,
            )
        if rows.empty and len(rows.columns) == 0:
            return

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
            paste_label = "Pasted transposed" if transpose else "Pasted"
            self.statusBar().showMessage(
                f"{paste_label} {pasted_rows} row(s) x {pasted_columns} column(s) "
                f"into {dataset.name}"
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
        if not column_names and rows.empty:
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
        """Return whether MIME data is available without eagerly parsing it."""
        mime_data = QApplication.clipboard().mimeData()
        return bool(
            mime_data is not None
            and (mime_data.hasFormat(_DATASET_COLUMNS_MIME) or mime_data.hasText())
        )

    def _clipboard_dataset_columns(
        self,
    ) -> tuple[list[str], pd.DataFrame, list[ColumnMetadata | None]]:
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
                    return column_names, pd.DataFrame(parsed_rows, dtype="object"), parsed_metadata

        rows = self._parse_clipboard_text(QApplication.clipboard().text())
        if rows.empty and len(rows.columns) == 0:
            return [], pd.DataFrame(), []

        column_count = len(rows.columns)
        column_names = [f"Pasted Column {index + 1}" for index in range(column_count)]
        return column_names, rows, []

    def _parse_clipboard_text(
        self,
        text: str,
        text_columns: set[int] | None = None,
    ) -> pd.DataFrame:
        """Parse tab-delimited clipboard text into a typed rectangular block."""
        return parse_tabular_clipboard(text, text_columns=text_columns)

    @staticmethod
    def _clipboard_text_column_offsets(dataset: Dataset, start_column: int) -> set[int]:
        """Return clipboard offsets that must preserve exact textual tokens."""
        text_columns: set[int] = set()
        for target_column in range(max(start_column, 0), len(dataset.frame.columns)):
            column_name = str(dataset.frame.columns[target_column])
            metadata = dataset.column_metadata.get(column_name)
            if (
                (metadata is not None and metadata.value_type == "text")
                or not pd.api.types.is_numeric_dtype(dataset.frame.iloc[:, target_column])
            ):
                text_columns.add(target_column - max(start_column, 0))
        return text_columns

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

    def _dataset_has_selection(self) -> bool:
        """Return selection presence without materializing every selected cell index."""
        selection_model = self._dataset_table.selectionModel()
        return bool(selection_model is not None and selection_model.hasSelection())

    def _selected_dataset_ranges(self) -> list[tuple[int, int, int, int]]:
        """Return compact selected cell rectangles without expanding every index."""
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return []
        return [
            (
                selection_range.top(),
                selection_range.left(),
                selection_range.bottom(),
                selection_range.right(),
            )
            for selection_range in selection_model.selection()
        ]

    def _dataset_selection_contains_column(self, column_index: int) -> bool:
        """Return whether any compact Qt selection range touches a column."""
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return False
        return any(
            selection_range.left() <= column_index <= selection_range.right()
            for selection_range in selection_model.selection()
        )

    def _selected_dataset_rows(self) -> list[int]:
        """Return sorted row indexes touched by the table selection."""
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return []
        rows: set[int] = set()
        for selection_range in selection_model.selection():
            rows.update(range(selection_range.top(), selection_range.bottom() + 1))
        return sorted(rows)

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
        self._delete_cells_action.setEnabled(has_dataset)
        self._delete_rows_action.setEnabled(has_dataset)
        self._delete_columns_action.setEnabled(has_dataset)
        self._paste_transposed_action.setEnabled(has_dataset)
        self._rename_dataset_action.setEnabled(has_dataset)
        self._duplicate_dataset_action.setEnabled(has_dataset)
        self._delete_dataset_action.setEnabled(has_dataset)
        self._add_column_action.setEnabled(has_dataset)
        self._add_row_action.setEnabled(has_dataset)
        self._insert_column_action.setEnabled(has_dataset)
        self._fill_range_action.setEnabled(has_dataset)
        self._column_metadata_action.setEnabled(has_dataset)
        self._insert_row_action.setEnabled(has_dataset)
        self._resize_sheet_action.setEnabled(has_dataset)
        self._apply_formula_action.setEnabled(has_dataset)
        self._remove_duplicates_action.setEnabled(has_dataset)
        self._derivative_action.setEnabled(has_dataset)
        self._integral_action.setEnabled(has_dataset)
        self._interpolation_action.setEnabled(has_dataset)
        self._fft_action.setEnabled(has_dataset)
        self._ifft_action.setEnabled(has_dataset)
        self._statistics_action.setEnabled(has_dataset)
        self._fit_action.setEnabled(has_dataset)
        self._rename_dataset_button.setEnabled(has_dataset)
        self._duplicate_dataset_button.setEnabled(has_dataset)
        self._remove_dataset_button.setEnabled(has_dataset)
        self._editor_add_row_button.setEnabled(has_dataset)
        self._editor_insert_row_button.setEnabled(has_dataset)
        self._editor_add_column_button.setEnabled(has_dataset)
        self._editor_insert_column_button.setEnabled(has_dataset)
        self._editor_delete_rows_button.setEnabled(has_dataset)
        self._editor_delete_columns_button.setEnabled(has_dataset)
        self._editor_resize_sheet_button.setEnabled(has_dataset)
        self._editor_rename_button.setEnabled(has_dataset)
        self._editor_remove_button.setEnabled(has_dataset)
        self._editor_export_button.setEnabled(has_dataset)
        self._editor_fill_range_button.setEnabled(has_dataset)
        self._editor_metadata_button.setEnabled(has_dataset)
        for button in getattr(self, "_data_prep_buttons", []):
            button.setEnabled(has_dataset)
        for button in getattr(self, "_analysis_buttons", []):
            button.setEnabled(has_dataset)
        self._undo_action.setEnabled(self._dataset_model.can_undo())
        self._redo_action.setEnabled(self._dataset_model.can_redo())
        self._save_project_action.setEnabled(has_project_content)
        self._save_project_as_action.setEnabled(has_project_content)
        self._close_project_action.setEnabled(has_project_content)
        self._update_plot_action_state()

    def _handle_dataset_history_changed(self) -> None:
        """Refresh history/action state without rescanning the worksheet."""
        if hasattr(self, "_undo_action"):
            self._update_dataset_summary()

    def _handle_dataset_columns_renamed(self, rename_map: dict[str, str]) -> None:
        """Retarget plots after undo/redo restores renamed dataset columns."""
        dataset = self._dataset_model.dataset
        if dataset is None or not rename_map:
            return
        self._workspace.rename_column_references_in_plots(dataset.name, rename_map)
        self._plot_tab_widget.rename_column_references(dataset.name, rename_map)

    def _handle_dataset_edit_rejected(self, message: str) -> None:
        """Show a visible reason when column typing rejects a cell edit."""
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "Cell Edit Rejected", message)

    def _undo_dataset_edit(self) -> None:
        """Undo the most recent editable dataset operation."""
        if not self._dataset_model.undo():
            return
        dataset = self._dataset_model.dataset
        if dataset is not None:
            self._resize_dataset_columns_to_contents(dataset)
            self._plot_tab_widget.refresh_controls(dataset.name)
            self._update_dataset_summary()
        self.statusBar().showMessage("Undid dataset edit")

    def _redo_dataset_edit(self) -> None:
        """Redo the most recently undone dataset operation."""
        if not self._dataset_model.redo():
            return
        dataset = self._dataset_model.dataset
        if dataset is not None:
            self._resize_dataset_columns_to_contents(dataset)
            self._plot_tab_widget.refresh_controls(dataset.name)
            self._update_dataset_summary()
        self.statusBar().showMessage("Redid dataset edit")

    def _set_sidebar_visible(self, visible: bool) -> None:
        """Show or hide the workspace navigator dock."""
        self._workspace_dock.setVisible(visible)
        if hasattr(self, "_show_sidebar_action"):
            self._sync_checkable_action(self._show_sidebar_action, visible)

    def _sync_inspector_to_current_tab(self, _index: int | None = None) -> None:
        """Show plot controls on Plot and maximize worksheet space on Data."""
        if not hasattr(self, "_inspector_stack"):
            return

        if self._tabs.currentWidget() is self._plot_tab_widget:
            self._inspector_stack.setCurrentWidget(self._plot_inspector)
            self._inspector_dock.setWindowTitle("Plot Inspector")
            self._plot_tab_widget.set_plot_options_visible(self._plot_inspector_enabled)
            self._inspector_dock.setVisible(self._plot_inspector_enabled)
        else:
            self._inspector_dock.setVisible(False)
        self._sync_plot_options_action(self._plot_inspector_enabled)

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
        self._plot_inspector_enabled = visible
        self._plot_tab_widget.set_plot_options_visible(visible)
        self._inspector_dock.setVisible(
            visible and self._tabs.currentWidget() is self._plot_tab_widget
        )

    def _handle_plot_options_visibility_changed(self, visible: bool) -> None:
        """Apply plot-tab option visibility to the external inspector dock."""
        self._plot_inspector_enabled = visible
        if self._tabs.currentWidget() is self._plot_tab_widget:
            self._inspector_dock.setVisible(visible)
        self._sync_plot_options_action(visible)

    def _handle_inspector_dock_visibility_changed(self, visible: bool) -> None:
        """Treat manual dock closing as a plot-inspector preference only on Plot."""
        if self._tabs.currentWidget() is not self._plot_tab_widget:
            return
        self._plot_inspector_enabled = visible
        self._plot_tab_widget.set_plot_options_visible(visible)
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
        self._plot_inspector_enabled = True
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
            metadata = dataset.column_metadata.get(column_name)
            if metadata is not None and metadata.value_type == "text":
                continue
            values = pd.to_numeric(dataset.frame[column], errors="coerce")
            if metadata is not None and metadata.value_type in COLUMN_NUMERIC_TYPES:
                source_values = dataset.frame[column]
                meaningful = source_values.notna() & (source_values.astype(str).str.strip() != "")
                if (meaningful & values.isna()).any():
                    continue
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
                value_type=source_metadata.value_type,
                display_precision=source_metadata.display_precision,
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
            value_type=value_metadata.value_type,
            display_precision=value_metadata.display_precision,
        )
        result_dataset.sync_column_metadata_attrs()

    def _selected_dataset_columns(self) -> list[int]:
        """Return sorted column indexes touched by the table selection."""
        selection_model = self._dataset_table.selectionModel()
        if selection_model is None:
            return []
        columns: set[int] = set()
        for selection_range in selection_model.selection():
            columns.update(range(selection_range.left(), selection_range.right() + 1))
        return sorted(columns)

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
            self._active_plot_name = None
            self._active_plot_baseline = None
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
        self._active_plot_name = None
        self._active_plot_baseline = None
        self._plot_tab_widget.set_workspace(self._workspace)
        self._refresh_dataset_list()
        self._refresh_plot_list()
        self._tabs.setCurrentIndex(0)
        self._set_project_window_title()
        self.statusBar().showMessage("Closed project")

    def _show_dataset_context_menu(self, pos) -> None:
        """Show common worksheet operations for a sidebar item."""
        item = self._dataset_list.itemAt(pos)
        if not item:
            return

        self._dataset_list.setCurrentItem(item)
        dataset_name = item.text()
        menu, actions = self._build_dataset_context_menu()
        action = menu.exec(self._dataset_list.mapToGlobal(pos))
        if action == actions["open"]:
            self._show_dataset_editor(dataset_name)
        elif action == actions["plot"]:
            self._start_plot_for_current_dataset()
        elif action == actions["export"]:
            self._export_current_dataset()
        elif action == actions["duplicate"]:
            self._duplicate_dataset(dataset_name)
        elif action == actions["rename"]:
            self._rename_dataset(dataset_name)
        elif action == actions["remove"]:
            self._delete_dataset(dataset_name)

    def _build_dataset_context_menu(self) -> tuple[QMenu, dict[str, object]]:
        """Build the workspace-dataset context menu and its named actions."""
        menu = QMenu(self)
        open_action = menu.addAction("Open Sheet")
        plot_action = menu.addAction("Create Plot from Dataset")
        export_action = menu.addAction("Export Dataset...")
        self._add_dataset_workflow_submenus(menu)
        menu.addSeparator()
        duplicate_action = menu.addAction("Duplicate Sheet")
        rename_action = menu.addAction("Rename...")
        delete_action = menu.addAction("Remove Dataset")
        return menu, {
            "open": open_action,
            "plot": plot_action,
            "export": export_action,
            "duplicate": duplicate_action,
            "rename": rename_action,
            "remove": delete_action,
        }

    def _start_plot_for_current_dataset(self) -> None:
        """Start a new plot draft with mappings prefilled from the current dataset."""
        dataset = self._current_dataset()
        if dataset is None or not self._start_new_plot():
            return
        self._plot_tab_widget.refresh_controls(dataset.name)
        self.statusBar().showMessage(
            f"New plot ready for '{dataset.name}'; choose a subtype and click Add Series"
        )

    def _refresh_plot_list(self, selected_name: str | None = None) -> None:
        """Refresh saved plot navigation and optionally reselect one plot."""
        plot_names = self._workspace.plot_names()
        target_name = selected_name if selected_name in plot_names else self._active_plot_name
        if target_name not in plot_names:
            target_name = None

        self._plot_list.blockSignals(True)
        self._plot_list.clear()
        empty_item = QListWidgetItem("New / Empty Plot")
        empty_item.setData(Qt.UserRole, None)
        self._plot_list.addItem(empty_item)
        for plot_name in plot_names:
            item = QListWidgetItem(plot_name)
            item.setData(Qt.UserRole, plot_name)
            self._plot_list.addItem(item)

        if target_name:
            for row in range(self._plot_list.count()):
                item = self._plot_list.item(row)
                if item.data(Qt.UserRole) == target_name:
                    self._plot_list.setCurrentItem(item)
                    break
        else:
            self._plot_list.setCurrentItem(empty_item)
        self._plot_list.blockSignals(False)
        self._update_plot_action_state()

    def _current_plot_name(self) -> str | None:
        """Return the saved plot currently loaded in the editor, if any."""
        return self._active_plot_name

    def _selected_plot_name(self) -> str | None:
        """Return the saved plot selected in the navigator, if any."""
        current_item = self._plot_list.currentItem()
        if current_item is None:
            return None
        value = current_item.data(Qt.UserRole)
        return str(value) if isinstance(value, str) and value else None

    def _handle_saved_plot_selection(
        self,
        current_item: QListWidgetItem | None,
        _previous_item: QListWidgetItem | None,
    ) -> None:
        """Load a saved plot or start the selected empty plot draft."""
        plot_name = None if current_item is None else current_item.data(Qt.UserRole)
        if isinstance(plot_name, str) and plot_name:
            if not self._confirm_plot_replacement():
                self._restore_active_plot_selection()
                return
            self._load_plot_by_name(plot_name, show_message=False)
        else:
            self._start_new_plot(update_selection=False)

    def _start_new_plot(
        self,
        _checked: bool = False,
        update_selection: bool = True,
        confirm_replacement: bool = True,
    ) -> bool:
        """Detach from any saved definition and display a fresh empty plot."""
        if confirm_replacement and not self._confirm_plot_replacement():
            self._restore_active_plot_selection()
            return False
        self._active_plot_name = None
        self._active_plot_baseline = None
        self._plot_tab_widget.reset_plot_draft()
        if update_selection and self._plot_list.count():
            self._plot_list.blockSignals(True)
            self._plot_list.setCurrentRow(0)
            self._plot_list.blockSignals(False)
        self._tabs.setCurrentWidget(self._plot_tab_widget)
        self._update_plot_action_state()
        self.statusBar().showMessage("Started a new empty plot")
        return True

    def _plot_has_unsaved_changes(self) -> bool:
        """Return whether replacing the editor would discard an unsaved definition."""
        if not self._plot_tab_widget.has_plot_series():
            return False
        if self._plot_tab_widget.has_unapplied_series_edits():
            return True
        if self._active_plot_baseline is None:
            return True
        return self._plot_state_fingerprint() != self._active_plot_baseline

    def _confirm_plot_replacement(self) -> bool:
        """Offer Save, Discard, and Cancel before replacing unsaved plot work."""
        if not self._plot_has_unsaved_changes():
            return True
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Warning)
        message.setWindowTitle("Unsaved Plot")
        message.setText("The current plot has unsaved changes.")
        message.setInformativeText("Save it before replacing the plot?")
        message.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        message.setDefaultButton(QMessageBox.Save)
        choice = message.exec()
        if choice == QMessageBox.Save:
            return self._save_current_plot()
        return choice == QMessageBox.Discard

    def _plot_state_fingerprint(self) -> str:
        """Return a stable JSON representation of the editable plot state."""
        return json.dumps(
            self._plot_tab_widget.current_plot_state(),
            sort_keys=True,
            separators=(",", ":"),
        )

    def _restore_active_plot_selection(self) -> None:
        """Restore navigator selection after a replacement prompt is canceled."""
        self._plot_list.blockSignals(True)
        target_row = 0
        if self._active_plot_name is not None:
            for row in range(self._plot_list.count()):
                if self._plot_list.item(row).data(Qt.UserRole) == self._active_plot_name:
                    target_row = row
                    break
        if self._plot_list.count():
            self._plot_list.setCurrentRow(target_row)
        self._plot_list.blockSignals(False)

    def _mark_plot_as_unsaved(self) -> None:
        """Detach an analysis-generated plot from a previously loaded saved plot."""
        self._active_plot_name = None
        self._active_plot_baseline = None
        if self._plot_list.count():
            self._plot_list.blockSignals(True)
            self._plot_list.setCurrentRow(0)
            self._plot_list.blockSignals(False)
        self._update_plot_action_state()

    def _save_current_plot(self) -> bool:
        """Save or overwrite the current plot definition in the workspace."""
        if not self._plot_tab_widget.has_plot_series():
            QMessageBox.information(self, "Save Plot", "Create a plot before saving it.")
            return False
        if self._plot_tab_widget.has_unapplied_series_edits():
            QMessageBox.information(
                self,
                "Unapplied Series Edits",
                "Click Update Series to keep the staged edits, or Revert Edits to discard them, before saving.",
            )
            return False

        selected_name = self._active_plot_name
        default_name = selected_name or self._plot_tab_widget.suggested_plot_name()
        plot_name, accepted = QInputDialog.getText(
            self,
            "Save Plot",
            "Plot name:",
            text=default_name,
        )
        if not accepted:
            return False

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
                    return False
                saved_plot = self._workspace.update_plot(clean_name, state)
            else:
                saved_plot = self._workspace.add_plot(clean_name, state)
        except Exception as exc:
            QMessageBox.critical(self, "Save Plot Failed", str(exc))
            return False

        self._active_plot_name = saved_plot.name
        self._active_plot_baseline = self._plot_state_fingerprint()
        self._refresh_plot_list(saved_plot.name)
        self.statusBar().showMessage(f"Saved plot '{saved_plot.name}'")
        return True

    def _load_selected_plot(self) -> None:
        """Load the currently selected saved plot with user feedback."""
        plot_name = self._selected_plot_name()
        if plot_name is None:
            QMessageBox.information(self, "Load Plot", "Select a saved plot before loading it.")
            return

        if plot_name != self._active_plot_name and not self._confirm_plot_replacement():
            self._restore_active_plot_selection()
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

        self._active_plot_name = saved_plot.name
        self._active_plot_baseline = self._plot_state_fingerprint()
        self._tabs.setCurrentWidget(self._plot_tab_widget)
        self._update_plot_action_state()
        if show_message:
            self.statusBar().showMessage(f"Loaded plot '{plot_name}'")
        else:
            self.statusBar().showMessage(f"Selected saved plot '{plot_name}' for editing")

    def _duplicate_selected_plot(self) -> None:
        """Duplicate the selected saved plot and load the independent copy."""
        plot_name = self._selected_plot_name()
        if plot_name is None:
            QMessageBox.information(
                self, "Duplicate Plot", "Select a saved plot before duplicating it."
            )
            return
        if not self._confirm_plot_replacement():
            self._restore_active_plot_selection()
            return
        try:
            duplicate = self._workspace.duplicate_plot(plot_name)
        except Exception as exc:
            QMessageBox.critical(self, "Duplicate Plot Failed", str(exc))
            return
        self._refresh_plot_list(duplicate.name)
        self._load_plot_by_name(duplicate.name, show_message=False)
        self.statusBar().showMessage(
            f"Duplicated plot '{plot_name}' as '{duplicate.name}'"
        )

    def _delete_selected_plot(self) -> None:
        """Remove the currently selected saved plot from the workspace."""
        plot_name = self._selected_plot_name()
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

        if self._active_plot_name == plot_name:
            self._active_plot_name = None
            self._active_plot_baseline = None
            self._plot_tab_widget.reset_plot_draft()
        self._refresh_plot_list()
        self.statusBar().showMessage(f"Removed plot '{plot_name}'")

    def _show_plot_context_menu(self, pos) -> None:
        """Show common saved-plot operations for a sidebar item."""
        item = self._plot_list.itemAt(pos)
        if not item:
            return
        self._plot_list.blockSignals(True)
        self._plot_list.setCurrentItem(item)
        self._plot_list.blockSignals(False)
        self._update_plot_action_state()

        plot_name = item.data(Qt.UserRole)
        menu, actions = self._build_plot_context_menu(plot_name)
        action = menu.exec(self._plot_list.mapToGlobal(pos))
        if action == actions["new"]:
            self._start_new_plot()
        elif action == actions["save"]:
            self._save_current_plot()
        elif action == actions["load"]:
            self._load_selected_plot()
        elif action == actions["duplicate"]:
            self._duplicate_selected_plot()
        elif action == actions["remove"]:
            self._delete_selected_plot()

    def _build_plot_context_menu(self, plot_name: object) -> tuple[QMenu, dict[str, object]]:
        """Build the saved-plot context menu and its named actions."""
        menu = QMenu(self)
        new_action = menu.addAction("New Empty Plot")
        save_action = menu.addAction("Save Current Plot...")
        save_action.setEnabled(self._plot_tab_widget.has_plot_series())
        menu.addSeparator()
        load_action = menu.addAction("Load Plot")
        load_action.setEnabled(isinstance(plot_name, str) and bool(plot_name))
        duplicate_action = menu.addAction("Duplicate Saved Plot")
        duplicate_action.setEnabled(isinstance(plot_name, str) and bool(plot_name))
        delete_action = menu.addAction("Remove Saved Plot")
        delete_action.setEnabled(isinstance(plot_name, str) and bool(plot_name))
        return menu, {
            "new": new_action,
            "save": save_action,
            "load": load_action,
            "duplicate": duplicate_action,
            "remove": delete_action,
        }

    def _update_plot_action_state(self) -> None:
        """Update plot menu and header action enabled states."""
        selected_plot_name = self._selected_plot_name()
        has_saved_plot = selected_plot_name is not None
        has_current_plot = self._plot_tab_widget.has_plot_series()

        if hasattr(self, "_save_plot_action"):
            self._save_plot_action.setEnabled(has_current_plot)
            self._copy_plot_action.setEnabled(has_current_plot)
            self._load_plot_action.setEnabled(has_saved_plot)
            self._duplicate_plot_action.setEnabled(has_saved_plot)
            self._delete_plot_action.setEnabled(has_saved_plot)

        self._duplicate_plot_button.setEnabled(has_saved_plot)

        self._plot_tab_widget.set_plot_actions_enabled(
            can_save=has_current_plot,
            can_load=has_saved_plot,
            can_remove=has_saved_plot,
        )
        self._plot_tab_widget.set_active_plot_name(self._active_plot_name)

    def _rename_dataset(self, old_name: str) -> None:
        """Prompt for and apply a dataset rename."""
        new_name, ok = QInputDialog.getText(self, "Rename Dataset", "New name:", text=old_name)
        if ok and new_name and new_name != old_name:
            try:
                final_name = self._workspace.rename_dataset(old_name, new_name)
                self._plot_tab_widget.clear_plot_state()
                self._active_plot_name = None
                self._active_plot_baseline = None
                self._refresh_plot_list()
                self._refresh_dataset_list(final_name)
                self.statusBar().showMessage(f"Renamed '{old_name}' to '{final_name}'")
            except Exception as exc:
                QMessageBox.critical(self, "Rename Failed", str(exc))

    def _duplicate_dataset(self, name: str) -> None:
        """Duplicate a named worksheet and open the independent copy."""
        try:
            duplicate = self._workspace.duplicate_dataset(name)
        except Exception as exc:
            QMessageBox.critical(self, "Duplicate Sheet Failed", str(exc))
            return
        self._refresh_dataset_list(duplicate.name)
        self.statusBar().showMessage(
            f"Duplicated sheet '{name}' as '{duplicate.name}'"
        )

    def _duplicate_current_dataset(self) -> None:
        """Duplicate the worksheet currently selected in the workspace."""
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(
                self, "Duplicate Sheet", "Select a dataset before duplicating it."
            )
            return
        self._duplicate_dataset(dataset.name)

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
                self._active_plot_name = None
                self._active_plot_baseline = None
                self._refresh_dataset_list()
                self._refresh_plot_list()
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
