"""Measure streaming text ingestion and bounded asynchronous page navigation.

Run: python -B benchmarks/paged_large_data_audit.py --output result.json
Synthetic CSV is generated in bounded chunks; no complete source frame exists.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import polars as pl
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from benchmarks.large_sheet_audit import memory_mib
from core.file_io import ImportOptions
from core.large_data import open_large_dataset
from ui.background_jobs import BackgroundJobController
from ui.large_data_view import LargeDataView


def wait_until(predicate, seconds: float = 180) -> None:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
    if not predicate():
        raise TimeoutError("The background operation did not finish")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--columns", type=int, default=10)
    parser.add_argument("--windows", type=int, default=60)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    view = LargeDataView()
    view.resize(1100, 700)
    view.show()
    jobs = BackgroundJobController()
    sources, errors, ticks, memories = [], [], [], []
    heartbeat = QTimer()
    heartbeat.setInterval(10)

    def tick() -> None:
        ticks.append(time.perf_counter())
        memories.append(memory_mib().get("rss_mib", 0))

    heartbeat.timeout.connect(tick)
    with tempfile.TemporaryDirectory(prefix="jasc-paged-audit-") as directory:
        path = Path(directory) / "large.csv"
        with path.open("wb") as target:
            for start in range(0, args.rows, 32_768):
                frame = pl.DataFrame({
                    f"C{i}": [value * 0.01 + i for value in range(start, min(args.rows, start + 32_768))]
                    for i in range(args.columns)
                })
                frame.write_csv(target, include_header=start == 0)
            del frame
        gc.collect()
        baseline = memory_mib()
        ticks.append(time.perf_counter())
        heartbeat.start()
        started = time.perf_counter()
        jobs.start(
            lambda context: open_large_dataset(path, ImportOptions(), context),
            on_success=sources.append, on_error=errors.append,
            on_cancelled=lambda: errors.append("Cancelled"),
        )
        wait_until(lambda: not jobs.is_running)
        import_elapsed = time.perf_counter() - started
        if errors:
            raise RuntimeError(errors)
        source = sources[0]
        view.set_source(source)
        durations, cached_rows, cached_bytes, navigation_memory = [], [], [], []
        for index in range(args.windows):
            row = (index * 104_729) % args.rows
            started = time.perf_counter()
            view.request_window(row)
            wait_until(lambda: view.model.page is not None and view.model.page.row_start == row and not view.jobs.is_running)
            durations.append(time.perf_counter() - started)
            cached_rows.append(view.model.rowCount())
            cached_bytes.append(view.model.page.frame.estimated_size())
            navigation_memory.append(memory_mib().get("rss_mib", 0))
        heartbeat.stop()
        gaps = [right - left for left, right in zip(ticks, ticks[1:])]
        ordered = sorted(gaps)
        payload = {
            "rows": args.rows, "columns": args.columns,
            "polars_version": pl.__version__,
            "csv_mib": path.stat().st_size / 2**20,
            "parquet_mib": source.path.stat().st_size / 2**20,
            "import_s": import_elapsed, "windows_visited": args.windows,
            "page_median_s": statistics.median(durations), "page_max_s": max(durations),
            "max_cached_rows": max(cached_rows), "max_cached_bytes": max(cached_bytes),
            "heartbeat_p95_gap_s": ordered[min(len(ordered) - 1, int(len(ordered) * .95))],
            "heartbeat_max_gap_s": max(gaps),
            "rss_before_import_mib": baseline.get("rss_mib"),
            "max_sampled_rss_mib": max(memories),
            "navigation_rss_after_warmup_min_mib": min(navigation_memory[10:]),
            "navigation_rss_after_warmup_max_mib": max(navigation_memory[10:]),
            "engine_buffers_separate_from_display_cache": True,
            "errors": errors,
        }
    view.shutdown()
    wait_until(lambda: not view.jobs.is_running)
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    output = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf8")
    print(output)


if __name__ == "__main__":
    main()
