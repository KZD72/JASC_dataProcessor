"""Serializable comparison layouts referencing independent plots by identity."""

from __future__ import annotations

from collections.abc import Iterable
from math import ceil, sqrt

MAX_COMPARISON_PANELS = 16


def is_comparison(state: dict[str, object]) -> bool:
    return state.get("kind") == "plot_comparison"


def suggested_grid(count: int) -> tuple[int, int]:
    columns = min(4, max(1, ceil(sqrt(count))))
    return min(4, max(1, ceil(count / columns))), columns


def comparison_state(
    plot_ids: Iterable[str], rows: int, columns: int, *, match_x: bool = False,
    match_y: bool = False, panel_labels: bool = True,
    name_hints: dict[str, str] | None = None,
) -> dict[str, object]:
    identities = list(dict.fromkeys(plot_ids))
    if not 2 <= len(identities) <= MAX_COMPARISON_PANELS:
        raise ValueError("Choose between 2 and 16 different plots to compare.")
    if not all(isinstance(identity, str) and identity for identity in identities):
        raise ValueError("Comparison sources must have valid plot identities.")
    if not 1 <= rows <= 4 or not 1 <= columns <= 4:
        raise ValueError("Use between 1 and 4 grid rows and columns.")
    if rows * columns < len(identities):
        raise ValueError("The selected grid has fewer cells than the selected plots.")
    return {
        "kind": "plot_comparison", "schema": 1, "plot_ids": identities,
        "rows": rows, "columns": columns, "match_x": bool(match_x), "match_y": bool(match_y),
        "panel_labels": bool(panel_labels),
        "name_hints": {identity: str((name_hints or {}).get(identity, "Missing plot")) for identity in identities},
    }


def validated_comparison(state: dict[str, object]) -> dict[str, object]:
    if not is_comparison(state) or state.get("schema") != 1:
        raise ValueError("Unsupported plot comparison format.")
    return comparison_state(
        state.get("plot_ids", []), int(state.get("rows", 1)), int(state.get("columns", 2)),
        match_x=bool(state.get("match_x")), match_y=bool(state.get("match_y")),
        panel_labels=bool(state.get("panel_labels", True)), name_hints=state.get("name_hints", {}),
    )
