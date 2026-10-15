"""Analytical function registry for curve fitting."""

from __future__ import annotations

import ast
import keyword
from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy import integrate, signal, special, stats


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
    category: str = "Other"
    description: str = ""
    default_lower: tuple[float | None, ...] = ()
    default_upper: tuple[float | None, ...] = ()
    parameter_roles: tuple[str, ...] = ()
    is_peak: bool = False


FIT_MODEL_CATEGORIES: tuple[str, ...] = (
    "Polynomial",
    "Exponential & decay",
    "Growth & sigmoidal",
    "Peak - symmetric",
    "Peak - asymmetric",
    "Transition & waveform",
    "Power, logarithmic & rational",
    "Binding & kinetics",
    "Rheology",
    "Probability distributions",
    "Special & physical",
    "Custom",
)


CUSTOM_MODEL_PREFIX = "custom:"

_ALLOWED_MODEL_NODE_TYPES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Attribute,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.keyword,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.Invert,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.BitAnd,
    ast.BitOr,
    ast.And,
    ast.Or,
)

_CUSTOM_NUMPY_FUNCTIONS = {
    "abs",
    "absolute",
    "angle",
    "arccos",
    "arccosh",
    "arcsin",
    "arcsinh",
    "arctan",
    "arctan2",
    "arctanh",
    "ceil",
    "clip",
    "cos",
    "cosh",
    "deg2rad",
    "degrees",
    "exp",
    "expm1",
    "floor",
    "heaviside",
    "hypot",
    "isfinite",
    "isinf",
    "isnan",
    "log",
    "log10",
    "log1p",
    "log2",
    "maximum",
    "minimum",
    "nan_to_num",
    "piecewise",
    "power",
    "polyval",
    "rad2deg",
    "radians",
    "select",
    "sign",
    "sinc",
    "sin",
    "sinh",
    "sqrt",
    "square",
    "tan",
    "tanh",
    "where",
    "zeros_like",
    "ones_like",
    "full_like",
}
_CUSTOM_NUMPY_CONSTANTS = {"e", "inf", "nan", "pi"}
_CUSTOM_SCIPY_SPECIAL = {
    "airy",
    "beta",
    "erf",
    "erfc",
    "erfinv",
    "expit",
    "gamma",
    "gammaln",
    "i0",
    "i1",
    "iv",
    "j0",
    "j1",
    "jn",
    "jv",
    "kv",
    "logit",
    "ndtr",
    "ndtri",
    "spherical_jn",
    "spherical_yn",
    "y0",
    "y1",
    "yn",
    "yv",
}
_CUSTOM_SCIPY_SIGNAL = {"savgol_filter"}
_CUSTOM_SCIPY_INTEGRATE = {"trapezoid", "simpson"}


@dataclass(frozen=True, slots=True)
class CustomFitModel:
    """Project-saved expression model that can be compiled for curve fitting."""

    name: str
    expression: str
    parameter_names: tuple[str, ...]
    default_initial: tuple[float, ...]

    @property
    def key(self) -> str:
        """Return the model key used by the fit dialog."""
        return f"{CUSTOM_MODEL_PREFIX}{self.name}"

    def to_metadata(self) -> dict[str, object]:
        """Return JSON-friendly project metadata."""
        return {
            "name": self.name,
            "expression": self.expression,
            "parameter_names": list(self.parameter_names),
            "default_initial": list(self.default_initial),
        }

    @classmethod
    def from_metadata(cls, metadata: object) -> "CustomFitModel":
        """Create a custom fit model from project metadata."""
        if not isinstance(metadata, dict):
            raise ValueError("Custom fit model metadata must be an object.")
        return create_custom_fit_model(
            name=str(metadata.get("name", "")),
            expression=str(metadata.get("expression", "")),
            parameter_names=[str(value) for value in metadata.get("parameter_names", [])],
            default_initial=[float(value) for value in metadata.get("default_initial", [])],
        )


class _FitNamespace:
    """Small namespace exposing only whitelisted model functions."""

    def __init__(self, display_name: str, members: dict[str, object]) -> None:
        """Store explicitly allowed namespace members."""
        self._display_name = display_name
        self._members = members

    def __getattr__(self, name: str) -> object:
        """Return one allowed attribute or reject it."""
        if name in self._members:
            return self._members[name]
        raise AttributeError(f"{self._display_name}.{name} is not available in custom fit models.")

    def attribute_paths(self, prefix: tuple[str, ...]) -> set[tuple[str, ...]]:
        """Return every allowed dotted attribute path."""
        paths: set[tuple[str, ...]] = set()
        for name, value in self._members.items():
            path = (*prefix, name)
            paths.add(path)
            if isinstance(value, _FitNamespace):
                paths.update(value.attribute_paths(path))
        return paths

    def callable_attribute_paths(self, prefix: tuple[str, ...]) -> set[tuple[str, ...]]:
        """Return dotted attribute paths whose final value is callable."""
        paths: set[tuple[str, ...]] = set()
        for name, value in self._members.items():
            path = (*prefix, name)
            if callable(value):
                paths.add(path)
            if isinstance(value, _FitNamespace):
                paths.update(value.callable_attribute_paths(path))
        return paths


class _CustomModelValidator(ast.NodeVisitor):
    """AST validator for custom fit model expressions."""

    def __init__(
        self,
        allowed_names: set[str],
        callable_names: set[str],
        attribute_names: set[tuple[str, ...]],
        callable_attribute_names: set[tuple[str, ...]],
    ) -> None:
        """Store the allowlists used during model-expression validation."""
        self._allowed_names = allowed_names
        self._callable_names = callable_names
        self._attribute_names = attribute_names
        self._callable_attribute_names = callable_attribute_names

    def generic_visit(self, node: ast.AST) -> None:
        """Reject syntax outside the safe expression subset."""
        if not isinstance(node, _ALLOWED_MODEL_NODE_TYPES):
            raise ValueError(f"Unsupported expression element: {type(node).__name__}.")
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Reject references outside the custom model environment."""
        if node.id not in self._allowed_names:
            raise ValueError(f"Unknown name '{node.id}' in custom model expression.")

    def visit_BinOp(self, node: ast.BinOp) -> None:
        """Reject caret exponent mistakes."""
        if isinstance(node.op, ast.BitXor):
            raise ValueError("Use ** for powers. The ^ operator is not exponentiation in Python.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Validate callable use against top-level and dotted allowlists."""
        if isinstance(node.func, ast.Name):
            if node.func.id not in self._callable_names:
                raise ValueError(f"'{node.func.id}' is not callable in custom fit models.")
        elif isinstance(node.func, ast.Attribute):
            path = self._attribute_path(node.func)
            if path not in self._callable_attribute_names:
                raise ValueError(f"{'.'.join(path)} is not callable or not available.")
        else:
            raise ValueError("Unsupported function call in custom fit model.")

        for keyword_arg in node.keywords:
            if keyword_arg.arg is None:
                raise ValueError("Expanded keyword arguments are not supported.")

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Validate dotted namespace access."""
        if node.attr.startswith("_"):
            raise ValueError(f"Private attributes are not allowed: .{node.attr}")
        path = self._attribute_path(node)
        if path not in self._attribute_names:
            raise ValueError(f"{'.'.join(path)} is not available in custom fit models.")

    def _attribute_path(self, node: ast.Attribute) -> tuple[str, ...]:
        """Convert a dotted AST attribute chain into a tuple."""
        path: list[str] = [node.attr]
        current = node.value
        while isinstance(current, ast.Attribute):
            path.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            raise ValueError("Unsupported dotted expression.")
        path.append(current.id)
        return tuple(reversed(path))


def create_custom_fit_model(
    name: str,
    expression: str,
    parameter_names: list[str] | tuple[str, ...],
    default_initial: list[float] | tuple[float, ...],
) -> CustomFitModel:
    """Validate user text and create a custom fit model definition."""
    clean_name = name.strip()
    clean_expression = expression.strip()
    parameters = tuple(item.strip() for item in parameter_names if item.strip())
    initial_values = tuple(float(value) for value in default_initial)

    if not clean_name:
        raise ValueError("Enter a custom model name.")
    if not clean_expression:
        raise ValueError("Enter a custom model expression.")
    if not parameters:
        raise ValueError("Enter at least one parameter name.")
    if len(parameters) != len(set(parameters)):
        raise ValueError("Parameter names must be unique.")
    if len(initial_values) != len(parameters):
        raise ValueError("Initial values must match the number of parameters.")
    for parameter in parameters:
        if not _is_safe_parameter_name(parameter):
            raise ValueError(f"Invalid parameter name '{parameter}'. Use a simple Python identifier.")
        if parameter == "x":
            raise ValueError("'x' is reserved for the independent variable.")
        if parameter in _reserved_custom_model_names():
            raise ValueError(f"Parameter name '{parameter}' conflicts with a built-in model name.")

    model = CustomFitModel(clean_name, clean_expression, parameters, initial_values)
    build_custom_fit_model(model)
    return model


def build_custom_fit_model(custom_model: CustomFitModel) -> FitModel:
    """Compile a custom fit model definition into a FitModel."""
    tree = ast.parse(custom_model.expression, mode="eval")
    base_environment = _build_custom_model_environment(
        x_values=np.asarray([0.0, 0.5, 1.0], dtype=float),
        parameter_names=custom_model.parameter_names,
        parameter_values=custom_model.default_initial,
    )
    validator = _CustomModelValidator(
        allowed_names=set(base_environment),
        callable_names={name for name, value in base_environment.items() if callable(value)},
        attribute_names=_attribute_names(base_environment),
        callable_attribute_names=_callable_attribute_names(base_environment),
    )
    validator.visit(tree)
    code = compile(tree, f"<custom fit model {custom_model.name}>", "eval")

    def custom_function(x_values: np.ndarray, *parameters: float) -> np.ndarray:
        """Evaluate the compiled custom fit model."""
        if len(parameters) != len(custom_model.parameter_names):
            raise ValueError(f"{custom_model.name} expects {len(custom_model.parameter_names)} parameter(s).")
        x_array = np.asarray(x_values, dtype=float)
        environment = _build_custom_model_environment(
            x_values=x_array,
            parameter_names=custom_model.parameter_names,
            parameter_values=parameters,
        )
        result = eval(code, {"__builtins__": {}}, environment)
        values = np.asarray(result, dtype=float)
        if values.ndim == 0:
            return np.full_like(x_array, float(values), dtype=float)
        if values.shape != x_array.shape:
            raise ValueError(
                f"Custom model '{custom_model.name}' returned shape {values.shape}; expected {x_array.shape}."
            )
        return values

    custom_function(np.asarray([0.0, 0.5, 1.0], dtype=float), *custom_model.default_initial)
    return FitModel(
        key=custom_model.key,
        name=f"Custom: {custom_model.name}",
        equation=custom_model.expression,
        parameter_names=custom_model.parameter_names,
        function=custom_function,
        default_initial=custom_model.default_initial,
        category="Custom",
        description="Project-defined expression model.",
    )


def constant(x: np.ndarray, c: float) -> np.ndarray:
    """Return a constant baseline."""
    return np.full_like(np.asarray(x, dtype=float), c, dtype=float)


def linear(x: np.ndarray, a: float, b: float) -> np.ndarray:
    """Return a linear model, a*x + b."""
    return a * x + b


def quadratic(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Return a quadratic polynomial model."""
    return a * x**2 + b * x + c


def cubic(x: np.ndarray, a: float, b: float, c: float, d: float) -> np.ndarray:
    """Return a cubic polynomial model."""
    return a * x**3 + b * x**2 + c * x + d


def quartic(x: np.ndarray, a: float, b: float, c: float, d: float, e: float) -> np.ndarray:
    """Return a fourth-order polynomial model."""
    return a * x**4 + b * x**3 + c * x**2 + d * x + e


def quintic(
    x: np.ndarray,
    a: float,
    b: float,
    c: float,
    d: float,
    e: float,
    f: float,
) -> np.ndarray:
    """Return a fifth-order polynomial model."""
    return a * x**5 + b * x**4 + c * x**3 + d * x**2 + e * x + f


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


def triple_exponential_decay(
    x: np.ndarray,
    a1: float,
    tau1: float,
    a2: float,
    tau2: float,
    a3: float,
    tau3: float,
    c: float,
) -> np.ndarray:
    """Return a triple exponential decay model."""
    return (
        a1 * np.exp(-x / _positive_width(tau1))
        + a2 * np.exp(-x / _positive_width(tau2))
        + a3 * np.exp(-x / _positive_width(tau3))
        + c
    )


def exponential_association(x: np.ndarray, amplitude: float, tau: float, offset: float) -> np.ndarray:
    """Return a one-phase exponential association model."""
    return offset + amplitude * (1.0 - np.exp(-x / _positive_width(tau)))


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


def voigt(
    x: np.ndarray,
    amplitude: float,
    center: float,
    sigma: float,
    gamma: float,
    offset: float,
) -> np.ndarray:
    """Return an exact Voigt peak normalized so amplitude is peak height."""
    gaussian_width = _positive_width(sigma)
    lorentz_width = _positive_width(gamma)
    profile = special.voigt_profile(x - center, gaussian_width, lorentz_width)
    peak_value = special.voigt_profile(0.0, gaussian_width, lorentz_width)
    return offset + amplitude * profile / max(float(peak_value), np.finfo(float).tiny)


def pearson_vii(
    x: np.ndarray,
    amplitude: float,
    center: float,
    scale: float,
    shape: float,
    offset: float,
) -> np.ndarray:
    """Return a Pearson type VII peak parameterized by height and scale."""
    width = _positive_width(scale)
    exponent = _positive_width(shape)
    return offset + amplitude * (1.0 + ((x - center) / width) ** 2) ** (-exponent)


def sech_squared(
    x: np.ndarray,
    amplitude: float,
    center: float,
    width: float,
    offset: float,
) -> np.ndarray:
    """Return a squared-hyperbolic-secant peak."""
    argument = np.clip((x - center) / _positive_width(width), -350.0, 350.0)
    return offset + amplitude / np.cosh(argument) ** 2


def laplace_peak(
    x: np.ndarray,
    amplitude: float,
    center: float,
    scale: float,
    offset: float,
) -> np.ndarray:
    """Return a double-exponential (Laplace) peak."""
    return offset + amplitude * np.exp(-np.abs(x - center) / _positive_width(scale))


def fano_peak(
    x: np.ndarray,
    amplitude: float,
    center: float,
    gamma: float,
    q: float,
    offset: float,
) -> np.ndarray:
    """Return a baseline-referenced Fano resonance peak/dip."""
    epsilon = (x - center) / _positive_width(gamma)
    return offset + amplitude * (((q + epsilon) ** 2 / (1.0 + epsilon**2)) - 1.0)


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


def cosine(
    x: np.ndarray,
    amplitude: float,
    frequency: float,
    phase: float,
    offset: float,
) -> np.ndarray:
    """Return a cosine model with offset."""
    return amplitude * np.cos(2.0 * np.pi * frequency * x + phase) + offset


def damped_cosine(
    x: np.ndarray,
    amplitude: float,
    frequency: float,
    phase: float,
    tau: float,
    offset: float,
) -> np.ndarray:
    """Return an exponentially damped cosine model."""
    return amplitude * np.exp(-x / _positive_width(tau)) * np.cos(
        2.0 * np.pi * frequency * x + phase
    ) + offset


def sine_squared(
    x: np.ndarray,
    amplitude: float,
    frequency: float,
    phase: float,
    offset: float,
) -> np.ndarray:
    """Return a squared-sine waveform."""
    return amplitude * np.sin(2.0 * np.pi * frequency * x + phase) ** 2 + offset


def fourier_two_term(
    x: np.ndarray,
    offset: float,
    a1: float,
    b1: float,
    a2: float,
    b2: float,
    frequency: float,
) -> np.ndarray:
    """Return a two-harmonic Fourier series."""
    angle = 2.0 * np.pi * frequency * x
    return offset + a1 * np.cos(angle) + b1 * np.sin(angle) + a2 * np.cos(2.0 * angle) + b2 * np.sin(2.0 * angle)


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


def boltzmann_sigmoid(
    x: np.ndarray,
    bottom: float,
    top: float,
    midpoint: float,
    slope: float,
) -> np.ndarray:
    """Return a four-parameter Boltzmann sigmoid."""
    z = np.clip((x - midpoint) / _safe_width(slope), -700.0, 700.0)
    return bottom + (top - bottom) / (1.0 + np.exp(z))


def logistic_five_parameter(
    x: np.ndarray,
    bottom: float,
    top: float,
    ec50: float,
    hill: float,
    asymmetry: float,
) -> np.ndarray:
    """Return a five-parameter logistic dose-response model."""
    safe_x = np.clip(x, np.finfo(float).tiny, None)
    ratio = np.power(safe_x / _positive_width(ec50), hill)
    return bottom + (top - bottom) / np.power(1.0 + ratio, _positive_width(asymmetry))


def richards(
    x: np.ndarray,
    amplitude: float,
    rate: float,
    midpoint: float,
    shape: float,
    offset: float,
) -> np.ndarray:
    """Return a generalized logistic (Richards) growth curve."""
    safe_shape = _positive_width(shape)
    base = 1.0 + safe_shape * np.exp(np.clip(-rate * (x - midpoint), -700.0, 700.0))
    return offset + amplitude / np.power(base, 1.0 / safe_shape)


def hill_sigmoid(
    x: np.ndarray,
    bottom: float,
    top: float,
    midpoint: float,
    hill: float,
) -> np.ndarray:
    """Return a Hill sigmoid using a positive concentration axis."""
    safe_x = np.clip(x, np.finfo(float).tiny, None)
    ratio = np.power(_positive_width(midpoint) / safe_x, hill)
    return bottom + (top - bottom) / (1.0 + ratio)


def erf_step(
    x: np.ndarray,
    amplitude: float,
    center: float,
    width: float,
    offset: float,
) -> np.ndarray:
    """Return an error-function step model."""
    return offset + 0.5 * amplitude * (1.0 + special.erf((x - center) / _safe_width(width)))


def arctangent_step(
    x: np.ndarray,
    amplitude: float,
    center: float,
    width: float,
    offset: float,
) -> np.ndarray:
    """Return an arctangent transition with broad tails."""
    return offset + amplitude * (0.5 + np.arctan((x - center) / _positive_width(width)) / np.pi)


def rectangular_pulse(
    x: np.ndarray,
    amplitude: float,
    center: float,
    width: float,
    edge: float,
    offset: float,
) -> np.ndarray:
    """Return a smooth rectangular pulse made from two logistic edges."""
    half_width = _positive_width(width) / 2.0
    edge_width = _positive_width(edge)
    left = special.expit((x - (center - half_width)) / edge_width)
    right = special.expit((x - (center + half_width)) / edge_width)
    return offset + amplitude * (left - right)


def power_law(x: np.ndarray, a: float, exponent: float, c: float) -> np.ndarray:
    """Return a power-law model with offset."""
    safe_x = np.clip(x, np.finfo(float).tiny, None)
    return a * np.power(safe_x, exponent) + c


def logarithmic(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Return a shifted logarithmic model."""
    return a * np.log(np.clip(x + b, np.finfo(float).tiny, None)) + c


def reciprocal(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Return a shifted reciprocal model."""
    denominator = _safe_array_denominator(x + b)
    return a / denominator + c


def rational_one_one(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """Return a first-order over first-order rational model."""
    return (a + b * x) / _safe_array_denominator(1.0 + c * x)


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


def exponentially_modified_gaussian(
    x: np.ndarray,
    area: float,
    center: float,
    sigma: float,
    tau: float,
    offset: float,
) -> np.ndarray:
    """Return an exponentially modified Gaussian peak with area scaling."""
    gaussian_width = _positive_width(sigma)
    decay = _positive_width(tau)
    return offset + area * stats.exponnorm.pdf(
        x,
        decay / gaussian_width,
        loc=center,
        scale=gaussian_width,
    )


def split_lorentzian(
    x: np.ndarray,
    amplitude: float,
    center: float,
    gamma_l: float,
    gamma_r: float,
    offset: float,
) -> np.ndarray:
    """Return a Lorentzian peak with independent left and right widths."""
    gamma = np.where(x < center, _positive_width(gamma_l), _positive_width(gamma_r))
    return offset + amplitude * gamma**2 / ((x - center) ** 2 + gamma**2)


def fraser_suzuki(
    x: np.ndarray,
    amplitude: float,
    center: float,
    width: float,
    asymmetry: float,
    offset: float,
) -> np.ndarray:
    """Return a Fraser-Suzuki asymmetric chromatographic peak."""
    safe_width = _positive_width(width)
    if abs(asymmetry) < 1e-8:
        return offset + amplitude * np.exp(-4.0 * np.log(2.0) * ((x - center) / safe_width) ** 2)
    argument = 1.0 + 2.0 * asymmetry * (x - center) / safe_width
    profile = np.zeros_like(np.asarray(x, dtype=float))
    valid = argument > 0.0
    profile[valid] = np.exp(
        -np.log(2.0) * (np.log(argument[valid]) / asymmetry) ** 2
    )
    return offset + amplitude * profile


def doniach_sunjic(
    x: np.ndarray,
    amplitude: float,
    center: float,
    gamma: float,
    asymmetry: float,
    offset: float,
) -> np.ndarray:
    """Return a Doniach-Sunjic asymmetric spectroscopy line shape."""
    width = _positive_width(gamma)
    alpha = float(np.clip(asymmetry, 0.0, 0.99))
    delta = x - center
    angle = np.pi * alpha / 2.0 + (1.0 - alpha) * np.arctan2(delta, width)
    denominator = np.power(delta**2 + width**2, (1.0 - alpha) / 2.0)
    return offset + amplitude * special.gamma(1.0 - alpha) * np.cos(angle) / denominator


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


def michaelis_menten(
    x: np.ndarray,
    vmax: float,
    km: float,
    offset: float,
) -> np.ndarray:
    """Return a Michaelis-Menten saturation model."""
    safe_x = np.clip(x, 0.0, None)
    return offset + vmax * safe_x / (np.abs(km) + safe_x + np.finfo(float).eps)


def hill_saturation(
    x: np.ndarray,
    maximum: float,
    half: float,
    hill: float,
    offset: float,
) -> np.ndarray:
    """Return a Hill saturation model."""
    safe_x = np.clip(x, 0.0, None)
    x_power = np.power(safe_x, _positive_width(hill))
    half_power = _positive_width(half) ** _positive_width(hill)
    return offset + maximum * x_power / (half_power + x_power + np.finfo(float).eps)


def substrate_inhibition(
    x: np.ndarray,
    vmax: float,
    km: float,
    ki: float,
    offset: float,
) -> np.ndarray:
    """Return a substrate-inhibition kinetics model."""
    safe_x = np.clip(x, 0.0, None)
    denominator = _positive_width(km) + safe_x + safe_x**2 / _positive_width(ki)
    return offset + vmax * safe_x / denominator


def one_site_binding(
    x: np.ndarray,
    capacity: float,
    kd: float,
    offset: float,
) -> np.ndarray:
    """Return a one-site specific binding isotherm."""
    safe_x = np.clip(x, 0.0, None)
    return offset + capacity * safe_x / (_positive_width(kd) + safe_x)


def two_site_binding(
    x: np.ndarray,
    capacity1: float,
    kd1: float,
    capacity2: float,
    kd2: float,
    offset: float,
) -> np.ndarray:
    """Return a two-site specific binding isotherm."""
    safe_x = np.clip(x, 0.0, None)
    return (
        offset
        + capacity1 * safe_x / (_positive_width(kd1) + safe_x)
        + capacity2 * safe_x / (_positive_width(kd2) + safe_x)
    )


def bingham(x: np.ndarray, yield_stress: float, viscosity: float) -> np.ndarray:
    """Return a Bingham plastic flow curve."""
    return yield_stress + viscosity * x


def herschel_bulkley(
    x: np.ndarray,
    yield_stress: float,
    consistency: float,
    exponent: float,
) -> np.ndarray:
    """Return a Herschel-Bulkley flow curve."""
    return yield_stress + consistency * np.power(np.clip(x, 0.0, None), exponent)


def cross_rheology(
    x: np.ndarray,
    eta_zero: float,
    eta_inf: float,
    time_constant: float,
    exponent: float,
) -> np.ndarray:
    """Return the Cross shear-thinning viscosity model."""
    safe_x = np.clip(x, 0.0, None)
    return eta_inf + (eta_zero - eta_inf) / (
        1.0 + np.power(_positive_width(time_constant) * safe_x, exponent)
    )


def carreau(
    x: np.ndarray,
    eta_zero: float,
    eta_inf: float,
    time_constant: float,
    exponent: float,
) -> np.ndarray:
    """Return the Carreau viscosity model."""
    safe_x = np.clip(x, 0.0, None)
    return eta_inf + (eta_zero - eta_inf) * np.power(
        1.0 + (_positive_width(time_constant) * safe_x) ** 2,
        (exponent - 1.0) / 2.0,
    )


def normal_pdf(x: np.ndarray, area: float, mean: float, sigma: float) -> np.ndarray:
    """Return an area-scaled normal probability density."""
    return area * stats.norm.pdf(x, loc=mean, scale=_positive_width(sigma))


def gamma_pdf(x: np.ndarray, area: float, shape: float, scale: float, location: float) -> np.ndarray:
    """Return an area-scaled shifted gamma probability density."""
    return area * stats.gamma.pdf(
        x,
        a=_positive_width(shape),
        loc=location,
        scale=_positive_width(scale),
    )


def weibull_pdf(x: np.ndarray, area: float, shape: float, scale: float, location: float) -> np.ndarray:
    """Return an area-scaled shifted Weibull probability density."""
    return area * stats.weibull_min.pdf(
        x,
        c=_positive_width(shape),
        loc=location,
        scale=_positive_width(scale),
    )


def lognormal_pdf(x: np.ndarray, area: float, shape: float, scale: float) -> np.ndarray:
    """Return an area-scaled log-normal probability density."""
    return area * stats.lognorm.pdf(
        x,
        s=_positive_width(shape),
        scale=_positive_width(scale),
    )


def gaussian_cdf(x: np.ndarray, amplitude: float, mean: float, sigma: float, offset: float) -> np.ndarray:
    """Return a scaled Gaussian cumulative distribution."""
    return offset + amplitude * stats.norm.cdf(x, loc=mean, scale=_positive_width(sigma))


def weibull_cdf(
    x: np.ndarray,
    amplitude: float,
    shape: float,
    scale: float,
    location: float,
    offset: float,
) -> np.ndarray:
    """Return a scaled shifted Weibull cumulative distribution."""
    return offset + amplitude * stats.weibull_min.cdf(
        x,
        c=_positive_width(shape),
        loc=location,
        scale=_positive_width(scale),
    )


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


def arrhenius(x: np.ndarray, prefactor: float, activation: float) -> np.ndarray:
    """Return an Arrhenius relation using activation_over_R in kelvin."""
    safe_temperature = np.clip(x, np.finfo(float).tiny, None)
    return prefactor * np.exp(-activation / safe_temperature)


def planck_spectrum(
    x: np.ndarray,
    scale: float,
    temperature: float,
    offset: float,
) -> np.ndarray:
    """Return wavelength-domain Planck radiance with an arbitrary scale."""
    wavelength = np.clip(x, np.finfo(float).tiny, None)
    exponent = np.clip(1.438776877e-2 / (wavelength * _positive_width(temperature)), 0.0, 700.0)
    return offset + scale / (wavelength**5 * np.expm1(exponent))


# Compatibility snapshot: saved projects and batch recipes may contain these keys and
# parameter orders. The expanded registry is checked against it below.
_COMPATIBILITY_FIT_MODELS: dict[str, FitModel] = {
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


def _model(
    key: str,
    name: str,
    equation: str,
    parameter_names: tuple[str, ...],
    function: ArrayFunction,
    default_initial: tuple[float, ...],
    category: str,
    description: str,
) -> FitModel:
    """Build a categorized built-in model with consistent metadata."""
    lower: list[float | None] = [None] * len(parameter_names)
    upper: list[float | None] = [None] * len(parameter_names)
    positive_names = {
        "ec50",
        "edge",
        "half",
        "kd",
        "kd1",
        "kd2",
        "ki",
        "km",
        "scale",
        "shape",
        "sigma",
        "sigma_l",
        "sigma_r",
        "gamma",
        "gamma_l",
        "gamma_r",
        "tau",
        "tau1",
        "tau2",
        "tau3",
        "temperature",
        "time_constant",
        "width",
    }
    for index, parameter_name in enumerate(parameter_names):
        if parameter_name in positive_names:
            lower[index] = np.finfo(float).eps
        elif parameter_name == "eta":
            lower[index] = 0.0
            upper[index] = 1.0
        elif parameter_name == "frequency":
            lower[index] = 0.0
    if key == "stretched_exponential":
        lower[parameter_names.index("beta")] = np.finfo(float).eps
    if key == "logistic_5p":
        lower[parameter_names.index("asymmetry")] = np.finfo(float).eps
    if key == "doniach_sunjic":
        lower[parameter_names.index("asymmetry")] = 0.0
        upper[parameter_names.index("asymmetry")] = 0.99
    is_peak = category.startswith("Peak -")
    role_by_name = {
        "amplitude": "height",
        "area": "area",
        "center": "center",
        "mu": "center",
        "sigma": "width",
        "sigma_l": "width",
        "sigma_r": "width",
        "gamma": "width",
        "gamma_l": "width",
        "gamma_r": "width",
        "scale": "width",
        "width": "width",
        "eta": "shape",
        "q": "shape",
        "shape": "shape",
        "asymmetry": "shape",
        "tau": "shape",
        "offset": "offset",
        "slope": "slope",
    }
    parameter_roles = tuple(
        role_by_name.get(parameter_name, "parameter") for parameter_name in parameter_names
    )
    if key == "fano_peak":
        # A Fano resonance is not an ordinary one-lobe peak.  ``amplitude`` is
        # the continuum-referenced scale, ``center`` is the unshifted
        # resonance position, and ``gamma`` is half the natural linewidth.
        # Keeping those semantics explicit prevents the composite fitter from
        # treating the observed extremum as the resonance centre/height.
        parameter_roles = (
            "scale",
            "resonance_center",
            "resonance_width",
            "fano_q",
            "offset",
        )
        lower[parameter_names.index("amplitude")] = np.finfo(float).eps
    return FitModel(
        key,
        name,
        equation,
        parameter_names,
        function,
        default_initial,
        category,
        description,
        tuple(lower),
        tuple(upper),
        parameter_roles,
        is_peak,
    )


FIT_MODELS: dict[str, FitModel] = {
    model.key: model
    for model in (
        _model("constant", "Constant", "c", ("c",), constant, (0.0,), "Polynomial", "Constant baseline."),
        _model("linear", "Linear", "a*x + b", ("a", "b"), linear, (1.0, 0.0), "Polynomial", "Straight line."),
        _model("quadratic", "Quadratic", "a*x**2 + b*x + c", ("a", "b", "c"), quadratic, (1.0, 1.0, 0.0), "Polynomial", "Second-order polynomial."),
        _model("cubic", "Cubic", "a*x**3 + b*x**2 + c*x + d", ("a", "b", "c", "d"), cubic, (1.0, 1.0, 1.0, 0.0), "Polynomial", "Third-order polynomial."),
        _model("quartic", "Quartic", "a*x**4 + b*x**3 + c*x**2 + d*x + e", ("a", "b", "c", "d", "e"), quartic, (1.0, 1.0, 1.0, 1.0, 0.0), "Polynomial", "Fourth-order polynomial."),
        _model("quintic", "Quintic", "a*x**5 + b*x**4 + c*x**3 + d*x**2 + e*x + f", ("a", "b", "c", "d", "e", "f"), quintic, (1.0, 1.0, 1.0, 1.0, 1.0, 0.0), "Polynomial", "Fifth-order polynomial."),

        _model("exponential_growth", "Exponential growth", "a*exp(k*x) + c", ("a", "k", "c"), exponential_growth, (1.0, 0.1, 0.0), "Exponential & decay", "Single exponential growth."),
        _model("exponential_decay", "Exponential decay", "a*exp(-x/tau) + c", ("a", "tau", "c"), exponential_decay, (1.0, 1.0, 0.0), "Exponential & decay", "Single exponential decay."),
        _model("double_exponential_decay", "Double exponential decay", "a1*exp(-x/tau1) + a2*exp(-x/tau2) + c", ("a1", "tau1", "a2", "tau2", "c"), double_exponential_decay, (0.7, 1.0, 0.3, 5.0, 0.0), "Exponential & decay", "Two-component exponential decay."),
        _model("triple_exponential_decay", "Triple exponential decay", "a1*exp(-x/tau1) + a2*exp(-x/tau2) + a3*exp(-x/tau3) + c", ("a1", "tau1", "a2", "tau2", "a3", "tau3", "c"), triple_exponential_decay, (0.6, 1.0, 0.3, 5.0, 0.1, 20.0, 0.0), "Exponential & decay", "Three-component exponential decay."),
        _model("exponential_association", "Exponential association", "offset + amplitude*(1-exp(-x/tau))", ("amplitude", "tau", "offset"), exponential_association, (1.0, 1.0, 0.0), "Exponential & decay", "One-phase rise to a plateau."),
        _model("stretched_exponential", "Stretched exponential", "amplitude*exp(-(x/tau)**beta) + offset", ("amplitude", "tau", "beta", "offset"), stretched_exponential, (1.0, 1.0, 0.5, 0.0), "Exponential & decay", "Kohlrausch stretched-exponential relaxation."),

        _model("logistic", "Logistic (4 parameter)", "offset + amplitude/(1 + exp(-rate*(x-midpoint)))", ("amplitude", "rate", "midpoint", "offset"), logistic, (1.0, 1.0, 0.0, 0.0), "Growth & sigmoidal", "Four-parameter logistic growth curve."),
        _model("logistic_5p", "Logistic (5 parameter)", "bottom + (top-bottom)/(1+(x/ec50)**hill)**asymmetry", ("bottom", "top", "ec50", "hill", "asymmetry"), logistic_five_parameter, (0.0, 1.0, 1.0, 1.0, 1.0), "Growth & sigmoidal", "Asymmetric five-parameter dose-response curve."),
        _model("gompertz", "Gompertz", "offset + amplitude*exp(-scale*exp(-rate*x))", ("amplitude", "scale", "rate", "offset"), gompertz, (1.0, 1.0, 1.0, 0.0), "Growth & sigmoidal", "Asymmetric Gompertz growth curve."),
        _model("richards", "Richards generalized logistic", "offset + amplitude/(1+shape*exp(-rate*(x-midpoint)))**(1/shape)", ("amplitude", "rate", "midpoint", "shape", "offset"), richards, (1.0, 1.0, 0.0, 1.0, 0.0), "Growth & sigmoidal", "Generalized logistic curve with adjustable asymmetry."),
        _model("boltzmann", "Boltzmann sigmoid", "bottom + (top-bottom)/(1+exp((x-midpoint)/slope))", ("bottom", "top", "midpoint", "slope"), boltzmann_sigmoid, (0.0, 1.0, 0.0, 1.0), "Growth & sigmoidal", "Four-parameter transition commonly used in electrophysiology."),
        _model("hill_sigmoid", "Hill sigmoid", "bottom + (top-bottom)/(1+(midpoint/x)**hill)", ("bottom", "top", "midpoint", "hill"), hill_sigmoid, (0.0, 1.0, 1.0, 1.0), "Growth & sigmoidal", "Concentration-response Hill sigmoid."),
        _model("weibull", "Weibull saturation", "amplitude*(1-exp(-(x/scale)**shape)) + offset", ("amplitude", "shape", "scale", "offset"), weibull, (1.0, 2.0, 1.0, 0.0), "Growth & sigmoidal", "Weibull rise-to-plateau model."),

        _model("gaussian", "Gaussian", "amplitude*exp(-0.5*((x-center)/sigma)**2) + offset", ("amplitude", "center", "sigma", "offset"), gaussian, (1.0, 0.0, 1.0, 0.0), "Peak - symmetric", "Gaussian peak; sigma is the standard deviation."),
        _model("lorentzian", "Lorentzian", "amplitude*gamma**2/((x-center)**2+gamma**2) + offset", ("amplitude", "center", "gamma", "offset"), lorentzian, (1.0, 0.0, 1.0, 0.0), "Peak - symmetric", "Lorentzian peak; gamma is the half width at half maximum."),
        _model("voigt", "Voigt", "offset + amplitude*Voigt(x-center,sigma,gamma)/Voigt(0,sigma,gamma)", ("amplitude", "center", "sigma", "gamma", "offset"), voigt, (1.0, 0.0, 1.0, 1.0, 0.0), "Peak - symmetric", "Exact convolution of Gaussian and Lorentzian profiles."),
        _model("pseudo_voigt", "Pseudo-Voigt", "eta*Lorentzian + (1-eta)*Gaussian + offset", ("amplitude", "center", "sigma", "eta", "offset"), pseudo_voigt, (1.0, 0.0, 1.0, 0.5, 0.0), "Peak - symmetric", "Fast Gaussian/Lorentzian mixture; eta should be between 0 and 1."),
        _model("pearson_vii", "Pearson VII", "offset + amplitude*(1+((x-center)/scale)**2)**(-shape)", ("amplitude", "center", "scale", "shape", "offset"), pearson_vii, (1.0, 0.0, 1.0, 2.0, 0.0), "Peak - symmetric", "Flexible bell-shaped peak spanning Lorentz-like to Gaussian-like tails."),
        _model("sech_squared", "Sech squared", "offset + amplitude/cosh((x-center)/width)**2", ("amplitude", "center", "width", "offset"), sech_squared, (1.0, 0.0, 1.0, 0.0), "Peak - symmetric", "Squared hyperbolic-secant peak used for pulse profiles."),
        _model("laplace_peak", "Laplace peak", "offset + amplitude*exp(-abs(x-center)/scale)", ("amplitude", "center", "scale", "offset"), laplace_peak, (1.0, 0.0, 1.0, 0.0), "Peak - symmetric", "Sharp double-exponential peak."),
        _model("fano_peak", "Fano resonance", "offset + amplitude*((q+epsilon)**2/(1+epsilon**2)-1)", ("amplitude", "center", "gamma", "q", "offset"), fano_peak, (1.0, 0.0, 1.0, 1.0, 0.0), "Peak - asymmetric", "Interference resonance capable of representing peaks, dips, and asymmetric profiles."),

        _model("asymmetric_gaussian", "Split Gaussian", "offset + amplitude*exp(-0.5*((x-center)/sigma_side)**2)", ("amplitude", "center", "sigma_l", "sigma_r", "offset"), asymmetric_gaussian, (1.0, 0.0, 1.0, 1.0, 0.0), "Peak - asymmetric", "Gaussian peak with independent left and right widths."),
        _model("split_lorentzian", "Split Lorentzian", "offset + amplitude*gamma_side**2/((x-center)**2+gamma_side**2)", ("amplitude", "center", "gamma_l", "gamma_r", "offset"), split_lorentzian, (1.0, 0.0, 1.0, 1.0, 0.0), "Peak - asymmetric", "Lorentzian peak with independent left and right widths."),
        _model("emg", "Exponentially modified Gaussian", "offset + area*ExponNormalPDF(x,center,sigma,tau)", ("area", "center", "sigma", "tau", "offset"), exponentially_modified_gaussian, (1.0, 0.0, 1.0, 1.0, 0.0), "Peak - asymmetric", "Gaussian convolved with an exponential decay; common in chromatography."),
        _model("log_normal", "Log-normal peak", "amplitude*exp(-0.5*((log(x)-mu)/sigma)**2) + offset", ("amplitude", "mu", "sigma", "offset"), log_normal, (1.0, 0.0, 1.0, 0.0), "Peak - asymmetric", "Log-normal-shaped peak on a positive X axis."),
        _model("fraser_suzuki", "Fraser-Suzuki", "offset + amplitude*exp(-ln(2)*(ln(1+2*asymmetry*(x-center)/width)/asymmetry)**2)", ("amplitude", "center", "width", "asymmetry", "offset"), fraser_suzuki, (1.0, 0.0, 1.0, 0.1, 0.0), "Peak - asymmetric", "Asymmetric chromatographic peak with a Gaussian limit."),
        _model("doniach_sunjic", "Doniach-Sunjic", "offset + amplitude*DS(x,center,gamma,asymmetry)", ("amplitude", "center", "gamma", "asymmetry", "offset"), doniach_sunjic, (1.0, 0.0, 1.0, 0.05, 0.0), "Peak - asymmetric", "Asymmetric metallic photoemission line shape."),

        _model("erf_step", "Error-function step", "offset + 0.5*amplitude*(1+erf((x-center)/width))", ("amplitude", "center", "width", "offset"), erf_step, (1.0, 0.0, 1.0, 0.0), "Transition & waveform", "Cumulative-Gaussian transition."),
        _model("arctangent_step", "Arctangent step", "offset + amplitude*(0.5+atan((x-center)/width)/pi)", ("amplitude", "center", "width", "offset"), arctangent_step, (1.0, 0.0, 1.0, 0.0), "Transition & waveform", "Smooth transition with broader tails than an error-function step."),
        _model("rectangular_pulse", "Smooth rectangular pulse", "offset + amplitude*(logistic_left-logistic_right)", ("amplitude", "center", "width", "edge", "offset"), rectangular_pulse, (1.0, 0.0, 1.0, 0.1, 0.0), "Transition & waveform", "Finite-width pulse with adjustable logistic edges."),
        _model("sine", "Sine", "amplitude*sin(2*pi*frequency*x+phase) + offset", ("amplitude", "frequency", "phase", "offset"), sine, (1.0, 1.0, 0.0, 0.0), "Transition & waveform", "Sinusoidal waveform."),
        _model("cosine", "Cosine", "amplitude*cos(2*pi*frequency*x+phase) + offset", ("amplitude", "frequency", "phase", "offset"), cosine, (1.0, 1.0, 0.0, 0.0), "Transition & waveform", "Cosine waveform."),
        _model("damped_sine", "Damped sine", "amplitude*exp(-x/tau)*sin(2*pi*frequency*x+phase) + offset", ("amplitude", "frequency", "phase", "tau", "offset"), damped_sine, (1.0, 1.0, 0.0, 10.0, 0.0), "Transition & waveform", "Exponentially damped sine."),
        _model("damped_cosine", "Damped cosine", "amplitude*exp(-x/tau)*cos(2*pi*frequency*x+phase) + offset", ("amplitude", "frequency", "phase", "tau", "offset"), damped_cosine, (1.0, 1.0, 0.0, 10.0, 0.0), "Transition & waveform", "Exponentially damped cosine."),
        _model("sine_squared", "Sine squared", "amplitude*sin(2*pi*frequency*x+phase)**2 + offset", ("amplitude", "frequency", "phase", "offset"), sine_squared, (1.0, 1.0, 0.0, 0.0), "Transition & waveform", "Nonnegative periodic squared-sine waveform."),
        _model("fourier_two_term", "Fourier series (2 harmonics)", "offset+a1*cos(w*x)+b1*sin(w*x)+a2*cos(2*w*x)+b2*sin(2*w*x)", ("offset", "a1", "b1", "a2", "b2", "frequency"), fourier_two_term, (0.0, 1.0, 0.0, 0.1, 0.0, 1.0), "Transition & waveform", "Two-harmonic Fourier series."),

        _model("power_law", "Power law", "a*x**exponent + c", ("a", "exponent", "c"), power_law, (1.0, 1.0, 0.0), "Power, logarithmic & rational", "Power-law relation with offset."),
        _model("logarithmic", "Logarithmic", "a*log(x+b) + c", ("a", "b", "c"), logarithmic, (1.0, 0.0, 0.0), "Power, logarithmic & rational", "Shifted natural-logarithm model."),
        _model("reciprocal", "Reciprocal", "a/(x+b) + c", ("a", "b", "c"), reciprocal, (1.0, 1.0, 0.0), "Power, logarithmic & rational", "Shifted reciprocal hyperbola."),
        _model("rational_1_1", "Rational (1/1)", "(a+b*x)/(1+c*x)", ("a", "b", "c"), rational_one_one, (0.0, 1.0, 0.1), "Power, logarithmic & rational", "First-order rational polynomial."),

        _model("michaelis_menten", "Michaelis-Menten", "offset + vmax*x/(km+x)", ("vmax", "km", "offset"), michaelis_menten, (1.0, 1.0, 0.0), "Binding & kinetics", "Single-substrate Michaelis-Menten kinetics."),
        _model("hill_saturation", "Hill saturation", "offset + maximum*x**hill/(half**hill+x**hill)", ("maximum", "half", "hill", "offset"), hill_saturation, (1.0, 1.0, 1.0, 0.0), "Binding & kinetics", "Cooperative saturation model."),
        _model("substrate_inhibition", "Substrate inhibition", "offset + vmax*x/(km+x+x**2/ki)", ("vmax", "km", "ki", "offset"), substrate_inhibition, (1.0, 1.0, 10.0, 0.0), "Binding & kinetics", "Michaelis-Menten kinetics with high-substrate inhibition."),
        _model("one_site_binding", "One-site binding", "offset + capacity*x/(kd+x)", ("capacity", "kd", "offset"), one_site_binding, (1.0, 1.0, 0.0), "Binding & kinetics", "Specific one-site binding isotherm."),
        _model("two_site_binding", "Two-site binding", "offset + capacity1*x/(kd1+x) + capacity2*x/(kd2+x)", ("capacity1", "kd1", "capacity2", "kd2", "offset"), two_site_binding, (0.7, 1.0, 0.3, 10.0, 0.0), "Binding & kinetics", "Specific binding at two independent site classes."),

        _model("bingham", "Bingham plastic", "yield_stress + viscosity*x", ("yield_stress", "viscosity"), bingham, (0.0, 1.0), "Rheology", "Yield-stress fluid with linear post-yield response."),
        _model("herschel_bulkley", "Herschel-Bulkley", "yield_stress + consistency*x**exponent", ("yield_stress", "consistency", "exponent"), herschel_bulkley, (0.0, 1.0, 1.0), "Rheology", "Generalized yield-stress power-law fluid."),
        _model("cross_rheology", "Cross viscosity", "eta_inf + (eta_zero-eta_inf)/(1+(time_constant*x)**exponent)", ("eta_zero", "eta_inf", "time_constant", "exponent"), cross_rheology, (10.0, 1.0, 1.0, 1.0), "Rheology", "Cross shear-thinning viscosity model."),
        _model("carreau", "Carreau viscosity", "eta_inf + (eta_zero-eta_inf)*(1+(time_constant*x)**2)**((exponent-1)/2)", ("eta_zero", "eta_inf", "time_constant", "exponent"), carreau, (10.0, 1.0, 1.0, 0.5), "Rheology", "Carreau viscosity model."),

        _model("normal_pdf", "Normal PDF", "area*NormalPDF(x,mean,sigma)", ("area", "mean", "sigma"), normal_pdf, (1.0, 0.0, 1.0), "Probability distributions", "Area-scaled normal probability density."),
        _model("gamma_pdf", "Gamma PDF", "area*GammaPDF(x,shape,scale,location)", ("area", "shape", "scale", "location"), gamma_pdf, (1.0, 2.0, 1.0, 0.0), "Probability distributions", "Area-scaled shifted gamma density."),
        _model("weibull_pdf", "Weibull PDF", "area*WeibullPDF(x,shape,scale,location)", ("area", "shape", "scale", "location"), weibull_pdf, (1.0, 2.0, 1.0, 0.0), "Probability distributions", "Area-scaled shifted Weibull density."),
        _model("lognormal_pdf", "Log-normal PDF", "area*LogNormalPDF(x,shape,scale)", ("area", "shape", "scale"), lognormal_pdf, (1.0, 1.0, 1.0), "Probability distributions", "Area-scaled log-normal density."),
        _model("gaussian_cdf", "Gaussian CDF", "offset + amplitude*NormalCDF(x,mean,sigma)", ("amplitude", "mean", "sigma", "offset"), gaussian_cdf, (1.0, 0.0, 1.0, 0.0), "Probability distributions", "Scaled normal cumulative distribution."),
        _model("weibull_cdf", "Weibull CDF", "offset + amplitude*WeibullCDF(x,shape,scale,location)", ("amplitude", "shape", "scale", "location", "offset"), weibull_cdf, (1.0, 2.0, 1.0, 0.0, 0.0), "Probability distributions", "Scaled shifted Weibull cumulative distribution."),

        _model("bessel_j", "Bessel J", "amplitude*J_order(scale*x) + offset", ("amplitude", "order", "scale", "offset"), bessel_j, (1.0, 0.0, 1.0, 0.0), "Special & physical", "Scaled Bessel function of the first kind."),
        _model("bessel_y", "Bessel Y", "amplitude*Y_order(scale*x) + offset", ("amplitude", "order", "scale", "offset"), bessel_y, (1.0, 0.0, 1.0, 0.0), "Special & physical", "Scaled Bessel function of the second kind."),
        _model("heidler", "Heidler impulse", "offset + amplitude*((x/tau1)**n/(1+(x/tau1)**n))*exp(-x/tau2)", ("amplitude", "tau1", "tau2", "n", "offset"), heidler, (1.0, 1.0, 10.0, 2.0, 0.0), "Special & physical", "Double-time-constant impulse model used for lightning currents."),
        _model("arrhenius", "Arrhenius", "prefactor*exp(-activation_over_R/temperature)", ("prefactor", "activation_over_R"), arrhenius, (1.0, 1000.0), "Special & physical", "Arrhenius relation; X is absolute temperature and activation_over_R is in kelvin."),
        _model("planck_spectrum", "Planck spectrum", "offset + scale/(wavelength**5*expm1(c2/(wavelength*temperature)))", ("scale", "temperature", "offset"), planck_spectrum, (1.0, 300.0, 0.0), "Special & physical", "Wavelength-domain black-body spectrum; X must be wavelength in metres."),
    )
}

for _legacy_key, _legacy_model in _COMPATIBILITY_FIT_MODELS.items():
    _current_model = FIT_MODELS.get(_legacy_key)
    if _current_model is None or _current_model.parameter_names != _legacy_model.parameter_names:
        raise RuntimeError(f"Built-in fit model compatibility changed for '{_legacy_key}'.")


def available_fit_models(
    custom_models: list[CustomFitModel] | None = None,
    category: str | None = None,
) -> list[FitModel]:
    """Return fit models in category-aware UI order."""
    models = list(FIT_MODELS.values())
    for custom_model in custom_models or []:
        models.append(build_custom_fit_model(custom_model))
    if category:
        models = [model for model in models if model.category == category]
    return models


def available_fit_categories(custom_models: list[CustomFitModel] | None = None) -> list[str]:
    """Return non-empty model categories in stable UI order."""
    populated = {model.category for model in available_fit_models(custom_models)}
    ordered = [category for category in FIT_MODEL_CATEGORIES if category in populated]
    ordered.extend(sorted(populated.difference(ordered)))
    return ordered


def get_fit_model(model_key: str, custom_models: list[CustomFitModel] | None = None) -> FitModel:
    """Return one fit model by key."""
    if model_key.startswith(CUSTOM_MODEL_PREFIX):
        for custom_model in custom_models or []:
            if custom_model.key == model_key:
                return build_custom_fit_model(custom_model)
        raise ValueError(f"Unknown custom fit model: {model_key.removeprefix(CUSTOM_MODEL_PREFIX)}")

    try:
        return FIT_MODELS[model_key]
    except KeyError as exc:
        raise ValueError(f"Unknown fit model: {model_key}") from exc


def default_initial_parameters(
    model_key: str,
    x_values: np.ndarray | None = None,
    y_values: np.ndarray | None = None,
    custom_models: list[CustomFitModel] | None = None,
) -> tuple[float, ...]:
    """Return practical initial parameters for a model and optional data."""
    model = get_fit_model(model_key, custom_models)
    if x_values is None or y_values is None or len(x_values) == 0 or len(y_values) == 0:
        return model.default_initial

    if model_key.startswith(CUSTOM_MODEL_PREFIX):
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
    edge_count = max(1, min(len(y) // 10, 10))
    baseline = float(np.nanmedian(np.concatenate((y[:edge_count], y[-edge_count:]))))
    peak_index = int(np.nanargmax(np.abs(y - baseline)))
    center = float(x[peak_index]) if len(y) else (x_min + x_max) / 2.0
    peak_amplitude = float(y[peak_index] - baseline)
    if not np.isfinite(peak_amplitude) or peak_amplitude == 0.0:
        peak_amplitude = amplitude
    offset = y_min

    if model_key == "constant":
        return (y_mean,)
    if model_key == "linear" and len(x) >= 2:
        slope, intercept = np.polyfit(x, y, 1)
        return (float(slope), float(intercept))
    if model_key == "quadratic" and len(x) >= 3:
        return tuple(float(value) for value in np.polyfit(x, y, 2))
    if model_key == "cubic" and len(x) >= 4:
        return tuple(float(value) for value in np.polyfit(x, y, 3))
    if model_key == "quartic" and len(x) >= 5:
        return tuple(float(value) for value in np.polyfit(x, y, 4))
    if model_key == "quintic" and len(x) >= 6:
        return tuple(float(value) for value in np.polyfit(x, y, 5))
    if model_key in {"gaussian", "lorentzian", "sech_squared", "laplace_peak"}:
        width = max(x_range / 6.0, np.finfo(float).eps)
        return (peak_amplitude, center, width, baseline)
    if model_key == "fano_peak":
        adjusted = y - baseline
        maximum_index = int(np.nanargmax(adjusted))
        minimum_index = int(np.nanargmin(adjusted))
        positive_contrast = max(float(adjusted[maximum_index]), 0.0)
        negative_contrast = max(float(-adjusted[minimum_index]), 0.0)
        if positive_contrast > 0.0 and negative_contrast > 0.0:
            q_magnitude = max(
                np.sqrt(positive_contrast / negative_contrast),
                np.finfo(float).eps,
            )
            q = q_magnitude if x[maximum_index] >= x[minimum_index] else -q_magnitude
            separation = abs(float(x[maximum_index] - x[minimum_index]))
            gamma = max(
                separation / (abs(q) + 1.0 / abs(q)),
                np.finfo(float).eps,
            )
            center = float(x[maximum_index] - gamma / q)
            return (negative_contrast, center, gamma, float(q), baseline)
        width = max(x_range / 8.0, np.finfo(float).eps)
        q = 2.0 if peak_amplitude >= 0.0 else 0.5
        scale = abs(peak_amplitude) / (q * q) if peak_amplitude >= 0.0 else abs(peak_amplitude)
        center = center - width / q if peak_amplitude >= 0.0 else center + width * q
        return (max(scale, np.finfo(float).eps), center, width, q, baseline)
    if model_key in {"voigt", "pseudo_voigt", "pearson_vii"}:
        width = max(x_range / 8.0, np.finfo(float).eps)
        if model_key == "voigt":
            return (peak_amplitude, center, width, width, baseline)
        if model_key == "pseudo_voigt":
            return (peak_amplitude, center, width, 0.5, baseline)
        if model_key == "pearson_vii":
            return (peak_amplitude, center, width, 2.0, baseline)
    if model_key in {"sine", "cosine", "sine_squared"}:
        return (amplitude / 2.0, 1.0 / x_range, 0.0, y_mean)
    if model_key in {"damped_sine", "damped_cosine"}:
        return (amplitude / 2.0, 1.0 / x_range, 0.0, x_range, y_mean)
    if model_key == "fourier_two_term":
        return (y_mean, amplitude / 2.0, 0.0, amplitude / 10.0, 0.0, 1.0 / x_range)
    if model_key == "exponential_growth":
        return (amplitude, 1.0 / x_range, offset)
    if model_key == "exponential_decay":
        return (amplitude, max(x_range / 2.0, np.finfo(float).eps), offset)
    if model_key == "exponential_association":
        return (amplitude, max(x_range / 2.0, np.finfo(float).eps), y_min)
    if model_key == "double_exponential_decay":
        return (amplitude * 0.7, x_range / 4.0, amplitude * 0.3, x_range, offset)
    if model_key == "triple_exponential_decay":
        return (
            amplitude * 0.6,
            x_range / 10.0,
            amplitude * 0.3,
            x_range / 3.0,
            amplitude * 0.1,
            x_range,
            offset,
        )
    if model_key in {
        "logistic",
        "logistic_5p",
        "gompertz",
        "richards",
        "boltzmann",
        "hill_sigmoid",
        "erf_step",
        "arctangent_step",
        "weibull",
        "gaussian_cdf",
    }:
        midpoint = (x_min + x_max) / 2.0
        if model_key == "logistic":
            return (amplitude, 1.0 / x_range, midpoint, offset)
        if model_key == "logistic_5p":
            return (y_min, y_max, max(midpoint, np.finfo(float).eps), 1.0, 1.0)
        if model_key == "gompertz":
            return (amplitude, 1.0, 1.0 / x_range, offset)
        if model_key == "richards":
            return (amplitude, 1.0 / x_range, midpoint, 1.0, offset)
        if model_key == "boltzmann":
            return (y_max, y_min, midpoint, x_range / 8.0)
        if model_key == "hill_sigmoid":
            return (y_min, y_max, max(midpoint, np.finfo(float).eps), 1.0)
        if model_key == "erf_step":
            return (amplitude, midpoint, x_range / 8.0, offset)
        if model_key == "arctangent_step":
            return (amplitude, midpoint, x_range / 8.0, offset)
        if model_key == "gaussian_cdf":
            return (amplitude, midpoint, x_range / 6.0, offset)
        return (amplitude, 2.0, x_range / 2.0, offset)
    if model_key == "log_normal":
        safe_center = max(center, np.finfo(float).tiny)
        return (peak_amplitude, float(np.log(safe_center)), 1.0, baseline)
    if model_key in {"asymmetric_gaussian", "split_lorentzian"}:
        width = max(x_range / 8.0, np.finfo(float).eps)
        return (peak_amplitude, center, width, width, baseline)
    if model_key in {"fraser_suzuki", "doniach_sunjic"}:
        width = max(x_range / 8.0, np.finfo(float).eps)
        return (peak_amplitude, center, width, 0.1, baseline)
    if model_key == "emg":
        width = max(x_range / 10.0, np.finfo(float).eps)
        area = peak_amplitude * width * np.sqrt(2.0 * np.pi)
        return (area, center, width, width, baseline)
    if model_key == "rectangular_pulse":
        return (peak_amplitude, center, x_range / 3.0, x_range / 30.0, baseline)
    if model_key == "power_law":
        return (1.0, 1.0, offset)
    if model_key in {"logarithmic", "reciprocal"}:
        return (amplitude, max(-x_min + np.finfo(float).eps, 0.0), offset)
    if model_key == "rational_1_1":
        return (offset, amplitude / x_range, 0.0)
    if model_key in {"michaelis_menten", "one_site_binding"}:
        return (amplitude, max(x_range / 2.0, np.finfo(float).eps), offset)
    if model_key == "hill_saturation":
        return (amplitude, max(x_range / 2.0, np.finfo(float).eps), 1.0, offset)
    if model_key == "substrate_inhibition":
        return (amplitude, x_range / 4.0, x_range, offset)
    if model_key == "two_site_binding":
        return (amplitude * 0.7, x_range / 4.0, amplitude * 0.3, x_range, offset)
    if model_key == "normal_pdf":
        return (amplitude * x_range, center, x_range / 6.0)
    if model_key in {"gamma_pdf", "weibull_pdf"}:
        return (amplitude * x_range, 2.0, x_range / 4.0, x_min)
    if model_key == "lognormal_pdf":
        return (amplitude * x_range, 1.0, max(center, np.finfo(float).eps))
    if model_key == "weibull_cdf":
        return (amplitude, 2.0, x_range / 2.0, x_min, offset)
    if model_key == "heidler":
        return (amplitude, x_range / 20.0, x_range / 4.0, 2.0, offset)
    if model_key == "stretched_exponential":
        return (amplitude, max(x_range / 2.0, np.finfo(float).eps), 0.5, offset)

    return model.default_initial


def _safe_width(value: float) -> float:
    """Return a nonzero width value for numerically stable model evaluation."""
    if abs(value) < np.finfo(float).eps:
        return np.finfo(float).eps
    return value


def _positive_width(value: float) -> float:
    """Return a strictly positive scale or width."""
    return max(abs(float(value)), np.finfo(float).eps)


def _safe_array_denominator(values: np.ndarray) -> np.ndarray:
    """Move zero-valued denominators a machine epsilon away from zero."""
    array = np.asarray(values, dtype=float)
    epsilon = np.finfo(float).eps
    signs = np.where(array < 0.0, -1.0, 1.0)
    return np.where(np.abs(array) < epsilon, signs * epsilon, array)


def _build_custom_model_environment(
    x_values: np.ndarray,
    parameter_names: tuple[str, ...],
    parameter_values: tuple[float, ...],
) -> dict[str, object]:
    """Build the safe name environment for custom fit model evaluation."""
    numpy_namespace = _build_numpy_namespace()
    scipy_namespace = _build_scipy_namespace()
    environment: dict[str, object] = {
        "integrate": scipy_namespace.integrate,
        "np": numpy_namespace,
        "scipy": scipy_namespace,
        "signal": scipy_namespace.signal,
        "special": scipy_namespace.special,
        "stats": scipy_namespace.stats,
        "x": x_values,
    }

    for name in _CUSTOM_NUMPY_CONSTANTS:
        environment[name] = getattr(np, name)
    for name in _CUSTOM_NUMPY_FUNCTIONS:
        environment[name] = getattr(np, name)
    for name, value in zip(parameter_names, parameter_values):
        environment[name] = float(value)
    return environment


def _build_numpy_namespace() -> _FitNamespace:
    """Create the curated NumPy namespace available to custom fit models."""
    members = {name: getattr(np, name) for name in _CUSTOM_NUMPY_FUNCTIONS}
    members.update({name: getattr(np, name) for name in _CUSTOM_NUMPY_CONSTANTS})
    members["linalg"] = _FitNamespace("np.linalg", {"norm": np.linalg.norm})
    return _FitNamespace("np", members)


def _build_scipy_namespace() -> _FitNamespace:
    """Create the curated SciPy namespace available to custom fit models."""
    special_namespace = _FitNamespace(
        "scipy.special",
        {name: getattr(special, name) for name in _CUSTOM_SCIPY_SPECIAL},
    )
    signal_namespace = _FitNamespace(
        "scipy.signal",
        {name: getattr(signal, name) for name in _CUSTOM_SCIPY_SIGNAL},
    )
    stats_namespace = _FitNamespace(
        "scipy.stats",
        {
            "norm": _FitNamespace(
                "scipy.stats.norm",
                {
                    "cdf": stats.norm.cdf,
                    "pdf": stats.norm.pdf,
                    "sf": stats.norm.sf,
                },
            )
        },
    )
    integrate_namespace = _FitNamespace(
        "scipy.integrate",
        {name: getattr(integrate, name) for name in _CUSTOM_SCIPY_INTEGRATE},
    )
    return _FitNamespace(
        "scipy",
        {
            "integrate": integrate_namespace,
            "signal": signal_namespace,
            "special": special_namespace,
            "stats": stats_namespace,
        },
    )


def _attribute_names(environment: dict[str, object]) -> set[tuple[str, ...]]:
    """Return all allowed attribute paths in safe namespaces."""
    names: set[tuple[str, ...]] = set()
    for name, value in environment.items():
        if isinstance(value, _FitNamespace):
            names.update(value.attribute_paths((name,)))
    return names


def _callable_attribute_names(environment: dict[str, object]) -> set[tuple[str, ...]]:
    """Return allowed attribute paths that may be called."""
    names: set[tuple[str, ...]] = set()
    for name, value in environment.items():
        if isinstance(value, _FitNamespace):
            names.update(value.callable_attribute_paths((name,)))
    return names


def _is_safe_parameter_name(name: str) -> bool:
    """Return whether a custom model parameter name is a safe identifier."""
    return name.isidentifier() and not keyword.iskeyword(name) and not name.startswith("_")


def _reserved_custom_model_names() -> set[str]:
    """Return names that cannot be used as custom model parameters."""
    environment = _build_custom_model_environment(
        x_values=np.asarray([0.0], dtype=float),
        parameter_names=(),
        parameter_values=(),
    )
    return set(environment)
