"""Focused editors opened by double-clicking rendered plot elements."""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QColorDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from models.plot_settings import AxisSettings, LegendSettings


_LEGEND_LOCATIONS: tuple[tuple[str, str], ...] = (
    ("Automatic", "best"),
    ("Upper right", "upper right"),
    ("Upper left", "upper left"),
    ("Lower left", "lower left"),
    ("Lower right", "lower right"),
    ("Center right", "center right"),
    ("Center left", "center left"),
    ("Upper center", "upper center"),
    ("Lower center", "lower center"),
    ("Center", "center"),
    ("Outside right", "outside right"),
    ("Outside top", "outside top"),
    ("Outside bottom", "outside bottom"),
)

_LINE_STYLES: tuple[tuple[str, str], ...] = (
    ("Continuous", "-"),
    ("Dashed", "--"),
    ("Dotted", ":"),
    ("Dash-dot", "-."),
    ("No line", ""),
)
_MARKERS: tuple[tuple[str, str], ...] = (
    ("None", ""),
    ("Circle", "o"),
    ("Square", "s"),
    ("Triangle", "^"),
    ("Diamond", "D"),
    ("Cross", "x"),
    ("Plus", "+"),
    ("Star", "*"),
    ("Dot", "."),
)
_MATPLOTLIB_COLOURS: dict[str, str] = {
    "tab:blue": "#1f77b4",
    "tab:orange": "#ff7f0e",
    "tab:green": "#2ca02c",
    "tab:red": "#d62728",
    "tab:purple": "#9467bd",
}


class PlotSeriesAppearanceDialog(QDialog):
    """Edit the representation of one committed series from the canvas."""

    def __init__(
        self,
        series: Any,
        plot_types: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        """Build a focused type, line, marker, and colour editor."""
        super().__init__(parent)
        self.setWindowTitle("Edit Plotted Series")
        self.setModal(True)
        self.setMinimumWidth(470)

        self._plot_type_combo = QComboBox()
        for label, value in plot_types:
            self._plot_type_combo.addItem(label, value)
        self._set_combo_data(self._plot_type_combo, series.plot_type)
        self._label_edit = QLineEdit(series.custom_label)
        self._label_edit.setPlaceholderText(series.label)
        self._legend_checkbox = QCheckBox("Show this series in the legend")
        self._legend_checkbox.setChecked(series.show_in_legend)

        self._line_style_combo = QComboBox()
        for label, value in _LINE_STYLES:
            self._line_style_combo.addItem(label, value)
        self._set_combo_data(self._line_style_combo, series.line_style)
        self._line_width_spin = self._float_spin(0.0, 10.0, series.line_width, 0.2)

        self._marker_combo = QComboBox()
        for label, value in _MARKERS:
            self._marker_combo.addItem(label, value)
        self._set_combo_data(self._marker_combo, series.marker)
        self._marker_size_spin = self._float_spin(1.0, 30.0, series.marker_size, 1.0)

        self._colour = str(series.color or "")
        self._colour_button = QPushButton()
        self._colour_button.clicked.connect(self._choose_colour)
        automatic_colour_button = QPushButton("Automatic")
        automatic_colour_button.clicked.connect(self._use_automatic_colour)
        colour_row = QHBoxLayout()
        colour_row.addWidget(self._colour_button, 1)
        colour_row.addWidget(automatic_colour_button)
        self._update_colour_button()

        self._fill_alpha_spin = self._float_spin(0.0, 1.0, series.fill_alpha, 0.05)
        self._bar_width_spin = self._float_spin(0.01, 1000.0, series.bar_width, 0.1)

        self._plot_type_combo.currentIndexChanged.connect(self._update_option_state)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow("Graph type", self._plot_type_combo)
        layout.addRow("Series name", self._label_edit)
        layout.addRow("", self._legend_checkbox)
        layout.addRow("Line pattern", self._line_style_combo)
        layout.addRow("Line width", self._line_width_spin)
        layout.addRow("Symbol", self._marker_combo)
        layout.addRow("Symbol size", self._marker_size_spin)
        layout.addRow("Colour", colour_row)
        layout.addRow("Fill opacity", self._fill_alpha_spin)
        layout.addRow("Bar width", self._bar_width_spin)
        layout.addRow(buttons)
        self._update_option_state()

    @staticmethod
    def _float_spin(
        minimum: float,
        maximum: float,
        value: float,
        step: float,
    ) -> QDoubleSpinBox:
        """Return a consistently configured numeric appearance control."""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        """Select combo item data when available."""
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _update_option_state(self, _index: int = 0) -> None:
        """Enable only representation controls relevant to the selected graph type."""
        plot_type = str(self._plot_type_combo.currentData() or "line")
        uses_line = plot_type in {"line", "line_marker", "errorbar", "area"}
        uses_marker = plot_type in {"scatter", "line_marker", "errorbar"}
        uses_fill = plot_type in {"area", "bar", "barh", "histogram", "box", "violin"}
        uses_bar_width = plot_type in {"bar", "barh"}
        self._line_style_combo.setEnabled(uses_line)
        self._line_width_spin.setEnabled(uses_line)
        self._marker_combo.setEnabled(uses_marker)
        self._marker_size_spin.setEnabled(uses_marker)
        self._fill_alpha_spin.setEnabled(uses_fill)
        self._bar_width_spin.setEnabled(uses_bar_width)

    def _choose_colour(self) -> None:
        """Open the platform colour chooser and retain a Matplotlib-compatible hex value."""
        initial = QColor(_MATPLOTLIB_COLOURS.get(self._colour, self._colour or "#1f77b4"))
        colour = QColorDialog.getColor(initial, self, "Choose Series Colour")
        if colour.isValid():
            self._colour = colour.name(QColor.HexRgb)
            self._update_colour_button()

    def _use_automatic_colour(self) -> None:
        """Return colour selection to the active plotting style's colour cycle."""
        self._colour = ""
        self._update_colour_button()

    def _update_colour_button(self) -> None:
        """Show the current colour as both text and a small swatch."""
        if not self._colour:
            self._colour_button.setText("Automatic (style cycle)")
            self._colour_button.setStyleSheet("")
            return
        swatch = _MATPLOTLIB_COLOURS.get(self._colour, self._colour)
        self._colour_button.setText(self._colour)
        self._colour_button.setStyleSheet(f"background-color: {swatch};")

    def series_updates(self) -> dict[str, object]:
        """Return dataclass fields represented by the focused controls."""
        return {
            "plot_type": str(self._plot_type_combo.currentData() or "line"),
            "custom_label": self._label_edit.text().strip(),
            "show_in_legend": self._legend_checkbox.isChecked(),
            "line_style": str(self._line_style_combo.currentData() or ""),
            "line_width": self._line_width_spin.value(),
            "marker": str(self._marker_combo.currentData() or ""),
            "marker_size": self._marker_size_spin.value(),
            "color": self._colour,
            "fill_alpha": self._fill_alpha_spin.value(),
            "bar_width": self._bar_width_spin.value(),
        }


class PlotTextEditDialog(QDialog):
    """Edit one rendered plot text value, such as the figure title."""

    def __init__(
        self,
        window_title: str,
        field_label: str,
        text: str,
        parent: QWidget | None = None,
    ) -> None:
        """Build a compact single-text editor."""
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setModal(True)
        self.setMinimumWidth(420)
        self._text_edit = QLineEdit(text)
        self._text_edit.selectAll()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        layout.addRow(field_label, self._text_edit)
        layout.addRow(buttons)

    def text_value(self) -> str:
        """Return the edited text."""
        return self._text_edit.text()


class PlotAxisEditDialog(QDialog):
    """Edit one axis label, scale, range, and the shared grid setting."""

    def __init__(
        self,
        axis_name: str,
        settings: AxisSettings,
        grid_enabled: bool,
        parent: QWidget | None = None,
    ) -> None:
        """Build the focused axis editor from current inspector values."""
        super().__init__(parent)
        self.setWindowTitle(f"Edit {axis_name} Axis")
        self.setModal(True)
        self.setMinimumWidth(440)
        self._axis_name = axis_name
        self._label_edit = QLineEdit(settings.label)
        self._scale_combo = QComboBox()
        self._scale_combo.addItem("Linear", "linear")
        self._scale_combo.addItem("Log10", "log")
        scale_index = self._scale_combo.findData(settings.scale)
        if scale_index >= 0:
            self._scale_combo.setCurrentIndex(scale_index)
        self._minimum_edit = QLineEdit(settings.minimum)
        self._maximum_edit = QLineEdit(settings.maximum)
        self._minimum_edit.setPlaceholderText("Automatic")
        self._maximum_edit.setPlaceholderText("Automatic")
        self._label_size_spin = self._font_size_spin(settings.label_font_size)
        self._tick_size_spin = self._font_size_spin(settings.tick_font_size)
        self._grid_checkbox = QCheckBox("Show grid")
        self._grid_checkbox.setChecked(grid_enabled)

        range_row = QHBoxLayout()
        range_row.addWidget(self._minimum_edit)
        range_row.addWidget(QLabel("to"))
        range_row.addWidget(self._maximum_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow("Label", self._label_edit)
        layout.addRow("Label size", self._label_size_spin)
        layout.addRow("Number size", self._tick_size_spin)
        layout.addRow("Scale", self._scale_combo)
        layout.addRow("Range", range_row)
        layout.addRow("", self._grid_checkbox)
        layout.addRow(buttons)

    def axis_settings(self) -> AxisSettings:
        """Return validated axis settings represented by the controls."""
        return AxisSettings(
            label=self._label_edit.text(),
            scale=str(self._scale_combo.currentData() or "linear"),
            minimum=self._minimum_edit.text().strip(),
            maximum=self._maximum_edit.text().strip(),
            label_font_size=self._label_size_spin.value(),
            tick_font_size=self._tick_size_spin.value(),
        )

    @staticmethod
    def _font_size_spin(value: float) -> QDoubleSpinBox:
        """Return a point-size control where zero follows the active plot style."""
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 72.0)
        spin.setSingleStep(0.5)
        spin.setValue(value)
        spin.setSuffix(" pt")
        spin.setSpecialValueText("Style default")
        return spin

    def grid_enabled(self) -> bool:
        """Return the edited shared grid state."""
        return self._grid_checkbox.isChecked()

    def accept(self) -> None:  # type: ignore[override]
        """Validate optional numeric limits before closing."""
        settings = self.axis_settings()
        parsed: dict[str, float | None] = {}
        errors: list[str] = []
        for key, value in (("minimum", settings.minimum), ("maximum", settings.maximum)):
            if not value:
                parsed[key] = None
                continue
            try:
                parsed[key] = float(value)
            except ValueError:
                errors.append(f"{self._axis_name} {key} must be numeric or blank.")
        minimum = parsed.get("minimum")
        maximum = parsed.get("maximum")
        if minimum is not None and maximum is not None and minimum >= maximum:
            errors.append(f"{self._axis_name} minimum must be smaller than its maximum.")
        if settings.scale == "log":
            if minimum is not None and minimum <= 0:
                errors.append(f"{self._axis_name} minimum must be positive for a logarithmic scale.")
            if maximum is not None and maximum <= 0:
                errors.append(f"{self._axis_name} maximum must be positive for a logarithmic scale.")
        if errors:
            QMessageBox.warning(self, "Invalid Axis Settings", "\n".join(errors))
            return
        super().accept()


class PlotLegendEditDialog(QDialog):
    """Edit the same legend settings exposed by the lateral inspector."""

    def __init__(
        self,
        settings: LegendSettings,
        parent: QWidget | None = None,
    ) -> None:
        """Build a focused legend editor from current settings."""
        super().__init__(parent)
        self.setWindowTitle("Edit Legend")
        self.setModal(True)
        self.setMinimumWidth(460)

        self._enabled_checkbox = QCheckBox("Show legend")
        self._enabled_checkbox.setChecked(settings.enabled)
        self._location_combo = QComboBox()
        for label, value in _LEGEND_LOCATIONS:
            self._location_combo.addItem(label, value)
        location_index = self._location_combo.findData(settings.location)
        if location_index >= 0:
            self._location_combo.setCurrentIndex(location_index)
        self._font_size_spin = self._float_spin(5.0, 72.0, settings.font_size, 0.5, " pt")
        self._title_edit = QLineEdit(settings.title)
        self._title_size_spin = self._float_spin(
            5.0, 72.0, settings.title_font_size, 0.5, " pt"
        )
        self._columns_spin = QSpinBox()
        self._columns_spin.setRange(1, 20)
        self._columns_spin.setValue(settings.columns)
        self._frame_checkbox = QCheckBox("Show frame")
        self._frame_checkbox.setChecked(settings.frame_enabled)
        self._frame_alpha_spin = self._float_spin(
            0.0, 1.0, settings.frame_alpha, 0.05, ""
        )
        self._marker_scale_spin = self._float_spin(
            0.1, 10.0, settings.marker_scale, 0.1, ""
        )
        self._handle_length_spin = self._float_spin(
            0.0, 20.0, settings.handle_length, 0.25, ""
        )
        self._include_locators_checkbox = QCheckBox("Include locator markers")
        self._include_locators_checkbox.setChecked(settings.include_locators)
        self._include_bands_checkbox = QCheckBox("Include confidence bands")
        self._include_bands_checkbox.setChecked(settings.include_confidence_bands)
        self._enabled_checkbox.toggled.connect(self._update_enabled_state)
        self._frame_checkbox.toggled.connect(self._update_enabled_state)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        layout.addRow("", self._enabled_checkbox)
        layout.addRow("Location", self._location_combo)
        layout.addRow("Text size", self._font_size_spin)
        layout.addRow("Title", self._title_edit)
        layout.addRow("Title size", self._title_size_spin)
        layout.addRow("Columns", self._columns_spin)
        layout.addRow("", self._frame_checkbox)
        layout.addRow("Frame opacity", self._frame_alpha_spin)
        layout.addRow("Marker scale", self._marker_scale_spin)
        layout.addRow("Handle length", self._handle_length_spin)
        layout.addRow("", self._include_locators_checkbox)
        layout.addRow("", self._include_bands_checkbox)
        layout.addRow(buttons)
        self._update_enabled_state()

    @staticmethod
    def _float_spin(
        minimum: float,
        maximum: float,
        value: float,
        step: float,
        suffix: str,
    ) -> QDoubleSpinBox:
        """Return a consistently configured floating-point control."""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    def _update_enabled_state(self, _checked: bool = False) -> None:
        """Disable subordinate controls when the legend or frame is disabled."""
        enabled = self._enabled_checkbox.isChecked()
        for widget in (
            self._location_combo,
            self._font_size_spin,
            self._title_edit,
            self._title_size_spin,
            self._columns_spin,
            self._frame_checkbox,
            self._marker_scale_spin,
            self._handle_length_spin,
            self._include_locators_checkbox,
            self._include_bands_checkbox,
        ):
            widget.setEnabled(enabled)
        self._frame_alpha_spin.setEnabled(enabled and self._frame_checkbox.isChecked())

    def legend_settings(self) -> LegendSettings:
        """Return settings represented by the controls."""
        return LegendSettings(
            enabled=self._enabled_checkbox.isChecked(),
            location=str(self._location_combo.currentData() or "best"),
            font_size=self._font_size_spin.value(),
            title=self._title_edit.text(),
            title_font_size=self._title_size_spin.value(),
            columns=self._columns_spin.value(),
            frame_enabled=self._frame_checkbox.isChecked(),
            frame_alpha=self._frame_alpha_spin.value(),
            marker_scale=self._marker_scale_spin.value(),
            handle_length=self._handle_length_spin.value(),
            include_locators=self._include_locators_checkbox.isChecked(),
            include_confidence_bands=self._include_bands_checkbox.isChecked(),
        )


class PlotLegendEntryEditDialog(QDialog):
    """Rename or hide one committed series legend entry."""

    def __init__(
        self,
        label: str,
        shown: bool,
        parent: QWidget | None = None,
    ) -> None:
        """Build a compact series-legend entry editor."""
        super().__init__(parent)
        self.setWindowTitle("Edit Legend Entry")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._label_edit = QLineEdit(label)
        self._label_edit.selectAll()
        self._shown_checkbox = QCheckBox("Show this series in the legend")
        self._shown_checkbox.setChecked(shown)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        layout.addRow("Entry label", self._label_edit)
        layout.addRow("", self._shown_checkbox)
        layout.addRow(buttons)

    def entry_label(self) -> str:
        """Return the edited legend entry label."""
        return self._label_edit.text().strip()

    def entry_shown(self) -> bool:
        """Return whether the series remains included in the legend."""
        return self._shown_checkbox.isChecked()
