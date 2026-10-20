Synthetic 2D-map fixtures
=========================

SurfaceMap_RegularGrid.csv is a complete 5 x 5 Cartesian grid. Its signal is
defined exactly by:

    Signal_V = 10 - (X_mm - 1)^2 - (Y_mm + 1)^2

The measured global maximum is therefore 10 V at (1, -1), and the measured
global minimum is -8 V at (-2, 2). Use this file to test native-grid rendering,
extrema labels, diverging colour normalization, profiles, ROI statistics and
contour extraction.

SurfaceMap_Irregular.csv is an intentionally scattered, non-rectangular point
cloud with signed values. Use it to test interpolation, measured-point and
triangulation overlays, convex-hull boundary display/masking, robust percentile
colour limits and measured versus interpolated extrema provenance.

Both files are deterministic synthetic examples and contain no experimental
measurements.
