"""Shared helpers for one-dimensional spectral analysis engines."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from math_engine.calculus import MathOperationError


@dataclass(frozen=True, slots=True)
class FiniteSegment:
    """One contiguous finite, strictly monotonic part of a spectrum."""

    positions: np.ndarray
    x: np.ndarray
    y: np.ndarray
    descending: bool

    def ascending(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return positions, X, and Y in ascending-X order."""
        if self.descending:
            return self.positions[::-1], self.x[::-1], self.y[::-1]
        return self.positions, self.x, self.y


def validate_spectral_arrays(
    x_values: np.ndarray,
    y_values: np.ndarray,
    *,
    minimum_finite: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """Return one-dimensional float arrays after basic spectrum validation."""
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise MathOperationError(
            "Spectral analysis requires one-dimensional X and Y arrays of equal length."
        )
    if len(x) < minimum_finite:
        raise MathOperationError(
            f"Spectral analysis requires at least {minimum_finite} points."
        )
    finite_count = int(np.count_nonzero(np.isfinite(x) & np.isfinite(y)))
    if finite_count < minimum_finite:
        raise MathOperationError(
            f"Spectral analysis requires at least {minimum_finite} aligned finite points."
        )
    return x, y


def finite_monotonic_segments(
    x_values: np.ndarray,
    y_values: np.ndarray,
    *,
    minimum_points: int = 2,
) -> Iterator[FiniteSegment]:
    """Yield contiguous finite spectrum segments and validate their X axes."""
    x, y = validate_spectral_arrays(x_values, y_values, minimum_finite=minimum_points)
    finite = np.isfinite(x) & np.isfinite(y)
    starts = np.flatnonzero(finite & np.r_[True, ~finite[:-1]])
    stops = np.flatnonzero(finite & np.r_[~finite[1:], True]) + 1
    yielded = False
    for start, stop in zip(starts, stops):
        if stop - start < minimum_points:
            continue
        segment_x = x[start:stop]
        differences = np.diff(segment_x)
        if np.any(differences == 0):
            raise MathOperationError(
                "Spectral X values must not contain duplicate coordinates within a finite segment."
            )
        increasing = bool(np.all(differences > 0))
        decreasing = bool(np.all(differences < 0))
        if not (increasing or decreasing):
            raise MathOperationError(
                "Spectral X values must be strictly monotonic within each finite segment."
            )
        yielded = True
        yield FiniteSegment(
            positions=np.arange(start, stop, dtype=int),
            x=segment_x,
            y=y[start:stop],
            descending=decreasing,
        )
    if not yielded:
        raise MathOperationError(
            f"No contiguous finite spectral segment contains {minimum_points} points."
        )


def is_uniform_axis(x_values: np.ndarray, *, relative_tolerance: float = 1.0e-3) -> bool:
    """Return whether an ascending or descending axis is approximately uniform."""
    x = np.asarray(x_values, dtype=float)
    if len(x) < 3:
        return True
    spacing = np.abs(np.diff(x))
    representative = float(np.median(spacing))
    tolerance = max(1.0e-12, representative * relative_tolerance)
    return bool(np.all(np.abs(spacing - representative) <= tolerance))


def coordinate_at_sample(x_values: np.ndarray, sample_position: float) -> float:
    """Interpolate a physical X coordinate from a fractional sample position."""
    x = np.asarray(x_values, dtype=float)
    clipped = float(np.clip(sample_position, 0.0, max(0, len(x) - 1)))
    lower = int(np.floor(clipped))
    upper = min(lower + 1, len(x) - 1)
    fraction = clipped - lower
    return float(x[lower] + fraction * (x[upper] - x[lower]))


def robust_noise_mad(y_values: np.ndarray) -> float:
    """Estimate point noise from the MAD of first differences."""
    y = np.asarray(y_values, dtype=float)
    finite = y[np.isfinite(y)]
    if len(finite) < 3:
        return 0.0
    differences = np.diff(finite)
    median = float(np.median(differences))
    mad = float(np.median(np.abs(differences - median)))
    estimate = 1.4826 * mad / np.sqrt(2.0)
    if estimate > 0 and np.isfinite(estimate):
        return float(estimate)
    centered = finite - np.median(finite)
    fallback = 1.4826 * float(np.median(np.abs(centered)))
    return fallback if np.isfinite(fallback) else 0.0
