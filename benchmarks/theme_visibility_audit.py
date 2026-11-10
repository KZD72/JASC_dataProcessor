"""Capture current theme visibility without modifying application styling.

Run with the project interpreter: python -B benchmarks/theme_visibility_audit.py
Outputs real Qt screenshots and palette/contrast evidence under artifacts.
The controlled dark/mixed palettes are reproductions, not captures of OS settings.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib import font_manager
import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QRadioButton, QStyleFactory, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.plot_comparison import comparison_state
from ui.main_window import MainWindow
from ui.plot_canvas import PlotSeries


def contrast(first: str, second: str) -> float:
    def luminance(value: str) -> float:
        color = QColor(value)
        channels = [part / 12.92 if part <= .04045 else ((part + .055) / 1.055) ** 2.4
                    for part in (color.redF(), color.greenF(), color.blueF())]
        return sum(part * weight for part, weight in zip(channels, (.2126, .7152, .0722)))
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return round((high + .05) / (low + .05), 3)


def palette_for(profile: str, standard: QPalette) -> QPalette:
    palette = QPalette(standard)
    if profile == "light":
        return palette
    colors = {"Window": "#252a32", "WindowText": "#e5e9ef", "Base": "#171c23",
              "AlternateBase": "#20262e", "Text": "#e5e9ef", "Button": "#303844",
              "ButtonText": "#e5e9ef", "Highlight": "#3978b8", "HighlightedText": "#ffffff",
              "ToolTipBase": "#303844", "ToolTipText": "#e5e9ef"}
    if profile == "mixed_dark":
        colors.update(Base="#ffffff", Button="#efefef", ButtonText="#101820")
    for role, value in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(value))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#7b8594"))
    return palette


def gallery(parent: MainWindow, title: str) -> tuple[QDialog, dict[str, object]]:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(1080, 640)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(title + " — current application stylesheet"))
    controls = QGroupBox("Indicators and interaction states")
    grid = QGridLayout(controls)
    probes: dict[str, object] = {}
    for column, heading in enumerate(("State", "Checkbox", "Radio", "Toggle button", "Field")):
        grid.addWidget(QLabel(heading), 0, column)
    states = (("Unchecked", Qt.Unchecked, True), ("Checked", Qt.Checked, True),
              ("Partially checked", Qt.PartiallyChecked, True),
              ("Disabled unchecked", Qt.Unchecked, False), ("Disabled checked", Qt.Checked, False))
    for row, (name, state, enabled) in enumerate(states, 1):
        grid.addWidget(QLabel(name), row, 0)
        check = QCheckBox("Enable option")
        check.setTristate(state == Qt.PartiallyChecked)
        check.setCheckState(state)
        radio = QRadioButton("Use option")
        radio.setAutoExclusive(False)
        radio.setChecked(state == Qt.Checked)
        toggle = QPushButton("Pan")
        toggle.setCheckable(True)
        toggle.setChecked(state == Qt.Checked)
        field = QLineEdit("Example value")
        for column, widget in enumerate((check, radio, toggle, field), 1):
            widget.setEnabled(enabled)
            grid.addWidget(widget, row, column)
        probes[name] = {"checkbox": check, "button": toggle, "field": field}
    layout.addWidget(controls)
    lower = QHBoxLayout()
    choices = QListWidget()
    for index, name in enumerate(("Checked and selected", "Unchecked", "Checked")):
        item = QListWidgetItem(name)
        item.setCheckState(Qt.Unchecked if index == 1 else Qt.Checked)
        choices.addItem(item)
    choices.setCurrentRow(0)
    lower.addWidget(choices)
    table = QTableWidget(3, 3)
    table.setHorizontalHeaderLabels(["Selected value", "Flag", "Description"])
    for row in range(3):
        for column in range(3):
            item = QTableWidgetItem(f"Row {row + 1}" if column != 1 else "")
            if column == 1:
                item.setCheckState(Qt.Checked if row % 2 == 0 else Qt.Unchecked)
            table.setItem(row, column, item)
    table.selectRow(0)
    lower.addWidget(table)
    layout.addLayout(lower)
    combo = QComboBox()
    combo.addItems(["Active choice", "Alternative choice"])
    layout.addWidget(combo)
    probes["choices"] = choices
    return dialog, probes


def probe_colors(probes: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, widgets in probes.items():
        if not isinstance(widgets, dict):
            continue
        group = QPalette.Disabled if name.startswith("Disabled") else QPalette.Active
        result[name] = {}
        for kind, widget in widgets.items():
            role = QPalette.ButtonText if kind == "button" else QPalette.Text if kind == "field" else QPalette.WindowText
            background = QPalette.Button if kind == "button" else QPalette.Base if kind == "field" else QPalette.Window
            front = widget.palette().color(group, role).name()
            back = widget.palette().color(group, background).name()
            result[name][kind] = {"text": front, "background_role": back,
                                  "contrast_ratio": contrast(front, back)}
    off = probes["Unchecked"]["button"].grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    on = probes["Checked"]["button"].grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    result["toggle_off_on_raster_equal"] = off.size() == on.size() and bytes(off.constBits()) == bytes(on.constBits())
    return result


def capture_comparison(window: MainWindow, folder: Path) -> dict[str, object]:
    manager = window._plot_tab_widget
    data = window._workspace.add_dataset("map", pd.DataFrame({
        "x": [0., 1., 0., 1.], "y": [0., 0., 1., 1.], "z": [1., 2., 3., 4.]}))
    identities = []
    for name in ("Reference map", "Sample map"):
        manager.queue_plot_series([PlotSeries(data.name, "x", data.name, "y", z_dataset=data.name,
                                               z_column="z", plot_type="heatmap")], name, "X", "Y")
        identities.append(manager.active_document.plot_id)
    manager.new_comparison("Dark image comparison", comparison_state(identities, 1, 2, match_x=True, match_y=True),
                           pop_out=True)
    view = manager._active_editor
    popup = manager._popouts[view]
    popup.resize(1350, 750)
    QTest.qWait(120)
    popup.grab().save(str(folder / "dark_comparison.png"))
    readout = view._panels[0][1].coordinate_readout
    foreground = readout.palette().color(QPalette.WindowText).name()
    background = readout.palette().color(QPalette.Window).name()
    return {"readout_text": foreground, "readout_background": background,
            "readout_contrast": contrast(foreground, background)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "theme_visibility")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(font_manager.findfont("DejaVu Sans"))
    app.setFont(QFont("DejaVu Sans", 10))
    results: dict[str, object] = {"platform": app.platformName(), "profiles": {}, "control_styles": []}
    for style in ("Fusion", "windowsvista"):
        if style not in QStyleFactory.keys():
            continue
        app.setStyle(style)
        standard = app.style().standardPalette()
        results["control_styles"].append(style)
        for profile in ("light", "dark", "mixed_dark"):
            app.setPalette(palette_for(profile, standard))
            window = MainWindow()
            dialog, probes = gallery(window, f"{style} / {profile}")
            dialog.show()
            QTest.qWait(50)
            probes["choices"].setFocus()
            dialog.grab().save(str(args.output / f"{style}_{profile}.png"))
            key = f"{style}_{profile}"
            results["profiles"][key] = probe_colors(probes)
            if style == "Fusion" and profile == "dark":
                dialog.hide()
                results["dark_comparison"] = capture_comparison(window, args.output)
            dialog.close()
            dialog.deleteLater()
            with patch.object(window, "_confirm_project_plot_changes", return_value=True):
                window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            gc.collect()
    from ui.theme import theme_colors
    colors = theme_colors(app.palette(), dark=False)
    results["light_qss_pairs"] = {"editor_border_white": contrast(colors["border"], colors["base"]),
                                   "button_border_white": contrast(colors["border"], colors["button"]),
                                   "disabled_button_text": contrast(colors["disabled_text"], colors["disabled_bg"])}
    (args.output / "measurements.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "screenshots": len(list(args.output.glob("*.png"))),
                      "dark_comparison": results.get("dark_comparison"),
                      "light_qss_pairs": results["light_qss_pairs"]}, indent=2))


if __name__ == "__main__":
    main()
