# ADR 0005: user-selected default and audit of existing tracker calculations

Date: 2026-10-28. Status: accepted; default implemented and local audit executed.

## Context and decision

The user selected the `Optimised CURRENT` entry in the local
`portfolio_plot17.py` as the default: `USLCAP3x` 40%, `ITT3x` 20%, `GOLDPM2x` 20%
and `COMM` 20%. Preserve those explicit input aliases in the default scenario;
adapters resolve them to `USLCAP3X`, `ITT3X`, `GOLD2X` and `CMDTY`.

The label records a user choice, not a finding that this project has optimised or
validated the allocation for future retirement. Use the supplied daily leveraged
fund series without multiplying returns again or duplicating embedded expenses.
Keep the previous equal-weight global portfolio as an explicitly named comparator.

Audit the existing tracker before replacing calculations. Compare its pure
calculation functions on common inputs rather than running its top-level script,
which also handles downloads, CPI/risk-free inputs, configuration and plotting.
Do not copy private source code or machine-specific paths into this repository.

## Alternatives and reasons

Alternatives were retaining the illustrative equal-weight default, copying the
whole tracker, or importing its module directly. Explicitly selecting the user's
weights satisfies their requirement. Auditing selected functions preserves
useful conventions while exposing date/timing differences, without invoking
unrelated I/O or publishing private machine configuration.

The [Stage 1A validation](../validation/stage-1a.md) includes both reference
projects. The optional local audit extracts only `simulate_portfolio`, `cagr`,
`twrr` and `max_dd` definitions using Python's AST, then supplies explicit NumPy,
pandas, dates, starting value and policy inputs. No top-level script code runs.
This optional audit executes trusted local calculation functions supplied by the
caller; it is not a sandbox for untrusted Python.

## Verified findings and consequences

The script snapshot SHA-256 inspected on 2026-10-28 is
`79159ca026bb42439fa1c903b3b7d22385bfe526e2f23a0f72775b0fa0fac63e`.
This records provenance without publishing the script or its private location.

- **CAGR and maximum drawdown:** the tracker formulas agree with the new report
  when applied to the same correctly dated, no-flow value paths. Reuse those
  mathematical conventions, including elapsed calendar days/365.25 for CAGR.
- **Date alignment:** the tracker initializes at its first return date, then
  applies the preceding row's return to the next dated value. On 4,023 observations
  the isolated function matches the new values shifted by one observation under
  both annual and buy-and-hold policies. Its final value excludes the last return.
  The new engine uses an opening valuation and applies each return on its own
  observation date; the regression fixture checks the full first/last intervals.
- **Contributions:** values `[100, 120, 108]`, with a contribution of 10 after a
  +10% return followed by -10%, have cumulative time-weighted return -1%. With
  its metric horizon set to one year to expose the cumulative factor, the tracker
  function yields approximately -0.307692%. Retain explicit flow phases and
  compound flow-adjusted daily performance, validated by the hand calculation.
- **Calendars and economic inputs:** the tracker carries valuations over a union
  calendar and has CPI/risk-free fallback paths. Stage 1A instead requires
  identical source calendars and remains nominal USD with no risk-free series.
  Mixed calendars and Australian real-return reporting need separate work.

These are findings from isolated functions on controlled inputs, not a complete
validation of every tracker output. The existing tracker has not been edited.
No claim is made about Sharpe, CPI adjustment or a live-data run. See
`tests/test_accounting.py` and `tests/test_reporting.py` for the date and cash-flow
regressions, and the optional local `tracker-audit.json` for numerical evidence.
