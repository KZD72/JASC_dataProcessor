"""Measure real background text import, GUI heartbeat, and cancellation.

Example: python -B benchmarks/background_import_audit.py --output result.json
Add --cancel-after-ms 50 to measure cancellation without publishing a dataset.
Temporary synthetic data is deleted; no preferences or user files are changed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from core.file_io import ImportOptions
from ui.main_window import MainWindow


class _OptionsDialog:
    Accepted = QDialog.Accepted

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def exec(self) -> int:
        return self.Accepted

    def options(self) -> ImportOptions:
        return ImportOptions()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--columns", type=int, default=10)
    parser.add_argument("--cancel-after-ms", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    ticks, phases, errors = [], [], []
    loop = QEventLoop()
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    window._jobs.progress.connect(lambda progress: phases.append(progress.message))
    cancel_requested = []

    def cancel() -> None:
        cancel_requested.append(time.perf_counter())
        window._cancel_text_import()

    def tick() -> None:
        ticks.append(time.perf_counter())
        if window._text_import_token is None:
            loop.quit()

    heartbeat.timeout.connect(tick)
    with tempfile.TemporaryDirectory(prefix="jasc-background-") as folder:
        source = Path(folder) / "large.csv"
        frame = pd.DataFrame({f"C{i}": np.arange(args.rows, dtype=float) * 0.01 + i for i in range(args.columns)})
        frame.to_csv(source, index=False)
        del frame
        with (
            patch("ui.main_window.QFileDialog.getOpenFileNames", return_value=([str(source)], "")),
            patch("ui.main_window.ImportOptionsDialog", _OptionsDialog),
            patch.object(window, "_confirm_large_file_import", return_value=True),
            patch.object(window, "_confirm_large_dataset", return_value=True),
            patch("ui.main_window.QMessageBox.critical", side_effect=lambda *items: errors.append(str(items[-1]))),
            patch("ui.main_window.QMessageBox.warning", side_effect=lambda *items: errors.append(str(items[-1]))),
        ):
            started = time.perf_counter()
            ticks.append(started)
            heartbeat.start()
            window._import_data_file()
            if args.cancel_after_ms:
                QTimer.singleShot(args.cancel_after_ms, cancel)
            loop.exec()
            finished = time.perf_counter()
            heartbeat.stop()
        intervals = np.diff(ticks)
        payload = {
            "rows": args.rows, "columns": args.columns,
            "csv_mib": source.stat().st_size / 2**20,
            "elapsed_s": finished - started,
            "heartbeat_ticks": len(ticks),
            "heartbeat_p95_gap_s": float(np.percentile(intervals, 95)),
            "heartbeat_max_gap_s": float(intervals.max()),
            "cancel_requested": bool(cancel_requested),
            "cancel_completion_s": finished - cancel_requested[0] if cancel_requested else None,
            "published_datasets": window._workspace.dataset_names(),
            "published_rows": sum(len(dataset.frame) for dataset in window._workspace.list_datasets()),
            "progress_messages": list(dict.fromkeys(phases)),
            "errors": errors,
            "qt_offscreen": True,
        }
    window.close()
    payload_text = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(payload_text + "\n", encoding="utf-8")
    print(payload_text)


if __name__ == "__main__":
    main()
