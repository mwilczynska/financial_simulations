# ADR 0027: model the Age Pension and SAPTO, and run past Age Pension age

Date: 2026-10-29. Status: accepted; implemented and locally validated.

## Context

The ledger stopped before the income year in which the person reached Age
Pension age (67), because the Age Pension and the seniors and pensioners tax
offset (SAPTO) were not implemented. For an early retiree this left about
three decades of retirement to a pre-tax, portfolio-only estimate. That
estimate ignores a means-tested pension that often switches on just as
private wealth runs down. The user asked for both to be implemented properly.

## Alternatives

1. Keep stopping at 67.
2. Run past 67 without the pension or SAPTO. This is cautious (more tax, less
   income) but understates late-retirement income.
3. Implement the single Age Pension (assets and income tests, deeming, Work
   Bonus, tax treatment), SAPTO and the senior Medicare thresholds, with
   sourced current values and declared projections.

## Decision

Option 3, for one single person at normal rates:

- `rules/au/age_pension.py` computes the fortnightly rate. Rule-set
  parameters `age_pension_rate`, `age_pension_assets_test`,
  `age_pension_income_test` and `deeming` hold the 20 September 2026 values
  from Services Australia, DSS and DVA.
- The ledger (`age_pension=True`) pays it fortnightly from a fortnight after
  67. It means-tests on the previous close, with every account as a financial
  asset and the home exempt.
- The taxable part (basic rate plus the basic pension supplement, applied pro
  rata to a part pension) is assessable income.
- SAPTO uses the latest published (2025-26) single amounts, and the senior
  Medicare thresholds apply from the year Age Pension age is reached.
- Projection: the basic rate grows with wage growth (the MTAWE benchmark);
  the supplement grows with CPI; thresholds grow with CPI; the deeming
  rates, Work Bonus and SAPTO are held.
- The planner's horizon now stops only the day before age 110.
  `person.homeowner` and `person.other_assets` are new plan inputs.

## Reasons

- The Age Pension is the main source of income for many Australian retirees,
  and it is strongly countercyclical in this model: it pays more on paths
  where markets did badly.
- Every current value is read from an official page with its effective date.
  Values not yet published for 2026-27 are labelled assumptions.
- Tests reproduce the published cut-offs and the ATO's SAPTO example.

## Consequences

- Results now cover the whole retirement to the planning age when the
  horizon is set that far.
- **Division 296.** Long horizons on high-growth portfolios often take super
  above the $3 million Division 296 threshold, which is still unsupported.
  In a 40-path check of a 50-year private plan, 18 paths were excluded. The
  app already labels results as conditional when paths are excluded.
  Implementing Division 296 is the next limit to lift. (Implemented the
  same day: [ADR 0028](0028-division-296-tax.md).)
- **Daily revaluation.** The means test revalues assets daily rather than on
  Centrelink's schedule.
- **Split of a part pension.** A part pension's taxable split is
  approximate (at most the tax on about $1,860 a year).
- **Out of scope:** couples, Rent Assistance and concessions.

## Validation

- `tests/test_au_rules.py::test_age_pension_assets_and_income_tests_match_published_figures`
- `tests/test_au_rules.py::test_sapto_matches_the_ato_example_and_unlocks_the_senior_medicare_thresholds`
- `tests/test_ledger.py::test_age_pension_is_paid_fortnightly_means_tested_and_taxed_with_sapto`
- `tests/test_ledger.py::test_without_the_age_pension_switch_the_ledger_still_stops_at_age_pension_age`
- `tests/test_plan.py::test_horizon_runs_past_age_pension_age_with_the_age_pension`
