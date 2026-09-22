"""Regression coverage for spreadsheet-style numeric Smart Fill."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication, QDialog

from core.smart_fill import (
    SMART_FILL_MODE_AUTO,
    SMART_FILL_MODE_CATEGORY,
    SMART_FILL_MODE_CUSTOM,
    SMART_FILL_MODE_DATETIME,
    SMART_FILL_MODE_NUMERIC,
    SmartFillError,
    plan_smart_fill,
    plan_numeric_smart_fill,
)
from core.workspace import Workspace
from ui.data_table import SmartFillDialog
from ui.dataframe_model import DataFrameTableModel
from ui.main_window import MainWindow


class SmartFillInferenceTests(unittest.TestCase):
    """Protect deterministic linear and interleaved inference rules."""

    def test_two_seeds_extrapolate_one_linear_sequence(self) -> None:
        plan = plan_numeric_smart_fill(
            pd.Series([1.0, 2.0, np.nan, np.nan, np.nan]),
            0,
            4,
        )

        self.assertEqual(plan.period, 1)
        self.assertEqual(plan.description, "linear sequence")
        self.assertEqual(plan.row_positions, (2, 3, 4))
        np.testing.assert_allclose(plan.values, [3.0, 4.0, 5.0])

    def test_gapped_anchors_interpolate_and_extrapolate_by_row(self) -> None:
        plan = plan_numeric_smart_fill(
            pd.Series([1.0, np.nan, 2.0, np.nan, np.nan]),
            0,
            4,
        )

        self.assertEqual(plan.period, 1)
        np.testing.assert_allclose(plan.values, [1.5, 2.5, 3.0])

    def test_auto_detects_two_interleaved_linear_sequences(self) -> None:
        plan = plan_numeric_smart_fill(
            pd.Series([1.0, 10.0, 2.0, 20.0, np.nan, np.nan, np.nan, np.nan]),
            0,
            7,
        )

        self.assertEqual(plan.period, 2)
        self.assertEqual(plan.description, "2 interleaved linear sequences")
        np.testing.assert_allclose(plan.values, [3.0, 30.0, 4.0, 40.0])

    def test_one_seed_repeats_across_blank_destinations(self) -> None:
        plan = plan_numeric_smart_fill(pd.Series([5.0, np.nan, np.nan]), 0, 2)

        self.assertEqual(plan.description, "repeated value")
        self.assertEqual(plan.values, (5.0, 5.0))

    def test_non_numeric_seed_is_rejected(self) -> None:
        with self.assertRaisesRegex(SmartFillError, "finite numbers"):
            plan_numeric_smart_fill(pd.Series([1.0, "label", np.nan]), 0, 2)

    def test_auto_detects_daily_date_time_values(self) -> None:
        plan = plan_smart_fill(
            pd.Series(["2026-01-01", "2026-01-02", None, None]),
            0,
            3,
        )

        self.assertEqual(plan.mode, SMART_FILL_MODE_DATETIME)
        self.assertEqual(
            plan.values,
            ("2026-01-03", "2026-01-04"),
        )

    def test_date_time_infers_every_day_month_year_field_order(self) -> None:
        cases = (
            (["30/12/2025", "31/12/2025", None], "01/01/2026"),
            (["12/30/2025", "12/31/2025", None], "01/01/2026"),
            (["2025/12/30", "2025/12/31", None], "2026/01/01"),
            (["2025/30/12", "2025/31/12", None], "2026/01/01"),
            (["30/2025/12", "31/2025/12", None], "01/2026/01"),
            (["12/2025/30", "12/2025/31", None], "01/2026/01"),
        )

        for values, expected in cases:
            with self.subTest(values=values):
                plan = plan_smart_fill(pd.Series(values), 0, 2)
                self.assertEqual(plan.mode, SMART_FILL_MODE_DATETIME)
                self.assertEqual(plan.values, (expected,))

    def test_ambiguous_day_month_order_uses_sequence_evidence(self) -> None:
        plan = plan_smart_fill(
            pd.Series(["01/02/2026", "01/03/2026", None]),
            0,
            2,
        )

        self.assertEqual(plan.values, ("01/04/2026",))

    def test_date_time_preserves_calendar_month_end(self) -> None:
        plan = plan_smart_fill(
            pd.Series(["2024-01-31", "2024-02-29", None, None]),
            0,
            3,
            mode=SMART_FILL_MODE_DATETIME,
        )

        self.assertEqual(plan.description, "calendar-month sequence")
        self.assertEqual(
            plan.values,
            ("2024-03-31", "2024-04-30"),
        )

    def test_auto_repeats_a_category_cycle(self) -> None:
        plan = plan_smart_fill(
            pd.Series(["red", "blue", None, None, None]),
            0,
            4,
        )

        self.assertEqual(plan.mode, SMART_FILL_MODE_CATEGORY)
        self.assertEqual(plan.values, ("red", "blue", "red"))

    def test_custom_list_aligns_to_an_existing_anchor(self) -> None:
        plan = plan_smart_fill(
            pd.Series(["Wednesday", None, None, None]),
            0,
            3,
            mode=SMART_FILL_MODE_CUSTOM,
            custom_values=("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"),
        )

        self.assertEqual(plan.values, ("Thursday", "Friday", "Monday"))

    def test_custom_list_can_fill_a_completely_blank_selection(self) -> None:
        plan = plan_smart_fill(
            pd.Series([None, None, None]),
            0,
            2,
            mode=SMART_FILL_MODE_CUSTOM,
            custom_values=("Madrid", "Paris"),
        )

        self.assertEqual(plan.seed_count, 0)
        self.assertEqual(plan.values, ("Madrid", "Paris", "Madrid"))


class SmartFillModelTests(unittest.TestCase):
    """Ensure worksheet commits are multi-column, undoable, and auditable."""

    def test_selection_fill_updates_columns_and_round_trips_through_undo(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame(
                {
                    "a": [1.0, 2.0, np.nan, np.nan],
                    "b": [10.0, 20.0, np.nan, np.nan],
                }
            ),
        )
        dataset.formulas["a"] = "col1"
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        plans = model.smart_fill_selection(0, 3, 0, 1)

        np.testing.assert_allclose(dataset.frame["a"], [1.0, 2.0, 3.0, 4.0])
        np.testing.assert_allclose(dataset.frame["b"], [10.0, 20.0, 30.0, 40.0])
        self.assertEqual(set(plans), {"a", "b"})
        self.assertNotIn("a", dataset.formulas)
        self.assertIn("Smart fill: linear sequence", dataset.column_metadata["a"].comment)

        self.assertTrue(model.undo())
        self.assertTrue(pd.isna(dataset.frame.iloc[2, 0]))
        self.assertEqual(dataset.formulas["a"], "col1")

    def test_explicit_text_column_is_rejected_before_mutation(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"value": [1.0, 2.0, np.nan]}),
        )
        dataset.metadata_for_column("value").value_type = "text"
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        with self.assertRaisesRegex(SmartFillError, "explicitly Text"):
            model.smart_fill_selection(0, 2, 0, 0, mode=SMART_FILL_MODE_NUMERIC)
        self.assertFalse(model.can_undo())

    def test_text_metadata_uses_category_mode_in_auto(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"city": ["Madrid", "Paris", None, None]}),
        )
        dataset.metadata_for_column("city").value_type = "text"
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        plans = model.smart_fill_selection(0, 3, 0, 0)

        self.assertEqual(plans["city"].mode, SMART_FILL_MODE_CATEGORY)
        self.assertEqual(dataset.frame["city"].tolist(), ["Madrid", "Paris", "Madrid", "Paris"])

    def test_custom_list_can_replace_blanks_in_an_empty_numeric_column(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"day": [np.nan, np.nan, np.nan]}),
        )
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        model.smart_fill_selection(
            0,
            2,
            0,
            0,
            mode=SMART_FILL_MODE_CUSTOM,
            custom_values=("Mon", "Tue"),
        )

        self.assertEqual(dataset.frame["day"].tolist(), ["Mon", "Tue", "Mon"])

    def test_auto_date_time_commits_to_a_string_backed_column(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"when": ["2026-01-01", "2026-01-02", None]}),
        )
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        plan = model.smart_fill_selection(0, 2, 0, 0)["when"]

        self.assertEqual(plan.mode, SMART_FILL_MODE_DATETIME)
        self.assertEqual(pd.Timestamp(dataset.frame.iloc[2, 0]), pd.Timestamp("2026-01-03"))


class SmartFillMainWindowTests(unittest.TestCase):
    """Exercise the selected-range GUI path without opening a modal dialog."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_selected_rectangle_is_completed_through_main_window(self) -> None:
        window = MainWindow()
        try:
            dataset = window._workspace.add_dataset(
                "series",
                pd.DataFrame({"value": [1.0, 10.0, 2.0, 20.0, np.nan, np.nan]}),
            )
            window._refresh_dataset_list(dataset.name)
            window._select_dataset_range(0, 0, 6, 1)

            class FakeSmartFillDialog:
                Accepted = QDialog.Accepted

                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                @staticmethod
                def exec() -> int:
                    return QDialog.Accepted

                @staticmethod
                def period() -> int:
                    return 0

                @staticmethod
                def mode() -> str:
                    return SMART_FILL_MODE_AUTO

                @staticmethod
                def custom_values() -> tuple[str, ...]:
                    return ()

            with patch("ui.main_window.SmartFillDialog", FakeSmartFillDialog):
                window._smart_fill_dataset_selection()

            np.testing.assert_allclose(
                dataset.frame["value"],
                [1.0, 10.0, 2.0, 20.0, 3.0, 30.0],
            )
            self.assertIn("Smart Fill completed 2 blank cell(s)", window.statusBar().currentMessage())
        finally:
            window.close()
            self.app.processEvents()

    def test_new_blank_sheet_columns_are_auto_typed(self) -> None:
        window = MainWindow()
        try:
            window._create_blank_sheet()
            dataset = window._current_dataset()

            self.assertIsNotNone(dataset)
            assert dataset is not None
            self.assertEqual(dataset.frame.dtypes.tolist(), [object, object])
            self.assertEqual(dataset.column_metadata["x"].value_type, "")
            self.assertEqual(dataset.column_metadata["y"].value_type, "")
            self.assertEqual(dataset.column_metadata["x"].role, "x")
            self.assertEqual(dataset.column_metadata["y"].role, "y")

            model = window._dataset_model
            self.assertTrue(model.setData(model.index(0, 0), "1.5"))
            self.assertTrue(pd.api.types.is_numeric_dtype(dataset.frame["x"]))
            self.assertEqual(dataset.column_metadata["x"].value_type, "")

            self.assertTrue(model.setData(model.index(1, 0), "31/12/2026"))
            self.assertEqual(dataset.frame.iloc[1, 0], "31/12/2026")
            self.assertTrue(pd.api.types.is_object_dtype(dataset.frame["x"]))
        finally:
            window.close()
            self.app.processEvents()

    def test_dialog_exposes_all_modes_and_custom_list_input(self) -> None:
        dialog = SmartFillDialog("Rows 1-4, column city")
        try:
            modes = [
                dialog._mode.itemData(index)
                for index in range(dialog._mode.count())
            ]
            self.assertEqual(
                modes,
                [
                    SMART_FILL_MODE_AUTO,
                    SMART_FILL_MODE_NUMERIC,
                    SMART_FILL_MODE_DATETIME,
                    SMART_FILL_MODE_CATEGORY,
                    SMART_FILL_MODE_CUSTOM,
                ],
            )

            dialog._mode.setCurrentIndex(dialog._mode.findData(SMART_FILL_MODE_CUSTOM))
            dialog._custom_list.setPlainText("Madrid\nParis\nBerlin")

            self.assertTrue(dialog._pattern.isHidden())
            self.assertFalse(dialog._custom_list.isHidden())
            self.assertEqual(dialog.custom_values(), ("Madrid", "Paris", "Berlin"))
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
