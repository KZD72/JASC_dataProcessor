"""Disk-backed, immutable tables; no complete source DataFrame is retained."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import BinaryIO

import pandas as pd
import polars as pl

from core.file_io import ImportOptions, inspect_delimited_file, read_leading_metadata
from core.jobs import JobContext

DISPLAY_ROWS = 1_000
DISPLAY_COLUMNS = 32
DISPLAY_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TablePage:
    """One bounded window, with zero-based positions in the complete source."""

    row_start: int
    column_start: int
    frame: pl.DataFrame


@dataclass(slots=True)
class LargeDataset:
    """Own a private Parquet snapshot independent of the original file."""

    name: str
    path: Path
    row_count: int
    columns: tuple[str, ...]
    source_path: str = ""
    details: dict[str, object] = field(default_factory=dict)
    _storage: tempfile.TemporaryDirectory | None = field(repr=False, default=None)

    def __del__(self) -> None:
        # Ownership is shared by the workspace and any in-flight reader. The
        # final owner removes the private snapshot only after readers release it.
        storage = getattr(self, "_storage", None)
        if storage is not None:
            storage.cleanup()

    def scan(self) -> pl.LazyFrame:
        """Return a lazy source for full-dataset operations, never a display page."""
        return pl.scan_parquet(self.path, cache=False, low_memory=True, parallel="none")

    def read_page(
        self, row_start: int, column_start: int = 0, *,
        context: JobContext | None = None,
        max_bytes: int = DISPLAY_BYTES,
    ) -> TablePage:
        """Project columns and push a bounded row slice into the Parquet scan.

        Shrink and re-read oversized windows rather than retaining a slice of
        their backing buffers. Decoder/in-flight memory is separate from this
        display-cache budget; one pathological cell can still be too large.
        """
        if row_start < 0 or row_start > self.row_count:
            raise ValueError("Row is outside the dataset.")
        if column_start < 0 or column_start >= len(self.columns):
            raise ValueError("Column is outside the dataset.")
        if max_bytes < 1:
            raise ValueError("The page memory budget must be positive.")
        columns = self.columns[column_start:column_start + DISPLAY_COLUMNS]
        count = min(DISPLAY_ROWS, self.row_count - row_start)
        while True:
            if context:
                context.check_cancelled()
            frame = self.scan().select(columns).slice(row_start, count).collect(engine="streaming")
            if context:
                context.check_cancelled()
            if frame.estimated_size() <= max_bytes:
                return TablePage(row_start, column_start, frame)
            del frame
            if count <= 1:
                raise ValueError("One row exceeds the display memory budget. Select fewer/smaller columns.")
            count = max(1, count // 2)

    def materialize_page(self, page: TablePage) -> pd.DataFrame:
        """Explicitly copy only a displayed window; never use PyArrow/full collect."""
        if page.frame.height > DISPLAY_ROWS or page.frame.width > DISPLAY_COLUMNS:
            raise ValueError("The selected window exceeds the worksheet extraction limit.")
        return pd.DataFrame(page.frame.to_dict(as_series=False))


def _copy_stream(source: BinaryIO, target: BinaryIO, context: JobContext | None) -> None:
    """Copy disk/archive data in bounded blocks with cooperative cancellation."""
    while True:
        if context:
            context.check_cancelled()
        block = source.read(1024 * 1024)
        if not block:
            break
        target.write(block)


def restore_large_dataset(
    source: BinaryIO, name: str, *, source_path: str = "",
    details: dict[str, object] | None = None, context: JobContext | None = None,
) -> LargeDataset:
    """Restore a private snapshot from an archive member without whole-file reads."""
    storage = tempfile.TemporaryDirectory(prefix="jasc-large-")
    try:
        path = Path(storage.name) / "table.parquet"
        with path.open("wb") as target:
            _copy_stream(source, target, context)
        return _describe(name, path, storage, source_path, details or {})
    except BaseException:
        storage.cleanup()
        raise


def _describe(
    name: str, path: Path, storage: tempfile.TemporaryDirectory,
    source_path: str, details: dict[str, object],
) -> LargeDataset:
    scan = pl.scan_parquet(path, cache=False, low_memory=True)
    columns = tuple(scan.collect_schema().names())
    if not columns:
        raise ValueError("The source has no columns.")
    rows = int(scan.select(pl.len()).collect(engine="streaming").item())
    return LargeDataset(name, path, rows, columns, source_path, details, storage)


def open_large_dataset(
    path: str | Path, options: ImportOptions, context: JobContext,
) -> LargeDataset:
    """Stream a regular text table to Parquet, or snapshot an existing Parquet.

    Text columns are deliberately stored losslessly as strings: bounded-sample
    numeric inference must not change late tokens, locale values, or IDs.
    Vendor-specific layouts continue through the ordinary import workflow.
    Native streaming phases cancel at their completion boundary.
    """
    source = Path(path)
    context.check_cancelled()
    if source.suffix.lower() == ".parquet":
        context.report(0, 0, f"Copying {source.name}")
        with source.open("rb") as stream:
            result = restore_large_dataset(stream, source.stem, source_path=str(source), context=context)
        context.check_cancelled()
        return result
    if source.suffix.lower() not in {".csv", ".dat", ".txt"}:
        raise ValueError("Large-data mode supports CSV, DAT, TXT, and Parquet files.")
    inspection = inspect_delimited_file(
        source, delimiter=options.delimiter, encoding=options.encoding,
        skip_rows=options.skip_rows, data_kind=options.data_kind,
        spectrometer=options.spectrometer,
    )
    if inspection.format_name != "delimited" or options.data_kind == "spectral_map":
        raise ValueError("Use ordinary Import Data for vendor-specific spectra/maps. Large-data mode currently opens regular tables.")
    if inspection.delimiter == " ":
        raise ValueError("Large-data mode currently requires a comma, tab, semicolon, or pipe separator; use ordinary Import Data for whitespace tables.")
    storage = tempfile.TemporaryDirectory(prefix="jasc-large-")
    try:
        root = Path(storage.name)
        # Strict incremental transcoding supports the existing ANSI/UTF-16
        # choices without asking Polars to decode the entire source eagerly.
        context.report(0, 0, f"Preparing encoding: {source.name}")
        transcoded = root / "source.csv"
        with source.open("r", encoding=inspection.encoding, newline="") as raw:
            with transcoded.open("w", encoding="utf-8", newline="") as target:
                while True:
                    context.check_cancelled()
                    block = raw.read(256 * 1024)
                    if not block:
                        break
                    target.write(block)
        header = inspection.has_header if options.has_header is None else options.has_header
        skip = inspection.metadata_rows if options.skip_rows is None else options.skip_rows
        context.report(0, 0, f"Writing disk-backed table: {source.name}")
        scan = pl.scan_csv(
            transcoded, separator=inspection.delimiter, has_header=header,
            skip_lines=skip, infer_schema=False, low_memory=True,
            raise_if_empty=True,
        )
        output = root / "table.parquet"
        scan.sink_parquet(output, row_group_size=16_384, maintain_order=True, engine="streaming")
        context.check_cancelled()
        transcoded.unlink()
        preamble = read_leading_metadata(source, inspection.metadata_rows, encoding=inspection.encoding)
        details = {
            "encoding": inspection.encoding, "delimiter": inspection.delimiter,
            "has_header": bool(header), "skip_rows": skip,
            "number_format": options.number_format, "text_storage": True,
            "preamble": list(preamble.raw_lines),
        }
        return _describe(source.stem, output, storage, str(source), details)
    except BaseException:
        storage.cleanup()
        raise
