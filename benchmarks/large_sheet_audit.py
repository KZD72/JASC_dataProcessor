"""Diagnostic large-sheet benchmarks; no app settings or source data are changed.

Run with the project interpreter: python -B benchmarks/large_sheet_audit.py
Each case runs in a fresh process. Results are printed as JSON; use --output
to retain the measurements. Temporary CSV/project files are removed on exit.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Callable, Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def memory_mib() -> dict[str, float]:
    """Report Windows working set including native allocations, when available."""
    if sys.platform != "win32":
        return {}
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "peak", "working", "paged_peak", "paged", "nonpaged_peak",
                "nonpaged", "pagefile", "pagefile_peak", "private",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        return {}
    return {"rss_mib": counters.working / 2**20, "peak_rss_mib": counters.peak / 2**20}


def timed(function: Callable[[], Any], repeats: int = 3) -> dict[str, Any]:
    """Measure wall time without allocation tracing or profiler overhead."""
    samples = []
    for _ in range(repeats):
        gc.collect()
        started = time.perf_counter()
        result = function()
        samples.append(time.perf_counter() - started)
        del result
    return {"median_s": statistics.median(samples), "samples_s": samples, **memory_mib()}


def run_case(case: str, rows: int, columns: int) -> dict[str, Any]:
    """Exercise actual app paths and small control operations on synthetic data."""
    import numpy as np
    import pandas as pd
    import PySide6
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from core.workspace import Workspace
    from ui.plot_canvas import PlotCanvas, PlotSeries

    app = QApplication.instance() or QApplication([])
    workspace = Workspace()
    frame = pd.DataFrame({f"C{i}": np.arange(rows, dtype=float) * 0.01 + i for i in range(columns)})
    source = workspace.add_dataset("benchmark", frame, copy_frame=False)
    del frame
    report: dict[str, Any] = {
        "case": case, "rows": rows, "columns": columns,
        "data_mib": float(source.frame.memory_usage(deep=True).sum() / 2**20),
        "environment": {"python": sys.version, "pandas": pd.__version__,
                        "numpy": np.__version__, "qt": PySide6.__version__},
    }
    if case == "table":
        from ui.main_window import MainWindow

        window = MainWindow()
        window._workspace.add_dataset("benchmark", source.frame, copy_frame=False)
        report["editor_attach"] = timed(lambda: window._refresh_dataset_list("benchmark"))
        model = window._dataset_model
        report["snapshot"] = timed(model._snapshot_if_within_budget, 1)
        cell = model.index(0, 0)
        edit_value = [0]

        def edit() -> bool:
            edit_value[0] -= 1
            return model.setData(cell, float(edit_value[0]), Qt.EditRole)

        report["single_cell_edit"] = timed(edit)
        report["undo_entries"] = len(model._undo_stack)
        report["undo_buffer_mib"] = model._history_memory_bytes(model._undo_stack) / 2**20
        report["undo"] = timed(model.undo, 1)
        window.deleteLater()
    elif case == "plot":
        canvas = PlotCanvas()
        series = PlotSeries(source.name, "C0", source.name, "C1")
        report["prepare_xy"] = timed(lambda: canvas._series_values(workspace, series, "linear", "linear"))
        report["raw_numpy_xy"] = timed(lambda: np.column_stack((source.frame.C0, source.frame.C1)))
        report["render_line"] = timed(lambda: canvas.plot_series(workspace, [series]), 1)
        report["paint_line"] = timed(canvas.canvas.draw, 1)
        report["rendered_points"] = len(canvas.axes.lines[0].get_xdata())
        canvas.deleteLater()
    elif case == "formula":
        from core.operations import evaluate_expression
        from math_engine.calculus import validate_numeric_column_metadata

        values = source.frame.C0
        report["numeric_validation"] = timed(lambda: validate_numeric_column_metadata(source.frame, "C0", values))
        report["formula_sin"] = timed(lambda: evaluate_expression(source.frame, "sin(col1)"))
        report["numpy_sin"] = timed(lambda: np.sin(values.to_numpy()))
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(10)
        ticks: list[float] = []
        done = [False]

        def tick() -> None:
            ticks.append(time.perf_counter())
            if done[0]:
                loop.quit()

        def formula() -> None:
            evaluate_expression(source.frame, "sin(col1)")
            done[0] = True

        timer.timeout.connect(tick)
        timer.start()
        QTimer.singleShot(40, formula)
        loop.exec()
        timer.stop()
        report["gui_max_timer_gap_s"] = max(np.diff(ticks), default=0.0)
    elif case == "import":
        from core.file_io import ImportOptions, read_tabular_file
        from core import project_io

        with tempfile.TemporaryDirectory(prefix="jasc-perf-") as folder:
            csv = Path(folder) / "numeric.csv"
            source.frame.to_csv(csv, index=False)
            report["csv_mib"] = csv.stat().st_size / 2**20
            report["pandas_typed_csv"] = timed(lambda: pd.read_csv(csv))
            report["jasc_auto_csv"] = timed(lambda: read_tabular_file(csv, ImportOptions()), 1)
            report["jasc_explicit_csv"] = timed(lambda: read_tabular_file(csv, ImportOptions(
                delimiter=",", has_header=True, encoding="utf-8", skip_rows=0, number_format="dot_decimal",
            )), 1)
            project = Path(folder) / "benchmark.jasc"
            report["project_save"] = timed(lambda: project_io.save_project(workspace, project), 1)
            report["project_load"] = timed(lambda: project_io.load_project(project), 1)
            report["project_mib"] = project.stat().st_size / 2**20
    elif case == "spectral":
        from core.spectral_analysis import SpectralAnalysisSession
        from ui.spectral_analysis_viewer import SpectralAnalysisViewer

        samples = 1000
        pixels = rows // samples
        ids = np.repeat(np.arange(pixels), samples)
        spectral = pd.DataFrame({
            "X": (ids % 32).astype(float), "Y": (ids // 32).astype(float),
            "shift": np.tile(np.arange(samples, dtype=float), pixels),
            "intensity": np.sin(np.tile(np.arange(samples, dtype=float), pixels) * 0.01),
        })
        cube_source = workspace.add_dataset("spectral", spectral, copy_frame=False)
        series = PlotSeries(cube_source.name, "X", cube_source.name, "Y",
                            z_dataset=cube_source.name, z_column="intensity",
                            plot_type="spectra_heatmap", spectral_column="shift", spectral_center=500.0)
        canvas = PlotCanvas()
        report["spectral_slice"] = timed(lambda: canvas._surface_values(workspace, series, "linear", "linear"))
        curves = spectral.rename(columns={"shift": "x", "intensity": "raw"})
        metrics = curves[["X", "Y"]].drop_duplicates().reset_index(drop=True)
        metrics["fit_success"] = 1.0
        viewer = SpectralAnalysisViewer()
        viewer.set_analysis(SpectralAnalysisSession(
            name="benchmark", source_dataset="spectral", analysis_kind="raman_map",
            x_column="shift", y_column="intensity", coordinate_columns=("X", "Y"),
            curves_frame=curves, metrics_frame=metrics,
        ))
        report["selected_spectrum_scan"] = timed(viewer._selected_curve_frame)
        report["viewer_redraw"] = timed(viewer._redraw)
        canvas.deleteLater()
        viewer.deleteLater()
    app.processEvents()
    report["final_memory"] = memory_mib()
    return report


def main() -> None:
    """Run isolated diagnostics and optionally retain machine-readable results."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("all", "table", "plot", "formula", "import", "spectral"), default="all")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--columns", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.case != "all":
        payload = json.dumps(run_case(args.case, args.rows, args.columns))
        if args.output:
            args.output.write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return
    cases = [(case, rows, 10) for rows in (100_000, 1_000_000) for case in ("table", "plot", "formula")]
    cases += [("table", 4_000_000, 10), ("import", 100_000, 10),
              ("import", 1_000_000, 2), ("spectral", 1_000_000, 4)]
    results = []
    for case, rows, columns in cases:
        print(f"Running {case}: {rows:,} x {columns}...", file=sys.stderr, flush=True)
        completed = subprocess.run([
            sys.executable, "-B", str(Path(__file__).resolve()), "--case", case,
            "--rows", str(rows), "--columns", str(columns),
        ], cwd=ROOT, capture_output=True, text=True, check=True)
        results.append(json.loads(completed.stdout.strip()))
    payload = json.dumps(results, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
