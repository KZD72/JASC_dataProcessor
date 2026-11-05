"""Independent project plot documents, lazy tab views, and per-plot history."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from collections.abc import Iterator

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QStackedWidget, QTabWidget, QVBoxLayout, QWidget

from core.workspace import SavedPlot, Workspace
from core.plot_documents import rename_editor_columns, rename_editor_dataset
from ui.plot_tab import PlotTab


class PlotDocuments(QWidget):
    """Each open document owns its editor; closed documents keep serializable state."""

    status_message = Signal(str)
    plot_rendered = Signal()
    save_plot_requested = Signal()
    load_plot_requested = Signal()
    remove_plot_requested = Signal()
    new_plot_requested = Signal()
    plot_draft_replaced = Signal()
    options_visibility_changed = Signal(bool)
    dataset_created = Signal(str)
    plot_created = Signal(str)
    documents_changed = Signal()

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._active_editor: PlotTab | None = None
        self._editors: dict[str, PlotTab] = {}
        self._saved: dict[str, str] = {}
        self._undo: dict[str, list[dict[str, object]]] = {}
        self._redo: dict[str, list[dict[str, object]]] = {}
        self._mutating = 0
        self._history_document: str | None = None
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(250)
        self._history_timer.timeout.connect(self._finish_history_group)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self._inspector = QStackedWidget()
        self._inspector.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        corner = QWidget()
        buttons = QHBoxLayout(corner)
        buttons.setContentsMargins(0, 0, 0, 0)
        self._undo_button, self._redo_button = QPushButton("Undo"), QPushButton("Redo")
        self._undo_button.clicked.connect(self.undo)
        self._redo_button.clicked.connect(self.redo)
        plus = QPushButton("+")
        plus.setToolTip("Create an independent plot")
        plus.clicked.connect(lambda: self.new_plot_requested.emit())
        for button in (self._undo_button, self._redo_button, plus):
            buttons.addWidget(button)
        self.tabs.setCornerWidget(corner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)
        self.mark_saved()
        self._placeholder()

    def __getattr__(self, name: str) -> object:
        # MainWindow's existing plotting entry points address the active view.
        # Replacement-producing entry points below explicitly create documents.
        editor = vars(self).get("_active_editor")
        if editor is not None:
            return getattr(editor, name)
        raise AttributeError(name)

    @contextmanager
    def _suspend(self) -> Iterator[None]:
        self._mutating += 1
        try:
            yield
        finally:
            self._mutating -= 1

    def _document(self, editor: PlotTab | None = None) -> SavedPlot | None:
        identity = getattr(editor or self._active_editor, "_document_id", None)
        return next((plot for plot in self._workspace.list_plots() if plot.plot_id == identity), None)

    @property
    def active_document(self) -> SavedPlot | None:
        return self._document()

    @staticmethod
    def _snapshot(plot: SavedPlot) -> dict[str, object]:
        return {"state": deepcopy(plot.state), "editor": deepcopy(plot.editor_state)}

    @staticmethod
    def _fingerprint(plot: SavedPlot) -> str:
        editor = plot.editor_state
        pending = (editor.get("controls") if editor.get("series_dirty")
                   or editor.get("new_series_touched") or editor.get("invalid_settings") else None)
        return json.dumps({"name": plot.name, "state": plot.state, "pending": pending}, sort_keys=True)

    def is_dirty(self) -> bool:
        self.flush()
        return self._saved != {plot.plot_id: self._fingerprint(plot) for plot in self._workspace.list_plots()}

    def mark_saved(self) -> None:
        self.flush()
        self._saved = {plot.plot_id: self._fingerprint(plot) for plot in self._workspace.list_plots()}
        self._finish_history_group()
        self._update_labels()
        self.documents_changed.emit()

    def _make_editor(self, plot: SavedPlot | None) -> PlotTab:
        with self._suspend():
            editor = PlotTab(self._workspace, external_options=True)
            editor._document_id = plot.plot_id if plot is not None else None
            if plot is not None:
                try:
                    editor.load_plot_state(plot.state)
                    editor.restore_editor_state(plot.editor_state)
                except Exception:
                    editor.options_widget().deleteLater()
                    editor.deleteLater()
                    raise
            self._inspector.addWidget(editor.options_widget())
            index = self.tabs.addTab(editor, plot.name if plot is not None else "New plot")
            for name in ("status_message", "save_plot_requested", "load_plot_requested", "remove_plot_requested",
                         "new_plot_requested", "options_visibility_changed", "dataset_created", "plot_created"):
                getattr(editor, name).connect(getattr(self, name).emit)
            editor.plot_rendered.connect(lambda: self._rendered(editor))
            editor.state_changed.connect(lambda: self._changed(editor))
            editor.plot_draft_replaced.connect(lambda: self._changed(editor))
            if plot is not None:
                self._editors[plot.plot_id] = editor
            self.tabs.setCurrentIndex(index)
            self._active_editor = editor
            self._inspector.setCurrentWidget(editor.options_widget())
        return editor

    def _placeholder(self) -> None:
        if not self.tabs.count():
            self._make_editor(None)
        self._update_labels()

    def _remove_editor(self, editor: PlotTab) -> None:
        editor._preview_timer.stop()
        editor._plot_canvas.cancel_surface_cut_selection()
        index = self.tabs.indexOf(editor)
        with self._suspend():
            if index >= 0:
                self.tabs.removeTab(index)
            inspector = editor.options_widget()
            self._inspector.removeWidget(inspector)
            inspector.deleteLater()
            editor.deleteLater()
        self._active_editor = self.tabs.currentWidget()

    def new_plot(self, name: str | None = None) -> SavedPlot:
        self.flush()
        if self._active_editor is not None and self._document() is None:
            self._remove_editor(self._active_editor)
        if name is None:
            index = 1
            while f"Plot {index}" in self._workspace.plot_names():
                index += 1
            name = f"Plot {index}"
        plot = self._workspace.add_plot(name, {})
        editor = self._make_editor(plot)
        self._capture(editor)
        self._undo[plot.plot_id], self._redo[plot.plot_id] = [], []
        self._finish_history_group()
        self._notify()
        return plot

    def open_plot(self, name: str) -> SavedPlot:
        self.flush()
        plot = self._workspace.get_plot(name)
        editor = self._editors.get(plot.plot_id)
        if editor is None:
            placeholder = self._active_editor if self._document() is None else None
            editor = self._make_editor(plot)
            if placeholder is not None:
                self._remove_editor(placeholder)
        self.tabs.setCurrentWidget(editor)
        self._active_editor = editor
        self._inspector.setCurrentWidget(editor.options_widget())
        self._notify()
        return plot

    def close_tab(self, index: int) -> None:
        editor = self.tabs.widget(index)
        if editor is None:
            return
        self._capture(editor)
        plot = self._document(editor)
        if plot is not None:
            self._editors.pop(plot.plot_id, None)
        self._remove_editor(editor)
        self._placeholder()
        self._notify()

    def delete_plot(self, name: str) -> None:
        plot = self._workspace.get_plot(name)
        editor = self._editors.pop(plot.plot_id, None)
        if editor is not None:
            self._remove_editor(editor)
        self._workspace.remove_plot(name)
        self._undo.pop(plot.plot_id, None)
        self._redo.pop(plot.plot_id, None)
        self._placeholder()
        self._notify()

    def rename_active(self, name: str) -> SavedPlot:
        self.flush()
        plot = self.active_document
        if plot is None:
            plot = self.new_plot(name)
        else:
            plot = self._workspace.rename_plot(plot.name, name)
        self._notify()
        return plot

    def options_widget(self) -> QWidget:
        return self._inspector

    def copy_plot_to_clipboard(self) -> bool:
        return self._active_editor.copy_plot_to_clipboard()

    def set_plot_actions_enabled(self, can_save: bool, can_load: bool, can_remove: bool) -> None:
        self._active_editor.set_plot_actions_enabled(can_save, can_load, can_remove)
        self._active_editor._copy_plot_button.setEnabled(self._active_editor.has_plot_series())

    def _capture(self, editor: PlotTab) -> None:
        pending = editor.capture_editor_state()
        try:
            state = editor.current_plot_state()
        except (TypeError, ValueError):
            state = None
            pending["invalid_settings"] = True
        plot = self._document(editor)
        if plot is None:
            if not editor.has_plot_series() and not pending.get("new_series_touched"):
                return
            plot = self._workspace.add_plot("Plot", state or {})
            editor._document_id = plot.plot_id
            self._editors[plot.plot_id] = editor
        if state is not None:
            plot.state = deepcopy(state)
        plot.editor_state = pending

    def flush(self) -> None:
        if self._mutating:
            return
        for index in range(self.tabs.count()):
            self._capture(self.tabs.widget(index))

    def _changed(self, editor: PlotTab) -> None:
        if self._mutating:
            return
        plot = self._document(editor)
        if plot is None:
            editor._new_series_touched = True
        before = self._snapshot(plot) if plot is not None else None
        self._capture(editor)
        plot = self._document(editor)
        if plot is not None and before is not None and before != self._snapshot(plot):
            if self._history_document != plot.plot_id:
                history = self._undo.setdefault(plot.plot_id, [])
                history.append(before)
                del history[:-100]
                self._redo[plot.plot_id] = []
            self._history_document = plot.plot_id
            self._history_timer.start()
        self._notify()

    def _rendered(self, editor: PlotTab) -> None:
        self._changed(editor)
        if not self._mutating:
            self.plot_rendered.emit()

    def _finish_history_group(self) -> None:
        self._history_document = None
        self._history_timer.stop()

    def _tab_changed(self, _index: int) -> None:
        if self._mutating:
            return
        self._finish_history_group()
        self._active_editor = self.tabs.currentWidget()
        if self._active_editor is not None:
            self._inspector.setCurrentWidget(self._active_editor.options_widget())
        self._notify()

    def _update_labels(self) -> None:
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            plot = self._document(editor)
            if plot is not None:
                dirty = self._saved.get(plot.plot_id) != self._fingerprint(plot)
                self.tabs.setTabText(index, plot.name + (" *" if dirty else ""))
                self.tabs.setTabToolTip(index, "Close this tab to keep the plot in Workspace > Plots.")
                editor.set_active_plot_name(plot.name)
        self._undo_button.setEnabled(self.can_undo())
        self._redo_button.setEnabled(self.can_redo())

    def _notify(self) -> None:
        self._update_labels()
        self.documents_changed.emit()

    def can_undo(self) -> bool:
        plot = self.active_document
        return bool(plot is not None and self._undo.get(plot.plot_id))

    def can_redo(self) -> bool:
        plot = self.active_document
        return bool(plot is not None and self._redo.get(plot.plot_id))

    def _restore(self, snapshot: dict[str, object]) -> None:
        plot = self.active_document
        if plot is None or self._active_editor is None:
            return
        with self._suspend():
            plot.state, plot.editor_state = deepcopy(snapshot["state"]), deepcopy(snapshot["editor"])
            self._active_editor.load_plot_state(plot.state)
            self._active_editor.restore_editor_state(plot.editor_state)
        self._notify()

    def undo(self) -> bool:
        self.flush()
        self._finish_history_group()
        plot = self.active_document
        if plot is None or not self.can_undo():
            return False
        self._redo.setdefault(plot.plot_id, []).append(self._snapshot(plot))
        self._restore(self._undo[plot.plot_id].pop())
        return True

    def redo(self) -> bool:
        self.flush()
        self._finish_history_group()
        plot = self.active_document
        if plot is None or not self.can_redo():
            return False
        self._undo.setdefault(plot.plot_id, []).append(self._snapshot(plot))
        self._restore(self._redo[plot.plot_id].pop())
        return True

    def set_workspace(self, workspace: Workspace) -> None:
        with self._suspend():
            for index in range(self.tabs.count() - 1, -1, -1):
                self._remove_editor(self.tabs.widget(index))
            self._editors.clear()
            self._undo.clear()
            self._redo.clear()
            self._workspace = workspace
            self._placeholder()
        self.mark_saved()
        self._notify()

    def refresh_controls(self, selected_dataset: str | None = None) -> None:
        # Sheet navigation must not reset an existing plot's staged editor.
        with self._suspend():
            for editor in self._editors.values():
                pending = editor.capture_editor_state()
                editor.refresh_controls()
                editor.restore_editor_state(pending)
            if self._active_editor is not None and self.active_document is None:
                self._active_editor.refresh_controls(selected_dataset)

    def dataset_renamed(self, old: str, new: str) -> None:
        """Retarget open views; Workspace has already retargeted closed documents."""
        self._invalidate_source_history(old)
        for identity, editor in self._editors.items():
            try:
                state = editor.current_plot_state()
            except (TypeError, ValueError):
                state = deepcopy(self._document(editor).state)
            pending = editor.capture_editor_state()
            before = json.dumps([state, pending], sort_keys=True)
            for series in state.get("series", []):
                for key in ("x_dataset", "y_dataset", "z_dataset"):
                    if series.get(key) == old:
                        series[key] = new
            rename_editor_dataset(pending, old, new)
            if json.dumps([state, pending], sort_keys=True) != before:
                plot = self._document(editor)
                with self._suspend():
                    plot.state, plot.editor_state = state, pending
                    editor.load_plot_state(state)
                    editor.restore_editor_state(pending)
                self._undo.pop(identity, None)
                self._redo.pop(identity, None)
        self._notify()

    def dataset_removed(self, name: str) -> None:
        self.refresh_controls()
        with self._suspend():
            for editor in self._editors.values():
                if any(name in (series.x_dataset, series.y_dataset, series.z_dataset) for series in editor._plot_series):
                    editor._render_plot(silent_if_empty=True, show_validation_messages=False)
        self._notify()

    def rename_column_references(self, dataset: str, names: dict[str, str]) -> None:
        self._invalidate_source_history(dataset)
        for identity, editor in self._editors.items():
            pending = editor.capture_editor_state()
            rename_editor_columns(pending, dataset, names)
            with self._suspend():
                editor.rename_column_references(dataset, names)
                editor.restore_editor_state(pending)
            self._capture(editor)
            self._undo.pop(identity, None)
            self._redo.pop(identity, None)
        self._notify()

    def _invalidate_source_history(self, dataset: str) -> None:
        """Closed tabs retain history, which must not resurrect retired bindings."""
        for identity in set(self._undo) | set(self._redo):
            snapshots = self._undo.get(identity, []) + self._redo.get(identity, [])
            affected = any(
                any(dataset in (series.get("x_dataset"), series.get("y_dataset"), series.get("z_dataset"))
                    for series in snapshot.get("state", {}).get("series", []))
                or any(name.endswith("_dataset_combo") and control.get("text") == dataset
                       for name, control in snapshot.get("editor", {}).get("controls", {}).items())
                for snapshot in snapshots
            )
            if affected:
                self._undo.pop(identity, None)
                self._redo.pop(identity, None)

    def _queue(self, method: str, *args: object, **kwargs: object) -> None:
        title_index = {"queue_single_series_plot": 3, "queue_analysis_plot": 4, "queue_plot_series": 1,
                       "queue_fit_plot": 4}[method]
        title = kwargs.get("title") or (args[title_index] if len(args) > title_index else None)
        if method == "queue_fit_plot":
            title = f"{kwargs.get('model_name') or title or 'Curve'} fit"
        name = str(title or "Analysis plot")
        self.new_plot(name)
        with self._suspend():
            getattr(self._active_editor, method)(*args, **kwargs)
            self._active_editor._new_series_touched = False
        self._capture(self._active_editor)
        self._notify()
        self.plot_rendered.emit()

    def queue_fit_plot(self, *args: object, **kwargs: object) -> None:
        self._queue("queue_fit_plot", *args, **kwargs)

    def queue_analysis_plot(self, *args: object, **kwargs: object) -> None:
        self._queue("queue_analysis_plot", *args, **kwargs)

    def queue_single_series_plot(self, *args: object, **kwargs: object) -> None:
        self._queue("queue_single_series_plot", *args, **kwargs)

    def queue_plot_series(self, *args: object, **kwargs: object) -> None:
        self._queue("queue_plot_series", *args, **kwargs)
