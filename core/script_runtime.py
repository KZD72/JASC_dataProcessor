"""Interpreter for validated recordings, with opaque, typed API result references."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import inspect
import math
from typing import Callable

from core.script_language import Program, ScriptError, METHODS, MAX_STEPS, column_count
from core.script_safety import FilePolicy, validate_math_text, validate_plot_settings, validate_workspace_plots


@dataclass(frozen=True)
class _Ref:
    kind: str
    value: object


DATASET_METHODS = frozenset({"sheet", "load", "load_excel", "new_sheet", "duplicate_sheet", "prepare", "fft", "ifft",
                            "statistics", "interpolate", "statistics_plot_data", "baseline_map", "export_analysis_table",
                            "collect_rows", "map_analysis", "extract_window"})
PLOT_METHODS = frozenset({"plot", "plot_by_name", "update_plot", "rename_plot", "compare", "update_comparison"})


class Interpreter:
    """No evaluation, importing, dynamic method lookup or Python object traversal."""
    def __init__(self, session: object, files: FilePolicy, progress: Callable[[int, str], None] | None = None) -> None:
        from jasc_api import Session
        self.session, self.files = session, files
        self.dispatch = {name: getattr(Session, name) for name in METHODS}
        self.variables: dict[str, object] = {}
        self.steps = 0
        self.progress = progress or (lambda *_: None)

    def run(self, program: Program) -> None:
        validate_workspace_plots(self.session.workspace)
        self.block(program.body)
        validate_workspace_plots(self.session.workspace)

    def tick(self, label: str) -> None:
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise ScriptError("The recording exceeds the 10,000 execution-step limit.")
        self.progress(self.steps, label)

    def block(self, body: tuple | list) -> None:
        for statement in body:
            self.tick("Recording")
            try:
                if isinstance(statement, ast.Assign):
                    self.variables[statement.targets[0].id] = self.expr(statement.value)
                elif isinstance(statement, ast.For):
                    items = self.expr(statement.iter)
                    if not isinstance(items, list) or len(items) > 256 or not all(isinstance(item, _Ref) and item.kind == "dataset" for item in items):
                        raise ScriptError("Repeat blocks can iterate over at most 256 worksheet references.")
                    for item in items:
                        self.variables[statement.target.id] = item
                        self.block(statement.body)
                elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                    self.expr(statement.value)
            except ScriptError as exc:
                raise ScriptError(f"Line {statement.lineno}: {exc}") from exc
            except Exception as exc:
                raise ScriptError(f"Line {statement.lineno}: {type(exc).__name__}: {exc}") from exc

    def expr(self, node: ast.AST) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self.variables[node.id]
        if isinstance(node, (ast.List, ast.Tuple)):
            items = [self.expr(item) for item in node.elts]
            return items if isinstance(node, ast.List) else tuple(items)
        if isinstance(node, ast.Dict):
            result = {}
            for key, value in zip(node.keys, node.values):
                actual = self.expr(key)
                if type(actual) not in {str, int, float, bool, type(None)}:
                    raise ScriptError("Dictionary keys must be scalar values.")
                result[actual] = self.expr(value)
            return result
        if isinstance(node, ast.UnaryOp):
            value = self.expr(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            left, right = self.expr(node.left), self.expr(node.right)
            if not isinstance(left, str) or not isinstance(right, str) or len(left)+len(right) > 1_000_000:
                raise ScriptError("Only bounded text concatenation is supported.")
            return left+right
        if isinstance(node, ast.Attribute):
            source = self.expr(node.value)
            if not isinstance(source, _Ref):
                raise ScriptError("Only named API result fields are readable.")
            if node.attr == "name" and source.kind in {"dataset", "plot", "analysis", "large"}:
                return source.value.name
            if node.attr == "frame" and source.kind == "dataset":
                return _Ref("frame", source.value.frame)
            if source.kind == "fit" and node.attr in {"curve", "residuals"}:
                value = source.value.curve if node.attr == "curve" else source.value.residuals
                return _Ref("dataset", value) if value is not None else None
            if source.kind == "spectral" and node.attr in {"sheets", "analysis"}:
                return ([_Ref("dataset", item) for item in source.value.sheets] if node.attr == "sheets" else
                        _Ref("analysis", source.value.analysis) if source.value.analysis is not None else None)
            raise ScriptError("This result does not expose that field.")
        if isinstance(node, ast.Subscript):
            items = self.expr(node.value)
            if not isinstance(items, (list, tuple)):
                raise ScriptError("Only bounded result collections can be indexed.")
            return items[node.slice.value]
        if isinstance(node, ast.Call):
            count = column_count(node)
            if count:
                frame, column = self.expr(count[0]), self.expr(count[1])
                if not isinstance(frame, _Ref) or frame.kind != "frame" or not isinstance(column, str):
                    raise ScriptError("Column counts need a worksheet frame and column name.")
                return int(frame.value[column].notna().sum())
            args = [self.expr(item) for item in node.args]
            kwargs = {item.arg: self.expr(item.value) for item in node.keywords}
            if isinstance(node.func, ast.Name):
                return self.helper(node.func.id, args, kwargs)
            return self.call(node.func.attr, args, kwargs)
        raise ScriptError("Invalid interpreter expression.")

    def helper(self, name: str, args: list, kwargs: dict) -> object:
        if name == "series":
            from jasc_api import series
            if args:
                raise ScriptError("series() takes named arguments.")
            for key in ("x", "y", "z"):
                if key not in kwargs and key == "z":
                    continue
                binding = kwargs.get(key)
                if not (isinstance(binding, (tuple, list)) and len(binding) == 2 and isinstance(binding[0], _Ref)
                        and binding[0].kind == "dataset" and isinstance(binding[1], str)):
                    raise ScriptError("Plot axes need explicit worksheet/column bindings.")
            return series(**self.unwrap(kwargs))
        if len(args) != 1 or kwargs:
            raise ScriptError("Recording helpers take exactly one argument.")
        value = args[0]
        if name == "float":
            return float(value)
        if name == "len" and isinstance(value, _Ref) and value.kind == "frame":
            return len(value.value)
        if name == "len" and isinstance(value, (list, tuple)):
            return len(value)
        if name == "int" and type(value) in {int, float} and math.isfinite(value):
            return int(value)
        raise ScriptError("Only bounded recording-helper inputs are allowed.")

    def unwrap(self, value: object) -> object:
        if isinstance(value, _Ref):
            return value.value
        if isinstance(value, dict):
            return {key: self.unwrap(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            items = [self.unwrap(item) for item in value]
            return items if isinstance(value, list) else tuple(items)
        return value

    def call(self, name: str, args: list, kwargs: dict) -> object:
        self.tick(name)
        function = self.dispatch[name]
        bound = inspect.signature(function).bind(self.session, *args, **kwargs)
        arguments = bound.arguments
        if name in {"plot", "update_plot"}:
            validate_plot_settings(arguments.get("settings", {}))
        if name == "export_plot":
            validate_workspace_plots(self.session.workspace)
        if name in {"load", "load_excel", "load_large", "load_folder"}:
            key = "folder" if name == "load_folder" else "path"
            arguments[key] = self.files.read(arguments[key], folder=name == "load_folder")
            extensions = ({".xlsx", ".xlsm"} if name == "load_excel" else
                          {".csv", ".dat", ".txt", ".parquet"} if name == "load_large" else {".csv", ".dat", ".txt", ".tsv"})
            if name != "load_folder" and arguments[key].suffix.lower() not in extensions:
                raise ScriptError("This import accepts only supported data-file extensions.")
        if name in {"export_data", "export_plot", "save_project"}:
            allowed = ({".csv", ".dat", ".txt", ".tsv"} if name == "export_data" else
                       {".png", ".pdf", ".svg", ".jpg", ".jpeg", ".tif", ".tiff"} if name == "export_plot" else {".jasc"})
            arguments["path"] = self.files.write(arguments["path"], allowed)
            if name == "save_project" and arguments.get("options"):
                raise ScriptError("Protected saves and custom persistence options are not available in playback.")
        self.check_parameters(name, arguments)
        if name == "load_folder":
            from core.macro_jobs import folder_sources
            sources = folder_sources(arguments["folder"], arguments.get("recursive", False))
            if len(sources) > 256:
                raise ScriptError("Folder playback is limited to 256 worksheets.")
            paths = [self.files.read(str(source.path)) for source in sources]
            result = [self.dispatch["load"](self.session, path, **self.unwrap(arguments.get("options", {}))) for path in paths]
        else:
            result = function(*self.unwrap(bound.args), **self.unwrap(bound.kwargs))
        if name in DATASET_METHODS:
            return _Ref("dataset", result)
        if name in PLOT_METHODS:
            return _Ref("plot", result)
        if name in {"load_large", "large_sheet"}:
            return _Ref("large", result)
        if name in {"analysis", "duplicate_analysis"}:
            return _Ref("analysis", result)
        if name == "load_folder":
            if len(result) > 256:
                raise ScriptError("Folder playback is limited to 256 worksheets.")
            return [_Ref("dataset", item) for item in result]
        if name == "fit":
            return _Ref("fit", result)
        if name in {"spectrum", "spectral_batch"}:
            return _Ref("spectral", result)
        return result

    def check_parameters(self, name: str, arguments: dict) -> None:
        # API objects are never returned raw to the language. Enforce the object
        # arguments here as well as in the numerical/plotting engines.
        for key, kind in {"sheet": "dataset", "other": "dataset", "secondary": "dataset",
                          "dataset": "dataset", "source_dataset": "dataset", "plot": "plot", "analysis": "analysis"}.items():
            item = arguments.get(key)
            if item is not None and not (isinstance(item, _Ref) and item.kind == kind):
                raise ScriptError(f"{key} must refer to an earlier {kind} result.")
        if name == "formula":
            validate_math_text(arguments["expression"])
        for values in [arguments, *(value for value in arguments.values() if isinstance(value, dict))]:
            for key in ("row_count", "count", "fit_points", "bin_count", "start_row", *( ["rows"] if name == "new_sheet" else [])):
                if key in values and (type(values[key]) is not int or not 0 <= values[key] <= 1_000_000):
                    raise ScriptError(f"{key} exceeds the playback allocation limit.")
            if "column_count" in values and (type(values["column_count"]) is not int or not 0 <= values["column_count"] <= 10_000):
                raise ScriptError("Column count exceeds the playback limit.")
            if "ranges" in values and values["ranges"] is not None:
                if math.prod(int(item[2]) for item in values["ranges"]) > 2_000_000:
                    raise ScriptError("Interpolation grid exceeds the playback allocation limit.")
        if name == "fit":
            for model in arguments.get("settings", {}).get("custom_models", []):
                validate_math_text(model["expression"])
