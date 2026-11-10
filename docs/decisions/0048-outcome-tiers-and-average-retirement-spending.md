# ADR 0048: outcome tiers for Age Pension reliance, and average retirement spending

Date: 2026-11-10.

Status: accepted; implemented and tested.

## Context

The user is particularly interested in the risk of ruin, and also in the paths that never reach ruin but fall so
low that they need the Age Pension, "which is near ruin". The user also asked for average spending after
retirement, for paths and for groups of paths.

The planner reported each path as `funded` or `depleted` ([ADR 0019](0019-retirement-path-results.md)), and the
share of paths paid any Age Pension ([ADR 0027](0027-age-pension-and-sapto.md)). It did not combine them, and
receiving *any* Age Pension is a weak sign of distress: for a single homeowner a part pension starts once
assessable assets fall below the cut-off (about $746,000 in 2026-27 dollars), well above ruin. Spending was
reported as a starting amount, a lowest year and a total over retired years
([ADR 0045](0045-strategy-comparison-section.md)), not as an average per year, and not by group.

## Alternatives considered

- **Two tiers of funded paths: received any Age Pension, or none.** Simple, but it counts a path that drew a few
  hundred dollars of part pension for one year as near ruin.
- **A wealth threshold** (for example, wealth below some dollar amount). Needs an arbitrary number, and ignores the
  home and other assessable assets.
- **Age Pension as a share of spending.** With spending well above the maximum rate the share never becomes large,
  so it does not separate paths.
- **A year at the full rate** (chosen for the near-ruin tier). The maximum rate is paid only when neither means
  test reduces it, which the rules themselves define: assessable assets under the full-pension limit (about
  $333,000 for a single homeowner in 2026-27) and deemed income under the free area.

## Decision

**Tiers.** `retirement/outcomes.py` puts each calculated path in one tier, the worst it reached:

| Tier | Definition |
| --- | --- |
| Ran out | The ledger's `depleted` status: unpaid spending or tax, or tax owed at the horizon that the money left cannot settle |
| Full Age Pension | Funded, with at least one financial year paid 95% or more of the maximum single rate for that year |
| Part Age Pension | Funded and paid some Age Pension, never a full-rate year |
| Self-funded | Funded and never paid any Age Pension |

- The maximum rate for a financial year is 26 fortnights of that year's projected rate (basic rate indexed to
  wages, supplements to CPI, as the ledger pays it), in today's dollars on the ledger's financial-year step
  (`full_age_pension_by_year`).
- **95%** (`FULL_RATE_SHARE`) is an engineering judgement. A year at the full rate has 26 or 27 paydays, so it pays
  at least 26 fortnights; the margin allows for a year in which a path reaches the full rate after a few reduced
  fortnights, and for rounding of projected rates. The first year of eligibility is usually a part year, so a path
  at the full rate from age 67 is counted from its first whole year.
- **Each year's state** uses the same four names (`yearly_states`). *Ran out* holds from the first financial year
  with a spending shortfall, even if the path later recovers. A path that is `depleted` without any shortfall is
  marked in its last year. Otherwise the year is full rate, part rate or self-funded by that year's payment, so a
  path can move back up when markets recover. The tier is therefore at least as bad as the path's last state.
- A path that ran out is counted only as *Ran out*, even if it was also paid the Age Pension. The Age Pension tab's
  shares of paths receiving any pension, and reaching the full rate, include those paths and say so.

**Average retirement spending.** A path's *average retired-year spending* is the mean of spending actually paid,
in today's dollars, over its full retired financial years (`path_outcomes`), so a shortfall or a cut by the
spending rule lowers it. `group_spending` reports, for each group of paths, the median path's average and the 10th
and 90th percentiles. Groups are every path, each tier that has paths, and the app's existing ending-wealth
groups (worst 1%, 5% and 10%, the middle 10%, best 10% and 1%).

**Where they appear.**

- Outcomes headline: the four tiers as shares of paths, and the median path's average retired-year spending.
- *Wealth*: every drawn path coloured by tier, with a control to choose the tiers drawn. Every path that ran out or
  reached the full Age Pension is drawn; the others are the existing sample spread evenly across ending wealth
  (`shown_paths`). A dot marks the month a path first received the Age Pension.
- *Risk over time*: the share of paths in each state each year, a count of ruin and full Age Pension together, and
  a table of medians by tier.
- *Spending*: average retired-year spending by group, as a chart and a table.
- Paths: the tiers are groups in the picker, each single path is labelled with its tier, and both views show the
  average retired-year spending.
- Compare: the shares of paths that ran out, reached the full Age Pension and drew a part Age Pension, and the
  median and 10th percentile of average retired-year spending, lead the statistics table and
  `comparison_summary.csv`.
- PNG: `retirement_outcomes.png` per strategy shows the yearly states and average spending by group.

**Colours.** Self-funded is a neutral grey; part Age Pension, full Age Pension and ran out are yellow, orange-red
and crimson, darkening with severity (`TIER_COLOURS` in `reporting/palette.py`).

## Reasons and evidence

- **User requirement:** show the paths that end up on the Age Pension beside the risk of ruin, and average spending
  after retirement for paths and groups of paths.
- **Primary-source facts** (Services Australia and DSS, recorded in
  [age-pension.md](../methodology/age-pension.md) and the 2026-27 rule register): the maximum rate, the
  full-pension asset limits and the assets and income tests that reduce it.
- **Engineering judgement:** using a full-rate year as the near-ruin line, the 95% margin, and holding *Ran out*
  from the first shortfall in the yearly states.
- **Colours checked with the palette validator** on 10 November 2026 (white surface): yellow, orange-red and crimson
  pass the lightness band, colour-vision separation (worst neighbour 14.8) and the normal-vision floor (18.1). The
  first choice, the palette's yellow, orange and red, failed the normal-vision floor (10.8 to 13.7).
- **Observed** on 10 November 2026 with the example plan extended to 40 years, fixed spending at 5% of wealth at
  retirement and 100 paths: 64% self-funded, 21% part Age Pension, 5% full Age Pension and 10% ran out. The median
  ending wealth was $1.68 million for the part Age Pension paths and $269,000 for the full Age Pension paths,
  which supports treating only the full rate as near ruin.

## Consequences

- Risk of ruin is unchanged. The tiers add two shares between it and self-funded.
- The tiers depend on the horizon: a run that stops before age 67 has no Age Pension tiers, and the app says so.
- The full-rate test uses the single homeowner or non-homeowner rules already modelled; it inherits their limits
  (no couples, no Rent Assistance).
- A path paid the full rate for one year and then recovering is still *Full Age Pension*. The table of medians by
  tier shows the years on the pension, and the yearly states show how many paths are on it at once.
- `comparison_summary.csv` gains five rows at the top.

## Implementation and validation

- **Code:** `src/financial_simulations/retirement/outcomes.py`; `retirement/strategy_results.py` (`MEASURES`);
  `reporting/plan.py` (`write_outcome_plot`); `retirement/run_plan.py`; `ui/outcomes_page.py`, `ui/paths_page.py`,
  `ui/charts.py` (`all_paths_chart`, `states_chart`, `group_spending_chart`).
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:** `tests/test_outcomes.py` checks the tier of one path per tier and of a path depleted without a
  shortfall, the 95% boundary, that a path that ran out keeps its full-rate years, that yearly states hold ruin and
  sum to one, group membership and spending figures, and that the full rate is 26 fortnights of the projected rate;
  `tests/test_plan.py::test_strategy_comparison_measures_follow_their_definitions` checks the new comparison rows.
