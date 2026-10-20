"""Regression coverage for explicit create/update column-fill behavior."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype
from PySide6.QtWidgets import QApplication

from core.operations import apply_column_expression, evaluate_expression
from core.workspace import Workspace
from ui.data_table import RangeFillDialog
from ui.dataframe_model import DataFrameTableModel
from ui.dialogs import ColumnExpressionDialog


class ColumnFillUxTests(unittest.TestCase):
    """Keep destructive and non-destructive fill choices visible and predictable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_range_fill_distinguishes_existing_and_new_targets(self) -> None:
        dialog = RangeFillDialog(
            ["x", "signal"],
            default_column="signal",
            default_start_row=2,
            default_count=3,
            default_target_mode="existing",
        )
        try:
            self.assertEqual(dialog.target_mode(), "existing")
            self.assertEqual(dialog.target_column(), "signal")
            self.assertIn("replace values in", dialog._summary.text())

            dialog._target_mode.setCurrentIndex(dialog._target_mode.findData("new"))
            dialog._new_target.setText("calculated")
            self.assertEqual(dialog.target_mode(), "new")
            self.assertEqual(dialog.target_column(), "calculated")
            self.assertIn("create", dialog._summary.text())
        finally:
            dialog.deleteLater()

    def test_constant_fill_is_an_explicit_zero_step_pattern(self) -> None:
        dialog = RangeFillDialog(
            ["x"],
            default_column="x",
            default_start_row=1,
            default_count=4,
        )
        try:
            dialog._start_value.setValue(7.5)
            dialog._fill_pattern.setCurrentIndex(dialog._fill_pattern.findData("constant"))
            self.assertEqual(dialog.fill_pattern(), "constant")
            self.assertEqual(dialog.step(), 0.0)
            self.assertIn("constant value 7.5", dialog._summary.text())
        finally:
            dialog.deleteLater()

    def test_selected_formula_target_defaults_to_update_with_clear_warning(self) -> None:
        dialog = ColumnExpressionDialog(
            ["x", "result"],
            selected_rows_available=True,
            default_target="result",
            dataset_names=["Current"],
            current_dataset_name="Current",
            selected_cell_columns={"result"},
        )
        try:
            self.assertEqual(dialog.target_conflict_policy(), "overwrite")
            self.assertIn("will be overwritten", dialog._target_action_hint.text())
            self.assertIn("scalar formula", dialog._batch_hint.text())
        finally:
            dialog.deleteLater()

    def test_scalar_formula_broadcast_is_intentional_and_rowwise_formula_is_not(self) -> None:
        scalar_frame = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        apply_column_expression(scalar_frame, "result", "np.mean(x)")
        self.assertEqual(scalar_frame["result"].tolist(), [2.0, 2.0, 2.0])

        rowwise_frame = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        apply_column_expression(rowwise_frame, "result", "x * 2")
        self.assertEqual(rowwise_frame["result"].tolist(), [2.0, 4.0, 6.0])

    def test_range_fill_makes_blank_object_column_safe_for_numpy_formula(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"Column 1": pd.Series([pd.NA] * 25, dtype="object")}),
        )
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        model.fill_range("Column 1", 1, 16, 1.0, 1.0)
        result = evaluate_expression(dataset.frame, "sin(col1)")

        self.assertTrue(is_numeric_dtype(dataset.frame["Column 1"]))
        self.assertEqual(
            dataset.metadata_for_column("Column 1").value_type,
            "numeric",
        )
        np.testing.assert_allclose(
            result.iloc[:16].to_numpy(dtype=float),
            np.sin(np.arange(1.0, 17.0)),
        )
        self.assertTrue(result.iloc[16:].isna().all())

    def test_range_fill_rejects_unreplaced_text_in_numeric_target(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"Column 1": pd.Series(["sample", pd.NA], dtype="object")}),
        )
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        with self.assertRaisesRegex(ValueError, "non-numeric value at row 1"):
            model.fill_range("Column 1", 2, 1, 1.0, 1.0)

        self.assertEqual(dataset.frame.iloc[0, 0], "sample")
        self.assertTrue(pd.isna(dataset.frame.iloc[1, 0]))
        self.assertFalse(model.can_undo())

    def test_numpy_formula_promotes_wholly_numeric_object_column(self) -> None:
        frame = pd.DataFrame({"x": pd.Series(["1", "2"], dtype="object")})

        result = evaluate_expression(frame, "sin(x)")

        np.testing.assert_allclose(result.to_numpy(dtype=float), np.sin([1.0, 2.0]))


if __name__ == "__main__":
    unittest.main()
