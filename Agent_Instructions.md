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
- Current roadmap focus is Competitive Stage 0 stabilization followed immediately by Competitive Stage 1 operation recipes, batch processing, and cumulative outputs. Do not bury batch processing behind later plot/import work unless the user explicitly reprioritizes.
- The competitive roadmap in `Roadmap.md` was added after reviewing official Origin/OriginPro and SigmaPlot v16 feature areas on 2026-05-29. If those comparisons are updated later, re-check official vendor pages and refresh the source links in `Roadmap.md`.
- Competitive Stage 1 is now the priority batch-processing layer. Implement it as reusable operation recipes plus worksheet batch selection, visible column-binding previews, per-sheet outputs, cumulative outputs, and batch logs.
- Batch processing is not just "run same function on many sheets." Each operation family must define: recipe schema, compatibility check, column-binding strategy, per-sheet output behavior, cumulative output schema, batch-log fields, and project persistence.
- First batch implementation target: capture/reuse the last successful operation, then add `Repeat Last Operation on Worksheets...` with target-sheet selection, mapping preview, output naming, dry-run validation, progress/status, and a batch log dataset.
- Batch formula/calculated-column workflows should write or append target columns in each selected sheet and optionally create a cumulative summary with source sheet, target column, row count, finite count, missing/non-numeric count, min/max/mean, status, and warnings.
- First formula batch slice is implemented in `ColumnExpressionDialog`/`MainWindow._apply_column_formula()`: users can select target sheets, choose an explicit target-exists policy, choose Auto/Sequential/Parallel execution, apply the same formula to each selected sheet, and create a `{current}_formula_batch_summary` dataset. Existing target columns are protected by default through unique output names; explicit overwrite/update requires confirmation and should mention non-visible sheet undo limitations. This is not yet a full `OperationRecipe`; role/position remapping, saved recipe persistence, rerun UI, and workspace-level undo for non-visible sheets remain to be built.
- `core/batch_processing.py` contains the first reusable parallel batch layer. Keep process workers as top-level functions and keep task/result payloads pickle-friendly: plain dataclasses, DataFrames/Series, strings, numbers, and lists/dicts only. Do not send Qt widgets/models, bound methods, lambdas, local functions, open handles, or workspace objects into worker processes. `main.py` calls `multiprocessing.freeze_support()` and keeps Qt imports inside `main()` for future PyInstaller/Windows compatibility.
- Formula batch parallelism currently targets whole-sheet non-visible worksheets. The active worksheet stays on the visible model path so undo/redo remains correct; selected-row mode remains current-sheet only. Auto mode should stay conservative because process-based DataFrame pickling can be slower for small batches and memory-heavy for large ones.
- Formula expressions support positional aliases `col1`, `col2`, etc. for the first, second, etc. worksheet columns when the alias does not conflict with an existing name. `ColumnExpressionDialog` also has insert controls for either the positional alias or an exact `col("Column Name")` reference.
- Generated formula, derivative/integral, interpolation, FFT/iFFT, statistics, and curve-fit outputs now write a generated `Operation: ...` line into output column metadata comments. Preserve user-written comment lines and update generated operation lines through `set_column_operation_comment()` or `set_dataset_operation_comments()`.
- Large-dataset safeguards are size warnings and GUI responsiveness guards, not true out-of-core processing. `MainWindow` warns for imports above 100 MiB, DataFrames above 2,000,000 cells or 250 MiB estimated memory, large sheets inside opened projects, and skips full Data Editor column auto-sizing above 250,000 cells. Undo snapshots still deep-copy the active dataset.
- Large-data implementation order: keep batch processing as the main priority, but maintain the lightweight backend/profile boundary first so batch recipes do not assume every source is an editable Pandas DataFrame. Full DuckDB/PyArrow/Parquet large-dataset mode should follow the first usable batch workflow unless backend dispatch becomes a blocker sooner.
- `core/data_backends.py` now owns backend labels, large-data thresholds, `DatasetProfile`, DataFrame/file size profiling, and byte formatting. `Dataset.backend` is persisted in `.jasc` metadata and defaults to `pandas`. Keep new batch compatibility checks and future import warnings routed through this module/label rather than duplicating thresholds in UI code.
- Future large-dataset architecture should use Pandas for normal editable worksheets and DuckDB plus PyArrow/Parquet for read-only or limited-edit large datasets with preview/query/sample/materialize workflows. Do not swap Pandas globally or require Dask/Modin before the app has backend dispatch.
- Batch derivative/integral workflows now have an initial sequential implementation in `ColumnMathDialog`/`MainWindow._run_column_math_batch()`: users can select target sheets, choose the same unique/stop/overwrite target-column policy as formulas, repeat exact X/Y/method/initial-value settings across sheets, append/update result columns, preserve operation metadata comments, plot the active-sheet result when available, and create a cumulative summary dataset for multi-sheet runs. Missing columns fail per sheet and are recorded in the summary. This is still not a formal `OperationRecipe`; role/position remapping, saved recipe persistence, per-source result-sheet mode, workspace-level undo for non-visible sheets, progress/cancel UI, and optional parallel execution remain to be built.
- FFT/iFFT workflows now have an initial sequential batch implementation in `FFTDialog`/`IFFTDialog` plus `MainWindow._run_fft_batch()` / `_run_ifft_batch()`: users can select target sheets, repeat exact signal/spectrum bindings, create one result sheet per source, use `{source}` in result-sheet naming, preserve operation metadata comments, plot the active-source result when available, and create cumulative multi-sheet quality/log summaries. This is still not a formal `OperationRecipe`; role/position remapping, saved recipe persistence, progress/cancel UI, optional parallel execution, and richer spectral diagnostics remain to be built.
- Continue batch implementation sequentially by operation family. Recommended next slices: interpolation batch prediction sheets/cumulative prediction tables, then statistics cumulative long-format results, then curve-fitting cumulative parameter/metric summaries. Reuse the calculus and FFT patterns: add target-sheet controls to the existing dialog, validate exact-name compatibility first, apply per sheet without guessing, write operation metadata, create a tidy cumulative summary/log, and document remaining recipe/remapping/undo gaps.
- Batch statistics workflows must create per-source result sheets plus a required cumulative long-format result sheet with source sheet, operation, bindings, metric, value, p-value, notes, status, and warnings.
- Batch curve-fitting workflows must create per-source fit/residual outputs plus a required cumulative fit summary with source sheet, model, parameter values/errors, bounds/fixed state, R2/adjusted R2/RMSE/MAE, output sheets, status, and warnings.
- Batch FFT/iFFT and interpolation workflows should create per-source result sheets plus cumulative quality/metrics tables; interpolation can additionally stack predictions when all sheets share generated/manual query coordinates.
- Batch plotting should apply a saved plot template to compatible sheets and produce saved plot definitions plus an export/log table. Full graph templates can come later, but the recipe model should not block this path.
- Competitive Stage 2 has started with lightweight per-column metadata. Datasets now store role, unit, long name, and comment metadata per column; roles currently include `x`, `y`, `z`, `error`, `x_error`, `y_error`, `group`, `label`, and `weight`.
- Column metadata is edited through `ColumnMetadataDialog`, persisted in `.jasc`, included in Data Editor undo/redo snapshots, shown in table-header tooltips, preserved by in-app whole-column copy/paste, and used as default-selection hints by PlotTab plus derivative/integral/FFT/curve-fit dialogs.
- Column names are also edited through `ColumnMetadataDialog`; double-clicking a Data Editor column header opens that dialog focused on the clicked column. Keep column renames routed through `DataFrameTableModel.apply_column_metadata()` so formulas, metadata, undo/redo, and plot references stay aligned.
- PlotTab should keep metadata-derived axis labels visible in the Axes inspector fields, not only apply them during Matplotlib rendering. The current auto-label tracker may update blank/auto-filled labels but should not overwrite labels typed manually by the user.
- Before building advanced 3D/specialty plots, peak/signal workflows, advanced statistics, or global/peak/surface fitting, prefer extending this metadata layer instead of hard-coding positional column assumptions.
- Phase 2A subphase 4 (pie/donut charts with label/value roles, percentage controls, exploded slice controls, and saved-state persistence) remains important, but the first usable batch workflow now takes priority after stabilization.
- Longer-term competitive direction is now staged as: stabilization/test harness, operation recipes and batch cumulative outputs, workbook metadata and column roles, import/export connectors, data-prep workbench, graph templates/layout, analysis expansion, advanced statistics, global/peak/surface fitting, recalculation/templates/workflow automation, reporting/export, and performance/packaging/plugins.
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
