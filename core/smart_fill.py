"""Predictable spreadsheet-style filling for numeric, date, and list data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence

import numpy as np
import pandas as pd


SMART_FILL_MODE_AUTO = "auto"
SMART_FILL_MODE_NUMERIC = "numeric"
SMART_FILL_MODE_DATETIME = "datetime"
SMART_FILL_MODE_CATEGORY = "category"
SMART_FILL_MODE_CUSTOM = "custom"
SMART_FILL_MODES = (
    SMART_FILL_MODE_AUTO,
    SMART_FILL_MODE_NUMERIC,
    SMART_FILL_MODE_DATETIME,
    SMART_FILL_MODE_CATEGORY,
    SMART_FILL_MODE_CUSTOM,
)

_DATE_TEXT_EVIDENCE = re.compile(r"(?:\d{1,4}[-/.]\d{1,4}[-/.]\d{1,4})|(?:\d{1,2}:\d{2})")
_NUMERIC_DATE_TEXT = re.compile(
    r"^\s*(\d{1,4})([-/.])(\d{1,4})\2(\d{1,4})\s*$"
)
_DATE_FIELD_ORDERS = (
    ("day", "month", "year"),
    ("month", "day", "year"),
    ("year", "month", "day"),
    ("year", "day", "month"),
    ("day", "year", "month"),
    ("month", "year", "day"),
)


class SmartFillError(ValueError):
    """Raised when a worksheet selection cannot define the requested fill pattern."""


@dataclass(frozen=True, slots=True)
class SmartFillPlan:
    """Values inferred for the blank cells in one selected column range."""

    row_positions: tuple[int, ...]
    values: tuple[Any, ...]
    seed_count: int
    period: int
    description: str
    mode: str

    @property
    def filled_count(self) -> int:
        """Return the number of destination cells in the plan."""
        return len(self.row_positions)


def _blank_mask(values: pd.Series) -> np.ndarray:
    """Treat pandas missing values and whitespace-only strings as blank cells."""
    missing = values.isna().to_numpy(dtype=bool, copy=True)
    if values.dtype == object or pd.api.types.is_string_dtype(values.dtype):
        strings = values.astype("string")
        missing |= strings.str.strip().eq("").fillna(True).to_numpy(dtype=bool)
    return missing


def _selection_parts(
    series: pd.Series,
    start_row: int,
    end_row: int,
) -> tuple[pd.Series, np.ndarray, np.ndarray]:
    """Return the selected values plus relative seed and blank positions."""
    if start_row < 0 or end_row < start_row or end_row >= len(series):
        raise SmartFillError("The selected row range is outside the worksheet.")
    selected = series.iloc[start_row : end_row + 1]
    blank = _blank_mask(selected)
    return selected, np.flatnonzero(~blank), np.flatnonzero(blank)


def _require_targets(target_offsets: np.ndarray) -> None:
    """Require at least one blank destination cell."""
    if len(target_offsets) == 0:
        raise SmartFillError("The selected range has no blank cells to fill.")


def _linear_fit(x_values: np.ndarray, y_values: np.ndarray) -> tuple[float, float]:
    """Return a least-squares slope and intercept, repeating a lone seed."""
    if len(x_values) == 1:
        return 0.0, float(y_values[0])
    centered = x_values - float(np.mean(x_values))
    denominator = float(np.dot(centered, centered))
    if denominator == 0.0:
        return 0.0, float(np.mean(y_values))
    slope = float(np.dot(centered, y_values - float(np.mean(y_values))) / denominator)
    intercept = float(np.mean(y_values) - slope * float(np.mean(x_values)))
    return slope, intercept


def _is_linear(x_values: np.ndarray, y_values: np.ndarray) -> bool:
    """Return whether seeds lie on one numerical straight line."""
    if len(x_values) <= 2:
        return True
    slope, intercept = _linear_fit(x_values, y_values)
    residual = np.abs(y_values - (slope * x_values + intercept))
    scale = max(float(np.ptp(y_values)), float(np.max(np.abs(y_values))), 1.0)
    return bool(float(np.max(residual)) <= 1.0e-9 * scale)


def _auto_period(seed_rows: np.ndarray, seed_values: np.ndarray, maximum: int) -> int:
    """Detect a small interleaved period from a consecutive block of seeds."""
    if len(seed_rows) < 4 or not np.all(np.diff(seed_rows) == 1):
        return 1
    if _is_linear(seed_rows.astype(float), seed_values):
        return 1

    maximum = min(maximum, len(seed_rows) // 2)
    origin = int(seed_rows[0])
    for period in range(2, maximum + 1):
        lanes_are_linear = True
        for lane in range(period):
            lane_mask = (seed_rows - origin) % period == lane
            if int(np.count_nonzero(lane_mask)) < 2 or not _is_linear(
                seed_rows[lane_mask].astype(float), seed_values[lane_mask]
            ):
                lanes_are_linear = False
                break
        if lanes_are_linear:
            return period
    return 1


def plan_numeric_smart_fill(
    series: pd.Series,
    start_row: int,
    end_row: int,
    *,
    period: int = 0,
    maximum_auto_period: int = 8,
) -> SmartFillPlan:
    """Infer blank values using one or more interleaved linear sequences."""
    if period < 0:
        raise SmartFillError("The smart-fill pattern period cannot be negative.")
    selected, seed_offsets, target_offsets = _selection_parts(series, start_row, end_row)
    if len(seed_offsets) == 0:
        raise SmartFillError("Enter at least one numeric seed value in the selected range.")
    _require_targets(target_offsets)

    seed_numeric = pd.to_numeric(
        selected.iloc[seed_offsets], errors="coerce"
    ).to_numpy(dtype=float)
    if not np.all(np.isfinite(seed_numeric)):
        raise SmartFillError("All nonblank seed cells in the selected range must be finite numbers.")

    seed_rows = seed_offsets.astype(int) + start_row
    target_rows = target_offsets.astype(int) + start_row
    resolved_period = (
        _auto_period(seed_rows, seed_numeric, maximum_auto_period)
        if period == 0
        else period
    )
    resolved_period = max(resolved_period, 1)

    origin = int(seed_rows[0])
    predictions: list[float] = []
    for target_row in target_rows:
        lane = (int(target_row) - origin) % resolved_period
        lane_mask = (seed_rows - origin) % resolved_period == lane
        if not np.any(lane_mask):
            raise SmartFillError(
                f"Pattern period {resolved_period} has no seed for lane {lane + 1}. "
                "Add more consecutive seed values or choose a smaller period."
            )
        slope, intercept = _linear_fit(
            seed_rows[lane_mask].astype(float), seed_numeric[lane_mask]
        )
        value = slope * float(target_row) + intercept
        if not np.isfinite(value):
            raise SmartFillError("The inferred series produced a non-finite value.")
        predictions.append(float(value))

    if resolved_period == 1:
        description = "repeated value" if len(seed_rows) == 1 else "linear sequence"
    else:
        description = f"{resolved_period} interleaved linear sequences"
    return SmartFillPlan(
        row_positions=tuple(int(row) for row in target_rows),
        values=tuple(predictions),
        seed_count=len(seed_rows),
        period=resolved_period,
        description=description,
        mode=SMART_FILL_MODE_NUMERIC,
    )


def _parse_timestamp(value: Any) -> pd.Timestamp | None:
    """Parse one date/time seed without applying numeric serial-date semantics."""
    if isinstance(value, (int, float, complex, np.number)) and not isinstance(value, bool):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(parsed, pd.DatetimeIndex) or pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


@dataclass(frozen=True, slots=True)
class _NumericDateFormat:
    """One inferred ordering and presentation for a numeric date string."""

    order: tuple[str, str, str]
    separator: str
    widths: tuple[int, int, int]

    def format(self, value: pd.Timestamp) -> str:
        """Render a generated timestamp in the same field order as its anchors."""
        components = {
            "day": value.day,
            "month": value.month,
            "year": value.year,
        }
        rendered: list[str] = []
        for field, width in zip(self.order, self.widths, strict=True):
            number = components[field]
            if field == "year" and width <= 2:
                number %= 100
            rendered.append(str(number).zfill(width))
        return self.separator.join(rendered)


def _expanded_year(value: int, width: int) -> int:
    """Expand a conventional two-digit year while retaining full years verbatim."""
    if width > 2:
        return value
    return 2000 + value if value <= 68 else 1900 + value


def _timestamps_for_numeric_order(
    matches: list[re.Match[str]],
    order: tuple[str, str, str],
) -> list[pd.Timestamp] | None:
    """Parse all numeric date anchors with one candidate field ordering."""
    timestamps: list[pd.Timestamp] = []
    for match in matches:
        raw_parts = (match.group(1), match.group(3), match.group(4))
        parts = {field: int(raw) for field, raw in zip(order, raw_parts, strict=True)}
        year_position = order.index("year")
        parts["year"] = _expanded_year(parts["year"], len(raw_parts[year_position]))
        try:
            timestamps.append(
                pd.Timestamp(
                    year=parts["year"],
                    month=parts["month"],
                    day=parts["day"],
                )
            )
        except (TypeError, ValueError, OverflowError):
            return None
    return timestamps


def _date_order_score(
    matches: list[re.Match[str]],
    order: tuple[str, str, str],
    timestamps: list[pd.Timestamp],
    seed_rows: np.ndarray,
) -> tuple[float, float, float, int]:
    """Rank valid date orders using year evidence and sequence regularity."""
    year_position = order.index("year")
    year_tokens = [
        (match.group(1), match.group(3), match.group(4))[year_position]
        for match in matches
    ]
    year_evidence = sum(
        2 if len(token) == 4 else 1 if len(token) == 3 or int(token) > 31 else 0
        for token in year_tokens
    )

    residual_ratio = 0.0
    cadence = 0.0
    if len(timestamps) >= 2:
        values = np.asarray(
            [float(timestamp.value - timestamps[0].value) for timestamp in timestamps],
            dtype=float,
        )
        rows = seed_rows.astype(float) - float(seed_rows[0])
        slope, intercept = _linear_fit(rows, values)
        residual = np.abs(values - (slope * rows + intercept))
        scale = max(float(np.ptp(values)), 1.0)
        residual_ratio = float(np.max(residual)) / scale
        row_steps = np.diff(seed_rows.astype(float))
        time_steps = np.abs(np.diff(values))
        valid_steps = row_steps != 0
        if np.any(valid_steps):
            cadence = float(np.median(time_steps[valid_steps] / np.abs(row_steps[valid_steps])))

    # Tuple ordering is intentional: a clearly placed year wins first, then the
    # most regular and shortest plausible cadence. Day/month/year is the stable
    # fallback when every field is <= 12 and the anchors provide no distinction.
    preference = _DATE_FIELD_ORDERS.index(order)
    return (-float(year_evidence), residual_ratio, cadence, preference)


def _infer_numeric_date_format(
    values: Sequence[Any],
    seed_rows: np.ndarray,
) -> tuple[list[pd.Timestamp], _NumericDateFormat] | None:
    """Infer one of all six day/month/year orders across numeric text anchors."""
    text_values = [str(value).strip() for value in values]
    matches = [_NUMERIC_DATE_TEXT.fullmatch(value) for value in text_values]
    if not matches or any(match is None for match in matches):
        return None
    resolved_matches = [match for match in matches if match is not None]
    separators = {match.group(2) for match in resolved_matches}
    if len(separators) != 1:
        return None

    candidates: list[
        tuple[tuple[float, float, float, int], tuple[str, str, str], list[pd.Timestamp]]
    ] = []
    for order in _DATE_FIELD_ORDERS:
        timestamps = _timestamps_for_numeric_order(resolved_matches, order)
        if timestamps is None:
            continue
        candidates.append(
            (_date_order_score(resolved_matches, order, timestamps, seed_rows), order, timestamps)
        )
    if not candidates:
        return None

    _score, order, timestamps = min(candidates, key=lambda candidate: candidate[0])
    first = resolved_matches[0]
    widths = (len(first.group(1)), len(first.group(3)), len(first.group(4)))
    return timestamps, _NumericDateFormat(order, first.group(2), widths)


def _parse_datetime_anchors(
    values: Sequence[Any],
    seed_rows: np.ndarray,
) -> tuple[list[pd.Timestamp], _NumericDateFormat | None] | None:
    """Parse date anchors consistently and retain an inferred text format."""
    numeric_dates = _infer_numeric_date_format(values, seed_rows)
    if numeric_dates is not None:
        return numeric_dates

    timestamps = [_parse_timestamp(value) for value in values]
    if any(timestamp is None for timestamp in timestamps):
        return None
    return [timestamp for timestamp in timestamps if timestamp is not None], None


def _calendar_prediction(
    base: pd.Timestamp,
    month_delta: int,
    *,
    month_end: bool,
) -> pd.Timestamp:
    """Advance a timestamp by calendar months while preserving month-end intent."""
    if month_delta == 0:
        return base
    if month_end:
        return base + pd.offsets.MonthEnd(month_delta)
    return base + pd.DateOffset(months=month_delta)


def _calendar_month_step(
    seed_rows: np.ndarray,
    seeds: list[pd.Timestamp],
) -> tuple[int, bool] | None:
    """Return an exact per-row calendar-month step when the anchors support one."""
    if len(seeds) < 2:
        return None
    row_delta = int(seed_rows[1] - seed_rows[0])
    if row_delta == 0:
        return None
    month_delta = (
        (seeds[1].year - seeds[0].year) * 12
        + seeds[1].month
        - seeds[0].month
    )
    if month_delta == 0 or month_delta % row_delta != 0:
        return None
    step = month_delta // row_delta
    same_clock = all(
        (seed.hour, seed.minute, seed.second, seed.microsecond, seed.nanosecond)
        == (
            seeds[0].hour,
            seeds[0].minute,
            seeds[0].second,
            seeds[0].microsecond,
            seeds[0].nanosecond,
        )
        for seed in seeds
    )
    all_month_end = all(seed.is_month_end for seed in seeds)
    same_day = all(seed.day == seeds[0].day for seed in seeds)
    if not same_clock or not (all_month_end or same_day):
        return None
    base_row = int(seed_rows[0])
    for row, seed in zip(seed_rows, seeds, strict=True):
        predicted = _calendar_prediction(
            seeds[0],
            (int(row) - base_row) * step,
            month_end=all_month_end,
        )
        if predicted != seed:
            return None
    return step, all_month_end


def plan_datetime_smart_fill(
    series: pd.Series,
    start_row: int,
    end_row: int,
) -> SmartFillPlan:
    """Infer blank date/time values using calendar or fixed time intervals."""
    selected, seed_offsets, target_offsets = _selection_parts(series, start_row, end_row)
    if len(seed_offsets) == 0:
        raise SmartFillError("Enter at least one date/time seed in the selected range.")
    _require_targets(target_offsets)

    seed_rows = seed_offsets.astype(int) + start_row
    parsed_anchors = _parse_datetime_anchors(
        selected.iloc[seed_offsets].tolist(),
        seed_rows,
    )
    if parsed_anchors is None:
        raise SmartFillError("All nonblank seeds must be recognizable date/time values.")
    timestamps, text_format = parsed_anchors
    timezone = timestamps[0].tz
    if any(seed.tz != timezone for seed in timestamps):
        raise SmartFillError("Date/time seeds must use a consistent timezone.")

    target_rows = target_offsets.astype(int) + start_row
    predictions: list[pd.Timestamp] = []
    calendar_step = _calendar_month_step(seed_rows, timestamps)
    if len(timestamps) == 1:
        predictions = [timestamps[0] for _row in target_rows]
        description = "repeated date/time"
    elif calendar_step is not None:
        months_per_row, month_end = calendar_step
        base_row = int(seed_rows[0])
        predictions = [
            _calendar_prediction(
                timestamps[0],
                (int(row) - base_row) * months_per_row,
                month_end=month_end,
            )
            for row in target_rows
        ]
        description = (
            "calendar-year sequence"
            if months_per_row % 12 == 0
            else "calendar-month sequence"
        )
    else:
        base_row = int(seed_rows[0])
        base = timestamps[0]
        deltas = np.asarray([seed.value - base.value for seed in timestamps], dtype=float)
        slope, intercept = _linear_fit(
            seed_rows.astype(float) - float(base_row), deltas
        )
        for row in target_rows:
            delta_ns = int(round(slope * (int(row) - base_row) + intercept))
            predictions.append(base + pd.to_timedelta(delta_ns, unit="ns"))
        description = "date-time interval sequence"

    output_values: tuple[Any, ...]
    if text_format is None:
        output_values = tuple(predictions)
    else:
        output_values = tuple(text_format.format(value) for value in predictions)

    return SmartFillPlan(
        row_positions=tuple(int(row) for row in target_rows),
        values=output_values,
        seed_count=len(seed_rows),
        period=1,
        description=description,
        mode=SMART_FILL_MODE_DATETIME,
    )


def _category_key(value: Any) -> str:
    """Return a stable comparison key for categorical anchors."""
    return str(value).strip()


def _smallest_repeating_cycle(values: list[Any]) -> list[Any]:
    """Reduce an explicitly repeated seed block to its shortest cycle."""
    keys = [_category_key(value) for value in values]
    for period in range(1, len(values) + 1):
        if all(keys[index] == keys[index % period] for index in range(len(keys))):
            return values[:period]
    return values


def plan_category_smart_fill(
    series: pd.Series,
    start_row: int,
    end_row: int,
) -> SmartFillPlan:
    """Repeat the first consecutive block of selected category seeds."""
    selected, seed_offsets, target_offsets = _selection_parts(series, start_row, end_row)
    if len(seed_offsets) == 0:
        raise SmartFillError("Enter at least one category seed in the selected range.")
    _require_targets(target_offsets)

    first_seed = int(seed_offsets[0])
    block_end = first_seed
    while block_end + 1 < len(selected) and not _blank_mask(
        selected.iloc[block_end + 1 : block_end + 2]
    )[0]:
        block_end += 1
    cycle = _smallest_repeating_cycle(selected.iloc[first_seed : block_end + 1].tolist())
    cycle_keys = [_category_key(value) for value in cycle]
    for seed_offset in seed_offsets:
        expected = cycle_keys[(int(seed_offset) - first_seed) % len(cycle)]
        actual = _category_key(selected.iloc[int(seed_offset)])
        if actual != expected:
            raise SmartFillError(
                "Category anchors do not match one repeating cycle. Place one complete "
                "cycle in consecutive cells or use Custom List."
            )

    target_rows = target_offsets.astype(int) + start_row
    predictions = tuple(
        cycle[(int(offset) - first_seed) % len(cycle)] for offset in target_offsets
    )
    return SmartFillPlan(
        row_positions=tuple(int(row) for row in target_rows),
        values=predictions,
        seed_count=len(seed_offsets),
        period=len(cycle),
        description=f"category cycle ({len(cycle)} value{'s' if len(cycle) != 1 else ''})",
        mode=SMART_FILL_MODE_CATEGORY,
    )


def normalize_custom_list(values: Sequence[Any]) -> tuple[str, ...]:
    """Trim custom-list entries and discard empty items."""
    return tuple(str(value).strip() for value in values if str(value).strip())


def plan_custom_list_smart_fill(
    series: pd.Series,
    start_row: int,
    end_row: int,
    custom_values: Sequence[Any],
) -> SmartFillPlan:
    """Fill from an explicit cyclic list, aligned to any selected anchors."""
    values = normalize_custom_list(custom_values)
    if not values:
        raise SmartFillError("Enter at least one value in the custom list.")
    selected, seed_offsets, target_offsets = _selection_parts(series, start_row, end_row)
    _require_targets(target_offsets)

    value_keys = [value.casefold() for value in values]
    resolved_offset: int | None = None
    for candidate in range(len(values)):
        if all(
            _category_key(selected.iloc[int(seed_offset)]).casefold()
            == value_keys[(int(seed_offset) + candidate) % len(values)]
            for seed_offset in seed_offsets
        ):
            resolved_offset = candidate
            break
    if resolved_offset is None:
        raise SmartFillError(
            "The selected anchors do not follow the entered custom-list order."
        )

    target_rows = target_offsets.astype(int) + start_row
    predictions = tuple(
        values[(int(offset) + resolved_offset) % len(values)]
        for offset in target_offsets
    )
    return SmartFillPlan(
        row_positions=tuple(int(row) for row in target_rows),
        values=predictions,
        seed_count=len(seed_offsets),
        period=len(values),
        description=f"custom list cycle ({len(values)} values)",
        mode=SMART_FILL_MODE_CUSTOM,
    )


def _auto_mode(series: pd.Series, start_row: int, end_row: int) -> str:
    """Choose a conservative fill mode from the selected nonblank anchors."""
    selected, seed_offsets, _target_offsets = _selection_parts(series, start_row, end_row)
    if len(seed_offsets) == 0:
        raise SmartFillError("Auto mode requires at least one nonblank seed value.")
    seed_values = selected.iloc[seed_offsets]
    if pd.api.types.is_datetime64_any_dtype(series.dtype) or all(
        isinstance(value, (date, datetime, pd.Timestamp)) for value in seed_values
    ):
        return SMART_FILL_MODE_DATETIME

    numeric = pd.to_numeric(seed_values, errors="coerce").to_numpy(dtype=float)
    if np.all(np.isfinite(numeric)):
        return SMART_FILL_MODE_NUMERIC

    text_values = [str(value).strip() for value in seed_values]
    if text_values and all(_DATE_TEXT_EVIDENCE.search(value) for value in text_values):
        parsed = _parse_datetime_anchors(text_values, seed_offsets.astype(int) + start_row)
        if parsed is not None:
            return SMART_FILL_MODE_DATETIME
    return SMART_FILL_MODE_CATEGORY


def plan_smart_fill(
    series: pd.Series,
    start_row: int,
    end_row: int,
    *,
    mode: str = SMART_FILL_MODE_AUTO,
    period: int = 0,
    custom_values: Sequence[Any] = (),
) -> SmartFillPlan:
    """Plan a typed fill operation without modifying the source Series."""
    if mode not in SMART_FILL_MODES:
        raise SmartFillError(f"Unknown Smart Fill mode: {mode}")
    resolved_mode = (
        _auto_mode(series, start_row, end_row)
        if mode == SMART_FILL_MODE_AUTO
        else mode
    )
    if resolved_mode == SMART_FILL_MODE_NUMERIC:
        return plan_numeric_smart_fill(series, start_row, end_row, period=period)
    if resolved_mode == SMART_FILL_MODE_DATETIME:
        return plan_datetime_smart_fill(series, start_row, end_row)
    if resolved_mode == SMART_FILL_MODE_CATEGORY:
        return plan_category_smart_fill(series, start_row, end_row)
    return plan_custom_list_smart_fill(
        series,
        start_row,
        end_row,
        custom_values,
    )
