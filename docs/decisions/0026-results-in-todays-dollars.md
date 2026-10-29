# ADR 0026: report results in today's dollars

Date: 2026-10-29. Status: accepted; implemented and locally validated.

## Context

Results mixed nominal amounts with a few deflated ones. Ending wealth
appeared twice, as nominal and in today's dollars, and every other chart was
nominal. The user found it hard to compare like with like, even with labels.
They asked for every number that can be inflation-adjusted to be shown that
way.

## Alternatives

1. Keep nominal results and label them better.
2. Offer a nominal/real toggle.
3. Convert every result to today's dollars, keep the ledger nominal, and
   say where a figure cannot be converted.

## Decision

Option 3.

- Today's dollars are dollars of the plan's start date, deflated at the CPI
  assumption.
- A balance on date `d` is divided by `(1 + CPI) ** ((d - start) / 365.25)`.
- A flow in a financial year (salary, spending, tax, returns, transfers) is
  divided by `(1 + CPI) ** n`, with `n` whole financial years since the
  opening year.
- `household_flows(..., inflation=True)` adds an `Inflation` flow, the
  difference between the change in real wealth and the sum of real flows.
- The path summaries convert the ledger before summarising. So bands, the
  every-path chart, flows, outcome tables, the CSVs and the PNG plots are in
  the same units.
- Section 3 deflates month-end portfolio values. Volatility and drawdowns
  stay on nominal daily returns.
- Section 2's history stays nominal, because the source data have no
  inflation series. The ledger, its event log and its CSV downloads stay
  nominal.

## Reasons

- A retiree thinks in today's money. Comparing a 2045 amount with a 2026
  amount in nominal dollars invites error.
- A flow on the financial-year step leaves CPI-indexed spending constant,
  which matches how spending is entered. It also leaves each year's
  withdrawal rate unchanged.
- Tax law is nominal: brackets, caps and the CGT discount apply to nominal
  amounts. So the ledger cannot run in real terms.
- The `Inflation` flow keeps the money in and out charts reconciled, and it
  shows a cost that nominal charts hide.

## Consequences

- Results change units. A real return below inflation now shows as a loss.
- Within a year, prices rise smoothly while flows step on 1 July. So the
  `Inflation` flow also absorbs a small timing difference.
- `Ending wealth, today's dollars` is removed. `Ending wealth` is now in
  today's dollars, and `Ending wealth, nominal` remains in the CSV.
- Real drawdowns would be slightly deeper than the nominal ones reported
  over long underwater spells.

## Validation

- `tests/test_ledger.py::test_todays_dollars_keep_cpi_indexed_spending_flat_and_flows_reconcile_with_inflation`
- `tests/test_ledger.py::test_path_summary_reports_starting_spending_and_rate_in_todays_dollars`
