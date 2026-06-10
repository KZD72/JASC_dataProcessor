"""Statistical analysis helpers for workspace datasets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from math_engine.calculus import MathOperationError, validate_numeric_column_metadata


@dataclass(frozen=True, slots=True)
class StatisticOperation:
    """Metadata for one statistics operation exposed in the UI."""

    label: str
    scope: str


STATISTIC_OPERATIONS: dict[str, StatisticOperation] = {
    "single_complete": StatisticOperation("Single column > Complete report", "single"),
    "single_summary": StatisticOperation("Single column > Descriptive summary", "single"),
    "single_quantiles": StatisticOperation("Single column > Quantiles and percentiles", "single"),
    "single_distribution": StatisticOperation("Single column > Distribution shape", "single"),
    "single_normality": StatisticOperation("Single column > Normality tests", "single"),
    "single_outliers": StatisticOperation("Single column > Outlier diagnostics", "single"),
    "single_ci_mean": StatisticOperation("Single column > Mean confidence interval", "single"),
    "single_zscore": StatisticOperation("Single column > Z-score series", "single"),
    "single_cumulative": StatisticOperation("Single column > Cumulative statistics", "single"),
    "pair_complete": StatisticOperation("Two columns > Complete comparison report", "pair"),
    "pair_summary": StatisticOperation("Two columns > Pair summary", "pair"),
    "pair_correlations": StatisticOperation("Two columns > Pearson/Spearman/Kendall", "pair"),
    "pair_covariance": StatisticOperation("Two columns > Covariance matrix values", "pair"),
    "pair_linear_regression": StatisticOperation("Two columns > Linear regression", "pair"),
    "pair_error_metrics": StatisticOperation("Two columns > Error metrics", "pair"),
    "pair_bland_altman": StatisticOperation("Two columns > Bland-Altman agreement", "pair"),
    "pair_paired_ttest": StatisticOperation("Two columns > Paired t-test", "pair"),
    "pair_wilcoxon": StatisticOperation("Two columns > Wilcoxon signed-rank", "pair"),
    "pair_welch_ttest": StatisticOperation("Two columns > Welch independent t-test", "pair"),
    "pair_mann_whitney": StatisticOperation("Two columns > Mann-Whitney U", "pair"),
    "pair_ks": StatisticOperation("Two columns > Kolmogorov-Smirnov two-sample", "pair"),
    "pair_variance_tests": StatisticOperation("Two columns > Variance tests", "pair"),
    "multi_complete": StatisticOperation("Multiple columns > Complete report", "multi"),
    "multi_summary": StatisticOperation("Multiple columns > Descriptive summary", "multi"),
    "multi_correlations": StatisticOperation("Multiple columns > Correlation matrix tests", "multi"),
    "multi_covariance": StatisticOperation("Multiple columns > Covariance matrix values", "multi"),
    "multi_pca": StatisticOperation("Multiple columns > PCA summary", "multi"),
    "group_complete": StatisticOperation("Grouped > Complete report", "group"),
    "group_summary": StatisticOperation("Grouped > Descriptive summary by group", "group"),
    "group_assumptions": StatisticOperation("Grouped > Assumption checks", "group"),
    "group_anova": StatisticOperation("Grouped > One-way ANOVA", "group"),
    "group_kruskal": StatisticOperation("Grouped > Kruskal-Wallis", "group"),
    "group_tukey": StatisticOperation("Grouped > Tukey HSD post-hoc", "group"),
    "group_pairwise_mann_whitney": StatisticOperation("Grouped > Pairwise Mann-Whitney", "group"),
}


def run_statistical_analysis(
    primary: pd.Series,
    primary_label: str,
    operation_key: str,
    secondary: pd.Series | None = None,
    secondary_label: str = "",
) -> pd.DataFrame:
    """Run a selected statistics operation and return a result DataFrame."""
    operation = STATISTIC_OPERATIONS.get(operation_key)
    if operation is None:
        raise MathOperationError(f"Unknown statistics operation: {operation_key}")

    if operation.scope in {"pair", "group"} and secondary is None:
        raise MathOperationError("Choose a second data column for this statistics operation.")

    x = _numeric_series(primary, primary_label, minimum_points=1)
    if operation.scope == "group":
        assert secondary is not None
        return _run_grouped_analysis(x, primary_label, secondary, secondary_label, operation_key)
    if operation.scope == "multi":
        raise MathOperationError("Multiple-column statistics require a multi-column input frame.")

    y = _numeric_series(secondary, secondary_label, minimum_points=1) if secondary is not None else None

    if operation_key == "single_complete":
        return _concat_reports(
            [
                _section_or_error(lambda: _single_summary(x, primary_label, operation_key), operation_key, primary_label),
                _section_or_error(lambda: _single_quantiles(x, primary_label, operation_key), operation_key, primary_label),
                _section_or_error(lambda: _single_distribution(x, primary_label, operation_key), operation_key, primary_label),
                _section_or_error(lambda: _single_normality(x, primary_label, operation_key), operation_key, primary_label),
                _section_or_error(lambda: _single_outliers(x, primary_label, operation_key), operation_key, primary_label),
                _section_or_error(lambda: _single_ci_mean(x, primary_label, operation_key), operation_key, primary_label),
            ]
        )
    if operation_key == "single_summary":
        return _single_summary(x, primary_label, operation_key)
    if operation_key == "single_quantiles":
        return _single_quantiles(x, primary_label, operation_key)
    if operation_key == "single_distribution":
        return _single_distribution(x, primary_label, operation_key)
    if operation_key == "single_normality":
        return _single_normality(x, primary_label, operation_key)
    if operation_key == "single_outliers":
        return _single_outliers(x, primary_label, operation_key)
    if operation_key == "single_ci_mean":
        return _single_ci_mean(x, primary_label, operation_key)
    if operation_key == "single_zscore":
        return _single_zscore_series(x, primary_label, operation_key)
    if operation_key == "single_cumulative":
        return _single_cumulative_series(x, primary_label, operation_key)

    assert y is not None
    if operation_key == "pair_complete":
        return _concat_reports(
            [
                _section_or_error(lambda: _pair_summary(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_correlations(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_covariance(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_linear_regression(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_error_metrics(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_bland_altman(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_paired_ttest(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_wilcoxon(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_welch_ttest(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_mann_whitney(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_ks(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
                _section_or_error(lambda: _pair_variance_tests(x, y, primary_label, secondary_label, operation_key), operation_key, primary_label, secondary_label),
            ]
        )
    if operation_key == "pair_summary":
        return _pair_summary(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_correlations":
        return _pair_correlations(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_covariance":
        return _pair_covariance(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_linear_regression":
        return _pair_linear_regression(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_error_metrics":
        return _pair_error_metrics(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_bland_altman":
        return _pair_bland_altman(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_paired_ttest":
        return _pair_paired_ttest(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_wilcoxon":
        return _pair_wilcoxon(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_welch_ttest":
        return _pair_welch_ttest(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_mann_whitney":
        return _pair_mann_whitney(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_ks":
        return _pair_ks(x, y, primary_label, secondary_label, operation_key)
    if operation_key == "pair_variance_tests":
        return _pair_variance_tests(x, y, primary_label, secondary_label, operation_key)

    raise MathOperationError(f"Unknown statistics operation: {operation_key}")


def run_multicolumn_statistical_analysis(
    frame: pd.DataFrame,
    column_labels: dict[str, str],
    operation_key: str,
) -> pd.DataFrame:
    """Run a selected multi-column statistics operation and return a report."""
    operation = STATISTIC_OPERATIONS.get(operation_key)
    if operation is None or operation.scope != "multi":
        raise MathOperationError(f"Unknown multi-column statistics operation: {operation_key}")

    numeric_frame = _numeric_frame(frame, column_labels, minimum_columns=2)
    if operation_key == "multi_complete":
        return _concat_reports(
            [
                _section_or_error(lambda: _multi_summary(numeric_frame, column_labels, operation_key), operation_key, "Multiple columns"),
                _section_or_error(lambda: _multi_correlations(numeric_frame, column_labels, operation_key), operation_key, "Multiple columns"),
                _section_or_error(lambda: _multi_covariance(numeric_frame, column_labels, operation_key), operation_key, "Multiple columns"),
                _section_or_error(lambda: _multi_pca(numeric_frame, column_labels, operation_key), operation_key, "Multiple columns"),
            ]
        )
    if operation_key == "multi_summary":
        return _multi_summary(numeric_frame, column_labels, operation_key)
    if operation_key == "multi_correlations":
        return _multi_correlations(numeric_frame, column_labels, operation_key)
    if operation_key == "multi_covariance":
        return _multi_covariance(numeric_frame, column_labels, operation_key)
    if operation_key == "multi_pca":
        return _multi_pca(numeric_frame, column_labels, operation_key)
    raise MathOperationError(f"Unknown multi-column statistics operation: {operation_key}")


def _run_grouped_analysis(
    values: pd.Series,
    value_label: str,
    groups: pd.Series,
    group_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Run a selected grouped/factor statistics operation."""
    grouped = _grouped_numeric_values(values, groups, value_label, group_label)
    if operation_key == "group_complete":
        return _concat_reports(
            [
                _section_or_error(lambda: _group_summary(grouped, value_label, group_label, operation_key), operation_key, value_label, group_label),
                _section_or_error(lambda: _group_assumptions(grouped, value_label, group_label, operation_key), operation_key, value_label, group_label),
                _section_or_error(lambda: _group_anova(grouped, value_label, group_label, operation_key), operation_key, value_label, group_label),
                _section_or_error(lambda: _group_kruskal(grouped, value_label, group_label, operation_key), operation_key, value_label, group_label),
                _section_or_error(lambda: _group_tukey(grouped, value_label, group_label, operation_key), operation_key, value_label, group_label),
                _section_or_error(lambda: _group_pairwise_mann_whitney(grouped, value_label, group_label, operation_key), operation_key, value_label, group_label),
            ]
        )
    if operation_key == "group_summary":
        return _group_summary(grouped, value_label, group_label, operation_key)
    if operation_key == "group_assumptions":
        return _group_assumptions(grouped, value_label, group_label, operation_key)
    if operation_key == "group_anova":
        return _group_anova(grouped, value_label, group_label, operation_key)
    if operation_key == "group_kruskal":
        return _group_kruskal(grouped, value_label, group_label, operation_key)
    if operation_key == "group_tukey":
        return _group_tukey(grouped, value_label, group_label, operation_key)
    if operation_key == "group_pairwise_mann_whitney":
        return _group_pairwise_mann_whitney(grouped, value_label, group_label, operation_key)
    raise MathOperationError(f"Unknown grouped statistics operation: {operation_key}")


def _group_summary(
    grouped: list[tuple[str, pd.Series]],
    value_label: str,
    group_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return descriptive statistics per group."""
    rows: list[dict[str, object]] = [
        _metric("group_count", len(grouped)),
        _metric("total_numeric_count", sum(len(values) for _name, values in grouped)),
    ]
    for group_name, group_values in grouped:
        prefix = _safe_metric_label(group_name)
        std = float(group_values.std(ddof=1)) if len(group_values) > 1 else np.nan
        rows.extend(
            [
                _metric(f"{prefix}_count", len(group_values), notes=f"group={group_name}"),
                _metric(f"{prefix}_mean", float(group_values.mean()), notes=f"group={group_name}"),
                _metric(f"{prefix}_median", float(group_values.median()), notes=f"group={group_name}"),
                _metric(f"{prefix}_std", std, notes=f"group={group_name}"),
                _metric(f"{prefix}_sem", float(stats.sem(group_values)) if len(group_values) > 1 else np.nan, notes=f"group={group_name}"),
                _metric(f"{prefix}_min", float(group_values.min()), notes=f"group={group_name}"),
                _metric(f"{prefix}_max", float(group_values.max()), notes=f"group={group_name}"),
                _metric(f"{prefix}_iqr", float(group_values.quantile(0.75) - group_values.quantile(0.25)), notes=f"group={group_name}"),
            ]
        )
    return _report_frame(operation_key, value_label, group_label, rows)


def _group_assumptions(
    grouped: list[tuple[str, pd.Series]],
    value_label: str,
    group_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return grouped normality and equal-variance diagnostics."""
    rows: list[dict[str, object]] = []
    arrays = _group_arrays(grouped, minimum_per_group=2)
    levene = stats.levene(*arrays, center="median")
    rows.append(_metric("levene_brown_forsythe_statistic", levene.statistic, p_value=levene.pvalue))
    bartlett = stats.bartlett(*arrays)
    rows.append(_metric("bartlett_statistic", bartlett.statistic, p_value=bartlett.pvalue))

    for group_name, values in grouped:
        prefix = _safe_metric_label(group_name)
        if len(values) < 3:
            rows.append(_metric(f"{prefix}_shapiro_wilk", np.nan, notes=f"group={group_name}; requires at least 3 samples."))
            continue
        if len(values) > 5000:
            rows.append(_metric(f"{prefix}_shapiro_wilk", np.nan, notes=f"group={group_name}; skipped because Shapiro-Wilk is intended for <= 5000 samples."))
            continue
        shapiro = stats.shapiro(values)
        rows.append(_metric(f"{prefix}_shapiro_wilk", shapiro.statistic, p_value=shapiro.pvalue, notes=f"group={group_name}"))
    return _report_frame(operation_key, value_label, group_label, rows)


def _group_anova(
    grouped: list[tuple[str, pd.Series]],
    value_label: str,
    group_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return a one-way ANOVA table and effect sizes."""
    arrays = _group_arrays(grouped, minimum_per_group=2)
    all_values = np.concatenate(arrays)
    grand_mean = float(np.mean(all_values))
    ss_between = float(sum(len(values) * (float(np.mean(values)) - grand_mean) ** 2 for values in arrays))
    ss_within = float(sum(np.sum((values - np.mean(values)) ** 2) for values in arrays))
    df_between = len(arrays) - 1
    df_within = len(all_values) - len(arrays)
    ms_between = ss_between / df_between if df_between > 0 else np.nan
    ms_within = ss_within / df_within if df_within > 0 else np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = stats.f_oneway(*arrays)
    eta_squared = ss_between / (ss_between + ss_within) if (ss_between + ss_within) > 0 else np.nan
    omega_squared = (
        (ss_between - df_between * ms_within) / (ss_between + ss_within + ms_within)
        if np.isfinite(ms_within) and (ss_between + ss_within + ms_within) > 0
        else np.nan
    )
    rows = [
        _metric("group_count", len(arrays)),
        _metric("total_numeric_count", len(all_values)),
        _metric("df_between_groups", df_between),
        _metric("df_within_groups", df_within),
        _metric("ss_between_groups", ss_between),
        _metric("ss_within_groups", ss_within),
        _metric("ms_between_groups", ms_between),
        _metric("ms_within_groups", ms_within),
        _metric("f_statistic", result.statistic, p_value=result.pvalue),
        _metric("eta_squared", eta_squared),
        _metric("omega_squared", omega_squared),
    ]
    return _report_frame(operation_key, value_label, group_label, rows)


def _group_kruskal(
    grouped: list[tuple[str, pd.Series]],
    value_label: str,
    group_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return Kruskal-Wallis nonparametric one-way test metrics."""
    arrays = _group_arrays(grouped, minimum_per_group=1)
    total_count = sum(len(values) for values in arrays)
    result = stats.kruskal(*arrays)
    epsilon_squared = (
        (float(result.statistic) - len(arrays) + 1) / (total_count - len(arrays))
        if total_count > len(arrays)
        else np.nan
    )
    rows = [
        _metric("group_count", len(arrays)),
        _metric("total_numeric_count", total_count),
        _metric("h_statistic", result.statistic, p_value=result.pvalue),
        _metric("epsilon_squared", epsilon_squared),
    ]
    return _report_frame(operation_key, value_label, group_label, rows)


def _group_tukey(
    grouped: list[tuple[str, pd.Series]],
    value_label: str,
    group_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return Tukey HSD pairwise mean comparisons."""
    arrays = _group_arrays(grouped, minimum_per_group=2)
    labels = [name for name, _values in grouped]
    try:
        result = stats.tukey_hsd(*arrays)
    except AttributeError as exc:
        raise MathOperationError("This SciPy version does not provide stats.tukey_hsd.") from exc

    low = high = None
    try:
        confidence_interval = result.confidence_interval(confidence_level=0.95)
        low = np.asarray(confidence_interval.low, dtype=float)
        high = np.asarray(confidence_interval.high, dtype=float)
    except Exception:
        pass

    statistic = np.asarray(result.statistic, dtype=float)
    p_values = np.asarray(result.pvalue, dtype=float)
    rows: list[dict[str, object]] = []
    for first, second in combinations(range(len(labels)), 2):
        pair_label = f"{labels[first]} vs {labels[second]}"
        notes = f"groups={pair_label}"
        if low is not None and high is not None:
            notes = f"{notes}; 95% CI [{low[first, second]:.6g}, {high[first, second]:.6g}]"
        rows.append(
            _metric(
                f"tukey_{_safe_metric_label(labels[first])}_vs_{_safe_metric_label(labels[second])}",
                statistic[first, second],
                p_value=p_values[first, second],
                notes=notes,
            )
        )
    return _report_frame(operation_key, value_label, group_label, rows)


def _group_pairwise_mann_whitney(
    grouped: list[tuple[str, pd.Series]],
    value_label: str,
    group_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return pairwise Mann-Whitney U tests with Holm-adjusted p-values."""
    labels = [name for name, _values in grouped]
    arrays = _group_arrays(grouped, minimum_per_group=1)
    comparisons: list[tuple[int, int, float, float, float]] = []
    raw_p_values: list[float] = []
    for first, second in combinations(range(len(arrays)), 2):
        result = stats.mannwhitneyu(arrays[first], arrays[second], alternative="two-sided")
        effect = _rank_biserial_from_u(float(result.statistic), len(arrays[first]), len(arrays[second]))
        comparisons.append((first, second, float(result.statistic), float(result.pvalue), effect))
        raw_p_values.append(float(result.pvalue))

    adjusted = _holm_adjusted_p_values(raw_p_values)
    rows: list[dict[str, object]] = []
    for index, (first, second, statistic, p_value, effect) in enumerate(comparisons):
        pair_metric = f"mann_whitney_{_safe_metric_label(labels[first])}_vs_{_safe_metric_label(labels[second])}"
        rows.append(
            _metric(
                pair_metric,
                statistic,
                p_value=p_value,
                notes=(
                    f"groups={labels[first]} vs {labels[second]}; "
                    f"holm_adjusted_p={adjusted[index]:.6g}; rank_biserial={effect:.6g}"
                ),
            )
        )
    return _report_frame(operation_key, value_label, group_label, rows)


def _single_summary(series: pd.Series, label: str, operation_key: str) -> pd.DataFrame:
    """Return central tendency and spread metrics for one column."""
    values = _clean_values(series, label, minimum_points=1)
    std = float(values.std(ddof=1)) if len(values) > 1 else np.nan
    mean = float(values.mean())
    rows = [
        _metric("count", len(values)),
        _metric("missing_or_non_numeric", int(series.isna().sum())),
        _metric("mean", mean),
        _metric("median", float(values.median())),
        _metric("standard_deviation_sample", std),
        _metric("variance_sample", float(values.var(ddof=1)) if len(values) > 1 else np.nan),
        _metric("standard_error_mean", float(stats.sem(values)) if len(values) > 1 else np.nan),
        _metric("minimum", float(values.min())),
        _metric("maximum", float(values.max())),
        _metric("range", float(values.max() - values.min())),
        _metric("sum", float(values.sum())),
        _metric("coefficient_of_variation", std / mean if mean != 0 and np.isfinite(std) else np.nan),
    ]
    return _report_frame(operation_key, label, "", rows)


def _single_quantiles(series: pd.Series, label: str, operation_key: str) -> pd.DataFrame:
    """Return common percentiles for one column."""
    values = _clean_values(series, label, minimum_points=1)
    rows = [
        _metric(f"p{percentile:g}", float(values.quantile(percentile / 100.0)))
        for percentile in (0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100)
    ]
    rows.append(_metric("iqr", float(values.quantile(0.75) - values.quantile(0.25))))
    return _report_frame(operation_key, label, "", rows)


def _single_distribution(series: pd.Series, label: str, operation_key: str) -> pd.DataFrame:
    """Return shape and robust spread metrics for one column."""
    values = _clean_values(series, label, minimum_points=2)
    median = float(values.median())
    mad = float(np.median(np.abs(values.to_numpy(dtype=float) - median)))
    rows = [
        _metric("skewness", float(stats.skew(values, bias=False)) if len(values) > 2 else np.nan),
        _metric("kurtosis_excess", float(stats.kurtosis(values, bias=False)) if len(values) > 3 else np.nan),
        _metric("median_absolute_deviation", mad),
        _metric("geometric_mean", float(stats.gmean(values)) if (values > 0).all() else np.nan, notes="Requires all values > 0."),
        _metric("harmonic_mean", float(stats.hmean(values)) if (values > 0).all() else np.nan, notes="Requires all values > 0."),
    ]
    return _report_frame(operation_key, label, "", rows)


def _single_normality(series: pd.Series, label: str, operation_key: str) -> pd.DataFrame:
    """Return normality test statistics for one column."""
    values = _clean_values(series, label, minimum_points=3)
    rows: list[dict[str, object]] = []
    if len(values) <= 5000:
        shapiro = stats.shapiro(values)
        rows.append(_metric("shapiro_wilk", shapiro.statistic, p_value=shapiro.pvalue))
    else:
        rows.append(_metric("shapiro_wilk", np.nan, notes="Skipped because Shapiro-Wilk is intended for <= 5000 samples."))

    if len(values) >= 8:
        normaltest = stats.normaltest(values)
        rows.append(_metric("dagostino_pearson", normaltest.statistic, p_value=normaltest.pvalue))
    else:
        rows.append(_metric("dagostino_pearson", np.nan, notes="Requires at least 8 samples."))

    rows.extend(_anderson_darling_normality_metrics(values))
    return _report_frame(operation_key, label, "", rows)


def _anderson_darling_normality_metrics(values: pd.Series) -> list[dict[str, object]]:
    """Return Anderson-Darling normality metrics across SciPy versions."""
    sample = values.to_numpy(dtype=float)
    method_errors: list[str] = []
    legacy_api = False
    for method in ("interpolate", "interpolated"):
        try:
            result = stats.anderson(sample, dist="norm", method=method)
        except TypeError:
            legacy_api = True
            break
        except ValueError as exc:
            method_errors.append(str(exc))
            continue

        p_value = getattr(result, "pvalue", np.nan)
        try:
            p_value_float = float(p_value)
        except (TypeError, ValueError):
            p_value_float = np.nan
        return [
            _metric(
                "anderson_darling_statistic",
                float(result.statistic),
                p_value=p_value_float if np.isfinite(p_value_float) else np.nan,
                notes=f"P-value calculated with SciPy method='{method}'.",
            )
        ]

    if method_errors and not legacy_api:
        raise MathOperationError(
            "Anderson-Darling normality test failed: " + "; ".join(method_errors)
        )

    try:
        legacy_result = stats.anderson(sample, dist="norm")
    except Exception as exc:
        detail = "; ".join(method_errors) if method_errors else str(exc)
        raise MathOperationError(f"Anderson-Darling normality test failed: {detail}") from exc

    rows = [
        _metric(
            "anderson_darling_statistic",
            float(legacy_result.statistic),
            notes="SciPy version does not support Anderson-Darling p-values; reporting legacy critical values.",
        )
    ]
    for level, critical in zip(legacy_result.significance_level, legacy_result.critical_values):
        rows.append(_metric(f"anderson_critical_{level:g}pct", float(critical)))
    return rows


def _single_outliers(series: pd.Series, label: str, operation_key: str) -> pd.DataFrame:
    """Return IQR, z-score, and modified-z outlier diagnostics."""
    values = _clean_values(series, label, minimum_points=2)
    q1 = float(values.quantile(0.25))
    q3 = float(values.quantile(0.75))
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    std = float(values.std(ddof=1))
    median = float(values.median())
    mad = float(np.median(np.abs(values.to_numpy(dtype=float) - median)))
    rows = [
        _metric("iqr_lower_fence", lower),
        _metric("iqr_upper_fence", upper),
        _metric("iqr_outlier_count", int(((values < lower) | (values > upper)).sum())),
        _metric("absolute_z_gt_3_count", int((np.abs((values - values.mean()) / std) > 3).sum()) if std > 0 else np.nan),
        _metric(
            "absolute_modified_z_gt_3_5_count",
            int((np.abs(0.6745 * (values - median) / mad) > 3.5).sum()) if mad > 0 else np.nan,
        ),
    ]
    return _report_frame(operation_key, label, "", rows)


def _single_ci_mean(series: pd.Series, label: str, operation_key: str) -> pd.DataFrame:
    """Return a 95 percent confidence interval for the column mean."""
    values = _clean_values(series, label, minimum_points=2)
    mean = float(values.mean())
    sem = float(stats.sem(values))
    half_width = float(stats.t.ppf(0.975, df=len(values) - 1) * sem)
    rows = [
        _metric("mean", mean),
        _metric("confidence_level", 0.95),
        _metric("lower_bound", mean - half_width),
        _metric("upper_bound", mean + half_width),
        _metric("half_width", half_width),
    ]
    return _report_frame(operation_key, label, "", rows)


def _single_zscore_series(series: pd.Series, label: str, operation_key: str) -> pd.DataFrame:
    """Return a row-wise z-score result sheet for one column."""
    values = _clean_values(series, label, minimum_points=2)
    std = float(values.std(ddof=1))
    if std == 0:
        raise MathOperationError(f"{label} has zero variance; z-scores cannot be calculated.")
    z_values = (values - values.mean()) / std
    return pd.DataFrame(
        {
            "operation": operation_key,
            "primary": label,
            "row_index": z_values.index,
            "value": values.to_numpy(dtype=float),
            "z_score": z_values.to_numpy(dtype=float),
        }
    )


def _single_cumulative_series(series: pd.Series, label: str, operation_key: str) -> pd.DataFrame:
    """Return expanding count, sum, mean, std, min, and max for one column."""
    values = _clean_values(series, label, minimum_points=1)
    expanding = values.expanding()
    return pd.DataFrame(
        {
            "operation": operation_key,
            "primary": label,
            "row_index": values.index,
            "value": values.to_numpy(dtype=float),
            "cumulative_count": expanding.count().to_numpy(dtype=float),
            "cumulative_sum": expanding.sum().to_numpy(dtype=float),
            "cumulative_mean": expanding.mean().to_numpy(dtype=float),
            "cumulative_std": expanding.std().to_numpy(dtype=float),
            "cumulative_min": expanding.min().to_numpy(dtype=float),
            "cumulative_max": expanding.max().to_numpy(dtype=float),
        }
    )


def _pair_summary(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return summary metrics for aligned column pairs."""
    paired = _aligned_pair(x, y, x_label, y_label, minimum_points=1)
    diff = paired["primary"] - paired["secondary"]
    rows = [
        _metric("aligned_count", len(paired)),
        _metric("primary_mean", float(paired["primary"].mean())),
        _metric("secondary_mean", float(paired["secondary"].mean())),
        _metric("mean_difference_primary_minus_secondary", float(diff.mean())),
        _metric("median_difference_primary_minus_secondary", float(diff.median())),
        _metric("difference_standard_deviation", float(diff.std(ddof=1)) if len(diff) > 1 else np.nan),
    ]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_correlations(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return Pearson, Spearman, and Kendall correlation tests."""
    paired = _aligned_pair(x, y, x_label, y_label, minimum_points=3)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pearson = stats.pearsonr(paired["primary"], paired["secondary"])
        spearman = stats.spearmanr(paired["primary"], paired["secondary"])
        kendall = stats.kendalltau(paired["primary"], paired["secondary"])
    rows = [
        _metric("pearson_r", pearson.statistic, p_value=pearson.pvalue),
        _metric("spearman_rho", spearman.statistic, p_value=spearman.pvalue),
        _metric("kendall_tau", kendall.statistic, p_value=kendall.pvalue),
    ]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_covariance(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return variance and covariance values for aligned columns."""
    paired = _aligned_pair(x, y, x_label, y_label, minimum_points=2)
    covariance = np.cov(paired["primary"], paired["secondary"], ddof=1)
    rows = [
        _metric("primary_variance", float(covariance[0, 0])),
        _metric("secondary_variance", float(covariance[1, 1])),
        _metric("covariance", float(covariance[0, 1])),
    ]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_linear_regression(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return ordinary least-squares linear regression metrics."""
    paired = _aligned_pair(x, y, x_label, y_label, minimum_points=2)
    result = stats.linregress(paired["primary"], paired["secondary"])
    rows = [
        _metric("slope", result.slope, p_value=result.pvalue),
        _metric("intercept", result.intercept),
        _metric("r_value", result.rvalue),
        _metric("r_squared", result.rvalue**2),
        _metric("slope_standard_error", result.stderr),
        _metric("intercept_standard_error", result.intercept_stderr),
    ]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_error_metrics(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return error metrics treating secondary as prediction against primary."""
    paired = _aligned_pair(x, y, x_label, y_label, minimum_points=2)
    observed = paired["primary"].to_numpy(dtype=float)
    predicted = paired["secondary"].to_numpy(dtype=float)
    residual = predicted - observed
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((observed - np.mean(observed)) ** 2))
    rows = [
        _metric("mean_error_secondary_minus_primary", float(np.mean(residual))),
        _metric("mean_absolute_error", float(np.mean(np.abs(residual)))),
        _metric("root_mean_square_error", float(np.sqrt(np.mean(residual**2)))),
        _metric("r_squared_against_primary", 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan),
    ]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_bland_altman(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return Bland-Altman agreement metrics for aligned pairs."""
    paired = _aligned_pair(x, y, x_label, y_label, minimum_points=2)
    diff = paired["primary"] - paired["secondary"]
    mean_diff = float(diff.mean())
    std_diff = float(diff.std(ddof=1))
    rows = [
        _metric("bias_mean_difference", mean_diff),
        _metric("lower_limit_of_agreement", mean_diff - 1.96 * std_diff),
        _metric("upper_limit_of_agreement", mean_diff + 1.96 * std_diff),
        _metric("difference_standard_deviation", std_diff),
    ]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_paired_ttest(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return a paired t-test for aligned column pairs."""
    paired = _aligned_pair(x, y, x_label, y_label, minimum_points=2)
    result = stats.ttest_rel(paired["primary"], paired["secondary"])
    rows = [
        _metric("paired_t_statistic", result.statistic, p_value=result.pvalue),
        _metric("degrees_of_freedom", len(paired) - 1),
    ]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_wilcoxon(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return a Wilcoxon signed-rank test for aligned column pairs."""
    paired = _aligned_pair(x, y, x_label, y_label, minimum_points=2)
    try:
        result = stats.wilcoxon(paired["primary"], paired["secondary"])
    except ValueError as exc:
        raise MathOperationError(str(exc)) from exc
    rows = [_metric("wilcoxon_statistic", result.statistic, p_value=result.pvalue)]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_welch_ttest(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return Welch's independent-samples t-test for two columns."""
    x_values, y_values = _independent_pair(x, y, x_label, y_label, minimum_points=2)
    result = stats.ttest_ind(x_values, y_values, equal_var=False)
    rows = [_metric("welch_t_statistic", result.statistic, p_value=result.pvalue)]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_mann_whitney(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return a Mann-Whitney U test for two independent columns."""
    x_values, y_values = _independent_pair(x, y, x_label, y_label, minimum_points=1)
    result = stats.mannwhitneyu(x_values, y_values, alternative="two-sided")
    rows = [_metric("mann_whitney_u", result.statistic, p_value=result.pvalue)]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_ks(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return a two-sample Kolmogorov-Smirnov test."""
    x_values, y_values = _independent_pair(x, y, x_label, y_label, minimum_points=1)
    result = stats.ks_2samp(x_values, y_values)
    rows = [_metric("ks_statistic", result.statistic, p_value=result.pvalue)]
    return _report_frame(operation_key, x_label, y_label, rows)


def _pair_variance_tests(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    operation_key: str,
) -> pd.DataFrame:
    """Return common equal-variance test results."""
    x_values, y_values = _independent_pair(x, y, x_label, y_label, minimum_points=2)
    levene = stats.levene(x_values, y_values)
    bartlett = stats.bartlett(x_values, y_values)
    rows = [
        _metric("primary_variance", float(x_values.var(ddof=1))),
        _metric("secondary_variance", float(y_values.var(ddof=1))),
        _metric("levene_statistic", levene.statistic, p_value=levene.pvalue),
        _metric("bartlett_statistic", bartlett.statistic, p_value=bartlett.pvalue),
    ]
    return _report_frame(operation_key, x_label, y_label, rows)


def _multi_summary(
    frame: pd.DataFrame,
    column_labels: dict[str, str],
    operation_key: str,
) -> pd.DataFrame:
    """Return descriptive metrics for each selected numeric column."""
    frames: list[pd.DataFrame] = []
    for column in frame.columns:
        label = _column_label(column_labels, column)
        series = frame[column]
        frames.extend(
            [
                _section_or_error(lambda series=series, label=label: _single_summary(series, label, operation_key), operation_key, label),
                _section_or_error(lambda series=series, label=label: _single_quantiles(series, label, operation_key), operation_key, label),
                _section_or_error(lambda series=series, label=label: _single_distribution(series, label, operation_key), operation_key, label),
            ]
        )
    return _concat_reports(frames)


def _multi_correlations(
    frame: pd.DataFrame,
    column_labels: dict[str, str],
    operation_key: str,
) -> pd.DataFrame:
    """Return pairwise Pearson, Spearman, and Kendall tests for many columns."""
    rows: list[dict[str, object]] = []
    for first, second in combinations(frame.columns, 2):
        first_label = _column_label(column_labels, first)
        second_label = _column_label(column_labels, second)
        paired = pd.DataFrame(
            {
                "first": frame[first],
                "second": frame[second],
            }
        ).dropna()
        if len(paired) < 3:
            rows.append(
                _metric(
                    "correlation_pair_unavailable",
                    np.nan,
                    notes=f"{first_label} vs {second_label}; requires at least 3 aligned numeric rows.",
                )
            )
            continue

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pearson = stats.pearsonr(paired["first"], paired["second"])
            spearman = stats.spearmanr(paired["first"], paired["second"])
            kendall = stats.kendalltau(paired["first"], paired["second"])
        notes = f"{first_label} vs {second_label}; aligned_count={len(paired)}"
        rows.extend(
            [
                _metric("pearson_r", pearson.statistic, p_value=pearson.pvalue, notes=notes),
                _metric("spearman_rho", spearman.statistic, p_value=spearman.pvalue, notes=notes),
                _metric("kendall_tau", kendall.statistic, p_value=kendall.pvalue, notes=notes),
            ]
        )
    return _report_frame(operation_key, "Multiple columns", "", rows)


def _multi_covariance(
    frame: pd.DataFrame,
    column_labels: dict[str, str],
    operation_key: str,
) -> pd.DataFrame:
    """Return pairwise covariance values for many columns."""
    rows: list[dict[str, object]] = []
    for column in frame.columns:
        label = _column_label(column_labels, column)
        values = frame[column].dropna()
        variance = float(values.var(ddof=1)) if len(values) > 1 else np.nan
        rows.append(_metric("variance", variance, notes=f"column={label}; count={len(values)}"))

    for first, second in combinations(frame.columns, 2):
        first_label = _column_label(column_labels, first)
        second_label = _column_label(column_labels, second)
        paired = pd.DataFrame(
            {
                "first": frame[first],
                "second": frame[second],
            }
        ).dropna()
        if len(paired) < 2:
            rows.append(
                _metric(
                    "covariance_unavailable",
                    np.nan,
                    notes=f"{first_label} vs {second_label}; requires at least 2 aligned numeric rows.",
                )
            )
            continue
        covariance = float(np.cov(paired["first"], paired["second"], ddof=1)[0, 1])
        rows.append(
            _metric(
                "covariance",
                covariance,
                notes=f"{first_label} vs {second_label}; aligned_count={len(paired)}",
            )
        )
    return _report_frame(operation_key, "Multiple columns", "", rows)


def _multi_pca(
    frame: pd.DataFrame,
    column_labels: dict[str, str],
    operation_key: str,
) -> pd.DataFrame:
    """Return a standardized PCA summary using singular value decomposition."""
    complete = frame.dropna()
    if len(complete) < 2:
        raise MathOperationError("PCA requires at least 2 complete rows across the selected columns.")

    means = complete.mean(axis=0)
    stds = complete.std(axis=0, ddof=1)
    constant_columns = [str(column) for column, std in stds.items() if not np.isfinite(std) or std <= 0]
    if constant_columns:
        raise MathOperationError("PCA requires non-constant columns; constant column(s): " + ", ".join(constant_columns))

    standardized = (complete - means) / stds
    _u, singular_values, components = np.linalg.svd(standardized.to_numpy(dtype=float), full_matrices=False)
    explained_variance = singular_values**2 / (len(complete) - 1)
    total_variance = float(np.sum(explained_variance))
    explained_ratio = explained_variance / total_variance if total_variance > 0 else np.full_like(explained_variance, np.nan)
    cumulative_ratio = np.cumsum(explained_ratio)

    rows: list[dict[str, object]] = [
        _metric("complete_row_count", len(complete)),
        _metric("variable_count", len(frame.columns)),
    ]
    for component_index, (variance, ratio, cumulative) in enumerate(
        zip(explained_variance, explained_ratio, cumulative_ratio),
        start=1,
    ):
        component_name = f"pc{component_index}"
        rows.extend(
            [
                _metric(f"{component_name}_explained_variance", float(variance)),
                _metric(f"{component_name}_explained_variance_ratio", float(ratio)),
                _metric(f"{component_name}_cumulative_variance_ratio", float(cumulative)),
            ]
        )
        for column, loading in zip(frame.columns, components[component_index - 1]):
            label = _column_label(column_labels, column)
            rows.append(
                _metric(
                    f"{component_name}_loading_{_safe_metric_label(str(column))}",
                    float(loading),
                    notes=f"column={label}",
                )
            )
    return _report_frame(operation_key, "Multiple columns", "", rows)


def _grouped_numeric_values(
    values: pd.Series,
    groups: pd.Series,
    value_label: str,
    group_label: str,
) -> list[tuple[str, pd.Series]]:
    """Return numeric values split by categorical group labels."""
    paired = pd.DataFrame(
        {
            "value": values.reset_index(drop=True),
            "group": groups.reset_index(drop=True),
        }
    )
    paired["value"] = pd.to_numeric(paired["value"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    paired["group"] = paired["group"].where(paired["group"].notna(), pd.NA)
    paired = paired.dropna(subset=["value", "group"])
    if paired.empty:
        raise MathOperationError(f"{value_label} and {group_label} do not contain any complete numeric/group rows.")

    paired["group"] = paired["group"].astype(str).str.strip()
    paired = paired[paired["group"] != ""]
    if paired.empty:
        raise MathOperationError(f"{group_label} does not contain any non-empty group labels.")

    grouped: list[tuple[str, pd.Series]] = []
    for group_name, group_frame in paired.groupby("group", sort=True):
        group_values = group_frame["value"].astype(float).reset_index(drop=True)
        if not group_values.empty:
            grouped.append((str(group_name), group_values))

    if len(grouped) < 2:
        raise MathOperationError("Grouped statistics require at least two groups with numeric values.")
    return grouped


def _group_arrays(grouped: list[tuple[str, pd.Series]], minimum_per_group: int) -> list[np.ndarray]:
    """Return group arrays after validating per-group sample counts."""
    arrays: list[np.ndarray] = []
    short_groups: list[str] = []
    for group_name, values in grouped:
        if len(values) < minimum_per_group:
            short_groups.append(group_name)
            continue
        arrays.append(values.to_numpy(dtype=float))
    if short_groups:
        raise MathOperationError(
            f"Each group needs at least {minimum_per_group} numeric value(s); short group(s): "
            + ", ".join(short_groups)
        )
    if len(arrays) < 2:
        raise MathOperationError("Grouped statistics require at least two valid groups.")
    return arrays


def _holm_adjusted_p_values(p_values: list[float]) -> list[float]:
    """Return Holm-Bonferroni adjusted p-values in original order."""
    if not p_values:
        return []
    adjusted = [np.nan] * len(p_values)
    sorted_indexes = sorted(range(len(p_values)), key=lambda index: p_values[index])
    running_max = 0.0
    total = len(p_values)
    for rank, original_index in enumerate(sorted_indexes):
        adjusted_value = min((total - rank) * p_values[original_index], 1.0)
        running_max = max(running_max, adjusted_value)
        adjusted[original_index] = running_max
    return adjusted


def _rank_biserial_from_u(u_statistic: float, first_count: int, second_count: int) -> float:
    """Return rank-biserial effect size from a Mann-Whitney U statistic."""
    denominator = first_count * second_count
    if denominator <= 0:
        return np.nan
    return 2.0 * u_statistic / denominator - 1.0


def _safe_metric_label(label: str) -> str:
    """Return a compact label safe for metric names."""
    cleaned = "".join(character if character.isalnum() else "_" for character in str(label).strip().lower())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "group"


def _numeric_frame(
    frame: pd.DataFrame,
    column_labels: dict[str, str],
    minimum_columns: int,
) -> pd.DataFrame:
    """Coerce selected columns to numeric values while preserving row alignment."""
    if frame.empty or len(frame.columns) < minimum_columns:
        raise MathOperationError(f"Choose at least {minimum_columns} columns for this statistics operation.")

    columns: dict[object, pd.Series] = {}
    for column in frame.columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        validate_numeric_column_metadata(frame, column, values)
        columns[column] = values
    numeric = pd.DataFrame(columns).replace([np.inf, -np.inf], np.nan)
    empty_columns = [
        _column_label(column_labels, column)
        for column in numeric.columns
        if numeric[column].notna().sum() == 0
    ]
    if empty_columns:
        raise MathOperationError(
            "Selected statistics columns need numeric values: " + ", ".join(empty_columns)
        )
    return numeric


def _column_label(column_labels: dict[str, str], column: object) -> str:
    """Return the display label for a selected source column."""
    column_name = str(column)
    return column_labels.get(column_name, column_name)


def _numeric_series(series: pd.Series | None, label: str, minimum_points: int) -> pd.Series:
    """Coerce a source series to numeric values while preserving row indexes."""
    if series is None:
        raise MathOperationError(f"Choose a data column for {label}.")
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if values.notna().sum() < minimum_points:
        raise MathOperationError(f"{label} needs at least {minimum_points} numeric value(s).")
    return values


def _clean_values(series: pd.Series, label: str, minimum_points: int) -> pd.Series:
    """Return non-missing numeric values and validate count."""
    values = series.dropna()
    if len(values) < minimum_points:
        raise MathOperationError(f"{label} needs at least {minimum_points} numeric value(s).")
    return values


def _aligned_pair(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    minimum_points: int,
) -> pd.DataFrame:
    """Return row-position-aligned numeric pairs with missing rows removed."""
    paired = pd.DataFrame(
        {
            "primary": x.reset_index(drop=True),
            "secondary": y.reset_index(drop=True),
        }
    ).dropna()
    if len(paired) < minimum_points:
        raise MathOperationError(
            f"{x_label} and {y_label} need at least {minimum_points} aligned numeric pair(s)."
        )
    return paired


def _independent_pair(
    x: pd.Series,
    y: pd.Series,
    x_label: str,
    y_label: str,
    minimum_points: int,
) -> tuple[pd.Series, pd.Series]:
    """Return independent non-missing samples from two columns."""
    x_values = _clean_values(x, x_label, minimum_points)
    y_values = _clean_values(y, y_label, minimum_points)
    return x_values, y_values


def _report_frame(
    operation_key: str,
    primary_label: str,
    secondary_label: str,
    rows: list[dict[str, object]],
) -> pd.DataFrame:
    """Return rows in the common metric-report result shape."""
    operation = STATISTIC_OPERATIONS[operation_key]
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        normalized_rows.append(
            {
                "operation": operation.label,
                "primary": primary_label,
                "secondary": secondary_label,
                "metric": row.get("metric", ""),
                "value": _normalize_number(row.get("value")),
                "p_value": _normalize_number(row.get("p_value")),
                "notes": row.get("notes", ""),
            }
        )
    return pd.DataFrame(normalized_rows)


def _section_or_error(
    builder: Callable[[], pd.DataFrame],
    operation_key: str,
    primary_label: str,
    secondary_label: str = "",
) -> pd.DataFrame:
    """Return a complete-report section, or a note row if that section cannot run."""
    try:
        return builder()
    except (MathOperationError, ValueError) as exc:
        return _report_frame(
            operation_key,
            primary_label,
            secondary_label,
            [_metric("section_unavailable", np.nan, notes=str(exc))],
        )


def _concat_reports(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate report sections into one result frame."""
    return pd.concat(frames, ignore_index=True)


def _metric(
    metric: str,
    value: object,
    p_value: object = np.nan,
    notes: str = "",
) -> dict[str, object]:
    """Return one common metric row dictionary."""
    return {"metric": metric, "value": value, "p_value": p_value, "notes": notes}


def _normalize_number(value: object) -> object:
    """Convert NumPy scalar values into plain Python values for display/export."""
    if isinstance(value, np.generic):
        return value.item()
    return value
