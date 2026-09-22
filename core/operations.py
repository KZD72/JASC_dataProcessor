"""DataFrame column and cell operations."""

from __future__ import annotations

import ast
import keyword
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Number
from typing import Any

import numpy as np
import pandas as pd
import scipy.integrate as scipy_integrate
import scipy.signal as scipy_signal
import scipy.special as scipy_special
import scipy.stats as scipy_stats


class ExpressionError(ValueError):
    """Raised when a user expression cannot be evaluated safely."""


_NUMPY_FUNCTION_NAMES = {
    "abs",
    "absolute",
    "add",
    "angle",
    "arccos",
    "arccosh",
    "arcsin",
    "arcsinh",
    "arctan",
    "arctan2",
    "arctanh",
    "average",
    "ceil",
    "clip",
    "conj",
    "cos",
    "cosh",
    "cumprod",
    "cumsum",
    "deg2rad",
    "degrees",
    "diff",
    "divide",
    "exp",
    "expm1",
    "floor",
    "floor_divide",
    "full_like",
    "gradient",
    "heaviside",
    "hypot",
    "imag",
    "interp",
    "isfinite",
    "isinf",
    "isnan",
    "log",
    "log10",
    "log1p",
    "log2",
    "logical_and",
    "logical_not",
    "logical_or",
    "logical_xor",
    "maximum",
    "mean",
    "median",
    "minimum",
    "multiply",
    "nan_to_num",
    "nanmax",
    "nanmean",
    "nanmedian",
    "nanmin",
    "nanpercentile",
    "nanquantile",
    "nanstd",
    "nansum",
    "nanvar",
    "negative",
    "ones_like",
    "percentile",
    "positive",
    "power",
    "prod",
    "ptp",
    "quantile",
    "rad2deg",
    "radians",
    "real",
    "remainder",
    "roll",
    "round",
    "select",
    "sign",
    "sinc",
    "sin",
    "sinh",
    "sqrt",
    "square",
    "std",
    "subtract",
    "sum",
    "tan",
    "tanh",
    "trapezoid",
    "true_divide",
    "unwrap",
    "var",
    "where",
    "zeros_like",
}

_NUMPY_CONSTANT_NAMES = {"e", "inf", "nan", "pi"}
_NUMPY_FFT_FUNCTION_NAMES = {"fft", "fftfreq", "fftshift", "ifft", "ifftshift"}
_NUMPY_LINALG_FUNCTION_NAMES = {"norm"}
_NUMPY_RANDOM_FUNCTION_NAMES = {"rand", "randn", "randint", "random", "choice", "normal", "uniform"}

_SCIPY_SPECIAL_FUNCTION_NAMES = {
    "airy",
    "beta",
    "erf",
    "erfc",
    "erfinv",
    "expit",
    "factorial",
    "gamma",
    "gammaln",
    "i0",
    "i1",
    "iv",
    "j0",
    "j1",
    "jn",
    "jv",
    "kv",
    "logit",
    "ndtr",
    "ndtri",
    "spherical_jn",
    "spherical_yn",
    "y0",
    "y1",
    "yn",
    "yv",
}

_SCIPY_SIGNAL_FUNCTION_NAMES = {
    "detrend",
    "filtfilt",
    "hilbert",
    "lfilter",
    "medfilt",
    "resample",
    "savgol_filter",
    "wiener",
}

_SCIPY_STATS_FUNCTION_NAMES = {
    "gmean",
    "hmean",
    "iqr",
    "kurtosis",
    "median_abs_deviation",
    "rankdata",
    "sem",
    "skew",
    "zscore",
}

_SCIPY_INTEGRATE_FUNCTION_NAMES = {
    "cumulative_trapezoid",
    "simpson",
    "trapezoid",
}

_ALLOWED_NODE_TYPES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Attribute,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.keyword,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.Invert,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.BitAnd,
    ast.BitOr,
    ast.And,
    ast.Or,
)


@dataclass(frozen=True, slots=True)
class ExpressionResult:
    """Details about a completed expression application."""

    target_column: str
    updated_rows: int


def referenced_worksheet_names(expression: str) -> set[str]:
    """Return literal worksheet names used by ``sheet(name, column)`` calls."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError:
        return set()

    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "sheet" or not node.args:
            continue
        worksheet_arg = node.args[0]
        if isinstance(worksheet_arg, ast.Constant) and isinstance(worksheet_arg.value, str):
            names.add(worksheet_arg.value)
    return names


def rename_worksheet_references(expression: str, old_name: str, new_name: str) -> str:
    """Rename literal ``sheet()`` worksheet references in one expression."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return expression

    changed = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "sheet" or not node.args:
            continue
        worksheet_arg = node.args[0]
        if isinstance(worksheet_arg, ast.Constant) and worksheet_arg.value == old_name:
            worksheet_arg.value = new_name
            changed = True
    if not changed:
        return expression
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


class _SafeNamespace:
    """Small attribute namespace exposing only explicitly listed members."""

    def __init__(self, display_name: str, members: dict[str, object]) -> None:
        """Store explicitly allowed namespace members for expression access."""
        self._display_name = display_name
        self._members = members

    def __getattr__(self, name: str) -> object:
        """Return an allowed member or reject unavailable attributes."""
        if name in self._members:
            return self._members[name]
        raise AttributeError(f"{self._display_name}.{name} is not available in formulas.")

    def attribute_paths(self, prefix: tuple[str, ...]) -> set[tuple[str, ...]]:
        """Return every allowed dotted attribute path below a prefix."""
        paths: set[tuple[str, ...]] = set()
        for name, value in self._members.items():
            path = (*prefix, name)
            paths.add(path)
            if isinstance(value, _SafeNamespace):
                paths.update(value.attribute_paths(path))
        return paths

    def callable_attribute_paths(self, prefix: tuple[str, ...]) -> set[tuple[str, ...]]:
        """Return allowed dotted attribute paths whose final value is callable."""
        paths: set[tuple[str, ...]] = set()
        for name, value in self._members.items():
            path = (*prefix, name)
            if callable(value):
                paths.add(path)
            if isinstance(value, _SafeNamespace):
                paths.update(value.callable_attribute_paths(path))
        return paths


def apply_column_expression(
    frame: pd.DataFrame,
    target_column: str,
    expression: str,
    row_positions: Sequence[int] | None = None,
    worksheet_frames: Mapping[str, pd.DataFrame] | None = None,
) -> ExpressionResult:
    """Evaluate an expression and write its result into a DataFrame column."""
    clean_target = target_column.strip()
    if not clean_target:
        raise ExpressionError("Choose or enter a target column.")

    values = evaluate_expression(
        frame,
        expression,
        worksheet_frames=worksheet_frames,
    )
    target_index = _target_index(frame, row_positions)

    if clean_target not in frame.columns:
        frame[clean_target] = pd.NA

    if row_positions is None:
        frame[clean_target] = values
    else:
        frame.loc[target_index, clean_target] = values.loc[target_index].to_numpy()

    return ExpressionResult(target_column=clean_target, updated_rows=len(target_index))


def evaluate_expression(
    frame: pd.DataFrame,
    expression: str,
    worksheet_frames: Mapping[str, pd.DataFrame] | None = None,
) -> pd.Series:
    """Evaluate a constrained expression against columns and workspace sheets.

    Cross-worksheet columns are aligned to the target worksheet by visible row
    position. Shorter sources are padded with missing values and longer sources
    are truncated to the target row count.
    """
    clean_expression = expression.strip()
    if not clean_expression:
        raise ExpressionError("Enter an expression to apply.")

    try:
        tree = ast.parse(clean_expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"Expression syntax error: {exc.msg}") from exc

    environment = _build_environment(frame, worksheet_frames=worksheet_frames)
    validator = _ExpressionValidator(
        allowed_names=set(environment),
        callable_names=_callable_names(environment),
        attribute_names=_attribute_names(environment),
        callable_attribute_names=_callable_attribute_names(environment),
    )
    validator.visit(tree)

    try:
        result = eval(compile(tree, "<column expression>", "eval"), {"__builtins__": {}}, environment)
    except Exception as exc:
        raise ExpressionError(f"Could not evaluate expression: {exc}") from exc

    return _coerce_result_to_series(result, frame.index)


def _build_environment(
    frame: pd.DataFrame,
    worksheet_frames: Mapping[str, pd.DataFrame] | None = None,
) -> dict[str, object]:
    """Build the names visible to the expression evaluator."""
    numpy_namespace = _build_numpy_namespace()
    scipy_namespace = _build_scipy_namespace()

    environment: dict[str, object] = {
        "col": lambda name: _column_by_name(frame, name),
        "e": np.e,
        "inf": np.inf,
        "integrate": scipy_namespace.integrate,
        "index": pd.Series(frame.index, index=frame.index),
        "nan": np.nan,
        "np": numpy_namespace,
        "pi": np.pi,
        "row": pd.Series(np.arange(1, len(frame) + 1), index=frame.index),
        "sheet": lambda sheet_name, column_name: _worksheet_column_by_name(
            frame,
            worksheet_frames,
            sheet_name,
            column_name,
        ),
        "scipy": scipy_namespace,
        "signal": scipy_namespace.signal,
        "sp": scipy_namespace,
        "special": scipy_namespace.special,
        "stats": scipy_namespace.stats,
    }

    for name in _NUMPY_FUNCTION_NAMES:
        environment[name] = getattr(np, name)

    for column_name in frame.columns:
        if _is_safe_identifier(str(column_name)) and str(column_name) not in environment:
            environment[str(column_name)] = frame[column_name]

    for index, column_name in enumerate(frame.columns, start=1):
        alias = f"col{index}"
        if alias not in environment or str(column_name) == alias:
            environment[alias] = frame[column_name]

    return environment


def _callable_names(environment: dict[str, object]) -> set[str]:
    """Return top-level environment names that may be called."""
    return {name for name, value in environment.items() if callable(value)}


def _attribute_names(environment: dict[str, object]) -> set[tuple[str, ...]]:
    """Return all allowed attribute paths exposed through safe namespaces."""
    names: set[tuple[str, ...]] = set()
    for name, value in environment.items():
        if isinstance(value, _SafeNamespace):
            names.update(value.attribute_paths((name,)))
    return names


def _callable_attribute_names(environment: dict[str, object]) -> set[tuple[str, ...]]:
    """Return safe namespace attribute paths that may be called."""
    names: set[tuple[str, ...]] = set()
    for name, value in environment.items():
        if isinstance(value, _SafeNamespace):
            names.update(value.callable_attribute_paths((name,)))
    return names


def _build_numpy_namespace() -> _SafeNamespace:
    """Create the curated NumPy namespace available in formulas."""
    members = {name: getattr(np, name) for name in _NUMPY_FUNCTION_NAMES}
    members.update({name: getattr(np, name) for name in _NUMPY_CONSTANT_NAMES})
    members["fft"] = _SafeNamespace(
        "np.fft",
        {name: getattr(np.fft, name) for name in _NUMPY_FFT_FUNCTION_NAMES},
    )
    members["linalg"] = _SafeNamespace(
        "np.linalg",
        {name: getattr(np.linalg, name) for name in _NUMPY_LINALG_FUNCTION_NAMES},
    )
    members["random"] = _SafeNamespace(
        "np.random",
        {name: getattr(np.random, name) for name in _NUMPY_RANDOM_FUNCTION_NAMES},
    )
    return _SafeNamespace("np", members)


def _build_scipy_namespace() -> _SafeNamespace:
    """Create the curated SciPy namespace available in formulas."""
    special = _SafeNamespace(
        "scipy.special",
        {name: getattr(scipy_special, name) for name in _SCIPY_SPECIAL_FUNCTION_NAMES},
    )
    signal = _SafeNamespace(
        "scipy.signal",
        {name: getattr(scipy_signal, name) for name in _SCIPY_SIGNAL_FUNCTION_NAMES},
    )
    stats = _SafeNamespace(
        "scipy.stats",
        {name: getattr(scipy_stats, name) for name in _SCIPY_STATS_FUNCTION_NAMES},
    )
    integrate = _SafeNamespace(
        "scipy.integrate",
        {name: getattr(scipy_integrate, name) for name in _SCIPY_INTEGRATE_FUNCTION_NAMES},
    )
    return _SafeNamespace(
        "scipy",
        {
            "integrate": integrate,
            "signal": signal,
            "special": special,
            "stats": stats,
        },
    )


def _column_by_name(frame: pd.DataFrame, name: object) -> pd.Series:
    """Return a DataFrame column by exact display name."""
    column_name = str(name)
    if column_name not in frame.columns:
        raise ExpressionError(f"Column '{column_name}' does not exist.")
    return frame[column_name]


def _worksheet_column_by_name(
    target_frame: pd.DataFrame,
    worksheet_frames: Mapping[str, pd.DataFrame] | None,
    worksheet_name: object,
    column_name: object,
) -> pd.Series:
    """Return another worksheet column aligned to target rows by position."""
    clean_worksheet_name = str(worksheet_name)
    clean_column_name = str(column_name)
    if worksheet_frames is None or clean_worksheet_name not in worksheet_frames:
        raise ExpressionError(f"Worksheet '{clean_worksheet_name}' does not exist.")

    source_frame = worksheet_frames[clean_worksheet_name]
    if clean_column_name not in source_frame.columns:
        raise ExpressionError(
            f"Column '{clean_column_name}' does not exist in worksheet "
            f"'{clean_worksheet_name}'."
        )

    positional_values = source_frame[clean_column_name].reset_index(drop=True)
    aligned_values = positional_values.reindex(pd.RangeIndex(len(target_frame)))
    aligned_values.index = target_frame.index
    return aligned_values


def _target_index(frame: pd.DataFrame, row_positions: Sequence[int] | None) -> pd.Index:
    """Return the DataFrame index targeted by an expression application."""
    if row_positions is None:
        return frame.index

    valid_positions = sorted({position for position in row_positions if 0 <= position < len(frame)})
    if not valid_positions:
        raise ExpressionError("Select one or more valid rows, or apply to all rows.")

    return frame.index[valid_positions]


def _coerce_result_to_series(result: object, index: pd.Index) -> pd.Series:
    """Normalize scalar or one-dimensional expression output to a Series."""
    if isinstance(result, pd.Series):
        return result.reindex(index)

    if isinstance(result, pd.Index):
        result = result.to_numpy()

    if isinstance(result, np.ndarray):
        if result.ndim != 1:
            raise ExpressionError("Expression returned more than one dimension.")
        if len(result) != len(index):
            raise ExpressionError(
                f"Expression returned {len(result)} values for {len(index)} rows."
            )
        return pd.Series(result, index=index)

    if isinstance(result, Sequence) and not isinstance(result, str | bytes):
        if len(result) != len(index):
            raise ExpressionError(
                f"Expression returned {len(result)} values for {len(index)} rows."
            )
        return pd.Series(list(result), index=index)

    if isinstance(result, Number | str | bool) or pd.isna(result):
        return pd.Series([result] * len(index), index=index)

    raise ExpressionError(f"Expression returned unsupported type: {type(result).__name__}.")


def _is_safe_identifier(name: str) -> bool:
    """Return whether a column name can be exposed as a bare expression name."""
    return name.isidentifier() and not keyword.iskeyword(name) and not name.startswith("_")


class _ExpressionValidator(ast.NodeVisitor):
    """AST validator for the constrained column-expression language."""

    def __init__(
        self,
        allowed_names: set[str],
        callable_names: set[str],
        attribute_names: set[tuple[str, ...]],
        callable_attribute_names: set[tuple[str, ...]],
    ) -> None:
        """Store the name and callable allowlists used during AST validation."""
        self._allowed_names = allowed_names
        self._callable_names = callable_names
        self._attribute_names = attribute_names
        self._callable_attribute_names = callable_attribute_names

    def generic_visit(self, node: ast.AST) -> None:
        """Reject AST node types outside the constrained expression language."""
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise ExpressionError(f"Unsupported expression element: {type(node).__name__}.")
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Reject references to names outside the safe environment."""
        if node.id not in self._allowed_names:
            raise ExpressionError(f"Unknown name '{node.id}'.")

    def visit_BinOp(self, node: ast.BinOp) -> None:
        """Validate binary operations and reject caret exponent mistakes."""
        if isinstance(node.op, ast.BitXor):
            raise ExpressionError("Use ** for powers. The ^ operator is not exponentiation in Python.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Validate calls against allowed top-level and dotted callables."""
        if isinstance(node.func, ast.Name):
            if node.func.id not in self._callable_names:
                raise ExpressionError(f"'{node.func.id}' is not callable in expressions.")
            if node.func.id == "sheet":
                if len(node.args) != 2 or node.keywords:
                    raise ExpressionError(
                        'Use sheet("Worksheet", "Column") with exactly two quoted names.'
                    )
                if not all(
                    isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                    for argument in node.args
                ):
                    raise ExpressionError(
                        'Worksheet references require quoted names: sheet("Worksheet", "Column").'
                    )
        elif isinstance(node.func, ast.Attribute):
            path = self._attribute_path(node.func)
            if path not in self._callable_attribute_names:
                raise ExpressionError(f"{'.'.join(path)} is not callable or not available in formulas.")
        else:
            raise ExpressionError("Unsupported function call.")

        for keyword_arg in node.keywords:
            if keyword_arg.arg is None:
                raise ExpressionError("Expanded keyword arguments are not supported.")

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Validate safe dotted attribute access."""
        if node.attr.startswith("_"):
            raise ExpressionError(
                f"Access to private attributes is not allowed: .{node.attr}"
            )
        path = self._attribute_path(node)
        if path not in self._attribute_names:
            raise ExpressionError(f"{'.'.join(path)} is not available in formulas.")

    def _attribute_path(self, node: ast.Attribute) -> tuple[str, ...]:
        """Convert an AST attribute chain into a tuple path."""
        path: list[str] = [node.attr]
        current = node.value
        while isinstance(current, ast.Attribute):
            path.append(current.attr)
            current = current.value

        if not isinstance(current, ast.Name):
            raise ExpressionError("Unsupported dotted expression.")

        path.append(current.id)
        return tuple(reversed(path))
