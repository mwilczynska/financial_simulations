# ADR 0033: statutory loss order, offsets against the minimum tax and the Age Pension exemption

Date: 2026-11-02.

Status: accepted; implemented and tested. Corrects parts of the CGT reform implementation from
[ADR 0015](0015-projected-rules-and-cgt-reform.md), which remains accepted for its other choices.

## Context

The [1 November 2026 retirement calculation review](../reviews/2026-11-01-retirement-calculations/README.md)
found three errors in the 2027 CGT reform (Act No. 49, 2026) as implemented:

1. Losses reduced post-reform gains before deferred gains. The docstring and methodology called this the
   taxpayer-favourable order the law permits.
2. The ledger never set `minimum_tax_exempt`, so a person receiving the Age Pension paid the minimum tax.
3. Non-refundable offsets were applied to basic tax and floored at nil before the minimum tax was added, so
   offsets could not reduce it. The methodology labelled this an engineering interpretation.

The first two understate or overstate tax for the shares and funds the ledger actually models; no property
support is needed to reach them.

## Alternatives considered

- **Loss order.** Keep the favourable order (contrary to the statute), or apply the s102-5 category order.
- **Exemption.** Exempt everyone of Age Pension age, exempt anyone the means test assesses, or exempt only
  those who receive a payment in the year.
- **Offsets.** Keep the minimum tax after offsets, or add it to basic tax before the non-refundable offsets.

## Decision

- From 2027-28, current-year and carried-forward losses reduce deferred gains, then post-reform gains. Within
  the deferred category, non-discount gains go before discountable gains. Years before the reform keep
  non-discount, then discountable.
- The ledger sets `minimum_tax_exempt` when the year's Age Pension receipts are above nil.
- `assess` adds the minimum tax to basic tax, then applies LITO, WATO, SAPTO, the excess concessional
  contributions offset and the foreign income tax offset, floored at nil. Franking credits remain refundable
  after that. Reported offsets are the amounts used against that total.

## Reasons and evidence

Verified source facts (read on 2 November 2026):

- Act No. 49, 2026 (as made, 26 June 2026), Schedule 1, amended s102-5 step 1: reduce deferred
  non-residential gains first, then deferred residential, then non-residential, then residential gains; its
  note lets the taxpayer choose the order within each. Step 2 applies earlier years' net capital losses to
  further reduce the amounts. The amendments apply to assessments for the income year that includes
  1 July 2027 and later years.
- The same Act, s119-15: s119-10 does not apply to a person who receives an age pension under Part 2.2 of the
  Social Security Act 1991 (or an age service pension) at any time during the income year.
- Act s119-10 computes the minimum tax gap amount from basic income tax liability disregarding Division 119.
  The Division guide says the 30% applies before offsets. No operative provision found states how offsets
  apply to the gap amount.
- Treasury, "Negative Gearing and Capital Gains Tax Reform" (Budget 2026 tax explainer), page 8, Jack's
  minimum-tax example: Jack "may have tax offsets available to reduce the minimum tax". The explainer also
  describes the exemption as applying if any income support payment is received in the year of the gain.

Engineering judgement: within deferred gains, reducing non-discount gains first is the favourable choice the
note permits. Applying current-year and carried-forward losses as one amount in the same category order gives
the same result as steps 1 and 2 in sequence. Ordering the offsets among themselves does not matter while all
are non-refundable and none transfers. The JobSeeker and other s119-15 payments are not modelled.

## Consequences

- Loss-order change: tax rises where losses meet both deferred and post-reform gains. The review case moves
  from a $20,000 net capital gain and nil minimum tax base to $25,000 and $10,000.
- Offset change: minimum tax falls for low-income taxpayers with offsets, from $3,000 to $2,300 in the review
  case.
- Exemption change: Age Pension recipients no longer pay it; the review ledger case falls from $1,349 to nil.
- A person who reaches Age Pension age but whose means test pays nil, or whose first payment falls after 30
  June, is still subject to the minimum tax.
- The combined effect on a plan is not measured here.

## Implementation and validation

- Code: `net_capital_gain` and `assess` in `src/financial_simulations/rules/au/tax.py`; the 30 June
  assessment in `src/financial_simulations/retirement/ledger.py`.
- Methodology: [australian-rules.md](../methodology/australian-rules.md),
  [au-projection.md](../rules/au-projection.md), [retirement-ledger.md](../methodology/retirement-ledger.md).
- Tests in `tests/test_projection.py`:
  - `test_reform_year_losses_reduce_deferred_gains_before_post_reform_gains` covers mixed categories, carried
    losses, deferred non-discount gains and losses beyond the deferred gains.
  - `test_non_refundable_offsets_reduce_the_minimum_tax` covers LITO, SAPTO, LITO with WATO, and franking
    credits.
  - `test_ledger_exempts_minimum_tax_only_when_age_pension_is_received` covers a part pension, a
    means-tested nil rate, a first payment on 24 June and a first payment after 30 June.
  - The existing CGT tests are unchanged and pass.
