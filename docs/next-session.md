# Stage 1C implementation and next-session handoff

Updated: 2026-10-28. The user authorised Stage 1B after the Stage 1A closeout.

The user has now requested a commit/push and implementation of the next part.
Stage 1C is in progress: daily correlated log-return calibration/generation,
annual return conventions and synthetic moment/boundary checks are implemented.
There are 67 passing tests. Continue with persistent scenario assumptions,
comparison integration, purchasing-power deflation, trace reconciliation and
direct Python PNG review. Read [parametric methodology](methodology/parametric.md),
[ADR 0007](decisions/0007-daily-parametric-assumptions.md) and
[Stage 1C validation](validation/stage-1c.md).

Stage 1B now provides complete-window mapped historical replay, joint independent
rows, moving blocks, stationary bootstrap and a daily no-flow sensitivity runner.
The sampler/accounting checkpoint is `245f9e4`; the following runner checkpoint
contains the rest of this implementation. See
[methodology](methodology/resampling.md) and [validation](validation/stage-1b.md).

The default comparison uses 2010-2025 and 2016-2025, horizons 252/1260/2520,
block lengths 21/63/252 and two seeds with 256 stochastic paths each. The first
run evaluates 90 cases and 33,060 paths, with 12 reconstructible examples.
The shorter sample has zero complete 2,520-observation replay windows. PNGs
include terminal intervals, individual paths and return/squared-return dependence.
No-flow batched accounting matches the full ledger; the full suite has 63 tests.

Use `python scripts/validate_stage1b.py --output output/stage1b` to run the
experiment and audit saved traces. The account calendar is explicitly a shared
observed template; an optional target-date CSV can provide another grid.

Stage 1A is implemented: explicit local adapters, daily holdings/cash accounting,
annual/buy-and-hold policies, dated flows, inspectable CSV/Parquet/HTML outputs
and standalone Matplotlib PNGs. The user-selected default is `USLCAP3x` 40%,
`ITT3x` 20%, `GOLDPM2x` 20%, `COMM` 20%. Keep daily observations distinct from
calendar account marks. Do not create PDFs. Interactive charts remain later work.

Implementation checkpoints are `a9031fc` (adapters) and `cd68aac` (daily
accounting, plots, examples and local legacy-calculation audit). The subsequent
closeout checkpoint contains this handoff and two boundary fixes: explicit null
status for an unrepresentable annualised summary, and validation of malformed
weight mappings. No ordinary historical calculation convention changed.

The initial implementation's hosted Python 3.11 and 3.14 jobs passed in
[run 40732786508](https://github.com/mwilczynska/financial_simulations/actions/runs/40732786508).
The expanded local suite has 43 tests. The local integration command is:

```powershell
python scripts/validate_stage1a.py --output output/validation
```

The optional `--tracker-script` argument accepts the trusted local
`portfolio_plot17.py`; its machine-specific path is intentionally not tracked.
The calculation audit confirms matching CAGR/drawdown formulas on common values
and records the existing tracker's observation-date shift and contribution-TWR
discrepancy. See [ADR 0005](decisions/0005-default-portfolio-and-tracker-audit.md).

Six optimiser comparisons across 4,023 observations passed; repeated CSV/PNG
outputs, CSV/Parquet agreement and daily account invariants passed. Exact input
and code provenance lives in ignored local manifests. The PNGs were visually
inspected, and an initial allocation-legend overlap was corrected. See the
[validation record](validation/stage-1a.md) and
[accounting methodology](methodology/portfolio-accounting.md) for details.

The earlier planned handoff write was interrupted after the implementation had
already been pushed. This document now supplies the durable project handoff.

Additional fees, Australian inflation/FX, tax, super and retirement modelling
remain unimplemented. Stage 1D follows the current Stage 1C work. Read AGENTS.md
and PLAN.md before changing behaviour.
