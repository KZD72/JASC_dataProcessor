"""Measure actual asynchronous dialog previews, GUI heartbeat, and cancellation.

Run: python -B benchmarks/spectral_preview_audit.py --kind fit --output result.json
Use --kind baseline/peaks, --cancel-after-ms 100, or --changes 10 as needed.
Synthetic data is seeded; no application settings or source files are changed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import PySide6
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from benchmarks.large_sheet_audit import memory_mib
from core.jobs import JobContext
from core.spectral_preview import SpectralPreviewRequest, SpectralPreviewResult, prepare_spectral_preview
from ui.peak_analysis_dialog import PeakAnalysisDialog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("baseline", "peaks", "fit"), default="fit")
    parser.add_argument("--samples", type=int, default=100_000)
    parser.add_argument("--cancel-after-ms", type=int, default=0)
    parser.add_argument("--changes", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.samples < 100 or args.changes < 0:
        parser.error("Use at least 100 samples and a nonnegative change count")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    rng = np.random.default_rng(123)
    x = np.linspace(100.0, 400.0, args.samples)
    frame = pd.DataFrame({"shift": x, "signal": 2.0 + 5.0 * np.exp(-0.5 * ((x - 245.0) / 6.0) ** 2)
                          + rng.normal(0, 0.01, args.samples)})
    dialog = PeakAnalysisDialog(frame, "Synthetic spectrum", default_x_column="shift",
                                 default_y_column="signal", baseline_only=args.kind == "baseline")
    dialog._prominence.setText("1")
    if args.kind != "baseline":
        # At this dense sampling, the default arPLS smoothness can follow the
        # broad synthetic Gaussian. Use the known background for detector/fit
        # measurements, and measure native arPLS separately with --kind baseline.
        dialog._baseline_method.setCurrentIndex(dialog._baseline_method.findData("constant"))
        dialog._constant_value.setText("2")
    dialog._preview_timer.stop()
    ticks, cancellations, requests, errors = [], [], [], []
    loop = QEventLoop()
    heartbeat, changes = QTimer(), QTimer()
    heartbeat.setInterval(10)
    changes.setInterval(10)
    change_count = 0

    def observe(context: JobContext, request: SpectralPreviewRequest) -> SpectralPreviewResult:
        requests.append({"kind": request.kind, "smoothness": request.baseline_parameters.smoothness})
        return prepare_spectral_preview(context, request)

    def tick() -> None:
        ticks.append(time.perf_counter())
        if time.perf_counter() - started > 120 and not cancellations:
            errors.append("Preview exceeded the benchmark timeout")
            cancel()
        if not dialog.preview_busy and not changes.isActive():
            loop.quit()

    def cancel() -> None:
        if dialog.preview_busy:
            cancellations.append(time.perf_counter())
            changes.stop()
            dialog._cancel_preview()

    def change() -> None:
        nonlocal change_count
        change_count += 1
        dialog._smoothness.setValue(100_000 + change_count * 10_000)
        if change_count == args.changes:
            changes.stop()

    heartbeat.timeout.connect(tick)
    changes.timeout.connect(change)
    before = memory_mib()
    with patch("ui.peak_analysis_dialog.prepare_spectral_preview", side_effect=observe), \
            patch("ui.peak_analysis_dialog.QMessageBox.warning", side_effect=lambda *items: errors.append(str(items[-1]))):
        started = time.perf_counter()
        ticks.append(started)
        heartbeat.start()
        {"baseline": dialog.preview_baseline, "peaks": dialog.preview_peaks, "fit": dialog.preview_composite_fit}[args.kind]()
        if args.changes:
            changes.start()
        if args.cancel_after_ms:
            QTimer.singleShot(args.cancel_after_ms, cancel)
        loop.exec()
        # Include explicit final painting, not just artist construction.
        dialog._canvas.draw()
        finished = time.perf_counter()
        ticks.append(finished)
        heartbeat.stop()
    intervals = np.diff(ticks)
    if args.cancel_after_ms and not cancellations:
        errors.append("Run finished before cancellation; increase --samples")
    baseline, peaks, fit = dialog._baseline_result, dialog.peak_result(), dialog.composite_result()
    if not cancellations and baseline is None:
        errors.append(dialog._status_label.text())
    if not cancellations and not args.changes and args.kind == "fit" and fit is None:
        errors.append("Composite preview did not produce a fit")
    payload = {
        "kind": args.kind, "samples": args.samples, "seed": 123,
        "elapsed_s": finished - started, "heartbeat_ticks": len(ticks),
        "heartbeat_p95_gap_s": float(np.percentile(intervals, 95)),
        "heartbeat_max_gap_s": float(intervals.max()),
        "cancel_requested": bool(cancellations),
        "cancel_completion_s": finished - cancellations[0] if cancellations else None,
        "setting_changes": change_count, "worker_requests": requests,
        "baseline_rows": len(baseline.x) if baseline is not None else 0,
        "peak_count": len(peaks.peaks) if peaks is not None else 0,
        "fit_rows": len(fit.fit_frame) if fit is not None else 0,
        "maximum_drawn_points": max((len(line.get_xdata()) for axis in dialog._figure.axes for line in axis.lines), default=0),
        "memory_before": before, "memory_after": memory_mib(),
        "environment": {"python": sys.version, "pandas": pd.__version__,
                        "numpy": np.__version__, "qt": PySide6.__version__},
        "qt_offscreen": True, "errors": errors,
    }
    dialog.reject()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    payload_text = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(payload_text + "\n", encoding="utf-8")
    print(payload_text)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
