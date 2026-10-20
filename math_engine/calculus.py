"""Phase 3 calculus and signal-processing operations."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import fft as scipy_fft
from scipy import integrate, signal

from core.workspace import COLUMN_NUMERIC_TYPES, dataframe_column_metadata


class MathOperationError(ValueError):
    """Raised when a math operation cannot be performed on the selected data."""


@dataclass(frozen=True, slots=True)
class ColumnOperationResult:
    """Result of an operation that writes a column into an existing DataFrame."""

    column_name: str
    values_written: int


DERIVATIVE_METHODS: dict[str, str] = {
    "gradient": "NumPy gradient",
    "forward": "Forward difference",
    "backward": "Backward difference",
    "central": "Central difference",
    "savgol": "Savitzky-Golay",
}

INTEGRATION_METHODS: dict[str, str] = {
    "trapezoid": "Cumulative trapezoid",
    "simpson": "Cumulative Simpson",
    "left_rectangle": "Left rectangle",
    "right_rectangle": "Right rectangle",
    "midpoint": "Midpoint rectangle",
}

WINDOW_METHODS: dict[str, str] = {
    "boxcar": "None / rectangular",
    "hann": "Hann",
    "hamming": "Hamming",
    "blackman": "Blackman",
    "bartlett": "Bartlett",
    "flattop": "Flat top",
}


def derivative_column(
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    method: str,
    target_column: str,
) -> ColumnOperationResult:
    """Calculate dy/dx and write the derivative into a target column."""
    x, y = _xy_values(frame, x_column, y_column, minimum_points=3 if method == "savgol" else 2)

    if method == "gradient":
        values = np.gradient(y.to_numpy(dtype=float), x.to_numpy(dtype=float))
    elif method == "forward":
        values = np.full(len(y), np.nan)
        values[:-1] = np.diff(y.to_numpy(dtype=float)) / np.diff(x.to_numpy(dtype=float))
    elif method == "backward":
        values = np.full(len(y), np.nan)
        values[1:] = np.diff(y.to_numpy(dtype=float)) / np.diff(x.to_numpy(dtype=float))
    elif method == "central":
        values = _central_difference(x.to_numpy(dtype=float), y.to_numpy(dtype=float))
    elif method == "savgol":
        values = _savgol_derivative(x.to_numpy(dtype=float), y.to_numpy(dtype=float))
    else:
        raise MathOperationError(f"Unknown derivative method: {method}")

    output = pd.Series(np.nan, index=frame.index, dtype="float64")
    output.loc[y.index] = values
    clean_target = _target_column_name(target_column, f"d_{y_column}_d_{x_column}")
    frame[clean_target] = output
    return ColumnOperationResult(column_name=clean_target, values_written=int(output.notna().sum()))


def integral_column(
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    method: str,
    target_column: str,
    initial_value: float = 0.0,
) -> ColumnOperationResult:
    """Calculate cumulative integral and write it into a target column."""
    x, y = _xy_values(frame, x_column, y_column, minimum_points=2)
    x_array = x.to_numpy(dtype=float)
    y_array = y.to_numpy(dtype=float)

    if method == "trapezoid":
        values = integrate.cumulative_trapezoid(y_array, x_array, initial=0.0)
    elif method == "simpson":
        values = integrate.cumulative_simpson(y=y_array, x=x_array, initial=0.0)
    elif method == "left_rectangle":
        values = np.concatenate([[0.0], np.cumsum(y_array[:-1] * np.diff(x_array))])
    elif method == "right_rectangle":
        values = np.concatenate([[0.0], np.cumsum(y_array[1:] * np.diff(x_array))])
    elif method == "midpoint":
        interval_values = ((y_array[:-1] + y_array[1:]) / 2.0) * np.diff(x_array)
        values = np.concatenate([[0.0], np.cumsum(interval_values)])
    else:
        raise MathOperationError(f"Unknown integration method: {method}")

    values = values + initial_value
    output = pd.Series(np.nan, index=frame.index, dtype="float64")
    output.loc[y.index] = values
    clean_target = _target_column_name(target_column, f"int_{y_column}_d_{x_column}")
    frame[clean_target] = output
    return ColumnOperationResult(column_name=clean_target, values_written=int(output.notna().sum()))


def fft_dataset(
    frame: pd.DataFrame,
    signal_column: str,
    x_column: str | None,
    window_method: str,
) -> pd.DataFrame:
    """Return a frequency-domain DataFrame for a selected signal column."""
    y = _numeric_column(frame, signal_column, minimum_points=2)
    x = _numeric_column(frame, x_column, minimum_points=2) if x_column else None

    if x is not None:
        aligned = pd.DataFrame({"x": x, "y": y}).dropna()
        if len(aligned) < 2:
            raise MathOperationError("FFT requires at least two aligned numeric points.")
        y_values = aligned["y"].to_numpy(dtype=float)
        spacing = _sample_spacing(aligned["x"].to_numpy(dtype=float))
    else:
        y_values = y.dropna().to_numpy(dtype=float)
        spacing = 1.0

    try:
        window = signal.get_window(window_method, len(y_values), fftbins=True)
    except ValueError as exc:
        raise MathOperationError(f"Unknown FFT window method: {window_method}") from exc
    transformed = scipy_fft.fft(y_values * window)
    frequencies = scipy_fft.fftfreq(len(y_values), d=spacing)

    return pd.DataFrame(
        {
            "frequency": frequencies,
            "real": transformed.real,
            "imaginary": transformed.imag,
            "magnitude": np.abs(transformed),
            "phase": np.angle(transformed),
        }
    )


def ifft_dataset(
    frame: pd.DataFrame,
    real_column: str,
    imaginary_column: str | None = None,
) -> pd.DataFrame:
    """Return a reconstructed time-domain signal from real/imaginary FFT columns."""
    real_values = _numeric_column(frame, real_column, minimum_points=1).dropna().to_numpy(dtype=float)

    if imaginary_column:
        imaginary_values = _numeric_column(frame, imaginary_column, minimum_points=1).dropna().to_numpy(dtype=float)
        point_count = min(len(real_values), len(imaginary_values))
        if point_count == 0:
            raise MathOperationError("iFFT requires at least one complex point.")
        spectrum = real_values[:point_count] + 1j * imaginary_values[:point_count]
    else:
        spectrum = real_values.astype(complex)

    reconstructed = scipy_fft.ifft(spectrum)
    return pd.DataFrame(
        {
            "sample": np.arange(len(reconstructed)),
            "real": reconstructed.real,
            "imaginary": reconstructed.imag,
            "magnitude": np.abs(reconstructed),
        }
    )


def _xy_values(
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    minimum_points: int,
) -> tuple[pd.Series, pd.Series]:
    """Return aligned numeric X/Y values after validating point count and spacing."""
    x = _numeric_column(frame, x_column, minimum_points=minimum_points)
    y = _numeric_column(frame, y_column, minimum_points=minimum_points)
    aligned = pd.DataFrame({"x": x, "y": y}).dropna()

    if len(aligned) < minimum_points:
        raise MathOperationError(f"Operation requires at least {minimum_points} aligned numeric points.")

    x_values = aligned["x"]
    if x_values.duplicated().any():
        raise MathOperationError("X values must not contain duplicates.")
    if np.any(np.diff(x_values.to_numpy(dtype=float)) == 0):
        raise MathOperationError("X spacing must not contain zero-length intervals.")

    return aligned["x"], aligned["y"]


def _numeric_column(frame: pd.DataFrame, column: str | None, minimum_points: int) -> pd.Series:
    """Coerce one DataFrame column to numeric values and validate point count."""
    if not column:
        raise MathOperationError("Choose a data column.")
    if column not in frame.columns:
        raise MathOperationError(f"Column '{column}' does not exist.")

    values = pd.to_numeric(frame[column], errors="coerce")
    validate_numeric_column_metadata(frame, column, values)
    if values.notna().sum() < minimum_points:
        raise MathOperationError(f"Column '{column}' needs at least {minimum_points} numeric value(s).")
    return values


def validate_numeric_column_metadata(frame: pd.DataFrame, column: object, values: pd.Series) -> None:
    """Reject text metadata and nonblank nonnumeric cells in numeric workflows."""
    metadata = dataframe_column_metadata(frame, column)
    if metadata.value_type == "text":
        raise MathOperationError(
            f"Column '{column}' is marked Text in metadata; choose a Numeric/Scientific column "
            "or update the column metadata."
        )

    source = frame[column]
    meaningful = source.notna() & (source.astype(str).str.strip() != "")
    source_numeric = pd.to_numeric(source.where(meaningful), errors="coerce")
    invalid = meaningful & source_numeric.isna()
    if invalid.any():
        example = str(source[invalid].iloc[0])
        row_position = int(np.flatnonzero(invalid.to_numpy())[0]) + 1
        type_context = (
            "is marked numeric but "
            if metadata.value_type in COLUMN_NUMERIC_TYPES
            else ""
        )
        raise MathOperationError(
            f"Column '{column}' {type_context}contains non-numeric text at row "
            f"{row_position}, such as '{example}'. Numerical operations do not silently "
            "discard text; correct the cell or choose another column."
        )


def _central_difference(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Return central-difference derivative values with one-sided endpoints."""
    values = np.full(len(y), np.nan)
    values[1:-1] = (y[2:] - y[:-2]) / (x[2:] - x[:-2])
    values[0] = (y[1] - y[0]) / (x[1] - x[0])
    values[-1] = (y[-1] - y[-2]) / (x[-1] - x[-2])
    return values


def _savgol_derivative(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Return a Savitzky-Golay smoothed first derivative."""
    spacing = _sample_spacing(x)
    window_length = min(len(y) if len(y) % 2 == 1 else len(y) - 1, 11)
    if window_length < 3:
        raise MathOperationError("Savitzky-Golay derivative requires at least three points.")

    polyorder = min(3, window_length - 1)
    return signal.savgol_filter(y, window_length=window_length, polyorder=polyorder, deriv=1, delta=spacing)


def _sample_spacing(x: np.ndarray) -> float:
    """Return representative sample spacing for FFT and Savitzky-Golay methods."""
    spacing = np.diff(x)
    if len(spacing) == 0:
        raise MathOperationError("At least two X values are required.")
    if not np.isfinite(spacing).all():
        raise MathOperationError("X values must be finite.")
    absolute_spacing = np.abs(spacing)
    if np.any(absolute_spacing == 0):
        raise MathOperationError("X values must not contain duplicate positions.")
    representative_spacing = float(np.median(absolute_spacing))
    tolerance = max(1.0e-12, representative_spacing * 1.0e-3)
    if np.any(np.abs(absolute_spacing - representative_spacing) > tolerance):
        raise MathOperationError("X values must be evenly spaced for this operation.")
    return representative_spacing


def _target_column_name(target_column: str, fallback: str) -> str:
    """Return a clean target column name or a generated fallback."""
    clean_target = target_column.strip()
    return clean_target or fallback
