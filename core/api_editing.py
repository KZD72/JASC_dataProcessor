"""Serializable worksheet commands and outermost-only model operation events."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, date
from enum import Enum
from functools import wraps
import inspect
from typing import Callable, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from core.workspace import Dataset, Workspace
    from ui.dataframe_model import DataFrameTableModel


EDIT_METHODS = frozenset({"setData", "undo", "redo", "delete_rows", "clear_cells", "resize_sheet",
    "add_row", "insert_row", "paste_block", "insert_columns", "delete_columns", "add_empty_column",
    "insert_empty_column", "fill_range", "smart_fill_selection", "set_column_metadata", "apply_column_metadata"})


def encode_value(value: object) -> object:
    if value is pd.NA or value is pd.NaT:
        return {"__missing__": True}
    if isinstance(value, pd.DataFrame):
        return {"__frame__": encode_value(value.to_dict(orient="split"))}
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return {"__timestamp__": value.isoformat()}
    if is_dataclass(value):
        return {"__metadata__": asdict(value)}
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "isValid") and hasattr(value, "row"):
        return {"__index__": [value.row(), value.column()]}
    if isinstance(value, dict):
        return {key: encode_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_value(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def decode_value(value: object, model: object) -> object:
    if isinstance(value, list):
        return [decode_value(item, model) for item in value]
    if isinstance(value, dict):
        if "__missing__" in value:
            return pd.NA
        if "__timestamp__" in value:
            return pd.Timestamp(value["__timestamp__"])
        if "__index__" in value:
            return model.index(*value["__index__"])
        if "__metadata__" in value:
            from core.workspace import ColumnMetadata
            return ColumnMetadata.from_metadata(value["__metadata__"])
        if "__frame__" in value:
            return pd.DataFrame(**decode_value(value["__frame__"], model))
        return {key: decode_value(item, model) for key, item in value.items()}
    return value


def record_edit(function: Callable) -> Callable:
    """Report a completed public mutation once, including nested convenience calls."""
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        outer = getattr(self, "_operation_depth", 0) == 0
        dataset = self.dataset
        interested = outer and dataset is not None and getattr(self, "_record_api_edits", False)
        # Signals are cheap when no recorder is attached; avoid copying payloads
        # until an operation has succeeded and somebody is listening.
        if outer and dataset is not None:
            self.operation_started.emit(dataset)
        self._operation_depth = getattr(self, "_operation_depth", 0)+1
        success = False
        try:
            result = function(self, *args, **kwargs)
            success = result is not False
            return result
        finally:
            self._operation_depth -= 1
            if outer and dataset is not None:
                payload = {}
                if interested and success:
                    payload = dict(signature.bind(self, *args, **kwargs).arguments)
                    payload.pop("self", None)
                    payload = encode_value(payload)
                self.operation_finished.emit(dataset, function.__name__, payload, success)
    return wrapped


def record_undo(function: Callable) -> Callable:
    @wraps(function)
    def wrapped(self, sheet, *args, **kwargs):
        model = self._editor(sheet)
        model.capture_undo_state()
        try:
            return function(self, sheet, *args, **kwargs)
        except Exception:
            model.discard_latest_undo_state()
            raise
    return wrapped


class WorksheetApi:
    workspace: Workspace

    def _editor(self, sheet: Dataset) -> DataFrameTableModel:
        from ui.dataframe_model import DataFrameTableModel
        editors = self.__dict__.setdefault("_editors", {})
        if id(sheet) not in editors:
            model = DataFrameTableModel()
            model.set_dataset(sheet)
            workspace = self.workspace
            model.columns_renamed.connect(lambda changes: workspace.rename_column_references_in_plots(sheet.name, changes))
            editors[id(sheet)] = model
        return editors[id(sheet)]

    def edit(self, sheet: Dataset, *, operation: str, parameters: dict[str, object]) -> object:
        if operation not in EDIT_METHODS:
            raise ValueError(f"Unknown worksheet operation: {operation}")
        model = self._editor(sheet)
        result = getattr(model, operation)(**decode_value(parameters, model))
        if operation == "apply_column_metadata" and result:
            self.workspace.rename_column_references_in_plots(sheet.name, result)
        return result

    def new_sheet(self, name: str = "Sheet", rows: int = 25) -> Dataset:
        frame = pd.DataFrame({column: pd.Series(pd.NA, index=range(rows), dtype="object") for column in ("x", "y")})
        sheet = self.workspace.add_dataset(name, frame, copy_frame=False)
        for column in ("x", "y"):
            item = sheet.metadata_for_column(column)
            item.role = column
            item.comment = f"Default {column.upper()} column for a blank worksheet."
        sheet.sync_column_metadata_attrs()
        return sheet

    def rename_sheet(self, sheet: Dataset, name: str) -> None:
        self.workspace.rename_dataset(sheet.name, name)

    def duplicate_sheet(self, sheet: Dataset) -> Dataset:
        return self.workspace.duplicate_dataset(sheet.name)

    def delete_sheet(self, sheet: Dataset) -> None:
        self.workspace.remove_dataset(sheet.name)
