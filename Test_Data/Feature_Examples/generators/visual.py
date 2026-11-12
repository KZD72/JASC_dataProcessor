"""Plotting and digitizer fixtures generated with standard scientific plotting."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .common import csv, inputs, truth


def generate_visual(root: Path) -> None:
    directory = inputs(root, "11_Plots_and_Maps")
    x = np.linspace(0, 10, 101)
    csv(directory/"curves.csv", pd.DataFrame({"x": x, "sine": np.sin(x), "cosine": np.cos(x),
                                             "sigma": np.full(len(x), .1), "right_scale": 100*np.cos(x)}))
    csv(directory/"categories.csv", pd.DataFrame({"label": ["A", "B", "C", "D"], "value": [1, 2, 3, 4]}))
    xx, yy = np.meshgrid(np.linspace(-2, 2, 21), np.linspace(-2, 2, 21))
    csv(directory/"map.csv", pd.DataFrame({"x": xx.ravel(), "y": yy.ravel(),
                                          "z": (4 - xx*xx - yy*yy).ravel()}))
    # A deterministic sparse subset retains corners and the center.
    full = pd.DataFrame({"x": xx.ravel(), "y": yy.ravel(), "z": (4 - xx*xx - yy*yy).ravel()})
    csv(directory/"scattered_map.csv", full.iloc[sorted(set(range(0, 441, 7)) | {0, 20, 220, 420, 440})])
    shift = np.linspace(200, 280, 41)
    spectra = []
    for sy in range(3):
        for sx in range(3):
            spectra.append(pd.DataFrame({"X": sx, "Y": sy, "shift": shift,
                "Intensity": 2 + (5 + sx + sy)*np.exp(-.5*((shift - 240)/6)**2)}))
    csv(directory/"spectral_map.csv", pd.concat(spectra, ignore_index=True))
    truth(directory, {"curve_rows": 101, "category_sum": 10, "category_fractions": [.1, .2, .3, .4],
        "map_rows": 441, "map_formula": "4-x*x-y*y", "map_maximum": {"x": 0, "y": 0, "z": 4},
        "horizontal_zero": "4-x*x", "vertical_zero": "4-y*y"})

    directory = inputs(root, "12_Image_Digitization")
    fig = Figure(figsize=(8, 5), dpi=120)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([.12, .15, .78, .75])
    x = np.linspace(0, 10, 201)
    ax.plot(x, 2*x + 3, color="#1565c0", linewidth=2)
    ax.scatter(np.arange(1, 10), 2*np.arange(1, 10) + 3, color="#c62828", s=30, zorder=3)
    ax.set(xlim=(0, 10), ylim=(0, 25), xlabel="X", ylabel="Y", title="Known line: y = 2x + 3")
    fig.savefig(directory/"linear_curve.png", dpi=120, facecolor="white")
    csv(directory/"linear_truth.csv", pd.DataFrame({"x": x, "y": 2*x + 3}))
    fig.clear()
    ax = fig.add_axes([.12, .15, .78, .75])
    x = np.geomspace(1, 100, 201)
    ax.loglog(x, 3*np.sqrt(x), color="#1565c0", linewidth=2)
    ax.set(xlim=(1, 100), ylim=(1, 100), xlabel="X (log)", ylabel="Y (log)", title="Power law: y = 3 sqrt(x)")
    fig.savefig(directory/"log_curve.png", dpi=120, facecolor="white")
    fig.clear()
    ax = fig.add_axes([.12, .15, .65, .75])
    color_ax = fig.add_axes([.83, .15, .035, .75])
    x, y = np.meshgrid(np.linspace(-2, 2, 201), np.linspace(-2, 2, 201))
    im = ax.imshow(np.exp(-x*x - y*y), origin="lower", extent=(-2, 2, -2, 2),
                   cmap="viridis", vmin=0, vmax=1, aspect="auto")
    ax.set(xlabel="X", ylabel="Y", title="Known colour field: exp(-x*x-y*y)")
    fig.colorbar(im, cax=color_ax, label="Z")
    fig.savefig(directory/"heatmap.png", dpi=120, facecolor="white")
    truth(directory, {"image_size_pixels": [960, 600], "linear_formula": "2*x+3",
        "linear_x_reference_pixels": [[115.2, 510], [864, 510]], "linear_x_reference_values": [0, 10],
        "linear_y_reference_pixels": [[115.2, 510], [115.2, 60]], "linear_y_reference_values": [0, 25],
        "linear_check": {"x": 5, "y": 13, "suggested_y_tolerance": .2},
        "log_formula": "3*sqrt(x)", "log_check": {"x": 10, "y": 9.486832980505},
        "heatmap_formula": "exp(-x*x-y*y)", "heatmap_center": 1., "heatmap_color_limits": [0, 1],
        "note": "Raster picking and colour interpolation have pixel/anti-aliasing uncertainty; reference files are ground truth, not extracted observations."})
