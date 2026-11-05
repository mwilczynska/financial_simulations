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
- Retirement, strategy comparison (when applicable), portfolios and downloads
  remain distinct workspaces, selected with a compact segmented control.
  Portfolios also presents all its plots together. Compared strategies retain
  ADR 0046's tracked tabs and independent choices; only the active strategy is
  rendered.
- Compact segmented controls select accounts or a single path versus a group.
  Cohort names use short labelled buttons. Hundreds of paths are addressed by
  numeric ID. Expanders remain exclusively explanatory in Results.
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
`tests/test_cashflow_chart.py` checks filtering of every value-bearing layer,
an unfixed y scale, retained totals and recoverability after hiding everything.
Browser review includes actual legend clicks, section links and narrow layout.
