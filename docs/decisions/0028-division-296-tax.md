# ADR 0028: assess Division 296 tax instead of rejecting large super balances

Date: 2026-10-29. Status: accepted; implemented and locally validated.

## Context

The ledger stopped any path whose total super balance (TSB) passed the $3
million Division 296 threshold at a 30 June. Once runs could reach the
planning age (ADR 0027), long horizons on high-growth portfolios hit the
threshold on many paths:

- 59 of 100 on the 40-year example plan;
- 18 of 40 on a private 50-year plan.

Excluding them left results conditional on the poorer paths and overstated
the risk of ruin. The user asked for Division 296 to be implemented.

## Sources

- Treasury Laws Amendment (Building a Stronger and Fairer Super System) Act
  2026 (No. 8, 2026), ITAA 1997 Division 296:
  - s296-40, taxable super earnings, with the 2-decimal rounding;
  - s296-45, the very large balance component;
  - s296-55, total super earnings;
  - s296-60, Division 296 fund earnings;
  - s296-65, attribution on a fair and reasonable basis;
  - s296-130, payable 84 days after the notice;
  - release from super under TAA Schedule 1 Division 131.
- ATO, "How Division 296 tax is calculated" (updated 29 June 2026), and
  "About Division 296 tax for APRA funds" (updated 29 June 2026), for the
  CGT factors of 0.2 to 0.8 and the reporting timetable (requests from April
  2028 for 2026-27).

## Alternatives

1. Keep rejecting the paths.
2. Charge a flat 15% on super earnings above the threshold.
3. Implement the enacted formula, with an earnings base from what the ledger
   models.

## Decision

Option 3:

- `superannuation.division_296_tax(tsb_start, tsb_end, earnings, rules)`
  applies the enacted percentages, rounding and rates. It uses the end
  balance only in 2026-27.
- The ledger's earnings are the year's super distributions and franking
  credits, in accumulation and pension. The ledger's funds realise no gains
  (an existing convention, shared with the 15% fund tax), and contributions
  are excluded, as the fund-earnings formula requires.
- The tax is released from super, accumulation first then the pension, on
  30 September 15 months after the year ends. This is an assumed date
  combining the ATO's reporting timetable and the 84-day payment period. A
  shortfall is paid personally or recorded as unpaid.
- It is a separate `division_296` flow in the ledger, flows, today's-dollar
  results and charts.

## Reasons

- The formula and rounding are enacted, and the ATO's worked examples test
  them exactly.
- Keeping the ledger's no-realised-gains convention avoids inventing a fund
  turnover rate. The shortfall is stated plainly instead.

## Consequences

- Large-balance paths stay in the results. The 40-path check of the private
  plan had no unsupported paths, and 18 paid Division 296.
- The tax shown is a **lower bound**. Real funds realise gains (from
  2029-30, at full value for large APRA funds), so their earnings, and the
  tax, are higher than distribution income alone.
- Not modelled:
  - defined benefit interests;
  - small-fund (SMSF) cost-base elections;
  - Division 296 debt-account deferral;
  - death-year rules;
  - interest on late payment.

## Validation

- `tests/test_au_rules.py::test_division_296_matches_the_ato_worked_examples`
- `tests/test_ledger.py::test_division_296_taxes_super_earnings_above_3m_and_is_released_from_super`
