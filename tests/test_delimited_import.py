"""Regression coverage for automatic CSV/TXT delimiter inference."""

from __future__ import annotations

import os
import gc
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtTest import QTest
from PySide6.QtCore import QCoreApplication, QEvent

from core.file_io import (
    AUTO_DATA_KIND,
    AUTO_DELIMITER,
    AUTO_ENCODING,
    AUTO_NUMBER_FORMAT,
    AUTO_SPECTROMETER,
    DATA_KIND_SPECTRAL_MAP,
    DATA_KIND_SPECTRUM,
    ImportOptions,
    NUMBER_FORMAT_COMMA_DECIMAL,
    NUMBER_FORMAT_DOT_DECIMAL,
    SPECTROMETER_BWTEK,
    SPECTROMETER_HORIBA,
    inspect_delimited_file,
    read_leading_metadata,
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
        self.assertEqual(ImportOptions().encoding, AUTO_ENCODING)
        self.assertIsNone(ImportOptions().has_header)
        self.assertIsNone(ImportOptions().skip_rows)
        self.assertEqual(ImportOptions().data_kind, AUTO_DATA_KIND)
        self.assertEqual(ImportOptions().spectrometer, AUTO_SPECTROMETER)
        self.assertEqual(ImportOptions().number_format, AUTO_NUMBER_FORMAT)
        dialog = ImportOptionsDialog()
        try:
            self.assertEqual(dialog._delimiter_combo.currentData(), AUTO_DELIMITER)
            self.assertEqual(dialog._encoding_combo.currentData(), AUTO_ENCODING)
            self.assertEqual(dialog._data_kind_combo.currentData(), AUTO_DATA_KIND)
            self.assertEqual(dialog._spectrometer_combo.currentData(), AUTO_SPECTROMETER)
            self.assertEqual(dialog._number_format_combo.currentData(), AUTO_NUMBER_FORMAT)
            self.assertEqual(dialog.options().delimiter, AUTO_DELIMITER)
            self.assertEqual(dialog.options().encoding, AUTO_ENCODING)
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

    def test_auto_detects_windows_1252_horiba_text_and_preserves_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "horiba_ansi.txt"
            path.write_bytes(
                "#Operator=Mueller\n#Temperature=23 °C\nRaman Shift\tIntensity\n100\t4\n200\t8\n".encode(
                    "cp1252"
                )
            )
            inspection = inspect_delimited_file(path)
            frame = read_tabular_file(
                path,
                ImportOptions(data_kind=DATA_KIND_SPECTRUM, spectrometer=SPECTROMETER_HORIBA),
            )
            metadata = read_leading_metadata(
                path, inspection.metadata_rows, encoding=inspection.encoding
            )

        self.assertEqual(inspection.encoding, "cp1252")
        self.assertEqual(frame.columns.tolist(), ["Raman Shift", "Intensity"])
        self.assertEqual(frame["Intensity"].tolist(), [4, 8])
        self.assertIn("#Temperature=23 °C", metadata.raw_lines)

    def test_auto_infers_whitespace_delimited_text(self) -> None:
        frame = self._read("space.txt", "name value\na    1\nb    2\n")

        self.assertEqual(frame.columns.tolist(), ["name", "value"])
        self.assertEqual(frame["value"].tolist(), [1, 2])

    def test_separator_free_file_remains_one_column(self) -> None:
        frame = self._read("single.csv", "name\nalpha\nbeta\n")

        self.assertEqual(frame.columns.tolist(), ["name"])
        self.assertEqual(frame["name"].tolist(), ["alpha", "beta"])

    def test_auto_preserves_detected_metadata_and_detects_header(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "instrument.dat"
            path.write_text(
                "Instrument;TDTR\nOperator;Julia\ntime;signal\n0;1.5\n1;2.5\n",
                encoding="utf-8",
            )

            inspection = inspect_delimited_file(path)
            frame = read_tabular_file(path, ImportOptions())
            metadata = read_leading_metadata(path, inspection.metadata_rows)

        self.assertEqual(inspection.delimiter, ";")
        self.assertEqual(inspection.metadata_rows, 2)
        self.assertTrue(inspection.has_header)
        self.assertEqual(inspection.column_names, ("time", "signal"))
        self.assertEqual(frame.columns.tolist(), ["time", "signal"])
        self.assertEqual(frame["signal"].tolist(), [1.5, 2.5])
        self.assertEqual(
            metadata.fields,
            (("Instrument", "TDTR"), ("Operator", "Julia")),
        )
        self.assertEqual(
            metadata.raw_lines,
            ("Instrument;TDTR", "Operator;Julia"),
        )

    def test_horiba_decimal_comma_columns_become_numeric(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "horiba.txt"
            path.write_text(
                "#Title=\tSilicon\n"
                "#AxisUnit[0]=\tCnt\n"
                "#AxisUnit[1]=\t1/cm\n"
                "93,48840\t0,0000000E+00\n"
                "93,97052\t13,44897\n",
                encoding="utf-8",
            )

            inspection = inspect_delimited_file(path)
            frame = read_tabular_file(path, ImportOptions())
            metadata = read_leading_metadata(path, inspection.metadata_rows)

        self.assertEqual(inspection.delimiter, "\t")
        self.assertEqual(inspection.metadata_rows, 3)
        self.assertEqual(frame.iloc[:, 0].tolist(), [93.4884, 93.97052])
        self.assertEqual(frame.iloc[:, 1].tolist(), [0.0, 13.44897])
        self.assertEqual(metadata.fields[0], ("Title", "Silicon"))

    def test_auto_number_format_handles_decimal_comma_and_grouping(self) -> None:
        frame = self._read(
            "european.csv",
            "value;uncertainty\n1.234,56;12,5\n2.345,67;25,75\n",
        )

        self.assertEqual(frame["value"].tolist(), [1234.56, 2345.67])
        self.assertEqual(frame["uncertainty"].tolist(), [12.5, 25.75])

    def test_explicit_number_format_resolves_ambiguous_separators(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            point_path = Path(folder) / "point.csv"
            point_path.write_text('value\n"1,234.56"\n"2,345.67"\n', encoding="utf-8")
            comma_path = Path(folder) / "comma.csv"
            comma_path.write_text("value;other\n1.234;2.345\n", encoding="utf-8")

            point_frame = read_tabular_file(
                point_path,
                ImportOptions(number_format=NUMBER_FORMAT_DOT_DECIMAL),
            )
            comma_frame = read_tabular_file(
                comma_path,
                ImportOptions(number_format=NUMBER_FORMAT_COMMA_DECIMAL),
            )
            auto_frame = read_tabular_file(comma_path, ImportOptions())

        self.assertEqual(point_frame["value"].tolist(), [1234.56, 2345.67])
        self.assertEqual(comma_frame.iloc[0].tolist(), [1234.0, 2345.0])
        self.assertEqual(auto_frame.iloc[0].tolist(), [1.234, 2.345])

    def test_bruker_coordinate_record_becomes_two_column_spectrum(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bruker.dat"
            path.write_text(
                "#d 3x1\n#r Sample A\n#c 4000 3998 3996\n0.1\n0.2\n0.3\n",
                encoding="utf-8",
            )

            inspection = inspect_delimited_file(path)
            frame = read_tabular_file(path, ImportOptions())
            metadata = read_leading_metadata(path, inspection.metadata_rows)

        self.assertEqual(inspection.format_name, "bruker_ir")
        self.assertEqual(inspection.column_names, ("Wavenumber", "Intensity"))
        self.assertEqual(frame.columns.tolist(), ["Wavenumber", "Intensity"])
        self.assertEqual(frame["Wavenumber"].tolist(), [4000.0, 3998.0, 3996.0])
        self.assertEqual(frame["Intensity"].tolist(), [0.1, 0.2, 0.3])
        self.assertEqual(metadata.fields[1], ("r", "Sample A"))

    def test_horiba_map_with_blank_coordinate_headers_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "horiba_map.txt"
            path.write_text(
                "#Title=\tSilicon map\n"
                "\t\t100.0\t101.0\t102.0\n"
                "0.0\t0.0\t142.5\t138.1\t450.2\n"
                "0.0\t1.0\t139.0\t140.2\t480.9\n"
                "1.0\t0.0\t151.2\t145.8\t421.5\n",
                encoding="utf-8",
            )

            inspection = inspect_delimited_file(path)
            frame = read_tabular_file(path, ImportOptions())
            metadata = read_leading_metadata(path, inspection.metadata_rows)

        self.assertEqual(inspection.format_name, "spectral_map_matrix")
        self.assertEqual(inspection.metadata_rows, 1)
        self.assertTrue(inspection.has_header)
        self.assertEqual(
            frame.columns.tolist(),
            ["X", "Y", "Raman Shift", "Intensity"],
        )
        self.assertEqual(frame.shape, (9, 4))
        self.assertEqual(frame.iloc[0].tolist(), [0.0, 0.0, 100.0, 142.5])
        self.assertEqual(frame.iloc[1].tolist(), [0.0, 0.0, 101.0, 138.1])
        self.assertEqual(frame.iloc[3].tolist(), [0.0, 1.0, 100.0, 139.0])
        self.assertEqual(metadata.fields, (("Title", "Silicon map"),))

    def test_horiba_map_with_coordinate_labels_is_detected(self) -> None:
        frame = self._read(
            "horiba_labelled_map.txt",
            "X_Coord\tY_Coord\t175.2\t177.8\t180.4\n"
            "0.0\t0.0\t134\t138\t142\n"
            "0.0\t1.0\t135\t141\t144\n"
            "1.0\t0.0\t142\t145\t153\n",
        )

        self.assertEqual(frame.columns.tolist(), ["X", "Y", "Raman Shift", "Intensity"])
        self.assertEqual(frame.shape, (9, 4))
        self.assertEqual(frame["Raman Shift"].iloc[:3].tolist(), [175.2, 177.8, 180.4])
        self.assertEqual(frame["Intensity"].iloc[:3].tolist(), [134.0, 138.0, 142.0])

    def test_horiba_map_preserves_decimal_comma_spectral_axis(self) -> None:
        frame = self._read(
            "horiba_comma_map.txt",
            "X\tY\t100,5\t101,5\n"
            "0,0\t0,0\t1.234,5\t2.345,5\n"
            "0,0\t1,0\t1.235,5\t2.346,5\n",
        )

        self.assertEqual(frame["Raman Shift"].iloc[:2].tolist(), [100.5, 101.5])
        self.assertEqual(frame["Intensity"].iloc[:2].tolist(), [1234.5, 2345.5])

    def test_explicit_horiba_map_profile_normalizes_and_rejects_non_maps(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            map_path = Path(folder) / "map.txt"
            map_path.write_text(
                "X\tY\t100\t200\n0\t0\t1\t2\n0\t1\t3\t4\n",
                encoding="utf-8",
            )
            spectrum_path = Path(folder) / "spectrum.txt"
            spectrum_path.write_text("Shift\tIntensity\n100\t1\n200\t2\n", encoding="utf-8")
            options = ImportOptions(
                data_kind=DATA_KIND_SPECTRAL_MAP,
                spectrometer=SPECTROMETER_HORIBA,
            )

            frame = read_tabular_file(map_path, options)
            with self.assertRaisesRegex(ValueError, "Horiba spectroscopy-map profile"):
                read_tabular_file(spectrum_path, options)

        self.assertEqual(frame.columns.tolist(), ["X", "Y", "Raman Shift", "Intensity"])
        self.assertEqual(frame.shape, (4, 4))

    def test_bwtek_profile_is_limited_to_single_spectra(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bwtek.txt"
            path.write_text(
                "Pixel;Wavelength;Raman Shift;Raw data\n1;500;100;12\n2;501;101;14\n",
                encoding="utf-8",
            )
            frame = read_tabular_file(
                path,
                ImportOptions(
                    data_kind=DATA_KIND_SPECTRUM,
                    spectrometer=SPECTROMETER_BWTEK,
                ),
            )
            with self.assertRaisesRegex(ValueError, "B&W Tek map import is not supported"):
                read_tabular_file(
                    path,
                    ImportOptions(
                        data_kind=DATA_KIND_SPECTRAL_MAP,
                        spectrometer=SPECTROMETER_BWTEK,
                    ),
                )

        self.assertEqual(
            frame.columns.tolist(),
            ["Pixel", "Wavelength", "Raman Shift", "Raw data"],
        )
        self.assertEqual(frame["Raw data"].tolist(), [12, 14])

    def test_dialog_rejects_bwtek_map_profile(self) -> None:
        dialog = ImportOptionsDialog()
        try:
            dialog._data_kind_combo.setCurrentIndex(
                dialog._data_kind_combo.findData(DATA_KIND_SPECTRAL_MAP)
            )
            dialog._spectrometer_combo.setCurrentIndex(
                dialog._spectrometer_combo.findData(SPECTROMETER_BWTEK)
            )
            with patch.object(QMessageBox, "warning") as warning:
                dialog.accept()

            warning.assert_called_once()
            self.assertNotEqual(dialog.result(), QDialog.Accepted)
        finally:
            dialog.close()

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
                dialog._data_kind_combo.setCurrentIndex(
                    dialog._data_kind_combo.findData(DATA_KIND_SPECTRUM)
                )
                dialog._spectrometer_combo.setCurrentIndex(
                    dialog._spectrometer_combo.findData(SPECTROMETER_BWTEK)
                )
                options = dialog.options()
                self.assertEqual(options.data_kind, DATA_KIND_SPECTRUM)
                self.assertEqual(options.spectrometer, SPECTROMETER_BWTEK)
            finally:
                dialog.close()


class DelimitedBatchImportTests(unittest.TestCase):
    """Exercise multi-file importing and header-pattern resolution."""

    def setUp(self) -> None:
        # Dispose unreachable widgets from earlier GUI tests on the GUI thread.
        gc.collect()

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
                    deadline = time.monotonic() + 15
                    while window._text_import_token is not None and time.monotonic() < deadline:
                        QTest.qWait(5)
                    self.assertIsNone(window._text_import_token, "Background import did not finish")

                self.assertEqual(window._workspace.dataset_names(), ["first", "second"])
                self.assertEqual(
                    window._workspace.get_dataset("second").frame.columns.tolist(),
                    ["x", "y"],
                )
                first_dataset = window._workspace.get_dataset("first")
                self.assertEqual(first_dataset.worksheet_metadata.raw_lines, [])
                self.assertEqual(
                    first_dataset.worksheet_metadata.import_details["Format"],
                    "Delimited text",
                )
            finally:
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                gc.collect()

    def test_import_attaches_raw_and_parsed_preamble_to_worksheet(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "spectrum.txt"
            source.write_text(
                "$LASER=532 nm\n% Operator: Julia\nRaman Shift\tIntensity\n100\t4\n200\t8\n",
                encoding="utf-8",
            )
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
                        return_value=([str(source)], ""),
                    ),
                    patch("ui.main_window.ImportOptionsDialog", FakeImportDialog),
                    patch.object(window, "_confirm_large_file_import", return_value=True),
                    patch.object(window, "_confirm_large_dataset", return_value=True),
                ):
                    window._import_data_file()
                    deadline = time.monotonic() + 15
                    while window._text_import_token is not None and time.monotonic() < deadline:
                        QTest.qWait(5)
                    self.assertIsNone(window._text_import_token, "Background import did not finish")

                dataset = window._workspace.get_dataset("spectrum")
                self.assertEqual(
                    dataset.worksheet_metadata.raw_lines,
                    ["$LASER=532 nm", "% Operator: Julia"],
                )
                self.assertEqual(
                    dataset.worksheet_metadata.fields,
                    [("LASER", "532 nm"), ("Operator", "Julia")],
                )
                self.assertEqual(dataset.column_metadata["Raman Shift"].role, "x")
                self.assertEqual(dataset.column_metadata["Intensity"].role, "y")
            finally:
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                gc.collect()

    def test_imported_spectral_map_records_layout_and_coordinate_roles(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "map.txt"
            source.write_text(
                "\t\t175.2\t177.8\n"
                "0\t0\t10\t11\n"
                "0\t1\t12\t13\n"
                "1\t0\t14\t15\n",
                encoding="utf-8",
            )
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
                    return ImportOptions(
                        data_kind=DATA_KIND_SPECTRAL_MAP,
                        spectrometer=SPECTROMETER_HORIBA,
                    )

            try:
                with (
                    patch(
                        "ui.main_window.QFileDialog.getOpenFileNames",
                        return_value=([str(source)], ""),
                    ),
                    patch("ui.main_window.ImportOptionsDialog", FakeImportDialog),
                    patch.object(window, "_confirm_large_file_import", return_value=True),
                    patch.object(window, "_confirm_large_dataset", return_value=True),
                ):
                    window._import_data_file()
                    deadline = time.monotonic() + 15
                    while window._text_import_token is not None and time.monotonic() < deadline:
                        QTest.qWait(5)
                    self.assertIsNone(window._text_import_token, "Background import did not finish")

                dataset = window._workspace.get_dataset("map")
                self.assertEqual(
                    dataset.frame.columns.tolist(),
                    ["X", "Y", "Raman Shift", "Intensity"],
                )
                self.assertEqual(dataset.frame.shape, (6, 4))
                self.assertEqual(dataset.column_metadata["X"].role, "x")
                self.assertEqual(dataset.column_metadata["Y"].role, "y")
                self.assertEqual(dataset.column_metadata["Raman Shift"].unit, "cm^-1")
                self.assertEqual(
                    dataset.worksheet_metadata.import_details["Format"],
                    "Spectral map matrix",
                )
                self.assertEqual(
                    dataset.worksheet_metadata.import_details["Raman shifts per pixel"],
                    "2",
                )
                self.assertEqual(
                    dataset.worksheet_metadata.import_details["Requested data type"],
                    "Spectroscopy map",
                )
                self.assertEqual(
                    dataset.worksheet_metadata.import_details["Spectrometer profile"],
                    "Horiba LabSpec",
                )
            finally:
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                gc.collect()

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
                    deadline = time.monotonic() + 15
                    while window._text_import_token is not None and time.monotonic() < deadline:
                        QTest.qWait(5)
                    self.assertIsNone(window._text_import_token, "Background import did not finish")

                pattern_prompt.assert_called_once()
                for name in ("first", "second"):
                    frame = window._workspace.get_dataset(name).frame
                    self.assertEqual(frame.columns.tolist(), ["Column 1", "Column 2"])
                    self.assertEqual(len(frame), 1)
            finally:
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                gc.collect()

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
                    deadline = time.monotonic() + 15
                    while window._text_import_token is not None and time.monotonic() < deadline:
                        QTest.qWait(5)
                    self.assertIsNone(window._text_import_token, "Background import did not finish")

                pattern_prompt.assert_called_once()
                inspections = pattern_prompt.call_args.args[0]
                self.assertEqual(
                    {inspection.has_header for inspection in inspections},
                    {True, False},
                )
                self.assertEqual(window._workspace.dataset_names(), [])
            finally:
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                gc.collect()


if __name__ == "__main__":
    unittest.main()
