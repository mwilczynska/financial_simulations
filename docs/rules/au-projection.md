# Australian rules after 2026-27: projected rule sets

Implemented 2026-10-28 in
[projection.py](../../src/financial_simulations/rules/au/projection.py).
Decision: [ADR 0015](../decisions/0015-projected-rules-and-cgt-reform.md). The
base year is the verified [2026-27 register](au-2026-27.md).

`project_rulesets(base, through, ProjectionAssumptions(cpi_annual,
wage_growth_annual, wato_amount=250))` derives each later income year from the
previous one. Each parameter is treated as follows:

| Parameter | Treatment from 2027-28 | Status |
| --- | --- | --- |
| Resident tax rates | 14% / 30% / 37% / 45% (Act No. 28, 2025) | Enacted |
| Resident tax thresholds, LITO, Division 293 threshold, $500,000 carry-forward test, SG 12%, standard deduction $1,000, preservation and Age Pension ages, minimum drawdown factors | Unchanged: not indexed in law | Enacted (inherited) |
| Working Australians Tax Offset | Lesser of $250 and a ministerial amount, for net labour income above $18,200 (Act No. 49, 2026, s61-155 and s61-160) | **Assumption** on the amount (default $250) |
| Minimum capital gains tax | 30% (Act No. 49, 2026, Division 119) | Enacted |
| Concessional cap | AWOTE-indexed, rounded down to $2,500 | **Projected** with assumed wage growth |
| Non-concessional cap | 4 x concessional cap | Projected |
| Maximum contribution base | Concessional cap x 100 / 12, rounded down to $10 | Projected |
| Transfer balance cap | CPI-indexed, rounded down to $100,000 | Projected with assumed CPI |
| Bring-forward thresholds | Transfer balance cap less two or one non-concessional caps | Projected |
| MLS thresholds | AWOTE-indexed, rounded down to $1,000 | Projected |
| Division 296 thresholds | CPI-indexed in $150,000 and $500,000 increments | Projected |
| Medicare low-income thresholds | Set by legislation each year; frozen at the latest value | **Assumption** |
| `assumed_cpi_annual`, `assumed_wage_growth_annual` | Declared inputs | **Assumption** |

## Indexation approximation

Indexation compounds an unrounded amount from the 2026-27 published value at
the assumed annual rate. The law instead indexes statutory base amounts using
actual index ratios for specified quarters. A projected cap can therefore
differ from the eventual published value by about one increment, even when
the assumed growth is correct. The assumptions are flat annual rates and are
not forecasts. `RuleSet.manifest()` lists every projected and assumed
parameter for each year, so reports carry them.

## CGT reform (from 1 July 2027)

Act No. 49, 2026, Schedule 1, was read on legislation.gov.au on 2026-10-28.

- **Deemed sale and reacquisition (s112-155).** An individual's asset held
  throughout 30 June 2027 is treated as sold just before 1 July 2027 and
  reacquired on 1 July 2027 at its market value. The apportionment
  alternative (s112-185) is not yet legislated and is not implemented. The
  ledger records each parcel's 30 June 2027 closing value.
- **Deferred gain (s112-160).** The initial notional gain or loss is deferred
  to the year of the later real sale. It is a discount capital gain if the
  12-month test, counted to the real sale, is met, so the 50% discount still
  applies.
- **Post-reform gain (s110-36(1A), s960-275(1B)).** The cost base is indexed
  by CPI(event quarter) / CPI(expenditure quarter), rounded to 3 decimal
  places, with no indexation when the factor is 1 or less. Indexation applies
  only if the asset was held 12 months, counting the original acquisition and
  disregarding the deemed reacquisition (s112-160(5)). Indexation cannot
  create or increase a loss. Post-reform gains are not discounted.
- **Minimum tax (s119-5, s119-10).** The minimum tax capital gain is the
  post-reform gains remaining after capital losses. Extra tax = 30% x that
  gain − (basic tax − basic tax with taxable income reduced by that gain),
  rounded down to whole dollars, if positive. Recipients of the payments in
  s119-15 (for example Age Pension and JobSeeker) are exempt; the input is
  `minimum_tax_exempt`. Gifts that reduce the base are not modelled. The
  extra tax is added after non-refundable offsets (engineering
  interpretation).
- **CPI path.** The CPI path is the constant assumed annual rate compounded
  quarterly. Real ABS quarterly CPI can replace it once Australian CPI is
  added to the datasets project.

Not implemented: residential versus non-residential apportionment (no
property is modelled), new-dwelling and affordable-housing choices,
negative-gearing quarantining, and the apportionment method.
