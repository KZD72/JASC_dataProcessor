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
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from core.file_io import ImportOptions
from math_engine.curve_fitting import FIT_METHODS
from math_engine.calculus import DERIVATIVE_METHODS, INTEGRATION_METHODS, WINDOW_METHODS
from models.fit_functions import available_fit_models, get_fit_model


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


class ColumnMathDialog(QDialog):
    """Collect settings for derivative or integral column operations."""

    def __init__(
        self,
        operation_name: str,
        column_names: list[str],
        methods: dict[str, str],
        default_target: str,
        include_initial_value: bool = False,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(operation_name)
        self.setModal(True)
        self.setMinimumWidth(420)

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItems(column_names)

        self._y_column_combo = QComboBox()
        self._y_column_combo.addItems(column_names)
        if len(column_names) > 1:
            self._y_column_combo.setCurrentIndex(1)

        self._method_combo = QComboBox()
        for method_key, method_label in methods.items():
            self._method_combo.addItem(method_label, method_key)

        self._target_edit = QLineEdit(default_target)
        self._initial_value_edit = QLineEdit("0")
        self._include_initial_value = include_initial_value

        form = QFormLayout()
        form.addRow("X column", self._x_column_combo)
        form.addRow("Y column", self._y_column_combo)
        form.addRow("Method", self._method_combo)
        if self._include_initial_value:
            form.addRow("Initial value", self._initial_value_edit)
        form.addRow("Target column", self._target_edit)

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
        """Return selected Y column."""
        return self._y_column_combo.currentText()

    def method(self) -> str:
        """Return selected method key."""
        return str(self._method_combo.currentData())

    def target_column(self) -> str:
        """Return target column name."""
        return self._target_edit.text().strip()

    def initial_value_text(self) -> str:
        """Return the raw initial value text for operations that need it."""
        return self._initial_value_edit.text().strip()


class FFTDialog(QDialog):
    """Collect settings for FFT operations."""

    def __init__(self, column_names: list[str], default_dataset_name: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FFT")
        self.setModal(True)
        self.setMinimumWidth(420)

        self._signal_column_combo = QComboBox()
        self._signal_column_combo.addItems(column_names)
        if len(column_names) > 1:
            self._signal_column_combo.setCurrentIndex(1)

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItem("Sample index", None)
        for column_name in column_names:
            self._x_column_combo.addItem(column_name, column_name)

        self._window_combo = QComboBox()
        for window_key, window_label in WINDOW_METHODS.items():
            self._window_combo.addItem(window_label, window_key)

        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_FFT")

        form = QFormLayout()
        form.addRow("Signal column", self._signal_column_combo)
        form.addRow("X/time column", self._x_column_combo)
        form.addRow("Window", self._window_combo)
        form.addRow("Result sheet", self._target_dataset_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def signal_column(self) -> str:
        """Return selected signal column."""
        return self._signal_column_combo.currentText()

    def x_column(self) -> str | None:
        """Return selected X/time column, or None for sample index spacing."""
        value = self._x_column_combo.currentData()
        return str(value) if value else None

    def window_method(self) -> str:
        """Return selected FFT window method."""
        return str(self._window_combo.currentData())

    def target_dataset_name(self) -> str:
        """Return requested result dataset name."""
        return self._target_dataset_edit.text().strip()


class IFFTDialog(QDialog):
    """Collect settings for inverse FFT operations."""

    def __init__(self, column_names: list[str], default_dataset_name: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Inverse FFT")
        self.setModal(True)
        self.setMinimumWidth(420)

        self._real_column_combo = QComboBox()
        self._real_column_combo.addItems(column_names)

        self._imaginary_column_combo = QComboBox()
        self._imaginary_column_combo.addItem("None / zero", None)
        for column_name in column_names:
            self._imaginary_column_combo.addItem(column_name, column_name)
        if "imaginary" in column_names:
            self._imaginary_column_combo.setCurrentText("imaginary")

        if "real" in column_names:
            self._real_column_combo.setCurrentText("real")

        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_iFFT")

        form = QFormLayout()
        form.addRow("Real column", self._real_column_combo)
        form.addRow("Imaginary column", self._imaginary_column_combo)
        form.addRow("Result sheet", self._target_dataset_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def real_column(self) -> str:
        """Return selected real spectrum column."""
        return self._real_column_combo.currentText()

    def imaginary_column(self) -> str | None:
        """Return selected imaginary spectrum column, or None for zero imaginary values."""
        value = self._imaginary_column_combo.currentData()
        return str(value) if value else None

    def target_dataset_name(self) -> str:
        """Return requested result dataset name."""
        return self._target_dataset_edit.text().strip()


class FitDialog(QDialog):
    """Collect settings for curve fitting."""

    def __init__(self, column_names: list[str], default_dataset_name: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Curve Fit")
        self.setModal(True)
        self.setMinimumWidth(560)

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItems(column_names)

        self._y_column_combo = QComboBox()
        self._y_column_combo.addItems(column_names)
        if len(column_names) > 1:
            self._y_column_combo.setCurrentIndex(1)

        self._model_combo = QComboBox()
        for model in available_fit_models():
            self._model_combo.addItem(model.name, model.key)

        self._method_combo = QComboBox()
        for method_key, method_label in FIT_METHODS.items():
            self._method_combo.addItem(method_label, method_key)
        self._method_combo.setCurrentText(FIT_METHODS["trf"])

        self._initial_params_edit = QLineEdit()
        self._parameter_hint = QLabel()
        self._parameter_hint.setWordWrap(True)
        self._parameter_hint.setTextFormat(Qt.RichText)

        self._fit_points_spin = QSpinBox()
        self._fit_points_spin.setRange(10, 10000)
        self._fit_points_spin.setSingleStep(50)
        self._fit_points_spin.setValue(400)

        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_fit")

        form = QFormLayout()
        form.addRow("X column", self._x_column_combo)
        form.addRow("Y column", self._y_column_combo)
        form.addRow("Model", self._model_combo)
        form.addRow("Method", self._method_combo)
        form.addRow("Initial parameters", self._initial_params_edit)
        form.addRow("", self._parameter_hint)
        form.addRow("Fit points", self._fit_points_spin)
        form.addRow("Result sheet", self._target_dataset_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._model_combo.currentIndexChanged.connect(self._update_parameter_hint)
        self._update_parameter_hint()

    def x_column(self) -> str:
        """Return selected X column."""
        return self._x_column_combo.currentText()

    def y_column(self) -> str:
        """Return selected Y column."""
        return self._y_column_combo.currentText()

    def model_key(self) -> str:
        """Return selected fit model key."""
        return str(self._model_combo.currentData())

    def method(self) -> str:
        """Return selected optimizer method key."""
        return str(self._method_combo.currentData())

    def initial_parameters_text(self) -> str:
        """Return raw initial-parameter text."""
        return self._initial_params_edit.text().strip()

    def fit_points(self) -> int:
        """Return number of points to generate for the fitted curve."""
        return self._fit_points_spin.value()

    def target_dataset_name(self) -> str:
        """Return requested result dataset name."""
        return self._target_dataset_edit.text().strip()

    def _update_parameter_hint(self) -> None:
        model = get_fit_model(self.model_key())
        parameter_names = ", ".join(model.parameter_names)
        defaults = ", ".join(f"{value:g}" for value in model.default_initial)
        self._parameter_hint.setText(
            f"<b>Equation:</b> <code>{escape(model.equation)}</code><br>"
            f"<b>Parameter order:</b> <code>{escape(parameter_names)}</code><br>"
            f"Leave blank for automatic guesses. Static defaults: <code>{escape(defaults)}</code>."
        )


class FitReportDialog(QDialog):
    """Display a curve-fitting report."""

    def __init__(self, report_text: str, parent: object | None = None) -> None:
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
