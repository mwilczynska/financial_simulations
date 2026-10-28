# ADR 0009: opt-in common-date calendars and per-return source provenance

Date: 2026-10-28. Status: accepted; implemented and fixture-validated. Extends
[ADR 0003](0003-stage-1a-data-contract.md), whose strict policy stays the default.

## Context

Stage 1D needs rolling holdouts and source-segment sensitivity, and both need
history before 2006. The default four series do not share calendars there. In
the inspected local snapshot, 459 dates between 1970 and 2005 appear in some
of the four files but not all. That is about 13 a year, consistent with
different holiday calendars (for example LBMA gold against US exchanges).
From 2006 they match. The strict loader rejects every window that reaches back
into the mixed period, so it can test neither a reconstructed segment nor a
long holdout sequence.

Per-row quality flags show that all four default series are model
reconstructions before 2006-02-07. The series move to observed ETF histories
at different dates, the last on 2009-06-26 (UPRO). Interpreting a sample
therefore needs to know, return by return, which segment it came from.

## Alternatives considered

1. Keep strict calendars only, limiting Stage 1D to 2006 onwards and excluding
   every reconstructed-only segment.
2. Use the union of dates and carry stale levels for assets without a quote.
   That invents a zero return on the missing day and moves the asset's real
   move to the next day, so it breaks cross-asset timing.
3. Keep only dates every asset observes, and recompute each return from the
   levels on consecutive kept dates. An asset whose holiday is removed then
   has one return covering two source intervals.

## Decision

Implement option 3 as an explicit opt-in, `calendar_policy = "common_dates"`.
Choosing it is a scenario/experiment setting, never an automatic fallback.
Published returns are still checked against each file's own adjacent levels
before thinning. Every kept interval records how many source observations
each asset spans. The manifest counts dropped source dates per asset and
multi-observation intervals.

Classify each return interval per asset from the quality flags of every source
row it touches, both endpoints included. The `observed_` prefix means
observed, and `model_` or `backcalculated_` means reconstructed. Any other
flag is unclassified. An interval touching more than one class is `mixed`, so
a splice interval is never labelled observed. The joint label is the common
class across assets, or `mixed`.

## Reasons

- **User requirements:** daily returns throughout; no fabricated returns or
  silently inserted zeros; reconstructed and observed segments distinguished.
- **Verified local facts:** calendar and quality-flag audit of the local
  companion snapshot on 2026-10-28 (counts above).
- **Engineering judgement:** a two-day interval for one asset is still a
  return observed between two actual valuation dates. Its length is reported
  rather than hidden. The optimiser's existing full-history behaviour is also
  an inner join of level dates, so this policy matches that convention.

## Consequences

About 3% of 1970-2005 intervals span more than one source observation for at
least one asset. Generators treat them as ordinary daily rows, which slightly
overstates the variance per row in those intervals. Calendar-only account
days remain carried marks. The strict default and all earlier results are
unchanged. Segment checks refuse to call a window observed or reconstructed
unless every interval qualifies.

## Implementation and validation

[datasets.py](../../src/financial_simulations/data/datasets.py) and
`tests/test_adapters.py` cover spanning-return compounding, dropped-date counts,
splice classification, unclassified flags and policy validation. See the
[adapter methodology](../methodology/data-adapters.md).
