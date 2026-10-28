# ADR 0011: GARCH(1,1) filtered historical simulation as the heavy-tail generator

Date: 2026-10-28. Status: accepted; implemented with synthetic validation.
Companion-data evidence is in the [Stage 1D validation record](../validation/stage-1d.md).

## Context

The user selected adding a heavy-tail/volatility model after the review noted
that the Gaussian benchmark ([ADR 0007](0007-daily-parametric-assumptions.md))
lacks fat tails and volatility clustering. Both drive losses in daily-reset
leveraged funds, which make up 80% of the default portfolio. The plan requires
positive gross returns, controlled moments, and no clipping or uncontrolled
exponentiated heavy tails.

## Alternatives considered

1. **Multivariate Student-t log returns.** These have fat tails, but
   E[exp(x)] is infinite for any finite degrees of freedom. Expected simple
   returns, and every arithmetic-mean conversion, would be undefined. The plan
   excludes this.
2. **Student-t simple returns.** This gives support below -100%, and would need
   clipping.
3. **Gaussian mixture or regime-switching log returns.** These have controlled
   moments, but need more parameters and a choice of regime count, and give
   no direct volatility-clustering mechanism tied to recent shocks.
4. **Multivariate GARCH (DCC/BEKK).** This adds time-varying correlation. It
   has many more parameters and harder estimation, and needs a numerical
   optimiser.
5. **Univariate GARCH(1,1) per asset, with variance targeting and filtered
   historical simulation from jointly resampled standardised residual rows.**

## Decision

Choose 5. It is parsimonious: two parameters per asset beyond the sample
moments. It is estimated by a deterministic grid with no new dependency. Its
tails are empirical rather than an assumed shape. It keeps cross-asset
dependence by resampling whole residual rows. It generates volatility
clustering from shocks, has bounded support and finite moments, and is a
standard approach in risk management. Only the `historical` and
`geometric_growth` mean conventions are supported. Their log-mean meaning is
exact under this model, while the other conventions would need moments that
have no closed form.

## Consequences

The generator is optional (`[volatility]` in a comparison, or `garch_fhs` in a
study) and never replaces the Gaussian, replay or bootstrap results. Results
are reported side by side, never averaged. Time-varying correlation, leverage
effects and jumps remain unmodelled; see the
[methodology](../methodology/volatility.md) limitations. Holdout PIT
diagnostics and the leveraged-risk tables are the evidence for whether the
extra structure changes conclusions.
