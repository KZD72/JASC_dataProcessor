"""Tabular data import helpers for delimited files and Excel workbooks."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import posixpath
import re
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

import pandas as pd


SUPPORTED_EXTENSIONS = {".csv", ".dat", ".txt"}
SUPPORTED_EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
AUTO_DELIMITER = "auto"
_INFERRED_DELIMITER_CANDIDATES = ",;\t| "
_DELIMITER_SAMPLE_SIZE = 128 * 1024

_DIMENSION_PATTERN = re.compile(rb"<(?:[A-Za-z0-9_]+:)?dimension\b[^>]*\bref=\"([^\"]+)\"")


@dataclass(frozen=True, slots=True)
class ImportOptions:
    """User-selected parser options for delimited text files."""

    delimiter: str = AUTO_DELIMITER
    has_header: bool | None = None
    encoding: str = "utf-8"
    skip_rows: int | None = None


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


def read_tabular_file(path: str | Path, options: ImportOptions) -> pd.DataFrame:
    """Read a CSV/TXT file into a DataFrame using the selected import options."""
    file_path = _validated_tabular_path(path)
    inspection: DelimitedFileInspection | None = None
    if (
        options.delimiter == AUTO_DELIMITER
        or options.has_header is None
        or options.skip_rows is None
    ):
        inspection = inspect_delimited_file(
            file_path,
            delimiter=options.delimiter,
            encoding=options.encoding,
            skip_rows=options.skip_rows,
        )
    delimiter = inspection.delimiter if inspection is not None else options.delimiter
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
    read_kwargs = _build_read_csv_kwargs(
        options,
        delimiter=delimiter,
        has_header=has_header,
        skip_rows=skip_rows,
    )

    try:
        frame = pd.read_csv(file_path, **read_kwargs)
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Could not decode the file as UTF-8. Save it as UTF-8 or add encoding selection later."
        ) from exc
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        source = "inferred" if options.delimiter == AUTO_DELIMITER else "selected"
        raise ValueError(f"Could not parse the file with the {source} delimiter: {exc}") from exc

    if frame.empty:
        raise ValueError("The selected file did not contain any rows.")

    if not has_header:
        frame.columns = [f"Column {index + 1}" for index in range(len(frame.columns))]

    return frame


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
    encoding: str = "utf-8",
) -> str:
    """Infer a common delimiter from a bounded text sample.

    Files without delimiter evidence are intentionally treated as comma-separated;
    pandas will then read them as a valid single-column table. Restricting Sniffer's
    candidate set prevents letters or digits in single-column data being mistaken
    for separators.
    """
    file_path = Path(path)
    sample = _read_delimited_sample(file_path, encoding)

    if not sample.strip():
        return ","
    try:
        dialect = csv.Sniffer().sniff(
            sample,
            delimiters=_INFERRED_DELIMITER_CANDIDATES,
        )
    except csv.Error:
        lines = [line.strip() for line in sample.splitlines() if line.strip()]
        whitespace_widths = [len(re.split(r"\s+", line)) for line in lines]
        if (
            len(whitespace_widths) >= 2
            and whitespace_widths[0] > 1
            and len(set(whitespace_widths)) == 1
        ):
            return " "
        return ","
    return str(dialect.delimiter)


def inspect_delimited_file(
    path: str | Path,
    *,
    delimiter: str = AUTO_DELIMITER,
    encoding: str = "utf-8",
    skip_rows: int | None = None,
) -> DelimitedFileInspection:
    """Infer separator, leading metadata rows, header presence, and a short preview."""
    file_path = _validated_tabular_path(path)
    sample = _read_delimited_sample(file_path, encoding)
    if not sample.strip():
        raise ValueError("The selected file did not contain any rows.")
    resolved_delimiter = (
        infer_tabular_delimiter(file_path, encoding)
        if delimiter == AUTO_DELIMITER
        else delimiter
    )
    parsed_rows = _sample_delimited_rows(sample, resolved_delimiter)
    if not parsed_rows:
        raise ValueError("The selected file did not contain any readable rows.")

    if skip_rows is None:
        table_width = _dominant_table_width(parsed_rows)
        base_position = _first_stable_width_position(parsed_rows, table_width)
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
    )


def _validated_tabular_path(path: str | Path) -> Path:
    """Return a validated CSV/DAT/TXT path."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported file type '{file_path.suffix}'. Expected {supported}.")
    return file_path


def _read_delimited_sample(file_path: Path, encoding: str) -> str:
    """Read the bounded text sample shared by delimiter and structure inference."""
    try:
        with file_path.open("r", encoding=encoding, newline="") as stream:
            return stream.read(_DELIMITER_SAMPLE_SIZE)
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Could not decode the file as UTF-8. Save it as UTF-8 or add encoding selection later."
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
    normalized = text.replace(",", ".")
    try:
        float(normalized)
    except ValueError:
        return "text"
    return "number"


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
        }

    return {
        "sep": resolved_delimiter,
        "header": header,
        "encoding": options.encoding,
        "skiprows": max(int(resolved_skip_rows or 0), 0),
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
