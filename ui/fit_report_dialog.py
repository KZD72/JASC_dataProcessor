"""Curve-fit report viewer with actions on its persistent workspace table."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)


class FitReportDialog(QDialog):
    """Display report text while the caller owns persistence and recorded export."""

    export_requested = Signal()
    open_sheet_requested = Signal()

    def __init__(self, report_text: str, parent: QWidget | None = None, *,
                 report_sheet_name: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Fit Report")
        self.setModal(True)
        self.resize(720, 560)
        self._report_text = report_text
        self._report_edit = QPlainTextEdit()
        self._report_edit.setReadOnly(True)
        self._report_edit.setPlainText(report_text)

        layout = QVBoxLayout(self)
        if report_sheet_name:
            saved_hint = QLabel(f"Saved in workspace: {report_sheet_name}")
            saved_hint.setTextFormat(Qt.PlainText)
            saved_hint.setWordWrap(True)
            saved_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(saved_hint)
        layout.addWidget(self._report_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        self._copy_button = buttons.addButton("Copy Report", QDialogButtonBox.ActionRole)
        self._copy_button.clicked.connect(self._copy_report)
        if report_sheet_name:
            self._export_button = buttons.addButton("Export Table...", QDialogButtonBox.ActionRole)
            self._export_button.setToolTip("Export the saved report, parameters and metrics as CSV or tab-delimited text.")
            self._export_button.clicked.connect(self.export_requested)
            self._open_button = buttons.addButton("Open Report Sheet", QDialogButtonBox.ActionRole)
            self._open_button.clicked.connect(self._open_sheet)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @Slot()
    def _copy_report(self) -> None:
        QApplication.clipboard().setText(self._report_text)

    @Slot()
    def _open_sheet(self) -> None:
        self.accept()
        self.open_sheet_requested.emit()
