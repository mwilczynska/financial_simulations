# Stage 1C validation

Date: 2026-10-28. Implemented scope: a daily correlated Gaussian log-return
benchmark and persistent assumption grid in the common-currency, no-flow
comparison. See [methodology](../methodology/parametric.md) and
[ADR 0007](../decisions/0007-daily-parametric-assumptions.md).

## Synthetic checks

All 71 local tests passed on Python 3.14, including eight new Stage 1C tests.
The repository check confirmed UTF-8/LF, local links, no tracked machine paths
and the expected privacy ignores.

The expanded suite checks log mean and n-1 covariance against hand calculations,
one-dimensional fitting, singular/perfect correlation, deterministic 8%
compounding and all three annual input conventions. A fixed-seed simulation of
200,000 joint observations recovers known log/simple moments and correlation
within declared statistical tolerances. It also verifies shared innovations
after a drift change, repeatability and different seeds.

Boundary checks cover nonfinite/asymmetric/non-PSD covariance, invalid annual
inputs and aliases, a total loss in calibration, invalid annualisation bases,
only-roundoff eigenvalue repair and numerical exponentiation failures without
clipping. The assumed price index includes weekend elapsed days, supports zero
and negative inflation and rejects invalid dates/rates.

The synthetic comparison tests require byte-identical case outcomes, daily
traces, summaries and calibration parameters across batch sizes 1 and 3. Saved
Gaussian and empirical returns independently reconstruct through the full
daily ledger. Gaussian traces cannot claim historical donor dates. Every paired
base/high-inflation path has identical nominal terminal wealth and the exact
expected deflator relationship. Existing Stage 1A/1B tests remain passing.

## Companion-data experiment

Run:

```powershell
python scripts/validate_stage1b.py --experiment scenarios/examples/monte_carlo.toml --output output/stage1c
```

The validator now supports both comparison stages. Generated evidence and
reports remain ignored. The example retains the user-selected `USLCAP3x` 40%,
`ITT3x` 20%, `GOLDPM2x` 20%, `COMM` 20%, annual risky-asset rebalancing and an
illustrative USD 100,000 opening value with no flows or cash reserve.

- Calibration windows 2010-2025 and 2016-2025 contain 4,023 and 2,513 daily
  return observations. Their source provenance/hashes are recorded.
- Horizons are 252, 1,260 and 2,520 observations on the shared observed account
  calendar template. These are not assumed to be exact calendar years.
- There are 512 stochastic paths per seed (1729 and 2718), one block setting
  L=63, four Gaussian assumption cases and all available complete replay windows.
- The run contains 90 cases and 54,564 paths: 43,008 stochastic paths and 11,556
  complete overlapping replays. The shorter calibration window has no complete
  2,520-observation replay, explicitly reported with zero paths.
- All 15 saved example paths reconcile through the full daily ledger with
  maximum absolute wealth error 0 in the executed run (tolerances rtol 1e-11,
  atol 1e-7). Empirical donor dates match source indices; Gaussian traces save
  generated daily returns and leave donor fields empty.
- All 6,144 base/high-inflation path pairs have exactly identical nominal
  terminal wealth. Deflated wealth matches the analytical ratio of assumed
  price indices. Outcome counts and complete-window counts pass.

## Visual review and interpretation

Five standalone PNGs were generated directly by Python/Matplotlib and visually
inspected: nominal terminal intervals, assumed purchasing-power intervals,
historical/forward mean comparison, individual paths and source dependence.
The assumption comparison uses a shared vertical scale across calibration
windows. Labels, seed separation, the absent replay window, explicit log axes
and the demonstration-input captions are readable. No PDFs were created.

The initial report makes a material assumption sensitivity visible: fitted
USLCAP3x geometric growth is much higher than the example's 8% base input,
and fitted ITT3x growth changes sign between these calibration windows. This
does not establish predictive accuracy. Lower return assumptions move the sampled
wealth distribution down. Higher assumed inflation reduces purchasing power
while leaving the paired nominal market outcomes unchanged by construction.

The core checkpoint `e48498a` passed hosted Python 3.11/3.14 CI in
[run 40765841885](https://github.com/mwilczynska/financial_simulations/actions/runs/40765841885).
The full implementation `e69401f` passed both hosted jobs in
[run 40767049484](https://github.com/mwilczynska/financial_simulations/actions/runs/40767049484).
The companion-data experiment was rerun from clean commit `e69401f`; its input
and validation manifests record `working_tree_dirty: false` and Python-source
SHA-256 `492e79b7f86e001d43fa839cf8991ca317e9c5cc77695b223724f90f6916e742`.
Counts, trace reconciliation and paired-scenario checks all passed again.
Private paths, source data and generated reports are excluded from Git.

## Limits

Rates are engineering demonstration inputs with recorded rationale, not
researched forecasts or user-approved expectations. The index is assumed
inflation in the reporting currency, not observed CPI, Australian purchasing
power or an AUD conversion. There is no market reaction to inflation, outer
parameter distribution, regime/tail calibration, tax, super or retirement
withdrawal model. Real drawdown/recovery, timewise percentiles, target metrics
and sampling-error reporting remain Stage 1D. Overlapping replays are dependent;
more simulated paths do not add independent historical evidence.
