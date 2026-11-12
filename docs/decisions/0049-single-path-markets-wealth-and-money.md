# ADR 0049: one path's markets, wealth and money on one date axis

Date: 2026-11-12.

Status: accepted; implemented and tested.

## Context

The user asked for a view where, after picking a path, they can see under each other (or two per row) a line plot
of market returns over time with CAGR and standard deviation statistics, a wealth over time plot, and a money in
and money out plot, and asked what the best way to show this would be.

The Paths page already drew one path's balances and its yearly money in and out, in separate tabs, with no view of
the markets the path ran on ([ADR 0047](0047-app-layout-and-one-visual-system.md)). Each path's sampled daily
returns were available (`PortfolioAnalysis.returns_for`) but only summarised across paths on the Markets page.

## Alternatives considered

- **Two charts per row.** Fits more on a screen, but a year no longer sits at the same horizontal position in each
  chart, so a market fall cannot be read down to its effect on wealth.
- **Three separate charts in one column.** Each chart keeps its own zoom, so the years stop lining up as soon as
  one is panned, and a hairline cannot follow the pointer across them.
- **Daily or yearly returns as the markets line.** Daily returns are mostly noise at this scale, and yearly returns
  hide when in the year a fall happened and how deep it went.
- **A separate panel per ticker.** Removes the scale problem of leveraged tickers, but the user's portfolio could no
  longer be compared with its parts.
- **One stacked chart of three panels sharing the date axis, markets drawn as growth of $1** (chosen).

## Decision

**The view.** A single path on the Paths page opens on *Markets, wealth and money*: a table of market statistics,
then one chart of three panels with one date axis.

| Panel | Contents |
| --- | --- |
| Markets | Growth of $1 invested on the first day, in today's dollars, on a log scale: each entered portfolio as a thick line and each ticker as a thin line, at weekly points |
| Wealth | Month-end balances by account, stacked (as before) |
| Money in and out | One bar per financial year by flow, with the net change in wealth and the amount added to outside investments as lines (as before); each bar spans its year on the date axis |

- Dragging or Shift+scrolling any panel moves all three. A hairline marks the month nearest the pointer in all
  three, and the tooltip gives that month's values for the panel under the pointer (that financial year's flows in
  the bottom panel).
- Clicking a legend item in the Markets or Money panel hides or shows it and the axis refits, with *Show all* and
  *Show none* for each.
- The former *Balances* and *Money in and out* tabs are this view. The transfers between accounts keep their own
  tab, followed by *Year by year* and *Event log*.

**The market series** (`retirement/path_markets.py`). The path's daily returns are the joint donor rows drawn for
it, the rows its tax ledger ran on. Each ticker is those returns compounded. Each entered portfolio (outside super,
inside super) is compounded at its entered weights with its rebalancing rule, exactly as the portfolio analysis
does ([ADR 0018](0018-planner-annual-rebalancing.md)); when both hold the same weights and rebalance alike
they are one line, *Your portfolio*.

**The statistics**, one row per series, all from the path's daily returns:

| Column | Definition |
| --- | --- |
| Growth per year (CAGR) | `end ** (1 / years) - 1` for $1 over the path, before inflation |
| CAGR after inflation | The same with the ending value deflated by the plan's CPI assumption |
| Volatility (st. dev.) | Sample standard deviation of daily returns times the square root of 252 |
| Worst drawdown | The deepest fall below a previous high |
| $1 grew to | The ending value of $1 in today's dollars |

**Groups of paths** (added later on 12 November 2026, after the user picked a group and found the old tabs). A
group opens on the same view, summarised over its paths: the median across the group's paths of each series'
growth of $1 at each month end, the median month-end balance of each account, and the average of each yearly flow
(averages, because the flows must add up, [ADR 0040](0040-medians-and-mostly-zero-measures.md)). The table gives the
median of each path's own statistics. Each series' median is taken on its own, so the lines need not belong to one
path. `group_markets` compounds every path with the portfolio analysis's routine, treating a ticker as a
one-ticker portfolio that is never rebalanced. The group's tabs are *Markets, wealth and money* and *Year by
year*.

**Legends that hide and show** (same day, user request: "click on/off various groups in figures"). Every chart
with a legend now toggles its items on a click: accounts in the balances panel, the states in *Where the paths
stand each year* (whose axis now refits, so hiding *Self-funded* closes in on the trouble), flows in the Outcomes
money chart, portfolios on the Markets page and strategies on the Compare page.

**Tabs keep the page still** (same day, user request). A tab's content is drawn only once it is open, so the panel
was empty for a moment after a click, the page shortened and the browser scrolled up. Tab panels now have a
minimum height of one window.

**Combined portfolio** (same day, user request: "combined portfolio stats to the table and the lineplot"). When
the outside and super portfolios differ, a *Combined portfolio* series leads the table and the markets panel: $1
split between the two in proportion to the plan's opening outside investments and super balances, each part then
compounding as its own portfolio with nothing moved between them. This is the portfolio analysis's existing
combined series (`PortfolioAnalysis.combined_shares`), so its statistics equal that path's *Combined* row there.
It is absent when the portfolios are alike (the one line is already the combination) or both balances are zero.

**Buttons beside their panel** (same day, user request: "add a show all/show none to the barplot"). The money in
and out panel's *Show all* and *Show none* sat above the chart, two panels away from the bars. They are now below
the chart, at the bars; the markets buttons stay above it.

**PNG.** `retirement_markets.png` per strategy draws the same lines for the path nearest median ending wealth,
with each series' CAGR, volatility and worst drawdown in the legend. `ledger.png` and `retirement_flows.png`
already cover that path's balances and flows.

## Reasons and evidence

- **User requirement:** the three plots for a chosen path, under each other, with CAGR and standard deviation
  statistics for the market returns.
- **Engineering judgement:** one column on a shared date axis, because the purpose is reading cause and effect
  between the panels; growth of $1 on a log scale, because equal slopes are equal growth rates and a crash is the
  same drop wherever it happens; weekly points for the lines (a fifth of the daily rows, and they still show a
  crash that month ends would smooth) with the statistics from daily returns; the factor of 252 and the portfolios'
  compounding copied from the existing portfolio analysis so the two agree.
- **Tested agreement:** for the same path, a portfolio's CAGR after inflation, volatility, worst drawdown and ending
  value equal that path's row in the portfolio analysis's outcomes.
- **Observed** on 12 November 2026 with the example plan extended to 40 years (fixed spending, path 37, nearest
  median ending wealth): the outside super portfolio grew 13.4% a year (10.6% after inflation) with 23.0%
  volatility and a worst drawdown of 69.1%, while `USLCAP3x` grew 6.5% a year with 51.8% volatility and fell 98.5%
  from its high.

## Consequences

- The markets panel shows returns in today's dollars, like the other panels; the table gives growth before and
  after inflation.
- Leveraged tickers swing far more than the portfolio even on a log scale. They can be hidden from the legend.
- The combined portfolio's split is fixed on the first day and then drifts with returns. The household's actual
  split also moves with contributions, drawdowns and the pension transfer, which the combined line leaves out.
- The portfolio lines are the entered portfolios at their target weights. The ledger's actual holdings also reflect
  contributions, sales and the cash buffer, so wealth does not move exactly with the portfolio line.
- The sampled returns are USD histories used as an AUD proxy, as everywhere in the planner.
- Two charts in one view each have a legend that hides items, so `charts.hideable` now listens only to clicks on
  its own legend; Vega-Lite's plain legend binding reacts to every click in a chart and would toggle the other
  legend's last item back.
- Altair lists a layered panel's selections against every layer that has one, which defines some twice. The stacked
  chart is therefore drawn from its specification with those lists corrected (`theme.with_views`).
- Each run writes one more PNG per strategy.

## Implementation and validation

- **Code:** `src/financial_simulations/retirement/path_markets.py`; `ui/charts.py` (`path_story`, `cursor_layers`,
  `fy_span`, `flow_items`, `hideable`); `ui/paths_page.py` (`path_story`, `market_table`, `path_moves`);
  `ui/theme.py` (`draw`, `with_views`); `reporting/plan.py` (`write_path_markets_plot`); `retirement/run_plan.py`.
- **Methodology:** [plan-and-app.md](../methodology/plan-and-app.md).
- **Tests:** `tests/test_path_markets.py` checks rebalancing on the first observation of a calendar year, agreement
  with the portfolio analysis for the same path (the combined portfolio included, and that it is the two portfolios
  at their opening shares), each ticker's compounding, that identical portfolios are one
  series, that a group of one path reproduces that path, and that a group's statistics are medians of its paths'; `tests/test_plan.py::test_browser_app_runs_with_tickers_and_interactive_results` opens the view and its
  other tabs and checks the PNG is written.
- **Browser check** on 12 November 2026: the three panels line up, the hairline and its tooltips follow the
  pointer through all three, and legend clicks in one panel leave the other's hidden items alone. Later the same
  day: a group shows the three panels; legend clicks hide items in the states, Outcomes flows, Markets and Compare
  charts; and the scroll position held at 700 pixels through three tab changes on the Outcomes page.
