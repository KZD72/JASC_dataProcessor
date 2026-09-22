"""Regression coverage for automatic CSV/TXT delimiter inference."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from core.file_io import (
    AUTO_DELIMITER,
    ImportOptions,
    inspect_delimited_file,
    read_tabular_file,
)
from ui.dialogs import ImportOptionsDialog
from ui.main_window import MainWindow


class DelimitedImportTests(unittest.TestCase):
    """Ensure Auto is the default and common separators are inferred safely."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _read(self, name: str, content: str):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_text(content, encoding="utf-8")
            return read_tabular_file(path, ImportOptions())

    def test_import_options_default_to_auto_in_dialog_and_model(self) -> None:
        self.assertEqual(ImportOptions().delimiter, AUTO_DELIMITER)
        self.assertIsNone(ImportOptions().has_header)
        self.assertIsNone(ImportOptions().skip_rows)
        dialog = ImportOptionsDialog()
        try:
            self.assertEqual(dialog._delimiter_combo.currentData(), AUTO_DELIMITER)
            self.assertEqual(dialog.options().delimiter, AUTO_DELIMITER)
            self.assertIsNone(dialog.options().has_header)
            self.assertIsNone(dialog.options().skip_rows)
        finally:
            dialog.close()

    def test_auto_infers_comma_semicolon_tab_and_pipe(self) -> None:
        cases = (
            ("comma.csv", "name,value\na,1\nb,2\n"),
            ("semicolon.csv", "name;value\na;1\nb;2\n"),
            ("tab.txt", "name\tvalue\na\t1\nb\t2\n"),
            ("pipe.txt", "name|value\na|1\nb|2\n"),
        )
        for name, content in cases:
            with self.subTest(name=name):
                frame = self._read(name, content)
                self.assertEqual(frame.columns.tolist(), ["name", "value"])
                self.assertEqual(frame["value"].tolist(), [1, 2])

    def test_auto_infers_whitespace_delimited_text(self) -> None:
        frame = self._read("space.txt", "name value\na    1\nb    2\n")

        self.assertEqual(frame.columns.tolist(), ["name", "value"])
        self.assertEqual(frame["value"].tolist(), [1, 2])

    def test_separator_free_file_remains_one_column(self) -> None:
        frame = self._read("single.csv", "name\nalpha\nbeta\n")

        self.assertEqual(frame.columns.tolist(), ["name"])
        self.assertEqual(frame["name"].tolist(), ["alpha", "beta"])

    def test_auto_discards_detected_metadata_and_detects_header(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "instrument.dat"
            path.write_text(
                "Instrument;TDTR\nOperator;Julia\ntime;signal\n0;1.5\n1;2.5\n",
                encoding="utf-8",
            )

            inspection = inspect_delimited_file(path)
            frame = read_tabular_file(path, ImportOptions())

        self.assertEqual(inspection.delimiter, ";")
        self.assertEqual(inspection.metadata_rows, 2)
        self.assertTrue(inspection.has_header)
        self.assertEqual(inspection.column_names, ("time", "signal"))
        self.assertEqual(frame.columns.tolist(), ["time", "signal"])
        self.assertEqual(frame["signal"].tolist(), [1.5, 2.5])

    def test_auto_detects_headerless_numeric_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "headerless.csv"
            path.write_text("0,1\n1,2\n2,3\n", encoding="utf-8")

            inspection = inspect_delimited_file(path)
            frame = read_tabular_file(path, ImportOptions())

        self.assertFalse(inspection.has_header)
        self.assertEqual(frame.columns.tolist(), ["Column 1", "Column 2"])
        self.assertEqual(frame.iloc[0].tolist(), [0, 1])

    def test_dialog_previews_detection_and_allows_fixed_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "metadata.csv"
            path.write_text("Note\na,b\n1,2\n2,3\n", encoding="utf-8")
            inspection = inspect_delimited_file(path)
            dialog = ImportOptionsDialog(inspections=[inspection])
            try:
                self.assertEqual(dialog._inspection_table.rowCount(), 1)
                self.assertEqual(dialog._inspection_table.item(0, 0).text(), "metadata.csv")
                dialog._header_combo.setCurrentIndex(
                    dialog._header_combo.findData("none")
                )
                dialog._metadata_combo.setCurrentIndex(
                    dialog._metadata_combo.findData("fixed")
                )
                dialog._metadata_rows.setValue(1)

                options = dialog.options()
                self.assertFalse(options.has_header)
                self.assertEqual(options.skip_rows, 1)
            finally:
                dialog.close()


class DelimitedBatchImportTests(unittest.TestCase):
    """Exercise multi-file importing and header-pattern resolution."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_batch_imports_multiple_files_with_one_auto_rule_set(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first.csv"
            second = Path(folder) / "second.csv"
            first.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
            second.write_text("x;y\n5;6\n7;8\n", encoding="utf-8")
            window = MainWindow()

            class FakeImportDialog:
                Accepted = QDialog.Accepted

                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                @staticmethod
                def exec() -> int:
                    return QDialog.Accepted

                @staticmethod
                def options() -> ImportOptions:
                    return ImportOptions()

            try:
                with (
                    patch(
                        "ui.main_window.QFileDialog.getOpenFileNames",
                        return_value=([str(first), str(second)], ""),
                    ),
                    patch("ui.main_window.ImportOptionsDialog", FakeImportDialog),
                    patch.object(window, "_confirm_large_file_import", return_value=True),
                    patch.object(window, "_confirm_large_dataset", return_value=True),
                ):
                    window._import_data_file()

                self.assertEqual(window._workspace.dataset_names(), ["first", "second"])
                self.assertEqual(
                    window._workspace.get_dataset("second").frame.columns.tolist(),
                    ["x", "y"],
                )
            finally:
                window.close()

    def test_mismatched_headers_can_be_discarded_for_generic_columns(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first.csv"
            second = Path(folder) / "second.csv"
            first.write_text("x,y\n1,2\n", encoding="utf-8")
            second.write_text("time,value\n3,4\n", encoding="utf-8")
            window = MainWindow()

            class FakeImportDialog:
                Accepted = QDialog.Accepted

                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                @staticmethod
                def exec() -> int:
                    return QDialog.Accepted

                @staticmethod
                def options() -> ImportOptions:
                    return ImportOptions()

            try:
                with (
                    patch(
                        "ui.main_window.QFileDialog.getOpenFileNames",
                        return_value=([str(first), str(second)], ""),
                    ),
                    patch("ui.main_window.ImportOptionsDialog", FakeImportDialog),
                    patch.object(window, "_confirm_large_file_import", return_value=True),
                    patch.object(window, "_confirm_large_dataset", return_value=True),
                    patch.object(
                        window,
                        "_confirm_delimited_batch_pattern",
                        return_value="generic",
                    ) as pattern_prompt,
                ):
                    window._import_data_file()

                pattern_prompt.assert_called_once()
                for name in ("first", "second"):
                    frame = window._workspace.get_dataset(name).frame
                    self.assertEqual(frame.columns.tolist(), ["Column 1", "Column 2"])
                    self.assertEqual(len(frame), 1)
            finally:
                window.close()

    def test_mixed_header_presence_prompts_and_can_cancel_the_batch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            headed = Path(folder) / "headed.csv"
            headerless = Path(folder) / "headerless.csv"
            headed.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
            headerless.write_text("5,6\n7,8\n9,10\n", encoding="utf-8")
            window = MainWindow()

            class FakeImportDialog:
                Accepted = QDialog.Accepted

                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                @staticmethod
                def exec() -> int:
                    return QDialog.Accepted

                @staticmethod
                def options() -> ImportOptions:
                    return ImportOptions()

            try:
                with (
                    patch(
                        "ui.main_window.QFileDialog.getOpenFileNames",
                        return_value=([str(headed), str(headerless)], ""),
                    ),
                    patch("ui.main_window.ImportOptionsDialog", FakeImportDialog),
                    patch.object(window, "_confirm_large_file_import", return_value=True),
                    patch.object(
                        window,
                        "_confirm_delimited_batch_pattern",
                        return_value="cancel",
                    ) as pattern_prompt,
                ):
                    window._import_data_file()

                pattern_prompt.assert_called_once()
                inspections = pattern_prompt.call_args.args[0]
                self.assertEqual(
                    {inspection.has_header for inspection in inspections},
                    {True, False},
                )
                self.assertEqual(window._workspace.dataset_names(), [])
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
