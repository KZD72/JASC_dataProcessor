"""Review a recorded macro, select inputs, and preview compatibility."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from core.macro_jobs import MacroSource, folder_sources
from models.macro import ColumnRef, Macro
from math_engine.smoothing import SMOOTHING_METHODS


class MacroDialog(QDialog):
    preview_requested = Signal()
    cancel_preview = Signal()

    def __init__(self, macro: Macro, datasets: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review and Run Macro")
        self.resize(1000, 720)
        self.macro = deepcopy(macro)
        self.busy = False
        self.saved_state = None
        self.ready_sources: list[MacroSource] = []
        self.file_sources: dict[str, MacroSource] = {}
        self.name = QLineEdit(macro.name)
        self.steps = QListWidget()
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.targets = QListWidget()
        for dataset in datasets:
            item = QListWidgetItem(dataset)
            item.setData(Qt.UserRole, ("workspace", dataset))
            item.setCheckState(Qt.Unchecked)
            self.targets.addItem(item)
        self.recursive = QCheckBox("Include subfolders")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Preview checks columns and dependencies. Numerical validation also runs at each step.")
        self.open_first = QCheckBox("Open the first generated plot")
        self.open_first.setChecked(True)
        self.export_folder = QLineEdit()
        self.export_folder.setReadOnly(True)
        self.export_folder.setPlaceholderText("Optional: export generated tables to a new run folder")
        self.preview_button = QPushButton("Preview Compatibility")
        self.cancel_button = QPushButton("Cancel Preview")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_preview.emit)
        self.run_button = QPushButton("Run Macro")
        self.run_button.setEnabled(False)
        self.preview_button.clicked.connect(self.preview_requested.emit)
        self.run_button.clicked.connect(self.accept)
        left, right = QWidget(), QWidget()
        a, b = QVBoxLayout(left), QVBoxLayout(right)
        a.addWidget(QLabel("Repeat these steps for each datasheet"))
        a.addWidget(self.steps, 2)
        actions = QHBoxLayout()
        for text, callback in (("Up", lambda: self.move(-1)), ("Down", lambda: self.move(1)),
                               ("Remove", self.remove), ("Edit Settings", self.edit)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        a.addLayout(actions)
        a.addWidget(self.details, 2)
        b.addWidget(QLabel("Inputs: choose workspace sheets and/or add folder files"))
        b.addWidget(self.targets, 2)
        files = QHBoxLayout()
        for text, callback in (("Add Files", self.add_files), ("Add Folder", self.add_folder),
                               ("Select All", lambda: self.select_all(True)), ("Clear Selection", lambda: self.select_all(False))):
            button = QPushButton(text)
            button.clicked.connect(callback)
            files.addWidget(button)
        b.addLayout(files)
        b.addWidget(self.recursive)
        b.addWidget(self.preview_button)
        b.addWidget(self.cancel_button)
        b.addWidget(self.preview, 2)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([470, 530])
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Macro name", self.name)
        layout.addLayout(form)
        note = QLabel("Records Smoothing, Curve Fit, and ordinary XY plots. Import settings are reused for new files. "
                      "Results are new worksheets and plots; source sheets stay unchanged. Macros are saved separately from projects.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(splitter, 1)
        output = QHBoxLayout()
        output.addWidget(self.export_folder, 1)
        choose = QPushButton("Export Tables To…")
        choose.clicked.connect(self.choose_export)
        output.addWidget(choose)
        layout.addLayout(output)
        layout.addWidget(self.open_first)
        buttons = QHBoxLayout()
        save = QPushButton("Save Macro…")
        save.clicked.connect(self.save)
        buttons.addWidget(save)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        buttons.addWidget(self.run_button)
        layout.addLayout(buttons)
        self.steps.currentRowChanged.connect(self.describe)
        self.targets.itemChanged.connect(self.invalidate)
        self.name.textChanged.connect(self.invalidate)
        self.refresh()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget in (self.name, self.steps, self.targets):
            widget.setEnabled(not busy)
        for button in self.findChildren(QPushButton):
            button.setEnabled(not busy or button is self.cancel_button)
        self.cancel_button.setVisible(busy)
        self.run_button.setEnabled(not busy and bool(self.ready_sources))

    def reject(self) -> None:
        if self.busy:
            self.cancel_preview.emit()
        else:
            super().reject()

    def closeEvent(self, event) -> None:
        if self.busy:
            self.cancel_preview.emit()
            event.ignore()
        else:
            super().closeEvent(event)

    def invalidate(self, *_args: object) -> None:
        self.ready_sources = []
        self.run_button.setEnabled(False)
        self.preview.clear()

    def refresh(self, selected: int = 0) -> None:
        self.steps.clear()
        for step in self.macro.steps:
            description = (step.settings.get("name") or step.settings.get("model_key")
                           or SMOOTHING_METHODS.get(step.settings.get("method"), step.settings.get("method", "")))
            self.steps.addItem(f"{step.operation.title()}: {description}")
        self.steps.setCurrentRow(min(selected, self.steps.count()-1))
        self.invalidate()
        if self.macro.issues:
            self.preview.setPlainText("Recording gaps — start a clean recording to run this routine:\n" + "\n".join(self.macro.issues))

    def describe(self, index: int) -> None:
        if not 0 <= index < len(self.macro.steps):
            self.details.clear()
            return
        step = self.macro.steps[index]
        lines = [step.operation.title(), ""]
        lines += [f"{name}: {ref.column} from {ref.table}" for name, ref in step.inputs.items()]
        for name, value in step.settings.items():
            if name not in {"state", "custom_models"}:
                if isinstance(value, dict):
                    lines.append(name.replace("_", " ").capitalize()+":")
                    lines += [f"  {key.replace('_', ' ').capitalize()}: {item}" for key, item in value.items()]
                elif isinstance(value, list):
                    lines.append(f"{name.replace('_', ' ').capitalize()}: " + ", ".join("Unbounded" if item is None else str(item) for item in value))
                else:
                    display = SMOOTHING_METHODS.get(value, value) if name == "method" else value
                    lines.append(f"{name.replace('_', ' ').capitalize()}: {display}")
        self.details.setPlainText("\n".join(lines))

    def move(self, direction: int) -> None:
        index = self.steps.currentRow()
        target = index+direction
        if index < 0 or not 0 <= target < len(self.macro.steps):
            return
        candidate = deepcopy(self.macro)
        candidate.steps[index], candidate.steps[target] = candidate.steps[target], candidate.steps[index]
        try:
            candidate.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Step Dependency", str(exc))
            return
        self.macro = candidate
        self.refresh(target)

    def remove(self) -> None:
        index = self.steps.currentRow()
        if index < 0:
            return
        candidate = deepcopy(self.macro)
        del candidate.steps[index]
        try:
            candidate.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Step Dependency", str(exc))
            return
        self.macro = candidate
        self.refresh(index)

    def edit(self) -> None:
        index = self.steps.currentRow()
        if index < 0:
            return
        step = deepcopy(self.macro.steps[index])
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit {step.operation.title()} Settings")
        form = QFormLayout(dialog)
        controls = []
        for name, value in step.settings.items():
            if name in {"state", "custom_models", "x_bounds", "y_bounds"}:
                continue
            entries = value.items() if name == "parameters" else [(name, value)]
            for key, entry in entries:
                if key == "method" and step.operation == "smooth":
                    widget = QComboBox()
                    for code, label in SMOOTHING_METHODS.items():
                        widget.addItem(label, code)
                    widget.setCurrentIndex(widget.findData(entry))
                    getter = widget.currentData
                elif isinstance(entry, bool):
                    widget = QCheckBox()
                    widget.setChecked(entry)
                    getter = widget.isChecked
                elif isinstance(entry, int):
                    widget = QSpinBox()
                    widget.setRange(0, 100000)
                    widget.setValue(entry)
                    getter = widget.value
                elif isinstance(entry, float):
                    widget = QDoubleSpinBox()
                    widget.setDecimals(10)
                    widget.setRange(-1.e10, 1.e10)
                    widget.setValue(entry)
                    getter = widget.value
                else:
                    widget = QLineEdit(", ".join("" if item is None else str(item) for item in entry) if isinstance(entry, list) else str(entry))
                    if isinstance(entry, list):
                        def getter(editor=widget, original=entry):
                            tokens = editor.text().split(",")
                            if len(tokens) != len(original):
                                raise ValueError("Keep the same number of parameter values.")
                            if all(isinstance(item, bool) for item in original):
                                if any(token.strip().lower() not in {"true", "false"} for token in tokens):
                                    raise ValueError("Fixed parameters must be True or False.")
                                return [token.strip().lower() == "true" for token in tokens]
                            return [float(token) if token.strip() else None for token in tokens]
                    else:
                        getter = widget.text
                form.addRow(key.replace("_", " ").capitalize(), widget)
                controls.append((name if name == "parameters" else None, key, getter))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            try:
                for parent, key, getter in controls:
                    (step.settings[parent] if parent else step.settings)[key] = getter()
                candidate = deepcopy(self.macro)
                candidate.steps[index] = step
                candidate.validate()
                self.macro = candidate
                self.refresh(index)
            except (ValueError, TypeError) as exc:
                QMessageBox.warning(self, "Macro Settings", str(exc))

    def select_all(self, checked: bool) -> None:
        for index in range(self.targets.count()):
            self.targets.item(index).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def add_paths(self, paths: list[Path]) -> None:
        for path in paths:
            key = str(path.resolve())
            if key in self.file_sources:
                continue
            self.file_sources[key] = MacroSource(key, path.stem, path=path)
            item = QListWidgetItem(str(path))
            item.setData(Qt.UserRole, ("file", key))
            item.setCheckState(Qt.Checked)
            self.targets.addItem(item)
        self.invalidate()

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Macro Input Files", "", "Data files (*.csv *.dat *.txt)")
        self.add_paths([Path(path) for path in paths])

    def add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Macro Input Folder")
        if path:
            self.add_paths([source.path for source in folder_sources(Path(path), self.recursive.isChecked())])

    def choose_export(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Macro Table Output Folder")
        if path:
            self.export_folder.setText(path)

    def save(self) -> None:
        self.macro.name = self.name.text().strip()
        path, _ = QFileDialog.getSaveFileName(self, "Save Macro", self.macro.name+".jasc-macro.json", "JASC Macro (*.jasc-macro.json)")
        if path:
            try:
                self.macro.save(path)
                self.saved_state = self.macro.to_state()
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "Save Macro", str(exc))
