# ADR 0013: a sourced 2026-27 rule register with explicit unsupported cases

Date: 2026-10-28. Status: accepted; rule set and functions implemented and
tested. The single-path ledger is a later 2A checkpoint.

## Context

The user asked to start Stage 2. The plan requires that Stage 2A come before
any stochastic retirement modelling. Its deliverable is a sourced rule
register for the 2026-27 rules plus verified enacted future changes, with
boundary tests and an auditable single-path ledger. A source check on
2026-10-28 found several recent changes:

- the 15% first marginal rate (14% from 2027-28);
- the $1,000 standard deduction from 2026-27;
- Payday Super from 1 July 2026;
- indexed caps ($32,500 concessional, $130,000 non-concessional, $2.1m
  transfer balance cap);
- Division 296 in force from 1 July 2026;
- the first stage of the CGT reform, enacted in June 2026 and effective from
  1 July 2027, with its apportionment method still to be legislated.

The user has deferred Australian CPI and AUD FX.

## Alternatives considered

1. Hard-code current rates inside the calculation functions. This is quick,
   but it hides provenance and dates.
2. Implement every in-force rule, including the 2027 CGT reform, Division
   296 earnings, excess-contribution regimes and SAPTO. The CGT reform needs
   Australian CPI and an unlegislated apportionment method. The others need
   inputs the single-person scope does not yet have.
3. Load parameters as dated data with a status and source each. Implement
   the in-scope 2026-27 calculations exactly, and reject everything else.

## Decision

Choose 3. Values that the ATO has not yet published for 2026-27 (the
Medicare low-income thresholds) are labelled assumptions, and loading
reports them. Calculations that would otherwise need guesses raise
`UnsupportedRule`, including CGT events from 1 July 2027. Future years get
their own rule sets in a later checkpoint, with a declared treatment for each
parameter: legislated, statutorily indexed under stated assumptions, or
frozen.

## Reasons

- **User requirement:** current authoritative sources, effective dates,
  boundary tests, and enacted law kept apart from proposals.
- **Engineering judgement:** a rejected scenario is visible, whereas a quietly
  approximated tax liability would contaminate every later retirement result.
  Data files make annual updates a reviewed diff with a hash.

## Consequences

- A long early-retirement plan cannot yet run past 30 June 2027 when it
  realises capital gains. That waits for the 2027-28 rule set, the CGT
  reform implementation and an Australian CPI input. AUD FX and CPI were
  deferred by the user, so the CPI input waits on that decision.
- Excess contributions, excess transfer balances and Division 296 balances
  must be avoided by scenario design until those regimes are modelled.
- The register must be revisited when the ATO publishes the 2026-27 Medicare
  thresholds or when further CGT legislation passes.

See the [methodology](../methodology/australian-rules.md) and the
[register](../rules/au-2026-27.md).
