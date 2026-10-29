# Decision records

Decision records preserve why Financial Simulations makes a material modelling or engineering choice. They complement the [detailed methodology](../methodology/README.md), which specifies how the calculations work.

## Register

| Record | Date | Status | Decision |
| --- | --- | --- | --- |
| [0001](0001-daily-returns-throughout.md) | 2026-10-28 | Accepted requirement; Stage 1A implemented and validated | Retain daily returns and daily account evolution throughout |
| [0002](0002-methodology-and-decision-records.md) | 2026-10-28 | Accepted documentation workflow | Maintain detailed methodology and referenced reasons with the code |
| [0003](0003-stage-1a-data-contract.md) | 2026-10-28 | Accepted; adapters fixture-validated | Explicit data/weight contracts and strict matching observation calendars |
| [0004](0004-stage-1a-accounting-conventions.md) | 2026-10-28 | Accepted; implemented and validated | Opening mark, cash execution, annual rebalancing, performance and PNG plots |
| [0005](0005-default-portfolio-and-tracker-audit.md) | 2026-10-28 | Accepted; default implemented and tracker functions audited | User-selected leveraged default and treatment of existing calculations |
| [0006](0006-joint-daily-resampling.md) | 2026-10-28 | Accepted; core and sensitivity runner validated | Joint rows, complete windows, explicit calendars and path streams |
| [0007](0007-daily-parametric-assumptions.md) | 2026-10-28 | Accepted; implemented and validated | Daily Gaussian log returns and persistent scenario assumptions |
| [0008](0008-calendar-evaluation-and-sampling-error.md) | 2026-10-28 | Accepted; initial reporting pass validated | Calendar-day evaluation, targets, censored recovery and sampling error |
| [0009](0009-common-date-calendar-policy.md) | 2026-10-28 | Accepted; fixture-validated | Opt-in common-date calendars and per-return source provenance |
| [0010](0010-batched-cash-flow-accounting.md) | 2026-10-28 | Accepted; reconciled to the full ledger | Batched many-path accounting with dated cash flows |
| [0011](0011-garch-filtered-historical-simulation.md) | 2026-10-28 | Accepted; synthetic validation | GARCH(1,1) filtered historical simulation as the heavy-tail generator |
| [0012](0012-paired-holdout-and-segment-studies.md) | 2026-10-28 | Accepted; synthetic and companion-data validation | Paired portfolio, source-segment and rolling holdout studies |
| [0013](0013-stage-2a-rule-register-scope.md) | 2026-10-28 | Accepted; 2026-27 rules implemented and tested | Sourced 2026-27 rule register with explicit unsupported cases |
| [0014](0014-single-person-ledger-conventions.md) | 2026-10-28 | Accepted; 2026-27 ledger implemented and tested | Daily single-person ledger conventions |
| [0015](0015-projected-rules-and-cgt-reform.md) | 2026-10-28 | Accepted; implemented and tested | Projected later-year rules and the 2027 CGT reform under an assumed CPI |
| [0016](0016-plan-file-and-browser-app.md) | 2026-10-28 | App/file decision remains; v1 inputs superseded by 0017 | One plan file with a local browser app |
| [0017](0017-ticker-portfolios-and-interactive-results.md) | 2026-10-28 | Accepted; buy-and-hold accounts superseded by 0018 | Local tickers, two portfolio mixes, shared daily simulations and interactive results |
| [0018](0018-planner-annual-rebalancing.md) | 2026-10-28 | Accepted; implemented and locally validated | Annual rebalancing per account in the planner and tax ledger |
| [0019](0019-retirement-path-results.md) | 2026-10-28 | Accepted; implemented and locally validated | Keep depleted retirement paths, cap whole-balance pension transfers, more paths and results |
| [0020](0020-outside-contributions-stop-at-retirement.md) | 2026-10-29 | Accepted; implemented and locally validated | Surplus or fixed (optionally indexed) outside contributions that stop at retirement; sacrifice as a percentage |
| [0021](0021-cash-interest-and-withdrawal-rates.md) | 2026-10-29 | Accepted; implemented and locally validated | Interest on cash; withdrawal rates to a planning age, and a rate that lasts indefinitely |
| [0022](0022-payg-withholding.md) | 2026-10-29 | Accepted; implemented and locally validated | Estimated PAYG withholding on salary each payday; assessment settles the balance |
| [0023](0023-retirement-spending-rules.md) | 2026-10-29 | Accepted; implemented and locally validated | Optional Guyton–Klinger and Vanguard retirement spending rules; fixed dollar spending stays the default |

## When to write a record

Record choices that materially affect interpretation, accounting, data selection, model structure, calibration, calendar handling, sampling, Australian rules or reproducibility. Routine edits do not need their own record.

Each record should identify the context and constraints, alternatives, the decision, why it was made, consequences, references and implementation/validation status. Distinguish a user requirement from a research finding or engineering judgement.

Use the next available numeric identifier and a concise filename. The [template](template.md) supplies a starting structure. Link records from the relevant method documents and vice versa.

If a decision changes, create a superseding record and link both records. Preserve the old reasoning and the status change. An accepted design is not a claim that it has been implemented or validated.
