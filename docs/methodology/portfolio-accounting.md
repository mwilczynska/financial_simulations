# Deterministic daily portfolio accounting and baseline reporting

Date: 2026-10-28. Status: implemented for Stage 1A, package 0.1.0. Synthetic
accounting/report tests and local companion reconciliation have run. Stochastic
generators, retirement accounts and Australian rules remain unimplemented.
See [ADR 0004](../decisions/0004-stage-1a-accounting-conventions.md).

## Purpose and architecture

Calculate one portfolio's daily holdings, cash and value from an explicit market
path, allocation policy and dated cash flows. This establishes accounting that
later generators can share. A historical baseline is not a forward forecast or
a probability of retirement success.

Implementation: [engine](../../src/financial_simulations/portfolios/engine.py),
[scenario loader](../../src/financial_simulations/scenario.py),
[runner](../../src/financial_simulations/runner.py),
[report calculations](../../src/financial_simulations/reporting/baseline.py),
and [reference comparison](../../src/financial_simulations/validation.py).

[Matplotlib plots](../../src/financial_simulations/reporting/plots.py) generate
the first-pass visual deliverables directly from Python. Interactive plots are
deferred and PDF generation is excluded by user instruction.

The engine uses NumPy position vectors inside a calendar-day loop. pandas is used
for adapter and output tables, not a monthly return engine. Inputs and source
limitations are specified in [data adapters](data-adapters.md).

## Inputs and conventions

- `MarketPath`: opening valuation date, subsequent daily observation dates,
  canonical asset order, simple returns and currency. Its matrix has one fewer
  row than its date tuple. Returns are finite and at least -100%.
- `PortfolioSpec`: long-only, fully invested risky-asset target weights and
  either `annual` or `buy_and_hold`. Supplied leveraged funds are holdings;
  there is no separate borrowing or new leveraged-fund construction.
- `initial_value`: opening amount allocated to risky assets at target weights.
  Optional `initial_cash` is a separate retained reserve. Both are nonnegative.
- `CashFlow`: calendar date, signed amount and `before_return` or
  `after_return` timing. Positive means contribution; negative means requested
  withdrawal. The default is after-return. Events outside the actual selected
  horizon fail, including requests on a weekend beyond the last valuation.
- Cash earns zero interest. Supplied return-series expenses/distributions are
  retained. Additional portfolio fees, transaction costs and tax are unsupported
  in 1A; unknown scenario fields are rejected rather than silently ignored.

The opening allocation is made at the first selected valuation. No return from
before that mark is applied. Calendar output includes every day from that mark
through the last valuation. Closed-market account marks are carried valuations,
not observations for calibration, and their performance return is left blank.

## Event order and cash execution

On each calendar date:

1. Record prior closing value as today's opening value.
2. Process before-return events, in their specified order.
3. On the first return observation of a new calendar year, an annual policy
   resets risky holdings to target weights using their pre-return values. It
   leaves the cash reserve and pending cash deposits separate. Buy-and-hold does
   not perform scheduled rebalances.
4. Apply the supplied asset-return vector if this is a return observation.
5. Process after-return events, in their specified order.
6. At an observation's close, invest pending deposits from closed-market dates
   at target proportions. Do not sweep the retained initial cash reserve.
7. Record holdings, cash, contributions, paid/requested withdrawals, shortfall,
   return, market P&L and the accounting reconciliation.

On an observation date, a contribution buys target proportions without resetting
existing holdings. A withdrawal spends cash first, then sells risky holdings in
proportion to their current values. On any other date, deposits enter cash and
only available cash can fund withdrawals. A cash payment consumes the retained
reserve before pending investment cash. No future sale, borrowing, negative
holding or silent date shift finances the event. An unmet amount is recorded on
that date and is **not retried** automatically. A new dated request is required.

Ordering within each event phase is intentional: on a closed date a deposit
followed by withdrawal may succeed where the reverse order records a shortfall.
Events are not silently netted.

Before-return timing is an analytical allocation at the previous valuation
before the dated return shock. It is not a claim of executable intraday prices
or settlement. After-return is the default when only close-to-close data exists.
Transaction settlement delays, spreads and actual market-opening executions are
outside this model. A birth/access date will require its own rule in Stage 2.

## Equations and invariants

Let `H[a]` be each holding's value before a return and `C` the cash balance.
Absent a trade or flow, `H'[a] = H[a] * (1 + r[a])`. Market P&L is
`P = sum(H[a] * r[a])`. Holdings drift naturally between rebalances.

For a contribution `D`, add `D*w[a]` to each holding on an observation date;
otherwise add it to pending cash. For a risky-asset sale `S`, multiply every
holding by `1 - S/sum(H)`, where `S` cannot exceed invested value.

For every calendar day, including the opening mark:

```text
closing_value = opening_value + market_pnl + contributions - withdrawals_paid
closing_value = sum(closing_holdings) + closing_cash
shortfall = withdrawals_requested - withdrawals_paid
```

The first invariant is checked during every run at `rtol=1e-11, atol=1e-9`.
Finite inputs must produce finite account values; invalid states raise errors.
Floating-point money is appropriate for this market baseline, not a promise of
cent-exact tax or transaction accounting. That requires a later convention.

At a return observation, period performance is
`p = market_pnl / (risky_value_after_before_flows + cash_after_before_flows)`.
With no exposed wealth it is defined as zero. A performance index starts at one
and compounds `(1+p)` over actual return observations. This excludes external
flows from investment performance and includes cash drag. Complete depletion
produces a -100% time-weighted chain even if later external capital is added.

Annualised time-weighted return uses the opening mark and actual elapsed dates:
`growth ** (365.25 / elapsed_calendar_days) - 1`. It is undefined for zero elapsed
days. A mathematically defined annualisation outside the floating-point range
is also reported as null, with `annualised_return_status=not_representable`;
the actual period return and account values remain unchanged. Zero duration is
identified separately as `zero_elapsed_days`; finite results are labelled
`finite`. No implicit 252-observation year is used. Maximum drawdown is the minimum
of `performance_index / running_max(performance_index) - 1`, including its opening
one. It is a performance drawdown, not a drawdown distorted by contributions.

## Worked examples

- Start 100; +10%, then -10%: values 110 then 99.
- Add 10 after the +10% observation: 120 then 108. Add it before instead:
  121 then 108.90. The report separates contributions from investment P&L.
- Two 50/50 holdings: first asset gains 10%, then the second gains 10%. Without
  a rebalance the result is 110. If the second observation starts a new calendar
  year, annual rebalancing gives `105 * 1.05 = 110.25`.
- Friday holdings 100 and no cash; Saturday deposit 10; Monday return +10%:
  Monday close is 120, comprising 110 old holdings plus the new investment of
  10 at the close. The Saturday deposit does not earn the Friday-Monday return.
- Holdings 100, cash reserve 10; Saturday withdrawal request 15: pay 10 and
  record shortfall 5. Holdings remain 100. Monday does not retry the shortfall.
- Supplied hypothetical daily-reset returns +30%, then -30% compound 100 to
  91. This validates consumption of a supplied path, not a financing model.

## Reporting and reproducibility

TOML scenarios specify manual weights or one optimiser rank. Paths inside a
scenario resolve relative to the scenario file, making them independent of the
process working directory. Examples demonstrate the user-selected 40/20/20/20
`Optimised CURRENT` portfolio, an equal-weight global comparator, optimiser import
and dated cash flows. All starting amounts are illustrative. The default's
supplied leveraged-fund returns retain their embedded financing and expenses.

Each run produces `wealth.png`, `drawdown.png` and `allocation.png` directly from
the daily ledger using Matplotlib's Agg renderer. The wealth plot includes net
capital supplied; drawdown uses the time-weighted performance index; allocation
uses actual holding/cash shares, leaving gaps for depleted balances. Every daily
mark enters the plots. These are images, with no interactive plotting layer or
PDF generation. A self-contained `report.html` embeds the same PNGs.

Other outputs are full `daily.csv`, actual
`market_returns.csv` with previous valuation dates, preserved
`source_observations.csv`, `monthly.csv`, `annual.csv` and `manifest.json`.
`--parquet` also writes the daily ledger as Parquet. Generated output is ignored
by Git. The manifest records scenario/input hashes, actual coverage, source
quality, code commit/dirty state, package-source hash, dependency versions and
conventions. A source hash supplements a dirty/uncommitted working-tree commit.
There is no random seed because Stage 1A is deterministic.

Monthly/annual summaries aggregate daily cash flows and P&L and reconcile to
their actual opening/closing values at `rtol=1e-11, atol=1e-8`. Returns compound
daily performance rather than dividing balances distorted by external flows.
Partial periods are labelled. The plots and CSV/Parquet use the full daily path.

## Batched many-path accounting with dated flows

`simulate_paths(returns, dates, portfolio, initial_value, cash_flows,
initial_cash=...)` in [batch.py](../../src/financial_simulations/portfolios/batch.py)
runs P paths with returns shaped (P, observations, assets) through the event
order above, vectorised across paths. Every path shares one observation
calendar and one dated flow schedule. The engine steps through *marks*: the
sorted union of observation dates and flow dates. Calendar days with neither
cannot change state, so they carry the previous mark, exactly as in the full
ledger. Per-path arrays hold cash, invested value, total value and withdrawals
paid at each mark. Shortfall is the path-independent requested amount minus
the amount paid. `calendar_values()` expands values to every calendar day.

Each operation mirrors `simulate_portfolio`: trading-date deposits buy target
weights, and closed-date deposits wait as pending cash until the next
observation close. Withdrawals take cash first, which also caps pending cash.
On observation dates they then sell holdings proportionally, never borrowing.
Annual rebalancing happens on a year's first observation before its return.
After-return flows precede the sweep. A path that loses everything records
shortfalls for later withdrawals and can be recapitalised by later deposits.
See [ADR 0010](../decisions/0010-batched-cash-flow-accounting.md).

The full single-path ledger remains the reference. `tests/test_batch_flows.py`
generates random calendars with weekends, about 8% random holidays and a year
boundary. It uses 25 random before/after-return flows plus a same-date
deposit/withdrawal pair and an oversized withdrawal, under both policies. It
requires agreement with the full ledger at `rtol=1e-12` for every path on every
calendar day, and for cash, payments, shortfalls, contributions and
rebalancing flags at every mark. State-dependent withdrawal policies are not
yet supported.

## Executed validation

Local validation on 2026-10-28 uses Python 3.14.0, NumPy 2.5.4, pandas 3.1.0,
pytest 9.2.0, Matplotlib 3.11.2 and PyArrow 26.0.0; the full environment snapshot is
[requirements-dev.lock.txt](../../requirements-dev.lock.txt).

The test suite covers all worked cases, holding drift, new-year boundaries,
retained cash, event ordering, depletion/recapitalisation, zero returns, one
opening mark, invalid input, leap-year annualisation, partial periods, flow-free
performance and end-to-end CLI artifacts. Report links, escaping and nonempty
PNG outputs are checked programmatically. PNGs are opened and visually inspected;
an overlapping allocation legend found in the first render was corrected and
re-rendered. Browser interaction is not part of this static-plot validation.
Exact test totals and local reconciliation results are recorded in the
[Stage 1A validation record](../validation/stage-1a.md).

Historical comparison runs the inspected local optimiser's actual functions
using the same files, weights and period, and compares every daily observation
under annual rebalancing and buy-and-hold. It verifies loaders select the same
dates/returns first. Tolerances are `rtol=1e-10, atol=1e-7`. Three cases cover the
user's leveraged default, equal global four-asset weights and rank 1 imported
from the optimiser's results CSV. The separate
[tracker audit](../decisions/0005-default-portfolio-and-tracker-audit.md) checks
reusable metrics and date/cash-flow differences in existing local calculations.

This compares account values, not all exported ranking statistics. The optimiser
derives some metrics from its first post-return value; this project explicitly
uses the opening valuation and full first interval. No changes are made to the
companion optimiser and no equivalence of all metrics is claimed.

## Limitations, decisions and references

Strict matching calendars are the default; the opt-in common-date policy
(see the adapter method) can supply longer histories. A common USD reporting
currency is required. As-of data, file/source reconstruction and shared missing
days remain limitations described in the adapter method. There is no borrowing,
shorting, transaction settlement, FX, Australian inflation, personal tax, super,
extra fees, adaptive strategy or stochastic model. Those remain separate stages.

User requirements establish daily resolution, companion adapters and documented
validation. Event timing, cash execution and drawdown/annualisation definitions
are engineering choices, made explicit in [ADR 0004](../decisions/0004-stage-1a-accounting-conventions.md).
The inspected primary implementation
[portfolio_optimizer.py](https://github.com/mwilczynska/portfolio_optimisation/blob/main/portfolio_optimizer.py)
provides the reference calendar-year rebalance and buy-and-hold behaviour. The
[dataset methods](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology.md)
define the supplied total-return semantics. Neither source establishes future
predictive accuracy or retirement adequacy.

Revision history: 2026-10-28, first implemented accounting/report baseline and
executed synthetic/historical validation.
