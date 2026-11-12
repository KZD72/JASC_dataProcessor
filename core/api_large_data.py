"""Explicit disk-backed imports and bounded worksheet extraction for macros."""
from __future__ import annotations
from threading import Event
from pathlib import Path

import pandas as pd

from core.file_io import ImportOptions
from core.jobs import JobContext
from core.large_data import LargeDataset, DISPLAY_ROWS, DISPLAY_COLUMNS, DISPLAY_BYTES, open_large_dataset
from core.workspace import Dataset, Workspace


class LargeDataApi:
    workspace: Workspace

    def load_large(self, path: str | Path, **options: object) -> LargeDataset:
        result = open_large_dataset(path, ImportOptions(**options), JobContext(Event(), lambda _: None))
        return self.workspace.add_large_dataset(result)

    def large_sheet(self, name: str) -> LargeDataset:
        return self.workspace.get_large_dataset(name)

    def delete_large(self, source: LargeDataset) -> None:
        self.workspace.remove_large_dataset(source.name)

    def extract_window(self, source: LargeDataset, *, name: str, row_start: int, row_count: int,
                       column_start: int, column_count: int) -> Dataset:
        if not (0 <= row_start <= source.row_count and 0 <= row_count <= DISPLAY_ROWS and
                0 <= column_start < len(source.columns) and 0 < column_count <= DISPLAY_COLUMNS):
            raise ValueError("The requested window is outside the worksheet extraction limits.")
        if row_start+row_count > source.row_count or column_start+column_count > len(source.columns):
            raise ValueError("The replay source does not contain the complete recorded window.")
        columns = list(source.columns[column_start:column_start+column_count])
        bounded = source.scan().select(columns).slice(row_start, row_count).collect(engine="streaming")
        if bounded.estimated_size() > DISPLAY_BYTES:
            raise ValueError("The replayed window exceeds the worksheet extraction memory budget.")
        frame = pd.DataFrame(bounded.to_dict(as_series=False))
        output = self.workspace.add_dataset(name, frame, source_path=source.source_path, copy_frame=False)
        output.worksheet_metadata.import_details = {
            "Large source": source.name,
            "Source rows (1-based)": f"{row_start+1}-{row_start+len(frame)}",
            "Source columns (1-based)": f"{column_start+1}-{column_start+len(frame.columns)}",
            "Scope": "Explicit display-window extraction; not the complete source",
        }
        return output
