ONE-, TWO- AND N-DIMENSIONAL INTERPOLATION
=========================================
Replay run_example.py with this directory as input; start an empty project.
GUI: Analysis > Interpolation. Source coordinates and query coordinates are
explicit; no source data is silently replaced.

line.csv: coordinate x, value value, PCHIP, generated 0..4 with 17 points.
Expected value_interpolated=2*x+1. Compare linear, cubic spline and Akima as variants.
plane.csv: coordinates x/y, value z, linear, mesh ranges -1..1 (9 each). Expect
81 rows with z_interpolated=2*x+3*y+1. Try nearest/RBF as variants; these need not
give the same affine result for every kernel/settings combination.
volume.csv: coordinates x/y/z, value value, linear, manual point "0.5,0.5,0.5".
Expected value_interpolated=3. This is a numerical 3D query, not a 3D plot feature.
Outside policy: line source, linear, manual x=-1,0,4,5, outside=blank. The first
and last prediction are blank; boundary predictions are 1 and 9.

The macro exports four query tables. Interpolated points are predictions, not
additional measured samples. Metadata identifies interpolation provenance.
