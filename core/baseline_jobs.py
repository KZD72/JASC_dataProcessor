"""Background baseline-only map correction with all output prepared off the GUI."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.jobs import JobCancelled, JobContext
from core.spectral_jobs import SpectralSource, map_spectrum_jobs
from core.workspace import Dataset, set_dataset_operation_comments
from math_engine.baseline import BaselineParameters, correct_baseline
from math_engine.calculus import MathOperationError, validate_numeric_column_metadata


@dataclass(frozen=True, slots=True)
class BaselineMapRequest:
    """Reviewed settings and independent input; no live Dataset or dialog."""

    source: SpectralSource
    x_column: str
    y_column: str
    parameters: BaselineParameters
    analysis_range: tuple[float, float] | None
    output_name: str
    detail: dict[str, str]


@dataclass(frozen=True, slots=True)
class PreparedBaselineMap:
    """A complete corrected worksheet to publish together or discard on cancel."""

    worksheet: Dataset
    successes: int
    failures: int


def prepare_baseline_map(context: JobContext, request: BaselineMapRequest) -> PreparedBaselineMap:
    """Correct map pixels sequentially and retain per-pixel failure provenance.

    Preserve strict numeric validation before running any pixel. Individual
    baseline failures do not discard successful pixels, but cancellation does.
    Native baseline calls finish before the next cancellation boundary.
    """
    context.report(0, 0, "Preparing baseline map spectra...")
    source = request.source
    x_column, y_column = request.x_column, request.y_column
    for column in dict.fromkeys((x_column, y_column)):
        context.check_cancelled()
        if column not in source.frame:
            raise MathOperationError(f"Required column '{column}' was not found.")
        numeric = pd.to_numeric(source.frame[column], errors="coerce")
        validate_numeric_column_metadata(source.frame, column, numeric)
    total, jobs = map_spectrum_jobs(source, context)
    if not total:
        raise MathOperationError("No X/Y pixel groups were found.")

    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for index, (_label, frame, coordinates) in enumerate(jobs, start=1):
        context.report(index - 1, total,
                       f"Baseline correction {index}/{total}: X={coordinates['X']:g}, Y={coordinates['Y']:g}")
        try:
            x = pd.to_numeric(frame[x_column], errors="coerce").to_numpy(dtype=float)
            raw = pd.to_numeric(frame[y_column], errors="coerce").to_numpy(dtype=float)
            if request.analysis_range is not None:
                lower, upper = request.analysis_range
                outside = (x < lower) | (x > upper)
                x, raw = x.copy(), raw.copy()
                x[outside], raw[outside] = np.nan, np.nan
            context.check_cancelled()
            result = correct_baseline(
                x, raw, request.parameters,
                provenance={"source_sheet": source.name, **coordinates},
            )
            context.check_cancelled()
            frames.append(pd.DataFrame({
                **coordinates, x_column: result.x, y_column: result.raw,
                f"{y_column}_baseline": result.baseline,
                f"{y_column}_corrected": result.corrected,
            }))
        except JobCancelled:
            raise
        except Exception as exc:
            errors.append(f"X={coordinates['X']:g}, Y={coordinates['Y']:g}: {exc}")

    context.report(total, total, "Assembling corrected map worksheet...")
    if not frames:
        raise MathOperationError(f"No map pixels were corrected successfully. First error: {errors[0]}")
    output = Dataset(name=request.output_name, frame=pd.concat(frames, ignore_index=True))
    output.worksheet_metadata.import_details.update(request.detail)
    output.worksheet_metadata.import_details.update({
        "Application scope": "Raman map", "Requested pixels": str(total),
        "Successful pixels": str(len(frames)), "Failed pixels": str(len(errors)),
        "Map errors": " | ".join(errors),
    })
    set_dataset_operation_comments(
        output, f"Baseline Correction map: source={source.name}; x={x_column}; "
                f"y={y_column}; baseline={request.parameters.method}",
    )
    context.check_cancelled()
    return PreparedBaselineMap(output, len(frames), len(errors))
