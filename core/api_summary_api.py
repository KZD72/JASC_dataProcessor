"""Recalculate batch tables from recorded result dependencies."""
from __future__ import annotations

from types import SimpleNamespace
import json
import pandas as pd

from core.api_summaries import OperationSummaries
from core.workspace import Dataset, Workspace, set_dataset_operation_comments


SUMMARY_METHODS = {
    "formula": "_formula_batch_summary_row", "smooth": "_smoothing_summary_row",
    "calculus": "_column_math_batch_summary_row", "interpolation": "_interpolation_batch_summary_row",
    "fft": "_fft_batch_summary_row", "ifft": "_ifft_batch_summary_row",
    "statistics": "_statistics_batch_result_rows", "fit": "_fit_batch_summary_row",
    "correlations": "_fit_parameter_correlation_rows",
}
DIALOG_GETTERS = {
    "fit": ("absolute_sigma", "confidence_level", "fit_points", "include_confidence_band", "method", "model_key", "weight_mode"),
    "interpolation": ("coordinate_columns", "epsilon", "fill_policy", "method_key", "mode", "query_mode", "smoothing", "value_column"),
}


def wide_statistics(frame: pd.DataFrame) -> pd.DataFrame:
    """Pivot the same metric and p-value columns used by the Statistics dialog."""
    metrics = frame[(frame["status"] == "ok") & frame["metric"].notna() & (frame["metric"].astype(str) != "")]
    columns = [key for key in ("source_sheet", "primary_column", "secondary_sheet", "secondary_column", "columns", "operation_key", "operation_label") if key in metrics]
    result = metrics.groupby(columns+["metric"], dropna=False)["value"].first().unstack("metric").reset_index()
    if "p_value" in metrics:
        p = metrics.groupby(columns+["metric"], dropna=False)["p_value"].first().unstack("metric").add_suffix("_p_value").reset_index()
        result = result.merge(p, on=columns, how="left")
    return result


class SummaryApi:
    workspace: Workspace

    def result_row(self, kind: str, **parameters: object) -> dict | list[dict]:
        """Compute a summary while its source and result are at the recorded step."""
        dialog = parameters.get("dialog")
        if isinstance(dialog, dict):
            parameters["dialog"] = SimpleNamespace(**{key: (lambda value=value: value) for key, value in dialog.items()})
        # Timings describe the original GUI run, not replay execution.
        if "elapsed_seconds" in parameters:
            parameters["elapsed_seconds"] = 0.0
        if kind == "fit_report":
            return fit_report_row(**parameters)
        return getattr(OperationSummaries(), SUMMARY_METHODS[kind])(**parameters)

    def collect_rows(self, *, name: str, rows: list[dict | list[dict]], wide: bool = False,
                     operation: str = "Batch summary") -> Dataset:
        flattened = [row for group in rows for row in (group if isinstance(group, list) else [group])]
        frame = pd.DataFrame(flattened)
        if wide:
            frame = wide_statistics(frame)
        output = self.workspace.add_dataset(name, frame, copy_frame=False)
        if operation:
            set_dataset_operation_comments(output, operation)
        return output


def fit_report_row(source_sheet: str, requested_y_column: str, y_column: str,
                   output_fit_sheet: str, result: object) -> dict:
    """Retain readable text, numeric parameters and uncertainty provenance per fit."""
    report = result.report
    row = {"source_sheet": source_sheet, "requested_y_column": requested_y_column,
            "y_column": y_column, "output_fit_sheet": output_fit_sheet,
            "model_name": report.model_name, "method": report.method,
            "r_squared": report.r_squared, "rmse": report.rmse, "report_text": report.to_text()}
    for field in ("model_key", "equation", "x_column", "point_count", "adjusted_r_squared", "mae",
                  "residual_mean", "residual_std", "confidence_level", "x_weight_column", "weight_column",
                  "weight_mode", "absolute_sigma", "negative_log_likelihood"):
        row[field] = getattr(report, field)
    row["x_percentile_bounds"] = json.dumps(report.x_bounds, sort_keys=True) if report.x_bounds else ""
    row["y_percentile_bounds"] = json.dumps(report.y_bounds, sort_keys=True) if report.y_bounds else ""
    row["warnings"] = " | ".join(report.warnings)
    for index, name in enumerate(report.parameter_names):
        row[f"param_{name}"] = report.parameters[index]
        row[f"stderr_{name}"] = report.standard_errors[index]
        row[f"lower_{name}"] = report.lower_bounds[index]
        row[f"upper_{name}"] = report.upper_bounds[index]
        row[f"fixed_{name}"] = report.fixed_parameters[index]
    return row
