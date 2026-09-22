"""Reusable batch execution helpers.

The worker functions in this module must stay top-level and avoid Qt objects.
That keeps process-based batch execution compatible with Windows spawn mode and
future PyInstaller builds.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import pandas as pd

from core.operations import ExpressionError, apply_column_expression

BATCH_EXECUTION_AUTO = "auto"
BATCH_EXECUTION_SEQUENTIAL = "sequential"
BATCH_EXECUTION_PARALLEL = "parallel"
BATCH_EXECUTION_MODES = {
    BATCH_EXECUTION_AUTO,
    BATCH_EXECUTION_SEQUENTIAL,
    BATCH_EXECUTION_PARALLEL,
}

FORMULA_PARALLEL_MIN_TASKS = 2
FORMULA_PARALLEL_MIN_CELLS = 250_000


@dataclass(frozen=True, slots=True)
class BatchExecutionDecision:
    """Resolved execution strategy for one batch run."""

    requested_mode: str
    execution_mode: str
    worker_count: int
    reason: str = ""

    @property
    def uses_parallel(self) -> bool:
        """Return whether this decision will use worker processes."""
        return self.execution_mode == BATCH_EXECUTION_PARALLEL and self.worker_count > 1


@dataclass(frozen=True, slots=True)
class FormulaBatchTask:
    """Serializable formula task for one worksheet."""

    source_sheet: str
    target_column: str
    expression: str
    frame: pd.DataFrame
    worksheet_frames: Mapping[str, pd.DataFrame] | None = None


@dataclass(frozen=True, slots=True)
class FormulaBatchWorkerResult:
    """Serializable result returned by a formula worker process."""

    source_sheet: str
    target_column: str
    updated_rows: int = 0
    values: pd.Series | None = None
    status: str = "ok"
    error: str = ""
    elapsed_seconds: float = 0.0


def resolve_formula_batch_execution(
    requested_mode: str,
    task_count: int,
    total_cells: int,
    max_workers: int | None = None,
) -> BatchExecutionDecision:
    """Choose sequential or parallel execution for a formula batch."""
    clean_mode = requested_mode if requested_mode in BATCH_EXECUTION_MODES else BATCH_EXECUTION_AUTO
    worker_limit = _worker_limit(max_workers)
    worker_count = min(worker_limit, max(1, task_count))

    if clean_mode == BATCH_EXECUTION_SEQUENTIAL:
        return BatchExecutionDecision(
            requested_mode=clean_mode,
            execution_mode=BATCH_EXECUTION_SEQUENTIAL,
            worker_count=1,
            reason="Sequential mode was selected.",
        )

    if task_count < FORMULA_PARALLEL_MIN_TASKS:
        return BatchExecutionDecision(
            requested_mode=clean_mode,
            execution_mode=BATCH_EXECUTION_SEQUENTIAL,
            worker_count=1,
            reason="Parallel execution needs at least two non-visible target sheets.",
        )

    if clean_mode == BATCH_EXECUTION_AUTO and total_cells < FORMULA_PARALLEL_MIN_CELLS:
        return BatchExecutionDecision(
            requested_mode=clean_mode,
            execution_mode=BATCH_EXECUTION_SEQUENTIAL,
            worker_count=1,
            reason="Auto mode kept this small batch sequential to avoid process overhead.",
        )

    if worker_count < 2:
        return BatchExecutionDecision(
            requested_mode=clean_mode,
            execution_mode=BATCH_EXECUTION_SEQUENTIAL,
            worker_count=1,
            reason="Only one worker is available.",
        )

    return BatchExecutionDecision(
        requested_mode=clean_mode,
        execution_mode=BATCH_EXECUTION_PARALLEL,
        worker_count=worker_count,
        reason=f"Using {worker_count} worker processes.",
    )


def run_formula_batch_parallel(
    tasks: list[FormulaBatchTask],
    max_workers: int | None = None,
) -> list[FormulaBatchWorkerResult]:
    """Run formula tasks in worker processes and return result series."""
    if not tasks:
        return []

    worker_limit = min(_worker_limit(max_workers), len(tasks))
    with ProcessPoolExecutor(max_workers=worker_limit) as executor:
        return list(executor.map(_run_formula_batch_task, tasks))


def _run_formula_batch_task(task: FormulaBatchTask) -> FormulaBatchWorkerResult:
    """Apply one formula in a child process."""
    started = time.perf_counter()
    try:
        result = apply_column_expression(
            task.frame,
            target_column=task.target_column,
            expression=task.expression,
            row_positions=None,
            worksheet_frames=task.worksheet_frames,
        )
        return FormulaBatchWorkerResult(
            source_sheet=task.source_sheet,
            target_column=result.target_column,
            updated_rows=result.updated_rows,
            values=task.frame[result.target_column].copy(),
            status="ok",
            elapsed_seconds=time.perf_counter() - started,
        )
    except ExpressionError as exc:
        return FormulaBatchWorkerResult(
            source_sheet=task.source_sheet,
            target_column=task.target_column,
            status="failed",
            error=str(exc),
            elapsed_seconds=time.perf_counter() - started,
        )
    except Exception as exc:
        return FormulaBatchWorkerResult(
            source_sheet=task.source_sheet,
            target_column=task.target_column,
            status="failed",
            error=str(exc),
            elapsed_seconds=time.perf_counter() - started,
        )


def _worker_limit(max_workers: int | None = None) -> int:
    """Return a conservative process count for batch work."""
    cpu_count = os.cpu_count() or 1
    default_workers = max(1, cpu_count - 1)
    if max_workers is None or max_workers <= 0:
        return default_workers
    return max(1, min(int(max_workers), cpu_count))
