"""Spreadsheet-like manual data entry widget."""

from __future__ import annotations

import csv
from io import StringIO

import pandas as pd
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class DataTableWidget(QWidget):
    """A simple editable table that can emit its contents as a DataFrame."""

    dataset_submitted = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the manual-entry table, controls, and clipboard shortcuts."""
        super().__init__(parent)

        self._sheet_name = QLineEdit("Manual Sheet")
        self._sheet_name.setMinimumWidth(180)

        self._table = QTableWidget(25, 4)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setDefaultSectionSize(120)
        self._table.horizontalHeader().setMinimumSectionSize(80)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().sectionDoubleClicked.connect(self._rename_column)
        self._refresh_default_headers()
        self._install_clipboard_shortcuts()

        add_row_button = QPushButton("Add Row")
        add_row_button.clicked.connect(self._add_row)

        add_column_button = QPushButton("Add Column")
        add_column_button.clicked.connect(self._add_column)

        remove_row_button = QPushButton("Remove Row")
        remove_row_button.clicked.connect(self._remove_selected_rows)

        remove_column_button = QPushButton("Remove Column")
        remove_column_button.clicked.connect(self._remove_selected_columns)

        fill_range_button = QPushButton("Fill Range")
        fill_range_button.clicked.connect(self._fill_range)

        table_size_button = QPushButton("Table Size")
        table_size_button.clicked.connect(self._set_table_size)

        save_button = QPushButton("Save Sheet")
        save_button.clicked.connect(self._submit_dataset)

        controls = QVBoxLayout()
        sheet_row = QHBoxLayout()
        sheet_row.addWidget(QLabel("Sheet name"))
        sheet_row.addWidget(self._sheet_name, 1)
        controls.addLayout(sheet_row)
        controls.addWidget(save_button)
        controls.addLayout(self._button_row(add_row_button, remove_row_button))
        controls.addLayout(self._button_row(add_column_button, remove_column_button))
        controls.addLayout(self._button_row(fill_range_button, table_size_button))

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self._table)

    @staticmethod
    def _button_row(left_button: QPushButton, right_button: QPushButton) -> QHBoxLayout:
        """Return a two-button row with stable minimum button widths."""
        left_button.setMinimumWidth(118)
        right_button.setMinimumWidth(118)
        row = QHBoxLayout()
        row.addWidget(left_button)
        row.addWidget(right_button)
        return row

    def to_dataframe(self) -> pd.DataFrame:
        """Convert non-empty table rows into a DataFrame."""
        headers = self._column_names()
        rows: list[list[object | None]] = []

        for row_index in range(self._table.rowCount()):
            row_values: list[object | None] = []
            has_value = False

            for column_index in range(self._table.columnCount()):
                item = self._table.item(row_index, column_index)
                text = item.text().strip() if item else ""
                if text:
                    has_value = True
                    row_values.append(text)
                else:
                    row_values.append(None)

            if has_value:
                rows.append(row_values)

        frame = pd.DataFrame(rows, columns=headers)
        return self._coerce_numeric_columns(frame)

    def _install_clipboard_shortcuts(self) -> None:
        """Bind standard copy/paste shortcuts to spreadsheet-style handlers."""
        self._copy_shortcut = QShortcut(QKeySequence.Copy, self._table)
        self._copy_shortcut.activated.connect(self._copy_selection)

        self._paste_shortcut = QShortcut(QKeySequence.Paste, self._table)
        self._paste_shortcut.activated.connect(self._paste_clipboard)

    def _add_row(self) -> None:
        """Append one empty row to the manual-entry table."""
        self._table.insertRow(self._table.rowCount())

    def _add_column(self) -> None:
        """Append one empty column with a default header."""
        column_index = self._table.columnCount()
        self._table.insertColumn(column_index)
        self._table.setHorizontalHeaderItem(
            column_index,
            QTableWidgetItem(f"Column {column_index + 1}"),
        )

    def _remove_selected_rows(self) -> None:
        """Remove all rows touched by the current cell selection."""
        selected_rows = sorted(
            {index.row() for index in self._table.selectedIndexes()},
            reverse=True,
        )
        for row_index in selected_rows:
            self._table.removeRow(row_index)

    def _remove_selected_columns(self) -> None:
        """Remove all columns touched by the current cell selection."""
        selected_columns = sorted(
            {index.column() for index in self._table.selectedIndexes()},
            reverse=True,
        )
        for column_index in selected_columns:
            self._table.removeColumn(column_index)
        if self._table.columnCount() == 0:
            self._add_column()

    def _rename_column(self, column_index: int) -> None:
        """Prompt for a new header label after a header double-click."""
        current_name = self._table.horizontalHeaderItem(column_index).text()
        new_name, accepted = QInputDialog.getText(
            self,
            "Rename Column",
            "Column name",
            text=current_name,
        )
        if accepted and new_name.strip():
            self._table.setHorizontalHeaderItem(
                column_index,
                QTableWidgetItem(new_name.strip()),
            )

    def _fill_range(self) -> None:
        """Fill a column with an arithmetic sequence."""
        dialog = RangeFillDialog(
            column_names=self._column_names(),
            default_column=self._current_column_name(),
            default_start_row=self._default_fill_start_row(),
            default_count=self._default_fill_count(),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        try:
            target_column = self._find_or_create_column(dialog.target_column())
            start_row = dialog.start_row() - 1
            count = dialog.count()
            self._ensure_table_size(start_row + count, target_column + 1)
            start_value = dialog.start_value()
            step = dialog.step()
            for offset in range(count):
                value = start_value + offset * step
                self._table.setItem(
                    start_row + offset,
                    target_column,
                    QTableWidgetItem(f"{value:g}"),
                )
            self._table.setCurrentCell(start_row, target_column)
        except Exception as exc:
            QMessageBox.critical(self, "Fill Range Failed", str(exc))

    def _set_table_size(self) -> None:
        """Resize the manual-entry grid to explicit row and column counts."""
        dialog = TableSizeDialog(
            current_rows=self._table.rowCount(),
            current_columns=self._table.columnCount(),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        self._table.setRowCount(dialog.row_count())
        current_columns = self._table.columnCount()
        self._table.setColumnCount(dialog.column_count())
        for column_index in range(current_columns, self._table.columnCount()):
            self._table.setHorizontalHeaderItem(
                column_index,
                QTableWidgetItem(f"Column {column_index + 1}"),
            )
        self._refresh_missing_headers()

    def _submit_dataset(self) -> None:
        """Validate and emit the manual table as a workspace dataset."""
        frame = self.to_dataframe()
        if frame.empty:
            QMessageBox.warning(self, "Empty Sheet", "Enter at least one row before saving.")
            return

        self.dataset_submitted.emit(self._sheet_name.text().strip() or "Manual Sheet", frame)

    def _copy_selection(self) -> None:
        """Copy the selected rectangular cell area as tab-delimited text."""
        selected_indexes = self._table.selectedIndexes()
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

                item = self._table.item(row_index, column_index)
                row_values.append(item.text() if item else "")
            writer.writerow(row_values)

        QApplication.clipboard().setText(output.getvalue().rstrip("\n"))

    def _paste_clipboard(self) -> None:
        """Paste tab-delimited clipboard text starting at the active cell."""
        rows = self._parse_clipboard_text(QApplication.clipboard().text())
        if not rows:
            return

        start_row = self._table.currentRow()
        start_column = self._table.currentColumn()
        if start_row < 0:
            start_row = 0
        if start_column < 0:
            start_column = 0

        self._ensure_table_size(
            minimum_rows=start_row + len(rows),
            minimum_columns=start_column + max(len(row) for row in rows),
        )

        for row_offset, row_values in enumerate(rows):
            for column_offset, value in enumerate(row_values):
                self._table.setItem(
                    start_row + row_offset,
                    start_column + column_offset,
                    QTableWidgetItem(value),
                )

    def _parse_clipboard_text(self, text: str) -> list[list[str]]:
        """Parse clipboard text into rows and cells."""
        cleaned_text = text.rstrip("\r\n")
        if not cleaned_text:
            return []

        reader = csv.reader(StringIO(cleaned_text), delimiter="\t")
        return [row for row in reader]

    def _ensure_table_size(self, minimum_rows: int, minimum_columns: int) -> None:
        """Grow the table until it can contain the requested row/column count."""
        while self._table.rowCount() < minimum_rows:
            self._add_row()

        while self._table.columnCount() < minimum_columns:
            self._add_column()

    def _default_fill_count(self) -> int:
        """Return the default number of rows for range filling."""
        selected_rows = {index.row() for index in self._table.selectedIndexes()}
        if selected_rows:
            return len(selected_rows)
        return self._table.rowCount()

    def _default_fill_start_row(self) -> int:
        """Return the default one-based starting row for fill operations."""
        selected_rows = {index.row() for index in self._table.selectedIndexes()}
        if selected_rows:
            return min(selected_rows) + 1
        current_row = self._table.currentRow()
        return current_row + 1 if current_row >= 0 else 1

    def _current_column_name(self) -> str:
        """Return the current column header or a practical fallback name."""
        current_column = self._table.currentColumn()
        if current_column >= 0:
            item = self._table.horizontalHeaderItem(current_column)
            if item and item.text().strip():
                return item.text().strip()
        return self._column_names()[0] if self._table.columnCount() else "Column 1"

    def _find_or_create_column(self, column_name: str) -> int:
        """Return an existing column index or create a new named column."""
        clean_name = column_name.strip()
        if not clean_name:
            raise ValueError("Choose or enter a target column.")

        for column_index in range(self._table.columnCount()):
            item = self._table.horizontalHeaderItem(column_index)
            if item and item.text().strip() == clean_name:
                return column_index

        column_index = self._table.columnCount()
        self._table.insertColumn(column_index)
        self._table.setHorizontalHeaderItem(column_index, QTableWidgetItem(clean_name))
        return column_index

    def _refresh_default_headers(self) -> None:
        """Install default names for all current columns."""
        for column_index in range(self._table.columnCount()):
            self._table.setHorizontalHeaderItem(
                column_index,
                QTableWidgetItem(f"Column {column_index + 1}"),
            )

    def _refresh_missing_headers(self) -> None:
        """Install default names only for columns missing header items."""
        for column_index in range(self._table.columnCount()):
            if self._table.horizontalHeaderItem(column_index) is None:
                self._table.setHorizontalHeaderItem(
                    column_index,
                    QTableWidgetItem(f"Column {column_index + 1}"),
                )

    def _column_names(self) -> list[str]:
        """Return unique DataFrame column names derived from table headers."""
        names: list[str] = []
        used: set[str] = set()

        for column_index in range(self._table.columnCount()):
            item = self._table.horizontalHeaderItem(column_index)
            base_name = item.text().strip() if item and item.text().strip() else "Column"
            unique_name = base_name
            suffix = 2
            while unique_name in used:
                unique_name = f"{base_name} ({suffix})"
                suffix += 1
            used.add(unique_name)
            names.append(unique_name)

        return names

    def _coerce_numeric_columns(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Convert columns to numeric dtype when every non-empty value is numeric."""
        for column in frame.columns:
            non_empty = frame[column].dropna()
            if non_empty.empty:
                continue

            converted = pd.to_numeric(non_empty, errors="coerce")
            if not converted.isna().any():
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

        return frame


class RangeFillDialog(QDialog):
    """Dialog for filling a manual-entry column with an arithmetic sequence."""

    def __init__(
        self,
        column_names: list[str],
        default_column: str,
        default_start_row: int,
        default_count: int,
        parent: QWidget | None = None,
    ) -> None:
        """Create a range-fill dialog with sensible defaults."""
        super().__init__(parent)
        self.setWindowTitle("Fill Range")

        self._target_column = QComboBox()
        self._target_column.setEditable(True)
        self._target_column.addItems(column_names)
        self._target_column.setCurrentText(default_column or "x")

        self._start_row = QSpinBox()
        self._start_row.setRange(1, 1_000_000)
        self._start_row.setValue(max(default_start_row, 1))

        self._count = QSpinBox()
        self._count.setRange(1, 1_000_000)
        self._count.setValue(max(default_count, 1))

        self._start_value = QDoubleSpinBox()
        self._start_value.setRange(-1.0e12, 1.0e12)
        self._start_value.setDecimals(10)
        self._start_value.setValue(0.0)

        self._step = QDoubleSpinBox()
        self._step.setRange(-1.0e12, 1.0e12)
        self._step.setDecimals(10)
        self._step.setValue(1.0)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow("Target column", self._target_column)
        layout.addRow("Start row", self._start_row)
        layout.addRow("Rows", self._count)
        layout.addRow("Start value", self._start_value)
        layout.addRow("Step", self._step)
        layout.addRow(buttons)

    def target_column(self) -> str:
        """Return the selected or typed target column name."""
        return self._target_column.currentText().strip()

    def start_row(self) -> int:
        """Return the one-based first row to fill."""
        return self._start_row.value()

    def count(self) -> int:
        """Return how many rows should be filled."""
        return self._count.value()

    def start_value(self) -> float:
        """Return the first numeric value in the generated sequence."""
        return self._start_value.value()

    def step(self) -> float:
        """Return the numeric increment between generated values."""
        return self._step.value()


class TableSizeDialog(QDialog):
    """Dialog for resizing the manual-entry table."""

    def __init__(
        self,
        current_rows: int,
        current_columns: int,
        parent: QWidget | None = None,
    ) -> None:
        """Create a table-size dialog initialized from the current grid."""
        super().__init__(parent)
        self.setWindowTitle("Table Size")

        self._rows = QSpinBox()
        self._rows.setRange(1, 1_000_000)
        self._rows.setValue(max(current_rows, 1))

        self._columns = QSpinBox()
        self._columns.setRange(1, 10_000)
        self._columns.setValue(max(current_columns, 1))

        hint = QLabel("Reducing the table size removes cells outside the new row or column limits.")
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow("Rows", self._rows)
        layout.addRow("Columns", self._columns)
        layout.addRow(hint)
        layout.addRow(buttons)

    def row_count(self) -> int:
        """Return the requested row count."""
        return self._rows.value()

    def column_count(self) -> int:
        """Return the requested column count."""
        return self._columns.value()
