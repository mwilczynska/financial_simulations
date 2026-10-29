# ADR 0025: spending in today's dollars, percentage starts and a percent-of-wealth rule

Date: 2026-10-29. Status: accepted; implemented and locally validated.

## Context

Spending had its own nominal growth rate beside the CPI assumption, and
both defaulted to 2.5%. The user found the stand-alone growth input hard to
read. They asked whether spending should simply rise with inflation, and
whether it could be a percentage of wealth.

The guardrail rules (ADR 0023) also took their starting withdrawal rate
from the dollar amount divided by wealth at the first 1 July review. On a
path where markets did badly before retirement, that starting rate was
already high, and the guardrails then protected it. Guyton and Klinger
(2006) and Vanguard's dynamic spending rule both start from a chosen rate.

## Alternatives

1. Keep a nominal growth input and explain it better.
2. Tie spending to CPI and add an optional real change on top.
3. For the starting amount: keep dollars only; allow a percentage of wealth
   only with rules; or allow it with every rule.
4. For rules: keep the measured start, or require a chosen percentage.

## Decision

The user chose:

- Spending is entered in today's dollars and rises each 1 July with CPI.
  `spending.real_change` (default 0) adds a real change on top, for
  example −1% for spending that falls with age. Nominal growth is
  `(1 + CPI)(1 + real_change) - 1`.
- `spending.retirement` sets the first retired year's spending:
  - `same`, the default, keeps the amount from before retirement;
  - `amount` uses `retirement_annual`, in today's dollars;
  - `percent` uses `retirement_percent` (default 4%) of total wealth on the
    retirement date, so each path gets its own amount.
- Guyton–Klinger, Vanguard and the new `percent` rule require a percentage
  start, which is their starting rate.
- Add the `percent` rule: each 1 July, spending is the starting rate times
  total wealth.
- Add a `maximum` beside `minimum`. Both are in today's dollars and rise
  with CPI only.
- Legacy files with `annual_growth` load with the real change it implies. A
  legacy file using a rule loads with a 4% percentage start.

## Reasons

- One inflation assumption removes a duplicate input that could drift from
  CPI without anyone noticing.
- A percentage start is how the published rules are defined. It also lets
  someone plan without guessing a dollar amount for wealth that is decades
  away.
- The percent-of-wealth rule is a reference point: it never runs out, but
  spending moves fully with markets.

## Consequences

- A percentage start is only known after the simulation. The inputs say so,
  and the results show its dollar range.
- Old plans that used a rule now start from 4% of wealth, not from their
  dollar amount, so their results change.
- Fixed spending with a percentage start is allowed. It is a Bengen-style
  plan: a percentage on the retirement date, then constant buying power.

## Validation

- `tests/test_ledger.py`: percentage start on the retirement date, the
  maximum, and the percent-of-wealth rule.
- `tests/test_plan.py`: the rules require a percentage start, and the
  legacy nominal growth becomes a real change.
