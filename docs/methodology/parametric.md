# Correlated daily log-return benchmark (Stage 1C)

Status on 2026-10-28: implemented for the no-flow, common-currency comparison
runner. Synthetic checks and the companion-data experiment have been executed;
see [validation evidence](../validation/stage-1c.md). This is an initial
conditional benchmark, not a fitted inflation model or retirement engine.

## Purpose and provenance

This benchmark separates a persistent return assumption from daily market
shocks. The user requires daily simulation, the selected 40/20/20/20 portfolio
and Python-generated PNGs. The Gaussian distribution, sample covariance with
one degree of freedom removed, and an explicit 252-observation annual basis
are engineering choices, not claims that returns are Gaussian or forecasts.
Data enters through the existing strict, hashed
[dataset adapter](data-adapters.md). Returns already include the selected
fund/proxy series' embedded expenses and leverage; neither is applied again.

## Equations and annual conventions

For joint daily simple returns r, fit x = ln(1+r), sample log mean mu and sample
log covariance S with denominator n-1. At least two observations and r > -1
are required. Draw independent daily vectors z with standard normal components,
then x = mu + A z and r = exp(x)-1, with A A' = S. Correlation across assets is
retained in log-return units; serial dependence and volatility clustering are
absent. One observed interval is one model step, including a Friday-to-Monday
return. No annual draws are spread across days.

The annual basis T is an explicit observation count, not elapsed calendar time.
For each asset with daily log variance v:

| Input convention | Daily log mean |
| --- | --- |
| `historical` | fitted sample log mean |
| `geometric_growth` g | ln(1+g)/T |
| `expected_compounded_return` R | ln(1+R)/T - v/2 |
| `annualised_daily_arithmetic` a | ln(1+a/T) - v/2 |

Geometric growth describes the median compounded gross return over T
independent observations for one asset. Expected compounded return describes
its expected gross return over those observations. Annualised daily arithmetic
means T times its expected daily simple return. These inputs are not
interchangeable and are not the expected return of a periodically rebalanced
portfolio. For example, an 8% expected compounded return with annual log
variance 0.04 gives daily mu = (ln(1.08)-0.02)/252; an 8% geometric input gives
mu = ln(1.08)/252.

The implied daily simple mean is exp(mu_i+S_ii/2)-1; simple covariance is
exp(mu_i+S_ii/2) exp(mu_j+S_jj/2) [exp(S_ij)-1]. These identities provide
independent checks of simulated moments. The multivariate expression follows
by applying the Gaussian exponential moment identity to x_i+x_j.

## Algorithm, reproducibility and error boundaries

Use a symmetric eigendecomposition to form A, allowing singular covariance.
Negative eigenvalues beyond 100 k epsilon max(abs(S)) fail, where k is asset
count. Only smaller negative roundoff is changed to zero; record the maximum
eigenvalue correction and effective covariance. Asymmetric or nonfinite inputs
fail. This numerical repair is not return clipping or covariance estimation.

Use PCG64 with SeedSequence `[seed, 4, horizon, path_id]`. Excluding the drift,
inflation and portfolio weights makes the innovations common across assumption
cases for a fitted model. A path's draws do not depend on batch size or the
order in which paths are requested. Reproduction also requires the saved
factor, code and NumPy/numerical environment; seeds alone do not promise
bitwise identity across platforms or library versions.

Exponentiation that produces nonfinite simple returns or rounds a gross return
to zero fails explicitly. Values are never silently clipped or redrawn.
The generator has mathematical support above -100%, so a source containing a
total loss cannot be fitted under this model.

## Validation and limitations

Synthetic checks cover hand-calculated log moments, a one-asset fit, perfectly
correlated/singular returns, deterministic 8% compounding, all three annual
conversions, fixed-seed log/simple moment recovery, common innovations and
numerical/domain failures. The 200,000-observation moment check is a software
check under known model inputs, not validation of a market distribution.

Historical means are noisy, and calibration windows may include reconstructed
or synthetic fund history. This model does not reproduce jumps, regimes,
serial dependence, changing covariance or uncertain long-run parameters.
Outer parameter sampling, heavy tails, FX and retirement rules are deferred.

## Persistent assumptions and assumed purchasing power

The comparison TOML optionally pairs a `[parametric]` table with named
`[[assumptions]]` tables. Every assumption records its convention, annual return
inputs when applicable, annual inflation rate and rationale. Overrides must
specify exactly the portfolio assets, with explicit alias resolution and no
duplicates. All Gaussian cases in a window share its fitted daily covariance.
The log mean and inflation assumption remain fixed for the entire path. The
grid is a set of alternatives, with no probability weights or averaging.

The supplied `monte_carlo.toml` uses engineering demonstration inputs:

| Case | USLCAP3x | ITT3x | GOLDPM2x | COMM | Assumed annual inflation |
| --- | --- | --- | --- | --- | --- |
| Historical fit | fitted log mean | fitted log mean | fitted log mean | fitted log mean | 2% |
| Base | 8% | 3% | 4% | 3% | 2% |
| Lower return | 4% | 1% | 2% | 1% | 2% |
| High inflation | 8% | 3% | 4% | 3% | 4% |

Return inputs above use `geometric_growth`. They are not research estimates,
forecasts, or user-approved expectations. They apply to the fund series after
its embedded expenses, rather than being unlevered inputs to multiply again.
The mean plot displays historical estimates beside these inputs in comparable
annual geometric units; `mean_assumptions.csv` also preserves daily log/simple
means and the original convention.

For target date d, opening date d0 and assumed annual inflation pi, define
I(d) = exp[ln(1+pi) (d-d0).days / 365.25]. Opening-price wealth is V(d)/I(d).
This is a deterministic assumed deflator in the selected reporting currency,
not observed CPI and not Australian inflation or an AUD conversion. It accrues
over weekends and holidays. Inflation must exceed -100%; negative rates are
supported. A zero rate leaves wealth unchanged. The annual mean basis counts
observations, while this deflator uses elapsed calendar days; horizons therefore
are not silently equated to calendar years.

Empirical methods use a separately recorded reference inflation rate. Base and
high inflation use identical nominal return assumptions and the same Gaussian
innovations, making their nominal paths identical. Their difference isolates
assumed purchasing power. Market returns do not react to inflation in this
model. A joint stochastic inflation/market model requires further research.

## Comparison accounting, outputs and validation

All methods use the same target observation dates, portfolio weights and
[daily no-flow accounting](resampling.md), including calendar-year risky-asset
rebalancing before the first return of the new year. An opening cash reserve
is retained. Initial portfolio investment must be positive; dated cash flows
are rejected. The default retains the user's 40/20/20/20 mix. No extra fees,
financing or taxes are charged to the existing total-return series.

Terminal nominal and opening-price p05/median/p95 use linear sample quantiles.
Fractions below opening capital are conditional sample fractions; they are not
retirement success probabilities. Nominal maximum drawdown includes the opening
mark and every return observation. The optional
[Stage 1D evaluation pass](evaluation.md) now adds real maximum
drawdown/recovery and timewise percentile bands, including calendar-only
deflator changes. These remain separate from the base Stage 1C summaries.

`calibration.json` records fitted log moments, the effective covariance/factor,
roundoff repair and each assumption's daily moments. Its SHA-256 is saved in
the input/code manifest alongside source hashes and the canonical grid. Small
saved Gaussian traces include every generated per-asset simple return and no
historical donor dates. Empirical traces retain source indices and boundaries.
All saved paths reconcile independently through the full daily ledger.

The runner writes nominal intervals, purchasing-power intervals, assumption
comparisons, individual paths and source dependence as standalone PNGs directly
from Python. Paths are individual realizations, separate from terminal
percentiles. The observed-date template is an explicit accounting device, not
a future exchange calendar forecast. Source-window and seed sensitivities
remain separate results. Keep all reports and companion input data ignored.

## Primary references

- [NIST lognormal distribution](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3669.htm),
  consulted 2026-10-28: log parameterisation and univariate moments. Our n-1
  covariance is an explicit choice, distinct from the NIST maximum-likelihood
  variance using n.
- [NumPy multivariate normal documentation](https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.multivariate_normal.html),
  consulted 2026-10-28: symmetric positive-semidefinite covariance and matrix
  factorisation. The implementation explicitly uses standard normals and its
  saved eigen factor rather than relying on the function's default factor.
