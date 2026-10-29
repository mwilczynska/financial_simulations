# Methodology

Detailed methodology is part of every model deliverable in Financial Simulations. Documents develop with the code and explain both the calculations and the reasons for the chosen approach.

Current status: Stage 1A data/portfolio adapters, deterministic daily accounting
and static PNG reporting are implemented and validated with synthetic fixtures
and local optimiser reconciliation. See [executed evidence](../validation/stage-1a.md).
Stage 1B empirical replay/bootstrap, the Stage 1C Gaussian benchmark and
assumption grid, the GARCH filtered-historical-simulation generator, batched
cash-flow accounting and Stage 1D evaluation are implemented. Retirement
rules are implemented for 2026-27 ([register](../rules/au-2026-27.md));
the single-person account ledger, projected later-year rules and the first
stochastic planner pass are implemented within their documented limits.

## Document register

| Topic | Document/status | Scope |
| --- | --- | --- |
| Daily time resolution and accounting | [Daily engine](daily-engine.md): Stage 1A daily core implemented; later generators/rules pending | Trading observations, calendar dates, compounding, scheduled events, costs and daily validation |
| Data contract and adapters | [Data adapters](data-adapters.md): implemented, fixture-validated | Dataset aliases, strict and opt-in common-date calendars, per-return provenance, currencies, source rows, distributions, embedded fees and input hashes |
| Deterministic portfolio accounting | [Portfolio accounting](portfolio-accounting.md): implemented and validated, including batched many-path flows | Positions, daily returns, cash flows, rebalancing, retained cash, shortfalls and transaction ordering |
| Historical replay | [Resampling](resampling.md): implemented with comparison runner | Complete windows, joint sequences, mapped calendar and overlap limitations |
| Independent and block bootstrap | [Resampling](resampling.md): implemented and validated | Joint rows, observation block lengths, circular boundaries, sensitivity and reproducible streams |
| Parametric Monte Carlo | [Parametric](parametric.md): implemented and validated | Daily calibration, covariance, return support and conversion of annual assumptions |
| Volatility clustering and heavy tails | [Volatility](volatility.md): implemented | GARCH(1,1) variance targeting and filtered historical simulation |
| Assumption uncertainty and stresses | [Parametric](parametric.md): persistent scenario grid implemented; parameter sampling planned | Persistent long-run parameters, scenario grids, parameter sampling and model comparison |
| Reporting and outcome measures | [Baseline reporting](portfolio-accounting.md) and [evaluation](evaluation.md): implemented | Daily performance drawdown, account value, allocation, flows, percentiles, targets, recovery, paired portfolios, holdouts and source segments |
| Australian personal tax | [Australian rules](australian-rules.md): 2026-27 rules implemented; ledger timing planned | Dated rules, income components, AUD cost bases, gains/losses, credits and payment timing |
| Super accumulation and contributions | [Australian rules](australian-rules.md): 2026-27 caps, SG and fund tax implemented | Eligibility, contribution history, caps, fund-return conventions and costs |
| Single-person retirement ledger | [Retirement ledger](retirement-ledger.md): implemented for 2026-27 | Daily accounts, distributions, CGT parcels, contributions timing, pensions, annual assessment and shortfalls |
| Ticker plans and browser app | [Plan and app](plan-and-app.md): schema v2 implemented and locally validated | Local processed ticker provenance, two portfolio mixes, joint daily resampling, interactive and PNG results, consolidated outputs |
| Super access and retirement pensions | [Australian rules](australian-rules.md): access dates, minimum payments and transfer balance implemented | Release conditions, access dates, transfer records, minimum payments and mixed withdrawals |
| Age Pension and longevity | Planned | Eligibility, means tests, residence, mortality sources and improvement assumptions |
| Couples | Planned | Individual ownership/tax, separate access dates, household spending and survivor extensions |

Create a substantive document for a topic when its design or implementation begins. A planned entry is not a claim that the calculation, rule research or validation is complete. Split large topics into smaller documents as necessary.

## Required content

Each method document should cover the following, at a depth appropriate to the calculation:

1. **Purpose and status.** State the question answered, supported scope, and whether behaviour is proposed, implemented, validated or superseded. Give the relevant code/configuration version when available.
2. **Inputs and provenance.** Identify datasets, columns, units, frequency, currencies, coverage, source segments, quality flags, revisions and hashes. Describe what is observed, reconstructed or assumed.
3. **Definitions and equations.** Define symbols, simple/log returns, arithmetic/geometric measures, nominal/real amounts, timing, tax basis and cost treatment. State day-count and annualisation conventions explicitly.
4. **Algorithm and event order.** Describe steps precisely enough to reproduce a small example independently. Include missing values, source/calendar alignment, random sampling, non-trading dates and boundary cases.
5. **Assumptions and decisions.** Link relevant [decision records](../decisions/README.md). Explain why the approach was selected, what alternatives were considered, what evidence informs it and what remains a judgement.
6. **Worked examples.** Include small numerical cases with independently calculated expected results. Distinguish an illustrative convention from an implemented default.
7. **Validation.** Record the invariants, test/fixture identifiers, comparison sources, tolerances and observed results. Separate tests that are specified from tests that have actually run.
8. **Limitations and sensitivity.** Describe unsupported situations, calibration/sample dependence, approximations and model uncertainty, and the sensitivity checks needed before interpretation.
9. **Reproducibility.** Describe the configuration, random generator/seed, dependency/code version and input/rule-set versions needed to reproduce a result.
10. **References and revision history.** Link primary sources close to the claims they support. Include author/date/DOI or stable URL where available, access date for changeable sources, and a short history of material revisions.

## Evidence and references

Keep four categories distinct:

- A **user requirement** defines intended behaviour. Record it as such; it need not be disguised as a research conclusion.
- A **verified source fact** describes data or rules checked against an identified source and version.
- A **research finding** has the scope and assumptions of the original study. Do not generalise a result beyond those assumptions without identifying the inference.
- An **engineering judgement** is the project's choice, with alternatives and consequences recorded for review.

Use original papers, official documentation and authoritative Australian rule sources where possible. If only an abstract, older version or secondary account was reviewed, say so. A literature citation is not a substitute for validating our implementation. An external calculator comparison is useful only with reconciled assumptions and is not proof of every rule.

## Maintenance workflow

Write the method specification and decision rationale before or alongside the implementation. Update examples, supported scope, code links and validation results in the same coherent checkpoint. Mark proposed tests as completed only after collecting actual results.

Commit and push reviewed checkpoints regularly. Preserve earlier decisions and methodology changes through Git history, and use explicit superseding records when the rationale changes materially. Private scenarios and reports remain outside committed methodology.

## Revision history

- 2026-10-28: Established the methodology register and writing standard following the requirement for detailed, referenced explanations of project decisions.
