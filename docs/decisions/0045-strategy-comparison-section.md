# ADR 0045: a headline comparison of spending strategies

Date: 2026-11-02.

Status: accepted; implemented and tested. Per-strategy tabs (stage 6 of the
[strategy comparison plan](../strategy-comparison-plan.md)) are proposed and not implemented.

## Context

[ADR 0044](0044-run-every-strategy-on-shared-paths.md) runs every compared strategy on the same paths. The user
asked for a headline comparison with statistics and plots: wealth over time with every strategy on one plot, and
median withdrawals over time with every strategy on one bar chart, with a dropdown for the other variables in
*Money in and out in a typical year*. The user also asked whether medians or means suit wealth over time;
[ADR 0040](0040-medians-and-mostly-zero-measures.md) chose medians.

## Alternatives considered

- **Wealth alone.** A strategy that spends less always keeps more, so wealth alone favours cautious strategies.
- **Means.** Leveraged portfolios give long right tails; ADR 0040 applies.
- **Statistics with spending first, then the two charts**, every figure a median or percentile across paths.

## Decision

A section *Spending strategies compared* between section 3 and the per-strategy results, shown when more than one
strategy was run:

- **Statistics table**, one column per strategy: starting retirement spending (median); total spending paid over
  full retired financial years (median and 10th percentile); each path's lowest retired year of spending (median
  and 10th percentile); the share of paths with any spending shortfall; the share that ever spent below the start;
  ending wealth after tax owed (median and 10th percentile).
- **Wealth over time:** the median of total wealth at each month end, one line per strategy, with a toggle that
  adds dashed 10th-percentile lines; milestones, end-of-line labels and a hover crosshair.
- **Year by year:** grouped bars by financial year, one per strategy, of the median across paths of a chosen flow
  (default *Spending*, labelled withdrawals). Outflows (spending and taxes) are shown as positive amounts paid. A
  toggle (on by default) keeps full retired years only, since earlier years are identical across strategies.
- Fixed colours by strategy, not by position: the first four slots of the reference categorical palette (blue,
  orange, aqua, yellow). They passed the palette validator's lightness, chroma, colour-vision separation and
  normal-vision checks; two are below 3:1 contrast, so every chart has a legend and the table carries the values.
- The calculations live in `retirement/strategy_results.py` and are shared by the app and the PNG writer:
  `comparison_summary.csv`, `comparison_wealth.png` (medians and 10th percentiles) and `comparison_spending.png`
  (median spending in full retired years) in the plan folder.

## Reasons and evidence

- **User requirements:** the two charts, the dropdown, statistics, medians.
- **Engineering judgement:** spending measures come first because wealth alone rewards spending less; the 10th
  percentile shows bad markets, where the strategies differ most.
- **Checked:** on a 60-path, 40-year example every strategy started from the same median spending ($65,808), as the
  shared start requires. Fixed spending's yearly median dipped slightly late in retirement; each path's fixed
  spending was flat, and the dip came from paths that ran short, which the caption now explains.

## Consequences

- Every figure is a separate median or percentile across paths, so a strategy's column or line need not describe
  one path; the captions say so.
- With one strategy the section is not shown; sections 4 and 5 already cover it.

## Implementation and validation

- **Code:** `retirement/strategy_results.py`, `ui/app.py` (`section_comparison`, `strategy_scale`),
  `reporting/plan.py` (`write_comparison_plots`), `retirement/run_plan.py` (`COMPARISON_FILES`).
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:** `tests/test_plan.py::test_strategy_comparison_measures_follow_their_definitions` (hand-computed
  values); the multi-strategy run test checks the comparison files and equal starting spending; the app test
  renders the section, changes the flow and adds the 10th percentile.
- **Visual check:** both PNGs were inspected; the browser check is recorded in
  [plan-portfolios.md](../validation/plan-portfolios.md).
