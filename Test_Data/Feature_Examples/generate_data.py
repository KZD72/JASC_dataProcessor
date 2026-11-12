"""Regenerate only this catalog's synthetic inputs and independent reference values.

Run from the repository root. --output allows a separate reproducibility check.
This is a trusted developer utility, not a restricted JASC recording.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from generators.tabular import generate_tabular
from generators.numerical import generate_numerical
from generators.visual import generate_visual


def generate(output: Path) -> None:
    """Write small, deterministic examples without touching legacy Test_Data files."""
    output.mkdir(parents=True, exist_ok=True)
    generate_tabular(output)
    generate_numerical(output)
    generate_visual(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    generate(parser.parse_args().output.resolve())
