"""Tests for independent worksheet and saved-plot duplication."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from core.workspace import Workspace


class WorkspaceDuplicationTests(unittest.TestCase):
    """Protect copied state, unique naming, and source independence."""

    def test_duplicate_dataset_copies_values_structure_formulas_and_metadata(self) -> None:
        workspace = Workspace()
        source = workspace.add_dataset(
            "Measurements",
            pd.DataFrame({
                "time": pd.Series([0.0, 1.0], dtype="float64"),
                "signal": pd.Series([2.0, 3.0], dtype="float64"),
            }),
            source_path=Path("measurements.csv"),
        )
        source.formulas["signal"] = 'col("time") + 2'
        metadata = source.metadata_for_column("signal")
        metadata.role = "y"
        metadata.unit = "V"
        metadata.comment = "Original signal"
        source.sync_column_metadata_attrs()

        duplicate = workspace.duplicate_dataset(source.name)
        second_duplicate = workspace.duplicate_dataset(source.name)
        copied_copy = workspace.duplicate_dataset(duplicate.name)

        self.assertEqual(duplicate.name, "Measurements Copy")
        self.assertEqual(second_duplicate.name, "Measurements Copy (2)")
        self.assertEqual(copied_copy.name, "Measurements Copy (3)")
        self.assertEqual(duplicate.source_path, source.source_path)
        self.assertEqual(duplicate.backend, source.backend)
        pd.testing.assert_frame_equal(duplicate.frame, source.frame)
        self.assertEqual(duplicate.formulas, source.formulas)
        self.assertEqual(duplicate.column_metadata["signal"].unit, "V")

        duplicate.frame.loc[0, "signal"] = 99.0
        duplicate.formulas["signal"] = "changed"
        duplicate.column_metadata["signal"].unit = "mV"
        self.assertEqual(source.frame.loc[0, "signal"], 2.0)
        self.assertEqual(source.formulas["signal"], 'col("time") + 2')
        self.assertEqual(source.column_metadata["signal"].unit, "V")

    def test_duplicate_plot_deep_copies_nested_definition(self) -> None:
        workspace = Workspace()
        source = workspace.add_plot(
            "Comparison",
            {
                "series": [{"x_dataset": "A", "y_dataset": "A", "color": "red"}],
                "settings": {"title": "Original"},
            },
        )

        duplicate = workspace.duplicate_plot(source.name)
        second_duplicate = workspace.duplicate_plot(source.name)
        copied_copy = workspace.duplicate_plot(duplicate.name)

        self.assertEqual(duplicate.name, "Comparison Copy")
        self.assertEqual(second_duplicate.name, "Comparison Copy (2)")
        self.assertEqual(copied_copy.name, "Comparison Copy (3)")
        self.assertEqual(duplicate.state, source.state)
        duplicate.state["series"][0]["color"] = "blue"
        duplicate.state["settings"]["title"] = "Copy"
        self.assertEqual(source.state["series"][0]["color"], "red")
        self.assertEqual(source.state["settings"]["title"], "Original")


if __name__ == "__main__":
    unittest.main()
