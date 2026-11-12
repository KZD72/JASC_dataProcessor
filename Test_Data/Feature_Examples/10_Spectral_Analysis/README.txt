BASELINE, PEAKS AND RAMAN MAPS
=============================
Replay run_example.py with this directory as input; start an empty project.
Import the normalized CSVs as General table to retain the supplied column names.

Single spectrum GUI: Analysis > Baseline Correction / Peak Analysis. Select
spectrum.csv, X=shift/Y=signal. Baseline Constant=2, detect positive peaks,
prominence=1. Two peaks should be at 200 and 300, amplitudes 5 and 3, Gaussian
sigmas 6 and 10. Review their enable states and assign Gaussian components.
Fit corrected data with zero residual baseline. The macro contains explicit
reviewed seeds and bounds; it recomputes baseline, candidates and component fits.
Save/reload a parameter profile through the dialog to try its reuse workflow.

Map GUI: raman_map.csv has long-form X/Y/shift/signal, six pixels (3 by 2), and
301 samples per pixel. Choose map scope, spectral X=shift, intensity=signal,
spatial X/Y as coordinates; constant background=2, one Gaussian near 240,
center-matching tolerance=15. Fit all pixels. In Raman Results choose center or
amplitude, click pixels and inspect fit/residual/QC tabs. Internal viewer style
changes and pixel clicks are manual presentation steps, not replay adapters.
Try Map Cuts, a picked cut line, and export internal tables to worksheets.

Expected at every pixel: center=240+3*X-2*Y, amplitude=5+X+Y, sigma=6, successful
fits. Full analyses remain in the workspace rather than expanding all internal
tables automatically. Replay explicitly exports parameters/metrics and a separate
baseline-corrected map. Baseline-only map correction should subtract exactly 2.
AsLS/arPLS/SNIP/manual anchors are GUI alternatives on the same data; their settings
are not expected to reproduce a known constant baseline exactly in every case.
