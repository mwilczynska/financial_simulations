"""The Compare and Markets pages."""

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
        bars = charts.with_period(bars)
        outflow = flow in OUTFLOWS
        chart, _ = charts.toggle(alt.Chart(bars).mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
            x=alt.X("x0:Q", axis=charts.fy_axis(bars), scale=charts.fy_scale(bars)), x2="x1:Q",
            y=alt.Y("Value:Q", title=f"Median {flow.lower()}" + (" paid" if outflow else "") + " per year, today's dollars",
                    axis=charts.money_axis()), y2=alt.datum(0), color=colour,
            tooltip=[*charts.year_tooltip(), "Strategy:N", alt.Tooltip("Value:Q", title="Median", format="$,.0f")]),
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
