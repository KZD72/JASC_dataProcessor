"""Disk-backed source, bounded cache, worker races, and project regressions."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path
from threading import Event
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import polars as pl
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.file_io import ImportOptions
from core.jobs import JobCancelled, JobContext
from core.large_data import DISPLAY_BYTES, LargeDataset, open_large_dataset
from core.project_io import create_signing_identity, load_project, save_project, verify_project_integrity
from core.workspace import Workspace
from ui.large_data_view import LargeDataView
from ui.main_window import MainWindow


def context(event: Event | None = None) -> JobContext:
    return JobContext(event or Event(), lambda progress: None)


class LargeDataBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def parquet(self, rows: int = 2507, columns: int = 3) -> Path:
        path = self.root / "source.parquet"
        pl.DataFrame({f"c{i}": range(rows) for i in range(columns)}).write_parquet(path, row_group_size=511)
        return path

    def test_far_pages_column_projection_and_snapshot_independence(self) -> None:
        original = self.parquet(10_007, 40)
        source = open_large_dataset(original, ImportOptions(), context())
        original.unlink()
        self.assertEqual(source.row_count, 10_007)
        self.assertEqual(source.read_page(9000).frame.shape, (1000, 32))
        page = source.read_page(10_000, 32)
        self.assertEqual(page.frame.shape, (7, 8))
        self.assertEqual(page.frame.item(0, 0), 10_000)
        self.assertEqual(page.frame.columns[0], "c32")
        self.assertLessEqual(page.frame.estimated_size(), DISPLAY_BYTES)
        self.assertEqual(source.read_page(10_007).frame.height, 0)
        with self.assertRaises(ValueError):
            source.read_page(-1)
        with self.assertRaises(ValueError):
            source.read_page(0, 40)

    def test_text_stream_preserves_late_tokens_locale_ids_and_preamble(self) -> None:
        path = self.root / "locale.csv"
        path.write_text('# instrument: caf\xe9\nx;identifier;label\n' + '1,25;001;"first\nsecond"\n' * 1300 + 'bad;True;NA\n', encoding="cp1252", newline="")
        with patch("core.large_data.pd.read_csv", side_effect=AssertionError("No full Pandas import")):
            source = open_large_dataset(path, ImportOptions(), context())
        self.assertEqual(source.row_count, 1301)
        self.assertEqual(source.columns, ("x", "identifier", "label"))
        self.assertEqual(source.read_page(0).frame.row(0), ("1,25", "001", "first\nsecond"))
        self.assertEqual(source.read_page(1300).frame.row(0), ("bad", "True", "NA"))
        self.assertEqual(source.details["encoding"], "cp1252")
        self.assertIn("caf\xe9", "".join(source.details["preamble"]))

    def test_empty_typed_table_and_memory_limited_page(self) -> None:
        empty_path = self.root / "empty.parquet"
        pl.DataFrame(schema={"x": pl.Float64}).write_parquet(empty_path)
        source = open_large_dataset(empty_path, ImportOptions(), context())
        self.assertEqual(source.read_page(0).frame.shape, (0, 1))
        path = self.root / "strings.parquet"
        pl.DataFrame({"text": ["a" * 1000] * 1500}).write_parquet(path)
        source = open_large_dataset(path, ImportOptions(), context())
        page = source.read_page(0, max_bytes=4000)
        self.assertLessEqual(page.frame.estimated_size(), 4000)
        self.assertGreater(page.frame.height, 0)
        with self.assertRaisesRegex(ValueError, "One row"):
            source.read_page(0, max_bytes=500)

    def test_utf16_header_override_and_header_only_text(self) -> None:
        path = self.root / "utf16.txt"
        path.write_text("# instrument\nx;y\n1,25;2,50\n3,75;4,00\n", encoding="utf-16")
        source = open_large_dataset(path, ImportOptions(), context())
        self.assertEqual(source.row_count, 2)
        self.assertEqual(source.read_page(0).frame.row(1), ("3,75", "4,00"))
        header_only = self.root / "header.csv"
        header_only.write_text("x,y\n", encoding="utf8")
        source = open_large_dataset(header_only, ImportOptions(has_header=True), context())
        self.assertEqual(source.columns, ("x", "y"))
        self.assertEqual(source.row_count, 0)

    def test_cancel_before_and_after_native_write_cleans_private_storage(self) -> None:
        path = self.root / "source.csv"
        path.write_text("x,y\n1,2\n3,4\n", encoding="utf8")
        cancellation = Event()
        cancellation.set()
        with self.assertRaises(JobCancelled):
            open_large_dataset(path, ImportOptions(), context(cancellation))
        cancellation.clear()
        original = pl.LazyFrame.sink_parquet
        output_paths = []

        def cancelled_sink(frame, target, **kwargs):
            output_paths.append(Path(target))
            result = original(frame, target, **kwargs)
            cancellation.set()
            return result

        with patch.object(pl.LazyFrame, "sink_parquet", cancelled_sink):
            with self.assertRaises(JobCancelled):
                open_large_dataset(path, ImportOptions(), context(cancellation))
        self.assertEqual(len(output_paths), 1)
        self.assertFalse(output_paths[0].parent.exists())

    def test_vendor_layout_rejected_without_partial_normalization(self) -> None:
        path = self.root / "map.txt"
        path.write_text("\t\t100\t200\n0\t0\t1\t2\n0\t1\t3\t4\n")
        with self.assertRaisesRegex(ValueError, "vendor-specific"):
            open_large_dataset(path, ImportOptions(data_kind="spectral_map"), context())

    def test_full_source_queries_are_independent_of_display_and_extraction_is_bounded(self) -> None:
        source = open_large_dataset(self.parquet(2507), ImportOptions(), context())
        page = source.read_page(2000)
        self.assertEqual(source.scan().select(pl.len()).collect().item(), 2507)
        self.assertEqual(source.scan().filter(pl.col("c0") >= 2500).select(pl.len()).collect().item(), 7)
        frame = source.materialize_page(page)
        self.assertEqual(frame.shape, (507, 3))
        frame.iloc[0, 0] = -1
        self.assertEqual(source.read_page(2000).frame.item(0, 0), 2000)

    def test_project_round_trip_embeds_parquet_streams_and_retains_seal(self) -> None:
        workspace = Workspace()
        source = workspace.add_large_dataset(open_large_dataset(self.parquet(), ImportOptions(), context()))
        workspace.add_dataset("small", pd.DataFrame({"x": [1, 2]}))
        path = self.root / "project.jasc"
        with patch.object(pl.LazyFrame, "collect", side_effect=AssertionError("Save must not materialize")):
            save_project(workspace, path)
        self.assertTrue(verify_project_integrity(path).verified)
        source.path.unlink()
        with zipfile.ZipFile(path) as archive:
            metadata = json.loads(archive.read("project.json"))
            self.assertEqual(metadata["version"], 9)
            self.assertIn("large_datasets/0000.parquet", archive.namelist())
        with patch("core.large_data.pd.read_csv", wraps=pd.read_csv) as reader:
            loaded = load_project(path)
        self.assertEqual(reader.call_count, 1)  # Only the ordinary sheet.
        self.assertEqual(loaded.dataset_names(), ["small"])
        self.assertEqual(loaded.large_dataset_names(), [source.name])
        restored = loaded.get_large_dataset(source.name)
        self.assertEqual(restored.row_count, 2507)
        self.assertEqual(restored.read_page(2500).frame.item(0, 0), 2500)
        self.assertNotEqual(restored.path, source.path)

    def test_signed_encrypted_large_project_round_trip(self) -> None:
        workspace = Workspace()
        source = workspace.add_large_dataset(open_large_dataset(self.parquet(), ImportOptions(), context()))
        identity, _ = create_signing_identity(self.root / "author.jasc-key", name="Test Author", password="test key password")
        path = self.root / "large.jascx"
        save_project(workspace, path, password="test encryption password", signing_identity=identity)
        loaded = load_project(path, password="test encryption password")
        self.assertEqual(loaded.project_signature_status, "valid")
        self.assertEqual(loaded.project_signer_fingerprint, identity.fingerprint)
        self.assertEqual(loaded.get_large_dataset(source.name).read_page(2500).frame.height, 7)


class LargeDataViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        gc.collect()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def wait_until(self, predicate, seconds: float = 10) -> None:
        end = time.monotonic() + seconds
        while not predicate() and time.monotonic() < end:
            QTest.qWait(5)
        self.assertTrue(predicate(), "Timed out waiting for a page")

    def source(self, name: str = "source", rows: int = 2507) -> LargeDataset:
        path = self.root / f"{name}.parquet"
        pl.DataFrame({"x": range(rows), "y": range(rows)}).write_parquet(path)
        return open_large_dataset(path, ImportOptions(), context())

    def dispose(self, view: LargeDataView) -> None:
        view.shutdown()
        self.wait_until(lambda: not view.jobs.is_running)
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def loaded(self, view: LargeDataView, row: int) -> bool:
        return view.model.page is not None and view.model.page.row_start == row and not view.jobs.is_running

    def test_navigation_replaces_cache_global_labels_and_read_only_copy(self) -> None:
        view = LargeDataView()
        self.addCleanup(self.dispose, view)
        view.set_source(self.source())
        self.wait_until(lambda: self.loaded(view, 0))
        first = view.model.page
        view.next.click()
        self.assertIsNone(view.model.page)
        self.wait_until(lambda: self.loaded(view, 1000))
        self.assertIsNot(view.model.page, first)
        self.assertEqual(view.model.rowCount(), 1000)
        self.assertEqual(view.model.headerData(0, Qt.Vertical), "1001")
        self.assertFalse(view.model.flags(view.model.index(0, 0)) & Qt.ItemIsEditable)
        view.row_input.setText("2,501")
        view._go_to_row()
        self.wait_until(lambda: self.loaded(view, 2500))
        self.assertEqual(view.model.rowCount(), 7)
        self.assertFalse(view.next.isEnabled())
        view.table.selectAll()
        view._copy_selection()
        self.assertTrue(QApplication.clipboard().text().startswith("2500\t2500\n"))

    def test_slow_page_requests_coalesce_and_do_not_block_or_publish_stale_source(self) -> None:
        view = LargeDataView()
        self.addCleanup(self.dispose, view)
        first, second = self.source("first"), self.source("second", 5000)
        entered, release = Event(), Event()
        self.addCleanup(release.set)
        calls = []
        original = LargeDataset.read_page

        def slow(source, row, column=0, **kwargs):
            calls.append((source.name, row))
            if source is first:
                entered.set()
                release.wait(5)
            return original(source, row, column, **kwargs)

        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        with patch.object(LargeDataset, "read_page", slow):
            timer.start()
            view.set_source(first)
            self.wait_until(entered.is_set)
            view.set_source(second)
            for row in (1000, 2000, 3000, 4000):
                view.request_window(row)
            QTest.qWait(40)
            self.assertGreater(len(ticks), 3)
            self.assertIsNone(view.model.page)
            release.set()
            self.wait_until(lambda: self.loaded(view, 4000))
            timer.stop()
        self.assertEqual(calls, [("first", 0), ("second", 4000)])
        self.assertIn("second", view.summary.text())

    def test_page_failure_is_contained_and_retry_recovers(self) -> None:
        view = LargeDataView()
        self.addCleanup(self.dispose, view)
        source = self.source()
        with self.assertLogs("ui.background_jobs", level="ERROR"), patch.object(LargeDataset, "read_page", side_effect=OSError("Read failed")):
            view.set_source(source)
            self.wait_until(lambda: "Read failed" in view.summary.text() and not view.jobs.is_running)
        self.assertIsNone(view.model.page)
        view.retry.click()
        self.wait_until(lambda: self.loaded(view, 0))

    def test_wheel_at_window_edge_loads_adjacent_rows(self) -> None:
        view = LargeDataView()
        self.addCleanup(self.dispose, view)
        view.resize(900, 500)
        view.show()
        view.set_source(self.source())
        self.wait_until(lambda: self.loaded(view, 0))
        view.table.scrollToBottom()
        event = QWheelEvent(QPointF(30, 30), QPointF(30, 30), QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(view.table.viewport(), event)
        self.wait_until(lambda: self.loaded(view, 1000))
        view.table.scrollToTop()
        event = QWheelEvent(QPointF(30, 30), QPointF(30, 30), QPoint(), QPoint(0, 120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(view.table.viewport(), event)
        self.wait_until(lambda: self.loaded(view, 0))
        self.assertEqual(view.table.verticalScrollBar().value(), view.table.verticalScrollBar().maximum())

    def test_open_large_action_commits_background_parquet_import(self) -> None:
        source = self.source()
        window = MainWindow()
        try:
            with patch("ui.main_window.QFileDialog.getOpenFileName", return_value=(str(source.path), "")):
                window._open_large_data()
            self.wait_until(lambda: window._text_import_token is None)
            self.assertEqual(len(window._workspace.large_dataset_names()), 1)
            self.assertEqual(window._workspace.dataset_names(), [])
            self.wait_until(lambda: window._large_data_view.model.page is not None)
            self.assertEqual(window._large_data_view.model.rowCount(), 1000)
        finally:
            window.close()
            self.wait_until(lambda: not window._jobs.is_running and not window._large_data_view.jobs.is_running)
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            gc.collect()

    def test_import_result_is_rejected_after_workspace_replacement(self) -> None:
        window = MainWindow()
        original_workspace = window._workspace
        token = object()
        window._text_import_token = token
        window._text_import_workspace = original_workspace
        window._workspace = Workspace()
        window._commit_large_data_import(token, self.source())
        self.assertEqual(window._workspace.large_dataset_names(), [])
        self.assertEqual(original_workspace.large_dataset_names(), [])
        self.assertIsNone(window._text_import_token)
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def test_csv_open_options_worker_and_commit(self) -> None:
        path = self.root / "source.csv"
        path.write_text("x,y\n001,1.25\n002,2.50\n", encoding="utf8")
        window = MainWindow()
        errors = []

        class Options:
            Accepted = 1

            def __init__(self, *args, **kwargs):
                pass

            def setWindowTitle(self, title):
                pass

            def exec(self):
                return self.Accepted

            def options(self):
                return ImportOptions()

        try:
            with (
                patch("ui.main_window.QFileDialog.getOpenFileName", return_value=(str(path), "")),
                patch("ui.main_window.ImportOptionsDialog", Options),
                patch("ui.main_window.QMessageBox.critical", side_effect=lambda *args: errors.append(args[-1])),
            ):
                window._open_large_data()
                self.wait_until(lambda: window._text_import_token is None)
                self.wait_until(lambda: window._large_data_view.model.page is not None)
            self.assertEqual(errors, [])
            self.assertEqual(window._workspace.dataset_names(), [])
            self.assertEqual(window._large_data_view.model.page.frame.row(0), ("001", "1.25"))
        finally:
            window.close()
            self.wait_until(lambda: not window._jobs.is_running and not window._large_data_view.jobs.is_running)
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            gc.collect()

    def test_main_window_import_safety_extraction_and_deferred_close(self) -> None:
        window = MainWindow()
        view = window._large_data_view
        source = self.source()
        window._workspace.add_dataset("ordinary", pd.DataFrame({"x": [1]}))
        window._refresh_dataset_list("ordinary")
        window._workspace.add_large_dataset(source)
        window._refresh_large_dataset_list(source.name)
        self.wait_until(lambda: self.loaded(view, 0))
        self.assertIsNone(window._current_dataset())
        self.assertIsNone(window._dataset_model.dataset)
        self.assertFalse(window._apply_formula_action.isEnabled())
        self.assertTrue(window._has_project_content())
        view.extract.click()
        self.assertEqual(len(window._workspace.dataset_names()), 2)
        extracted = window._current_dataset()
        self.assertEqual(len(extracted.frame), 1000)
        self.assertIn("not the complete source", extracted.worksheet_metadata.import_details["Scope"])
        window._show_large_dataset(source.name)
        self.wait_until(lambda: view.jobs.is_running or view.model.page is not None)
        window.close()
        self.wait_until(lambda: not view.jobs.is_running and not window._jobs.is_running)
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()


if __name__ == "__main__":
    unittest.main()
