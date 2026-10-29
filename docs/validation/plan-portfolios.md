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

## Depleted paths, path counts and new statistics (ADR 0019)

Run on the invented default plan (10 years, 1,000 portfolio paths and 200
ledger paths, local processed data), before the transfer-cap change:

- 177 paths were funded and 11 depleted. All 11 depleted paths would
  previously have stopped or been excluded.
- 12 were unsupported: whole-balance transfers above the transfer balance
  cap, plus Division 296.
- The whole-balance transfer now stops at the cap, which removes the
  transfer-cap cases.

Combined-portfolio historical statistics on 1970-01-02 to 2026-10-27:

| Portfolio | CAGR | Volatility | Maximum drawdown | Longest drawdown | Worst year | Best year |
| --- | --- | --- | --- | --- | --- | --- |
| Outside super | 15.25% | 22.2% | −58.1% | 5.0 years | −37.7% | +79.5% |
| Inside super | 10.08% | 16.6% | −57.3% | 5.4 years | −39.2% | +44.0% |
| Combined | 13.66% | 19.5% | −52.7% | 4.4 years | −33.1% | +54.6% |

The default 40.9%/59.1% combined starting split is from the invented
balances.

Tests check the withdrawal-rate formula exactly:

- in a flat market with 10% second-year growth,
  `rate * (12 + 13.2) / 12 = 1`;
- a portfolio that doubles at once sustains a 100% rate over two years;
- fewer than 12 month ends gives no rate.

Ledger tests check that unfundable tax is recorded in `tax_unpaid` while the
path runs to its horizon, and that a whole-balance transfer of $2.5 million
moves exactly the $2.1 million cap. Storing indices reduced a 1,000-path,
35-year sample from 365 MB of float returns to 37 MB of indices.

Timings on the owner's desktop varied by a factor of three with background
load, which was about 50–60% CPU during testing. They are indicative only:

| Stage | Time |
| --- | --- |
| Portfolio analysis, 1,000 ten-year paths | 9–15 s |
| One ten-year ledger path, after the valuation changes | 0.35–0.5 s |

## Browser review of the expanded results (2026-10-29)

The local app ran the invented default on local processed data with 1,000
portfolio paths and 100 ledger paths. Results:

- 95 paths calculated, of which 93.7% were funded; 5 were unsupported
  (Division 296).
- Median ending wealth $2.21m nominal, $1.73m in today's dollars.
- Median first retired-year withdrawal rate 6.6%.

Each of the following rendered and was inspected:

- the split 100% allocations and the three-series statistics table;
- the history, drawdown and calendar-year charts;
- the future fan, median comparison and drawdown charts;
- four overlaid distributions plus the withdrawal-rate distribution;
- the retirement bands, withdrawal-rate, shortfall and pension charts;
- the percentile tables;
- the path picker. Choosing the 10th-percentile path (33) re-ran its ledger,
  which ended at $823k, with outside money exhausted around 2032 and the
  pension funding spending thereafter.

The review found and fixed:

- wheel zoom capturing page scrolls;
- loose log-axis domains;
- uneven log histogram ticks;
- truncated percentile tables;
- a fixed 0–100% shortfall axis.

A 34-year command-line check (born 1994, horizon shortened to 2060-06-30)
produced legible five-year ticks and labelled log axes in the PNGs. 37 of 40
ledger paths reached the unimplemented Division 296 rule, so long-horizon
retirement statistics are conditional; implementing Division 296 is the
next requirement for 30-year retirement results.

## Contributions, flows, milestones and progress (2026-10-29)

Tests:

- `household_flows` sums exactly to each financial year's change in total
  wealth on a busy random ledger path;
- `account_flows` nets the pension transfer to zero and matches pension
  payments;
- fixed outside contributions, the stop at retirement and the indexed step-up
  behave as specified (ADR 0020);
- the salary-sacrifice percentage maps to the ledger;
- progress callbacks arrive in order through every stage.

The browser review on local data checked:

- labelled donuts with ticker legends;
- the portfolio stats line;
- the 2×2 work estimate;
- the year, month and day birth fields;
- dashed milestone lines;
- "Jul 2026 – Jun 2027" year labels with age;
- the sorted, hoverable ending-wealth chart;
- the withdrawal-rate chart with sustainable-rate references and its
  explanation;
- the money in and out chart and the per-account transfer charts.

The review found and fixed:

- an apostrophe in a field name, which stopped Vega-Lite rendering the
  ending-wealth chart;
- truncated metrics and legend overlap in narrow columns;
- per-account charts that collapsed in three columns.

The first progress stage had appeared stuck. Two causes:

- the market load ran before the bar was drawn;
- each Windows worker re-ran the whole app as its main module, which took
  49 s before the first ledger result and once broke the pool.

Fixed by running at the top of the page, hiding `__main__` on submission
and keeping a warm pool. After the fix the bar reported every stage, and
the first ledger results arrived 10 s after the ledger stage began. The
desktop was at about 96% CPU from other programs during the check, so
absolute times are not representative.

After the user asked whether the money in and out chart should use medians, the retirement section gained a typical-year version. It shows the median of each flow across all calculated paths, with interquartile tooltips and the median net change with whiskers. A test checks that each path's yearly flow columns sum to its net change. The single-path chart in section 5 remains, labelled as one path.
