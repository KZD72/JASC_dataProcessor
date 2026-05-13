"""Analytical function registry for curve fitting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy import special


ArrayFunction = Callable[..., np.ndarray]


@dataclass(frozen=True, slots=True)
class FitModel:
    """Metadata for a curve-fitting model."""

    key: str
    name: str
    equation: str
    parameter_names: tuple[str, ...]
    function: ArrayFunction
    default_initial: tuple[float, ...]


def linear(x: np.ndarray, a: float, b: float) -> np.ndarray:
    """Return a linear model, a*x + b."""
    return a * x + b


def quadratic(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Return a quadratic polynomial model."""
    return a * x**2 + b * x + c


def cubic(x: np.ndarray, a: float, b: float, c: float, d: float) -> np.ndarray:
    """Return a cubic polynomial model."""
    return a * x**3 + b * x**2 + c * x + d


def exponential_growth(x: np.ndarray, a: float, k: float, c: float) -> np.ndarray:
    """Return a single exponential growth model."""
    return a * np.exp(k * x) + c


def exponential_decay(x: np.ndarray, a: float, tau: float, c: float) -> np.ndarray:
    """Return a single exponential decay model."""
    return a * np.exp(-x / _safe_width(tau)) + c


def double_exponential_decay(
    x: np.ndarray,
    a1: float,
    tau1: float,
    a2: float,
    tau2: float,
    c: float,
) -> np.ndarray:
    """Return a double exponential decay model."""
    return a1 * np.exp(-x / _safe_width(tau1)) + a2 * np.exp(-x / _safe_width(tau2)) + c


def gaussian(
    x: np.ndarray,
    amplitude: float,
    center: float,
    sigma: float,
    offset: float,
) -> np.ndarray:
    """Return a Gaussian peak with offset."""
    width = _safe_width(sigma)
    return amplitude * np.exp(-0.5 * ((x - center) / width) ** 2) + offset


def lorentzian(
    x: np.ndarray,
    amplitude: float,
    center: float,
    gamma: float,
    offset: float,
) -> np.ndarray:
    """Return a Lorentzian peak with offset."""
    width = _safe_width(gamma)
    return amplitude * (width**2 / ((x - center) ** 2 + width**2)) + offset


def pseudo_voigt(
    x: np.ndarray,
    amplitude: float,
    center: float,
    sigma: float,
    eta: float,
    offset: float,
) -> np.ndarray:
    """Return a pseudo-Voigt blend of Lorentzian and Gaussian peaks."""
    mix = float(np.clip(eta, 0.0, 1.0))
    return mix * lorentzian(x, amplitude, center, sigma, 0.0) + (1.0 - mix) * gaussian(
        x,
        amplitude,
        center,
        sigma,
        0.0,
    ) + offset


def sine(
    x: np.ndarray,
    amplitude: float,
    frequency: float,
    phase: float,
    offset: float,
) -> np.ndarray:
    """Return a sinusoidal model with offset."""
    return amplitude * np.sin(2.0 * np.pi * frequency * x + phase) + offset


def damped_sine(
    x: np.ndarray,
    amplitude: float,
    frequency: float,
    phase: float,
    tau: float,
    offset: float,
) -> np.ndarray:
    """Return an exponentially damped sine model."""
    return amplitude * np.exp(-x / _safe_width(tau)) * np.sin(2.0 * np.pi * frequency * x + phase) + offset


def logistic(
    x: np.ndarray,
    amplitude: float,
    rate: float,
    midpoint: float,
    offset: float,
) -> np.ndarray:
    """Return a logistic sigmoid model."""
    return offset + amplitude / (1.0 + np.exp(-rate * (x - midpoint)))


def gompertz(
    x: np.ndarray,
    amplitude: float,
    scale: float,
    rate: float,
    offset: float,
) -> np.ndarray:
    """Return a Gompertz growth model."""
    return offset + amplitude * np.exp(-scale * np.exp(-rate * x))


def erf_step(
    x: np.ndarray,
    amplitude: float,
    center: float,
    width: float,
    offset: float,
) -> np.ndarray:
    """Return an error-function step model."""
    return offset + 0.5 * amplitude * (1.0 + special.erf((x - center) / _safe_width(width)))


def power_law(x: np.ndarray, a: float, exponent: float, c: float) -> np.ndarray:
    """Return a power-law model with offset."""
    safe_x = np.clip(x, np.finfo(float).tiny, None)
    return a * np.power(safe_x, exponent) + c


def log_normal(
    x: np.ndarray,
    amplitude: float,
    mu: float,
    sigma: float,
    offset: float,
) -> np.ndarray:
    """Return a log-normal peak model."""
    safe_x = np.clip(x, np.finfo(float).tiny, None)
    width = _safe_width(sigma)
    return amplitude * np.exp(-0.5 * ((np.log(safe_x) - mu) / width) ** 2) + offset


def weibull(
    x: np.ndarray,
    amplitude: float,
    shape: float,
    scale: float,
    offset: float,
) -> np.ndarray:
    """Return a Weibull saturation model."""
    safe_x = np.clip(x, 0.0, None)
    safe_scale = abs(_safe_width(scale))
    safe_shape = abs(_safe_width(shape))
    return amplitude * (1.0 - np.exp(-((safe_x / safe_scale) ** safe_shape))) + offset


def heidler(
    x: np.ndarray,
    amplitude: float,
    tau1: float,
    tau2: float,
    n: float,
    offset: float,
) -> np.ndarray:
    """Return a Heidler impulse model."""
    safe_x = np.clip(x, 0.0, None)
    rise = (safe_x / abs(_safe_width(tau1))) ** abs(_safe_width(n))
    return offset + amplitude * (rise / (1.0 + rise)) * np.exp(-safe_x / abs(_safe_width(tau2)))


def bessel_j(
    x: np.ndarray,
    amplitude: float,
    order: float,
    scale: float,
    offset: float,
) -> np.ndarray:
    """Return a scaled Bessel function of the first kind."""
    return amplitude * special.jv(order, scale * x) + offset


def bessel_y(
    x: np.ndarray,
    amplitude: float,
    order: float,
    scale: float,
    offset: float,
) -> np.ndarray:
    """Return a scaled Bessel function of the second kind."""
    return amplitude * special.yv(order, scale * x) + offset


def stretched_exponential(
    x: np.ndarray,
    amplitude: float,
    tau: float,
    beta: float,
    offset: float,
) -> np.ndarray:
    """Return a stretched exponential decay model."""
    safe_x = np.clip(x, 0.0, None)
    return amplitude * np.exp(-((safe_x / abs(_safe_width(tau))) ** beta)) + offset


def asymmetric_gaussian(
    x: np.ndarray,
    amplitude: float,
    center: float,
    sigma_l: float,
    sigma_r: float,
    offset: float,
) -> np.ndarray:
    """Return an asymmetric Gaussian peak with separate left/right widths."""
    sigma = np.where(x < center, abs(_safe_width(sigma_l)), abs(_safe_width(sigma_r)))
    return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2) + offset


FIT_MODELS: dict[str, FitModel] = {
    "linear": FitModel("linear", "Linear", "a*x + b", ("a", "b"), linear, (1.0, 0.0)),
    "quadratic": FitModel(
        "quadratic",
        "Quadratic",
        "a*x**2 + b*x + c",
        ("a", "b", "c"),
        quadratic,
        (1.0, 1.0, 0.0),
    ),
    "cubic": FitModel(
        "cubic",
        "Cubic",
        "a*x**3 + b*x**2 + c*x + d",
        ("a", "b", "c", "d"),
        cubic,
        (1.0, 1.0, 1.0, 0.0),
    ),
    "exponential_growth": FitModel(
        "exponential_growth",
        "Exponential growth",
        "a*exp(k*x) + c",
        ("a", "k", "c"),
        exponential_growth,
        (1.0, 0.1, 0.0),
    ),
    "exponential_decay": FitModel(
        "exponential_decay",
        "Exponential decay",
        "a*exp(-x/tau) + c",
        ("a", "tau", "c"),
        exponential_decay,
        (1.0, 1.0, 0.0),
    ),
    "double_exponential_decay": FitModel(
        "double_exponential_decay",
        "Double exponential decay",
        "a1*exp(-x/tau1) + a2*exp(-x/tau2) + c",
        ("a1", "tau1", "a2", "tau2", "c"),
        double_exponential_decay,
        (1.0, 1.0, 0.5, 5.0, 0.0),
    ),
    "gaussian": FitModel(
        "gaussian",
        "Gaussian",
        "amplitude*exp(-0.5*((x-center)/sigma)**2) + offset",
        ("amplitude", "center", "sigma", "offset"),
        gaussian,
        (1.0, 0.0, 1.0, 0.0),
    ),
    "lorentzian": FitModel(
        "lorentzian",
        "Lorentzian",
        "amplitude*gamma**2/((x-center)**2 + gamma**2) + offset",
        ("amplitude", "center", "gamma", "offset"),
        lorentzian,
        (1.0, 0.0, 1.0, 0.0),
    ),
    "pseudo_voigt": FitModel(
        "pseudo_voigt",
        "Pseudo-Voigt",
        "eta*Lorentzian + (1-eta)*Gaussian + offset",
        ("amplitude", "center", "sigma", "eta", "offset"),
        pseudo_voigt,
        (1.0, 0.0, 1.0, 0.5, 0.0),
    ),
    "sine": FitModel(
        "sine",
        "Sine",
        "amplitude*sin(2*pi*frequency*x + phase) + offset",
        ("amplitude", "frequency", "phase", "offset"),
        sine,
        (1.0, 1.0, 0.0, 0.0),
    ),
    "damped_sine": FitModel(
        "damped_sine",
        "Damped sine",
        "amplitude*exp(-x/tau)*sin(2*pi*frequency*x + phase) + offset",
        ("amplitude", "frequency", "phase", "tau", "offset"),
        damped_sine,
        (1.0, 1.0, 0.0, 10.0, 0.0),
    ),
    "logistic": FitModel(
        "logistic",
        "Logistic",
        "offset + amplitude/(1 + exp(-rate*(x-midpoint)))",
        ("amplitude", "rate", "midpoint", "offset"),
        logistic,
        (1.0, 1.0, 0.0, 0.0),
    ),
    "gompertz": FitModel(
        "gompertz",
        "Gompertz",
        "offset + amplitude*exp(-scale*exp(-rate*x))",
        ("amplitude", "scale", "rate", "offset"),
        gompertz,
        (1.0, 1.0, 1.0, 0.0),
    ),
    "erf_step": FitModel(
        "erf_step",
        "Error-function step",
        "offset + 0.5*amplitude*(1 + erf((x-center)/width))",
        ("amplitude", "center", "width", "offset"),
        erf_step,
        (1.0, 0.0, 1.0, 0.0),
    ),
    "power_law": FitModel(
        "power_law",
        "Power law",
        "a*x**exponent + c",
        ("a", "exponent", "c"),
        power_law,
        (1.0, 1.0, 0.0),
    ),
    "log_normal": FitModel(
        "log_normal",
        "Log-normal peak",
        "amplitude*exp(-0.5*((log(x)-mu)/sigma)**2) + offset",
        ("amplitude", "mu", "sigma", "offset"),
        log_normal,
        (1.0, 0.0, 1.0, 0.0),
    ),
    "weibull": FitModel(
        "weibull",
        "Weibull saturation",
        "amplitude*(1 - exp(-(x/scale)**shape)) + offset",
        ("amplitude", "shape", "scale", "offset"),
        weibull,
        (1.0, 2.0, 1.0, 0.0),
    ),
    "heidler": FitModel(
        "heidler",
        "Heidler impulse",
        "offset + amplitude*((x/tau1)**n/(1+(x/tau1)**n))*exp(-x/tau2)",
        ("amplitude", "tau1", "tau2", "n", "offset"),
        heidler,
        (1.0, 1.0, 10.0, 2.0, 0.0),
    ),
    "bessel_j": FitModel(
        "bessel_j",
        "Bessel J",
        "amplitude*J_order(scale*x) + offset",
        ("amplitude", "order", "scale", "offset"),
        bessel_j,
        (1.0, 0.0, 1.0, 0.0),
    ),
    "bessel_y": FitModel(
        "bessel_y",
        "Bessel Y",
        "amplitude*Y_order(scale*x) + offset",
        ("amplitude", "order", "scale", "offset"),
        bessel_y,
        (1.0, 0.0, 1.0, 0.0),
    ),
    "stretched_exponential": FitModel(
        "stretched_exponential",
        "Stretched exponential",
        "amplitude*exp(-(x/tau)**beta) + offset",
        ("amplitude", "tau", "beta", "offset"),
        stretched_exponential,
        (1.0, 1.0, 0.5, 0.0),
    ),
    "asymmetric_gaussian": FitModel(
        "asymmetric_gaussian",
        "Asymmetric Gaussian",
        "amplitude*exp(-0.5*((x-center)/sigma)**2) + offset",
        ("amplitude", "center", "sigma_l", "sigma_r", "offset"),
        asymmetric_gaussian,
        (1.0, 0.0, 1.0, 1.0, 0.0),
    ),
}


def available_fit_models() -> list[FitModel]:
    """Return fit models in UI order."""
    return list(FIT_MODELS.values())


def get_fit_model(model_key: str) -> FitModel:
    """Return one fit model by key."""
    try:
        return FIT_MODELS[model_key]
    except KeyError as exc:
        raise ValueError(f"Unknown fit model: {model_key}") from exc


def default_initial_parameters(
    model_key: str,
    x_values: np.ndarray | None = None,
    y_values: np.ndarray | None = None,
) -> tuple[float, ...]:
    """Return practical initial parameters for a model and optional data."""
    model = get_fit_model(model_key)
    if x_values is None or y_values is None or len(x_values) == 0 or len(y_values) == 0:
        return model.default_initial

    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    x_min = float(np.nanmin(x))
    x_max = float(np.nanmax(x))
    x_range = max(x_max - x_min, 1.0)
    y_min = float(np.nanmin(y))
    y_max = float(np.nanmax(y))
    y_mean = float(np.nanmean(y))
    amplitude = y_max - y_min if y_max != y_min else 1.0
    center = float(x[np.nanargmax(y)]) if len(y) else (x_min + x_max) / 2.0
    offset = y_min

    if model_key == "linear" and len(x) >= 2:
        slope, intercept = np.polyfit(x, y, 1)
        return (float(slope), float(intercept))
    if model_key == "quadratic" and len(x) >= 3:
        return tuple(float(value) for value in np.polyfit(x, y, 2))
    if model_key == "cubic" and len(x) >= 4:
        return tuple(float(value) for value in np.polyfit(x, y, 3))
    if model_key in {"gaussian", "lorentzian", "pseudo_voigt"}:
        width = max(x_range / 6.0, np.finfo(float).eps)
        if model_key == "pseudo_voigt":
            return (amplitude, center, width, 0.5, offset)
        return (amplitude, center, width, offset)
    if model_key == "sine":
        return (amplitude / 2.0, 1.0 / x_range, 0.0, y_mean)
    if model_key == "damped_sine":
        return (amplitude / 2.0, 1.0 / x_range, 0.0, x_range, y_mean)
    if model_key == "exponential_growth":
        return (amplitude, 1.0 / x_range, offset)
    if model_key == "exponential_decay":
        return (amplitude, max(x_range / 2.0, np.finfo(float).eps), offset)
    if model_key == "double_exponential_decay":
        return (amplitude * 0.7, x_range / 4.0, amplitude * 0.3, x_range, offset)
    if model_key in {"logistic", "gompertz", "erf_step", "weibull"}:
        midpoint = (x_min + x_max) / 2.0
        if model_key == "logistic":
            return (amplitude, 1.0 / x_range, midpoint, offset)
        if model_key == "gompertz":
            return (amplitude, 1.0, 1.0 / x_range, offset)
        if model_key == "erf_step":
            return (amplitude, midpoint, x_range / 8.0, offset)
        return (amplitude, 2.0, x_range / 2.0, offset)
    if model_key == "log_normal":
        safe_center = max(center, np.finfo(float).tiny)
        return (amplitude, float(np.log(safe_center)), 1.0, offset)
    if model_key == "power_law":
        return (1.0, 1.0, offset)
    if model_key == "heidler":
        return (amplitude, x_range / 20.0, x_range / 4.0, 2.0, offset)
    if model_key == "stretched_exponential":
        return (amplitude, max(x_range / 2.0, np.finfo(float).eps), 0.5, offset)
    if model_key == "asymmetric_gaussian":
        width = max(x_range / 6.0, np.finfo(float).eps)
        return (amplitude, center, width, width, offset)

    return model.default_initial


def _safe_width(value: float) -> float:
    """Return a nonzero width value for numerically stable model evaluation."""
    if abs(value) < np.finfo(float).eps:
        return np.finfo(float).eps
    return value
