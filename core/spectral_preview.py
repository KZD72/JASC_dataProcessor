"""Detached baseline, detection, and composite-fit previews without Qt access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from core.jobs import JobContext
from core.spectral_jobs import SpectralSource
from math_engine.baseline import BaselineParameters, BaselineResult, correct_baseline
from math_engine.calculus import MathOperationError, validate_numeric_column_metadata
from math_engine.composite_peak_fit import (
    CompositeFitParameters, CompositeFitResult, PeakComponentSpec, fit_composite_peaks,
)
from math_engine.peak_detection import PeakDetectionParameters, PeakDetectionResult, detect_peaks

PreviewKind = Literal["baseline", "peaks", "fit"]


@dataclass(frozen=True, slots=True)
class SpectralPreviewRequest:
    """Independent inputs and reviewed settings for one preview generation."""

    kind: PreviewKind
    source: SpectralSource
    x_column: str
    y_column: str
    coordinates: dict[str, float]
    analysis_range: tuple[float, float] | None
    baseline_parameters: BaselineParameters
    detection_parameters: PeakDetectionParameters | None = None
    fit_parameters: CompositeFitParameters | None = None
    components: tuple[PeakComponentSpec, ...] = ()
    baseline: BaselineResult | None = None
    peaks: PeakDetectionResult | None = None


@dataclass(frozen=True, slots=True)
class SpectralPreviewResult:
    baseline: BaselineResult
    peaks: PeakDetectionResult | None = None
    fit: CompositeFitResult | None = None


def preview_source_arrays(
    context: JobContext, request: SpectralPreviewRequest,
) -> tuple[np.ndarray, np.ndarray]:
    """Validate a detached source and select exactly one representative pixel."""
    context.check_cancelled()
    frame = request.source.frame
    x_column, y_column = request.x_column, request.y_column
    if not x_column or not y_column:
        raise MathOperationError("Choose both the X axis and intensity column.")
    if x_column == y_column:
        raise MathOperationError("Choose different columns for the X axis and intensity.")
    if x_column not in frame or y_column not in frame:
        raise MathOperationError("The selected X axis or intensity column is no longer available.")
    selected = frame
    if request.coordinates:
        values = {}
        for column in ("X", "Y"):
            if column not in frame:
                raise MathOperationError("Map preview requires X and Y coordinate columns.")
            numeric = pd.to_numeric(frame[column], errors="coerce")
            validate_numeric_column_metadata(frame, column, numeric)
            values[column] = numeric.to_numpy(dtype=float)
            context.check_cancelled()
        mask = np.isclose(values["X"], request.coordinates["X"], rtol=0, atol=1e-12)
        mask &= np.isclose(values["Y"], request.coordinates["Y"], rtol=0, atol=1e-12)
        selected = frame.loc[mask]
        if selected.empty:
            raise MathOperationError("The selected X/Y preview pixel contains no rows.")
    x_numeric = pd.to_numeric(selected[x_column], errors="coerce")
    y_numeric = pd.to_numeric(selected[y_column], errors="coerce")
    validate_numeric_column_metadata(frame, x_column, x_numeric)
    validate_numeric_column_metadata(frame, y_column, y_numeric)
    x, raw = x_numeric.to_numpy(dtype=float), y_numeric.to_numpy(dtype=float)
    if request.analysis_range is not None:
        lower, upper = request.analysis_range
        outside = (x < lower) | (x > upper)
        x, raw = x.copy(), raw.copy()
        x[outside], raw[outside] = np.nan, np.nan
    context.check_cancelled()
    return x, raw


def prepare_spectral_preview(context: JobContext, request: SpectralPreviewRequest) -> SpectralPreviewResult:
    """Run native phases cooperatively and check cancellation during optimization."""
    context.report(0, 0, "Calculating baseline preview...")
    provenance = {"source_sheet": request.source.name, "x_column": request.x_column,
                  "y_column": request.y_column, **request.coordinates}
    baseline = request.baseline
    if baseline is None:
        x, raw = preview_source_arrays(context, request)
        baseline = correct_baseline(x, raw, request.baseline_parameters, provenance=provenance)
    context.check_cancelled()
    peaks = request.peaks
    if request.kind in {"peaks", "fit"} and peaks is None:
        if request.detection_parameters is None:
            raise MathOperationError("Choose peak detection parameters before previewing peaks.")
        context.report(0, 0, "Detecting peak candidates...")
        peaks = detect_peaks(
            baseline.x, baseline.raw, baseline.corrected, request.detection_parameters,
            source_sheet=request.source.name, channel=request.y_column,
            map_coordinates=request.coordinates,
            provenance={"x_column": request.x_column, "baseline": request.baseline_parameters.to_dict(),
                        **request.coordinates},
        )
    context.check_cancelled()
    fit = None
    if request.kind == "fit":
        context.report(0, 0, "Fitting reviewed components...")
        fit = fit_composite_peaks(
            baseline.x, baseline.raw, baseline.corrected, request.components,
            request.fit_parameters, provenance=provenance, check_cancelled=context.check_cancelled,
        )
    context.check_cancelled()
    return SpectralPreviewResult(baseline, peaks, fit)
