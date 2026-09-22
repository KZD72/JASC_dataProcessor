"""Numerical and offscreen-GUI tests for raster figure extraction."""

from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core.color_scale import ColorScaleCalibration
from core import project_io
from core.workspace import Workspace
from ui.dialogs import (
    ColorPlotDigitizerDialog,
    FigureDigitizerDialog,
    FigureExtractionModeDialog,
    FigureExtractionResult,
)
from ui.main_window import MainWindow


class ColorScaleCalibrationTests(unittest.TestCase):
    """Exercise colour matching independently of the Qt workflow."""

    def test_linear_palette_maps_midpoint_and_reports_confidence(self) -> None:
        palette = np.asarray([[0, 0, 0], [128, 128, 128], [255, 255, 255]], dtype=float)
        match = ColorScaleCalibration(palette, 0.0, 100.0).match_rgb([128, 128, 128])

        self.assertAlmostEqual(match.value, 50.0, places=6)
        self.assertAlmostEqual(match.confidence, 1.0, places=6)
        self.assertTrue(match.valid)
        self.assertFalse(match.ambiguous)

    def test_log_palette_interpolates_values_in_log_space(self) -> None:
        model = ColorScaleCalibration(
            np.asarray([[0, 0, 0], [255, 255, 255]], dtype=float),
            1.0,
            100.0,
            scale="log",
        )

        self.assertAlmostEqual(model.value_at(0.5), 10.0, places=8)

    def test_repeated_palette_colours_are_flagged_as_ambiguous(self) -> None:
        palette = np.asarray(
            [[0, 0, 0], [255, 0, 0], [0, 0, 0], [255, 0, 0]],
            dtype=float,
        )
        match = ColorScaleCalibration(palette, 0.0, 1.0).match_rgb([128, 0, 0])

        self.assertTrue(match.ambiguous)
        self.assertFalse(match.valid)


class FigureDigitizerGuiTests(unittest.TestCase):
    """Exercise workflow selection, full-image bounds, and X/Y/Z probes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _synthetic_colourplot(path: str) -> None:
        image = QImage(120, 80, QImage.Format_RGB888)
        image.fill(QColor("white"))
        for y in range(10, 71):
            level = int(round(255.0 * (70 - y) / 60.0))
            colour = QColor(level, level, level)
            for x in range(104, 108):
                image.setPixelColor(x, y, colour)
        image.setPixelColor(50, 40, QColor(128, 128, 128))
        if not image.save(path):
            raise RuntimeError("Could not save synthetic colour-plot fixture.")

    def test_mode_chooser_defaults_to_xy_and_exposes_colourplot(self) -> None:
        dialog = FigureExtractionModeDialog()
        self.assertEqual(dialog.extraction_mode(), "xy")
        dialog._colorplot_radio.setChecked(True)
        self.assertEqual(dialog.extraction_mode(), "colorplot")
        dialog.close()

    def test_xy_scan_bounds_are_not_cropped_by_calibration_references(self) -> None:
        dialog = FigureDigitizerDialog()
        dialog._image = QImage(200, 120, QImage.Format_RGB888)
        dialog._calibration_pixels = {
            "x1": (40.0, 100.0),
            "x2": (160.0, 100.0),
            "y1": (40.0, 95.0),
            "y2": (40.0, 25.0),
        }

        self.assertEqual(dialog._plot_bounds(), (0, 199, 0, 119))
        dialog.close()

    def test_calibration_tab_arms_scale_picker_when_correction_is_skipped(self) -> None:
        dialog = FigureDigitizerDialog()
        image = QImage(100, 80, QImage.Format_RGB888)
        image.fill(QColor("white"))
        dialog._set_working_image(image)
        dialog._set_click_target("warp_tl")

        dialog._controls_tabs.setCurrentWidget(dialog._calibration_tab)

        self.assertEqual(dialog._click_target_combo.currentData(), "x1")
        self.assertIn("X axis point 1", dialog._tool_mode_label.text())

        dialog._calibration_pixels["x1"] = (10.0, 70.0)
        dialog._controls_tabs.setCurrentWidget(dialog._correction_tab)
        dialog._controls_tabs.setCurrentWidget(dialog._calibration_tab)
        self.assertEqual(dialog._click_target_combo.currentData(), "x2")
        dialog.close()

    def test_multi_curve_session_preserves_image_and_axis_calibration(self) -> None:
        dialog = FigureDigitizerDialog()
        image = QImage(100, 80, QImage.Format_RGB888)
        image.fill(QColor("white"))
        dialog._image_path = "multi_curve.png"
        dialog._set_working_image(image)
        dialog._calibration_pixels = {
            "x1": (10.0, 70.0),
            "x2": (90.0, 70.0),
            "y1": (10.0, 70.0),
            "y2": (10.0, 10.0),
        }
        dialog._x1_value_edit.setText("0")
        dialog._x2_value_edit.setText("80")
        dialog._y1_value_edit.setText("0")
        dialog._y2_value_edit.setText("60")
        calibration = dict(dialog._calibration_pixels)

        dialog._dataset_name_edit.setText("red curve")
        dialog._manual_points = [{"pixel_x": 20.0, "pixel_y": 40.0}]
        dialog._roi_points = [(20.0, 40.0, 5.0)]
        dialog._save_current_extraction_and_start_new()

        self.assertEqual(dialog._calibration_pixels, calibration)
        self.assertFalse(dialog._manual_points)
        self.assertFalse(dialog._roi_points)
        self.assertEqual(dialog._dataset_name_edit.text(), "red curve Curve 2")

        dialog._dataset_name_edit.setText("blue curve")
        dialog._manual_points = [{"pixel_x": 60.0, "pixel_y": 25.0}]
        results = dialog.extraction_results()
        self.assertEqual([result.dataset_name for result in results], ["red curve", "blue curve"])
        self.assertEqual([len(result.rows) for result in results], [1, 1])
        self.assertEqual(results[0].calibration_summary, results[1].calibration_summary)
        dialog.close()

    def test_create_dataset_and_continue_emits_result_and_preserves_calibration(self) -> None:
        dialog = FigureDigitizerDialog()
        image = QImage(100, 80, QImage.Format_RGB888)
        image.fill(QColor("white"))
        dialog._image_path = "embedded_source.png"
        dialog._original_image = image.copy()
        dialog._set_working_image(image)
        dialog._calibration_pixels = {
            "x1": (10.0, 70.0),
            "x2": (90.0, 70.0),
            "y1": (10.0, 70.0),
            "y2": (10.0, 10.0),
        }
        dialog._x1_value_edit.setText("0")
        dialog._x2_value_edit.setText("80")
        dialog._y1_value_edit.setText("0")
        dialog._y2_value_edit.setText("60")
        dialog._dataset_name_edit.setText("first curve")
        dialog._manual_points = [{"pixel_x": 20.0, "pixel_y": 40.0}]
        calibration = dict(dialog._calibration_pixels)
        created: list[FigureExtractionResult] = []

        def accept_creation(request: object) -> None:
            request.imported = True
            created.append(request.result)

        dialog.extraction_created.connect(accept_creation)

        dialog._create_dataset_and_continue()

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].dataset_name, "first curve")
        self.assertIsNotNone(created[0].figure_session)
        self.assertTrue(created[0].figure_session.image_png)
        self.assertEqual(dialog._calibration_pixels, calibration)
        self.assertFalse(dialog._manual_points)
        self.assertEqual(dialog._dataset_name_edit.text(), "first curve Curve 2")

        resumed = FigureDigitizerDialog(session=created[0].figure_session)
        self.assertFalse(resumed._image.isNull())
        self.assertEqual(resumed._calibration_pixels, calibration)
        self.assertEqual(resumed._x2_value_edit.text(), "80")
        resumed.close()
        dialog.close()

    def test_failed_live_dataset_import_keeps_current_extraction(self) -> None:
        dialog = FigureDigitizerDialog()
        image = QImage(30, 30, QImage.Format_RGB888)
        image.fill(QColor("white"))
        dialog._set_working_image(image)
        dialog._calibration_pixels = {
            "x1": (2.0, 27.0),
            "x2": (27.0, 27.0),
            "y1": (2.0, 27.0),
            "y2": (2.0, 2.0),
        }
        dialog._manual_points = [{"pixel_x": 10.0, "pixel_y": 10.0}]

        def reject_creation(request: object) -> None:
            request.error = "Import was declined for testing."

        dialog.extraction_created.connect(reject_creation)
        with patch.object(QMessageBox, "warning") as warning:
            dialog._create_dataset_and_continue()

        self.assertEqual(len(dialog._manual_points), 1)
        warning.assert_called_once()
        self.assertIn("declined", warning.call_args.args[2])
        dialog.close()

    def test_figure_session_round_trips_once_for_multiple_datasets(self) -> None:
        dialog = FigureDigitizerDialog()
        image = QImage(20, 20, QImage.Format_RGB888)
        image.fill(QColor("white"))
        dialog._set_working_image(image)
        dialog._calibration_pixels = {
            "x1": (1.0, 18.0),
            "x2": (18.0, 18.0),
            "y1": (1.0, 18.0),
            "y2": (1.0, 1.0),
        }
        session = dialog.figure_session()
        self.assertIsNotNone(session)

        workspace = Workspace()
        first = workspace.add_dataset("curve one", pd.DataFrame({"x": [1.0], "y": [2.0]}))
        second = workspace.add_dataset("curve two", pd.DataFrame({"x": [3.0], "y": [4.0]}))
        first.figure_session = session
        second.figure_session = session

        with tempfile.TemporaryDirectory() as folder:
            project_path = os.path.join(folder, "figure_session.jasc")
            project_io.save_project(workspace, project_path)
            with zipfile.ZipFile(project_path, "r") as archive:
                embedded_images = [
                    name for name in archive.namelist() if name.startswith("figure_sessions/")
                ]
            loaded = project_io.load_project(project_path)

        self.assertEqual(len(embedded_images), 1)
        loaded_first = loaded.get_dataset("curve one")
        loaded_second = loaded.get_dataset("curve two")
        self.assertIsNotNone(loaded_first.figure_session)
        self.assertIs(loaded_first.figure_session, loaded_second.figure_session)
        self.assertEqual(
            loaded_first.figure_session.state["calibration_pixels"],
            session.state["calibration_pixels"],
        )
        dialog.close()

    def test_main_window_creates_live_dataset_without_closing_digitizer(self) -> None:
        window = MainWindow()
        dialog = FigureDigitizerDialog(parent=window)
        image = QImage(30, 30, QImage.Format_RGB888)
        image.fill(QColor("white"))
        dialog._image_path = "live.png"
        dialog._original_image = image.copy()
        dialog._set_working_image(image)
        dialog._calibration_pixels = {
            "x1": (2.0, 27.0),
            "x2": (27.0, 27.0),
            "y1": (2.0, 27.0),
            "y2": (2.0, 2.0),
        }
        dialog._dataset_name_edit.setText("live curve")
        dialog._manual_points = [{"pixel_x": 10.0, "pixel_y": 10.0}]

        def create_then_keep_dialog_session() -> int:
            dialog._create_dataset_and_continue()
            self.assertFalse(dialog._manual_points)
            self.assertFalse(dialog._image.isNull())
            return QDialog.Rejected

        with (
            patch.object(dialog, "exec", side_effect=create_then_keep_dialog_session),
            patch.object(window, "_confirm_large_dataset", return_value=True),
        ):
            window._run_figure_digitizer_dialog(dialog, "xy")

        dataset = window._workspace.get_dataset("live curve")
        self.assertEqual(len(dataset.frame), 1)
        self.assertIsNotNone(dataset.figure_session)
        self.assertEqual(dataset.figure_session.source_path, "live.png")
        window.close()

    def test_main_window_imports_every_saved_figure_curve(self) -> None:
        class FakeModeDialog:
            def __init__(self, _parent: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def extraction_mode() -> str:
                return "xy"

        class FakeDigitizerDialog:
            def __init__(self, _path: str, _parent: object) -> None:
                pass

            @staticmethod
            def image_file_filter() -> str:
                return "Images (*)"

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def extraction_results() -> list[FigureExtractionResult]:
                return [
                    FigureExtractionResult(
                        dataset_name="curve one",
                        rows=({"x": 1.0, "y": 2.0, "source_image": "figure.png"},),
                        source_path="figure.png",
                        extraction_kind="xy",
                        calibration_summary="shared calibration",
                        extraction_summary="manual curve one",
                    ),
                    FigureExtractionResult(
                        dataset_name="curve two",
                        rows=({"x": 3.0, "y": 4.0, "source_image": "figure.png"},),
                        source_path="figure.png",
                        extraction_kind="xy",
                        calibration_summary="shared calibration",
                        extraction_summary="manual curve two",
                    ),
                ]

        window = MainWindow()
        with (
            patch("ui.main_window.FigureExtractionModeDialog", FakeModeDialog),
            patch("ui.main_window.FigureDigitizerDialog", FakeDigitizerDialog),
            patch("ui.main_window.QFileDialog.getOpenFileName", return_value=("figure.png", "")),
            patch.object(window, "_confirm_large_dataset", return_value=True),
        ):
            window._import_from_figure()

        self.assertEqual(window._workspace.get_dataset("curve one").frame.iloc[0].tolist(), [1.0, 2.0, "figure.png"])
        self.assertEqual(window._workspace.get_dataset("curve two").frame.iloc[0].tolist(), [3.0, 4.0, "figure.png"])
        self.assertIn(
            "manual curve one",
            window._workspace.get_dataset("curve one").metadata_for_column("x").comment,
        )
        window.close()

    def test_colourplot_probe_returns_calibrated_xyz_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image_path = os.path.join(folder, "colourplot.png")
            self._synthetic_colourplot(image_path)
            dialog = ColorPlotDigitizerDialog(image_path)
            dialog._calibration_pixels = {
                "x1": (10.0, 70.0),
                "x2": (90.0, 70.0),
                "y1": (10.0, 70.0),
                "y2": (10.0, 10.0),
            }
            dialog._x1_value_edit.setText("0")
            dialog._x2_value_edit.setText("80")
            dialog._y1_value_edit.setText("0")
            dialog._y2_value_edit.setText("60")
            dialog._colorbar_pixels = {"low": (105.0, 70.0), "high": (105.0, 10.0)}
            dialog._color_low_value_edit.setText("0")
            dialog._color_high_value_edit.setText("100")
            dialog._probe_patch_radius_spin.setValue(0)
            self.assertTrue(dialog._rebuild_color_scale(show_errors=False))

            dialog._color_probes.append((50.0, 40.0))
            row = dialog.extracted_rows()[0]

            self.assertAlmostEqual(float(row["x"]), 40.0, places=6)
            self.assertAlmostEqual(float(row["y"]), 30.0, places=6)
            self.assertAlmostEqual(float(row["z"]), 50.0, delta=1.0)
            self.assertTrue(row["color_valid"])
            self.assertGreater(float(row["color_confidence"]), 0.95)
            self.assertIn("compression", dialog._DISCLAIMER.lower())
            dialog.close()

    def test_colourplot_session_restores_palette_endpoints_and_settings(self) -> None:
        dialog = ColorPlotDigitizerDialog()
        image = QImage(40, 30, QImage.Format_RGB888)
        image.fill(QColor("white"))
        dialog._set_working_image(image)
        dialog._calibration_pixels = {
            "x1": (2.0, 27.0),
            "x2": (30.0, 27.0),
            "y1": (2.0, 27.0),
            "y2": (2.0, 2.0),
        }
        dialog._colorbar_pixels = {"low": (35.0, 27.0), "high": (35.0, 2.0)}
        dialog._color_low_value_edit.setText("1")
        dialog._color_high_value_edit.setText("100")
        dialog._set_combo_data(dialog._color_scale_combo, "log")
        dialog._probe_patch_radius_spin.setValue(3)
        session = dialog.figure_session()
        self.assertIsNotNone(session)

        resumed = ColorPlotDigitizerDialog(session=session)

        self.assertEqual(resumed._colorbar_pixels, dialog._colorbar_pixels)
        self.assertEqual(resumed._color_low_value_edit.text(), "1")
        self.assertEqual(resumed._color_high_value_edit.text(), "100")
        self.assertEqual(resumed._color_scale_combo.currentData(), "log")
        self.assertEqual(resumed._probe_patch_radius_spin.value(), 3)
        resumed.close()
        dialog.close()

    def test_colourplot_import_assigns_xyz_metadata_and_keeps_diagnostics(self) -> None:
        class FakeModeDialog:
            def __init__(self, _parent: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def extraction_mode() -> str:
                return "colorplot"

        class FakeColorDialog:
            def __init__(self, _path: str, _parent: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def extracted_rows() -> list[dict[str, object]]:
                return [
                    {
                        "x": 1.0,
                        "y": 2.0,
                        "z": 3.0,
                        "pixel_x": 10.0,
                        "pixel_y": 20.0,
                        "red": 1,
                        "green": 2,
                        "blue": 3,
                        "color_confidence": 0.9,
                        "color_ambiguous": False,
                        "color_valid": True,
                        "source_image": "figure.png",
                    }
                ]

            @staticmethod
            def dataset_name() -> str:
                return "colour_data"

            @staticmethod
            def source_path() -> str:
                return "figure.png"

            @staticmethod
            def calibration_summary() -> str:
                return "calibrated"

            @staticmethod
            def extraction_summary() -> str:
                return "colour probes with compression disclaimer"

        window = MainWindow()
        with (
            patch("ui.main_window.FigureExtractionModeDialog", FakeModeDialog),
            patch("ui.main_window.ColorPlotDigitizerDialog", FakeColorDialog),
            patch("ui.main_window.QFileDialog.getOpenFileName", return_value=("figure.png", "")),
            patch.object(window, "_confirm_large_dataset", return_value=True),
        ):
            window._import_from_figure()

        dataset = window._workspace.get_dataset("colour_data")
        self.assertEqual(dataset.metadata_for_column("x").role, "x")
        self.assertEqual(dataset.metadata_for_column("y").role, "y")
        self.assertEqual(dataset.metadata_for_column("z").role, "z")
        self.assertIn("compression", dataset.metadata_for_column("z").comment.lower())
        self.assertIn("color_confidence", dataset.frame.columns)
        window.close()


if __name__ == "__main__":
    unittest.main()
