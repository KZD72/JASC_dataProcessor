"""Analytically defined signal, interpolation, fitting and spectral fixtures."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import j0

from .common import csv, inputs, truth


def generate_numerical(root: Path) -> None:
    directory = inputs(root, "05_Signal_Processing")
    t = np.arange(512)/128.
    clean = 2*np.sin(2*np.pi*5*t) + .5*np.cos(2*np.pi*13*t)
    csv(directory/"signals.csv", pd.DataFrame({"time_s": t, "signal": clean,
        "noisy": clean + np.random.default_rng(505).normal(0, .15, len(t)), "quadratic": t*t}))
    truth(directory, {"rows": 512, "sample_rate_hz": 128, "peak_frequencies_hz": [5, 13],
                      "peak_amplitudes": [2, .5], "derivative": "2*time_s", "integral": "time_s**3/3"})

    directory = inputs(root, "06_Interpolation")
    x = np.linspace(0, 4, 9)
    csv(directory/"line.csv", pd.DataFrame({"x": x, "value": 2*x + 1}))
    x, y = np.meshgrid(np.linspace(-1, 1, 5), np.linspace(-1, 1, 5))
    csv(directory/"plane.csv", pd.DataFrame({"x": x.ravel(), "y": y.ravel(), "z": (2*x + 3*y + 1).ravel()}))
    x, y, z = np.meshgrid([0., 1.], [0., 1.], [0., 1.])
    csv(directory/"volume.csv", pd.DataFrame({"x": x.ravel(), "y": y.ravel(), "z": z.ravel(),
                                            "value": (x + 2*y + 3*z).ravel()}))
    truth(directory, {"line": "2*x+1", "plane": "2*x+3*y+1", "volume": "x+2*y+3*z",
                      "line_query_rows": 17, "plane_query_rows": 81, "volume_center": 3.})

    directory = inputs(root, "08_Curve_Fitting")
    x = np.linspace(.1, 10, 201)
    frame = pd.DataFrame({"x": x, "linear": 2.5*x + 1.2,
        "gaussian": 8*np.exp(-.5*((x - 5)/.7)**2) + .5,
        "decay": 6*np.exp(-x/2) + .4, "logistic": 5/(1 + np.exp(-1.5*(x - 5))),
        "sine": 2*np.sin(2*np.pi*.3*x + .2) + 1,
        "kinetics": 4*x/(2 + x), "power": 3*x**.6,
        "log_normal": np.exp(-.5*((np.log(x) - 1)/.4)**2)/(x*.4*np.sqrt(2*np.pi)),
        "bessel": j0(x)})
    csv(directory/"models.csv", frame)
    truth(directory, {"linear_parameters": [2.5, 1.2], "gaussian_parameters": [8, 5, .7, .5],
        "decay_formula": "6*exp(-x/2)+0.4", "logistic_formula": "5/(1+exp(-1.5*(x-5)))",
        "custom_expression": "a*x+b", "no_measurement_noise": True})

    directory = inputs(root, "09_Asymmetric_Uncertainty")
    # A known monotone measurement model y_obs = true + h(Z), Z standard normal,
    # h(z)=0.18*z + 0.07*log(cosh(z)). Independent points; no shared systematic term.
    # The supplied endpoints describe this sampling model, not posterior quantiles.
    x = np.linspace(0, 10, 121)
    rng = np.random.default_rng(909)
    normal = rng.normal(size=len(x))
    y = 1.7*x + 2 + .18*normal + .07*np.log(np.cosh(normal))
    from scipy.special import ndtri
    low, high = ndtri(.16), ndtri(.84)
    csv(directory/"percentiles.csv", pd.DataFrame({"x": x, "y": y,
        "y_p16": y + .18*low + .07*np.log(np.cosh(low)),
        "y_p84": y + .18*high + .07*np.log(np.cosh(high)),
        "x_p16": x - .03, "x_p84": x + .05}))
    truth(directory, {"rows": 121, "slope": 1.7, "intercept": 2., "fit_parameter_tolerance": .15,
        "probabilities": [.16, .84], "centre": "median", "origin": "measurement",
        "note": "Example measurement distribution has Gaussian tails but is not exactly JASC's interpolated quantile-normal likelihood. X endpoints are plotting examples; generated X values are exact."})

    directory = inputs(root, "10_Spectral_Analysis")
    shift = np.linspace(100, 400, 301)
    signal = 2 + 5*np.exp(-.5*((shift - 200)/6)**2) + 3*np.exp(-.5*((shift - 300)/10)**2)
    csv(directory/"spectrum.csv", pd.DataFrame({"shift": shift, "signal": signal}))
    frames = []
    for y in range(2):
        for x in range(3):
            center, amplitude = 240 + 3*x - 2*y, 5 + x + y
            frames.append(pd.DataFrame({"X": x, "Y": y, "shift": shift,
                "signal": 2 + amplitude*np.exp(-.5*((shift - center)/6)**2)}))
    csv(directory/"raman_map.csv", pd.concat(frames, ignore_index=True))
    truth(directory, {"single_centers": [200., 300.], "single_amplitudes": [5., 3.],
        "single_sigmas": [6., 10.], "baseline": 2., "map_pixels": 6, "samples_per_pixel": 301,
        "map_center": "240+3*X-2*Y", "map_amplitude": "5+X+Y", "map_sigma": 6.})
