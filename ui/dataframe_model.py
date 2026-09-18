"""Qt table model for editing pandas DataFrames in the workspace."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Number
from typing import Any

import pandas as pd
from pandas.api.types import is_numeric_dtype
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, Signal

from core.operations import ExpressionResult, apply_column_expression
from core.workspace import (
    COLUMN_NUMERIC_TYPES,
    ColumnMetadata,
    Dataset,
    column_type_label,
    column_role_label,
    copy_column_metadata,
    normalize_display_precision,
    set_column_operation_comment,
)


@dataclass(slots=True)
class _DatasetSnapshot:
    """Stored dataset state for undo/redo history."""

    frame: pd.DataFrame
    formulas: dict[str, str]
    column_metadata: dict[str, ColumnMetadata]


_INVALID_TYPED_VALUE = object()
_DEFAULT_MAX_HISTORY_ENTRIES = 20
_DEFAULT_MAX_HISTORY_BYTES = 256 * 1024 * 1024


class DataFrameTableModel(QAbstractTableModel):
    """Editable table model that writes changes directly into a workspace dataset."""

    history_changed = Signal()
    history_warning = Signal(str)
    columns_renamed = Signal(dict)
    edit_rejected = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Create an empty model until a workspace dataset is attached."""
        super().__init__(parent)
        self._dataset: Dataset | None = None
        self._undo_stack: list[_DatasetSnapshot] = []
        self._redo_stack: list[_DatasetSnapshot] = []
        self._max_history_entries = _DEFAULT_MAX_HISTORY_ENTRIES
        self._max_history_bytes = _DEFAULT_MAX_HISTORY_BYTES

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
        snapshot = self._snapshot_if_within_budget()
        if snapshot is None:
            self._undo_stack.clear()
            self.history_warning.emit(
                "This edit is larger than the "
                f"{self._max_history_bytes / (1024 * 1024):g} MiB undo budget and cannot be undone."
            )
        else:
            self._push_history(self._undo_stack, snapshot)
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
        current_snapshot = self._snapshot_if_within_budget()
        if current_snapshot is None:
            self._redo_stack.clear()
        else:
            self._push_history(self._redo_stack, current_snapshot)
        self._restore_snapshot(self._undo_stack.pop())
        self.history_changed.emit()
        return True

    def redo(self) -> bool:
        """Restore the next dataset state after an undo."""
        if self._dataset is None or not self._redo_stack:
            return False
        current_snapshot = self._snapshot_if_within_budget()
        if current_snapshot is None:
            self._undo_stack.clear()
        else:
            self._push_history(self._undo_stack, current_snapshot)
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
        if role == Qt.DisplayRole:
            column_name = str(self._dataset.frame.columns[index.column()])
            metadata = self._dataset.column_metadata.get(column_name)
            return self._format_display_value(value, metadata)
        return str(value)

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        """Write a user edit back into the backing DataFrame."""
        if not index.isValid() or self._dataset is None or role != Qt.EditRole:
            return False

        frame = self._dataset.frame
        column_name = frame.columns[index.column()]
        metadata = self._dataset.column_metadata.get(str(column_name))
        normalized_value = self._normalize_value(frame[column_name], value, metadata)
        if normalized_value is _INVALID_TYPED_VALUE:
            type_label = column_type_label(metadata.value_type) if metadata is not None else "Numeric"
            self.edit_rejected.emit(
                f"Column '{column_name}' is marked {type_label}; enter a numeric value "
                "or change the column metadata to Text."
            )
            return False
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
                if metadata.value_type:
                    lines.append(f"Type: {column_type_label(metadata.value_type)}")
                if metadata.display_precision is not None:
                    lines.append(f"Shown precision: {metadata.display_precision}")
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

    def clear_cells(self, ranges: list[tuple[int, int, int, int]]) -> int:
        """Clear values inside compact ``(top, left, bottom, right)`` ranges.

        The operation records one undo snapshot regardless of the number of cells
        and removes whole-column formula metadata for every touched column because
        the formula result is no longer intact after a partial value deletion.
        """
        if self._dataset is None:
            return 0

        frame = self._dataset.frame
        row_count = len(frame)
        column_count = len(frame.columns)
        selected_rows_by_column: dict[int, set[int]] = {}
        for top, left, bottom, right in ranges:
            bounded_top = max(0, min(int(top), row_count - 1))
            bounded_bottom = max(0, min(int(bottom), row_count - 1))
            bounded_left = max(0, min(int(left), column_count - 1))
            bounded_right = max(0, min(int(right), column_count - 1))
            if (
                row_count == 0
                or column_count == 0
                or bounded_top > bounded_bottom
                or bounded_left > bounded_right
            ):
                continue
            for column in range(bounded_left, bounded_right + 1):
                selected_rows_by_column.setdefault(column, set()).update(
                    range(bounded_top, bounded_bottom + 1)
                )

        if not selected_rows_by_column:
            return 0

        active_rows_by_column: dict[int, list[int]] = {}
        for column, rows in selected_rows_by_column.items():
            sorted_rows = sorted(rows)
            values = frame.iloc[sorted_rows, column]
            active_rows = [
                row
                for row, is_present in zip(sorted_rows, values.notna().tolist())
                if is_present
            ]
            if active_rows:
                active_rows_by_column[column] = active_rows
        changed_cells = sum(len(rows) for rows in active_rows_by_column.values())
        if changed_cells == 0:
            return 0

        self.capture_undo_state()
        for column, rows in active_rows_by_column.items():
            column_name = str(frame.columns[column])
            target = frame.iloc[:, column]
            if target.dtype.kind == "i":
                frame[column_name] = target.astype("Int64")
            elif target.dtype.kind == "u":
                frame[column_name] = target.astype("UInt64")
            elif target.dtype.kind == "b":
                frame[column_name] = target.astype("boolean")
            frame.iloc[rows, column] = pd.NA
            self._dataset.formulas.pop(column_name, None)
        self._dataset.frame = frame
        top = min(min(rows) for rows in active_rows_by_column.values())
        bottom = max(max(rows) for rows in active_rows_by_column.values())
        left = min(active_rows_by_column)
        right = max(active_rows_by_column)
        self.dataChanged.emit(
            self.index(top, left),
            self.index(bottom, right),
            [Qt.DisplayRole, Qt.EditRole],
        )
        self.history_changed.emit()
        return changed_cells

    def resize_sheet(self, row_count: int, column_count: int) -> tuple[int, int]:
        """Resize the worksheet to exact row and column counts in one undo step."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")
        if row_count < 1 or column_count < 1:
            raise ValueError("A worksheet must contain at least one row and one column.")

        frame = self._dataset.frame
        old_row_count, old_column_count = frame.shape
        if (row_count, column_count) == (old_row_count, old_column_count):
            return (old_row_count, old_column_count)

        self.capture_undo_state()
        self.beginResetModel()
        try:
            if row_count < old_row_count:
                frame = frame.iloc[:row_count, :].copy().reset_index(drop=True)
            elif row_count > old_row_count:
                frame = frame.reset_index(drop=True).reindex(range(row_count))

            if column_count < old_column_count:
                removed_names = [str(name) for name in frame.columns[column_count:]]
                frame = frame.iloc[:, :column_count].copy()
                for column_name in removed_names:
                    self._dataset.formulas.pop(column_name, None)
                    self._dataset.column_metadata.pop(column_name, None)
            elif column_count > old_column_count:
                new_names = self._new_column_names(column_count - old_column_count)
                new_columns = pd.DataFrame(
                    {
                        column_name: pd.Series(pd.NA, index=frame.index, dtype="object")
                        for column_name in new_names
                    },
                    index=frame.index,
                )
                frame = pd.concat([frame, new_columns], axis=1)

            self._dataset.frame = frame
            self._dataset.sync_column_metadata_attrs()
        finally:
            self.endResetModel()
            self.history_changed.emit()
        return (row_count, column_count)

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

    def paste_block(
        self,
        start_row: int,
        start_column: int,
        rows: pd.DataFrame | list[list[object]],
    ) -> tuple[int, int]:
        """Paste a rectangular text block into the dataset, growing rows/columns as needed."""
        if self._dataset is None:
            return (0, 0)

        block = self._coerce_paste_block(rows)
        if block.empty and len(block.columns) == 0:
            return (0, 0)
        normalized_start_row = max(start_row, 0)
        normalized_start_column = max(start_column, 0)
        row_count, column_count = block.shape
        if column_count == 0:
            return (0, 0)

        self.beginResetModel()
        try:
            frame = self._dataset.frame
            target_rows = normalized_start_row + row_count
            target_columns = normalized_start_column + column_count

            missing_column_count = max(0, target_columns - len(frame.columns))
            if missing_column_count:
                new_column_names = self._new_column_names(missing_column_count)
                new_columns = pd.DataFrame(
                    {
                        column_name: pd.Series(pd.NA, index=frame.index, dtype="object")
                        for column_name in new_column_names
                    },
                    index=frame.index,
                )
                frame = pd.concat([frame, new_columns], axis=1)

            if len(frame) < target_rows or not isinstance(frame.index, pd.RangeIndex):
                frame = frame.reset_index(drop=True).reindex(range(max(len(frame), target_rows)))

            normalized_columns: list[pd.Series] = []
            touched_column_names: list[str] = []
            for column_offset in range(column_count):
                target_column = normalized_start_column + column_offset
                column_name = str(frame.columns[target_column])
                metadata = self._dataset.column_metadata.get(column_name)
                normalized_columns.append(
                    self._normalize_pasted_series(
                        frame.iloc[:, target_column],
                        block.iloc[:, column_offset],
                        metadata,
                    )
                )
                touched_column_names.append(column_name)

            self.capture_undo_state()
            row_slice = slice(normalized_start_row, normalized_start_row + row_count)
            for column_offset, normalized_values in enumerate(normalized_columns):
                target_column = normalized_start_column + column_offset
                column_name = touched_column_names[column_offset]
                target_series = frame.iloc[:, target_column]
                if is_numeric_dtype(target_series) and not is_numeric_dtype(normalized_values):
                    frame[column_name] = target_series.astype("object")
                elif (
                    is_numeric_dtype(target_series)
                    and target_series.dtype.kind in "iu"
                    and normalized_values.isna().any()
                ):
                    frame[column_name] = target_series.astype("float64")

                frame.iloc[row_slice, target_column] = normalized_values.to_numpy()
                self._dataset.formulas.pop(column_name, None)

            for column_name in frame.columns[len(self._dataset.frame.columns):]:
                self._dataset.formulas.pop(str(column_name), None)
                self._dataset.column_metadata.pop(str(column_name), None)
            self._dataset.frame = frame
            return (row_count, column_count)
        finally:
            self.endResetModel()
            self.history_changed.emit()

    def insert_columns(
        self,
        position: int,
        column_names: list[str],
        rows: pd.DataFrame | list[list[object]],
        column_metadata: list[ColumnMetadata | dict[str, object] | None] | None = None,
    ) -> list[str]:
        """Insert pasted columns before the requested position and return final names."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")

        block = self._coerce_paste_block(rows)
        column_count = max(len(column_names), len(block.columns))
        if column_count == 0:
            return []

        insert_position = max(0, min(position, len(self._dataset.frame.columns)))

        self.capture_undo_state()
        self.beginResetModel()
        try:
            frame = self._dataset.frame
            target_row_count = max(len(frame), len(block))
            if len(frame) < target_row_count:
                frame = frame.reset_index(drop=True).reindex(range(target_row_count))

            inserted_names: list[str] = []
            for column_offset in range(column_count):
                requested_name = (
                    str(column_names[column_offset]).strip()
                    if column_offset < len(column_names)
                    else ""
                )
                base_name = requested_name or f"Pasted Column {column_offset + 1}"
                column_name = self._make_unique_column_name(base_name)
                values = (
                    block.iloc[:, column_offset].reindex(range(target_row_count))
                    if column_offset < len(block.columns)
                    else pd.Series(pd.NA, index=range(target_row_count), dtype="object")
                )
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
                        value_type=metadata_entry.value_type,
                        display_precision=metadata_entry.display_precision,
                    )
                else:
                    metadata = ColumnMetadata.from_metadata(metadata_entry)
                if metadata.is_empty():
                    self._dataset.column_metadata.pop(column_name, None)
                else:
                    self._dataset.column_metadata[column_name] = metadata
                inserted_names.append(column_name)

            self._dataset.frame = frame
            self._dataset.sync_column_metadata_attrs()
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

    def fill_range(
        self,
        target_column: str,
        start_row: int,
        count: int,
        start_value: float,
        step: float,
    ) -> str:
        """Fill or create a column with an arithmetic sequence."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")
        if count <= 0:
            raise ValueError("Range fill requires at least one row.")

        clean_name = target_column.strip() or "x"
        start_index = max(0, start_row - 1)
        end_index = start_index + count

        self.capture_undo_state()
        self.beginResetModel()
        try:
            frame = self._dataset.frame
            if clean_name in frame.columns:
                column_name = clean_name
            else:
                column_name = self._make_unique_column_name(clean_name)
                frame[column_name] = pd.Series(
                    [float("nan")] * len(frame),
                    index=frame.index,
                    dtype="float64",
                )
                self._dataset.formulas.pop(column_name, None)
                self._dataset.column_metadata.pop(column_name, None)

            if len(frame) < end_index:
                frame = frame.reset_index(drop=True).reindex(range(end_index))

            if is_numeric_dtype(frame[column_name]):
                frame[column_name] = pd.to_numeric(
                    frame[column_name],
                    errors="coerce",
                ).astype("float64")

            values = pd.Series(range(count), dtype="float64").mul(step).add(start_value)
            column_position = list(frame.columns).index(column_name)
            frame.iloc[start_index:end_index, column_position] = values.to_numpy()
            self._dataset.frame = frame
            self._dataset.formulas.pop(column_name, None)
            set_column_operation_comment(
                self._dataset,
                str(column_name),
                f"Range fill: start={start_value:g}, step={step:g}, rows={start_row}-{end_index}",
            )
            return str(column_name)
        finally:
            self.endResetModel()
            self.history_changed.emit()

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
            set_column_operation_comment(
                self._dataset,
                result.target_column,
                f"Formula = {expression.strip()}",
            )
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

    def _normalize_value(
        self,
        column: pd.Series,
        value: Any,
        metadata: ColumnMetadata | None = None,
    ) -> object:
        """Coerce edited text to a numeric value when the column supports it."""
        text = str(value).strip()
        if text == "":
            return pd.NA

        value_type = metadata.value_type if metadata is not None else ""
        if value_type == "text":
            return text
        if value_type in COLUMN_NUMERIC_TYPES:
            numeric_value = pd.to_numeric(text, errors="coerce")
            if not pd.isna(numeric_value):
                return numeric_value
            return _INVALID_TYPED_VALUE

        if is_numeric_dtype(column):
            numeric_value = pd.to_numeric(text, errors="coerce")
            if not pd.isna(numeric_value):
                return numeric_value

        return text

    @staticmethod
    def _format_display_value(value: object, metadata: ColumnMetadata | None) -> str:
        """Format one display value using explicit column metadata."""
        if metadata is None or metadata.value_type not in COLUMN_NUMERIC_TYPES:
            return str(value)

        numeric_value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        if pd.isna(numeric_value):
            return str(value)

        precision = normalize_display_precision(metadata.display_precision)
        if metadata.value_type == "scientific":
            digits = 6 if precision is None else precision
            return f"{float(numeric_value):.{digits}e}"
        if precision is not None:
            return f"{float(numeric_value):.{precision}f}"
        return f"{float(numeric_value):g}"

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

    def _series_from_pasted_values(self, values: pd.Series | list[object]) -> pd.Series:
        """Build a Series from clipboard text, preserving numeric columns when possible."""
        series = pd.Series(values, dtype="object").astype("string").str.strip()
        series = series.mask(series.eq(""), pd.NA)
        non_empty = series.dropna()
        if non_empty.empty:
            return series.astype("object")

        converted = pd.to_numeric(non_empty, errors="coerce")
        if not converted.isna().any():
            return pd.to_numeric(series, errors="coerce")
        return series.astype("object")

    @staticmethod
    def _coerce_paste_block(rows: pd.DataFrame | list[list[object]]) -> pd.DataFrame:
        """Return clipboard values as a reset-index rectangular DataFrame."""
        if isinstance(rows, pd.DataFrame):
            return rows.reset_index(drop=True)
        if not rows:
            return pd.DataFrame()
        column_count = max((len(row) for row in rows), default=0)
        padded_rows = [list(row) + [""] * (column_count - len(row)) for row in rows]
        return pd.DataFrame(padded_rows, dtype="object")

    @staticmethod
    def _normalize_pasted_series(
        target: pd.Series,
        source: pd.Series,
        metadata: ColumnMetadata | None,
    ) -> pd.Series:
        """Normalize one pasted column in bulk for its worksheet destination."""
        text = source.astype("string").str.strip()
        blank = text.isna() | text.eq("")
        value_type = metadata.value_type if metadata is not None else ""

        if value_type == "text" or (not value_type and not is_numeric_dtype(target)):
            return text.mask(blank, pd.NA).astype("object")

        numeric = pd.to_numeric(text.mask(blank), errors="coerce")
        invalid = ~blank & numeric.isna()
        if value_type in COLUMN_NUMERIC_TYPES and invalid.any():
            bad_value = str(text.loc[invalid].iloc[0])
            raise ValueError(
                f"Column '{target.name}' is marked {column_type_label(value_type)}; "
                f"clipboard value '{bad_value}' is not numeric."
            )
        if invalid.any():
            mixed = numeric.astype("object")
            mixed.loc[invalid] = text.loc[invalid]
            mixed.loc[blank] = pd.NA
            return mixed
        return numeric

    def _new_column_names(self, count: int) -> list[str]:
        """Return unique default names for columns appended by a pasted block."""
        if self._dataset is None:
            return []
        used = {str(column) for column in self._dataset.frame.columns}
        names: list[str] = []
        for offset in range(count):
            base_name = f"Column {len(used) + 1}"
            candidate = base_name
            suffix = 2
            while candidate in used:
                candidate = f"{base_name} ({suffix})"
                suffix += 1
            names.append(candidate)
            used.add(candidate)
        return names

    def _snapshot(self) -> _DatasetSnapshot:
        """Return a deep copy of the current dataset edit state."""
        if self._dataset is None:
            raise ValueError("No dataset is selected.")
        return _DatasetSnapshot(
            frame=self._dataset.frame.copy(deep=True),
            formulas=dict(self._dataset.formulas),
            column_metadata=copy_column_metadata(self._dataset.column_metadata),
        )

    def _snapshot_if_within_budget(self) -> _DatasetSnapshot | None:
        """Copy the current edit state only when one snapshot fits the budget."""
        if self._dataset is None:
            return None
        estimated_bytes = self._frame_memory_bytes(self._dataset.frame)
        estimated_bytes += len(self._dataset.formulas) * 256
        estimated_bytes += len(self._dataset.column_metadata) * 512
        if estimated_bytes > self._max_history_bytes:
            return None
        return self._snapshot()

    def _push_history(
        self,
        stack: list[_DatasetSnapshot],
        snapshot: _DatasetSnapshot,
    ) -> bool:
        """Push a snapshot while enforcing entry-count and memory budgets."""
        snapshot_bytes = self._snapshot_memory_bytes(snapshot)
        if snapshot_bytes > self._max_history_bytes:
            stack.clear()
            return False

        stack.append(snapshot)
        while len(stack) > self._max_history_entries:
            stack.pop(0)
        while len(stack) > 1 and self._history_memory_bytes(stack) > self._max_history_bytes:
            stack.pop(0)
        return True

    @staticmethod
    def _snapshot_memory_bytes(snapshot: _DatasetSnapshot) -> int:
        """Return a conservative buffer-size estimate for one history snapshot."""
        frame_bytes = DataFrameTableModel._frame_memory_bytes(snapshot.frame)
        metadata_bytes = len(snapshot.formulas) * 256 + len(snapshot.column_metadata) * 512
        return frame_bytes + metadata_bytes

    @staticmethod
    def _frame_memory_bytes(frame: pd.DataFrame) -> int:
        """Return the estimated copied buffer size for one DataFrame."""
        try:
            return int(frame.memory_usage(index=True, deep=False).sum())
        except Exception:
            return 0

    def _history_memory_bytes(self, stack: list[_DatasetSnapshot]) -> int:
        """Return the estimated memory retained by a history stack."""
        return sum(self._snapshot_memory_bytes(snapshot) for snapshot in stack)

    def _restore_snapshot(self, snapshot: _DatasetSnapshot) -> None:
        """Replace the current dataset contents with a stored snapshot."""
        if self._dataset is None:
            return
        old_columns = [str(column) for column in self._dataset.frame.columns]
        self.beginResetModel()
        self._dataset.frame = snapshot.frame.copy(deep=True)
        self._dataset.formulas = dict(snapshot.formulas)
        self._dataset.column_metadata = copy_column_metadata(snapshot.column_metadata)
        self._dataset.sync_column_metadata_attrs()
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
