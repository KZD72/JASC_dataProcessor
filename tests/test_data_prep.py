"""Unit tests for data preparation helpers."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from core.data_prep import DataPrepError, remove_duplicate_rows


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
