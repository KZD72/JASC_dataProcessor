# Plot Inspector Final-State Review

Date: 2026-08-17

## Outcome

The Plot Inspector has a capable plotting foundation, but it is not yet in a final, publication-oriented state. The next iteration should not be implemented as a flat addition of more controls to the existing Axes form. The durable path is to formalize plot appearance state, make editing behavior consistent, then add typography, legend, axes/grid, and plot-type-specific controls through focused inspector sections.

This review intentionally scopes the polish pass to the current single-canvas plot editor. Multi-panel graph pages, annotations, new graph families, reusable data-independent graph templates, and export queues remain separate roadmap stages.

## Current Implementation Map

| Area | Current behavior | Persistence/rendering | Main limitation |
| --- | --- | --- | --- |
| Series | Family/subtype, dataset/column mapping, errors, left/right Y axis, label, line, marker, color, and some type-specific fields | Stored in a 30-field `PlotSeries` dataclass and rendered by `PlotCanvas` | One long dynamic form; changes can be silently lost unless **Update Series** is clicked |
| Axes | Title, three labels, linear/log scales, optional ranges, style preset/cycle, LaTeX, grid, legend visibility/location, figure width/height | 22 flat settings are saved in plot-state version 2 | Typography, ticks, spines, grid details, aspect, formatting, DPI, backgrounds, and layout are absent |
| Legend | Visible and one Matplotlib location string | Left/right handles are combined through one `Axes.legend()` call | No text size, title, columns, frame, opacity, item inclusion/order, outside placement, or spacing controls |
| Locator | Forward/inverse/surface lookup, target series, marker, size, and color | Saved and rendered; target is a series list index | No edit action; reordering series would invalidate index-based references |
| Styles | Matplotlib/SciencePlots preset, cycle, LaTeX flag, and raw custom style tokens | Applied through `matplotlib.style.context()` | Invalid tokens fail at render time; precedence between preset and explicit future controls is not defined in the model |
| Maps/composition | Interpolation/grid/container controls | Several visual choices are hard-coded in the renderer | Colormap, colorbar, levels, value range, pie label/percentage behavior, and legend behavior are unavailable |

Measured codebase signals:

- `PlotTab` is about 2,041 lines with 85 methods.
- `PlotCanvas` is about 1,865 lines with 50 methods.
- Global plot settings are a flat dictionary; `PlotSeries` has 30 fields.
- `models.plot_types` contains useful descriptions, but the inspector exposes no tooltips or inline plot-type help.
- Current automated coverage exercises locator deserialization and a few main-window lifecycle paths, but not full plot-state round trips, legend rendering, control visibility for every plot type, or appearance rendering.

## Highest-Priority Findings

### 1. Editing behavior is inconsistent

Three different interaction contracts are mixed:

- Series fields require **Add Series** or **Update Series**.
- Style preset changes redraw immediately.
- Most axes, legend, and figure fields do nothing until **Plot** is clicked.

The most serious consequence is that a user can select a series, change its appearance, select another series, and lose the uncommitted changes without a warning.

Final-state contract:

- Maintain a checked **Auto preview** option by default.
- Debounce redraws by roughly 150-250 ms so spin boxes and text edits do not trigger render storms.
- Apply global appearance changes directly to plot state.
- Apply selected-series appearance changes directly to that series when Auto preview is enabled.
- Keep an explicit **Apply** button for expensive maps/large datasets and show a visible `Preview out of date` indicator when automatic rendering is paused.
- Provide **Revert section** and **Reset plot appearance** actions.

### 2. Appearance state needs a typed boundary

Adding legend and typography fields to the existing 22-key dictionary would make `PlotTab`, persistence, validation, and `PlotCanvas.plot_series()` increasingly brittle.

Recommended internal model in `models/plot_state.py`:

- `PlotDefinition`
- `FigureSettings`
- `TypographySettings`
- `AxisSettings` for X, left Y, and right Y
- `GridSettings`
- `LegendSettings`
- Existing `PlotSeries`, followed by a later nested `SeriesAppearance` only if useful

Each type should provide validated defaults plus `from_state()` and `to_state()` methods. The project container can continue storing ordinary JSON dictionaries.

Use plot-state version 3 with a migration from the current flat version-2 settings. A project-format version bump is not intrinsically required because project I/O already stores plot state opaquely, but legacy and malformed plot-state tests are required.

Define style precedence explicitly:

1. Application defaults
2. Matplotlib/SciencePlots preset
3. Saved explicit figure/axes/legend overrides
4. Per-series explicit overrides

An `Auto`/unset value must remain distinguishable from an explicit value so presets can still work.

### 3. The inspector information architecture is too dense

The current inspector has a minimum content width of 440 px and places the queue below a long form. On the default 1,100 px window this materially reduces the canvas and makes series selection/editing require unnecessary scrolling.

Recommended top-level sections:

1. **Series**
2. **Axes**
3. **Legend**
4. **Figure**
5. **Locate**

Series should place the plotted-series list first, with a compact toolbar for Add, Duplicate, Remove, Move Up, and Move Down. Below it, use collapsible groups for **Data mapping**, **Appearance**, and **Type options**. The selected plot type's existing description should be shown as short inline help.

The inspector should work around 340-380 px wide, remember its width and selected section as application UI preferences, and keep project plot state separate from those preferences.

### 4. Legend support is well below the rest of the plotting feature set

The first visible implementation slice should introduce a dedicated Legend section with:

- Show legend
- Location presets, including outside-right, outside-top, and outside-bottom
- Optional custom anchor X/Y
- Text size in points
- Optional title and title size
- Column count
- Frame visibility
- Frame/background color and opacity
- Border color and width
- Marker scale and handle length
- Label, row, and column spacing
- Include/exclude locators
- Include confidence bands separately or group them with their parent series
- Per-series **Show in legend**
- Series reordering, which becomes the default legend order

Legend labels should be deduplicated deterministically. Combined left/right-axis items must preserve explicit series order rather than simply appending all right-axis handles. Composition charts must either use this legend model or clearly switch to a composition-specific label mode.

Outside legends need explicit layout handling because the canvas deliberately disables Matplotlib layout engines. The renderer should reserve margins or use a figure-level legend; otherwise toolbar exports can clip the legend.

### 5. Publication typography and axes controls are missing

Figure/Typography controls:

- Font family with an `Inherit from style` default
- Base font size
- Title size and weight
- Axis-label size and weight
- Tick-label size
- Figure width, height, and DPI
- Figure and axes background colors
- Layout margins or a safe `Auto margins` mode
- Optional fixed/equal/data aspect ratio

Per-axis controls:

- Label, scale, auto/manual minimum and maximum
- Reverse direction
- Major/minor ticks enabled
- Tick direction, length, and width
- Tick-label rotation
- Numeric formatter: automatic, fixed decimals, scientific, engineering, percentage where appropriate
- Optional major/minor locator spacing
- Spine visibility, color, and width

Grid controls:

- Visible
- Major, minor, or both
- X, Y, or both axes
- Line style, width, color, and opacity

Use checkable **Auto** range controls rather than encoding automatic limits as blank text. Add numeric validators and inline error styling instead of waiting for a modal warning after **Plot**.

### 6. Series appearance is too restrictive

Current color selection is limited to Auto plus six colors. The final inspector should use a theme-aware color button with a swatch, **Auto**, recent colors, and a normal color dialog.

Common series options:

- Visibility
- Show in legend
- Opacity
- Z-order
- Duplicate series
- Reorder series

Line/marker options:

- Line style and width
- Marker shape and size
- Marker face and edge colors
- Marker edge width
- Mark-every-N-points for dense signals

Error bars:

- Error-line width
- Cap size and cap thickness
- Error color and opacity

Bars/area/histograms:

- Fill and edge colors
- Fill opacity
- Edge width
- Baseline
- Histogram bin mode/range and edge styling

Concrete existing mismatch: box/violin plots render with `fill_alpha`, while the fill-opacity control is hidden for those plot types. Violin statistic-line width also depends on `line_width`, while that control is hidden. These controls should be made capability-driven rather than maintained through duplicated hard-coded sets.

### 7. Plot-type-specific controls need completion

Maps:

- Colormap and reverse toggle
- Automatic/manual value minimum and maximum
- Linear/log/symmetric color normalization
- Contour level count or explicit levels
- Filled/line contour styling
- Colorbar visibility, label, position, size, padding, and typography
- Invalid-region/mask color

Composition:

- Label mode: none, names, values, percentages, or combinations
- Percentage precision and threshold
- Legend versus direct labels
- Start angle and direction
- Donut width
- Slice explode and edge styling
- Voronoi label density, font sizing, and geometry refinements already noted in the roadmap

Distributions:

- Width, orientation, notch, whisker rule, and outlier appearance
- Violin bandwidth and half/split presentation when supported
- Fill opacity exposed consistently

These controls belong in each plot type's capability specification so the UI, defaults, validation, persistence, and renderer share one source of truth.

## Proposed Capability Registry

`models.plot_types` should evolve from labels/descriptions into a declarative registry that describes:

- Plot family
- Required/optional column roles
- Compatible axes
- Supported common appearance capabilities
- Type-specific option panel/factory key
- Default appearance values
- Whether multiple series can coexist
- Whether locators, legends, and right axes are supported

This replaces duplicated sets such as `_SURFACE_PLOT_TYPES`, `_COMPOSITION_PLOT_TYPES`, and the visibility sets in both `PlotTab` and `PlotCanvas`. It will prevent controls from being visible but ignored, or hidden while still affecting rendering.

## Stable Identity and Ordering

Final-state series management needs stable IDs rather than list positions:

- Add a saved `series_id` to each series.
- Refer to locator targets by `series_id`; migrate old `series_index` values on load.
- Use the ordered series-ID list for drawing and default legend order.
- Persist optional legend-item overrides separately only when users customize them.

This makes Duplicate/Move Up/Move Down safe and avoids locator corruption as the editor grows.

## Recommended Module Split

- `models/plot_state.py`: versioned, validated plot and appearance state
- `models/plot_types.py`: plot capabilities and type metadata
- `ui/plot_inspector.py` or `ui/plot_inspector/`: coordinator plus focused Series, Axes, Legend, Figure, and Locator panels
- `ui/plot_canvas.py`: rendering coordinator only
- `ui/plot_renderers/`: optional type-family render helpers when extracting them materially reduces the canvas module

Avoid a full renderer rewrite in one change. First make the state boundary and inspector panels, then extract render families while adding the new options.

## Implementation Sequence

Implementation status: the first vertical slice is now in place. Plot-state version 3 and legacy flat-state migration are implemented in `models/plot_settings.py`; the dedicated Legend section, ordered combined legends, per-series inclusion, outside placement, debounced Auto preview, non-modal live validation, and direct selected-series editing are implemented. The Heatmap/Contour/Filled Contour GUI path is regression-tested and failed surfaces display a canvas explanation. Stable series IDs, deeper typography, and the remaining slices below are still pending.

### Slice 1: State and interaction foundation

- Add typed settings with version-2 migration.
- Add the debounced Auto preview/Apply contract and dirty feedback.
- Add inline range validation.
- Move the queue to the top and add Duplicate/Move controls.
- Add stable series identity and migrate locators.
- Add state round-trip and legacy-state tests.

### Slice 2: Legend and typography

- Add the dedicated Legend section and all core size/frame/order options.
- Add typography controls and explicit style precedence.
- Add per-series visibility/show-in-legend/opacity/z-order.
- Correct combined left/right legend ordering, duplicate labels, locator/band inclusion, composition behavior, and outside-layout export.

### Slice 3: Axes, ticks, grid, and figure

- Add auto ranges, reverse axes, tick/minor-tick formatting, spines, detailed grid styling, backgrounds, aspect, DPI, and margins.
- Ensure right-Y controls only appear when a right-axis series exists.
- Persist and test all settings.

### Slice 4: Existing plot-type completion

- Add complete marker/error/bar/histogram/distribution controls.
- Add map colormap/colorbar/levels/range controls.
- Add composition label/percentage/legend options.
- Drive inspector visibility and validation from the capability registry.

### Slice 5: Presets, export, and hardening

- Add named appearance presets independent of data mapping.
- Add publication export profiles and predictable DPI/margin behavior.
- Add plot-local undo/redo if the direct-edit workflow proves stable.
- Finish visual, project-cycle, performance, and accessibility testing.

## Test and Acceptance Matrix

Required automated coverage:

- Version-2 to version-3 migration and malformed-state fallbacks
- Exact save/load round trip for every new global and per-series option
- New Empty Plot defaults and reset-section behavior
- Every existing plot subtype exposes only supported controls
- Auto preview debounce and manual Apply behavior
- Selected-series edits cannot be silently lost
- Left/right legend ordering, text size, columns, frames, hidden entries, and deduplication
- Locator and confidence-band legend inclusion policies
- Outside legends are not clipped in raster or vector export
- Font/tick/grid/spine settings are observable on Matplotlib artists
- Map colormap/colorbar/level settings and composition label modes
- Series reorder preserves locator targeting
- Project save/open keeps appearance and remains compatible with old saved plots

Manual acceptance:

- The common task—choose X/Y, add a line, change its color, resize title/legend, set axes, and export—should not require scrolling through irrelevant fields or guessing whether **Plot**/**Update** is needed.
- A saved plot should reload visually equivalent to the original.
- The inspector should remain usable at 340-380 px width in both light and dark themes.
- Expensive plots should communicate whether preview is live, pending, or paused.
- Keyboard focus, labels, tooltips, and color-selection workflows should be accessible.

## Recommended First Implementation Target

Start with Slice 1 plus a vertical slice of Slice 2: typed state/migration, consistent preview behavior, a dedicated Legend section, legend text size/title/columns/frame/outside presets, and tests. This immediately solves the user's visible legend problem while preventing the rest of the polish from expanding the current flat state and monolithic form.
