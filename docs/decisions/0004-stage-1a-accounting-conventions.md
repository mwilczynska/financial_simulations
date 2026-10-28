# ADR 0004: Stage 1A opening mark, cash execution and annual rebalancing

Date: 2026-10-28. Status: accepted; implemented and validated for Stage 1A.

## Context and alternatives

Daily returns and a dated ledger require event ordering and an explicit starting
valuation. The optimiser resets target weights before the first return in each
calendar year. Its CSV does not carry this policy. Scheduled expenses may occur
when no market quote is available.

Alternatives include implicit daily weight resets, anniversary rebalancing,
calendar-year rebalancing, silently moving events to trading dates, allowing
unconfigured credit, or limiting closed-date payments to existing cash. Reports
can measure raw wealth changes or isolate investment performance from flows.

## Decision

Use an explicit opening mark, then retain positions through each supplied daily
return. Support buy-and-hold and calendar-year rebalancing before the new year's
first return. Process before-return flows, scheduled risky-holdings rebalance,
return, after-return flows, then pending cash investment. The default flow phase
is after-return; within-phase ordering follows the scenario.

Retain initial cash as a zero-interest reserve. New closed-date deposits wait in
cash until the next observation's close. Withdrawals use cash first; proportional
sales are available only on observation dates. Record unmet requested amounts
without borrowing, silent date shifts or automatic retry. The whole account is
marked on every calendar date without creating market return observations.

Report external flows and market gains separately. Chain daily time-weighted
returns, use actual elapsed days/365.25 for annualisation and calculate drawdown
on a performance index that includes the opening one. Monthly/annual tables must
reconcile to the daily ledger and label partial periods.

Generate standalone wealth, drawdown and allocation PNGs directly from Python
for the first reporting pass, and inspect the actual images. The HTML report
embeds those images. This is an explicit user reporting requirement; interactive
plots are a later extension and PDFs must not be created.

## Reasons and evidence

- **User requirements:** daily portfolio/account evolution, inspectable cash
  flows, annual/buy-and-hold support and reconciliation with the optimiser.
- **Verified source fact:** the local reference implementation inspected on
  2026-10-28 compounds each year's asset returns from reset target holdings.
- **Engineering judgement:** explicit phases avoid hidden assumptions; a cash
  shortfall is preferable to silently financing a closed-date withdrawal. Default
  after-return contributions avoid attributing earlier interval returns to new
  capital. Keeping the opening mark corrects first-interval ambiguity in reports.
- **Limitation:** before-return execution is a mathematical valuation convention,
  not a reconstructed intraday trade or settlement model. Daily close data does
  not establish exact executable prices.

## Consequences and implementation

Some withdrawals record shortfalls despite sufficient invested wealth. Users
can schedule a prior trading-date withdrawal to cash in a later extension; 1A
does not automatically plan those sales. The retained reserve and pending
investment cash have distinct treatment. Additional fees, tax and inflation are
explicitly unsupported, not silently assumed to be exact.

See [portfolio accounting](../methodology/portfolio-accounting.md), its linked
implementation/tests and [validation evidence](../validation/stage-1a.md).
Reference agreement establishes accounting equivalence only for the tested
inputs and conventions, not correctness of every upstream metric or policy.
