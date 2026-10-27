"""Workspace state for loaded and manually-created datasets."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from core.data_backends import PANDAS_BACKEND, normalize_backend
from core.operations import rename_worksheet_references
from core.spectral_analysis import SpectralAnalysisSession
from core.large_data import LargeDataset
from models.fit_functions import CustomFitModel


COLUMN_ROLE_LABELS: dict[str, str] = {
    "": "None",
    "x": "X",
    "y": "Y",
    "z": "Z",
    "error": "Error",
    "x_error": "X error",
    "y_error": "Y error",
    "group": "Group",
    "label": "Label",
    "weight": "Weight",
}
COLUMN_ROLE_OPTIONS: tuple[tuple[str, str], ...] = tuple(COLUMN_ROLE_LABELS.items())

COLUMN_TYPE_LABELS: dict[str, str] = {
    "": "Auto",
    "numeric": "Numeric",
    "scientific": "Scientific",
    "text": "Text",
}
COLUMN_TYPE_OPTIONS: tuple[tuple[str, str], ...] = tuple(COLUMN_TYPE_LABELS.items())
COLUMN_NUMERIC_TYPES = {"numeric", "scientific"}
DATAFRAME_COLUMN_METADATA_ATTR = "jasc_column_metadata"


@dataclass(slots=True)
class WorksheetMetadata:
    """Descriptive and import metadata attached to an entire worksheet."""

    fields: list[tuple[str, str]] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)
    import_details: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """Return whether the worksheet has no stored metadata."""
        return not (self.fields or self.raw_lines or self.import_details)

    def to_metadata(self) -> dict[str, object]:
        """Return a JSON-friendly representation for project persistence."""
        return {
            "fields": [
                {"name": str(name), "value": str(value)}
                for name, value in self.fields
            ],
            "raw_lines": [str(line) for line in self.raw_lines],
            "import_details": {
                str(name): str(value)
                for name, value in self.import_details.items()
            },
        }

    @classmethod
    def from_metadata(cls, metadata: object) -> "WorksheetMetadata":
        """Restore worksheet metadata from a project entry."""
        if not isinstance(metadata, dict):
            return cls()

        fields: list[tuple[str, str]] = []
        raw_fields = metadata.get("fields", [])
        if isinstance(raw_fields, list):
            for entry in raw_fields:
                if isinstance(entry, dict):
                    fields.append((
                        str(entry.get("name", "") or ""),
                        str(entry.get("value", "") or ""),
                    ))
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    fields.append((str(entry[0]), str(entry[1])))

        raw_lines_value = metadata.get("raw_lines", [])
        raw_lines = (
            [str(line) for line in raw_lines_value]
            if isinstance(raw_lines_value, list)
            else []
        )
        raw_details = metadata.get("import_details", {})
        import_details = (
            {str(name): str(value) for name, value in raw_details.items()}
            if isinstance(raw_details, dict)
            else {}
        )
        return cls(
            fields=fields,
            raw_lines=raw_lines,
            import_details=import_details,
        )


@dataclass(slots=True)
class ColumnMetadata:
    """User-editable metadata associated with one dataset column."""

    role: str = ""
    unit: str = ""
    long_name: str = ""
    comment: str = ""
    value_type: str = ""
    display_precision: int | None = None

    def is_empty(self) -> bool:
        """Return whether no meaningful metadata is stored."""
        return not any((
            self.role,
            self.unit,
            self.long_name,
            self.comment,
            self.value_type,
            self.display_precision is not None,
        ))

    def to_metadata(self) -> dict[str, str | int | None]:
        """Return JSON-friendly metadata."""
        return {
            "role": self.role,
            "unit": self.unit,
            "long_name": self.long_name,
            "comment": self.comment,
            "value_type": self.value_type,
            "display_precision": self.display_precision,
        }

    @classmethod
    def from_metadata(cls, metadata: object) -> "ColumnMetadata":
        """Create column metadata from a project file entry."""
        if not isinstance(metadata, dict):
            return cls()
        role = normalize_column_role(str(metadata.get("role", "") or ""))
        precision = normalize_display_precision(metadata.get("display_precision"))
        return cls(
            role=role,
            unit=str(metadata.get("unit", "") or "").strip(),
            long_name=str(metadata.get("long_name", "") or "").strip(),
            comment=str(metadata.get("comment", "") or "").strip(),
            value_type=normalize_column_type(str(metadata.get("value_type", "") or "")),
            display_precision=precision,
        )


@dataclass(slots=True)
class FigureExtractionSession:
    """Embedded image and calibration state used to resume figure extraction."""

    session_id: str
    extraction_kind: str
    image_png: bytes
    source_path: str = ""
    state: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class Dataset:
    """A named DataFrame plus optional source metadata."""

    name: str
    frame: pd.DataFrame
    source_path: Path | None = None
    backend: str = PANDAS_BACKEND
    formulas: dict[str, str] = field(default_factory=dict)
    column_metadata: dict[str, ColumnMetadata] = field(default_factory=dict)
    worksheet_metadata: WorksheetMetadata = field(default_factory=WorksheetMetadata)
    figure_session: FigureExtractionSession | None = None

    def metadata_for_column(self, column_name: str) -> ColumnMetadata:
        """Return metadata for a column, creating an empty record if needed."""
        key = str(column_name)
        metadata = self.column_metadata.get(key)
        if metadata is None:
            metadata = ColumnMetadata()
            self.column_metadata[key] = metadata
        return metadata

    def set_column_metadata(self, metadata: dict[str, ColumnMetadata]) -> None:
        """Replace metadata, keeping only entries for existing columns."""
        existing = {str(column) for column in self.frame.columns}
        self.column_metadata = {
            str(column): ColumnMetadata(
                role=normalize_column_role(entry.role),
                unit=entry.unit.strip(),
                long_name=entry.long_name.strip(),
                comment=entry.comment.strip(),
                value_type=normalize_column_type(entry.value_type),
                display_precision=normalize_display_precision(entry.display_precision),
            )
            for column, entry in metadata.items()
            if str(column) in existing and not entry.is_empty()
        }
        self.sync_column_metadata_attrs()

    def prune_column_metadata(self) -> None:
        """Drop metadata entries for columns no longer present in the DataFrame."""
        existing = {str(column) for column in self.frame.columns}
        self.column_metadata = {
            str(column): metadata
            for column, metadata in self.column_metadata.items()
            if str(column) in existing and not metadata.is_empty()
        }
        self.sync_column_metadata_attrs()

    def sync_column_metadata_attrs(self) -> None:
        """Mirror lightweight column metadata into DataFrame attrs for math helpers."""
        self.frame.attrs[DATAFRAME_COLUMN_METADATA_ATTR] = {
            str(column): metadata.to_metadata()
            for column, metadata in self.column_metadata.items()
            if not metadata.is_empty()
        }


@dataclass(slots=True)
class SavedPlot:
    """A named plot definition that can be restored from project state."""

    name: str
    state: dict[str, object] = field(default_factory=dict)


class Workspace:
    """Container for all datasets and saved plots currently open in the application."""

    def __init__(self) -> None:
        """Initialize empty dataset and saved-plot registries."""
        self._datasets: dict[str, Dataset] = {}
        # Large sources never masquerade as a Dataset with a partial frame.
        self._large_datasets: dict[str, LargeDataset] = {}
        self._plots: dict[str, SavedPlot] = {}
        self._spectral_analyses: dict[str, SpectralAnalysisSession] = {}
        self._custom_fit_models: dict[str, CustomFitModel] = {}
        self.project_signature_status = "unsigned"
        self.project_signer_fingerprint: str | None = None
        self.project_signer_name: str | None = None

    def add_large_dataset(self, dataset: LargeDataset) -> LargeDataset:
        """Adopt an immutable disk snapshot outside the editable-sheet registry."""
        base = dataset.name.strip() or "Large Dataset"
        name, index = base, 2
        while name in self._large_datasets:
            name = f"{base} ({index})"
            index += 1
        dataset.name = name
        self._large_datasets[name] = dataset
        return dataset

    def large_dataset_names(self) -> list[str]:
        return list(self._large_datasets)

    def list_large_datasets(self) -> list[LargeDataset]:
        return list(self._large_datasets.values())

    def get_large_dataset(self, name: str) -> LargeDataset:
        return self._large_datasets[name]

    def remove_large_dataset(self, name: str) -> None:
        """Release workspace ownership; readers retain their own safe reference."""
        del self._large_datasets[name]

    def add_dataset(
        self,
        name: str,
        frame: pd.DataFrame,
        source_path: str | Path | None = None,
        backend: str = PANDAS_BACKEND,
        *,
        copy_frame: bool = True,
    ) -> Dataset:
        """Add a DataFrame under a unique display name and return its dataset.

        ``copy_frame=False`` is reserved for ownership-transfer paths such as a
        freshly parsed import, where no caller will continue mutating ``frame``.
        """
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("Workspace datasets must be pandas DataFrames.")

        clean_name = name.strip() or "Dataset"
        unique_name = self._make_unique_name(clean_name)
        dataset = Dataset(
            name=unique_name,
            frame=frame.copy() if copy_frame else frame,
            source_path=Path(source_path) if source_path else None,
            backend=normalize_backend(backend),
        )
        self._datasets[unique_name] = dataset
        return dataset

    def remove_dataset(self, name: str) -> None:
        """Remove a dataset by name."""
        if name not in self._datasets:
            raise KeyError(f"Dataset '{name}' does not exist in the workspace.")
        del self._datasets[name]

    def duplicate_dataset(self, name: str) -> Dataset:
        """Create an independent copy of a dataset, including formulas and metadata."""
        if name not in self._datasets:
            raise KeyError(f"Dataset '{name}' does not exist in the workspace.")
        source = self._datasets[name]
        duplicate = self.add_dataset(
            self._copy_base_name(source.name),
            source.frame.copy(deep=True),
            source_path=source.source_path,
            backend=source.backend,
            copy_frame=False,
        )
        duplicate.formulas = deepcopy(source.formulas)
        duplicate.column_metadata = copy_column_metadata(source.column_metadata)
        duplicate.worksheet_metadata = deepcopy(source.worksheet_metadata)
        duplicate.figure_session = deepcopy(source.figure_session)
        duplicate.sync_column_metadata_attrs()
        return duplicate

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
        for workspace_dataset in self._datasets.values():
            workspace_dataset.formulas = {
                column_name: rename_worksheet_references(expression, old_name, unique_name)
                for column_name, expression in workspace_dataset.formulas.items()
            }
        self._rename_dataset_references_in_plots(old_name, unique_name)
        for analysis in self._spectral_analyses.values():
            if analysis.source_dataset == old_name:
                analysis.source_dataset = unique_name
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

    def duplicate_plot(self, name: str) -> SavedPlot:
        """Create an independently editable copy of a saved plot definition."""
        if name not in self._plots:
            raise KeyError(f"Saved plot '{name}' does not exist in the workspace.")
        source = self._plots[name]
        return self.add_plot(self._copy_base_name(source.name), source.state)

    def get_plot(self, name: str) -> SavedPlot:
        """Return the saved plot for a workspace name."""
        return self._plots[name]

    def list_plots(self) -> list[SavedPlot]:
        """Return saved plots in insertion order."""
        return list(self._plots.values())

    def plot_names(self) -> list[str]:
        """Return saved plot names in insertion order."""
        return list(self._plots.keys())

    def add_spectral_analysis(
        self,
        analysis: SpectralAnalysisSession,
    ) -> SpectralAnalysisSession:
        """Store a spectral analysis under a unique navigator name."""
        clean_name = analysis.name.strip() or "Spectral Analysis"
        unique_name = self._make_unique_analysis_name(clean_name)
        analysis.name = unique_name
        self._spectral_analyses[unique_name] = analysis
        return analysis

    def get_spectral_analysis(self, name: str) -> SpectralAnalysisSession:
        """Return one stored spectral analysis."""
        return self._spectral_analyses[name]

    def list_spectral_analyses(self) -> list[SpectralAnalysisSession]:
        """Return analyses in insertion order."""
        return list(self._spectral_analyses.values())

    def spectral_analysis_names(self) -> list[str]:
        """Return stored analysis names in insertion order."""
        return list(self._spectral_analyses.keys())

    def remove_spectral_analysis(self, name: str) -> None:
        """Remove an analysis without touching its source dataset."""
        if name not in self._spectral_analyses:
            raise KeyError(f"Analysis '{name}' does not exist in the workspace.")
        del self._spectral_analyses[name]

    def duplicate_spectral_analysis(self, name: str) -> SpectralAnalysisSession:
        """Duplicate a result session and all of its internal frames."""
        source = self.get_spectral_analysis(name)
        return self.add_spectral_analysis(source.copy(name=self._copy_base_name(source.name)))

    def add_custom_fit_model(self, model: CustomFitModel) -> CustomFitModel:
        """Add a custom fit model under a unique display name."""
        unique_name = self._make_unique_custom_fit_model_name(model.name)
        stored_model = CustomFitModel(
            name=unique_name,
            expression=model.expression,
            parameter_names=model.parameter_names,
            default_initial=model.default_initial,
        )
        self._custom_fit_models[unique_name] = stored_model
        return stored_model

    def set_custom_fit_models(self, models: list[CustomFitModel]) -> None:
        """Replace all project custom fit models."""
        self._custom_fit_models = {model.name: model for model in models}

    def list_custom_fit_models(self) -> list[CustomFitModel]:
        """Return custom fit models in insertion order."""
        return list(self._custom_fit_models.values())

    def custom_fit_model_names(self) -> list[str]:
        """Return custom fit model names in insertion order."""
        return list(self._custom_fit_models.keys())

    def clear(self) -> None:
        """Remove all datasets, saved plots, and custom fit models from the workspace."""
        self._datasets.clear()
        self._plots.clear()
        self._spectral_analyses.clear()
        self._custom_fit_models.clear()

    def _make_unique_name(self, base_name: str) -> str:
        """Return a dataset name that does not collide with existing datasets."""
        if base_name not in self._datasets:
            return base_name

        counter = 2
        while f"{base_name} ({counter})" in self._datasets:
            counter += 1
        return f"{base_name} ({counter})"

    @staticmethod
    def _copy_base_name(name: str) -> str:
        """Return a stable Copy base so duplicating a copy increments its suffix."""
        if name.endswith(" Copy"):
            return name
        root, marker, suffix = name.rpartition(" Copy (")
        if marker and suffix.endswith(")") and suffix[:-1].isdigit():
            return f"{root} Copy"
        return f"{name} Copy"

    def _make_unique_plot_name(self, base_name: str) -> str:
        """Return a saved-plot name that does not collide with existing plots."""
        if base_name not in self._plots:
            return base_name

        counter = 2
        while f"{base_name} ({counter})" in self._plots:
            counter += 1
        return f"{base_name} ({counter})"

    def _make_unique_analysis_name(self, base_name: str) -> str:
        """Return an analysis name that does not collide with existing analyses."""
        if base_name not in self._spectral_analyses:
            return base_name
        counter = 2
        while f"{base_name} ({counter})" in self._spectral_analyses:
            counter += 1
        return f"{base_name} ({counter})"

    def _make_unique_custom_fit_model_name(self, base_name: str) -> str:
        """Return a custom fit model name that does not collide with existing models."""
        if base_name not in self._custom_fit_models:
            return base_name

        counter = 2
        while f"{base_name} ({counter})" in self._custom_fit_models:
            counter += 1
        return f"{base_name} ({counter})"

    def _rename_dataset_references_in_plots(self, old_name: str, new_name: str) -> None:
        """Update saved plot series when a referenced dataset is renamed."""
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
                if series.get("z_dataset") == old_name:
                    series["z_dataset"] = new_name

    def rename_column_references_in_plots(
        self,
        dataset_name: str,
        rename_map: dict[str, str],
    ) -> None:
        """Update saved plot series when referenced columns are renamed."""
        if not rename_map:
            return

        for saved_plot in self._plots.values():
            series_list = saved_plot.state.get("series")
            if not isinstance(series_list, list):
                continue
            for series in series_list:
                if not isinstance(series, dict):
                    continue
                if series.get("x_dataset") == dataset_name:
                    self._rename_series_column(series, "x_column", rename_map)
                    self._rename_series_column(series, "x_err_column", rename_map)
                if series.get("y_dataset") == dataset_name:
                    self._rename_series_column(series, "y_column", rename_map)
                    self._rename_series_column(series, "y_err_column", rename_map)
                    self._rename_series_column(series, "lower_column", rename_map)
                    self._rename_series_column(series, "upper_column", rename_map)
                    distribution_columns = series.get("distribution_columns")
                    if isinstance(distribution_columns, list):
                        series["distribution_columns"] = [
                            rename_map.get(str(column), str(column))
                            for column in distribution_columns
                        ]
                    elif isinstance(distribution_columns, tuple):
                        series["distribution_columns"] = tuple(
                            rename_map.get(str(column), str(column))
                            for column in distribution_columns
                        )
                if series.get("z_dataset") == dataset_name:
                    self._rename_series_column(series, "z_column", rename_map)

    @staticmethod
    def _rename_series_column(
        series: dict[str, object],
        key: str,
        rename_map: dict[str, str],
    ) -> None:
        """Rename one saved-series column field if it exists in a rename map."""
        value = series.get(key)
        if isinstance(value, str) and value in rename_map:
            series[key] = rename_map[value]


def normalize_column_role(role: str) -> str:
    """Return a supported column role key, accepting a few display aliases."""
    clean = role.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "none": "",
        "": "",
        "xerror": "x_error",
        "x_err": "x_error",
        "yerror": "y_error",
        "y_err": "y_error",
        "err": "error",
        "sigma": "error",
    }
    clean = aliases.get(clean, clean)
    return clean if clean in COLUMN_ROLE_LABELS else ""


def column_role_label(role: str) -> str:
    """Return a user-facing label for a column role key."""
    return COLUMN_ROLE_LABELS.get(normalize_column_role(role), "None")


def normalize_column_type(value_type: str) -> str:
    """Return a supported column type key."""
    clean = value_type.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "auto": "",
        "none": "",
        "": "",
        "number": "numeric",
        "float": "numeric",
        "integer": "numeric",
        "int": "numeric",
        "sci": "scientific",
        "scientific_notation": "scientific",
        "string": "text",
        "category": "text",
        "categorical": "text",
    }
    clean = aliases.get(clean, clean)
    return clean if clean in COLUMN_TYPE_LABELS else ""


def column_type_label(value_type: str) -> str:
    """Return a user-facing label for a column type key."""
    return COLUMN_TYPE_LABELS.get(normalize_column_type(value_type), "Auto")


def normalize_display_precision(value: object) -> int | None:
    """Return a valid display precision, treating blanks and negatives as automatic."""
    if value in ("", None):
        return None
    try:
        precision = int(value)
    except (TypeError, ValueError):
        return None
    if precision < 0:
        return None
    return min(precision, 15)


def dataframe_column_metadata(frame: pd.DataFrame, column: str) -> ColumnMetadata:
    """Return metadata mirrored into DataFrame attrs for non-Workspace helpers."""
    metadata_by_column = frame.attrs.get(DATAFRAME_COLUMN_METADATA_ATTR, {})
    if not isinstance(metadata_by_column, dict):
        return ColumnMetadata()
    metadata = metadata_by_column.get(str(column), {})
    return ColumnMetadata.from_metadata(metadata)


def set_column_operation_comment(dataset: Dataset, column_name: str, operation_text: str) -> None:
    """Record the latest generated operation in a column metadata comment."""
    metadata = dataset.metadata_for_column(column_name)
    existing_lines = [
        line
        for line in metadata.comment.splitlines()
        if not line.startswith("Operation: ")
    ]
    while existing_lines and not existing_lines[-1].strip():
        existing_lines.pop()
    existing_lines.append(f"Operation: {operation_text.strip()}")
    metadata.comment = "\n".join(existing_lines).strip()
    dataset.sync_column_metadata_attrs()


def set_dataset_operation_comments(
    dataset: Dataset,
    operation_text: str,
    column_names: list[str] | tuple[str, ...] | None = None,
) -> None:
    """Record operation provenance on multiple generated result columns."""
    available_columns = {str(column) for column in dataset.frame.columns}
    target_columns = column_names if column_names is not None else [str(column) for column in dataset.frame.columns]
    for column_name in target_columns:
        clean_name = str(column_name)
        if clean_name in available_columns:
            set_column_operation_comment(dataset, clean_name, operation_text)


def copy_column_metadata(metadata: dict[str, ColumnMetadata]) -> dict[str, ColumnMetadata]:
    """Return a deep-enough copy of column metadata values."""
    return {
        str(column): ColumnMetadata(
            role=entry.role,
            unit=entry.unit,
            long_name=entry.long_name,
            comment=entry.comment,
            value_type=entry.value_type,
            display_precision=entry.display_precision,
        )
        for column, entry in metadata.items()
    }
