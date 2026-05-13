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
    QGridLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
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
        super().__init__(parent)

        self._sheet_name = QLineEdit("Manual Sheet")
        self._sheet_name.setMinimumWidth(180)

        self._table = QTableWidget(25, 4)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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

        save_button = QPushButton("Save Sheet")
        save_button.clicked.connect(self._submit_dataset)

        controls = QGridLayout()
        controls.addWidget(QLabel("Sheet name"), 0, 0)
        controls.addWidget(self._sheet_name, 0, 1, 1, 3)
        controls.addWidget(save_button, 0, 4)
        controls.addWidget(add_row_button, 1, 0)
        controls.addWidget(add_column_button, 1, 1)
        controls.addWidget(remove_row_button, 1, 2)
        controls.addWidget(remove_column_button, 1, 3)
        controls.setColumnStretch(1, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self._table)

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
        self._copy_shortcut = QShortcut(QKeySequence.Copy, self._table)
        self._copy_shortcut.activated.connect(self._copy_selection)

        self._paste_shortcut = QShortcut(QKeySequence.Paste, self._table)
        self._paste_shortcut.activated.connect(self._paste_clipboard)

    def _add_row(self) -> None:
        self._table.insertRow(self._table.rowCount())

    def _add_column(self) -> None:
        column_index = self._table.columnCount()
        self._table.insertColumn(column_index)
        self._table.setHorizontalHeaderItem(
            column_index,
            QTableWidgetItem(f"Column {column_index + 1}"),
        )

    def _remove_selected_rows(self) -> None:
        selected_rows = sorted(
            {index.row() for index in self._table.selectedIndexes()},
            reverse=True,
        )
        for row_index in selected_rows:
            self._table.removeRow(row_index)

    def _remove_selected_columns(self) -> None:
        selected_columns = sorted(
            {index.column() for index in self._table.selectedIndexes()},
            reverse=True,
        )
        for column_index in selected_columns:
            self._table.removeColumn(column_index)
        if self._table.columnCount() == 0:
            self._add_column()

    def _rename_column(self, column_index: int) -> None:
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

    def _submit_dataset(self) -> None:
        frame = self.to_dataframe()
        if frame.empty:
            QMessageBox.warning(self, "Empty Sheet", "Enter at least one row before saving.")
            return

        self.dataset_submitted.emit(self._sheet_name.text().strip() or "Manual Sheet", frame)

    def _copy_selection(self) -> None:
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
        cleaned_text = text.rstrip("\r\n")
        if not cleaned_text:
            return []

        reader = csv.reader(StringIO(cleaned_text), delimiter="\t")
        return [row for row in reader]

    def _ensure_table_size(self, minimum_rows: int, minimum_columns: int) -> None:
        while self._table.rowCount() < minimum_rows:
            self._add_row()

        while self._table.columnCount() < minimum_columns:
            self._add_column()

    def _refresh_default_headers(self) -> None:
        for column_index in range(self._table.columnCount()):
            self._table.setHorizontalHeaderItem(
                column_index,
                QTableWidgetItem(f"Column {column_index + 1}"),
            )

    def _column_names(self) -> list[str]:
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
        for column in frame.columns:
            non_empty = frame[column].dropna()
            if non_empty.empty:
                continue

            converted = pd.to_numeric(non_empty, errors="coerce")
            if not converted.isna().any():
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

        return frame
