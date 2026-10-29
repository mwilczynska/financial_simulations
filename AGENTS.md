# Project instructions

## Scope and accepted requirements

- This repository is `mwilczynska/financial_simulations`. Use `financial_simulations` for the working-folder and Python-package name.
- Keep the simulation core in Python. Consume local processed data from the sibling `financial_datasets` project and portfolio weights from `portfolio_optimisation` through explicit adapters.
- Daily returns are required throughout loading, calibration, replay, resampling, generated paths, portfolio compounding and retirement accounting. Monthly/annual values are report summaries. Do not replace the core with a monthly or annual return engine.
- Generate PNG plot images directly from Python and inspect them visually. The retirement planner also has interactive plots; keep both outputs consistent. Do not create PDFs.
- The default portfolio is `USLCAP3x` 40%, `ITT3x` 20%, `GOLDPM2x` 20% and `COMM` 20%, selected by the user from the `Optimised CURRENT` entry in the local `portfolio_plot17.py`. Audit relevant existing calculations there before replacing conventions; keep private script paths/content out of tracked files.
- Distinguish trading observations from calendar days and scheduled events. Do not fabricate daily observed CPI or silently insert zero returns for missing trading data.
- Initial retirement scope: one Australian tax resident, then couples. Preserve individual ownership, access dates and tax positions in the design.
- Read `PLAN.md` and relevant methodology/decision records before changing model behaviour. Proposed behaviour is not implemented or validated merely because it appears in a document.

## Methodology is part of the work

- Maintain detailed documents under `docs/methodology/` for every implemented model and material calculation. Include purpose, equations/conventions, inputs/provenance, assumptions, algorithm, examples, validation, limitations and references.
- Maintain dated decision records under `docs/decisions/` for material choices, explaining context, alternatives, the decision, reasons and consequences.
- Distinguish user requirements, primary-source facts, research findings and engineering judgement. Do not invent references or imply a source proves more than it does.
- Update methodology, decision status and validation evidence with the implementation in the same coherent checkpoint. Preserve superseded decisions as history.
- Source Australian tax and super rules from current authoritative sources, record effective dates and test boundaries. Distinguish enacted law from proposals and future policy assumptions.
- Respect dataset-specific meanings of price and total-return columns. Distributions and fund fees already embedded in a return series must not be added or charged again.

## Git and privacy

- The user has requested regular commits and pushes. Commit reviewed, coherent milestones and push them to the configured origin/current branch after appropriate validation. Do not wait until a large task ends to preserve completed milestones.
- Preserve remote history, inspect upstream changes before integrating them, and avoid force pushes unless the user explicitly requests one.
- Stage explicit project files. Exclude private scenarios, personal balances/birth dates/tax records, generated personal reports, credentials and copied source data.
- Use the public GitHub handle `mwilczynska` and a GitHub noreply commit address. Do not publish the user's personal email address, real-name identity or machine-specific absolute paths in tracked documentation or commit metadata. Author names in scholarly references are appropriate.
- Keep `scenarios/private/`, `output/`, local data copies and environment secrets ignored. Track useful small, synthetic validation fixtures deliberately.

## Windows workflow

- Use PowerShell, `rg` for searches and explicit working directories. Keep commands on separate lines and use `-LiteralPath` for filesystem operations.
- Read/write Markdown as UTF-8 and preserve LF line endings. Use `apply_patch` for source/document edits.
- Write nontrivial Python checks to script files rather than embedding quoted programs in `python -c`.
- Before moving a directory, verify the resolved source, destination parent and absence of a conflicting target. Keep the operation within the user's explicitly requested paths.
