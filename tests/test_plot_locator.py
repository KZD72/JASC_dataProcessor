"""Unit tests for inverse plot-locator interpolation."""

from __future__ import annotations

import unittest

import pandas as pd

from ui.plot_canvas import PlotCanvas
from ui.plot_tab import PlotTab


class InversePlotLocatorTests(unittest.TestCase):
    """Verify scientifically meaningful Y-to-X curve intersections."""

    def test_non_monotonic_curve_returns_every_intersection(self) -> None:
        x = pd.Series([0.0, 1.0, 2.0, 3.0, 4.0])
        y = pd.Series([0.0, 2.0, 0.0, 2.0, 0.0])
        matches = PlotCanvas._interpolate_x_values(x, y, 1.0)
        self.assertEqual(matches, [0.5, 1.5, 2.5, 3.5])

    def test_shared_vertex_is_not_duplicated(self) -> None:
        x = pd.Series([0.0, 1.0, 2.0])
        y = pd.Series([0.0, 1.0, 0.0])
        matches = PlotCanvas._interpolate_x_values(x, y, 1.0)
        self.assertEqual(matches, [1.0])

    def test_horizontal_overlap_is_reported_as_ambiguous(self) -> None:
        x = pd.Series([0.0, 1.0, 2.0])
        y = pd.Series([1.0, 1.0, 2.0])
        with self.assertRaisesRegex(ValueError, "horizontal segment"):
            PlotCanvas._interpolate_x_values(x, y, 1.0)

    def test_out_of_range_y_is_rejected(self) -> None:
        x = pd.Series([0.0, 1.0, 2.0])
        y = pd.Series([0.0, 1.0, 0.0])
        with self.assertRaisesRegex(ValueError, "outside the data range"):
            PlotCanvas._interpolate_x_values(x, y, 2.0)

    def test_version_one_locator_defaults_to_x_to_y(self) -> None:
        locator = PlotTab._plot_locator_from_state({
            "series_index": 0,
            "x_value": 1.25,
            "marker": "o",
        })
        self.assertEqual(locator.lookup_mode, "x_to_y")
        self.assertEqual(locator.x_value, 1.25)


if __name__ == "__main__":
    unittest.main()
