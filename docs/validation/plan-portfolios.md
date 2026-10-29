# Ticker planner and long-horizon validation

Date: 2026-10-28. Scope: schema version 2, processed ticker adapter, separate
portfolios, daily bootstrap, retirement-ledger handoff, interactive browser
results and Python PNGs. Method: [plan and app](../methodology/plan-and-app.md);
decision: [ADR 0017](../decisions/0017-ticker-portfolios-and-interactive-results.md).

## Synthetic tests

`tests/conftest.py` writes a small processed-data fixture with distinct
custom total-return histories, matching distribution companions, a missing
date and one fund with shorter vendor history. The tests check:

- supported and unsupported ticker codes; custom level/return reconciliation,
  joint common dates, source hashes and observed-fund inception;
- full-sample descriptive and cash-proxy derivation;
- schema-v2 TOML/JSON round trips, defaults, invalid fields and rejection
  of version 1 without a silent tax-parcel conversion;
- opening balances/cost bases split by portfolio weight, derived income
  and zero-franking mapping into the daily ledger;
- shared daily source draws for different outside/inside mixes, with
  different portfolio outcomes from different weights;
- command-line and runner outputs, including CSV, manifest and PNG files;
- a 35-year daily run, at least 420 month-end band rows per portfolio,
  compact annual summaries and generated ledger figure.

The full repository suite completed with **178 passed, 1 skipped** using a
workspace-local pytest temp directory. The default sandbox temp directory
could not create fixture folders, so that first run was discarded. The skip
is `Streamlit AppTest`: its runner stalls before entering the app script in
this managed Windows sandbox. The real local app was exercised in the
in-app browser, including the 35-year annual chart. The final browser and
repository checks are recorded below.

## Local processed-data and browser checks

The local default selected tickers loaded from the sibling processed
dataset: outside super is 40% `USLCAP3x`, 20% `ITT3x`, 20% `GOLDPM2x`,
20% `COMM`; inside super is 100% `GLSTOCK`. Their shared calibration was
1970-01-02 to 2026-10-27 with
14,028 joint daily returns. The custom and fund-loader paths both completed.
The fund check mixed ticker histories with different starting dates.

An invented 10-year default case completed 16 portfolio paths and two
retirement ledgers; PNGs and report files were produced. The browser ran
an invented example with 16 portfolio paths and one retirement ledger.
The Investments tab showed derived ticker information and two editable
portfolio mixes. The Results tab rendered the historical and future
portfolio charts before the retirement results, plus account, flow and tax
charts. These were interactive Altair charts, inspected through the local
in-app browser. The later browser run used the requested 35-year default
split, 32 portfolio draws and eight retirement draws. It reported five
complete ledgers and three unsupported ones, and showed annual portfolio
bands with sparse year labels, hover values on the retirement fan, and
separate tax and contribution-cap scales. This is manual UI evidence,
separate from the skipped headless `AppTest`.

## Thirty-five-year plot review

A 35-year synthetic case ran through the daily ledger and produced over
35 x 12 month-end portfolio/retirement points. A second invented 35-year
case used actual local processed returns with the requested default split:
32 shared portfolio draws and eight tax-ledger draws. Five ledgers completed
and three reached existing unsupported-rule conditions. The retirement
band therefore uses only five complete paths and is explicitly labelled
conditional. It must not be read as a reliable tail-risk estimate.

The full-size `portfolio_future.png`, `retirement_range.png`,
`retirement_flows.png` and `ledger.png` were visually inspected for the
35-year case. Five-year date ticks kept labels legible; the log-labelled
portfolio axis preserved the early values despite large late compounding.
The review found duplicate rounded cash-flow y-axis labels, a no-flow
panel that needed explicit text, and a caption that did not state completed
ledger count. One complete path ended near $66.9 million, flattening the
central retirement bands on a linear y-axis. The revised plot uses a labelled
log-like scale above $1,000 and remains linear near zero; the median and
upper tail are both visible. The interactive version displayed explicit
$10k, $100k, $1m and $10m ticks. These display defects were corrected. The
plot data itself remained daily-derived.

## Interpretation limits

The long-run case can grow leveraged reconstructed history to very large
values. Its log axis is a display choice, not a probability adjustment.
The source return convention is USD; applying it to the retirement ledger
as AUD is an explicit temporary proxy. Cash distributions are estimated
from historical contributions and do not identify Australian franking.
Complete-path retirement bands omit unsupported tax situations and
need substantially more complete draws for stable tail estimates.

## Annual rebalancing and agreement with the tracker (ADR 0018)

The user reported a historical CAGR of about 10% in the planner for the
default outside mix against about 15% in `portfolio_plot17.py`. The tracker
rebalances annually; the planner then compounded buy and hold. Executed on
the local processed data, 1970-01-02 to 2026-10-27:

| Calculation | Buy and hold | Annual rebalance |
| --- | --- | --- |
| Tracker conventions (`Adj Close`, union calendar, forward fill, lagged return) | 10.19% | 15.25% |
| Planner `analyse_portfolios` (common dates, pre-return reset) | 10.21% | 15.25% |

The rebalanced planner portfolio has 22.2% annualised daily volatility and
−58.1% maximum drawdown; buy and hold has 28.5% and −89.2%. The inside
mix (100% `GLSTOCK`) is unaffected: 10.08% either way. New tests check the
portfolio-accounting worked example (110 against 110.25), a ledger
rebalance that sells 5,000 of the overweight asset, realising a 1,666.67
gain on a 40,000/60,000 cost-to-value parcel, untaxed super switching, and
conservation of total wealth. The ledger now keeps per-asset outside unit
totals instead of summing every parcel daily. One invented 10-year ledger
path fell from 0.89 s to 0.21 s, with all existing ledger reconciliations
unchanged.
