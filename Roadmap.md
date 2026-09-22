# Development Roadmap

> **Instructions for AI Agent**: Development must follow the active roadmap order unless the user explicitly reprioritizes. Keep the current phase functional and tested before opening a broad new feature family. Always update `ChangeLog_Session.md` and `Agent_Instructions.md` when the roadmap changes.

## Current Capability Baseline

Reviewed on 2026-09-18 against the current repository state, session changelog, and automated test suite.

### Implemented or Started
- Workspace and project state: multiple Pandas DataFrames, persisted dataset backend labels, unique dataset names, independent dataset and saved-plot duplication, `.jasc` save/load, saved plots, project-scoped custom fit models, current project path tracking, close project, and lightweight per-column metadata including role, type, units, precision, long name, and comments.
- Data ingestion and editing: single/multi-file CSV/DAT/TXT import with per-file delimiter, leading-metadata, header, names, and preview preflight; default Auto inference plus global explicit overrides and batch header-pattern conflict decisions; initial value-only `.xlsx`/`.xlsm` import with OOXML object warnings, worksheet-tab selection, hidden/chart-tab handling, and one dataset per selected sheet; XY-graph and 2D-colourplot raster digitization with immediate create-and-continue output, multiple curve/probe-set capture from one shared calibration, project-embedded resumable image/calibration sessions, and four-corner perspective correction; manual spreadsheet entry with Auto-typed blank columns; explicit arithmetic range fill plus selection-based Smart Fill for numeric linear/interleaved sequences, all day/month/year field orders with calendar/fixed-interval continuation, repeated categories, and user-entered ordered lists; editable Data Editor; positional odd/even/Every-N row and column subset extraction into new sheets; large file/dataset warnings; size-aware column auto-sizing; atomic worksheet row/column-count resizing; value-clearing Delete plus explicit structural deletion; formula metadata; operation provenance in column comments; column roles/types/units/precision/long names/comments; bounded undo/redo history; block, row, whole-column, and transposed clipboard operations; and right-click/double-click affordances across cells and headers.
- Formulas and transforms: constrained Python-like formula evaluator with curated NumPy/SciPy namespaces, direct/positional/exact column references, safe cross-worksheet `sheet("Worksheet", "Column")` references, explicit selected-cell or entire-column application, derivative/integral result columns, FFT/iFFT result sheets, and a first general interpolation workbench.
- Statistics: descriptive summaries, quantiles, diagnostics, normality tests, outlier checks, z-score/cumulative series, correlations, regression, agreement metrics, paired tests, independent-sample tests, multi-column summaries/correlations/covariance/PCA, grouped one-way analyses, post-hoc comparisons, and optional companion plots.
- Curve fitting: built-in analytical models, custom expression models, parameter guesses/bounds/fixed parameters, weighting/error columns, ODR for X/Y uncertainties, confidence bands, residual sheets, fit reports, and immediate fit overlay plots.
- Plotting: Matplotlib canvas and toolbar, saved plot definitions and duplication, multi-series XY plots, right Y axis, axis ranges/scales, per-axis label/tick typography, live-canvas clipboard copy, locators, SciencePlots styles, family/subtype plot selection, line/scatter/line+markers/errorbar, bar/barh/area/histogram with categorical label support, box/violin, initial pie/donut/Voronoi composition charts, early interpolated 2D maps, export-only physical sizing, and direct double-click editing of rendered labels, legends, axes, and series appearance.
- Interpolated 2D maps: X/Y/Z coordinate roles, heatmap/contour/filled contour rendering, linear/cubic-spline/piecewise-cubic interpolation, grid resolution, saved state, dataset rename support, and X/Y locator prediction of Z values.
- Batch workflows: dialog-based multi-sheet execution, exact-name and column-position bindings, preflight tables, multi-column expansion, cancelable modal progress, per-source outputs, and cumulative summaries are implemented for formulas, calculus, smoothing, FFT/iFFT, interpolation, statistics, and curve fitting. Formula batches have an initial process-worker path; the remaining long operations are still executed synchronously from the UI workflow.
- Verification and UI polish: 134 automated tests pass in the active Python environment, including Qt-offscreen workflow coverage. The interface has docked workspace/inspector panels, compact toolbar grouping, reset view, sidebar visibility controls, application icon, direct context actions, reliable cross-style numeric steppers, and theme-aware styling.

### Current Gaps
- The automated suite exists and is runnable, but core import, formula, calculus, interpolation, statistics, fitting, project-persistence, and end-to-end batch paths need broader regression coverage. Verification commands, linting, and repeatable manual smoke scripts are not yet documented as a complete developer gate.
- Long-running import and analysis workflows can still block the Qt event loop. Background execution with real progress/cancel is the immediate engineering priority.
- The app has project-level datasets and a first lightweight column-metadata layer, but not full Origin/SigmaPlot-style workbooks with matrix sheets, notes, reports, folders, cell comments, dependency graphs, or rich worksheet formatting.
- Import/export is narrow compared with current commercial tools.
- Plotting is strong for core 2D scientific charts but lacks multi-panel/page layouts, annotation tools, many specialized graph families, and true 3D graphing. Reusable plot/analysis templates are deliberately deferred to the final roadmap stage.
- Batch analysis exists but lacks semantic role binding, a uniform timestamped audit-log schema, true background execution for most operation families, and workspace-level undo for edits to non-visible sheets.
- Fitting lacks global multi-dataset fitting, dynamic/robust initial-guess search, peak analysis, surface fitting, and advanced model comparison.
- No PyInstaller specification or repeatable standalone Windows build exists yet.

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
- Add an Import From Figure workflow for raster image digitization into normal workspace datasets. (initial implementation complete)
- Implement manual spreadsheet creation with visible Workspace/File/toolbar entry points that create a normal editable Data-tab worksheet with default X/Y columns. (complete)
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
- Phase 4: add composition and categorical reporting plots: pie, donut, and Voronoi composition charts with label/value column roles, percentage labels, exploded slice or composition geometry controls, and saved-state persistence. (initial slice started: text/category X labels now work for bar/barh; the Plot Inspector now uses Plot family plus Subtype dropdowns; Pie/Donut render label/value composition charts; Voronoi Composition renders circular, rectangular, or polygonal value-weighted polygon partitions; percentage/exploded-slice, label-density, and more exact composition geometry controls remain)
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
- Harden the existing dialog-based batch execution and move long imports, transforms, statistics, fitting, interpolation, and FFT/iFFT work off the Qt UI thread with real progress/cancel and safe result commits. (current major implementation target)

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
| Import/connectors | Multi-file CSV/DAT/TXT with delimiter/metadata/header preflight, shared overrides, and mismatch decisions; CSV/TXT export; initial value-only `.xlsx`/`.xlsm` worksheet-tab import with unsupported-object preflight; XY/2D-colourplot digitization with precision zoom, ROI/color tracing, symbol matching, perspective correction, manual uncertainty, empirical colour-scale calibration, and multiple curve/probe-set capture per calibration | Missing Excel export, named/range-only mapping and metadata rows, legacy `.xls`, JSON/XML/HTML, HDF5/NetCDF/MATLAB, binary/instrument formats, ODBC/SQL, drag/drop, re-import/refresh, per-file batch parser overrides, plus digitizer point cleanup, overlap splitting, automatic multi-curve separation, discrete colour levels, automatic grid extraction, and OCR tick assistance |
| Data preparation | Formula columns, row/column operations, clipboard, filter/query, sort, duplicate removal, missing-value cleanup, binning, group/aggregate, merge/join, and reshape result sheets | Missing richer multi-condition filters, previews, type conversion, pivot tables, append/split tools, date/time parsing, resampling, and data reduction |
| Graphing breadth | Core 2D, distribution plots, early 2D maps, initial pie/donut/Voronoi composition charts, SciencePlots styles | Missing density families, grouped/categorical chart variants, polar/radar/ternary, waterfall, 3D scatter/surface/mesh/bars, specialized scientific diagrams, map overlays, images, and graph object editing |
| Graph layout | Single responsive canvas with saved/duplicable plots, right Y axis, direct element editing, and export-specific sizing | Missing page layout manager, multi-panel/multi-layer graph pages, linked axes, inset graphs, object manager, annotation tools, direct data labels, and graph galleries; reusable templates/themes are intentionally deferred |
| Analysis | Calculus, FFT/iFFT, advanced smoothing including derivative reconstruction, 1D/2D/N-D interpolation, statistics workbench | Missing broader filters, baseline correction, peak detection/integration, convolution/correlation, STFT, wavelets, 2D FFT, resampling workflows, ROI/gadget-style analysis, and analysis chains |
| Statistics | Useful first-pass reports, multi-column correlations/covariance/PCA summaries, grouped one-way analyses, post-hoc comparisons, and companion plots | Missing two-way/repeated-measures ANOVA, ANCOVA/MANOVA families, broader nonparametric families, clustering, survival/reliability, SPC/control charts, DOE, power/sample-size, ROC, probability/distribution fitting, and guided statistical advisor workflows |
| Fitting | Nonlinear and batch fits, ODR, custom models, weights, residuals, confidence bands, per-source outputs, and cumulative summaries | Missing global fitting with shared/local parameters, dynamic initial-guess search, robust model ranking, arbitrary polynomial degree UI, prediction bands, peak deconvolution, surface fitting, implicit fitting UI, constraints by expression, and background execution |
| Automation | Saved plots/projects, formula metadata, column roles, and initial dialog-based batch execution with previews and cumulative summaries | Missing role-aware binding, uniform audit logs, background workers, safe cross-sheet undo, operation history, recalculation, repeat-last-operation, scripting/API, and command log; reusable templates are deferred |
| Reporting/export | Dataset export and Matplotlib toolbar save | Missing report editor, PDF/Word/PowerPoint export workflows, SVG/PDF/EPS/EMF export presets, journal export profiles, graph page export, HTML/web reports, and project-wide slideshow/export |
| Performance/package | Pandas/Matplotlib desktop app with large-dataset warnings, sampled sizing, block clipboard updates, bounded snapshot history, streaming project reads, and an initial backend profile boundary | Missing background jobs with real cancellation, true large-data query/lazy loading, plot decimation, delta undo, autosave/recovery, installer/spec, sample projects, and CI fixtures |

## Step-by-Step Competitive Roadmap

### Competitive Stage 0: Stabilization Gate

Purpose: make future work safer before broad feature growth.

Completed foundation:
- A usable Python environment is available.
- The repository has a 121-test `unittest` suite and Qt-offscreen tests that instantiate `MainWindow` and exercise important worksheet, Excel import, plot, digitizer, and performance workflows.

Remaining tasks:
- Document one-command core and Qt verification paths in `README.md`.
- Add focused regression coverage for file import, formulas/calculus, interpolation, statistics, fitting, project persistence, and every batch operation family.
- Add `ruff` configuration and a documented lint/preflight command, retaining `git diff --check`.
- Add repeatable manual smoke scripts and identify the matching files under `Test_Data`.
- Resolve development dependency drift: declare the PDF generator dependency and deliberately support or constrain the Pandas/NumPy versions used by the active environment.

Acceptance criteria:
- A new agent can run one command to verify core non-GUI logic and one command to verify Qt smoke flows.
- Core operation and batch families have representative success, validation-failure, cancellation, and project-round-trip tests.
- Lint, diff integrity, automated tests, and manual smoke checks are documented as the standard preflight.

### Competitive Stage 1: Background Execution, Batch Processing, and Auditability

Purpose: keep the application responsive while existing operations run on one or many worksheets, with safe commits, visible mappings, and auditable outputs. Moving long operations off the Qt UI thread is the highest-priority implementation item after the short Stage 0 gate.

Current foundation:
- Formulas, derivative/integral, smoothing, FFT/iFFT, interpolation, statistics, and curve fitting already support multi-sheet execution through their existing dialogs.
- These workflows provide exact-name or column-position bindings, multi-column expansion where appropriate, preflight tables, per-source outputs, cumulative summaries, operation comments, and cancelable modal progress.
- Formula batches have the first PyInstaller-safe process-worker path. Most other long workflows still run synchronously and call `QApplication.processEvents()`; this is not a substitute for background execution.

Core architecture:
- Keep batch execution inside the existing operation dialogs rather than adding a separate recipe system for now.
- Each batch-capable dialog should let the user choose target worksheets, preview compatibility, inspect requested/resolved column mappings, choose output behavior, and run the batch from the same workflow.
- Column binding must support exact column names, column positions (`col1`, `col2`, ...), and column roles (`x`, `y`, `z`, `group`, `label`, `weight`, `x_error`, `y_error`), with visible warnings when fallback mapping is used.
- Operation inputs may be single-column or multi-column bindings. When a dialog accepts multiple source columns, batch execution should expand into one source-sheet/input-column or source-sheet/input-series job and write one cumulative summary row per expanded job.
- Every batch run must create a batch log dataset with source sheet, status, warning/error text, output dataset names, operation key, timestamp, and key parameters.
- Cumulative outputs should use a long/tidy table by default because it is easy to filter, pivot, plot, and export. Add wide/pivot summaries as optional convenience outputs for statistics and fitting where useful.
- Reusable recipes and graph/analysis templates are explicitly deferred to the final future stage. They are not prerequisites for responsive, auditable batch analysis.

Operation-by-operation implementation plan:
- Formula / calculated columns:
  - Batch mode applies the same expression to each selected worksheet.
  - Inputs are remapped by column name/role/position; target column can overwrite, append, or use a name template such as `{source}_{target}`.
  - Output remains in each target worksheet by default, with formula metadata preserved.
  - Cumulative output is a batch log plus optional per-sheet summary: source sheet, target column, row count, missing/non-numeric counts, min/max/mean of the generated column, and warnings.
  - Initial implementation started: `Apply Formula` can target multiple worksheets, applies the expression to each selected sheet, supports exact-name or column-position matching for formula inputs, shows a preflight preview, preserves formula metadata, protects existing target columns by default with unique output names, requires confirmation for explicit overwrite/update mode, supports cancelable sequential progress for non-parallel work, and creates a formula batch summary dataset when more than one sheet is selected. Role-based remapping and workspace-level undo for non-visible sheets remain follow-ups.
- Derivative and integral:
  - Batch mode repeats the same X/method/parameter choices across compatible sheets and can expand over one or more selected Y columns per sheet.
  - Output can append result columns to each source sheet or create per-source result sheets.
  - Cumulative output records source sheet, requested/resolved Y column, method, output column/sheet, row count, finite result count, min/max/mean, and integration initial value when relevant.
  - Initial implementation started: `Derivative` and `Integral` dialogs can target multiple worksheets, select multiple Y columns per worksheet, use exact-name or column-position matching for X/Y inputs, show preflight previews, use the same target-column conflict policy as formulas, append/update result columns on each selected sheet, support `{column}` target naming with automatic per-Y suffixing for multi-column runs, preserve operation provenance metadata, support cancelable sequential progress, plot the active-sheet result when available, and create `{current}_derivative_batch_summary` / `{current}_integral_batch_summary` datasets with one row per sheet/Y result. Role-based remapping, per-source result-sheet mode, workspace-level undo for non-visible sheets, background workers, and parallel workers remain follow-ups.
- FFT and iFFT:
  - Batch mode creates one spectrum/reconstruction result sheet per source and selected signal/real-spectrum column combination.
  - Cumulative output records source sheet, requested/resolved signal or spectrum columns, sample count, sample spacing, dominant frequency, dominant amplitude, total spectral power, and warnings.
  - Initial implementation started: `FFT` and `Inverse FFT` dialogs can target multiple worksheets, select multiple signal/real spectrum columns per worksheet, use exact-name or column-position matching for signal/spectrum inputs, show preflight previews, create per-source/per-column spectrum/reconstruction sheets, support `{source}` and `{column}` in result-sheet naming, preserve operation metadata comments, support cancelable sequential progress, plot the active-source result when available, and create cumulative `{current}_FFT_batch_summary` / `{current}_iFFT_batch_summary` datasets with one row per sheet/column result. Role-based remapping, background workers, optional parallel workers, and richer spectral diagnostics remain follow-ups.
- Interpolation:
  - Batch mode repeats the same coordinate bindings, method, smoothing/RBF parameters, outside-range policy, and query mode, and can expand over one or more selected value columns per sheet.
  - Create one per-source/per-value prediction sheet plus a cumulative run/quality table. Do not create a stacked raw prediction table by default: raw interpolation predictions are usually not comparable operation metrics and can become large/noisy.
  - Initial implementation started: `Interpolation` can target multiple worksheets, select multiple value columns per worksheet, use exact-name or column-position matching for coordinate/value/query columns, show preflight previews, create one prediction sheet per source/value result, support `{source}` and `{column}` result-sheet naming, preserve interpolation metadata/comments, support cancelable sequential progress, and create cumulative `{current}_interpolation_batch_summary` sheets with one row per sheet/value result. Role-based remapping, background workers, and optional parallel workers remain follow-ups.
- Statistics:
  - Batch mode repeats the same single-column, pair, multi-column, or grouped statistic across selected worksheets, and should expand over selected value/group/series columns where the statistic supports it.
  - Per-source result sheets are still created for inspection.
  - Cumulative output is required: source sheet, requested/resolved input columns or groups, operation, primary/secondary/group binding, metric, value, p-value, notes, and status.
  - Initial implementation started: `Statistics` can target multiple worksheets, select multiple primary/value columns for single and grouped statistics, pair one or many secondary columns by order for two-column statistics, match inputs by exact name or column position, show preflight previews, create one result sheet per source/column or source/multi-column job, use `{source}` and `{column}` result-sheet naming, preserve operation metadata comments, support cancelable sequential progress, plot the first active-source result when available, and create `{current}_statistics_batch_summary` with long-format cumulative rows containing source sheet, requested/resolved inputs, operation metadata, metric/result rows, p-values, notes, status/error text, output sheet, and elapsed seconds. Row-wise z-score/cumulative outputs are compacted in the batch summary, and metric/value outputs also create a `{current}_statistics_batch_wide_summary` pivot sheet when useful. Role-based remapping, background workers, and optional parallel workers remain follow-ups.
- Curve fitting:
  - Batch mode repeats the same model, method, initial parameters, bounds, fixed parameters, weighting/error bindings, confidence-band settings, and residual settings, and should allow one or more Y/response series per source sheet when they share the same X/model.
  - Per-source fit curve and optional residual sheets are still created.
  - Cumulative output is required: source sheet, requested/resolved response column, model, parameter, value, standard error, bounds/fixed state, R2, adjusted R2, RMSE, MAE, covariance availability, fit status, warning/error text, and output sheet names.
  - Initial implementation started: `Curve Fit` can target multiple worksheets, select multiple Y/response columns per worksheet, use exact-name or column-position matching for X/Y/error inputs, show preflight previews, pair Y weight/sigma columns as none/one/shared or one-per-Y by selection order, create fit and optional residual sheets per source/Y result, support `{source}` and `{column}` result naming, support cancelable sequential progress, plot the first active-source fit when available, optionally create long-format parameter covariance/correlation sheets, create `{current}_fit_reports` text-report export rows for batch runs, and create `{current}_fit_batch_summary` with one row per sheet/Y fit containing parameters, standard errors, bounds/fixed flags, covariance availability, metrics, warnings, and output sheet names. Role-based remapping, background workers, optional parallel workers, fit-correlation plots, and global/shared-parameter fitting remain follow-ups.
  - Later extend the same framework to global fitting with shared/local parameters across datasets.
- Future peak/signal/data-preparation workflows:
  - New tools must define compatibility checks, preview rows, per-source output, cumulative output, and batch-log fields before being considered batch-complete.

Implementation phases:
1. Add a shared background-job controller with progress, cooperative cancellation, controlled error propagation, close-window safety, and result handoff back to the Qt thread.
   - Use threads for I/O-bound import/export and orchestration.
   - Use top-level, pickle-friendly process workers for CPU-bound whole-sheet analysis when serialization cost is justified.
   - Never send Qt widgets/models, workspace objects, bound methods, lambdas, local functions, or open handles to worker processes.
   - Keep a conservative sequential fallback for process-startup, pickling, or frozen-build failures.
2. Move long imports, calculus/smoothing, FFT/iFFT, interpolation, statistics, and curve fitting off the UI thread. Worker results must be staged and committed on the UI thread.
3. Add cancellation and failure tests proving that partial or canceled jobs do not corrupt the workspace.
4. Add one shared column resolver supporting exact name, column position, and semantic role (`x`, `y`, `z`, `group`, `label`, `weight`, `x_error`, `y_error`). Every fallback or ambiguity must appear in preflight.
5. Standardize batch audit rows across operations: run ID, timestamp, operation key, serialized key parameters, source sheet/backend, requested/resolved inputs, output names, status, warnings/errors, elapsed time, and cancellation state.
6. Add workspace transactions or workspace-level undo for non-visible sheets before allowing background jobs to commit in-place edits.
7. Add operation-family batch tests covering mixed compatible/incompatible sheets, multi-column expansion, naming conflicts, cancellation, partial failure, metadata preservation, and project save/load.
8. Harden operation-specific diagnostics and summaries. Statistics/fitting retain tidy cumulative outputs; FFT/interpolation retain per-source result sheets plus compact quality summaries; formulas/calculus/smoothing retain per-sheet columns plus audit summaries.
9. Add rerun-failed-batch and project-level operation history only after the shared audit and transaction models are stable.

Acceptance criteria:
- Long-running work does not freeze the main window; progress remains visible and cancellation leaves the workspace consistent.
- A user can run an operation on one worksheet or many compatible worksheets and inspect a consistent success/failure/cancellation log.
- Statistics and fitting batches always produce cumulative result sheets suitable for filtering, plotting, and export.
- Formula/calculus batches can write results back to each target sheet without breaking undo/redo or column metadata.
- Column mapping is visible and editable before execution; ambiguous mappings never happen silently.
- Batch execution can use multiple CPU cores for compatible whole-sheet jobs without sending Qt objects, bound methods, lambdas, or open file handles to worker processes.
- Batch runs survive project save/load as auditable summaries; rerun UI remains optional follow-up work.

### Competitive Stage 2: Metadata-Rich Workbook Model

Purpose: build the data foundation needed for Origin/SigmaPlot-like workflows.

Tasks:
- Introduce dataset metadata: long name, units, comments, source file, import timestamp, role hints, and protected/read-only flags.
- Add column metadata: long name, units, comments, semantic role (`X`, `Y`, `Z`, `Y error`, `X error`, `label`, `group`, `weight`), explicit value type, and display precision/formatting hints. (foundation started: column rename plus role/type/precision/unit/long-name/comment editing, project persistence, undo/redo, column-copy preservation, table tooltips, plot-axis labels, plot-reference retargeting, plot/math/fitting/statistics/interpolation default column hints, and explicit numeric/text validation)
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
- Harden the image/figure data extraction module for digitizing plots from screenshots, papers, and instrument images. The current implementation supports XY graphs and 2D colourplots, pointer-centered zoom and magnification, pan/mode feedback, four-point perspective correction, four-point linear/log X/Y calibration, manual points and uncertainty, ROI-restricted dark/selected-colour tracing, connected-symbol barycentres, sampled-template matching with shape priors, empirical linear/log colour-bar calibration, colour probes with ambiguity/confidence diagnostics, multiple named curve/probe-set snapshots from one preserved calibration, previews, provenance metadata, and separate normal workspace outputs.
- Add editable extracted-point cleanup, stronger overlapping-symbol splitting, automatic multi-curve segmentation, axis de-skew/twist correction, OCR/tick-label assistance, explicit discrete/contour colour-level calibration, automatic colourplot grid sampling, richer uncertainty propagation, and repeatable manual smoke tests.
- Harden Excel support. (initial `.xlsx`/`.xlsm` value-only multi-sheet import complete with worksheet selection, hidden/chart-tab handling, cached-formula semantics, unsupported-object warnings, partial per-sheet failure handling, source provenance, and large-data prompts; Excel export, named/range-only mapping, metadata rows, import preview, and background execution remain)
- Add JSON, XML/HTML table, HDF5, NetCDF, MATLAB `.mat`, and Parquet import where dependencies are reasonable.
- Add ODBC/SQLite import with query preview; start with SQLite if full ODBC is too heavy.
- Add drag/drop import and recent import settings.
- Add re-import from source file and manual refresh; defer periodic refresh until Stage 9.
- Add export profiles for CSV/TXT/XLSX plus graph export presets for PNG, SVG, PDF, and EPS.

Acceptance criteria:
- A user can digitize a plotted curve from an image into calibrated X/Y data without leaving the app.
- A user can save multiple named curves or colour-probe sets from one figure without repeating image, axis, or colour-scale calibration, and import each as a separate dataset.
- A user can calibrate a continuous linear/log colour bar, probe a 2D colourplot into X/Y/Z values, and see confidence/ambiguity diagnostics.
- A user can import a multi-sheet Excel workbook into multiple datasets with clean names.
- Imported datasets remember enough source metadata for refresh.
- Exported graph files support publication-friendly vector output.

### Competitive Stage 4: Data Preparation Workbench

Purpose: make the app useful before analysis begins.

Tasks:
- Add sort, filter, query, positional subset/downsampling, duplicate removal, missing-value fill/drop/interpolate, and type conversion tools. (implemented first pass in the Data menu: Filter/Query, Extract Subset with independent odd/even/Every-N row and column rules, Sort, Remove Duplicates with match-column and keep-policy controls, Missing Values, Bin/Average, Group/Aggregate, Merge/Join, and Reshape; all create metadata-preserving result sheets where possible)
- Add stack/unstack, transpose, split columns, merge/join, append rows, group-by aggregate, and pivot table outputs. (implemented first pass: stack/melt, transpose, merge/join, and group-by aggregate; pivot tables, append rows, split columns, and richer reshape controls remain)
- Add text extraction/flash-fill-style helpers for mixed text/numeric columns.
- Add date/time parsing, resampling, rolling-window summaries, and data reduction/downsampling.
- Add conditional formatting and basic data-quality indicators in the Data Editor.

Acceptance criteria:
- Each operation creates an undoable change or a new result dataset.
- Operations record enough metadata to be repeated after parameter edits in Stage 9.
- Near-term Data Prep continuation: add preview row counts/sample rows, multiple AND/OR conditions, output-mode choices, batch application, type conversion, pivot tables, append rows, and split-column tools.

### Competitive Stage 5: Graphing and Layout Parity

Purpose: make plots feel like publishable scientific graph pages, not just traces.

The Plot Inspector final-state audit and recommended single-canvas polish sequence are documented in `Plot_Inspector_Final_State.md`. Complete that state/interaction, legend/typography, axes/grid/figure, and existing-plot-type polish before coupling the inspector to multi-panel page layout work.

Tasks:
- Finish Phase 2A subphases 4-7.
- Add a graph page layout editor for multi-panel/multi-layer figures, insets, linked axes, shared legends, and aligned panels.
- Add annotation tools: text, arrows, lines, rectangles, images, direct labels, legend ordering, and graph object selection.
- Add grouped/categorical charts, kernel density, ECDF, probability plots, forest plots, radar/polar, ternary, waterfall, and 3D scatter/surface/mesh/bar plots.
- Add colormap, colorbar, symbol, line pattern, font, and journal export preset editors.

Acceptance criteria:
- A saved graph page can include multiple panels with different plot types and reload exactly.
- Vector export preserves text and line quality.

### Competitive Stage 6: Analysis Workbench Expansion

Purpose: move from isolated math tools to a broad scientific analysis suite.

Tasks:
- Add smoothing tools: Savitzky-Golay, adjacent average, moving median, LOESS/LOWESS, FFT smoothing, and preview. (initial implementation complete, including batch worksheet/column application and derivative-smoothing-plus-integration reconstruction with optional endpoint preservation)
- Add filtering tools: Butterworth, Chebyshev, elliptic, Bessel, FIR/IIR design, band-pass/stop/high/low, and frequency response preview.
- Add baseline correction and subtraction methods for spectra and chromatograms.
- Add peak detection, peak area/height/FWHM tables, integration regions, and multi-peak summaries.
- Add interpolation/resampling tools for 1D and 2D data, including extrapolation controls. (foundation started: `Analysis > Interpolation` creates 1D, 2D, and N-D prediction datasets with generated, column-based, or manual query coordinates)
- Add signal tools: convolution, cross-correlation, autocorrelation, Hilbert transform, STFT, wavelet transforms, and 2D FFT.
- Add ROI/gadget-style analysis on plots, starting with rectangular range selection that outputs statistics and optional fitted summaries.

Acceptance criteria:
- Analysis outputs are datasets plus reports and can be plotted immediately.
- Parameter choices are stored for later operation-history and recalculation use in Stage 9.

### Competitive Stage 7: Advanced Statistics

Purpose: approach SigmaPlot/OriginPro statistical coverage in practical phases.

Tasks:
- Add companion plots for every statistical family, including assumptions, residuals, confidence intervals, and comparison summaries. (foundation started with optional histogram/box/violin/scatter/regression/Bland-Altman/result-series plots)
- Introduce group-aware statistics dialogs that can use one value column plus one group/factor column, not only one/two selected numeric columns. (initial implementation complete)
- Add one-way/two-way/repeated-measures ANOVA, ANCOVA, MANOVA where feasible, and multiple comparison procedures. (one-way ANOVA, Kruskal-Wallis, Tukey HSD, and pairwise Mann-Whitney foundation complete)
- Add nonparametric alternatives and assumption checks with guided recommendations.
- Add clustering, logistic regression, ROC curves, survival/reliability analysis, and distribution fitting. (PCA summary foundation complete)
- Add SPC/control charts and process capability reports.
- Add power/sample-size calculators.
- Add structured reports with plain-language assumptions, warnings, and interpretation notes.

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

### Competitive Stage 9: Operation History and Recalculation

Purpose: build on Stage 1 audit records so existing workflows become traceable and recalculating without introducing a template system.

Tasks:
- Add a full operation-history graph that records inputs, parameters, outputs, dependencies, status, and provenance without requiring a separate recipe workflow.
- Add manual/automatic recalculation modes for formulas, transforms, fits, statistics, and plots.
- Add repeat-last-operation and reopen-last-dialog commands.
- Add batch import, project-wide plot/export queues, rerun-failed-batch, and scheduled/queued batch workflows from the GUI.
- Add a scripting console/API and a command log; macro recording can follow once operations are represented consistently.

Acceptance criteria:
- Editing source data can update dependent results on demand or automatically.
- Operation history can explain what produced an output and safely repeat supported operations.

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

The measured performance findings and regression budgets are documented in `Large_Data_Performance_Audit.md`. Its local amplification fixes—single editor attachment/sizing, block clipboard updates, lazy clipboard inspection, bounded history, and streaming project reads—are implemented. Remaining work concerns background execution, delta undo, decimation, and the large-data backend.

Tasks:
- Remove redundant dataset editor refresh/column-sizing passes and replace automatic full-content sizing with bounded sampling plus an explicit user action. (single-pass attachment and bounded automatic sampling implemented; explicit manual fit action remains optional)
- Replace row-at-a-time/scalar clipboard paste with one block-oriented grow/normalize/assign path, and avoid parsing clipboard contents merely to construct a context menu. (implemented, including whole-column paste and Fill Range bulk growth)
- Introduce bounded, operation-specific undo storage before encouraging edits on larger in-memory worksheets. (bounded 20-entry/256 MiB snapshot first pass implemented; compact delta commands remain)
- Extend the Stage 1 background-job controller to large-data queries and decimated plot preparation.
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

### Competitive Stage 12: Deferred Templates and Extended Automation

Purpose: consider reusable templates only after background jobs, audit records, transactions, recalculation, packaging, and the main operation families are stable. This stage is deliberately outside the active and medium-term roadmap.

Possible tasks:
- Re-evaluate whether users still need separate analysis templates after operation history, repeat-last-operation, and dataset/plot duplication are mature.
- If justified, add role-aware graph appearance templates that are independent of source data.
- If justified, add reusable analysis configurations built on versioned operation schemas rather than dialog-state snapshots.
- Add optional template libraries, sharing/import, compatibility validation, and migration only after the underlying schemas are stable.

Acceptance criteria:
- Template work does not complicate or block earlier background execution, batch auditability, recalculation, or packaging milestones.
- Any template format is versioned, validates compatibility before applying changes, and can be removed without affecting normal saved projects.

## Near-Term Recommended Order

1. Close the small remaining Stage 0 gate: document verification commands, add missing core/batch smoke coverage, configure linting, define manual checks, and resolve dependency drift.
2. Build the shared Stage 1 background-job controller with real progress, cooperative cancellation, safe shutdown, UI-thread result commits, and sequential fallback.
3. Move long imports and the existing calculus, smoothing, FFT/iFFT, interpolation, statistics, and curve-fitting workflows off the Qt UI thread. This is the immediate development priority.
4. Add workspace transactions/undo for background and non-visible-sheet edits, then test cancellation, partial failures, and project consistency.
5. Complete semantic role binding and normalized timestamped audit logs across every batch-capable dialog.
6. Harden Excel support with background parsing, previews, named/range-only selection, metadata-row mapping, and `.xlsx` export.
7. Continue figure extraction with editable point cleanup, discrete/contour colour-level calibration, automatic colourplot grid sampling, overlap splitting, automatic multi-curve separation, and OCR-assisted calibration.
8. Extend Data Prep with previews, multi-condition AND/OR filters, explicit output modes, type conversion, pivot tables, append rows, split columns, date/time parsing, resampling, rolling summaries, and batch application.
9. Add the next signal-analysis family: digital filter design and response previews, baseline correction, peak detection/integration, convolution/correlation, Hilbert transform, STFT, wavelets, and 2D FFT.
10. Extend statistics and fitting with two-way/repeated-measures ANOVA, ANCOVA/MANOVA planning, clustering, logistic/ROC, survival/reliability, distribution fitting, arbitrary-degree polynomial fitting, model comparison, global fitting, peak fitting, and surface fitting.
11. Continue plotting with composition controls, regular/matrix/correlation heatmaps, 2D histograms, hexbin, colour/contour controls, engineering/time-series plots, annotations, and multi-panel page layouts. Reusable templates remain excluded from this stage.
12. After the main workflows are responsive and tested, continue DuckDB/PyArrow large-data mode, decimated plotting, delta undo, autosave/recovery, PyInstaller packaging, reporting, and plugin extension points.

Reusable graph/analysis templates are intentionally deferred to Competitive Stage 12 and must not displace the priorities above.
