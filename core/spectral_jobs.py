"""Detached spectral inputs and cancellable iteration over normalized map pixels."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pandas as pd

from core.jobs import JobContext
from math_engine.calculus import MathOperationError, validate_numeric_column_metadata


@dataclass(frozen=True, slots=True)
class SpectralSource:
    """Independent projection of a worksheet, captured before worker execution."""

    name: str
    frame: pd.DataFrame


def map_spectrum_jobs(
    source: SpectralSource, context: JobContext,
) -> tuple[int, Iterator[tuple[str, pd.DataFrame, dict[str, float]]]]:
    """Count and iterate map groups without retaining a list of copied pixels."""
    for column in ("X", "Y"):
        context.check_cancelled()
        if column not in source.frame:
            raise MathOperationError("Map processing requires normalized X and Y coordinate columns.")
        numeric = pd.to_numeric(source.frame[column], errors="coerce")
        validate_numeric_column_metadata(source.frame, column, numeric)
    context.check_cancelled()
    grouped = source.frame.groupby(["X", "Y"], sort=False, dropna=False)
    total = grouped.ngroups

    def pixels() -> Iterator[tuple[str, pd.DataFrame, dict[str, float]]]:
        for (x_coordinate, y_coordinate), group in grouped:
            context.check_cancelled()
            yield (
                f"{source.name} [X={x_coordinate}, Y={y_coordinate}]",
                group.reset_index(drop=True),
                {"X": float(x_coordinate), "Y": float(y_coordinate)},
            )

    return total, pixels()
