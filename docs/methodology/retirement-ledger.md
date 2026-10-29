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
   less salary sacrifice goes to cash as labour income. SG is 12% of the gross
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
   at annual spending/12, rising by `spending_growth` at each 1 July. Needs
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
10. **Surplus cash.** Cash above `cash_buffer` buys new outside parcels at the
    outside weights.
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
| PAYG withholding | Not modelled; tax settles annually | Simplification: cash timing differs from real pay slips |
| Tax settlement | 31 October after the year | Engineering choice: a self-lodger's due date. Agents and assessment notices give other dates |
| Distribution timing and size | Quarterly, at annual_yield/4 of price | Labelled assumption (estimated income mode) |
| Franking credit ratio | 30% company tax | Assumption; base-rate entities pay 25% |
| Fund realised gains | None | Simplification: overstates net fund returns when funds turn over assets |
| Rebalancing | Optional per account (`outside_rebalance`, `super_rebalance`; ledger default off, planner default annual). On the first return observation of a calendar year, accounts reset to target weights at pre-return values. Outside sales are CGT events labelled `purpose = rebalance`; super switches are untaxed | [ADR 0018](../decisions/0018-planner-annual-rebalancing.md); untaxed super switching overstates fund returns |
| Parcel selection | Oldest first within asset | Engineering choice; specific identification is allowed in law |
| Interest on cash | Nil | Simplification |
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
  Runs stop before Age Pension age (SAPTO is not implemented). A horizon
  ending before 30 June reports the partial year as `unassessed_year`.
- **CGT reform.** On 1 July 2027 each parcel held records its 30 June
  close as the deemed reacquisition value. Later sales split into a deferred
  gain and an indexed post-reform gain. Opening parcels for runs starting
  after the reform must supply that value.
- **Income split.** The income split is an assumption, not a fund's actual tax
  statement. Foreign income and credits, AMIT cost-base adjustments and
  capital-gain distributions are not modelled.
- **People and policies.** One person only. Spending is a fixed nominal
  amount: no guardrails, no spending rules that depend on wealth, and no
  Age Pension.
- **Excess regimes.** Excess contributions, excess transfer balances,
  Division 296 balances, early access and tax debts stop the run by design.

Revision history: 2026-10-28, first implementation.
