# ADR 0030: reinvest surplus cash in retirement

Date: 2026-10-30. Status: accepted; implemented and locally validated.
Supersedes the stop on all new investing at retirement in
[ADR 0020](0020-outside-contributions-stop-at-retirement.md). Its contribution
modes stand.

## Context

Under ADR 0020 the ledger made no new outside investment on or after the
retirement date. After retirement, money arriving in cash stayed there:
- pension payments (the legislated minimum, which rises with age);
- distributions from outside investments;
- interest, the Age Pension and tax refunds.

Spending and tax are paid from cash first, and outside parcels are sold only
when cash runs short. So on paths where the pension minimum plus income
exceeded spending, cash grew for decades. On one path of the user's private
plan, cash reached about twenty times its level at retirement within 27
years. It earned only the cash interest rate, taxed as ordinary income. ADR 0020 noted this drag and left reinvestment unimplemented.

The user asked for reinvesting surplus cash to be the default, without an
option, and for the change to be logged in the methodology documents.

## Alternatives considered

1. Keep cash after retirement (ADR 0020). This is simple, but cash grows
   without limit on strong paths.
2. Add an option to reinvest. The user declined an option.
3. Reinvest all cash above the buffer from the retirement date, always.
4. Reinvest only above a larger retirement buffer, for example a year of
   spending. This needs a new input and a sizing rule.

## Decision

Choose 3. At each observation close on or after the retirement date, all
outside cash above `cash_buffer` buys new outside parcels at the outside
weights. This happens in both saving modes and in place of fixed
contributions, which end at retirement because salary does. The ledger field
`stop_investing_at_retirement` is removed and the plan has no setting.
Before retirement nothing changes.

## Reasons and evidence

Reinvesting by default and having no option are **user requirements**.
Reusing the existing cash buffer as the retirement float is an
**engineering choice**. Spending and tax are still paid from cash first, so
the buffer limits how often reinvested money is sold back.

Evidence: the user's private plan, comparing the committed ledger with this
change on the same 300 market paths and the same seed. Its balances are not
recorded here, so results are relative, in today's dollars. The outside
portfolio is the default 3x and 2x leveraged mix with annual rebalancing,
and spending follows Guyton-Klinger.

| Measure | Reinvested relative to cash kept (ADR 0020) |
| --- | --- |
| Median of each path's peak retired cash | about 70% lower |
| Ending wealth, 10th percentile | +7% |
| Ending wealth, median | −0.5% |
| Ending wealth, 90th percentile | −0.9% |
| Median total retired spending | unchanged |
| Paths with a shortfall | none in either |

Per path, reinvesting changed ending wealth by a median of −0.9% (10th
percentile −4.4%, 90th +0.8%). It was higher in 16% of paths.

The result is close to neutral, and slightly negative at the median.
Decomposing 40 paths shows why. Over retirement, the median path:
- sold about 13% more outside parcels for spending or tax, an amount larger
  than all the cash reinvested;
- realised about 11% more gains on those sales;
- paid slightly more personal tax (+0.6%);
- earned less cash interest.

Reinvested cash is later sold again to pay spending and tax, especially
large tax bills. Cash would have paid those without a sale. Sales take the
oldest parcels first, so each one realises old, large gains rather than the
small gain on the newly bought parcel. With this volatile portfolio the
extra realised CGT roughly offsets the higher expected return over cash.

This is a finding for one plan, not a general result. Plans with less
volatile portfolios, smaller tax bills or a larger buffer will differ.

## Consequences

- Cash no longer piles up after retirement. It stays near the buffer, so
  outside wealth is invested as the user expects.
- On this plan the effect on wealth is small: the 10th percentile improves,
  while the median and upper tail are slightly lower.
- The churn comes from the parcel order. Selling the newest or
  highest-cost parcels first for spending (specific identification) would
  reduce the extra gains. [ADR 0031](0031-sell-lowest-taxable-gain-parcels-first.md)
  implements this for every outside sale.
- Reinvested amounts appear in the planner's "added to outside investments"
  line after retirement, and the app captions say so.

## Implementation and validation

- `retirement/ledger.py`: new investing at the observation close sweeps all
  cash above the buffer once the retirement date is reached;
  `LedgerScenario.stop_investing_at_retirement` is removed.
- `retirement/plan.py` no longer sets that field. App captions and
  `default_plan.toml` describe the reinvestment.
- `tests/test_ledger.py::test_fixed_outside_contributions_then_surplus_cash_reinvested_from_retirement`
  checks the following, with a funded $5k buffer and retirement on
  1 January 2027:
  - fixed contributions are invested exactly on paydays before
    retirement;
  - pay left in cash is reinvested on the retirement date down to the
    buffer;
  - the buffer remains in cash.
- The full suite passed (216 tests).
- The comparison above used scratch scripts outside the repository against
  a private plan, so only its summary figures are recorded.
- Methodology: [retirement ledger](../methodology/retirement-ledger.md),
  step 10; [plan and app](../methodology/plan-and-app.md).
