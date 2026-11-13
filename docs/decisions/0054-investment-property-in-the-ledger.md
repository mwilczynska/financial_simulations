# ADR 0054: an investment property in the daily ledger

Date: 2026-11-13.

Status: accepted; implemented and tested.

## Context

[ADR 0052](0052-home-loan-in-the-ledger.md) added a loan on the home the person lives in. The user asked how to model an
investment property: a mortgage repayment offset by rent, and repair costs over time.

The rules table ([au-2026-27.md](../rules/au-2026-27.md)) already listed the 2026 limit on negative gearing as enacted
but not modelled, because investment property was out of scope. The user asked to follow the new law rather than
negative gearing.

The user made these choices in conversation:

- **Scope:** cash flow, loan and tax, with no sale.
- **Value:** a fixed growth rate applied monthly.
- **Repairs:** a yearly share of value.
- **Inputs:** three main inputs (value, weekly rent, loan owed), with everything else defaulted under *More*, including
  whether losses may offset salary.
- **Spending rules:** property equity must not count in the percentage spent.
- **Running out of money:** report a path's shortfall as usual, and show the property equity at that point.

## Alternatives considered

**Value**

- **Fixed growth (chosen).** It is simple, but understates risk.
- **A listed property (A-REIT) series as a daily proxy.** Rejected: it is leveraged commercial property, far more volatile
  than a house.
- **A house price index.** Rejected for now: at best monthly or quarterly, with no local dataset, and the project does not
  fabricate daily observations.

**Repairs**

- **A share of value each year (chosen).**
- **Scheduled capital works.** Deferred.
- **Random large repairs.** Rejected: no data to set them.

**Losses**

- **Always offset against salary (negative gearing).** Rejected as the default. Since 2027-28 the law quarantines losses
  on established dwellings bought after 7.30 pm on 12 May 2026.
- **Ask for the purchase date and property type, and apply the law exactly.** Rejected to keep the inputs short.
- **Quarantine by default, with a setting for grandfathered or new properties (chosen).**
- **Ignore losses altogether.** Rejected: quarantining is already the cautious case, and a loss carried forward against
  later rent is the law's actual effect.

**Spending rules**

- **Count property equity.** Rejected: spending would draw on liquid money faster than the chosen rate, and the
  property's fixed growth would damp the market-responsive rules.
- **Leave equity out (chosen).**

**Sale**

- **A sale on a date, or when money runs out.** Deferred by the user.

## Decision

A plan's `[investment_property]` section has:

- **Main inputs:** `value`, `weekly_rent` and `loan`.
- **Under *More*:**
  - `growth` (4%);
  - `interest_rate` (6%);
  - `years` (25);
  - `interest_only_years` (0);
  - `running_costs` (1.5% of value a year);
  - `losses_offset_salary` (false).
- **Fixed in the model:** rent kept is 90% (vacancy and management), and rent rises with the CPI assumption.

The ledger (`InvestmentProperty`, `LedgerScenario.investment_property`) works as follows:

- **Rent and costs.** Rent arrives on the first of each month. The month's running costs fall due then and are paid on an
  observation day, through the needs waterfall.
- **The loan.** It reuses the home loan's daily accrual and fortnightly repayments, adds an interest-only period, and has
  no redraw. Its repayments are paid after the home loan's and before spending. Unpaid repayments and costs are
  shortfalls.
- **Value.** It grows by `(1 + growth)^(1/12)` on each month's last day.
- **Tax.** Each year, rent less interest incurred, running costs paid and any carried loss is the rental result:
  - a profit is assessable;
  - a loss is carried forward;
  - with `losses_offset_salary`, a loss is deducted from other income instead.
- **Age Pension.** Value less the loan (not below nil) is an assessable asset. Current net rent (not below nil) is
  assessed income.
- **Wealth.**
  - `total` is net wealth including the property's equity;
  - the new daily column `spendable` excludes it;
  - spending rules, starting rates and withdrawal rates use `spendable`;
  - without a property, `spendable` equals the previous `total`, so existing results are unchanged.
- **Reporting.**
  - Four household flows, drawn as one *Investment property* flow in charts.
  - An *Investment loan* account, and property and loan series in charts and bands.
  - Path outcomes, including *Property equity when money ran out*.

## Reasons and evidence

**Primary source.** Act No. 49, 2026, Schedule 2 inserts ITAA 1997 s 26-155, applying from the 2027-28 income year:

- deductions for residential dwellings above their assessable income are a quarantined amount;
- it is used against residential capital gains, then carried forward as a deduction against later rental income;
- exempt: an interest last acquired before 7.30 pm on 12 May 2026, a new residential dwelling (s 26-160), and
  ministerially specified uses.

This was read from the Act as made on the Federal Register of Legislation on 13 November 2026, through a fetch tool
that summarised and transcribed it. Exact wording should be checked against the original.

**Engineering judgement.**

- Quarantining from the start, 2026-27 included, and for any property unless the setting is ticked, is cautious and
  simple. It overstates tax in 2026-27 for any property, and in later years for exempt properties left unticked.
- 90% rent kept, 1.5% running costs and 4% growth are planning defaults, not sourced statistics.

**Age Pension.**

- The Social Security Guide (4.3.8.30) says rental income is assessed largely as for tax, without depreciation; this was
  seen in a search excerpt, and the full page was not read.
- How a rental loss is treated against other income was not confirmed, so the model does not let it reduce assessed
  income.
- Equity as an asset follows the charge rule in Social Security Act s 1121, as in ADR 0052.

**User requirements:** the scope, the defaults, leaving equity out of spending rules, and the reporting when money runs
out.

## Consequences

**New behaviour**

- A negatively geared property costs pay that would have been invested. A positive one adds to saving.
- Without the offset setting, a loss gives no immediate tax benefit.
- A long loan into retirement is paid from investments and accessible super.
- Wealth bands are narrower than they would be with a volatile property value: the property adds no market risk.
- The *Spendable wealth* band appears with a property.

**Not modelled**

- A sale, capital gains tax on it, or using a carried loss against a gain.
- Depreciation, borrowing costs, lumpy repairs and capital works.
- More than one property, joint ownership, change of use, a variable rate, an offset account, refinancing.

**Compatibility**

- Plans without `[investment_property]` read as before. The schema version is unchanged.
- Saved runs from before this change lack the new series, and the app handles their absence.

**Numbering fix:** the saved-run record that shared number 0052 with the home loan is renumbered
[ADR 0053](0053-one-saved-run-per-plan-name.md). The home loan record was committed first, so it keeps 0052.

## Implementation and validation

Code:

- `retirement/ledger.py`: `InvestmentProperty`, `Mortgage.interest_only_years`, the shared `_Loan` state, rent, costs,
  growth, tax, the Age Pension and `spendable`;
- `rules/au/age_pension.py` (`other_income`);
- `retirement/plan.py`;
- `retirement/paths.py`, `retirement/flows.py` and `retirement/real.py`;
- `reporting/palette.py`;
- `ui/inputs.py`, `ui/charts.py`, `ui/outcomes_page.py` and `ui/paths_page.py`.

Methodology: [investment property](../methodology/investment-property.md).

Tests (`tests/test_investment_property.py`) cover:

- cash flows and wealth identities, and flow reconciliation;
- quarantine against offset, and carry-forward into a profit year;
- spending rules on spendable wealth;
- shortfalls;
- interest-only repayments;
- the Age Pension;
- the plan section.

The home loan tests and the full suite pass.
