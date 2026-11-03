# ADR 0044: run every compared spending strategy on every shared path

Date: 2026-11-02.

Status: accepted; implemented and tested. The comparison section and per-strategy tabs (stages 5 and 6 of the
[strategy comparison plan](../strategy-comparison-plan.md)) are proposed and not implemented.

## Context

[ADR 0043](0043-compared-spending-strategies-in-the-plan.md) let a plan list the spending strategies to compare,
but a run still used only the first. The user requires every ticked strategy to run on all ledger paths, with no
reduction in path count, and every other input held constant.

## Alternatives considered

- **Separate runs per strategy**, each drawing its own paths. Simple, but differences between strategies would mix
  the strategy's effect with sampling noise from different markets.
- **Shared draws, one pass per strategy** over all paths. Paired, but each path's market draw would be gathered
  and sent to the workers once per strategy.
- **Shared draws, every strategy per path inside each worker task.**

## Decision

The third alternative.

- `run_ledgers` takes one plan per strategy (`strategy_plan`). Each worker task handles a chunk of paths; for
  each path it gathers the market draw once and runs every strategy's ledger and summary on it. The automatic
  worker count uses paths × strategies as the number of tasks.
- `run_plan` builds one `PlanRun` per strategy (`_strategy_run`): its own representative path, bands, tables,
  monthly series and notes, sharing the portfolio analysis and market. It returns the first compared strategy's
  `PlanRun`, whose `strategies` field holds all of them by rule, so existing callers keep working.
- Output: with one strategy the plan folder keeps its layout. With several, shared portfolio files stay at the top
  and each strategy's ledger, CSVs and retirement PNGs go in `strategies/<rule>/`; `manifest.json` lists each
  strategy's folder and representative path. A run removes the other layout's files.
- The app gains a strategy selector above sections 4 and 5, with separate widget choices per strategy, until the
  comparison section and tabs replace it.

## Reasons and evidence

- **User requirements:** every ticked strategy on all paths; other inputs constant.
- **Research finding (Monte Carlo practice; PLAN.md):** comparing alternatives on common random numbers removes
  most sampling noise from their differences.
- **Verified:** on every path, every strategy reaches the retirement date with the same wealth, because the ledger
  is identical until then (`tests/test_plan.py::test_every_compared_strategy_runs_on_the_same_draws_and_writes_its_own_folder`).
- **Measured (2 November 2026):** the default plan extended to 50 years, 1,000 ledger paths and all four
  strategies took 484 s in total: 8 s for the portfolio analysis, 469 s for the 4,000 daily ledgers on the
  automatic worker count, and 7 s to summarise and build results. The results held about 60 MB per strategy
  (240 MB in all), mostly the monthly series for every path.

## Consequences

- Run time grows in proportion to the number of strategies ticked. The Retirement tab says so.
- Memory for results is about 60 MB per strategy at 1,000 paths and 50 years, below the 300 MB at which the plan
  proposed storing monthly series more compactly.
- Splitting each path's ledger at retirement and running only the retirement years per strategy would save the
  pre-retirement share of the work. For the default plan that share is about one year in fifty, so it is not done.

## Implementation and validation

- **Code:** `retirement/paths.py` (`_run_chunk`, `run_ledgers`), `retirement/run_plan.py` (`PlanRun.strategies`,
  `_strategy_run`, `STRATEGY_FILES`), `reporting/plan.py` (`write_portfolio_plots`, `write_retirement_plots`),
  `ui/app.py` (`strategy_key`, the strategy selector).
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:** the paired-draws and folder-layout test above;
  `tests/test_plan.py::test_app_compares_ticked_strategies_and_ignores_a_stale_cores_choice` runs three strategies
  in the app and switches the strategy shown; the full suite.
