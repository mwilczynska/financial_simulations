# 0008: Calendar evaluation, censored recovery and conditional simulation error

Date: 2026-10-28. Status: accepted and implemented for the initial Stage 1D
single-portfolio, no-flow evaluation/reporting pass.

## Context and alternatives

Stage 1D needs pointwise nominal/real wealth, explicit targets and recovery
statistics. Observation-only real drawdowns miss inflation on weekends.
Reporting an unfinished drawdown's endpoint as its recovery understates risk.
Treating overlapping replay windows as independent samples produces misleading
precision. A percentile band is not a realizable individual path.

## Decision and reasons

Evaluate every calendar-day account mark, carrying the last nominal observation
between market dates and applying the assumed deflator every day. Retain exact
per-case observation panels under an explicit memory budget; calculate quantiles
in column chunks. Report pointwise bands separately from complete example paths.

Require a stated target basis, multiple and calendar-time growth assumption.
Use strict shortfall and preserve equal-to-target as success. Record recovery
status and observed lower-bound durations for open drawdowns; do not impute
their recovery dates or hide them in recovered-only averages.

Report Wilson score intervals and plug-in fraction MCSE only for conditional
independent generated paths. Report mean MCSE where at least two such paths
exist. Replay results are descriptive. Preserve model/assumption/seed separation
and explain that Monte Carlo precision excludes uncertain long-run assumptions.

## Consequences and scope

The evaluation pass does not modify generator streams, weights or daily
compounding. It adds no observed CPI, taxes or retirement model. Exact panels
can require more memory than pure terminal summaries, so oversized requests
fail explicitly. Rolling holdouts and multiple paired portfolios remain further
Stage 1D work. See [methodology](../methodology/evaluation.md).
