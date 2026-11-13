# ADR 0057: one line per figure in hover boxes, and a shorter test suite

Date: 2026-11-13.

Status: accepted; implemented and tested.

## Context

**User requirements:**

- Chart hover boxes showed each figure's name on one line and its value on the next, so a box with eleven figures
  was about 550 pixels tall and was sometimes cut off by the screen. Name and value should share a line.
- The financial year and the age at its 30 June shared one row ("Jul 2060 – Jun 2061 (age 70 at 30 June)"), which
  made the box wide. They should be separate rows.
- The test suite took about four minutes before every commit. Tests whose risk does not justify their time should
  go, including tests for bugs with a vanishingly small chance of occurring.

**Measured** on 13 November 2026: the hover box is Vega's table of name and value cells, which Streamlit's own
style sheet displays as blocks, so each value falls under its name. In the suite, 292 tests took 235 to 265 s, and
about 25 tests accounted for nearly all of it: each one ran a whole plan, a whole comparison study, or the whole
app.

A failing GitHub Actions run was also reported. `tests/test_story_chart.py` (ADR 0056) imported Altair without
checking for it; the workflow installs the package without the app's optional packages.

## Decision

### Hover boxes

- `ui/theme.py` styles the hover box's name and value cells as table cells on one line, names on the left and
  values on the right with figures aligned.
- `charts.with_period` adds the financial year in words and, when a birth date is known, the age at its 30 June as
  its own column; `charts.year_tooltip` gives the two rows. `charts.period_label` is removed.

### Tests removed, and why

| Test | Reason |
| --- | --- |
| `test_plan.py::test_ledger_workers_run_below_normal_priority` | Started a process to read its Windows priority class. The call is one line that has not changed since ADR 0042, and a failure would slow the desktop, not change a result. |
| `test_studies.py::test_paired_outputs_do_not_depend_on_batch_size` | Ran a whole paired study twice. That a draw does not depend on its batch is tested on the generators themselves (`test_resampling.py`, `test_volatility.py`, `test_batch_flows.py`). |
| Second runs with `batch_size=1` in four `test_comparison.py` tests | The same reason. The comparison, study and evaluation modules have not changed since 28 October 2026. |
| The second run in `test_every_compared_strategy_runs_on_the_same_draws_and_writes_its_own_folder` (back to one strategy removes the strategy folders) | A second whole run with report files for one clean-up step. The test also now compares two strategies on two paths instead of three on four. |

### Tests merged or made cheaper, with the same checks

- `test_saved_runs.py`: one simulated run for the file instead of one for each of six tests (no test changes it).
  The synthetic market data in `conftest.py` is written once per session.
- The plan-menu save-and-open app test joined the main app test, which already had a finished run on screen. One
  app start and one plan run fewer.
- Three `test_plan.py` tests that each ran the same small plan (monthly wealth kept, account series kept, progress
  messages) share one run. The command-line test now also checks the report files, replacing a separate test that
  ran the same plan to check them.
- The 35-year run no longer writes report files.

### Continuous integration

- `tests/test_story_chart.py` is skipped when Altair or Streamlit is not installed, as the other app tests are.

## Reasons and evidence

- **Engineering judgement:** a test earns its time by the chance of the bug it guards against, the cost of that
  bug, and whether a cheaper test already guards against it. The removed tests fail only if code that is stable and
  separately tested changes, or guard a behaviour with no effect on results.
- **Kept on purpose:** the two remaining app tests (about 45 s together). The app changes most often, and they are
  the only tests that draw every page.
- **Measured:** 286 tests pass in 180 s, against 265 s for the 292 before, both on a machine that was also doing
  other work. A clean total was not measured: a 20-worker plan was running during some of the later runs, which
  roughly doubled the timings of the tests it overlapped.
- **Browser check:** the flows hover box of a single path showed eleven figures on eleven lines with year and age
  on separate rows, about 180 pixels tall.

## Consequences

- A change to how generators batch their draws is now checked end to end only through the unit tests of the
  generators, not through a whole study.
- Removing the strategy folders when a plan goes back to one strategy is no longer tested.
- The worker priority of [ADR 0042](0042-faster-ledger-summaries-and-worker-priority.md) is no longer tested.
- Continuous integration still skips every app test, because it does not install the app's packages.

## Implementation and validation

- **Code:** `ui/theme.py` (styles), `ui/charts.py` (`with_period`, `year_tooltip`), `ui/outcomes_page.py`,
  `ui/paths_page.py`, `ui/more_pages.py`.
- **Tests:** `tests/conftest.py`, `tests/test_plan.py`, `tests/test_saved_runs.py`, `tests/test_comparison.py`,
  `tests/test_studies.py`, `tests/test_story_chart.py`.
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
