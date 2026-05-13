# JASC Data Processor

A lightweight, modular application for data ingestion, visualization, mathematical operations, and curve fitting. Built with Python, PySide6, Pandas, and SciPy.

## Features

- **Data Ingestion**: Import tabular datasets (CSV/TXT) with dynamic type detection, or manually enter data in a spreadsheet interface.
- **Formula Engine**: Apply safe math operations to columns using a sandboxed expression evaluator supporting standard numpy/scipy operations.
- **Signal Processing & Calculus**: Perform numerical differentiation, cumulative integration, and Fast Fourier Transforms (FFT).
- **Curve Fitting**: Fit analytical models (Linear, Exponential, Gaussian, Peak functions, etc.) with customizable parameters using Levenberg-Marquardt or Trust-Region algorithms.
- **Dynamic Plotting**: High-performance multi-axis plotting with Matplotlib, featuring data locators, scaling controls, and visual customization.
- **Saved Plots**: Store named plot definitions in the workspace so plot series, locators, axes, legends, and sizing can be restored later.
- **Project Persistence**: Save and load complete workspaces, including datasets, mathematical formulas, and saved plots using `.jasc` project files.

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
