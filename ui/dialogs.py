"""Application dialogs."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
    QVBoxLayout,
)

from core.file_io import ImportOptions
from core.workspace import COLUMN_ROLE_OPTIONS, ColumnMetadata, column_role_label
from math_engine.curve_fitting import FIT_METHODS
from math_engine.calculus import DERIVATIVE_METHODS, INTEGRATION_METHODS, WINDOW_METHODS
from math_engine.interpolation import (
    FILL_POLICIES,
    INTERPOLATION_METHODS,
    MAX_GENERATED_QUERY_POINTS,
)
from math_engine.statistics import STATISTIC_OPERATIONS
from models.fit_functions import (
    CustomFitModel,
    available_fit_models,
    create_custom_fit_model,
    get_fit_model,
)


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


class ColumnMetadataDialog(QDialog):
    """Edit lightweight role and descriptive metadata for dataset columns."""

    def __init__(
        self,
        dataset_name: str,
        column_names: list[str],
        column_metadata: dict[str, ColumnMetadata],
        focus_column: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Create a metadata table with one editable row per column."""
        super().__init__(parent)
        self.setWindowTitle("Column Metadata")
        self.setModal(True)
        self.resize(860, 420)
        self._column_names = list(column_names)

        self._table = QTableWidget(len(self._column_names), 5)
        self._table.setHorizontalHeaderLabels(["Column name", "Role", "Unit", "Long name", "Comment"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)

        for row, column_name in enumerate(self._column_names):
            metadata = column_metadata.get(column_name, ColumnMetadata())
            name_item = QTableWidgetItem(column_name)
            self._table.setItem(row, 0, name_item)

            role_combo = QComboBox()
            for role_key, role_label in COLUMN_ROLE_OPTIONS:
                role_combo.addItem(role_label, role_key)
            role_index = role_combo.findData(metadata.role)
            if role_index >= 0:
                role_combo.setCurrentIndex(role_index)
            self._table.setCellWidget(row, 1, role_combo)

            self._table.setItem(row, 2, QTableWidgetItem(metadata.unit))
            self._table.setItem(row, 3, QTableWidgetItem(metadata.long_name))
            self._table.setItem(row, 4, QTableWidgetItem(metadata.comment))

        hint = QLabel(
            "Edit the column name here to rename the dataset column. "
            "Roles are used as hints by plot, fitting, and future analysis dialogs. "
            "Units and long names appear in table tooltips and can be used for cleaner plot labels."
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Dataset: {dataset_name}"))
        layout.addWidget(hint)
        layout.addWidget(self._table)
        layout.addWidget(buttons)
        self._focus_column(focus_column)

    def column_names(self) -> list[str]:
        """Return edited column names in table order."""
        return [self._item_text(row, 0) for row in range(len(self._column_names))]

    def column_metadata(self) -> dict[str, ColumnMetadata]:
        """Return edited non-empty metadata keyed by edited column name."""
        metadata_by_column: dict[str, ColumnMetadata] = {}
        edited_names = self.column_names()
        for row, column_name in enumerate(edited_names):
            role_widget = self._table.cellWidget(row, 1)
            role = ""
            if isinstance(role_widget, QComboBox):
                role = str(role_widget.currentData() or "")

            metadata = ColumnMetadata(
                role=role,
                unit=self._item_text(row, 2),
                long_name=self._item_text(row, 3),
                comment=self._item_text(row, 4),
            )
            if not metadata.is_empty():
                metadata_by_column[column_name] = metadata
        return metadata_by_column

    def accept(self) -> None:
        """Validate column names, then accept edits."""
        names = self.column_names()
        if any(not name for name in names):
            QMessageBox.warning(self, "Column Metadata", "Column names cannot be blank.")
            return
        if len(set(names)) != len(names):
            QMessageBox.warning(self, "Column Metadata", "Column names must be unique.")
            return

        for row in range(self._table.rowCount()):
            role_widget = self._table.cellWidget(row, 1)
            if isinstance(role_widget, QComboBox):
                role_widget.setToolTip(column_role_label(str(role_widget.currentData() or "")))
        super().accept()

    def _focus_column(self, focus_column: str | None) -> None:
        """Select a column row when the dialog was opened from a header."""
        if not focus_column:
            return
        try:
            row = self._column_names.index(focus_column)
        except ValueError:
            return

        self._table.setCurrentCell(row, 0)
        item = self._table.item(row, 0)
        if item is not None:
            self._table.scrollToItem(item)

    def _item_text(self, row: int, column: int) -> str:
        """Return stripped text from a metadata table item."""
        item = self._table.item(row, column)
        return item.text().strip() if item is not None else ""


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
        default_x_column: str | None = None,
        default_y_column: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for derivative/integral settings."""
        super().__init__(parent)
        self.setWindowTitle(operation_name)
        self.setModal(True)
        self.setMinimumWidth(420)

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItems(column_names)
        self._set_combo_text_if_present(self._x_column_combo, default_x_column)

        self._y_column_combo = QComboBox()
        self._y_column_combo.addItems(column_names)
        if default_y_column:
            self._set_combo_text_if_present(self._y_column_combo, default_y_column)
        elif len(column_names) > 1:
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

    @staticmethod
    def _set_combo_text_if_present(combo: QComboBox, value: str | None) -> None:
        """Select a combo item by text when it exists."""
        if not value:
            return
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)


class FFTDialog(QDialog):
    """Collect settings for FFT operations."""

    def __init__(
        self,
        column_names: list[str],
        default_dataset_name: str,
        default_signal_column: str | None = None,
        default_x_column: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for FFT input, spacing, and output naming."""
        super().__init__(parent)
        self.setWindowTitle("FFT")
        self.setModal(True)
        self.setMinimumWidth(420)

        self._signal_column_combo = QComboBox()
        self._signal_column_combo.addItems(column_names)
        if default_signal_column:
            self._set_combo_text_if_present(self._signal_column_combo, default_signal_column)
        elif len(column_names) > 1:
            self._signal_column_combo.setCurrentIndex(1)

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItem("Sample index", None)
        for column_name in column_names:
            self._x_column_combo.addItem(column_name, column_name)
        self._set_combo_text_if_present(self._x_column_combo, default_x_column)

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

    @staticmethod
    def _set_combo_text_if_present(combo: QComboBox, value: str | None) -> None:
        """Select a combo item by text when it exists."""
        if not value:
            return
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)


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


class InterpolationDialog(QDialog):
    """Collect settings for 1D, 2D, and N-D interpolation."""

    def __init__(
        self,
        column_names: list[str],
        default_dataset_name: str,
        column_ranges: dict[str, tuple[float, float]],
        default_x_column: str | None = None,
        default_y_column: str | None = None,
        default_z_column: str | None = None,
        default_value_column: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build interpolation source, method, query, and output controls."""
        super().__init__(parent)
        self.setWindowTitle("Interpolation")
        self.setModal(True)
        self.resize(760, 620)
        self._column_names = list(column_names)
        self._column_ranges = column_ranges
        self._default_value_by_mode = {
            "1d": default_value_column or default_y_column or default_z_column,
            "2d": default_z_column or default_value_column or default_y_column,
            "nd": default_z_column or default_value_column or default_y_column,
        }
        self._last_mode = "1d"

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("1D: x -> value", "1d")
        self._mode_combo.addItem("2D: x, y -> value", "2d")
        self._mode_combo.addItem("N-D: coordinates -> value", "nd")

        self._value_column_combo = QComboBox()
        self._value_column_combo.addItems(self._column_names)
        self._set_combo_text_if_present(
            self._value_column_combo,
            self._default_value_by_mode["1d"],
        )

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItems(self._column_names)
        self._set_combo_text_if_present(self._x_column_combo, default_x_column)

        self._y_column_combo = QComboBox()
        self._y_column_combo.addItems(self._column_names)
        self._set_combo_text_if_present(self._y_column_combo, default_y_column)

        self._nd_source_list = self._column_list()
        self._select_list_columns(
            self._nd_source_list,
            [column for column in (default_x_column, default_y_column) if column],
        )

        self._method_combo = QComboBox()
        self._fill_policy_combo = QComboBox()
        for key, label in FILL_POLICIES.items():
            self._fill_policy_combo.addItem(label, key)

        self._smoothing_spin = QDoubleSpinBox()
        self._smoothing_spin.setRange(0.0, 1_000_000.0)
        self._smoothing_spin.setDecimals(6)
        self._smoothing_spin.setSingleStep(0.1)
        self._smoothing_spin.setValue(0.0)

        self._epsilon_spin = QDoubleSpinBox()
        self._epsilon_spin.setRange(0.0, 1_000_000.0)
        self._epsilon_spin.setDecimals(6)
        self._epsilon_spin.setSingleStep(0.1)
        self._epsilon_spin.setSpecialValueText("auto")
        self._epsilon_spin.setValue(0.0)

        self._query_mode_combo = QComboBox()

        self._x_start_edit = QLineEdit()
        self._x_end_edit = QLineEdit()
        self._x_count_spin = QSpinBox()
        self._x_count_spin.setRange(1, 1_000_000)
        self._x_count_spin.setValue(200)

        self._y_start_edit = QLineEdit()
        self._y_end_edit = QLineEdit()
        self._y_count_spin = QSpinBox()
        self._y_count_spin.setRange(1, 100_000)
        self._y_count_spin.setValue(100)

        self._query_x_column_combo = QComboBox()
        self._query_x_column_combo.addItems(self._column_names)
        self._set_combo_text_if_present(self._query_x_column_combo, default_x_column)

        self._query_y_column_combo = QComboBox()
        self._query_y_column_combo.addItems(self._column_names)
        self._set_combo_text_if_present(self._query_y_column_combo, default_y_column)

        self._nd_query_list = self._column_list()
        self._select_list_columns(
            self._nd_query_list,
            [column for column in (default_x_column, default_y_column) if column],
        )

        self._manual_points_edit = QPlainTextEdit()
        self._manual_points_edit.setMinimumHeight(120)

        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_interpolation")

        source_panel = self._source_panel()

        query_stack = QStackedWidget()
        query_stack.addWidget(self._generated_query_panel())
        query_stack.addWidget(self._column_query_panel())
        query_stack.addWidget(self._manual_query_panel())
        self._query_stack = query_stack

        form = QFormLayout()
        form.addRow("Dimension", self._mode_combo)
        form.addRow("Value column", self._value_column_combo)
        form.addRow("Source coordinates", source_panel)
        form.addRow("Method", self._method_combo)
        form.addRow("Outside range", self._fill_policy_combo)
        form.addRow("Smoothing", self._smoothing_spin)
        form.addRow("RBF epsilon", self._epsilon_spin)
        form.addRow("Query mode", self._query_mode_combo)
        form.addRow("Query coordinates", query_stack)
        form.addRow("Result sheet", self._target_dataset_edit)

        hint = QLabel(
            "Generated 2D queries create a full X/Y grid. N-D interpolation supports existing "
            "query columns or manual coordinate rows. Duplicate source coordinates are averaged."
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self._mode_combo.currentIndexChanged.connect(self._update_mode)
        self._method_combo.currentIndexChanged.connect(self._update_method_parameters)
        self._query_mode_combo.currentIndexChanged.connect(self._update_query_mode)
        self._x_column_combo.currentTextChanged.connect(lambda: self._set_range_fields("x"))
        self._y_column_combo.currentTextChanged.connect(lambda: self._set_range_fields("y"))
        self._update_mode()
        self._set_range_fields("x")
        self._set_range_fields("y")

    def mode(self) -> str:
        """Return interpolation dimensionality key."""
        return str(self._mode_combo.currentData())

    def coordinate_columns(self) -> list[str]:
        """Return selected source coordinate columns in dimensional order."""
        mode = self.mode()
        if mode == "1d":
            return [self._x_column_combo.currentText()]
        if mode == "2d":
            return [self._x_column_combo.currentText(), self._y_column_combo.currentText()]
        return self._selected_list_columns(self._nd_source_list)

    def value_column(self) -> str:
        """Return the source value column."""
        return self._value_column_combo.currentText()

    def method_key(self) -> str:
        """Return selected interpolation method key."""
        return str(self._method_combo.currentData())

    def fill_policy(self) -> str:
        """Return selected 1D outside-range policy."""
        return str(self._fill_policy_combo.currentData() or "nan")

    def smoothing(self) -> float:
        """Return smoothing parameter for spline/RBF methods."""
        return self._smoothing_spin.value()

    def epsilon(self) -> float | None:
        """Return RBF epsilon, or None when disabled."""
        return self._epsilon_spin.value() if self._epsilon_spin.isEnabled() else None

    def query_mode(self) -> str:
        """Return selected query input mode."""
        return str(self._query_mode_combo.currentData())

    def query_columns(self) -> list[str]:
        """Return query coordinate columns for the existing-column query mode."""
        mode = self.mode()
        if mode == "1d":
            return [self._query_x_column_combo.currentText()]
        if mode == "2d":
            return [self._query_x_column_combo.currentText(), self._query_y_column_combo.currentText()]
        return self._selected_list_columns(self._nd_query_list)

    def generated_ranges(self) -> list[tuple[float, float, int]]:
        """Return generated coordinate ranges."""
        ranges = [
            (
                self._required_float(self._x_start_edit.text(), "X start"),
                self._required_float(self._x_end_edit.text(), "X end"),
                self._x_count_spin.value(),
            )
        ]
        if self.mode() == "2d":
            ranges.append(
                (
                    self._required_float(self._y_start_edit.text(), "Y start"),
                    self._required_float(self._y_end_edit.text(), "Y end"),
                    self._y_count_spin.value(),
                )
            )
        return ranges

    def manual_points_text(self) -> str:
        """Return raw manual query coordinate text."""
        return self._manual_points_edit.toPlainText()

    def target_dataset_name(self) -> str:
        """Return requested result dataset name."""
        return self._target_dataset_edit.text().strip()

    def accept(self) -> None:
        """Validate the interpolation request before closing."""
        try:
            self._validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Interpolation", str(exc))
            return
        super().accept()

    def _source_panel(self) -> QWidget:
        """Return source-coordinate controls shared by all modes."""
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("X column", self._x_column_combo)
        form.addRow("Y column", self._y_column_combo)
        form.addRow("N-D columns", self._nd_source_list)
        self._source_x_label = form.labelForField(self._x_column_combo)
        self._source_y_label = form.labelForField(self._y_column_combo)
        self._source_nd_label = form.labelForField(self._nd_source_list)
        return panel

    def _generated_query_panel(self) -> QWidget:
        """Return generated query range controls."""
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("X range", self._range_row(self._x_start_edit, self._x_end_edit, self._x_count_spin))
        self._generated_y_row = self._range_row(self._y_start_edit, self._y_end_edit, self._y_count_spin)
        form.addRow("Y range", self._generated_y_row)
        self._generated_y_label = form.labelForField(self._generated_y_row)
        return panel

    def _column_query_panel(self) -> QWidget:
        """Return query-from-columns controls."""
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Query X", self._query_x_column_combo)
        form.addRow("Query Y", self._query_y_column_combo)
        form.addRow("Query N-D columns", self._nd_query_list)
        self._query_x_label = form.labelForField(self._query_x_column_combo)
        self._query_y_label = form.labelForField(self._query_y_column_combo)
        self._query_nd_label = form.labelForField(self._nd_query_list)
        return panel

    def _manual_query_panel(self) -> QWidget:
        """Return manual query-coordinate controls."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self._manual_points_edit.setPlaceholderText("One query point per line, values separated by spaces, commas, or tabs.")
        layout.addWidget(self._manual_points_edit)
        return panel

    def _update_mode(self) -> None:
        """Refresh mode-specific controls."""
        mode = self.mode()
        previous_default = self._default_value_by_mode.get(self._last_mode)
        new_default = self._default_value_by_mode.get(mode)
        if new_default and self._value_column_combo.currentText() in {"", previous_default}:
            self._set_combo_text_if_present(self._value_column_combo, new_default)
        self._last_mode = mode
        x_visible = mode in {"1d", "2d"}
        y_visible = mode == "2d"
        nd_visible = mode == "nd"
        self._source_x_label.setVisible(x_visible)
        self._x_column_combo.setVisible(x_visible)
        self._source_y_label.setVisible(y_visible)
        self._y_column_combo.setVisible(y_visible)
        self._source_nd_label.setVisible(nd_visible)
        self._nd_source_list.setVisible(nd_visible)
        self._refresh_methods()
        self._refresh_query_modes()
        self._fill_policy_combo.setEnabled(mode == "1d")
        self._generated_y_label.setVisible(mode == "2d")
        self._generated_y_row.setVisible(mode == "2d")
        query_xy_visible = mode in {"1d", "2d"}
        self._query_x_label.setVisible(query_xy_visible)
        self._query_x_column_combo.setVisible(query_xy_visible)
        self._query_y_label.setVisible(mode == "2d")
        self._query_y_column_combo.setVisible(mode == "2d")
        self._query_nd_label.setVisible(mode == "nd")
        self._nd_query_list.setVisible(mode == "nd")
        self._set_range_fields("x")
        self._set_range_fields("y")

    def _refresh_methods(self) -> None:
        """Reload methods for the selected dimensionality."""
        current = self._method_combo.currentData()
        methods = INTERPOLATION_METHODS.get(self.mode(), {})
        self._method_combo.blockSignals(True)
        self._method_combo.clear()
        for key, method in methods.items():
            self._method_combo.addItem(method.label, key)
        index = self._method_combo.findData(current)
        if index >= 0:
            self._method_combo.setCurrentIndex(index)
        self._method_combo.blockSignals(False)
        self._update_method_parameters()

    def _refresh_query_modes(self) -> None:
        """Reload query modes for the selected dimensionality."""
        current = self._query_mode_combo.currentData()
        self._query_mode_combo.blockSignals(True)
        self._query_mode_combo.clear()
        if self.mode() in {"1d", "2d"}:
            self._query_mode_combo.addItem("Generated range/grid", "generated")
        self._query_mode_combo.addItem("From existing columns", "columns")
        self._query_mode_combo.addItem("Manual coordinates", "manual")
        index = self._query_mode_combo.findData(current)
        if index >= 0:
            self._query_mode_combo.setCurrentIndex(index)
        self._query_mode_combo.blockSignals(False)
        self._update_query_mode()

    def _update_query_mode(self) -> None:
        """Show the controls for the selected query mode."""
        mode_index = {"generated": 0, "columns": 1, "manual": 2}.get(self.query_mode(), 0)
        self._query_stack.setCurrentIndex(mode_index)

    def _update_method_parameters(self) -> None:
        """Enable optional parameter controls only when relevant."""
        method = self.method_key()
        uses_smoothing = method in {
            "smoothing_spline",
            "smooth_bivariate_spline",
            "rbf_linear",
            "rbf_thin_plate",
            "rbf_cubic",
            "rbf_gaussian",
        }
        self._smoothing_spin.setEnabled(uses_smoothing)
        self._epsilon_spin.setEnabled(method == "rbf_gaussian")
        method_info = INTERPOLATION_METHODS.get(self.mode(), {}).get(method)
        self._method_combo.setToolTip(method_info.description if method_info else "")

    def _validate(self) -> None:
        """Validate source/query controls."""
        coordinates = self.coordinate_columns()
        if any(not column for column in coordinates):
            raise ValueError("Choose all coordinate columns.")
        if len(set(coordinates)) != len(coordinates):
            raise ValueError("Coordinate columns must be unique.")
        if self.value_column() in coordinates:
            raise ValueError("The value column must be different from coordinate columns.")
        if self.mode() == "nd" and len(coordinates) < 2:
            raise ValueError("N-D interpolation requires at least two coordinate columns.")
        if self.query_mode() == "columns":
            query_columns = self.query_columns()
            if len(query_columns) != len(coordinates) or any(not column for column in query_columns):
                raise ValueError("Choose one query column for each coordinate dimension.")
            if len(set(query_columns)) != len(query_columns):
                raise ValueError("Query coordinate columns must be unique.")
        elif self.query_mode() == "generated":
            total_count = 1
            for _start, _end, count in self.generated_ranges():
                total_count *= count
            if total_count > MAX_GENERATED_QUERY_POINTS:
                raise ValueError(
                    f"Generated queries are limited to {MAX_GENERATED_QUERY_POINTS:,} points."
                )
        elif not self.manual_points_text().strip():
            raise ValueError("Enter manual query coordinates.")

    def _set_range_fields(self, axis: str) -> None:
        """Prefill generated query ranges from source column numeric ranges."""
        if axis == "x":
            column = self._x_column_combo.currentText()
            start_edit, end_edit = self._x_start_edit, self._x_end_edit
        else:
            column = self._y_column_combo.currentText()
            start_edit, end_edit = self._y_start_edit, self._y_end_edit
        value_range = self._column_ranges.get(column)
        if value_range is None:
            return
        start, end = value_range
        start_edit.setText(f"{start:g}")
        end_edit.setText(f"{end:g}")

    @staticmethod
    def _range_row(start_edit: QLineEdit, end_edit: QLineEdit, count_spin: QSpinBox) -> QWidget:
        """Return a compact generated-range row."""
        start_edit.setPlaceholderText("start")
        end_edit.setPlaceholderText("end")
        start_edit.setMaximumWidth(100)
        end_edit.setMaximumWidth(100)
        count_spin.setPrefix("n=")
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(start_edit)
        layout.addWidget(end_edit)
        layout.addWidget(count_spin)
        layout.addStretch(1)
        return row

    def _column_list(self) -> QListWidget:
        """Return a multi-select list populated with dataset columns."""
        widget = QListWidget()
        widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        widget.setMaximumHeight(120)
        widget.addItems(self._column_names)
        return widget

    @staticmethod
    def _selected_list_columns(widget: QListWidget) -> list[str]:
        """Return selected list items in visual order."""
        return [
            widget.item(row).text()
            for row in range(widget.count())
            if widget.item(row).isSelected()
        ]

    @staticmethod
    def _select_list_columns(widget: QListWidget, columns: list[str]) -> None:
        """Select list items whose text appears in columns."""
        wanted = set(columns)
        for row in range(widget.count()):
            item = widget.item(row)
            item.setSelected(item.text() in wanted)

    @staticmethod
    def _set_combo_text_if_present(combo: QComboBox, value: str | None) -> None:
        """Select a combo item by text when present."""
        if not value:
            return
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _required_float(text: str, label: str) -> float:
        """Parse a required float."""
        try:
            return float(text.strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be numeric.") from exc


class StatisticsDialog(QDialog):
    """Collect settings for single, paired, grouped, and multi-column statistics."""

    def __init__(
        self,
        dataset_columns: dict[str, list[str]],
        default_dataset_name: str,
        parent: QWidget | None = None,
    ) -> None:
        """Build operation, dataset, column, and result-sheet controls."""
        super().__init__(parent)
        self.setWindowTitle("Statistics")
        self.setModal(True)
        self.setMinimumWidth(620)
        self._dataset_columns = dataset_columns

        self._operation_combo = QComboBox()
        for key, operation in STATISTIC_OPERATIONS.items():
            self._operation_combo.addItem(operation.label, key)

        self._primary_dataset_combo = QComboBox()
        self._primary_dataset_combo.addItems(list(dataset_columns.keys()))
        if default_dataset_name in dataset_columns:
            self._primary_dataset_combo.setCurrentText(default_dataset_name)

        self._primary_column_combo = QComboBox()
        self._multi_column_list = QListWidget()
        self._multi_column_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._multi_column_list.setMinimumHeight(130)
        self._secondary_dataset_combo = QComboBox()
        self._secondary_dataset_combo.addItems(list(dataset_columns.keys()))
        if default_dataset_name in dataset_columns:
            self._secondary_dataset_combo.setCurrentText(default_dataset_name)

        self._secondary_column_combo = QComboBox()
        self._target_dataset_edit = QLineEdit(f"{default_dataset_name}_statistics")
        self._plot_result_checkbox = QCheckBox("Create companion plot")
        self._plot_result_checkbox.setChecked(True)
        self._plot_kind_combo = QComboBox()

        self._hint_label = QLabel()
        self._hint_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Operation", self._operation_combo)
        form.addRow("Primary sheet", self._primary_dataset_combo)
        form.addRow("Primary column", self._primary_column_combo)
        form.addRow("Columns", self._multi_column_list)
        form.addRow("Secondary sheet", self._secondary_dataset_combo)
        form.addRow("Secondary column", self._secondary_column_combo)
        form.addRow("Result sheet", self._target_dataset_edit)
        form.addRow("", self._plot_result_checkbox)
        form.addRow("Plot", self._plot_kind_combo)
        form.addRow("", self._hint_label)
        self._primary_column_label = form.labelForField(self._primary_column_combo)
        self._multi_columns_label = form.labelForField(self._multi_column_list)
        self._secondary_sheet_label = form.labelForField(self._secondary_dataset_combo)
        self._secondary_column_label = form.labelForField(self._secondary_column_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._operation_combo.currentIndexChanged.connect(self._update_scope)
        self._primary_dataset_combo.currentTextChanged.connect(self._refresh_primary_columns)
        self._secondary_dataset_combo.currentTextChanged.connect(self._refresh_secondary_columns)
        self._plot_result_checkbox.toggled.connect(self._plot_kind_combo.setEnabled)

        self._refresh_primary_columns(self._primary_dataset_combo.currentText())
        self._refresh_secondary_columns(self._secondary_dataset_combo.currentText())
        self._update_scope()

    def operation_key(self) -> str:
        """Return the selected statistics operation key."""
        return str(self._operation_combo.currentData())

    def primary_dataset_name(self) -> str:
        """Return the selected primary dataset name."""
        return self._primary_dataset_combo.currentText()

    def primary_column(self) -> str:
        """Return the selected primary column name."""
        return self._primary_column_combo.currentText()

    def multi_columns(self) -> list[str]:
        """Return selected source columns for multi-column operations."""
        return [item.text() for item in self._multi_column_list.selectedItems()]

    def secondary_dataset_name(self) -> str:
        """Return the selected secondary dataset name."""
        return self._secondary_dataset_combo.currentText()

    def secondary_column(self) -> str:
        """Return the selected secondary column name."""
        return self._secondary_column_combo.currentText()

    def target_dataset_name(self) -> str:
        """Return requested statistics result dataset name."""
        return self._target_dataset_edit.text().strip()

    def plot_result_immediately(self) -> bool:
        """Return whether a companion plot should be created."""
        return self._plot_result_checkbox.isChecked()

    def statistics_plot_kind(self) -> str:
        """Return the selected companion plot kind."""
        return str(self._plot_kind_combo.currentData() or "auto")

    def requires_secondary_column(self) -> bool:
        """Return whether the selected operation needs a secondary/group column."""
        return self.operation_scope() in {"pair", "group"}

    def operation_scope(self) -> str:
        """Return the selected operation scope key."""
        operation = STATISTIC_OPERATIONS[self.operation_key()]
        return operation.scope

    def _refresh_primary_columns(self, dataset_name: str) -> None:
        """Refresh primary column choices for the selected dataset."""
        self._refresh_column_combo(self._primary_column_combo, dataset_name, prefer_second=False)
        self._refresh_multi_columns(dataset_name)

    def _refresh_secondary_columns(self, dataset_name: str) -> None:
        """Refresh secondary column choices for the selected dataset."""
        self._refresh_column_combo(self._secondary_column_combo, dataset_name, prefer_second=True)

    def _refresh_column_combo(self, combo: QComboBox, dataset_name: str, prefer_second: bool) -> None:
        """Reload one column combo from the dataset-column map."""
        previous = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        columns = self._dataset_columns.get(dataset_name, [])
        combo.addItems(columns)
        if previous in columns:
            combo.setCurrentText(previous)
        elif prefer_second and len(columns) > 1:
            combo.setCurrentIndex(1)
        combo.blockSignals(False)

    def _refresh_multi_columns(self, dataset_name: str) -> None:
        """Refresh multi-column operation choices for the selected dataset."""
        previous = set(self.multi_columns())
        columns = self._dataset_columns.get(dataset_name, [])
        selected = previous.intersection(columns) or set(columns)
        self._multi_column_list.clear()
        for column in columns:
            self._multi_column_list.addItem(column)
            item = self._multi_column_list.item(self._multi_column_list.count() - 1)
            item.setSelected(column in selected)

    def _update_scope(self) -> None:
        """Refresh controls for single, pair, or grouped operations."""
        scope = self.operation_scope()
        is_multi = scope == "multi"
        uses_secondary = scope in {"pair", "group"}
        self._primary_column_combo.setVisible(not is_multi)
        self._primary_column_label.setVisible(not is_multi)
        self._multi_column_list.setVisible(is_multi)
        self._multi_columns_label.setVisible(is_multi)
        self._secondary_dataset_combo.setEnabled(uses_secondary)
        self._secondary_column_combo.setEnabled(uses_secondary)
        if scope == "group":
            self._secondary_sheet_label.setText("Group sheet")
            self._secondary_column_label.setText("Group column")
        else:
            self._secondary_sheet_label.setText("Secondary sheet")
            self._secondary_column_label.setText("Secondary column")
        self._refresh_plot_kind_options()
        if scope == "pair":
            self._hint_label.setText(
                "Two-column operations align values by row position for paired tests and correlations. "
                "Independent-sample tests use all numeric values in each selected column."
            )
        elif scope == "group":
            self._hint_label.setText(
                "Grouped operations use the primary numeric value column and split rows by the selected group/factor column."
            )
        elif scope == "multi":
            self._hint_label.setText(
                "Multiple-column operations use two or more numeric columns from the primary sheet for summaries, "
                "correlations, covariance, and PCA."
            )
        else:
            self._hint_label.setText(
                "Single-column operations use numeric values from the primary column and ignore blanks, text, and infinities."
            )

    def _refresh_plot_kind_options(self) -> None:
        """Reload companion plot choices for the selected statistics operation."""
        previous = self._plot_kind_combo.currentData()
        operation_key = self.operation_key()
        scope = self.operation_scope()
        options = [("Auto", "auto")]
        if scope == "pair":
            options.extend(
                [
                    ("Scatter", "scatter"),
                    ("Scatter + regression line", "regression"),
                    ("Box plot comparison", "box"),
                    ("Violin comparison", "violin"),
                    ("Bland-Altman", "bland_altman"),
                ]
            )
        elif scope == "group":
            options.extend(
                [
                    ("Box plot by group", "box"),
                    ("Violin by group", "violin"),
                ]
            )
        elif scope == "multi":
            options.extend(
                [
                    ("Box plot selected columns", "box"),
                    ("Violin selected columns", "violin"),
                ]
            )
            if operation_key in {"multi_complete", "multi_correlations"}:
                options.append(("Correlation heatmap", "correlation_heatmap"))
            if operation_key in {"multi_complete", "multi_pca"}:
                options.append(("PCA explained variance", "pca_variance"))
        else:
            options.extend(
                [
                    ("Histogram + normal curve", "histogram"),
                    ("Box plot", "box"),
                    ("Violin plot", "violin"),
                ]
            )
            if operation_key in {"single_zscore", "single_cumulative"}:
                options.append(("Result series", "result_series"))

        self._plot_kind_combo.blockSignals(True)
        self._plot_kind_combo.clear()
        for label, key in options:
            self._plot_kind_combo.addItem(label, key)
        index = self._plot_kind_combo.findData(previous)
        if index >= 0:
            self._plot_kind_combo.setCurrentIndex(index)
        self._plot_kind_combo.blockSignals(False)
        self._plot_kind_combo.setEnabled(self._plot_result_checkbox.isChecked())

    def accept(self) -> None:
        """Validate statistics selections before closing."""
        if self.operation_scope() == "multi" and len(self.multi_columns()) < 2:
            QMessageBox.warning(self, "Statistics", "Choose at least two columns for a multiple-column operation.")
            return
        super().accept()


class CustomFitModelDialog(QDialog):
    """Create or edit one expression-based custom fit model."""

    def __init__(
        self,
        model: CustomFitModel | None = None,
        existing_names: set[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build custom model fields and validation controls."""
        super().__init__(parent)
        self.setWindowTitle("Custom Fit Model")
        self.setModal(True)
        self.setMinimumWidth(680)
        self._existing_names = existing_names or set()
        self._model: CustomFitModel | None = model

        self._name_edit = QLineEdit(model.name if model else "Custom Model")
        self._parameters_edit = QLineEdit(
            ", ".join(model.parameter_names) if model else "a, b"
        )
        self._initial_edit = QLineEdit(
            ", ".join(f"{value:g}" for value in model.default_initial) if model else "1, 0"
        )
        self._expression_edit = QPlainTextEdit()
        self._expression_edit.setMinimumHeight(110)
        self._expression_edit.setPlainText(model.expression if model else "a*x + b")
        self._expression_edit.setPlaceholderText("Example: a*np.exp(-x/tau) + c")

        hint = QLabel(
            "Use x for the independent variable and comma-separated parameter names. "
            "Available namespaces include np, scipy.special, scipy.signal, scipy.stats, and scipy.integrate."
        )
        hint.setWordWrap(True)

        validate_button = QPushButton("Validate")
        validate_button.clicked.connect(self._validate_model)

        form = QFormLayout()
        form.addRow("Name", self._name_edit)
        form.addRow("Expression", self._expression_edit)
        form.addRow("Parameters", self._parameters_edit)
        form.addRow("Initial values", self._initial_edit)
        form.addRow("", hint)
        form.addRow("", validate_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def model(self) -> CustomFitModel:
        """Return the validated custom fit model."""
        if self._model is None:
            raise ValueError("Custom model has not been validated.")
        return self._model

    def accept(self) -> None:
        """Validate and accept the dialog."""
        try:
            self._model = self._model_from_fields()
        except Exception as exc:
            QMessageBox.warning(self, "Custom Fit Model", str(exc))
            return
        super().accept()

    def _validate_model(self) -> None:
        """Validate current fields and show the result to the user."""
        try:
            self._model = self._model_from_fields()
        except Exception as exc:
            QMessageBox.warning(self, "Custom Fit Model", str(exc))
            return
        QMessageBox.information(self, "Custom Fit Model", "Model expression is valid.")

    def _model_from_fields(self) -> CustomFitModel:
        """Create a custom model from the current dialog fields."""
        name = self._name_edit.text().strip()
        if name in self._existing_names:
            raise ValueError(f"A custom model named '{name}' already exists.")
        return create_custom_fit_model(
            name=name,
            expression=self._expression_edit.toPlainText(),
            parameter_names=self._parse_csv_text(self._parameters_edit.text()),
            default_initial=[float(value) for value in self._parse_csv_text(self._initial_edit.text())],
        )

    @staticmethod
    def _parse_csv_text(text: str) -> list[str]:
        """Return comma-separated entries with whitespace stripped."""
        return [item.strip() for item in text.split(",") if item.strip()]


class CustomFitModelsDialog(QDialog):
    """Manage project custom fit models."""

    def __init__(self, models: list[CustomFitModel], parent: QWidget | None = None) -> None:
        """Build the custom model manager."""
        super().__init__(parent)
        self.setWindowTitle("Custom Fit Models")
        self.setModal(True)
        self.resize(720, 420)
        self._models = list(models)

        self._model_list = QListWidget()
        self._model_list.currentRowChanged.connect(self._update_preview)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)

        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_model)
        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(self._edit_model)
        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(self._duplicate_model)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_model)

        button_row = QHBoxLayout()
        button_row.addWidget(add_button)
        button_row.addWidget(edit_button)
        button_row.addWidget(duplicate_button)
        button_row.addWidget(remove_button)
        button_row.addStretch(1)

        content_row = QHBoxLayout()
        content_row.addWidget(self._model_list, 1)
        content_row.addWidget(self._preview, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(content_row)
        layout.addLayout(button_row)
        layout.addWidget(buttons)
        self._refresh_model_list()

    def custom_models(self) -> list[CustomFitModel]:
        """Return the edited custom fit model list."""
        return list(self._models)

    def _add_model(self) -> None:
        """Create a new custom model."""
        dialog = CustomFitModelDialog(existing_names=self._model_names(), parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._models.append(dialog.model())
        self._refresh_model_list(len(self._models) - 1)

    def _edit_model(self) -> None:
        """Edit the selected custom model."""
        row = self._selected_row()
        if row is None:
            QMessageBox.information(self, "Custom Fit Models", "Select a model before editing it.")
            return
        model = self._models[row]
        dialog = CustomFitModelDialog(
            model=model,
            existing_names=self._model_names(excluding=row),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._models[row] = dialog.model()
        self._refresh_model_list(row)

    def _duplicate_model(self) -> None:
        """Duplicate the selected custom model."""
        row = self._selected_row()
        if row is None:
            QMessageBox.information(self, "Custom Fit Models", "Select a model before duplicating it.")
            return
        source = self._models[row]
        model = CustomFitModel(
            name=self._unique_name(f"{source.name} Copy"),
            expression=source.expression,
            parameter_names=source.parameter_names,
            default_initial=source.default_initial,
        )
        self._models.append(model)
        self._refresh_model_list(len(self._models) - 1)

    def _remove_model(self) -> None:
        """Remove the selected custom model."""
        row = self._selected_row()
        if row is None:
            QMessageBox.information(self, "Custom Fit Models", "Select a model before removing it.")
            return
        self._models.pop(row)
        self._refresh_model_list(min(row, len(self._models) - 1))

    def _refresh_model_list(self, selected_row: int | None = None) -> None:
        """Refresh the visible model list."""
        self._model_list.blockSignals(True)
        self._model_list.clear()
        self._model_list.addItems([model.name for model in self._models])
        self._model_list.blockSignals(False)
        if selected_row is not None and selected_row >= 0 and self._models:
            self._model_list.setCurrentRow(selected_row)
        elif self._models:
            self._model_list.setCurrentRow(0)
        else:
            self._update_preview()

    def _update_preview(self) -> None:
        """Show a read-only summary for the selected model."""
        row = self._selected_row()
        if row is None:
            self._preview.clear()
            return
        model = self._models[row]
        initial_values = ", ".join(f"{value:g}" for value in model.default_initial)
        self._preview.setPlainText(
            f"Name: {model.name}\n"
            f"Expression: {model.expression}\n"
            f"Parameters: {', '.join(model.parameter_names)}\n"
            f"Initial values: {initial_values}"
        )

    def _selected_row(self) -> int | None:
        """Return the selected model row, if any."""
        row = self._model_list.currentRow()
        return row if 0 <= row < len(self._models) else None

    def _model_names(self, excluding: int | None = None) -> set[str]:
        """Return existing model names, optionally excluding one row."""
        return {
            model.name
            for index, model in enumerate(self._models)
            if excluding is None or index != excluding
        }

    def _unique_name(self, base_name: str) -> str:
        """Return a custom model name unique within the manager."""
        names = self._model_names()
        if base_name not in names:
            return base_name
        counter = 2
        while f"{base_name} ({counter})" in names:
            counter += 1
        return f"{base_name} ({counter})"


class FitDialog(QDialog):
    """Collect settings for curve fitting."""

    def __init__(
        self,
        column_names: list[str],
        default_dataset_name: str,
        custom_models: list[CustomFitModel] | None = None,
        default_x_column: str | None = None,
        default_y_column: str | None = None,
        default_x_weight_column: str | None = None,
        default_y_weight_column: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Create controls for model selection, optimizer settings, and outputs."""
        super().__init__(parent)
        self.setWindowTitle("Curve Fit")
        self.setModal(True)
        self.setMinimumWidth(760)
        self._custom_models = custom_models or []

        self._x_column_combo = QComboBox()
        self._x_column_combo.addItems(column_names)
        self._set_combo_text_if_present(self._x_column_combo, default_x_column)

        self._y_column_combo = QComboBox()
        self._y_column_combo.addItems(column_names)
        if default_y_column:
            self._set_combo_text_if_present(self._y_column_combo, default_y_column)
        elif len(column_names) > 1:
            self._y_column_combo.setCurrentIndex(1)

        self._model_combo = QComboBox()
        for model in available_fit_models(self._custom_models):
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
        self._set_combo_text_if_present(self._x_weight_column_combo, default_x_weight_column)

        self._weight_column_combo = QComboBox()
        self._weight_column_combo.addItem("None", None)
        for column_name in column_names:
            self._weight_column_combo.addItem(column_name, column_name)
        self._set_combo_text_if_present(self._weight_column_combo, default_y_weight_column)

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
        self._on_x_weight_changed()

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

    @staticmethod
    def _set_combo_text_if_present(combo: QComboBox, value: str | None) -> None:
        """Select a combo item by text when it exists."""
        if not value:
            return
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

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
        model = get_fit_model(self.model_key(), self._custom_models)
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
        model = get_fit_model(self.model_key(), self._custom_models)
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
