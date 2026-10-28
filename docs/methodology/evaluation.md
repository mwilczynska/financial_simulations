# Calendar-day evaluation and reporting (Stage 1D)

Date: 2026-10-28. Status: evaluation kernel and synthetic checks implemented;
runner integration and PNG reporting are in progress. This does not establish
completion of all Stage 1D validation, including rolling holdout studies.

## Purpose, inputs and conventions

The user requires a Python daily engine, the selected 40/20/20/20 portfolio and
visually reviewed PNG reports. Stage 1D evaluates the separate conditional
generators/assumptions from [resampling](resampling.md) and
[parametric simulation](parametric.md). It neither averages model probabilities
nor changes market draws when reporting settings change. The currently
supported comparison has no dated flows or additional fees; the existing
fund/proxy returns retain their embedded expenses.

Input wealth includes the opening mark and every observed return. Between
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
Integration, artifact reconciliation and visual review remain in progress.
Multi-portfolio paired comparisons, rolling holdout exercises and observed-data
segment sensitivity remain further Stage 1D work; retirement rules remain later.

The drawdown/target definitions and reporting choices above are engineering
conventions. The [NIST Wilson interval reference](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm),
consulted 2026-10-28, supports the score-interval formula. It does not validate
financial independence assumptions or the market model.
