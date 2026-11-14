# ADR 0060: the largest fall in wealth is measured before loans

Date: 2026-11-14.

Status: accepted; implemented and tested. Changes the *Largest fall in wealth* measure for plans with a home loan
or an investment loan ([ADR 0052](0052-home-loan-in-the-ledger.md),
[ADR 0054](0054-investment-property-in-the-ledger.md)); plans without a loan are unaffected.

## Context

**User requirement:** fix the *Largest fall in wealth* figure, which read -1605.9% on a plan with a home loan.

**Measured** on 14 November 2026, on an invented plan: a 30-year-old with $210,000 of cash, investments and super
and a $600,000 home loan. The measure was

```
min over days d of  W[d] / max(W[s] for s <= d) − 1
```

on total wealth `W`, which is net of the loan. `W` started at about -$397,000 and rose through zero in the plan's
early years, so for a time its previous high was a small positive number. On the path nearest median ending wealth
a fall measured against such a high came to -1605.9%. The path ended with $6.0m and never missed a payment.

A percentage fall needs a positive base that is large compared with the fall. Net wealth near zero is not one.

## Alternatives

| Alternative | Why not |
| --- | --- |
| Cap the fall at -100% | Any dip below zero after a small positive high reads -100%, "lost everything", on a path that did not. |
| Skip days until total wealth is clearly positive | Needs an arbitrary threshold, and ignores the years in which a borrower's investments are most exposed. |
| Report the fall in dollars | Always defined, but cannot be compared across paths or plans of different size, and the tile, the table column and the Outcomes median are all percentages. |
| Measure the fall on wealth before loans | Chosen. |

## Decision

`paths.largest_fall(daily)` measures the fall on wealth before loans:

```
A[d] = total[d] + home loan owed[d] + investment loan owed[d]
largest fall = min over days d of  A[d] / max(A[s] for s <= d) − 1
```

in today's dollars. Days before the first positive high of `A` are skipped, and a path that only rises reports 0.

The path outcome `Largest fall in wealth`, the single-path tile on the Paths page and the Outcomes page's median
all use this function. The name is unchanged; the help texts and the Method page say that it is measured before
subtracting loans.

## Reasons and evidence

- **Engineering judgement:** the choice among the alternatives. `A` is never negative, so the measure stays
  between -100% and 0. It answers the question the tile is there for: how far the money you hold fell from its
  high, through markets and spending together.
- Without a loan `A` equals total wealth, so every existing result for such a plan is unchanged.
- Repaying principal moves money from an account to the loan. It lowers `A` and leaves total wealth unchanged.
  Required repayments come from pay, so in practice this appears only when retirement spending includes
  repayments. It is a real reduction in the money held, and is small beside the falls the measure reports.

## Consequences

- For a plan with a loan the figure is smaller in size than a fall of net wealth would be, because the base
  includes money that is owed. Net wealth by date remains in the wealth charts and the yearly tables.
- An investment property's value is part of `A`. It grows at a fixed rate, so it steadies the measure.
- Saved results made before this change keep the old figure in their outcome table until the plan is run again;
  the single-path tile is recomputed from the daily ledger and shows the new one.

## Implementation and validation

- **Code:** `retirement/paths.py` (`largest_fall`), `ui/paths_page.py`, `ui/outcomes_page.py`, `ui/method_page.py`.
- **Test:** `tests/test_mortgage.py::test_largest_fall_in_wealth_is_measured_before_loans` checks a hand-worked
  series in which net wealth crosses zero, the no-loan case and a path that only rises.
- **Methodology:** [home loan](../methodology/home-loan.md), [plan and app](../methodology/plan-and-app.md).
- **Browser check:** the plan above was re-run. The path nearest median ending wealth shows -59.9% where it showed
  -1605.9%; its wealth chart peaks near $12.5m in the 2070s and falls to about $5m by 2085. The Outcomes page's
  median largest fall across the 100 paths is -54.4%.
