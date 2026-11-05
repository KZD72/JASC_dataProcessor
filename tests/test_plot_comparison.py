"""Comparison workflow, native rendering, equal geometry, and document ownership."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import gc
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from matplotlib.backend_bases import MouseEvent, MouseButton
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from shiboken6 import isValid

from core import project_io
from core.plot_comparison import comparison_state, suggested_grid
from core.workspace import Workspace
from ui.main_window import MainWindow
from ui.plot_canvas import PlotSeries
from ui.plot_comparison import ComparePlotsDialog, PlotComparisonView


class ComparisonStateTests(unittest.TestCase):
    def test_invalid_selection_and_insufficient_grid_rejected(self) -> None:
        for identities, rows, columns in ((["a"], 1, 2), (["a", "a"], 1, 2),
                                           (["a", "b"], 1, 1), (["a", "b"], 0, 2),
                                           ([str(i) for i in range(17)], 4, 4)):
            with self.assertRaises(ValueError):
                comparison_state(identities, rows, columns)
        for count in range(2, 17):
            rows, columns = suggested_grid(count)
            self.assertGreaterEqual(rows * columns, count)
            self.assertLessEqual(max(rows, columns), 4)


class PlotComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        gc.collect()
        self.window = MainWindow()
        self.manager = self.window._plot_tab_widget
        self.data = self.window._workspace.add_dataset("signal", pd.DataFrame({
            "x": [0., 1., 2.], "y": [1., 2., 4.], "other": [4., 3., 1.]}))
        self.window._refresh_dataset_list(self.data.name)
        self.manager.queue_single_series_plot(self.data, "x", "y", "First")
        self.first = self.manager.active_document
        self.manager.queue_single_series_plot(self.data, "x", "other", "Second")
        self.second = self.manager.active_document
        self.warning = patch("ui.main_window.QMessageBox.warning").start()

    def tearDown(self) -> None:
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        patch.stopall()
        gc.collect()

    def compare(self, **options: object) -> PlotComparisonView:
        self.manager.new_comparison("Comparison", comparison_state(
            [self.first.plot_id, self.second.plot_id], 1, 2, **options))
        return self.manager._active_editor

    def test_menu_opens_picker_and_cancel_does_not_create_document(self) -> None:
        self.assertTrue(self.window._compare_plots_action.isEnabled())
        with patch.object(ComparePlotsDialog, "exec", lambda _dialog: QDialog.Rejected):
            self.window._compare_plots()
        self.assertEqual(len(self.window._workspace.list_plots()), 2)
        self.manager.delete_plot(self.second.name)
        self.assertFalse(self.window._compare_plots_action.isEnabled())

    def test_picker_order_validation_and_comparison_exclusion(self) -> None:
        self.compare()
        dialog = ComparePlotsDialog(self.window._workspace)
        self.assertEqual(dialog._plots.count(), 2)
        for index in range(2):
            dialog._plots.item(index).setCheckState(Qt.Checked)
        dialog._plots.setCurrentRow(1)
        dialog._move(-1)
        self.assertEqual(dialog.specification()["plot_ids"], [self.second.plot_id, self.first.plot_id])
        dialog._rows.setValue(1)
        dialog._columns.setValue(1)
        with self.assertRaises(ValueError):
            dialog.specification()
        dialog._fit_grid()
        self.assertEqual(dialog.specification()["columns"], 2)
        dialog.deleteLater()

    def test_compare_command_accepts_selection_and_popout(self) -> None:
        def choose(dialog: ComparePlotsDialog) -> int:
            for index in range(dialog._plots.count()):
                dialog._plots.item(index).setCheckState(Qt.Checked)
            dialog._name.setText("Selected plots")
            dialog._pop_out.setChecked(True)
            return QDialog.Accepted
        with patch.object(ComparePlotsDialog, "exec", choose):
            self.window._compare_plots()
        view = self.manager._active_editor
        self.assertEqual(self.manager.active_document.name, "Selected plots")
        self.assertIn(view, self.manager._popouts)
        self.assertIs(self.window._tabs.currentWidget(), self.manager)

    def test_native_contents_and_layout_leave_source_drafts_unchanged(self) -> None:
        source_editor = self.manager._active_editor
        source_editor._series_label_edit.setText("Unapplied edit")
        self.manager.flush()
        before = [deepcopy((plot.state, plot.editor_state)) for plot in (self.first, self.second)]
        view = self.compare(match_x=True, match_y=True)
        self.assertEqual(len(view._panels), 2)
        np.testing.assert_array_equal(view._panels[0][1].axes.lines[0].get_ydata(), self.data.frame["y"])
        np.testing.assert_array_equal(view._panels[1][1].axes.lines[0].get_ydata(), self.data.frame["other"])
        view._rows.setValue(2)
        view._letters.setChecked(False)
        view._panels[0][1].axes.set_ylim(-10, 10)
        self.assertEqual([deepcopy((plot.state, plot.editor_state)) for plot in (self.first, self.second)], before)
        self.assertEqual(source_editor._series_label_edit.text(), "Unapplied edit")

    def test_equal_cells_with_empty_trailing_cell_and_resizing(self) -> None:
        third = self.window._workspace.duplicate_plot(self.first.name)
        self.manager.new_comparison("Grid", comparison_state(
            [self.first.plot_id, self.second.plot_id, third.plot_id], 2, 2))
        view = self.manager._active_editor
        self.window._tabs.setCurrentWidget(self.manager)
        self.window.show()
        for width in (1300, 1000):
            self.window.resize(width, 900)
            QTest.qWait(70)
            rectangles = [view._grid.itemAtPosition(row, column).widget().geometry()
                          for row in range(2) for column in range(2)]
            self.assertLessEqual(max(r.width() for r in rectangles) - min(r.width() for r in rectangles), 1)
            self.assertLessEqual(max(r.height() for r in rectangles) - min(r.height() for r in rectangles), 1)

    def test_numeric_matching_navigation_and_scale_mismatch(self) -> None:
        view = self.compare(match_x=True, match_y=True)
        first, second = [canvas for _, canvas in view._panels]
        first.axes.set_xlim(.25, 1.5)
        second.axes.set_ylim(-2, 6)
        self.assertEqual(tuple(second.axes.get_xlim()), (.25, 1.5))
        self.assertEqual(tuple(first.axes.get_ylim()), (-2., 6.))
        view._navigation("pan", True)
        self.assertTrue(all(canvas.toolbar.mode.name == "PAN" for _, canvas in view._panels))
        view._navigation("zoom", True)
        self.assertTrue(all(canvas.toolbar.mode.name == "ZOOM" for _, canvas in view._panels))
        self.manager._editors[self.second.plot_id]._x_scale_combo.setCurrentText("log")
        view.refresh()
        self.assertIn("Matching X limits skipped", view._status.text())
        limits = tuple(view._panels[1][1].axes.get_xlim())
        view._panels[0][1].axes.set_xlim(10, 20)
        self.assertEqual(tuple(view._panels[1][1].axes.get_xlim()), limits)

    def test_matched_zoom_survives_close_and_reopen(self) -> None:
        view = self.compare(match_x=True)
        layout = self.manager.active_document
        view._panels[0][1].axes.set_xlim(.4, 1.4)
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.manager.open_plot(layout.name)
        for _, canvas in self.manager._active_editor._panels:
            self.assertEqual(tuple(canvas.axes.get_xlim()), (.4, 1.4))

    def test_cancel_close_keeps_popout_and_close_tab_releases_window(self) -> None:
        view = self.compare()
        layout = self.manager.active_document
        self.manager.toggle_popout(view)
        dialog = self.manager._popouts[view]
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=False):
            self.window.close()
        self.assertIn(view, self.manager._popouts)
        self.manager.close_tab(self.manager.tabs.indexOf(view))
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(dialog))
        self.assertFalse(isValid(view))
        self.assertIn(layout.name, self.window._workspace.plot_names())

    def test_categories_and_composition_not_given_numeric_matching(self) -> None:
        self.manager.close_tab(self.manager.tabs.indexOf(self.manager._editors[self.first.plot_id]))
        self.first.state["series"][0]["plot_type"] = "pie"
        view = self.compare(match_x=True, match_y=True)
        self.assertTrue(view._panels[0][1].axes.patches)
        self.assertFalse(view._compatible_axes["x"])
        self.assertIn("Matching Y limits skipped", view._status.text())

    def test_refresh_and_source_rename_resolve_stable_identity(self) -> None:
        view = self.compare()
        self.manager.open_plot(self.first.name)
        self.manager._title_edit.setText("Revised source")
        QTest.qWait(180)
        self.assertEqual(view._panels[0][1].axes.get_title(), "Revised source")
        self.manager.rename_active("Renamed source")
        QTest.qWait(180)
        self.assertIn("Renamed source", view._sources_label.text())
        self.assertEqual(view.current_plot_state()["plot_ids"][0], self.first.plot_id)
        self.data.frame.loc[0, "y"] = 99.
        view.refresh()
        self.assertEqual(view._panels[0][1].axes.lines[0].get_ydata()[0], 99.)

    def test_missing_source_remains_in_layout_with_placeholder(self) -> None:
        view = self.compare()
        self.manager.delete_plot(self.first.name)
        QTest.qWait(180)
        self.assertEqual(len(view._panels), 2)
        self.assertIn(self.first.plot_id, view.current_plot_state()["plot_ids"])
        self.assertIn("Source plot is unavailable", view._status.text())
        self.assertTrue(view._panels[1][1].axes.lines)

    def test_source_double_click_activates_original_editor(self) -> None:
        editor = self.manager._active_editor
        view = self.compare()
        view._open_source(type("Click", (), {"dblclick": True})(), self.second.plot_id)
        self.assertIs(self.manager._active_editor, editor)
        self.assertEqual(self.manager.tabs.count(), 3)

    def test_layout_undo_and_sixteen_panel_dimension_clamping(self) -> None:
        view = self.compare()
        self.manager.mark_saved()
        view._rows.setValue(2)
        self.assertTrue(self.manager.is_dirty())
        self.assertTrue(self.manager.undo())
        self.assertEqual(view.current_plot_state()["rows"], 1)
        self.assertTrue(self.manager.redo())
        self.assertEqual(view.current_plot_state()["rows"], 2)
        identities = [self.first.plot_id, self.second.plot_id]
        identities.extend(self.window._workspace.duplicate_plot(self.first.name).plot_id for _ in range(14))
        view.load_plot_state(comparison_state(identities, 4, 4))
        view._rows.setValue(1)
        self.assertEqual((view._rows.value(), view._columns.value()), (4, 4))

    def test_project_save_close_reopen_and_duplicate_layout(self) -> None:
        view = self.compare(match_y=True)
        layout = self.manager.active_document
        view._panels[0][1].axes.set_xlim(.3, 1.2)
        self.manager.close_tab(self.manager.tabs.currentIndex())
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(view))
        self.manager.open_plot(layout.name)
        self.assertEqual(tuple(self.manager._active_editor._panels[0][1].axes.get_xlim()), (.3, 1.2))
        self.manager.flush()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.jasc"
            project_io.save_project(self.window._workspace, path)
            loaded = project_io.load_project(path)
        self.window._workspace = loaded
        self.manager.set_workspace(loaded)
        self.manager.open_plot(layout.name)
        self.assertIsInstance(self.manager._active_editor, PlotComparisonView)
        self.assertEqual(self.manager.active_document.state, layout.state)
        self.assertFalse(self.manager.is_dirty())
        duplicate = loaded.duplicate_plot(layout.name)
        self.assertNotEqual(duplicate.plot_id, layout.plot_id)
        self.assertEqual(duplicate.state["plot_ids"], layout.state["plot_ids"])

    def test_popout_close_reattaches_and_workspace_replacement_disposes_it(self) -> None:
        view = self.compare()
        self.manager.toggle_popout(view)
        dialog = self.manager._popouts[view]
        self.assertIs(view._content.window(), dialog)
        self.assertFalse(view.options_widget().isHidden())
        view._rows.setValue(2)
        self.manager.flush()
        self.assertEqual(self.manager.active_document.state["rows"], 2)
        dialog.close()
        self.assertNotIn(view, self.manager._popouts)
        self.assertIs(view._content.parentWidget(), view)
        self.assertIs(self.manager.options_widget().currentWidget(), view.options_widget())
        self.manager.toggle_popout(view)
        dialog = self.manager._popouts[view]
        self.window._workspace = Workspace()
        self.manager.set_workspace(self.window._workspace)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(dialog))
        self.assertFalse(isValid(view))
        self.assertFalse(self.manager._popouts)

    def test_png_export_and_clipboard_grid_preserve_native_view(self) -> None:
        view = self.compare()
        self.window.show()
        self.window._tabs.setCurrentWidget(self.manager)
        QTest.qWait(50)
        sizes = [canvas.figure.get_size_inches().copy() for _, canvas in view._panels]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grid.png"
            view.export_png(path, cell_width=500, cell_height=400)
            image = QImage(str(path))
            self.assertEqual((image.width(), image.height()), (1000, 400))
            self.assertFalse(image.isNull())
            for offset in (0, 500):
                self.assertTrue(any(image.pixelColor(offset + x, y) != Qt.white
                                    for x in range(30, 480, 10) for y in range(20, 380, 10)))
        for before, (_, canvas) in zip(sizes, view._panels):
            np.testing.assert_allclose(canvas.figure.get_size_inches(), before)
        self.assertTrue(view.copy_plot_to_clipboard())
        self.assertFalse(QApplication.clipboard().pixmap().isNull())

    def test_native_heatmap_colorbar_and_right_axis_are_retained(self) -> None:
        for identity in (self.first.plot_id, self.second.plot_id):
            self.manager.close_tab(self.manager.tabs.indexOf(self.manager._editors[identity]))
        data = self.window._workspace.add_dataset("map", pd.DataFrame({
            "x": [0., 1., 0., 1.], "y": [0., 0., 1., 1.], "z": [1., 2., 3., 4.]}))
        surface = PlotSeries(x_dataset=data.name, x_column="x", y_dataset=data.name, y_column="y",
                             custom_label="Map", plot_type="heatmap", z_dataset=data.name, z_column="z")
        self.first.state["series"] = [asdict(surface)]
        right = deepcopy(self.second.state["series"][0])
        right["y_axis"] = "right"
        right["custom_label"] = "Right axis"
        self.second.state["series"].append(right)
        view = self.compare()
        self.assertGreater(len(view._panels[0][1].figure.axes), 1)
        self.assertIsNotNone(view._panels[1][1].right_axes)
        self.assertTrue(view._panels[1][1].right_axes.lines)

    def test_image_synchronization_links_wheel_pan_drag_and_survives_reload(self) -> None:
        for identity in (self.first.plot_id, self.second.plot_id):
            self.manager.close_tab(self.manager.tabs.indexOf(self.manager._editors[identity]))
        data = self.window._workspace.add_dataset("images", pd.DataFrame({
            "x": [0., 10., 0., 10.], "y": [0., 0., 10., 10.], "z": [1., 2., 3., 4.]}))
        surface = PlotSeries(data.name, "x", data.name, "y", z_dataset=data.name, z_column="z",
                             plot_type="heatmap", surface_aspect="equal")
        for plot in (self.first, self.second):
            plot.state["series"] = [asdict(surface)]
        original = deepcopy((self.first.state, self.second.state))
        view = self.compare()
        self.assertIn("Synchronize", view._match_x.text())
        view._match_x.setChecked(True)
        view._match_y.setChecked(True)
        layout = self.manager.active_document
        for _, canvas in view._panels:
            canvas.canvas.draw()
        first, second = [canvas for _, canvas in view._panels]
        bounds = first.axes.bbox
        center = ((bounds.x0 + bounds.x1) / 2, (bounds.y0 + bounds.y1) / 2)
        before_x, before_y = first.axes.get_xlim(), first.axes.get_ylim()
        event = MouseEvent("scroll_event", first.canvas, center[0], bounds.y0 - 4, step=1)
        first.canvas.callbacks.process("scroll_event", event)
        np.testing.assert_allclose(first.axes.get_xlim(), second.axes.get_xlim())
        np.testing.assert_allclose(first.axes.get_ylim(), before_y)
        self.assertLess(abs(np.diff(first.axes.get_xlim())[0]), abs(np.diff(before_x)[0]))
        for step, modifiers in ((1, ()), (1, ("shift",))):
            event = MouseEvent("scroll_event", first.canvas, *center, step=step, modifiers=modifiers)
            first.canvas.callbacks.process("scroll_event", event)
            np.testing.assert_allclose(first.axes.get_xlim(), second.axes.get_xlim())
            np.testing.assert_allclose(first.axes.get_ylim(), second.axes.get_ylim())
        for name, point, kwargs in (
            ("button_press_event", center, {"button": MouseButton.MIDDLE}),
            ("motion_notify_event", (center[0] + 25, center[1] + 20), {"buttons": {MouseButton.MIDDLE}}),
            ("button_release_event", center, {"button": MouseButton.MIDDLE}),
        ):
            first.canvas.callbacks.process(name, MouseEvent(name, first.canvas, *point, **kwargs))
        np.testing.assert_allclose(first.axes.get_xlim(), second.axes.get_xlim())
        np.testing.assert_allclose(first.axes.get_ylim(), second.axes.get_ylim())
        self.assertEqual((self.first.state, self.second.state), original)
        zoom = first.axes.get_xlim(), first.axes.get_ylim()
        self.manager.close_tab(self.manager.tabs.indexOf(view))
        self.manager.open_plot(layout.name)
        view = self.manager._active_editor
        self.assertTrue(view._match_x.isChecked())
        self.assertTrue(view._match_y.isChecked())
        for _, canvas in view._panels:
            np.testing.assert_allclose(canvas.axes.get_xlim(), zoom[0])
            np.testing.assert_allclose(canvas.axes.get_ylim(), zoom[1])
        view._match_x.setChecked(False)
        view._match_y.setChecked(False)
        first, second = [canvas for _, canvas in view._panels]
        first.canvas.draw()
        bounds = first.axes.bbox
        point = ((bounds.x0 + bounds.x1) / 2, (bounds.y0 + bounds.y1) / 2)
        before_x, before_y = second.axes.get_xlim(), second.axes.get_ylim()
        first.canvas.callbacks.process("scroll_event", MouseEvent("scroll_event", first.canvas, *point, step=1))
        np.testing.assert_allclose(second.axes.get_xlim(), before_x)
        np.testing.assert_allclose(second.axes.get_ylim(), before_y)


if __name__ == "__main__":
    unittest.main()
