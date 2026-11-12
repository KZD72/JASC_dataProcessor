"""Review a restricted recording and choose explicit file-access folders."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from core.script_language import Program, ScriptError
from core.script_safety import local_spelling
from core.script_jobs import ScriptRequest


class ScriptDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run Python API Recording")
        self.resize(950, 720)
        self.program: Program | None = None
        self.path: Path | None = None
        self.source_path, self.input_dir, self.output_dir = QLineEdit(), QLineEdit(), QLineEdit()
        self.source_path.setReadOnly(True)
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 3600)
        self.timeout.setValue(120)
        self.timeout.setSuffix(" seconds")
        form = QFormLayout()
        form.addRow("Recording (.py)", self.path_row(self.source_path, self.browse_script))
        form.addRow("Allowed input folder", self.path_row(self.input_dir, lambda: self.browse_folder(self.input_dir)))
        form.addRow("Save run inside", self.path_row(self.output_dir, lambda: self.browse_folder(self.output_dir)))
        form.addRow("Time limit", self.timeout)
        hint = QLabel("Only approved JASC calls are accepted. Imports read from the allowed input folder. "
                      "Exports go into a new run subfolder; recorded absolute export paths use their filename. "
                      "Existing files are never overwritten. The current workspace is replaced only after a successful run.")
        hint.setWordWrap(True)
        self.status = QLabel("Choose a recording to review.")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.run_button = buttons.button(QDialogButtonBox.Ok)
        self.run_button.setText("Run Recording")
        self.run_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self.status)
        layout.addWidget(self.preview, 1)
        layout.addWidget(buttons)

    def path_row(self, field: QLineEdit, callback: object) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse…")
        button.clicked.connect(callback)
        layout.addWidget(field, 1)
        layout.addWidget(button)
        return row

    def browse_script(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose API Recording", "", "Python Recording (*.py)")
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> None:
        self.program = None
        self.path = path
        self.source_path.setText(str(path))
        self.preview.clear()
        self.run_button.setEnabled(False)
        try:
            self.program = Program.read(path)
            self.preview.setPlainText(self.program.source)
            self.status.setText(f"Validated {len(self.program.commands)} API command(s). Review the calls and access folders before running.")
            self.run_button.setEnabled(True)
            self.input_dir.setText(str(path.parent))
            self.output_dir.setText(str(path.parent/"jasc_script_outputs"))
        except (OSError, ScriptError) as exc:
            self.status.setText(str(exc))

    def browse_folder(self, field: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Folder", field.text())
        if path:
            field.setText(path)

    def request(self) -> ScriptRequest:
        if self.program is None or self.path is None:
            raise ScriptError("Choose a valid recording first.")
        source, output = self.input_dir.text().strip(), self.output_dir.text().strip()
        local_spelling(source)
        local_spelling(output)
        if not Path(source).is_dir():
            raise ScriptError("Choose an existing input folder.")
        return ScriptRequest(self.program.source, Path(source), Path(output), self.timeout.value(), script_name=self.path.name)

    def accept(self) -> None:
        try:
            self.request()
        except (ScriptError, OSError) as exc:
            self.status.setText(str(exc))
            return
        super().accept()
