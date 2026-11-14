# Home loan

Decision record: [ADR 0052](../decisions/0052-home-loan-in-the-ledger.md). Code: `Mortgage` and `run_ledger` in
`retirement/ledger.py`; the `[mortgage]` plan section in `retirement/plan.py`.

## Purpose and scope

This models a principal-and-interest loan on the home the person lives in, still owed at the start of a plan. It
has three parts:

- required repayments that come before spending and saving;
- a choice of how much spare money pays the loan down instead of being invested;
- the loan's effect on net wealth.

One borrower, one loan, and one fixed rate for the whole run.

## Inputs and provenance

| Field | Meaning | Default |
| --- | --- | --- |
| `mortgage.balance` | Amount owed on the start date, AUD. 0 means no loan | 0 |
| `mortgage.interest_rate` | Annual rate, fixed for the run (an assumption, not a lender's quote) | 6% |
| `mortgage.years` | Years left on the loan; sets the required repayment | 25 |
| `mortgage.extra_share` | Share of money that would be invested outside super that pays the loan down instead, 0 to 1 | 0 |

All values are user inputs. A loan needs `person.homeowner = true`. `spending.annual` should exclude repayments.

## Equations and conventions

The required fortnightly repayment, for balance `B`, rate `i`, `r = i / 26` and `n = round(years × 26)`:

```
P = B r / (1 − (1 + r)^−n)        (P = B / n when i = 0)
```

`P` is fixed in nominal dollars. It is due every 14 days, from the first payday on or after the start, or from the
start when there is no salary.

On each calendar day, before anything else:

```
accrued += balance × i / 365
```

On a month's last day, `balance += accrued` and `accrued = 0`. A repayment reduces `accrued` first, then `balance`.
The amount owed is `balance + accrued`. It is the daily `mortgage` column, in nominal dollars, deflated like other
balances in today's-dollar views.

Net wealth:

```
total = cash + outside investments + accumulation + pension − owed
```

The **largest fall in wealth** is not measured on this total. A plan whose loan exceeds its savings starts with
`total` below zero, and a fall from a peak near zero is not a percentage of anything. It is measured on wealth
before loans, `A = total + owed` (plus any investment loan owed):

```
largest fall = min over days d of  A[d] / max(A[s] for s <= d) − 1
```

Days before the first positive high are skipped. Without a loan `A` is `total`
([ADR 0060](../decisions/0060-largest-fall-in-wealth-before-loans.md)).

## Algorithm

Each day in the ledger (see the event order in [retirement-ledger.md](retirement-ledger.md)):

1. **Interest** accrues, as above.
2. **Repayment due.** On a repayment day while anything is owed, `P` is added to the amount due.
3. **Required repayment.** On the first observation day on or after it falls due, the amount due, capped at what is
   owed, is paid before spending. It goes through the needs waterfall: cash, outside sales, then accessible super.
   It is never paid from the redraw. An unpaid part is recorded as a `shortfall` (event purpose `mortgage`) and stays
   on the loan. The next repayment is the normal amount, with no catch-up.
4. **Spending and tax** are paid as before, with one more source after cash. **Redraw** is the extra repayments not
   yet drawn back. It is drawn before outside investments are sold, and what is drawn is added to the loan.
5. **Extra repayment.** At the observation close the ledger works out the amount it would invest. While anything is
   owed, `min(amount × extra_share, owed)` pays the loan down instead and joins the redraw. The rest is invested.
   After the loan is repaid, everything is invested again.
6. **Month end** charges the accrued interest to the balance.
7. **Reconciliation.** Assets reconcile as before, less principal repaid net of redraws. The loan reconciles
   separately (`owed = opening owed + interest − repaid`). Both checks use the existing tolerance.

Repaying the loan in full closes it and its redraw.

## Tax and Age Pension

- Interest on a loan for the home you live in is a private expense, so the loan has no income tax effect.
- **Age Pension.** The home is exempt, and the loan does not reduce assessable assets: the means test uses assets,
  not net wealth. This rests on how section 1121 of the Social Security Act 1991 treats a charge on an exempt asset.
  The Social Security Guide wording was not checked (see ADR 0052).

## Reporting

- **Money in and out.** "Mortgage interest" is an outflow: it lowers net wealth. Principal repaid moves money from
  assets to the loan, so net wealth does not change.
- **Account flows.** A "Mortgage" account shows "Interest charged" and "Repaid, net of redraws".
- **Charts.** Balance charts draw the amount owed below zero, only on paths that owe something. The Outcomes bands
  offer "Mortgage owed" when a loan exists.
- **Path outcomes.** They add `Mortgage interest`, `Mortgage owed at end` and `Mortgage paid off` (the first day
  nothing is owed). The yearly rows add `Mortgage interest`.
- **Withdrawal rate.** It includes mortgage interest as a draw on wealth. It does not include principal.
- **You tab.** The *Home loan* card shows the required repayment. *Where your pay goes* deducts it, and the extra
  repayments, from the first-year estimate.

## Home value and running costs

ADR 0055. Optional: `[home]` `value` (0 means not modelled), `running_costs` (1% of value a year, an assumption) and
`growth` (4% a year, an assumption).

With a value:

- **Running costs:** on the first of each month `running_costs × value / 12` falls due. It is paid on an observation
  day before spending, through the needs waterfall, and may use the redraw. Spending rules never cut it.
- **Value:** it grows by `(1 + growth)^(1/12)` on each month's last day (daily `home_value` column).
- **Wealth:** the home is in neither `total` nor `spendable` wealth. It is shown as the optional *Home value* band.
- **Age Pension:** the home stays exempt.
- **Tax:** none; the costs are private.

`spending.annual` should then exclude rates, insurance and repairs.

## Rent paid

ADR 0055. A person who does not own the home they live in can enter `person.weekly_rent`. Each month
`weekly_rent × 52 / 12`, rising with CPI each 1 July, is paid before spending, and spending rules never cut it.
`spending.annual` should then exclude it. It stops when the person moves into their investment property
([investment-property.md](investment-property.md)). Rent Assistance is not modelled.

## Examples

**Annuity.** $500,000 at 6% over 25 years: `r = 0.06 / 26`, `n = 650`, so `P = $1,485.99` a fortnight
($38,635.70 a year).

**Paying down or investing** (13 November 2026; one year from 1 July 2026; zero market return; salary $150,000;
spending $40,000; no cash buffer; $90,000 owed at 6% over 25 years):

| `extra_share` | Owed at 30 June | Interest | Net wealth at 30 June |
| --- | --- | --- | --- |
| 0 | $88,386.16 | $5,340.58 | $33,292.75 |
| 0.5 | $52,382.85 | $4,193.39 | $34,439.94 |
| 1 | $0 | $2,076.47 | $36,556.86 |

With no market return, each row's gain in net wealth over the first equals its interest saved, to the cent:

- 0.5: $1,147.19 more wealth, $1,147.19 less interest;
- 1: $3,264.11 more wealth, $3,264.11 less interest.

With a positive return, paying down gives up the after-tax return the money would have earned. Running the plan at
different `extra_share` values compares the two.

## Validation

`tests/test_mortgage.py`:

- the annuity, including a zero rate;
- equal zero-rate instalments;
- net wealth equals assets less the loan;
- one day's interest, and the annuity clearing the loan within a few dollars;
- the extra-repayment share, with investing resuming after the loan is repaid;
- the redraw: no added shortfall, and interest saved equal to the gain in net wealth;
- a missed repayment as a shortfall, with the balance growing;
- yearly flows reconciling with net wealth, and the loan account;
- Age Pension assets not reduced by the loan;
- plan validation, the TOML round trip and the ledger inputs.

## Limitations

- **Interest rate.** One fixed rate for the whole run: no rate changes, no link to market paths and no fees.
- **Compounding.** Daily accrual charged monthly does not exactly match the fortnightly annuity, so the final
  instalment is a few dollars smaller or larger. The `years` input only sets `P`.
- **Redraw.** It pays only spending and tax. There is no offset account, interest-only period, refinancing or
  repayment holiday.
- **Not modelled:** paying the loan off from super at retirement; a home value, sale or downsizing; rent; a loan
  shared by a couple; debt recycling or deductible investment debt.
- **Comparing settings.** `extra_share` settings are compared only by running the plan more than once. Option C in
  ADR 0052 would compare them on shared paths.

## References

- Social Security Act 1991 (Cth), s 1121 (effect of a charge or encumbrance on the value of assets).
- Department of Social Services, *Social Security Guide*, 4.6.3 (assessing the principal home). Not re-read for this
  record; see ADR 0052.

Revision history: 2026-11-13, first implementation; home value, running costs and rent paid (ADR 0055).
