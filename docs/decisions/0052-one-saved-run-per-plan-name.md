# ADR 0052: one saved run per plan name

Date: 2026-11-13.

Status: accepted; implemented and tested. Supersedes the dated folder names of
[ADR 0050](0050-saved-run-results.md); the saved-run format is unchanged.

## Context

ADR 0050 saved each run's results to `output/saved_runs/<plan-name>_<date>_<time>/`, so every save added a folder.
The user asked for saved runs not to include the date, with a run saved again simply overwriting the earlier save,
and for the existing saves to be renamed and still load.

## Alternatives considered

- **Keep dated folders.** Rejected by the user.
- **Replace the folder in place** (delete, then write). An interrupted save would lose both.
- **Write the new save beside the old one and swap them when complete** (chosen).

## Decision

Results are saved to `output/saved_runs/<plan-name>/`, using the same name as the plan file `plans/<plan-name>.toml`.
Saving the results of a plan with the same name replaces the earlier save completely; nothing of it is kept (for
example, every path's ledger is gone if the new save does not include them).

A save is written to `.<plan-name>.partial`. When complete, the earlier save is renamed `.<plan-name>.old`, the new
one takes its name and the old one is removed. If anything fails between those renames, the earlier save is put
back, and the next save puts it back if a crash left only `.<plan-name>.old`. A folder of that name that is not a
saved run (no `run.json`) is never replaced; the save stops with an error.

The Plan menu says when ticking *Also save results* will replace the results saved under the plan's name. If the
results on screen were opened from the folder being replaced, the new save is opened in their place, so stored
ledgers are read from files that still exist.

`run.json` still records when the run was saved, and the list of saved results still shows it.

## Reasons and evidence

User requirement: no date in saved-run names; saving the same run again overwrites. Writing first and swapping is
engineering judgement, so an interrupted save cannot lose the earlier one.

## Consequences

Only the latest save of each plan name is kept: saving under a new plan name keeps an earlier save. Existing saves
were renamed on 13 November 2026 (see [planner validation](../validation/plan-portfolios.md)); where two saves had
the same plan name, the newer one was kept.

## Implementation and validation

`saved_runs.saved_folder` and `save_run`; `ui/saved.py`. `tests/test_saved_runs.py` checks the folder name, that a
second save replaces the first and its stored ledgers, that an interrupted second save leaves the first openable and
no partial folders behind, and that a folder that is not a saved run is never replaced.
