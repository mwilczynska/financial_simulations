# ADR 0047: a top bar, one page at a time and one visual system

Date: 2026-11-10.

Status: accepted; implemented and tested. Supersedes the page layout in
[ADR 0016](0016-plan-file-and-browser-app.md) and the strategy tabs in
[ADR 0046](0046-one-tab-per-strategy.md); the calculations behind every figure are unchanged.

## Context

The user asked for the app to be redesigned: cleaner, with resized plots, an opinion on which plots are needed,
and inputs, buttons and graphs that belong together. The user also said the sidebar takes a lot of space.

The app was one script. A permanent sidebar held Run and the plan's file actions. Five tabs held the inputs and
one results page of five numbered sections, about twenty charts of 400 to 670 pixels each with a paragraph under
every chart. Every tab's code ran on every rerun, so changing an input rebuilt the results. Charts used Streamlit's
default chart theme and about twenty hand-picked colours; the money in and out charts used eleven.

## Alternatives considered

- **Restyle in place** (theme and smaller charts only). Leaves the long page, the sidebar and the rebuilt results.
- **Streamlit's own multipage navigation.** Gives URLs per page, but its top bar cannot hold Run or the plan menu,
  and the test harness cannot switch between pages defined in one script.
- **Move to another web framework.** A much larger change that would not improve the calculations.
- **Keep the sidebar, collapsed by default.** Hides Run, the most used control.
- **A bar across the top, one page drawn at a time** (chosen).

## Decision

**Layout.**

- No sidebar. A bar that stays on screen holds the plan's name, the pages, the state of the results (not run, up to
  date, inputs changed, or problems to fix), a *Plan* menu (name, save, rename, open, import, download, reset) and
  *Run plan*. A finished run opens the Outcomes page.
- Pages: **Plan** (inputs in four tabs: You, Investments, Retirement, Assumptions), **Outcomes**, **Paths**,
  **Compare** (only when several strategies ran), **Markets** and **Method**. Only the open page is drawn. Inside
  Outcomes and Paths, tracked tabs draw only the open tab.
- With several strategies, Outcomes and Paths show one strategy at a time, chosen with a control at the top of the
  page; each strategy keeps its own choices. This replaces one tab per strategy.
- Content is at most 1,320 pixels wide. Inputs and charts sit in white cards on a slightly darker page.
- The long explanation of each chart is folded under it (*How to read this*); a one-line subtitle stays visible.

**Charts kept, moved and removed.** The old five sections map to pages as follows.

| Before | Now |
| --- | --- |
| 1 Your portfolios, 2 History, 3 Future simulations | Markets |
| 4 Retirement outcomes | Outcomes: headline, then tabs *Wealth*, *Risk over time*, *Spending*, *Age Pension*, *Money in and out*, *Tables* |
| 5 One path in full, and groups | Paths: tabs *Balances*, *Money in and out*, *Year by year*, *Event log* |
| Spending strategies compared | Compare |
| Notes on today's dollars, how results are calculated, saved files, rule assumptions | Method |

Removed, because another chart or table already carries the figures:

- Ending wealth on every path (ranked dots): the outcome tiers, the every-path chart and the *Outcome ranges* and
  *Every path* tables cover it.
- Share of paths with a shortfall each year: *Where the paths stand each year*
  ([ADR 0048](0048-outcome-tiers-and-average-retirement-spending.md)) shows it with the Age Pension states.
- Account-based pension payments across paths, and one path's pension minimum against paid: in the tables.
- One path's personal tax and concessional cap lines: in its *Year by year* table.
- Markets: the median lines side by side (the fan chart and the percentile table cover them), and the ending value
  and volatility histograms (in the percentile table). Growth and maximum drawdown histograms remain.
- The whiskers on the typical year's net change: in late years the middle half of the net change is several times
  the height of the bars and flattened them. The 25th and 75th percentiles stay in the line's tooltip.

Changed:

- The four taxes (income, contributions, super fund and Division 296) are drawn as one **Tax** flow in every money
  in and out chart, interactive and PNG. Sums are unchanged, so one path's bars still add up to its net change. The
  yearly tables, the Compare page's flow picker and the CSV files keep each tax.
- The Age Pension chart shows the paths paid any Age Pension that year, with the full single rate as a line. Across
  every path its median and 75th percentile were zero in most plans, so the chart showed only a 95th percentile.
- Chart heights are 250, 340 or 430 pixels by role.

**One visual system.** `reporting/palette.py` holds every colour, for the app and the PNG review plots:

- Eight series hues, ink and surface greys from one reference palette (already used for the compared strategies).
- Outside super is blue and super is orange wherever accounts or portfolios appear.
- Outcome tiers have their own four colours (ADR 0048).
- The Streamlit theme (`STREAMLIT_THEME`): a light theme only, with one accent blue. `.streamlit/config.toml`
  repeats it for `streamlit run`; `financial-simulations ui` passes it on the command line, so the app looks the
  same from any working folder.

`ui/theme.py` applies one chart configuration (type, quiet axes, horizontal grid only, legend above the plot)
instead of Streamlit's chart theme.

**Code.** The app is split into `ui/app.py` (the bar and the page switch), `inputs.py`, `outcomes_page.py`,
`paths_page.py`, `more_pages.py` (Compare, Markets, Method), `charts.py`, `results.py`, `theme.py` and `state.py`.

## Reasons and evidence

- **User requirement:** a cleaner app, resized plots, an opinion on which plots are needed, a consistent design and
  a smaller sidebar.
- **Engineering judgement:** which charts to remove, the page split, the folded explanations and the single Tax
  flow. Each removal is listed above so it can be reversed.
- **Checked with the palette validator** (10 November 2026, white surface, neighbours in drawing order): the account
  colours, the eight flow colours and the tier colours pass the lightness band, the colour-vision separation of
  neighbours and the normal-vision floor. The neutral grey fails the chroma floor by design: it marks inflation and
  self-funded paths, which are meant to recede. Yellow, aqua and magenta are below 3:1 contrast on white, so every
  chart that uses them has a legend and a table.
- **Why Streamlit forgets choices.** Streamlit drops a widget's value on any run that does not draw it. With only
  one page and tab drawn, `sticky` in `ui/state.py` registers each such widget and `keep_sticky` re-assigns its
  value at the top of every run, which makes it ordinary session state. This generalises ADR 0046's
  `keep_strategy_choices`.

## Consequences

- Changing an input no longer rebuilds the results; opening a page or tab costs one rerun of that page.
- The app has no dark theme. The PNG plots share the light surface, and chart colours were validated only on it.
- Charts and explanations removed here are not in the app; their figures remain in tables and CSV files.
- A sticky bar depends on Streamlit's page structure (the bar's wrapper element); a Streamlit upgrade could unstick
  it without breaking anything else.
- The calculation cores choice and the open Plan tab are kept across pages by `state.KEPT`.

## Implementation and validation

- **Code:** `src/financial_simulations/ui/`, `reporting/palette.py`, `reporting/plan.py` (PNG colours, folded
  taxes), `retirement/flows.py` (`fold_taxes`, `fold_tax_columns`), `cli.py` (theme flags), `.streamlit/config.toml`.
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:** `tests/test_plan.py::test_browser_app_runs_with_tickers_and_interactive_results` runs a plan and opens
  every Outcomes tab, the Markets, Method and Paths pages and a group's tabs without an exception;
  `test_app_compares_ticked_strategies_and_ignores_a_stale_cores_choice` checks the strategy picker, that each
  strategy keeps its own path choice, and the Compare page; `tests/test_outcomes.py` checks that the config file
  repeats the palette's theme and that folded taxes keep each year's total.
- **Checked in the in-app browser** on 10 November 2026 with a 40-year plan comparing fixed and Guyton–Klinger
  spending on 100 paths: every page and tab, the plan menu, a run from start to the Outcomes page, and the PNG
  plots `retirement_outcomes.png` and `retirement_flows.png`.
