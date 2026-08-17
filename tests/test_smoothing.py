"""Unit tests for the worksheet smoothing engine."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from math_engine.calculus import MathOperationError
from math_engine.smoothing import SmoothingParameters, smooth_column, smooth_values


class SmoothingTests(unittest.TestCase):
    """Exercise algorithms and worksheet row alignment."""

    def test_adjacent_average_preserves_constant_signal(self) -> None:
        x = np.arange(20, dtype=float)
        y = np.full(20, 4.25)
        result = smooth_values(
            x, y, "adjacent_average", SmoothingParameters(window_length=6)
        )
        np.testing.assert_allclose(result, y)

    def test_derivative_integration_recovers_quadratic_and_endpoints(self) -> None:
        x = np.linspace(-2.0, 3.0, 101)
        y = 2.0 * x**2 - 3.0 * x + 7.0
        result = smooth_values(
            x,
            y,
            "derivative_integral",
            SmoothingParameters(
                window_length=11,
                polynomial_order=3,
                derivative_median_window=1,
                preserve_endpoints=True,
            ),
        )
        self.assertAlmostEqual(result[0], y[0], places=12)
        self.assertAlmostEqual(result[-1], y[-1], places=12)
        np.testing.assert_allclose(result, y, rtol=1.0e-8, atol=1.0e-8)

    def test_even_spacing_is_required_for_derivative_reconstruction(self) -> None:
        x = np.asarray([0.0, 1.0, 2.1, 3.0, 4.0])
        y = x**2
        with self.assertRaisesRegex(MathOperationError, "evenly spaced"):
            smooth_values(
                x,
                y,
                "derivative_integral",
                SmoothingParameters(window_length=3, polynomial_order=2),
            )

    def test_derivative_reconstruction_accepts_every_smoothing_method(self) -> None:
        x = np.linspace(0.0, 8.0, 161)
        y = np.sin(x) + 0.02 * np.cos(29.0 * x)
        for method in ("adjacent_average", "moving_median", "savgol", "lowess", "fft"):
            with self.subTest(method=method):
                result = smooth_values(
                    x,
                    y,
                    "derivative_integral",
                    SmoothingParameters(
                        window_length=9,
                        polynomial_order=3,
                        lowess_fraction=0.15,
                        fft_cutoff_fraction=0.15,
                        derivative_smoothing_method=method,
                        preserve_endpoints=True,
                    ),
                )
                self.assertEqual(result.shape, y.shape)
                self.assertTrue(np.isfinite(result).all())
                self.assertAlmostEqual(result[0], y[0], places=12)
                self.assertAlmostEqual(result[-1], y[-1], places=12)

    def test_lowess_runs_and_preserves_shape(self) -> None:
        x = np.linspace(0.0, 5.0, 51)
        y = np.sin(x) + 0.05 * np.cos(17.0 * x)
        result = smooth_values(
            x,
            y,
            "lowess",
            SmoothingParameters(lowess_fraction=0.2, lowess_iterations=1),
        )
        self.assertEqual(result.shape, y.shape)
        self.assertTrue(np.isfinite(result).all())

    def test_smooth_column_restores_original_row_alignment(self) -> None:
        frame = pd.DataFrame({
            "x": [0.0, 1.0, 2.0, 3.0, 4.0],
            "y": [1.0, np.nan, 3.0, 5.0, 7.0],
        })
        result = smooth_column(
            frame,
            x_column="x",
            y_column="y",
            method="adjacent_average",
            target_column="smooth",
            parameters=SmoothingParameters(window_length=2),
        )
        self.assertEqual(result.column_name, "smooth")
        self.assertTrue(np.isnan(frame.loc[1, "smooth"]))
        self.assertEqual(result.values_written, 4)


if __name__ == "__main__":
    unittest.main()
