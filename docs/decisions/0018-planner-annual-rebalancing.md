# ADR 0018: annual rebalancing in the planner and retirement ledger

Date: 2026-10-28. Status: accepted; implemented and locally validated.
Supersedes the buy-and-hold account representation in
[ADR 0017](0017-ticker-portfolios-and-interactive-results.md) and the
"no rebalancing" ledger default in the
[retirement ledger](../methodology/retirement-ledger.md). The rest of
ADR 0017 stays in force.

## Context

The user reported that the planner's historical CAGR for the
40/20/20/20 `USLCAP3x`/`ITT3x`/`GOLDPM2x`/`COMM` portfolio was about 10%.
The local `portfolio_plot17.py` reports about 15% for the same weights.
The tracker rebalances once a year (`rebalance_annually = True`); the
planner held and drifted. The local processed data were the same for both.

On the full shared 1970-01-02 to 2026-10-27 sample, compounding each
convention gave:

| Calculation | Buy and hold | Annual rebalance |
| --- | --- | --- |
| Tracker conventions: union calendar, forward fill, lagged return | 10.19% | 15.25% |
| Planner conventions: common dates, pre-return reset at the first observation of a year | 10.21% | 15.25% |

A buy-and-hold CAGR cannot exceed the best component's CAGR, which is
11.68% for `USLCAP3x`. An annually rebalanced mix of volatile, weakly
correlated leveraged assets can. It sells recent winners and buys losers,
which harvests dispersion. The rebalanced portfolio also had lower
volatility (22.2% against 28.5%) and a smaller maximum drawdown (−58%
against −89%). Buy-and-hold weights drift towards whichever asset has
compounded most, here `USLCAP3x`.

## Alternatives considered

1. **Keep buy and hold and document the difference.** This would leave
   the planner disagreeing with the user's tracker and with the Stage 1
   default experiment. It also understates the return of the portfolio
   the user actually holds.
2. **Rebalance only in the portfolio statistics.** This makes the
   displayed statistics match while the tax ledger compounds a different
   portfolio, so retirement outcomes would not follow from the portfolio
   shown.
3. **Rebalance in both, with an explicit per-account policy.** Outside
   super, a rebalance is a set of real disposals that realise CGT.

## Decision

Choose 3. Each account has `rebalance = "annual"` (the default) or
`"none"`, as `outside.rebalance` and `super.rebalance`. This is an
additive field in plan schema version 2, so existing version 2 files take
the default.

The timing follows the Stage 1 [portfolio accounting](../methodology/portfolio-accounting.md)
convention. On the first return observation of each calendar year,
holdings reset to target weights at their pre-return values. The day's
return then applies.

In the retirement ledger:

- **Outside super.** Overweight assets are sold oldest parcel first. Each
  sale is an ordinary CGT event, with the same discount, loss and
  1 July 2027 reform treatment as any other sale. The event is labelled
  `purpose = "rebalance"`. The proceeds buy new parcels of the
  underweight assets, acquired that day.
- **Inside super.** Accumulation and pension units switch to target
  weights without tax. This keeps the ledger's existing simplification
  that funds realise no gains.

## Reasons and evidence

The tracker's rebalancing setting is a **verified local fact**, read from
its source. The CAGR table is an **executed local calculation** on the
processed datasets. Matching the user's own portfolio convention is a
**user requirement**. The timing convention is an existing **engineering
decision** from Stage 1, and it agreed with the tracker to 0.01 percentage
point. Taxing outside rebalances is required by Australian CGT law: a
switch between assets is a disposal. Untaxed super switching is a stated
simplification. A real fund realises gains, taxed at 10% or 15% in
accumulation, when it rebalances.

## Consequences

- Planner portfolio statistics for rebalanced mixes now agree with the
  tracker and the Stage 1 default experiment.
- Outside-super rebalancing creates taxable gains every year, so the
  ledger pays more personal tax than buy and hold would. Users who prefer
  to avoid that can choose `outside.rebalance = "none"`.
- Super returns are slightly overstated relative to a fund that pays tax
  on its rebalancing gains.
- Rebalancing has no transaction costs or spreads.

## Implementation and validation

Implemented in `retirement/analysis.py` (`_wealth`), `retirement/ledger.py`
(`rebalance`, `sell_parcels`) and `retirement/plan.py`. Tests cover:

- the worked example (110 buy and hold, 110.25 rebalanced) in
  `tests/test_plan.py`;
- outside CGT on a ledger rebalance, untaxed super switching and value
  conservation in `tests/test_ledger.py`;
- schema validation of the new field.

See the [planner validation](../validation/plan-portfolios.md) record.
