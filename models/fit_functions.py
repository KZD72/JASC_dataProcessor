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
    )


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


def available_fit_models(custom_models: list[CustomFitModel] | None = None) -> list[FitModel]:
    """Return fit models in UI order."""
    models = list(FIT_MODELS.values())
    for custom_model in custom_models or []:
        models.append(build_custom_fit_model(custom_model))
    return models


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
