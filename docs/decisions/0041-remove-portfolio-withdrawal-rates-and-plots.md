# ADR 0041: remove the portfolio-only withdrawal rates, drawdown and calendar-year charts

Date: 2026-11-02.

Status: accepted; implemented and tested. Supersedes the withdrawal-rate parts of
[ADR 0021](0021-cash-interest-and-withdrawal-rates.md) and
[ADR 0039](0039-withdrawal-rate-basis-and-claims.md); their other decisions stand.

## Context

The user is preparing the planner to compare retirement spending strategies on every ledger path, and asked to
remove these results first:

- both "Below previous peak" drawdown charts (historical, section 2; future, section 3);
- both calendar-year return charts (historical bars, section 2; future "after inflation" bands, section 3);
- everything under "How much could each portfolio pay out each year?" (section 3).

The withdrawal rates under that heading came from a separate set of portfolio-only draws, from the retirement
date to `assumptions.planning_age`. The same rates also fed the section 4 caption "Estimated chance of running out
by age N" and the reference lines on the section 4 withdrawal-rate chart. Compute time is the main constraint on
running several strategies.

## Alternatives considered

- **Remove the plots, keep the calculation** for the caption and reference lines. This saves no compute, and keeps
  a pre-tax, portfolio-only, fixed-spending estimate beside the tax ledger's own result. It would also be wrong
  for the market-responsive spending rules about to be compared.
- **Remove the calculation, the caption, the reference lines and `planning_age`.** The ledger answers whether the
  money lasts, with tax and the Age Pension, over the years simulated.

## Decision

The second alternative, chosen by the user on 2 November 2026:

- `analyse_portfolios` no longer draws the retirement-length paths or computes sustainable or capital-preserving
  rates. `PortfolioAnalysis` loses `annual_returns`, `historical_annual` and `planning_end`. The future bands lose
  their drawdown percentiles, and the history loses its month-end drawdown column.
- The `portfolio_annual.csv` output is no longer written, and a stale copy in a reused plan folder is deleted.
- `assumptions.planning_age` leaves the normalised plan and the Assumptions tab. Older plan files that contain it
  still load; the value is ignored.
- The section 4 caption becomes a warning when the ledger stops before age 90 (`SHORT_HORIZON_AGE`): the risk of
  ruin covers only the years simulated.
- Kept: maximum drawdown and longest drawdown per path (section 3 distributions and table), and the historical
  worst and best calendar years and share of positive years (section 1 statistics). These are summaries of the
  same daily compounding, not the removed charts.

## Reasons and evidence

- **User requirement:** the three plot removals and the removal of the calculation.
- **Engineering judgement:** the withdrawal rates were a second, simpler model of the same question the ledger
  answers. With strategy comparison coming, a fixed-spending, pre-tax estimate would conflict with the ledger's
  results for the other rules.
- **Compute (not timed):** removing the extra draws removes one full set of `paths` resampled and compounded from
  retirement to the planning age (about 40 years for the example plan) from every run.

## Consequences

- Plans whose horizon ends well before old age no longer get any estimate beyond the horizon. The warning tells
  the user to extend *Years to simulate*, which runs the full ledger further and costs more time per path.
- Scripts that read `portfolio_annual.csv` or the `Sustainable withdrawal rate` and `Capital-preserving withdrawal
  rate` columns of `portfolio_outcomes.csv` must change.
- The ledger's own withdrawal rate (spending plus tax, less Age Pension, over wealth at 1 July) is unchanged.

## Implementation and validation

- **Code:** `retirement/analysis.py`, `retirement/run_plan.py`, `retirement/plan.py`,
  `retirement/default_plan.toml`, `ui/app.py`.
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md),
  [age-pension.md](../methodology/age-pension.md).
- **Tests:** the two withdrawal-rate identity tests are removed with the functions they tested;
  `tests/test_plan.py::test_legacy_planning_age_still_loads_and_is_dropped` is new; the full suite passes.
- **Browser check:** recorded in [plan-portfolios.md](../validation/plan-portfolios.md).
