"""Empirical colour-scale calibration for raster colour-plot extraction."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class ColorMatch:
    """One colour-to-value match with quality and ambiguity diagnostics."""

    value: float
    palette_position: float
    distance: float
    confidence: float
    ambiguous: bool
    valid: bool


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert one or more 8-bit sRGB colours to CIE Lab (D65)."""
    values = np.asarray(rgb, dtype=float)
    if values.shape[-1] != 3:
        raise ValueError("RGB input must have a final dimension of size 3.")
    normalized = np.clip(values / 255.0, 0.0, 1.0)
    linear = np.where(
        normalized <= 0.04045,
        normalized / 12.92,
        ((normalized + 0.055) / 1.055) ** 2.4,
    )
    transform = np.asarray(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=float,
    )
    xyz = linear @ transform.T
    xyz /= np.asarray([0.95047, 1.0, 1.08883], dtype=float)
    delta = 6.0 / 29.0
    pivot = np.where(
        xyz > delta**3,
        np.cbrt(xyz),
        xyz / (3.0 * delta**2) + 4.0 / 29.0,
    )
    lab = np.empty_like(pivot)
    lab[..., 0] = 116.0 * pivot[..., 1] - 16.0
    lab[..., 1] = 500.0 * (pivot[..., 0] - pivot[..., 1])
    lab[..., 2] = 200.0 * (pivot[..., 1] - pivot[..., 2])
    return lab


class ColorScaleCalibration:
    """Map raster colours onto values learned from an ordered colour-bar sample."""

    def __init__(
        self,
        palette_rgb: np.ndarray,
        low_value: float,
        high_value: float,
        scale: str = "linear",
        maximum_distance: float = 18.0,
    ) -> None:
        palette = np.asarray(palette_rgb, dtype=float)
        if palette.ndim != 2 or palette.shape[1] != 3 or len(palette) < 2:
            raise ValueError("A colour scale requires at least two ordered RGB samples.")
        if not np.all(np.isfinite(palette)):
            raise ValueError("Colour-scale samples must be finite RGB values.")
        if not math.isfinite(low_value) or not math.isfinite(high_value):
            raise ValueError("Colour-scale endpoint values must be finite.")
        if low_value == high_value:
            raise ValueError("Colour-scale endpoint values must be different.")
        if scale not in {"linear", "log"}:
            raise ValueError("Colour-scale normalization must be linear or log.")
        if scale == "log" and (low_value <= 0 or high_value <= 0):
            raise ValueError("Log colour-scale values must be positive.")
        if not math.isfinite(maximum_distance) or maximum_distance <= 0:
            raise ValueError("Maximum colour distance must be positive.")

        self.palette_rgb = np.clip(palette, 0.0, 255.0)
        self.palette_lab = srgb_to_lab(self.palette_rgb)
        self.low_value = float(low_value)
        self.high_value = float(high_value)
        self.scale = scale
        self.maximum_distance = float(maximum_distance)

    def value_at(self, position: float) -> float:
        """Convert a normalized palette position to its calibrated value."""
        normalized = float(np.clip(position, 0.0, 1.0))
        if self.scale == "log":
            low_log = math.log10(self.low_value)
            high_log = math.log10(self.high_value)
            return 10.0 ** (low_log + normalized * (high_log - low_log))
        return self.low_value + normalized * (self.high_value - self.low_value)

    def match_rgb(self, rgb: np.ndarray) -> ColorMatch:
        """Project an RGB colour onto the closest Lab-space palette segment."""
        query = srgb_to_lab(np.asarray(rgb, dtype=float).reshape(1, 3))[0]
        starts = self.palette_lab[:-1]
        deltas = self.palette_lab[1:] - starts
        lengths_squared = np.einsum("ij,ij->i", deltas, deltas)
        safe_lengths = np.where(lengths_squared > 1.0e-12, lengths_squared, 1.0)
        fractions = np.einsum("ij,ij->i", query - starts, deltas) / safe_lengths
        fractions = np.clip(fractions, 0.0, 1.0)
        projections = starts + fractions[:, None] * deltas
        distances = np.linalg.norm(projections - query, axis=1)
        best_index = int(np.argmin(distances))
        best_distance = float(distances[best_index])
        denominator = max(1, len(self.palette_lab) - 1)
        best_position = float((best_index + fractions[best_index]) / denominator)

        near_indices = np.flatnonzero(distances <= best_distance + 1.5)
        near_positions = np.asarray(
            [(index + fractions[index]) / denominator for index in near_indices],
            dtype=float,
        )
        ambiguous = bool(
            near_positions.size > 1
            and float(near_positions.max() - near_positions.min()) > 0.08
        )
        confidence = max(0.0, min(1.0, 1.0 - best_distance / self.maximum_distance))
        valid = best_distance <= self.maximum_distance and not ambiguous
        return ColorMatch(
            value=self.value_at(best_position),
            palette_position=best_position,
            distance=best_distance,
            confidence=confidence,
            ambiguous=ambiguous,
            valid=valid,
        )
