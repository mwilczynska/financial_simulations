# ADR 0052: a fixed-rate home loan in the daily ledger

Date: 2026-11-13.

Status: accepted; implemented and tested.

## Context

The home appeared only as a homeowner flag for the Age Pension assets test. A person still paying off their home
had to fold repayments into spending. That overstated later spending (repayments are fixed in dollars, while spending
rises with CPI), left the debt out of wealth, and gave no way to choose between paying the loan down and investing.
PLAN.md listed "mortgage repayment/offset choices" as future work.

The user asked for options and chose the simplest one that puts a loan in the ledger (option B): a fixed-rate loan
with required repayments and a setting that splits spare money between extra repayments and investing. They set
aside comparing repayment strategies on shared paths (option C) and a variable rate drawn from history (option D)
for now.

## Alternatives considered

- **Repayments as spending (option A).** Needs no code, but it only fits a loan that ends exactly at retirement. It
  indexes repayments to CPI, leaves the debt out of wealth and cannot model paying the loan off early.
- **A loan with required repayments and a split (option B)** (chosen).
- **B plus compared repayment strategies on shared paths (option C).** This answers "pay down or invest?" directly,
  but it needs B first and more interface work. Deferred.
- **A variable rate from a historical cash-rate series (option D).** This captures rate risk alongside market moves,
  but `financial_datasets` has no interest-rate series. Deferred.
- **Without a redraw.** The first version sent extra repayments straight off the loan with no way back. In a test
  with no cash buffer, every spare dollar went to the loan and monthly spending then fell short, even though net
  wealth was higher. Most Australian variable-rate loans let the borrower redraw extra repayments, so a redraw was
  added.

## Decision

A plan's `[mortgage]` section has `balance` (owed today; 0 means no loan), `interest_rate` (annual, fixed for the
run), `years` (left on the loan) and `extra_share` (0 to 1). A loan needs `person.homeowner = true`.

In the ledger (`Mortgage`, `LedgerScenario.mortgage`):

- **Interest** accrues every calendar day at `rate / 365` on the balance at the previous close. It is charged to the
  balance on the last day of each month.
- **Required repayment.** The fortnightly annuity `B r / (1 - (1 + r)^-n)`, with `r = rate / 26` and
  `n = round(years × 26)`, or `B / n` at a zero rate. It is fixed in dollars and due every 14 days from the first
  payday on or after the start (from the start with no salary). It is paid on the first observation day on or after
  it falls due: first from cash, then from outside sales and accessible super. It is paid before spending and never
  from the redraw. A final instalment is cut to what is owed. Anything that cannot be paid is a shortfall (the same
  `shortfall` flow as unpaid spending, so the path is depleted); the arrears stay on the loan and accrue interest.
- **Extra repayments.** At each observation close, `extra_share` of the money that would buy outside investments pays
  the loan down instead, while anything is owed. That money is the surplus above the buffer, the fixed contribution
  in fixed mode, or all cash above the buffer after retirement. It then flows back to investing.
- **Redraw.** Extra repayments not yet drawn back can be redrawn. When cash cannot meet spending or tax, the redraw is
  used before any investments are sold, and it adds to the loan. Repaying the loan in full closes it and its redraw.
- **Wealth.** The daily `total` is net wealth: assets less the amount owed (`mortgage` column). Market P&L, the
  assets reconciliation and the Age Pension tests use assets. Spending rules, percentage starts, bands and outcomes
  use net wealth.
- **Tax and Age Pension.** Interest on a loan for the home you live in is not deductible, so the loan does not
  affect income tax. The loan does not reduce assessable assets, because the home it is secured on is exempt.

Reporting: `mortgage_interest` is a household outflow ("Mortgage interest"). Principal repaid, net of redraws
(`mortgage_repaid`), is a transfer between assets and the loan, not a change in net wealth. Account flows add a
"Mortgage" account. Path summaries give the interest, the amount owed at the end and the date the loan was repaid.
Mortgage interest counts in the yearly withdrawal rate. The You tab has a *Home loan* card, and charts show the
amount owed below zero and the band only when there is a loan.

## Reasons and evidence

- **User requirement:** the option B scope and a split between the loan and investments.
- **Engineering judgement:** lenders commonly charge interest daily and debit it monthly, and quote fortnightly
  repayments as an annuity. Here the rate is one fixed input, not a product's actual terms.
- **Engineering judgement (redraw):** without a redraw, a person with little spare cash shows false shortfalls. With
  it, extra repayments behave like a redraw facility or an offset account: with a zero market return, paying the loan
  down changes net wealth by exactly the interest saved (tested).
- **Tax:** interest on a loan used to buy or improve the home you live in is a private expense, not deductible, which
  is the general treatment the ATO describes. Investment use of the loan (debt recycling) is out of scope.
- **Age Pension (research finding with a stated limit):** the principal home is exempt from the assets test
  (age-pension.md). Social Security Act 1991 section 1121 lets a charge or encumbrance reduce the value of the asset
  it is secured on, and apportions a liability secured over both assessable and exempt assets. A loan secured only
  on the exempt home therefore does not reduce other assessable assets. That is our reading of the apportionment
  rule. The Social Security Guide pages (4.6.3.10 and 4.6.6.30) could not be fetched on 13 November 2026 (HTTP 403),
  so their wording has not been checked. The model keeps assessed assets unchanged, which is also what it did before.

## Consequences

- A loan that outlasts the salary is paid from investments and accessible super, so a long mortgage into retirement
  shows its cost in wealth and in outcomes.
- With a zero `extra_share` the loan runs to its term and every spare dollar is invested. Comparing `extra_share`
  settings means running the plan more than once. Option C would put both on the same paths.
- **Not modelled:** a variable rate or rate changes, fees, offset accounts beyond the redraw, interest-only periods,
  refinancing, redraw used for anything except spending and tax, paying the balance off from super at retirement, a
  home value, rent, and a loan shared by a couple.
- Plans without a `[mortgage]` section read as before, with no loan. A plan file that contains the section cannot be
  read by an earlier version. The schema version is unchanged, because the section is optional.

## Implementation and validation

Code: `retirement/ledger.py` (`Mortgage`, the daily accrual, the repayment, the extra repayment and the redraw, and a
second reconciliation for the loan), `retirement/plan.py`, `retirement/paths.py`, `retirement/flows.py`,
`retirement/real.py`, `ui/inputs.py`, `ui/charts.py`, `ui/outcomes_page.py`, `ui/paths_page.py` and
`reporting/palette.py`. Methodology: [home loan](../methodology/home-loan.md).

Tests (`tests/test_mortgage.py`) cover:

- the annuity, including a zero rate;
- equal zero-rate instalments, with net wealth equal to assets less the loan;
- daily accrual charged monthly, and the annuity clearing the loan;
- the extra-repayment share;
- the redraw, with interest saved equal to the gain in net wealth;
- missed repayments as shortfalls;
- yearly flows that reconcile with net wealth, and the loan account;
- assets for the Age Pension assets test not reduced by the loan;
- plan validation, the TOML round trip and the inputs the plan builds.

The full suite passes.
