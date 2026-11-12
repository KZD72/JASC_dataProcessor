"""Additional numerical demonstrations for the GitHub screenshot gallery."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.workspace import Dataset, SavedPlot
from jasc_api import Session, series


@dataclass
class ExperimentGallery:
    signal: Dataset
    signal_plot: SavedPlot
    map_plot: SavedPlot
    statistics_plot: SavedPlot
    checks: dict[str, object]


def settings(title: str, x_label: str, y_label: str, *, legend: bool = True) -> dict:
    return {
        "title": title,
        "axes": {"x": {"label": x_label, "label_font_size": 13, "tick_font_size": 11},
                 "left_y": {"label": y_label, "label_font_size": 13, "tick_font_size": 11}},
        "legend": {"enabled": legend, "location": "best", "font_size": 10,
                   "frame_enabled": False, "include_confidence_bands": False},
        "grid": {"enabled": False},
    }


def comparison(session: Session, plots: list[SavedPlot], name: str) -> SavedPlot:
    return session.compare(plots, name=name, rows=1, columns=2, panel_labels=True,
                           name_hints={plot.plot_id: plot.name for plot in plots})


def create_experiments(session: Session) -> ExperimentGallery:
    """Compute smoothing, FFT, map cuts and statistical reports with the real API."""
    rng = np.random.default_rng(20261113)
    time = np.arange(600) / 300
    clean = np.sin(2*np.pi*5*time) + .45*np.sin(2*np.pi*17*time)
    signal = session.workspace.add_dataset("Signal experiment", pd.DataFrame({
        "time_s": time, "measured": clean + rng.normal(0, .28, time.size),
    }))
    session.smooth(signal, x_column="time_s", y_column="measured", method="savgol",
                   output_column="smoothed", window_length=15, polynomial_order=3)
    fft = session.fft(signal, signal_column="measured", x_column="time_s", name="Frequency spectrum")
    positive = fft.frame[fft.frame["frequency"] > 0]
    frequencies = sorted(positive.nlargest(2, "magnitude")["frequency"].tolist())
    if not np.allclose(frequencies, [5, 17]):
        raise RuntimeError(f"Unexpected FFT peak positions: {frequencies}")
    time_plot = session.plot([
        series(x=(signal, "time_s"), y=(signal, "measured"), color="#a4b0bf",
               line_width=.9, custom_label="Measured signal"),
        series(x=(signal, "time_s"), y=(signal, "smoothed"), color="#087f8c",
               line_width=1.9, custom_label="Savitzky–Golay"),
    ], name="Noise reduction", settings=settings("Noise reduction", "Time (s)", "Signal (V)"))
    fft_settings = settings("Recover the frequency components", "Frequency (Hz)", "Magnitude", legend=False)
    fft_settings["axes"]["x"].update(minimum="0", maximum="30")
    frequency_plot = session.plot([
        series(x=(fft, "frequency"), y=(fft, "magnitude"), color="#8156a7", line_width=1.8),
    ], name="FFT components", settings=fft_settings)
    signal_plot = comparison(session, [time_plot, frequency_plot], "Signal processing")

    x, y = np.meshgrid(np.linspace(-4, 4, 81), np.linspace(-3, 3, 61))
    z = (np.exp(-((x+.8)**2/2.6 + (y-.35)**2/1.7))
         + .65*np.exp(-((x-1.7)**2/.65 + (y+1.1)**2/.85)))
    spatial = session.workspace.add_dataset("Spatial field", pd.DataFrame({
        "x": x.ravel(), "y": y.ravel(), "intensity": z.ravel(),
    }))
    map_series = series(x=(spatial, "x"), y=(spatial, "y"), z=(spatial, "intensity"),
                        plot_type="contourf", surface_render_mode="native", surface_aspect="auto",
                        color_map="viridis", colorbar_label="Normalized intensity",
                        contour_overlay=True, contour_level_count=8, contour_labels=False,
                        contour_line_color="#ffffff", contour_line_width=.6,
                        show_global_maximum=True, extrema_label_mode="z")
    image = session.plot([map_series], name="Spatial intensity", settings=settings(
        "Spatial field and contours", "X position (µm)", "Y position (µm)", legend=False))
    cut = session.map_analysis(map_series, operation="horizontal", parameters=[0.], name="Map line profile")
    roi = session.map_analysis(map_series, operation="roi", parameters=[-2., 0., -.5, 1.5], name="Map ROI statistics")
    profile = session.plot([
        series(x=(cut, "distance"), y=(cut, "z"), color="#087f8c", line_width=2.3,
               custom_label="Horizontal cut at Y = 0 µm"),
    ], name="Horizontal profile", settings=settings(
        "Extract a numerical line profile", "X position (µm)", "Normalized intensity"))
    map_plot = comparison(session, [image, profile], "Maps and line profiles")

    study = session.workspace.add_dataset("Comparison study", pd.DataFrame({
        "sample": np.arange(1, 61), "Control": rng.normal(5, .55, 60),
        "Treatment A": rng.normal(6.1, .65, 60), "Treatment B": rng.normal(7.3, .5, 60),
        "concentration": np.linspace(0, 10, 60),
    }))
    study.frame["response"] = 2.4*study.frame["concentration"] + 1.2 + rng.normal(0, 1.1, 60)
    summary = session.statistics(study, operation_key="multi_complete",
                                 columns=["Control", "Treatment A", "Treatment B"], name="Statistics report")
    regression = session.statistics(study, operation_key="pair_linear_regression",
                                    primary_column="concentration", secondary=study,
                                    secondary_column="response", name="Regression report")
    fit = session.fit(study, x_column="concentration", y_column="response", model_key="linear",
                      method="trf", initial_parameters=[2, 1], curve_name="Calibration fit",
                      create_residuals=False)
    distribution = session.plot([
        series(x=(study, "sample"), y=(study, "Control"), plot_type="violin",
               distribution_columns=("Control", "Treatment A", "Treatment B"), color="#087f8c",
               distribution_show_median=True, distribution_show_mean=True),
    ], name="Group distributions", settings=settings(
        "Compare response distributions", "Group (1: control, 2: A, 3: B)", "Response (a.u.)", legend=False))
    calibration = session.plot([
        series(x=(study, "concentration"), y=(study, "response"), plot_type="scatter",
               marker="o", marker_size=4.5, color="#8156a7", custom_label="Observations"),
        series(x=(fit.curve, "fit_x"), y=(fit.curve, "fit_y"), color="#253f65",
               line_width=2, lower_column="fit_lower", upper_column="fit_upper",
               custom_label="Linear fit (95% band)"),
    ], name="Calibration regression", settings=settings(
        "Fit a calibration curve", "Concentration (a.u.)", "Response (a.u.)"))
    statistics_plot = comparison(session, [distribution, calibration], "Statistics and regression")
    if abs(fit.report.parameters[0] - 2.4) > .15:
        raise RuntimeError("The synthetic calibration fit did not recover the expected slope.")
    return ExperimentGallery(signal, signal_plot, map_plot, statistics_plot, {
        "experiment_seed": 20261113, "fft_peak_frequencies_hz": frequencies,
        "map_profile_rows": len(cut.frame),
        "map_roi_rows": len(roi.frame), "statistics_report_rows": len(summary.frame),
        "regression_report_rows": len(regression.frame),
        "calibration_slope": float(fit.report.parameters[0]),
    })
