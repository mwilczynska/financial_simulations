# ADR 0034: future observation calendar at the history's density, and an accounting end apart from the last observation

Date: 2026-11-02.

Status: accepted; implemented and tested. Replaces the weekday target calendar used by the planner since
[ADR 0017](0017-ticker-portfolios-and-interactive-results.md).

## Context

The [1 November 2026 retirement calculation review](../reviews/2026-11-01-retirement-calculations/README.md)
found three calendar errors (findings 5, 7 and 12):

- **Finding 5.** The planner's future template had every Monday to Friday, about 261 a year, and each date
  drew one historical return. The default joint history has 14,031 returns from 2 January 1970 to
  30 October 2026: 246.85 per 365.25 days, ranging from 241 to 253 by year. Each path therefore compounded
  about 5.7% more returns per calendar year than the history, which overstates expected growth and variance.
  The constant-CAGR reference path converted each CAGR over 252 observations and then compounded it on the
  same denser grid.
- **Finding 7.** The ledger ended on the last weekday. A plan ending on a Saturday 30 June skipped that
  year's assessment and fund tax.
- **Finding 12.** The last observation of a month or quarter cut off by the horizon was treated as that
  period's close. A truncated path paid a quarter-end distribution that a longer path with the same prefix
  did not.

The project rules require daily returns, distinct trading observations and calendar events, and no invented
holiday returns ([ADR 0001](0001-daily-returns-throughout.md), `PLAN.md` item 9).

## Alternatives considered

1. **Keep weekdays.** This keeps the bias.
2. **An exchange holiday calendar** (for example NYSE rules, about 252 a year). This is still denser than
   the joint calendar of several markets, whose density depends on the tickers selected.
3. **Insert zero returns on future holidays.** This fabricates observations and is prohibited.
4. **Weekdays thinned to the density of the sampled history.** Deterministic and ticker-aware. The holiday
   positions are not realistic.
5. **Sample by calendar duration.** Draw blocks of calendar time, not observations. This is more faithful but
   a larger change to the bootstrap.

## Decision

- **Calendar.** Choose 4. `markets/calendar.py` measures `observations_per_year` over the sampled history.
  `observation_calendar(start, end, per_year)` keeps the opening mark, then keeps weekdays in order while
  the count stays within ceil(per_year x elapsed days / 365.25).
- **Where it applies.** `retirement.plan.future_observations` applies the calendar to the portfolio paths
  (`target_observations`), the retirement-length withdrawal paths and every ledger path from
  `build_inputs`.
- **Reference path.** The constant-CAGR path compounds each step over its calendar days.
- **Accounting end.** `LedgerScenario.end_date` is the accounting end; `None` keeps the last observation. It
  must fall within a week after the last observation. Days after it carry the last close with no return.
  The planner sets the requested horizon end.
- **Period closes.** Distributions and pension minimum instalments fire on a period's last observation only
  when the calendar period ends by the accounting end.

## Reasons and evidence

- **User requirement and project rule:** daily returns throughout, with no fabricated observations.
- **Research finding:** the joint default history has 246.85 returns a year. The fixture used by the tests
  has about 260 a year, so existing fixture-based tests barely change.
- **Engineering judgement:** evenly spread drops give the right count and keep prefixes stable, and a run
  depends only on its start and the density. The dropped dates do not mimic real holidays, so the timing of
  events that fall on dropped weekdays moves by a day. Option 5 remains the better long-term design if
  calendar-time sampling matters.

## Consequences

- Planner results fall relative to the old calendar: growth per calendar year matches the history instead
  of compounding about 5.7% more returns per year. Volatility per calendar year also falls. The combined
  change for a plan has not been measured here.
- **Annualised volatility.** Reported volatility still annualises daily variance with sqrt(252). That is
  a separate reporting convention, not changed here.
- **Mid-period horizon ends.** A horizon ending mid-quarter has no partial distribution. Partial-period
  income is not accrued.
- **Run lengths.** Path lengths change, so seeds give different draws from before.

## Implementation and validation

- **Code:** `src/financial_simulations/markets/calendar.py`; `future_observations` and `build_inputs` in
  `retirement/plan.py`; `target_observations` and the retirement-length paths in `retirement/analysis.py`;
  `end_date` and `_period_closes` in `retirement/ledger.py`.
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md) and
  [retirement-ledger.md](../methodology/retirement-ledger.md).
- **Tests in `tests/test_plan.py`:**
  - `test_future_calendar_keeps_the_history_density_and_extends_shorter_horizons` covers density, prefixes,
    no weekends and the weekday ceiling.
  - `test_planner_paths_use_the_history_density_and_the_requested_end` covers the planner using the
    calendar and the requested end, and the reference path growing at its CAGR.
- **Other tests:**
  - `tests/test_projection.py::test_a_weekend_30_june_horizon_is_still_assessed` covers the review's
    $600 fund tax.
  - `tests/test_ledger.py::test_a_truncated_period_has_no_close_so_identical_prefixes_match` covers the
    review's $1,000 distribution.
