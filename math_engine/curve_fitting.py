"""Phase 4 curve-fitting operations."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeWarning, curve_fit

from math_engine.calculus import MathOperationError
from models.fit_functions import default_initial_parameters, get_fit_model


FIT_METHODS: dict[str, str] = {
    "lm": "Levenberg-Marquardt",
    "trf": "Trust Region Reflective",
    "dogbox": "Dogbox",
}


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
    r_squared: float
    adjusted_r_squared: float
    rmse: float
    mae: float
    residual_mean: float
    residual_std: float
    point_count: int
    warnings: tuple[str, ...] = ()

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

        for name, value, error in zip(self.parameter_names, self.parameters, self.standard_errors):
            lines.append(f"  {name} = {_format_number(value)} +/- {_format_number(error)}")

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
    report: FitReport


def fit_curve(
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    model_key: str,
    method: str,
    initial_parameters: list[float] | tuple[float, ...] | None = None,
    fit_points: int = 400,
) -> FitResult:
    """Fit a registered analytical model to two numeric columns."""
    if method not in FIT_METHODS:
        raise MathOperationError(f"Unknown fitting method: {method}")

    model = get_fit_model(model_key)
    aligned = _xy_frame(frame, x_column, y_column)
    x_values = aligned["x"].to_numpy(dtype=float)
    y_values = aligned["y"].to_numpy(dtype=float)

    p0 = tuple(initial_parameters) if initial_parameters is not None else default_initial_parameters(
        model_key,
        x_values,
        y_values,
    )
    if len(p0) != len(model.parameter_names):
        raise MathOperationError(
            f"{model.name} expects {len(model.parameter_names)} initial parameter(s): "
            f"{', '.join(model.parameter_names)}."
        )

    if method == "lm" and len(x_values) < len(p0):
        raise MathOperationError(
            "Levenberg-Marquardt requires at least as many data points as fit parameters."
        )

    captured_warnings: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as warning_records:
            warnings.simplefilter("always", OptimizeWarning)
            parameters, covariance = curve_fit(
                model.function,
                x_values,
                y_values,
                p0=p0,
                method=method,
                maxfev=50000,
            )
            captured_warnings = [str(record.message) for record in warning_records]
    except Exception as exc:
        raise MathOperationError(f"Curve fit failed: {exc}") from exc

    fitted_y = np.asarray(model.function(x_values, *parameters), dtype=float)
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
        y_values=y_values,
        residuals=residuals,
        warnings=captured_warnings,
    )

    x_min = float(np.nanmin(x_values))
    x_max = float(np.nanmax(x_values))
    point_count = max(int(fit_points), 2)
    fit_x = np.linspace(x_min, x_max, point_count)
    fit_y = np.asarray(model.function(fit_x, *parameters), dtype=float)
    fit_frame = pd.DataFrame({"fit_x": fit_x, "fit_y": fit_y})

    return FitResult(fit_frame=fit_frame, report=report)


def _xy_frame(frame: pd.DataFrame, x_column: str, y_column: str) -> pd.DataFrame:
    if x_column not in frame.columns:
        raise MathOperationError(f"Column '{x_column}' does not exist.")
    if y_column not in frame.columns:
        raise MathOperationError(f"Column '{y_column}' does not exist.")

    aligned = pd.DataFrame(
        {
            "x": pd.to_numeric(frame[x_column], errors="coerce"),
            "y": pd.to_numeric(frame[y_column], errors="coerce"),
        }
    ).replace([np.inf, -np.inf], np.nan).dropna()

    if len(aligned) < 2:
        raise MathOperationError("Curve fitting requires at least two aligned numeric points.")
    if aligned["x"].nunique() < 2:
        raise MathOperationError("Curve fitting requires at least two distinct X values.")
    return aligned


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
    y_values: np.ndarray,
    residuals: np.ndarray,
    warnings: list[str],
) -> FitReport:
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
    if not np.isfinite(value):
        return "n/a"
    return f"{value:.8g}"
