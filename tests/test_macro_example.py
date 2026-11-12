"""Execute the shipped folder macro and recover independent synthetic truth."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest

import numpy as np
import pandas as pd

from core import project_io
from core.jobs import JobContext
from core.script_jobs import ScriptRequest, run_script
from core.script_language import Program


EXAMPLE = Path(__file__).resolve().parents[1]/"Test_Data"/"Macro_Example"


class MacroExampleTests(unittest.TestCase):
    def test_shipped_macro_cleans_fits_and_exports_the_synthetic_measurements(self) -> None:
        truth = json.loads((EXAMPLE/"expected_truth.json").read_text(encoding="utf-8"))
        original_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in (EXAMPLE/"input").glob("*.csv")}
        program = Program.read(EXAMPLE/"process_spectra.py")
        with tempfile.TemporaryDirectory() as temporary:
            result = run_script(
                JobContext(Event(), lambda _: None),
                ScriptRequest(program.source, EXAMPLE, Path(temporary), script_name="process_spectra.py"),
            )
            workspace = project_io.load_project(result.folder/"_jasc_result.jasc")
            self.assertEqual(len(workspace.list_datasets()), 18)
            self.assertEqual(len(workspace.list_plots()), 4)
            self.assertEqual(len(list((result.folder/"tables").glob("*.csv"))), 15)
            self.assertEqual(len(list((result.folder/"figures").glob("*.png"))), 4)
            for name, expected in truth["spectra"].items():
                with self.subTest(spectrum=name):
                    raw = workspace.get_dataset(name).frame
                    processed = workspace.get_dataset(name+"_processed").frame
                    self.assertEqual(len(raw), truth["raw_rows_per_file"])
                    self.assertEqual(int(raw.signal.isna().sum()), truth["missing_signal_rows_per_file"])
                    self.assertEqual(int(raw.x.duplicated().sum()), truth["duplicate_rows_per_file"])
                    self.assertEqual(len(processed), truth["processed_rows_per_file"])
                    self.assertTrue(np.all(np.diff(processed.x.to_numpy()) > 0))
                    self.assertTrue(np.isfinite(processed[["corrected", "smoothed"]].to_numpy()).all())
                    np.testing.assert_allclose(processed.corrected, processed.signal-processed.background)
                    row = workspace.get_dataset(name+"_fit_parameters").frame.iloc[0]
                    self.assertEqual(row["weight_mode"], "sigma")
                    self.assertTrue(row["absolute_sigma"])
                    self.assertEqual(row["point_count"], len(processed))
                    self.assertGreater(row["r_squared"], 0.99)
                    self.assertAlmostEqual(row["rmse"], expected["noise_std"], delta=expected["noise_std"]*0.25)
                    for parameter, tolerance in truth["parameter_absolute_tolerances"].items():
                        self.assertAlmostEqual(row["param_"+parameter], expected[parameter], delta=tolerance)
                    curve = workspace.get_dataset(name+"_fit").frame
                    expected_curve = row.param_offset+row.param_amplitude*np.exp(-0.5*((curve.fit_x-row.param_center)/row.param_sigma)**2)
                    np.testing.assert_allclose(curve.fit_y, expected_curve, atol=1e-8)
                    self.assertTrue((curve.fit_lower <= curve.fit_y).all())
                    self.assertTrue((curve.fit_upper >= curve.fit_y).all())
                    exported = pd.read_csv(result.folder/"tables"/(name+"_processed.csv"))
                    pd.testing.assert_frame_equal(exported, processed)
            comparison = workspace.get_plot("Synthetic spectra comparison").state
            self.assertEqual((comparison["rows"], comparison["columns"]), (1, 3))
            self.assertTrue(comparison["match_x"] and comparison["match_y"])
            self.assertEqual(len(set(comparison["plot_ids"])), 3)
            for path in (result.folder/"figures").glob("*.png"):
                self.assertGreater(path.stat().st_size, 2000)
            self.assertTrue((result.folder/"_jasc_run.json").is_file())
        for path in (EXAMPLE/"input").glob("*.csv"):
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original_hashes[path.name])


if __name__ == "__main__":
    unittest.main()
