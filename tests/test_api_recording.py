"""Executable Python recordings, chronological GUI calls, and public API parity."""

import ast
from copy import deepcopy
from dataclasses import asdict
import gc
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from core import project_io
from core.api_recording import ApiRecording, literal
from core.file_io import ImportOptions
from core.workspace import Workspace
from jasc_api import Session, series
from math_engine.smoothing import SmoothingParameters, smooth_column
from tests.test_macros import data


def replay(text, workspace, *, input_root=None, output_root=None):
    from core.script_language import Program
    from core.script_runtime import Interpreter
    from core.script_safety import FilePolicy
    with tempfile.TemporaryDirectory() as temporary:
        files = FilePolicy(Path(input_root or Path.cwd()), Path(output_root or temporary))
        Interpreter(Session(workspace), files).run(Program.parse(text))


def methods(recording):
    tree = ast.parse(recording.source())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    return [node.func.attr for statement in function.body for node in ast.walk(statement)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "session"]


class ApiTests(unittest.TestCase):
    def test_public_formula_calculus_and_fft_use_existing_engines(self):
        workspace = Workspace()
        sheet = workspace.add_dataset("sample", data().frame)
        session = Session(workspace)
        session.formula(sheet, output_column="twice", expression='col("y") * 2')
        np.testing.assert_allclose(sheet.frame.twice, 2*sheet.frame.y)
        self.assertIn("twice", sheet.formulas)
        session.derivative(sheet, x_column="x", y_column="twice", method="gradient", output_column="dy")
        self.assertTrue(np.isfinite(sheet.frame.dy).all())
        session.integral(sheet, x_column="x", y_column="dy", method="trapezoid", output_column="restored", initial_value=7)
        self.assertEqual(sheet.frame.restored.iloc[0], 7)
        spectrum = session.fft(sheet, signal_column="y", x_column="x")
        reconstructed = session.ifft(spectrum, real_column="real", imaginary_column="imaginary")
        self.assertEqual(len(reconstructed.frame), len(sheet.frame))

    def test_import_calls_execute_in_order_with_recorded_options(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"input 'quoted'.csv"
            data().frame.to_csv(path, sep=";", index=False)
            workspace = Workspace()
            session = Session(workspace)
            recording = ApiRecording("Import and process", workspace)
            options = ImportOptions(delimiter=";", has_header=True)
            sheet = session.load(path, **asdict(options))
            recording.imported(sheet, options)
            recording.before(sheet)
            parameters = SmoothingParameters()
            session.smooth(sheet, x_column="x", y_column="y", method="savgol", output_column="smoothed", **asdict(parameters))
            recording.smoothed(sheet, "x", "y", "savgol", parameters, "smoothed")
            recording.finish(workspace)
            output = Workspace()
            replay(recording.source(), output, input_root=path.parent)
            np.testing.assert_allclose(output.list_datasets()[0].frame.smoothed, sheet.frame.smoothed)
            self.assertEqual(methods(recording), ["load", "smooth"])
            self.assertFalse(recording.issues)

    def test_unrecorded_changes_make_the_script_explicitly_incomplete(self):
        workspace = Workspace()
        source = workspace.add_dataset("sample", data().frame)
        recording = ApiRecording("Incomplete", workspace)
        source.frame.loc[0, "y"] = 1000
        workspace.add_dataset("unrecorded result", data().frame)
        recording.finish(workspace)
        self.assertEqual(len(recording.issues), 2)
        with self.assertRaisesRegex(ValueError, "Incomplete recording"):
            replay(recording.source(), Workspace())

    def test_names_and_nonfinite_literals_remain_python_values(self):
        workspace = Workspace()
        name = "sample 'quoted' \\ sheet"
        source = workspace.add_dataset(name, data().frame)
        recording = ApiRecording("Names", workspace)
        recording.before(source)
        output = deepcopy(workspace)
        replay(recording.source(), output)
        self.assertIn(name, output.dataset_names())
        self.assertEqual(literal(float("inf")), "float('inf')")
        ast.parse(recording.source())

    def test_load_folder_and_workspace_sheets_share_one_public_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            data().frame.to_csv(path/"one.csv", index=False)
            data().frame.to_csv(path/"two.csv", index=False)
            session = Session()
            loaded = session.load_folder(path)
            self.assertEqual(len(loaded), 2)
            self.assertIs(session.sheet("one"), loaded[0])


class ApiRecordingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ui.main_window import MainWindow
        self.window = MainWindow()
        self.source = self.window._workspace.add_dataset("source", data().frame)
        self.window._refresh_dataset_list(self.source.name)

    def tearDown(self):
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def record_example(self):
        from tests.test_macro_ui import MacroUiTests
        MacroUiTests.record(self)
        return self.window._macros.api_recording

    def test_actual_gui_actions_generate_executable_chronological_calls(self):
        recording = self.record_example()
        self.assertFalse(recording.issues)
        self.assertEqual(methods(recording), ["sheet", "smooth", "plot", "fit", "result_row", "collect_rows", "plot"])
        workspace = Workspace()
        workspace.add_dataset("source", data().frame)
        replay(recording.source(), workspace)
        for name in ("source", "source_fit", "source_residuals", "source_fit_report"):
            pd.testing.assert_frame_equal(workspace.get_dataset(name).frame, self.window._workspace.get_dataset(name).frame)
        originals = self.window._workspace.list_plots()
        self.assertEqual([plot.state for plot in workspace.list_plots()], [plot.state for plot in originals])

    def test_plot_changes_and_figure_export_are_recorded_at_the_time_of_action(self):
        from ui.plot_canvas import PlotSeries
        controller = self.window._macros
        controller.start_recording(name="Plot and style")
        self.window._plot_tab_widget.queue_plot_series([PlotSeries("source", "x", "source", "y")], "Initial")
        editor = self.window._plot_tab_widget._active_editor
        editor._title_edit.setText("Updated")
        editor._render_plot()
        plot = self.window._plot_tab_widget.active_document
        self.window._workspace.rename_plot(plot.name, "Renamed")
        self.window._plot_tab_widget._notify()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"figure.png"
            editor._plot_canvas.export_figure(str(path))
            controller.stop_recording()
            recording = controller.api_recording
            self.assertFalse(recording.issues)
            self.assertIn("update_plot", methods(recording))
            self.assertIn("rename_plot", methods(recording))
            self.assertEqual(methods(recording)[-1], "export_plot")
            path.unlink()
            workspace = Workspace()
            workspace.add_dataset("source", data().frame)
            replay(recording.source(), workspace, output_root=path.parent)
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 1000)
            self.assertEqual(workspace.list_plots()[0].state["settings"]["title"], "Updated")
            self.assertEqual(workspace.list_plots()[0].name, "Renamed")

    def test_cli_launches_a_saved_recording_and_writes_a_project(self):
        initial = deepcopy(self.window._workspace)
        recording = self.record_example()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_io.save_project(initial, root/"initial.jasc")
            recording.save(root/"recorded.py")
            result = subprocess.run([sys.executable, "-B", "-m", "jasc_api", str(root/"recorded.py"),
                                     "--project", str(root/"initial.jasc"), "--output", str(root/"result.jasc")],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            loaded = project_io.load_project(root/"result.jasc")
            np.testing.assert_allclose(loaded.get_dataset("source_fit").frame.fit_y,
                                       self.window._workspace.get_dataset("source_fit").frame.fit_y)
            self.assertEqual(len(loaded.list_plots()), 2)

    def test_calculus_and_formula_hooks_record_api_calls(self):
        self.window._macros.start_recording(name="Transform")
        self.window._apply_column_math_to_dataset(self.source, "derivative", "x", "y", "gradient", "dy", None,
                                                 True, {"gradient": "Gradient"}, "Derivative")
        self.window._apply_expression_to_dataset(self.source, "twice", 'col("dy") * 2', None, True)
        self.window._macros.stop_recording()
        recording = self.window._macros.api_recording
        self.assertFalse(recording.issues)
        self.assertEqual(methods(recording), ["sheet", "derivative", "formula"])
        workspace = Workspace()
        workspace.add_dataset("source", data().frame)
        replay(recording.source(), workspace)
        np.testing.assert_allclose(workspace.get_dataset("source").frame.twice, self.source.frame.twice)

    def test_python_save_guard_keeps_the_script_distinct_from_batch_recipes(self):
        from PySide6.QtWidgets import QMessageBox
        recording = self.record_example()
        controller = self.window._macros
        with patch("ui.macro_controller.QMessageBox.question", return_value=QMessageBox.Cancel):
            self.assertFalse(controller.confirm_saved())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"recording.py"
            with patch("ui.macro_controller.QFileDialog.getSaveFileName", return_value=(str(path), "")):
                self.assertTrue(controller.save_api_script())
            self.assertEqual(path.read_text(encoding="utf-8"), recording.source())
            self.assertTrue(controller.confirm_saved())

    def test_comparison_calls_rebind_plot_identities_and_export_the_grid(self):
        from core.plot_comparison import comparison_state
        from ui.plot_canvas import PlotSeries
        controller = self.window._macros
        controller.start_recording(name="Comparison")
        manager = self.window._plot_tab_widget
        manager.queue_plot_series([PlotSeries("source", "x", "source", "y")], "First")
        first = manager.active_document
        manager.queue_plot_series([PlotSeries("source", "x", "source", "y", color="tab:red")], "Second")
        second = manager.active_document
        manager.new_comparison("Compare", comparison_state([first.plot_id, second.plot_id], 1, 2, match_x=True))
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory)/"comparison.png"
            manager._active_editor.export_png(image)
            controller.stop_recording()
            recording = controller.api_recording
            self.assertFalse(recording.issues)
            self.assertIn("compare", methods(recording))
            image.unlink()
            workspace = Workspace()
            workspace.add_dataset("source", data().frame)
            replay(recording.source(), workspace, output_root=image.parent)
            plots = workspace.list_plots()
            self.assertEqual(plots[-1].state["plot_ids"], [plots[0].plot_id, plots[1].plot_id])
            self.assertTrue(plots[-1].state["match_x"])
            self.assertGreater(image.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
