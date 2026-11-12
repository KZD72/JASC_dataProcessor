"""Deterministic, wholly synthetic experiments for the public screenshot gallery."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from core.spectral_analysis import SpectralAnalysisSession
from core.workspace import Dataset, SavedPlot
from jasc_api import Session, series
from math_engine.baseline import BaselineParameters, correct_baseline
from math_engine.composite_peak_fit import build_peak_component_spec
from math_engine.peak_detection import PeakDetectionParameters, detect_peaks


@dataclass
class GalleryDemo:
    samples: list[Dataset]
    plots: list[SavedPlot]
    comparison: SavedPlot
    analysis: SpectralAnalysisSession
    fit_r_squared: list[float]


def create_demo(session: Session) -> GalleryDemo:
    """Calculate actual weighted fits and a 252-pixel Raman analysis session."""
    rng = np.random.default_rng(20261112)
    samples, plots, reports, scores = [], [], [], []
    x = np.linspace(520, 620, 141)
    colors = ("#087f8c", "#c46a23", "#8156a7", "#27774a")
    for index, (amplitude, center, width) in enumerate(
        ((7.8, 561, 6.8), (8.4, 568, 8.5), (6.8, 575, 5.8), (9.2, 583, 9.2))
    ):
        letter = chr(65 + index)
        measured = .35 + amplitude * np.exp(-.5 * ((x - center) / width) ** 2)
        sample = session.workspace.add_dataset(f"Sample {letter}", pd.DataFrame({
            "wavelength_nm": x, "intensity": measured + rng.normal(0, .14, x.size),
            "sigma": np.full(x.size, .14),
        }))
        samples.append(sample)
        fit = session.fit(
            sample, x_column="wavelength_nm", y_column="intensity", model_key="gaussian",
            method="trf", initial_parameters=[7, center - 1, 7.5, .2],
            lower_bounds=[0, 530, 1, -1], upper_bounds=[20, 610, 20, 2],
            fixed_parameters=[False] * 4, weight_column="sigma", weight_mode="sigma",
            absolute_sigma=True, include_confidence_band=True, confidence_level=.95,
            fit_points=600, curve_name=f"Fit {letter}", create_residuals=False,
        )
        scores.append(float(fit.report.r_squared))
        reports.append(session.result_row(
            "fit_report", source_sheet=sample.name, requested_y_column="intensity",
            y_column="intensity", output_fit_sheet=fit.curve.name, result=fit,
        ))
        plots.append(session.plot([
            series(x=(sample, "wavelength_nm"), y=(sample, "intensity"),
                   plot_type="errorbar", y_err_column="sigma", line_style="",
                   marker="o", marker_size=3.6, line_width=.8, color=colors[index],
                   custom_label=f"Sample {letter} measurements"),
            series(x=(fit.curve, "fit_x"), y=(fit.curve, "fit_y"),
                   color="#253f65", line_width=2.2, custom_label="Gaussian fit",
                   lower_column="fit_lower", upper_column="fit_upper", fill_alpha=.22),
        ], name=f"Sample {letter} fit", settings={
            "title": f"Photoluminescence | Sample {letter}",
            "axes": {
                "x": {"label": "Wavelength (nm)", "minimum": "535", "maximum": "605",
                      "label_font_size": 13, "tick_font_size": 11},
                "left_y": {"label": "Emission intensity (a.u.)", "minimum": "-.3",
                           "maximum": "10.5", "label_font_size": 13, "tick_font_size": 11},
            },
            "grid": {"enabled": False},
            "legend": {"enabled": True, "location": "best", "font_size": 10,
                       "frame_enabled": False, "include_confidence_bands": False},
            "figure": {"width": 7.0, "height": 5.0},
        }))
    session.collect_rows(name="Fit reports", rows=reports, operation="Weighted Gaussian fits")
    comparison = session.compare(plots, name="Compare samples", rows=2, columns=2,
                                 match_x=True, match_y=True, panel_labels=True,
                                 name_hints={plot.plot_id: plot.name for plot in plots})
    analysis = create_raman_map(session, rng)
    return GalleryDemo(samples, plots, comparison, analysis, scores)


def create_raman_map(session: Session, rng: np.random.Generator) -> SpectralAnalysisSession:
    """Fit every pixel of a synthetic Raman peak-position map through JASC's API."""
    shift = np.linspace(505, 538, 181)
    frames = []
    for y in range(14):
        for x in range(18):
            center = 520.5 + .05 * x - .04 * y + .6 * np.exp(-((x-8)**2 + (y-6)**2)/22)
            amplitude = 40 + 20 * np.exp(-((x-8)**2 + (y-7)**2)/18) + 3*x
            width = 2.5 + .2 * np.sin(x/4)
            signal = 3 + amplitude * np.exp(-.5 * ((shift-center)/width)**2)
            frames.append(pd.DataFrame({"X": x, "Y": y, "shift": shift,
                                        "intensity": signal + rng.normal(0, .18, shift.size)}))
    sample = session.workspace.add_dataset("Raman scan", pd.concat(frames, ignore_index=True))
    baseline_settings = BaselineParameters(method="constant", constant_value=3)
    detection_settings = PeakDetectionParameters(prominence=5, maximum_count=1)
    baseline = correct_baseline(shift, frames[0]["intensity"].to_numpy(), baseline_settings)
    peaks = detect_peaks(shift, baseline.raw, baseline.corrected, detection_settings)
    component = build_peak_component_spec(peaks.peaks[0], "gaussian", shift)
    result = session.spectral_batch([sample], settings={
        "scope": "map", "source_dataset": sample.name, "components": [asdict(component)],
        "baseline": asdict(baseline_settings), "detection": asdict(detection_settings),
        "fit": {"data_mode": "raw", "baseline_model": "constant"},
        "x_column": "shift", "y_column": "intensity", "analysis_range": None,
        "tolerance": 4, "analysis_name": "Raman peak map", "profile": {}, "detail": {},
    })
    statuses = result.analysis.metrics_frame["status"].value_counts().to_dict()
    if statuses != {"success": 252}:
        raise RuntimeError(f"Unexpected Raman fit outcomes: {statuses}")
    return result.analysis
