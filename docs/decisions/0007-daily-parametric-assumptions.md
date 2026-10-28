# 0007: Daily Gaussian log returns and persistent scenario assumptions

Date: 2026-10-28. Status: accepted; generator implemented, report integration
in progress.

## Context and alternatives

Stage 1C needs an understandable parametric comparator to empirical replay and
bootstrap. Annual simple-return draws spread over days would lose daily risk
and could violate return support. Reusing historical means as forecasts would
hide assumption uncertainty. A normal simple-return model permits losses
below 100%; exponentiated heavy-tailed draws can lack controlled moments.

## Decision

Use a correlated Gaussian model in daily natural-log returns, fitted with a
sample log mean and n-1 covariance. State the observation annualisation basis
and the precise meaning of every annual return override. Keep historical
estimates visible beside a named scenario grid whose assumptions persist
through each path. Share Gaussian innovations across that grid, with seed and
path identifiers independent of mean assumptions and portfolio weights.

Use an eigen factor so perfectly correlated assets and zero-variance cases are
supported. Repair only negative eigenvalues attributable to roundoff under the
documented relative tolerance; record the repair. Fail on numeric return
overflow/rounding to total loss rather than clipping or resampling.

## Reasons and consequences

This preserves positive asset gross returns and permits analytical moment
checks. It does not establish Gaussian market behaviour or a realistic tail
model. Differences between generators remain separate results. The initial
grid represents assumption uncertainty transparently; an outer parameter
distribution, regime models and retirement integration remain later work.

The planned high-inflation comparison is a persistent assumed purchasing-power
deflator paired with the same nominal market draws as the base case. It will
not model market reactions to inflation or claim to be observed CPI. Rates
must have a recorded rationale and units, with demonstration inputs labelled
as such. See [methodology](../methodology/parametric.md) for the implemented
generator and remaining report work.
