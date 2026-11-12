# Development Roadmap

> **Instructions for AI Agent**: Development must follow the active roadmap order unless the user explicitly reprioritizes. Keep the current phase functional and tested before opening a broad new feature family. Always update `ChangeLog_Session.md` and `Agent_Instructions.md` when the roadmap changes.

## Current Capability Baseline

The first measured large-sheet performance slice, shared background-job controller, and cancellable staged text imports are implemented. Peak/Raman batch/map fitting and baseline-only map correction now share the controller for sequential detached computation, spectrum/pixel-count progress, cancellation, stale-source rejection, and atomic publication. Baseline/detection/composite-fit dialog previews are also asynchronous, with coalesced updates, current-review acceptance, and safe cancellation/close. A first Polars/Parquet large-data slice provides read-only disk-backed sources, bounded asynchronous 1,000-row/32-column/8 MiB windows, explicit window extraction, and embedded version-9 project persistence. Full-source query/analysis UI, vendor-map storage, larger-than-RAM capacity validation, Excel/project/remaining-analysis job migration, delta undo, and plot reduction/caching remain pending; see `Large_Data_Performance_Audit.md` for measured results.

Map cuts create persistent editable workspace plots backed by profile worksheets. The Peak/Raman viewer supports horizontal, vertical, and mouse-picked arbitrary cuts of its selected parameter/quality metric.

The user-approved independent-plot document/tab layer is implemented.
Open plots have separate editors/canvases and history; closed
views retain definitions, pending input, and viewport state in project documents.
Analysis creates new documents, opening an existing plot activates its view, and
Save Project serializes current states together. Plot rename cannot overwrite
another document; tab close and document deletion are distinct. At the user's
request, this now includes selectable 2-16-panel comparisons with persistent source
IDs, panel ordering, equal grid cells, tab/pop-out controls, optional compatible
numeric X/left-Y matching, native styles, PNG export, and clipboard copy. Source
plots remain independent. This reprioritizes comparison layout ahead of remaining
worker migrations. Full graph pages, shared legends, insets, and vector/PDF page
export remain future work. Individual plots and comparisons now support
maximizable pop-outs with retained inspectors/drafts, pointer-aware wheel zoom,
Shift+wheel/middle-button pan, and synchronized image-map navigation through the
comparison's X/Y options. These gestures preserve log/reversed axes and toolbar
navigation history.

The Series and Data Location colour controls now provide 20 swatched presets and
a custom RGB/hex picker. Existing colour strings remain the project/API format;
custom pending selections are restored across tab/project reopen without applying
them implicitly. The direct canvas appearance editor shares picker/name conversion.

At the user's 2026-11-10 priority, light/dark visibility issues are addressed with
shared contrasted theme tokens, explicit checkbox/radio/toggle/focus states,
state-aware navigation glyphs, readable swatches, and scoped comparison readouts.
Asymmetric X/Y percentile endpoint mapping is implemented in plots and Curve Fit.
Median measurement values use a calibrated quantile-normal likelihood, with
latent X for errors in both axes; projects/results preserve levels and provenance.
The shared composite numerical core accepts this uncertainty model. Dedicated
Peak/Raman bound-column controls, correlated/systematic error models, and
bootstrap/profile percentile intervals remain follow-ups; current errors/bands
are explicitly local approximations. These user-prioritized changes precede the
remaining general worker migrations.

Curve Fit now exposes its reference Worksheet in the Source group and refreshes
column/uncertainty mappings when it changes, while retaining explicit batch targets.
Every successful single or batch fit stores a report table with full text, numeric
parameters/errors, metrics and percentile provenance. The single-fit viewer can
copy text, export the table or open its saved worksheet. Report generation/export
uses the existing API recording and project-persistence paths.

The first application macro release is implemented at the user's 2026-11-10
priority. Record Smoothing, Curve Fit, and applied ordinary XY plot definitions
on one reference sheet, then replay on CSV/DAT/TXT folder files, workspace sheets,
or both. Import settings, typed source/result references, model settings, and plot
styles persist in standalone versioned macro files. Review/edit/reorder supported
steps, preview compatibility, run sequentially in the background with Cancel, and
publish independent complete-source worksheets/plots plus a cumulative audit.
Optional CSV export stages a new run directory. Existing sources are preserved;
unrecorded data changes/dependencies and invalid uncertainty propagation block
replay. This paragraph describes the narrower JSON batch recipe runner. Python
API recording now covers broader analysis/worksheet operations, comparisons,
figure exports and recomputed summaries. Its remaining adapters, repeat-block
mappings, streaming, and embedded libraries are listed under Stage 9; general
graph/analysis templates remain deferred.

The user subsequently clarified that the intended macro is a readable file of
API calls, analogous to generated methods in a scientific application. A public
`jasc_api.Session` facade and chronological Python recorder now complement the
recipe runner. `.py` recordings contain direct method calls, named sheet/fit/plot
references, and ordered plot updates/exports; they run through a command-line
launcher. Recording coverage includes calculus/formulas/FFT alongside the original
smoothing/fitting, native plot definitions, and comparisons. Additional adapters,
in-app script execution/editor integration, and complete shared GUI/API dispatch
remain follow-ups. The `.jasc-macro.json` menu is explicitly labelled batch recipes.
Active recording now has a mouse-transparent red window edge plus a persistent
Recording (.py) status badge and Stop Recording button, with palette/resize support.

Reviewed on 2026-09-24 against the current repository state, session changelog, and automated test suite.

### Implemented or Started
- Workspace and project state: multiple Pandas DataFrames, persisted dataset backend labels, unique dataset names, independent dataset/saved-plot/spectral-analysis results, open `.jasc` save/load with version 8 canonical JASC Package Seals covering member names/sizes/SHA-256 digests plus unique timestamp/UUID/nonce identity, readable CSV-backed spectral-analysis sessions, optional Ed25519 author signatures with password-encrypted private identities/shareable public identities/persistent trusted fingerprints, backward-compatible version 5 manifests and version 6/7 packages, optional password-encrypted/authenticated `.jascx` containers using Scrypt plus AES-256-GCM, atomic project replacement, saved plots, project-scoped custom fit models, current project path tracking, close project, and lightweight per-column metadata including role, type, units, precision, long name, and comments.
- Data ingestion and editing: single/multi-file CSV/DAT/TXT import with per-file delimiter, retained leading metadata, header, names, and preview preflight; safe Auto number-format inference plus explicit `1,234.56`/`1.234,56` decimal/grouping overrides; explicit General table/Single spectrum/Spectroscopy map and Horiba/B&W Tek profiles, global overrides, and batch header-pattern conflict decisions; exact spectrometer preamble preservation with parsed `#`/`$`/`%` fields, Horiba spectrum/map and B&W Tek single-spectrum compatibility, reconstruction of legacy Bruker IR `#c` coordinate exports, Horiba spectral-map matrix recognition, worksheet-level metadata viewing, and `.jasc` persistence; initial value-only `.xlsx`/`.xlsm` import with OOXML object warnings, worksheet-tab selection, hidden/chart-tab handling, and one dataset per selected sheet; XY-graph and 2D-colourplot raster digitization with immediate create-and-continue output, multiple curve/probe-set capture from one shared calibration, project-embedded resumable image/calibration sessions, and four-corner perspective correction; manual spreadsheet entry with Auto-typed blank columns; explicit arithmetic range fill plus selection-based Smart Fill for numeric linear/interleaved sequences, all day/month/year field orders with calendar/fixed-interval continuation, repeated categories, and user-entered ordered lists; editable Data Editor; positional odd/even/Every-N row and column subset extraction into new sheets; large file/dataset warnings; size-aware column auto-sizing; atomic worksheet row/column-count resizing; value-clearing Delete plus explicit structural deletion; formula metadata; operation provenance in column comments; column roles/types/units/precision/long names/comments; bounded undo/redo history; block, row, whole-column, and transposed clipboard operations; and right-click/double-click affordances across cells and headers.
- Formulas and transforms: constrained Python-like formula evaluator with curated NumPy/SciPy namespaces, direct/positional/exact column references, safe cross-worksheet `sheet("Worksheet", "Column")` references, explicit selected-cell or entire-column application, derivative/integral result columns, FFT/iFFT result sheets, and a first general interpolation workbench.
- Statistics: descriptive summaries, quantiles, diagnostics, normality tests, outlier checks, z-score/cumulative series, correlations, regression, agreement metrics, paired tests, independent-sample tests, multi-column summaries/correlations/covariance/PCA, grouped one-way analyses, post-hoc comparisons, and optional companion plots.
- Curve fitting: 66 built-in analytical models organized into scientific families (including a broad symmetric/asymmetric peak library), custom expression models, parameter guesses/bounds/fixed parameters, weighting/error columns, ODR for X/Y uncertainties, confidence bands, residual sheets, fit reports, and immediate fit overlay plots.
- Plotting: Matplotlib canvas and toolbar, saved plot definitions and duplication, multi-series XY plots, right Y axis, axis ranges/scales, per-axis label/tick typography, live-canvas clipboard copy, locators, SciencePlots styles, family/subtype plot selection, line/scatter/line+markers/errorbar, bar/barh/area/histogram with categorical label support, box/violin, initial pie/donut/Voronoi composition charts, interpolated 2D and spectral-slice maps with selectable palettes plus X/Y/intensity readout, export-only physical sizing, and direct double-click editing of rendered labels (including colour bars), legends, axes, and series appearance.
- Interpolated 2D maps: X/Y/Z coordinate roles, heatmap/contour/filled contour rendering, linear/cubic-spline/piecewise-cubic interpolation, grid resolution, saved state, dataset rename support, and X/Y locator prediction of Z values.
- Batch workflows: dialog-based multi-sheet execution, exact-name and column-position bindings, preflight tables, multi-column expansion, cancelable modal progress, per-source outputs, and cumulative summaries are implemented for formulas, calculus, smoothing, FFT/iFFT, interpolation, statistics, and curve fitting. Formula batches have an initial process-worker path; the remaining long operations are still executed synchronously from the UI workflow.
- Verification and UI polish: 210 automated tests pass in the active Python environment, including Qt-offscreen workflow coverage. The interface has screen/DPI-aware initial geometry, proportionally resized workspace/inspector docks, responsive wrapping forms, toolbar overflow, compact-mode workspace collapse with explicit override, reset view, sidebar visibility controls, application icon, direct context actions, reliable cross-style numeric steppers, explicit project-security save modes, and theme-aware styling.

### Current Gaps
- The automated suite exists and is runnable, but core import, formula, calculus, interpolation, statistics, fitting, project-persistence, and end-to-end batch paths need broader regression coverage. Verification commands, linting, and repeatable manual smoke scripts are not yet documented as a complete developer gate.
- Long-running import and analysis workflows can still block the Qt event loop. Background execution with real progress/cancel is the immediate engineering priority.
- The app has project-level datasets and a first lightweight column-metadata layer, but not full Origin/SigmaPlot-style workbooks with matrix sheets, notes, reports, folders, cell comments, dependency graphs, or rich worksheet formatting.
- Import/export is narrow compared with current commercial tools.
- Plotting includes equal-cell comparison layouts but lacks a general graph-page editor, shared legends, insets, annotation tools, many specialized graph families, and true 3D graphing. Reusable plot/analysis templates are deliberately deferred to the final roadmap stage.
- Batch analysis exists but lacks semantic role binding, a uniform timestamped audit-log schema, true background execution for most operation families, and workspace-level undo for edits to non-visible sheets.
- Fitting lacks global multi-dataset fitting, general dynamic/robust initial-guess search, surface fitting, and advanced model comparison; Fano components now have dedicated multistart initialization.
- A rebuilt PyInstaller one-folder Windows release provides GUI/console executables, manual, logo and curated examples in a verified ZIP. A Python-based Linux .sh installer packages source/examples, creates an isolated environment and checks startup; Linux-native installation validation, native frozen Linux builds, signing and fresh-machine release validation remain pending.
- JASC Package Seals provide normal-security forgery deterrence, `.jascx` provides authenticated encryption for sensitive packages, and optional Ed25519 signatures provide independently trustable author provenance through imported public-key fingerprints. Certificate-authority integration, revocation lists, hardware-token key storage, and trusted timestamp authorities remain optional future institutional-security extensions.

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
  - X/Y/Z heatmap, contour, and filled contour with automatic native-grid preservation or selectable interpolation, grid resolution, boundary masking, X/Y-to-Z locators, palettes, editable colour-bar labels, and live X/Y/Z reading. (complete)
  - Scientific map controls: automatic/manual/percentile colour limits; linear/log/symmetric-log/diverging normalization; configurable contour levels, labels, overlays, and line styles; data-point/triangulation/convex-hull overlays; measured/interpolated global and local extrema with provenance; missing/under/over colours; aspect and opacity. Rendered-grid, horizontal/vertical/arbitrary profile, rectangular ROI-statistic, and contour-vertex worksheet extraction are complete.
  - Remaining density/matrix follow-ups: matrix and correlation heatmaps, 2D histograms, hexbin plots, colour-bar tick formatting, polygonal ROI interaction, and general graph-page layout beyond the comparison grid.
- Phase 6: add engineering/time-series specialty plots: candlestick/OHLC with time, open, high, low, close, volume, and style controls.
- Phase 7: initial selectable equal-cell comparison layouts are complete, including persistent source links, tab/pop-out views, compatible numeric linked limits, and PNG export. General page composition, shared legends, insets, and vector/PDF export remain.
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
- PyInstaller one-folder GUI/CLI build, tested Windows release ZIP and opt-in standalone replay/security checks implemented. Python-based Linux .sh packaging/extraction/installer contracts are tested; continue native Linux installation, signing and fresh-machine validation.

## Competitive Gap Matrix

| Area | Current JASC Status | Gap Versus Origin/SigmaPlot-Level Tools |
| --- | --- | --- |
| Data model | Multiple DataFrames with formulas, lightweight column metadata, and persisted worksheet-level source/import metadata | No full workbook/sheet hierarchy, matrix sheets, notes/reports, project folders, cell comments, general editable dataset descriptions, rich formatting, or protected data |
| Import/connectors | Multi-file CSV/DAT/TXT with delimiter/metadata/header preflight, retained raw/parsed preambles, shared overrides, mismatch decisions, explicit data-type plus initial Horiba/B&W Tek profiles, decimal-comma spectra, legacy Horiba/B&WTech/Bruker IR text compatibility, and Horiba wide-map recognition normalized to X/Y/Raman Shift/Intensity rows; CSV/TXT export; initial value-only `.xlsx`/`.xlsm` worksheet-tab import with unsupported-object preflight; XY/2D-colourplot digitization with precision zoom, ROI/color tracing, symbol matching, perspective correction, manual uncertainty, empirical colour-scale calibration, and multiple curve/probe-set capture per calibration | Missing stacked/multiple-channel/multi-acquisition spectrometer layouts, broader encoding/locale controls, additional fixture-driven vendor/map profiles, Excel export, named/range-only mapping and metadata rows, legacy `.xls`, JSON/XML/HTML, HDF5/NetCDF/MATLAB, binary/instrument formats, ODBC/SQL, drag/drop, re-import/refresh, per-file batch parser overrides, plus digitizer point cleanup, overlap splitting, automatic multi-curve separation, discrete colour levels, automatic grid extraction, and OCR tick assistance |
| Data preparation | Formula columns, row/column operations, clipboard, filter/query, sort, duplicate removal, missing-value cleanup, binning, group/aggregate, merge/join, and reshape result sheets | Missing richer multi-condition filters, previews, type conversion, pivot tables, append/split tools, date/time parsing, resampling, and data reduction |
| Graphing breadth | Core 2D, distribution plots, early 2D maps, initial pie/donut/Voronoi composition charts, SciencePlots styles | Missing density families, grouped/categorical chart variants, polar/radar/ternary, waterfall, 3D scatter/surface/mesh/bars, specialized scientific diagrams, map overlays, images, and graph object editing |
| Graph layout | Independent plot documents, equal-cell comparison tabs/pop-outs with linked numeric X/left-Y ranges, native heterogeneous panels, PNG grid export, right Y axis, and direct source editing | General page layout, shared legends, multi-layer pages, insets, vector/PDF comparison export, object manager, annotations, direct data labels, and galleries remain; reusable templates/themes are intentionally deferred |
| Analysis | Calculus, FFT/iFFT, advanced smoothing including derivative reconstruction, 1D/2D/N-D interpolation, statistics workbench, baseline correction, physical-unit peak detection/review, registered composite peak fitting, sequential worksheet/Raman-map application, persistent spectral-analysis sessions, linked map/spectrum/residual/QC visualization, and opt-in worksheet export | Missing broader filters, advanced peak constraints/global fitting, convolution/correlation, STFT, wavelets, 2D FFT, resampling workflows, ROI/gadget-style analysis, and analysis chains |
| Statistics | Useful first-pass reports, multi-column correlations/covariance/PCA summaries, grouped one-way analyses, post-hoc comparisons, and companion plots | Missing two-way/repeated-measures ANOVA, ANCOVA/MANOVA families, broader nonparametric families, clustering, survival/reliability, SPC/control charts, DOE, power/sample-size, ROC, probability/distribution fitting, and guided statistical advisor workflows |
| Fitting | Nonlinear and batch fits, ODR, custom models, weights, residuals, confidence bands, per-source outputs, and cumulative summaries | Missing global fitting with shared/local parameters, dynamic initial-guess search, robust model ranking, arbitrary polynomial degree UI, prediction bands, peak deconvolution, surface fitting, implicit fitting UI, constraints by expression, and background execution |
| Automation | Saved plots/projects, formula metadata, column roles, and initial dialog-based batch execution with previews and cumulative summaries | Missing role-aware binding, uniform audit logs, background workers, safe cross-sheet undo, operation history, recalculation, repeat-last-operation, scripting/API, and command log; reusable templates are deferred |
| Reporting/export | Dataset export and Matplotlib toolbar save | Missing report editor, PDF/Word/PowerPoint export workflows, SVG/PDF/EPS/EMF export presets, journal export profiles, graph page export, HTML/web reports, and project-wide slideshow/export |
| Performance/package | Pandas/Matplotlib desktop app with large-dataset warnings, sampled sizing, block clipboard updates, bounded snapshot history, streaming project reads, sealed/signed open ZIP/CSV projects, and optional authenticated password encryption | Missing background jobs with real cancellation, true large-data query/lazy loading, plot decimation, delta undo, autosave/recovery, installer/spec, sample projects, CI fixtures, and optional institutional certificate/hardware-key integration |

## Step-by-Step Competitive Roadmap

### Competitive Stage 0: Stabilization Gate

Purpose: make future work safer before broad feature growth.

Completed foundation:
- A usable Python environment is available.
- The repository has a 210-test `unittest` suite and Qt-offscreen tests that instantiate `MainWindow` and exercise important worksheet, Excel import, plot, responsive-layout, digitizer, and performance workflows.

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

First execution slice implemented: shared thread ownership/progress/cancellation, background text preflight and parsing, GUI-thread staged commits with rollback, stale-workspace guards, and deferred close. Native parser reads check cancellation and report byte progress. Excel, project I/O, and operation families below still need migration.

Second execution slice implemented (2026-10-30): Peak/Raman worksheet-batch and
map fitting prepares grouped spectra and result tables in `core/peak_fit_jobs.py`.
It reports completed/total spectra, checks cancellation during optimizer residuals,
records individual failures, rejects changed source data/metadata and projects,
and publishes the session/optional worksheets together with rollback. Cancel
discards all pending outputs. The 400-pixel benchmark and 11 new regressions cover
responsive delivery, cancellation/restart, races, failure, and shutdown. Single
preview fits and baseline-only correction were completed in the slices below;
CPU process parallelism and other operation-family migration remain follow-ups.

Third execution slice implemented (2026-11-05): baseline-only map correction now
uses `core/baseline_jobs.py` for strict validation, sequential per-pixel correction,
and corrected-worksheet assembly. It shares map iteration, input snapshots,
status-bar progress/Cancel, source/project validation, safe shutdown, and result
publication guards with full map fitting. Cancel discards the whole pending map;
individual baseline failures retain successful pixels and record counts/errors
in Worksheet Metadata. Snapshot capture and final source comparison remain GUI
work. Asynchronous dialog previews are implemented in the fourth slice below.

Fourth execution slice implemented (2026-11-05): baseline, peak-detection, and
composite-fit dialog previews use Qt-independent `core/spectral_preview.py` and a
dialog-owned shared background controller. Settings changes invalidate results
immediately, retain the 250 ms debounce, coalesce pending requests, and reject old
source/pixel/range/configuration generations. Stop Preview cancels pending work;
optimizer evaluations check cancellation. Review/model choices survive fit and
acceptance; OK finishes prerequisites asynchronously and preserves manual edits.
Dialog/parent/project closure cancels and retains worker ownership until threads
stop. Baseline/fit/component drawing is bounded at 6,000 points while numerical
outputs stay complete. Input snapshots, source comparisons, source/pixel control
population, and drawing remain GUI work. Broader operation-family migration and
process parallelism remain next execution slices.

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

#### Spectrometer Text Import Foundation

The spectroscopy-analysis workbench depends on preserving acquisition context and
loading numeric axes correctly before baseline or peak algorithms are introduced.

Implemented foundation:
- Retain every detected leading metadata/preamble line verbatim instead of discarding it.
- Parse common `#`, `$`, `%`, plain `key=value`, `key: value`, tab, and semicolon records on a best-effort basis while always preserving the raw source text.
- Store source/import details, parsed fields, and raw preamble records as worksheet-level metadata; show them from the Data workspace and persist them in `.jasc` projects.
- Convert all-numeric localized decimal-comma columns after structural delimiter detection, including Horiba-style tab-separated spectra.
- Recognize the legacy Bruker IR text layout where `#c` contains the complete X coordinate array and following scalar records contain Y, producing normal `Wavenumber`/`Intensity` columns.
- Preserve broad B&WTech semicolon exports as full worksheets, including all raw-data and processed channels rather than reducing them to two columns.
- Recognize wide hyperspectral map matrices used by Horiba LabSpec: the first raw row contains two blank or X/Y-labelled coordinate cells followed by numeric Raman shifts, and every later row contains one spatial-pixel spectrum. Normalize the worksheet to four numeric columns—`X`, `Y`, `Raman Shift`, and `Intensity`—with one row per pixel/shift pair, preserve source pixel and shift order, and record both source and worksheet layouts plus pixel/shift counts and range in worksheet metadata. Keep non-Horiba map profiles deferred until representative formats are supplied.
- Apply conservative numeric type, X/Y role, and available Horiba axis-unit hints without overwriting the original metadata.
- Detect BOM-marked UTF-8/UTF-16, strict UTF-8, Windows-1252/ANSI, and Latin-1 text without replacement-character data loss; expose an explicit encoding override and retain the resolved encoding in preflight/provenance.

Required hardening before peak/map processing:
- Build committed, anonymized fixtures for Horiba, B&WTech, Bruker/OPUS-style IR, Renishaw, WITec, Thermo, Ocean Insight, and generic Raman/IR/PL exports as samples become available.
- Extend the new point/comma number-format controls to less-common locale conventions without allowing silent numeric corruption; add any vendor-specific legacy encodings only from representative fixtures.
- Extend the initial wide-map recognition to multiple-Y, stacked-spectrum, long-form map, time-series, depth-profile, and repeated-acquisition layouts during preflight.
- Add a mapping step for coordinate columns (`X`, `Y`, `Z/depth/time`), spectral axis, intensity channels, errors, and acquisition identifiers; retain the original source columns even when normalized views are created.
- Keep the normalized four-column map representation compatible with grouping by X/Y pixel for baseline and peak jobs; evaluate a more compact backend representation later if very large maps make repeated Raman-shift values a memory bottleneck.
- Add per-file parser overrides inside mixed batches, vendor-format diagnostics, and a safe generic fallback that never drops unrecognized records.
- Move inspection/parsing to the shared background-job architecture with cancellation and staged UI-thread commits.
- Define re-import provenance: source path, size/hash or timestamp, parser profile/version, delimiter/encoding/locale, header/data boundary, and user overrides.

Acceptance criteria:
- Importing a supported spectrometer text export produces numeric analysis-ready columns and preserves every preamble record.
- Worksheet metadata survives duplication and `.jasc` save/load unchanged.
- Unsupported or partially recognized vendor records remain visible as raw metadata and generate a warning rather than disappearing.
- Representative single spectra and maps can be batch imported with deterministic coordinate/channel roles and no silent row loss.

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

The Plot Inspector final-state audit is documented in `Plot_Inspector_Final_State.md`. The user explicitly prioritized independent plot documents and now comparison layouts. Those are implemented; broader inspector polish and general page composition remain.

Tasks:
- Finish Phase 2A subphases 4-7.
- Extend the implemented equal-cell comparison grids and numeric linked axes into a graph page editor with multi-layer figures, insets, shared legends, and vector/PDF page export.
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

#### Peak Analysis Integration Plan

This work starts only after spectrometer and map imports reliably preserve metadata,
numeric axes, coordinate/channel roles, and batch grouping. Reuse the workflow and
fixtures from `Raman_Data_Processing`, but replace its UI-coupled/dense numerical
implementations with tested, Qt-independent engines.

Implementation status (2026-09-28): the single-spectrum foundation and first
composite/batch/map slice are now in place. `math_engine/spectral.py`,
`baseline.py`, `peak_detection.py`, and `composite_peak_fit.py` provide
serializable contracts and central finite-segment/axis/polarity handling. The
shared **Baseline Correction** / **Peak Analysis** workbench provides debounced,
render-decimated previews, baseline diagnostics, physical-unit peak properties,
manual add/remove/disable/reposition review, a switchable source worksheet, and
per-peak registered-model selection. Its preview has Matplotlib home/history,
pan, zoom, and image-save navigation. Versioned JSON analysis profiles preserve
the complete range/baseline/detection/component/fit/matching configuration, while
manual baselines accept either explicit X:Y points or reusable X-only anchors
that resolve against every source spectrum independently. Normalized long-form
maps are explicitly identified in Source & Range, one finite X/Y group is chosen
for representative preview/review, and the accepted settings are then applied
independently to every map pixel for baseline-only or full peak fitting. It fits one shared baseline plus additive
components and writes curves, residuals, uncertainties, areas, metrics, and
provenance. Reviewed components can be applied sequentially to selected
worksheets or grouped X/Y map pixels using center-tolerance matching with
cumulative coordinate-keyed parameter and status outputs. Map fitting stores
one-row-per-X/Y peak intensity/area/position/FWHM/asymmetry, uncertainty,
baseline, SNR/noise, and fit-quality columns inside a first-class persisted
analysis session. The dedicated Raman Analysis viewer provides linked map/spectrum,
component, residual, distribution, and QC views while keeping result tables out
of the generic Data navigator until explicitly exported. Batch/map fitting now
runs in the shared background controller with atomic publication and cancellation.
Process parallelism, advanced component
constraints/ties, and explicit missing/extra-peak policies remain the next slices.

Architecture and contracts:
- Use `math_engine/baseline.py`, `math_engine/peak_detection.py`, and `math_engine/composite_peak_fit.py` as Qt-independent numerical layers.
- Define serializable `BaselineParameters`, `BaselineResult`, `PeakDetectionParameters`, `PeakRecord`, `PeakDetectionResult`, `PeakComponentSpec`, and `CompositeFitResult` contracts.
- Include raw/corrected arrays, convergence diagnostics, warnings, complete parameters, software versions, and source/map coordinates in provenance.
- Handle finite segments, descending X, irregular X, positive/negative/both polarities, and physical X units centrally rather than separately in each dialog.

Baseline correction phase:
- Add `pybaselines` as the preferred maintained numerical backend; begin with arPLS as the automatic default, plus AsLS, airPLS, SNIP, and rubber-band methods.
- Preserve the legacy manual-anchor workflow with editable anchors and linear, PCHIP, or Akima interpolation; also expose constant, linear, and polynomial backgrounds.
- For negative peaks, transform polarity explicitly and restore it after solving. Methods that assume one-sided positive peaks must warn rather than silently claim mixed-polarity support.
- Return baseline, corrected signal, iterations/convergence, and method warnings. Never build the legacy dense identity/difference matrices for long spectra.
- Create non-destructive `{Y}_baseline` and `{Y}_corrected` outputs or a user-selected result sheet.

Peak detection phase:
- Use `scipy.signal.find_peaks` as the fast default detector on corrected data, with optional existing Savitzky-Golay/moving-median smoothing.
- Support prominence, height/SNR, minimum distance, minimum/maximum FWHM, plateau handling, and maximum-count ranking.
- Express distance and width in X units. Convert to samples only for uniform axes; for irregular axes convert interpolated boundaries back to physical coordinates and prune by physical separation.
- Estimate automatic thresholds from robust noise statistics such as MAD of first differences or raw-minus-smoothed residuals.
- Run positive and negative detection explicitly and merge labeled candidates for mixed-polarity data.
- Produce a tidy peak table with source sheet/channel/map coordinates, row/index, center, polarity, raw/corrected height, prominence, FWHM, left/right boundaries and bases, area, local SNR, plateau size, asymmetry, detector, and manual-edit status.
- Preserve manual add/remove/disable/reposition controls through linked plot markers and an editable table.
- Add continuous-wavelet detection later for noisy multiscale signals; do not make it the first/default detector.

Peak Analysis UI:
- Add one `Analysis > Peak Analysis...` workbench with tabs for **Source & Range**, **Baseline**, **Detection**, **Fit Components**, and **Output & Batch**.
- Show raw+baseline and corrected+peak-marker previews. Debounce preview requests, cancel stale generations, and decimate only rendering—not numerical input.
- Provide home/history, pan, zoom, and image-save navigation for detailed inspection of small peaks.
- Make baseline controls reusable from a standalone Baseline Correction entry without creating divergent implementations.
- Store reviewed/manual peak candidates separately from automatic candidates so recalculation can preserve deliberate user edits.
- Save and load versioned portable analysis profiles containing every exposed range, baseline, anchor, detector, component-model, fit, and center-matching setting without binding the profile to worksheet/output names.
- For normalized maps, expose an explicit spectrum/map layout choice and representative X/Y preview-pixel selector; never preview the complete repeated spectral axis as one spectrum.

Composite peak fitting phase:
- Extend `FitModel` metadata with semantic parameter roles (`center`, `width`, `height`, `area`, `shape`, `offset`, `slope`) and an `is_peak` flag.
- Initialize registered Gaussian/Lorentzian/Voigt/pseudo-Voigt/Pearson/Fano/asymmetric components from detected centers, heights, and FWHM using model-correct conversions. Fano now uses extrema-aware resonance seeds, a positive physical scale, signed-q multistart fitting, and separately reports resonance/peak/dip quantities. (complete for current models)
- Fit `one shared baseline + peak 1 + ... + peak N`; suppress individual component offsets so the baseline is never counted repeatedly.
- Offer corrected-data mode with a fixed zero baseline and raw-data mode with one shared constant/linear/quadratic baseline. Prevent accidental double baseline subtraction.
- Provide a per-peak component table for enable/model/center/height-or-area/width/shape, bounds, fixed values, and shared/tied parameters.
- Fit separated overlap clusters independently for speed unless global/shared constraints require a joint fit.
- Output total fit, individual components, residuals, parameter uncertainties/correlations, peak areas, model metrics, and reproducible report metadata.

Batch spectra and map processing:
- Carry baseline/detection/fitting settings through serializable templates only after the operation schemas are stable.
- Match peaks across spectra by expected center plus tolerance and optional continuity constraints, never solely by prominence rank.
- Define explicit policies for missing/extra peaks: skip/report, fit matched only, accept additional candidates, or stop for review.
- For maps, process each pixel/acquisition as a grouped job; write long-form peak/fit results keyed by coordinates and generate parameter maps for center, width, height/area, baseline, SNR, and fit quality.
- Parallelize across independent spectrum/map groups above a measured threshold using pickle-safe tasks; stage outputs and commit them on the UI thread.

Validation and performance gates:
- Generate synthetic constant/linear/quadratic/exponential/fluorescence baselines with positive, negative, mixed, isolated, overlapping, asymmetric, plateau, Fano, irregular-X, descending-X, missing-data, and varied-noise peaks.
- Measure baseline RMSE, detection precision/recall, center/FWHM/area error, fit recovery, runtime, and peak memory.
- Reuse anonymized silicon, double-peak, asymmetry, Fano, Horiba, B&WTech, and Bruker fixtures from the older application for behavioral regression, without requiring exact legacy numerical parity.
- Add UI tests for preview generations, anchors, marker editing, cancellation, partial batch failure, provenance, project round trips, and map-result reconstruction.
- Establish explicit performance budgets for approximately 100,000-point spectra and large spectrum maps before enabling automatic full-project processing.

Delivery sequence:
1. **Started/completed for the single-spectrum foundation:** engine contracts, alignment/polarity/X-unit helpers, synthetic fixtures, and initial validation metrics.
2. **Completed for single spectra:** baseline engine and reusable preview UI.
3. **Completed except cross-spectrum batch summaries:** fast prominence-based detection, peak properties, and marker/table review.
4. **Completed for the first production slice:** composite multi-peak fitting connected to the existing categorized registry, one shared baseline, curve/parameter outputs, uncertainties, areas, and fit metrics.
5. **Completed for sequential batch/map application and result viewing:** source switching, reviewed-model carry-over, center-tolerance matching, grouped X/Y jobs, first-class persisted analysis sessions, one-row-per-pixel metrics, linked parameter maps/spectra/components/residuals/distributions/QC, and explicit worksheet export. Advanced missing/extra policies, representative vendor-map fixture gates, and background/parallel execution remain.
6. **Completed for reproducible setup reuse:** interactive preview navigation, X-only per-spectrum manual anchors, and versioned JSON save/load of all exposed Peak Analysis algorithm parameters.
7. **Completed for map preview/application:** explicit map layout, representative X/Y pixel selection, and independent full-map baseline or peak jobs with coordinate-preserving outputs.
8. CWT detection, advanced morphological baselines, automatic tuning, and measured optimization.

The recommended first implementation slice is items 1-3. It establishes reliable
corrected signals and reviewed peak candidates before the more failure-prone
composite-fitting and map-automation layers are introduced.

Acceptance criteria:
- Users can fit multiple datasets with shared parameters and inspect per-dataset residuals.
- Peak and surface fitting workflows produce reproducible reports and plots.

### Competitive Stage 9: Operation History and Recalculation

Purpose: build on Stage 1 audit records so existing workflows become traceable and recalculating without introducing a template system.

#### User-prioritized application macro recording (2026-11-10)

The user's clarified target is chronological Python API-call recording.
`jasc_api.py` provides the public Session API and script launcher;
`core/api_recording.py` emits readable `.py` files and detects gaps. The existing
recorder now captures successful calls and live plot changes in execution order,
with separate API-script view/save and batch-recipe actions. Tests execute generated
scripts and compare numerical outputs, plot definitions, exported figures, and
comparison identities. Complete operation coverage still requires individual
adapters; GUI computations currently retain their established engine paths.

Expanded adapters now cover worksheet edits/history/lifecycle; Excel and large-data
imports/extraction; every existing Data Prep operation; statistics with companion
tables, long/wide summaries and dynamic groups; interpolation; sequential/parallel
formulas; baseline maps and single/batch/map spectral analysis; reviewed peak
decisions; analysis lifecycle/table export; map data products; plot deletion; and
ordinary project saves. Summary/report builders and single-spectrum publication
are shared with GUI execution, so replay recomputes scientific values. Spectral
background calls are captured only on validated publication. New regressions execute
scripts against original and changed inputs, including changed row/group counts.
Image-digitizer extraction, nested recipe execution, spectral-viewer presentation
adapters and full command dispatch migration remain open;
protected save credentials stay outside recordings.

Restricted in-app and executable playback is implemented (2026-11-11).
`core/script_language.py` validates the recording grammar; `script_runtime.py`
dispatches explicit API commands using opaque references; `script_safety.py`
limits file and renderer capabilities. `script_jobs.py` stages a detached workspace
and runs a limited child process, with Windows job-object memory/process limits,
cancellation, timeout, stale-workspace rejection and atomic result-folder publication.
The GUI runner reviews exact source bytes and allowed input/output folders.
`main.py --run-script`, `python -m jasc_api`, and frozen entry points share this
interpreter; arbitrary Python programs are not accepted. `JASC.spec` and
`build_windows.py` produce GUI/console executables, including Conda runtime DLLs.
Rebuilding the PyInstaller executable package requires an explicit user request;
ordinary development uses source/Python checks and leaves the existing bundle as-is.
Tests cover hostile syntax/object escapes/embedded formulas, file scopes, Windows
junctions, renderer style restrictions, actual child cancellation, GUI publication
and a bundle running without Python on PATH. Continue fresh-VM validation, stronger
OS isolation if general extensibility is introduced, installer and code signing.

A runnable synthetic folder example now lives in `Test_Data/Macro_Example`: three
seeded noisy Gaussian measurements, explicit missing/duplicate cleanup, background
correction, LOWESS display smoothing, weighted fits of unsmoothed observations,
parameter/statistics exports and synchronized comparison plots. Independent ground
truth and an actual child-run regression verify scientific recovery and source
preservation. Instructions cover GUI, source CLI and the standalone executable.

`Test_Data/Feature_Examples` now supplies a catalog for fourteen application feature
families, with small reproducible synthetic inputs, independent expected answers,
GUI walkthroughs, and thirteen restricted replay macros. All registered plot
subtypes have actual figure exports. Digitization uses analytic raster fixtures
and manual review steps; protected saves, plot gestures and theming remain manual.
The disk-backed fixture demonstrates paging, not larger-than-RAM capacity. Source
regression checks execute every supplied replay and verify input regeneration and
preservation. The original whole-folder macro remains a separate linked example.

First release implemented: `models/macro.py`, `core/macro_recording.py`, and
`core/macro_jobs.py` provide versioned declarative steps, source/result bindings,
structural preflight and runtime numeric checks, per-source staging, and staged
CSV export. `ui/macro_controller.py` and `ui/macro_dialog.py` provide the Macros
menu, recording hooks in existing Smoothing/Curve Fit/import paths, collection of
applied XY plot definitions on Stop, review/edit/remove/reorder, both input types,
background execution, stale-source rejection, rollback, and save guards. Existing
interactive numerical workflows keep their established execution paths. Replay
retains independent fit seeds, uncertainty semantics, and new plot identities.
Macro files remain separate from projects; generated results use normal project
persistence. Cancellation keeps complete sources and discards the incomplete one.

The design below guides remaining coverage. Configurable repeat-block bindings,
embedded macro libraries and the remaining adapters are still future work. Python
scripts already support native plot families, comparisons and figure exports;
the older JSON recipe runner retains its narrower Smoothing/Curve Fit/XY scope.

- Introduce validated, versioned operation commands and an allowlisted registry
  that numerical workers and ordinary dialogs can both execute. Existing
  `Operation:` metadata records only the latest description and cannot reconstruct
  an exact prior sequence.
- Record supported, successfully applied operations and their full settings;
  previews, cancelled dialogs, and failed operations are not steps. Identify
  unsupported actions explicitly instead of silently omitting a dependency.
- Store logical source/column bindings and references to earlier step outputs,
  independently of temporary sheet names or collision suffixes. Retain model
  definitions, fit seeds/constraints, ranges, and uncertainty semantics. Require
  explicit dependencies for external-sheet references.
- Provide Record / Stop / Save Macro / Run Macro, an editable ordered step list,
  and sample validation. The user confirmed both disk-folder files and workspace
  datasheets as sources; allow either or their union through one target group.
  Start folder support with existing delimited-text importers and retain their
  format/locale rules. Import all selected eligible files into normal workspace
  sheets by default; retaining a large group consumes normal dataset memory.
- Represent an input-group setup, a repeat-for-each-datasheet block, and final
  group actions. Loading occurs once for the group, per-sheet operations and plot
  creation repeat, and combined overlays/comparisons/summary exports run once after
  the individual results exist. Replaying must rebind source paths and logical
  aliases rather than reimporting the recorded example for every target.
- Record applied plot definitions/styles with symbolic data/column references.
  Replay creates independent plot documents with new identities and rebinds any
  final comparison layout to the generated plots, preserving existing panel limits.
  Save generated plots without opening every tab; let the user inspect selected
  results. Numerical work stays in workers; Workspace/Qt plot publication stays
  on the GUI thread.
- Preview source/sheet eligibility, resolved columns, required settings, and
  skip/block reasons. Name matching is the default; positional mapping must be
  explicit, and ambiguous role mapping must not silently choose a signal.
  Structural preflight is followed by full per-step numeric validation at run time.
- Process one source at a time off the GUI thread through existing job contracts.
  Stage every step for that source, publish only a complete source result, retain
  completed sources on Cancel, and discard the incomplete source. Keep inputs
  unchanged by default; output to a separate location with explicit collision
  handling and exclude output directories from recursive source discovery.
- Emit a cumulative per-source/per-step audit with workflow version, settings,
  bindings, status, error/warning, elapsed time, and output paths. Export results
  incrementally; retain imported sheets and requested outputs by default, while
  transient intermediates need not remain. A future low-memory option can stream
  sources without retaining them; it must be an explicit alternative to load-all.
- Never attach raw percentile bounds to transformed/smoothed data without a valid
  propagation rule. Unsupported uncertainty propagation must be visible and block
  any downstream fit that would otherwise use invalid error metadata.
- First implement and verify a small complete macro such as load/select inputs ->
  for each sheet: smoothing -> Curve Fit -> create plot -> collect summary/export.
  Add formula, calculus, baseline, FFT, interpolation,
  statistics, and other adapters as individually verified operations. Tests must
  cover step dependencies, mapping/collision failures, numeric equivalence to
  individual operations, cancellation, source preservation, and bounded loading.

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
- Evaluate Polars lazy/streaming execution against DuckDB over Parquet before selecting the large-data backend; keep Pandas as the default editable backend for small and medium worksheets. Backend adoption must ship together with bounded table paging, not a complete in-memory replacement DataFrame.
- Add lazy loading or chunked import for large text/Excel/HDF5 files.
- Add row/column import limits, sampling previews, and user-selectable load strategies for very large delimited files.
- Add a read-only paged table model for disk-backed datasets with at most 1,000 resident data rows in its display cache, then add limited materialize-to-Pandas workflows for selected rows/columns. (first slice implemented through `LargeDataset`, `LargeDataView`, and explicit displayed-window extraction; continuous global scrollbar and arbitrary range/column selection remain)
- Keep global row identities and column headers stable while asynchronous viewport/page requests replace the cached window. Debounce rapid scrolling, coalesce pending requests, and reject stale results after another page, filter, source revision, or dataset is selected; never perform disk queries from the model's cell-data callback.
- Bound the display cache by bytes as well as rows for wide sheets or long strings, with column projection/windowing when needed. Evict old pages instead of accumulating visited rows; account separately for the bounded in-flight page and engine/import buffers. Provide global row counts/ranges, direct row navigation, and loading/error feedback without full-content column sizing.
- Execute filters, sorts, summaries, plots, and analysis against the backend dataset or an explicit selection, never silently against the visible 1,000 rows. Large-data import and project loading must also avoid materializing the complete source; initially keep disk-backed sheets read-only so ordinary snapshot undo cannot copy the whole source.
- Gate the backend/paged-view slice on bounded-memory tests across repeated scrolling and far-row jumps, correct global row labels and final/empty pages, stale-result rejection, responsive navigation, full-dataset query semantics, and bounded extraction for SciPy. (initial regression and million/four-million-row navigation benchmarks implemented; 10 GB/larger-than-RAM acceptance, full-source operation UI, and decoder/import budget hardening remain)
- Add backend-aware operation dispatch: DuckDB/Polars-style query execution for simple filters, summaries, grouped statistics, and transforms; materialize selected columns for SciPy-heavy fitting/interpolation/statistical tests.
- Add plot decimation/downsampling for interactive rendering.
- Replace whole-DataFrame undo snapshots with delta-based or bounded-history undo for large sheets.
- Add autosave, crash recovery, and project backups.
- Add PyInstaller spec, icons/resources, version metadata, and a repeatable Windows build command. (Windows build/ZIP and Python-based Linux .sh installer implemented; native Linux GUI installation and signing/fresh-machine release audits remain)
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

The user's latest priority has broad Python API recording described in Stage 9,
alongside the earlier Smoothing/Curve Fit batch recipe runner for folder/workspace
targets. Complete the remaining image-digitizer, nested-run and viewer-presentation
adapters before opening a general template family. Restricted in-app/executable
playback is now implemented; general Python execution remains outside its scope.
Use the existing job contracts and tests while adding this slice, then continue
the broader priorities below. This does not open the deferred general template scope.

1. Close the small remaining Stage 0 gate: document verification commands, add missing core/batch smoke coverage, configure linting, define manual checks, and resolve dependency drift.
2. Harden the new spectrometer-import foundation with committed/anonymized vendor fixtures, additional locale controls and fixture-driven legacy encodings, stacked/long-form/multi-acquisition layouts, explicit coordinate/channel mapping, and lossless warnings for unrecognized records.
3. Extend the implemented Stage 1 background-job controller beyond text import and the spectral preview/batch/map workflows, retaining progress, cooperative cancellation, safe shutdown, and GUI-thread result commits.
4. Move long imports and the existing calculus, smoothing, FFT/iFFT, interpolation, statistics, and curve-fitting workflows off the Qt UI thread.
5. Add workspace transactions/undo for background and non-visible-sheet edits, then test cancellation, partial failures, and project consistency.
6. Complete semantic role binding and normalized timestamped audit logs across every batch-capable dialog.
7. Harden Excel support with background parsing, previews, named/range-only selection, metadata-row mapping, and `.xlsx` export.
8. Continue figure extraction and Data Prep with their listed cleanup, mapping, preview, date/time, reshape, and batch follow-ups.
9. Harden the implemented Peak/Raman Analysis composite, background batch/map fits, baseline-only map correction, and asynchronous previews with representative vendor-map fixtures, advanced bounds/fixed/tied parameters, explicit missing/extra-peak policies, and process parallelism.
10. Add the remaining signal-analysis family: digital filter design and response previews, convolution/correlation, Hilbert transform, STFT, wavelets, and 2D FFT.
11. Extend statistics, general/global fitting, plotting families, annotations, and multi-panel page layouts. Reusable templates remain excluded from this stage.
12. After the main workflows are responsive and tested, continue disk-backed large-data mode (Polars/DuckDB evaluation plus a bounded 1,000-row display window), decimated plotting, delta undo, autosave/recovery, PyInstaller packaging, reporting, and plugin extension points.

Reusable graph/analysis templates are intentionally deferred to Competitive Stage 12 and must not displace the priorities above.
