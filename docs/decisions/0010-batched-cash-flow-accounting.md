# ADR 0010: batched many-path accounting with dated cash flows

Date: 2026-10-28. Status: accepted; implemented and reconciled against the full
ledger on randomised synthetic paths.

## Context

The full daily ledger (`simulate_portfolio`) is a Python loop over calendar
days for a single path. It is the reference implementation. Stage 1B-1D runs
many paths with the vectorised `compound_paths`, which supports no dated flows.
Stage 2 will need contributions, spending and withdrawals over 50-year
horizons across thousands of paths. A per-path calendar-day loop would take
hours, and an approximate faster method would undermine the reconciled
accounting conventions.

## Alternatives considered

1. Call the full ledger once per path: exact but slow, and it builds a pandas
   frame per path.
2. Write a separate faster flow engine with simplified conventions, for
   example applying flows only on trading days: fast but inconsistent.
3. Vectorise the same event order across paths, stepping only through marks,
   meaning observations and flow dates. Other calendar days carry the
   previous mark.

## Decision

Choose 3: `simulate_paths` in
[batch.py](../../src/financial_simulations/portfolios/batch.py). Paths share
one observation calendar and one flow schedule, and differ only in returns.
The event order, closed-date cash rules, proportional sales, shortfall
recording and pending-deposit sweep follow `simulate_portfolio` line by line.
The result stores state at marks only, so memory scales with marks rather than
calendar days. It can expand values to every calendar day on request.

## Reasons and consequences

Exactness is checked rather than argued. Randomised calendars with holidays,
year boundaries, both rebalancing policies, depletion and recapitalisation
must match the full ledger at `rtol=1e-12` on every mark and calendar day. The
full ledger remains the audit reference.

Limits: flows are path-independent amounts, and withdrawals that depend on a
path's wealth (spending rules) are not supported yet. Stage 2 withdrawal
policies will need a state-dependent extension that is checked against the
ledger in the same way. Comparison runners stay no-flow until a report defines
how drawdowns and targets treat external flows.

See the [accounting methodology](../methodology/portfolio-accounting.md) and
`tests/test_batch_flows.py`.
