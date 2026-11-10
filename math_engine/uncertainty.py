"""Calibrated percentile likelihoods with smooth CDFs and Gaussian tails.

F(e)=Phi(g(e)), with g(-lower_width)=Phi^-1(p_lower), g(0)=0 and
g(upper_width)=Phi^-1(p_upper). Each interval uses quintic Hermite interpolation
with zero second derivatives at the knots, outer secant slopes, and a harmonic
central slope. Positive slopes remain monotone; linear tails give full support.
The normalized density is phi(g(e))*g'(e). Its Jacobian is part of the likelihood.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr, ndtri

from math_engine.calculus import MathOperationError


@dataclass(frozen=True)
class QuantileNormal:
    lower_width: np.ndarray
    upper_width: np.ndarray
    lower_probability: float = .16
    upper_probability: float = .84

    def __post_init__(self) -> None:
        low, high = np.asarray(self.lower_width, dtype=float), np.asarray(self.upper_width, dtype=float)
        if low.ndim != 1 or low.shape != high.shape or not np.isfinite(low).all() or not np.isfinite(high).all():
            raise MathOperationError("Percentile widths must be finite, aligned one-dimensional arrays.")
        if (low <= 0).any() or (high <= 0).any():
            raise MathOperationError("Fitting requires strictly lower/upper bounds around every median.")
        if not 0 < self.lower_probability < .5 < self.upper_probability < 1:
            raise MathOperationError("Invalid percentile probabilities.")
        object.__setattr__(self, "lower_width", low.copy())
        object.__setattr__(self, "upper_width", high.copy())

    @classmethod
    def normal(cls, sigma: np.ndarray) -> QuantileNormal:
        return cls(np.asarray(sigma) * -ndtri(.16), np.asarray(sigma) * ndtri(.84))

    def transform(self, error: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        error = np.asarray(error, dtype=float)
        low, high = self.lower_width, self.upper_width
        a, b = -ndtri(self.lower_probability) / low, ndtri(self.upper_probability) / high
        middle = 2 * a * b / (a + b)
        left = error < 0
        t = np.where(left, np.clip((error + low) / low, 0, 1), np.clip(error / high, 0, 1))
        # h11 on the left and h10 on the right set only the central slope.
        h = np.where(left, -4*t**3 + 7*t**4 - 3*t**5, t - 6*t**3 + 8*t**4 - 3*t**5)
        dh = np.where(left, -12*t**2 + 28*t**3 - 15*t**4, 1 - 18*t**2 + 32*t**3 - 15*t**4)
        ddh = np.where(left, -24*t + 84*t**2 - 60*t**3, -36*t + 96*t**2 - 60*t**3)
        slope, width = np.where(left, a, b), np.where(left, low, high)
        ratio = middle / slope - 1
        inside = (error >= -low) & (error <= high)
        z = slope * error + np.where(inside, slope * width * ratio * h, 0)
        derivative = slope * (1 + np.where(inside, ratio * dh, 0))
        second = np.where(inside, slope / width * ratio * ddh, 0)
        return z, derivative, second

    def nll_score(self, error: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return normalized negative log density and its derivative in error."""
        z, derivative, second = self.transform(error)
        return .5*z*z + .5*np.log(2*np.pi) - np.log(derivative), z*derivative - second/derivative

    def cdf(self, error: np.ndarray) -> np.ndarray:
        return ndtr(self.transform(error)[0])


def likelihood_fit(
    function: Callable[..., np.ndarray], x: np.ndarray, y: np.ndarray,
    initial: np.ndarray, lower: np.ndarray, upper: np.ndarray, free: np.ndarray,
    y_error: QuantileNormal, x_error: QuantileNormal | None = None,
    *, check_cancelled: Callable[[], None] | None = None, maximum_iterations: int = 2000,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, list[str]]:
    """Fit model medians, optionally profiling independent latent true X values.

    Independent X errors use a joint errors-in-variables likelihood. Covariance
    is a local observed-Hessian approximation; a diagonal latent-X block is
    eliminated by a Schur complement without constructing an N-by-N matrix.
    """
    x, y, initial = np.asarray(x, dtype=float), np.asarray(y, dtype=float), np.asarray(initial, dtype=float)
    free = np.asarray(free, dtype=int)
    count = len(free)
    step_factor = np.cbrt(np.finfo(float).eps)

    def evaluate(values: np.ndarray) -> tuple[float, np.ndarray]:
        if check_cancelled is not None:
            check_cancelled()
        parameters = initial.copy()
        parameters[free] = values[:count]
        latent = values[count:] if x_error is not None else x
        with np.errstate(all="ignore"):
            predicted = np.asarray(function(latent, *parameters), dtype=float)
            if predicted.shape != y.shape or not np.isfinite(predicted).all():
                return 1.e200, np.zeros_like(values)
            nll, score = y_error.nll_score(y - predicted)
            gradient = np.empty_like(values)
            for position, index in enumerate(free):
                delta = step_factor * max(1., abs(parameters[index]))
                high, low = parameters.copy(), parameters.copy()
                high[index], low[index] = min(parameters[index] + delta, upper[index]), max(parameters[index] - delta, lower[index])
                derivative = (function(latent, *high) - function(latent, *low)) / (high[index] - low[index])
                gradient[position] = -np.dot(score, derivative)
            if x_error is not None:
                x_nll, x_score = x_error.nll_score(x - latent)
                delta = step_factor * np.maximum(1., np.abs(latent))
                derivative = (function(latent + delta, *parameters) - function(latent - delta, *parameters)) / (2*delta)
                gradient[count:] = -x_score - score*derivative
                nll = nll + x_nll
        if not np.isfinite(nll).all() or not np.isfinite(gradient).all():
            return 1.e200, np.zeros_like(values)
        return float(nll.sum()), gradient

    starting = np.concatenate((initial[free], x)) if x_error is not None else initial[free].copy()
    bounds = list(zip(lower[free], upper[free])) + ([(None, None)] * len(x) if x_error is not None else [])
    if len(starting):
        starts = [starting]
        if count:
            # Calibrated asymmetric densities need not be log-concave. Avoid
            # accepting an exactly stationary median curve at a saddle point.
            for direction in (-1., 1.):
                trial = starting.copy()
                trial[:count] += direction * .025 * np.maximum(1., np.abs(starting[:count]))
                trial[:count] = np.clip(trial[:count], lower[free], upper[free])
                starts.append(trial)
        solutions = [minimize(evaluate, start, jac=True, bounds=bounds, method="L-BFGS-B",
                              options={"maxiter": maximum_iterations, "maxls": 50, "ftol": 1.e-12, "gtol": 1.e-7})
                     for start in starts]
        successful = [candidate for candidate in solutions if candidate.success]
        solution = min(successful or solutions, key=lambda candidate: candidate.fun)
        if not np.isfinite(solution.fun) or solution.fun >= 1.e190:
            raise MathOperationError("Percentile likelihood is not finite; check model domain and starting parameters.")
        if not solution.success:
            raise MathOperationError(f"Percentile likelihood did not converge: {solution.message}")
        optimum = solution.x
    else:
        optimum = starting
    total_nll = evaluate(optimum)[0]
    parameters = initial.copy()
    parameters[free] = optimum[:count]
    latent = optimum[count:].copy() if x_error is not None else x.copy()
    covariance = np.zeros((len(initial), len(initial)))
    messages = ["Quantile-normal measurement model: calibrated percentiles, median centres, Gaussian tails; independent points.",
                "Parameter errors and bands use a local Hessian approximation, not bootstrap percentile intervals."]
    if count:
        tolerance = step_factor * np.maximum(1., np.abs(parameters[free]))
        on_bound = (np.abs(parameters[free] - lower[free]) <= tolerance) | (np.abs(upper[free] - parameters[free]) <= tolerance)
        if on_bound.any():
            covariance[np.ix_(free, free)] = np.nan
            messages.append("A parameter is at its constraint; local symmetric parameter errors/bands are unavailable.")
            return parameters, covariance, latent, total_nll, messages
    if count:
        hessian = np.empty((count, count))
        cross = np.empty((len(x), count)) if x_error is not None else None
        for column in range(count):
            delta = step_factor * max(1., abs(optimum[column]))
            high, low = optimum.copy(), optimum.copy()
            high[column] += delta
            low[column] -= delta
            derivative = (evaluate(high)[1] - evaluate(low)[1]) / (2*delta)
            hessian[:, column] = derivative[:count]
            if cross is not None:
                cross[:, column] = derivative[count:]
        if x_error is not None:
            delta = step_factor * np.maximum(1., np.abs(latent))
            high, low = optimum.copy(), optimum.copy()
            high[count:] += delta
            low[count:] -= delta
            diagonal = (evaluate(high)[1][count:] - evaluate(low)[1][count:]) / (2*delta)
            if np.any(diagonal <= 0):
                hessian[:] = np.nan
            else:
                hessian -= cross.T @ (cross / diagonal[:, None])
        hessian = (hessian + hessian.T) / 2
        try:
            eigenvalues = np.linalg.eigvalsh(hessian)
            if not np.isfinite(hessian).all() or np.min(eigenvalues) <= max(1.e-12, np.max(eigenvalues)*1.e-10):
                raise np.linalg.LinAlgError()
            covariance[np.ix_(free, free)] = np.linalg.inv(hessian)
        except np.linalg.LinAlgError:
            covariance[np.ix_(free, free)] = np.nan
            messages.append("Local likelihood curvature is singular/nonpositive; parameter errors are unavailable.")
    return parameters, covariance, latent, total_nll, messages
