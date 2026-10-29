# Single-person retirement ledger (Stage 2A)

Date: 2026-10-28. Status: implemented and tested against hand calculations,
the stand-alone rule functions and a daily reconciliation identity. It runs
across income years with [projected rule sets](../rules/au-projection.md)
([ADR 0015](../decisions/0015-projected-rules-and-cgt-reform.md)).
Decision: [ADR 0014](../decisions/0014-single-person-ledger-conventions.md).
Rules: [Australian rules](australian-rules.md) and the
[2026-27 register](../rules/au-2026-27.md). Evidence:
[Stage 2A validation](../validation/stage-2a.md).

## Purpose and scope

`run_ledger(path, scenario, rules_by_year)` in
[ledger.py](../../src/financial_simulations/retirement/ledger.py) follows one
Australian resident individual day by day. It tracks:

- outside cash and outside investments held in CGT parcels;
- a taxed super accumulation account and an account-based pension, held as
  fund units;
- tax assessed at each 30 June;
- the transfer balance account, contribution caps and access dates.

The market input is a `MarketPath` in AUD. Companion data are USD, and AUD
conversion has been deferred, so a USD path is rejected. Every day the run
touches must fall in a supplied rule year, or the run stops with
`UnsupportedRule`.

## State and the daily event order

Asset unit prices start at 1. On each day:

0. **Interest.** With `cash_interest = r` (annual effective), outside cash at
   the previous close earns `cash * ((1 + r) ** (1 / 365.25) - 1)` every
   calendar day. It is credited to cash, reported in the daily `interest`
   flow and assessed as interest income. Market P&L excludes it.
1. **Market return.** On an observation day, each price is multiplied by
   (1 + daily total return).
2. **Distributions.** At the last observation of each calendar quarter, each
   asset pays annual_yield/4 of its price per unit, and the price falls by
   the same amount. Outside holders receive cash. The amount is split by the
   asset's franked fraction, with franking credits of franked cash x t/(1 - t)
   for company tax rate t (default 30%). Super holders reinvest within the
   fund, and the fund tracks income and credits for fund tax. Total return is
   unchanged: the distribution only moves value from price to cash.
3. **Payday.** On fortnightly paydays before the retirement date, gross salary
   less salary sacrifice goes to cash as labour income. Salary and sacrifice
   are multiplied by `(1 + annual_growth)^n`, where `n` is the number of whole
   financial years since the opening year (ADR 0024). SG is 12% of the gross
   (qualifying) earnings, stopping at the maximum contribution base. SG plus
   the sacrifice is queued to reach the fund after the configured number of
   business days (default 7).
4. **Contribution receipt.** A concessional contribution counts in the
   financial year the fund receives it. If the year's running total exceeds
   the available cap (the general cap plus any eligible carry-forward), the
   run stops. The fund deducts 15% contributions tax and buys units at the
   super weights.
5. **Non-concessional contributions** are scheduled from outside cash and
   checked against the bring-forward rules.
6. **Pension commencement.** The person needs unrestricted access and must be
   at least 60. The run credits the transfer balance account, moves units pro
   rata from accumulation, and sets the pro-rated minimum. A whole-balance
   transfer (`amount = None`) moves at most the unused transfer balance cap
   and leaves the rest in accumulation. An explicit amount that would exceed
   the cap stops the run, because excess transfer balance tax is not modelled.
7. **Spending** is scheduled on the opening day and on each 1st of the month,
   at annual spending/12, rising by `spending_growth` at each 1 July. From the
   retirement date the base becomes `retirement_spending` when it is given
   (same base year, same growth).
   - **Percentage start.** With `spending_rule.start_rate`, the first
     spending date on or after the retirement date sets retirement spending
     to `start_rate` times total wealth at the previous close, and `r0 =
     start_rate` ([ADR 0025](../decisions/0025-spending-in-todays-dollars-and-percentage-starts.md)).
     The amount then grows at `spending_growth` like any other.

   A `spending_rule` other than `fixed` then reviews spending each 1 July
   from retirement ([ADR 0023](../decisions/0023-retirement-spending-rules.md)).
   The withdrawal rate is the year's planned spending divided by total
   wealth at the previous close. Without a percentage start, the first
   review records the starting rate `r0`.
   - **Guyton–Klinger.** After a year with a negative market return, and
     with the rate above `r0`, that year's growth step is skipped. Then
     spending is cut by `step` if the rate is above `r0 * (1 + band)`, or
     raised by `step` if it is below `r0 * (1 - band)`. Defaults are
     `band = 20%` and `step = 10%`.
   - **Vanguard.** The target is `r0` times wealth. The change from last
     year's amount, after the growth step, is limited to `+ceiling` and
     `-floor`. Defaults are 5% and 2.5%.
   - **Percent of wealth.** Spending is `r0` times wealth at each review.
   - **Bounds.** `maximum` caps every rule's amount and `minimum` floors it
     (the minimum wins if they cross). Both grow at `bound_growth` (the
     planner passes CPI), or at `spending_growth` when it is not given.

   Spending scheduled from that 1 July uses the new amount. Each review is
   logged as a `spending_rule` event with its reason. The year's
   `annual` record carries `spending_rule_amount` and `spending_rule_rate`. Needs
   are paid on the first observation day on or after their scheduled date,
   using this order:
   1. outside cash;
   2. outside sales, proportional to value across assets and oldest parcels
      first within each asset, realising a dated CGT event per parcel;
   3. accumulation lump sums, once accessible (tax free at 60 or over);
   4. extra account-based pension payments.

   Whatever remains is recorded as a shortfall. Super that is still preserved
   never pays spending, so a bridge shortfall shows up even when total wealth
   is positive.
8. **Tax settlements** due on or before the day are paid through the same
   order. Refunds go to cash. When every account is exhausted, the unpaid
   part is recorded in the daily `tax_unpaid` flow and
   `outstanding["unpaid_tax"]`, and the run continues. Payment plans and the
   general interest charge are not modelled. Before 2026-10-28 this case
   stopped the run, which removed the worst market paths from planner
   results.
9. **Pension minimum instalments.** On the last observation of each month,
   (minimum − paid so far) / months remaining in the year goes to cash.
10. **New outside investment.** With `outside_contribution_per_payday = None`
    (surplus mode), all cash above `cash_buffer` buys new outside parcels at the
    outside weights. With an amount (fixed mode), each payday schedules that
    amount, grown by `(1 + outside_contribution_growth) ** n` after `n` whole
    financial years. At the observation close the ledger invests the lesser
    of the scheduled amount and the cash above the buffer. An amount that
    cannot be met is not carried forward. Other leftover cash stays in cash.
    With `stop_investing_at_retirement`, no new money is invested on or after
    the retirement date in either mode. Unspent pension payments or lump sums
    then stay in cash, which earns no interest.
    [ADR 0020](../decisions/0020-outside-contributions-stop-at-retirement.md)
    covers this convention.
11. **30 June** (the financial year's last day):
    - Assess the year's income tax with `assess`, using labour income,
      franked and unfranked distributions, franking credits, the year's CGT
      events, brought-forward losses, salary sacrifice as reportable employer
      super, and concessional contributions as low-tax contributions.
    - Schedule the net tax plus Division 293 tax for settlement (default
      31 October).
    - Charge accumulation fund tax: 15% x (income + credits) − credits,
      selling units or crediting them. Credit retirement-phase franking
      credits to the pension.
    - Update unused concessional cap amounts and the TSB at 30 June. A TSB
      above the Division 296 threshold stops the run.
    - Check that the pension minimum was met, unless the pension is
      exhausted.

The opening value plus market P&L, cash salary and employer contributions,
less contributions tax, spending paid, tax paid and fund tax, must equal
total wealth at the close of every calendar day (`rtol=1e-11, atol=1e-6`).
Otherwise the run raises `ArithmeticError`. Distributions, purchases, sales,
pension payments, lump sums and non-concessional contributions are internal
transfers between the person's accounts.

## Defaults and their status

| Convention | Default | Status |
| --- | --- | --- |
| Pay frequency | Fortnightly from `first_payday` | Engineering choice |
| SG and sacrifice arrival | 7 business days after payday (weekdays only) | The legal deadline, ignoring public holidays; actual employer timing may be earlier |
| PAYG withholding | Optional `payg_withholding` (ledger default off; planner on). In each financial year every payday withholds 1/26 of `assess` applied to a full year's salary less sacrifice (SG and sacrifice as low-tax contributions; cover as entered). The 30 June assessment's liability is net tax plus Division 293 less the year's withholding, so a negative balance is refunded at settlement | [ADR 0022](../decisions/0022-payg-withholding.md). An estimate, not the ATO withholding schedules; investment income and part-year work are settled at assessment |
| Tax settlement | 31 October after the year | Engineering choice: a self-lodger's due date. Agents and assessment notices give other dates |
| Distribution timing and size | Quarterly, at annual_yield/4 of price | Labelled assumption (estimated income mode) |
| Franking credit ratio | 30% company tax | Assumption; base-rate entities pay 25% |
| Fund realised gains | None | Simplification: overstates net fund returns when funds turn over assets |
| Rebalancing | Optional per account (`outside_rebalance`, `super_rebalance`; ledger default off, planner default annual). On the first return observation of a calendar year, accounts reset to target weights at pre-return values. Outside sales are CGT events labelled `purpose = rebalance`; super switches are untaxed | [ADR 0018](../decisions/0018-planner-annual-rebalancing.md); untaxed super switching overstates fund returns |
| Parcel selection | Oldest first within asset | Engineering choice; specific identification is allowed in law |
| Interest on cash | `cash_interest` (ledger default 0; planner default 3% a year, an assumption), credited daily, taxable | [ADR 0021](../decisions/0021-cash-interest-and-withdrawal-rates.md); no bank interest calendar, deposit rate curve or term deposits |
| Outside contributions | Surplus sweep (ledger default) or a fixed per-payday amount, optionally indexed each 1 July; the planner stops new investing at retirement | User requirement, [ADR 0020](../decisions/0020-outside-contributions-stop-at-retirement.md) |
| Default weights | Opening holdings' proportions; error if none | Prevents silently investing in an arbitrary asset |
| Opening TSB at the prior 30 June | Opening super value unless supplied | Input; supply the true value for cap tests |

## Outputs

`LedgerResult` contains:

- `daily`: balances by account, flows, accessibility, pending contributions
  and tax liabilities, one row per calendar day;
- `events`: every salary, contribution, distribution, buy, sale (with
  parcel, gain and acquisition date), spending payment, shortfall, pension
  payment, lump sum, assessment, settlement and fund-tax record;
- `annual`: the full `TaxAssessment`, contributions against the cap,
  non-concessional total, fund tax, pension minimum and amount paid, TSB,
  spending, shortfall, unused cap history and transfer balance;
- `outstanding`: tax liabilities, unpaid tax debts, pending contributions,
  unpaid scheduled spending, losses carried forward and unused caps at the
  horizon.

`write_ledger_report` writes `daily.csv`, `events.csv`, `annual.json` (with
the rule-set hash and assumptions) and `ledger.png` directly from Python.

## Limitations

- **Horizon.** Years after 2026-27 depend on an assumed CPI and wage growth.
  A horizon ending before 30 June reports the partial year as
  `unassessed_year`.
- **Age Pension.** With `age_pension=True` (the planner's setting), the
  single Age Pension is paid fortnightly from a fortnight after Age Pension
  age, means-tested on the previous close. SAPTO applies from the year Age
  Pension age is reached ([age-pension.md](age-pension.md)). Without it, a
  run reaching Age Pension age stops with `UnsupportedRule`.
- **CGT reform.** On 1 July 2027 each parcel held records its 30 June
  close as the deemed reacquisition value. Later sales split into a deferred
  gain and an indexed post-reform gain. Opening parcels for runs starting
  after the reform must supply that value.
- **Income split.** The income split is an assumption, not a fund's actual tax
  statement. Foreign income and credits, AMIT cost-base adjustments and
  capital-gain distributions are not modelled.
- **People and policies.** One person only. No Age Pension.
- **Excess regimes.** Excess contributions, excess transfer balances,
  Division 296 balances, early access and tax debts stop the run by design.

Revision history: 2026-10-28, first implementation.
