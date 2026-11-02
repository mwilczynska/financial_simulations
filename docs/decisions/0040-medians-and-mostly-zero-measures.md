# ADR 0040: medians for path summaries, and share-plus-median for mostly-zero measures

Date: 2026-11-02.

Status: accepted; implemented and tested.

## Context

The user asked whether the planner's plots should show averages or medians, given that outliers can move an
average a long way. An audit of `ui/app.py` found:

- Section 4 (retirement outcomes) already summarised paths by medians and percentiles. Shares such as "paths that
  ran out" are means of yes/no indicators, which is the correct estimator for a share.
- Two section 4 tiles were medians of quantities that are zero on most paths: *Median Age Pension received* and
  *Median spending shortfall*. Their median is often exactly $0, which hides the paths where the quantity matters.
- *Median total tax* added the medians of personal tax, fund tax and Division 296 tax. A sum of medians is not
  the median of each path's total, and it disagreed with the neighbouring tile, which used the median of totals.
- Section 5's path groups ("Worst 1%" to "Best 1%", plus all paths) were arithmetic means throughout: tiles,
  month-end balances by account, stacked money in and out bars, and the year-by-year table.

## Alternatives considered

- **Keep means in the groups.** Means add up across accounts and flows. But the default portfolios are leveraged,
  so path wealth has a long right tail. The open-ended groups (best 10%, best 1%, all paths) can be dominated by
  one extreme path, and the mean of a skewed quantity is also noisier between seeds than its median.
- **Medians everywhere, including the stacked flows.** Medians of components do not add up to the median of the
  total, and the group flow chart exists to show how a year's flows produce its net change.
- **Means for mostly-zero measures.** A mean blends how often something happens with how large it is. Reporting
  the share above zero and the size among those paths separately is clearer.

## Decision

- Path-group tiles, month-end balances by account and the year-by-year table use medians. Each account's or
  column's median is taken on its own, and the captions say so.
- The group's stacked money in and out bars stay arithmetic means, labelled as averages, because they must add
  up to the net change line.
- Measures that are zero on most paths (spending shortfall, Age Pension received) show the share of paths above
  zero and the median among those paths, formatted by `affected` in `ui/app.py`. In the group table, the
  shortfall column becomes the share of the group's paths with a shortfall that year.
- Total tax is the median of each path's total.
- The section 5 picker calls them "groups", not "averages".

## Reasons and evidence

- **User requirement:** avoid summaries that outliers can distort.
- **Engineering judgement:** a median describes what a typical path in the group experienced; a share plus a
  conditional median answers both "how often" and "how bad". Additivity is kept only where the chart's purpose
  needs it.
- **Verified arithmetic:** three paths with two tax components `(0, 10)`, `(10, 0)` and `(10, 10)` have totals
  10, 10 and 20, so the median total is 10. The component medians are 10 and 10, which sum to 20.

## Consequences

- Group figures change, most in the open-ended best groups.
- Stacked group balances are a median per account, so their total need not equal any path's wealth.
- Section 4's typical-year flow bars were already medians and stay so; their caption already says medians do not
  add up.

## Implementation and validation

- **Code:** `affected`, `typical_flows_section`, `age_pension_section`, `section_retirement` (total tax tile),
  `group_paths` (formerly `averaged_paths`) and the section 5 picker in `ui/app.py`.
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md),
  [age-pension.md](../methodology/age-pension.md).
- **Tests:** `tests/test_plan.py::test_mostly_zero_measures_report_share_and_median_among_affected`; the app test
  opens the all-paths group and checks the median table heading.
- **Browser check:** recorded in [plan-portfolios.md](../validation/plan-portfolios.md).
