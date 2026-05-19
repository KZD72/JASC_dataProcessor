"""Statistical analysis helpers for workspace datasets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from math_engine.calculus import MathOperationError


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

    if operation.scope == "pair" and secondary is None:
        raise MathOperationError("Choose a second data column for this statistics operation.")

    x = _numeric_series(primary, primary_label, minimum_points=1)
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

    anderson = stats.anderson(values, dist="norm")
    rows.append(_metric("anderson_darling_statistic", anderson.statistic))
    for level, critical in zip(anderson.significance_level, anderson.critical_values):
        rows.append(_metric(f"anderson_critical_{level:g}pct", float(critical)))
    return _report_frame(operation_key, label, "", rows)


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
