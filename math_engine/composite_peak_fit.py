"""Composite multi-peak fitting using the application's registered peak models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import integrate, optimize

from math_engine.calculus import MathOperationError
from math_engine.peak_detection import PeakRecord
from models.fit_functions import FitModel, available_fit_models, get_fit_model


SUPPORTED_COMPOSITE_PEAK_MODELS: tuple[str, ...] = (
    "gaussian",
    "lorentzian",
    "voigt",
    "pseudo_voigt",
    "pearson_vii",
    "sech_squared",
    "laplace_peak",
    "fano_peak",
    "asymmetric_gaussian",
    "split_lorentzian",
    "emg",
    "fraser_suzuki",
    "doniach_sunjic",
)


@dataclass(frozen=True, slots=True)
class PeakComponentSpec:
    """Serializable model choice and parameter controls for one reviewed peak."""

    model_key: str
    peak: PeakRecord
    enabled: bool = True
    initial_parameters: tuple[float, ...] = ()
    lower_bounds: tuple[float | None, ...] = ()
    upper_bounds: tuple[float | None, ...] = ()
    fixed_parameters: tuple[bool, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["peak"] = self.peak.to_dict()
        return values


@dataclass(frozen=True, slots=True)
class CompositeFitParameters:
    """Serializable settings shared by all components in one composite fit."""

    data_mode: str = "corrected"
    baseline_model: str = "zero"
    maximum_evaluations: int = 20_000
    loss: str = "linear"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CompositeFitResult:
    """Composite curve, components, diagnostics, and tidy fitted parameters."""

    fit_frame: pd.DataFrame
    parameter_frame: pd.DataFrame
    covariance: tuple[tuple[float, ...], ...]
    r_squared: float
    rmse: float
    mae: float
    aic: float
    bic: float
    converged: bool
    message: str
    evaluations: int
    parameters: CompositeFitParameters
    components: tuple[PeakComponentSpec, ...]
    warnings: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)


def available_composite_peak_models() -> list[FitModel]:
    """Return registered peak models suitable for additive composite fitting."""
    supported = set(SUPPORTED_COMPOSITE_PEAK_MODELS)
    return [
        model
        for model in available_fit_models()
        if model.is_peak and model.key in supported and "offset" in model.parameter_names
    ]


def build_peak_component_spec(
    peak: PeakRecord,
    model_key: str,
    x_values: np.ndarray,
) -> PeakComponentSpec:
    """Create model-correct starting values and physical bounds for one peak."""
    model = _composite_model(model_key)
    x = np.asarray(x_values, dtype=float)
    finite_x = x[np.isfinite(x)]
    if finite_x.size < 2:
        raise MathOperationError("Composite peak fitting requires at least two finite X values.")
    x_min = float(np.min(finite_x))
    x_max = float(np.max(finite_x))
    span = max(x_max - x_min, np.finfo(float).eps)
    fwhm = peak.fwhm if np.isfinite(peak.fwhm) and peak.fwhm > 0 else span / 20.0

    if model.key == "fano_peak":
        gamma = max(fwhm / 2.0, span * 1.0e-9, np.finfo(float).eps)
        q = 2.0 if peak.polarity == "positive" else 0.5
        if np.isfinite(peak.asymmetry) and peak.asymmetry < 0.0:
            q = -q
        if peak.polarity == "positive":
            scale = abs(float(peak.corrected_height)) / (q * q)
            resonance_center = float(peak.center) - gamma / q
        else:
            scale = abs(float(peak.corrected_height))
            resonance_center = float(peak.center) + gamma * q
        return PeakComponentSpec(
            model_key=model_key,
            peak=peak,
            initial_parameters=(
                max(scale, np.finfo(float).eps),
                float(np.clip(resonance_center, x_min, x_max)),
                gamma,
                q,
            ),
            lower_bounds=(np.finfo(float).eps, x_min, max(span * 1.0e-9, np.finfo(float).eps), None),
            upper_bounds=(None, x_max, span * 2.0, None),
            fixed_parameters=(False, False, False, False),
        )

    initial: list[float] = []
    lower: list[float | None] = []
    upper: list[float | None] = []
    fixed: list[bool] = []
    for index, (name, role) in enumerate(zip(model.parameter_names, model.parameter_roles)):
        if role == "offset":
            continue
        default = float(model.default_initial[index])
        if role == "center":
            value = float(peak.center)
            low, high = x_min, x_max
        elif role == "height":
            value = float(peak.corrected_height)
            low, high = None, None
        elif role == "area":
            value = float(peak.area) if np.isfinite(peak.area) and peak.area != 0 else (
                float(peak.corrected_height) * fwhm * 1.064467
            )
            low, high = None, None
        elif role == "width":
            value = _width_from_fwhm(model.key, name, fwhm, model.default_initial)
            low, high = max(span * 1.0e-9, np.finfo(float).eps), span * 2.0
        else:
            value = default
            low = model.default_lower[index] if model.default_lower else None
            high = model.default_upper[index] if model.default_upper else None
        initial.append(value)
        lower.append(low)
        upper.append(high)
        fixed.append(False)
    return PeakComponentSpec(
        model_key=model_key,
        peak=peak,
        initial_parameters=tuple(initial),
        lower_bounds=tuple(lower),
        upper_bounds=tuple(upper),
        fixed_parameters=tuple(fixed),
    )


def fit_composite_peaks(
    x_values: np.ndarray,
    raw_values: np.ndarray,
    corrected_values: np.ndarray,
    components: list[PeakComponentSpec] | tuple[PeakComponentSpec, ...],
    parameters: CompositeFitParameters | None = None,
    *,
    provenance: dict[str, Any] | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> CompositeFitResult:
    """Fit a shared baseline and peak components, optionally checking cancellation."""
    if check_cancelled is not None:
        check_cancelled()
    settings = parameters or CompositeFitParameters()
    _validate_fit_parameters(settings)
    x = np.asarray(x_values, dtype=float)
    raw = np.asarray(raw_values, dtype=float)
    corrected = np.asarray(corrected_values, dtype=float)
    if x.ndim != 1 or raw.shape != x.shape or corrected.shape != x.shape:
        raise MathOperationError("Composite fitting requires equal-length one-dimensional arrays.")
    active = tuple(component for component in components if component.enabled)
    if not active:
        raise MathOperationError("Enable at least one peak component before fitting.")

    observed_source = corrected if settings.data_mode == "corrected" else raw
    finite = np.isfinite(x) & np.isfinite(observed_source)
    if np.count_nonzero(finite) < 4:
        raise MathOperationError("Composite fitting requires at least four finite X/Y points.")
    fit_x = x[finite]
    observed = observed_source[finite]
    order = np.argsort(fit_x, kind="stable")
    fit_x = fit_x[order]
    observed = observed[order]
    if np.any(np.diff(fit_x) <= 0):
        raise MathOperationError("Composite fitting requires unique X coordinates.")

    baseline_names, baseline_initial, baseline_lower, baseline_upper = _baseline_settings(
        settings, fit_x, observed
    )
    parameter_names = [f"baseline.{name}" for name in baseline_names]
    initial = list(baseline_initial)
    lower = list(baseline_lower)
    upper = list(baseline_upper)
    fixed = [False] * len(initial)
    layouts: list[tuple[PeakComponentSpec, FitModel, list[str], slice]] = []
    for component_index, component in enumerate(active, start=1):
        model = _composite_model(component.model_key)
        names = [
            name
            for name, role in zip(model.parameter_names, model.parameter_roles)
            if role != "offset"
        ]
        expected = len(names)
        if len(component.initial_parameters) != expected:
            component = build_peak_component_spec(component.peak, component.model_key, fit_x)
        start = len(initial)
        initial.extend(component.initial_parameters)
        lower.extend(_numeric_bounds(component.lower_bounds, expected, -np.inf))
        upper.extend(_numeric_bounds(component.upper_bounds, expected, np.inf))
        component_fixed = list(component.fixed_parameters or (False,) * expected)
        if len(component_fixed) != expected:
            raise MathOperationError(f"{model.name} fixed-parameter settings do not match its parameters.")
        fixed.extend(component_fixed)
        parameter_names.extend(f"peak_{component_index}.{name}" for name in names)
        layouts.append((component, model, names, slice(start, start + expected)))

    initial_array = np.asarray(initial, dtype=float)
    lower_array = np.asarray(lower, dtype=float)
    upper_array = np.asarray(upper, dtype=float)
    fixed_array = np.asarray(fixed, dtype=bool)
    if np.any(lower_array >= upper_array):
        raise MathOperationError("Every composite-fit lower bound must be below its upper bound.")
    initial_array = np.maximum(np.minimum(initial_array, upper_array), lower_array)
    free_indices = np.flatnonzero(~fixed_array)

    def calculate(all_parameters: np.ndarray) -> tuple[np.ndarray, list[np.ndarray], np.ndarray]:
        baseline = _evaluate_baseline(settings, fit_x, all_parameters[: len(baseline_names)])
        component_values: list[np.ndarray] = []
        total = baseline.copy()
        for _spec, model, names, component_slice in layouts:
            values_by_name = dict(zip(names, all_parameters[component_slice]))
            full_values = [
                0.0 if role == "offset" else float(values_by_name[name])
                for name, role in zip(model.parameter_names, model.parameter_roles)
            ]
            values = np.asarray(model.function(fit_x, *full_values), dtype=float)
            component_values.append(values)
            total = total + values
        return total, component_values, baseline

    def expand_free(free_values: np.ndarray) -> np.ndarray:
        values = initial_array.copy()
        values[free_indices] = free_values
        return values

    def residuals(free_values: np.ndarray) -> np.ndarray:
        if check_cancelled is not None:
            check_cancelled()
        total, _components, _baseline = calculate(expand_free(free_values))
        residual = total - observed
        return np.nan_to_num(residual, nan=1.0e30, posinf=1.0e30, neginf=-1.0e30)

    try:
        starts = _fano_multistart_parameters(
            initial_array,
            lower_array,
            upper_array,
            layouts,
        )
        solutions = [
            optimize.least_squares(
                residuals,
                start[free_indices],
                bounds=(lower_array[free_indices], upper_array[free_indices]),
                max_nfev=max(100, int(settings.maximum_evaluations)),
                loss=settings.loss,
            )
            for start in starts
        ]
        solution = min(solutions, key=lambda candidate: float(np.sum(candidate.fun**2)))
    except (ValueError, RuntimeError, FloatingPointError) as exc:
        raise MathOperationError(f"Composite peak fit failed: {exc}") from exc

    fitted_parameters = expand_free(solution.x)
    if check_cancelled is not None:
        check_cancelled()
    total, component_values, baseline = calculate(fitted_parameters)
    residual = observed - total
    point_count = len(observed)
    free_count = len(free_indices)
    rss = float(np.sum(residual**2))
    tss = float(np.sum((observed - np.mean(observed)) ** 2))
    rmse = float(np.sqrt(np.mean(residual**2)))
    mae = float(np.mean(np.abs(residual)))
    r_squared = 1.0 - rss / tss if tss > 0 else float("nan")
    safe_rss = max(rss, np.finfo(float).tiny)
    aic = float(point_count * np.log(safe_rss / point_count) + 2 * free_count)
    bic = float(point_count * np.log(safe_rss / point_count) + free_count * np.log(point_count))
    covariance, standard_errors, covariance_warning = _covariance_from_solution(
        solution, point_count, free_count, len(initial_array), free_indices, rss
    )

    fit_data: dict[str, np.ndarray] = {
        "x": fit_x,
        "observed": observed,
        "baseline": baseline,
        "total_fit": total,
        "residual": residual,
    }
    for index, values in enumerate(component_values, start=1):
        fit_data[f"peak_{index}"] = values

    parameter_rows: list[dict[str, Any]] = []
    for index, name in enumerate(baseline_names):
        parameter_rows.append({
            "component": "baseline", "component_index": 0,
            "model": settings.baseline_model, "parameter": name,
            "role": "baseline", "value": fitted_parameters[index],
            "standard_error": standard_errors[index], "fixed": bool(fixed_array[index]),
            "lower_bound": lower_array[index], "upper_bound": upper_array[index],
        })
    for component_index, (component, model, names, component_slice) in enumerate(layouts, start=1):
        component_parameter_rows: list[dict[str, Any]] = []
        for local_index, name in enumerate(names):
            global_index = component_slice.start + local_index
            model_index = model.parameter_names.index(name)
            row = {
                "component": f"peak_{component_index}", "component_index": component_index,
                "model": model.name, "parameter": name,
                "role": model.parameter_roles[model_index], "value": fitted_parameters[global_index],
                "standard_error": standard_errors[global_index], "fixed": bool(fixed_array[global_index]),
                "lower_bound": lower_array[global_index], "upper_bound": upper_array[global_index],
            }
            parameter_rows.append(row)
            component_parameter_rows.append(row)
        profile_position, profile_intensity, profile_fwhm, profile_asymmetry = _component_profile_metrics(
            fit_x,
            component_values[component_index - 1],
            component.peak.polarity,
        )
        height_error = _first_role_error(component_parameter_rows, "height")
        area_error = _first_role_error(component_parameter_rows, "area")
        asymmetry_error = _named_parameter_error(component_parameter_rows, "asymmetry")
        position_error = _first_role_error(component_parameter_rows, "center")
        if model.key == "fano_peak":
            fano_values = _fano_profile_values(fitted_parameters[component_slice])
            if component.peak.polarity == "negative":
                profile_position = fano_values["dip_position"]
                profile_intensity = fano_values["dip_contrast"]
            else:
                profile_position = fano_values["peak_position"]
                profile_intensity = fano_values["peak_contrast"]
            position_error, height_error = _fano_report_errors(
                fitted_parameters[component_slice],
                covariance[np.ix_(
                    np.arange(component_slice.start, component_slice.stop),
                    np.arange(component_slice.start, component_slice.stop),
                )],
                component.peak.polarity,
            )
        parameter_rows.append({
            "component": f"peak_{component_index}", "component_index": component_index,
            "model": model.name, "parameter": "integrated_area", "role": "area",
            "value": float(integrate.trapezoid(component_values[component_index - 1], fit_x)),
            "standard_error": area_error, "fixed": False,
            "lower_bound": float("nan"), "upper_bound": float("nan"),
        })
        for parameter_name, role, value, standard_error in (
            ("fitted_position", "apex_position", profile_position, position_error),
            ("fitted_intensity", "height", profile_intensity, height_error),
            ("fitted_fwhm", "width", profile_fwhm, float("nan")),
            ("fitted_asymmetry", "shape", profile_asymmetry, asymmetry_error),
        ):
            parameter_rows.append({
                "component": f"peak_{component_index}",
                "component_index": component_index,
                "model": model.name,
                "parameter": parameter_name,
                "role": role,
                "value": value,
                "standard_error": standard_error,
                "fixed": False,
                "lower_bound": float("nan"),
                "upper_bound": float("nan"),
            })
        if model.key == "fano_peak":
            parameter_rows.extend(_fano_derived_rows(
                component_index,
                model.name,
                fitted_parameters[component_slice],
                covariance[np.ix_(
                    np.arange(component_slice.start, component_slice.stop),
                    np.arange(component_slice.start, component_slice.stop),
                )],
            ))

    warning_values = [value for value in (covariance_warning,) if value]
    if any(component.model_key == "fano_peak" for component in active):
        warning_values.append(
            "Fano areas are signed integrals over the selected fitting window; "
            "use resonance position, natural linewidth, q, and peak/dip contrasts for interpretation."
        )
    warnings = tuple(warning_values)
    return CompositeFitResult(
        fit_frame=pd.DataFrame(fit_data),
        parameter_frame=pd.DataFrame(parameter_rows),
        covariance=tuple(tuple(float(value) for value in row) for row in covariance),
        r_squared=float(r_squared),
        rmse=rmse,
        mae=mae,
        aic=aic,
        bic=bic,
        converged=bool(solution.success),
        message=str(solution.message),
        evaluations=int(solution.nfev),
        parameters=settings,
        components=active,
        warnings=warnings,
        provenance=dict(provenance or {}),
    )


def _composite_model(model_key: str) -> FitModel:
    model = get_fit_model(model_key)
    if model_key not in SUPPORTED_COMPOSITE_PEAK_MODELS or not model.is_peak:
        raise MathOperationError(f"Model '{model.name}' is not available for composite peak fitting.")
    if not model.parameter_roles or "offset" not in model.parameter_roles:
        raise MathOperationError(f"Model '{model.name}' does not expose composite-fit parameter roles.")
    return model


def _width_from_fwhm(
    model_key: str,
    parameter_name: str,
    fwhm: float,
    defaults: tuple[float, ...],
) -> float:
    if model_key in {"gaussian", "pseudo_voigt", "asymmetric_gaussian", "emg"}:
        return fwhm / 2.354820045
    if model_key in {"lorentzian", "fano_peak", "split_lorentzian", "doniach_sunjic"}:
        return fwhm / 2.0
    if model_key == "sech_squared":
        return fwhm / (2.0 * np.arccosh(np.sqrt(2.0)))
    if model_key == "laplace_peak":
        return fwhm / (2.0 * np.log(2.0))
    if model_key == "pearson_vii":
        shape = defaults[3] if len(defaults) > 3 else 2.0
        return fwhm / (2.0 * np.sqrt(2.0 ** (1.0 / shape) - 1.0))
    if model_key == "voigt":
        return fwhm / 3.6013
    if model_key == "fraser_suzuki":
        return fwhm
    return max(fwhm / 2.0, np.finfo(float).eps)


def _fano_multistart_parameters(
    initial: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    layouts: list[tuple[PeakComponentSpec, FitModel, list[str], slice]],
) -> list[np.ndarray]:
    """Return bounded physically distinct starts for Fano components.

    A one-lobe detector observes a Fano extremum rather than its resonance
    centre.  Trying both orientations and several useful q magnitudes avoids
    the common local minimum where q runs towards an effectively symmetric
    profile at the wrong centre.
    """
    fano_layouts = [layout for layout in layouts if layout[1].key == "fano_peak"]
    if not fano_layouts:
        return [initial]

    starts = [initial.copy()]
    for q_seed in (-8.0, -3.0, -1.0, -0.35, 0.35, 1.0, 3.0, 8.0):
        candidate = initial.copy()
        for component, _model, names, parameter_slice in fano_layouts:
            local = candidate[parameter_slice].copy()
            indices = {name: index for index, name in enumerate(names)}
            gamma = max(float(local[indices["gamma"]]), np.finfo(float).eps)
            detected_height = float(component.peak.corrected_height)
            if component.peak.polarity == "negative":
                scale = abs(detected_height)
                center = float(component.peak.center) + gamma * q_seed
            else:
                scale = abs(detected_height) / (q_seed * q_seed)
                center = float(component.peak.center) - gamma / q_seed
            local[indices["amplitude"]] = max(scale, np.finfo(float).eps)
            local[indices["center"]] = center
            local[indices["q"]] = q_seed
            candidate[parameter_slice] = local
        candidate = np.maximum(np.minimum(candidate, upper), lower)
        if not any(np.allclose(candidate, existing) for existing in starts):
            starts.append(candidate)
    return starts


def _fano_profile_values(parameters: np.ndarray) -> dict[str, float]:
    """Return physically labelled extrema and linewidth for ``A, x0, gamma, q``."""
    amplitude, center, gamma, q = (float(value) for value in parameters)
    if abs(q) <= np.sqrt(np.finfo(float).eps):
        peak_position = float("nan")
        peak_contrast = 0.0
    else:
        peak_position = center + gamma / q
        peak_contrast = amplitude * q * q
    return {
        "resonance_position": center,
        "natural_linewidth": 2.0 * gamma,
        "peak_position": peak_position,
        "dip_position": center - gamma * q,
        "peak_contrast": peak_contrast,
        "dip_contrast": -amplitude,
        "fano_q": q,
    }


def _delta_standard_error(gradient: np.ndarray, covariance: np.ndarray) -> float:
    """Return a first-order propagated standard error for one derived value."""
    if covariance.shape != (len(gradient), len(gradient)) or not np.all(np.isfinite(covariance)):
        return float("nan")
    variance = float(gradient @ covariance @ gradient)
    if not np.isfinite(variance) or variance < 0.0:
        return float("nan")
    return float(np.sqrt(variance))


def _fano_report_errors(
    parameters: np.ndarray,
    covariance: np.ndarray,
    polarity: str,
) -> tuple[float, float]:
    """Propagate Fano covariance to the reported extremum position/intensity."""
    amplitude, _center, gamma, q = (float(value) for value in parameters)
    if polarity == "negative":
        position_gradient = np.array([0.0, 1.0, -q, -gamma], dtype=float)
        intensity_gradient = np.array([-1.0, 0.0, 0.0, 0.0], dtype=float)
    elif abs(q) > np.sqrt(np.finfo(float).eps):
        position_gradient = np.array([0.0, 1.0, 1.0 / q, -gamma / (q * q)], dtype=float)
        intensity_gradient = np.array([q * q, 0.0, 0.0, 2.0 * amplitude * q], dtype=float)
    else:
        return float("nan"), float("nan")
    return (
        _delta_standard_error(position_gradient, covariance),
        _delta_standard_error(intensity_gradient, covariance),
    )


def _fano_derived_rows(
    component_index: int,
    model_name: str,
    parameters: np.ndarray,
    covariance: np.ndarray,
) -> list[dict[str, Any]]:
    """Return labelled Fano quantities without conflating resonance and apex."""
    amplitude, _center, gamma, q = (float(value) for value in parameters)
    values = _fano_profile_values(parameters)
    gradients = {
        "natural_linewidth": np.array([0.0, 0.0, 2.0, 0.0]),
        "fano_peak_position": (
            np.array([0.0, 1.0, 1.0 / q, -gamma / (q * q)])
            if abs(q) > np.sqrt(np.finfo(float).eps) else None
        ),
        "fano_dip_position": np.array([0.0, 1.0, -q, -gamma]),
        "fano_peak_contrast": np.array([q * q, 0.0, 0.0, 2.0 * amplitude * q]),
        "fano_dip_contrast": np.array([-1.0, 0.0, 0.0, 0.0]),
    }
    entries = (
        ("natural_linewidth", "width", values["natural_linewidth"]),
        ("fano_peak_position", "peak_position", values["peak_position"]),
        ("fano_dip_position", "dip_position", values["dip_position"]),
        ("fano_peak_contrast", "peak_contrast", values["peak_contrast"]),
        ("fano_dip_contrast", "dip_contrast", values["dip_contrast"]),
    )
    rows: list[dict[str, Any]] = []
    for parameter_name, role, value in entries:
        gradient = gradients[parameter_name]
        rows.append({
            "component": f"peak_{component_index}",
            "component_index": component_index,
            "model": model_name,
            "parameter": parameter_name,
            "role": role,
            "value": value,
            "standard_error": (
                _delta_standard_error(gradient, covariance)
                if gradient is not None else float("nan")
            ),
            "fixed": False,
            "lower_bound": float("nan"),
            "upper_bound": float("nan"),
        })
    return rows


def _validate_fit_parameters(settings: CompositeFitParameters) -> None:
    if settings.data_mode not in {"corrected", "raw"}:
        raise MathOperationError("Composite data mode must be corrected or raw.")
    if settings.data_mode == "corrected" and settings.baseline_model != "zero":
        raise MathOperationError("Corrected-data fitting requires a fixed zero baseline.")
    if settings.baseline_model not in {"zero", "constant", "linear", "quadratic"}:
        raise MathOperationError("Shared baseline must be zero, constant, linear, or quadratic.")
    if settings.loss not in {"linear", "soft_l1", "huber"}:
        raise MathOperationError("Composite fit loss must be linear, soft_l1, or Huber.")


def _baseline_settings(
    settings: CompositeFitParameters,
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[list[str], list[float], list[float], list[float]]:
    if settings.baseline_model == "zero":
        return [], [], [], []
    edge_count = max(1, min(10, len(y) // 10))
    edge_x = np.concatenate((x[:edge_count], x[-edge_count:]))
    edge_y = np.concatenate((y[:edge_count], y[-edge_count:]))
    degree = {"constant": 0, "linear": 1, "quadratic": 2}[settings.baseline_model]
    coefficients = np.polyfit(edge_x, edge_y, degree)
    names = {0: ["offset"], 1: ["slope", "offset"], 2: ["quadratic", "slope", "offset"]}[degree]
    return names, coefficients.tolist(), [-np.inf] * len(names), [np.inf] * len(names)


def _evaluate_baseline(
    settings: CompositeFitParameters,
    x: np.ndarray,
    parameters: np.ndarray,
) -> np.ndarray:
    if settings.baseline_model == "zero":
        return np.zeros_like(x)
    return np.polyval(parameters, x)


def _numeric_bounds(
    values: tuple[float | None, ...],
    count: int,
    fallback: float,
) -> tuple[float, ...]:
    if not values:
        return (fallback,) * count
    if len(values) != count:
        raise MathOperationError("Composite component bounds do not match its parameters.")
    return tuple(fallback if value is None else float(value) for value in values)


def _covariance_from_solution(
    solution: optimize.OptimizeResult,
    point_count: int,
    free_count: int,
    total_count: int,
    free_indices: np.ndarray,
    rss: float,
) -> tuple[np.ndarray, np.ndarray, str]:
    covariance = np.full((total_count, total_count), np.nan, dtype=float)
    errors = np.full(total_count, np.nan, dtype=float)
    if free_count == 0 or point_count <= free_count:
        return covariance, errors, "Parameter uncertainty is unavailable for this fit."
    try:
        free_covariance = np.linalg.pinv(solution.jac.T @ solution.jac) * (
            rss / (point_count - free_count)
        )
        covariance[np.ix_(free_indices, free_indices)] = free_covariance
        errors[free_indices] = np.sqrt(np.maximum(np.diag(free_covariance), 0.0))
        return covariance, errors, ""
    except np.linalg.LinAlgError:
        return covariance, errors, "The parameter covariance matrix is singular."


def _first_role_error(rows: list[dict[str, Any]], role: str) -> float:
    for row in rows:
        if row["role"] == role:
            return float(row["standard_error"])
    return float("nan")


def _named_parameter_error(rows: list[dict[str, Any]], parameter: str) -> float:
    for row in rows:
        if row["parameter"] == parameter:
            return float(row["standard_error"])
    return float("nan")


def _component_profile_metrics(
    x_values: np.ndarray,
    component_values: np.ndarray,
    polarity: str,
) -> tuple[float, float, float, float]:
    """Return apex position, signed intensity, numerical FWHM, and asymmetry."""
    x = np.asarray(x_values, dtype=float)
    values = np.asarray(component_values, dtype=float)
    finite = np.isfinite(x) & np.isfinite(values)
    if np.count_nonzero(finite) < 3:
        return (float("nan"),) * 4
    x = x[finite]
    values = values[finite]
    order = np.argsort(x, kind="stable")
    x = x[order]
    values = values[order]
    apex_index = int(np.argmin(values) if polarity == "negative" else np.argmax(values))
    intensity = float(values[apex_index])
    half_height = abs(intensity) / 2.0
    if not np.isfinite(half_height) or half_height <= np.finfo(float).eps:
        return float(x[apex_index]), intensity, float("nan"), float("nan")
    magnitude = np.abs(values)
    left_index = apex_index
    while left_index > 0 and magnitude[left_index - 1] >= half_height:
        left_index -= 1
    right_index = apex_index
    while right_index < len(x) - 1 and magnitude[right_index + 1] >= half_height:
        right_index += 1
    if left_index == 0 or right_index == len(x) - 1:
        return float(x[apex_index]), intensity, float("nan"), float("nan")
    left_boundary = _interpolated_level_crossing(
        x[left_index - 1], magnitude[left_index - 1],
        x[left_index], magnitude[left_index], half_height,
    )
    right_boundary = _interpolated_level_crossing(
        x[right_index], magnitude[right_index],
        x[right_index + 1], magnitude[right_index + 1], half_height,
    )
    center = float(x[apex_index])
    left_width = max(0.0, center - left_boundary)
    right_width = max(0.0, right_boundary - center)
    fwhm = left_width + right_width
    asymmetry = (
        (right_width - left_width) / fwhm
        if fwhm > np.finfo(float).eps
        else float("nan")
    )
    return center, intensity, float(fwhm), float(asymmetry)


def _interpolated_level_crossing(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    level: float,
) -> float:
    if y1 == y0:
        return float((x0 + x1) / 2.0)
    fraction = np.clip((level - y0) / (y1 - y0), 0.0, 1.0)
    return float(x0 + fraction * (x1 - x0))
