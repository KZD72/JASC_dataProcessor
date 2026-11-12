"""Shared numerical tables backing statistics companion plots."""
from __future__ import annotations
import re
import numpy as np
import pandas as pd
from core.workspace import Dataset, Workspace
from math_engine.calculus import validate_numeric_column_metadata

class StatisticsPlotData:
    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    def _statistics_normal_curve_dataset(self, dataset: Dataset, column: str) -> Dataset | None:
        """Create a normal PDF overlay dataset for a histogram when possible."""
        values = self._statistics_numeric_values(dataset, column)
        if len(values) < 2:
            return None
        mean = float(values.mean())
        std = float(values.std(ddof=1))
        if not np.isfinite(std) or std <= 0:
            return None
        x_min = float(values.min())
        x_max = float(values.max())
        if x_min == x_max:
            return None
        x_values = np.linspace(x_min, x_max, 200)
        density = np.exp(-0.5 * ((x_values - mean) / std) ** 2) / (std * np.sqrt(2 * np.pi))
        return self._workspace.add_dataset(
            f"{dataset.name}_{column}_normal_curve",
            pd.DataFrame({"value": x_values, "normal_density": density}),
        )


    def _statistics_comparison_dataset(
        self,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset,
        secondary_column: str,
        result_name: str,
    ) -> Dataset:
        """Create a two-column dataset suitable for box/violin comparisons."""
        primary_values = self._statistics_numeric_values(primary_dataset, primary_column).reset_index(drop=True)
        secondary_values = self._statistics_numeric_values(secondary_dataset, secondary_column).reset_index(drop=True)
        row_count = max(len(primary_values), len(secondary_values))
        primary_label = self._statistics_column_label(primary_dataset, primary_column)
        secondary_label = self._statistics_column_label(secondary_dataset, secondary_column)
        if primary_label == secondary_label:
            secondary_label = f"{secondary_label} 2"
        frame = pd.DataFrame(
            {
                primary_label: primary_values.reindex(range(row_count)),
                secondary_label: secondary_values.reindex(range(row_count)),
            }
        )
        return self._workspace.add_dataset(f"{result_name}_plot_data", frame)


    def _statistics_group_distribution_dataset(
        self,
        value_dataset: Dataset,
        value_column: str,
        group_dataset: Dataset,
        group_column: str,
        result_name: str,
    ) -> Dataset:
        """Create a wide dataset with one numeric column per group."""
        values = self._statistics_numeric_series(value_dataset, value_column)
        if group_column not in group_dataset.frame.columns:
            raise ValueError(f"Column '{group_column}' is no longer available.")
        groups = group_dataset.frame[group_column].reset_index(drop=True)
        paired = pd.DataFrame(
            {
                "value": values.reset_index(drop=True),
                "group": groups,
            }
        ).dropna(subset=["value", "group"])
        paired["group"] = paired["group"].astype(str).str.strip()
        paired = paired[paired["group"] != ""]
        if paired.empty:
            raise ValueError("No complete numeric/group rows are available for the grouped plot.")

        grouped_values: dict[str, pd.Series] = {}
        for group_name, group_frame in paired.groupby("group", sort=True):
            column_name = self._unique_plot_data_column(str(group_name), grouped_values)
            grouped_values[column_name] = group_frame["value"].astype(float).reset_index(drop=True)
        if len(grouped_values) < 2:
            raise ValueError("Grouped plots require at least two groups.")

        row_count = max(len(values) for values in grouped_values.values())
        frame = pd.DataFrame(
            {
                column_name: values.reindex(range(row_count))
                for column_name, values in grouped_values.items()
            }
        )
        return self._workspace.add_dataset(f"{result_name}_group_plot_data", frame)


    @staticmethod
    def _unique_plot_data_column(base_name: str, columns: dict[str, pd.Series]) -> str:
        """Return a unique column name for generated plot-helper datasets."""
        clean_name = base_name.strip() or "Group"
        if clean_name not in columns:
            return clean_name
        suffix = 2
        while f"{clean_name} {suffix}" in columns:
            suffix += 1
        return f"{clean_name} {suffix}"


    def _statistics_correlation_heatmap_dataset(
        self,
        dataset: Dataset,
        columns: list[str],
        result_name: str,
    ) -> Dataset:
        """Create X/Y/Z helper data for a Pearson correlation heatmap."""
        numeric = pd.DataFrame(
            {
                column: self._statistics_numeric_series(dataset, column)
                for column in columns
            }
        )
        correlation = numeric.corr(method="pearson", min_periods=2)
        rows: list[dict[str, object]] = []
        has_off_diagonal_value = False
        for row_index, row_column in enumerate(columns):
            for column_index, column in enumerate(columns):
                value = correlation.loc[row_column, column]
                if pd.isna(value):
                    continue
                if row_index != column_index:
                    has_off_diagonal_value = True
                rows.append(
                    {
                        "column_index": float(column_index),
                        "row_index": float(row_index),
                        "pearson_r": float(value),
                        "column": column,
                        "row": row_column,
                    }
                )
        if not rows or not has_off_diagonal_value:
            raise ValueError("Correlation heatmap requires at least two aligned numeric values.")
        return self._workspace.add_dataset(
            f"{result_name}_correlation_heatmap",
            pd.DataFrame(rows),
        )


    def _statistics_pca_variance_dataset(self, result_dataset: Dataset) -> Dataset:
        """Create component/variance helper data from a PCA statistics result."""
        required_columns = {"metric", "value"}
        if not required_columns.issubset(result_dataset.frame.columns):
            raise ValueError("PCA variance plot requires a statistics result with metric and value columns.")

        rows: list[dict[str, float]] = []
        for _index, row in result_dataset.frame.iterrows():
            metric = str(row.get("metric", ""))
            match = re.fullmatch(r"pc(\d+)_explained_variance_ratio", metric)
            if match is None:
                continue
            value = pd.to_numeric(pd.Series([row.get("value")]), errors="coerce").iloc[0]
            if pd.isna(value):
                continue
            rows.append(
                {
                    "component": float(match.group(1)),
                    "explained_variance_ratio": float(value),
                }
            )
        if not rows:
            raise ValueError("This statistics result does not contain PCA explained-variance rows.")
        return self._workspace.add_dataset(
            f"{result_dataset.name}_pca_variance",
            pd.DataFrame(rows),
        )


    def _statistics_bland_altman_dataset(
        self,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset,
        secondary_column: str,
        result_name: str,
    ) -> Dataset:
        """Create paired mean/difference data for a Bland-Altman companion plot."""
        paired = self._statistics_aligned_pair(
            primary_dataset,
            primary_column,
            secondary_dataset,
            secondary_column,
            minimum_points=2,
        )
        mean_values = paired.mean(axis=1)
        difference_values = paired["primary"] - paired["secondary"]
        frame = pd.DataFrame(
            {
                "mean": mean_values.to_numpy(dtype=float),
                "difference": difference_values.to_numpy(dtype=float),
            }
        )
        return self._workspace.add_dataset(f"{result_name}_bland_altman", frame)


    def _statistics_regression_line_dataset(
        self,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset,
        secondary_column: str,
        result_dataset: Dataset,
    ) -> Dataset:
        """Create an OLS regression line dataset from aligned numeric pairs."""
        paired = self._statistics_aligned_pair(
            primary_dataset,
            primary_column,
            secondary_dataset,
            secondary_column,
            minimum_points=2,
        )
        x_min = float(paired["primary"].min())
        x_max = float(paired["primary"].max())
        if x_min == x_max:
            raise ValueError("Regression companion plot needs non-constant primary X values.")
        slope, intercept = np.polyfit(
            paired["primary"].to_numpy(dtype=float),
            paired["secondary"].to_numpy(dtype=float),
            1,
        )
        x_values = np.linspace(x_min, x_max, 200)
        frame = pd.DataFrame({"x": x_values, "fit": slope * x_values + intercept})
        return self._workspace.add_dataset(f"{result_dataset.name}_regression_line", frame)


    @staticmethod
    def _statistics_numeric_values(dataset: Dataset, column: str) -> pd.Series:
        """Return finite numeric values for one dataset column."""
        if column not in dataset.frame.columns:
            raise ValueError(f"Column '{column}' is no longer available.")
        values = pd.to_numeric(dataset.frame[column], errors="coerce")
        validate_numeric_column_metadata(dataset.frame, column, values)
        values = values[
            values.notna()
            & (values != float("inf"))
            & (values != float("-inf"))
        ]
        if values.empty:
            raise ValueError(f"{dataset.name}: {column} has no numeric values to plot.")
        return values.astype(float)


    @staticmethod
    def _statistics_numeric_series(dataset: Dataset, column: str) -> pd.Series:
        """Return a numeric series preserving blanks as NaN for alignment."""
        if column not in dataset.frame.columns:
            raise ValueError(f"Column '{column}' is no longer available.")
        values = pd.to_numeric(dataset.frame[column], errors="coerce")
        validate_numeric_column_metadata(dataset.frame, column, values)
        return values.replace([np.inf, -np.inf], np.nan)


    def _statistics_aligned_pair(
        self,
        primary_dataset: Dataset,
        primary_column: str,
        secondary_dataset: Dataset,
        secondary_column: str,
        minimum_points: int,
    ) -> pd.DataFrame:
        """Return row-position-aligned numeric values for two columns."""
        primary_values = self._statistics_numeric_series(primary_dataset, primary_column)
        secondary_values = self._statistics_numeric_series(secondary_dataset, secondary_column)
        paired = pd.DataFrame(
            {
                "primary": primary_values.reset_index(drop=True),
                "secondary": secondary_values.reset_index(drop=True),
            }
        ).dropna()
        if len(paired) < minimum_points:
            raise ValueError(f"Need at least {minimum_points} aligned numeric pair(s) to plot this statistic.")
        return paired


    @staticmethod
    def _statistics_column_label(dataset: Dataset, column: str) -> str:
        """Return a compact label for statistics companion plots."""
        metadata = dataset.column_metadata.get(column)
        label = metadata.long_name if metadata is not None and metadata.long_name else column
        if metadata is not None and metadata.unit:
            label = f"{label} ({metadata.unit})"
        return f"{dataset.name}: {label}"

