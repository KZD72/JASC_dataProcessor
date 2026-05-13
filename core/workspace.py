"""Workspace state for loaded and manually-created datasets."""

from __future__ import annotations

from copy import deepcopy
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


@dataclass(slots=True)
class SavedPlot:
    """A named plot definition that can be restored from project state."""

    name: str
    state: dict[str, object] = field(default_factory=dict)


class Workspace:
    """Container for all datasets and saved plots currently open in the application."""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}
        self._plots: dict[str, SavedPlot] = {}

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
        if name not in self._datasets:
            raise KeyError(f"Dataset '{name}' does not exist in the workspace.")
        del self._datasets[name]

    def rename_dataset(self, old_name: str, new_name: str) -> str:
        """Rename a dataset and return its final unique name."""
        if old_name not in self._datasets:
            raise KeyError(f"Dataset '{old_name}' does not exist in the workspace.")
        clean_name = new_name.strip() or old_name
        if clean_name == old_name:
            return old_name
        unique_name = self._make_unique_name(clean_name)
        dataset = self._datasets.pop(old_name)
        dataset.name = unique_name
        self._datasets[unique_name] = dataset
        self._rename_dataset_references_in_plots(old_name, unique_name)
        return unique_name

    def get_dataset(self, name: str) -> Dataset:
        """Return the dataset for a workspace name."""
        return self._datasets[name]

    def list_datasets(self) -> list[Dataset]:
        """Return datasets in insertion order."""
        return list(self._datasets.values())

    def dataset_names(self) -> list[str]:
        """Return the current dataset names in insertion order."""
        return list(self._datasets.keys())

    def add_plot(self, name: str, state: dict[str, object]) -> SavedPlot:
        """Add a saved plot under a unique display name and return it."""
        clean_name = name.strip() or "Plot"
        unique_name = self._make_unique_plot_name(clean_name)
        plot = SavedPlot(name=unique_name, state=deepcopy(state))
        self._plots[unique_name] = plot
        return plot

    def update_plot(self, name: str, state: dict[str, object]) -> SavedPlot:
        """Replace the state for an existing saved plot."""
        if name not in self._plots:
            raise KeyError(f"Saved plot '{name}' does not exist in the workspace.")
        self._plots[name].state = deepcopy(state)
        return self._plots[name]

    def remove_plot(self, name: str) -> None:
        """Remove a saved plot by name."""
        if name not in self._plots:
            raise KeyError(f"Saved plot '{name}' does not exist in the workspace.")
        del self._plots[name]

    def get_plot(self, name: str) -> SavedPlot:
        """Return the saved plot for a workspace name."""
        return self._plots[name]

    def list_plots(self) -> list[SavedPlot]:
        """Return saved plots in insertion order."""
        return list(self._plots.values())

    def plot_names(self) -> list[str]:
        """Return saved plot names in insertion order."""
        return list(self._plots.keys())

    def clear(self) -> None:
        """Remove all datasets and saved plots from the workspace."""
        self._datasets.clear()
        self._plots.clear()

    def _make_unique_name(self, base_name: str) -> str:
        if base_name not in self._datasets:
            return base_name

        counter = 2
        while f"{base_name} ({counter})" in self._datasets:
            counter += 1
        return f"{base_name} ({counter})"

    def _make_unique_plot_name(self, base_name: str) -> str:
        if base_name not in self._plots:
            return base_name

        counter = 2
        while f"{base_name} ({counter})" in self._plots:
            counter += 1
        return f"{base_name} ({counter})"

    def _rename_dataset_references_in_plots(self, old_name: str, new_name: str) -> None:
        for saved_plot in self._plots.values():
            series_list = saved_plot.state.get("series")
            if not isinstance(series_list, list):
                continue
            for series in series_list:
                if not isinstance(series, dict):
                    continue
                if series.get("x_dataset") == old_name:
                    series["x_dataset"] = new_name
                if series.get("y_dataset") == old_name:
                    series["y_dataset"] = new_name
