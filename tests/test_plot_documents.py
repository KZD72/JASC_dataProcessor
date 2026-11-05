"""Independent plot documents, project persistence, and safe tab lifecycle."""

from __future__ import annotations

from copy import deepcopy
import gc
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from shiboken6 import isValid

from core import project_io
from core.workspace import Workspace
from ui.main_window import MainWindow


class PlotDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        gc.collect()
        self.window = MainWindow()
        self.manager = self.window._plot_tab_widget
        self.data = self.window._workspace.add_dataset(
            "signal", pd.DataFrame({"x": [0., 1., 2.], "y": [1., 2., 4.], "other": [4., 3., 1.]}))
        self.window._refresh_dataset_list(self.data.name)
        self.warning = patch("ui.main_window.QMessageBox.warning").start()

    def tearDown(self) -> None:
        with patch("ui.main_window.QMessageBox.exec", return_value=QMessageBox.Discard):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        patch.stopall()
        gc.collect()

    def plot(self, title: str = "Spectrum") -> object:
        self.manager.queue_single_series_plot(self.data, "x", "y", title)
        return self.manager.active_document

    def test_startup_has_no_phantom_plot_or_unsaved_change(self) -> None:
        self.assertEqual(self.window._workspace.plot_names(), [])
        self.assertFalse(self.manager.is_dirty())
        self.assertEqual(self.manager.tabs.count(), 1)
        self.assertIs(self.window._plot_inspector, self.manager.options_widget())
        self.window.show()
        self.window._workspace_nav_tabs.setCurrentWidget(self.window._plot_nav_page)
        QTest.qWait(20)
        for count in (1, 2):
            item = self.window._plot_list.item(0)
            QTest.mouseClick(self.window._plot_list.viewport(), Qt.LeftButton,
                             pos=self.window._plot_list.visualItemRect(item).center())
            self.assertEqual(len(self.window._workspace.plot_names()), count)
            self.assertIs(self.window._tabs.currentWidget(), self.manager)

    def test_new_and_analysis_plots_preserve_existing_document(self) -> None:
        first = self.plot()
        self.manager._title_edit.setText("Work in progress")
        first_editor = self.manager._active_editor
        self.manager._series_label_edit.setText("Unapplied label")
        self.assertTrue(first_editor.has_unapplied_series_edits())
        with patch.object(self.window, "_confirm_plot_replacement", return_value=False) as prompt:
            self.window._start_new_plot()
            self.manager.queue_analysis_plot(self.data, "x", "y", "other", "Derivative")
        prompt.assert_not_called()
        self.assertEqual(len(self.window._workspace.plot_names()), 3)
        self.manager.open_plot(first.name)
        self.assertIs(self.manager._active_editor, first_editor)
        self.assertEqual(self.manager._title_edit.text(), "Work in progress")
        self.assertEqual(self.manager._series_label_edit.text(), "Unapplied label")
        self.assertTrue(self.manager.has_unapplied_series_edits())

    def test_individual_plot_popout_keeps_editor_draft_zoom_and_maximize(self) -> None:
        plot = self.plot()
        editor = self.manager._active_editor
        editor._series_label_edit.setText("Pending in window")
        editor._plot_canvas.axes.set_xlim(.3, 1.3)
        editor._detach_action.trigger()
        dialog = self.manager._popouts[editor]
        self.assertTrue(dialog.windowFlags() & Qt.WindowMaximizeButtonHint)
        self.assertIs(editor._content.window(), dialog)
        self.assertFalse(editor.options_widget().isHidden())
        dialog.showMaximized()
        QTest.qWait(20)
        self.assertTrue(dialog.isMaximized())
        self.manager.flush()
        self.assertEqual(plot.editor_state["controls"]["_series_label_edit"]["value"], "Pending in window")
        dialog.close()
        self.assertNotIn(editor, self.manager._popouts)
        self.assertIs(editor._content.parentWidget(), editor)
        self.assertIs(self.manager._active_editor, editor)
        self.assertEqual(editor._series_label_edit.text(), "Pending in window")
        self.assertEqual(tuple(editor._plot_canvas.axes.get_xlim()), (.3, 1.3))

    def test_activating_popout_routes_document_actions_to_its_plot(self) -> None:
        first = self.plot("First")
        editor = self.manager._active_editor
        self.manager.toggle_popout(editor)
        dialog = self.manager._popouts[editor]
        self.plot("Second")
        QCoreApplication.sendEvent(dialog, QEvent(QEvent.WindowActivate))
        self.assertIs(self.manager.active_document, first)
        with patch("ui.main_window.QInputDialog.getText", return_value=("Window name", True)):
            editor._save_plot_button.click()
        self.assertEqual(first.name, "Window name")
        self.assertIn("Second", self.window._workspace.plot_names())

    def test_popout_close_tab_project_replace_and_cancel_close_lifecycle(self) -> None:
        plot = self.plot()
        editor = self.manager._active_editor
        self.manager.toggle_popout(editor)
        dialog = self.manager._popouts[editor]
        with patch("ui.main_window.QMessageBox.exec", return_value=QMessageBox.Cancel):
            self.assertFalse(self.window.close())
        self.assertIn(editor, self.manager._popouts)
        self.manager.close_tab(self.manager.tabs.indexOf(editor))
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(dialog))
        self.assertFalse(isValid(editor))
        self.manager.open_plot(plot.name)
        editor = self.manager._active_editor
        self.manager.toggle_popout(editor)
        dialog = self.manager._popouts[editor]
        self.window._workspace = Workspace()
        self.manager.set_workspace(self.window._workspace)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(dialog))
        self.assertFalse(isValid(editor))

    def test_popout_inspector_toggle_is_local_and_project_save_captures_fields(self) -> None:
        plot = self.plot()
        editor = self.manager._active_editor
        self.manager.toggle_popout(editor)
        editor.set_plot_options_visible(False)
        self.assertTrue(editor.options_widget().isHidden())
        self.manager._return_to_tab(editor)
        self.assertFalse(self.window._plot_inspector_enabled)
        self.manager.toggle_popout(editor)
        self.assertTrue(editor.options_widget().isHidden())
        editor.set_plot_options_visible(True)
        self.assertFalse(editor.options_widget().isHidden())
        editor._title_edit.setText("Changed in window")
        editor._series_label_edit.setText("Pending in window")
        with tempfile.TemporaryDirectory() as folder:
            self.window._project_path = Path(folder) / "popout.jasc"
            self.window._save_project()
            loaded = project_io.load_project(self.window._project_path)
        self.assertEqual(loaded.get_plot(plot.name).state["settings"]["title"], "Changed in window")
        self.assertEqual(loaded.get_plot(plot.name).editor_state["controls"]["_series_label_edit"]["value"],
                         "Pending in window")

    def test_open_existing_activates_view_without_reload(self) -> None:
        first = self.plot()
        self.manager._title_edit.setText("Edited")
        self.window._refresh_plot_list(first.name)
        count = self.manager.tabs.count()
        with patch.object(self.manager._active_editor, "load_plot_state") as load:
            self.window._load_selected_plot()
            self.window._load_selected_plot()
            load.assert_not_called()
        self.assertEqual(self.manager.tabs.count(), count)
        self.assertEqual(self.manager._title_edit.text(), "Edited")

    def test_close_releases_canvas_and_reopen_restores_pending_fields_and_zoom(self) -> None:
        first = self.plot()
        editor = self.manager._active_editor
        editor._series_label_edit.setText("Pending")
        editor._plot_canvas.axes.set_xlim(0.25, 1.25)
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.assertIn(first.name, self.window._workspace.plot_names())
        self.assertNotIn(first.plot_id, self.manager._editors)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(editor))
        self.manager.open_plot(first.name)
        self.assertEqual(self.manager._series_label_edit.text(), "Pending")
        self.assertTrue(self.manager.has_unapplied_series_edits())
        self.assertEqual(tuple(self.manager._plot_canvas.axes.get_xlim()), (0.25, 1.25))

    def test_save_project_captures_all_tabs_closed_documents_and_pending_editor(self) -> None:
        first = self.plot("First")
        self.manager._title_edit.setText("Changed first")
        self.manager._series_label_edit.setText("Pending label")
        self.manager.close_tab(self.manager.tabs.currentIndex())
        second = self.plot("Second")
        self.manager._title_edit.setText("Changed second")
        with tempfile.TemporaryDirectory() as folder:
            self.window._project_path = Path(folder) / "plots.jasc"
            self.window._save_project()
            self.assertFalse(self.manager.is_dirty())
            self.assertNotIn(" *", self.window.windowTitle())
            loaded = project_io.load_project(self.window._project_path)
        self.assertEqual(loaded.get_plot(first.name).plot_id, first.plot_id)
        self.assertEqual(loaded.get_plot(second.name).state["settings"]["title"], "Changed second")
        self.manager.set_workspace(loaded)
        self.window._workspace = loaded
        self.manager.open_plot(first.name)
        self.assertEqual(self.manager._title_edit.text(), "Changed first")
        self.assertEqual(self.manager._series_label_edit.text(), "Pending label")
        self.assertTrue(self.manager.has_unapplied_series_edits())
        self.assertFalse(self.manager.is_dirty())

    def test_incomplete_global_field_is_restored_without_losing_applied_plot(self) -> None:
        plot = self.plot()
        self.manager._x_min_edit.setText("incomplete")
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.manager.open_plot(plot.name)
        self.assertEqual(self.manager._x_min_edit.text(), "incomplete")
        self.assertEqual(len(self.manager._plot_series), 1)
        self.assertTrue(self.manager.is_dirty())

    def test_identity_survives_rename_and_duplicate_is_independent(self) -> None:
        first = self.plot()
        identity = first.plot_id
        self.manager.rename_active("Renamed")
        self.assertEqual(first.plot_id, identity)
        self.assertEqual(self.window._active_plot_name, "Renamed")
        self.window._duplicate_selected_plot()
        duplicate = self.manager.active_document
        self.assertNotEqual(duplicate.plot_id, identity)
        self.manager._title_edit.setText("Only the copy")
        self.manager.open_plot(first.name)
        self.assertEqual(self.manager._title_edit.text(), "Spectrum")
        self.assertNotEqual(first.state, duplicate.state)

    def test_rename_cannot_overwrite_another_document(self) -> None:
        first, second = self.plot("A"), self.plot("B")
        with patch("ui.main_window.QInputDialog.getText", return_value=("A", True)):
            self.assertFalse(self.window._save_current_plot())
        self.assertEqual(first.name, "A")
        self.assertEqual(second.name, "B")
        self.warning.assert_called_once()

    def test_delete_is_distinct_from_close_and_does_not_change_other_plot(self) -> None:
        first, second = self.plot("A"), self.plot("B")
        before = deepcopy(first.state)
        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window._delete_selected_plot()
        self.assertNotIn(second.name, self.window._workspace.plot_names())
        self.assertEqual(self.window._workspace.get_plot(first.name).state, before)
        self.assertEqual(self.manager.active_document.plot_id, first.plot_id)

    def test_per_document_undo_redo_survives_tab_switch(self) -> None:
        first = self.plot("A")
        self.manager._finish_history_group()
        self.manager._title_edit.setText("Changed A")
        second = self.plot("B")
        self.manager._finish_history_group()
        self.manager._title_edit.setText("Changed B")
        self.manager.open_plot(first.name)
        self.assertTrue(self.manager.undo())
        self.assertEqual(self.manager._title_edit.text(), "A")
        self.assertEqual(second.state["settings"]["title"], "Changed B")
        self.assertTrue(self.manager.redo())
        self.assertEqual(self.manager._title_edit.text(), "Changed A")

    def test_inspector_tracks_active_view(self) -> None:
        first = self.plot("A")
        first_inspector = self.manager._active_editor.options_widget()
        self.plot("B")
        self.assertIsNot(self.manager.options_widget().currentWidget(), first_inspector)
        self.manager.open_plot(first.name)
        self.assertIs(self.manager.options_widget().currentWidget(), first_inspector)

    def test_dataset_rename_keeps_open_and_closed_plot_bindings_and_pending_edits(self) -> None:
        first = self.plot("A")
        self.manager._series_label_edit.setText("Staged label")
        self.manager.close_tab(self.manager.tabs.currentIndex())
        second = self.plot("B")
        self.manager.flush()
        self.window._workspace.rename_dataset("signal", "Renamed data")
        self.manager.dataset_renamed("signal", "Renamed data")
        for plot in (first, second):
            self.assertEqual(plot.state["series"][0]["x_dataset"], "Renamed data")
        self.manager.open_plot(first.name)
        self.assertEqual(self.manager._series_label_edit.text(), "Staged label")
        self.assertEqual(self.manager._y_dataset_combo.currentText(), "Renamed data")
        self.assertFalse(self.manager.can_undo())

    def test_column_rename_preserves_pending_fields_on_closed_plot(self) -> None:
        first = self.plot()
        self.manager._series_label_edit.setText("Keep this")
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.data.frame.rename(columns={"y": "voltage"}, inplace=True)
        self.window._workspace.rename_column_references_in_plots("signal", {"y": "voltage"})
        self.manager.rename_column_references("signal", {"y": "voltage"})
        self.manager.open_plot(first.name)
        self.assertEqual(self.manager._y_column_combo.currentText(), "voltage")
        self.assertEqual(self.manager._series_label_edit.text(), "Keep this")
        self.assertFalse(self.manager.can_undo())

    def test_missing_dataset_retains_document_and_other_plots(self) -> None:
        first = self.plot()
        self.manager.close_tab(self.manager.tabs.currentIndex())
        self.window._workspace.remove_dataset("signal")
        self.manager.open_plot(first.name)
        self.assertIn(first.name, self.window._workspace.plot_names())
        self.assertEqual(first.state["series"][0]["y_dataset"], "signal")

    def test_open_plot_with_deleted_source_keeps_bindings_visible(self) -> None:
        first = self.plot()
        self.window._workspace.remove_dataset("signal")
        self.manager.dataset_removed("signal")
        self.assertEqual(self.manager._y_dataset_combo.currentText(), "signal")
        self.assertEqual(first.state["series"][0]["y_dataset"], "signal")

    def test_legacy_archive_without_document_fields_loads(self) -> None:
        plot = self.plot()
        with tempfile.TemporaryDirectory() as folder:
            modern, legacy = Path(folder) / "modern.jasc", Path(folder) / "legacy.jasc"
            project_io.save_project(self.window._workspace, modern)
            with zipfile.ZipFile(modern) as archive:
                members = {name: archive.read(name) for name in archive.namelist() if name != "integrity.json"}
            metadata = json.loads(members["project.json"])
            metadata["version"] = 4
            for entry in metadata["plots"]:
                entry.pop("plot_id", None)
                entry.pop("editor_state", None)
            members["project.json"] = json.dumps(metadata).encode("utf-8")
            with zipfile.ZipFile(legacy, "w") as archive:
                for name, value in members.items():
                    archive.writestr(name, value)
            loaded = project_io.load_project(legacy)
        self.assertEqual(json.dumps(loaded.get_plot(plot.name).state, sort_keys=True), json.dumps(plot.state, sort_keys=True))
        self.assertTrue(loaded.get_plot(plot.name).plot_id)

    def test_encrypted_project_preserves_identity_and_pending_editor(self) -> None:
        plot = self.plot()
        self.manager._series_label_edit.setText("Pending encrypted label")
        self.manager.flush()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plots.jascx"
            project_io.save_project(self.window._workspace, path, password="PlotTest-Password-2026")
            loaded = project_io.load_project(path, password="PlotTest-Password-2026")
        restored = loaded.get_plot(plot.name)
        self.assertEqual(restored.plot_id, plot.plot_id)
        self.assertEqual(restored.editor_state["controls"]["_series_label_edit"]["value"], "Pending encrypted label")

    def test_project_close_uses_one_save_decision(self) -> None:
        self.plot()
        with patch("ui.main_window.QMessageBox.exec", return_value=QMessageBox.Discard) as prompt, \
                patch("ui.main_window.QMessageBox.question") as extra:
            self.window._close_project()
        prompt.assert_called_once()
        extra.assert_not_called()
        self.assertEqual(self.window._workspace.plot_names(), [])

    def test_old_plot_without_document_metadata_loads(self) -> None:
        plot = self.plot()
        workspace = Workspace()
        source = workspace.add_dataset("signal", self.data.frame)
        old = workspace.add_plot("Old", plot.state)
        self.manager.set_workspace(workspace)
        self.window._workspace = workspace
        self.manager.open_plot(old.name)
        self.assertTrue(self.manager.has_plot_series())
        self.assertEqual(self.manager.active_document.plot_id, old.plot_id)

    def test_duplicate_document_ids_are_rejected(self) -> None:
        plot = self.plot()
        with self.assertRaisesRegex(ValueError, "Duplicate plot"):
            self.window._workspace.add_plot("B", {}, plot_id=plot.plot_id)

    def test_application_close_cancel_preserves_everything(self) -> None:
        plot = self.plot()
        with patch("ui.main_window.QMessageBox.exec", return_value=QMessageBox.Cancel):
            self.assertFalse(self.window.close())
        self.assertFalse(self.window._closing_when_idle)
        self.assertIn(plot.name, self.window._workspace.plot_names())

    def test_cancelled_save_dialog_prevents_close(self) -> None:
        self.plot()
        with patch("ui.main_window.QMessageBox.exec", return_value=QMessageBox.Save), \
                patch("ui.main_window.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertFalse(self.window.close())
        self.assertTrue(self.manager.is_dirty())

    def test_save_failure_prevents_close_and_retains_dirty_state(self) -> None:
        self.plot()
        self.window._project_path = Path(tempfile.gettempdir()) / "jasc-intentionally-not-written.jasc"
        with patch("ui.main_window.QMessageBox.exec", return_value=QMessageBox.Save), \
                patch("ui.main_window.project_io.save_project", side_effect=OSError("test failure")), \
                patch("ui.main_window.QMessageBox.critical"):
            self.assertFalse(self.window.close())
        self.assertTrue(self.manager.is_dirty())

    def test_save_then_close_persists_latest_changes(self) -> None:
        plot = self.plot()
        self.manager._title_edit.setText("Latest")
        with tempfile.TemporaryDirectory() as folder:
            self.window._project_path = Path(folder) / "saved.jasc"
            with patch("ui.main_window.QMessageBox.exec", return_value=QMessageBox.Save):
                self.assertTrue(self.window.close())
            loaded = project_io.load_project(self.window._project_path)
            self.assertEqual(loaded.get_plot(plot.name).state["settings"]["title"], "Latest")


if __name__ == "__main__":
    unittest.main()
