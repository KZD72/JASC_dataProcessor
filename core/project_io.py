"""Project file save/load for workspace persistence.

Projects are saved as ZIP archives (.jasc) containing CSV data files
and a JSON metadata document.
"""

from __future__ import annotations

import json
import zipfile
from io import StringIO
from pathlib import Path

import pandas as pd

from core.workspace import Workspace

PROJECT_EXTENSION = ".jasc"
_META_FILENAME = "project.json"
_DATASETS_DIR = "datasets"
_PROJECT_VERSION = 1


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
    }

    with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, dataset in enumerate(datasets):
            csv_name = f"{_DATASETS_DIR}/{index:04d}_{_sanitise_filename(dataset.name)}.csv"
            csv_buffer = StringIO()
            dataset.frame.to_csv(csv_buffer, index=False, encoding="utf-8")
            archive.writestr(csv_name, csv_buffer.getvalue())

            metadata["datasets"].append({
                "name": dataset.name,
                "csv_file": csv_name,
                "source_path": str(dataset.source_path) if dataset.source_path else None,
                "formulas": dict(dataset.formulas),
            })

        for plot in workspace.list_plots():
            metadata["plots"].append({
                "name": plot.name,
                "state": plot.state,
            })

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
            csv_data = archive.read(entry["csv_file"]).decode("utf-8")
            frame = pd.read_csv(StringIO(csv_data))
            source_path = entry.get("source_path")

            dataset = workspace.add_dataset(
                entry["name"],
                frame,
                source_path=source_path,
            )

            formulas = entry.get("formulas")
            if isinstance(formulas, dict):
                dataset.formulas.update(formulas)

        for entry in metadata.get("plots", []):
            name = entry.get("name")
            state = entry.get("state")
            if isinstance(name, str) and isinstance(state, dict):
                workspace.add_plot(name, state)

    return workspace


def _sanitise_filename(name: str) -> str:
    """Convert a dataset display name to a safe ZIP entry name."""
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return safe.strip() or "dataset"
