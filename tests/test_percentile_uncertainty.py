"""Probability calibration, normalized likelihoods, and asymmetric regression."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
from scipy.integrate import quad
from scipy.special import ndtri

from math_engine.calculus import MathOperationError
from math_engine.curve_fitting import fit_curve
from math_engine.uncertainty import QuantileNormal
from models.uncertainty import PercentileBounds


def sample(model: QuantileNormal, rng: np.random.Generator) -> np.ndarray:
    probability = rng.uniform(.000001, .999999, len(model.lower_width))
    low, high = -20*model.lower_width, 20*model.upper_width
    for _ in range(55):
        middle = (low + high)/2
        below = model.cdf(middle) < probability
        low, high = np.where(below, middle, low), np.where(below, high, middle)
    return (low + high)/2


class PercentileLikelihoodTests(unittest.TestCase):
    def test_exact_quantiles_and_full_probability_mass(self) -> None:
        for low, high in ((2., 4.), (.02, 40.), (40., .02), (3., 3.)):
            for probabilities in ((.16, .84), (.025, .95)):
                model = QuantileNormal(np.array([low]), np.array([high]), *probabilities)
                self.assertAlmostEqual(model.cdf(np.array([-low]))[0], probabilities[0], places=12)
                self.assertAlmostEqual(model.cdf(np.array([0.]))[0], .5, places=12)
                self.assertAlmostEqual(model.cdf(np.array([high]))[0], probabilities[1], places=12)
                mass = quad(lambda value: np.exp(-model.nll_score(np.array([value]))[0][0]),
                            -20*low, 20*high, points=[-low, 0, high], epsabs=1.e-8)[0]
                self.assertAlmostEqual(mass, 1., places=7)

    def test_monotone_cdf_and_likelihood_score(self) -> None:
        errors = np.linspace(-8, 15, 600)
        model = QuantileNormal(np.full(600, 2.), np.full(600, 4.))
        cdf = model.cdf(errors)
        self.assertTrue((np.diff(cdf) >= 0).all())
        score = model.nll_score(errors)[1]
        delta = 1.e-5
        numeric = (model.nll_score(errors + delta)[0] - model.nll_score(errors - delta)[0]) / (2*delta)
        np.testing.assert_allclose(score, numeric, atol=1.e-7, rtol=1.e-5)
        self.assertTrue((model.transform(errors)[1] > 0).all())

    def test_normal_limit_matches_existing_absolute_sigma_fit(self) -> None:
        rng = np.random.default_rng(43)
        x = np.linspace(0, 10, 80)
        y = 2*x + 3 + rng.normal(0, .4, len(x))
        frame = pd.DataFrame({"x": x, "y": y, "sigma": .4, "low": y + ndtri(.16)*.4, "high": y + ndtri(.84)*.4})
        legacy = fit_curve(frame, "x", "y", "linear", "trf", weight_column="sigma", absolute_sigma=True)
        result = fit_curve(frame, "x", "y", "linear", "trf", y_bounds=PercentileBounds("low", "high"))
        np.testing.assert_allclose(result.report.parameters, legacy.report.parameters, atol=1.e-6)
        np.testing.assert_allclose(result.report.covariance, legacy.report.covariance, rtol=.002, atol=1.e-8)
        self.assertEqual(result.report.method, "percentile")
        self.assertTrue(result.report.absolute_sigma)
        self.assertIn("median", result.report.to_text())
        self.assertIn("local Hessian", result.report.to_text())

    def test_asymmetric_measurement_likelihood_recovers_seeded_line(self) -> None:
        rng = np.random.default_rng(2026)
        x = np.linspace(0, 10, 350)
        model = QuantileNormal(np.full(len(x), .2), np.full(len(x), .7))
        y = 2*x + 3 + sample(model, rng)
        frame = pd.DataFrame({"x": x, "y": y, "low": y-.2, "high": y+.7})
        result = fit_curve(frame, "x", "y", "linear", "trf", y_bounds=PercentileBounds("low", "high"))
        np.testing.assert_allclose(result.report.parameters, (2., 3.), atol=.12)
        self.assertIsNotNone(result.report.negative_log_likelihood)
        self.assertIn("likelihood_residual", result.residual_frame)
        self.assertTrue(np.isfinite(result.report.standard_errors).all())
        np.testing.assert_allclose(result.residual_frame["y_lower_bound"], frame["low"])

    def test_asymmetric_x_and_y_use_latent_x_likelihood(self) -> None:
        rng = np.random.default_rng(12)
        true_x = np.linspace(1, 8, 50)
        x_model = QuantileNormal(np.full(50, .15), np.full(50, .3))
        y_model = QuantileNormal(np.full(50, .3), np.full(50, .5))
        x, y = true_x + sample(x_model, rng), 1.5*true_x + 2 + sample(y_model, rng)
        frame = pd.DataFrame({"x": x, "y": y, "xl": x-.15, "xh": x+.3, "yl": y-.3, "yh": y+.5})
        result = fit_curve(frame, "x", "y", "linear", "trf", x_bounds=PercentileBounds("xl", "xh"),
                           y_bounds=PercentileBounds("yl", "yh"))
        self.assertEqual(result.report.method, "percentile")
        self.assertIn("latent_x", result.residual_frame)
        self.assertGreater(np.max(np.abs(result.residual_frame["latent_x"] - x)), .01)
        np.testing.assert_allclose(result.report.parameters, (1.5, 2), atol=.3)
        self.assertTrue(np.isfinite(result.report.standard_errors).all())

    def test_reject_invalid_bounds_and_posterior_likelihood(self) -> None:
        frame = pd.DataFrame({"x": [0., 1., 2.], "y": [1., 2., 3.], "low": [0., 1., 2.], "high": [2., 3., 4.], "s": 1.})
        for changed in (frame.assign(low=frame.y), frame.assign(high=frame.y-1), frame.assign(high=np.nan)):
            with self.assertRaises((MathOperationError, ValueError)):
                fit_curve(changed, "x", "y", "linear", "trf", y_bounds=PercentileBounds("low", "high"))
        with self.assertRaisesRegex(MathOperationError, "posterior"):
            fit_curve(frame, "x", "y", "linear", "trf", y_bounds=PercentileBounds("low", "high", origin="posterior"))
        with self.assertRaisesRegex(MathOperationError, "either"):
            fit_curve(frame, "x", "y", "linear", "trf", y_bounds=PercentileBounds("low", "high"), weight_column="s")
        with self.assertRaisesRegex(MathOperationError, "median"):
            fit_curve(frame, "x", "y", "linear", "trf", y_bounds=PercentileBounds("low", "high", centre="mean"))

    def test_fixed_parameters_parameter_bounds_and_cancellation(self) -> None:
        x = np.linspace(0, 5, 20)
        y = 2*x + 3
        frame = pd.DataFrame({"x": x, "y": y, "low": y-1, "high": y+1})
        result = fit_curve(frame, "x", "y", "linear", "trf", initial_parameters=[2., 3.], fixed_parameters=[True, True],
                           y_bounds=PercentileBounds("low", "high"))
        self.assertEqual(result.report.parameters, (2., 3.))
        self.assertEqual(result.report.standard_errors, (0., 0.))
        def cancel() -> None:
            raise RuntimeError("Cancelled test")
        with self.assertRaisesRegex(MathOperationError, "Cancelled test"):
            fit_curve(frame, "x", "y", "linear", "trf", y_bounds=PercentileBounds("low", "high"), check_cancelled=cancel)

    def test_shared_composite_peak_likelihood_and_provenance(self) -> None:
        from math_engine.composite_peak_fit import build_peak_component_spec, fit_composite_peaks
        from math_engine.peak_detection import detect_peaks, PeakDetectionParameters
        x = np.linspace(-5, 5, 151)
        y = 4*np.exp(-.5*((x-.4)/.8)**2)
        detected = detect_peaks(x, y, y, PeakDetectionParameters(prominence=1.))
        specification = build_peak_component_spec(detected.peaks[0], "gaussian", x)
        result = fit_composite_peaks(x, y, y, [specification], uncertainty=QuantileNormal.normal(np.full(len(x), .1)))
        self.assertTrue(result.converged)
        self.assertGreater(result.r_squared, .9999)
        self.assertEqual(result.provenance["uncertainty"]["distribution"], "quantile_normal")
        self.assertIn("local Hessian", " ".join(result.warnings))

    def test_covariance_respects_partial_fixed_parameters_and_cancellation_contract(self) -> None:
        from core.jobs import JobCancelled
        x = np.linspace(0, 5, 30)
        y = 2*x+3+np.random.default_rng(8).normal(0, .1, len(x))
        frame = pd.DataFrame({"x": x, "y": y, "low": y-.3, "high": y+.3})
        result = fit_curve(frame, "x", "y", "linear", "trf", initial_parameters=[1., 3.],
                           lower_bounds=[0., None], upper_bounds=[4., None], fixed_parameters=[False, True],
                           y_bounds=PercentileBounds("low", "high"))
        self.assertEqual(result.report.parameters[1], 3.)
        self.assertEqual(result.report.standard_errors[1], 0.)
        self.assertTrue(0 < result.report.parameters[0] < 4)
        def cancel() -> None:
            raise JobCancelled()
        with self.assertRaises(JobCancelled):
            fit_curve(frame, "x", "y", "linear", "trf", y_bounds=PercentileBounds("low", "high"), check_cancelled=cancel)

    def test_parameters_at_constraints_do_not_report_misleading_local_errors(self) -> None:
        x = np.linspace(0, 5, 30)
        y = 2*x+3
        frame = pd.DataFrame({"x": x, "y": y, "low": y-.3, "high": y+.3})
        result = fit_curve(frame, "x", "y", "linear", "trf", initial_parameters=[1., 3.],
                           lower_bounds=[0., None], upper_bounds=[1.5, None], fixed_parameters=[False, True],
                           y_bounds=PercentileBounds("low", "high"))
        self.assertAlmostEqual(result.report.parameters[0], 1.5)
        self.assertTrue(np.isnan(result.report.standard_errors[0]))
        self.assertIn("constraint", " ".join(result.report.warnings))


if __name__ == "__main__":
    unittest.main()
