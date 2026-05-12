# Session Changelog & State Tracker

> **Instructions for AI Agent**: 
> Read this file at the start of a session to understand current context.
> ALWAYS update this file at the end of your response to maintain state for the next session.

## 1. Project State
- **Current Version**: 0.1.0
- **Last Updated**: 2026-05-12
- **Current Phase**: Phase 2 (Plotting & Visualization)

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
- [x] Added plot guide/reference lines for X, left Y, and right Y axes using comma-separated numeric values.
- [x] Added a plot grid toggle.
- [x] Ran smoke checks:
  - `python -m py_compile main.py ui/main_window.py ui/plot_canvas.py ui/dialogs.py ui/data_table.py ui/dataframe_model.py core/workspace.py core/file_io.py core/operations.py`
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
  - Advanced plot canvas smoke test for log scales, right axis, ranges, and guide lines.
  - Main-window advanced plot workflow smoke test.

## 3. Active Bugs / Known Issues
- [ ] No application bugs found in smoke testing.
- [ ] `git` is not available in the current shell, so worktree status could not be checked.

## 4. Next Steps for Current/New Session (To-Do)
1. Run `python main.py` in a normal desktop session and manually test plotting one series, multiple series, columns from different datasets, log scales, right-axis series, ranges, and guide lines.
2. Add richer plot controls such as scatter-only mode, legend toggle/location, and per-series labels.
3. Add workspace management actions such as rename/remove dataset.
4. Consider adding copy/paste support to the main workspace data editor, matching the manual-entry table.
5. Once Phase 2 plotting is manually verified, begin Phase 3 data analysis operations such as derivative, integral, FFT, and iFFT.

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
- Plotting lives in `ui/plot_canvas.py`; main-window controls collect workspace column mappings and pass `PlotSeries` objects to the canvas.
- Cross-dataset plots currently align X/Y data by row order and truncate to the shorter column length before dropping non-numeric/blank points.
- Right-axis plotting is controlled per queued series; moving an already queued series currently means removing it and adding it again with the desired axis.
- Plot ranges are optional blank min/max fields; blank entries leave that side auto-scaled.
- Plot guide lines are comma-separated numeric values and are drawn as dashed reference lines.
