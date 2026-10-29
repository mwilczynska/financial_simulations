# Next-session handoff

Updated: 2026-10-28. Read [AGENTS.md](../AGENTS.md) and [PLAN.md](../PLAN.md) before
changing model behaviour. This note describes the current state. Earlier
handoff text is in Git history.

## Where the project stands

Stage 1 (portfolio futures, 1A-1D) is implemented and validated within its
documented scope. The user started Stage 2 on 2026-10-28. Stage 2A's first
checkpoint (sourced 2026-27 rule register, data file and tested rule
functions) is done; the auditable single-path ledger is next. AUD FX and Australian inflation are deferred
by the user to a later date. Keep the user-selected default portfolio:
`USLCAP3x` 40%, `ITT3x` 20%, `GOLDPM2x` 20%, `COMM` 20%, annual rebalancing.
Generate PNGs directly from Python; never create PDFs.

| Area | Entry point | Method / decision | Evidence |
| --- | --- | --- | --- |
| Data adapters, strict and `common_dates` calendars, per-return provenance | `load_datasets` | [data adapters](methodology/data-adapters.md), ADR [0003](decisions/0003-stage-1a-data-contract.md), [0009](decisions/0009-common-date-calendar-policy.md) | `tests/test_adapters.py` |
| Daily ledger and batched many-path ledger with dated flows | `simulate_portfolio`, `simulate_paths` | [accounting](methodology/portfolio-accounting.md), ADR [0004](decisions/0004-stage-1a-accounting-conventions.md), [0010](decisions/0010-batched-cash-flow-accounting.md) | `tests/test_accounting.py`, `tests/test_batch_flows.py` |
| Replay and bootstraps | `compare` | [resampling](methodology/resampling.md), ADR [0006](decisions/0006-joint-daily-resampling.md) | [stage 1B](validation/stage-1b.md) |
| Gaussian benchmark, assumption grid | `compare` with `[parametric]` | [parametric](methodology/parametric.md), ADR [0007](decisions/0007-daily-parametric-assumptions.md) | [stage 1C](validation/stage-1c.md) |
| GARCH(1,1) filtered historical simulation | `[volatility]` or `garch_fhs` | [volatility](methodology/volatility.md), ADR [0011](decisions/0011-garch-filtered-historical-simulation.md) | `tests/test_volatility.py` |
| Calendar evaluation, targets, recovery, MC error | `compare` with `[evaluation]` | [evaluation](methodology/evaluation.md), ADR [0008](decisions/0008-calendar-evaluation-and-sampling-error.md) | [stage 1D](validation/stage-1d.md) |
| Australian 2026-27 tax and super rules | `rules.au` | [Australian rules](methodology/australian-rules.md), ADR [0013](decisions/0013-stage-2a-rule-register-scope.md), [register](rules/au-2026-27.md) | `tests/test_au_rules.py` |
| Paired portfolios, source segments, tail diagnostic, holdouts | `paired`, `holdout` | [evaluation](methodology/evaluation.md#paired-portfolio-source-segment-and-holdout-studies), ADR [0012](decisions/0012-paired-holdout-and-segment-studies.md) | [stage 1D](validation/stage-1d.md), `tests/test_studies.py` |

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts/check_repository.py
.\.venv\Scripts\python.exe scripts/validate_stage1a.py --output output/validation
.\.venv\Scripts\python.exe scripts/validate_experiment.py --experiment scenarios/examples/evaluation.toml --output output/stage1d
.\.venv\Scripts\python.exe -m financial_simulations paired scenarios/examples/paired.toml --output output/stage1d-paired
.\.venv\Scripts\python.exe -m financial_simulations holdout scenarios/examples/holdout.toml --output output/stage1d-holdout
.\.venv\Scripts\python.exe scripts/validate_studies.py --reuse
```

`validate_experiment.py` (formerly `validate_stage1b.py`) audits any `compare`
experiment. `validate_studies.py` audits the two study outputs and the batched
cash-flow engine. Outputs and companion data stay ignored.

## Findings to carry forward

These are conditional, nominal-USD results, not forecasts:

- **The lognormal model understates leveraged-portfolio risk.** Across 45
  one-year rolling holdouts, its central 90% interval covered the default
  portfolio's realised volatility in 38% of origins, and its maximum drawdown
  in 51%. GARCH-FHS covered 78% and 73%, and the stationary bootstrap 67% and
  71%. All three covered terminal wealth in about 90% of origins.
- **GARCH-FHS overstates the most extreme days.** A 1987-style residual drawn
  in a high-variance state gives losses beyond history: in the reconstructed
  window, a -66% worst portfolio day against -25% observed.
- **Window choice dominates generator choice.** On the observed-only
  2009-2025 window, the leveraged default beats both comparators on almost
  every 2,520-observation path. On the reconstructed 1970-2006 window, the
  unlevered same mix beats it on 27-35% of generated paths, and its 5th
  percentile is higher.
- **Reconstructed history differs materially.** Before 2006 the series are
  dataset-project models: `USLCAP3X` excess kurtosis is 67 there against 16
  observed, and its worst day is -57% against -35%.

## Open next steps

- Stage 2A checkpoint 2: an auditable single-path daily ledger for one
  person: salary, Payday Super contributions and cap years, outside
  investments with cost bases, super accumulation and pension phase, tax
  assessment timing and minimum pension payments. `simulate_paths` is the
  batched building block; state-dependent withdrawals need a ledger-reconciled
  extension.
- 2027-28 and later rule sets with declared per-parameter treatment, and the
  enacted 1 July 2027 CGT reform (needs Australian CPI, which the user
  deferred).
- Refresh the 2026-27 Medicare low-income thresholds when the ATO publishes
  them (currently a labelled assumption).
- Optional Stage 1 extensions: residual trimming or stress scenarios for
  GARCH-FHS, time-varying correlation, outer parameter sampling, and
  interactive plots (a later reporting step).
- AUD FX and Australian CPI datasets belong in `financial_datasets` when the
  user schedules them.
