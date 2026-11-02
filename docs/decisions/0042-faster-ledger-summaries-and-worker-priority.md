# ADR 0042: faster ledger summaries, more ledger workers at below-normal priority

Date: 2026-11-02.

Status: accepted; implemented and tested.

## Context

The user plans to compare up to four spending strategies on every ledger path, with no reduction in path count
([strategy comparison plan](../strategy-comparison-plan.md), stage 2). Run time is the constraint. The user asked
for more cores to be used, with a check so the rest of the computer is not slowed down.

Measured on 2 November 2026 (default plan extended to 40 years, one core):

- the daily ledger took about 0.78 s per path;
- summarising each path in its worker (`_summarise`) took about 0.93 s per path, more than the ledger. Two pandas
  patterns caused most of it: `account_flows` walked the whole event log with `iterrows`, and `_summarise` rebuilt
  `daily.index.date` once per financial year;
- inside the ledger, ranking parcels at each sale converted dates and recomputed indexation factors about 33,000
  times per path.

The pool used at most 12 worker processes at normal priority on a machine with 32 hardware threads (24 cores).

## Alternatives considered

- **Restructure the ledger** (vectorised parcel ranking, skipping quiet days). Larger gains are possible, but the
  arithmetic and order of operations would change and need fresh validation of every tax result.
- **Reserve cores** for other programs by using a small fixed worker count. This wastes idle cores and still
  competes with whatever runs on the cores it does use.
- **Lower worker priority and use most hardware threads**, keeping every result bit-for-bit identical.

## Decision

The third alternative.

- **Summaries:** `account_flows` selects the four transfer event kinds before looping; financial years are computed
  for the whole index at once (`_financial_years`); `_summarise` builds `daily.index.date` once.
- **Ledger:** parcel ranking caches 12-month anniversaries, quarter numbers and indexation factors for the run
  (`twelve_month_anniversary` and `indexation_for_quarters` in `rules/au/tax.py`, shared with the rule functions);
  the rule set is looked up only when the financial year changes; the daily frame is built from columns.
- **Workers:** `worker_count` chooses the count (*Calculation cores* in the app or `FINANCIAL_SIMULATIONS_WORKERS`
  when set; otherwise the smaller of half the paths and the hardware threads less 4, reduced to leave 4 GB of
  physical memory at 200 MB per worker). Workers set themselves to below-normal priority when they start.

## Reasons and evidence

- **User requirements:** keep every path; use more cores; protect the rest of the computer.
- **Verified:** full ledger outputs (daily frame, event log, annual records, outstanding items) and per-path
  summaries on 48 fixed 40-year paths across the fixed, Guyton–Klinger, Vanguard and percentage rules were exactly
  equal before and after.
- **Measured (one core):** ledger about 0.78 → 0.73 s per path; summary about 0.93 → 0.27 s per path; the worker's
  whole step about 1.7 → 1.0 s per path.
- **Two candidate changes were rejected because results changed in the last bits:** replacing the valuation loop
  with built-in `sum()` (compensated summation since Python 3.12), and reading returns as Python floats instead of
  NumPy scalars (which switched other `sum()` calls in the ledger to compensated summation).
- **Engineering judgement:** priority, not core reservation, is how the operating system protects interactive
  work. Below-normal workers take only cycles that normal-priority programs leave idle.
- **Worker memory (measured):** one worker running 50-year ledgers peaked at a 142 MB working set and 123 MB
  committed.

## Consequences

- A run uses up to 28 workers on the development machine instead of 12, and is about 2.6 times faster from cold. When another normal-priority job is
  running (for example a second simulation), the ledgers slow down rather than slowing it.
- The ledger itself is only about 7% faster; it remains the larger part of each path's cost and the target for any
  later restructuring.
- 28 idle workers hold about 2–3 GB of memory between runs; *Calculation cores* can lower that.
- **Fix (2026-11-02, same day):** the *Calculation cores* label first included the automatic count, which changes
  with free memory; Streamlit then returned a stale label as the choice and the page failed. The label is now fixed
  (see [plan-portfolios.md](../validation/plan-portfolios.md)).

## Implementation and validation

- **Code:** `retirement/ledger.py`, `retirement/flows.py`, `retirement/paths.py`, `retirement/run_plan.py`,
  `rules/au/tax.py`, `ui/app.py`.
- **Methodology:** [retirement-ledger.md](../methodology/retirement-ledger.md),
  [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:** `tests/test_plan.py::test_worker_count_honours_requests_and_limits_the_automatic_count`,
  `tests/test_plan.py::test_ledger_workers_run_below_normal_priority`,
  `tests/test_projection.py::test_cached_cgt_dates_and_factors_match_the_rule_functions`; the full suite.
- **Benchmark (idle machine, each run after a two-minute cool-down):** 280 paths of a 50-year plan.

  | Code | Workers | Time |
  | --- | --- | --- |
  | Original | 12 (the old cap) | 66.6 s |
  | Original | 28 | 47.2 s |
  | Changed | 12 | 38.3 s |
  | Changed | 20 | 31.2 s |
  | Changed | 28 (the new automatic count) | 25.2 s |

  The default run is 2.6 times faster: the code changes give 1.7 times at 12 workers, and 28 workers give a further
  1.5 times. Each figure is a single run. Back-to-back runs without a cool-down were up to twice as slow, because
  this laptop throttles under sustained all-core load, so long runs will gain less than these figures.
- **Benchmark (contended):** while the user ran another simulation with 12 normal-priority workers, the same
  280 paths took 122 s on 12 workers (123 s with the original code at normal priority), 108 s on 16, 99 s on 22 and
  94 s on 28: the below-normal workers gave way to the other simulation.
