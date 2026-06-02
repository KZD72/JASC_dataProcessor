"""Dataset backend metadata and large-data profiling helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


PANDAS_BACKEND = "pandas"
DUCKDB_BACKEND = "duckdb"
KNOWN_BACKENDS = {PANDAS_BACKEND, DUCKDB_BACKEND}

LARGE_FILE_WARNING_BYTES = 100 * 1024 * 1024
LARGE_DATASET_WARNING_CELLS = 2_000_000
LARGE_DATASET_WARNING_MEMORY_BYTES = 250 * 1024 * 1024
AUTO_RESIZE_CELL_LIMIT = 250_000
DEFAULT_LARGE_DATASET_COLUMN_WIDTH = 120


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """Lightweight size and backend profile for one worksheet-like dataset."""

    name: str
    backend: str
    row_count: int
    column_count: int
    memory_bytes: int = 0
    file_size_bytes: int | None = None

    @property
    def cell_count(self) -> int:
        """Return the total number of table cells represented by the profile."""
        return self.row_count * self.column_count

    @property
    def is_large(self) -> bool:
        """Return whether the dataset should trigger a large-data warning."""
        return (
            self.cell_count >= LARGE_DATASET_WARNING_CELLS
            or self.memory_bytes >= LARGE_DATASET_WARNING_MEMORY_BYTES
        )

    @property
    def should_skip_full_auto_resize(self) -> bool:
        """Return whether Qt should avoid full column auto-sizing."""
        return self.cell_count > AUTO_RESIZE_CELL_LIMIT

    def dimensions_text(self) -> str:
        """Return compact row/column/cell dimensions for dialogs."""
        return (
            f"{self.row_count:,} rows x {self.column_count:,} columns "
            f"({self.cell_count:,} cells)"
        )


def profile_dataframe(frame: pd.DataFrame, name: str = "", backend: str = PANDAS_BACKEND) -> DatasetProfile:
    """Return a profile for an in-memory pandas DataFrame."""
    row_count, column_count = frame.shape
    return DatasetProfile(
        name=name,
        backend=backend,
        row_count=int(row_count),
        column_count=int(column_count),
        memory_bytes=dataframe_memory_bytes(frame),
    )


def dataframe_memory_bytes(frame: pd.DataFrame) -> int:
    """Return a fast DataFrame memory estimate in bytes."""
    try:
        return int(frame.memory_usage(index=True, deep=False).sum())
    except Exception:
        return 0


def file_size_bytes(path: str | Path) -> int:
    """Return a file size in bytes, or zero when it cannot be read."""
    try:
        return int(Path(path).stat().st_size)
    except OSError:
        return 0


def should_warn_for_large_file(path: str | Path) -> bool:
    """Return whether a file should trigger a pre-import size warning."""
    return file_size_bytes(path) >= LARGE_FILE_WARNING_BYTES


def normalize_backend(backend: object) -> str:
    """Return a supported backend label, defaulting to Pandas."""
    clean_backend = str(backend or PANDAS_BACKEND).strip().lower()
    return clean_backend if clean_backend in KNOWN_BACKENDS else PANDAS_BACKEND


def format_bytes(byte_count: int) -> str:
    """Format a byte count for user-facing warning dialogs."""
    value = float(max(byte_count, 0))
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024.0 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} GiB"
