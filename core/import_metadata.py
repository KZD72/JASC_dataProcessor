"""Shared conservative column-role/type hints for text and workbook imports."""
from __future__ import annotations
import pandas as pd
from core.workspace import Dataset, ColumnMetadata
from core.file_io import DelimitedFileInspection

def apply_imported_column_hints(
    dataset: Dataset,
    inspection: DelimitedFileInspection | None = None,
) -> None:
    """Apply conservative numeric, X/Y, and spectroscopy-unit hints."""
    if inspection is not None and inspection.format_name == "spectral_map_matrix":
        columns = [str(column) for column in dataset.frame.columns]
        if columns:
            x_metadata = dataset.metadata_for_column(columns[0])
            x_metadata.role = "x"
            x_metadata.value_type = "numeric"
            x_metadata.long_name = "Map X coordinate"
        if len(columns) >= 2:
            y_metadata = dataset.metadata_for_column(columns[1])
            y_metadata.role = "y"
            y_metadata.value_type = "numeric"
            y_metadata.long_name = "Map Y coordinate"
        if "Raman Shift" in columns:
            shift_metadata = dataset.metadata_for_column("Raman Shift")
            shift_metadata.value_type = "numeric"
            shift_metadata.unit = "cm^-1"
            shift_metadata.long_name = "Raman shift"
        if "Intensity" in columns:
            intensity_metadata = dataset.metadata_for_column("Intensity")
            intensity_metadata.value_type = "numeric"
            intensity_metadata.long_name = "Raman intensity"
        dataset.prune_column_metadata()
        return

    x_terms = (
        "wavenumber",
        "wave number",
        "wavelength",
        "raman shift",
        "frequency",
        "time",
    )
    y_terms = (
        "intensity",
        "signal",
        "count",
        "absorbance",
        "transmittance",
        "dark subtracted",
    )
    numeric_columns: list[str] = []
    assigned_x = False
    assigned_y = False
    for column in dataset.frame.columns:
        column_name = str(column)
        if not pd.api.types.is_numeric_dtype(dataset.frame[column].dtype):
            continue
        numeric_columns.append(column_name)
        entry = dataset.metadata_for_column(column_name)
        entry.value_type = "numeric"
        normalized_name = column_name.casefold()
        if not assigned_x and any(term in normalized_name for term in x_terms):
            entry.role = "x"
            assigned_x = True
        elif not assigned_y and any(term in normalized_name for term in y_terms):
            entry.role = "y"
            assigned_y = True

    if numeric_columns and not assigned_x:
        dataset.metadata_for_column(numeric_columns[0]).role = "x"
        assigned_x = True
    if len(numeric_columns) >= 2 and not assigned_y:
        y_column = next(
            (column for column in numeric_columns if dataset.metadata_for_column(column).role != "x"),
            numeric_columns[1],
        )
        dataset.metadata_for_column(y_column).role = "y"

    metadata_fields = {
        name.strip().casefold(): value.strip()
        for name, value in dataset.worksheet_metadata.fields
    }
    if len(numeric_columns) >= 2:
        x_unit = metadata_fields.get("axisunit[1]", "")
        y_unit = metadata_fields.get("axisunit[0]", "")
        if x_unit:
            dataset.metadata_for_column(numeric_columns[0]).unit = x_unit
        if y_unit:
            dataset.metadata_for_column(numeric_columns[1]).unit = y_unit
    dataset.prune_column_metadata()


def apply_interpolation_metadata(
    source_dataset: Dataset,
    result_dataset: Dataset,
    coordinate_columns: list[str],
    value_column: str,
) -> None:
    """Copy useful source metadata onto interpolation result columns."""
    for column_name in coordinate_columns:
        if column_name not in result_dataset.frame.columns:
            continue
        source_metadata = source_dataset.column_metadata.get(column_name)
        if source_metadata is None:
            continue
        result_dataset.column_metadata[column_name] = ColumnMetadata(
            role=source_metadata.role,
            unit=source_metadata.unit,
            long_name=source_metadata.long_name,
            comment=source_metadata.comment,
            value_type=source_metadata.value_type,
            display_precision=source_metadata.display_precision,
        )

    prediction_column = f"{value_column}_interpolated"
    if prediction_column not in result_dataset.frame.columns:
        return
    value_metadata = source_dataset.column_metadata.get(value_column, ColumnMetadata())
    result_dataset.column_metadata[prediction_column] = ColumnMetadata(
        role=value_metadata.role or ("y" if len(coordinate_columns) == 1 else "z"),
        unit=value_metadata.unit,
        long_name=f"Interpolated {value_metadata.long_name or value_column}",
        comment=value_metadata.comment,
        value_type=value_metadata.value_type,
        display_precision=value_metadata.display_precision,
    )
    result_dataset.sync_column_metadata_attrs()
