"""Matplotlib canvas integration for workspace plotting."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from matplotlib import colormaps, colors as mpl_colors, rcParams, style as mpl_style
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.path import Path as MplPath
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox, QSizePolicy, QVBoxLayout, QWidget
from scipy import ndimage
from scipy.interpolate import CloughTocher2DInterpolator, LinearNDInterpolator, SmoothBivariateSpline
from scipy.spatial import ConvexHull, Delaunay

from core.workspace import COLUMN_NUMERIC_TYPES, Workspace, dataframe_column_metadata
from models.plot_settings import LegendSettings
from ui.plot_navigation import PlotMouseNavigation

try:
    import scienceplots  # noqa: F401
    SCIENCEPLOTS_AVAILABLE = True
except ImportError:
    SCIENCEPLOTS_AVAILABLE = False


_SPECTRAL_PLOT_TYPES = {"spectra_heatmap", "spectra_contour", "spectra_contourf"}
_SURFACE_PLOT_TYPES = {"heatmap", "contour", "contourf"} | _SPECTRAL_PLOT_TYPES
_PIE_PLOT_TYPES = {"pie", "donut"}
_VORONOI_PLOT_TYPES = {"voronoi"}
_COMPOSITION_PLOT_TYPES = _PIE_PLOT_TYPES | _VORONOI_PLOT_TYPES
_CATEGORICAL_X_PLOT_TYPES = {"bar", "barh"} | _COMPOSITION_PLOT_TYPES


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
    color_map: str = "viridis"
    colorbar_label: str = ""
    surface_render_mode: str = "auto"
    surface_aspect: str = "auto"
    surface_alpha: float = 1.0
    color_scale_mode: str = "auto"
    color_minimum: str = ""
    color_maximum: str = ""
    color_percentile_low: float = 2.0
    color_percentile_high: float = 98.0
    color_normalization: str = "linear"
    color_center: float = 0.0
    color_bad: str = "#d9d9d9"
    color_under: str = ""
    color_over: str = ""
    contour_level_mode: str = "count"
    contour_level_count: int = 12
    contour_interval: float = 1.0
    contour_custom_levels: str = ""
    contour_labels: bool = True
    contour_label_format: str = ".4g"
    contour_overlay: bool = False
    contour_line_color: str = ""
    contour_line_width: float = 0.8
    contour_line_style: str = "solid"
    show_data_points: bool = False
    show_triangulation: bool = False
    show_boundary: bool = False
    mask_outside_boundary: bool = True
    show_global_maximum: bool = False
    show_global_minimum: bool = False
    extrema_source: str = "measured"
    show_local_maxima: bool = False
    show_local_minima: bool = False
    local_extrema_count: int = 5
    local_extrema_prominence: float = 0.0
    local_extrema_separation: float = 0.0
    extrema_label_mode: str = "xyz"
    extrema_label_format: str = ".4g"
    spectral_column: str = ""
    spectral_center: float = 0.0
    spectral_sampling: str = "nearest"
    voronoi_shape: str = "circle"
    show_in_legend: bool = True

    @property
    def label(self) -> str:
        """Return a readable legend label."""
        if self.custom_label:
            return self.custom_label
        if self.plot_type in _SURFACE_PLOT_TYPES:
            z_column = self.z_column or self.y_column
            if self.plot_type in _SPECTRAL_PLOT_TYPES:
                return (
                    f"{self.z_dataset or self.y_dataset}: {z_column} at "
                    f"{self.spectral_center:g} {self.spectral_column}"
                )
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

    @property
    def legend_label(self) -> str:
        """Return the visible label or Matplotlib's legend-suppression sentinel."""
        return self.label if self.show_in_legend else "_nolegend_"


@dataclass(frozen=True, slots=True)
class PlotLocator:
    """Marker request for a forward, inverse, or surface data lookup."""

    series_index: int
    x_value: float | None = None
    y_value: float | None = None
    lookup_mode: str = "x_to_y"
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
class SurfaceExtremum:
    """One measured or interpolated map extremum selected for annotation."""

    kind: str
    x_value: float
    y_value: float
    z_value: float
    source: str
    local: bool = False


@dataclass(frozen=True, slots=True)
class PlotResult:
    """Summary of a completed plot render."""

    plotted_count: int
    skipped_messages: list[str]
    located_points: list[LocatedPoint]


class PlotNavigationToolbar(NavigationToolbar2QT):
    """Matplotlib toolbar whose save action respects JASC export geometry."""

    def __init__(self, plot_canvas: PlotCanvas) -> None:
        """Bind the standard navigation tools to the owning plot canvas."""
        self._plot_canvas_owner = plot_canvas
        super().__init__(plot_canvas.canvas, plot_canvas)
        self.addSeparator()
        copy_action = self.addAction("Copy")
        copy_action.setToolTip("Copy the current plot visualization to the clipboard")
        copy_action.triggered.connect(
            lambda _checked=False: plot_canvas.copy_to_clipboard()
        )

    def home(self, *args: object) -> None:
        self._plot_canvas_owner._mouse_navigation.finish()
        super().home(*args)

    def back(self, *args: object) -> None:
        self._plot_canvas_owner._mouse_navigation.finish()
        super().back(*args)

    def forward(self, *args: object) -> None:
        self._plot_canvas_owner._mouse_navigation.finish()
        super().forward(*args)

    def save_figure(self, *args: object) -> str:
        """Choose a destination and export with the configured physical size."""
        filetypes = self.canvas.get_supported_filetypes_grouped()
        default_filetype = self.canvas.get_default_filetype()
        start_path = os.path.expanduser(str(rcParams["savefig.directory"]))
        start = os.path.join(start_path, self.canvas.get_default_filename())
        filters: list[str] = []
        selected_filter = ""
        for name, extensions in sorted(filetypes.items()):
            extension_list = " ".join(f"*.{extension}" for extension in extensions)
            file_filter = f"{name} ({extension_list})"
            if default_filetype in extensions:
                selected_filter = file_filter
            filters.append(file_filter)
        file_name, _chosen_filter = QFileDialog.getSaveFileName(
            self._plot_canvas_owner,
            "Choose a filename to save to",
            start,
            ";;".join(filters),
            selected_filter,
        )
        if not file_name:
            return ""
        if start_path:
            rcParams["savefig.directory"] = os.path.dirname(file_name)
        try:
            self._plot_canvas_owner.export_figure(file_name)
        except Exception as exc:
            QMessageBox.critical(self, "Error saving file", str(exc))
            return ""
        return file_name


class PlotCanvas(QWidget):
    """A QWidget wrapping a Matplotlib FigureCanvas and navigation toolbar."""

    element_double_clicked = Signal(str, object)
    surface_cut_selected = Signal(float, float, float, float)
    surface_cut_cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the Matplotlib figure, toolbar, and empty plot placeholder."""
        super().__init__(parent)

        self._export_width = 7.0
        self._export_height = 4.8
        self._export_size_mode = "figure"
        self.figure = Figure(figsize=(7.0, 4.8), constrained_layout=False)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setToolTip(
            "Wheel: zoom. Shift+wheel or middle-button drag: pan. "
            "Over X/Y axes: that axis only; inside the plot: both. "
            "Double-click plotted data, the title, an axis label/tick area, the legend, "
            "or a legend entry to edit it directly."
        )
        self.canvas.mpl_connect("button_press_event", self._handle_canvas_button_press)
        self.canvas.mpl_connect("key_press_event", self._handle_canvas_key_press)
        self.toolbar = PlotNavigationToolbar(self)
        self.canvas.mpl_connect("motion_notify_event", self._handle_canvas_motion)
        self.axes = self.figure.add_subplot(111)
        self.right_axes: Any | None = None
        self._series_artists: list[tuple[int, object]] = []
        self._colorbar_labels: list[tuple[int, object]] = []
        self._rendered_surface_grids: list[
            tuple[_SurfaceValues, np.ndarray, np.ndarray, np.ma.MaskedArray]
        ] = []
        self._surface_cut_pick_active = False
        self._surface_cut_points: list[tuple[float, float]] = []
        self._surface_cut_artists: list[Any] = []
        self._mouse_navigation = PlotMouseNavigation(self)
        self.coordinate_readout = QLabel()
        self.coordinate_readout.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.coordinate_readout.setObjectName("MutedLabel")
        self.coordinate_readout.setMinimumHeight(20)
        self.coordinate_readout.setVisible(False)
        self._draw_empty_state()

        layout = QVBoxLayout(self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.coordinate_readout)
        layout.addWidget(self.canvas, 1)

    def set_export_size(self, width: float, height: float, size_mode: str) -> None:
        """Set physical export geometry without resizing the interactive canvas."""
        if width <= 0 or height <= 0:
            raise ValueError("Export width and height must be positive.")
        if size_mode not in {"figure", "plot_area"}:
            raise ValueError("Export size mode must be figure or plot_area.")
        self._export_width = float(width)
        self._export_height = float(height)
        self._export_size_mode = size_mode

    def copy_to_clipboard(self) -> bool:
        """Copy the current interactive canvas image without applying export geometry."""
        application = QApplication.instance()
        if application is None:
            return False
        self.canvas.draw()
        pixmap = self.canvas.grab()
        if pixmap.isNull():
            return False
        QApplication.clipboard().setPixmap(pixmap)
        return True

    def export_figure(self, file_name: str) -> None:
        """Save using full-image or axes-box dimensions, then restore canvas geometry."""
        original_size = tuple(float(value) for value in self.figure.get_size_inches())
        target_width, target_height = self._export_figure_dimensions()
        try:
            self.figure.set_size_inches(target_width, target_height, forward=False)
            if self._export_size_mode == "plot_area":
                target_width, target_height = self._refined_plot_area_figure_dimensions(
                    target_width,
                    target_height,
                )
                self.figure.set_size_inches(target_width, target_height, forward=False)
            with mpl_style.context({"savefig.bbox": None}):
                self.figure.savefig(file_name, bbox_inches=None)
        finally:
            self.figure.set_size_inches(*original_size, forward=False)
            self.canvas.draw_idle()

    def _export_figure_dimensions(self) -> tuple[float, float]:
        """Return total figure dimensions required by the selected export basis."""
        if self._export_size_mode == "figure":
            return self._export_width, self._export_height
        axes_position = self.axes.get_position()
        if axes_position.width <= 1.0e-9 or axes_position.height <= 1.0e-9:
            raise ValueError("The plotting area has no measurable size to export.")
        return (
            self._export_width / float(axes_position.width),
            self._export_height / float(axes_position.height),
        )

    def _refined_plot_area_figure_dimensions(
        self,
        figure_width: float,
        figure_height: float,
    ) -> tuple[float, float]:
        """Refine total size when aspect constraints alter the normalized axes box."""
        width = figure_width
        height = figure_height
        for _iteration in range(3):
            self.figure.set_size_inches(width, height, forward=False)
            self.figure.canvas.draw()
            axes_position = self.axes.get_position()
            actual_width = width * float(axes_position.width)
            actual_height = height * float(axes_position.height)
            if actual_width <= 1.0e-9 or actual_height <= 1.0e-9:
                break
            width *= self._export_width / actual_width
            height *= self._export_height / actual_height
        return width, height

    def _handle_canvas_button_press(self, event: object) -> None:
        """Emit the rendered plot element under a left-button double-click."""
        if self._surface_cut_pick_active:
            self._handle_surface_cut_click(event)
            return
        if not bool(getattr(event, "dblclick", False)):
            return
        button = getattr(event, "button", None)
        if button not in {1, "left"} and getattr(button, "name", "").lower() != "left":
            return
        pixel_x = getattr(event, "x", None)
        pixel_y = getattr(event, "y", None)
        if pixel_x is None or pixel_y is None:
            return
        target = self.editable_element_at(float(pixel_x), float(pixel_y))
        if target is not None:
            self.element_double_clicked.emit(target[0], target[1])

    def begin_surface_cut_selection(self) -> None:
        """Arm a two-click interaction for selecting a line across a rendered map."""
        if not self._rendered_surface_grids:
            raise ValueError("Render a 2D map before selecting a cut line.")
        toolbar_mode = str(self.toolbar.mode).lower()
        if toolbar_mode:
            if "zoom" in toolbar_mode:
                self.toolbar.zoom()
            else:
                self.toolbar.pan()
        self.clear_surface_cut_overlay()
        self._surface_cut_pick_active = True
        self._surface_cut_points = []
        self.canvas.setCursor(Qt.CrossCursor)
        self.canvas.setFocus()
        self.coordinate_readout.setVisible(True)
        self.coordinate_readout.setText(
            "Cut selection: click the start point; right-click or Esc cancels."
        )

    def cancel_surface_cut_selection(self, *, notify: bool = True) -> None:
        """Cancel an active cut-line selection and remove its temporary overlay."""
        was_active = self._surface_cut_pick_active
        self._surface_cut_pick_active = False
        self._surface_cut_points = []
        self.canvas.unsetCursor()
        self.clear_surface_cut_overlay()
        if self._rendered_surface_grids:
            self.coordinate_readout.setText(
                "Move the mouse over the map to read X, Y, and intensity"
            )
        if was_active and notify:
            self.surface_cut_cancelled.emit()

    def clear_surface_cut_overlay(self) -> None:
        """Remove the interactive cut line without changing the rendered map."""
        for artist in self._surface_cut_artists:
            try:
                artist.remove()
            except (AttributeError, ValueError):
                pass
        self._surface_cut_artists = []
        self.canvas.draw_idle()

    def surface_cut_selection_active(self) -> bool:
        """Return whether the canvas is waiting for cut-line clicks."""
        return self._surface_cut_pick_active

    def _handle_surface_cut_click(self, event: object) -> None:
        """Capture or cancel one endpoint during the two-click cut workflow."""
        button = getattr(event, "button", None)
        button_name = getattr(button, "name", "").lower()
        if button in {3, "right"} or button_name == "right":
            self.cancel_surface_cut_selection()
            return
        if button not in {1, "left"} and button_name != "left":
            return
        if getattr(event, "inaxes", None) is not self.axes:
            return
        x_value = getattr(event, "xdata", None)
        y_value = getattr(event, "ydata", None)
        if x_value is None or y_value is None:
            return
        point = (float(x_value), float(y_value))
        if not np.all(np.isfinite(point)):
            return

        if not self._surface_cut_points:
            self._surface_cut_points = [point]
            self._draw_surface_cut_overlay(point, point)
            self.coordinate_readout.setText(
                f"Cut start x={point[0]:.6g}, y={point[1]:.6g}; click the end point."
            )
            return

        start = self._surface_cut_points[0]
        if np.hypot(point[0] - start[0], point[1] - start[1]) <= 1e-15:
            self.coordinate_readout.setText("Choose an end point different from the start.")
            return
        self._draw_surface_cut_overlay(start, point)
        self._surface_cut_pick_active = False
        self._surface_cut_points = [start, point]
        self.canvas.unsetCursor()
        self.coordinate_readout.setText(
            f"Selected cut ({start[0]:.6g}, {start[1]:.6g}) to "
            f"({point[0]:.6g}, {point[1]:.6g})."
        )
        self.surface_cut_selected.emit(start[0], start[1], point[0], point[1])

    def _draw_surface_cut_overlay(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        """Draw a high-contrast selected cut over any map palette."""
        if len(self._surface_cut_artists) == 2:
            for artist in self._surface_cut_artists:
                artist.set_data([start[0], end[0]], [start[1], end[1]])
        else:
            self.clear_surface_cut_overlay()
            outline, = self.axes.plot(
                [start[0], end[0]],
                [start[1], end[1]],
                color="white",
                linewidth=4.2,
                marker="o",
                markersize=7.0,
                markeredgecolor="white",
                markerfacecolor="white",
                zorder=30,
                label="_nolegend_",
            )
            line, = self.axes.plot(
                [start[0], end[0]],
                [start[1], end[1]],
                color="#d627d9",
                linewidth=2.0,
                marker="o",
                markersize=4.5,
                markeredgecolor="#d627d9",
                markerfacecolor="#d627d9",
                zorder=31,
                label="_nolegend_",
            )
            self._surface_cut_artists = [outline, line]
        self.canvas.draw_idle()

    def _handle_canvas_key_press(self, event: object) -> None:
        """Allow Escape to leave interactive cut selection safely."""
        if self._surface_cut_pick_active and str(getattr(event, "key", "")).lower() == "escape":
            self.cancel_surface_cut_selection()

    def editable_element_at(self, pixel_x: float, pixel_y: float) -> tuple[str, object] | None:
        """Return the editable artist or axis region at display-pixel coordinates."""
        renderer = self.canvas.get_renderer()
        for series_index, label_artist in self._colorbar_labels:
            if self._artist_contains(
                label_artist,
                renderer,
                pixel_x,
                pixel_y,
                padding=5.0,
            ):
                return "colorbar_label", series_index
        legend = self.axes.get_legend()
        if legend is not None and legend.get_visible():
            for text in legend.get_texts():
                if self._artist_contains(text, renderer, pixel_x, pixel_y, padding=3.0):
                    return "legend_entry", text.get_text()
            legend_title = legend.get_title()
            if legend_title.get_text() and self._artist_contains(
                legend_title, renderer, pixel_x, pixel_y, padding=3.0
            ):
                return "legend", None
            if self._artist_contains(legend, renderer, pixel_x, pixel_y, padding=2.0):
                return "legend", None

        if self.axes.title.get_text() and self._artist_contains(
            self.axes.title, renderer, pixel_x, pixel_y, padding=5.0
        ):
            return "title", None
        if self.axes.xaxis.label.get_text() and self._artist_contains(
            self.axes.xaxis.label, renderer, pixel_x, pixel_y, padding=5.0
        ):
            return "x_axis", None
        if self.axes.yaxis.label.get_text() and self._artist_contains(
            self.axes.yaxis.label, renderer, pixel_x, pixel_y, padding=5.0
        ):
            return "left_y_axis", None
        if self.right_axes is not None:
            if self.right_axes.yaxis.label.get_text() and self._artist_contains(
                self.right_axes.yaxis.label, renderer, pixel_x, pixel_y, padding=5.0
            ):
                return "right_y_axis", None

        if self._contains_any_artist(
            self.axes.get_xticklabels(), renderer, pixel_x, pixel_y, padding=2.0
        ):
            return "x_axis", None
        if self.right_axes is not None and self._contains_any_artist(
            self.right_axes.get_yticklabels(), renderer, pixel_x, pixel_y, padding=2.0
        ):
            return "right_y_axis", None
        if self._contains_any_artist(
            self.axes.get_yticklabels(), renderer, pixel_x, pixel_y, padding=2.0
        ):
            return "left_y_axis", None

        axes_bounds = self.axes.bbox
        if axes_bounds.x0 - 8.0 <= pixel_x <= axes_bounds.x1 + 8.0:
            if abs(pixel_y - axes_bounds.y0) <= 8.0:
                return "x_axis", None
        if axes_bounds.y0 - 8.0 <= pixel_y <= axes_bounds.y1 + 8.0:
            if self.right_axes is not None and abs(pixel_x - axes_bounds.x1) <= 8.0:
                return "right_y_axis", None
            if abs(pixel_x - axes_bounds.x0) <= 8.0:
                return "left_y_axis", None
        series_index = self._plotted_series_at(pixel_x, pixel_y)
        if series_index is not None:
            return "series", series_index
        return None

    def _plotted_series_at(self, pixel_x: float, pixel_y: float) -> int | None:
        """Return the source-series index of the topmost data artist at a display point."""
        event = MouseEvent("button_press_event", self.canvas, pixel_x, pixel_y, button=1)
        for series_index, artist in reversed(self._series_artists):
            if not bool(getattr(artist, "get_visible", lambda: False)()):
                continue
            try:
                contains, _details = artist.contains(event)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
            if contains:
                return series_index
        return None

    def _register_series_artists(
        self,
        series_index: int,
        axes: Any,
        previous_artist_ids: set[int],
    ) -> None:
        """Associate newly drawn Matplotlib artists with their source series."""
        for artist in axes.get_children():
            if id(artist) not in previous_artist_ids:
                self._series_artists.append((series_index, artist))

    @classmethod
    def _contains_any_artist(
        cls,
        artists: list[object],
        renderer: object,
        pixel_x: float,
        pixel_y: float,
        padding: float,
    ) -> bool:
        """Return whether any visible artist contains the display point."""
        return any(
            cls._artist_contains(artist, renderer, pixel_x, pixel_y, padding)
            for artist in artists
            if bool(getattr(artist, "get_visible", lambda: False)())
        )

    @staticmethod
    def _artist_contains(
        artist: object,
        renderer: object,
        pixel_x: float,
        pixel_y: float,
        padding: float,
    ) -> bool:
        """Return whether a padded Matplotlib artist extent contains a point."""
        try:
            bounds = artist.get_window_extent(renderer)  # type: ignore[attr-defined]
        except (AttributeError, RuntimeError, ValueError):
            return False
        return bool(
            bounds.x0 - padding <= pixel_x <= bounds.x1 + padding
            and bounds.y0 - padding <= pixel_y <= bounds.y1 + padding
        )

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
        x_label_font_size: float = 0.0,
        x_tick_font_size: float = 0.0,
        y_label_font_size: float = 0.0,
        y_tick_font_size: float = 0.0,
        right_y_label_font_size: float = 0.0,
        right_y_tick_font_size: float = 0.0,
        grid_enabled: bool = True,
        legend_settings: LegendSettings | None = None,
        locators: list[PlotLocator] | None = None,
        style_names: list[str] | None = None,
    ) -> PlotResult:
        """Render selected workspace series onto the axes."""
        self._mouse_navigation.reset()
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
                    x_label_font_size=x_label_font_size,
                    x_tick_font_size=x_tick_font_size,
                    y_label_font_size=y_label_font_size,
                    y_tick_font_size=y_tick_font_size,
                    right_y_label_font_size=right_y_label_font_size,
                    right_y_tick_font_size=right_y_tick_font_size,
                    grid_enabled=grid_enabled,
                    legend_settings=legend_settings or LegendSettings(),
                    locators=locators,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            self._draw_error_state(str(exc))
            self.canvas.draw()
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
        x_label_font_size: float,
        x_tick_font_size: float,
        y_label_font_size: float,
        y_tick_font_size: float,
        right_y_label_font_size: float,
        right_y_tick_font_size: float,
        grid_enabled: bool,
        legend_settings: LegendSettings,
        locators: list[PlotLocator] | None,
    ) -> PlotResult:
        """Render selected workspace series with active Matplotlib style settings."""
        if self._surface_cut_pick_active:
            self.cancel_surface_cut_selection()
        else:
            self._surface_cut_points = []
            self._surface_cut_artists = []
            self.canvas.unsetCursor()
        self._remove_right_axes()
        self.figure.clear()
        self._disable_layout_engine()
        self._reset_figure_margins()
        self.axes = self.figure.add_subplot(111)
        self.right_axes = None
        self._series_artists = []
        self._colorbar_labels = []
        self._rendered_surface_grids = []
        self.coordinate_readout.clear()
        self.coordinate_readout.setVisible(False)

        skipped_messages: list[str] = []
        located_points: list[LocatedPoint] = []
        plotted_count = 0
        x_axis_values: list[np.ndarray] = []
        left_y_axis_values: list[np.ndarray] = []
        right_y_axis_values: list[np.ndarray] = []
        uses_composition_plot = any(series.plot_type in _COMPOSITION_PLOT_TYPES for series in series_list)
        uses_right_axis = not uses_composition_plot and any(series.y_axis == "right" for series in series_list)
        if uses_right_axis:
            self.right_axes = self.axes.twinx()

        plotted_series_values: dict[int, tuple[pd.Series, pd.Series, PlotSeries]] = {}
        plotted_surface_values: dict[int, _SurfaceValues] = {}
        rendered_surface_grids: list[
            tuple[_SurfaceValues, np.ndarray, np.ndarray, np.ma.MaskedArray]
        ] = []

        for series_index, series in enumerate(series_list):
            if uses_composition_plot and series.plot_type not in _COMPOSITION_PLOT_TYPES:
                skipped_messages.append(f"{series.label}: composition plots cannot be mixed with XY series")
                continue
            if uses_composition_plot and plotted_count:
                skipped_messages.append(f"{series.label}: only one composition series can be rendered at a time")
                continue

            series_y_scale = right_y_scale if series.y_axis == "right" else y_scale
            target_axes = self.right_axes if series.y_axis == "right" and self.right_axes else self.axes
            if series.plot_type in _SURFACE_PLOT_TYPES:
                previous_artist_ids = {id(artist) for artist in self.axes.get_children()}
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
                        series_index=series_index,
                        series=series,
                        surface_values=surface_values,
                        grid_x=grid_x,
                        grid_y=grid_y,
                        grid_z=grid_z,
                    )
                except (KeyError, ValueError) as exc:
                    skipped_messages.append(f"{series.label}: {exc}")
                    continue

                plotted_surface_values[series_index] = surface_values
                rendered_surface_grids.append(
                    (surface_values, grid_x, grid_y, grid_z)
                )
                self._register_series_artists(series_index, self.axes, previous_artist_ids)
                x_axis_values.append(surface_values.x_values)
                left_y_axis_values.append(surface_values.y_values)
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

                previous_artist_ids = {id(artist) for artist in target_axes.get_children()}
                self._draw_distribution_by_type(
                    target_axes=target_axes,
                    series=series,
                    values_by_column=values_by_column,
                    column_labels=column_labels,
                )
                self._register_series_artists(series_index, target_axes, previous_artist_ids)
                x_axis_values.append(np.arange(1, len(values_by_column) + 1, dtype=float))
                left_y_axis_values.extend(value.to_numpy(dtype=float) for value in values_by_column)
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
                skipped_messages.append(f"{series.label}: no plottable points")
                continue

            plot_kwargs = {
                "label": series.legend_label,
                "linestyle": series.line_style,
                "marker": series.marker,
                "linewidth": series.line_width,
                "markersize": series.marker_size,
            }
            if series.color:
                plot_kwargs["color"] = series.color

            previous_artist_ids = {id(artist) for artist in target_axes.get_children()}
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
                include_in_legend=legend_settings.include_confidence_bands,
            )
            self._register_series_artists(series_index, target_axes, previous_artist_ids)
            if series.plot_type not in ({"histogram"} | _COMPOSITION_PLOT_TYPES):
                plotted_series_values[series_index] = (x_values, y_values, series)
            self._record_axis_values(
                series=series,
                x_values=x_values,
                y_values=y_values,
                x_axis_values=x_axis_values,
                left_y_axis_values=left_y_axis_values,
                right_y_axis_values=right_y_axis_values,
            )
            plotted_count += 1

        if not plotted_count:
            detail = skipped_messages[0] if skipped_messages else "No series could be plotted."
            self._draw_error_state(detail)
            self.canvas.draw()
            return PlotResult(
                plotted_count=0,
                skipped_messages=skipped_messages,
                located_points=[],
            )

        self.axes.set_title(title)
        if uses_composition_plot:
            self.axes.set_xlabel("")
            self.axes.set_ylabel("")
            self.axes.set_aspect("equal")
            self.axes.grid(False)
            self.canvas.draw()
            return PlotResult(
                plotted_count=plotted_count,
                skipped_messages=skipped_messages,
                located_points=[],
            )

        x_label_kwargs = {"fontsize": x_label_font_size} if x_label_font_size > 0 else {}
        y_label_kwargs = {"fontsize": y_label_font_size} if y_label_font_size > 0 else {}
        self.axes.set_xlabel(x_label, **x_label_kwargs)
        self.axes.set_ylabel(y_label, **y_label_kwargs)
        if x_tick_font_size > 0:
            self.axes.tick_params(axis="x", labelsize=x_tick_font_size)
        if y_tick_font_size > 0:
            self.axes.tick_params(axis="y", labelsize=y_tick_font_size)
        if x_scale == "log":
            self._seed_positive_axis_limits(self.axes, "x", x_axis_values)
        if y_scale == "log":
            self._seed_positive_axis_limits(self.axes, "y", left_y_axis_values)
        self.axes.set_xscale(x_scale)
        self.axes.set_yscale(y_scale)
        if grid_enabled:
            self.axes.grid(True, alpha=0.25)
        else:
            self.axes.grid(False)

        if self.right_axes is not None:
            right_label_kwargs = (
                {"fontsize": right_y_label_font_size}
                if right_y_label_font_size > 0
                else {}
            )
            self.right_axes.set_ylabel(right_y_label, **right_label_kwargs)
            if right_y_tick_font_size > 0:
                self.right_axes.tick_params(axis="y", labelsize=right_y_tick_font_size)
            if right_y_scale == "log":
                self._seed_positive_axis_limits(self.right_axes, "y", right_y_axis_values)
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
            include_in_legend=legend_settings.include_locators,
        )
        skipped_messages.extend(locator_messages)

        self._draw_legend(legend_settings, series_list)
        if rendered_surface_grids:
            self._install_surface_coordinate_reader(rendered_surface_grids)

        self.canvas.draw()
        return PlotResult(
            plotted_count=plotted_count,
            skipped_messages=skipped_messages,
            located_points=located_points,
        )

    def clear_plot(self) -> None:
        """Clear the plot surface."""
        self._mouse_navigation.reset()
        self._draw_empty_state()
        nav_stack = getattr(self.toolbar, "_nav_stack", None)
        if nav_stack is not None:
            nav_stack.clear()
            self.toolbar.update()
        self.canvas.draw_idle()

    def _disable_layout_engine(self) -> None:
        """Disable Matplotlib layout engines before manual Qt canvas drawing."""
        set_layout_engine = getattr(self.figure, "set_layout_engine", None)
        if callable(set_layout_engine):
            set_layout_engine(None)
        else:
            self.figure.set_constrained_layout(False)

    def _reset_figure_margins(self) -> None:
        """Restore active-style subplot margins before applying custom outside layout."""
        self.figure.subplots_adjust(
            left=float(rcParams["figure.subplot.left"]),
            right=float(rcParams["figure.subplot.right"]),
            bottom=float(rcParams["figure.subplot.bottom"]),
            top=float(rcParams["figure.subplot.top"]),
            wspace=float(rcParams["figure.subplot.wspace"]),
            hspace=float(rcParams["figure.subplot.hspace"]),
        )

    def _record_axis_values(
        self,
        series: PlotSeries,
        x_values: pd.Series,
        y_values: pd.Series,
        x_axis_values: list[np.ndarray],
        left_y_axis_values: list[np.ndarray],
        right_y_axis_values: list[np.ndarray],
    ) -> None:
        """Record data-space values used to seed valid log-axis limits."""
        if series.plot_type in _COMPOSITION_PLOT_TYPES:
            return

        target_y_values = right_y_axis_values if series.y_axis == "right" else left_y_axis_values
        if series.plot_type == "histogram":
            x_axis_values.append(self._numeric_axis_array(y_values))
            target_y_values.append(self._histogram_axis_counts(y_values, series))
            return

        if series.plot_type == "barh":
            x_axis_values.append(self._numeric_axis_array(y_values))
            target_y_values.append(self._numeric_axis_array(x_values))
            return

        x_axis_values.append(self._numeric_axis_array(x_values))
        target_y_values.append(self._numeric_axis_array(y_values))

    @staticmethod
    def _numeric_axis_array(values: pd.Series) -> np.ndarray:
        """Return numeric axis values, preserving nonnumeric labels as NaN."""
        return pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)

    @staticmethod
    def _histogram_axis_counts(values: pd.Series, series: PlotSeries) -> np.ndarray:
        """Return positive histogram-axis values for log-limit seeding."""
        numeric_values = values.to_numpy(dtype=float)
        if numeric_values.size == 0:
            return np.asarray([], dtype=float)
        try:
            counts, _bin_edges = np.histogram(numeric_values, bins=max(series.histogram_bins, 1))
        except ValueError:
            return np.asarray([], dtype=float)
        counts = counts.astype(float)
        if series.histogram_cumulative:
            counts = np.cumsum(counts)
        return counts

    def _seed_positive_axis_limits(
        self,
        axes: Any,
        axis_name: str,
        value_groups: list[np.ndarray],
    ) -> None:
        """Set positive view limits before switching an axis to log scale."""
        limits = self._positive_axis_limits(value_groups)
        if limits is None:
            limits = (0.1, 1.0)
        if axis_name == "x":
            axes.set_xlim(*limits)
        else:
            axes.set_ylim(*limits)

    @staticmethod
    def _positive_axis_limits(value_groups: list[np.ndarray]) -> tuple[float, float] | None:
        """Return padded positive min/max limits from one or more value arrays."""
        if not value_groups:
            return None
        arrays = [
            np.asarray(group, dtype=float).ravel()
            for group in value_groups
            if np.asarray(group).size
        ]
        if not arrays:
            return None
        values = np.concatenate(arrays)
        if values.size == 0:
            return None
        values = values[np.isfinite(values) & (values > 0)]
        if values.size == 0:
            return None

        lower = float(np.min(values))
        upper = float(np.max(values))
        if not np.isfinite(lower) or not np.isfinite(upper) or lower <= 0 or upper <= 0:
            return None
        if lower == upper:
            return max(lower / 10.0, np.nextafter(0.0, 1.0)), upper * 10.0

        padding = max((upper / lower) ** 0.05, 1.02)
        return max(lower / padding, np.nextafter(0.0, 1.0)), upper * padding

    def _series_values(
        self,
        workspace: Workspace,
        series: PlotSeries,
        x_scale: str,
        y_scale: str,
    ) -> tuple[pd.Series, pd.Series, pd.Series | None, pd.Series | None]:
        """Return aligned X/Y values and their errors for a plot series."""
        y_frame = workspace.get_dataset(series.y_dataset).frame

        if series.plot_type == "histogram":
            if series.y_column not in y_frame.columns:
                raise ValueError(f"missing value column '{series.y_column}'")
            y_values = self._numeric_column_values(
                workspace,
                series.y_dataset,
                series.y_column,
                "value",
            ).dropna()
            if x_scale == "log":
                y_values = y_values[y_values > 0]
            if y_values.empty:
                return pd.Series(dtype=float), pd.Series(dtype=float), None, None
            x_values = pd.Series(np.arange(len(y_values)), dtype=float)
            return x_values, y_values.reset_index(drop=True), None, None

        if series.plot_type in _CATEGORICAL_X_PLOT_TYPES:
            return self._categorical_x_series_values(
                workspace=workspace,
                series=series,
                x_scale=x_scale,
                y_scale=y_scale,
            )

        x_frame = workspace.get_dataset(series.x_dataset).frame
        if series.x_column not in x_frame.columns:
            raise ValueError(f"missing X column '{series.x_column}'")
        if series.y_column not in y_frame.columns:
            raise ValueError(f"missing Y column '{series.y_column}'")

        x_values = self._numeric_column_values(workspace, series.x_dataset, series.x_column, "X")
        y_values = self._numeric_column_values(workspace, series.y_dataset, series.y_column, "Y")
        
        cols = {
            "x": x_values,
            "y": y_values,
        }
        
        if series.x_err_column and series.x_err_column in x_frame.columns:
            cols["x_err"] = self._numeric_column_values(
                workspace,
                series.x_dataset,
                series.x_err_column,
                "X error",
            )
        if series.y_err_column and series.y_err_column in y_frame.columns:
            cols["y_err"] = self._numeric_column_values(
                workspace,
                series.y_dataset,
                series.y_err_column,
                "Y error",
            )

        # Find the minimum valid length across all provided columns
        point_count = min(len(col) for col in cols.values())
        if point_count == 0:
            return pd.Series(dtype=float), pd.Series(dtype=float), None, None

        # Truncate to matching length
        for key in cols:
            cols[key] = cols[key].iloc[:point_count].to_numpy()

        aligned = pd.DataFrame(cols).dropna()

        if series.plot_type == "barh":
            if x_scale == "log":
                aligned = aligned[aligned["y"] > 0]
            if y_scale == "log":
                aligned = aligned[aligned["x"] > 0]
        else:
            if x_scale == "log":
                aligned = aligned[aligned["x"] > 0]
            if y_scale == "log":
                aligned = aligned[aligned["y"] > 0]

        if aligned.empty:
            return pd.Series(dtype=float), pd.Series(dtype=float), None, None

        x_err_out = aligned["x_err"] if "x_err" in aligned.columns else None
        y_err_out = aligned["y_err"] if "y_err" in aligned.columns else None
        return aligned["x"], aligned["y"], x_err_out, y_err_out

    def _categorical_x_series_values(
        self,
        workspace: Workspace,
        series: PlotSeries,
        x_scale: str,
        y_scale: str,
    ) -> tuple[pd.Series, pd.Series, pd.Series | None, pd.Series | None]:
        """Return label/value pairs for categorical chart types."""
        x_frame = workspace.get_dataset(series.x_dataset).frame
        y_frame = workspace.get_dataset(series.y_dataset).frame
        if series.x_column not in x_frame.columns:
            raise ValueError(f"missing label column '{series.x_column}'")
        if series.y_column not in y_frame.columns:
            raise ValueError(f"missing value column '{series.y_column}'")

        labels = x_frame[series.x_column]
        values = self._numeric_column_values(
            workspace,
            series.y_dataset,
            series.y_column,
            "value",
        )
        point_count = min(len(labels), len(values))
        if point_count == 0:
            return pd.Series(dtype=object), pd.Series(dtype=float), None, None

        aligned = pd.DataFrame(
            {
                "label": labels.iloc[:point_count].to_numpy(),
                "value": values.iloc[:point_count].to_numpy(),
            }
        )
        aligned["label_text"] = aligned["label"].map(self._format_category_label)
        aligned = aligned[(aligned["label_text"] != "") & aligned["value"].notna()].copy()

        if series.plot_type in _COMPOSITION_PLOT_TYPES:
            aligned = aligned[aligned["value"] > 0]
            return (
                aligned["label_text"].reset_index(drop=True),
                aligned["value"].reset_index(drop=True),
                None,
                None,
            )

        if series.plot_type == "bar":
            if x_scale == "log":
                aligned["axis_label"] = self._numeric_label_values(
                    workspace,
                    series.x_dataset,
                    series.x_column,
                    aligned["label"],
                )
                aligned = aligned[aligned["axis_label"] > 0]
            else:
                aligned["axis_label"] = self._category_axis_values(
                    workspace,
                    series.x_dataset,
                    series.x_column,
                    aligned["label"],
                    aligned["label_text"],
                )
            if y_scale == "log":
                aligned = aligned[aligned["value"] > 0]
        else:
            if x_scale == "log":
                aligned = aligned[aligned["value"] > 0]
            if y_scale == "log":
                aligned["axis_label"] = self._numeric_label_values(
                    workspace,
                    series.x_dataset,
                    series.x_column,
                    aligned["label"],
                )
                aligned = aligned[aligned["axis_label"] > 0]
            else:
                aligned["axis_label"] = self._category_axis_values(
                    workspace,
                    series.x_dataset,
                    series.x_column,
                    aligned["label"],
                    aligned["label_text"],
                )

        if aligned.empty:
            return pd.Series(dtype=object), pd.Series(dtype=float), None, None
        return (
            aligned["axis_label"].reset_index(drop=True),
            aligned["value"].reset_index(drop=True),
            None,
            None,
        )

    def _category_axis_values(
        self,
        workspace: Workspace,
        dataset_name: str,
        column: str,
        labels: pd.Series,
        label_text: pd.Series,
    ) -> pd.Series:
        """Return numeric labels when possible, otherwise text labels for categorical axes."""
        metadata = dataframe_column_metadata(workspace.get_dataset(dataset_name).frame, column)
        if metadata.value_type == "text":
            return label_text.astype(str)
        if metadata.value_type in COLUMN_NUMERIC_TYPES:
            return self._numeric_label_values(workspace, dataset_name, column, labels)
        numeric_labels = pd.to_numeric(labels, errors="coerce")
        if numeric_labels.notna().all():
            return numeric_labels.astype(float)
        return label_text.astype(str)

    @staticmethod
    def _format_category_label(value: object) -> str:
        """Return a clean string label for categorical charts."""
        if pd.isna(value):
            return ""
        return str(value).strip()

    def _numeric_column_values(
        self,
        workspace: Workspace,
        dataset_name: str,
        column: str,
        role_label: str,
    ) -> pd.Series:
        """Return numeric values, enforcing explicit column type metadata."""
        frame = workspace.get_dataset(dataset_name).frame
        if column not in frame.columns:
            raise ValueError(f"missing {role_label} column '{column}'")
        values = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        self._validate_numeric_metadata(frame[column], values, frame, column, role_label)
        return values

    def _numeric_label_values(
        self,
        workspace: Workspace,
        dataset_name: str,
        column: str,
        labels: pd.Series,
    ) -> pd.Series:
        """Return numeric categorical positions when a categorical axis is logarithmic."""
        frame = workspace.get_dataset(dataset_name).frame
        values = pd.to_numeric(labels, errors="coerce")
        self._validate_numeric_metadata(labels, values, frame, column, "label/position")
        return values

    @staticmethod
    def _validate_numeric_metadata(
        source_values: pd.Series,
        numeric_values: pd.Series,
        frame: pd.DataFrame,
        column: str,
        role_label: str,
    ) -> None:
        """Raise when metadata or cell content conflicts with numeric plot usage."""
        metadata = dataframe_column_metadata(frame, column)
        if metadata.value_type == "text":
            raise ValueError(
                f"{role_label} column '{column}' is marked Text in metadata; "
                "choose a Numeric/Scientific column or update its metadata."
            )

        meaningful = source_values.notna()
        if not pd.api.types.is_numeric_dtype(source_values.dtype):
            meaningful &= source_values.astype(str).str.strip().ne("")
        invalid = meaningful & numeric_values.isna()
        if invalid.any():
            example = str(source_values[invalid].iloc[0])
            row_position = int(np.flatnonzero(invalid.to_numpy())[0]) + 1
            raise ValueError(
                f"{role_label} column '{column}' contains non-numeric text at row "
                f"{row_position}, such as '{example}'. Plotting will not silently omit it."
            )

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
            "x": self._numeric_column_values(workspace, series.x_dataset, series.x_column, "X coordinate"),
            "y": self._numeric_column_values(workspace, series.y_dataset, series.y_column, "Y coordinate"),
            "z": self._numeric_column_values(workspace, z_dataset_name, series.z_column, "Z value"),
        }
        if series.plot_type in _SPECTRAL_PLOT_TYPES:
            if not series.spectral_column:
                raise ValueError("choose a Raman shift/frequency column")
            if series.spectral_column not in z_frame.columns:
                raise ValueError(
                    f"missing Raman shift/frequency column '{series.spectral_column}'"
                )
            columns["spectral"] = self._numeric_column_values(
                workspace,
                z_dataset_name,
                series.spectral_column,
                "Raman shift/frequency",
            )
        point_count = min(len(column) for column in columns.values())
        if point_count == 0:
            raise ValueError("no numeric X/Y/Z points to plot")

        aligned = pd.DataFrame(
            {
                key: column.iloc[:point_count].to_numpy()
                for key, column in columns.items()
            }
        ).dropna()

        if series.plot_type in _SPECTRAL_PLOT_TYPES:
            points = self._spectral_slice_points(aligned, series)
        else:
            points = aligned.groupby(["x", "y"], as_index=False)["z"].mean()
        if x_scale == "log":
            points = points[points["x"] > 0]
        if y_scale == "log":
            points = points[points["y"] > 0]
        if points.empty:
            raise ValueError("no numeric X/Y/Z points remain after scale filtering")

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

    @staticmethod
    def _spectral_slice_points(aligned: pd.DataFrame, series: PlotSeries) -> pd.DataFrame:
        """Return one sampled intensity value per spatial X/Y coordinate."""
        center = float(series.spectral_center)
        if not np.isfinite(center):
            raise ValueError("Raman shift/frequency center must be finite")

        sampling = str(series.spectral_sampling or "nearest").strip().lower()
        if sampling == "nearest":
            candidates = aligned.assign(
                _distance=(aligned["spectral"] - center).abs()
            )
            nearest_rows = candidates.groupby(
                ["x", "y"],
                sort=False,
            )["_distance"].idxmin()
            return candidates.loc[nearest_rows, ["x", "y", "z"]].reset_index(
                drop=True
            )
        if sampling != "linear":
            raise ValueError(f"unknown spectral sampling method '{series.spectral_sampling}'")

        sampled: list[tuple[float, float, float]] = []
        for (x_value, y_value), pixel in aligned.groupby(["x", "y"], sort=False):
            spectrum = (
                pixel.groupby("spectral", as_index=False, sort=True)["z"]
                .mean()
                .dropna()
            )
            if spectrum.empty:
                continue
            shifts = spectrum["spectral"].to_numpy(dtype=float)
            intensities = spectrum["z"].to_numpy(dtype=float)
            if center < shifts[0] or center > shifts[-1]:
                continue
            sampled.append((
                float(x_value),
                float(y_value),
                float(np.interp(center, shifts, intensities)),
            ))

        if not sampled:
            raise ValueError(
                "the selected Raman shift/frequency is outside every pixel spectrum"
            )
        return pd.DataFrame(sampled, columns=["x", "y", "z"])

    def _interpolated_surface_grid(
        self,
        surface_values: _SurfaceValues,
    ) -> tuple[np.ndarray, np.ndarray, np.ma.MaskedArray]:
        """Return a native regular grid when possible or an interpolated grid."""
        render_mode = str(surface_values.series.surface_render_mode or "auto")
        if render_mode in {"auto", "native"}:
            native = self._native_surface_grid(surface_values)
            if native is not None:
                return native
            if render_mode == "native":
                raise ValueError(
                    "Native grid mode requires one complete value for every X/Y grid cell."
                )

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
        if surface_values.series.mask_outside_boundary:
            points = np.column_stack((surface_values.x_values, surface_values.y_values))
            targets = np.column_stack((grid_x.ravel(), grid_y.ravel()))
            try:
                outside = Delaunay(points).find_simplex(targets) < 0
                grid_z = np.asarray(grid_z, dtype=float)
                grid_z.ravel()[outside] = np.nan
            except Exception:
                pass
        return grid_x, grid_y, np.ma.masked_invalid(grid_z)

    @staticmethod
    def _native_surface_grid(
        surface_values: _SurfaceValues,
    ) -> tuple[np.ndarray, np.ndarray, np.ma.MaskedArray] | None:
        """Return the original complete Cartesian grid without interpolation."""
        frame = pd.DataFrame({
            "x": surface_values.x_values,
            "y": surface_values.y_values,
            "z": surface_values.z_values,
        })
        if frame.duplicated(["x", "y"]).any():
            frame = frame.groupby(["x", "y"], as_index=False)["z"].mean()
        x_values = np.sort(frame["x"].unique())
        y_values = np.sort(frame["y"].unique())
        if len(frame) != len(x_values) * len(y_values):
            return None
        pivot = frame.pivot(index="y", columns="x", values="z").reindex(
            index=y_values, columns=x_values
        )
        if pivot.isna().any().any():
            return None
        grid_x, grid_y = np.meshgrid(x_values, y_values)
        return grid_x, grid_y, np.ma.masked_invalid(pivot.to_numpy(dtype=float))

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
                "label": series.legend_label,
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
                label=series.legend_label,
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
                label=series.legend_label,
                color=series.color if series.color else None,
                alpha=series.fill_alpha,
            )
            return

        if plot_type == "barh":
            target_axes.barh(
                x_values,
                y_values,
                height=series.bar_width,
                label=series.legend_label,
                color=series.color if series.color else None,
                alpha=series.fill_alpha,
            )
            return

        if plot_type in _COMPOSITION_PLOT_TYPES:
            values = y_values.to_numpy(dtype=float)
            labels = [self._format_category_label(value) for value in x_values]
            if values.size == 0 or not np.isfinite(values).all() or np.sum(values) <= 0:
                raise ValueError("composition plots need at least one positive finite value")
            if plot_type in _PIE_PLOT_TYPES:
                wedgeprops: dict[str, object] = {"edgecolor": "white"}
                if plot_type == "donut":
                    wedgeprops["width"] = 0.38
                target_axes.pie(
                    values,
                    labels=labels,
                    autopct="%1.1f%%",
                    startangle=90,
                    counterclock=False,
                    wedgeprops=wedgeprops,
                )
                target_axes.axis("equal")
            else:
                self._draw_voronoi_composition(
                    target_axes=target_axes,
                    labels=labels,
                    values=values,
                    shape=series.voronoi_shape,
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
                label=series.legend_label,
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
                label=series.legend_label,
                color=series.color if series.color else None,
                alpha=series.fill_alpha,
            )
            return

        target_axes.plot(x_values, y_values, **plot_kwargs)

    def _draw_voronoi_composition(
        self,
        target_axes: Any,
        labels: list[str],
        values: np.ndarray,
        shape: str,
    ) -> None:
        """Draw a value-weighted polygonal Voronoi-style composition chart."""
        values = np.asarray(values, dtype=float)
        valid = np.isfinite(values) & (values > 0)
        labels = [label for label, keep in zip(labels, valid) if keep]
        values = values[valid]
        if values.size == 0 or np.sum(values) <= 0:
            raise ValueError("Voronoi composition needs at least one positive finite value")

        shape_key = self._normalized_voronoi_shape(shape)
        container = self._voronoi_container_polygon(shape_key)
        seeds = self._voronoi_seed_points(len(values), shape_key)
        weights = self._power_voronoi_weights(shape_key, seeds, values)
        polygons = self._power_voronoi_polygons(container, seeds, weights)
        colors = [f"C{index % 10}" for index in range(len(values))]

        for index, polygon in enumerate(polygons):
            if polygon.shape[0] < 3:
                continue
            target_axes.fill(
                polygon[:, 0],
                polygon[:, 1],
                facecolor=colors[index],
                edgecolor="white",
                linewidth=1.1,
                alpha=0.92,
                antialiased=True,
            )

        self._draw_voronoi_container_outline(target_axes, shape_key)
        self._label_voronoi_polygons(
            target_axes=target_axes,
            polygons=polygons,
            labels=labels,
            values=values,
        )
        target_axes.set_xlim(-1.05, 1.05)
        target_axes.set_ylim(-1.05, 1.05)
        target_axes.set_xticks([])
        target_axes.set_yticks([])
        target_axes.set_aspect("equal")
        target_axes.grid(False)
        target_axes.set_frame_on(False)

    def _voronoi_container_polygon(self, shape: str) -> np.ndarray:
        """Return a clipping polygon for the requested Voronoi composition container."""
        if shape == "rectangle":
            return np.array(
                [
                    [-1.0, -1.0],
                    [1.0, -1.0],
                    [1.0, 1.0],
                    [-1.0, 1.0],
                ],
                dtype=float,
            )
        if shape == "polygon":
            return self._polygon_container_vertices()

        angles = np.linspace(0.0, 2.0 * np.pi, 97)[:-1]
        return np.column_stack([np.cos(angles), np.sin(angles)])

    @staticmethod
    def _normalized_voronoi_shape(shape: str) -> str:
        """Return the supported Voronoi container shape key."""
        key = str(shape or "circle").strip().lower()
        if key in {"rect", "rectangle", "rectangular"}:
            return "rectangle"
        if key in {"polygon", "polygonal", "poly", "hexagon", "hexagonal"}:
            return "polygon"
        return "circle"

    @staticmethod
    def _voronoi_grid_resolution(item_count: int) -> int:
        """Keep the weighted grid responsive as composition item counts grow."""
        if item_count <= 20:
            return 170
        if item_count <= 60:
            return 140
        if item_count <= 150:
            return 100
        return 70

    def _voronoi_container_grid(
        self,
        shape: str,
        resolution: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return a square grid and a mask for the requested composition container."""
        axis = np.linspace(-1.0, 1.0, max(int(resolution), 20))
        grid_x, grid_y = np.meshgrid(axis, axis)
        if shape == "rectangle":
            mask = np.ones(grid_x.shape, dtype=bool)
        elif shape == "polygon":
            vertices = self._polygon_container_vertices()
            path = MplPath(vertices)
            mask = path.contains_points(np.column_stack([grid_x.ravel(), grid_y.ravel()]))
            mask = mask.reshape(grid_x.shape)
        else:
            mask = (grid_x * grid_x + grid_y * grid_y) <= 1.0
        return grid_x, grid_y, mask

    @staticmethod
    def _polygon_container_vertices() -> np.ndarray:
        """Return vertices for the default polygonal Voronoi container."""
        angles = np.linspace(np.pi / 2.0, np.pi / 2.0 + 2.0 * np.pi, 7)[:-1]
        return np.column_stack([np.cos(angles), np.sin(angles)])

    @staticmethod
    def _voronoi_seed_points(item_count: int, shape: str) -> np.ndarray:
        """Place deterministic seeds inside the selected Voronoi container."""
        if item_count <= 1:
            return np.array([[0.0, 0.0]], dtype=float)

        index = np.arange(item_count, dtype=float)
        golden_angle = np.pi * (3.0 - np.sqrt(5.0))
        radius = np.sqrt((index + 0.5) / item_count)
        max_radius = 0.74 if shape in {"circle", "polygon"} else 0.82
        angles = index * golden_angle
        points = np.column_stack([
            np.cos(angles) * radius * max_radius,
            np.sin(angles) * radius * max_radius,
        ])
        if shape == "rectangle":
            points[:, 0] *= 1.15
            points[:, 1] *= 0.95
        return points

    def _weighted_voronoi_assignments(
        self,
        points: np.ndarray,
        seeds: np.ndarray,
        values: np.ndarray,
    ) -> np.ndarray:
        """Assign grid points to nearby seeds while matching value-proportional areas."""
        point_count = len(points)
        seed_count = len(seeds)
        target_counts = self._proportional_voronoi_counts(values, point_count)
        distances = np.sum((points[:, None, :] - seeds[None, :, :]) ** 2, axis=2)
        order = np.argsort(distances, axis=None)

        assignments = np.full(point_count, -1, dtype=int)
        remaining = target_counts.astype(int).copy()
        assigned_count = 0
        for flat_index in order:
            point_index = int(flat_index // seed_count)
            seed_index = int(flat_index % seed_count)
            if assignments[point_index] >= 0 or remaining[seed_index] <= 0:
                continue
            assignments[point_index] = seed_index
            remaining[seed_index] -= 1
            assigned_count += 1
            if assigned_count >= point_count:
                break

        if assigned_count < point_count:
            missing = np.flatnonzero(assignments < 0)
            assignments[missing] = np.argmin(distances[missing], axis=1)
        return assignments

    def _power_voronoi_weights(
        self,
        shape: str,
        seeds: np.ndarray,
        values: np.ndarray,
    ) -> np.ndarray:
        """Estimate additive weights so polygon areas follow composition values."""
        if len(values) <= 1:
            return np.zeros(len(values), dtype=float)

        resolution = self._voronoi_grid_resolution(len(values))
        grid_x, grid_y, mask = self._voronoi_container_grid(shape, resolution)
        points = np.column_stack([grid_x[mask], grid_y[mask]])
        if points.size == 0:
            return np.zeros(len(values), dtype=float)

        target = values / np.sum(values)
        weights = np.zeros(len(values), dtype=float)
        distances = np.sum((points[:, None, :] - seeds[None, :, :]) ** 2, axis=2)
        gain = 0.32
        for _iteration in range(90):
            assignments = np.argmin(distances - weights[None, :], axis=1)
            counts = np.bincount(assignments, minlength=len(values)).astype(float)
            current = counts / max(float(np.sum(counts)), 1.0)
            error = target - current
            if float(np.max(np.abs(error))) < 0.006:
                break
            weights += gain * error
            weights -= float(np.mean(weights))
            gain *= 0.985
        return weights

    def _power_voronoi_polygons(
        self,
        container: np.ndarray,
        seeds: np.ndarray,
        weights: np.ndarray,
    ) -> list[np.ndarray]:
        """Build clipped power-diagram cells as ordinary polygons."""
        polygons: list[np.ndarray] = []
        for index, seed in enumerate(seeds):
            polygon = np.asarray(container, dtype=float)
            for other_index, other_seed in enumerate(seeds):
                if other_index == index or polygon.shape[0] < 3:
                    continue
                normal = 2.0 * (other_seed - seed)
                limit = (
                    float(np.dot(other_seed, other_seed))
                    - float(np.dot(seed, seed))
                    + float(weights[index])
                    - float(weights[other_index])
                )
                polygon = self._clip_polygon_to_half_plane(polygon, normal, limit)
            polygons.append(polygon)
        return polygons

    @staticmethod
    def _clip_polygon_to_half_plane(
        polygon: np.ndarray,
        normal: np.ndarray,
        limit: float,
    ) -> np.ndarray:
        """Clip a polygon to the half-plane normal dot point <= limit."""
        if polygon.shape[0] < 3:
            return np.empty((0, 2), dtype=float)

        clipped: list[np.ndarray] = []
        epsilon = 1e-9
        previous = polygon[-1]
        previous_value = float(np.dot(normal, previous) - limit)
        previous_inside = previous_value <= epsilon

        for current in polygon:
            current_value = float(np.dot(normal, current) - limit)
            current_inside = current_value <= epsilon
            if current_inside != previous_inside:
                direction = current - previous
                denominator = float(np.dot(normal, direction))
                if abs(denominator) > epsilon:
                    ratio = (limit - float(np.dot(normal, previous))) / denominator
                    clipped.append(previous + np.clip(ratio, 0.0, 1.0) * direction)
            if current_inside:
                clipped.append(current)
            previous = current
            previous_inside = current_inside

        if not clipped:
            return np.empty((0, 2), dtype=float)
        return np.asarray(clipped, dtype=float)

    @staticmethod
    def _proportional_voronoi_counts(values: np.ndarray, point_count: int) -> np.ndarray:
        """Return integer grid-cell counts proportional to the composition values."""
        weights = values / np.sum(values)
        raw_counts = weights * point_count
        counts = np.floor(raw_counts).astype(int)
        remainder = int(point_count - np.sum(counts))
        if remainder > 0:
            order = np.argsort(raw_counts - counts)[::-1]
            for index in order[:remainder]:
                counts[index] += 1
        elif remainder < 0:
            order = np.argsort(raw_counts - counts)
            for index in order:
                if remainder == 0:
                    break
                removable = min(counts[index], -remainder)
                counts[index] -= removable
                remainder += removable
        return counts

    def _draw_voronoi_container_outline(self, target_axes: Any, shape: str) -> None:
        """Draw the visible boundary of the Voronoi composition container."""
        if shape == "rectangle":
            x_values = [-1.0, 1.0, 1.0, -1.0, -1.0]
            y_values = [-1.0, -1.0, 1.0, 1.0, -1.0]
        elif shape == "polygon":
            vertices = self._polygon_container_vertices()
            closed = np.vstack([vertices, vertices[0]])
            x_values = closed[:, 0]
            y_values = closed[:, 1]
        else:
            angles = np.linspace(0.0, 2.0 * np.pi, 361)
            x_values = np.cos(angles)
            y_values = np.sin(angles)
        target_axes.plot(x_values, y_values, color="black", linewidth=0.9)

    @staticmethod
    def _label_voronoi_polygons(
        target_axes: Any,
        polygons: list[np.ndarray],
        labels: list[str],
        values: np.ndarray,
    ) -> None:
        """Place compact labels at polygon centroids for readable Voronoi regions."""
        total = float(np.sum(values))
        item_count = len(values)
        for polygon, label, value in zip(polygons, labels, values):
            if polygon.shape[0] < 3:
                continue
            percentage = 100.0 * float(value) / total if total > 0 else 0.0
            if item_count > 18 and percentage < 3.0:
                continue
            area, centroid = PlotCanvas._polygon_area_and_centroid(polygon)
            if area <= 0.004:
                continue
            text = f"{label}\n{percentage:.1f}%" if item_count <= 30 else f"{percentage:.1f}%"
            target_axes.text(
                float(centroid[0]),
                float(centroid[1]),
                text,
                ha="center",
                va="center",
                fontsize=8 if item_count <= 18 else 7,
                color="black",
            )

    @staticmethod
    def _polygon_area_and_centroid(polygon: np.ndarray) -> tuple[float, np.ndarray]:
        """Return polygon area and centroid, falling back to vertex mean if degenerate."""
        x_values = polygon[:, 0]
        y_values = polygon[:, 1]
        shifted_x = np.roll(x_values, -1)
        shifted_y = np.roll(y_values, -1)
        cross = x_values * shifted_y - shifted_x * y_values
        signed_area = 0.5 * float(np.sum(cross))
        if abs(signed_area) < 1e-12:
            return 0.0, np.mean(polygon, axis=0)
        centroid = np.array(
            [
                float(np.sum((x_values + shifted_x) * cross) / (6.0 * signed_area)),
                float(np.sum((y_values + shifted_y) * cross) / (6.0 * signed_area)),
            ],
            dtype=float,
        )
        return abs(signed_area), centroid

    def _draw_surface_by_type(
        self,
        target_axes: Any,
        series_index: int,
        series: PlotSeries,
        surface_values: _SurfaceValues,
        grid_x: np.ndarray,
        grid_y: np.ndarray,
        grid_z: np.ma.MaskedArray,
    ) -> None:
        """Draw an interpolated X/Y/Z surface using its explicit plot type."""
        if grid_z.count() == 0:
            raise ValueError("interpolation produced no plottable grid values")
        color_map = colormaps.get_cmap(series.color_map or "viridis").copy()
        color_map.set_bad(series.color_bad or "#d9d9d9")
        if series.color_under:
            color_map.set_under(series.color_under)
        if series.color_over:
            color_map.set_over(series.color_over)
        normalization, minimum, maximum = self._surface_normalization(series, grid_z)
        levels = self._surface_contour_levels(series, minimum, maximum)
        common = {
            "cmap": color_map,
            "norm": normalization,
            "alpha": min(max(float(series.surface_alpha), 0.0), 1.0),
        }

        if series.plot_type in {"contour", "spectra_contour"}:
            line_kwargs: dict[str, object] = dict(common)
            if series.contour_line_color:
                line_kwargs.pop("cmap", None)
                line_kwargs.pop("norm", None)
                line_kwargs["colors"] = series.contour_line_color
            mappable = target_axes.contour(
                grid_x,
                grid_y,
                grid_z,
                levels=levels,
                linewidths=max(float(series.contour_line_width), 0.0),
                linestyles=series.contour_line_style or "solid",
                **line_kwargs,
            )
            if series.contour_labels:
                target_axes.clabel(
                    mappable,
                    inline=True,
                    fontsize=8,
                    fmt=self._matplotlib_number_format(series.contour_label_format),
                )
        elif series.plot_type in {"contourf", "spectra_contourf"}:
            mappable = target_axes.contourf(
                grid_x,
                grid_y,
                grid_z,
                levels=levels,
                extend="both" if series.color_under or series.color_over else "neither",
                **common,
            )
            if series.contour_overlay:
                overlay_kwargs: dict[str, object] = {
                    "levels": levels,
                    "linewidths": max(float(series.contour_line_width), 0.0),
                    "linestyles": series.contour_line_style or "solid",
                    "alpha": min(max(float(series.surface_alpha), 0.0), 1.0),
                }
                if series.contour_line_color:
                    overlay_kwargs["colors"] = series.contour_line_color
                else:
                    overlay_kwargs["colors"] = "black"
                lines = target_axes.contour(grid_x, grid_y, grid_z, **overlay_kwargs)
                if series.contour_labels:
                    target_axes.clabel(
                        lines,
                        inline=True,
                        fontsize=8,
                        fmt=self._matplotlib_number_format(series.contour_label_format),
                    )
        else:
            mappable = target_axes.pcolormesh(
                grid_x,
                grid_y,
                grid_z,
                shading="auto",
                **common,
            )

        self._draw_surface_validity_overlays(target_axes, surface_values, series)
        self._draw_surface_extrema(
            target_axes, surface_values, grid_x, grid_y, grid_z, series
        )
        target_axes.set_aspect("equal" if series.surface_aspect == "equal" else "auto")

        colorbar = self.figure.colorbar(mappable, ax=target_axes)
        colorbar_label = series.colorbar_label or self.default_colorbar_label(series)
        colorbar.set_label(colorbar_label)
        self._colorbar_labels.append((series_index, colorbar.ax.yaxis.label))

    @staticmethod
    def _matplotlib_number_format(value: str) -> str:
        """Return a safe Matplotlib format string from a compact Python format."""
        clean = str(value or ".4g").strip()
        return clean if clean.startswith("%") else "%" + clean

    @staticmethod
    def _surface_contour_levels(
        series: PlotSeries,
        minimum: float,
        maximum: float,
    ) -> int | np.ndarray:
        """Return validated contour levels from count, interval, or explicit values."""
        mode = str(series.contour_level_mode or "count")
        if mode == "custom":
            tokens = [
                token for token in str(series.contour_custom_levels).replace(",", " ").replace(";", " ").split()
                if token
            ]
            try:
                levels = np.asarray(sorted({float(token) for token in tokens}), dtype=float)
            except ValueError as exc:
                raise ValueError("Custom contour levels must be numeric values.") from exc
            levels = levels[np.isfinite(levels)]
            if len(levels) < 2:
                raise ValueError("Enter at least two distinct custom contour levels.")
            return levels
        if mode == "interval":
            interval = float(series.contour_interval)
            if not np.isfinite(interval) or interval <= 0:
                raise ValueError("Contour interval must be a positive finite number.")
            start = np.floor(minimum / interval) * interval
            levels = np.arange(start, maximum + interval, interval, dtype=float)
            levels = levels[(levels >= minimum) & (levels <= maximum)]
            if len(levels) < 2:
                return np.linspace(minimum, maximum, 2)
            if len(levels) > 1000:
                raise ValueError("Contour interval creates more than 1,000 levels.")
            return levels
        return max(2, min(int(series.contour_level_count), 256))

    @staticmethod
    def _surface_normalization(
        series: PlotSeries,
        grid_z: np.ma.MaskedArray,
    ) -> tuple[mpl_colors.Normalize, float, float]:
        """Return colour normalization and its effective finite range."""
        values = np.asarray(grid_z.compressed(), dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            raise ValueError("surface contains no finite values")
        mode = str(series.color_scale_mode or "auto")
        if mode == "manual":
            try:
                minimum = float(str(series.color_minimum).strip())
                maximum = float(str(series.color_maximum).strip())
            except ValueError as exc:
                raise ValueError("Manual colour limits require numeric minimum and maximum values.") from exc
        elif mode == "percentile":
            low = min(max(float(series.color_percentile_low), 0.0), 100.0)
            high = min(max(float(series.color_percentile_high), 0.0), 100.0)
            if low >= high:
                raise ValueError("Lower colour percentile must be below the upper percentile.")
            minimum, maximum = (float(value) for value in np.percentile(values, [low, high]))
        else:
            minimum, maximum = float(np.min(values)), float(np.max(values))
        if not np.isfinite(minimum) or not np.isfinite(maximum) or minimum >= maximum:
            if minimum == maximum:
                padding = max(abs(minimum) * 1e-9, 1e-12)
                minimum -= padding
                maximum += padding
            else:
                raise ValueError("Colour scale minimum must be below maximum.")

        normalization = str(series.color_normalization or "linear")
        if normalization == "log":
            positive = values[values > 0]
            if positive.size == 0 or maximum <= 0:
                raise ValueError("Log colour normalization requires positive Z values.")
            minimum = max(minimum, float(np.min(positive)))
            norm: mpl_colors.Normalize = mpl_colors.LogNorm(minimum, maximum)
        elif normalization == "symlog":
            threshold = max(max(abs(minimum), abs(maximum)) * 1e-3, 1e-12)
            norm = mpl_colors.SymLogNorm(threshold, vmin=minimum, vmax=maximum)
        elif normalization == "centered":
            center = float(series.color_center)
            if not minimum < center < maximum:
                raise ValueError("Diverging colour center must lie between the colour limits.")
            norm = mpl_colors.TwoSlopeNorm(vcenter=center, vmin=minimum, vmax=maximum)
        else:
            norm = mpl_colors.Normalize(minimum, maximum)
        return norm, minimum, maximum

    @staticmethod
    def _draw_surface_validity_overlays(
        target_axes: Any,
        surface_values: _SurfaceValues,
        series: PlotSeries,
    ) -> None:
        """Draw optional measured points, Delaunay mesh, and convex-hull boundary."""
        x_values = surface_values.x_values
        y_values = surface_values.y_values
        points = np.column_stack((x_values, y_values))
        if series.show_triangulation and len(points) >= 3:
            target_axes.triplot(x_values, y_values, color="0.35", linewidth=0.45, alpha=0.6)
        if series.show_boundary and len(points) >= 3:
            try:
                hull = ConvexHull(points)
                closed = np.append(hull.vertices, hull.vertices[0])
                target_axes.plot(
                    x_values[closed], y_values[closed], color="black", linewidth=1.1,
                    linestyle="--", alpha=0.85,
                )
            except Exception:
                pass
        if series.show_data_points:
            target_axes.scatter(
                x_values, y_values, s=12.0, marker="o", facecolors="white",
                edgecolors="black", linewidths=0.55, alpha=0.9, zorder=4,
                label="_nolegend_",
            )

    def surface_extrema(
        self,
        surface_values: _SurfaceValues,
        grid_x: np.ndarray,
        grid_y: np.ndarray,
        grid_z: np.ma.MaskedArray,
        series: PlotSeries,
    ) -> list[SurfaceExtremum]:
        """Return selected global/local extrema with measured/interpolated provenance."""
        if series.extrema_source == "interpolated":
            x_values = np.asarray(grid_x, dtype=float)
            y_values = np.asarray(grid_y, dtype=float)
            z_values = np.asarray(grid_z.filled(np.nan), dtype=float)
            source = "interpolated"
        else:
            x_values = np.asarray(surface_values.x_values, dtype=float)
            y_values = np.asarray(surface_values.y_values, dtype=float)
            z_values = np.asarray(surface_values.z_values, dtype=float)
            source = "measured"
        valid = np.isfinite(z_values)
        if not np.any(valid):
            return []
        extrema: list[SurfaceExtremum] = []
        if series.show_global_maximum:
            extrema.append(self._global_extremum(x_values, y_values, z_values, valid, "maximum", source))
        if series.show_global_minimum:
            extrema.append(self._global_extremum(x_values, y_values, z_values, valid, "minimum", source))
        if series.show_local_maxima or series.show_local_minima:
            if z_values.ndim == 2:
                local = self._local_surface_extrema(
                    x_values, y_values, z_values, series, source, extrema
                )
            else:
                local = self._local_measured_extrema(
                    x_values, y_values, z_values, series, source, extrema
                )
            extrema.extend(local)
        return extrema

    @staticmethod
    def _global_extremum(
        x_values: np.ndarray,
        y_values: np.ndarray,
        z_values: np.ndarray,
        valid: np.ndarray,
        kind: str,
        source: str,
    ) -> SurfaceExtremum:
        """Return one centroid-nearest representative for a tied global extremum."""
        target = np.nanmax(z_values) if kind == "maximum" else np.nanmin(z_values)
        candidates = np.argwhere(valid & np.isclose(z_values, target, rtol=1e-12, atol=1e-15))
        if z_values.ndim == 1:
            indexes = candidates[:, 0]
            cx, cy = np.mean(x_values[indexes]), np.mean(y_values[indexes])
            chosen = indexes[np.argmin((x_values[indexes] - cx) ** 2 + (y_values[indexes] - cy) ** 2)]
            return SurfaceExtremum(kind, float(x_values[chosen]), float(y_values[chosen]), float(target), source)
        cx = float(np.mean(x_values[tuple(candidates.T)]))
        cy = float(np.mean(y_values[tuple(candidates.T)]))
        distances = (x_values[tuple(candidates.T)] - cx) ** 2 + (y_values[tuple(candidates.T)] - cy) ** 2
        row, column = candidates[int(np.argmin(distances))]
        return SurfaceExtremum(kind, float(x_values[row, column]), float(y_values[row, column]), float(target), source)

    @staticmethod
    def _local_surface_extrema(
        x_values: np.ndarray,
        y_values: np.ndarray,
        z_values: np.ndarray,
        series: PlotSeries,
        source: str,
        existing: list[SurfaceExtremum],
    ) -> list[SurfaceExtremum]:
        """Return prominence-filtered local extrema with greedy physical separation."""
        valid = np.isfinite(z_values)
        filled_max = np.where(valid, z_values, -np.inf)
        filled_min = np.where(valid, z_values, np.inf)
        local_max = valid & (filled_max == ndimage.maximum_filter(filled_max, size=3, mode="nearest"))
        local_min = valid & (filled_min == ndimage.minimum_filter(filled_min, size=3, mode="nearest"))
        local_floor = ndimage.minimum_filter(filled_min, size=3, mode="nearest")
        local_ceiling = ndimage.maximum_filter(filled_max, size=3, mode="nearest")
        prominence = max(float(series.local_extrema_prominence), 0.0)
        candidates: list[tuple[float, SurfaceExtremum]] = []
        if series.show_local_maxima:
            for row, column in np.argwhere(local_max & ((z_values - local_floor) >= prominence)):
                score = float(z_values[row, column] - local_floor[row, column])
                candidates.append((score, SurfaceExtremum("maximum", float(x_values[row, column]), float(y_values[row, column]), float(z_values[row, column]), source, True)))
        if series.show_local_minima:
            for row, column in np.argwhere(local_min & ((local_ceiling - z_values) >= prominence)):
                score = float(local_ceiling[row, column] - z_values[row, column])
                candidates.append((score, SurfaceExtremum("minimum", float(x_values[row, column]), float(y_values[row, column]), float(z_values[row, column]), source, True)))
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected: list[SurfaceExtremum] = []
        separation = max(float(series.local_extrema_separation), 0.0)
        for _score, candidate in candidates:
            if any(np.hypot(candidate.x_value - item.x_value, candidate.y_value - item.y_value) <= max(separation, 1e-12) for item in [*existing, *selected]):
                continue
            selected.append(candidate)
            if len(selected) >= max(1, min(int(series.local_extrema_count), 100)):
                break
        return selected

    @staticmethod
    def _local_measured_extrema(
        x_values: np.ndarray,
        y_values: np.ndarray,
        z_values: np.ndarray,
        series: PlotSeries,
        source: str,
        existing: list[SurfaceExtremum],
    ) -> list[SurfaceExtremum]:
        """Return local extrema among measured Delaunay-neighbouring points."""
        points = np.column_stack((x_values, y_values))
        try:
            triangulation = Delaunay(points)
        except Exception:
            return []
        neighbours: list[set[int]] = [set() for _ in range(len(points))]
        for simplex in triangulation.simplices:
            for index in simplex:
                neighbours[int(index)].update(int(item) for item in simplex if item != index)

        threshold = max(float(series.local_extrema_prominence), 0.0)
        candidates: list[tuple[float, SurfaceExtremum]] = []
        for index, adjacent in enumerate(neighbours):
            if not adjacent or not np.isfinite(z_values[index]):
                continue
            adjacent_values = z_values[list(adjacent)]
            adjacent_values = adjacent_values[np.isfinite(adjacent_values)]
            if adjacent_values.size == 0:
                continue
            maximum_score = float(z_values[index] - np.max(adjacent_values))
            minimum_score = float(np.min(adjacent_values) - z_values[index])
            if series.show_local_maxima and maximum_score >= threshold:
                candidates.append((maximum_score, SurfaceExtremum(
                    "maximum", float(x_values[index]), float(y_values[index]),
                    float(z_values[index]), source, True,
                )))
            if series.show_local_minima and minimum_score >= threshold:
                candidates.append((minimum_score, SurfaceExtremum(
                    "minimum", float(x_values[index]), float(y_values[index]),
                    float(z_values[index]), source, True,
                )))

        candidates.sort(key=lambda item: item[0], reverse=True)
        selected: list[SurfaceExtremum] = []
        separation = max(float(series.local_extrema_separation), 0.0)
        for _score, candidate in candidates:
            if any(
                np.hypot(
                    candidate.x_value - item.x_value,
                    candidate.y_value - item.y_value,
                ) <= max(separation, 1e-12)
                for item in [*existing, *selected]
            ):
                continue
            selected.append(candidate)
            if len(selected) >= max(1, min(int(series.local_extrema_count), 100)):
                break
        return selected

    def _draw_surface_extrema(
        self,
        target_axes: Any,
        surface_values: _SurfaceValues,
        grid_x: np.ndarray,
        grid_y: np.ndarray,
        grid_z: np.ma.MaskedArray,
        series: PlotSeries,
    ) -> None:
        """Draw uncluttered extrema markers and provenance-aware callout labels."""
        extrema = self.surface_extrema(surface_values, grid_x, grid_y, grid_z, series)
        number_format = str(series.extrema_label_format or ".4g")
        offsets = ((8, 8), (8, -18), (-72, 8), (-72, -18))
        for index, item in enumerate(extrema):
            is_maximum = item.kind == "maximum"
            marker = "^" if is_maximum else "v"
            color = "#d62728" if is_maximum else "#1f77b4"
            target_axes.scatter([item.x_value], [item.y_value], marker=marker, s=72, color=color, edgecolors="white", linewidths=0.9, zorder=7, label="_nolegend_")
            if series.extrema_label_mode == "z":
                label = f"{item.kind[:3].title()} Z={format(item.z_value, number_format)}"
            else:
                label = (
                    f"{item.kind[:3].title()} ({item.source})\n"
                    f"X={format(item.x_value, number_format)}, Y={format(item.y_value, number_format)}\n"
                    f"Z={format(item.z_value, number_format)}"
                )
            target_axes.annotate(
                label, (item.x_value, item.y_value), xytext=offsets[index % len(offsets)],
                textcoords="offset points", fontsize=8, color="black",
                bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "alpha": 0.82, "edgecolor": color},
                arrowprops={"arrowstyle": "-", "color": color, "linewidth": 0.7}, zorder=8,
            )

    def surface_grid_frame(
        self,
        workspace: Workspace,
        series: PlotSeries,
    ) -> pd.DataFrame:
        """Return the rendered native/interpolated surface as tidy X/Y/Z rows."""
        surface = self._surface_values(workspace, series, "linear", "linear")
        grid_x, grid_y, grid_z = self._interpolated_surface_grid(surface)
        values = np.asarray(grid_z.filled(np.nan), dtype=float)
        return pd.DataFrame({
            "x": grid_x.ravel(),
            "y": grid_y.ravel(),
            "z": values.ravel(),
            "valid": np.isfinite(values).ravel().astype(int),
        })

    def surface_profile_frame(
        self,
        workspace: Workspace,
        series: PlotSeries,
        orientation: str,
        coordinate: float,
    ) -> pd.DataFrame:
        """Return the closest horizontal or vertical profile through a surface grid."""
        surface = self._surface_values(workspace, series, "linear", "linear")
        grid_x, grid_y, grid_z = self._interpolated_surface_grid(surface)
        if orientation == "vertical":
            column = int(np.argmin(np.abs(grid_x[0, :] - coordinate)))
            frame = pd.DataFrame({
                "distance": grid_y[:, column],
                "x": grid_x[:, column],
                "y": grid_y[:, column],
                "z": np.asarray(grid_z[:, column].filled(np.nan), dtype=float),
            })
        else:
            row = int(np.argmin(np.abs(grid_y[:, 0] - coordinate)))
            frame = pd.DataFrame({
                "distance": grid_x[row, :],
                "x": grid_x[row, :],
                "y": grid_y[row, :],
                "z": np.asarray(grid_z[row, :].filled(np.nan), dtype=float),
            })
        return frame.dropna(subset=["z"]).reset_index(drop=True)

    def surface_line_profile_frame(
        self,
        workspace: Workspace,
        series: PlotSeries,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        sample_count: int = 200,
    ) -> pd.DataFrame:
        """Return an interpolated profile between two arbitrary map coordinates."""
        count = max(2, min(int(sample_count), 10_000))
        start = np.asarray([float(start_x), float(start_y)], dtype=float)
        end = np.asarray([float(end_x), float(end_y)], dtype=float)
        if not np.all(np.isfinite([*start, *end])):
            raise ValueError("Line-profile coordinates must be finite numbers.")
        length = float(np.linalg.norm(end - start))
        if length <= 0.0:
            raise ValueError("The line-profile start and end points must be different.")

        surface = self._surface_values(workspace, series, "linear", "linear")
        fraction = np.linspace(0.0, 1.0, count)
        x_values = start[0] + fraction * (end[0] - start[0])
        y_values = start[1] + fraction * (end[1] - start[1])
        z_values = self._evaluate_surface(surface, x_values, y_values)
        if series.mask_outside_boundary:
            points = np.column_stack((surface.x_values, surface.y_values))
            targets = np.column_stack((x_values, y_values))
            try:
                z_values[Delaunay(points).find_simplex(targets) < 0] = np.nan
            except Exception:
                pass
        frame = pd.DataFrame({
            "distance": fraction * length,
            "fraction": fraction,
            "x": x_values,
            "y": y_values,
            "z": np.asarray(z_values, dtype=float),
        })
        return frame.dropna(subset=["z"]).reset_index(drop=True)

    def surface_roi_summary_frame(
        self,
        workspace: Workspace,
        series: PlotSeries,
        x_minimum: float,
        x_maximum: float,
        y_minimum: float,
        y_maximum: float,
    ) -> pd.DataFrame:
        """Return descriptive and integrated values inside one rectangular map ROI."""
        grid = self.surface_grid_frame(workspace, series)
        low_x, high_x = sorted((float(x_minimum), float(x_maximum)))
        low_y, high_y = sorted((float(y_minimum), float(y_maximum)))
        roi = grid[
            grid["x"].between(low_x, high_x)
            & grid["y"].between(low_y, high_y)
            & grid["z"].notna()
        ]
        if roi.empty:
            raise ValueError("The selected ROI contains no finite rendered map cells.")
        unique_x = np.sort(grid["x"].unique())
        unique_y = np.sort(grid["y"].unique())
        dx = float(np.median(np.diff(unique_x))) if len(unique_x) > 1 else 1.0
        dy = float(np.median(np.diff(unique_y))) if len(unique_y) > 1 else 1.0
        values = roi["z"].to_numpy(dtype=float)
        maximum_row = roi.loc[roi["z"].idxmax()]
        minimum_row = roi.loc[roi["z"].idxmin()]
        metrics: list[tuple[str, float]] = [
            ("cell_count", float(len(values))),
            ("mean", float(np.mean(values))),
            ("median", float(np.median(values))),
            ("standard_deviation", float(np.std(values, ddof=1)) if len(values) > 1 else 0.0),
            ("minimum", float(np.min(values))),
            ("minimum_x", float(minimum_row["x"])),
            ("minimum_y", float(minimum_row["y"])),
            ("maximum", float(np.max(values))),
            ("maximum_x", float(maximum_row["x"])),
            ("maximum_y", float(maximum_row["y"])),
            ("integrated_z_dx_dy", float(np.sum(values) * abs(dx * dy))),
            ("x_minimum", low_x),
            ("x_maximum", high_x),
            ("y_minimum", low_y),
            ("y_maximum", high_y),
        ]
        return pd.DataFrame(metrics, columns=["metric", "value"])

    def surface_contours_frame(
        self,
        workspace: Workspace,
        series: PlotSeries,
    ) -> pd.DataFrame:
        """Extract rendered contour vertices and enclosed polygon areas."""
        surface = self._surface_values(workspace, series, "linear", "linear")
        grid_x, grid_y, grid_z = self._interpolated_surface_grid(surface)
        _norm, minimum, maximum = self._surface_normalization(series, grid_z)
        levels = self._surface_contour_levels(series, minimum, maximum)
        if isinstance(levels, int):
            levels = np.linspace(minimum, maximum, levels)
        figure = Figure()
        axes = figure.add_subplot(111)
        contour_set = axes.contour(grid_x, grid_y, grid_z, levels=levels)
        rows: list[dict[str, float | int]] = []
        for level, segments in zip(contour_set.levels, contour_set.allsegs):
            for segment_index, segment in enumerate(segments):
                if len(segment) < 2:
                    continue
                area = 0.0
                if len(segment) >= 3 and np.allclose(segment[0], segment[-1]):
                    area = 0.5 * abs(float(np.sum(
                        segment[:, 0] * np.roll(segment[:, 1], -1)
                        - np.roll(segment[:, 0], -1) * segment[:, 1]
                    )))
                for vertex_index, (x_value, y_value) in enumerate(segment):
                    rows.append({
                        "level": float(level),
                        "segment": int(segment_index),
                        "vertex": int(vertex_index),
                        "x": float(x_value),
                        "y": float(y_value),
                        "enclosed_area": area,
                    })
        if not rows:
            raise ValueError("No contour vertices could be extracted for these levels.")
        return pd.DataFrame(rows)

    @staticmethod
    def default_colorbar_label(series: PlotSeries) -> str:
        """Return the automatic colour-bar label for a surface series."""
        colorbar_label = series.z_column or series.label
        if series.plot_type in _SPECTRAL_PLOT_TYPES:
            return (
                f"{colorbar_label} at {series.spectral_column} = "
                f"{series.spectral_center:g}"
            )
        return colorbar_label

    def _install_surface_coordinate_reader(
        self,
        rendered_surfaces: list[
            tuple[_SurfaceValues, np.ndarray, np.ndarray, np.ma.MaskedArray]
        ],
    ) -> None:
        """Show interpolated map values in Matplotlib's live mouse-coordinate reader."""
        self._rendered_surface_grids = list(rendered_surfaces)
        self.coordinate_readout.setText("Move the mouse over the map to read X, Y, and intensity")
        self.coordinate_readout.setVisible(True)
        self.axes.format_coord = self._format_surface_coordinate

    def _format_surface_coordinate(self, x_value: float, y_value: float) -> str:
        """Return a stable X/Y/Z readout for the currently rendered surfaces."""
        text = f"x={x_value:.6g}, y={y_value:.6g}"
        readouts: list[str] = []
        for surface, grid_x, grid_y, grid_z in self._rendered_surface_grids:
            z_value = self._surface_grid_value(
                grid_x,
                grid_y,
                grid_z,
                x_value,
                y_value,
            )
            if z_value is None:
                z_value = self._nearest_surface_value(surface, x_value, y_value)
            if z_value is None:
                continue
            value_label = surface.series.z_column or "Z"
            if len(self._rendered_surface_grids) > 1:
                value_label = f"{surface.series.label} {value_label}"
            readouts.append(f"{value_label}={z_value:.6g}")
        if readouts:
            text += ", " + ", ".join(readouts)
        return text

    def _handle_canvas_motion(self, event: object) -> None:
        """Keep the dedicated map readout visible even when toolbar space is narrow."""
        if not self._rendered_surface_grids or getattr(event, "inaxes", None) is not self.axes:
            return
        x_value = getattr(event, "xdata", None)
        y_value = getattr(event, "ydata", None)
        if x_value is None or y_value is None:
            return
        if self._surface_cut_pick_active and len(self._surface_cut_points) == 1:
            start = self._surface_cut_points[0]
            self._draw_surface_cut_overlay(
                start,
                (float(x_value), float(y_value)),
            )
        text = self._format_surface_coordinate(float(x_value), float(y_value))
        if self._surface_cut_pick_active:
            if self._surface_cut_points:
                text = "Cut end: " + text
            else:
                text = "Cut start: " + text
        self.coordinate_readout.setText(text)
        self.toolbar.set_message(text)

    @staticmethod
    def _nearest_surface_value(
        surface: _SurfaceValues,
        x_value: float,
        y_value: float,
    ) -> float | None:
        """Return the nearest measured surface value when a grid cell is masked."""
        if not np.isfinite(x_value) or not np.isfinite(y_value):
            return None
        distances = np.square(surface.x_values - x_value) + np.square(
            surface.y_values - y_value
        )
        finite = np.isfinite(distances) & np.isfinite(surface.z_values)
        if not finite.any():
            return None
        finite_indices = np.flatnonzero(finite)
        nearest = finite_indices[int(np.argmin(distances[finite]))]
        return float(surface.z_values[nearest])

    @staticmethod
    def _surface_grid_value(
        grid_x: np.ndarray,
        grid_y: np.ndarray,
        grid_z: np.ma.MaskedArray,
        x_value: float,
        y_value: float,
    ) -> float | None:
        """Bilinearly sample a rendered regular surface grid at one cursor position."""
        if not np.isfinite(x_value) or not np.isfinite(y_value):
            return None
        x_axis = np.asarray(grid_x[0, :], dtype=float)
        y_axis = np.asarray(grid_y[:, 0], dtype=float)
        if (
            x_axis.size < 2
            or y_axis.size < 2
            or x_value < x_axis[0]
            or x_value > x_axis[-1]
            or y_value < y_axis[0]
            or y_value > y_axis[-1]
        ):
            return None

        x_index = int(np.clip(np.searchsorted(x_axis, x_value) - 1, 0, x_axis.size - 2))
        y_index = int(np.clip(np.searchsorted(y_axis, y_value) - 1, 0, y_axis.size - 2))
        x0, x1 = x_axis[x_index], x_axis[x_index + 1]
        y0, y1 = y_axis[y_index], y_axis[y_index + 1]
        x_fraction = 0.0 if x1 == x0 else float((x_value - x0) / (x1 - x0))
        y_fraction = 0.0 if y1 == y0 else float((y_value - y0) / (y1 - y0))

        cell = np.ma.asarray(
            grid_z[y_index : y_index + 2, x_index : x_index + 2]
        )
        if cell.count() < 4:
            nearest_x = x_index + int(x_fraction >= 0.5)
            nearest_y = y_index + int(y_fraction >= 0.5)
            nearest = np.ma.asarray(grid_z)[nearest_y, nearest_x]
            if np.ma.is_masked(nearest) or not np.isfinite(float(nearest)):
                return None
            return float(nearest)

        values = np.asarray(cell, dtype=float)
        interpolated = (
            values[0, 0] * (1.0 - x_fraction) * (1.0 - y_fraction)
            + values[0, 1] * x_fraction * (1.0 - y_fraction)
            + values[1, 0] * (1.0 - x_fraction) * y_fraction
            + values[1, 1] * x_fraction * y_fraction
        )
        return float(interpolated) if np.isfinite(interpolated) else None

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

            values = self._numeric_column_values(
                workspace,
                series.y_dataset,
                column,
                "distribution",
            ).dropna()
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
            target_axes.plot([], [], color=color, label=series.legend_label)
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
        target_axes.plot([], [], color=color, label=series.legend_label)

    def _draw_confidence_band(
        self,
        workspace: Workspace,
        series: PlotSeries,
        target_axes: Any,
        x_scale: str,
        y_scale: str,
        include_in_legend: bool,
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

        x_values = self._numeric_column_values(workspace, series.x_dataset, series.x_column, "X")
        lower_values = self._numeric_column_values(workspace, series.y_dataset, series.lower_column, "lower band")
        upper_values = self._numeric_column_values(workspace, series.y_dataset, series.upper_column, "upper band")
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
            label=(
                f"{series.label} confidence"
                if include_in_legend and series.show_in_legend
                else "_nolegend_"
            ),
        )

    def _draw_empty_state(self, clear_axes: bool = True) -> None:
        """Show the placeholder plot when no series can be rendered."""
        if self._surface_cut_pick_active:
            self.cancel_surface_cut_selection()
        self._surface_cut_points = []
        self._surface_cut_artists = []
        self.canvas.unsetCursor()
        self._series_artists = []
        self._colorbar_labels = []
        self._rendered_surface_grids = []
        self.coordinate_readout.clear()
        self.coordinate_readout.setVisible(False)
        self._remove_right_axes()
        if clear_axes:
            self.axes.clear()

        self.axes.set_xscale("linear")
        self.axes.set_yscale("linear")
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

    def _draw_error_state(self, message: str) -> None:
        """Show a visible canvas explanation when every requested series fails."""
        self._series_artists = []
        self._colorbar_labels = []
        self._rendered_surface_grids = []
        self.coordinate_readout.clear()
        self.coordinate_readout.setVisible(False)
        self._remove_right_axes()
        self.axes.clear()
        self.axes.set_xscale("linear")
        self.axes.set_yscale("linear")
        self.axes.set_xticks([])
        self.axes.set_yticks([])
        self.axes.grid(False)
        self.axes.set_title("Plot could not be rendered")
        clean_message = " ".join(str(message).split())
        if len(clean_message) > 220:
            clean_message = clean_message[:217] + "..."
        self.axes.text(
            0.5,
            0.5,
            clean_message,
            ha="center",
            va="center",
            wrap=True,
            transform=self.axes.transAxes,
            color="tab:red",
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
        include_in_legend: bool,
    ) -> tuple[list[str], list[LocatedPoint]]:
        """Draw locator markers and return interpolation summaries."""
        messages: list[str] = []
        located_points: list[LocatedPoint] = []

        for locator_index, locator in enumerate(locators):
            surface_values = plotted_surface_values.get(locator.series_index)
            if surface_values is not None:
                if locator.x_value is None or locator.y_value is None:
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
                        if include_in_legend
                        else "_nolegend_"
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
            target_axes = self.right_axes if series.y_axis == "right" and self.right_axes else self.axes
            if locator.lookup_mode == "y_to_x":
                if locator.y_value is None:
                    messages.append(f"{series.label}: locator needs a Y value")
                    continue
                try:
                    x_matches = self._interpolate_x_values(x_values, y_values, locator.y_value)
                except ValueError as exc:
                    messages.append(f"{series.label}: {exc}")
                    continue
                target_axes.scatter(
                    x_matches,
                    np.full(len(x_matches), locator.y_value, dtype=float),
                    marker=locator.marker,
                    s=locator.size,
                    color=locator.color,
                    edgecolors="black",
                    linewidths=0.7,
                    zorder=5,
                    label=(
                        f"{series.label} @ y={locator.y_value:g}"
                        if include_in_legend
                        else "_nolegend_"
                    ),
                )
                located_points.extend(
                    LocatedPoint(
                        locator_index=locator_index,
                        series_index=locator.series_index,
                        series_label=series.label,
                        x_value=x_match,
                        y_value=locator.y_value,
                        y_axis=series.y_axis,
                    )
                    for x_match in x_matches
                )
                continue

            if locator.x_value is None:
                messages.append(f"{series.label}: locator needs an X value")
                continue
            try:
                y_value = self._interpolate_y(x_values, y_values, locator.x_value)
            except ValueError as exc:
                messages.append(f"{series.label}: {exc}")
                continue

            target_axes.scatter(
                [locator.x_value],
                [y_value],
                marker=locator.marker,
                s=locator.size,
                color=locator.color,
                edgecolors="black",
                linewidths=0.7,
                zorder=5,
                label=(
                    f"{series.label} @ x={locator.x_value:g}"
                    if include_in_legend
                    else "_nolegend_"
                ),
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

    @staticmethod
    def _interpolate_x_values(
        x_values: pd.Series,
        y_values: pd.Series,
        y_value: float,
    ) -> list[float]:
        """Return every piecewise-linear X intersection for a requested Y value."""
        points = pd.DataFrame({"x": x_values.to_numpy(), "y": y_values.to_numpy()}).dropna()
        if len(points) < 2:
            raise ValueError("locator needs at least two numeric points for interpolation")

        x_array = points["x"].to_numpy(dtype=float)
        y_array = points["y"].to_numpy(dtype=float)
        y_min = float(np.min(y_array))
        y_max = float(np.max(y_array))
        if y_value < y_min or y_value > y_max:
            raise ValueError(f"locator y={y_value:g} is outside the data range [{y_min:g}, {y_max:g}]")

        scale = max(1.0, abs(y_min), abs(y_max), abs(y_value))
        tolerance = np.finfo(float).eps * scale * 32.0
        matches: list[float] = []
        plateau_found = False
        for index in range(len(points) - 1):
            x0, x1 = x_array[index], x_array[index + 1]
            y0, y1 = y_array[index], y_array[index + 1]
            if abs(y0 - y_value) <= tolerance and abs(y1 - y_value) <= tolerance:
                plateau_found = True
                continue
            if y_value < min(y0, y1) - tolerance or y_value > max(y0, y1) + tolerance:
                continue
            fraction = (y_value - y0) / (y1 - y0)
            x_match = float(x0 + fraction * (x1 - x0))
            if not any(np.isclose(x_match, existing, rtol=1.0e-10, atol=1.0e-12) for existing in matches):
                matches.append(x_match)

        if plateau_found:
            raise ValueError(
                f"locator y={y_value:g} overlaps a horizontal segment, so X is not unique"
            )
        if not matches:
            raise ValueError(f"locator y={y_value:g} does not cross a connected plot segment")
        return matches

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

    def _draw_legend(
        self,
        settings: LegendSettings,
        series_list: list[PlotSeries],
    ) -> None:
        """Draw a configurable, ordered legend combined across both Y axes."""
        if not settings.enabled:
            return

        handles, labels = self.axes.get_legend_handles_labels()
        if self.right_axes is not None:
            right_handles, right_labels = self.right_axes.get_legend_handles_labels()
            handles.extend(right_handles)
            labels.extend(right_labels)

        if not handles:
            return

        unique_entries: list[tuple[object, str, int]] = []
        seen_labels: set[str] = set()
        for source_index, (handle, label) in enumerate(zip(handles, labels, strict=False)):
            if not label or label.startswith("_") or label in seen_labels:
                continue
            seen_labels.add(label)
            unique_entries.append((handle, label, source_index))

        series_order = {series.label: index for index, series in enumerate(series_list)}

        def entry_key(entry: tuple[object, str, int]) -> tuple[int, int, int]:
            _handle, label, source_index = entry
            for series_label, series_index in series_order.items():
                if label == series_label:
                    return series_index, 0, source_index
                if label == f"{series_label} confidence":
                    return series_index, 1, source_index
                if label.startswith(f"{series_label} @"):
                    return series_index, 2, source_index
            return len(series_order), 3, source_index

        unique_entries.sort(key=entry_key)
        ordered_handles = [entry[0] for entry in unique_entries]
        ordered_labels = [entry[1] for entry in unique_entries]
        location, bbox_anchor = self._legend_placement(settings.location)
        if settings.location == "outside right":
            self.figure.subplots_adjust(right=0.75)
        elif settings.location == "outside top":
            self.figure.subplots_adjust(top=0.76)
        elif settings.location == "outside bottom":
            self.figure.subplots_adjust(bottom=0.24)

        legend_kwargs: dict[str, object] = {
            "loc": location,
            "fontsize": settings.font_size,
            "title": settings.title or None,
            "title_fontsize": settings.title_font_size,
            "ncols": settings.columns,
            "frameon": settings.frame_enabled,
            "markerscale": settings.marker_scale,
            "handlelength": settings.handle_length,
        }
        if settings.frame_enabled:
            legend_kwargs["framealpha"] = settings.frame_alpha
        if bbox_anchor is not None:
            legend_kwargs["bbox_to_anchor"] = bbox_anchor
        self.axes.legend(ordered_handles, ordered_labels, **legend_kwargs)

    @staticmethod
    def _legend_placement(
        location: str,
    ) -> tuple[str, tuple[float, float] | None]:
        """Translate inspector outside presets into Matplotlib placement arguments."""
        if location == "outside right":
            return "center left", (1.02, 0.5)
        if location == "outside top":
            return "lower center", (0.5, 1.16)
        if location == "outside bottom":
            return "upper center", (0.5, -0.18)
        return location, None
