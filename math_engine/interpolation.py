"""Reusable interpolation operations for 1D, 2D, and N-D datasets."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.interpolate import (
    Akima1DInterpolator,
    CloughTocher2DInterpolator,
    CubicSpline,
    LinearNDInterpolator,
    NearestNDInterpolator,
    PchipInterpolator,
    RBFInterpolator,
    SmoothBivariateSpline,
    UnivariateSpline,
    interp1d,
)

from math_engine.calculus import MathOperationError, validate_numeric_column_metadata


@dataclass(frozen=True, slots=True)
class InterpolationMethod:
    """Metadata for one interpolation method exposed in the UI."""

    label: str
    description: str


INTERPOLATION_METHODS: dict[str, dict[str, InterpolationMethod]] = {
    "1d": {
        "linear": InterpolationMethod("Linear", "Piecewise linear interpolation."),
        "nearest": InterpolationMethod("Nearest neighbor", "Use the nearest source sample."),
        "cubic_spline": InterpolationMethod("Cubic spline", "Smooth cubic spline through source samples."),
        "pchip": InterpolationMethod("PCHIP", "Shape-preserving piecewise cubic interpolation."),
        "akima": InterpolationMethod("Akima", "Local cubic interpolation that is less sensitive to outliers."),
        "smoothing_spline": InterpolationMethod("Smoothing spline", "Spline with optional smoothing parameter."),
    },
    "2d": {
        "nearest": InterpolationMethod("Nearest neighbor", "Nearest scattered source point."),
        "linear": InterpolationMethod("Linear scattered", "Linear interpolation inside the convex hull."),
        "cubic_spline": InterpolationMethod("Cubic spline", "Bivariate cubic spline surface through X/Y/Z data."),
        "piecewise_cubic": InterpolationMethod("Piecewise cubic", "Clough-Tocher cubic interpolation for 2D scattered data."),
        "smooth_bivariate_spline": InterpolationMethod("Smooth bivariate spline", "2D smoothing spline for X/Y/Z data."),
        "rbf_linear": InterpolationMethod("RBF linear", "Radial basis interpolation with a linear kernel."),
        "rbf_thin_plate": InterpolationMethod("RBF thin plate", "Radial basis interpolation with a thin-plate spline kernel."),
        "rbf_cubic": InterpolationMethod("RBF cubic", "Radial basis interpolation with a cubic kernel."),
        "rbf_gaussian": InterpolationMethod("RBF Gaussian", "Radial basis interpolation with a Gaussian kernel."),
    },
    "nd": {
        "nearest": InterpolationMethod("Nearest neighbor", "Nearest scattered source point in N-D."),
        "linear": InterpolationMethod("Linear scattered", "N-D linear interpolation inside the convex hull."),
        "rbf_linear": InterpolationMethod("RBF linear", "Radial basis interpolation with a linear kernel."),
        "rbf_thin_plate": InterpolationMethod("RBF thin plate", "Radial basis interpolation with a thin-plate spline kernel."),
        "rbf_cubic": InterpolationMethod("RBF cubic", "Radial basis interpolation with a cubic kernel."),
        "rbf_gaussian": InterpolationMethod("RBF Gaussian", "Radial basis interpolation with a Gaussian kernel."),
    },
}

FILL_POLICIES: dict[str, str] = {
    "nan": "Outside source range as blank",
    "extrapolate": "Extrapolate when supported",
    "constant": "Clamp 1D outside range to edge values",
}
MAX_GENERATED_QUERY_POINTS = 1_000_000

_RBF_KERNELS: dict[str, str] = {
    "rbf_linear": "linear",
    "rbf_thin_plate": "thin_plate_spline",
    "rbf_cubic": "cubic",
    "rbf_gaussian": "gaussian",
}
_RBF_KERNELS_REQUIRING_EPSILON = {"gaussian", "multiquadric", "inverse_multiquadric", "inverse_quadratic"}


def interpolate_dataset(
    frame: pd.DataFrame,
    coordinate_columns: list[str],
    value_column: str,
    query_points: np.ndarray,
    method: str,
    fill_policy: str = "nan",
    smoothing: float = 0.0,
    epsilon: float | None = None,
) -> pd.DataFrame:
    """Interpolate values at query coordinates and return a result DataFrame."""
    clean_coordinates = [
        str(column)
        for column in coordinate_columns
        if str(column).strip()
    ]
    clean_value = str(value_column)
    if not clean_coordinates:
        raise MathOperationError("Choose at least one coordinate column.")
    if not clean_value.strip():
        raise MathOperationError("Choose a value column to interpolate.")
    if fill_policy not in FILL_POLICIES:
        raise MathOperationError(f"Unknown interpolation outside-range policy: {fill_policy}")
    if clean_value in clean_coordinates:
        raise MathOperationError("The value column must be different from the coordinate columns.")
    if len(set(clean_coordinates)) != len(clean_coordinates):
        raise MathOperationError("Coordinate columns must be unique.")

    points, values = _source_points(frame, clean_coordinates, clean_value)
    query = _normalize_query_points(query_points, len(clean_coordinates))
    if len(clean_coordinates) == 1:
        predictions = _interpolate_1d(
            points[:, 0],
            values,
            query[:, 0],
            method=method,
            fill_policy=fill_policy,
            smoothing=smoothing,
        )
    else:
        predictions = _interpolate_nd(
            points,
            values,
            query,
            method=method,
            smoothing=smoothing,
            epsilon=epsilon,
        )

    result = {
        column: query[:, index]
        for index, column in enumerate(clean_coordinates)
    }
    result[f"{clean_value}_interpolated"] = predictions
    return pd.DataFrame(result)


def generated_query_points(ranges: list[tuple[float, float, int]], mesh: bool) -> np.ndarray:
    """Create query points from one or more generated coordinate ranges."""
    if not ranges:
        raise MathOperationError("Define at least one generated coordinate range.")

    axes: list[np.ndarray] = []
    total_count = 1
    for start, stop, count in ranges:
        if count < 1:
            raise MathOperationError("Generated point counts must be at least 1.")
        if not np.isfinite(start) or not np.isfinite(stop):
            raise MathOperationError("Generated range limits must be finite numbers.")
        total_count *= int(count)
        if total_count > MAX_GENERATED_QUERY_POINTS:
            raise MathOperationError(
                f"Generated queries are limited to {MAX_GENERATED_QUERY_POINTS:,} points."
            )
        axes.append(np.linspace(float(start), float(stop), int(count)))

    if not mesh:
        if len(axes) != 1:
            raise MathOperationError("Non-mesh generated queries require exactly one range.")
        return axes[0].reshape(-1, 1)

    mesh_axes = np.meshgrid(*axes, indexing="xy")
    return np.column_stack([axis.ravel() for axis in mesh_axes])


def query_points_from_columns(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    """Read query coordinates from existing dataset columns."""
    clean_columns = [
        str(column)
        for column in columns
        if str(column).strip()
    ]
    if not clean_columns:
        raise MathOperationError("Choose query coordinate columns.")
    missing = [column for column in clean_columns if column not in frame.columns]
    if missing:
        raise MathOperationError("Missing query column(s): " + ", ".join(missing))

    numeric_columns: dict[str, pd.Series] = {}
    for column in clean_columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        validate_numeric_column_metadata(frame, column, values)
        numeric_columns[column] = values
    data = pd.DataFrame(numeric_columns).replace([np.inf, -np.inf], np.nan).dropna()
    if data.empty:
        raise MathOperationError("Query columns do not contain any complete numeric coordinate rows.")
    return data.to_numpy(dtype=float)


def query_points_from_text(text: str, dimension: int) -> np.ndarray:
    """Parse manual query coordinates from text."""
    rows: list[list[float]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        tokens = [token for token in stripped.replace(",", " ").replace(";", " ").split() if token]
        if len(tokens) != dimension:
            raise MathOperationError(
                f"Manual query line {line_number} must contain {dimension} numeric value(s)."
            )
        try:
            rows.append([float(token) for token in tokens])
        except ValueError as exc:
            raise MathOperationError(f"Manual query line {line_number} contains non-numeric text.") from exc

    if not rows:
        raise MathOperationError("Enter at least one manual query coordinate.")
    return np.asarray(rows, dtype=float)


def _source_points(
    frame: pd.DataFrame,
    coordinate_columns: list[str],
    value_column: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Return numeric source coordinates and values, averaging duplicate coordinates."""
    missing = [column for column in [*coordinate_columns, value_column] if column not in frame.columns]
    if missing:
        raise MathOperationError("Missing source column(s): " + ", ".join(missing))

    numeric_columns: dict[str, pd.Series] = {}
    for column in [*coordinate_columns, value_column]:
        values = pd.to_numeric(frame[column], errors="coerce")
        validate_numeric_column_metadata(frame, column, values)
        numeric_columns[column] = values
    data = pd.DataFrame(numeric_columns).replace([np.inf, -np.inf], np.nan).dropna()
    if data.empty:
        raise MathOperationError("Source columns do not contain complete numeric coordinate/value rows.")

    grouped = (
        data.groupby(coordinate_columns, as_index=False, sort=True)[value_column]
        .mean()
        .dropna()
    )
    dimension = len(coordinate_columns)
    minimum = _minimum_points_for_dimension(dimension)
    if len(grouped) < minimum:
        raise MathOperationError(
            f"Interpolation requires at least {minimum} unique numeric source point(s) for this dimension."
        )

    points = grouped[coordinate_columns].to_numpy(dtype=float)
    values = grouped[value_column].to_numpy(dtype=float)
    return points, values


def _minimum_points_for_dimension(dimension: int) -> int:
    """Return a conservative generic minimum source-point count."""
    return 2 if dimension == 1 else dimension + 1


def _normalize_query_points(query_points: np.ndarray, dimension: int) -> np.ndarray:
    """Validate query point shape and values."""
    query = np.asarray(query_points, dtype=float)
    if query.ndim == 1:
        query = query.reshape(-1, 1)
    if query.ndim != 2 or query.shape[1] != dimension:
        raise MathOperationError(f"Query coordinates must have {dimension} column(s).")
    if query.shape[0] == 0:
        raise MathOperationError("At least one query coordinate is required.")
    if not np.isfinite(query).all():
        raise MathOperationError("Query coordinates must be finite numeric values.")
    return query


def _interpolate_1d(
    x_values: np.ndarray,
    y_values: np.ndarray,
    query_values: np.ndarray,
    method: str,
    fill_policy: str,
    smoothing: float,
) -> np.ndarray:
    """Interpolate a one-dimensional source series."""
    order = np.argsort(x_values)
    x = x_values[order]
    y = y_values[order]
    if len(np.unique(x)) != len(x):
        raise MathOperationError("1D source X values must be unique after duplicate aggregation.")

    if method == "nearest":
        interpolator = interp1d(
            x, y, kind="nearest", bounds_error=False,
            fill_value="extrapolate" if fill_policy in {"extrapolate", "constant"} else np.nan,
            assume_sorted=True,
        )
        predictions = np.asarray(interpolator(query_values), dtype=float)
    elif method == "linear":
        interpolator = interp1d(
            x, y, kind="linear", bounds_error=False,
            fill_value="extrapolate" if fill_policy in {"extrapolate", "constant"} else np.nan,
            assume_sorted=True,
        )
        predictions = np.asarray(interpolator(query_values), dtype=float)
    elif method == "cubic_spline":
        _require_points(x, 4, "Cubic spline")
        spline = CubicSpline(x, y, extrapolate=fill_policy in {"extrapolate", "constant"})
        predictions = np.asarray(spline(query_values), dtype=float)
    elif method == "pchip":
        _require_points(x, 2, "PCHIP")
        interpolator = PchipInterpolator(x, y, extrapolate=fill_policy in {"extrapolate", "constant"})
        predictions = np.asarray(interpolator(query_values), dtype=float)
    elif method == "akima":
        _require_points(x, 5, "Akima")
        interpolator = Akima1DInterpolator(x, y, extrapolate=fill_policy in {"extrapolate", "constant"})
        predictions = np.asarray(interpolator(query_values), dtype=float)
    elif method == "smoothing_spline":
        _require_points(x, 4, "Smoothing spline")
        spline = UnivariateSpline(x, y, s=max(float(smoothing), 0.0))
        predictions = np.asarray(spline(query_values), dtype=float)
        if fill_policy == "nan":
            predictions = _blank_outside_1d(x, query_values, predictions)
    else:
        raise MathOperationError(f"Unknown 1D interpolation method: {method}")

    if fill_policy == "constant":
        predictions = _constant_outside_1d(x, y, query_values, predictions)
    elif fill_policy == "nan" and method not in {"nearest", "linear", "cubic_spline", "pchip", "akima", "smoothing_spline"}:
        predictions = _blank_outside_1d(x, query_values, predictions)
    return predictions


def _interpolate_nd(
    points: np.ndarray,
    values: np.ndarray,
    query: np.ndarray,
    method: str,
    smoothing: float,
    epsilon: float | None,
) -> np.ndarray:
    """Interpolate scattered data in two or more dimensions."""
    dimension = points.shape[1]
    try:
        if method == "nearest":
            return np.asarray(NearestNDInterpolator(points, values)(query), dtype=float)
        if method == "linear":
            _require_points(points, dimension + 1, "Linear scattered interpolation")
            return np.asarray(LinearNDInterpolator(points, values, fill_value=np.nan)(query), dtype=float)
        if method == "piecewise_cubic":
            if dimension != 2:
                raise MathOperationError("Piecewise cubic interpolation is only available for 2D data.")
            _require_points(points, 4, "Piecewise cubic interpolation")
            return np.asarray(CloughTocher2DInterpolator(points, values, fill_value=np.nan)(query), dtype=float)
        if method in {"cubic_spline", "smooth_bivariate_spline"}:
            if dimension != 2:
                raise MathOperationError("Bivariate spline interpolation is only available for 2D data.")
            label = (
                "Cubic spline interpolation"
                if method == "cubic_spline"
                else "Smooth bivariate spline interpolation"
            )
            _require_points(points, 16, label)
            spline = SmoothBivariateSpline(
                points[:, 0],
                points[:, 1],
                values,
                kx=3,
                ky=3,
                s=0.0 if method == "cubic_spline" else max(float(smoothing), 0.0),
            )
            return np.asarray(spline.ev(query[:, 0], query[:, 1]), dtype=float)
        if method in _RBF_KERNELS:
            _require_points(points, dimension + 1, "RBF interpolation")
            kernel = _RBF_KERNELS[method]
            kwargs: dict[str, float | str] = {
                "kernel": kernel,
                "smoothing": max(float(smoothing), 0.0),
            }
            if kernel in _RBF_KERNELS_REQUIRING_EPSILON:
                kwargs["epsilon"] = float(epsilon) if epsilon and epsilon > 0 else _estimate_epsilon(points)
            interpolator = RBFInterpolator(points, values, **kwargs)
            return np.asarray(interpolator(query), dtype=float)
    except MathOperationError:
        raise
    except Exception as exc:
        raise MathOperationError(f"Interpolation failed: {exc}") from exc

    raise MathOperationError(f"Unknown interpolation method: {method}")


def _require_points(points: np.ndarray, minimum: int, label: str) -> None:
    """Raise when a method does not have enough unique source points."""
    if len(points) < minimum:
        raise MathOperationError(f"{label} requires at least {minimum} unique source point(s).")


def _blank_outside_1d(x: np.ndarray, query: np.ndarray, predictions: np.ndarray) -> np.ndarray:
    """Set 1D predictions outside the source range to NaN."""
    output = predictions.copy()
    outside = (query < float(np.min(x))) | (query > float(np.max(x)))
    output[outside] = np.nan
    return output


def _constant_outside_1d(
    x: np.ndarray,
    y: np.ndarray,
    query: np.ndarray,
    predictions: np.ndarray,
) -> np.ndarray:
    """Clamp 1D predictions outside the source range to edge source values."""
    output = predictions.copy()
    output[query < float(np.min(x))] = float(y[0])
    output[query > float(np.max(x))] = float(y[-1])
    return output


def _estimate_epsilon(points: np.ndarray) -> float:
    """Estimate a practical RBF epsilon from coordinate ranges."""
    ranges = np.ptp(points, axis=0)
    finite_ranges = ranges[np.isfinite(ranges) & (ranges > 0)]
    if len(finite_ranges) == 0:
        return 1.0
    return float(np.mean(finite_ranges))
