"""Regression tests for optimized clipboard, editor refresh, and project I/O paths."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from core import project_io
from core.clipboard_io import parse_tabular_clipboard
from core.workspace import Workspace
from ui.dataframe_model import DataFrameTableModel
from ui.main_window import MainWindow


class ClipboardBlockTests(unittest.TestCase):
    """Protect clipboard token semantics and block-oriented model updates."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_parser_preserves_text_columns_quotes_and_embedded_newlines(self) -> None:
        block = parse_tabular_clipboard(
            '001\t"a\tb"\n002\t"line 1\nline 2"\n',
            text_columns={0},
        )

        self.assertEqual(block.shape, (2, 2))
        self.assertEqual(block.iloc[0, 0], "001")
        self.assertEqual(block.iloc[0, 1], "a\tb")
        self.assertEqual(block.iloc[1, 1], "line 1\nline 2")

    def test_block_paste_grows_once_and_round_trips_through_undo(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset(
            "sheet",
            pd.DataFrame(
                {
                    "x": pd.Series([float("nan")] * 25, dtype="float64"),
                    "label": pd.Series([pd.NA] * 25, dtype="object"),
                }
            ),
        )
        dataset.formulas["x"] = "col1 * 2"
        model = DataFrameTableModel()
        model.set_dataset(dataset)
        block = parse_tabular_clipboard(
            "\n".join(f"{index}\titem-{index}\t{index + 1}" for index in range(1_000)),
            text_columns={1},
        )

        pasted_shape = model.paste_block(0, 0, block)

        self.assertEqual(pasted_shape, (1_000, 3))
        self.assertEqual(dataset.frame.shape, (1_000, 3))
        self.assertEqual(dataset.frame.iloc[999, 0], 999.0)
        self.assertEqual(dataset.frame.iloc[999, 1], "item-999")
        self.assertEqual(dataset.frame.iloc[999, 2], "1000")
        self.assertNotIn("x", dataset.formulas)

        self.assertTrue(model.undo())
        self.assertEqual(dataset.frame.shape, (25, 2))
        self.assertEqual(dataset.formulas["x"], "col1 * 2")
        self.assertTrue(model.redo())
        self.assertEqual(dataset.frame.shape, (1_000, 3))

    def test_numeric_metadata_rejects_invalid_clipboard_without_history_entry(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset("sheet", pd.DataFrame({"x": [1.0, 2.0]}))
        dataset.metadata_for_column("x").value_type = "numeric"
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        with self.assertRaisesRegex(ValueError, "not numeric"):
            model.paste_block(0, 0, pd.DataFrame([["bad"]]))

        self.assertFalse(model.can_undo())
        self.assertEqual(dataset.frame["x"].tolist(), [1.0, 2.0])

    def test_whole_column_paste_bulk_grows_and_infers_numeric_values(self) -> None:
        dataset = Workspace().add_dataset("sheet", pd.DataFrame({"existing": [1, 2]}))
        model = DataFrameTableModel()
        model.set_dataset(dataset)
        block = parse_tabular_clipboard("1\ta\n2\tb\n3\tc")

        inserted = model.insert_columns(0, ["number", "label"], block)

        self.assertEqual(inserted, ["number", "label"])
        self.assertEqual(dataset.frame.shape, (3, 3))
        self.assertEqual(dataset.frame["number"].tolist(), [1, 2, 3])
        self.assertEqual(dataset.frame["label"].tolist(), ["a", "b", "c"])
        self.assertTrue(model.undo())
        self.assertEqual(dataset.frame.shape, (2, 1))

    def test_clear_cells_preserves_shape_and_is_one_undoable_edit(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"x": [1, 2, 3], "y": [4.0, 5.0, 6.0]}),
        )
        dataset.formulas = {"x": "col1 * 2", "y": "col2 + 1"}
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        cleared = model.clear_cells([(0, 0, 1, 0), (2, 1, 2, 1)])

        self.assertEqual(cleared, 3)
        self.assertEqual(dataset.frame.shape, (3, 2))
        self.assertTrue(dataset.frame.iloc[:2, 0].isna().all())
        self.assertTrue(pd.isna(dataset.frame.iloc[2, 1]))
        self.assertEqual(dataset.frame.iloc[2, 0], 3.0)
        self.assertNotIn("x", dataset.formulas)
        self.assertNotIn("y", dataset.formulas)
        self.assertTrue(model.undo())
        pd.testing.assert_frame_equal(
            dataset.frame,
            pd.DataFrame({"x": [1, 2, 3], "y": [4.0, 5.0, 6.0]}),
        )

    def test_resize_sheet_changes_both_dimensions_and_restores_metadata_on_undo(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]}),
        )
        dataset.formulas["y"] = "col1 * 2"
        dataset.metadata_for_column("y").unit = "V"
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        self.assertEqual(model.resize_sheet(2, 1), (2, 1))
        self.assertEqual(dataset.frame.shape, (2, 1))
        self.assertNotIn("y", dataset.formulas)
        self.assertNotIn("y", dataset.column_metadata)
        self.assertTrue(model.undo())
        self.assertEqual(dataset.frame.shape, (3, 2))
        self.assertEqual(dataset.formulas["y"], "col1 * 2")
        self.assertEqual(dataset.column_metadata["y"].unit, "V")

        self.assertEqual(model.resize_sheet(5, 4), (5, 4))
        self.assertEqual(dataset.frame.shape, (5, 4))
        self.assertEqual(list(dataset.frame.columns[:2]), ["x", "y"])
        self.assertTrue(dataset.frame.iloc[3:, :].isna().all().all())

    def test_large_fill_range_uses_bulk_growth_and_assignment(self) -> None:
        dataset = Workspace().add_dataset("sheet", pd.DataFrame({"x": [float("nan")]}))
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        result_column = model.fill_range("x", 1, 10_000, 0.0, 0.5)

        self.assertEqual(result_column, "x")
        self.assertEqual(dataset.frame.shape, (10_000, 1))
        self.assertEqual(dataset.frame.iloc[-1, 0], 4_999.5)

    def test_history_is_bounded_by_entry_count(self) -> None:
        dataset = Workspace().add_dataset("sheet", pd.DataFrame({"x": [0.0]}))
        model = DataFrameTableModel()
        model._max_history_entries = 3
        model.set_dataset(dataset)

        index = model.index(0, 0)
        for value in range(1, 7):
            self.assertTrue(model.setData(index, str(value), Qt.EditRole))

        self.assertEqual(len(model._undo_stack), 3)

    def test_oversized_history_snapshot_is_not_copied_or_retained(self) -> None:
        dataset = Workspace().add_dataset("sheet", pd.DataFrame({"x": [0.0]}))
        model = DataFrameTableModel()
        model._max_history_bytes = 1
        model.set_dataset(dataset)

        with patch.object(model, "_snapshot", side_effect=AssertionError("snapshot copied")):
            self.assertTrue(model.setData(model.index(0, 0), "1", Qt.EditRole))

        self.assertFalse(model.can_undo())


class EditorRefreshTests(unittest.TestCase):
    """Ensure dataset attachment and history changes avoid redundant table scans."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()

    def test_dataset_list_refresh_attaches_and_sizes_once(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": range(1_000), "y": range(1_000)}),
        )
        with (
            patch.object(
                self.window,
                "_show_dataset_editor",
                wraps=self.window._show_dataset_editor,
            ) as show_editor,
            patch.object(
                self.window,
                "_resize_dataset_columns_to_contents",
                wraps=self.window._resize_dataset_columns_to_contents,
            ) as resize_columns,
        ):
            self.window._refresh_dataset_list(dataset.name)

        self.assertEqual(show_editor.call_count, 1)
        self.assertEqual(resize_columns.call_count, 1)

    def test_cell_edit_does_not_trigger_column_resizing(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0], "y": [2.0]}),
        )
        self.window._show_dataset_editor(dataset.name)

        with patch.object(self.window, "_resize_dataset_columns_to_contents") as resize_columns:
            changed = self.window._dataset_model.setData(
                self.window._dataset_model.index(0, 0),
                "3",
                Qt.EditRole,
            )

        self.assertTrue(changed)
        resize_columns.assert_not_called()

    def test_clipboard_availability_check_does_not_parse_contents(self) -> None:
        QApplication.clipboard().setText("1\t2\n3\t4")

        with (
            patch.object(
                self.window,
                "_parse_clipboard_text",
                side_effect=AssertionError("clipboard was parsed eagerly"),
            ),
            patch.object(
                self.window,
                "_clipboard_dataset_columns",
                side_effect=AssertionError("clipboard columns were decoded eagerly"),
            ),
        ):
            self.assertTrue(self.window._clipboard_has_dataset_columns())

    def test_large_selection_context_menu_does_not_enumerate_selected_cells(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "large",
            pd.DataFrame({f"c{column}": range(20_000) for column in range(12)}),
        )
        self.window._refresh_dataset_list(dataset.name)
        self.window._dataset_table.selectAll()

        with (
            patch.object(
                self.window,
                "_selected_dataset_indexes",
                side_effect=AssertionError("context menu enumerated selected cells"),
            ),
            patch.object(
                self.window,
                "_selected_dataset_columns",
                side_effect=AssertionError("context menu expanded selected columns"),
            ),
            patch("ui.main_window.QMenu") as menu_class,
        ):
            menu_class.return_value.exec.return_value = None
            self.window._show_dataset_editor_context_menu(QPoint(0, 0), context_column=0)

        action_labels = [
            call.args[0]
            for call in menu_class.return_value.addAction.call_args_list
            if call.args
        ]
        self.assertIn("Copy Row(s)", action_labels)
        self.assertIn("Paste Values Transposed", action_labels)
        self.assertIn("Clear Selected Cell Values", action_labels)
        self.assertIn("Resize Sheet...", action_labels)

    def test_delete_clears_cells_and_modified_delete_removes_structure(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]}),
        )
        self.window._refresh_dataset_list(dataset.name)
        self.window.show()
        self.window._dataset_table.setFocus()
        self.window._dataset_table.selectRow(1)
        self.app.processEvents()

        QTest.keyClick(self.window._dataset_table, Qt.Key_Delete)
        self.app.processEvents()
        self.assertEqual(len(dataset.frame), 3)
        self.assertEqual(list(dataset.frame.columns), ["x", "y"])
        self.assertTrue(dataset.frame.iloc[1].isna().all())

        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question,
            patch.object(QMessageBox, "information") as information,
        ):
            QTest.keyClick(
                self.window._dataset_table,
                Qt.Key_Delete,
                Qt.ShiftModifier,
            )
            self.app.processEvents()
        self.assertTrue(question.called)
        information.assert_not_called()
        self.assertEqual(len(dataset.frame), 2)

        self.window._select_dataset_column_range(0, 1)
        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question,
            patch.object(QMessageBox, "information") as information,
        ):
            QTest.keyClick(
                self.window._dataset_table,
                Qt.Key_Delete,
                Qt.ControlModifier,
            )
            self.app.processEvents()
        self.assertTrue(question.called)
        information.assert_not_called()
        self.assertEqual(list(dataset.frame.columns), ["y"])
        self.assertEqual(self.window._delete_cells_action.shortcut().toString(), "Del")
        self.assertEqual(self.window._delete_rows_action.shortcut().toString(), "Shift+Del")
        self.assertEqual(self.window._delete_columns_action.shortcut().toString(), "Ctrl+Del")

    def test_transposed_paste_rotates_the_complete_clipboard_matrix(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"a": [0.0, 0.0, 0.0], "b": [0.0, 0.0, 0.0]}),
        )
        self.window._refresh_dataset_list(dataset.name)
        self.window._dataset_table.setCurrentIndex(self.window._dataset_model.index(0, 0))
        QApplication.clipboard().setText("1\t2\t3\n4\t5\t6")

        self.window._paste_dataset_clipboard(transpose=True)

        self.assertEqual(dataset.frame.iloc[:3, :2].values.tolist(), [[1, 4], [2, 5], [3, 6]])
        self.assertEqual(
            self.window._dataset_table.selectionModel().selection()[0].bottom(),
            2,
        )

    def test_row_header_context_selects_rows_and_body_menu_remains_available(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"a": [1, 2], "b": [3, 4]}),
        )
        self.window._refresh_dataset_list(dataset.name)
        header = self.window._dataset_table.verticalHeader()
        row_position = QPoint(2, header.sectionViewportPosition(1) + 2)

        with patch.object(self.window, "_show_dataset_editor_context_menu") as show_menu:
            self.window._show_dataset_row_header_context_menu(row_position)

        self.assertEqual(self.window._selected_dataset_rows(), [1])
        self.assertEqual(self.window._selected_dataset_columns(), [0, 1])
        self.assertEqual(show_menu.call_args.kwargs["context_row"], 1)
        self.window._copy_dataset_rows()
        self.assertEqual(QApplication.clipboard().text(), "2\t4")
        self.assertEqual(
            self.window._dataset_table.viewport().contextMenuPolicy(),
            Qt.CustomContextMenu,
        )
        self.assertEqual(header.contextMenuPolicy(), Qt.CustomContextMenu)


class ProjectStreamingTests(unittest.TestCase):
    """Protect streamed project persistence and ownership-transfer behavior."""

    def test_project_round_trip_uses_streamed_dataset_members(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0, 2.0], "label": ["a", "b"]}),
        )
        dataset.metadata_for_column("x").role = "x"
        dataset.sync_column_metadata_attrs()

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "streamed.jasc"
            project_io.save_project(workspace, path)
            loaded = project_io.load_project(path)

        loaded_dataset = loaded.get_dataset("sheet")
        pd.testing.assert_frame_equal(loaded_dataset.frame, dataset.frame)
        self.assertEqual(loaded_dataset.column_metadata["x"].role, "x")

    def test_workspace_can_adopt_a_freshly_parsed_frame(self) -> None:
        frame = pd.DataFrame({"x": [1, 2, 3]})
        dataset = Workspace().add_dataset("sheet", frame, copy_frame=False)
        self.assertIs(dataset.frame, frame)


if __name__ == "__main__":
    unittest.main()
