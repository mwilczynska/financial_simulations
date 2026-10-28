# ADR 0012: paired portfolio, source-segment and rolling holdout studies

Date: 2026-10-28. Status: accepted; implemented with synthetic and
companion-data validation. Completes the Stage 1D work that
[ADR 0008](0008-calendar-evaluation-and-sampling-error.md) left open.

## Context

The plan's Stage 1D requires three things. Portfolio comparisons on shared
simulated paths. Rolling calibration/holdout exercises. Sensitivity to
reconstructed versus observed data segments. It also forbids choosing a model
because it gives the most reassuring answer. The selected default portfolio
was chosen by an optimiser on the same history it would be evaluated on, and
its leveraged series before 2009 are model reconstructions. Single-portfolio
reports cannot show either how much of a result comes from leverage, or how a
calibrated generator would have performed out of sample.

## Alternatives considered

1. Extend the existing `compare` runner with more portfolios and windows. Its
   single-portfolio loop and output schema would need replacing, which risks
   the reconciled Stage 1B-1D outputs.
2. Run separate experiments per portfolio and compare them afterwards. Draws
   would no longer be shared unless every stream key matched, and the
   comparison noise would be larger.
3. Add separate `paired` and `holdout` study commands. They reuse the same
   samplers, generators and accounting, and compound every portfolio on each
   batch of draws.

## Decision

Choose 3 ([studies.py](../../src/financial_simulations/studies.py)).

- **Paired:** for each window, horizon and generator case, every portfolio
  compounds identical joint daily return rows. Report each portfolio's
  terminal and drawdown percentiles. For each portfolio against the reference,
  report pathwise wealth-ratio percentiles, the share of paths ahead (with
  Wilson intervals for generated paths only), and drawdown differences.
- **Source segments:** each window can require every return interval of a
  chosen set of assets to be `observed` or `reconstructed`, using ADR 0009's
  provenance labels. The run fails instead of quietly mixing segments. For
  each window and asset it reports growth, volatility, skewness, kurtosis,
  worst-day, clustering and provenance-count statistics.
- **Tail diagnostics:** compare the historical calibration sample with
  generated paths for each portfolio and asset. The statistics are excess
  kurtosis, the 0.1% and 1% daily quantiles, summed squared-return
  autocorrelation over 21 lags, rolling 63-observation volatility percentiles
  and volatility drag. This is the leveraged-risk diagnostic.
- **Rolling holdouts:** at the first observation of each year, fit each
  generator only on returns ending at or before that origin (rolling or
  expanding). Simulate the next H observations on the realised dates, and
  score the realised terminal wealth, maximum drawdown and realised
  volatility with a mid-rank PIT. Summaries report PIT means, tail
  frequencies, central-90% coverage, a KS distance from uniform, and the
  number of non-overlapping holdouts.

## Reasons

- **User requirements:** finish Stage 1D; add a leveraged-risk diagnostic; keep
  daily returns, Python PNGs and no PDFs.
- **Research basis:** the PIT is the standard tool for checking a forecast
  distribution against outcomes (Diebold, Gunther and Tay 1998). A calibrated
  forecaster's PIT values are uniform. Overlapping multi-period holdouts are
  serially dependent, so formal uniformity tests do not apply directly. This
  project therefore reports descriptive coverage plus non-overlapping counts,
  and no p-values.
- **Engineering judgement:** sharing draws is the variance-reduction method the
  plan prescribes. Making provenance an enforced requirement, rather than a
  label, prevents reconstructed history from passing as observed fund
  history.

## Consequences

- Studies are nominal USD with no flows, as before.
- Holdout realised outcomes before 2009 use reconstructed leveraged series,
  so the PIT there measures agreement with the dataset project's model as
  well as with markets. The provenance fraction of each fold's calibration
  and holdout is recorded for this reason.
- An optimiser-selected default can look good in holdouts partly because it
  was selected on that history. Holdouts recalibrate generators, but cannot
  undo the selection of the weights.
- The diagnostic's generated statistics use a configured subset of paths
  from the first seed at the longest horizon.

## Implementation and validation

See the [evaluation methodology](../methodology/evaluation.md), `tests/test_studies.py`
and `scripts/validate_studies.py`. Companion-data evidence is in the
[Stage 1D validation record](../validation/stage-1d.md).

Reference: Francis X. Diebold, Todd A. Gunther and Anthony S. Tay (1998),
*Evaluating Density Forecasts with Applications to Financial Risk Management*,
International Economic Review 39(4), 863-883,
[publisher record](https://doi.org/10.2307/2527342). Cited for the PIT principle;
not re-read in full for this checkpoint.
