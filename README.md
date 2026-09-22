# JASC Data Processor

A lightweight, modular application for data ingestion, visualization, mathematical operations, and curve fitting. Built with Python, PySide6, Pandas, and SciPy.

## Features

- **Data Ingestion**: Batch-import CSV/DAT/TXT data with delimiter, leading-metadata, and header preflight/inference, or select worksheet tabs from modern Excel `.xlsx`/`.xlsm` workbooks as value-only datasets with explicit warnings for unsupported workbook objects; data can also be entered manually in the spreadsheet interface.
- **Data Editing**: Edit imported datasets directly with bounded undo/redo, append/insert/delete row and column operations, fast block-oriented spreadsheet copy/paste, whole-column copy/paste, large-dataset warnings, sampled table auto-sizing, and per-column name/role/unit/long-name/comment metadata.
- **Formula Engine**: Apply safe math operations to columns using a sandboxed expression evaluator with NumPy/SciPy support, positional aliases such as `col1`, exact-name insertion helpers, worksheet batch targets, and protected output naming by default.
- **Signal Processing & Calculus**: Perform numerical differentiation, cumulative integration, FFT, and previewed smoothing with adjacent-average, median, Savitzky-Golay, LOWESS, FFT low-pass, or derivative-smoothing reconstruction.
- **Interpolation Workbench**: Generate 1D, 2D, and N-D prediction datasets with linear, spline, piecewise cubic, nearest-neighbor, and RBF methods.
- **Statistics Workbench**: Generate single-column summaries, multi-column summaries/correlations/covariance/PCA, grouped/factor analyses, normality tests, outlier checks, regression metrics, paired tests, independent-sample tests, one-way ANOVA, Kruskal-Wallis, post-hoc comparisons, and optional companion plots.
- **Curve Fitting**: Fit analytical models (Linear, Exponential, Gaussian, Peak functions, etc.) with customizable parameters using Levenberg-Marquardt or Trust-Region algorithms.
- **Custom Fit Models**: Define project-saved fit models from safe NumPy/SciPy expressions and use them in the standard fitting workflow.
- **Dynamic Plotting**: High-performance multi-axis plotting with Matplotlib, featuring data locators, scaling controls, SciencePlots journal styling, visual customization, error bars, reporting plots, histograms, box/violin distribution comparisons, and early interpolated 2D maps.
- **Saved Plots**: Start from a default empty plot, protect unsaved drafts with Save/Discard/Cancel before replacement, and store named definitions so series, locators, axes, legends, and sizing can be restored later.
- **Data Preparation**: Create non-destructive result sheets for filtering, sorting, duplicate removal, missing-value cleanup, binning, grouping, joins, and reshaping.
- **Docked Workspace Layout**: Keep datasets and saved plots in the workspace navigator, show plot controls in a plot-specific inspector, and give the Data editor the full central width.
- **Project Persistence**: Save and load complete workspaces, including datasets, column metadata, mathematical formulas, custom fit models, and saved plots using `.jasc` project files.

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
