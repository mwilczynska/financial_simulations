# Daily simulation engine

Date: 2026-10-28.

Status: Stage 1A implements and validates the daily data contract, explicit
opening mark, calendar-day account ledger, dated cash flows and portfolio
accounting. See [implemented accounting conventions](portfolio-accounting.md),
[data adapters](data-adapters.md) and [executed validation](../validation/stage-1a.md).
Stage 1B [joint empirical generators](resampling.md) and their no-flow sensitivity
runner are also implemented. Parametric calibration, new leveraged-fund
construction, additional cost accrual and Australian retirement rules below
remain design requirements.

Decision record: [ADR 0001: retain daily returns throughout](../decisions/0001-daily-returns-throughout.md).

## Purpose and rationale

The simulation engine will retain daily returns from the financial datasets through calibration, replay/resampling, future path generation, portfolio compounding and retirement account accounting. Daily paths are also the basis of drawdown and shortfall calculations. Monthly and annual reports are derived views.

This is an explicit user requirement, chosen for consistency with the companion datasets and for inspection of path-dependent investments and dated cash flows. It is not a claim that daily data automatically gives more accurate long-horizon forecasts.

The existing leveraged dataset methodology supplies a concrete reason to preserve the time basis: it compounds daily-reset leveraged returns and accrues financing/expenses using elapsed calendar days between trading observations. See the [upstream USLCAP3X methodology](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology_uslcap3x.md), inspected 2026-10-28. That source documents the existing historical series; future fund parameters remain a separate modelling choice.

## Two clocks

### Market observations

An asset return row is an observation between successive valuation dates. Load its date and return without first converting the history to monthly or annual returns. Retain the source/provenance fields needed to interpret the observation.

The asset registry must state the market calendar, missing-data policy and how it aligns with the other assets. A missing trading quote is different from an expected market closure. Any common-calendar restriction, carried valuation or other alignment treatment must be visible in the run manifest.

No universal 252-day conversion is implicit. When a model uses an assumed trading-day count per year, record that count and why it is suitable. Bootstrap block lengths count actual trading observations, not calendar days.

### Calendar events

Maintain dated account state on the calendar/event timeline. Birthdays, financial-year boundaries, pension commencement, contributions, spending, fees and tax settlements occur on defined dates. A payment can recur monthly while the account continues to compound daily.

Non-trading-date events need an explicit policy: for example, when a sale can be executed, which valuation is used and whether available cash can meet the event before the next market observation. These details must be specified and tested during implementation. The engine must not silently borrow from a future sale or move a legal eligibility date.

Flat carried valuations on closed-market dates are accounting marks, not newly observed market quotes. They must not be added to calibration or bootstrap samples as fabricated daily observations.

## Returns and compounding

For a defensible total-return level `A_t`, the basic daily simple return is:

```text
r_t = A_t / A_(t-1) - 1
```

The meaning of `A` is asset-specific. Total returns can already include reinvested distributions, fund expenses and financing. The adapter must preserve those semantics. In particular, do not infer a cash distribution merely from the names `Close` and `Adj Close`. See the [upstream common methodology](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology.md) and the distribution audit in [the project plan](../../PLAN.md).

For a single holding without external cash flows or additional charges:

```text
V_t = V_(t-1) * (1 + r_t)
V_T = V_0 * product(1 + r_t)
```

A portfolio maintains its asset positions and cash through the daily path. Rebalancing occurs only on the configured dates, rather than implicitly restoring target weights every day. Withdrawal-driven sales and contributions also change positions.

Taxable account modelling will need appropriate price/income and cost-base accounting. Stage 1's use of an accumulated total-return level must not be presented as a cash-payment ledger for Stage 2.

## Generated paths and daily sampling

- Historical replay retains contiguous daily observations and applies the selected future account/rule calendar.
- Independent resampling draws complete daily asset/factor vectors.
- Moving and stationary bootstraps draw consecutive daily observations using common indices across assets. Their parameters specify numbers of observations; a label such as "one year" must state the assumed count or mapping.
- The initial parametric benchmark calibrates daily log-return means/covariances and generates daily innovations. Explicit annual assumptions require a mathematically consistent conversion under the model's stated time basis.
- Uncertainty about long-run expected returns is separate from daily innovations. Sampling a new long-run mean independently every day is not the same as holding an uncertain persistent mean through a path.

Attaching donor observations to future trading dates can change holiday gaps and the mapping of lower-frequency factors. Document that mapping rather than treating historical source dates and future account dates as interchangeable. Detailed sampling behaviour belongs in each generator's own methodology.

## Daily-reset leverage and elapsed-day costs

When a supplied daily fund series already includes its daily reset and expenses, use its returns as defined. A separate scenario charge must represent an additional cost, not a second copy of an embedded charge.

When constructing a new leveraged path from underlying simulated returns, calculate the reset and relevant financing/expenses at the required daily/event frequency. State whether each accrual is based on trading observations or elapsed calendar days, its day-count denominator and how holiday gaps are treated.

The upstream USLCAP3X model, for example, uses elapsed calendar-day financing and expense carry. Resampling an existing net fund return and rebuilding a fund under a new future financing path are distinct model modes. The latter must not add fresh financing costs to an already net return. See the [upstream construction](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology_uslcap3x.md).

## Lower-frequency economic factors

Daily simulation does not create daily observations of inflation, wages, mortality or tax rules. Keep their published frequencies and identify any daily alignment, carry-forward, interpolation or modelled evolution.

For joint bootstrapping, sampling interpolated inflation at arbitrary daily block boundaries needs separate assessment: preserve a coherent price-level path and document the induced dependence. Adding an interpolated field to every row is not proof that the joint resampling specification is valid.

For personal tax, calculate nominal AUD amounts using the applicable dated rules. Deflate report values separately. Annual tax calculations, monthly salary payments and daily asset returns can coexist on the dated ledger.

## Worked examples

These independent calculations are now executed fixtures in
`tests/test_accounting.py`. The leverage example validates compounding supplied
daily-reset returns; constructing a financed leveraged fund remains unimplemented.

### Compounding and report reconciliation

Start with 100 and apply daily returns of +10% and -10%, with no cash flows or additional costs:

```text
Day 1: 100 * 1.10 = 110
Day 2: 110 * 0.90 = 99
Two-observation compounded return: -1%
```

A summary covering both observations must end at 99. The average simple daily return of 0% must not be substituted for the compounded result.

### Cash-flow timing

Use the same returns and add 10 at the end of day 1, after that day's return:

```text
Day 1: 100 * 1.10 + 10 = 120
Day 2: 120 * 0.90 = 108
```

Adding the 10 before day 1's return instead produces 108.90 at the end of day 2. This demonstrates why event order needs a stated convention. It does not establish the production default for every event type.

### Resetting leverage

Assume a hypothetical 3x daily-reset fund with no financing or fees and underlying returns of +10% then -10%:

```text
Underlying: 100 * 1.10 * 0.90 = 99
Daily-reset fund: 100 * 1.30 * 0.70 = 91
```

Multiplying the underlying two-day return of -1% by three would instead suggest 97. The correct daily-reset toy result is 91. Actual fund modelling must additionally account for its specified costs and treatment of extreme losses.

## Validation specification

The initial implementation must provide evidence for:

- Preservation of input daily rows, dates and return definitions through the adapters.
- Compounding and timing examples above, plus zero-return and single-observation cases.
- Position drift between rebalance dates and correct execution on scheduled rebalance dates.
- Weekend/holiday events and actual elapsed-day accrual, including expected market closures versus missing observations.
- No double counting of distributions, fund fees or financing.
- Correct daily covariance/return calibration under a declared time basis and appropriate return support.
- Shared bootstrap indices across assets, contiguous blocks and reproducible sampling.
- Daily extrema/drawdown calculations and reconciliation of every monthly/annual summary to the corresponding daily results.
- Traceable failures and accessible-cash shortfalls, without drawing on preserved super or unconfigured borrowing.

The [Stage 1A validation record](../validation/stage-1a.md) identifies executed
tests, numerical tolerances and historical accounting comparisons. Covariance,
sampling, financing accrual and retirement-account validations above remain
future work; the Stage 1A results do not establish those properties.

## Computational consequences and limitations

Daily paths contain more observations than monthly paths and increase runtime, memory and output size. Profile representative multi-decade runs, process paths in batches where needed, and make full-path persistence configurable. Storage optimisation must not reduce the simulation frequency or hide the daily evidence needed to inspect a result.

Record the random-generator/seed policy and the extent to which batching or other execution changes preserve reproducibility. Do not claim these properties before validating them.

Daily resolution preserves the chosen time structure; it does not remove historical sample limitations, source reconstruction, parameter uncertainty or the need for model comparison.

## Revision history

- 2026-10-28: Initial design following the explicit requirement to retain daily returns throughout the simulation and retirement accounting pipeline.
- 2026-10-28: Linked the implemented Stage 1A conventions and executed evidence;
  retained proposed status for later generators, costs and retirement rules.
