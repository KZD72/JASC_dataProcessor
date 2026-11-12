JASC MACRO EXAMPLE: THREE SYNTHETIC GAUSSIAN SPECTRA
=================================================

Start with process_spectra.py. It is an editable macro containing approved JASC
API calls. The input files are already supplied; Python is not needed when using
the packaged application.

comparison_preview.png shows the expected three-panel result from a tested run.

RUN THROUGH THE GUI
-------------------
1. Start with a NEW, EMPTY project so the example sheet/plot names are available.
2. Choose Macros > Run Python API Script.
3. Browse to Test_Data/Macro_Example/process_spectra.py.
4. Allowed input folder: Test_Data/Macro_Example (NOT its input subfolder).
   The macro imports the relative folder "input" below this access root.
5. Save run inside: Test_Data/Macro_Example/results, or another output folder.
6. Click Run Recording. No starting .jasc project is required.
7. Select the *_processed and *_fit_parameters worksheets under Data. Open the
   three *_analysis plots or "Synthetic spectra comparison" under Plots.

For a second GUI trial, start another empty project. The macro's final comparison
looks up the three supplied plot names; an existing workspace can cause naming
collisions. The command-line examples below start fresh on every run.

RUN FROM THE REPOSITORY ROOT WITH PYTHON
--------------------------------------
python -m jasc_api Test_Data/Macro_Example/process_spectra.py --input-dir Test_Data/Macro_Example --output-dir Test_Data/Macro_Example/results

RUN FROM THE REPOSITORY ROOT WITH THE WINDOWS BUNDLE (PowerShell)
--------------------------------------------------------------
.\artifacts\standalone\JASC\JASC-cli.exe --run-script Test_Data\Macro_Example\process_spectra.py --input-dir Test_Data\Macro_Example --output-dir Test_Data\Macro_Example\results

Keep the full bundle folder, including _internal. Run the macro through JASC's
runner, which validates its commands and limits file access.

WHAT THE INPUT DATA CONTAINS
---------------------------
input/spectrum_01.csv, spectrum_02.csv and spectrum_03.csv contain:
  x             X coordinate, in arbitrary units.
  signal        Gaussian peak + a linear reference background + Gaussian noise.
  signal_sigma  Known standard deviation of independent measurement noise in Y.
  background    Exact synthetic reference background, with no uncertainty.

Each file has 407 shuffled rows: a 401-point grid, six exact duplicate samples,
and five samples with a missing signal. Noise is generated with fixed seeds.

The separate expected_truth.json records the true peak parameters, noise levels,
seeds and acceptance tolerances. The macro NEVER reads this file when fitting.

TREATMENT STEPS
---------------
1. Load all CSV files from input.
2. Drop missing measurements, remove duplicate X samples, and sort X.
3. Subtract the supplied exact background using a column formula.
4. Add a LOWESS smoothed column for visualization only. LOWESS handles the uneven
   spacing left by dropping missing samples; no artificial measurements are added.
5. Fit the UNSMOOTHED corrected observations with a weighted Gaussian model:
      offset + amplitude * exp(-0.5*((x-center)/sigma)^2)
   Weights use signal_sigma with absolute_sigma=True. The fitted Gaussian sigma
   is a width in X; it is different from the measurement noise signal_sigma in Y.
   Smoothing is not used for fitting, so its correlated errors are not treated
   as independent measurements. Real uncertain backgrounds need extra modelling.
6. Build parameter/quality tables and descriptive statistics.
7. Plot measurements/error bars, smoothing, fitted curves and 95% fit bands.
8. Export tables and individual plots.
9. Export a three-panel comparison with synchronized X/Y axes and equal cells.

EXPECTED OUTPUTS
----------------
JASC creates a NEW results/jasc_script_run_<timestamp>_<id> folder every time:
  _jasc_result.jasc   Complete workspace: 18 worksheets and four saved plots.
  _jasc_run.json      Run information and the reviewed macro's source hash.
  tables/            15 CSV files: processed data, curves, residuals, fit
                     parameters, and statistics for each spectrum.
  figures/           Three individual PNG figures and comparison.png.

Each *_processed sheet should have 396 rows, strictly increasing unique X,
and finite corrected/smoothed values. Original imported sheets remain unchanged.
Inspect param_amplitude, param_center, param_sigma, param_offset, point_count,
r_squared and rmse in each *_fit_parameters table. Approximate true parameters:

  spectrum       amplitude   center   sigma (peak width)   offset
  spectrum_01       8.0       -0.8           0.65             0.0
  spectrum_02      10.0        0.2           0.80             0.0
  spectrum_03       6.5        1.0           1.05             0.0

Noise makes the estimates slightly different from these true values. Automated
checks use the explicit tolerances in expected_truth.json rather than requiring
exact coefficient equality. Fit bands describe local uncertainty of the fitted
mean curve; they are not prediction intervals for individual observations.

TRY RECORDING YOUR OWN WORKFLOW
-------------------------------
1. Start a new project, import input/spectrum_01.csv, and save a starting .jasc
   project BEFORE recording. This preserves the input sheet used by your calls.
2. Choose Macros > Record Macro. Check the red window edge and persistent
   Recording (.py) badge. Perform operations through the normal dialogs, for
   example missing-value cleanup, sorting, a formula, smoothing and plotting.
3. Open View Recorded API Calls to inspect captured semantic calls. Stop Recording
   and choose Save Python API Script. Unsupported changes must be resolved before
   a complete recording can replay; do not assume every dialog is recordable.
4. Reopen the saved starting project, then Run Python API Script on your recording.
   Choose this example directory as its input folder and a fresh output parent.
   If you imported files while recording instead, the script contains those import
   calls and needs the corresponding files under its allowed input root.
5. For the smaller JSON Batch Recipe workflow, make a separate simple recording
   containing only supported smoothing, Curve Fit and basic XY plot steps; select
   workspace sheets and/or compatible folder files in Review / Run Batch Recipe.
   Data Prep and other broader Python API steps are not JSON recipe support.
   Use the processed worksheets from a successful demo run for this simpler
   recipe; the raw CSVs deliberately contain missing/duplicate measurements.

OPTIONAL REGENERATION (DEVELOPER UTILITY, NOT A MACRO)
---------------------------------------------------
python Test_Data/Macro_Example/generate_data.py

This trusted Python helper uses NumPy/Pandas to recreate the three bundled CSV
files and expected_truth.json with the same seeds. It overwrites those example
input files. Do not select generate_data.py in JASC's restricted macro runner.

AUTOMATED CHECK (FROM THE REPOSITORY ROOT)
----------------------------------------
python -B -m unittest tests.test_macro_example

This runs the real restricted child-process player, verifies cleanup and exports,
checks parameter recovery against the known truth, and confirms that the input
files were not modified.

The demonstration is intentionally small. You may add compatible CSV files to
input; they receive the same per-file processing. The final comparison explicitly
selects only the three supplied spectra and can be edited to select other plots.
