"""Qt table model for editing pandas DataFrames in the workspace."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Number
from typing import Any

import pandas as pd
from pandas.api.types import is_numeric_dtype
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, Signal

from core.operations import ExpressionResult, apply_column_expression
from core.workspace import Dataset


@dataclass(slots=True)
class _DatasetSnapshot:
    """Stored dataset state for undo/redo history."""

    frame: pd.DataFrame
    formulas: dict[str, str]


class DataFrameTableModel(QAbstractTableModel):
    """Editable table model that writes changes directly into a workspace dataset."""

    history_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        """Create an empty model until a workspace dataset is attached."""
        super().__init__(parent)
        self._dataset: Dataset | None = None
        self._undo_stack: list[_DatasetSnapshot] = []
        self._redo_stack: list[_DatasetSnapshot] = []

    @property
    def dataset(self) -> Dataset | None:
        """Return the dataset currently shown by the model."""
        return self._dataset

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Replace the displayed dataset."""
        self.beginResetModel()
        self._dataset = dataset
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.endResetModel()
        self.history_changed.emit()

    def can_undo(self) -> bool:
        """Return whether a dataset edit can be undone."""
        return bool(self._undo_stack and self._dataset is not None)

    def can_redo(self) -> bool:
        """Return whether an undone dataset edit can be redone."""
        return bool(self._redo_stack and self._dataset is not None)

    def capture_undo_state(self) -> None:
        """Push the current dataset state before an external in-place edit."""
        if self._dataset is None:
            return
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()

    def discard_latest_undo_state(self) -> None:
        """Remove the most recent pending undo state when an external edit failed."""
        if self._undo_stack:
            self._undo_stack.pop()
            self.history_changed.emit()

    def undo(self) -> bool:
        """Restore the previous dataset state."""
        if self._dataset is None or not self._undo_stack:
            return False
        self._redo_stack.append(self._snapshot())
        self._restore_snapshot(self._undo_stack.pop())
        self.history_changed.emit()
        return True

    def redo(self) -> bool:
        """Restore the next dataset state after an undo."""
        if self._dataset is None or not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot())
        self._restore_snapshot(self._redo_stack.pop())
        self.history_changed.emit()
        return True

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of visible DataFrame rows for Qt views."""
        if parent.isValid() or self._dataset is None:
            return 0
        return len(self._dataset.frame)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of visible DataFrame columns for Qt views."""
        if parent.isValid() or self._dataset is None:
            return 0
        return len(self._dataset.frame.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> str | None:
        """Return display/edit text for one DataFrame cell."""
        if not index.isValid() or self._dataset is None:
            return None

        if role not in (Qt.DisplayRole, Qt.EditRole):
            return None

        value = self._dataset.frame.iat[index.row(), index.column()]
        if pd.isna(value):
            return ""
        return str(value)

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        """Write a user edit back into the backing DataFrame."""
        if not index.isValid() or self._dataset is None or role != Qt.EditRole:
            return False

        frame = self._dataset.frame
        column_name = frame.columns[index.column()]
        normalized_value = self._normalize_value(frame[column_name], value)
        old_value = frame.iat[index.row(), index.column()]
        if self._values_equal(old_value, normalized_value):
            return False

        self.capture_undo_state()
        if not self._value_fits_column(frame[column_name], normalized_value):
            frame[column_name] = frame[column_name].astype("object")

        frame.iat[index.row(), index.column()] = normalized_value
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        self.history_changed.emit()
        return True

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> str | None:
        """Return row/column labels and formula tooltips for Qt headers."""
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
        """Return Qt item flags making valid cells selectable and editable."""
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

        self.capture_undo_state()
        self.beginResetModel()
        self._dataset.frame.drop(self._dataset.frame.index[valid_rows], inplace=True)
        self._dataset.frame.reset_index(drop=True, inplace=True)
        self.endResetModel()
        self.history_changed.emit()
        return len(valid_rows)

    def add_row(self) -> None:
        """Add an empty row to the end of the current dataset."""
        if self._dataset is None:
            return

        self.capture_undo_state()
        insert_position = len(self._dataset.frame)
        self.beginInsertRows(QModelIndex(), insert_position, insert_position)
        # Append a row of NAs
        new_row = pd.Series([pd.NA] * len(self._dataset.frame.columns), index=self._dataset.frame.columns)
        self._dataset.frame.loc[insert_position] = new_row
        self.endInsertRows()
        self.history_changed.emit()

    def delete_columns(self, columns: list[int]) -> list[str]:
        """Delete column positions from the current dataset and return removed names."""
        if self._dataset is None:
            return []

        frame = self._dataset.frame
        valid_columns = sorted({column for column in columns if 0 <= column < len(frame.columns)})
        if not valid_columns:
            return []

        deleted_names = [str(frame.columns[column]) for column in valid_columns]

        self.capture_undo_state()
        self.beginResetModel()
        frame.drop(columns=frame.columns[valid_columns], inplace=True)
        for column_name in deleted_names:
            self._dataset.formulas.pop(column_name, None)
        self.endResetModel()
        self.history_changed.emit()
        return deleted_names

    def add_empty_column(self, column_name: str) -> str:
        """Add an empty column to the current dataset and return its final unique name."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")

        clean_name = column_name.strip() or "New Column"
        unique_name = self._make_unique_column_name(clean_name)
        insert_position = len(self._dataset.frame.columns)

        self.capture_undo_state()
        self.beginInsertColumns(QModelIndex(), insert_position, insert_position)
        self._dataset.frame[unique_name] = pd.NA
        self._dataset.formulas.pop(unique_name, None)
        self.endInsertColumns()
        self.history_changed.emit()
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

        self.capture_undo_state()
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
        except Exception:
            self.discard_latest_undo_state()
            raise
        finally:
            self.endResetModel()
            self.history_changed.emit()

    def _normalize_value(self, column: pd.Series, value: Any) -> object:
        """Coerce edited text to a numeric value when the column supports it."""
        text = str(value).strip()
        if text == "":
            return pd.NA

        if is_numeric_dtype(column):
            numeric_value = pd.to_numeric(text, errors="coerce")
            if not pd.isna(numeric_value):
                return numeric_value

        return text

    def _value_fits_column(self, column: pd.Series, value: object) -> bool:
        """Return whether a value can be stored without widening column dtype."""
        if not is_numeric_dtype(column):
            return True

        if pd.isna(value):
            return column.dtype.kind == "f"

        return isinstance(value, Number)

    def _make_unique_column_name(self, base_name: str) -> str:
        """Return a column name that does not collide with existing columns."""
        if self._dataset is None:
            return base_name

        existing_names = {str(column) for column in self._dataset.frame.columns}
        if base_name not in existing_names:
            return base_name

        counter = 2
        while f"{base_name} ({counter})" in existing_names:
            counter += 1
        return f"{base_name} ({counter})"

    def _snapshot(self) -> _DatasetSnapshot:
        """Return a deep copy of the current dataset edit state."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")
        return _DatasetSnapshot(
            frame=self._dataset.frame.copy(deep=True),
            formulas=dict(self._dataset.formulas),
        )

    def _restore_snapshot(self, snapshot: _DatasetSnapshot) -> None:
        """Replace the current dataset contents with a stored snapshot."""
        if self._dataset is None:
            return
        self.beginResetModel()
        self._dataset.frame = snapshot.frame.copy(deep=True)
        self._dataset.formulas = dict(snapshot.formulas)
        self.endResetModel()

    @staticmethod
    def _values_equal(left: object, right: object) -> bool:
        """Return whether two cell values should be treated as equivalent."""
        if pd.isna(left) and pd.isna(right):
            return True
        try:
            return bool(left == right)
        except TypeError:
            return False
