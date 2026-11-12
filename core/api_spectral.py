"""Spectrum API, including replay of explicit peak review decisions."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from threading import Event
from types import SimpleNamespace

import numpy as np
import pandas as pd

from core.jobs import JobContext
from core.spectral_analysis import SpectralAnalysisSession
from core.spectral_jobs import SpectralSource
from core.spectral_preview import SpectralPreviewRequest, prepare_spectral_preview
from core.spectral_single import publish_spectrum
from core.workspace import Dataset, Workspace, set_dataset_operation_comments
from math_engine.baseline import BaselineParameters
from math_engine.composite_peak_fit import CompositeFitParameters, PeakComponentSpec
from math_engine.peak_detection import PeakDetectionParameters, PeakRecord


def components_from_dict(items: list[dict]) -> tuple[PeakComponentSpec, ...]:
    return tuple(PeakComponentSpec(**{**item, "peak": PeakRecord(**item["peak"])}) for item in items)


def spectrum_settings(dialog: object, baseline_only: bool, detail: dict) -> dict:
    """Capture choices and fit seeds, without copying measured result arrays."""
    baseline, detection, fit = dialog.baseline_result(), dialog.peak_result(), dialog.composite_result()
    reviewed = dialog.reviewed_peak_frame()
    original = list(detection.peaks) if detection else []
    decisions, retained = [], set()
    for row in reviewed.to_dict("records"):
        if row["manual_status"] == "added":
            decisions.append({"action": "add", "center": row["center"], "enabled": bool(row["enabled"])})
            continue
        match = next((index for index, peak in enumerate(original) if peak.row_index == row["row_index"] and peak.polarity == row["polarity"]), None)
        if match is None:
            raise ValueError("A reviewed peak cannot be linked to its detected candidate.")
        retained.add(match)
        peak = original[match]
        if row["manual_status"] != "automatic" or not row["enabled"]:
            decisions.append({"action": "review", "center": peak.center, "polarity": peak.polarity,
                              "target_center": row["center"], "enabled": bool(row["enabled"]),
                              "manual_status": row["manual_status"]})
    for index, peak in enumerate(original):
        if index not in retained:
            decisions.append({"action": "remove", "center": peak.center, "polarity": peak.polarity})
    values = dict(baseline_only=baseline_only, x_column=dialog.x_column(), y_column=dialog.y_column(),
                  baseline=baseline.parameters.to_dict(), detection=detection.parameters.to_dict() if detection else None,
                  fit=fit.parameters.to_dict() if fit else None,
                  components=[asdict(spec) for spec in dialog.component_specs()] if fit else [],
                  analysis_range=dialog.analysis_range(), coordinates=dialog.preview_coordinates(),
                  review=decisions, tolerance=dialog.center_tolerance(), detail=deepcopy(detail),
                  analysis_name=dialog.analysis_name(), profile=dialog.analysis_profile())
    for key, getter in (("signal_name", "result_sheet_name"), ("peak_name", "peak_sheet_name"),
                        ("fit_name", "fit_sheet_name"), ("parameter_name", "fit_parameter_sheet_name")):
        enabled = dialog.create_signal_output() if key == "signal_name" else dialog.create_peak_output() if key == "peak_name" else dialog.create_fit_output() and fit is not None
        values[key] = getattr(dialog, getter)() if enabled else None
    return values


def reviewed_peaks(baseline: object, detection: object, settings: dict, sheet: Dataset) -> pd.DataFrame:
    rows = [{**peak.to_dict(), "enabled": True} for peak in detection.peaks] if detection else []
    used = set()
    for decision in settings.get("review", []):
        center = decision["center"]
        if decision["action"] == "add":
            valid = np.flatnonzero(np.isfinite(baseline.x) & np.isfinite(baseline.corrected))
            if not len(valid):
                raise ValueError("Cannot add a reviewed peak to an empty spectrum.")
            index = int(valid[np.argmin(np.abs(baseline.x[valid]-center))])
            x, height = float(baseline.x[index]), float(baseline.corrected[index])
            peak = PeakRecord(sheet.name, settings["y_column"], index, x, "positive" if height >= 0 else "negative",
                              float(baseline.raw[index]), height, np.nan, np.nan, x, x, x, x, np.nan, np.nan,
                              0., np.nan, "manual", "added", tuple(settings.get("coordinates", {}).items()))
            rows.append({**peak.to_dict(), "enabled": decision["enabled"]})
            continue
        candidates = [index for index, row in enumerate(rows) if index not in used and row["polarity"] == decision["polarity"]]
        if not candidates:
            raise ValueError(f"Reviewed peak near {center} was not detected in the replay data.")
        index = min(candidates, key=lambda i: abs(rows[i]["center"]-center))
        if abs(rows[index]["center"]-center) > settings.get("tolerance", 0.):
            raise ValueError(f"Reviewed peak near {center} is outside the recorded matching tolerance.")
        used.add(index)
        if decision["action"] == "remove":
            rows[index]["_removed"] = True
        else:
            rows[index].update(center=decision["target_center"], enabled=decision["enabled"], manual_status=decision["manual_status"])
    frame = pd.DataFrame([{key: value for key, value in row.items() if key != "_removed"} for row in rows if not row.get("_removed")])
    if frame.empty:
        frame = detection.peak_frame().iloc[:0].copy() if detection else pd.DataFrame()
        frame["enabled"] = pd.Series(dtype=bool)
    return frame.sort_values("center", ignore_index=True) if "center" in frame else frame


class SpectralApi:
    workspace: Workspace

    def spectrum(self, sheet: Dataset, *, settings: dict) -> SimpleNamespace:
        """Recompute baseline, candidates, reviewed fit and optional worksheets."""
        options = deepcopy(settings)
        sheet.sync_column_metadata_attrs()
        request = SpectralPreviewRequest(
            "fit" if options.get("fit") else "peaks" if options.get("detection") else "baseline",
            SpectralSource(sheet.name, sheet.frame.copy()), options["x_column"], options["y_column"],
            options.get("coordinates", {}), options.get("analysis_range"), BaselineParameters(**options["baseline"]),
            PeakDetectionParameters(**options["detection"]) if options.get("detection") else None,
            CompositeFitParameters(**options["fit"]) if options.get("fit") else None,
            components_from_dict(options.get("components", [])),
        )
        result = prepare_spectral_preview(JobContext(Event(), lambda _: None), request)
        peak_frame = reviewed_peaks(result.baseline, result.peaks, options, sheet)
        getters = {key: options.get(key) for key in ("x_column", "y_column", "analysis_name")}
        getters.update(analysis_profile=options.get("profile", {}), reviewed_peak_frame=peak_frame,
                       result_sheet_name=options.get("signal_name"), peak_sheet_name=options.get("peak_name"),
                       fit_sheet_name=options.get("fit_name"), fit_parameter_sheet_name=options.get("parameter_name"),
                       create_signal_output=options.get("signal_name") is not None,
                       create_peak_output=options.get("peak_name") is not None,
                       create_fit_output=options.get("fit_name") is not None)
        adapter = SimpleNamespace(**{key: (lambda value=value: value) for key, value in getters.items()})
        detail = options.get("detail", {})
        detail.update({"Baseline iterations": str(result.baseline.iterations), "Baseline converged": str(result.baseline.converged),
                       "Baseline warnings": " | ".join(result.baseline.warnings)})
        if result.peaks:
            detail["Noise estimate"] = f"{result.peaks.noise_estimate:.12g}"
        if result.fit:
            for key, value in (("R squared", result.fit.r_squared), ("RMSE", result.fit.rmse), ("AIC", result.fit.aic), ("BIC", result.fit.bic)):
                detail["Composite "+key] = f"{value:.12g}"
        return publish_spectrum(self.workspace, sheet, adapter, result.baseline, result.peaks, result.fit,
                                options.get("baseline_only", False), options.get("coordinates", {}), detail,
                                "Baseline Correction" if options.get("baseline_only") else "Peak Analysis")

    def analysis(self, name: str) -> SpectralAnalysisSession:
        return self.workspace.get_spectral_analysis(name)

    def duplicate_analysis(self, analysis: SpectralAnalysisSession) -> SpectralAnalysisSession:
        return self.workspace.duplicate_spectral_analysis(analysis.name)

    def delete_analysis(self, analysis: SpectralAnalysisSession) -> None:
        self.workspace.remove_spectral_analysis(analysis.name)

    def export_analysis_table(self, analysis: SpectralAnalysisSession, *, table: str, name: str) -> Dataset:
        if table not in {"metrics", "curves", "parameters", "peaks"}:
            raise ValueError(f"Unknown analysis table: {table}")
        output = self.workspace.add_dataset(name, getattr(analysis, table+"_frame").copy(), copy_frame=False)
        output.worksheet_metadata.import_details.update({"Operation": "Spectral Analysis Export", "Analysis": analysis.name,
                                                         "Source worksheet": analysis.source_dataset, "Internal result": table})
        for coordinate, role in zip(analysis.coordinate_columns, ("x", "y")):
            if coordinate in output.frame:
                output.metadata_for_column(coordinate).role = role
                output.metadata_for_column(coordinate).value_type = "numeric"
        output.sync_column_metadata_attrs()
        set_dataset_operation_comments(output, f"Exported from spectral analysis {analysis.name}; source={analysis.source_dataset}")
        return output
