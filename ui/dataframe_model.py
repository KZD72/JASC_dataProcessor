"""Qt table model for editing pandas DataFrames in the workspace."""

from __future__ import annotations

from numbers import Number
from typing import Any

import pandas as pd
from pandas.api.types import is_numeric_dtype
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from core.operations import ExpressionResult, apply_column_expression
from core.workspace import Dataset


class DataFrameTableModel(QAbstractTableModel):
    """Editable table model that writes changes directly into a workspace dataset."""

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self._dataset: Dataset | None = None

    @property
    def dataset(self) -> Dataset | None:
        """Return the dataset currently shown by the model."""
        return self._dataset

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Replace the displayed dataset."""
        self.beginResetModel()
        self._dataset = dataset
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._dataset is None:
            return 0
        return len(self._dataset.frame)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._dataset is None:
            return 0
        return len(self._dataset.frame.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> str | None:
        if not index.isValid() or self._dataset is None:
            return None

        if role not in (Qt.DisplayRole, Qt.EditRole):
            return None

        value = self._dataset.frame.iat[index.row(), index.column()]
        if pd.isna(value):
            return ""
        return str(value)

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or self._dataset is None or role != Qt.EditRole:
            return False

        frame = self._dataset.frame
        column_name = frame.columns[index.column()]
        normalized_value = self._normalize_value(frame[column_name], value)

        if not self._value_fits_column(frame[column_name], normalized_value):
            frame[column_name] = frame[column_name].astype("object")

        frame.iat[index.row(), index.column()] = normalized_value
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        return True

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> str | None:
        if self._dataset is None:
            return None

        if role == Qt.ToolTipRole and orientation == Qt.Horizontal:
            column_name = str(self._dataset.frame.columns[section])
            formula = self._dataset.formulas.get(column_name)
            if formula:
                return f"Formula: {formula}"
            return None

        if role != Qt.DisplayRole:
            return None

        if orientation == Qt.Horizontal:
            return str(self._dataset.frame.columns[section])
        return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def delete_rows(self, rows: list[int]) -> int:
        """Delete row positions from the current dataset and return the count removed."""
        if self._dataset is None:
            return 0

        valid_rows = sorted({row for row in rows if 0 <= row < len(self._dataset.frame)})
        if not valid_rows:
            return 0

        self.beginResetModel()
        self._dataset.frame.drop(self._dataset.frame.index[valid_rows], inplace=True)
        self._dataset.frame.reset_index(drop=True, inplace=True)
        self.endResetModel()
        return len(valid_rows)

    def delete_columns(self, columns: list[int]) -> list[str]:
        """Delete column positions from the current dataset and return removed names."""
        if self._dataset is None:
            return []

        frame = self._dataset.frame
        valid_columns = sorted({column for column in columns if 0 <= column < len(frame.columns)})
        if not valid_columns:
            return []

        deleted_names = [str(frame.columns[column]) for column in valid_columns]

        self.beginResetModel()
        frame.drop(columns=frame.columns[valid_columns], inplace=True)
        for column_name in deleted_names:
            self._dataset.formulas.pop(column_name, None)
        self.endResetModel()
        return deleted_names

    def add_empty_column(self, column_name: str) -> str:
        """Add an empty column to the current dataset and return its final unique name."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")

        clean_name = column_name.strip() or "New Column"
        unique_name = self._make_unique_column_name(clean_name)
        insert_position = len(self._dataset.frame.columns)

        self.beginInsertColumns(QModelIndex(), insert_position, insert_position)
        self._dataset.frame[unique_name] = pd.NA
        self._dataset.formulas.pop(unique_name, None)
        self.endInsertColumns()
        return unique_name

    def apply_expression(
        self,
        target_column: str,
        expression: str,
        row_positions: list[int] | None = None,
    ) -> ExpressionResult:
        """Apply a column expression to the current dataset."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")

        self.beginResetModel()
        try:
            result = apply_column_expression(
                self._dataset.frame,
                target_column=target_column,
                expression=expression,
                row_positions=row_positions,
            )
            self._dataset.formulas[result.target_column] = expression.strip()
            return result
        finally:
            self.endResetModel()

    def _normalize_value(self, column: pd.Series, value: Any) -> object:
        text = str(value).strip()
        if text == "":
            return pd.NA

        if is_numeric_dtype(column):
            numeric_value = pd.to_numeric(text, errors="coerce")
            if not pd.isna(numeric_value):
                return numeric_value

        return text

    def _value_fits_column(self, column: pd.Series, value: object) -> bool:
        if not is_numeric_dtype(column):
            return True

        if pd.isna(value):
            return not is_numeric_dtype(column) or column.dtype.kind == "f"

        return isinstance(value, Number)

    def _make_unique_column_name(self, base_name: str) -> str:
        if self._dataset is None:
            return base_name

        existing_names = {str(column) for column in self._dataset.frame.columns}
        if base_name not in existing_names:
            return base_name

        counter = 2
        while f"{base_name} ({counter})" in existing_names:
            counter += 1
        return f"{base_name} ({counter})"
