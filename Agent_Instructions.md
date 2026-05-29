# System Instructions for AI Assistant (Codex)

## 1. Project Overview
**Role**: You are an expert Python developer specialized in PySide6, Pandas, Matplotlib, and SciPy.
**Goal**: Build a lightweight, performant data processing and visualization application, conceptually similar to SciDAVis or Origin.
**Tech Stack**:
- **GUI Framework**: PySide6 (Targeting standalone `.exe` deployment via PyInstaller)
- **Data Handling**: Pandas, NumPy
- **Math & Fitting Engine**: SciPy (`scipy.optimize`, `scipy.special`, `scipy.integrate`, `scipy.fft`)
- **Plotting**: Matplotlib (embedded in PySide6 using `FigureCanvasQTAgg` and `NavigationToolbar2QT`)

## 2. Core Functional Requirements

### A. Data Management & Workspace
- Maintain a central "Workspace" or "Project" state capable of holding multiple Pandas DataFrames simultaneously.
- Allow users to select columns from different loaded datasets to plot them together on the same canvas.

### B. Data Import & Entry
- **File Import**: Support `.csv` and `.txt`. Include smart parsing: allow the user to select delimiters (comma, semicolon, space, tab) and toggle header detection.
- **Manual Entry**: Implement a spreadsheet-like widget (`QTableWidget` or a custom `QAbstractTableModel` with `QTableView`) allowing users to create new sheets, name columns, and manually enter/edit data.

### C. Visualization & Plotting
- **Mapping**: UI elements (e.g., dropdowns/list widgets) to assign specific columns to X and Y axes.
- **Customization**: Controls for plot title, X/Y labels, line styles, marker styles, colors, and canvas dimensions.
- **Interactivity**: Integrate standard Matplotlib Navigation Toolbar (zoom, pan, save figure).

### D. Mathematical Operations
- **Calculus**: Numerical differentiation (derivative) and integration of selected data columns.
- **Signal Processing**: Fast Fourier Transform (FFT) and Inverse Fast Fourier Transform (iFFT) capabilities. Results should be displayable as new data columns or instant plots.

### E. Curve Fitting Engine
Implement a robust fitting module using `scipy.optimize.curve_fit`. The UI must allow users to select data, choose a model, guess initial parameters, and visualize the fit line against raw data. 
**Required Predefined Analytical Models**:
1. **Polynomial & Linear**: Linear, Quadratic, Cubic, Arbitrary n-th degree.
2. **Exponential & Power**: Single Exponential Growth/Decay, Double Exponential Decay, Stretched Exponential (Kohlrausch), Power Law.
3. **Peak Functions**: Gaussian, Lorentzian (Cauchy), Voigt / Pseudo-Voigt, Asymmetric Gaussian (Skewed).
4. **Sigmoidal & Step**: Logistic Curve, Gompertz Model, Error Function (erf).
5. **Oscillatory**: Sine/Cosine Wave, Damped Sine Wave.
6. **Specialized**: Heidler Function, Bessel Functions (1st & 2nd kind), Weibull Distribution, Log-Normal.

## 3. Coding Guidelines & AI Directives
- **Modularity**: DO NOT write monolithic code. Separate concerns (UI, Data Logic, Math Operations, Plotting) into different modules/files.
- **Type Hinting**: Use Python type hints for all function signatures.
- **Error Handling**: Use `try/except` blocks to handle malformed data, failed curve fits (`OptimizeWarning`), or unreadable files gracefully. Use PySide6 `QMessageBox` to inform the user of errors without crashing.
- **Documentation**: Write clear docstrings for complex math operations.
- **Session Continuity**: Always refer to `ChangeLog_Session.md` and `Roadmap.md` before starting new tasks, and update the changelog before ending your response.

## 4. Current Handoff Notes
- Current roadmap focus is Phase 2A Plot Type Expansion plus the newly added Origin/SigmaPlot competitive roadmap. Start with Competitive Stage 0 stabilization before large new feature families.
- The competitive roadmap in `Roadmap.md` was added after reviewing official Origin/OriginPro and SigmaPlot v16 feature areas on 2026-05-29. If those comparisons are updated later, re-check official vendor pages and refresh the source links in `Roadmap.md`.
- Competitive Stage 1 has started with lightweight per-column metadata. Datasets now store role, unit, long name, and comment metadata per column; roles currently include `x`, `y`, `z`, `error`, `x_error`, `y_error`, `group`, `label`, and `weight`.
- Column metadata is edited through `ColumnMetadataDialog`, persisted in `.jasc`, included in Data Editor undo/redo snapshots, shown in table-header tooltips, preserved by in-app whole-column copy/paste, and used as default-selection hints by PlotTab plus derivative/integral/FFT/curve-fit dialogs.
- Column names are also edited through `ColumnMetadataDialog`; double-clicking a Data Editor column header opens that dialog focused on the clicked column. Keep column renames routed through `DataFrameTableModel.apply_column_metadata()` so formulas, metadata, undo/redo, and plot references stay aligned.
- PlotTab should keep metadata-derived axis labels visible in the Axes inspector fields, not only apply them during Matplotlib rendering. The current auto-label tracker may update blank/auto-filled labels but should not overwrite labels typed manually by the user.
- Before building advanced 3D/specialty plots, peak/signal workflows, advanced statistics, or global/peak/surface fitting, prefer extending this metadata layer instead of hard-coding positional column assumptions.
- Phase 2A subphase 4 (pie/donut charts with label/value roles, percentage controls, exploded slice controls, and saved-state persistence) remains the next plot-type implementation target after verification.
- Longer-term competitive direction is now staged as: stabilization/test harness, workbook metadata and column roles, import/export connectors, data-prep workbench, graph templates/layout, analysis expansion, advanced statistics, global/peak/surface fitting, recalculation/templates/batch processing, reporting/export, and performance/packaging/plugins.
- New 2D-map request: Phase 2A subphase 5 foundation has started with Interpolated Heatmap, Contour, and Filled Contour plot types from X/Y/Z coordinate columns.
- Interpolated 2D maps expose linear, cubic spline, and piecewise cubic interpolation; coordinate locators accept X and Y inputs and report predicted Z/value results. Remaining follow-ups include regular-grid heatmaps, correlation heatmaps, 2D histograms, hexbin plots, color-map controls, and contour-level controls.
- General interpolation is now a separate Analysis workflow. `math_engine/interpolation.py` provides 1D, 2D, and N-D prediction helpers; `InterpolationDialog` exposes source coordinates, value column, method, smoothing, RBF epsilon, outside-range policy, generated ranges/grids, existing query columns, manual query coordinates, and result-sheet naming.
- `Analysis > Interpolation...` and the Data Inspector Interpolation button create a new prediction dataset rather than editing the source sheet. The output copies coordinate/value metadata where possible and uses `{value_column}_interpolated` for predictions.
- The interpolation workbench currently supports 1D linear/nearest/cubic spline/PCHIP/Akima/smoothing spline; 2D nearest/linear/cubic spline/piecewise cubic/smooth bivariate spline/RBF; and N-D nearest/linear/RBF. Generated query grids are capped at 1,000,000 points.
- Statistics now has optional companion plots. `StatisticsDialog` exposes "Create companion plot" and a scope-aware plot kind selector; `MainWindow._queue_statistics_companion_plot()` maps results to histograms with normal overlays, box/violin plots, scatter/regression plots, Bland-Altman plots, result-series plots, correlation heatmaps, or PCA variance plots.
- `PlotTab.queue_plot_series()` is the reusable entry point for prebuilt plot queues. Prefer it when future analysis workflows need editable/savable companion plots without duplicating PlotTab internals.
- Statistics supports a multi-column scope using two or more numeric columns from one sheet. Implemented multi-column operations include complete reports, per-column descriptive/distribution summaries, pairwise Pearson/Spearman/Kendall correlations, covariance values, and standardized PCA summaries.
- Statistics now supports a grouped scope: value column plus group/factor column. Implemented grouped operations include descriptive summaries, assumption checks, one-way ANOVA, Kruskal-Wallis, Tukey HSD, pairwise Mann-Whitney with Holm-adjusted p-values, and complete grouped reports.
- Advanced statistics should continue from the multi-column/grouped foundation toward two-way/repeated-measures ANOVA, ANCOVA/MANOVA, broader nonparametric families, clustering, logistic/ROC, survival, and distribution-fitting workflows.
- The Data Editor now has a right-click context menu on cells and horizontal column headers. Keep Undo/Redo, value copy/paste, and whole-column copy/paste wired through the existing `DataFrameTableModel` history so `Ctrl+Z`/`Ctrl+Y` remains consistent.
- Whole-column copy/paste uses the custom Qt MIME type `application/x-jasc-dataframe-columns` to preserve headers for in-app copies, with tab-delimited text fallback for external spreadsheet clipboard data.
- A usable Python interpreter is not currently available in the Codex shell; `python` resolves to the Microsoft Store launcher and currently fails with "A specified logon session does not exist", while `py` is not installed. Re-run compile/import and Qt smoke checks once Python is activated or installed.
