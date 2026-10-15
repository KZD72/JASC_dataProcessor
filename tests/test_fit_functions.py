"""Tests for the categorized analytical curve-fitting registry."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from math_engine.curve_fitting import fit_curve
from models.fit_functions import (
    FIT_MODELS,
    FIT_MODEL_CATEGORIES,
    available_fit_categories,
    available_fit_models,
    default_initial_parameters,
    get_fit_model,
)


class FitFunctionRegistryTests(unittest.TestCase):
    """Keep the broad model catalog numerically usable and well organized."""

    def test_registry_exposes_large_categorized_catalog(self) -> None:
        self.assertGreaterEqual(len(FIT_MODELS), 60)
        categories = available_fit_categories()
        self.assertEqual(categories, [name for name in FIT_MODEL_CATEGORIES if name != "Custom"])
        for category in categories:
            models = available_fit_models(category=category)
            self.assertTrue(models, category)
            self.assertTrue(all(model.category == category for model in models))

    def test_every_default_model_evaluates_to_finite_vector(self) -> None:
        x_values = np.linspace(0.1, 2.0, 41)
        for key, model in FIT_MODELS.items():
            with self.subTest(model=key):
                values = np.asarray(model.function(x_values, *model.default_initial), dtype=float)
                self.assertEqual(values.shape, x_values.shape)
                self.assertTrue(np.isfinite(values).all())
                self.assertEqual(len(model.parameter_names), len(model.default_initial))
                self.assertEqual(len(model.parameter_names), len(model.default_lower))
                self.assertEqual(len(model.parameter_names), len(model.default_upper))
                self.assertEqual(len(model.parameter_names), len(model.parameter_roles))
                self.assertTrue(model.description)

    def test_peak_registry_exposes_semantic_component_roles(self) -> None:
        gaussian = get_fit_model("gaussian")
        self.assertTrue(gaussian.is_peak)
        self.assertEqual(
            gaussian.parameter_roles,
            ("height", "center", "width", "offset"),
        )
        self.assertFalse(get_fit_model("linear").is_peak)

    def test_peak_widths_and_mixing_parameters_have_recommended_bounds(self) -> None:
        gaussian = get_fit_model("gaussian")
        self.assertGreater(gaussian.default_lower[gaussian.parameter_names.index("sigma")], 0.0)
        pseudo_voigt = get_fit_model("pseudo_voigt")
        eta_index = pseudo_voigt.parameter_names.index("eta")
        self.assertEqual(pseudo_voigt.default_lower[eta_index], 0.0)
        self.assertEqual(pseudo_voigt.default_upper[eta_index], 1.0)
        fano = get_fit_model("fano_peak")
        self.assertEqual(
            fano.parameter_roles,
            ("scale", "resonance_center", "resonance_width", "fano_q", "offset"),
        )
        self.assertGreater(fano.default_lower[fano.parameter_names.index("amplitude")], 0.0)

    def test_peak_profiles_use_the_requested_center_and_height(self) -> None:
        x_values = np.asarray([-1.0, 0.0, 1.0])
        for key, parameters in {
            "gaussian": (3.0, 0.0, 0.5, 2.0),
            "lorentzian": (3.0, 0.0, 0.5, 2.0),
            "voigt": (3.0, 0.0, 0.5, 0.25, 2.0),
            "pearson_vii": (3.0, 0.0, 0.5, 2.0, 2.0),
            "sech_squared": (3.0, 0.0, 0.5, 2.0),
            "laplace_peak": (3.0, 0.0, 0.5, 2.0),
        }.items():
            with self.subTest(model=key):
                values = get_fit_model(key).function(x_values, *parameters)
                self.assertAlmostEqual(float(values[1]), 5.0, places=10)
                self.assertAlmostEqual(float(values[0]), float(values[2]), places=10)

    def test_peak_initialization_detects_negative_peaks(self) -> None:
        x_values = np.linspace(-5.0, 5.0, 101)
        y_values = 4.0 - 2.5 * np.exp(-0.5 * ((x_values - 1.2) / 0.6) ** 2)
        amplitude, center, _width, offset = default_initial_parameters(
            "gaussian",
            x_values,
            y_values,
        )
        self.assertLess(amplitude, 0.0)
        self.assertAlmostEqual(center, 1.2, places=1)
        self.assertAlmostEqual(offset, 4.0, places=2)

    def test_representative_peak_models_recover_synthetic_curves(self) -> None:
        x_values = np.linspace(-5.0, 5.0, 201)
        cases = {
            "gaussian": (3.0, 0.7, 0.8, 1.2),
            "voigt": (3.0, 0.7, 0.6, 0.3, 1.2),
            "pearson_vii": (3.0, 0.7, 0.8, 2.0, 1.2),
            "emg": (5.0, 0.5, 0.4, 0.8, 1.2),
        }
        for key, parameters in cases.items():
            with self.subTest(model=key):
                y_values = get_fit_model(key).function(x_values, *parameters)
                result = fit_curve(
                    pd.DataFrame({"x": x_values, "y": y_values}),
                    "x",
                    "y",
                    key,
                    "trf",
                    include_confidence_band=False,
                )
                self.assertGreater(result.report.r_squared, 0.999999)


if __name__ == "__main__":
    unittest.main()
