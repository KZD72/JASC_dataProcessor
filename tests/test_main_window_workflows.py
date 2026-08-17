"""Focused GUI workflow tests that run with Qt's offscreen platform."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtWidgets import QApplication, QMessageBox

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
