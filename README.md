# JASC Data Processor

A lightweight, modular application for data ingestion, visualization, mathematical operations, and curve fitting. Built with Python, PySide6, Pandas, and SciPy.

## Features

- **Python API Recordings**: Record chronological calls to `jasc_api.Session`, then use **Macros > Run Python API Script** or the CLI to replay the supported command language. Playback validates the entire recording, restricts imports/exports to selected folders, and runs in a separate process with time/memory limits. Completed results replace the workspace only if it stayed unchanged; exports enter a new run folder. Arbitrary Python, shell calls, object introspection, style URLs/files and external LaTeX are rejected.
- **Folder/Workspace Batch Recipes**: The existing `.jasc-macro.json` workflow remains available through separate batch-recipe menu actions for Smoothing/Fit/XY-plot replay, compatibility preview, progress/Cancel, independent outputs, summaries, and staged CSV export.
- **Disk-backed Large Tables**: File > Open Large Dataset opens regular CSV/DAT/TXT tables or Parquet through Polars and private Parquet storage. The read-only Large Data view replaces a cache of at most 1,000 rows, 32 columns, and 8 MiB; scroll past a window edge, use Previous/Next, or jump to a global row. Page reads run in the background, obsolete requests are discarded, and visited pages are evicted. Create an editable worksheet explicitly from the displayed window. Large sources are embedded as Parquet in version-9 projects; ordinary projects retain version 8. Text values remain strings to preserve IDs, late tokens, and locale values. Vendor-specific layouts and whitespace-separated tables continue through ordinary import; full-source analysis/filter UI is a later slice.

- **Data Ingestion**: Text-file inspection and parsing run in the background with inline progress and Cancel; cancelled batches add no partial worksheets. Batch-import CSV/DAT/TXT data with encoding, delimiter, leading-metadata, header, and number-format preflight/inference; choose Auto, General table, Single spectrum, or Spectroscopy map plus an Auto/generic, Horiba LabSpec, or B&W Tek profile. Auto detects BOM-marked UTF-8/UTF-16, strict UTF-8, Windows-1252/ANSI, or Latin-1 without replacement-character data loss. Auto also safely recognizes unambiguous point/comma decimals and grouped forms, while explicit `1,234.56` and `1.234,56` modes resolve ambiguous values. Instrument preambles are retained as worksheet metadata, and legacy Horiba/B&WTech/Bruker IR text layouts are supported. Horiba LabSpec maps are normalized into `X`, `Y`, `Raman Shift`, and `Intensity`; B&W Tek is currently supported for single spectra only. Modern Excel `.xlsx`/`.xlsm` tabs can be imported as value-only datasets with explicit warnings for unsupported workbook objects; data can also be entered manually in the spreadsheet interface.
- **Data Editing**: Edit imported datasets directly with bounded undo/redo, append/insert/delete row and column operations, fast block-oriented spreadsheet copy/paste, whole-column copy/paste, large-dataset warnings, sampled table auto-sizing, and per-column name/role/unit/long-name/comment metadata.
- **Formula Engine**: Apply safe math operations to columns using a sandboxed expression evaluator with NumPy/SciPy support, positional aliases such as `col1`, exact-name insertion helpers, worksheet batch targets, protected output naming, numeric-string promotion, and metadata-aware atomic result validation.
- **Signal Processing & Calculus**: Perform numerical differentiation, cumulative integration, FFT, and previewed smoothing with adjacent-average, median, Savitzky-Golay, LOWESS, FFT low-pass, or derivative-smoothing reconstruction.
- **Baseline, Peak & Raman Analysis**: Choose any worksheet while retaining the launching sheet as the initial selection; explicitly identify a single spectrum or normalized X/Y map; select one representative map pixel for zoomable raw/baseline/corrected preview; correct spectra with arPLS, AsLS, airPLS, SNIP, rubber-band, manual-anchor, constant, linear, or polynomial baselines; detect and review positive, negative, or mixed peaks; assign a registered model to each component; and apply the reviewed setup to one spectrum, a worksheet batch, or every X/Y pixel. Full fits now become persistent analysis sessions rather than automatically filling the Data workspace. The dedicated Raman Analysis viewer keeps the parameter/quality map and click-linked selected-pixel fit prominent, supports direct title/axis/legend editing and per-curve visibility, and provides residual/error, metric-distribution, and QC details on demand in a tabbed diagnostic panel; selected internal tables can be explicitly exported to worksheets. The Fano model uses a positive physical scale, resonance position, natural linewidth, signed q, multistart fitting, separate peak/dip positions and contrasts, and propagated extrema uncertainties. Versioned JSON parameter profiles remain reusable across files.
- **Interpolation Workbench**: Generate 1D, 2D, and N-D prediction datasets with linear, spline, piecewise cubic, nearest-neighbor, and RBF methods.
- **Statistics Workbench**: Generate single-column summaries, multi-column summaries/correlations/covariance/PCA, grouped/factor analyses, normality tests, outlier checks, regression metrics, paired tests, independent-sample tests, one-way ANOVA, Kruskal-Wallis, post-hoc comparisons, and optional companion plots.
- **Curve Fitting**: Fit 66 categorized analytical models spanning polynomials, decay/growth, symmetric and asymmetric peaks, transitions/waveforms, kinetics, rheology, probability distributions, and physical functions, with customizable parameters and LM, trust-region, Dogbox, or ODR optimization.
- **Percentile Error Bounds**: Map separate X/Y lower and upper endpoint columns and their probability levels for asymmetric error bars. Curve Fit supports a calibrated quantile-normal measurement likelihood for median data, including latent-X fitting when X bounds are supplied. Bounds, levels, and provenance are retained in projects, generated plots, and fit worksheets; ordinary symmetric sigma/weight fits remain available. Parameter errors/bands are local approximations, not bootstrap intervals.
- **Custom Fit Models**: Define project-saved fit models from safe NumPy/SciPy expressions and use them in the standard fitting workflow.
- **Persistent Fit Reports**: Choose any loaded editable worksheet directly in Curve Fit. Successful single and batch fits retain report text, numeric parameters/errors, metrics and uncertainty settings as workspace tables; copy, export or open the report from its viewer and save it with the project.
- **Dynamic Plotting**: High-performance multi-axis plotting with Matplotlib, featuring data locators, scaling controls, SciencePlots journal styling, visual customization, error bars, reporting plots, histograms, box/violin distribution comparisons, and native-grid or interpolated 2D and Raman/frequency-slice maps. Scientific map controls include automatic/manual/percentile colour ranges, linear/log/symmetric/diverging normalization, explicit contour levels and labels, measured-point/triangulation/boundary overlays, measured or interpolated extrema with provenance, aspect control, and live X/Y/intensity readout. Rendered grids, horizontal/vertical/arbitrary profiles, rectangular ROI statistics, and contour vertices can be exported as normal worksheets. Each cut also creates a persistent editable workspace plot. Peak/Raman result maps offer Map Cuts and mouse-picked cut lines for the selected metric.
- **Independent Plot Tabs**: Each plot is a project document with its own editor, pending fields, view, and undo history. Open existing plots without reloading over edits; analysis results create new tabs. Close tabs without deleting plots, reopen them from Workspace, and use Save Project to persist every plot together. Rename and Delete are separate actions; project/app closure asks to save unsaved plot work.
- **Custom Plot Colours**: Pick from 20 swatched presets or choose any RGB/hex colour in the Series or Data Location inspector. Colours follow lines, symbols and supported fills and persist with plots, pending edits, project saves and API recordings.
- **Mouse Navigation and Pop-outs**: Pop out individual plots or comparisons into maximizable windows with their inspectors. Wheel zoom, Shift+wheel pan, and middle-button dragging affect X over its axis, Y over its axis, and both in the plot interior. Back/Home work with these gestures, including logarithmic/reversed axes. Comparison X/Y synchronization also links image-map navigation.
- **Plot Comparisons**: Choose and order 2-16 plots through **Plot > Compare Plots...**. Open a persistent comparison tab or pop-out window, arrange equal-sized grid cells, optionally match numeric X/left-Y limits, and copy or export the grid as PNG. Source plots remain independently editable.
- **Data Preparation**: Create non-destructive result sheets for filtering, sorting, duplicate removal, missing-value cleanup, binning, grouping, joins, and reshaping.
- **Responsive Docked Workspace Layout**: Size the initial window from the active screen work area, proportionally rebalance docks after window or DPI changes, and reflow the Plot Inspector without collapsing its editors. Plot actions move into a toolbar overflow menu when horizontal room is limited; on very narrow Plot layouts the Workspace navigator collapses automatically to preserve the canvas and can still be explicitly restored from View. Datasets, saved plots, and spectral-analysis sessions remain separate navigator sections, while Data receives the full central width and Raman Results appears only when a result exists or is explicitly opened.
- **Readable Light/Dark Controls**: Explicit checkbox/radio/toggle states, keyboard focus, contrasted input boundaries, readable colour swatches, and state-aware navigation icons support light, dark, and mixed palettes. Comparison readouts retain readable text while scientific figure canvases keep their chosen/export styling.
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

To record Python API calls, save your starting project, choose **Macros > Record
Macro**, perform supported operations, and open **View Recorded API Calls** to
inspect the live script. Choose **Stop Recording > Save Python API Script**.
While recording, the main window has a red edge and a persistent **Recording
(.py)** badge with a **Stop Recording** button; ordinary status messages leave
this indicator visible. Both disappear when recording stops.
The saved `run(session)` function is editable in a Python editor; use the CLI above
from the repository root. `--project` supplies sheets already in the workspace when
recording began; recorded file imports include their parser settings and paths.
The public API also provides `load_folder()` for hand-written loops over files.

Python recording now also covers worksheet editing/history/lifecycle, Excel and
large-data imports/window extraction, all Data Prep operations, statistics and
companion data, interpolation, baseline/Peak/Raman analysis, map cuts/ROI/contours,
analysis-table export, plot deletion, and ordinary project saves. Batch summaries,
fit reports, and correlations are recomputed from replayed results. Background
spectral operations are recorded only when their results are published.
Image-digitizer extraction, internal spectral-viewer presentation changes, nested
recipe runs remain pending. Credentials for protected
project saving are never captured. See the manual's recording coverage table;
the separate JSON batch runner retains its existing smaller scope.

To replay, choose **Macros > Run Python API Script**, review the source, choose the
allowed input folder and output parent, and click **Run Recording**. Existing files
are never overwritten. Cancel, errors, and workspace changes discard staged results.
The CLI uses the same restricted interpreter:

```powershell
python main.py --run-script recording.py --project starting.jasc --input-dir measurements --output results.jasc
```

For a complete runnable example, see [Test_Data/Macro_Example/README.txt](Test_Data/Macro_Example/README.txt).
Three seeded noisy Gaussian spectra and `process_spectra.py` demonstrate folder
import, missing/duplicate cleanup, background subtraction, LOWESS visualization,
weighted fitting, statistics, CSV/PNG export and an equal-cell comparison. The
example includes independent ground truth, a comparison preview and an end-to-end
test. Start with an empty GUI project; no starting project file is needed.

For examples across the application, start with [Test_Data/README.txt](Test_Data/README.txt)
and the [feature catalog](Test_Data/Feature_Examples/README.txt). Fourteen numbered
families provide synthetic inputs, expected results and GUI walkthroughs; thirteen
include restricted replay macros. Image digitization, plot interactions and protected
project saving have explicit manual steps. Regenerate inputs or verify the catalog
with the commands in that guide; no executable rebuild is needed.

Python syntax is deliberately limited to approved API calls, data literals,
recording helpers, and bounded worksheet loops. General Python programs are not
accepted. Use JASC's runner for untrusted recordings; launching an arbitrary file
with Python itself can execute its top-level code before JASC can inspect it.

For a Windows distribution, install `requirements-build.txt` in the build
environment and run `python build_windows.py`. An optional `--tools` folder can
supply a local PyInstaller installation. The build produces
`artifacts/standalone/JASC/JASC.exe` and the console entry point `JASC-cli.exe`.
Copy the **whole JASC folder**, including `_internal`; recipients do not need a
separate Python installation. Both support `--run-script` with the same arguments.
Run the opt-in bundle tests with `JASC_TEST_BUNDLE` set to that folder. A fresh
Windows VM/installer/signing audit remains a distribution follow-up.

For the Python-based Linux release, run `python build_linux.py` to create
`artifacts/releases/JASC-Linux-0.1.0.sh`. On the target machine use
`sh JASC-Linux-0.1.0.sh`: it verifies and extracts the included application,
creates a private virtual environment, downloads dependencies and checks the GUI
before creating `JASC` and `JASC-cli` launchers in `~/.local/opt/JASC-0.1.0`.
This installer needs Python 3.10-3.12 with venv/pip, internet and compatible Qt
desktop libraries. It does not require root or change the system Python.
Use `--install-dir PATH` for a different new directory, `--verify` for checksum
verification only, or `--extract-only PATH` for offline source extraction.
See [LINUX_INSTALL.txt](LINUX_INSTALL.txt) for requirements and troubleshooting;
Linux installation is not a guarantee of support on every distribution/CPU.

For the earlier batch-recipe workflow, choose **Macros > Record Macro**, import a representative file or
use the selected sheet, apply **Smoothing** and **Curve Fit** to one Y column,
and create/style ordinary XY plots. Choose **Stop Recording**, then **Review /
Run Batch Recipe**. Select workspace inputs and/or add folder files, preview compatibility,
and run. Inputs bind by exact column name; earlier generated columns bind to
their producing step. Replay preserves original workspace sheets and creates new
results. Recording gaps from unsupported data changes block replay; start a clean
recording to resolve them. Save the macro separately from the project. Parameter
seeds are reused independently for every fit, and transformed signals cannot
silently reuse raw measurement uncertainties.

To try asymmetric data, choose the **Errorbar** plot subtype and enable **Use X/Y
percentile bounds** in the Series inspector. Select endpoint columns (not widths),
set their percentile levels, and identify the centre/origin. In **Curve Fit >
Uncertainty**, the same controls select the median measurement likelihood. A
single Y-bound pair maps to one response column; batch worksheets and optional X
uncertainty are supported. Posterior quantiles and non-median centres can be
plotted but are not used as measurement likelihoods. The documented quantile
model assumes independent points and Gaussian tails; correlated/systematic
errors and bootstrap/profile intervals remain follow-ups. The composite peak
core accepts the same likelihood through its numerical API; its dedicated
Peak/Raman dialog does not yet expose bound-column mapping.

`benchmarks/theme_visibility_audit.py --output artifacts/theme_visibility_fixed`
captures actual controls in six style/palette combinations and a comparison
readout. The full regression suite also checks percentile calibration, normalized
densities, fit recovery, asymmetric plotting, and persistence. UI previews are in
`artifacts/asymmetric_uncertainty/`.

The independent-plot document/tab layout now includes comparison views. Run
`main.py`, select **Plots**, and use **New Plot** or **+**. Open two plots, edit one,
switch back and forth, close/reopen a tab from Workspace, and save/reopen the
project. An asterisk marks changes since project save. **Rename** replaces the
old separate Save Plot action. Pending series fields are saved as editor drafts;
**Update Series** still applies them to the rendered plot. Closed canvases are
released and recreated on demand. A preview is in `artifacts/plot_tabs_preview.png`.

Try **Plot > Compare Plots...** after creating two plots. Select/reorder sources,
choose rows and columns or **Fit Grid**, and optionally open a separate window.
**Pop Out** and **Return to Tab** move the same view; closing the window returns
it to its tab. Individual plot tabs also have **Pop Out**, and all plot windows
support normal window maximization. **Synchronize X axis** / **Synchronize Y axis**
link compatible numeric panels, including image maps, without converting
units; Y matching concerns the left axis. Applied source definitions refresh after
edits; use **Refresh** after worksheet value changes. Comparisons reference plot
identities and save with the project; deleted sources keep a visible placeholder.
Pending series edits still need **Update Series**. Equal cells preserve native
aspect ratios, legends, and colour bars, so inner plotting areas can differ.
Export currently produces PNG; shared legends, vector/PDF page export, insets,
and arbitrary page composition remain future work. Actual-widget previews are
`artifacts/plot_comparison_preview.png` and
`artifacts/plot_comparison_popout_preview.png`.

Use the wheel to zoom around the pointer, **Shift+wheel** to pan, or drag with the
middle mouse button. Pointer location determines the affected axes: X ticks/label
or spine restrict to X, Y ticks/label or spine restrict to that Y axis, and the
plot interior affects both (including a secondary Y axis). Map colour bars are
excluded. Navigation does not also scroll the comparison container, and pauses
during interactive map-cut picking. Back/Forward/Home include these gestures.
Previews: `artifacts/plot_popout_preview.png` and
`artifacts/comparison_image_sync_preview.png`.

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
