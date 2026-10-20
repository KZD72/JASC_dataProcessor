"""Forensic regression coverage for worksheet numeric/text boundaries."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication

from core.data_prep import (
    DataPrepError,
    FilterCondition,
    apply_filter_condition,
    bin_dataframe,
    clean_missing_values,
    group_aggregate_dataframe,
)
from core.operations import ExpressionError, apply_column_expression, evaluate_expression
from core.workspace import ColumnMetadata, Workspace
from math_engine.calculus import MathOperationError, derivative_column
from math_engine.curve_fitting import fit_curve
from math_engine.interpolation import interpolate_dataset
from math_engine.smoothing import SmoothingParameters, smooth_column
from math_engine.statistics import run_statistical_analysis
from ui.dataframe_model import DataFrameTableModel
from ui.plot_canvas import PlotCanvas


class NumericTypeSafetyTests(unittest.TestCase):
    """Ensure scientific workflows never silently reinterpret text as missing data."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _mixed_frame() -> pd.DataFrame:
        return pd.DataFrame({
            "x": [0.0, 1.0, 2.0, 3.0],
            "y": pd.Series(["1", "bad", "3", "4"], dtype="object"),
        })

    def test_scientific_engines_reject_auto_column_with_nonblank_text(self) -> None:
        operations = {
            "derivative": lambda frame: derivative_column(
                frame, "x", "y", "gradient", "result"
            ),
            "smoothing": lambda frame: smooth_column(
                frame,
                "x",
                "y",
                "adjacent_average",
                "result",
                SmoothingParameters(window_length=2),
            ),
            "interpolation": lambda frame: interpolate_dataset(
                frame,
                ["x"],
                "y",
                np.asarray([[0.5], [1.5]]),
                "linear",
            ),
            "curve fitting": lambda frame: fit_curve(
                frame,
                "x",
                "y",
                "linear",
                "trf",
                include_confidence_band=False,
            ),
        }
        for label, operation in operations.items():
            with self.subTest(operation=label):
                frame = self._mixed_frame()
                with self.assertRaisesRegex(MathOperationError, "non-numeric text at row 2"):
                    operation(frame)
                self.assertNotIn("result", frame.columns)

    def test_statistics_reject_nonblank_text_instead_of_dropping_row(self) -> None:
        with self.assertRaisesRegex(MathOperationError, "non-numeric text at row 2"):
            run_statistical_analysis(
                self._mixed_frame()["y"],
                "signal",
                "single_summary",
            )

    def test_plot_numeric_validation_rejects_auto_mixed_column(self) -> None:
        frame = self._mixed_frame()
        numeric = pd.to_numeric(frame["y"], errors="coerce")

        with self.assertRaisesRegex(ValueError, "non-numeric text at row 2"):
            PlotCanvas._validate_numeric_metadata(
                frame["y"],
                numeric,
                frame,
                "y",
                "Y",
            )

    def test_data_prep_numeric_operations_reject_text_without_mutation(self) -> None:
        frame = pd.DataFrame({
            "group": ["A", "A", "B"],
            "x": [0.0, 1.0, 2.0],
            "value": pd.Series(["1", "bad", pd.NA], dtype="object"),
        })
        original = frame.copy(deep=True)
        operations = {
            "missing values": lambda: clean_missing_values(
                frame, ["value"], "fill_mean"
            ),
            "group aggregate": lambda: group_aggregate_dataframe(
                frame, ["group"], ["value"], ["mean"]
            ),
            "binning": lambda: bin_dataframe(frame, "x", ["value"], 2),
            "numeric filter": lambda: apply_filter_condition(
                frame, FilterCondition("value", "gt", "0")
            ),
        }
        for label, operation in operations.items():
            with self.subTest(operation=label):
                with self.assertRaisesRegex(DataPrepError, "row 2"):
                    operation()
        pd.testing.assert_frame_equal(frame, original)

    def test_fill_value_does_not_poison_numeric_column_with_text(self) -> None:
        frame = pd.DataFrame({"value": [1.0, np.nan, 3.0]})
        original = frame.copy(deep=True)

        with self.assertRaisesRegex(DataPrepError, "cannot fill numeric column"):
            clean_missing_values(frame, ["value"], "fill_value", "unknown")

        pd.testing.assert_frame_equal(frame, original)
        result = clean_missing_values(frame, ["value"], "fill_value", "2.5")
        self.assertEqual(result["value"].tolist(), [1.0, 2.5, 3.0])

    def test_data_prep_respects_explicit_text_metadata(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset(
            "sheet",
            pd.DataFrame({"label": ["1", "2", pd.NA]}),
        )
        dataset.metadata_for_column("label").value_type = "text"
        dataset.sync_column_metadata_attrs()

        with self.assertRaisesRegex(DataPrepError, "marked Text"):
            clean_missing_values(dataset.frame, ["label"], "fill_mean")

        result = clean_missing_values(
            dataset.frame, ["label"], "fill_value", "missing"
        )
        self.assertEqual(result["label"].tolist(), ["1", "2", "missing"])

    def test_formula_arithmetic_promotes_numeric_strings(self) -> None:
        frame = pd.DataFrame({"value": pd.Series(["1", "2", "3"], dtype="object")})

        result = evaluate_expression(frame, "col1 * 2")

        self.assertEqual(result.tolist(), [2, 4, 6])

    def test_formula_rejects_accidental_string_repetition_from_mixed_column(self) -> None:
        frame = pd.DataFrame({
            "value": pd.Series(["1", "bad", "3"], dtype="object")
        })

        with self.assertRaisesRegex(ExpressionError, "mixed numbers and text"):
            evaluate_expression(frame, "col1 * 2")

        deliberate = evaluate_expression(frame, '"sample-" + col1')
        self.assertEqual(deliberate.tolist(), ["sample-1", "sample-bad", "sample-3"])

    def test_formula_cannot_write_text_into_numeric_metadata_target(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0, 2.0], "result": [9.0, 9.0]}),
        )
        dataset.metadata_for_column("result").value_type = "numeric"
        dataset.sync_column_metadata_attrs()

        with self.assertRaisesRegex(ExpressionError, "formula produced non-numeric text"):
            apply_column_expression(dataset.frame, "result", '"label"')

        self.assertEqual(dataset.frame["result"].tolist(), [9.0, 9.0])

    def test_formula_converts_numeric_output_for_explicit_text_target(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0, 2.0], "label": ["a", "b"]}),
        )
        dataset.metadata_for_column("label").value_type = "text"
        dataset.sync_column_metadata_attrs()

        apply_column_expression(dataset.frame, "label", "x * 2")

        self.assertEqual(dataset.frame["label"].tolist(), ["2.0", "4.0"])

    def test_formula_respects_text_metadata_even_for_numeric_dtype(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset(
            "sheet",
            pd.DataFrame({"label": [1.0, 2.0]}),
        )
        dataset.metadata_for_column("label").value_type = "text"
        dataset.sync_column_metadata_attrs()

        with self.assertRaisesRegex(ExpressionError, "text/object column"):
            evaluate_expression(dataset.frame, "sin(label)")

    def test_metadata_preserving_column_paste_is_validated_atomically(self) -> None:
        dataset = Workspace().add_dataset("sheet", pd.DataFrame({"x": [1.0, 2.0]}))
        model = DataFrameTableModel()
        model.set_dataset(dataset)
        block = pd.DataFrame({0: ["3", "4"], 1: ["5", "bad"]})
        metadata = [
            ColumnMetadata(value_type="numeric"),
            ColumnMetadata(value_type="numeric"),
        ]

        with self.assertRaisesRegex(ValueError, "clipboard value 'bad' is not numeric"):
            model.insert_columns(1, ["valid", "invalid"], block, metadata)

        self.assertEqual(dataset.frame.columns.tolist(), ["x"])
        self.assertFalse(model.can_undo())


if __name__ == "__main__":
    unittest.main()
