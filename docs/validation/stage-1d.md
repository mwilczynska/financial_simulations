# Stage 1D validation

Date: 2026-10-28. Status: evaluation kernel implemented with five new synthetic
tests. Runner integration, companion-data audits and direct PNG review remain
in progress. This is not a claim that all Stage 1D work has been completed.

Tests cover exact pointwise quantiles and target equality, completed versus
unrecovered drawdowns, repeated high-water marks, total loss and longest
underwater durations. Friday-to-Monday checks show flat nominal wealth but
three days of real drawdown under assumed inflation. Wilson reference values,
zero/all misses, shrinking intervals as path count increases, replay fields
without inference, invalid inputs and exact-panel memory limits are checked.

See [methodology](../methodology/evaluation.md) and
[ADR 0008](../decisions/0008-calendar-evaluation-and-sampling-error.md).
