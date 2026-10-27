"""One reusable background job with GUI-thread completion and safe lifetime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from core.jobs import JobCancelled, JobContext, JobProgress


class JobProgressWidget(QWidget):
    """Inline progress and cancel controls that keep the workspace accessible."""

    canceled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel("Preparing import...")
        self._label.setMaximumWidth(400)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedWidth(140)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.canceled.emit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        layout.addWidget(self._bar)
        layout.addWidget(cancel)

    def setLabelText(self, text: str) -> None:
        self._label.setText(text)
        self._label.setToolTip(text)

    def setRange(self, minimum: int, maximum: int) -> None:
        self._bar.setRange(minimum, maximum)

    def setValue(self, value: int) -> None:
        self._bar.setValue(value)


@dataclass
class _Outcome:
    result: Any = None
    error: str | None = None
    cancelled: bool = False


class _Worker(QObject):
    progress = Signal(object, object)
    finished = Signal()

    def __init__(self, operation: Callable[[JobContext], Any], cancellation: Event, outcome: _Outcome) -> None:
        super().__init__()
        self._operation = operation
        self._cancellation = cancellation
        self._outcome = outcome

    @Slot()
    def run(self) -> None:
        context = JobContext(self._cancellation, lambda progress: self.progress.emit(self._outcome, progress))
        try:
            context.check_cancelled()
            self._outcome.result = self._operation(context)
            context.check_cancelled()
        except JobCancelled:
            self._outcome.cancelled = True
            self._outcome.result = None
        except Exception as exc:
            logging.getLogger(__name__).exception("Background job failed")
            self._outcome.error = str(exc) or type(exc).__name__
        finally:
            self.finished.emit()


class BackgroundJobController(QObject):
    """Own threads until they stop; invoke callbacks only on the GUI thread.

    Cancellation is checked again before dispatching completion, so a queued
    successful result cannot commit after the user has pressed Cancel.
    """

    progress = Signal(object)
    finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._cancellation = Event()
        self._outcome: _Outcome | None = None
        self._success: Callable[[Any], None] | None = None
        self._failure: Callable[[str], None] | None = None
        self._cancelled: Callable[[], None] | None = None

    @property
    def is_running(self) -> bool:
        """Remain busy until thread termination has been processed."""
        return self._thread is not None

    def start(
        self, operation: Callable[[JobContext], Any], *,
        on_success: Callable[[Any], None], on_error: Callable[[str], None],
        on_cancelled: Callable[[], None],
    ) -> None:
        """Start detached computation; never pass Qt models/workspaces to it."""
        if self.is_running:
            raise RuntimeError("Another background job is still running.")
        self._cancellation = Event()
        self._outcome = _Outcome()
        self._success, self._failure, self._cancelled = on_success, on_error, on_cancelled
        thread = QThread(self)
        worker = _Worker(operation, self._cancellation, self._outcome)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._forward_progress, Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        thread.finished.connect(self._complete)
        self._thread, self._worker = thread, worker
        thread.start()

    def cancel(self) -> None:
        """Request cancellation without blocking or forcibly killing a thread."""
        self._cancellation.set()

    @Slot(object, object)
    def _forward_progress(self, outcome: _Outcome, progress: JobProgress) -> None:
        if outcome is self._outcome and self.is_running and not self._cancellation.is_set():
            self.progress.emit(progress)

    @Slot()
    def _complete(self) -> None:
        thread, outcome = self._thread, self._outcome
        worker = self._worker
        success, failure, cancelled = self._success, self._failure, self._cancelled
        was_cancelled = self._cancellation.is_set() or bool(outcome and outcome.cancelled)
        if thread is not None:
            # finished can precede final thread-local cleanup. Join only here,
            # after the worker has returned, before releasing its Qt owner.
            thread.wait()
            thread.deleteLater()
        self._thread = self._worker = self._outcome = None
        self._success = self._failure = self._cancelled = None
        del worker  # Release the Python wrapper only after thread-local cleanup.
        try:
            if was_cancelled:
                cancelled()
            elif outcome.error is not None:
                failure(outcome.error)
            else:
                success(outcome.result)
        except Exception as exc:
            logging.getLogger(__name__).exception("Background result callback failed")
            if failure is not None:
                failure(str(exc) or type(exc).__name__)
        finally:
            self.finished.emit()
