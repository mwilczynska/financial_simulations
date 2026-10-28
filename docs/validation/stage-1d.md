# Stage 1D validation

Date: 2026-10-28. Status: initial single-portfolio/no-flow evaluation and report
implemented. All 79 local tests pass on Python 3.14. This is not a claim that
all Stage 1D work has been completed.

Tests cover exact pointwise quantiles and target equality, completed versus
unrecovered drawdowns, repeated high-water marks, total loss and longest
underwater durations. Friday-to-Monday checks show flat nominal wealth but
three days of real drawdown under assumed inflation. Wilson reference values,
zero/all misses, shrinking intervals as path count increases, replay fields
without inference, invalid inputs and exact-panel memory limits are checked.

Additional tests validate growing targets on a leap-year calendar, finite mean
and mean MCSE for amounts near 1e300, unchanged market outcomes when reporting
is enabled, byte-identical reports across batch sizes and nominal/real recovery
agreement with the full daily ledger. Real integration covers a weekend gap
and retains every daily deflator mark. Earlier Stage 1A/1B/1C tests still pass.

## Companion-data experiment and visual review

Run `python scripts/validate_stage1b.py --experiment scenarios/examples/evaluation.toml --output output/stage1d`.
The example retains the selected 40/20/20/20 portfolio, annual rebalancing,
illustrative USD 100,000 opening capital, two calibration windows, three
observation horizons, two seeds and the Stage 1C demonstration grid. Its toy
target is 1x opening real capital, with zero real target growth and explicit
95% confidence for conditional Monte Carlo intervals.

The first executed run contains 90 cases and 54,564 paths, with 89 evaluable
cases and 171,873 calendar-day percentile rows. The shorter source window still
has no complete 2,520-observation replay; that case gets no invented evaluation
rows. The largest exact observation panel is 30,332,672 bytes, within the
explicit 128 MiB panel limit. All 15 saved nominal paths reconcile through the
full daily ledger with zero measured absolute wealth difference. All 6,144
base/high-inflation pairs remain identical nominally.

Five new PNGs were generated directly from Python and inspected: nominal and
real percentile facets, terminal empirical CDFs, target shortfalls and
drawdown/recovery. The first review found crowded title/caption spacing; fixed
header alignment was rendered and inspected again. Wealth panels share a
stated logarithmic scale. Pointwise bands, complete paths, path percentile
ranges and Monte Carlo intervals have distinct labels. Missing replay windows
and censored recovery durations are explicit. No PDFs were created.

The expanded companion audit passed terminal quantiles against case summaries,
calendar-only nominal carry, real deflation, target counts, interval scope and
saved-path calendar recovery. Final execution evidence and clean-code/CI
provenance are recorded in the handoff as the checkpoint closes.

The kernel checkpoint `8f33304` passed Python 3.11/3.14 hosted CI in
[run 40773485891](https://github.com/mwilczynska/financial_simulations/actions/runs/40773485891).

## Remaining Stage 1D work

Paired multi-portfolio reporting, rolling calibration/holdout studies and
observed-versus-reconstructed source-segment sensitivity remain unimplemented.
Increasing path count does not settle those questions. This reporting pass
does not introduce personal targets, Australian CPI/FX, tax, super or retirement
withdrawal rules. Private inputs, market data copies and reports remain ignored.

See [methodology](../methodology/evaluation.md) and
[ADR 0008](../decisions/0008-calendar-evaluation-and-sampling-error.md).
