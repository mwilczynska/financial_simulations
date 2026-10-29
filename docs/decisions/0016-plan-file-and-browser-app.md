# ADR 0016: one plan file with a local browser app

Date: 2026-10-28. Status: the local plan-file and browser-app decision remains
accepted; schema version 1 inputs and deterministic market assumptions were
superseded by [ADR 0017](0017-ticker-portfolios-and-interactive-results.md).

## Context

The user found inputs and outputs spread across many folders. Inputs were
nine experiment TOML files plus retirement scenarios written in Python, and
`output/` had about 45 folders. They asked for one user-friendly,
customisable place to set inputs (starting age, salary, portfolio, planned
retirement age and so on) in a browser UI, with import and export to a
file. They also approved deleting old scratch outputs.

## Alternatives considered

1. **Plan file and command line only.** Simple, but not the requested
   browser experience.
2. **A static HTML page with a hand-written Python server.** No new
   dependency, but much more code for forms, tables, uploads and charts.
3. **A hosted web service.** This would put personal financial details on
   someone else's machine.
4. **A local Streamlit app over a single plan format.** Forms, editable
   tables, upload and download, and interactive charts come in a few
   hundred lines of Python, reusing the same validation as the command line.

## Decision

Choose 4. Treat the plan (schema version 1; TOML or JSON) as the single
source of truth. The browser app, `financial-simulations plan` and hand
editing all go through `normalize_plan`, and every run writes one folder,
`output/plans/<plan-name>/`. Keep saved plans in git-ignored `plans/`.
Streamlit is an optional `ui` extra, so the core package and CI do not need
it. The headless app test is skipped when it is absent.

## Consequences

- One more dependency for interactive use, pinned to `>=1.60,<2`.
- The plan schema becomes a public contract; changes need a version bump
  and a migration.
- Until AUD market data arrive, plan runs use deterministic assumed AUD
  returns per asset. Connecting the Stage 1 generators and AUD FX is the
  next step for the app.
- Stage 1 research outputs are unchanged and stay separate from personal
  plan outputs.

See the [plan and app guide](../methodology/plan-and-app.md).
