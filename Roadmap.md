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

### Phase 2A: Plot Type Expansion
- Add explicit plot type metadata and GUI selection so each queued series records how it should render.
- Phase 1: formalize current 2D plot modes as Line, Scatter, Line + Markers, and Errorbar while preserving saved-plot compatibility.
- Phase 2: add reporting plots that still map naturally to X/Y columns: vertical bar, horizontal bar, area/fill, and histogram.
- Phase 3: add distribution comparison plots that need multi-column capture: box plots and violin plots, with mean/median/outlier options.
- Phase 4: add composition and categorical reporting plots: pie and donut charts with label/value column roles and percentage label controls.
- Phase 5: add matrix and density visualization: heatmap, correlation heatmap, 2D histogram, hexbin, contour, and filled contour where data shape supports it.
- Phase 6: add engineering/time-series specialty plots: candlestick/OHLC with time, open, high, low, and close column roles.
- Phase 7: add multi-panel/subplot layouts so heterogeneous plot types can be arranged in one saved figure.
- For every plot type phase, ensure GUI controls only show relevant options, saved plots persist the new state, invalid column-role selections fail with clear messages, and the Matplotlib output is manually tested.

## Phase 3: Basic Math & Signal Processing
- Add menu options for Calculus (Derivative, Integral).
- Add menu options for FFT and iFFT.
- Add a statistics workbench for descriptive, distribution, correlation, regression, paired-test, and independent-test reports across columns and sheets.
- Ensure results from these operations can be saved as new columns in the workspace or plotted immediately.

## Phase 4: The Curve Fitting Engine
- Create the curve fitting dialog/UI.
- Implement the library of analytical functions (`models/fit_functions.py`).
- Link UI to `scipy.optimize.curve_fit`.
- Plot the fitted curve over the raw scatter data and display parameters (e.g., $R^2$, equation coefficients).
- Add project-saved custom fit models built from safe NumPy/SciPy expressions, with editable parameter lists, initial values, validation, and integration into the standard fit workflow.

## Phase 5: Polish & Packaging
- Refine the UI (menus, icons, layout).
- Perform error handling and edge-case testing.
- Write PyInstaller setup script to build the standalone `.exe`.
