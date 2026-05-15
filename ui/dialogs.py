"""Application dialogs."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
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


class ColumnExpressionDialog(QDialog):
    """Collect settings for applying a Python-like expression to a column."""

    def __init__(
        self,
        column_names: list[str],
        selected_rows_available: bool,
        default_target: str | None = None,
        column_formulas: dict[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for target column, formula text, and row scope."""
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
        """Return HTML help text for the expression editor."""
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


class ColumnMathDialog(QDialog):
    """Collect settings for derivative or integral column operations."""

    def __init__(
        self,
        operation_name: str,
        column_names: list[str],
        methods: dict[str, str],
        default_target: str,
        include_initial_value: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for derivative/integral settings."""
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
        self._plot_result_checkbox = QCheckBox("Plot result immediately")
        self._plot_result_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow("X column", self._x_column_combo)
        form.addRow("Y column", self._y_column_combo)
        form.addRow("Method", self._method_combo)
        if self._include_initial_value:
            form.addRow("Initial value", self._initial_value_edit)
        form.addRow("Target column", self._target_edit)
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

    def plot_result_immediately(self) -> bool:
        """Return whether the operation result should be plotted immediately."""
        return self._plot_result_checkbox.isChecked()


class FFTDialog(QDialog):
    """Collect settings for FFT operations."""

    def __init__(self, column_names: list[str], default_dataset_name: str, parent: QWidget | None = None) -> None:
        """Create controls for FFT input, spacing, and output naming."""
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
        self._plot_result_checkbox = QCheckBox("Plot magnitude immediately")
        self._plot_result_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow("Signal column", self._signal_column_combo)
        form.addRow("X/time column", self._x_column_combo)
        form.addRow("Window", self._window_combo)
        form.addRow("Result sheet", self._target_dataset_edit)
        form.addRow("", self._plot_result_checkbox)

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

    def plot_result_immediately(self) -> bool:
        """Return whether the FFT magnitude should be plotted immediately."""
        return self._plot_result_checkbox.isChecked()


class IFFTDialog(QDialog):
    """Collect settings for inverse FFT operations."""

    def __init__(self, column_names: list[str], default_dataset_name: str, parent: QWidget | None = None) -> None:
        """Create controls for inverse FFT input and output naming."""
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
        self._plot_result_checkbox = QCheckBox("Plot reconstructed real signal immediately")
        self._plot_result_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow("Real column", self._real_column_combo)
        form.addRow("Imaginary column", self._imaginary_column_combo)
        form.addRow("Result sheet", self._target_dataset_edit)
        form.addRow("", self._plot_result_checkbox)

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

    def plot_result_immediately(self) -> bool:
        """Return whether the reconstructed real signal should be plotted immediately."""
        return self._plot_result_checkbox.isChecked()


class FitDialog(QDialog):
    """Collect settings for curve fitting."""

    def __init__(self, column_names: list[str], default_dataset_name: str, parent: QWidget | None = None) -> None:
        """Create controls for model selection, optimizer settings, and outputs."""
        super().__init__(parent)
        self.setWindowTitle("Curve Fit")
        self.setModal(True)
        self.setMinimumWidth(760)

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

        self._parameter_table = QTableWidget(0, 5)
        self._parameter_table.setHorizontalHeaderLabels(["Parameter", "Initial", "Lower", "Upper", "Fixed"])
        self._parameter_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._parameter_table.verticalHeader().setVisible(False)
        self._parameter_table.setMinimumHeight(170)

        self._parameter_hint = QLabel()
        self._parameter_hint.setWordWrap(True)
        self._parameter_hint.setTextFormat(Qt.RichText)

        self._x_weight_column_combo = QComboBox()
        self._x_weight_column_combo.addItem("None", None)
        for column_name in column_names:
            self._x_weight_column_combo.addItem(column_name, column_name)

        self._weight_column_combo = QComboBox()
        self._weight_column_combo.addItem("None", None)
        for column_name in column_names:
            self._weight_column_combo.addItem(column_name, column_name)

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

        self._fit_points_spin = QSpinBox()
        self._fit_points_spin.setRange(10, 10000)
        self._fit_points_spin.setSingleStep(50)
        self._fit_points_spin.setValue(400)

        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_fit")
        self._residual_dataset_edit = QLineEdit(f"{default_dataset_name}_residuals")

        form = QFormLayout()
        form.addRow("X column", self._x_column_combo)
        form.addRow("Y column", self._y_column_combo)
        form.addRow("Model", self._model_combo)
        form.addRow("Method", self._method_combo)
        form.addRow("Parameters", self._parameter_table)
        form.addRow("", self._parameter_hint)
        form.addRow("X weight/sigma column", self._x_weight_column_combo)
        form.addRow("Y weight/sigma column", self._weight_column_combo)
        form.addRow("Weight mode", self._weight_mode_combo)
        form.addRow("", self._absolute_sigma_checkbox)
        confidence_row = QWidget()
        confidence_layout = QHBoxLayout(confidence_row)
        confidence_layout.setContentsMargins(0, 0, 0, 0)
        confidence_layout.addWidget(self._confidence_checkbox)
        confidence_layout.addWidget(self._confidence_spin)
        confidence_layout.addStretch(1)
        form.addRow("", confidence_row)
        form.addRow("Fit points", self._fit_points_spin)
        form.addRow("Result sheet", self._target_dataset_edit)
        form.addRow("", self._residual_sheet_checkbox)
        form.addRow("", self._plot_residuals_checkbox)
        form.addRow("Residual sheet", self._residual_dataset_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._model_combo.currentIndexChanged.connect(self._update_parameter_hint)
        self._confidence_checkbox.toggled.connect(self._confidence_spin.setEnabled)
        self._residual_sheet_checkbox.toggled.connect(self._residual_dataset_edit.setEnabled)
        self._x_weight_column_combo.currentTextChanged.connect(self._on_x_weight_changed)
        self._update_parameter_hint()

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
        """Return optional Y weight/sigma column."""
        value = self._weight_column_combo.currentData()
        return str(value) if value else None

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

    def fit_points(self) -> int:
        """Return number of points to generate for the fitted curve."""
        return self._fit_points_spin.value()

    def target_dataset_name(self) -> str:
        """Return requested result dataset name."""
        return self._target_dataset_edit.text().strip()

    def residual_dataset_name(self) -> str:
        """Return requested residual dataset name."""
        return self._residual_dataset_edit.text().strip()

    def _update_parameter_hint(self) -> None:
        """Refresh model equation help and rebuild the parameter table."""
        model = get_fit_model(self.model_key())
        parameter_names = ", ".join(model.parameter_names)
        defaults = ", ".join(f"{value:g}" for value in model.default_initial)
        self._parameter_hint.setText(
            f"<b>Equation:</b> <code>{escape(model.equation)}</code><br>"
            f"<b>Parameter order:</b> <code>{escape(parameter_names)}</code><br>"
            f"Edit initial guesses and optional bounds. Blank bounds are unbounded. "
            f"Static defaults: <code>{escape(defaults)}</code>."
        )
        self._populate_parameter_table()

    def _populate_parameter_table(self) -> None:
        """Populate editable parameter rows for the selected model."""
        model = get_fit_model(self.model_key())
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
