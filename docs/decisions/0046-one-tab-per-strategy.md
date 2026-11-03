# ADR 0046: one results tab per compared strategy, drawn when opened

Date: 2026-11-02.

Status: accepted; implemented and tested.

## Context

The user asked for a tab per strategy after the headline comparison
([ADR 0045](0045-strategy-comparison-section.md)), each showing the full single-strategy results (sections 4 and
5). [ADR 0044](0044-run-every-strategy-on-shared-paths.md) had used a strategy selector instead.

Streamlit runs every tab's code on each rerun unless the tabs are tracked. Measured on 2 November 2026 with the
default plan (100 ledger paths) in Streamlit's test harness, a full page rerun took 4.7 s with one strategy and
14.6 s with four strategies drawn in plain tabs, because every tab's charts and tables were rebuilt.

## Alternatives considered

- **Plain tabs.** Every interaction outside a fragment waited for four strategies' results to be rebuilt.
- **A "Show" button per tab.** Lighter, but adds a click to every tab.
- **Tracked tabs** (`st.tabs(..., key=..., on_change="rerun")`), drawing only the open tab: switching tabs reruns
  the page, which then draws that strategy.

## Decision

- Results with several strategies show *Spending strategies compared*, then *Each strategy in detail* with one
  tracked tab per strategy, named as in the comparison. Only the open tab is drawn. With one strategy there are no
  tabs, as before.
- Each tab shows notes that apply only to its strategy, then sections 4 and 5 for that strategy.
- Every widget in a tab has a per-strategy key (`strategy_key`), including the download buttons, whose identical
  unkeyed copies in several tabs clashed. Downloaded file names include the strategy.
- Streamlit forgets a widget's value on any run that does not draw it. `keep_strategy_choices` re-saves the closed
  tabs' choices before the tabs are drawn, and `first_value` passes a widget's starting value only until it has
  one, which avoids Streamlit's warning that a value was set twice.
- The static PNG list shows the shared and comparison PNGs, then each strategy's own, labelled with its name.

## Reasons and evidence

- **User requirement:** tabs per strategy with the current single-strategy results.
- **Measured:** with tracked tabs a full rerun took 5.7 s with four strategies (4.7 s with one).
- **Verified in the in-app browser:** four tabs; a log-scale choice in the Fixed tab survived a visit to another
  tab, which kept its own; no page warnings or exceptions; no new server warning after `first_value`.

## Consequences

- Opening a tab costs one rerun (a few seconds), instead of every rerun costing all tabs.
- Charts and tables in tabs need no keys: in this Streamlit version they only register IDs when selections are on,
  which the app does not use. A future selection-enabled chart in a tab would need a per-strategy key.

## Implementation and validation

- **Code:** `ui/app.py` (`results`, `strategy_key`, `STRATEGY_WIDGETS`, `keep_strategy_choices`, `first_value`,
  `section_ledger` download buttons).
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:** `tests/test_plan.py::test_app_compares_ticked_strategies_and_ignores_a_stale_cores_choice` checks the
  tab labels, that only the open tab is drawn, that switching tabs works and that a choice in one tab survives a
  visit to another; the full suite.
