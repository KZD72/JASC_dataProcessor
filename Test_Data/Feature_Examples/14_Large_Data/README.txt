DISK-BACKED BROWSING AND EXPLICIT WINDOWS
========================================
Replay run_example.py with this directory as input; start an empty project.
sensor_log.csv is deliberately small (12,000 rows) so the demo is quick. It tests
the disk-backed API and paging semantics, not larger-than-RAM performance.

GUI: File > Open Large Dataset, select sensor_log.csv, comma/header present.
The source is read-only; browse pages and select columns. A visible page is a
bounded window, not the full source. Go to row 2501 and use Create worksheet from
this window; the GUI copies its current window (up to 1,000 rows). Run Statistics
on that extracted signal and inspect its source-range provenance metadata.
The supplied macro instead requests exactly 400 rows from zero-based start=2500,
columns 0..3. Those are visible 1-based source positions 2501..2900. A default GUI
window may contain more rows, so compare its statistics using its actual range.

Expected for the macro: row_id 2500..2899; time_s=row_id*0.01; signal=1+0.002*row_id;
mean signal=6.399. Output has exactly 400 rows, not 12,000. The complete source
is retained separately in the result project and should reopen without the CSV.
Replay exports window.csv and window_statistics.csv, retaining the disk-backed
source inside _jasc_result.jasc. Full-source analysis/editing is not implied.
For a general responsive UI check, start a longer operation on your own larger
disposable file and try Cancel; this small sample is not a cancellation benchmark.
