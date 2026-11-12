"""Recorder bindings between a demonstration and reusable macro inputs/results."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

from core.workspace import Dataset, SavedPlot
from models.macro import ColumnRef, Macro, MacroStep, XY_TYPES


class MacroRecorder:
    def __init__(self, name: str, source: Dataset | None) -> None:
        self.macro = Macro(name)
        self.bindings: dict[tuple[str, str], ColumnRef] = {}
        self.snapshots: dict[str, Dataset] = {}
        self.root: str | None = None
        if source is not None:
            self.adopt(source)

    def gap(self, message: str) -> None:
        if message not in self.macro.issues:
            self.macro.issues.append(message)

    def adopt(self, source: Dataset) -> None:
        if self.root is None:
            self.root = source.name
            self.bindings.update({(source.name, str(column)): ColumnRef("source", str(column)) for column in source.frame.columns})
            self.remember(source)

    def remember(self, source: Dataset) -> None:
        self.snapshots[source.name] = deepcopy(source)

    def check(self, source: Dataset) -> None:
        self.adopt(source)
        before = self.snapshots.get(source.name)
        if before is None:
            self.gap(f"'{source.name}' is outside the recorded source/result chain.")
        elif (not before.frame.equals(source.frame) or before.column_metadata != source.column_metadata):
            self.gap(f"Unrecorded data or metadata changes in '{source.name}'. Start a new recording from the intended inputs.")

    def ref(self, dataset: str, column: str) -> ColumnRef:
        try:
            return self.bindings[dataset, column]
        except KeyError:
            raise ValueError(f"Unrecorded dependency: {dataset} / {column}") from None

    def step(self, operation: str, settings: dict, inputs: dict[str, ColumnRef]) -> MacroStep:
        key = f"step{len(self.macro.steps)+1}"
        step = MacroStep(key, operation, deepcopy(settings), inputs)
        self.macro.steps.append(step)
        return step

    def smooth(self, source: Dataset, x: str, y: str, method: str, parameters: object, result_column: str) -> None:
        step = self.step("smooth", {"method": method, "parameters": asdict(parameters), "output_column": result_column},
                         {"x": self.ref(source.name, x), "y": self.ref(source.name, y)})
        self.bindings[source.name, result_column] = ColumnRef(step.key, "y")
        self.remember(source)

    def fit(self, source: Dataset, inputs: dict[str, str], settings: dict, fit: Dataset, residuals: Dataset | None) -> None:
        step = self.step("fit", settings, {key: self.ref(source.name, column) for key, column in inputs.items() if column})
        for output, alias in ((fit, step.key), (residuals, step.key+".residuals")):
            if output is not None:
                self.bindings.update({(output.name, str(column)): ColumnRef(alias, str(column)) for column in output.frame.columns})
                self.remember(output)

    def plot(self, plot: SavedPlot) -> None:
        state = deepcopy(plot.state)
        if not state.get("series"):
            if state.get("kind"):
                self.gap("Comparison recording is not yet supported; record ordinary XY plots.")
            return
        for series in state["series"]:
            if series.get("plot_type", "line") not in XY_TYPES:
                raise ValueError("Only line, scatter, line+marker, and errorbar plots can currently be recorded.")
            for axis in ("x", "y"):
                dataset = series[axis+"_dataset"]
                central = self.ref(dataset, series[axis+"_column"])
                columns = [axis+"_column", axis+"_err_column"]
                if axis == "y":
                    columns += ["lower_column", "upper_column"]
                for key in columns:
                    if series.get(key):
                        ref = self.ref(dataset, series[key])
                        if ref.table != central.table:
                            raise ValueError("Plot errors/bands must belong to the same recorded result as their central values.")
                        series[key] = ref.column
                bounds = series.get(axis+"_bounds")
                if bounds:
                    for key in ("lower_column", "upper_column"):
                        ref = self.ref(dataset, bounds[key])
                        if ref.table != central.table:
                            raise ValueError("Transformed plot bounds need an explicit propagation rule.")
                        bounds[key] = ref.column
                series[axis+"_dataset"] = central.table
        self.step("plot", {"name": plot.name, "state": state}, {})
