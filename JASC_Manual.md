# JASC Data Processor - Comprehensive User Manual

*Version 0.1.0 - reviewed against the application source on 24 August 2026*

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
- The packages in `requirements.txt`: PySide6, pandas, NumPy, Matplotlib, SciPy, odrpack, SciencePlots, and statsmodels.

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
| File | Open Project, Save Project, Save Project As, New Blank Sheet, Close Project, Import Data, Import From Figure, Export Dataset, Exit |
| Edit | Undo, Redo, Clear Selected Cell Values, Delete Selected Rows, Delete Selected Columns, Paste Values Transposed |
| View | Navigator/section/inspector visibility and Reset View to Default |
| Data | Duplicate/Rename/Remove Dataset; Add/Insert Row or Column; Resize Sheet; Fill Range; all Data Preparation tools; Column Metadata; Apply Formula |
| Analysis | Derivative, Integral, Smoothing, Interpolation, FFT, Inverse FFT, Statistics, Custom Fit Models, Curve Fit |
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

1. Choose **File > Open Project...** to load a `.jasc` file. Opening a project replaces the current workspace after confirmation.
2. Choose **File > Save Project** to save to the current project path. The first save opens the Save As dialog.
3. Choose **File > Save Project As...** to choose a different path. JASC adds `.jasc` if no suffix is supplied.
4. Choose **File > Close Project** to clear the workspace without closing JASC. This action warns that unsaved changes will be lost.

Save before using **File > Exit** or closing the application window. Project-level automatic save and recovery are not implemented.

### What a `.jasc` project preserves

A project is a ZIP archive containing CSV worksheet payloads and JSON metadata. It preserves:

- Dataset names, values, source paths, and backend labels.
- Column formulas.
- Column roles, value types, precision, units, long names, and comments.
- Operation-provenance comments written by JASC.
- Saved plot definitions, including plot series and appearance settings.
- Project-scoped custom fit models.

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

### Import CSV or TXT data

1. Choose **File > Import Data...** (`Ctrl+I`) or use the toolbar action.
2. Select a `.csv` or `.txt` file.
3. In **Import Options**, choose one delimiter:
   - Comma
   - Semicolon
   - Tab
   - Space / whitespace (one or more whitespace characters)
4. Check **First row contains column names** when row 1 contains headers. Clear it to generate `Column 1`, `Column 2`, and so on.
5. Confirm the import.

The current import dialog does not auto-detect a delimiter or header row, does not select an arbitrary starting row, and always reads text as UTF-8. If decoding fails, convert the source file to UTF-8 before importing.

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
- Numeric `x` and `y` columns.
- `X` and `Y` column roles already assigned.

The sheet is immediately editable in the Data tab. Use Data menu commands to add or insert rows and columns.

### Fill an arithmetic range

Choose **Data > Fill Range...** to populate a sequence. Configure:

- **Target column**: an existing or new column.
- **Start row**: one-based worksheet row.
- **Count**: number of values.
- **Start value** and **Step**.

JASC grows the worksheet if required and writes `start + offset * step`. It marks the output Numeric, assigns the X role when the name is `x`, `time`, or `t`, removes a stale formula from the overwritten column, and records provenance in the column comment.

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

To extract another curve from the same figure without repeating calibration:

1. Enter a distinct dataset name for the completed curve.
2. Click **Save Current Curve & Start New**. JASC stores a snapshot of its rows and provenance, then clears only curve-specific manual points, uncertainty marks, automatic trace, symbol results/template, and ROI marks.
3. Extract the next curve using the same working image, perspective correction, and X/Y calibration. Repeat the save/start action for any additional curves.
4. Leave the last curve in the preview and click **Create Dataset(s)**. Every saved curve and the current curve are imported as separate workspace datasets. If the last curve was already saved and the current extraction is empty, the saved curves are still imported.

The saved-curve status in **Output** lists how many curves are waiting to be imported. Loading another image, applying a new perspective correction, or resetting to the original image changes pixel geometry, so JASC asks for confirmation before clearing saved curves and calibration.

For a single curve, skip **Save Current Curve & Start New** and click **Create Dataset(s)** directly. JASC requires a loaded image, complete four-point calibration, at least one manual, traced, or symbol point, and a dataset name. Each created dataset receives numeric coordinate metadata, X/Y/error roles where appropriate, source/provenance comments, and the image source path.

### 2D colour plot / heatmap workflow

Choose **2D colour plot / heatmap** in the initial figure-type dialog. This workflow learns the palette empirically from the colour bar as it actually appears in the image, rather than assuming a named Matplotlib colour map.

1. Load the image and optionally apply perspective correction.
2. Calibrate X and Y exactly as described above. Reference points may be inside the full data region; the mapping extrapolates beyond them.
3. In **Displayed Colour Scale**, enter the numeric values represented at the two ends and choose **Linear** or **Log10** value normalization. Log10 endpoints must be positive.
4. Click **Pick Low End**, then click the centre of the colour bar at the entered low-value end. Click **Pick High End** and click its high-value end. Endpoints may be horizontal, vertical, diagonal, or reversed in screen direction.
5. Adjust **Bar sample width** if necessary. JASC samples a median stripe across that width along the complete endpoint-to-endpoint segment. **Palette samples** controls its resolution. Click **Rebuild Scale** and inspect the displayed sampled palette.
6. Set the probe **Median patch radius**. A small median patch reduces isolated compression noise, but a large radius can mix neighbouring colours near sharp boundaries.
7. Click **Start Probing**, then click locations in the colour plot. The shared magnifier shows live X, Y, estimated Z, RGB, confidence, and validity. Click **Stop** when finished.
8. In **Output**, inspect the rows. Use **Undo Last**, **Remove Selected**, or **Clear Probes** to clean the result. To preserve this probe set and begin another one with the same image, X/Y calibration, and colour-scale calibration, enter its dataset name and click **Save Current Curve & Start New**. Only the probes are cleared. Repeat as needed, then click **Create Dataset(s)** to import every saved and current probe set as a separate dataset.

Each output row contains calibrated `x`, `y`, and estimated `z`; source pixel coordinates; median red/green/blue values; normalized palette position; CIE Lab colour distance; confidence; ambiguity and validity flags; patch radius; extraction method; and source image. X, Y, and Z metadata roles are assigned automatically. Rows that fail the distance threshold or are ambiguous are deliberately retained so they can be inspected and filtered instead of silently discarded. **Maximum Lab distance** controls the validity cutoff.

> **Accuracy disclaimer:** colour values are estimates from rendered raster pixels. Lossy image compression, anti-aliasing, resizing, overlaid text or contours, transparency, and limited palette resolution introduce inherent error. Always review colour distance, confidence, ambiguity, and validity before scientific use. Prefer an original lossless image and probe away from labels, grid lines, and boundaries when possible.

The current colour workflow supports continuous empirical colour bars and clicked point probes. Discrete/categorical palettes and automatic full-grid reconstruction are not yet implemented.

---

## 6. Editing Worksheets and Column Metadata

### Select and edit cells

- Double-click a cell, enter a value, and press Enter to commit.
- Blank input is stored as a missing value.
- Numeric/Scientific metadata rejects non-numeric text. Text columns preserve entered text.
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

### Undo and redo

Use **Edit > Undo** (`Ctrl+Z`) and **Edit > Redo** (`Ctrl+Y`). History covers cell edits and clearing, worksheet resizing, row/column changes, clipboard pastes, Fill Range, formula writes, metadata/column renames, and current-sheet calculus/smoothing changes where the operation captures editor state.

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

1. Select or type a **Target column**.
2. Choose what happens if the target exists:
   - Create a unique new column.
   - Stop and warn.
   - Overwrite/update the existing column.
3. Enter the expression.
4. Optionally apply only to selected rows. Selected-row mode applies only to the current sheet.
5. Select one or more sheets for a full-column/batch operation.
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
| `row` | One-based row-number series |
| `index` | The pandas index as a series |

Use the dialog's **Insert colN** and **Insert col("Name")** buttons to avoid typing mistakes.

Examples:

```python
col("Voltage (V)") / col("Current (A)")
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
- A scalar result is repeated across the sheet. A vector result must match the worksheet length.
- Numeric/Scientific metadata is validated before downstream math operations.
- Applying a formula stores the expression in project metadata and records it in the target column comment.

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
2. Select a model and optimizer.
3. Edit each parameter's initial value, optional lower/upper bounds, and Fixed checkbox.
4. Configure uncertainty, confidence, residual, and output options.
5. Select target sheets and column matching.
6. Confirm the batch preview and run.

### Built-in models

- Linear, quadratic, and cubic.
- Exponential growth, exponential decay, and double exponential decay.
- Gaussian, asymmetric Gaussian, Lorentzian, and pseudo-Voigt.
- Sine and damped sine.
- Logistic and Gompertz.
- Error-function step.
- Power law.
- Log-normal peak.
- Weibull saturation.
- Heidler impulse.
- Bessel J and Bessel Y.
- Stretched exponential.

The dialog shows the selected equation, parameter order, and static defaults.

### Optimizers and parameter constraints

- **Levenberg-Marquardt** is suitable for unconstrained least squares.
- **Trust Region Reflective** is the default and supports bounds.
- **Dogbox** supports bounded least squares.
- **Orthogonal Distance Regression** supports uncertainty in both X and Y.

Blank bounds are unbounded. Fixed parameters remain at their initial values. At least one parameter must remain free.

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

- A **plotted line, marker, bar, filled region, distribution, composition cell, or 2D map** to edit that committed series. The focused dialog provides compatible graph subtypes, series name and legend inclusion, continuous/dashed/dotted/dash-dot line patterns, line width, symbol shape and size, automatic or custom colour, fill opacity, and bar width. For example, an XY line can be changed directly to scatter, line + markers, errorbar, bar, horizontal bar, or area.
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
| 2D Maps | Interpolated Heatmap | X/Y/Z scattered coordinates, interpolation method, grid resolution |
| 2D Maps | Contour | X/Y/Z scattered coordinates, interpolation method, grid resolution |
| 2D Maps | Filled Contour | X/Y/Z scattered coordinates, interpolation method, grid resolution |

2D-map interpolation choices are **Linear**, **Cubic spline**, and **Piecewise cubic**. Maps require numeric Z values and at least three distinct non-collinear X/Y coordinate points. Rendering failures appear as a message on the canvas instead of a blank plot.

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

All datasets are currently held in memory by pandas. CSV/TXT/Excel import and much project parsing still run synchronously, so very large files can pause the interface even after confirmation. Background import, paged/out-of-core datasets, autosave, and recovery are not implemented.

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

### A CSV/TXT file parses incorrectly

- Reimport and choose the correct delimiter.
- Check or clear **First row contains column names** as appropriate.
- Save the source as UTF-8.
- JASC does not currently auto-detect delimiters/headers, skip arbitrary leading rows, preview imports, or choose encodings.

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

### A plot style or LaTeX fails

- Reinstall requirements to provide SciencePlots.
- Disable **Use LaTeX text** if a LaTeX distribution is not installed.
- Remove unsupported tokens from **Custom styles**.

### Current scope limitations

The current version does not provide:

- Excel export, legacy `.xls` import, named/range-only Excel import, database, JSON/XML, HDF5, NetCDF, MATLAB, or instrument-format connectors.
- Import preview, arbitrary header/start rows, encoding selection, or batch file import.
- A workbook/folder hierarchy, matrix sheets, rich cell formatting, notes, or dependency/recalculation graphs.
- Multi-condition filters, pivot tables, resampling, date/time tooling, or reusable preparation recipes.
- Multi-panel pages, true 3D plots, polar/ternary plots, annotation objects, or general graph templates.
- Global multi-dataset fitting, automated model ranking, peak deconvolution, or surface fitting.
- A scripting console, macro recorder, plugins, autosave/recovery, installer, or true out-of-core data backend.

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
