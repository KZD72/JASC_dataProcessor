# Large Data Loading and Clipboard Performance Audit

Latest execution slice: 2026-10-30. Loading/clipboard re-evaluation: 2026-10-21. Original audit: 2026-08-17.

## Background Peak/Raman Fitting Slice (2026-10-30)

`core/peak_fit_jobs.py` captures no Qt objects or live workspace. The GUI copies
only the input columns; the worker groups map pixels lazily, validates numeric
inputs, corrects baselines, detects/matches components, fits spectra sequentially,
and assembles the session plus optional worksheets. The shared background-job
controller delivers real spectrum-count progress and GUI-thread completion.
Cancellation propagates between phases and from optimizer residual evaluations;
it discards all pending outputs. Native baseline/detection calls still finish
their current phase before stopping. Individual failures remain in QC/metrics
while other spectra continue.

Completion checks workspace identity, source dataset identity, projected data,
and column metadata before publication, including edits outside the visible table
model. A publication failure rolls back all newly added worksheets and sessions.
Closing or replacing a project requests cancellation, and window destruction
waits for worker termination. Only one import/fit job uses the shared controller
at once. Preview fitting and baseline-only map correction remain synchronous;
this does not migrate Excel/project I/O or other analysis families.

Measured with `benchmarks/background_peak_fit_audit.py`, using 400 seeded
Gaussian spectra of 601 samples each (7.34 MiB input), including GUI input capture,
result publication, and offscreen viewer rendering:

| Measurement | Result |
| --- | --- |
| Full run | 5.336 s; all 400 fits succeeded; one analysis and no optional worksheets |
| 10 ms GUI heartbeat | 349 ticks; p95 gap 19.24 ms; maximum gap 136.75 ms |
| Cancellation requested by a 100 ms timer | Stopped 5.82 ms after actual delivery; no analyses or worksheets published |
| Process working set, before / after success | 274.0 / 327.8 MiB; process peak 353.1 MiB |

Raw results: `benchmarks/background_peak_fit_2026-10-30.json` and
`benchmarks/background_peak_fit_cancel_2026-10-30.json`. These are timer-delivery
measurements on one synthetic case, not a desktop interaction or vendor-map
capacity claim. Input snapshots, per-spectrum results, and combined result tables
remain in memory; initial input copying and final source comparison/rendering
still run on the GUI thread. Larger-than-RAM analysis and process parallelism
remain future work. Recorded environment: Python 3.13.13, Pandas 3.0.3, NumPy 2.4.4,
PySide6 6.11.0. The existing Pandas/NumPy dependency drift remains unresolved.

The full **295-test suite passes** in 73.135 s. Eleven new regressions cover
worker/GUI affinity and heartbeat, per-spectrum failure isolation, cancellation
during preprocessing/optimizer work and after queued success, cancellation after
a successful pixel with restart, stale source/project rejection, rollback after
publication failure, and deferred close. The existing map-fit integration test
now waits for asynchronous completion and preserves its numerical/output checks.

## Polars/Parquet Paged Table Slice (2026-10-21)

Implemented an explicit **Open Large Dataset** workflow and separate workspace registry for read-only disk-backed sources. Regular separated text is incrementally transcoded to UTF-8, then written through Polars' streaming Parquet sink; existing Parquet is snapshotted with bounded copies. Source tables never become complete Pandas DataFrames. Text columns remain strings to avoid sample-based numeric corruption; vendor-specific layouts and whitespace tables are deferred rather than silently interpreted as ordinary tables.

`LargeDataView` holds one replaceable data-buffer window capped at 1,000 rows, 32 projected columns, and 8 MiB estimated Polars data size. Oversized windows shrink and a single over-budget row fails safely. Cell callbacks never query disk. Background requests coalesce and check source/generation before commit; old windows are evicted. Edge-wheel navigation, Previous/Next, global row jumps, column windows, global row labels, copy, retry, and explicit window-to-worksheet extraction are implemented. Ordinary analysis and undo never see a partial source disguised as a complete worksheet. A full-source lazy scan boundary is available; full-source filtering/analysis controls remain future work.

Version-9 projects stream embedded Parquet members to/from disk and preserve the existing package seal, signing, and encryption path. Ordinary-only projects continue to write version 8. Project I/O is still synchronous. Large-import cancellation rejects results and cleans temporary storage; native Polars phases finish cooperatively before cancellation takes effect. Closing retains both import and page worker owners until they stop.

Measured with `benchmarks/paged_large_data_audit.py`, including a visible offscreen Qt view and 60 distant windows; synthetic CSV generation uses bounded chunks outside the timed interval:

| Measurement | 1,000,000 x 10 | 4,000,000 x 10 |
| --- | --- | --- |
| Source CSV / Parquet snapshot | 88.29 / 7.60 MiB | 382.02 / 29.49 MiB |
| Disk-backed text preparation | 3.589 s | 12.740 s |
| Median / maximum window load (includes 40 ms debounce and GUI delivery) | 87.2 / 107.0 ms | 82.6 / 101.2 ms |
| Maximum cached rows / data bytes | 1,000 / 91,200 | 1,000 / 99,200 |
| GUI heartbeat p95 / maximum gap | 12.9 / 24.0 ms | 12.8 / 20.4 ms |
| Navigation working set after first 10 windows | 302.0-334.0 MiB | 358.5-383.7 MiB |
| Maximum sampled process working set including import | 483.7 MiB | 903.1 MiB |

These measurements establish bounded display windows and responsive navigation for these cases, not a total-process 1,000-row memory cap or proof of 10 GB/larger-than-RAM capacity. Native decoder/streaming buffers, memory-mapped input pages, Qt, in-flight results, and allocator retention require additional memory; import working set rises with this larger source. Memory-budget hardening and larger capacity tests remain necessary. No speed comparison against DuckDB was performed; Polars is the first implementation, not a benchmark-selected winner. Raw results: `benchmarks/paged_large_data_2026-10-21.json` and `benchmarks/paged_large_data_4m_2026-10-21.json`. Official API references: [Polars streaming Parquet sink](https://docs.pola.rs/api/python/stable/reference/api/polars.LazyFrame.sink_parquet.html), [lazy CSV scan](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_csv.html).

## Background Text Import Slice (2026-10-21)

Implemented a reusable thread-based job controller with Qt-independent cancellation/progress contracts, queued GUI-thread delivery, controlled errors, rejection of late cancelled results, and thread ownership through complete termination. Keep the worker's Python wrapper alive until its thread has joined; releasing it early exposed a native Qt lifetime race during regression testing. Window close requests cancel and defer destruction until the active job stops.

Text preflight, explicit-rule reinspection, parsing, and preamble/provenance preparation now run off the GUI thread. Status-bar controls show the current phase, actual byte progress during CSV parser reads, and Cancel. Numeric/locale checks and result metadata remain unchanged. The optional `read_tabular_file(context=...)` path wraps binary reads to check cancellation, throttles progress notifications, and checks again between conversion phases; ordinary synchronous API calls remain compatible. Encoding detection now opens the file and reads only the sample, fixing `read_bytes()[:sample_size]`, which previously allocated the entire file before slicing.

Prepared data is detached from the live workspace. Size decisions and metadata hints run on the GUI thread before publishing the accepted batch. A cancelled run adds no sheets, even if earlier files were already prepared. A failed commit rolls back all newly added sheets; failures in individual source/metadata reads are reported without publishing that incomplete file. Project changes reject stale results. Import reentry is prevented until the current run finishes.

`benchmarks/background_import_audit.py` exercises the real asynchronous import path with a synthetic 1,000,000 x 10 numeric CSV (89.25 MiB), bypassing only file/options/size prompts. It measures Qt timer delivery rather than physical screen painting; synthetic input is generated outside the timed interval. Results under the same development environment as the first slice:

| Run | Result |
| --- | --- |
| Successful full import | 1.751 s including GUI commit; 1,000,000 rows published |
| 10 ms GUI heartbeat during import | 166 ticks; 95th-percentile gap 10.8 ms; maximum gap 100.4 ms |
| Cancellation requested after 50 ms timer delay | Completed 10.6 ms after actual request delivery; no datasets/rows published |
| Cancellation heartbeat | Maximum gap 26.5 ms; no reported errors |

Raw results are in `benchmarks/background_import_2026-10-21.json` and `benchmarks/background_import_cancel_2026-10-21.json`. Reproduce with:

```powershell
& 'C:\Users\julia\anaconda3\envs\dataProcessing\python.exe' -B benchmarks/background_import_audit.py --output benchmarks/background_import_2026-10-21.json
& 'C:\Users\julia\anaconda3\envs\dataProcessing\python.exe' -B benchmarks/background_import_audit.py --cancel-after-ms 50 --output benchmarks/background_import_cancel_2026-10-21.json
```

All **267 tests pass**. Eleven new background/import regressions cover event-loop responsiveness, worker versus GUI callback affinity, duplicate-job protection, queued-success cancellation, restart/error recovery, cancellation after the first batch file, stale-workspace rejection, incomplete metadata, commit rollback and GUI affinity, deferred close, cancellation during real parser reads with released file handles, bounded encoding detection, and encoding/locale/map equivalence. Existing batch-import tests now wait for asynchronous completion and explicitly dispose their widgets on the GUI thread. `git diff --check` passes; README, roadmap, handoff, and Markdown/PDF manual are synchronized.

Cancellation remains cooperative: a native conversion, map-array allocation, or legacy Bruker parsing phase may finish its current work unit before stopping. This slice is still in-memory Pandas and does not implement chunked storage, delta undo, process-worker jobs, or background Excel/project/analysis execution. Those are subsequent migrations onto this controller. Desktop interaction and representative very large vendor files remain manual follow-up checks.

## First Implementation Slice (2026-10-21)

The import/validation/formula improvements below are implemented and verified. The assessment in the following section is the preserved pre-change baseline. Recorded after-change results are in `benchmarks/large_sheet_audit_phase1_2026-10-21.json`, using the same ten-case harness and environment as the baseline.

| Path | Baseline | After this slice |
| --- | --- | --- |
| Auto import, 100,000 x 10 numeric CSV, 8.16 MiB | 5.511 s | 0.173 s |
| Auto import, 1,000,000 x 2 numeric CSV, 18.61 MiB | 11.409 s | 0.367 s |
| Explicit dot-decimal import, same million-row CSV | 3.560 s | 0.350 s |
| Million-point X/Y preparation | 0.699 s | 0.0169 s |
| Million-point line construction, excluding subsequent explicit canvas paint | 0.888 s | 0.215 s |
| Million-row safe `sin(col1)` evaluation | 0.468 s | 0.00670 s |
| GUI timer maximum gap during that formula | 0.518 s | 0.0148 s |
| One selected spectral slice over 1,000,000 source rows | 1.337 s | 0.0734 s |
| One-cell edit, 1,000,000 x 10 sheet with snapshot history | 0.0737 s | 0.0251 s |
| One-cell edit, 4,000,000 x 10 sheet above snapshot budget | 0.0381 s | 0.000983 s; still no undo |

Changes:

- Standard numeric point-decimal text tables now use the native float reader after a bounded parser-selection probe. The complete file must still parse; explicit comma formats and Python/whitespace parsing retain the strict raw-token path. Round-trip float parsing preserves precision and signed zero. Boolean probe columns are rejected; native parsing disables internal low-memory chunks to prevent a late Boolean-only chunk becoming 1/0. An invalid token, nonfinite overflow, or all-missing column triggers the raw-token fallback. This is an in-memory fast path, not chunked or out-of-core ingestion.
- Locale conversion now computes each convention's finite numeric candidates once per column and reuses the evidence. Only ambiguous columns wait for table-wide evidence. Invalid/mixed columns retain their exact original strings; explicit formats and grouping rules stay supported. Direct float-array conversion retains signed zero and decimal precision; exceptional conversions use the existing scalar parser.
- Calculus and formula validation bypass string conversion for native numeric dtypes after respecting explicit Text metadata. Plotting, statistics, and Data Prep avoid string conversion while preserving their existing missing/nonfinite policies and row-specific text rejection. No validation results are cached across operations.
- Formula environments bind only AST-referenced column names/aliases, reuse converted inputs within the evaluation, and avoid allocating unused row/index arrays. Name collisions, exact `col(...)` references, worksheet access, and deliberate text formulas retain their behavior.
- Native numeric cell edits no longer rescan/reconvert an already numeric Auto column. Whole-sheet history copies remain; their storage architecture has not changed.

Verification: all **256 tests pass**, including 11 new regressions covering scalar/vector locale equivalence, late malformed/Boolean/overflow/grouped tokens, table-level ambiguity, a Boolean tail beyond parser chunk boundaries, signed zero, precision, missing/nullable values, Text metadata, formula bindings, and numeric targets. All ten isolated benchmark cases completed. `git diff --check` passes. Results retain the baseline's synthetic/offscreen and dependency-version limitations; the CSV measurements describe the guarded ordinary-numeric path, not all locale/vendor files.

Next implementation slices remain the shared background-job controller and safe commits, operation-delta undo, revision-aware display reduction/map caches, and disk-backed large-data mode. Faster synchronous work does not make remaining long operations cancellable.

## Current Re-evaluation (2026-10-21)

The earlier clipboard, column-sizing, ownership-transfer, and streaming-project fixes remain implemented. The historical sections below describe their original causes and must not be read as a list of defects still present. Current measurements identify **locale conversion, numeric validation, whole-sheet history, synchronous execution, and unbounded plotted point counts** as the next priorities. This evaluation changes no application behavior.

### Method and reproducibility

Added `benchmarks/large_sheet_audit.py`, with recorded output in `benchmarks/large_sheet_audit_2026-10-21.json`. Run the complete diagnostic suite with:

```powershell
& 'C:\Users\julia\anaconda3\envs\dataProcessing\python.exe' -B benchmarks/large_sheet_audit.py --output benchmarks/large_sheet_audit_2026-10-21.json
```

Each of ten cases runs sequentially in a fresh process with Qt offscreen. Most timings are medians of three calls; CSV JASC import, project I/O, full plot construction, painting, snapshots, and undo use one call each. Fixture generation and garbage collection are outside timed regions. Synthetic numeric sheets cover 100,000 and 1,000,000 rows with 10 columns, plus a 4,000,000 x 10 worksheet (40 million cells). The spectral case covers 1,000 pixels x 1,000 spectral samples. CSVs are 8.16 and 18.61 MiB. No user files are modified; generated CSV/project files use temporary directories.

Environment: Windows, 16 logical CPUs, 63.4 GiB physical RAM (about 43 GiB available at the start); Python 3.13.13, Pandas 3.0.3, NumPy 2.4.4, PySide6 6.11.0. Pandas and NumPy exceed the repository's declared `<3` / `<2` constraints, so results describe the actual development environment, not every supported installation. Raw timings have no profiling/tracemalloc overhead. Windows working-set counters include native memory, but each recorded peak is the process high-water mark up to that point, not an isolated allocation count for the operation.

These are diagnostic results on synthetic, mostly numeric data with warm/repeated file reads. Offscreen attachment excludes physical screen painting, and viewport scrolling, real instrument exports, large Excel workbooks, complete Raman fits, process-worker startup/serialization, and multi-gigabyte files were not benchmarked. No 10 GB capability is claimed.

### Measurements

| Actual path | Input | Observed time or memory |
| --- | --- | --- |
| Editor attachment and bounded sizing | 100,000 x 10 / 1,000,000 x 10 | 20 ms / 68 ms |
| Editor attachment and bounded sizing | 4,000,000 x 10 | 505 ms |
| One-cell edit including history | 1,000,000 x 10 (76.3 MiB numeric buffers) | 74 ms median; three edits retain 228.9 MiB of undo buffers |
| Undo | Same million-row sheet | 91 ms; total process peak reached 785 MiB, including interpreter/Qt/native allocations and earlier operations |
| One-cell edit above history limit | 4,000,000 x 10 (305.2 MiB buffers) | 38 ms, but **no undo entry is created** because one snapshot exceeds 256 MiB |
| JASC Auto CSV import / explicit dot-decimal import | 100,000 x 10, 8.16 MiB CSV | 5.51 s / 1.68 s |
| Direct Pandas typed CSV reader, control | Same 8.16 MiB file | 0.057 s |
| JASC Auto CSV import / explicit dot-decimal import | 1,000,000 x 2, 18.61 MiB CSV | 11.41 s / 3.56 s |
| Direct Pandas typed CSV reader, control | Same 18.61 MiB file | 0.111 s |
| Plot X/Y preparation alone | 1,000,000 numeric points | 0.699 s; direct NumPy two-column assembly control: 0.00435 s |
| Plot construction, then explicit canvas paint | Same million-point line | 0.888 s + 0.143 s; all 1,000,000 points remain in the plotted artist |
| Numeric validation of an already numeric column | 1,000,000 values | 0.342 s |
| Safe formula evaluation `sin(col1)` | 1,000,000 values | 0.468 s; direct NumPy sine control: 0.00391 s |
| GUI timer gap while evaluating that formula | A 10 ms Qt timer, formula dispatched on GUI thread | 0.518 s maximum gap |
| Spectral map preparation at one selected shift | 1,000 pixels x 1,000 samples | 1.337 s |
| Selected fit-spectrum lookup / viewer redraw preparation | Same curves, 1,000 metric rows | 1.4 ms / 45 ms; redraw preparation excludes later canvas paint |
| Ordinary `.jasc` save / verified load | 1,000,000 x 2 synthetic numeric sheet | 1.29 s / 0.185 s |

The Pandas/NumPy controls omit JASC's locale rules, metadata checks, validation, workspace operations, and history. Their ratios show where overhead lies; they are **not promised speedups** for a complete replacement implementation. CSV compression is unusually effective for this synthetic sequence, so project times are not estimates for noisy scientific data.

Additional `cProfile` evidence is saved in `benchmarks/large_sheet_profiles_2026-10-21.json`. Profiling times are intentionally not mixed with the table's wall timings:

- Locale Auto conversion of just 20,000 x 10 cells made **1,000,000 calls** to `_parse_localized_number`: two decimal-convention parses per token during table-level inference, two again during column-level inference, then one conversion parse. The inference passes consumed most of the profiled conversion time.
- Numeric validation and formula-result validation spent most of their profiled time constructing string arrays, stripping strings, and parsing numbers that were already numeric.
- A supplementary 100,000-row mixed worksheet with one numeric and nine object-text columns took 0.864 s to evaluate `sin(col1)`. `_build_environment()` eagerly prepares every identifier and positional alias, including unused text columns; it can prepare the same column twice.
- That mixed sheet's shallow profile was 7.63 MiB versus 51.55 MiB using `memory_usage(deep=True)`. The current file/dataset warning profile is a buffer estimate and can substantially underestimate text data. Deep estimates may count shared strings repeatedly; this is not a direct measurement of uniquely owned RAM. Likewise, object snapshots copy pointer arrays and may share immutable string objects, so this ratio must not be applied blindly to undo memory.

### Findings and proposed changes

1. **Optimize locale-aware ingestion first.** `core/file_io.py::_infer_frame_number_format()` and `_convert_localized_numeric_columns()` currently inspect all tokens repeatedly and then perform Python regex/float conversion per cell. An explicit number format avoids inference but still parses every cell in Python. Introduce one shared token classification/conversion pass per column or bounded chunk, reuse its evidence, and add a vectorized path for ordinary decimal/scientific numbers. `read_csv` selected columns, row limits, and chunk iteration should bound temporary string storage. Sample only to propose a schema: validate all subsequent chunks and fall back losslessly if later tokens contradict it. Preserve mixed/text columns, raw tokens, locale ambiguity decisions, and exact leading metadata; do not replace this with unconditional inferred numeric parsing or coercion that drops text.

2. **Use dtype-aware numeric validation.** `math_engine/calculus.py::validate_numeric_column_metadata()`, `ui/plot_canvas.py::_validate_numeric_metadata()`, and `core/operations.py::_validate_expression_result_type()` stringify whole numeric arrays. Native numeric dtypes can bypass text parsing after checking declared Text metadata and the algorithm's finite/missing-value policy. Object/string columns still need complete strict conversion with visible row/example errors. Reuse validated numeric arrays within an operation. Evaluate only AST-referenced formula columns and reuse one prepared value for its name and alias. Introduce dataset/column mutation revisions before caching validation across operations; numerous current paths write directly to DataFrames, so caching without comprehensive invalidation would risk stale results.

3. **Run long work outside the Qt event loop.** The measured half-second timer gap confirms actual event starvation even for a simple formula, and imports are far longer. Build the shared job controller with progress, cooperative cancellation, stale-result protection, safe shutdown, immutable/owned input snapshots, and transactional GUI-thread commits. Use threads for I/O and suitable native numerical work; process workers for CPU-bound Python work only when transfer cost and memory fit a measured budget. Cancellation must be checked between chunks/jobs, since an arbitrary native parser or optimizer call cannot necessarily be interrupted immediately. Qt model APIs stay on the GUI thread; workers return data/results through queued signals. [Qt thread-safety requirements](https://doc.qt.io/qt-6/qabstractitemmodel.html#thread-safety) support this boundary.

4. **Replace snapshot history with operation deltas.** `ui/dataframe_model.py::_snapshot()` copies the complete sheet before a one-cell edit, and `_restore_snapshot()` copies it again. Store cell/range changes with old/new values and dtypes; for formulas or fills retain only affected columns/slices and associated metadata. Structural edits need removed row/column payloads and index/shape information. Group an entire paste/analysis commit as one command; cap aggregate retained history bytes and consider disk-backed payloads for large structural commands. Preserve atomic failure and exact undo/redo values, metadata, formulas, and dtypes. Do not treat the existing no-undo path above 256 MiB as the completed large-sheet solution.

5. **Bound display work and reuse map intermediates.** Million-point line construction still validates and sends the entire dataset to Matplotlib. Add viewport-aware min/max envelope or an equivalent feature-preserving display reduction, use fewer markers, and cache by data revision, columns, range, scales, and display resolution. Preserve the full source arrays for scientific calculations, cut exports, and a deliberate full-resolution export option; simple every-N sampling can erase narrow peaks. Cache spatial grids/triangulations and extracted spectral slices instead of reconstructing them for each cut/style change. The measured Raman result viewer is reasonably quick at 1,000 pixels: prioritize full spectral-map preparation and future large cases over rewriting its already fast lookup. Its code still recreates hidden diagnostics and scans curve tables repeatedly; lazily draw diagnostics and pre-index spectrum groups when measurements justify it.

6. **Implement a separate disk-backed path for genuinely large data.** The `Dataset.backend` label is persisted, but `Workspace.add_dataset()` still requires a Pandas DataFrame; the label alone provides no out-of-core support. Keep normal editable Pandas sheets and introduce a backend interface for schema, row count, paged reads, selection/query, summaries, and explicit bounded materialization. Use DuckDB over Parquet/Arrow for large read-only/limited-edit datasets, with asynchronous page caching, selected-column/filter pushdown, bounded query memory, a spill directory, and limited worker count. SciPy fitting should materialize the requested columns/region or one spectrum batch, rather than the full dataset. Pandas itself recommends loading less data and chunking for suitable operations; DuckDB documents both disk spilling and Parquet projection/filter pushdown. [Pandas scaling](https://pandas.pydata.org/docs/user_guide/scale.html), [DuckDB workload tuning](https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads), [DuckDB file formats](https://duckdb.org/docs/current/guides/performance/file_formats).

7. **Store spectral cubes without repeating their axes internally.** The current Horiba normalizer repeats X, Y, and spectral coordinates for every intensity value. A regular P-pixel x S-sample cube uses roughly `32 * P * S` bytes for four float64 columns versus roughly `8 * P * S + 16 * P + 8 * S` bytes for intensity plus separate axes, before masks, indexes, and result columns. Preserve the existing long-form worksheet/export contract, but consider a chunked cube representation behind the backend boundary and row-offset/pixel indexes for analysis. Full Raman jobs currently build all grouped job frames and accumulate many curve/result frames before concatenation; stream bounded batches and result blocks rather than retaining every intermediate. This is a code-based scaling finding, not a benchmark of complete peak fitting.

Project save/load now stream correctly and are not the leading bottleneck in this run. Integrity checking intentionally adds member reads: preserve package seals, signatures, authentication, atomic replacement, and backward compatibility. Hashing while streaming writes is a possible later improvement. Versioned optional Parquet payloads could preserve dtypes and accelerate large typed project reads, while the default open CSV format remains supported.

### Large-data display requirement (2026-10-21)

The user clarified that backend adoption must ship together with dynamic row loading. Evaluate Polars lazy/streaming against the DuckDB/Parquet proposal above before choosing an engine. The current Qt table paints only requested cells but its source is still a complete Pandas DataFrame; UI painting virtualization alone does not reduce source storage.

For disk-backed mode, retain at most 1,000 data rows in a replaceable display cache, with an additional byte limit and column projection for wide tables. Fetch windows in the background, coalesce navigation requests, discard stale results, preserve global row identities, and evict visited pages rather than accumulating them. Budget in-flight results and engine/import buffers separately: 1,000 cached display rows is not a claim that the whole process uses only 1,000 rows of memory. Avoid full-source materialization during import, project loading, resizing, and undo. Filters, sorts, summaries, and scientific analysis must target the backend dataset or an explicit selection, not implicitly the displayed page. Start read-only and materialize only bounded selections for existing Pandas/SciPy operations.

Acceptance checks must include repeated scrolling and far-row jumps with bounded retained memory, final/empty page correctness, stable global labels, source/filter switch races, responsive navigation, and backend-wide operation semantics. This section records requirements; the paged backend is not implemented yet. See Stage 11 in `Roadmap.md`.

### Suggested delivery order and acceptance gates

Start with locale conversion and dtype-aware validation, then add background jobs and delta history before a larger backend migration. Display reduction and map caches can follow once revision tracking exists. DuckDB/Parquet and a spectral-cube backend address capacity limits that the earlier steps cannot solve.

Proposed targets for the same reference machine (targets, not achieved results):

- The 18.61 MiB ordinary numeric CSV should import below 1 s, with lossless mixed/locale fallback covered separately.
- Simple million-row `sin(col1)` evaluation and X/Y preparation should each be below 100 ms, excluding deliberate full-data canvas painting.
- A one-cell undo command should retain storage proportional to the changed cell/dtype metadata, not the sheet, including on the 305 MiB worksheet.
- Under a long job, a 10 ms GUI heartbeat should have a 95th-percentile gap below 50 ms and no routine blocking commit above 100 ms. Cancel acknowledgement should arrive within 250 ms between bounded work units; uninterruptible algorithm phases must be identified honestly.
- Interactive million-point line redraw should target below 100 ms after preprocessing, with automated peak/extrema preservation checks for display reduction.
- A future 10 GB source should be queryable/previewable without full Pandas materialization; its test must verify process memory and cancellation, not merely successful parsing.

Before accepting optimizations, run the existing numeric type-safety/import/persistence regressions, add late-invalid-token and locale-chunk-boundary cases, verify revision invalidation and cancellation atomicity, and repeat the diagnostic suite. Extend benchmarks with long strings, wide sheets, missing values, real vendor maps, cold-cache reads, desktop scrolling, and constrained-RAM runs. Resolve the declared-versus-installed dependency mismatch so future comparisons are meaningful.

## Historical Audit (2026-08-17)

## Outcome

The principal clipboard slowdown is not Qt's virtual table model or the tab-delimited parser by itself. `DataFrameTableModel.paste_block()` grows a DataFrame one row at a time and then normalizes and assigns every cell through Python/Pandas scalar operations. The general dataset-load delay is dominated by redundant `resizeColumnsToContents()` passes: one dataset-list refresh can load the editor twice, and each editor load currently triggers column sizing both indirectly through `history_changed` and explicitly.

Large file and project reads also run synchronously on the GUI thread. Current `.jasc` loading creates avoidable byte, decoded string, `StringIO`, parsed DataFrame, and workspace-copy representations, increasing peak memory even when raw parsing is acceptably fast.

## Implementation Status

The immediate amplification fixes were implemented on 2026-08-17:

- Dataset-list refresh now attaches the editor once and performs one column-sizing pass.
- Column sizing uses at most 100 sampled rows for normal sheets and 25 for sheets above the existing large-table threshold.
- History notifications update action/summary state without rescanning the worksheet after every edit.
- Clipboard text uses a fast typed pandas parser with a robust ragged CSV fallback and destination text-column preservation.
- Value paste grows the DataFrame once, normalizes one destination column at a time, and assigns column slices instead of individual cells.
- Whole-column paste and Fill Range also use bulk row growth and assignment.
- Clipboard availability checks inspect MIME capabilities without parsing clipboard contents.
- Undo history is capped at 20 snapshots and 256 MiB per undo/redo stack. A sheet that cannot fit one snapshot is edited without creating the copy and shows a visible warning that the edit is not undoable.
- Fresh file imports and project loads transfer DataFrame ownership into the workspace instead of immediately copying parsed buffers.
- `.jasc` CSV members now stream through the ZIP archive instead of materializing decoded CSV strings and `StringIO` copies. The project format remains backward compatible.

Post-change measurements on the same environment:

| Path | Before | After |
| --- | --- | --- |
| 10,000 x 10 value paste into the default sheet | Approximately 8 s extrapolated from the measured 5,000-row path | 0.034 s model paste plus 0.007 s parsing |
| 100,000 x 10 end-to-end GUI clipboard paste | Not practical with the scalar path | 0.35 s without allocation tracing |
| 1,000 x 10 dataset/editor refresh | 2.9-3.6 s; two editor attachments and four sizing passes | 0.057 s; one attachment and one sampled sizing pass |
| 10,000 x 30 dataset/editor refresh | Multiple full sizing passes | 0.047 s with a 25-row sample |
| 300,000 x 10 `.jasc` load traced peak | 121.5 MiB | 25.3 MiB |

Background import/progress and true out-of-core datasets remain architectural follow-ups for sources large enough that parsing itself exceeds an acceptable GUI pause. They are no longer required to compensate for the avoidable editor, paste, and project-memory amplification described above.

## Measured Evidence

Measurements used the repository's `dataProcessing` environment on Windows with Qt's offscreen platform. Timings are diagnostic rather than portable performance guarantees. `tracemalloc` reports Python-tracked allocations and does not include every native Qt/NumPy allocation.

| Path | Test | Observed result |
| --- | --- | --- |
| Clipboard parsing | 100,000 rows x 10 numeric columns | Existing `csv.reader` list-of-lists: 0.437 s and 84.6 MiB traced peak; direct inferred `pandas.read_csv`: 0.084 s and 30.9 MiB traced peak |
| Value paste | 5,000 rows x 10 columns into a 25-row sheet | 4.124 s |
| Value paste without row growth | Same block into a preallocated 5,000-row sheet | 1.559 s, showing that scalar cell conversion/assignment remains expensive after removing growth cost |
| Paste profile | 2,000 rows x 10 columns | 7.96 million profiled calls, including 1,975 individual row appends, 40,000 DataFrame column lookups, and 20,000 scalar assignments |
| Dataset/editor refresh | 1,000 rows x 10 columns | 3.631 s under profiling; `_show_dataset_editor()` ran twice, `_resize_dataset_columns_to_contents()` ran four times, and the model handled 320,000 `data()` calls |
| One Qt width pass | 10,000 rows x 30 columns | 2.133 s with the default resize-content precision of 1,000 rows |
| Project load | One 300,000 x 10 numeric dataset; 19.3 MiB CSV payload | Direct CSV read: 0.177 s and 25.2 MiB traced peak; current `.jasc` load: 0.243 s and 121.5 MiB traced peak |
| Workspace adoption | 1,000,000 rows x 10 numeric columns | `Workspace.add_dataset()` copy took 0.012 s in isolation, but creates another set of approximately 76 MiB numeric column buffers |

## Root Causes

### 1. Quadratic-style row growth and scalar paste

`ui/dataframe_model.py::DataFrameTableModel.paste_block()`:

- Calls `frame.loc[len(frame)] = ...` repeatedly until every missing row exists. Each append can rebuild pandas internals.
- Visits every pasted cell in nested Python loops.
- Fetches the same DataFrame column repeatedly for normalization and dtype checks.
- Uses `.iat` for one scalar write per cell.
- Resets the complete model after the operation.

The first defect makes pasting into the default 25-row blank sheet especially expensive. Preallocating rows removes only part of the delay because per-cell Pandas access remains substantial.

### 2. Redundant full column sizing

`ui/main_window.py::_refresh_dataset_list()` selects the new list item, which emits `currentTextChanged` and invokes `_show_dataset_editor()`, then invokes `_show_dataset_editor()` explicitly again.

Each `_show_dataset_editor()` calls `DataFrameTableModel.set_dataset()`. That emits `history_changed`, whose main-window handler resizes columns. `_show_dataset_editor()` then explicitly resizes them again. Consequently, one import/refresh can perform four full sizing passes.

The same broad `history_changed` handler resizes columns and refreshes plot controls after ordinary value edits and bulk model operations. Clipboard handlers then repeat resize, plot-control refresh, and summary refresh explicitly. A history-state notification is therefore doing content/layout work that should be independently signaled and scheduled.

The current 250,000-cell guard prevents this on larger tables, producing a counterintuitive performance cliff: a table just below the guard may attach more slowly than a larger table just above it.

### 3. Clipboard materialization and eager context-menu parsing

`QClipboard.text()` materializes the complete clipboard as a Python string. `_parse_clipboard_text()` strips it, wraps it in `StringIO`, and builds a Python list plus one Python string per cell before the DataFrame update begins.

Opening the Data Editor context menu parses plain clipboard text once to enable `Paste Values` and again through `_clipboard_has_dataset_columns()` to enable `Paste Column(s)`. Clipboard contents should only be parsed after the user chooses a paste operation.

### 4. Whole-DataFrame undo snapshots

Every edit calls `_snapshot()`, which deep-copies the entire visible DataFrame, formulas, and column metadata. History is not bounded by entry count or memory. A single paste into an existing large sheet duplicates its current buffers; repeated cell edits can retain many full copies. This is primarily a peak/resident-memory problem, but memory pressure can become a major latency problem through allocator and paging costs.

### 5. Synchronous and copy-amplified ingestion

CSV/TXT import, clipboard transformation, and `.jasc` project loading all run on the GUI thread without a progress/cancel worker. The 100 MiB file warning does not make accepted work responsive, and files below that threshold can still visibly freeze the application.

Project loading currently uses `archive.read(...).decode(...)`, then `StringIO`, then `pd.read_csv`, followed by the normal workspace DataFrame copy. Project saving similarly builds each complete CSV in a `StringIO` before passing it to the ZIP writer. These stages increase peak memory and delay garbage collection.

## Recommended Implementation Sequence

### Slice 1: remove redundant UI work (implemented)

1. Make `_refresh_dataset_list()` use exactly one editor-load path: either keep the selection signal or make one explicit call while signals are blocked.
2. Separate undo/redo availability notification from dataset-content and dataset-structure notifications. `set_dataset()` should not masquerade as an edit.
3. Stop automatic full-table sizing from the generic history handler. Size once on initial attachment and only size affected/new columns after structural operations.
4. Replace automatic full-table sizing with bounded sampling of headers plus visible/limited rows. Keep a user-invoked `Fit Columns to Contents` action for an intentional deeper scan.
5. Remove duplicate post-operation refreshes in paste and other editor handlers.

This is the lowest-risk slice and should improve normal imports, dataset switching, pastes, and single-cell edits immediately.

### Slice 2: make clipboard paste block-oriented (implemented)

1. Parse clipboard input into one rectangular typed block rather than a list consumed through scalar Pandas calls.
2. Grow rows once with `reindex`/one `concat`, and add missing columns in one structural operation.
3. Normalize by target column and assign whole column slices or the complete rectangular block in bulk.
4. Cache touched column names and clear formula/metadata state once per touched column.
5. Emit row/column insertion and `dataChanged` signals where practical; use one reset only when the shape/dtypes make incremental notification unsafe.
6. For context-menu enablement, inspect MIME availability/non-empty text only. Parse lazily after an action is selected.
7. For context-menu selection enablement, use `hasSelection()` and compact `QItemSelectionRange` bounds. Do not call `selectedIndexes()` or expand selected rows/columns merely to decide whether an action is enabled. This follow-up is implemented; it removes the multi-million-`QModelIndex` pause caused by opening a menu over a large/full-table selection.

Clipboard parsing must preserve quoted tabs/newlines, blanks, text columns, leading-zero identifiers where appropriate, numeric/scientific values, and ragged rows. A pandas parser is substantially faster for homogeneous numeric blocks, but type-preservation tests should decide whether it can replace or augment the CSV parser.

### Slice 3: bounded undo (implemented first pass)

1. Represent a cell edit as row/column plus old/new value and any dtype transition.
2. Represent a paste as the overwritten rectangular block, original shape, added columns/rows, and touched formula/metadata entries.
3. Keep structural-operation commands or snapshots only where deltas would be unsafe.
4. Enforce both entry-count and memory budgets, with a visible warning when an operation is too large to retain in undo history.

### Slice 4: responsive import and project I/O (streaming/copy reduction implemented)

1. Run delimited parsing and project dataset parsing in a worker, with GUI-thread-only model/workspace attachment.
2. Add progress, cancellation, and a busy state. Copy clipboard text on the GUI thread, then parse/transform the copied string in the worker.
3. Stream ZIP dataset members through `ZipFile.open()` plus a text wrapper instead of `read` + `decode` + `StringIO`.
4. Add an internal ownership-transfer/adopt path so newly parsed DataFrames do not need an immediate defensive workspace copy. Retain copying as the safe public default.
5. Add import preview, row limits, selected columns, and sampling before the later DuckDB/PyArrow backend work.

### Slice 5: project format and true large-data mode

Keep backward-compatible CSV project reads, but consider a future versioned Parquet payload for faster typed persistence and lower memory amplification. Follow the existing roadmap: Pandas remains the editable small/medium backend; DuckDB plus PyArrow/Parquet provides paged preview/query/materialize workflows for genuinely large sources.

## Verification and Performance Budgets

Add functional tests before tuning absolute timings:

- One dataset-list refresh invokes one editor attachment and at most one bounded sizing pass.
- `set_dataset()` and history-state changes do not trigger duplicate layout work.
- Paste growth is one bulk row-growth operation, not one append per row.
- A bulk paste records one undo command and undo restores values, shape, formulas, metadata, and dtypes.
- Context-menu construction does not parse clipboard contents or enumerate every selected cell.
- Clipboard tests cover numeric, mixed text/numeric, empty fields, ragged rows, quotes, embedded tabs/newlines, Unicode, scientific notation, and leading zeros.
- Project v1/v2 CSV archives remain loadable after adding streaming or a newer payload format.

Add an opt-in benchmark suite with representative 10,000 x 10 and 100,000 x 10 blocks. Initial local targets should be:

- 100,000 x 10 numeric clipboard parsing below 0.5 s and below 3x the final numeric DataFrame memory in Python-tracked peak allocations.
- 10,000 x 10 paste, including growth, below 1 s on the reference development machine.
- No uninterrupted GUI-thread operation longer than roughly 250 ms for worker-eligible imports; longer work exposes progress and cancellation.
- Undo memory remains within a configured budget instead of growing by one full DataFrame per edit.

## Non-Causes and Secondary Costs

- `QAbstractTableModel` is already virtual: attaching it does not create a widget per row. Its normal viewport access is not the main problem; redundant width scans amplify otherwise reasonable `data()` calls.
- `profile_dataframe()` uses `memory_usage(deep=False)` and is inexpensive relative to paste and sizing.
- `Workspace.add_dataset()` copying was fast for the numeric benchmark. It remains worth eliminating on ownership-transfer paths because of memory amplification, not because it is the first latency bottleneck.
- Plot-control refresh and metadata pruning scale mainly with column count. They should still be de-duplicated, but the measured dominant general-load cost is repeated column sizing.
