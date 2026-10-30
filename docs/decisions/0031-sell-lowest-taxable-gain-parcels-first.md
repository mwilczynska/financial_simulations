# ADR 0031: sell the lowest-taxable-gain parcels first

Date: 2026-10-30. Status: accepted; implemented and locally validated.
Replaces the oldest-first parcel order used since
[ADR 0014](0014-single-person-ledger-conventions.md) and in rebalancing
([ADR 0018](0018-planner-annual-rebalancing.md)).

## Context

Every outside sale sold the oldest parcels of each asset first. With
rising prices, the oldest parcels usually have the lowest cost base, so each
sale realised the largest available gain.
[ADR 0030](0030-reinvest-surplus-cash-in-retirement.md) found this made
reinvesting surplus cash after retirement roughly neutral. Reinvested cash
was later sold again, and those sales realised old, large gains rather than
the small gain on the parcel just bought. ADR 0030 named selling the newest
or highest-cost parcels first as a follow-up, and the user asked for it to
be implemented.

## Alternatives considered

1. Keep oldest-first (first in, first out). It is simple and the common
   default, but it maximises realised gains while prices rise.
2. Newest first (last in, first out). It is simple, but a recent parcel can
   carry a larger taxable gain than an old one: it may not yet be held 12
   months, so it gets no discount, and a parcel bought low can be newer than
   one bought high.
3. Highest cost first. This ignores the discount, the 12-month test and the
   1 July 2027 reform split.
4. Lowest taxable gain per dollar of proceeds first, computed with the
   ledger's own CGT rules. This generalises 3.
5. Plan sales across years, for example to hold losses back for later. This
   needs future prices and incomes, so it is not a rule the ledger can apply
   day by day.

## Decision

Choose 4, for every outside sale: spending, tax and rebalancing alike.
Within each asset, parcels are sold in ascending order of

    k = taxable gain if the whole parcel were sold today / its value today

with ties broken by acquisition date. The taxable gain uses the same events
as the sale:
- before 1 July 2027, `value − cost base`;
- from that date, the deferred gain plus the indexed post-reform gain.

A gain eligible for the discount counts at `1 − cgt_discount_individual`.
Losses have negative k and are realised first. There is no option. The
proportional split of a withdrawal across assets is unchanged.

## Reasons and evidence

Implementing the follow-up is a **user requirement**. The ordering rule and
applying it to rebalancing as well are **engineering choices**.

**Source fact.** The ATO page
[Keeping records of shares and units](https://www.ato.gov.au/individuals-and-families/investments-and-assets/capital-gains-tax/shares-and-similar-investments/keeping-records-of-shares-and-units)
(last updated 22 June 2026, viewed 30 October 2026) says each parcel is a
separate CGT asset. Where records such as CHESS or issuer-sponsored
statements identify them, an investor can select which shares were sold. Its
example shows an investor selling a later, higher-cost parcel to claim a
loss. The page does not prescribe an order. The model assumes the records
exist and that every sale is identified this way.

**Effect on the user's private plan.** The comparison used 300 market paths
with the same seed, in today's dollars, against the oldest-first ledger with
ADR 0030 in place. Its balances are not recorded here, so results are
relative.

| Measure | All sales (chosen) | Withdrawals only (for comparison) |
| --- | --- | --- |
| Ending wealth per path, median ratio | 1.25 | 1.09 |
| Ending wealth per path, 10th–90th percentile ratio | 1.05–1.59 | 1.00–1.23 |
| Paths with higher ending wealth | 97% | 90% |
| Wealth at retirement, median ratio | 1.03 | 1.01 |
| Total retired spending, median | +14% | +4% |
| Gains realised by withdrawals, median | −57% | −85% |
| Lifetime personal tax, median ratio | 1.02 | 1.01 |
| Paths with a shortfall | none | none |

Lifetime tax is slightly higher, not lower, because the rule mostly defers
tax. Deferred gains stay invested and compound, so wealth grows. With
Guyton-Klinger guardrails, higher wealth raises spending, which is in turn
taxed and realised later. The deferral is the benefit: lower realised gains
in each early sale leave more capital working.

Applying the rule to rebalancing as well as withdrawals adds most of the
gain. Rebalancing sells far more than spending does in this plan.

**Performance.** Ranking every parcel at each sale costs about 0.4 seconds
over a 50-year path, a ledger run going from about 0.9 to about 1.3
seconds. The key is computed with plain arithmetic rather than by building
CGT events. A scratch check against `parcel_gains` matched within 1e-9 on
525,388 parcel rankings across six paths.

## Consequences

- Realised gains and tax are deferred, and wealth is higher on almost
  every path of this plan. Results depend on keeping parcel records, which
  the model assumes.
- The rule is greedy, sale by sale. It can realise a loss in a year with
  little income rather than keeping it for a high-income year, and it does
  not consider future rates.
- The parcels left are older and cheaper, so a final full sale would
  realise larger gains. The after-liquidation value is not reported.
- Results from runs before this change are not comparable for tax and
  wealth.

## Implementation and validation

- `retirement/ledger.py`:
  - `parcel_gains` holds the CGT event split shared by sales;
  - `taxable_per_dollar` is the ranking key;
  - `sell_parcels` sorts each asset's parcels by it.
- The app's withdrawal-strategy summary now says holdings with the smallest
  taxable gain are sold first.
- `tests/test_ledger.py::test_sales_take_the_lowest_taxable_gain_per_dollar_first`
  sells a loss parcel, then a recent parcel with a small undiscounted gain,
  then an old low-cost parcel. Oldest-first would have sold that last parcel
  first. The test checks the amounts sold and the realised gain.
- Methodology: [retirement ledger](../methodology/retirement-ledger.md),
  *Parcel selection* and the defaults table.
