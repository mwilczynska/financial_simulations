# ADR 0024: index salary to the wage-growth assumption

Date: 2026-10-29. Status: accepted; implemented and locally validated.

## Context

The ledger paid the same nominal salary every year until retirement. The
wage-growth assumption only indexed contribution caps and Medicare levy
surcharge thresholds (ADR 0015). Spending grew each 1 July, so pay fell
behind spending every year.

On the user's plan this made outside saving start high and fall to nearly
zero within a few years. The user asked whether salary should be indexed
and whether wage growth should already cover it.

## Alternatives

1. Keep salary constant in nominal dollars. This is simple, but it is a
   real pay cut of about the CPI rate every year. Over a 10–20 year working
   horizon it understates saving substantially.
2. Index salary to CPI. This keeps buying power constant but ignores
   productivity growth, which average wages have historically included.
3. Index salary to the wage-growth assumption. This uses the same rate the
   planner already applies to wage-indexed caps.
4. Add a separate salary growth rate. This handles individual career paths
   but adds another input that usually equals wage growth.

## Decision

Adopt option 3, with a switch:

- `employment.salary_indexed` (default `true`) sets `Employment.annual_growth`
  to `assumptions.wage_growth_annual`. When it is `false`, the rate is 0 and
  the earlier behaviour is kept.
- Salary steps up each 1 July, by the same whole-financial-year count as
  spending growth.
- Salary sacrifice grows by the same factor, so a percentage stays a
  percentage and a dollar amount keeps its share of pay.
- PAYG withholding is estimated each year on that year's grown salary.

## Reasons

- Wage growth is the planner's existing assumption for how earnings grow.
  Using it for salary is consistent with its use for caps.
- Indexed salary is the usual planning default. A fixed nominal salary is an
  implicit, unstated pay cut.
- The switch keeps a nominal-salary case available for people who expect no
  rises.

## Consequences

- Saving outside super, super guarantee and sacrifice all rise with salary.
- Tax brackets are not indexed in law (`docs/rules/au-projection.md`), so a
  growing salary pays a growing share in tax (bracket creep). The ledger
  models this.
- A rising salary sacrifice can exceed the concessional cap in later years
  (the cap is wage-indexed but rounded down to $2,500). The ledger then
  stops with its existing excess-contributions message.
- Plans saved without the field load with indexing on, which changes their
  results. Set `salary_indexed = false` to reproduce earlier runs.

## Validation

- `tests/test_ledger.py::test_salary_and_sacrifice_grow_each_first_of_july_and_withholding_follows`
- `tests/test_plan.py::test_salary_follows_wage_growth_unless_switched_off`
