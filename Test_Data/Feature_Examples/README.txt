JASC FEATURE EXAMPLE CATALOG
===========================

Each numbered family has input/, expected.json, and README.txt. Thirteen also
have run_example.py, an editable restricted JASC macro. The image digitizer is
intentionally a manual walkthrough. catalog.json lists features and entry points.
Inputs are synthetic and contain no real experimental or personal information.

FAMILY                              WHAT TO TRY
01_Import                           CSV/TXT/DAT, encodings, decimal comma, Excel
02_Worksheet_Editing                Smart Fill, paste, metadata, undo/redo, sheets
03_Data_Preparation                 Missing/duplicates/filter/subset/sort/group/join/bin/melt
04_Formulas                         Safe math, cross-sheet references, selected rows
05_Signal_Processing                 All six smoothers, derivative/integral, FFT/iFFT
06_Interpolation                    1D, 2D, N-D, generated/manual query, outside bounds
07_Statistics                       Single/pair/multi/group, PCA, tests, companion data
08_Curve_Fitting                    Built-in and custom models, bounds, reports, fit bands
09_Asymmetric_Uncertainty            Percentile endpoints, plotting and likelihood fitting
10_Spectral_Analysis                 Baseline, peak review/composite fitting, Raman maps
11_Plots_and_Maps                    Every registered plot subtype, maps, comparisons/cuts
12_Image_Digitization                Linear/log XY, trace/symbol picking, colour probes
13_Projects_and_Export               .jasc round-trip, data/figure export, protection steps
14_Large_Data                       Disk-backed browsing, explicit window, scope metadata
../Macro_Example                    Recording feedback and whole-folder processing

RUN ANY REPLAY EXAMPLE THROUGH THE GUI
------------------------------------
1. Start a NEW, EMPTY project. Names are deliberately readable, so do not stack
   multiple runs in one workspace. Save existing work before starting.
2. Choose Macros > Run Python API Script and select the family's run_example.py.
3. Allowed input folder: THAT NUMBERED FAMILY DIRECTORY, not input/ and not the
   whole Test_Data folder. All imports are relative to that root.
4. Save run inside: that family's results/ directory or an output parent of your
   choice. The runner creates a fresh jasc_script_run_* subfolder on every run.
5. Run Recording. Inspect Data, Plots and (for spectral fits) Raman Results.
   _jasc_result.jasc retains the completed workspace; _jasc_run.json records the
   reviewed source hash. Open the result project to revisit the example later.
6. Follow the family's README for GUI variations and compare with expected.json.

RUN FROM SOURCE (REPOSITORY ROOT)
---------------------------------
python -m jasc_api Test_Data/Feature_Examples/05_Signal_Processing/run_example.py --input-dir Test_Data/Feature_Examples/05_Signal_Processing --output-dir Test_Data/Feature_Examples/05_Signal_Processing/results

Substitute another numbered family in all three locations. With a Windows bundle,
replace "python -m jasc_api" with "<bundle>/JASC-cli.exe --run-script". Keep the
whole bundle folder including _internal. Use JASC's runner; do not launch an
untrusted .py file directly through Python. No executable rebuild is performed.

EXPECTED RESULTS AND COVERAGE
-----------------------------
expected.json describes analytic answers, planted conditions, and tolerances;
macros never read it. Exact/noise-free examples test numerical answers; noisy
examples use explicit tolerances. Raster picking needs pixel-scale tolerances.
Fit confidence bands describe fitted means, not individual-observation predictions.
These are representative workflows per family, not exhaustive numerical validation
of every fit model, optimizer, statistics assumption, or import instrument dialect.
Manual tasks (image review, mouse navigation, theming, signing/encryption) are
clearly identified in each walkthrough and are not claimed as automatic coverage.

REGENERATE INPUTS / CHECK EXAMPLES (DEVELOPERS)
---------------------------------------------
python -B Test_Data/Feature_Examples/generate_data.py
python -B Test_Data/Feature_Examples/generate_data.py --output <separate-folder>
python -B -m unittest tests.test_feature_examples

generate_data.py is a trusted Python utility, not a JASC macro. It overwrites only
the generated input files and expected.json in these fourteen family directories;
it does not rewrite macros, guides, or legacy Test_Data files. Fixed seeds, normalized
Excel ZIP timestamps and stable CSV formatting make repeat runs reproducible in
the same dependency environment. The supplied files are ready to use as-is.
The 12,000-row disk example demonstrates paging; it is not a larger-than-RAM benchmark.
