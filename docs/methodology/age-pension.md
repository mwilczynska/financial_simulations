# Age Pension and the seniors and pensioners tax offset

Implemented 2026-10-29 in
[age_pension.py](../../src/financial_simulations/rules/au/age_pension.py),
[tax.py](../../src/financial_simulations/rules/au/tax.py) (SAPTO) and the
[retirement ledger](retirement-ledger.md). Decision:
[ADR 0027](../decisions/0027-age-pension-and-sapto.md). Parameters and their
sources are in the [2026-27 rule register](../rules/au-2026-27.md#age-pension-single-normal-rates).

## Purpose

From Age Pension age (67) two rules change a retiree's cash flow:

- the means-tested **Age Pension**;
- the **seniors and pensioners tax offset (SAPTO)**, with its higher Medicare
  levy low-income thresholds.

Before these were modelled, the planner stopped before the income year in
which the person turned 67. That left most of an early retiree's retirement
untested by the tax ledger. With both rules in place, the ledger runs to the
planning age.

## Scope and assumptions

**Implemented** (from user requirements and Services Australia, DSS, DVA and
ATO pages read on 2026-10-29):

- one single person at normal (not transitional) rates;
- homeowner or non-homeowner;
- the assets test and the income test, with deeming;
- the Work Bonus for wages earned after 67;
- the tax treatment of each pension component;
- SAPTO with rebate income;
- the senior Medicare thresholds.

**Assumptions:**

- 10 years' Australian residence (5 continuous), and a claim on time.
- Other personal assets (cars, contents) are a nominal amount that the user
  enters. It is held constant.
- 2026-27 SAPTO and senior Medicare thresholds equal the 2025-26 values, the
  latest published.

**Not modelled:**

- couples;
- Rent Assistance;
- transitional rates;
- grandfathered income streams;
- gifting and deprivation;
- the Commonwealth Seniors Health Card and other concessions;
- payment of the pension supplement minimum to some part-pensioners;
- the Pension Loans (Home Equity Access) Scheme.

## Fortnightly rate

Each Age Pension payday (every 14 days, the first a fortnight after the 67th
birthday) the ledger computes:

```
maximum          = basic rate + pension supplement + energy supplement
financial assets = cash + outside investments + accumulation super + account-based pension   (previous close)
assessed assets  = financial assets + other assets                                          (home exempt)
assets reduction = max(0, assessed assets - limit) / 1000 * 3           limit: homeowner or non-homeowner
deemed income    = (min(F, T) * lower_rate + max(0, F - T) * upper_rate) / 26     F = financial assets, T = threshold
income           = deemed income + wages this fortnight after the Work Bonus
income reduction = max(0, income - free area) * 0.5
rate             = max(0, maximum - max(assets reduction, income reduction))
```

From 20 September 2026 (single) the inputs are:

| Input | Value |
| --- | --- |
| Basic rate | $1,135.40 |
| Pension supplement | $88.20 |
| Energy supplement | $14.10 |
| Maximum rate | $1,237.70 |
| Assets limits | $333,000 homeowner; $600,000 non-homeowner |
| Deeming | 1.75% to $66,800; 3.75% above |
| Income free area | $226 |

The ledger values every account at the previous close, so the assessment
follows markets daily. Centrelink revalues listed investments and
account-based pensions periodically (on reporting and on 20 March and 20
September) rather than daily. That is a known simplification.

**Assets taper.** The reduction is taken pro rata per dollar over the limit.
The published part-pension cut-offs ($745,750 homeowner, $1,012,750
non-homeowner) are reproduced: limit + maximum rate / 0.003.

**Work Bonus.** A $300 credit accrues each fortnight, up to an $11,800
balance. It offsets employment income before the income test.

## Tax treatment

The taxable part of the Age Pension is assessable income. It is the basic
rate plus the basic part of the pension supplement ($30.70). The minimum and
remaining parts of the supplement ($57.50) and the energy supplement are
tax-free. For a part pension the ledger applies the full-rate taxable share,
`(basic + supplement_taxable) / maximum`, to the amount paid. This is an
approximation: the law reduces components in a set order. The error is at
most the tax on the tax-free supplements, about $1,860 a year of income.

The Age Pension is paid gross. As with other income, the 30 June assessment
settles the tax.

## SAPTO

SAPTO applies in every income year in which the person reaches Age Pension
age at any time. Eligibility does not depend on the pension being paid, and
residence is assumed. The single offset for 2025-26 (ATO) is:

```
rebate income = taxable income + reportable employer super + deductible super contributions + reportable fringe benefits
SAPTO         = 0 if rebate income >= 52,759, else ceil(2,230 - 0.125 * max(0, rebate income - 34,919))
```

- **Non-refundable.** With LITO, it can reduce basic tax to nil but not
  below. Net investment losses are nil, because a loss year has nil taxable
  income in this model.
- **Medicare thresholds.** A taxpayer entitled to at least $1 of SAPTO uses
  the senior Medicare levy thresholds: $44,268 lower and $55,335 upper.
  Others use $28,011 and $35,013.
- **Reporting.** `TaxAssessment.sapto` is the offset actually used.
  `lines["sapto_entitlement"]` is the entitlement before the basic-tax limit.

## Projection

See [au-projection.md](../rules/au-projection.md).

- **Basic rate:** grows with the assumed wage growth. This stands in for the
  benchmark of the couple rate to 41.76% of MTAWE, which has usually set
  increases since 2009 (DSS Guide 5.1.8.50).
- **Pension supplement** (and its taxable part): grows with CPI.
- **Energy supplement:** held at $14.10.
- **Assets limits, income free area and deeming threshold:** grow with CPI
  and are rounded to $250, $2 and $200.
- **Held at current values:** the deeming rates, which the Minister sets, the
  Work Bonus and SAPTO.

Each financial year holds one value. The law indexes rates on 20 March and
20 September, and the thresholds on 1 July.

## Effect on results

- **Path flows.** Each path's daily `age_pension` flow appears in the money
  in and out charts and in today's-dollar flows. It reduces the withdrawal
  rate, which is the draw on your own wealth: spending plus tax, less Age
  Pension.
- **Age Pension section in the app:** the share of paths receiving any, the
  median starting age, a typical year's amount and a band chart.
- **Risk to the planning age.** When the horizon reaches the planning age,
  the ledger's own risk of ruin replaces the portfolio-only estimate.

## Validation

- `tests/test_au_rules.py`:
  - the published maximum rate;
  - deeming;
  - which test binds for a homeowner and a non-homeowner;
  - the published assets and income cut-offs;
  - the taxable part and the Work Bonus;
  - the ATO SAPTO example ($39,000 of rebate income gives $1,720);
  - the senior Medicare threshold;
  - reportable super removing SAPTO;
  - SAPTO's non-refundability.
- `tests/test_ledger.py`:
  - 26 fortnightly payments;
  - the first assessed on the previous close plus other assets;
  - payments rising as wealth falls;
  - the taxable sum in the assessment;
  - SAPTO entitlement;
  - the daily flow reconciling;
  - the stop without `age_pension`.
- `tests/test_plan.py`: the horizon runs past 67 and the plan inputs reach
  the scenario.

A 40-path check of a long-horizon private plan behaved as expected:

- paths that ran down received the full rate, rising in today's dollars at
  about the gap between wage growth and CPI;
- wealthy paths received none until their assets fell;
- SAPTO was used in eligible low-tax years.

The same check found 18 of 40 paths above the Division 296 threshold, which
is not implemented. Those paths are excluded, so long-horizon results are
conditional on the others.

## Limitations

- Single only; the planner's couple scope will need the couple rates,
  combined tests and SAPTO transfer.
- Daily revaluation of assets, as described above.
- 2026-27 values apply from 1 July, although rates for 1 July to 19
  September 2026 were lower (by under 3%).
- The Division 296 tax on super balances above $3 million is still not
  implemented. Long horizons on high-growth portfolios often exceed it, and
  those paths are excluded.

## References

- Services Australia:
  - [How much Age Pension you can get](https://www.servicesaustralia.gov.au/how-much-age-pension-you-can-get)
  - [Assets test](https://www.servicesaustralia.gov.au/assets-test-for-age-pension)
  - [Income test](https://www.servicesaustralia.gov.au/income-test-for-age-pension)
  - [Work Bonus](https://www.servicesaustralia.gov.au/how-work-bonus-works)
- DSS Social Security Guide:
  - [4.4.1.10 Deeming](https://guides.dss.gov.au/social-security-guide/4/4/1/10)
  - [5.2.2.10 Maximum basic rates](https://guides.dss.gov.au/social-security-guide/5/2/2/10)
  - [5.1.8.50 Indexation](https://guides.dss.gov.au/social-security-guide/5/1/8/50)
- Pension supplement components:
  - [DVA Income Support Payment Rates 20 September 2026](https://clik.dva.gov.au/book/export/html/86936)
  - [Services Australia Pension Supplement blueprint](https://operational.servicesaustralia.gov.au/public/Pages/income-assests-and-rates-of-payment/108-08020000-01.html)
- ATO:
  - [Seniors and pensioners tax offset](https://www.ato.gov.au/individuals-and-families/income-deductions-offsets-and-records/tax-offsets/seniors-and-pensioners-tax-offset)
  - [Income tests](https://www.ato.gov.au/individuals-and-families/income-deductions-offsets-and-records/income-tests)
  - [Medicare levy reduction for low-income earners](https://www.ato.gov.au/individuals-and-families/medicare-and-private-health-insurance/medicare-levy/medicare-levy-reduction/medicare-levy-reduction-for-low-income-earners)
