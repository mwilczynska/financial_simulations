# ADR 0022: PAYG withholding in the planner

Date: 2026-10-29. Status: accepted; implemented and locally validated.
Changes the "PAYG not modelled" convention of the
[retirement ledger](../methodology/retirement-ledger.md).

## Context

The user asked why "Savings invested" outside super fell from about $52,000
in the first year to about $18,000 in the second, using their saved plan.
Salary arrived gross, and the whole year's tax was paid in one amount on
31 October after the year ended. In 2026-27 no tax left cash, so the surplus
sweep invested pre-tax leftover pay. The 2027-28 cash then paid the whole
2026-27 bill, about $53,800. The jump was a cash-timing artefact.

## Alternatives considered

1. Keep annual settlement and explain the jump.
2. Implement the ATO withholding schedules (scales, coefficients and the
   Medicare and HELP variations).
3. Withhold an estimate. Each payday takes a 26th of the year's assessed tax
   on a full year's salary, and the assessment settles the balance.

## Decision

Choose 3. The planner sets `payg_withholding = True`, and the ledger default
stays off for the existing unit tests. Assessment, Division 293 and
settlement dates are unchanged. Only the cash timing moves forward.

## Consequences

On the user's plan, savings invested became about $19,800 in 2026-27 and
$7,300 in 2027-28. The second year is still lower because it pays the
2026-27 top-up on taxable distributions, interest and gains realised by
rebalancing; withholding does not cover these, as in practice. After that,
take-home pay barely covers spending. Total tax is unchanged; only its
timing moves.

The estimate differs from real withholding by the gap between the
schedules and the exact assessment. It also over-withholds in a part year
of work, which is refunded at settlement.

## Validation

`tests/test_ledger.py` checks:

- 26 withholdings that sum to the salary-only assessment;
- a zero settlement balance;
- the plain run's full liability;
- an unchanged ending wealth, net of that year's tax.
