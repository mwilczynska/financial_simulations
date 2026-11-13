# ADR 0058: the Method page as a technical summary of the model

Date: 2026-11-13.

Status: accepted; implemented and tested.

## Context

**User requirements:**

- The Method page should give more mathematical and modelling detail: what was chosen to be modelled and how. The
  reader is a data scientist, and the app is for personal use.
- *Assumptions behind the rules* gave no information. It listed the names of rule parameters, such as
  `medicare_low_income_lower`, for each financial year.
- Where an assumption is relevant, the methodology should explain it. Not every detail and assumption is wanted.

**Before:** the page had a six-step plain-language outline, a table on today's dollars, four steps on the market
simulation, the saved files and the parameter-name list. The equations were only in `docs/methodology`, which is
written for maintaining the code and runs to several thousand lines.

## Alternatives considered

- **Show the methodology documents in the app.** Complete, but long, organised by implementation stage, and static:
  they cannot quote the run on screen.
- **Keep the page and add an explanation to each rule parameter.** Fixes the empty expander only.
- **Rewrite the page as a technical summary** (chosen).

## Decision

`ui/method_page.py` replaces `more_pages.method_page`. The page has nine tabs:

| Tab | Contents |
| --- | --- |
| Overview | The model as a daily state update with one random input; the five stages with this run's sizes; what is random and what is fixed; today's dollars |
| Markets | The return matrix; the stationary bootstrap's recursion and block-length distribution; what it keeps and loses; the random streams; the future calendar; portfolio compounding and rebalancing; simulation error and the error of the history itself |
| Daily ledger | State and the three wealth measures; the order of a day's events; the daily identity; the income split with each ticker's rate; pay and saving; the payment order; parcel choice; the super accounts |
| Spending strategies | The schedule, the percentage start and each rule's yearly review as equations, with the plan's parameters; how the rules differ from their sources |
| Tax and super | The income tax calculation with the marginal scale; capital gains before and after 1 July 2027 and the minimum tax; super contributions, fund tax and the realised-gains assumption; Division 296; how rules are carried into later years |
| Age Pension | The payment formula with the year's values; the tapers as yearly rates; the tax offset; projection; simplifications; the outcome tiers |
| Property and loans | The annuity and interest accrual; the home; the investment property's cash flows, tax and treatment in wealth |
| Reading results | How a path is classified; pointwise percentiles; the withdrawal rate and other measures |
| Assumptions | The main simplifications in three tables (markets, economy and rules, household), each with the plan's value and the direction of its effect |

**Figures come from the run.** The text is Markdown with `[[name]]` placeholders. `facts(run)` reads every quoted
figure from the plan, the market data, the portfolio results and the rule sets, and `fill` raises `KeyError` for a
placeholder with no value. Rule values are read from the rule sets, so the page cannot drift from the TOML register.

**Rule assumptions.** The parameter-name list is replaced by:

- a table of the ten thresholds with the most effect on results, each with its 2026-27 value, its value in the last
  year simulated, that value in today's dollars and how later years are set;
- a paragraph on income tax thresholds, which the law does not index and the projection therefore holds fixed;
- an expander listing every assumed or projected parameter with its first and last values and the note from the
  rule set.

## Reasons and evidence

- **User requirement:** more technical detail, with relevant assumptions explained where they apply.
- **Engineering judgement:** tabs keep each subject to about a screen or two; one long page would not be read. The
  detailed, sourced documents stay in `docs/methodology`, and the page points to them.
- **Statements the page adds.** The page changes no calculation. It does state consequences of the method that the
  methodology documents did not spell out. Their status:
  - *Derived from the algorithm.* Under the stationary bootstrap two days `h` apart fall in the same block with
    probability `(1 - 1/L)^h` and are independent draws otherwise, so the autocovariance at lag `h`, conditional on
    the history, is `(1 - 1/L)^h` times the (circular) sample autocovariance. This was worked out from
    `sample_indices`; the proofs in Politis and Romano (1994) were not re-read.
  - *Standard results.* The count of paths below a true quantile `α` is Binomial(`N`, `α`). A share estimated from
    `M` paths has standard error `sqrt(π(1 - π) / M)`. A portfolio held at fixed weights grows faster than the
    weighted average of its parts' growth rates by about `(Σ w σ² − w'Σw) / 2` a year under continuous rebalancing.
  - *Rough guide, labelled as such.* The standard error of a mean yearly log return from `Y` years at volatility
    `σ` is `σ / sqrt(Y)`, which assumes independent years.
  - *Engineering judgement, labelled as such.* The direction of each assumption's effect in the Assumptions tab.
    Two are not in earlier documents: sampled nominal returns are deflated at the constant CPI assumption, which
    flatters stretches of history with higher inflation; and fixed income tax thresholds overstate tax late in a
    long run.
- **Sources** for the two spending rules are those of [ADR 0023](0023-retirement-spending-rules.md); the page states
  the same limits (the Guyton–Klinger portfolio rule is not used and the cut applies in every year; the Vanguard
  rule follows secondary descriptions).

## Consequences

- A change to model behaviour now has a third place to update: the code, `docs/methodology` and the page's text.
- The rule tables are rebuilt from the plan's CPI and wage assumptions with the current code. For saved results
  opened under later code they show that code's projection, not the saved manifest's.
- The Assumptions tab's directions are judgements. Measuring any of them (for example the constant-CPI deflator
  against a CPI history) would need new data or sensitivity runs.
- The page no longer has the six-step plain-language outline.

## Implementation and validation

- **Code:** `ui/method_page.py` (new), `ui/app.py`, `ui/more_pages.py` (the old page removed).
- **Tests:** `tests/test_method_page.py`: placeholders are filled and an unknown one fails; dollar signs pair and no
  placeholder or percent sign sits inside a formula; the projected-rule tables show fixed and indexed amounts (tax
  threshold \$18,200 in both years, concessional cap \$32,500 to \$42,500 and transfer balance cap \$2.1m to \$2.6m
  over nine years at 2.5% CPI and 3.5% wage growth). The app test draws the page.
- **Browser check** (13 November 2026, example plan, 1,000 portfolio and 100 ledger paths): the nine tabs drew with
  162 formulas, no formula error, no unfilled placeholder and no exception.
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
