"""Phase 4 curve-fitting operations."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.stats import t as student_t
from scipy.stats import norm

from math_engine.calculus import MathOperationError, validate_numeric_column_metadata
from models.fit_functions import CustomFitModel, default_initial_parameters, get_fit_model
from models.uncertainty import PercentileBounds
from math_engine.uncertainty import QuantileNormal, likelihood_fit
from core.jobs import JobCancelled


FIT_METHODS: dict[str, str] = {
    "lm": "Levenberg-Marquardt",
    "trf": "Trust Region Reflective",
    "dogbox": "Dogbox",
    "odr": "Orthogonal Distance Regression",
    "percentile": "Percentile likelihood (median model)",
}

_ODR_MAX_ITERATIONS = 1000


@dataclass(frozen=True, slots=True)
class FitReport:
    """Numerical report produced by one curve fit."""

    model_key: str
    model_name: str
    equation: str
    method: str
    x_column: str
    y_column: str
    parameter_names: tuple[str, ...]
    parameters: tuple[float, ...]
    standard_errors: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]
    fixed_parameters: tuple[bool, ...]
    lower_bounds: tuple[float, ...]
    upper_bounds: tuple[float, ...]
    x_weight_column: str | None
    weight_column: str | None
    weight_mode: str
    absolute_sigma: bool
    confidence_level: float
    r_squared: float
    adjusted_r_squared: float
    rmse: float
    mae: float
    residual_mean: float
    residual_std: float
    point_count: int
    warnings: tuple[str, ...] = ()
    x_bounds: dict[str, object] | None = None
    y_bounds: dict[str, object] | None = None
    negative_log_likelihood: float | None = None

    def to_text(self) -> str:
        """Return a plain-text report for display/export."""
        lines = [
            "Curve Fit Report",
            "",
            f"Model: {self.model_name}",
            f"Equation: {self.equation}",
            f"Method: {FIT_METHODS.get(self.method, self.method)} ({self.method})",
            f"Source: {self.y_column} vs {self.x_column}",
            f"Points used: {self.point_count}",
            "",
            "Parameters:",
        ]

        for index, (name, value, error) in enumerate(
            zip(self.parameter_names, self.parameters, self.standard_errors)
        ):
            fixed_text = " (fixed)" if self.fixed_parameters[index] else ""
            lines.append(
                f"  {name} = {_format_number(value)} +/- {_format_number(error)}"
                f"{fixed_text}; bounds [{_format_number(self.lower_bounds[index])}, "
                f"{_format_number(self.upper_bounds[index])}]"
            )

        if self.x_weight_column or self.weight_column:
            lines.extend(
                [
                    "",
                    "Uncertainty / weights:",
                    f"  X column: {self.x_weight_column or 'None'}",
                    f"  Y column: {self.weight_column or 'None'}",
                    f"  Mode: {self.weight_mode}",
                    f"  Absolute sigma: {self.absolute_sigma}",
                ]
            )

        if self.x_bounds or self.y_bounds:
            lines.extend(["", "Percentile measurement likelihood (central values are medians):"])
            for axis, bounds in (("X", self.x_bounds), ("Y", self.y_bounds)):
                if bounds:
                    lines.append(f"  {axis}: {bounds['lower_column']} ({100*bounds['lower_probability']:g}%) / "
                                 f"{bounds['upper_column']} ({100*bounds['upper_probability']:g}%); {bounds['distribution']}")
            lines.append(f"  Negative log likelihood: {_format_number(self.negative_log_likelihood)}")
        if self.confidence_level:
            lines.extend(
                [
                    "",
                    "Confidence band:",
                    f"  Level: {self.confidence_level * 100:.3g}%",
                ]
            )

        lines.extend(
            [
                "",
                "Goodness of fit:",
                f"  R^2 = {_format_number(self.r_squared)}",
                f"  Adjusted R^2 = {_format_number(self.adjusted_r_squared)}",
                f"  RMSE = {_format_number(self.rmse)}",
                f"  MAE = {_format_number(self.mae)}",
                f"  Residual mean = {_format_number(self.residual_mean)}",
                f"  Residual std = {_format_number(self.residual_std)}",
                "",
                "Covariance matrix:",
            ]
        )

        for row in self.covariance:
            lines.append("  " + "  ".join(_format_number(value) for value in row))

        if self.warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"  {message}" for message in self.warnings)

        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class FitResult:
    """Fit output containing the curve points and report."""

    fit_frame: pd.DataFrame
    residual_frame: pd.DataFrame
    report: FitReport


def fit_curve(
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    model_key: str,
    method: str,
    initial_parameters: list[float] | tuple[float, ...] | None = None,
    lower_bounds: list[float | None] | tuple[float | None, ...] | None = None,
    upper_bounds: list[float | None] | tuple[float | None, ...] | None = None,
    fixed_parameters: list[bool] | tuple[bool, ...] | None = None,
    weight_column: str | None = None,
    weight_mode: str = "sigma",
    absolute_sigma: bool = False,
    include_confidence_band: bool = True,
    confidence_level: float = 0.95,
    fit_points: int = 400,
    x_weight_column: str | None = None,
    custom_models: list[CustomFitModel] | None = None,
    x_bounds: PercentileBounds | None = None,
    y_bounds: PercentileBounds | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> FitResult:
    """Fit a registered analytical model to two numeric columns."""
    if method not in FIT_METHODS:
        raise MathOperationError(f"Unknown fitting method: {method}")

    model = get_fit_model(model_key, custom_models)
    x_bounds, y_bounds = PercentileBounds.from_state(x_bounds), PercentileBounds.from_state(y_bounds)
    percentile = x_bounds is not None or y_bounds is not None
    if method == "percentile" and not percentile:
        raise MathOperationError("Select X or Y percentile bounds for percentile likelihood fitting.")
    for axis, bounds, weight in (("X", x_bounds, x_weight_column), ("Y", y_bounds, weight_column)):
        if bounds is not None and bounds.origin != "measurement":
            raise MathOperationError(f"{axis} posterior quantiles cannot be used as a measurement likelihood.")
        if bounds is not None and bounds.centre != "median":
            raise MathOperationError(f"{axis} percentile fitting requires median central values; other centres are plot-only.")
        if bounds is not None and weight:
            raise MathOperationError(f"Choose either {axis} symmetric weights or percentile bounds.")
    aligned = _fit_input_frame(frame, x_column, y_column, weight_column, x_weight_column, x_bounds, y_bounds)
    x_values = aligned["x"].to_numpy(dtype=float)
    y_values = aligned["y"].to_numpy(dtype=float)

    p0 = tuple(initial_parameters) if initial_parameters is not None else default_initial_parameters(
        model_key,
        x_values,
        y_values,
        custom_models,
    )
    if len(p0) != len(model.parameter_names):
        raise MathOperationError(
            f"{model.name} expects {len(model.parameter_names)} initial parameter(s): "
            f"{', '.join(model.parameter_names)}."
        )

    parameter_count = len(p0)
    lower = _normalize_bounds(lower_bounds, parameter_count, -np.inf)
    upper = _normalize_bounds(upper_bounds, parameter_count, np.inf)
    fixed = tuple(bool(value) for value in (fixed_parameters or [False] * parameter_count))
    if len(fixed) != parameter_count:
        raise MathOperationError(f"{model.name} expects {parameter_count} fixed/free setting(s).")
    _validate_parameter_settings(p0, lower, upper, fixed, model.parameter_names)

    free_indices = tuple(index for index, is_fixed in enumerate(fixed) if not is_fixed)
    prefit_warnings: list[str] = []
    if percentile:
        method = "percentile"
        absolute_sigma = True
    if x_weight_column and method != "odr" and not percentile:
        prefit_warnings.append("X uncertainty requires Orthogonal Distance Regression; method was switched to ODR.")
        method = "odr"

    if method == "lm" and any(np.isfinite(lower[index]) or np.isfinite(upper[index]) for index in free_indices):
        raise MathOperationError("Levenberg-Marquardt does not support finite bounds. Use TRF or Dogbox.")

    if method == "lm" and len(x_values) < len(free_indices):
        raise MathOperationError(
            "Levenberg-Marquardt requires at least as many data points as fit parameters."
        )

    sigma = _sigma_values(aligned, "weight" if weight_column else None, "Y", weight_mode)
    x_sigma = _sigma_values(aligned, "x_weight" if x_weight_column else None, "X", weight_mode)

    def error_model(axis: str, bounds: PercentileBounds | None, sigma: np.ndarray | None) -> QuantileNormal:
        if bounds is not None:
            return QuantileNormal(aligned[axis].to_numpy() - aligned[f"{axis}_lower"].to_numpy(),
                                  aligned[f"{axis}_upper"].to_numpy() - aligned[axis].to_numpy(),
                                  bounds.lower_probability, bounds.upper_probability)
        return QuantileNormal.normal(sigma if sigma is not None else np.ones(len(aligned)))

    evaluation_x = x_values
    negative_log_likelihood = None
    
    captured_warnings: list[str] = list(prefit_warnings)
    if free_indices or percentile:
        try:
            with warnings.catch_warnings(record=True) as warning_records:
                warnings.simplefilter("always")
                warnings.filterwarnings("ignore", message=".*scipy\\.odr.*", category=Warning)
                
                if percentile:
                    likelihood_parameters, likelihood_covariance, evaluation_x, negative_log_likelihood, messages = likelihood_fit(
                        model.function, x_values, y_values, np.asarray(p0), np.asarray(lower), np.asarray(upper),
                        np.asarray(free_indices, dtype=int), error_model("y", y_bounds, sigma),
                        error_model("x", x_bounds, x_sigma) if x_bounds is not None or x_sigma is not None else None,
                        check_cancelled=check_cancelled)
                    free_parameters = likelihood_parameters[list(free_indices)]
                    free_covariance = likelihood_covariance[np.ix_(free_indices, free_indices)]
                    captured_warnings.extend(messages)
                    if y_bounds is None and sigma is None:
                        captured_warnings.append("Y likelihood uses unit standard deviation because no Y uncertainty was selected.")
                elif method == "odr":
                    free_parameters, free_covariance, odr_warnings = _run_odr_fit(
                        function=model.function,
                        initial_parameters=p0,
                        free_indices=free_indices,
                        x_values=x_values,
                        y_values=y_values,
                        x_sigma=x_sigma,
                        y_sigma=sigma,
                        lower_bounds=lower,
                        upper_bounds=upper,
                        absolute_sigma=absolute_sigma,
                    )
                    captured_warnings.extend(odr_warnings)
                else:
                    curve_fit_kwargs = {
                        "p0": [p0[index] for index in free_indices],
                        "sigma": sigma,
                        "absolute_sigma": absolute_sigma,
                        "method": method,
                        "maxfev": 50000,
                    }
                    if method != "lm":
                        curve_fit_kwargs["bounds"] = (
                            [lower[index] for index in free_indices],
                            [upper[index] for index in free_indices],
                        )
                    free_parameters, free_covariance = curve_fit(
                        _free_parameter_function(model.function, p0, free_indices),
                        x_values,
                        y_values,
                        **curve_fit_kwargs,
                    )
                captured_warnings.extend(str(record.message) for record in warning_records)
        except JobCancelled:
            raise
        except Exception as exc:
            raise MathOperationError(f"Curve fit failed: {exc}") from exc

        parameters = np.asarray(p0, dtype=float)
        parameters[list(free_indices)] = free_parameters
        covariance = np.zeros((parameter_count, parameter_count), dtype=float)
        free_covariance = np.asarray(free_covariance, dtype=float)
        if free_covariance.shape == (len(free_indices), len(free_indices)):
            for row_position, row_index in enumerate(free_indices):
                for column_position, column_index in enumerate(free_indices):
                    covariance[row_index, column_index] = free_covariance[row_position, column_position]
        else:
            covariance[:, :] = np.nan
    else:
        parameters = np.asarray(p0, dtype=float)
        covariance = np.zeros((parameter_count, parameter_count), dtype=float)
        captured_warnings.append("All parameters were fixed; no optimization was performed.")

    fitted_y = np.asarray(model.function(evaluation_x, *parameters), dtype=float)
    residuals = y_values - fitted_y
    report = _build_report(
        model_key=model_key,
        model_name=model.name,
        equation=model.equation,
        method=method,
        x_column=x_column,
        y_column=y_column,
        parameter_names=model.parameter_names,
        parameters=parameters,
        covariance=covariance,
        fixed_parameters=fixed,
        lower_bounds=lower,
        upper_bounds=upper,
        x_weight_column=x_weight_column,
        weight_column=weight_column,
        weight_mode=weight_mode,
        absolute_sigma=absolute_sigma,
        confidence_level=confidence_level if include_confidence_band else 0.0,
        y_values=y_values,
        residuals=residuals,
        warnings=captured_warnings,
    )
    if percentile:
        from dataclasses import replace
        report = replace(report, x_bounds=x_bounds.to_state() if x_bounds else None,
                         y_bounds=y_bounds.to_state() if y_bounds else None,
                         negative_log_likelihood=negative_log_likelihood)

    x_min = float(np.nanmin(x_values))
    x_max = float(np.nanmax(x_values))
    point_count = max(int(fit_points), 2)
    fit_x = np.linspace(x_min, x_max, point_count)
    fit_y = np.asarray(model.function(fit_x, *parameters), dtype=float)
    fit_frame = pd.DataFrame({"fit_x": fit_x, "fit_y": fit_y})
    if include_confidence_band:
        lower_band, upper_band = _confidence_band(
            model.function,
            fit_x,
            parameters,
            covariance,
            confidence_level=confidence_level,
            degrees_of_freedom=max(len(x_values) - len(free_indices), 1),
            normal_approximation=percentile,
        )
        fit_frame["fit_lower"] = lower_band
        fit_frame["fit_upper"] = upper_band

    residual_frame = pd.DataFrame(
        {
            "x": x_values,
            "observed": y_values,
            "fitted": fitted_y,
            "residual": residuals,
        }
    )
    if sigma is not None:
        residual_frame["sigma"] = sigma
    if x_sigma is not None:
        residual_frame["x_sigma"] = x_sigma
    for axis, bounds in (("x", x_bounds), ("y", y_bounds)):
        if bounds:
            residual_frame[f"{axis}_lower_bound"] = aligned[f"{axis}_lower"].to_numpy()
            residual_frame[f"{axis}_upper_bound"] = aligned[f"{axis}_upper"].to_numpy()
    if percentile:
        residual_frame["likelihood_residual"] = error_model("y", y_bounds, sigma).transform(residuals)[0]
        if x_bounds is not None or x_sigma is not None:
            residual_frame["latent_x"] = evaluation_x
            residual_frame["x_residual"] = x_values - evaluation_x

    return FitResult(fit_frame=fit_frame, residual_frame=residual_frame, report=report)


def _fit_input_frame(
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    weight_column: str | None,
    x_weight_column: str | None = None,
    x_bounds: PercentileBounds | None = None,
    y_bounds: PercentileBounds | None = None,
) -> pd.DataFrame:
    """Return aligned numeric fit inputs and optional weights."""
    if x_column not in frame.columns:
        raise MathOperationError(f"Column '{x_column}' does not exist.")
    if y_column not in frame.columns:
        raise MathOperationError(f"Column '{y_column}' does not exist.")

    x_values = pd.to_numeric(frame[x_column], errors="coerce")
    y_values = pd.to_numeric(frame[y_column], errors="coerce")
    validate_numeric_column_metadata(frame, x_column, x_values)
    validate_numeric_column_metadata(frame, y_column, y_values)
    values = {
        "x": x_values,
        "y": y_values,
    }
    for axis, bounds in (("x", x_bounds), ("y", y_bounds)):
        if bounds is not None:
            for side, column in (("lower", bounds.lower_column), ("upper", bounds.upper_column)):
                if column not in frame.columns:
                    raise MathOperationError(f"Percentile column '{column}' does not exist.")
                numeric = pd.to_numeric(frame[column], errors="coerce")
                validate_numeric_column_metadata(frame, column, numeric)
                if not np.isfinite(numeric.to_numpy(dtype=float)).all():
                    raise MathOperationError(f"Percentile column '{column}' must contain finite bounds for every row.")
                values[f"{axis}_{side}"] = numeric
    if weight_column:
        if weight_column not in frame.columns:
            raise MathOperationError(f"Weight column '{weight_column}' does not exist.")
        weight_values = pd.to_numeric(frame[weight_column], errors="coerce")
        validate_numeric_column_metadata(frame, weight_column, weight_values)
        values["weight"] = weight_values
    
    if x_weight_column:
        if x_weight_column not in frame.columns:
            raise MathOperationError(f"X weight column '{x_weight_column}' does not exist.")
        x_weight_values = pd.to_numeric(frame[x_weight_column], errors="coerce")
        validate_numeric_column_metadata(frame, x_weight_column, x_weight_values)
        values["x_weight"] = x_weight_values

    aligned = pd.DataFrame(values).replace([np.inf, -np.inf], np.nan).dropna()

    if len(aligned) < 2:
        raise MathOperationError("Curve fitting requires at least two aligned numeric points.")
    if aligned["x"].nunique() < 2:
        raise MathOperationError("Curve fitting requires at least two distinct X values.")
    return aligned


def _normalize_bounds(
    bounds: list[float | None] | tuple[float | None, ...] | None,
    parameter_count: int,
    fallback: float,
) -> tuple[float, ...]:
    """Return a full bound tuple, replacing blanks with an infinite fallback."""
    if bounds is None:
        return tuple([fallback] * parameter_count)
    if len(bounds) != parameter_count:
        raise MathOperationError(f"Expected {parameter_count} bound value(s).")
    return tuple(fallback if value is None else float(value) for value in bounds)


def _validate_parameter_settings(
    p0: tuple[float, ...],
    lower: tuple[float, ...],
    upper: tuple[float, ...],
    fixed: tuple[bool, ...],
    parameter_names: tuple[str, ...],
) -> None:
    """Validate initial guesses, bounds, and fixed/free parameter settings."""
    for index, (initial, lower_value, upper_value) in enumerate(zip(p0, lower, upper)):
        if lower_value > upper_value:
            raise MathOperationError(f"Lower bound exceeds upper bound for {parameter_names[index]}.")
        if not fixed[index] and lower_value == upper_value:
            raise MathOperationError(
                f"Lower and upper bounds are equal for {parameter_names[index]}; mark it fixed instead."
            )
        if not lower_value <= initial <= upper_value:
            raise MathOperationError(f"Initial value for {parameter_names[index]} must be inside its bounds.")
        if fixed[index] and (np.isfinite(lower_value) or np.isfinite(upper_value)):
            if not lower_value <= initial <= upper_value:
                raise MathOperationError(f"Fixed value for {parameter_names[index]} must be inside its bounds.")


def _sigma_values(
    aligned: pd.DataFrame,
    aligned_column: str | None,
    axis_label: str,
    weight_mode: str,
) -> np.ndarray | None:
    """Return positive sigma values from an aligned sigma or weight column."""
    if not aligned_column:
        return None

    values = aligned[aligned_column].to_numpy(dtype=float)
    if np.any(values <= 0):
        raise MathOperationError(f"{axis_label} weight/sigma values must be positive.")

    if weight_mode == "sigma":
        return values
    if weight_mode == "weight":
        return 1.0 / np.sqrt(values)
    raise MathOperationError(f"Unknown weight mode: {weight_mode}")


def _run_odr_fit(
    function: object,
    initial_parameters: tuple[float, ...],
    free_indices: tuple[int, ...],
    x_values: np.ndarray,
    y_values: np.ndarray,
    x_sigma: np.ndarray | None,
    y_sigma: np.ndarray | None,
    lower_bounds: tuple[float, ...],
    upper_bounds: tuple[float, ...],
    absolute_sigma: bool,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Fit with ODR, preferring the maintained odrpack package."""
    try:
        return _run_odrpack_fit(
            function=function,
            initial_parameters=initial_parameters,
            free_indices=free_indices,
            x_values=x_values,
            y_values=y_values,
            x_sigma=x_sigma,
            y_sigma=y_sigma,
            lower_bounds=lower_bounds,
            upper_bounds=upper_bounds,
            absolute_sigma=absolute_sigma,
        )
    except ImportError:
        return _run_scipy_odr_fit(
            function=function,
            initial_parameters=initial_parameters,
            free_indices=free_indices,
            x_values=x_values,
            y_values=y_values,
            x_sigma=x_sigma,
            y_sigma=y_sigma,
            absolute_sigma=absolute_sigma,
        )


def _run_odrpack_fit(
    function: object,
    initial_parameters: tuple[float, ...],
    free_indices: tuple[int, ...],
    x_values: np.ndarray,
    y_values: np.ndarray,
    x_sigma: np.ndarray | None,
    y_sigma: np.ndarray | None,
    lower_bounds: tuple[float, ...],
    upper_bounds: tuple[float, ...],
    absolute_sigma: bool,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Run ODR through the maintained external odrpack package."""
    from odrpack import odr_fit

    beta0 = np.asarray([initial_parameters[index] for index in free_indices], dtype=float)

    def wrapped(x_data: np.ndarray, free_parameters: np.ndarray) -> np.ndarray:
        """Evaluate an ODRPACK model with free parameters merged into fixed values."""
        full_parameters = np.asarray(initial_parameters, dtype=float)
        full_parameters[list(free_indices)] = free_parameters
        return function(x_data, *full_parameters)

    fit_kwargs: dict[str, object] = {"maxit": _ODR_MAX_ITERATIONS}

    lower = np.asarray([lower_bounds[index] for index in free_indices], dtype=float)
    upper = np.asarray([upper_bounds[index] for index in free_indices], dtype=float)
    if np.isfinite(lower).any() or np.isfinite(upper).any():
        fit_kwargs["bounds"] = (lower, upper)

    if x_sigma is not None:
        fit_kwargs["weight_x"] = 1.0 / np.square(x_sigma)
    if y_sigma is not None:
        fit_kwargs["weight_y"] = 1.0 / np.square(y_sigma)

    result = odr_fit(wrapped, x_values, y_values, beta0, **fit_kwargs)
    covariance = np.asarray(result.cov_beta, dtype=float)
    if not absolute_sigma:
        covariance = covariance * float(result.res_var)

    messages: list[str] = []
    if not bool(result.success):
        messages.append(f"ODR may not have converged. Stop reason: {result.stopreason}")
    return np.asarray(result.beta, dtype=float), covariance, messages


def _run_scipy_odr_fit(
    function: object,
    initial_parameters: tuple[float, ...],
    free_indices: tuple[int, ...],
    x_values: np.ndarray,
    y_values: np.ndarray,
    x_sigma: np.ndarray | None,
    y_sigma: np.ndarray | None,
    absolute_sigma: bool,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Run ODR through scipy.odr as a compatibility fallback."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*scipy\\.odr.*", category=DeprecationWarning)
        warnings.filterwarnings("ignore", message=".*scipy\\.odr.*", category=FutureWarning)
        from scipy.odr import Model, Data, ODR, RealData

    def odr_wrapper(beta: np.ndarray, x_data: np.ndarray) -> np.ndarray:
        """Evaluate a scipy.odr model with free parameters merged into fixed values."""
        full_parameters = np.asarray(initial_parameters, dtype=float)
        full_parameters[list(free_indices)] = beta
        return function(x_data, *full_parameters)

    odr_model = Model(odr_wrapper)
    if y_sigma is not None or x_sigma is not None:
        data = RealData(x_values, y_values, sx=x_sigma, sy=y_sigma)
    else:
        data = Data(x_values, y_values)

    odr_obj = ODR(
        data,
        odr_model,
        beta0=[initial_parameters[index] for index in free_indices],
        maxit=_ODR_MAX_ITERATIONS,
    )
    output = odr_obj.run()
    covariance = (
        np.full((len(free_indices), len(free_indices)), np.nan)
        if output.cov_beta is None
        else np.asarray(output.cov_beta, dtype=float)
    )
    if not absolute_sigma:
        covariance = covariance * float(output.res_var)

    messages = ["Using scipy.odr compatibility fallback; install odrpack to use the maintained ODR backend."]
    if output.info not in (1, 2, 3):
        messages.append(f"ODR may not have converged. Stop reason: {output.stopreason}")
    return np.asarray(output.beta, dtype=float), covariance, messages


def _free_parameter_function(
    function: object,
    initial_parameters: tuple[float, ...],
    free_indices: tuple[int, ...],
) -> object:
    """Wrap a model so curve_fit optimizes only free parameters."""
    def wrapped(x_values: np.ndarray, *free_parameters: float) -> np.ndarray:
        """Evaluate the model after merging free parameters into fixed values."""
        parameters = np.asarray(initial_parameters, dtype=float)
        parameters[list(free_indices)] = free_parameters
        return function(x_values, *parameters)

    return wrapped


def _confidence_band(
    function: object,
    x_values: np.ndarray,
    parameters: np.ndarray,
    covariance: np.ndarray,
    confidence_level: float,
    degrees_of_freedom: int,
    normal_approximation: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Estimate pointwise confidence bands from covariance and a Jacobian."""
    fit_y = np.asarray(function(x_values, *parameters), dtype=float)
    if covariance.shape != (len(parameters), len(parameters)) or not np.isfinite(covariance).any():
        nan_band = np.full_like(fit_y, np.nan, dtype=float)
        return nan_band, nan_band

    jacobian = _numerical_jacobian(function, x_values, parameters)
    prediction_variance = np.einsum("ij,jk,ik->i", jacobian, covariance, jacobian)
    prediction_variance = np.maximum(prediction_variance, 0.0)
    standard_error = np.sqrt(prediction_variance)
    alpha = 1.0 - min(max(confidence_level, 0.001), 0.999)
    critical_value = float(norm.ppf(1.0 - alpha / 2.0) if normal_approximation
                           else student_t.ppf(1.0 - alpha / 2.0, degrees_of_freedom))
    margin = critical_value * standard_error
    return fit_y - margin, fit_y + margin


def _numerical_jacobian(function: object, x_values: np.ndarray, parameters: np.ndarray) -> np.ndarray:
    """Return a finite-difference Jacobian for confidence band propagation."""
    base_parameters = np.asarray(parameters, dtype=float)
    jacobian = np.empty((len(x_values), len(base_parameters)), dtype=float)
    for parameter_index, parameter_value in enumerate(base_parameters):
        step = np.sqrt(np.finfo(float).eps) * max(abs(parameter_value), 1.0)
        plus = base_parameters.copy()
        minus = base_parameters.copy()
        plus[parameter_index] += step
        minus[parameter_index] -= step
        y_plus = np.asarray(function(x_values, *plus), dtype=float)
        y_minus = np.asarray(function(x_values, *minus), dtype=float)
        jacobian[:, parameter_index] = (y_plus - y_minus) / (2.0 * step)
    return jacobian


def _build_report(
    model_key: str,
    model_name: str,
    equation: str,
    method: str,
    x_column: str,
    y_column: str,
    parameter_names: tuple[str, ...],
    parameters: np.ndarray,
    covariance: np.ndarray,
    fixed_parameters: tuple[bool, ...],
    lower_bounds: tuple[float, ...],
    upper_bounds: tuple[float, ...],
    x_weight_column: str | None,
    weight_column: str | None,
    weight_mode: str,
    absolute_sigma: bool,
    confidence_level: float,
    y_values: np.ndarray,
    residuals: np.ndarray,
    warnings: list[str],
) -> FitReport:
    """Build fit metrics and package them into a FitReport."""
    parameter_count = len(parameters)
    point_count = len(y_values)

    if covariance.shape != (parameter_count, parameter_count):
        covariance = np.full((parameter_count, parameter_count), np.nan)

    with np.errstate(invalid="ignore"):
        standard_errors = np.sqrt(np.diag(covariance))

    ss_residual = float(np.sum(residuals**2))
    ss_total = float(np.sum((y_values - np.mean(y_values)) ** 2))
    r_squared = np.nan if ss_total == 0.0 else 1.0 - ss_residual / ss_total
    adjusted_r_squared = np.nan
    if np.isfinite(r_squared) and point_count > parameter_count + 1:
        adjusted_r_squared = 1.0 - (1.0 - r_squared) * (point_count - 1) / (
            point_count - parameter_count - 1
        )

    rmse = float(np.sqrt(np.mean(residuals**2)))
    mae = float(np.mean(np.abs(residuals)))
    residual_mean = float(np.mean(residuals))
    residual_std = float(np.std(residuals, ddof=1)) if point_count > 1 else np.nan

    covariance_tuple = tuple(tuple(float(value) for value in row) for row in covariance)
    return FitReport(
        model_key=model_key,
        model_name=model_name,
        equation=equation,
        method=method,
        x_column=x_column,
        y_column=y_column,
        parameter_names=parameter_names,
        parameters=tuple(float(value) for value in parameters),
        standard_errors=tuple(float(value) for value in standard_errors),
        covariance=covariance_tuple,
        fixed_parameters=fixed_parameters,
        lower_bounds=tuple(float(value) for value in lower_bounds),
        upper_bounds=tuple(float(value) for value in upper_bounds),
        x_weight_column=x_weight_column,
        weight_column=weight_column,
        weight_mode=weight_mode,
        absolute_sigma=absolute_sigma,
        confidence_level=confidence_level,
        r_squared=float(r_squared),
        adjusted_r_squared=float(adjusted_r_squared),
        rmse=rmse,
        mae=mae,
        residual_mean=residual_mean,
        residual_std=residual_std,
        point_count=point_count,
        warnings=tuple(warnings),
    )


def _format_number(value: float) -> str:
    """Format report numbers while handling infinities and NaNs."""
    if value == np.inf:
        return "inf"
    if value == -np.inf:
        return "-inf"
    if not np.isfinite(value):
        return "n/a"
    return f"{value:.8g}"
