# ADR 0056: speed of the stacked markets, wealth and money chart

Date: 2026-11-13.

Status: accepted; implemented and tested.

## Context

The stacked chart of [ADR 0049](0049-single-path-markets-wealth-and-money.md) (one path, or a group of paths) was
slow. **User report:** the chart is slow, and hovering takes a while to show the figures and only does so on some
pixels. The user asked for it to be tested with 1,000 paths.

**Measured** on 13 November 2026 on a saved run of 1,000 paths over 55 years, median path, in the in-app browser:

- Every rerun of the view rebuilt the chart on the server in about 2.4 s: about 2.0 s for the chart (Altair's schema
  validation, repeated copies of the chart by each `configure_*` call, and data conversion) and 0.2 to 0.35 s for the
  path's yearly flows.
- The specification was 3.6 MB, of which 2.5 MB was the weekly lines in long form (22,976 rows, each repeating the
  series name and kind).
- The browser drew about 5,100 SVG elements. The hover used Vega-Lite's nearest-point selection, which adds a
  Voronoi cell per month in each panel: 1,980 cells about 1.7 pixels wide, on top of 1,980 invisible points.
  Handling one pointer move took about 9 ms of script, before the browser repainted the SVG. Leaving one cell and
  entering the next each changed the chart, so every pixel of movement did this twice.

The number of paths does not change the single-path chart; it changes the page around it (1,011 picker options)
and the group view.

## Alternatives considered

- **Fewer points** (monthly lines instead of weekly): faster, but ADR 0049 chose weekly points so a crash inside a
  month still shows. Rejected.
- **A server-drawn image for the lines**, as the all-paths chart uses: the lines here must hide and show from the
  legend and refit the axis without a rerun. Rejected.
- **Hand-written Vega-Lite** instead of Altair: removes the remaining build time, but duplicates the shared chart
  builders (`balances_chart`, `hideable`, `milestone_layers`). Not done; see Consequences.
- **Canvas, hover strips, a smaller specification and a kept specification (chosen).**

## Decision

- The stacked chart uses the canvas renderer, as the all-paths chart does.
- The hover targets are one invisible full-height strip per month in each panel, from halfway to the month before
  to halfway to the month after, with the first and last strips closed at the plotted dates. The selection is a
  plain pointer-over selection on the strip's month, with no nearest-point search.
- The weekly lines are sent as one row per week, six significant figures, with short column names; the browser folds
  them into one row per series and looks up each series' name and kind.
- `theme.specification` builds the dictionary without Altair's schema validation and adds the app's configuration
  to the dictionary, worked out once, instead of calling `configure_*` on the chart.
- `paths_page.story_chart` keeps the specification in the session per view (run and path, or run and group) and
  legend-button state, up to six. The path's yearly flow frames are kept per result.

## Reasons and evidence

- **Engineering judgement:** a strip per month gives the same month as the nearest-point search, because the strip
  edges are the midpoints between month ends, and needs half the marks and no Voronoi transform (which was also
  recomputed on every pan and zoom step). On canvas a hover redraws only the hairline's strip.
- **Engineering judgement:** skipping validation is safe only with a test that validates the same chart, which
  `tests/test_story_chart.py` does.
- **Measured** after the change, same run and path: specification 1.7 MB (weekly lines 0.44 MB); chart build about
  1.4 s the first time a path is opened; reopening the Paths page 0.2 s (was 2.4 s); one canvas element; a pointer
  move handled in about 2 ms of synchronous script (median of 150 moves, largest 5 ms), with the tooltip shown on
  294 of 300 sampled positions (the others were over the axis). The group of all 1,000 paths: about 3 ms, tooltip on
  116 of 120.
- **Not measured:** paint time. The browser pane was hidden during the measurements, so frame timing was not
  available; the SVG repaint that the canvas renderer removes is therefore reasoned, not timed.

## Consequences

- A rerun that changes neither the view nor the legend buttons sends an identical specification, so the browser
  keeps the chart as it is, including zoom and items hidden from the legend.
- Six significant figures for the drawn lines; the table's statistics still come from the daily returns.
- The kept specifications hold up to about 10 MB per session.
- The first open of a path still takes about 1.4 s on the server, most of it Altair building and converting the
  chart. Hand-written Vega-Lite would remove it and is the next step if that matters.
- Opening a group still compounds every member path's markets once (about 9 s for 1,000 paths, with a spinner); the
  result is kept for the session. Not changed here.
- Text in a canvas chart cannot be selected, and the chart's elements are not in the accessibility tree.

## Implementation and validation

- **Code:** `ui/charts.py` (`cursor_layers`, `path_story`); `ui/theme.py` (`specification`, `configuration`,
  `draw_specification`); `ui/paths_page.py` (`story_chart`, `path_flow_frames`).
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md), "One path: markets, wealth and money on one
  date axis".
- **Tests:** `tests/test_story_chart.py` validates the specification against the Vega-Lite schema, and checks the
  canvas renderer, that the strips tile the plotted dates with each month end inside its own, that the selection has
  no nearest-point search, and that the lines are sent one row per week (a ticker name with a dot included).
- **Browser check** on 13 November 2026, saved 1,000-path run: the hairline and tooltips follow a real pointer in
  the markets, wealth and flows panels of a single path and of the all-paths group; a legend click hides a ticker
  and the axis refits; the legend strokes and line widths match the earlier chart.
