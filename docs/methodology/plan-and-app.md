# Ticker portfolios and the retirement planner

Date: 2026-10-28. Status: schema version 2, local ticker adapter, daily
portfolio simulations and interactive results implemented. Decision:
[ADR 0017](../decisions/0017-ticker-portfolios-and-interactive-results.md),
which updates the market and input conventions of
[ADR 0016](../decisions/0016-plan-file-and-browser-app.md).

## Purpose and user requirements

A plan describes one Australian tax resident's outside-super and inside-super
portfolios, employment, spending and super access. The user asked to select
the tickers used by the companion investment tracker, including custom
histories reaching back to 1970; derive return and income information from
processed data; enter one portfolio allocation for each account; inspect
their historical behaviour and simulated risk before retirement findings;
and make plots interactive and readable over 30 or more years. The local
browser app, command line and TOML/JSON file share one validated plan.

## Inputs and provenance

`assets` is a list of ticker codes available to **both** portfolios. It is a
universe selection, not a third account. The supported local catalogue is:

| Source | Tickers | Return field |
| --- | --- | --- |
| Processed custom histories | `USLCAP`, `GOLDPM`, `LTT`, `ITT`, `STT`, `COMM`, `USLCAP3x`, `LTT3x`, `ITT3x`, `GOLDPM2x`, `GLSTOCK`, `GLBOND`, `GLSTBOND` | Registry total-return level and daily return columns |
| Processed funds | `SHY`, `IEF`, `TLT`, `VT`, `BND`, `BWX`, `ISHG`, `BWZ`, `UPRO`, `TYD`, `TMF`, `GLD`, `UGL`, `DBC` | `Vendor Total Return` in `distributions/fund_prices.csv` |

The custom series come from the sibling `financial_datasets/data/processed`
directory. Each uses the registry-defined total-return level and the matching
file in `distributions/`, which supplies `Distribution Return` and provenance
counts. Fund series use processed vendor total returns and distribution
contributions. Files remain in the sibling project; plans contain codes, not
copied data or machine paths. The loader records SHA-256 hashes and first/last
dates in `manifest.json`. `FINANCIAL_DATASETS_PROCESSED` can override the
processed-data location. There is no network download or arbitrary ticker
lookup.

Custom pre-fund segments can be reconstructed or modelled. Fund ticker
histories start at available vendor inception. For any selection, the return
sample uses the **intersection of recorded dates**. A step across a missing
date compounds source total-return levels between the shared dates; no
observed zero return is inserted. The loader requires at least 252 joint
returns and checks dates, finite values, positive levels and reconciliation
between custom published levels and returns. These are nominal USD return
conventions, not Australian dollar observations. See
[data adapters](data-adapters.md) for the wider dataset contract.

The app shows full-sample descriptive measures for each ticker:

- **CAGR:** `(last total-return level / first level) ** (365.25 / elapsed calendar days) - 1`.
- **Annualised daily volatility:** sample standard deviation of daily simple
  returns times `sqrt(252)`.
- **Maximum drawdown:** minimum of `level / running maximum(level) - 1`.
- **Cash contribution proxy:** mean, over complete calendar years, of the sum
  of daily `Distribution Return` contributions. It is a planning split of
  already included total return, not a buy-and-hold income yield, Australian
  tax statement or additional return.

The ledger uses the cash proxy as its existing quarterly estimated-income
split: at quarter end `q = annual proxy / 4`; it removes `q` from the current
unit price and pays that amount in cash. Total wealth before tax is unchanged
by this split. The data do not identify Australian franking, so the planner
sets the franked fraction to zero. Fund expenses and financing already in
total-return histories are not charged again. See the
[retirement ledger](retirement-ledger.md) for the account convention.

## Plan schema and accounting

Schema version 2 uses:

| Section | Relevant fields |
| --- | --- |
| `[plan]` | Name, start date from 2026-07-01, requested years |
| `[person]` and `[employment]` | Birth date, retirement age, cover, salary, sacrifice, payday |
| `assets` | Selected local ticker codes |
| `[outside]` | Cash, cash buffer, `investment_balance`, `opening_cost_base`, `opening_acquired`, `weights`, `rebalance` |
| `[super]` | Balance, prior 30 June total super balance, `weights`, `rebalance` |
| `[spending]`, `[pension]`, `[assumptions]` | Spending, pension transfer and projected-rule assumptions |
| `[market]` | Portfolio path count, retirement path count, seed, mean block length |

`outside.weights` and `super.weights` each sum to one. They represent the
opening allocation and future purchases or contributions in that account.
There is no second per-asset holdings entry. The outside opening value and
cost base are allocated by weight; every opening parcel takes the entered
acquisition date. A $10,000 outside balance, $7,000 aggregate cost base and
60/40 mix create $6,000/$4,000 positions and $4,200/$2,800 cost bases. This
approximates actual parcels purchased at different prices or dates. The super
opening balance is likewise divided by its weights. A positive balance
requires an allocation, and the outside allocation also governs future
surplus investments.

`normalize_plan` fills defaults, rejects unknown fields and reports all
field paths with errors. Version 1 files are rejected with a conversion
message: silently merging their CGT parcels would discard tax positions.
The invented default uses 40% `USLCAP3x`, 20% `ITT3x`, 20%
`GOLDPM2x` and 20% `COMM` outside super, and 100% `GLSTOCK` inside
super, as requested by the user. Personal saved plans go to ignored `plans/`.

## Daily simulation algorithm

The source return matrix has one column per selected ticker. The stationary
bootstrap chooses a joint source row for all tickers on each step. It
continues the source block with probability `1 - 1 / block_length`, or
starts another with probability `1 / block_length`; source rows wrap at the
end. Block length counts **observations**. The user sets mean block length,
path count and seed. Each path has a stable stream keyed by path number.
Both portfolios receive the same source-row sequence on a path, so their
differences reflect weights. See [resampling](resampling.md).

For each portfolio, positions begin at `100 * weight[ticker]`. Every daily
return updates its position:
`position[t,ticker] = position[t-1,ticker] * (1 + return[t,ticker])`.
Portfolio value is their sum. Each account's `rebalance` policy is
`annual` (default) or `none`. Under `annual`, on the first return
observation of each calendar year the positions reset to
`value[t-1] * weight[ticker]` before that day's return. This is the Stage 1
and investment-tracker convention. Under `none` the weights drift (buy and
hold). Historical growth uses the same accounting on the full shared sample.
[ADR 0018](../decisions/0018-planner-annual-rebalancing.md) records why: on
the 1970–2026 shared sample, the default 40/20/20/20 outside mix compounds
at 15.25% a year rebalanced and 10.21% buy and hold. The tracker reports
15.25% with its own calendar convention. In the retirement ledger, an
outside-super rebalance is a set of CGT disposals; inside super it is an
untaxed unit switch.

The future target is a weekday accounting template from plan start to its
supported end, not a forecast of exchange holidays. The ledger also
processes calendar events on closed dates. The planner stops before the
income year in which the person reaches Age Pension age, because SAPTO and
Age Pension are unsupported. A longer requested horizon is shortened and
reported.

Three series are reported: each account's portfolio and a **combined**
portfolio. The combined series starts in proportion to the opening outside
investment balance and super balance. It then lets each account compound
under its own policy, without moving money between accounts, because super
and outside money cannot be pooled. With $450,000 outside and $650,000 in
super, the combined series starts 40.9%/59.1%.

The paths store only donor-row indices, one 32-bit integer per path and
day. Each step gathers the joint returns. Statistics accumulate as the
loop runs:

- **Terminal growth** of $100, and annualised growth
  `(terminal / 100) ** (365.25 / elapsed days) - 1`.
- **Annualised volatility:** the sample standard deviation of the path's
  daily returns times `sqrt(252)`.
- **Maximum drawdown:** the lowest `value / running peak - 1`.
- **Longest drawdown:** the most calendar time between a peak and either
  recovery to it or the horizon.
- Month-end value and drawdown snapshots, which feed the pointwise 5th, 25th,
  50th, 75th and 95th percentile bands.

Historical statistics add the worst and best calendar years and the share
of positive years. A full calendar-year return is its final wealth mark
divided by the prior year-end mark minus one; partial years are excluded.
Monthly and yearly values summarize daily compounding. For example, +10%
then -10% turns $100 into $99, a -1% total return.

The **sustainable withdrawal rate** of a path is the largest first-year
withdrawal it could fund. It is expressed as a fraction of the portfolio's
value at the retirement date, or at plan start if that is later.
Withdrawals are paid monthly at each month end, one twelfth of the annual
amount. The annual amount rises by the plan's spending growth every
12 months, and the portfolio must not run out before the horizon. Let
`G_k` be the growth factor from retirement to the `k`-th month end.
Proportional sales leave each later month's growth factor unchanged, so
remaining wealth is nonnegative exactly while
`1 >= rate * sum_k (1 + g) ** floor(k / 12) / (12 * G_k)`. Every term is
positive, so the horizon binds and
`rate = 1 / sum_k (1 + g) ** floor(k / 12) / (12 * G_k)`. In a flat market
over two years with 10% growth, `rate = 12 / (12 + 13.2) = 0.476`. The rate
is pre-tax and ignores salary, contributions and super access. It depends
strongly on the remaining horizon, which ends before Age Pension age, so it
is not comparable with 30-year "4% rule" studies. The rate is undefined
with fewer than 12 month ends.

The first `retirement_paths` of those same joint draws run through the
[daily tax ledger](retirement-ledger.md). USD source returns are explicitly
applied as an **AUD proxy** because USD/AUD FX and Australian distribution
components are absent. Ledgers run in worker processes when there are
more than four; each worker returns only a summary row, month-end account
series and financial-year rows. Every calculated path is classified:

- **funded:** all spending and tax was paid;
- **depleted:** some spending shortfall or unpaid tax arose. These paths stay
  in every band and rate. Before 2026-10-28 an unpaid tax debt stopped the
  ledger, which silently removed the worst paths. See
  [ADR 0019](../decisions/0019-retirement-path-results.md).
- **unsupported:** an existing `UnsupportedRule` was reached, such as
  Division 296 above $3 million. Its reason is shown, and the path is
  excluded from bands and rates, which are therefore conditional.

Per path the planner reports:

- ending wealth, nominal and deflated by `(1 + CPI) ** years` into
  today's dollars;
- ending outside and super/pension wealth, and wealth at the retirement date;
- spending paid, shortfall, shortfall years, and the first shortfall date;
- the date outside-super money (cash plus investments) first runs out;
- unpaid tax, personal tax assessed and fund tax;
- pension payments, and the pension balance at commencement;
- withdrawal rates.

A **withdrawal rate** for a full financial year that starts on or after
the retirement date is `(spending paid + tax paid) / wealth at 1 July`.
Each path reports its first, median and highest rate. Financial-year rows
also record pension payments and super lump sums. Retirement bands summarise
total, outside, super-plus-pension and pension-account wealth at month ends.

The **representative ledger** is the calculated path whose *ending* wealth
is closest to the median ending wealth. It is re-run in full for its
daily ledger and events. Its number is its position in the shared draw
sequence, not a rank. Its intermediate dates need not be median. The app can
also re-run any other path. Defaults are 1,000 portfolio paths and 100
ledger paths. With fewer than 100 calculated ledger paths, the planner
warns that tail percentiles are noisy.

## Results and reproducibility

The Results tab has five sections, each chart followed by an explanation:

1. **Your portfolios.** Each account's allocation on its own 0–100% axis,
   with balance and rebalancing policy, and the combined split. A
   whole-portfolio statistics table covers outside, inside and combined.
   Ticker-level source statistics sit in an expander.
2. **Historical behaviour.** Growth of $100 on a log axis, drawdown below the
   running peak, and calendar-year returns for all three series.
3. **Future simulations.** A step-by-step description of the calculation
   with the run's actual dates, row counts, block length, seed and path
   count. Then:
   - a fan for the selected portfolio;
   - median paths compared;
   - median and 5th-percentile drawdown;
   - four distributions (ending value on a log axis, annualised growth,
     volatility, maximum drawdown), each overlaying outside and inside super
     with dashed medians;
   - the sustainable-withdrawal-rate distribution;
   - a percentile table;
   - calendar-year return bands.
4. **Retirement outcomes.** An explanation of the ledger and the path
   classes. Then:
   - headline metrics (paths calculated, share funded, median ending wealth
     nominal and in today's dollars, wealth at retirement, withdrawal rates,
     total tax);
   - wealth bands selectable by account;
   - ending-wealth distributions by account;
   - withdrawal-rate bands by financial year;
   - the share of paths with a shortfall each year;
   - pension payment bands;
   - an outcome percentile table, and every path in a formatted table.
5. **One path in full.** The median-ending path by default, or the 10th or
   90th percentile, worst, best or any numbered path, re-run on demand. It
   shows balances by account, financial-year flows, a year-by-year tax,
   cap and pension table, tax and cap charts, pension minimum against paid,
   a filterable event log and CSV downloads.

Charts show hover values. Dragging pans, Shift+scroll zooms and a
double-click resets. Plain scrolling scrolls the page, because an
earlier version zoomed the chart under the pointer. Python generates PNG
counterparts for review: history, the future fan for each series, the four
overlaid distributions, the retirement range and the flows. Long-horizon date ticks step five years from 25 years onward;
growth charts use labelled log axes with a data-fitted domain; no-flow
panels say so explicitly. The retirement wealth fan uses a log-like y-axis
when its maximum 95th percentile exceeds 20 times the larger of $1,000 and
the maximum median. It stays linear from $0 to $1,000, so zero wealth remains
visible. The plot explicitly labels this scale. The change affects display only, not path values or quantiles.

The browser starts with `financial-simulations ui`; the command line uses
`financial-simulations plan <plan-file>`. Both write an ignored
`output/plans/<plan-name>/` folder. It contains the normalized `plan.toml`,
`daily.csv`, `events.csv`, `annual.json`, `asset_summary.csv`,
`portfolio_summary.csv`, `portfolio_history.csv`, `portfolio_bands.csv`, `portfolio_outcomes.csv`,
`portfolio_annual.csv`, `retirement_paths.csv`, `retirement_bands.csv` (by account), `retirement_annual.csv`,
`ledger.png`, five other PNGs and `manifest.json` with source hashes,
code/rule manifests, sample settings and notes. None belongs in Git.

## Validation, limitations and references

Synthetic fixtures in `tests/test_plan_markets.py` and
`tests/test_plan.py` cover ticker parsing, source reconciliation, income
proxy, schema round trips/failures, portfolio-to-ledger handoff, outputs
and a 35-year horizon. Executed checks are recorded in
[planner validation](../validation/plan-portfolios.md). The local browser
Investments and Results views and 10- and 35-year PNGs were inspected.

These are conditional resamples of historical or reconstructed USD sources,
not forecasts. Full-sample CAGR is descriptive. Bootstrap blocks preserve
local sequences and joint co-movement but can repeat rare events or miss new
regimes. Pointwise percentile bands are not whole-path confidence intervals.
Leveraged synthetic histories can compound to very large values over decades;
a log axis improves visibility, not credibility. Small numbers of complete
ledger paths make tail percentiles and shortfall rates unstable. The cash
proxy, zero franking, aggregate opening tax position and AUD return proxy
limit tax interpretation. Division 296 is not implemented. Any ledger path whose
total super balance passes $3 million at a 30 June is unsupported. On long
horizons this excludes most paths: in a 34-year check, 37 of 40 paths. Long-horizon
retirement statistics are therefore conditional on the low-growth paths,
and the app says so.

References: processed source data and provenance in the sibling
`financial_datasets` project, identified by run-manifest hashes;
[resampling](resampling.md), [portfolio accounting](portfolio-accounting.md),
[retirement ledger](retirement-ledger.md), and the
[Australian rule register](../rules/au-2026-27.md).

Revision history: 2026-10-28 version 1 plan and browser app under ADR 0016;
2026-10-28 version 2 ticker portfolios and portfolio-first interactive
results under ADR 0017.
