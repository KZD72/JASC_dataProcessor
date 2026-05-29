"""Qt table model for editing pandas DataFrames in the workspace."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Number
from typing import Any

import pandas as pd
from pandas.api.types import is_numeric_dtype
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, Signal

from core.operations import ExpressionResult, apply_column_expression
from core.workspace import ColumnMetadata, Dataset, column_role_label, copy_column_metadata


@dataclass(slots=True)
class _DatasetSnapshot:
    """Stored dataset state for undo/redo history."""

    frame: pd.DataFrame
    formulas: dict[str, str]
    column_metadata: dict[str, ColumnMetadata]


class DataFrameTableModel(QAbstractTableModel):
    """Editable table model that writes changes directly into a workspace dataset."""

    history_changed = Signal()
    columns_renamed = Signal(dict)

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
        """Return row/column labels and metadata/formula tooltips for Qt headers."""
        if self._dataset is None:
            return None

        if role == Qt.ToolTipRole and orientation == Qt.Horizontal:
            column_name = str(self._dataset.frame.columns[section])
            metadata = self._dataset.column_metadata.get(column_name)
            formula = self._dataset.formulas.get(column_name)
            lines: list[str] = []
            if metadata is not None:
                if metadata.long_name:
                    lines.append(f"Long name: {metadata.long_name}")
                if metadata.role:
                    lines.append(f"Role: {column_role_label(metadata.role)}")
                if metadata.unit:
                    lines.append(f"Unit: {metadata.unit}")
                if metadata.comment:
                    lines.append(f"Comment: {metadata.comment}")
            if formula:
                lines.append(f"Formula: {formula}")
            return "\n".join(lines) if lines else None

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

        self.insert_row(len(self._dataset.frame))

    def insert_row(self, position: int) -> int:
        """Insert an empty row before the requested row position and return its index."""
        if self._dataset is None:
            return -1

        insert_position = max(0, min(position, len(self._dataset.frame)))
        self.capture_undo_state()
        self.beginInsertRows(QModelIndex(), insert_position, insert_position)
        upper = self._dataset.frame.iloc[:insert_position]
        lower = self._dataset.frame.iloc[insert_position:]
        new_row = pd.DataFrame(
            [[pd.NA] * len(self._dataset.frame.columns)],
            columns=self._dataset.frame.columns,
        )
        self._dataset.frame = pd.concat([upper, new_row, lower], ignore_index=True)
        self.endInsertRows()
        self.history_changed.emit()
        return insert_position

    def paste_block(self, start_row: int, start_column: int, rows: list[list[str]]) -> tuple[int, int]:
        """Paste a rectangular text block into the dataset, growing rows/columns as needed."""
        if self._dataset is None or not rows:
            return (0, 0)

        normalized_start_row = max(start_row, 0)
        normalized_start_column = max(start_column, 0)
        row_count = len(rows)
        column_count = max((len(row) for row in rows), default=0)
        if column_count == 0:
            return (0, 0)

        self.capture_undo_state()
        self.beginResetModel()
        try:
            frame = self._dataset.frame
            target_rows = normalized_start_row + row_count
            target_columns = normalized_start_column + column_count

            while len(frame.columns) < target_columns:
                column_name = self._make_unique_column_name(f"Column {len(frame.columns) + 1}")
                frame[column_name] = pd.NA
                self._dataset.formulas.pop(column_name, None)
                self._dataset.column_metadata.pop(column_name, None)

            while len(frame) < target_rows:
                frame.loc[len(frame)] = pd.Series([pd.NA] * len(frame.columns), index=frame.columns)

            for row_offset, row_values in enumerate(rows):
                for column_offset, value in enumerate(row_values):
                    target_column = normalized_start_column + column_offset
                    column_name = frame.columns[target_column]
                    self._dataset.formulas.pop(str(column_name), None)
                    normalized_value = self._normalize_value(frame[column_name], value)
                    if not self._value_fits_column(frame[column_name], normalized_value):
                        frame[column_name] = frame[column_name].astype("object")
                    frame.iat[normalized_start_row + row_offset, target_column] = normalized_value

            return (row_count, column_count)
        finally:
            self.endResetModel()
            self.history_changed.emit()

    def insert_columns(
        self,
        position: int,
        column_names: list[str],
        rows: list[list[str]],
        column_metadata: list[ColumnMetadata | dict[str, object] | None] | None = None,
    ) -> list[str]:
        """Insert pasted columns before the requested position and return final names."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")

        column_count = max(
            len(column_names),
            max((len(row) for row in rows), default=0),
        )
        if column_count == 0:
            return []

        insert_position = max(0, min(position, len(self._dataset.frame.columns)))

        self.capture_undo_state()
        self.beginResetModel()
        try:
            frame = self._dataset.frame
            target_row_count = max(len(frame), len(rows))
            if len(frame) < target_row_count:
                additional_rows = pd.DataFrame(
                    [[pd.NA] * len(frame.columns)] * (target_row_count - len(frame)),
                    columns=frame.columns,
                )
                self._dataset.frame = pd.concat(
                    [frame.reset_index(drop=True), additional_rows],
                    ignore_index=True,
                )
                frame = self._dataset.frame

            inserted_names: list[str] = []
            for column_offset in range(column_count):
                requested_name = (
                    str(column_names[column_offset]).strip()
                    if column_offset < len(column_names)
                    else ""
                )
                base_name = requested_name or f"Pasted Column {column_offset + 1}"
                column_name = self._make_unique_column_name(base_name)
                values = self._pasted_column_values(rows, column_offset, target_row_count)
                series = self._series_from_pasted_values(values)
                series.index = frame.index
                frame.insert(
                    insert_position + column_offset,
                    column_name,
                    series,
                )
                self._dataset.formulas.pop(column_name, None)
                metadata_entry = (
                    column_metadata[column_offset]
                    if column_metadata is not None and column_offset < len(column_metadata)
                    else None
                )
                if isinstance(metadata_entry, ColumnMetadata):
                    metadata = ColumnMetadata(
                        role=metadata_entry.role,
                        unit=metadata_entry.unit,
                        long_name=metadata_entry.long_name,
                        comment=metadata_entry.comment,
                    )
                else:
                    metadata = ColumnMetadata.from_metadata(metadata_entry)
                if metadata.is_empty():
                    self._dataset.column_metadata.pop(column_name, None)
                else:
                    self._dataset.column_metadata[column_name] = metadata
                inserted_names.append(column_name)

            return inserted_names
        finally:
            self.endResetModel()
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
            self._dataset.column_metadata.pop(column_name, None)
        self.endResetModel()
        self.history_changed.emit()
        return deleted_names

    def add_empty_column(self, column_name: str) -> str:
        """Add an empty column to the current dataset and return its final unique name."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")

        return self.insert_empty_column(len(self._dataset.frame.columns), column_name)

    def insert_empty_column(self, position: int, column_name: str) -> str:
        """Insert an empty column before the requested position and return its final name."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")

        clean_name = column_name.strip() or "New Column"
        unique_name = self._make_unique_column_name(clean_name)
        insert_position = max(0, min(position, len(self._dataset.frame.columns)))

        self.capture_undo_state()
        self.beginInsertColumns(QModelIndex(), insert_position, insert_position)
        self._dataset.frame.insert(insert_position, unique_name, pd.NA)
        self._dataset.formulas.pop(unique_name, None)
        self._dataset.column_metadata.pop(unique_name, None)
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

    def set_column_metadata(self, metadata: dict[str, ColumnMetadata]) -> None:
        """Replace metadata for the current dataset with undo/redo support."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")

        self.capture_undo_state()
        self._dataset.set_column_metadata(metadata)
        if self.columnCount() > 0:
            self.headerDataChanged.emit(Qt.Horizontal, 0, self.columnCount() - 1)
        self.history_changed.emit()

    def apply_column_metadata(
        self,
        column_names: list[str],
        metadata: dict[str, ColumnMetadata],
    ) -> list[tuple[str, str]]:
        """Rename columns and replace metadata with undo/redo support."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")

        if len(column_names) != len(self._dataset.frame.columns):
            raise ValueError("Column metadata edit does not match the current dataset shape.")

        clean_names = [str(name).strip() for name in column_names]
        if any(not name for name in clean_names):
            raise ValueError("Column names cannot be blank.")
        if len(set(clean_names)) != len(clean_names):
            raise ValueError("Column names must be unique.")

        old_names = [str(column) for column in self._dataset.frame.columns]
        rename_pairs = [
            (old_name, new_name)
            for old_name, new_name in zip(old_names, clean_names)
            if old_name != new_name
        ]

        self.capture_undo_state()
        self.beginResetModel()
        try:
            self._dataset.frame.columns = clean_names
            self._dataset.formulas = {
                new_name: self._dataset.formulas[old_name]
                for old_name, new_name in zip(old_names, clean_names)
                if old_name in self._dataset.formulas
            }
            self._dataset.set_column_metadata(metadata)
        finally:
            self.endResetModel()
            self.history_changed.emit()

        return rename_pairs

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

    def _pasted_column_values(
        self,
        rows: list[list[str]],
        column_offset: int,
        target_row_count: int,
    ) -> list[object]:
        """Return one pasted column padded to the dataset row count."""
        values: list[object] = []
        for row_index in range(target_row_count):
            if row_index < len(rows) and column_offset < len(rows[row_index]):
                values.append(rows[row_index][column_offset])
            else:
                values.append(pd.NA)
        return values

    def _series_from_pasted_values(self, values: list[object]) -> pd.Series:
        """Build a Series from clipboard text, preserving numeric columns when possible."""
        normalized_values: list[object] = []
        for value in values:
            if pd.isna(value):
                normalized_values.append(pd.NA)
                continue

            text = str(value).strip()
            normalized_values.append(pd.NA if text == "" else text)

        series = pd.Series(normalized_values, dtype="object")
        non_empty = series.dropna()
        if non_empty.empty:
            return series

        converted = pd.to_numeric(non_empty, errors="coerce")
        if not converted.isna().any():
            return pd.to_numeric(series, errors="coerce")
        return series

    def _snapshot(self) -> _DatasetSnapshot:
        """Return a deep copy of the current dataset edit state."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")
        return _DatasetSnapshot(
            frame=self._dataset.frame.copy(deep=True),
            formulas=dict(self._dataset.formulas),
            column_metadata=copy_column_metadata(self._dataset.column_metadata),
        )

    def _restore_snapshot(self, snapshot: _DatasetSnapshot) -> None:
        """Replace the current dataset contents with a stored snapshot."""
        if self._dataset is None:
            return
        old_columns = [str(column) for column in self._dataset.frame.columns]
        self.beginResetModel()
        self._dataset.frame = snapshot.frame.copy(deep=True)
        self._dataset.formulas = dict(snapshot.formulas)
        self._dataset.column_metadata = copy_column_metadata(snapshot.column_metadata)
        self.endResetModel()
        new_columns = [str(column) for column in self._dataset.frame.columns]
        if len(old_columns) == len(new_columns):
            rename_map = {
                old_name: new_name
                for old_name, new_name in zip(old_columns, new_columns)
                if old_name != new_name
            }
            if rename_map:
                self.columns_renamed.emit(rename_map)

    @staticmethod
    def _values_equal(left: object, right: object) -> bool:
        """Return whether two cell values should be treated as equivalent."""
        if pd.isna(left) and pd.isna(right):
            return True
        try:
            return bool(left == right)
        except TypeError:
            return False
