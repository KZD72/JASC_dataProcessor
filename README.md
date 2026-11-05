# JASC Data Processor

A lightweight, modular application for data ingestion, visualization, mathematical operations, and curve fitting. Built with Python, PySide6, Pandas, and SciPy.

## Features

- **Disk-backed Large Tables**: File > Open Large Dataset opens regular CSV/DAT/TXT tables or Parquet through Polars and private Parquet storage. The read-only Large Data view replaces a cache of at most 1,000 rows, 32 columns, and 8 MiB; scroll past a window edge, use Previous/Next, or jump to a global row. Page reads run in the background, obsolete requests are discarded, and visited pages are evicted. Create an editable worksheet explicitly from the displayed window. Large sources are embedded as Parquet in version-9 projects; ordinary projects retain version 8. Text values remain strings to preserve IDs, late tokens, and locale values. Vendor-specific layouts and whitespace-separated tables continue through ordinary import; full-source analysis/filter UI is a later slice.

- **Data Ingestion**: Text-file inspection and parsing run in the background with inline progress and Cancel; cancelled batches add no partial worksheets. Batch-import CSV/DAT/TXT data with encoding, delimiter, leading-metadata, header, and number-format preflight/inference; choose Auto, General table, Single spectrum, or Spectroscopy map plus an Auto/generic, Horiba LabSpec, or B&W Tek profile. Auto detects BOM-marked UTF-8/UTF-16, strict UTF-8, Windows-1252/ANSI, or Latin-1 without replacement-character data loss. Auto also safely recognizes unambiguous point/comma decimals and grouped forms, while explicit `1,234.56` and `1.234,56` modes resolve ambiguous values. Instrument preambles are retained as worksheet metadata, and legacy Horiba/B&WTech/Bruker IR text layouts are supported. Horiba LabSpec maps are normalized into `X`, `Y`, `Raman Shift`, and `Intensity`; B&W Tek is currently supported for single spectra only. Modern Excel `.xlsx`/`.xlsm` tabs can be imported as value-only datasets with explicit warnings for unsupported workbook objects; data can also be entered manually in the spreadsheet interface.
- **Data Editing**: Edit imported datasets directly with bounded undo/redo, append/insert/delete row and column operations, fast block-oriented spreadsheet copy/paste, whole-column copy/paste, large-dataset warnings, sampled table auto-sizing, and per-column name/role/unit/long-name/comment metadata.
- **Formula Engine**: Apply safe math operations to columns using a sandboxed expression evaluator with NumPy/SciPy support, positional aliases such as `col1`, exact-name insertion helpers, worksheet batch targets, protected output naming, numeric-string promotion, and metadata-aware atomic result validation.
- **Signal Processing & Calculus**: Perform numerical differentiation, cumulative integration, FFT, and previewed smoothing with adjacent-average, median, Savitzky-Golay, LOWESS, FFT low-pass, or derivative-smoothing reconstruction.
- **Baseline, Peak & Raman Analysis**: Choose any worksheet while retaining the launching sheet as the initial selection; explicitly identify a single spectrum or normalized X/Y map; select one representative map pixel for zoomable raw/baseline/corrected preview; correct spectra with arPLS, AsLS, airPLS, SNIP, rubber-band, manual-anchor, constant, linear, or polynomial baselines; detect and review positive, negative, or mixed peaks; assign a registered model to each component; and apply the reviewed setup to one spectrum, a worksheet batch, or every X/Y pixel. Full fits now become persistent analysis sessions rather than automatically filling the Data workspace. The dedicated Raman Analysis viewer keeps the parameter/quality map and click-linked selected-pixel fit prominent, supports direct title/axis/legend editing and per-curve visibility, and provides residual/error, metric-distribution, and QC details on demand in a tabbed diagnostic panel; selected internal tables can be explicitly exported to worksheets. The Fano model uses a positive physical scale, resonance position, natural linewidth, signed q, multistart fitting, separate peak/dip positions and contrasts, and propagated extrema uncertainties. Versioned JSON parameter profiles remain reusable across files.
- **Interpolation Workbench**: Generate 1D, 2D, and N-D prediction datasets with linear, spline, piecewise cubic, nearest-neighbor, and RBF methods.
- **Statistics Workbench**: Generate single-column summaries, multi-column summaries/correlations/covariance/PCA, grouped/factor analyses, normality tests, outlier checks, regression metrics, paired tests, independent-sample tests, one-way ANOVA, Kruskal-Wallis, post-hoc comparisons, and optional companion plots.
- **Curve Fitting**: Fit 66 categorized analytical models spanning polynomials, decay/growth, symmetric and asymmetric peaks, transitions/waveforms, kinetics, rheology, probability distributions, and physical functions, with customizable parameters and LM, trust-region, Dogbox, or ODR optimization.
- **Custom Fit Models**: Define project-saved fit models from safe NumPy/SciPy expressions and use them in the standard fitting workflow.
- **Dynamic Plotting**: High-performance multi-axis plotting with Matplotlib, featuring data locators, scaling controls, SciencePlots journal styling, visual customization, error bars, reporting plots, histograms, box/violin distribution comparisons, and native-grid or interpolated 2D and Raman/frequency-slice maps. Scientific map controls include automatic/manual/percentile colour ranges, linear/log/symmetric/diverging normalization, explicit contour levels and labels, measured-point/triangulation/boundary overlays, measured or interpolated extrema with provenance, aspect control, and live X/Y/intensity readout. Rendered grids, horizontal/vertical/arbitrary profiles, rectangular ROI statistics, and contour vertices can be exported as normal worksheets. Each cut also creates a persistent editable workspace plot. Peak/Raman result maps offer Map Cuts and mouse-picked cut lines for the selected metric.
- **Independent Plot Tabs**: Each plot is a project document with its own editor, pending fields, view, and undo history. Open existing plots without reloading over edits; analysis results create new tabs. Close tabs without deleting plots, reopen them from Workspace, and use Save Project to persist every plot together. Rename and Delete are separate actions; project/app closure asks to save unsaved plot work.
- **Data Preparation**: Create non-destructive result sheets for filtering, sorting, duplicate removal, missing-value cleanup, binning, grouping, joins, and reshaping.
- **Responsive Docked Workspace Layout**: Size the initial window from the active screen work area, proportionally rebalance docks after window or DPI changes, and reflow the Plot Inspector without collapsing its editors. Plot actions move into a toolbar overflow menu when horizontal room is limited; on very narrow Plot layouts the Workspace navigator collapses automatically to preserve the canvas and can still be explicitly restored from View. Datasets, saved plots, and spectral-analysis sessions remain separate navigator sections, while Data receives the full central width and Raman Results appears only when a result exists or is explicitly opened.
- **Project Persistence and Protection**: Save complete workspaces as open `.jasc` ZIP/CSV packages or optional password-encrypted `.jascx` packages. Encrypted saves use Scrypt-derived AES-256-GCM authenticated encryption; ordinary `.jasc` files remain directly inspectable for open-science use. Version 8 packages retain the uniquely salted JASC Package Seal over every member name, byte size, and SHA-256 digest, store spectral-analysis tables as readable CSV members, and can optionally add an Ed25519 author signature. JASC creates password-encrypted private identity files, exports shareable public identities, maintains a local trusted-fingerprint list, and distinguishes trusted, valid-but-unknown, unsigned, and invalid signatures.

## Installation

1. Clone the repository.
2. Ensure you have Python 3.10+ installed.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the application:
   ```bash
   python main.py
   ```
   Run `main.py` from the repository root; `ui/main_window.py` is an internal module and is not a standalone entry point. In VS Code, use the **Run JASC Data Processor** launch configuration.

## Development

The independent-plot document/tab layout is a trial for desktop review. Run
`main.py`, select **Plots**, and use **New Plot** or **+**. Open two plots, edit one,
switch back and forth, close/reopen a tab from Workspace, and save/reopen the
project. An asterisk marks changes since project save. **Rename** replaces the
old separate Save Plot action. Pending series fields are saved as editor drafts;
**Update Series** still applies them to the rendered plot. Closed canvases are
released and recreated on demand. A preview is in `artifacts/plot_tabs_preview.png`.

Peak/Raman worksheet-batch and map fitting, plus baseline-only map correction,
run in the background with status-bar progress and Cancel. Completed results are
published together; cancelling discards the entire pending run. Changing source
data, column metadata, or the project discards pending results. Spectra are
processed sequentially within a run. Baseline-only correction creates a normal
corrected worksheet with pixel counts and failure details in Worksheet Metadata.

Dialog baseline, detection, and component-fit previews also run in workers.
The existing 250 ms debounce keeps only the latest requested settings; **Stop
Preview** cancels pending work. **OK** uses current reviewed peaks/model choices
and finishes any required preview before accepting. Dialog/parent/project closure
cancels preview work safely. Plot curves use at most 6,000 display points while
numerical results retain their full resolution.

Run verification from the repository root with the project environment active:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -B -m unittest discover -s tests
git diff --check
```

For the focused worker/UI regressions and reproducible synthetic map benchmarks:

```powershell
python -B -m unittest discover -s tests -p test_background_peak_fit.py
python -B -m unittest discover -s tests -p test_background_baseline.py
python -B -m unittest discover -s tests -p test_spectral_previews.py
python -B -m unittest discover -s tests -p test_plot_documents.py
python -B benchmarks/background_peak_fit_audit.py --output result.json
python -B benchmarks/background_peak_fit_audit.py --cancel-after-ms 100 --output cancel.json
python -B benchmarks/background_peak_fit_audit.py --baseline-only --output baseline.json
python -B benchmarks/background_peak_fit_audit.py --baseline-only --cancel-after-ms 100 --output baseline_cancel.json
python -B benchmarks/spectral_preview_audit.py --kind fit --output preview.json
python -B benchmarks/spectral_preview_audit.py --kind baseline --changes 10 --output preview_updates.json
python -B benchmarks/spectral_preview_audit.py --kind fit --samples 1000000 --cancel-after-ms 100 --output preview_cancel.json
```

The architecture strictly separates concerns:
- `core/`: State management, IO, and core validation.
- `math_engine/`: Data operations (calculus, FFT, curve-fitting logic).
- `models/`: Registries for math models and parameters.
- `ui/`: PySide6 view layer (Main window, plot canvas, dialogs).

See `Architecture.md` and `Roadmap.md` for architectural blueprints and project progression.
