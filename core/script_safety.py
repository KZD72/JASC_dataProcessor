"""File capabilities and bounded mathematical expressions for script playback."""
from __future__ import annotations

import ast
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat

from core.script_language import ScriptError


def validate_math_text(text: str) -> None:
    """Use the existing numerical grammar, without evaluating the expression."""
    if not isinstance(text, str) or len(text) > 16_384:
        raise ScriptError("A formula/model expression exceeds the 16 KiB limit.")
    try:
        tree = ast.parse(text, mode="eval")
        nodes = list(ast.walk(tree))
        if len(nodes) > 2_000:
            raise ScriptError("A formula/model expression is too complex.")
        from core.operations import _build_environment, _ExpressionValidator, _callable_names, _attribute_names, _callable_attribute_names
        import pandas as pd
        names = {node.id for node in nodes if isinstance(node, ast.Name)}
        # Free column/parameter identifiers are non-callable Series. All callable
        # names and attributes still come from the established numerical allowlist.
        frame = pd.DataFrame({name: pd.Series(dtype=float) for name in names})
        environment = _build_environment(frame, referenced_names=names)
        _ExpressionValidator(set(environment), _callable_names(environment), _attribute_names(environment),
                             _callable_attribute_names(environment)).visit(tree)
        for node in nodes:
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and isinstance(node.left, ast.Constant) and type(node.left.value) is int:
                if not (isinstance(node.right, ast.Constant) and type(node.right.value) in {int, float} and abs(node.right.value) <= 128):
                    raise ScriptError("Unbounded integer exponentiation is not allowed in playback.")
            if isinstance(node, ast.Call):
                path = ast.unparse(node.func)
                if ".random." in path or path.startswith("np.fft.") or path.startswith("numpy.fft."):
                    # These helpers can allocate arrays unrelated to the worksheet.
                    for argument in [*node.args, *(item.value for item in node.keywords)]:
                        if isinstance(argument, (ast.Constant, ast.Tuple, ast.List, ast.UnaryOp)):
                            value = ast.literal_eval(argument)
                            if isinstance(value, (list, tuple)):
                                size = math.prod(abs(item) for item in value if type(item) is int)
                            else:
                                size = abs(value) if type(value) is int else 0
                            if size > 2_000_000:
                                raise ScriptError("A numerical allocation exceeds the playback limit.")
                        elif path.endswith(("rand", "randn", "random", "normal", "uniform", "randint")):
                            raise ScriptError("Random array sizes must be bounded literals during playback.")
    except ScriptError:
        raise
    except (ValueError, SyntaxError, RecursionError, TypeError) as exc:
        raise ScriptError(f"Unsafe or invalid formula/model expression: {exc}") from exc


def local_spelling(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
        raise ScriptError("Expected a local file/folder path.")
    normalized = value.replace("\\", "/")
    if normalized.startswith("//") or "://" in normalized or normalized.startswith(("/??/", "//?/")):
        raise ScriptError("Network, URL and device paths are not allowed in playback.")
    pieces = normalized.split("/")
    if ".." in pieces:
        raise ScriptError("Parent-directory traversal is not allowed in playback paths.")
    for index, piece in enumerate(pieces):
        if ":" in piece and not (index == 0 and re.fullmatch(r"[A-Za-z]:", piece)):
            raise ScriptError("Device paths and alternate data streams are not allowed.")
        reserved = (os.path.isreserved(piece) if hasattr(os.path, "isreserved") else
                    bool(re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", piece, re.IGNORECASE)))
        if piece and (piece.endswith((" ", ".")) and piece != "." or reserved):
            raise ScriptError("Reserved or ambiguous file names are not allowed.")


class FilePolicy:
    """Reads stay inside input_root; all script writes stay in fresh output_root."""
    def __init__(self, input_root: Path, output_root: Path) -> None:
        local_spelling(str(input_root))
        local_spelling(str(output_root))
        self.input_root = input_root.resolve(strict=True)
        self.output_root = output_root.resolve(strict=True)
        if not self.input_root.is_dir() or not self.output_root.is_dir():
            raise ScriptError("Input and output roots must be folders.")
        self.written: list[str] = []

    @staticmethod
    def regular_path(root: Path, target: Path) -> None:
        if not target.is_relative_to(root):
            raise ScriptError("The path escapes the selected access folder.")
        cursor = root
        # Inspect from root to leaf, without following a reparse point first.
        # In particular a local junction to a network share must never be opened.
        for piece in target.relative_to(root).parts:
            cursor = cursor/piece
            try:
                metadata = cursor.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_reparse_tag", 0) in {0xA0000003, 0xA000000C}:
                raise ScriptError("The path escapes the regular-file policy through a link or junction.")

    def read(self, value: str, *, folder: bool = False) -> Path:
        local_spelling(value)
        path = Path(value.replace("\\", "/"))
        candidate = (path if path.is_absolute() else self.input_root/path).absolute()
        self.regular_path(self.input_root, candidate)
        try:
            target = candidate.resolve(strict=True)
        except OSError as exc:
            raise ScriptError(f"Input is unavailable: {value}") from exc
        if not target.is_relative_to(self.input_root):
            raise ScriptError("An input path escapes the selected input folder (including links).")
        if not (target.is_dir() if folder else target.is_file()):
            raise ScriptError("Expected an input folder." if folder else "Expected an input file.")
        return target

    def write(self, value: str, extensions: set[str]) -> Path:
        local_spelling(value)
        path = Path(value.replace("\\", "/"))
        # Recorded absolute destinations belong to the old machine/workspace.
        # Explicitly redirect their basenames; relative subfolders are retained.
        relative = Path(path.name) if path.is_absolute() or PureWindowsPath(value).is_absolute() else path
        candidate = (self.output_root/relative).absolute()
        self.regular_path(self.output_root, candidate)
        target = candidate.resolve()
        if not target.is_relative_to(self.output_root) or target.suffix.lower() not in extensions:
            raise ScriptError("The output must be an approved data/project/figure file in the output folder.")
        if target.exists() or str(target) in self.written:
            raise ScriptError("Playback does not overwrite output files, including earlier exports in the same run.")
        target.parent.mkdir(parents=True, exist_ok=True)
        self.written.append(str(target))
        return target


def validate_plot_settings(settings: object) -> None:
    """Style URLs/files and external TeX tools are not playback capabilities."""
    from models.plot_settings import PlotSettings, StyleSettings
    values = settings if isinstance(settings, dict) else {}
    parsed = PlotSettings.from_state(values)
    if isinstance(values.get("style"), dict):
        # Validate nested fields even when an incomplete settings dictionary
        # would currently fall through the legacy migration path.
        from dataclasses import replace
        parsed = replace(parsed, style=StyleSettings.from_state(values["style"]))
    if parsed.style.use_latex:
        raise ScriptError("External LaTeX rendering is not allowed during script playback.")
    names = [token.strip() for token in parsed.style.preset.split(",") if token.strip()]
    if parsed.style.cycle:
        names.append(parsed.style.cycle)
    names.extend(token.strip() for token in parsed.style.custom.split(",") if token.strip())
    if not names:
        return
    import scienceplots  # Register only the application's installed style package.
    from matplotlib import style
    if "science" in names and "no-latex" not in names:
        names.append("no-latex")
    effective = {}
    for name in names:
        if name not in style.library:
            raise ScriptError("Playback accepts installed style names, not style files, URLs or module paths.")
        effective.update(style.library[name])
    if effective.get("text.usetex", False):
        raise ScriptError("The selected style requires an external LaTeX process.")


def validate_workspace_plots(workspace: object) -> None:
    for plot in workspace.list_plots():
        validate_plot_settings(plot.state.get("settings", {}))
