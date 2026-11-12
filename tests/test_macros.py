"""Macro dependency, numerical, import, failure, cancellation, and export contracts."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from core.jobs import JobContext
from core.macro_jobs import MacroRun, MacroSource, export_macro_tables, folder_sources, preflight_macro, run_macro
from core.macro_recording import MacroRecorder
from core.workspace import ColumnMetadata, Dataset
from math_engine.curve_fitting import fit_curve
from math_engine.smoothing import SmoothingParameters, smooth_column
from models.macro import ColumnRef, Macro, MacroStep
from models.uncertainty import PercentileBounds


def data(name="sample", slope=2.):
    x = np.linspace(1, 10, 51)
    return Dataset(name, pd.DataFrame({"x": x, "y": slope*x+3+.03*np.sin(x*6)}))


def macro():
    settings = {"model_key": "linear", "method": "trf", "initial_parameters": [1., 0.],
                "lower_bounds": [None, None], "upper_bounds": [None, None], "fixed_parameters": [False, False],
                "fit_points": 50, "include_confidence_band": True}
    return Macro("Smooth and fit", [
        MacroStep("smooth1", "smooth", {"method": "savgol", "parameters": asdict(SmoothingParameters()), "output_column": "smoothed"},
                  {"x": ColumnRef("source", "x"), "y": ColumnRef("source", "y")}),
        MacroStep("fit1", "fit", settings, {"x": ColumnRef("smooth1", "x"), "y": ColumnRef("smooth1", "y")}),
        MacroStep("plot1", "plot", {"name": "Fit", "state": {"version": 5, "series": [
            {"x_dataset": "smooth1", "x_column": "x", "y_dataset": "smooth1", "y_column": "y", "plot_type": "scatter"},
            {"x_dataset": "fit1", "x_column": "fit_x", "y_dataset": "fit1", "y_column": "fit_y", "plot_type": "line"}], "settings": {}}})])


def context(event=None, report=lambda _progress: None):
    return JobContext(event or Event(), report)


class MacroTests(unittest.TestCase):
    def test_file_changed_after_preview_is_not_processed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"input.csv"
            data().frame.to_csv(path, index=False)
            source = MacroSource(str(path), path.stem, path=path)
            self.assertEqual(preflight_macro(context(), macro(), [source])[0]["status"], "ready")
            data(slope=4.).frame.to_csv(path, index=False)
            result = run_macro(context(), macro(), [source], MacroRun())
            self.assertFalse(result.outputs)
            self.assertIn("changed since", result.rows[0]["details"])

    def test_raw_asymmetric_fit_keeps_bounds_and_likelihood_provenance(self):
        routine = macro()
        del routine.steps[0]
        step = routine.steps[0]
        step.inputs = {"x": ColumnRef("source", "x"), "y": ColumnRef("source", "y"),
                       "y_lower": ColumnRef("source", "yl"), "y_upper": ColumnRef("source", "yh")}
        step.settings["method"] = "percentile"
        step.settings["y_bounds"] = PercentileBounds("yl", "yh").to_state()
        routine.steps = [step]
        source = data()
        source.frame["yl"], source.frame["yh"] = source.frame.y-.1, source.frame.y+.3
        result = run_macro(context(), routine, [MacroSource("one", "one", source)], MacroRun())
        self.assertEqual(len(result.outputs), 1)
        report = dict(result.outputs[0].tables["fit1"].worksheet_metadata.fields)["Fit report"]
        self.assertIn("quantile_normal", report)
        self.assertIn("16%", report)
        self.assertIn("Hessian", report)

    def test_json_roundtrip_and_unknown_commands_rejected(self):
        routine = macro()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"routine.json"
            routine.save(path)
            self.assertEqual(Macro.load(path).to_state(), routine.to_state())
        for change in (lambda state: state.update(version=99),
                       lambda state: state["steps"][0].update(operation="exec"),
                       lambda state: state["steps"][1]["inputs"]["x"].update(table="future")):
            state = routine.to_state()
            change(state)
            with self.assertRaises(ValueError):
                Macro.from_state(state)

    def test_dependency_removal_and_reordering_rejected(self):
        routine = macro()
        routine.steps[0], routine.steps[1] = routine.steps[1], routine.steps[0]
        with self.assertRaisesRegex(ValueError, "missing or later"):
            routine.validate()
        routine = macro()
        del routine.steps[0]
        with self.assertRaises(ValueError):
            routine.validate()

    def test_replay_matches_existing_engines_and_preserves_source(self):
        source = data()
        original = deepcopy(source.frame)
        result = run_macro(context(), macro(), [MacroSource("one", "one", source)], MacroRun())
        self.assertEqual(len(result.outputs), 1)
        direct = source.frame.copy()
        smooth_column(direct, "x", "y", "savgol", "s", SmoothingParameters())
        fit = fit_curve(direct, "x", "s", "linear", "trf", [1., 0.], fit_points=50)
        np.testing.assert_allclose(result.outputs[0].tables["smooth1"].frame.y, direct.s)
        np.testing.assert_allclose(result.outputs[0].tables["fit1"].frame.fit_y, fit.fit_frame.fit_y)
        pd.testing.assert_frame_equal(original, source.frame)
        self.assertIn("a", result.rows[1])
        self.assertTrue(result.outputs[0].plots)

    def test_folder_and_workspace_inputs_with_skipped_invalid_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data().frame.to_csv(root/"good.csv", index=False)
            pd.DataFrame({"other": [1, 2]}).to_csv(root/"bad.csv", index=False)
            (root/"ignored.png").write_bytes(b"image")
            sub = root/"sub"
            sub.mkdir()
            data().frame.to_csv(sub/"nested.csv", index=False)
            exported = root/"jasc_macro_run_old"
            exported.mkdir()
            data().frame.to_csv(exported/"generated.csv", index=False)
            self.assertEqual(len(folder_sources(root)), 2)
            sources = folder_sources(root, True)+[MacroSource("workspace", "workspace", data(slope=4.))]
            preview = preflight_macro(context(), macro(), sources)
            self.assertEqual([row["status"] for row in preview].count("ready"), 3)
            ready = {row["key"] for row in preview if row["status"] == "ready"}
            result = run_macro(context(), macro(), [item for item in sources if item.key in ready], MacroRun())
            self.assertEqual(len(result.outputs), 3)
            self.assertTrue(all(row["status"] == "ok" for row in result.rows))

    def test_numeric_text_and_metadata_are_preflight_failures(self):
        bad = data()
        bad.frame["y"] = bad.frame.y.astype(object)
        bad.frame.loc[2, "y"] = "invalid"
        marked = data("marked")
        marked.column_metadata["y"] = ColumnMetadata(value_type="text")
        result = preflight_macro(context(), macro(), [MacroSource("bad", "bad", bad), MacroSource("marked", "marked", marked)])
        self.assertTrue(all(row["status"] == "skipped" for row in result))

    def test_failure_discards_all_steps_for_only_that_source(self):
        good, bad = data(), data("bad")
        bad.frame = bad.frame.iloc[:2]
        result = run_macro(context(), macro(), [MacroSource("bad", "bad", bad), MacroSource("good", "good", good)], MacroRun())
        self.assertEqual(len(result.outputs), 1)
        self.assertEqual(result.outputs[0].source.key, "good")
        self.assertEqual(result.rows[0]["status"], "failed")

    def test_cancellation_keeps_completed_sources_and_discards_current(self):
        event = Event()
        calls = 0
        from core import macro_jobs
        original = macro_jobs.smooth_column
        def cancel_during_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = original(*args, **kwargs)
            if calls == 2:
                event.set()
            return result
        with patch.object(macro_jobs, "smooth_column", cancel_during_second):
            result = run_macro(context(event), macro(), [MacroSource(str(i), str(i), data()) for i in range(3)], MacroRun())
        self.assertTrue(result.cancelled)
        self.assertEqual(len(result.outputs), 1)
        self.assertEqual(sum(row["status"] == "cancelled" for row in result.rows), 2)

    def test_derived_values_cannot_reuse_raw_measurement_errors(self):
        routine = macro()
        routine.steps[1].inputs["weight"] = ColumnRef("source", "y")
        rows = preflight_macro(context(), routine, [MacroSource("one", "one", data())])
        self.assertIn("propagation", rows[0]["details"])

    def test_recorder_maps_derived_output_and_detects_unrecorded_mutation(self):
        source = data()
        recorder = MacroRecorder("recorded", source)
        recorder.check(source)
        smooth_column(source.frame, "x", "y", "savgol", "s", SmoothingParameters())
        recorder.smooth(source, "x", "y", "savgol", SmoothingParameters(), "s")
        self.assertEqual(recorder.ref(source.name, "s"), ColumnRef("step1", "y"))
        recorder.check(source)
        self.assertFalse(recorder.macro.issues)
        source.frame.loc[0, "y"] = 123
        recorder.check(source)
        self.assertTrue(recorder.macro.issues)
        with self.assertRaises(ValueError):
            recorder.macro.validate(runnable=True)

    def test_export_is_separate_reusable_and_does_not_overwrite(self):
        routine = macro()
        result = run_macro(context(), routine, [MacroSource("one", "one", data())], MacroRun())
        with tempfile.TemporaryDirectory() as directory:
            first = export_macro_tables(context(), routine, result, Path(directory))
            second = export_macro_tables(context(), routine, result, Path(directory))
            self.assertNotEqual(first, second)
            self.assertTrue((first/"run_summary.csv").exists())
            self.assertEqual(Macro.load(first/"macro.jasc-macro.json").to_state(), routine.to_state())
            self.assertTrue((first/"source_0001_fit1.csv").exists())


if __name__ == "__main__":
    unittest.main()
