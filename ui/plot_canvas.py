"""Matplotlib canvas integration for workspace plotting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget

from core.workspace import Workspace


@dataclass(frozen=True, slots=True)
class PlotSeries:
    """A single X/Y mapping from workspace columns."""

    x_dataset: str
    x_column: str
    y_dataset: str
    y_column: str
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

    @property
    def label(self) -> str:
        """Return a readable legend label."""
        if self.custom_label:
            return self.custom_label
        if self.x_dataset == self.y_dataset:
            return f"{self.y_dataset}: {self.y_column}"
        return f"{self.y_dataset}: {self.y_column} vs {self.x_dataset}: {self.x_column}"


@dataclass(frozen=True, slots=True)
class PlotLocator:
    """Marker request for an interpolated Y value on a plotted series."""

    series_index: int
    x_value: float
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
    ) -> PlotResult:
        """Render selected workspace series onto the axes."""
        self.figure.set_size_inches(figure_width, figure_height, forward=True)
        self._remove_right_axes()
        self.axes.clear()

        skipped_messages: list[str] = []
        located_points: list[LocatedPoint] = []
        plotted_count = 0
        uses_right_axis = any(series.y_axis == "right" for series in series_list)
        if uses_right_axis:
            self.right_axes = self.axes.twinx()

        plotted_series_values: dict[int, tuple[pd.Series, pd.Series, PlotSeries]] = {}

        for series_index, series in enumerate(series_list):
            series_y_scale = right_y_scale if series.y_axis == "right" else y_scale
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

            target_axes = self.right_axes if series.y_axis == "right" and self.right_axes else self.axes
            
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
        )
        skipped_messages.extend(locator_messages)

        if plotted_count:
            self._draw_legend(legend_enabled, legend_position)
        else:
            self._draw_empty_state(clear_axes=False)

        self.canvas.draw_idle()
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
    ) -> tuple[list[str], list[LocatedPoint]]:
        """Draw locator markers and return interpolation summaries."""
        messages: list[str] = []
        located_points: list[LocatedPoint] = []

        for locator_index, locator in enumerate(locators):
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
