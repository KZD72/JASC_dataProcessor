PLOTS, COMPARISONS AND MAP PRODUCTS
==================================
Replay run_example.py with this directory as input; start an empty project.
The macro creates and exports every registered plot subtype (19 subtypes), plus
dual-Y and scattered-map variants and two comparisons. Use its saved plot tabs
to experiment without rebuilding data mappings for each chart.
comparison_preview.png is an actual exported 3x3 result from the supplied macro.

curves.csv: x versus sine/cosine; sigma=0.1 for symmetric error bars; right_scale
demonstrates an independent right Y axis. Try line, scatter, line+markers, area,
histogram, box and violin. Distribution columns can include sine and cosine.
categories.csv: text label/value for bar, horizontal bar, pie, donut or Voronoi.
Values sum to 10, so fractions are 10%,20%,30%,40%. Voronoi areas are approximate.
map.csv: x/y/z, exact 21x21 native grid, z=4-x^2-y^2. Try heatmap, contour and filled
contour, colour limits/normalization, palette, labels, overlays and measured extrema.
scattered_map.csv: use Interpolated mode and show measured points/boundary. Keep
measured and interpolated extrema distinct; they are not interchangeable evidence.
spectral_map.csv: Spectra Plot, X/Y, shift, Intensity, target center=240. At that
measured shift intensity=7+X+Y. Try spectral heatmap/contour/filled contour and
closest/linear spectral sampling. Sampling in shift is distinct from XY interpolation.

Analyse Map: grid, horizontal y=0, diagonal (-2,-2) to (2,2), rectangular ROI
[-1,1]x[-1,1], contours. Horizontal cut follows 4-x^2; map maximum is (0,0,4).
Replay exports these five tables and 23 PNGs, including a 3x3 family comparison
and two synchronized maps. Equal cells do not force identical inner axes margins.

MANUAL GUI CHECKS: open independent tabs, edit one, switch/close/reopen, rename,
save the project. Pop Out, maximize, Return to Tab. Wheel zoom; Shift+wheel pan;
middle-button drag. X-axis region affects X only, Y region Y only, interior both.
Synchronized maps should move together; comparisons across unlike units should
not be synchronized. Try direct axis/title/legend edits, locators, log/reversed
axes, light/dark themes and narrower window sizes. Look for readable checkbox,
selection and focus states. These interaction checks are not simulated by the macro.

CUSTOM COLOURS: select a line/scatter/bar series, then Series > Color > Custom.
Pick any colour or enter RGB / HTML hex (for example #13a2a7). Update Series and
check lines/symbols/fills. The dropdown includes 20 presets with colour swatches;
Auto restores the style cycle. Custom colours persist in project/recording exports.
Try choosing a colour without updating, close/reopen the tab, and confirm the
pending choice is retained. Data Location has the same custom picker for locators.
