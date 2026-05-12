"""Matplotlib canvas integration for workspace plotting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    color: str = ""
    line_style: str = "-"
    marker: str = ""
    y_axis: str = "left"

    @property
    def label(self) -> str:
        """Return a readable legend label."""
        if self.x_dataset == self.y_dataset:
            return f"{self.y_dataset}: {self.y_column}"
        return f"{self.y_dataset}: {self.y_column} vs {self.x_dataset}: {self.x_column}"


@dataclass(frozen=True, slots=True)
class PlotResult:
    """Summary of a completed plot render."""

    plotted_count: int
    skipped_messages: list[str]


class PlotCanvas(QWidget):
    """A QWidget wrapping a Matplotlib FigureCanvas and navigation toolbar."""

    def __init__(self, parent: object | None = None) -> None:
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
        vertical_guides: list[float] | None = None,
        y_guides: list[float] | None = None,
        right_y_guides: list[float] | None = None,
        figure_width: float = 7.0,
        figure_height: float = 4.8,
    ) -> PlotResult:
        """Render selected workspace series onto the axes."""
        self.figure.set_size_inches(figure_width, figure_height, forward=True)
        self._remove_right_axes()
        self.axes.clear()

        skipped_messages: list[str] = []
        plotted_count = 0
        uses_right_axis = any(series.y_axis == "right" for series in series_list) or bool(right_y_guides)
        if uses_right_axis:
            self.right_axes = self.axes.twinx()

        for series in series_list:
            series_y_scale = right_y_scale if series.y_axis == "right" else y_scale
            try:
                x_values, y_values = self._series_values(
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
            }
            if series.color:
                plot_kwargs["color"] = series.color

            target_axes = self.right_axes if series.y_axis == "right" and self.right_axes else self.axes
            target_axes.plot(x_values, y_values, **plot_kwargs)
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

        self._draw_guides(
            vertical_guides=vertical_guides or [],
            y_guides=y_guides or [],
            right_y_guides=right_y_guides or [],
        )

        if plotted_count:
            self._draw_legend()
        else:
            self._draw_empty_state(clear_axes=False)

        self.canvas.draw_idle()
        return PlotResult(plotted_count=plotted_count, skipped_messages=skipped_messages)

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
    ) -> tuple[pd.Series, pd.Series]:
        x_frame = workspace.get_dataset(series.x_dataset).frame
        y_frame = workspace.get_dataset(series.y_dataset).frame

        if series.x_column not in x_frame.columns:
            raise ValueError(f"missing X column '{series.x_column}'")
        if series.y_column not in y_frame.columns:
            raise ValueError(f"missing Y column '{series.y_column}'")

        x_values = pd.to_numeric(x_frame[series.x_column], errors="coerce")
        y_values = pd.to_numeric(y_frame[series.y_column], errors="coerce")

        point_count = min(len(x_values), len(y_values))
        if point_count == 0:
            return pd.Series(dtype=float), pd.Series(dtype=float)

        aligned = pd.DataFrame(
            {
                "x": x_values.iloc[:point_count].to_numpy(),
                "y": y_values.iloc[:point_count].to_numpy(),
            }
        ).dropna()

        if x_scale == "log":
            aligned = aligned[aligned["x"] > 0]
        if y_scale == "log":
            aligned = aligned[aligned["y"] > 0]

        if aligned.empty:
            return pd.Series(dtype=float), pd.Series(dtype=float)

        return aligned["x"], aligned["y"]

    def _draw_empty_state(self, clear_axes: bool = True) -> None:
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

    def _draw_guides(
        self,
        vertical_guides: list[float],
        y_guides: list[float],
        right_y_guides: list[float],
    ) -> None:
        for value in vertical_guides:
            self.axes.axvline(value, color="0.45", linestyle="--", linewidth=1.0, alpha=0.75)

        for value in y_guides:
            self.axes.axhline(value, color="0.45", linestyle="--", linewidth=1.0, alpha=0.75)

        if right_y_guides and self.right_axes is None:
            self.right_axes = self.axes.twinx()

        if self.right_axes is not None:
            for value in right_y_guides:
                self.right_axes.axhline(
                    value,
                    color="tab:red",
                    linestyle="--",
                    linewidth=1.0,
                    alpha=0.65,
                )

    def _draw_legend(self) -> None:
        handles, labels = self.axes.get_legend_handles_labels()
        if self.right_axes is not None:
            right_handles, right_labels = self.right_axes.get_legend_handles_labels()
            handles.extend(right_handles)
            labels.extend(right_labels)

        if handles:
            self.axes.legend(handles, labels)
