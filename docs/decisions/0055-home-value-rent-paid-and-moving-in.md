# ADR 0055: the home's value and running costs, rent paid, and moving into an investment property

Date: 2026-11-13.

Status: accepted; implemented and tested.

## Context

[ADR 0052](0052-home-loan-in-the-ledger.md) modelled a home loan, and [ADR 0054](0054-investment-property-in-the-ledger.md)
an investment property. Neither gave the home a value. A homeowner's rates, insurance and repairs sat inside
`spending.annual`. That had two effects:

- these costs rose with CPI instead of with the home's value;
- a spending rule (Guyton–Klinger cuts, Vanguard floors) cut them along with discretionary spending.

A renter's rent was also inside spending, so spending rules cut it too.

Reviewing a saved plan, the user found two problems with "I own my home":

- the tick box was on the Retirement tab, away from the home loan;
- its wording was unclear when the person also owns a rental.

The user then asked for:

- an optional home value with running costs;
- the recommended treatment of it: kept out of total wealth and shown alongside;
- a renamed tick box;
- an option for a person who only owns an investment property to move into it on a chosen date.

## Alternatives considered

**Home value**

- **Required.** Rejected: most people's spending already includes home costs, and a required split invites counting
  them twice.
- **Optional (chosen).**

**The home in total wealth**

- **Include it, so total wealth is net worth.** Consistent with the investment property, but every homeowner's ending
  wealth would jump and be driven mostly by house prices.
- **Exclude it and show it separately (chosen).**

**Rent paid**

- **Leave it inside spending.** Rejected: spending rules would cut it, and it cannot stop on a move-in date.
- **A separate weekly amount, paid before spending (chosen).**

**Moving in**

- **Keep the property in total wealth after the move (chosen in the revision below).** First rejected as
  inconsistent with an entered home being in no wealth total.
- **Take the property out of total wealth on the move, as a flow (first implementation).** Superseded the same day:
  the user saw the whole value drawn as a one-year loss in money in and out, and its wealth layer vanish.
- **Leave the tenants' rent and the loan's deductibility unchanged.** Rejected: both change in law when the property
  becomes the main residence.
- **Make it the home, following every home rule (chosen).**

## Decision

**Your home card** (You tab) holds the tick box, renamed "I own the home I live in". The Retirement tab now only says
which assets limits apply.

**When ticked:**

- **Home value** (`[home]`, optional; 0 means not modelled).
  - Running costs default to 1% of the value a year, and value growth to 4%, applied monthly.
  - Costs fall due on the first of each month and are paid before spending (event `home_costs`). They may use the home
    loan redraw.
- **The home loan**, as before.

**When not ticked:**

- **Rent you pay**, weekly (`person.weekly_rent`): paid monthly before spending, rising with CPI each 1 July (event
  `rent_paid`).
- A home loan and a home value are not allowed, and Rent Assistance is not modelled.

**Moving in** (`investment_property.move_in_date`). Only for a person who does not own the home they live in, with no
home loan or home value, on a date after the start. On that day:

- **Rent stops:** the tenants' rent and the rent the person pays.
- **The loan becomes the home loan.** It keeps its repayment schedule, and its interest is now `mortgage_interest`,
  not deductible.
- **Running costs** switch to `home.running_costs` of the value, and the value keeps growing at the property's rate as
  `home_value`.
- **Wealth:** the move is a transfer, not a flow. The home stays in total wealth (daily `home_in_wealth`) and is drawn
  as *Home you moved into* on the wealth charts. Its later growth is the *Property value growth* flow. The loan moves
  from investment loan to home loan, so total wealth does not change on the day, but spendable wealth now deducts it,
  as for any home loan. A home entered as `[home]` remains in no wealth total.
- **Age Pension:** the property becomes an exempt home, and the homeowner limits apply.
- **Tax:** rental income and deductions stop. A quarantined loss carried forward stays unused.

**Reporting**

- Home value is an optional band.
- *Home costs* and *Rent paid* are household flows. They are folded with *Mortgage interest* into one *Home* flow in
  charts. The move itself is not a flow.
- Path outcomes add home costs, home value at the end, rent paid and the move-in date.
- Withdrawal rates count home costs and rent paid as draws.

## Reasons and evidence

**User requirements:** an optional home value with costs, the home kept out of total wealth, the renamed tick box, and
the move-in option.

**Engineering judgement:**

- Costs that track value, and payment before spending, put non-discretionary housing outside the spending rules.
- 1% of value a year for an owner-occupied home is a planning default, not a sourced figure. It is lower than the 1.5%
  for a rental, which carries landlord insurance, strata and management.

**Tax and Age Pension**

- From the move, interest is no longer for producing assessable income, so it is not deductible.
- The principal home is exempt from the assets test, and a homeowner's limits apply (age-pension.md).
- Main-residence CGT apportionment on a later sale is out of scope, because nothing is sold.

## Consequences

**New behaviour**

- **Housing costs are protected.** Renters and homeowners who enter these amounts have their housing costs shielded
  from spending-rule cuts.
- **Totals change for those who enter them.** Total and spendable wealth are unchanged for plans that do not use the
  new fields.
- **The move-in year's money in and out shows a large negative *Investment property* flow:** the value leaving total
  wealth.

**Not modelled**

- Rent Assistance.
- Moving out of a home.
- More than one move, and moving into a property for a homeowner (who would need to sell).
- Using a quarantined loss after the move.

**Compatibility.** Plans without `[home]`, `weekly_rent` or `move_in_date` read as before; the schema version is
unchanged.

## Revision (2026-11-13)

The first implementation took the property's value out of total wealth on the move day, through a `property_moved_in`
flow. The user saw it drawn as a loss of about $1.6M in that year's money in and out, and its wealth layer vanished.
They asked for the move to be a transfer and for the home's value to stay on the wealth graph. The home you move into
now stays in total wealth.

## Implementation and validation

Code:

- `retirement/ledger.py`: `Home`, `InvestmentProperty.move_in` and `home_running_costs`, `LedgerScenario.home`,
  `rent_paid_weekly` and `rent_paid_growth`, and the move-in step;
- `retirement/plan.py`;
- `retirement/flows.py`, `retirement/paths.py` and `retirement/real.py`;
- `reporting/palette.py`;
- `ui/inputs.py`.

Methodology: [home loan](../methodology/home-loan.md) (home value, rent paid) and
[investment property](../methodology/investment-property.md) (moving in).

Tests (`tests/test_home.py`) cover:

- home costs and value outside total wealth;
- monthly rent paid, rising each July;
- the move-in switch of rent, loan, value and costs, with money in and out reconciling;
- the Age Pension before and after moving in;
- plan validation, the TOML round trip and the inputs the plan builds.

The full suite passes.
