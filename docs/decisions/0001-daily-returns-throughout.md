# ADR 0001: retain daily returns throughout

Date: 2026-10-28.

Status: accepted user requirement; implementation pending.

## Context

The companion financial datasets publish daily return histories. The initial project plan allowed monthly aggregation in the simulation pipeline and proposed a monthly retirement cash-flow ledger. The user explicitly requested that returns remain daily throughout, consistent with the datasets.

Daily-reset leveraged funds, dated transactions and costs accruing over calendar gaps also make frequency and timing material parts of the model.

## Alternatives considered

1. A monthly engine consuming aggregated daily history, with daily handling only for specialised cases.
2. A daily engine for market paths and all portfolio/account evolution, with scheduled cash flows and derived monthly/annual reports.
3. Mixed daily and monthly core engines depending on the asset or retirement phase.

## Decision

Use alternative 2. Retain daily returns in loading, calibration, replay/resampling, generated paths and account compounding. A recurring salary or expense remains on its configured schedule. Lower-frequency economic observations retain their actual frequency and provenance even when mapped to the daily ledger.

Monthly and annual results are report summaries of daily calculations. Bootstrap block lengths use explicit counts of daily trading observations. Separate the market-observation calendar from calendar-day events and cost accrual.

## Reasons and evidence

- **User requirement:** daily returns are the intended scope, rather than an optional precision setting.
- **Verified source fact:** the upstream [dataset contract](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology.md) supplies daily returns. Its [USLCAP3X methodology](https://github.com/mwilczynska/financial_datasets/blob/main/docs/methodology_uslcap3x.md) describes daily resets and financing/expenses based on elapsed calendar days. Sources inspected 2026-10-28.
- **Engineering judgement:** using one daily core makes portfolio comparisons and account transitions easier to reconcile without reconciling separate return-frequency engines.
- **Scope limitation:** retaining daily resolution does not establish superior predictive accuracy for long-horizon retirement outcomes.

## Consequences

The design requires daily calendar handling, date-specific events and additional runtime/storage. Performance work should use appropriate batching and storage choices while retaining daily calculations. Published monthly/quarterly factors must not be relabelled as observed daily data.

Event ordering, future-calendar mapping and concrete accrual conventions require documented implementation decisions and validation. Daily-reset leverage must be applied to daily paths; costs already embedded in historical fund returns must not be charged again.

## Implementation and validation

The [project plan](../../PLAN.md) and [literature review](../literature-review.md) have been updated. The [daily-engine methodology](../methodology/daily-engine.md) specifies the current requirements, worked examples and proposed validation cases. Simulation code and executed test evidence remain pending.
