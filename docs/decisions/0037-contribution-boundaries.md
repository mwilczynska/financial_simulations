# ADR 0037: count bring-forward contributions once, and enforce the age-75 acceptance deadline

Date: 2026-11-02.

Status: accepted; implemented and tested.

## Context

The [1 November 2026 retirement calculation review](../reviews/2026-11-01-retirement-calculations/README.md)
found two P2 contribution errors:

- **Finding 9.** The ledger passed the year's cumulative non-concessional total to `apply_non_concessional`.
  When a period was already open, that function added the total to the period's used amount, and the period
  already included this year's earlier payments. With a $200,000 payment then a $50,000 payment against a
  $390,000 three-year cap, the second payment compared $250,000 with the remaining $190,000. It was rejected
  even though only $250,000 had been contributed.
- **Finding 10.** Being over 75 only removed bring-forward eligibility. A synthetic 76-year-old could still
  contribute $50,000 as an ordinary non-concessional contribution, and salary sacrifice continued at any age.

## Alternatives considered

- **Finding 9.**
  1. Change the function to take each payment incrementally.
  2. Keep the cumulative input and pass the bring-forward state at the start of the year.
- **Finding 10.**
  1. Reject the run.
  2. Refuse only the contribution. Non-concessional contributions are a scheduled input, so an invalid one is
     an input error. Salary sacrifice is an arrangement that has to end when the fund can no longer accept it.

## Decision

- **Bring-forward.** The ledger records the bring-forward state at each 1 July (`ncc_period_start`). Every
  call, including opening contributions, passes the year's cumulative total with that state.
  `apply_non_concessional` keeps its signature, and its docstring now states this contract.
- **Age 75.** `voluntary_contribution_deadline(born)` returns 28 days after the end of the month of the 75th
  birthday.
  - A scheduled non-concessional contribution after that date raises `ValueError`.
  - On each payday whose contribution would reach the fund after the deadline, salary sacrifice is set to nil
    and paid as salary. The super guarantee, a mandated employer contribution, continues.
  - Downsizer contributions are not modelled.

## Reasons and evidence

- **Verified source fact:** Superannuation Legislation Amendment (Broadening Contribution Rules) Regulations
  2022 (F2022L01286), Schedule 1, replaced the SIS reg 7.04(1) table from 1 January 2023. For a member "75
  years or older", item 3 allows only mandated employer contributions and downsizer contributions. It was read
  on 2 November 2026.
- **Source limitation:** the 28-day window in reg 7.04(1A) is confirmed from the review's ATO citation and
  practitioner summaries ([SMSF Adviser](https://www.smsfadviser.com/age-can-determine-what-kind-of-contributions-a-fund-can-accept-technical-adviser)).
  The ATO pages refused automated access, and the consolidated regulation text was not retrieved. Recheck the
  wording when the rules are next reviewed.
- **Engineering judgement:** salary sacrifice is a non-mandated employer contribution, so it falls outside
  item 3. Paying it as salary is the planning assumption, not an employer's legal obligation.

## Consequences

- Several non-concessional payments within one year, and repeated payments in later years of a period, now
  work up to the cap.
- People working past 75 lose salary-sacrifice concessions after the deadline; their extra salary is taxed
  normally.
- **Not modelled:** personal deductible contributions; downsizer contributions; the fund's 30-day return of
  an invalid contribution.

## Implementation and validation

- **Code:** `voluntary_contribution_deadline` and the `apply_non_concessional` docstring
  (`rules/au/superannuation.py`); `ncc_period_start`, the deadline check and the payday sacrifice stop
  (`retirement/ledger.py`).
- **Methodology:** [australian-rules.md](../methodology/australian-rules.md) and
  [retirement-ledger.md](../methodology/retirement-ledger.md).
- **Tests:**
  - `tests/test_ledger.py::test_several_non_concessional_payments_count_each_dollar_once` covers three
    payments in the trigger year, and a fourth over the cap.
  - `tests/test_ledger.py::test_voluntary_contributions_stop_28_days_after_the_month_of_the_75th_birthday`
    covers the deadline dates, a contribution on and after the deadline, and sacrifice before and after it.
  - `tests/test_projection.py::test_bring_forward_counts_this_years_total_against_the_opening_period` covers
    repeated payments in a later year of an open period.
