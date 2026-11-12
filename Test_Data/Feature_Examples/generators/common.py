"""Stable serialization helpers for the feature examples."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def inputs(root: Path, family: str) -> Path:
    directory = root / family / "input"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def csv(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, float_format="%.12g", lineterminator="\n")


def truth(directory: Path, values: dict) -> None:
    (directory.parent / "expected.json").write_text(
        json.dumps(values, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
