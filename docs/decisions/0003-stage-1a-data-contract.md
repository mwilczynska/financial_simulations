# ADR 0003: explicit Stage 1A adapters and strict observation calendars

Date: 2026-10-28. Status: accepted; adapters implemented and fixture-validated.

## Context

Stage 1A needs reproducible daily histories and manually supplied or imported
portfolio weights. Upstream aliases differ. The four default assets have
matching calendars from 2010 in the inspected snapshot but different early
calendars. The optimiser intersects level dates before calculating returns.

## Alternatives considered

1. Replicate the optimiser's full-history inner join, losing intermediate marks.
2. Use a union and carry missing levels as accounting marks, requiring explicit
   closure, missing-quote and transaction policies.
3. Require identical source observation dates in the selected window and defer
   mixed-calendar support until its policy has been specified and tested.

## Decision

Choose 3 for Stage 1A. Preserve every selected source row, with an opening
valuation followed by adjacent-level daily returns. Reject mismatched calendars
and invalid data. Reconcile on the aligned modern window rather than claiming
equivalence across the earlier mixed calendars.

Maintain explicit canonical aliases, USD currency and supplied total-return
semantics. Import numeric weight columns only and require the scenario to supply
policy absent from optimiser CSVs. Record file hashes and source/quality metadata.

## Reasons and evidence

- **User requirements:** daily returns, explicit companion adapters, no silently
  fabricated returns, no double-counting of distributions or embedded fees.
- **Verified local facts:** common column contract and optimiser implementation
  inspected on 2026-10-28; the calendar audit is recorded in the
  [adapter methodology](../methodology/data-adapters.md).
- **Engineering judgement:** a limited aligned baseline is easier to reconcile
  than introducing an unreviewed stale-valuation assumption. The first level is
  an opening mark so returns never include performance before the opening date.

## Consequences

Some long-history requests fail explicitly. There is no default 1970 four-asset
example. A future calendar policy can extend the adapter without replacing the
market-path contract. Missing days common to all files remain an audit limitation.
USD nominal results cannot be represented as Australian real-spending outcomes.

## Implementation and validation

See [data adapters](../methodology/data-adapters.md) and
`tests/test_adapters.py`: 18 synthetic tests passed on 2026-10-28, including
Parquet equivalence. The subsequent [Stage 1A validation](../validation/stage-1a.md)
records the expanded suite and portfolio-accounting/optimiser reconciliation.
