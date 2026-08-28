# Large Data Loading and Clipboard Performance Audit

Date: 2026-08-17

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
