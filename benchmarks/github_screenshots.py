"""Capture the real JASC GUI with synthetic data; no packaging or user settings.

From the repository root, run: python -B benchmarks/github_screenshots.py
Requires the normal application dependencies. PNGs go to docs/screenshots.
The generated artifacts/github_screenshots/demo.jasc can also be opened in JASC.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "1"

from matplotlib import font_manager
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

from benchmarks.gallery_demo import create_demo
from benchmarks.gallery_workflows import capture_more
from core import project_io
from jasc_api import Session
from models.plot_settings import AxisSettings, LegendSettings
from ui.dialogs import FitDialog, select_list_items
from ui.main_window import MainWindow

OUTPUT = ROOT / "docs" / "screenshots"


def settle() -> None:
    """Allow the real Qt layout, dock timers and Matplotlib draws to finish."""
    QApplication.processEvents()
    QTest.qWait(450)
    QApplication.processEvents()


def capture(widget: QWidget, name: str) -> dict[str, object]:
    settle()
    pixmap = widget.grab()
    path = OUTPUT / name
    if not pixmap.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save {path}")
    print(f"Captured {name}: {pixmap.width()} x {pixmap.height()}", flush=True)
    return {"file": name, "width": pixmap.width(), "height": pixmap.height(),
            "bytes": path.stat().st_size}


def fit_dialog(window: MainWindow, names: list[str]) -> FitDialog:
    columns = ["wavelength_nm", "intensity", "sigma"]
    dialog = FitDialog(columns, "Sample A_fit", default_x_column="wavelength_nm",
                       dataset_names=names, current_dataset_name="Sample A", parent=window,
                       dataset_columns={name: columns for name in names})
    dialog._model_category_combo.setCurrentIndex(0)
    dialog._model_combo.setCurrentIndex(dialog._model_combo.findData("gaussian"))
    select_list_items(dialog._y_column_list, ["intensity"])
    select_list_items(dialog._weight_column_list, ["sigma"])
    dialog._absolute_sigma_checkbox.setChecked(True)
    for row, (seed, low, high) in enumerate(((7, 0, 20), (560, 530, 610), (7.5, 1, 20), (.2, -1, 2))):
        for column, value in enumerate((seed, low, high), 1):
            dialog._parameter_table.item(row, column).setText(str(value))
    dialog._target_dataset_edit.setText("Fit A")
    dialog.show()
    dialog.resize(1220, 820)
    return dialog


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="jasc-gallery-settings-") as settings_dir:
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir)
        app = QApplication(sys.argv[:1])
        app.setStyle(QStyleFactory.create("Fusion"))
        for font in (Path(font_manager.__file__).parent / "mpl-data" / "fonts" / "ttf").glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont("DejaVu Sans", 10))
        window = MainWindow()
        print("Calculating synthetic spectra and Raman map...", flush=True)
        demo = create_demo(Session(window._workspace))
        manager = window._plot_tab_widget
        manager.set_workspace(window._workspace)
        window._refresh_dataset_list("Sample A")
        window._refresh_plot_list()
        window._refresh_spectral_analysis_list(demo.analysis.name)
        for plot in demo.plots:
            manager.open_plot(plot.name)
        manager.open_plot(demo.comparison.name)
        manager.open_plot(demo.plots[0].name)
        window._tabs.setCurrentWidget(manager)
        window._workspace_nav_tabs.setCurrentWidget(window._plot_nav_page)
        window.show()
        window.resize(1660, 1040)
        settle()
        manager.flush()
        project_path = ROOT / "artifacts" / "github_screenshots" / "demo.jasc"
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project_io.save_project(window._workspace, project_path)
        manager.mark_saved()
        images = [capture(window, "01-workspace.png")]

        manager.open_plot(demo.comparison.name)
        manager._active_editor.set_plot_options_visible(False)
        images.append(capture(window, "02-comparison.png"))

        dialog = fit_dialog(window, [sample.name for sample in demo.samples])
        images.append(capture(dialog, "03-curve-fit.png"))
        dialog.close()
        dialog.deleteLater()

        window._show_spectral_analysis(demo.analysis)
        window.resize(1880, 1080)
        viewer = window._spectral_analysis_viewer
        peak_index = viewer._peak_selector.findData("peak_1")
        if peak_index < 0:
            raise RuntimeError("The Raman peak selector has no calculated peak.")
        viewer._peak_selector.setCurrentIndex(peak_index)
        metric_index = viewer._metric_selector.findData("peak_1_position")
        if metric_index < 0:
            raise RuntimeError("The fitted Raman peak position is missing.")
        viewer._metric_selector.setCurrentIndex(metric_index)
        for index, key in enumerate(viewer._spectrum_keys):
            coordinates = dict(key)
            if coordinates.get("X") == 9 and coordinates.get("Y") == 7:
                viewer._spectrum_selector.setCurrentIndex(index)
                break
        viewer._plot_titles["map"] = r"Raman peak position (cm$^{-1}$)"
        viewer._axis_settings[("map", "x")] = AxisSettings(label="X position (µm)")
        viewer._axis_settings[("map", "y")] = AxisSettings(label="Y position (µm)")
        viewer._axis_settings[("spectrum", "x")] = AxisSettings(label=r"Raman shift (cm$^{-1}$)")
        viewer._axis_settings[("spectrum", "y")] = AxisSettings(label="Intensity (a.u.)")
        viewer._curve_visibility.update({"corrected": False, "observed": False,
                                         "preprocessing_baseline": False, "peak_1": False})
        viewer._legend_settings = LegendSettings(font_size=10, columns=1, frame_enabled=False)
        viewer._show_diagnostics.setChecked(True)
        viewer._detail_tabs.setCurrentIndex(0)
        viewer._redraw()
        if viewer._map_axis is None or len(viewer._map_points) != 252:
            raise RuntimeError("The Raman viewer did not render the complete spatial map.")
        images.append(capture(window, "04-raman-analysis.png"))
        more_images, checks = capture_more(window, project_path.parent, capture)
        images.extend(more_images)
        (OUTPUT / "capture.json").write_text(json.dumps({
            "data": "Synthetic spectra, raster charts, signals, spatial fields and study data; no experimental data",
            "seed": 20261112, "weighted_fit_r_squared": demo.fit_r_squared,
            "raman_pixels": len(demo.analysis.metrics_frame), "checks": checks, "images": images,
        }, indent=2) + "\n", encoding="utf-8")
        with patch.object(window, "_confirm_project_plot_changes", return_value=True):
            window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == "__main__":
    main()
