"""Replay real GUI operations against both original and changed source data."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import gc
import os
from threading import Event
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from core.api_recording import ApiRecording
from core.jobs import JobContext
from core.workspace import Workspace, ColumnMetadata
from jasc_api import Session
from tests.test_api_recording import replay, methods
from tests.test_background_peak_fit import example_request, ReviewedDialog


def settings(**values):
    return SimpleNamespace(**{key: (lambda value=value: value) for key, value in values.items()})


class ApiCoverageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ui.main_window import MainWindow
        self.window = MainWindow()
        self.source = self.window._workspace.add_dataset("source", pd.DataFrame({
            "x": np.arange(12, dtype=float), "y": np.arange(12, dtype=float)**2+1,
            "other": np.arange(12, dtype=float)*3+2, "group": ["a"]*6+["b"]*6,
        }))
        self.window._refresh_dataset_list(self.source.name)
        for column in self.source.frame:
            self.source.metadata_for_column(column)
        self.starting = deepcopy(self.window._workspace)
        self.controller = self.window._macros
        self.controller.start_recording(name="Full analysis")
        preview = patch.object(self.window, "_show_batch_preview", return_value=True)
        preview.start()
        self.addCleanup(preview.stop)
        self.messages = []
        for name in ("warning", "critical", "information"):
            patcher = patch("ui.main_window.QMessageBox."+name, side_effect=lambda *args: self.messages.append(args[1:]))
            patcher.start()
            self.addCleanup(patcher.stop)

    def wait_job(self):
        limit = time.monotonic()+20
        while self.window._jobs.is_running and time.monotonic() < limit:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.window._jobs.is_running)

    def tearDown(self):
        self.window._jobs.cancel()
        self.wait_job()
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def finish(self):
        self.controller.stop_recording()
        recording = self.controller.api_recording
        self.assertEqual(recording.issues, [])
        return recording

    def assert_frames(self, actual):
        self.assertEqual(actual.dataset_names(), self.window._workspace.dataset_names())
        for name in actual.dataset_names():
            expected = self.window._workspace.get_dataset(name).frame
            result = actual.get_dataset(name).frame
            # Runtime measurements are intentionally recalculated rather than copied.
            columns = [column for column in expected if column != "elapsed_seconds"]
            pd.testing.assert_frame_equal(result[columns], expected[columns], check_dtype=False, check_exact=False)

    def test_worksheet_edit_history_and_lifecycle_are_executable(self):
        model = self.window._dataset_model
        model.setData(model.index(0, 1), "25")
        model.fill_range("sequence", 1, 12, 10., 2.)
        model.paste_block(1, 1, [[44.], [55.]])
        model.undo()
        model.redo()
        model.clear_cells([(3, 1, 3, 1)])
        model.delete_rows([11])
        output = self.window._workspace.duplicate_dataset(self.source.name)
        self.controller.api_duplicate_sheet(self.source, output)
        old = output.name
        self.window._workspace.rename_dataset(old, "copy")
        self.controller.api_renamed_sheet(output, old)
        self.window._workspace.remove_dataset(output.name)
        self.controller.api_deleted_sheet(output)
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        self.assertIn("edit", methods(recording))

    def test_all_data_prep_dispatches_recompute_from_replayed_input(self):
        from core import data_prep
        cases = [
            ("filter", {"condition": {"column": "y", "operator": "gt", "value": "12"}}, lambda f: data_prep.apply_filter_condition(f, data_prep.FilterCondition("y", "gt", "12"))),
            ("subset", {"row_mode": "odd"}, lambda f: data_prep.extract_positional_subset(f, row_mode="odd")),
            ("sort", {"columns": ["y"], "ascending": False}, lambda f: data_prep.sort_dataframe(f, ["y"], False)),
            ("duplicates", {"columns": ["group"], "keep": "first"}, lambda f: data_prep.remove_duplicate_rows(f, ["group"], "first")),
            ("missing", {"columns": ["y"], "strategy": "fill_mean"}, lambda f: data_prep.clean_missing_values(f, ["y"], "fill_mean")),
            ("group", {"group_columns": ["group"], "value_columns": ["y"], "aggregations": ["mean", "std"]}, lambda f: data_prep.group_aggregate_dataframe(f, ["group"], ["y"], ["mean", "std"])),
            ("merge", {"left_key": "x", "right_key": "x", "how": "inner"}, lambda f: data_prep.merge_join_dataframes(f, f, "x", "x", "inner")),
            ("reshape", {"mode": "melt", "id_columns": ["x"], "value_columns": ["y", "other"]}, lambda f: data_prep.reshape_dataframe(f, "melt", ["x"], ["y", "other"])),
            ("bin", {"bin_column": "x", "value_columns": ["y"], "bin_count": 3}, lambda f: data_prep.bin_dataframe(f, "x", ["y"], 3)),
        ]
        for operation, options, compute in cases:
            self.window._create_data_prep_result(operation, operation, compute(self.source.frame),
                [self.source, self.source] if operation == "merge" else [self.source], operation, "", {"operation": operation, **options})
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        changed = Workspace()
        modified = self.source.frame.copy()
        modified["y"] *= 5
        changed.add_dataset("source", modified)
        replay(recording.source(), changed)
        for operation, _, compute in cases:
            pd.testing.assert_frame_equal(changed.get_dataset(operation).frame, compute(modified))

    def test_statistics_summaries_and_companion_plots_recalculate(self):
        dialog = settings(operation_key="single_complete", primary_dataset_name="source", primary_columns=["y", "other"],
                          secondary_dataset_name="source", secondary_columns=[], requires_secondary_column=False,
                          multi_columns=[], target_dataset_names=["source"], target_dataset_name="stats", column_binding_mode="name",
                          plot_result_immediately=True, statistics_plot_kind="auto")
        self.window._run_statistics_batch(dialog)
        self.assertEqual(self.messages, [])
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        self.assertTrue(self.starting.list_plots())
        changed = Workspace()
        modified = pd.concat([self.source.frame, self.source.frame], ignore_index=True)
        modified["y"] *= 10
        changed.add_dataset("source", modified)
        replay(recording.source(), changed)
        summary = changed.get_dataset("source_statistics_batch_summary").frame
        self.assertAlmostEqual(float(summary.loc[(summary.primary_column == "y") & (summary.metric == "mean"), "value"].iloc[0]), modified.y.mean())

    def test_interpolation_results_and_batch_quality_metrics_recalculate(self):
        metadata = deepcopy(self.source.column_metadata)
        metadata["x"].unit = "s"
        metadata["y"].long_name = "Observed signal"
        self.window._dataset_model.set_column_metadata(metadata)
        dialog = settings(mode="1d", coordinate_columns=["x"], value_column="y", value_columns=["y", "other"],
                          method_key="linear", fill_policy="nan", smoothing=0., epsilon=None,
                          query_mode="generated", query_columns=[], generated_ranges=[(0., 11., 17)],
                          target_dataset_names=["source"], target_dataset_name="interp", column_binding_mode="name")
        self.window._run_interpolation_batch(self.source, dialog)
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        self.assertIn("result_row", methods(recording))
        for name in ("interp_y", "interp_other"):
            self.assertEqual(self.starting.get_dataset(name).column_metadata,
                             self.window._workspace.get_dataset(name).column_metadata)

    def test_peak_background_job_records_published_analysis_and_exports(self):
        request = example_request()
        source = self.window._workspace.add_dataset("Map", request.sources[0].frame)
        self.controller.stop_recording()
        self.starting = deepcopy(self.window._workspace)
        self.controller.start_recording(name="Map fitting")
        dialog = ReviewedDialog(replace(request, signal_name="corrected", peak_name="peaks", fit_name="fit", parameter_name="parameters"))
        self.window._run_peak_analysis_batch_or_map(source, dialog, {})
        self.wait_job()
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        actual = self.starting.list_spectral_analyses()[0]
        expected = self.window._workspace.list_spectral_analyses()[0]
        pd.testing.assert_frame_equal(actual.curves_frame, expected.curves_frame)
        self.assertIn("spectral_batch", methods(recording))

    def test_changed_background_source_adds_no_recorded_analysis_call(self):
        request = example_request()
        source = self.window._workspace.add_dataset("Map", request.sources[0].frame)
        self.controller.stop_recording()
        self.controller.start_recording(name="Stale job")
        self.window._run_peak_analysis_batch_or_map(source, ReviewedDialog(request), {})
        source.frame.loc[0, "signal"] += 1
        self.wait_job()
        # This edit bypassed the editor deliberately; check publication separately.
        self.assertFalse(self.window._workspace.list_spectral_analyses())
        self.assertNotIn("spectral_batch", methods(self.controller.api_recording))

    def test_fit_batch_reports_correlations_and_summary_recalculate(self):
        from ui.dialogs import FitDialog
        from tests.test_macro_ui import select_list_items
        dialog = FitDialog(list(self.source.frame), self.source.name, default_x_column="x", parent=self.window)
        select_list_items(dialog._y_column_list, ["y", "other"])
        dialog._model_combo.setCurrentIndex(dialog._model_combo.findData("linear"))
        dialog.create_parameter_correlation_sheet = lambda: True
        self.window._run_curve_fit_batch(self.source, dialog, [1., 0.], [None, None], [None, None], [False, False])
        dialog.deleteLater()
        self.assertEqual(self.messages, [])
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        modified = Workspace()
        frame = self.source.frame.copy()
        frame["other"] = frame.x * 7+9
        modified.add_dataset("source", frame)
        replay(recording.source(), modified)
        summary = modified.get_dataset("source_fit_batch_summary").frame
        row = summary.loc[summary.y_column == "other"].iloc[0]
        self.assertAlmostEqual(row.param_a, 7., places=6)
        self.assertAlmostEqual(row.param_b, 9., places=6)

    def test_group_statistics_keep_all_new_groups_in_summary(self):
        dialog = settings(operation_key="group_summary", primary_dataset_name="source", primary_columns=["y", "other"],
                          secondary_dataset_name="source", secondary_columns=["group"], requires_secondary_column=True,
                          multi_columns=[], target_dataset_names=["source"], target_dataset_name="grouped", column_binding_mode="name",
                          plot_result_immediately=False, statistics_plot_kind="auto")
        self.window._run_statistics_batch(dialog)
        self.assertEqual(self.messages, [])
        recording = self.finish()
        modified = deepcopy(self.starting)
        modified.get_dataset("source").frame.loc[8:, "group"] = "new group"
        replay(recording.source(), modified)
        summary = modified.get_dataset("source_statistics_batch_summary").frame
        self.assertIn("new_group_count", summary.metric.tolist())
        self.assertTrue((summary.loc[summary.metric == "group_count", "value"] == 3).all())

    def test_baseline_map_records_only_completed_result(self):
        # Reuse the real settings-only peak dialog: baseline map needs the same getters.
        request = replace(example_request(), signal_name="baseline output")
        source = self.window._workspace.add_dataset("Map", request.sources[0].frame)
        self.controller.stop_recording()
        self.starting = deepcopy(self.window._workspace)
        self.controller.start_recording(name="Map baseline")
        self.window._run_baseline_map(source, ReviewedDialog(request), {})
        self.wait_job()
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        self.assertIn("baseline_map", methods(recording))

    def test_map_grid_roi_and_line_cut_use_dynamic_source_bindings(self):
        from ui.plot_canvas import PlotCanvas, PlotSeries
        frame = pd.DataFrame({"mx": np.tile([0., 1., 2.], 3), "my": np.repeat([0., 1., 2.], 3), "signal": np.arange(9, dtype=float)})
        source = self.window._workspace.add_dataset("map", frame)
        self.controller.stop_recording()
        self.starting = deepcopy(self.window._workspace)
        self.controller.start_recording(name="Map cuts")
        series = PlotSeries("map", "mx", "map", "my", z_dataset="map", z_column="signal", plot_type="heatmap")
        canvas = PlotCanvas()
        frames = [
            ("grid", [], canvas.surface_grid_frame(self.window._workspace, series)),
            ("roi", [0., 2., 0., 2.], canvas.surface_roi_summary_frame(self.window._workspace, series, 0., 2., 0., 2.)),
            ("line", [0., 0., 2., 2., 7], canvas.surface_line_profile_frame(self.window._workspace, series, 0., 0., 2., 2., 7)),
        ]
        for operation, parameters, result in frames:
            self.window._plot_tab_widget._commit_surface_analysis(series, operation, operation, result, parameters)
        canvas.deleteLater()
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        changed = deepcopy(self.starting)
        changed.get_dataset("map").frame.signal *= 3
        # New session avoids result-name collisions; preserve only the starting sheets.
        changed = Workspace()
        changed.add_dataset("source", self.source.frame)
        changed.add_dataset("map", frame.assign(signal=frame.signal*3))
        replay(recording.source(), changed)
        np.testing.assert_allclose(changed.get_dataset("grid").frame.z, self.starting.get_dataset("grid").frame.z*3)

    def test_single_spectrum_replays_reviewed_peak_choices_and_analysis_exports(self):
        from core.spectral_preview import SpectralPreviewRequest, prepare_spectral_preview
        from core.spectral_jobs import SpectralSource
        from core.spectral_single import publish_spectrum
        request = example_request()
        source = self.window._workspace.add_dataset("spectrum", request.sources[0].frame.iloc[:301].drop(columns=["X", "Y"]))
        self.controller.stop_recording()
        self.starting = deepcopy(self.window._workspace)
        self.controller.start_recording(name="Single spectrum")
        preview = prepare_spectral_preview(JobContext(Event(), lambda _: None), SpectralPreviewRequest(
            "fit", SpectralSource(source.name, source.frame), "shift", "signal", {}, None,
            request.baseline, request.detection, request.fit, request.components))
        peak_frame = preview.peaks.peak_frame().assign(enabled=False, manual_status="disabled")
        dialog = settings(baseline_result=preview.baseline, peak_result=preview.peaks, composite_result=preview.fit,
                          reviewed_peak_frame=peak_frame, component_specs=request.components, baseline_parameters=request.baseline,
                          analysis_range=None, preview_coordinates={}, center_tolerance=10., analysis_name="single fit", analysis_profile={},
                          x_column="shift", y_column="signal", create_signal_output=True, result_sheet_name="corrected",
                          create_peak_output=True, peak_sheet_name="reviewed peaks", create_fit_output=True,
                          fit_sheet_name="curve", fit_parameter_sheet_name="parameters")
        published = publish_spectrum(self.window._workspace, source, dialog, preview.baseline, preview.peaks, preview.fit,
                                     False, {}, {}, "Peak Analysis")
        self.controller.api_spectrum(source, dialog, False, {}, published)
        output = Session(self.window._workspace).export_analysis_table(published.analysis, table="metrics", name="metrics")
        self.controller.api_analysis_table(published.analysis, "metrics", output)
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        self.assertFalse(self.starting.get_dataset("reviewed peaks").frame.enabled.iloc[0])

    def test_plot_deletion_and_column_rename_keep_live_references(self):
        from jasc_api import series
        session = Session(self.window._workspace)
        plot = session.plot([series(x=(self.source, "x"), y=(self.source, "y"))], name="delete me")
        recording = self.controller.api_recording
        recording.plotted(plot, self.window._workspace)
        session.delete_plot(plot)
        recording.plot_deletions(self.window._workspace)
        metadata = deepcopy(self.source.column_metadata)
        metadata["renamed"] = metadata.pop("y")
        pairs = self.window._dataset_model.apply_column_metadata(["x", "renamed", "other", "group"], metadata)
        self.window._workspace.rename_column_references_in_plots(self.source.name, pairs)
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        self.assertFalse(self.starting.list_plots())

    def test_excel_imports_and_large_data_windows_replay_from_files(self):
        from core.file_io import ImportOptions
        from openpyxl import Workbook
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = Workbook()
            workbook.active.title = "Values"
            workbook.active.append(["time", "signal"])
            workbook.active.append([0., 4.])
            workbook.active.append([1., 6.])
            path = root/"values.xlsx"
            workbook.save(path)
            dialog = settings(exec=QDialog.Accepted, selected_sheet_names=["Values"], has_header=True)
            with patch("ui.main_window.ExcelImportDialog", return_value=dialog):
                self.window._import_excel_workbook(path)
            csv = root/"large.csv"
            pd.DataFrame({"x": np.arange(100), "y": np.arange(100)*2}).to_csv(csv, index=False)
            session = Session(self.window._workspace)
            options = ImportOptions(delimiter=",", has_header=True)
            large = session.load_large(csv, **asdict(options))
            self.addCleanup(large._storage.cleanup)
            self.controller.api_large_import(large, options)
            page = large.read_page(10)
            output = session.extract_window(large, name="window", row_start=page.row_start,
                                            row_count=page.frame.height, column_start=0, column_count=page.frame.width)
            self.controller.api_large_extract(large, page, output)
            recording = self.finish()
            replay(recording.source(), self.starting, input_root=root)
            for replayed_large in self.starting.list_large_datasets():
                self.addCleanup(replayed_large._storage.cleanup)
            self.assert_frames(self.starting)
            self.assertEqual(self.starting.large_dataset_names(), self.window._workspace.large_dataset_names())
            self.assertEqual(methods(recording), ["load_excel", "load_large", "extract_window"])
            import polars as pl
            from core.large_data import DISPLAY_BYTES
            oversized = pl.DataFrame({"x": ["x"*(DISPLAY_BYTES+1)], "y": ["z"]}).lazy()
            with patch.object(type(large), "scan", return_value=oversized):
                with self.assertRaisesRegex(ValueError, "memory budget"):
                    session.extract_window(large, name="oversized", row_start=0, row_count=1, column_start=0, column_count=2)
            self.assertNotIn("oversized", self.window._workspace.dataset_names())

    def test_blank_sheet_cell_edits_and_undo_replay(self):
        self.window._create_blank_sheet()
        model = self.window._dataset_model
        model.setData(model.index(0, 0), "3")
        model.setData(model.index(0, 1), "4")
        model.undo()
        model.redo()
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)
        expected = self.window._workspace.get_dataset("Sheet")
        self.assertEqual(self.starting.get_dataset("Sheet").column_metadata, expected.column_metadata)

    def test_multi_statistics_and_regression_helpers_are_computations(self):
        session = Session(self.window._workspace)
        output = session.statistics(self.source, operation_key="multi_pca", columns=["x", "y", "other"], name="pca")
        self.controller.api_result("statistics", self.source, {"operation_key": "multi_pca", "columns": ["x", "y", "other"]}, output)
        self.window._statistics_pca_variance_dataset(output)
        result = session.statistics(self.source, operation_key="pair_linear_regression", primary_column="x",
                                    secondary=self.source, secondary_column="other", name="regression")
        self.controller.api_result("statistics", self.source, {"operation_key": "pair_linear_regression", "primary_column": "x",
                                   "secondary_column": "other"}, result, {"secondary": self.source})
        self.window._statistics_regression_line_dataset(self.source, "x", self.source, "other", result)
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)

    def test_fft_and_ifft_batch_summaries_replay(self):
        dialog = settings(target_dataset_names=["source"], target_dataset_name="spectrum", column_binding_mode="name",
                          signal_columns=["y", "other"], x_column="x", window_method="boxcar", plot_result_immediately=False)
        self.window._run_fft_batch(self.source, dialog)
        spectra = [item.name for item in self.window._workspace.list_datasets() if item.name.startswith("spectrum")]
        self.assertEqual(len(spectra), 2)
        dialog = settings(target_dataset_names=spectra, target_dataset_name="reconstructed", column_binding_mode="name",
                          real_columns=["real"], imaginary_columns=["imaginary"], plot_result_immediately=False)
        self.window._run_ifft_batch(self.window._workspace.get_dataset(spectra[0]), dialog)
        self.assertEqual(self.messages, [])
        recording = self.finish()
        replay(recording.source(), self.starting)
        self.assert_frames(self.starting)

    def test_parallel_formula_publication_records_formula_not_worker_values(self):
        from core.batch_processing import FormulaBatchWorkerResult
        expression = 'col("y") * 5'
        result = FormulaBatchWorkerResult("source", "processed", len(self.source.frame), self.source.frame.y*5)
        self.window._apply_formula_worker_result_to_dataset(self.source, result, expression, "name")
        recording = self.finish()
        modified = deepcopy(self.starting)
        modified.get_dataset("source").frame.y *= 3
        replay(recording.source(), modified)
        frame = modified.get_dataset("source").frame
        np.testing.assert_allclose(frame.processed, frame.y*5)


if __name__ == "__main__":
    unittest.main()
