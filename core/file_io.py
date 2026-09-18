"""Tabular data import helpers for delimited files and Excel workbooks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import posixpath
import re
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

import pandas as pd


SUPPORTED_EXTENSIONS = {".csv", ".txt"}
SUPPORTED_EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}

_DIMENSION_PATTERN = re.compile(rb"<(?:[A-Za-z0-9_]+:)?dimension\b[^>]*\bref=\"([^\"]+)\"")


@dataclass(frozen=True, slots=True)
class ImportOptions:
    """User-selected parser options for delimited text files."""

    delimiter: str = ","
    has_header: bool = True
    encoding: str = "utf-8"


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
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported file type '{file_path.suffix}'. Expected {supported}.")

    read_kwargs = _build_read_csv_kwargs(options)

    try:
        frame = pd.read_csv(file_path, **read_kwargs)
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Could not decode the file as UTF-8. Save it as UTF-8 or add encoding selection later."
        ) from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"Could not parse the file with the selected delimiter: {exc}") from exc

    if frame.empty:
        raise ValueError("The selected file did not contain any rows.")

    if not options.has_header:
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


def _build_read_csv_kwargs(options: ImportOptions) -> dict[str, object]:
    """Translate import dialog options into pandas read_csv keyword arguments."""
    header = 0 if options.has_header else None

    if options.delimiter == " ":
        return {
            "sep": r"\s+",
            "header": header,
            "encoding": options.encoding,
            "engine": "python",
        }

    return {
        "sep": options.delimiter,
        "header": header,
        "encoding": options.encoding,
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
