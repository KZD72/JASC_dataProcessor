"""Interactive baseline correction and prominence-based peak-review workbench."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from math_engine.baseline import (
    BASELINE_METHODS,
    BaselineParameters,
    BaselineResult,
)
from math_engine.calculus import MathOperationError, validate_numeric_column_metadata
from math_engine.composite_peak_fit import (
    CompositeFitParameters,
    CompositeFitResult,
    PeakComponentSpec,
    available_composite_peak_models,
    build_peak_component_spec,
)
from math_engine.peak_detection import (
    PEAK_POLARITIES,
    PEAK_SMOOTHING_METHODS,
    PeakDetectionParameters,
    PeakDetectionResult,
    PeakRecord,
)
from core.jobs import JobProgress
from core.spectral_jobs import SpectralSource
from core.spectral_preview import (
    PreviewKind, SpectralPreviewRequest, SpectralPreviewResult, prepare_spectral_preview,
)
from ui.background_jobs import BackgroundJobController


ANALYSIS_PROFILE_SCHEMA = "jasc.peak-analysis-profile"
ANALYSIS_PROFILE_VERSION = 1


class PeakAnalysisDialog(QDialog):
    """Configure baseline correction, detect peaks, and review candidates."""

    def __init__(
        self,
        frame: pd.DataFrame,
        dataset_name: str,
        *,
        default_x_column: str | None = None,
        default_y_column: str | None = None,
        baseline_only: bool = False,
        raman_mode: bool = False,
        datasets: dict[str, pd.DataFrame] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "Baseline Correction"
            if baseline_only else ("Raman Analysis" if raman_mode else "Peak Analysis")
        )
        self.setModal(True)
        self.resize(1160, 760)
        self.setMinimumSize(900, 620)
        self._frames = dict(datasets or {dataset_name: frame})
        if dataset_name not in self._frames:
            self._frames[dataset_name] = frame
        self._frame = self._frames[dataset_name]
        self._dataset_name = dataset_name
        self._baseline_only = baseline_only
        self._raman_mode = raman_mode
        self._baseline_result: BaselineResult | None = None
        self._peak_result: PeakDetectionResult | None = None
        self._composite_result: CompositeFitResult | None = None
        self._reviewed_peaks: list[tuple[bool, PeakRecord]] = []
        self._removed_peak_centers: list[float] = []
        self._preview_generation = 0
        self._preview_jobs = BackgroundJobController(self)
        self._preview_jobs.finished.connect(self._preview_finished)
        self._preview_jobs.progress.connect(self._preview_progress)
        self._pending_preview: tuple[PreviewKind, int, bool] | None = None
        self._active_preview: tuple[PreviewKind, int, bool] | None = None
        self._result_request: SpectralPreviewRequest | None = None
        self._result_frame: pd.DataFrame | None = None
        self._accept_pending = False
        self._fit_after_preview = False
        self._preview_close_result: int | None = None
        self._delete_when_idle = False
        self._preview_closed = False
        self._scheduled_preview_generation = 0
        self._updating_table = False
        self._profile_loading = False
        self._profile_components: list[dict[str, object]] = []
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._run_scheduled_preview)
        self.finished.connect(self._stop_preview_timer)

        self._tabs = QTabWidget()
        self._source_tab = self._build_source_tab(default_x_column, default_y_column)
        self._baseline_tab = self._build_baseline_tab()
        self._detection_tab = self._build_detection_tab()
        self._fit_tab = self._build_fit_tab()
        self._output_tab = self._build_output_tab()
        self._tabs.addTab(self._source_tab, "Source & Range")
        self._tabs.addTab(self._baseline_tab, "Baseline")
        if not baseline_only:
            self._tabs.addTab(self._detection_tab, "Detection")
            self._tabs.addTab(self._fit_tab, "Fit Components")
        self._tabs.addTab(self._output_tab, "Output & Batch")

        self._figure = Figure(figsize=(7.0, 5.0), constrained_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._status_label = QLabel("Choose source columns, then preview the baseline.")
        self._status_label.setWordWrap(True)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        profile_row = QHBoxLayout()
        load_profile = QPushButton("Load Parameters...")
        load_profile.clicked.connect(self._load_analysis_profile_dialog)
        save_profile = QPushButton("Save Parameters...")
        save_profile.clicked.connect(self._save_analysis_profile_dialog)
        profile_row.addWidget(load_profile)
        profile_row.addWidget(save_profile)
        left_layout.addLayout(profile_row)
        left_layout.addWidget(self._tabs)
        preview_baseline = QPushButton("Preview Baseline")
        preview_baseline.clicked.connect(self.preview_baseline)
        self._preview_peaks_button = QPushButton("Detect / Refresh Peaks")
        self._preview_peaks_button.clicked.connect(self.preview_peaks)
        self._preview_peaks_button.setVisible(not baseline_only)
        preview_row = QHBoxLayout()
        preview_row.addWidget(preview_baseline)
        preview_row.addWidget(self._preview_peaks_button)
        self._stop_preview_button = QPushButton("Stop Preview")
        self._stop_preview_button.clicked.connect(self._cancel_preview)
        self._stop_preview_button.setEnabled(False)
        preview_row.addWidget(self._stop_preview_button)
        left_layout.addLayout(preview_row)
        left_layout.addWidget(self._status_label)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self._navigation_toolbar = NavigationToolbar2QT(self._canvas, self)
        right_layout.addWidget(self._navigation_toolbar)
        right_layout.addWidget(self._canvas, 3)
        self._review_group = self._build_review_group()
        self._review_group.setVisible(not baseline_only)
        right_layout.addWidget(self._review_group, 2)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        buttons = self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        layout.addWidget(buttons)

        self._connect_preview_controls()
        self._source_layout_changed()
        self._update_baseline_controls()
        self._update_anchor_definition()
        self._update_smoothing_controls()
        # Use the dialog-owned debounce timer for the initial preview.  A
        # context-free ``singleShot`` can outlive a dialog that is constructed
        # and closed before the event loop runs (notably in batch workflows),
        # leaving a callback aimed at already-destroyed Qt widgets.
        self._schedule_preview()

    def _build_source_tab(
        self,
        default_x_column: str | None,
        default_y_column: str | None,
    ) -> QWidget:
        tab = QWidget()
        columns = [str(column) for column in self._frame.columns]
        self._source_dataset_combo = QComboBox()
        for name in self._frames:
            self._source_dataset_combo.addItem(name, name)
        self._source_dataset_combo.setCurrentIndex(
            max(0, self._source_dataset_combo.findData(self._dataset_name))
        )
        self._source_dataset_combo.currentIndexChanged.connect(self._source_dataset_changed)
        self._x_combo = QComboBox()
        self._x_combo.addItems(columns)
        self._y_combo = QComboBox()
        self._y_combo.addItem("Choose signal column...", None)
        for column in columns:
            self._y_combo.addItem(column, column)
        if default_x_column in columns:
            self._x_combo.setCurrentText(str(default_x_column))
        if default_y_column in columns:
            self._y_combo.setCurrentIndex(self._y_combo.findData(default_y_column))

        self._source_layout = QComboBox()
        self._source_layout.addItem("Single spectrum", "spectrum")
        self._source_layout.addItem("Long-form map (group by X/Y)", "map")
        if self._frame_looks_like_map(self._frame):
            self._source_layout.setCurrentIndex(self._source_layout.findData("map"))
        self._preview_pixel = QComboBox()
        self._preview_pixel_label = QLabel("Preview X/Y pixel")
        self._map_coordinate_values: list[tuple[float, float]] = []
        self._source_layout.currentIndexChanged.connect(self._source_layout_changed)
        self._preview_pixel.currentIndexChanged.connect(self._preview_pixel_changed)
        self._refresh_preview_pixels()

        self._range_checkbox = QCheckBox("Restrict analysis to physical X range")
        self._range_min = QDoubleSpinBox()
        self._range_max = QDoubleSpinBox()
        for spin in (self._range_min, self._range_max):
            spin.setDecimals(9)
            spin.setRange(-1.0e300, 1.0e300)
        numeric_x = pd.to_numeric(self._frame[self._x_combo.currentText()], errors="coerce") if columns else pd.Series(dtype=float)
        if numeric_x.notna().any():
            self._range_min.setValue(float(numeric_x.min()))
            self._range_max.setValue(float(numeric_x.max()))
        self._range_min.setEnabled(False)
        self._range_max.setEnabled(False)
        self._range_checkbox.toggled.connect(self._range_min.setEnabled)
        self._range_checkbox.toggled.connect(self._range_max.setEnabled)
        self._x_combo.currentIndexChanged.connect(self._reset_range_for_x)

        note = QLabel(
            "The worksheet that launched the workbench is preselected, but any open worksheet "
            "can be chosen here. Descending and irregular X axes are supported."
        )
        note.setWordWrap(True)
        form = QFormLayout(tab)
        form.addRow("Source worksheet", self._source_dataset_combo)
        form.addRow("Source layout", self._source_layout)
        form.addRow(self._preview_pixel_label, self._preview_pixel)
        form.addRow("X / spectral axis", self._x_combo)
        form.addRow("Y / intensity", self._y_combo)
        form.addRow(self._range_checkbox)
        form.addRow("Range minimum", self._range_min)
        form.addRow("Range maximum", self._range_max)
        form.addRow(note)
        return tab

    def _build_baseline_tab(self) -> QWidget:
        tab = QWidget()
        self._baseline_method = QComboBox()
        for key, label in BASELINE_METHODS.items():
            self._baseline_method.addItem(label, key)
        self._baseline_polarity = QComboBox()
        for key, label in PEAK_POLARITIES.items():
            self._baseline_polarity.addItem(label, key)
        self._smoothness = _scientific_spin(1.0e5, 1.0, 1.0e15)
        self._asymmetry = QDoubleSpinBox()
        self._asymmetry.setDecimals(6)
        self._asymmetry.setRange(1.0e-6, 0.499999)
        self._asymmetry.setValue(0.01)
        self._baseline_iterations = QSpinBox()
        self._baseline_iterations.setRange(1, 10000)
        self._baseline_iterations.setValue(100)
        self._baseline_tolerance = _scientific_spin(1.0e-3, 1.0e-12, 1.0)
        self._snip_window = QSpinBox()
        self._snip_window.setRange(1, 100000)
        self._snip_window.setValue(40)
        self._polynomial_order = QSpinBox()
        self._polynomial_order.setRange(0, 20)
        self._polynomial_order.setValue(2)
        self._edge_fraction = QDoubleSpinBox()
        self._edge_fraction.setDecimals(3)
        self._edge_fraction.setRange(0.01, 0.5)
        self._edge_fraction.setValue(0.10)
        self._constant_value = QLineEdit()
        self._constant_value.setPlaceholderText("Automatic edge median")
        self._anchor_mode = QComboBox()
        for label, key in (("PCHIP", "pchip"), ("Linear", "linear"), ("Akima", "akima")):
            self._anchor_mode.addItem(label, key)
        self._anchor_definition = QComboBox()
        self._anchor_definition.addItem("Explicit X:Y baseline points", "xy_pairs")
        self._anchor_definition.addItem("X positions (sample each source signal)", "x_values")
        self._anchor_definition.currentIndexChanged.connect(self._update_anchor_definition)
        self._anchors = QLineEdit()
        self._anchors.setPlaceholderText("x1:y1; x2:y2; ...")
        self._anchors.setToolTip("Enter physical-X and baseline-Y anchor pairs separated by semicolons.")

        form = QFormLayout(tab)
        form.addRow("Method", self._baseline_method)
        form.addRow("Expected peak polarity", self._baseline_polarity)
        form.addRow("Smoothness (lambda)", self._smoothness)
        form.addRow("Asymmetry", self._asymmetry)
        form.addRow("Maximum iterations", self._baseline_iterations)
        form.addRow("Convergence tolerance", self._baseline_tolerance)
        form.addRow("SNIP half-window", self._snip_window)
        form.addRow("Polynomial order", self._polynomial_order)
        form.addRow("Edge fraction", self._edge_fraction)
        form.addRow("Constant value", self._constant_value)
        form.addRow("Anchor interpolation", self._anchor_mode)
        form.addRow("Anchor definition", self._anchor_definition)
        form.addRow("Manual anchors", self._anchors)
        return tab

    def _build_detection_tab(self) -> QWidget:
        tab = QWidget()
        self._detection_polarity = QComboBox()
        for key, label in PEAK_POLARITIES.items():
            self._detection_polarity.addItem(label, key)
        self._prominence = QLineEdit()
        self._prominence.setPlaceholderText("Automatic from robust noise")
        self._minimum_height = QLineEdit()
        self._minimum_height.setPlaceholderText("No absolute height threshold")
        self._snr = QDoubleSpinBox()
        self._snr.setDecimals(2)
        self._snr.setRange(0.0, 1.0e6)
        self._snr.setValue(3.0)
        self._distance = _scientific_spin(0.0, 0.0, 1.0e300)
        self._minimum_width = _scientific_spin(0.0, 0.0, 1.0e300)
        self._maximum_width = QLineEdit()
        self._maximum_width.setPlaceholderText("No maximum")
        self._relative_height = QDoubleSpinBox()
        self._relative_height.setDecimals(3)
        self._relative_height.setRange(0.01, 0.99)
        self._relative_height.setValue(0.5)
        self._maximum_count = QSpinBox()
        self._maximum_count.setRange(0, 1000000)
        self._maximum_count.setSpecialValueText("Unlimited")
        self._plateau_minimum = _scientific_spin(0.0, 0.0, 1.0e300)
        self._smoothing_method = QComboBox()
        for key, label in PEAK_SMOOTHING_METHODS.items():
            self._smoothing_method.addItem(label, key)
        self._smoothing_window = QSpinBox()
        self._smoothing_window.setRange(3, 100001)
        self._smoothing_window.setSingleStep(2)
        self._smoothing_window.setValue(7)
        self._smoothing_order = QSpinBox()
        self._smoothing_order.setRange(0, 20)
        self._smoothing_order.setValue(3)
        note = QLabel("Distance and FWHM limits are interpreted in physical X-axis units, not samples.")
        note.setWordWrap(True)
        form = QFormLayout(tab)
        form.addRow("Peak polarity", self._detection_polarity)
        form.addRow("Minimum prominence", self._prominence)
        form.addRow("Minimum height", self._minimum_height)
        form.addRow("Automatic threshold (SNR)", self._snr)
        form.addRow("Minimum center distance", self._distance)
        form.addRow("Minimum FWHM", self._minimum_width)
        form.addRow("Maximum FWHM", self._maximum_width)
        form.addRow("Width relative height", self._relative_height)
        form.addRow("Maximum peak count", self._maximum_count)
        form.addRow("Minimum plateau width", self._plateau_minimum)
        form.addRow("Pre-detection smoothing", self._smoothing_method)
        form.addRow("Smoothing window", self._smoothing_window)
        form.addRow("Savitzky-Golay order", self._smoothing_order)
        form.addRow(note)
        return tab

    def _build_fit_tab(self) -> QWidget:
        tab = QWidget()
        self._component_table = QTableWidget(0, 3)
        self._component_table.itemChanged.connect(self._clear_composite_preview)
        self._component_table.setHorizontalHeaderLabels(["Use", "Detected center", "Peak model"])
        self._component_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._component_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._component_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._fit_data_mode = QComboBox()
        self._fit_data_mode.addItem("Corrected data (fixed zero baseline)", "corrected")
        self._fit_data_mode.addItem("Raw data (one shared baseline)", "raw")
        self._shared_fit_baseline = QComboBox()
        for label, key in (
            ("Fixed zero", "zero"),
            ("Constant", "constant"),
            ("Linear", "linear"),
            ("Quadratic", "quadratic"),
        ):
            self._shared_fit_baseline.addItem(label, key)
        self._shared_fit_baseline.setEnabled(False)
        self._fit_data_mode.currentIndexChanged.connect(self._sync_fit_baseline)
        self._fit_loss = QComboBox()
        self._fit_loss.addItem("Least squares", "linear")
        self._fit_loss.addItem("Robust soft L1", "soft_l1")
        self._fit_loss.addItem("Robust Huber", "huber")
        self._maximum_fit_evaluations = QSpinBox()
        self._maximum_fit_evaluations.setRange(100, 10_000_000)
        self._maximum_fit_evaluations.setValue(20_000)
        self._fit_data_mode.currentIndexChanged.connect(self._clear_composite_preview)
        self._shared_fit_baseline.currentIndexChanged.connect(self._clear_composite_preview)
        self._fit_loss.currentIndexChanged.connect(self._clear_composite_preview)
        self._maximum_fit_evaluations.valueChanged.connect(self._clear_composite_preview)
        fit_button = QPushButton("Fit Selected Components")
        fit_button.clicked.connect(self.preview_composite_fit)
        self._fit_metrics = QLabel("Detect peaks first, then choose a model for each component.")
        self._fit_metrics.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Fit signal", self._fit_data_mode)
        form.addRow("Shared baseline", self._shared_fit_baseline)
        form.addRow("Loss", self._fit_loss)
        form.addRow("Maximum fit evaluations", self._maximum_fit_evaluations)
        layout = QVBoxLayout(tab)
        layout.addLayout(form)
        layout.addWidget(self._component_table, 1)
        layout.addWidget(fit_button)
        layout.addWidget(self._fit_metrics)
        return tab

    def _build_output_tab(self) -> QWidget:
        tab = QWidget()
        base = self._dataset_name
        default_analysis_name = (
            f"{base} Analysis" if "raman" in base.casefold() else f"{base} Raman Analysis"
        )
        self._analysis_name = QLineEdit(default_analysis_name)
        self._result_sheet = QLineEdit(f"{base}_peak_signal")
        self._peak_sheet = QLineEdit(f"{base}_peaks")
        self._fit_sheet = QLineEdit(f"{base}_peak_fit")
        self._fit_parameter_sheet = QLineEdit(f"{base}_peak_parameters")
        self._create_signal_output = QCheckBox("Create raw/baseline/corrected signal worksheet")
        self._create_signal_output.setChecked(self._baseline_only)
        self._create_peak_output = QCheckBox("Create reviewed tidy peak table")
        self._create_peak_output.setChecked(False)
        self._create_peak_output.setVisible(not self._baseline_only)
        self._peak_sheet.setVisible(not self._baseline_only)
        self._create_fit_output = QCheckBox("Create composite fit curve and parameter worksheets")
        self._create_fit_output.setChecked(False)
        self._create_fit_output.setVisible(not self._baseline_only)
        self._fit_sheet.setVisible(not self._baseline_only)
        self._fit_parameter_sheet.setVisible(not self._baseline_only)
        peak_label = QLabel("Peak table name")
        peak_label.setVisible(not self._baseline_only)
        fit_label = QLabel("Fit curve name")
        fit_label.setVisible(not self._baseline_only)
        parameter_label = QLabel("Fit parameter name")
        parameter_label.setVisible(not self._baseline_only)
        self._application_scope = QComboBox()
        self._application_scope.addItem("Current preview spectrum / selected pixel", "single")
        if not self._baseline_only:
            self._application_scope.addItem("Selected worksheets (batch)", "batch")
        self._application_scope.addItem("Current long-form Raman map (group by X/Y)", "map")
        self._application_scope.currentIndexChanged.connect(self._sync_application_scope)
        self._batch_sheets = QListWidget()
        self._batch_sheets.setSelectionMode(QAbstractItemView.MultiSelection)
        self._batch_sheets.setMaximumHeight(110)
        for name in self._frames:
            self._batch_sheets.addItem(name)
        self._batch_sheets.setVisible(False)
        self._center_tolerance = _scientific_spin(10.0, 0.0, 1.0e300)
        self._center_tolerance.setVisible(not self._baseline_only)
        form = QFormLayout(tab)
        if not self._baseline_only:
            note = QLabel(
                "The complete result is stored as a Raman Analysis session with linked maps, "
                "spectra, residuals, distributions, and QC. Worksheets are optional exports."
            )
            note.setWordWrap(True)
            form.addRow(note)
            form.addRow("Analysis name", self._analysis_name)
        form.addRow("Apply to", self._application_scope)
        if not self._baseline_only:
            form.addRow("Batch worksheets", self._batch_sheets)
            form.addRow("Peak center matching tolerance", self._center_tolerance)
        form.addRow(self._create_signal_output)
        form.addRow("Signal result name", self._result_sheet)
        form.addRow(self._create_peak_output)
        form.addRow(peak_label, self._peak_sheet)
        form.addRow(self._create_fit_output)
        form.addRow(fit_label, self._fit_sheet)
        form.addRow(parameter_label, self._fit_parameter_sheet)
        return tab

    def analysis_name(self) -> str:
        """Return the first-class analysis-session name."""
        return self._analysis_name.text().strip() or f"{self._dataset_name} Spectral Analysis"

    def _build_review_group(self) -> QGroupBox:
        group = QGroupBox("Reviewed Peak Candidates")
        self._peak_table = QTableWidget(0, 8)
        self._peak_table.setHorizontalHeaderLabels(
            ["Use", "Center", "Polarity", "Height", "Prominence", "FWHM", "Area", "Status"]
        )
        self._peak_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._peak_table.horizontalHeader().setStretchLastSection(True)
        self._peak_table.itemChanged.connect(self._review_item_changed)
        add_button = QPushButton("Add at X...")
        add_button.clicked.connect(self._add_manual_peak)
        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self._remove_selected_peaks)
        controls = QHBoxLayout()
        controls.addWidget(add_button)
        controls.addWidget(remove_button)
        controls.addStretch(1)
        layout = QVBoxLayout(group)
        layout.addWidget(self._peak_table)
        layout.addLayout(controls)
        return group

    def _connect_preview_controls(self) -> None:
        controls = [
            self._x_combo, self._y_combo, self._range_checkbox, self._range_min,
            self._range_max, self._baseline_method, self._baseline_polarity,
            self._smoothness, self._asymmetry, self._baseline_iterations,
            self._baseline_tolerance, self._snip_window, self._polynomial_order,
            self._edge_fraction, self._constant_value, self._anchor_mode,
            self._anchor_definition, self._anchors,
        ]
        if not self._baseline_only:
            controls.extend([
                self._detection_polarity, self._prominence, self._minimum_height,
                self._snr, self._distance, self._minimum_width, self._maximum_width,
                self._relative_height, self._maximum_count,
                self._smoothing_method, self._smoothing_window,
                self._smoothing_order, self._plateau_minimum,
            ])
        for control in controls:
            if isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self._schedule_preview)
            elif isinstance(control, QCheckBox):
                control.toggled.connect(self._schedule_preview)
            elif isinstance(control, (QDoubleSpinBox, QSpinBox)):
                control.valueChanged.connect(self._schedule_preview)
            elif isinstance(control, QLineEdit):
                control.textChanged.connect(self._schedule_preview)
        self._baseline_method.currentIndexChanged.connect(self._update_baseline_controls)
        if not self._baseline_only:
            self._smoothing_method.currentIndexChanged.connect(self._update_smoothing_controls)

    def _schedule_preview(self, *_args: object) -> None:
        """Invalidate immediately, debounce, and keep only the newest desired input."""
        if self._profile_loading or self._preview_closed or self._preview_close_result is not None:
            return
        self._preview_generation += 1
        self._scheduled_preview_generation = self._preview_generation
        self._pending_preview = None
        self._accept_pending = self._fit_after_preview = False
        self._baseline_result = self._peak_result = self._composite_result = None
        self._result_request = self._result_frame = None
        self._preview_jobs.cancel()
        self._preview_timer.start(250)
        self._status_label.setText("Preview settings changed; preparing an update...")
        self._fit_metrics.setText("Fit preview needs refreshing.")
        self._draw_preview()
        self._update_preview_buttons()

    def _run_scheduled_preview(self) -> None:
        if self._scheduled_preview_generation == self._preview_generation:
            self._request_preview("baseline" if self._baseline_only else "peaks", show_errors=False)

    def _stop_preview_timer(self, _result: int) -> None:
        self._preview_timer.stop()

    @property
    def preview_busy(self) -> bool:
        return self._preview_jobs.is_running or self._pending_preview is not None or self._preview_timer.isActive()

    def _update_preview_buttons(self) -> None:
        self._stop_preview_button.setEnabled(self.preview_busy and self._preview_close_result is None)
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(
            not self._accept_pending and self._preview_close_result is None)

    def _source_matches(self, request: SpectralPreviewRequest, frame: pd.DataFrame) -> bool:
        if self._frame is not frame or self._frames.get(request.source.name) is not frame:
            return False
        columns = list(request.source.frame.columns)
        return (set(columns).issubset(frame.columns)
                and frame.loc[:, columns].equals(request.source.frame)
                and frame.attrs == request.source.frame.attrs)

    def _cache_is_current(self) -> bool:
        return bool(self._result_request is not None and self._result_frame is not None
                    and self._source_matches(self._result_request, self._result_frame))

    def _make_preview_request(self, kind: PreviewKind) -> SpectralPreviewRequest:
        x_column, y_column = self.x_column(), self.y_column()
        if not x_column or not y_column:
            raise MathOperationError("Choose both the X axis and intensity column.")
        if x_column == y_column:
            raise MathOperationError("Choose different columns for the X axis and intensity.")
        coordinates = self.preview_coordinates()
        if self.source_layout() == "map" and not coordinates:
            raise MathOperationError("Map preview requires a finite X/Y pixel. Choose a preview pixel.")
        columns = list(dict.fromkeys([*(('X', 'Y') if coordinates else ()), x_column, y_column]))
        source = SpectralSource(self._dataset_name,
            self._frame.loc[:, [name for name in columns if name in self._frame]].copy(deep=True))
        cached = self._cache_is_current()
        return SpectralPreviewRequest(
            kind, source, x_column, y_column, coordinates, self.analysis_range(),
            self.baseline_parameters(),
            detection_parameters=None if self._baseline_only else self.detection_parameters(),
            fit_parameters=self.composite_parameters() if kind == "fit" else None,
            components=tuple(deepcopy(self.component_specs())) if kind == "fit" else (),
            baseline=self._baseline_result if cached else None,
            peaks=self._peak_result if cached and kind == "fit" else None,
        )

    def _request_preview(self, kind: PreviewKind, *, show_errors: bool, for_accept: bool = False) -> bool:
        """Queue a preview; True means accepted for asynchronous computation."""
        if self._preview_closed or self._preview_close_result is not None:
            return False
        self._preview_timer.stop()
        if not for_accept:
            self._accept_pending = False
        if not self._cache_is_current():
            self._baseline_result = self._peak_result = self._composite_result = None
            self._result_request = self._result_frame = None
        self._fit_after_preview = kind == "fit" and self._peak_result is None
        if self._fit_after_preview:
            kind = "peaks"
        self._preview_generation += 1
        self._pending_preview = kind, self._preview_generation, show_errors
        self._preview_jobs.cancel()
        self._status_label.setText("Preview queued; waiting for the current calculation..."
                                   if self._preview_jobs.is_running else "Preparing preview...")
        started = self._start_pending_preview()
        self._update_preview_buttons()
        return started

    def _start_pending_preview(self) -> bool:
        if self._preview_jobs.is_running or self._pending_preview is None:
            return True
        kind, generation, show_errors = self._pending_preview
        self._pending_preview = None
        try:
            request = self._make_preview_request(kind)
        except (MathOperationError, ValueError, KeyError) as exc:
            self._preview_failed(str(exc), show_errors)
            return False
        frame = self._frame
        self._active_preview = kind, generation, show_errors

        def current() -> bool:
            return (generation == self._preview_generation and not self._preview_closed
                    and self._preview_close_result is None)

        def succeeded(result: SpectralPreviewResult) -> None:
            if not current():
                return
            if not self._source_matches(request, frame):
                self._schedule_preview()
                self._status_label.setText("Source data changed; refreshing preview...")
                return
            self._apply_preview(request, result)
            self._result_request, self._result_frame = request, frame
            if self._fit_after_preview:
                self._fit_after_preview = False
                self._request_preview("fit", show_errors=show_errors, for_accept=self._accept_pending)
            elif self._accept_pending:
                self.accept()

        def failed(message: str) -> None:
            if current():
                self._preview_failed(message, show_errors)

        self._preview_jobs.start(
            lambda context: prepare_spectral_preview(context, request), on_success=succeeded,
            on_error=failed, on_cancelled=lambda: None,
        )
        return True

    def _preview_failed(self, message: str, show_errors: bool) -> None:
        self._accept_pending = self._fit_after_preview = False
        self._composite_result = None
        self._status_label.setText(message)
        self._fit_metrics.setText(message)
        self._update_preview_buttons()
        if show_errors:
            QMessageBox.warning(self, self.windowTitle(), message)

    def _preview_progress(self, progress: JobProgress) -> None:
        if (self._active_preview is not None and self._active_preview[1] == self._preview_generation
                and self._preview_close_result is None):
            self._status_label.setText(progress.message)

    def _preview_finished(self) -> None:
        # A completion callback may already have started the next phase.
        if self._preview_jobs.is_running:
            return
        superseded = self._active_preview is not None and self._active_preview[1] != self._preview_generation
        self._active_preview = None
        if self._preview_close_result is not None:
            self.done(self._preview_close_result)
        elif self._pending_preview is not None:
            self._start_pending_preview()
        elif superseded and not self._preview_timer.isActive():
            self._status_label.setText("Preview cancelled.")
        self._update_preview_buttons()

    def _cancel_preview(self, *_args: object) -> None:
        self._preview_generation += 1
        self._preview_timer.stop()
        self._pending_preview = None
        self._accept_pending = self._fit_after_preview = False
        self._preview_jobs.cancel()
        self._status_label.setText("Stopping preview; waiting for the current calculation..."
                                   if self._preview_jobs.is_running else "Preview cancelled.")
        self._update_preview_buttons()

    def _apply_preview(self, request: SpectralPreviewRequest, result: SpectralPreviewResult) -> None:
        """Publish only a current generation, preserving review edits for fit-only work."""
        self._baseline_result = result.baseline
        if request.kind == "peaks" and result.peaks is not None:
            previous = [(enabled, peak) for enabled, peak in self._reviewed_peaks
                        if peak.manual_status != "automatic"]
            reviewed = [(True, peak) for peak in result.peaks.peaks
                        if not any(abs(peak.center - center) <= self.center_tolerance()
                                   for center in self._removed_peak_centers)]
            finite_x = result.baseline.x[np.isfinite(result.baseline.x)]
            for enabled, peak in previous:
                if not finite_x.size or not float(finite_x.min()) <= peak.center <= float(finite_x.max()):
                    continue
                if reviewed and peak.manual_status != "added":
                    nearest = min(range(len(reviewed)), key=lambda i: abs(reviewed[i][1].center - peak.center))
                    if abs(reviewed[nearest][1].center - peak.center) <= self.center_tolerance():
                        reviewed.pop(nearest)
                reviewed.append((enabled, peak))
            self._reviewed_peaks = sorted(reviewed, key=lambda entry: entry[1].center)
            self._peak_result = result.peaks
            self._populate_peak_table()
            self._populate_component_table()
            self._composite_result = None
            warning = f" Warnings: {'; '.join(result.peaks.warnings)}" if result.peaks.warnings else ""
            self._status_label.setText(f"Detected {len(result.peaks.peaks)} candidate peak(s); robust noise "
                                       f"estimate={result.peaks.noise_estimate:.6g}.{warning}")
        elif request.kind == "baseline":
            baseline = result.baseline
            warning = f" Warnings: {'; '.join(baseline.warnings)}" if baseline.warnings else ""
            self._status_label.setText(f"Baseline ready: {BASELINE_METHODS[baseline.parameters.method]}; "
                f"iterations={baseline.iterations}; converged={'yes' if baseline.converged else 'no'}.{warning}")
        if result.fit is not None:
            self._composite_result = result.fit
            fit = result.fit
            self._fit_metrics.setText(f"Converged={'yes' if fit.converged else 'no'}; "
                f"R?={fit.r_squared:.6g}; RMSE={fit.rmse:.6g}; AIC={fit.aic:.6g}; BIC={fit.bic:.6g}. {fit.message}")
            self._status_label.setText("Composite fit preview ready.")
        self._draw_preview()

    def reject(self) -> None:
        self.done(QDialog.Rejected)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.reject()
        if self._preview_jobs.is_running:
            event.ignore()
        else:
            event.accept()

    def done(self, result: int) -> None:
        if self._preview_closed:
            if self._delete_when_idle:
                super().deleteLater()
            return
        self._preview_timer.stop()
        self._pending_preview = None
        self._accept_pending = self._fit_after_preview = False
        self._preview_generation += 1
        self._preview_close_result = result
        self._preview_jobs.cancel()
        if self._preview_jobs.is_running:
            self._status_label.setText("Closing; waiting for the current preview to stop...")
            self._update_preview_buttons()
            return
        self._preview_closed = True
        super().done(result)
        if self._delete_when_idle:
            super().deleteLater()

    def deleteLater(self) -> None:
        """Retain the dialog/controller until workers stop, including programmatic disposal."""
        self._delete_when_idle = True
        if self._preview_closed and not self._preview_jobs.is_running:
            super().deleteLater()
            return
        self.done(QDialog.Rejected)

    def event(self, event: QEvent) -> bool:
        if (event.type() == QEvent.DeferredDelete and hasattr(self, "_preview_jobs")
                and self._preview_jobs.is_running):
            self.deleteLater()
            return True
        return super().event(event)

    def _update_baseline_controls(self, *_args: object) -> None:
        method = str(self._baseline_method.currentData())
        weighted = method in {"arpls", "asls", "airpls"}
        self._smoothness.setEnabled(weighted)
        self._asymmetry.setEnabled(method == "asls")
        self._baseline_iterations.setEnabled(weighted)
        self._baseline_tolerance.setEnabled(weighted)
        self._snip_window.setEnabled(method == "snip")
        self._polynomial_order.setEnabled(method == "polynomial")
        self._edge_fraction.setEnabled(method in {"constant", "linear"})
        self._constant_value.setEnabled(method == "constant")
        self._anchor_mode.setEnabled(method == "manual")
        self._anchor_definition.setEnabled(method == "manual")
        self._anchors.setEnabled(method == "manual")

    def _update_anchor_definition(self, *_args: object) -> None:
        """Explain whether anchors supply Y explicitly or sample each spectrum."""
        if self._anchor_definition.currentData() == "x_values":
            self._anchors.setPlaceholderText("x1; x2; x3; ...")
            self._anchors.setToolTip(
                "Enter physical X positions separated by semicolons, commas, or spaces. "
                "Each spectrum supplies its own interpolated Y value at those positions."
            )
        else:
            self._anchors.setPlaceholderText("x1:y1; x2:y2; ...")
            self._anchors.setToolTip(
                "Enter physical-X and baseline-Y anchor pairs separated by semicolons."
            )

    def _update_smoothing_controls(self, *_args: object) -> None:
        method = str(self._smoothing_method.currentData())
        self._smoothing_window.setEnabled(method != "none")
        self._smoothing_order.setEnabled(method == "savgol")

    @staticmethod
    def _frame_looks_like_map(frame: pd.DataFrame) -> bool:
        """Return whether a normalized worksheet contains multiple X/Y pixel groups."""
        if not {"X", "Y"}.issubset({str(column) for column in frame.columns}):
            return False
        coordinates = frame[["X", "Y"]].apply(pd.to_numeric, errors="coerce").dropna()
        return len(coordinates.drop_duplicates()) > 1

    def _refresh_preview_pixels(self) -> None:
        """Populate the finite coordinate pairs available for map preview."""
        self._map_coordinate_values = []
        self._preview_pixel.blockSignals(True)
        try:
            self._preview_pixel.clear()
            if not {"X", "Y"}.issubset({str(column) for column in self._frame.columns}):
                return
            coordinates = self._frame[["X", "Y"]].apply(pd.to_numeric, errors="coerce")
            coordinates = coordinates.dropna().drop_duplicates(keep="first")
            for x_coordinate, y_coordinate in coordinates.itertuples(index=False, name=None):
                pair = (float(x_coordinate), float(y_coordinate))
                self._map_coordinate_values.append(pair)
                self._preview_pixel.addItem(f"X={pair[0]:g}, Y={pair[1]:g}")
        finally:
            self._preview_pixel.blockSignals(False)

    def _source_layout_changed(self, *_args: object) -> None:
        """Switch between an ordinary spectrum and one selected map-pixel preview."""
        is_map = self.source_layout() == "map"
        self._preview_pixel.setVisible(is_map)
        self._preview_pixel_label.setVisible(is_map)
        if is_map:
            self._refresh_preview_pixels()
        if hasattr(self, "_application_scope"):
            desired_scope = "map" if is_map else "single"
            index = self._application_scope.findData(desired_scope)
            if index >= 0:
                self._application_scope.setCurrentIndex(index)
        if hasattr(self, "_baseline_result"):
            self._baseline_result = None
            self._peak_result = None
            self._composite_result = None
            self._reviewed_peaks = []
            self._removed_peak_centers = []
            self._populate_peak_table()
            self._populate_component_table()
            self._schedule_preview()

    def _preview_pixel_changed(self, *_args: object) -> None:
        """Invalidate previews when the representative map pixel changes."""
        self._baseline_result = None
        self._peak_result = None
        self._composite_result = None
        self._reviewed_peaks = []
        self._removed_peak_centers = []
        self._populate_peak_table()
        self._populate_component_table()
        self._schedule_preview()

    def _source_dataset_changed(self, *_args: object) -> None:
        """Switch the preview source without locking the launching worksheet."""
        name = str(self._source_dataset_combo.currentData() or "")
        if not name or name not in self._frames:
            return
        self._dataset_name = name
        self._frame = self._frames[name]
        columns = [str(column) for column in self._frame.columns]
        preferred_x = next(
            (column for column in columns if column.casefold() in {
                "raman shift", "wavenumber", "wavelength", "frequency"
            }),
            columns[0] if columns else "",
        )
        self._x_combo.blockSignals(True)
        self._y_combo.blockSignals(True)
        try:
            self._x_combo.clear()
            self._x_combo.addItems(columns)
            if preferred_x:
                self._x_combo.setCurrentText(preferred_x)
            self._y_combo.clear()
            self._y_combo.addItem("Choose signal column...", None)
            for column in columns:
                self._y_combo.addItem(column, column)
        finally:
            self._x_combo.blockSignals(False)
            self._y_combo.blockSignals(False)
        layout = "map" if self._frame_looks_like_map(self._frame) else "spectrum"
        self._source_layout.blockSignals(True)
        try:
            self._source_layout.setCurrentIndex(self._source_layout.findData(layout))
        finally:
            self._source_layout.blockSignals(False)
        self._source_layout_changed()
        self._reset_range_for_x()
        self._result_sheet.setText(f"{name}_peak_signal")
        self._peak_sheet.setText(f"{name}_peaks")
        self._fit_sheet.setText(f"{name}_peak_fit")
        self._fit_parameter_sheet.setText(f"{name}_peak_parameters")
        self._baseline_result = None
        self._peak_result = None
        self._composite_result = None
        self._reviewed_peaks = []
        self._removed_peak_centers = []
        self._populate_peak_table()
        self._populate_component_table()
        self._schedule_preview()

    def _sync_fit_baseline(self, *_args: object) -> None:
        raw_mode = self._fit_data_mode.currentData() == "raw"
        self._shared_fit_baseline.setEnabled(raw_mode)
        if not raw_mode:
            self._shared_fit_baseline.setCurrentIndex(
                self._shared_fit_baseline.findData("zero")
            )
        elif self._shared_fit_baseline.currentData() == "zero":
            self._shared_fit_baseline.setCurrentIndex(
                self._shared_fit_baseline.findData("linear")
            )

    def _sync_application_scope(self, *_args: object) -> None:
        batch = self._application_scope.currentData() == "batch"
        self._batch_sheets.setVisible(batch)
        if batch and not self._batch_sheets.selectedItems():
            for row in range(self._batch_sheets.count()):
                item = self._batch_sheets.item(row)
                item.setSelected(item.text() == self._dataset_name)

    def _reset_range_for_x(self, *_args: object) -> None:
        """Reset physical range controls when the source axis changes."""
        column = self._x_combo.currentText().strip()
        if not column or column not in self._frame:
            return
        values = pd.to_numeric(self._frame[column], errors="coerce")
        finite = values[np.isfinite(values)]
        if finite.empty:
            return
        self._range_min.setValue(float(finite.min()))
        self._range_max.setValue(float(finite.max()))

    def baseline_parameters(self) -> BaselineParameters:
        """Return validated baseline controls as a serializable contract."""
        anchor_source = str(self._anchor_definition.currentData())
        anchor_x_values = (
            _parse_anchor_x_values(self._anchors.text())
            if anchor_source == "x_values"
            else ()
        )
        anchors = _parse_anchors(self._anchors.text()) if anchor_source == "xy_pairs" else ()
        return BaselineParameters(
            method=str(self._baseline_method.currentData()),
            polarity=str(self._baseline_polarity.currentData()),
            smoothness=float(self._smoothness.value()),
            asymmetry=float(self._asymmetry.value()),
            max_iterations=int(self._baseline_iterations.value()),
            tolerance=float(self._baseline_tolerance.value()),
            snip_half_window=int(self._snip_window.value()),
            polynomial_order=int(self._polynomial_order.value()),
            edge_fraction=float(self._edge_fraction.value()),
            constant_value=_optional_float(self._constant_value.text(), "constant baseline"),
            anchors=anchors,
            anchor_interpolation=str(self._anchor_mode.currentData()),
            anchor_source=anchor_source,
            anchor_x_values=anchor_x_values,
        )

    def detection_parameters(self) -> PeakDetectionParameters:
        """Return validated detector controls as a serializable contract."""
        maximum_count = int(self._maximum_count.value())
        return PeakDetectionParameters(
            polarity=str(self._detection_polarity.currentData()),
            prominence=_optional_float(self._prominence.text(), "prominence"),
            height=_optional_float(self._minimum_height.text(), "minimum height"),
            snr_threshold=float(self._snr.value()),
            minimum_distance_x=float(self._distance.value()),
            minimum_fwhm_x=float(self._minimum_width.value()),
            maximum_fwhm_x=_optional_float(self._maximum_width.text(), "maximum FWHM"),
            maximum_count=maximum_count or None,
            relative_height=float(self._relative_height.value()),
            plateau_minimum_x=float(self._plateau_minimum.value()),
            smoothing_method=str(self._smoothing_method.currentData()),
            smoothing_window=int(self._smoothing_window.value()),
            smoothing_polynomial_order=int(self._smoothing_order.value()),
        )

    def preview_baseline(self, *_args: object, show_errors: bool = True) -> bool:
        """Queue baseline preview; results arrive on the GUI thread."""
        return self._request_preview("baseline", show_errors=show_errors)

    def preview_peaks(self, *_args: object, show_errors: bool = True) -> bool:
        """Queue baseline/detection without blocking the dialog."""
        return self._request_preview("peaks", show_errors=show_errors)

    def _draw_preview(self) -> None:
        self._figure.clear()
        if self._baseline_result is None:
            self._canvas.draw_idle()
            return
        upper = self._figure.add_subplot(211)
        lower = self._figure.add_subplot(212, sharex=upper)
        result = self._baseline_result
        preview_positions = _preview_positions(result.x, result.raw, maximum=6000)
        upper.plot(
            result.x[preview_positions], result.raw[preview_positions],
            color="#355C9A", linewidth=1.0, label="Raw",
        )
        upper.plot(
            result.x[preview_positions], result.baseline[preview_positions],
            color="#E67E22", linewidth=1.3, label="Baseline",
        )
        upper.set_ylabel("Intensity")
        upper.legend(loc="best")
        show_raw_fit = bool(
            self._composite_result is not None
            and self._composite_result.parameters.data_mode == "raw"
        )
        lower_values = result.raw if show_raw_fit else result.corrected
        lower.plot(
            result.x[preview_positions], lower_values[preview_positions],
            color="#333333", linewidth=1.0, label="Raw" if show_raw_fit else "Corrected",
        )
        if self._composite_result is not None:
            fit = self._composite_result.fit_frame
            fit_positions = _preview_positions(fit["x"].to_numpy(), fit["total_fit"].to_numpy(), maximum=6000)
            displayed_fit = fit.iloc[fit_positions]
            lower.plot(displayed_fit["x"], displayed_fit["total_fit"], color="#D62728", linewidth=1.5, label="Composite fit")
            for column in (name for name in fit.columns if name.startswith("peak_")):
                lower.plot(displayed_fit["x"], displayed_fit[column], linewidth=0.9, alpha=0.75, label=column)
        for enabled, peak in self._reviewed_peaks:
            color = "#2E8B57" if peak.polarity == "positive" else "#B03A8F"
            if not enabled:
                color = "#999999"
            lower.axvline(peak.center, color=color, alpha=0.85 if enabled else 0.45, linewidth=1.0)
        lower.axhline(0.0, color="#888888", linewidth=0.7)
        lower.set_xlabel(self._x_combo.currentText())
        lower.set_ylabel("Raw intensity" if show_raw_fit else "Corrected")
        if self._composite_result is not None:
            lower.legend(loc="best", fontsize="small")
        self._canvas.draw_idle()

    def _populate_peak_table(self) -> None:
        self._updating_table = True
        try:
            self._peak_table.setRowCount(len(self._reviewed_peaks))
            for row, (enabled, peak) in enumerate(self._reviewed_peaks):
                use_item = QTableWidgetItem("")
                use_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                use_item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
                self._peak_table.setItem(row, 0, use_item)
                center_item = QTableWidgetItem(f"{peak.center:.12g}")
                self._peak_table.setItem(row, 1, center_item)
                values = (
                    peak.polarity, peak.corrected_height, peak.prominence,
                    peak.fwhm, peak.area, peak.manual_status,
                )
                for column, value in enumerate(values, start=2):
                    text = f"{value:.8g}" if isinstance(value, float) else str(value)
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self._peak_table.setItem(row, column, item)
        finally:
            self._updating_table = False

    def _populate_component_table(self) -> None:
        """Keep reviewed candidates separate while assigning one registered model each."""
        if not hasattr(self, "_component_table"):
            return
        was_updating = self._updating_table
        self._updating_table = True
        try:
            previous: dict[float, tuple[str, bool]] = {}
            for row in range(self._component_table.rowCount()):
                center_item = self._component_table.item(row, 1)
                use_item = self._component_table.item(row, 0)
                combo = self._component_table.cellWidget(row, 2)
                if center_item is not None and isinstance(combo, QComboBox):
                    try:
                        previous[float(center_item.text())] = (
                            str(combo.currentData()),
                            bool(use_item is not None and use_item.checkState() == Qt.Checked),
                        )
                    except ValueError:
                        pass
            models = available_composite_peak_models()
            remaining_previous = dict(previous)
            remaining_profile = list(self._profile_components)
            self._component_table.setRowCount(len(self._reviewed_peaks))
            for row, (review_enabled, peak) in enumerate(self._reviewed_peaks):
                enabled = review_enabled
                model_key = "gaussian"
                if remaining_previous:
                    preserved = min(
                        remaining_previous,
                        key=lambda value: abs(value - peak.center),
                    )
                    model_key, enabled = remaining_previous.pop(preserved)
                elif remaining_profile:
                    compatible = [
                        item for item in remaining_profile
                        if str(item.get("polarity", peak.polarity)) == peak.polarity
                    ] or remaining_profile
                    preserved_profile = min(
                        compatible,
                        key=lambda item: abs(float(item["reference_center"]) - peak.center),
                    )
                    remaining_profile.remove(preserved_profile)
                    model_key = str(preserved_profile["model_key"])
                    enabled = bool(preserved_profile.get("enabled", review_enabled))
                use_item = QTableWidgetItem("")
                use_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                use_item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
                self._component_table.setItem(row, 0, use_item)
                center_item = QTableWidgetItem(f"{peak.center:.12g}")
                center_item.setFlags(center_item.flags() & ~Qt.ItemIsEditable)
                self._component_table.setItem(row, 1, center_item)
                combo = QComboBox()
                for model in models:
                    combo.addItem(model.name, model.key)
                index = combo.findData(model_key)
                combo.setCurrentIndex(max(0, index))
                combo.currentIndexChanged.connect(lambda _index: self._clear_composite_preview())
                self._component_table.setCellWidget(row, 2, combo)
        finally:
            self._updating_table = was_updating

    def _clear_composite_preview(self, *_args: object) -> None:
        if self._profile_loading or self._updating_table:
            return
        self._composite_result = None
        self._accept_pending = self._fit_after_preview = False
        fit_active = self._active_preview is not None and self._active_preview[0] == "fit"
        fit_pending = self._pending_preview is not None and self._pending_preview[0] == "fit"
        if fit_active or fit_pending:
            self._preview_generation += 1
            self._pending_preview = None
            self._preview_jobs.cancel()
            self._status_label.setText("Fit settings changed; preview needs refreshing.")
        self._fit_metrics.setText("Fit settings changed; preview needs refreshing.")
        self._draw_preview()
        self._update_preview_buttons()

    def component_specs(self) -> list[PeakComponentSpec]:
        """Return reviewed peak/model selections as serializable component specs."""
        if self._baseline_result is None:
            raise MathOperationError("Preview the spectrum before building fit components.")
        specs: list[PeakComponentSpec] = []
        for row, (_review_enabled, peak) in enumerate(self._reviewed_peaks):
            use_item = self._component_table.item(row, 0)
            combo = self._component_table.cellWidget(row, 2)
            enabled = bool(use_item is not None and use_item.checkState() == Qt.Checked)
            if not isinstance(combo, QComboBox):
                continue
            spec = build_peak_component_spec(
                peak, str(combo.currentData()), self._baseline_result.x
            )
            specs.append(replace(spec, enabled=enabled))
        return specs

    def composite_parameters(self) -> CompositeFitParameters:
        data_mode = str(self._fit_data_mode.currentData())
        baseline_model = (
            str(self._shared_fit_baseline.currentData()) if data_mode == "raw" else "zero"
        )
        return CompositeFitParameters(
            data_mode=data_mode,
            baseline_model=baseline_model,
            maximum_evaluations=int(self._maximum_fit_evaluations.value()),
            loss=str(self._fit_loss.currentData()),
        )

    def analysis_profile(self) -> dict[str, object]:
        """Return every reusable algorithm control in a versioned JSON contract."""
        payload: dict[str, object] = {
            "schema": ANALYSIS_PROFILE_SCHEMA,
            "version": ANALYSIS_PROFILE_VERSION,
            "baseline": self.baseline_parameters().to_dict(),
            "analysis_range": {
                "enabled": self._range_checkbox.isChecked(),
                "minimum": float(self._range_min.value()),
                "maximum": float(self._range_max.value()),
            },
        }
        if self._baseline_only:
            return payload
        components: list[dict[str, object]] = []
        for row in range(self._component_table.rowCount()):
            center_item = self._component_table.item(row, 1)
            use_item = self._component_table.item(row, 0)
            model_combo = self._component_table.cellWidget(row, 2)
            if center_item is None or not isinstance(model_combo, QComboBox):
                continue
            polarity = (
                self._reviewed_peaks[row][1].polarity
                if row < len(self._reviewed_peaks)
                else "positive"
            )
            components.append({
                "reference_center": float(center_item.text()),
                "polarity": polarity,
                "model_key": str(model_combo.currentData()),
                "enabled": bool(use_item is not None and use_item.checkState() == Qt.Checked),
            })
        payload.update({
            "detection": self.detection_parameters().to_dict(),
            "fit": self.composite_parameters().to_dict(),
            "components": components,
            "center_tolerance": float(self._center_tolerance.value()),
        })
        return payload

    def apply_analysis_profile(self, payload: Mapping[str, object]) -> None:
        """Validate and apply a saved analysis profile without changing worksheet/output choices."""
        if payload.get("schema") != ANALYSIS_PROFILE_SCHEMA:
            raise ValueError("This is not a JASC Peak Analysis parameter profile.")
        if payload.get("version") != ANALYSIS_PROFILE_VERSION:
            raise ValueError(
                f"Unsupported analysis profile version: {payload.get('version')!r}."
            )
        baseline = _profile_section(payload, "baseline")
        range_settings = _profile_section(payload, "analysis_range")
        self._profile_loading = True
        self._preview_timer.stop()
        self._preview_generation += 1
        self._pending_preview = None
        self._preview_jobs.cancel()
        self._accept_pending = self._fit_after_preview = False
        self._baseline_result = self._peak_result = self._composite_result = None
        self._result_request = self._result_frame = None
        self._reviewed_peaks = []
        self._removed_peak_centers = []
        self._populate_peak_table()
        try:
            _select_combo_data(self._baseline_method, baseline.get("method"), "baseline method")
            _select_combo_data(self._baseline_polarity, baseline.get("polarity"), "baseline polarity")
            self._smoothness.setValue(float(baseline.get("smoothness", 1.0e5)))
            self._asymmetry.setValue(float(baseline.get("asymmetry", 0.01)))
            self._baseline_iterations.setValue(int(baseline.get("max_iterations", 100)))
            self._baseline_tolerance.setValue(float(baseline.get("tolerance", 1.0e-3)))
            self._snip_window.setValue(int(baseline.get("snip_half_window", 40)))
            self._polynomial_order.setValue(int(baseline.get("polynomial_order", 2)))
            self._edge_fraction.setValue(float(baseline.get("edge_fraction", 0.10)))
            self._constant_value.setText(_profile_optional_number(baseline.get("constant_value")))
            _select_combo_data(
                self._anchor_mode,
                baseline.get("anchor_interpolation", "pchip"),
                "anchor interpolation",
            )
            anchor_source = str(baseline.get("anchor_source", "xy_pairs"))
            _select_combo_data(self._anchor_definition, anchor_source, "anchor definition")
            if anchor_source == "x_values":
                anchor_values = baseline.get("anchor_x_values", [])
                if not isinstance(anchor_values, list):
                    raise ValueError("Profile anchor_x_values must be a list.")
                self._anchors.setText("; ".join(f"{float(value):.12g}" for value in anchor_values))
            else:
                anchors = baseline.get("anchors", [])
                if not isinstance(anchors, list):
                    raise ValueError("Profile anchors must be a list.")
                formatted_anchors: list[str] = []
                for anchor in anchors:
                    if not isinstance(anchor, list) or len(anchor) != 2:
                        raise ValueError("Every explicit profile anchor must contain X and Y.")
                    formatted_anchors.append(f"{float(anchor[0]):.12g}:{float(anchor[1]):.12g}")
                self._anchors.setText("; ".join(formatted_anchors))

            self._range_checkbox.setChecked(bool(range_settings.get("enabled", False)))
            self._range_min.setValue(float(range_settings.get("minimum", self._range_min.value())))
            self._range_max.setValue(float(range_settings.get("maximum", self._range_max.value())))

            if not self._baseline_only and "detection" in payload:
                detection = _profile_section(payload, "detection")
                _select_combo_data(
                    self._detection_polarity, detection.get("polarity"), "detection polarity"
                )
                self._prominence.setText(_profile_optional_number(detection.get("prominence")))
                self._minimum_height.setText(_profile_optional_number(detection.get("height")))
                self._snr.setValue(float(detection.get("snr_threshold", 3.0)))
                self._distance.setValue(float(detection.get("minimum_distance_x", 0.0)))
                self._minimum_width.setValue(float(detection.get("minimum_fwhm_x", 0.0)))
                self._maximum_width.setText(
                    _profile_optional_number(detection.get("maximum_fwhm_x"))
                )
                self._relative_height.setValue(float(detection.get("relative_height", 0.5)))
                maximum_count = detection.get("maximum_count")
                self._maximum_count.setValue(0 if maximum_count is None else int(maximum_count))
                self._plateau_minimum.setValue(
                    float(detection.get("plateau_minimum_x", 0.0))
                )
                _select_combo_data(
                    self._smoothing_method,
                    detection.get("smoothing_method", "none"),
                    "detection smoothing",
                )
                self._smoothing_window.setValue(int(detection.get("smoothing_window", 7)))
                self._smoothing_order.setValue(
                    int(detection.get("smoothing_polynomial_order", 3))
                )

            if not self._baseline_only and "fit" in payload:
                fit = _profile_section(payload, "fit")
                _select_combo_data(self._fit_data_mode, fit.get("data_mode"), "fit signal")
                _select_combo_data(
                    self._shared_fit_baseline,
                    fit.get("baseline_model"),
                    "shared fit baseline",
                )
                _select_combo_data(self._fit_loss, fit.get("loss"), "fit loss")
                self._maximum_fit_evaluations.setValue(
                    int(fit.get("maximum_evaluations", 20_000))
                )
                self._center_tolerance.setValue(float(payload.get("center_tolerance", 10.0)))
                raw_components = payload.get("components", [])
                if not isinstance(raw_components, list):
                    raise ValueError("Profile components must be a list.")
                valid_models = {model.key for model in available_composite_peak_models()}
                loaded_components: list[dict[str, object]] = []
                for component in raw_components:
                    if not isinstance(component, dict):
                        raise ValueError("Every profile component must be an object.")
                    model_key = str(component.get("model_key", ""))
                    if model_key not in valid_models:
                        raise ValueError(f"Unknown composite peak model in profile: {model_key!r}.")
                    loaded_components.append({
                        "reference_center": float(component.get("reference_center")),
                        "polarity": str(component.get("polarity", "positive")),
                        "model_key": model_key,
                        "enabled": bool(component.get("enabled", True)),
                    })
                self._profile_components = loaded_components
                self._component_table.setRowCount(0)
        finally:
            self._profile_loading = False
        self._update_baseline_controls()
        self._update_anchor_definition()
        if not self._baseline_only:
            self._update_smoothing_controls()
            self._sync_fit_baseline()
            self._populate_component_table()
        self._baseline_result = None
        self._peak_result = None
        self._composite_result = None
        self._schedule_preview()

    def save_analysis_profile(self, path: str | Path) -> None:
        """Write the current algorithm parameters as portable UTF-8 JSON."""
        target = Path(path)
        target.write_text(
            json.dumps(self.analysis_profile(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def load_analysis_profile(self, path: str | Path) -> None:
        """Load and apply a portable UTF-8 JSON algorithm profile."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Analysis profile must contain one JSON object.")
        self.apply_analysis_profile(payload)

    def _save_analysis_profile_dialog(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Peak Analysis Parameters",
            "peak_analysis.jasc-analysis.json",
            "JASC Analysis Profile (*.jasc-analysis.json);;JSON Files (*.json)",
        )
        if not path:
            return
        try:
            self.save_analysis_profile(path)
            self._status_label.setText(f"Saved analysis parameters to {Path(path).name}.")
        except (OSError, TypeError, ValueError, MathOperationError) as exc:
            QMessageBox.warning(self, "Save Analysis Parameters", str(exc))

    def _load_analysis_profile_dialog(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Load Peak Analysis Parameters",
            "",
            "JASC Analysis Profile (*.jasc-analysis.json *.json);;All Files (*)",
        )
        if not path:
            return
        try:
            self.load_analysis_profile(path)
            self._status_label.setText(
                f"Loaded analysis parameters from {Path(path).name}; preview is refreshing."
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Load Analysis Parameters", str(exc))

    def preview_composite_fit(self, *_args: object, show_errors: bool = True) -> bool:
        """Queue a fit from current reviewed components, detecting first when needed."""
        return self._request_preview("fit", show_errors=show_errors)

    def _review_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.row() >= len(self._reviewed_peaks):
            return
        enabled, peak = self._reviewed_peaks[item.row()]
        try:
            if item.column() == 0:
                enabled = item.checkState() == Qt.Checked
                peak = replace(peak, manual_status="disabled" if not enabled else "reviewed")
            elif item.column() == 1:
                center = float(item.text())
                if not np.isfinite(center):
                    raise ValueError
                peak = replace(peak, center=center, manual_status="repositioned")
            self._reviewed_peaks[item.row()] = (enabled, peak)
            self._populate_component_table()
            if item.column() == 0:
                self._updating_table = True
                try:
                    self._component_table.item(item.row(), 0).setCheckState(Qt.Checked if enabled else Qt.Unchecked)
                finally:
                    self._updating_table = False
            self._clear_composite_preview()
        except ValueError:
            QMessageBox.warning(self, "Peak Review", "Peak center must be a finite number.")
            self._populate_peak_table()

    def _add_manual_peak(self) -> None:
        if self._baseline_result is None or not self._cache_is_current():
            self.preview_baseline()
            self._status_label.setText("Wait for the baseline preview, then add a manual peak.")
            return
        from PySide6.QtWidgets import QInputDialog

        assert self._baseline_result is not None
        finite_x = self._baseline_result.x[np.isfinite(self._baseline_result.x)]
        if finite_x.size == 0:
            return
        center, accepted = QInputDialog.getDouble(
            self,
            "Add Manual Peak",
            "Physical X coordinate:",
            float(np.median(finite_x)),
            float(np.min(finite_x)),
            float(np.max(finite_x)),
            9,
        )
        if not accepted:
            return
        valid = np.isfinite(self._baseline_result.x) & np.isfinite(self._baseline_result.corrected)
        positions = np.flatnonzero(valid)
        nearest = int(positions[np.argmin(np.abs(self._baseline_result.x[valid] - center))])
        corrected_height = float(self._baseline_result.corrected[nearest])
        polarity = "positive" if corrected_height >= 0 else "negative"
        y_column = self.y_column()
        peak = PeakRecord(
            source_sheet=self._dataset_name,
            channel=y_column,
            row_index=nearest,
            center=float(self._baseline_result.x[nearest]),
            polarity=polarity,
            raw_height=float(self._baseline_result.raw[nearest]),
            corrected_height=corrected_height,
            prominence=float("nan"),
            fwhm=float("nan"),
            left_boundary=float(self._baseline_result.x[nearest]),
            right_boundary=float(self._baseline_result.x[nearest]),
            left_base=float(self._baseline_result.x[nearest]),
            right_base=float(self._baseline_result.x[nearest]),
            area=float("nan"),
            local_snr=float("nan"),
            plateau_size=0.0,
            asymmetry=float("nan"),
            detector="manual",
            manual_status="added",
            map_coordinates=tuple(self.preview_coordinates().items()),
        )
        self._reviewed_peaks.append((True, peak))
        self._reviewed_peaks.sort(key=lambda entry: entry[1].center)
        self._populate_peak_table()
        self._populate_component_table()
        self._clear_composite_preview()

    def _remove_selected_peaks(self) -> None:
        rows = sorted({index.row() for index in self._peak_table.selectedIndexes()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self._reviewed_peaks):
                _enabled, peak = self._reviewed_peaks.pop(row)
                self._removed_peak_centers.append(peak.center)
        self._populate_peak_table()
        self._populate_component_table()
        self._clear_composite_preview()

    def baseline_result(self) -> BaselineResult:
        if self._baseline_result is None:
            raise RuntimeError("Baseline preview has not been calculated.")
        return self._baseline_result

    def peak_result(self) -> PeakDetectionResult | None:
        return self._peak_result

    def composite_result(self) -> CompositeFitResult | None:
        return self._composite_result

    def reviewed_peak_frame(self) -> pd.DataFrame:
        rows = []
        for enabled, peak in self._reviewed_peaks:
            row = peak.to_dict()
            row["enabled"] = bool(enabled)
            rows.append(row)
        if rows:
            return pd.DataFrame(rows)
        columns = [
            "source_sheet", "channel", "row_index", "center", "polarity",
            "raw_height", "corrected_height", "prominence", "fwhm",
            "left_boundary", "right_boundary", "left_base", "right_base",
            "area", "local_snr", "plateau_size", "asymmetry", "detector",
            "manual_status", "enabled",
        ]
        return pd.DataFrame(columns=columns)

    def x_column(self) -> str:
        return self._x_combo.currentText().strip()

    def source_dataset_name(self) -> str:
        return self._dataset_name

    def source_layout(self) -> str:
        return str(self._source_layout.currentData() or "spectrum")

    def preview_coordinates(self) -> dict[str, float]:
        """Return the selected representative map pixel, if map mode is active."""
        if self.source_layout() != "map":
            return {}
        index = self._preview_pixel.currentIndex()
        if index < 0 or index >= len(self._map_coordinate_values):
            return {}
        x_coordinate, y_coordinate = self._map_coordinate_values[index]
        return {"X": x_coordinate, "Y": y_coordinate}

    def y_column(self) -> str:
        return str(self._y_combo.currentData() or "")

    def result_sheet_name(self) -> str:
        return self._result_sheet.text().strip()

    def peak_sheet_name(self) -> str:
        return self._peak_sheet.text().strip()

    def create_signal_output(self) -> bool:
        return self._create_signal_output.isChecked()

    def create_peak_output(self) -> bool:
        return not self._baseline_only and self._create_peak_output.isChecked()

    def create_fit_output(self) -> bool:
        return not self._baseline_only and self._create_fit_output.isChecked()

    def fit_sheet_name(self) -> str:
        return self._fit_sheet.text().strip()

    def fit_parameter_sheet_name(self) -> str:
        return self._fit_parameter_sheet.text().strip()

    def application_scope(self) -> str:
        return str(self._application_scope.currentData())

    def batch_dataset_names(self) -> list[str]:
        if self.application_scope() != "batch":
            return [self._dataset_name]
        return [item.text() for item in self._batch_sheets.selectedItems()]

    def center_tolerance(self) -> float:
        return 0.0 if self._baseline_only else float(self._center_tolerance.value())

    def analysis_range(self) -> tuple[float, float] | None:
        if not self._range_checkbox.isChecked():
            return None
        return (
            min(self._range_min.value(), self._range_max.value()),
            max(self._range_min.value(), self._range_max.value()),
        )

    def accept(self) -> None:
        if self._preview_closed or self._preview_close_result is not None:
            return
        if not self._cache_is_current():
            self._baseline_result = self._peak_result = self._composite_result = None
        ready = (self._baseline_result is not None and
                 (self._baseline_only or (self._peak_result is not None and self._composite_result is not None)))
        if not ready or self.preview_busy:
            self._accept_pending = True
            self._preview_timer.stop()
            if self._preview_jobs.is_running and self._active_preview is not None and self._active_preview[1] == self._preview_generation:
                self._fit_after_preview = not self._baseline_only and self._active_preview[0] != "fit"
            else:
                self._request_preview("baseline" if self._baseline_only else "fit", show_errors=True, for_accept=True)
            self._update_preview_buttons()
            return
        self._accept_pending = False
        self._update_preview_buttons()
        if self._baseline_only and not self.create_signal_output():
            QMessageBox.warning(self, self.windowTitle(), "Choose a corrected-signal output worksheet.")
            return
        if self.create_signal_output() and not self.result_sheet_name():
            QMessageBox.warning(self, self.windowTitle(), "Enter a signal result worksheet name.")
            return
        if self.create_peak_output() and not self.peak_sheet_name():
            QMessageBox.warning(self, self.windowTitle(), "Enter a peak table worksheet name.")
            return
        if self.create_fit_output() and (not self.fit_sheet_name() or not self.fit_parameter_sheet_name()):
            QMessageBox.warning(self, self.windowTitle(), "Enter fit curve and parameter worksheet names.")
            return
        if self.application_scope() == "batch" and not self.batch_dataset_names():
            QMessageBox.warning(self, self.windowTitle(), "Select at least one batch worksheet.")
            return
        if self.application_scope() == "map":
            required = {"X", "Y", self.x_column(), self.y_column()}
            if not required.issubset({str(column) for column in self._frame.columns}):
                QMessageBox.warning(
                    self,
                    self.windowTitle(),
                    "Map mode requires X, Y, the selected spectral axis, and intensity columns.",
                )
                return
        self.done(QDialog.Accepted)


def _scientific_spin(value: float, minimum: float, maximum: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setDecimals(9)
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


def _optional_float(text: str, label: str) -> float | None:
    clean = text.strip()
    if not clean:
        return None
    try:
        value = float(clean)
    except ValueError as exc:
        raise ValueError(f"{label.capitalize()} must be numeric or blank.") from exc
    if not np.isfinite(value):
        raise ValueError(f"{label.capitalize()} must be finite.")
    return value


def _parse_anchors(text: str) -> tuple[tuple[float, float], ...]:
    clean = text.strip()
    if not clean:
        return ()
    anchors: list[tuple[float, float]] = []
    for entry in clean.split(";"):
        pieces = entry.strip().replace(",", ":").split(":")
        if len(pieces) != 2:
            raise ValueError("Manual anchors must use x:y pairs separated by semicolons.")
        try:
            anchors.append((float(pieces[0]), float(pieces[1])))
        except ValueError as exc:
            raise ValueError("Manual anchor coordinates must be numeric.") from exc
    return tuple(anchors)


def _parse_anchor_x_values(text: str) -> tuple[float, ...]:
    clean = text.strip()
    if not clean:
        return ()
    pieces = clean.replace(";", " ").replace(",", " ").split()
    try:
        values = tuple(float(piece) for piece in pieces)
    except ValueError as exc:
        raise ValueError(
            "Manual anchor X positions must be numeric and separated by semicolons, commas, or spaces."
        ) from exc
    if not all(np.isfinite(value) for value in values):
        raise ValueError("Manual anchor X positions must be finite.")
    if len(set(values)) != len(values):
        raise ValueError("Manual anchor X positions must be unique.")
    return values


def _profile_section(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = payload.get(name)
    if not isinstance(value, Mapping):
        raise ValueError(f"Analysis profile section '{name}' is missing or invalid.")
    return value


def _profile_optional_number(value: object) -> str:
    if value is None:
        return ""
    number = float(value)
    if not np.isfinite(number):
        raise ValueError("Analysis profile numeric values must be finite.")
    return f"{number:.12g}"


def _select_combo_data(combo: QComboBox, value: object, label: str) -> None:
    index = combo.findData(value)
    if index < 0:
        raise ValueError(f"Unknown {label} in analysis profile: {value!r}.")
    combo.setCurrentIndex(index)


def _preview_positions(x: np.ndarray, y: np.ndarray, *, maximum: int) -> np.ndarray:
    """Return bounded render positions while leaving analysis arrays untouched."""
    finite = np.flatnonzero(np.isfinite(x) & np.isfinite(y))
    if len(finite) <= maximum:
        return finite
    sample = np.linspace(0, len(finite) - 1, maximum, dtype=int)
    return finite[sample]


BaselineCorrectionDialog = PeakAnalysisDialog
