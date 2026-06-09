"""Plot type registry for Matplotlib-backed workspace visualizations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlotType:
    """Metadata for one plot type exposed in the Plot Inspector."""

    key: str
    label: str
    description: str


PLOT_TYPES: dict[str, PlotType] = {
    "line": PlotType(
        key="line",
        label="Line",
        description="Continuous X/Y line plot for ordered numeric data.",
    ),
    "scatter": PlotType(
        key="scatter",
        label="Scatter",
        description="Marker-only X/Y plot for point clouds or unconnected observations.",
    ),
    "line_marker": PlotType(
        key="line_marker",
        label="Line + Markers",
        description="Line plot with visible markers at each sampled point.",
    ),
    "errorbar": PlotType(
        key="errorbar",
        label="Errorbar",
        description="X/Y plot with optional X and Y uncertainty columns.",
    ),
    "bar": PlotType(
        key="bar",
        label="Vertical Bar",
        description="Bar chart using X/category labels or numeric positions and Y heights.",
    ),
    "barh": PlotType(
        key="barh",
        label="Horizontal Bar",
        description="Horizontal bar chart using X/category labels or numeric positions and Y widths.",
    ),
    "pie": PlotType(
        key="pie",
        label="Pie",
        description="Pie chart using X/category labels and Y/value slices.",
    ),
    "donut": PlotType(
        key="donut",
        label="Donut",
        description="Donut chart using X/category labels and Y/value slices.",
    ),
    "voronoi": PlotType(
        key="voronoi",
        label="Voronoi Composition",
        description="Voronoi-style composition map using X/category labels and Y/value magnitudes.",
    ),
    "area": PlotType(
        key="area",
        label="Area",
        description="Filled area under an X/Y curve.",
    ),
    "histogram": PlotType(
        key="histogram",
        label="Histogram",
        description="Distribution plot from the selected Y/value column.",
    ),
    "box": PlotType(
        key="box",
        label="Box Plot",
        description="Distribution comparison across one or more numeric columns.",
    ),
    "violin": PlotType(
        key="violin",
        label="Violin Plot",
        description="Kernel-density distribution comparison across one or more numeric columns.",
    ),
    "heatmap": PlotType(
        key="heatmap",
        label="Interpolated Heatmap",
        description="2D X/Y/Z coordinate map interpolated onto a regular grid.",
    ),
    "contour": PlotType(
        key="contour",
        label="Contour",
        description="Interpolated 2D contour lines from X/Y/Z coordinate data.",
    ),
    "contourf": PlotType(
        key="contourf",
        label="Filled Contour",
        description="Interpolated filled contour map from X/Y/Z coordinate data.",
    ),
}


def plot_type_label(plot_type_key: str) -> str:
    """Return the display label for a plot type key."""
    plot_type = PLOT_TYPES.get(plot_type_key)
    return plot_type.label if plot_type else plot_type_key or "Line"
