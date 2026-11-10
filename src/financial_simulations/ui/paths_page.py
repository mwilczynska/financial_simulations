"""The Paths page: one path's daily ledger in full, or a group of paths summarised."""

from datetime import date

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from financial_simulations.reporting.palette import FLOW_COLOURS, INK, SERIES
from financial_simulations.retirement.flows import account_flows, fold_taxes, household_flows
from financial_simulations.retirement.outcomes import TIERS, ending_percentiles
from financial_simulations.retirement.plan import slug
from financial_simulations.retirement.real import real_daily, real_events, year_deflator
from financial_simulations.retirement.run_plan import ledger_for_path
from financial_simulations.rules.au.superannuation import age_on
from financial_simulations.ui import charts
from financial_simulations.ui.results import derived, header, kept_tabs
from financial_simulations.ui.state import (affected, compact, fit, key, money_column, ordinal, percent_column, plural,
                                            result_key, share, sticky, sticky_choice)
from financial_simulations.ui.theme import MEDIUM, SHORT, card, chart_title, draw, explain, legend


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
    tabs = kept_tabs(result_key(run, "group_tabs"), ["Balances", "Money in and out", "Year by year"])
    annual = d.annual.loc[d.annual["Path"].isin(members)]
    if tabs[0].open:
        with tabs[0]:
            series = run.path_series.loc[run.path_series["Path"].isin(members)] if run.path_series is not None else None
            if series is not None and not series.empty:
                series = series.assign(Accumulation=series["Super and pension"] - series["Pension account"])
                middle = series.groupby("Date")[["Outside super", "Accumulation", "Pension account"]].median()
                frame = pd.DataFrame({"cash": 0.0, "outside_investments": middle["Outside super"],
                                      "accumulation": middle["Accumulation"], "pension": middle["Pension account"]},
                                     index=pd.DatetimeIndex(middle.index, name="Date"))
                with card("groupbalances"):
                    chart_title("Balances by account", "Median month-end balance across the group's paths; outside "
                                                       "super combines cash and investments.")
                    draw(charts.with_milestones(charts.balances_chart(frame), d.marks))
                    explain("Each account's median is taken on its own, so the stacked total need not equal any one "
                            "path's wealth. Medians are used because one extreme path can pull an average a long way, "
                            "especially in the open-ended best and worst groups.")
    flows = [c for c in annual.columns if c.startswith("Flow: ")]
    if tabs[1].open and flows:
        with tabs[1]:
            yearly = annual.groupby("FY ending")[flows + ["Net change in wealth", "Added to outside investments"]].mean().reset_index()
            long = yearly.melt("FY ending", value_vars=flows, var_name="Flow", value_name="AUD")
            long["Flow"] = long["Flow"].str.replace("Flow: ", "", regex=False)
            long = long.groupby("Flow").filter(lambda g: g["AUD"].abs().max() > 1e-6)
            long["Period"] = long["FY ending"].map(charts.period_label)
            yearly["Period"] = yearly["FY ending"].map(charts.period_label)
            order = [f for f in FLOW_COLOURS if f in set(long["Flow"])]
            x = alt.X("FY ending:Q", axis=charts.fy_axis(yearly), scale=charts.fy_scale(yearly))
            domain = charts.flow_domain(long, "AUD", (yearly["Net change in wealth"], yearly["Added to outside investments"]))
            bars = charts.flow_bars(long, x, "AUD", "Average per year, today's dollars", order, domain=domain,
                                    tooltip=[alt.Tooltip("AUD:Q", title="Average", format="$,.0f")])
            line = alt.Chart(yearly).mark_line(color=INK, strokeWidth=2, point=alt.OverlayMarkDef(color=INK, size=30)).encode(
                x=x, y="Net change in wealth:Q",
                tooltip=[alt.Tooltip("Period:N", title="Year"),
                         alt.Tooltip("Net change in wealth:Q", title="Average net change", format="$,.0f")])
            added = charts.additions_layer(yearly.rename(columns={"Added to outside investments": "AUD"}), x)
            layers = [bars, charts.zero_rule(), line] + ([added] if added is not None else [])
            with card("groupflows"):
                chart_title("Money in and out, averaged across the group", "Money in above zero, money out below.")
                legend([("Average net change in wealth", INK, "line"),
                        *([("Added to outside investments", charts.ADDED_COLOUR, "line")] if added is not None else [])])
                draw(charts.with_milestones(alt.layer(*layers).properties(height=MEDIUM + 60), d.marks, "Position:Q"))
                explain("Each bar is the **average** of that flow across the group's paths in that year, unlike the "
                        "medians elsewhere in this group: averages add up, so the bars sum to the average net change "
                        "in wealth (black line). Tax adds income, contributions, fund and Division 296 tax.")
    if tabs[2].open:
        with tabs[2]:
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


def legend_controls(name, names):
    """Show all / Show none buttons for a chart whose legend hides and shows its items.

    Legend clicks are handled inside the chart, so they need no rerun. The buttons rebuild the chart with every
    item shown or hidden; the counter changes the chart spec each time so a repeated press still resets it.
    """
    state = st.session_state.get(f"{name}_legend", {"hidden": [], "count": 0})
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button("Show all", key=f"{name}_all", type="tertiary", icon=":material/visibility:"):
            state = {"hidden": [], "count": state["count"] + 1}
        if st.button("Show none", key=f"{name}_none", type="tertiary", icon=":material/visibility_off:"):
            state = {"hidden": list(names), "count": state["count"] + 1}
        st.caption("Click a legend item to hide or show it; the axis refits.")
    st.session_state[f"{name}_legend"] = state
    return state


@st.fragment
def path_flows(run, d, result, daily, marks):
    start, cpi = daily.index[0], run.plan["assumptions"]["cpi_annual"]
    household = fold_taxes(household_flows(daily, inflation=True))
    household["Period"] = household["FY ending"].map(charts.period_label)
    shown = household.groupby("Flow").filter(lambda g: g["AUD"].abs().max() > 1e-6)
    order = [f for f in FLOW_COLOURS if f in set(shown["Flow"])]
    x = alt.X("FY ending:Q", axis=charts.fy_axis(household), scale=charts.fy_scale(household))
    moves = account_flows(daily, real_events(result.events, start, cpi))
    additions = (moves.loc[moves["Flow"] == "Savings invested"].groupby("FY ending")["AUD"].sum()
                 .reindex(sorted(household["FY ending"].unique()), fill_value=0.0).reset_index(name="AUD"))
    additions["Period"] = additions["FY ending"].map(charts.period_label)
    # No fixed y domain: it refits to whatever the legend leaves visible. The net-change and additions lines are
    # legend items too, so hiding them lets the axis close in on the bars that remain.
    net = household.drop_duplicates("FY ending").assign(Flow=charts.NET_LABEL)
    additions["Flow"] = charts.ADDED_LABEL
    items = order + [charts.NET_LABEL] + ([charts.ADDED_LABEL] if (additions["AUD"].abs() > 1e-6).any() else [])
    colour = charts.flow_colour(items)
    with card("pathflows"):
        chart_title("Money in and out on this path", "Every dollar that changed total wealth each year: in above zero, "
                                                     "out below. The bars add up to the net change.")
        state = legend_controls("path_flows", items)
        bars, visible = charts.hideable(alt.Chart(shown).mark_bar(size=14, stroke="#ffffff", strokeWidth=0.6).encode(
            x=x, y=alt.Y("sum(AUD):Q", title="Per year, today's dollars", axis=charts.money_axis()),
            color=colour, order=alt.Order("Flow:N"),
            tooltip=[alt.Tooltip("Period:N", title="Year"), "Flow:N", alt.Tooltip("AUD:Q", format="$,.0f")]),
            "Flow", items, state, "path_flows")
        line = alt.Chart(net).mark_line(color=INK, strokeWidth=2, point=alt.OverlayMarkDef(color=INK, size=30)).encode(
            x=x, y="Net change:Q", color=colour,
            tooltip=[alt.Tooltip("Period:N", title="Year"), alt.Tooltip("Opening:Q", title="Wealth at start", format="$,.0f"),
                     alt.Tooltip("Net change:Q", title="Net change in wealth", format="$,.0f"),
                     alt.Tooltip("Closing:Q", title="Wealth at end", format="$,.0f")]).transform_filter(visible)
        added = charts.additions_layer(additions, x, color=colour)
        layers = [bars, charts.zero_rule(), line] + ([added.transform_filter(visible)] if added is not None else [])
        draw(charts.with_milestones(alt.layer(*layers).properties(height=MEDIUM + 60), marks, "Position:Q"))
        explain("Above zero: take-home salary, employer and salary-sacrifice contributions into super, the Age Pension "
                "and investment returns in good years. Below zero: spending, tax (income tax, the 15% contributions "
                "tax, super fund tax and Division 296 tax together), investment losses in bad years and inflation (the "
                "buying power wealth lost that year). The black line is the net change in total wealth, which equals "
                "the sum of the bars. The dashed line is what was **added to outside investments** that year, from "
                "your pay or, after retirement, from unspent pension payments and other spare cash: it moves money "
                "from cash into the portfolio, so it is a line rather than a bar.")
    if moves.empty:
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
    tabs = kept_tabs(result_key(run, "path_tabs"), ["Balances", "Money in and out", "Year by year", "Event log"])
    if tabs[0].open:
        with tabs[0], card("pathbalances"):
            chart_title("Balances by account", "Month-end balances, stacked. Outside money funds spending until super "
                                               "becomes accessible, then super moves into the pension.")
            draw(charts.with_milestones(charts.balances_chart(daily), d.marks))
    if tabs[1].open:
        with tabs[1]:
            path_flows(run, d, result, daily, d.marks)
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
