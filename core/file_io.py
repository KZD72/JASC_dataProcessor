"""Tabular data import helpers for delimited files and Excel workbooks."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, replace
from io import BufferedReader, FileIO, StringIO
from pathlib import Path
import posixpath
import re
import time
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

import numpy as np
import pandas as pd

from core.jobs import JobContext


SUPPORTED_EXTENSIONS = {".csv", ".dat", ".txt"}
SUPPORTED_EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
AUTO_ENCODING = "auto"
SUPPORTED_TEXT_ENCODINGS = {
    AUTO_ENCODING,
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "cp1252",
    "latin-1",
}
AUTO_DELIMITER = "auto"
AUTO_DATA_KIND = "auto"
DATA_KIND_TABLE = "table"
DATA_KIND_SPECTRUM = "spectrum"
DATA_KIND_SPECTRAL_MAP = "spectral_map"
AUTO_SPECTROMETER = "auto"
SPECTROMETER_HORIBA = "horiba"
SPECTROMETER_BWTEK = "bwtek"
AUTO_NUMBER_FORMAT = "auto"
NUMBER_FORMAT_DOT_DECIMAL = "dot_decimal"
NUMBER_FORMAT_COMMA_DECIMAL = "comma_decimal"
SUPPORTED_NUMBER_FORMATS = {
    AUTO_NUMBER_FORMAT,
    NUMBER_FORMAT_DOT_DECIMAL,
    NUMBER_FORMAT_COMMA_DECIMAL,
}
SUPPORTED_DATA_KINDS = {
    AUTO_DATA_KIND,
    DATA_KIND_TABLE,
    DATA_KIND_SPECTRUM,
    DATA_KIND_SPECTRAL_MAP,
}
SUPPORTED_SPECTROMETERS = {
    AUTO_SPECTROMETER,
    SPECTROMETER_HORIBA,
    SPECTROMETER_BWTEK,
}
_INFERRED_DELIMITER_CANDIDATES = ",;\t| "
_DELIMITER_SAMPLE_SIZE = 128 * 1024

_DIMENSION_PATTERN = re.compile(rb"<(?:[A-Za-z0-9_]+:)?dimension\b[^>]*\bref=\"([^\"]+)\"")


@dataclass(frozen=True, slots=True)
class ImportOptions:
    """User-selected parser options for delimited text files."""

    delimiter: str = AUTO_DELIMITER
    has_header: bool | None = None
    encoding: str = AUTO_ENCODING
    skip_rows: int | None = None
    data_kind: str = AUTO_DATA_KIND
    spectrometer: str = AUTO_SPECTROMETER
    number_format: str = AUTO_NUMBER_FORMAT


@dataclass(frozen=True, slots=True)
class DelimitedFileInspection:
    """Detected structure for one delimited text file before import."""

    path: Path
    delimiter: str
    metadata_rows: int
    has_header: bool
    column_names: tuple[str, ...]
    column_count: int
    preview_rows: tuple[tuple[str, ...], ...]
    format_name: str = "delimited"
    spectral_axis: tuple[str, ...] = ()
    encoding: str = "utf-8"

    @property
    def delimiter_label(self) -> str:
        """Return a compact user-facing name for the detected separator."""
        return {
            ",": "Comma",
            ";": "Semicolon",
            "\t": "Tab",
            "|": "Pipe",
            " ": "Whitespace",
        }.get(self.delimiter, repr(self.delimiter))


@dataclass(frozen=True, slots=True)
class ExcelSheetInfo:
    """One workbook tab discovered during the OOXML preflight."""

    name: str
    state: str = "visible"
    sheet_type: str = "worksheet"
    used_range: str = "Unknown"

    @property
    def is_importable(self) -> bool:
        """Return whether this tab contains worksheet cells pandas can parse."""
        return self.sheet_type == "worksheet"


@dataclass(frozen=True, slots=True)
class ExcelWorkbookInspection:
    """Workbook tabs and value-only import warnings from an OOXML preflight."""

    sheets: tuple[ExcelSheetInfo, ...]
    warnings: tuple[str, ...]

    @property
    def importable_sheets(self) -> tuple[ExcelSheetInfo, ...]:
        """Return worksheet tabs, excluding chart-only and unsupported tab types."""
        return tuple(sheet for sheet in self.sheets if sheet.is_importable)


@dataclass(slots=True)
class ExcelReadResult:
    """Frames parsed from selected sheets plus isolated per-sheet failures."""

    frames: dict[str, pd.DataFrame]
    errors: dict[str, str]


@dataclass(frozen=True, slots=True)
class DelimitedMetadata:
    """Exact leading text plus best-effort key/value metadata fields."""

    raw_lines: tuple[str, ...]
    fields: tuple[tuple[str, str], ...]


def read_tabular_file(
    path: str | Path, options: ImportOptions, *, context: JobContext | None = None,
) -> pd.DataFrame:
    """Read a CSV/TXT file into a DataFrame using the selected import options."""
    if context is not None:
        context.check_cancelled()
    validate_import_profile(options.data_kind, options.spectrometer)
    validate_number_format(options.number_format)
    if options.data_kind == DATA_KIND_SPECTRAL_MAP and options.has_header is False:
        raise ValueError(
            "Spectroscopy maps require the first tabular row to contain the spectral axis. "
            "Use Auto headers or select that the first tabular row contains column names."
        )
    file_path = _validated_tabular_path(path)
    resolved_encoding = resolve_text_encoding(file_path, options.encoding)
    inspection: DelimitedFileInspection | None = None
    if (
        options.delimiter == AUTO_DELIMITER
        or options.has_header is None
        or options.skip_rows is None
        or options.data_kind == DATA_KIND_SPECTRAL_MAP
    ):
        inspection = inspect_delimited_file(
            file_path,
            delimiter=options.delimiter,
            encoding=resolved_encoding,
            skip_rows=options.skip_rows,
            data_kind=options.data_kind,
            spectrometer=options.spectrometer,
        )
    delimiter = inspection.delimiter if inspection is not None else options.delimiter
    resolved_encoding = inspection.encoding if inspection is not None else resolved_encoding
    has_header = (
        inspection.has_header
        if options.has_header is None and inspection is not None
        else bool(options.has_header)
    )
    skip_rows = (
        inspection.metadata_rows
        if options.skip_rows is None and inspection is not None
        else max(int(options.skip_rows or 0), 0)
    )
    if inspection is not None and inspection.format_name == "bruker_ir":
        return _read_bruker_ir_export(file_path, resolved_encoding)
    if (
        inspection is not None
        and inspection.format_name == "spectral_map_matrix"
        and has_header
    ):
        return _read_spectral_map_matrix(
            file_path,
            inspection,
            encoding=resolved_encoding,
            number_format=options.number_format,
            context=context,
        )

    read_kwargs = _build_read_csv_kwargs(
        replace(options, encoding=resolved_encoding),
        delimiter=delimiter,
        has_header=has_header,
        skip_rows=skip_rows,
    )

    try:
        frame = _read_standard_numeric_table(file_path, read_kwargs, options.number_format, context=context)
        if frame is None:
            frame = _read_csv_with_context(file_path, read_kwargs, context)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Could not decode the file with the selected {resolved_encoding} encoding."
        ) from exc
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        source = "inferred" if options.delimiter == AUTO_DELIMITER else "selected"
        raise ValueError(f"Could not parse the file with the {source} delimiter: {exc}") from exc

    if frame.empty:
        raise ValueError("The selected file did not contain any rows.")

    if not has_header:
        frame.columns = [f"Column {index + 1}" for index in range(len(frame.columns))]
    return _convert_localized_numeric_columns(
        frame,
        delimiter,
        number_format=options.number_format,
        context=context,
    )


def read_leading_metadata(
    path: str | Path,
    row_count: int,
    *,
    encoding: str = AUTO_ENCODING,
) -> DelimitedMetadata:
    """Read and parse the physical lines preceding an imported table.

    Raw lines are retained without their newline terminators. Parsing is
    deliberately best-effort: vendor-specific records remain available in
    ``raw_lines`` even when no reliable key/value split can be inferred.
    """
    file_path = _validated_tabular_path(path)
    resolved_encoding = resolve_text_encoding(file_path, encoding)
    requested_rows = max(int(row_count), 0)
    raw_lines: list[str] = []
    try:
        with file_path.open("r", encoding=resolved_encoding, newline="") as stream:
            for _index, line in zip(range(requested_rows), stream, strict=False):
                raw_lines.append(line.rstrip("\r\n"))
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Could not decode the file with the selected {resolved_encoding} encoding."
        ) from exc

    fields = tuple(
        parsed
        for line in raw_lines
        if (parsed := _parse_metadata_line(line)) is not None
    )
    return DelimitedMetadata(raw_lines=tuple(raw_lines), fields=fields)


def inspect_excel_workbook(path: str | Path) -> ExcelWorkbookInspection:
    """Inspect an OOXML workbook without executing formulas or loading cell data.

    The preflight reads workbook relationships and package member names directly.
    This exposes worksheet tabs and unsupported Excel objects before `openpyxl`
    parses any selected cell ranges.
    """
    file_path = _validated_excel_path(path)
    try:
        with ZipFile(file_path) as archive:
            names = tuple(archive.namelist())
            workbook_root = _read_xml_member(archive, "xl/workbook.xml")
            relationship_root = _read_xml_member(archive, "xl/_rels/workbook.xml.rels")
            relationships = _workbook_relationships(relationship_root)
            sheets = _inspect_excel_sheets(archive, workbook_root, relationships)
            warnings = _excel_package_warnings(file_path, names, workbook_root, sheets)
    except BadZipFile as exc:
        raise ValueError(
            "The selected workbook is not a readable .xlsx/.xlsm package. "
            "Encrypted, legacy .xls, and damaged workbooks are not supported."
        ) from exc

    if not sheets:
        raise ValueError("The workbook did not contain any worksheet tabs.")
    return ExcelWorkbookInspection(sheets=tuple(sheets), warnings=tuple(warnings))


def read_excel_sheets(
    path: str | Path,
    sheet_names: list[str] | tuple[str, ...],
    *,
    has_header: bool = True,
) -> ExcelReadResult:
    """Read selected Excel worksheet tabs as cached values only.

    Each sheet is parsed independently so one malformed or empty tab does not
    discard successfully read tabs. `openpyxl` never evaluates formulas or runs
    VBA; pandas receives only the values cached in the workbook file.
    """
    file_path = _validated_excel_path(path)
    requested = list(dict.fromkeys(str(name) for name in sheet_names if str(name).strip()))
    if not requested:
        raise ValueError("Choose at least one worksheet tab to import.")

    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    try:
        with pd.ExcelFile(file_path, engine="openpyxl") as workbook:
            available = set(workbook.sheet_names)
            for sheet_name in requested:
                if sheet_name not in available:
                    errors[sheet_name] = "Worksheet tab was not found in the workbook."
                    continue
                try:
                    frame = workbook.parse(
                        sheet_name=sheet_name,
                        header=0 if has_header else None,
                    )
                    if not has_header:
                        frame.columns = [f"Column {index + 1}" for index in range(len(frame.columns))]
                    else:
                        frame.columns = _normalized_excel_headers(frame.columns)
                    frames[sheet_name] = frame
                except Exception as exc:  # isolate a broken tab from other selected tabs
                    errors[sheet_name] = str(exc)
    except ImportError as exc:
        raise RuntimeError(
            "Excel import requires openpyxl. Install the dependencies from requirements.txt."
        ) from exc
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not open Excel workbook '{file_path.name}': {exc}") from exc

    return ExcelReadResult(frames=frames, errors=errors)


def export_tabular_file(
    frame: pd.DataFrame,
    path: str | Path,
    delimiter: str = ",",
    include_index: bool = False,
    encoding: str = "utf-8",
) -> None:
    """Export a DataFrame to a delimited text file."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Only pandas DataFrames can be exported.")

    file_path = Path(path)
    if not file_path.parent.exists():
        raise FileNotFoundError(f"Folder does not exist: {file_path.parent}")

    try:
        frame.to_csv(file_path, sep=delimiter, index=include_index, encoding=encoding)
    except OSError as exc:
        raise OSError(f"Could not export data to {file_path}: {exc}") from exc


def infer_tabular_delimiter(
    path: str | Path,
    encoding: str = AUTO_ENCODING,
) -> str:
    """Infer a common delimiter from a bounded text sample.

    Files without delimiter evidence are intentionally treated as comma-separated;
    pandas will then read them as a valid single-column table. Restricting Sniffer's
    candidate set prevents letters or digits in single-column data being mistaken
    for separators.
    """
    file_path = _validated_tabular_path(path)
    sample = _read_delimited_sample(file_path, resolve_text_encoding(file_path, encoding))
    inference_sample = _without_leading_comment_records(sample)

    if not inference_sample.strip():
        return ","
    localized_delimiter = _delimiter_around_decimal_commas(inference_sample)
    if localized_delimiter is not None:
        return localized_delimiter
    try:
        dialect = csv.Sniffer().sniff(
            inference_sample,
            delimiters=_INFERRED_DELIMITER_CANDIDATES,
        )
    except csv.Error:
        lines = [line.strip() for line in inference_sample.splitlines() if line.strip()]
        whitespace_widths = [len(re.split(r"\s+", line)) for line in lines]
        if (
            len(whitespace_widths) >= 2
            and whitespace_widths[0] > 1
            and len(set(whitespace_widths)) == 1
        ):
            return " "
        return ","
    return str(dialect.delimiter)


def _delimiter_around_decimal_commas(sample: str) -> str | None:
    """Prefer a structural separator when commas are localized decimals."""
    lines = [line for line in sample.splitlines() if line.strip()][:50]
    numeric_lines = [line for line in lines if re.search(r"\d,\d", line)]
    if len(numeric_lines) < 2:
        return None
    for candidate in ("\t", ";", "|"):
        counts = [line.count(candidate) for line in numeric_lines]
        if counts and min(counts) > 0 and len(set(counts)) == 1:
            comma_positions_are_decimal = all(
                all(
                    0 < match.start() < len(line) - 1
                    and line[match.start() - 1].isdigit()
                    and line[match.start() + 1].isdigit()
                    for match in re.finditer(",", line)
                )
                for line in numeric_lines
            )
            if comma_positions_are_decimal:
                return candidate
    return None


def inspect_delimited_file(
    path: str | Path,
    *,
    delimiter: str = AUTO_DELIMITER,
    encoding: str = AUTO_ENCODING,
    skip_rows: int | None = None,
    data_kind: str = AUTO_DATA_KIND,
    spectrometer: str = AUTO_SPECTROMETER,
) -> DelimitedFileInspection:
    """Infer separator, leading metadata rows, header presence, and a short preview."""
    validate_import_profile(data_kind, spectrometer)
    file_path = _validated_tabular_path(path)
    resolved_encoding = resolve_text_encoding(file_path, encoding)
    sample = _read_delimited_sample(file_path, resolved_encoding)
    if not sample.strip():
        raise ValueError("The selected file did not contain any rows.")
    if (
        delimiter == AUTO_DELIMITER
        and skip_rows is None
        and data_kind in {AUTO_DATA_KIND, DATA_KIND_SPECTRUM}
        and spectrometer == AUTO_SPECTROMETER
    ):
        bruker_inspection = _inspect_bruker_ir_export(file_path, sample)
        if bruker_inspection is not None:
            return replace(bruker_inspection, encoding=resolved_encoding)
    resolved_delimiter = (
        infer_tabular_delimiter(file_path, resolved_encoding)
        if delimiter == AUTO_DELIMITER
        else delimiter
    )
    parsed_rows = _sample_delimited_rows(sample, resolved_delimiter)
    if not parsed_rows:
        raise ValueError("The selected file did not contain any readable rows.")

    minimum_line = max(int(skip_rows or 0), 0) if skip_rows is not None else 0
    if (
        data_kind in {AUTO_DATA_KIND, DATA_KIND_SPECTRAL_MAP}
        and spectrometer in {AUTO_SPECTROMETER, SPECTROMETER_HORIBA}
    ):
        spectral_map_inspection = _inspect_spectral_map_matrix(
            file_path,
            parsed_rows,
            resolved_delimiter,
            minimum_line=minimum_line,
        )
        if spectral_map_inspection is not None:
            return replace(spectral_map_inspection, encoding=resolved_encoding)
        if data_kind == DATA_KIND_SPECTRAL_MAP:
            raise ValueError(
                "The selected Horiba spectroscopy-map profile did not match this file. "
                "Expected a tabular header with X and Y coordinate cells followed by "
                "numeric Raman-shift values."
            )

    if skip_rows is None:
        first_candidate_line = _first_noncomment_line_number(sample)
        first_candidate_position = next(
            (
                position
                for position, (line_number, _row) in enumerate(parsed_rows)
                if line_number >= first_candidate_line
            ),
            0,
        )
        candidate_rows = parsed_rows[first_candidate_position:]
        table_width = _dominant_table_width(candidate_rows)
        base_position = first_candidate_position + _first_stable_width_position(
            candidate_rows,
            table_width,
        )
        table_position, has_header = _infer_table_start_and_header(
            parsed_rows,
            base_position,
            table_width,
            resolved_delimiter,
        )
    else:
        requested_start = max(int(skip_rows), 0)
        table_position = next(
            (
                position
                for position, (line_number, _row) in enumerate(parsed_rows)
                if line_number >= requested_start
            ),
            len(parsed_rows) - 1,
        )
        table_width = len(parsed_rows[table_position][1])
        has_header = _infer_header_at_position(
            parsed_rows,
            table_position,
            table_width,
            resolved_delimiter,
        )
    line_number, table_row = parsed_rows[table_position]
    metadata_rows = line_number if skip_rows is None else max(int(skip_rows), 0)
    if has_header:
        column_names = tuple(_normalized_excel_headers(pd.Index(table_row)))
        preview_start = table_position + 1
    else:
        column_names = tuple(f"Column {index + 1}" for index in range(table_width))
        preview_start = table_position
    preview = tuple(
        tuple(row[:table_width])
        for _line, row in parsed_rows[preview_start:]
        if len(row) == table_width
    )[:5]
    return DelimitedFileInspection(
        path=file_path,
        delimiter=resolved_delimiter,
        metadata_rows=metadata_rows,
        has_header=has_header,
        column_names=column_names,
        column_count=table_width,
        preview_rows=preview,
        encoding=resolved_encoding,
    )


def validate_import_profile(data_kind: str, spectrometer: str) -> None:
    """Validate the supported data-kind and spectrometer combinations."""
    if data_kind not in SUPPORTED_DATA_KINDS:
        raise ValueError(f"Unsupported import data type: {data_kind!r}.")
    if spectrometer not in SUPPORTED_SPECTROMETERS:
        raise ValueError(f"Unsupported spectrometer profile: {spectrometer!r}.")
    if data_kind == DATA_KIND_SPECTRAL_MAP and spectrometer == SPECTROMETER_BWTEK:
        raise ValueError(
            "B&W Tek map import is not supported yet. Select Single spectrum for B&W Tek "
            "files, or Horiba LabSpec for spectroscopy maps."
        )


def validate_number_format(number_format: str) -> None:
    """Validate a requested decimal/thousands-separator convention."""
    if number_format not in SUPPORTED_NUMBER_FORMATS:
        raise ValueError(f"Unsupported number format: {number_format!r}.")


_X_COORDINATE_LABELS = {
    "",
    "x",
    "xcoord",
    "xcoordinate",
    "xposition",
    "xpos",
    "mapx",
}
_Y_COORDINATE_LABELS = {
    "",
    "y",
    "ycoord",
    "ycoordinate",
    "yposition",
    "ypos",
    "mapy",
}


def _inspect_spectral_map_matrix(
    file_path: Path,
    rows: list[tuple[int, tuple[str, ...]]],
    delimiter: str,
    *,
    minimum_line: int = 0,
) -> DelimitedFileInspection | None:
    """Recognize a wide X/Y plus spectral-intensity matrix.

    Horiba LabSpec maps may leave the first two header cells blank or label them
    as X/Y coordinate columns. Every remaining header token is a Raman-shift
    value and each following row contains one spatial pixel spectrum.
    """
    for position, (line_number, header_row) in enumerate(rows):
        if line_number < minimum_line or len(header_row) < 4:
            continue
        x_label = _normalized_coordinate_label(header_row[0])
        y_label = _normalized_coordinate_label(header_row[1])
        if x_label not in _X_COORDINATE_LABELS or y_label not in _Y_COORDINATE_LABELS:
            continue
        if not all(_cell_kind(value) == "number" for value in header_row[2:]):
            continue

        data_rows = [
            row
            for _candidate_line, row in rows[position + 1 :]
            if len(row) == len(header_row)
        ][:5]
        if len(data_rows) < 2:
            continue
        if not all(
            all(_cell_kind(value) == "number" for value in row)
            for row in data_rows
        ):
            continue

        spectral_names = tuple(value.strip() for value in header_row[2:])
        first_data_row = data_rows[0]
        preview_rows = tuple(
            (
                first_data_row[0],
                first_data_row[1],
                spectral_name,
                first_data_row[index + 2],
            )
            for index, spectral_name in enumerate(spectral_names[:5])
        )
        return DelimitedFileInspection(
            path=file_path,
            delimiter=delimiter,
            metadata_rows=line_number,
            has_header=True,
            column_names=("X", "Y", "Raman Shift", "Intensity"),
            column_count=4,
            preview_rows=preview_rows,
            format_name="spectral_map_matrix",
            spectral_axis=spectral_names,
        )
    return None


def _normalized_coordinate_label(value: str) -> str:
    """Normalize common spatial-coordinate header variants for matching."""
    return re.sub(r"[^a-z0-9]+", "", value.strip().casefold())


def _read_spectral_map_matrix(
    file_path: Path,
    inspection: DelimitedFileInspection,
    *,
    encoding: str,
    number_format: str,
    context: JobContext | None = None,
) -> pd.DataFrame:
    """Normalize a wide spectral map into X/Y/shift/intensity rows."""
    read_kwargs: dict[str, object] = {
        "sep": inspection.delimiter,
        "header": 0,
        "encoding": encoding,
        "skiprows": inspection.metadata_rows,
        "dtype": "string",
    }
    if inspection.delimiter == " ":
        read_kwargs.update({"sep": r"\s+", "engine": "python"})
    try:
        wide_frame = _read_csv_with_context(file_path, read_kwargs, context)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Could not decode the spectral map with the selected {encoding} encoding."
        ) from exc
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise ValueError(f"Could not parse the spectral map matrix: {exc}") from exc

    expected_columns = len(inspection.spectral_axis) + 2
    if len(wide_frame.columns) != expected_columns:
        raise ValueError(
            "The spectral map header defines "
            f"{len(inspection.spectral_axis)} Raman shifts, but the table contains "
            f"{max(len(wide_frame.columns) - 2, 0)} intensity columns."
        )
    wide_frame.columns = ["X", "Y", *inspection.spectral_axis]
    wide_frame = _convert_localized_numeric_columns(
        wide_frame,
        inspection.delimiter,
        number_format=number_format,
        context=context,
    )
    if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in wide_frame.dtypes):
        raise ValueError("The spectral map contains non-numeric coordinate or intensity values.")

    try:
        resolved_axis_format = _resolved_number_format(
            pd.Series(inspection.spectral_axis, dtype="string"),
            delimiter=inspection.delimiter,
            requested=number_format,
        )
        shifts = np.asarray(
            [
                _required_localized_number(value, resolved_axis_format)
                for value in inspection.spectral_axis
            ],
            dtype="float64",
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("The spectral map header contains a non-numeric Raman shift.") from exc

    if context is not None:
        context.report(0, 0, f"Normalizing spectral map: {file_path.name}")
    pixel_count = len(wide_frame)
    shift_count = len(shifts)
    coordinates = wide_frame.iloc[:, :2].to_numpy(dtype="float64", copy=False)
    intensities = wide_frame.iloc[:, 2:].to_numpy(dtype="float64", copy=False)
    return pd.DataFrame({
        "X": np.repeat(coordinates[:, 0], shift_count),
        "Y": np.repeat(coordinates[:, 1], shift_count),
        "Raman Shift": np.tile(shifts, pixel_count),
        "Intensity": intensities.reshape(pixel_count * shift_count),
    })


def _inspect_bruker_ir_export(
    file_path: Path,
    sample: str,
) -> DelimitedFileInspection | None:
    """Recognize the legacy Bruker text layout used by the Raman application."""
    lines = sample.splitlines()
    coordinate_line = next(
        (
            (index, line)
            for index, line in enumerate(lines)
            if line.lstrip().lower().startswith("#c ")
        ),
        None,
    )
    if coordinate_line is None:
        return None
    coordinate_index, coordinate_text = coordinate_line
    if not any(line.lstrip().lower().startswith("#d ") for line in lines[:coordinate_index]):
        return None
    try:
        x_values = [float(token) for token in coordinate_text.lstrip()[2:].split()]
    except ValueError:
        return None
    if len(x_values) < 2:
        return None

    y_values: list[float] = []
    for line in lines[coordinate_index + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "$", "%")):
            continue
        try:
            y_values.append(float(stripped.replace(",", ".")))
        except ValueError:
            return None
        if len(y_values) >= 5:
            break
    if len(y_values) < 2:
        return None

    preview = tuple(
        (f"{x_value:g}", f"{y_value:g}")
        for x_value, y_value in zip(x_values, y_values, strict=False)
    )
    return DelimitedFileInspection(
        path=file_path,
        delimiter=" ",
        metadata_rows=coordinate_index + 1,
        has_header=False,
        column_names=("Wavenumber", "Intensity"),
        column_count=2,
        preview_rows=preview,
        format_name="bruker_ir",
    )


def _read_bruker_ir_export(file_path: Path, encoding: str) -> pd.DataFrame:
    """Read a Bruker IR export whose X coordinates are stored in ``#c``."""
    try:
        lines = file_path.read_text(encoding=encoding).splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Could not decode the Bruker export with the selected {encoding} encoding."
        ) from exc

    coordinate_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lstrip().lower().startswith("#c ")
        ),
        None,
    )
    if coordinate_index is None:
        raise ValueError("The Bruker export does not contain a #c coordinate record.")
    try:
        x_values = [
            float(token.replace(",", "."))
            for token in lines[coordinate_index].lstrip()[2:].split()
        ]
        y_values = [
            float(line.strip().replace(",", "."))
            for line in lines[coordinate_index + 1 :]
            if line.strip() and not line.lstrip().startswith(("#", "$", "%"))
        ]
    except ValueError as exc:
        raise ValueError("The Bruker export contains non-numeric spectrum values.") from exc
    if len(x_values) != len(y_values):
        raise ValueError(
            "The Bruker export contains "
            f"{len(x_values)} X coordinates but {len(y_values)} intensity values."
        )
    if not x_values:
        raise ValueError("The Bruker export does not contain spectrum values.")
    return pd.DataFrame({"Wavenumber": x_values, "Intensity": y_values})


_DOT_DECIMAL_NUMBER_PATTERN = re.compile(
    r"^[+-]?(?:(?:\d{1,3}(?:[, '\u00a0\u202f’]\d{3})+|\d+)"
    r"(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
)
_COMMA_DECIMAL_NUMBER_PATTERN = re.compile(
    r"^[+-]?(?:(?:\d{1,3}(?:[. '\u00a0\u202f’]\d{3})+|\d+)"
    r"(?:,\d*)?|,\d+)(?:[eE][+-]?\d+)?$"
)
_GROUPING_SPACES = " '\u00a0\u202f’"


class _JobReader(BufferedReader):
    """Check cancellation at parser reads and throttle byte progress updates."""

    def __init__(self, path: Path, context: JobContext) -> None:
        super().__init__(FileIO(path, "r"))
        self._context = context
        self._total = path.stat().st_size
        self._name = path.name
        self._last_report = 0.0

    def _report_read(self) -> None:
        self._context.check_cancelled()
        now = time.monotonic()
        if now - self._last_report >= 0.05:
            self._last_report = now
            self._context.report(self.tell(), self._total, f"Reading {self._name}")

    def read(self, size: int = -1) -> bytes:
        self._context.check_cancelled()
        data = super().read(size)
        self._report_read()
        return data

    def read1(self, size: int = -1) -> bytes:
        self._context.check_cancelled()
        data = super().read1(size)
        self._report_read()
        return data

    def readinto(self, buffer: object) -> int:
        self._context.check_cancelled()
        count = super().readinto(buffer)
        self._report_read()
        return count


def _read_csv_with_context(
    path: Path, kwargs: dict[str, object], context: JobContext | None,
) -> pd.DataFrame:
    """Keep normal parser behavior, optionally with cancellable byte reads."""
    if context is None:
        return pd.read_csv(path, **kwargs)
    context.report(0, 0, f"Reading {path.name}")
    with _JobReader(path, context) as stream:
        frame = pd.read_csv(stream, **kwargs)
    context.check_cancelled()
    return frame


def _read_standard_numeric_table(
    file_path: Path,
    read_kwargs: dict[str, object],
    number_format: str,
    *,
    context: JobContext | None = None,
) -> pd.DataFrame | None:
    """Try the native float parser, falling back losslessly for other tables.

    The bounded probe only chooses a parser. The entire file must parse as
    floats, with no infinities or empty columns, before accepting its result.
    Reject inferred Boolean columns: Pandas' explicit float parser would turn
    True/False into 1/0. Mixed, localized, and late-invalid columns always go
    through the original raw-token path. Float parsing retains signed zero.
    """
    if number_format == NUMBER_FORMAT_COMMA_DECIMAL or read_kwargs.get("engine", "c") != "c":
        return None
    probe_kwargs = dict(read_kwargs)
    probe_kwargs.pop("dtype", None)
    probe_kwargs["nrows"] = 128
    probe = _read_csv_with_context(file_path, probe_kwargs, context)
    if probe.empty or any(
        not pd.api.types.is_numeric_dtype(probe[column].dtype)
        or pd.api.types.is_bool_dtype(probe[column].dtype)
        or not probe[column].notna().any()
        for column in probe.columns
    ):
        return None
    numeric_kwargs = dict(read_kwargs)
    numeric_kwargs["dtype"] = "float64"
    numeric_kwargs["float_precision"] = "round_trip"
    # Prevent an isolated all-Boolean parser chunk from becoming numeric 1/0
    # after earlier chunks in the same column contained ordinary numbers.
    numeric_kwargs["low_memory"] = False
    try:
        frame = _read_csv_with_context(file_path, numeric_kwargs, context)
    except (ValueError, OverflowError):
        return None
    if any(
        not frame[column].notna().any() or np.isinf(frame[column].to_numpy()).any()
        for column in frame.columns
    ):
        return None
    return frame


def _localized_numeric_tokens(tokens: pd.Series, number_format: str) -> pd.Series:
    """Parse one complete token column, retaining NaN for invalid/nonfinite tokens.

    Grammar validation keeps grouping and locale rules identical to the scalar
    parser. Array conversion avoids invoking the locale parser for every cell;
    exceptional conversions fall back to its existing scalar behavior.
    """
    comma = number_format == NUMBER_FORMAT_COMMA_DECIMAL
    pattern = _COMMA_DECIMAL_NUMBER_PATTERN if comma else _DOT_DECIMAL_NUMBER_PATTERN
    valid = tokens.str.fullmatch(pattern).fillna(False)
    separators = ("." if comma else ",") + _GROUPING_SPACES
    normalized = tokens.str.translate(str.maketrans("", "", separators))
    if comma:
        normalized = normalized.str.replace(",", ".", regex=False)
    # Convert directly to float, retaining signed zero and Python-float rounding.
    # to_numeric can infer integers first (losing -0) or round long decimals.
    try:
        numeric = pd.Series(
            normalized.where(valid).to_numpy(dtype="float64", na_value=np.nan),
            index=tokens.index,
        )
    except (ValueError, OverflowError):
        numeric = pd.to_numeric(normalized.where(valid), errors="coerce").astype("float64")
    fallback = valid & numeric.isna()
    if fallback.any():
        numeric.loc[fallback] = [
            _parse_localized_number(str(value), number_format)
            for value in tokens.loc[fallback]
        ]
    return numeric.where(np.isfinite(numeric))


def _number_format_evidence(dot: pd.Series, comma: pd.Series) -> str | None:
    """Resolve a convention only from finite, unambiguous tokens."""
    dot_valid, comma_valid = dot.notna(), comma.notna()
    has_dot = bool((dot_valid & ~comma_valid).any())
    has_comma = bool((comma_valid & ~dot_valid).any())
    if has_dot == has_comma:
        return None
    return NUMBER_FORMAT_DOT_DECIMAL if has_dot else NUMBER_FORMAT_COMMA_DECIMAL


def _convert_localized_numeric_columns(
    frame: pd.DataFrame,
    delimiter: str,
    *,
    number_format: str = AUTO_NUMBER_FORMAT,
    context: JobContext | None = None,
) -> pd.DataFrame:
    """Convert complete numeric columns without reparsing locale evidence.

    Unambiguous columns commit immediately. Only ambiguous columns wait for
    table-level evidence, avoiding a second inference pass over every token.
    A single invalid nonblank token preserves the entire original text column.
    """
    validate_number_format(number_format)
    evidence: set[str] = set()
    pending: list[tuple[object, pd.Series, pd.Series, pd.Series]] = []

    def commit(column: object, meaningful: pd.Series, values: pd.Series) -> None:
        result = pd.Series(float("nan"), index=frame.index, dtype="float64")
        result.loc[meaningful] = values.to_numpy()
        frame[column] = result

    for position, column in enumerate(frame.columns):
        if context is not None:
            context.report(position, len(frame.columns), f"Validating column {column}")
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series.dtype):
            continue
        text = series.astype("string").str.strip()
        meaningful = text.notna() & text.ne("")
        if not meaningful.any():
            continue
        tokens = text.loc[meaningful]
        if number_format != AUTO_NUMBER_FORMAT:
            values = _localized_numeric_tokens(tokens, number_format)
            if values.notna().all():
                commit(column, meaningful, values)
            continue
        dot = _localized_numeric_tokens(tokens, NUMBER_FORMAT_DOT_DECIMAL)
        comma = _localized_numeric_tokens(tokens, NUMBER_FORMAT_COMMA_DECIMAL)
        inferred = _number_format_evidence(dot, comma)
        if inferred is not None:
            evidence.add(inferred)
            values = comma if inferred == NUMBER_FORMAT_COMMA_DECIMAL else dot
            if values.notna().all():
                commit(column, meaningful, values)
        elif dot.notna().all() and comma.notna().all():
            if dot.equals(comma):
                commit(column, meaningful, dot)
            else:
                pending.append((column, meaningful, dot, comma))
        # Conflicting or invalid columns stay verbatim, just as before.

    fallback = next(iter(evidence)) if len(evidence) == 1 else NUMBER_FORMAT_DOT_DECIMAL
    for column, meaningful, dot, comma in pending:
        commit(column, meaningful, comma if fallback == NUMBER_FORMAT_COMMA_DECIMAL else dot)
    return frame


def _infer_frame_number_format(
    frame: pd.DataFrame,
    delimiter: str,
    requested: str,
) -> str:
    """Infer one fallback convention from unambiguous tokens across a table."""
    if requested != AUTO_NUMBER_FORMAT:
        return requested
    evidence: set[str] = set()
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series.dtype):
            continue
        text = series.astype("string").str.strip()
        tokens = text[text.notna() & (text != "")]
        inferred = _infer_number_format(tokens)
        if inferred is not None:
            evidence.add(inferred)
    if len(evidence) == 1:
        return next(iter(evidence))
    # A comma field delimiter strongly implies point-decimal values. Otherwise
    # point decimal is the backward-compatible fallback for genuinely ambiguous
    # tokens such as 1.234; users can select comma decimal explicitly.
    return NUMBER_FORMAT_DOT_DECIMAL


def _resolved_number_format(
    tokens: pd.Series,
    *,
    delimiter: str,
    requested: str,
) -> str:
    """Resolve a requested or inferred convention for one token series."""
    validate_number_format(requested)
    if requested != AUTO_NUMBER_FORMAT:
        return requested
    return _infer_number_format(tokens) or NUMBER_FORMAT_DOT_DECIMAL


def _infer_number_format(tokens: pd.Series) -> str | None:
    """Infer decimal convention only when at least one token is unambiguous."""
    tokens = tokens.astype("string").str.strip()
    return _number_format_evidence(
        _localized_numeric_tokens(tokens, NUMBER_FORMAT_DOT_DECIMAL),
        _localized_numeric_tokens(tokens, NUMBER_FORMAT_COMMA_DECIMAL),
    )


def _parse_localized_number(value: str, number_format: str) -> float | None:
    """Parse one localized number, validating grouping before removing it."""
    token = value.strip()
    if not token:
        return None
    if number_format == NUMBER_FORMAT_COMMA_DECIMAL:
        if _COMMA_DECIMAL_NUMBER_PATTERN.fullmatch(token) is None:
            return None
        normalized = token
        for separator in "." + _GROUPING_SPACES:
            normalized = normalized.replace(separator, "")
        normalized = normalized.replace(",", ".")
    elif number_format == NUMBER_FORMAT_DOT_DECIMAL:
        if _DOT_DECIMAL_NUMBER_PATTERN.fullmatch(token) is None:
            return None
        normalized = token
        for separator in "," + _GROUPING_SPACES:
            normalized = normalized.replace(separator, "")
    else:
        return None
    try:
        result = float(normalized)
    except ValueError:
        return None
    return result if np.isfinite(result) else None


def _required_localized_number(value: str, number_format: str) -> float:
    """Parse one required number or raise a concise value error."""
    parsed = _parse_localized_number(str(value), number_format)
    if parsed is None:
        raise ValueError(f"Invalid localized number: {value!r}")
    return parsed


def _parse_metadata_line(line: str) -> tuple[str, str] | None:
    """Best-effort parse of common ``#``, ``$``, ``%`` and text records."""
    stripped = line.strip()
    if not stripped:
        return None
    content = stripped.lstrip("#$%").strip()
    if not content:
        return None
    for separator in ("=", "\t", ";", ":"):
        if separator not in content:
            continue
        key, value = content.split(separator, 1)
        if key.strip():
            return key.strip(), value.strip().strip("\t;")
    if stripped[0] in "#$%" and " " in content:
        key, value = content.split(None, 1)
        return key.strip(), value.strip()
    return None


def _validated_tabular_path(path: str | Path) -> Path:
    """Return a validated CSV/DAT/TXT path."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported file type '{file_path.suffix}'. Expected {supported}.")
    return file_path


def resolve_text_encoding(path: str | Path, requested: str = AUTO_ENCODING) -> str:
    """Return an explicit encoding after bounded, lossless text detection.

    UTF byte-order marks take priority. Without a mark, UTF-8 is attempted
    strictly before the common Windows-1252 instrument-export encoding and the
    byte-preserving Latin-1 fallback. No decoding errors are silently replaced.
    """
    file_path = _validated_tabular_path(path)
    normalized = str(requested or AUTO_ENCODING).strip().lower()
    if normalized not in SUPPORTED_TEXT_ENCODINGS:
        raise ValueError(f"Unsupported text encoding: {requested!r}.")
    if normalized != AUTO_ENCODING:
        return normalized

    with file_path.open("rb") as stream:
        sample = stream.read(_DELIMITER_SAMPLE_SIZE)
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    try:
        sample.decode("utf-8", errors="strict")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        sample.decode("cp1252", errors="strict")
        return "cp1252"
    except UnicodeDecodeError:
        return "latin-1"


def _read_delimited_sample(file_path: Path, encoding: str) -> str:
    """Read the bounded text sample shared by delimiter and structure inference."""
    try:
        with file_path.open("r", encoding=encoding, newline="") as stream:
            return stream.read(_DELIMITER_SAMPLE_SIZE)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Could not decode the file with the selected {encoding} encoding."
        ) from exc


def _sample_delimited_rows(
    sample: str,
    delimiter: str,
) -> list[tuple[int, tuple[str, ...]]]:
    """Parse nonblank physical sample lines while retaining zero-based line numbers."""
    rows: list[tuple[int, tuple[str, ...]]] = []
    for line_number, line in enumerate(sample.splitlines()[:250]):
        if not line.strip():
            continue
        if delimiter == " ":
            values = tuple(value.strip() for value in re.split(r"\s+", line.strip()))
        else:
            try:
                values = tuple(
                    value.strip()
                    for value in next(csv.reader([line], delimiter=delimiter))
                )
            except csv.Error:
                continue
        if values:
            rows.append((line_number, values))
    return rows


def _without_leading_comment_records(sample: str) -> str:
    """Remove leading ``#``/``$``/``%`` records for delimiter inference."""
    lines = sample.splitlines()
    start = _first_noncomment_line_number(sample)
    return "\n".join(lines[start:])


def _first_noncomment_line_number(sample: str) -> int:
    """Return the physical line where non-comment tabular content begins."""
    lines = sample.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "$", "%")):
            continue
        return index
    return 0


def _dominant_table_width(rows: list[tuple[int, tuple[str, ...]]]) -> int:
    """Return the most frequent row width, preferring wider layouts on ties."""
    counts = Counter(len(row) for _line, row in rows)
    return max(counts, key=lambda width: (counts[width], width))


def _first_stable_width_position(
    rows: list[tuple[int, tuple[str, ...]]],
    width: int,
) -> int:
    """Find the first row beginning a stable block with the dominant width."""
    for position, (_line, row) in enumerate(rows):
        if len(row) != width:
            continue
        following = rows[position : position + 3]
        matching = sum(len(candidate) == width for _line, candidate in following)
        if matching >= min(2, len(following)):
            return position
    return next(position for position, (_line, row) in enumerate(rows) if len(row) == width)


def _cell_kind(value: str) -> str:
    """Classify a sample token coarsely for header/preamble inference."""
    text = value.strip()
    if not text:
        return "blank"
    if (
        _parse_localized_number(text, NUMBER_FORMAT_DOT_DECIMAL) is not None
        or _parse_localized_number(text, NUMBER_FORMAT_COMMA_DECIMAL) is not None
    ):
        return "number"
    return "text"


def _row_signature(row: tuple[str, ...]) -> tuple[str, ...]:
    """Return the coarse value-kind signature for one parsed row."""
    return tuple(_cell_kind(value) for value in row)


def _infer_table_start_and_header(
    rows: list[tuple[int, tuple[str, ...]]],
    base_position: int,
    width: int,
    delimiter: str,
) -> tuple[int, bool]:
    """Infer where tabular data begins and whether its first row is a header."""
    for position in range(base_position, len(rows) - 1):
        _line, row = rows[position]
        if len(row) != width:
            continue
        signature = _row_signature(row)
        if "number" not in signature:
            continue
        following_signatures = [
            _row_signature(candidate)
            for _candidate_line, candidate in rows[position : position + 4]
            if len(candidate) == width
        ]
        if len(following_signatures) < 2:
            continue
        if sum(candidate == signature for candidate in following_signatures) < 2:
            continue
        previous_position = position - 1
        if previous_position >= base_position:
            _previous_line, previous = rows[previous_position]
            if len(previous) == width and all(
                kind in {"blank", "text"} for kind in _row_signature(previous)
            ):
                return previous_position, True
        return position, False

    return base_position, _infer_header_at_position(
        rows,
        base_position,
        width,
        delimiter,
    )


def _infer_header_at_position(
    rows: list[tuple[int, tuple[str, ...]]],
    position: int,
    width: int,
    delimiter: str,
) -> bool:
    """Infer header presence specifically at one chosen physical table start."""
    first_signature = _row_signature(rows[position][1])
    following = [
        candidate
        for _line, candidate in rows[position + 1 : position + 5]
        if len(candidate) == width
    ]
    if following:
        next_signatures = [_row_signature(candidate) for candidate in following]
        numeric_following = sum("number" in signature for signature in next_signatures)
        if "number" not in first_signature and numeric_following >= min(2, len(following)):
            return True
        if "number" in first_signature and numeric_following >= min(2, len(following)):
            return False

    sample_lines = []
    for _line, row in rows[position : position + 25]:
        if len(row) != width:
            continue
        output = StringIO()
        writer = csv.writer(output, delimiter=delimiter if delimiter != " " else " ")
        writer.writerow(row)
        sample_lines.append(output.getvalue().strip("\r\n"))
    has_header = True
    if len(sample_lines) >= 2:
        try:
            has_header = csv.Sniffer().has_header("\n".join(sample_lines))
        except csv.Error:
            has_header = True
    return has_header


def _build_read_csv_kwargs(
    options: ImportOptions,
    *,
    delimiter: str | None = None,
    has_header: bool | None = None,
    skip_rows: int | None = None,
) -> dict[str, object]:
    """Translate import dialog options into pandas read_csv keyword arguments."""
    resolved_header = options.has_header if has_header is None else has_header
    header = 0 if resolved_header else None
    resolved_delimiter = options.delimiter if delimiter is None else delimiter
    resolved_skip_rows = options.skip_rows if skip_rows is None else skip_rows

    if resolved_delimiter == " ":
        return {
            "sep": r"\s+",
            "header": header,
            "encoding": options.encoding,
            "engine": "python",
            "skiprows": max(int(resolved_skip_rows or 0), 0),
            "dtype": "string",
        }

    return {
        "sep": resolved_delimiter,
        "header": header,
        "encoding": options.encoding,
        "skiprows": max(int(resolved_skip_rows or 0), 0),
        "dtype": "string",
    }


def _validated_excel_path(path: str | Path) -> Path:
    """Return a validated modern Excel workbook path."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")
    if file_path.suffix.lower() not in SUPPORTED_EXCEL_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXCEL_EXTENSIONS))
        raise ValueError(
            f"Unsupported Excel file type '{file_path.suffix}'. Expected {supported}. "
            "Save legacy .xls files as .xlsx before importing."
        )
    return file_path


def _read_xml_member(archive: ZipFile, name: str) -> ElementTree.Element:
    """Read a required OOXML member and return its root element."""
    try:
        with archive.open(name) as stream:
            return ElementTree.parse(stream).getroot()
    except KeyError as exc:
        raise ValueError(f"Workbook package is missing required member '{name}'.") from exc
    except ElementTree.ParseError as exc:
        raise ValueError(f"Workbook member '{name}' contains invalid XML.") from exc


def _workbook_relationships(
    relationship_root: ElementTree.Element,
) -> dict[str, tuple[str, str]]:
    """Map workbook relationship IDs to normalized package targets and types."""
    relationships: dict[str, tuple[str, str]] = {}
    for relationship in relationship_root.iter():
        if _xml_local_name(relationship.tag) != "Relationship":
            continue
        relationship_id = relationship.attrib.get("Id", "")
        target = relationship.attrib.get("Target", "").replace("\\", "/")
        relationship_type = relationship.attrib.get("Type", "")
        if not relationship_id or not target:
            continue
        if target.startswith("/"):
            normalized_target = target.lstrip("/")
        else:
            normalized_target = posixpath.normpath(posixpath.join("xl", target))
        relationships[relationship_id] = (normalized_target, relationship_type)
    return relationships


def _inspect_excel_sheets(
    archive: ZipFile,
    workbook_root: ElementTree.Element,
    relationships: dict[str, tuple[str, str]],
) -> list[ExcelSheetInfo]:
    """Build ordered tab information from workbook.xml and its relationships."""
    sheets: list[ExcelSheetInfo] = []
    for sheet in workbook_root.iter():
        if _xml_local_name(sheet.tag) != "sheet":
            continue
        name = str(sheet.attrib.get("name", "")).strip() or "Unnamed Sheet"
        state = str(sheet.attrib.get("state", "visible") or "visible")
        relationship_id = next(
            (
                value
                for key, value in sheet.attrib.items()
                if _xml_local_name(key) == "id"
            ),
            "",
        )
        target, relationship_type = relationships.get(relationship_id, ("", ""))
        if relationship_type.endswith("/worksheet"):
            sheet_type = "worksheet"
            used_range = _worksheet_used_range(archive, target)
        elif relationship_type.endswith("/chartsheet"):
            sheet_type = "chart sheet"
            used_range = "Not applicable"
        else:
            sheet_type = "unsupported tab"
            used_range = "Not applicable"
        sheets.append(
            ExcelSheetInfo(
                name=name,
                state=state,
                sheet_type=sheet_type,
                used_range=used_range,
            )
        )
    return sheets


def _worksheet_used_range(archive: ZipFile, target: str) -> str:
    """Read the early worksheet dimension marker without loading sheet cells."""
    if not target:
        return "Unknown"
    try:
        with archive.open(target) as stream:
            prefix = stream.read(128 * 1024)
    except KeyError:
        return "Unknown"
    match = _DIMENSION_PATTERN.search(prefix)
    if match is None:
        return "Unknown"
    return match.group(1).decode("utf-8", errors="replace")


def _excel_package_warnings(
    file_path: Path,
    names: tuple[str, ...],
    workbook_root: ElementTree.Element,
    sheets: list[ExcelSheetInfo],
) -> list[str]:
    """Describe workbook objects that a values-only import will not reproduce."""
    warnings: list[str] = [
        "Only cached worksheet cell values are imported. Formulas are not recalculated; "
        "a formula without a saved cached result may import as blank.",
        "Cell formatting, conditional formatting, validation, protection, merged-cell layout, "
        "print settings, and row/column display settings are not reproduced.",
    ]

    feature_rules = (
        ("xl/charts/", "chart definition(s)", "Charts are ignored; their source cells can still be imported."),
        ("xl/pivotTables/", "pivot table definition(s)", "Pivot layouts/caches are ignored; only displayed source or result cells are imported."),
        ("xl/tables/", "Excel table definition(s)", "Table styling, filters, totals, and structured references are ignored."),
        ("xl/media/", "embedded image/media item(s)", "Embedded images and media are ignored."),
        ("xl/externalLinks/", "external link definition(s)", "External links are not refreshed."),
        ("xl/queryTables/", "query table definition(s)", "Queries are not refreshed or imported as connections."),
        ("xl/comments", "comment/note part(s)", "Cell comments and notes are ignored."),
        ("xl/slicers/", "slicer definition(s)", "Slicers and interactive controls are ignored."),
    )
    for prefix, label, explanation in feature_rules:
        count = sum(1 for name in names if name.startswith(prefix))
        if count:
            warnings.append(f"Detected {count} {label}. {explanation}")

    if "xl/connections.xml" in names:
        warnings.append("Detected workbook data connections. Connections are not executed or refreshed.")
    if "xl/vbaProject.bin" in names or file_path.suffix.lower() == ".xlsm":
        warnings.append("This is a macro-enabled workbook. VBA macros are never executed or imported.")

    defined_names = next(
        (
            element
            for element in workbook_root.iter()
            if _xml_local_name(element.tag) == "definedNames"
        ),
        None,
    )
    if defined_names is not None and len(defined_names):
        warnings.append(
            f"Detected {len(defined_names)} named range/formula definition(s). "
            "Names are ignored; their worksheet cell values remain available."
        )

    chart_tabs = sum(1 for sheet in sheets if sheet.sheet_type == "chart sheet")
    if chart_tabs:
        warnings.append(
            f"Detected {chart_tabs} chart-only tab(s). They contain no data grid and cannot be selected."
        )
    hidden_tabs = sum(1 for sheet in sheets if sheet.state != "visible" and sheet.is_importable)
    if hidden_tabs:
        warnings.append(
            f"Detected {hidden_tabs} hidden worksheet tab(s). They are listed but not selected by default."
        )
    return warnings


def _xml_local_name(name: str) -> str:
    """Return an XML tag or attribute name without its namespace."""
    return name.rsplit("}", 1)[-1]


def _normalized_excel_headers(columns: pd.Index) -> list[str]:
    """Return stable string headers, filling blanks and de-duplicating names."""
    normalized: list[str] = []
    counts: dict[str, int] = {}
    for index, value in enumerate(columns):
        if (
            value is None
            or (isinstance(value, str) and value.startswith("Unnamed:"))
            or (not isinstance(value, str) and pd.isna(value))
        ):
            base = f"Column {index + 1}"
        else:
            base = str(value).strip() or f"Column {index + 1}"
        count = counts.get(base, 0) + 1
        counts[base] = count
        normalized.append(base if count == 1 else f"{base} ({count})")
    return normalized
