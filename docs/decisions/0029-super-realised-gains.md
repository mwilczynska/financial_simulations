# ADR 0029: assume super funds realise part of their gains each year

Date: 2026-10-29. Status: accepted; implemented and locally validated.

## Context

The ledger's super funds never realised capital gains. So the 15% fund tax
fell only on distributions, and Division 296 (ADR 0028), whose earnings are
based on the fund's taxable income, was a lower bound. For growth-heavy
portfolios most of the return is price growth.

Real funds realise gains as they trade, rebalance and meet member
withdrawals. Large APRA funds must count those gains towards Division 296:
20% of the gain in 2026-27, rising to 80% in 2029-30, and in full from
2030-31. The user asked for a realised-gains assumption.

## Evidence

No published source gives the share of a super fund's unrealised gains that
is realised each year. A search found commentary on Division 296 but no
turnover data. The enacted general rule (s296-60, s296-65) bases earnings
on the fund's taxable income, so realised gains, not unrealised gains,
count. The tax-on-unrealised-gains approach applies only to defined benefit
and prescribed interests (s296-70).

## Alternatives

1. Keep realising nothing (lower bound).
2. Model each fund's trades. The data do not exist.
3. Realise a fixed share of each account's accumulated unrealised gain each
   30 June, as a declared plan input.

## Decision

Option 3:

- **Plan input.** `super.realised_gains`, default 0.20, an engineering
  judgement equivalent to gains held about five years on average. The
  ledger's own default is 0, so earlier results can be reproduced.
- **Cost base.** Each super account (accumulation, pension) keeps an
  aggregate cost base:
  - purchases (contributions, reinvested distributions, fund tax credits) add
    to it;
  - sales and the move to the pension carry it pro rata;
  - realised gains are added to it;
  - the opening balance is taken to carry no accrued gain.
- **Realisation.** Each 30 June the fund realises the chosen share of
  (value − cost base) when positive. Losses are not realised.
- **Fund tax.** Accumulation tax is 15% of the gain after the one-third
  complying-fund discount (10% effective), using the existing
  `accumulation_earnings_tax`. Pension-phase gains are exempt.
- **Division 296 earnings.** These add the discounted gains of both
  accounts, scaled by the new rule parameter `division_296_cgt_factor`: 0.2
  in 2026-27, then 0.4, 0.6 and 0.8, then 1.0 (ATO, prescribed by
  regulation; enacted status).

## Reasons

- It applies the enacted tax rules to a stated, adjustable behaviour rather
  than to an implicit zero.
- 0% and 100% bracket the plausible range, and the input lets the user test
  sensitivity.

## Consequences

- Super grows more slowly in accumulation (the 10% effective tax on realised
  gains), and Division 296 is higher and rises through 2030-31 as the
  transitional factor phases out.
- Results depend on an unsourced assumption, which the app and the
  documents label as such.
- Not modelled:
  - fund-level capital losses;
  - gains embedded in the opening balance;
  - assets held less than 12 months (all realised gains are discounted);
  - small funds' cost-base reset election.

## Validation

- `tests/test_ledger.py::test_super_funds_realise_a_share_of_gains_taxed_in_accumulation_and_counted_for_division_296`
