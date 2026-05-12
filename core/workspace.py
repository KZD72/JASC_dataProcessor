"""Workspace state for loaded and manually-created datasets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass(slots=True)
class Dataset:
    """A named DataFrame plus optional source metadata."""

    name: str
    frame: pd.DataFrame
    source_path: Path | None = None
    formulas: dict[str, str] = field(default_factory=dict)


class Workspace:
    """Container for all datasets currently open in the application."""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}

    def add_dataset(
        self,
        name: str,
        frame: pd.DataFrame,
        source_path: str | Path | None = None,
    ) -> Dataset:
        """Add a DataFrame under a unique display name and return its dataset."""
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("Workspace datasets must be pandas DataFrames.")

        clean_name = name.strip() or "Dataset"
        unique_name = self._make_unique_name(clean_name)
        dataset = Dataset(
            name=unique_name,
            frame=frame.copy(),
            source_path=Path(source_path) if source_path else None,
        )
        self._datasets[unique_name] = dataset
        return dataset

    def remove_dataset(self, name: str) -> None:
        """Remove a dataset by name."""
        del self._datasets[name]

    def get_dataset(self, name: str) -> Dataset:
        """Return the dataset for a workspace name."""
        return self._datasets[name]

    def list_datasets(self) -> list[Dataset]:
        """Return datasets in insertion order."""
        return list(self._datasets.values())

    def dataset_names(self) -> list[str]:
        """Return the current dataset names in insertion order."""
        return list(self._datasets.keys())

    def clear(self) -> None:
        """Remove all datasets from the workspace."""
        self._datasets.clear()

    def _make_unique_name(self, base_name: str) -> str:
        if base_name not in self._datasets:
            return base_name

        counter = 2
        while f"{base_name} ({counter})" in self._datasets:
            counter += 1
        return f"{base_name} ({counter})"
