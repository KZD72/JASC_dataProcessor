# JASC Data Processor - Comprehensive User Manual

*Version 0.1.0 - reviewed against the application source on 22 September 2026*

JASC Data Processor is a desktop application for scientific worksheet editing, data preparation, mathematical transforms, signal processing, interpolation, statistics, curve fitting, figure digitization, and Matplotlib-based visualization. This manual describes the features implemented in the current repository. Features listed as limitations are not yet available.

---

## Table of Contents

1. [Installation and First Launch](#1-installation-and-first-launch)
2. [Application Window, Menus, and Shortcuts](#2-application-window-menus-and-shortcuts)
3. [Projects, Datasets, and the Workspace](#3-projects-datasets-and-the-workspace)
4. [Importing and Creating Data](#4-importing-and-creating-data)
5. [Digitizing Data from Figure Images](#5-digitizing-data-from-figure-images)
6. [Editing Worksheets and Column Metadata](#6-editing-worksheets-and-column-metadata)
7. [Data Preparation](#7-data-preparation)
8. [Formulas and Expressions](#8-formulas-and-expressions)
9. [Calculus, Smoothing, FFT, and Interpolation](#9-calculus-smoothing-fft-and-interpolation)
10. [Statistics Workbench](#10-statistics-workbench)
11. [Curve Fitting and Custom Models](#11-curve-fitting-and-custom-models)
12. [Plotting and the Plot Inspector](#12-plotting-and-the-plot-inspector)
13. [Batch Processing](#13-batch-processing)
14. [Export, Persistence, and Large Data](#14-export-persistence-and-large-data)
15. [Troubleshooting and Current Limitations](#15-troubleshooting-and-current-limitations)
16. [Quick Reference](#16-quick-reference)

---

## 1. Installation and First Launch

### System requirements

- Python 3.10 or later.
- A desktop environment capable of displaying a Qt application.
- The packages in `requirements.txt`, including PySide6, pandas, Polars, NumPy, Matplotlib, and SciPy.

### Install dependencies

Open a terminal in the repository root and run:

```bash
python -m pip install -r requirements.txt
```

Using a virtual environment is recommended so that JASC's package versions remain isolated from other Python projects.

### Start JASC

Run the application from the repository root:

```bash
python main.py
```

`main.py` is the supported entry point. Do not run `ui/main_window.py` directly. In the supplied VS Code workspace, the **Run JASC Data Processor** launch configuration starts the correct entry point.

At first launch, JASC opens an empty workspace. Create a sheet, import data, or open a `.jasc` project to begin.

### File types at a glance

| Purpose | Supported format |
| --- | --- |
| Tabular import | `.csv`, `.txt`, `.xlsx`, `.xlsm` (Excel worksheet values only) |
| Tabular export | `.csv`, `.txt` / tab-delimited text |
| Project save/open | `.jasc` |
| Figure digitizer | PNG, JPEG, BMP, TIFF, GIF, and other image formats readable by Qt |
| Plot image export | Formats offered by the embedded Matplotlib toolbar |

---

## 2. Application Window, Menus, and Shortcuts

### Main layout

```text
+----------------------------------------------------------------------------+
| File | Edit | View | Data | Analysis | Plot                               |
+----------------------------------------------------------------------------+
| Main toolbar: project controls, new sheet, import, digitizer, export       |
+-------------------+-----------------------------------+--------------------+
| Workspace         | Central work area                 | Plot Inspector     |
|                   |                                   |                    |
| Datasets          | Data tab: worksheet editor        | Series             |
| Saved Plots       | Plot tab: Matplotlib canvas       | Axes               |
|                   | and navigation toolbar            | Legend             |
|                   |                                   | Locator            |
+-------------------+-----------------------------------+--------------------+
| Status bar: active operation, warnings, progress, and result messages      |
+----------------------------------------------------------------------------+
```

- **Workspace Navigator**: The left dock contains the dataset and saved-plot lists. Select a dataset to display it in the Data tab. Select a saved plot to load it, subject to the unsaved-plot prompt.
- **Data tab**: Shows the selected worksheet and a summary containing its dimensions, memory estimate, metadata/formula counts, and backend.
- **Plot tab**: Shows the current plot canvas, the standard Matplotlib navigation toolbar, and plot-management buttons.
- **Plot Inspector**: The right dock is synchronized with the Plot tab and contains Series, Axes, Legend, and Locator controls. It is hidden while the Data tab is active.
- **Status bar**: Reports completed operations, selected outputs, large-data warnings, and batch progress summaries.

JASC automatically follows the operating-system light or dark palette and reapplies theme-aware table, input, dock, and dialog styling when the Qt palette changes.

Window dimensions are calculated in Qt logical pixels from the active monitor's available work area, so operating-system scaling and taskbar space are respected. Resizing or moving the window between monitors triggers a debounced dock rebalance. Inspector forms wrap long rows and keep their editors usable; Plot actions that do not fit move into the toolbar overflow menu. In a very narrow Plot layout, JASC temporarily collapses the Workspace Navigator to protect the plot canvas. Selecting **View > Show Workspace Navigator** explicitly restores it even at that width.

### View controls

The **View** menu can independently show or hide:

- **Workspace Navigator**: the complete left dock.
- **Workspace Datasheets**: the dataset section within the navigator.
- **Saved Plots**: the saved-plot section within the navigator.
- **Plot Inspector**: the right plot-control dock.

Use **View > Reset View to Default** to restore the normal dock arrangement and visibility.

### Mouse and context actions

JASC follows the desktop convention used by spreadsheet and scientific-analysis software:

- **Left-click** selects a worksheet, saved plot, cell, queued series, or locator. Double-click a worksheet cell to edit it, a saved plot to load it, or a rendered plot element to open its focused editor.
- **Right-click** opens the actions relevant to the item under the pointer. Worksheet menus are available from cells, empty table space, row headers, and column headers. Right-clicking an unselected worksheet cell, row, column, dataset, series, locator, or saved plot makes that item the context target first.

The dataset navigator menu includes **Open Sheet**, **Create Plot from Dataset**, export, Data Preparation and Analysis submenus, duplication, rename, and removal. **Create Plot from Dataset** starts a protected empty draft and prefills its dataset/column mappings; choose the subtype and click **Add Series** to render it. Worksheet menus include value, row, and column copying; normal and transposed paste; cell clearing; worksheet resizing; Row and Column submenus; plotting; Data Preparation; and Analysis. Saved-plot, queued-series, and locator lists expose their corresponding create/save/load/update/revert/duplicate/remove actions. Disabled actions remain visible when the current selection or state does not support them.

### Menu reference

| Menu | Commands |
| --- | --- |
| File | Open Project, Save Project, four explicit Save As security modes, Signing Identities, New Blank Sheet, Close Project, Import Data, Import From Figure, Export Dataset, Exit |
| Edit | Undo, Redo, Clear Selected Cell Values, Delete Selected Rows, Delete Selected Columns, Paste Values Transposed |
| View | Navigator/section/inspector visibility and Reset View to Default |
| Data | Duplicate/Rename/Remove Dataset; Add/Insert Row or Column; Resize Sheet; Fill Range; Smart Fill Selection; all Data Preparation tools; Column Metadata; Apply Formula |
| Analysis | Derivative, Integral, Smoothing, Interpolation, FFT, Inverse FFT, Statistics, Baseline Correction, Peak Analysis, Raman Analysis, Custom Fit Models, Curve Fit |
| Plot | New Empty Plot, Save Current Plot, Copy Current Plot to Clipboard, Load/Duplicate/Remove Selected Plot |

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+O` | Open project |
| `Ctrl+S` | Save project |
| `Ctrl+Shift+S` | Save project as |
| `Ctrl+W` | Close project |
| `Ctrl+N` | New blank sheet |
| `Ctrl+I` | Import data |
| `Ctrl+E` | Export selected dataset |
| `Ctrl+Z` | Undo worksheet edit |
| `Ctrl+Y` | Redo worksheet edit |
| `Delete` | Clear values in selected worksheet cells; rows and columns remain |
| `Shift+Delete` | Delete selected rows after confirmation |
| `Ctrl+Delete` | Delete selected columns after confirmation |
| `Ctrl+C` | Copy selected worksheet values |
| `Ctrl+V` | Paste worksheet values at the active cell |
| `Ctrl+Shift+V` | Paste the clipboard matrix transposed at the active cell |
| `Ctrl+Shift+F` | Apply Formula |
| `Ctrl+Shift+C` | Curve Fit |
| `Ctrl+Shift+R` | Reset view layout |
| `Ctrl+Alt+N` | New empty plot |
| `Ctrl+Alt+S` | Save current plot |
| `Ctrl+Alt+C` | Copy the current live plot visualization to the clipboard |

---

## 3. Projects, Datasets, and the Workspace

### Workspace concepts

- A **dataset** is a named pandas worksheet with a table, formulas, column metadata, source path, and backend label.
- A **saved plot** is a named snapshot of plot series, axes, legend, locator, style, and figure settings.
- A **custom fit model** is an expression-based fitting function stored with the project.
- The **workspace** is the collection of all three.

Names are made unique automatically. If `Sheet` already exists, another dataset requested with that name becomes `Sheet (2)`, then `Sheet (3)`, and so on. Saved plots and custom models use equivalent unique-name behavior.

### Open, save, and close a project

1. Choose **File > Open Project...** to load an open `.jasc` or encrypted `.jascx` file. Encrypted projects prompt for their password. Opening a project replaces the current workspace after confirmation.
2. Choose **File > Save Project** to save to the current project path. The first save opens the Save As dialog.
3. Choose **File > Save Open Project As...** for a normal `.jasc`, or **File > Save Encrypted Project As...** for password-protected `.jascx`. Encrypted saves ask for **Encryption password** and **Confirm encryption password**; the password is retained only for the current open application session so later saves do not repeatedly prompt.
4. Choose **File > Save Signed Open Project As...** for signed `.jasc`, or **File > Save Signed + Encrypted Project As...** for signed `.jascx`. These are separate menu actions rather than hidden file-type choices.
5. Choose **File > Close Project** to clear the workspace without closing JASC. This action warns that unsaved changes will be lost.

Save before using **File > Exit** or closing the application window. Project-level automatic save and recovery are not implemented.

### What a `.jasc` project preserves

A project is a ZIP archive containing CSV worksheet payloads and JSON metadata. It preserves:

- Dataset names, values, source paths, and backend labels.
- Worksheet-level source/import metadata, parsed instrument fields, and exact raw text preambles.
- Column formulas.
- Column roles, value types, precision, units, long names, and comments.
- Operation-provenance comments written by JASC.
- Resumable figure-extraction sessions attached to digitized datasets, including an embedded working image and X/Y calibration; colour-plot sessions also retain their empirical colour-bar calibration.
- Saved plot definitions, including plot series and appearance settings.
- Project-scoped custom fit models.
- Named spectral-analysis sessions with readable metric, fitted-curve, parameter,
  and detected-peak tables plus their configuration and provenance.

Every newly saved version 8 project contains an `integrity.json` **JASC Package Seal** introduced in version 6. Its canonical manifest records every other member's exact filename, original byte size, and SHA-256 digest together with a UTC creation timestamp, random package UUID, and 256-bit random nonce. JASC sorts and deterministically serializes that manifest, combines it with the `JASC-SEAL-v1` domain marker, and hashes it again to create the package seal. Each save receives a new identity and seal even when the scientific content is unchanged. Spectral-analysis internals are normal UTF-8 CSV members under `analyses/`, with JSON metadata in `project.json`, so derived results remain inspectable without JASC.

JASC verifies the seal, names, sizes, and member hashes before loading. Missing, added, renamed, duplicated, resized, or changed members, including a manifest edited without correctly recreating the complete seal, trigger a **Project Integrity Warning** stating that the package may have been forged or damaged. The safe default is Cancel, with an explicit **Open Anyway** choice for a trusted source. Version 5 hash manifests and version 4 or older projects without a manifest remain loadable for backward compatibility.

The Package Seal is designed as a practical normal-security forgery and corruption check. It makes casual CSV replacement or editing only one member hash insufficient, but it is not a digital signature or independent proof of authorship: a knowledgeable attacker who fully reproduces the documented algorithm can generate a different internally consistent package. Use encrypted `.jascx` when the package or threat model is sensitive.

### Open and encrypted project packages

The normal `.jasc` format remains the recommended open-science form. It is an ordinary ZIP archive, so its CSV values and JSON metadata can be recovered without JASC. It provides transparency and portability, not secrecy or proof of authorship.

The optional `.jascx` form encrypts the complete `.jasc` package with AES-256-GCM. Its key is derived from the user password with Scrypt and a random salt; each save also uses a fresh random nonce. Authentication means that a wrong password or any ciphertext/header change is rejected before project data is loaded. Saves replace the destination atomically only after the new package has been completed. JASC never writes the password into the project.

Encryption has deliberate trade-offs:

- A `.jascx` package requires JASC (or a separately implemented compatible decryptor) and its password before the open ZIP/CSV contents can be recovered.
- There is no password-recovery mechanism. Losing the password means losing access, so retain it in an appropriate password manager.
- Anyone who knows the password can decrypt, edit, and encrypt a new package. Authenticated encryption therefore protects against outsiders and accidental/unauthorized byte changes, but it does not prove which authorized person created the package.
- For publication and long-term preservation, save a separate open `.jasc` copy when confidentiality restrictions permit it.

### Digital signatures and signing identities

JASC can optionally sign the Package Seal with Ed25519. The private key creates the signature and must remain secret; the public key verifies it and can be distributed freely. Because the signature covers the Package Seal, an attacker who edits data and completely regenerates the normal manifest still cannot create the original author's signature without the private key.

1. Choose **File > Create Signing Identity...**, select a `.jasc-key` location, enter the researcher or organization name, and protect the private key with a strong password.
2. JASC writes a password-encrypted `.jasc-key` private identity and a matching `.jasc-pub` public identity. Back up the private key securely. Share only the public file.
3. Choose **File > Save Signed Open Project As...** or **File > Save Signed + Encrypted Project As...**, then unlock the private key when the clearly labelled **Private-key password** prompt appears.
4. Recipients obtain the `.jasc-pub` file through an independent trusted channel, compare its SHA-256 fingerprint, and choose **File > Trust Public Signing Key...**.

When a project opens, JASC reports one of four states:

- **Signed and trusted**: the Ed25519 signature is valid and its fingerprint is in the local trusted-signer list.
- **Signature valid, signer unknown**: the mathematics is valid, but the public-key fingerprint has not been independently trusted.
- **Unsigned**: the package has normal Package Seal protection but no author signature.
- **Invalid signature**: the signature is missing where required, malformed, uses a different fingerprint, or no longer matches the Package Seal. JASC treats this as an integrity failure and defaults to cancelling the open operation.

The signature record embeds the public key for portable mathematical verification, while the signed `project.json` declaration binds the claimed signer name and fingerprint to the sealed package. The embedded key alone does not establish identity; trust comes from comparing or importing the matching `.jasc-pub` fingerprint through an independent source. Signed encrypted projects are signed internally before AES-256-GCM encryption, so password authentication and author verification both apply after decryption.

Because worksheet payloads are CSV, specialized pandas dtypes are reconstructed on load rather than serialized as native binary dataframe types.

### Dataset navigation and management

- Select a dataset in the navigator to display it.
- Click **Duplicate Sheet**, right-click a dataset and choose **Duplicate Sheet**, or use **Data > Duplicate Dataset** to create and open a fully independent copy. Values, column order and dtypes, formulas, metadata, source provenance, and backend label are retained. Copies are named `Sheet Copy`, `Sheet Copy (2)`, and so on; later edits do not affect the source.
- Right-click a dataset for its common Open, Plot, Export, Data Preparation, Analysis, Duplicate, Rename, and Remove operations.
- The same management actions are available from the **Data** menu.
- Renaming a dataset updates references inside saved plots. The active plot draft is cleared so it cannot retain stale controls.
- Deleting a dataset asks for confirmation. Dataset deletion is not part of worksheet Undo/Redo.

---

## 4. Importing and Creating Data

### Import CSV, DAT, or TXT data

Text-file inspection and reading run in the background. The status bar shows the current file and phase, byte progress while reading ordinary tables, and a **Cancel** button. Existing worksheets and plots remain available while files are being prepared. Cancellation discards the pending batch without adding partial worksheets; it may wait for the current parsing or conversion work unit to finish. Successfully prepared files are added together after any size warnings are resolved. If an individual file fails, the completed import identifies it in a warning and can still add the other successful files. Switching projects discards stale import results, and closing JASC waits for the worker to stop safely.

1. Choose **File > Import Data...** (`Ctrl+I`) or use the toolbar action.
2. Select one or several `.csv`, `.dat`, or `.txt` files. Every successfully imported file becomes an independent dataset named from its filename.
3. Review the preflight table. For each file it shows the detected text encoding, delimiter, number of leading metadata rows, header status, column count/names, and the first data values.
4. Choose a **Data type**. **Auto (infer from file)** is the default; explicit choices are **General table**, **Single spectrum**, and **Spectroscopy map**.
5. Choose a **Spectrometer** profile. **Auto / generic** is the default. **Horiba LabSpec** supports single spectra and wide spectroscopy maps; **B&W Tek** currently supports single spectra only. JASC stops an unsupported B&W Tek map selection instead of guessing another vendor format.
6. Leave **Text encoding** on **Auto (detect safely)** or explicitly choose UTF-8, UTF-8 with BOM, UTF-16, Windows-1252/ANSI, or Latin-1. Auto recognizes byte-order marks first, then attempts strict UTF-8, Windows-1252, and Latin-1 without silently inserting replacement characters.
7. Choose a **Number format**:
   - **Auto (infer safely)** recognizes unambiguous decimal-point, decimal-comma, scientific-notation, and grouped values by column.
   - **Decimal point: 1,234.56** treats `.` as decimal and `,` as thousands grouping.
   - **Decimal comma: 1.234,56** treats `,` as decimal and `.` as thousands grouping.
8. Leave **Delimiter** on **Auto (infer from file)** or choose an explicit delimiter:
   - Auto (comma, semicolon, tab, pipe, or whitespace)
   - Comma
   - Semicolon
   - Tab
   - Pipe
   - Space / whitespace (one or more whitespace characters)
9. Choose **Headers**:
   - **Auto (detect for each file)** is the default.
   - **First tabular row contains column names** forces a header after any discarded metadata rows.
   - **No header row** keeps the first tabular row as data and creates `Column 1`, `Column 2`, and so on.
10. Choose **Leading metadata**:
   - **Auto (detect and preserve leading metadata)** is the default and is resolved independently for each file. These rows are excluded from the numeric table but retained with the worksheet.
   - **Keep all leading rows as worksheet data** begins table parsing at the start of every file.
   - **Use a fixed number of leading metadata rows** applies one explicit boundary to every selected file and retains those rows as metadata.
11. Confirm the import.

Auto examines a bounded sample before pandas reads the complete file. A file with no separator evidence imports as one column. Header, metadata, and number-format detection use structural/value-pattern heuristics, so the preflight is intentionally visible and every inference can be overridden. Values such as `12,50` and `1.234,56`, or `12.50` and `1,234.56`, provide clear evidence. A value such as `1.234` alone is inherently ambiguous: it may mean one point two three four or one thousand two hundred thirty-four. Auto therefore retains the backward-compatible point-decimal interpretation; select the explicit comma-decimal mode when the dot is grouping. Leading records beginning with `#`, `$`, or `%`, plus common key/value forms, are parsed when possible and always retained verbatim. Use the **Worksheet Metadata** button above the Data table or **Data > Worksheet Metadata...** to review source/import details, selected number format, parsed fields, and the raw preamble.

Spectrometer-oriented text support includes tab-separated decimal-comma numeric conversion used by Horiba exports, full semicolon-table import for B&W Tek single-spectrum files, and reconstruction of legacy Bruker IR text where a `#c` record stores the X coordinate array followed by scalar intensity values. The requested data type and spectrometer profile are retained in Worksheet Metadata.

JASC also recognizes the wide Horiba LabSpec hyperspectral-map source layout. Its first data row has two blank cells or X/Y coordinate labels followed by numeric Raman shifts; each later row is one complete spatial-pixel spectrum. During import, JASC normalizes that matrix into four numeric worksheet columns: `X`, `Y`, `Raman Shift`, and `Intensity`. Each spatial pixel therefore contributes one worksheet row per Raman shift. Pixel order and Raman-shift order, including descending axes, are preserved. Worksheet Metadata records the wide source layout, normalized worksheet layout, spatial-pixel count, shifts per pixel, unit, and axis range. Map profiles for other manufacturers remain deferred until representative formats are supplied.

Unknown records remain in the raw metadata rather than being discarded. The resolved encoding is recorded in Worksheet Metadata. If an unusual instrument encoding is not identified correctly, choose an explicit encoding and review the preflight before importing. Additional stacked/long-form/multi-acquisition vendor profiles remain planned.

When several files use Auto headers, JASC compares the results before importing. If some appear headerless or the detected names differ, choose:

- **Keep Detected** to import each file with its own detected structure.
- **Use Generic Columns** to drop detected header rows and consistently name columns `Column 1`, `Column 2`, and so on; genuinely headerless files keep their first data row.
- **Cancel Batch** to import nothing and revise the source selection or rules.

Unreadable files stop the preflight. Once importing begins, an individual parse failure or declined large-dataset warning is reported without removing other files imported successfully.

The imported dataset uses the source filename as its base name and remembers the source path. Files of at least 100 MiB trigger a warning before parsing. Large parsed worksheets trigger a second size/memory warning before they enter the workspace.

### Import an Excel workbook

1. Choose **File > Import Data...** (`Ctrl+I`) or use the toolbar action.
2. Select a modern `.xlsx` or `.xlsm` workbook. Legacy `.xls` files must first be saved as `.xlsx` in Excel or another compatible application.
3. Review the workbook compatibility warnings. JASC inspects the workbook package for charts, pivot tables, Excel tables, images/media, chart-only tabs, macros, external links, query tables, data connections, comments, slicers, named ranges, and hidden tabs.
4. Choose **Import all worksheet tabs** or **Choose specific worksheet tabs**. Selective import is the safer default: visible worksheets start checked and hidden worksheets start unchecked. Import All includes hidden worksheets. Chart-only tabs are listed for transparency but are always excluded because they contain no worksheet grid.
5. Choose whether the first row of every selected worksheet contains column names and confirm the import.

Each selected worksheet becomes an independent dataset named `Workbook - Worksheet`. If that name already exists, JASC adds its normal numeric suffix. Every imported dataset retains the workbook as its source path.

Excel import is intentionally value-only:

- Cached worksheet cell values are imported. JASC does not execute Excel formulas; formulas without a saved cached result may appear blank.
- VBA macros, queries, external connections, and external links are never executed or refreshed.
- Charts, pivot layouts/caches, images, shapes, controls, comments, named ranges, filters, totals rows, formatting, conditional formatting, validation, protection, merged-cell layout, print settings, and display settings are not reproduced.
- Cells backing a chart, pivot result, or Excel table can still be imported when they are present in a selected worksheet grid.
- One malformed or missing selected tab is reported without discarding other successfully parsed tabs. Empty tabs and worksheets declined at the large-data warning are skipped.

Excel workbooks are compressed containers, so their in-memory DataFrames can be substantially larger than the file on disk. The normal file-size and per-worksheet memory warnings apply.

### Create a blank worksheet

Choose **File > New Blank Sheet** (`Ctrl+N`), the toolbar action, or **New Sheet** in the dataset navigator. JASC creates a normal workspace dataset with:

- 25 initially blank rows.
- Auto-typed `x` and `y` columns. All-numeric input is stored numerically, while dates and text remain accepted without changing metadata first.
- `X` and `Y` column roles already assigned.

The sheet is immediately editable in the Data tab. Use Data menu commands to add or insert rows and columns.

### Fill or create a numeric column

Choose **Data > Fill Range...** to populate values. The dialog now makes the destination explicit:

- **Target action**: update a selected existing column, or create a separately named new column.
- **Fill pattern**: an arithmetic sequence, or one constant value repeated deliberately.
- **Start row**: one-based worksheet row.
- **Count**: number of values.
- **Start value** and **Step**.

The **Result** line previews the action, target, affected row interval, and generated values before the operation runs. Launching Fill Range from a selected column defaults to updating that column; without a column selection it defaults to creating a new column. JASC rejects a new-column name that already exists instead of silently changing the operation. For a sequence it writes `start + offset * step`; Constant value is the same operation with an explicit zero step. JASC grows the worksheet if required and converts a blank/object-backed destination to a real numeric column, so it can immediately be used by formulas such as `sin(col1)`. Existing text outside the replaced rows is rejected before any write; replace it or create a separate numeric column. JASC marks the output Numeric, assigns the X role when the name is `x`, `time`, or `t`, removes a stale formula from an overwritten column, and records provenance in the column comment.

### Smart Fill from existing cell values

Use **Data > Smart Fill Selection...**, the **Smart Fill** inspector button, or **Columns > Smart Fill Selection...** in the worksheet context menu to complete blank cells from values already entered in the sheet:

1. Enter seed values when the selected mode requires them.
2. Select one contiguous rectangle containing the seeds and blank destination cells. A Custom List may instead fill a completely blank selection.
3. Open Smart Fill and select **Auto**, **Numeric**, **Date-Time**, **Category Cycle**, or **Custom List**.

Smart Fill reports the existing-anchor count for each selected column, treats every existing value as an anchor, and writes only blank selected cells. It handles:

- **Auto** chooses Numeric when every anchor is a finite number, Date-Time for datetime values or recognizable date/time strings, and Category Cycle for other text. A column explicitly marked Text remains categorical in Auto even if its labels look numeric.
- **Numeric** repeats one seed or applies linear interpolation/extrapolation to two or more anchors using visible worksheet row positions. For example, `1, 2, blank, blank` becomes `1, 2, 3, 4`; `1, blank, 2` becomes `1, 1.5, 2`. Numeric pattern controls can also detect or explicitly select two through eight interleaved linear sequences: `1, 10, 2, 20, blank, blank` becomes `1, 10, 2, 20, 3, 30`.
- **Date-Time** repeats one timestamp or infers the interval between two or more anchors. Numeric text dates accept every ordering of day, month, and year (`day/month/year`, `month/day/year`, `year/month/day`, `year/day/month`, `day/year/month`, or `month/year/day`). Smart Fill infers one order from all anchors, uses sequence evidence when day and month are both 12 or less, falls back deterministically to day-first if the anchors cannot distinguish them, and keeps the inferred order, separator, and zero-padding in generated cells. Exact same-day or month-end monthly/yearly patterns use calendar offsets, so `2024-01-31, 2024-02-29` continues with `2024-03-31`; other patterns use elapsed-time interpolation/extrapolation.
- **Category Cycle** takes the first consecutive seed block as one complete cycle. `Red, Blue, Green, blank, blank` continues with `Red, Blue`. Additional nonblank anchors must agree with the cycle.
- **Custom List** accepts one ordered item per line. Existing anchors align the list case-insensitively; with no anchors, filling starts at its first item. Lists can represent weekdays, months, cities, colours, sample states, or a user-specific order.
- Several selected columns are inferred independently using the same requested mode and custom list.

The operation is deliberately deterministic and does not query the web. It does not guess arbitrary semantic relationships, nonlinear numeric models, or worksheet cell background formatting: colour names are category values, while actual cell colours would require a separate formatting system. Smart Fill is undoable, invalidates stale whole-column formula metadata in modified columns, and records its resolved mode and pattern in column provenance.

---

## 5. Digitizing Data from Figure Images

Use **File > Import From Figure...** to extract calibrated data from PNG, JPEG, BMP, TIFF, or GIF figures. First choose the image type:

- **XY graph** calibrates graph axes and extracts curves, lines, or symbols.
- **2D colour plot / heatmap** calibrates X/Y plus a displayed continuous colour scale and returns clicked X/Y/Z probes.

Both workflows share image loading, optional perspective correction, linear/log X/Y calibration, canvas navigation, and normal workspace-dataset output.

### Canvas controls and tool state

The toolbar above/below the image provides **Load Image**, **Fit View**, **1:1**, **Zoom In**, **Zoom Out**, **Pan**, and **Magnifier**. The mouse wheel zooms around the pointer. The **Precision Zoom** panel follows the cursor and shows an enlarged neighborhood with pixel and calibrated-coordinate readouts.

The yellow mode banner reports what the next canvas click or drag will do. It is a status display, not a button. Use the controls in the Correction, Calibration, and Extraction tabs to activate a picking tool. Enable **Pan** when dragging should move the image without picking data.

### Step 1: optional perspective correction

Use the **Correction** tab when a photograph or scan is skewed.

1. Click **Pick top-left**, **Pick top-right**, **Pick bottom-right**, and **Pick bottom-left**, clicking the corresponding plot-frame or axis-bar corners in that order.
2. Review the green quadrilateral.
3. Set the corrected image width and height in pixels.
4. Click **Apply Correction**.

Calibration and extraction then operate on the rectified working image. **Clear Points** removes the four correction points. **Reset Original** restores the original image and clears pixel-dependent calibration and extraction state.

Correction is optional. When you switch from **Correction** to **Calibration**, JASC automatically changes the canvas tool from the correction corners to the first unpicked X/Y calibration reference. Returning to Correction similarly selects the first unpicked correction corner.

### Step 2: calibrate X and Y

The calibration maps pixels to data coordinates using two references per axis.

1. In **Calibration**, select `X axis point 1`, click its pixel location, and enter the known X value.
2. Repeat for X point 2, Y point 1, and Y point 2.
3. Choose **Linear** or **Log10** independently for X and Y.
4. Review the calibration status. Use **Clear Calibration** to start over.

Calibration values must be distinct on each axis. Log10 calibration requires positive reference values and is appropriate only for logarithmic axes.

### XY graph: Step 3A, manual point extraction

1. Open **Extraction** and click **Manual Mode**.
2. Click data points on the image. Use **Stop Picking** when finished.
3. Use **Undo Last** to remove the latest manual point or **Clear Manual** to remove all manual points.

To attach uncertainty to a manual point:

1. Select the target point number in **Error target point**.
2. Click **Radius Error**, then click one radial boundary. This assigns symmetric pixel uncertainty from the distance to the point.
3. Alternatively, click **4-Point Error** and pick the X-low, X-high, Y-low, and Y-high boundaries.

Manual uncertainties appear as blue error bars and are exported in both pixel and calibrated data units.

### XY graph: Step 3B, automatic curve or line tracing

The **Automatic Extraction Region** is shared by curve tracing and symbol detection.

1. Optionally click **ROI Brush** and paint the region to scan. Adjust **Brush size** as needed. Without ROI marks, JASC scans the full working image. X/Y calibration points define the coordinate scale only; they do not crop automatic extraction. Pixel-to-data conversion extrapolates outside the calibration references when necessary.
2. In the **Curves/Lines** subtab, choose **Dark pixels** or **Selected color**.
3. For dark pixels, adjust **Dark threshold**.
4. For color tracing, use **Pick Color...** or **Sample From Image**, then set **Color tolerance**.
5. Set **X pixel step** to control horizontal sampling density.
6. Click **Run Auto Trace**. Use **Clear Auto** to discard the trace.

### XY graph: Step 3C, symbol detection

The **Symbols** subtab has two related paths:

- **Detect Symbols** finds connected foreground components using the current dark/color rule and ROI. Use Min area, Max area, and Max symbols to reject lines, noise, or oversized objects.
- **Detect Sampled** matches a learned marker template. Click **Sample Symbol**, then click near a marker center for radius-based capture or drag a box around it. Configure the shape prior, sample radius, minimum match score, minimum separation, and maximum symbol count before detection.

Shape priors are **Auto from sample**, **Dot / circle**, **X cross**, **Plus cross**, **Square**, **Diamond**, **Triangle up**, and **Triangle down**. They help suppress line pixels touching a marker. **Clear Template** discards the learned template; **Clear Symbols** discards detected centers.

Symbol outputs include area, width, height, match score when applicable, template dimensions, and uncertainty estimated from marker size.

### XY graph: Step 4, review and create one or more datasets

Open **Output** to set the dataset name and inspect the read-only preview. Each row can include:

- Calibrated X, Y, dX, and dY.
- Pixel X, Pixel Y, dPx, and dPy.
- Extraction method, trace rule/color, ROI count, and source image.
- Symbol ID, area, score, size, and template diagnostics.

To create a worksheet and continue extracting from the same figure without repeating calibration:

1. Enter a distinct dataset name for the completed curve.
2. Click **Create Dataset & Continue**. The worksheet is added to the workspace immediately while the digitizer remains open.
3. After the worksheet is successfully added, JASC clears only curve-specific manual points, uncertainty marks, automatic trace, symbol results/template, and ROI marks. The embedded working image, perspective-correction result, and X/Y calibration remain available. If worksheet creation is declined or fails, the current extraction remains intact.
4. Extract the next curve and repeat **Create Dataset & Continue** for every additional worksheet.

**Queue Current Curve & Start New** remains available when several completed curves should be imported together when the dialog closes. The Output status distinguishes queued curves from datasets already created. **Close** warns before discarding an uncreated current extraction. Loading another image, applying a new perspective correction, or resetting to the original image changes pixel geometry, so JASC asks for confirmation before clearing queued curves and calibration.

JASC requires a loaded image, complete four-point calibration, at least one manual, traced, or symbol point, and a dataset name. Each created dataset receives numeric coordinate metadata, X/Y/error roles where appropriate, source/provenance comments, the image source path, and a resumable figure-session snapshot.

### Resume a saved figure extraction

Every dataset created through **Create Dataset & Continue** stores a reference to its figure session. Choose the dataset and use **Data > Resume Figure Extraction...** or the dataset context menu to reopen it. JASC restores:

- The exact working image used for digitization, embedded in the `.jasc` project rather than loaded from the original external path.
- X/Y calibration pixels, values, and linear/log scale choices.
- Whether the embedded working image resulted from perspective correction.
- For 2D colour plots, colour-bar endpoints and values, normalization, sampling controls, validity threshold, and probe patch radius.

Extracted point markers are deliberately not restored: reopening starts a clean next curve/probe set on the retained image and calibration. Datasets created from the same session share one embedded image inside the project archive. Saving embedded raster images increases `.jasc` project size, particularly when unrelated figures or high-resolution images are used.

### 2D colour plot / heatmap workflow

Choose **2D colour plot / heatmap** in the initial figure-type dialog. This workflow learns the palette empirically from the colour bar as it actually appears in the image, rather than assuming a named Matplotlib colour map.

1. Load the image and optionally apply perspective correction.
2. Calibrate X and Y exactly as described above. Reference points may be inside the full data region; the mapping extrapolates beyond them.
3. In **Displayed Colour Scale**, enter the numeric values represented at the two ends and choose **Linear** or **Log10** value normalization. Log10 endpoints must be positive.
4. Click **Pick Low End**, then click the centre of the colour bar at the entered low-value end. Click **Pick High End** and click its high-value end. Endpoints may be horizontal, vertical, diagonal, or reversed in screen direction.
5. Adjust **Bar sample width** if necessary. JASC samples a median stripe across that width along the complete endpoint-to-endpoint segment. **Palette samples** controls its resolution. Click **Rebuild Scale** and inspect the displayed sampled palette.
6. Set the probe **Median patch radius**. A small median patch reduces isolated compression noise, but a large radius can mix neighbouring colours near sharp boundaries.
7. Click **Start Probing**, then click locations in the colour plot. The shared magnifier shows live X, Y, estimated Z, RGB, confidence, and validity. Click **Stop** when finished.
8. In **Output**, inspect the rows. Use **Undo Last**, **Remove Selected**, or **Clear Probes** to clean the result. Enter its dataset name and click **Create Dataset & Continue** to add the worksheet immediately while retaining the image, X/Y calibration, and colour-scale calibration. Only the probes are cleared, so additional probe datasets can be created without closing or recalibrating.

Each output row contains calibrated `x`, `y`, and estimated `z`; source pixel coordinates; median red/green/blue values; normalized palette position; CIE Lab colour distance; confidence; ambiguity and validity flags; patch radius; extraction method; and source image. X, Y, and Z metadata roles are assigned automatically. Rows that fail the distance threshold or are ambiguous are deliberately retained so they can be inspected and filtered instead of silently discarded. **Maximum Lab distance** controls the validity cutoff.

> **Accuracy disclaimer:** colour values are estimates from rendered raster pixels. Lossy image compression, anti-aliasing, resizing, overlaid text or contours, transparency, and limited palette resolution introduce inherent error. Always review colour distance, confidence, ambiguity, and validity before scientific use. Prefer an original lossless image and probe away from labels, grid lines, and boundaries when possible.

The current colour workflow supports continuous empirical colour bars and clicked point probes. Discrete/categorical palettes and automatic full-grid reconstruction are not yet implemented.

---

## 6. Editing Worksheets and Column Metadata

### Select and edit cells

- Double-click a cell, enter a value, and press Enter to commit.
- Blank input is stored as a missing value.
- Numeric/Scientific metadata rejects non-numeric text. Text columns preserve entered text.
- Numerical operations also inspect Auto columns: blanks may be treated as missing where
  supported, but nonblank text is never silently discarded. The error identifies the
  first visible row and an example value so the worksheet can be corrected before retrying.
- Select complete rows or columns using their headers; use Ctrl/Shift selection where supported by the platform.

### Add, insert, and delete structure

- **Data > Add Row** appends a blank row.
- **Data > Insert Row** inserts before the active/selected row.
- **Data > Add Column...** appends a uniquely named blank column.
- **Data > Insert Column...** inserts before the active/selected column.
- **Data > Resize Sheet...**, the **Resize Sheet** inspector button, or the worksheet context menu sets the total row and column counts together. Growing adds empty cells and uniquely named columns. Shrinking asks for confirmation because values, formulas, and metadata outside the new limits are removed.
- **Edit > Delete Selected Rows** or `Shift+Delete` removes every selected row after confirmation.
- **Edit > Delete Selected Columns** or `Ctrl+Delete` removes every selected column after confirmation.
- `Delete` clears values in the selected cells without removing worksheet structure. The clear is undoable and invalidates stored formula metadata for affected columns because their generated result is no longer intact.

Row and column edits participate in Undo/Redo when the worksheet fits within the history budget.

### Clipboard operations

#### Copy and paste values

1. Select cells and press `Ctrl+C`, or right-click and choose **Copy Values**.
2. Activate the destination cell and press `Ctrl+V`, or choose **Paste Values**.

Values use tab-delimited clipboard text. JASC expands the worksheet to fit the pasted rectangle, infers numeric blocks where safe, preserves explicit Text destinations, and clears formulas on overwritten columns.

Right-click and choose **Copy Row(s)** to copy every column from all rows touched by the selection. To exchange rows and columns, choose **Paste Values Transposed** or press `Ctrl+Shift+V`. The complete rectangular clipboard matrix is transposed: an M-row by N-column copy becomes N rows by M columns, so this works for single rows, single columns, and multi-row/multi-column selections.

#### Copy and paste whole columns

Right-click selected columns and choose **Copy Column(s)**. In another JASC worksheet, right-click a destination column and choose **Paste Column(s)**. Whole-column copy uses a JASC-specific clipboard payload that preserves:

- Column headers.
- Values.
- Column roles, types, precision, units, long names, and comments.

Pasted columns are inserted before the destination and renamed automatically if their names collide. The metadata-preserving payload is available only while the clipboard still contains the JASC column data; plain-text applications receive the tabular values.

JASC validates every metadata-preserving pasted column before inserting any of them. If
a Numeric/Scientific column contains nonnumeric text, the whole paste is rejected and the
worksheet remains unchanged.

### Undo and redo

Use **Edit > Undo** (`Ctrl+Z`) and **Edit > Redo** (`Ctrl+Y`). History covers cell edits and clearing, worksheet resizing, row/column changes, clipboard pastes, Fill Range, Smart Fill, formula writes, metadata/column renames, and current-sheet calculus/smoothing changes where the operation captures editor state.

History is dataset-specific and resets when the displayed dataset changes. Each undo and redo stack retains at most 20 snapshots and approximately 256 MiB. If one worksheet snapshot exceeds the budget, JASC performs the edit but warns that it cannot be undone. Creating/removing datasets or batch changes to non-visible sheets are not guaranteed to be undoable from the current table history.

### Column Metadata dialog

Open **Data > Column Metadata...**, double-click a column header, or use the table context menu. Each row exposes:

| Field | Purpose |
| --- | --- |
| Column name | Renames the column; names must be nonblank and unique |
| Role | Hints default selections in plotting, fitting, interpolation, and analysis |
| Type | Controls display and explicit numeric/text validation |
| Precision | Auto or 0-15 displayed decimal places; Scientific uses exponential notation |
| Unit | Included in suggested plot-axis labels |
| Long name | Human-readable axis/header description |
| Comment | Notes, source details, and generated-operation provenance |

Available roles are **None**, **X**, **Y**, **Z**, **Error**, **X error**, **Y error**, **Group**, **Label**, and **Weight**. Available types are **Auto**, **Numeric**, **Scientific**, and **Text**.

Changing display precision does not change stored values. Renaming a column carries its formula and metadata forward and updates active and saved plot column references.

### Formula and provenance indicators

Formula-backed and metadata-rich column headers expose details in tooltips. Generated operations append an `Operation:` line to column comments, replacing the prior generated-operation line while retaining other user comments.

---

## 7. Data Preparation

Data Preparation commands create new result datasets. The source sheet remains unchanged. Matching metadata is copied where output columns retain their original names, and JASC records the operation in output-column comments.

If an operation returns no rows, JASC asks whether to create the empty output sheet.

### Extract Subset

Use **Data > Extract Subset...**, the Data Prep inspector, or a worksheet's **Data Preparation** context submenu to create a positional sample of the active sheet. Row and column rules are independent and can be combined:

- **All positions** keeps that dimension unchanged.
- **Odd positions** keeps visible worksheet positions 1, 3, 5, and so on.
- **Even positions** keeps visible worksheet positions 2, 4, 6, and so on.
- **Every Nth position** keeps the selected starting position and advances by N. For example, interval 3 starting at row 2 keeps rows 2, 5, 8, and so on.

The dialog previews the resulting row and column counts before creation. Positions are based on the displayed 1-based worksheet numbering, not the internal Pandas index. The source remains unchanged, output rows are renumbered from zero internally, retained columns keep their metadata, and the row/column rules are written to the result's operation provenance.

Use **Filter / Query** instead when rows should be chosen by their values rather than their positions.

### Filter / Query

Choose one dataset, one column, one condition, and an output sheet. Supported conditions are:

- Equals / does not equal.
- Greater than, greater than or equal, less than, less than or equal.
- Between two numeric values, inclusive.
- Contains / starts with.
- Is in a comma-separated list.
- Is blank / is not blank.

Numeric comparison text must parse as a number. The current dialog applies one condition at a time; multi-condition query building and in-place filtering are not implemented.

Mean/median/interpolation cleanup, numeric filters, grouping, and binning reject nonblank
nonnumeric source cells instead of treating them as missing. **Fill with value** also
refuses a text replacement for a numeric or safely inferred numeric column; mark an
intentional category column Text when textual missing-value labels are required.

### Sort

Select one or more columns, Ascending or Descending, and an output name. Multiple keys are applied in their worksheet order using a stable sort.

### Remove Duplicates

Select the columns that define a duplicate group and choose:

- **Keep first occurrence**.
- **Keep last occurrence**.
- **Remove every row in a duplicate group**.

Blank/NaN values in the same selected key columns are treated as matching.

### Missing Values

Select one or more columns and a strategy:

- Drop rows missing a selected value.
- Fill with a literal value.
- Fill numeric blanks with the column mean.
- Fill numeric blanks with the column median.
- Interpolate numeric gaps in both directions.

Mean, median, and interpolation coerce the selected output columns to numeric values; non-numeric entries become missing before filling.

### Bin / Average

Choose a numeric bin column, one or more value columns, and a bin count. JASC creates equal-width bins between the observed minimum and maximum and reports:

- Bin interval, start, end, and center.
- Row count.
- Mean, sample standard deviation, SEM, minimum, and maximum for every selected value column.

Binning requires a non-constant numeric bin column.

### Group / Aggregate

Choose one or more group columns, distinct numeric value columns, and one or more aggregations: count, mean, standard deviation, SEM, minimum, maximum, and sum. Missing group keys are retained as groups.

### Merge / Join

Choose left and right datasets, one key from each, and **Inner**, **Left**, **Right**, or **Outer** join. Same-named right-side columns receive a `_right` suffix where required.

### Reshape

- **Transpose** converts columns to rows and adds a `source_column` field.
- **Melt / stack** retains selected identifier columns and stacks selected value columns into `variable` and `value` fields.

---

## 8. Formulas and Expressions

Choose **Data > Apply Formula...** (`Ctrl+Shift+F`) to calculate a new column or update an existing column with a constrained Python-like expression.

### Basic workflow

1. Select or type a **Target column**. When the dialog was launched from one selected existing column, that column is preselected as an update target.
2. Choose the explicit **Output action**:
   - Create a unique new column.
   - Stop and warn.
   - Overwrite/update the existing column.
3. Enter the expression.
4. Choose the **Operation scope**:
   - **Entire target column** evaluates and writes every row. This is the mode used for multi-sheet batches.
   - **Selected cells in target column** writes only cells that are selected in that specific target column. It applies only to the current sheet and always updates the existing target column.
5. Select one or more sheets for an entire-column/batch operation.
6. Choose exact-name or position column matching for batch targets.
7. For formula batches, choose **Auto**, **Sequential**, or **Parallel processes**, plus the maximum worker count.
8. Confirm the preflight preview and run.

When a formula-backed target column is selected, JASC reloads its stored expression unless doing so would overwrite an expression currently being edited.

### Referencing columns and rows

| Syntax | Meaning |
| --- | --- |
| `voltage` | A column whose name is a safe Python identifier and does not conflict with a built-in name |
| `col1`, `col2`, ... | First, second, and later columns by position |
| `col("Voltage (V)")` | Exact-name access for spaces, punctuation, keywords, or conflicting names |
| `sheet("Calibration", "Gain")` | Column `Gain` from worksheet `Calibration`, aligned by visible row position |
| `row` | One-based row-number series |
| `index` | The pandas index as a series |

Use the worksheet/column selectors and insert buttons to avoid typing mistakes. Choosing the current worksheet inserts `colN` or `col("Name")`; choosing another worksheet inserts a complete `sheet("Worksheet", "Column")` reference.

Cross-worksheet values are matched by visible row position, independently of the pandas index. If the referenced worksheet is shorter than the target, remaining target rows receive missing values; extra source rows are ignored. Renaming a worksheet updates literal `sheet(...)` references saved in formula metadata.

Examples:

```python
col("Voltage (V)") / col("Current (A)")
col("Raw signal") * sheet("Calibration", "Gain") + sheet("Calibration", "Offset")
np.sin(col1) * np.exp(-col2)
where(col1 > 0, sqrt(col1), nan)
row * 0.1
special.erf((col1 - 5) / 2)
signal.savgol_filter(col2, 11, 3)
np.random.normal(0 * col1, 1)
```

### Available safe namespaces

The evaluator exposes a curated subset, not unrestricted NumPy/SciPy or Python.

- **NumPy**: functions are available both directly (`sin`, `sqrt`, `where`) and through `np` (`np.sin`, `np.sqrt`, `np.where`). Categories include arithmetic, trigonometry, logarithms, rounding, reductions, cumulative operations, gradients/differences, clipping, conditions, interpolation, finite-value checks, and array helpers.
- **NumPy subnamespaces**: selected `np.fft` functions, `np.linalg.norm`, and selected `np.random` generators.
- **SciPy aliases**: `scipy` and `sp`.
- **SciPy subnamespaces**: `special`, `signal`, `stats`, and `integrate`, also accessible as `scipy.special`, `scipy.signal`, `scipy.stats`, and `scipy.integrate`.
- **Constants**: `pi`, `e`, `nan`, and `inf`, also available through `np`.

The Help panel inside Apply Formula lists the allowed functions and examples for the installed version.

### Safety and expression rules

- Use `**` for powers. JASC rejects `^` because Python interprets it as bitwise XOR.
- File access, imports, Python builtins, private attributes, assignments, comprehensions, and arbitrary object access are blocked.
- A scalar result such as `5` or `np.mean(x)` is deliberately repeated across the destination rows. Reference a column, such as `x * 2`, for row-by-row results. A vector result must match the worksheet length.
- Wholly numeric object/string columns are promoted before formula evaluation, so imported
  values such as `"1"`, `"2"` work numerically. Mixed number/text columns cannot silently
  perform string repetition during numerical expressions; correct the source data or use
  an explicit text expression.
- Numeric/Scientific formula targets reject textual results before assignment. Explicit
  Text targets receive string values, and Numeric/Scientific metadata is also validated
  before every downstream math operation.
- Entire-column application stores the expression in project metadata and records it in the target column comment. Selected-cell application records cell-scoped provenance but removes any whole-column formula marker because the complete column no longer represents one formula.

---

## 9. Calculus, Smoothing, FFT, and Interpolation

All workbenches in this section support multiple compatible worksheets. Derivative, Integral, and Smoothing write columns into target worksheets; FFT, Inverse FFT, and Interpolation create result datasets.

Target signal/value lists start with **no columns selected**. Choose one or more columns explicitly in the dialog before applying the operation; each click toggles a column, so selecting two signals does not require accepting an automatically chosen first signal. JASC may still suggest the coordinate/X column from metadata because it defines spacing or alignment, but it never silently selects the Y, signal, spectrum, interpolation-value, statistics, or curve-fit response columns. Optional fit uncertainty/weight columns also start empty. Applying without the required selection shows a validation message and performs no operation.

### Derivative

Choose **Analysis > Derivative...**, select one X column and one or more Y columns, then choose:

- NumPy gradient.
- Forward difference.
- Backward difference.
- Central difference.
- Savitzky-Golay derivative.

Set a target column or template, conflict policy, matching mode, target sheets, and whether to plot immediately. Use `{column}` in the target name when processing several Y columns.

X/Y data are aligned after numeric conversion and blank removal. X values cannot contain duplicate positions. The Savitzky-Golay derivative also requires evenly spaced X values.

### Integral

Choose **Analysis > Integral...**. Methods are:

- Cumulative trapezoid.
- Cumulative Simpson.
- Left rectangle.
- Right rectangle.
- Midpoint rectangle.

The **Initial value** is the integration constant added to the cumulative result. Integral has the same multiple-Y, target, conflict, batch, and immediate-plot controls as Derivative.

### Smoothing

Choose **Analysis > Smoothing...**. The dialog previews the first selected Y signal and limits preview rendering to at most 4,000 evenly sampled points.

| Method | Relevant controls |
| --- | --- |
| Adjacent average | Window points |
| Moving median | Odd window points |
| Savitzky-Golay | Odd window points and polynomial order smaller than the window |
| LOWESS / LOESS | Fraction of data and robust iterations |
| FFT low-pass | Cutoff as percent of Nyquist; evenly spaced X required |
| Derivative smoothing + integration | Derivative smoother, optional odd slope-spike median prefilter, endpoint preservation |

Derivative reconstruction calculates `dy/dx`, optionally removes derivative spikes, applies any non-recursive smoothing method, then integrates from the original first Y value. **Preserve first and last data values** distributes residual drift so the reconstruction ends at the original last value.

The default target template is `{column}_smoothed`. Choose a conflict policy, name/position matching, target sheets, and whether to plot original versus smoothed data immediately.

### FFT

Choose **Analysis > FFT...** and select one or more signal columns. Choose an X/time column to derive sample spacing, or **Sample index** for spacing 1. Available windows are:

- None / rectangular.
- Hann.
- Hamming.
- Blackman.
- Bartlett.
- Flat top.

When an X/time column is used, values must be finite and evenly spaced within the operation tolerance. Each result dataset contains `frequency`, `real`, `imaginary`, `magnitude`, and `phase`. The optional immediate plot shows magnitude versus frequency.

### Inverse FFT

Choose **Analysis > Inverse FFT...** and select one or more real spectrum columns. Imaginary input may be:

- Empty, meaning zero imaginary component.
- One column reused for every selected real column.
- The same number of columns as real selections, paired by selection order.

Each result contains `sample`, `real`, `imaginary`, and `magnitude`. The optional immediate plot shows the reconstructed real signal.

### Interpolation

Choose **Analysis > Interpolation...**. Select one or more value columns and a dimensional mode.

#### Supported methods

| Mode | Methods |
| --- | --- |
| 1D | Linear, nearest neighbor, cubic spline, PCHIP, Akima, smoothing spline |
| 2D | Nearest neighbor, linear scattered, cubic spline, piecewise cubic / Clough-Tocher, smooth bivariate spline, RBF linear, thin plate, cubic, Gaussian |
| N-D | Nearest neighbor, linear scattered, RBF linear, thin plate, cubic, Gaussian |

N-D mode requires at least two unique coordinate columns. Value columns must differ from coordinate columns. Duplicate source coordinates are averaged.

#### Query coordinates

- **Generated range/grid**: available for 1D and 2D. Set start, end, and count for each dimension. A 2D query produces the Cartesian X/Y grid.
- **From existing columns**: choose one query column per coordinate dimension.
- **Manual coordinates**: enter one point per line, separating values with spaces, commas, or tabs.

Generated queries are limited to 1,000,000 points.

#### Optional method parameters

- **Outside range** applies to 1D: blank outside the source range, extrapolate where supported, or clamp to edge values.
- **Smoothing** is enabled for smoothing splines and RBF methods.
- **RBF epsilon** is enabled for Gaussian RBF; zero displays as automatic.

The result preserves query coordinates and adds one `{value_column}_interpolated` prediction column per selected value. Result-sheet templates can use `{source}` and `{column}` in batch mode.

### Baseline Correction and Peak Analysis

Choose **Analysis > Baseline Correction...** for a correction-only workflow,
**Analysis > Peak Analysis...** for a general spectrum workflow, or **Analysis >
Raman Analysis...** for the same tested configuration and numerical engines with
results presented in the dedicated Raman Analysis module. The Raman entry does
not maintain a divergent fitting implementation.

The worksheet from which the command was launched is preselected, but it is not
locked: choose any workspace worksheet in **Source & Range**, then select one
X/spectral-axis column and one intensity column explicitly. The engines accept
ascending or descending and evenly or irregularly spaced X values.
Missing rows remain missing, while contiguous finite segments are analyzed
independently. An optional physical-X range can limit the analysis.

For a normalized long-form map, choose **Long-form map (group by X/Y)** under
**Source layout**. JASC selects this automatically when the worksheet contains
multiple finite `X`/`Y` coordinate groups, but the control remains explicit so a
worksheet can be interpreted deliberately. Choose one entry under **Preview X/Y
pixel**. Only that pixel's spectrum is used for interactive baseline, detection,
and component-fit preview; the complete repeated-axis table is never treated as
one spectrum.

After the representative pixel looks correct, choose **Current long-form Raman
map (group by X/Y)** under **Apply to**. Baseline Correction then applies the
reviewed baseline parameters independently to every X/Y group. Peak Analysis
does the same for baseline/detection/fitting and matches reviewed components by
center tolerance. The saved analysis retains `X` and `Y` on every metric, curve,
peak, and parameter row. A single-pixel result remains available by choosing
**Current preview spectrum / selected pixel** instead.

The **Baseline** tab provides:

- arPLS (automatic default), AsLS, airPLS, SNIP, and rubber-band methods;
- manual anchors with linear, PCHIP, or Akima interpolation. Choose **Explicit
  X:Y baseline points** to enter `x:y` pairs separated by semicolons, or **X
  positions (sample each source signal)** to enter a list such as
  `100; 250; 400; 700`;
- constant, linear, and polynomial backgrounds; and
- explicit positive, negative, or mixed peak polarity.

X-only anchors are the recommended reusable segment definition. JASC stores the
physical X positions, then independently interpolates the current source signal
at those positions whenever the correction runs. The same profile therefore
uses identical spectral locations across worksheets or map pixels without
incorrectly copying one spectrum's baseline Y values into another. Every anchor
must be unique and inside the finite, selected X range. The resolved X:Y points
are retained in operation provenance.

`pybaselines` is the preferred backend. If it is absent, JASC uses a sparse,
memory-bounded fallback and reports that fact in the warnings/provenance. The
preview reports convergence and iteration diagnostics. One-sided baseline
methods warn when mixed-polarity peaks may bias the result.

The **Detection** tab uses prominence-based SciPy peak finding on the corrected
signal. Prominence may be explicit or estimated from robust first-difference
noise. Height/SNR, minimum center distance, minimum/maximum FWHM, minimum
plateau width, maximum candidate count, polarity, and optional moving-median or
Savitzky-Golay smoothing are configurable. Distances and widths are always in
physical X units, including on irregular axes.

The preview shows raw data with its baseline and corrected data with linked peak
markers. In the review table you can disable a candidate, edit its center,
remove it, or add a candidate at a physical X coordinate. Numerical analysis
always uses the complete input; only preview rendering is decimated for long
spectra.

Use the toolbar directly above the preview to inspect small features. **Zoom**
lets you drag a rectangle around a small peak, **Pan** moves through the enlarged
view, **Back/Forward** revisit view changes, and **Home** restores the complete
preview. The toolbar's save action exports the currently displayed preview image;
it does not create an analysis worksheet or parameter profile.

### Reusing Peak Analysis parameters

Use **Save Parameters...** and **Load Parameters...** at the top of either
Baseline Correction or Peak Analysis. Profiles are portable, human-readable
UTF-8 JSON files with the `.jasc-analysis.json` extension. A profile saved from
Baseline Correction contains the range and baseline subset; one saved from Peak
Analysis additionally contains detector and fit settings. Together the fields are:

- the optional physical analysis range;
- every baseline method control, interpolation choice, and explicit or X-only
  anchor list;
- every detection threshold, physical distance/FWHM/plateau control, width
  relative height, smoothing choice, and candidate limit;
- corrected/raw fit mode, the shared baseline, loss function, maximum
  evaluations, and peak-center matching tolerance; and
- reviewed component enable states, reference centers, polarities, and registered
  peak-model choices.

Loading a profile changes algorithm settings only. It does not change the source
worksheet, source columns, output names, output scope, or selected batch sheets.
After detection refreshes, saved component models are assigned to the nearest
compatible reviewed centers. Batch/map execution continues to enforce the
explicit center-matching tolerance. Profile files carry a schema name and version;
unknown or malformed profiles are rejected instead of being partially guessed.

The **Fit Components** tab creates one row per reviewed peak. Enable or disable
each component and independently choose a registered Gaussian, Lorentzian,
Voigt, pseudo-Voigt, Pearson VII, sech-squared, Laplace, Fano, asymmetric
Gaussian, split Lorentzian, exponentially modified Gaussian, Fraser-Suzuki, or
Doniach-Sunjic model. Starting centers, heights/areas, and physical widths come
from the reviewed detector results with model-specific conversions.

Fano is handled as an interference resonance rather than an ordinary one-lobe
peak. Its positive `amplitude` is the continuum-referenced scale, `center` is the
unshifted resonance position, `gamma` is half the natural linewidth, and signed
`q` sets the peak/dip orientation. JASC tries several physically distinct q
starts and reports resonance position, natural linewidth, q, peak position, dip
position, peak contrast, dip contrast, and propagated position/intensity errors.
Its integrated area is explicitly a signed integral over the selected fitting
window and should not be interpreted as a window-independent total area.

Use **Corrected signal** to fit the baseline-corrected values with a fixed zero
fit baseline. Use **Raw signal** to fit one shared zero, constant, linear, or
quadratic baseline plus all enabled peaks. Individual peak offsets are suppressed
so the baseline is not counted once per component. Least-squares, soft-L1, and
Huber loss are available. **Fit Selected Components** previews the total fit and
each component and reports convergence, R squared, RMSE, AIC, and BIC.

Completed full fits are saved first as named analysis sessions under **Workspace
> Analyses**. Signal, peak, fit-curve, parameter, and map worksheets are unchecked
by default and are optional exports, preventing intermediate results from
crowding the Data navigator. Peak rows record
source/channel, source row, center, polarity, raw/corrected height, prominence,
FWHM, boundaries and bases, signed area, local SNR, plateau width, asymmetry,
detector, manual status, and whether the reviewed row is enabled. Worksheet
metadata stores the complete baseline/detection settings, convergence, warnings,
noise estimate, software versions, and source columns.

The **Output & Batch** tab can optionally create a composite-fit curve worksheet
(`observed`, shared `baseline`, `total_fit`, `residual`, and every peak component)
and a tidy parameter worksheet containing semantic roles, bounds, fixed state,
standard errors, integrated areas, fit metrics, status, and errors.

Choose an application scope:

- **Current source worksheet** fits only the selected source.
- **Selected worksheets (batch)** applies the reviewed peak models to the checked
  worksheets. Each spectrum is redetected and matched to the reviewed centers by
  the selected physical-X tolerance; peaks are never matched only by prominence
  rank.
- **Current long-form Raman map** groups the selected worksheet by its normalized
  `X` and `Y` columns and fits every pixel spectrum. Curve, peak, parameter, and
  summary rows carry their X/Y coordinates. A failed worksheet or pixel is
  reported in the cumulative summary without discarding successful jobs.

### Raman Analysis result viewer

The main workspace starts with only **Data** and **Plot**. After a fit is
successfully completed, or after a saved result is opened from **Workspace >
Analyses**, JASC creates the contextual **Raman Results** tab and opens the
persistent session there. Merely starting JASC or loading a project does not add
an empty Raman tab. The Workspace **Analyses** section is likewise hidden when
the project contains no saved analysis sessions.

The map displays the selected numeric parameter or quality metric over X/Y.
Regular grids render as a heatmap and irregular positions as coloured spatial
points. Choose **All / quality** or one reviewed peak, then choose intensity,
area, position, FWHM, asymmetry, native parameters/errors, baseline, SNR, RMSE,
R squared, or another stored metric. Click a map position, or use **Spectrum /
pixel**, to update the linked raw/baseline/corrected spectrum, individual
components, and total fit. The primary view deliberately keeps only the 2D map
and selected-pixel fit visible so both remain large enough for inspection.
The fitted-spectrum title shows only the selected X/Y coordinates rather than
repeating a potentially long source filename. Double-click either plot title,
an X/Y axis label or tick area, or the fitted-spectrum legend to edit it in
place. The axis editor controls its label, scale, automatic/manual limits,
label/tick sizes, and grid.

Double-click the spectrum legend, or use **Curves / Legend...**, to show or hide
the raw/original signal, removed preprocessing baseline, corrected signal, fit
input, shared fit baseline, total fit, and individual peak components. The same
dialog edits legend labels, position, text size, columns, frame, and opacity;
the button remains available even if every curve or the legend itself is hidden.
Enable **Show diagnostics** when needed to reveal a compact lower panel with
separate **Residual / Fit Error**, **Metric Distribution**, and **QC Details**
tabs. Hiding diagnostics returns that space to the map and fitted spectrum.

Use **Export Results to Worksheets...** only when a normal worksheet is needed.
The export dialog independently offers parameter maps/fit quality, all fitted
curves, detailed parameters, and detected/reviewed peaks. Published tables retain
the analysis and source names in metadata. The internal metrics table contains
exactly one row per X/Y pixel. Peak identity follows the reviewed template order
(`peak_1`, `peak_2`, and so on), not the prominence rank at each pixel.
Available map columns include:

- fitted `peak_N_intensity`, signed integrated `peak_N_area`, fitted
  `peak_N_position`, numerical `peak_N_fwhm`, and half-width
  `peak_N_asymmetry`;
- local `peak_N_snr`, detected position, model name, every native model parameter,
  and the covariance-derived standard error for each fitted parameter;
- standardized position/intensity/area/FWHM/asymmetry standard-error columns where
  that uncertainty is directly available;
- `fit_r_squared`, `fit_rmse`, `fit_mae`, `fit_aic`, `fit_bic`, convergence,
  evaluation count, robust noise estimate, and baseline minimum/mean/maximum; and
- numeric `fit_success` plus text status/error fields. Failed pixels remain in
  their spatial row with NaN result cells, preserving the coordinate grid.

The dedicated viewer draws these results directly. For further customization,
export **Parameter maps and fit quality**, then open **2D Maps > Interpolated
Heatmap** (or a contour subtype), choose `X` and `Y`, and select, for example,
`peak_1_area`, `peak_1_position`, `peak_1_asymmetry`, or `fit_rmse` as Z. RMSE/MAE
describe the complete overlapping fit; per-parameter standard errors quantify
individual fitted-parameter uncertainty. A derived area or numerical FWHM may
have no direct standard error when it is not a native model parameter, in which
case its standard-error cell is intentionally blank/NaN rather than estimated
without a defensible propagation model.

Batch and map execution currently runs sequentially with a cancellable progress
dialog. The shared background-worker/parallel implementation and advanced
per-parameter bound/fixed/tied editing remain roadmap work.

---

## 10. Statistics Workbench

Choose **Analysis > Statistics...**. Select an operation, its primary/secondary/group inputs, output name, target sheets, column-binding mode, and optional companion plot. Numeric operations ignore blanks, non-numeric values, and infinities after validating explicit metadata.

### Single-column operations

- Complete report.
- Descriptive summary: count, missing count, mean, median, standard deviation, variance, SEM, min, max, range, and coefficient of variation.
- Quantiles and percentiles.
- Distribution shape: skewness and kurtosis.
- Normality tests: Shapiro-Wilk, D'Agostino-Pearson, Jarque-Bera, and Anderson-Darling.
- Outlier diagnostics using Z-score and IQR fences.
- Mean confidence interval.
- Z-score result series.
- Cumulative statistics result series.

### Two-column operations

Two-column operations can reuse one secondary column for several primary columns or pair equal-sized selections by order. Paired analyses align rows before dropping incomplete pairs.

- Complete comparison report and pair summary.
- Pearson, Spearman, and Kendall correlations.
- Covariance matrix values.
- Linear regression.
- Error metrics: MAE, RMSE, mean error, and R-squared against the primary column.
- Bland-Altman agreement.
- Paired t-test and Wilcoxon signed-rank.
- Welch independent t-test, Mann-Whitney U, and two-sample Kolmogorov-Smirnov.
- Levene and Bartlett variance tests.

### Multiple-column operations

Select two or more columns from the primary sheet:

- Complete multi-column report.
- Descriptive summary.
- Pairwise correlation matrix tests.
- Covariance matrix values.
- Principal component analysis with eigenvalues, explained variance, loadings, and score rows.

### Grouped operations

Choose one or more primary numeric columns and exactly one group/factor column, which may come from another sheet:

- Complete grouped report.
- Descriptive summary by group.
- Assumption checks.
- One-way ANOVA.
- Kruskal-Wallis.
- Tukey HSD post-hoc comparisons.
- Pairwise Mann-Whitney comparisons with Holm-Bonferroni adjustment.

### Companion plots

Available choices depend on operation scope:

| Scope | Plot choices |
| --- | --- |
| Single | Auto, histogram + normal curve, box, violin; Z-score/cumulative operations can also plot the result series |
| Pair | Auto, scatter, scatter + regression line, comparison box, comparison violin, Bland-Altman |
| Multi | Auto, selected-column box/violin; correlation heatmap for correlation/complete reports; PCA explained variance for PCA/complete reports |
| Group | Auto, box by group, violin by group |

Batch statistics creates long summary results and, when applicable, a wide summary dataset. At most one companion plot is queued for a batch run so a large batch does not replace the plot repeatedly.

---

## 11. Curve Fitting and Custom Models

### Standard curve fitting

Choose **Analysis > Curve Fit...** (`Ctrl+Shift+C`).

1. Select one X column and one or more Y columns.
2. Select a model category, model, and optimizer.
3. Edit each parameter's initial value, optional lower/upper bounds, and Fixed checkbox.
4. Configure uncertainty, confidence, residual, and output options.
5. Select target sheets and column matching.
6. Confirm the batch preview and run.

### Built-in models

The Category control keeps the 66 built-in functions navigable. **All models** is also available when you want the original flat view.

| Category | Included models |
|---|---|
| Polynomial | Constant, linear, quadratic, cubic, quartic, and quintic |
| Exponential & decay | Exponential growth, one/two/three-component decay, exponential association, and stretched exponential |
| Growth & sigmoidal | Four- and five-parameter logistic, Gompertz, Richards, Boltzmann, Hill sigmoid, and Weibull saturation |
| Peak - symmetric | Gaussian, Lorentzian, exact Voigt, pseudo-Voigt, Pearson VII, sech-squared, and Laplace |
| Peak - asymmetric | Split Gaussian, split Lorentzian, exponentially modified Gaussian, log-normal, Fraser-Suzuki, Doniach-Sunjic, and Fano resonance |
| Transition & waveform | Error-function and arctangent steps, smooth rectangular pulse, sine, cosine, damped sine/cosine, sine-squared, and two-harmonic Fourier series |
| Power, logarithmic & rational | Power law, shifted logarithm, shifted reciprocal, and first-order rational |
| Binding & kinetics | Michaelis-Menten, Hill saturation, substrate inhibition, and one-/two-site binding |
| Rheology | Bingham, Herschel-Bulkley, Cross, and Carreau |
| Probability distributions | Normal, gamma, Weibull, and log-normal PDFs plus Gaussian and Weibull CDFs |
| Special & physical | Bessel J/Y, Heidler impulse, Arrhenius, and wavelength-domain Planck spectrum |
| Custom | Project-defined safe expression models |

The dialog shows the selected category description, equation, parameter order, and static defaults. Width conventions are named explicitly: Gaussian `sigma` is a standard deviation and Lorentzian `gamma` is a half width at half maximum. The exact Voigt uses both conventions. The EMG uses area scaling; its `center` is the mean of the underlying Gaussian component. Planck expects wavelength in metres and Arrhenius expects absolute temperature with `activation_over_R` in kelvin.

### Optimizers and parameter constraints

- **Levenberg-Marquardt** is suitable for unconstrained least squares.
- **Trust Region Reflective** is the default and supports bounds.
- **Dogbox** supports bounded least squares.
- **Orthogonal Distance Regression** supports uncertainty in both X and Y.

Blank bounds are unbounded. Built-in models prefill recommended domain bounds for scale/width/time parameters and bounded fractions such as pseudo-Voigt `eta`; these remain editable. Clear all finite bounds before choosing Levenberg-Marquardt, which only supports unconstrained fitting. Fixed parameters remain at their initial values. At least one parameter must remain free.

### Uncertainty and weighting

- Select an optional X weight/sigma column.
- Select zero, one, or one-per-Y Y weight/sigma columns.
- Choose **Sigma / standard deviation** or **Weight (larger = stronger)**.
- **Treat sigma as absolute** controls covariance scaling.

Selecting an X uncertainty column automatically switches to ODR and locks the optimizer control. Error/sigma values must be positive and finite where used.

### Outputs and report

Configure:

- Confidence band on/off and confidence percentage, 50.0-99.9%.
- Number of generated fit-curve points, 10-10,000.
- Result sheet name.
- Residual sheet on/off and name.
- Residual plot on the right Y axis.
- Optional long-format parameter covariance/correlation sheet.

The Fit Report includes model/method, parameter estimates, fixed/free state, bounds, standard errors, covariance, R-squared, adjusted R-squared, RMSE, MAE, residual mean/standard deviation, point counts, and warnings. Successful immediate plotting queues raw data, fitted curve, optional confidence band, and optional residuals.

### Custom fit models

Choose **Analysis > Custom Fit Models...** to **Add**, **Edit**, **Duplicate**, or **Remove** project-scoped models.

A custom model defines:

- A unique name.
- An expression using `x` as the independent variable.
- Comma-separated parameter names.
- One default initial value per parameter.

Example:

```python
amplitude * np.exp(-x / tau) + offset
```

Parameter names must be unique Python identifiers, cannot be `x`, and cannot conflict with built-in model names. The validator exposes a curated selection of NumPy plus `scipy.special`, `scipy.signal`, `scipy.stats`, and `scipy.integrate`; imports, file access, arbitrary attributes, and `^` powers are blocked. Click **Validate** before saving when you want an explicit check.

Custom models appear in Curve Fit as `Custom: model name` and are stored inside the `.jasc` project.

---

## 12. Plotting and the Plot Inspector

The Plot tab holds one editable plot draft. A plot can contain multiple queued series, including series whose X, Y, and Z values come from different datasets.

### Build and edit a plot

1. Open the **Plot** tab. Click **New Plot** first if you want to replace the current draft; JASC asks what to do with unsaved work.
2. In **Series**, choose a plot family and subtype.
3. Configure the data mappings and type-specific appearance.
4. Click **Add Series**. The series is queued and the plot is rendered.
5. To add another series, click **New Series**, adjust the retained mappings and appearance, and click **Add Series** again.

Selecting a queued series switches the editor to **Update Series** mode. Mapping, subtype, and appearance edits are staged: they do not alter the queue or canvas, even when **Live preview** is enabled. The status line identifies unapplied edits. Click **Update Series** to commit them or **Revert Edits** to reload the queued values. Until you choose one, JASC keeps that series selected rather than silently losing the staged edits, and it will not save the plot. Use **Remove Selected** or **Clear All** to edit the queue. Right-click the queue for New, Update, Revert, Duplicate, Remove, and Clear actions.

### Edit directly on the plot

Rendered data, text, and axes can be edited without navigating to the lateral inspector. Double-click:

- A **plotted line, marker, bar, filled region, distribution, or composition cell** to edit that committed series. The focused dialog provides compatible graph subtypes, series name and legend inclusion, continuous/dashed/dotted/dash-dot line patterns, line width, symbol shape and size, automatic or custom colour, fill opacity, and bar width. For example, an XY line can be changed directly to scatter, line + markers, errorbar, bar, horizontal bar, or area.
- A **2D or spectral map** to open its map-specific Colour & Grid, Contours, Validity, and Extrema editor.
- The **plot title** to change its text.
- An **X, left-Y, or right-Y axis label**, tick-label area, or axis line to edit its label, label size, tick-number size, linear/log scale, optional minimum/maximum, and the shared grid state.
- A **legend entry label** to rename that committed series or include/exclude it from the legend.
- The **legend title, frame, handle area, or other empty legend space** to edit visibility, position, text/title sizes, title, columns, frame and opacity, marker scale, handle length, and locator/confidence-band inclusion.

Accepted changes redraw immediately and update the corresponding lateral Plot Inspector controls; the inspector remains available for the same settings. Direct series and legend-entry edits respect staged-series protection: use **Update Series** or **Revert Edits** first if the selected series has unapplied changes. Hovering over the canvas also shows a reminder about the available double-click targets.

### Plot types and mappings

| Family | Subtype | Data mapping and special controls |
| --- | --- | --- |
| XY / Categorical | Line | X and Y; line style/width; optional left/right Y axis |
| XY / Categorical | Scatter | X and Y; marker and size; optional left/right Y axis |
| XY / Categorical | Line + Markers | X and Y; line and marker controls; optional left/right Y axis |
| XY / Categorical | Errorbar | X/Y plus optional X-error and Y-error columns |
| XY / Categorical | Vertical Bar | Numeric positions or text categories plus values; bar width and fill alpha |
| XY / Categorical | Horizontal Bar | Numeric positions or text categories plus values; bar width and fill alpha |
| XY / Categorical | Area | X/Y filled area, line controls, fill alpha |
| Distribution | Histogram | One value column, 1-1,000 bins, density, cumulative, fill alpha |
| Distribution | Box Plot | One or more value columns; mean, median, outlier controls |
| Distribution | Violin Plot | One or more value columns; mean, median, extrema, statistic-line width |
| Composition | Pie | Label column plus positive value column |
| Composition | Donut | Label column plus positive value column |
| Composition | Voronoi Composition | Label/value columns and Circular, Rectangular, or Polygonal container |
| 2D Maps | Interpolated Heatmap | X/Y/Z coordinates; native complete grid or interpolated scattered grid |
| 2D Maps | Contour | X/Y/Z coordinates; configurable levels, labels, line style, and normalization |
| 2D Maps | Filled Contour | X/Y/Z coordinates; configurable fill levels and optional contour overlay |
| Spectra Plot | Spectral Heatmap | Long-form X/Y/Raman-shift-or-frequency/intensity data; target center; closest or linear spectral sampling |
| Spectra Plot | Spectral Contour | Long-form spectral-map data rendered as contour lines at the target center |
| Spectra Plot | Filled Spectral Contour | Long-form spectral-map data rendered as filled contours at the target center |

2D-map interpolation choices are **Linear**, **Cubic spline**, and **Piecewise cubic**. **Automatic** rendering preserves a complete Cartesian input grid without resampling and otherwise interpolates onto the selected resolution; users may explicitly require Native or Interpolated mode. The **Palette** selector applies the supplied Matplotlib colour maps and is retained in saved plots. **Colour-bar label** sets a custom intensity/Z label; leaving it blank uses the selected value column automatically. The rendered colour-bar label can also be edited directly by double-clicking it.

Select a committed map and click **Map Details...**, or double-click the map, for four groups of saved controls:

- **Colour & Grid**: automatic, manual, or robust-percentile limits; linear, logarithmic, symmetric-log, or center-aware diverging normalization; missing/under/over colours; opacity; and automatic or equal-unit aspect.
- **Contours**: level count, fixed interval, or explicit numeric levels; labels and number format; line colour/width/style; and an optional line overlay on filled contours.
- **Validity**: measured data points, Delaunay triangulation, convex-hull boundary, and masking outside that measured boundary.
- **Extrema**: global and local maxima/minima, prominence and physical-separation filters, label count/content, and either measured or rendered-grid values. Labels explicitly state **measured** or **interpolated** so interpolation overshoot is not presented as an observation.

Click **Analyse Map...** to create an ordinary reusable worksheet containing the rendered X/Y/Z grid, a closest horizontal or vertical profile, an arbitrary point-to-point profile, rectangular ROI statistics, or contour vertices and enclosed areas. ROI output includes cell count, mean, median, standard deviation, extrema with coordinates, and a grid-spacing-weighted integral. The repository includes analytically defined regular-grid and irregular point-cloud examples under `Test_Data`.

Horizontal, vertical, and arbitrary line cuts also create named, editable plots under **Workspace > Plots**, backed by the generated profile worksheet. They are saved with the project. The source map stays active, so you can create several cuts before opening their plots. Use **Pick Cut Line...** to click the start and end directly on an ordinary or spectral map, then confirm the endpoints and sample count.

Peak/Raman result maps provide **Map Cuts...** for horizontal, vertical, or arbitrary cuts of the currently selected parameter or quality metric, and **Pick Cut Line...** for mouse-picked endpoints. These cuts respect **Hide failed pixels** and publish only the cut worksheet and saved plot, without exporting the complete internal result tables. Right-click or press Esc to cancel picking; changing the metric or analysis also cancels it. Arbitrary-line values are spatially interpolated, rather than additional measured pixels.


A dedicated row above the canvas follows the mouse and reports `x`, `y`, and interpolated Z/intensity for ordinary and spectral maps; masked interpolation edges fall back to the closest measured map pixel. Maps require numeric Z values and at least three distinct non-collinear X/Y coordinate points. Rendering failures appear as a message on the canvas instead of a blank plot.

For an imported hyperspectral map, choose **Spectra Plot** and select its worksheet. JASC automatically proposes `X`, `Y`, `Raman Shift` (or a frequency/wavenumber equivalent), and `Intensity`. Enter the target center and choose **Closest measured shift** to take the nearest available spectral sample independently at every pixel, or **Linear spectral interpolation** to interpolate between the two surrounding samples in every pixel spectrum. The separate 2D-map interpolation control then determines how those sampled XY intensities are drawn on the spatial grid. Target center, spectral column, sampling method, spatial interpolation, and grid resolution are retained in saved plots.

Composition plots cannot be mixed with XY series, and only one composition series can render at a time. Pie/donut require positive values. Voronoi regions are value-weighted approximations and automatically reduce label density for large category counts.

### Common series appearance

Depending on plot type, the inspector exposes:

- Custom legend label and per-series **Show this series in legend**.
- Solid, dashed, dotted, dash-dot, or no line.
- Circle, square, triangle, diamond, cross, or dot markers.
- Automatic or named colors.
- Line width, marker size, fill alpha, and bar width.
- Left or right Y-axis assignment.

Column roles preselect likely mappings. Axis-label fields prefill from Long Name and Unit metadata while they remain blank or automatically managed; manually typed labels are not overwritten.

### Axes, style, and figure

The **Axes** tab controls:

- Title; X, left-Y, and right-Y labels.
- Per-axis label and tick-number sizes for X, left Y, and right Y. **Style default** leaves typography under the selected Matplotlib/SciencePlots style; any positive point size overrides it on the live canvas and exported output.
- Linear or log scale independently on X, left Y, and right Y.
- Optional minimum/maximum for each axis.
- Grid visibility.
- Export size basis plus width (3-20 inches) and height (2-15 inches). Choose **Full exported image** to size the complete output, or **Plotting area (axes box)** to size only the inner rectangle bounded by the X and Y axes.
- Style preset: Matplotlib default, Science, IEEE, Nature, or Notebook.
- Color cycle: Default, Bright, or High visibility.
- LaTeX text on/off.
- Custom comma-separated SciencePlots style tokens.

Log ranges must be positive. Invalid or reversed ranges mark the preview out of date without interrupting typing with modal dialogs. SciencePlots styles require the dependency in `requirements.txt`; LaTeX rendering also depends on a working external LaTeX installation.

The interactive plot always expands to the available canvas. Applying a style or changing export width, height, or size basis does not resize the on-screen canvas. Physical dimensions are applied only by the toolbar export action. In plotting-area mode, JASC calculates the larger complete figure required to keep the requested axes-box dimensions while retaining titles, tick labels, margins, color bars, and outside legends.

### Legend

The **Legend** tab controls:

- Visibility.
- Automatic or standard inside positions.
- Outside right, outside top, or outside bottom placement with reserved export space.
- Text size, optional title, and title size.
- Column count.
- Frame visibility and opacity.
- Marker scale and handle length.
- Whether locator markers and confidence bands appear.

Entries follow queued-series order across both Y axes, and duplicate labels are removed.

### Live preview and Refresh Plot

**Live preview** is off by default. Axes, Legend, and style changes mark the canvas out of date; click **Refresh Plot** when ready. Enabling Live preview redraws those plot-wide changes automatically after a short debounce. Export-size changes are stored without redrawing because they affect saved files only. Series edits always remain staged until **Add Series** or **Update Series** is clicked, which avoids accidental queue changes while experimenting with mappings or appearance. The preview indicator reports current, pending, out-of-date, invalid, or failed state.

### Data locators

Open **Locator**, select a queued series, and choose a lookup:

- **Find Y from X** interpolates Y on an ordinary XY series.
- **Find X from Y** finds every piecewise-linear crossing on an ordinary XY series.
- Surface plots use entered X and Y to interpolate Z.

Choose marker shape, size, and color, then click **Add Locator**. Located values appear in the list and on the correct left/right axis. Right-click the located-items list to add, remove, or clear locators. Non-monotonic curves can return several X crossings; repeated shared vertices are deduplicated. A horizontal segment at the requested Y is reported as ambiguous instead of returning an arbitrary X.

### Matplotlib canvas toolbar

Use the embedded Matplotlib toolbar for home/reset, back/forward, pan, zoom, subplot configuration where offered, copying, and saving the rendered figure. **Copy** places the current on-screen canvas image on the system clipboard without applying export dimensions. The same command is available as the top-row **Copy Plot** button and as **Plot > Copy Current Plot to Clipboard** (`Ctrl+Alt+C`). The save action applies the configured full-image or plotting-area physical size only for export, then restores the responsive canvas. Both operations produce static images; neither saves editable JASC plot state.

### Saved plots and unsaved drafts

- **New / Empty Plot** is the default unsaved workspace entry.
- Use the Plot menu, top-row buttons, or saved-plot right-click menu to create, save, load, duplicate, and remove plot definitions.
- **Duplicate Saved Plot** creates a deep copy named `Plot Copy`, `Plot Copy (2)`, and so on, then loads that copy for editing. Series, mappings, locators, axes, legend, style, export geometry, and type-specific settings are retained. Editing or saving the copy does not alter the source definition. If the current draft has unsaved changes, the normal Save/Discard/Cancel protection appears first.
- Saving under an existing name asks before replacement.
- Starting or loading another plot while the current draft has unsaved changes offers **Save**, **Discard**, and **Cancel**. Resolve any staged series edits with **Update Series** or **Revert Edits** before saving.
- Analysis-generated plots detach from a previously loaded saved plot so they cannot silently overwrite it.

Saved definitions preserve queued series, locators, mappings, axis labels/scales/ranges/typography, legend, styles, figure dimensions, and type-specific settings. Save the overall `.jasc` project to persist them between application sessions.

---

## 13. Batch Processing

Batch-capable workbenches are:

- Apply Formula.
- Derivative and Integral.
- Smoothing.
- FFT and Inverse FFT.
- Interpolation.
- Statistics.
- Curve Fit.

### Standard batch workflow

1. Configure the operation using the current sheet as the reference.
2. Select one or more entries in **Apply to sheets**.
3. Select **Exact name** or **Column position** matching.
4. Configure output names/conflict behavior where offered.
5. Confirm the operation dialog.
6. Review **Batch Preflight Preview**, including resolved inputs, outputs, status, and error details.
7. Click **Run Batch**.
8. Monitor the cancelable progress dialog.

Preflight rows marked failed or blocked explain incompatible columns, invalid mappings, or output conflicts before execution. Compatible jobs can still run when other rows fail, depending on the operation's plan.

### Column binding

- **Exact name** resolves each requested header literally on every target sheet. Use it for standardized worksheets.
- **Column position** treats the reference mapping as `col1`, `col2`, and so forth and resolves the same positions on every target sheet. Use it for repeated exports whose headers differ but layouts match.

Column roles influence initial dialog choices but do not replace batch binding.

### Output naming and collision policies

Where the dialog supports them:

- `{source}` expands to the source sheet name.
- `{column}` expands to the processed signal/value column.
- **Create unique** protects existing columns by generating a noncolliding name.
- **Stop and warn** blocks the colliding output.
- **Overwrite/update** permits replacement after the preflight makes the target explicit.

Dataset-producing operations also create unique names when a requested result name already exists.

### Multiple input columns

- Derivative, Integral, Smoothing, FFT, Statistics, and Curve Fit can process multiple selected signal/value columns.
- Inverse FFT accepts zero, one shared, or one-per-real imaginary column.
- Curve Fit accepts zero, one shared, or one-per-Y sigma/weight column.
- Pair statistics accept one shared secondary column or one-per-primary secondary columns.
- Interpolation accepts multiple value columns.

### Parallel formula execution

Apply Formula uniquely exposes **Auto**, **Sequential**, and **Parallel processes** plus maximum workers. Auto decides whether parallel processing is worthwhile for the headless target sheets. The visible current sheet may be handled safely in the GUI path while compatible background jobs use worker processes.

### Progress, cancellation, and summaries

Batch operations display a modal progress dialog and check for cancellation between jobs/results. A cancellation does not undo jobs already completed.

Multi-job runs create operation-specific summary datasets such as:

- `_formula_batch_summary`
- `_derivative_batch_summary` / `_integral_batch_summary`
- `_smoothing_batch_summary`
- `_fft_batch_summary` / `_ifft_batch_summary`
- `_interpolation_batch_summary`
- `_statistics_batch_summary` and sometimes `_statistics_batch_wide_summary`
- `_fit_batch_summary`

Summaries include source sheets/columns, resolved mappings, requested outputs, status/errors, execution details, and operation-specific metrics.

---

## 14. Export, Persistence, and Large Data

### Export a dataset

Select a dataset and choose **File > Export Dataset...** (`Ctrl+E`). Choose CSV or tab-delimited text. JASC exports column headers and values without the pandas row index.

Dataset export does not include formulas, column metadata, saved plots, or custom models. Save a `.jasc` project when those need to be preserved.

### Export a plot

Use the save button in the Matplotlib toolbar. The available raster/vector formats depend on Matplotlib. Outside legends reserve figure space in the exported output. To reuse the current screen rendering quickly, use **Copy Plot**, the toolbar **Copy** action, or `Ctrl+Alt+C`; clipboard copy uses the live canvas size, while file export uses the configured physical dimensions.

An exported image is static. Save the plot definition and project when later editing is required.

### Large-data thresholds and behavior

- Source files of at least 100 MiB trigger a pre-import warning.
- A worksheet is flagged as large at 2,000,000 cells or an estimated 250 MiB of DataFrame memory.
- Column sizing uses at most 100 sampled rows normally and 25 rows above the 250,000-cell responsiveness threshold.
- Clipboard parsing, worksheet growth, range fill, and rectangular assignment use block-oriented operations. Right-click menu availability checks inspect compact Qt selection ranges rather than materializing every selected cell, so selecting a large table does not make menu opening proportional to its cell count.
- `.jasc` worksheet CSV entries stream from the ZIP archive during project load.
- Undo/redo retains at most 20 snapshots and approximately 256 MiB per stack.

Ordinary editable worksheets remain in Pandas memory. Text inspection/parsing runs in the background; Excel and project I/O still run synchronously. Autosave and recovery are not implemented.

### Open a disk-backed large dataset

Choose **File > Open Large Dataset...** or **Workspace > Large Data > Open Large Dataset**. Select a regular comma-, semicolon-, tab-, or pipe-separated `.csv`, `.dat`, or `.txt` table, or an existing `.parquet` file. Text files use the usual import preflight and parser options. Large-data mode currently rejects whitespace-separated tables and vendor-specific spectrum/map layouts; use ordinary **Import Data** for these.

JASC creates a private Parquet snapshot on disk through Polars rather than retaining a complete source DataFrame. Text values remain strings, including numeric-looking values, identifiers with leading zeros, and late mixed tokens. Number-format choices are retained as provenance; this mode does not perform whole-column numeric inference. Existing Parquet types are retained. The original file is not modified, and later changes to it do not affect the snapshot.

The central **Large Data** tab is read-only and shows one window of at most **1,000 rows and 32 columns**, with an **8 MiB data-buffer limit**. Oversized windows shrink; a row exceeding the limit produces a controlled error. Column widths are fixed initially. This budget covers the displayed data, not all process memory: workers, Parquet decoders, Qt, and import buffers require additional memory.

- Scroll past the bottom/top edge to load adjacent rows, or use **Previous rows / Next rows**.
- Enter a global, one-based row number and choose **Go to row** to jump directly.
- Use **Previous columns / Next columns** to browse wide tables in bounded column windows.
- The summary and row labels retain positions in the complete source. Copy (`Ctrl+C`) copies only selected cells in the current window.
- Reads run in a worker. Old windows are evicted, rapid requests coalesce, and stale results cannot replace a newer source/window. **Retry** is available after a read failure.
- **Create worksheet from this window** explicitly copies the displayed rows/columns into an ordinary editable worksheet with source-range provenance. This is a subset; analysis on that worksheet covers that subset. Text-import values remain strings; ordinary numeric-string validation is available in the analysis workflows.

Large datasets appear separately from ordinary worksheets, so existing formulas, plotting, batch analysis, and snapshot undo cannot silently operate on a partial source. Full-source filtering, sorting, aggregation controls, reduced plots, and bounded spectrum extraction remain future work; the backend exposes a lazy full-source query boundary for those operations.

Save the project to retain large sources. Projects containing them use version 9 and embed Parquet members; load streams those members back to private disk snapshots. Original source files are not needed to reopen the project. Ordinary-only projects continue to use version 8. Package seals, signatures, and encryption cover the embedded data as usual. Project save/load remains synchronous, so very large packages can pause the interface despite bounded payload memory.

Opening requires temporary disk space for the snapshot and, for text, an intermediate UTF-8 copy. Snapshots are unencrypted files in the operating system's temporary directory while open, including sources loaded from encrypted projects. Removing a source releases its snapshot once any active reader finishes. Import Cancel checks streaming-copy boundaries and rejects pending results; native Polars conversion cancels after that phase finishes. Closing waits safely for active workers.

---

## 15. Troubleshooting and Current Limitations

### JASC does not start

Run from the repository root and verify the active interpreter:

```powershell
python --version
python -m pip install -r requirements.txt
python main.py
```

If `python` is not found, activate the environment where the dependencies were installed or invoke that environment's Python executable directly.

### A CSV/DAT/TXT file parses incorrectly

- Review the preflight row, especially detected metadata rows, header status, and preview values.
- Auto detects comma, semicolon, tab, pipe, and whitespace. If an unusual or inconsistent file is parsed incorrectly, reimport and choose an explicit delimiter.
- Force **First tabular row contains column names** or **No header row** when header inference is wrong.
- Choose a fixed number of leading rows when an instrument preamble cannot be distinguished reliably from the data table.
- Save the source as UTF-8.
- JASC does not currently choose encodings or provide per-file manual overrides inside one batch; split unusually inconsistent files into separate imports when they require different forced rules.

### A numeric operation rejects a column

- Open Column Metadata and confirm it is Auto, Numeric, or Scientific rather than Text.
- Remove or correct non-numeric text in explicitly Numeric/Scientific columns.
- Check for duplicate X values, missing aligned points, or uneven spacing where the selected method requires uniform samples.

### A formula fails

- Use `**`, not `^`, for powers.
- Use `col("Exact Header")` for spaces, punctuation, keywords, or names that conflict with functions.
- Check the Apply Formula Help panel for the curated function list.
- Ensure a vector expression returns exactly one value per worksheet row.

### A fit does not converge

- Use realistic initial guesses.
- Confirm lower bounds are smaller than upper bounds and do not exclude the solution.
- Try Trust Region Reflective or Dogbox for bounded fits.
- Inspect missing, nonfinite, or nonpositive uncertainty values.
- Reduce the number of free parameters or fix known parameters.
- Confirm the model domain is valid for the selected X range, especially log-normal, power-law, Bessel Y, or fractional-power models.

### A 2D map is blank or reports an error

- Choose distinct X, Y, and Z mappings.
- Provide at least three distinct, non-collinear coordinate points.
- Ensure Z is numeric and enough finite points remain after blank removal.
- Try Linear before cubic methods and reduce grid resolution for expensive data.
- Use **Automatic** or **Interpolated grid** when the X/Y points do not form a complete Cartesian grid; **Native regular grid** deliberately rejects missing cells.
- Logarithmic colour normalization requires positive Z values. For signed data, use linear, symmetric-log, or diverging-around-center normalization.
- Ensure custom contour levels contain at least two distinct finite numbers.

### A plot style or LaTeX fails

- Reinstall requirements to provide SciencePlots.
- Disable **Use LaTeX text** if a LaTeX distribution is not installed.
- Remove unsupported tokens from **Custom styles**.

### Current scope limitations

The current version does not provide:

- Excel export, legacy `.xls` import, named/range-only Excel import, database, JSON/XML, HDF5, NetCDF, MATLAB, or instrument-format connectors.
- Encoding selection, arbitrary non-leading row filtering during import, or different forced parser overrides for individual files inside one batch.
- A workbook/folder hierarchy, matrix sheets, rich cell formatting, notes, or dependency/recalculation graphs.
- Multi-condition filters, pivot tables, resampling, date/time tooling, or reusable preparation recipes.
- Multi-panel pages, true 3D plots, polar/ternary plots, annotation objects, or general graph templates.
- Global multi-dataset fitting, automated model ranking, peak deconvolution, or surface fitting.
- A scripting console, macro recorder, plugins, autosave/recovery, or installer. Disk-backed large-table browsing is available, but full-source analysis controls, direct large-table editing, and vendor-map disk storage are not yet implemented.

Consult `Roadmap.md` for planned work; roadmap entries are not instructions for currently available features.

---

## 16. Quick Reference

### Recommended end-to-end workflow

1. Import/create data.
2. Assign column names, roles, types, units, and long names.
3. Clean data with non-destructive Data Preparation outputs.
4. Apply formulas or analysis operations, using preflight for batch work.
5. Inspect generated comments and batch summaries.
6. Build an unsaved plot draft, configure axes/legend/locators, and save the plot definition.
7. Export final data/figures as needed.
8. Save the `.jasc` project to retain the editable workspace.

### Output type summary

| Operation | Primary output |
| --- | --- |
| Fill Range / Formula / Derivative / Integral / Smoothing | Column(s) written into target worksheet(s) |
| Data Preparation | New non-destructive dataset |
| FFT / Inverse FFT / Interpolation | New result dataset(s) |
| Statistics | New report/result dataset(s), optional plot |
| Curve Fit | Fit dataset, report, and optional residual/covariance/plot outputs |
| Figure digitizer | New calibrated dataset with diagnostics |
| Plot Inspector | Editable plot draft; optionally saved plot definition |

### Naming tokens

| Token | Expands to | Common locations |
| --- | --- | --- |
| `{source}` | Source worksheet name | FFT/iFFT, interpolation, statistics, fit result sheets |
| `{column}` | Processed Y/signal/value column | Formula/math/smoothing columns and result sheets where supported |

### Metadata role hints

| Role | Typical use |
| --- | --- |
| X | Independent variable, time, horizontal coordinate |
| Y | Dependent signal/value |
| Z | Surface/map value |
| Error | Generic uncertainty fallback |
| X error / Y error | Errorbar uncertainty and explicit fit-uncertainty choices |
| Group | Statistics factor/group default |
| Label | Categorical/composition labels |
| Weight | Semantic hint for an explicitly selected curve-fit weight |

### Safe practices

- Save the project before opening or closing another workspace and before exiting JASC.
- Prefer unique-output policies until a batch preflight has been reviewed.
- Assign explicit Numeric/Text types when automatic inference could be ambiguous.
- Use exact-name batch binding for standardized headers and position binding only when layouts are known to match.
- Leave Live preview off while editing expensive 2D-map settings on large datasets; use **Update Series** and **Refresh Plot** deliberately.
- Treat exported CSV/TXT and figures as deliverables; treat `.jasc` as the editable project source.
