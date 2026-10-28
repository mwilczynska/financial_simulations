# Local data and portfolio adapters

Date: 2026-10-28. Status: implemented for Stage 1A in package 0.1.0; validated
with synthetic fixtures. Historical accounting reconciliation is a subsequent
Stage 1A check. See [ADR 0003](../decisions/0003-stage-1a-data-contract.md).

## Purpose and supported scope

Read local processed financial datasets and selected numeric optimiser weights
without downloading data, executing exported script strings or importing
historical performance statistics as forward assumptions. The adapter is a
boundary between the companion projects and the simulation core.

Implementation: [registry](../../src/financial_simulations/data/registry.py),
[dataset loader](../../src/financial_simulations/data/datasets.py),
[optimiser importer](../../src/financial_simulations/data/optimiser.py),
[portfolio specification](../../src/financial_simulations/portfolios/spec.py),
and [market path](../../src/financial_simulations/markets/path.py).

## Inputs, provenance and semantics

The registry contains 13 investment series. All currently use USD return
conventions, including unhedged USD global assets. It maps canonical aliases to
explicit filenames and their upstream methodology. In particular `COMM` maps to
`CMDTY`, `GOLDPM2x` to `GOLD2X`, and the optimiser's `3x` aliases to canonical
`3X`. Unknown aliases fail. CPI is an economic factor, not an investment.

CSV and optional Parquet inputs require `Date`, `Adj Close`, `Total Return`,
`Source`, `Quality Flag` and `Source Notes`. Other supplied columns are preserved
in `source_rows`. Source and quality fields are retained per observation, with
source names and quality counts also recorded in the manifest. They identify
provenance, not an automatic decision that every reconstructed segment is fit
for every calibration question.

The run reads and hashes the same complete file bytes with SHA-256. Its manifest
records filenames rather than machine-specific paths, selected coverage, row
counts, currency, return semantics, and the requested window. Hashes cover the
entire input, so a later out-of-window data update can change the hash without
changing this window's calculated results.

`Adj Close` is the supplied total-return level or documented proxy, not
necessarily a market price. Reinvested distributions and any fund costs already
embedded in the series are retained. No distribution is added and no fund fee or
financing charge is deducted again. `Close` minus `Adj Close`, or differences
between their returns, are never interpreted as taxable distribution events.

The optimiser adapter selects exactly one positive integer `Rank` and reads
only the `<asset> Weight` numeric columns. The scenario must supply currency and
annual/buy-and-hold policy because these are absent from the result CSV. Neither
its `Existing Script Syntax` nor its historical summary statistics are executed
or used as assumptions. Input bytes and the selected rank are recorded.

## Calendar and return algorithm

1. Resolve aliases and validate the inclusive ISO-date window. Each selected
   asset must have the declared portfolio currency; FX conversion is not yet
   implemented.
2. Reject unsorted, duplicated, missing or non-date observations. Do not sort,
   deduplicate, forward-fill or remove bad rows to make inputs look usable.
3. Select each asset's observations within the requested window. At least two
   finite positive levels are required. Window endpoints need not themselves
   be market dates; actual selected endpoints are recorded.
4. Require **identical observation dates for all selected assets**, including
   zero-weight assets when explicitly selected. Do not inner-join calendars.
5. Keep the first selected level as the opening valuation. For every subsequent
   observation calculate `r[i] = A[i] / A[i-1] - 1`. Check agreement with published
   `Total Return` at an absolute tolerance of `1e-8`, allowing decimal-publication
   rounding. The opening row's published return belongs to a preceding interval
   outside this run and is retained as provenance but not applied.
6. Supply an immutable return matrix with shape `(number_of_dates - 1,
   number_of_assets)`. Each row belongs to a pair of actual valuation dates.
   No invented opening zero-return row enters the market path.

Weights are long-only fractions summing to one within `1e-10`; only rounding
noise inside that tolerance is divided out. Negative, nonfinite, duplicate-alias
or materially non-unit weights fail. Asset-level leveraged funds can be held
long-only; this does not implement portfolio borrowing or reconstruct leverage.

## Worked example

Three levels `[100, 110, 99]` on Thursday, Friday and Monday produce two returns,
`[+0.10, -0.10]`. The opening Thursday is a valuation, not a zero-return sample.
Saturday and Sunday are account calendar dates, not extra source observations.
If a second asset has a Tuesday mark instead of Monday, the loader fails. It
does not reinterpret Friday-to-Tuesday performance as a shared Monday return.

## Validation and reproducibility

`tests/test_adapters.py`: 18 tests passed on 2026-10-28 using Python 3.14.0,
NumPy 2.4.6, pandas 3.0.3, pytest 9.0.2 and PyArrow 24.0.0. The tests cover the
opening anchor, daily return calculation, provenance, file hashes, CSV/Parquet
equivalence, invalid dates/levels/returns, mismatched calendars, unsafe exported
text, aliases, currencies and invalid weights. Run with `python -m pytest`.

The local four-asset calendar audit found identical dates from 2010 through
2026-10-26. Their full histories differ. This is observed coverage of the local
snapshot, not a promised future property. The strict check runs on every load.
The inspected four series' maximum published-return rounding discrepancy was
below `5.2e-11`, well inside the chosen validation tolerance.

## Limitations and consequences

- Strict equality cannot identify a day absent from every source or establish
  whether an absence was a closure, lost quote or publication issue. A formal
  exchange-calendar and missing-observation audit remains future work.
- Early mixed calendars are rejected. Supporting them requires a separately
  documented valuation/alignment policy that preserves source observations.
- There is no AUD conversion, Australian inflation, tax-income decomposition,
  quality-filtered sampling, statistical calibration or generator yet.
- The loader validates the selected interval, not every historical row outside
  it. Sortedness and date uniqueness are checked on the whole input.
- A requested end beyond available data uses the latest available observation;
  the manifest exposes the actual end. There is no extrapolation.

## References and reasons

Primary project sources inspected 2026-10-28:

- [financial_datasets contract](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology.md)
  defines columns, returns and provenance.
- Per-asset upstream methodology filenames are recorded in the registry and
  manifest. The [global-stock method](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology_glstock.md),
  [global-bond method](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology_glbond.md),
  [gold method](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology_goldpm.md)
  and [commodity method](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology_cmdty.md)
  explain the default example's actual return semantics.
- [portfolio_optimizer.py](https://github.com/mwilczynska/portfolio_optimisation/blob/main/portfolio_optimizer.py)
  defines exported weights and historical accounting conventions.

Daily resolution is a user requirement. Strict alignment, fail-fast validation
and numeric-only portfolio import are engineering choices; no paper is claimed
to establish their unique correctness. These choices favour an auditable first
baseline while leaving unsupported calendars and tax semantics explicit.

Revision history: 2026-10-28, initial implemented adapters and fixture evidence.
