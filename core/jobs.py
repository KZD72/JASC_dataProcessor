"""Qt-independent progress and cooperative cancellation for background work."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event


class JobCancelled(Exception):
    """Raised at a safe work boundary after cancellation is requested."""


@dataclass(frozen=True, slots=True)
class JobProgress:
    """Completed units in the current phase; zero total means indeterminate."""

    completed: int
    total: int
    message: str


class JobContext:
    """Worker-owned progress reporter with a thread-safe cancellation token."""

    def __init__(
        self, cancellation: Event, report: Callable[[JobProgress], None],
    ) -> None:
        self._cancellation = cancellation
        self._report = report

    def check_cancelled(self) -> None:
        """Stop without returning a partial successful result."""
        if self._cancellation.is_set():
            raise JobCancelled()

    def report(self, completed: int, total: int, message: str) -> None:
        """Publish actual phase progress after checking for cancellation."""
        self.check_cancelled()
        self._report(JobProgress(completed, total, message))
