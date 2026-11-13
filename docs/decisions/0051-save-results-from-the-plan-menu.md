# ADR 0051: save results from the Plan menu

Date: 2026-11-13.

Status: accepted; implemented and tested. Supersedes the Results menu of
[ADR 0050](0050-saved-run-results.md); the saved-run format and behaviour are unchanged.

## Context

ADR 0050 added a Results menu beside the Plan menu, so the top bar had two menus for saving. The user asked for
saving results to be a tick box in the Plan menu, used when saving a plan, greyed out and not clickable while there
are no results, as a UI simplification.

## Alternatives considered

- **Keep the two menus.** Rejected by the user.
- **A tick box that is only greyed out before the first run.** After inputs change, ticking it would save a plan file
  beside results of different inputs.
- **Tick boxes in the Plan menu, greyed out without matching results** (chosen).

## Decision

The Results menu is removed. In the Plan menu, under the plan name:

- **Also save results**: greyed out and cleared when there are no results, or when the inputs have changed since the
  last run (its help says which). When ticked, **Save** writes the plan file and then saves the results as in
  ADR 0050, with progress under the bar.
- **Also save every path's full daily ledger**: greyed out and cleared unless *Also save results* is ticked; off by
  default.
- **Open saved results** sits below *Open a saved plan*; opening one loads its plan and results, as before.

When opened results are on screen, the menu says where they came from and warns if the code has changed since.

**Rename** saves only the plan.

## Reasons and evidence

User requirement: one menu, results saved by a tick box when saving a plan, greyed out without results. Greying it
out after inputs change too is engineering judgement, so a saved plan and the results saved with it describe the
same inputs.

## Consequences

Saving results now always saves the plan file too. The menu is drawn before the Plan page applies an edit, so the
box greys out on the next rerun after an edit (as the status text does); a Save click starts a new rerun, which
sees the edit, so results are never saved beside changed inputs.

The browser review found that opening saved results gave the plan editor the opened run's own plan object, so
editing an input also changed the plan the results belonged to and the status still said they matched. The editor
now gets a copy.

## Implementation and validation

`ui/saved.py` (`save_options`, `open_saved_results`, `opened_note`), `ui/app.py` (`plan_menu`, `top_bar`).
`tests/test_saved_runs.py::test_plan_menu_saves_results_with_the_plan_and_opens_them` checks both boxes are greyed
out before a run, the ledger box until results are ticked, that Save writes the plan and the results, that opening
works, and that changed inputs grey the results box out again. Method:
[plan and app](../methodology/plan-and-app.md#saved-results).
