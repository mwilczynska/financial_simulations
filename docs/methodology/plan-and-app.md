# Ticker portfolios and the retirement planner

Date: 2026-10-28. Status: schema version 3 (reads 2), local ticker adapter, daily
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
| Processed custom histories | `USLCAP`, `GOLDPM`, `LTT`, `ITT`, `STT`, `COMM`, `USLCAP3x`, `LTT3x`, `ITT3x`, `GOLDPM2x`, `GLSTOCK`, `GLBOND`, `GLSTBOND`, `USLCAP2x`, `GLSTOCK2x`, `LTT2x`, `ITT2x`, `STT2x`, `GLBOND2x` | Registry total-return level and daily return columns |
| Processed funds | `SHY`, `IEF`, `TLT`, `VT`, `BND`, `BWX`, `ISHG`, `BWZ`, `UPRO`, `TYD`, `TMF`, `GLD`, `UGL`, `DBC`, `SSO`, `UST`, `UBT` | `Vendor Total Return` in `distributions/fund_prices.csv` |

The 2x daily-reset custom series follow current funds where one exists
(`USLCAP2x` SSO, `GLSTOCK2x` WLDU, `ITT2x` UST, `LTT2x` UBT): a calibrated
model of the base dataset before fund inception, then observed fund returns.
`STT2x` and `GLBOND2x` have no 2x fund and are modelled on every row; see the
upstream methodology for each. The WLDU fund history itself is not offered
because it began in March 2026, short of the 252 returns the loader requires;
`GLSTOCK2x` carries that exposure over the full sample.

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

Schema version 3 uses the fields below. Version 2 files, which name one `rule`, still load (ADR 0043).

| Section | Relevant fields |
| --- | --- |
| `[plan]` | Name, start date from 2026-07-01, requested years |
| `[person]` and `[employment]` | Birth date, retirement age, cover, salary, `salary_sacrifice_per_year`, `salary_sacrifice_percent` (fraction of salary, added to the dollar amount), payday |
| `assets` | Selected local ticker codes |
| `[outside]` | Cash, cash buffer, `cash_interest`, `investment_balance`, `opening_cost_base`, `opening_acquired`, `weights`, `rebalance`, `saving` (`surplus` or `fixed`), `contribution_per_year`, `contribution_indexed` |
| `[super]` | Balance, prior 30 June total super balance, `weights`, `rebalance`, `realised_gains` (share of the fund's unrealised gains realised each year; default 0.2, an assumption; ADR 0029) |
| `[spending]`, `[pension]`, `[assumptions]` | `annual` (today's dollars), `real_change` (a year, on top of CPI; default 0), `retirement` (`same` default, `amount` with `retirement_annual`, or `percent` with `retirement_percent` of total wealth on the retirement date), `compare` (the spending strategies to compare, a list of `fixed` (default), `guyton_klinger`, `vanguard` and `percent`, kept in that order; anything but `["fixed"]` requires `retirement = "percent"`, so every compared strategy starts from the same spending; a version 2 `rule` loads as a one-item list), `minimum`, `maximum` (today's dollars, CPI-indexed), `guardrail_band`, `guardrail_step`, `ceiling`, `floor`; pension transfer; projected-rule assumptions. A `planning_age` in older files is accepted and ignored (ADR 0041). A legacy nominal `annual_growth` is read as `real_change = (1 + annual_growth) / (1 + cpi) - 1` (ADR 0025) |
| `[mortgage]` | `balance` (0 = no loan), `interest_rate`, `years`, `extra_share` ([home loan](home-loan.md), ADR 0052); a loan needs `person.homeowner` |
| `[market]` | Portfolio path count, retirement path count, seed, mean block length |

**Spending strategies** ([ADR 0043](../decisions/0043-compared-spending-strategies-in-the-plan.md)). A normalized
plan lists its compared strategies in `spending.compare` and has no single rule. `strategy_plan(plan, rule)`
returns a copy with `spending.rule` set, and `build_inputs` uses that rule (a plan comparing one strategy needs
no copy). Every strategy keeps its own parameters in the plan, so ticking one off and on again restores them.
The app's Retirement tab has a tick box per strategy and shows the settings of each ticked one.

**Running compared strategies** ([ADR 0044](../decisions/0044-run-every-strategy-on-shared-paths.md)). A run
puts every compared strategy through the daily ledger on **every** retirement path; no strategy uses fewer
paths. Each worker task takes a chunk of paths and, for each path, gathers its market draw once and runs every
strategy's ledger on it. The strategies therefore see identical markets, and any difference between them on a
path comes from the strategy alone. Before the retirement date their ledgers are identical, so every strategy
reaches retirement with the same wealth on each path (a test checks this). `run_plan` returns the first
compared strategy's `PlanRun`; its `strategies` field holds every strategy's `PlanRun`, by rule in the plan's
order, each with its own representative path, bands, tables and notes, and all sharing one portfolio analysis.

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

The future target is an observation calendar from plan start to its
supported end, not a forecast of exchange holidays
([ADR 0034](../decisions/0034-future-observation-calendar-and-accounting-end.md)).
Each sampled return is one historical observation, so the calendar keeps
the sampled history's density: observations per 365.25 calendar days over
the joint history (about 247 for the default tickers, against 261
weekdays). `observation_calendar` keeps weekdays in order while the count
stays within ceil(density x elapsed days / 365.25), so the dropped weekdays
are evenly spread. Expected growth and variance per calendar year then
match the history. The same calendar serves the portfolio paths, the
retirement-length withdrawal paths and every ledger run. The constant-CAGR
reference path compounds each step over its calendar days, so it grows at
the CAGR on any calendar. The ledger's accounting end is the plan's
requested end, which may follow the last observation by a weekend; those
days carry the last close, so a 30 June on a weekend is still assessed. The
ledger also processes calendar events on closed dates. The planner runs past Age
Pension age with the single Age Pension and SAPTO
([age-pension.md](age-pension.md)). It stops only the day before age 110;
a longer requested horizon is shortened and reported. `person.homeowner`
(default true) and `person.other_assets` (default 0) feed the assets test.

`[year_to_date]` holds the opening position for the start's financial year
([ADR 0036](../decisions/0036-opening-year-to-date-position.md)):

- **Year-to-date amounts.** Salary received after sacrifice, salary
  sacrificed, PAYG withheld, concessional contributions the fund has
  received, non-concessional contributions, other taxable income (interest,
  unfranked dividends and net capital gains, assessed as ordinary income),
  franked dividends with their credits, and Age Pension received. Its
  taxable part uses the year's basic plus taxable-supplement share.
- **Amounts in flight.** `pending_employer_contributions` arrive seven
  business days after the start. `prior_year_tax` is last year's tax still
  to settle (negative for a refund), due 31 October or at the start if
  later.
- **Confirmation.** A start after 1 July is rejected unless `entered = true`,
  so a part year is never silently assessed as a whole year with full-year
  thresholds. Zeros are a valid confirmed answer.
- **Not covered.** Fund income earlier in the year (its tax is taken as
  reflected in the opening super balance), Division 296 earnings before the
  start, and capital gains that would attract the minimum tax.

The pension commences on the later of `pension.start_age` and the date super
becomes accessible (retirement after preservation age, or 65). An earlier
requested age is moved to that date with a run note, because a
transition-to-retirement pension is not modelled
([ADR 0032](../decisions/0032-defer-early-pension-to-super-access.md)).

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
- Month-end value snapshots, which feed the pointwise 5th, 25th, 50th, 75th
  and 95th percentile bands.

Historical statistics add the worst and best calendar years and the share
of positive years. A full calendar-year return is its final wealth mark
divided by the prior year-end mark minus one; partial years are excluded.
Monthly and yearly values summarize daily compounding. For example, +10%
then -10% turns $100 into $99, a -1% total return.

Until 2 November 2026 a separate set of draws from the retirement date to
`assumptions.planning_age` produced two pre-tax, portfolio-only withdrawal
rates per path (ADR 0021 and ADR 0039 describe the method).
[ADR 0041](../decisions/0041-remove-portfolio-withdrawal-rates-and-plots.md)
removed them: the daily tax ledger answers whether the money lasts, with
tax and the Age Pension, over the years simulated.

The first `retirement_paths` of those same joint draws run through the
[daily tax ledger](retirement-ledger.md). USD source returns are explicitly
applied as an **AUD proxy** because USD/AUD FX and Australian distribution
components are absent. Ledgers run in worker processes when there are
more than four; each worker returns only a summary row, month-end account
series and financial-year rows. Every calculated path is classified:

- **funded:** all spending and tax was paid, and the tax owed at the
  horizon can be settled;
- **depleted:** some spending shortfall or unpaid tax arose, or the tax owed
  at the horizon exceeds the money available to settle it (outside wealth,
  the pension, and accumulation if accessible at the end). These paths stay
  in every band and rate. Before 2026-10-28 an unpaid tax debt stopped the
  ledger, which silently removed the worst paths. See
  [ADR 0019](../decisions/0019-retirement-path-results.md).
- **unsupported:** an existing `UnsupportedRule` was reached, such as an
  excess transfer balance. Its reason is shown, and the path is excluded
  from bands and rates, which are therefore conditional. Division 296 is
  assessed rather than rejected since 2026-10-29
  ([ADR 0028](../decisions/0028-division-296-tax.md)).

Per path the planner reports, in today's dollars (`retirement/real.py`,
[ADR 0026](../decisions/0026-results-in-todays-dollars.md)):

- ending wealth (and `Ending wealth, nominal`, kept for the CSV only);
- tax owed at the end: tax already incurred but not yet paid at the
  horizon. That is assessments not yet due (refunds count against them),
  pending Division 296, unpaid tax and the ledger's estimate for an
  unassessed final period. It is deflated at the end date. Also reported:
  ending wealth after tax owed (the headline ending figure in the app) and
  whether that tax can be settled
  ([ADR 0035](../decisions/0035-fund-tax-accrual-and-tax-owed-at-the-horizon.md));
- ending outside and super/pension wealth, and wealth at the retirement date;
- spending paid, shortfall, shortfall years, and the first shortfall date;
- the date outside-super money (cash plus investments) first runs out;
- unpaid tax, personal tax assessed and fund tax;
- pension payments, and the pension balance at commencement;
- retirement spending: the starting amount (twelve times the first monthly
  need on or after the retirement date), the starting withdrawal rate (that
  amount over total wealth the day before), the lowest spending paid in a
  full retired year, the deepest cut below the start, and the number of
  retired years more than 1% below it;
- withdrawal rates.

A **withdrawal rate** for a full financial year that starts on or after
the retirement date is `(spending paid + max(tax paid, 0) + Division 296
− Age Pension) / wealth at 1 July`. Both parts are nominal, from the
ledger's own dollars, so the ratio is the nominal rate whatever the start
date and CPI
([ADR 0039](../decisions/0039-withdrawal-rate-basis-and-claims.md)).
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

**Saving outside super.** In `surplus` mode every dollar of take-home pay
left after tax, spending and the cash buffer is invested. In `fixed` mode
`contribution_per_year / 26` is invested each payday, as far as cash above
the buffer allows. With `contribution_indexed`, that amount rises each
1 July by the CPI assumption. Leftover pay stays in cash. Contributions from
pay end at the retirement date
([ADR 0020](../decisions/0020-outside-contributions-stop-at-retirement.md)).
From then on all cash above the buffer, such as unspent pension payments,
is reinvested in the outside portfolio. This is not a plan setting
([ADR 0030](../decisions/0030-reinvest-surplus-cash-in-retirement.md)).

The You tab shows a first-year estimate of where pay goes, using the
2026-27 rules and `assess`:

- super guarantee plus sacrifice against the concessional cap, with a
  warning above the cap;
- income tax on salary less sacrifice;
- the amount added to outside investments.

The estimate excludes investment income. Birth dates are entered as year,
month and day fields.

**Saving plans.** The *Plan* menu in the top bar holds the plan name, which is also the file
name. **Save** writes `plans/<plan-name>.toml` and shows which file the app is
working on. After a name change, **Rename** writes the new file and removes
the old one; **Save** keeps both. **Open** loads a saved plan. Import and
browser download sit in an expander.

### Saved results

In the *Plan* menu, **Also save results** makes **Save** save the results on screen with the plan, and
**Open saved results** opens them again ([ADR 0050](../decisions/0050-saved-run-results.md),
[ADR 0051](../decisions/0051-save-results-from-the-plan-menu.md)). The box is greyed out when there are no results
or the inputs have changed since the last run; **Also save every path's full daily ledger** is greyed out unless it
is ticked, and off by default. A save writes
`output/saved_runs/<plan-name>/` (git-ignored), replacing any earlier save of the same plan name
([ADR 0052](../decisions/0052-one-saved-run-per-plan-name.md)), with:

- `run.json` (format version, time, note, plan, rule, code and market manifests) and `plan.toml`;
- the market's daily history returns and ticker statistics, and every market path's sampled history rows
  (`portfolio_draws.npz`: the first row and the steps between rows, compressed);
- the portfolio results, and each strategy's path outcomes, yearly rows, account bands and month-end balances by
  path, as Parquet;
- each strategy's median-path ledger in full;
- only when *Also save every path's full daily ledger* is ticked, every calculated path's ledger.

A ledger set is `daily.parquet` and `events.parquet` with a `path` column, one row group per path, and `years.json`
holding each path's financial-year records and outstanding liabilities. For analysis,
`pd.read_parquet(".../ledgers/daily.parquet", filters=[("path", "==", 7)])` reads one path and leaving out
`filters` reads all of them. In code, `saved_runs.load_run(folder)` returns the `PlanRun` the app uses and
`LedgerStore(folder).read(path)` one path's `LedgerResult`.

The full ledgers are produced at save time: every calculated path is re-run on the run's stored draws in the worker
pool and written, which can take longer than the run itself. The menu shows the expected size (about 0.6 kB per path
per strategy per plan year for the results, plus about 21 kB per path per strategy per year for the full ledgers).

Opening a saved run loads its plan and results together; nothing the run summarised is recalculated. The Paths page
reads a path's ledger from the saved ledgers when present, otherwise re-runs it from the saved market and draws, so
it is the ledger the run summarised. The plan editor gets a copy of the opened plan, so edits never change the
opened results' plan. If the model's Python source has changed since the save, the menu says the
results are those of the saving code. Saves are written to a hidden partial folder and swapped with the
earlier save only when complete; if that fails, the earlier save is put back.

**Inflation.** Results are in today's dollars, the dollars of the plan's
start date ([ADR 0026](../decisions/0026-results-in-todays-dollars.md)). The
Method page explains the conversion:

- A balance on date `d` is divided by `(1 + CPI) ** ((d - start) / 365.25)`.
- A flow during a financial year is divided by `(1 + CPI) ** n`, where `n` is
  the number of whole financial years since the opening year. That is the
  step on which spending rises, so CPI-indexed spending is flat. Flows
  deflated in yearly steps over wealth deflated by days would not keep a
  nominal ratio for a start after 1 July, so withdrawal rates are computed
  from nominal amounts.
- An `Inflation` flow in the money in and out charts is the buying power
  wealth lost in the year, so each year's flows still sum to the change in
  real wealth.
- Section 3 deflates each month-end portfolio value, so growth and ending
  value are after inflation. Volatility and drawdowns stay on nominal daily
  returns.
- Section 2's history is nominal, because the source data have no
  inflation series.
- The ledger runs in nominal dollars; the event log and the CSV downloads in
  section 5 are its nominal records.

Inputs:

- Spending is entered in today's dollars and rises with CPI, plus an
  optional real change (ADR 0025).
- Salary and salary sacrifice rise each 1 July by the wage-growth assumption
  when `employment.salary_indexed` is true (the default; ADR 0024). Otherwise
  they stay constant in nominal dollars.
- Fixed outside additions are indexed only when that option is ticked.
- Rule thresholds are projected with CPI and wages.

**Block length.** The Assumptions tab explains the average block length in
plain terms: average run length in trading days, the jump probability
`1 / block_length`, and the trade-off between keeping longer historical
patterns and mixing eras.

### App layout since 10 November 2026

[ADR 0047](../decisions/0047-app-layout-and-one-visual-system.md) replaced the sidebar and the single results page.
A bar that stays on screen holds the pages, the state of the results, the *Plan* menu and *Run plan*. Only the open
page is drawn, and a finished run opens Outcomes.

| Page | Contents |
| --- | --- |
| Plan | The inputs, in tabs You, Investments, Retirement and Assumptions |
| Outcomes | The outcome tiers and headline figures, then tabs *Wealth*, *Risk over time*, *Spending*, *Age Pension*, *Money in and out* and *Tables* (old section 4) |
| Paths | One path's daily ledger, in tabs *Markets, wealth and money*, *Transfers between accounts*, *Year by year* and *Event log*; or a group of paths, in tabs *Markets, wealth and money* and *Year by year* (old section 5) |
| Compare | The compared strategies' statistics, wealth over time and yearly flows; shown when several strategies ran |
| Markets | The portfolios, their history and the simulated futures (old sections 1 to 3) |
| Method | How results are calculated, today's dollars, saved files and rule assumptions |

With several strategies, Outcomes and Paths show one strategy at a time, chosen at the top of the page. The
calculations behind every figure are unchanged, so the section-by-section description below still defines them;
where it says "section", read the page in this table. ADR 0047 lists the charts that were removed (their figures
remain in tables) and two that changed: the four taxes are drawn as one *Tax* flow in money in and out charts
(`flows.fold_taxes`), and the Age Pension chart shows only the paths paid that year, with the full single rate as a
line. Colours for the app and the PNG plots come from `reporting/palette.py`.

### Outcome tiers and average retirement spending

[ADR 0048](../decisions/0048-outcome-tiers-and-average-retirement-spending.md); code in `retirement/outcomes.py`.

**Purpose.** Risk of ruin misses paths that never run out but fall far enough to live on the Age Pension. Each
calculated path is put in one tier, the worst it reached.

| Tier | Definition |
| --- | --- |
| Ran out | `Status` is `depleted` |
| Full Age Pension | Funded, and in at least one financial year `Age Pension >= 0.95 × full rate for that year` |
| Part Age Pension | Funded, some Age Pension, no full-rate year |
| Self-funded | Funded, no Age Pension |

**Full rate for a year.** With `m(y)` the projected maximum fortnightly single rate for the financial year ending in
`y` (basic rate, pension supplement and energy supplement; `rules/au/age_pension.py`, projected by
`rules/au/projection.py`), and `n` the whole financial years since the opening year:

```
full(y) = 26 × m(y) / (1 + CPI) ** n
```

This is the same financial-year step as the ledger's flows in today's dollars (`real.year_deflator`), so it compares
directly with each path's yearly `Age Pension`. The basic rate is indexed to wages and the supplements to CPI, so
`full(y)` rises slowly in today's dollars when wage growth is above CPI. The 0.95 factor is an engineering
judgement, explained in the decision record.

**Yearly states.** Each path has one state per financial year, with the same names. *Ran out* holds from the first
year with a spending shortfall; a path that is `depleted` with no shortfall (unpaid tax, or tax owed at the horizon
it cannot settle) is marked in its last year. Otherwise the year's own payment sets full, part or self-funded. The
app and `retirement_outcomes.png` show the share of paths in each state each year.

**Average retired-year spending.** For one path, the mean of `Spending paid` over its full retired financial years,
in today's dollars. For a group of paths the app reports the median of those averages and their 10th and 90th
percentiles. Groups are every path, each tier, and the ending-wealth groups (worst 1%, 5%, 10%, middle 10%, best
10%, 1%).

**Example** (10 November 2026; the example plan run for 40 years to age 93 with fixed spending starting at 5% of
wealth at retirement, 100 paths, seed 20261028): 64 paths self-funded, 21 part Age Pension, 5 full Age Pension and 10
ran out. The median path averaged $66,486 a year in retirement; the medians by tier were $68,684, $63,887, $59,916
and $61,602.

**Limitations.** The tiers cover only the simulated years: a horizon that ends before age 67 has no Age Pension
tiers. A path with one full-rate year that later recovers stays in the full Age Pension tier. The full-rate test
inherits the Age Pension model's scope (single person, no Rent Assistance). With few paths a tier can rest on a
handful of market sequences.

**Validation.** `tests/test_outcomes.py` (tiers, the 95% boundary, yearly states, groups, the full rate).

### One path: markets, wealth and money on one date axis

[ADR 0049](../decisions/0049-single-path-markets-wealth-and-money.md); code in `retirement/path_markets.py` and
`ui/charts.py` (`path_story`).

**Purpose.** For one chosen path, show what markets did, what the accounts held and the money that came in and went
out, lined up by date so that a market fall can be read down to its effect.

**Inputs.** The path's sampled daily returns, `r[t, a]` for observation `t` and ticker `a`
(`PortfolioAnalysis.returns_for`: the joint donor rows of the stationary bootstrap, the rows the path's ledger ran
on); the observation dates `d[0..T]` (`d[0]` is the opening mark); the entered weights and rebalancing rule of the
outside and super portfolios; the plan's CPI assumption.

**Growth of $1.**

```
ticker a:     g_a[0] = 1,   g_a[t] = g_a[t-1] × (1 + r[t, a])
portfolio:    h[0] = w,     h[t] = h'[t-1] × (1 + r[t]),   G[t] = sum(h[t])
              h'[t-1] = sum(h[t-1]) × w   if rebalanced yearly and d[t] is the first observation of a calendar year
              h'[t-1] = h[t-1]            otherwise
today's dollars:  g[t] / (1 + CPI) ** ((d[t] - d[0]).days / 365.25)
```

This is the portfolio analysis's compounding (`analysis._simulate`). When the two portfolios hold the same weights
and rebalance alike they are one series. When they differ, a combined portfolio leads them:

```text
combined[t] = share_outside * g_outside[t] + share_super * g_super[t]
share_x     = opening balance of x / (opening outside investments + opening super balance)
```

Each part compounds as its own portfolio and nothing moves between them, so the split drifts with returns. These are
the portfolio analysis's `combined_shares` and its *Combined* series; the combined series is left out when both
opening balances are zero. Its statistics are worked out from its own daily values like any other series.

**Statistics**, per series, with `years = (d[T] - d[0]).days / 365.25`:

```
CAGR                  = g[T] ** (1 / years) - 1
CAGR after inflation  = (g[T] / (1 + CPI) ** years) ** (1 / years) - 1
Volatility            = sample standard deviation of (g[t] / g[t-1] - 1) × sqrt(252)
Worst drawdown        = min over t of g[t] / max(g[0..t]) - 1
```

Volatility and drawdown use nominal daily returns, as the portfolio analysis does.

**The chart.** Three panels share one date axis: the growth lines (weekly points, log scale, today's dollars), the
month-end balances by account, and the yearly flows. A financial year's bar spans 1 July to 30 June, cut to the
plotted dates and inset, with the net-change line at its midpoint. A hairline marks the month end nearest the
pointer in every panel; the markets and wealth tooltips give that month's values and the flows tooltip that
financial year's. `retirement_markets.png` draws the same lines and statistics for the path nearest median ending
wealth.

**A group of paths.** With `g_p[t]` the growth of one series on path `p` of the group, the line drawn is
`median over p of g_p[m]` at the opening mark and each month end `m`, and each statistic is the median over `p` of
that path's statistic (`group_markets`). The balances are each account's median month-end balance and the flows
each flow's average across the group's paths, so the bars sum to the average net change. Each median is taken on
its own, so the lines and balances need not belong to one path.

**Example** (12 November 2026; the example plan run for 40 years with fixed spending, path 37): outside super
portfolio CAGR 13.4%, 10.6% after inflation, volatility 23.0%, worst drawdown 69.1%, $1 grew to $55.97 in today's
dollars; `USLCAP3x` CAGR 6.5%, volatility 51.8%, worst drawdown 98.5%.

**Limitations.** The portfolio lines are the entered portfolios at their target weights, not the ledger's holdings,
which also reflect contributions, sales and the cash buffer. The combined portfolio keeps the opening split between
outside and super; the household's actual split also moves with contributions, drawdowns and pension transfers. Returns are USD histories used as an AUD proxy. The
factor 252 is a convention, not the sampled history's exact observations per year.

**Validation.** `tests/test_path_markets.py`: rebalancing at the first observation of a calendar year; a portfolio's
statistics equal the same path's row in the portfolio analysis's outcomes; identical portfolios are one series.

### Results: how each figure is defined

The results were first laid out as five sections on one page, each chart followed by an explanation.
Financial years are written "Jul 2026 – Jun 2027" in tables and tooltips,
and axes are titled "Year ending 30 June". Dashed vertical lines mark
retirement, when super becomes accessible and when the pension starts on
time and financial-year charts; `milestones` in `retirement/flows.py`
positions them.

1. **Your portfolios.** A donut for each account labels weights on the
   slices, with a ticker legend. Each also shows its balance, rebalancing
   policy, and historical CAGR, volatility and maximum drawdown, plus the
   combined split. A whole-portfolio statistics table covers outside, inside
   and combined. Ticker-level source statistics sit in an expander.
2. **Historical behaviour.** Growth of $100 on a log axis for all three
   series. The drawdown and calendar-year return charts were removed by
   ADR 0041; maximum drawdown and the worst and best calendar years remain
   in the section 1 statistics.
3. **Future simulations.** A step-by-step description of the calculation
   with the run's actual dates, row counts, block length, seed and path
   count. Then:
   - for the selected portfolio, a fan of growth paths. It sits in a
     Streamlit fragment
     with the selector, as do the account choice in section 4 and the
     whole of section 5. A choice then reruns only its own charts, so the
     page does not redraw and jump back to the top;
   - median paths compared;
   - a note that this section shows investment returns only on $100, with
     no additions, withdrawals or tax; those are applied in sections 4 and 5;
   - four distributions (ending value on a log axis, annualised growth,
     volatility, maximum drawdown), each overlaying outside super, inside
     super and the combined portfolio with dashed medians;
   - a percentile table;
   When several strategies were compared, **Spending strategies compared**
   ([ADR 0045](../decisions/0045-strategy-comparison-section.md)) follows section 3. Its statistics table has
   one column per strategy: median starting retirement spending; total spending paid over full retired
   financial years (median and 10th percentile); each path's lowest retired year (median and 10th
   percentile); the shares of paths with any shortfall and that ever spent below the start; and ending wealth
   after tax owed (median and 10th percentile). *Wealth over time* draws the median total wealth at each month
   end per strategy, with optional dashed 10th percentiles. *Year by year* draws grouped bars of each financial
   year's median of a chosen money in and out flow (default spending; outflows shown as positive amounts paid),
   full retired years only by default. Strategy colours are fixed per strategy (`STRATEGY_COLOURS`). The same
   functions (`retirement/strategy_results.py`) write `comparison_summary.csv`, `comparison_wealth.png` and
   `comparison_spending.png`.
   Below it, *Each strategy in detail* has **one tab per strategy**
   ([ADR 0046](../decisions/0046-one-tab-per-strategy.md)) holding that strategy's sections 4 and 5. The tabs are
   tracked, so only the open tab is drawn and switching tabs reruns the page; with four strategies a full rerun
   took 5.7 s against 14.6 s when every tab was drawn. Run notes that apply to every strategy are shown at the
   top; notes for one strategy appear in its tab. Each tab's widgets have per-strategy keys (`strategy_key`), and
   `keep_strategy_choices` keeps a closed tab's choices, which Streamlit would otherwise forget.
4. **Retirement outcomes.** It opens with a **withdrawal strategy** box,
   built from the plan by `withdrawal_strategy`:
   - the rule;
   - the retirement date;
   - how starting spending is set;
   - how the rule adjusts it each 1 July, with its limits;
   - the order money is drawn from, the super access date, the pension
     start and the Age Pension.

   Then a collapsed **broad-strokes explanation** in six plain steps:
   markets, the daily ledger, retirement, tax, government support and how
   results are summarised. It points to section 5 and the methodology for
   detail. Then:
   - headline metrics (paths calculated, share funded, median ending wealth
     after tax owed, wealth at retirement, withdrawal rates, total tax), all in today's
     dollars;
   - wealth bands selectable by account;
   - **risk statistics** above the all-paths chart:
     - *risk of ruin to the horizon*: the share of tax-ledger paths with any
       unpaid spending or tax;
     - the share whose first shortfall came before super was accessible;
     - the median age at the first shortfall;
     - the share where outside money ever reached zero;
     - a warning when the ledger stops before age 90 (`SHORT_HORIZON_AGE`):
       the risk of ruin covers only the years simulated (ADR 0041).

     Above the ending-wealth chart, in today's dollars:
     - the share of paths ending below their starting wealth, and below half
       of it;
     - the median and the 5th percentile of ending wealth;
     - withdrawal-rate percentiles (median, 90th, 95th and 5th). The measure
       is each path's median withdrawal rate over its full retired years,
       ranked across paths;
   - **wealth over time across many paths** (`PlanRun.wealth_paths`):
     - **What is drawn.** Every depleted path, and up to 300 funded paths
       chosen at evenly spaced ending-wealth ranks, so the sample keeps the
       full set's spread.
     - **Colours.** Funded paths are translucent grey, with opacity
       `clip(45 / n, 0.08, 0.4)`, so overlaps darken where most paths went.
       Depleted paths are red on top, with opacity `clip(25 / n, 0.3, 0.85)`,
       so many red lines do not hide the grey. A red cross marks each
       depleted path's first shortfall. It can sit above $0 when super was
       not yet accessible. A teal line is the median of all paths, drawn or
       not.
     - **Axis.** A *Log scale* toggle, on by default, picks the y axis. On,
       it is a symlog scale (constant $1,000: linear below, logarithmic
       above, so $0 still plots) reaching every drawn path's peak. Off, it is
       linear and stops at 1.05 times the 97.5th percentile of the drawn
       paths' peaks; the caption says how many paths are clipped.
     - **Speed.** The lines are one matplotlib PNG reduced to a 256-colour
       palette, cached in the session per result and axis range. Its left
       edge uses the shared `Date` field, so it lines up with the axes. The
       browser draws only the median, the hovered path (quarterly points)
       and yearly invisible pointer targets. Per-path tooltip facts are
       joined in the browser with a lookup. The chart uses the canvas
       renderer. Measured in the in-app browser on a 500-path run, a hover
       took about 12 ms to handle;
   - every path's ending wealth, sorted. Hovering gives the exact value,
     the account split and any shortfall; labelled
     10th, median and 90th percentile lines; depleted paths in red;
   - in both money in and out charts, a dashed teal line for the amount
     **added to outside investments** from pay each year (`account_flows`
     "Savings invested"). It is a transfer from cash, so it is drawn as a
     line rather than a bar and is excluded from the net change. Each path's
     `retirement_annual` rows record it as `Added to outside investments`;
   - **money in and out in a typical year**: for each financial year, the
     median of every flow across calculated paths, with tooltips giving the
     25th and 75th percentiles, plus the median net change in wealth with
     whiskers from the 25th to the 75th percentile. Each path's
     `retirement_annual` rows carry its `Flow: …` columns and its
     `Net change in wealth`. Medians of components do not add up, so the
     bars need not sum to the median net change; the chart says so. The
     rows also carry `Wealth at start of year` and `Wealth at end of year`
     (`household_flows` opening and closing totals), and the net-change
     tooltip gives their medians. Above the chart, the single-path figures
     from the daily ledger section appear as medians across calculated
     paths: wealth at start (the same on every path), at retirement, when
     super becomes accessible and at the end; total personal, fund and
     Division 296 tax (the median of each path's total); and largest fall
     in wealth. Each is a separate median. Age Pension received and
     spending shortfall are zero on many paths, so they show the share of
     paths above zero and the median among those paths (`affected`;
     ADR 0040);
   - **spending in retirement**. With a percentage start, it shows the median
     and 5th–95th percentile dollar amounts the percentage produced. With a
     dollar start, it shows that amount as a percentage of wealth at
     retirement (median and 5th–95th percentile). It also shows the share of
     paths that ever spent more than 1% below the start, the 5th percentile
     of each path's lowest retired year, the deepest cut, and bands of
     spending paid in each full retired year;
   - withdrawal-rate bands by financial year, with an expanded explanation
     of how to read them;
   - the share of paths with a shortfall each year;
   - pension payment bands;
   - an outcome percentile table, and every path in a formatted table. The
     table is sorted from the worst ending wealth to the best and tagged with
     each path's ending-wealth percentile, `(rank + 0.5) / n x 100`.
5. **One path in full.** The median-ending path by default.
   - **Groups.** The picker also offers groups of paths: all calculated
     paths, then the worst 1%, 5% and 10%, the middle 10% (45th to 55th
     percentile), the best 10% and the best 1%. The ranked groups are
     ranked by ending wealth, and each has at least one path. A group's
     view uses **medians** across its paths (ADR 0040) for:
     - its outcomes: wealth at retirement, when super becomes accessible
       and at the end, and each path's median withdrawal rate;
     - month-end balances by account (from `PlanRun.path_series`); each
       account's median is taken on its own, so the stacked total need
       not be any path's wealth;
     - the year-by-year table, except that the shortfall column is the
       share of the group's paths with any shortfall that year.

     Shortfall and Age Pension received show the share of paths above
     zero and the median among them, and the share that ran out is a
     share. The stacked money in and out bars stay **averages** of each
     year's flows, net change and additions, so that they add up to the
     net change; the chart says so. No ledger is re-run, so the view is
     immediate. It says when a group has fewer than five paths.
   - **Single paths.** The picker lists every path from the worst to the
     best, each tagged with its ending-wealth percentile. A single path is
     re-run on demand. Its metrics include wealth at the start, at
     retirement, when super becomes accessible and at the horizon. The view
     shows:
   - balances by account, and the largest fall in total wealth;
   - **money in and out each year**, from `household_flows`: take-home
     salary, super contributions and investment returns against spending,
     income tax, contributions tax and fund tax, with a net-change line.
     The bars sum exactly to each year's change in total wealth;
   - **transfers into and out of each account**, from `account_flows`:
     savings invested, sales, contributions, fund tax, the move to the
     pension and pension payments;
   - in both of these, clicking a legend item hides or shows it (in the
     yearly chart this includes the net-change and additions lines), and
     *Show all* / *Show none* buttons reset the chart. Hidden items stay in
     the legend, faded, and the y axis refits to what is shown. This only
     filters the display; the flows still sum to the change in wealth;
   - a year-by-year tax, cap and pension table with age at 30 June;
   - tax and cap charts, pension minimum against paid, a filterable event
     log and CSV downloads.

A run starts at the top of the page, so its progress bar shows on any
tab. The bar reports each stage:

- ticker loading;
- path sampling;
- historical and future compounding;
- each finished ledger chunk;
- saving.

Ledger worker processes start when the app loads and are reused between
runs. On Windows each new worker re-runs the launching program's main
module; under Streamlit that is the app script. The pool therefore hides
`__main__` while it submits work. Without this a worker re-ran the whole
app, which took about 49 seconds and once broke the pool.

**Memory.** On Windows, numpy's OpenBLAS reserves a buffer for every CPU
thread. On a 32-thread machine each ledger worker therefore committed about
800 MB while touching only about 89 MB. Twelve workers committed about
9.6 GB, and Windows grew the pagefile to back that commitment. Two app
instances took system commitment to about 50 GB against 32 GB of RAM.

Workers now start with `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS` and
`MKL_NUM_THREADS` set to 1, which brings each to about 64 MB. The
`financial-simulations ui` launcher gives the app process four. A
5,000/500-path plan peaked at about 2.1 GB committed in total, against
10.9 GB before. Only one app instance should run at a time, because each
keeps its own worker pool.

**Worker count and priority** ([ADR 0042](../decisions/0042-faster-ledger-summaries-and-worker-priority.md)).
`worker_count` in `retirement/paths.py` chooses the number of ledger
processes:

- *Calculation cores* on the Assumptions tab (a setting for the computer,
  not stored in the plan), or `FINANCIAL_SIMULATIONS_WORKERS`, sets it
  directly, never above the number of paths;
- otherwise one process for four paths or fewer; else the smaller of half
  the paths and the hardware threads less `CPU_HEADROOM` (4), so 28 on a
  32-thread machine;
- the automatic count is then reduced so the workers, at `WORKER_MEMORY`
  (200 MB) each, leave `MEMORY_RESERVE` (4 GB) of physical memory available.
  A worker running 50-year ledgers peaked at a 142 MB working set (123 MB
  committed) on 2 November 2026. A reduced count is reported as a run note.

Every worker lowers itself to below-normal priority when it starts
(`SetPriorityClass` on Windows, `os.nice(10)` elsewhere). The operating
system then gives foreground programs, and normal-priority work such as
another simulation, the CPU whenever they need it; the ledgers use the
remaining cycles. The app process keeps normal priority. Priority changes
when the calculation runs, never its result.

Charts show hover values. Dragging pans, Shift+scroll zooms and a
double-click resets. Plain scrolling scrolls the page, because an
earlier version zoomed the chart under the pointer. Python generates PNG
counterparts for review: history, the future fan for each series, the four
overlaid distributions, the retirement range and the flows. Long-horizon date ticks step five years from 25 years onward;
growth charts use labelled log axes with a data-fitted domain; no-flow
panels say so explicitly. In the app, the retirement wealth fan has a *Log
scale* toggle, on by default, that switches between a linear y-axis and a
log-like (symlog) one. The log-like axis stays linear from $0 to $1,000, so
zero wealth remains visible, and is labelled as a log scale. The PNG
counterpart keeps the automatic rule: log-like when the maximum 95th
percentile exceeds 20 times the larger of $1,000 and the maximum median. The
choice affects display only, not path values or quantiles.

The browser starts with `financial-simulations ui`; the command line uses
`financial-simulations plan <plan-file>`. Both write an ignored
`output/plans/<plan-name>/` folder. It contains the normalized `plan.toml`,
`asset_summary.csv`, `portfolio_summary.csv`, `portfolio_history.csv`, `portfolio_bands.csv`,
`portfolio_outcomes.csv`, three portfolio PNGs and `manifest.json` with source hashes, code/rule manifests,
sample settings, notes and each strategy's folder and representative path. Each strategy's own files are
`daily.csv`, `events.csv`, `annual.json` (with that strategy's manifest), `ledger.png`, `retirement_paths.csv`,
`retirement_bands.csv` (by account), `retirement_annual.csv`, `retirement_range.png` and
`retirement_flows.png`. With one strategy they sit in the plan folder itself, as before; with several, each
strategy's are in `strategies/<rule>/` and the comparison files (`comparison_summary.csv`,
`comparison_wealth.png`, `comparison_spending.png`) sit in the plan folder. A run removes the other layout's
files, so a folder never mixes the two.
None belongs in Git.

## Validation, limitations and references

Synthetic fixtures in `tests/test_plan_markets.py` and
`tests/test_plan.py` cover ticker parsing, source reconciliation, income
proxy, schema round trips/failures, portfolio-to-ledger handoff, outputs
and a 35-year horizon; `tests/test_saved_runs.py` covers saved results
(ADR 0050). Executed checks are recorded in
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
limit tax interpretation. Division 296 used to make every path with super
above $3 million unsupported: 37 of 40 paths in a 34-year check. Since ADR
0028 it is assessed, and a 40-path check of a 50-year plan had no
unsupported paths. Its earnings include the fund's realised gains under the
`super.realised_gains` assumption (ADR 0029), so the tax depends on that
assumption.

References: processed source data and provenance in the sibling
`financial_datasets` project, identified by run-manifest hashes;
[resampling](resampling.md), [portfolio accounting](portfolio-accounting.md),
[retirement ledger](retirement-ledger.md), and the
[Australian rule register](../rules/au-2026-27.md).

Revision history: 2026-10-28 version 1 plan and browser app under ADR 0016;
2026-10-28 version 2 ticker portfolios and portfolio-first interactive
results under ADR 0017. 2026-11-02, future calendar at the history's observation density and the
requested end as the ledger's accounting end (ADR 0034).
