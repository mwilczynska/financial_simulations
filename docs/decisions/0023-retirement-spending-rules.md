# ADR 0023: optional Guyton–Klinger and Vanguard retirement spending rules

Date: 2026-10-29. Status: accepted; implemented and locally validated.

## Context

The user asked for spending that falls when markets do poorly, and asked
for the research and the outcomes before choosing. The default was a fixed
dollar schedule: first-year spending grown at a chosen rate, whatever the
markets do. That is not a percentage of the portfolio.

On the planner's own default combined-portfolio draws (1,000 paths, 40
years to age 95, real, pre-tax, a scratch comparison):

| Strategy | Ran out, 4% start | Ran out, 5% start | Paths with a year >20% below start, 4% start | Paths with a year >20% below start, 5% start |
| --- | --- | --- | --- | --- |
| Fixed real spending | 3.5% | 9.1% | 4% | 9% |
| Guyton–Klinger | 0.1% | 0.7% | 19% | 26% |
| Vanguard ceiling/floor | 1.4% | 5.6% | 10% | 16% |

The annuity-style and skip-inflation rules were also compared and were not
chosen. The user chose to implement Guyton–Klinger and Vanguard.

## Decision

Add `spending.rule`, one of:

- `fixed`, the default, which leaves earlier behaviour unchanged;
- `guyton_klinger`, with band 20% and step 10%;
- `vanguard`, with ceiling 5% and floor 2.5%.

An optional `minimum` sets an essential-spending floor. Rules review
spending each 1 July after the retirement date, against total wealth
(cash, outside investments and super), and reschedule monthly spending
from that day.

## Sources and limits

- **Guyton–Klinger:** Guyton and Klinger, "Decision Rules and Maximum
  Initial Withdrawal Rates", Journal of Financial Planning, March 2006. Its
  capital-preservation rule stops in the last 15 years of a retirement. The
  planner's ledger ends before Age Pension age, so every review here is
  well before that point. The inflation rule is applied as "skip this year's
  growth step".
- **Vanguard:** Jaconetti and colleagues, Vanguard, 2013. Only secondary
  descriptions were available; the ceiling and floor here apply to changes
  after the growth step.

Both use total wealth, including super that may not yet be accessible.
Taxes and pension minimums still apply as before.

## Validation

Ledger tests cover:

- a Guyton–Klinger review in a falling market (skip growth, then cut 10%);
- a Vanguard cut limited to the floor;
- the minimum holding.

A plan test covers the default, the mapping, a run with reviews, and
rejection of an unknown rule.
