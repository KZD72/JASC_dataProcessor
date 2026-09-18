"""Application dialogs."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from html import escape

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
    QVBoxLayout,
)
from scipy import ndimage, signal

from core.color_scale import ColorScaleCalibration
from core.file_io import ExcelWorkbookInspection, ImportOptions
from core.workspace import (
    COLUMN_ROLE_OPTIONS,
    COLUMN_TYPE_OPTIONS,
    ColumnMetadata,
    column_role_label,
    normalize_display_precision,
)
from math_engine.curve_fitting import FIT_METHODS
from math_engine.calculus import DERIVATIVE_METHODS, INTEGRATION_METHODS, WINDOW_METHODS
from math_engine.interpolation import (
    FILL_POLICIES,
    INTERPOLATION_METHODS,
    MAX_GENERATED_QUERY_POINTS,
)
from math_engine.smoothing import (
    DERIVATIVE_SMOOTHING_METHODS,
    SMOOTHING_METHODS,
    SmoothingParameters,
    smooth_values,
)
from math_engine.statistics import STATISTIC_OPERATIONS
from models.fit_functions import (
    CustomFitModel,
    available_fit_models,
    create_custom_fit_model,
    get_fit_model,
)

BATCH_COLUMN_BINDING_NAME = "name"
BATCH_COLUMN_BINDING_POSITION = "position"
FILTER_OPERATOR_OPTIONS: tuple[tuple[str, str], ...] = (
    ("eq", "Equals"),
    ("ne", "Does not equal"),
    ("gt", ">"),
    ("ge", ">="),
    ("lt", "<"),
    ("le", "<="),
    ("between", "Between"),
    ("contains", "Contains"),
    ("starts", "Starts with"),
    ("in", "In comma-separated list"),
    ("blank", "Is blank"),
    ("not_blank", "Is not blank"),
)
MISSING_VALUE_STRATEGIES: tuple[tuple[str, str], ...] = (
    ("drop_rows", "Drop rows with blanks"),
    ("fill_value", "Fill with value"),
    ("fill_mean", "Fill numeric with mean"),
    ("fill_median", "Fill numeric with median"),
    ("interpolate", "Interpolate numeric"),
)
GROUP_AGGREGATIONS: tuple[tuple[str, str], ...] = (
    ("count", "Count"),
    ("mean", "Mean"),
    ("std", "Std. deviation"),
    ("sem", "Std. error"),
    ("min", "Minimum"),
    ("max", "Maximum"),
    ("sum", "Sum"),
)


def batch_column_binding_combo() -> QComboBox:
    """Return the shared batch column matching selector."""
    combo = QComboBox()
    combo.addItem("By exact column name", BATCH_COLUMN_BINDING_NAME)
    combo.addItem("By column position", BATCH_COLUMN_BINDING_POSITION)
    combo.setToolTip(
        "Name matching looks for the same column names in each sheet. "
        "Position matching maps selected columns by their col1, col2, ... positions."
    )
    return combo


def selected_list_items(widget: QListWidget) -> list[str]:
    """Return selected list item texts in visual order."""
    return [
        widget.item(row).text()
        for row in range(widget.count())
        if widget.item(row).isSelected()
    ]


def select_list_items(widget: QListWidget, items: list[str]) -> None:
    """Select list items whose text appears in items."""
    wanted = set(items)
    for row in range(widget.count()):
        item = widget.item(row)
        item.setSelected(item.text() in wanted)


class DataFilterDialog(QDialog):
    """Collect settings for a first-pass Data Prep filter/query operation."""

    def __init__(
        self,
        dataset_columns: dict[str, list[str]],
        default_dataset_name: str,
        parent: QWidget | None = None,
    ) -> None:
        """Create a filter dialog for one selected worksheet."""
        super().__init__(parent)
        self.setWindowTitle("Filter / Query")
        self.setModal(True)
        self.resize(520, 260)
        self._dataset_columns = dataset_columns

        self._dataset_combo = QComboBox()
        self._dataset_combo.addItems(dataset_columns.keys())
        if default_dataset_name in dataset_columns:
            self._dataset_combo.setCurrentText(default_dataset_name)

        self._column_combo = QComboBox()
        self._operator_combo = QComboBox()
        for operator_key, operator_label in FILTER_OPERATOR_OPTIONS:
            self._operator_combo.addItem(operator_label, operator_key)

        self._value_edit = QLineEdit()
        self._value_edit.setPlaceholderText("Text, number, list, or range minimum")
        self._value2_edit = QLineEdit()
        self._value2_edit.setPlaceholderText("Range maximum")
        self._output_edit = QLineEdit()

        self._dataset_combo.currentTextChanged.connect(self._refresh_columns)
        self._operator_combo.currentIndexChanged.connect(lambda _index: self._sync_value_enabled())
        self._refresh_columns(self._dataset_combo.currentText())
        self._sync_value_enabled()

        form = QFormLayout()
        form.addRow("Dataset", self._dataset_combo)
        form.addRow("Column", self._column_combo)
        form.addRow("Condition", self._operator_combo)
        form.addRow("Value", self._value_edit)
        form.addRow("Second value", self._value2_edit)
        form.addRow("Output sheet", self._output_edit)

        hint = QLabel(
            "Creates a filtered copy of the selected sheet. "
            "Multiple-condition query builders, in-place filtering, and batch filtering are planned next."
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def dataset_name(self) -> str:
        """Return the selected source dataset name."""
        return self._dataset_combo.currentText().strip()

    def column_name(self) -> str:
        """Return the selected source column name."""
        return self._column_combo.currentText().strip()

    def operator_key(self) -> str:
        """Return the selected filter operator key."""
        return str(self._operator_combo.currentData() or "")

    def value_text(self) -> str:
        """Return the comparison value text."""
        return self._value_edit.text().strip()

    def value2_text(self) -> str:
        """Return the optional second comparison value text."""
        return self._value2_edit.text().strip()

    def output_name(self) -> str:
        """Return the requested output sheet name."""
        return self._output_edit.text().strip()

    def accept(self) -> None:
        """Validate required fields before accepting."""
        if not self.dataset_name():
            QMessageBox.warning(self, "Filter / Query", "Choose a dataset.")
            return
        if not self.column_name():
            QMessageBox.warning(self, "Filter / Query", "Choose a column.")
            return
        if self.operator_key() not in {"blank", "not_blank"} and not self.value_text():
            QMessageBox.warning(self, "Filter / Query", "Enter a comparison value.")
            return
        if self.operator_key() == "between" and not self.value2_text():
            QMessageBox.warning(self, "Filter / Query", "Enter the second range value.")
            return
        if not self.output_name():
            QMessageBox.warning(self, "Filter / Query", "Enter an output sheet name.")
            return
        super().accept()

    def _refresh_columns(self, dataset_name: str) -> None:
        """Refresh column choices and default output name for the selected dataset."""
        columns = self._dataset_columns.get(dataset_name, [])
        current = self._column_combo.currentText()
        self._column_combo.clear()
        self._column_combo.addItems(columns)
        if current in columns:
            self._column_combo.setCurrentText(current)
        if dataset_name:
            self._output_edit.setText(f"{dataset_name}_filtered")

    def _sync_value_enabled(self) -> None:
        """Disable the value field for blank/not-blank operators."""
        needs_value = self.operator_key() not in {"blank", "not_blank"}
        self._value_edit.setEnabled(needs_value)
        self._value2_edit.setEnabled(self.operator_key() == "between")
        if not needs_value:
            self._value_edit.clear()
        if self.operator_key() != "between":
            self._value2_edit.clear()


class DataSortDialog(QDialog):
    """Collect settings for sorting a dataset into a new sheet."""

    def __init__(self, column_names: list[str], default_output_name: str, parent: QWidget | None = None) -> None:
        """Create sort controls."""
        super().__init__(parent)
        self.setWindowTitle("Sort")
        self.setModal(True)
        self.resize(460, 360)
        self._column_list = QListWidget()
        self._column_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._column_list.addItems(column_names)
        if column_names:
            self._column_list.item(0).setSelected(True)
        self._order_combo = QComboBox()
        self._order_combo.addItem("Ascending", True)
        self._order_combo.addItem("Descending", False)
        self._output_edit = QLineEdit(default_output_name)

        form = QFormLayout()
        form.addRow("Order", self._order_combo)
        form.addRow("Output sheet", self._output_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Sort by selected columns in their worksheet order."))
        layout.addWidget(self._column_list)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def selected_columns(self) -> list[str]:
        """Return selected sort columns."""
        return selected_list_items(self._column_list)

    def ascending(self) -> bool:
        """Return whether sorting is ascending."""
        return bool(self._order_combo.currentData())

    def output_name(self) -> str:
        """Return requested output sheet name."""
        return self._output_edit.text().strip()

    def accept(self) -> None:
        """Validate sort settings."""
        if not self.selected_columns():
            QMessageBox.warning(self, "Sort", "Choose at least one sort column.")
            return
        if not self.output_name():
            QMessageBox.warning(self, "Sort", "Enter an output sheet name.")
            return
        super().accept()


class RemoveDuplicatesDialog(QDialog):
    """Choose duplicate-key columns and which matching row to retain."""

    def __init__(
        self,
        column_names: list[str],
        default_output_name: str,
        parent: QWidget | None = None,
    ) -> None:
        """Build duplicate-removal controls with all columns selected by default."""
        super().__init__(parent)
        self.setWindowTitle("Remove Duplicates")
        self.setModal(True)
        self.setMinimumWidth(430)

        self._columns_list = QListWidget()
        self._columns_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._columns_list.addItems(column_names)
        for row in range(self._columns_list.count()):
            self._columns_list.item(row).setSelected(True)

        self._keep_combo = QComboBox()
        self._keep_combo.addItem("Keep first occurrence", "first")
        self._keep_combo.addItem("Keep last occurrence", "last")
        self._keep_combo.addItem("Remove every row in a duplicate group", "none")
        self._output_name_edit = QLineEdit(default_output_name)

        hint = QLabel(
            "Rows are duplicates when all selected columns match. Blank/NaN values in the "
            "same selected columns are treated as matching values."
        )
        hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Match columns", self._columns_list)
        form.addRow("Duplicate policy", self._keep_combo)
        form.addRow("Output sheet", self._output_name_edit)
        form.addRow("", hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def columns(self) -> list[str]:
        """Return columns used to determine duplicate groups."""
        return selected_list_items(self._columns_list)

    def keep_policy(self) -> str:
        """Return first, last, or none."""
        return str(self._keep_combo.currentData() or "first")

    def output_name(self) -> str:
        """Return the requested result-sheet name."""
        return self._output_name_edit.text().strip()

    def accept(self) -> None:
        """Require columns and an output name."""
        if not self.columns():
            QMessageBox.warning(self, "Remove Duplicates", "Choose at least one match column.")
            return
        if not self.output_name():
            QMessageBox.warning(self, "Remove Duplicates", "Enter an output sheet name.")
            return
        super().accept()


class MissingValuesDialog(QDialog):
    """Collect settings for missing-value cleanup."""

    def __init__(self, column_names: list[str], default_output_name: str, parent: QWidget | None = None) -> None:
        """Create missing-value cleanup controls."""
        super().__init__(parent)
        self.setWindowTitle("Missing Values")
        self.setModal(True)
        self.resize(480, 380)
        self._column_list = QListWidget()
        self._column_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._column_list.addItems(column_names)
        for row in range(self._column_list.count()):
            self._column_list.item(row).setSelected(True)
        self._strategy_combo = QComboBox()
        for key, label in MISSING_VALUE_STRATEGIES:
            self._strategy_combo.addItem(label, key)
        self._fill_value_edit = QLineEdit()
        self._fill_value_edit.setPlaceholderText("Value used by 'Fill with value'")
        self._output_edit = QLineEdit(default_output_name)
        self._strategy_combo.currentIndexChanged.connect(lambda _index: self._sync_fill_value_enabled())
        self._sync_fill_value_enabled()

        form = QFormLayout()
        form.addRow("Strategy", self._strategy_combo)
        form.addRow("Fill value", self._fill_value_edit)
        form.addRow("Output sheet", self._output_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Apply missing-value cleanup to the selected columns."))
        layout.addWidget(self._column_list)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def selected_columns(self) -> list[str]:
        """Return selected cleanup columns."""
        return selected_list_items(self._column_list)

    def strategy(self) -> str:
        """Return selected cleanup strategy."""
        return str(self._strategy_combo.currentData() or "")

    def fill_value(self) -> str:
        """Return literal fill value."""
        return self._fill_value_edit.text()

    def output_name(self) -> str:
        """Return requested output sheet name."""
        return self._output_edit.text().strip()

    def accept(self) -> None:
        """Validate cleanup settings."""
        if not self.selected_columns():
            QMessageBox.warning(self, "Missing Values", "Choose at least one column.")
            return
        if self.strategy() == "fill_value" and self.fill_value() == "":
            QMessageBox.warning(self, "Missing Values", "Enter a fill value.")
            return
        if not self.output_name():
            QMessageBox.warning(self, "Missing Values", "Enter an output sheet name.")
            return
        super().accept()

    def _sync_fill_value_enabled(self) -> None:
        """Enable fill-value field only for literal fill mode."""
        self._fill_value_edit.setEnabled(self.strategy() == "fill_value")


class GroupAggregateDialog(QDialog):
    """Collect settings for grouped aggregation."""

    def __init__(self, column_names: list[str], default_output_name: str, parent: QWidget | None = None) -> None:
        """Create grouped aggregation controls."""
        super().__init__(parent)
        self.setWindowTitle("Group / Aggregate")
        self.setModal(True)
        self.resize(720, 420)
        self._group_list = QListWidget()
        self._group_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._group_list.addItems(column_names)
        self._value_list = QListWidget()
        self._value_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._value_list.addItems(column_names)
        self._agg_list = QListWidget()
        self._agg_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for key, label in GROUP_AGGREGATIONS:
            self._agg_list.addItem(f"{label} ({key})")
            self._agg_list.item(self._agg_list.count() - 1).setData(Qt.UserRole, key)
        for row in range(self._agg_list.count()):
            key = self._agg_list.item(row).data(Qt.UserRole)
            self._agg_list.item(row).setSelected(key in {"count", "mean", "std"})
        self._output_edit = QLineEdit(default_output_name)

        list_row = QHBoxLayout()
        list_row.addLayout(self._labeled_list("Group columns", self._group_list))
        list_row.addLayout(self._labeled_list("Value columns", self._value_list))
        list_row.addLayout(self._labeled_list("Aggregations", self._agg_list))

        form = QFormLayout()
        form.addRow("Output sheet", self._output_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(list_row)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def group_columns(self) -> list[str]:
        """Return selected group columns."""
        return selected_list_items(self._group_list)

    def value_columns(self) -> list[str]:
        """Return selected numeric value columns."""
        return selected_list_items(self._value_list)

    def aggregations(self) -> list[str]:
        """Return selected aggregation keys."""
        return [
            str(self._agg_list.item(row).data(Qt.UserRole))
            for row in range(self._agg_list.count())
            if self._agg_list.item(row).isSelected()
        ]

    def output_name(self) -> str:
        """Return requested output sheet name."""
        return self._output_edit.text().strip()

    def accept(self) -> None:
        """Validate grouped aggregation settings."""
        if not self.group_columns():
            QMessageBox.warning(self, "Group / Aggregate", "Choose at least one group column.")
            return
        if not self.value_columns():
            QMessageBox.warning(self, "Group / Aggregate", "Choose at least one value column.")
            return
        overlap = sorted(set(self.group_columns()) & set(self.value_columns()))
        if overlap:
            QMessageBox.warning(
                self,
                "Group / Aggregate",
                "Group columns cannot also be value columns: " + ", ".join(overlap),
            )
            return
        if not self.aggregations():
            QMessageBox.warning(self, "Group / Aggregate", "Choose at least one aggregation.")
            return
        if not self.output_name():
            QMessageBox.warning(self, "Group / Aggregate", "Enter an output sheet name.")
            return
        super().accept()

    @staticmethod
    def _labeled_list(label: str, widget: QListWidget) -> QVBoxLayout:
        """Return a labeled list layout."""
        layout = QVBoxLayout()
        layout.addWidget(QLabel(label))
        layout.addWidget(widget)
        return layout


class MergeJoinDialog(QDialog):
    """Collect settings for merging two datasets."""

    def __init__(
        self,
        dataset_columns: dict[str, list[str]],
        default_dataset_name: str,
        parent: QWidget | None = None,
    ) -> None:
        """Create merge/join controls."""
        super().__init__(parent)
        self.setWindowTitle("Merge / Join")
        self.setModal(True)
        self.resize(560, 260)
        self._dataset_columns = dataset_columns
        self._left_dataset_combo = QComboBox()
        self._right_dataset_combo = QComboBox()
        self._left_dataset_combo.addItems(dataset_columns.keys())
        self._right_dataset_combo.addItems(dataset_columns.keys())
        if default_dataset_name in dataset_columns:
            self._left_dataset_combo.setCurrentText(default_dataset_name)
        if len(dataset_columns) > 1:
            for name in dataset_columns:
                if name != self._left_dataset_combo.currentText():
                    self._right_dataset_combo.setCurrentText(name)
                    break
        self._left_key_combo = QComboBox()
        self._right_key_combo = QComboBox()
        self._how_combo = QComboBox()
        for key, label in [("inner", "Inner"), ("left", "Left"), ("right", "Right"), ("outer", "Outer")]:
            self._how_combo.addItem(label, key)
        self._output_edit = QLineEdit(f"{default_dataset_name}_joined")

        self._left_dataset_combo.currentTextChanged.connect(lambda _text: self._refresh_keys())
        self._right_dataset_combo.currentTextChanged.connect(lambda _text: self._refresh_keys())
        self._refresh_keys()

        form = QFormLayout()
        form.addRow("Left dataset", self._left_dataset_combo)
        form.addRow("Left key", self._left_key_combo)
        form.addRow("Right dataset", self._right_dataset_combo)
        form.addRow("Right key", self._right_key_combo)
        form.addRow("Join mode", self._how_combo)
        form.addRow("Output sheet", self._output_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def left_dataset_name(self) -> str:
        """Return selected left dataset name."""
        return self._left_dataset_combo.currentText().strip()

    def right_dataset_name(self) -> str:
        """Return selected right dataset name."""
        return self._right_dataset_combo.currentText().strip()

    def left_key(self) -> str:
        """Return selected left key column."""
        return self._left_key_combo.currentText().strip()

    def right_key(self) -> str:
        """Return selected right key column."""
        return self._right_key_combo.currentText().strip()

    def join_mode(self) -> str:
        """Return selected join mode."""
        return str(self._how_combo.currentData() or "inner")

    def output_name(self) -> str:
        """Return requested output sheet name."""
        return self._output_edit.text().strip()

    def accept(self) -> None:
        """Validate merge settings."""
        if not self.left_dataset_name() or not self.right_dataset_name():
            QMessageBox.warning(self, "Merge / Join", "Choose both datasets.")
            return
        if not self.left_key() or not self.right_key():
            QMessageBox.warning(self, "Merge / Join", "Choose both key columns.")
            return
        if not self.output_name():
            QMessageBox.warning(self, "Merge / Join", "Enter an output sheet name.")
            return
        super().accept()

    def _refresh_keys(self) -> None:
        """Refresh key column combos after dataset changes."""
        left_columns = self._dataset_columns.get(self._left_dataset_combo.currentText(), [])
        right_columns = self._dataset_columns.get(self._right_dataset_combo.currentText(), [])
        self._left_key_combo.clear()
        self._left_key_combo.addItems(left_columns)
        self._right_key_combo.clear()
        self._right_key_combo.addItems(right_columns)


class ReshapeDialog(QDialog):
    """Collect settings for transpose or stack/melt reshaping."""

    def __init__(self, column_names: list[str], default_output_name: str, parent: QWidget | None = None) -> None:
        """Create reshape controls."""
        super().__init__(parent)
        self.setWindowTitle("Reshape")
        self.setModal(True)
        self.resize(640, 420)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Transpose", "transpose")
        self._mode_combo.addItem("Stack selected columns (melt)", "melt")
        self._id_list = QListWidget()
        self._id_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._id_list.addItems(column_names)
        self._value_list = QListWidget()
        self._value_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._value_list.addItems(column_names)
        for row in range(self._value_list.count()):
            self._value_list.item(row).setSelected(True)
        self._output_edit = QLineEdit(default_output_name)

        list_row = QHBoxLayout()
        list_row.addLayout(GroupAggregateDialog._labeled_list("Identifier columns", self._id_list))
        list_row.addLayout(GroupAggregateDialog._labeled_list("Value columns", self._value_list))

        form = QFormLayout()
        form.addRow("Mode", self._mode_combo)
        form.addRow("Output sheet", self._output_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(list_row)
        layout.addWidget(buttons)

    def mode(self) -> str:
        """Return selected reshape mode."""
        return str(self._mode_combo.currentData() or "transpose")

    def id_columns(self) -> list[str]:
        """Return selected identifier columns."""
        return selected_list_items(self._id_list)

    def value_columns(self) -> list[str]:
        """Return selected value columns."""
        return selected_list_items(self._value_list)

    def output_name(self) -> str:
        """Return requested output sheet name."""
        return self._output_edit.text().strip()

    def accept(self) -> None:
        """Validate reshape settings."""
        if self.mode() == "melt" and not self.value_columns():
            QMessageBox.warning(self, "Reshape", "Choose at least one value column to stack.")
            return
        if not self.output_name():
            QMessageBox.warning(self, "Reshape", "Enter an output sheet name.")
            return
        super().accept()


class BinningDialog(QDialog):
    """Collect settings for binned means and dispersion outputs."""

    def __init__(self, column_names: list[str], default_output_name: str, parent: QWidget | None = None) -> None:
        """Create binning controls."""
        super().__init__(parent)
        self.setWindowTitle("Bin / Average")
        self.setModal(True)
        self.resize(520, 420)
        self._bin_column_combo = QComboBox()
        self._bin_column_combo.addItems(column_names)
        self._value_list = QListWidget()
        self._value_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._value_list.addItems(column_names)
        for row in range(self._value_list.count()):
            self._value_list.item(row).setSelected(row > 0)
        self._bin_count_spin = QSpinBox()
        self._bin_count_spin.setRange(1, 10000)
        self._bin_count_spin.setValue(20)
        self._output_edit = QLineEdit(default_output_name)

        form = QFormLayout()
        form.addRow("Bin by", self._bin_column_combo)
        form.addRow("Bin count", self._bin_count_spin)
        form.addRow("Output sheet", self._output_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Value columns"))
        layout.addWidget(self._value_list)
        layout.addWidget(buttons)

    def bin_column(self) -> str:
        """Return selected bin coordinate column."""
        return self._bin_column_combo.currentText().strip()

    def value_columns(self) -> list[str]:
        """Return selected value columns."""
        return selected_list_items(self._value_list)

    def bin_count(self) -> int:
        """Return requested number of bins."""
        return int(self._bin_count_spin.value())

    def output_name(self) -> str:
        """Return requested output sheet name."""
        return self._output_edit.text().strip()

    def accept(self) -> None:
        """Validate binning settings."""
        if not self.bin_column():
            QMessageBox.warning(self, "Bin / Average", "Choose a bin column.")
            return
        if not self.value_columns():
            QMessageBox.warning(self, "Bin / Average", "Choose at least one value column.")
            return
        if self.bin_column() in self.value_columns():
            QMessageBox.warning(self, "Bin / Average", "The bin column should not also be a value column.")
            return
        if not self.output_name():
            QMessageBox.warning(self, "Bin / Average", "Enter an output sheet name.")
            return
        super().accept()


class ImportOptionsDialog(QDialog):
    """Collect delimiter and header settings before importing a text file."""

    _DELIMITERS: tuple[tuple[str, str], ...] = (
        ("Comma (,)", ","),
        ("Semicolon (;)", ";"),
        ("Tab", "\t"),
        ("Space / whitespace", " "),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the delimiter and header-selection controls."""
        super().__init__(parent)
        self.setWindowTitle("Import Options")
        self.setModal(True)

        self._delimiter_combo = QComboBox()
        for label, delimiter in self._DELIMITERS:
            self._delimiter_combo.addItem(label, delimiter)

        self._header_checkbox = QCheckBox("First row contains column names")
        self._header_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow("Delimiter", self._delimiter_combo)
        form.addRow("", self._header_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def options(self) -> ImportOptions:
        """Return the selected parser options."""
        return ImportOptions(
            delimiter=str(self._delimiter_combo.currentData()),
            has_header=self._header_checkbox.isChecked(),
        )


class ExcelImportDialog(QDialog):
    """Select worksheet tabs and acknowledge value-only Excel import limits."""

    def __init__(
        self,
        inspection: ExcelWorkbookInspection,
        parent: QWidget | None = None,
    ) -> None:
        """Build a tab selector from a lightweight OOXML workbook preflight."""
        super().__init__(parent)
        self.setWindowTitle("Import Excel Workbook")
        self.setModal(True)
        self.resize(760, 540)
        self._inspection = inspection

        boundary = QLabel(
            "JASC imports worksheet cell values into normal datasets. Excel charts, pivot "
            "layouts, macros, queries, formatting, controls, and other workbook objects are "
            "not reproduced. Each selected worksheet tab becomes a separate dataset."
        )
        boundary.setWordWrap(True)

        self._selected_sheets_radio = QRadioButton("Choose specific worksheet tabs")
        self._all_sheets_radio = QRadioButton(
            "Import all worksheet tabs (including hidden worksheets)"
        )
        self._selected_sheets_radio.setChecked(True)
        import_scope = QHBoxLayout()
        import_scope.addWidget(self._selected_sheets_radio)
        import_scope.addWidget(self._all_sheets_radio)
        import_scope.addStretch(1)

        self._sheet_table = QTableWidget(len(inspection.sheets), 5)
        self._sheet_table.setHorizontalHeaderLabels(
            ["Import", "Worksheet tab", "Visibility", "Tab type", "Used range"]
        )
        self._sheet_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._sheet_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._sheet_table.verticalHeader().setVisible(False)
        self._sheet_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._sheet_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (2, 3, 4):
            self._sheet_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )

        for row, sheet in enumerate(inspection.sheets):
            import_item = QTableWidgetItem()
            if sheet.is_importable:
                import_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                import_item.setCheckState(Qt.Checked if sheet.state == "visible" else Qt.Unchecked)
            else:
                import_item.setFlags(Qt.NoItemFlags)
            import_item.setData(Qt.UserRole, sheet.name)
            self._sheet_table.setItem(row, 0, import_item)
            self._sheet_table.setItem(row, 1, QTableWidgetItem(sheet.name))
            self._sheet_table.setItem(row, 2, QTableWidgetItem(sheet.state))
            self._sheet_table.setItem(row, 3, QTableWidgetItem(sheet.sheet_type))
            self._sheet_table.setItem(row, 4, QTableWidgetItem(sheet.used_range))
        self._sheet_table.itemChanged.connect(self._sheet_selection_changed)

        select_all_button = QPushButton("Select All Worksheets")
        select_all_button.clicked.connect(lambda: self._set_all_importable_checked(True))
        select_none_button = QPushButton("Select None")
        select_none_button.clicked.connect(lambda: self._set_all_importable_checked(False))
        selection_buttons = QHBoxLayout()
        selection_buttons.addWidget(select_all_button)
        selection_buttons.addWidget(select_none_button)
        selection_buttons.addStretch(1)

        self._header_checkbox = QCheckBox(
            "First row of each selected worksheet contains column names"
        )
        self._header_checkbox.setChecked(True)

        warning_label = QLabel("Workbook compatibility warnings")
        self._warning_text = QPlainTextEdit()
        self._warning_text.setReadOnly(True)
        self._warning_text.setPlainText(
            "\n\n".join(f"• {warning}" for warning in inspection.warnings)
        )
        self._warning_text.setMinimumHeight(150)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(boundary)
        layout.addLayout(import_scope)
        layout.addWidget(self._sheet_table, 1)
        layout.addLayout(selection_buttons)
        layout.addWidget(self._header_checkbox)
        layout.addWidget(warning_label)
        layout.addWidget(self._warning_text)
        layout.addWidget(buttons)

    def selected_sheet_names(self) -> list[str]:
        """Return selected importable worksheet names in workbook order."""
        if self._all_sheets_radio.isChecked():
            return [sheet.name for sheet in self._inspection.sheets if sheet.is_importable]
        selected: list[str] = []
        for row, sheet in enumerate(self._inspection.sheets):
            item = self._sheet_table.item(row, 0)
            if sheet.is_importable and item is not None and item.checkState() == Qt.Checked:
                selected.append(sheet.name)
        return selected

    def import_all_sheets(self) -> bool:
        """Return whether every worksheet tab should be imported."""
        return self._all_sheets_radio.isChecked()

    def has_header(self) -> bool:
        """Return whether the first row should be parsed as column names."""
        return self._header_checkbox.isChecked()

    def _set_all_importable_checked(self, checked: bool) -> None:
        """Check or clear every worksheet row, leaving chart tabs disabled."""
        self._selected_sheets_radio.setChecked(True)
        state = Qt.Checked if checked else Qt.Unchecked
        for row, sheet in enumerate(self._inspection.sheets):
            if not sheet.is_importable:
                continue
            item = self._sheet_table.item(row, 0)
            if item is not None:
                item.setCheckState(state)

    def _sheet_selection_changed(self, item: QTableWidgetItem) -> None:
        """Switch to selective mode when a worksheet checkbox is edited."""
        if item.column() == 0 and bool(item.flags() & Qt.ItemIsUserCheckable):
            self._selected_sheets_radio.setChecked(True)

    def accept(self) -> None:
        """Require at least one worksheet before starting the value import."""
        if not self.selected_sheet_names():
            QMessageBox.warning(
                self,
                "Excel Import",
                "Choose at least one worksheet tab containing data.",
            )
            return
        super().accept()


class BatchPreviewDialog(QDialog):
    """Preview batch jobs before running them."""

    def __init__(
        self,
        title: str,
        rows: list[dict[str, object]],
        columns: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        """Build a read-only table of planned batch jobs."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(920, 520)

        blocked_count = sum(
            1
            for row in rows
            if str(row.get("status", "")).lower() in {"failed", "blocked"}
        )
        ready_count = len(rows) - blocked_count
        summary = QLabel(
            f"{ready_count} job(s) ready, {blocked_count} job(s) will fail or are blocked. "
            "Review the planned mappings and outputs before continuing."
        )
        summary.setWordWrap(True)

        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setRowCount(len(rows))
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels([label for label, _key in columns])
        for row_index, row in enumerate(rows):
            for column_index, (_label, key) in enumerate(columns):
                value = row.get(key, "")
                item = QTableWidgetItem("" if value is None else str(value))
                if str(row.get("status", "")).lower() in {"failed", "blocked"}:
                    item.setToolTip(str(row.get("error", "")))
                table.setItem(row_index, column_index, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Run Batch")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(table)
        layout.addWidget(buttons)


class FigureDigitizerView(QGraphicsView):
    """Graphics view that reports image-coordinate clicks for digitizing."""

    point_clicked = Signal(float, float)
    point_dragged = Signal(float, float)
    point_released = Signal(float, float)
    cursor_moved = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create a zoomable image view."""
        super().__init__(parent)
        self._point_picking_enabled = True
        self.setMouseTracking(True)
        self.setRenderHint(self._render_hint("SmoothPixmapTransform"), True)
        self.setDragMode(self._drag_mode("NoDrag"))
        self.setTransformationAnchor(self._viewport_anchor("AnchorUnderMouse"))
        self.setResizeAnchor(self._viewport_anchor("AnchorUnderMouse"))

    def set_point_picking_enabled(self, enabled: bool) -> None:
        """Enable digitizing clicks or hand-drag panning."""
        self._point_picking_enabled = enabled
        mode = "NoDrag" if enabled else "ScrollHandDrag"
        self.setDragMode(self._drag_mode(mode))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """Emit left-click scene coordinates before normal view handling."""
        if self._point_picking_enabled and event.button() == Qt.LeftButton and self.scene() is not None:
            position = event.position().toPoint() if hasattr(event, "position") else event.pos()
            scene_position = self.mapToScene(position)
            self.point_clicked.emit(float(scene_position.x()), float(scene_position.y()))
            self.cursor_moved.emit(float(scene_position.x()), float(scene_position.y()))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        """Emit image-coordinate movement and drag points for precision tools."""
        if self.scene() is not None:
            position = event.position().toPoint() if hasattr(event, "position") else event.pos()
            scene_position = self.mapToScene(position)
            pixel_x = float(scene_position.x())
            pixel_y = float(scene_position.y())
            self.cursor_moved.emit(pixel_x, pixel_y)
            if self._point_picking_enabled and event.buttons() & Qt.LeftButton:
                self.point_dragged.emit(pixel_x, pixel_y)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        """Emit image-coordinate release points for drag-defined samples."""
        if self._point_picking_enabled and event.button() == Qt.LeftButton and self.scene() is not None:
            position = event.position().toPoint() if hasattr(event, "position") else event.pos()
            scene_position = self.mapToScene(position)
            self.point_released.emit(float(scene_position.x()), float(scene_position.y()))
            self.cursor_moved.emit(float(scene_position.x()), float(scene_position.y()))
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """Zoom around the mouse cursor with the wheel."""
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.scale(factor, factor)

    def zoom_by(self, factor: float) -> None:
        """Apply an explicit zoom factor around the current view anchor."""
        if factor > 0:
            self.scale(factor, factor)

    @staticmethod
    def _render_hint(name: str):
        """Return a QPainter render hint across PySide6 enum styles."""
        render_hint = getattr(QPainter, name, None)
        if render_hint is not None:
            return render_hint
        return getattr(QPainter.RenderHint, name)

    @staticmethod
    def _drag_mode(name: str):
        """Return a QGraphicsView drag mode across PySide6 enum styles."""
        drag_mode = getattr(QGraphicsView, name, None)
        if drag_mode is not None:
            return drag_mode
        return getattr(QGraphicsView.DragMode, name)

    @staticmethod
    def _viewport_anchor(name: str):
        """Return a QGraphicsView viewport anchor across PySide6 enum styles."""
        anchor = getattr(QGraphicsView, name, None)
        if anchor is not None:
            return anchor
        return getattr(QGraphicsView.ViewportAnchor, name)


class FigureExtractionModeDialog(QDialog):
    """Choose how values should be extracted from a raster figure."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the figure-type chooser shown before loading an image."""
        super().__init__(parent)
        self.setWindowTitle("Import From Figure")
        self.setModal(True)
        self.setMinimumWidth(520)

        heading = QLabel("What kind of data does the image contain?")
        heading.setStyleSheet("font-size: 14px; font-weight: 600;")

        self._xy_radio = QRadioButton("XY graph (curves, lines, or symbols)")
        self._xy_radio.setChecked(True)
        xy_hint = QLabel(
            "Calibrate X and Y axes, then extract curve points or marker centres."
        )
        xy_hint.setWordWrap(True)

        self._colorplot_radio = QRadioButton("2D colour plot / heatmap")
        color_hint = QLabel(
            "Calibrate X and Y, sample the displayed colour scale, then click the image "
            "to retrieve estimated X, Y, and colour-mapped values."
        )
        color_hint.setWordWrap(True)

        disclaimer = QLabel(
            "Accuracy notice: colour values are estimates from rendered pixels. Image "
            "compression, anti-aliasing, resizing, overlays, and limited colour resolution "
            "can introduce unavoidable error."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            "QLabel { background: #fff7ed; color: #7c2d12; border: 1px solid #fb923c; "
            "border-radius: 4px; padding: 8px; }"
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Continue")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addSpacing(6)
        layout.addWidget(self._xy_radio)
        layout.addWidget(xy_hint)
        layout.addSpacing(8)
        layout.addWidget(self._colorplot_radio)
        layout.addWidget(color_hint)
        layout.addSpacing(10)
        layout.addWidget(disclaimer)
        layout.addWidget(buttons)

    def extraction_mode(self) -> str:
        """Return ``xy`` or ``colorplot`` for the selected workflow."""
        return "colorplot" if self._colorplot_radio.isChecked() else "xy"


@dataclass(frozen=True, slots=True)
class FigureExtractionResult:
    """One saved curve/probe set from a multi-extraction figure session."""

    dataset_name: str
    rows: tuple[dict[str, object], ...]
    source_path: str
    extraction_kind: str
    calibration_summary: str
    extraction_summary: str


class FigureDigitizerDialog(QDialog):
    """Import a raster figure and extract calibrated XY data from it."""

    _IMAGE_FILTER = (
        "Image Files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif);;"
        "PNG Files (*.png);;JPEG Files (*.jpg *.jpeg);;TIFF Files (*.tif *.tiff);;"
        "Bitmap Files (*.bmp);;All Files (*)"
    )
    _CALIBRATION_KEYS: tuple[tuple[str, str], ...] = (
        ("x1", "X axis point 1"),
        ("x2", "X axis point 2"),
        ("y1", "Y axis point 1"),
        ("y2", "Y axis point 2"),
    )
    _WARP_KEYS: tuple[tuple[str, str], ...] = (
        ("warp_tl", "Correction top-left"),
        ("warp_tr", "Correction top-right"),
        ("warp_br", "Correction bottom-right"),
        ("warp_bl", "Correction bottom-left"),
    )

    def __init__(
        self,
        image_path: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the figure digitizer workspace."""
        super().__init__(parent)
        self.setWindowTitle("Import From Figure")
        self.setModal(True)
        self.resize(1180, 680)

        self._image_path = ""
        self._original_image = QImage()
        self._image = QImage()
        self._scene = QGraphicsScene(self)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._marker_items: list[object] = []
        self._warp_pixels: dict[str, tuple[float, float]] = {}
        self._warp_applied = False
        self._calibration_pixels: dict[str, tuple[float, float]] = {}
        self._manual_points: list[dict[str, object]] = []
        self._manual_error_samples: list[tuple[float, float]] = []
        self._manual_error_target_index: int | None = None
        self._manual_target_spin: QSpinBox | None = None
        self._auto_points: list[tuple[float, float]] = []
        self._symbol_points: list[dict[str, object]] = []
        self._roi_points: list[tuple[float, float, float]] = []
        self._cursor_pixel: tuple[float, float] | None = None
        self._trace_color = QColor("#000000")
        self._symbol_sample_start: tuple[float, float] | None = None
        self._symbol_sample_preview_rect: tuple[int, int, int, int] | None = None
        self._symbol_template_rect: tuple[int, int, int, int] | None = None
        self._symbol_template_weights: np.ndarray | None = None
        self._symbol_template_mask: np.ndarray | None = None
        self._symbol_template_color: tuple[float, float, float] | None = None
        self._saved_extractions: list[FigureExtractionResult] = []
        self._multi_curve_name_root = ""

        self._view = FigureDigitizerView()
        self._view.setScene(self._scene)
        self._view.point_clicked.connect(self._handle_canvas_click)
        self._view.point_dragged.connect(self._handle_canvas_drag)
        self._view.point_released.connect(self._handle_canvas_release)
        self._view.cursor_moved.connect(self._handle_cursor_move)

        self._source_label = QLabel("No image loaded")
        self._source_label.setWordWrap(True)
        load_button = QPushButton("Load Image...")
        load_button.clicked.connect(self._choose_image)
        fit_button = QPushButton("Fit View")
        fit_button.clicked.connect(self._fit_image_in_view)
        actual_size_button = QPushButton("1:1")
        actual_size_button.clicked.connect(self._actual_size_view)
        zoom_in_button = QPushButton("Zoom In")
        zoom_in_button.clicked.connect(lambda: self._view.zoom_by(1.6))
        zoom_out_button = QPushButton("Zoom Out")
        zoom_out_button.clicked.connect(lambda: self._view.zoom_by(1 / 1.6))
        self._pan_checkbox = QCheckBox("Pan")
        self._pan_checkbox.toggled.connect(self._handle_pan_toggled)
        self._magnifier_checkbox = QCheckBox("Magnifier")
        self._magnifier_checkbox.setChecked(True)
        self._tool_mode_label = QLabel("Mode: load a figure image.")
        self._tool_mode_label.setWordWrap(True)
        self._tool_mode_label.setStyleSheet(
            "QLabel { background: #fef3c7; color: #111827; border: 1px solid #f59e0b; "
            "border-radius: 4px; padding: 5px 7px; font-weight: 600; }"
        )

        image_controls = QHBoxLayout()
        image_controls.addWidget(load_button)
        image_controls.addWidget(fit_button)
        image_controls.addWidget(actual_size_button)
        image_controls.addWidget(zoom_in_button)
        image_controls.addWidget(zoom_out_button)
        image_controls.addWidget(self._pan_checkbox)
        image_controls.addWidget(self._magnifier_checkbox)
        image_controls.addStretch()

        self._precision_group = self._build_precision_zoom_panel()
        self._magnifier_checkbox.toggled.connect(self._precision_group.setVisible)

        canvas_body = QWidget()
        canvas_body_layout = QHBoxLayout(canvas_body)
        canvas_body_layout.setContentsMargins(0, 0, 0, 0)
        canvas_body_layout.addWidget(self._view, 1)
        canvas_body_layout.addWidget(self._precision_group)

        canvas_layout = QVBoxLayout()
        canvas_layout.addWidget(self._source_label)
        canvas_layout.addWidget(self._tool_mode_label)
        canvas_layout.addWidget(canvas_body, 1)
        canvas_layout.addLayout(image_controls)
        canvas_widget = QWidget()
        canvas_widget.setLayout(canvas_layout)

        controls = QTabWidget()
        calibration_tab = self._build_calibration_tab()
        controls.addTab(self._build_correction_tab(), "Correction")
        controls.addTab(calibration_tab, "Calibration")
        controls.addTab(self._build_extraction_tab(), "Extraction")
        controls.addTab(self._build_output_tab(), "Output")

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(canvas_widget)
        splitter.addWidget(controls)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText("Create Dataset(s)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(buttons)

        if image_path:
            self.load_image(image_path)

    @classmethod
    def image_file_filter(cls) -> str:
        """Return the QFileDialog filter for supported raster image formats."""
        return cls._IMAGE_FILTER

    def dataset_name(self) -> str:
        """Return the requested output dataset name."""
        return self._dataset_name_edit.text().strip() or "Digitized Figure"

    def source_path(self) -> str:
        """Return the loaded image path."""
        return self._image_path

    def extraction_kind(self) -> str:
        """Return the workflow identifier used by the dataset importer."""
        return "xy"

    def extraction_results(self) -> list[FigureExtractionResult]:
        """Return saved curves plus any valid current extraction in session order."""
        results = list(self._saved_extractions)
        if self.extracted_rows():
            results.append(self._capture_current_extraction())
        return results

    def _capture_current_extraction(self) -> FigureExtractionResult:
        """Freeze the current extracted rows and provenance as one result."""
        return FigureExtractionResult(
            dataset_name=self._unique_extraction_name(self.dataset_name()),
            rows=tuple(dict(row) for row in self.extracted_rows()),
            source_path=self.source_path(),
            extraction_kind=self.extraction_kind(),
            calibration_summary=self.calibration_summary(),
            extraction_summary=self.extraction_summary(),
        )

    def _unique_extraction_name(self, requested_name: str) -> str:
        """Keep names unique inside the dialog before workspace naming is applied."""
        clean_name = requested_name.strip() or "Digitized Figure"
        used_names = {result.dataset_name for result in self._saved_extractions}
        if clean_name not in used_names:
            return clean_name
        suffix = 2
        while f"{clean_name} ({suffix})" in used_names:
            suffix += 1
        return f"{clean_name} ({suffix})"

    def extracted_rows(self) -> list[dict[str, object]]:
        """Return calibrated extracted rows from manual and automatic points."""
        rows: list[dict[str, object]] = []
        for manual_point in self._manual_points:
            pixel_x, pixel_y = self._manual_point_xy(manual_point)
            data = self._pixel_to_data(pixel_x, pixel_y)
            data_x, data_y = data if data is not None else (None, None)
            pixel_x_uncertainty = self._manual_point_uncertainty(manual_point, "pixel_x_uncertainty")
            pixel_y_uncertainty = self._manual_point_uncertainty(manual_point, "pixel_y_uncertainty")
            x_uncertainty, y_uncertainty = self._pixel_uncertainty_to_data(
                pixel_x,
                pixel_y,
                pixel_x_uncertainty,
                pixel_y_uncertainty,
            )
            rows.append(
                {
                    "x": data_x,
                    "y": data_y,
                    "pixel_x": pixel_x,
                    "pixel_y": pixel_y,
                    "x_uncertainty": x_uncertainty,
                    "y_uncertainty": y_uncertainty,
                    "pixel_x_uncertainty": pixel_x_uncertainty,
                    "pixel_y_uncertainty": pixel_y_uncertainty,
                    "method": "manual",
                    "trace_mode": "",
                    "trace_color": "",
                    "roi_marks": 0,
                    "source_image": self._image_path,
                }
            )

        for method, points in (("auto_trace", self._auto_points),):
            for pixel_x, pixel_y in points:
                data = self._pixel_to_data(pixel_x, pixel_y)
                data_x, data_y = data if data is not None else (None, None)
                trace_mode = str(self._trace_mode_combo.currentData()) if method == "auto_trace" else ""
                rows.append(
                    {
                        "x": data_x,
                        "y": data_y,
                        "pixel_x": pixel_x,
                        "pixel_y": pixel_y,
                        "method": method,
                        "trace_mode": trace_mode,
                        "trace_color": self._trace_color.name() if trace_mode == "color" else "",
                        "roi_marks": len(self._roi_points) if method == "auto_trace" else 0,
                        "source_image": self._image_path,
                    }
                )
        trace_mode = str(self._trace_mode_combo.currentData())
        for symbol_index, symbol in enumerate(self._symbol_points, start=1):
            pixel_x = float(symbol["pixel_x"])
            pixel_y = float(symbol["pixel_y"])
            data = self._pixel_to_data(pixel_x, pixel_y)
            data_x, data_y = data if data is not None else (None, None)
            pixel_x_uncertainty, pixel_y_uncertainty = self._symbol_pixel_uncertainty(symbol)
            x_uncertainty, y_uncertainty = self._pixel_uncertainty_to_data(
                pixel_x,
                pixel_y,
                pixel_x_uncertainty,
                pixel_y_uncertainty,
            )
            method = str(symbol.get("method", "symbol_centroid"))
            rows.append(
                {
                    "x": data_x,
                    "y": data_y,
                    "pixel_x": pixel_x,
                    "pixel_y": pixel_y,
                    "method": method,
                    "trace_mode": trace_mode,
                    "trace_color": self._trace_color.name() if trace_mode == "color" else "",
                    "roi_marks": len(self._roi_points),
                    "symbol_id": symbol_index,
                    "symbol_area": int(symbol["area"]),
                    "symbol_width": int(symbol["width"]),
                    "symbol_height": int(symbol["height"]),
                    "symbol_score": symbol.get("score", ""),
                    "symbol_template_width": symbol.get("template_width", ""),
                    "symbol_template_height": symbol.get("template_height", ""),
                    "pixel_x_uncertainty": pixel_x_uncertainty,
                    "pixel_y_uncertainty": pixel_y_uncertainty,
                    "x_uncertainty": x_uncertainty,
                    "y_uncertainty": y_uncertainty,
                    "source_image": self._image_path,
                }
            )
        return rows

    def calibration_summary(self) -> str:
        """Return a compact text summary of the current calibration."""
        values, errors = self._calibration_values()
        if errors or values is None:
            return "calibration incomplete"
        x_scale = str(self._x_scale_combo.currentData())
        y_scale = str(self._y_scale_combo.currentData())
        return (
            f"x=({values['x1']}, {values['x2']}) {x_scale}; "
            f"y=({values['y1']}, {values['y2']}) {y_scale}"
        )

    def extraction_summary(self) -> str:
        """Return a compact text summary of extraction settings."""
        trace_mode = str(self._trace_mode_combo.currentData())
        if trace_mode == "color":
            trace_text = (
                f"trace_mode=color, trace_color={self._trace_color.name()}, "
                f"tolerance={self._color_tolerance_spin.value()}"
            )
        else:
            trace_text = f"trace_mode=dark, threshold={self._threshold_spin.value()}"
        roi_text = f"roi_marks={len(self._roi_points)}"
        symbol_text = f"symbol_centers={len(self._symbol_points)}"
        return f"{trace_text}, {roi_text}, x_step={self._x_step_spin.value()}, {symbol_text}"

    def accept(self) -> None:  # type: ignore[override]
        """Validate the current curve when present, then finish the session."""
        if self.extracted_rows() or not self._saved_extractions:
            error = self._current_extraction_error()
            if error is not None:
                title, message = error
                QMessageBox.warning(self, title, message)
                return
        QDialog.accept(self)

    def _current_extraction_error(self) -> tuple[str, str] | None:
        """Return a user-facing validation error for the current XY curve."""
        if self._image.isNull():
            return "Import From Figure", "Load an image before creating a dataset."

        values, errors = self._calibration_values()
        if values is None or errors:
            return (
                "Calibration Required",
                "\n".join(errors or ["Pick all four calibration points and enter axis values."]),
            )

        if not self._manual_points and not self._auto_points and not self._symbol_points:
            return (
                "No Extracted Points",
                "Add manual points, run Auto Trace, or detect symbol centers before creating a dataset.",
            )

        if not self.dataset_name():
            return "Dataset Name", "Enter a dataset name."
        return None

    def _build_calibration_tab(self) -> QWidget:
        """Build axis calibration controls."""
        tab = QWidget()

        self._click_target_combo = QComboBox()
        for key, label in self._WARP_KEYS:
            self._click_target_combo.addItem(label, key)
        for key, label in self._CALIBRATION_KEYS:
            self._click_target_combo.addItem(label, key)
        self._click_target_combo.addItem("No active picking tool", "none")
        self._click_target_combo.addItem("Manual data point", "manual")
        self._click_target_combo.addItem("Manual radius error", "manual_error_radius")
        self._click_target_combo.addItem("Manual 4-point error", "manual_error_four")
        self._click_target_combo.addItem("ROI brush", "roi_brush")
        self._click_target_combo.addItem("Sample trace color", "trace_color")
        self._click_target_combo.addItem("Sample symbol box", "symbol_sample")
        self._click_target_combo.currentIndexChanged.connect(self._refresh_tool_mode_label)

        self._x1_value_edit = QLineEdit("0")
        self._x2_value_edit = QLineEdit("1")
        self._y1_value_edit = QLineEdit("0")
        self._y2_value_edit = QLineEdit("1")
        for edit in (
            self._x1_value_edit,
            self._x2_value_edit,
            self._y1_value_edit,
            self._y2_value_edit,
        ):
            edit.textChanged.connect(self._refresh_preview)

        self._x_scale_combo = QComboBox()
        self._x_scale_combo.addItem("Linear", "linear")
        self._x_scale_combo.addItem("Log10", "log")
        self._x_scale_combo.currentIndexChanged.connect(self._refresh_preview)

        self._y_scale_combo = QComboBox()
        self._y_scale_combo.addItem("Linear", "linear")
        self._y_scale_combo.addItem("Log10", "log")
        self._y_scale_combo.currentIndexChanged.connect(self._refresh_preview)

        clear_calibration_button = QPushButton("Clear Calibration")
        clear_calibration_button.clicked.connect(self._clear_calibration)

        values_group = QGroupBox("Axis Values")
        grid = QGridLayout(values_group)
        grid.addWidget(QLabel("X point 1"), 0, 0)
        grid.addWidget(self._x1_value_edit, 0, 1)
        grid.addWidget(QLabel("X point 2"), 1, 0)
        grid.addWidget(self._x2_value_edit, 1, 1)
        grid.addWidget(QLabel("Y point 1"), 2, 0)
        grid.addWidget(self._y1_value_edit, 2, 1)
        grid.addWidget(QLabel("Y point 2"), 3, 0)
        grid.addWidget(self._y2_value_edit, 3, 1)
        grid.addWidget(QLabel("X scale"), 4, 0)
        grid.addWidget(self._x_scale_combo, 4, 1)
        grid.addWidget(QLabel("Y scale"), 5, 0)
        grid.addWidget(self._y_scale_combo, 5, 1)

        self._calibration_status_label = QLabel("Pick calibration points on the canvas.")
        self._calibration_status_label.setWordWrap(True)

        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Click target"))
        layout.addWidget(self._click_target_combo)
        layout.addWidget(values_group)
        layout.addWidget(clear_calibration_button)
        layout.addWidget(self._calibration_status_label)
        layout.addStretch()
        return tab

    def _build_correction_tab(self) -> QWidget:
        """Build optional perspective correction controls."""
        tab = QWidget()

        pick_group = QGroupBox("Perspective / Warp Correction")
        pick_layout = QVBoxLayout(pick_group)
        pick_hint = QLabel(
            "Optional first step: pick the four corners of the plotted frame or the axis-bar "
            "rectangle, then apply correction. Calibration and extraction use the corrected image."
        )
        pick_hint.setWordWrap(True)
        pick_layout.addWidget(pick_hint)

        pick_grid = QGridLayout()
        for index, (key, label) in enumerate(self._WARP_KEYS):
            button = QPushButton(label.replace("Correction ", "Pick "))
            button.clicked.connect(lambda _checked=False, target=key: self._set_click_target(target))
            pick_grid.addWidget(button, index // 2, index % 2)
        pick_layout.addLayout(pick_grid)

        size_group = QGroupBox("Corrected Image Size")
        size_form = QFormLayout(size_group)
        self._warp_width_spin = QSpinBox()
        self._warp_width_spin.setRange(50, 50_000)
        self._warp_width_spin.setValue(1000)
        self._warp_width_spin.setSuffix(" px")
        self._warp_height_spin = QSpinBox()
        self._warp_height_spin.setRange(50, 50_000)
        self._warp_height_spin.setValue(700)
        self._warp_height_spin.setSuffix(" px")
        size_form.addRow("Width", self._warp_width_spin)
        size_form.addRow("Height", self._warp_height_spin)

        button_row = QHBoxLayout()
        apply_button = QPushButton("Apply Correction")
        apply_button.clicked.connect(self._apply_warp_correction)
        clear_button = QPushButton("Clear Points")
        clear_button.clicked.connect(self._clear_warp_points)
        reset_button = QPushButton("Reset Original")
        reset_button.clicked.connect(self._reset_warp_correction)
        button_row.addWidget(apply_button)
        button_row.addWidget(clear_button)
        button_row.addWidget(reset_button)

        self._warp_status_label = QLabel("Load an image, then pick correction points if needed.")
        self._warp_status_label.setWordWrap(True)

        layout = QVBoxLayout(tab)
        layout.addWidget(pick_group)
        layout.addWidget(size_group)
        layout.addLayout(button_row)
        layout.addWidget(self._warp_status_label)
        layout.addStretch()
        return tab

    def _build_precision_zoom_panel(self) -> QGroupBox:
        """Build the shared cursor-following magnifier panel."""
        precision_group = QGroupBox("Precision Zoom")
        precision_group.setMaximumWidth(250)
        precision_layout = QVBoxLayout(precision_group)
        self._magnifier_label = QLabel("Move over image")
        self._magnifier_label.setAlignment(Qt.AlignCenter)
        self._magnifier_label.setFixedSize(220, 220)
        self._magnifier_label.setStyleSheet(
            "QLabel { background: #111827; color: #f9fafb; border: 1px solid #4b5563; }"
        )
        self._cursor_status_label = QLabel("Pixel: -")
        self._cursor_status_label.setWordWrap(True)
        self._magnifier_zoom_spin = QSpinBox()
        self._magnifier_zoom_spin.setRange(2, 40)
        self._magnifier_zoom_spin.setValue(12)
        self._magnifier_zoom_spin.setSuffix("x")
        self._magnifier_zoom_spin.valueChanged.connect(self._refresh_cursor_preview)
        precision_form = QFormLayout()
        precision_form.addRow("Magnifier", self._magnifier_zoom_spin)
        precision_layout.addWidget(self._magnifier_label)
        precision_layout.addLayout(precision_form)
        precision_layout.addWidget(self._cursor_status_label)
        precision_layout.addStretch()
        return precision_group

    def _build_extraction_tab(self) -> QWidget:
        """Build manual and assisted extraction controls."""
        tab = QWidget()

        manual_group = QGroupBox("Manual Points")
        manual_layout = QVBoxLayout(manual_group)
        manual_button_row = QHBoxLayout()
        manual_mode_button = QPushButton("Manual Mode")
        manual_mode_button.clicked.connect(lambda: self._set_click_target("manual"))
        stop_picking_button = QPushButton("Stop Picking")
        stop_picking_button.clicked.connect(lambda: self._set_click_target("none"))
        radius_error_button = QPushButton("Radius Error")
        radius_error_button.clicked.connect(self._begin_manual_radius_error)
        four_point_error_button = QPushButton("4-Point Error")
        four_point_error_button.clicked.connect(self._begin_manual_four_point_error)
        undo_manual_button = QPushButton("Undo Last")
        undo_manual_button.clicked.connect(self._undo_manual_point)
        clear_manual_button = QPushButton("Clear Manual")
        clear_manual_button.clicked.connect(self._clear_manual_points)
        manual_button_row.addWidget(manual_mode_button)
        manual_button_row.addWidget(stop_picking_button)
        manual_error_row = QHBoxLayout()
        manual_error_row.addWidget(radius_error_button)
        manual_error_row.addWidget(four_point_error_button)
        manual_button_row.addWidget(undo_manual_button)
        manual_button_row.addWidget(clear_manual_button)
        manual_target_row = QHBoxLayout()
        self._manual_target_spin = QSpinBox()
        self._manual_target_spin.setRange(1, 1)
        self._manual_target_spin.setEnabled(False)
        self._manual_target_spin.setMinimumWidth(90)
        self._manual_target_spin.setToolTip("Manual point used by Radius Error and 4-Point Error.")
        manual_target_row.addWidget(QLabel("Error target point"))
        manual_target_row.addWidget(self._manual_target_spin)
        manual_target_row.addStretch()
        self._manual_status_label = QLabel(
            "Manual errors apply to the selected manual point. Use Radius Error or 4-Point Error after placing it."
        )
        self._manual_status_label.setWordWrap(True)
        manual_layout.addLayout(manual_button_row)
        manual_layout.addLayout(manual_target_row)
        manual_layout.addLayout(manual_error_row)
        manual_layout.addWidget(self._manual_status_label)

        roi_group = QGroupBox("Automatic Extraction Region")
        roi_layout = QVBoxLayout(roi_group)
        roi_form = QFormLayout()
        self._roi_brush_size_spin = QSpinBox()
        self._roi_brush_size_spin.setRange(2, 200)
        self._roi_brush_size_spin.setValue(18)
        self._roi_brush_size_spin.setSuffix(" px")
        roi_buttons = QHBoxLayout()
        roi_mode_button = QPushButton("ROI Brush")
        roi_mode_button.clicked.connect(lambda: self._set_click_target("roi_brush"))
        clear_roi_button = QPushButton("Clear ROI")
        clear_roi_button.clicked.connect(self._clear_roi_points)
        roi_buttons.addWidget(roi_mode_button)
        roi_buttons.addWidget(clear_roi_button)
        self._roi_status_label = QLabel("No ROI brush marks. Auto trace scans the full working image.")
        self._roi_status_label.setWordWrap(True)
        roi_form.addRow("Brush size", self._roi_brush_size_spin)
        roi_form.addRow(roi_buttons)
        roi_form.addRow(self._roi_status_label)
        roi_layout.addLayout(roi_form)

        auto_group = QGroupBox("Curves / Lines")
        auto_layout = QFormLayout(auto_group)
        self._trace_mode_combo = QComboBox()
        self._trace_mode_combo.addItem("Dark pixels", "dark")
        self._trace_mode_combo.addItem("Selected color", "color")
        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(0, 255)
        self._threshold_spin.setValue(90)
        self._color_tolerance_spin = QSpinBox()
        self._color_tolerance_spin.setRange(0, 442)
        self._color_tolerance_spin.setValue(55)
        self._trace_color_button = QPushButton("Pick Color...")
        self._trace_color_button.clicked.connect(self._choose_trace_color)
        sample_color_button = QPushButton("Sample From Image")
        sample_color_button.clicked.connect(lambda: self._set_click_target("trace_color"))
        color_buttons = QHBoxLayout()
        color_buttons.addWidget(self._trace_color_button)
        color_buttons.addWidget(sample_color_button)
        self._x_step_spin = QSpinBox()
        self._x_step_spin.setRange(1, 100)
        self._x_step_spin.setValue(2)
        self._auto_status_label = QLabel("No automatic trace yet.")
        self._auto_status_label.setWordWrap(True)
        auto_buttons = QHBoxLayout()
        run_auto_button = QPushButton("Run Auto Trace")
        run_auto_button.clicked.connect(self._run_auto_trace)
        clear_auto_button = QPushButton("Clear Auto")
        clear_auto_button.clicked.connect(self._clear_auto_points)
        auto_buttons.addWidget(run_auto_button)
        auto_buttons.addWidget(clear_auto_button)
        auto_layout.addRow("Trace mode", self._trace_mode_combo)
        auto_layout.addRow("Dark threshold", self._threshold_spin)
        auto_layout.addRow("Trace color", color_buttons)
        auto_layout.addRow("Color tolerance", self._color_tolerance_spin)
        auto_layout.addRow("X pixel step", self._x_step_spin)
        auto_layout.addRow(auto_buttons)
        auto_layout.addRow(self._auto_status_label)
        self._update_trace_color_button()

        symbol_group = QGroupBox("Symbol Centers")
        symbol_layout = QFormLayout(symbol_group)
        self._symbol_min_area_spin = QSpinBox()
        self._symbol_min_area_spin.setRange(1, 1_000_000)
        self._symbol_min_area_spin.setValue(6)
        self._symbol_min_area_spin.setSuffix(" px")
        self._symbol_max_area_spin = QSpinBox()
        self._symbol_max_area_spin.setRange(1, 10_000_000)
        self._symbol_max_area_spin.setValue(5000)
        self._symbol_max_area_spin.setSuffix(" px")
        self._symbol_max_count_spin = QSpinBox()
        self._symbol_max_count_spin.setRange(1, 100_000)
        self._symbol_max_count_spin.setValue(1000)
        self._symbol_sample_radius_spin = QSpinBox()
        self._symbol_sample_radius_spin.setRange(3, 80)
        self._symbol_sample_radius_spin.setValue(10)
        self._symbol_sample_radius_spin.setSuffix(" px")
        self._symbol_shape_combo = QComboBox()
        self._symbol_shape_combo.addItem("Auto from sample", "auto")
        self._symbol_shape_combo.addItem("Dot / circle", "dot")
        self._symbol_shape_combo.addItem("X cross", "x_cross")
        self._symbol_shape_combo.addItem("Plus cross", "plus_cross")
        self._symbol_shape_combo.addItem("Square", "square")
        self._symbol_shape_combo.addItem("Diamond", "diamond")
        self._symbol_shape_combo.addItem("Triangle up", "triangle_up")
        self._symbol_shape_combo.addItem("Triangle down", "triangle_down")
        self._symbol_score_threshold_spin = QDoubleSpinBox()
        self._symbol_score_threshold_spin.setRange(0.05, 1.0)
        self._symbol_score_threshold_spin.setSingleStep(0.05)
        self._symbol_score_threshold_spin.setDecimals(2)
        self._symbol_score_threshold_spin.setValue(0.55)
        self._symbol_min_separation_spin = QSpinBox()
        self._symbol_min_separation_spin.setRange(1, 500)
        self._symbol_min_separation_spin.setValue(8)
        self._symbol_min_separation_spin.setSuffix(" px")
        symbol_spin_style = """
            QSpinBox, QDoubleSpinBox { padding-right: 22px; }
            QSpinBox::up-button, QSpinBox::down-button,
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 18px; }
        """
        for spin_box in (
            self._symbol_min_area_spin,
            self._symbol_max_area_spin,
            self._symbol_max_count_spin,
            self._symbol_sample_radius_spin,
            self._symbol_score_threshold_spin,
            self._symbol_min_separation_spin,
        ):
            spin_box.setMinimumWidth(145)
            spin_box.setAccelerated(True)
            spin_box.setKeyboardTracking(False)
            spin_box.setStyleSheet(symbol_spin_style)
        self._symbol_template_status_label = QLabel("No sampled symbol template.")
        self._symbol_template_status_label.setWordWrap(True)
        self._symbol_status_label = QLabel("No symbol centers detected.")
        self._symbol_status_label.setWordWrap(True)
        template_buttons = QHBoxLayout()
        sample_symbol_button = QPushButton("Sample Symbol")
        sample_symbol_button.clicked.connect(lambda: self._set_click_target("symbol_sample"))
        clear_template_button = QPushButton("Clear Template")
        clear_template_button.clicked.connect(self._clear_symbol_template)
        template_buttons.addWidget(sample_symbol_button)
        template_buttons.addWidget(clear_template_button)
        symbol_buttons = QHBoxLayout()
        detect_template_button = QPushButton("Detect Sampled")
        detect_template_button.clicked.connect(self._run_template_symbol_detection)
        detect_symbols_button = QPushButton("Detect Symbols")
        detect_symbols_button.clicked.connect(self._run_symbol_detection)
        clear_symbols_button = QPushButton("Clear Symbols")
        clear_symbols_button.clicked.connect(self._clear_symbol_points)
        symbol_buttons.addWidget(detect_template_button)
        symbol_buttons.addWidget(detect_symbols_button)
        symbol_buttons.addWidget(clear_symbols_button)
        symbol_layout.addRow("Template", template_buttons)
        symbol_layout.addRow(self._symbol_template_status_label)
        symbol_layout.addRow("Shape prior", self._symbol_shape_combo)
        symbol_layout.addRow("Sample radius", self._symbol_sample_radius_spin)
        symbol_layout.addRow("Min area", self._symbol_min_area_spin)
        symbol_layout.addRow("Max area", self._symbol_max_area_spin)
        symbol_layout.addRow("Min match score", self._symbol_score_threshold_spin)
        symbol_layout.addRow("Min separation", self._symbol_min_separation_spin)
        symbol_layout.addRow("Max symbols", self._symbol_max_count_spin)
        symbol_layout.addRow(symbol_buttons)
        symbol_layout.addRow(self._symbol_status_label)

        auto_tab = QWidget()
        auto_tab_layout = QVBoxLayout(auto_tab)
        auto_tab_layout.addWidget(auto_group)
        auto_tab_layout.addStretch()

        symbol_tab = QWidget()
        symbol_tab_layout = QVBoxLayout(symbol_tab)
        symbol_tab_layout.addWidget(symbol_group)
        symbol_tab_layout.addStretch()

        automatic_tabs = QTabWidget()
        automatic_tabs.addTab(auto_tab, "Curves/Lines")
        automatic_tabs.addTab(symbol_tab, "Symbols")
        roi_layout.addWidget(automatic_tabs)

        layout = QVBoxLayout(tab)
        layout.addWidget(manual_group)
        layout.addWidget(roi_group)
        layout.addStretch()
        return tab

    def _build_output_tab(self) -> QWidget:
        """Build output naming and preview controls."""
        tab = QWidget()
        self._dataset_name_edit = QLineEdit("digitized_data")
        self._preview_table = QTableWidget(0, 18)
        self._preview_table.setHorizontalHeaderLabels(
            [
                "Method",
                "X",
                "Y",
                "dX",
                "dY",
                "Pixel X",
                "Pixel Y",
                "dPx",
                "dPy",
                "Trace",
                "Color",
                "ROI",
                "Symbol",
                "Area",
                "Score",
                "Size",
                "Template",
                "Source",
            ]
        )
        self._preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._preview_table.setAlternatingRowColors(True)
        self._preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._preview_table.horizontalHeader().setStretchLastSection(True)
        self._preview_status_label = QLabel("No extracted points.")
        self._preview_status_label.setWordWrap(True)

        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Dataset name"))
        layout.addWidget(self._dataset_name_edit)
        layout.addWidget(self._build_multi_curve_controls())
        layout.addWidget(self._preview_table, 1)
        layout.addWidget(self._preview_status_label)
        return tab

    def _build_multi_curve_controls(self) -> QWidget:
        """Build session controls for saving several curves with one calibration."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        save_button = QPushButton("Save Current Curve && Start New")
        save_button.setToolTip(
            "Store the current extracted data, clear curve-specific points/ROI/template, "
            "and keep the same image correction and X/Y calibration."
        )
        save_button.clicked.connect(self._save_current_extraction_and_start_new)
        self._saved_extractions_label = QLabel(
            "No curves saved in this session. The final Create Dataset(s) action also includes the current curve."
        )
        self._saved_extractions_label.setWordWrap(True)
        layout.addWidget(save_button)
        layout.addWidget(self._saved_extractions_label)
        return widget

    def _save_current_extraction_and_start_new(self) -> None:
        """Store the current curve and reset extraction state without recalibrating."""
        error = self._current_extraction_error()
        if error is not None:
            title, message = error
            QMessageBox.warning(self, title, message)
            return

        result = self._capture_current_extraction()
        self._saved_extractions.append(result)
        if not self._multi_curve_name_root:
            self._multi_curve_name_root = result.dataset_name
        self._clear_current_extraction()
        next_number = len(self._saved_extractions) + 1
        self._dataset_name_edit.setText(f"{self._multi_curve_name_root} Curve {next_number}")
        self._refresh_saved_extractions_status()

    def _clear_current_extraction(self) -> None:
        """Clear only curve-specific XY state, preserving image and calibration."""
        self._manual_points.clear()
        self._manual_error_samples.clear()
        self._manual_error_target_index = None
        self._refresh_manual_target_selector()
        self._auto_points.clear()
        self._symbol_points.clear()
        self._roi_points.clear()
        self._symbol_sample_start = None
        self._symbol_sample_preview_rect = None
        self._symbol_template_rect = None
        self._symbol_template_weights = None
        self._symbol_template_mask = None
        self._symbol_template_color = None
        if hasattr(self, "_manual_status_label"):
            self._manual_status_label.setText("No manual points for the new curve.")
        if hasattr(self, "_auto_status_label"):
            self._auto_status_label.setText("No automatic trace yet for the new curve.")
        if hasattr(self, "_symbol_status_label"):
            self._symbol_status_label.setText("No symbol centers detected for the new curve.")
        if hasattr(self, "_symbol_template_status_label"):
            self._symbol_template_status_label.setText("No sampled symbol template.")
        self._set_click_target("none")
        self._refresh_all()

    def _refresh_saved_extractions_status(self) -> None:
        """Show saved curve names and point counts in the Output tab."""
        label = getattr(self, "_saved_extractions_label", None)
        if label is None:
            return
        if not self._saved_extractions:
            label.setText(
                "No curves saved in this session. The final Create Dataset(s) action also includes the current curve."
            )
            return
        summaries = ", ".join(
            f"{result.dataset_name} ({len(result.rows)} points)"
            for result in self._saved_extractions
        )
        label.setText(
            f"Saved {len(self._saved_extractions)} curve(s): {summaries}. "
            "Image correction and calibration are unchanged."
        )

    def _choose_image(self) -> None:
        """Ask for an image path and load it into the canvas."""
        file_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Figure Image",
            "",
            self.image_file_filter(),
        )
        if file_name:
            self.load_image(file_name)

    def load_image(self, image_path: str) -> None:
        """Load a raster image from disk."""
        image = QImage(image_path)
        if image.isNull():
            QMessageBox.critical(
                self,
                "Import Figure Image",
                f"Could not load image:\n{image_path}",
            )
            return
        if not self._confirm_extraction_reset("Loading another image"):
            return

        self._image_path = image_path
        self._original_image = image.copy()
        self._warp_applied = False
        self._warp_pixels.clear()
        self._set_working_image(image.copy(), reset_view=False)
        self._clear_digitized_points()
        self._set_default_warp_size_from_image()
        self._set_click_target("warp_tl")
        self._update_source_label()
        current_name = self._dataset_name_edit.text().strip()
        if current_name in {"", "digitized_data"}:
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            self._dataset_name_edit.setText(f"{base_name}_digitized")
        self._fit_image_in_view()
        self._refresh_all()

    def _set_working_image(self, image: QImage, reset_view: bool = True) -> None:
        """Replace the image shown on the canvas."""
        self._image = image
        self._scene.clear()
        self._marker_items.clear()
        self._pixmap_item = self._scene.addPixmap(QPixmap.fromImage(self._image))
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        if reset_view:
            self._fit_image_in_view()

    def _update_source_label(self) -> None:
        """Refresh loaded-image text with correction state."""
        if self._image.isNull():
            self._source_label.setText("No image loaded")
            return
        correction_text = "corrected" if self._warp_applied else "original"
        self._source_label.setText(
            f"{os.path.basename(self._image_path)} - {self._image.width()} x "
            f"{self._image.height()} px ({correction_text})"
        )

    def _clear_digitized_points(self) -> None:
        """Clear calibration, extraction state, and saved curves tied to image pixels."""
        self._calibration_pixels.clear()
        self._saved_extractions.clear()
        self._multi_curve_name_root = ""
        self._manual_points.clear()
        self._manual_error_samples.clear()
        self._manual_error_target_index = None
        self._refresh_manual_target_selector()
        self._auto_points.clear()
        self._symbol_points.clear()
        self._roi_points.clear()
        self._cursor_pixel = None
        self._symbol_sample_start = None
        self._symbol_sample_preview_rect = None
        self._symbol_template_rect = None
        self._symbol_template_weights = None
        self._symbol_template_mask = None
        self._symbol_template_color = None
        if hasattr(self, "_symbol_template_status_label"):
            self._symbol_template_status_label.setText("No sampled symbol template.")
        if hasattr(self, "_symbol_status_label"):
            self._symbol_status_label.setText("No symbol centers detected.")
        if hasattr(self, "_manual_status_label"):
            self._manual_status_label.setText(
                "Manual errors apply to the selected manual point. Use Radius Error or 4-Point Error after placing it."
            )
        self._refresh_saved_extractions_status()

    def _set_default_warp_size_from_image(self) -> None:
        """Initialize correction output size from the current working image."""
        if self._image.isNull() or not hasattr(self, "_warp_width_spin"):
            return
        self._warp_width_spin.setValue(max(50, self._image.width()))
        self._warp_height_spin.setValue(max(50, self._image.height()))

    def _update_warp_output_size(self) -> None:
        """Estimate corrected image size from the selected correction corners."""
        if not all(key in self._warp_pixels for key, _label in self._WARP_KEYS):
            return
        top_left = np.asarray(self._warp_pixels["warp_tl"], dtype=float)
        top_right = np.asarray(self._warp_pixels["warp_tr"], dtype=float)
        bottom_right = np.asarray(self._warp_pixels["warp_br"], dtype=float)
        bottom_left = np.asarray(self._warp_pixels["warp_bl"], dtype=float)
        width = int(round(max(
            np.linalg.norm(top_right - top_left),
            np.linalg.norm(bottom_right - bottom_left),
        )))
        height = int(round(max(
            np.linalg.norm(bottom_left - top_left),
            np.linalg.norm(bottom_right - top_right),
        )))
        self._warp_width_spin.setValue(max(50, width))
        self._warp_height_spin.setValue(max(50, height))

    def _clear_warp_points(self) -> None:
        """Clear perspective correction points without changing the image."""
        self._warp_pixels.clear()
        self._set_click_target("warp_tl")
        self._refresh_all()

    def _reset_warp_correction(self) -> None:
        """Restore the originally loaded image and clear derived digitizer state."""
        if self._original_image.isNull():
            return
        if not self._confirm_extraction_reset("Resetting image correction"):
            return
        self._warp_applied = False
        self._warp_pixels.clear()
        self._set_working_image(self._original_image.copy())
        self._clear_digitized_points()
        self._set_default_warp_size_from_image()
        self._set_click_target("warp_tl")
        self._update_source_label()
        self._refresh_all()

    def _apply_warp_correction(self) -> None:
        """Rectify the working image with a four-corner perspective transform."""
        if self._image.isNull():
            QMessageBox.information(self, "Image Correction", "Load an image before applying correction.")
            return
        missing = [
            label
            for key, label in self._WARP_KEYS
            if key not in self._warp_pixels
        ]
        if missing:
            QMessageBox.warning(
                self,
                "Image Correction",
                "Pick correction points: " + ", ".join(missing),
            )
            return
        if not self._confirm_extraction_reset("Applying image correction"):
            return

        width = int(self._warp_width_spin.value())
        height = int(self._warp_height_spin.value())
        try:
            corrected = self._perspective_corrected_image(self._image, self._warp_pixels, width, height)
        except ValueError as exc:
            QMessageBox.warning(self, "Image Correction", str(exc))
            return

        self._warp_applied = True
        self._warp_pixels.clear()
        self._set_working_image(corrected)
        self._clear_digitized_points()
        self._set_click_target("x1")
        self._update_source_label()
        self._refresh_all()

    def _confirm_extraction_reset(self, action: str) -> bool:
        """Protect current and saved curves before changing image pixel geometry."""
        current_count = len(self.extracted_rows())
        saved_count = len(self._saved_extractions)
        if current_count == 0 and saved_count == 0:
            return True
        reply = QMessageBox.question(
            self,
            "Clear Digitized Curves?",
            (
                f"{action} clears the current extraction, calibration, and all curves saved "
                f"inside this dialog session ({saved_count} saved curve(s), "
                f"{current_count} current point(s)).\n\nContinue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _refresh_warp_status(self) -> None:
        """Update perspective correction status text."""
        if not hasattr(self, "_warp_status_label"):
            return
        if self._image.isNull():
            self._warp_status_label.setText("Load an image, then pick correction points if needed.")
            return
        if self._warp_applied:
            self._warp_status_label.setText(
                f"Correction applied. Working image is {self._image.width()} x {self._image.height()} px. "
                "Calibrate and extract on this corrected image, or reset to the original."
            )
            return
        missing = [
            label.replace("Correction ", "")
            for key, label in self._WARP_KEYS
            if key not in self._warp_pixels
        ]
        if missing:
            self._warp_status_label.setText("Perspective correction not applied. Missing: " + ", ".join(missing))
        else:
            self._warp_status_label.setText("Correction points ready. Review the green quadrilateral, then apply correction.")

    @classmethod
    def _perspective_corrected_image(
        cls,
        image: QImage,
        corner_pixels: dict[str, tuple[float, float]],
        width: int,
        height: int,
    ) -> QImage:
        """Return a perspective-corrected image from four source corners."""
        if width < 2 or height < 2:
            raise ValueError("Corrected image size must be at least 2 x 2 pixels.")

        source = np.asarray(
            [
                corner_pixels["warp_tl"],
                corner_pixels["warp_tr"],
                corner_pixels["warp_br"],
                corner_pixels["warp_bl"],
            ],
            dtype=float,
        )
        destination = np.asarray(
            [
                (0.0, 0.0),
                (width - 1.0, 0.0),
                (width - 1.0, height - 1.0),
                (0.0, height - 1.0),
            ],
            dtype=float,
        )
        if cls._polygon_area(source) < 1.0:
            raise ValueError("Correction points must form a non-empty quadrilateral.")

        destination_to_source = cls._homography(destination, source)
        rgb = cls._qimage_to_rgb_array(image).astype(float)

        y_grid, x_grid = np.indices((height, width), dtype=float)
        flat_x = x_grid.ravel()
        flat_y = y_grid.ravel()
        denominator = (
            destination_to_source[2, 0] * flat_x
            + destination_to_source[2, 1] * flat_y
            + destination_to_source[2, 2]
        )
        valid = np.abs(denominator) > 1.0e-12
        source_x = np.full_like(flat_x, -1.0)
        source_y = np.full_like(flat_y, -1.0)
        source_x[valid] = (
            destination_to_source[0, 0] * flat_x[valid]
            + destination_to_source[0, 1] * flat_y[valid]
            + destination_to_source[0, 2]
        ) / denominator[valid]
        source_y[valid] = (
            destination_to_source[1, 0] * flat_x[valid]
            + destination_to_source[1, 1] * flat_y[valid]
            + destination_to_source[1, 2]
        ) / denominator[valid]

        corrected = np.empty((height, width, 3), dtype=float)
        coordinates = np.vstack([source_y, source_x])
        for channel in range(3):
            corrected[:, :, channel] = ndimage.map_coordinates(
                rgb[:, :, channel],
                coordinates,
                order=1,
                mode="constant",
                cval=255.0,
            ).reshape((height, width))
        return cls._rgb_array_to_qimage(np.clip(corrected, 0, 255).astype(np.uint8))

    @staticmethod
    def _homography(source: np.ndarray, destination: np.ndarray) -> np.ndarray:
        """Return the 3x3 projective transform mapping source to destination."""
        if source.shape != (4, 2) or destination.shape != (4, 2):
            raise ValueError("Perspective correction requires exactly four source and destination points.")
        matrix_rows: list[list[float]] = []
        targets: list[float] = []
        for (source_x, source_y), (dest_x, dest_y) in zip(source, destination):
            matrix_rows.append([source_x, source_y, 1.0, 0.0, 0.0, 0.0, -dest_x * source_x, -dest_x * source_y])
            targets.append(dest_x)
            matrix_rows.append([0.0, 0.0, 0.0, source_x, source_y, 1.0, -dest_y * source_x, -dest_y * source_y])
            targets.append(dest_y)
        try:
            coefficients = np.linalg.solve(np.asarray(matrix_rows, dtype=float), np.asarray(targets, dtype=float))
        except np.linalg.LinAlgError as exc:
            raise ValueError("Correction points are degenerate; pick four distinct frame corners.") from exc
        return np.asarray(
            [
                [coefficients[0], coefficients[1], coefficients[2]],
                [coefficients[3], coefficients[4], coefficients[5]],
                [coefficients[6], coefficients[7], 1.0],
            ],
            dtype=float,
        )

    @staticmethod
    def _polygon_area(points: np.ndarray) -> float:
        """Return absolute polygon area for ordered 2D points."""
        x = points[:, 0]
        y = points[:, 1]
        return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)

    @classmethod
    def _qimage_to_rgb_array(cls, image: QImage) -> np.ndarray:
        """Convert a QImage to an RGB uint8 array."""
        rgb_format = cls._qimage_format("Format_RGB888")
        rgb_image = image.convertToFormat(rgb_format)
        width = rgb_image.width()
        height = rgb_image.height()
        bytes_per_line = rgb_image.bytesPerLine()
        buffer = rgb_image.bits()
        array = np.frombuffer(buffer, dtype=np.uint8).reshape((height, bytes_per_line))
        return array[:, : width * 3].reshape((height, width, 3)).copy()

    @classmethod
    def _rgb_array_to_qimage(cls, rgb: np.ndarray) -> QImage:
        """Convert an RGB uint8 array to a detached QImage."""
        contiguous = np.ascontiguousarray(rgb, dtype=np.uint8)
        height, width, _channels = contiguous.shape
        rgb_format = cls._qimage_format("Format_RGB888")
        return QImage(contiguous.data, width, height, width * 3, rgb_format).copy()

    @staticmethod
    def _qimage_format(name: str):
        """Return a QImage format across PySide6 enum styles."""
        image_format = getattr(QImage, name, None)
        if image_format is not None:
            return image_format
        return getattr(QImage.Format, name)

    def _fit_image_in_view(self) -> None:
        """Fit the loaded image inside the canvas view."""
        if self._pixmap_item is None:
            return
        self._view.resetTransform()
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _actual_size_view(self) -> None:
        """Show image pixels at canvas pixel size."""
        self._view.resetTransform()

    def _handle_pan_toggled(self, enabled: bool) -> None:
        """Switch between canvas pan and picking modes."""
        self._view.set_point_picking_enabled(not enabled)
        self._refresh_tool_mode_label()

    def _refresh_tool_mode_label(self) -> None:
        """Refresh the visible canvas interaction mode label."""
        if not hasattr(self, "_tool_mode_label"):
            return
        if getattr(self, "_pan_checkbox", None) is not None and self._pan_checkbox.isChecked():
            self._tool_mode_label.setText("Mode: Pan view - drag the image; clicks do not pick data.")
            return
        if self._image.isNull():
            self._tool_mode_label.setText("Mode: load a figure image.")
            return

        target = str(self._click_target_combo.currentData()) if hasattr(self, "_click_target_combo") else "none"
        warp_labels = dict(self._WARP_KEYS)
        calibration_labels = dict(self._CALIBRATION_KEYS)
        if target in warp_labels:
            self._tool_mode_label.setText(f"Mode: {warp_labels[target]} - click that plot-frame corner.")
        elif target in calibration_labels:
            self._tool_mode_label.setText(f"Mode: {calibration_labels[target]} - click that axis reference point.")
        elif target == "manual":
            self._tool_mode_label.setText("Mode: Manual pick - canvas clicks add data points.")
        elif target == "manual_error_radius":
            self._tool_mode_label.setText(
                f"Mode: Manual radius error - click one boundary point around {self._manual_error_target_label()}."
            )
        elif target == "manual_error_four":
            count = len(self._manual_error_samples) if hasattr(self, "_manual_error_samples") else 0
            self._tool_mode_label.setText(
                f"Mode: Manual 4-point error - click four boundary/error-bar points around "
                f"{self._manual_error_target_label()} ({count}/4)."
            )
        elif target == "roi_brush":
            self._tool_mode_label.setText("Mode: ROI brush - click or drag to paint the automatic extraction region.")
        elif target == "trace_color":
            self._tool_mode_label.setText("Mode: Sample trace color - click the curve, line, or marker color.")
        elif target == "symbol_sample":
            self._tool_mode_label.setText("Mode: Sample symbol - click a marker center or drag a box around it.")
        else:
            self._tool_mode_label.setText("Mode: Idle - canvas clicks only inspect coordinates.")

    def _handle_canvas_click(self, pixel_x: float, pixel_y: float) -> None:
        """Route a canvas click to calibration or point extraction."""
        if self._image.isNull():
            return
        if pixel_x < 0 or pixel_y < 0 or pixel_x >= self._image.width() or pixel_y >= self._image.height():
            return

        target = str(self._click_target_combo.currentData())
        if target in {key for key, _label in self._WARP_KEYS}:
            self._warp_pixels[target] = (pixel_x, pixel_y)
            self._update_warp_output_size()
            self._advance_warp_target()
        elif target in {key for key, _label in self._CALIBRATION_KEYS}:
            self._calibration_pixels[target] = (pixel_x, pixel_y)
            self._advance_click_target()
        elif target == "manual_error_radius":
            self._set_manual_radius_uncertainty(pixel_x, pixel_y)
        elif target == "manual_error_four":
            self._add_manual_four_point_uncertainty(pixel_x, pixel_y)
        elif target == "roi_brush":
            self._add_roi_brush_point(pixel_x, pixel_y)
        elif target == "trace_color":
            self._sample_trace_color(pixel_x, pixel_y)
            self._set_click_target("none")
        elif target == "symbol_sample":
            self._begin_symbol_sample(pixel_x, pixel_y)
        elif target == "manual":
            self._manual_points.append(
                {
                    "pixel_x": float(pixel_x),
                    "pixel_y": float(pixel_y),
                    "pixel_x_uncertainty": None,
                    "pixel_y_uncertainty": None,
                }
            )
            self._refresh_manual_target_selector(select_latest=True)
            if hasattr(self, "_manual_status_label"):
                self._manual_status_label.setText(
                    f"Manual point {len(self._manual_points)} added. Use Radius Error or 4-Point Error to assign uncertainty."
                )
        self._refresh_all()

    def _advance_warp_target(self) -> None:
        """Advance click target to the next unpicked correction point."""
        for index in range(self._click_target_combo.count()):
            key = str(self._click_target_combo.itemData(index))
            if key in {warp_key for warp_key, _label in self._WARP_KEYS} and key not in self._warp_pixels:
                self._click_target_combo.setCurrentIndex(index)
                return
        self._set_click_target("none")

    def _handle_canvas_drag(self, pixel_x: float, pixel_y: float) -> None:
        """Handle drag operations for brush-defined regions."""
        if self._image.isNull():
            return
        if pixel_x < 0 or pixel_y < 0 or pixel_x >= self._image.width() or pixel_y >= self._image.height():
            return
        target = str(self._click_target_combo.currentData())
        if target == "symbol_sample" and self._symbol_sample_start is not None:
            self._symbol_sample_preview_rect = self._rect_from_points(self._symbol_sample_start, (pixel_x, pixel_y))
            self._redraw_markers()
            return
        if target != "roi_brush":
            return
        if self._add_roi_brush_point(pixel_x, pixel_y):
            self._redraw_markers()
            self._refresh_roi_status()

    def _handle_canvas_release(self, pixel_x: float, pixel_y: float) -> None:
        """Finish drag-defined canvas interactions."""
        if self._image.isNull() or str(self._click_target_combo.currentData()) != "symbol_sample":
            return
        if self._symbol_sample_start is None:
            return
        if pixel_x < 0 or pixel_y < 0 or pixel_x >= self._image.width() or pixel_y >= self._image.height():
            self._symbol_sample_start = None
            self._symbol_sample_preview_rect = None
            self._refresh_all()
            return
        self._finish_symbol_sample(pixel_x, pixel_y)
        self._refresh_all()

    def _handle_cursor_move(self, pixel_x: float, pixel_y: float) -> None:
        """Update cursor readout and magnifier from image-coordinate movement."""
        if self._image.isNull():
            return
        if pixel_x < 0 or pixel_y < 0 or pixel_x >= self._image.width() or pixel_y >= self._image.height():
            return
        self._cursor_pixel = (pixel_x, pixel_y)
        self._refresh_cursor_preview()

    def _advance_click_target(self) -> None:
        """Advance click target to the next unpicked calibration point."""
        calibration_keys = {key for key, _label in self._CALIBRATION_KEYS}
        for index in range(self._click_target_combo.count()):
            key = str(self._click_target_combo.itemData(index))
            if key in calibration_keys and key not in self._calibration_pixels:
                self._click_target_combo.setCurrentIndex(index)
                return
        self._set_click_target("none")

    def _set_click_target(self, target: str) -> None:
        """Select the active click target by internal key."""
        if target != "manual_error_four" and hasattr(self, "_manual_error_samples"):
            self._manual_error_samples.clear()
        if target not in {"manual_error_radius", "manual_error_four"}:
            self._manual_error_target_index = None
        for index in range(self._click_target_combo.count()):
            if str(self._click_target_combo.itemData(index)) == target:
                self._click_target_combo.setCurrentIndex(index)
                return

    def _clear_calibration(self) -> None:
        """Remove all calibration points."""
        self._calibration_pixels.clear()
        self._set_click_target("x1")
        self._refresh_all()

    def _clear_manual_points(self) -> None:
        """Remove all manually selected points."""
        self._manual_points.clear()
        self._manual_error_samples.clear()
        self._manual_error_target_index = None
        self._refresh_manual_target_selector()
        if hasattr(self, "_manual_status_label"):
            self._manual_status_label.setText("No manual points.")
        self._refresh_all()

    def _undo_manual_point(self) -> None:
        """Remove the most recently added manual point."""
        if self._manual_points:
            self._manual_points.pop()
            self._manual_error_samples.clear()
            self._manual_error_target_index = None
            self._refresh_manual_target_selector(select_latest=True)
            if hasattr(self, "_manual_status_label"):
                self._manual_status_label.setText(f"{len(self._manual_points)} manual point(s) remaining.")
            self._refresh_all()

    def _refresh_manual_target_selector(self, select_latest: bool = False) -> None:
        """Keep the manual uncertainty target selector aligned with available points."""
        spin_box = getattr(self, "_manual_target_spin", None)
        if spin_box is None:
            return
        count = len(self._manual_points)
        spin_box.blockSignals(True)
        if count <= 0:
            spin_box.setRange(1, 1)
            spin_box.setValue(1)
            spin_box.setEnabled(False)
        else:
            current_value = spin_box.value()
            spin_box.setRange(1, count)
            if select_latest:
                spin_box.setValue(count)
            else:
                spin_box.setValue(min(max(1, current_value), count))
            spin_box.setEnabled(True)
        spin_box.blockSignals(False)

    def _selected_manual_point_index(self) -> int | None:
        """Return the zero-based manual point index selected for uncertainty editing."""
        if not self._manual_points:
            return None
        spin_box = getattr(self, "_manual_target_spin", None)
        if spin_box is None or not spin_box.isEnabled():
            return len(self._manual_points) - 1
        return min(max(0, spin_box.value() - 1), len(self._manual_points) - 1)

    def _manual_error_target_label(self) -> str:
        """Return a user-facing label for the current manual uncertainty target."""
        index = self._manual_error_target_index
        if index is None:
            index = self._selected_manual_point_index()
        if index is None:
            return "the selected manual point"
        return f"manual point {index + 1}"

    def _begin_manual_radius_error(self) -> None:
        """Arm a one-click radius uncertainty assignment for the selected manual point."""
        target_index = self._selected_manual_point_index()
        if target_index is None:
            QMessageBox.information(self, "Manual Error", "Add a manual point before assigning uncertainty.")
            return
        self._manual_error_target_index = target_index
        self._manual_error_samples.clear()
        self._set_click_target("manual_error_radius")
        if hasattr(self, "_manual_status_label"):
            self._manual_status_label.setText(
                f"Click one boundary point around manual point {target_index + 1}."
            )

    def _begin_manual_four_point_error(self) -> None:
        """Arm a four-click asymmetric X/Y uncertainty assignment for the selected manual point."""
        target_index = self._selected_manual_point_index()
        if target_index is None:
            QMessageBox.information(self, "Manual Error", "Add a manual point before assigning uncertainty.")
            return
        self._manual_error_target_index = target_index
        self._manual_error_samples.clear()
        self._set_click_target("manual_error_four")
        if hasattr(self, "_manual_status_label"):
            self._manual_status_label.setText(
                f"Click four boundary/error-bar points around manual point {target_index + 1}."
            )

    def _set_manual_radius_uncertainty(self, pixel_x: float, pixel_y: float) -> None:
        """Set the selected manual point uncertainty from one radius click."""
        manual_point = self._manual_error_target_point()
        if manual_point is None:
            QMessageBox.information(self, "Manual Error", "Add a manual point before assigning uncertainty.")
            self._set_click_target("none")
            return
        center_x, center_y = self._manual_point_xy(manual_point)
        radius = math.hypot(pixel_x - center_x, pixel_y - center_y)
        self._set_manual_point_uncertainty(manual_point, radius, radius, "radius")
        self._manual_error_samples.clear()
        self._manual_error_target_index = None
        self._set_click_target("none")

    def _add_manual_four_point_uncertainty(self, pixel_x: float, pixel_y: float) -> None:
        """Collect four boundary clicks and set selected manual point uncertainty."""
        manual_point = self._manual_error_target_point()
        if manual_point is None:
            QMessageBox.information(self, "Manual Error", "Add a manual point before assigning uncertainty.")
            self._set_click_target("none")
            return
        self._manual_error_samples.append((pixel_x, pixel_y))
        if len(self._manual_error_samples) < 4:
            if hasattr(self, "_manual_status_label"):
                self._manual_status_label.setText(
                    f"Manual 4-point error for {self._manual_error_target_label()}: "
                    f"{len(self._manual_error_samples)}/4 boundary point(s) selected."
                )
            self._refresh_tool_mode_label()
            return

        center_x, center_y = self._manual_point_xy(manual_point)
        pixel_x_uncertainty = max(abs(sample_x - center_x) for sample_x, _sample_y in self._manual_error_samples)
        pixel_y_uncertainty = max(abs(sample_y - center_y) for _sample_x, sample_y in self._manual_error_samples)
        self._set_manual_point_uncertainty(
            manual_point,
            pixel_x_uncertainty,
            pixel_y_uncertainty,
            "four-point",
        )
        self._manual_error_samples.clear()
        self._manual_error_target_index = None
        self._set_click_target("none")

    def _manual_error_target_point(self) -> dict[str, object] | None:
        """Return the manual point selected for uncertainty editing."""
        if not self._manual_points:
            return None
        index = self._manual_error_target_index
        if index is None:
            index = self._selected_manual_point_index()
        if index is None or index < 0 or index >= len(self._manual_points):
            return None
        point = self._manual_points[index]
        if isinstance(point, dict):
            return point
        pixel_x, pixel_y = point
        converted = {"pixel_x": float(pixel_x), "pixel_y": float(pixel_y)}
        self._manual_points[index] = converted
        return converted

    @staticmethod
    def _manual_point_xy(point: dict[str, object] | tuple[float, float]) -> tuple[float, float]:
        """Return one manual point's pixel coordinates."""
        if isinstance(point, dict):
            return float(point.get("pixel_x", 0.0)), float(point.get("pixel_y", 0.0))
        return float(point[0]), float(point[1])

    @staticmethod
    def _manual_point_uncertainty(point: dict[str, object] | tuple[float, float], key: str) -> float | None:
        """Return a manual point pixel uncertainty value if assigned."""
        if not isinstance(point, dict):
            return None
        value = point.get(key)
        try:
            uncertainty = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(uncertainty) or uncertainty < 0:
            return None
        return uncertainty

    def _set_manual_point_uncertainty(
        self,
        point: dict[str, object],
        pixel_x_uncertainty: float,
        pixel_y_uncertainty: float,
        source: str,
    ) -> None:
        """Assign uncertainty in pixels to a manual point."""
        pixel_x_uncertainty = max(0.0, float(pixel_x_uncertainty))
        pixel_y_uncertainty = max(0.0, float(pixel_y_uncertainty))
        point["pixel_x_uncertainty"] = pixel_x_uncertainty
        point["pixel_y_uncertainty"] = pixel_y_uncertainty
        point["uncertainty_source"] = source
        if hasattr(self, "_manual_status_label"):
            self._manual_status_label.setText(
                f"{self._manual_error_target_label().capitalize()} uncertainty: "
                f"dPx={pixel_x_uncertainty:.4g}, dPy={pixel_y_uncertainty:.4g} ({source})."
            )

    def _clear_auto_points(self) -> None:
        """Remove all automatic trace points."""
        self._auto_points.clear()
        self._auto_status_label.setText("No automatic trace yet.")
        self._refresh_all()

    def _clear_symbol_points(self) -> None:
        """Remove all detected symbol centers."""
        self._symbol_points.clear()
        if hasattr(self, "_symbol_status_label"):
            self._symbol_status_label.setText("No symbol centers detected.")
        self._refresh_all()

    def _clear_symbol_template(self) -> None:
        """Clear the sampled symbol template."""
        self._symbol_sample_start = None
        self._symbol_sample_preview_rect = None
        self._symbol_template_rect = None
        self._symbol_template_weights = None
        self._symbol_template_mask = None
        self._symbol_template_color = None
        if hasattr(self, "_symbol_template_status_label"):
            self._symbol_template_status_label.setText("No sampled symbol template.")
        self._refresh_all()

    def _clear_roi_points(self) -> None:
        """Remove all ROI brush marks."""
        self._roi_points.clear()
        self._refresh_all()

    def _add_roi_brush_point(self, pixel_x: float, pixel_y: float) -> bool:
        """Add one ROI brush mark, skipping points that are too close together."""
        radius = float(self._roi_brush_size_spin.value())
        if self._roi_points:
            last_x, last_y, last_radius = self._roi_points[-1]
            min_spacing = max(2.0, min(radius, last_radius) / 3.0)
            if (pixel_x - last_x) ** 2 + (pixel_y - last_y) ** 2 < min_spacing**2:
                return False
        self._roi_points.append((pixel_x, pixel_y, radius))
        return True

    def _choose_trace_color(self) -> None:
        """Open a color picker for color-based auto tracing."""
        color = QColorDialog.getColor(self._trace_color, self, "Trace Color")
        if color.isValid():
            self._set_trace_color(color)

    def _sample_trace_color(self, pixel_x: float, pixel_y: float) -> None:
        """Sample a trace color from the loaded image."""
        pixel_x_int = min(max(0, int(round(pixel_x))), self._image.width() - 1)
        pixel_y_int = min(max(0, int(round(pixel_y))), self._image.height() - 1)
        self._set_trace_color(QColor(self._image.pixel(pixel_x_int, pixel_y_int)))
        index = self._trace_mode_combo.findData("color")
        if index >= 0:
            self._trace_mode_combo.setCurrentIndex(index)

    def _set_trace_color(self, color: QColor) -> None:
        """Set the target color used by color-based auto tracing."""
        self._trace_color = QColor(color)
        self._update_trace_color_button()

    def _update_trace_color_button(self) -> None:
        """Refresh the trace color button swatch."""
        if not hasattr(self, "_trace_color_button"):
            return
        color_name = self._trace_color.name()
        self._trace_color_button.setText(color_name)
        self._trace_color_button.setStyleSheet(
            f"QPushButton {{ background: {color_name}; color: #ffffff; font-weight: 700; }}"
        )

    def _begin_symbol_sample(self, pixel_x: float, pixel_y: float) -> None:
        """Start a click-or-drag symbol sample."""
        self._symbol_sample_start = (pixel_x, pixel_y)
        self._symbol_sample_preview_rect = None
        self._symbol_template_status_label.setText(
            "Release on the symbol center for auto sampling, or drag a box around the symbol."
        )

    def _finish_symbol_sample(self, pixel_x: float, pixel_y: float) -> None:
        """Create a symbol template from a click center or dragged rectangle."""
        if self._symbol_sample_start is None:
            return

        start = self._symbol_sample_start
        self._symbol_sample_start = None
        self._symbol_sample_preview_rect = None
        dx = abs(pixel_x - start[0])
        dy = abs(pixel_y - start[1])
        if max(dx, dy) < 3.0:
            learned = self._learn_symbol_template_around_click(start[0], start[1])
        else:
            left, top, width, height = self._rect_from_points(start, (pixel_x, pixel_y))
            learned = self._learn_symbol_template(
                left,
                top,
                left + width - 1,
                top + height - 1,
                seed_point=((start[0] + pixel_x) / 2.0, (start[1] + pixel_y) / 2.0),
            )
        if learned:
            self._set_click_target("none")

    def _learn_symbol_template_around_click(self, pixel_x: float, pixel_y: float) -> bool:
        """Auto-grow a symbol sample around one clicked marker center."""
        left, top, width, height = self._auto_symbol_template_rect(pixel_x, pixel_y)
        return self._learn_symbol_template(
            left,
            top,
            left + width - 1,
            top + height - 1,
            seed_point=(pixel_x, pixel_y),
        )

    def _auto_symbol_template_rect(self, pixel_x: float, pixel_y: float) -> tuple[int, int, int, int]:
        """Return a padded local template rectangle around a clicked symbol."""
        radius = int(self._symbol_sample_radius_spin.value()) if hasattr(self, "_symbol_sample_radius_spin") else 10
        center_x = min(max(0, int(round(pixel_x))), self._image.width() - 1)
        center_y = min(max(0, int(round(pixel_y))), self._image.height() - 1)
        if self._current_symbol_shape() != "auto":
            return self._minimum_symbol_rect(center_x, center_y, minimum=max(5, radius * 2 + 1))

        left = max(0, center_x - radius)
        right = min(self._image.width() - 1, center_x + radius)
        top = max(0, center_y - radius)
        bottom = min(self._image.height() - 1, center_y + radius)
        width = right - left + 1
        height = bottom - top + 1
        if width < 3 or height < 3:
            return self._minimum_symbol_rect(center_x, center_y, minimum=3)

        rgb = self._image_rgb_array(left, top, width, height)
        local_x = center_x - left
        local_y = center_y - top
        seed_color = rgb[local_y, local_x, :]
        background = self._template_background_color(rgb)
        distance_to_seed = np.linalg.norm(rgb - seed_color.reshape(1, 1, 3), axis=2)
        distance_to_background = np.linalg.norm(rgb - background.reshape(1, 1, 3), axis=2)
        seed_background_distance = float(np.linalg.norm(seed_color - background))
        if seed_background_distance >= 6.0:
            seed_threshold = max(18.0, min(120.0, seed_background_distance * 0.70 + 12.0))
            contrast_threshold = max(6.0, seed_background_distance * 0.12)
            foreground = (distance_to_seed <= seed_threshold) & (distance_to_background >= contrast_threshold)
        else:
            border_distance = np.linalg.norm(
                self._template_border_pixels(rgb) - background.reshape(1, 3),
                axis=1,
            )
            contrast_threshold = max(8.0, float(np.percentile(border_distance, 95)) + 6.0)
            foreground = distance_to_background > contrast_threshold

        component_bounds = self._foreground_component_bounds(foreground, local_x, local_y)
        if component_bounds is None:
            half_size = max(3, min(radius, int(round(radius * 0.6))))
            return self._minimum_symbol_rect(center_x, center_y, minimum=half_size * 2 + 1)

        comp_left, comp_top, comp_right, comp_bottom = component_bounds
        pad = max(2, min(8, int(round(radius * 0.25))))
        rect_left = max(0, left + comp_left - pad)
        rect_top = max(0, top + comp_top - pad)
        rect_right = min(self._image.width() - 1, left + comp_right + pad)
        rect_bottom = min(self._image.height() - 1, top + comp_bottom + pad)
        rect_left, rect_top, rect_width, rect_height = self._ensure_minimum_rect(
            rect_left,
            rect_top,
            rect_right,
            rect_bottom,
            minimum=5,
        )
        return rect_left, rect_top, rect_width, rect_height

    @staticmethod
    def _foreground_component_bounds(
        foreground: np.ndarray,
        local_x: int,
        local_y: int,
    ) -> tuple[int, int, int, int] | None:
        """Return the foreground component nearest the clicked point."""
        mask = FigureDigitizerDialog._foreground_component_mask(foreground, local_x, local_y)
        if mask is None:
            return None
        y_coords, x_coords = np.nonzero(mask)
        return int(x_coords.min()), int(y_coords.min()), int(x_coords.max()), int(y_coords.max())

    @staticmethod
    def _foreground_component_mask(
        foreground: np.ndarray,
        local_x: int,
        local_y: int,
    ) -> np.ndarray | None:
        """Return the foreground component mask nearest the clicked point."""
        if not np.any(foreground):
            return None
        labels, count = ndimage.label(foreground)
        if count <= 0:
            return None
        if 0 <= local_y < labels.shape[0] and 0 <= local_x < labels.shape[1]:
            chosen_label = int(labels[local_y, local_x])
        else:
            chosen_label = 0
        if chosen_label == 0:
            best_label = 0
            best_distance = math.inf
            for label_index in range(1, count + 1):
                y_coords, x_coords = np.nonzero(labels == label_index)
                area = int(x_coords.size)
                if area < 3:
                    continue
                distance = float(np.min((x_coords - local_x) ** 2 + (y_coords - local_y) ** 2))
                if distance < best_distance:
                    best_distance = distance
                    best_label = label_index
            chosen_label = best_label
        if chosen_label == 0:
            return None

        mask = labels == chosen_label
        if int(mask.sum()) < 3:
            return None
        return mask

    def _minimum_symbol_rect(self, center_x: int, center_y: int, minimum: int) -> tuple[int, int, int, int]:
        """Return a centered image rect with at least the requested size."""
        half = max(1, int(math.ceil((minimum - 1) / 2.0)))
        left = max(0, center_x - half)
        right = min(self._image.width() - 1, center_x + half)
        top = max(0, center_y - half)
        bottom = min(self._image.height() - 1, center_y + half)
        return self._ensure_minimum_rect(left, top, right, bottom, minimum=max(3, minimum))

    def _ensure_minimum_rect(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        minimum: int,
    ) -> tuple[int, int, int, int]:
        """Expand an image rectangle until it reaches a minimum width and height."""
        minimum = max(3, int(minimum))
        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0
        half = (minimum - 1) / 2.0
        if right - left + 1 < minimum:
            left = int(math.floor(center_x - half))
            right = int(math.ceil(center_x + half))
        if bottom - top + 1 < minimum:
            top = int(math.floor(center_y - half))
            bottom = int(math.ceil(center_y + half))
        left = max(0, left)
        top = max(0, top)
        right = min(self._image.width() - 1, right)
        bottom = min(self._image.height() - 1, bottom)
        if right - left + 1 < minimum:
            left = max(0, right - minimum + 1)
        if bottom - top + 1 < minimum:
            top = max(0, bottom - minimum + 1)
        right = min(self._image.width() - 1, max(right, left + minimum - 1))
        bottom = min(self._image.height() - 1, max(bottom, top + minimum - 1))
        return left, top, right - left + 1, bottom - top + 1

    @staticmethod
    def _rect_from_points(
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> tuple[int, int, int, int]:
        """Return an inclusive image rectangle from two scene points."""
        left = int(math.floor(min(first[0], second[0])))
        right = int(math.ceil(max(first[0], second[0])))
        top = int(math.floor(min(first[1], second[1])))
        bottom = int(math.ceil(max(first[1], second[1])))
        return left, top, right - left + 1, bottom - top + 1

    def _current_symbol_shape(self) -> str:
        """Return the selected symbol shape-prior key."""
        if not hasattr(self, "_symbol_shape_combo"):
            return "auto"
        return str(self._symbol_shape_combo.currentData() or "auto")

    @staticmethod
    def _symbol_shape_label(shape: str) -> str:
        """Return a compact label for a symbol shape-prior key."""
        labels = {
            "auto": "auto",
            "dot": "dot/circle",
            "x_cross": "X cross",
            "plus_cross": "plus cross",
            "square": "square",
            "diamond": "diamond",
            "triangle_up": "triangle up",
            "triangle_down": "triangle down",
        }
        return labels.get(shape, shape)

    @staticmethod
    def _symbol_shape_prior_mask(width: int, height: int, shape: str) -> np.ndarray | None:
        """Return a soft predefined symbol-shape support mask."""
        if shape == "auto" or width <= 0 or height <= 0:
            return None

        yy, xx = np.indices((height, width), dtype=float)
        center_x = (width - 1) / 2.0
        center_y = (height - 1) / 2.0
        radius_x = max(1.0, center_x)
        radius_y = max(1.0, center_y)
        x_norm = (xx - center_x) / radius_x
        y_norm = (yy - center_y) / radius_y
        inside_box = (np.abs(x_norm) <= 1.0) & (np.abs(y_norm) <= 1.0)
        thickness = max(0.10, 1.35 / max(2.0, min(radius_x, radius_y)))

        if shape == "dot":
            distance = np.sqrt(x_norm * x_norm + y_norm * y_norm)
            mask = np.clip(1.0 - distance, 0.0, 1.0)
            return mask * (distance <= 1.05)

        if shape == "x_cross":
            diagonal_distance = np.minimum(np.abs(y_norm - x_norm), np.abs(y_norm + x_norm))
            mask = np.exp(-np.square(diagonal_distance / thickness)) * inside_box
            return mask

        if shape == "plus_cross":
            axis_distance = np.minimum(np.abs(x_norm), np.abs(y_norm))
            mask = np.exp(-np.square(axis_distance / thickness)) * inside_box
            return mask

        if shape == "square":
            edge_distance = np.minimum(1.0 - np.abs(x_norm), 1.0 - np.abs(y_norm))
            mask = np.exp(-np.square(edge_distance / thickness)) * inside_box
            return mask

        if shape == "diamond":
            diamond_distance = np.abs(x_norm) + np.abs(y_norm)
            mask = np.exp(-np.square((diamond_distance - 1.0) / thickness)) * (diamond_distance <= 1.25)
            return mask

        if shape in {"triangle_up", "triangle_down"}:
            oriented_y = y_norm if shape == "triangle_up" else -y_norm
            left_edge = np.abs(oriented_y + 2.0 * x_norm - 1.0)
            right_edge = np.abs(oriented_y - 2.0 * x_norm - 1.0)
            bottom_edge = np.abs(oriented_y + 1.0)
            edge_distance = np.minimum(np.minimum(left_edge, right_edge), bottom_edge)
            inside_triangle = (oriented_y >= -1.0) & (oriented_y <= 1.0 - 2.0 * np.abs(x_norm))
            mask = np.exp(-np.square(edge_distance / max(thickness, 0.16))) * (
                inside_triangle | (edge_distance <= thickness * 1.5)
            )
            return mask

        return None

    def _learn_symbol_template(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        seed_point: tuple[float, float] | None = None,
    ) -> bool:
        """Build a weighted symbol template from a user-selected image box."""
        if self._image.isNull():
            return False

        left = max(0, min(left, self._image.width() - 1))
        right = max(0, min(right, self._image.width() - 1))
        top = max(0, min(top, self._image.height() - 1))
        bottom = max(0, min(bottom, self._image.height() - 1))
        width = right - left + 1
        height = bottom - top + 1
        if width < 3 or height < 3:
            center_x = int(round((left + right) / 2.0))
            center_y = int(round((top + bottom) / 2.0))
            left, top, width, height = self._minimum_symbol_rect(center_x, center_y, minimum=5)
            right = left + width - 1
            bottom = top + height - 1

        rgb = self._image_rgb_array(left, top, width, height)
        symbol_shape = self._current_symbol_shape()
        shape_prior = self._symbol_shape_prior_mask(width, height, symbol_shape)
        if shape_prior is not None and seed_point is None:
            seed_point = (left + (width - 1) / 2.0, top + (height - 1) / 2.0)
        background = self._template_background_color(rgb)
        color_distance = np.linalg.norm(rgb - background.reshape(1, 1, 3), axis=2)
        border = self._template_border_pixels(rgb)
        border_distance = np.linalg.norm(border - background.reshape(1, 3), axis=1)
        threshold = max(10.0, float(np.percentile(border_distance, 95)) + 8.0)
        foreground = color_distance > threshold
        if seed_point is not None:
            seed_x = min(max(0, int(round(seed_point[0])) - left), width - 1)
            seed_y = min(max(0, int(round(seed_point[1])) - top), height - 1)
            seed_color = rgb[seed_y, seed_x, :]
            seed_background_distance = float(np.linalg.norm(seed_color - background))
            if seed_background_distance >= 6.0:
                distance_to_seed = np.linalg.norm(rgb - seed_color.reshape(1, 1, 3), axis=2)
                seed_threshold = max(18.0, min(120.0, seed_background_distance * 0.70 + 12.0))
                seed_foreground = (
                    (distance_to_seed <= seed_threshold)
                    & (color_distance >= max(6.0, seed_background_distance * 0.12))
                )
                if int(seed_foreground.sum()) >= 3:
                    mask = self._foreground_component_mask(seed_foreground, seed_x, seed_y)
                    if mask is not None:
                        foreground = foreground | mask

        if shape_prior is not None:
            shape_support = shape_prior > 0.12
            shaped_foreground = foreground & shape_support
            if int(shaped_foreground.sum()) >= 3:
                foreground = shaped_foreground
            else:
                relaxed_foreground = (color_distance > max(5.0, threshold * 0.45)) & shape_support
                if int(relaxed_foreground.sum()) >= 3:
                    foreground = relaxed_foreground

        if int(foreground.sum()) < 3:
            QMessageBox.warning(
                self,
                "Sample Symbol",
                "Could not isolate enough symbol pixels. Click the marker center, increase Sample radius, or drag a box with a little background around the marker.",
            )
            return False

        foreground_rgb = rgb[foreground]
        foreground_color = np.median(foreground_rgb, axis=0)
        foreground_spread = np.linalg.norm(foreground_rgb - foreground_color.reshape(1, 3), axis=1)
        tolerance = int(max(20, min(220, float(np.percentile(foreground_spread, 90)) + 30.0)))

        color = QColor(
            int(np.clip(round(float(foreground_color[0])), 0, 255)),
            int(np.clip(round(float(foreground_color[1])), 0, 255)),
            int(np.clip(round(float(foreground_color[2])), 0, 255)),
        )
        self._set_trace_color(color)
        color_index = self._trace_mode_combo.findData("color")
        if color_index >= 0:
            self._trace_mode_combo.setCurrentIndex(color_index)
        self._color_tolerance_spin.setValue(tolerance)

        yy, xx = np.indices(foreground.shape, dtype=float)
        center_x = (width - 1) / 2.0
        center_y = (height - 1) / 2.0
        sigma = max(width, height) / 2.0
        center_weight = 0.35 + 0.65 * np.exp(
            -(((xx - center_x) ** 2 + (yy - center_y) ** 2) / max(1.0, 2.0 * sigma * sigma))
        )
        contrast = color_distance / max(float(color_distance.max()), 1.0)
        weights = foreground.astype(float) * center_weight * np.clip(contrast, 0.2, 1.0)
        if shape_prior is not None:
            weights *= np.clip(shape_prior, 0.0, 1.0)
            if float(weights.sum()) <= 0:
                weights = foreground.astype(float) * np.clip(shape_prior, 0.0, 1.0)

        self._symbol_template_rect = (left, top, width, height)
        self._symbol_template_weights = weights
        self._symbol_template_mask = foreground.astype(bool)
        self._symbol_template_color = tuple(float(value) for value in foreground_color)
        self._symbol_min_separation_spin.setValue(max(2, int(round(min(width, height) * 0.45))))
        self._symbol_min_area_spin.setValue(max(1, min(self._symbol_min_area_spin.maximum(), int(foreground.sum() * 0.35))))
        self._symbol_max_area_spin.setValue(
            max(
                self._symbol_min_area_spin.value(),
                min(self._symbol_max_area_spin.maximum(), int(max(foreground.sum() * 3.0, width * height))),
            )
        )
        self._symbol_template_status_label.setText(
            f"Template: {width} x {height} px, {int(foreground.sum())} foreground px, "
            f"shape {self._symbol_shape_label(symbol_shape)}, color {color.name()}, tolerance {tolerance}."
        )
        return True

    @staticmethod
    def _template_border_pixels(rgb: np.ndarray) -> np.ndarray:
        """Return border pixels from an RGB template sample."""
        top = rgb[0, :, :]
        bottom = rgb[-1, :, :]
        left = rgb[:, 0, :]
        right = rgb[:, -1, :]
        return np.vstack((top, bottom, left, right))

    @staticmethod
    def _template_background_color(rgb: np.ndarray) -> np.ndarray:
        """Estimate template background color from border pixels."""
        return np.median(FigureDigitizerDialog._template_border_pixels(rgb), axis=0)

    def _image_rgb_array(self, left: int, top: int, width: int, height: int) -> np.ndarray:
        """Return an RGB float array for a rectangular image region."""
        image_format = getattr(QImage, "Format_RGB32", None)
        if image_format is None:
            image_format = QImage.Format.Format_RGB32
        image = self._image.convertToFormat(image_format)
        rgb = np.empty((height, width, 3), dtype=float)
        for row in range(height):
            pixel_y = top + row
            for column in range(width):
                color = QColor(image.pixel(left + column, pixel_y))
                rgb[row, column, 0] = color.red()
                rgb[row, column, 1] = color.green()
                rgb[row, column, 2] = color.blue()
        return rgb

    def _run_symbol_detection(self) -> None:
        """Find connected symbol blobs and store weighted barycenters."""
        if self._image.isNull():
            QMessageBox.information(self, "Detect Symbols", "Load an image before detecting symbols.")
            return

        min_area = int(self._symbol_min_area_spin.value())
        max_area = int(self._symbol_max_area_spin.value())
        if max_area < min_area:
            QMessageBox.warning(self, "Detect Symbols", "Max area must be greater than or equal to min area.")
            return

        left, right, top, bottom = self._plot_bounds()
        if right <= left or bottom <= top:
            QMessageBox.warning(self, "Detect Symbols", "The scan area is empty.")
            return

        trace_mode = str(self._trace_mode_combo.currentData())
        threshold = self._threshold_spin.value()
        color_tolerance = self._color_tolerance_spin.value()
        color_tolerance_squared = color_tolerance * color_tolerance
        image_format = getattr(QImage, "Format_RGB32", None)
        if image_format is None:
            image_format = QImage.Format.Format_RGB32
        image = self._image.convertToFormat(image_format)

        scan_left = left + 2 if right - left > 8 else left
        scan_right = right - 2 if right - left > 8 else right
        scan_top = top + 2 if bottom - top > 8 else top
        scan_bottom = bottom - 2 if bottom - top > 8 else bottom
        roi_intervals = self._roi_scan_intervals(scan_left, scan_right, scan_top, scan_bottom)

        matched_pixels: dict[tuple[int, int], float] = {}
        for pixel_x in range(scan_left, scan_right + 1):
            y_ranges = (
                roi_intervals.get(pixel_x, [])
                if roi_intervals is not None
                else [(scan_top, scan_bottom)]
            )
            if not y_ranges:
                continue
            for start_y, end_y in y_ranges:
                for pixel_y in range(start_y, end_y + 1):
                    weight = self._trace_pixel_weight(
                        color=QColor(image.pixel(pixel_x, pixel_y)),
                        trace_mode=trace_mode,
                        dark_threshold=threshold,
                        color_tolerance_squared=color_tolerance_squared,
                    )
                    if weight > 0:
                        matched_pixels[(pixel_x, pixel_y)] = weight

        max_symbols = int(self._symbol_max_count_spin.value())
        components = self._symbol_components(
            matched_pixels=matched_pixels,
            min_area=min_area,
            max_area=max_area,
            max_symbols=max_symbols,
        )
        self._symbol_points = components
        mode_label = "selected color" if trace_mode == "color" else "dark pixels"
        roi_label = f" within {len(self._roi_points)} ROI brush mark(s)" if self._roi_points else ""
        self._symbol_status_label.setText(
            f"Detected {len(components)} symbol center(s) using {mode_label}{roi_label}."
        )
        self._refresh_all()

    def _symbol_components(
        self,
        matched_pixels: dict[tuple[int, int], float],
        min_area: int,
        max_area: int,
        max_symbols: int,
    ) -> list[dict[str, float]]:
        """Return weighted barycenters for connected matched-pixel components."""
        components: list[dict[str, float]] = []
        neighbor_offsets = (
            (-1, -1),
            (-1, 0),
            (-1, 1),
            (0, -1),
            (0, 1),
            (1, -1),
            (1, 0),
            (1, 1),
        )

        while matched_pixels:
            start_pixel, start_weight = matched_pixels.popitem()
            stack = [(start_pixel[0], start_pixel[1], start_weight)]
            area = 0
            weight_sum = 0.0
            weighted_x_sum = 0.0
            weighted_y_sum = 0.0
            x_sum = 0.0
            y_sum = 0.0
            min_x = start_pixel[0]
            max_x = start_pixel[0]
            min_y = start_pixel[1]
            max_y = start_pixel[1]

            while stack:
                pixel_x, pixel_y, weight = stack.pop()
                area += 1
                weight_sum += weight
                weighted_x_sum += pixel_x * weight
                weighted_y_sum += pixel_y * weight
                x_sum += pixel_x
                y_sum += pixel_y
                min_x = min(min_x, pixel_x)
                max_x = max(max_x, pixel_x)
                min_y = min(min_y, pixel_y)
                max_y = max(max_y, pixel_y)
                for dx, dy in neighbor_offsets:
                    neighbor = (pixel_x + dx, pixel_y + dy)
                    neighbor_weight = matched_pixels.pop(neighbor, None)
                    if neighbor_weight is not None:
                        stack.append((neighbor[0], neighbor[1], neighbor_weight))

            if area < min_area or area > max_area:
                continue

            if weight_sum > 0:
                center_x = weighted_x_sum / weight_sum
                center_y = weighted_y_sum / weight_sum
            else:
                center_x = x_sum / area
                center_y = y_sum / area
            components.append(
                {
                    "pixel_x": center_x,
                    "pixel_y": center_y,
                    "area": float(area),
                    "width": float(max_x - min_x + 1),
                    "height": float(max_y - min_y + 1),
                }
            )
            if len(components) >= max_symbols:
                break

        components.sort(key=lambda item: (item["pixel_x"], item["pixel_y"]))
        return components

    def _run_template_symbol_detection(self) -> None:
        """Detect symbols by matching the user-sampled symbol template."""
        if self._image.isNull():
            QMessageBox.information(self, "Detect Sampled Symbols", "Load an image before detecting symbols.")
            return
        if self._symbol_template_weights is None or self._symbol_template_mask is None:
            QMessageBox.information(
                self,
                "Detect Sampled Symbols",
                "Sample one representative symbol before running template detection.",
            )
            return

        left, right, top, bottom = self._plot_bounds()
        if right <= left or bottom <= top:
            QMessageBox.warning(self, "Detect Sampled Symbols", "The scan area is empty.")
            return

        template_weights = np.asarray(self._symbol_template_weights, dtype=float)
        template_height, template_width = template_weights.shape
        scan_left = left + 2 if right - left > 8 else left
        scan_right = right - 2 if right - left > 8 else right
        scan_top = top + 2 if bottom - top > 8 else top
        scan_bottom = bottom - 2 if bottom - top > 8 else bottom
        scan_width = scan_right - scan_left + 1
        scan_height = scan_bottom - scan_top + 1
        if scan_width < template_width or scan_height < template_height:
            QMessageBox.warning(
                self,
                "Detect Sampled Symbols",
                "The sampled symbol template is larger than the scan area.",
            )
            return

        target_weights = self._template_target_weights(scan_left, scan_right, scan_top, scan_bottom)
        if not np.any(target_weights > 0):
            QMessageBox.information(
                self,
                "Detect Sampled Symbols",
                "No pixels matched the sampled symbol color/rule in the scan area.",
            )
            return

        template_energy = float(np.square(template_weights).sum())
        if template_energy <= 0:
            QMessageBox.warning(self, "Detect Sampled Symbols", "The sampled symbol template is empty.")
            return

        numerator = signal.correlate2d(target_weights, template_weights, mode="valid")
        local_energy = signal.correlate2d(
            np.square(target_weights),
            np.ones_like(template_weights, dtype=float),
            mode="valid",
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            score = numerator / np.sqrt(np.maximum(template_energy * local_energy, 1e-12))
        score[~np.isfinite(score)] = 0.0

        detections = self._template_match_detections(
            score=score,
            target_weights=target_weights,
            template_weights=template_weights,
            scan_left=scan_left,
            scan_top=scan_top,
        )
        self._symbol_points = detections
        self._symbol_status_label.setText(
            f"Detected {len(detections)} sampled symbol match(es) "
            f"with score >= {self._symbol_score_threshold_spin.value():.2f}."
        )
        self._refresh_all()

    def _template_target_weights(
        self,
        scan_left: int,
        scan_right: int,
        scan_top: int,
        scan_bottom: int,
    ) -> np.ndarray:
        """Return normalized target weights for sampled-template matching."""
        trace_mode = str(self._trace_mode_combo.currentData())
        threshold = self._threshold_spin.value()
        color_tolerance = self._color_tolerance_spin.value()
        color_tolerance_squared = color_tolerance * color_tolerance
        image_format = getattr(QImage, "Format_RGB32", None)
        if image_format is None:
            image_format = QImage.Format.Format_RGB32
        image = self._image.convertToFormat(image_format)
        roi_intervals = self._roi_scan_intervals(scan_left, scan_right, scan_top, scan_bottom)

        height = scan_bottom - scan_top + 1
        width = scan_right - scan_left + 1
        weights = np.zeros((height, width), dtype=float)
        for pixel_x in range(scan_left, scan_right + 1):
            y_ranges = (
                roi_intervals.get(pixel_x, [])
                if roi_intervals is not None
                else [(scan_top, scan_bottom)]
            )
            if not y_ranges:
                continue
            column_index = pixel_x - scan_left
            for start_y, end_y in y_ranges:
                for pixel_y in range(start_y, end_y + 1):
                    weight = self._trace_pixel_weight(
                        color=QColor(image.pixel(pixel_x, pixel_y)),
                        trace_mode=trace_mode,
                        dark_threshold=threshold,
                        color_tolerance_squared=color_tolerance_squared,
                    )
                    if weight > 0:
                        weights[pixel_y - scan_top, column_index] = weight
        max_weight = float(weights.max())
        if max_weight > 0:
            weights /= max_weight
        return weights

    def _template_match_detections(
        self,
        score: np.ndarray,
        target_weights: np.ndarray,
        template_weights: np.ndarray,
        scan_left: int,
        scan_top: int,
    ) -> list[dict[str, object]]:
        """Convert a template-match score map into refined symbol detections."""
        threshold = float(self._symbol_score_threshold_spin.value())
        max_symbols = int(self._symbol_max_count_spin.value())
        min_separation = float(self._symbol_min_separation_spin.value())
        template_height, template_width = template_weights.shape
        peak_window = max(3, int(round(min_separation)))
        local_max = ndimage.maximum_filter(score, size=peak_window, mode="constant", cval=0.0)
        candidate_mask = (score >= threshold) & (score >= local_max)
        candidate_y, candidate_x = np.nonzero(candidate_mask)
        if candidate_x.size == 0:
            return []

        candidate_scores = score[candidate_y, candidate_x]
        order = np.argsort(candidate_scores)[::-1]
        detections: list[dict[str, object]] = []
        for ordered_index in order:
            peak_y = int(candidate_y[ordered_index])
            peak_x = int(candidate_x[ordered_index])
            peak_score = float(candidate_scores[ordered_index])
            center_x, center_y, matched_area = self._refined_template_center(
                target_weights=target_weights,
                template_weights=template_weights,
                peak_x=peak_x,
                peak_y=peak_y,
                scan_left=scan_left,
                scan_top=scan_top,
            )
            if any(
                (center_x - float(existing["pixel_x"])) ** 2
                + (center_y - float(existing["pixel_y"])) ** 2
                < min_separation * min_separation
                for existing in detections
            ):
                continue

            detections.append(
                {
                    "pixel_x": center_x,
                    "pixel_y": center_y,
                    "area": float(matched_area),
                    "width": float(template_width),
                    "height": float(template_height),
                    "method": "symbol_template",
                    "score": peak_score,
                    "template_width": float(template_width),
                    "template_height": float(template_height),
                }
            )
            if len(detections) >= max_symbols:
                break

        detections.sort(key=lambda item: (float(item["pixel_x"]), float(item["pixel_y"])))
        return detections

    @staticmethod
    def _refined_template_center(
        target_weights: np.ndarray,
        template_weights: np.ndarray,
        peak_x: int,
        peak_y: int,
        scan_left: int,
        scan_top: int,
    ) -> tuple[float, float, int]:
        """Return a local weighted center for one template detection."""
        template_height, template_width = template_weights.shape
        patch = target_weights[peak_y : peak_y + template_height, peak_x : peak_x + template_width]
        if patch.shape != template_weights.shape:
            return (
                scan_left + peak_x + (template_width - 1) / 2.0,
                scan_top + peak_y + (template_height - 1) / 2.0,
                0,
            )
        matched = patch * template_weights
        total = float(matched.sum())
        if total <= 0:
            return (
                scan_left + peak_x + (template_width - 1) / 2.0,
                scan_top + peak_y + (template_height - 1) / 2.0,
                int(np.count_nonzero(patch > 0)),
            )
        yy, xx = np.indices(template_weights.shape, dtype=float)
        center_x = scan_left + peak_x + float((xx * matched).sum() / total)
        center_y = scan_top + peak_y + float((yy * matched).sum() / total)
        return center_x, center_y, int(np.count_nonzero(patch > 0))

    def _run_auto_trace(self) -> None:
        """Extract a simple dark-pixel trace inside the calibrated plot bounds."""
        if self._image.isNull():
            QMessageBox.information(self, "Auto Trace", "Load an image before tracing.")
            return

        left, right, top, bottom = self._plot_bounds()
        if right <= left or bottom <= top:
            QMessageBox.warning(self, "Auto Trace", "The scan area is empty.")
            return

        step = self._x_step_spin.value()
        trace_mode = str(self._trace_mode_combo.currentData())
        threshold = self._threshold_spin.value()
        color_tolerance = self._color_tolerance_spin.value()
        color_tolerance_squared = color_tolerance * color_tolerance
        image_format = getattr(QImage, "Format_RGB32", None)
        if image_format is None:
            image_format = QImage.Format.Format_RGB32
        image = self._image.convertToFormat(image_format)

        scan_left = left + 2 if right - left > 8 else left
        scan_right = right - 2 if right - left > 8 else right
        scan_top = top + 2 if bottom - top > 8 else top
        scan_bottom = bottom - 2 if bottom - top > 8 else bottom
        roi_intervals = self._roi_scan_intervals(scan_left, scan_right, scan_top, scan_bottom)

        points: list[tuple[float, float]] = []
        for pixel_x in range(scan_left, scan_right + 1, step):
            y_ranges = (
                roi_intervals.get(pixel_x, [])
                if roi_intervals is not None
                else [(scan_top, scan_bottom)]
            )
            if not y_ranges:
                continue
            matching_y: list[int] = []
            for start_y, end_y in y_ranges:
                for pixel_y in range(start_y, end_y + 1):
                    color = QColor(image.pixel(pixel_x, pixel_y))
                    if self._trace_color_matches(
                        color=color,
                        trace_mode=trace_mode,
                        dark_threshold=threshold,
                        color_tolerance_squared=color_tolerance_squared,
                    ):
                        matching_y.append(pixel_y)
            if matching_y:
                matching_y.sort()
                points.append((float(pixel_x), float(matching_y[len(matching_y) // 2])))

        mode_label = "selected color" if trace_mode == "color" else "dark pixels"
        roi_label = f" within {len(self._roi_points)} ROI brush mark(s)" if self._roi_points else ""
        self._auto_points = points
        self._auto_status_label.setText(
            f"Auto trace found {len(points)} point(s) using {mode_label}{roi_label} "
            f"in pixels x={scan_left}..{scan_right}, y={scan_top}..{scan_bottom}."
        )
        self._refresh_all()

    def _trace_color_matches(
        self,
        color: QColor,
        trace_mode: str,
        dark_threshold: int,
        color_tolerance_squared: int,
    ) -> bool:
        """Return whether one image color should be treated as trace data."""
        return self._trace_pixel_weight(
            color=color,
            trace_mode=trace_mode,
            dark_threshold=dark_threshold,
            color_tolerance_squared=color_tolerance_squared,
        ) > 0

    def _trace_pixel_weight(
        self,
        color: QColor,
        trace_mode: str,
        dark_threshold: int,
        color_tolerance_squared: int,
    ) -> float:
        """Return a positive extraction weight for matched trace pixels."""
        if trace_mode == "color":
            red_diff = color.red() - self._trace_color.red()
            green_diff = color.green() - self._trace_color.green()
            blue_diff = color.blue() - self._trace_color.blue()
            distance_squared = red_diff * red_diff + green_diff * green_diff + blue_diff * blue_diff
            if distance_squared <= color_tolerance_squared:
                return float(max(1, color_tolerance_squared - distance_squared + 1))
            return 0.0
        gray = (299 * color.red() + 587 * color.green() + 114 * color.blue()) // 1000
        if gray <= dark_threshold:
            return float(256 - gray)
        return 0.0

    def _roi_scan_intervals(
        self,
        left: int,
        right: int,
        top: int,
        bottom: int,
    ) -> dict[int, list[tuple[int, int]]] | None:
        """Return merged y-intervals per x pixel for brushed ROI marks."""
        if not self._roi_points:
            return None

        intervals_by_x: dict[int, list[tuple[int, int]]] = {}
        for center_x, center_y, radius in self._roi_points:
            radius_squared = radius * radius
            start_x = max(left, int(math.floor(center_x - radius)))
            end_x = min(right, int(math.ceil(center_x + radius)))
            for pixel_x in range(start_x, end_x + 1):
                dx = pixel_x - center_x
                remaining = radius_squared - dx * dx
                if remaining < 0:
                    continue
                dy = math.sqrt(remaining)
                start_y = max(top, int(math.floor(center_y - dy)))
                end_y = min(bottom, int(math.ceil(center_y + dy)))
                if start_y <= end_y:
                    intervals_by_x.setdefault(pixel_x, []).append((start_y, end_y))

        for pixel_x, intervals in list(intervals_by_x.items()):
            intervals.sort()
            merged: list[tuple[int, int]] = []
            for start_y, end_y in intervals:
                if not merged or start_y > merged[-1][1] + 1:
                    merged.append((start_y, end_y))
                else:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end_y))
            intervals_by_x[pixel_x] = merged
        return intervals_by_x

    def _plot_bounds(self) -> tuple[int, int, int, int]:
        """Return full-image scan bounds; axis references only define scale."""
        if self._image.isNull():
            return (0, 0, 0, 0)
        return (0, self._image.width() - 1, 0, self._image.height() - 1)

    def _refresh_all(self) -> None:
        """Refresh markers, calibration status, and preview."""
        self._refresh_manual_target_selector()
        self._redraw_markers()
        self._refresh_warp_status()
        self._refresh_calibration_status()
        self._refresh_roi_status()
        self._refresh_tool_mode_label()
        self._refresh_cursor_preview()
        self._refresh_preview()

    def _redraw_markers(self) -> None:
        """Redraw calibration, manual, and automatic point markers."""
        for item in self._marker_items:
            self._scene.removeItem(item)
        self._marker_items.clear()

        if self._symbol_sample_preview_rect is not None:
            self._add_template_rect_marker(
                self._symbol_sample_preview_rect,
                tooltip="Symbol sample preview",
                color="#0ea5e9",
                alpha=30,
            )
        if self._symbol_template_rect is not None:
            self._add_template_rect_marker(self._symbol_template_rect)
        self._add_warp_markers()
        for index, (pixel_x, pixel_y, radius) in enumerate(self._roi_points, start=1):
            self._add_roi_marker(pixel_x, pixel_y, radius, f"ROI brush mark {index}")
        for key, label in self._CALIBRATION_KEYS:
            point = self._calibration_pixels.get(key)
            if point is not None:
                self._add_marker(point[0], point[1], "#f59e0b", label)
        for index, manual_point in enumerate(self._manual_points, start=1):
            pixel_x, pixel_y = self._manual_point_xy(manual_point)
            self._add_marker(pixel_x, pixel_y, "#2563eb", f"Manual point {index}")
            pixel_x_uncertainty = self._manual_point_uncertainty(manual_point, "pixel_x_uncertainty")
            pixel_y_uncertainty = self._manual_point_uncertainty(manual_point, "pixel_y_uncertainty")
            if pixel_x_uncertainty is not None or pixel_y_uncertainty is not None:
                self._add_error_bar_marker(
                    pixel_x,
                    pixel_y,
                    pixel_x_uncertainty or 0.0,
                    pixel_y_uncertainty or 0.0,
                    "#2563eb",
                    f"Manual point {index} uncertainty",
                )
        for index, (pixel_x, pixel_y) in enumerate(self._auto_points, start=1):
            self._add_marker(pixel_x, pixel_y, "#dc2626", f"Auto trace point {index}", radius=2.5)
        for index, symbol in enumerate(self._symbol_points, start=1):
            self._add_cross_marker(
                float(symbol["pixel_x"]),
                float(symbol["pixel_y"]),
                "#7c3aed",
                f"Symbol center {index}",
            )

    def _add_warp_markers(self) -> None:
        """Draw perspective correction corner markers and connecting edges."""
        if not self._warp_pixels:
            return
        ordered_points = [
            self._warp_pixels[key]
            for key, _label in self._WARP_KEYS
            if key in self._warp_pixels
        ]
        for key, label in self._WARP_KEYS:
            point = self._warp_pixels.get(key)
            if point is not None:
                self._add_marker(point[0], point[1], "#16a34a", label, radius=5.0)
        if len(ordered_points) < 2:
            return
        pen = QPen(QColor("#16a34a"), 1.6)
        pen_color = QColor("#16a34a")
        pen_color.setAlpha(190)
        pen.setColor(pen_color)
        for first, second in zip(ordered_points, ordered_points[1:]):
            item = QGraphicsLineItem(first[0], first[1], second[0], second[1])
            item.setPen(pen)
            item.setToolTip("Perspective correction edge")
            item.setZValue(8)
            self._scene.addItem(item)
            self._marker_items.append(item)
        if len(ordered_points) == len(self._WARP_KEYS):
            first = ordered_points[-1]
            second = ordered_points[0]
            item = QGraphicsLineItem(first[0], first[1], second[0], second[1])
            item.setPen(pen)
            item.setToolTip("Perspective correction edge")
            item.setZValue(8)
            self._scene.addItem(item)
            self._marker_items.append(item)

    def _add_marker(
        self,
        pixel_x: float,
        pixel_y: float,
        color: str,
        tooltip: str,
        radius: float = 4.5,
    ) -> None:
        """Add one circular marker to the graphics scene."""
        item = QGraphicsEllipseItem(pixel_x - radius, pixel_y - radius, radius * 2, radius * 2)
        item.setPen(QPen(QColor("#111827"), 1.2))
        item.setBrush(QBrush(QColor(color)))
        item.setToolTip(tooltip)
        item.setZValue(10)
        self._scene.addItem(item)
        self._marker_items.append(item)

    def _add_cross_marker(
        self,
        pixel_x: float,
        pixel_y: float,
        color: str,
        tooltip: str,
        radius: float = 4.0,
    ) -> None:
        """Add a small X marker centered on a detected point."""
        pen = QPen(QColor(color), 1.5)
        first = QGraphicsLineItem(pixel_x - radius, pixel_y - radius, pixel_x + radius, pixel_y + radius)
        second = QGraphicsLineItem(pixel_x - radius, pixel_y + radius, pixel_x + radius, pixel_y - radius)
        for item in (first, second):
            item.setPen(pen)
            item.setToolTip(tooltip)
            item.setZValue(11)
            self._scene.addItem(item)
            self._marker_items.append(item)

    def _add_error_bar_marker(
        self,
        pixel_x: float,
        pixel_y: float,
        pixel_x_uncertainty: float,
        pixel_y_uncertainty: float,
        color: str,
        tooltip: str,
    ) -> None:
        """Add simple cross error bars around a point."""
        pen = QPen(QColor(color), 1.1)
        pen_color = QColor(color)
        pen_color.setAlpha(170)
        pen.setColor(pen_color)
        items: list[QGraphicsLineItem] = []
        if pixel_x_uncertainty > 0:
            items.append(
                QGraphicsLineItem(
                    pixel_x - pixel_x_uncertainty,
                    pixel_y,
                    pixel_x + pixel_x_uncertainty,
                    pixel_y,
                )
            )
        if pixel_y_uncertainty > 0:
            items.append(
                QGraphicsLineItem(
                    pixel_x,
                    pixel_y - pixel_y_uncertainty,
                    pixel_x,
                    pixel_y + pixel_y_uncertainty,
                )
            )
        for item in items:
            item.setPen(pen)
            item.setToolTip(tooltip)
            item.setZValue(9)
            self._scene.addItem(item)
            self._marker_items.append(item)

    def _add_template_rect_marker(
        self,
        rect: tuple[int, int, int, int],
        tooltip: str = "Sampled symbol template",
        color: str = "#7c3aed",
        alpha: int = 35,
    ) -> None:
        """Add a rectangle marker around the sampled symbol template."""
        left, top, width, height = rect
        item = QGraphicsRectItem(float(left), float(top), float(width), float(height))
        item.setPen(QPen(QColor(color), 1.4))
        fill_color = QColor(color)
        fill_color.setAlpha(alpha)
        item.setBrush(QBrush(fill_color))
        item.setToolTip(tooltip)
        item.setZValue(6)
        self._scene.addItem(item)
        self._marker_items.append(item)

    def _add_roi_marker(
        self,
        pixel_x: float,
        pixel_y: float,
        radius: float,
        tooltip: str,
    ) -> None:
        """Add one translucent ROI brush marker to the graphics scene."""
        item = QGraphicsEllipseItem(pixel_x - radius, pixel_y - radius, radius * 2, radius * 2)
        fill_color = QColor("#22c55e")
        fill_color.setAlpha(35)
        no_pen = getattr(Qt, "NoPen", None)
        if no_pen is None:
            no_pen = Qt.PenStyle.NoPen
        item.setPen(QPen(no_pen))
        item.setBrush(QBrush(fill_color))
        item.setToolTip(tooltip)
        item.setZValue(4)
        self._scene.addItem(item)
        self._marker_items.append(item)

    def _refresh_calibration_status(self) -> None:
        """Update calibration status text."""
        missing = [
            label
            for key, label in self._CALIBRATION_KEYS
            if key not in self._calibration_pixels
        ]
        values, errors = self._calibration_values()
        if missing:
            self._calibration_status_label.setText("Missing: " + ", ".join(missing))
            return
        if values is None or errors:
            self._calibration_status_label.setText("\n".join(errors))
            return
        self._calibration_status_label.setText("Calibration ready.")

    def _refresh_roi_status(self) -> None:
        """Update ROI brush status text."""
        if not hasattr(self, "_roi_status_label"):
            return
        if self._roi_points:
            self._roi_status_label.setText(
                f"{len(self._roi_points)} ROI brush mark(s). Auto trace is restricted to the painted region."
            )
        else:
            self._roi_status_label.setText("No ROI brush marks. Auto trace scans the full working image.")

    def _refresh_cursor_preview(self) -> None:
        """Update cursor coordinate text and magnifier crop."""
        if not hasattr(self, "_magnifier_label"):
            return
        if self._image.isNull() or self._cursor_pixel is None:
            self._magnifier_label.setText("Move over image")
            self._cursor_status_label.setText("Pixel: -")
            return

        pixel_x, pixel_y = self._cursor_pixel
        pixel_x_int = min(max(0, int(round(pixel_x))), self._image.width() - 1)
        pixel_y_int = min(max(0, int(round(pixel_y))), self._image.height() - 1)
        zoom = max(2, int(self._magnifier_zoom_spin.value()))
        preview_size = max(80, self._magnifier_label.width())
        half_width = max(2, int(preview_size / (2 * zoom)))
        left = max(0, pixel_x_int - half_width)
        top = max(0, pixel_y_int - half_width)
        right = min(self._image.width(), pixel_x_int + half_width + 1)
        bottom = min(self._image.height(), pixel_y_int + half_width + 1)
        crop = self._image.copy(left, top, right - left, bottom - top)
        pixmap = QPixmap.fromImage(crop).scaled(preview_size, preview_size)

        painter = QPainter(pixmap)
        center = preview_size // 2
        painter.setPen(QPen(QColor("#ef4444"), 1))
        painter.drawLine(center, 0, center, preview_size)
        painter.drawLine(0, center, preview_size, center)
        painter.end()
        self._magnifier_label.setPixmap(pixmap)

        data = self._pixel_to_data(pixel_x, pixel_y)
        if data is None:
            self._cursor_status_label.setText(f"Pixel: ({pixel_x:.2f}, {pixel_y:.2f})")
        else:
            self._cursor_status_label.setText(
                f"Pixel: ({pixel_x:.2f}, {pixel_y:.2f})\n"
                f"Data: ({data[0]:.10g}, {data[1]:.10g})"
            )

    def _refresh_preview(self) -> None:
        """Refresh the extracted point preview table."""
        rows = self.extracted_rows()
        preview_limit = 2000
        shown_rows = rows[:preview_limit]
        self._preview_table.setRowCount(len(shown_rows))
        for row_index, row in enumerate(shown_rows):
            values = [
                row.get("method", ""),
                self._format_number(row.get("x")),
                self._format_number(row.get("y")),
                self._format_number(row.get("x_uncertainty")),
                self._format_number(row.get("y_uncertainty")),
                self._format_number(row.get("pixel_x")),
                self._format_number(row.get("pixel_y")),
                self._format_number(row.get("pixel_x_uncertainty")),
                self._format_number(row.get("pixel_y_uncertainty")),
                row.get("trace_mode", ""),
                row.get("trace_color", ""),
                row.get("roi_marks", ""),
                row.get("symbol_id", ""),
                row.get("symbol_area", ""),
                self._format_number(row.get("symbol_score")),
                self._symbol_size_text(row),
                self._symbol_template_size_text(row),
                os.path.basename(str(row.get("source_image", ""))),
            ]
            for column_index, value in enumerate(values):
                self._preview_table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
        if len(rows) > preview_limit:
            self._preview_status_label.setText(
                f"{len(rows)} extracted point(s); showing first {preview_limit}."
            )
        elif rows:
            self._preview_status_label.setText(f"{len(rows)} extracted point(s).")
        else:
            self._preview_status_label.setText("No extracted points.")

    def _calibration_values(self) -> tuple[dict[str, float] | None, list[str]]:
        """Parse and validate calibration values and picked pixels."""
        errors: list[str] = []
        missing = [
            label
            for key, label in self._CALIBRATION_KEYS
            if key not in self._calibration_pixels
        ]
        if missing:
            errors.append("Pick calibration points: " + ", ".join(missing))

        values: dict[str, float] = {}
        for key, label, edit in (
            ("x1", "X point 1", self._x1_value_edit),
            ("x2", "X point 2", self._x2_value_edit),
            ("y1", "Y point 1", self._y1_value_edit),
            ("y2", "Y point 2", self._y2_value_edit),
        ):
            try:
                values[key] = float(edit.text().strip())
            except ValueError:
                errors.append(f"{label} value must be numeric.")

        if "x1" in self._calibration_pixels and "x2" in self._calibration_pixels:
            if abs(self._calibration_pixels["x2"][0] - self._calibration_pixels["x1"][0]) < 1e-12:
                errors.append("X calibration points must have different pixel X positions.")
        if "y1" in self._calibration_pixels and "y2" in self._calibration_pixels:
            if abs(self._calibration_pixels["y2"][1] - self._calibration_pixels["y1"][1]) < 1e-12:
                errors.append("Y calibration points must have different pixel Y positions.")

        if str(self._x_scale_combo.currentData()) == "log":
            if values.get("x1", 0.0) <= 0 or values.get("x2", 0.0) <= 0:
                errors.append("Log X calibration values must be positive.")
        if str(self._y_scale_combo.currentData()) == "log":
            if values.get("y1", 0.0) <= 0 or values.get("y2", 0.0) <= 0:
                errors.append("Log Y calibration values must be positive.")

        return (None if errors else values, errors)

    def _pixel_to_data(self, pixel_x: float, pixel_y: float) -> tuple[float, float] | None:
        """Convert one pixel coordinate to calibrated data coordinates."""
        values, errors = self._calibration_values()
        if values is None or errors:
            return None
        x_value = self._axis_value(
            pixel_x,
            self._calibration_pixels["x1"][0],
            values["x1"],
            self._calibration_pixels["x2"][0],
            values["x2"],
            str(self._x_scale_combo.currentData()),
        )
        y_value = self._axis_value(
            pixel_y,
            self._calibration_pixels["y1"][1],
            values["y1"],
            self._calibration_pixels["y2"][1],
            values["y2"],
            str(self._y_scale_combo.currentData()),
        )
        return x_value, y_value

    @staticmethod
    def _symbol_pixel_uncertainty(symbol: dict[str, object]) -> tuple[float, float]:
        """Estimate symbol-center uncertainty in pixels from detected/template size."""
        width_value = symbol.get("template_width", symbol.get("width", 1.0))
        height_value = symbol.get("template_height", symbol.get("height", 1.0))
        try:
            width = float(width_value)
        except (TypeError, ValueError):
            width = 1.0
        try:
            height = float(height_value)
        except (TypeError, ValueError):
            height = 1.0
        if not math.isfinite(width) or width <= 0:
            width = 1.0
        if not math.isfinite(height) or height <= 0:
            height = 1.0
        return max(0.5, width / 2.0), max(0.5, height / 2.0)

    def _pixel_uncertainty_to_data(
        self,
        pixel_x: float,
        pixel_y: float,
        pixel_x_uncertainty: float | None,
        pixel_y_uncertainty: float | None,
    ) -> tuple[float | None, float | None]:
        """Convert symmetric pixel uncertainty into calibrated X/Y uncertainty."""
        values, errors = self._calibration_values()
        if values is None or errors:
            return None, None
        if pixel_x_uncertainty is None or pixel_y_uncertainty is None:
            return None, None

        x_low = self._axis_value(
            pixel_x - pixel_x_uncertainty,
            self._calibration_pixels["x1"][0],
            values["x1"],
            self._calibration_pixels["x2"][0],
            values["x2"],
            str(self._x_scale_combo.currentData()),
        )
        x_high = self._axis_value(
            pixel_x + pixel_x_uncertainty,
            self._calibration_pixels["x1"][0],
            values["x1"],
            self._calibration_pixels["x2"][0],
            values["x2"],
            str(self._x_scale_combo.currentData()),
        )
        y_low = self._axis_value(
            pixel_y - pixel_y_uncertainty,
            self._calibration_pixels["y1"][1],
            values["y1"],
            self._calibration_pixels["y2"][1],
            values["y2"],
            str(self._y_scale_combo.currentData()),
        )
        y_high = self._axis_value(
            pixel_y + pixel_y_uncertainty,
            self._calibration_pixels["y1"][1],
            values["y1"],
            self._calibration_pixels["y2"][1],
            values["y2"],
            str(self._y_scale_combo.currentData()),
        )
        return abs(x_high - x_low) / 2.0, abs(y_high - y_low) / 2.0

    @staticmethod
    def _axis_value(
        pixel: float,
        pixel_1: float,
        value_1: float,
        pixel_2: float,
        value_2: float,
        scale: str,
    ) -> float:
        """Map one pixel coordinate onto a linear or log axis."""
        fraction = (pixel - pixel_1) / (pixel_2 - pixel_1)
        if scale == "log":
            log_value = math.log10(value_1) + fraction * (math.log10(value_2) - math.log10(value_1))
            return 10 ** log_value
        return value_1 + fraction * (value_2 - value_1)

    @staticmethod
    def _format_number(value: object) -> str:
        """Format a preview number without excessive digits."""
        if value is None:
            return ""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if not math.isfinite(number):
            return ""
        return f"{number:.10g}"

    @staticmethod
    def _symbol_size_text(row: dict[str, object]) -> str:
        """Return a compact symbol width x height preview."""
        width = row.get("symbol_width", "")
        height = row.get("symbol_height", "")
        if width == "" or height == "":
            return ""
        return f"{width} x {height}"

    @staticmethod
    def _symbol_template_size_text(row: dict[str, object]) -> str:
        """Return a compact sampled-template width x height preview."""
        width = row.get("symbol_template_width", "")
        height = row.get("symbol_template_height", "")
        if width == "" or height == "":
            return ""
        return f"{width} x {height}"


class ColorPlotDigitizerDialog(FigureDigitizerDialog):
    """Extract calibrated X/Y/Z probes from a raster colour plot or heatmap."""

    _DISCLAIMER = (
        "Accuracy notice: extracted colour values are estimates from rendered pixels. "
        "Image compression, anti-aliasing, resizing, overlays, and limited palette "
        "resolution can introduce unavoidable error. Review distance, confidence, and "
        "ambiguity diagnostics before using the data."
    )

    def __init__(
        self,
        image_path: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the colour-plot extraction workspace."""
        self._colorbar_pixels: dict[str, tuple[float, float]] = {}
        self._color_probes: list[tuple[float, float]] = []
        self._color_scale_cache: ColorScaleCalibration | None = None
        self._color_palette_cache: np.ndarray | None = None
        self._color_image_rgb_cache: np.ndarray | None = None
        super().__init__(image_path, parent)
        self.setWindowTitle("Import From Figure - 2D Colour Plot")

    def extraction_kind(self) -> str:
        """Return the colour-plot workflow identifier."""
        return "colorplot"

    def dataset_name(self) -> str:
        """Return the requested output dataset name."""
        return self._dataset_name_edit.text().strip() or "Digitized Colour Plot"

    def load_image(self, image_path: str) -> None:
        """Load a raster image and choose a colour-plot-specific default name."""
        super().load_image(image_path)
        if not self._image.isNull():
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            if self._dataset_name_edit.text().strip() == f"{base_name}_digitized":
                self._dataset_name_edit.setText(f"{base_name}_colourplot")

    def _set_working_image(self, image: QImage, reset_view: bool = True) -> None:
        """Replace the canvas image and invalidate its cached RGB array."""
        self._color_image_rgb_cache = None
        super()._set_working_image(image, reset_view)

    def _color_image_rgb(self) -> np.ndarray:
        """Return one cached RGB array for repeated palette and probe sampling."""
        if self._color_image_rgb_cache is None:
            self._color_image_rgb_cache = self._qimage_to_rgb_array(self._image)
        return self._color_image_rgb_cache

    def _build_calibration_tab(self) -> QWidget:
        """Build shared X/Y calibration plus empirical colour-bar controls."""
        tab = super()._build_calibration_tab()
        irrelevant_targets = {
            "manual",
            "manual_error_radius",
            "manual_error_four",
            "roi_brush",
            "trace_color",
            "symbol_sample",
        }
        for index in reversed(range(self._click_target_combo.count())):
            if str(self._click_target_combo.itemData(index)) in irrelevant_targets:
                self._click_target_combo.removeItem(index)
        self._click_target_combo.addItem("Colour scale: low-value end", "colorbar_low")
        self._click_target_combo.addItem("Colour scale: high-value end", "colorbar_high")
        self._click_target_combo.addItem("Colour-value probe", "color_probe")

        self._color_low_value_edit = QLineEdit("0")
        self._color_high_value_edit = QLineEdit("1")
        self._color_scale_combo = QComboBox()
        self._color_scale_combo.addItem("Linear", "linear")
        self._color_scale_combo.addItem("Log10", "log")
        self._colorbar_width_spin = QSpinBox()
        self._colorbar_width_spin.setRange(1, 31)
        self._colorbar_width_spin.setSingleStep(2)
        self._colorbar_width_spin.setValue(5)
        self._colorbar_width_spin.setSuffix(" px")
        self._colorbar_samples_spin = QSpinBox()
        self._colorbar_samples_spin.setRange(16, 2048)
        self._colorbar_samples_spin.setValue(256)
        self._maximum_color_distance_spin = QDoubleSpinBox()
        self._maximum_color_distance_spin.setRange(1.0, 100.0)
        self._maximum_color_distance_spin.setDecimals(1)
        self._maximum_color_distance_spin.setValue(18.0)
        self._maximum_color_distance_spin.setToolTip(
            "Maximum CIE Lab distance accepted as a valid palette match."
        )
        for edit in (self._color_low_value_edit, self._color_high_value_edit):
            edit.textChanged.connect(self._invalidate_color_scale)
        for control in (
            self._color_scale_combo,
            self._colorbar_width_spin,
            self._colorbar_samples_spin,
            self._maximum_color_distance_spin,
        ):
            if isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self._invalidate_color_scale)
            else:
                control.valueChanged.connect(self._invalidate_color_scale)

        pick_low_button = QPushButton("Pick Low End")
        pick_low_button.clicked.connect(lambda: self._set_click_target("colorbar_low"))
        pick_high_button = QPushButton("Pick High End")
        pick_high_button.clicked.connect(lambda: self._set_click_target("colorbar_high"))
        rebuild_button = QPushButton("Rebuild Scale")
        rebuild_button.clicked.connect(lambda: self._rebuild_color_scale(show_errors=True))
        clear_button = QPushButton("Clear Scale")
        clear_button.clicked.connect(self._clear_color_scale)

        color_group = QGroupBox("Displayed Colour Scale")
        color_layout = QFormLayout(color_group)
        color_layout.addRow("Low-end value", self._color_low_value_edit)
        color_layout.addRow("High-end value", self._color_high_value_edit)
        color_layout.addRow("Value normalization", self._color_scale_combo)
        color_layout.addRow("Bar sample width", self._colorbar_width_spin)
        color_layout.addRow("Palette samples", self._colorbar_samples_spin)
        color_layout.addRow("Maximum Lab distance", self._maximum_color_distance_spin)
        pick_row = QHBoxLayout()
        pick_row.addWidget(pick_low_button)
        pick_row.addWidget(pick_high_button)
        color_layout.addRow(pick_row)
        build_row = QHBoxLayout()
        build_row.addWidget(rebuild_button)
        build_row.addWidget(clear_button)
        color_layout.addRow(build_row)
        self._color_palette_label = QLabel("Pick both ends of the colour bar.")
        self._color_palette_label.setAlignment(Qt.AlignCenter)
        self._color_palette_label.setMinimumHeight(34)
        self._color_palette_label.setStyleSheet(
            "QLabel { background: #f3f4f6; border: 1px solid #9ca3af; padding: 4px; }"
        )
        self._color_scale_status_label = QLabel("Colour scale is not calibrated.")
        self._color_scale_status_label.setWordWrap(True)
        color_layout.addRow("Sampled palette", self._color_palette_label)
        color_layout.addRow(self._color_scale_status_label)

        layout = tab.layout()
        if isinstance(layout, QVBoxLayout):
            stretch_item = layout.takeAt(layout.count() - 1)
            layout.addWidget(color_group)
            if stretch_item is not None:
                layout.addItem(stretch_item)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(tab)
        return scroll

    def _build_extraction_tab(self) -> QWidget:
        """Build click-probe controls and an unavoidable accuracy disclaimer."""
        tab = QWidget()
        disclaimer = QLabel(self._DISCLAIMER)
        disclaimer.setObjectName("colorExtractionDisclaimer")
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            "QLabel { background: #fff7ed; color: #7c2d12; border: 1px solid #fb923c; "
            "border-radius: 4px; padding: 8px; }"
        )

        probe_group = QGroupBox("Point Probes")
        probe_layout = QFormLayout(probe_group)
        self._probe_patch_radius_spin = QSpinBox()
        self._probe_patch_radius_spin.setRange(0, 10)
        self._probe_patch_radius_spin.setValue(1)
        self._probe_patch_radius_spin.setSuffix(" px")
        self._probe_patch_radius_spin.setToolTip(
            "Median RGB is taken from this radius around each click to reduce single-pixel noise."
        )
        self._probe_patch_radius_spin.valueChanged.connect(self._refresh_preview)
        button_row = QHBoxLayout()
        start_button = QPushButton("Start Probing")
        start_button.clicked.connect(lambda: self._set_click_target("color_probe"))
        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(lambda: self._set_click_target("none"))
        button_row.addWidget(start_button)
        button_row.addWidget(stop_button)
        edit_row = QHBoxLayout()
        undo_button = QPushButton("Undo Last")
        undo_button.clicked.connect(self._undo_color_probe)
        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self._remove_selected_color_probes)
        clear_button = QPushButton("Clear Probes")
        clear_button.clicked.connect(self._clear_color_probes)
        edit_row.addWidget(undo_button)
        edit_row.addWidget(remove_button)
        edit_row.addWidget(clear_button)
        self._color_probe_status_label = QLabel("No colour-value probes.")
        self._color_probe_status_label.setWordWrap(True)
        probe_layout.addRow("Median patch radius", self._probe_patch_radius_spin)
        probe_layout.addRow(button_row)
        probe_layout.addRow(edit_row)
        probe_layout.addRow(self._color_probe_status_label)

        instructions = QLabel(
            "Workflow: calibrate X and Y, pick the low- and high-value centres of the "
            "displayed colour bar, enter their values, rebuild the scale, then start "
            "probing and click locations in the colour plot."
        )
        instructions.setWordWrap(True)

        layout = QVBoxLayout(tab)
        layout.addWidget(instructions)
        layout.addWidget(disclaimer)
        layout.addWidget(probe_group)
        layout.addStretch()
        return tab

    def _build_output_tab(self) -> QWidget:
        """Build the colour-probe output preview."""
        tab = QWidget()
        self._dataset_name_edit = QLineEdit("digitized_colourplot")
        self._preview_table = QTableWidget(0, 13)
        self._preview_table.setHorizontalHeaderLabels(
            [
                "X",
                "Y",
                "Z",
                "Pixel X",
                "Pixel Y",
                "R",
                "G",
                "B",
                "Palette",
                "Distance",
                "Confidence",
                "Ambiguous",
                "Valid",
            ]
        )
        self._preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._preview_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._preview_table.setAlternatingRowColors(True)
        self._preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._preview_table.horizontalHeader().setStretchLastSection(True)
        self._preview_status_label = QLabel("No extracted points.")
        self._preview_status_label.setWordWrap(True)

        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Dataset name"))
        layout.addWidget(self._dataset_name_edit)
        layout.addWidget(self._build_multi_curve_controls())
        layout.addWidget(self._preview_table, 1)
        layout.addWidget(self._preview_status_label)
        return tab

    def _handle_canvas_click(self, pixel_x: float, pixel_y: float) -> None:
        """Route colour-scale and probe clicks, delegating shared calibration clicks."""
        if self._image.isNull():
            return
        if pixel_x < 0 or pixel_y < 0 or pixel_x >= self._image.width() or pixel_y >= self._image.height():
            return
        target = str(self._click_target_combo.currentData())
        if target == "colorbar_low":
            self._colorbar_pixels["low"] = (float(pixel_x), float(pixel_y))
            self._invalidate_color_scale(refresh=False)
            self._set_click_target("colorbar_high")
        elif target == "colorbar_high":
            self._colorbar_pixels["high"] = (float(pixel_x), float(pixel_y))
            self._invalidate_color_scale(refresh=False)
            self._rebuild_color_scale(show_errors=False)
            self._set_click_target("color_probe")
        elif target == "color_probe":
            self._color_probes.append((float(pixel_x), float(pixel_y)))
            self._color_probe_status_label.setText(
                f"{len(self._color_probes)} probe(s). Select rows in Output to remove individual probes."
            )
        else:
            super()._handle_canvas_click(pixel_x, pixel_y)
            return
        self._refresh_all()

    def _refresh_tool_mode_label(self) -> None:
        """Show colour-specific picking modes in the shared canvas banner."""
        super()._refresh_tool_mode_label()
        if not hasattr(self, "_click_target_combo") or self._image.isNull():
            return
        if getattr(self, "_pan_checkbox", None) is not None and self._pan_checkbox.isChecked():
            return
        target = str(self._click_target_combo.currentData())
        if target == "colorbar_low":
            self._tool_mode_label.setText("Mode: Colour scale low end - click the centre of its low-value end.")
        elif target == "colorbar_high":
            self._tool_mode_label.setText("Mode: Colour scale high end - click the centre of its high-value end.")
        elif target == "color_probe":
            self._tool_mode_label.setText("Mode: Colour-value probe - click the colour plot to add X/Y/Z samples.")

    def _clear_digitized_points(self) -> None:
        """Clear shared calibration and colour state tied to image pixels."""
        super()._clear_digitized_points()
        self._colorbar_pixels.clear()
        self._color_probes.clear()
        self._color_scale_cache = None
        self._color_palette_cache = None
        if hasattr(self, "_color_scale_status_label"):
            self._color_scale_status_label.setText("Colour scale is not calibrated.")
        if hasattr(self, "_color_palette_label"):
            self._color_palette_label.setPixmap(QPixmap())
            self._color_palette_label.setText("Pick both ends of the colour bar.")
        if hasattr(self, "_color_probe_status_label"):
            self._color_probe_status_label.setText("No colour-value probes.")

    def _clear_color_scale(self) -> None:
        """Remove sampled colour-bar endpoints and cached calibration."""
        self._colorbar_pixels.clear()
        self._color_scale_cache = None
        self._color_palette_cache = None
        self._color_palette_label.setPixmap(QPixmap())
        self._color_palette_label.setText("Pick both ends of the colour bar.")
        self._color_scale_status_label.setText("Colour scale is not calibrated.")
        self._set_click_target("colorbar_low")
        self._refresh_all()

    def _invalidate_color_scale(self, _value: object = None, refresh: bool = True) -> None:
        """Discard cached palette values after a calibration-control change."""
        self._color_scale_cache = None
        self._color_palette_cache = None
        if hasattr(self, "_color_scale_status_label"):
            self._color_scale_status_label.setText("Colour-scale settings changed; rebuild or continue to preview.")
        if refresh and hasattr(self, "_preview_table"):
            self._refresh_preview()
            self._refresh_cursor_preview()

    def _color_endpoint_values(self) -> tuple[float, float]:
        """Parse colour-scale endpoint values."""
        try:
            low_value = float(self._color_low_value_edit.text().strip())
            high_value = float(self._color_high_value_edit.text().strip())
        except ValueError as exc:
            raise ValueError("Colour-scale endpoint values must be numeric.") from exc
        return low_value, high_value

    def _sample_colorbar_palette(self) -> np.ndarray:
        """Sample a median RGB stripe along the picked colour-bar segment."""
        if self._image.isNull():
            raise ValueError("Load an image before calibrating its colour scale.")
        if "low" not in self._colorbar_pixels or "high" not in self._colorbar_pixels:
            raise ValueError("Pick both the low- and high-value ends of the colour bar.")
        low = np.asarray(self._colorbar_pixels["low"], dtype=float)
        high = np.asarray(self._colorbar_pixels["high"], dtype=float)
        direction = high - low
        length = float(np.linalg.norm(direction))
        if length < 2.0:
            raise ValueError("Colour-bar endpoints must be at least two pixels apart.")
        perpendicular = np.asarray([-direction[1], direction[0]], dtype=float) / length
        sample_count = int(self._colorbar_samples_spin.value())
        width = int(self._colorbar_width_spin.value())
        positions = low[None, :] + np.linspace(0.0, 1.0, sample_count)[:, None] * direction[None, :]
        offsets = np.arange(width, dtype=float) - (width - 1.0) / 2.0
        sample_positions = positions[:, None, :] + offsets[None, :, None] * perpendicular[None, None, :]
        sample_x = np.clip(np.rint(sample_positions[:, :, 0]).astype(int), 0, self._image.width() - 1)
        sample_y = np.clip(np.rint(sample_positions[:, :, 1]).astype(int), 0, self._image.height() - 1)
        rgb = self._color_image_rgb()
        return np.median(rgb[sample_y, sample_x], axis=1)

    def _get_color_scale(self) -> ColorScaleCalibration:
        """Return the current empirical colour scale, rebuilding it when needed."""
        if self._color_scale_cache is not None:
            return self._color_scale_cache
        palette = self._sample_colorbar_palette()
        low_value, high_value = self._color_endpoint_values()
        model = ColorScaleCalibration(
            palette,
            low_value,
            high_value,
            str(self._color_scale_combo.currentData()),
            float(self._maximum_color_distance_spin.value()),
        )
        self._color_palette_cache = palette
        self._color_scale_cache = model
        return model

    def _rebuild_color_scale(self, show_errors: bool = True) -> bool:
        """Build the colour calibration and update its visual preview."""
        self._color_scale_cache = None
        self._color_palette_cache = None
        try:
            model = self._get_color_scale()
        except ValueError as exc:
            self._color_scale_status_label.setText(str(exc))
            if show_errors:
                QMessageBox.warning(self, "Colour Scale Calibration", str(exc))
            return False
        self._update_palette_preview(model.palette_rgb)
        self._color_scale_status_label.setText(
            f"Colour scale ready: {len(model.palette_rgb)} samples, "
            f"{model.low_value:g} to {model.high_value:g} ({model.scale}); "
            f"valid-match Lab distance {model.maximum_distance:g}."
        )
        self._refresh_preview()
        self._refresh_cursor_preview()
        return True

    def _update_palette_preview(self, palette: np.ndarray) -> None:
        """Render the sampled palette inside the calibration panel."""
        width = 320
        indices = np.rint(np.linspace(0, len(palette) - 1, width)).astype(int)
        strip = np.clip(palette[indices], 0, 255).astype(np.uint8)
        preview = np.repeat(strip[None, :, :], 24, axis=0)
        pixmap = QPixmap.fromImage(self._rgb_array_to_qimage(preview))
        self._color_palette_label.setText("")
        self._color_palette_label.setPixmap(pixmap)

    def _sample_probe_rgb(self, pixel_x: float, pixel_y: float) -> np.ndarray:
        """Return median RGB around a probe location."""
        radius = int(self._probe_patch_radius_spin.value())
        center_x = min(max(0, int(round(pixel_x))), self._image.width() - 1)
        center_y = min(max(0, int(round(pixel_y))), self._image.height() - 1)
        left = max(0, center_x - radius)
        right = min(self._image.width(), center_x + radius + 1)
        top = max(0, center_y - radius)
        bottom = min(self._image.height(), center_y + radius + 1)
        rgb = self._color_image_rgb()
        return np.median(rgb[top:bottom, left:right].reshape(-1, 3), axis=0)

    def extracted_rows(self) -> list[dict[str, object]]:
        """Return one diagnostic-rich X/Y/Z row for each colour probe."""
        try:
            model = self._get_color_scale()
        except ValueError:
            model = None
        rows: list[dict[str, object]] = []
        for pixel_x, pixel_y in self._color_probes:
            data = self._pixel_to_data(pixel_x, pixel_y)
            data_x, data_y = data if data is not None else (None, None)
            rgb = self._sample_probe_rgb(pixel_x, pixel_y)
            match = model.match_rgb(rgb) if model is not None else None
            rows.append(
                {
                    "x": data_x,
                    "y": data_y,
                    "z": match.value if match is not None else None,
                    "pixel_x": pixel_x,
                    "pixel_y": pixel_y,
                    "red": int(round(float(rgb[0]))),
                    "green": int(round(float(rgb[1]))),
                    "blue": int(round(float(rgb[2]))),
                    "palette_position": match.palette_position if match is not None else None,
                    "color_distance": match.distance if match is not None else None,
                    "color_confidence": match.confidence if match is not None else None,
                    "color_ambiguous": match.ambiguous if match is not None else True,
                    "color_valid": match.valid if match is not None else False,
                    "patch_radius": int(self._probe_patch_radius_spin.value()),
                    "method": "color_probe",
                    "source_image": self._image_path,
                }
            )
        return rows

    def _redraw_markers(self) -> None:
        """Draw shared calibration, the colour-bar segment, and all probes."""
        super()._redraw_markers()
        low = self._colorbar_pixels.get("low")
        high = self._colorbar_pixels.get("high")
        if low is not None:
            self._add_marker(low[0], low[1], "#0ea5e9", "Colour scale low-value end", radius=5.0)
        if high is not None:
            self._add_marker(high[0], high[1], "#ec4899", "Colour scale high-value end", radius=5.0)
        if low is not None and high is not None:
            line = QGraphicsLineItem(low[0], low[1], high[0], high[1])
            line.setPen(QPen(QColor("#7c3aed"), 2.0))
            line.setToolTip("Sampled colour-bar path")
            line.setZValue(9)
            self._scene.addItem(line)
            self._marker_items.append(line)
        for index, (pixel_x, pixel_y) in enumerate(self._color_probes, start=1):
            self._add_cross_marker(pixel_x, pixel_y, "#dc2626", f"Colour probe {index}", radius=5.0)

    def _refresh_cursor_preview(self) -> None:
        """Append live colour/value diagnostics to the shared X/Y cursor preview."""
        super()._refresh_cursor_preview()
        if self._image.isNull() or self._cursor_pixel is None or not hasattr(self, "_probe_patch_radius_spin"):
            return
        try:
            model = self._get_color_scale()
            rgb = self._sample_probe_rgb(*self._cursor_pixel)
            match = model.match_rgb(rgb)
        except ValueError:
            return
        validity = "valid" if match.valid else ("ambiguous" if match.ambiguous else "outside limit")
        base_text = self._cursor_status_label.text()
        self._cursor_status_label.setText(
            f"{base_text}\nZ: {match.value:.10g}\n"
            f"RGB: ({rgb[0]:.0f}, {rgb[1]:.0f}, {rgb[2]:.0f})\n"
            f"Confidence: {match.confidence:.1%}; {validity}"
        )

    def _refresh_preview(self) -> None:
        """Refresh colour-probe rows and diagnostic status."""
        if not hasattr(self, "_preview_table"):
            return
        rows = self.extracted_rows()
        self._preview_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                self._format_number(row.get("x")),
                self._format_number(row.get("y")),
                self._format_number(row.get("z")),
                self._format_number(row.get("pixel_x")),
                self._format_number(row.get("pixel_y")),
                row.get("red", ""),
                row.get("green", ""),
                row.get("blue", ""),
                self._format_number(row.get("palette_position")),
                self._format_number(row.get("color_distance")),
                self._format_number(row.get("color_confidence")),
                "yes" if row.get("color_ambiguous") else "no",
                "yes" if row.get("color_valid") else "no",
            ]
            for column_index, value in enumerate(values):
                self._preview_table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
        valid_count = sum(bool(row.get("color_valid")) for row in rows)
        ambiguous_count = sum(bool(row.get("color_ambiguous")) for row in rows)
        if rows:
            self._preview_status_label.setText(
                f"{len(rows)} probe(s): {valid_count} valid; {ambiguous_count} ambiguous. "
                "All rows are retained so diagnostics can be reviewed."
            )
        else:
            self._preview_status_label.setText("No extracted points.")

    def _undo_color_probe(self) -> None:
        """Remove the most recently added colour probe."""
        if self._color_probes:
            self._color_probes.pop()
        self._color_probe_status_label.setText(f"{len(self._color_probes)} probe(s).")
        self._refresh_all()

    def _remove_selected_color_probes(self) -> None:
        """Remove probes represented by selected Output table rows."""
        selected_rows = sorted({index.row() for index in self._preview_table.selectedIndexes()}, reverse=True)
        for row in selected_rows:
            if 0 <= row < len(self._color_probes):
                self._color_probes.pop(row)
        self._color_probe_status_label.setText(f"{len(self._color_probes)} probe(s).")
        self._refresh_all()

    def _clear_color_probes(self) -> None:
        """Remove all colour probes without changing calibration."""
        self._color_probes.clear()
        self._color_probe_status_label.setText("No colour-value probes.")
        self._refresh_all()

    def _clear_current_extraction(self) -> None:
        """Clear current colour probes while preserving X/Y and palette calibration."""
        self._color_probes.clear()
        self._color_probe_status_label.setText("No colour-value probes for the new data set.")
        self._set_click_target("color_probe")
        self._refresh_all()

    def calibration_summary(self) -> str:
        """Return X/Y and empirical colour-scale calibration provenance."""
        xy_summary = super().calibration_summary()
        try:
            model = self._get_color_scale()
        except ValueError as exc:
            return f"{xy_summary}; colour scale incomplete ({exc})"
        return (
            f"{xy_summary}; colour scale={model.low_value:g} to {model.high_value:g} "
            f"{model.scale}, samples={len(model.palette_rgb)}, max_Lab_distance={model.maximum_distance:g}"
        )

    def extraction_summary(self) -> str:
        """Return colour-probe settings and explicit raster-error provenance."""
        return (
            f"mode=colourplot, probes={len(self._color_probes)}, "
            f"patch_radius={self._probe_patch_radius_spin.value()} px; "
            "values estimated from rendered pixels; compression/anti-aliasing may introduce error"
        )

    def accept(self) -> None:  # type: ignore[override]
        """Finish the colourplot multi-extraction session."""
        super().accept()

    def _current_extraction_error(self) -> tuple[str, str] | None:
        """Return a user-facing validation error for the current colour probe set."""
        if self._image.isNull():
            return "Import From Figure", "Load an image before creating a dataset."
        values, errors = self._calibration_values()
        if values is None or errors:
            return "Calibration Required", "\n".join(errors)
        try:
            self._get_color_scale()
        except ValueError as exc:
            return "Colour Scale Calibration", str(exc)
        if not self._color_probes:
            return (
                "No Extracted Points",
                "Start probing and click at least one colour-plot location.",
            )
        return None


class ColumnMetadataDialog(QDialog):
    """Edit lightweight role and descriptive metadata for dataset columns."""

    def __init__(
        self,
        dataset_name: str,
        column_names: list[str],
        column_metadata: dict[str, ColumnMetadata],
        focus_column: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Create a metadata table with one editable row per column."""
        super().__init__(parent)
        self.setWindowTitle("Column Metadata")
        self.setModal(True)
        self.resize(1080, 460)
        self._column_names = list(column_names)

        self._table = QTableWidget(len(self._column_names), 7)
        self._table.setHorizontalHeaderLabels([
            "Column name",
            "Role",
            "Type",
            "Precision",
            "Unit",
            "Long name",
            "Comment",
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)

        for row, column_name in enumerate(self._column_names):
            metadata = column_metadata.get(column_name, ColumnMetadata())
            name_item = QTableWidgetItem(column_name)
            self._table.setItem(row, 0, name_item)

            role_combo = QComboBox()
            for role_key, role_label in COLUMN_ROLE_OPTIONS:
                role_combo.addItem(role_label, role_key)
            role_index = role_combo.findData(metadata.role)
            if role_index >= 0:
                role_combo.setCurrentIndex(role_index)
            self._table.setCellWidget(row, 1, role_combo)

            type_combo = QComboBox()
            for type_key, type_label in COLUMN_TYPE_OPTIONS:
                type_combo.addItem(type_label, type_key)
            type_index = type_combo.findData(metadata.value_type)
            if type_index >= 0:
                type_combo.setCurrentIndex(type_index)
            self._table.setCellWidget(row, 2, type_combo)

            precision_spin = QSpinBox()
            precision_spin.setRange(-1, 15)
            precision_spin.setSpecialValueText("Auto")
            precision_spin.setValue(
                metadata.display_precision
                if metadata.display_precision is not None
                else -1
            )
            self._table.setCellWidget(row, 3, precision_spin)

            self._table.setItem(row, 4, QTableWidgetItem(metadata.unit))
            self._table.setItem(row, 5, QTableWidgetItem(metadata.long_name))
            self._table.setItem(row, 6, QTableWidgetItem(metadata.comment))

        hint = QLabel(
            "Edit the column name here to rename the dataset column. "
            "Roles are used as hints by plot, fitting, and analysis dialogs. "
            "Types control display and explicit numeric/text validation. "
            "Units and long names appear in table tooltips and plot labels."
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Dataset: {dataset_name}"))
        layout.addWidget(hint)
        layout.addWidget(self._table)
        layout.addWidget(buttons)
        self._focus_column(focus_column)

    def column_names(self) -> list[str]:
        """Return edited column names in table order."""
        return [self._item_text(row, 0) for row in range(len(self._column_names))]

    def column_metadata(self) -> dict[str, ColumnMetadata]:
        """Return edited non-empty metadata keyed by edited column name."""
        metadata_by_column: dict[str, ColumnMetadata] = {}
        edited_names = self.column_names()
        for row, column_name in enumerate(edited_names):
            role_widget = self._table.cellWidget(row, 1)
            role = ""
            if isinstance(role_widget, QComboBox):
                role = str(role_widget.currentData() or "")
            type_widget = self._table.cellWidget(row, 2)
            value_type = ""
            if isinstance(type_widget, QComboBox):
                value_type = str(type_widget.currentData() or "")
            precision_widget = self._table.cellWidget(row, 3)
            display_precision = None
            if isinstance(precision_widget, QSpinBox):
                display_precision = normalize_display_precision(precision_widget.value())

            metadata = ColumnMetadata(
                role=role,
                unit=self._item_text(row, 4),
                long_name=self._item_text(row, 5),
                comment=self._item_text(row, 6),
                value_type=value_type,
                display_precision=display_precision,
            )
            if not metadata.is_empty():
                metadata_by_column[column_name] = metadata
        return metadata_by_column

    def accept(self) -> None:
        """Validate column names, then accept edits."""
        names = self.column_names()
        if any(not name for name in names):
            QMessageBox.warning(self, "Column Metadata", "Column names cannot be blank.")
            return
        if len(set(names)) != len(names):
            QMessageBox.warning(self, "Column Metadata", "Column names must be unique.")
            return

        for row in range(self._table.rowCount()):
            role_widget = self._table.cellWidget(row, 1)
            if isinstance(role_widget, QComboBox):
                role_widget.setToolTip(column_role_label(str(role_widget.currentData() or "")))
        super().accept()

    def _focus_column(self, focus_column: str | None) -> None:
        """Select a column row when the dialog was opened from a header."""
        if not focus_column:
            return
        try:
            row = self._column_names.index(focus_column)
        except ValueError:
            return

        self._table.setCurrentCell(row, 0)
        item = self._table.item(row, 0)
        if item is not None:
            self._table.scrollToItem(item)

    def _item_text(self, row: int, column: int) -> str:
        """Return stripped text from a metadata table item."""
        item = self._table.item(row, column)
        return item.text().strip() if item is not None else ""


class ColumnExpressionDialog(QDialog):
    """Collect settings for applying a Python-like expression to a column."""

    def __init__(
        self,
        column_names: list[str],
        selected_rows_available: bool,
        default_target: str | None = None,
        column_formulas: dict[str, str] | None = None,
        dataset_names: list[str] | None = None,
        current_dataset_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for target column, formula text, and row scope."""
        super().__init__(parent)
        self.setWindowTitle("Apply Formula")
        self.setModal(True)
        self.setMinimumSize(900, 520)
        self.resize(980, 560)
        self._column_formulas = column_formulas or {}
        self._current_dataset_name = current_dataset_name
        self._last_loaded_formula = ""

        self._target_combo = QComboBox()
        self._target_combo.setEditable(True)
        self._target_combo.addItems(column_names)
        if default_target:
            if default_target not in column_names:
                self._target_combo.addItem(default_target)
            self._target_combo.setCurrentText(default_target)
        elif column_names:
            self._target_combo.setCurrentText(column_names[0])
        else:
            self._target_combo.setCurrentText("Result")

        self._target_conflict_combo = QComboBox()
        self._target_conflict_combo.addItem("Create unique new column if target exists", "unique")
        self._target_conflict_combo.addItem("Stop and warn if target exists", "stop")
        self._target_conflict_combo.addItem("Overwrite/update existing column", "overwrite")

        cpu_count = os.cpu_count() or 1
        self._batch_execution_combo = QComboBox()
        self._batch_execution_combo.addItem("Auto", "auto")
        self._batch_execution_combo.addItem("Sequential", "sequential")
        self._batch_execution_combo.addItem("Parallel processes", "parallel")

        self._batch_workers_spin = QSpinBox()
        self._batch_workers_spin.setRange(1, max(1, cpu_count))
        self._batch_workers_spin.setValue(max(1, min(4, cpu_count - 1)))
        self._batch_workers_spin.setToolTip("Maximum worker processes for parallel batch runs.")

        self._column_binding_combo = batch_column_binding_combo()

        self._expression_edit = QPlainTextEdit()
        self._expression_edit.setFixedHeight(80)
        self._expression_edit.setPlaceholderText(
            'Examples: col1 + col2, x + y, sin(x), sqrt(col("Voltage"))'
        )

        self._column_reference_combo = QComboBox()
        for index, column_name in enumerate(column_names, start=1):
            self._column_reference_combo.addItem(f"col{index} -> {column_name}", (index, column_name))
        self._insert_alias_button = QPushButton("Insert colN")
        self._insert_exact_button = QPushButton('Insert col("Name")')

        reference_panel = QWidget()
        reference_layout = QHBoxLayout(reference_panel)
        reference_layout.setContentsMargins(0, 0, 0, 0)
        reference_layout.addWidget(self._column_reference_combo, 1)
        reference_layout.addWidget(self._insert_alias_button)
        reference_layout.addWidget(self._insert_exact_button)

        self._formula_hint = QLabel()
        self._formula_hint.setWordWrap(True)
        self._formula_hint.setTextFormat(Qt.RichText)
        self._formula_hint.setMaximumHeight(54)

        self._cheatsheet = QLabel(self._build_cheatsheet(column_names))
        self._cheatsheet.setWordWrap(True)
        self._cheatsheet.setTextFormat(Qt.RichText)
        self._cheatsheet.setOpenExternalLinks(False)
        self._cheatsheet.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._cheatsheet.setMargin(8)

        self._selected_rows_checkbox = QCheckBox("Apply only to selected rows")
        self._selected_rows_checkbox.setEnabled(selected_rows_available)
        self._selected_rows_checkbox.setChecked(selected_rows_available)

        self._dataset_list = QListWidget()
        self._dataset_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._dataset_list.setMinimumHeight(72)
        self._dataset_list.setMaximumHeight(105)
        for dataset_name in dataset_names or [current_dataset_name]:
            if not dataset_name:
                continue
            self._dataset_list.addItem(dataset_name)
            item = self._dataset_list.item(self._dataset_list.count() - 1)
            item.setSelected(dataset_name == current_dataset_name)

        self._batch_hint = QLabel(
            "Selected-row mode only applies to the current sheet. "
            "Uncheck it to apply the formula to multiple sheets. "
            "Existing target columns are protected by the output policy above. "
            "Position matching treats source columns as col1, col2, ... on every target sheet."
        )
        self._batch_hint.setWordWrap(True)
        self._batch_hint.setMaximumHeight(58)

        form = QFormLayout()
        form.addRow("Target column", self._target_combo)
        form.addRow("If target exists", self._target_conflict_combo)
        form.addRow("Batch execution", self._batch_execution_combo)
        form.addRow("Max workers", self._batch_workers_spin)
        form.addRow("Column matching", self._column_binding_combo)
        form.addRow("Expression", self._expression_edit)
        form.addRow("Insert column", reference_panel)
        form.addRow("", self._formula_hint)
        form.addRow("", self._selected_rows_checkbox)
        form.addRow("Apply to sheets", self._dataset_list)
        form.addRow("", self._batch_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        controls_panel = QWidget()
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addLayout(form)
        controls_layout.addStretch(1)

        help_scroll = QScrollArea()
        help_scroll.setWidgetResizable(True)
        help_scroll.setFrameShape(QFrame.NoFrame)
        help_scroll.setWidget(self._cheatsheet)

        help_group = QGroupBox("Help")
        help_group.setMinimumWidth(300)
        help_group.setMaximumWidth(380)
        help_layout = QVBoxLayout(help_group)
        help_layout.addWidget(help_scroll)

        body = QHBoxLayout()
        body.addWidget(controls_panel, 3)
        body.addWidget(help_group, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

        self._target_combo.currentTextChanged.connect(self._load_formula_for_target)
        self._column_reference_combo.currentIndexChanged.connect(self._update_column_insert_buttons)
        self._insert_alias_button.clicked.connect(self._insert_selected_column_alias)
        self._insert_exact_button.clicked.connect(self._insert_selected_column_exact)
        self._selected_rows_checkbox.toggled.connect(self._update_dataset_selection_state)
        self._load_formula_for_target(self._target_combo.currentText(), force=True)
        self._update_dataset_selection_state()
        self._update_column_insert_buttons()

    def target_column(self) -> str:
        """Return the selected or typed target column."""
        return self._target_combo.currentText().strip()

    def target_conflict_policy(self) -> str:
        """Return how existing target columns should be handled."""
        return str(self._target_conflict_combo.currentData() or "unique")

    def batch_execution_mode(self) -> str:
        """Return the requested formula batch execution mode."""
        return str(self._batch_execution_combo.currentData() or "auto")

    def batch_max_workers(self) -> int:
        """Return the requested worker limit for parallel formula batches."""
        return int(self._batch_workers_spin.value())

    def column_binding_mode(self) -> str:
        """Return how formula column references should be matched in batch mode."""
        return str(self._column_binding_combo.currentData() or BATCH_COLUMN_BINDING_NAME)

    def expression(self) -> str:
        """Return the expression text."""
        return self._expression_edit.toPlainText().strip()

    def apply_selected_rows_only(self) -> bool:
        """Return whether only selected rows should be updated."""
        return self._selected_rows_checkbox.isChecked()

    def target_dataset_names(self) -> list[str]:
        """Return the worksheet names selected for formula application."""
        return [item.text() for item in self._dataset_list.selectedItems()]

    def accept(self) -> None:
        """Validate worksheet selection before accepting the formula request."""
        if not self.target_column():
            QMessageBox.warning(self, "Apply Formula", "Choose or enter a target column.")
            return
        if not self.expression():
            QMessageBox.warning(self, "Apply Formula", "Enter a formula expression.")
            return
        if not self.target_dataset_names():
            QMessageBox.warning(self, "Apply Formula", "Choose at least one target sheet.")
            return
        if self.apply_selected_rows_only() and self.target_dataset_names() != [self._current_dataset_name]:
            QMessageBox.warning(
                self,
                "Apply Formula",
                "Selected-row mode can only apply to the current sheet.",
            )
            return
        super().accept()

    def _build_cheatsheet(self, column_names: list[str]) -> str:
        """Return HTML help text for the expression editor."""
        shown_columns = column_names[:8]
        column_examples = ", ".join(f'col("{escape(name)}")' for name in shown_columns)
        if len(column_names) > len(shown_columns):
            column_examples += ", ..."

        return (
            "<b>Formula cheatsheet</b><br>"
            "Use plain column names only when they are valid Python names, like "
            "<code>x</code>, <code>temperature</code>, or <code>Voltage_1</code>.<br>"
            "Use positional aliases like <code>col1</code>, <code>col2</code>, and "
            "<code>col3</code> for the first, second, and third columns when those aliases "
            "do not conflict with existing names.<br>"
            'Use <code>col("exact column name")</code> for names with spaces, symbols, or default '
            'manual-entry names. Example: <code>col("Column 1") + col("Column 2")</code>.<br>'
            "Powers use <code>**</code>, so square a column with <code>x ** 2</code>. "
            "<code>^</code> is not exponentiation.<br>"
            "Common functions: <code>sin</code>, <code>cos</code>, <code>sqrt</code>, "
            "<code>log</code>, <code>abs</code>, <code>where</code>, <code>minimum</code>, "
            "<code>maximum</code>, <code>pi</code>, <code>np.pi</code>.<br>"
            "NumPy/SciPy examples: <code>np.gradient(x)</code>, "
            "<code>np.mean(x)</code>, <code>np.random.normal(0, 1, len(x))</code>, "
            "<code>scipy.special.erf(x)</code>, "
            "<code>scipy.signal.savgol_filter(y, 11, 3)</code>, "
            "<code>stats.zscore(x)</code>. A safe math/signal/stat subset is exposed; "
            "file IO and arbitrary imports are blocked.<br>"
            "Formula-generated columns reload their stored expression when selected as the target.<br>"
            f"Available column reference style: <code>{column_examples}</code>"
        )

    def _load_formula_for_target(self, target_column: str, force: bool = False) -> None:
        """Load any stored formula associated with the selected target column."""
        clean_target = target_column.strip()
        stored_formula = self._column_formulas.get(clean_target, "")
        current_formula = self._expression_edit.toPlainText().strip()

        if stored_formula:
            self._formula_hint.setText(
                f'Stored formula for <b>{escape(clean_target)}</b>: '
                f"<code>{escape(stored_formula)}</code>"
            )
            if force or not current_formula or current_formula == self._last_loaded_formula:
                self._expression_edit.setPlainText(stored_formula)
                self._last_loaded_formula = stored_formula
            return

        self._formula_hint.setText("No stored formula for this target column.")
        if force or current_formula == self._last_loaded_formula:
            self._expression_edit.clear()
        self._last_loaded_formula = ""

    def _update_dataset_selection_state(self) -> None:
        """Limit target sheets when selected-row mode is active."""
        selected_rows_only = self._selected_rows_checkbox.isChecked()
        self._dataset_list.setEnabled(not selected_rows_only)
        if not selected_rows_only:
            return

        for row in range(self._dataset_list.count()):
            item = self._dataset_list.item(row)
            item.setSelected(item.text() == self._current_dataset_name)

    def _selected_column_reference(self) -> tuple[int, str] | None:
        """Return the currently selected positional alias and column name."""
        data = self._column_reference_combo.currentData()
        if not isinstance(data, tuple) or len(data) != 2:
            return None
        return int(data[0]), str(data[1])

    def _update_column_insert_buttons(self) -> None:
        """Refresh insert button labels for the selected column reference."""
        selected = self._selected_column_reference()
        if selected is None:
            self._insert_alias_button.setEnabled(False)
            self._insert_exact_button.setEnabled(False)
            return

        index, column_name = selected
        self._insert_alias_button.setEnabled(True)
        self._insert_exact_button.setEnabled(True)
        self._insert_alias_button.setText(f"Insert col{index}")
        self._insert_exact_button.setText("Insert exact")
        self._insert_alias_button.setToolTip(
            f"Insert col{index}, the positional alias for {column_name}."
        )
        self._insert_exact_button.setToolTip(
            f'Insert col("{column_name}") for an exact column-name reference.'
        )

    def _insert_selected_column_alias(self) -> None:
        """Insert the selected column's short positional alias."""
        selected = self._selected_column_reference()
        if selected is None:
            return
        index, _column_name = selected
        self._insert_expression_text(f"col{index}")

    def _insert_selected_column_exact(self) -> None:
        """Insert the selected column's exact-name reference."""
        selected = self._selected_column_reference()
        if selected is None:
            return
        _index, column_name = selected
        self._insert_expression_text(f"col({self._python_string_literal(column_name)})")

    def _insert_expression_text(self, text: str) -> None:
        """Insert text at the expression cursor and return focus to the editor."""
        cursor = self._expression_edit.textCursor()
        cursor.insertText(text)
        self._expression_edit.setTextCursor(cursor)
        self._expression_edit.setFocus()

    @staticmethod
    def _python_string_literal(value: str) -> str:
        """Return a double-quoted Python string literal for an exact column name."""
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'


class ColumnMathDialog(QDialog):
    """Collect settings for derivative or integral column operations."""

    def __init__(
        self,
        operation_name: str,
        column_names: list[str],
        methods: dict[str, str],
        default_target: str,
        include_initial_value: bool = False,
        default_x_column: str | None = None,
        dataset_names: list[str] | None = None,
        current_dataset_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for derivative/integral settings."""
        super().__init__(parent)
        self.setWindowTitle(operation_name)
        self.setModal(True)
        self.setMinimumWidth(420)
        self._current_dataset_name = current_dataset_name

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItems(column_names)
        self._set_combo_text_if_present(self._x_column_combo, default_x_column)

        self._y_column_list = QListWidget()
        self._y_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._y_column_list.setMaximumHeight(120)
        self._y_column_list.addItems(column_names)
        self._y_column_list.setToolTip(
            "Select one or more Y columns explicitly; none are selected automatically."
        )

        self._method_combo = QComboBox()
        for method_key, method_label in methods.items():
            self._method_combo.addItem(method_label, method_key)

        self._target_edit = QLineEdit(default_target)
        self._target_conflict_combo = QComboBox()
        self._target_conflict_combo.addItem("Create unique new column if target exists", "unique")
        self._target_conflict_combo.addItem("Stop and warn if target exists", "stop")
        self._target_conflict_combo.addItem("Overwrite/update existing column", "overwrite")

        self._column_binding_combo = batch_column_binding_combo()
        self._initial_value_edit = QLineEdit("0")
        self._include_initial_value = include_initial_value
        self._plot_result_checkbox = QCheckBox("Plot result immediately")
        self._plot_result_checkbox.setChecked(True)
        self._dataset_list = QListWidget()
        self._dataset_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._dataset_list.setMinimumHeight(110)
        for dataset_name in dataset_names or [current_dataset_name]:
            if not dataset_name:
                continue
            self._dataset_list.addItem(dataset_name)
            item = self._dataset_list.item(self._dataset_list.count() - 1)
            item.setSelected(dataset_name == current_dataset_name)

        self._batch_hint = QLabel(
            "Batch mode repeats the same X and selected Y columns on each selected sheet. "
            "Use position matching when compatible sheets use different names for the same column order. "
            "Use {column} in the target column name when you want a custom per-Y output name. "
            "The summary includes one row per source sheet and Y column."
        )
        self._batch_hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("X column", self._x_column_combo)
        form.addRow("Y columns", self._y_column_list)
        form.addRow("Column matching", self._column_binding_combo)
        form.addRow("Method", self._method_combo)
        if self._include_initial_value:
            form.addRow("Initial value", self._initial_value_edit)
        form.addRow("Target column", self._target_edit)
        form.addRow("If target exists", self._target_conflict_combo)
        form.addRow("Apply to sheets", self._dataset_list)
        form.addRow("", self._batch_hint)
        form.addRow("", self._plot_result_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def x_column(self) -> str:
        """Return selected X column."""
        return self._x_column_combo.currentText()

    def y_column(self) -> str:
        """Return the first selected Y column."""
        columns = self.y_columns()
        return columns[0] if columns else ""

    def y_columns(self) -> list[str]:
        """Return selected Y columns."""
        return selected_list_items(self._y_column_list)

    def method(self) -> str:
        """Return selected method key."""
        return str(self._method_combo.currentData())

    def target_column(self) -> str:
        """Return target column name."""
        return self._target_edit.text().strip()

    def target_conflict_policy(self) -> str:
        """Return how existing target columns should be handled."""
        return str(self._target_conflict_combo.currentData() or "unique")

    def column_binding_mode(self) -> str:
        """Return how input columns should be matched in batch mode."""
        return str(self._column_binding_combo.currentData() or BATCH_COLUMN_BINDING_NAME)

    def target_dataset_names(self) -> list[str]:
        """Return worksheet names selected for this operation."""
        return [item.text() for item in self._dataset_list.selectedItems()]

    def initial_value_text(self) -> str:
        """Return the raw initial value text for operations that need it."""
        return self._initial_value_edit.text().strip()

    def plot_result_immediately(self) -> bool:
        """Return whether the operation result should be plotted immediately."""
        return self._plot_result_checkbox.isChecked()

    def accept(self) -> None:
        """Validate batch target selection before accepting."""
        if not self.x_column() or not self.y_columns():
            QMessageBox.warning(self, self.windowTitle(), "Choose X and at least one Y column.")
            return
        if not self.target_column():
            QMessageBox.warning(self, self.windowTitle(), "Choose or enter a target column.")
            return
        if not self.target_dataset_names():
            QMessageBox.warning(self, self.windowTitle(), "Choose at least one target sheet.")
            return
        super().accept()

    @staticmethod
    def _set_combo_text_if_present(combo: QComboBox, value: str | None) -> None:
        """Select a combo item by text when it exists."""
        if not value:
            return
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)


class SmoothingDialog(QDialog):
    """Collect smoothing, preview, output, and worksheet-batch settings."""

    def __init__(
        self,
        frame: pd.DataFrame,
        column_names: list[str],
        default_x_column: str | None,
        dataset_names: list[str],
        current_dataset_name: str,
        parent: QWidget | None = None,
    ) -> None:
        """Build a smoothing workbench with a live source/result preview."""
        super().__init__(parent)
        self.setWindowTitle("Smoothing")
        self.setModal(True)
        self.resize(940, 650)
        self._preview_frame = frame

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItems(column_names)
        self._set_combo_text(self._x_column_combo, default_x_column)

        self._y_column_list = QListWidget()
        self._y_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._y_column_list.setMaximumHeight(110)
        self._y_column_list.addItems(column_names)
        self._y_column_list.setToolTip(
            "Select every signal to smooth; none are selected automatically."
        )

        self._method_combo = QComboBox()
        for key, label in SMOOTHING_METHODS.items():
            self._method_combo.addItem(label, key)

        self._derivative_method_combo = QComboBox()
        for key, label in DERIVATIVE_SMOOTHING_METHODS.items():
            self._derivative_method_combo.addItem(label, key)
        self._derivative_method_combo.setCurrentIndex(
            self._derivative_method_combo.findData("savgol")
        )

        self._window_spin = QSpinBox()
        self._window_spin.setRange(2, 100_001)
        self._window_spin.setValue(11)
        self._polynomial_spin = QSpinBox()
        self._polynomial_spin.setRange(0, 20)
        self._polynomial_spin.setValue(3)

        self._lowess_fraction_spin = QDoubleSpinBox()
        self._lowess_fraction_spin.setRange(0.001, 1.0)
        self._lowess_fraction_spin.setDecimals(3)
        self._lowess_fraction_spin.setSingleStep(0.025)
        self._lowess_fraction_spin.setValue(0.15)
        self._lowess_iterations_spin = QSpinBox()
        self._lowess_iterations_spin.setRange(0, 10)
        self._lowess_iterations_spin.setValue(2)

        self._fft_cutoff_spin = QDoubleSpinBox()
        self._fft_cutoff_spin.setRange(0.1, 100.0)
        self._fft_cutoff_spin.setDecimals(1)
        self._fft_cutoff_spin.setValue(10.0)
        self._fft_cutoff_spin.setSuffix(" % of Nyquist")

        self._derivative_median_spin = QSpinBox()
        self._derivative_median_spin.setRange(1, 100_001)
        self._derivative_median_spin.setSingleStep(2)
        self._derivative_median_spin.setValue(1)
        self._preserve_endpoints_checkbox = QCheckBox("Preserve first and last data values")
        self._preserve_endpoints_checkbox.setChecked(True)
        derivative_help = QLabel(
            "Derivative reconstruction calculates dy/dx, optionally rejects slope spikes with a "
            "moving median, smooths the derivative, and integrates it from the original first value."
        )
        derivative_help.setWordWrap(True)

        self._target_edit = QLineEdit("{column}_smoothed")
        self._target_conflict_combo = QComboBox()
        self._target_conflict_combo.addItem("Create unique new column if target exists", "unique")
        self._target_conflict_combo.addItem("Stop and warn if target exists", "stop")
        self._target_conflict_combo.addItem("Overwrite/update existing column", "overwrite")
        self._column_binding_combo = batch_column_binding_combo()
        self._plot_result_checkbox = QCheckBox("Plot original and smoothed data immediately")
        self._plot_result_checkbox.setChecked(True)

        self._dataset_list = QListWidget()
        self._dataset_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._dataset_list.setMinimumHeight(90)
        for dataset_name in dataset_names:
            self._dataset_list.addItem(dataset_name)
            item = self._dataset_list.item(self._dataset_list.count() - 1)
            item.setSelected(dataset_name == current_dataset_name)

        controls = QWidget()
        form = QFormLayout(controls)
        form.addRow("X column", self._x_column_combo)
        form.addRow("Y columns", self._y_column_list)
        form.addRow("Column matching", self._column_binding_combo)
        form.addRow("Method", self._method_combo)
        form.addRow("Derivative smoother", self._derivative_method_combo)
        form.addRow("Window points", self._window_spin)
        form.addRow("Polynomial order", self._polynomial_spin)
        form.addRow("LOWESS fraction", self._lowess_fraction_spin)
        form.addRow("Robust iterations", self._lowess_iterations_spin)
        form.addRow("FFT cutoff", self._fft_cutoff_spin)
        form.addRow("Slope-spike prefilter", self._derivative_median_spin)
        form.addRow("", self._preserve_endpoints_checkbox)
        form.addRow("", derivative_help)
        form.addRow("Target column", self._target_edit)
        form.addRow("If target exists", self._target_conflict_combo)
        form.addRow("Apply to sheets", self._dataset_list)
        form.addRow("", self._plot_result_checkbox)

        self._preview_figure = Figure(figsize=(6.0, 4.0), constrained_layout=True)
        self._preview_canvas = FigureCanvasQTAgg(self._preview_figure)
        self._preview_axes = self._preview_figure.add_subplot(111)
        self._preview_status = QLabel()
        self._preview_status.setWordWrap(True)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.addWidget(self._preview_canvas, 1)
        preview_layout.addWidget(self._preview_status)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(controls)
        splitter.addWidget(preview_panel)
        splitter.setSizes([380, 560])

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(buttons)

        self._method_combo.currentIndexChanged.connect(self._update_method_controls)
        self._derivative_method_combo.currentIndexChanged.connect(self._update_method_controls)
        self._x_column_combo.currentIndexChanged.connect(self._refresh_preview)
        self._y_column_list.itemSelectionChanged.connect(self._refresh_preview)
        for spin in (
            self._window_spin,
            self._polynomial_spin,
            self._lowess_fraction_spin,
            self._lowess_iterations_spin,
            self._fft_cutoff_spin,
            self._derivative_median_spin,
        ):
            spin.valueChanged.connect(self._refresh_preview)
        self._preserve_endpoints_checkbox.toggled.connect(self._refresh_preview)
        self._update_method_controls()

    def x_column(self) -> str:
        """Return the selected coordinate column."""
        return self._x_column_combo.currentText()

    def y_columns(self) -> list[str]:
        """Return the selected signal columns."""
        return selected_list_items(self._y_column_list)

    def method(self) -> str:
        """Return the selected smoothing method key."""
        return str(self._method_combo.currentData() or "adjacent_average")

    def parameters(self) -> SmoothingParameters:
        """Return the currently configured engine parameters."""
        return SmoothingParameters(
            window_length=self._window_spin.value(),
            polynomial_order=self._polynomial_spin.value(),
            lowess_fraction=self._lowess_fraction_spin.value(),
            lowess_iterations=self._lowess_iterations_spin.value(),
            fft_cutoff_fraction=self._fft_cutoff_spin.value() / 100.0,
            derivative_smoothing_method=str(
                self._derivative_method_combo.currentData() or "savgol"
            ),
            derivative_median_window=self._derivative_median_spin.value(),
            preserve_endpoints=self._preserve_endpoints_checkbox.isChecked(),
        )

    def target_column(self) -> str:
        """Return the output column template."""
        return self._target_edit.text().strip()

    def target_conflict_policy(self) -> str:
        """Return the requested existing-output policy."""
        return str(self._target_conflict_combo.currentData() or "unique")

    def column_binding_mode(self) -> str:
        """Return name or position input matching."""
        return str(self._column_binding_combo.currentData() or BATCH_COLUMN_BINDING_NAME)

    def target_dataset_names(self) -> list[str]:
        """Return selected worksheet names."""
        return [item.text() for item in self._dataset_list.selectedItems()]

    def plot_result_immediately(self) -> bool:
        """Return whether a comparison plot should be created."""
        return self._plot_result_checkbox.isChecked()

    def _update_method_controls(self) -> None:
        """Show which parameters affect the selected method and refresh preview."""
        method = self.method()
        derivative_mode = method == "derivative_integral"
        effective_method = (
            str(self._derivative_method_combo.currentData() or "savgol")
            if derivative_mode
            else method
        )
        self._derivative_method_combo.setEnabled(derivative_mode)
        self._window_spin.setEnabled(effective_method in {
            "adjacent_average", "moving_median", "savgol"
        })
        self._polynomial_spin.setEnabled(effective_method == "savgol")
        self._lowess_fraction_spin.setEnabled(effective_method == "lowess")
        self._lowess_iterations_spin.setEnabled(effective_method == "lowess")
        self._fft_cutoff_spin.setEnabled(effective_method == "fft")
        self._derivative_median_spin.setEnabled(method == "derivative_integral")
        self._preserve_endpoints_checkbox.setEnabled(method == "derivative_integral")
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """Render the first selected signal and its current smoothing result."""
        self._preview_axes.clear()
        columns = self.y_columns()
        if not self.x_column() or not columns:
            self._preview_status.setText("Choose X and at least one Y column to preview smoothing.")
            self._preview_canvas.draw_idle()
            return
        try:
            values = pd.DataFrame({
                "x": pd.to_numeric(self._preview_frame[self.x_column()], errors="coerce"),
                "y": pd.to_numeric(self._preview_frame[columns[0]], errors="coerce"),
            }).replace([np.inf, -np.inf], np.nan).dropna()
            if len(values) > 4000:
                stride = int(math.ceil(len(values) / 4000))
                values = values.iloc[::stride]
                preview_note = " Preview uses up to 4,000 evenly sampled points."
            else:
                preview_note = ""
            smoothed = smooth_values(
                values["x"].to_numpy(dtype=float),
                values["y"].to_numpy(dtype=float),
                method=self.method(),
                parameters=self.parameters(),
            )
            self._preview_axes.plot(values["x"], values["y"], color="0.6", linewidth=1.0, label="Original")
            self._preview_axes.plot(values["x"], smoothed, color="tab:red", linewidth=1.8, label="Smoothed")
            self._preview_axes.legend(loc="best")
            self._preview_axes.grid(True, alpha=0.25)
            self._preview_status.setText(
                f"Previewing {SMOOTHING_METHODS.get(self.method(), self.method())} on {columns[0]}."
                f"{preview_note}"
            )
        except Exception as exc:
            self._preview_status.setText(str(exc))
        self._preview_canvas.draw_idle()

    def accept(self) -> None:
        """Validate required selections and odd-window constraints."""
        if not self.x_column() or not self.y_columns():
            QMessageBox.warning(self, "Smoothing", "Choose X and at least one Y column.")
            return
        if not self.target_column():
            QMessageBox.warning(self, "Smoothing", "Enter a target column name or template.")
            return
        if not self.target_dataset_names():
            QMessageBox.warning(self, "Smoothing", "Choose at least one target sheet.")
            return
        effective_method = (
            str(self._derivative_method_combo.currentData() or "savgol")
            if self.method() == "derivative_integral"
            else self.method()
        )
        if effective_method in {"moving_median", "savgol"} and self._window_spin.value() % 2 == 0:
            QMessageBox.warning(self, "Smoothing", "This method requires an odd smoothing window.")
            return
        if effective_method == "savgol" and self._polynomial_spin.value() >= self._window_spin.value():
            QMessageBox.warning(self, "Smoothing", "Polynomial order must be smaller than the smoothing window.")
            return
        if self.method() == "derivative_integral" and self._derivative_median_spin.value() % 2 == 0:
            QMessageBox.warning(self, "Smoothing", "The derivative median window must be 1 or an odd number.")
            return
        super().accept()

    @staticmethod
    def _set_combo_text(combo: QComboBox, value: str | None) -> None:
        """Select a combo item by text when present."""
        if value:
            index = combo.findText(value)
            if index >= 0:
                combo.setCurrentIndex(index)


class FFTDialog(QDialog):
    """Collect settings for FFT operations."""

    def __init__(
        self,
        column_names: list[str],
        default_dataset_name: str,
        default_x_column: str | None = None,
        dataset_names: list[str] | None = None,
        current_dataset_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for FFT input, spacing, and output naming."""
        super().__init__(parent)
        self.setWindowTitle("FFT")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._current_dataset_name = current_dataset_name or default_dataset_name

        self._signal_column_list = QListWidget()
        self._signal_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._signal_column_list.setMaximumHeight(120)
        self._signal_column_list.addItems(column_names)
        self._signal_column_list.setToolTip(
            "Select one or more signal columns explicitly; none are selected automatically."
        )

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItem("Sample index", None)
        for column_name in column_names:
            self._x_column_combo.addItem(column_name, column_name)
        self._set_combo_text_if_present(self._x_column_combo, default_x_column)

        self._window_combo = QComboBox()
        for window_key, window_label in WINDOW_METHODS.items():
            self._window_combo.addItem(window_label, window_key)

        self._column_binding_combo = batch_column_binding_combo()
        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_FFT")
        self._dataset_list = QListWidget()
        self._dataset_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._dataset_list.setMinimumHeight(110)
        for dataset_name in dataset_names or [self._current_dataset_name]:
            if not dataset_name:
                continue
            self._dataset_list.addItem(dataset_name)
            item = self._dataset_list.item(self._dataset_list.count() - 1)
            item.setSelected(dataset_name == self._current_dataset_name)

        self._batch_hint = QLabel(
            "Batch mode repeats the selected signal columns, X/time selection, and window on each selected sheet. "
            "Use position matching when compatible sheets use different names for the same column order. "
            "Use {source} and {column} in the result sheet name for custom per-source naming."
        )
        self._batch_hint.setWordWrap(True)
        self._plot_result_checkbox = QCheckBox("Plot magnitude immediately")
        self._plot_result_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow("Signal columns", self._signal_column_list)
        form.addRow("X/time column", self._x_column_combo)
        form.addRow("Column matching", self._column_binding_combo)
        form.addRow("Window", self._window_combo)
        form.addRow("Result sheet", self._target_dataset_edit)
        form.addRow("Apply to sheets", self._dataset_list)
        form.addRow("", self._batch_hint)
        form.addRow("", self._plot_result_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def signal_column(self) -> str:
        """Return the first selected signal column."""
        columns = self.signal_columns()
        return columns[0] if columns else ""

    def signal_columns(self) -> list[str]:
        """Return selected signal columns."""
        return selected_list_items(self._signal_column_list)

    def x_column(self) -> str | None:
        """Return selected X/time column, or None for sample index spacing."""
        value = self._x_column_combo.currentData()
        return str(value) if value else None

    def window_method(self) -> str:
        """Return selected FFT window method."""
        return str(self._window_combo.currentData())

    def column_binding_mode(self) -> str:
        """Return how input columns should be matched in batch mode."""
        return str(self._column_binding_combo.currentData() or BATCH_COLUMN_BINDING_NAME)

    def target_dataset_name(self) -> str:
        """Return requested result dataset name."""
        return self._target_dataset_edit.text().strip()

    def target_dataset_names(self) -> list[str]:
        """Return worksheet names selected for FFT application."""
        return [item.text() for item in self._dataset_list.selectedItems()]

    def plot_result_immediately(self) -> bool:
        """Return whether the FFT magnitude should be plotted immediately."""
        return self._plot_result_checkbox.isChecked()

    def accept(self) -> None:
        """Validate FFT batch target selection before accepting."""
        if not self.signal_columns():
            QMessageBox.warning(self, "FFT", "Choose at least one signal column.")
            return
        if not self.target_dataset_names():
            QMessageBox.warning(self, "FFT", "Choose at least one target sheet.")
            return
        super().accept()

    @staticmethod
    def _set_combo_text_if_present(combo: QComboBox, value: str | None) -> None:
        """Select a combo item by text when it exists."""
        if not value:
            return
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)


class IFFTDialog(QDialog):
    """Collect settings for inverse FFT operations."""

    def __init__(
        self,
        column_names: list[str],
        default_dataset_name: str,
        dataset_names: list[str] | None = None,
        current_dataset_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for inverse FFT input and output naming."""
        super().__init__(parent)
        self.setWindowTitle("Inverse FFT")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._current_dataset_name = current_dataset_name or default_dataset_name

        self._real_column_list = QListWidget()
        self._real_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._real_column_list.setMaximumHeight(120)
        self._real_column_list.addItems(column_names)

        self._imaginary_column_list = QListWidget()
        self._imaginary_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._imaginary_column_list.setMaximumHeight(120)
        self._imaginary_column_list.addItems(column_names)
        self._real_column_list.setToolTip(
            "Select one or more real spectrum columns explicitly."
        )
        self._imaginary_column_list.setToolTip(
            "Optionally select matching imaginary columns; none are selected automatically."
        )

        self._column_binding_combo = batch_column_binding_combo()
        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_iFFT")
        self._dataset_list = QListWidget()
        self._dataset_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._dataset_list.setMinimumHeight(110)
        for dataset_name in dataset_names or [self._current_dataset_name]:
            if not dataset_name:
                continue
            self._dataset_list.addItem(dataset_name)
            item = self._dataset_list.item(self._dataset_list.count() - 1)
            item.setSelected(dataset_name == self._current_dataset_name)

        self._batch_hint = QLabel(
            "Batch mode repeats the same real/imaginary selection on each selected sheet. "
            "Leave imaginary empty for zero; select one imaginary column for all real columns, "
            "or select the same number of imaginary columns to pair them in order. "
            "Use position matching when compatible sheets use different names for the same column order. "
            "Use {source} and {column} in the result sheet name for custom per-source naming."
        )
        self._batch_hint.setWordWrap(True)
        self._plot_result_checkbox = QCheckBox("Plot reconstructed real signal immediately")
        self._plot_result_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow("Real columns", self._real_column_list)
        form.addRow("Imaginary columns", self._imaginary_column_list)
        form.addRow("Column matching", self._column_binding_combo)
        form.addRow("Result sheet", self._target_dataset_edit)
        form.addRow("Apply to sheets", self._dataset_list)
        form.addRow("", self._batch_hint)
        form.addRow("", self._plot_result_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def real_column(self) -> str:
        """Return the first selected real spectrum column."""
        columns = self.real_columns()
        return columns[0] if columns else ""

    def real_columns(self) -> list[str]:
        """Return selected real spectrum columns."""
        return selected_list_items(self._real_column_list)

    def imaginary_column(self) -> str | None:
        """Return the first selected imaginary spectrum column, or None."""
        columns = self.imaginary_columns()
        return columns[0] if columns else None

    def imaginary_columns(self) -> list[str]:
        """Return selected imaginary spectrum columns."""
        return selected_list_items(self._imaginary_column_list)

    def column_binding_mode(self) -> str:
        """Return how input columns should be matched in batch mode."""
        return str(self._column_binding_combo.currentData() or BATCH_COLUMN_BINDING_NAME)

    def target_dataset_name(self) -> str:
        """Return requested result dataset name."""
        return self._target_dataset_edit.text().strip()

    def target_dataset_names(self) -> list[str]:
        """Return worksheet names selected for inverse FFT application."""
        return [item.text() for item in self._dataset_list.selectedItems()]

    def plot_result_immediately(self) -> bool:
        """Return whether the reconstructed real signal should be plotted immediately."""
        return self._plot_result_checkbox.isChecked()

    def accept(self) -> None:
        """Validate inverse FFT batch target selection before accepting."""
        real_columns = self.real_columns()
        imaginary_columns = self.imaginary_columns()
        if not real_columns:
            QMessageBox.warning(self, "Inverse FFT", "Choose at least one real spectrum column.")
            return
        if imaginary_columns and len(imaginary_columns) not in {1, len(real_columns)}:
            QMessageBox.warning(
                self,
                "Inverse FFT",
                "Select zero, one, or the same number of imaginary columns as real columns.",
            )
            return
        if not self.target_dataset_names():
            QMessageBox.warning(self, "Inverse FFT", "Choose at least one target sheet.")
            return
        super().accept()


class InterpolationDialog(QDialog):
    """Collect settings for 1D, 2D, and N-D interpolation."""

    def __init__(
        self,
        column_names: list[str],
        default_dataset_name: str,
        column_ranges: dict[str, tuple[float, float]],
        default_x_column: str | None = None,
        default_y_column: str | None = None,
        dataset_names: list[str] | None = None,
        current_dataset_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Build interpolation source, method, query, and output controls."""
        super().__init__(parent)
        self.setWindowTitle("Interpolation")
        self.setModal(True)
        self.resize(760, 620)
        self._column_names = list(column_names)
        self._column_ranges = column_ranges
        self._current_dataset_name = current_dataset_name or default_dataset_name
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("1D: x -> value", "1d")
        self._mode_combo.addItem("2D: x, y -> value", "2d")
        self._mode_combo.addItem("N-D: coordinates -> value", "nd")

        self._value_column_list = self._column_list(maximum_height=120)
        self._value_column_list.setToolTip(
            "Select one or more values to interpolate; none are selected automatically."
        )

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItems(self._column_names)
        self._set_combo_text_if_present(self._x_column_combo, default_x_column)

        self._y_column_combo = QComboBox()
        self._y_column_combo.addItems(self._column_names)
        self._set_combo_text_if_present(self._y_column_combo, default_y_column)

        self._nd_source_list = self._column_list()
        self._select_list_columns(
            self._nd_source_list,
            [column for column in (default_x_column, default_y_column) if column],
        )

        self._method_combo = QComboBox()
        self._fill_policy_combo = QComboBox()
        for key, label in FILL_POLICIES.items():
            self._fill_policy_combo.addItem(label, key)

        self._smoothing_spin = QDoubleSpinBox()
        self._smoothing_spin.setRange(0.0, 1_000_000.0)
        self._smoothing_spin.setDecimals(6)
        self._smoothing_spin.setSingleStep(0.1)
        self._smoothing_spin.setValue(0.0)

        self._epsilon_spin = QDoubleSpinBox()
        self._epsilon_spin.setRange(0.0, 1_000_000.0)
        self._epsilon_spin.setDecimals(6)
        self._epsilon_spin.setSingleStep(0.1)
        self._epsilon_spin.setSpecialValueText("auto")
        self._epsilon_spin.setValue(0.0)

        self._query_mode_combo = QComboBox()

        self._x_start_edit = QLineEdit()
        self._x_end_edit = QLineEdit()
        self._x_count_spin = QSpinBox()
        self._x_count_spin.setRange(1, 1_000_000)
        self._x_count_spin.setValue(200)

        self._y_start_edit = QLineEdit()
        self._y_end_edit = QLineEdit()
        self._y_count_spin = QSpinBox()
        self._y_count_spin.setRange(1, 100_000)
        self._y_count_spin.setValue(100)

        self._query_x_column_combo = QComboBox()
        self._query_x_column_combo.addItems(self._column_names)
        self._set_combo_text_if_present(self._query_x_column_combo, default_x_column)

        self._query_y_column_combo = QComboBox()
        self._query_y_column_combo.addItems(self._column_names)
        self._set_combo_text_if_present(self._query_y_column_combo, default_y_column)

        self._nd_query_list = self._column_list()
        self._select_list_columns(
            self._nd_query_list,
            [column for column in (default_x_column, default_y_column) if column],
        )

        self._manual_points_edit = QPlainTextEdit()
        self._manual_points_edit.setMinimumHeight(120)

        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_interpolation")
        self._dataset_list = QListWidget()
        self._dataset_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._dataset_list.setMinimumHeight(110)
        for dataset_name in dataset_names or [self._current_dataset_name]:
            if not dataset_name:
                continue
            self._dataset_list.addItem(dataset_name)
            item = self._dataset_list.item(self._dataset_list.count() - 1)
            item.setSelected(dataset_name == self._current_dataset_name)

        source_panel = self._source_panel()

        query_stack = QStackedWidget()
        query_stack.addWidget(self._generated_query_panel())
        query_stack.addWidget(self._column_query_panel())
        query_stack.addWidget(self._manual_query_panel())
        self._query_stack = query_stack

        self._column_binding_combo = batch_column_binding_combo()

        form = QFormLayout()
        form.addRow("Dimension", self._mode_combo)
        form.addRow("Value columns", self._value_column_list)
        form.addRow("Source coordinates", source_panel)
        form.addRow("Column matching", self._column_binding_combo)
        form.addRow("Method", self._method_combo)
        form.addRow("Outside range", self._fill_policy_combo)
        form.addRow("Smoothing", self._smoothing_spin)
        form.addRow("RBF epsilon", self._epsilon_spin)
        form.addRow("Query mode", self._query_mode_combo)
        form.addRow("Query coordinates", query_stack)
        form.addRow("Result sheet", self._target_dataset_edit)
        form.addRow("Apply to sheets", self._dataset_list)

        hint = QLabel(
            "Generated 2D queries create a full X/Y grid. N-D interpolation supports existing "
            "query columns or manual coordinate rows. Duplicate source coordinates are averaged. "
            "Batch position matching maps source and query columns by their col1, col2, ... positions. "
            "Use {source} and {column} in the result sheet name for custom per-source naming."
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self._mode_combo.currentIndexChanged.connect(self._update_mode)
        self._method_combo.currentIndexChanged.connect(self._update_method_parameters)
        self._query_mode_combo.currentIndexChanged.connect(self._update_query_mode)
        self._x_column_combo.currentTextChanged.connect(lambda: self._set_range_fields("x"))
        self._y_column_combo.currentTextChanged.connect(lambda: self._set_range_fields("y"))
        self._update_mode()
        self._set_range_fields("x")
        self._set_range_fields("y")

    def mode(self) -> str:
        """Return interpolation dimensionality key."""
        return str(self._mode_combo.currentData())

    def coordinate_columns(self) -> list[str]:
        """Return selected source coordinate columns in dimensional order."""
        mode = self.mode()
        if mode == "1d":
            return [self._x_column_combo.currentText()]
        if mode == "2d":
            return [self._x_column_combo.currentText(), self._y_column_combo.currentText()]
        return self._selected_list_columns(self._nd_source_list)

    def value_column(self) -> str:
        """Return the first selected source value column."""
        columns = self.value_columns()
        return columns[0] if columns else ""

    def value_columns(self) -> list[str]:
        """Return selected source value columns."""
        return self._selected_list_columns(self._value_column_list)

    def method_key(self) -> str:
        """Return selected interpolation method key."""
        return str(self._method_combo.currentData())

    def fill_policy(self) -> str:
        """Return selected 1D outside-range policy."""
        return str(self._fill_policy_combo.currentData() or "nan")

    def smoothing(self) -> float:
        """Return smoothing parameter for spline/RBF methods."""
        return self._smoothing_spin.value()

    def epsilon(self) -> float | None:
        """Return RBF epsilon, or None when disabled."""
        return self._epsilon_spin.value() if self._epsilon_spin.isEnabled() else None

    def query_mode(self) -> str:
        """Return selected query input mode."""
        return str(self._query_mode_combo.currentData())

    def query_columns(self) -> list[str]:
        """Return query coordinate columns for the existing-column query mode."""
        mode = self.mode()
        if mode == "1d":
            return [self._query_x_column_combo.currentText()]
        if mode == "2d":
            return [self._query_x_column_combo.currentText(), self._query_y_column_combo.currentText()]
        return self._selected_list_columns(self._nd_query_list)

    def generated_ranges(self) -> list[tuple[float, float, int]]:
        """Return generated coordinate ranges."""
        ranges = [
            (
                self._required_float(self._x_start_edit.text(), "X start"),
                self._required_float(self._x_end_edit.text(), "X end"),
                self._x_count_spin.value(),
            )
        ]
        if self.mode() == "2d":
            ranges.append(
                (
                    self._required_float(self._y_start_edit.text(), "Y start"),
                    self._required_float(self._y_end_edit.text(), "Y end"),
                    self._y_count_spin.value(),
                )
            )
        return ranges

    def manual_points_text(self) -> str:
        """Return raw manual query coordinate text."""
        return self._manual_points_edit.toPlainText()

    def target_dataset_name(self) -> str:
        """Return requested result dataset name."""
        return self._target_dataset_edit.text().strip()

    def target_dataset_names(self) -> list[str]:
        """Return worksheet names selected for interpolation application."""
        return [item.text() for item in self._dataset_list.selectedItems()]

    def column_binding_mode(self) -> str:
        """Return how interpolation columns should be matched in batch mode."""
        return str(self._column_binding_combo.currentData() or BATCH_COLUMN_BINDING_NAME)

    def accept(self) -> None:
        """Validate the interpolation request before closing."""
        try:
            self._validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Interpolation", str(exc))
            return
        super().accept()

    def _source_panel(self) -> QWidget:
        """Return source-coordinate controls shared by all modes."""
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("X column", self._x_column_combo)
        form.addRow("Y column", self._y_column_combo)
        form.addRow("N-D columns", self._nd_source_list)
        self._source_x_label = form.labelForField(self._x_column_combo)
        self._source_y_label = form.labelForField(self._y_column_combo)
        self._source_nd_label = form.labelForField(self._nd_source_list)
        return panel

    def _generated_query_panel(self) -> QWidget:
        """Return generated query range controls."""
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("X range", self._range_row(self._x_start_edit, self._x_end_edit, self._x_count_spin))
        self._generated_y_row = self._range_row(self._y_start_edit, self._y_end_edit, self._y_count_spin)
        form.addRow("Y range", self._generated_y_row)
        self._generated_y_label = form.labelForField(self._generated_y_row)
        return panel

    def _column_query_panel(self) -> QWidget:
        """Return query-from-columns controls."""
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Query X", self._query_x_column_combo)
        form.addRow("Query Y", self._query_y_column_combo)
        form.addRow("Query N-D columns", self._nd_query_list)
        self._query_x_label = form.labelForField(self._query_x_column_combo)
        self._query_y_label = form.labelForField(self._query_y_column_combo)
        self._query_nd_label = form.labelForField(self._nd_query_list)
        return panel

    def _manual_query_panel(self) -> QWidget:
        """Return manual query-coordinate controls."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self._manual_points_edit.setPlaceholderText("One query point per line, values separated by spaces, commas, or tabs.")
        layout.addWidget(self._manual_points_edit)
        return panel

    def _update_mode(self) -> None:
        """Refresh mode-specific controls."""
        mode = self.mode()
        x_visible = mode in {"1d", "2d"}
        y_visible = mode == "2d"
        nd_visible = mode == "nd"
        self._source_x_label.setVisible(x_visible)
        self._x_column_combo.setVisible(x_visible)
        self._source_y_label.setVisible(y_visible)
        self._y_column_combo.setVisible(y_visible)
        self._source_nd_label.setVisible(nd_visible)
        self._nd_source_list.setVisible(nd_visible)
        self._refresh_methods()
        self._refresh_query_modes()
        self._fill_policy_combo.setEnabled(mode == "1d")
        self._generated_y_label.setVisible(mode == "2d")
        self._generated_y_row.setVisible(mode == "2d")
        query_xy_visible = mode in {"1d", "2d"}
        self._query_x_label.setVisible(query_xy_visible)
        self._query_x_column_combo.setVisible(query_xy_visible)
        self._query_y_label.setVisible(mode == "2d")
        self._query_y_column_combo.setVisible(mode == "2d")
        self._query_nd_label.setVisible(mode == "nd")
        self._nd_query_list.setVisible(mode == "nd")
        self._set_range_fields("x")
        self._set_range_fields("y")

    def _refresh_methods(self) -> None:
        """Reload methods for the selected dimensionality."""
        current = self._method_combo.currentData()
        methods = INTERPOLATION_METHODS.get(self.mode(), {})
        self._method_combo.blockSignals(True)
        self._method_combo.clear()
        for key, method in methods.items():
            self._method_combo.addItem(method.label, key)
        index = self._method_combo.findData(current)
        if index >= 0:
            self._method_combo.setCurrentIndex(index)
        self._method_combo.blockSignals(False)
        self._update_method_parameters()

    def _refresh_query_modes(self) -> None:
        """Reload query modes for the selected dimensionality."""
        current = self._query_mode_combo.currentData()
        self._query_mode_combo.blockSignals(True)
        self._query_mode_combo.clear()
        if self.mode() in {"1d", "2d"}:
            self._query_mode_combo.addItem("Generated range/grid", "generated")
        self._query_mode_combo.addItem("From existing columns", "columns")
        self._query_mode_combo.addItem("Manual coordinates", "manual")
        index = self._query_mode_combo.findData(current)
        if index >= 0:
            self._query_mode_combo.setCurrentIndex(index)
        self._query_mode_combo.blockSignals(False)
        self._update_query_mode()

    def _update_query_mode(self) -> None:
        """Show the controls for the selected query mode."""
        mode_index = {"generated": 0, "columns": 1, "manual": 2}.get(self.query_mode(), 0)
        self._query_stack.setCurrentIndex(mode_index)

    def _update_method_parameters(self) -> None:
        """Enable optional parameter controls only when relevant."""
        method = self.method_key()
        uses_smoothing = method in {
            "smoothing_spline",
            "smooth_bivariate_spline",
            "rbf_linear",
            "rbf_thin_plate",
            "rbf_cubic",
            "rbf_gaussian",
        }
        self._smoothing_spin.setEnabled(uses_smoothing)
        self._epsilon_spin.setEnabled(method == "rbf_gaussian")
        method_info = INTERPOLATION_METHODS.get(self.mode(), {}).get(method)
        self._method_combo.setToolTip(method_info.description if method_info else "")

    def _validate(self) -> None:
        """Validate source/query controls."""
        coordinates = self.coordinate_columns()
        if any(not column for column in coordinates):
            raise ValueError("Choose all coordinate columns.")
        if len(set(coordinates)) != len(coordinates):
            raise ValueError("Coordinate columns must be unique.")
        value_columns = self.value_columns()
        if not value_columns:
            raise ValueError("Choose at least one value column.")
        conflicting_values = [column for column in value_columns if column in coordinates]
        if conflicting_values:
            raise ValueError("Value columns must be different from coordinate columns.")
        if self.mode() == "nd" and len(coordinates) < 2:
            raise ValueError("N-D interpolation requires at least two coordinate columns.")
        if self.query_mode() == "columns":
            query_columns = self.query_columns()
            if len(query_columns) != len(coordinates) or any(not column for column in query_columns):
                raise ValueError("Choose one query column for each coordinate dimension.")
            if len(set(query_columns)) != len(query_columns):
                raise ValueError("Query coordinate columns must be unique.")
        elif self.query_mode() == "generated":
            total_count = 1
            for _start, _end, count in self.generated_ranges():
                total_count *= count
            if total_count > MAX_GENERATED_QUERY_POINTS:
                raise ValueError(
                    f"Generated queries are limited to {MAX_GENERATED_QUERY_POINTS:,} points."
                )
        elif not self.manual_points_text().strip():
            raise ValueError("Enter manual query coordinates.")
        if not self.target_dataset_names():
            raise ValueError("Choose at least one target sheet.")

    def _set_range_fields(self, axis: str) -> None:
        """Prefill generated query ranges from source column numeric ranges."""
        if axis == "x":
            column = self._x_column_combo.currentText()
            start_edit, end_edit = self._x_start_edit, self._x_end_edit
        else:
            column = self._y_column_combo.currentText()
            start_edit, end_edit = self._y_start_edit, self._y_end_edit
        value_range = self._column_ranges.get(column)
        if value_range is None:
            return
        start, end = value_range
        start_edit.setText(f"{start:g}")
        end_edit.setText(f"{end:g}")

    @staticmethod
    def _range_row(start_edit: QLineEdit, end_edit: QLineEdit, count_spin: QSpinBox) -> QWidget:
        """Return a compact generated-range row."""
        start_edit.setPlaceholderText("start")
        end_edit.setPlaceholderText("end")
        start_edit.setMaximumWidth(100)
        end_edit.setMaximumWidth(100)
        count_spin.setPrefix("n=")
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(start_edit)
        layout.addWidget(end_edit)
        layout.addWidget(count_spin)
        layout.addStretch(1)
        return row

    def _column_list(self, maximum_height: int = 120) -> QListWidget:
        """Return a multi-select list populated with dataset columns."""
        widget = QListWidget()
        widget.setSelectionMode(QAbstractItemView.MultiSelection)
        widget.setMaximumHeight(maximum_height)
        widget.addItems(self._column_names)
        return widget

    @staticmethod
    def _selected_list_columns(widget: QListWidget) -> list[str]:
        """Return selected list items in visual order."""
        return [
            widget.item(row).text()
            for row in range(widget.count())
            if widget.item(row).isSelected()
        ]

    @staticmethod
    def _select_list_columns(widget: QListWidget, columns: list[str]) -> None:
        """Select list items whose text appears in columns."""
        wanted = set(columns)
        for row in range(widget.count()):
            item = widget.item(row)
            item.setSelected(item.text() in wanted)

    @staticmethod
    def _set_combo_text_if_present(combo: QComboBox, value: str | None) -> None:
        """Select a combo item by text when present."""
        if not value:
            return
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _required_float(text: str, label: str) -> float:
        """Parse a required float."""
        try:
            return float(text.strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be numeric.") from exc


class StatisticsDialog(QDialog):
    """Collect settings for single, paired, grouped, and multi-column statistics."""

    def __init__(
        self,
        dataset_columns: dict[str, list[str]],
        default_dataset_name: str,
        parent: QWidget | None = None,
    ) -> None:
        """Build operation, dataset, column, and result-sheet controls."""
        super().__init__(parent)
        self.setWindowTitle("Statistics")
        self.setModal(True)
        self.setMinimumWidth(700)
        self._dataset_columns = dataset_columns

        self._operation_combo = QComboBox()
        for key, operation in STATISTIC_OPERATIONS.items():
            self._operation_combo.addItem(operation.label, key)

        self._primary_dataset_combo = QComboBox()
        self._primary_dataset_combo.addItems(list(dataset_columns.keys()))
        if default_dataset_name in dataset_columns:
            self._primary_dataset_combo.setCurrentText(default_dataset_name)

        self._primary_column_list = QListWidget()
        self._primary_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._primary_column_list.setMaximumHeight(120)
        self._multi_column_list = QListWidget()
        self._multi_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._multi_column_list.setMinimumHeight(130)
        self._secondary_dataset_combo = QComboBox()
        self._secondary_dataset_combo.addItems(list(dataset_columns.keys()))
        if default_dataset_name in dataset_columns:
            self._secondary_dataset_combo.setCurrentText(default_dataset_name)

        self._secondary_column_list = QListWidget()
        self._secondary_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._secondary_column_list.setMaximumHeight(120)
        self._column_binding_combo = batch_column_binding_combo()
        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_statistics")
        self._dataset_list = QListWidget()
        self._dataset_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._dataset_list.setMinimumHeight(110)
        for dataset_name in dataset_columns:
            self._dataset_list.addItem(dataset_name)
            item = self._dataset_list.item(self._dataset_list.count() - 1)
            item.setSelected(dataset_name == default_dataset_name)
        self._plot_result_checkbox = QCheckBox("Create companion plot")
        self._plot_result_checkbox.setChecked(True)
        self._plot_kind_combo = QComboBox()

        self._hint_label = QLabel()
        self._hint_label.setWordWrap(True)
        self._batch_hint = QLabel(
            "Batch mode repeats the selected statistic on each selected sheet. "
            "Use exact-name matching for identically named worksheets, or position matching when the same data lives "
            "in col1, col2, ... with different column names. Result sheet names may use {source} and {column}."
        )
        self._batch_hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Operation", self._operation_combo)
        form.addRow("Primary sheet", self._primary_dataset_combo)
        form.addRow("Primary columns", self._primary_column_list)
        form.addRow("Columns", self._multi_column_list)
        form.addRow("Secondary sheet", self._secondary_dataset_combo)
        form.addRow("Secondary columns", self._secondary_column_list)
        form.addRow("Column matching", self._column_binding_combo)
        form.addRow("Result sheet", self._target_dataset_edit)
        form.addRow("Apply to sheets", self._dataset_list)
        form.addRow("", self._batch_hint)
        form.addRow("", self._plot_result_checkbox)
        form.addRow("Plot", self._plot_kind_combo)
        form.addRow("", self._hint_label)
        self._primary_column_label = form.labelForField(self._primary_column_list)
        self._multi_columns_label = form.labelForField(self._multi_column_list)
        self._secondary_sheet_label = form.labelForField(self._secondary_dataset_combo)
        self._secondary_column_label = form.labelForField(self._secondary_column_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._operation_combo.currentIndexChanged.connect(self._update_scope)
        self._primary_dataset_combo.currentTextChanged.connect(self._refresh_primary_columns)
        self._secondary_dataset_combo.currentTextChanged.connect(self._refresh_secondary_columns)
        self._plot_result_checkbox.toggled.connect(self._plot_kind_combo.setEnabled)

        self._refresh_primary_columns(self._primary_dataset_combo.currentText())
        self._refresh_secondary_columns(self._secondary_dataset_combo.currentText())
        self._update_scope()

    def operation_key(self) -> str:
        """Return the selected statistics operation key."""
        return str(self._operation_combo.currentData())

    def primary_dataset_name(self) -> str:
        """Return the selected primary dataset name."""
        return self._primary_dataset_combo.currentText()

    def primary_column(self) -> str:
        """Return the selected primary column name."""
        columns = self.primary_columns()
        return columns[0] if columns else ""

    def primary_columns(self) -> list[str]:
        """Return selected primary/value columns."""
        return selected_list_items(self._primary_column_list)

    def multi_columns(self) -> list[str]:
        """Return selected source columns for multi-column operations."""
        return selected_list_items(self._multi_column_list)

    def secondary_dataset_name(self) -> str:
        """Return the selected secondary dataset name."""
        return self._secondary_dataset_combo.currentText()

    def secondary_column(self) -> str:
        """Return the selected secondary column name."""
        columns = self.secondary_columns()
        return columns[0] if columns else ""

    def secondary_columns(self) -> list[str]:
        """Return selected secondary/group columns."""
        return selected_list_items(self._secondary_column_list)

    def column_binding_mode(self) -> str:
        """Return how batch columns should be resolved on target sheets."""
        return str(self._column_binding_combo.currentData())

    def target_dataset_name(self) -> str:
        """Return requested statistics result dataset name."""
        return self._target_dataset_edit.text().strip()

    def target_dataset_names(self) -> list[str]:
        """Return selected target worksheets for batch statistics."""
        return selected_list_items(self._dataset_list)

    def plot_result_immediately(self) -> bool:
        """Return whether a companion plot should be created."""
        return self._plot_result_checkbox.isChecked()

    def statistics_plot_kind(self) -> str:
        """Return the selected companion plot kind."""
        return str(self._plot_kind_combo.currentData() or "auto")

    def requires_secondary_column(self) -> bool:
        """Return whether the selected operation needs a secondary/group column."""
        return self.operation_scope() in {"pair", "group"}

    def operation_scope(self) -> str:
        """Return the selected operation scope key."""
        operation = STATISTIC_OPERATIONS[self.operation_key()]
        return operation.scope

    def _refresh_primary_columns(self, dataset_name: str) -> None:
        """Refresh primary column choices for the selected dataset."""
        self._refresh_column_list(self._primary_column_list, dataset_name)
        self._refresh_multi_columns(dataset_name)

    def _refresh_secondary_columns(self, dataset_name: str) -> None:
        """Refresh secondary column choices for the selected dataset."""
        self._refresh_column_list(self._secondary_column_list, dataset_name)

    def _refresh_column_list(self, widget: QListWidget, dataset_name: str) -> None:
        """Reload one selectable column list from the dataset-column map."""
        previous = set(selected_list_items(widget))
        columns = self._dataset_columns.get(dataset_name, [])
        selected = previous.intersection(columns)
        widget.clear()
        for column in columns:
            widget.addItem(column)
            item = widget.item(widget.count() - 1)
            item.setSelected(column in selected)

    def _refresh_multi_columns(self, dataset_name: str) -> None:
        """Refresh multi-column operation choices for the selected dataset."""
        previous = set(self.multi_columns())
        columns = self._dataset_columns.get(dataset_name, [])
        selected = previous.intersection(columns)
        self._multi_column_list.clear()
        for column in columns:
            self._multi_column_list.addItem(column)
            item = self._multi_column_list.item(self._multi_column_list.count() - 1)
            item.setSelected(column in selected)

    def _update_scope(self) -> None:
        """Refresh controls for single, pair, or grouped operations."""
        scope = self.operation_scope()
        is_multi = scope == "multi"
        uses_secondary = scope in {"pair", "group"}
        self._primary_column_list.setVisible(not is_multi)
        self._primary_column_label.setVisible(not is_multi)
        self._multi_column_list.setVisible(is_multi)
        self._multi_columns_label.setVisible(is_multi)
        self._secondary_dataset_combo.setVisible(uses_secondary)
        self._secondary_sheet_label.setVisible(uses_secondary)
        self._secondary_column_list.setVisible(uses_secondary)
        self._secondary_column_label.setVisible(uses_secondary)
        self._secondary_dataset_combo.setEnabled(uses_secondary)
        self._secondary_column_list.setEnabled(uses_secondary)
        if scope == "group":
            self._secondary_sheet_label.setText("Group sheet")
            self._secondary_column_label.setText("Group column")
            self._secondary_column_list.setSelectionMode(QAbstractItemView.SingleSelection)
        else:
            self._secondary_sheet_label.setText("Secondary sheet")
            self._secondary_column_label.setText("Secondary columns")
            self._secondary_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._refresh_plot_kind_options()
        if scope == "pair":
            self._hint_label.setText(
                "Two-column operations can reuse one secondary column for several primary columns, or pair the same "
                "number of secondary columns by selection order. Paired tests and correlations align values by row."
            )
        elif scope == "group":
            self._hint_label.setText(
                "Grouped operations use one or more primary numeric value columns and split rows by the selected group/factor column."
            )
        elif scope == "multi":
            self._hint_label.setText(
                "Multiple-column operations use two or more numeric columns from the primary sheet for summaries, "
                "correlations, covariance, and PCA."
            )
        else:
            self._hint_label.setText(
                "Single-column operations use numeric values from the primary column and ignore blanks, text, and infinities."
            )

    def _refresh_plot_kind_options(self) -> None:
        """Reload companion plot choices for the selected statistics operation."""
        previous = self._plot_kind_combo.currentData()
        operation_key = self.operation_key()
        scope = self.operation_scope()
        options = [("Auto", "auto")]
        if scope == "pair":
            options.extend(
                [
                    ("Scatter", "scatter"),
                    ("Scatter + regression line", "regression"),
                    ("Box plot comparison", "box"),
                    ("Violin comparison", "violin"),
                    ("Bland-Altman", "bland_altman"),
                ]
            )
        elif scope == "group":
            options.extend(
                [
                    ("Box plot by group", "box"),
                    ("Violin by group", "violin"),
                ]
            )
        elif scope == "multi":
            options.extend(
                [
                    ("Box plot selected columns", "box"),
                    ("Violin selected columns", "violin"),
                ]
            )
            if operation_key in {"multi_complete", "multi_correlations"}:
                options.append(("Correlation heatmap", "correlation_heatmap"))
            if operation_key in {"multi_complete", "multi_pca"}:
                options.append(("PCA explained variance", "pca_variance"))
        else:
            options.extend(
                [
                    ("Histogram + normal curve", "histogram"),
                    ("Box plot", "box"),
                    ("Violin plot", "violin"),
                ]
            )
            if operation_key in {"single_zscore", "single_cumulative"}:
                options.append(("Result series", "result_series"))

        self._plot_kind_combo.blockSignals(True)
        self._plot_kind_combo.clear()
        for label, key in options:
            self._plot_kind_combo.addItem(label, key)
        index = self._plot_kind_combo.findData(previous)
        if index >= 0:
            self._plot_kind_combo.setCurrentIndex(index)
        self._plot_kind_combo.blockSignals(False)
        self._plot_kind_combo.setEnabled(self._plot_result_checkbox.isChecked())

    def accept(self) -> None:
        """Validate statistics selections before closing."""
        scope = self.operation_scope()
        if not self.target_dataset_names():
            QMessageBox.warning(self, "Statistics", "Choose at least one target sheet.")
            return
        if scope == "multi" and len(self.multi_columns()) < 2:
            QMessageBox.warning(self, "Statistics", "Choose at least two columns for a multiple-column operation.")
            return
        if scope != "multi" and not self.primary_columns():
            QMessageBox.warning(self, "Statistics", "Choose at least one primary column.")
            return
        if scope == "pair":
            secondary_count = len(self.secondary_columns())
            primary_count = len(self.primary_columns())
            if secondary_count not in {1, primary_count}:
                QMessageBox.warning(
                    self,
                    "Statistics",
                    "Choose one secondary column to reuse, or the same number of secondary columns as primary columns.",
                )
                return
        if scope == "group" and len(self.secondary_columns()) != 1:
            QMessageBox.warning(self, "Statistics", "Choose exactly one group column.")
            return
        super().accept()


class CustomFitModelDialog(QDialog):
    """Create or edit one expression-based custom fit model."""

    def __init__(
        self,
        model: CustomFitModel | None = None,
        existing_names: set[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build custom model fields and validation controls."""
        super().__init__(parent)
        self.setWindowTitle("Custom Fit Model")
        self.setModal(True)
        self.setMinimumWidth(680)
        self._existing_names = existing_names or set()
        self._model: CustomFitModel | None = model

        self._name_edit = QLineEdit(model.name if model else "Custom Model")
        self._parameters_edit = QLineEdit(
            ", ".join(model.parameter_names) if model else "a, b"
        )
        self._initial_edit = QLineEdit(
            ", ".join(f"{value:g}" for value in model.default_initial) if model else "1, 0"
        )
        self._expression_edit = QPlainTextEdit()
        self._expression_edit.setMinimumHeight(110)
        self._expression_edit.setPlainText(model.expression if model else "a*x + b")
        self._expression_edit.setPlaceholderText("Example: a*np.exp(-x/tau) + c")

        hint = QLabel(
            "Use x for the independent variable and comma-separated parameter names. "
            "Available namespaces include np, scipy.special, scipy.signal, scipy.stats, and scipy.integrate."
        )
        hint.setWordWrap(True)

        validate_button = QPushButton("Validate")
        validate_button.clicked.connect(self._validate_model)

        form = QFormLayout()
        form.addRow("Name", self._name_edit)
        form.addRow("Expression", self._expression_edit)
        form.addRow("Parameters", self._parameters_edit)
        form.addRow("Initial values", self._initial_edit)
        form.addRow("", hint)
        form.addRow("", validate_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def model(self) -> CustomFitModel:
        """Return the validated custom fit model."""
        if self._model is None:
            raise ValueError("Custom model has not been validated.")
        return self._model

    def accept(self) -> None:
        """Validate and accept the dialog."""
        try:
            self._model = self._model_from_fields()
        except Exception as exc:
            QMessageBox.warning(self, "Custom Fit Model", str(exc))
            return
        super().accept()

    def _validate_model(self) -> None:
        """Validate current fields and show the result to the user."""
        try:
            self._model = self._model_from_fields()
        except Exception as exc:
            QMessageBox.warning(self, "Custom Fit Model", str(exc))
            return
        QMessageBox.information(self, "Custom Fit Model", "Model expression is valid.")

    def _model_from_fields(self) -> CustomFitModel:
        """Create a custom model from the current dialog fields."""
        name = self._name_edit.text().strip()
        if name in self._existing_names:
            raise ValueError(f"A custom model named '{name}' already exists.")
        return create_custom_fit_model(
            name=name,
            expression=self._expression_edit.toPlainText(),
            parameter_names=self._parse_csv_text(self._parameters_edit.text()),
            default_initial=[float(value) for value in self._parse_csv_text(self._initial_edit.text())],
        )

    @staticmethod
    def _parse_csv_text(text: str) -> list[str]:
        """Return comma-separated entries with whitespace stripped."""
        return [item.strip() for item in text.split(",") if item.strip()]


class CustomFitModelsDialog(QDialog):
    """Manage project custom fit models."""

    def __init__(self, models: list[CustomFitModel], parent: QWidget | None = None) -> None:
        """Build the custom model manager."""
        super().__init__(parent)
        self.setWindowTitle("Custom Fit Models")
        self.setModal(True)
        self.resize(720, 420)
        self._models = list(models)

        self._model_list = QListWidget()
        self._model_list.currentRowChanged.connect(self._update_preview)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)

        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_model)
        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(self._edit_model)
        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(self._duplicate_model)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_model)

        button_row = QHBoxLayout()
        button_row.addWidget(add_button)
        button_row.addWidget(edit_button)
        button_row.addWidget(duplicate_button)
        button_row.addWidget(remove_button)
        button_row.addStretch(1)

        content_row = QHBoxLayout()
        content_row.addWidget(self._model_list, 1)
        content_row.addWidget(self._preview, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(content_row)
        layout.addLayout(button_row)
        layout.addWidget(buttons)
        self._refresh_model_list()

    def custom_models(self) -> list[CustomFitModel]:
        """Return the edited custom fit model list."""
        return list(self._models)

    def _add_model(self) -> None:
        """Create a new custom model."""
        dialog = CustomFitModelDialog(existing_names=self._model_names(), parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._models.append(dialog.model())
        self._refresh_model_list(len(self._models) - 1)

    def _edit_model(self) -> None:
        """Edit the selected custom model."""
        row = self._selected_row()
        if row is None:
            QMessageBox.information(self, "Custom Fit Models", "Select a model before editing it.")
            return
        model = self._models[row]
        dialog = CustomFitModelDialog(
            model=model,
            existing_names=self._model_names(excluding=row),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._models[row] = dialog.model()
        self._refresh_model_list(row)

    def _duplicate_model(self) -> None:
        """Duplicate the selected custom model."""
        row = self._selected_row()
        if row is None:
            QMessageBox.information(self, "Custom Fit Models", "Select a model before duplicating it.")
            return
        source = self._models[row]
        model = CustomFitModel(
            name=self._unique_name(f"{source.name} Copy"),
            expression=source.expression,
            parameter_names=source.parameter_names,
            default_initial=source.default_initial,
        )
        self._models.append(model)
        self._refresh_model_list(len(self._models) - 1)

    def _remove_model(self) -> None:
        """Remove the selected custom model."""
        row = self._selected_row()
        if row is None:
            QMessageBox.information(self, "Custom Fit Models", "Select a model before removing it.")
            return
        self._models.pop(row)
        self._refresh_model_list(min(row, len(self._models) - 1))

    def _refresh_model_list(self, selected_row: int | None = None) -> None:
        """Refresh the visible model list."""
        self._model_list.blockSignals(True)
        self._model_list.clear()
        self._model_list.addItems([model.name for model in self._models])
        self._model_list.blockSignals(False)
        if selected_row is not None and selected_row >= 0 and self._models:
            self._model_list.setCurrentRow(selected_row)
        elif self._models:
            self._model_list.setCurrentRow(0)
        else:
            self._update_preview()

    def _update_preview(self) -> None:
        """Show a read-only summary for the selected model."""
        row = self._selected_row()
        if row is None:
            self._preview.clear()
            return
        model = self._models[row]
        initial_values = ", ".join(f"{value:g}" for value in model.default_initial)
        self._preview.setPlainText(
            f"Name: {model.name}\n"
            f"Expression: {model.expression}\n"
            f"Parameters: {', '.join(model.parameter_names)}\n"
            f"Initial values: {initial_values}"
        )

    def _selected_row(self) -> int | None:
        """Return the selected model row, if any."""
        row = self._model_list.currentRow()
        return row if 0 <= row < len(self._models) else None

    def _model_names(self, excluding: int | None = None) -> set[str]:
        """Return existing model names, optionally excluding one row."""
        return {
            model.name
            for index, model in enumerate(self._models)
            if excluding is None or index != excluding
        }

    def _unique_name(self, base_name: str) -> str:
        """Return a custom model name unique within the manager."""
        names = self._model_names()
        if base_name not in names:
            return base_name
        counter = 2
        while f"{base_name} ({counter})" in names:
            counter += 1
        return f"{base_name} ({counter})"


class FitDialog(QDialog):
    """Collect settings for curve fitting."""

    def __init__(
        self,
        column_names: list[str],
        default_dataset_name: str,
        custom_models: list[CustomFitModel] | None = None,
        default_x_column: str | None = None,
        dataset_names: list[str] | None = None,
        current_dataset_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for model selection, optimizer settings, and outputs."""
        super().__init__(parent)
        self.setWindowTitle("Curve Fit")
        self.setModal(True)
        self.setMinimumWidth(960)
        self.resize(1020, 640)
        self._custom_models = custom_models or []
        self._current_dataset_name = current_dataset_name or default_dataset_name

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItems(column_names)
        self._set_combo_text_if_present(self._x_column_combo, default_x_column)

        self._y_column_list = QListWidget()
        self._y_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._y_column_list.setMaximumHeight(96)
        self._y_column_list.addItems(column_names)
        self._y_column_list.setToolTip(
            "Select one or more response columns explicitly; none are selected automatically."
        )

        self._model_combo = QComboBox()
        for model in available_fit_models(self._custom_models):
            self._model_combo.addItem(model.name, model.key)

        self._method_combo = QComboBox()
        for method_key, method_label in FIT_METHODS.items():
            self._method_combo.addItem(method_label, method_key)
        self._method_combo.setCurrentText(FIT_METHODS["trf"])

        self._parameter_table = QTableWidget(0, 5)
        self._parameter_table.setHorizontalHeaderLabels(["Parameter", "Initial", "Lower", "Upper", "Fixed"])
        self._parameter_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._parameter_table.verticalHeader().setVisible(False)
        self._parameter_table.setMinimumHeight(150)

        self._parameter_hint = QLabel()
        self._parameter_hint.setWordWrap(True)
        self._parameter_hint.setTextFormat(Qt.RichText)
        self._parameter_hint.setMaximumHeight(82)

        self._x_weight_column_combo = QComboBox()
        self._x_weight_column_combo.addItem("None", None)
        for column_name in column_names:
            self._x_weight_column_combo.addItem(column_name, column_name)

        self._weight_column_list = QListWidget()
        self._weight_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._weight_column_list.setMaximumHeight(82)
        self._weight_column_list.addItems(column_names)
        self._weight_column_list.setToolTip(
            "Optional: select weight/sigma columns explicitly; none are selected automatically."
        )

        self._weight_mode_combo = QComboBox()
        self._weight_mode_combo.addItem("Sigma / standard deviation", "sigma")
        self._weight_mode_combo.addItem("Weight (larger = stronger)", "weight")

        self._absolute_sigma_checkbox = QCheckBox("Treat sigma as absolute")

        self._confidence_checkbox = QCheckBox("Create confidence band")
        self._confidence_checkbox.setChecked(True)

        self._confidence_spin = QDoubleSpinBox()
        self._confidence_spin.setRange(50.0, 99.9)
        self._confidence_spin.setSingleStep(1.0)
        self._confidence_spin.setValue(95.0)
        self._confidence_spin.setSuffix(" %")

        self._residual_sheet_checkbox = QCheckBox("Create residual sheet")
        self._residual_sheet_checkbox.setChecked(True)

        self._plot_residuals_checkbox = QCheckBox("Plot residuals on right axis")
        self._plot_residuals_checkbox.setChecked(True)

        self._parameter_correlation_sheet_checkbox = QCheckBox("Create parameter covariance/correlation sheet")
        self._parameter_correlation_sheet_checkbox.setToolTip(
            "Creates a long-format sheet with covariance and normalized parameter correlation pairs when available."
        )

        self._fit_points_spin = QSpinBox()
        self._fit_points_spin.setRange(10, 10000)
        self._fit_points_spin.setSingleStep(50)
        self._fit_points_spin.setValue(400)

        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_fit")
        self._residual_dataset_edit = QLineEdit(f"{default_dataset_name}_residuals")
        self._column_binding_combo = batch_column_binding_combo()
        self._dataset_list = QListWidget()
        self._dataset_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._dataset_list.setMaximumHeight(96)
        for dataset_name in dataset_names or [self._current_dataset_name]:
            if not dataset_name:
                continue
            self._dataset_list.addItem(dataset_name)
            item = self._dataset_list.item(self._dataset_list.count() - 1)
            item.setSelected(dataset_name == self._current_dataset_name)

        self._batch_hint = QLabel(
            "Batch mode repeats the same X/model/parameter settings on each selected sheet and "
            "fits every selected Y column. Leave Y weight/sigma empty for none; select one "
            "Y weight/sigma column for every Y column, or select the same number to pair by order. "
            "Use {source} and {column} in result and residual sheet names for custom batch naming."
        )
        self._batch_hint.setWordWrap(True)

        for combo in (
            self._x_column_combo,
            self._model_combo,
            self._method_combo,
            self._x_weight_column_combo,
            self._weight_mode_combo,
            self._column_binding_combo,
        ):
            combo.setMinimumContentsLength(18)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

        source_group = QGroupBox("Source")
        source_form = QFormLayout(source_group)
        source_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        source_form.addRow("X column", self._x_column_combo)
        source_form.addRow("Y columns", self._y_column_list)
        source_form.addRow("Column matching", self._column_binding_combo)

        model_group = QGroupBox("Model")
        model_layout = QVBoxLayout(model_group)
        model_form = QFormLayout()
        model_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        model_form.addRow("Model", self._model_combo)
        model_form.addRow("Method", self._method_combo)
        model_layout.addLayout(model_form)
        model_layout.addWidget(self._parameter_table)
        model_layout.addWidget(self._parameter_hint)

        setup_row = QHBoxLayout()
        setup_row.addWidget(source_group, 1)
        setup_row.addWidget(model_group, 2)

        uncertainty_tab = QWidget()
        uncertainty_form = QFormLayout(uncertainty_tab)
        uncertainty_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        uncertainty_form.addRow("X weight/sigma column", self._x_weight_column_combo)
        uncertainty_form.addRow("Y weight/sigma columns", self._weight_column_list)
        uncertainty_form.addRow("Weight mode", self._weight_mode_combo)
        uncertainty_form.addRow("", self._absolute_sigma_checkbox)

        confidence_row = QWidget()
        confidence_layout = QHBoxLayout(confidence_row)
        confidence_layout.setContentsMargins(0, 0, 0, 0)
        confidence_layout.addWidget(self._confidence_checkbox)
        confidence_layout.addWidget(self._confidence_spin)
        confidence_layout.addStretch(1)
        output_tab = QWidget()
        output_form = QFormLayout(output_tab)
        output_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        output_form.addRow("", confidence_row)
        output_form.addRow("Fit points", self._fit_points_spin)
        output_form.addRow("Result sheet", self._target_dataset_edit)
        output_form.addRow("", self._residual_sheet_checkbox)
        output_form.addRow("", self._plot_residuals_checkbox)
        output_form.addRow("Residual sheet", self._residual_dataset_edit)
        output_form.addRow("", self._parameter_correlation_sheet_checkbox)

        batch_tab = QWidget()
        batch_form = QFormLayout(batch_tab)
        batch_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        batch_form.addRow("Apply to sheets", self._dataset_list)
        batch_form.addRow("", self._batch_hint)

        options_tabs = QTabWidget()
        options_tabs.addTab(uncertainty_tab, "Uncertainty")
        options_tabs.addTab(output_tab, "Output")
        options_tabs.addTab(batch_tab, "Batch")
        options_tabs.setMinimumHeight(180)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(setup_row, 1)
        layout.addWidget(options_tabs)
        layout.addWidget(buttons)

        self._model_combo.currentIndexChanged.connect(self._update_parameter_hint)
        self._confidence_checkbox.toggled.connect(self._confidence_spin.setEnabled)
        self._residual_sheet_checkbox.toggled.connect(self._residual_dataset_edit.setEnabled)
        self._x_weight_column_combo.currentTextChanged.connect(self._on_x_weight_changed)
        self._update_parameter_hint()
        self._on_x_weight_changed()

    def _on_x_weight_changed(self) -> None:
        """Lock method to ODR if X errors are provided."""
        has_x_weight = self.x_weight_column() is not None
        if has_x_weight:
            self._method_combo.setCurrentText(FIT_METHODS.get("odr", "Orthogonal Distance Regression"))
            self._method_combo.setEnabled(False)
        else:
            self._method_combo.setEnabled(True)
            if self.method() == "odr":
                self._method_combo.setCurrentText(FIT_METHODS.get("trf", "Trust Region Reflective"))

    @staticmethod
    def _set_combo_text_if_present(combo: QComboBox, value: str | None) -> None:
        """Select a combo item by text when it exists."""
        if not value:
            return
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def x_column(self) -> str:
        """Return selected X column."""
        return self._x_column_combo.currentText()

    def y_column(self) -> str:
        """Return the first selected Y column."""
        columns = self.y_columns()
        return columns[0] if columns else ""

    def y_columns(self) -> list[str]:
        """Return selected Y columns."""
        return selected_list_items(self._y_column_list)

    def model_key(self) -> str:
        """Return selected fit model key."""
        return str(self._model_combo.currentData())

    def method(self) -> str:
        """Return selected optimizer method key."""
        return str(self._method_combo.currentData())

    def initial_parameters_text(self) -> str:
        """Return raw initial-parameter text."""
        return ", ".join(f"{value:g}" for value in self.initial_parameters())

    def initial_parameters(self) -> list[float]:
        """Return initial parameter values in model order."""
        return [self._table_float(row, 1, f"initial value for {self._parameter_name(row)}") for row in range(self._parameter_table.rowCount())]

    def lower_bounds(self) -> list[float | None]:
        """Return lower bounds in model order."""
        return [self._optional_table_float(row, 2, f"lower bound for {self._parameter_name(row)}") for row in range(self._parameter_table.rowCount())]

    def upper_bounds(self) -> list[float | None]:
        """Return upper bounds in model order."""
        return [self._optional_table_float(row, 3, f"upper bound for {self._parameter_name(row)}") for row in range(self._parameter_table.rowCount())]

    def fixed_parameters(self) -> list[bool]:
        """Return fixed/free settings in model order."""
        settings: list[bool] = []
        for row in range(self._parameter_table.rowCount()):
            item = self._parameter_table.item(row, 4)
            settings.append(item.checkState() == Qt.Checked if item is not None else False)
        return settings

    def x_weight_column(self) -> str | None:
        """Return optional X weight/sigma column."""
        value = self._x_weight_column_combo.currentData()
        return str(value) if value else None

    def weight_column(self) -> str | None:
        """Return the first optional Y weight/sigma column."""
        columns = self.weight_columns()
        return columns[0] if columns else None

    def weight_columns(self) -> list[str]:
        """Return selected Y weight/sigma columns."""
        return selected_list_items(self._weight_column_list)

    def column_binding_mode(self) -> str:
        """Return how fit columns should be matched in batch mode."""
        return str(self._column_binding_combo.currentData() or BATCH_COLUMN_BINDING_NAME)

    def weight_mode(self) -> str:
        """Return how the selected weight/sigma column should be interpreted."""
        return str(self._weight_mode_combo.currentData())

    def absolute_sigma(self) -> bool:
        """Return whether sigma values should be treated as absolute."""
        return self._absolute_sigma_checkbox.isChecked()

    def include_confidence_band(self) -> bool:
        """Return whether confidence band columns should be created."""
        return self._confidence_checkbox.isChecked()

    def confidence_level(self) -> float:
        """Return confidence level as a fraction."""
        return self._confidence_spin.value() / 100.0

    def create_residual_sheet(self) -> bool:
        """Return whether a residual workspace sheet should be created."""
        return self._residual_sheet_checkbox.isChecked()

    def plot_residuals(self) -> bool:
        """Return whether residuals should be shown with the fit plot."""
        return self._plot_residuals_checkbox.isChecked()

    def create_parameter_correlation_sheet(self) -> bool:
        """Return whether parameter covariance/correlation rows should be saved."""
        return self._parameter_correlation_sheet_checkbox.isChecked()

    def fit_points(self) -> int:
        """Return number of points to generate for the fitted curve."""
        return self._fit_points_spin.value()

    def target_dataset_name(self) -> str:
        """Return requested result dataset name."""
        return self._target_dataset_edit.text().strip()

    def residual_dataset_name(self) -> str:
        """Return requested residual dataset name."""
        return self._residual_dataset_edit.text().strip()

    def target_dataset_names(self) -> list[str]:
        """Return worksheet names selected for curve fitting."""
        return [item.text() for item in self._dataset_list.selectedItems()]

    def accept(self) -> None:
        """Validate curve-fit batch selection before accepting."""
        y_columns = self.y_columns()
        weight_columns = self.weight_columns()
        if not self.x_column() or not y_columns:
            QMessageBox.warning(self, "Curve Fit", "Choose X and at least one Y column.")
            return
        if weight_columns and len(weight_columns) not in {1, len(y_columns)}:
            QMessageBox.warning(
                self,
                "Curve Fit",
                "Select zero, one, or the same number of Y weight/sigma columns as Y columns.",
            )
            return
        if not self.target_dataset_names():
            QMessageBox.warning(self, "Curve Fit", "Choose at least one target sheet.")
            return
        super().accept()

    def _update_parameter_hint(self) -> None:
        """Refresh model equation help and rebuild the parameter table."""
        model = get_fit_model(self.model_key(), self._custom_models)
        parameter_names = ", ".join(model.parameter_names)
        defaults = ", ".join(f"{value:g}" for value in model.default_initial)
        hint = (
            f"<b>Equation:</b> <code>{escape(model.equation)}</code><br>"
            f"<b>Parameter order:</b> <code>{escape(parameter_names)}</code><br>"
            f"Edit initial guesses and optional bounds. Blank bounds are unbounded. "
            f"Static defaults: <code>{escape(defaults)}</code>."
        )
        self._parameter_hint.setText(hint)
        self._parameter_hint.setToolTip(hint)
        self._populate_parameter_table()

    def _populate_parameter_table(self) -> None:
        """Populate editable parameter rows for the selected model."""
        model = get_fit_model(self.model_key(), self._custom_models)
        self._parameter_table.setRowCount(len(model.parameter_names))
        for row, (name, initial_value) in enumerate(zip(model.parameter_names, model.default_initial)):
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self._parameter_table.setItem(row, 0, name_item)
            self._parameter_table.setItem(row, 1, QTableWidgetItem(f"{initial_value:g}"))
            self._parameter_table.setItem(row, 2, QTableWidgetItem(""))
            self._parameter_table.setItem(row, 3, QTableWidgetItem(""))
            fixed_item = QTableWidgetItem("")
            fixed_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            fixed_item.setCheckState(Qt.Unchecked)
            self._parameter_table.setItem(row, 4, fixed_item)

    def _parameter_name(self, row: int) -> str:
        """Return the displayed model parameter name for a table row."""
        item = self._parameter_table.item(row, 0)
        return item.text() if item is not None else f"parameter {row + 1}"

    def _table_float(self, row: int, column: int, label: str) -> float:
        """Parse a required floating-point value from the parameter table."""
        item = self._parameter_table.item(row, column)
        text = item.text().strip() if item is not None else ""
        if not text:
            raise ValueError(f"Enter {label}.")
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{label.capitalize()} must be numeric.") from exc

    def _optional_table_float(self, row: int, column: int, label: str) -> float | None:
        """Parse an optional floating-point value from the parameter table."""
        item = self._parameter_table.item(row, column)
        text = item.text().strip() if item is not None else ""
        if not text:
            return None
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{label.capitalize()} must be numeric.") from exc


class FitReportDialog(QDialog):
    """Display a curve-fitting report."""

    def __init__(self, report_text: str, parent: QWidget | None = None) -> None:
        """Create a read-only report viewer dialog."""
        super().__init__(parent)
        self.setWindowTitle("Fit Report")
        self.setModal(True)
        self.resize(640, 520)

        report_edit = QPlainTextEdit()
        report_edit.setReadOnly(True)
        report_edit.setPlainText(report_text)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(report_edit)
        layout.addWidget(buttons)


def derivative_methods() -> dict[str, str]:
    """Return derivative method labels for dialog construction."""
    return DERIVATIVE_METHODS


def integration_methods() -> dict[str, str]:
    """Return integration method labels for dialog construction."""
    return INTEGRATION_METHODS
