# ADR 0019: keep depleted retirement paths and report many more of them

Date: 2026-10-28. Status: accepted; implemented and locally validated.
Changes the unpaid-tax and whole-balance pension conventions of the
[retirement ledger](../methodology/retirement-ledger.md) and the path
counts of [ADR 0017](0017-ticker-portfolios-and-interactive-results.md).

## Context

The user saw only 7 retirement paths in a run. They asked whether 32
portfolio paths gave robust statistics, and asked for more results,
including withdrawal rates and pension data. In the earlier validation run
of 8 ledger paths, three stopped with "Unpaid tax debts are not modelled".
Those were the paths where money ran out. Excluding them biased every
retirement band and success count upwards. In a 200-path default run, 12
further paths stopped because a whole-balance pension transfer exceeded the
$2.1 million transfer balance cap. Division 296 (balances above $3 million)
stopped others. The ledger took about 0.9 s per ten-year path, and the
analysis held every sampled return in memory.

## Alternatives considered

1. Keep excluding failed paths and only label the bias. The statistics
   would still describe the wrong population.
2. Model ATO payment plans and the general interest charge. These are
   correct but outside the planner's current scope.
3. Record unfundable tax as an unpaid debt and continue the path, flagging
   it as depleted. Treat a whole-balance transfer as "up to the cap".

## Decision

Choose 3. A path is `funded`, `depleted` (some spending shortfall or unpaid
tax) or `unsupported`, and only unsupported paths are excluded. A
whole-balance pension transfer moves at most the unused transfer balance
cap; the remainder stays in accumulation, as a fund would leave it. An
explicit transfer above the cap still stops, since excess transfer balance
tax is not modelled.

Raise the defaults to 1,000 portfolio paths and 100 ledger paths, with
limits of 5,000 and 2,000. Store donor-row indices rather than sampled
returns: at 1,000 paths and 35 years that is 37 MB instead of 365 MB.
Accumulate path statistics in the loop instead of keeping daily wealth.
Run ledgers in worker processes that return summaries; re-run only the
path being shown in full.

Add the combined portfolio, longest drawdown, best and worst calendar year,
the pre-tax sustainable withdrawal rate per portfolio path, and per-path
retirement withdrawal rates, pension totals, real ending wealth and the date
outside money runs out.

## Reasons and evidence

The failure counts and timings were **executed local runs** on the invented
default plan. Treating a depleted path as a failure is a **methodological
requirement** for any success rate. A transfer up to the cap matches how a
retiree would commence a pension; this is an **engineering decision**. The
statutory cap is sourced in the [rule register](../rules/au-2026-27.md). The
noise of tail percentiles is a statistical fact: the 5th percentile of 100
paths rests on about five observations. The 100-path default balances run
time on a desktop against that noise.

## Consequences

- Bands and rates now include the worst funded-or-not paths, so central and
  lower percentiles fall compared with earlier runs.
- Unpaid tax carries no interest, so a depleted path's outstanding debt is
  understated.
- A ten-year default run takes on the order of a minute on a busy desktop;
  35-year runs take several minutes. The browser shows progress.
- 100 ledger paths still leave the 5th percentile noisy. Users can raise the
  count to 2,000.

## Implementation and validation

Code: `retirement/analysis.py`, `retirement/run_plan.py` and
`retirement/ledger.py`. Tests:

- `tests/test_plan.py` covers the rebalancing worked example and the
  combined series, and exactness of the withdrawal-rate formula in flat
  and doubling markets;
- `tests/test_ledger.py` covers unpaid tax recorded and continued, and the
  cap-limited transfer.

See the [planner method](../methodology/plan-and-app.md) and
[validation](../validation/plan-portfolios.md).
