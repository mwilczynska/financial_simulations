# ADR 0050: saved run results, with every path's ledger optional

Date: 2026-11-13.

Status: accepted; implemented and tested. Its Results menu is superseded by
[ADR 0051](0051-save-results-from-the-plan-menu.md) (tick boxes in the Plan menu); the rest stands.

## Context

The user asked whether the outputs of certain simulations could be saved. Only inputs (plans) were saved, and a
large run takes significant time, so opening results meant running again. Saved outputs would also allow further
analysis outside the app. After an estimate of the space needed, the user asked for both: saving the results the app
shows, and an optional tick box, off by default, that also saves every path's full daily ledger.

A run already wrote `output/plans/<plan-name>/` (CSV summaries, the median path's ledger and PNGs; ADR 0044), but
each run overwrote it, and the app could not open it: it lacked the market history, the sampled draws and every
path's month-end balances, and CSV loses types.

Measured on 12 November 2026 for a 50-year plan (zstd Parquet): month-end balances by account and the yearly rows
take about 29 kB per retirement path per strategy; one path's full daily ledger and event log about 1.06 MB; the
1,000 × 12,345 sampled history rows 49 MB raw, 17 MB compressed and 1 MB delta-encoded (bootstrap blocks are runs of
consecutive rows, so most steps are +1). One path's ledger re-runs in about 0.9 s.

## Alternatives considered

- **Pickle the `PlanRun`.** Smallest code, but files break when a class changes, cannot be read by other tools and
  can run code when loaded.
- **Reuse `output/plans/<plan-name>/`.** One folder per plan name is overwritten by every run, and CSV loses dtypes.
- **Store only the seed and re-derive.** Re-running is what the user wants to avoid; the draws also depend on the
  source data, which can change.
- **Save every path's ledger always.** About 1 GB per strategy for 1,000 paths, while one path re-runs in a second.
- **Capture every ledger during the run.** Avoids re-running them, but the choice must then be made before the run,
  and every run pays the cost in memory or disk whether it is kept or not.
- **One Parquet file per path for the full ledgers.** Simple, but thousands of files.

## Decision

**What is saved.** The Results menu in the top bar saves the results on screen to
`output/saved_runs/<plan-name>_<date>_<time>/` (git-ignored; one undated folder per plan name since
[ADR 0052](0052-one-saved-run-per-plan-name.md)), with an optional note. The folder holds:

| File | Contents |
| --- | --- |
| `run.json` | Format version, time saved, note, normalized plan, rule and code manifests, market manifest and income proxies, portfolio shares, strategy index |
| `plan.toml` | The plan |
| `market_returns.parquet`, `asset_summary.parquet` | The joint daily history returns the paths were drawn from, and ticker statistics |
| `portfolio_draws.npz` | The future observation dates and every market path's history rows: first row and the steps between rows |
| `portfolio_history/bands/outcomes/summary.parquet` | The portfolio results |
| `strategies/<rule>/retirement_paths/retirement_annual/account_bands/path_series.parquet` | Each strategy's path outcomes, yearly rows, account bands and month-end balances by path |
| `strategies/<rule>/representative/` | The median path's full ledger |
| `strategies/<rule>/ledgers/` | Only with the tick box: every calculated path's full ledger |

A stored ledger set is `daily.parquet` and `events.parquet` with a `path` column and one row group per path, and
`years.json` with each path's financial-year records (tax assessments included), outstanding liabilities, its own
columns and row groups. Paths can lack event fields that other paths have, so each file uses the union of the
columns, and a path reads back with only its own. Timestamps keep their unit through file metadata.

**Every path's ledger.** The tick box *Also save every path's full daily ledger* is off by default. When ticked, the
save re-runs every calculated path's ledger, for each strategy, on the run's own stored draws in the worker pool;
each worker writes its paths to a scratch folder, which is merged into one ledger set per strategy and removed. The
menu shows the expected size before saving.

**Opening.** *Open* loads the plan and results together; the status reads *Saved results opened* and the Outcomes
page opens. Nothing summarised by the run is recalculated: the bands and the all-paths wealth table are taken from
the stored frames exactly as a run takes them. On the Paths page a path's ledger is read from the saved ledgers when
they exist, otherwise re-run from the saved market history and draws, which gives the ledger the run summarised.
When the model's Python source differs from the saving code (`python_source_sha256` in `run.json`), the menu warns
that the results are those of the saving code.

**Writing safely.** A save is written under a hidden `.<name>.partial` folder and renamed when complete, so an
interrupted save never lists as a saved run.

## Reasons and evidence

User requirements: save run outputs to avoid re-running and to allow further analysis; save every path's full
ledger only when a tick box (default off) asks for it.

Engineering judgement: Parquet keeps types, is compact and readable by pandas and other tools; the `path` column and
one row group per path let one path load without the rest and let analysis read every path at once. Re-running the
ledgers at save time keeps the choice after the results are seen and costs nothing for runs not saved; the stored
draws make the re-run ledgers those the run summarised, which the tests check.

## Consequences

- A 50-year, 1,000-retirement-path, one-strategy save measured 26.8 MB in 16 files without the full ledgers and 1.16 GB in 19 files
  with them; see the measurements in [planner validation](../validation/plan-portfolios.md).
- Saved results are tied to the code that produced them. After a model change they still open (with a warning) as
  long as the stored frames still have the columns the pages read; a format change will need `FORMAT` raised and
  older saves migrated or refused.
- Saving every ledger re-runs and writes them all: 363 s against a 158 s run in the validation measurement.
- Saved runs are not deleted by the app; remove folders under `output/saved_runs/` to free space.

## Implementation and validation

`retirement/ledger_store.py` (stored ledger sets and the worker that writes them), `retirement/saved_runs.py`
(`save_run`, `load_run`, `list_saved_runs`, `estimate_bytes`), `ui/saved.py` (the Results menu), `PlanRun.saved_ledgers`
and `PlanRun.saved_from`, and the Paths page's `selected_ledger`. `tests/test_saved_runs.py` checks that every
strategy's frames, the median ledgers, portfolio results, market and draws open identical in value and dtype; that
every stored path ledger equals a re-run of that path; that paths with different columns read back with their own;
that a folder without a manifest is not a saved run; and, through the app, that the tick box starts off and saving
and opening work. Method: [plan and app](../methodology/plan-and-app.md#saved-results).
