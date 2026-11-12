TEXT AND EXCEL IMPORT
=====================
Replay run_example.py using this directory as allowed input; start an empty project.
See ../README.txt for shared GUI and command-line instructions.

GUI: File > Import Data. Try comma.csv, tab.txt and utf16.txt with Auto options.
Import preamble.txt with delimiter semicolon, two skipped metadata lines, header
present; check that Experiment/Operator text survives as worksheet metadata.
Import headerless.dat with whitespace separator and Header absent. Generic column
names are intentional. Batch comma.csv and headerless.dat to see the mixed-header
decision; keep detected headers or deliberately choose generic columns.
For decimal_comma.txt choose semicolon and comma-decimal numeric format. Avoid
letting decimal commas become field separators. For cp1252.txt use Windows-1252;
labels should display cafe/creme with their original accented letters.
Import two_sheets.xlsx and select both Measurements and Groups tabs. These are
values only; this example does not imply Excel chart/VBA/formula execution support.

Expected: standard numeric variants have six rows, y=2*x+1. Decimal-comma input
has x=[0,0.5,1], y=[1,2,3]. Excel tabs contain six measurements and two group labels.
Replay exports nine CSV tables and retains all imported sheets/metadata in its
result project. Original files are never changed. Instrument-specific dialects
are not modeled by these generic examples; normalized spectral data is in family 10.
