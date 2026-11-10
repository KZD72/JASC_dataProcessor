"""Reusable percentile-column mapping with explicit probability semantics."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QWidget, QVBoxLayout

from models.uncertainty import PercentileBounds


class ProbabilitySpinBox(QDoubleSpinBox):
    def textFromValue(self, value: float) -> str:
        return self.locale().toString(value, "f", self.decimals()).rstrip("0").rstrip(self.locale().decimalPoint())


class ReflowLabel(QLabel):
    """Keep wrapped help text tall enough inside nested form/scroll layouts."""

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        required = self.heightForWidth(max(1, event.size().width()))
        if required > 0 and self.minimumHeight() != required:
            self.setMinimumHeight(required)


class PercentileBoundsEditor(QWidget):
    changed = Signal()

    def __init__(self, axis: str, columns: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.enabled_check = QCheckBox(f"Use {axis} percentile bounds")
        self.lower_combo, self.upper_combo = QComboBox(), QComboBox()
        self.lower_probability_spin, self.upper_probability_spin = ProbabilitySpinBox(), ProbabilitySpinBox()
        self._loaded_probabilities: tuple[float, float] | None = None
        self._loaded_display: tuple[float, float] | None = None
        self.lower_probability_spin.setRange(.01, 49.99)
        self.upper_probability_spin.setRange(50.01, 99.99)
        self.lower_probability_spin.setValue(16.)
        self.upper_probability_spin.setValue(84.)
        for spin in (self.lower_probability_spin, self.upper_probability_spin):
            spin.setSuffix(" %")
            spin.setDecimals(12)
        self.lower_probability_spin.setRange(1.e-10, 50-1.e-10)
        self.upper_probability_spin.setRange(50+1.e-10, 100-1.e-10)
        self.origin_combo = QComboBox()
        self.origin_combo.addItem("Measurement / sampling quantiles", "measurement")
        self.origin_combo.addItem("Posterior quantiles (plot only)", "posterior")
        self.centre_combo = QComboBox()
        for label, value in (("Median", "median"), ("Mean (plot only)", "mean"),
                             ("Mode (plot only)", "mode"), ("Other estimate (plot only)", "estimate")):
            self.centre_combo.addItem(label, value)
        self._fields = QWidget()
        form = QFormLayout(self._fields)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.addRow("Lower bound column", self.lower_combo)
        form.addRow("Upper bound column", self.upper_combo)
        levels = QWidget()
        row = QHBoxLayout(levels)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.lower_probability_spin)
        row.addWidget(self.upper_probability_spin)
        form.addRow("Percentile levels", levels)
        form.addRow("Meaning", self.origin_combo)
        form.addRow("Central values", self.centre_combo)
        note = ReflowLabel("Medians use a quantile-normal model with Gaussian tails. "
                      "Bounds are endpoint values, not error widths.")
        self._note = note
        note.setWordWrap(True)
        form.addRow(note)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.enabled_check)
        layout.addWidget(self._fields)
        self.enabled_check.toggled.connect(self._toggle)
        for combo in (self.lower_combo, self.upper_combo, self.origin_combo, self.centre_combo):
            combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        for spin in (self.lower_probability_spin, self.upper_probability_spin):
            spin.valueChanged.connect(lambda _value: self.changed.emit())
        self._fields.setVisible(False)
        self.set_columns(columns or [])

    def _toggle(self, enabled: bool) -> None:
        self._fields.setVisible(enabled)
        self.changed.emit()

    def set_columns(self, columns: list[str]) -> None:
        for combo in (self.lower_combo, self.upper_combo):
            selected = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            combo.addItems(columns)
            if selected and selected not in columns:
                combo.addItem(selected)
            combo.setCurrentText(selected)
            combo.blockSignals(False)

    def specification(self) -> PercentileBounds | None:
        if not self.enabled_check.isChecked():
            return None
        display = self.lower_probability_spin.value(), self.upper_probability_spin.value()
        probabilities = [value/100 for value in display]
        if self._loaded_display is not None:
            for index in range(2):
                if display[index] == self._loaded_display[index]:
                    probabilities[index] = self._loaded_probabilities[index]
        return PercentileBounds(self.lower_combo.currentText(), self.upper_combo.currentText(),
                                *probabilities,
                                origin=str(self.origin_combo.currentData()), centre=str(self.centre_combo.currentData()))

    def load(self, specification: PercentileBounds | None) -> None:
        self.enabled_check.setChecked(specification is not None)
        if specification is None:
            return
        for combo, column in ((self.lower_combo, specification.lower_column), (self.upper_combo, specification.upper_column)):
            if combo.findText(column) < 0:
                combo.addItem(column)
            combo.setCurrentText(column)
        self.lower_probability_spin.setValue(specification.lower_probability*100)
        self.upper_probability_spin.setValue(specification.upper_probability*100)
        self._loaded_probabilities = specification.lower_probability, specification.upper_probability
        self._loaded_display = self.lower_probability_spin.value(), self.upper_probability_spin.value()
        self.origin_combo.setCurrentIndex(self.origin_combo.findData(specification.origin))
        self.centre_combo.setCurrentIndex(self.centre_combo.findData(specification.centre))

    def persisted_controls(self) -> dict[str, QWidget]:
        return {name: getattr(self, name) for name in ("enabled_check", "lower_combo", "upper_combo",
                                                      "lower_probability_spin", "upper_probability_spin", "origin_combo", "centre_combo")}
