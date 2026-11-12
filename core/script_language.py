"""Parse JASC recordings as a small command language, never as executable Python.

The Python spelling is retained for editable API recordings. Only explicitly
recognized statements and expressions are interpreted; imports and the standard
launcher are checked as syntax and never executed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


class ScriptError(ValueError):
    """Invalid, disallowed or failed recorded command."""


METHODS = frozenset({
    "sheet", "load", "load_excel", "load_folder", "load_large", "large_sheet", "extract_window", "delete_large",
    "new_sheet", "edit", "rename_sheet", "duplicate_sheet", "delete_sheet", "prepare",
    "smooth", "derivative", "integral", "formula", "fft", "ifft", "fit", "statistics", "interpolate",
    "statistics_plot_data", "baseline_map", "spectral_batch", "spectrum", "analysis", "duplicate_analysis",
    "delete_analysis", "export_analysis_table", "result_row", "collect_rows", "map_analysis",
    "plot", "plot_by_name", "update_plot", "rename_plot", "delete_plot", "compare", "update_comparison",
    "export_data", "export_plot", "save_project",
})
MAX_SCRIPT_BYTES = 2 * 1024 * 1024
MAX_NODES = 100_000
MAX_DEPTH = 64
MAX_STEPS = 10_000
RESERVED = {"session", "Session", "series", "float", "int", "len", "run", "launch_recording"}
LAUNCHER = ast.parse('if __name__ == "__main__":\n    session = Session.from_cli()\n    run(session)\n    session.finish()').body[0]
SECURE_LAUNCHER = ast.parse('if __name__ == "__main__":\n    launch_recording(__file__)').body[0]


def fail(node: ast.AST, message: str) -> None:
    raise ScriptError(f"Line {getattr(node, 'lineno', 1)}: {message}")


def column_count(node: ast.AST) -> tuple[ast.AST, ast.AST] | None:
    """Recognize just the recorder's frame[column].notna().sum() spelling."""
    if not (isinstance(node, ast.Call) and not node.args and not node.keywords and
            isinstance(node.func, ast.Attribute) and node.func.attr == "sum"):
        return None
    inner = node.func.value
    if not (isinstance(inner, ast.Call) and not inner.args and not inner.keywords and
            isinstance(inner.func, ast.Attribute) and inner.func.attr == "notna" and
            isinstance(inner.func.value, ast.Subscript)):
        return None
    selected = inner.func.value
    if not (isinstance(selected.value, ast.Attribute) and selected.value.attr == "frame"):
        return None
    return selected.value, selected.slice


@dataclass(frozen=True)
class Program:
    source: str
    body: tuple[ast.stmt, ...]
    commands: tuple[str, ...]

    @classmethod
    def read(cls, path: str | Path) -> Program:
        from core.script_safety import local_spelling
        local_spelling(str(path))
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_SCRIPT_BYTES+1)
        if len(data) > MAX_SCRIPT_BYTES:
            raise ScriptError("The recording exceeds the 2 MiB size limit.")
        try:
            return cls.parse(data.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise ScriptError("Recordings must use UTF-8 text.") from exc

    @classmethod
    def parse(cls, source: str) -> Program:
        if len(source.encode("utf-8")) > MAX_SCRIPT_BYTES:
            raise ScriptError("The recording exceeds the 2 MiB size limit.")
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise ScriptError(f"Invalid recording syntax: {exc}") from exc
        stack, count = [(tree, 0)], 0
        while stack:
            node, depth = stack.pop()
            count += 1
            if count > MAX_NODES or depth > MAX_DEPTH:
                raise ScriptError("The recording exceeds the syntax complexity limit.")
            stack.extend((child, depth+1) for child in ast.iter_child_nodes(node))
        function = None
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            if isinstance(node, ast.ImportFrom) and node.module == "jasc_api" and node.level == 0:
                if all(alias.name in {"Session", "series", "launch_recording"} and alias.asname is None for alias in node.names):
                    continue
            if isinstance(node, ast.FunctionDef) and node.name == "run" and function is None:
                arguments = node.args
                if (node.decorator_list or node.returns or getattr(node, "type_params", []) or
                        len(arguments.args) != 1 or arguments.args[0].arg != "session" or arguments.args[0].annotation or
                        arguments.posonlyargs or arguments.kwonlyargs or arguments.vararg or arguments.kwarg or arguments.defaults):
                    fail(node, "Use an undecorated def run(session) without annotations or default arguments.")
                function = node
                continue
            if isinstance(node, ast.If) and any(ast.dump(node, include_attributes=False) == ast.dump(launcher, include_attributes=False)
                                               for launcher in (LAUNCHER, SECURE_LAUNCHER)):
                continue
            fail(node, "Only run(session), the JASC import, and the standard recording launcher are allowed.")
        if function is None:
            raise ScriptError("The recording must define run(session).")
        validator = _Validator()
        validator.block(function.body)
        return cls(source, tuple(function.body), tuple(validator.commands))


class _Validator:
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.commands: list[str] = []

    def target(self, node: ast.AST) -> str:
        if not isinstance(node, ast.Name) or node.id.startswith("_") or node.id in RESERVED:
            fail(node, "Only ordinary variable names can be assigned; API names cannot be replaced.")
        return node.id

    def block(self, body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Pass):
                continue
            if isinstance(node, ast.Raise):
                message = (node.exc.args[0].value if isinstance(node.exc, ast.Call) and node.exc.args and
                           isinstance(node.exc.args[0], ast.Constant) and isinstance(node.exc.args[0].value, str) else "")
                fail(node, message or "Raise statements are not supported; this recording may be incomplete.")
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                name = self.target(node.targets[0])
                self.expr(node.value)
                self.names.add(name)
                continue
            if isinstance(node, ast.Expr):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    continue
                if not (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                        and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == "session"):
                    fail(node, "Statements must call an approved session operation.")
                self.expr(node.value)
                continue
            if isinstance(node, ast.For) and not node.orelse:
                name = self.target(node.target)
                self.expr(node.iter)
                before = self.names.copy()
                self.names.add(name)
                self.block(node.body)
                # A loop can have no iterations; its locals are not definite bindings.
                self.names = before
                continue
            fail(node, f"{type(node).__name__} is outside the recording language.")

    def expr(self, node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and (node.value is None or type(node.value) in {str, int, float, bool}):
            if isinstance(node.value, str) and len(node.value) > 1_000_000:
                fail(node, "A string exceeds the recording limit.")
            if type(node.value) is int and node.value.bit_length() > 256:
                fail(node, "An integer exceeds the recording limit.")
            return
        if isinstance(node, ast.Name) and node.id in self.names:
            return
        if isinstance(node, (ast.List, ast.Tuple)):
            for item in node.elts:
                self.expr(item)
            return
        if isinstance(node, ast.Dict) and all(key is not None for key in node.keys):
            for key, value in zip(node.keys, node.values):
                self.expr(key)
                self.expr(value)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)) and isinstance(node.operand, ast.Constant) and type(node.operand.value) in {int, float}:
            self.expr(node.operand)
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            self.expr(node.left)
            self.expr(node.right)
            return
        if isinstance(node, ast.Attribute) and node.attr in {"name", "frame", "curve", "residuals", "sheets", "analysis"}:
            self.expr(node.value)
            return
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int and 0 <= node.slice.value < MAX_STEPS:
            self.expr(node.value)
            return
        if isinstance(node, ast.Call):
            count = column_count(node)
            if count:
                self.expr(count[0])
                self.expr(count[1])
                return
            if any(item.arg is None or item.arg.startswith("_") for item in node.keywords):
                fail(node, "Expanded or private keyword arguments are not allowed.")
            if len({item.arg for item in node.keywords}) != len(node.keywords):
                fail(node, "Duplicate keyword arguments are not allowed.")
            if isinstance(node.func, ast.Name) and node.func.id in {"series", "len", "int", "float"}:
                if node.func.id == "float" and not (len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Constant) and node.args[0].value in {"nan", "inf", "-inf"}):
                    fail(node, "float() is limited to recorded non-finite constants.")
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "session" and node.func.attr in METHODS:
                self.commands.append(node.func.attr)
                from core.script_safety import validate_math_text
                if node.func.attr == "formula":
                    for item in node.keywords:
                        if item.arg == "expression" and isinstance(item.value, ast.Constant):
                            validate_math_text(item.value.value)
                if node.func.attr == "fit":
                    for mapping in ast.walk(node):
                        if isinstance(mapping, ast.Dict):
                            for key, value in zip(mapping.keys, mapping.values):
                                if isinstance(key, ast.Constant) and key.value == "expression" and isinstance(value, ast.Constant):
                                    validate_math_text(value.value)
            else:
                fail(node, "Only explicitly approved JASC operations and recording helpers may be called.")
            for argument in [*node.args, *(item.value for item in node.keywords)]:
                self.expr(argument)
            return
        fail(node, f"{type(node).__name__} is not an approved recording expression.")
