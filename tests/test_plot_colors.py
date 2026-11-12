"""Custom colours through inspector controls, draft persistence and recording."""
from __future__ import annotations

from copy import deepcopy
import gc
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.colors import to_rgba
import numpy as np
import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog

from core import project_io
from tests.test_api_recording import replay, methods
from ui.main_window import MainWindow
from ui.plot_canvas import PlotSeries
from ui.plot_colors import PLOT_COLOR_PRESETS, PlotColorSelector
from ui.plot_element_dialogs import PlotSeriesAppearanceDialog


class PlotColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()
        self.manager = self.window._plot_tab_widget
        self.data = self.window._workspace.add_dataset("Signal", pd.DataFrame({"x": [0., 1., 2.], "y": [1., 3., 2.]}))
        self.window._refresh_dataset_list(self.data.name)

    def tearDown(self) -> None:
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def plot(self, kind: str = "line_marker") -> object:
        self.manager.queue_plot_series([PlotSeries(self.data.name, "x", self.data.name, "y", plot_type=kind, marker="o")], "Custom colours")
        return self.manager.active_document

    def pick(self, selector: PlotColorSelector, value: str) -> None:
        with patch("ui.plot_colors.QColorDialog.getColor", return_value=QColor(value)):
            selector.custom_button.click()

    def test_picker_has_rgb_hex_controls_presets_swatches_and_cancel(self) -> None:
        selector = PlotColorSelector(default="tab:orange", parent=self.window)
        self.assertGreaterEqual(len(PLOT_COLOR_PRESETS), 20)
        self.assertTrue(all(not selector.combo.itemIcon(i).isNull() for i in range(1, selector.combo.count())))
        with patch("ui.plot_colors.QColorDialog.getColor", return_value=QColor("#159a86")) as picker:
            selector.custom_button.click()
        initial, _parent, _title, options = picker.call_args.args
        self.assertEqual(initial.name(), "#ff7f0e")
        self.assertTrue(options & QColorDialog.ColorDialogOption.DontUseNativeDialog)
        self.assertEqual(selector.combo.currentData(), "#159a86")
        count = selector.combo.count()
        self.pick(selector, "#159a86")
        self.assertEqual(selector.combo.count(), count)
        with patch("ui.plot_colors.QColorDialog.getColor", return_value=QColor()):
            selector.custom_button.click()
        self.assertEqual(selector.combo.currentData(), "#159a86")
        selector.combo.set_color("")
        self.assertEqual(selector.combo.currentData(), "")

    def test_custom_colour_renders_for_lines_and_symbols(self) -> None:
        self.plot()
        editor = self.manager._active_editor
        self.pick(editor._color_selector, "#7951c2")
        self.assertTrue(editor.has_unapplied_series_edits())
        editor._update_selected_series()
        self.assertEqual(editor._plot_series[0].color, "#7951c2")
        line = editor._plot_canvas.axes.lines[0]
        self.assertEqual(line.get_color(), "#7951c2")
        self.assertEqual(line.get_markerfacecolor(), "#7951c2")

    def test_custom_colour_renders_for_scatter(self) -> None:
        self.plot("scatter")
        editor = self.manager._active_editor
        self.pick(editor._color_selector, "#13a2a7")
        editor._update_selected_series()
        np.testing.assert_allclose(editor._plot_canvas.axes.collections[0].get_facecolors()[0], to_rgba("#13a2a7"))

    def test_unapplied_custom_colour_survives_tab_close_and_project_reload(self) -> None:
        plot = self.plot()
        editor = self.manager._active_editor
        self.pick(editor._color_selector, "#df7219")
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.manager.open_plot(plot.name)
        self.assertEqual(self.manager._active_editor._color_combo.currentData(), "#df7219")
        self.assertEqual(self.manager._active_editor._plot_series[0].color, "")
        self.manager.flush()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"colours.jasc"
            project_io.save_project(self.window._workspace, path)
            loaded = project_io.load_project(path)
        self.window._workspace = loaded
        self.manager.set_workspace(loaded)
        self.manager.open_plot(plot.name)
        editor = self.manager._active_editor
        self.assertEqual(editor._color_combo.currentData(), "#df7219")
        self.assertTrue(editor.has_unapplied_series_edits())
        editor._update_selected_series()
        self.assertEqual(editor._plot_series[0].color, "#df7219")
        self.assertEqual(editor._plot_canvas.axes.lines[0].get_color(), "#df7219")

    def test_custom_locator_colour_is_stored(self) -> None:
        self.plot()
        editor = self.manager._active_editor
        self.pick(editor._locator_color_selector, "#b91763")
        editor._locator_x_edit.setText("0.5")
        with patch("ui.plot_tab.QMessageBox.warning") as warning:
            editor._add_locator()
        warning.assert_not_called()
        self.assertEqual(editor._plot_locators[0].color, "#b91763")
        self.assertEqual(editor.current_plot_state()["locators"][0]["color"], "#b91763")

    def test_custom_colour_is_recorded_recomputed_and_exported(self) -> None:
        plot = self.plot("scatter")
        starting = deepcopy(self.window._workspace)
        controller = self.window._macros
        controller.start_recording(name="Custom colour")
        editor = self.manager._active_editor
        self.pick(editor._color_selector, "#276a91")
        editor._update_selected_series()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            editor._plot_canvas.export_figure(str(directory/"colour.png"))
            controller.stop_recording()
            recording = controller.api_recording
            self.assertEqual(recording.issues, [])
            self.assertIn("update_plot", methods(recording))
            self.assertIn("export_plot", methods(recording))
            outputs = directory/"replayed"
            outputs.mkdir()
            replay(recording.source(), starting, output_root=outputs)
            self.assertEqual(starting.get_plot(plot.name).state["series"][0]["color"], "#276a91")
            self.assertGreater((outputs/"colour.png").stat().st_size, 1000)

    def test_canvas_editor_uses_same_picker_for_extended_matplotlib_names(self) -> None:
        dialog = PlotSeriesAppearanceDialog(PlotSeries(self.data.name, "x", self.data.name, "y", color="xkcd:sky blue"), [("Line", "line")], self.window)
        with patch("ui.plot_colors.QColorDialog.getColor", return_value=QColor("#914ea6")) as picker:
            dialog._choose_colour()
        self.assertTrue(picker.call_args.args[0].isValid())
        self.assertEqual(dialog.series_updates()["color"], "#914ea6")
        dialog._use_automatic_colour()
        self.assertEqual(dialog.series_updates()["color"], "")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
