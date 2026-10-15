# JASC Data Processor

A lightweight, modular application for data ingestion, visualization, mathematical operations, and curve fitting. Built with Python, PySide6, Pandas, and SciPy.

## Features

- **Data Ingestion**: Batch-import CSV/DAT/TXT data with encoding, delimiter, leading-metadata, header, and number-format preflight/inference; choose Auto, General table, Single spectrum, or Spectroscopy map plus an Auto/generic, Horiba LabSpec, or B&W Tek profile. Auto detects BOM-marked UTF-8/UTF-16, strict UTF-8, Windows-1252/ANSI, or Latin-1 without replacement-character data loss. Auto also safely recognizes unambiguous point/comma decimals and grouped forms, while explicit `1,234.56` and `1.234,56` modes resolve ambiguous values. Instrument preambles are retained as worksheet metadata, and legacy Horiba/B&WTech/Bruker IR text layouts are supported. Horiba LabSpec maps are normalized into `X`, `Y`, `Raman Shift`, and `Intensity`; B&W Tek is currently supported for single spectra only. Modern Excel `.xlsx`/`.xlsm` tabs can be imported as value-only datasets with explicit warnings for unsupported workbook objects; data can also be entered manually in the spreadsheet interface.
- **Data Editing**: Edit imported datasets directly with bounded undo/redo, append/insert/delete row and column operations, fast block-oriented spreadsheet copy/paste, whole-column copy/paste, large-dataset warnings, sampled table auto-sizing, and per-column name/role/unit/long-name/comment metadata.
- **Formula Engine**: Apply safe math operations to columns using a sandboxed expression evaluator with NumPy/SciPy support, positional aliases such as `col1`, exact-name insertion helpers, worksheet batch targets, and protected output naming by default.
- **Signal Processing & Calculus**: Perform numerical differentiation, cumulative integration, FFT, and previewed smoothing with adjacent-average, median, Savitzky-Golay, LOWESS, FFT low-pass, or derivative-smoothing reconstruction.
- **Baseline, Peak & Raman Analysis**: Choose any worksheet while retaining the launching sheet as the initial selection; explicitly identify a single spectrum or normalized X/Y map; select one representative map pixel for zoomable raw/baseline/corrected preview; correct spectra with arPLS, AsLS, airPLS, SNIP, rubber-band, manual-anchor, constant, linear, or polynomial baselines; detect and review positive, negative, or mixed peaks; assign a registered model to each component; and apply the reviewed setup to one spectrum, a worksheet batch, or every X/Y pixel. Full fits now become persistent analysis sessions rather than automatically filling the Data workspace. The dedicated Raman Analysis viewer keeps the parameter/quality map and click-linked selected-pixel fit prominent, supports direct title/axis/legend editing and per-curve visibility, and provides residual/error, metric-distribution, and QC details on demand in a tabbed diagnostic panel; selected internal tables can be explicitly exported to worksheets. The Fano model uses a positive physical scale, resonance position, natural linewidth, signed q, multistart fitting, separate peak/dip positions and contrasts, and propagated extrema uncertainties. Versioned JSON parameter profiles remain reusable across files.
- **Interpolation Workbench**: Generate 1D, 2D, and N-D prediction datasets with linear, spline, piecewise cubic, nearest-neighbor, and RBF methods.
- **Statistics Workbench**: Generate single-column summaries, multi-column summaries/correlations/covariance/PCA, grouped/factor analyses, normality tests, outlier checks, regression metrics, paired tests, independent-sample tests, one-way ANOVA, Kruskal-Wallis, post-hoc comparisons, and optional companion plots.
- **Curve Fitting**: Fit 66 categorized analytical models spanning polynomials, decay/growth, symmetric and asymmetric peaks, transitions/waveforms, kinetics, rheology, probability distributions, and physical functions, with customizable parameters and LM, trust-region, Dogbox, or ODR optimization.
- **Custom Fit Models**: Define project-saved fit models from safe NumPy/SciPy expressions and use them in the standard fitting workflow.
- **Dynamic Plotting**: High-performance multi-axis plotting with Matplotlib, featuring data locators, scaling controls, SciencePlots journal styling, visual customization, error bars, reporting plots, histograms, box/violin distribution comparisons, and interpolated 2D or Raman/frequency-slice maps with a full-width palette selector, editable colour-bar labels, and a dedicated live X/Y/intensity readout.
- **Saved Plots**: Start from a default empty plot, protect unsaved drafts with Save/Discard/Cancel before replacement, and store named definitions so series, locators, axes, legends, and sizing can be restored later.
- **Data Preparation**: Create non-destructive result sheets for filtering, sorting, duplicate removal, missing-value cleanup, binning, grouping, joins, and reshaping.
- **Docked Workspace Layout**: Keep datasets, saved plots, and spectral-analysis sessions in separate workspace navigator sections, show plot controls in a plot-specific inspector, and give the Data editor the full central width. The main workspace starts with only Data and Plot; the central Raman Results tab is created only when a result is completed or explicitly opened, and the Analyses navigator is hidden in projects without analysis sessions.
- **Project Persistence and Protection**: Save complete workspaces as open `.jasc` ZIP/CSV packages or optional password-encrypted `.jascx` packages. Encrypted saves use Scrypt-derived AES-256-GCM authenticated encryption; ordinary `.jasc` files remain directly inspectable for open-science use. Version 8 packages retain the uniquely salted JASC Package Seal over every member name, byte size, and SHA-256 digest, store spectral-analysis tables as readable CSV members, and can optionally add an Ed25519 author signature. JASC creates password-encrypted private identity files, exports shareable public identities, maintains a local trusted-fingerprint list, and distinguishes trusted, valid-but-unknown, unsigned, and invalid signatures.

## Installation

1. Clone the repository.
2. Ensure you have Python 3.10+ installed.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the application:
   ```bash
   python main.py
   ```
   Run `main.py` from the repository root; `ui/main_window.py` is an internal module and is not a standalone entry point. In VS Code, use the **Run JASC Data Processor** launch configuration.

## Development

The architecture strictly separates concerns:
- `core/`: State management, IO, and core validation.
- `math_engine/`: Data operations (calculus, FFT, curve-fitting logic).
- `models/`: Registries for math models and parameters.
- `ui/`: PySide6 view layer (Main window, plot canvas, dialogs).

See `Architecture.md` and `Roadmap.md` for architectural blueprints and project progression.
