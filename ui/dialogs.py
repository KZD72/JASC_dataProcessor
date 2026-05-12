"""Application dialogs."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.file_io import ImportOptions


class ImportOptionsDialog(QDialog):
    """Collect delimiter and header settings before importing a text file."""

    _DELIMITERS: tuple[tuple[str, str], ...] = (
        ("Comma (,)", ","),
        ("Semicolon (;)", ";"),
        ("Tab", "\t"),
        ("Space / whitespace", " "),
    )

    def __init__(self, parent: object | None = None) -> None:
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


class ColumnExpressionDialog(QDialog):
    """Collect settings for applying a Python-like expression to a column."""

    def __init__(
        self,
        column_names: list[str],
        selected_rows_available: bool,
        default_target: str | None = None,
        column_formulas: dict[str, str] | None = None,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apply Formula")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._column_formulas = column_formulas or {}
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

        self._expression_edit = QPlainTextEdit()
        self._expression_edit.setFixedHeight(90)
        self._expression_edit.setPlaceholderText(
            'Examples: x + y, sin(x), sqrt(col("Voltage")), where(x > 0, x, 0)'
        )

        self._formula_hint = QLabel()
        self._formula_hint.setWordWrap(True)
        self._formula_hint.setTextFormat(Qt.RichText)

        self._cheatsheet = QLabel(self._build_cheatsheet(column_names))
        self._cheatsheet.setWordWrap(True)
        self._cheatsheet.setTextFormat(Qt.RichText)
        self._cheatsheet.setOpenExternalLinks(False)

        self._selected_rows_checkbox = QCheckBox("Apply only to selected rows")
        self._selected_rows_checkbox.setEnabled(selected_rows_available)
        self._selected_rows_checkbox.setChecked(selected_rows_available)

        form = QFormLayout()
        form.addRow("Target column", self._target_combo)
        form.addRow("Expression", self._expression_edit)
        form.addRow("", self._formula_hint)
        form.addRow("", self._selected_rows_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._cheatsheet)
        layout.addWidget(buttons)

        self._target_combo.currentTextChanged.connect(self._load_formula_for_target)
        self._load_formula_for_target(self._target_combo.currentText(), force=True)

    def target_column(self) -> str:
        """Return the selected or typed target column."""
        return self._target_combo.currentText().strip()

    def expression(self) -> str:
        """Return the expression text."""
        return self._expression_edit.toPlainText().strip()

    def apply_selected_rows_only(self) -> bool:
        """Return whether only selected rows should be updated."""
        return self._selected_rows_checkbox.isChecked()

    def _build_cheatsheet(self, column_names: list[str]) -> str:
        shown_columns = column_names[:8]
        column_examples = ", ".join(f'col("{escape(name)}")' for name in shown_columns)
        if len(column_names) > len(shown_columns):
            column_examples += ", ..."

        return (
            "<b>Formula cheatsheet</b><br>"
            "Use plain column names only when they are valid Python names, like "
            "<code>x</code>, <code>temperature</code>, or <code>Voltage_1</code>.<br>"
            'Use <code>col("exact column name")</code> for names with spaces, symbols, or default '
            'manual-entry names. Example: <code>col("Column 1") + col("Column 2")</code>.<br>'
            "Powers use <code>**</code>, so square a column with <code>x ** 2</code>. "
            "<code>^</code> is not exponentiation.<br>"
            "Common functions: <code>sin</code>, <code>cos</code>, <code>sqrt</code>, "
            "<code>log</code>, <code>abs</code>, <code>where</code>, <code>minimum</code>, "
            "<code>maximum</code>, <code>pi</code>, <code>np.pi</code>.<br>"
            "NumPy/SciPy examples: <code>np.gradient(x)</code>, "
            "<code>np.mean(x)</code>, <code>scipy.special.erf(x)</code>, "
            "<code>scipy.signal.savgol_filter(y, 11, 3)</code>, "
            "<code>stats.zscore(x)</code>. A safe math/signal/stat subset is exposed; "
            "file IO and arbitrary imports are blocked.<br>"
            "Formula-generated columns reload their stored expression when selected as the target.<br>"
            f"Available column reference style: <code>{column_examples}</code>"
        )

    def _load_formula_for_target(self, target_column: str, force: bool = False) -> None:
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
