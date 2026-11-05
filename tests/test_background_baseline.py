"""Baseline-map numerical equivalence, GUI delivery, cancellation, and races."""

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
from PySide6.QtWidgets import QApplication, QMessageBox

from core.baseline_jobs import BaselineMapRequest, prepare_baseline_map
from core.jobs import JobCancelled, JobContext
from core.spectral_jobs import SpectralSource
from core.workspace import Dataset, Workspace
from math_engine.baseline import BaselineParameters, correct_baseline
from math_engine.calculus import MathOperationError
from ui.main_window import MainWindow


def example_request() -> BaselineMapRequest:
    x = np.linspace(220.0, 100.0, 121)
    frame = pd.concat([pd.DataFrame({
        "X": coordinate, "Y": 0.0, "shift": x,
        "signal": 3.0 + 5.0 * np.exp(-0.5 * ((x - center) / 4.0) ** 2),
    }) for coordinate, center in ((0.0, 145.0), (1.0, 175.0))], ignore_index=True)
    return BaselineMapRequest(
        source=SpectralSource("Map", frame), x_column="shift", y_column="signal",
        parameters=BaselineParameters(method="constant", constant_value=3.0),
        analysis_range=None, output_name="Corrected map", detail={"Operator": "Example"},
    )


class ReviewedBaselineDialog:
    def __init__(self, request: BaselineMapRequest) -> None:
        self.request = request
        self.gui_thread = get_ident()

    def __getattribute__(self, name: str) -> object:
        if not name.startswith("_") and name not in {"request", "gui_thread"}:
            assert get_ident() == object.__getattribute__(self, "gui_thread")
        return object.__getattribute__(self, name)

    def x_column(self) -> str: return self.request.x_column
    def y_column(self) -> str: return self.request.y_column
    def baseline_parameters(self) -> BaselineParameters: return self.request.parameters
    def analysis_range(self) -> tuple[float, float] | None: return self.request.analysis_range
    def result_sheet_name(self) -> str: return self.request.output_name


class BaselineMapWorkerTests(unittest.TestCase):
    def test_descending_map_range_matches_single_spectrum_engine_and_preserves_source(self) -> None:
        request = replace(example_request(), analysis_range=(125.0, 200.0))
        original = request.source.frame.copy(deep=True)
        progress = []
        result = prepare_baseline_map(JobContext(Event(), progress.append), request)
        self.assertEqual((result.successes, result.failures), (2, 0))
        self.assertEqual(len(result.worksheet.frame), len(original))
        for coordinate, source in original.groupby("X", sort=False):
            x, raw = source["shift"].to_numpy(copy=True), source["signal"].to_numpy(copy=True)
            outside = (x < 125.0) | (x > 200.0)
            x[outside], raw[outside] = np.nan, np.nan
            expected = correct_baseline(x, raw, request.parameters)
            actual = result.worksheet.frame[result.worksheet.frame["X"] == coordinate]
            np.testing.assert_allclose(actual["signal_baseline"], expected.baseline)
            np.testing.assert_allclose(actual["signal_corrected"], expected.corrected)
            np.testing.assert_allclose(actual["shift"], expected.x)
        pd.testing.assert_frame_equal(request.source.frame, original)
        detail = result.worksheet.worksheet_metadata.import_details
        self.assertEqual((detail["Requested pixels"], detail["Successful pixels"], detail["Failed pixels"]),
                         ("2", "2", "0"))
        self.assertEqual(detail["Operator"], "Example")
        self.assertIn("baseline=constant", result.worksheet.metadata_for_column("signal_corrected").comment)
        self.assertEqual((progress[-1].completed, progress[-1].total), (2, 2))

    def test_failed_pixels_are_reported_without_losing_successful_pixels(self) -> None:
        request = example_request()
        # Repeated X inside one spectrum is invalid for baseline correction.
        request.source.frame.loc[121:, "shift"] = 100.0
        result = prepare_baseline_map(JobContext(Event(), lambda _p: None), request)
        self.assertEqual((result.successes, result.failures), (1, 1))
        self.assertEqual(set(result.worksheet.frame["X"]), {0.0})
        detail = result.worksheet.worksheet_metadata.import_details
        self.assertEqual(detail["Failed pixels"], "1")
        self.assertIn("X=1, Y=0", detail["Map errors"])

    def test_missing_text_and_empty_inputs_fail_without_publishing(self) -> None:
        request = example_request()
        text = request.source.frame.astype({"signal": object})
        text.loc[0, "signal"] = "invalid"
        for frame in (request.source.frame.drop(columns=["X"]),
                      request.source.frame.drop(columns=["signal"]), text,
                      request.source.frame.iloc[:0]):
            with self.subTest(columns=frame.columns.tolist(), rows=len(frame)):
                with self.assertRaises(MathOperationError):
                    prepare_baseline_map(JobContext(Event(), lambda _p: None), replace(
                        request, source=SpectralSource("Map", frame),
                    ))
        dataset = Dataset("Map", request.source.frame.copy())
        dataset.metadata_for_column("signal").value_type = "text"
        dataset.sync_column_metadata_attrs()
        with self.assertRaisesRegex(MathOperationError, "Text"):
            prepare_baseline_map(JobContext(Event(), lambda _p: None), replace(
                request, source=SpectralSource("Map", dataset.frame),
            ))

    def test_all_failed_pixels_raise_with_first_error(self) -> None:
        request = replace(example_request(), parameters=BaselineParameters(method="unknown"))
        with self.assertRaisesRegex(MathOperationError, "No map pixels.*First error.*Unknown baseline"):
            prepare_baseline_map(JobContext(Event(), lambda _p: None), request)

    def test_cancellation_is_not_recorded_as_a_failed_pixel(self) -> None:
        request = example_request()
        cancellation = Event()

        def cancel_after_first(*args: object, **kwargs: object) -> object:
            result = correct_baseline(*args, **kwargs)
            cancellation.set()
            return result

        with patch("core.baseline_jobs.correct_baseline", side_effect=cancel_after_first) as baseline:
            with self.assertRaises(JobCancelled):
                prepare_baseline_map(JobContext(cancellation, lambda _p: None), request)
            self.assertEqual(baseline.call_count, 1)
        with patch("core.baseline_jobs.map_spectrum_jobs") as grouping:
            with self.assertRaises(JobCancelled):
                prepare_baseline_map(JobContext(cancellation, lambda _p: None), request)
            grouping.assert_not_called()


class BackgroundBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        gc.collect()
        self.request = example_request()
        self.window = MainWindow()
        self.source = self.window._workspace.add_dataset("Map", self.request.source.frame)
        self.entered, self.release = Event(), Event()
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
        self.assertTrue(predicate(), "Background baseline correction did not reach the expected state")

    def start(self, request: BaselineMapRequest | None = None) -> None:
        self.window._run_baseline_map(self.source, ReviewedBaselineDialog(request or self.request),
                                      dict((request or self.request).detail))

    def blocked_baseline(self, *args: object, **kwargs: object) -> object:
        self.worker_threads.append(get_ident())
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError("Test did not release baseline correction")
        return correct_baseline(*args, **kwargs)

    def test_gui_heartbeat_progress_and_detached_worker_with_gui_publication(self) -> None:
        ticks, commits = [], []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        workspace = self.window._workspace
        add = workspace.add_dataset

        def publish(*args: object, **kwargs: object) -> object:
            commits.append(QThread.currentThread() == self.app.thread())
            return add(*args, **kwargs)

        try:
            timer.start()
            with patch("core.baseline_jobs.correct_baseline", side_effect=self.blocked_baseline), \
                    patch.object(workspace, "add_dataset", side_effect=publish):
                self.start()
                self.wait_until(lambda: self.entered.is_set() and len(ticks) >= 4
                                and "1/2" in self.window._spectral_job_progress._label.text())
                self.assertIn("1/2", self.window._spectral_job_progress._label.text())
                self.assertEqual(workspace.dataset_names(), ["Map"])
                token = self.window._spectral_job_token
                self.start()
                # Fitting and import cannot replace the correction worker.
                self.window._run_peak_analysis_batch_or_map(self.source, object(), {})
                with patch("ui.main_window.QFileDialog.getOpenFileNames") as files:
                    self.window._import_data_file()
                    files.assert_not_called()
                self.assertIs(self.window._spectral_job_token, token)
                self.release.set()
                self.wait_until(lambda: not self.window._jobs.is_running)
            self.assertTrue(all(thread != get_ident() for thread in self.worker_threads))
            self.assertEqual(commits, [True])
            self.assertEqual(workspace.dataset_names(), ["Map", "Corrected map"])
            self.assertEqual(workspace.spectral_analysis_names(), [])
            self.assertIsNone(self.window._spectral_job_progress)
            self.assertTrue(self.window._import_action.isEnabled())
            np.testing.assert_allclose(workspace.get_dataset("Corrected map").frame["signal_baseline"], 3.0)
            self.errors.assert_not_called()
        finally:
            timer.stop()

    def test_cancel_after_successful_pixel_discards_run_and_allows_restart(self) -> None:
        calls = []

        def block_second(*args: object, **kwargs: object) -> object:
            calls.append(True)
            if len(calls) == 2:
                self.entered.set()
                self.release.wait(5)
            return correct_baseline(*args, **kwargs)

        with patch("core.baseline_jobs.correct_baseline", side_effect=block_second):
            self.start()
            self.wait_until(self.entered.is_set)
            self.window._cancel_spectral_job()
            self.release.set()
            self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertEqual(self.window._workspace.dataset_names(), ["Map"])
        self.assertIn("cancelled", self.window.statusBar().currentMessage())
        self.assertIsNone(self.window._spectral_job_token)
        self.start()
        self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertEqual(self.window._workspace.dataset_names(), ["Map", "Corrected map"])

    def test_source_changes_including_non_visible_edits_discard_pending_result(self) -> None:
        for change in ("edit", "metadata", "replace", "delete", "rename", "workspace", "clear"):
            with self.subTest(change=change):
                self.release.clear()
                self.entered.clear()
                workspace = self.window._workspace = Workspace()
                self.source = workspace.add_dataset("Map", self.request.source.frame)
                with patch("core.baseline_jobs.correct_baseline", side_effect=self.blocked_baseline):
                    self.start()
                    self.wait_until(self.entered.is_set)
                    if change == "edit":
                        self.source.frame.loc[0, "signal"] = 99.0
                    elif change == "metadata":
                        self.source.metadata_for_column("signal").value_type = "text"
                    elif change == "replace":
                        workspace.remove_dataset("Map")
                        workspace.add_dataset("Map", self.request.source.frame)
                    elif change == "delete":
                        workspace.remove_dataset("Map")
                    elif change == "rename":
                        workspace.rename_dataset("Map", "Renamed")
                    elif change == "workspace":
                        self.window._workspace = Workspace()
                    else:
                        workspace.clear()
                    self.release.set()
                    self.wait_until(lambda: not self.window._jobs.is_running)
                self.assertNotIn("Corrected map", workspace.dataset_names())
                self.assertNotIn("Corrected map", self.window._workspace.dataset_names())
                self.assertIn("discarded", self.window.statusBar().currentMessage())
                self.errors.assert_not_called()

    def test_failed_publication_after_insertion_rolls_back_and_retains_existing_output(self) -> None:
        workspace = self.window._workspace
        existing = workspace.add_dataset("Corrected map", pd.DataFrame({"value": [42]}))
        add = workspace.add_dataset

        def fail_after_add(*args: object, **kwargs: object) -> None:
            add(*args, **kwargs)
            raise RuntimeError("Cannot publish worksheet")

        with patch.object(workspace, "add_dataset", side_effect=fail_after_add):
            with self.assertLogs("ui.background_jobs", level="ERROR"):
                self.start()
                self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertEqual(workspace.dataset_names(), ["Map", "Corrected map"])
        self.assertIs(workspace.get_dataset("Corrected map"), existing)
        self.assertIsNone(self.window._spectral_job_token)
        self.errors.assert_called_once()

    def test_worker_failure_cleans_up_progress_and_allows_retry(self) -> None:
        with self.assertLogs("ui.background_jobs", level="ERROR"):
            self.start(replace(self.request, parameters=BaselineParameters(method="unknown")))
            self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertEqual(self.window._workspace.dataset_names(), ["Map"])
        self.assertIsNone(self.window._spectral_job_progress)
        self.assertTrue(self.window._import_action.isEnabled())
        self.errors.assert_called_once()
        self.start()
        self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertIn("Corrected map", self.window._workspace.dataset_names())

    def test_queued_success_is_discarded_when_cancelled_before_gui_delivery(self) -> None:
        self.start()
        self.assertTrue(self.window._jobs._thread.wait(5000))
        self.window._cancel_spectral_job()
        self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertEqual(self.window._workspace.dataset_names(), ["Map"])

    def test_close_project_cancels_pending_correction(self) -> None:
        workspace = self.window._workspace
        with patch("core.baseline_jobs.correct_baseline", side_effect=self.blocked_baseline):
            self.start()
            self.wait_until(self.entered.is_set)
            with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.Yes):
                self.window._close_project()
            self.assertTrue(self.window._spectral_job_cancel_requested)
            self.release.set()
            self.wait_until(lambda: not self.window._jobs.is_running)
        self.assertIsNot(workspace, self.window._workspace)
        self.assertEqual(workspace.dataset_names(), ["Map"])
        self.assertEqual(self.window._workspace.dataset_names(), [])

    def test_window_close_waits_for_worker_and_publishes_nothing(self) -> None:
        self.window.show()
        with patch("core.baseline_jobs.correct_baseline", side_effect=self.blocked_baseline):
            self.start()
            self.wait_until(self.entered.is_set)
            self.window.close()
            self.assertTrue(self.window.isVisible())
            self.assertTrue(self.window._jobs.is_running)
            self.release.set()
            self.wait_until(lambda: not self.window.isVisible())
        self.assertFalse(self.window._jobs.is_running)
        self.assertEqual(self.window._workspace.dataset_names(), ["Map"])


if __name__ == "__main__":
    unittest.main()
