# JASC Data Processor

A lightweight, modular application for data ingestion, visualization, mathematical operations, and curve fitting. Built with Python, PySide6, Pandas, and SciPy.

## Features

- **Data Ingestion**: Import tabular datasets (CSV/TXT) with dynamic type detection, or manually enter data in a spreadsheet interface.
- **Data Editing**: Edit imported datasets directly with undo/redo, append/insert/delete row and column operations, spreadsheet-style copy/paste, whole-column copy/paste, large-dataset warnings, size-aware table auto-sizing, and per-column name/role/unit/long-name/comment metadata.
- **Formula Engine**: Apply safe math operations to columns using a sandboxed expression evaluator with NumPy/SciPy support, positional aliases such as `col1`, exact-name insertion helpers, worksheet batch targets, and protected output naming by default.
- **Signal Processing & Calculus**: Perform numerical differentiation, cumulative integration, and Fast Fourier Transforms (FFT).
- **Interpolation Workbench**: Generate 1D, 2D, and N-D prediction datasets with linear, spline, piecewise cubic, nearest-neighbor, and RBF methods.
- **Statistics Workbench**: Generate single-column summaries, multi-column summaries/correlations/covariance/PCA, grouped/factor analyses, normality tests, outlier checks, regression metrics, paired tests, independent-sample tests, one-way ANOVA, Kruskal-Wallis, post-hoc comparisons, and optional companion plots.
- **Curve Fitting**: Fit analytical models (Linear, Exponential, Gaussian, Peak functions, etc.) with customizable parameters using Levenberg-Marquardt or Trust-Region algorithms.
- **Custom Fit Models**: Define project-saved fit models from safe NumPy/SciPy expressions and use them in the standard fitting workflow.
- **Dynamic Plotting**: High-performance multi-axis plotting with Matplotlib, featuring data locators, scaling controls, SciencePlots journal styling, visual customization, error bars, reporting plots, histograms, box/violin distribution comparisons, and early interpolated 2D maps.
- **Saved Plots**: Store named plot definitions in the workspace so plot series, locators, axes, legends, and sizing can be restored later.
- **Docked Workspace Layout**: Keep datasets, saved plots, data tools, manual entry, and plot options in dockable panels so the central Data and Plot work areas stay focused.
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

## Development

The architecture strictly separates concerns:
- `core/`: State management, IO, and core validation.
- `math_engine/`: Data operations (calculus, FFT, curve-fitting logic).
- `models/`: Registries for math models and parameters.
- `ui/`: PySide6 view layer (Main window, plot canvas, dialogs).

See `Architecture.md` and `Roadmap.md` for architectural blueprints and project progression.
