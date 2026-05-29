"""Matplotlib canvas integration for workspace plotting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from matplotlib import style as mpl_style
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget
from scipy.interpolate import CloughTocher2DInterpolator, LinearNDInterpolator, SmoothBivariateSpline

from core.workspace import Workspace

try:
    import scienceplots  # noqa: F401
    SCIENCEPLOTS_AVAILABLE = True
except ImportError:
    SCIENCEPLOTS_AVAILABLE = False


_SURFACE_PLOT_TYPES = {"heatmap", "contour", "contourf"}


@dataclass(frozen=True, slots=True)
class PlotSeries:
    """A single X/Y mapping from workspace columns."""

    x_dataset: str
    x_column: str
    y_dataset: str
    y_column: str
    z_dataset: str = ""
    z_column: str = ""
    plot_type: str = "line"
    x_err_column: str = ""
    y_err_column: str = ""
    color: str = ""
    line_style: str = "-"
    marker: str = ""
    y_axis: str = "left"
    custom_label: str = ""
    line_width: float = 1.8
    marker_size: float = 6.0
    lower_column: str = ""
    upper_column: str = ""
    fill_alpha: float = 0.18
    bar_width: float = 0.8
    histogram_bins: int = 20
    histogram_density: bool = False
    histogram_cumulative: bool = False
    distribution_columns: tuple[str, ...] = ()
    distribution_show_mean: bool = False
    distribution_show_median: bool = True
    distribution_show_outliers: bool = True
    interpolation_method: str = "linear"
    grid_resolution: int = 120

    @property
    def label(self) -> str:
        """Return a readable legend label."""
        if self.custom_label:
            return self.custom_label
        if self.plot_type in _SURFACE_PLOT_TYPES:
            z_column = self.z_column or self.y_column
            return f"{self.z_dataset or self.y_dataset}: {z_column}"
        if self.plot_type in {"box", "violin"}:
            columns = list(self.distribution_columns) or ([self.y_column] if self.y_column else [])
            if len(columns) > 1:
                return f"{self.y_dataset}: {len(columns)} distributions"
            if columns:
                return f"{self.y_dataset}: {columns[0]}"
        if self.x_dataset == self.y_dataset:
            return f"{self.y_dataset}: {self.y_column}"
        return f"{self.y_dataset}: {self.y_column} vs {self.x_dataset}: {self.x_column}"


@dataclass(frozen=True, slots=True)
class PlotLocator:
    """Marker request for an interpolated Y value on a plotted series."""

    series_index: int
    x_value: float
    y_value: float | None = None
    marker: str = "o"
    size: float = 70.0
    color: str = "tab:red"


@dataclass(frozen=True, slots=True)
class LocatedPoint:
    """Interpolated point calculated from a plot locator."""

    locator_index: int
    series_index: int
    series_label: str
    x_value: float
    y_value: float
    y_axis: str
    z_value: float | None = None


@dataclass(frozen=True, slots=True)
class _SurfaceValues:
    """Prepared X/Y/Z values for an interpolated 2D plot."""

    x_values: np.ndarray
    y_values: np.ndarray
    z_values: np.ndarray
    series: PlotSeries


@dataclass(frozen=True, slots=True)
class PlotResult:
    """Summary of a completed plot render."""

    plotted_count: int
    skipped_messages: list[str]
    located_points: list[LocatedPoint]


class PlotCanvas(QWidget):
    """A QWidget wrapping a Matplotlib FigureCanvas and navigation toolbar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the Matplotlib figure, toolbar, and empty plot placeholder."""
        super().__init__(parent)

        self.figure = Figure(figsize=(7.0, 4.8), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.axes = self.figure.add_subplot(111)
        self.right_axes: Any | None = None
        self._draw_empty_state()

        layout = QVBoxLayout(self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

    def plot_series(
        self,
        workspace: Workspace,
        series_list: list[PlotSeries],
        title: str = "",
        x_label: str = "",
        y_label: str = "",
        right_y_label: str = "",
        x_scale: str = "linear",
        y_scale: str = "linear",
        right_y_scale: str = "linear",
        x_limits: tuple[float | None, float | None] = (None, None),
        y_limits: tuple[float | None, float | None] = (None, None),
        right_y_limits: tuple[float | None, float | None] = (None, None),
        grid_enabled: bool = True,
        legend_enabled: bool = True,
        legend_position: str = "best",
        locators: list[PlotLocator] | None = None,
        figure_width: float = 7.0,
        figure_height: float = 4.8,
        style_names: list[str] | None = None,
    ) -> PlotResult:
        """Render selected workspace series onto the axes."""
        try:
            with mpl_style.context(style_names or []):
                return self._plot_series_with_style(
                    workspace=workspace,
                    series_list=series_list,
                    title=title,
                    x_label=x_label,
                    y_label=y_label,
                    right_y_label=right_y_label,
                    x_scale=x_scale,
                    y_scale=y_scale,
                    right_y_scale=right_y_scale,
                    x_limits=x_limits,
                    y_limits=y_limits,
                    right_y_limits=right_y_limits,
                    grid_enabled=grid_enabled,
                    legend_enabled=legend_enabled,
                    legend_position=legend_position,
                    locators=locators,
                    figure_width=figure_width,
                    figure_height=figure_height,
                )
        except (OSError, RuntimeError) as exc:
            return PlotResult(
                plotted_count=0,
                skipped_messages=[f"Plot style/rendering unavailable: {exc}"],
                located_points=[],
            )

    def _plot_series_with_style(
        self,
        workspace: Workspace,
        series_list: list[PlotSeries],
        title: str,
        x_label: str,
        y_label: str,
        right_y_label: str,
        x_scale: str,
        y_scale: str,
        right_y_scale: str,
        x_limits: tuple[float | None, float | None],
        y_limits: tuple[float | None, float | None],
        right_y_limits: tuple[float | None, float | None],
        grid_enabled: bool,
        legend_enabled: bool,
        legend_position: str,
        locators: list[PlotLocator] | None,
        figure_width: float,
        figure_height: float,
    ) -> PlotResult:
        """Render selected workspace series with active Matplotlib style settings."""
        self._remove_right_axes()
        self.figure.clear()
        self.figure.set_constrained_layout(True)
        self.figure.set_size_inches(figure_width, figure_height, forward=True)
        self.axes = self.figure.add_subplot(111)
        self.right_axes = None

        skipped_messages: list[str] = []
        located_points: list[LocatedPoint] = []
        plotted_count = 0
        uses_right_axis = any(series.y_axis == "right" for series in series_list)
        if uses_right_axis:
            self.right_axes = self.axes.twinx()

        plotted_series_values: dict[int, tuple[pd.Series, pd.Series, PlotSeries]] = {}
        plotted_surface_values: dict[int, _SurfaceValues] = {}

        for series_index, series in enumerate(series_list):
            series_y_scale = right_y_scale if series.y_axis == "right" else y_scale
            target_axes = self.right_axes if series.y_axis == "right" and self.right_axes else self.axes
            if series.plot_type in _SURFACE_PLOT_TYPES:
                try:
                    surface_values = self._surface_values(
                        workspace,
                        series,
                        x_scale=x_scale,
                        y_scale=y_scale,
                    )
                    grid_x, grid_y, grid_z = self._interpolated_surface_grid(surface_values)
                    self._draw_surface_by_type(
                        target_axes=self.axes,
                        series=series,
                        grid_x=grid_x,
                        grid_y=grid_y,
                        grid_z=grid_z,
                    )
                except (KeyError, ValueError) as exc:
                    skipped_messages.append(f"{series.label}: {exc}")
                    continue

                plotted_surface_values[series_index] = surface_values
                plotted_count += 1
                continue

            if series.plot_type in {"box", "violin"}:
                try:
                    values_by_column, column_labels = self._distribution_values(
                        workspace,
                        series,
                        y_scale=series_y_scale,
                    )
                except (KeyError, ValueError) as exc:
                    skipped_messages.append(f"{series.label}: {exc}")
                    continue

                self._draw_distribution_by_type(
                    target_axes=target_axes,
                    series=series,
                    values_by_column=values_by_column,
                    column_labels=column_labels,
                )
                plotted_count += 1
                continue

            try:
                x_values, y_values, x_err, y_err = self._series_values(
                    workspace,
                    series,
                    x_scale=x_scale,
                    y_scale=series_y_scale,
                )
            except (KeyError, ValueError) as exc:
                skipped_messages.append(f"{series.label}: {exc}")
                continue

            if x_values.empty or y_values.empty:
                skipped_messages.append(f"{series.label}: no numeric points to plot")
                continue

            plot_kwargs = {
                "label": series.label,
                "linestyle": series.line_style,
                "marker": series.marker,
                "linewidth": series.line_width,
                "markersize": series.marker_size,
            }
            if series.color:
                plot_kwargs["color"] = series.color

            self._draw_series_by_type(
                target_axes=target_axes,
                series=series,
                x_values=x_values,
                y_values=y_values,
                x_err=x_err,
                y_err=y_err,
                plot_kwargs=plot_kwargs,
            )
                
            self._draw_confidence_band(
                workspace=workspace,
                series=series,
                target_axes=target_axes,
                x_scale=x_scale,
                y_scale=series_y_scale,
            )
            if series.plot_type != "histogram":
                plotted_series_values[series_index] = (x_values, y_values, series)
            plotted_count += 1

        self.axes.set_title(title)
        self.axes.set_xlabel(x_label)
        self.axes.set_ylabel(y_label)
        self.axes.set_xscale(x_scale)
        self.axes.set_yscale(y_scale)
        self.axes.grid(grid_enabled, alpha=0.25)

        if self.right_axes is not None:
            self.right_axes.set_ylabel(right_y_label)
            self.right_axes.set_yscale(right_y_scale)
            self.right_axes.grid(False)

        skipped_messages.extend(self._apply_limits(self.axes, "x", x_limits, x_scale, "X"))
        skipped_messages.extend(self._apply_limits(self.axes, "y", y_limits, y_scale, "Y"))
        if self.right_axes is not None:
            skipped_messages.extend(
                self._apply_limits(self.right_axes, "y", right_y_limits, right_y_scale, "Right Y")
            )

        locator_messages, located_points = self._draw_locators(
            locators=locators or [],
            plotted_series_values=plotted_series_values,
            plotted_surface_values=plotted_surface_values,
        )
        skipped_messages.extend(locator_messages)

        if plotted_count:
            self._draw_legend(legend_enabled, legend_position)
        else:
            self._draw_empty_state(clear_axes=False)

        self.canvas.draw()
        return PlotResult(
            plotted_count=plotted_count,
            skipped_messages=skipped_messages,
            located_points=located_points,
        )

    def clear_plot(self) -> None:
        """Clear the plot surface."""
        self._draw_empty_state()
        self.canvas.draw_idle()

    def _series_values(
        self,
        workspace: Workspace,
        series: PlotSeries,
        x_scale: str,
        y_scale: str,
    ) -> tuple[pd.Series, pd.Series, pd.Series | None, pd.Series | None]:
        """Return aligned numeric X/Y values and their errors for a plot series."""
        y_frame = workspace.get_dataset(series.y_dataset).frame

        if series.plot_type == "histogram":
            if series.y_column not in y_frame.columns:
                raise ValueError(f"missing value column '{series.y_column}'")
            y_values = pd.to_numeric(y_frame[series.y_column], errors="coerce").dropna()
            if x_scale == "log":
                y_values = y_values[y_values > 0]
            if y_values.empty:
                return pd.Series(dtype=float), pd.Series(dtype=float), None, None
            x_values = pd.Series(np.arange(len(y_values)), dtype=float)
            return x_values, y_values.reset_index(drop=True), None, None

        x_frame = workspace.get_dataset(series.x_dataset).frame
        if series.x_column not in x_frame.columns:
            raise ValueError(f"missing X column '{series.x_column}'")
        if series.y_column not in y_frame.columns:
            raise ValueError(f"missing Y column '{series.y_column}'")

        x_values = pd.to_numeric(x_frame[series.x_column], errors="coerce")
        y_values = pd.to_numeric(y_frame[series.y_column], errors="coerce")
        
        cols = {
            "x": x_values,
            "y": y_values,
        }
        
        if series.x_err_column and series.x_err_column in x_frame.columns:
            cols["x_err"] = pd.to_numeric(x_frame[series.x_err_column], errors="coerce")
        if series.y_err_column and series.y_err_column in y_frame.columns:
            cols["y_err"] = pd.to_numeric(y_frame[series.y_err_column], errors="coerce")

        # Find the minimum valid length across all provided columns
        point_count = min(len(col) for col in cols.values())
        if point_count == 0:
            return pd.Series(dtype=float), pd.Series(dtype=float), None, None

        # Truncate to matching length
        for key in cols:
            cols[key] = cols[key].iloc[:point_count].to_numpy()

        aligned = pd.DataFrame(cols).dropna()

        if x_scale == "log":
            aligned = aligned[aligned["x"] > 0]
        if y_scale == "log":
            aligned = aligned[aligned["y"] > 0]

        if aligned.empty:
            return pd.Series(dtype=float), pd.Series(dtype=float), None, None

        x_err_out = aligned["x_err"] if "x_err" in aligned.columns else None
        y_err_out = aligned["y_err"] if "y_err" in aligned.columns else None
        return aligned["x"], aligned["y"], x_err_out, y_err_out

    def _surface_values(
        self,
        workspace: Workspace,
        series: PlotSeries,
        x_scale: str,
        y_scale: str,
    ) -> _SurfaceValues:
        """Return aligned numeric X/Y/Z values for a 2D interpolated map."""
        x_frame = workspace.get_dataset(series.x_dataset).frame
        y_frame = workspace.get_dataset(series.y_dataset).frame
        z_dataset_name = series.z_dataset or series.y_dataset
        z_frame = workspace.get_dataset(z_dataset_name).frame

        if series.x_column not in x_frame.columns:
            raise ValueError(f"missing X coordinate column '{series.x_column}'")
        if series.y_column not in y_frame.columns:
            raise ValueError(f"missing Y coordinate column '{series.y_column}'")
        if not series.z_column:
            raise ValueError("choose a Z/value column")
        if series.z_column not in z_frame.columns:
            raise ValueError(f"missing Z/value column '{series.z_column}'")

        columns = {
            "x": pd.to_numeric(x_frame[series.x_column], errors="coerce"),
            "y": pd.to_numeric(y_frame[series.y_column], errors="coerce"),
            "z": pd.to_numeric(z_frame[series.z_column], errors="coerce"),
        }
        point_count = min(len(column) for column in columns.values())
        if point_count == 0:
            raise ValueError("no numeric X/Y/Z points to plot")

        aligned = pd.DataFrame(
            {
                key: column.iloc[:point_count].to_numpy()
                for key, column in columns.items()
            }
        ).dropna()

        if x_scale == "log":
            aligned = aligned[aligned["x"] > 0]
        if y_scale == "log":
            aligned = aligned[aligned["y"] > 0]
        if aligned.empty:
            raise ValueError("no numeric X/Y/Z points remain after scale filtering")

        points = aligned.groupby(["x", "y"], as_index=False)["z"].mean()
        if len(points) < 3:
            raise ValueError("2D interpolation needs at least three distinct X/Y points")
        if points["x"].nunique() < 2 or points["y"].nunique() < 2:
            raise ValueError("2D interpolation needs at least two distinct X and Y values")

        return _SurfaceValues(
            x_values=points["x"].to_numpy(dtype=float),
            y_values=points["y"].to_numpy(dtype=float),
            z_values=points["z"].to_numpy(dtype=float),
            series=series,
        )

    def _interpolated_surface_grid(
        self,
        surface_values: _SurfaceValues,
    ) -> tuple[np.ndarray, np.ndarray, np.ma.MaskedArray]:
        """Interpolate scattered X/Y/Z points onto a regular grid."""
        resolution = max(10, min(int(surface_values.series.grid_resolution), 500))
        grid_x_values = np.linspace(
            float(np.min(surface_values.x_values)),
            float(np.max(surface_values.x_values)),
            resolution,
        )
        grid_y_values = np.linspace(
            float(np.min(surface_values.y_values)),
            float(np.max(surface_values.y_values)),
            resolution,
        )
        grid_x, grid_y = np.meshgrid(grid_x_values, grid_y_values)
        grid_z = self._evaluate_surface(
            surface_values=surface_values,
            x_values=grid_x.ravel(),
            y_values=grid_y.ravel(),
        ).reshape(grid_x.shape)
        return grid_x, grid_y, np.ma.masked_invalid(grid_z)

    def _evaluate_surface(
        self,
        surface_values: _SurfaceValues,
        x_values: np.ndarray,
        y_values: np.ndarray,
    ) -> np.ndarray:
        """Evaluate a selected 2D interpolation method at X/Y coordinates."""
        method = surface_values.series.interpolation_method or "linear"
        points = np.column_stack((surface_values.x_values, surface_values.y_values))
        target_points = np.column_stack((x_values, y_values))

        try:
            if method == "cubic_spline":
                spline = SmoothBivariateSpline(
                    surface_values.x_values,
                    surface_values.y_values,
                    surface_values.z_values,
                    kx=3,
                    ky=3,
                    s=0,
                )
                return spline.ev(x_values, y_values)

            if method == "piecewise_cubic":
                interpolator = CloughTocher2DInterpolator(points, surface_values.z_values)
            else:
                interpolator = LinearNDInterpolator(points, surface_values.z_values)
            return np.asarray(interpolator(target_points), dtype=float)
        except Exception as exc:
            label = self._interpolation_method_label(method)
            raise ValueError(f"{label} interpolation failed: {exc}") from exc

    @staticmethod
    def _interpolation_method_label(method: str) -> str:
        """Return a readable interpolation method name."""
        labels = {
            "linear": "Linear",
            "cubic_spline": "Cubic spline",
            "piecewise_cubic": "Piecewise cubic",
        }
        return labels.get(method, method or "Linear")

    def _draw_series_by_type(
        self,
        target_axes: Any,
        series: PlotSeries,
        x_values: pd.Series,
        y_values: pd.Series,
        x_err: pd.Series | None,
        y_err: pd.Series | None,
        plot_kwargs: dict[str, object],
    ) -> None:
        """Draw one aligned series using its explicit plot type."""
        plot_type = series.plot_type or "line"
        if plot_type == "scatter":
            scatter_kwargs: dict[str, object] = {
                "label": series.label,
                "marker": series.marker or "o",
                "s": series.marker_size**2,
            }
            if series.color:
                scatter_kwargs["color"] = series.color
            target_axes.scatter(x_values, y_values, **scatter_kwargs)
            return

        if plot_type == "line_marker":
            plot_kwargs["marker"] = series.marker or "o"
            plot_kwargs["linestyle"] = series.line_style or "-"
            target_axes.plot(x_values, y_values, **plot_kwargs)
            return

        if plot_type == "errorbar" or (
            plot_type in {"line", "line_marker", "scatter"} and (x_err is not None or y_err is not None)
        ):
            marker = series.marker or "o"
            target_axes.errorbar(
                x_values,
                y_values,
                xerr=x_err,
                yerr=y_err,
                fmt=marker,
                label=series.label,
                linestyle=series.line_style,
                linewidth=series.line_width,
                markersize=series.marker_size,
                color=series.color if series.color else None,
            )
            return

        if plot_type == "bar":
            target_axes.bar(
                x_values,
                y_values,
                width=series.bar_width,
                label=series.label,
                color=series.color if series.color else None,
            )
            return

        if plot_type == "barh":
            target_axes.barh(
                x_values,
                y_values,
                height=series.bar_width,
                label=series.label,
                color=series.color if series.color else None,
            )
            return

        if plot_type == "area":
            line_kwargs = dict(plot_kwargs)
            line_kwargs["label"] = "_nolegend_"
            target_axes.plot(x_values, y_values, **line_kwargs)
            target_axes.fill_between(
                x_values,
                y_values,
                0,
                label=series.label,
                color=series.color if series.color else None,
                alpha=series.fill_alpha,
            )
            return

        if plot_type == "histogram":
            target_axes.hist(
                y_values,
                bins=max(series.histogram_bins, 1),
                density=series.histogram_density,
                cumulative=series.histogram_cumulative,
                label=series.label,
                color=series.color if series.color else None,
                alpha=series.fill_alpha,
            )
            return

        target_axes.plot(x_values, y_values, **plot_kwargs)

    def _draw_surface_by_type(
        self,
        target_axes: Any,
        series: PlotSeries,
        grid_x: np.ndarray,
        grid_y: np.ndarray,
        grid_z: np.ma.MaskedArray,
    ) -> None:
        """Draw an interpolated X/Y/Z surface using its explicit plot type."""
        if grid_z.count() == 0:
            raise ValueError("interpolation produced no plottable grid values")

        if series.plot_type == "contour":
            mappable = target_axes.contour(
                grid_x,
                grid_y,
                grid_z,
                levels=12,
                cmap="viridis",
            )
            target_axes.clabel(mappable, inline=True, fontsize=8)
        elif series.plot_type == "contourf":
            mappable = target_axes.contourf(
                grid_x,
                grid_y,
                grid_z,
                levels=16,
                cmap="viridis",
            )
        else:
            mappable = target_axes.pcolormesh(
                grid_x,
                grid_y,
                grid_z,
                shading="auto",
                cmap="viridis",
            )

        colorbar = self.figure.colorbar(mappable, ax=target_axes)
        colorbar.set_label(series.z_column or series.label)

    def _distribution_values(
        self,
        workspace: Workspace,
        series: PlotSeries,
        y_scale: str,
    ) -> tuple[list[pd.Series], list[str]]:
        """Return numeric values for multi-column distribution plots."""
        frame = workspace.get_dataset(series.y_dataset).frame
        columns = list(series.distribution_columns) or ([series.y_column] if series.y_column else [])
        if not columns:
            raise ValueError("choose at least one distribution column")

        values_by_column: list[pd.Series] = []
        labels: list[str] = []
        missing_columns: list[str] = []
        empty_columns: list[str] = []
        for column in columns:
            if column not in frame.columns:
                missing_columns.append(column)
                continue

            values = pd.to_numeric(frame[column], errors="coerce").dropna()
            if y_scale == "log":
                values = values[values > 0]
            if values.empty:
                empty_columns.append(column)
                continue

            values_by_column.append(values.reset_index(drop=True))
            labels.append(column)

        messages: list[str] = []
        if missing_columns:
            messages.append("missing column(s): " + ", ".join(missing_columns))
        if empty_columns:
            messages.append("empty/non-numeric column(s): " + ", ".join(empty_columns))
        if not values_by_column:
            detail = "; ".join(messages)
            raise ValueError(detail or "no numeric distribution values to plot")

        return values_by_column, labels

    def _draw_distribution_by_type(
        self,
        target_axes: Any,
        series: PlotSeries,
        values_by_column: list[pd.Series],
        column_labels: list[str],
    ) -> None:
        """Draw a box or violin distribution comparison."""
        positions = np.arange(1, len(values_by_column) + 1, dtype=float)
        color = series.color or "tab:blue"

        if series.plot_type == "box":
            median_props = {"visible": series.distribution_show_median}
            box_parts = target_axes.boxplot(
                values_by_column,
                labels=column_labels,
                positions=positions,
                patch_artist=True,
                showmeans=series.distribution_show_mean,
                showfliers=series.distribution_show_outliers,
                widths=0.7,
                medianprops=median_props,
            )
            for box in box_parts.get("boxes", []):
                box.set_facecolor(color)
                box.set_alpha(series.fill_alpha)
            for mean in box_parts.get("means", []):
                mean.set_marker("D")
                mean.set_markerfacecolor("white")
                mean.set_markeredgecolor(color)
            target_axes.plot([], [], color=color, label=series.label)
            return

        violin_parts = target_axes.violinplot(
            values_by_column,
            positions=positions,
            widths=0.8,
            showmeans=series.distribution_show_mean,
            showmedians=series.distribution_show_median,
            showextrema=series.distribution_show_outliers,
        )
        for body in violin_parts.get("bodies", []):
            body.set_facecolor(color)
            body.set_edgecolor(color)
            body.set_alpha(series.fill_alpha)
        for part_name in ("cmeans", "cmedians", "cmins", "cmaxes", "cbars"):
            part = violin_parts.get(part_name)
            if part is not None:
                part.set_color(color)
                part.set_linewidth(max(series.line_width, 1.0))

        target_axes.set_xticks(positions)
        target_axes.set_xticklabels(column_labels)
        target_axes.plot([], [], color=color, label=series.label)

    def _draw_confidence_band(
        self,
        workspace: Workspace,
        series: PlotSeries,
        target_axes: Any,
        x_scale: str,
        y_scale: str,
    ) -> None:
        """Draw an optional lower/upper confidence band for a series."""
        if not series.lower_column or not series.upper_column:
            return

        x_frame = workspace.get_dataset(series.x_dataset).frame
        y_frame = workspace.get_dataset(series.y_dataset).frame
        if series.x_column not in x_frame.columns:
            return
        if series.lower_column not in y_frame.columns or series.upper_column not in y_frame.columns:
            return

        x_values = pd.to_numeric(x_frame[series.x_column], errors="coerce")
        lower_values = pd.to_numeric(y_frame[series.lower_column], errors="coerce")
        upper_values = pd.to_numeric(y_frame[series.upper_column], errors="coerce")
        point_count = min(len(x_values), len(lower_values), len(upper_values))
        if point_count == 0:
            return

        aligned = pd.DataFrame(
            {
                "x": x_values.iloc[:point_count].to_numpy(),
                "lower": lower_values.iloc[:point_count].to_numpy(),
                "upper": upper_values.iloc[:point_count].to_numpy(),
            }
        ).dropna()

        if x_scale == "log":
            aligned = aligned[aligned["x"] > 0]
        if y_scale == "log":
            aligned = aligned[(aligned["lower"] > 0) & (aligned["upper"] > 0)]
        if aligned.empty:
            return

        fill_color = series.color or None
        target_axes.fill_between(
            aligned["x"],
            aligned["lower"],
            aligned["upper"],
            color=fill_color,
            alpha=series.fill_alpha,
            linewidth=0,
            label=f"{series.label} confidence",
        )

    def _draw_empty_state(self, clear_axes: bool = True) -> None:
        """Show the placeholder plot when no series can be rendered."""
        self._remove_right_axes()
        if clear_axes:
            self.axes.clear()

        self.axes.set_title("")
        self.axes.set_xlabel("")
        self.axes.set_ylabel("")
        self.axes.grid(True, alpha=0.25)
        self.axes.text(
            0.5,
            0.5,
            "Add a data series to plot",
            ha="center",
            va="center",
            transform=self.axes.transAxes,
            color="0.45",
        )

    def _remove_right_axes(self) -> None:
        """Remove the secondary Y axis if it exists."""
        if self.right_axes is None:
            return

        self.right_axes.remove()
        self.right_axes = None

    def _apply_limits(
        self,
        axes: Any,
        axis_name: str,
        limits: tuple[float | None, float | None],
        scale: str,
        label: str,
    ) -> list[str]:
        """Apply axis limits and return messages for invalid requests."""
        lower, upper = limits
        if lower is None and upper is None:
            return []

        if lower is not None and upper is not None and lower >= upper:
            return [f"{label} range ignored: minimum must be smaller than maximum"]

        if scale == "log":
            if lower is not None and lower <= 0:
                return [f"{label} range ignored: log scale minimum must be positive"]
            if upper is not None and upper <= 0:
                return [f"{label} range ignored: log scale maximum must be positive"]

        if axis_name == "x":
            axes.set_xlim(left=lower, right=upper)
        else:
            axes.set_ylim(bottom=lower, top=upper)
        return []

    def _draw_locators(
        self,
        locators: list[PlotLocator],
        plotted_series_values: dict[int, tuple[pd.Series, pd.Series, PlotSeries]],
        plotted_surface_values: dict[int, _SurfaceValues],
    ) -> tuple[list[str], list[LocatedPoint]]:
        """Draw locator markers and return interpolation summaries."""
        messages: list[str] = []
        located_points: list[LocatedPoint] = []

        for locator_index, locator in enumerate(locators):
            surface_values = plotted_surface_values.get(locator.series_index)
            if surface_values is not None:
                if locator.y_value is None:
                    messages.append(
                        f"{surface_values.series.label}: locator needs both X and Y coordinates"
                    )
                    continue

                try:
                    z_value = self._interpolate_z(
                        surface_values,
                        locator.x_value,
                        locator.y_value,
                    )
                except ValueError as exc:
                    messages.append(f"{surface_values.series.label}: {exc}")
                    continue

                self.axes.scatter(
                    [locator.x_value],
                    [locator.y_value],
                    marker=locator.marker,
                    s=locator.size,
                    color=locator.color,
                    edgecolors="black",
                    linewidths=0.7,
                    zorder=5,
                    label=(
                        f"{surface_values.series.label} @ "
                        f"x={locator.x_value:g}, y={locator.y_value:g}"
                    ),
                )
                located_points.append(
                    LocatedPoint(
                        locator_index=locator_index,
                        series_index=locator.series_index,
                        series_label=surface_values.series.label,
                        x_value=locator.x_value,
                        y_value=locator.y_value,
                        y_axis="left",
                        z_value=z_value,
                    )
                )
                continue

            series_values = plotted_series_values.get(locator.series_index)
            if series_values is None:
                messages.append(f"Locator skipped: series {locator.series_index + 1} is not plotted.")
                continue

            x_values, y_values, series = series_values
            try:
                y_value = self._interpolate_y(x_values, y_values, locator.x_value)
            except ValueError as exc:
                messages.append(f"{series.label}: {exc}")
                continue

            target_axes = self.right_axes if series.y_axis == "right" and self.right_axes else self.axes
            target_axes.scatter(
                [locator.x_value],
                [y_value],
                marker=locator.marker,
                s=locator.size,
                color=locator.color,
                edgecolors="black",
                linewidths=0.7,
                zorder=5,
                label=f"{series.label} @ x={locator.x_value:g}",
            )
            located_points.append(
                LocatedPoint(
                    locator_index=locator_index,
                    series_index=locator.series_index,
                    series_label=series.label,
                    x_value=locator.x_value,
                    y_value=y_value,
                    y_axis=series.y_axis,
                )
            )

        return messages, located_points

    def _interpolate_y(self, x_values: pd.Series, y_values: pd.Series, x_value: float) -> float:
        """Interpolate a Y value for a requested X coordinate."""
        points = pd.DataFrame({"x": x_values.to_numpy(), "y": y_values.to_numpy()}).dropna()
        if len(points) < 2:
            raise ValueError("locator needs at least two numeric points for interpolation")

        points = points.groupby("x", as_index=False)["y"].mean().sort_values("x")
        unique_x = points["x"].to_numpy(dtype=float)
        unique_y = points["y"].to_numpy(dtype=float)

        if len(unique_x) < 2:
            raise ValueError("locator needs at least two distinct X values")

        x_min = float(unique_x[0])
        x_max = float(unique_x[-1])
        if x_value < x_min or x_value > x_max:
            raise ValueError(f"locator x={x_value:g} is outside the data range [{x_min:g}, {x_max:g}]")

        return float(np.interp(x_value, unique_x, unique_y))

    def _interpolate_z(
        self,
        surface_values: _SurfaceValues,
        x_value: float,
        y_value: float,
    ) -> float:
        """Interpolate a Z value for requested X/Y coordinates."""
        x_min = float(np.min(surface_values.x_values))
        x_max = float(np.max(surface_values.x_values))
        y_min = float(np.min(surface_values.y_values))
        y_max = float(np.max(surface_values.y_values))
        if x_value < x_min or x_value > x_max or y_value < y_min or y_value > y_max:
            raise ValueError(
                "locator coordinate is outside the data range "
                f"x=[{x_min:g}, {x_max:g}], y=[{y_min:g}, {y_max:g}]"
            )

        z_values = self._evaluate_surface(
            surface_values=surface_values,
            x_values=np.asarray([x_value], dtype=float),
            y_values=np.asarray([y_value], dtype=float),
        )
        z_value = float(z_values[0])
        if np.isnan(z_value):
            raise ValueError("locator coordinate is outside the interpolation hull")
        return z_value

    def _draw_legend(self, legend_enabled: bool, legend_position: str) -> None:
        """Draw a combined legend for left and right axes when requested."""
        if not legend_enabled:
            return

        handles, labels = self.axes.get_legend_handles_labels()
        if self.right_axes is not None:
            right_handles, right_labels = self.right_axes.get_legend_handles_labels()
            handles.extend(right_handles)
            labels.extend(right_labels)

        if handles:
            self.axes.legend(handles, labels, loc=legend_position)
