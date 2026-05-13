# Session Changelog & State Tracker

> **Instructions for AI Agent**: 
> Read this file at the start of a session to understand current context.
> ALWAYS update this file at the end of your response to maintain state for the next session.

## 1. Project State
- **Current Version**: 0.1.0
- **Last Updated**: 2026-05-13
- **Current Phase**: Phase 5 (Polish & Packaging)

## 2. Completed Tasks
- [x] Initial project definition, tech stack selection, and requirements gathering.
- [x] Added `requirements.txt` with Phase 1-5 runtime dependencies.
- [x] Set up `main.py` with the PySide6 application loop.
- [x] Created the primary `QMainWindow` shell in `ui/main_window.py`.
- [x] Implemented `core/workspace.py` for managing multiple named DataFrames.
- [x] Implemented `core/file_io.py` for `.csv` and `.txt` imports using selectable delimiter and header options.
- [x] Added `ui/dialogs.py` with an import-options dialog.
- [x] Added `ui/data_table.py` with a spreadsheet-like manual entry tab and DataFrame export.
- [x] Added manual-entry clipboard support for `Ctrl+C`/`Ctrl+V` tabular data blocks.
- [x] Wired imported and manual datasets into a workspace list and editable data editor.
- [x] Added `ui/dataframe_model.py` for editing workspace DataFrames through a Qt table model.
- [x] Added selected-sheet export to CSV or tab-delimited TXT.
- [x] Added selected-row deletion for imported and manually created workspace datasets.
- [x] Added `core/operations.py` with a constrained Python-like expression evaluator for DataFrame columns.
- [x] Added an Apply Formula dialog for writing expressions into new or existing columns.
- [x] Added a formula cheatsheet directly inside the Apply Formula dialog.
- [x] Added Add Column actions for creating empty workspace columns before formulas.
- [x] Formula operations can update all rows or only the rows currently selected in the data editor.
- [x] Blocked `^` in formulas with a clear message to use Python exponentiation (`**`) instead.
- [x] Added per-dataset formula metadata so formula-generated columns remember their source expression.
- [x] Apply Formula now reloads the stored expression when a formula-backed target column is selected.
- [x] Data editor summaries include formula-column counts, and formula-backed column headers expose formula tooltips.
- [x] Expanded formulas with safe NumPy/SciPy namespaces: `np`, `scipy`, `sp`, `special`, `signal`, `stats`, and `integrate`.
- [x] Updated the formula cheatsheet with NumPy/SciPy examples and clarified that file IO/imports remain blocked.
- [x] Added `ui/plot_canvas.py` with embedded Matplotlib `FigureCanvasQTAgg` and `NavigationToolbar2QT`.
- [x] Added a Plot tab to the main window.
- [x] Added plot controls for X/Y dataset and column selection from the workspace.
- [x] Added support for queued multi-series plots, including series built from columns in different datasets.
- [x] Added basic plot customization for title, X/Y labels, line style, marker, color, and Matplotlib figure size.
- [x] Added linear/log scale controls for X, left Y, and right Y axes.
- [x] Added secondary right Y axis support with per-series axis assignment.
- [x] Added optional min/max plot ranges for X, left Y, and right Y axes.
- [x] Added a plot grid toggle.
- [x] Reorganized the plot lateral panel into tabs (Series, Axes, Locator) to improve navigation and layout.
- [x] Replaced the Guides tab with a Locator tab for interpolating Y at a user-provided X on a queued series.
- [x] Added locator marker customization for shape, size, and color.
- [x] Locator markers are drawn on the correct left/right Y axis and the computed Y values are shown in the locator list.
- [x] Reworked the main GUI layout so workspace datasheets and data-ingestion actions live together in the left sidebar.
- [x] Moved Manual Entry out of the main work tabs and into a sidebar Data Input tab next to Import.
- [x] Removed the top-toolbar Import action so the primary visible import path is next to the workspace list.
- [x] Kept the central work area focused on Data Editor and Plot tabs.
- [x] Added `math_engine/calculus.py` for Phase 3 derivative, integration, FFT, and inverse FFT operations.
- [x] Added derivative methods: NumPy gradient, forward difference, backward difference, central difference, and Savitzky-Golay.
- [x] Added integration methods: cumulative trapezoid, cumulative Simpson, left rectangle, right rectangle, and midpoint rectangle.
- [x] Added an integration initial value/constant so integrated derivative data can be offset back to the original signal level.
- [x] Added FFT result sheet generation with selectable window methods: rectangular, Hann, Hamming, Blackman, Bartlett, and flat top.
- [x] Added inverse FFT result sheet generation from real and optional imaginary spectrum columns.
- [x] Added Analysis menu actions and Data Editor buttons for Derivative, Integral, FFT, and iFFT.
- [x] Added Phase 3 operation dialogs for column/method/window/result-name selection.
- [x] Added a Data Editor button and Edit menu action to delete selected columns.
- [x] Added `models/fit_functions.py` with a reusable analytical fit-model registry for Phase 4.
- [x] Added `math_engine/curve_fitting.py` to connect registered models to `scipy.optimize.curve_fit`.
- [x] Added curve-fitting method selection for Levenberg-Marquardt, Trust Region Reflective, and Dogbox.
- [x] Added a Curve Fit dialog with X/Y column selection, model selection, initial-parameter entry, fit-point count, and result-sheet naming.
- [x] Added a full fit report dialog with fitted parameters, standard errors, covariance matrix, R^2, adjusted R^2, RMSE, MAE, and residual statistics.
- [x] Curve fitting now creates a new workspace result sheet and immediately plots raw data against the fitted curve.
- [x] Fixed cross-dataset plot-series labels so labels no longer fall through when X and Y come from different sheets.
- [x] Extracted plotting into `ui/plot_tab.py` and removed stale embedded plot code from `ui/main_window.py`.
- [x] Fixed workspace refresh after project open and dataset deletion so the data editor selects a valid sheet or clears itself.
- [x] Fixed plot state cleanup after project open, dataset rename, and dataset deletion.
- [x] Fixed the Plot tab scatter shortcut so it actually creates marker-only series.
- [x] Project saves now append `.jasc` when the user enters a filename without an extension.
- [x] Added Phase 4 fitting refinements: editable parameter initial values, lower/upper bounds, and fixed/free parameter controls.
- [x] Added weighted fitting through optional sigma/error or weight columns, including absolute-sigma handling.
- [x] Added confidence-band generation for fitted curves and confidence-band plotting in the plot canvas.
- [x] Added residual-sheet generation and optional residual plotting on the right Y axis for curve fits.
- [x] Added Phase 3 "plot result immediately" shortcuts for derivative, integral, FFT, and inverse FFT workflows.
- [x] Added per-series custom labels, line width, marker size, and edit/update controls in the Plot tab.
- [x] Exposed dataset Rename/Remove actions through sidebar buttons, the Data menu, and the main toolbar.
- [x] Ran smoke checks:
  - `python -m py_compile main.py ui/main_window.py ui/plot_canvas.py ui/dialogs.py ui/data_table.py ui/dataframe_model.py core/workspace.py core/file_io.py core/operations.py math_engine/__init__.py math_engine/calculus.py`
  - Core CSV import/workspace smoke test.
  - Qt offscreen `MainWindow` instantiation smoke test.
  - Qt offscreen manual-entry clipboard paste smoke test.
  - Data editor edit/delete/export smoke test.
  - Formula expression engine smoke test.
  - DataFrame model add-column/apply-formula smoke test.
  - Formula cheatsheet dialog smoke test.
  - Formula metadata storage/reload smoke test.
  - Expanded NumPy/SciPy formula namespace smoke test.
  - Matplotlib plot canvas smoke test.
  - Main-window plot tab/series smoke test.
  - Advanced plot canvas smoke test for log scales, right axis, and ranges.
  - Main-window advanced plot workflow smoke test.
  - Plot locator canvas interpolation smoke test.
  - Main-window plot locator workflow smoke test.
  - Sidebar data-input layout relocation smoke test.
  - Phase 3 math engine smoke test.
  - Phase 3 dialog smoke test.
  - Phase 3 main-window action smoke test.
  - Phase 3 handler smoke test for derivative and FFT.
  - Integral initial value recovery smoke test.
  - Integral handler initial value smoke test.
  - Phase 4 curve-fitting engine smoke test.
  - Phase 4 fit dialog/report smoke test.
  - Phase 4 main-window fit handler smoke test.
  - DataFrame model selected-column deletion smoke test.
  - Main-window selected-column deletion smoke test.
  - Main-window project-open refresh regression smoke test.
  - Main-window dataset-delete editor-clearing smoke test.
  - Plot tab scatter shortcut regression smoke test.
  - Project save suffix smoke test.
  - Fit handler smoke test using the extracted `PlotTab`.
  - Advanced curve-fit smoke test for bounds, fixed parameters, sigma weights, confidence bands, and residual output.
  - Enhanced fitting/options dialog smoke test.
  - Plot tab series add/edit smoke test for custom labels and style sizing.
  - Main-window curve-fit handler smoke test with residual sheet and residual overlay.
  - Derivative plot shortcut smoke test.
  - FFT plot shortcut smoke test.
  - Plot canvas legend-toggle and confidence-band smoke test.
  - Workspace menu/sidebar action enablement smoke test.
- [x] Added saved plot workspace state with named plot definitions.
- [x] Added a Saved Plots sidebar section and Plot menu actions for saving, loading, and removing current plot definitions.
- [x] Saved plot definitions now persist through `.jasc` project save/load metadata.
- [x] Saved plot definitions include series, locators, axes labels, scales, ranges, grid/legend settings, and figure size.
- [x] Dataset renames update saved plot dataset references.
- [x] Updated README project-persistence wording to include saved plots instead of fit reports.
- [x] Updated README Python minimum version to 3.10+ to match current type-hint syntax.
- [x] Polished saved plot editing so selecting a saved plot loads it into the Plot tab as the active editable plot.
- [x] Restored/generated plots now select the first queued trace so Series controls reflect the editable trace instead of stale controls from the previous plot.
- [x] Added File > Close Project to clear the current workspace, saved plots, active plot, and editor state without exiting the app.
- [x] Added an initial visual polish stylesheet with stronger button hover/pressed states, clearer list selection, tab framing, table headers, and section labels.
- [x] Removed duplicated Data Editor action buttons so sheet operations are concentrated in the main toolbar and menus.
- [x] Added hide/show controls for Workspace Datasheets and Saved Plots so the Data Input/manual-entry area can expand.
- [x] Added a Plot Options hide/show control so the Matplotlib canvas can use the full plot workspace.
- [x] Manual Entry columns now keep an interactive default width and use horizontal scrolling instead of shrinking to fit all columns.
- [x] Plot Options now opens at a wider usable default size and can be reset with the new View menu.
- [x] Added View > Reset View to Default (`Ctrl+Shift+R`) to restore sidebar sections, splitters, and plot option visibility.
- [x] Removed the non-functional "Scatter" shortcut button from the Plot tab.
- [x] Fixed Manual Entry button layout in the sidebar to prevent text from being cut off.
- [x] Reorganized the main toolbar into logical groups: Data Editor options (Add/Delete/Rename/Export) and Math Operations (Formula/Calculus/FFT/Fit).
- [x] Added "Add Row" capability to the Data Editor and integrated it into the toolbar and Data menu, with proper enablement state tied to dataset availability.
- [x] Renamed "Export Sheet" to "Export Dataset" across the UI for consistency.
- [x] Added support for an application window icon, loading from the `resources/logo.png` directory.
- [x] Added Manual Entry "Fill Range" for generating arithmetic X-style columns with start value, step, start row, and row count.
- [x] Replaced Manual Entry "Fill Formula" with "Table Size" because formula generation belongs in the Data Editor manipulation workflow after saving the manual sheet.
- [x] Added Manual Entry "Table Size" for setting explicit row and column counts.
- [x] Reworked Manual Entry controls into stacked rows with minimum button widths so button labels remain readable in the sidebar.
- [x] Rebalanced the GUI into clearer zones: project/import plus analysis shortcuts in the main toolbar, dataset editing actions in the Data Editor header, and plot actions in the Plot tab header.
- [x] Added checkable View menu actions for sidebar, Workspace Datasheets, Saved Plots, and Plot Options visibility, with Reset View restoring all panels.
- [x] Removed saved-plot action buttons from the sidebar so Saved Plots is primarily navigation and plot management lives with the Plot tab.
- [x] Removed the redundant sidebar Import tab now that import is available from the File menu and main toolbar; the sidebar data-entry area is dedicated to Manual Entry.


## 3. Active Bugs / Known Issues
- [ ] No runtime application bugs found in the previous smoke testing, but this session could not rerun Python checks because no usable Python launcher is available in the current shell.
- [ ] `git` is not available in the current shell, so worktree status could not be checked.
- [ ] Required analytical-model list mentions arbitrary n-th degree polynomial fitting, but the current fit registry only has linear, quadratic, and cubic polynomial models.
- [ ] There is no automated test suite or PyInstaller/spec packaging file in the repository yet.

## 4. Next Steps for Current/New Session (To-Do)
1. Install or activate usable `python` and `git` commands, then rerun the documented smoke checks and capture real worktree status.
2. Run `python main.py` in a normal desktop session and manually test project open/save, dataset rename/delete, selected-column deletion, derivative, integral, FFT, iFFT, curve fitting bounds/fixed/weights/confidence bands/residuals, and plot series editing on real datasets.
3. Begin Phase 5 polish: tighten spacing/text in the larger dialogs, review menu/toolbar ordering, and standardize button labels.
4. Add broader edge-case tests for unusual imported data, singular fits, non-monotonic X values, missing values, and project files with many sheets.
5. Resolve documentation/requirement drift: arbitrary n-th degree polynomial fitting.
6. Write the PyInstaller setup script for building the standalone `.exe`.

## 5. Architectural Context Notes
- File parsing lives in `core/file_io.py`; Qt file selection and dialogs live in the UI layer.
- `Workspace` stores copies of DataFrames under unique display names to avoid accidental mutation and naming collisions.
- Manual entry converts columns to numeric dtype only when every non-empty value in that column is numeric.
- Manual entry clipboard paste starts at the active cell and expands the table as needed.
- The workspace data editor writes cell edits directly to the selected dataset's DataFrame.
- Export currently writes UTF-8 CSV or tab-delimited TXT without the DataFrame index.
- Formula expressions expose valid Python-identifier columns directly (`x + y`) and all columns through `col("Column Name")`.
- Formula expressions include common NumPy functions/constants such as `sin`, `log`, `sqrt`, `where`, `pi`, and `np.pi`; arbitrary imports, attribute access, and statements are intentionally blocked.
- Formula exponentiation uses Python syntax (`**`); `^` is intentionally rejected to avoid accidental bitwise-XOR results.
- Formula metadata is currently in-memory project state: it is retained while the app session/dataset exists, but it is not yet exported with CSV/TXT files.
- Formula namespaces expose a curated NumPy/SciPy math/signal/stat/integration subset, including examples such as `np.gradient(x)`, `scipy.special.erf(x)`, `scipy.signal.savgol_filter(y, 11, 3)`, `stats.zscore(x)`, and `integrate.cumulative_trapezoid(y, x, initial=0)`.
- File-oriented helpers such as `np.load` are intentionally unavailable in formulas.
- Plotting UI and plot state live in `ui/plot_tab.py`; rendering primitives live in `ui/plot_canvas.py`.
- Saved plot definitions live in `Workspace` as JSON-friendly state dictionaries and are serialized in `.jasc` project metadata under `plots`.
- Cross-dataset plots currently align X/Y data by row order and truncate to the shorter column length before dropping non-numeric/blank points.
- Right-axis plotting is controlled per queued series; moving an already queued series currently means removing it and adding it again with the desired axis.
- Plot ranges are optional blank min/max fields; blank entries leave that side auto-scaled.
- Plot locators perform piecewise linear interpolation on the plotted numeric data after X/Y log-scale filtering and mark the computed point on the correct axis.
- Locator X values outside the plotted series X domain are skipped with a status warning rather than extrapolated.
- Main central tabs are now reserved for work surfaces (`Data Editor`, `Plot`); data creation/import lives in the left workspace sidebar.
- Phase 3 derivative/integral operations save results as new columns in the selected dataset.
- Cumulative integration starts from the user-selected initial value. Use the original first Y value as the initial value when integrating a derivative to reconstruct the original curve.
- Phase 3 FFT/iFFT operations save results as new workspace datasets because their output shape/columns differ from the source sheet.
- Curve fitting is implemented as the first Phase 4 pass, with model/method selection, fitted-curve datasets, immediate overlay plotting, and full text reports.
- Phase 4 curve fitting saves fitted curve points as a new workspace dataset with `fit_x` and `fit_y` columns.
- Running a fit replaces the current plot queue with the source data and fitted curve so the overlay is visible immediately.
- Fit parameters are edited in a table with initial values, optional lower/upper bounds, and fixed/free checkboxes.
- Curve fitting can use an optional sigma/error column or weight column; weight mode converts weights to sigma as `1/sqrt(weight)`.
- Confidence bands are stored as `fit_lower` and `fit_upper` in the fitted-curve dataset when enabled.
- Residual outputs are stored as a separate dataset with `x`, `observed`, `fitted`, and `residual` columns when enabled.
