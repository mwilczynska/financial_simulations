# ADR 0014: daily single-person ledger conventions

Date: 2026-10-28. Status: accepted; implemented for 2026-27 and tested.

## Context

Stage 2A's remaining deliverable is an auditable single-path ledger that
applies the 2026-27 rules ([ADR 0013](0013-stage-2a-rule-register-scope.md))
to one person's accounts. Market returns arrive as daily total returns
([ADR 0001](0001-daily-returns-throughout.md)). Tax, however, depends on
income, gains and franking, not total return. Contribution caps depend on
when the fund receives money, and super access depends on dated release
conditions. The user approved the proposed defaults: employer contributions
7 business days after payday, an annual tax settlement after 30 June, and
withdrawals from outside investments first until super is accessible.

## Alternatives considered

1. **Accounting.** Annual-step accounting with tax on annual returns was
   rejected. It breaks the daily-returns requirement and cannot place
   contributions in the right cap year.
2. **Income split.** Instrument-exact income from fund tax statements is
   unavailable for the synthetic and index series. Treating all return as
   taxable income each year would double-tax unrealised gains.
3. **Withdrawal policy.** Optimised or tax-aware withdrawal order is a later
   decision policy, not a ledger convention.

## Decision

Use a calendar-day ledger with fund units and outside CGT parcels, on the
Stage 1 trading-day convention: returns on observations, and sale-requiring
needs rolled forward to the next observation. Split total return with
declared annual yields and franked fractions (estimated income mode).
Distributions reduce the unit price by exactly the cash paid. Settle income
tax annually on a configurable date. Use the fixed waterfall: cash, outside
sales, accessible accumulation, then extra pension payments, with any
remaining need recorded as a shortfall. Check a wealth identity every day,
and stop rather than approximate any unsupported rule.

## Reasons

- **User requirements:** daily accounting, individual access dates,
  unsupported rules made explicit, and a bridge shortfall recorded even
  when super is positive.
- **Engineering judgement:** price-reducing distributions are the only split
  that keeps the supplied total return exact while generating taxable income.
  Fund units let pension commencement be a pro-rata transfer without a CGT
  event for the member.

## Consequences

- Cash timing differs from PAYG withholding during employment.
- Fund-level realised gains are ignored, so net returns are slightly high
  for funds that turn over assets.
- Multi-year runs and stochastic paths need later-year rule sets, and the
  ledger itself will later need wealth-dependent withdrawal policies,
  checked against this reference ledger. See the
  [methodology](../methodology/retirement-ledger.md) and
  [validation](../validation/stage-2a.md).
