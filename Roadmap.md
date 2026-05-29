# Development Roadmap

> **Instructions for AI Agent**: Development must follow the active roadmap order unless the user explicitly reprioritizes. Keep the current phase functional and tested before opening a broad new feature family. Always update `ChangeLog_Session.md` and `Agent_Instructions.md` when the roadmap changes.

## Current Capability Baseline

Reviewed on 2026-05-29 against the current repository state and session changelog.

### Implemented or Started
- Workspace and project state: multiple Pandas DataFrames, unique dataset names, `.jasc` save/load, saved plots, project-scoped custom fit models, current project path tracking, close project, and lightweight per-column metadata.
- Data ingestion and editing: CSV/TXT import with delimiter/header options, manual spreadsheet entry, table sizing, fill range, editable Data Editor, add/insert/delete/rename rows and columns, formula metadata, column roles/units/long names/comments, undo/redo history, value clipboard, whole-column clipboard, and right-click/double-click metadata affordances.
- Formulas and transforms: constrained Python-like formula evaluator with curated NumPy/SciPy namespaces, row-scoped or full-column formula application, derivative/integral result columns, FFT/iFFT result sheets, and a first general interpolation workbench.
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
- Analysis operations exist but are mostly individual dialogs, not reusable recalculating operation graphs/templates.
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
| Automation | Saved plots, saved projects, formula metadata | Missing operation history graph, automatic/manual recalculation locks, templates for analysis and graphing, repeat-last-operation, batch processing, macro recorder, scripting console/API, plugins, and command log |
| Reporting/export | Dataset export and Matplotlib toolbar save | Missing report editor, PDF/Word/PowerPoint export workflows, SVG/PDF/EPS/EMF export presets, journal export profiles, graph page export, HTML/web reports, and project-wide slideshow/export |
| Performance/package | Pandas/Matplotlib desktop app | Missing large-data strategy, lazy loading, background jobs, progress/cancel, memory profiling, autosave/recovery, installer/spec, sample projects, and automated CI/test fixtures |

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

### Competitive Stage 1: Metadata-Rich Workbook Model

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

### Competitive Stage 2: Import, Export, and Data Connectors

Purpose: close the most visible data-ingestion gap.

Tasks:
- Add Excel import/export with multi-sheet selection, named ranges or row/column ranges, and metadata row mapping.
- Add JSON, XML/HTML table, HDF5, NetCDF, MATLAB `.mat`, and Parquet import where dependencies are reasonable.
- Add ODBC/SQLite import with query preview; start with SQLite if full ODBC is too heavy.
- Add drag/drop import and recent import settings.
- Add re-import from source file and manual refresh; defer periodic refresh until Stage 7.
- Add export profiles for CSV/TXT/XLSX plus graph export presets for PNG, SVG, PDF, and EPS.

Acceptance criteria:
- A user can import a multi-sheet Excel workbook into multiple datasets with clean names.
- Imported datasets remember enough source metadata for refresh.
- Exported graph files support publication-friendly vector output.

### Competitive Stage 3: Data Preparation Workbench

Purpose: make the app useful before analysis begins.

Tasks:
- Add sort, filter, query, duplicate removal, missing-value fill/drop/interpolate, and type conversion tools.
- Add stack/unstack, transpose, split columns, merge/join, append rows, group-by aggregate, and pivot table outputs.
- Add text extraction/flash-fill-style helpers for mixed text/numeric columns.
- Add date/time parsing, resampling, rolling-window summaries, and data reduction/downsampling.
- Add conditional formatting and basic data-quality indicators in the Data Editor.

Acceptance criteria:
- Each operation creates an undoable change or a new result dataset.
- Operations record enough metadata to be repeated after parameter edits in Stage 7.

### Competitive Stage 4: Graphing and Layout Parity

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

### Competitive Stage 5: Analysis Workbench Expansion

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
- Parameter choices are stored for later recalculation/template use in Stage 7.

### Competitive Stage 6: Advanced Statistics

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

### Competitive Stage 7: Advanced Fitting, Peak Fitting, and Surface Fitting

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

### Competitive Stage 8: Recalculation, Templates, and Batch Processing

Purpose: make workflows reproducible and reusable.

Tasks:
- Introduce an operation-history model that records inputs, parameters, outputs, and dependencies.
- Add manual/automatic recalculation modes for formulas, transforms, fits, statistics, and plots.
- Add analysis templates that can be applied to compatible datasets.
- Add graph templates and cloneable graph workflows using column roles/names.
- Add repeat-last-operation and reopen-last-dialog commands.
- Add batch import, batch plot, batch analysis, and batch export from GUI.
- Add a scripting console/API and a command log; macro recording can follow once operations are represented consistently.

Acceptance criteria:
- Editing source data can update dependent results on demand or automatically.
- A template created from one project can process another compatible dataset without hand rebuilding every step.

### Competitive Stage 9: Reporting and Publication Workflow

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

### Competitive Stage 10: Performance, Packaging, and Extensibility

Purpose: make the app robust outside the development environment.

Tasks:
- Add background workers with progress/cancel for imports, fitting, statistics, and large plots.
- Add lazy loading or chunked import for large text/Excel/HDF5 files.
- Add plot decimation/downsampling for interactive rendering.
- Add autosave, crash recovery, and project backups.
- Add PyInstaller spec, icons/resources, version metadata, and a repeatable Windows build command.
- Add plugin/app extension points for importers, analysis operations, plot types, and fit models.
- Add sample projects, tutorial datasets, and user documentation.

Acceptance criteria:
- Large-data workflows remain responsive.
- A signed or at least repeatable `.exe` build can be produced from a clean checkout.
- Third-party feature additions can be registered without editing core UI code.

## Near-Term Recommended Order

1. Finish Competitive Stage 0 so the current feature set can be verified reliably.
2. Complete Phase 2A subphase 4 (pie/donut) and manually smoke-test all existing plot types.
3. Finish Phase 2A subphase 5 follow-ups for matrix/density maps.
4. Implement Stage 1 metadata and column roles before adding major import, graph-template, or batch features.
5. Implement Stage 2 Excel import/export next, because it unlocks real-world user workflows and supports later workbook metadata.
6. Start Stage 4 graph templates/layout after column roles exist, not before.
7. Start Stage 8 recalculation/templates once data-prep, fitting, and analysis operations have consistent metadata.
