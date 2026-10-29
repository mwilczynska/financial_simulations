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
| `[outside]` | Cash, cash buffer, `investment_balance`, `opening_cost_base`, `opening_acquired`, `weights` |
| `[super]` | Balance, prior 30 June total super balance, `weights` |
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
Portfolio value is their sum. This is **buy and hold**: weights drift.
Historical growth uses the same accounting on the full shared sample. The
separate Stage 1 default experiment uses annual rebalancing, so its
statistics need not match the planner's.

The future target is a weekday accounting template from plan start to its
supported end, not a forecast of exchange holidays. The ledger also
processes calendar events on closed dates. The planner stops before the
income year in which the person reaches Age Pension age, because SAPTO and
Age Pension are unsupported. A longer requested horizon is shortened and
reported.

Portfolio results include historical CAGR, volatility and drawdown; future
month-end 5th, 25th, 50th, 75th and 95th pointwise values; and each path's
terminal growth, calendar-time annualised growth, daily annualised volatility
and maximum drawdown. A full calendar-year return is its final wealth mark
divided by the prior year-end mark minus one; partial years are excluded.
Monthly and yearly values summarize daily compounding. For example, +10%
then -10% turns $100 into $99, a -1% total return.

The first `retirement_paths` of those same joint draws run through the
[daily tax ledger](retirement-ledger.md). USD source returns are explicitly
applied as an **AUD proxy** because USD/AUD FX and Australian distribution
components are absent. A path reaching an existing `UnsupportedRule` is
recorded with its reason. Retirement bands use only complete paths; the
completion count and exclusion are shown. They are not unconditional risk
estimates. The representative ledger is the complete path whose *ending*
wealth is closest to median ending wealth. Its intermediate dates need not
be median.

## Results and reproducibility

The app presents (1) entered portfolios and ticker source statistics;
(2) historical portfolio growth; (3) future portfolio bands, growth and
drawdown distributions, and full-year return bands; (4) retirement wealth
bands, completion/shortfall counts, representative account balances,
financial-year flows, tax/contribution plots and a year-by-year table.
Interactive Altair charts have hover values and zoom, with a short
explanation after each. Python generates PNG counterparts for review.
Long-horizon date ticks step five years from 25 years onward; growth charts
use labelled log axes; no-flow panels say so explicitly. The retirement
wealth fan uses a log-like y-axis when its maximum 95th percentile exceeds
20 times the larger of $1,000 and the maximum median. It stays linear from
$0 to $1,000, so zero wealth remains visible. The plot explicitly labels
this scale. The change affects display only, not path values or quantiles.

The browser starts with `financial-simulations ui`; the command line uses
`financial-simulations plan <plan-file>`. Both write an ignored
`output/plans/<plan-name>/` folder. It contains the normalized `plan.toml`,
`daily.csv`, `events.csv`, `annual.json`, `asset_summary.csv`,
`portfolio_history.csv`, `portfolio_bands.csv`, `portfolio_outcomes.csv`,
`portfolio_annual.csv`, `retirement_paths.csv`, `retirement_bands.csv`,
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
limit tax interpretation.

References: processed source data and provenance in the sibling
`financial_datasets` project, identified by run-manifest hashes;
[resampling](resampling.md), [portfolio accounting](portfolio-accounting.md),
[retirement ledger](retirement-ledger.md), and the
[Australian rule register](../rules/au-2026-27.md).

Revision history: 2026-10-28 version 1 plan and browser app under ADR 0016;
2026-10-28 version 2 ticker portfolios and portfolio-first interactive
results under ADR 0017.
