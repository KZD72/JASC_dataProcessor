"""Preserve scientific and import semantics through numeric performance paths."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication

from core.file_io import (
    AUTO_NUMBER_FORMAT,
    ImportOptions,
    NUMBER_FORMAT_COMMA_DECIMAL,
    NUMBER_FORMAT_DOT_DECIMAL,
    _convert_localized_numeric_columns,
    _localized_numeric_tokens,
    _parse_localized_number,
    read_tabular_file,
)
from core.operations import ExpressionError, apply_column_expression, evaluate_expression
from core.workspace import Workspace
from math_engine.calculus import MathOperationError, validate_numeric_column_metadata
from ui.plot_canvas import PlotCanvas


class NumericPerformancePathTests(unittest.TestCase):
    """Cover late invalid data, locale ambiguity, metadata, and formula binding."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_vector_locale_conversion_matches_scalar_grammar(self) -> None:
        tokens = pd.Series([
            "1234", "-0", "+.5", "1.", ",5", "1e-300", "1e309",
            "1e-500", "1_000", "NaN", "inf", "True", "1,23,4",
            "1,234", "1.234", "1.234,56", "1,234.56", "12 345",
            "12\u202f345,6", "12\u00a0345.6", "1'234", "١٢.٥",
            "9" * 400, "1.234e307", "12 34", "1,", "-.3e+5",
        ], dtype="string")
        for number_format in (NUMBER_FORMAT_DOT_DECIMAL, NUMBER_FORMAT_COMMA_DECIMAL):
            actual = _localized_numeric_tokens(tokens, number_format)
            for token, result in zip(tokens, actual):
                with self.subTest(number_format=number_format, token=token):
                    expected = _parse_localized_number(str(token), number_format)
                    if expected is None:
                        self.assertTrue(pd.isna(result))
                    else:
                        np.testing.assert_allclose(result, expected, rtol=1e-14, atol=0)
                        if expected == 0:
                            self.assertEqual(np.signbit(result), np.signbit(expected))

    def test_ambiguous_columns_wait_for_late_table_evidence(self) -> None:
        frame = pd.DataFrame({
            "ambiguous": ["1.234", "2.345"],
            "integers": ["1", "2"],
            "comma_evidence": ["12,5", "25,75"],
        }, dtype="string")
        result = _convert_localized_numeric_columns(frame, ";")
        self.assertEqual(result.ambiguous.tolist(), [1234.0, 2345.0])
        self.assertEqual(result.comma_evidence.tolist(), [12.5, 25.75])
        self.assertEqual(result.integers.tolist(), [1.0, 2.0])

    def test_conflicting_table_conventions_keep_point_fallback_and_raw_mixed_column(self) -> None:
        frame = pd.DataFrame({
            "ambiguous": ["1.234", "2.345"],
            "point": ["12.5", "25.75"],
            "comma": ["12,5", "25,75"],
            "mixed": [" 001 ", "invalid"],
        }, dtype="string")
        original_mixed = frame.mixed.copy()
        result = _convert_localized_numeric_columns(frame, ";")
        self.assertEqual(result.ambiguous.tolist(), [1.234, 2.345])
        self.assertEqual(result.point.tolist(), [12.5, 25.75])
        self.assertEqual(result.comma.tolist(), [12.5, 25.75])
        pd.testing.assert_series_equal(result.mixed, original_mixed)

    def test_native_csv_fallback_preserves_invalid_tokens_after_probe(self) -> None:
        options = ImportOptions(delimiter=";", has_header=True, skip_rows=0, encoding="utf-8")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "late.csv"
            for tail in ("bad", "True", "1e309", "1_000", "1,5"):
                with self.subTest(tail=tail):
                    path.write_text("value;other\n" + "001;2\n" * 200 + f"{tail};2\n", encoding="utf-8")
                    frame = read_tabular_file(path, options)
                    # Comma decimal evidence can make 001 numeric, but the other
                    # late tokens must preserve every original source token.
                    if tail == "1,5":
                        self.assertEqual(frame.value.iloc[-1], 1.5)
                    else:
                        self.assertEqual(frame.value.iloc[0], "001")
                        self.assertEqual(frame.value.iloc[-1], tail)
                    self.assertEqual(frame.other.iloc[-1], 2.0)

    def test_boolean_parser_chunk_never_becomes_numeric(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "late_boolean.csv"
            path.write_text("value\n" + "1\n" * 1_050_000 + "True\n" * 100, encoding="utf-8")
            frame = read_tabular_file(path, ImportOptions(
                delimiter=",", has_header=True, skip_rows=0, encoding="utf-8",
            ))
        self.assertEqual(frame.value.iloc[0], "1")
        self.assertEqual(frame.value.iloc[-1], "True")

    def test_numeric_csv_retains_signed_zero_missing_and_precision(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "numbers.csv"
            path.write_text(
                "x,y,empty\n-0,1.2345678901234567,\n1,,\n2,3.5,\n", encoding="utf-8",
            )
            frame = read_tabular_file(path, ImportOptions())
        self.assertTrue(np.signbit(frame.x.iloc[0]))
        self.assertEqual(frame.y.iloc[0], float("1.2345678901234567"))
        self.assertTrue(pd.isna(frame.y.iloc[1]))
        self.assertTrue(frame["empty"].isna().all())
        self.assertTrue(pd.api.types.is_string_dtype(frame["empty"].dtype))

    def test_native_numeric_csv_preserves_negative_zero_without_text_columns(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "numeric.csv"
            path.write_text("x,y\n-0,1.2345678901234567\n1,2\n", encoding="utf-8")
            frame = read_tabular_file(path, ImportOptions())
        self.assertTrue(np.signbit(frame.x.iloc[0]))
        self.assertEqual(frame.y.iloc[0], float("1.2345678901234567"))

    def test_explicit_comma_format_and_boolean_columns_keep_original_meaning(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "explicit.csv"
            path.write_text("value;flag\n1.234;True\n2.345;False\n", encoding="utf-8")
            for number_format, expected in (
                (AUTO_NUMBER_FORMAT, [1.234, 2.345]),
                (NUMBER_FORMAT_COMMA_DECIMAL, [1234.0, 2345.0]),
            ):
                with self.subTest(number_format=number_format):
                    frame = read_tabular_file(path, ImportOptions(number_format=number_format))
                    self.assertEqual(frame.value.tolist(), expected)
                    self.assertEqual(frame.flag.tolist(), ["True", "False"])

    def test_numeric_and_nullable_storage_still_honors_text_metadata(self) -> None:
        for dtype in ("float64", "Float64", "Int64"):
            with self.subTest(dtype=dtype):
                values = pd.Series([1, None, 3], dtype=dtype)
                workspace = Workspace()
                dataset = workspace.add_dataset("sheet", pd.DataFrame({"value": values}))
                validate_numeric_column_metadata(dataset.frame, "value", values)
                result = evaluate_expression(dataset.frame, "col1 * 2")
                self.assertEqual(result.iloc[0], 2)
                self.assertTrue(pd.isna(result.iloc[1]))
                dataset.metadata_for_column("value").value_type = "text"
                dataset.sync_column_metadata_attrs()
                with self.assertRaisesRegex(MathOperationError, "marked Text"):
                    validate_numeric_column_metadata(dataset.frame, "value", values)
                canvas = PlotCanvas()
                try:
                    with self.assertRaisesRegex(ValueError, "marked Text"):
                        canvas._numeric_column_values(workspace, dataset.name, "value", "Y")
                finally:
                    canvas.deleteLater()

    def test_formula_names_aliases_accessors_and_row_variables_remain_consistent(self) -> None:
        frame = pd.DataFrame({
            "value": pd.Series(["1", "2"], dtype="object"),
            "col1": [10.0, 20.0],
            "unused": ["bad", "text"],
        })
        self.assertEqual(evaluate_expression(frame, 'value + col("value") + col2').tolist(), [12.0, 24.0])
        self.assertEqual(evaluate_expression(frame, "col1 + row + index").tolist(), [11.0, 23.0])
        self.assertEqual(evaluate_expression(frame, "sin(0) + 2").tolist(), [2.0, 2.0])
        with self.assertRaises(ExpressionError):
            evaluate_expression(frame, "unused * 2")

    def test_numeric_formula_target_retains_nullable_missing_values(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset("sheet", pd.DataFrame({
            "source": pd.Series([1, None, 3], dtype="Int64"),
            "target": [0.0, 0.0, 0.0],
        }))
        dataset.metadata_for_column("target").value_type = "numeric"
        dataset.sync_column_metadata_attrs()
        apply_column_expression(dataset.frame, "target", "source * 2")
        self.assertEqual(dataset.frame.target.iloc[0], 2)
        self.assertTrue(pd.isna(dataset.frame.target.iloc[1]))


if __name__ == "__main__":
    unittest.main()
