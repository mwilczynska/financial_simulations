# ADR 0006: joint daily sampling, explicit calendars and reproducible path streams

Date: 2026-10-28. Status: accepted; core and sensitivity runner implemented and tested.

## Context and alternatives

Stage 1B compares sequence assumptions for one configurable portfolio. Alternatives
include separate asset sampling, monthly aggregation, unlabelled repeated history,
using donor dates as future dates, and one shared mutable random stream.

## Decision and reasons

Preserve full joint daily vectors and expose contiguous replay, independent
rows, non-circular moving blocks and circular stationary bootstrap separately.
Count only complete replay windows. Keep source dates distinct from explicit
target account dates; the initial runner uses a shared observed calendar template.
Document its interpretation instead of guessing future market holidays.

Generate independent PCG64 streams from deterministic per-path keys. Batch only
the no-flow accounting, with tests against the full ledger; do not reduce the
return frequency to save work. Retain indices and boundary flags for traceable
paths and the seed/version recipe for regenerating other draws.

Joint daily returns and transparent provenance are user requirements. The
stationary-bootstrap algorithm follows Politis and Romano; it does not prove
historical financial representativeness. Non-circular moving blocks, calendar
templates, integer expected lengths and stream keys are engineering choices.

## Consequences and evidence

Endpoint bias differs between moving and stationary blocks. A circular join is
an artificial boundary. Generated horizons do not imply historical coverage or
independent long-run evidence. Net donor returns keep embedded costs; no new
financing or Australian tax assumptions enter this comparison.

See [resampling methodology](../methodology/resampling.md) and
`tests/test_resampling.py`: 16 new cases passed at the initial checkpoint. The
calibration-window/block-length sensitivity runner is now implemented. The
[Stage 1B evidence](../validation/stage-1b.md) records 63 tests, complete replay
counts and reconstruction of saved traces through the full account ledger.
