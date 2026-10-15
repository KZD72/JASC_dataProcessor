"""Fast, physical-axis-aware peak detection for corrected spectra."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import integrate, signal

from math_engine.calculus import MathOperationError
from math_engine.spectral import (
    coordinate_at_sample,
    finite_monotonic_segments,
    is_uniform_axis,
    robust_noise_mad,
    validate_spectral_arrays,
)


PEAK_POLARITIES: dict[str, str] = {
    "positive": "Positive peaks",
    "negative": "Negative peaks",
    "both": "Positive and negative peaks",
}
PEAK_SMOOTHING_METHODS: dict[str, str] = {
    "none": "None",
    "savgol": "Savitzky-Golay",
    "moving_median": "Moving median",
}


@dataclass(frozen=True, slots=True)
class PeakDetectionParameters:
    """Serializable controls for prominence-based peak detection."""

    polarity: str = "positive"
    prominence: float | None = None
    height: float | None = None
    snr_threshold: float = 3.0
    minimum_distance_x: float = 0.0
    minimum_fwhm_x: float = 0.0
    maximum_fwhm_x: float | None = None
    maximum_count: int | None = None
    relative_height: float = 0.5
    plateau_minimum_x: float = 0.0
    smoothing_method: str = "none"
    smoothing_window: int = 7
    smoothing_polynomial_order: int = 3

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly settings for provenance and templates."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PeakRecord:
    """One detected peak with physical-coordinate measurements."""

    source_sheet: str
    channel: str
    row_index: int
    center: float
    polarity: str
    raw_height: float
    corrected_height: float
    prominence: float
    fwhm: float
    left_boundary: float
    right_boundary: float
    left_base: float
    right_base: float
    area: float
    local_snr: float
    plateau_size: float
    asymmetry: float
    detector: str = "scipy.signal.find_peaks"
    manual_status: str = "automatic"
    map_coordinates: tuple[tuple[str, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a flat row suitable for a tidy peak worksheet."""
        values = asdict(self)
        coordinates = values.pop("map_coordinates")
        for name, value in coordinates:
            values[str(name)] = value
        return values


@dataclass(frozen=True, slots=True)
class PeakDetectionResult:
    """Detected candidates plus the numerical signal used to find them."""

    x: np.ndarray
    raw: np.ndarray
    corrected: np.ndarray
    detection_signal: np.ndarray
    noise_estimate: float
    peaks: tuple[PeakRecord, ...]
    parameters: PeakDetectionParameters
    warnings: tuple[str, ...] = ()
    software_versions: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def peak_frame(self) -> pd.DataFrame:
        """Return the candidates as a tidy DataFrame."""
        rows = [peak.to_dict() for peak in self.peaks]
        columns = [
            "source_sheet", "channel", "row_index", "center", "polarity",
            "raw_height", "corrected_height", "prominence", "fwhm",
            "left_boundary", "right_boundary", "left_base", "right_base",
            "area", "local_snr", "plateau_size", "asymmetry", "detector",
            "manual_status",
        ]
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns)


def detect_peaks(
    x_values: np.ndarray,
    raw_values: np.ndarray,
    corrected_values: np.ndarray,
    parameters: PeakDetectionParameters | None = None,
    *,
    source_sheet: str = "",
    channel: str = "",
    map_coordinates: dict[str, float] | None = None,
    provenance: dict[str, Any] | None = None,
) -> PeakDetectionResult:
    """Detect positive, negative, or mixed peaks on baseline-corrected data."""
    params = parameters or PeakDetectionParameters()
    _validate_parameters(params)
    x, raw = validate_spectral_arrays(x_values, raw_values, minimum_finite=3)
    corrected_x, corrected = validate_spectral_arrays(x_values, corrected_values, minimum_finite=3)
    if not np.array_equal(x, corrected_x, equal_nan=True):
        raise MathOperationError("Raw and corrected spectra must use the same X coordinates.")

    detection_signal = np.full_like(corrected, np.nan, dtype=float)
    warnings: list[str] = []
    candidates: list[PeakRecord] = []
    finite_corrected = corrected[np.isfinite(x) & np.isfinite(corrected)]
    noise_estimate = robust_noise_mad(finite_corrected)
    effective_prominence = (
        float(params.prominence)
        if params.prominence is not None
        else float(params.snr_threshold) * noise_estimate
    )
    if effective_prominence <= 0:
        scale = float(np.nanmax(finite_corrected) - np.nanmin(finite_corrected))
        effective_prominence = max(scale * 1.0e-6, np.finfo(float).eps)
        warnings.append("Noise was zero; used a small signal-range prominence threshold.")

    coordinates = tuple((str(name), float(value)) for name, value in (map_coordinates or {}).items())
    for segment in finite_monotonic_segments(x, corrected, minimum_points=3):
        positions, segment_x, segment_corrected = segment.ascending()
        segment_raw = raw[positions]
        smoothed, smooth_warnings = _smooth_detection_signal(segment_x, segment_corrected, params)
        warnings.extend(smooth_warnings)
        detection_signal[positions] = smoothed
        for polarity in _requested_polarities(params.polarity):
            multiplier = 1.0 if polarity == "positive" else -1.0
            measured = _detect_segment(
                segment_x,
                segment_raw,
                segment_corrected,
                smoothed * multiplier,
                positions,
                polarity,
                multiplier,
                effective_prominence,
                max(noise_estimate, np.finfo(float).eps),
                params,
                source_sheet,
                channel,
                coordinates,
            )
            candidates.extend(measured)

    candidates = _prune_physical_distance(candidates, params.minimum_distance_x)
    if params.maximum_count is not None:
        candidates = sorted(
            candidates,
            key=lambda peak: (peak.prominence, abs(peak.corrected_height)),
            reverse=True,
        )[: params.maximum_count]
    candidates.sort(key=lambda peak: (peak.center, peak.polarity))
    if not candidates:
        warnings.append("No peaks met the current detection thresholds.")
    return PeakDetectionResult(
        x=x.copy(),
        raw=raw.copy(),
        corrected=corrected.copy(),
        detection_signal=detection_signal,
        noise_estimate=float(noise_estimate),
        peaks=tuple(candidates),
        parameters=params,
        warnings=tuple(dict.fromkeys(warnings)),
        software_versions={"numpy": np.__version__, "scipy": __import__("scipy").__version__},
        provenance=dict(provenance or {}),
    )


def _validate_parameters(params: PeakDetectionParameters) -> None:
    if params.polarity not in PEAK_POLARITIES:
        raise MathOperationError("Peak polarity must be positive, negative, or both.")
    if params.smoothing_method not in PEAK_SMOOTHING_METHODS:
        raise MathOperationError(f"Unknown peak-detection smoothing method: {params.smoothing_method}")
    for name, value in (
        ("Prominence", params.prominence),
        ("Height", params.height),
        ("SNR threshold", params.snr_threshold),
        ("Minimum distance", params.minimum_distance_x),
        ("Minimum FWHM", params.minimum_fwhm_x),
        ("Maximum FWHM", params.maximum_fwhm_x),
        ("Minimum plateau", params.plateau_minimum_x),
    ):
        if value is not None and value < 0:
            raise MathOperationError(f"{name} must not be negative.")
    if params.maximum_count is not None and params.maximum_count < 1:
        raise MathOperationError("Maximum peak count must be at least one.")
    if not 0 < params.relative_height < 1:
        raise MathOperationError("Relative peak-width height must be between zero and one.")


def _requested_polarities(value: str) -> tuple[str, ...]:
    return ("positive", "negative") if value == "both" else (value,)


def _smooth_detection_signal(
    x: np.ndarray,
    y: np.ndarray,
    params: PeakDetectionParameters,
) -> tuple[np.ndarray, list[str]]:
    if params.smoothing_method == "none":
        return y.copy(), []
    window = int(params.smoothing_window)
    if window < 3:
        raise MathOperationError("Peak-detection smoothing window must contain at least three points.")
    if window > len(y):
        window = len(y)
    if window % 2 == 0:
        window -= 1
    if window < 3:
        return y.copy(), ["A short finite segment was not smoothed."]
    if params.smoothing_method == "moving_median":
        return signal.medfilt(y, kernel_size=window), []
    order = int(params.smoothing_polynomial_order)
    if order < 0 or order >= window:
        raise MathOperationError("Savitzky-Golay order must be below the smoothing window.")
    warnings = [] if is_uniform_axis(x) else [
        "Savitzky-Golay smoothing uses sample positions on the irregular X axis; peak widths remain in physical units."
    ]
    return signal.savgol_filter(y, window_length=window, polyorder=order, mode="interp"), warnings


def _detect_segment(
    x: np.ndarray,
    raw: np.ndarray,
    corrected: np.ndarray,
    search_signal: np.ndarray,
    original_positions: np.ndarray,
    polarity: str,
    multiplier: float,
    prominence: float,
    noise: float,
    params: PeakDetectionParameters,
    source_sheet: str,
    channel: str,
    coordinates: tuple[tuple[str, float], ...],
) -> list[PeakRecord]:
    height = params.height if params.height is not None else None
    indices, properties = signal.find_peaks(
        search_signal,
        height=height,
        prominence=prominence,
        plateau_size=(None, None),
    )
    if indices.size == 0:
        return []
    widths, _, left_ips, right_ips = signal.peak_widths(
        search_signal,
        indices,
        rel_height=params.relative_height,
        prominence_data=(
            properties["prominences"],
            properties["left_bases"],
            properties["right_bases"],
        ),
    )
    del widths
    records: list[PeakRecord] = []
    for offset, peak_index in enumerate(indices):
        left_boundary = coordinate_at_sample(x, float(left_ips[offset]))
        right_boundary = coordinate_at_sample(x, float(right_ips[offset]))
        fwhm = abs(right_boundary - left_boundary)
        if fwhm < params.minimum_fwhm_x:
            continue
        if params.maximum_fwhm_x is not None and fwhm > params.maximum_fwhm_x:
            continue
        left_base_index = int(properties["left_bases"][offset])
        right_base_index = int(properties["right_bases"][offset])
        plateau_left = int(properties["left_edges"][offset])
        plateau_right = int(properties["right_edges"][offset])
        plateau_size = abs(float(x[plateau_right] - x[plateau_left]))
        if plateau_size < params.plateau_minimum_x:
            continue
        left_width = abs(float(x[peak_index] - left_boundary))
        right_width = abs(float(right_boundary - x[peak_index]))
        asymmetry = (
            (right_width - left_width) / (right_width + left_width)
            if right_width + left_width > 0
            else 0.0
        )
        area_x = x[left_base_index : right_base_index + 1]
        area_y = corrected[left_base_index : right_base_index + 1]
        area = float(integrate.trapezoid(area_y, area_x)) if len(area_x) >= 2 else 0.0
        corrected_height = float(corrected[peak_index])
        records.append(PeakRecord(
            source_sheet=source_sheet,
            channel=channel,
            row_index=int(original_positions[peak_index]),
            center=float(x[peak_index]),
            polarity=polarity,
            raw_height=float(raw[peak_index]),
            corrected_height=corrected_height,
            prominence=float(properties["prominences"][offset]),
            fwhm=fwhm,
            left_boundary=min(left_boundary, right_boundary),
            right_boundary=max(left_boundary, right_boundary),
            left_base=float(x[left_base_index]),
            right_base=float(x[right_base_index]),
            area=area,
            local_snr=abs(corrected_height) / noise,
            plateau_size=plateau_size,
            asymmetry=float(asymmetry),
            map_coordinates=coordinates,
        ))
    return records


def _prune_physical_distance(
    candidates: list[PeakRecord],
    minimum_distance: float,
) -> list[PeakRecord]:
    """Retain the strongest peaks separated by a physical X distance."""
    if minimum_distance <= 0 or len(candidates) < 2:
        return candidates
    ranked = sorted(
        candidates,
        key=lambda peak: (peak.prominence, abs(peak.corrected_height)),
        reverse=True,
    )
    retained: list[PeakRecord] = []
    for candidate in ranked:
        if all(abs(candidate.center - existing.center) >= minimum_distance for existing in retained):
            retained.append(candidate)
    return retained
