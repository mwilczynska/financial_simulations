# ADR 0036: require the opening year-to-date position for a start after 1 July

Date: 2026-11-02.

Status: accepted; implemented and tested.

## Context

[Review finding 8](../reviews/2026-11-01-retirement-calculations/README.md) (P1 for an existing worker starting
mid-year): the ledger started every run with zero year-to-date salary, withholding, contributions and income.
It then assessed the part year against full-year thresholds and caps. In the review's case, a continuing
$104,000 salary assessed at $23,480 over the whole year produced only $5,265 when the run started on
1 January, and a false $5,571.92 refund of the modelled withholding. Employer contributions in flight at the
start and last year's tax still to settle were also absent. The assumption that nothing happened before the
start was not recorded anywhere.

## Alternatives considered

1. Reject mid-year starts until opening inputs exist. This is safe but blocks a common case: planning from
   today.
2. Annualise the part year. This invents income and does not handle withholding or caps.
3. Accept an opening year-to-date position, and require it to be stated for a mid-year start.

## Decision

Choose 3.

- **Ledger.** `OpeningYear` seeds the first financial year's totals with:
  - salary after sacrifice, sacrifice and withholding;
  - concessional and non-concessional contributions received;
  - interest, unfranked and franked dividends with credits, and other assessable income;
  - CGT events and Age Pension.

  It also adds pending employer contributions (arriving on or after the start) and tax due (on or after the
  start). A run starting after 1 July without `opening_year` raises `ValueError`. Opening non-concessional
  contributions establish the bring-forward state, and opening concessional contributions above the cap stop
  the run.
- **Plan.** A `[year_to_date]` section with `entered` and eleven amounts. A start after 1 July requires
  `entered = true`. Zeros are valid once confirmed.
  - **Planner simplifications:** other taxable income is assessed as ordinary income. The Age Pension's
    taxable part uses the year's rate share. Pending employer contributions arrive seven business days after
    the start. `prior_year_tax` is due 31 October, or at the start if later.
- **App.** An expander under the horizon holds these inputs and a confirmation checkbox. It opens
  automatically for an unconfirmed mid-year start.

## Reasons and evidence

- **Tax law (verified fact):** income tax, the LITO/SAPTO tapers, the concessional cap and the Medicare
  thresholds all apply to the whole financial year. A part year cannot be assessed on its own.
- **Engineering judgement:** explicit confirmation records the assumption that a mid-year run would otherwise
  make silently. The ledger-level object can represent everything the ledger tracks. The plan keeps a short,
  user-facing subset.
- **Evidence:** the regression test resumes the review's $104,000 case on 1 January using the first half-year
  as the opening position. It then reproduces the full-year taxable income, net tax, settlement and
  concessional total. With `OpeningYear()` it shows the false refund, which is why a blank opening year must
  be stated deliberately.

## Consequences

- Existing plan files that start on 1 July are unchanged. Mid-year plan files must add the section.
- **Not represented:**
  - fund income earned earlier in the year (its accrued tax is taken as reflected in the opening balance);
  - Division 296 earnings before the start;
  - planner-level capital gains that attract the minimum tax;
  - Work Bonus balances (finding 11 remains open).
- PAYG withholding still estimates a full year's tax spread over 26 paydays. Supplying the withholding already
  paid makes the total consistent.

## Implementation and validation

- **Code:**
  - `OpeningYear` and its use in `run_ledger` (`retirement/ledger.py`);
  - `YEAR_TO_DATE`, the `year_to_date` validation and `opening_year` (`retirement/plan.py`);
  - `year_to_date_inputs` (`ui/app.py`).
- **Methodology:** [retirement-ledger.md](../methodology/retirement-ledger.md) and
  [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:**
  - `tests/test_ledger.py::test_a_midyear_start_needs_its_opening_year_and_then_matches_the_full_year`
  - `tests/test_ledger.py::test_opening_year_carries_last_years_tax_and_rejects_dates_outside_the_part_year`
  - `tests/test_plan.py::test_a_midyear_plan_start_requires_confirmed_year_to_date_amounts`
  - `tests/test_plan.py::test_a_1_july_plan_start_passes_last_years_tax_and_age_pension_split`
  - `test_annual_rebalance_resets_weights_and_realises_outside_cgt` now states `OpeningYear()` for its
    December start.
  - `test_a_weekend_30_june_horizon_is_still_assessed` now keeps the Saturday 1 July opening mark.
- **Not checked:** Streamlit is not installed in the validation environment, so the app input itself was
  compiled but not exercised.
