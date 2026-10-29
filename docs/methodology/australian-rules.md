# Australian tax and super rules (Stage 2A)

Date: 2026-10-28. Status: the 2026-27 rule set and its calculation functions
are implemented and tested against hand calculations and ATO worked
examples. The single-path account ledger is the next 2A checkpoint, and no
stochastic retirement modelling is connected yet. Register:
[2026-27 rules](../rules/au-2026-27.md). Decision:
[ADR 0013](../decisions/0013-stage-2a-rule-register-scope.md).

## Purpose and evidence classes

This method turns dated Australian rules into functions a daily ledger can
call. It is the retirement model's only source of tax and super rules. The
evidence classes are:

- **User requirements:** one Australian tax resident, then couples; individual
  ownership and access dates; current authoritative sources; enacted law kept
  apart from proposals.
- **Verified source facts:** every number in the register was read on the
  linked ATO or legislation page on 2026-10-28.
- **Engineering choices:** marked as such below.

## Rule data and loading

Each `fyYYYY_YY.toml` file in `financial_simulations/rules/au` contains a
`[ruleset]` header (financial year, 1 July start, 30 June end, verification
date), a source list and named parameters. Each parameter has a value, a
status (`enacted`, `published_indexed` or `assumption`), a source id and an
optional note. `load_ruleset` rejects unknown statuses or sources and metadata
that disagrees with the file name. It records the file's SHA-256 hash. The
manifest lists every assumption and its reason, so a later report can show
which results depend on values the law has not yet set.

No future year is filled in silently. In law, the personal brackets, LITO
and the Division 293 threshold are unindexed. Caps and the transfer balance
cap are indexed in steps. The Medicare low-income thresholds are set by
legislation each year. A later rule set must declare which of these
treatments it applies to each parameter.

## Personal income tax (`rules/au/tax.py`)

For one resident full year:

1. **Net capital gain.** Current-year and carried-forward losses offset
   non-discountable gains first, then discountable gains. The 50% discount
   then applies to the remaining discountable gains. That order is the
   favourable one the law allows. Unused losses carry forward. An asset is
   discountable if the CGT event is after the first anniversary of
   acquisition. That is "at least 12 months excluding both days"; a
   29 February acquisition's anniversary is 1 March.
2. **Assessable income.** Labour income, interest, unfranked dividends,
   franked dividends grossed up by franking credits, other income, foreign
   income, the net capital gain, and any excess concessional contributions.
3. **Deductions.** The work deduction is max(claimed expenses,
   min($1,000, labour income)). Deductible personal super contributions and
   other deductions are added.
4. **Taxable income** is assessable income less deductions, rounded down to
   a whole dollar, with a floor of nil. Tax losses are not carried in this
   checkpoint.
5. **Basic tax** comes from the marginal brackets.
6. **Non-refundable offsets.** LITO, the 15% offset on excess concessional
   contributions, and foreign tax paid up to the $1,000 no-calculation limit
   reduce basic tax to no less than nil. Applying the foreign offset only
   against basic tax is a simplification.
7. **Medicare levy.** Nil up to the lower threshold, then 10% of the excess
   until it reaches 2% of taxable income.
8. **Medicare levy surcharge** (without hospital cover). The tier is chosen
   on taxable income plus reportable fringe benefits and reportable super
   contributions. The rate applies to taxable income plus fringe benefits,
   which reproduces the ATO's 2026-27 example.
9. **Franking credits** are refundable: net tax = income tax after offsets +
   levy + surcharge − franking credits, which can be negative.
10. **Division 293 tax**, assessed separately, is 15% x min(low-tax
    contributions, taxable income + fringe benefits + low-tax contributions −
    $250,000). Net investment losses are not modelled.

## Super (`rules/au/superannuation.py`)

### Ages and access

- **Ages.** A person attains an age on the anniversary date. A 29 February
  birth attains it on 1 March in a common year.
- **Preservation age** comes from the date-of-birth table.
- **Access date.** Unrestricted access starts at the earlier of age 65 and
  retirement on or after preservation age. Retiring earlier gives access at
  preservation age, given the stated intention never to work again (an
  engineering interpretation of the ATO's description of the retirement
  condition).
- **Benefits before 60** are rejected, so all supported benefits are tax
  free.

### Contributions

- **Super guarantee (SG)** is 12% of each payday's qualifying earnings until
  the year's maximum contribution base is reached.
- **Contribution dates.** `add_business_days` gives the latest date the fund
  must receive the contribution, counting weekdays only. Public holidays are
  not modelled, so the true deadline can be later. A contribution's cap year
  is the financial year in which the fund receives it.
- **Concessional cap.** The general cap, plus unused amounts from the five
  prior years (accrued from 2018-19) when TSB at the prior 30 June was below
  $500,000. Contributions above the general cap use the oldest unused amounts
  first. The function returns the unused history still valid for the next
  year. Exceeding the available cap fails.
- **Non-concessional cap.** At or above the transfer balance cap, the cap is
  nil. Within an open bring-forward period, the remaining fixed total
  applies, and later indexation is ignored, as the ATO describes. Otherwise a
  person under 75 at any time in the year gets 3-, 2- or 1-year room by TSB.
  Exceeding the available room fails. A period opens only when a
  contribution exceeds the annual cap.

### Retirement phase and fund tax

- **Minimum pension payments** use the age-band factor. For a full year,
  this is the 1 July balance and age. A pension commencing mid-year uses its
  commencement balance and age, pro-rated by days remaining (including the
  commencement day) over days in the year, and needs nothing if it starts in
  June. The result is rounded to the nearest $10.
- **Transfer balance account.** Credits and debits (commutations) are
  tracked against the personal cap. A credit that would exceed it fails.
  Proportional indexation of a partly used personal cap is not yet
  implemented; it matters only in years after the first retirement-phase
  transfer.
- **Accumulation earnings tax** is 15% of income + franking credits + net
  capital gain x (1 − one-third), less franking credits. Losses offset gains
  before the discount. Retirement-phase earnings are exempt. How returns
  separate into income, gains and fees is a ledger input. It must reconcile
  to the total-return series, so distributions are never counted twice
  ([ADR 0001](../decisions/0001-daily-returns-throughout.md) principles apply).
- **Division 296.** A TSB above $3 million fails explicitly.

## Worked examples (all tested)

| Case | Result |
| --- | --- |
| Salary $100,000, no other income | Taxable $99,000 after the standard deduction; tax $20,220 + Medicare $1,980 = $22,200 |
| Taxable income $29,000 | Medicare levy $98.90 (ATO example) |
| $90,000 taxable, $27,000 fringe benefits, no hospital cover | MLS $1,170 (ATO 2026-27 example) |
| $7,000 franked dividends with $3,000 credits, no other income | Taxable $10,000; refund $3,000 |
| Taxable $240,000, $30,000 low-tax contributions | Division 293 $3,000 |
| $40,000 concessional; unused $10,000 (2021-22) and $2,000 (2025-26); TSB $400,000 | 2021-22 covers the $7,500 excess; only $2,000 (2025-26) carries to 2027-28 |
| TSB $1.5m / $1.9m / $2.0m / $2.1m | NCC room $390k / $260k / $130k / nil |
| $250,000 pension commencing 1 Jan 2027 at 66 | $12,500 x 181/365 = $6,198.63, rounded to $6,200 |
| ATO 2019-20 example, halved | $3,107 rounded to $3,110 |

## Validation, limitations and maintenance

`tests/test_au_rules.py` covers every bracket boundary, the LITO turning
points, the ATO Medicare and MLS examples, the standard deduction cases, the
CGT holding-period edges (including leap days), loss ordering and carry
forward, franking refunds, Division 293, and preservation-age births on
either side of each cut-off. It also covers leap-day ages, access paths, SG
at the maximum base, business days, the carry-forward expiry bug found during
development, bring-forward thresholds and fixed totals, pension minimums,
the transfer balance cap, Division 296 rejection and fund tax. A further test
requires every TOML parameter to appear in the register.

These functions do not yet form an account ledger. They do not track tax
instalments and assessment timing, rental property, trusts, couples, Age
Pension, or the 2027 reforms. Whenever the ATO publishes the 2026-27 Medicare
thresholds or other values change, update the TOML file, the register and
the verification date in the same change.

Revision history: 2026-10-28, first 2026-27 rule set and functions.
