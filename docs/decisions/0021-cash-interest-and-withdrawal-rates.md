# ADR 0021: interest on cash, and withdrawal rates over a whole retirement

Date: 2026-10-29. Status: accepted; implemented and locally validated.
Amends [ADR 0019](0019-retirement-path-results.md) (withdrawal rates) and
the interest convention of the [retirement ledger](../methodology/retirement-ledger.md).

## Context

[ADR 0020](0020-outside-contributions-stop-at-retirement.md) left unspent
cash idle at 0%, and the user asked for interest. The user also said a
median sustainable withdrawal rate of about 15% did not seem right. The rate
was measured from retirement to the ledger horizon, which stops before Age
Pension age: about 8.8 years in the example. Even with no growth, 8.8 years
of withdrawals supports about 11% a year. The user added that a sustainable
withdrawal rate usually means an outside portfolio lasting indefinitely.

## Decision

- **Interest.** `outside.cash_interest`, an annual effective rate (default
  3%, an assumption), applies to outside cash. It is credited daily and
  taxed as interest income.
- **Withdrawal-rate horizon.** Rates use separate draws from the retirement
  date to `assumptions.planning_age` (default 95).
- **Two rates per path.** The rate that spends the portfolio to zero at the
  planning age, and the rate that keeps its CPI-grown real value at the end
  of the window ("lasts indefinitely"). The app reports the median and the
  5th percentile of each, and explains them in detail.

## Reasons and consequences

The horizon problem is a **verified finding**: the formula was correct for
the window it was given. The keep-the-real-capital definition is the common
**convention** for a perpetual rate; the 4% rule is a separate 30-year
**research result**, mentioned only as context. On the example's 40-year
window and 300 draws:

| Portfolio | Spend to zero, 5th pct | Spend to zero, median |
| --- | --- | --- |
| Combined | 4.9% | 9.5% |
| Inside super | 3.9% | 7.6% |
| Outside super | 4.8% | 11.1% |

All are pre-tax. The new draws add a long simulation per run, roughly as
costly as a 40-year portfolio run. A flat interest rate ignores deposit-rate
changes and the timing of bank interest credits.

## Validation

Tests cover:

- daily interest compounding to `1.04 ** (days / 365.25)` and its taxation;
- the exact perpetual-rate identity;
- the flat-market zero case;
- the default `planning_age`;
- all existing withdrawal-rate tests.
