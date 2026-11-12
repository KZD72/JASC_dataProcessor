"""Persistent recording feedback without changing window layout or input handling."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QPaintEvent, QPainter, QPen, QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QToolButton, QWidget

from ui.theme import readable_text


class RecordingBorder(QWidget):
    """Paint only an inset edge; mouse gestures pass through to the application."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.color = QColor("#c62828")
        self.setObjectName("MacroRecordingBorder")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(self.color, 3.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5))


class RecordingFeedback(QObject):
    """Keep a red window edge and a permanent status badge tied to recording state."""

    def __init__(self, window: QMainWindow, stop_action: QAction) -> None:
        super().__init__(window)
        self._window = weakref.ref(window)
        self.active = False
        self._syncing = False
        self.border = RecordingBorder(window)
        self.badge = QWidget(window.statusBar())
        self.badge.setObjectName("MacroRecordingStatus")
        self.label = QLabel("● Recording (.py)")
        self.label.setObjectName("MacroRecordingBadge")
        self.label.setAccessibleName("Python macro recording active")
        self.label.setToolTip("Recording application API calls to a Python script (.py).")
        self.stop_button = QToolButton()
        self.stop_button.setDefaultAction(stop_action)
        self.stop_button.setAccessibleName("Stop macro recording")
        layout = QHBoxLayout(self.badge)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.label)
        layout.addWidget(self.stop_button)
        window.statusBar().addPermanentWidget(self.badge)
        self.badge.hide()
        self._update_colors()
        window.installEventFilter(self)

    def _update_colors(self) -> None:
        window = self._window()
        if window is None:
            return
        dark = window.palette().color(QPalette.Window).lightnessF() < .5
        background = "#ff6464" if dark else "#c62828"
        foreground = readable_text(background, "#ffffff")
        self.border.color = QColor(background)
        self.border.update()
        self.label.setStyleSheet(
            "QLabel#MacroRecordingBadge {"
            f"background-color: {background}; color: {foreground};"
            "border: none; border-radius: 3px; padding: 3px 8px; font-weight: 600; }"
        )

    def _sync_border(self) -> None:
        window = self._window()
        if window is None or self._syncing:
            return
        self._syncing = True
        try:
            self.border.setGeometry(window.rect())
            self.border.raise_()
            self.border.show()
        finally:
            self._syncing = False

    def set_recording(self, active: bool) -> None:
        self.active = active
        self.badge.setVisible(active)
        if active:
            self._update_colors()
            self._sync_border()
        else:
            self.border.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._window():
            if event.type() in (QEvent.PaletteChange, QEvent.ApplicationPaletteChange):
                self._update_colors()
            if self.active and event.type() in (QEvent.Resize, QEvent.Show, QEvent.WindowStateChange,
                                                QEvent.LayoutRequest, QEvent.ChildAdded):
                self._sync_border()
        return False
