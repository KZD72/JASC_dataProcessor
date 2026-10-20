"""Spreadsheet-like manual data entry widget."""

from __future__ import annotations

import csv
from html import escape
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
    QPlainTextEdit,
    QSpinBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.clipboard_io import parse_tabular_clipboard
from core.smart_fill import (
    SMART_FILL_MODE_AUTO,
    SMART_FILL_MODE_CATEGORY,
    SMART_FILL_MODE_CUSTOM,
    SMART_FILL_MODE_DATETIME,
    SMART_FILL_MODE_NUMERIC,
    normalize_custom_list,
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
        if rows.empty and len(rows.columns) == 0:
            return

        start_row = self._table.currentRow()
        start_column = self._table.currentColumn()
        if start_row < 0:
            start_row = 0
        if start_column < 0:
            start_column = 0

        self._ensure_table_size(
            minimum_rows=start_row + len(rows),
            minimum_columns=start_column + len(rows.columns),
        )

        self._table.setUpdatesEnabled(False)
        try:
            for row_offset in range(len(rows)):
                for column_offset in range(len(rows.columns)):
                    value = rows.iat[row_offset, column_offset]
                    self._table.setItem(
                        start_row + row_offset,
                        start_column + column_offset,
                        QTableWidgetItem("" if pd.isna(value) else str(value)),
                    )
        finally:
            self._table.setUpdatesEnabled(True)

    def _parse_clipboard_text(self, text: str) -> pd.DataFrame:
        """Parse clipboard text into rows and cells."""
        return parse_tabular_clipboard(text, preserve_all_text=True)

    def _ensure_table_size(self, minimum_rows: int, minimum_columns: int) -> None:
        """Grow the table until it can contain the requested row/column count."""
        if self._table.rowCount() < minimum_rows:
            self._table.setRowCount(minimum_rows)
        if self._table.columnCount() < minimum_columns:
            self._table.setColumnCount(minimum_columns)
            self._refresh_missing_headers()

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
    """Dialog for explicitly creating or updating a numeric column fill."""

    def __init__(
        self,
        column_names: list[str],
        default_column: str,
        default_start_row: int,
        default_count: int,
        default_target_mode: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Create a range-fill dialog with sensible defaults."""
        super().__init__(parent)
        self.setWindowTitle("Fill Range")
        self.setMinimumWidth(500)
        self._column_names = list(column_names)

        self._target_mode = QComboBox()
        self._target_mode.addItem("Update an existing column", "existing")
        self._target_mode.addItem("Create a new column", "new")

        self._existing_target = QComboBox()
        self._existing_target.addItems(column_names)
        if default_column in column_names:
            self._existing_target.setCurrentText(default_column)

        self._new_target = QLineEdit(self._suggest_new_column_name("New Column"))
        if default_column and default_column not in column_names:
            self._new_target.setText(default_column)

        target_mode = default_target_mode
        if target_mode not in {"existing", "new"}:
            target_mode = "existing" if default_column in column_names else "new"
        target_mode_index = self._target_mode.findData(target_mode)
        self._target_mode.setCurrentIndex(max(0, target_mode_index))

        self._fill_pattern = QComboBox()
        self._fill_pattern.addItem("Arithmetic sequence", "sequence")
        self._fill_pattern.addItem("Constant value", "constant")

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

        self._summary = QLabel()
        self._summary.setWordWrap(True)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow("Target action", self._target_mode)
        self._existing_target_label = QLabel("Existing column")
        layout.addRow(self._existing_target_label, self._existing_target)
        self._new_target_label = QLabel("New column name")
        layout.addRow(self._new_target_label, self._new_target)
        layout.addRow("Fill pattern", self._fill_pattern)
        layout.addRow("Start row", self._start_row)
        layout.addRow("Rows", self._count)
        layout.addRow("Start value", self._start_value)
        self._step_label = QLabel("Step")
        layout.addRow(self._step_label, self._step)
        layout.addRow("Result", self._summary)
        layout.addRow(self._buttons)

        self._target_mode.currentIndexChanged.connect(self._sync_controls)
        self._fill_pattern.currentIndexChanged.connect(self._sync_controls)
        self._existing_target.currentTextChanged.connect(self._update_summary)
        self._new_target.textChanged.connect(self._update_summary)
        self._start_row.valueChanged.connect(self._update_summary)
        self._count.valueChanged.connect(self._update_summary)
        self._start_value.valueChanged.connect(self._update_summary)
        self._step.valueChanged.connect(self._update_summary)
        self._sync_controls()

    def _suggest_new_column_name(self, base_name: str) -> str:
        """Return a non-conflicting default name without mutating the worksheet."""
        if base_name not in self._column_names:
            return base_name
        suffix = 2
        while f"{base_name} {suffix}" in self._column_names:
            suffix += 1
        return f"{base_name} {suffix}"

    def _sync_controls(self) -> None:
        """Keep target and pattern controls consistent with the explicit choices."""
        use_existing = self.target_mode() == "existing"
        self._existing_target_label.setEnabled(use_existing)
        self._existing_target.setEnabled(use_existing)
        self._new_target_label.setEnabled(not use_existing)
        self._new_target.setEnabled(not use_existing)

        use_step = self.fill_pattern() == "sequence"
        self._step_label.setEnabled(use_step)
        self._step.setEnabled(use_step)
        self._update_summary()

    def _update_summary(self) -> None:
        """Describe the exact write before the dialog is accepted."""
        target = self.target_column() or "(unnamed)"
        first_row = self.start_row()
        last_row = first_row + self.count() - 1
        action = "replace values in" if self.target_mode() == "existing" else "create"
        if self.fill_pattern() == "constant":
            values = f"the constant value {self.start_value():g}"
        else:
            final_value = self.start_value() + (self.count() - 1) * self.step()
            values = (
                f"a sequence from {self.start_value():g} to {final_value:g} "
                f"(step {self.step():g})"
            )
        self._summary.setText(
            f"This will {action} <b>{escape(target)}</b>, rows {first_row}-{last_row}, "
            f"using {values}."
        )
        ok_button = self._buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            label = "Update Column" if self.target_mode() == "existing" else "Create Column"
            ok_button.setText(label)

    def target_mode(self) -> str:
        """Return ``existing`` or ``new`` for the requested write."""
        return str(self._target_mode.currentData() or "existing")

    def fill_pattern(self) -> str:
        """Return ``sequence`` or ``constant`` for the generated values."""
        return str(self._fill_pattern.currentData() or "sequence")

    def target_column(self) -> str:
        """Return the selected existing column or requested new column name."""
        if self.target_mode() == "existing":
            return self._existing_target.currentText().strip()
        return self._new_target.text().strip()

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
        if self.fill_pattern() == "constant":
            return 0.0
        return self._step.value()

    def accept(self) -> None:
        """Reject ambiguous target choices before any worksheet is modified."""
        target = self.target_column()
        if not target:
            QMessageBox.warning(self, "Fill Range", "Choose a target column.")
            return
        if self.target_mode() == "existing" and target not in self._column_names:
            QMessageBox.warning(self, "Fill Range", "Choose an existing column to update.")
            return
        if self.target_mode() == "new" and target in self._column_names:
            QMessageBox.warning(
                self,
                "Fill Range",
                "That column already exists. Choose 'Update an existing column' or enter a new name.",
            )
            return
        super().accept()


class SmartFillDialog(QDialog):
    """Choose how blank cells should be inferred from selected seed values."""

    def __init__(
        self,
        selection_description: str,
        parent: QWidget | None = None,
    ) -> None:
        """Create the smart-fill options dialog for one rectangular selection."""
        super().__init__(parent)
        self.setWindowTitle("Smart Fill Selection")
        self.setMinimumWidth(500)

        selection_label = QLabel(selection_description)
        selection_label.setWordWrap(True)

        self._mode = QComboBox()
        self._mode.addItem("Auto", SMART_FILL_MODE_AUTO)
        self._mode.addItem("Numeric", SMART_FILL_MODE_NUMERIC)
        self._mode.addItem("Date-Time", SMART_FILL_MODE_DATETIME)
        self._mode.addItem("Category Cycle", SMART_FILL_MODE_CATEGORY)
        self._mode.addItem("Custom List", SMART_FILL_MODE_CUSTOM)

        self._pattern = QComboBox()
        self._pattern.addItem("Auto detect", 0)
        self._pattern.addItem("One linear sequence", 1)
        for period in range(2, 9):
            self._pattern.addItem(f"{period} interleaved sequences", period)

        self._custom_list = QPlainTextEdit()
        self._custom_list.setPlaceholderText(
            "One item per line, for example:\nMonday\nTuesday\nWednesday"
        )
        self._custom_list.setFixedHeight(115)

        self._hint = QLabel()
        self._hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow("Selection", selection_label)
        layout.addRow("Mode", self._mode)
        self._pattern_label = QLabel("Numeric pattern")
        layout.addRow(self._pattern_label, self._pattern)
        self._custom_list_label = QLabel("Custom list")
        layout.addRow(self._custom_list_label, self._custom_list)
        layout.addRow(self._hint)
        layout.addRow(buttons)
        self._mode.currentIndexChanged.connect(self._sync_mode_controls)
        self._sync_mode_controls()

    def _sync_mode_controls(self) -> None:
        """Show only the controls and explanation relevant to the selected mode."""
        mode = self.mode()
        numeric_controls = mode in {SMART_FILL_MODE_AUTO, SMART_FILL_MODE_NUMERIC}
        custom_controls = mode == SMART_FILL_MODE_CUSTOM
        self._pattern_label.setVisible(numeric_controls)
        self._pattern.setVisible(numeric_controls)
        self._custom_list_label.setVisible(custom_controls)
        self._custom_list.setVisible(custom_controls)

        hints = {
            SMART_FILL_MODE_AUTO: (
                "Auto chooses Numeric for finite numbers, Date-Time for recognizable date "
                "values, and Category Cycle otherwise. Existing cells are anchors and only "
                "blank selected cells are written. One numeric anchor repeats because at least "
                "two anchors are needed to infer an increment."
            ),
            SMART_FILL_MODE_NUMERIC: (
                "Important: one numeric anchor is treated as a constant and repeats; it cannot "
                "define an increment. Two or more anchors define a row-position linear sequence. "
                "Auto pattern can detect consecutive interleaved numeric seeds "
                "such as 1, 10, 2, 20."
            ),
            SMART_FILL_MODE_DATETIME: (
                "Date-Time infers the field order of numeric dates (including any ordering "
                "of day, month, and year) and keeps it in filled cells. Exact month/month-end "
                "steps are preserved; other values use a fixed elapsed-time interval."
            ),
            SMART_FILL_MODE_CATEGORY: (
                "Enter one complete category cycle in consecutive cells, such as Red, Blue, "
                "Green. Smart Fill repeats that cycle into selected blanks."
            ),
            SMART_FILL_MODE_CUSTOM: (
                "Enter the ordered list once, one item per line. Existing anchors align the "
                "list; a completely blank selection starts from its first item."
            ),
        }
        self._hint.setText(hints[mode])

    def mode(self) -> str:
        """Return the requested inference mode."""
        return str(self._mode.currentData())

    def period(self) -> int:
        """Return zero for automatic detection or the requested pattern period."""
        return int(self._pattern.currentData())

    def custom_values(self) -> tuple[str, ...]:
        """Return nonblank custom-list entries in their entered order."""
        return normalize_custom_list(self._custom_list.toPlainText().splitlines())

    def accept(self) -> None:
        """Require a nonempty ordered list when Custom List mode is selected."""
        if self.mode() == SMART_FILL_MODE_CUSTOM and not self.custom_values():
            QMessageBox.warning(
                self,
                "Custom List Required",
                "Enter at least one custom-list item, one item per line.",
            )
            return
        super().accept()


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
