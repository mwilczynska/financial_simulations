"""The Compare, Markets and Method pages."""

import altair as alt
import pandas as pd
import streamlit as st

from financial_simulations.reporting.palette import MUTED, PORTFOLIO_COLOURS
from financial_simulations.retirement.flows import milestones
from financial_simulations.retirement.strategy_results import (DEFAULT_FLOW, OUTFLOWS, STRATEGY_COLOURS, STRATEGY_NAMES,
                                                               available_flows, comparison_table, wealth_lines,
                                                               yearly_medians)
from financial_simulations.ui import charts
from financial_simulations.ui.results import derived
from financial_simulations.ui.state import compact, fit, percent_column, percentile_table, share, sticky, sticky_choice
from financial_simulations.ui.theme import MEDIUM, card, chart_title, draw, explain, legend, page_title


def strategy_scale(rules):
    """Each strategy's fixed colour, whatever is ticked: colour follows the strategy, not its position."""
    return alt.Scale(domain=[STRATEGY_NAMES[r] for r in rules], range=[STRATEGY_COLOURS[r] for r in rules])


@st.fragment
def compare_page(run):
    strategies = run.strategies
    rules = list(strategies)
    paths = len(run.retirement_paths)
    page_title("Compare strategies",
               f"All {len(rules)} spending strategies ran through the daily tax ledger on the same {paths:,} market paths, "
               "with every other input unchanged and the same starting spending, so the differences come from the "
               "strategy alone. Today's dollars.")
    with card("comparetable"):
        table = comparison_table(strategies)
        shown = pd.DataFrame({"Measure": table["Measure"],
                              **{STRATEGY_NAMES[r]: [share(v) if kind == "share" else compact(v)
                                                     for v, kind in zip(table[r], table["Kind"])] for r in rules}})
        st.dataframe(shown, width="stretch", hide_index=True, height=fit(shown),
                     column_config={"Measure": st.column_config.TextColumn("Measure", pinned=True, width="large")})
        explain("Read risk, spending and wealth together: a strategy that spends less always ends with more. The first "
                "three rows count each path once by the worst it reached (the Outcomes page's tiles). *Average "
                "retired-year spending* is each path's spending paid, averaged over its full retired years; *spending "
                "over full retired years* is the total. A *10th percentile* is the level 90% of paths beat, so it "
                "describes bad markets. The *lowest retired year* is each path's smallest year of spending paid "
                "(shortfalls lower it). Every figure is a separate median or percentile across paths, so a column need "
                "not describe one path.")
    marks = derived(run).marks
    colour = alt.Color("Strategy:N", scale=strategy_scale(rules))
    with card("comparewealth"):
        left, right = st.columns([3, 1.4], vertical_alignment="center")
        with left:
            chart_title("Wealth over time", "Median total wealth across paths at each month end, one line per strategy.")
        with right:
            low = st.toggle("Add the 10th percentile", key=sticky("compare_p10", False),
                            help="Dashed lines that 90% of paths stay above: bad markets.")
        lines = wealth_lines(strategies)
        lines["Strategy"] = lines["Strategy"].map(STRATEGY_NAMES)
        long = lines.melt(["Date", "Strategy"], value_vars=["Median", "P10"] if low else ["Median"], var_name="Statistic",
                          value_name="Wealth")
        long["Statistic"] = long["Statistic"].map({"Median": "Median", "P10": "10th percentile"})
        long = charts.add_age(long)
        base = alt.Chart(long).encode(x=alt.X("Date:T", title=None, axis=charts.year_axis(long)), color=colour)
        names = [STRATEGY_NAMES[r] for r in rules]
        drawn, visible = charts.toggle(base.mark_line(strokeWidth=2).encode(
            y=alt.Y("Wealth:Q", title="Total wealth, today's dollars", axis=charts.money_axis()),
            strokeDash=alt.StrokeDash("Statistic:N", scale=alt.Scale(domain=["Median", "10th percentile"], range=[[1, 0], [6, 3]]),
                                      legend=alt.Legend() if low else None)), "Strategy", names, "strategies")
        drawn = drawn.properties(name="compare_lines_0")
        hover = alt.selection_point(fields=["Date"], nearest=True, on="pointerover", empty=False, name="compare_hover")
        targets = base.transform_filter(visible).mark_point(size=80, opacity=0).encode(
            y="Wealth:Q", tooltip=[alt.Tooltip("Date:T", format="%b %Y"), *charts.age_tooltip(long), "Strategy:N", "Statistic:N",
                                   alt.Tooltip("Wealth:Q", format="$,.0f")]).add_params(hover)
        rule = alt.Chart(long).mark_rule(color=MUTED).encode(x="Date:T").transform_filter(hover)
        # One flat layer: nesting a chart that owns a selection inside another layer duplicates its signals. The
        # legend selection belongs to the lines only (see charts.path_story on Altair's lists of views).
        draw(charts.zoomable(alt.layer(drawn, targets, rule, *charts.milestone_layers(marks)).properties(height=MEDIUM + 40)),
             views={visible.name: ("compare_lines_",)})
        st.caption("The strategies match until retirement and separate after it. Lines are worked out month by month: "
                   "no single path follows them.")
    with card("compareyears"):
        flows = available_flows(strategies)
        left, mid, right = st.columns([2.2, 1.6, 1.4], vertical_alignment="bottom")
        with left:
            chart_title("Year by year", "The median across paths of one flow in each year, by strategy.")
        with mid:
            flow = st.selectbox("Flow", flows, key=sticky_choice("compare_flow", flows, DEFAULT_FLOW),
                                format_func=lambda f: f"{f} (withdrawals)" if f == "Spending" else f)
        with right:
            retired = st.toggle("Full retired years only", key=sticky("compare_retired", True),
                                help="Before retirement every strategy is the same, so those years add bars but no "
                                     "difference.")
        bars = yearly_medians(strategies, flow, retired)
        if bars.empty:
            st.info("No full retired financial year falls inside the horizon, so there is nothing to compare year by "
                    "year. Raise *Years to simulate* (Plan, Assumptions).")
            return
        width = 0.84 / len(rules)
        position = {r: i for i, r in enumerate(rules)}
        bars["x0"] = bars["FY ending"] - 0.42 + bars["Strategy"].map(position) * width
        bars["x1"] = bars["x0"] + width * 0.88  # a small gap between neighbouring bars
        bars["Strategy"] = bars["Strategy"].map(STRATEGY_NAMES)
        bars["Period"] = bars["FY ending"].map(charts.period_label)
        outflow = flow in OUTFLOWS
        chart, _ = charts.toggle(alt.Chart(bars).mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
            x=alt.X("x0:Q", axis=charts.fy_axis(bars), scale=charts.fy_scale(bars)), x2="x1:Q",
            y=alt.Y("Value:Q", title=f"Median {flow.lower()}" + (" paid" if outflow else "") + " per year, today's dollars",
                    axis=charts.money_axis()), y2=alt.datum(0), color=colour,
            tooltip=[alt.Tooltip("Period:N", title="Year"), "Strategy:N", alt.Tooltip("Value:Q", title="Median", format="$,.0f")]),
            "Strategy", [STRATEGY_NAMES[r] for r in rules], "strategy_bars")
        first, last = int(bars["FY ending"].min()) - 0.6, int(bars["FY ending"].max()) + 0.6
        # Markers outside the years shown (retirement falls before the first full retired year) would sit on the axis.
        inside = marks.loc[marks["Position"].between(first, last)] if not marks.empty else marks
        draw(charts.with_milestones(alt.layer(chart, charts.zero_rule()).properties(height=MEDIUM), inside, "Position:Q"))
        st.caption("Outflows are shown as positive amounts paid. Medians are taken year by year, so a strategy's bars "
                   "need not come from one path. Fixed spending is the same every year on each path; its median dips "
                   "only where paths ran short and paid less.")


@st.fragment
def future_fan(run, names, marks):
    portfolios = run.portfolios
    with card("fan"):
        left, right = st.columns([2, 1.6], vertical_alignment="center")
        with left:
            chart_title("Simulated future growth", "$100 left alone in each portfolio, after inflation: no additions, "
                                                   "withdrawals or tax.")
        with right:
            selected = st.segmented_control("Portfolio", names, required=True, label_visibility="collapsed",
                                            key=sticky_choice("portfolio_result", names, names[0]))
        fan = portfolios.paths.loc[portfolios.paths["Portfolio"] == selected]
        draw(charts.band_chart(fan, "Growth of $100 in today's dollars · log scale", log=True,
                               color=PORTFOLIO_COLOURS[selected], marks=marks))
        st.caption("Dark band: the middle half of paths. Light band: 90% of paths. Line: the median at each month.")


def markets_page(run):
    plan, portfolios, market = run.plan, run.portfolios, run.market
    page_title("Markets", "The portfolios you entered, how they behaved in history and how the simulated futures are "
                          "built. Investment returns only: your contributions, spending and tax are on the other pages.")
    tickers = list(plan["assets"])
    colours = charts.ticker_colours(tickers)
    cols = st.columns(2, gap="medium")
    for column, (title, section) in zip(cols, (("Outside super", "outside"), ("Inside super", "super"))):
        with column, card(f"alloc_{section}"):
            balance = plan["outside"]["investment_balance"] if section == "outside" else plan["super"]["balance"]
            chart_title(f"{title} · {compact(balance)}",
                        "Rebalanced every January" if plan[section]["rebalance"] == "annual" else "Buy and hold")
            weights = pd.DataFrame([{"Ticker": t, "Weight": w, "Label": f"{t} {w:.0%}", "Amount": w * balance}
                                    for t, w in plan[section]["weights"].items()])
            a, b = st.columns([1, 1.1], vertical_alignment="center")
            with a:
                draw(charts.allocation_pie(weights, tickers))
            with b:
                legend([(f"{t} {w:.0%}", colours[t]) for t, w in zip(weights["Ticker"], weights["Weight"])])
                stats = portfolios.summary.set_index("Portfolio").loc[title]
                st.markdown(f"Historical growth **{share(stats['CAGR'])}** a year  \nVolatility **{share(stats['Volatility'])}**  \n"
                            f"Deepest fall **{share(stats['Maximum drawdown'])}**",
                            help=f"Whole portfolio, {stats['First']} to {stats['Last']}, nominal, measured daily.")
    summary = portfolios.summary.copy()
    for field in ("CAGR", "Volatility", "Maximum drawdown", "Worst calendar year", "Best calendar year", "Positive years"):
        summary[field] *= 100
    first, last = summary["First"].iloc[0], summary["Last"].iloc[0]
    with card("history"):
        chart_title("Historical growth", f"$100 invested at the start of the shared history, {first} to {last}; nominal, "
                                         "log scale.")
        history = portfolios.historical
        names = list(dict.fromkeys(history["Portfolio"]))
        draw(charts.zoomable(charts.toggle(alt.Chart(history).mark_line(strokeWidth=1.8).encode(
            x=alt.X("Date:T", title=None, axis=charts.year_axis(history)),
            y=alt.Y("Growth of 100:Q", scale=alt.Scale(type="log"), title="Growth of $100 · log scale",
                    axis=charts.log_axis(float(history["Growth of 100"].min()), float(history["Growth of 100"].max()))),
            color=alt.Color("Portfolio:N", scale=alt.Scale(domain=names, range=[PORTFOLIO_COLOURS[n] for n in names])),
            tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Portfolio:N", alt.Tooltip("Growth of 100:Q", format="$,.0f")]
        ).properties(height=MEDIUM), "Portfolio", names, "history")[0]))
        st.dataframe(summary.drop(columns=["First", "Last"]), width="stretch", hide_index=True, column_config={
            "CAGR": percent_column("CAGR", "Compound annual growth rate of the whole portfolio over the full shared history."),
            "Volatility": percent_column("Volatility", "Standard deviation of daily portfolio returns times √252."),
            "Maximum drawdown": percent_column("Max drawdown", "Deepest fall from an earlier peak, measured daily."),
            "Longest drawdown (years)": st.column_config.NumberColumn("Longest drawdown (yrs)", format="%.1f",
                                                                      help="Longest time from a peak until it was regained."),
            "Worst calendar year": percent_column("Worst year"), "Best calendar year": percent_column("Best year"),
            "Positive years": percent_column("Positive years", "Share of full calendar years with a gain.", 0)})
        shares = portfolios.combined_shares
        explain(f"Statistics for each portfolio as a whole ({market.manifest['common_returns']:,} joint daily returns, USD "
                "total returns), using the same rebalancing as the simulations. Historical returns are **nominal**: the "
                "source data have no inflation history. On a log scale equal vertical distances are equal percentage "
                "changes, so a straight line means steady compound growth. Reconstructed pre-fund history is a model, "
                "not observed fund performance. Rebalancing matters: an annually rebalanced mix of volatile, weakly "
                "correlated assets can grow faster than any of its parts, because each January it sells what rose and "
                "buys what fell."
                + (f" The **combined** portfolio is both accounts together: {shares['Outside super']:.1%} outside and "
                   f"{shares['Inside super']:.1%} inside super at the start, by invested balance. Each account keeps its "
                   "own mix; money never moves between them, so the split drifts with returns." if shares else ""))
    names = [p for p in ("Outside super", "Inside super", "Combined") if p in set(portfolios.paths["Portfolio"])]
    future_fan(run, names, milestones(plan, portfolios.dates[0], portfolios.dates[-1]))
    outcomes = portfolios.outcomes
    with card("distributions"):
        chart_title("How the simulated paths differ", f"{plan['market']['paths']:,} paths; dashed lines are medians.")
        a, b = st.columns(2, gap="medium")
        with a:
            draw(charts.overlay_histogram(outcomes, "Annualised growth", "Growth per year after inflation", series=tuple(names)))
        with b:
            draw(charts.overlay_histogram(outcomes, "Maximum drawdown", "Deepest fall from a peak", series=tuple(names)))
        table = []
        for title in names:
            part = outcomes.loc[outcomes["Portfolio"] == title]
            t = percentile_table(part, {"Ending value of $100 (today's dollars)": ("Terminal growth of 100", "money"),
                                        "Annualised growth after inflation": ("Annualised growth", "percent"),
                                        "Annualised volatility": ("Annualised volatility", "percent"),
                                        "Maximum drawdown": ("Maximum drawdown", "percent"),
                                        "Longest drawdown (years)": ("Longest drawdown (years)", "number")})
            t.insert(0, "Portfolio", title)
            table.append(t)
        table = pd.concat(table)
        st.dataframe(table, width="stretch", hide_index=True, height=fit(table))
        st.caption("Read across a row: 5% of paths fall below the 5th-percentile value, half below the median. For "
                   "drawdowns the 5th percentile is the severe end.")
    with st.expander("Ticker-level source statistics", icon=":material/table:"):
        asset_table = market.asset_summary.copy()
        for field in ("Full-sample CAGR", "Daily volatility, annualised", "Maximum drawdown", "Cash contribution proxy"):
            asset_table[field] *= 100
        st.dataframe(asset_table, width="stretch", hide_index=True, column_config={
            "Full-sample CAGR": percent_column("CAGR"), "Daily volatility, annualised": percent_column("Volatility"),
            "Maximum drawdown": percent_column("Max drawdown"),
            "Cash contribution proxy": percent_column("Cash proxy %/yr", digits=2),
            "Observations": st.column_config.NumberColumn(format="%,d")})
        st.caption("Each ticker over its own full history. The cash proxy averages annual sums of daily cash distributions "
                   "over complete years. The tax ledger uses it to split total return into income and price; it is not "
                   "added to growth. No Australian franking is inferred from these USD sources.")


def method_page(run):
    plan, portfolios, market = run.plan, run.portfolios, run.market
    strategies = run.strategies or {run.rule: run}
    page_title("Method", "How the results are calculated, what the amounts mean and where the files are.")
    cpi = plan["assumptions"]["cpi_annual"]
    n, years = plan["market"]["paths"], (portfolios.dates[-1] - portfolios.dates[0]).days / 365.25
    left, right = st.columns(2, gap="medium")
    with left, card("broad"):
        st.subheader("The broad strokes")
        st.markdown(f"""
1. **Markets.** {n:,} possible futures are built by stitching together random stretches of real daily market
   history. The first **{len(run.retirement_paths):,}** go through the full ledger. Each future applies the same market
   days to your outside-super and super portfolios.
2. **Your money, day by day.** For each future, a ledger follows every dollar from {run.result.daily.index[0].date()} to
   {run.result.daily.index[-1].date()}: pay comes in, spending goes out, what is left is invested, investments grow or
   fall with the market, and super receives your contributions.
3. **Retirement.** When your salary stops, spending follows your strategy. It is paid from cash, then from outside
   investments, then from super once you can access it, and the account-based pension pays at least its legal minimum.
4. **Tax.** Australian tax is worked out each year as the law applies it: income tax and capital gains tax on your own
   investments, tax inside super, and the extra tax on super balances over 3 million dollars. Later years use
   thresholds projected with your inflation and wage assumptions.
5. **Government support.** From 67 the means-tested Age Pension is added when your assets and income are low enough,
   along with the seniors' tax offset.
6. **Outcomes.** A future **ran out** if any spending or tax could not be paid. A future that never ran out is on the
   **full Age Pension** if any year paid at least 95% of the maximum single rate, on a **part Age Pension** if it was
   paid less, and **self-funded** if it was paid none.

These are resamples of the past, not forecasts. The project's methodology documents give every rule and its source.
""")
    with right, card("dollars"):
        st.subheader("Today's dollars")
        st.markdown(f"""
Every result is in today's dollars: what it would buy on {plan['plan']['start_date']}, the plan's start, at the assumed
{cpi:.1%} CPI. So \\$90,000 in 2045 and \\$90,000 today mean the same standard of living. (A nominal \\$1,000,000 in 20
years is about \\${1e6 / (1 + cpi) ** 20:,.0f} in today's dollars.)

| Item | How it is shown |
| --- | --- |
| Wealth and balances | Divided by the price level on their date |
| Yearly money in and out | Divided by (1 + CPI) to the power of whole financial years since the start, the step on which spending rises each 1 July |
| "Inflation" in money in and out | The buying power wealth lost that year, so each year's bars still add up |
| Simulated portfolio growth (Markets) | After inflation; volatility and drawdowns use nominal daily returns |
| Historical returns (Markets) | **Nominal**: the source data have no history of inflation |
| Withdrawal rates | Ratios of nominal amounts, so unaffected |
| Event log and CSV downloads | The ledger's **nominal** records |

The tax ledger itself runs in nominal dollars, because tax brackets, caps and the CGT discount are set in nominal
dollars. Only the reporting is converted.
""")
    with card("simulations"):
        st.subheader("How the market paths are simulated")
        st.markdown(f"""
1. **Source history.** The selected tickers' daily total returns on their shared dates, {market.manifest['common_first']}
   to {market.manifest['common_last']}: {market.manifest['common_returns']:,} rows, one return per ticker per row. A row
   keeps the tickers' same-day co-movement.
2. **Stationary block bootstrap.** Each simulated path is a sequence of whole source rows for the
   {len(portfolios.dates) - 1:,} future trading days from {portfolios.dates[0]} to {portfolios.dates[-1]} ({years:.1f} years),
   as many per year as the source history has (weekdays evenly thinned; not a holiday forecast). A path starts at a
   random row and copies consecutive rows (a *block*). After each day it jumps to a new random row with probability
   1/{plan['market']['block_length']}, so blocks average {plan['market']['block_length']} trading days. Blocks keep
   short-run momentum, volatility clusters and crash sequences; jumping between blocks mixes eras.
3. **Same draws for every portfolio and strategy.** Path *k* uses the same rows for outside super, inside super and
   every compared spending strategy. Differences come only from weights and strategies, not luck.
4. **Daily compounding.** Each ticker position grows by its daily return. With annual rebalancing, on the first trading
   day of each calendar year the positions are reset to the target weights before that day's return.

Seed {plan['market']['seed']} makes the run repeatable. With {n:,} paths the median is stable to well under a
percentage point of annual growth; the 5th percentile rests on about {max(1, n // 20)} paths, so tails are less precise.
Every sampled day is a real historical day, so no single day is worse than the worst day in the source; but blocks can
repeat and join bad stretches, so a path can contain longer or deeper losses than history did.
""")
    if run.folder:
        nested = len(strategies) > 1
        with card("files"):
            st.subheader("Saved files")
            st.markdown(f"The plan, path summaries, the median path's daily ledger, a manifest and PNG review plots are in "
                        f"`{run.folder}`" + (", with each strategy's own files in `strategies/`." if nested else "."))
            with st.expander("PNG review plots", icon=":material/image:"):
                shared = ("portfolio_history.png", "portfolio_future.png", "portfolio_distributions.png") + \
                    (("comparison_wealth.png", "comparison_spending.png") if nested else ())
                files = [(run.folder / name, "") for name in shared]
                for rule in strategies:
                    own = run.folder / "strategies" / rule if nested else run.folder
                    files += [(own / name, f"{STRATEGY_NAMES[rule]}: " if nested else "")
                              for name in ("retirement_outcomes.png", "retirement_range.png", "retirement_markets.png",
                                           "retirement_flows.png", "ledger.png")]
                for file, prefix in files:
                    if file.exists():
                        st.image(str(file), caption=prefix + file.name.replace("_", " ").replace(".png", ""))
    with st.expander("Assumptions behind the rules", icon=":material/gavel:"):
        for year, manifest in run.rules_manifest.items():
            st.markdown(f"**{year}**: " + "; ".join(f"`{name}`" for name in manifest["assumptions"]))

