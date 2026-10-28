# Correlated daily log-return benchmark (Stage 1C)

Status on 2026-10-28: generator and synthetic checks implemented. Scenario-grid
integration and the companion-data report are in progress; this document does
not yet establish their validation.

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

## Primary references

- [NIST lognormal distribution](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3669.htm),
  consulted 2026-10-28: log parameterisation and univariate moments. Our n-1
  covariance is an explicit choice, distinct from the NIST maximum-likelihood
  variance using n.
- [NumPy multivariate normal documentation](https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.multivariate_normal.html),
  consulted 2026-10-28: symmetric positive-semidefinite covariance and matrix
  factorisation. The implementation explicitly uses standard normals and its
  saved eigen factor rather than relying on the function's default factor.
