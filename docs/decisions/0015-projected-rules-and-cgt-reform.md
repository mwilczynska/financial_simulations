# ADR 0015: projected later-year rules and the 2027 CGT reform under an assumed CPI

Date: 2026-10-28. Status: accepted; implemented and tested.

## Context

The single-person ledger ([ADR 0014](0014-single-person-ledger-conventions.md))
could not cross 1 July 2027. From that date the enacted CGT reform (Act No.
49, 2026) replaces the 50% discount for gains accruing afterwards. It uses
CPI cost-base indexation and a 30% minimum tax, with a deemed sale and
reacquisition at market value on 1 July 2027. Other enacted changes take
effect at the same time: the 14% first rate (Act No. 28, 2025) and the
Working Australians Tax Offset. Caps and thresholds are indexed in law, but
their future values are unknown. Australian CPI data was deferred by the
user, who has now approved an explicit assumed CPI rate in the meantime.

## Alternatives considered

1. Freeze every threshold at its 2026-27 value. This is simple, but it
   misstates caps that the law indexes.
2. Wait for Australian CPI and wage data. That blocks all multi-year
   retirement work.
3. Derive later years with a declared treatment per parameter (enacted,
   projected from assumed CPI or wage growth at statutory rounding, or a
   frozen assumption). Implement the reform with the market-value method and
   an assumed CPI path.

## Decision

Choose 3. Mark projected values with a new `projected` status, and report
them with assumptions in every manifest. Implement the deemed reacquisition
in the ledger by recording each parcel's 30 June 2027 close. Split later
sales into a deferred gain (discountable) and a post-reform gain on an
indexed cost base. Apply the s119-10 minimum tax. Stop the ledger before the
person reaches Age Pension age, because SAPTO, which applies from that age,
is not yet implemented. Report a horizon that ends mid-year as an
unassessed partial year, rather than dropping its income.

## Consequences

- Long runs depend on two declared rates. Results must be read as
  conditional on them, and should be tested for sensitivity to them.
- The apportionment method, property-specific rules and negative gearing are
  outside scope until legislated or modelled.
- Retirement runs end before age 67 until the Age Pension and SAPTO module
  (Stage 2D) exists.

See the [projection register](../rules/au-projection.md),
[methodology](../methodology/australian-rules.md) and
[validation](../validation/stage-2a.md).
