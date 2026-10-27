"""Responsiveness, cancellation, ownership, and atomic import regressions."""

from __future__ import annotations

from contextlib import ExitStack
from collections.abc import Callable
import gc
import os
from pathlib import Path
from threading import Event, get_ident
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from core.file_io import ImportOptions, read_tabular_file, resolve_text_encoding
from core.import_jobs import _worksheet_metadata
from core.jobs import JobCancelled, JobContext
from core.workspace import Workspace
from ui.background_jobs import BackgroundJobController
from ui.main_window import MainWindow


class BackgroundImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        gc.collect()

    def wait_until(self, predicate: Callable[[], bool], seconds: float = 10) -> None:
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(predicate(), "Background operation did not reach the expected state")

    def dispose(self, window: MainWindow) -> None:
        window._jobs.cancel()
        self.wait_until(lambda: not window._jobs.is_running)
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def import_patches(self, stack: ExitStack, paths: list[Path]) -> None:
        class OptionsDialog:
            Accepted = QDialog.Accepted

            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def exec(self) -> int:
                return self.Accepted

            def options(self) -> ImportOptions:
                return ImportOptions()

        stack.enter_context(patch("ui.main_window.QFileDialog.getOpenFileNames", return_value=([str(p) for p in paths], "")))
        stack.enter_context(patch("ui.main_window.ImportOptionsDialog", OptionsDialog))
        stack.enter_context(patch("ui.main_window.QMessageBox.critical"))
        stack.enter_context(patch("ui.main_window.QMessageBox.warning"))

    def test_controller_worker_heartbeat_and_gui_delivery(self) -> None:
        jobs = BackgroundJobController()
        release = Event()
        entered = Event()
        ticks, results, errors, worker_threads, callback_threads = [], [], [], [], []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))

        def operation(context: JobContext) -> int:
            worker_threads.append(get_ident())
            entered.set()
            while not release.wait(0.005):
                context.report(0, 0, "Working")
            return 42

        def receive(result: object) -> None:
            results.append(result)
            callback_threads.append(QThread.currentThread() == self.app.thread())

        try:
            timer.start()
            jobs.start(operation, on_success=receive, on_error=errors.append, on_cancelled=lambda: None)
            self.wait_until(lambda: entered.is_set() and len(ticks) >= 4)
            with self.assertRaises(RuntimeError):
                jobs.start(operation, on_success=receive, on_error=errors.append, on_cancelled=lambda: None)
            release.set()
            self.wait_until(lambda: not jobs.is_running)
            self.assertEqual(results, [42])
            self.assertEqual(callback_threads, [True])
            self.assertNotEqual(worker_threads, [get_ident()])
            self.assertEqual(errors, [])
        finally:
            release.set()
            jobs.cancel()
            self.wait_until(lambda: not jobs.is_running)
            timer.stop()

    def test_late_cancellation_discards_queued_success_and_controller_can_restart(self) -> None:
        jobs = BackgroundJobController()
        ready = Event()
        results, cancelled, errors = [], [], []

        def operation(context: JobContext) -> int:
            ready.set()
            return 42

        jobs.start(operation, on_success=results.append, on_error=errors.append, on_cancelled=lambda: cancelled.append(True))
        self.assertTrue(ready.wait(2))  # Deliberately do not dispatch queued Qt completion yet.
        jobs.cancel()
        self.wait_until(lambda: not jobs.is_running)
        self.assertEqual(results, [])
        self.assertEqual(cancelled, [True])
        jobs.start(lambda context: 7, on_success=results.append, on_error=errors.append, on_cancelled=lambda: None)
        self.wait_until(lambda: not jobs.is_running)
        self.assertEqual(results, [7])
        self.assertEqual(errors, [])

    def test_worker_error_is_reported_once_and_allows_next_job(self) -> None:
        jobs = BackgroundJobController()
        errors, results = [], []

        def fail(context: JobContext) -> None:
            raise ValueError("Unreadable input")

        with self.assertLogs("ui.background_jobs", level="ERROR"):
            jobs.start(fail, on_success=results.append, on_error=errors.append, on_cancelled=lambda: None)
            self.wait_until(lambda: not jobs.is_running)
        self.assertEqual(errors, ["Unreadable input"])
        jobs.start(lambda context: 1, on_success=results.append, on_error=errors.append, on_cancelled=lambda: None)
        self.wait_until(lambda: not jobs.is_running)
        self.assertEqual(results, [1])

    def test_cancel_after_first_file_prepared_keeps_workspace_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            paths = [Path(folder) / name for name in ("first.csv", "second.csv")]
            for path in paths:
                path.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
            self.import_patches(stack, paths)
            window = MainWindow()
            existing = window._workspace.add_dataset("existing", pd.DataFrame({"value": [9.0]}))
            second_started = Event()

            def reader(path: Path, options: ImportOptions, *, context: JobContext) -> pd.DataFrame:
                if path == paths[1]:
                    second_started.set()
                    while not context._cancellation.wait(0.005):
                        context.report(0, 0, "Reading second file")
                    context.check_cancelled()
                return read_tabular_file(path, options, context=context)

            stack.enter_context(patch("core.import_jobs.read_tabular_file", reader))
            try:
                window._import_data_file()
                self.wait_until(second_started.is_set)
                self.assertEqual(window._workspace.dataset_names(), ["existing"])
                window._cancel_text_import()
                self.wait_until(lambda: window._text_import_token is None)
                self.assertEqual(window._workspace.dataset_names(), ["existing"])
                self.assertEqual(existing.frame.value.tolist(), [9.0])
                self.assertFalse(window._jobs.is_running)
                self.assertTrue(window._import_action.isEnabled())
            finally:
                self.dispose(window)

    def test_workspace_replacement_discards_stale_import_results(self) -> None:
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            path = Path(folder) / "source.csv"
            path.write_text("x,y\n1,2\n", encoding="utf-8")
            self.import_patches(stack, [path])
            window = MainWindow()
            entered, release = Event(), Event()

            def reader(path: Path, options: ImportOptions, *, context: JobContext) -> pd.DataFrame:
                entered.set()
                release.wait(3)
                return read_tabular_file(path, options, context=context)

            stack.enter_context(patch("core.import_jobs.read_tabular_file", reader))
            try:
                window._import_data_file()
                self.wait_until(entered.is_set)
                replacement = Workspace()
                replacement.add_dataset("new_project", pd.DataFrame({"value": [5]}))
                window._workspace = replacement
                release.set()
                self.wait_until(lambda: window._text_import_token is None)
                self.assertEqual(replacement.dataset_names(), ["new_project"])
            finally:
                release.set()
                self.dispose(window)

    def test_metadata_failure_never_publishes_incomplete_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            paths = [Path(folder) / name for name in ("good.csv", "bad.csv")]
            for path in paths:
                path.write_text("x,y\n1,2\n", encoding="utf-8")
            self.import_patches(stack, paths)
            window = MainWindow()

            def metadata(path: Path, *args: object) -> object:
                if path == paths[1]:
                    raise OSError("Metadata could not be read")
                return _worksheet_metadata(path, *args)

            stack.enter_context(patch("core.import_jobs._worksheet_metadata", metadata))
            try:
                window._import_data_file()
                self.wait_until(lambda: window._text_import_token is None)
                self.assertEqual(window._workspace.dataset_names(), ["good"])
            finally:
                self.dispose(window)

    def test_commit_failure_rolls_back_all_new_sheets_on_gui_thread(self) -> None:
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            paths = [Path(folder) / name for name in ("first.csv", "second.csv")]
            for path in paths:
                path.write_text("x,y\n1,2\n", encoding="utf-8")
            self.import_patches(stack, paths)
            window = MainWindow()
            window._workspace.add_dataset("existing", pd.DataFrame({"value": [9]}))
            add = window._workspace.add_dataset
            calls = []

            def add_or_fail(*args: object, **kwargs: object) -> object:
                calls.append(QThread.currentThread() == self.app.thread())
                if len(calls) == 2:
                    raise ValueError("Commit could not finish")
                return add(*args, **kwargs)

            stack.enter_context(patch.object(window._workspace, "add_dataset", side_effect=add_or_fail))
            try:
                with self.assertLogs("ui.background_jobs", level="ERROR"):
                    window._import_data_file()
                    self.wait_until(lambda: window._text_import_token is None)
                self.assertEqual(window._workspace.dataset_names(), ["existing"])
                self.assertEqual(calls, [True, True])
            finally:
                self.dispose(window)

    def test_close_defers_destruction_until_worker_stops(self) -> None:
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            path = Path(folder) / "source.csv"
            path.write_text("x,y\n1,2\n", encoding="utf-8")
            self.import_patches(stack, [path])
            entered = Event()
            window = MainWindow()

            def reader(path: Path, options: ImportOptions, *, context: JobContext) -> pd.DataFrame:
                entered.set()
                while not context._cancellation.wait(0.005):
                    pass
                context.check_cancelled()

            stack.enter_context(patch("core.import_jobs.read_tabular_file", reader))
            try:
                window._import_data_file()
                self.wait_until(entered.is_set)
                self.assertFalse(window.close())
                self.assertTrue(window._closing_when_idle)
                self.wait_until(lambda: not window._jobs.is_running)
                self.assertEqual(window._workspace.dataset_names(), [])
                self.assertIsNone(window._text_import_token)
            finally:
                self.dispose(window)

    def test_parser_cancels_during_actual_byte_reads_and_releases_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.csv"
            path.write_text("x,y\n" + "1.25,2.5\n" * 150_000, encoding="utf-8")
            cancellation = Event()
            progress = []

            def report(update: object) -> None:
                progress.append(update)
                if update.total > 0:
                    cancellation.set()

            with self.assertRaises(JobCancelled):
                read_tabular_file(path, ImportOptions(), context=JobContext(cancellation, report))
            self.assertTrue(any(update.total > 0 for update in progress))
            path.unlink()  # Windows refuses this if a parser handle was leaked.

    def test_encoding_detection_reads_only_its_bounded_sample(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.csv"
            path.write_bytes(b"x,y\n1,2\n" * 20_000)
            with patch.object(Path, "read_bytes", side_effect=AssertionError("Unbounded file read")):
                self.assertEqual(resolve_text_encoding(path), "utf-8")

    def test_context_reader_preserves_vendor_encoding_locale_and_map_layout(self) -> None:
        cases = (
            ("cp1252", "$Operator=Jos\u00e9\nx;y\n1;2,5\n2;3,5\n", ImportOptions()),
            ("utf-16", "X\tY\t100,5\t200,5\n0\t0\t1,5\t2,5\n1\t0\t3,5\t4,5\n",
             ImportOptions(data_kind="spectral_map", spectrometer="horiba")),
        )
        with tempfile.TemporaryDirectory() as folder:
            for encoding, text, options in cases:
                with self.subTest(encoding=encoding):
                    path = Path(folder) / "instrument.txt"
                    path.write_text(text, encoding=encoding)
                    expected = read_tabular_file(path, options)
                    actual = read_tabular_file(path, options, context=JobContext(Event(), lambda update: None))
                    pd.testing.assert_frame_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
