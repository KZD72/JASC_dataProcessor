ASYMMETRIC PERCENTILE BOUNDS
============================
Replay run_example.py with this directory as input; start an empty project.
percentiles.csv supplies measured y medians, LOWER/UPPER ENDPOINT columns y_p16
and y_p84, and probability levels 0.16/0.84. They are not error magnitudes.

GUI plot: X=x, Y=y, Errorbar, enable Y percentile bounds, select y_p16/y_p84,
levels 16%/84%, center median, origin measurement. Optional x_p16/x_p84 demonstrate
independent X mapping in the plot. Generated X is exact, so the supplied fit does
not use these illustrative X endpoints as measurement noise.
Curve Fit: choose the raw worksheet in Source > Worksheet (Percentile measurements
after running the macro, or percentiles after importing the CSV), X=x and Y=y.
Switching worksheets clears response/error mappings so choose them explicitly.
In Uncertainty, choose the same Y endpoints/levels, Linear model,
initial slope 1.5/intercept 2.0. Fit the unsmoothed observations. Expected slope
about 1.7 and intercept about 2, within 0.15 for this seeded example.

The GUI automatically stores each successful single-fit report as <fit-sheet>_report
in the workspace. It contains full report_text, numeric parameters/errors/metrics
and percentile settings. Save Project to retain it. The report viewer has Copy
Report, Export Table (CSV/tab-delimited), and Open Report Sheet. A batch retains
one report table with a row per successful fit. The supplied macro's explicitly
named Percentile report table uses the same recomputed report builder.

The generator uses a stated monotone Gaussian transform with median-zero,
asymmetric noise and Gaussian tails. Its exact density differs from JASC's
quantile-normal interpolation between the given percentiles; percentile endpoints
alone do not identify a unique distribution. This demonstrates the supported
likelihood approximation, not exact uncertainty calibration or bootstrapping.
Posterior/non-median bounds can be plotted but are not measurement likelihoods.
Correlated/systematic errors require additional modeling. Fit bands/parameter
errors are local approximations. Replay exports the curve/residual/report and PNG.
