# Stage 2A validation

Date: 2026-10-28. Status: the 2026-27 rule set, the rule functions and the
single-person daily ledger are implemented and tested. Hosted CI passed for
the rule checkpoint `2b064e6`. This record covers the rules and the ledger.

## Rule functions (`tests/test_au_rules.py`, 36 tests)

Bracket boundaries match the ATO's cumulative amounts. The ATO worked
examples are reproduced exactly: a Medicare levy of $98.90 at $29,000 of
taxable income, a 2026-27 Medicare levy surcharge of $1,170, and the halved
2019-20 pension minimum of $3,110. Further tests cover:

- the LITO turning points and the standard deduction cases;
- CGT holding-period edges, including 29 February acquisitions, and loss
  ordering;
- franking refunds, Division 293 and preservation-age cut-offs;
- leap-day ages and access paths;
- SG at the maximum contribution base, and business days;
- carry-forward expiry, bring-forward thresholds and fixed totals;
- pension minimums, the transfer balance cap, Division 296 rejection and
  fund tax;
- every unsupported path.

One test requires every rule parameter, and every assumption, to appear in
the [register](../rules/au-2026-27.md) with ATO or legislation sources.
During development a test caught carry-forward amounts older than five
years being consumed; the fix and its regression test are in place.

## Ledger (`tests/test_ledger.py`, 13 tests)

- **Salary and SG.** $104,000 over 26 fortnightly paydays gives a $480 SG each
  payday, reaching the fund exactly 7 business days later, less $72
  contributions tax. The accumulation closes at $100,000 + 26 x $408. The
  year's assessment equals a stand-alone `assess` call. The liability is due
  2027-10-31, and $20,020 of unused cap carries forward.
- **Cap years.** A payday on 24 June 2027 contributes on 5 July 2027, so it is
  outside the 2026-27 cap and reported as pending.
- **Pensions.** A $500,000 pension at 61 pays a $20,000 minimum in 12
  instalments. The surplus is invested outside, and the transfer balance is
  $500,000. A 1 January commencement pro-rates the minimum to $4,960
  ($10,000 x 181/365, rounded to $10).
- **Bridge shortfall.** A 46-year-old with $10,000 accessible and $300,000
  of preserved super records $14,000 of shortfall over seven months while
  super is untouched. Spending scheduled for Saturday 1 August is paid on
  Monday 3 August.
- **Accessible super.** A 61-year-old retiree's $9,000 of unmet spending
  comes from accumulation lump sums.
- **Income and gains.** Franked distributions of $4,000 leave total wealth
  unchanged in a flat market and produce a $1,714.29 refund. Monthly sales
  from a 2020 parcel with a 50% cost base realise $6,000 of gains, giving a
  $3,000 net capital gain, and leave $38,000 invested.
- **Fund tax.** A $200,000 accumulation earning 4% unfranked pays $1,200
  fund tax. A pension's franking credits are refunded exactly.
- **Reconciliation.** On a random path, buy-and-hold super compounds exactly
  to the product of returns. A mixed scenario reconciles every day:
  employment, retirement, sacrifice, distributions, sales, a mid-year
  pension and spending.
- **Failure cases.** A $200,000 bring-forward is accepted, while $400,000 of
  non-concessional contributions and excess salary sacrifice are rejected.
  A horizon into 2027-28, a pension without a release condition, a USD path
  and a $3.1m balance (Division 296) also fail.
- **Report.** The writer produces CSV, JSON and PNG outputs, with no PDF.

The suite has 160 tests, all passing on Python 3.14, and the repository
check passes.

## Projected years and the CGT reform (`tests/test_projection.py`, 7 tests)

- **Projected rule sets** (2.5% CPI, 3.5% wage growth): the 14% rate is
  marked enacted. Concessional caps are $32,500, $32,500 and $35,000 (2029-30
  non-concessional $140,000, maximum contribution base $291,660). Transfer
  balance caps are $2.1m then $2.2m, and the 2028-29 Division 296 threshold
  is $3.15m. Medicare thresholds stay frozen as assumptions. Each year's hash
  is unique.
- **Indexation.** Eight quarters give a factor of 1.051; the same quarter or
  deflation gives 1. Gains above the indexed cost are taxed, nothing between,
  and an unindexed loss below cost; there is no indexation under 12 months.
- **Minimum tax.** The cases give $9,748 (exempt: nil), nil for a
  high-income taxpayer, $1,600 in the deferred-plus-post-reform mix, and nil
  when losses absorb the gain.
- **Working Australians offset.** $250 at $50,000 of labour income; nil at
  $18,000 of net labour income and in 2026-27.
- **Three-year ledger run.** The 1 July 2027 valuation equals the 30 June
  close. Later sales split into deferred and post-reform gains, and the
  2027-28 minimum-tax base equals the post-reform gains. The 2026-27 tax due
  on Sunday 31 October 2027 is paid on Monday 1 November. A partial final
  year is reported as unassessed.
- **Pension across years.** The second year's minimum is reset from the
  30 June balance and paid in full. Age Pension age stops the run, and a
  post-reform start without the reform values is rejected.

Floating-point noise briefly turned a $1,600 minimum tax into $1,599 before
the statutory round-down. The calculation now removes noise below a cent
first. The suite has 167 tests, all passing.

## Example run and visual review

`python scripts/ledger_example.py` runs two invented people for five income
years (2026-27 to 2030-31). The market input is deterministic 7% and 6%
annual growth, and the projected rules assume 2.5% CPI and 3.5% wage growth.
Outputs go to `output/stage2a-ledger/<scenario>/`. An earlier version used
one random draw; over five years it fell 33% for the global asset, which
made the demonstration depend on an arbitrary seed. Stochastic paths are
left to the Stage 1 generators. The first-year results below are from the
first, one-year version of the example.

- **Early retiree at 54.** They stop work on 31 December 2026 after 13
  paydays and $14,800 of concessional contributions. The bridge is funded
  from outside cash and investments with no shortfall. Taxable income is
  $98,205; the $18,031 tax settles on 31 October 2027.
- **Retiree at 62.** They have an $800,000 account-based pension and
  $150,000 outside. A $32,000 minimum is paid monthly and spending of
  $65,000 is met. Taxable income is $10,263, from outside distributions and
  gains, giving a $2,159 refund.

Both `ledger.png` files were inspected. The first review found that pension
payments were missing from the flow panel, because they are internal
transfers, and that a refund was shown as negative tax. Both were fixed and
re-rendered. These are mechanics demonstrations, not projections.
