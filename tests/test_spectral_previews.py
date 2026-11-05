"""Numerical equivalence, preview races, review preservation, and Qt ownership."""

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
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox
from shiboken6 import isValid

from core.jobs import JobCancelled, JobContext
from core.spectral_jobs import SpectralSource
from core.spectral_preview import SpectralPreviewRequest, prepare_spectral_preview
from math_engine.baseline import BaselineParameters, correct_baseline
from math_engine.calculus import MathOperationError
from math_engine.composite_peak_fit import CompositeFitParameters, build_peak_component_spec, fit_composite_peaks
from math_engine.peak_detection import PeakDetectionParameters, detect_peaks
from ui.main_window import MainWindow
from ui.peak_analysis_dialog import PeakAnalysisDialog


def spectrum(center: float = 245.0) -> pd.DataFrame:
    x = np.linspace(100.0, 400.0, 301)
    return pd.DataFrame({"shift": x, "signal": 2.0 + 5.0 * np.exp(-0.5 * ((x - center) / 6.0) ** 2)})


class SpectralPreviewWorkerTests(unittest.TestCase):
    def request(self) -> SpectralPreviewRequest:
        return SpectralPreviewRequest(
            "peaks", SpectralSource("Example", spectrum()), "shift", "signal", {}, None,
            BaselineParameters(method="constant", constant_value=2.0), PeakDetectionParameters(prominence=1.0),
        )

    def test_pipeline_matches_engines_and_cached_fit_preserves_input(self) -> None:
        request = self.request()
        source = request.source.frame.copy(deep=True)
        result = prepare_spectral_preview(JobContext(Event(), lambda _p: None), request)
        expected = correct_baseline(source["shift"].to_numpy(), source["signal"].to_numpy(), request.baseline_parameters)
        np.testing.assert_allclose(result.baseline.corrected, expected.corrected)
        peaks = detect_peaks(expected.x, expected.raw, expected.corrected, request.detection_parameters,
                             source_sheet="Example", channel="signal")
        self.assertEqual([peak.center for peak in result.peaks.peaks], [peak.center for peak in peaks.peaks])
        component = build_peak_component_spec(result.peaks.peaks[0], "gaussian", result.baseline.x)
        fit_request = replace(request, kind="fit", baseline=result.baseline, peaks=result.peaks,
                              components=(component,), fit_parameters=CompositeFitParameters())
        with patch("core.spectral_preview.correct_baseline") as baseline, patch("core.spectral_preview.detect_peaks") as detect:
            fitted = prepare_spectral_preview(JobContext(Event(), lambda _p: None), fit_request)
            baseline.assert_not_called()
            detect.assert_not_called()
        self.assertGreater(fitted.fit.r_squared, 0.99999)
        pd.testing.assert_frame_equal(request.source.frame, source)

    def test_map_pixel_descending_axis_range_and_text_validation(self) -> None:
        frame = pd.concat([spectrum(center).assign(X=coordinate, Y=0.0)
                           for coordinate, center in ((0.0, 245.0), (1.0, 275.0))], ignore_index=True).iloc[::-1]
        request = replace(self.request(), source=SpectralSource("Map", frame), coordinates={"X": 1.0, "Y": 0.0},
                          analysis_range=(200.0, 350.0))
        result = prepare_spectral_preview(JobContext(Event(), lambda _p: None), request)
        self.assertEqual(len(result.baseline.x), 301)
        self.assertEqual(result.baseline.provenance["X"], 1.0)
        self.assertEqual(result.peaks.peaks[0].center, 275.0)
        finite = result.baseline.x[np.isfinite(result.baseline.x)]
        self.assertLess(finite[-1], finite[0])
        self.assertTrue(np.isnan(result.baseline.corrected).any())
        text = frame.astype({"signal": object})
        text.loc[text["X"] == 1.0, "signal"] = "invalid"
        with self.assertRaises(MathOperationError):
            prepare_spectral_preview(JobContext(Event(), lambda _p: None), replace(request, source=SpectralSource("Map", text)))

    def test_cancellation_between_native_phases_and_during_fit(self) -> None:
        cancellation = Event()
        request = self.request()

        def cancel_after_baseline(*args: object, **kwargs: object) -> object:
            baseline = correct_baseline(*args, **kwargs)
            cancellation.set()
            return baseline

        with patch("core.spectral_preview.correct_baseline", side_effect=cancel_after_baseline), \
                patch("core.spectral_preview.detect_peaks") as detect:
            with self.assertRaises(JobCancelled):
                prepare_spectral_preview(JobContext(cancellation, lambda _p: None), request)
            detect.assert_not_called()
        with self.assertRaises(JobCancelled):
            prepare_spectral_preview(JobContext(cancellation, lambda _p: None), request)


class SpectralPreviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        gc.collect()
        self.dialogs: list[PeakAnalysisDialog] = []
        self.windows: list[MainWindow] = []
        self.release, self.entered = Event(), Event()
        self.warnings = patch("ui.peak_analysis_dialog.QMessageBox.warning").start()

    def tearDown(self) -> None:
        self.release.set()
        for dialog in self.dialogs:
            if isValid(dialog):
                dialog.reject()
                self.wait_until(lambda: not isValid(dialog) or not dialog._preview_jobs.is_running)
                if isValid(dialog):
                    dialog.deleteLater()
        for window in self.windows:
            window.close()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        patch.stopall()
        gc.collect()

    def wait_until(self, predicate: Callable[[], bool], seconds: float = 15) -> None:
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(predicate(), "Preview did not reach the expected state")

    def dialog(self, frame: pd.DataFrame | None = None, **kwargs: object) -> PeakAnalysisDialog:
        dialog = PeakAnalysisDialog(spectrum() if frame is None else frame, "Example",
                                    default_x_column="shift", default_y_column="signal", **kwargs)
        self.dialogs.append(dialog)
        dialog._baseline_method.setCurrentIndex(dialog._baseline_method.findData("constant"))
        dialog._constant_value.setText("2")
        dialog._prominence.setText("1")
        dialog._preview_timer.stop()
        return dialog

    def wait_preview(self, dialog: PeakAnalysisDialog) -> None:
        self.wait_until(lambda: not dialog.preview_busy)

    def block_baseline(self, *args: object, **kwargs: object) -> object:
        self.entered.set()
        if not self.release.wait(8):
            raise RuntimeError("Test did not release the baseline worker")
        return correct_baseline(*args, **kwargs)

    def test_worker_heartbeat_and_gui_publication(self) -> None:
        dialog = self.dialog(baseline_only=True)
        ticks, workers, deliveries = [], [], []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        apply = dialog._apply_preview

        def baseline(*args: object, **kwargs: object) -> object:
            workers.append(get_ident())
            return self.block_baseline(*args, **kwargs)

        def publish(*args: object) -> None:
            deliveries.append(QThread.currentThread() == self.app.thread())
            apply(*args)

        try:
            timer.start()
            with patch("core.spectral_preview.correct_baseline", side_effect=baseline), \
                    patch.object(dialog, "_apply_preview", side_effect=publish):
                dialog.preview_baseline()
                self.wait_until(lambda: self.entered.is_set() and len(ticks) >= 4)
                self.assertIsNone(dialog._baseline_result)
                self.release.set()
                self.wait_preview(dialog)
            self.assertEqual(deliveries, [True])
            self.assertNotEqual(workers, [get_ident()])
            np.testing.assert_allclose(dialog.baseline_result().baseline, 2.0)
        finally:
            timer.stop()

    def test_rapid_changes_coalesce_and_only_latest_result_is_drawn(self) -> None:
        dialog = self.dialog(baseline_only=True)
        calls, published = [], []
        apply = dialog._apply_preview

        def baseline(*args: object, **kwargs: object) -> object:
            calls.append(args[2].constant_value)
            if len(calls) == 1:
                return self.block_baseline(*args, **kwargs)
            return correct_baseline(*args, **kwargs)

        def publish(request: object, result: object) -> None:
            published.append(result.baseline.parameters.constant_value)
            apply(request, result)

        with patch("core.spectral_preview.correct_baseline", side_effect=baseline), \
                patch.object(dialog, "_apply_preview", side_effect=publish):
            dialog.preview_baseline()
            self.wait_until(self.entered.is_set)
            for value in (3, 4, 5):
                dialog._constant_value.setText(str(value))
                dialog.preview_baseline()
            self.release.set()
            self.wait_preview(dialog)
        self.assertEqual(calls, [2.0, 5.0])
        self.assertEqual(published, [5.0])
        self.assertEqual(dialog.baseline_result().parameters.constant_value, 5.0)

    def test_switching_pixel_and_range_discards_previous_work(self) -> None:
        frame = pd.concat([spectrum(center).assign(X=coordinate, Y=0.0)
                           for coordinate, center in ((0.0, 245.0), (1.0, 275.0))], ignore_index=True)
        dialog = self.dialog(frame)
        with patch("core.spectral_preview.correct_baseline", side_effect=self.block_baseline):
            dialog.preview_peaks()
            self.wait_until(self.entered.is_set)
            dialog._preview_pixel.setCurrentIndex(1)
            dialog._range_checkbox.setChecked(True)
            dialog._range_min.setValue(250.0)
            dialog._range_max.setValue(350.0)
            dialog.preview_peaks()
            self.release.set()
            self.wait_preview(dialog)
        self.assertEqual(dialog.baseline_result().provenance["X"], 1.0)
        self.assertEqual(dialog.peak_result().peaks[0].center, 275.0)
        self.assertEqual(float(np.nanmin(dialog.baseline_result().x)), 250.0)

    def test_external_source_edit_is_recomputed_before_publication(self) -> None:
        frame = spectrum()
        dialog = self.dialog(frame, baseline_only=True)
        calls = []

        def baseline(*args: object, **kwargs: object) -> object:
            calls.append(True)
            if len(calls) == 1:
                return self.block_baseline(*args, **kwargs)
            return correct_baseline(*args, **kwargs)

        with patch("core.spectral_preview.correct_baseline", side_effect=baseline):
            dialog.preview_baseline()
            self.wait_until(self.entered.is_set)
            frame.loc[:, "signal"] += 10.0
            self.release.set()
            self.wait_preview(dialog)
        self.assertEqual(len(calls), 2)
        np.testing.assert_allclose(dialog.baseline_result().raw, frame["signal"])

    def test_source_switch_rejects_old_preview(self) -> None:
        first, other = spectrum(), spectrum(275.0)
        dialog = self.dialog(first, datasets={"Example": first, "Other": other})
        with patch("core.spectral_preview.correct_baseline", side_effect=self.block_baseline):
            dialog.preview_peaks()
            self.wait_until(self.entered.is_set)
            dialog._source_dataset_combo.setCurrentIndex(dialog._source_dataset_combo.findData("Other"))
            dialog._y_combo.setCurrentIndex(dialog._y_combo.findData("signal"))
            dialog.preview_peaks()
            self.release.set()
            self.wait_preview(dialog)
        self.assertEqual(dialog.baseline_result().provenance["source_sheet"], "Other")
        self.assertEqual(dialog.peak_result().peaks[0].center, 275.0)

    def test_fit_edits_discard_inflight_result_and_preserve_reviewed_components(self) -> None:
        dialog = self.dialog()
        dialog.preview_peaks()
        self.wait_preview(dialog)
        dialog._peak_table.item(0, 1).setText("245.5")

        def fit(*args: object, **kwargs: object) -> object:
            self.entered.set()
            self.release.wait(8)
            return fit_composite_peaks(*args, **kwargs)

        with patch("core.spectral_preview.fit_composite_peaks", side_effect=fit):
            dialog.preview_composite_fit()
            self.wait_until(self.entered.is_set)
            model = dialog._component_table.cellWidget(0, 2)
            model.setCurrentIndex(model.findData("lorentzian"))
            self.release.set()
            self.wait_preview(dialog)
        self.assertIsNone(dialog.composite_result())
        self.assertEqual(dialog.component_specs()[0].model_key, "lorentzian")
        self.assertEqual(dialog.reviewed_peak_frame().iloc[0]["center"], 245.5)
        dialog.preview_composite_fit()
        self.wait_preview(dialog)
        self.assertEqual(dialog.composite_result().components[0].model_key, "lorentzian")

    def test_accept_uses_review_without_redetecting_and_waits_for_fit(self) -> None:
        dialog = self.dialog()
        dialog.preview_peaks()
        self.wait_preview(dialog)
        dialog._peak_table.item(0, 1).setText("245.5")
        accepted = []
        dialog.accepted.connect(lambda: accepted.append(True))
        with patch("core.spectral_preview.detect_peaks") as detect:
            dialog.accept()
            self.assertFalse(accepted)
            self.wait_until(lambda: bool(accepted))
            detect.assert_not_called()
        self.assertEqual(accepted, [True])
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.reviewed_peak_frame().iloc[0]["center"], 245.5)
        self.assertEqual(dialog.composite_result().components[0].peak.center, 245.5)

    def test_accept_before_first_preview_chains_detection_and_fit(self) -> None:
        dialog = self.dialog()
        dialog.accept()
        self.wait_until(lambda: dialog._preview_closed)
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertGreater(dialog.composite_result().r_squared, 0.99999)

    def test_rendered_fit_is_bounded_while_full_result_is_retained(self) -> None:
        x = np.linspace(100.0, 400.0, 10001)
        dialog = self.dialog(pd.DataFrame({"shift": x, "signal": 2.0 + 5.0 * np.exp(-0.5 * ((x - 245.0) / 6.0) ** 2)}))
        dialog.preview_composite_fit()
        self.wait_preview(dialog)
        self.assertEqual(len(dialog.composite_result().fit_frame), 10001)
        for axis in dialog._figure.axes:
            self.assertTrue(all(len(line.get_xdata()) <= 6000 for line in axis.lines))

    def test_review_disable_remove_and_manual_add_survive_refresh(self) -> None:
        dialog = self.dialog()
        dialog.preview_peaks()
        self.wait_preview(dialog)
        dialog._peak_table.item(0, 0).setCheckState(Qt.Unchecked)
        self.assertFalse(dialog.component_specs()[0].enabled)
        dialog.preview_peaks()
        self.wait_preview(dialog)
        self.assertFalse(dialog.component_specs()[0].enabled)
        dialog._peak_table.selectRow(0)
        dialog._remove_selected_peaks()
        dialog.preview_peaks()
        self.wait_preview(dialog)
        self.assertEqual(len(dialog.reviewed_peak_frame()), 0)
        with patch("PySide6.QtWidgets.QInputDialog.getDouble", return_value=(265.0, True)):
            dialog._add_manual_peak()
        dialog.preview_peaks()
        self.wait_preview(dialog)
        self.assertEqual(list(dialog.reviewed_peak_frame()["manual_status"]), ["added"])

    def test_invalid_output_name_after_pending_accept_can_be_fixed(self) -> None:
        dialog = self.dialog(baseline_only=True)
        dialog._result_sheet.clear()
        dialog.accept()
        self.wait_preview(dialog)
        self.warnings.assert_called_once()
        self.assertTrue(dialog._buttons.button(QDialogButtonBox.Ok).isEnabled())
        self.assertFalse(dialog._preview_closed)
        dialog._result_sheet.setText("Corrected")
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_stop_queued_success_then_retry(self) -> None:
        dialog = self.dialog()
        dialog.preview_peaks()
        self.assertTrue(dialog._preview_jobs._thread.wait(5000))
        dialog._cancel_preview()
        self.wait_preview(dialog)
        self.assertIsNone(dialog.peak_result())
        dialog.preview_peaks()
        self.wait_preview(dialog)
        self.assertEqual(len(dialog.peak_result().peaks), 1)

    def test_profile_change_while_busy_uses_latest_settings(self) -> None:
        dialog = self.dialog(baseline_only=True)
        profile = dialog.analysis_profile()
        profile["baseline"]["constant_value"] = 7.0
        with patch("core.spectral_preview.correct_baseline", side_effect=self.block_baseline):
            dialog.preview_baseline()
            self.wait_until(self.entered.is_set)
            dialog.apply_analysis_profile(profile)
            self.release.set()
            self.wait_preview(dialog)
        self.assertEqual(dialog.baseline_result().parameters.constant_value, 7.0)

    def test_error_recovery_and_invalid_selection(self) -> None:
        dialog = self.dialog(baseline_only=True)
        dialog._anchors.setText("bad anchors")
        dialog._baseline_method.setCurrentIndex(dialog._baseline_method.findData("manual"))
        dialog.preview_baseline(show_errors=False)
        self.wait_preview(dialog)
        self.assertIsNone(dialog._baseline_result)
        dialog._anchors.clear()
        dialog._baseline_method.setCurrentIndex(dialog._baseline_method.findData("constant"))
        dialog.preview_baseline()
        self.wait_preview(dialog)
        self.assertIsNotNone(dialog._baseline_result)
        dialog._frame.loc[1, "shift"] = dialog._frame.loc[0, "shift"]
        with self.assertLogs("ui.background_jobs", level="ERROR"):
            dialog.preview_baseline(show_errors=False)
            self.wait_preview(dialog)
        self.assertIsNone(dialog._baseline_result)
        dialog._y_combo.setCurrentIndex(0)
        self.assertFalse(dialog.preview_baseline(show_errors=False))
        self.assertIsNone(dialog._baseline_result)

    def test_close_and_programmatic_delete_wait_for_worker(self) -> None:
        for delete in (False, True):
            with self.subTest(delete=delete):
                self.release.clear()
                self.entered.clear()
                dialog = self.dialog(baseline_only=True)
                dialog.show()
                with patch("core.spectral_preview.correct_baseline", side_effect=self.block_baseline):
                    dialog.preview_baseline()
                    self.wait_until(self.entered.is_set)
                    if delete:
                        dialog.deleteLater()
                    else:
                        dialog.close()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                    self.assertTrue(isValid(dialog))
                    self.assertTrue(dialog._preview_jobs.is_running)
                    self.release.set()
                    self.wait_until(lambda: not isValid(dialog) if delete else not dialog.isVisible())
                if not delete:
                    self.assertEqual(dialog.result(), QDialog.Rejected)
                    self.assertIsNone(dialog._baseline_result)

    def test_parent_window_close_waits_for_preview(self) -> None:
        window = MainWindow()
        self.windows.append(window)
        dialog = self.dialog(baseline_only=True, parent=window)
        window.show()
        dialog.show()
        with patch("core.spectral_preview.correct_baseline", side_effect=self.block_baseline):
            dialog.preview_baseline()
            self.wait_until(self.entered.is_set)
            window.close()
            self.assertTrue(window.isVisible())
            self.release.set()
            self.wait_until(lambda: not window.isVisible())
        self.assertFalse(dialog._preview_jobs.is_running)

    def test_project_replacement_rejects_pending_dialog_results(self) -> None:
        window = MainWindow()
        self.windows.append(window)
        source = window._workspace.add_dataset("Example", spectrum())
        dialog = self.dialog(source.frame, baseline_only=True, parent=window)
        with patch("core.spectral_preview.correct_baseline", side_effect=self.block_baseline):
            dialog.preview_baseline()
            self.wait_until(self.entered.is_set)
            with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.Yes):
                window._close_project()
            self.assertEqual(dialog._preview_close_result, QDialog.Rejected)
            self.release.set()
            self.wait_until(lambda: dialog._preview_closed)
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertIsNone(dialog._baseline_result)
        self.assertEqual(window._workspace.dataset_names(), [])


if __name__ == "__main__":
    unittest.main()
