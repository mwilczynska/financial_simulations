# Calendar-day evaluation and reporting (Stage 1D)

Date: 2026-10-28. Status: the initial evaluation/reporting pass is implemented
for the existing single-portfolio, no-flow comparison. This does not establish
completion of all Stage 1D work, including paired multi-portfolio reporting,
rolling holdout studies and source-segment sensitivity.

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
Multi-portfolio paired comparisons, rolling holdout exercises and observed-data
segment sensitivity remain further Stage 1D work; retirement rules remain later.

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
