# ADR 0039: nominal withdrawal rates with Division 296, and claims limited to what is calculated

Date: 2026-11-02.

Status: accepted; implemented and tested. Supersedes the "lasts indefinitely" interpretation in
[ADR 0021](0021-cash-interest-and-withdrawal-rates.md), whose calculation is unchanged.

## Context

The [1 November 2026 retirement calculation review](../reviews/2026-11-01-retirement-calculations/README.md)
found two reporting errors:

- **Finding 14.**
  - Ledger withdrawal rates divided today's-dollar flows, which are deflated in whole financial-year steps,
    by today's-dollar wealth, which is deflated by exact days. For a start after 1 July this does not keep the
    nominal ratio. With a 1 November start and a 10% CPI stress, a nominal 4% showed as 3.87%.
  - The numerator also left out Division 296, although the description says spending plus tax less the Age
    Pension.
- **Finding 15.** Three app claims went further than the calculations:
  - `perpetual_withdrawal_rates` only checks that starting real capital remains at the end of a finite
    window, yet it was called a rate that "lasts indefinitely" and the closest analogue of the 4% rule;
  - the app said bootstrap resampling cannot produce a crash worse than the worst block in the source;
  - it said the percentage-of-wealth rule "can never run out".

## Alternatives considered

- **Withdrawal rates.** Deflate both flows and wealth by date; or compute the ratio from nominal amounts.
  The ratio has no units, so the nominal calculation is exact and needs no new convention.
- **The finite-window rate.** Extend the stochastic horizon to approximate a perpetual rate; or rename it to
  what it computes. Extending is a larger change. If longer-run survival is wanted, it remains possible.

## Decision

- **Withdrawal rate.** The ledger rate is `(spending + max(tax, 0) + Division 296 − Age Pension) / wealth on
  1 July`, all nominal. Financial-year rows also report Division 296 in today's dollars.
- **Renamed rate.** `perpetual_withdrawal_rates` becomes `capital_preserving_withdrawal_rates`, and its
  output column becomes `Capital-preserving withdrawal rate`. The app labels it "keeps real capital to age N"
  and states that it is checked only at that date. The 4% rule is compared with the spend-down rate over
  30 years.
- **Bootstrap text.** Every sampled day is a historical day. Blocks can repeat and join bad stretches, so a
  path can have longer or deeper losses than history did.
- **Percentage-of-wealth text.** Spending resets only each 1 July. Super may be inaccessible, and the minimum
  can force spending above the rate, so this rule can still run short.

## Reasons and evidence

- **Arithmetic (verified):** with the stepped flow deflator, the ratio for financial year `n` is scaled by
  `(1 + cpi) ** (days to 1 July / 365.25 − n)`. That factor equals 1 only for a 1 July start.
- **Review finding:** the 4% rule's 30-year spend-down criterion is not the same as preserving all starting
  real capital (Bengen 1994 used a 30-year depletion test). Block bootstrap paths are concatenations of
  historical blocks, so cumulative losses are not bounded by the worst historical stretch.
- **Engineering judgement:** renaming says what the number is, at no cost to the calculation.

## Consequences

- Withdrawal rates for plans starting after 1 July rise to their nominal values; 1 July starts are
  unchanged.
- Years with Division 296 show higher rates.
- **CSV column.** The portfolio outcomes CSV column is renamed. Scripts that read `Perpetual withdrawal rate`
  must change.
- **Still open:**
  - real flows remain step-deflated, so a CPI-indexed spending series is flat by construction (ADR 0026);
  - the capital-preserving rate is still a single-date test.

## Implementation and validation

- **Code:** `_summarise` in `retirement/paths.py`; `capital_preserving_withdrawal_rates` in
  `retirement/analysis.py`; the `real.py` docstring; the app text in `ui/app.py`.
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:**
  - `tests/test_projection.py::test_withdrawal_rates_are_the_nominal_ratio_for_a_start_after_1_july` covers
    the review's 1 November case with 10% CPI.
  - `tests/test_plan.py::test_capital_preserving_withdrawal_rate_keeps_real_capital` is renamed; its
    calculation is unchanged.
- **Not checked:** Streamlit is not installed in the validation environment, so the app text was compiled but
  not rendered.
