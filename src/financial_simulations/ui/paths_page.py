"""The Paths page: one path's daily ledger in full, or a group of paths summarised."""

from datetime import date

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from financial_simulations.reporting.palette import INK, MUTED, SERIES
from financial_simulations.retirement.flows import account_flows, fold_taxes, household_flows
from financial_simulations.retirement.outcomes import TIERS, ending_percentiles
from financial_simulations.retirement.path_markets import PORTFOLIO, group_markets, path_markets, real_growth
from financial_simulations.retirement.plan import slug
from financial_simulations.retirement.real import real_daily, real_events, year_deflator
from financial_simulations.retirement.run_plan import ledger_for_path
from financial_simulations.rules.au.superannuation import age_on
from financial_simulations.ui import charts
from financial_simulations.ui.results import derived, header, kept_tabs
from financial_simulations.ui.state import (affected, compact, fit, key, money_column, ordinal, percent_column, plural,
                                            result_key, share, sticky, sticky_choice)
from financial_simulations.ui.theme import SHORT, card, chart_title, draw, explain


def selected_ledger(run, path):
    """The full daily ledger for one path, re-run on demand and kept for this result."""
    if path == run.representative_path:
        return run.result
    cache = st.session_state.setdefault("ledger_cache", {})
    if (id(run), path) not in cache:
        cache[(id(run), path)] = ledger_for_path(run.plan, run.market, run.portfolios, path)
    return cache[(id(run), path)]


def choices_for(run, d):
    """The picker's options: the median path, the groups, then every path from the worst ending wealth."""
    outcomes = d.outcomes.sort_values("Ending wealth")
    ranks = ending_percentiles(outcomes)
    choices = {f"Median ending wealth · path {run.representative_path}": run.representative_path}
    headings = {}
    for name, members in d.groups.items():
        label = "all paths" if name == "All paths" else name if name in TIERS else f"the {name.lower()}"
        choice = f"Group: {label} · {plural(len(members), 'path')}"
        choices[choice] = members
        headings[choice] = name if name == "All paths" or name in TIERS else f"The {name.lower()} of paths"
    for path, tier in zip(outcomes["Path"].astype(int), outcomes["Outcome"]):
        choices[f"Path {path} · {ordinal(ranks[path])} percentile · {tier.lower()}"] = path
    return choices, headings, ranks


def page(run):
    run = header(run, "Paths", "One market path's daily ledger in full, or a group of paths summarised.")
    d = derived(run)
    choices, headings, ranks = choices_for(run, d)
    picked = st.selectbox("Path or group to inspect", list(choices),
                          key=sticky_choice(result_key(run, "ledger_path"), list(choices)),
                          help=f"The default is path {run.representative_path}: its ending wealth is closest to the "
                               "median. A median ending does not make every year median. Groups summarise several paths: "
                               "the outcome groups are the headline tiles on the Outcomes page, and the others rank "
                               "paths by ending wealth, so the worst 5% is what bad outcomes typically look like, not "
                               "one unlucky path. Single paths follow, from the worst ending wealth to the best.")
    if isinstance(choices[picked], list):
        group_view(run, d, choices[picked], headings[picked])
    else:
        path_view(run, d, choices[picked], ranks)


def group_view(run, d, members, label):
    """A group of paths summarised by medians (tiles, balances, table) and by averages for the stacked flows, which
    must add up (ADR 0040)."""
    group = d.outcomes.loc[d.outcomes["Path"].isin(members)]
    st.subheader(f"{label} ({plural(len(members), 'path')})")
    if len(members) < 5:
        st.caption(f"Only {plural(len(members), 'path')} in this group, so its figures rest on very few market sequences. "
                   "Raise *Daily retirement-ledger paths* (Plan, Assumptions) for a steadier picture.")
    a, b, c, e = st.columns(4)
    a.metric("Wealth at retirement (median)", compact(float(group["Wealth at retirement"].median())))
    b.metric("Ending wealth (median)", compact(float(group["Ending wealth"].median())))
    c.metric("Average spending per retired year", compact(float(group["Average retired-year spending"].median())),
             help="Each path's spending paid, averaged over its full retired financial years; the group's median path.")
    e.metric("Withdrawal rate (median)", share(float(group["Median withdrawal rate"].median())),
             help="The median, across the group, of each path's median withdrawal rate over its retired years.")
    a, b, c, e = st.columns(4)
    a.metric("Ran out", share(float((group["Status"] == "depleted").mean())),
             help="Share of the group's paths with any unpaid spending or tax.")
    b.metric("Shortfall: paths · median", affected(group["Spending shortfall"]),
             help="Share of the group's paths with any unpaid spending, then the median total shortfall among them.")
    c.metric("Age Pension: paths · median", affected(group["Age Pension received"]),
             help="Share of the group's paths paid any Age Pension, then the median total received among them.")
    e.metric("Reached the full Age Pension", share(float((group["Full Age Pension years"] > 0).mean())),
             help="Share of the group's paths with at least one year paid the full rate.")
    tabs = kept_tabs(result_key(run, "group_tabs"), ["Markets, wealth and money", "Year by year"])
    if tabs[0].open:
        with tabs[0]:
            group_story(run, d, members, label)
    if tabs[1].open:
        with tabs[1]:
            raw = run.retirement_annual.loc[run.retirement_annual["Path"].isin(members)]
            table = raw.groupby("FY ending")[[c for c in ("Wealth at 1 July", "Spending paid", "Tax paid", "Age Pension",
                                                          "Pension payments", "Withdrawal rate") if c in raw]].median().reset_index()
            short = raw.groupby("FY ending")["Shortfall"].agg(lambda x: 100 * float((x > 0).mean()))
            table.insert(3, "Paths with a shortfall", table["FY ending"].map(short).to_numpy())
            pensioners = raw.groupby("FY ending")["Age Pension"].agg(lambda x: 100 * float((x > 0).mean()))
            table.insert(4, "Paths on Age Pension", table["FY ending"].map(pensioners).to_numpy())
            table.insert(0, "Year", table["FY ending"].map(charts.period))
            table.insert(1, "Age at 30 June", [age_on(d.born, date(int(y), 6, 30)) for y in table["FY ending"]])
            if "Withdrawal rate" in table:
                table["Withdrawal rate"] *= 100
            shares = ("Withdrawal rate", "Paths with a shortfall", "Paths on Age Pension")
            st.dataframe(table.drop(columns="FY ending"), width="stretch", hide_index=True, height=fit(table, 22),
                         column_config={"Year": st.column_config.TextColumn("Year (1 July – 30 June)", pinned=True),
                                        "Age at 30 June": st.column_config.NumberColumn(format="%d"),
                                        **{c: percent_column(c) for c in shares},
                                        **{c: money_column(c) for c in table.columns
                                           if c not in ("Year", "Age at 30 June", "FY ending", *shares)}})
            st.caption("Medians across the group's paths for each year, today's dollars, each column taken on its own. "
                       "The two share columns count the group's paths with unpaid spending, and paid any Age Pension, "
                       "that year.")


def story_colours(run, stats):
    """Each market series' kind and colour: the portfolios dark, each ticker its colour from the Markets page."""
    kinds = dict(zip(stats["Series"], stats["Kind"]))
    tickers = charts.ticker_colours(run.plan["assets"])
    portfolio_colours = iter((INK, MUTED))
    return kinds, {name: next(portfolio_colours) if kind == PORTFOLIO else tickers[name] for name, kind in kinds.items()}


@st.fragment
def group_story(run, d, members, label):
    """Markets, balances and money in and out for a group of paths, stacked on one date axis.

    Medians for the markets and the balances, averages for the flows, which must add up (ADR 0040).
    """
    cpi = run.plan["assumptions"]["cpi_annual"]
    cache = st.session_state.setdefault("group_markets_cache", {})
    if (id(run), label) not in cache:
        if len(cache) > 12:
            cache.clear()
        with st.spinner(f"Compounding the markets of {plural(len(members), 'path')} day by day..."):
            cache[(id(run), label)] = group_markets(run.plan, run.market, run.portfolios, members)
    growth, stats = cache[(id(run), label)]
    series = run.path_series.loc[run.path_series["Path"].isin(members)] if run.path_series is not None else None
    annual = d.annual.loc[d.annual["Path"].isin(members)]
    flows = [c for c in annual.columns if c.startswith("Flow: ")]
    if series is None or series.empty or not flows:
        st.caption("This run has no month-end balances or yearly flows to draw.")
        return
    series = series.assign(Accumulation=series["Super and pension"] - series["Pension account"])
    middle = series.groupby("Date")[["Outside super", "Accumulation", "Pension account"]].median()
    balances = pd.DataFrame({"cash": 0.0, "outside_investments": middle["Outside super"],
                             "accumulation": middle["Accumulation"], "pension": middle["Pension account"]},
                            index=pd.DatetimeIndex(middle.index, name="Date"))
    balances["total"] = balances.sum(axis=1)
    yearly = annual.groupby("FY ending")[flows + ["Net change in wealth", "Added to outside investments"]].mean().reset_index()
    household = yearly.melt("FY ending", value_vars=flows, var_name="Flow", value_name="AUD")
    household["Flow"] = household["Flow"].str.replace("Flow: ", "", regex=False)
    household["Net change"] = household["FY ending"].map(yearly.set_index("FY ending")["Net change in wealth"])
    additions = yearly[["FY ending", "Added to outside investments"]].rename(columns={"Added to outside investments": "AUD"})
    kinds, colours = story_colours(run, stats)
    _, items = charts.flow_items(household, additions)
    with card("groupstory"):
        chart_title("Markets, wealth and money across the group",
                    "The same three views as a single path, summarised over the group's paths: median markets, median "
                    "balances and average flows.")
        market_table(stats, "Median across the group")
        with st.container(horizontal=True, vertical_alignment="center"):
            states = {"markets": legend_controls("path_markets", list(growth.columns), "Markets"),
                      "flows": legend_controls("path_flows", items, "Money in and out")}
        st.caption("Click a legend item to hide or show it; the axis refits. Drag any panel sideways to pan all three, "
                   "Shift+scroll to zoom, double-click to reset.")
        with st.container(key="pathstorychart"):
            draw(*charts.path_story(real_growth(growth, cpi), kinds, colours, balances, household, additions, d.marks,
                                    states, group=True))
        explain("**Markets (top).** For each portfolio and ticker, the median across the group's paths of what $1 "
                "invested on the first day is worth at each month end, in today's dollars, on a log scale. The table "
                "gives the median of each path's own growth per year, volatility and worst drawdown. Each line's "
                "median is taken on its own, so the lines need not come from one path: a group of bad outcomes "
                "shows what markets typically did on those paths.\n\n"
                "**Wealth (middle).** The median month-end balance of each account across the group's paths; outside "
                "investments include cash. Each account's median is taken on its own, so the stacked total need not "
                "equal any one path's wealth. Medians are used because one extreme path can pull an average a long "
                "way, especially in the open-ended best and worst groups.\n\n"
                "**Money in and out (bottom).** Each bar is the **average** of that flow across the group's paths in "
                "that financial year, unlike the medians above: averages add up, so the bars sum to the average net "
                "change in wealth (black line). Tax adds income, contributions, fund and Division 296 tax.")


def legend_controls(name, names, label=None):
    """Show all / Show none buttons for a chart whose legend hides and shows its items.

    Legend clicks are handled inside the chart, so they need no rerun. The buttons rebuild the chart with every
    item shown or hidden; the counter changes the chart spec each time so a repeated press still resets it.
    ``label`` names the legend when one chart has several, in place of the hint.
    """
    state = st.session_state.get(f"{name}_legend", {"hidden": [], "count": 0})
    with st.container(horizontal=True, vertical_alignment="center"):
        if label:
            st.markdown(f"**{label}**", width="content")
        if st.button("Show all", key=f"{name}_all", type="tertiary", icon=":material/visibility:"):
            state = {"hidden": [], "count": state["count"] + 1}
        if st.button("Show none", key=f"{name}_none", type="tertiary", icon=":material/visibility_off:"):
            state = {"hidden": list(names), "count": state["count"] + 1}
        if not label:
            st.caption("Click a legend item to hide or show it; the axis refits.")
    st.session_state[f"{name}_legend"] = state
    return state


def path_flow_frames(run, result, daily):
    """One path's yearly household flows (taxes folded), account transfers and additions to outside investments."""
    start, cpi = daily.index[0], run.plan["assumptions"]["cpi_annual"]
    household = fold_taxes(household_flows(daily, inflation=True))
    moves = account_flows(daily, real_events(result.events, start, cpi))
    invested = moves.loc[moves["Flow"] == "Savings invested"] if not moves.empty else moves
    additions = (invested.groupby("FY ending")["AUD"].sum() if not invested.empty else pd.Series(dtype=float, name="AUD"))
    additions = additions.reindex(sorted(household["FY ending"].unique()), fill_value=0.0).rename_axis("FY ending").reset_index(name="AUD")
    return household, moves, additions


def selected_markets(run, path):
    """One path's growth of $1 by series and its statistics, kept for this result."""
    cache = st.session_state.setdefault("markets_cache", {})
    if (id(run), path) not in cache:
        if len(cache) > 24:
            cache.clear()
        cache[(id(run), path)] = path_markets(run.plan, run.market, run.portfolios, path)
    return cache[(id(run), path)]


def market_table(stats, heading="On this path"):
    """Each series' growth and risk, portfolios first."""
    table = stats.drop(columns="Kind").copy()
    weights = [c for c in table.columns if c.endswith(" weight")]
    if (stats["Kind"] == PORTFOLIO).sum() == 1:  # one portfolio in both places: one weight column
        table = table.drop(columns=weights[1:]).rename(columns={weights[0]: "Weight"})
        weights = ["Weight"]
    shares = ["CAGR", "CAGR after inflation", "Volatility", "Worst drawdown"]
    table[shares] *= 100
    for column in weights:  # text, so a portfolio's row is blank rather than "None"
        table[column] = table[column].map(lambda w: "" if pd.isna(w) else f"{w:.0%}")
    st.dataframe(table, width="stretch", hide_index=True, height=fit(table, 8),
                 column_config={"Series": st.column_config.TextColumn(heading, pinned=True),
                                "CAGR": st.column_config.NumberColumn(
                                    "Growth per year (CAGR)", format="%.1f%%",
                                    help="Compound annual growth of $1 over the whole path, before inflation."),
                                "CAGR after inflation": st.column_config.NumberColumn(
                                    "CAGR after inflation", format="%.1f%%",
                                    help="The same growth after the plan's inflation assumption: growth in buying power."),
                                "Volatility": st.column_config.NumberColumn(
                                    "Volatility (st. dev.)", format="%.1f%%",
                                    help="Standard deviation of the path's daily returns, scaled to a year (times the "
                                         "square root of 252)."),
                                "Worst drawdown": st.column_config.NumberColumn(
                                    format="%.1f%%", help="The deepest fall below a previous high on this path."),
                                "Growth of $1 after inflation": st.column_config.NumberColumn(
                                    "$1 grew to (today's dollars)", format="dollar",
                                    help="What $1 invested on the first day is worth on the last, in today's dollars."),
                                **{w: st.column_config.TextColumn(alignment="right") for w in weights}})


@st.fragment
def path_story(run, d, path, result, daily):
    """Markets, balances and money in and out for one path, stacked on one date axis."""
    cpi = run.plan["assumptions"]["cpi_annual"]
    growth, stats = selected_markets(run, path)
    household, _, additions = path_flow_frames(run, result, daily)
    kinds, colours = story_colours(run, stats)
    _, items = charts.flow_items(household, additions)
    with card("pathstory"):
        chart_title("Markets, wealth and money on this path",
                    "Three views of the same years on one date axis: what markets did, what your accounts held, and "
                    "the money that came in and went out.")
        market_table(stats)
        with st.container(horizontal=True, vertical_alignment="center"):
            states = {"markets": legend_controls("path_markets", list(growth.columns), "Markets"),
                      "flows": legend_controls("path_flows", items, "Money in and out")}
        st.caption("Click a legend item to hide or show it; the axis refits. Drag any panel sideways to pan all three, "
                   "Shift+scroll to zoom, double-click to reset.")
        # Streamlit gives each stacked panel the container's full width and the y axis is drawn outside that, so
        # this container is narrower by the axis's width (see the pathstorychart rule in theme.py).
        with st.container(key="pathstorychart"):
            draw(*charts.path_story(real_growth(growth, cpi), kinds, colours, daily, household, additions, d.marks, states))
        explain("**Markets (top).** Each line is $1 invested on the first day, in today's dollars, on a log scale: a "
                "steady slope is steady growth, and a crash is the same drop wherever it happens. The thick line is "
                "your portfolio at its entered weights; the thin lines are its tickers. The table above gives each "
                "line's growth per year, volatility and worst drawdown on this path, all worked out from the path's "
                "daily returns. Leveraged tickers swing far more than the portfolio: hide them in the legend to look "
                "closer.\n\n"
                "**Wealth (middle).** Month-end balances by account, stacked. Outside money funds spending until super "
                "becomes accessible, then super moves into the pension. Wealth follows the market line above, less what "
                "you spend and pay in tax.\n\n"
                "**Money in and out (bottom).** One bar per financial year (1 July to 30 June). Above zero: take-home "
                "salary, super contributions, the Age Pension and investment returns in good years. Below zero: "
                "spending, tax (income tax, the 15% contributions tax, super fund tax and Division 296 tax together), "
                "investment losses in bad years and inflation (the buying power wealth lost that year). The black line "
                "is the net change in total wealth, which equals the sum of the bars. The dashed line is what was "
                "**added to outside investments**: it moves money from cash into the portfolio, so it is a line "
                "rather than a bar.\n\n"
                "The hairline marks the same month in all three panels, so a market fall can be read straight down "
                "to its effect on wealth and on that year's investment returns.")


@st.fragment
def path_moves(run, d, result, daily, marks):
    household, moves, _ = path_flow_frames(run, result, daily)
    x = alt.X("FY ending:Q", axis=charts.fy_axis(household), scale=charts.fy_scale(household))
    if moves.empty:
        st.caption("No money moved between accounts on this path.")
        return
    with card("pathmoves"):
        chart_title("Money moving into and out of each account", "Transfers only, excluding investment growth.")
        for account in ("Outside investments", "Super (accumulation)", "Account-based pension"):
            part = moves.loc[moves["Account"] == account].copy()
            if part.empty:
                st.caption(f"{account}: no transfers on this path.")
                continue
            part["Period"] = part["FY ending"].map(charts.period_label)
            flows = sorted(part["Flow"].unique())
            name = "path_moves_" + account.split()[0].lower()
            st.markdown(f"**{account}**")
            state = legend_controls(name, flows)
            # A fixed colour domain keeps hidden flows in the legend so they can be shown again.
            chart, _ = charts.hideable(alt.Chart(part).mark_bar(size=12, stroke="#ffffff", strokeWidth=0.6).encode(
                x=x, y=alt.Y("sum(AUD):Q", title="Today's dollars", axis=charts.money_axis()),
                color=alt.Color("Flow:N", scale=alt.Scale(domain=flows, range=list(SERIES[:len(flows)])),
                                legend=alt.Legend(symbolType="square")),
                tooltip=[alt.Tooltip("Period:N", title="Year"), "Flow:N", alt.Tooltip("AUD:Q", format="$,.0f")]),
                "Flow", flows, state, name)
            draw(charts.with_milestones(alt.layer(chart, charts.zero_rule()).properties(height=SHORT), marks, "Position:Q"))
        explain("Outside investments receive your leftover pay and are sold to pay spending and tax; super receives "
                "contributions (after the 15% tax), pays fund tax and moves into the pension; the pension pays you at "
                "least the yearly minimum.")


def yearly_table(run, d, result, start):
    cpi = run.plan["assumptions"]["cpi_annual"]
    rows = []
    for x in result.annual:
        end_year = int(x["financial_year"][:4]) + 1
        flow = year_deflator(end_year, start, cpi)  # this year's amounts in today's dollars
        balance = (1 + cpi) ** ((pd.Timestamp(date(end_year, 6, 30)) - start).days / 365.25)
        rows.append({"Year": charts.period(end_year), "Age at 30 June": age_on(d.born, date(end_year, 6, 30)),
                     "Spending paid": x["spending_paid"] / flow, "Shortfall": x["shortfall"] / flow,
                     "Age Pension": x.get("age_pension", 0.0) / flow,
                     "Taxable income": x["assessment"].taxable_income / flow,
                     "Net tax": (x["assessment"].net_tax + x["assessment"].division_293_tax) / flow,
                     "Net capital gain": x["assessment"].net_capital_gain / flow,
                     "SAPTO": x["assessment"].sapto / flow,
                     "Division 296 tax": x.get("division_296_tax", 0.0) / flow,
                     "Concessional contributions": x["concessional_contributions"] / flow,
                     "Cap available": x["concessional_cap_available"] / flow,
                     "Pension minimum": (x["pension_minimum"] or 0.0) / flow, "Pension paid": (x["pension_paid"] or 0.0) / flow,
                     "Transfer balance": (x["transfer_balance"] or 0.0) / balance,
                     "Super at 30 June": x["total_super_balance_30_june"] / balance})
    frame = pd.DataFrame(rows)
    st.dataframe(frame, width="stretch", hide_index=True, height=fit(frame, 22),
                 column_config={"Year": st.column_config.TextColumn("Year (1 July – 30 June)", pinned=True),
                                "Age at 30 June": st.column_config.NumberColumn(format="%d"),
                                **{c: money_column(c) for c in frame.columns if c not in ("Year", "Age at 30 June")}})
    st.caption("Amounts in today's dollars; each row is a financial year. Taxable income includes realised capital gains "
               "after the discount; the pension columns show the legislated minimum and what was actually paid; the "
               "transfer balance counts amounts moved into the tax-free pension against the cap; the cap available "
               "includes carried-forward unused concessional cap when your balance allows it.")
    outstanding = result.outstanding
    if outstanding["tax_liabilities"] or outstanding["unassessed_year"] or outstanding["unpaid_tax"]:
        st.caption(f"At the horizon: tax not yet due {[l['financial_year'] for l in outstanding['tax_liabilities']]}; "
                   f"unpaid tax {[u['financial_year'] for u in outstanding['unpaid_tax']]}; partial year not yet assessed "
                   f"{(outstanding['unassessed_year'] or {}).get('financial_year')}.")


def path_view(run, d, path, ranks):
    with st.spinner(f"Running the daily ledger for path {path}..."):
        result = selected_ledger(run, path)
    cpi = run.plan["assumptions"]["cpi_annual"]
    daily = real_daily(result.daily, cpi)
    start = daily.index[0]
    outcome = d.outcomes.set_index("Path").loc[path]
    st.subheader(f"Path {path} · {outcome['Outcome'].lower()}")
    a, b, c, e = st.columns(4)
    a.metric("Wealth at retirement", compact(outcome["Wealth at retirement"]),
             help="Total wealth on your retirement date.")
    b.metric(f"Wealth at {daily.index[-1].date():%B %Y}", compact(daily["total"].iloc[-1]),
             help=f"The {ordinal(ranks[path])} percentile of ending wealth among calculated paths.")
    c.metric("Average spending per retired year", compact(outcome["Average retired-year spending"]),
             help="Spending paid, averaged over this path's full retired financial years. Its lowest retired year paid "
                  f"{compact(outcome['Lowest retired-year spending'])}.")
    e.metric("Largest fall in wealth", share(float((daily["total"] / daily["total"].cummax() - 1).min())),
             help="Deepest fall of total wealth below its previous high on this path. Unlike a portfolio drawdown it "
                  "includes spending, so it keeps falling in retirement even in flat markets.")
    a, b, c, e = st.columns(4)
    a.metric("Age Pension received", compact(daily["age_pension"].sum()) if "age_pension" in daily else "–",
             help=(f"First paid {outcome['Age Pension first paid']}; {outcome['Age Pension years']} financial years with a "
                   f"payment, {outcome['Full Age Pension years']} of them at the full rate."
                   if outcome["Age Pension first paid"] else "This path never received the Age Pension."))
    b.metric("Spending shortfall", compact(daily["shortfall"].sum()),
             help=f"First ran short {outcome['First shortfall']}." if outcome["First shortfall"] else "Every dollar of spending was paid.")
    c.metric("Tax (personal, fund, Division 296)",
             compact(sum((x["assessment"].net_tax + x["assessment"].division_293_tax)
                         / year_deflator(int(x["financial_year"][:4]) + 1, start, cpi) for x in result.annual)
                     + daily["fund_tax"].sum() + daily["division_296"].sum()))
    e.metric("Wealth when super becomes accessible", compact(outcome.get("Wealth when super accessible", np.nan)),
             help="Total wealth on the first day super can be withdrawn (preservation age and retirement), when that "
                  "is after the start.")
    tabs = kept_tabs(result_key(run, "path_tabs"), ["Markets, wealth and money", "Transfers between accounts",
                                                    "Year by year", "Event log"])
    if tabs[0].open:
        with tabs[0]:
            path_story(run, d, path, result, daily)
    if tabs[1].open:
        with tabs[1]:
            path_moves(run, d, result, daily, d.marks)
    if tabs[2].open:
        with tabs[2]:
            yearly_table(run, d, result, start)
    if tabs[3].open:
        with tabs[3]:
            event_log(run, result, path)


@st.fragment
def event_log(run, result, path):
    events = result.events
    kinds = sorted(events["event"].unique())
    default = [k for k in kinds if k not in ("buy", "distribution")]
    widget = sticky(result_key(run, "event_types"), default)
    st.session_state[widget] = [k for k in st.session_state[widget] if k in kinds]
    chosen = st.multiselect("Event types", kinds, key=widget)
    st.dataframe(events.loc[events["event"].isin(chosen)], width="stretch", hide_index=True, height=460,
                 column_config={"amount": money_column("amount")})
    st.caption("Nominal dollars, as the ledger records them.")
    name = slug(run.plan["plan"]["name"]) + (f"-{run.rule}" if len(run.strategies or {}) > 1 else "")
    with st.container(horizontal=True):
        # Keyed per strategy: identical unkeyed buttons would clash.
        st.download_button("Daily ledger (CSV, nominal)", result.daily.to_csv(), f"{name}-path{path}-daily.csv", "text/csv",
                           key=key(result_key(run, "download_daily")), icon=":material/download:")
        st.download_button("Events (CSV, nominal)", result.events.to_csv(index=False), f"{name}-path{path}-events.csv",
                           "text/csv", key=key(result_key(run, "download_events")), icon=":material/download:")
