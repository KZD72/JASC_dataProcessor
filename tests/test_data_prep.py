"""Unit tests for data preparation helpers."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from core.data_prep import (
    DataPrepError,
    extract_positional_subset,
    remove_duplicate_rows,
)


class PositionalSubsetTests(unittest.TestCase):
    """Verify 1-based odd/even and Every-N row/column extraction."""

    def setUp(self) -> None:
        self.frame = pd.DataFrame(
            np.arange(30).reshape(6, 5),
            columns=["a", "b", "c", "d", "e"],
        )

    def test_odd_rows_use_visible_one_based_positions(self) -> None:
        result = extract_positional_subset(self.frame, row_mode="odd")
        self.assertEqual(result["a"].tolist(), [0, 10, 20])
        self.assertEqual(result.index.tolist(), [0, 1, 2])

    def test_even_columns_keep_second_fourth_and_so_on(self) -> None:
        result = extract_positional_subset(self.frame, column_mode="even")
        self.assertEqual(result.columns.tolist(), ["b", "d"])
        self.assertEqual(result.iloc[0].tolist(), [1, 3])

    def test_every_n_rows_and_columns_honor_independent_start_positions(self) -> None:
        result = extract_positional_subset(
            self.frame,
            row_mode="every_n",
            row_step=3,
            row_start=2,
            column_mode="every_n",
            column_step=2,
            column_start=1,
        )
        self.assertEqual(result.columns.tolist(), ["a", "c", "e"])
        self.assertEqual(result.values.tolist(), [[5, 7, 9], [20, 22, 24]])

    def test_invalid_every_n_rule_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataPrepError, "interval"):
            extract_positional_subset(
                self.frame,
                row_mode="every_n",
                row_step=0,
            )


class RemoveDuplicateRowsTests(unittest.TestCase):
    """Verify duplicate grouping and retention policies."""

    def setUp(self) -> None:
        self.frame = pd.DataFrame({
            "sample": ["a", "a", "b", "b", "c"],
            "value": [1.0, 2.0, 3.0, 3.0, np.nan],
        })

    def test_selected_key_columns_keep_first(self) -> None:
        result = remove_duplicate_rows(self.frame, ["sample"], keep="first")
        self.assertEqual(result["sample"].tolist(), ["a", "b", "c"])
        self.assertEqual(result.loc[0, "value"], 1.0)

    def test_all_columns_keep_last(self) -> None:
        result = remove_duplicate_rows(self.frame, ["sample", "value"], keep="last")
        self.assertEqual(len(result), 4)
        self.assertEqual(result[result["sample"] == "b"].index.tolist(), [2])

    def test_remove_every_member_of_duplicate_group(self) -> None:
        result = remove_duplicate_rows(self.frame, ["sample"], keep="none")
        self.assertEqual(result["sample"].tolist(), ["c"])

    def test_requires_at_least_one_key_column(self) -> None:
        with self.assertRaisesRegex(DataPrepError, "at least one"):
            remove_duplicate_rows(self.frame, [], keep="first")


if __name__ == "__main__":
    unittest.main()
