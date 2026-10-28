# Financial Simulations

Python tools for simulating portfolio futures and planning Australian retirement, including early retirement funded outside super and subsequent combinations of outside investments and super.

Status: Stage 1A implementation in progress. Typed portfolio specifications and
local CSV/Parquet dataset and optimiser-weight adapters are implemented and
fixture-validated. Daily accounting and the baseline report are the next checkpoint.

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
