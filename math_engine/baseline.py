"""Qt-independent baseline correction for spectra and chromatograms."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from importlib import metadata
from typing import Any

import numpy as np
from scipy import interpolate, sparse
from scipy.sparse import linalg as sparse_linalg

from math_engine.calculus import MathOperationError
from math_engine.spectral import finite_monotonic_segments, is_uniform_axis, validate_spectral_arrays


BASELINE_METHODS: dict[str, str] = {
    "arpls": "arPLS (automatic)",
    "asls": "AsLS",
    "airpls": "airPLS",
    "snip": "SNIP",
    "rubber_band": "Rubber band",
    "manual": "Manual anchors",
    "constant": "Constant background",
    "linear": "Linear background",
    "polynomial": "Polynomial background",
}


@dataclass(frozen=True, slots=True)
class BaselineParameters:
    """Serializable settings for one baseline-correction operation."""

    method: str = "arpls"
    polarity: str = "positive"
    smoothness: float = 1.0e5
    asymmetry: float = 0.01
    max_iterations: int = 100
    tolerance: float = 1.0e-3
    snip_half_window: int = 40
    polynomial_order: int = 2
    edge_fraction: float = 0.10
    constant_value: float | None = None
    anchors: tuple[tuple[float, float], ...] = ()
    anchor_interpolation: str = "pchip"
    anchor_source: str = "xy_pairs"
    anchor_x_values: tuple[float, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly settings for provenance and templates."""
        values = asdict(self)
        values["anchors"] = [list(anchor) for anchor in self.anchors]
        values["anchor_x_values"] = list(self.anchor_x_values)
        return values


@dataclass(frozen=True, slots=True)
class BaselineResult:
    """Numerical output and diagnostics from baseline correction."""

    x: np.ndarray
    raw: np.ndarray
    baseline: np.ndarray
    corrected: np.ndarray
    parameters: BaselineParameters
    iterations: int
    converged: bool
    warnings: tuple[str, ...] = ()
    software_versions: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


def correct_baseline(
    x_values: np.ndarray,
    y_values: np.ndarray,
    parameters: BaselineParameters | None = None,
    *,
    provenance: dict[str, Any] | None = None,
) -> BaselineResult:
    """Estimate and subtract a baseline without modifying the source arrays."""
    params = parameters or BaselineParameters()
    if params.method not in BASELINE_METHODS:
        raise MathOperationError(f"Unknown baseline method: {params.method}")
    if params.polarity not in {"positive", "negative", "both"}:
        raise MathOperationError("Baseline polarity must be positive, negative, or both.")
    if params.smoothness <= 0:
        raise MathOperationError("Baseline smoothness must be greater than zero.")
    if params.max_iterations < 1:
        raise MathOperationError("Baseline maximum iterations must be at least one.")
    if params.tolerance <= 0:
        raise MathOperationError("Baseline tolerance must be greater than zero.")
    if params.anchor_source not in {"xy_pairs", "x_values"}:
        raise MathOperationError("Manual anchor source must be X:Y pairs or X-only values.")

    x, raw = validate_spectral_arrays(x_values, y_values, minimum_finite=2)
    effective_params = params
    if params.method == "manual" and params.anchor_source == "x_values":
        effective_params = replace(
            params,
            anchors=_resolve_x_only_anchors(x, raw, params.anchor_x_values),
        )
    baseline = np.full(raw.shape, np.nan, dtype=float)
    warning_messages: list[str] = []
    iteration_counts: list[int] = []
    convergence_flags: list[bool] = []
    sign = (
        -1.0
        if params.polarity == "negative"
        and params.method in {"arpls", "asls", "airpls", "snip", "rubber_band"}
        else 1.0
    )
    if params.polarity == "both" and params.method in {"arpls", "asls", "airpls", "snip", "rubber_band"}:
        warning_messages.append(
            "This baseline method assumes peaks on one side of the baseline; mixed-polarity peaks may bias it."
        )

    segment_count = 0
    for segment in finite_monotonic_segments(x, raw, minimum_points=2):
        positions, segment_x, segment_y = segment.ascending()
        transformed_y = sign * segment_y
        estimated, iterations, converged, method_warnings = _baseline_segment(
            segment_x,
            transformed_y,
            effective_params,
        )
        baseline[positions] = sign * estimated
        iteration_counts.append(iterations)
        convergence_flags.append(converged)
        warning_messages.extend(method_warnings)
        segment_count += 1

    missing_count = int(np.count_nonzero(~(np.isfinite(x) & np.isfinite(raw))))
    if missing_count:
        warning_messages.append(
            f"Preserved {missing_count} row(s) with missing or non-finite X/Y values."
        )
    if segment_count > 1:
        warning_messages.append(f"Processed {segment_count} finite spectral segments independently.")

    corrected = raw - baseline
    return BaselineResult(
        x=x.copy(),
        raw=raw.copy(),
        baseline=baseline,
        corrected=corrected,
        parameters=effective_params,
        iterations=max(iteration_counts, default=0),
        converged=all(convergence_flags) if convergence_flags else False,
        warnings=tuple(dict.fromkeys(warning_messages)),
        software_versions=_software_versions(),
        provenance=dict(provenance or {}),
    )


def _baseline_segment(
    x: np.ndarray,
    y: np.ndarray,
    params: BaselineParameters,
) -> tuple[np.ndarray, int, bool, list[str]]:
    """Return a baseline for one finite ascending-X segment."""
    if len(y) == 2 and params.method not in {"constant", "linear", "manual"}:
        return np.interp(x, x, y), 1, True, [
            "A two-point segment was represented by a straight baseline."
        ]
    if params.method == "manual":
        return _manual_anchor_baseline(x, params), 1, True, []
    if params.method == "constant":
        value = (
            float(params.constant_value)
            if params.constant_value is not None
            else _edge_level(y, params.edge_fraction)
        )
        return np.full_like(y, value), 1, True, []
    if params.method == "linear":
        return _linear_background(x, y, params.edge_fraction), 1, True, []
    if params.method == "polynomial":
        return _polynomial_background(x, y, params), min(8, params.max_iterations), True, []
    external = _pybaselines_segment(x, y, params)
    if external is not None:
        return external

    warnings = [
        "pybaselines is unavailable; used the built-in sparse fallback. Install project requirements for the maintained backend."
    ]
    if not is_uniform_axis(x) and params.method in {"arpls", "asls", "airpls", "snip"}:
        warnings.append(
            "The built-in fallback applies smoothness by sample position on this irregular X axis."
        )
    if params.method == "snip":
        return _snip(y, params.snip_half_window), max(1, params.snip_half_window), True, warnings
    if params.method == "rubber_band":
        return _rubber_band(x, y), 1, True, warnings
    estimated, iterations, converged = _whittaker_baseline(y, params)
    return estimated, iterations, converged, warnings


def _pybaselines_segment(
    x: np.ndarray,
    y: np.ndarray,
    params: BaselineParameters,
) -> tuple[np.ndarray, int, bool, list[str]] | None:
    """Use pybaselines lazily when installed, keeping it optional for old environments."""
    try:
        from pybaselines import Baseline
    except ImportError:
        return None
    fitter = Baseline(x_data=x, check_finite=False, assume_sorted=True)
    try:
        if params.method == "arpls":
            values, details = fitter.arpls(
                y,
                lam=params.smoothness,
                max_iter=params.max_iterations,
                tol=params.tolerance,
            )
        elif params.method == "asls":
            values, details = fitter.asls(
                y,
                lam=params.smoothness,
                p=params.asymmetry,
                max_iter=params.max_iterations,
                tol=params.tolerance,
            )
        elif params.method == "airpls":
            values, details = fitter.airpls(
                y,
                lam=params.smoothness,
                max_iter=params.max_iterations,
                tol=params.tolerance,
            )
        elif params.method == "snip":
            values, details = fitter.snip(y, max_half_window=params.snip_half_window)
        elif params.method == "rubber_band":
            values, details = fitter.rubberband(y)
        else:
            return None
    except Exception as exc:
        fallback_warning = f"pybaselines {params.method} failed ({exc}); used the built-in fallback."
        if params.method == "snip":
            values = _snip(y, params.snip_half_window)
            return values, max(1, params.snip_half_window), True, [fallback_warning]
        if params.method == "rubber_band":
            return _rubber_band(x, y), 1, True, [fallback_warning]
        values, iterations, converged = _whittaker_baseline(y, params)
        return values, iterations, converged, [fallback_warning]

    tolerance_history = np.asarray(details.get("tol_history", []), dtype=float)
    iterations = max(1, len(tolerance_history))
    converged = bool(
        tolerance_history.size == 0 or tolerance_history[-1] < params.tolerance
    )
    warnings = [] if converged else [
        f"{BASELINE_METHODS[params.method]} reached the iteration limit before convergence."
    ]
    return np.asarray(values, dtype=float), iterations, converged, warnings


def _whittaker_baseline(
    y: np.ndarray,
    params: BaselineParameters,
) -> tuple[np.ndarray, int, bool]:
    """Sparse Whittaker fallback for arPLS, AsLS, and airPLS."""
    count = len(y)
    differences = sparse.diags(
        [np.ones(count - 2), -2.0 * np.ones(count - 2), np.ones(count - 2)],
        [0, 1, 2],
        shape=(count - 2, count),
        format="csc",
    )
    penalty = params.smoothness * (differences.T @ differences)
    weights = np.ones(count, dtype=float)
    baseline = y.copy()
    converged = False
    for iteration in range(1, params.max_iterations + 1):
        system = sparse.diags(weights, format="csc") + penalty
        baseline = np.asarray(sparse_linalg.spsolve(system, weights * y), dtype=float)
        residual = y - baseline
        if params.method == "asls":
            updated = np.where(residual > 0, params.asymmetry, 1.0 - params.asymmetry)
        else:
            negative = residual[residual < 0]
            if negative.size == 0:
                converged = True
                break
            scale = float(np.std(negative))
            mean = float(np.mean(negative))
            if scale <= np.finfo(float).eps:
                converged = True
                break
            if params.method == "airpls":
                updated = np.ones_like(weights)
                negative_mask = residual < 0
                updated[~negative_mask] = 1.0e-8
                exponent = np.clip(iteration * np.abs(residual[negative_mask]) / max(np.sum(np.abs(negative)), 1.0e-12), 0, 60)
                updated[negative_mask] = np.exp(exponent)
            else:
                exponent = np.clip(2.0 * (residual - (2.0 * scale - mean)) / scale, -60, 60)
                updated = 1.0 / (1.0 + np.exp(exponent))
        denominator = max(float(np.linalg.norm(weights)), np.finfo(float).eps)
        if float(np.linalg.norm(updated - weights)) / denominator < params.tolerance:
            weights = updated
            converged = True
            break
        weights = np.clip(updated, 1.0e-8, 1.0e8)
    return baseline, iteration, converged


def _snip(y: np.ndarray, half_window: int) -> np.ndarray:
    """Memory-bounded iterative peak clipping fallback."""
    baseline = np.asarray(y, dtype=float).copy()
    maximum = min(max(1, int(half_window)), max(1, (len(y) - 1) // 2))
    for window in range(1, maximum + 1):
        middle = 0.5 * (baseline[:-2 * window] + baseline[2 * window:])
        baseline[window:-window] = np.minimum(baseline[window:-window], middle)
    return baseline


def _rubber_band(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Interpolate the lower convex hull (rubber-band baseline)."""
    hull: list[int] = []
    for index in range(len(x)):
        while len(hull) >= 2:
            first, second = hull[-2], hull[-1]
            cross = (x[second] - x[first]) * (y[index] - y[second]) - (
                y[second] - y[first]
            ) * (x[index] - x[second])
            if cross > 0:
                break
            hull.pop()
        hull.append(index)
    return np.interp(x, x[hull], y[hull])


def _manual_anchor_baseline(x: np.ndarray, params: BaselineParameters) -> np.ndarray:
    """Interpolate a user-supplied set of physical-X baseline anchors."""
    if len(params.anchors) < 2:
        raise MathOperationError("Manual baseline correction requires at least two anchors.")
    anchors = np.asarray(params.anchors, dtype=float)
    if anchors.ndim != 2 or anchors.shape[1] != 2 or not np.isfinite(anchors).all():
        raise MathOperationError("Manual baseline anchors must contain finite X and Y pairs.")
    order = np.argsort(anchors[:, 0])
    anchor_x = anchors[order, 0]
    anchor_y = anchors[order, 1]
    if np.any(np.diff(anchor_x) <= 0):
        raise MathOperationError("Manual baseline anchor X coordinates must be unique.")
    mode = params.anchor_interpolation.lower()
    if mode == "linear":
        return np.interp(x, anchor_x, anchor_y)
    if mode == "pchip":
        function = interpolate.PchipInterpolator(anchor_x, anchor_y, extrapolate=True)
    elif mode == "akima":
        if len(anchor_x) < 3:
            raise MathOperationError("Akima baseline interpolation requires at least three anchors.")
        function = interpolate.Akima1DInterpolator(anchor_x, anchor_y, extrapolate=True)
    else:
        raise MathOperationError("Anchor interpolation must be linear, PCHIP, or Akima.")
    return np.asarray(function(x), dtype=float)


def _resolve_x_only_anchors(
    x: np.ndarray,
    y: np.ndarray,
    anchor_x_values: tuple[float, ...],
) -> tuple[tuple[float, float], ...]:
    """Resolve reusable physical-X anchors against the current spectrum."""
    if len(anchor_x_values) < 2:
        raise MathOperationError("Manual baseline correction requires at least two anchor X values.")
    requested = np.asarray(anchor_x_values, dtype=float)
    if requested.ndim != 1 or not np.isfinite(requested).all():
        raise MathOperationError("Manual baseline anchor X values must be finite numbers.")
    requested = np.sort(requested)
    if np.any(np.diff(requested) <= 0):
        raise MathOperationError("Manual baseline anchor X values must be unique.")

    finite = np.isfinite(x) & np.isfinite(y)
    finite_x = np.asarray(x[finite], dtype=float)
    finite_y = np.asarray(y[finite], dtype=float)
    if finite_x.size < 2:
        raise MathOperationError("X-only anchors require at least two finite source points.")
    order = np.argsort(finite_x, kind="stable")
    finite_x = finite_x[order]
    finite_y = finite_y[order]
    if np.any(np.diff(finite_x) <= 0):
        raise MathOperationError("X-only anchors require unique source X coordinates.")
    if requested[0] < finite_x[0] or requested[-1] > finite_x[-1]:
        raise MathOperationError(
            "Every manual anchor X value must lie inside the finite source X range."
        )
    resolved_y = np.interp(requested, finite_x, finite_y)
    return tuple(
        (float(anchor_x), float(anchor_y))
        for anchor_x, anchor_y in zip(requested, resolved_y)
    )


def _edge_level(y: np.ndarray, fraction: float) -> float:
    count = max(1, min(len(y) // 2, int(np.ceil(len(y) * np.clip(fraction, 0.01, 0.5)))))
    return float(np.median(np.concatenate((y[:count], y[-count:]))))


def _linear_background(x: np.ndarray, y: np.ndarray, fraction: float) -> np.ndarray:
    count = max(1, min(len(y) // 2, int(np.ceil(len(y) * np.clip(fraction, 0.01, 0.5)))))
    indices = np.r_[np.arange(count), np.arange(len(y) - count, len(y))]
    coefficients = np.polyfit(x[indices], y[indices], 1)
    return np.polyval(coefficients, x)


def _polynomial_background(
    x: np.ndarray,
    y: np.ndarray,
    params: BaselineParameters,
) -> np.ndarray:
    order = int(params.polynomial_order)
    if order < 0 or order >= len(x):
        raise MathOperationError("Baseline polynomial order must be non-negative and below the point count.")
    mask = np.ones(len(y), dtype=bool)
    baseline = np.full_like(y, np.median(y))
    for _ in range(min(8, params.max_iterations)):
        if np.count_nonzero(mask) <= order:
            break
        coefficients = np.polyfit(x[mask], y[mask], order)
        baseline = np.polyval(coefficients, x)
        residual = y - baseline
        negative = residual[residual <= 0]
        scale = 1.4826 * float(np.median(np.abs(negative - np.median(negative)))) if negative.size else 0.0
        new_mask = residual <= max(3.0 * scale, np.finfo(float).eps)
        if np.array_equal(new_mask, mask):
            break
        mask = new_mask
    return baseline


def _software_versions() -> dict[str, str]:
    versions = {"numpy": np.__version__, "scipy": metadata.version("scipy")}
    try:
        versions["pybaselines"] = metadata.version("pybaselines")
    except metadata.PackageNotFoundError:
        versions["pybaselines"] = "not installed (built-in sparse fallback)"
    return versions
