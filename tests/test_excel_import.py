"""Regression tests for value-only, multi-sheet Excel workbook import."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.worksheet.table import Table
from PySide6.QtWidgets import QApplication, QDialog

from core.file_io import inspect_excel_workbook, read_excel_sheets
from ui.dialogs import ExcelImportDialog
from ui.main_window import MainWindow


class ExcelImportTests(unittest.TestCase):
    """Verify workbook preflight, tab splitting, and workspace integration."""

    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        """Create one offscreen Qt application for dialog and workflow tests."""
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        """Create a representative workbook with data and unsupported objects."""
        self.temporary_directory = TemporaryDirectory()
        self.workbook_path = Path(self.temporary_directory.name) / "experiment.xlsx"

        workbook = Workbook()
        data = workbook.active
        data.title = "Measurements"
        data.append(["time", "signal", None])
        data.append([0.0, 1.5, "first"])
        data.append([1.0, 2.5, "second"])
        data.add_table(Table(displayName="MeasurementsTable", ref="A1:B3"))

        chart = BarChart()
        chart.add_data(Reference(data, min_col=2, min_row=1, max_row=3), titles_from_data=True)
        data.add_chart(chart, "E2")

        hidden = workbook.create_sheet("Hidden helper")
        hidden.append(["factor", "offset", "formula result"])
        hidden.append([2, 10, "=A2*B2"])
        hidden.sheet_state = "hidden"

        chart_tab = workbook.create_chartsheet("Chart dashboard")
        dashboard_chart = BarChart()
        dashboard_chart.add_data(
            Reference(data, min_col=2, min_row=1, max_row=3), titles_from_data=True
        )
        chart_tab.add_chart(dashboard_chart)
        workbook.save(self.workbook_path)

    def tearDown(self) -> None:
        """Remove the temporary workbook."""
        self.temporary_directory.cleanup()

    def test_preflight_lists_tabs_and_warns_about_unsupported_objects(self) -> None:
        """Charts, tables, chart tabs, and hidden worksheets are disclosed."""
        inspection = inspect_excel_workbook(self.workbook_path)

        self.assertEqual(
            [sheet.name for sheet in inspection.sheets],
            ["Measurements", "Hidden helper", "Chart dashboard"],
        )
        self.assertEqual(inspection.sheets[0].used_range, "A1:C3")
        self.assertEqual(inspection.sheets[1].state, "hidden")
        self.assertFalse(inspection.sheets[2].is_importable)

        warning_text = "\n".join(inspection.warnings)
        self.assertIn("cached worksheet cell values", warning_text)
        self.assertIn("chart definition", warning_text)
        self.assertIn("Excel table definition", warning_text)
        self.assertIn("chart-only tab", warning_text)
        self.assertIn("hidden worksheet", warning_text)

    def test_selected_worksheets_are_read_as_independent_frames(self) -> None:
        """Every selected worksheet becomes a separate tabular result."""
        result = read_excel_sheets(
            self.workbook_path,
            ["Measurements", "Hidden helper", "Missing"],
        )

        self.assertEqual(set(result.frames), {"Measurements", "Hidden helper"})
        self.assertIn("Missing", result.errors)
        self.assertEqual(list(result.frames["Measurements"].columns), ["time", "signal", "Column 3"])
        pd.testing.assert_series_equal(
            result.frames["Measurements"]["signal"],
            pd.Series([1.5, 2.5], name="signal"),
        )
        self.assertEqual(result.frames["Hidden helper"].iloc[0, :2].tolist(), [2, 10])
        self.assertTrue(pd.isna(result.frames["Hidden helper"].iloc[0, 2]))

    def test_dialog_selects_visible_worksheets_but_not_hidden_or_chart_tabs(self) -> None:
        """Hidden helper tabs require an explicit user choice."""
        dialog = ExcelImportDialog(inspect_excel_workbook(self.workbook_path))
        self.assertEqual(dialog.selected_sheet_names(), ["Measurements"])

        dialog._set_all_importable_checked(True)
        self.assertEqual(dialog.selected_sheet_names(), ["Measurements", "Hidden helper"])

        dialog._set_all_importable_checked(False)
        dialog._all_sheets_radio.setChecked(True)
        self.assertTrue(dialog.import_all_sheets())
        self.assertEqual(dialog.selected_sheet_names(), ["Measurements", "Hidden helper"])

    def test_main_window_creates_one_dataset_per_selected_tab(self) -> None:
        """Workbook tabs use provenance-friendly, collision-safe dataset names."""
        window = MainWindow()
        inspection = inspect_excel_workbook(self.workbook_path)

        with (
            patch.object(window, "_confirm_large_file_import", return_value=True),
            patch.object(window, "_confirm_large_dataset", return_value=True),
            patch("ui.main_window.inspect_excel_workbook", return_value=inspection),
            patch("ui.main_window.ExcelImportDialog") as dialog_type,
        ):
            dialog = dialog_type.return_value
            dialog.exec.return_value = QDialog.Accepted
            dialog.selected_sheet_names.return_value = ["Measurements", "Hidden helper"]
            dialog.has_header.return_value = True
            window._import_excel_workbook(self.workbook_path)

        measurement = window._workspace.get_dataset("experiment - Measurements")
        helper = window._workspace.get_dataset("experiment - Hidden helper")
        self.assertEqual(measurement.source_path, self.workbook_path)
        self.assertEqual(helper.source_path, self.workbook_path)
        self.assertEqual(len(measurement.frame), 2)
        self.assertEqual(len(helper.frame), 1)


if __name__ == "__main__":
    unittest.main()
