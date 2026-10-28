# Joint daily replay and empirical resampling

Date: 2026-10-28. Status: Stage 1B sampling and no-flow batched accounting are
implemented and fixture-validated. The comparison runner and sensitivity report
are in progress. No parametric forecast or retirement model is implemented.
See [ADR 0006](../decisions/0006-joint-daily-resampling.md).

## Purpose, inputs and provenance

Compare the effect of preserving or breaking historical sequences for the same
portfolio. Input is the [strict daily market path](data-adapters.md), retaining
its total-return conventions, assets, currency, valuation dates and file hashes.
No income, expenses or financing are added to already net fund returns.
There is no inflation or FX factor resampling in this first USD nominal scope.

Implementation: [samplers](../../src/financial_simulations/markets/resampling.py)
and [batched accounting](../../src/financial_simulations/portfolios/batch.py).
An index `j` identifies the entire source return vector between source valuation
dates `j` and `j+1`. All assets use the same donor index on each sampled day.
The source path is neither changed nor thinned.

## Algorithms and boundaries

For `n` source return observations and `h` requested observations:

- **Historical replay:** there are `max(0, n-h+1)` complete windows at stride
  one. Start `s` selects indices `s,...,s+h-1`. A partial window is rejected;
  no repeat, wrap or stitch is called historical replay. Overlapping windows
  are dependent and do not represent independent retirement experiments.
- **Independent joint rows:** each index is uniform on `0,...,n-1`, independently
  through time. Cross-asset relationships within a row remain intact; serial
  dependence is deliberately broken.
- **Moving blocks:** choose block starts uniformly on `0,...,n-L`, append `L`
  consecutive rows and repeat. The last block is truncated to exactly `h` rows.
  There is no wrapping, and `L` must fit in the source. Endpoint observations
  consequently have different inclusion probabilities; this is not a circular
  block bootstrap.
- **Stationary bootstrap:** each block starts uniformly on `0,...,n-1`. Its
  length `K` has `P(K=k)=(1-1/L)^(k-1)/L`, for positive integers `k`, giving
  expected length `L`. Within a block indices continue modulo `n`; the final
  block is truncated. `L=1` is independent uniform rows. Mean lengths are
  positive integers in this initial API. Circular wraps are recorded separately
  from random restarts, including when a restart happens to pick the next index.

Returned donor indices, block-start flags and wrap flags are read-only arrays.
Only existing daily vectors are sampled; raw price levels are not concatenated.
Blocks and horizons count observations, not elapsed calendar days or exact years.

## Source dates and account dates

`sampled_path` requires a separate target observation calendar with `h+1` dates,
including an opening mark. Repeated or nonmonotone donor dates cannot become the
account dates. Portfolio rebalancing follows the target calendar. Source dates
remain audit metadata; they do not import historical tax rules or schedules.

The first comparison uses the first `h+1` valuations of its baseline dataset as
a **shared observed accounting-calendar template**, explicitly not a forecast of
future exchange holidays. A caller can provide other explicit target dates to
the API. Moving the target calendar can change annual rebalancing and outcomes.
Donor net fund returns retain their historical elapsed-day financing; mapping
them does not rebuild a fund under new financing rates or holiday gaps.

## Accounting and efficiency

No-flow comparison paths are processed in batches with vectorised positions
across paths and daily observations through time. Positions drift; the risky
holdings reset before the first return in a new target calendar year under the
annual policy. Retained initial cash is separate and earns zero. Opening wealth
is included in every result. There are no dated cash flows or extra costs in
this batched function; use the full Stage 1A ledger for those cases.

Batching preserves daily resolution. Matching tests compare every observed
wealth against the full ledger, including weekends, a new-year boundary, cash
reserves, asset loss of 100% and both rebalancing policies.

## Reproducibility and examples

Random stream v1 uses NumPy `Generator(PCG64(SeedSequence(key)))`, with key
`[master_seed, method_code, block_length_or_zero, horizon, path_id]` and method
codes independent=1, moving-block=2, stationary=3. This prevents execution order,
batch size or weights from changing a path's draw. Changing the horizon selects
a different stream; prefix consistency between horizons is not claimed.
Record NumPy/code versions as well as seed and indices.

Example: five return rows and a horizon of three have starts 0, 1 and 2; start 2
uses rows `[2,3,4]`. A horizon of six has zero complete replays. A moving block
of length two might select `[1,2,3,4,0]` for a five-row path, with block starts at
positions 0, 2 and 4. A stationary block can continue from source row 4 to 0;
that artificial circular boundary is flagged, not presented as contiguous history.

## Validation and limitations

`tests/test_resampling.py` adds 16 executed cases to Stage 1A's 43 tests. They
check complete windows, joint rows, reproducibility across order, block
continuity/truncation, circular wraps, geometric restart frequency, uniform donor
selection, invalid inputs and full-ledger reconciliation. Statistical checks use
fixed synthetic seeds and broad tolerances, not a fitted financial conclusion.

Stationarity and historical representativeness are assumptions. Long blocks
cannot add independent history or unknown daily shocks. The early mixed-calendar
restriction remains. A longer generated horizon is possible with an explicit
target calendar, but does not create complete historical replay evidence.
Neither bootstrap frequencies nor historical overlap counts establish retirement
success probabilities. Block length and calibration period require sensitivity;
no statistically optimal retirement block length has been selected.

## References and revision history

Politis and Romano (1994), *The Stationary Bootstrap*, JASA 89(428), 1303-1313:
[publisher record](https://doi.org/10.1080/01621459.1994.10476870),
[original paper](https://users.ssc.wisc.edu/~behansen/718/Politis%20Romano.pdf),
and [Stanford report record](https://statistics.stanford.edu/technical-reports/stationary-bootstrap).
Algorithm definitions were inspected on 2026-10-28; proofs and inference
guarantees have not been independently reproduced. The engineering choices about
non-circular moving blocks, shared calendars, integer mean lengths and stream
keys are this project's explicit conventions, not claims proved by the paper.

2026-10-28: first implemented sampling/accounting checkpoint; runner pending.
