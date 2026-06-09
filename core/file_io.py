"""Tabular data import helpers for CSV and text files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


SUPPORTED_EXTENSIONS = {".csv", ".txt"}


@dataclass(frozen=True, slots=True)
class ImportOptions:
    """User-selected parser options for delimited text files."""

    delimiter: str = ","
    has_header: bool = True
    encoding: str = "utf-8"


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
