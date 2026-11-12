"""Chronological, readable Python call recording for the public JASC API."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import pandas as pd

from core.workspace import Dataset, SavedPlot, Workspace


@dataclass(frozen=True)
class Expression:
    """A recorder-owned variable reference, never user-entered Python text."""
    text: str


def literal(value: object) -> str:
    if isinstance(value, Expression):
        return value.text
    if isinstance(value, dict):
        if not value:
            return "{}"
        entries = [f"{literal(key)}: {literal(item)}" for key, item in value.items()]
        return "{\n" + "".join("    "+entry.replace("\n", "\n    ")+",\n" for entry in entries)+"}"
    if isinstance(value, (list, tuple)):
        items = ", ".join(literal(item) for item in value)
        return "["+items+"]" if isinstance(value, list) else "("+items+("," if len(value) == 1 else "")+")"
    if isinstance(value, Path):
        return repr(str(value))
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return f"float({str(value)!r})"
    if value is None or isinstance(value, (str, bool, int, float)):
        return repr(value)
    raise ValueError(f"This parameter type is not yet recordable: {type(value).__name__}")


def fingerprint(dataset: Dataset) -> str:
    """Detect unrecorded input edits without retaining additional full sheet copies."""
    digest = hashlib.sha256()
    digest.update(dataset.name.encode())
    digest.update(repr(list(dataset.frame.columns)).encode())
    try:
        digest.update(pd.util.hash_pandas_object(dataset.frame, index=True).values.tobytes())
    except TypeError:
        digest.update(dataset.frame.to_csv(index=True).encode())
    digest.update(json.dumps({column: item.to_metadata() for column, item in dataset.column_metadata.items()
                              if not item.is_empty()}, sort_keys=True).encode())
    return digest.hexdigest()


class ApiRecording:
    def __init__(self, name: str, workspace: Workspace) -> None:
        self.name = name
        self.calls: list[str] = []
        self.issues: list[str] = []
        self.bindings: dict[int, Expression] = {}
        self.sheets: dict[int, Dataset] = {id(item): item for item in workspace.list_datasets()}
        self.fit_results: dict[int, tuple[object, Expression]] = {}
        self.summary_rows: dict[int, tuple[object, Expression]] = {}
        self.summary_calls: dict[str, Expression] = {}
        self.used_summary_rows: set[Expression] = set()
        self.analysis_bindings: dict[int, Expression] = {}
        self.initial_analyses = {id(item): item.name for item in workspace.list_spectral_analyses()}
        self.known_analyses = set(self.initial_analyses)
        self.large_bindings: dict[int, Expression] = {}
        self.initial_large = {id(item): item.name for item in workspace.list_large_datasets()}
        self.known_large = set(self.initial_large)
        self.expected: dict[int, str] = {id(item): fingerprint(item) for item in workspace.list_datasets()}
        self.initial_names = {id(item): item.name for item in workspace.list_datasets()}
        self.initial_plots = {item.plot_id: item.name for item in workspace.list_plots()}
        self.deleted_plots: set[str] = set()
        self.plots: dict[str, tuple[Expression, dict[str, object]]] = {}
        self.plot_names: dict[str, str] = {}
        self.counter = 0

    def gap(self, message: str) -> None:
        if message not in self.issues:
            self.issues.append(message)

    def variable(self, prefix: str) -> Expression:
        self.counter += 1
        return Expression(f"{prefix}{self.counter}")

    def call(self, api_method: str, args: list[object] | None = None, *, assign_to: Expression | None = None,
             **settings: object) -> None:
        arguments = [literal(arg) for arg in (args or [])]
        arguments += [f"{key}={literal(value)}" for key, value in settings.items()]
        code = (assign_to.text+" = " if assign_to else "") + "session."+api_method+"(\n"
        code += "".join("    "+argument.replace("\n", "\n    ")+",\n" for argument in arguments)+")"
        ast.parse(code)
        self.calls.append(code)

    def before(self, source: Dataset) -> None:
        expected = self.expected.get(id(source))
        if expected is None:
            self.gap(f"Unrecorded creation of worksheet '{source.name}'.")
        elif expected != fingerprint(source):
            self.gap(f"Unrecorded edits or operations on worksheet '{source.name}'.")
        self.ref(source)

    def remember(self, source: Dataset) -> None:
        self.expected[id(source)] = fingerprint(source)
        self.sheets[id(source)] = source

    def ref(self, source: Dataset) -> Expression:
        expression = self.bindings.get(id(source))
        if expression is None:
            expression = self.variable("sheet")
            self.call("sheet", [self.initial_names.get(id(source), source.name)], assign_to=expression)
            self.bindings[id(source)] = expression
            if id(source) not in self.initial_names:
                self.gap(f"Worksheet '{source.name}' was produced by an unrecorded operation.")
        return expression

    def imported(self, source: Dataset, options: object, pattern_choice: str = "keep") -> None:
        expression = self.variable("sheet")
        self.call("load", [str(source.source_path)], assign_to=expression, name=source.name,
                  pattern_choice=pattern_choice, **asdict(options))
        self.bindings[id(source)] = expression
        self.remember(source)

    def smoothed(self, source: Dataset, x: str, y: str, method: str, parameters: object, column: str) -> None:
        self.call("smooth", [self.ref(source)], x_column=x, y_column=y, method=method,
                  output_column=column, **asdict(parameters))
        self.remember(source)

    def fitted(self, source: Dataset, inputs: dict[str, str], settings: dict[str, object],
               curve: Dataset, residuals: Dataset | None, engine_result: object = None) -> None:
        result = self.variable("fit")
        self.call("fit", [self.ref(source)], assign_to=result,
                  x_column=inputs["x"], y_column=inputs["y"],
                  x_weight_column=inputs.get("x_weight"), weight_column=inputs.get("weight"),
                  curve_name=curve.name, residual_name=residuals.name if residuals else None,
                  create_residuals=residuals is not None, **settings)
        self.bindings[id(curve)] = Expression(result.text+".curve")
        self.remember(curve)
        if residuals is not None:
            self.bindings[id(residuals)] = Expression(result.text+".residuals")
            self.remember(residuals)
        self.remember(source)
        if engine_result is not None:
            self.fit_results[id(engine_result)] = (engine_result, result)

    def summary_row(self, helper: str, parameters: dict[str, object], value: object) -> None:
        from core.api_summary_api import SUMMARY_METHODS, DIALOG_GETTERS
        kind = "fit_report" if helper == "fit_report" else next(key for key, name in SUMMARY_METHODS.items() if name == helper)
        options = dict(parameters)
        for key, item in options.items():
            if isinstance(item, Dataset):
                self.before(item)
                options[key] = self.ref(item)
            elif key == "dialog" and item is not None:
                options[key] = {name: getattr(item, name)() for name in DIALOG_GETTERS[kind]}
            elif isinstance(item, pd.DataFrame):
                name = str(parameters.get("output_sheet", ""))
                sheet = next((sheet for sheet in self.sheets.values() if sheet.name == name), None)
                if sheet is None:
                    raise ValueError("Summary result has no recorded output worksheet.")
                options[key] = Expression(self.ref(sheet).text+".frame")
            elif key == "result" and item is not None:
                options[key] = self.fit_results[id(item)][1]
        # Counts must follow replayed columns when the number of source rows changes.
        source = parameters.get("dataset")
        if kind == "smooth" and parameters.get("status") == "ok":
            name = parameters["plan_row"]["source_sheet"]
            sheet = next((sheet for sheet in self.sheets.values() if sheet.name == name), None)
            if sheet is None:
                raise ValueError("Smoothing summary source has no recorded worksheet.")
            column = parameters["result_column"]
            options["values_written"] = Expression(f"int({self.ref(sheet).text}.frame[{column!r}].notna().sum())")
        if parameters.get("status") == "ok" and isinstance(source, Dataset):
            column = parameters.get("result_column", parameters.get("result_target_column", ""))
            if "values_written" in options:
                options["values_written"] = Expression(f"int({self.ref(source).text}.frame[{column!r}].notna().sum())")
            # A full-sheet formula normally writes every row; selected rows keep their count.
            if options.get("updated_rows") == len(source.frame):
                options["updated_rows"] = Expression(f"len({self.ref(source).text}.frame)")
        expression = self.variable("rows" if isinstance(value, list) else "row")
        self.call("result_row", [kind], assign_to=expression, **options)
        self.summary_calls[self.calls[-1]] = expression
        for row in value if isinstance(value, list) else [value]:
            self.summary_rows[id(row)] = (row, expression)

    def collected(self, output: Dataset, rows: list[dict], wide: bool = False) -> None:
        expressions = []
        for row in rows:
            entry = self.summary_rows.get(id(row))
            if entry is None:
                raise ValueError("A batch result row has no recorded computation.")
            if entry[1] not in expressions:
                expressions.append(entry[1])
        expression = self.variable("sheet")
        comments = next(iter(output.column_metadata.values()), None)
        operation = comments.comment.removeprefix("Operation: ") if comments else ""
        self.call("collect_rows", assign_to=expression, name=output.name, rows=expressions,
                  wide=wide, operation=operation)
        self.used_summary_rows.update(expressions)
        self.bindings[id(output)] = expression
        self.remember(output)

    def column_math(self, source: Dataset, operation: str, x: str, y: str, method: str,
                    column: str, initial: float | None) -> None:
        settings = {"x_column": x, "y_column": y, "method": method, "output_column": column}
        if operation == "integral":
            settings["initial_value"] = initial if initial is not None else 0.
        self.call(operation, [self.ref(source)], **settings)
        self.remember(source)

    def transformed(self, source: Dataset, operation: str, settings: dict[str, object], output: Dataset) -> None:
        result = self.variable("sheet")
        self.call(operation, [self.ref(source)], assign_to=result, name=output.name, **settings)
        self.bindings[id(output)] = result
        self.remember(source)
        self.remember(output)

    def formula(self, source: Dataset, column: str, expression: str, rows: list[int] | None) -> None:
        self.call("formula", [self.ref(source)], output_column=column, expression=expression, row_positions=rows)
        self.remember(source)

    def result(self, method: str, source: Dataset, settings: dict[str, object], output: Dataset,
               other_inputs: dict[str, Dataset] | None = None) -> None:
        inputs = other_inputs or {}
        for item in [source, *inputs.values()]:
            self.before(item)
        settings = dict(settings)
        if method in {"prepare", "statistics", "interpolate"}:
            metadata = ([output.column_metadata.get(str(settings.get("value_column"))+"_interpolated")]
                        if method == "interpolate" else output.column_metadata.values())
            operation = next((line.removeprefix("Operation: ") for entry in metadata if entry is not None
                              for line in entry.comment.splitlines() if line.startswith("Operation: ")), None)
            if operation:
                settings["operation_comment"] = operation
        expression = self.variable("sheet")
        self.call(method, [self.ref(source)], assign_to=expression, name=output.name,
                  **{key: self.ref(value) for key, value in inputs.items()}, **settings)
        self.bindings[id(output)] = expression
        self.remember(output)

    def spectral(self, method: str, sources: list[Dataset], settings: dict, outputs: list[Dataset], analysis: object) -> None:
        for source in sources:
            self.before(source)
        expression = self.variable("spectral")
        args = [self.ref(sources[0])] if method == "spectrum" else [[self.ref(source) for source in sources]]
        self.call(method, args, assign_to=expression, settings=settings)
        for index, output in enumerate(outputs):
            self.bindings[id(output)] = Expression(f"{expression.text}.sheets[{index}]")
            self.remember(output)
        if analysis is not None:
            self.analysis_bindings[id(analysis)] = Expression(expression.text+".analysis")
            self.known_analyses.add(id(analysis))

    def analysis_ref(self, analysis: object) -> Expression:
        identity = id(analysis)
        if identity not in self.analysis_bindings:
            if identity not in self.initial_analyses:
                raise ValueError("This spectral analysis was created by an unrecorded operation.")
            expression = self.variable("analysis")
            self.call("analysis", [self.initial_analyses[identity]], assign_to=expression)
            self.analysis_bindings[identity] = expression
        return self.analysis_bindings[identity]

    def analysis_table(self, analysis: object, table: str, output: Dataset) -> None:
        expression = self.variable("sheet")
        self.call("export_analysis_table", [self.analysis_ref(analysis)], assign_to=expression, table=table, name=output.name)
        self.bindings[id(output)] = expression
        self.remember(output)

    def large_ref(self, source: object) -> Expression:
        if id(source) not in self.large_bindings:
            if id(source) not in self.initial_large:
                raise ValueError("Large-data source was not imported while recording.")
            expression = self.variable("large")
            self.call("large_sheet", [self.initial_large[id(source)]], assign_to=expression)
            self.large_bindings[id(source)] = expression
        return self.large_bindings[id(source)]

    def edited(self, source: Dataset, operation: str, parameters: dict[str, object]) -> None:
        self.call("edit", [self.ref(source)], operation=operation, parameters=parameters)
        self.remember(source)

    def new_sheet(self, source: Dataset) -> None:
        expression = self.variable("sheet")
        self.call("new_sheet", assign_to=expression, name=source.name, rows=len(source.frame))
        self.bindings[id(source)] = expression
        self.remember(source)

    def renamed_sheet(self, source: Dataset, old_name: str) -> None:
        if id(source) not in self.bindings:
            expression = self.variable("sheet")
            self.call("sheet", [old_name], assign_to=expression)
            self.bindings[id(source)] = expression
        self.call("rename_sheet", [self.ref(source), source.name])
        self.remember(source)

    def deleted_sheet(self, source: Dataset) -> None:
        self.call("delete_sheet", [self.ref(source)])
        self.expected.pop(id(source), None)

    def finish(self, workspace: Workspace) -> None:
        self.plot_deletions(workspace)
        if {id(item) for item in workspace.list_spectral_analyses()} - self.known_analyses:
            self.gap("A spectral analysis was produced without an API recording.")
        if {id(item) for item in workspace.list_large_datasets()} != self.known_large:
            self.gap("A large-data import or removal was not recorded.")
        current_ids = {id(source) for source in workspace.list_datasets()}
        for source in workspace.list_datasets():
            if id(source) not in self.expected:
                self.gap(f"Worksheet '{source.name}' was produced by an operation without an API recorder.")
            elif self.expected[id(source)] != fingerprint(source):
                self.gap(f"Unrecorded changes in worksheet '{source.name}'.")
        if self.expected.keys() - current_ids:
            self.gap("Worksheet deletion is not yet recorded as an API call.")

    def plot_deletions(self, workspace: Workspace) -> None:
        removed = (self.plots.keys() | self.initial_plots.keys()) - {plot.plot_id for plot in workspace.list_plots()} - self.deleted_plots
        for identity in sorted(removed):
            if identity in self.plots:
                expression = self.plots[identity][0]
            else:
                expression = self.variable("plot")
                self.call("plot_by_name", [self.initial_plots[identity]], assign_to=expression)
            self.call("delete_plot", [expression])
            self.deleted_plots.add(identity)

    def series_expression(self, item: dict, workspace: Workspace) -> Expression:
        appearance = {key: value for key, value in item.items()
                      if key not in {"x_dataset", "y_dataset", "x_column", "y_column", "z_dataset", "z_column"}}
        # Keep only nondefault series appearance to make scripts readable.
        from ui.plot_canvas import PlotSeries
        defaults = asdict(PlotSeries("", "", "", ""))
        appearance = {key: value for key, value in appearance.items() if value != defaults.get(key)}
        arguments = []
        for axis in ("x", "y", "z"):
            if axis == "z" and not item.get("z_dataset"):
                continue
            source = workspace.get_dataset(item[axis+"_dataset"])
            self.before(source)
            arguments.append(axis+"="+literal((self.ref(source), item[axis+"_column"])))
        arguments += [key+"="+literal(value) for key, value in appearance.items()]
        return Expression("series("+", ".join(arguments)+")")

    def plotted(self, plot: SavedPlot, workspace: Workspace) -> None:
        state = deepcopy(plot.state)
        previous = self.plots.get(plot.plot_id)
        if previous and self.plot_names.get(plot.plot_id) != plot.name:
            self.call("rename_plot", [previous[0], plot.name])
            self.plot_names[plot.plot_id] = plot.name
        if previous and previous[1] == state:
            return
        if state.get("kind") == "plot_comparison":
            sources = []
            for identity in state["plot_ids"]:
                source = next((item for item in workspace.list_plots() if item.plot_id == identity), None)
                if source is None:
                    raise ValueError("Comparison sources must exist when recording their API calls.")
                if identity not in self.plots:
                    self.plotted(source, workspace)
                sources.append(self.plots[identity][0])
            layout = {key: state[key] for key in ("rows", "columns", "match_x", "match_y", "panel_labels")}
            expression = previous[0] if previous else self.variable("plot")
            if previous:
                self.call("update_comparison", [expression, sources], **layout)
            else:
                self.call("compare", [sources], assign_to=expression, name=plot.name, **layout)
            self.plots[plot.plot_id] = expression, state
            self.plot_names[plot.plot_id] = plot.name
            return
        if not state.get("series"):
            if state.get("kind"):
                self.gap("Comparison API recording is not implemented yet.")
            return
        recorded_series = []
        for item in state["series"]:
            recorded_series.append(self.series_expression(item, workspace))
        if previous:
            expression = previous[0]
            self.call("update_plot", [expression, recorded_series], settings=state.get("settings", {}), locators=state.get("locators", []))
        else:
            expression = self.variable("plot")
            if plot.plot_id in self.initial_plots:
                self.call("plot_by_name", [self.initial_plots[plot.plot_id]], assign_to=expression)
                if plot.name != self.initial_plots[plot.plot_id]:
                    self.call("rename_plot", [expression, plot.name])
                self.call("update_plot", [expression, recorded_series], settings=state.get("settings", {}), locators=state.get("locators", []))
            else:
                self.call("plot", [recorded_series], assign_to=expression, name=plot.name,
                          settings=state.get("settings", {}), locators=state.get("locators", []))
        self.plots[plot.plot_id] = expression, state
        self.plot_names[plot.plot_id] = plot.name

    def exported_plot(self, plot: SavedPlot, workspace: Workspace, path: str) -> None:
        self.plotted(plot, workspace)
        self.call("export_plot", [self.plots[plot.plot_id][0], path])

    def source(self) -> str:
        header = ("# JASC Python API recording (API version 1)\n"
                  "# Replay through JASC or python -m jasc_api; existing sheets need --project input.jasc.\n"
                  "from jasc_api import Session, series, launch_recording\n\n\ndef run(session):\n")
        body = []
        if self.issues:
            body.append("raise RuntimeError("+repr("Incomplete recording: "+"; ".join(self.issues))+")")
        body.extend(call for call in self.calls if call not in self.summary_calls
                    or self.summary_calls[call] in self.used_summary_rows)
        text = header + "\n\n".join("\n".join("    "+line for line in call.splitlines()) for call in body or ["pass"])
        text += '\n\n\nif __name__ == "__main__":\n    launch_recording(__file__)\n'
        ast.parse(text)
        return text

    def save(self, path: str | Path) -> None:
        path = Path(path)
        descriptor, name = tempfile.mkstemp(prefix=".jasc-api-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(self.source())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
