"""Detached, per-source transactional macro execution using existing math engines."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import tempfile
import time
from uuid import uuid4

import pandas as pd

from core.file_io import ImportOptions
from core.import_jobs import inspect_text_files, prepare_text_files
from core.jobs import JobCancelled, JobContext
from core.workspace import ColumnMetadata, Dataset, set_dataset_operation_comments
from math_engine.calculus import validate_numeric_column_metadata
from math_engine.curve_fitting import fit_curve
from math_engine.smoothing import SmoothingParameters, smooth_column
from models.fit_functions import CustomFitModel, get_fit_model
from models.macro import ColumnRef, Macro, MacroStep
from models.uncertainty import PercentileBounds


@dataclass
class MacroSource:
    key: str
    name: str
    dataset: Dataset | None = None
    path: Path | None = None
    file_signature: tuple[int, int] | None = None


@dataclass
class MacroOutput:
    source: MacroSource
    tables: dict[str, Dataset]
    plots: list[tuple[str, dict[str, object]]]
    rows: list[dict[str, object]]


@dataclass
class MacroRun:
    """Written only by the worker; read by the GUI after thread termination."""
    outputs: list[MacroOutput] = field(default_factory=list)
    rows: list[dict[str, object]] = field(default_factory=list)
    cancelled: bool = False


class MacroStepFailure(ValueError):
    def __init__(self, step: MacroStep, message: str) -> None:
        super().__init__(f"{step.key} ({step.operation}): {message}")
        self.step = step


def folder_sources(folder: Path, recursive: bool = False) -> list[MacroSource]:
    """Discover supported files deterministically; do not follow directory symlinks."""
    folder = folder.resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("Choose a folder containing data files.")
    paths = folder.rglob("*") if recursive else folder.iterdir()
    return [MacroSource(str(path.resolve()), path.stem, path=path)
            for path in sorted(paths, key=lambda value: str(value).casefold())
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".csv", ".dat", ".txt"}
            and not any(part.startswith("jasc_macro_run_") for part in path.relative_to(folder).parts)]


def _load(context: JobContext, source: MacroSource, macro: Macro) -> Dataset:
    if source.dataset is not None:
        result = deepcopy(source.dataset)
    else:
        before = source.path.stat()
        signature = before.st_size, before.st_mtime_ns
        if source.file_signature is not None and source.file_signature != signature:
            raise ValueError("Source file changed since compatibility preview; preview it again.")
        source.file_signature = signature
        options = ImportOptions(**macro.import_options)
        inspection = inspect_text_files(context, [source.path], options)
        prepared = prepare_text_files(context, [source.path], inspection, options, "keep")
        if prepared.errors or not prepared.files:
            raise ValueError("; ".join(prepared.errors) or "No data were read.")
        item = prepared.files[0]
        result = Dataset(source.name, item.frame, source.path, worksheet_metadata=item.metadata)
        after = source.path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Source file changed while reading.")
    result.sync_column_metadata_attrs()
    return result


def _schema(macro: Macro, dataset: Dataset) -> None:
    schemas = {"source": set(map(str, dataset.frame.columns))}
    for step in macro.steps:
        for ref in step.inputs.values():
            if ref.column not in schemas[ref.table]:
                raise ValueError(f"{step.key}: missing column '{ref.column}' in {ref.table}.")
            if ref.table == "source":
                numeric = pd.to_numeric(dataset.frame[ref.column], errors="coerce")
                validate_numeric_column_metadata(dataset.frame, ref.column, numeric)
        if step.operation == "smooth":
            SmoothingParameters(**step.settings["parameters"])
            schemas[step.key] = {"x", "y"}
        elif step.operation == "fit":
            custom = [CustomFitModel.from_metadata(item) for item in step.settings.get("custom_models", [])]
            get_fit_model(step.settings["model_key"], custom)
            if step.inputs["y"].table != "source" and ("weight" in step.inputs or step.settings.get("y_bounds")):
                raise ValueError("Transformed Y needs an explicit uncertainty propagation rule before weighted fitting.")
            schemas[step.key] = {"fit_x", "fit_y", "fit_lower", "fit_upper"}
            schemas[step.key+".residuals"] = {"x", "observed", "fitted", "residual", "standardized_residual"}
        else:
            for series in step.settings["state"]["series"]:
                for axis in ("x", "y"):
                    columns = [series[axis+"_column"]]
                    columns += [series.get(axis+"_err_column", "")]
                    bounds = series.get(axis+"_bounds")
                    if bounds:
                        columns += [bounds["lower_column"], bounds["upper_column"]]
                    if axis == "y":
                        columns += [series.get("lower_column", ""), series.get("upper_column", "")]
                    for column in filter(None, columns):
                        if column not in schemas[series[axis+"_dataset"]]:
                            raise ValueError(f"{step.key}: missing plotted column '{column}'.")
                        if series[axis+"_dataset"] == "source":
                            numeric = pd.to_numeric(dataset.frame[column], errors="coerce")
                            validate_numeric_column_metadata(dataset.frame, column, numeric)


def preflight_macro(context: JobContext, macro: Macro, sources: list[MacroSource]) -> list[dict[str, object]]:
    macro.validate(runnable=True)
    rows = []
    for index, source in enumerate(sources):
        context.report(index, len(sources), f"Checking {source.name}")
        try:
            data = _load(context, source, macro)
            _schema(macro, data)
            rows.append({"source": source.name, "key": source.key, "status": "ready", "details": f"{len(data.frame)} rows"})
        except JobCancelled:
            raise
        except Exception as exc:
            rows.append({"source": source.name, "key": source.key, "status": "skipped", "details": str(exc)})
    context.check_cancelled()
    return rows


def _frame(tables: dict[str, Dataset], inputs: dict[str, ColumnRef]) -> pd.DataFrame:
    """Align referenced columns by original row identity, never by display names."""
    data = {name: tables[ref.table].frame[ref.column] for name, ref in inputs.items()}
    lengths = {len(value) for value in data.values()}
    indexes = [value.index for value in data.values()]
    if len(lengths) != 1 or any(not indexes[0].equals(index) for index in indexes[1:]):
        raise ValueError("Macro inputs have different row identities or lengths.")
    result = pd.DataFrame(data)
    result.attrs["jasc_column_metadata"] = {
        name: tables[ref.table].column_metadata.get(ref.column, ColumnMetadata()).to_metadata()
        for name, ref in inputs.items()}
    return result


def _execute(context: JobContext, macro: Macro, source: MacroSource) -> MacroOutput:
    data = _load(context, source, macro)
    _schema(macro, data)
    tables, plots, rows = {"source": data}, [], []
    for position, step in enumerate(macro.steps):
        context.report(position, len(macro.steps), f"{source.name}: {step.operation} ({position+1}/{len(macro.steps)})")
        start = time.perf_counter()
        try:
            metrics = {}
            if step.operation == "plot":
                plots.append((step.key, deepcopy(step.settings["state"])))
            else:
                frame = _frame(tables, step.inputs)
                if step.operation == "smooth":
                    smooth_column(frame, "x", "y", step.settings["method"], "result", SmoothingParameters(**step.settings["parameters"]))
                    output = frame[["x", "result"]].rename(columns={"result": "y"})
                    tables[step.key] = Dataset(f"{source.name}_{step.settings['output_column']}", output)
                    tables[step.key].column_metadata = {
                        name: deepcopy(tables[step.inputs[name].table].column_metadata.get(step.inputs[name].column, ColumnMetadata()))
                        for name in ("x", "y")}
                    tables[step.key].sync_column_metadata_attrs()
                else:
                    settings = deepcopy(step.settings)
                    custom = [CustomFitModel.from_metadata(item) for item in settings.pop("custom_models", [])]
                    for axis in ("x", "y"):
                        bounds = settings.get(axis+"_bounds")
                        if bounds:
                            bounds["lower_column"], bounds["upper_column"] = axis+"_lower", axis+"_upper"
                            settings[axis+"_bounds"] = PercentileBounds.from_state(bounds)
                    result = fit_curve(frame, "x", "y", custom_models=custom,
                                       weight_column="weight" if "weight" in step.inputs else None,
                                       x_weight_column="x_weight" if "x_weight" in step.inputs else None,
                                       check_cancelled=context.check_cancelled, **settings)
                    tables[step.key] = Dataset(f"{source.name}_{step.key}_fit", result.fit_frame)
                    tables[step.key+".residuals"] = Dataset(f"{source.name}_{step.key}_residuals", result.residual_frame)
                    for key in (step.key, step.key+".residuals"):
                        tables[key].worksheet_metadata.fields += [("Fit report", result.report.to_text()), ("Macro", macro.name)]
                    metrics = {**dict(zip(result.report.parameter_names, result.report.parameters)),
                               **{name+"_error": value for name, value in zip(result.report.parameter_names, result.report.standard_errors)},
                               "r_squared": result.report.r_squared, "rmse": result.report.rmse,
                               "warnings": "; ".join(result.report.warnings)}
                set_dataset_operation_comments(tables[step.key], f"Macro {macro.name}: {step.operation} ({step.key})")
        except JobCancelled:
            raise
        except Exception as exc:
            raise MacroStepFailure(step, str(exc)) from exc
        context.check_cancelled()
        rows.append({"source": source.name, "source_key": source.key, "step": step.key, "operation": step.operation,
                     "status": "ok", "details": "", "elapsed_seconds": time.perf_counter()-start, **metrics})
    return MacroOutput(source, tables, plots, rows)


def run_macro(context: JobContext, macro: Macro, sources: list[MacroSource], result: MacroRun) -> MacroRun:
    """Only complete sources enter result; a failed/cancelled source publishes nothing."""
    macro.validate(runnable=True)
    for index, source in enumerate(sources):
        try:
            context.report(index, len(sources), f"Processing {source.name}")
            output = _execute(context, macro, source)
            context.check_cancelled()
            result.outputs.append(output)
            result.rows.extend(output.rows)
        except JobCancelled:
            result.cancelled = True
            result.rows.extend({"source": pending.name, "source_key": pending.key, "step": "", "operation": "",
                                "status": "cancelled", "details": "Cancelled before completion."}
                               for pending in sources[index:])
            break
        except Exception as exc:
            step = getattr(exc, "step", None)
            result.rows.append({"source": source.name, "source_key": source.key,
                                "step": step.key if step else "", "operation": step.operation if step else "",
                                "status": "failed", "details": str(exc)})
    return result


def export_macro_tables(context: JobContext, macro: Macro, result: MacroRun, folder: Path) -> Path:
    """Stage CSVs/provenance, then publish one new directory without overwrites."""
    destination = folder / ("jasc_macro_run_" + uuid4().hex[:12])
    with tempfile.TemporaryDirectory(prefix=".jasc-macro-", dir=folder) as temporary:
        staging = Path(temporary) / "results"
        staging.mkdir()
        for index, output in enumerate(result.outputs):
            if any(row["status"] != "ok" for row in output.rows):
                continue
            context.report(index, len(result.outputs), f"Exporting {output.source.name}")
            for alias, table in output.tables.items():
                table.frame.to_csv(staging / f"source_{index+1:04d}_{alias}.csv", index=False)
        context.check_cancelled()
        pd.DataFrame(result.rows).to_csv(staging / "run_summary.csv", index=False)
        (staging / "macro.jasc-macro.json").write_text(json.dumps(macro.to_state(), indent=2), encoding="utf-8")
        context.check_cancelled()
        os.replace(staging, destination)
    return destination
