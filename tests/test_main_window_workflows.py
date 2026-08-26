"""Focused GUI workflow tests that run with Qt's offscreen platform."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from ui.main_window import MainWindow


class MainWindowWorkflowTests(unittest.TestCase):
    """Exercise plot replacement safeguards and context-sensitive inspector state."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()

    def _queue_unsaved_plot(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "signal",
            pd.DataFrame({"x": [0.0, 1.0, 2.0], "y": [1.0, 2.0, 4.0]}),
        )
        self.window._plot_tab_widget.queue_single_series_plot(
            dataset,
            x_column="x",
            y_column="y",
            title="Working plot",
        )

    @staticmethod
    def _menu_texts(menu: QMenu) -> list[str]:
        """Return all visible action labels, including submenu entries."""
        texts: list[str] = []

        def collect(target: QMenu) -> None:
            for action in target.actions():
                if action.text():
                    texts.append(action.text())
                submenu = action.menu()
                if submenu is not None:
                    collect(submenu)

        collect(menu)
        return texts

    def test_new_plot_cancel_preserves_unsaved_draft(self) -> None:
        self._queue_unsaved_plot()
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Cancel):
            started = self.window._start_new_plot()
        self.assertFalse(started)
        self.assertTrue(self.window._plot_tab_widget.has_plot_series())

    def test_new_plot_discard_replaces_unsaved_draft(self) -> None:
        self._queue_unsaved_plot()
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Discard):
            started = self.window._start_new_plot()
        self.assertTrue(started)
        self.assertFalse(self.window._plot_tab_widget.has_plot_series())

    def test_new_plot_save_replaces_draft_only_after_successful_save(self) -> None:
        self._queue_unsaved_plot()
        with (
            patch.object(QMessageBox, "exec", return_value=QMessageBox.Save),
            patch.object(self.window, "_save_current_plot", return_value=True) as save_plot,
        ):
            started = self.window._start_new_plot()
        save_plot.assert_called_once_with()
        self.assertTrue(started)
        self.assertFalse(self.window._plot_tab_widget.has_plot_series())

    def test_staged_series_edits_must_be_resolved_before_saving(self) -> None:
        self._queue_unsaved_plot()
        tab = self.window._plot_tab_widget
        self.window._active_plot_baseline = self.window._plot_state_fingerprint()
        tab._series_label_edit.setText("Staged label")

        self.assertTrue(tab.has_unapplied_series_edits())
        self.assertTrue(self.window._plot_has_unsaved_changes())
        with patch.object(QMessageBox, "information") as information:
            saved = self.window._save_current_plot()

        self.assertFalse(saved)
        information.assert_called_once()
        self.assertEqual(self.window._workspace.plot_names(), [])

    def test_dataset_context_menus_expose_common_workflows(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "signal",
            pd.DataFrame({"x": [0.0, 1.0], "y": [1.0, 2.0]}),
        )
        self.window._refresh_dataset_list(dataset.name)

        dataset_menu, _actions = self.window._build_dataset_context_menu()
        dataset_texts = self._menu_texts(dataset_menu)
        self.assertTrue({
            "Open Sheet",
            "Create Plot from Dataset",
            "Export Dataset...",
            "Data Preparation",
            "Analysis",
            "Rename...",
            "Remove Dataset",
        }.issubset(set(dataset_texts)))

        editor_menu = QMenu(self.window)
        self.window._add_dataset_edit_submenus(
            editor_menu,
            has_dataset=True,
            has_selection=True,
            has_columns=True,
        )
        self.window._add_dataset_workflow_submenus(editor_menu)
        editor_texts = self._menu_texts(editor_menu)
        self.assertTrue({
            "Rows",
            "Columns",
            "Fill Range...",
            "Column Metadata...",
            "Data Preparation",
            "Analysis",
            "Curve Fit...",
        }.issubset(set(editor_texts)))

        plot_menu, _plot_actions = self.window._build_plot_context_menu("Saved")
        self.assertEqual(
            self._menu_texts(plot_menu),
            [
                "New Empty Plot",
                "Save Current Plot...",
                "Load Plot",
                "Remove Saved Plot",
            ],
        )

    def test_create_plot_from_dataset_prefills_new_series_editor(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "signal",
            pd.DataFrame({"time": [0.0, 1.0], "value": [1.0, 2.0]}),
        )
        dataset.metadata_for_column("time").role = "x"
        dataset.metadata_for_column("value").role = "y"
        self.window._refresh_dataset_list(dataset.name)

        self.window._start_plot_for_current_dataset()

        tab = self.window._plot_tab_widget
        self.assertIs(self.window._tabs.currentWidget(), tab)
        self.assertFalse(tab.has_plot_series())
        self.assertEqual(tab._x_dataset_combo.currentText(), dataset.name)
        self.assertEqual(tab._x_column_combo.currentText(), "time")
        self.assertEqual(tab._y_column_combo.currentText(), "value")

    def test_inspector_is_plot_specific(self) -> None:
        self.assertTrue(self.window._inspector_dock.isHidden())
        self.assertIs(self.window._dataset_summary.parent(), self.window._data_tab_widget)

        self.window._tabs.setCurrentWidget(self.window._plot_tab_widget)
        self.app.processEvents()
        self.assertFalse(self.window._inspector_dock.isHidden())
        self.assertEqual(self.window._inspector_dock.windowTitle(), "Plot Inspector")

        self.window._tabs.setCurrentWidget(self.window._data_tab_widget)
        self.app.processEvents()
        self.assertTrue(self.window._inspector_dock.isHidden())
        self.assertTrue(self.window._plot_inspector_enabled)


if __name__ == "__main__":
    unittest.main()
