# ADR 0038: gross wages and the Work Bonus starting credit; order-independent distributions

Date: 2026-11-02.

Status: accepted; implemented and tested.

## Context

The [1 November 2026 retirement calculation review](../reviews/2026-11-01-retirement-calculations/README.md)
found these P2 errors:

- **Finding 11, salary sacrifice.** The ledger fed `gross - sacrifice` into the Age Pension income test. Once
  the Work Bonus was exhausted, a $500 sacrifice cut assessed earnings by $500, which can raise an
  income-tested pension by up to $250 a fortnight.
- **Finding 11, starting balance.** The Work Bonus bank started at nil, ignoring the $4,000 starting credit for
  a new recipient. This error works in the opposite direction to the first.
- **Finding 13.** Each asset's super distribution was reinvested across all target weights before the next
  asset's distribution was calculated. Reversing otherwise identical asset columns changed fund tax from
  $732.58 to $725.51 in one year.

## Alternatives considered

- **Work Bonus starting balance:**
  - always start at nil (understates the concession);
  - always start at $4,000 (overstates it for existing recipients);
  - distinguish new recipients from existing ones with an opening bank.
- **Distributions:**
  - sort the assets (still order-dependent in principle);
  - take one snapshot, drop every price, then reinvest once per account.

## Decision

- **Wages.** Employment income for the Work Bonus and income test is gross wages, including salary sacrifice.
- **Starting balance.** A person whose first Age Pension payday falls in the run, a fortnight after Age Pension
  age, starts with `work_bonus_starting_credit` ($4,000). That is the whole first fortnight's balance, as in
  DSS Example 1. A person already receiving at the start brings `LedgerScenario.work_bonus_balance`
  (default nil). The 2026-27 rule set gains `work_bonus_starting_credit` in `age_pension_income_test`, with the
  DSS guide as its source.
- **Distributions.** Quarterly distributions are calculated for every asset from one holdings snapshot, and
  all prices fall. Then each super account accrues fund tax on, and reinvests, its total once. Distribution
  events are still logged per asset.

## Reasons and evidence

Verified source facts, read in a browser on 2 November 2026:

- Services Australia, "Employment income - Age Pension": "Employment income includes all the following", and
  its list includes "salary sacrifice amounts".
- DSS Social Security Guide 3.1.15.40 (last reviewed 12 August 2024; guide version 1.344): from 1 January 2024
  "all people commencing on an eligible payment receive an upfront $4,000 starting credit". Example 1 shows a
  $4,000 balance in fortnight 1 and $300 added in each following fortnight.

Engineering judgement:

- The bank starts at the first payday from Age Pension age, even when the means test pays nil. Strictly, the
  credit follows commencement on a payment.
- A real fund prices distributions and reinvestment at the unit-price level. The snapshot is the
  order-independent equivalent.

## Consequences

- Working pensioners who salary-sacrifice receive less Age Pension once the bank is exhausted.
- New recipients have up to $4,000 more of earnings exempted early on.
- Results no longer depend on the order of the tickers. Two-asset super holdings change slightly, because
  later assets no longer distribute on units bought from earlier distributions in the same quarter.
- The planner does not set an opening Work Bonus bank, so a plan starting after Age Pension age assumes an
  empty bank.

## Implementation and validation

- **Code:** the Work Bonus `started` state, gross `earned` and the quarterly distribution block in
  `retirement/ledger.py`; `work_bonus_starting_credit` and the `dss-work-bonus-examples` source in
  `rules/au/fy2026_27.toml`.
- **Methodology:** [age-pension.md](../methodology/age-pension.md),
  [retirement-ledger.md](../methodology/retirement-ledger.md) and the
  [2026-27 rules register](../rules/au-2026-27.md).
- **Tests:**
  - `tests/test_ledger.py::test_working_pensioner_income_includes_sacrifice_and_a_new_recipient_gets_the_starting_credit`
    covers $700 assessed for the review's case, an opening bank, and a new recipient.
  - `tests/test_ledger.py::test_super_distributions_do_not_depend_on_the_order_of_assets` covers the review's
    A/B case.
