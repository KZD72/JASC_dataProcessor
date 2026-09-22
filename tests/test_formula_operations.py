"""Formula evaluator and Apply Formula scope regression tests."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtWidgets import QApplication

from core.operations import (
    ExpressionError,
    apply_column_expression,
    evaluate_expression,
    referenced_worksheet_names,
)
from core.workspace import Workspace
from ui.dataframe_model import DataFrameTableModel
from ui.dialogs import ColumnExpressionDialog


class CrossWorksheetFormulaTests(unittest.TestCase):
    """Verify safe cross-worksheet lookup and row-position alignment."""

    def test_cross_worksheet_column_is_aligned_by_visible_row_position(self) -> None:
        target = pd.DataFrame({"local": [1.0, 2.0, 3.0]}, index=[10, 20, 30])
        source = pd.DataFrame({"value": [10.0, 20.0]}, index=[100, 200])

        result = evaluate_expression(
            target,
            'local + sheet("Source Sheet", "value")',
            worksheet_frames={"Source Sheet": source},
        )

        self.assertEqual(result.index.tolist(), [10, 20, 30])
        self.assertEqual(result.iloc[:2].tolist(), [11.0, 22.0])
        self.assertTrue(pd.isna(result.iloc[2]))

    def test_cross_worksheet_errors_name_the_missing_sheet_or_column(self) -> None:
        target = pd.DataFrame({"x": [1.0]})
        with self.assertRaisesRegex(ExpressionError, "Worksheet 'Missing' does not exist"):
            evaluate_expression(target, 'sheet("Missing", "x")')
        with self.assertRaisesRegex(ExpressionError, "Column 'missing'.*'Source'"):
            evaluate_expression(
                target,
                'sheet("Source", "missing")',
                worksheet_frames={"Source": pd.DataFrame({"x": [2.0]})},
            )

    def test_selected_cell_positions_only_update_requested_rows(self) -> None:
        frame = pd.DataFrame({"x": [1.0, 2.0, 3.0], "result": [9.0, 9.0, 9.0]})
        applied = apply_column_expression(
            frame,
            target_column="result",
            expression="x * 2",
            row_positions=[1],
        )

        self.assertEqual(applied.updated_rows, 1)
        self.assertEqual(frame["result"].tolist(), [9.0, 4.0, 9.0])

    def test_literal_sheet_dependencies_are_discovered(self) -> None:
        names = referenced_worksheet_names(
            'sheet("A", "x") + sheet("B", "y") + sheet("A", "z")'
        )
        self.assertEqual(names, {"A", "B"})

    def test_sheet_reference_requires_two_literal_names(self) -> None:
        target = pd.DataFrame({"x": [1.0]})
        with self.assertRaisesRegex(ExpressionError, "require quoted names"):
            evaluate_expression(
                target,
                "sheet(x, x)",
                worksheet_frames={"x": pd.DataFrame({"x": [2.0]})},
            )

    def test_renaming_a_worksheet_updates_stored_cross_sheet_formulas(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("Reference", pd.DataFrame({"x": [1.0]}))
        result = workspace.add_dataset("Result", pd.DataFrame({"y": [2.0]}))
        result.formulas["y"] = 'sheet("Reference", "x") * 2'

        workspace.rename_dataset("Reference", "Calibration")

        self.assertEqual(result.formulas["y"], "sheet('Calibration', 'x') * 2")


class FormulaDialogScopeTests(unittest.TestCase):
    """Verify explicit whole-column/cell scope and reference insertion controls."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_cell_scope_requires_selected_cells_in_target_column(self) -> None:
        dialog = ColumnExpressionDialog(
            ["x", "result"],
            selected_rows_available=True,
            default_target="result",
            dataset_names=["Current", "Reference"],
            current_dataset_name="Current",
            worksheet_columns={"Current": ["x", "result"], "Reference": ["value"]},
            selected_cell_columns={"result"},
        )
        try:
            self.assertEqual(dialog.operation_scope(), "column")
            dialog._operation_scope_combo.setCurrentIndex(1)
            self.assertEqual(dialog.operation_scope(), "cells")
            self.assertEqual(dialog.target_conflict_policy(), "overwrite")
            self.assertEqual(dialog.target_dataset_names(), ["Current"])

            dialog._target_combo.setCurrentText("x")
            self.assertEqual(dialog.operation_scope(), "column")
        finally:
            dialog.deleteLater()

    def test_partial_model_write_removes_stale_whole_column_formula(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset(
            "Current",
            pd.DataFrame({"x": [1.0, 2.0], "result": [9.0, 9.0]}),
        )
        dataset.formulas["result"] = "x + 1"
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        model.apply_expression("result", "x * 3", row_positions=[1])

        self.assertEqual(dataset.frame["result"].tolist(), [9.0, 6.0])
        self.assertNotIn("result", dataset.formulas)
        self.assertIn("Cell formula", dataset.column_metadata["result"].comment)

    def test_cross_worksheet_insert_control_builds_safe_sheet_reference(self) -> None:
        dialog = ColumnExpressionDialog(
            ["x", "result"],
            selected_rows_available=False,
            default_target="result",
            dataset_names=["Current", "Reference Sheet"],
            current_dataset_name="Current",
            worksheet_columns={
                "Current": ["x", "result"],
                "Reference Sheet": ["Voltage (V)"],
            },
        )
        try:
            dialog._reference_worksheet_combo.setCurrentText("Reference Sheet")
            dialog._insert_selected_column_exact()
            self.assertEqual(
                dialog.expression(),
                'sheet("Reference Sheet", "Voltage (V)")',
            )
            self.assertFalse(dialog._insert_alias_button.isEnabled())
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
