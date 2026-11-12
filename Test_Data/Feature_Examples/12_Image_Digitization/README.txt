IMAGE DIGITIZATION (MANUAL WORKFLOW)
===================================
There is no run_example.py: calibration, trace choices and ambiguity review are
not yet recording adapters. The PNGs are reproducible scientific charts, with
independent truth in expected.json and linear_truth.csv. Use supplied images;
no Python or image-generation service is needed to try the workflow.

LINEAR XY: File > Import From Figure, open input/linear_curve.png. No perspective
correction is needed. In Calibration select linear X and Y axes. Pick X=0 and
X=10 at the left/right ends of the bottom axis; Y=0 and Y=25 at the bottom/top
of the left axis. Pixel reference locations (960x600 image, top-left origin):
X (115.2,510)->0, (864,510)->10; Y (115.2,510)->0, (115.2,60)->25.
Pick several blue-line points manually. Then try automatic tracing by selecting
the blue curve colour/region. Try symbol detection on red circles, not axis ticks.
Review candidates/outliers and extraction uncertainty before creating the dataset.
Expect y=2*x+3: at x=5, y about 13, with a useful initial tolerance of 0.2 Y units.
Raster resolution and click placement set practical accuracy; do not expect exact
floating-point agreement with the analytic reference CSV.

MULTIPLE/RESUMED DATASETS: Create Dataset & Continue for one trace, then another.
Save .jasc; reopen and Data > Resume Figure Extraction from an extracted sheet.
The embedded working image/calibration should remain usable without the source PNG.

LOG XY: open input/log_curve.png, use logarithmic X/Y calibration at 1 and 100.
Extract y=3*sqrt(x); at x=10 expect about 9.487. Calibrating this as linear is a
deliberate wrong-setting demonstration, not an alternative correct answer.

HEATMAP: open input/heatmap.png, choose 2D colour plot workflow. Calibrate X/Y
from -2 to 2. Calibrate the colour-bar ends as 0 and 1 with a linear scale and
choose/probe the displayed viridis colours. The field is exp(-x^2-y^2), about 1
at the center and 0.368 at (1,0). Colours are finite raster samples; inspect the
preview/error estimates. Save exported numerical data, then apply normal macros.
