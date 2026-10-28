# Financial Simulations

Python tools for simulating portfolio futures and planning Australian retirement, including early retirement funded outside super and subsequent combinations of outside investments and super.

Status: Stage 1A is implemented: typed portfolio inputs, local CSV/Parquet and
optimiser adapters, daily holdings/cash accounting, annual rebalancing or
buy-and-hold, dated contributions/withdrawals, static PNG plots and inspectable
baseline reports. Synthetic tests and daily reconciliation with the companion
optimiser are recorded in [validation evidence](docs/validation/stage-1a.md).
Stochastic generators and Australian retirement rules remain planned.

## Development

Use Python 3.11 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,parquet]'
.\.venv\Scripts\python.exe -m pytest
```

Parquet support is optional; omit `parquet` for CSV-only use. The
[adapter methodology](docs/methodology/data-adapters.md) records the implemented
scope, strict calendar policy, supported aliases and validation evidence.

## Run the first baseline

Keep `financial_datasets` and optionally `portfolio_optimisation` as sibling
checkouts, as described in [the plan](PLAN.md). From this repository:

```powershell
.\.venv\Scripts\python.exe -m financial_simulations run scenarios/examples/baseline.toml --output output/baseline --parquet
.\.venv\Scripts\python.exe -m financial_simulations run scenarios/examples/optimiser_baseline.toml --output output/optimiser-baseline
.\.venv\Scripts\python.exe -m financial_simulations run scenarios/examples/cash_flows.toml --output output/cash-flows
```

Each run writes `wealth.png`, `drawdown.png` and `allocation.png` directly from
Python/Matplotlib. These are the first-pass plot deliverables; interactive plots
are a later extension. No PDFs are generated. The local HTML report embeds the
same images and links the full daily ledger, source observations, monthly/annual
summaries and a versioned input/code manifest. All generated output stays ignored.

The examples use nominal USD. The default is the user-selected `Optimised CURRENT`
portfolio from `portfolio_plot17.py`: `USLCAP3x` 40%, `ITT3x` 20%, `GOLDPM2x` 20%
and `COMM` 20%, with annual calendar-year rebalancing. This label records the
user's selection, not a new claim of optimality. Existing daily fund returns
retain their embedded financing/expenses. An equal-weight global four-asset
comparator is available in `equal_weight_baseline.toml`. The default's
2010-2025 window uses matching source observation calendars. The loader rejects
mixed calendars and bad data rather than filling or dropping trading rows.
These historical results do not implement Australian purchasing power or tax.

Edit the TOML examples for other weights, windows, policies or dated cash flows.
Paths in TOML resolve relative to that file. A contribution uses a positive
amount; a withdrawal request uses a negative amount. Initial cash is a retained
reserve. On closed-market dates withdrawals can spend only cash; any shortfall
is recorded without borrowing or automatic retry. See the
[accounting methodology](docs/methodology/portfolio-accounting.md) for timing.

## Reproduce the checks

The unit suite uses only small synthetic fixtures; companion data is not needed.
The integration script below needs both sibling checkouts and Parquet support:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts/validate_stage1a.py --output output/validation
```

The script checks repeated CSV/PNG outputs, CSV/Parquet agreement, daily account
invariants, the cash-flow example and both policies against the actual optimiser
for the default, equal-weight comparator and imported portfolio. Its local evidence
is `output/validation/validation.json`. An optional `--tracker-script` argument
audits selected calculation functions from a trusted local `portfolio_plot17.py`
without running its top-level downloads, plotting or configuration. The
[tracker audit](docs/decisions/0005-default-portfolio-and-tracker-audit.md) explains
which conventions reconcile and which require different treatment.
The declared numerical tolerances and observed results are in the validation record.
GitHub Actions runs the synthetic suite on Python 3.11 and 3.14 without copying
companion data into this repository.

For the exact tested Windows/Python 3.14 runtime/test versions, install
`requirements-dev.lock.txt` before the editable package:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Other platforms/Python versions should resolve the compatible ranges from
`pyproject.toml`; the snapshot is not a universal platform lock. Each run records
its actual dependency versions.

## Project principles

- Keep daily returns throughout calibration, path generation and portfolio/account compounding, consistent with [financial_datasets](https://github.com/mwilczynska/financial_datasets).
- Consume candidate asset weights from [portfolio_optimisation](https://github.com/mwilczynska/portfolio_optimisation) or a manually specified portfolio.
- Compare historical replay, joint daily block resampling and statistical Monte Carlo rather than relying on one generator.
- Separate market paths from portfolio accounting, personal accounts, Australian rules and spending policies.
- Start retirement modelling with one Australian tax resident, then add couples with separate account ownership and super access dates.
- Write detailed methodology and decision records as the models develop, including assumptions, alternatives, reasons, references, validation and limitations.
- Commit and push coherent, reviewed checkpoints regularly. Keep private financial inputs and generated personal reports out of Git.

## Read the design

- [Project plan](PLAN.md): staged implementation, data contracts and validation requirements.
- [Literature review](docs/literature-review.md): primary research, modelling implications and limitations of the review.
- [Methodology register](docs/methodology/README.md): detailed documentation standards, topic roadmap and current status.
- [Daily-engine methodology](docs/methodology/daily-engine.md): calendars, compounding, scheduled cash flows, leverage, costs and worked examples.
- [Decision records](docs/decisions/README.md): dated explanations of material choices, alternatives, evidence and consequences.

Monthly and annual charts or tables will be summaries derived from daily paths. Cash flows may occur monthly, annually or on other configured dates; the underlying accounting remains daily.
