"""Detached fitting, responsive Qt delivery, cancellation, and atomic publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import gc
import os
from threading import Event, get_ident
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.jobs import JobCancelled, JobContext
from core.peak_fit_jobs import PeakFitRequest, PeakFitSource, prepare_peak_fit
from core.workspace import Workspace
from math_engine.baseline import BaselineParameters, correct_baseline
from math_engine.composite_peak_fit import (
    CompositeFitParameters, build_peak_component_spec, fit_composite_peaks,
)
from math_engine.peak_detection import PeakDetectionParameters, detect_peaks
from ui.main_window import MainWindow


def example_request() -> PeakFitRequest:
    x = np.linspace(100.0, 400.0, 301)
    frames = [pd.DataFrame({
        "X": coordinate, "Y": 0.0, "shift": x,
        "signal": 2.0 + 5.0 * np.exp(-0.5 * ((x - center) / 6.0) ** 2),
    }) for coordinate, center in ((0.0, 245.0), (1.0, 248.0))]
    baseline = correct_baseline(x, frames[0]["signal"].to_numpy(),
                                BaselineParameters(method="constant", constant_value=2.0))
    detection = detect_peaks(x, baseline.raw, baseline.corrected,
                             PeakDetectionParameters(prominence=1.0))
    component = build_peak_component_spec(detection.peaks[0], "gaussian", x)
    return PeakFitRequest(
        scope="map", source_dataset="Map",
        sources=(PeakFitSource("Map", pd.concat(frames, ignore_index=True)),),
        components=(component,), baseline=baseline.parameters, detection=detection.parameters,
        fit=CompositeFitParameters(), x_column="shift", y_column="signal",
        analysis_range=None, tolerance=10.0, analysis_name="Map fit", profile={}, detail={},
    )


class ReviewedDialog:
    """Settings-only stand-in; assertions ensure workers never read its methods."""

    def __init__(self, request: PeakFitRequest) -> None:
        self.request = request
        self.gui_thread = get_ident()

    def __getattribute__(self, name: str) -> object:
        if not name.startswith("_") and name not in {"request", "gui_thread"}:
            assert get_ident() == object.__getattribute__(self, "gui_thread")
        return object.__getattribute__(self, name)

    def application_scope(self) -> str: return self.request.scope
    def batch_dataset_names(self) -> list[str]: return [source.name for source in self.request.sources]
    def component_specs(self) -> tuple: return self.request.components
    def baseline_parameters(self) -> BaselineParameters: return self.request.baseline
    def detection_parameters(self) -> PeakDetectionParameters: return self.request.detection
    def composite_parameters(self) -> CompositeFitParameters: return self.request.fit
    def analysis_range(self) -> tuple[float, float] | None: return self.request.analysis_range
    def x_column(self) -> str: return self.request.x_column
    def y_column(self) -> str: return self.request.y_column
    def center_tolerance(self) -> float: return self.request.tolerance
    def analysis_name(self) -> str: return self.request.analysis_name
    def analysis_profile(self) -> dict[str, object]: return self.request.profile
    def create_signal_output(self) -> bool: return self.request.signal_name is not None
    def create_peak_output(self) -> bool: return self.request.peak_name is not None
    def create_fit_output(self) -> bool: return self.request.fit_name is not None
    def result_sheet_name(self) -> str: return self.request.signal_name
    def peak_sheet_name(self) -> str: return self.request.peak_name
    def fit_sheet_name(self) -> str: return self.request.fit_name
    def fit_parameter_sheet_name(self) -> str: return self.request.parameter_name


class PeakFitWorkerTests(unittest.TestCase):
    def test_batch_keeps_failed_spectra_in_qc_and_continues(self) -> None:
        request = example_request()
        good = request.sources[0].frame.iloc[:301].drop(columns=["X", "Y"])
        bad = pd.DataFrame({"shift": good["shift"], "signal": ["invalid"] * len(good)})
        request = replace(request, scope="batch", sources=(
            PeakFitSource("good", good), PeakFitSource("bad", bad),
            PeakFitSource("missing", pd.DataFrame({"shift": good["shift"]})),
        ))
        reports = []
        result = prepare_peak_fit(JobContext(Event(), reports.append), request)
        self.assertEqual((result.successes, result.failures), (1, 2))
        self.assertEqual(list(result.analysis.metrics_frame["status"]), ["success", "failed", "failed"])
        self.assertEqual(set(result.analysis.curves_frame["source_sheet"]), {"good"})
        self.assertEqual(result.worksheets, ())
        self.assertEqual((reports[-1].completed, reports[-1].total), (3, 3))
        self.assertIn("numeric", result.analysis.metrics_frame.iloc[1]["error"].lower())

    def test_cancellation_during_preprocessing_propagates_without_partial_results(self) -> None:
        request = example_request()
        cancellation = Event()

        def cancel_after_baseline(*args: object, **kwargs: object) -> object:
            baseline = correct_baseline(*args, **kwargs)
            cancellation.set()
            return baseline

        with patch("core.peak_fit_jobs.correct_baseline", side_effect=cancel_after_baseline):
            with self.assertRaises(JobCancelled):
                prepare_peak_fit(JobContext(cancellation, lambda _progress: None), request)

    def test_optimizer_cancellation_is_checked_during_residual_evaluation(self) -> None:
        request = example_request()
        frame = request.sources[0].frame.iloc[:301]
        calls = []

        def check_cancelled() -> None:
            calls.append(True)
            if len(calls) == 5:
                raise JobCancelled()

        with self.assertRaises(JobCancelled):
            fit_composite_peaks(
                frame["shift"].to_numpy(), frame["signal"].to_numpy(),
                frame["signal"].to_numpy() - 2.0, request.components,
                check_cancelled=check_cancelled,
            )
        self.assertEqual(len(calls), 5)

    def test_cancel_before_start_skips_grouping_and_fitting(self) -> None:
        cancellation = Event()
        cancellation.set()
        with patch("core.peak_fit_jobs.fit_composite_peaks") as fit:
            with self.assertRaises(JobCancelled):
                prepare_peak_fit(JobContext(cancellation, lambda _progress: None), example_request())
            fit.assert_not_called()

    def test_map_validation_errors_do_not_become_successful_empty_sessions(self) -> None:
        request = example_request()
        for frame in (request.sources[0].frame.drop(columns=["X"]), pd.DataFrame({"X": [], "Y": []})):
            with self.subTest(columns=frame.columns.tolist()):
                with self.assertRaisesRegex(ValueError, "normalized|No compatible"):
                    prepare_peak_fit(JobContext(Event(), lambda _progress: None), replace(
                        request, sources=(PeakFitSource("Map", frame),),
                    ))


class BackgroundPeakFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        gc.collect()
        self.request = example_request()
        self.window = MainWindow()
        self.source = self.window._workspace.add_dataset("Map", self.request.sources[0].frame)
        self.release = Event()
        self.entered = Event()
        self.worker_threads: list[int] = []
        self.errors = patch("ui.main_window.QMessageBox.critical").start()

    def tearDown(self) -> None:
        self.release.set()
        self.window._jobs.cancel()
        self.wait_until(lambda: not self.window._jobs.is_running)
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        patch.stopall()
        gc.collect()

    def wait_until(self, predicate: Callable[[], bool], seconds: float = 10.0) -> None:
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(predicate(), "Background fitting did not reach the expected state")

    def blocked_baseline(self, *args: object, **kwargs: object) -> object:
        self.worker_threads.append(get_ident())
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError("Test did not release preprocessing")
        return correct_baseline(*args, **kwargs)

    def start(self, request: PeakFitRequest | None = None) -> None:
        self.window._run_peak_analysis_batch_or_map(
            self.source, ReviewedDialog(request or self.request), {},
        )

    def test_worker_runs_with_gui_heartbeat_and_commits_on_gui_thread(self) -> None:
        ticks, commits = [], []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        workspace = self.window._workspace
        add_analysis = workspace.add_spectral_analysis

        def commit(analysis: object) -> object:
            commits.append(QThread.currentThread() == self.app.thread())
            return add_analysis(analysis)

        try:
            timer.start()
            with patch("core.peak_fit_jobs.correct_baseline", side_effect=self.blocked_baseline), \
                    patch.object(workspace, "add_spectral_analysis", side_effect=commit):
                self.start()
                token = self.window._peak_fit_token
                self.start()  # A second run cannot replace a live worker.
                self.assertIs(self.window._peak_fit_token, token)
                self.wait_until(lambda: self.entered.is_set() and len(ticks) >= 4)
                self.assertIn("1/2", self.window._peak_fit_progress._label.text())
                self.assertFalse(workspace.spectral_analysis_names())
                self.release.set()
                self.wait_until(lambda: not self.window._jobs.is_running)
            self.assertTrue(all(thread != get_ident() for thread in self.worker_threads))
            self.assertEqual(commits, [True])
            self.assertEqual(workspace.dataset_names(), ["Map"])
            metrics = workspace.get_spectral_analysis("Map fit").metrics_frame
            np.testing.assert_allclose(metrics["peak_1_position"], [245.0, 248.0], atol=0.1)
            self.assertIsNone(self.window._peak_fit_progress)
            self.assertTrue(self.window._import_action.isEnabled())
            self.errors.assert_not_called()
        finally:
            timer.stop()

    def test_cancel_after_first_pixel_discards_all_outputs_and_allows_retry(self) -> None:
        calls = []

        def block_second(*args: object, **kwargs: object) -> object:
            calls.append(True)
            if len(calls) == 2:
                self.entered.set()
                self.release.wait(5)
            return fit_composite_peaks(*args, **kwargs)

        with patch("core.peak_fit_jobs.fit_composite_peaks", side_effect=block_second):
            self.start(replace(self.request, fit_name="curves", parameter_name="parameters"))
            self.wait_until(self.entered.is_set)
            self.window._cancel_peak_fit()
            self.release.set()
            self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertEqual(self.window._workspace.dataset_names(), ["Map"])
        self.assertEqual(self.window._workspace.spectral_analysis_names(), [])
        self.assertIn("cancelled", self.window.statusBar().currentMessage())
        self.assertIsNone(self.window._peak_fit_token)
        self.start()
        self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertEqual(self.window._workspace.spectral_analysis_names(), ["Map fit"])

    def test_source_or_workspace_changes_discard_results(self) -> None:
        # Includes non-visible in-place edits, replacement, deletion and rename;
        # no reliance on the table model emitting a change notification.
        for change in ("edit", "replace", "delete", "rename", "metadata", "workspace", "clear"):
            with self.subTest(change=change):
                self.release.clear()
                self.entered.clear()
                self.window._workspace = Workspace()
                self.source = self.window._workspace.add_dataset("Map", self.request.sources[0].frame)
                workspace = self.window._workspace
                with patch("core.peak_fit_jobs.correct_baseline", side_effect=self.blocked_baseline):
                    self.start()
                    self.wait_until(self.entered.is_set)
                    if change == "edit":
                        self.source.frame.loc[0, "signal"] = 123.0
                    elif change == "replace":
                        workspace.remove_dataset("Map")
                        workspace.add_dataset("Map", self.request.sources[0].frame)
                    elif change == "delete":
                        workspace.remove_dataset("Map")
                    elif change == "rename":
                        workspace.rename_dataset("Map", "Renamed")
                    elif change == "metadata":
                        self.source.metadata_for_column("signal").value_type = "text"
                        self.source.sync_column_metadata_attrs()
                    elif change == "workspace":
                        self.window._workspace = Workspace()
                    else:
                        workspace.clear()
                    self.release.set()
                    self.wait_until(lambda: not self.window._jobs.is_running)
                self.assertEqual(workspace.spectral_analysis_names(), [])
                self.assertEqual(self.window._workspace.spectral_analysis_names(), [])
                self.assertIn("discarded", self.window.statusBar().currentMessage())
                self.errors.assert_not_called()

    def test_failed_publication_rolls_back_worksheets_and_analysis(self) -> None:
        request = replace(self.request, signal_name="signal", peak_name="peaks",
                          fit_name="fit", parameter_name="parameters")
        workspace = self.window._workspace
        add_analysis = workspace.add_spectral_analysis

        def fail_after_insertion(analysis: object) -> None:
            add_analysis(analysis)
            raise RuntimeError("Cannot publish analysis")

        with patch.object(workspace, "add_spectral_analysis", side_effect=fail_after_insertion):
            with self.assertLogs("ui.background_jobs", level="ERROR"):
                self.start(request)
                self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertEqual(workspace.dataset_names(), ["Map"])
        self.assertEqual(workspace.spectral_analysis_names(), [])
        self.assertIsNone(self.window._peak_fit_token)
        self.assertTrue(self.window._import_action.isEnabled())
        self.errors.assert_called_once()

    def test_cancel_queued_success_before_gui_delivery(self) -> None:
        self.start(replace(self.request, fit_name="fit", parameter_name="parameters"))
        # Join without pumping the GUI: the successful result is queued but has
        # not reached the GUI callback when the user cancellation arrives.
        self.assertTrue(self.window._jobs._thread.wait(5000))
        self.window._cancel_peak_fit()
        self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertEqual(self.window._workspace.dataset_names(), ["Map"])
        self.assertEqual(self.window._workspace.spectral_analysis_names(), [])

    def test_close_waits_for_running_worker_and_discards_results(self) -> None:
        self.window.show()
        with patch("core.peak_fit_jobs.correct_baseline", side_effect=self.blocked_baseline):
            self.start()
            self.wait_until(self.entered.is_set)
            self.window.close()
            self.assertTrue(self.window.isVisible())
            self.assertTrue(self.window._jobs.is_running)
            self.release.set()
            self.wait_until(lambda: not self.window.isVisible())
        self.assertFalse(self.window._jobs.is_running)
        self.assertEqual(self.window._workspace.spectral_analysis_names(), [])


if __name__ == "__main__":
    unittest.main()
