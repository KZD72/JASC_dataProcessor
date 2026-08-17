"""Reusable data-preparation helpers for workspace datasets."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


class DataPrepError(ValueError):
    """Raised when a data-preparation operation cannot be applied."""


@dataclass(frozen=True, slots=True)
class FilterCondition:
    """One simple filter/query condition."""

    column: str
    operator: str
    value: str = ""
    value2: str = ""


FILTER_OPERATORS: dict[str, str] = {
    "eq": "equals",
    "ne": "does not equal",
    "gt": ">",
    "ge": ">=",
    "lt": "<",
    "le": "<=",
    "between": "is between",
    "contains": "contains",
    "starts": "starts with",
    "in": "is in list",
    "blank": "is blank",
    "not_blank": "is not blank",
}


def apply_filter_condition(frame: pd.DataFrame, condition: FilterCondition) -> pd.DataFrame:
    """Return a filtered DataFrame using one condition."""
    if condition.column not in frame.columns:
        raise DataPrepError(f"Column '{condition.column}' does not exist.")
    if condition.operator not in FILTER_OPERATORS:
        raise DataPrepError(f"Unknown filter operator: {condition.operator}")

    mask = _condition_mask(frame[condition.column], condition)
    return _reset_copy(frame.loc[mask])


def sort_dataframe(frame: pd.DataFrame, columns: list[str], ascending: bool = True) -> pd.DataFrame:
    """Return a sorted DataFrame."""
    clean_columns = _existing_columns(frame, columns, "sort")
    if not clean_columns:
        raise DataPrepError("Choose at least one sort column.")
    return _reset_copy(frame.sort_values(by=clean_columns, ascending=ascending, kind="mergesort"))


def remove_duplicate_rows(
    frame: pd.DataFrame,
    columns: list[str],
    keep: str = "first",
) -> pd.DataFrame:
    """Return rows remaining after duplicate detection on selected columns."""
    clean_columns = _existing_columns(frame, columns, "duplicate-match")
    if not clean_columns:
        raise DataPrepError("Choose at least one column for duplicate detection.")
    if keep not in {"first", "last", "none"}:
        raise DataPrepError(f"Unknown duplicate keep policy: {keep}")
    pandas_keep: str | bool = False if keep == "none" else keep
    duplicate_mask = frame.duplicated(subset=clean_columns, keep=pandas_keep)
    return _reset_copy(frame.loc[~duplicate_mask])


def clean_missing_values(
    frame: pd.DataFrame,
    columns: list[str],
    strategy: str,
    fill_value: str = "",
) -> pd.DataFrame:
    """Return a DataFrame with missing values dropped, filled, or interpolated."""
    clean_columns = _existing_columns(frame, columns, "missing-value")
    if not clean_columns:
        raise DataPrepError("Choose at least one column.")

    result = frame.copy()
    if strategy == "drop_rows":
        return _reset_copy(result.dropna(subset=clean_columns))
    if strategy == "fill_value":
        result[clean_columns] = result[clean_columns].fillna(fill_value)
        return result
    if strategy in {"fill_mean", "fill_median", "interpolate"}:
        for column in clean_columns:
            numeric = pd.to_numeric(result[column], errors="coerce")
            if strategy == "fill_mean":
                replacement = numeric.mean()
                result[column] = numeric.fillna(replacement)
            elif strategy == "fill_median":
                replacement = numeric.median()
                result[column] = numeric.fillna(replacement)
            else:
                result[column] = numeric.interpolate(limit_direction="both")
        return result
    raise DataPrepError(f"Unknown missing-value strategy: {strategy}")


def group_aggregate_dataframe(
    frame: pd.DataFrame,
    group_columns: list[str],
    value_columns: list[str],
    aggregations: list[str],
) -> pd.DataFrame:
    """Return grouped aggregate values for selected numeric columns."""
    clean_groups = _existing_columns(frame, group_columns, "group")
    clean_values = _existing_columns(frame, value_columns, "value")
    clean_aggs = [agg for agg in aggregations if agg in {"count", "mean", "std", "sem", "min", "max", "sum"}]
    if not clean_groups:
        raise DataPrepError("Choose at least one group column.")
    if not clean_values:
        raise DataPrepError("Choose at least one value column.")
    overlap = sorted(set(clean_groups) & set(clean_values))
    if overlap:
        raise DataPrepError("Group columns cannot also be value columns: " + ", ".join(overlap))
    if not clean_aggs:
        raise DataPrepError("Choose at least one aggregation.")

    numeric = frame[clean_values].apply(pd.to_numeric, errors="coerce")
    working = pd.concat([frame[clean_groups], numeric], axis=1)
    result = working.groupby(clean_groups, dropna=False)[clean_values].agg(clean_aggs)
    result.columns = [
        f"{column}_{aggregation}"
        for column, aggregation in result.columns.to_flat_index()
    ]
    return result.reset_index()


def merge_join_dataframes(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_key: str,
    right_key: str,
    how: str,
) -> pd.DataFrame:
    """Return a merged DataFrame using selected key columns."""
    if left_key not in left.columns:
        raise DataPrepError(f"Left key column '{left_key}' does not exist.")
    if right_key not in right.columns:
        raise DataPrepError(f"Right key column '{right_key}' does not exist.")
    if how not in {"inner", "left", "right", "outer"}:
        raise DataPrepError(f"Unknown join mode: {how}")
    return left.merge(
        right,
        left_on=left_key,
        right_on=right_key,
        how=how,
        suffixes=("", "_right"),
    )


def reshape_dataframe(
    frame: pd.DataFrame,
    mode: str,
    id_columns: list[str] | None = None,
    value_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Return a reshaped DataFrame."""
    if mode == "transpose":
        result = frame.transpose().reset_index()
        result.rename(columns={"index": "source_column"}, inplace=True)
        return result
    if mode == "melt":
        ids = _existing_columns(frame, id_columns or [], "identifier")
        values = _existing_columns(frame, value_columns or [], "value")
        if not values:
            raise DataPrepError("Choose at least one value column to stack.")
        return frame.melt(
            id_vars=ids,
            value_vars=values,
            var_name="variable",
            value_name="value",
        )
    raise DataPrepError(f"Unknown reshape mode: {mode}")


def bin_dataframe(
    frame: pd.DataFrame,
    bin_column: str,
    value_columns: list[str],
    bin_count: int,
) -> pd.DataFrame:
    """Return binned means and dispersion for selected numeric value columns."""
    if bin_column not in frame.columns:
        raise DataPrepError(f"Bin column '{bin_column}' does not exist.")
    clean_values = _existing_columns(frame, value_columns, "value")
    if not clean_values:
        raise DataPrepError("Choose at least one value column to bin.")
    if bin_count < 1:
        raise DataPrepError("Bin count must be at least 1.")

    numeric_bins = pd.to_numeric(frame[bin_column], errors="coerce")
    finite = numeric_bins.replace([np.inf, -np.inf], np.nan).dropna()
    if finite.empty:
        raise DataPrepError(f"Bin column '{bin_column}' does not contain numeric values.")
    minimum = float(finite.min())
    maximum = float(finite.max())
    if minimum == maximum:
        raise DataPrepError("Binning requires a non-constant numeric bin column.")

    edges = np.linspace(minimum, maximum, int(bin_count) + 1)
    categories = pd.cut(numeric_bins, bins=edges, include_lowest=True, duplicates="drop")
    numeric_values = frame[clean_values].apply(pd.to_numeric, errors="coerce")
    working = pd.concat([pd.Series(categories, name="_bin"), numeric_bins.rename(bin_column), numeric_values], axis=1)
    grouped = working.dropna(subset=["_bin"]).groupby("_bin", observed=False)

    rows: list[dict[str, object]] = []
    for bin_interval, group in grouped:
        row: dict[str, object] = {
            "bin": str(bin_interval),
            "bin_start": float(bin_interval.left),
            "bin_end": float(bin_interval.right),
            "bin_center": float((bin_interval.left + bin_interval.right) / 2.0),
            "count": int(len(group)),
        }
        for column in clean_values:
            values = group[column].dropna()
            row[f"{column}_mean"] = float(values.mean()) if not values.empty else np.nan
            row[f"{column}_std"] = float(values.std(ddof=1)) if len(values) > 1 else np.nan
            row[f"{column}_sem"] = float(values.sem(ddof=1)) if len(values) > 1 else np.nan
            row[f"{column}_min"] = float(values.min()) if not values.empty else np.nan
            row[f"{column}_max"] = float(values.max()) if not values.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _condition_mask(source: pd.Series, condition: FilterCondition) -> pd.Series:
    """Return a boolean mask for one condition."""
    operator = condition.operator
    if operator == "blank":
        return source.isna() | (source.astype(str).str.strip() == "")
    if operator == "not_blank":
        return source.notna() & (source.astype(str).str.strip() != "")

    value = condition.value
    if operator in {"gt", "ge", "lt", "le", "between"}:
        numeric_source = pd.to_numeric(source, errors="coerce")
        first_value = _parse_float(value, "Numeric filter comparisons need a numeric value.")
        if operator == "between":
            second_value = _parse_float(condition.value2, "Range filters need numeric minimum and maximum values.")
            low, high = sorted((first_value, second_value))
            return (numeric_source >= low) & (numeric_source <= high)
        if operator == "gt":
            return numeric_source > first_value
        if operator == "ge":
            return numeric_source >= first_value
        if operator == "lt":
            return numeric_source < first_value
        return numeric_source <= first_value

    text_source = source.where(source.notna(), "").astype(str)
    if operator == "eq":
        return text_source == value
    if operator == "ne":
        return text_source != value
    if operator == "contains":
        return text_source.str.contains(value, case=False, na=False, regex=False)
    if operator == "starts":
        return text_source.str.startswith(value, na=False)
    if operator == "in":
        values = {item.strip() for item in value.split(",") if item.strip()}
        if not values:
            raise DataPrepError("List filters need at least one comma-separated value.")
        return text_source.isin(values)
    raise DataPrepError(f"Unknown filter operator: {operator}")


def _existing_columns(frame: pd.DataFrame, columns: list[str], label: str) -> list[str]:
    """Return existing columns or raise for the first missing entry."""
    clean_columns = [str(column) for column in columns if str(column).strip()]
    missing = [column for column in clean_columns if column not in frame.columns]
    if missing:
        raise DataPrepError(f"Missing {label} column(s): " + ", ".join(missing))
    return clean_columns


def _parse_float(text: str, message: str) -> float:
    """Parse a floating-point value or raise a DataPrepError."""
    try:
        return float(str(text).strip())
    except ValueError as exc:
        raise DataPrepError(message) from exc


def _reset_copy(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with a compact row index."""
    result = frame.copy()
    result.reset_index(drop=True, inplace=True)
    return result
