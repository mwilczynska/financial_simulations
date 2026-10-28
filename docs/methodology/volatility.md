# GARCH filtered historical simulation (heavy tails and volatility clustering)

Date: 2026-10-28. Status: implemented as an optional generator for the Stage 1C
comparison runner and the Stage 1D studies. Synthetic checks have run; for
companion-data evidence see the [Stage 1D validation record](../validation/stage-1d.md).
Decision: [ADR 0011](../decisions/0011-garch-filtered-historical-simulation.md).

## Purpose

The [Gaussian benchmark](parametric.md) has constant daily variance and thin
tails. A daily-reset leveraged fund loses most when volatility stays high for
weeks: the compounding drag grows with the square of the leverage times
realised variance, and a few very bad days in a row can impair it
permanently. A model with neither volatility clustering nor fat tails is
therefore likely to understate exactly the risks that dominate the user's
default 40/20/20/20 portfolio, which is mostly 3x and 2x funds. This
generator adds both while keeping return support above -100% and every
expectation finite.

## Model

Per asset i, with daily log return x_t = ln(1 + r_t), sample log mean mu and
demeaned error e_t = x_t - mu:

    h_(t+1) = omega + alpha e_t^2 + beta h_t,   omega = s^2 (1 - alpha - beta)

Here s^2 is the sample variance (denominator n-1), and h_1 = s^2. This
*variance targeting* fixes the unconditional variance at its sample value, so
the fit chooses only alpha >= 0 and beta >= 0 with alpha + beta <= cap
(default 0.999) and alpha <= 0.5. Estimation minimises the Gaussian
quasi-likelihood 0.5 sum[ln h_t + e_t^2 / h_t]. The search is a deterministic
grid at step 0.01, refined twice around the incumbent at steps 0.001 and
0.0001. The result is reproducible without an iterative optimiser or a new
dependency. A fit on a grid edge (alpha = 0, alpha = 0.5 or the persistence
cap) is flagged `at_bound` in the manifest.

Standardised residuals z_t = e_t / sqrt(h_t) are recentred and rescaled per
asset to mean 0 and variance 1 (denominator n). The raw mean and standard
deviation are recorded. Simulation then follows *filtered historical
simulation*:

1. For each path, draw residual row indices independently and uniformly over
   the calibration sample, using PCG64/SeedSequence `[seed, 5, horizon,
   path_id]`. A whole row is drawn at once, so every asset takes the same
   historical day's shock.
2. Start h at the unconditional s^2 (default) or, with
   `initial_variance = "last_fitted"`, at the filtered variance for the first
   day after the sample.
3. Each step: innovation = sqrt(h) z, x = mu + innovation, r = exp(x) - 1, and
   the GARCH recursion updates h from the simulated innovation.

Cross-asset dependence comes from the empirical residual rows, so the
conditional correlation is constant. Volatility is asset-specific, with no
spillover between assets. Tails are those of the observed standardised
shocks, amplified when conditional variance is high. Because shocks are drawn
from a finite sample and h is finite over a finite horizon, simulated log
returns are bounded and the expected simple return exists. This avoids the
infinite exponential moments of a Student-t log-return model, which the plan
rules out.

## Means and conventions

Standardised residuals have mean exactly zero over the resampling
distribution, so the expected daily log return is exactly mu. Two conventions
are supported:

| Convention | Daily log mean |
| --- | --- |
| `historical` | fitted sample log mean |
| `geometric_growth` g | ln(1+g)/T with T observations per year |

`expected_compounded_return` and `annualised_daily_arithmetic` need
E[exp(x)], which has no closed form under GARCH with empirical shocks. They
are rejected, not approximated. A comparison with a `[volatility]` table
requires every assumption to use one of the two supported conventions. The
residual-row stream excludes the mean, inflation and weights, so assumption
cases and portfolios share identical shocks and variance paths.

## Configuration

```toml
[volatility]
model = "garch_fhs"
initial_variance = "unconditional"   # or "last_fitted"
persistence_cap = 0.999
```

In `compare`, this adds a `garch_fhs` case for every assumption, beside the
`lognormal` cases. `calibration.json` records, per window and asset: alpha,
beta, persistence, unconditional and last-filtered variance, quasi-likelihood,
the bound flag, raw residual moments and the residual correlation matrix.
Saved traces store every generated return, with no donor dates.

## Validation

`tests/test_volatility.py` checks the following:

- Recovery of known parameters, within 0.03 for alpha and 0.04 for beta, from
  4,000 simulated GARCH observations.
- A near-zero alpha for homoskedastic noise.
- A hand-calculated variance recursion and deterministic refits.
- Residual standardisation.
- Batch-invariant streams, and shocks shared across means (log returns differ
  by exactly the mean shift).
- Simulated per-step variance within 8% and mean within 3e-5 of target.
- Squared-return autocorrelation above 0.05, against below 0.02 for the
  Gaussian model.
- The last-fitted start, and rejection of unsupported conventions and settings.

`tests/test_comparison.py` checks the comparison runner: byte-identical outputs
across batch sizes, identical nominal paths for deflator-only twins, and saved
traces reconciling through the full daily ledger. Companion-data evidence,
including the leveraged-risk diagnostic, is in the
[Stage 1D validation record](../validation/stage-1d.md).

## Limitations

- Residuals are resampled independently. Clustering enters only through the
  variance recursion, so any dependence left in the standardised residuals is
  broken. Asymmetric (leverage-effect) responses, jumps, regimes and
  time-varying correlation are not modelled.
- Variance targeting ties long-run volatility to the calibration sample. A
  short sample from a calm or turbulent period sets the level for every
  simulated year.
- Shocks cannot exceed the worst standardised day in the sample, but that
  bound is in standardised units. A residual recorded after a calm period
  (19 October 1987 is -13.5 standard deviations for `USLCAP3X` in the
  1970-2006 fit) can be drawn when simulated variance is high, giving a
  daily loss larger than any in history. On companion data the
  reconstructed-window portfolio's worst generated day was -66%, against
  -25% in the sample. Excess kurtosis was 219 against 22. Read GARCH-FHS
  extreme tails as a stress-leaning model, not as a fitted tail. Capping or
  trimming residuals would be a separate, documented choice.
- Gaussian QML is consistent for GARCH parameters under broad conditions, but
  grid precision (0.0001) and the bounds limit the estimates. No standard
  errors are reported.
- Synthetic leveraged series before 2009 are model reconstructions. GARCH fits
  on them inherit those reconstruction assumptions.

## References

The following were cited from these papers' published formulations; they were
not re-read in full for this checkpoint. A citation does not validate this
implementation.

- Tim Bollerslev (1986), *Generalized Autoregressive Conditional
  Heteroskedasticity*, Journal of Econometrics 31(3), 307-327,
  [author-hosted paper](https://public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf).
  Defines GARCH(1,1) and its stationarity condition alpha + beta < 1.
- Robert Engle and Joseph Mezrich (1996), *GARCH for Groups*, Risk 9(8), 36-40.
  Proposes variance targeting.
- Giovanni Barone-Adesi, Kostas Giannopoulos and Les Vosper (1999), *VaR
  without Correlations for Portfolios of Derivative Securities*, Journal of
  Futures Markets 19(5), 583-602,
  [publisher record](https://doi.org/10.1002/(SICI)1096-9934(199908)19:5%3C583::AID-FUT5%3E3.0.CO;2-S).
  Introduces filtered historical simulation.
- Tim Bollerslev and Jeffrey Wooldridge (1992), *Quasi-Maximum Likelihood
  Estimation and Inference in Dynamic Models with Time-Varying Covariances*,
  Econometric Reviews 11(2), 143-172,
  [publisher record](https://doi.org/10.1080/07474939208800229). Covers Gaussian
  QML under non-normal innovations.

Revision history: 2026-10-28, first implementation.
