"""Shared palette colours and explicit, legible control states."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPainter, QPalette
from PySide6.QtCore import QSize


def contrast(first: QColor | str, second: QColor | str) -> float:
    def luminance(value: QColor | str) -> float:
        color = QColor(value)
        components = [part / 12.92 if part <= .04045 else ((part + .055) / 1.055) ** 2.4
                      for part in (color.redF(), color.greenF(), color.blueF())]
        return sum(part * weight for part, weight in zip(components, (.2126, .7152, .0722)))
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + .05) / (low + .05)


def readable_text(background: QColor | str, preferred: QColor | str = "#182430",
                  minimum: float = 4.5) -> str:
    if contrast(background, preferred) >= minimum:
        return QColor(preferred).name()
    return max(("#000000", "#ffffff"), key=lambda color: contrast(color, background))


def theme_colors(palette: QPalette, dark: bool | None = None) -> dict[str, str]:
    dark = palette.color(QPalette.Window).lightness() < 128 if dark is None else dark
    window = palette.color(QPalette.Window).name() if dark else "#f4f7fa"
    base = palette.color(QPalette.Base).name() if dark else "#ffffff"
    button = palette.color(QPalette.Button).name() if dark else "#ffffff"
    if dark and QColor(base).lightness() > 140:
        base = "#1b222c"
    if dark and QColor(button).lightness() > 140:
        button = "#303a48"
    highlight = palette.color(QPalette.Highlight).name() if dark else "#2467a5"
    return {
        "window": window, "base": base, "button": button,
        "text": readable_text(window, palette.color(QPalette.WindowText)),
        "input_text": readable_text(base, palette.color(QPalette.Text)),
        "button_text": readable_text(button, palette.color(QPalette.ButtonText)),
        "highlight": highlight, "highlight_text": readable_text(highlight, "#ffffff"),
        "border": "#99a8bb" if dark else "#64748b",
        "soft_border": "#68788d" if dark else "#9aa9ba",
        "panel": "#293341" if dark else "#edf2f7",
        "muted": "#b0bdcf" if dark else "#526377",
        "disabled_bg": "#2c333d" if dark else "#e6ebf0",
        "disabled_text": "#a1adbd" if dark else "#5a6b7e",
        "hover": "#384a60" if dark else "#dbeaff",
        "hover_text": "#ffffff" if dark else "#152d48",
        "alternate": "#222c38" if dark else "#f0f5fa",
        "focus": "#80bcff" if dark else "#19578f",
    }


def navigation_icon(source: QIcon, palette: QPalette, size: QSize, ratio: float) -> QIcon:
    """Retain toolbar glyph alpha while contrasting enabled and checked states."""
    colors = theme_colors(palette)
    icon = QIcon()
    original = source.pixmap(size * ratio)
    original.setDevicePixelRatio(ratio)
    for mode in (QIcon.Normal, QIcon.Active, QIcon.Disabled):
        for state in (QIcon.Off, QIcon.On):
            foreground = (colors["disabled_text"] if mode == QIcon.Disabled else
                          colors["highlight_text"] if state == QIcon.On else
                          colors["hover_text"] if mode == QIcon.Active else colors["button_text"])
            pixmap = original.copy()
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(foreground))
            painter.end()
            icon.addPixmap(pixmap, mode, state)
    return icon


def stylesheet(palette: QPalette, dark: bool | None = None) -> str:
    colors = theme_colors(palette, dark)
    glyph = "white" if colors["highlight_text"] == "#ffffff" else "black"
    asset = (Path(__file__).parent / "assets" / "theme").resolve().as_posix()
    colors.update(check=f'{asset}/check_{glyph}.svg', dash=f'{asset}/dash_{glyph}.svg',
                  disabled_check=f'{asset}/check_{"white" if QColor(colors["disabled_text"]).lightness() > 128 else "black"}.svg',
                  disabled_dash=f'{asset}/dash_{"white" if QColor(colors["disabled_text"]).lightness() > 128 else "black"}.svg',
                  up=f'{asset}/up_{"white" if QColor(colors["input_text"]).lightness() > 128 else "black"}.svg',
                  down=f'{asset}/down_{"white" if QColor(colors["input_text"]).lightness() > 128 else "black"}.svg')
    return """
        QWidget { color: %(text)s; }
        QMainWindow, QDialog { background: %(window)s; }
        QMenuBar, QMenu, QStatusBar { background: %(base)s; color: %(input_text)s; padding: 2px 4px; }
        QMenuBar::item:selected, QMenu::item:selected { background: %(highlight)s; color: %(highlight_text)s; }
        QToolBar { background: %(panel)s; border-bottom: 1px solid %(border)s; spacing: 4px; padding: 4px; }
        QDockWidget::title, QHeaderView::section { background: %(panel)s; border: 1px solid %(border)s;
            padding: 4px; font-weight: 700; }
        QPushButton, QToolButton { background: %(button)s; color: %(button_text)s;
            border: 1px solid %(border)s; border-radius: 4px; padding: 5px 10px; }
        QPushButton:hover, QToolButton:hover { background: %(hover)s; color: %(hover_text)s; border-color: %(focus)s; }
        QPushButton:checked, QToolButton:checked, QPushButton:pressed, QToolButton:pressed {
            background: %(highlight)s; color: %(highlight_text)s; border: 2px solid %(focus)s; padding: 4px 9px; }
        QPushButton:focus, QToolButton:focus { border: 2px solid %(focus)s; padding: 4px 9px; }
        QPushButton:disabled, QToolButton:disabled { background: %(disabled_bg)s; color: %(disabled_text)s;
            border: 1px solid %(soft_border)s; padding: 5px 10px; }
        QPushButton:checked:disabled, QToolButton:checked:disabled { background: %(panel)s;
            border: 2px dashed %(soft_border)s; padding: 4px 9px; font-weight: 700; }
        QLabel#SectionLabel { font-weight: 700; padding: 8px 2px 3px; }
        QLabel#MutedLabel { color: %(muted)s; background: %(window)s; }
        QWidget#PlotCanvasPanel { background: %(window)s; }
        QWidget#PlotComparisonGrid { background: white; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit,
        QAbstractItemView { background: %(base)s; color: %(input_text)s; border: 1px solid %(border)s;
            border-radius: 4px; selection-background-color: %(highlight)s; selection-color: %(highlight_text)s; }
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
        QPlainTextEdit:disabled, QTextEdit:disabled { background: %(disabled_bg)s; color: %(disabled_text)s; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QAbstractItemView:focus { border: 2px solid %(focus)s; }
        QSpinBox, QDoubleSpinBox { padding-right: 24px; }
        QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; }
        QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; }
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("%(up)s"); width: 10px; height: 7px; }
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QComboBox::down-arrow { image: url("%(down)s"); width: 10px; height: 7px; }
        QComboBox::drop-down { border: none; width: 20px; }
        QCheckBox, QRadioButton { spacing: 6px; border: 1px solid transparent; border-radius: 3px; padding: 2px; }
        QCheckBox:focus, QRadioButton:focus { border: 1px dashed %(focus)s; }
        QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled { color: %(disabled_text)s; }
        QCheckBox::indicator, QGroupBox::indicator, QAbstractItemView::indicator {
            width: 16px; height: 16px; border: 2px solid %(border)s; border-radius: 3px; background: %(base)s; }
        QCheckBox::indicator:hover, QGroupBox::indicator:hover, QAbstractItemView::indicator:hover { border-color: %(focus)s; }
        QCheckBox::indicator:checked, QGroupBox::indicator:checked, QAbstractItemView::indicator:checked {
            background: %(highlight)s; border-color: %(highlight)s; image: url("%(check)s"); }
        QCheckBox::indicator:indeterminate, QAbstractItemView::indicator:indeterminate {
            background: %(highlight)s; border-color: %(highlight)s; image: url("%(dash)s"); }
        QCheckBox::indicator:disabled, QGroupBox::indicator:disabled, QAbstractItemView::indicator:disabled {
            border-color: %(soft_border)s; background: %(disabled_bg)s; }
        QCheckBox::indicator:checked:disabled, QGroupBox::indicator:checked:disabled,
        QAbstractItemView::indicator:checked:disabled { image: url("%(disabled_check)s"); }
        QCheckBox::indicator:indeterminate:disabled, QAbstractItemView::indicator:indeterminate:disabled {
            image: url("%(disabled_dash)s"); }
        QRadioButton::indicator { width: 16px; height: 16px; border: 2px solid %(border)s;
            border-radius: 10px; background: %(base)s; }
        QRadioButton::indicator:checked { border: 6px solid %(highlight)s; width: 8px; height: 8px;
            background: %(highlight_text)s; }
        QRadioButton::indicator:disabled { border-color: %(soft_border)s; background: %(disabled_bg)s; }
        QAbstractItemView { alternate-background-color: %(alternate)s; }
        QTableView { gridline-color: %(soft_border)s; }
        QListWidget::item { padding: 4px 6px; border-radius: 3px; }
        QListWidget::item:hover { background: %(hover)s; color: %(hover_text)s; }
        QListWidget::item:selected, QTableView::item:selected { background: %(highlight)s; color: %(highlight_text)s; }
        QTabWidget::pane { border: 1px solid %(border)s; background: %(base)s; border-radius: 4px; }
        QTabBar::tab { background: %(panel)s; border: 1px solid %(border)s; border-bottom: none;
            border-top-left-radius: 4px; border-top-right-radius: 4px; padding: 6px 12px; margin-right: 2px; }
        QTabBar::tab:selected { background: %(base)s; color: %(input_text)s; font-weight: 700;
            border-top: 3px solid %(focus)s; padding-top: 4px; }
        QTabBar::tab:disabled { color: %(disabled_text)s; }
        QGroupBox { border: 1px solid %(border)s; border-radius: 5px; margin-top: 10px;
            padding: 8px; background: %(panel)s; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; font-weight: 700; }
        QToolTip { color: %(input_text)s; background: %(base)s; border: 1px solid %(border)s; padding: 4px; }
    """ % colors
