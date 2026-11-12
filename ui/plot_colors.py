"""Shared plot colour presets, swatches and RGB/hex custom selection."""
from __future__ import annotations

from matplotlib.colors import to_rgba
from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QColorDialog, QComboBox, QHBoxLayout, QPushButton, QSizePolicy, QWidget


PLOT_COLOR_PRESETS: tuple[tuple[str, str], ...] = (
    ("Blue", "tab:blue"), ("Orange", "tab:orange"), ("Green", "tab:green"),
    ("Red", "tab:red"), ("Purple", "tab:purple"), ("Brown", "tab:brown"),
    ("Pink", "tab:pink"), ("Grey", "tab:gray"), ("Olive", "tab:olive"),
    ("Cyan", "tab:cyan"), ("Black", "black"), ("White", "white"),
    ("Navy", "navy"), ("Teal", "teal"), ("Turquoise", "turquoise"),
    ("Gold", "gold"), ("Magenta", "magenta"), ("Crimson", "crimson"),
    ("Slate blue", "slateblue"), ("Silver", "silver"),
)


def qt_plot_color(value: str) -> QColor:
    """Resolve Matplotlib names (including tab:/xkcd:) without Qt-name ambiguity."""
    try:
        return QColor.fromRgbF(*to_rgba(value or "C0"))
    except (TypeError, ValueError):
        return QColor()


def plot_color_icon(value: str) -> QIcon:
    """Show colour independently of theme text, with a border around pale swatches."""
    color = qt_plot_color(value)
    if not value or not color.isValid():
        return QIcon()
    pixmap = QPixmap(24, 16)
    pixmap.fill(color)
    painter = QPainter(pixmap)
    painter.setPen(QColor("#808080"))
    painter.drawRect(0, 0, 23, 15)
    painter.end()
    return QIcon(pixmap)


def choose_plot_color(value: str, parent: QWidget) -> QColor:
    """Use Qt's full picker, including RGB and HTML hex fields, without alpha edits."""
    initial = qt_plot_color(value)
    if not initial.isValid():
        initial = qt_plot_color("C0")
    return QColorDialog.getColor(initial, parent, "Choose Plot Colour",
                                 QColorDialog.ColorDialogOption.DontUseNativeDialog)


class PlotColorComboBox(QComboBox):
    """Retain string-valued colour bindings for existing plot state and recording."""

    def __init__(self, parent: QWidget | None = None, *, allow_auto: bool = True) -> None:
        super().__init__(parent)
        self.setIconSize(QSize(24, 16))
        self.setMinimumContentsLength(8)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        if allow_auto:
            self.addItem("Auto (style cycle)", "")
        for label, value in PLOT_COLOR_PRESETS:
            self.addItem(plot_color_icon(value), label, value)

    def set_color(self, value: str) -> None:
        """Restore or reuse arbitrary saved colour strings, keeping their exact value."""
        index = self.findData(value)
        if index < 0 and value:
            self.addItem(plot_color_icon(value), f"Custom ({value})", value)
            index = self.count() - 1
        if index >= 0:
            self.setItemData(index, value or "Automatic colour from the plotting style", Qt.ToolTipRole)
            self.setCurrentIndex(index)


class PlotColorSelector(QWidget):
    """Preset dropdown plus a discoverable custom picker for any solid plot colour."""

    def __init__(self, parent: QWidget | None = None, *, default: str = "", allow_auto: bool = True) -> None:
        super().__init__(parent)
        self.combo = PlotColorComboBox(self, allow_auto=allow_auto)
        self.custom_button = QPushButton("Custom...", self)
        self.custom_button.setToolTip("Choose any colour or enter RGB / HTML hex values. Applies to the selected series or locator.")
        self.custom_button.clicked.connect(self._choose_custom_color)
        self.combo.currentIndexChanged.connect(self._update_button)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.custom_button)
        self.combo.set_color(default)
        self._update_button()

    @Slot()
    def _choose_custom_color(self) -> None:
        color = choose_plot_color(str(self.combo.currentData() or ""), self)
        if color.isValid():
            self.combo.set_color(color.name(QColor.NameFormat.HexRgb))

    @Slot(int)
    def _update_button(self, _index: int = 0) -> None:
        value = str(self.combo.currentData() or "")
        self.custom_button.setIcon(plot_color_icon(value))
        self.custom_button.setIconSize(QSize(24, 16))
