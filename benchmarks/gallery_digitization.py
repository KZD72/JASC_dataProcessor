"""Prepare real, calibrated raster extraction dialogs for the screenshot gallery."""

from __future__ import annotations

from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSplitter, QWidget

from ui.dialogs import ColorPlotDigitizerDialog, FigureDigitizerDialog


def response(x: np.ndarray) -> np.ndarray:
    return np.exp(-x/6) * np.cos(2*np.pi*.6*x) + .15


def calibrate(dialog: FigureDigitizerDialog, pixels: dict, values: tuple) -> None:
    """Supply the same reference picks and endpoint values as the manual UI."""
    for key, value in zip(("x1", "x2", "y1", "y2"), values):
        getattr(dialog, f"_{key}_value_edit").setText(str(value))
        dialog._set_click_target(key)
        dialog._handle_canvas_click(*(coordinate * 2 for coordinate in pixels[key]))


def show_output(dialog: FigureDigitizerDialog) -> None:
    dialog._magnifier_checkbox.setChecked(False)
    dialog._controls_tabs.setCurrentWidget(dialog._output_tab)
    dialog.show()
    dialog.resize(1680, 980)
    dialog.findChildren(QSplitter)[0].setSizes([1070, 580])
    dialog._fit_image_in_view()


def curve_dialog(directory: Path, parent: QWidget) -> tuple[FigureDigitizerDialog, dict]:
    """Trace rendered pixels, then check the extracted values against analytic truth."""
    directory.mkdir(parents=True, exist_ok=True)
    figure = Figure(figsize=(9.6, 6), dpi=200, facecolor="white")
    canvas = FigureCanvasAgg(figure)
    axis = figure.add_axes([.12, .15, .78, .75])
    x = np.linspace(0, 10, 1500)
    axis.plot(x, response(x), color="#2069a5", linewidth=2.5)
    axis.set(xlim=(0, 10), ylim=(-1, 1.3), xlabel="Time (s)", ylabel="Response (a.u.)",
             title="Oscillatory relaxation · synthetic reference figure")
    axis.grid(alpha=.15)
    canvas.draw()
    path = directory / "oscillatory_relaxation.png"
    figure.savefig(path)
    dialog = FigureDigitizerDialog(str(path), parent)
    pixels = {"x1": (115.2, 510), "x2": (864, 510), "y1": (115.2, 510), "y2": (115.2, 60)}
    calibrate(dialog, pixels, (0, 10, -1, 1.3))
    dialog._set_trace_color(QColor("#2069a5"))
    dialog._trace_mode_combo.setCurrentIndex(dialog._trace_mode_combo.findData("color"))
    dialog._color_tolerance_spin.setValue(40)
    dialog._x_step_spin.setValue(16)
    dialog._run_auto_trace()
    rows = dialog.extracted_rows()
    frame = pd.DataFrame(rows)
    error = np.abs(frame["y"].to_numpy(dtype=float) - response(frame["x"].to_numpy(dtype=float)))
    if len(rows) < 85 or float(error.max()) > .025:
        raise RuntimeError(f"Unexpected curve extraction: {len(rows)} points, max error {error.max()}")
    dialog._dataset_name_edit.setText("Recovered relaxation curve")
    frame.to_csv(directory / "recovered_curve.csv", index=False)
    show_output(dialog)
    return dialog, {"curve_points": len(rows), "curve_maximum_absolute_y_error": float(error.max())}


def colour_dialog(directory: Path, parent: QWidget) -> tuple[ColorPlotDigitizerDialog, dict]:
    """Recover X/Y/Z probes through an empirical colourbar sampled from the raster."""
    figure = Figure(figsize=(9.6, 6), dpi=200, facecolor="white")
    canvas = FigureCanvasAgg(figure)
    axis = figure.add_axes([.12, .15, .65, .75])
    color_axis = figure.add_axes([.81, .15, .025, .75])
    x, y = np.meshgrid(np.linspace(-2, 2, 241), np.linspace(-2, 2, 241))
    image = axis.imshow(np.exp(-x*x-y*y), extent=(-2, 2, -2, 2), origin="lower",
                        cmap="viridis", vmin=0, vmax=1, aspect="auto")
    axis.set(xlabel="X position (µm)", ylabel="Y position (µm)", title="Synthetic intensity map")
    figure.colorbar(image, cax=color_axis, label="Normalized intensity")
    canvas.draw()
    path = directory / "intensity_map.png"
    figure.savefig(path)
    dialog = ColorPlotDigitizerDialog(str(path), parent)
    pixels = {"x1": (115.2, 510), "x2": (739.2, 510), "y1": (115.2, 510), "y2": (115.2, 60)}
    calibrate(dialog, pixels, (-2, 2, -2, 2))
    for key, pixel in (("colorbar_low", (790, 508)), ("colorbar_high", (790, 62))):
        dialog._set_click_target(key)
        dialog._handle_canvas_click(*(coordinate * 2 for coordinate in pixel))
    dialog._set_click_target("color_probe")
    for data_x, data_y in ((0, 0), (.5, 0), (1, 0), (0, 1), (-.75, .75), (1.25, 1), (-1, -1)):
        dialog._handle_canvas_click(2*(115.2 + (data_x+2)/4*624), 2*(510 - (data_y+2)/4*450))
    frame = pd.DataFrame(dialog.extracted_rows())
    truth = np.exp(-frame["x"].to_numpy(dtype=float)**2 - frame["y"].to_numpy(dtype=float)**2)
    error = np.abs(frame["z"].to_numpy(dtype=float) - truth)
    if not frame["color_valid"].all() or float(error.max()) > .035:
        raise RuntimeError(f"Unexpected colour-probe accuracy: {error.tolist()}")
    dialog._dataset_name_edit.setText("Recovered heatmap probes")
    frame.to_csv(directory / "recovered_probes.csv", index=False)
    show_output(dialog)
    return dialog, {"colour_probes": len(frame), "colour_maximum_absolute_z_error": float(error.max())}
