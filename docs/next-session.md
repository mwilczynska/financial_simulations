# Stage 1A closeout and next-session handoff

Updated: 2026-10-28, following the scheduled closeout review.

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

No Stage 1B generators, additional fees, Australian inflation/FX, tax, super or
retirement modelling have been started. Wait for further user instruction before
starting Stage 1B. Read AGENTS.md and PLAN.md before changing model behaviour.
