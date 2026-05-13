# Development Roadmap

> **Instructions for AI Agent**: Development must strictly follow these phases. Do not jump ahead to future phases until the current one is fully functional and tested.

## Phase 1: Core Framework & Data Ingestion
- Set up `main.py` and the primary `QMainWindow`.
- Implement `core/workspace.py` to hold datasets.
- Implement file importing (`.csv`, `.txt`) with delimiter selection.
- Implement the manual spreadsheet entry tab.

## Phase 2: Plotting & Visualization
- Integrate Matplotlib `FigureCanvas` into the main window.
- Implement UI controls to select X and Y columns from the workspace.
- Add Matplotlib navigation toolbar.
- Implement plot customization (titles, colors, labels).

## Phase 3: Basic Math & Signal Processing
- Add menu options for Calculus (Derivative, Integral).
- Add menu options for FFT and iFFT.
- Ensure results from these operations can be saved as new columns in the workspace or plotted immediately.

## Phase 4: The Curve Fitting Engine
- Create the curve fitting dialog/UI.
- Implement the library of analytical functions (`models/fit_functions.py`).
- Link UI to `scipy.optimize.curve_fit`.
- Plot the fitted curve over the raw scatter data and display parameters (e.g., $R^2$, equation coefficients).

## Phase 5: Polish & Packaging
- Refine the UI (menus, icons, layout).
- Perform error handling and edge-case testing.
- Write PyInstaller setup script to build the standalone `.exe`.