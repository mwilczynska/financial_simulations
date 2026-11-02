# ADR 0035: accrue fund tax with each distribution, and report tax owed at the horizon

Date: 2026-11-02.

Status: accepted; implemented and tested. Refines the path classification of
[ADR 0019](0019-retirement-path-results.md).

## Context

The [1 November 2026 retirement calculation review](../reviews/2026-11-01-retirement-calculations/README.md)
found two P1 errors (findings 4 and 6):

- **Finding 4.** Accumulation fund tax was assessed on the whole year's income at 30 June, but collected only
  from units still in accumulation. A balance transferred to pension or withdrawn before 30 June took its
  income tax with it. With $100,000, a 4% yield and a transfer on 1 April, the review found $450 assessed and
  nothing charged. Excess franking credits were likewise lost when no accumulation units remained.
- **Finding 6.** Ending wealth and the funded status ignored tax already incurred: assessments not yet due,
  pending Division 296 and an unassessed closing period. A path that sold everything to fund spending ended
  with $0, an assessed $9,620 October bill, and the status `funded`.

## Alternatives considered

- **Finding 4.**
  1. Carry an unsettled fund-level liability through transfers and withdrawals.
  2. Accrue fund tax on income as it is earned.
  3. Charge the shortfall to the pension account at 30 June.
- **Finding 6.**
  1. Subtract only liabilities due before the horizon.
  2. Report net wealth after every incurred liability, and whether it can be settled.
  3. Liquidate all assets and report after-tax wealth.

## Decision

- **Fund tax.** Accrue it (alternative 2). On each accumulation distribution the fund deducts
  `accumulation_earnings_tax(cash, 0, 0, credits)` and reinvests only the net amount. A negative amount (excess
  franking credits) is reinvested as a credit. At 30 June the year's tax is assessed as before. The remainder
  after the accrued amount, which is the tax on the realised gain on the remaining accumulation units, is
  charged or credited there. The annual record keeps the full assessed amount.
- **Tax owed at the horizon.** Report net wealth (alternative 2). The ledger's `unassessed_year` gains
  `estimated_tax`: the partial year assessed as if it ended on the last day, less withholding. Each path then
  reports three new fields:
  - `Tax owed at end`: assessments not yet due (net of refunds), plus pending Division 296, unpaid tax and the
    estimate, deflated at the end date;
  - `Ending wealth after tax owed`;
  - `Can settle tax owed at end`: whether outside wealth, the pension and accumulation (if accessible at the
    end) cover it.
- **Status.** A path that cannot settle the tax owed is `depleted`. The app's headline ending-wealth metrics
  show wealth after tax owed.

## Reasons and evidence

- **Fund-tax accrual (engineering judgement and industry practice).** Unit-priced funds provide for tax in
  their unit prices as income accrues. Members who switch or leave mid-year therefore bear their share. It is
  also the simplest change: the income component can never become orphaned. The realised-gain component is
  modelled at 30 June on the remaining units only (ADR 0029), so it has no orphan either.
- **Timing (behaviour change).** Tax now leaves the fund each quarter instead of each 30 June. Later
  distributions are paid on a slightly smaller balance; at a 1% quarterly yield the balance falls by a factor
  of 0.9985 a quarter. Existing tests were updated to these compounded amounts.
- **Net wealth (review recommendation).** Tax already incurred is a real claim on the horizon's wealth. It is
  distinct from optional tax on liquidating unsold assets, which is still not deducted. The settle test uses
  money that could pay the bill when it falls due. Preserved, inaccessible super cannot.

## Consequences

- Results differ slightly through the quarterly timing of fund tax. Transfers and withdrawals before 30 June
  now bear their tax.
- Ending wealth after tax owed is lower than gross ending wealth for most paths, mainly because of the final
  year's assessment, which is due after the horizon. The funded share can fall where closing tax cannot be
  settled.
- **Not included:** tax on liquidating unrealised gains; Division 296 and fund gains tax for an unassessed
  partial year; interest charges on unpaid tax. Real funds' daily tax provisioning and actual tax payment
  dates are not modelled.
- The representative path is still chosen by gross ending wealth.

## Implementation and validation

- **Code:**
  - `retirement/ledger.py`: the distribution accrual, the 30 June remainder, `income_year` and
    `estimated_tax`.
  - `retirement/paths.py`: `_summarise`.
  - `ui/app.py`: the headline metrics and the risk-of-ruin explanation.
- **Methodology:** [retirement-ledger.md](../methodology/retirement-ledger.md) and
  [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests in `tests/test_ledger.py`:**
  - `test_fund_tax_accrued_before_a_transfer_to_pension_is_not_lost` covers unfranked and fully franked
    income: the review's case, now about $450 charged.
  - `test_outcomes_report_tax_owed_at_the_horizon_and_whether_it_can_be_settled` covers the review's case, now
    `depleted`, with $9,620 owed, and a settled control.
  - `test_an_unassessed_final_period_estimates_the_tax_already_incurred`.
  - `test_fund_tax_on_accumulation_income_and_pension_franking_refund` is updated for accrual.
- **Other tests:** `tests/test_projection.py::test_a_weekend_30_june_horizon_is_still_assessed`, updated for
  accrual.
