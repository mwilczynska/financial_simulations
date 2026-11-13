# Investment property

Decision record: [ADR 0054](../decisions/0054-investment-property-in-the-ledger.md). Code: `InvestmentProperty`,
`Mortgage` and `run_ledger` in `retirement/ledger.py`; the `[investment_property]` plan section in
`retirement/plan.py`.

## Purpose and scope

This models one residential property let to tenants and held for the whole run, with an optional loan. It covers:

- monthly cash flow: rent less running costs and loan repayments, paid before spending;
- income tax on net rent, with losses carried forward or offset against salary;
- the property's value and equity in net wealth;
- the Age Pension means test.

The property is never sold, so there is no capital gains tax, sale proceeds or sale costs. One owner, as for the rest of
the ledger.

## Inputs and provenance

| Field | Meaning | Default | Status |
| --- | --- | --- | --- |
| `value` | Market value on the start date; 0 means no property | 0 | User input |
| `weekly_rent` | Rent today | 0 | User input |
| `loan` | Amount owed on the property's loan today | 0 | User input |
| `growth` | Value growth a year, applied monthly | 4% | Assumption (engineering judgement) |
| `interest_rate` | Loan rate, fixed for the run | 6% | Assumption |
| `years` | Years left on the loan | 25 | User input with a default |
| `interest_only_years` | Interest-only years left | 0 | User input with a default |
| `running_costs` | Repairs, council rates, insurance, strata and land tax, as a share of value a year | 1.5% | Assumption (engineering judgement: about 1% repairs and 0.5% for the rest) |
| `losses_offset_salary` | A net rental loss reduces tax on other income | false | User input; see Tax |

Fixed in the model, not inputs:

- **Rent kept:** 90% of rent, allowing for vacancy and management (`RENT_KEPT`, engineering judgement).
- **Rent growth:** the plan's CPI assumption, stepped each 1 July like spending.

`spending.annual` should exclude the property's costs and repayments, and `person.other_assets` should exclude the
property.

## Equations and conventions

On the first of each month (and on the start date):

```
rent  = weekly_rent × 52 / 12 × 0.9 × (1 + cpi)^(financial years since the start)
costs = running_costs × value / 12
```

Rent is credited to cash that day. Costs fall due and are paid on the first observation day on or after it.

On the last day of each month:

```
value = value × (1 + growth)^(1/12)
```

The loan follows the home loan's conventions ([home-loan.md](home-loan.md)):

- interest accrues daily at `rate / 365` and is charged at month end;
- repayments are due every 14 days from the first payday on or after the start;
- during an interest-only period each repayment is `loan × rate / 26`;
- after it, the annuity `P = B r / (1 − (1 + r)^−n)`, with `r = rate / 26` and `n = round(years × 26) −
  interest-only fortnights`, clears the balance.

There is no redraw and no extra-repayment setting on this loan.

Wealth (daily columns):

```
spendable = cash + outside investments + accumulation + pension − home loan
total     = spendable + property_value − property_loan
```

## Algorithm

Each day, in the ledger's event order ([retirement-ledger.md](retirement-ledger.md)):

1. **Interest** accrues on both loans.
2. **First of the month:** rent is received; the month's running costs fall due.
3. **Repayments.** On an observation day, the home loan's required repayment, then this loan's, are paid through the
   needs waterfall (cash, outside sales, accessible super). Unpaid amounts are a `shortfall` (event purpose
   `property_loan`) and stay on the loan.
4. **Running costs** are paid the same way (purpose `property_costs`). An unpaid amount is a shortfall and is dropped,
   like unpaid spending.
5. **Spending, tax and investing** follow as before. A negative net cash flow leaves less to invest; a positive one adds
   to it. Neither spending nor tax can redraw from this loan, and the home loan's redraw does not pay property costs or
   repayments.
6. **Month end:** both loans charge their interest, and the value grows.
7. **Reconciliation:**
   - assets reconcile with rent as an inflow, and costs and principal repaid as outflows;
   - each loan reconciles (`owed = opening owed + interest − repaid`);
   - the value reconciles with its growth.

## Tax

Each 30 June the year's rental result is:

```
net = rent received − interest incurred − running costs paid − loss carried forward
```

- **A profit** (`net ≥ 0`) is assessable income.
- **A loss, when `losses_offset_salary` is false (the default)**, is carried forward to the next year's calculation and
  does not reduce tax on other income.
- **A loss, when `losses_offset_salary` is true**, is a deduction against other income (negative gearing), and nothing
  is carried forward.

**The law (primary source).** Treasury Laws Amendment (Tax Reform No. 1) Act 2026 (Act No. 49, 2026), Schedule 2,
inserts ITAA 1997 s 26-155. From the 2027-28 income year, deductions for holding residential dwellings as residential
accommodation are not deductible to the extent they exceed the assessable income from those dwellings. The excess is
a quarantined amount:

- it is applied first against residential capital gains in the net capital gain method (s 102-5 steps 3 and 4);
- the rest carries forward as a deduction in the next year, under the same test.

Two kinds of dwelling are exempt:

- an ownership interest last acquired before 7.30 pm (ACT legal time) on 12 May 2026, counting from the contract date;
- a new residential dwelling, as defined by ministerial determination under s 26-160.

**How the model applies it (engineering judgement).**

- The default quarantines losses in every year, including 2026-27, and treats deductions as rent less interest and
  running costs. The user chose this as the cautious default; the law begins in 2027-28.
- `losses_offset_salary` is the setting for an exempt (grandfathered or new) property. The app's hint says so.
- No sale is modelled, so a carried loss is never used against a capital gain. It is reported as
  `rental_loss_carried_forward`, in each year's record and at the end.
- Depreciation (Divisions 40 and 43) and borrowing costs are not modelled. A loss year's other deductions do not change
  the income tests that add back net investment losses (rebate income, Division 293 income). That only matters with
  `losses_offset_salary`.

## Age Pension

On each Age Pension payday, using the previous close:

- **Assets test:** the value less the loan secured on it, not below nil, is added to assessable assets. The property is
  not the principal home. A charge on an asset reduces that asset's value (Social Security Act 1991 s 1121).
- **Income test:** net rent is income, on top of deemed income:

```
other income = max(0, 12 × this month's rent − running_costs × value − owed × rate) / 26
```

The Social Security Guide (4.3.8.30, "Real estate income") says rental income is generally assessed as it is for tax.
It also says capital depreciation, the special building write-off and construction costs are not allowed as
deductions. This model has no depreciation, so its net rent fits that rule. The Guide's treatment of a rental loss
against other income was not confirmed. The model does not let a loss reduce other assessed income (a cautious
choice).

## Moving in

ADR 0055. With `move_in_date`, for a person who does not own the home they live in (no home loan or home value), the
property becomes their home on that date:

- the tenants' rent and the person's own rent stop;
- the loan becomes the home loan, with the same repayment schedule and interest that is no longer deductible;
- running costs become `home.running_costs` of the value (1% by default);
- the value continues as `home_value`, growing at the property's rate, and leaves total wealth (flow
  `property_moved_in`, *Became your home*);
- the Age Pension treats it as the exempt home and applies the homeowner limits.

The year's rental result covers the months before the move. Any loss carried forward stays unused. Spendable wealth
now deducts the loan, as for any home loan.

## Spending rules and running out of money

**Spending rules.** All of these use `spendable` wealth, not `total`:

- a starting withdrawal rate (`retirement = "percent"`);
- the `percent`, `vanguard` and `guyton_klinger` reviews;
- the yearly withdrawal rates;
- the starting withdrawal rate in path outcomes.

The user decided that property equity should not count in the percentage spent. The model never sells the property,
so its equity could not pay for spending: counting it would draw down spendable money faster than the chosen rate. Its
fixed growth would also damp the market-responsive rules.

**Running out of money.** The property is not in the needs waterfall. A path can therefore run short while it owns the
property. That is reported as a shortfall, as usual. The path outcome *Property equity when money ran out* shows the
value less the loan on the first shortfall day, in today's dollars: what a sale could have covered.

## Reporting

- **Money in and out:** *Rent*, *Property costs*, *Investment loan interest* and *Property value growth*.
  - Charts draw them as one *Investment property* flow; yearly tables keep each.
  - Principal repaid is a transfer, not a flow.
- **Account flows:** an *Investment loan* account (interest charged, repaid) and an *Investment property* account (value
  growth).
- **Balance charts:** the property's value above the accounts (green) and its loan below zero (violet), only when present.
- **Outcomes bands:** *Spendable wealth*, *Investment property* and *Investment loan owed*, only when a path has a
  property.
- **Path outcomes:**
  - property value and loan owed at the end, and the date the loan is paid off;
  - rent, costs and interest;
  - the rental loss carried forward at the end;
  - property equity when money ran out.
- **Withdrawal rate:** includes the property's interest and costs less rent, over spendable wealth.
- **You tab:** an *Investment property* card with three main inputs and the rest under *More*. It shows the first year's
  net cash and taxable rental result. *Where your pay goes* includes the net cash.

## Example

Ledger run, 1 July 2026 to 30 June 2027, zero market return:

- salary $160,000; spending $75,000; $20,000 cash;
- a $750,000 property at $650 a week;
- $500,000 owed at 6% over 25 years;
- defaults otherwise.

| Item | Amount |
| --- | --- |
| Rent kept (650 × 52 × 0.9) | $30,420.00 |
| Running costs (1.5% of each month's value) | $11,454.79 |
| Loan repayments (26 × $1,485.99) | $38,635.70 |
| **Net cash** | **−$19,670.49** (outside investments $19,670.49 lower than without the property) |
| Interest incurred | $29,669.92 |
| **Rental loss** | **$10,704.71** |
| Value at 30 June | $780,000.00 |
| Loan owed at 30 June | $491,034.21 |

Tax:

- **Default:** the $10,704.71 loss is carried forward. Taxable income stays $159,000, as without the property.
- **With `losses_offset_salary`:** taxable income is $148,295, and the year's tax is $4,174.95 lower ($38,905.05 against
  $43,080.00).

## Validation

`tests/test_investment_property.py`:

- rent, costs, value growth and repayments, and the wealth identities;
- money in and out reconciling with net wealth, the folded chart flow and the loan account;
- quarantine against offset, with taxable income unchanged or reduced by the loss;
- a carried loss reducing a later profit;
- spending rules on spendable wealth;
- unpaid costs and repayments as shortfalls;
- interest-only repayments then the annuity;
- Age Pension assets and income;
- plan validation, the TOML round trip and the inputs the plan builds.

## Limitations

- **Value:** a fixed growth rate on every path. It is not linked to markets, has no volatility and never falls, so wealth
  bands understate risk.
- **No sale:** no capital gains tax and no use of a carried loss against a gain. A depleted path cannot draw on the
  equity.
- **Costs:** one share of value, smooth from month to month. No lumpy repairs, capital works, depreciation, borrowing
  costs or land tax rules by state.
- **Rent:** a fixed 10% vacancy and management allowance; rent indexed to CPI.
- **Loan:** a fixed rate, no offset or redraw, no fees, no refinancing.
- **Tax:** quarantining by default in 2026-27 is a cautious choice, not the law (which starts in 2027-28). Both loss
  settings apply to the whole run. Rebate income and Division 293 income do not add back a rental loss.
- **Age Pension:** current net rent is used, not the Services Australia annual estimate. A rental loss does not offset
  other income.
- **Ownership:** one property and one owner. No joint ownership. The only change of use is one move-in (ADR 0055):
  no moving out, and no CGT main-residence apportionment.

## References

- Treasury Laws Amendment (Tax Reform No. 1) Act 2026 (Cth), Act No. 49, 2026, Schedule 2 (ITAA 1997 ss 26-155,
  26-160) and Schedule 1 item 5 (s 102-5). Federal Register of Legislation, as made 26 June 2026.
- Social Security Act 1991 (Cth), s 1121.
- Department of Social Services, *Social Security Guide*, 4.3.8.30 (real estate income), seen in a search excerpt on
  13 November 2026; the full page was not read.

Revision history: 2026-11-13, first implementation; moving in (ADR 0055).
