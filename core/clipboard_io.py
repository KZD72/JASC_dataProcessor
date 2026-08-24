"""Efficient parsing helpers for spreadsheet-style clipboard blocks."""

from __future__ import annotations

import csv
from io import StringIO

import pandas as pd


def parse_tabular_clipboard(
    text: str,
    text_columns: set[int] | None = None,
    *,
    preserve_all_text: bool = False,
) -> pd.DataFrame:
    """Parse tab-delimited clipboard text into a rectangular DataFrame.

    The fast pandas parser handles normal rectangular spreadsheet data. A CSV
    fallback preserves unusually ragged rows that the fast parser rejects.
    ``text_columns`` identifies zero-based clipboard columns whose tokens must
    remain text, for example when pasting into a Text/object worksheet column.
    ``preserve_all_text`` is used by the legacy manual-entry grid, whose cells
    do not have destination dtypes.
    """
    if not text or not any(character not in "\r\n" for character in text):
        return pd.DataFrame()

    dtype: object = str if preserve_all_text else {
        column: str for column in sorted(text_columns or ())
    }
    try:
        return pd.read_csv(
            StringIO(text),
            sep="\t",
            header=None,
            dtype=dtype or None,
            keep_default_na=False,
            na_filter=False,
            skip_blank_lines=False,
            engine="c",
        )
    except (pd.errors.EmptyDataError, pd.errors.ParserError, ValueError):
        return _parse_ragged_clipboard(text)


def _parse_ragged_clipboard(text: str) -> pd.DataFrame:
    """Parse a ragged clipboard block while padding absent trailing cells."""
    rows = list(csv.reader(StringIO(text.rstrip("\r\n")), delimiter="\t"))
    column_count = max((len(row) for row in rows), default=0)
    if column_count == 0:
        return pd.DataFrame()
    padded_rows = [row + [""] * (column_count - len(row)) for row in rows]
    return pd.DataFrame(padded_rows, dtype="object")
