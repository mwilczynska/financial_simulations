# Joint daily replay and empirical resampling

Date: 2026-10-28. Status: Stage 1B sampling, no-flow batched accounting and the
sensitivity runner are implemented and validated. No parametric forecast or
retirement model is implemented. See [executed evidence](../validation/stage-1b.md).
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

## Comparison configuration and output calculations

The [comparison runner](../../src/financial_simulations/comparison.py) accepts a
TOML experiment that references an existing Stage 1A portfolio scenario. This
keeps manual and optimiser-imported weights consistent. The experiment requires
distinct horizon counts, seeds and block lengths, positive path/batch counts,
named calibration windows and explicit settings for its saved example traces.
The no-flow runner requires positive starting investment. Retained initial cash
is supported; dated contributions and withdrawals are rejected in this runner.

The default [experiment](../../scenarios/examples/comparison.toml) compares the
user's 40/20/20/20 portfolio over 252, 1,260 and 2,520 observations using 2010-2025
and 2016-2025 source windows. These horizons are not exact calendar years.
Moving and stationary block settings are 21, 63 and 252 observations; they are
sensitivity choices, not calibrated optimal defaults. Two separate seeds, 1729
and 2718, each generate 256 paths per stochastic setting. Complete replay uses
every feasible starting observation, not a random subset.

All methods in a horizon use the same target account-date template and daily
rebalance convention. If its available dates do not cover the horizon, the run
fails and requires an explicit `calendar_file`: a CSV containing just `Date`,
with strictly increasing ISO calendar dates, including the opening mark. This
permits longer hypothetical paths without inventing complete replay evidence.
The file is hashed, and the used target calendar is saved with every run. The
caller is responsible for the interpretation of any future exchange calendar.

Each case produces per-path terminal wealth, total return and maximum drawdown.
With no external flows, `total_return=terminal/(initial_investment+cash)-1` and
`drawdown[t]=wealth[t]/max(wealth[0:t])-1`; the opening mark is included. Daily
calendar-only marks cannot change these extrema in the supported no-flow scope.
Terminal percentiles use NumPy's linear sample-quantile convention at 5%, 50%
and 95%. The below-initial fraction is a descriptive sample fraction. For replay
it is over dependent overlapping windows; for bootstrap it is conditional on
the specified historical empirical process. Neither is an unconditional future
probability or a retirement success rate. No arbitrary model weights combine
methods. Seeds remain separate rows and coloured intervals in the report.

Published source diagnostics include Pearson correlations between assets and
`Corr(r[lag:],r[:-lag])`, separately centred, at lags 1 through 21. The same
calculation is applied to squared returns. Constant or insufficient series give
undefined entries, not invented zero correlations. These are descriptive
dependence diagnostics, not p-values or a block-selection algorithm.

Files generated under the ignored output folder:

- `summary.csv`: case settings, coverage, counts, percentiles, sample fraction
  below initial wealth and median maximum drawdown. A zero-window replay row has
  `status=no_complete_window`, zero paths and blank outcome summaries.
- `outcomes.csv`: all individual path IDs, case IDs and terminal/drawdown metrics.
- `traces.csv`: twelve default example paths with an opening mark, target dates,
  source previous/current dates, donor indices, restart/wrap flags and daily wealth.
  Replay examples use first/middle/last starts; stochastic examples use path IDs
  0, 1 and 2 of the first seed, without selecting by their outcomes.
- `dependence.csv`, `correlations.csv`, `target_calendar.csv` and `manifest.json`.
  The manifest includes full source file hashes/quality counts, requested/actual
  coverage, scenario/configuration hashes, effective settings, source-code hash,
  Git state, dependency versions and the stream recipe. Other paths' full daily
  indices are regenerated from this recipe rather than all persisted in memory.
- `terminal_wealth.png`, `sample_paths.png`, `dependence.png`, generated directly
  by Matplotlib. Terminal intervals are sample percentiles, not confidence
  intervals. Sample lines are individual paths, not percentile histories. Log
  wealth axes are labelled; no PDFs or interactive plotting are generated.

The runner retains only one batch's daily wealth/positions plus scalar outcomes
and selected traces. Batch size affects memory use, not daily frequency or donor
draws. The report does not model additional expenses, financing changes,
inflation, FX, cash-flow schedules, tax, super or retirement adequacy.

## Executed comparison checks and interpretation

The [comparison tests](../../tests/test_comparison.py) add end-to-end CSV/PNG
checks, exact batch-size invariance, reconstruction through the full ledger,
explicit future-calendar input, missing replay windows, configuration failures,
undefined correlations, and a synthetic alternating-return process. In that
process blocks retain strong negative lag-one dependence and independent rows
break it, as intended. The complete suite has 63 tests at this checkpoint.

The default local run evaluates 90 cases and 33,060 paths. In the shorter
calibration window, 2,513 source returns provide no complete 2,520-observation
replay. All twelve saved example paths have been reconciled observation by
observation to Stage 1A's full calendar ledger. See the validation record for
tolerances and the reproducible integration command.

256 paths per seed provide exploratory sample quantiles with considerable tail
sampling variation. Two seeds expose some numerical variation, not parameter or
model uncertainty. Longer blocks preserve more observed runs but may reduce
effective variety; there is no guarantee they produce more conservative results.
The modern matched-calendar sample does not resolve long-history, country or
selection bias. In particular, these outputs do not establish a sustainable
spending rate for the leveraged default portfolio.

Revision history: 2026-10-28, sampling core followed by implemented sensitivity
runner, trace reconciliation and visually inspected PNG output.
