"""One-dimensional smoothing operations for worksheet columns."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import integrate, signal

from math_engine.calculus import MathOperationError, validate_numeric_column_metadata


SMOOTHING_METHODS: dict[str, str] = {
    "adjacent_average": "Adjacent average",
    "moving_median": "Moving median",
    "savgol": "Savitzky-Golay",
    "lowess": "LOWESS / LOESS",
    "fft": "FFT low-pass smoothing",
    "derivative_integral": "Derivative smoothing + integration",
}
DERIVATIVE_SMOOTHING_METHODS: dict[str, str] = {
    key: label
    for key, label in SMOOTHING_METHODS.items()
    if key != "derivative_integral"
}


@dataclass(frozen=True, slots=True)
class SmoothingParameters:
    """Parameters shared by the supported smoothing algorithms."""

    window_length: int = 11
    polynomial_order: int = 3
    lowess_fraction: float = 0.15
    lowess_iterations: int = 2
    fft_cutoff_fraction: float = 0.10
    derivative_smoothing_method: str = "savgol"
    derivative_median_window: int = 1
    preserve_endpoints: bool = True


@dataclass(frozen=True, slots=True)
class SmoothingResult:
    """Summary of a smoothing result written into a worksheet."""

    column_name: str
    values_written: int


def smooth_column(
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    method: str,
    target_column: str,
    parameters: SmoothingParameters,
) -> SmoothingResult:
    """Smooth aligned X/Y data and write the result at the original row indexes."""
    x, y = _aligned_numeric_values(frame, x_column, y_column)
    smoothed = smooth_values(
        x.to_numpy(dtype=float),
        y.to_numpy(dtype=float),
        method=method,
        parameters=parameters,
    )
    output = pd.Series(np.nan, index=frame.index, dtype="float64")
    output.loc[y.index] = smoothed
    clean_target = _target_column_name(target_column, f"{y_column}_smoothed")
    frame[clean_target] = output
    return SmoothingResult(column_name=clean_target, values_written=int(output.notna().sum()))


def smooth_values(
    x_values: np.ndarray,
    y_values: np.ndarray,
    method: str,
    parameters: SmoothingParameters,
) -> np.ndarray:
    """Return smoothed values without modifying a worksheet."""
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise MathOperationError("Smoothing requires one-dimensional X and Y arrays of equal length.")
    if len(x) < 3:
        raise MathOperationError("Smoothing requires at least three aligned numeric points.")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise MathOperationError("Smoothing inputs must contain only finite aligned values.")

    differences = np.diff(x)
    if np.any(differences == 0):
        raise MathOperationError("Smoothing X values must not contain duplicates.")
    if not (np.all(differences > 0) or np.all(differences < 0)):
        raise MathOperationError("Smoothing X values must be strictly monotonic.")

    if method == "adjacent_average":
        window = _window_length(parameters.window_length, len(y), odd=False, minimum=2)
        return (
            pd.Series(y)
            .rolling(window=window, center=True, min_periods=1)
            .mean()
            .to_numpy(dtype=float)
        )
    if method == "moving_median":
        window = _window_length(parameters.window_length, len(y), odd=True, minimum=3)
        return (
            pd.Series(y)
            .rolling(window=window, center=True, min_periods=1)
            .median()
            .to_numpy(dtype=float)
        )
    if method == "savgol":
        _require_even_spacing(x, "Savitzky-Golay smoothing")
        return _savgol(y, parameters)
    if method == "lowess":
        return _lowess(x, y, parameters)
    if method == "fft":
        _require_even_spacing(x, "FFT smoothing")
        return _fft_smooth(x, y, parameters.fft_cutoff_fraction)
    if method == "derivative_integral":
        return _smooth_derivative_and_integrate(x, y, parameters)
    raise MathOperationError(f"Unknown smoothing method: {method}")


def _aligned_numeric_values(
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
) -> tuple[pd.Series, pd.Series]:
    """Return aligned finite numeric values after metadata validation."""
    for column in (x_column, y_column):
        if not column or column not in frame.columns:
            raise MathOperationError(f"Column '{column}' does not exist.")
    x_numeric = pd.to_numeric(frame[x_column], errors="coerce")
    y_numeric = pd.to_numeric(frame[y_column], errors="coerce")
    validate_numeric_column_metadata(frame, x_column, x_numeric)
    validate_numeric_column_metadata(frame, y_column, y_numeric)
    aligned = pd.DataFrame({"x": x_numeric, "y": y_numeric}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(aligned) < 3:
        raise MathOperationError("Smoothing requires at least three aligned finite points.")
    return aligned["x"], aligned["y"]


def _window_length(requested: int, point_count: int, odd: bool, minimum: int) -> int:
    """Validate and cap a smoothing window for the available point count."""
    window = int(requested)
    if window < minimum:
        raise MathOperationError(f"Smoothing window must contain at least {minimum} points.")
    if window > point_count:
        window = point_count
    if odd and window % 2 == 0:
        window -= 1
    if window < minimum:
        raise MathOperationError(f"Smoothing needs at least {minimum} points for this window.")
    return window


def _savgol(y: np.ndarray, parameters: SmoothingParameters) -> np.ndarray:
    """Return a validated Savitzky-Golay smoothing pass."""
    order = int(parameters.polynomial_order)
    if order < 0 or order >= int(parameters.window_length):
        raise MathOperationError("Savitzky-Golay polynomial order must be smaller than the window.")
    window = _window_length(parameters.window_length, len(y), odd=True, minimum=3)
    order = min(order, window - 1)
    return signal.savgol_filter(y, window_length=window, polyorder=order, mode="interp")


def _lowess(x: np.ndarray, y: np.ndarray, parameters: SmoothingParameters) -> np.ndarray:
    """Return robust locally weighted regression values."""
    fraction = float(parameters.lowess_fraction)
    if not 0.0 < fraction <= 1.0:
        raise MathOperationError("LOWESS fraction must be greater than 0 and no greater than 1.")
    try:
        from statsmodels.nonparametric.smoothers_lowess import lowess
    except ImportError as exc:
        raise MathOperationError(
            "LOWESS requires the statsmodels package. Install the project requirements and retry."
        ) from exc
    descending = x[0] > x[-1]
    working_x = x[::-1] if descending else x
    working_y = y[::-1] if descending else y
    result = np.asarray(
        lowess(
            working_y,
            working_x,
            frac=fraction,
            it=max(0, int(parameters.lowess_iterations)),
            is_sorted=True,
            return_sorted=False,
        ),
        dtype=float,
    )
    return result[::-1] if descending else result


def _fft_smooth(x: np.ndarray, y: np.ndarray, cutoff_fraction: float) -> np.ndarray:
    """Low-pass filter detrended data in the real FFT domain."""
    cutoff = float(cutoff_fraction)
    if not 0.0 < cutoff <= 1.0:
        raise MathOperationError("FFT cutoff fraction must be greater than 0 and no greater than 1.")
    trend = np.linspace(y[0], y[-1], len(y))
    spectrum = np.fft.rfft(y - trend)
    frequencies = np.fft.rfftfreq(len(y), d=abs(float(np.median(np.diff(x)))))
    nyquist = frequencies[-1]
    cutoff_frequency = cutoff * nyquist
    transition_start = cutoff_frequency * 0.8
    weights = np.ones_like(frequencies)
    weights[frequencies >= cutoff_frequency] = 0.0
    transition = (frequencies > transition_start) & (frequencies < cutoff_frequency)
    if cutoff_frequency > transition_start:
        phase = (frequencies[transition] - transition_start) / (cutoff_frequency - transition_start)
        weights[transition] = 0.5 * (1.0 + np.cos(np.pi * phase))
    return np.fft.irfft(spectrum * weights, n=len(y)) + trend


def _smooth_derivative_and_integrate(
    x: np.ndarray,
    y: np.ndarray,
    parameters: SmoothingParameters,
) -> np.ndarray:
    """Smooth dy/dx, integrate it, and anchor the reconstructed signal."""
    derivative = np.gradient(y, x, edge_order=2)
    median_window = int(parameters.derivative_median_window)
    if median_window > 1:
        median_window = _window_length(median_window, len(y), odd=True, minimum=3)
        derivative = (
            pd.Series(derivative)
            .rolling(window=median_window, center=True, min_periods=1)
            .median()
            .to_numpy(dtype=float)
        )
    derivative_method = parameters.derivative_smoothing_method
    if derivative_method not in DERIVATIVE_SMOOTHING_METHODS:
        raise MathOperationError(f"Unknown derivative smoothing method: {derivative_method}")
    derivative = smooth_values(
        x,
        derivative,
        method=derivative_method,
        parameters=parameters,
    )
    reconstructed = y[0] + integrate.cumulative_trapezoid(derivative, x, initial=0.0)
    if parameters.preserve_endpoints:
        span = x[-1] - x[0]
        if span == 0:
            raise MathOperationError("Cannot preserve endpoints when the X range is zero.")
        endpoint_error = y[-1] - reconstructed[-1]
        reconstructed = reconstructed + endpoint_error * ((x - x[0]) / span)
    return reconstructed


def _require_even_spacing(x: np.ndarray, operation: str) -> None:
    """Require finite, approximately uniform sample spacing."""
    spacing = np.abs(np.diff(x))
    representative = float(np.median(spacing))
    tolerance = max(1.0e-12, representative * 1.0e-3)
    if np.any(np.abs(spacing - representative) > tolerance):
        raise MathOperationError(f"{operation} requires evenly spaced X values.")


def _target_column_name(requested: str, fallback: str) -> str:
    """Return a usable smoothing output column name."""
    return requested.strip() or fallback


def smoothing_operation_text(
    x_column: str,
    y_column: str,
    method: str,
    parameters: SmoothingParameters,
) -> str:
    """Return compact provenance text for output column metadata."""
    method_label = SMOOTHING_METHODS.get(method, method)
    effective_method = (
        parameters.derivative_smoothing_method
        if method == "derivative_integral"
        else method
    )
    details = f"method={method_label}; x={x_column}; y={y_column}"
    if effective_method in {"adjacent_average", "moving_median", "savgol"}:
        details += f"; window={parameters.window_length}"
    if effective_method == "savgol":
        details += f"; polynomial_order={parameters.polynomial_order}"
    if effective_method == "lowess":
        details += f"; fraction={parameters.lowess_fraction:g}; iterations={parameters.lowess_iterations}"
    if effective_method == "fft":
        details += f"; cutoff_fraction={parameters.fft_cutoff_fraction:g}"
    if method == "derivative_integral":
        details += (
            f"; derivative_smoother={DERIVATIVE_SMOOTHING_METHODS.get(effective_method, effective_method)}; "
            f"median_prefilter_window={parameters.derivative_median_window}; "
            f"preserve_endpoints={parameters.preserve_endpoints}"
        )
    return f"Smoothing: {details}"
