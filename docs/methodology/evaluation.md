# Calendar-day evaluation and reporting (Stage 1D)

Date: 2026-10-28. Status: implemented. The first sections describe the
calendar-day evaluation pass for the single-portfolio, no-flow comparison
([ADR 0008](../decisions/0008-calendar-evaluation-and-sampling-error.md)).
[Paired, segment and holdout studies](#paired-portfolio-source-segment-and-holdout-studies)
completes Stage 1D ([ADR 0012](../decisions/0012-paired-holdout-and-segment-studies.md)).

## Purpose, inputs and conventions

The user requires a Python daily engine, the selected 40/20/20/20 portfolio and
visually reviewed PNG reports. Stage 1D evaluates the separate conditional
generators/assumptions from [resampling](resampling.md) and
[parametric simulation](parametric.md). It neither averages model probabilities
nor changes market draws when reporting settings change. The currently
supported comparison has no dated flows or additional fees; the existing
fund/proxy returns retain their embedded expenses.

Input wealth includes the same stated opening capital in every path and every
observed return. A mismatched opening value is rejected. Between
observations, repeat the last account value on calendar days. These are account
marks, not invented observed zero-return rows. Apply the explicit assumed
price index on every calendar date before computing real drawdowns. An assumed
inflation path is required for real targets/metrics. It is not observed CPI,
Australian inflation or an AUD conversion.

## Pointwise wealth percentiles and memory

For each case and date, report linear sample quantiles at 5%, 50% and 95%.
An identical positive deterministic deflator across paths commutes with these
quantiles. Nominal calendar-only percentiles carry the previous observation;
real percentiles continue to change with assumed inflation. A percentile curve
is not an individual realizable market path; saved complete paths remain a
separate report.

Retain one case's observation-wealth panel for exact quantiles. Explicit
`max_panel_mb` limits its float64 allocation (paths x valuation marks x 8
bytes), not total process RAM. Quantile sorting uses 128-column chunks, and
calendar-day path statistics use existing batches. Exceeding the panel limit
fails with an actionable error rather than silently approximating quantiles or
reducing the number of paths.

## Explicit targets and shortfalls

Evaluation settings specify `target_basis` (nominal or real), a positive
`target_multiple` m and annual target growth g > -1. For initial total capital
C and elapsed calendar days D, target T(D) = C m (1+g)^(D/365.25). These are
reporting inputs, not inferred personal goals. A 1x real target with zero
growth means maintaining opening purchasing power under the assumed deflator.

Terminal shortfall is the strict event W < T. Equality meets the target. The
gap is max(T-W,0). Report the below-target fraction, mean gap including zeros
and mean gap conditional on a miss; the last is undefined if there are no
misses. These are finite-horizon investment metrics, not retirement success.

## Drawdown and recovery

For positive opening wealth and nonnegative later marks, high water H(t) is
the cumulative maximum, and drawdown is W(t)/H(t)-1. Select the first deepest
trough, and the latest mark at its preceding high water. Repeated equal highs
reset that anchor. Recovery is the first subsequent mark at or above that
high. No return clipping or numerical equality tolerance is introduced here.

Keep `no_drawdown`, `recovered` and `unrecovered` statuses distinct. For a
recovered maximum-drawdown episode, duration is calendar days from its peak to
recovery. For an unfinished episode, observed duration ends at the horizon
and is a lower bound; there is no fabricated recovery date. Longest underwater
duration includes both closed and open episodes and includes the recovery day
in elapsed-time measurement. Flag when an open episode attains that longest
observed duration. Nominal and real metrics are calculated separately.

Example: [100,100,80,90,100,110] on consecutive dates has -20% maximum
drawdown; its anchor is the second 100 and recovery is three elapsed days later.
A flat nominal portfolio over Friday to Monday with 4% assumed annual inflation
has no nominal drawdown but real drawdown 1.04^(-3/365.25)-1, still unrecovered.

## Conditional Monte Carlo precision

Generated paths are independent draws conditional on the specified fitted
process and assumption. Serial dependence within a generated path does not
make separate path draws dependent. For N generated paths and K misses,
p=K/N, the reported plug-in fraction MCSE is sqrt(p(1-p)/N). The confidence
interval is the Wilson score interval at the explicitly selected confidence,
not a clipped Wald interval. With z the corresponding normal quantile, its
centre is (p+z^2/(2N))/(1+z^2/N) and half width is
z sqrt(p(1-p)/N+z^2/(4N^2))/(1+z^2/N). Zero observed misses does not make its
upper bound zero. It is an approximate repeated-simulation interval.

Terminal mean MCSE is sample standard deviation divided by sqrt(N), undefined
with one path. Scale currency amounts before mean/variance calculation to
avoid overflow from squaring amounts. These measures quantify simulation
sampling error only. They do not cover parameter uncertainty, reconstructed
data uncertainty, calibration bias, distributional error or model disagreement.
Keep seeds and models separate. Shared innovations between assumption cases
make those cases dependent comparisons; their intervals are not independent
evidence to combine.

Overlapping historical replays are dependent enumerations. Their fractions and
distributions are descriptive; leave all MCSE and confidence fields empty.
Do not substitute overlap counts for independent sample size.

## Validation, limitations and references

Synthetic checks cover deterministic quantiles, exact target equality, closed
and censored recoveries, repeated high-water marks, total loss, calendar-weekend
deflation, Wilson reference values and extremes, and panel-memory/input errors.
Runner tests verify unchanged market outcomes when evaluation is enabled,
byte-identical reports across batch sizes, agreement with the full calendar-day
ledger including weekends, valid PNG output and no PDF generation. See
[executed evidence](../validation/stage-1d.md).
Multi-portfolio paired comparisons, rolling holdouts and source-segment
sensitivity are covered in the study section below. Retirement rules remain
later work.

The drawdown/target definitions and reporting choices above are engineering
conventions. The [NIST Wilson interval reference](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm),
consulted 2026-10-28, supports the score-interval formula. It does not validate
financial independence assumptions or the market model.

## Configuration, outputs and report selection

An optional `[evaluation]` section adds the five explicit settings described
above. A real target requires the existing `[parametric]` inflation assumptions;
a nominal-only evaluation can run on Stage 1B empirical cases. Earlier examples
without evaluation retain their existing outputs and generator streams.
The [evaluation example](../../scenarios/examples/evaluation.toml) keeps the
Stage 1C demonstration grid and the user's selected portfolio, with the toy
target of preserving opening real wealth, zero real target growth, 95%
confidence and a 128 MiB exact-panel limit.

Each case writes every calendar day's nominal/real p05, median and p95,
observation flag/index and target curves to `wealth_percentiles.csv`.
`outcomes.csv` adds pathwise nominal/real drawdown dates, recovery statuses,
observed episode durations and open-episode flags. `risk_summary.csv` stores
terminal targets, miss/gap statistics, conditional Monte Carlo precision,
drawdown/duration quantiles and recovery fractions. The recovered-only median
duration excludes unfinished episodes and no-drawdown paths; it must not be
read as the full population's recovery median.

Exact target-day count is preserved; an unavailable complete replay produces
no percentile/risk rows, retaining its explicit missing-case summary. The
manifest records evaluation settings, row/case counts and the largest exact
panel allocation. Portfolio weights, assumptions, source hashes and the
simulation code manifest remain available from the comparison.

The percentile, terminal-CDF and drawdown PNGs show the first calibration
window, configured trace horizon/block length and first generated seed, plus
all complete replays at that setting. All Gaussian assumptions remain separate.
The shortfall PNG includes all windows/horizons/seeds. Full CSVs cover every
available case. Wealth facets share a scale and distinguish pointwise bands
from realizable paths; the existing sample-path PNG remains separate.

The terminal plot is an empirical CDF, without arbitrary histogram bin choices.
The drawdown plot's depth/duration bars are path percentiles, whereas the target
plot's bars are conditional Monte Carlo confidence intervals. Caption this
distinction explicitly. All plots are generated directly from Python as PNGs.

## Paired portfolio, source-segment and holdout studies

Two commands complete Stage 1D:
`financial-simulations paired <study.toml> --output <dir>` and
`financial-simulations holdout <study.toml> --output <dir>`. A study file names
at least two portfolios with weights and rebalancing, one reference portfolio,
the data root and calendar policy, and a `[generators]` table. That table lists
the methods (`historical_replay`, `independent`, `moving_block`, `stationary`,
`lognormal`, `garch_fhs`), the block length, paths, seeds, batch size, annual
observation basis, GARCH settings and the number of diagnostic paths. The
union of held assets is loaded jointly, so a draw is a joint row covering every
portfolio's assets. Generators always use historical fitted means. Forward
assumption grids remain a feature of `compare`.

### Paired portfolios

Within a case (window x horizon x method x seed), every portfolio compounds the
same return draws with the [batched accounting](portfolio-accounting.md). For
portfolio A against reference R on path k, the wealth ratio is
W_A,k / W_R,k at the horizon. `paired_differences.csv` reports the 5th, 50th
and 95th percentiles of ln(W_A/W_R), the share of paths with W_A > W_R (and
the share of exact ties), and the share where A's maximum drawdown is
shallower. It also reports percentiles of the drawdown difference. For
generated paths, a 95% Wilson interval for the share ahead measures
simulation error conditional on the generator. Replay windows overlap, so they
get no interval. Sharing draws removes most of the generator noise from the
difference. It does not make the generator correct. Paths are mapped onto one
observed account calendar (`calendar_window`) taken from the first H+1 dates
of that window, as in the [comparison runner](resampling.md).
`paired_summary.csv` gives each portfolio's own terminal and drawdown
percentiles. `paired_outcomes.csv` keeps every path's terminal wealth and
drawdown for every portfolio.

### Source segments

Each `[[windows]]` entry can set `provenance = "observed"` or
`"reconstructed"`, and optionally `provenance_assets` to scope the check. The
run fails unless every return interval of every scoped asset carries that
label (see the [adapter method](data-adapters.md#common-date-policy-and-per-return-provenance)).
Splice intervals are `mixed`, so a window can only be observed if it opens on
or after the last asset's switch date. `window_statistics.csv` records, per
window and asset, the interval counts by provenance class and the
multi-observation intervals, plus annual log growth (mean log return x basis),
annual volatility, volatility drag, skewness, excess kurtosis, worst day, the
0.1% and 1% quantiles, summed squared-return ACF and rolling-volatility
percentiles. `window_correlations.csv` gives log-return correlations. Running
the same generators on separate windows shows how far conclusions depend on
reconstructed history.

### Leveraged-risk diagnostic

`tail_diagnostics.csv` computes the same daily statistics for the calibration
sample (`method = historical`) and for each generator's paths. It covers every
asset and every portfolio's daily log growth, and uses the first
`diagnostic_paths` paths of the first seed at the longest horizon. For daily
log returns x:

- excess kurtosis is m4/m2^2 - 3, using pooled central moments;
- `squared_acf_sum_21` sums, over lags 1 to 21, the average across paths of
  each path's autocorrelation of x^2;
- rolling volatility is the population standard deviation over 63 consecutive
  observations, times sqrt(basis), pooled before taking percentiles;
- volatility drag is (mean(exp(x)-1) - mean(x)) x basis.

A Gaussian generator gives excess kurtosis near zero and no squared-return
autocorrelation, whatever the sample. Matching the sample on these statistics
is necessary, but not sufficient, for a generator to represent the risk of
daily-reset leverage. `tail_diagnostics.png` shows them for the reference
portfolio and its holdings.

### Rolling holdouts

The origins are the first common observation on or after 1 January of each year
from `first_origin_year`, in steps of `step_years`. For origin o, calibration
returns are those ending on dates from the first observation of year
(o - `calibration_years`) up to and including o (`rolling`), or from the data
start (`expanding`). The holdout is the next H returns, mapped onto their
actual dates. A fold without H future returns is recorded as
`incomplete_holdout`. One set of generators fitted at an origin serves every
horizon. With `initial_variance = "last_fitted"`, GARCH-FHS starts from the
variance filtered up to the origin, which makes it a conditional forecast.

For each portfolio and generator, the realised value y and N generated values
g_i give the mid-rank PIT, (#{g_i < y} + 0.5 #{g_i = y}) / N. It is computed
for terminal wealth, maximum drawdown (a negative number: a low PIT means the
realised drawdown was deeper than most simulated ones) and realised annualised
volatility. `holdout_summary.csv` reports, per horizon, method, portfolio and
metric:

- the number of folds and the mean PIT;
- the shares of PIT below 0.05 and above 0.95, and the central 90% coverage;
- the KS distance max_i max(i/n - u_(i), u_(i) - (i-1)/n) from uniform;
- the number of non-overlapping folds (every ceil(H/basis/step) origins) and
  their coverage.

These figures are descriptive. Holdouts at H = 1,260 overlap heavily, so they
are not independent tests. Each fold row records the observed fraction of its
calibration and holdout intervals for the portfolio's assets.
`holdout_generated.csv` stores every generated path's three metrics, so PIT
values can be recomputed independently. `holdout_pit.png` plots the PIT ECDF
against the diagonal, and `holdout_timeline.png` the generated annualised
growth bands against realised growth.

### Validation and limitations

`tests/test_studies.py` covers paired outcomes recomputed through the full
ledger for replay, stationary and lognormal paths, for every portfolio, with
byte-identical outputs across batch sizes. It checks Wilson-interval scope,
provenance enforcement (failure and success cases), segment counts with
multi-step intervals, and diagnostic coverage. For holdouts it checks that
perturbing returns after a fold's holdout leaves the fold unchanged (no
look-ahead), the incomplete-fold status, PIT recomputation, realised-path
reconciliation and hand-checked PIT/KS/kurtosis values.
`scripts/validate_studies.py` repeats the recomputations on companion data
and adds a batched cash-flow reconciliation. The executed results are in the
[validation record](../validation/stage-1d.md).

Limitations: the studies use historical means fitted to each window.
Pre-2009 leveraged series are reconstructions, so holdout scores there
partly test the dataset project's model. The reference default portfolio was
chosen by an optimiser on this history. Generators fitted on 10 years of
history inherit that decade's mean, which is the main source of PIT
miscalibration for terminal wealth. No metric combines generators.
