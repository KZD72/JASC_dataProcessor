"""Shared numerical/audit summary builders for GUI operations and API replay."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
import numpy as np
import pandas as pd
from core.workspace import Dataset
from math_engine.curve_fitting import FIT_METHODS, FitResult
from math_engine.smoothing import SMOOTHING_METHODS
from math_engine.calculus import WINDOW_METHODS
from math_engine.interpolation import INTERPOLATION_METHODS
from math_engine.statistics import STATISTIC_OPERATIONS

if TYPE_CHECKING:
    from ui.dialogs import FitDialog, InterpolationDialog

BATCH_COLUMN_BINDING_NAME = "name"
BATCH_COLUMN_BINDING_POSITION = "position"


class OperationSummaries:
    @staticmethod
    def _batch_column_binding_label(binding_mode: str) -> str:
        """Return a readable label for a batch column binding mode."""
        if binding_mode == BATCH_COLUMN_BINDING_POSITION:
            return "column_position"
        return "exact_column_name"

    def _formula_batch_summary_row(
        self,
        result_target_column: str,
        updated_rows: int,
        status: str,
        error: str,
        dataset: Dataset | None = None,
        dataset_name: str = "",
        requested_target_column: str = "",
        output_action: str = "",
        target_existed_before: bool = False,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
        execution_mode: str = "",
        elapsed_seconds: float = 0.0,
    ) -> dict[str, object]:
        """Return one formula batch summary row."""
        source_sheet = dataset.name if dataset is not None else dataset_name
        row: dict[str, object] = {
            "source_sheet": source_sheet,
            "requested_target_column": requested_target_column or result_target_column,
            "target_column": result_target_column,
            "output_action": output_action,
            "target_existed_before": target_existed_before,
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "updated_rows": updated_rows,
            "status": status,
            "error": error,
            "execution_mode": execution_mode,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
            "row_count": len(dataset.frame) if dataset is not None else 0,
            "finite_count": np.nan,
            "missing_or_non_numeric": np.nan,
            "minimum": np.nan,
            "maximum": np.nan,
            "mean": np.nan,
        }
        if dataset is None or result_target_column not in dataset.frame.columns:
            return row

        values = pd.to_numeric(dataset.frame[result_target_column], errors="coerce")
        values = values.replace([np.inf, -np.inf], np.nan)
        finite_values = values.dropna()
        row["finite_count"] = int(len(finite_values))
        row["missing_or_non_numeric"] = int(len(values) - len(finite_values))
        if not finite_values.empty:
            row["minimum"] = float(finite_values.min())
            row["maximum"] = float(finite_values.max())
            row["mean"] = float(finite_values.mean())
        return row

    @staticmethod
    def _smoothing_summary_row(
        plan_row: dict[str, object],
        method: str,
        result_column: str,
        values_written: int,
        status: str,
        error: str,
        elapsed_seconds: float,
    ) -> dict[str, object]:
        """Return one tidy smoothing batch result row."""
        return {
            "source_sheet": plan_row["source_sheet"],
            "requested_x_column": plan_row["requested_x_column"],
            "requested_y_column": plan_row["requested_y_column"],
            "x_column": plan_row["x_column"],
            "y_column": plan_row["y_column"],
            "method": method,
            "method_label": SMOOTHING_METHODS.get(method, method),
            "requested_target_column": plan_row["requested_target_column"],
            "target_column": result_column,
            "output_action": plan_row["output_action"],
            "values_written": values_written,
            "status": status,
            "error": error,
            "elapsed_seconds": elapsed_seconds,
        }

    def _column_math_batch_summary_row(
        self,
        operation_title: str,
        x_column: str,
        y_column: str,
        method: str,
        method_label: str,
        initial_value: float | None,
        result_column: str,
        values_written: int,
        status: str,
        error: str,
        dataset: Dataset | None = None,
        dataset_name: str = "",
        requested_x_column: str = "",
        requested_y_column: str = "",
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
        requested_target_column: str = "",
        output_action: str = "",
        target_existed_before: bool = False,
        elapsed_seconds: float = 0.0,
    ) -> dict[str, object]:
        """Return one derivative/integral batch summary row."""
        source_sheet = dataset.name if dataset is not None else dataset_name
        row: dict[str, object] = {
            "source_sheet": source_sheet,
            "operation": operation_title,
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_x_column": requested_x_column or x_column,
            "requested_y_column": requested_y_column or y_column,
            "x_column": x_column,
            "y_column": y_column,
            "method": method,
            "method_label": method_label,
            "initial_value": np.nan if initial_value is None else initial_value,
            "requested_target_column": requested_target_column or result_column,
            "target_column": result_column,
            "output_action": output_action,
            "target_existed_before": target_existed_before,
            "values_written": values_written,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
            "row_count": len(dataset.frame) if dataset is not None else 0,
            "finite_count": np.nan,
            "missing_or_non_numeric": np.nan,
            "minimum": np.nan,
            "maximum": np.nan,
            "mean": np.nan,
        }
        if dataset is None or result_column not in dataset.frame.columns:
            return row

        values = pd.to_numeric(dataset.frame[result_column], errors="coerce")
        values = values.replace([np.inf, -np.inf], np.nan)
        finite_values = values.dropna()
        row["finite_count"] = int(len(finite_values))
        row["missing_or_non_numeric"] = int(len(values) - len(finite_values))
        if not finite_values.empty:
            row["minimum"] = float(finite_values.min())
            row["maximum"] = float(finite_values.max())
            row["mean"] = float(finite_values.mean())
        return row

    @staticmethod
    def _interpolation_prediction_column(value_column: str) -> str:
        """Return the generated interpolation prediction column name."""
        return f"{value_column}_interpolated"

    def _interpolation_batch_summary_row(
        self,
        dialog: InterpolationDialog,
        requested_result_sheet: str,
        output_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        coordinate_columns: list[str] | None = None,
        value_column: str = "",
        query_columns: list[str] | None = None,
        requested_coordinate_columns: list[str] | None = None,
        requested_value_column: str = "",
        requested_query_columns: list[str] | None = None,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        result_frame: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        """Return one interpolation batch summary row."""
        resolved_value_column = value_column or requested_value_column or dialog.value_column()
        resolved_coordinate_columns = coordinate_columns or dialog.coordinate_columns()
        resolved_query_columns = query_columns or []
        requested_coordinates = requested_coordinate_columns or resolved_coordinate_columns
        requested_queries = requested_query_columns or resolved_query_columns
        prediction_column = self._interpolation_prediction_column(resolved_value_column)
        metrics = self._interpolation_result_metrics(
            source_dataset=source_dataset,
            result_frame=result_frame,
            prediction_column=prediction_column,
        )
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": "Interpolation",
            "mode": dialog.mode(),
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_coordinate_columns": ", ".join(requested_coordinates),
            "coordinate_columns": ", ".join(resolved_coordinate_columns),
            "requested_value_column": requested_value_column or resolved_value_column,
            "value_column": resolved_value_column,
            "query_mode": dialog.query_mode(),
            "requested_query_columns": (
                ", ".join(requested_queries) if dialog.query_mode() == "columns" else ""
            ),
            "query_columns": (
                ", ".join(resolved_query_columns) if dialog.query_mode() == "columns" else ""
            ),
            "method": dialog.method_key(),
            "method_label": self._interpolation_method_label(dialog.mode(), dialog.method_key()),
            "fill_policy": dialog.fill_policy(),
            "smoothing": dialog.smoothing(),
            "epsilon": np.nan if dialog.epsilon() is None else dialog.epsilon(),
            "requested_result_sheet": requested_result_sheet,
            "output_sheet": output_sheet,
            "prediction_column": prediction_column,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
        }
        row.update(metrics)
        return row

    @staticmethod
    def _interpolation_method_label(mode: str, method_key: str) -> str:
        """Return a display label for an interpolation method."""
        method = INTERPOLATION_METHODS.get(mode, {}).get(method_key)
        return method.label if method is not None else method_key

    @staticmethod
    def _interpolation_result_metrics(
        source_dataset: Dataset | None,
        result_frame: pd.DataFrame | None,
        prediction_column: str,
    ) -> dict[str, object]:
        """Return quality metrics for one interpolation result."""
        metrics: dict[str, object] = {
            "source_row_count": len(source_dataset.frame) if source_dataset is not None else 0,
            "query_count": len(result_frame) if result_frame is not None else 0,
            "finite_prediction_count": np.nan,
            "missing_prediction_count": np.nan,
            "prediction_minimum": np.nan,
            "prediction_maximum": np.nan,
            "prediction_mean": np.nan,
        }
        if result_frame is None or prediction_column not in result_frame.columns:
            return metrics

        predictions = pd.to_numeric(result_frame[prediction_column], errors="coerce")
        predictions = predictions.replace([np.inf, -np.inf], np.nan)
        finite_predictions = predictions.dropna()
        metrics["finite_prediction_count"] = int(len(finite_predictions))
        metrics["missing_prediction_count"] = int(len(predictions) - len(finite_predictions))
        if not finite_predictions.empty:
            metrics["prediction_minimum"] = float(finite_predictions.min())
            metrics["prediction_maximum"] = float(finite_predictions.max())
            metrics["prediction_mean"] = float(finite_predictions.mean())
        return metrics

    def _fft_batch_summary_row(
        self,
        operation: str,
        signal_column: str,
        x_column: str | None,
        window_method: str,
        requested_result_sheet: str,
        output_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        requested_signal_column: str = "",
        requested_x_column: str | None = None,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        result_frame: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        """Return one FFT batch summary row."""
        metrics = self._fft_result_metrics(source_dataset, result_frame, signal_column, x_column)
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": operation,
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_signal_column": requested_signal_column or signal_column,
            "signal_column": signal_column,
            "requested_x_column": requested_x_column or "sample index",
            "x_column": x_column or "sample index",
            "window": window_method,
            "window_label": WINDOW_METHODS.get(window_method, window_method),
            "requested_result_sheet": requested_result_sheet,
            "output_sheet": output_sheet,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
        }
        row.update(metrics)
        return row

    @staticmethod
    def _fft_result_metrics(
        source_dataset: Dataset | None,
        result_frame: pd.DataFrame | None,
        signal_column: str,
        x_column: str | None,
    ) -> dict[str, object]:
        """Return quality metrics for one FFT result."""
        metrics: dict[str, object] = {
            "source_row_count": len(source_dataset.frame) if source_dataset is not None else 0,
            "sample_count": len(result_frame) if result_frame is not None else 0,
            "sample_spacing": np.nan,
            "dominant_frequency": np.nan,
            "dominant_amplitude": np.nan,
            "total_spectral_power": np.nan,
        }
        if source_dataset is not None:
            metrics["sample_spacing"] = OperationSummaries._estimate_fft_sample_spacing(
                source_dataset,
                signal_column,
                x_column,
            )
        if result_frame is None or result_frame.empty or "magnitude" not in result_frame:
            return metrics

        magnitudes = pd.to_numeric(result_frame["magnitude"], errors="coerce")
        magnitudes = magnitudes.replace([np.inf, -np.inf], np.nan).dropna()
        if magnitudes.empty:
            return metrics

        dominant_index = magnitudes.idxmax()
        metrics["dominant_amplitude"] = float(magnitudes.loc[dominant_index])
        if "frequency" in result_frame:
            frequency = pd.to_numeric(result_frame.loc[[dominant_index], "frequency"], errors="coerce")
            if not frequency.empty and pd.notna(frequency.iloc[0]):
                metrics["dominant_frequency"] = float(frequency.iloc[0])
        metrics["total_spectral_power"] = float(np.square(magnitudes.to_numpy(dtype=float)).sum())
        return metrics

    @staticmethod
    def _estimate_fft_sample_spacing(
        source_dataset: Dataset,
        signal_column: str,
        x_column: str | None,
    ) -> float:
        """Estimate sample spacing for the FFT batch summary."""
        if not x_column:
            return 1.0
        if x_column not in source_dataset.frame.columns or signal_column not in source_dataset.frame.columns:
            return float("nan")
        x_values = pd.to_numeric(source_dataset.frame[x_column], errors="coerce")
        y_values = pd.to_numeric(source_dataset.frame[signal_column], errors="coerce")
        aligned = pd.DataFrame({"x": x_values, "y": y_values}).dropna()
        if len(aligned) < 2:
            return float("nan")
        spacing = np.diff(aligned["x"].to_numpy(dtype=float))
        if len(spacing) == 0:
            return float("nan")
        return float(np.median(np.abs(spacing)))

    def _ifft_batch_summary_row(
        self,
        real_column: str,
        imaginary_column: str | None,
        requested_result_sheet: str,
        output_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        requested_real_column: str = "",
        requested_imaginary_column: str | None = None,
        column_binding_mode: str = BATCH_COLUMN_BINDING_NAME,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        result_frame: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        """Return one inverse FFT batch summary row."""
        metrics = self._ifft_result_metrics(source_dataset, result_frame)
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": "Inverse FFT",
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_real_column": requested_real_column or real_column,
            "real_column": real_column,
            "requested_imaginary_column": requested_imaginary_column or "0",
            "imaginary_column": imaginary_column or "0",
            "requested_result_sheet": requested_result_sheet,
            "output_sheet": output_sheet,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
        }
        row.update(metrics)
        return row

    @staticmethod
    def _ifft_result_metrics(
        source_dataset: Dataset | None,
        result_frame: pd.DataFrame | None,
    ) -> dict[str, object]:
        """Return quality metrics for one inverse FFT result."""
        metrics: dict[str, object] = {
            "source_row_count": len(source_dataset.frame) if source_dataset is not None else 0,
            "reconstruction_count": len(result_frame) if result_frame is not None else 0,
            "finite_real_count": np.nan,
            "real_minimum": np.nan,
            "real_maximum": np.nan,
            "real_mean": np.nan,
            "maximum_magnitude": np.nan,
            "reconstructed_power": np.nan,
        }
        if result_frame is None or result_frame.empty:
            return metrics

        if "real" in result_frame:
            real_values = pd.to_numeric(result_frame["real"], errors="coerce")
            real_values = real_values.replace([np.inf, -np.inf], np.nan).dropna()
            metrics["finite_real_count"] = int(len(real_values))
            if not real_values.empty:
                real_array = real_values.to_numpy(dtype=float)
                metrics["real_minimum"] = float(real_values.min())
                metrics["real_maximum"] = float(real_values.max())
                metrics["real_mean"] = float(real_values.mean())
                metrics["reconstructed_power"] = float(np.square(real_array).sum())

        if "magnitude" in result_frame:
            magnitudes = pd.to_numeric(result_frame["magnitude"], errors="coerce")
            magnitudes = magnitudes.replace([np.inf, -np.inf], np.nan).dropna()
            if not magnitudes.empty:
                metrics["maximum_magnitude"] = float(magnitudes.max())
        return metrics

    def _statistics_batch_result_rows(
        self,
        operation_key: str,
        operation_scope: str,
        column_binding_mode: str,
        source_sheet: str,
        secondary_sheet: str,
        requested_result_sheet: str,
        output_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        result_frame: pd.DataFrame | None = None,
        requested_primary_column: str = "",
        primary_column: str = "",
        requested_secondary_column: str = "",
        secondary_column: str = "",
        requested_columns: list[str] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Return annotated cumulative statistics rows for one batch job."""
        operation = STATISTIC_OPERATIONS[operation_key]
        base: dict[str, object] = {
            "source_sheet": source_sheet,
            "secondary_sheet": secondary_sheet,
            "operation_key": operation_key,
            "operation_label": operation.label,
            "operation_scope": operation_scope,
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_primary_column": requested_primary_column,
            "primary_column": primary_column,
            "requested_secondary_column": requested_secondary_column,
            "secondary_column": secondary_column,
            "requested_columns": ", ".join(requested_columns or []),
            "columns": ", ".join(columns or []),
            "requested_result_sheet": requested_result_sheet,
            "output_sheet": output_sheet,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
        }
        if result_frame is None or result_frame.empty:
            row = dict(base)
            row["result_row"] = np.nan
            return [row]

        if operation_key in {"single_zscore", "single_cumulative"}:
            row = dict(base)
            row.update(self._statistics_rowwise_result_metrics(result_frame))
            return [row]

        rows: list[dict[str, object]] = []
        for result_index, result_row in result_frame.reset_index(drop=True).iterrows():
            row = dict(base)
            row["result_row"] = int(result_index)
            for column_name, value in result_row.items():
                clean_name = str(column_name)
                if clean_name in row:
                    clean_name = f"result_{clean_name}"
                row[clean_name] = value
            rows.append(row)
        return rows

    @staticmethod
    def _statistics_rowwise_result_metrics(result_frame: pd.DataFrame) -> dict[str, object]:
        """Return compact batch-summary metrics for row-wise statistics outputs."""
        metrics: dict[str, object] = {
            "result_row": "compact",
            "result_row_count": len(result_frame),
        }
        for column_name in [
            "value",
            "z_score",
            "cumulative_count",
            "cumulative_sum",
            "cumulative_mean",
            "cumulative_std",
            "cumulative_min",
            "cumulative_max",
        ]:
            if column_name not in result_frame:
                continue
            values = pd.to_numeric(result_frame[column_name], errors="coerce")
            values = values.replace([np.inf, -np.inf], np.nan).dropna()
            metrics[f"{column_name}_finite_count"] = int(len(values))
            if values.empty:
                continue
            metrics[f"{column_name}_first"] = float(values.iloc[0])
            metrics[f"{column_name}_last"] = float(values.iloc[-1])
            metrics[f"{column_name}_minimum"] = float(values.min())
            metrics[f"{column_name}_maximum"] = float(values.max())
            metrics[f"{column_name}_mean"] = float(values.mean())
        if "z_score" in result_frame:
            z_values = pd.to_numeric(result_frame["z_score"], errors="coerce")
            z_values = z_values.replace([np.inf, -np.inf], np.nan).dropna()
            metrics["absolute_z_gt_3_count"] = int((np.abs(z_values) > 3).sum())
        return metrics

    def _fit_batch_summary_row(
        self,
        requested_x_column: str,
        x_column: str | None,
        requested_y_column: str,
        y_column: str | None,
        requested_x_weight_column: str | None,
        x_weight_column: str | None,
        requested_weight_column: str | None,
        weight_column: str | None,
        column_binding_mode: str,
        requested_fit_sheet: str,
        output_fit_sheet: str,
        requested_residual_sheet: str,
        output_residual_sheet: str,
        status: str,
        error: str,
        elapsed_seconds: float,
        result: FitResult | None = None,
        source_dataset: Dataset | None = None,
        source_sheet: str = "",
        dialog: FitDialog | None = None,
    ) -> dict[str, object]:
        """Return one curve-fit batch summary row."""
        report = result.report if result is not None else None
        method_key = report.method if report is not None else (dialog.method() if dialog is not None else "")
        model_key = report.model_key if report is not None else (dialog.model_key() if dialog is not None else "")
        row: dict[str, object] = {
            "source_sheet": source_dataset.name if source_dataset is not None else source_sheet,
            "operation": "Curve Fit",
            "column_binding": self._batch_column_binding_label(column_binding_mode),
            "requested_x_column": requested_x_column,
            "x_column": x_column or "",
            "requested_y_column": requested_y_column,
            "y_column": y_column or "",
            "requested_x_weight_column": requested_x_weight_column or "",
            "x_weight_column": x_weight_column or "",
            "requested_y_weight_column": requested_weight_column or "",
            "y_weight_column": weight_column or "",
            "weight_mode": report.weight_mode if report is not None else (dialog.weight_mode() if dialog else ""),
            "absolute_sigma": report.absolute_sigma if report is not None else (dialog.absolute_sigma() if dialog else False),
            "model_key": model_key,
            "model_name": report.model_name if report is not None else model_key,
            "method": method_key,
            "method_label": FIT_METHODS.get(method_key, method_key),
            "fit_points": dialog.fit_points() if dialog is not None else (len(result.fit_frame) if result is not None else 0),
            "confidence_level": (
                report.confidence_level
                if report is not None
                else (dialog.confidence_level() if dialog is not None and dialog.include_confidence_band() else 0.0)
            ),
            "requested_fit_sheet": requested_fit_sheet,
            "output_fit_sheet": output_fit_sheet,
            "requested_residual_sheet": requested_residual_sheet,
            "output_residual_sheet": output_residual_sheet,
            "status": status,
            "error": error,
            "elapsed_seconds": round(float(elapsed_seconds), 6),
            "point_count": report.point_count if report is not None else 0,
            "r_squared": report.r_squared if report is not None else np.nan,
            "adjusted_r_squared": report.adjusted_r_squared if report is not None else np.nan,
            "rmse": report.rmse if report is not None else np.nan,
            "mae": report.mae if report is not None else np.nan,
            "residual_mean": report.residual_mean if report is not None else np.nan,
            "residual_std": report.residual_std if report is not None else np.nan,
            "covariance_available": False,
            "warnings": "",
        }
        if report is None:
            return row

        covariance = np.asarray(report.covariance, dtype=float)
        row["covariance_available"] = bool(covariance.size and np.isfinite(covariance).any())
        row["warnings"] = "; ".join(report.warnings)
        for name, value, standard_error, lower, upper, fixed in zip(
            report.parameter_names,
            report.parameters,
            report.standard_errors,
            report.lower_bounds,
            report.upper_bounds,
            report.fixed_parameters,
        ):
            key = self._fit_summary_key(name)
            row[f"param_{key}"] = value
            row[f"stderr_{key}"] = standard_error
            row[f"lower_{key}"] = lower
            row[f"upper_{key}"] = upper
            row[f"fixed_{key}"] = fixed
        return row

    def _fit_parameter_correlation_rows(
        self,
        source_dataset: Dataset,
        result: FitResult,
        requested_x_column: str,
        x_column: str,
        requested_y_column: str,
        y_column: str,
        column_binding_mode: str,
        output_fit_sheet: str,
    ) -> list[dict[str, object]]:
        """Return long-format covariance/correlation rows for one fit report."""
        report = result.report
        parameter_names = list(report.parameter_names)
        covariance = np.asarray(report.covariance, dtype=float)
        if covariance.shape != (len(parameter_names), len(parameter_names)):
            return []
        if not np.isfinite(covariance).any():
            return []

        variances = np.diag(covariance)
        rows: list[dict[str, object]] = []
        for first_index, first_name in enumerate(parameter_names):
            for second_index in range(first_index, len(parameter_names)):
                second_name = parameter_names[second_index]
                covariance_value = float(covariance[first_index, second_index])
                first_variance = float(variances[first_index])
                second_variance = float(variances[second_index])
                correlation = np.nan
                if (
                    np.isfinite(covariance_value)
                    and np.isfinite(first_variance)
                    and np.isfinite(second_variance)
                    and first_variance > 0
                    and second_variance > 0
                ):
                    correlation = float(covariance_value / np.sqrt(first_variance * second_variance))

                rows.append(
                    {
                        "source_sheet": source_dataset.name,
                        "output_fit_sheet": output_fit_sheet,
                        "model_key": report.model_key,
                        "model_name": report.model_name,
                        "method": report.method,
                        "method_label": FIT_METHODS.get(report.method, report.method),
                        "column_binding": self._batch_column_binding_label(column_binding_mode),
                        "requested_x_column": requested_x_column,
                        "x_column": x_column,
                        "requested_y_column": requested_y_column,
                        "y_column": y_column,
                        "parameter_1": first_name,
                        "parameter_2": second_name,
                        "parameter_1_index": first_index,
                        "parameter_2_index": second_index,
                        "pair_type": "variance" if first_index == second_index else "cross",
                        "covariance": covariance_value,
                        "correlation": correlation,
                    }
                )
        return rows

    @staticmethod
    def _fit_summary_key(parameter_name: str) -> str:
        """Return a stable summary-column suffix for a fit parameter."""
        clean = re.sub(r"\W+", "_", str(parameter_name).strip()).strip("_")
        return clean or "parameter"
