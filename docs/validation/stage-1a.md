# Stage 1A validation evidence

Date: 2026-10-28. Scope: package 0.1.0, deterministic daily portfolio baseline.
This record accompanies the implementation checkpoint; exact commit, source
hash, scenario and input-file hashes are recorded in each local run manifest.
These results validate the tested accounting conventions, not future returns.

## Environment and reproducible commands

Python 3.14.0, NumPy 2.5.4, pandas 3.1.0, Matplotlib 3.11.2, PyArrow 26.0.0,
pytest 9.2.0. The full environment snapshot is
[requirements-dev.lock.txt](../../requirements-dev.lock.txt).

From the repository root after installing the editable project with dev/Parquet
extras:

```powershell
python -m pytest
python scripts/validate_stage1a.py --output output/validation
```

Supply optional `--tracker-script` with the path of the trusted local
`portfolio_plot17.py` to repeat the existing-calculation audit. No local machine
path or copied source/data is needed in this public repository.

The integration script writes `output/validation/validation.json`, daily CSVs,
PNG plots, optional Parquet, manifests and per-reference comparison reports.
All generated artifacts remain ignored. The script requires sibling companion
projects and local processed data; the unit suite uses only synthetic fixtures.

## Synthetic validation

43 tests passed locally after the scheduled closeout review. The initial
implementation checkpoint passed 39 tests. Coverage includes:

- Source dates, opening anchor, immutable daily return arrays, explicit aliases,
  currency rejection and provenance/hash preservation.
- Invalid/duplicate/unsorted data, inconsistent levels/returns, mismatched
  calendars, invalid weights and numeric-only optimiser import.
- CSV/Parquet equivalence and no addition of price/total-return differences.
- +10%/-10% compounding, before/after-return cash-flow timing, zero-return and
  one-opening-mark cases, holding drift and first-observation new-year rebalance.
- Closed-market cash reserves, deferred deposit investment, order of same-date
  events, unmet withdrawals, depletion and recapitalisation.
- Period accounting reconciliation, flow-adjusted performance, leap-year
  annualisation, partial periods and CLI-generated files.
- HTML escaping/local links and valid, nonempty PNGs. No PDF output is created.
- A finite one-day +1,000% synthetic path retains wealth/period-return results
  when its annualisation exceeds floating-point range. The annualised summary
  is null with an explicit status and still serialises as strict JSON.
- Malformed weights provided as a scalar/list/null produce an input validation
  error rather than an attribute traceback from a missing mapping interface.

Test files: [adapters](../../tests/test_adapters.py),
[accounting](../../tests/test_accounting.py),
[reporting](../../tests/test_reporting.py).

## Local historical reconciliation

All cases use the same 4,024 source valuations from 2010-01-04 to 2025-12-31,
producing **4,023 daily return observations** and **5,841 calendar account marks**.
Starting investment is an illustrative USD 100,000, with no contributions,
additional fees, inflation, FX or tax. These are validation examples.

The reference is the actual `annual_rebalanced_values` or `buy_and_hold_values`
function in the local companion optimiser. Loaders' dates and return vectors
are checked first, then every dated portfolio value is compared. Tolerances are
`rtol=1e-10, atol=1e-7` for values and `rtol=1e-12, atol=1e-12` for return vectors.

| Portfolio | Policy | Final nominal USD | Maximum absolute difference, USD |
| --- | --- | ---: | ---: |
| User default: USLCAP3x/ITT3x/GOLDPM2x/COMM, 40/20/20/20 | Annual | 1,369,170.50 | 2.10e-9 |
| Same default | Buy-and-hold | 2,384,142.84 | 3.26e-9 |
| GLSTOCK/GLBOND/GOLDPM/COMM, 25/25/25/25 | Annual | 237,037.87 | 3.20e-10 |
| Same equal-weight comparator | Buy-and-hold | 260,261.87 | 3.78e-10 |
| Numeric rank 1 from optimiser CSV | Annual | 425,852.33 | 9.31e-10 |
| Same imported portfolio | Buy-and-hold | 414,244.84 | 1.40e-9 |

All six comparisons passed. The largest relative discrepancy was below
`3.9e-15`. The optimiser source snapshot SHA-256 is
`1c4cadf22130750264a039d06c3a61d419646617085686110f194aad9dca4577`.
The imported rank is a historical candidate, not this project's default.

The default annual baseline has 17.7815% annualised time-weighted growth and
-36.8216% maximum performance drawdown in this particular nominal sample.
The name `Optimised CURRENT` is the user's existing portfolio label; this
validation does not independently optimise or recommend the allocation.

## Repeatability, accounting and formats

- Two runs produce identical SHA-256 hashes for all five CSV outputs and the
  three PNG plots on the tested environment. Manifest generation timestamps
  intentionally differ. Exact versions are recorded; cross-version byte identity
  of plots is not promised.
- The selected real source CSV/Parquet daily return arrays agree exactly in this
  snapshot (maximum absolute difference zero).
- Daily CSV and Parquet account outputs agree at `rtol=1e-12, atol=1e-9` after
  comparing equivalent date storage resolutions. CSV and Arrow readers select
  different timestamp units; calendar dates themselves are identical.
- Every daily value reconciles to holdings plus cash and to previous value plus
  market P&L and net external flows at `rtol=1e-11, atol=1e-9`.
- The dated cash-flow example contributes USD 150, pays USD 60 and records a
  USD 10 closed-market shortfall. It uses cash available on the actual date,
  without future sales or automatic retry.

## Existing tracker and visual inspection

The optional calculation-only audit confirms the existing tracker's CAGR and
drawdown formulas on common values, and identifies a one-observation value-date
shift and a contribution-TWR discrepancy. See
[ADR 0005](../decisions/0005-default-portfolio-and-tracker-audit.md) for the
controlled example, inspected source hash and limitations. Its top-level code,
downloads and plotting are not executed; the private script is not copied.

Wealth, drawdown and allocation PNGs were opened and inspected as images. The
initial allocation legend overlapped an explanatory line; the legend was given
its own space, re-rendered and inspected. Date labels, currency/percentage axes,
legend text and full daily paths are legible. The default portfolio's plots were
regenerated and reviewed after the user's allocation change. Interactive
browser behaviour and interactive charts are not claimed by this visual pass.
No PDF was generated.

## Limits and remaining work

Stage 1B generators and complete rolling historical-window analysis are not
implemented. Strict calendar equality excludes some earlier histories; no policy
for identifying missing days common to every source is validated. Extra fees,
settlement, currency conversion, Australian inflation/tax, super and retirement
rules remain separate work. See [data adapters](../methodology/data-adapters.md)
and [accounting](../methodology/portfolio-accounting.md) for supported conventions.

The initial implementation commit `cd68aac` passed hosted synthetic tests on
both Python 3.11 and 3.14 in
[GitHub Actions run 40732786508](https://github.com/mwilczynska/financial_simulations/actions/runs/40732786508).
The scheduled closeout added four boundary regressions, bringing the local suite
to 43 tests. Hosted results for later commits must be checked independently.
