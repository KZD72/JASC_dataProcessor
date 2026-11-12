"""Versioned, JSON-only application macros. No executable code is deserialized."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import tempfile

from core.file_io import ImportOptions


OPERATIONS = {"smooth", "fit", "plot"}
XY_TYPES = {"line", "scatter", "line_marker", "errorbar"}


@dataclass(frozen=True)
class ColumnRef:
    table: str
    column: str

    @classmethod
    def from_state(cls, value: dict[str, str]) -> ColumnRef:
        if not isinstance(value, dict) or set(value) != {"table", "column"}:
            raise ValueError("A macro column needs table and column references.")
        if not all(isinstance(value[key], str) and value[key] for key in value):
            raise ValueError("Macro column references must be nonempty text.")
        return cls(**value)


@dataclass
class MacroStep:
    key: str
    operation: str
    settings: dict[str, object] = field(default_factory=dict)
    inputs: dict[str, ColumnRef] = field(default_factory=dict)

    def to_state(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class Macro:
    name: str = "New macro"
    steps: list[MacroStep] = field(default_factory=list)
    import_options: dict[str, object] = field(default_factory=lambda: asdict(ImportOptions()))
    issues: list[str] = field(default_factory=list)

    def validate(self, *, runnable: bool = False) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Give the macro a name.")
        ImportOptions(**self.import_options)
        available = {"source"}
        for step in self.steps:
            if not isinstance(step.key, str) or not step.key or step.key in available or "." in step.key:
                raise ValueError("Macro step identifiers must be unique and cannot contain dots.")
            if step.operation not in OPERATIONS or not isinstance(step.settings, dict):
                raise ValueError(f"Unsupported macro operation: {step.operation}")
            for ref in step.inputs.values():
                ColumnRef.from_state(asdict(ref))
                if ref.table not in available:
                    raise ValueError(f"{step.key} references a missing or later step: {ref.table}")
            if step.operation in {"smooth", "fit"} and not {"x", "y"} <= step.inputs.keys():
                raise ValueError(f"{step.key} needs X and Y inputs.")
            if step.operation == "smooth":
                if set(step.settings) != {"method", "parameters", "output_column"}:
                    raise ValueError("Invalid smoothing settings.")
                available.add(step.key)
            elif step.operation == "fit":
                available.update((step.key, step.key+".residuals"))
            else:
                state = step.settings.get("state", {})
                if not isinstance(state, dict) or not state.get("series") or state.get("kind"):
                    raise ValueError("Record a nonempty ordinary XY plot.")
                for series in state["series"]:
                    if series.get("plot_type", "line") not in XY_TYPES:
                        raise ValueError("The first macro version supports ordinary XY plots only.")
                    for axis in ("x", "y"):
                        if series.get(axis+"_dataset") not in available:
                            raise ValueError("A macro plot references an unavailable result.")
        json.dumps(self.to_state(), allow_nan=False)
        if runnable and (not self.steps or self.issues):
            raise ValueError("Record at least one step and resolve recording gaps before running.\n" + "\n".join(self.issues))

    def to_state(self) -> dict[str, object]:
        return {"format": "jasc-macro", "version": 1, "name": self.name,
                "steps": [step.to_state() for step in self.steps],
                "import_options": deepcopy(self.import_options), "issues": list(self.issues)}

    @classmethod
    def from_state(cls, state: dict[str, object]) -> Macro:
        if not isinstance(state, dict) or state.get("format") != "jasc-macro" or state.get("version") != 1:
            raise ValueError("Unsupported JASC macro format or version.")
        steps = [MacroStep(item["key"], item["operation"], deepcopy(item["settings"]),
                           {name: ColumnRef.from_state(ref) for name, ref in item["inputs"].items()})
                 for item in state["steps"]]
        result = cls(state["name"], steps, deepcopy(state["import_options"]), list(state.get("issues", [])))
        if not all(isinstance(issue, str) for issue in result.issues):
            raise ValueError("Invalid recording gaps.")
        result.validate()
        return result

    @classmethod
    def load(cls, path: str | Path) -> Macro:
        return cls.from_state(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        """Atomically replace a standalone macro, preserving an earlier file on failure."""
        self.validate()
        path = Path(path)
        payload = json.dumps(self.to_state(), indent=2, ensure_ascii=False, allow_nan=False)
        descriptor, name = tempfile.mkstemp(prefix=".jasc-macro-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
