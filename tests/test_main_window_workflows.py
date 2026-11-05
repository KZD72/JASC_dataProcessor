"""Focused GUI workflow tests that run with Qt's offscreen platform."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QMenu,
    QMessageBox,
    QSpinBox,
    QStyle,
    QStyleFactory,
    QStyleOptionSpinBox,
)

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
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
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

    def test_spin_box_increment_and_decrement_buttons_are_separate_and_clickable(self) -> None:
        """Keep both spinner directions reliable under Qt's Windows 11 style."""
        if "windows11" not in {name.lower() for name in QStyleFactory.keys()}:
            self.skipTest("Qt Windows 11 style is not available")

        plot_tab = self.window._plot_tab_widget
        spin_boxes: tuple[QSpinBox | QDoubleSpinBox, ...] = (
            plot_tab._histogram_bins_spin,
            plot_tab._line_width_spin,
        )
        for spin in spin_boxes:
            with self.subTest(spin_type=type(spin).__name__):
                windows_style = QStyleFactory.create("windows11")
                # QWidget.setStyle() does not transfer ownership. Parent the
                # temporary native style to the target widget so older PySide6
                # releases do not destroy it before/after the widget at process
                # shutdown and trigger a Windows access violation.
                windows_style.setParent(spin)
                spin.setStyle(windows_style)
                spin.ensurePolished()
                self.app.processEvents()
                option = QStyleOptionSpinBox()
                spin.initStyleOption(option)
                up_rect = spin.style().subControlRect(
                    QStyle.CC_SpinBox,
                    option,
                    QStyle.SC_SpinBoxUp,
                    spin,
                )
                down_rect = spin.style().subControlRect(
                    QStyle.CC_SpinBox,
                    option,
                    QStyle.SC_SpinBoxDown,
                    spin,
                )

                self.assertEqual(up_rect.center().x(), down_rect.center().x())
                self.assertLess(up_rect.center().y(), down_rect.center().y())
                starting_value = spin.value()
                QTest.mouseClick(spin, Qt.LeftButton, pos=up_rect.center())
                self.assertGreater(spin.value(), starting_value)
                QTest.mouseClick(spin, Qt.LeftButton, pos=down_rect.center())
                self.assertAlmostEqual(float(spin.value()), float(starting_value))

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

    def test_new_plot_preserves_existing_document_without_prompt(self) -> None:
        self._queue_unsaved_plot()
        document = self.window._plot_tab_widget.active_document
        with patch.object(QMessageBox, "exec") as prompt:
            self.assertTrue(self.window._start_new_plot())
        prompt.assert_not_called()
        self.assertFalse(self.window._plot_tab_widget.has_plot_series())
        self.window._plot_tab_widget.open_plot(document.name)
        self.assertTrue(self.window._plot_tab_widget.has_plot_series())

    def test_closing_new_tab_preserves_document(self) -> None:
        self._queue_unsaved_plot()
        manager = self.window._plot_tab_widget
        document = manager.active_document
        manager.close_tab(manager.tabs.currentIndex())
        self.assertIn(document.name, self.window._workspace.plot_names())
        manager.open_plot(document.name)
        self.assertTrue(manager.has_plot_series())

    def test_new_plot_does_not_require_separate_save(self) -> None:
        self._queue_unsaved_plot()
        with patch.object(self.window, "_save_current_plot") as rename:
            self.window._start_new_plot()
        rename.assert_not_called()
        self.assertEqual(len(self.window._workspace.plot_names()), 2)

    def test_pending_series_edits_are_retained_in_document(self) -> None:
        self._queue_unsaved_plot()
        manager = self.window._plot_tab_widget
        manager._series_label_edit.setText("Staged label")
        self.assertTrue(manager.has_unapplied_series_edits())
        manager.flush()
        self.assertTrue(manager.active_document.editor_state["series_dirty"])
        self.assertEqual(manager.active_document.editor_state["controls"]["_series_label_edit"]["value"], "Staged label")

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
            "Duplicate Sheet",
            "Rename...",
            "Remove Dataset",
            "Extract Subset...",
        }.issubset(set(dataset_texts)))

    def test_extract_subset_creates_new_sheet_and_preserves_column_metadata(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "source",
            pd.DataFrame({
                "x": [1, 2, 3, 4, 5],
                "y": [10, 20, 30, 40, 50],
                "z": [100, 200, 300, 400, 500],
                "note": ["a", "b", "c", "d", "e"],
            }),
        )
        dataset.metadata_for_column("x").role = "x"
        self.window._refresh_dataset_list(dataset.name)

        class FakeSubsetDialog:
            Accepted = QDialog.Accepted

            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            @staticmethod
            def exec() -> int:
                return QDialog.Accepted

            @staticmethod
            def row_mode() -> str:
                return "odd"

            @staticmethod
            def row_step() -> int:
                return 2

            @staticmethod
            def row_start() -> int:
                return 1

            @staticmethod
            def column_mode() -> str:
                return "odd"

            @staticmethod
            def column_step() -> int:
                return 2

            @staticmethod
            def column_start() -> int:
                return 1

            @staticmethod
            def output_name() -> str:
                return "sampled"

        with patch("ui.main_window.PositionalSubsetDialog", FakeSubsetDialog):
            self.window._run_extract_subset()

        result = self.window._workspace.get_dataset("sampled")
        self.assertEqual(result.frame.columns.tolist(), ["x", "z"])
        self.assertEqual(result.frame["x"].tolist(), [1, 3, 5])
        self.assertEqual(result.column_metadata["x"].role, "x")
        self.assertIn("Extract positional subset", result.column_metadata["x"].comment)

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
                "New Plot",
                "Rename Current Plot...",
                "Open Plot",
                "Duplicate Plot",
                "Delete Plot",
                "Compare Plots...",
            ],
        )

    def test_workspace_actions_duplicate_sheet_and_saved_plot(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "signal",
            pd.DataFrame({"x": [0.0, 1.0], "y": [1.0, 2.0]}),
        )
        dataset.formulas["y"] = 'col("x") + 1'
        dataset.metadata_for_column("y").unit = "V"
        dataset.sync_column_metadata_attrs()
        self.window._refresh_dataset_list(dataset.name)

        self.window._duplicate_current_dataset()

        duplicate = self.window._workspace.get_dataset("signal Copy")
        self.assertEqual(self.window._current_dataset().name, duplicate.name)
        pd.testing.assert_frame_equal(duplicate.frame, dataset.frame)
        self.assertEqual(duplicate.formulas, dataset.formulas)
        self.assertEqual(duplicate.column_metadata["y"].unit, "V")

        saved = self.window._workspace.add_plot(
            "Saved",
            self.window._plot_tab_widget.current_plot_state(),
        )
        self.window._refresh_plot_list(saved.name)
        self.window._duplicate_selected_plot()

        self.assertIn("Saved Copy", self.window._workspace.plot_names())
        self.assertEqual(self.window._active_plot_name, "Saved Copy")
        self.assertEqual(self.window._selected_plot_name(), "Saved Copy")

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

    def test_plot_inspector_remains_usable_at_narrow_window_width(self) -> None:
        """Regression: dock relayout must not collapse spin-box editors to zero."""
        self.window._tabs.setCurrentWidget(self.window._plot_tab_widget)
        self.window.resize(720, 640)
        self.window._apply_responsive_layout()
        self.window._plot_tab_widget._options_tabs.setCurrentIndex(1)
        self.app.processEvents()

        plot_tab = self.window._plot_tab_widget
        typography_controls = (
            plot_tab._x_label_size_spin,
            plot_tab._x_tick_size_spin,
            plot_tab._y_label_size_spin,
            plot_tab._y_tick_size_spin,
            plot_tab._right_y_label_size_spin,
            plot_tab._right_y_tick_size_spin,
        )
        self.assertLessEqual(self.window.width(), 720)
        self.assertGreaterEqual(self.window.centralWidget().width(), 240)
        for spin in typography_controls:
            with self.subTest(control=spin.objectName() or type(spin).__name__):
                self.assertGreaterEqual(spin.width(), 90)
                self.assertGreater(spin.lineEdit().width(), 0)

    def test_responsive_docks_recalculate_after_window_resize(self) -> None:
        """Keep docks proportional and wholly inside repeated size changes."""
        self.window._tabs.setCurrentWidget(self.window._plot_tab_widget)
        for width in (760, 1200, 820):
            with self.subTest(width=width):
                self.window.resize(width, 700)
                self.window._apply_responsive_layout()
                self.app.processEvents()
                self.assertLessEqual(
                    self.window._workspace_dock.width()
                    + self.window._inspector_dock.width()
                    + self.window.centralWidget().width(),
                    self.window.width(),
                )
                self.assertGreaterEqual(self.window.centralWidget().width(), 240)
                self.assertGreaterEqual(self.window._inspector_dock.width(), 260)

    def test_compact_plot_layout_collapses_workspace_but_allows_override(self) -> None:
        """Reserve useful canvas width on very small logical screens."""
        self.window._tabs.setCurrentWidget(self.window._plot_tab_widget)
        self.window.resize(640, 600)
        self.window._apply_responsive_layout()
        self.app.processEvents()
        self.assertFalse(self.window._workspace_dock.isVisible())
        self.assertGreaterEqual(self.window.centralWidget().width(), 300)

        self.window._set_sidebar_visible(True)
        self.window._apply_responsive_layout()
        self.app.processEvents()
        self.assertTrue(self.window._workspace_dock.isVisible())

    def test_initial_geometry_and_plot_toolbar_fit_available_screen(self) -> None:
        """Use logical screen geometry and an overflow-capable action bar."""
        available = self.window.screen().availableGeometry()
        self.assertLessEqual(self.window.width(), available.width())
        self.assertLessEqual(self.window.height(), available.height())
        self.assertLess(
            self.window._plot_tab_widget._plot_actions_toolbar.minimumSizeHint().width(),
            250,
        )

    def test_plot_option_visibility_updates_are_idempotent(self) -> None:
        """Repeated dock synchronization must not create a visibility loop."""
        plot_tab = self.window._plot_tab_widget
        emissions: list[bool] = []
        plot_tab.options_visibility_changed.connect(emissions.append)
        plot_tab.set_plot_options_visible(True)
        plot_tab.set_plot_options_visible(True)
        plot_tab.set_plot_options_visible(False)
        plot_tab.set_plot_options_visible(False)
        self.assertEqual(emissions, [False])


if __name__ == "__main__":
    unittest.main()
