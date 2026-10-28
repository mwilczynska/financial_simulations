# Stage 1B validation evidence

Date: 2026-10-28. Scope: joint daily replay/resampling and no-flow comparisons.
The source-code version, hashes, input coverage and dependency versions are
recorded in local run manifests. See [methodology](../methodology/resampling.md)
and [ADR 0006](../decisions/0006-joint-daily-resampling.md).

## Executed synthetic suite

63 tests passed locally on Python 3.14.0, NumPy 2.5.4, pandas 3.1.0 and Matplotlib
3.11.2. This comprises the previous 43 cases, 16 sampler/batched-accounting cases
and four comparison cases. The latter cover exact CSV equality under changed
batch size, all saved trace reconstructions, explicit target calendars, zero
complete replay coverage, malformed settings, and serial dependence on a
synthetic alternating-return process.

Tests are [samplers/accounting](../../tests/test_resampling.py) and
[comparison integration](../../tests/test_comparison.py), plus all Stage 1A tests.
Restart-frequency and uniform-donor checks use fixed seeds, large synthetic
draws and broad tolerances. They test implementation, not financial stationarity.

## Local default experiment

Run from the project root in the installed development environment:

```powershell
python scripts/validate_stage1b.py --output output/stage1b
```

The [experiment](../../scenarios/examples/comparison.toml) references the user's
default 40/20/20/20 portfolio and an illustrative USD 100,000 investment with
annual rebalancing, no dated flows, no additional expenses and no inflation/FX.
All generators use the same observation-date template for each horizon.

The completed run has **90 cases**, **33,060 paths**, and **12 saved example
paths**. Seven stochastic settings (independent plus moving/stationary blocks
of lengths 21, 63, 252) each use two seeds and 256 paths: 21,504 stochastic paths
across the six calibration/horizon pairs. The other 11,556 are complete
overlapping historical replay windows:

| Calibration window | Source returns | Horizon observations | Complete replay windows |
| --- | ---: | ---: | ---: |
| 2010-2025 | 4,023 | 252 | 3,772 |
| 2010-2025 | 4,023 | 1,260 | 2,764 |
| 2010-2025 | 4,023 | 2,520 | 1,504 |
| 2016-2025 | 2,513 | 252 | 2,262 |
| 2016-2025 | 2,513 | 1,260 | 1,254 |
| 2016-2025 | 2,513 | 2,520 | 0 |

The last case has `no_complete_window` status and no outcome quantiles. It is
not filled with an incomplete window or a stitched history. Bootstrap generation
is still possible because that is a separately labelled model assumption.

Every saved path is reconstructed from its source indices and target calendar
through Stage 1A's full daily ledger. The audit compares every observation using
`rtol=1e-11, atol=1e-7`, checks recorded donor dates and reconciles case/path counts.
Observed numerical results are saved in `output/stage1b/validation.json`, with
the exact code/input provenance in `manifest.json`. Generated results, source
dates and local files remain ignored by Git.

The PNGs are inspected directly as images. Visual review identified dense minor
log-axis tick labels and an out-of-bounds missing-window caption; tick formatting
and fixed category limits were corrected before the final inspection. No PDF
or interactive-browser validation is claimed or required for these static plots.

## Interpretation and remaining scope

The seed comparisons expose finite-simulation variation. A 5th sample percentile
from 256 paths is an exploratory tail estimate; more paths reduce sampling noise
without adding historical evidence. Replay windows overlap and are dependent.
Generator/sample/block-length disagreement is retained rather than averaged into
a single success probability. Diagnostics of returns and squared returns do not
establish an optimal block length.

The explicit common calendar is an observed template, not a future exchange
schedule. Historical net leveraged-fund returns are sampled as supplied; they
are not rebuilt for a new financing or holiday-gap path. Australian inflation,
FX, dated cash flows in this runner, parametric models, tax and retirement rules
remain future work. Stages 1C onward have not been started.
