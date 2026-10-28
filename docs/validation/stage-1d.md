# Stage 1D validation

Date: 2026-10-28. Status: Stage 1D complete. The first sections record the
initial single-portfolio evaluation pass, run when 79 tests existed. The
[completion section](#stage-1d-completion-studies-garch-fhs-and-batched-flows)
records the paired, segment, holdout, tail-diagnostic, GARCH-FHS and
batched-flow evidence.

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

Run `python scripts/validate_experiment.py --experiment scenarios/examples/evaluation.toml --output output/stage1d`.
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
saved-path calendar recovery. A fresh run from clean implementation commit
`9b57ed2` passed every check, recording `working_tree_dirty: false` and package
Python-source SHA-256
`defefec95b9855ea862c6419085801a7f1c1f8484086a29bc64a7d5c4d04fed2`.

The kernel checkpoint `8f33304` passed Python 3.11/3.14 hosted CI in
[run 40773485891](https://github.com/mwilczynska/financial_simulations/actions/runs/40773485891).
The full report implementation `9b57ed2` passed both hosted jobs in
[run 40775393820](https://github.com/mwilczynska/financial_simulations/actions/runs/40775393820).

## Remaining work after the initial pass (since completed)

At the time of the initial pass, paired multi-portfolio reporting, rolling
calibration/holdout studies and source-segment sensitivity were still open.
They are now implemented; see the completion section below. Personal targets,
Australian CPI/FX, tax, super and retirement withdrawal rules remain outside
Stage 1D. Private inputs, market data copies and reports remain ignored.

See [methodology](../methodology/evaluation.md) and
[ADR 0008](../decisions/0008-calendar-evaluation-and-sampling-error.md).

## Stage 1D completion: studies, GARCH-FHS and batched flows

Local run on 2026-10-28: Python 3.14.0, NumPy 2.5.4, pandas 3.1.0, Matplotlib
3.11.2, PyArrow 26.0.0 and pytest 9.2.0. The suite has 111 tests, including
new files `test_batch_flows.py` (12), `test_volatility.py` (8) and
`test_studies.py` (9), and extensions to the adapter and comparison tests. All
pass. `scripts/check_repository.py` passes and now runs in CI. The validator
script was renamed from `validate_stage1b.py` to `validate_experiment.py`;
commands in earlier records use the new name.

### Commands

```powershell
.\.venv\Scripts\python.exe scripts/validate_experiment.py --experiment scenarios/examples/evaluation.toml --output output/stage1d
.\.venv\Scripts\python.exe scripts/validate_studies.py
```

The second command runs the paired and holdout example studies and then
audits them, unless `--reuse` is given. It writes
`output/stage1d-studies-validation.json`.

### Comparison with GARCH-FHS

`evaluation.toml` now adds `[volatility] model = "garch_fhs"`. The run has 138
cases and 79,140 paths, with 137 evaluable cases and 265,489 calendar-day
percentile rows. All 18 saved traces, now including GARCH-FHS paths,
reconcile through the full daily ledger with zero measured difference. Across
both models, 12,288 deflator-only twin pairs have identical nominal outcomes.
Percentile, carry, deflation, target-count, interval-scope and recovery audits
all pass. Deflator-only twins are labelled "(deflator only)" in every plot.

### Paired, segment and diagnostic study (`paired.toml`)

Three portfolios compound identical draws: the default, the same mix through
unlevered series, and the equal-weight global portfolio. The windows are
observed-only 2009-06-26 to 2025-12-31 (all 4,154 intervals observed for all
nine assets), reconstructed-only 1970-2006-02-06 (enforced for the default's
four assets) and full 1970-2025, all under `common_dates`. The run has 36 cases
and 82,107 paths. The reconstructed window drops 220-435 source dates per asset
and has 438 multi-observation intervals; the observed window drops none.

The audit regenerates 108 paths (three per case) through the public samplers
and generators and recomputes each portfolio through the full daily ledger.
Terminal wealth matches exactly (maximum relative error 0). Drawdowns match at
1e-10. Summary quantiles, paired win shares and provenance counts are
recomputed and agree. No PDFs are created.

Results at 2,520 observations (conditional, nominal USD; generators shown
separately):

| Window | Generator | Default median | Default 5th pct | Unlevered ahead | Equal-weight ahead |
| --- | --- | --- | --- | --- | --- |
| Observed 2009-2025 | Replay (1,635 windows) | 402,506 | 293,518 | 0% | 0% |
| Observed 2009-2025 | Stationary L=63 | 615,684 | 207,637 | 1.4% | 0.0% |
| Observed 2009-2025 | GARCH-FHS | 723,652 | 179,074 | 2.3% | 1.2% |
| Reconstructed 1970-2006 | Replay (6,296 windows) | 411,065 | 256,972 | 12.0% | 10.7% |
| Reconstructed 1970-2006 | Stationary L=63 | 392,832 | 130,025 | 26.8% | 29.5% |
| Reconstructed 1970-2006 | Lognormal | 369,123 | 120,782 | 31.8% | 32.8% |
| Reconstructed 1970-2006 | GARCH-FHS | 335,868 | 105,432 | 34.6% | 37.9% |
| Full 1970-2025 | Stationary L=63 | 387,779 | 138,739 | 16.6% | 15.8% |

The unlevered same mix had a shallower maximum drawdown than the default on
essentially every path, in every window and generator. The observed window's
historical means (`USLCAP3X` 28% annual log growth against 9% reconstructed)
drive most of the difference between windows.

Tail diagnostic (`tail_diagnostics.csv`, `tail_diagnostics.png`). For the
default portfolio in the full window:

- excess kurtosis of daily log growth: 15.4 in the sample, 8.6 for the
  stationary bootstrap, 0.24 for the lognormal model, 46.8 for GARCH-FHS;
- summed squared-return autocorrelation over 21 lags: 0.87 sample, 1.92
  bootstrap, 0.67 lognormal, 2.59 GARCH-FHS;
- 95th percentile of 63-observation volatility: 33.6% sample, 34.7%
  bootstrap, 30.8% lognormal, 37.8% GARCH-FHS.

For `USLCAP3X` itself, the lognormal model's squared-return autocorrelation is
0.01, against 1.5 in the sample. Its 0.1% daily quantile is -9.7% against
-18.3%. GARCH-FHS overshoots the most extreme days. The 19 October 1987
standardised residual (-13.5 sd in the reconstructed fit) can be drawn in a
high-variance state, so the reconstructed-window portfolio reaches a -66%
worst day against -25% in the sample. This is documented as a limitation in
the [volatility method](../methodology/volatility.md).

### Rolling holdout study (`holdout.toml`)

The study uses rolling 10-year calibration with origins each January from
1980, 252- and 1,260-observation holdouts, and 256 paths per generator. GARCH
starts from the last filtered variance. It produces 45 one-year and 41
five-year scored origins. Six are incomplete because the holdout would run
past 2025-12-31: one one-year and five five-year. The audit reconciles all 774 scored fold rows' realised
terminal wealth and drawdown through the full daily ledger, and recomputes
every PIT from `holdout_generated.csv`. It regenerates path 0 for each method
and portfolio at 6 sampled origins (99 paths, matching exactly) and confirms
that every calibration ends at its origin. A synthetic perturbation test
confirms that future data cannot change an earlier fold.

Central 90% coverage for the default portfolio over one-year holdouts (45
origins):

| Generator | Terminal wealth | Maximum drawdown | Realised volatility |
| --- | --- | --- | --- |
| Stationary L=63 | 89% | 71% | 67% |
| Lognormal | 91% | 51% | 38% |
| GARCH-FHS | 91% | 73% | 78% |

For five-year holdouts (41 overlapping origins, 9 non-overlapping), the
figures are 93/59/56%, 95/51/29% and 95/71/76% respectively. Lognormal
realised-volatility PIT values fall below 0.05 in 44% of one-year origins and
above 0.95 in 18%: its fixed-variance distribution is too narrow. The
unlevered and global portfolios show the same pattern: lognormal
realised-volatility coverage is 11% for both at one year, against 60-71% for
GARCH-FHS. These coverages are descriptive. Holdouts before 2009 use
reconstructed leveraged series, and the default portfolio was selected on
this history.

### Batched cash-flow engine on companion data

Using 64 stationary-bootstrap paths from the 2010-2025 default sources over
2,520 observations, with 161 dated flows (monthly deposits, often on closed
dates; quarterly before-return withdrawals; and a final oversized
withdrawal), `simulate_paths` matches `simulate_portfolio` on all 3,657
calendar days for every path, with maximum absolute difference 0.0.
Shortfalls agree at every mark. Throughput: 1,000 paths x 12,600
observations with 580 monthly flows took 3.75 s batched. The full ledger took
1.49 s per path, extrapolating to about 25 minutes.

### Visual review

These PNGs were opened and inspected:

- `paired_terminal.png`, `paired_differences.png`, `segment_statistics.png`
  and `tail_diagnostics.png`;
- `holdout_pit.png` and `holdout_timeline.png`;
- the re-rendered comparison PNGs.

The first review found y-axis labels running into neighbouring panels, single
tick labels on narrow log axes, a truncated portfolio label, a subtitle
crowding the legend, clipped deflator-twin labels and an inaccurate PIT
caption. All were fixed and re-rendered.
