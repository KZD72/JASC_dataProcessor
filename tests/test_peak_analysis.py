"""Regression tests for baseline correction and physical-unit peak detection."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtTest import QTest

from math_engine.baseline import BaselineParameters, correct_baseline
from math_engine.calculus import MathOperationError
from math_engine.composite_peak_fit import (
    CompositeFitParameters,
    build_peak_component_spec,
    fit_composite_peaks,
)
from math_engine.peak_detection import PeakDetectionParameters, detect_peaks
from models.fit_functions import fano_peak
from ui.main_window import MainWindow
from ui.peak_analysis_dialog import PeakAnalysisDialog


class BaselineCorrectionTests(unittest.TestCase):
    """Exercise the Qt-independent baseline engine and contracts."""

    def test_arpls_fallback_recovers_sloped_baseline_without_dense_matrices(self) -> None:
        x = np.linspace(100.0, 1000.0, 901)
        expected = 2.0 + 0.003 * x
        peak = 18.0 * np.exp(-0.5 * ((x - 520.0) / 18.0) ** 2)
        result = correct_baseline(
            x,
            expected + peak,
            BaselineParameters(method="arpls", smoothness=1.0e6),
        )
        self.assertEqual(result.baseline.shape, x.shape)
        self.assertLess(float(np.sqrt(np.mean((result.baseline - expected) ** 2))), 0.35)
        self.assertAlmostEqual(result.corrected[np.argmax(peak)], 18.0, delta=0.6)
        self.assertIn("numpy", result.software_versions)

    def test_descending_axis_and_negative_peak_are_restored_to_source_order(self) -> None:
        x = np.linspace(50.0, 0.0, 501)
        baseline = 4.0 + 0.02 * x
        dip = -7.0 * np.exp(-0.5 * ((x - 21.0) / 1.2) ** 2)
        result = correct_baseline(
            x,
            baseline + dip,
            BaselineParameters(method="rubber_band", polarity="negative"),
        )
        self.assertEqual(int(np.nanargmin(result.corrected)), int(np.argmin(dip)))
        self.assertLess(float(np.nanmin(result.corrected)), -6.5)

    def test_manual_pchip_anchors_and_missing_segment_are_preserved(self) -> None:
        x = np.linspace(0.0, 10.0, 101)
        expected = 1.0 + 0.1 * x
        y = expected + 3.0 * np.exp(-0.5 * ((x - 5.0) / 0.4) ** 2)
        y[45:48] = np.nan
        result = correct_baseline(
            x,
            y,
            BaselineParameters(
                method="manual",
                anchors=((0.0, 1.0), (5.0, 1.5), (10.0, 2.0)),
                anchor_interpolation="pchip",
            ),
        )
        self.assertTrue(np.isnan(result.baseline[45:48]).all())
        finite = np.isfinite(y)
        np.testing.assert_allclose(result.baseline[finite], expected[finite], atol=1.0e-10)
        self.assertTrue(any("segments" in warning for warning in result.warnings))

    def test_duplicate_x_is_rejected_clearly(self) -> None:
        with self.assertRaisesRegex(MathOperationError, "duplicate"):
            correct_baseline(
                np.asarray([0.0, 1.0, 1.0, 2.0]),
                np.asarray([0.0, 1.0, 2.0, 0.0]),
            )

    def test_x_only_anchors_resolve_against_each_source_signal(self) -> None:
        x = np.linspace(0.0, 10.0, 101)
        settings = BaselineParameters(
            method="manual",
            anchor_interpolation="linear",
            anchor_source="x_values",
            anchor_x_values=(0.0, 5.0, 10.0),
        )
        first = correct_baseline(x, 1.0 + 0.2 * x, settings)
        second = correct_baseline(x, 8.0 - 0.1 * x, settings)
        np.testing.assert_allclose(first.baseline, 1.0 + 0.2 * x, atol=1.0e-12)
        np.testing.assert_allclose(second.baseline, 8.0 - 0.1 * x, atol=1.0e-12)
        self.assertEqual(first.parameters.anchor_x_values, (0.0, 5.0, 10.0))
        self.assertNotEqual(first.parameters.anchors, second.parameters.anchors)


class PeakDetectionTests(unittest.TestCase):
    """Exercise physical widths, polarity, ranking, and tidy output."""

    def test_detects_gaussian_center_and_fwhm_in_physical_units(self) -> None:
        x = np.linspace(100.0, 900.0, 4001)
        sigma = 6.0
        corrected = 12.0 * np.exp(-0.5 * ((x - 431.5) / sigma) ** 2)
        raw = 5.0 + corrected
        result = detect_peaks(
            x,
            raw,
            corrected,
            PeakDetectionParameters(prominence=1.0, minimum_distance_x=10.0),
            source_sheet="raman",
            channel="Intensity",
        )
        self.assertEqual(len(result.peaks), 1)
        peak = result.peaks[0]
        self.assertAlmostEqual(peak.center, 431.5, delta=0.11)
        self.assertAlmostEqual(peak.fwhm, 2.35482 * sigma, delta=0.15)
        self.assertEqual(peak.source_sheet, "raman")
        self.assertEqual(peak.channel, "Intensity")
        self.assertEqual(result.peak_frame().loc[0, "manual_status"], "automatic")

    def test_mixed_polarity_and_irregular_descending_axis(self) -> None:
        ascending = np.cumsum(np.linspace(0.08, 0.12, 1200))
        corrected = (
            5.0 * np.exp(-0.5 * ((ascending - 30.0) / 0.45) ** 2)
            - 4.0 * np.exp(-0.5 * ((ascending - 75.0) / 0.7) ** 2)
        )
        x = ascending[::-1]
        corrected = corrected[::-1]
        result = detect_peaks(
            x,
            corrected + 2.0,
            corrected,
            PeakDetectionParameters(polarity="both", prominence=0.5),
        )
        self.assertEqual({peak.polarity for peak in result.peaks}, {"positive", "negative"})
        centers = {peak.polarity: peak.center for peak in result.peaks}
        self.assertAlmostEqual(centers["positive"], 30.0, delta=0.15)
        self.assertAlmostEqual(centers["negative"], 75.0, delta=0.15)

    def test_physical_distance_pruning_keeps_stronger_candidate(self) -> None:
        x = np.linspace(0.0, 20.0, 2001)
        corrected = (
            8.0 * np.exp(-0.5 * ((x - 8.0) / 0.15) ** 2)
            + 4.0 * np.exp(-0.5 * ((x - 8.7) / 0.15) ** 2)
        )
        result = detect_peaks(
            x,
            corrected,
            corrected,
            PeakDetectionParameters(prominence=0.5, minimum_distance_x=1.0),
        )
        self.assertEqual(len(result.peaks), 1)
        self.assertAlmostEqual(result.peaks[0].center, 8.0, delta=0.02)

    def test_snr_auto_threshold_uses_robust_noise(self) -> None:
        rng = np.random.default_rng(14)
        x = np.linspace(0.0, 100.0, 2001)
        corrected = rng.normal(0.0, 0.05, len(x))
        corrected += 2.0 * np.exp(-0.5 * ((x - 42.0) / 0.35) ** 2)
        result = detect_peaks(
            x,
            corrected,
            corrected,
            PeakDetectionParameters(prominence=None, snr_threshold=8.0, maximum_count=5),
        )
        self.assertGreater(result.noise_estimate, 0.0)
        self.assertTrue(any(abs(peak.center - 42.0) < 0.1 for peak in result.peaks))


class CompositePeakFitTests(unittest.TestCase):
    """Verify registered models recover overlapping components with one baseline."""

    def test_two_registered_peak_models_fit_one_corrected_signal(self) -> None:
        x = np.linspace(100.0, 500.0, 2001)
        first = 7.0 * np.exp(-0.5 * ((x - 255.0) / 9.0) ** 2)
        second = 4.0 * 11.0**2 / ((x - 292.0) ** 2 + 11.0**2)
        corrected = first + second
        detected = detect_peaks(
            x,
            corrected + 3.0,
            corrected,
            PeakDetectionParameters(prominence=0.5, minimum_distance_x=8.0),
        )
        self.assertEqual(len(detected.peaks), 2)
        specs = [
            build_peak_component_spec(detected.peaks[0], "gaussian", x),
            build_peak_component_spec(detected.peaks[1], "lorentzian", x),
        ]
        result = fit_composite_peaks(
            x,
            corrected + 3.0,
            corrected,
            specs,
            CompositeFitParameters(data_mode="corrected", baseline_model="zero"),
        )
        self.assertTrue(result.converged)
        self.assertGreater(result.r_squared, 0.999)
        self.assertIn("peak_1", result.fit_frame)
        self.assertIn("peak_2", result.fit_frame)
        centers = result.parameter_frame[
            result.parameter_frame["role"] == "center"
        ]["value"].tolist()
        self.assertAlmostEqual(centers[0], 255.0, delta=0.3)
        self.assertAlmostEqual(centers[1], 292.0, delta=0.3)
        first_derived = result.parameter_frame[
            result.parameter_frame["component"] == "peak_1"
        ].set_index("parameter")
        self.assertAlmostEqual(first_derived.loc["fitted_intensity", "value"], 7.0, delta=0.05)
        self.assertAlmostEqual(
            first_derived.loc["fitted_fwhm", "value"], 2.35482 * 9.0, delta=0.25
        )
        self.assertAlmostEqual(first_derived.loc["fitted_asymmetry", "value"], 0.0, delta=0.02)

    def test_raw_mode_uses_one_shared_linear_baseline(self) -> None:
        x = np.linspace(0.0, 100.0, 1001)
        corrected = 5.0 * np.exp(-0.5 * ((x - 44.0) / 3.0) ** 2)
        raw = 2.0 + 0.03 * x + corrected
        detected = detect_peaks(
            x, raw, corrected, PeakDetectionParameters(prominence=1.0)
        )
        spec = build_peak_component_spec(detected.peaks[0], "gaussian", x)
        result = fit_composite_peaks(
            x,
            raw,
            corrected,
            [spec],
            CompositeFitParameters(data_mode="raw", baseline_model="linear"),
        )
        self.assertGreater(result.r_squared, 0.99999)
        baseline_rows = result.parameter_frame[
            result.parameter_frame["component"] == "baseline"
        ]
        self.assertEqual(baseline_rows["parameter"].tolist(), ["slope", "offset"])
        self.assertAlmostEqual(baseline_rows.iloc[0]["value"], 0.03, delta=1.0e-4)

    def test_fano_fit_recovers_resonance_not_detected_extremum(self) -> None:
        x = np.linspace(60.0, 140.0, 1601)
        corrected = fano_peak(x, 3.0, 100.0, 5.0, 2.0, 0.0)
        detected = detect_peaks(
            x,
            corrected,
            corrected,
            PeakDetectionParameters(
                polarity="both",
                prominence=0.05,
                minimum_distance_x=2.0,
            ),
        )
        strongest = max(detected.peaks, key=lambda peak: abs(peak.corrected_height))
        self.assertAlmostEqual(strongest.center, 102.5, delta=0.06)
        result = fit_composite_peaks(
            x,
            corrected,
            corrected,
            [build_peak_component_spec(strongest, "fano_peak", x)],
            CompositeFitParameters(),
        )
        self.assertGreater(result.r_squared, 0.999999)
        rows = result.parameter_frame.set_index("parameter")
        self.assertAlmostEqual(rows.loc["center", "value"], 100.0, delta=0.02)
        self.assertAlmostEqual(rows.loc["gamma", "value"], 5.0, delta=0.02)
        self.assertAlmostEqual(rows.loc["q", "value"], 2.0, delta=0.02)
        self.assertAlmostEqual(rows.loc["fano_peak_position", "value"], 102.5, delta=0.03)
        self.assertAlmostEqual(rows.loc["fano_dip_position", "value"], 90.0, delta=0.03)
        self.assertAlmostEqual(rows.loc["fano_peak_contrast", "value"], 12.0, delta=0.03)
        self.assertAlmostEqual(rows.loc["natural_linewidth", "value"], 10.0, delta=0.03)
        self.assertTrue(any("selected fitting window" in warning for warning in result.warnings))


class PeakAnalysisDialogTests(unittest.TestCase):
    """Verify explicit selection, preview, and manual review behavior."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        x = np.linspace(100.0, 800.0, 1401)
        y = 3.0 + 0.001 * x + 8.0 * np.exp(-0.5 * ((x - 520.0) / 7.0) ** 2)
        self.frame = pd.DataFrame({"Raman Shift": x, "Intensity": y})

    def wait_preview(self, dialog: PeakAnalysisDialog, seconds: float = 15.0) -> None:
        deadline = time.monotonic() + seconds
        while dialog.preview_busy and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertFalse(dialog.preview_busy, "Preview did not finish")

    def test_signal_starts_unselected_and_preview_populates_review_table(self) -> None:
        dialog = PeakAnalysisDialog(
            self.frame,
            "Raman",
            default_x_column="Raman Shift",
        )
        try:
            self.assertEqual(dialog.y_column(), "")
            dialog._y_combo.setCurrentIndex(dialog._y_combo.findData("Intensity"))
            dialog._prominence.setText("1")
            self.assertTrue(dialog.preview_peaks())
            self.wait_preview(dialog)
            self.assertEqual(dialog._peak_table.rowCount(), 1)
            self.assertAlmostEqual(dialog.peak_result().peaks[0].center, 520.0, delta=0.3)

            center_item = dialog._peak_table.item(0, 1)
            center_item.setText("521.25")
            reviewed = dialog.reviewed_peak_frame()
            self.assertAlmostEqual(reviewed.loc[0, "center"], 521.25)
            self.assertEqual(reviewed.loc[0, "manual_status"], "repositioned")
        finally:
            dialog.deleteLater()

    def test_peak_results_default_to_analysis_session_not_worksheets(self) -> None:
        dialog = PeakAnalysisDialog(self.frame, "Raman", default_x_column="Raman Shift")
        try:
            self.assertFalse(dialog.create_signal_output())
            self.assertFalse(dialog.create_peak_output())
            self.assertFalse(dialog.create_fit_output())
            self.assertEqual(dialog.analysis_name(), "Raman Analysis")
        finally:
            dialog.deleteLater()

    def test_baseline_only_uses_same_controls_without_detection_output(self) -> None:
        dialog = PeakAnalysisDialog(
            self.frame,
            "Raman",
            default_x_column="Raman Shift",
            baseline_only=True,
        )
        try:
            dialog._y_combo.setCurrentIndex(dialog._y_combo.findData("Intensity"))
            self.assertTrue(dialog.preview_baseline())
            self.wait_preview(dialog)
            self.assertIsNone(dialog.peak_result())
            self.assertFalse(dialog.create_peak_output())
            self.assertEqual(dialog._tabs.count(), 3)
        finally:
            dialog.deleteLater()

    def test_launching_worksheet_is_preselected_but_source_can_be_changed(self) -> None:
        other = pd.DataFrame({"Wavenumber": [1.0, 2.0, 3.0], "Signal": [2.0, 4.0, 3.0]})
        dialog = PeakAnalysisDialog(
            self.frame,
            "Raman",
            default_x_column="Raman Shift",
            datasets={"Raman": self.frame, "Other spectrum": other},
        )
        try:
            self.assertEqual(dialog.source_dataset_name(), "Raman")
            dialog._source_dataset_combo.setCurrentIndex(
                dialog._source_dataset_combo.findData("Other spectrum")
            )
            self.assertEqual(dialog.source_dataset_name(), "Other spectrum")
            self.assertEqual(dialog.x_column(), "Wavenumber")
            self.assertEqual(dialog.y_column(), "")
            self.assertEqual(dialog._y_combo.findData("Signal"), 2)
        finally:
            dialog.deleteLater()

    def test_detected_peak_accepts_registered_model_and_composite_preview(self) -> None:
        dialog = PeakAnalysisDialog(
            self.frame,
            "Raman",
            default_x_column="Raman Shift",
        )
        try:
            dialog._y_combo.setCurrentIndex(dialog._y_combo.findData("Intensity"))
            dialog._prominence.setText("1")
            self.assertTrue(dialog.preview_peaks())
            self.wait_preview(dialog)
            self.assertEqual(dialog._component_table.rowCount(), 1)
            model_combo = dialog._component_table.cellWidget(0, 2)
            self.assertGreaterEqual(model_combo.findData("lorentzian"), 0)
            model_combo.setCurrentIndex(model_combo.findData("gaussian"))
            self.assertTrue(dialog.preview_composite_fit())
            self.wait_preview(dialog)
            self.assertGreater(dialog.composite_result().r_squared, 0.999)
            self.assertEqual(dialog.component_specs()[0].model_key, "gaussian")
        finally:
            dialog.deleteLater()

    def test_preview_has_zoom_pan_and_reset_navigation(self) -> None:
        dialog = PeakAnalysisDialog(self.frame, "Raman", default_x_column="Raman Shift")
        try:
            actions = {action.text().replace("&", "").casefold() for action in dialog._navigation_toolbar.actions()}
            self.assertIn("home", actions)
            self.assertIn("pan", actions)
            self.assertIn("zoom", actions)
        finally:
            dialog.deleteLater()

    def test_analysis_profile_round_trip_preserves_x_anchors_and_all_fit_controls(self) -> None:
        source = PeakAnalysisDialog(self.frame, "Raman", default_x_column="Raman Shift")
        target = PeakAnalysisDialog(
            self.frame.assign(Intensity=self.frame["Intensity"] + 5.0),
            "Other",
            default_x_column="Raman Shift",
        )
        try:
            source._y_combo.setCurrentIndex(source._y_combo.findData("Intensity"))
            source._baseline_method.setCurrentIndex(source._baseline_method.findData("manual"))
            source._anchor_definition.setCurrentIndex(
                source._anchor_definition.findData("x_values")
            )
            source._anchor_mode.setCurrentIndex(source._anchor_mode.findData("linear"))
            source._anchors.setText("100; 400; 700")
            source._prominence.setText("1")
            source._relative_height.setValue(0.4)
            source._distance.setValue(12.5)
            source._fit_data_mode.setCurrentIndex(source._fit_data_mode.findData("raw"))
            source._shared_fit_baseline.setCurrentIndex(
                source._shared_fit_baseline.findData("quadratic")
            )
            source._fit_loss.setCurrentIndex(source._fit_loss.findData("huber"))
            source._maximum_fit_evaluations.setValue(34567)
            source._center_tolerance.setValue(7.5)
            self.assertTrue(source.preview_peaks())
            self.wait_preview(source)
            model_combo = source._component_table.cellWidget(0, 2)
            model_combo.setCurrentIndex(model_combo.findData("lorentzian"))

            target._y_combo.setCurrentIndex(target._y_combo.findData("Intensity"))
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "parameters.jasc-analysis.json"
                source.save_analysis_profile(path)
                target.load_analysis_profile(path)

            baseline = target.baseline_parameters()
            self.assertEqual(baseline.anchor_source, "x_values")
            self.assertEqual(baseline.anchor_x_values, (100.0, 400.0, 700.0))
            self.assertEqual(target.detection_parameters().relative_height, 0.4)
            self.assertEqual(target.detection_parameters().minimum_distance_x, 12.5)
            fit = target.composite_parameters()
            self.assertEqual(fit.data_mode, "raw")
            self.assertEqual(fit.baseline_model, "quadratic")
            self.assertEqual(fit.loss, "huber")
            self.assertEqual(fit.maximum_evaluations, 34567)
            self.assertEqual(target.center_tolerance(), 7.5)
            self.assertTrue(target.preview_peaks())
            self.wait_preview(target)
            loaded_combo = target._component_table.cellWidget(0, 2)
            self.assertEqual(loaded_combo.currentData(), "lorentzian")
        finally:
            source.deleteLater()
            target.deleteLater()

    def test_map_mode_previews_only_the_selected_xy_pixel(self) -> None:
        shift = np.linspace(100.0, 200.0, 101)
        frames = []
        for x_coordinate, center in ((0.0, 135.0), (1.0, 165.0)):
            intensity = 2.0 + 4.0 * np.exp(-0.5 * ((shift - center) / 3.0) ** 2)
            frames.append(pd.DataFrame({
                "X": x_coordinate,
                "Y": 0.0,
                "Raman Shift": shift,
                "Intensity": intensity,
            }))
        frame = pd.concat(frames, ignore_index=True)
        dialog = PeakAnalysisDialog(frame, "Map", default_x_column="Raman Shift")
        try:
            self.assertEqual(dialog.source_layout(), "map")
            self.assertEqual(dialog.application_scope(), "map")
            self.assertEqual(dialog._preview_pixel.count(), 2)
            dialog._preview_pixel.setCurrentIndex(1)
            dialog._y_combo.setCurrentIndex(dialog._y_combo.findData("Intensity"))
            dialog._baseline_method.setCurrentIndex(dialog._baseline_method.findData("constant"))
            dialog._constant_value.setText("2")
            self.assertTrue(dialog.preview_baseline())
            self.wait_preview(dialog)
            result = dialog.baseline_result()
            self.assertEqual(len(result.x), len(shift))
            self.assertEqual(dialog.preview_coordinates(), {"X": 1.0, "Y": 0.0})
            self.assertAlmostEqual(float(result.x[np.argmax(result.corrected)]), 165.0)
            self.assertEqual(result.provenance["X"], 1.0)
        finally:
            dialog.deleteLater()



class PeakAnalysisMainWindowTests(unittest.TestCase):
    """Verify that accepted analysis results become ordinary persisted worksheets."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_peak_analysis_creates_signal_and_tidy_peak_outputs_with_provenance(self) -> None:
        window = MainWindow()
        try:
            x = np.linspace(100.0, 700.0, 1201)
            corrected = 6.0 * np.exp(-0.5 * ((x - 350.0) / 5.0) ** 2)
            source = window._workspace.add_dataset(
                "Raman", pd.DataFrame({"Raman Shift": x, "Intensity": 2.0 + corrected})
            )
            window._refresh_dataset_list(source.name)
            baseline = correct_baseline(
                x,
                source.frame["Intensity"].to_numpy(),
                BaselineParameters(method="constant", constant_value=2.0),
            )
            peaks = detect_peaks(
                x,
                baseline.raw,
                baseline.corrected,
                PeakDetectionParameters(prominence=1.0),
                source_sheet="Raman",
                channel="Intensity",
            )
            reviewed = peaks.peak_frame()
            reviewed["enabled"] = True

            class FakeDialog:
                Accepted = QDialog.Accepted

                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                def exec(self) -> int:
                    return self.Accepted

                def baseline_result(self):
                    return baseline

                def source_dataset_name(self) -> str:
                    return "Raman"

                def peak_result(self):
                    return peaks

                def composite_result(self):
                    return None

                def application_scope(self) -> str:
                    return "single"

                def reviewed_peak_frame(self):
                    return reviewed

                def x_column(self) -> str:
                    return "Raman Shift"

                def y_column(self) -> str:
                    return "Intensity"

                def create_signal_output(self) -> bool:
                    return True

                def create_peak_output(self) -> bool:
                    return True

                def create_fit_output(self) -> bool:
                    return False

                def result_sheet_name(self) -> str:
                    return "Raman_peak_signal"

                def peak_sheet_name(self) -> str:
                    return "Raman_peaks"

            with patch("ui.main_window.PeakAnalysisDialog", FakeDialog):
                window._run_peak_analysis()

            signal_sheet = window._workspace.get_dataset("Raman_peak_signal")
            peak_sheet = window._workspace.get_dataset("Raman_peaks")
            self.assertIn("Intensity_baseline", signal_sheet.frame.columns)
            self.assertIn("Intensity_corrected", signal_sheet.frame.columns)
            self.assertEqual(len(peak_sheet.frame), 1)
            self.assertIn("Baseline parameters", signal_sheet.worksheet_metadata.import_details)
            self.assertIn("Peak detection parameters", peak_sheet.worksheet_metadata.import_details)
            self.assertEqual(
                peak_sheet.worksheet_metadata.import_details["Reviewed peak count"], "1"
            )
        finally:
            window.close()

    def test_raman_map_fit_groups_pixels_and_writes_coordinate_keyed_parameters(self) -> None:
        window = MainWindow()
        try:
            shift = np.linspace(100.0, 400.0, 601)
            frames = []
            for x_coordinate, center in ((0.0, 245.0), (1.0, 248.0)):
                intensity = 2.0 + 5.0 * np.exp(-0.5 * ((shift - center) / 6.0) ** 2)
                frames.append(pd.DataFrame({
                    "X": x_coordinate,
                    "Y": 0.0,
                    "Raman Shift": shift,
                    "Intensity": intensity,
                }))
            dataset = window._workspace.add_dataset(
                "Map", pd.concat(frames, ignore_index=True), copy_frame=False
            )
            reference = frames[0]
            baseline = correct_baseline(
                shift,
                reference["Intensity"].to_numpy(),
                BaselineParameters(method="constant", constant_value=2.0),
            )
            detection_parameters = PeakDetectionParameters(prominence=1.0)
            detection = detect_peaks(
                shift, baseline.raw, baseline.corrected, detection_parameters
            )
            template = build_peak_component_spec(detection.peaks[0], "gaussian", shift)

            class FakeMapDialog:
                def application_scope(self): return "map"
                def component_specs(self): return [template]
                def baseline_parameters(self): return BaselineParameters(method="constant", constant_value=2.0)
                def detection_parameters(self): return detection_parameters
                def composite_parameters(self): return CompositeFitParameters()
                def analysis_range(self): return None
                def x_column(self): return "Raman Shift"
                def y_column(self): return "Intensity"
                def center_tolerance(self): return 10.0
                def create_signal_output(self): return False
                def create_peak_output(self): return False
                def create_fit_output(self): return True
                def fit_sheet_name(self): return "Map_peak_fit"
                def fit_parameter_sheet_name(self): return "Map_peak_parameters"

            window._run_peak_analysis_batch_or_map(dataset, FakeMapDialog(), {})
            deadline = time.monotonic() + 10.0
            while window._jobs.is_running and time.monotonic() < deadline:
                QTest.qWait(5)
            self.assertFalse(window._jobs.is_running)
            parameters = window._workspace.get_dataset("Map_peak_parameters").frame
            summary = parameters[parameters["record_type"] == "fit_summary"]
            self.assertEqual(len(summary), 2)
            self.assertEqual(set(summary["X"]), {0.0, 1.0})
            self.assertTrue((summary["status"] == "success").all())
            center_rows = parameters[
                (parameters["record_type"] == "parameter")
                & (parameters["role"] == "center")
            ]
            self.assertEqual(len(center_rows), 2)
            parameter_maps = window._workspace.get_dataset(
                "Map_peak_parameters_maps"
            ).frame
            self.assertEqual(len(parameter_maps), 2)
            self.assertEqual(len(parameter_maps[["X", "Y"]].drop_duplicates()), 2)
            expected_columns = {
                "peak_1_intensity",
                "peak_1_area",
                "peak_1_position",
                "peak_1_fwhm",
                "peak_1_asymmetry",
                "peak_1_position_standard_error",
                "peak_1_parameter_amplitude_standard_error",
                "fit_r_squared",
                "fit_rmse",
                "fit_mae",
                "noise_estimate",
            }
            self.assertTrue(expected_columns.issubset(parameter_maps.columns))
            np.testing.assert_allclose(
                parameter_maps.sort_values("X")["peak_1_position"],
                [245.0, 248.0],
                atol=0.1,
            )
            np.testing.assert_allclose(parameter_maps["peak_1_intensity"], 5.0, atol=0.05)
            self.assertTrue(
                np.isfinite(parameter_maps["peak_1_position_standard_error"]).all()
            )
            self.assertTrue((parameter_maps["fit_success"] == 1.0).all())
            analysis = window._workspace.get_spectral_analysis("Map Raman Analysis")
            self.assertEqual(analysis.analysis_kind, "raman_map")
            self.assertEqual(analysis.coordinate_columns, ("X", "Y"))
            self.assertEqual(len(analysis.metrics_frame), 2)
            self.assertIn("residual", analysis.curves_frame)
        finally:
            window.close()

    def test_baseline_only_map_applies_reviewed_parameters_to_every_pixel(self) -> None:
        window = MainWindow()
        try:
            shift = np.linspace(100.0, 220.0, 121)
            frames = []
            for x_coordinate, center in ((0.0, 145.0), (1.0, 175.0)):
                intensity = 3.0 + 5.0 * np.exp(-0.5 * ((shift - center) / 4.0) ** 2)
                frames.append(pd.DataFrame({
                    "X": x_coordinate,
                    "Y": 0.0,
                    "Raman Shift": shift,
                    "Intensity": intensity,
                }))
            dataset = window._workspace.add_dataset(
                "Baseline Map", pd.concat(frames, ignore_index=True), copy_frame=False
            )
            dialog = PeakAnalysisDialog(
                dataset.frame,
                dataset.name,
                default_x_column="Raman Shift",
                baseline_only=True,
            )
            try:
                dialog._y_combo.setCurrentIndex(dialog._y_combo.findData("Intensity"))
                dialog._baseline_method.setCurrentIndex(
                    dialog._baseline_method.findData("constant")
                )
                dialog._constant_value.setText("3")
                window._run_baseline_map(dataset, dialog, {})
            finally:
                dialog.deleteLater()

            deadline = time.monotonic() + 10.0
            while window._jobs.is_running and time.monotonic() < deadline:
                QTest.qWait(5)
            self.assertFalse(window._jobs.is_running)

            output = window._workspace.get_dataset("Baseline Map_peak_signal")
            self.assertEqual(len(output.frame), 2 * len(shift))
            self.assertEqual(set(output.frame["X"]), {0.0, 1.0})
            np.testing.assert_allclose(output.frame["Intensity_baseline"], 3.0)
            maxima = output.frame.groupby(["X", "Y"])["Intensity_corrected"].max()
            np.testing.assert_allclose(maxima.to_numpy(), 5.0, atol=1.0e-12)
            self.assertEqual(
                output.worksheet_metadata.import_details["Successful pixels"], "2"
            )
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
