# ADR 0048: a continuous analytical report with interactive cash flow

Date: 2026-11-04. Status: implemented; validation recorded in the planner methodology.

## Context

After ADR 0047's visible-choice refinement, the user found too many radio dots
and too much switching between results. They explicitly asked to retain every
plot and prioritised the cash-flow bar chart with clickable spending, Age Pension
and other legend items. The purpose is analytical retirement planning, including
shortfalls, pension-supported paths and average retirement spending.

## Decision and alternatives

Merely styling every radio as a button would preserve the nested navigation.
Hiding diagnostics would violate the requirement to retain plots. Instead:

- Retirement becomes a continuous report: outcomes, cash flow and wealth,
  spending and cohort averages, Age Pension, risk/tax diagnostics and the path
  explorer. In-page links scroll to these sections without changing results.
  The section links remain visible while scrolling, with anchor spacing that
  keeps headings below the fixed navigation at desktop and narrow widths.
- Retirement, strategy comparison (when applicable), portfolios and downloads
  remain distinct workspaces, selected with a compact segmented control.
  Portfolios also presents all its plots together. Compared strategies retain
  ADR 0046's tracked tabs and independent choices; only the active strategy is
  rendered.
- Compact segmented controls select accounts or a single path versus a group.
  Cohort names use short labelled buttons. Expanders remain exclusively
  explanatory in Results. On 5 November, the user asked to replace the numeric
  path input with a searchable dropdown. It keeps each calculated path's ID,
  labels it with its existing ending-wealth percentile, and orders paths from
  lowest to highest ending wealth. The median path is the starting selection.
  Two decimal places keep adjacent ranks distinguishable at the supported path
  counts; the table and path details use the same precision.
- The yearly cash-flow chart is near the top of the report. The all-path median
  and group-mean charts now support the existing single-path chart's independent
  legend toggles. A Spending & pension preset isolates spending, Age Pension,
  personal income tax and Division 296 tax. Show all and Show none are available.
  All items remain recoverable through the legend. Hidden bars, net-change lines,
  uncertainty intervals and additions lines leave the y scale, so it refits.
- Following the user's request for more vertical room, main time-series plots
  use roughly 420–520 pixels and small diagnostic charts 340–360 pixels. Cash-flow
  legends use four columns on desktop and two on narrow screens, preserving
  more of the chart height for the plot itself. Outcome summary bars stay compact.
  Narrow legends use concise labels while the full flow names remain in the
  data and tooltips; each path/group chart identifies its selected cohort locally.
- Net change always represents total change in wealth, even when some flows are
  hidden. Group flows retain arithmetic means; the overview retains separately
  calculated medians, which do not add up. Filtering changes presentation only.

## Consequences

All existing plots remain available. The page is longer, but moving between
retirement questions does not replace content. In-page links provide direct
access; chart-local fragments keep account and flow controls from redrawing
the whole report. Long interpretation notes remain available in expanders.
The daily model, pension rules, outcome cohorts, spending averages and PNG
accounting conventions are unchanged.

## Evidence

User feedback in this chat is the requirement. Information hierarchy and
control choices are engineering judgement. `tests/test_plan.py` checks the
continuous report, navigation, flow preset and strategy-state persistence.
It also verifies the individual path picker labels, order and selected path ID.
`tests/test_cashflow_chart.py` checks filtering of every value-bearing layer,
an unfixed y scale, retained totals and recoverability after hiding everything.
Browser review includes actual legend clicks, section links and narrow layout.
