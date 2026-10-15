"""Linked result viewer for Raman and general spectral analyses."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.spectral_analysis import SpectralAnalysisSession
from models.plot_settings import AxisSettings, LegendSettings
from ui.plot_element_dialogs import PlotAxisEditDialog, PlotTextEditDialog


_LEGEND_LOCATIONS: tuple[tuple[str, str], ...] = (
    ("Automatic", "best"),
    ("Upper right", "upper right"),
    ("Upper left", "upper left"),
    ("Lower left", "lower left"),
    ("Lower right", "lower right"),
    ("Center right", "center right"),
    ("Center left", "center left"),
    ("Upper center", "upper center"),
    ("Lower center", "lower center"),
    ("Center", "center"),
)


class SpectralAnalysisExportDialog(QDialog):
    """Choose which internal analysis tables become ordinary worksheets."""

    def __init__(self, analysis: SpectralAnalysisSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Spectral Analysis")
        self._prefix = QLineEdit(analysis.name)
        self._choices: dict[str, QCheckBox] = {}
        form = QFormLayout(self)
        form.addRow("Worksheet name prefix", self._prefix)
        for key, label, frame, checked in (
            ("metrics", "Parameter maps and fit quality", analysis.metrics_frame, True),
            ("curves", "Spectrum, components, and residual curves", analysis.curves_frame, False),
            ("parameters", "Detailed fitted parameters", analysis.parameters_frame, False),
            ("peaks", "Detected/reviewed peaks", analysis.peaks_frame, False),
        ):
            choice = QCheckBox(label)
            choice.setChecked(checked and not frame.empty)
            choice.setEnabled(not frame.empty)
            self._choices[key] = choice
            form.addRow(choice)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def prefix(self) -> str:
        """Return the requested worksheet prefix."""
        return self._prefix.text().strip() or "Spectral Analysis"

    def selected_frames(self) -> list[str]:
        """Return the internal frame keys selected for publication."""
        return [key for key, choice in self._choices.items() if choice.isChecked()]


class SpectralLegendEditDialog(QDialog):
    """Edit fitted-spectrum curve visibility, labels, and legend appearance."""

    def __init__(
        self,
        curves: list[tuple[str, str, bool]],
        settings: LegendSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Spectrum Curves and Legend")
        self.setModal(True)
        self.setMinimumSize(560, 430)

        self._enabled = QCheckBox("Show legend")
        self._enabled.setChecked(settings.enabled)
        self._location = QComboBox()
        for label, value in _LEGEND_LOCATIONS:
            self._location.addItem(label, value)
        location_index = self._location.findData(settings.location)
        if location_index >= 0:
            self._location.setCurrentIndex(location_index)
        self._font_size = QDoubleSpinBox()
        self._font_size.setRange(5.0, 72.0)
        self._font_size.setSingleStep(0.5)
        self._font_size.setSuffix(" pt")
        self._font_size.setValue(settings.font_size)
        self._columns = QSpinBox()
        self._columns.setRange(1, 12)
        self._columns.setValue(settings.columns)
        self._frame = QCheckBox("Show legend frame")
        self._frame.setChecked(settings.frame_enabled)
        self._frame_alpha = QDoubleSpinBox()
        self._frame_alpha.setRange(0.0, 1.0)
        self._frame_alpha.setSingleStep(0.05)
        self._frame_alpha.setValue(settings.frame_alpha)

        self._curves = QTableWidget(len(curves), 2)
        self._curves.setHorizontalHeaderLabels(["Display curve", "Legend label"])
        self._curves.verticalHeader().setVisible(False)
        self._curves.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._curves.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for row, (column, label, visible) in enumerate(curves):
            visible_item = QTableWidgetItem(column.replace("_", " ").title())
            visible_item.setData(Qt.UserRole, column)
            visible_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            visible_item.setCheckState(Qt.Checked if visible else Qt.Unchecked)
            self._curves.setItem(row, 0, visible_item)
            self._curves.setItem(row, 1, QTableWidgetItem(label))

        self._enabled.toggled.connect(self._update_enabled_state)
        self._frame.toggled.connect(self._update_enabled_state)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("", self._enabled)
        form.addRow("Location", self._location)
        form.addRow("Text size", self._font_size)
        form.addRow("Columns", self._columns)
        form.addRow("", self._frame)
        form.addRow("Frame opacity", self._frame_alpha)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Choose which measured, baseline, fit, and component curves are displayed:"))
        layout.addWidget(self._curves, 1)
        layout.addWidget(buttons)
        self._update_enabled_state()

    def _update_enabled_state(self, _checked: bool = False) -> None:
        enabled = self._enabled.isChecked()
        for widget in (self._location, self._font_size, self._columns, self._frame):
            widget.setEnabled(enabled)
        self._frame_alpha.setEnabled(enabled and self._frame.isChecked())

    def legend_settings(self) -> LegendSettings:
        """Return the edited legend appearance settings."""
        return LegendSettings(
            enabled=self._enabled.isChecked(),
            location=str(self._location.currentData() or "best"),
            font_size=self._font_size.value(),
            columns=self._columns.value(),
            frame_enabled=self._frame.isChecked(),
            frame_alpha=self._frame_alpha.value(),
        )

    def curve_states(self) -> dict[str, tuple[bool, str]]:
        """Return curve visibility and legend labels keyed by stored curve column."""
        states: dict[str, tuple[bool, str]] = {}
        for row in range(self._curves.rowCount()):
            visible_item = self._curves.item(row, 0)
            label_item = self._curves.item(row, 1)
            if visible_item is None:
                continue
            column = str(visible_item.data(Qt.UserRole) or "")
            if column:
                states[column] = (
                    visible_item.checkState() == Qt.Checked,
                    label_item.text().strip() if label_item is not None else "",
                )
        return states


class SpectralAnalysisViewer(QWidget):
    """Display linked parameter maps, spectra, fit components, residuals, and QC."""

    export_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._analysis: SpectralAnalysisSession | None = None
        self._spectrum_keys: list[tuple[tuple[str, Any], ...]] = []
        self._map_axis = None
        self._spectrum_axis = None
        self._map_points = np.empty((0, 2), dtype=float)
        self._map_key_indices: list[int] = []
        self._axis_settings: dict[tuple[str, str], AxisSettings] = {}
        self._grid_enabled = {"map": False, "spectrum": False}
        self._plot_titles: dict[str, str] = {}
        self._curve_visibility: dict[str, bool] = {}
        self._curve_labels: dict[str, str] = {}
        self._current_curve_specs: list[tuple[str, str]] = []
        self._legend_settings = LegendSettings(font_size=8.0, columns=2)
        self._peak_selector = QComboBox()
        self._peak_selector.currentIndexChanged.connect(self._refresh_metric_choices)
        self._metric_selector = QComboBox()
        self._metric_selector.currentIndexChanged.connect(self._redraw)
        self._spectrum_selector = QComboBox()
        self._spectrum_selector.currentIndexChanged.connect(self._redraw)
        self._successful_only = QCheckBox("Hide failed pixels")
        self._successful_only.setChecked(True)
        self._successful_only.toggled.connect(self._redraw)
        self._show_diagnostics = QCheckBox("Show diagnostics")
        self._show_diagnostics.setToolTip(
            "Show residuals, metric distributions, and fit-quality details below the main view."
        )
        self._edit_curves = QPushButton("Curves / Legend...")
        self._edit_curves.setToolTip(
            "Show or hide raw, baseline, corrected, fitted, and component curves. "
            "The same editor opens by double-clicking the spectrum legend."
        )
        self._edit_curves.clicked.connect(self._edit_spectrum_legend)
        self._qc = QLabel("")
        self._qc.setWordWrap(True)
        self._qc.setContentsMargins(8, 8, 8, 8)
        self._export = QPushButton("Export Results to Worksheets...")
        self._export.clicked.connect(self._request_export)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Peak"))
        controls.addWidget(self._peak_selector)
        controls.addWidget(QLabel("Map metric"))
        controls.addWidget(self._metric_selector, 2)
        controls.addWidget(QLabel("Spectrum / pixel"))
        controls.addWidget(self._spectrum_selector, 2)
        controls.addWidget(self._successful_only)
        controls.addWidget(self._show_diagnostics)
        controls.addWidget(self._edit_curves)
        controls.addWidget(self._export)

        self._figure = Figure(figsize=(10.0, 5.5), constrained_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.setToolTip(
            "Click a map pixel to inspect its fit. Double-click a plot title, axis, or "
            "the spectrum legend to edit it directly."
        )
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        self._canvas.mpl_connect("button_press_event", self._map_clicked)
        self._canvas.mpl_connect("button_press_event", self._canvas_double_clicked)

        self._residual_figure = Figure(figsize=(8.0, 2.0), constrained_layout=True)
        self._residual_canvas = FigureCanvasQTAgg(self._residual_figure)
        self._distribution_figure = Figure(figsize=(8.0, 2.0), constrained_layout=True)
        self._distribution_canvas = FigureCanvasQTAgg(self._distribution_figure)
        self._detail_tabs = QTabWidget()
        self._detail_tabs.addTab(self._residual_canvas, "Residual / Fit Error")
        self._detail_tabs.addTab(self._distribution_canvas, "Metric Distribution")
        self._detail_tabs.addTab(self._qc, "QC Details")
        self._detail_tabs.setMinimumHeight(170)
        self._detail_tabs.setMaximumHeight(250)
        self._detail_tabs.setVisible(False)
        self._show_diagnostics.toggled.connect(self._detail_tabs.setVisible)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._canvas, 1)
        layout.addWidget(self._detail_tabs)

    @property
    def analysis(self) -> SpectralAnalysisSession | None:
        """Return the result currently shown."""
        return self._analysis

    def set_analysis(self, analysis: SpectralAnalysisSession | None) -> None:
        """Load an analysis and reset linked selection controls."""
        if analysis is not self._analysis:
            self._axis_settings.clear()
            self._grid_enabled = {"map": False, "spectrum": False}
            self._plot_titles.clear()
            self._curve_visibility.clear()
            self._curve_labels.clear()
            self._current_curve_specs = []
            self._legend_settings = LegendSettings(font_size=8.0, columns=2)
        self._analysis = analysis
        self._peak_selector.blockSignals(True)
        self._metric_selector.blockSignals(True)
        self._spectrum_selector.blockSignals(True)
        try:
            self._peak_selector.clear()
            self._metric_selector.clear()
            self._spectrum_selector.clear()
            self._spectrum_keys = []
            if analysis is None:
                self._canvas.setToolTip("No spectral analysis selected")
                self._redraw()
                return
            self._canvas.setToolTip(
                f"{analysis.name} - source {analysis.source_dataset}. Click a map pixel to "
                "inspect its fit. Double-click a plot title, axis, or the spectrum legend "
                "to edit it directly."
            )
            self._populate_peaks()
            self._populate_spectra()
        finally:
            self._peak_selector.blockSignals(False)
            self._metric_selector.blockSignals(False)
            self._spectrum_selector.blockSignals(False)
        self._refresh_metric_choices()

    def selected_metric(self) -> str:
        """Return the selected metric column, or an empty string."""
        return str(self._metric_selector.currentData() or "")

    def selected_spectrum_key(self) -> tuple[tuple[str, Any], ...]:
        """Return the selected source/coordinate key."""
        index = self._spectrum_selector.currentIndex()
        if 0 <= index < len(self._spectrum_keys):
            return self._spectrum_keys[index]
        return ()

    def _populate_peaks(self) -> None:
        self._peak_selector.addItem("All / quality", "")
        analysis = self._analysis
        if analysis is None:
            return
        prefixes: set[str] = set()
        for column in analysis.metrics_frame.columns:
            text = str(column)
            if text.startswith("peak_"):
                parts = text.split("_", 2)
                if len(parts) >= 2 and parts[1].isdigit():
                    prefixes.add(f"peak_{parts[1]}")
        for prefix in sorted(prefixes, key=lambda value: int(value.split("_")[1])):
            self._peak_selector.addItem(prefix.replace("_", " ").title(), prefix)

    def _populate_spectra(self) -> None:
        analysis = self._analysis
        if analysis is None or analysis.curves_frame.empty:
            return
        group_columns = self._curve_group_columns(analysis)
        if not group_columns:
            self._spectrum_keys = [()]
            self._spectrum_selector.addItem("Spectrum")
            return
        for values, _group in analysis.curves_frame.groupby(group_columns, sort=False, dropna=False):
            if not isinstance(values, tuple):
                values = (values,)
            key = tuple(zip(group_columns, values))
            self._spectrum_keys.append(key)
            self._spectrum_selector.addItem(self._key_label(key))

    def _refresh_metric_choices(self) -> None:
        analysis = self._analysis
        previous = self.selected_metric()
        self._metric_selector.blockSignals(True)
        self._metric_selector.clear()
        if analysis is not None:
            prefix = str(self._peak_selector.currentData() or "")
            excluded = {"source_sheet", "status", "error", *analysis.coordinate_columns}
            for column in analysis.metrics_frame.columns:
                name = str(column)
                if name in excluded or name.endswith("_model"):
                    continue
                numeric = pd.to_numeric(analysis.metrics_frame[column], errors="coerce")
                if not numeric.notna().any():
                    continue
                if prefix and not name.startswith(f"{prefix}_"):
                    continue
                self._metric_selector.addItem(self._metric_label(name), name)
            index = self._metric_selector.findData(previous)
            if index >= 0:
                self._metric_selector.setCurrentIndex(index)
        self._metric_selector.blockSignals(False)
        self._redraw()

    def _redraw(self) -> None:
        self._figure.clear()
        self._residual_figure.clear()
        self._distribution_figure.clear()
        self._map_axis = None
        self._spectrum_axis = None
        self._map_points = np.empty((0, 2), dtype=float)
        self._map_key_indices = []
        analysis = self._analysis
        if analysis is None:
            self._qc.clear()
            self._canvas.draw_idle()
            self._residual_canvas.draw_idle()
            self._distribution_canvas.draw_idle()
            return

        grid = self._figure.add_gridspec(1, 2, width_ratios=(1.0, 1.35))
        map_axis = self._figure.add_subplot(grid[0, 0])
        spectrum_axis = self._figure.add_subplot(grid[0, 1])
        self._spectrum_axis = spectrum_axis
        residual_axis = self._residual_figure.add_subplot(111)
        distribution_axis = self._distribution_figure.add_subplot(111)
        self._draw_map(map_axis)
        self._draw_spectrum(spectrum_axis)
        self._draw_residual(residual_axis)
        self._draw_distribution(distribution_axis)
        self._update_qc_label()
        self._canvas.draw_idle()
        self._residual_canvas.draw_idle()
        self._distribution_canvas.draw_idle()

    def _filtered_metrics(self) -> pd.DataFrame:
        analysis = self._analysis
        if analysis is None:
            return pd.DataFrame()
        frame = analysis.metrics_frame
        if self._successful_only.isChecked() and "fit_success" in frame:
            success = pd.to_numeric(frame["fit_success"], errors="coerce") > 0.0
            return frame.loc[success]
        return frame

    def _draw_map(self, axis) -> None:
        analysis = self._analysis
        metric = self.selected_metric()
        if analysis is None or len(analysis.coordinate_columns) < 2 or not metric:
            axis.text(0.5, 0.5, "No spatial map for this result", ha="center", va="center")
            axis.set_axis_off()
            return
        x_name, y_name = analysis.coordinate_columns[:2]
        frame = self._filtered_metrics()
        if not {x_name, y_name, metric}.issubset(frame.columns):
            axis.text(0.5, 0.5, "Selected metric is unavailable", ha="center", va="center")
            axis.set_axis_off()
            return
        x = pd.to_numeric(frame[x_name], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(frame[y_name], errors="coerce").to_numpy(dtype=float)
        z = pd.to_numeric(frame[metric], errors="coerce").to_numpy(dtype=float)
        finite_xy = np.isfinite(x) & np.isfinite(y)
        finite = finite_xy & np.isfinite(z)
        if not np.any(finite):
            axis.text(0.5, 0.5, "No finite values for this metric", ha="center", va="center")
            axis.set_axis_off()
            return
        finite_frame = pd.DataFrame({x_name: x[finite], y_name: y[finite], metric: z[finite]})
        x_unique = np.sort(finite_frame[x_name].unique())
        y_unique = np.sort(finite_frame[y_name].unique())
        complete_grid = (
            len(x_unique) >= 2
            and len(y_unique) >= 2
            and len(finite_frame) == len(x_unique) * len(y_unique)
            and not finite_frame.duplicated([x_name, y_name]).any()
        )
        if complete_grid:
            grid = finite_frame.pivot(index=y_name, columns=x_name, values=metric).reindex(
                index=y_unique,
                columns=x_unique,
            )
            artist = axis.pcolormesh(
                x_unique,
                y_unique,
                grid.to_numpy(dtype=float),
                shading="nearest",
                cmap="viridis",
            )
        else:
            artist = axis.scatter(
                x[finite], y[finite], c=z[finite], cmap="viridis", marker="s", s=70
            )
        self._figure.colorbar(artist, ax=axis, label=self._metric_label(metric))
        axis.set_title(self._plot_titles.get("map", self._metric_label(metric)))
        axis.set_xlabel(x_name)
        axis.set_ylabel(y_name)
        axis.set_aspect("equal", adjustable="datalim")
        self._map_axis = axis
        self._map_points = np.column_stack((x[finite_xy], y[finite_xy]))
        self._map_key_indices = frame.index[finite_xy].tolist()
        selected = dict(self.selected_spectrum_key())
        if x_name in selected and y_name in selected:
            axis.plot(float(selected[x_name]), float(selected[y_name]), "o", ms=11, mfc="none", mec="red", mew=1.7)
        self._apply_axis_settings(axis, "map")

    def _draw_spectrum(self, spectrum_axis) -> None:
        self._current_curve_specs = []
        analysis = self._analysis
        if analysis is None or analysis.curves_frame.empty:
            spectrum_axis.text(0.5, 0.5, "No fitted spectrum stored", ha="center", va="center")
            spectrum_axis.set_axis_off()
            return
        frame = self._selected_curve_frame()
        if frame.empty or "x" not in frame:
            spectrum_axis.text(0.5, 0.5, "Selected spectrum is unavailable", ha="center", va="center")
            spectrum_axis.set_axis_off()
            return
        x = pd.to_numeric(frame["x"], errors="coerce").to_numpy(dtype=float)
        styles = (
            ("raw", "Raw", "#355C9A", 0.8, "-"),
            ("preprocessing_baseline", "Removed baseline", "#E67E22", 1.0, "--"),
            ("corrected", "Corrected", "#333333", 0.9, "-"),
            ("observed", "Fit input", "#555555", 0.8, ":"),
            ("fit_baseline", "Shared fit baseline", "#2E8B57", 1.0, "--"),
            ("total_fit", "Total fit", "#D62728", 1.5, "-"),
        )
        plotted: set[str] = set()
        curve_specs: list[tuple[str, str]] = []
        for column, label, color, width, linestyle in styles:
            if column not in frame or column in plotted:
                continue
            curve_specs.append((column, label))
            if not self._curve_visibility.get(column, True):
                plotted.add(column)
                continue
            values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
            line, = spectrum_axis.plot(
                x,
                values,
                label=self._curve_labels.get(column, label),
                color=color,
                linewidth=width,
                linestyle=linestyle,
            )
            line.set_gid(column)
            plotted.add(column)
        for column in (name for name in frame.columns if str(name).startswith("peak_")):
            column = str(column)
            default_label = column.replace("_", " ").title()
            curve_specs.append((column, default_label))
            if not self._curve_visibility.get(column, True):
                continue
            values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
            line, = spectrum_axis.plot(
                x,
                values,
                label=self._curve_labels.get(column, default_label),
                linewidth=0.9,
                alpha=0.8,
            )
            line.set_gid(column)
        self._current_curve_specs = curve_specs
        default_title = self._spectrum_plot_title()
        spectrum_axis.set_title(self._plot_titles.get("spectrum", default_title))
        spectrum_axis.set_xlabel(analysis.x_column)
        spectrum_axis.set_ylabel(analysis.y_column)
        self._apply_axis_settings(spectrum_axis, "spectrum")
        self._apply_spectrum_legend(spectrum_axis)
        if not spectrum_axis.lines:
            spectrum_axis.text(
                0.5,
                0.5,
                "All spectrum curves are hidden. Use Curves / Legend to restore them.",
                ha="center",
                va="center",
                transform=spectrum_axis.transAxes,
            )

    def _apply_axis_settings(self, axis, plot_key: str) -> None:
        """Apply direct-edit overrides to one map or spectrum axis."""
        for dimension in ("x", "y"):
            settings = self._axis_settings.get((plot_key, dimension))
            if settings is None:
                continue
            set_label = axis.set_xlabel if dimension == "x" else axis.set_ylabel
            set_scale = axis.set_xscale if dimension == "x" else axis.set_yscale
            get_limits = axis.get_xlim if dimension == "x" else axis.get_ylim
            set_limits = axis.set_xlim if dimension == "x" else axis.set_ylim
            set_label(settings.label)
            set_scale(settings.scale)
            if settings.minimum or settings.maximum:
                current_minimum, current_maximum = get_limits()
                minimum = float(settings.minimum) if settings.minimum else current_minimum
                maximum = float(settings.maximum) if settings.maximum else current_maximum
                set_limits(minimum, maximum)
            label_artist = axis.xaxis.label if dimension == "x" else axis.yaxis.label
            tick_artists = axis.get_xticklabels() if dimension == "x" else axis.get_yticklabels()
            if settings.label_font_size > 0.0:
                label_artist.set_fontsize(settings.label_font_size)
            if settings.tick_font_size > 0.0:
                for tick in tick_artists:
                    tick.set_fontsize(settings.tick_font_size)
        axis.grid(self._grid_enabled.get(plot_key, False))

    def _apply_spectrum_legend(self, axis) -> None:
        """Draw the fitted-spectrum legend using the current direct-edit settings."""
        settings = self._legend_settings
        handles, labels = axis.get_legend_handles_labels()
        if not settings.enabled or not handles:
            return
        axis.legend(
            handles,
            labels,
            loc=settings.location,
            fontsize=settings.font_size,
            ncols=settings.columns,
            frameon=settings.frame_enabled,
            framealpha=settings.frame_alpha,
            markerscale=settings.marker_scale,
            handlelength=settings.handle_length,
            title=settings.title,
            title_fontsize=settings.title_font_size,
        )

    def _edit_spectrum_legend(self) -> None:
        """Open curve visibility and legend controls for the selected spectrum."""
        if self._analysis is None or not self._current_curve_specs:
            return
        curves = [
            (
                column,
                self._curve_labels.get(column, default_label),
                self._curve_visibility.get(column, True),
            )
            for column, default_label in self._current_curve_specs
        ]
        dialog = SpectralLegendEditDialog(curves, self._legend_settings, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._legend_settings = dialog.legend_settings()
        for column, (visible, label) in dialog.curve_states().items():
            self._curve_visibility[column] = visible
            self._curve_labels[column] = label
        self._redraw()

    def _canvas_double_clicked(self, event) -> None:
        """Open focused title, axis, or legend editors from the main canvas."""
        if not bool(getattr(event, "dblclick", False)):
            return
        button = getattr(event, "button", None)
        if button not in {1, "left"} and getattr(button, "name", "").lower() != "left":
            return
        pixel_x = getattr(event, "x", None)
        pixel_y = getattr(event, "y", None)
        if pixel_x is None or pixel_y is None:
            return
        target = self._editable_element_at(float(pixel_x), float(pixel_y))
        if target is None:
            return
        plot_key, element = target
        if element == "legend":
            self._edit_spectrum_legend()
        elif element == "title":
            self._edit_plot_title(plot_key)
        elif element in {"x", "y"}:
            self._edit_axis(plot_key, element)

    def _editable_element_at(self, pixel_x: float, pixel_y: float) -> tuple[str, str] | None:
        """Return the directly editable main-plot element at canvas coordinates."""
        renderer = self._canvas.get_renderer()
        for plot_key, axis in (("spectrum", self._spectrum_axis), ("map", self._map_axis)):
            if axis is None:
                continue
            legend = axis.get_legend()
            if legend is not None and legend.get_visible():
                if any(
                    self._artist_contains(text, renderer, pixel_x, pixel_y, 3.0)
                    for text in legend.get_texts()
                ) or self._artist_contains(legend, renderer, pixel_x, pixel_y, 2.0):
                    return plot_key, "legend"
            if axis.title.get_text() and self._artist_contains(
                axis.title, renderer, pixel_x, pixel_y, 5.0
            ):
                return plot_key, "title"
            if self._artist_contains(axis.xaxis.label, renderer, pixel_x, pixel_y, 5.0):
                return plot_key, "x"
            if self._artist_contains(axis.yaxis.label, renderer, pixel_x, pixel_y, 5.0):
                return plot_key, "y"
            if any(
                self._artist_contains(tick, renderer, pixel_x, pixel_y, 2.0)
                for tick in axis.get_xticklabels()
                if tick.get_visible()
            ):
                return plot_key, "x"
            if any(
                self._artist_contains(tick, renderer, pixel_x, pixel_y, 2.0)
                for tick in axis.get_yticklabels()
                if tick.get_visible()
            ):
                return plot_key, "y"
            bounds = axis.bbox
            if bounds.x0 - 8.0 <= pixel_x <= bounds.x1 + 8.0 and abs(pixel_y - bounds.y0) <= 8.0:
                return plot_key, "x"
            if bounds.y0 - 8.0 <= pixel_y <= bounds.y1 + 8.0 and abs(pixel_x - bounds.x0) <= 8.0:
                return plot_key, "y"
        return None

    def _edit_axis(self, plot_key: str, dimension: str) -> None:
        """Edit one map or spectrum axis and retain the override across redraws."""
        axis = self._map_axis if plot_key == "map" else self._spectrum_axis
        if axis is None:
            return
        current = self._axis_settings.get((plot_key, dimension))
        if current is None:
            current = AxisSettings(
                label=axis.get_xlabel() if dimension == "x" else axis.get_ylabel(),
                scale=axis.get_xscale() if dimension == "x" else axis.get_yscale(),
            )
        name = f"{'Map' if plot_key == 'map' else 'Spectrum'} {dimension.upper()}"
        dialog = PlotAxisEditDialog(
            name,
            current,
            self._grid_enabled.get(plot_key, False),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._axis_settings[(plot_key, dimension)] = dialog.axis_settings()
        self._grid_enabled[plot_key] = dialog.grid_enabled()
        self._redraw()

    def _edit_plot_title(self, plot_key: str) -> None:
        """Edit the map or selected-spectrum title without adding a shared file title."""
        axis = self._map_axis if plot_key == "map" else self._spectrum_axis
        if axis is None:
            return
        dialog = PlotTextEditDialog("Edit Plot Title", "Title", axis.get_title(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._plot_titles[plot_key] = dialog.text_value()
        self._redraw()

    @staticmethod
    def _artist_contains(
        artist: object,
        renderer: object,
        pixel_x: float,
        pixel_y: float,
        padding: float,
    ) -> bool:
        """Return whether a padded Matplotlib artist extent contains a display point."""
        try:
            bounds = artist.get_window_extent(renderer)  # type: ignore[attr-defined]
        except (AttributeError, RuntimeError, ValueError):
            return False
        return bool(
            bounds.x0 - padding <= pixel_x <= bounds.x1 + padding
            and bounds.y0 - padding <= pixel_y <= bounds.y1 + padding
        )

    def _draw_residual(self, residual_axis) -> None:
        """Draw fit error for the selected spectrum in the diagnostics panel."""
        analysis = self._analysis
        frame = self._selected_curve_frame()
        if analysis is None or frame.empty or "x" not in frame or "residual" not in frame:
            residual_axis.text(0.5, 0.5, "No residual stored", ha="center", va="center")
            residual_axis.set_axis_off()
            return
        x = pd.to_numeric(frame["x"], errors="coerce").to_numpy(dtype=float)
        residual = pd.to_numeric(frame["residual"], errors="coerce").to_numpy(dtype=float)
        finite = np.isfinite(x) & np.isfinite(residual)
        if not np.any(finite):
            residual_axis.text(0.5, 0.5, "No finite residual values", ha="center", va="center")
            residual_axis.set_axis_off()
            return
        residual_axis.plot(x[finite], residual[finite], color="#7A3E9D", linewidth=0.9)
        residual_axis.axhline(0.0, color="#777777", linewidth=0.7)
        rmse = float(np.sqrt(np.mean(np.square(residual[finite]))))
        residual_axis.set_title(f"Residual / Fit Error - RMSE {rmse:.4g}")
        residual_axis.set_xlabel(analysis.x_column)
        residual_axis.set_ylabel("Observed - fitted")

    def _draw_distribution(self, axis) -> None:
        metric = self.selected_metric()
        frame = self._filtered_metrics()
        if not metric or metric not in frame:
            axis.text(0.5, 0.5, "Choose a numeric result metric", ha="center", va="center")
            axis.set_axis_off()
            return
        values = pd.to_numeric(frame[metric], errors="coerce").to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if not len(values):
            axis.text(0.5, 0.5, "No finite values", ha="center", va="center")
            axis.set_axis_off()
            return
        bins = max(5, min(40, int(np.sqrt(len(values))) + 1))
        axis.hist(values, bins=bins, color="#4C78A8", alpha=0.85)
        axis.axvline(float(np.median(values)), color="#D62728", linestyle="--", linewidth=1.0, label="Median")
        axis.set_title(f"Distribution · n={len(values)}")
        axis.set_xlabel(self._metric_label(metric))
        axis.set_ylabel("Count")
        axis.legend(loc="best", fontsize="small")

    def _selected_curve_frame(self) -> pd.DataFrame:
        analysis = self._analysis
        if analysis is None:
            return pd.DataFrame()
        frame = analysis.curves_frame
        for name, value in self.selected_spectrum_key():
            if name not in frame:
                return pd.DataFrame()
            series = frame[name]
            if pd.isna(value):
                frame = frame.loc[series.isna()]
            else:
                frame = frame.loc[series == value]
        return frame

    def _update_qc_label(self) -> None:
        analysis = self._analysis
        if analysis is None or analysis.metrics_frame.empty:
            self._qc.clear()
            return
        frame = analysis.metrics_frame
        key = dict(self.selected_spectrum_key())
        for name, value in key.items():
            if name in frame:
                frame = frame.loc[frame[name] == value]
        if frame.empty:
            self._qc.setText("No quality record is available for the selected spectrum.")
            return
        row = frame.iloc[0]
        fields = []
        for column, label in (
            ("status", "Status"),
            ("fit_r_squared", "R²"),
            ("fit_rmse", "RMSE"),
            ("fit_mae", "MAE"),
            ("noise_estimate", "Noise"),
            ("warnings", "Warnings"),
            ("error", "Error"),
        ):
            if column in row and not pd.isna(row[column]) and str(row[column]) != "":
                value = row[column]
                fields.append(f"{label}: {value:.6g}" if isinstance(value, (float, np.floating)) else f"{label}: {value}")
        self._qc.setText(" · ".join(fields))

    def _map_clicked(self, event) -> None:
        if event.inaxes is not self._map_axis or event.xdata is None or event.ydata is None:
            return
        if not len(self._map_points) or self._analysis is None:
            return
        span = np.ptp(self._map_points, axis=0)
        span[span == 0.0] = 1.0
        distances = np.sum(((self._map_points - [event.xdata, event.ydata]) / span) ** 2, axis=1)
        metrics_index = self._map_key_indices[int(np.argmin(distances))]
        row = self._analysis.metrics_frame.loc[metrics_index]
        target = {
            name: row[name]
            for name in self._analysis.coordinate_columns
            if name in row
        }
        for index, key in enumerate(self._spectrum_keys):
            values = dict(key)
            if all(values.get(name) == value for name, value in target.items()):
                self._spectrum_selector.setCurrentIndex(index)
                return

    def _request_export(self) -> None:
        if self._analysis is not None:
            self.export_requested.emit(self._analysis.name)

    @staticmethod
    def _curve_group_columns(analysis: SpectralAnalysisSession) -> list[str]:
        candidates = ["source_sheet", *analysis.coordinate_columns]
        return [name for name in candidates if name in analysis.curves_frame]

    @staticmethod
    def _key_label(key: tuple[tuple[str, Any], ...]) -> str:
        if not key:
            return "Spectrum"
        return " · ".join(f"{name}={value}" for name, value in key)

    def _spectrum_plot_title(self) -> str:
        """Return a compact pixel title without repeating the source filename."""
        spatial_key = tuple(
            (name, value)
            for name, value in self.selected_spectrum_key()
            if name != "source_sheet"
        )
        return self._key_label(spatial_key)

    @staticmethod
    def _metric_label(name: str) -> str:
        return name.replace("_", " ").strip().title()
