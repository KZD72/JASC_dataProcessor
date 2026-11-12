"""Exercise shipped feature examples through the actual restricted child runner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import unittest

import numpy as np
import pandas as pd
from PIL import Image

from core import project_io
from core.jobs import JobContext
from core.script_jobs import ScriptRequest, run_script
from core.script_language import Program
from models.plot_types import PLOT_TYPES


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "Test_Data" / "Feature_Examples"


def hashes(directory: Path) -> dict[str, str]:
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()
            and ("input" in path.relative_to(directory).parts or path.name == "expected.json")}


def metric(frame: pd.DataFrame, key: str) -> float:
    return float(frame.loc[frame.metric == key, "value"].iloc[0])


class FeatureExampleTests(unittest.TestCase):
    def test_catalog_and_supplied_inputs_are_complete(self) -> None:
        catalog = json.loads((EXAMPLES/"catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(len(catalog["families"]), 14)
        self.assertEqual(len({family["directory"] for family in catalog["families"]}), 14)
        for family in catalog["families"]:
            directory = EXAMPLES / family["directory"]
            with self.subTest(family=directory.name):
                self.assertTrue((directory/"README.txt").is_file())
                self.assertTrue((directory/"expected.json").is_file())
                self.assertTrue(any((directory/"input").iterdir()))
                self.assertTrue(family["features"])
                if family["macro"]:
                    Program.read(directory/family["macro"])
                else:
                    self.assertEqual(directory.name, "12_Image_Digitization")
        for name in ("linear_curve.png", "log_curve.png", "heatmap.png"):
            with Image.open(EXAMPLES/"12_Image_Digitization"/"input"/name) as image:
                self.assertEqual(image.size, (960, 600))
                image.verify()

    def test_input_regeneration_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary)/"regenerated"
            subprocess.run([sys.executable, "-B", str(EXAMPLES/"generate_data.py"),
                            "--output", str(generated)], cwd=ROOT, check=True,
                           capture_output=True, text=True, timeout=60)
            expected = hashes(EXAMPLES)
            self.assertGreater(len(expected), 40)
            self.assertEqual(hashes(generated), expected)

    def test_every_supplied_macro_recomputes_known_results(self) -> None:
        catalog = json.loads((EXAMPLES/"catalog.json").read_text(encoding="utf-8"))
        before = hashes(EXAMPLES)
        for family in catalog["families"]:
            if family["macro"] is None:
                continue
            with self.subTest(family=family["directory"]), tempfile.TemporaryDirectory() as temporary:
                directory = EXAMPLES/family["directory"]
                program = Program.read(directory/family["macro"])
                result = run_script(JobContext(Event(), lambda _: None),
                                    ScriptRequest(program.source, directory, Path(temporary),
                                                  script_name=family["macro"]))
                workspace = result.workspace
                try:
                    truth = json.loads((directory/"expected.json").read_text(encoding="utf-8"))
                    getattr(self, "_check_" + family["directory"][:2])(workspace, result.folder, truth)
                    self.assertTrue((result.folder/"_jasc_result.jasc").is_file())
                    self.assertEqual(json.loads((result.folder/"_jasc_run.json").read_text())["status"], "completed")
                    for image in result.folder.rglob("*.png"):
                        with Image.open(image) as opened:
                            self.assertGreater(opened.width, 100)
                            self.assertGreater(opened.height, 100)
                            opened.verify()
                finally:
                    for large in workspace.list_large_datasets():
                        large._storage.cleanup()
        self.assertEqual(hashes(EXAMPLES), before, "Replay must not modify supplied inputs or truth")

    def _check_01(self, workspace, folder, truth):
        self.assertEqual(len(workspace.list_datasets()), 9)
        for name in ("Comma", "Tab", "Preamble", "UTF16", "Excel measurements"):
            frame = workspace.get_dataset(name).frame
            self.assertEqual(len(frame), truth["standard_rows"])
            np.testing.assert_allclose(frame.y, frame.x*2 + 1)
        self.assertIn("Experiment", str(workspace.get_dataset("Preamble").worksheet_metadata))
        np.testing.assert_allclose(workspace.get_dataset("Decimal comma").frame.x, truth["decimal_comma_x"])
        self.assertEqual(workspace.get_dataset("ANSI").frame.label.tolist(), ["caf\u00e9", "cr\u00e8me"])
        self.assertEqual(len(list((folder/"tables").glob("*.csv"))), 9)

    def _check_02(self, workspace, folder, truth):
        filled = workspace.get_dataset("Seeds")
        np.testing.assert_allclose(filled.frame.x, truth["filled_x"])
        np.testing.assert_allclose(filled.frame.y, truth["filled_y"])
        self.assertEqual(filled.column_metadata["x"].unit, "s")
        self.assertEqual(filled.column_metadata["y"].long_name, "Signal")
        manual = workspace.get_dataset("Manual").frame
        np.testing.assert_allclose(manual.y, manual.x*2 + 1)
        np.testing.assert_allclose(manual.sequence, [100, 105, 110, 115])
        self.assertEqual(workspace.dataset_names(), ["Seeds", "Manual"])

    def _check_03(self, workspace, folder, truth):
        self.assertEqual(len(workspace.get_dataset("Raw").frame), truth["raw_rows"])
        clean = workspace.get_dataset("Clean").frame
        self.assertEqual(clean.id.tolist(), truth["clean_ids"])
        self.assertAlmostEqual(clean.measurement.sum(), truth["sum"])
        self.assertEqual(workspace.get_dataset("Filtered").frame.id.tolist(), [6, 7, 8])
        self.assertEqual(workspace.get_dataset("Odd rows").frame.id.tolist(), [1, 3, 6, 8])
        means = workspace.get_dataset("Grouped").frame.set_index("group").measurement_mean.to_dict()
        self.assertEqual(means, truth["group_means"])
        self.assertFalse(workspace.get_dataset("Joined").frame.label.isna().any())
        self.assertEqual(len(workspace.get_dataset("Long form").frame), truth["melt_rows"])

    def _check_04(self, workspace, folder, truth):
        frame = workspace.get_dataset("Measurements").frame
        np.testing.assert_allclose(frame.corrected, truth["corrected_slope"]*frame.x + truth["corrected_intercept"])
        np.testing.assert_allclose(frame.squared, frame.corrected**2)
        expected = frame.corrected.copy()
        expected.iloc[[0, 2]] *= -1
        np.testing.assert_allclose(frame.selected, expected)
        self.assertNotIn("selected", workspace.get_dataset("Measurements").formulas)

    def _check_05(self, workspace, folder, truth):
        frame = workspace.get_dataset("Signals").frame
        np.testing.assert_allclose(frame.derivative.iloc[1:-1], 2*frame.time_s.iloc[1:-1], atol=1e-8)
        np.testing.assert_allclose(frame.integral, frame.time_s**3/3, atol=5e-5)
        fft = workspace.get_dataset("FFT").frame
        positive = fft.loc[fft.frequency > 0].nlargest(2, "magnitude").sort_values("frequency")
        np.testing.assert_allclose(positive.frequency, truth["peak_frequencies_hz"])
        np.testing.assert_allclose(positive.magnitude*2/truth["rows"], truth["peak_amplitudes"], atol=1e-9)
        np.testing.assert_allclose(workspace.get_dataset("Inverse FFT").frame.real, frame.signal, atol=1e-10)
        self.assertTrue(np.isfinite(frame[["average", "median", "savgol", "lowess", "lowpass", "reconstructed_smooth"]]).all().all())

    def _check_06(self, workspace, folder, truth):
        line = workspace.get_dataset("Line query").frame
        self.assertEqual(len(line), truth["line_query_rows"])
        np.testing.assert_allclose(line.value_interpolated, 2*line.x + 1)
        plane = workspace.get_dataset("Plane query").frame
        self.assertEqual(len(plane), truth["plane_query_rows"])
        np.testing.assert_allclose(plane.z_interpolated, 2*plane.x + 3*plane.y + 1, atol=1e-10)
        self.assertAlmostEqual(workspace.get_dataset("Volume center").frame.value_interpolated.iloc[0], truth["volume_center"])
        outside = workspace.get_dataset("Outside blank").frame.value_interpolated
        self.assertTrue(outside.iloc[[0, 3]].isna().all())
        np.testing.assert_allclose(outside.iloc[[1, 2]], [1, 9])

    def _check_07(self, workspace, folder, truth):
        single = workspace.get_dataset("Single report").frame
        self.assertEqual(metric(single, "count"), truth["count"])
        self.assertAlmostEqual(metric(single, "mean"), truth["value_mean"])
        regression = workspace.get_dataset("Regression").frame
        self.assertAlmostEqual(metric(regression, "slope"), truth["regression_slope"])
        self.assertAlmostEqual(metric(regression, "intercept"), truth["regression_intercept"])
        self.assertTrue(workspace.get_dataset("Multi report").frame.metric.str.contains("explained_variance").any())
        self.assertEqual(metric(workspace.get_dataset("Group report").frame, "group_count"), truth["group_count"])

    def _check_08(self, workspace, folder, truth):
        for name in ("Linear fit", "Custom fit"):
            frame = workspace.get_dataset(name).frame
            np.testing.assert_allclose(frame.fit_y, 2.5*frame.fit_x + 1.2, atol=1e-7)
        gaussian = workspace.get_dataset("Gaussian fit").frame
        np.testing.assert_allclose(gaussian.fit_y, 8*np.exp(-.5*((gaussian.fit_x - 5)/.7)**2) + .5, atol=1e-7)
        decay = workspace.get_dataset("Decay fit").frame
        np.testing.assert_allclose(decay.fit_y, 6*np.exp(-decay.fit_x/2) + .4, atol=1e-7)
        self.assertTrue((workspace.get_dataset("Fit reports").frame.rmse < 1e-7).all())
        self.assertTrue(workspace.get_dataset("Fit reports").frame.model_name.str.contains("Example line").any())

    def _check_09(self, workspace, folder, truth):
        raw = workspace.get_dataset("Percentile measurements").frame
        self.assertTrue(((raw.y_p16 < raw.y) & (raw.y < raw.y_p84)).all())
        frame = workspace.get_dataset("Percentile fit").frame
        slope, intercept = np.polyfit(frame.fit_x, frame.fit_y, 1)
        self.assertAlmostEqual(slope, truth["slope"], delta=truth["fit_parameter_tolerance"])
        self.assertAlmostEqual(intercept, truth["intercept"], delta=truth["fit_parameter_tolerance"])
        bounds = workspace.get_plot("Asymmetric error bars").state["series"][0]["y_bounds"]
        self.assertEqual(bounds["lower_probability"], truth["probabilities"][0])

    def _check_10(self, workspace, folder, truth):
        parameters = workspace.get_dataset("Single analysis parameters").frame
        centers = sorted(parameters.loc[parameters.parameter == "center", "value"].astype(float))
        np.testing.assert_allclose(centers, truth["single_centers"], atol=1e-5)
        metrics = workspace.get_dataset("Map metrics").frame
        self.assertEqual(len(metrics), truth["map_pixels"])
        self.assertTrue((metrics.status == "success").all())
        mapped = workspace.get_dataset("Map parameters").frame
        centers = mapped.loc[mapped.parameter == "center"]
        np.testing.assert_allclose(centers.value, 240 + 3*centers.X - 2*centers.Y, atol=1e-5)
        sigmas = mapped.loc[mapped.parameter == "sigma", "value"]
        np.testing.assert_allclose(sigmas, truth["map_sigma"], atol=1e-5)
        self.assertEqual(len(workspace.list_spectral_analyses()), 2)

    def _check_11(self, workspace, folder, truth):
        subtypes = {series["plot_type"] for plot in workspace.list_plots() for series in plot.state.get("series", [])}
        self.assertEqual(subtypes, set(PLOT_TYPES))
        grid = workspace.get_dataset("Rendered grid").frame
        self.assertEqual(len(grid), truth["map_rows"])
        np.testing.assert_allclose(grid.z, 4 - grid.x**2 - grid.y**2, atol=1e-10)
        cut = workspace.get_dataset("Horizontal cut").frame
        np.testing.assert_allclose(cut.z, 4 - cut.x**2, atol=1e-10)
        self.assertAlmostEqual(metric(workspace.get_dataset("ROI").frame, "maximum"), 4.)
        self.assertEqual(len(list((folder/"figures").glob("*.png"))), 23)
        synchronized = workspace.get_plot("Synchronized maps").state
        self.assertTrue(synchronized["match_x"] and synchronized["match_y"])

    def _check_13(self, workspace, folder, truth):
        restored = project_io.load_project(folder/"example.jasc")
        pd.testing.assert_frame_equal(restored.get_dataset("Measurements").frame,
                                      workspace.get_dataset("Measurements").frame)
        self.assertEqual(restored.get_plot("Saved plot").state, workspace.get_plot("Saved plot").state)
        for suffix in ("png", "svg", "pdf"):
            self.assertGreater((folder/"figures"/f"measurement.{suffix}").stat().st_size, 1000)

    def _check_14(self, workspace, folder, truth):
        self.assertEqual(workspace.list_large_datasets()[0].row_count, truth["source_rows"])
        window = workspace.get_dataset("Explicit window")
        frame = window.frame.apply(pd.to_numeric)
        self.assertEqual(len(frame), truth["window_rows"])
        self.assertEqual((frame.row_id.iloc[0], frame.row_id.iloc[-1]), (truth["first_id"], truth["last_id"]))
        self.assertAlmostEqual(frame.signal.mean(), truth["signal_mean"])
        self.assertIn("2501-2900", str(window.worksheet_metadata))
        self.assertAlmostEqual(metric(workspace.get_dataset("Window statistics").frame, "mean"), truth["signal_mean"])


if __name__ == "__main__":
    unittest.main()
