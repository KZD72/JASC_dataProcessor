# Development Roadmap

> **Instructions for AI Agent**: Development must follow the active roadmap order unless the user explicitly reprioritizes. Keep the current phase functional and tested before opening a broad new feature family. Always update `ChangeLog_Session.md` and `Agent_Instructions.md` when the roadmap changes.

## Current Capability Baseline

Reviewed on 2026-05-29 against the current repository state and session changelog.

### Implemented or Started
- Workspace and project state: multiple Pandas DataFrames, persisted dataset backend labels, unique dataset names, `.jasc` save/load, saved plots, project-scoped custom fit models, current project path tracking, close project, and lightweight per-column metadata.
- Data ingestion and editing: CSV/TXT import with delimiter/header options, manual spreadsheet entry, table sizing, fill range, editable Data Editor, large file/dataset warnings, size-aware column auto-sizing, add/insert/delete/rename rows and columns, formula metadata, operation provenance in column comments, column roles/units/long names/comments, undo/redo history, value clipboard, whole-column clipboard, and right-click/double-click metadata affordances.
- Formulas and transforms: constrained Python-like formula evaluator with curated NumPy/SciPy namespaces, direct/positional/exact column references, row-scoped or full-column formula application, derivative/integral result columns, FFT/iFFT result sheets, and a first general interpolation workbench.
- Statistics: descriptive summaries, quantiles, diagnostics, normality tests, outlier checks, z-score/cumulative series, correlations, regression, agreement metrics, paired tests, independent-sample tests, multi-column summaries/correlations/covariance/PCA, grouped one-way analyses, post-hoc comparisons, and optional companion plots.
- Curve fitting: built-in analytical models, custom expression models, parameter guesses/bounds/fixed parameters, weighting/error columns, ODR for X/Y uncertainties, confidence bands, residual sheets, fit reports, and immediate fit overlay plots.
- Plotting: Matplotlib canvas and toolbar, saved plot definitions, multi-series XY plots, right Y axis, axis ranges/scales, locators, SciencePlots styles, line/scatter/line+markers/errorbar, bar/barh/area/histogram, box/violin, and early interpolated 2D maps.
- Interpolated 2D maps: X/Y/Z coordinate roles, heatmap/contour/filled contour rendering, linear/cubic-spline/piecewise-cubic interpolation, grid resolution, saved state, dataset rename support, and X/Y locator prediction of Z values.
- UI polish: docked workspace and inspector panels, compact toolbar grouping, reset view, sidebar visibility controls, application icon, and docstrings across core modules.

### Known Baseline Gaps
- Python and Qt smoke tests could not be rerun in the current Codex shell because no usable Python launcher is available.
- No automated regression test suite or packaging/spec file exists yet.
- The app has project-level datasets and a first lightweight column-metadata layer, but not full Origin/SigmaPlot-style workbooks with matrix sheets, notes, reports, folders, cell comments, dependency graphs, or rich worksheet formatting.
- Import/export is narrow compared with current commercial tools.
- Plotting is strong for core 2D scientific charts but lacks broad template/layout/page/report workflows, many specialized graph families, and true 3D graphing.
- Analysis operations exist but are mostly individual dialogs, not reusable recipes with batch execution, cumulative outputs, recalculation, or audit logs.
- Fitting lacks global multi-dataset fitting, dynamic/robust initial-guess search, peak analysis, surface fitting, and advanced model comparison.

## Competitive Reference Points

Official sources checked on 2026-05-29:
- Origin and OriginPro features: https://www.originlab.com/origin
- Origin 2026 release announcement: https://www.originlab.com/index.aspx?go=COMPANY%2FNEWSANDEVENTS%2FPRESSROOM&pid=5481
- SigmaPlot v16 overview: https://grafiti.com/sigmaplot-v16/
- SigmaPlot v16 new features: https://grafiti.com/sigmaplot-v16/sigmaplot-whats-new/
- SigmaPlot product features: https://grafiti.com/sigmaplot-detail/sigmaplot-product-features/
- SigmaPlot curve fitting/regression: https://grafiti.com/sigmaplot-detail/curve-fitting-regression/

The benchmark products emphasize:
- Many built-in graph types, graph templates/themes, multi-panel/multi-axis pages, 3D surfaces/meshes, publication export, and interactive graph editing.
- Metadata-rich workbooks, worksheet formulas, data filters, pivot/reduce tools, matrix data, notes, reports, folders, and project search.
- Import connectors for Excel, databases/ODBC, JSON/XML/HTML, HDF5/NetCDF/MATLAB, instrument formats, re-import/refresh, and batch import.
- Analysis templates, automatic/manual recalculation, batch processing, repeat-last-operation workflows, operation copying, and GUI automation.
- Peak analysis, baseline correction, signal smoothing/filtering/wavelets/STFT, 2D transforms, survival/reliability/statistical process control, PCA/ANCOVA/ANOVA families, and guided statistical reports.
- Global/dynamic curve fitting, automatic initial-parameter search, shared/local fit parameters, confidence/prediction bands, model ranking, arbitrary equations, and surface fitting.
- Report editors, Word/PowerPoint/PDF workflows, notebook-style project containers, macros/scripting, large-data performance, and plugin/app ecosystems.

## Active Roadmap

### Phase 1: Core Framework and Data Ingestion
- Set up `main.py` and the primary `QMainWindow`. (complete)
- Implement `core/workspace.py` to hold datasets. (complete)
- Implement file importing (`.csv`, `.txt`) with delimiter selection. (complete)
- Implement the manual spreadsheet entry tab. (complete)
- Add spreadsheet-style workspace Data Editor affordances for undo/redo, value copy/paste, and whole-column copy/paste from menus, shortcuts, and context menus. (complete)

### Phase 2: Plotting and Visualization
- Integrate Matplotlib `FigureCanvas` into the main window. (complete)
- Implement UI controls to select X and Y columns from the workspace. (complete)
- Add Matplotlib navigation toolbar. (complete)
- Implement plot customization for titles, colors, labels, and figure size. (complete)
- Add SciencePlots journal/preset styling to the live plot canvas and saved plot definitions. (complete)

### Phase 2A: Plot Type Expansion
- Add explicit plot type metadata and GUI selection so each queued series records how it should render. (complete)
- Phase 1: formalize current 2D plot modes as Line, Scatter, Line + Markers, and Errorbar while preserving saved-plot compatibility. (complete)
- Phase 2: add reporting plots that still map naturally to X/Y columns: vertical bar, horizontal bar, area/fill, and histogram. (complete)
- Phase 3: add distribution comparison plots that need multi-column capture: box plots and violin plots, with mean/median/outlier options. (complete)
- Phase 4: add composition and categorical reporting plots: pie and donut charts with label/value column roles, percentage labels, exploded slice controls, and saved-state persistence. (next)
- Phase 5: add matrix and density visualization.
  - Interpolated irregular X/Y/Z heatmap, contour, filled contour, interpolation choices, grid resolution, and X/Y to Z locator prediction. (initial implementation complete)
  - Follow-ups: regular-grid heatmaps, matrix heatmaps, correlation heatmaps, 2D histograms, hexbin plots, color-map controls, colorbar controls, contour-level controls, masking of invalid regions, and export-friendly legends.
- Phase 6: add engineering/time-series specialty plots: candlestick/OHLC with time, open, high, low, close, volume, and style controls.
- Phase 7: add multi-panel/subplot layouts so heterogeneous plot types can be arranged in one saved figure.
- For every plot type phase, ensure GUI controls only show relevant options, saved plots persist the new state, invalid column-role selections fail with clear messages, and the Matplotlib output is manually tested.

### Phase 3: Basic Math and Signal Processing
- Add menu options for Calculus (Derivative, Integral). (complete)
- Add menu options for FFT and iFFT. (complete)
- Add a general interpolation workbench for 1D, 2D, and N-D prediction datasets. (initial implementation complete)
- Add a statistics workbench for descriptive, distribution, correlation, regression, paired-test, independent-test, multi-column, and grouped/factor reports across columns and sheets. (complete)
- Add optional companion plots for statistics outputs, including distribution, comparison, scatter/regression, Bland-Altman, and result-series plots. (initial implementation complete)
- Ensure results from these operations can be saved as new columns in the workspace or plotted immediately. (complete)
- Add operation recipes and batch execution so formulas, transforms, statistics, fitting, interpolation, FFT/iFFT, and plots can be repeated across compatible worksheets with cumulative outputs. (next major implementation target)

### Phase 4: Curve Fitting Engine
- Create the curve fitting dialog/UI. (complete)
- Implement the library of analytical functions (`models/fit_functions.py`). (complete, except arbitrary n-th polynomial)
- Link UI to SciPy fitting backends. (complete)
- Plot fitted curves over raw scatter data and display parameters, metrics, covariance, residuals, and confidence bands. (complete)
- Add project-saved custom fit models built from safe NumPy/SciPy expressions. (complete)

### Phase 5: Polish and Packaging
- Refine UI menus, icons, layout, and inspector workflows. (in progress)
- Perform error handling and edge-case testing. (in progress)
- Write PyInstaller setup script to build the standalone `.exe`. (not started)

## Competitive Gap Matrix

| Area | Current JASC Status | Gap Versus Origin/SigmaPlot-Level Tools |
| --- | --- | --- |
| Data model | Multiple DataFrames with formulas and lightweight column metadata | No full workbook/sheet hierarchy, matrix sheets, notes/reports, project folders, cell comments, dataset-level metadata, rich formatting, or protected data |
| Import/connectors | CSV/TXT with options; CSV/TXT export | Missing Excel multi-sheet/ranges, JSON/XML/HTML, HDF5/NetCDF/MATLAB, binary/instrument formats, ODBC/SQL, drag/drop, re-import, periodic refresh, import themes, and batch import |
| Data preparation | Formula columns, row/column operations, clipboard, some statistics outputs | Missing sort/filter/query, data filters, pivot/group/aggregate, stack/unstack, join/merge, reshape, split text/flash fill, missing-value workflows, date/time parsing tools, duplicate handling, and data reduction |
| Graphing breadth | Core 2D, distribution plots, early 2D maps, SciencePlots styles | Missing pie/donut, density families, grouped/categorical charts, polar/radar/ternary, waterfall, 3D scatter/surface/mesh/bars, specialized scientific diagrams, map overlays, images, and graph object editing |
| Graph layout | Single canvas with saved plot queue and right Y axis | Missing page layout manager, multi-panel/multi-layer graph pages, linked axes, inset graphs, graph templates/themes, object manager, annotation tools, direct labels, graph galleries, and plot cloning |
| Analysis | Calculus, FFT/iFFT, 1D/2D/N-D interpolation, statistics workbench | Missing smoothing workbench, filters, baseline correction, peak detection/integration, convolution/correlation, STFT, wavelets, 2D FFT, resampling workflows, ROI/gadget-style analysis, and analysis chains |
| Statistics | Useful first-pass reports, multi-column correlations/covariance/PCA summaries, grouped one-way analyses, post-hoc comparisons, and companion plots | Missing two-way/repeated-measures ANOVA, ANCOVA/MANOVA families, broader nonparametric families, clustering, survival/reliability, SPC/control charts, DOE, power/sample-size, ROC, probability/distribution fitting, and guided statistical advisor workflows |
| Fitting | Nonlinear fits, ODR, custom models, weights, residuals, confidence bands | Missing global fitting with shared/local parameters, dynamic initial-guess search, robust model ranking, arbitrary polynomial degree UI, prediction bands, peak deconvolution, surface fitting, implicit fitting UI, constraints by expression, and batch fitting |
| Automation | Saved plots, saved projects, formula metadata, and column-role hints | Missing operation recipes, batch application across compatible worksheets, cumulative result sheets, operation history graph, automatic/manual recalculation locks, templates for analysis and graphing, repeat-last-operation, macro recorder, scripting console/API, plugins, and command log |
| Reporting/export | Dataset export and Matplotlib toolbar save | Missing report editor, PDF/Word/PowerPoint export workflows, SVG/PDF/EPS/EMF export presets, journal export profiles, graph page export, HTML/web reports, and project-wide slideshow/export |
| Performance/package | Pandas/Matplotlib desktop app with large dataset warnings and editor auto-size guards | Missing true large-data strategy, lazy/chunked loading, preview import, background jobs, progress/cancel, memory profiling, smarter undo storage, autosave/recovery, installer/spec, sample projects, and automated CI/test fixtures |

## Step-by-Step Competitive Roadmap

### Competitive Stage 0: Stabilization Gate

Purpose: make future work safer before broad feature growth.

Tasks:
- Install or activate a usable Python runtime for the Codex/dev shell.
- Add a minimal automated smoke-test suite for import, workspace editing, formulas, plotting state, fitting, statistics, and project save/load.
- Add a Qt offscreen smoke-test harness that can instantiate `MainWindow`, load sample data, and exercise key menu actions.
- Add `ruff`/formatting or at least a documented lint command, plus `git diff --check` as a required preflight.
- Document sample datasets and repeatable manual verification scripts.

Acceptance criteria:
- A new agent can run one command to verify core non-GUI logic and one command to verify Qt smoke flows.
- Current Data Editor context-menu work, interpolated 2D-map work, and general interpolation workbench are tested.
- Known runtime blocker is removed from `ChangeLog_Session.md`.

### Competitive Stage 1: Operation Recipes, Batch Processing, and Cumulative Outputs

Purpose: turn JASC from a collection of one-off tools into a lab/R&D workbench where an analysis defined once can be applied to many compatible worksheets with clear per-sheet and cumulative outputs.

Core architecture:
- Introduce an `OperationRecipe` model that records operation family, operation key/model, input bindings, parameters, output naming templates, column-matching strategy, cumulative-output strategy, and source compatibility requirements.
- Keep recipes backend-aware from the start: record whether a source is an in-memory Pandas worksheet, a future DuckDB/Parquet large dataset, or another backend, plus whether the operation can run in-place, must materialize selected columns, or can run as a query.
- Capture recipes from completed dialogs where practical: formula, derivative/integral, FFT/iFFT, interpolation, statistics, curve fitting, and plot generation.
- Add a `Batch Processing...` workflow that starts from a selected recipe or the last successful operation, then lets the user choose target worksheets, preview compatibility, override column mappings, choose output behavior, and run the batch.
- Column binding must support exact column names, column roles (`x`, `y`, `z`, `group`, `label`, `weight`, `x_error`, `y_error`), and positional fallback, with visible warnings when fallback mapping is used.
- Every batch run must create a batch log dataset with source sheet, status, warning/error text, output dataset names, operation key, timestamp, and key parameters.
- Cumulative outputs should use a long/tidy table by default because it is easy to filter, pivot, plot, and export. Add wide/pivot summaries later as optional views.
- Persist reusable recipes and recent batch runs in `.jasc` project metadata with backward-compatible loading.

Operation-by-operation implementation plan:
- Formula / calculated columns:
  - Batch mode applies the same expression to each selected worksheet.
  - Inputs are remapped by column name/role/position; target column can overwrite, append, or use a name template such as `{source}_{target}`.
  - Output remains in each target worksheet by default, with formula metadata preserved.
  - Cumulative output is a batch log plus optional per-sheet summary: source sheet, target column, row count, missing/non-numeric counts, min/max/mean of the generated column, and warnings.
  - Initial implementation started: `Apply Formula` can target multiple worksheets, applies the expression to each selected sheet, preserves formula metadata, protects existing target columns by default with unique output names, requires confirmation for explicit overwrite/update mode, and creates a formula batch summary dataset when more than one sheet is selected. Formal recipe persistence, role/position remapping, and workspace-level undo for non-visible sheets remain follow-ups.
- Derivative and integral:
  - Batch mode repeats the same X/Y/method/parameter choices across compatible sheets.
  - Output can append result columns to each source sheet or create per-source result sheets.
  - Cumulative output records source sheet, input columns, method, output column/sheet, row count, finite result count, min/max/mean, and integration initial value when relevant.
  - Initial implementation started: `Derivative` and `Integral` dialogs can target multiple worksheets, use the same target-column conflict policy as formulas, append/update result columns on each selected sheet, preserve operation provenance metadata, plot the active-sheet result when available, and create `{current}_derivative_batch_summary` / `{current}_integral_batch_summary` datasets for multi-sheet runs. Formal recipe persistence, role/position remapping, per-source result-sheet mode, workspace-level undo for non-visible sheets, progress/cancel UI, and parallel workers remain follow-ups.
- FFT and iFFT:
  - Batch mode creates one spectrum/reconstruction result sheet per source.
  - Cumulative output records source sheet, signal/spectrum columns, sample count, sample spacing, dominant frequency, dominant amplitude, total spectral power, and warnings.
  - Initial implementation started: `FFT` and `Inverse FFT` dialogs can target multiple worksheets, reuse exact signal/spectrum column names across sheets, create per-source spectrum/reconstruction sheets, support `{source}` in result-sheet naming, preserve operation metadata comments, plot the active-source result when available, and create cumulative `{current}_FFT_batch_summary` / `{current}_iFFT_batch_summary` datasets for multi-sheet runs. Formal recipe persistence, role/position remapping, progress/cancel UI, optional parallel workers, and richer spectral diagnostics remain follow-ups.
- Interpolation:
  - Batch mode repeats the same coordinate/value bindings, method, smoothing/RBF parameters, outside-range policy, and query mode.
  - For shared generated/manual query coordinates, create one per-source prediction sheet and an optional cumulative prediction table keyed by source sheet and query coordinates.
  - For worksheet-specific query columns, create per-source prediction sheets plus a cumulative run/quality table.
- Statistics:
  - Batch mode repeats the same single-column, pair, multi-column, or grouped statistic across selected worksheets.
  - Per-source result sheets are still created for inspection.
  - Cumulative output is required: source sheet, operation, primary/secondary/group binding, metric, value, p-value, notes, and status.
  - Add optional wide summary/pivot output later for common metrics such as mean, standard deviation, p-values, ANOVA F/H statistics, PCA variance ratios, and post-hoc comparisons.
- Curve fitting:
  - Batch mode repeats the same model, method, initial parameters, bounds, fixed parameters, weighting/error bindings, confidence-band settings, and residual settings.
  - Per-source fit curve and optional residual sheets are still created.
  - Cumulative output is required: source sheet, model, parameter, value, standard error, bounds/fixed state, R2, adjusted R2, RMSE, MAE, covariance availability, fit status, warning/error text, and output sheet names.
  - Later extend the same framework to global fitting with shared/local parameters across datasets.
- Plot generation:
  - Batch mode applies a saved plot template to each compatible sheet or compatible group of sheets.
  - Outputs are saved plot definitions per source sheet and optionally queued graph export jobs.
  - Cumulative output is a plot/export log with source sheet, saved plot name, template name, render status, and export file path when applicable.
- Future peak/signal/data-preparation workflows:
  - New tools must define their recipe schema, compatibility check, per-source output, cumulative output, and batch-log fields before being considered complete.

Implementation phases:
1. Add a lightweight dataset backend/profile boundary before the formal recipe model grows further, so batch code does not assume every source is an editable Pandas DataFrame. (started: `core/data_backends.py` plus persisted `Dataset.backend`)
2. Add a reusable batch execution layer before broadening batch operations: top-level worker functions, serializable task/result dataclasses, conservative Auto/Sequential/Parallel execution choices, PyInstaller-compatible Windows spawn behavior, and sequential fallback when process startup or pickling fails. (started: `core/batch_processing.py` plus Apply Formula execution controls)
3. Add a lightweight `OperationRecipe` and `BatchRunResult` model in the core layer, plus JSON-friendly project persistence.
4. Implement column-binding and compatibility-check helpers using name, role, and positional fallback.
5. Add a first `Repeat Last Operation on Worksheets...` dialog with target worksheet selection, mapping preview, output naming, and dry-run validation.
6. Implement batch formula/calculated-column and derivative/integral first because they exercise in-place column outputs. (initial slices started)
7. Implement batch statistics and curve fitting next because they require cumulative result aggregation and are the highest-value lab/R&D workflows.
8. Add batch interpolation next; FFT/iFFT now has an initial sequential result-sheet batch slice.
9. Add batch plot-template application and graph export queues.
10. Add saved named recipes, recipe editing, rerun failed sheets, and project-level operation history.

Acceptance criteria:
- A user can run an operation on one worksheet, repeat it on many compatible worksheets, and inspect a clear success/failure log.
- Statistics and fitting batches always produce cumulative result sheets suitable for filtering, plotting, and export.
- Formula/calculus batches can write results back to each target sheet without breaking undo/redo or column metadata.
- Column mapping is visible and editable before execution; ambiguous mappings never happen silently.
- Batch execution can use multiple CPU cores for compatible whole-sheet jobs without sending Qt objects, bound methods, lambdas, or open file handles to worker processes.
- Batch operations can be saved in `.jasc` and rerun after reopening the project.

### Competitive Stage 2: Metadata-Rich Workbook Model

Purpose: build the data foundation needed for Origin/SigmaPlot-like workflows.

Tasks:
- Introduce dataset metadata: long name, units, comments, source file, import timestamp, role hints, and protected/read-only flags.
- Add column metadata: long name, units, comments, semantic role (`X`, `Y`, `Z`, `Y error`, `X error`, `label`, `group`, `weight`), and formatting hints. (foundation started: column rename plus role/unit/long-name/comment editing, project persistence, undo/redo, column-copy preservation, table tooltips, plot-axis labels, plot-reference retargeting, and plot/math/fitting default column hints)
- Add optional project folders/groups so datasets, plots, reports, and analysis outputs can be organized.
- Add notes/report items to the workspace model, even if the first UI is simple text.
- Persist metadata and project structure in `.jasc` with backward-compatible loading.
- Add project search over dataset names, columns, notes, formulas, and saved plot names.

Acceptance criteria:
- Existing projects open unchanged.
- Metadata survives save/load and appears in Data Editor headers/tooltips.
- Plot and analysis dialogs can filter or suggest columns by role.

### Competitive Stage 3: Import, Export, and Data Connectors

Purpose: close the most visible data-ingestion gap.

Tasks:
- Add Excel import/export with multi-sheet selection, named ranges or row/column ranges, and metadata row mapping.
- Add JSON, XML/HTML table, HDF5, NetCDF, MATLAB `.mat`, and Parquet import where dependencies are reasonable.
- Add ODBC/SQLite import with query preview; start with SQLite if full ODBC is too heavy.
- Add drag/drop import and recent import settings.
- Add re-import from source file and manual refresh; defer periodic refresh until Stage 9.
- Add export profiles for CSV/TXT/XLSX plus graph export presets for PNG, SVG, PDF, and EPS.

Acceptance criteria:
- A user can import a multi-sheet Excel workbook into multiple datasets with clean names.
- Imported datasets remember enough source metadata for refresh.
- Exported graph files support publication-friendly vector output.

### Competitive Stage 4: Data Preparation Workbench

Purpose: make the app useful before analysis begins.

Tasks:
- Add sort, filter, query, duplicate removal, missing-value fill/drop/interpolate, and type conversion tools.
- Add stack/unstack, transpose, split columns, merge/join, append rows, group-by aggregate, and pivot table outputs.
- Add text extraction/flash-fill-style helpers for mixed text/numeric columns.
- Add date/time parsing, resampling, rolling-window summaries, and data reduction/downsampling.
- Add conditional formatting and basic data-quality indicators in the Data Editor.

Acceptance criteria:
- Each operation creates an undoable change or a new result dataset.
- Operations record enough metadata to be repeated after parameter edits in Stage 9.

### Competitive Stage 5: Graphing and Layout Parity

Purpose: make plots feel like publishable scientific graph pages, not just traces.

Tasks:
- Finish Phase 2A subphases 4-7.
- Add plot templates/themes that store graph appearance independent of data.
- Add a graph page layout editor for multi-panel/multi-layer figures, insets, linked axes, shared legends, and aligned panels.
- Add annotation tools: text, arrows, lines, rectangles, images, direct labels, legend ordering, and graph object selection.
- Add grouped/categorical charts, kernel density, ECDF, probability plots, forest plots, radar/polar, ternary, waterfall, and 3D scatter/surface/mesh/bar plots.
- Add colormap, colorbar, symbol, line pattern, font, and journal export preset editors.

Acceptance criteria:
- A saved graph page can include multiple panels with different plot types and reload exactly.
- A graph template can be applied to a different dataset with compatible roles.
- Vector export preserves text and line quality.

### Competitive Stage 6: Analysis Workbench Expansion

Purpose: move from isolated math tools to a broad scientific analysis suite.

Tasks:
- Add smoothing tools: Savitzky-Golay, adjacent average, moving median, LOESS/LOWESS, FFT smoothing, and preview.
- Add filtering tools: Butterworth, Chebyshev, elliptic, Bessel, FIR/IIR design, band-pass/stop/high/low, and frequency response preview.
- Add baseline correction and subtraction methods for spectra and chromatograms.
- Add peak detection, peak area/height/FWHM tables, integration regions, and multi-peak summaries.
- Add interpolation/resampling tools for 1D and 2D data, including extrapolation controls. (foundation started: `Analysis > Interpolation` creates 1D, 2D, and N-D prediction datasets with generated, column-based, or manual query coordinates)
- Add signal tools: convolution, cross-correlation, autocorrelation, Hilbert transform, STFT, wavelet transforms, and 2D FFT.
- Add ROI/gadget-style analysis on plots, starting with rectangular range selection that outputs statistics and optional fitted summaries.

Acceptance criteria:
- Analysis outputs are datasets plus reports and can be plotted immediately.
- Parameter choices are stored for later recalculation/template use in Stage 9.

### Competitive Stage 7: Advanced Statistics

Purpose: approach SigmaPlot/OriginPro statistical coverage in practical phases.

Tasks:
- Add statistics companion plot templates for every statistical family, including assumptions, residuals, confidence intervals, and comparison summaries. (foundation started with optional histogram/box/violin/scatter/regression/Bland-Altman/result-series plots)
- Introduce group-aware statistics dialogs that can use one value column plus one group/factor column, not only one/two selected numeric columns. (initial implementation complete)
- Add one-way/two-way/repeated-measures ANOVA, ANCOVA, MANOVA where feasible, and multiple comparison procedures. (one-way ANOVA, Kruskal-Wallis, Tukey HSD, and pairwise Mann-Whitney foundation complete)
- Add nonparametric alternatives and assumption checks with guided recommendations.
- Add clustering, logistic regression, ROC curves, survival/reliability analysis, and distribution fitting. (PCA summary foundation complete)
- Add SPC/control charts and process capability reports.
- Add power/sample-size calculators.
- Add report templates with plain-language assumptions, warnings, and interpretation notes.

Acceptance criteria:
- Each statistical test produces a structured result dataset and human-readable report.
- Assumption violations are surfaced with recommended alternative tests.

### Competitive Stage 8: Advanced Fitting, Peak Fitting, and Surface Fitting

Purpose: close the high-value analysis gap for research users.

Tasks:
- Add arbitrary n-th degree polynomial fit UI.
- Add prediction bands and robust model-comparison metrics such as AIC, BIC, and likelihood-derived criteria where applicable.
- Add global multi-dataset fitting with shared/local parameters and per-dataset weights.
- Add dynamic initial-guess search and multi-start fitting for difficult nonlinear fits.
- Add constraints by expression and parameter tying.
- Add peak analyzer workflow: baseline, peak finding, multi-peak model selection, deconvolution, area reports, and batch peak fitting.
- Add 2D/surface fitting for X/Y/Z data, including polynomial surfaces, 2D Gaussian peaks, residual surface plots, and contour overlays.

Acceptance criteria:
- Users can fit multiple datasets with shared parameters and inspect per-dataset residuals.
- Peak and surface fitting workflows produce reproducible reports and plots.

### Competitive Stage 9: Recalculation, Templates, and Workflow Automation

Purpose: build on Stage 1 recipes so workflows become editable, recalculating, template-driven, and scriptable.

Tasks:
- Extend the Stage 1 recipe model into a full operation-history graph that records inputs, parameters, outputs, dependencies, status, and provenance.
- Add manual/automatic recalculation modes for formulas, transforms, fits, statistics, and plots.
- Add analysis templates that can be applied to compatible datasets.
- Add graph templates and cloneable graph workflows using column roles/names.
- Add repeat-last-operation and reopen-last-dialog commands.
- Add batch import, advanced batch plot/export, rerun-failed-batch, and scheduled/queued batch workflows from GUI.
- Add a scripting console/API and a command log; macro recording can follow once operations are represented consistently.

Acceptance criteria:
- Editing source data can update dependent results on demand or automatically.
- A template created from one project can process another compatible dataset without hand rebuilding every step.

### Competitive Stage 10: Reporting and Publication Workflow

Purpose: turn data, graphs, and analyses into final deliverables inside the app.

Tasks:
- Add report pages that can contain text, result tables, plots, images, and linked analysis values.
- Add PDF and HTML report export.
- Add Word/PowerPoint export paths if dependency and platform choices are acceptable.
- Add project-wide graph export, slideshow, and selected-plot export queues.
- Add journal presets for figure size, fonts, DPI, color mode, and vector/raster format.

Acceptance criteria:
- A report can be saved in `.jasc`, update linked values after recalculation, and export to PDF.
- A user can export all publication-ready figures from a project in one command.

### Competitive Stage 11: Performance, Packaging, and Extensibility

Purpose: make the app robust outside the development environment.

Tasks:
- Add background workers with progress/cancel for imports, fitting, statistics, and large plots.
- Add a large-data backend based first on DuckDB plus PyArrow/Parquet, keeping Pandas as the default editable backend for small and medium worksheets.
- Add lazy loading or chunked import for large text/Excel/HDF5 files.
- Add row/column import limits, sampling previews, and user-selectable load strategies for very large delimited files.
- Add a read-only paged table model for DuckDB/Parquet-backed datasets, then add limited materialize-to-Pandas workflows for selected rows/columns.
- Add backend-aware operation dispatch: DuckDB/Polars-style query execution for simple filters, summaries, grouped statistics, and transforms; materialize selected columns for SciPy-heavy fitting/interpolation/statistical tests.
- Add plot decimation/downsampling for interactive rendering.
- Replace whole-DataFrame undo snapshots with delta-based or bounded-history undo for large sheets.
- Add autosave, crash recovery, and project backups.
- Add PyInstaller spec, icons/resources, version metadata, and a repeatable Windows build command.
- Add plugin/app extension points for importers, analysis operations, plot types, and fit models.
- Add sample projects, tutorial datasets, and user documentation.

Acceptance criteria:
- Large-data workflows remain responsive.
- A 10 GB source file can be opened as a preview/queryable large dataset without loading the full table into Pandas memory.
- Large datasets can be sampled, filtered, summarized, plotted through downsampled/materialized views, and exported without breaking normal Pandas worksheets.
- A signed or at least repeatable `.exe` build can be produced from a clean checkout.
- Third-party feature additions can be registered without editing core UI code.

## Near-Term Recommended Order

1. Finish Competitive Stage 0 so the current feature set can be verified reliably.
2. Add the lightweight dataset backend/profile boundary that lets batch recipes carry source-backend capability without implementing full DuckDB/Parquet large mode yet.
3. Start Competitive Stage 1 immediately: operation recipes, worksheet batch selection, column-binding previews, batch logs, and cumulative outputs.
4. Implement the first batch MVP for formula/calculated columns and derivative/integral because they exercise in-place worksheet outputs.
5. Implement batch statistics and batch curve fitting next because cumulative result sheets are the major lab/R&D productivity gain.
6. Continue Competitive Stage 2 metadata/workbook work as needed to strengthen column matching, source metadata, notes, and project organization.
7. Complete Phase 2A subphase 4 (pie/donut) and Phase 2A subphase 5 matrix/density follow-ups after the first batch workflow is usable.
8. Implement Stage 3 Excel import/export because it unlocks real-world multi-file and multi-sheet workflows for batching.
9. Implement the full DuckDB/PyArrow large-dataset backend after the first batch workflow and import/export foundations are stable, or earlier only if batch implementation starts requiring backend dispatch.
10. Start Stage 5 graph templates/layout after batch plot-template application and column roles exist.
11. Start Stage 9 recalculation/templates after operation recipes and batch outputs are stable.
