"""Detached text-import preparation; workers never access a live workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.file_io import (
    DelimitedFileInspection, ImportOptions, inspect_delimited_file,
    read_leading_metadata, read_tabular_file,
)
from core.jobs import JobCancelled, JobContext
from core.workspace import WorksheetMetadata


@dataclass(slots=True)
class PreparedTextFile:
    path: Path
    frame: pd.DataFrame
    metadata: WorksheetMetadata
    inspection: DelimitedFileInspection


@dataclass(slots=True)
class PreparedTextBatch:
    files: list[PreparedTextFile]
    errors: list[str]


def inspect_text_files(
    context: JobContext, paths: list[Path], options: ImportOptions | None = None,
) -> list[DelimitedFileInspection]:
    """Inspect a batch off the UI thread with all-or-nothing preflight."""
    inspections, errors = [], []
    for index, path in enumerate(paths):
        context.report(index, len(paths), f"Inspecting {path.name}")
        try:
            if options is None:
                inspections.append(inspect_delimited_file(path))
            else:
                inspections.append(inspect_delimited_file(
                    path, delimiter=options.delimiter, encoding=options.encoding,
                    skip_rows=options.skip_rows, data_kind=options.data_kind,
                    spectrometer=options.spectrometer,
                ))
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    context.check_cancelled()
    if errors:
        raise ValueError("One or more files could not be inspected:\n\n" + "\n".join(errors))
    return inspections


def _worksheet_metadata(
    path: Path, inspection: DelimitedFileInspection, options: ImportOptions, frame: pd.DataFrame,
) -> WorksheetMetadata:
    """Keep exact preambles and the established import provenance contract."""
    preamble = read_leading_metadata(path, inspection.metadata_rows, encoding=inspection.encoding)
    metadata = WorksheetMetadata(
        fields=list(preamble.fields),
        raw_lines=list(preamble.raw_lines),
        import_details={
            "Requested data type": {
                "auto": "Auto",
                "table": "General table",
                "spectrum": "Single spectrum",
                "spectral_map": "Spectroscopy map",
            }.get(options.data_kind, options.data_kind),
            "Spectrometer profile": {
                "auto": "Auto / generic",
                "horiba": "Horiba LabSpec",
                "bwtek": "B&W Tek",
            }.get(options.spectrometer, options.spectrometer),
            "Number format": {
                "auto": "Auto",
                "dot_decimal": "Decimal point (1,234.56)",
                "comma_decimal": "Decimal comma (1.234,56)",
            }.get(options.number_format, options.number_format),
            "Format": (
                "Bruker IR text export"
                if inspection.format_name == "bruker_ir"
                else (
                    "Spectral map matrix"
                    if inspection.format_name == "spectral_map_matrix"
                    else "Delimited text"
                )
            ),
            "Delimiter": inspection.delimiter_label,
            "Header": "Present" if inspection.has_header else "Not present",
            "Encoding": inspection.encoding,
            "Leading metadata rows": str(inspection.metadata_rows),
        },
    )
    if inspection.format_name == "spectral_map_matrix":
        spectral_columns = list(inspection.spectral_axis)
        pixel_count = (
            len(frame) // len(spectral_columns)
            if spectral_columns
            else 0
        )
        metadata.import_details.update({
            "Source layout": "Wide matrix: one spatial pixel per row",
            "Worksheet layout": "Long form: X, Y, Raman Shift, Intensity",
            "Spatial coordinate columns": "X, Y",
            "Spatial pixels": str(pixel_count),
            "Raman shifts per pixel": str(len(spectral_columns)),
            "Spectral axis unit": "cm^-1",
        })
        if spectral_columns:
            metadata.import_details["Spectral axis range"] = (
                f"{spectral_columns[0]} to {spectral_columns[-1]} cm^-1"
            )
    return metadata


def prepare_text_files(
    context: JobContext, paths: list[Path], inspections: list[DelimitedFileInspection],
    options: ImportOptions, pattern_choice: str,
) -> PreparedTextBatch:
    """Stage parsed frames and metadata; cancellation discards the whole batch."""
    files, errors = [], []
    for index, (path, inspection) in enumerate(zip(paths, inspections, strict=True)):
        context.report(index, len(paths), f"Preparing {path.name} ({index + 1}/{len(paths)})")
        file_options = ImportOptions(
            delimiter=options.delimiter, has_header=options.has_header,
            encoding=inspection.encoding, skip_rows=options.skip_rows,
            data_kind=options.data_kind, spectrometer=options.spectrometer,
            number_format=options.number_format,
        )
        if pattern_choice == "generic":
            metadata_rows = inspection.metadata_rows if options.skip_rows is None else options.skip_rows
            file_options = ImportOptions(
                delimiter=inspection.delimiter, has_header=False, encoding=inspection.encoding,
                skip_rows=metadata_rows + int(inspection.has_header),
                data_kind=options.data_kind, spectrometer=options.spectrometer,
                number_format=options.number_format,
            )
        try:
            frame = read_tabular_file(path, file_options, context=context)
            context.report(0, 0, f"Reading metadata: {path.name}")
            metadata = _worksheet_metadata(path, inspection, options, frame)
            context.check_cancelled()
            files.append(PreparedTextFile(path, frame, metadata, inspection))
        except JobCancelled:
            raise
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    context.check_cancelled()
    return PreparedTextBatch(files, errors)
