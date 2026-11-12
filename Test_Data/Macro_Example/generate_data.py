"""Regenerate the bundled synthetic measurements; this is not a JASC macro.

Run with the project Python environment. The example CSV files are included, so
users of the standalone application do not need to run this helper.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


SPECTRA = (
    ("spectrum_01", 8.0, -0.8, 0.65, 1.5, 0.08, 0.12),
    ("spectrum_02", 10.0, 0.2, 0.80, 2.1, -0.04, 0.15),
    ("spectrum_03", 6.5, 1.0, 1.05, 1.0, 0.06, 0.10),
)
MISSING_ROWS = (40, 120, 200, 280, 360)
DUPLICATE_ROWS = (35, 75, 155, 225, 305, 365)


def generate(destination: Path | None = None) -> None:
    """Write seeded independent-noise spectra and their separate ground truth."""
    root = Path(destination) if destination is not None else Path(__file__).resolve().parent
    inputs = root/"input"
    inputs.mkdir(parents=True, exist_ok=True)
    truth = {
        "model": "signal = background + amplitude * exp(-0.5*((x-center)/sigma)**2) + noise",
        "background": "Exact synthetic reference: background_offset + background_slope*x",
        "noise": "Independent Gaussian measurement noise; signal_sigma is its known Y standard deviation",
        "base_seed": 20261111,
        "original_grid_rows": 401,
        "raw_rows_per_file": 407,
        "missing_signal_rows_per_file": 5,
        "duplicate_rows_per_file": 6,
        "processed_rows_per_file": 396,
        "parameter_absolute_tolerances": {"amplitude": 0.20, "center": 0.04, "sigma": 0.04, "offset": 0.08},
        "spectra": {},
    }
    x = np.linspace(-5.0, 5.0, 401)
    for index, (name, amplitude, center, width, background_offset, background_slope, noise_std) in enumerate(SPECTRA):
        seed = truth["base_seed"]+index
        rng = np.random.default_rng(seed)
        background = background_offset+background_slope*x
        peak = amplitude*np.exp(-0.5*((x-center)/width)**2)
        frame = pd.DataFrame({
            "x": x, "signal": background+peak+rng.normal(0.0, noise_std, len(x)),
            "signal_sigma": np.full(len(x), noise_std), "background": background,
        })
        frame.loc[list(MISSING_ROWS), "signal"] = np.nan
        frame = pd.concat([frame, frame.iloc[list(DUPLICATE_ROWS)]], ignore_index=True)
        frame = frame.iloc[rng.permutation(len(frame))].reset_index(drop=True)
        frame.to_csv(inputs/(name+".csv"), index=False, float_format="%.12g", lineterminator="\n")
        truth["spectra"][name] = {
            "amplitude": amplitude, "center": center, "sigma": width, "offset": 0.0,
            "noise_std": noise_std, "background_offset": background_offset,
            "background_slope": background_slope, "seed": seed,
        }
    (root/"expected_truth.json").write_text(json.dumps(truth, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    generate()
