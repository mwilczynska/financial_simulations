# ADR 0020: explicit outside contributions that stop at retirement

Date: 2026-10-29. Status: accepted; implemented and locally validated. The stop on all
new investing at retirement was superseded on 2026-10-30 by
[ADR 0030](0030-reinvest-surplus-cash-in-retirement.md): cash above the buffer is now
reinvested after retirement. The contribution modes stand.
Extends the surplus-investing convention of the
[retirement ledger](../methodology/retirement-ledger.md).

## Context

The user asked whether contributions to investments outside super could be
entered, said this was needed, and that investing should stop at
retirement. They then asked for an option to raise a fixed annual amount
with inflation. The ledger invested every dollar of cash above the buffer,
before and after retirement. The amount saved therefore depended on
salary, sacrifice, spending and tax, and the user had no direct control
over it.

## Alternatives considered

1. Keep the surplus sweep and only explain it. This does not answer the
   request.
2. Replace the sweep with a fixed amount. People who save "whatever is
   left" would then have to estimate it.
3. Offer both: `surplus` (the previous behaviour) or `fixed`, with optional
   CPI indexing of the fixed amount. Stop all new investing at retirement.

## Decision

Choose 3. In fixed mode each payday schedules `contribution_per_year / 26`.
If indexed, it is multiplied by `(1 + cpi) ** n` after `n` whole financial
years, the same step-up convention as spending. At the observation close
the ledger invests the lesser of that amount and the cash above the buffer.
An amount that cannot be met is not carried forward. In both modes no new
outside investment is made on or after the retirement date. Salary
sacrifice can also be entered as a percentage of salary, which is added to
any dollar amount.

## Reasons and consequences

The inputs and the stop at retirement are **user requirements**. The
no-catch-up rule and the payday timing are **engineering choices**.

- In fixed mode, pay left after the contribution stays in cash. The ledger
  pays no interest on cash, so this money does not grow.
- After retirement, pension payments above the legislated minimum need and
  any unspent lump sums also stay in cash. Earlier runs reinvested that cash
  outside super, so results for plans whose pension minimum exceeds spending
  are lower than before.
- Interest on cash, or an option to reinvest in retirement, would remove
  this drag. Neither is implemented.

## Implementation and validation

Implemented in `retirement/ledger.py` (`outside_contribution_per_payday`,
`outside_contribution_growth`, `stop_investing_at_retirement`) and
`retirement/plan.py` (`outside.saving`, `contribution_per_year`,
`contribution_indexed`, `employment.salary_sacrifice_percent`). The app
inputs are on the You and Investments tabs. Tests in `tests/test_ledger.py`
and `tests/test_plan.py` cover:

- fixed amounts invested exactly on paydays, with the remainder left in
  cash;
- no outside purchases after retirement in either mode;
- the indexed step-up to 103 from July 2027;
- the schema mapping and validation.
