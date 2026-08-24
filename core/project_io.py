"""Project file save/load for workspace persistence.

Projects are saved as ZIP archives (.jasc) containing CSV data files
and a JSON metadata document.
"""

from __future__ import annotations

import json
import zipfile
from io import TextIOWrapper
from pathlib import Path

import pandas as pd

from core.workspace import ColumnMetadata, Workspace
from models.fit_functions import CustomFitModel

PROJECT_EXTENSION = ".jasc"
_META_FILENAME = "project.json"
_DATASETS_DIR = "datasets"
_PROJECT_VERSION = 2


def save_project(workspace: Workspace, path: str | Path) -> None:
    """Save the full workspace to a .jasc project file."""
    file_path = Path(path)
    if not file_path.parent.exists():
        raise FileNotFoundError(f"Folder does not exist: {file_path.parent}")

    datasets = workspace.list_datasets()
    metadata = {
        "version": _PROJECT_VERSION,
        "datasets": [],
        "plots": [],
        "custom_fit_models": [],
    }

    with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, dataset in enumerate(datasets):
            csv_name = f"{_DATASETS_DIR}/{index:04d}_{_sanitise_filename(dataset.name)}.csv"
            with archive.open(csv_name, "w") as raw_csv:
                with TextIOWrapper(raw_csv, encoding="utf-8", newline="") as csv_stream:
                    dataset.frame.to_csv(csv_stream, index=False)

            metadata["datasets"].append({
                "name": dataset.name,
                "csv_file": csv_name,
                "backend": dataset.backend,
                "source_path": str(dataset.source_path) if dataset.source_path else None,
                "formulas": dict(dataset.formulas),
                "column_metadata": {
                    str(column): entry.to_metadata()
                    for column, entry in dataset.column_metadata.items()
                    if not entry.is_empty()
                },
            })

        for plot in workspace.list_plots():
            metadata["plots"].append({
                "name": plot.name,
                "state": plot.state,
            })

        for model in workspace.list_custom_fit_models():
            metadata["custom_fit_models"].append(model.to_metadata())

        archive.writestr(_META_FILENAME, json.dumps(metadata, indent=2, ensure_ascii=False))


def load_project(path: str | Path) -> Workspace:
    """Load a workspace from a .jasc project file."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Project file does not exist: {file_path}")

    workspace = Workspace()

    with zipfile.ZipFile(file_path, "r") as archive:
        raw_meta = archive.read(_META_FILENAME).decode("utf-8")
        metadata = json.loads(raw_meta)

        if metadata.get("version", 0) > _PROJECT_VERSION:
            raise ValueError(
                f"Project file version {metadata['version']} is newer than "
                f"this application supports (version {_PROJECT_VERSION})."
            )

        for entry in metadata.get("datasets", []):
            with archive.open(entry["csv_file"], "r") as raw_csv:
                with TextIOWrapper(raw_csv, encoding="utf-8", newline="") as csv_stream:
                    frame = pd.read_csv(csv_stream)
            source_path = entry.get("source_path")

            dataset = workspace.add_dataset(
                entry["name"],
                frame,
                source_path=source_path,
                backend=entry.get("backend", "pandas"),
                copy_frame=False,
            )

            formulas = entry.get("formulas")
            if isinstance(formulas, dict):
                dataset.formulas.update(formulas)

            column_metadata = entry.get("column_metadata")
            if isinstance(column_metadata, dict):
                dataset.set_column_metadata({
                    str(column): ColumnMetadata.from_metadata(metadata_entry)
                    for column, metadata_entry in column_metadata.items()
                })

        for entry in metadata.get("plots", []):
            name = entry.get("name")
            state = entry.get("state")
            if isinstance(name, str) and isinstance(state, dict):
                workspace.add_plot(name, state)

        for entry in metadata.get("custom_fit_models", []):
            try:
                workspace.add_custom_fit_model(CustomFitModel.from_metadata(entry))
            except (TypeError, ValueError):
                continue

    return workspace


def _sanitise_filename(name: str) -> str:
    """Convert a dataset display name to a safe ZIP entry name."""
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return safe.strip() or "dataset"
