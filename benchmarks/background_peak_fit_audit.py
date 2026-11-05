"""Measure real Raman map fitting/correction, GUI heartbeat, memory, and cancellation.

Run: python -B benchmarks/background_peak_fit_audit.py --output result.json
Add --baseline-only for arPLS map correction; --cancel-after-ms 100 cancels.
Uses synthetic, seeded spectra;
no source files or application preferences are changed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import PySide6
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from benchmarks.large_sheet_audit import memory_mib
from math_engine.baseline import BaselineParameters, correct_baseline
from math_engine.composite_peak_fit import CompositeFitParameters, build_peak_component_spec
from math_engine.peak_detection import PeakDetectionParameters, detect_peaks
from ui.main_window import MainWindow


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pixels", type=int, default=400)
    parser.add_argument("--samples", type=int, default=601)
    parser.add_argument("--cancel-after-ms", type=int, default=0)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.pixels < 1 or args.samples < 20:
        parser.error("Use at least one pixel and twenty samples per spectrum")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    rng = np.random.default_rng(123)
    x = np.linspace(100.0, 400.0, args.samples)
    side = max(1, int(np.ceil(np.sqrt(args.pixels))))
    frame = pd.concat([pd.DataFrame({
        "X": pixel % side, "Y": pixel // side, "shift": x,
        "signal": 2.0 + 5.0 * np.exp(-0.5 * ((x - (245.0 + pixel % 4)) / 6.0) ** 2)
                  + rng.normal(0, 0.01, args.samples),
    }) for pixel in range(args.pixels)], ignore_index=True)
    source = window._workspace.add_dataset("Synthetic map", frame, copy_frame=False)
    baseline_settings = (BaselineParameters(method="arpls") if args.baseline_only
                         else BaselineParameters(method="constant", constant_value=2.0))
    detection_settings = PeakDetectionParameters(prominence=1.0)
    reference = correct_baseline(x, frame["signal"].iloc[:args.samples].to_numpy(), baseline_settings)
    peaks = detect_peaks(x, reference.raw, reference.corrected, detection_settings)
    component = build_peak_component_spec(peaks.peaks[0], "gaussian", x)
    dialog = SimpleNamespace(
        application_scope=lambda: "map", component_specs=lambda: [component],
        baseline_parameters=lambda: baseline_settings,
        detection_parameters=lambda: detection_settings,
        composite_parameters=lambda: CompositeFitParameters(), analysis_range=lambda: None,
        x_column=lambda: "shift", y_column=lambda: "signal", center_tolerance=lambda: 10.0,
        analysis_name=lambda: "Synthetic map fit", analysis_profile=lambda: {},
        create_signal_output=lambda: False, create_peak_output=lambda: False,
        create_fit_output=lambda: False,
        result_sheet_name=lambda: "Synthetic corrected map",
    )
    ticks: list[float] = []
    progress: list[tuple[float, int, int]] = []
    errors: list[str] = []
    cancelled: list[float] = []
    loop = QEventLoop()
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    window._jobs.progress.connect(lambda p: progress.append((time.perf_counter(), p.completed, p.total)))

    def tick() -> None:
        ticks.append(time.perf_counter())
        if not window._jobs.is_running and window._spectral_job_token is None:
            loop.quit()

    def cancel() -> None:
        if window._jobs.is_running:
            cancelled.append(time.perf_counter())
            window._cancel_spectral_job()

    heartbeat.timeout.connect(tick)
    before = memory_mib()
    with patch("ui.main_window.QMessageBox.critical", side_effect=lambda *items: errors.append(str(items[-1]))):
        started = time.perf_counter()
        ticks.append(started)
        heartbeat.start()
        if args.baseline_only:
            window._run_baseline_map(source, dialog, {})
        else:
            window._run_peak_analysis_batch_or_map(source, dialog, {})
        if args.cancel_after_ms:
            QTimer.singleShot(args.cancel_after_ms, cancel)
        loop.exec()
        finished = time.perf_counter()
        heartbeat.stop()
    intervals = np.diff(ticks)
    analyses = window._workspace.list_spectral_analyses()
    outputs = [dataset for dataset in window._workspace.list_datasets() if dataset is not source]
    failed_pixels = sum(int((analysis.metrics_frame["status"] == "failed").sum()) for analysis in analyses)
    if args.baseline_only:
        failed_pixels += sum(int(dataset.worksheet_metadata.import_details["Failed pixels"]) for dataset in outputs)
    if args.cancel_after_ms and not cancelled:
        errors.append("Run completed before cancellation delivery; increase --pixels")
    if cancelled and (analyses or outputs):
        errors.append("Cancelled run published output")
    payload = {
        "operation": "baseline_map" if args.baseline_only else "peak_fit_map",
        "baseline_method": baseline_settings.method,
        "pixels": args.pixels, "samples_per_pixel": args.samples, "seed": 123,
        "input_mib": float(frame.memory_usage(deep=True).sum() / 2**20),
        "elapsed_s": finished - started,
        "heartbeat_ticks": len(ticks),
        "heartbeat_p95_gap_s": float(np.percentile(intervals, 95)) if intervals.size else None,
        "heartbeat_max_gap_s": float(intervals.max()) if intervals.size else None,
        "cancel_requested": bool(cancelled),
        "cancel_completion_s": finished - cancelled[0] if cancelled else None,
        "progress_reports": len(progress),
        "last_completed": max((completed for _, completed, _ in progress), default=0),
        "published_analyses": [analysis.name for analysis in analyses],
        "published_metrics": sum(len(analysis.metrics_frame) for analysis in analyses),
        "failed_pixels": failed_pixels,
        "published_worksheets": [dataset.name for dataset in outputs],
        "published_rows": sum(len(dataset.frame) for dataset in outputs),
        "memory_before": before, "memory_after": memory_mib(),
        "environment": {"python": sys.version, "pandas": pd.__version__,
                        "numpy": np.__version__, "qt": PySide6.__version__},
        "errors": errors, "qt_offscreen": True,
    }
    window.close()
    payload_text = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(payload_text + "\n", encoding="utf-8")
    print(payload_text)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
