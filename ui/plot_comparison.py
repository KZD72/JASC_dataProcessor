"""Selectable, equal-cell native plot comparisons with independent navigation."""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QToolBar, QVBoxLayout, QWidget,
)

from core.plot_comparison import comparison_state, is_comparison, suggested_grid, validated_comparison
from core.workspace import Workspace
from models.plot_settings import PlotSettings
from ui.plot_canvas import PlotCanvas
from ui.plot_tab import PlotTab


class ComparePlotsDialog(QDialog):
    """Choose source plots, panel order, equal-cell grid, and optional common ranges."""

    def __init__(self, workspace: Workspace, state: dict[str, object] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compare Plots")
        self.resize(520, 560)
        self._workspace = workspace
        self._plots = QListWidget()
        self._plots.setDragDropMode(QAbstractItemView.InternalMove)
        self._plots.setDefaultDropAction(Qt.MoveAction)
        available = [plot for plot in workspace.list_plots() if not is_comparison(plot.state) and plot.state.get("series")]
        previous = (state or {}).get("plot_ids", [])
        ordered = sorted(available, key=lambda plot: previous.index(plot.plot_id) if plot.plot_id in previous else len(previous))
        for plot in ordered:
            item = QListWidgetItem(plot.name)
            item.setData(Qt.UserRole, plot.plot_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
            item.setCheckState(Qt.Checked if plot.plot_id in previous else Qt.Unchecked)
            self._plots.addItem(item)
        self._name = QLineEdit("Plot comparison")
        self._rows, self._columns = QSpinBox(), QSpinBox()
        for spin in (self._rows, self._columns):
            spin.setRange(1, 4)
        self._rows.setValue(int((state or {}).get("rows", 1)))
        self._columns.setValue(int((state or {}).get("columns", 2)))
        self._match_x, self._match_y = QCheckBox("Synchronize X axis"), QCheckBox("Synchronize Y axis")
        self._letters = QCheckBox("Show panel labels (A, B, C...)")
        self._match_x.setChecked(bool((state or {}).get("match_x")))
        self._match_y.setChecked(bool((state or {}).get("match_y")))
        self._letters.setChecked(bool((state or {}).get("panel_labels", True)))
        self._pop_out = QCheckBox("Open in a separate window")
        form = QFormLayout()
        if state is None:
            form.addRow("Comparison name", self._name)
        else:
            self._name.hide()
        form.addRow("Rows", self._rows)
        form.addRow("Columns", self._columns)
        order = QHBoxLayout()
        for label, offset in (("Move Up", -1), ("Move Down", 1)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, step=offset: self._move(step))
            order.addWidget(button)
        auto = QPushButton("Fit Grid")
        auto.clicked.connect(self._fit_grid)
        order.addWidget(auto)
        self._count = QLabel()
        self._plots.itemChanged.connect(self._update_count)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose plots and drag or move them into panel order:"))
        layout.addWidget(self._plots, 1)
        layout.addLayout(order)
        layout.addWidget(self._count)
        layout.addLayout(form)
        layout.addWidget(self._match_x)
        layout.addWidget(self._match_y)
        layout.addWidget(self._letters)
        if state is None:
            layout.addWidget(self._pop_out)
        else:
            self._pop_out.hide()
        note = QLabel("Grid cells have equal dimensions. Matching limits does not convert units.\n"
                      "Comparisons show applied plot definitions; update pending series edits first.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self._update_count()

    def selected_ids(self) -> list[str]:
        return [self._plots.item(row).data(Qt.UserRole) for row in range(self._plots.count())
                if self._plots.item(row).checkState() == Qt.Checked]

    def _move(self, offset: int) -> None:
        row = self._plots.currentRow()
        if row >= 0 and 0 <= row + offset < self._plots.count():
            item = self._plots.takeItem(row)
            self._plots.insertItem(row + offset, item)
            self._plots.setCurrentItem(item)

    def _fit_grid(self) -> None:
        rows, columns = suggested_grid(len(self.selected_ids()))
        self._rows.setValue(rows)
        self._columns.setValue(columns)

    def _update_count(self, *_args: object) -> None:
        count = len(self.selected_ids())
        self._count.setText(f"{count} plot(s) selected; up to 16 panels.")
        if self._rows.value() * self._columns.value() < count <= 16:
            self._fit_grid()

    def specification(self) -> dict[str, object]:
        names = {plot.plot_id: plot.name for plot in self._workspace.list_plots()}
        return comparison_state(self.selected_ids(), self._rows.value(), self._columns.value(),
                                match_x=self._match_x.isChecked(), match_y=self._match_y.isChecked(),
                                panel_labels=self._letters.isChecked(), name_hints=names)

    def accept(self) -> None:
        try:
            self.specification()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Compare Plots", str(exc))
            return
        super().accept()


def _render_options(state: dict[str, object]) -> dict[str, object]:
    """Translate typed saved settings to the existing PlotCanvas renderer contract."""
    settings = PlotSettings.from_state(state.get("settings", {}))
    names = [token.strip() for token in settings.style.preset.split(",") if token.strip()]
    if settings.style.cycle:
        names.append(settings.style.cycle)
    names.extend(token.strip() for token in settings.style.custom.split(",") if token.strip() and token.strip() not in names)
    if "science" in names and not settings.style.use_latex and "no-latex" not in names:
        names.append("no-latex")
    options: dict[str, object] = {
        "title": settings.title, "x_label": settings.x_axis.label, "y_label": settings.left_y_axis.label,
        "right_y_label": settings.right_y_axis.label, "grid_enabled": settings.grid_enabled,
        "legend_settings": settings.legend, "style_names": names,
        "locators": [PlotTab._plot_locator_from_state(value) for value in state.get("locators", [])],
    }
    for prefix, axis in (("x", settings.x_axis), ("y", settings.left_y_axis), ("right_y", settings.right_y_axis)):
        options[f"{prefix}_scale"] = axis.scale
        options[f"{prefix}_limits"] = tuple(float(value) if value.strip() else None for value in (axis.minimum, axis.maximum))
        options[f"{prefix}_label_font_size"] = axis.label_font_size
        options[f"{prefix}_tick_font_size"] = axis.tick_font_size
    return options


class PlotComparisonView(QWidget):
    """Read-only native plot panels; layout controls never mutate source documents."""

    status_message = Signal(str)
    plot_rendered = Signal()
    plot_draft_replaced = Signal()
    state_changed = Signal()
    detach_requested = Signal()
    source_requested = Signal(str)
    save_plot_requested = Signal()
    new_plot_requested = Signal()
    remove_plot_requested = Signal()
    load_plot_requested = Signal()
    options_visibility_changed = Signal(bool)
    dataset_created = Signal(str)
    plot_created = Signal(str)

    def __init__(self, workspace: Workspace, state: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._state = validated_comparison(state)
        self._panels: list[tuple[str, PlotCanvas]] = []
        self._plot_series = []
        self._new_series_touched = False
        self._loading = False
        self._linking = False
        self._source_fingerprint = ""
        self._plot_options_visible = True
        self._compatible_axes: dict[str, bool] = {}
        self._valid_panels: list[PlotCanvas] = []
        self._inspector = QWidget()
        form = QVBoxLayout(self._inspector)
        form.addWidget(QLabel("Comparison layout"))
        self._selection = QPushButton("Choose / Reorder Plots...")
        self._selection.clicked.connect(self._edit_selection)
        form.addWidget(self._selection)
        grid_form = QFormLayout()
        self._rows, self._columns = QSpinBox(), QSpinBox()
        for spin in (self._rows, self._columns):
            spin.setRange(1, 4)
        self._rows.setValue(self._state["rows"])
        self._columns.setValue(self._state["columns"])
        grid_form.addRow("Rows", self._rows)
        grid_form.addRow("Columns", self._columns)
        form.addLayout(grid_form)
        fit_grid = QPushButton("Fit Grid")
        fit_grid.clicked.connect(self._fit_grid)
        form.addWidget(fit_grid)
        form.addWidget(QLabel("Axis synchronization"))
        self._match_x, self._match_y = QCheckBox("Synchronize X axis"), QCheckBox("Synchronize Y axis")
        self._letters = QCheckBox("Panel labels")
        for widget, key in ((self._match_x, "match_x"), (self._match_y, "match_y"), (self._letters, "panel_labels")):
            widget.setChecked(self._state[key])
            widget.toggled.connect(self._layout_changed)
            form.addWidget(widget)
        for widget in (self._match_x, self._match_y):
            widget.setToolTip("Share limits and synchronize wheel, pan, and zoom across panels, including image maps.")
        self._rows.valueChanged.connect(self._layout_changed)
        self._columns.valueChanged.connect(self._layout_changed)
        self._sources_label = QLabel()
        self._sources_label.setWordWrap(True)
        form.addWidget(self._sources_label)
        explanation = QLabel("Equal grid cells retain each plot's styling and aspect ratio.\n"
                             "Synchronized axes link zoom and pan, including image maps, without unit conversion.")
        explanation.setWordWrap(True)
        form.addWidget(explanation)
        form.addStretch(1)
        self._active_plot_label = QLabel("Plot comparison")
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.addWidget(self._active_plot_label)
        for text, callback in (("Refresh", self.refresh), ("Edit Comparison...", self._edit_selection),
                               ("Export PNG...", self._export_dialog)):
            action = toolbar.addAction(text)
            action.triggered.connect(lambda _checked=False, function=callback: function())
        self._detach_action = toolbar.addAction("Pop Out", self.detach_requested.emit)
        self._pan_action = toolbar.addAction("Pan")
        self._zoom_action = toolbar.addAction("Zoom")
        for action, mode in ((self._pan_action, "pan"), (self._zoom_action, "zoom")):
            action.setCheckable(True)
            action.triggered.connect(lambda checked, name=mode: self._navigation(name, checked))
        toolbar.addAction("Reset View", self.refresh)
        self._copy_plot_button = QPushButton("Copy")
        self._copy_plot_button.clicked.connect(self.copy_plot_to_clipboard)
        copy_action = toolbar.addWidget(self._copy_plot_button)
        copy_action.setText("Copy")
        self._grid_widget = QWidget()
        self._grid_widget.setObjectName("PlotComparisonGrid")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setContentsMargins(2, 2, 2, 2)
        self._grid.setSpacing(8)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._grid_widget)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._content = QWidget()
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(toolbar)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._status)
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self._outer_layout.addWidget(self._content)
        self._detached_notice = QWidget()
        notice = QVBoxLayout(self._detached_notice)
        notice.addStretch()
        message = QLabel("This comparison is open in a separate window.")
        message.setAlignment(Qt.AlignCenter)
        notice.addWidget(message)
        return_button = QPushButton("Return to Tab")
        return_button.clicked.connect(self.detach_requested.emit)
        notice.addWidget(return_button, alignment=Qt.AlignCenter)
        notice.addStretch()
        self._outer_layout.addWidget(self._detached_notice)
        self._detached_notice.hide()
        self.refresh()

    def take_content(self) -> QWidget:
        self._outer_layout.removeWidget(self._content)
        self._detached_notice.show()
        self._detach_action.setText("Return to Tab")
        return self._content

    def return_content(self) -> None:
        self._outer_layout.insertWidget(0, self._content)
        self._detached_notice.hide()
        self._detach_action.setText("Pop Out")

    def options_widget(self) -> QWidget:
        return self._inspector

    def has_plot_series(self) -> bool:
        return bool(self._state["plot_ids"])

    def has_unapplied_series_edits(self) -> bool:
        return False

    def current_plot_state(self) -> dict[str, object]:
        return deepcopy(self._state)

    def capture_editor_state(self) -> dict[str, object]:
        return {"panel_views": {identity: {"xlim": list(canvas.axes.get_xlim()), "ylim": list(canvas.axes.get_ylim())}
                                for identity, canvas in self._panels}}

    def restore_editor_state(self, state: dict[str, object]) -> None:
        for axis in ("x", "y"):
            linked = self._state[f"match_{axis}"] and self._compatible_axes.get(axis)
            for identity, canvas in self._panels:
                limits = state.get("panel_views", {}).get(identity, {}).get(f"{axis}lim")
                if limits is None:
                    continue
                try:
                    if linked:
                        self._set_limits(axis, limits)
                        break
                    getattr(canvas.axes, f"set_{axis}lim")(limits)
                    canvas.canvas.draw_idle()
                except (TypeError, ValueError):
                    pass

    def load_plot_state(self, state: dict[str, object]) -> None:
        self._state = validated_comparison(state)
        self._loading = True
        try:
            self._rows.setValue(self._state["rows"])
            self._columns.setValue(self._state["columns"])
            self._match_x.setChecked(self._state["match_x"])
            self._match_y.setChecked(self._state["match_y"])
            self._letters.setChecked(self._state["panel_labels"])
        finally:
            self._loading = False
        self.refresh()

    def _layout_changed(self, *_args: object) -> None:
        if self._loading:
            return
        # Grow the other dimension, then clamp the requested dimension if needed.
        rows, columns, count = self._rows.value(), self._columns.value(), len(self._state["plot_ids"])
        if rows * columns < count:
            self._loading = True
            if self.sender() is self._rows:
                self._columns.setValue(min(4, int(np.ceil(count / rows))))
                self._rows.setValue(max(rows, int(np.ceil(count / self._columns.value()))))
            else:
                self._rows.setValue(min(4, int(np.ceil(count / columns))))
                self._columns.setValue(max(columns, int(np.ceil(count / self._rows.value()))))
            self._loading = False
        self._state = comparison_state(self._state["plot_ids"], self._rows.value(), self._columns.value(),
                                       match_x=self._match_x.isChecked(), match_y=self._match_y.isChecked(),
                                       panel_labels=self._letters.isChecked(), name_hints=self._state["name_hints"])
        self.refresh()
        self.state_changed.emit()

    def _fit_grid(self) -> None:
        rows, columns = suggested_grid(len(self._state["plot_ids"]))
        self._loading = True
        self._rows.setValue(rows)
        self._columns.setValue(columns)
        self._loading = False
        self._layout_changed()

    def _edit_selection(self) -> None:
        dialog = ComparePlotsDialog(self._workspace, self._state, self)
        if dialog.exec() == QDialog.Accepted:
            self.load_plot_state(dialog.specification())
            self.state_changed.emit()
        dialog.deleteLater()

    def refresh_if_sources_changed(self) -> None:
        sources = {plot.plot_id: [plot.name, plot.state] for plot in self._workspace.list_plots()
                   if plot.plot_id in self._state["plot_ids"]}
        if json.dumps(sources, sort_keys=True) != self._source_fingerprint:
            self.refresh()

    def refresh(self, *_args: object) -> None:
        self._pan_action.setChecked(False)
        self._zoom_action.setChecked(False)
        self.release_views()
        self._panels = []
        self._valid_panels = []
        self._compatible_axes = {}
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        plots = {plot.plot_id: plot for plot in self._workspace.list_plots()}
        messages, names = [], []
        self._source_fingerprint = json.dumps({identity: [plots[identity].name, plots[identity].state]
                                               for identity in self._state["plot_ids"] if identity in plots}, sort_keys=True)
        for index, identity in enumerate(self._state["plot_ids"]):
            plot = plots.get(identity)
            names.append(plot.name if plot is not None else self._state["name_hints"].get(identity, "Missing plot"))
            canvas = PlotCanvas()
            canvas.toolbar.hide()
            canvas.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            self._grid.addWidget(canvas, index // self._state["columns"], index % self._state["columns"])
            self._panels.append((identity, canvas))
            try:
                if plot is None or is_comparison(plot.state):
                    raise ValueError(f"Source plot is unavailable: {self._state['name_hints'].get(identity, identity)}")
                options = _render_options(plot.state)
                options["title"] = options["title"] or plot.name
                series = [PlotTab._plot_series_from_state(value) for value in plot.state.get("series", [])]
                result = canvas.plot_series(self._workspace, series, **options)
                messages.extend(result.skipped_messages)
                if result.plotted_count:
                    # Composition/category positions are not numeric ranges to link.
                    excluded = {"pie", "donut", "voronoi", "box", "violin"}
                    numeric = not any(value.plot_type in excluded for value in series)
                    numeric = numeric and all(getattr(canvas.axes, f"{axis}axis").get_units() is None for axis in ("x", "y"))
                    if numeric:
                        self._valid_panels.append(canvas)
            except (TypeError, ValueError, KeyError) as exc:
                canvas._draw_error_state(str(exc))
                messages.append(str(exc))
            if self._state["panel_labels"]:
                canvas.axes.text(0.01, 0.99, chr(65 + index), transform=canvas.axes.transAxes,
                                 va="top", ha="left", fontweight="bold", fontsize=11)
            # Each cell can be much smaller than a standalone plot. Reflow its
            # margins during canvas resize/export so axis labels stay visible.
            canvas.figure.set_layout_engine("tight", pad=1.0)
            canvas.toolbar.update()
            canvas.axes.callbacks.connect("xlim_changed", lambda axes: self._link_limits("x", axes))
            canvas.axes.callbacks.connect("ylim_changed", lambda axes: self._link_limits("y", axes))
            canvas.canvas.mpl_connect("button_press_event", lambda event, key=identity: self._open_source(event, key))
        # Empty trailing cells keep the occupied cells equal rather than spanning.
        for index in range(len(self._panels), self._state["rows"] * self._state["columns"]):
            empty = QWidget()
            empty.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            self._grid.addWidget(empty, index // self._state["columns"], index % self._state["columns"])
        for index in range(4):
            self._grid.setRowStretch(index, 1 if index < self._state["rows"] else 0)
            self._grid.setColumnStretch(index, 1 if index < self._state["columns"] else 0)
        self._grid_widget.setMinimumSize(self._state["columns"] * 280, self._state["rows"] * 230)
        for axis in ("x", "y"):
            if self._state[f"match_{axis}"]:
                scales = {getattr(canvas.axes, f"get_{axis}scale")() for canvas in self._valid_panels}
                self._compatible_axes[axis] = len(scales) == 1 and len(self._valid_panels) == len(self._panels)
                if self._compatible_axes[axis]:
                    limits = [getattr(canvas.axes, f"get_{axis}lim")() for canvas in self._valid_panels]
                    shared = min(min(value) for value in limits), max(max(value) for value in limits)
                    if limits[0][0] > limits[0][1]:
                        shared = shared[::-1]
                    self._set_limits(axis, shared)
                else:
                    messages.append(f"Matching {axis.upper()} limits skipped: use available numeric panels with the same scale.")
        for _, canvas in self._panels:
            canvas.canvas.draw_idle()
        self._sources_label.setText("Panels:\n" + "\n".join(f"{index + 1}. {name}" for index, name in enumerate(names)))
        self._status.setText(" | ".join(dict.fromkeys(messages)) or "Double-click a panel to open its source plot.")
        self.plot_rendered.emit()

    def _set_limits(self, axis: str, limits: tuple[float, float]) -> None:
        if self._linking:
            return
        self._linking = True
        try:
            for _, canvas in self._panels:
                getattr(canvas.axes, f"set_{axis}lim")(limits)
                canvas.canvas.draw_idle()
        finally:
            self._linking = False

    def _link_limits(self, axis: str, axes: object) -> None:
        if not self._state[f"match_{axis}"] or self._linking or not self._compatible_axes.get(axis):
            return
        self._set_limits(axis, getattr(axes, f"get_{axis}lim")())

    def _navigation(self, mode: str, checked: bool) -> None:
        self._pan_action.setChecked(checked if mode == "pan" else False)
        self._zoom_action.setChecked(checked if mode == "zoom" else False)
        for _, canvas in self._panels:
            active = canvas.toolbar.mode.name.lower()
            if active in {"pan", "zoom"}:
                getattr(canvas.toolbar, active)()
            if checked:
                getattr(canvas.toolbar, mode)()

    def _open_source(self, event: object, identity: str) -> None:
        if getattr(event, "dblclick", False):
            self.source_requested.emit(identity)

    def set_active_plot_name(self, name: str | None) -> None:
        self._active_plot_label.setText(name or "Plot comparison")

    def set_plot_actions_enabled(self, can_save: bool, can_load: bool, can_remove: bool) -> None:
        self._copy_plot_button.setEnabled(bool(self._panels))

    def set_plot_options_visible(self, visible: bool) -> None:
        if visible != self._plot_options_visible:
            self._plot_options_visible = visible
            self.options_visibility_changed.emit(visible)

    def plot_options_visible(self) -> bool:
        return self._plot_options_visible

    def refresh_controls(self, selected_dataset: str | None = None) -> None:
        self.refresh_if_sources_changed()

    def rename_column_references(self, dataset: str, names: dict[str, str]) -> None:
        self.refresh()

    def reset_view_to_default(self) -> None:
        self.refresh()

    def release_views(self) -> None:
        for _, canvas in self._panels:
            canvas._mouse_navigation.reset()
            canvas.cancel_surface_cut_selection(notify=False)

    def copy_plot_to_clipboard(self) -> bool:
        QApplication.clipboard().setPixmap(self._grid_widget.grab())
        return True

    def export_png(self, path: str | Path, cell_width: int = 1000, cell_height: int = 750) -> None:
        """Render native panel figures at equal high-resolution sizes into one PNG."""
        image = QImage(self._state["columns"] * cell_width, self._state["rows"] * cell_height, QImage.Format_RGB32)
        image.fill(Qt.white)
        painter = QPainter(image)
        try:
            for index, (_identity, canvas) in enumerate(self._panels):
                previous = canvas.figure.get_size_inches().copy()
                try:
                    canvas.figure.set_size_inches(cell_width / 150, cell_height / 150, forward=False)
                    buffer = BytesIO()
                    canvas.figure.savefig(buffer, format="png", dpi=150, bbox_inches=None)
                    panel = QImage.fromData(buffer.getvalue(), "PNG")
                    painter.drawImage((index % self._state["columns"]) * cell_width,
                                      (index // self._state["columns"]) * cell_height, panel)
                finally:
                    canvas.figure.set_size_inches(previous, forward=False)
                    canvas.canvas.draw_idle()
        finally:
            painter.end()
        if not image.save(str(path), "PNG"):
            raise OSError("Could not write comparison PNG.")

    def _export_dialog(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "Export Comparison", "comparison.png", "PNG image (*.png)")
        if path:
            try:
                self.export_png(path)
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.warning(self, "Export Comparison", str(exc))
