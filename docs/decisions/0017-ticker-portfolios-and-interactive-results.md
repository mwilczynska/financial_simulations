# ADR 0017: ticker portfolios and portfolio-first interactive results

Date: 2026-10-28. Status: accepted; implemented and locally validated. The
buy-and-hold account representation was superseded by
[ADR 0018](0018-planner-annual-rebalancing.md).
Supersedes the input and deterministic market conventions in
[ADR 0016](0016-plan-file-and-browser-app.md). Its local plan-file and
browser-app decision remains in force.

## Context

The user wants to select tickers already used in the companion investment
tracker, including custom processed histories reaching back to 1970. They
do not want to type annual total return or income yield. The version 1
Investments tab mixed per-asset holdings outside super with a separate
investment mix, and the label `Assets` was ambiguous. Retirement results
appeared before a clear analysis of the entered portfolios. The user asked
for much more explanatory detail, interactive plots and explicit 30-year
plot checks. Daily returns remain a project requirement.

## Alternatives considered

1. Keep manual annual growth and yield fields. This leaves the entered
   portfolio disconnected from the processed full sample and invites a
   second charge or credit for distributions already in total returns.
2. Accept any typed internet ticker and download it at run time. This
   conflicts with the local reproducible data contract and offers no
   matching 1970 synthetic history or Australian tax distribution data.
3. Keep exact opening parcels and delete only the separate mix, then infer
   future weights from current holdings. This assumes future investment
   choices match current holdings and makes a portfolio difficult to edit.
4. Select tickers from local processed data; enter one allocation and
   aggregate opening balance per account; then show both portfolios before
   running the daily retirement ledger.

## Decision and reasons

Choose 4 and bump the plan to schema version 2. `assets` becomes a
shared ticker universe; `outside.weights` and `super.weights` are the
two portfolios. Their allocations apply to opening balances and future
purchases. Derive descriptive return, volatility, drawdown and a cash
contribution proxy from each full available processed sample. Use the
intersection of selected ticker dates for joint daily stationary-bootstrap
paths. Compound each portfolio buy and hold on the same source-row draws,
then pass the first selected draws through the existing daily tax ledger.
Show historical portfolio behaviour, future return and risk distributions,
and retirement outcomes in that order.

The user subsequently specified the invented default allocation: outside
super retains 40% `USLCAP3x`, 20% `ITT3x`, 20% `GOLDPM2x` and 20%
`COMM`; inside super uses 100% `GLSTOCK`.

The browser uses interactive Altair charts with plot explanations. Python
also writes PNG images for review and offline inspection. The user's
current request advances the previously planned interactive reporting
step. Long-horizon axes use sparse years, and growth fans label their log
scale. When an upper retirement-wealth tail would flatten the median on a
linear axis, its fan uses a labelled log-like y-axis that remains linear
near zero. This design preserves daily accounting while using monthly and
annual summaries for display.

## Consequences and limits

- A version 1 file needs reviewed conversion. The loader rejects it
  because collapsing multiple actual CGT parcels into one opening tax
  position would silently lose acquisition history.
- The new aggregate outside cost base/date is an approximation even for
  version 2 plans. The UI labels it.
- The processed data use USD return conventions. Until FX and Australian
  distribution details exist, the retirement ledger explicitly applies
  those returns as an AUD proxy, and assumes zero franking. The historical
  cash contribution is split out of total return, never added on top.
- Custom pre-fund returns are reconstructed or modelled, while fund
  tickers have shorter vendor histories. The common-date window can
  shrink when tickers are mixed. Unsupported ledger draws are counted
  and excluded from displayed retirement percentiles.
- This planner's buy-and-hold allocation differs from the Stage 1
  annual-rebalanced default experiment.
- Files stay local, output is ignored, and run manifests include source
  hashes, settings and code/rule versions.

## Implementation and validation

The adapter is `data/plan_markets.py`; normalization and account mapping
are in `retirement/plan.py`; daily paired sampling is in
`retirement/analysis.py`; the runner, browser and PNG writer are in
`retirement/run_plan.py`, `ui/app.py` and `reporting/plan.py`.
Synthetic tests cover the adapter, schema, output and 35-year horizon.
The local processed data, local browser and 35-year static figures were
also reviewed. See [methodology](../methodology/plan-and-app.md) and
[executed validation](../validation/plan-portfolios.md).

## Evidence classification

The desired input and result order are **user requirements**. Source
column meanings and provenance are **verified local dataset facts**, as
checked by the adapter and recorded hashes. The common-date policy,
buy-and-hold account representation, bootstrap choice, aggregate opening
tax position and display conventions are **engineering decisions**. They
are not empirical claims that the simulated distribution predicts returns.
