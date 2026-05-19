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
        description="Bar chart using X positions and Y heights.",
    ),
    "barh": PlotType(
        key="barh",
        label="Horizontal Bar",
        description="Horizontal bar chart using X positions and Y widths.",
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
}


def plot_type_label(plot_type_key: str) -> str:
    """Return the display label for a plot type key."""
    plot_type = PLOT_TYPES.get(plot_type_key)
    return plot_type.label if plot_type else plot_type_key or "Line"
