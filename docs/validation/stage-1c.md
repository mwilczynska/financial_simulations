# Stage 1C validation

Date: 2026-10-28. Generator checkpoint: 67 local tests pass, including four new
parametric tests. Scenario-grid integration, companion-data execution and PNG
review are pending; Stage 1C is not yet complete.

The synthetic parametric checks verify fitted log means and n-1 covariance,
one-dimensional calibration, singular covariance, deterministic compounding,
three explicit annual mean conventions, 200,000 fixed-seed simulated joint
log/simple moments and shared innovations under a changed drift. Invalid
covariance, nonfinite inputs, unsupported total loss and numerical overflow or
rounding to total loss fail. See the [methodology](../methodology/parametric.md).

The full 67-test suite passed locally on Python 3.14. The repository check also
confirmed UTF-8/LF, valid local documentation links and ignored private inputs
and outputs. No companion market data or private input has been added to Git.
