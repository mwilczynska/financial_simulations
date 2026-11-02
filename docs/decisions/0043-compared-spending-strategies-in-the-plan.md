# ADR 0043: compared spending strategies in the plan file

Date: 2026-11-02.

Status: accepted; implemented and tested. Running every compared strategy on the same paths is proposed as stage 4
of the [strategy comparison plan](../strategy-comparison-plan.md) and is not implemented.

## Context

The user wants to compare the four retirement spending strategies the planner offers (fixed, Guyton–Klinger
guardrails, Vanguard ceiling and floor, a percentage of wealth each year), each with its existing options and with
every other input held constant, and to choose which to compare with tick boxes. Schema version 2 held one
`spending.rule`. The market-responsive rules start from a percentage of wealth at retirement, while fixed spending
could also start from a dollar amount; compared strategies that started from different spending would mostly show
that difference, not the rules.

## Alternatives considered

- **A list of strategy tables**, each with its own parameters and start. Flexible, but the user asked for one set
  of options per strategy and every other input held constant, and separate starts would reintroduce the unfair
  comparison.
- **Keep `rule` and add `compare`.** Two fields that can disagree.
- **Replace `rule` with `compare`**, keeping every rule's parameters in the existing fields.

## Decision

- Schema version 3 replaces `spending.rule` with `spending.compare`, a non-empty list drawn from `fixed`,
  `guyton_klinger`, `vanguard` and `percent`, stored in that order. Version 2 files still load; their `rule`
  becomes a one-item list.
- When `compare` is anything but `["fixed"]`, `retirement` must be `"percent"`: every compared strategy starts
  from the same percentage of wealth on the retirement date (user decision, 2 November 2026). Fixed spending then
  keeps that starting amount's buying power.
- The minimum and maximum apply to every market-responsive strategy, as before; fixed spending ignores them.
- `strategy_plan(plan, rule)` gives the plan for one strategy (`spending.rule` set); `build_inputs` requires one
  when more than one strategy is compared.
- The app shows a tick box per strategy and each ticked strategy's settings.
- Until stage 4, a run uses the first compared strategy and adds a run note saying that only it was run.

## Reasons and evidence

- **User requirements:** the four strategies, their existing options, every other variable constant, tick boxes,
  and a shared percentage start (decision 3 in the strategy comparison plan).
- **Engineering judgement:** one list cannot disagree with itself, and the existing per-rule fields already hold
  every strategy's options.

## Consequences

- Plan files saved by this version are version 3 and cannot be read by earlier versions.
- A plan with fixed spending only keeps its "same" and "amount" start options; adding any other strategy requires
  a percentage start.
- Until stage 4, ticking several strategies changes nothing in the results except the note.

## Implementation and validation

- **Code:** `retirement/plan.py` (`SCHEMA_VERSION`, `READABLE_VERSIONS`, `_strategies`, `strategy_plan`,
  `build_inputs`), `retirement/run_plan.py`, `retirement/default_plan.toml`, `ui/app.py`
  (`spending_rule_inputs`).
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:** `tests/test_plan.py::test_spending_rule_defaults_to_fixed_and_maps_to_the_ledger`,
  `tests/test_plan.py::test_compared_strategies_share_one_start_and_old_single_rules_still_load`, the TOML and
  JSON round trip, and the full suite. The user's ten saved version 2 plans were checked to load (read only).
