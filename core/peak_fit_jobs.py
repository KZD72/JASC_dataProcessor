"""Detached Peak/Raman batch fitting; no Qt or live workspace access."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import time

import numpy as np
import pandas as pd

from core.jobs import JobCancelled, JobContext
from core.spectral_analysis import SpectralAnalysisSession
from core.workspace import Dataset, set_dataset_operation_comments
from math_engine.baseline import BaselineParameters, correct_baseline
from math_engine.calculus import MathOperationError, validate_numeric_column_metadata
from math_engine.composite_peak_fit import (
    CompositeFitParameters, CompositeFitResult, PeakComponentSpec,
    build_peak_component_spec, fit_composite_peaks,
)
from math_engine.peak_detection import PeakDetectionParameters, PeakRecord, detect_peaks


@dataclass(frozen=True, slots=True)
class PeakFitSource:
    """Independent projection of one source worksheet, captured on the GUI thread."""

    name: str
    frame: pd.DataFrame


@dataclass(frozen=True, slots=True)
class PeakFitRequest:
    """Reviewed settings and detached inputs; never retain a dialog in a worker."""

    scope: str
    source_dataset: str
    sources: tuple[PeakFitSource, ...]
    components: tuple[PeakComponentSpec, ...]
    baseline: BaselineParameters
    detection: PeakDetectionParameters
    fit: CompositeFitParameters
    x_column: str
    y_column: str
    analysis_range: tuple[float, float] | None
    tolerance: float
    analysis_name: str
    profile: dict[str, object]
    detail: dict[str, str]
    signal_name: str | None = None
    peak_name: str | None = None
    fit_name: str | None = None
    parameter_name: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedPeakFit:
    """Complete result to publish together, or discard entirely on cancellation."""

    analysis: SpectralAnalysisSession
    worksheets: tuple[Dataset, ...]
    successes: int
    failures: int


def _source_jobs(
    request: PeakFitRequest, context: JobContext,
) -> tuple[int, Iterator[tuple[str, pd.DataFrame, dict[str, float]]]]:
    context.report(0, 0, "Preparing peak-fit spectra...")
    if request.scope == "batch":
        return len(request.sources), ((source.name, source.frame, {}) for source in request.sources)
    if request.scope != "map" or len(request.sources) != 1:
        raise MathOperationError("Choose a worksheet batch or one normalized X/Y map.")
    source = request.sources[0]
    for column in ("X", "Y"):
        if column not in source.frame:
            raise MathOperationError("Map fitting requires normalized X and Y coordinate columns.")
        numeric = pd.to_numeric(source.frame[column], errors="coerce")
        validate_numeric_column_metadata(source.frame, column, numeric)
        context.check_cancelled()
    grouped = source.frame.groupby(["X", "Y"], sort=False, dropna=False)
    total = grouped.ngroups

    def pixels() -> Iterator[tuple[str, pd.DataFrame, dict[str, float]]]:
        for (x_coordinate, y_coordinate), group in grouped:
            context.check_cancelled()
            yield (
                f"{source.name} [X={x_coordinate}, Y={y_coordinate}]",
                group.reset_index(drop=True),
                {"X": float(x_coordinate), "Y": float(y_coordinate)},
            )

    return total, pixels()


def prepare_peak_fit(context: JobContext, request: PeakFitRequest) -> PreparedPeakFit:
    """Fit each spectrum independently and assemble all output before publication.

    Cancellation propagates past per-spectrum failure handling. A failed pixel
    remains visible in metrics/QC while compatible pixels continue fitting.
    """
    total, jobs = _source_jobs(request, context)
    if not total:
        raise MathOperationError("No compatible batch or map jobs were selected.")
    if not request.components:
        raise MathOperationError("Enable at least one fit component.")
    if request.fit_name is not None and request.parameter_name is None:
        raise MathOperationError("Choose a parameter worksheet name for optional fit output.")
    scope = request.scope
    template_specs = list(request.components)
    baseline_parameters, detection_parameters = request.baseline, request.detection
    fit_parameters, analysis_range = request.fit, request.analysis_range
    x_column, y_column, tolerance = request.x_column, request.y_column, request.tolerance
    detail = request.detail
    worksheets: list[Dataset] = []

    def stage_dataset(name: str, frame: pd.DataFrame, *, copy_frame: bool = False) -> Dataset:
        dataset = Dataset(name=name, frame=frame.copy(deep=True) if copy_frame else frame)
        worksheets.append(dataset)
        return dataset

    signal_frames: list[pd.DataFrame] = []
    peak_frames: list[pd.DataFrame] = []
    fit_frames: list[pd.DataFrame] = []
    parameter_frames: list[pd.DataFrame] = []
    analysis_curve_frames: list[pd.DataFrame] = []
    analysis_peak_frames: list[pd.DataFrame] = []
    analysis_parameter_frames: list[pd.DataFrame] = []
    map_parameter_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for job_index, (source_name, frame, coordinates) in enumerate(jobs, start=1):
        context.report(job_index - 1, total, f"Peak fit {job_index}/{total}: {source_name}")
        started = time.perf_counter()
        try:
            if x_column not in frame or y_column not in frame:
                raise MathOperationError(
                    f"Required columns '{x_column}' and '{y_column}' were not found."
                )
            x_numeric = pd.to_numeric(frame[x_column], errors="coerce")
            y_numeric = pd.to_numeric(frame[y_column], errors="coerce")
            validate_numeric_column_metadata(frame, x_column, x_numeric)
            validate_numeric_column_metadata(frame, y_column, y_numeric)
            x_values = x_numeric.to_numpy(dtype=float)
            y_values = y_numeric.to_numpy(dtype=float)
            if analysis_range is not None:
                lower, upper = analysis_range
                outside = (x_values < lower) | (x_values > upper)
                x_values = x_values.copy()
                y_values = y_values.copy()
                x_values[outside] = np.nan
                y_values[outside] = np.nan
            context.check_cancelled()
            baseline = correct_baseline(
                x_values,
                y_values,
                baseline_parameters,
                provenance={"source_sheet": source_name, **coordinates},
            )
            context.check_cancelled()
            detection = detect_peaks(
                baseline.x,
                baseline.raw,
                baseline.corrected,
                detection_parameters,
                source_sheet=source_name,
                channel=y_column,
                map_coordinates=coordinates,
            )
            context.check_cancelled()
            matched = match_peak_components(
                template_specs,
                list(detection.peaks),
                baseline.x,
                tolerance,
            )
            fit = fit_composite_peaks(
                baseline.x,
                baseline.raw,
                baseline.corrected,
                matched,
                fit_parameters,
                check_cancelled=context.check_cancelled,
                provenance={"source_sheet": source_name, **coordinates},
            )
            context.check_cancelled()
            common = {"source_sheet": source_name, **coordinates}
            analysis_curve = fit.fit_frame.rename(
                columns={"baseline": "fit_baseline"}
            ).copy()
            preprocessing = pd.DataFrame({
                "x": baseline.x,
                "raw": baseline.raw,
                "preprocessing_baseline": baseline.baseline,
                "corrected": baseline.corrected,
            })
            analysis_curve = preprocessing.merge(
                analysis_curve,
                on="x",
                how="inner",
                sort=False,
            )
            for name, value in reversed(list(common.items())):
                analysis_curve.insert(0, name, value)
            analysis_curve_frames.append(analysis_curve)

            analysis_peak_frame = detection.peak_frame()
            for name, value in common.items():
                if name not in analysis_peak_frame:
                    analysis_peak_frame[name] = value
            analysis_peak_frames.append(analysis_peak_frame)

            analysis_parameter_frame = fit.parameter_frame.copy()
            for name, value in common.items():
                analysis_parameter_frame[name] = value
            analysis_parameter_frame["r_squared"] = fit.r_squared
            analysis_parameter_frame["rmse"] = fit.rmse
            analysis_parameter_frame["aic"] = fit.aic
            analysis_parameter_frame["bic"] = fit.bic
            analysis_parameter_frame["status"] = "success"
            analysis_parameter_frame["error"] = ""
            analysis_parameter_frame["warnings"] = " | ".join(fit.warnings)
            analysis_parameter_frames.append(analysis_parameter_frame)
            if request.signal_name is not None:
                signal_frame = pd.DataFrame({
                    x_column: baseline.x,
                    y_column: baseline.raw,
                    f"{y_column}_baseline": baseline.baseline,
                    f"{y_column}_corrected": baseline.corrected,
                })
                for name, value in reversed(list(common.items())):
                    signal_frame.insert(0, name, value)
                signal_frames.append(signal_frame)
            if request.peak_name is not None:
                peak_frames.append(analysis_peak_frame.copy())
            if request.fit_name is not None:
                fit_frame = fit.fit_frame.copy()
                for name, value in reversed(list(common.items())):
                    fit_frame.insert(0, name, value)
                fit_frames.append(fit_frame)
                parameter_frames.append(analysis_parameter_frame.copy())
            map_parameter_rows.append(
                peak_fit_map_row(
                    fit,
                    source_name=source_name,
                    coordinates=coordinates,
                    noise_estimate=detection.noise_estimate,
                    detected_peak_count=len(detection.peaks),
                    matched_peak_count=len(matched),
                )
            )
            summary_rows.append({
                **common,
                "status": "success",
                "detected_peaks": len(detection.peaks),
                "matched_peaks": len(matched),
                "r_squared": fit.r_squared,
                "rmse": fit.rmse,
                "aic": fit.aic,
                "bic": fit.bic,
                "elapsed_seconds": time.perf_counter() - started,
                "error": "",
            })
        except JobCancelled:
            raise
        except Exception as exc:
            map_parameter_rows.append({
                "source_sheet": source_name,
                **coordinates,
                "fit_success": 0.0,
                "fit_converged": 0.0,
                "status": "failed",
                "error": str(exc),
            })
            summary_rows.append({
                "source_sheet": source_name,
                **coordinates,
                "status": "failed",
                "detected_peaks": 0,
                "matched_peaks": 0,
                "r_squared": np.nan,
                "rmse": np.nan,
                "aic": np.nan,
                "bic": np.nan,
                "elapsed_seconds": time.perf_counter() - started,
                "error": str(exc),
            })
    context.report(total, total, "Assembling peak-fit result tables...")

    detail = dict(detail)
    detail.update({
        "Application scope": "Raman map" if scope == "map" else "Worksheet batch",
        "Requested jobs": str(total),
        "Peak center matching tolerance": f"{tolerance:g}",
    })
    analysis_name = request.analysis_name
    profile = request.profile
    analysis = SpectralAnalysisSession(
        name=analysis_name,
        source_dataset=request.source_dataset,
        analysis_kind="raman_map" if scope == "map" else "spectrum_batch",
        x_column=x_column,
        y_column=y_column,
        coordinate_columns=("X", "Y") if scope == "map" else (),
        profile={"settings": profile, "provenance": detail},
        metrics_frame=pd.DataFrame(map_parameter_rows),
        curves_frame=(
            pd.concat(analysis_curve_frames, ignore_index=True)
            if analysis_curve_frames else pd.DataFrame()
        ),
        parameters_frame=(
            pd.concat(analysis_parameter_frames, ignore_index=True)
            if analysis_parameter_frames else pd.DataFrame()
        ),
        peaks_frame=(
            pd.concat(analysis_peak_frames, ignore_index=True)
            if analysis_peak_frames else pd.DataFrame()
        ),
    )
    if request.signal_name is not None and signal_frames:
        output = stage_dataset(
            request.signal_name, pd.concat(signal_frames, ignore_index=True), copy_frame=False
        )
        output.worksheet_metadata.import_details.update(detail)
        set_dataset_operation_comments(output, f"Peak Analysis {scope} corrected signals")
    if request.peak_name is not None and peak_frames:
        output = stage_dataset(
            request.peak_name, pd.concat(peak_frames, ignore_index=True), copy_frame=False
        )
        output.worksheet_metadata.import_details.update(detail)
        set_dataset_operation_comments(output, f"Peak Analysis {scope} detected peaks")
    if request.fit_name is not None:
        if fit_frames:
            output = stage_dataset(
                request.fit_name, pd.concat(fit_frames, ignore_index=True), copy_frame=False
            )
            output.worksheet_metadata.import_details.update(detail)
            set_dataset_operation_comments(output, f"Composite Peak Fit {scope} curves")
        combined_parameters = (
            pd.concat(parameter_frames, ignore_index=True)
            if parameter_frames
            else pd.DataFrame()
        )
        if summary_rows:
            summary_frame = pd.DataFrame(summary_rows)
            summary_frame["record_type"] = "fit_summary"
            if combined_parameters.empty:
                combined_parameters = summary_frame
            else:
                combined_parameters["record_type"] = "parameter"
                combined_parameters = pd.concat(
                    [combined_parameters, summary_frame], ignore_index=True, sort=False
                )
        output = stage_dataset(
            request.parameter_name, combined_parameters, copy_frame=False
        )
        output.worksheet_metadata.import_details.update(detail)
        set_dataset_operation_comments(output, f"Composite Peak Fit {scope} parameters and summary")
        if scope == "map" and map_parameter_rows:
            map_frame = pd.DataFrame(map_parameter_rows)
            coordinate_columns = [name for name in ("X", "Y") if name in map_frame]
            leading_columns = [
                name for name in ("source_sheet", *coordinate_columns)
                if name in map_frame
            ]
            map_frame = map_frame[
                leading_columns
                + [name for name in map_frame.columns if name not in leading_columns]
            ]
            map_output = stage_dataset(
                f"{request.parameter_name}_maps",
                map_frame,
                copy_frame=False,
            )
            map_output.worksheet_metadata.import_details.update(detail)
            map_output.worksheet_metadata.import_details.update({
                "Worksheet layout": "One row per X/Y pixel; numeric columns are heatmap-ready Z values",
                "Recommended plot family": "2D Maps",
            })
            for coordinate_name, role in (("X", "x"), ("Y", "y")):
                if coordinate_name in map_frame:
                    metadata = map_output.metadata_for_column(coordinate_name)
                    metadata.role = role
                    metadata.value_type = "numeric"
            for column_name in map_frame.columns:
                if column_name in {"source_sheet", "status", "error"} or column_name.endswith("_model"):
                    map_output.metadata_for_column(str(column_name)).value_type = "text"
                elif column_name not in {"X", "Y"}:
                    map_output.metadata_for_column(str(column_name)).value_type = "numeric"
            map_output.sync_column_metadata_attrs()
            set_dataset_operation_comments(
                map_output,
                "Composite Peak Fit heatmap-ready parameter maps: one row per X/Y pixel",
            )

    context.check_cancelled()
    return PreparedPeakFit(
        analysis=analysis, worksheets=tuple(worksheets),
        successes=sum(row["status"] == "success" for row in summary_rows),
        failures=sum(row["status"] == "failed" for row in summary_rows),
    )


def peak_fit_map_row(
    fit: CompositeFitResult,
    *,
    source_name: str,
    coordinates: dict[str, float],
    noise_estimate: float,
    detected_peak_count: int,
    matched_peak_count: int,
) -> dict[str, object]:
    """Flatten one fit into heatmap-ready metrics for exactly one X/Y pixel."""
    fit_frame = fit.fit_frame
    baseline_values = pd.to_numeric(fit_frame["baseline"], errors="coerce").to_numpy(
        dtype=float
    )
    finite_baseline = baseline_values[np.isfinite(baseline_values)]
    row: dict[str, object] = {
        "source_sheet": source_name,
        **coordinates,
        "fit_success": 1.0,
        "fit_converged": 1.0 if fit.converged else 0.0,
        "fit_r_squared": fit.r_squared,
        "fit_rmse": fit.rmse,
        "fit_mae": fit.mae,
        "fit_aic": fit.aic,
        "fit_bic": fit.bic,
        "fit_evaluations": float(fit.evaluations),
        "noise_estimate": float(noise_estimate),
        "detected_peak_count": float(detected_peak_count),
        "matched_peak_count": float(matched_peak_count),
        "baseline_mean": (
            float(np.mean(finite_baseline)) if finite_baseline.size else float("nan")
        ),
        "baseline_minimum": (
            float(np.min(finite_baseline)) if finite_baseline.size else float("nan")
        ),
        "baseline_maximum": (
            float(np.max(finite_baseline)) if finite_baseline.size else float("nan")
        ),
        "status": "success",
        "error": "",
        "warnings": " | ".join(fit.warnings),
    }

    baseline_parameters = fit.parameter_frame[
        fit.parameter_frame["component"] == "baseline"
    ]
    for parameter in baseline_parameters.itertuples(index=False):
        name = str(parameter.parameter)
        row[f"baseline_parameter_{name}"] = float(parameter.value)
        row[f"baseline_parameter_{name}_standard_error"] = float(
            parameter.standard_error
        )

    aliases = {
        "integrated_area": "area",
        "fitted_position": "position",
        "fitted_intensity": "intensity",
        "fitted_fwhm": "fwhm",
        "fitted_asymmetry": "asymmetry",
        "natural_linewidth": "natural_linewidth",
        "fano_peak_position": "fano_peak_position",
        "fano_dip_position": "fano_dip_position",
        "fano_peak_contrast": "fano_peak_contrast",
        "fano_dip_contrast": "fano_dip_contrast",
    }
    peak_parameters = fit.parameter_frame[
        fit.parameter_frame["component_index"] > 0
    ]
    for component_index, parameters in peak_parameters.groupby(
        "component_index", sort=True
    ):
        index = int(component_index)
        prefix = f"peak_{index}"
        first = parameters.iloc[0]
        row[f"{prefix}_model"] = str(first["model"])
        if index <= len(fit.components):
            detected_peak = fit.components[index - 1].peak
            row[f"{prefix}_snr"] = float(detected_peak.local_snr)
            row[f"{prefix}_detected_position"] = float(detected_peak.center)
        for parameter in parameters.itertuples(index=False):
            name = str(parameter.parameter)
            value = float(parameter.value)
            standard_error = float(parameter.standard_error)
            row[f"{prefix}_parameter_{name}"] = value
            row[f"{prefix}_parameter_{name}_standard_error"] = standard_error
            if str(parameter.role) == "center" and f"{prefix}_position" not in row:
                row[f"{prefix}_position"] = value
                row[f"{prefix}_position_standard_error"] = standard_error
            alias = aliases.get(name)
            if alias is not None:
                row[f"{prefix}_{alias}"] = value
                row[f"{prefix}_{alias}_standard_error"] = standard_error
        intensity = row.get(f"{prefix}_intensity")
        intensity_error = row.get(f"{prefix}_intensity_standard_error")
        if isinstance(intensity, float) and isinstance(intensity_error, float):
            row[f"{prefix}_intensity_relative_standard_error"] = (
                abs(intensity_error / intensity)
                if np.isfinite(intensity)
                and np.isfinite(intensity_error)
                and intensity != 0.0
                else float("nan")
            )
    return row

def match_peak_components(
    templates: list[PeakComponentSpec],
    candidates: list[PeakRecord],
    x_values: np.ndarray,
    tolerance: float,
) -> list[PeakComponentSpec]:
    """Match batch/map peaks by expected physical center, never prominence rank."""
    remaining = list(candidates)
    matched: list[PeakComponentSpec] = []
    for template in templates:
        compatible = [
            peak for peak in remaining if peak.polarity == template.peak.polarity
        ] or remaining
        if not compatible:
            raise MathOperationError(
                f"No detected candidate is available near {template.peak.center:g}."
            )
        candidate = min(compatible, key=lambda peak: abs(peak.center - template.peak.center))
        separation = abs(candidate.center - template.peak.center)
        if separation > tolerance:
            raise MathOperationError(
                f"Expected peak near {template.peak.center:g}, but the closest candidate "
                f"at {candidate.center:g} is outside tolerance {tolerance:g}."
            )
        remaining.remove(candidate)
        matched.append(build_peak_component_spec(candidate, template.model_key, x_values))
    return matched

