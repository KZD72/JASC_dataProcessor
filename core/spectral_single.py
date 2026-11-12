"""Publish single-spectrum results identically from the GUI and Python API."""
from __future__ import annotations
from types import SimpleNamespace
import pandas as pd
from core.workspace import ColumnMetadata, Workspace, Dataset, set_dataset_operation_comments
from core.spectral_analysis import SpectralAnalysisSession
from core.peak_fit_jobs import peak_fit_map_row

def publish_spectrum(workspace: Workspace, dataset: Dataset, dialog: object, baseline_result: object,
                     peak_result: object, composite_result: object, baseline_only: bool,
                     preview_coordinates: dict, detail: dict, operation_name: str) -> SimpleNamespace:
    spectral_analysis: SpectralAnalysisSession | None = None
    if not baseline_only and composite_result is not None and peak_result is not None:
        common = {"source_sheet": dataset.name, **preview_coordinates}
        curve_frame = composite_result.fit_frame.rename(
            columns={"baseline": "fit_baseline"}
        ).copy()
        preprocessing = pd.DataFrame({
            "x": baseline_result.x,
            "raw": baseline_result.raw,
            "preprocessing_baseline": baseline_result.baseline,
            "corrected": baseline_result.corrected,
        })
        curve_frame = preprocessing.merge(curve_frame, on="x", how="inner", sort=False)
        for name, value in reversed(list(common.items())):
            curve_frame.insert(0, name, value)
        parameter_frame = composite_result.parameter_frame.copy()
        for name, value in common.items():
            parameter_frame[name] = value
        peak_frame = dialog.reviewed_peak_frame()
        for name, value in common.items():
            if name not in peak_frame:
                peak_frame[name] = value
        metrics = pd.DataFrame([
            peak_fit_map_row(
                composite_result,
                source_name=dataset.name,
                coordinates=preview_coordinates,
                noise_estimate=peak_result.noise_estimate,
                detected_peak_count=len(peak_result.peaks),
                matched_peak_count=len(composite_result.components),
            )
        ])
        spectral_analysis = workspace.add_spectral_analysis(
            SpectralAnalysisSession(
                name=dialog.analysis_name(),
                source_dataset=dataset.name,
                analysis_kind="raman_pixel" if preview_coordinates else "spectrum",
                x_column=dialog.x_column(),
                y_column=dialog.y_column(),
                coordinate_columns=tuple(preview_coordinates),
                profile={"settings": dialog.analysis_profile(), "provenance": detail},
                metrics_frame=metrics,
                curves_frame=curve_frame,
                parameters_frame=parameter_frame,
                peaks_frame=peak_frame,
            )
        )

    created_names: list[str] = []
    selected_name: str | None = None
    if dialog.create_signal_output():
        y_column = dialog.y_column()
        baseline_column = f"{y_column}_baseline"
        corrected_column = f"{y_column}_corrected"
        signal_frame = pd.DataFrame({
            dialog.x_column(): baseline_result.x,
            y_column: baseline_result.raw,
            baseline_column: baseline_result.baseline,
            corrected_column: baseline_result.corrected,
        })
        for coordinate_name, coordinate_value in reversed(list(preview_coordinates.items())):
            signal_frame.insert(0, coordinate_name, coordinate_value)
        signal_dataset = workspace.add_dataset(
            dialog.result_sheet_name(), signal_frame, copy_frame=False
        )
        signal_dataset.worksheet_metadata.import_details.update(detail)
        source_x_metadata = dataset.column_metadata.get(dialog.x_column())
        source_y_metadata = dataset.column_metadata.get(y_column)
        signal_dataset.column_metadata[dialog.x_column()] = ColumnMetadata(
            role="x",
            unit=source_x_metadata.unit if source_x_metadata else "",
            long_name=source_x_metadata.long_name if source_x_metadata else "",
            value_type="numeric",
        )
        for column_name, long_name in (
            (y_column, source_y_metadata.long_name if source_y_metadata else "Raw signal"),
            (baseline_column, "Estimated baseline"),
            (corrected_column, "Baseline-corrected signal"),
        ):
            signal_dataset.column_metadata[column_name] = ColumnMetadata(
                role="y",
                unit=source_y_metadata.unit if source_y_metadata else "",
                long_name=long_name,
                value_type="numeric",
            )
        signal_dataset.sync_column_metadata_attrs()
        set_dataset_operation_comments(
            signal_dataset,
            f"{operation_name}: source={dataset.name}; x={dialog.x_column()}; "
            f"y={y_column}; baseline={baseline_result.parameters.method}",
        )
        selected_name = signal_dataset.name
        created_names.append(signal_dataset.name)

    if dialog.create_peak_output():
        peak_frame = dialog.reviewed_peak_frame()
        peak_dataset = workspace.add_dataset(
            dialog.peak_sheet_name(), peak_frame, copy_frame=False
        )
        peak_dataset.worksheet_metadata.import_details.update(detail)
        peak_dataset.worksheet_metadata.import_details["Reviewed peak count"] = str(
            int(peak_frame["enabled"].sum()) if "enabled" in peak_frame else 0
        )
        for column_name in peak_frame.columns:
            metadata = peak_dataset.metadata_for_column(str(column_name))
            metadata.value_type = "text" if str(column_name) in {
                "source_sheet", "channel", "polarity", "detector", "manual_status"
            } else "numeric"
            if str(column_name) == "center":
                metadata.role = "x"
                source_x_metadata = dataset.column_metadata.get(dialog.x_column())
                metadata.unit = source_x_metadata.unit if source_x_metadata else ""
            elif str(column_name) in {"raw_height", "corrected_height", "prominence", "area"}:
                metadata.role = "y"
        peak_dataset.sync_column_metadata_attrs()
        set_dataset_operation_comments(
            peak_dataset,
            f"Peak Detection: source={dataset.name}; x={dialog.x_column()}; "
            f"y={dialog.y_column()}; reviewed candidates",
        )
        selected_name = peak_dataset.name
        created_names.append(peak_dataset.name)

    if dialog.create_fit_output() and composite_result is not None:
        fit_dataset = workspace.add_dataset(
            dialog.fit_sheet_name(), composite_result.fit_frame, copy_frame=False
        )
        fit_dataset.worksheet_metadata.import_details.update(detail)
        set_dataset_operation_comments(
            fit_dataset,
            f"Composite Peak Fit: source={dataset.name}; x={dialog.x_column()}; "
            f"y={dialog.y_column()}; components={len(composite_result.components)}",
        )
        parameter_dataset = workspace.add_dataset(
            dialog.fit_parameter_sheet_name(),
            composite_result.parameter_frame,
            copy_frame=False,
        )
        parameter_dataset.worksheet_metadata.import_details.update(detail)
        set_dataset_operation_comments(
            parameter_dataset,
            f"Composite Peak Fit parameters: source={dataset.name}",
        )
        selected_name = parameter_dataset.name
        created_names.extend((fit_dataset.name, parameter_dataset.name))

    return SimpleNamespace(analysis=spectral_analysis, sheets=[workspace.get_dataset(name) for name in created_names],
                           selected_name=selected_name)
