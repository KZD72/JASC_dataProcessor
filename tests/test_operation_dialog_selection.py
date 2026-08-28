"""Regression tests for explicit multi-column choices in analysis dialogs."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.dialogs import (
    ColumnMathDialog,
    FFTDialog,
    FitDialog,
    IFFTDialog,
    InterpolationDialog,
    SmoothingDialog,
    StatisticsDialog,
    select_list_items,
)


class ExplicitOperationColumnSelectionTests(unittest.TestCase):
    """Ensure opening an operation cannot silently choose its target columns."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.columns = ["x", "signal_a", "signal_b", "real", "imaginary", "sigma"]
        self.frame = pd.DataFrame(
            {column: [1.0, 2.0, 3.0, 4.0, 5.0] for column in self.columns}
        )

    def _dialogs(self) -> list[object]:
        """Return representative column-targeting analysis dialogs."""
        return [
            ColumnMathDialog(
                "Derivative",
                self.columns,
                {"gradient": "Gradient"},
                "Derivative",
                default_x_column="x",
                dataset_names=["sheet"],
                current_dataset_name="sheet",
            ),
            SmoothingDialog(
                self.frame,
                self.columns,
                default_x_column="x",
                dataset_names=["sheet"],
                current_dataset_name="sheet",
            ),
            FFTDialog(
                self.columns,
                "sheet",
                default_x_column="x",
                dataset_names=["sheet"],
                current_dataset_name="sheet",
            ),
            IFFTDialog(
                self.columns,
                "sheet",
                dataset_names=["sheet"],
                current_dataset_name="sheet",
            ),
            InterpolationDialog(
                self.columns,
                "sheet",
                {column: (1.0, 5.0) for column in self.columns},
                default_x_column="x",
                default_y_column="signal_a",
                dataset_names=["sheet"],
                current_dataset_name="sheet",
            ),
            StatisticsDialog({"sheet": self.columns}, "sheet"),
            FitDialog(
                self.columns,
                "sheet",
                default_x_column="x",
                dataset_names=["sheet"],
                current_dataset_name="sheet",
            ),
        ]

    def test_target_columns_start_unselected_in_every_analysis_dialog(self) -> None:
        dialogs = self._dialogs()
        column_math, smoothing, fft, ifft, interpolation, statistics, fit = dialogs
        try:
            self.assertEqual(column_math.y_columns(), [])
            self.assertEqual(smoothing.y_columns(), [])
            self.assertEqual(fft.signal_columns(), [])
            self.assertEqual(ifft.real_columns(), [])
            self.assertEqual(ifft.imaginary_columns(), [])
            self.assertEqual(interpolation.value_columns(), [])
            self.assertEqual(statistics.primary_columns(), [])
            self.assertEqual(statistics.multi_columns(), [])
            self.assertEqual(statistics.secondary_columns(), [])
            self.assertEqual(fit.y_columns(), [])
            self.assertIsNone(fit.x_weight_column())
            self.assertEqual(fit.weight_columns(), [])
        finally:
            for dialog in dialogs:
                dialog.deleteLater()

    def test_multi_column_selection_is_preserved_in_operation_order(self) -> None:
        dialog = ColumnMathDialog(
            "Derivative",
            self.columns,
            {"gradient": "Gradient"},
            "Derivative",
            default_x_column="x",
            dataset_names=["sheet"],
            current_dataset_name="sheet",
        )
        try:
            select_list_items(dialog._y_column_list, ["signal_a", "signal_b"])
            self.assertEqual(dialog.y_columns(), ["signal_a", "signal_b"])
        finally:
            dialog.deleteLater()

    def test_accepting_without_a_target_column_shows_clear_validation(self) -> None:
        dialog = ColumnMathDialog(
            "Derivative",
            self.columns,
            {"gradient": "Gradient"},
            "Derivative",
            default_x_column="x",
            dataset_names=["sheet"],
            current_dataset_name="sheet",
        )
        try:
            with patch.object(QMessageBox, "warning") as warning:
                dialog.accept()
            warning.assert_called_once()
            self.assertIn("at least one Y column", warning.call_args.args[2])
            self.assertEqual(dialog.result(), 0)
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
