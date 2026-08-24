"""Versioned, JSON-friendly settings for saved plot appearance."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PLOT_STATE_VERSION = 3


@dataclass(frozen=True, slots=True)
class AxisSettings:
    """Appearance and range settings for one plot axis."""

    label: str = ""
    scale: str = "linear"
    minimum: str = ""
    maximum: str = ""

    @classmethod
    def from_state(cls, state: object) -> AxisSettings:
        """Return validated axis settings from an arbitrary saved value."""
        values = state if isinstance(state, dict) else {}
        scale = str(values.get("scale", "linear"))
        return cls(
            label=_text(values.get("label")),
            scale=scale if scale in {"linear", "log"} else "linear",
            minimum=_text(values.get("minimum")),
            maximum=_text(values.get("maximum")),
        )


@dataclass(frozen=True, slots=True)
class LegendSettings:
    """Legend visibility, placement, typography, and content policy."""

    enabled: bool = True
    location: str = "best"
    font_size: float = 10.0
    title: str = ""
    title_font_size: float = 10.0
    columns: int = 1
    frame_enabled: bool = True
    frame_alpha: float = 0.8
    marker_scale: float = 1.0
    handle_length: float = 2.0
    include_locators: bool = True
    include_confidence_bands: bool = True

    @classmethod
    def from_state(cls, state: object) -> LegendSettings:
        """Return bounded legend settings from an arbitrary saved value."""
        values = state if isinstance(state, dict) else {}
        location = str(values.get("location", "best"))
        allowed_locations = {
            "best", "upper right", "upper left", "lower left", "lower right",
            "right", "center left", "center right", "lower center", "upper center",
            "center", "outside right", "outside top", "outside bottom",
        }
        if location not in allowed_locations:
            location = "best"
        return cls(
            enabled=bool(values.get("enabled", True)),
            location=location,
            font_size=_bounded_float(values.get("font_size"), 10.0, 5.0, 72.0),
            title=_text(values.get("title")),
            title_font_size=_bounded_float(
                values.get("title_font_size"), 10.0, 5.0, 72.0
            ),
            columns=_bounded_int(values.get("columns"), 1, 1, 20),
            frame_enabled=bool(values.get("frame_enabled", True)),
            frame_alpha=_bounded_float(values.get("frame_alpha"), 0.8, 0.0, 1.0),
            marker_scale=_bounded_float(values.get("marker_scale"), 1.0, 0.1, 10.0),
            handle_length=_bounded_float(values.get("handle_length"), 2.0, 0.0, 20.0),
            include_locators=bool(values.get("include_locators", True)),
            include_confidence_bands=bool(
                values.get("include_confidence_bands", True)
            ),
        )


@dataclass(frozen=True, slots=True)
class FigureSettings:
    """Physical figure dimensions used by rendering and export."""

    width: float = 7.0
    height: float = 4.8

    @classmethod
    def from_state(cls, state: object) -> FigureSettings:
        """Return bounded figure dimensions from saved state."""
        values = state if isinstance(state, dict) else {}
        return cls(
            width=_bounded_float(values.get("width"), 7.0, 3.0, 20.0),
            height=_bounded_float(values.get("height"), 4.8, 2.0, 15.0),
        )


@dataclass(frozen=True, slots=True)
class StyleSettings:
    """Matplotlib and SciencePlots style selections."""

    preset: str = ""
    cycle: str = ""
    use_latex: bool = False
    custom: str = ""

    @classmethod
    def from_state(cls, state: object) -> StyleSettings:
        """Return style selections from saved state."""
        values = state if isinstance(state, dict) else {}
        return cls(
            preset=_text(values.get("preset")),
            cycle=_text(values.get("cycle")),
            use_latex=bool(values.get("use_latex", False)),
            custom=_text(values.get("custom")),
        )


@dataclass(frozen=True, slots=True)
class PlotSettings:
    """Typed global appearance settings for one saved plot definition."""

    title: str = ""
    x_axis: AxisSettings = field(default_factory=AxisSettings)
    left_y_axis: AxisSettings = field(default_factory=AxisSettings)
    right_y_axis: AxisSettings = field(default_factory=AxisSettings)
    grid_enabled: bool = True
    legend: LegendSettings = field(default_factory=LegendSettings)
    figure: FigureSettings = field(default_factory=FigureSettings)
    style: StyleSettings = field(default_factory=StyleSettings)

    def to_state(self) -> dict[str, object]:
        """Return the canonical version-3 JSON representation."""
        return {
            "title": self.title,
            "axes": {
                "x": asdict(self.x_axis),
                "left_y": asdict(self.left_y_axis),
                "right_y": asdict(self.right_y_axis),
            },
            "grid": {"enabled": self.grid_enabled},
            "legend": asdict(self.legend),
            "figure": asdict(self.figure),
            "style": asdict(self.style),
        }

    @classmethod
    def from_state(cls, state: object) -> PlotSettings:
        """Load version-3 settings or migrate the former flat settings dictionary."""
        values = state if isinstance(state, dict) else {}
        axes = values.get("axes")
        if isinstance(axes, dict):
            grid = values.get("grid") if isinstance(values.get("grid"), dict) else {}
            return cls(
                title=_text(values.get("title")),
                x_axis=AxisSettings.from_state(axes.get("x")),
                left_y_axis=AxisSettings.from_state(axes.get("left_y")),
                right_y_axis=AxisSettings.from_state(axes.get("right_y")),
                grid_enabled=bool(grid.get("enabled", True)),
                legend=LegendSettings.from_state(values.get("legend")),
                figure=FigureSettings.from_state(values.get("figure")),
                style=StyleSettings.from_state(values.get("style")),
            )
        return cls._from_flat_state(values)

    @classmethod
    def _from_flat_state(cls, state: dict[str, Any]) -> PlotSettings:
        """Migrate plot-state version 1/2 global settings without losing behavior."""
        return cls(
            title=_text(state.get("title")),
            x_axis=AxisSettings(
                label=_text(state.get("x_label")),
                scale=_legacy_scale(state.get("x_scale")),
                minimum=_text(state.get("x_min")),
                maximum=_text(state.get("x_max")),
            ),
            left_y_axis=AxisSettings(
                label=_text(state.get("y_label")),
                scale=_legacy_scale(state.get("y_scale")),
                minimum=_text(state.get("y_min")),
                maximum=_text(state.get("y_max")),
            ),
            right_y_axis=AxisSettings(
                label=_text(state.get("right_y_label")),
                scale=_legacy_scale(state.get("right_y_scale")),
                minimum=_text(state.get("right_y_min")),
                maximum=_text(state.get("right_y_max")),
            ),
            grid_enabled=bool(state.get("grid_enabled", True)),
            legend=LegendSettings(
                enabled=bool(state.get("legend_enabled", True)),
                location=_legacy_legend_location(state.get("legend_position")),
            ),
            figure=FigureSettings(
                width=_bounded_float(state.get("figure_width"), 7.0, 3.0, 20.0),
                height=_bounded_float(state.get("figure_height"), 4.8, 2.0, 15.0),
            ),
            style=StyleSettings(
                preset=_text(state.get("plot_style_preset")),
                cycle=_text(state.get("plot_style_cycle")),
                use_latex=bool(state.get("plot_style_use_latex", False)),
                custom=_text(state.get("plot_style_custom")),
            ),
        )


def _text(value: object) -> str:
    """Return text while treating None as blank."""
    return "" if value is None else str(value)


def _legacy_scale(value: object) -> str:
    """Return a supported legacy scale value."""
    scale = str(value or "linear")
    return scale if scale in {"linear", "log"} else "linear"


def _legacy_legend_location(value: object) -> str:
    """Return a supported legend location from flat state."""
    return LegendSettings.from_state({"location": value or "best"}).location


def _bounded_float(value: object, fallback: float, minimum: float, maximum: float) -> float:
    """Parse and clamp a floating-point saved value."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(max(parsed, minimum), maximum)


def _bounded_int(value: object, fallback: int, minimum: int, maximum: int) -> int:
    """Parse and clamp an integer saved value."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(max(parsed, minimum), maximum)
