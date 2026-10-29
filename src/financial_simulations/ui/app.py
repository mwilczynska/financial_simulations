"""Browser app for editing, importing, exporting and running a retirement plan.

Launch with ``financial-simulations ui`` (or ``streamlit run`` on this file).
The plan dictionary in session state is the single source of truth: every
tab edits it, the sidebar imports and exports it, and Run writes one folder,
output/plans/<plan-name>/.
"""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from financial_simulations.data.plan_markets import CUSTOM_TICKERS, TICKERS, load_plan_markets
from financial_simulations.reporting.plan import wide_wealth_range
from financial_simulations.retirement.plan import (PlanError, default_plan, load_plan_text, normalize_plan, plan_to_json,
                                                   plan_to_toml, slug)
from financial_simulations.retirement.run_plan import ledger_for_path, run_plan
from financial_simulations.rules.au.parameters import UnsupportedRule


PLANS_DIR = Path("plans")


def cached_market(tickers):
    cache = st.session_state.setdefault("market_cache", {})
    if tickers not in cache:
        cache[tickers] = load_plan_markets(tickers)
    return cache[tickers]


def key(name):
    # Widgets are re-created from the plan whenever a new plan is loaded.
    return f"{name}__{st.session_state.version}"


def load_into_session(plan, message):
    st.session_state.plan = plan
    st.session_state.version += 1
    st.session_state.result = None
    st.session_state.flash = message


def percent(label, value, name, *, low=-50.0, high=50.0, step=0.1, help=None):
    return st.number_input(label, float(low), float(high), round(float(value) * 100, 4), float(step), key=key(name),
                           format="%.2f", help=help) / 100


def money(label, value, name, help=None):
    return float(st.number_input(label, 0.0, 1e9, float(value), 1000.0, key=key(name), format="%.0f", help=help))


def weights_editor(title, current, assets, name):
    st.markdown(f"**{title}**")
    st.caption("Current balance and future purchases use this allocation. Weights must total 100%.")
    weights = {}
    columns = st.columns(2)
    for i, asset in enumerate(assets):
        with columns[i % 2]:
            weights[asset] = st.number_input(asset, 0.0, 100.0, round(current.get(asset, 0.0) * 100, 4), 5.0,
                                             key=key(f"{name}_{asset}"), format="%.1f") / 100
    total = sum(weights.values())
    if abs(total - 1) > 1e-6:
        st.warning(f"{title} total {total:.1%}; adjust to 100%.")
    return {a: w for a, w in weights.items() if w > 0}


REBALANCE_LABELS = {"annual": "Rebalance to these weights every January", "none": "Buy and hold (weights drift)"}


def rebalance_choice(current, name, help):
    return st.radio("Rebalancing", list(REBALANCE_LABELS), index=list(REBALANCE_LABELS).index(current), horizontal=True,
                    format_func=REBALANCE_LABELS.get, key=key(name), help=help)


def sidebar():
    if st.sidebar.button("Run plan", type="primary", width="stretch", key="run_sidebar"):
        st.session_state.run_requested = True
    st.sidebar.caption("Results appear on the Results tab.")
    st.sidebar.header("Plan file")
    upload = st.sidebar.file_uploader("Import a plan (.toml or .json)", type=["toml", "json"], key=key("upload"))
    if upload is not None:
        try:
            load_into_session(load_plan_text(upload.getvalue().decode("utf-8"), upload.name), f"Imported {upload.name}.")
            st.rerun()
        except (PlanError, UnicodeDecodeError) as exc:
            st.sidebar.error(f"Could not import {upload.name}: {exc}")
    plan = st.session_state.plan
    try:
        valid = normalize_plan(plan)
        name = slug(valid["plan"]["name"])
        st.sidebar.download_button("Export plan as TOML", plan_to_toml(valid), f"{name}.toml", "application/toml",
                                   width="stretch")
        st.sidebar.download_button("Export plan as JSON", plan_to_json(valid), f"{name}.json", "application/json",
                                   width="stretch")
        if st.sidebar.button(f"Save to {PLANS_DIR}/{name}.toml", width="stretch"):
            PLANS_DIR.mkdir(exist_ok=True)
            (PLANS_DIR / f"{name}.toml").write_text(plan_to_toml(valid), encoding="utf-8", newline="\n")
            st.sidebar.success(f"Saved {PLANS_DIR / (name + '.toml')}")
    except PlanError:
        st.sidebar.info("Fix the highlighted problems to export or save.")
    saved = sorted(PLANS_DIR.glob("*.toml")) + sorted(PLANS_DIR.glob("*.json")) if PLANS_DIR.exists() else []
    if saved:
        choice = st.sidebar.selectbox("Open a saved plan", [p.name for p in saved], key=key("saved"))
        if st.sidebar.button("Open", width="stretch"):
            chosen = PLANS_DIR / choice
            try:
                load_into_session(load_plan_text(chosen.read_text(encoding="utf-8"), chosen.name), f"Opened {chosen}.")
                st.rerun()
            except PlanError as exc:
                st.sidebar.error(str(exc))
    if st.sidebar.button("Reset to the example plan", width="stretch"):
        load_into_session(default_plan(), "Loaded the example plan.")
        st.rerun()
    st.sidebar.caption(f"Saved plans live in `{PLANS_DIR}/` (git-ignored). Runs write `output/plans/<plan-name>/`.")


def inputs_you(plan):
    person, employment = plan["person"], plan["employment"]
    st.subheader("About you")
    a, b = st.columns(2)
    with a:
        plan["plan"]["name"] = st.text_input("Plan name", plan["plan"]["name"], key=key("name"))
        born = st.date_input("Date of birth", date.fromisoformat(person["date_of_birth"]), date(1930, 1, 1), date(2010, 12, 31),
                             key=key("born"), format="YYYY-MM-DD")
        person["date_of_birth"] = born.isoformat()
    with b:
        person["retirement_age"] = int(st.number_input("Planned retirement age", 18, 80, int(person["retirement_age"]), 1,
                                                       key=key("retire"), help="Salary stops on this birthday."))
        person["private_hospital_cover"] = st.checkbox("Private hospital cover (avoids Medicare levy surcharge)",
                                                       person["private_hospital_cover"], key=key("cover"))
    st.subheader("Work")
    a, b = st.columns(2)
    with a:
        employment["annual_salary"] = money("Gross annual salary (AUD, excluding super)", employment["annual_salary"], "salary",
                                            help="Paid fortnightly until retirement; constant in nominal terms.")
    with b:
        employment["salary_sacrifice_per_year"] = money("Salary sacrifice to super per year", employment["salary_sacrifice_per_year"],
                                                        "sacrifice", help="Concessional; counts towards the cap with the 12% SG.")


def inputs_investments(plan):
    st.subheader("Tickers used in your portfolios")
    st.caption("These tickers are available to both portfolios. Custom series extend back to 1970; fund tickers begin at their observed inception. Return and cash-contribution estimates come from local processed data.")
    plan["assets"] = st.multiselect("Select tickers", TICKERS, default=plan["assets"], key=key("tickers"),
                                     format_func=lambda ticker: f"{ticker} · {'long-history dataset' if ticker in CUSTOM_TICKERS else 'fund history'}")
    names = plan["assets"]
    if names:
        try:
            preview = cached_market(tuple(names))
            summary = preview.asset_summary[["Ticker", "First", "Last", "Full-sample CAGR", "Cash contribution proxy"]].copy()
            summary["Coverage"] = summary["First"].astype(str) + "–" + summary["Last"].astype(str)
            summary = summary[["Ticker", "Coverage", "Full-sample CAGR", "Cash contribution proxy"]]
            summary["Full-sample CAGR"] *= 100
            summary["Cash contribution proxy"] *= 100
            st.dataframe(summary, width="stretch", hide_index=True, column_config={
                "Full-sample CAGR": st.column_config.NumberColumn("Full-sample CAGR %", format="%.2f"),
                "Cash contribution proxy": st.column_config.NumberColumn("Cash contribution proxy %/yr", format="%.2f")})
            st.caption("Cash contribution is a historical planning proxy, not an ETF tax statement or an extra return. The results tab explains how it is used.")
        except ValueError as exc:
            st.warning(str(exc))
    st.subheader("Portfolio outside super")
    a, b = st.columns(2)
    with a:
        plan["outside"]["cash"] = money("Cash today", plan["outside"]["cash"], "cash")
    with b:
        plan["outside"]["cash_buffer"] = money("Cash buffer kept uninvested", plan["outside"]["cash_buffer"], "buffer")
    plan["outside"]["investment_balance"] = money("Investments today", plan["outside"]["investment_balance"], "outside_value")
    with st.expander("Opening tax position for outside investments"):
        st.caption("One aggregate cost base and acquisition date are allocated across the portfolio. This is an approximation if you bought at different times or prices.")
        plan["outside"]["opening_cost_base"] = money("Total cost base", plan["outside"]["opening_cost_base"], "outside_basis")
        acquired = st.date_input("Acquisition date used for the opening portfolio", date.fromisoformat(plan["outside"]["opening_acquired"]),
                                 date(1900, 1, 1), date.fromisoformat(plan["plan"]["start_date"]), key=key("acquired"), format="YYYY-MM-DD")
        plan["outside"]["opening_acquired"] = acquired.isoformat()
    plan["outside"]["weights"] = weights_editor("Outside-super portfolio", plan["outside"]["weights"], names, "outw")
    plan["outside"]["rebalance"] = rebalance_choice(plan["outside"]["rebalance"], "outside_rebalance",
                                                    "Outside super each rebalance sells overweight holdings, which realises capital gains tax.")
    st.subheader("Portfolio inside super")
    a, b = st.columns(2)
    with a:
        plan["super"]["balance"] = money("Super balance today", plan["super"]["balance"], "super")
    with b:
        plan["super"]["total_super_balance_prior_30_june"] = money("Total super balance at last 30 June",
                                                                   plan["super"]["total_super_balance_prior_30_june"], "tsb",
                                                                   help="Sets this year's contribution caps.")
    plan["super"]["weights"] = weights_editor("Inside-super portfolio", plan["super"]["weights"], names, "supw")
    plan["super"]["rebalance"] = rebalance_choice(plan["super"]["rebalance"], "super_rebalance",
                                                  "Inside super the switch is modelled without tax (funds are assumed not to realise gains).")


def inputs_retirement(plan):
    st.subheader("Spending")
    a, b = st.columns(2)
    with a:
        plan["spending"]["annual"] = money("Annual spending (AUD, first year)", plan["spending"]["annual"], "spend")
    with b:
        plan["spending"]["annual_growth"] = percent("Spending growth %/yr", plan["spending"]["annual_growth"], "spendg", low=-20, high=20)
    st.subheader("Account-based pension")
    pension = plan["pension"]
    a, b = st.columns(2)
    with a:
        pension["start_age"] = int(st.number_input("Start pension at age (0 = never)", 0, 80, int(pension["start_age"]), 1,
                                                   key=key("pension_age"), help="Needs retirement and age 60 or over, or age 65."))
    with b:
        pension["transfer_all"] = st.checkbox("Move the whole super balance into the pension (up to the transfer balance cap)",
                                              pension["transfer_all"], key=key("all"))
        if not pension["transfer_all"]:
            pension["amount"] = money("Amount to move into the pension", pension["amount"], "pension_amount")
    st.caption("Before super is accessible, spending is paid from cash and outside investments; any gap is shown as a shortfall.")


def inputs_assumptions(plan):
    st.subheader("Horizon")
    a, b = st.columns(2)
    with a:
        plan["plan"]["start_date"] = st.date_input("Start date", date.fromisoformat(plan["plan"]["start_date"]), date(2026, 7, 1),
                                                   date(2040, 6, 30), key=key("start"), format="YYYY-MM-DD").isoformat()
    with b:
        plan["plan"]["years"] = int(st.number_input("Years to simulate", 1, 60, int(plan["plan"]["years"]), 1, key=key("years"),
                                                    help="Runs stop before the year you reach Age Pension age (not yet modelled)."))
    st.subheader("Economic assumptions")
    a, b = st.columns(2)
    with a:
        plan["assumptions"]["cpi_annual"] = percent("CPI %/yr", plan["assumptions"]["cpi_annual"], "cpi", low=-10, high=20,
                                                    help="Indexes CGT cost bases from 1 July 2027 and CPI-linked thresholds.")
    with b:
        plan["assumptions"]["wage_growth_annual"] = percent("Wage growth %/yr", plan["assumptions"]["wage_growth_annual"], "wages",
                                                            low=-10, high=20, help="Indexes contribution caps and MLS thresholds.")
    st.caption("Tax and super rules are sourced for 2026-27; later years apply enacted changes and project indexed "
               "thresholds with these assumptions (see docs/rules/au-projection.md).")
    st.subheader("Market simulation")
    st.caption("Stationary blocks resample joint daily returns from the full common ticker history. Longer generated horizons repeat patterns; they do not create longer observed history.")
    a, b = st.columns(2)
    with a:
        plan["market"]["paths"] = int(st.number_input("Portfolio paths", 16, 5000, int(plan["market"]["paths"]), 100,
                                                       key=key("paths"),
                                                       help="Market paths for the portfolio statistics. 1,000 gives stable medians and usable 5th/95th percentiles."))
        plan["market"]["seed"] = int(st.number_input("Random seed", 0, 2147483647, int(plan["market"]["seed"]), 1,
                                                      key=key("seed")))
    with b:
        plan["market"]["retirement_paths"] = int(st.number_input("Daily retirement-ledger paths", 1, 2000,
                                                                   int(plan["market"]["retirement_paths"]), 1,
                                                                   key=key("retirement_paths"),
                                                                   help="The first shared market draws are run through the full daily tax, spending and super ledger. Each takes about half a second per ten years; 100 or more is recommended for shortfall rates."))
        plan["market"]["block_length"] = int(st.number_input("Average block length (trading observations)", 1, 1260,
                                                               int(plan["market"]["block_length"]), 1,
                                                               key=key("block_length")))


PALETTE = {"Outside super": "#126a63", "Inside super": "#386a98", "Combined": "#b76a42"}
ACCOUNTS = {"cash": ("Cash", "#9a8a2e"), "outside_investments": ("Outside investments", "#126a63"),
            "accumulation": ("Super (accumulation)", "#386a98"), "pension": ("Account-based pension", "#8363a0")}
MONEY = "$%,d"


def zoomable(chart):
    """Drag to pan and Shift+scroll to zoom; plain scrolling keeps scrolling the page."""
    import altair as alt

    zoom = alt.selection_interval(bind="scales", zoom="wheel![event.shiftKey]")
    if isinstance(chart, alt.LayerChart):
        chart.layer[0] = chart.layer[0].add_params(zoom)
        return chart
    return chart.add_params(zoom)


def scale_for(names):
    import altair as alt

    return alt.Scale(domain=list(names), range=[PALETTE[n] for n in names])


def money_column(label, help=None):
    return st.column_config.NumberColumn(label, format=MONEY, help=help)


def percent_column(label, help=None, digits=1):
    return st.column_config.NumberColumn(label, format=f"%.{digits}f%%", help=help)


def compact(value):
    if value is None or not np.isfinite(value):
        return "–"
    return f"${value / 1e6:,.2f}m" if abs(value) >= 1e6 else f"${value:,.0f}"


def share(value):
    return "–" if value is None or not np.isfinite(value) else f"{value:.1%}"


def fit(frame):
    """A table height that shows every row without an inner scroll bar."""
    return 38 + 35 * len(frame)


def percentile_table(frame, measures):
    """One row per measure, columns 5th to 95th percentile across paths, each formatted for its unit."""
    rows = []
    for label, (field, kind) in measures.items():
        values = frame[field].dropna()
        if values.empty:
            continue
        q = values.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).to_numpy()
        fmt = compact if kind == "money" else share if kind == "percent" else (lambda v: f"{v:,.1f}")
        rows.append({"Measure": label, **{name: fmt(v) for name, v in zip(("5th", "25th", "Median", "75th", "95th"), q)}})
    return pd.DataFrame(rows)


def year_axis(frame, field="Date"):
    import altair as alt

    span = (pd.to_datetime(frame[field]).max() - pd.to_datetime(frame[field]).min()).days / 365.25
    return alt.Axis(format="%Y", tickCount=max(4, min(12, int(span / (5 if span >= 25 else 2 if span >= 12 else 1)))),
                    labelOverlap=True)


def balances_chart(daily):
    """Stacked month-end balances by account, in a fixed account order and colour."""
    import altair as alt

    monthly = daily[list(ACCOUNTS)].resample("ME").last().reset_index()
    long = monthly.melt("Date", var_name="account", value_name="balance")
    long["Account"] = long["account"].map(lambda a: ACCOUNTS[a][0])
    long["order"] = long["account"].map(list(ACCOUNTS).index)
    return zoomable(alt.Chart(long).mark_area().encode(
        x=alt.X("Date:T", title=None, axis=year_axis(long)),
        y=alt.Y("balance:Q", stack="zero", title="AUD (nominal)", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Account:N", sort=[v[0] for v in ACCOUNTS.values()],
                        scale=alt.Scale(domain=[v[0] for v in ACCOUNTS.values()], range=[v[1] for v in ACCOUNTS.values()]),
                        legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Account:N", alt.Tooltip("balance:Q", format="$,.0f")],
    ).properties(height=320))


def band_chart(frame, title, *, log=False, symlog=False, color="#126a63", percent=False, x="Date:T"):
    """Hoverable percentile bands with zoom and a sparse long-horizon year axis."""
    import altair as alt

    if x == "Date:T":
        xs = alt.X("Date:T", title=None, axis=year_axis(frame))
    else:
        field = x.split(":")[0]
        xs = alt.X(x, title=None, scale=alt.Scale(domain=[int(frame[field].min()), int(frame[field].max())]),
                   axis=alt.Axis(format="d", tickCount=min(12, frame[field].nunique())))
    if symlog:
        scale = alt.Scale(type="symlog", constant=1000, zero=True)
    elif log:
        scale = alt.Scale(type="log", domain=[float(frame["P05"].min()) * 0.9, float(frame["P95"].max()) * 1.1], nice=False)
    else:
        scale = alt.Scale(zero=True)
    if symlog:
        upper = float(frame["P95"].max())
        first_power = 4 if upper >= 1e6 else 3
        ticks = [0, *[10 ** power for power in range(first_power, 10) if 10 ** power <= upper]]
        labels = ("datum.value === 0 ? '$0' : datum.value >= 1000000 ? "
                  "'$' + datum.value / 1000000 + 'm' : '$' + datum.value / 1000 + 'k'")
        axis = alt.Axis(values=ticks, labelExpr=labels, labelOverlap=False)
    else:
        axis = alt.Axis(format=".0%" if percent else "$,.0f")
    number = ".1%" if percent else "$,.0f"
    y = alt.Y("P05:Q", title=title, scale=scale, axis=axis)
    tooltip = [alt.Tooltip(x.split(":")[0] + ":" + x.split(":")[1], format="%b %Y" if x == "Date:T" else "d"),
               *[alt.Tooltip(f"{q}:Q", format=number) for q in ("P05", "P25", "P50", "P75", "P95")]]
    base = alt.Chart(frame)
    outer = base.mark_area(opacity=0.13, color=color).encode(x=xs, y=y, y2="P95:Q", tooltip=tooltip)
    inner = base.mark_area(opacity=0.27, color=color).encode(x=xs, y="P25:Q", y2="P75:Q", tooltip=tooltip)
    median = base.mark_line(color=color, strokeWidth=2).encode(x=xs, y="P50:Q", tooltip=tooltip)
    return zoomable(alt.layer(outer, inner, median).properties(height=330))


def quantile_bands(frame, by, field):
    q = frame.groupby(by)[field].quantile([0.05, 0.25, 0.5, 0.75, 0.95]).unstack().reset_index()
    q.columns = [by, "P05", "P25", "P50", "P75", "P95"]
    return q


def overlay_histogram(frame, field, title, *, series=("Outside super", "Inside super"), log=False, percent=True, money=False):
    """Two (or more) distributions on one axis: unstacked, translucent bars with a median rule each."""
    import altair as alt

    part = frame.loc[frame["Portfolio"].isin(series), ["Portfolio", field]].dropna().copy()
    value = field
    if log:
        part = part.loc[part[field] > 0]
        part["log_value"] = np.log10(part[field])
        value = "log_value"
    ticks = [np.log10(v) for v in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6)]
    axis = (alt.Axis(labelExpr="'$' + format(pow(10, datum.value), ',.0f')", title=title, values=ticks) if log
            else alt.Axis(format="$,.0f" if money else ".0%" if percent else ",.2f", title=title))
    bars = alt.Chart(part).mark_bar(opacity=0.5, binSpacing=0).encode(
        x=alt.X(f"{value}:Q", bin=alt.Bin(maxbins=40), axis=axis),
        y=alt.Y("count():Q", stack=None, title="Paths"),
        color=alt.Color("Portfolio:N", scale=scale_for(series), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Portfolio:N", alt.Tooltip("count():Q", title="Paths")])
    rules = alt.Chart(part).mark_rule(strokeDash=[5, 3], strokeWidth=2).encode(
        x=f"median({value}):Q", color=alt.Color("Portfolio:N", scale=scale_for(series), legend=None),
        tooltip=["Portfolio:N", alt.Tooltip(f"median({field}):Q", title="Median",
                                            format="$,.0f" if (money or log) else ".1%" if percent else ",.2f")])
    return zoomable(alt.layer(bars, rules).properties(height=250))


def run_with_progress(valid):
    bar = st.progress(0.0, text="Loading history and simulating portfolio paths...")

    def progress(done, total):
        bar.progress(done / total, text=f"Daily tax ledgers: {done} of {total} paths")

    try:
        return run_plan(valid, market=cached_market(tuple(valid["assets"])), progress=progress)
    finally:
        bar.empty()


def selected_ledger(run, path):
    """The full daily ledger for one path, re-run on demand and kept for this result."""
    if path == run.representative_path:
        return run.result
    cache = st.session_state.setdefault("ledger_cache", {})
    if (id(run), path) not in cache:
        cache[(id(run), path)] = ledger_for_path(run.plan, run.market, run.portfolios, path)
    return cache[(id(run), path)]


def section_portfolios(run):
    import altair as alt

    st.header("1 · Your portfolios")
    plan = run.plan
    cols = st.columns(2)
    for column, (title, section) in zip(cols, (("Outside super", "outside"), ("Inside super", "super"))):
        with column:
            balance = plan["outside"]["investment_balance"] if section == "outside" else plan["super"]["balance"]
            st.markdown(f"**{title}** · {compact(balance)} invested · "
                        f"{'rebalanced every January' if plan[section]['rebalance'] == 'annual' else 'buy and hold'}")
            weights = pd.DataFrame([{"Ticker": t, "Weight": 100 * w} for t, w in plan[section]["weights"].items()])
            bars = alt.Chart(weights).mark_bar(color=PALETTE[title]).encode(
                x=alt.X("Weight:Q", title="Weight %", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("Ticker:N", sort="-x", title=None), tooltip=["Ticker:N", alt.Tooltip("Weight:Q", format=".1f")])
            text = bars.mark_text(align="left", dx=4, color="#19353a").encode(text=alt.Text("Weight:Q", format=".0f"))
            st.altair_chart((bars + text).properties(height=max(90, 34 * len(weights))), width="stretch")
    shares = run.portfolios.combined_shares
    if shares:
        st.caption(f"The **combined** portfolio is both accounts together: {shares['Outside super']:.1%} outside and "
                   f"{shares['Inside super']:.1%} inside super at the start, by invested balance. Each account keeps its "
                   "own mix and rebalancing; money never moves between them, so the split drifts with returns.")
    summary = run.portfolios.summary.copy()
    for field in ("CAGR", "Volatility", "Maximum drawdown", "Worst calendar year", "Best calendar year", "Positive years"):
        summary[field] *= 100
    st.subheader("Whole-portfolio statistics, full shared history")
    st.dataframe(summary.drop(columns=["First", "Last"]), width="stretch", hide_index=True, column_config={
        "CAGR": percent_column("CAGR", "Compound annual growth rate of the whole portfolio over the full shared history."),
        "Volatility": percent_column("Volatility", "Standard deviation of daily portfolio returns times √252."),
        "Maximum drawdown": percent_column("Max drawdown", "Deepest fall from an earlier peak, measured daily."),
        "Longest drawdown (years)": st.column_config.NumberColumn("Longest drawdown (yrs)", format="%.1f",
                                                                  help="Longest time from a peak until it was regained."),
        "Worst calendar year": percent_column("Worst year"), "Best calendar year": percent_column("Best year"),
        "Positive years": percent_column("Positive years", "Share of full calendar years with a gain.", 0)})
    first, last = summary["First"].iloc[0], summary["Last"].iloc[0]
    st.caption(f"Statistics for each portfolio as a whole, {first} to {last} "
               f"({run.market.manifest['common_returns']:,} joint daily returns, USD total returns), using the same "
               "rebalancing as the simulations. Rebalancing matters: an annually rebalanced mix of volatile, weakly "
               "correlated assets can grow faster than any of its parts, because each January it sells what rose and "
               "buys what fell.")
    with st.expander("Ticker-level source statistics"):
        asset_table = run.market.asset_summary.copy()
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


def section_history(run):
    import altair as alt

    st.header("2 · Historical portfolio behaviour")
    history = run.portfolios.historical
    names = list(dict.fromkeys(history["Portfolio"]))
    growth = zoomable(alt.Chart(history).mark_line(strokeWidth=2).encode(
        x=alt.X("Date:T", title=None, axis=year_axis(history)),
        y=alt.Y("Growth of 100:Q", scale=alt.Scale(type="log"), title="Growth of $100 · log scale", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Portfolio:N", scale=scale_for(names), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Portfolio:N", alt.Tooltip("Growth of 100:Q", format="$,.0f")]
    ).properties(height=330))
    st.altair_chart(growth, width="stretch")
    st.caption("$100 invested at the start of the shared history, valued at each month end. On a log scale equal "
               "vertical distances are equal percentage changes, so a straight line means steady compound growth "
               "and early decades stay visible. Reconstructed pre-fund history is a model, not observed fund performance.")
    drawdown = zoomable(alt.Chart(history).mark_line(strokeWidth=1.3).encode(
        x=alt.X("Date:T", title=None, axis=year_axis(history)),
        y=alt.Y("Drawdown:Q", title="Below previous peak", axis=alt.Axis(format=".0%")),
        color=alt.Color("Portfolio:N", scale=scale_for(names), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Portfolio:N", alt.Tooltip("Drawdown:Q", format=".1%")]
    ).properties(height=230))
    st.altair_chart(drawdown, width="stretch")
    st.caption("How far each portfolio sat below its previous high at each month end (0% = at a new high). Deep and "
               "long dips are what a retiree has to live through while still withdrawing.")
    yearly = run.portfolios.historical_annual
    if not yearly.empty:
        bars = alt.Chart(yearly).mark_bar().encode(
            x=alt.X("Year:O", title=None, axis=alt.Axis(labelAngle=-90, values=[y for y in yearly["Year"].unique() if y % 5 == 0])),
            xOffset="Portfolio:N", y=alt.Y("Return:Q", title="Calendar-year return", axis=alt.Axis(format=".0%")),
            color=alt.Color("Portfolio:N", scale=scale_for(names), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["Year:O", "Portfolio:N", alt.Tooltip("Return:Q", format=".1%")]).properties(height=260)
        st.altair_chart(bars, width="stretch")
        st.caption("Return in each full calendar year. The spread between good and bad years is the sequence risk a "
                   "retirement plan has to absorb.")


def section_future(run):
    import altair as alt

    plan, portfolios, market = run.plan, run.portfolios, run.market
    st.header("3 · Future portfolio simulations")
    n, years = plan["market"]["paths"], (portfolios.dates[-1] - portfolios.dates[0]).days / 365.25
    with st.expander("How these simulations are calculated", expanded=False):
        st.markdown(f"""
1. **Source history.** The selected tickers' daily total returns on their shared dates,
   {market.manifest['common_first']} to {market.manifest['common_last']}: {market.manifest['common_returns']:,}
   rows, one return per ticker per row. A row keeps the tickers' same-day co-movement.
2. **Stationary block bootstrap.** Each simulated path is a sequence of whole source rows for the
   {len(portfolios.dates) - 1:,} weekdays from {portfolios.dates[0]} to {portfolios.dates[-1]} ({years:.1f} years).
   A path starts at a random row and copies consecutive rows (a *block*). After each day it jumps to a new
   random row with probability 1/{plan['market']['block_length']}, so blocks average {plan['market']['block_length']}
   trading days (about {plan['market']['block_length'] / 21:.0f} months) and follow a geometric length
   distribution. Blocks keep short-run momentum, volatility clusters and crash sequences; jumping between
   blocks mixes eras. The source wraps from its end to its start.
3. **Same draws for every portfolio.** Path *k* uses the same rows for outside super, inside super and the
   combined portfolio. Differences between portfolios come only from their weights, not luck.
4. **Daily compounding.** Each ticker position grows by its daily return. With annual rebalancing, on the first
   trading day of each calendar year the positions are reset to the target weights before that day's return.
5. **Statistics per path.** Ending value of $100; annualised growth over the calendar horizon; volatility
   (standard deviation of daily returns × √252); maximum drawdown (deepest fall from a running peak);
   longest drawdown; and the sustainable withdrawal rate described below.
6. **Bands.** At each month end the 5th, 25th, 50th, 75th and 95th percentiles across the {n:,} paths.
   They are pointwise: no single path follows the median line.

Seed {plan['market']['seed']} makes the run repeatable. With {n:,} paths the median is stable to well under a
percentage point of annual growth; the 5th percentile rests on about {max(1, n // 20)} paths, so tails are less
precise. These are resamples of history, not a forecast: they cannot produce a crash worse than the worst
block in the source, and they treat every era as equally likely.
""")
    names = [p for p in ("Outside super", "Inside super", "Combined") if p in set(portfolios.paths["Portfolio"])]
    selected = st.radio("Portfolio", names, horizontal=True, key=key("portfolio_result"))
    fan = portfolios.paths.loc[portfolios.paths["Portfolio"] == selected]
    st.altair_chart(band_chart(fan, "Growth of $100 · log scale", log=True, color=PALETTE[selected]), width="stretch")
    st.caption("Dark band: middle half of paths (25th–75th percentile). Light band: 90% of paths (5th–95th). Line: "
               "median at each month. Hover for values; drag to pan, Shift+scroll to zoom, double-click to reset.")
    medians = portfolios.paths[["Date", "Portfolio", "P50"]]
    st.altair_chart(zoomable(alt.Chart(medians).mark_line(strokeWidth=2).encode(
        x=alt.X("Date:T", title=None, axis=year_axis(medians)),
        y=alt.Y("P50:Q", title="Median growth of $100", scale=alt.Scale(type="log", nice=False,
                domain=[float(medians["P50"].min()) * 0.95, float(medians["P50"].max()) * 1.05]), axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Portfolio:N", scale=scale_for(names), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Portfolio:N", alt.Tooltip("P50:Q", format="$,.0f")]
    ).properties(height=230)), width="stretch")
    st.caption("Median paths side by side, to compare the portfolios' central outcomes on the same draws.")
    dd = fan.rename(columns={"Drawdown P05": "Bad (5th pct)", "Drawdown P50": "Typical (median)"})
    dd = dd.melt("Date", value_vars=["Bad (5th pct)", "Typical (median)"], var_name="Path", value_name="Drawdown")
    st.altair_chart(zoomable(alt.Chart(dd).mark_line().encode(
        x=alt.X("Date:T", title=None, axis=year_axis(dd)), y=alt.Y("Drawdown:Q", title="Below previous peak", axis=alt.Axis(format=".0%")),
        strokeDash=alt.StrokeDash("Path:N", legend=alt.Legend(orient="bottom", title=None)), color=alt.value(PALETTE[selected]),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Path:N", alt.Tooltip("Drawdown:Q", format=".1%")]
    ).properties(height=210)), width="stretch")
    st.caption(f"{selected}: how far below its running peak the portfolio sits at each month end, for the median "
               "path and for the worst 5% of paths at that date.")

    st.subheader("Distributions across paths")
    outcomes = portfolios.outcomes
    a, b = st.columns(2)
    with a:
        st.altair_chart(overlay_histogram(outcomes, "Terminal growth of 100", "Ending value of $100 (log scale)", log=True),
                        width="stretch")
        st.caption("Where $100 ends up at the horizon. Dashed lines are medians.")
        st.altair_chart(overlay_histogram(outcomes, "Annualised volatility", "Annualised volatility"), width="stretch")
        st.caption("Day-to-day variability of each path, annualised. Higher volatility means wider swings in wealth.")
    with b:
        st.altair_chart(overlay_histogram(outcomes, "Annualised growth", "Annualised growth"), width="stretch")
        st.caption("Compound growth per year over the whole horizon on each path.")
        st.altair_chart(overlay_histogram(outcomes, "Maximum drawdown", "Maximum drawdown"), width="stretch")
        st.caption("Deepest peak-to-trough fall on each path. −50% means the portfolio halved at some point.")
    st.altair_chart(overlay_histogram(outcomes, "Sustainable withdrawal rate", "Sustainable withdrawal rate"),
                    width="stretch")
    st.caption(f"The largest first-year withdrawal each path could fund from {portfolios.retirement_start} to the "
               f"horizon, as a share of the portfolio at that date, rising {plan['spending']['annual_growth']:.1%} a year "
               "with your spending growth and paid monthly. It is pre-tax and ignores salary, contributions and "
               "super access rules, and is exact for that path: wealth reaches zero on the last day. A short horizon "
               "gives high rates; it is not a 30-year 4%-rule figure.")
    table = []
    for title in names:
        part = outcomes.loc[outcomes["Portfolio"] == title]
        t = percentile_table(part, {"Ending value of $100": ("Terminal growth of 100", "money"),
                                    "Annualised growth": ("Annualised growth", "percent"),
                                    "Annualised volatility": ("Annualised volatility", "percent"),
                                    "Maximum drawdown": ("Maximum drawdown", "percent"),
                                    "Longest drawdown (years)": ("Longest drawdown (years)", "number"),
                                    "Sustainable withdrawal rate": ("Sustainable withdrawal rate", "percent")})
        t.insert(0, "Portfolio", title)
        table.append(t)
    table = pd.concat(table)
    st.dataframe(table, width="stretch", hide_index=True, height=fit(table))
    st.caption("Read across a row: 5% of paths fall below the 5th-percentile value, half below the median. For "
               "drawdowns the 5th percentile is the severe end.")
    if not portfolios.annual_returns.empty:
        annual = portfolios.annual_returns.loc[portfolios.annual_returns["Portfolio"] == selected]
        st.altair_chart(band_chart(quantile_bands(annual, "Year", "Return"), "Calendar-year return", percent=True,
                                   color=PALETTE[selected], x="Year:Q"), width="stretch")
        st.caption(f"{selected}: spread of each full calendar year's return across paths. Partial first and last years "
                   "are left out.")


def section_retirement(run):
    import altair as alt

    plan, paths = run.plan, run.retirement_paths
    st.header("4 · Retirement outcomes")
    calculated = paths.loc[paths["Status"] != "unsupported"]
    with st.expander("How the retirement results are calculated", expanded=False):
        st.markdown(f"""
The first **{len(paths)}** of the {plan['market']['paths']:,} market paths above (set by *Daily retirement-ledger
paths* on the Assumptions tab) are each run through a full **daily Australian tax and super ledger**,
{run.result.daily.index[0].date()} to {run.result.daily.index[-1].date()}. Each path is a separate life story on
the same rules:

1. **Work.** Fortnightly salary until your retirement birthday. Super guarantee (12%) and salary sacrifice reach
   the fund 7 business days later, less 15% contributions tax, and buy the inside-super portfolio.
2. **Spending** is due monthly, rising each 1 July. It is paid from cash, then by selling outside investments
   (oldest parcels first, realising capital gains), then from super once it is accessible (preservation age and
   retirement), then from the pension.
3. **Investing.** Cash above the buffer buys the outside portfolio. Each January both accounts are rebalanced if
   chosen; outside super that sells parcels and realises CGT.
4. **Distributions** split each ticker's total return into a quarterly cash payment (the cash proxy) and price
   growth; outside super they are taxable income.
5. **Tax.** Each 30 June personal tax is assessed (brackets, Medicare levy and surcharge, LITO, CGT discount,
   Division 293, the 2027 CGT reform) and paid on 31 October. Accumulation earnings are taxed at 15%; pension
   earnings are exempt.
6. **Pension.** At the chosen age the accumulation balance moves into an account-based pension, up to the
   transfer balance cap; the age-based minimum is paid monthly.

A path is **funded** if every spending need and tax bill was paid, **depleted** if any spending went unmet or
tax could not be paid (both included in every statistic), and **unsupported** if it reached a rule the model
does not cover (excluded, with the reason shown). Returns are the USD histories applied as an AUD proxy.
""")
    funded = int((paths["Status"] == "funded").sum())
    depleted = int((paths["Status"] == "depleted").sum())
    unsupported = int((paths["Status"] == "unsupported").sum())
    a, b, c, d = st.columns(4)
    a.metric("Paths calculated", f"{len(calculated)} / {len(paths)}", help=f"{unsupported} unsupported")
    b.metric("Funded all spending", share(funded / len(calculated)) if len(calculated) else "–",
             help=f"{funded} funded, {depleted} depleted")
    c.metric("Median ending wealth", compact(calculated["Ending wealth"].median()),
             help="Nominal dollars at the horizon.")
    d.metric("…in today's dollars", compact(calculated["Ending wealth, today's dollars"].median()),
             help=f"Deflated at the assumed {plan['assumptions']['cpi_annual']:.1%} CPI.")
    a, b, c, d = st.columns(4)
    a.metric("Median wealth at retirement", compact(calculated["Wealth at retirement"].median()))
    b.metric("Median first retired-year withdrawal", share(calculated["First retired-year withdrawal rate"].median()),
             help="Spending plus tax paid in the first full retired financial year, over wealth at its 1 July.")
    c.metric("Median highest withdrawal rate", share(calculated["Highest withdrawal rate"].median()),
             help="Each path's highest financial-year withdrawal rate while retired.")
    d.metric("Median total tax", compact(calculated["Personal tax assessed"].median() + calculated["Fund tax"].median()),
             help="Personal tax assessed plus super fund tax.")
    if unsupported:
        reasons = paths.loc[paths["Status"] == "unsupported", "Reason"].value_counts()
        st.warning("Unsupported paths are excluded, so the shares above are conditional on the others: "
                   + "; ".join(f"{count} × {reason}" for reason, count in reasons.items()))
    st.subheader("Wealth over time")
    names = list(dict.fromkeys(run.account_bands["Series"]))
    choice = st.radio("Show", names, horizontal=True, key=key("wealth_series"))
    bands = run.account_bands.loc[run.account_bands["Series"] == choice]
    wide = wide_wealth_range(bands)
    st.altair_chart(band_chart(bands, f"{choice} (AUD proxy" + (", log-like)" if wide else ")"), symlog=wide), width="stretch")
    st.caption(f"Month-end {choice.lower()} across the {len(calculated)} calculated paths, nominal dollars: dark band the "
               "middle half, light band 90% of paths, line the median. "
               + ("The axis is linear up to $1,000 and logarithmic above, so a very high upper tail does not flatten "
                  "the median. " if wide else "")
               + "Total wealth includes super that may not yet be accessible.")
    a, b = st.columns(2)
    with a:
        ending = calculated.melt("Path", value_vars=["Ending outside wealth", "Ending super and pension"],
                                 var_name="Account", value_name="AUD").rename(columns={"Account": "Portfolio"})
        ending["Portfolio"] = ending["Portfolio"].map({"Ending outside wealth": "Outside super",
                                                       "Ending super and pension": "Inside super"})
        st.altair_chart(overlay_histogram(ending, "AUD", "Ending wealth (nominal AUD)", percent=False, money=True),
                        width="stretch")
        st.caption("Wealth left at the horizon in each account, across paths.")
    with b:
        annual = run.retirement_annual
        retired = annual.loc[annual["Full retired year"] & annual["Withdrawal rate"].notna()]
        if retired.empty:
            st.info("No full financial year after retirement falls inside the horizon, so there are no withdrawal rates.")
        else:
            st.altair_chart(band_chart(quantile_bands(retired, "FY ending", "Withdrawal rate"),
                                       "Withdrawal rate", percent=True, color="#b76a42", x="FY ending:Q"), width="stretch")
            st.caption("Each retired financial year's spending plus tax paid, divided by total wealth on its 1 July. "
                       "A rate climbing over time means wealth is shrinking relative to spending.")
    annual = run.retirement_annual
    stress = annual.groupby("FY ending").agg(**{"Paths with a shortfall": ("Shortfall", lambda x: (x > 0).mean()),
                                                "Median spending paid": ("Spending paid", "median")}).reset_index()
    a, b = st.columns(2)
    with a:
        st.altair_chart(alt.Chart(stress).mark_bar(color="#8c2f2f").encode(
            x=alt.X("FY ending:O", title="Financial year ending"),
            y=alt.Y("Paths with a shortfall:Q", axis=alt.Axis(format=".0%"),
                    scale=alt.Scale(domain=[0, max(0.1, float(stress["Paths with a shortfall"].max()) * 1.2)])),
            tooltip=["FY ending:O", alt.Tooltip("Paths with a shortfall:Q", format=".1%")]).properties(height=240),
            width="stretch")
        st.caption("Share of paths that could not pay all spending in each financial year.")
    with b:
        pensions = annual.loc[annual["Pension payments"] > 0]
        if pensions.empty:
            st.info("No account-based pension is paid in this plan (pension start age 0, or after the horizon).")
        else:
            st.altair_chart(band_chart(quantile_bands(pensions, "FY ending", "Pension payments"), "Pension payments per year",
                                       color="#8363a0", x="FY ending:Q"), width="stretch")
            st.caption("Pension paid each financial year across paths: at least the age-based minimum, more when "
                       "spending needs it once outside money is used up.")
    st.subheader("Outcome ranges")
    ranges = percentile_table(calculated, {
        "Ending wealth": ("Ending wealth", "money"), "Ending wealth, today's dollars": ("Ending wealth, today's dollars", "money"),
        "Ending outside wealth": ("Ending outside wealth", "money"), "Ending super and pension": ("Ending super and pension", "money"),
        "Wealth at retirement": ("Wealth at retirement", "money"), "Spending shortfall": ("Spending shortfall", "money"),
        "Personal tax assessed": ("Personal tax assessed", "money"), "Fund tax": ("Fund tax", "money"),
        "Pension payments": ("Pension payments", "money"), "Pension balance at start": ("Pension balance at start", "money"),
        "First retired-year withdrawal rate": ("First retired-year withdrawal rate", "percent"),
        "Highest withdrawal rate": ("Highest withdrawal rate", "percent")})
    st.dataframe(ranges, width="stretch", hide_index=True, height=fit(ranges))
    st.caption("Percentiles across calculated paths. Each column is a separate ranking, so a row's 5th percentile "
               "and another row's 5th percentile usually come from different paths.")
    with st.expander(f"Every path ({len(paths)})"):
        table = paths.copy()
        for field in ("First retired-year withdrawal rate", "Highest withdrawal rate", "Median withdrawal rate"):
            if field in table:
                table[field] *= 100
        money = ("Ending wealth", "Ending wealth, today's dollars", "Ending outside wealth", "Ending super and pension",
                 "Wealth at retirement", "Spending paid", "Spending shortfall", "Unpaid tax", "Personal tax assessed",
                 "Fund tax", "Pension payments", "Pension balance at start")
        st.dataframe(table, width="stretch", hide_index=True, column_config={
            "Path": st.column_config.NumberColumn("Path", format="%d", pinned=True),
            "Status": st.column_config.TextColumn("Status", pinned=True),
            **{field: money_column(field) for field in money},
            **{field: percent_column(field) for field in ("First retired-year withdrawal rate", "Highest withdrawal rate",
                                                          "Median withdrawal rate")}})
        st.caption("Path numbers are positions in the shared draw sequence (path 0 is the first draw), not ranks. "
                   "Scroll sideways for every column; hover a header for its full name.")


def section_ledger(run):
    import altair as alt

    paths = run.retirement_paths
    calculated = paths.loc[paths["Status"] != "unsupported"].sort_values("Ending wealth")
    st.header("5 · One path in full: the daily ledger")
    st.markdown("Everything above summarises many paths. Here one path's daily ledger is shown in full, so you can "
                "see each salary payment, sale, tax bill and pension payment that produced its result.")
    ranked = {"Median ending wealth": run.representative_path,
              "Poor (10th percentile ending wealth)": int(calculated.iloc[int(0.10 * (len(calculated) - 1))]["Path"]),
              "Good (90th percentile ending wealth)": int(calculated.iloc[int(0.90 * (len(calculated) - 1))]["Path"]),
              "Worst ending wealth": int(calculated.iloc[0]["Path"]), "Best ending wealth": int(calculated.iloc[-1]["Path"])}
    options = [f"{label} · path {path}" for label, path in ranked.items()] + [f"Path {p}" for p in calculated["Path"].sort_values()]
    picked = st.selectbox("Path to inspect", options, key=key("ledger_path"))
    path = int(picked.rsplit(" ", 1)[1])
    st.caption(f"The default is path {run.representative_path}: of the calculated paths, its ending wealth is closest "
               "to the median. The number is simply its position in the draw sequence. A median *ending* does not "
               "make every year median; the path may have had a bad start and a strong finish. Pick other paths to "
               "see how a poor or good market sequence plays out.")
    with st.spinner(f"Running the daily ledger for path {path}..."):
        result = selected_ledger(run, path)
    daily, annual = result.daily, result.annual
    a, b, c, d = st.columns(4)
    a.metric("Wealth at start", compact(daily["total"].iloc[0]))
    b.metric(f"Wealth at {daily.index[-1].date()}", compact(daily["total"].iloc[-1]))
    c.metric("Spending shortfall", compact(daily["shortfall"].sum()))
    d.metric("Tax (personal + fund)", compact(sum(x["assessment"].net_tax + x["assessment"].division_293_tax for x in annual)
                                              + daily["fund_tax"].sum()))
    st.altair_chart(balances_chart(daily), width="stretch")
    st.caption("Month-end balances by account, stacked. Watch outside money fund spending until super becomes "
               "accessible, then the move from accumulation into the pension.")
    flows = daily[["salary", "employer_contributions", "pension_payments", "lump_sums", "spending_paid", "shortfall",
                   "tax_paid"]].resample("YE-JUN").sum().reset_index()
    names = {"salary": "Salary (after sacrifice)", "employer_contributions": "Super contributions",
             "pension_payments": "Pension payments", "lump_sums": "Super lump sums", "spending_paid": "Spending paid",
             "shortfall": "Spending shortfall", "tax_paid": "Tax paid"}
    flow_long = flows.melt("Date", var_name="Flow", value_name="AUD")
    flow_long = flow_long.groupby("Flow").filter(lambda group: group["AUD"].abs().max() > 1e-9)
    flow_long["Flow"] = flow_long["Flow"].map(names)
    flow_long["FY ending"] = flow_long["Date"].dt.year
    if flow_long.empty:
        st.info("No salary, spending, contribution, pension or tax cash flows on this path.")
    else:
        st.altair_chart(zoomable(alt.Chart(flow_long).mark_line(point=True).encode(
            x=alt.X("FY ending:O", title="Financial year ending"), y=alt.Y("AUD:Q", axis=alt.Axis(format="$,.0f")),
            color=alt.Color("Flow:N", legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["FY ending:O", "Flow:N", alt.Tooltip("AUD:Q", format="$,.0f")]).properties(height=300)),
            width="stretch")
        st.caption("Cash flows summed by financial year. Tax paid in a year is mostly the previous year's assessment, "
                   "settled on 31 October.")
    rows = [{"Year": x["financial_year"], "Taxable income": x["assessment"].taxable_income,
             "Net tax": x["assessment"].net_tax + x["assessment"].division_293_tax,
             "Net capital gain": x["assessment"].net_capital_gain,
             "Concessional contributions": x["concessional_contributions"], "Cap available": x["concessional_cap_available"],
             "Spending paid": x["spending_paid"], "Shortfall": x["shortfall"],
             "Pension minimum": x["pension_minimum"] or 0.0, "Pension paid": x["pension_paid"] or 0.0,
             "Transfer balance": x["transfer_balance"] or 0.0, "Super at 30 June": x["total_super_balance_30_june"]}
            for x in annual]
    st.subheader("Year by year")
    frame = pd.DataFrame(rows)
    st.dataframe(frame, width="stretch", hide_index=True, height=fit(frame),
                 column_config={"Year": st.column_config.TextColumn("Year", pinned=True),
                                **{c: money_column(c) for c in frame.columns if c != "Year"}})
    st.caption("Each financial year's assessment and super position. Taxable income includes realised capital gains "
               "after the discount; the pension columns show the legislated minimum and what was actually paid; the "
               "transfer balance counts amounts moved into the tax-free pension against the cap.")
    tax_frame = frame.melt("Year", value_vars=["Taxable income", "Net tax", "Net capital gain"], var_name="Measure", value_name="AUD")
    cap_frame = frame.melt("Year", value_vars=["Concessional contributions", "Cap available"], var_name="Measure", value_name="AUD")
    a, b = st.columns(2)
    for column, part, heading in ((a, tax_frame, "Personal tax"), (b, cap_frame, "Concessional contributions and cap")):
        with column:
            st.markdown(f"**{heading}**")
            st.altair_chart(zoomable(alt.Chart(part).mark_line(point=True).encode(
                x=alt.X("Year:N", title=None, axis=alt.Axis(labelAngle=-45)), y=alt.Y("AUD:Q", axis=alt.Axis(format="$,.0f")),
                color=alt.Color("Measure:N", legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["Year:N", "Measure:N", alt.Tooltip("AUD:Q", format="$,.0f")]).properties(height=260)),
                width="stretch")
    st.caption("Left: income, realised gains and tax assessed each year. Right: concessional contributions against the "
               "cap available, which includes carried-forward unused cap when your balance allows it.")
    if (frame["Pension paid"] > 0).any():
        pension = frame.melt("Year", value_vars=["Pension minimum", "Pension paid"], var_name="Measure", value_name="AUD")
        st.markdown("**Account-based pension**")
        st.altair_chart(alt.Chart(pension).mark_bar().encode(
            x=alt.X("Year:N", title=None), xOffset="Measure:N", y=alt.Y("AUD:Q", axis=alt.Axis(format="$,.0f")),
            color=alt.Color("Measure:N", scale=alt.Scale(range=["#c9b8da", "#8363a0"]), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["Year:N", "Measure:N", alt.Tooltip("AUD:Q", format="$,.0f")]).properties(height=240), width="stretch")
        st.caption("The legislated minimum (a percentage of the 1 July balance that rises with age) against what was "
                   "paid. Payments above the minimum happen when spending needs them.")
    outstanding = result.outstanding
    if outstanding["tax_liabilities"] or outstanding["unassessed_year"] or outstanding["unpaid_tax"]:
        st.caption(f"At the horizon: tax not yet due {[l['financial_year'] for l in outstanding['tax_liabilities']]}; "
                   f"unpaid tax {[u['financial_year'] for u in outstanding['unpaid_tax']]}; partial year not yet assessed "
                   f"{(outstanding['unassessed_year'] or {}).get('financial_year')}.")
    with st.expander("Event log for this path"):
        events = result.events
        kinds = sorted(events["event"].unique())
        chosen = st.multiselect("Event types", kinds, default=[k for k in kinds if k not in ("buy", "distribution")],
                                key=key("event_types"))
        st.dataframe(events.loc[events["event"].isin(chosen)], width="stretch", hide_index=True,
                     column_config={"amount": money_column("amount")})
    name = slug(run.plan["plan"]["name"])
    a, b = st.columns(2)
    a.download_button("Download this path's daily ledger (CSV)", daily.to_csv(), f"{name}-path{path}-daily.csv", "text/csv")
    b.download_button("Download this path's events (CSV)", result.events.to_csv(index=False), f"{name}-path{path}-events.csv",
                      "text/csv")


def results(plan):
    try:
        valid = normalize_plan(plan)
    except PlanError as exc:
        st.error("The plan has problems to fix before it can run:")
        for problem in exc.problems:
            st.markdown(f"- `{problem}`")
        return
    if st.button("Run plan", type="primary") or st.session_state.pop("run_requested", False):
        try:
            st.session_state.result = run_with_progress(valid)
            st.session_state.ledger_cache = {}
        except (UnsupportedRule, PlanError, ValueError, ArithmeticError) as exc:
            st.session_state.result = None
            st.error(f"The plan cannot run as specified: {exc}")
    run = st.session_state.result
    if run is None:
        st.info("Press Run plan to see your portfolios, their history and simulated futures, retirement outcomes "
                "across many market paths, and any single path's daily ledger.")
        return
    if plan_to_json(valid) != plan_to_json(run.plan):
        st.warning("Inputs have changed since this run. Press Run plan to refresh the results.")
    for note in run.notes:
        st.warning(note)
    section_portfolios(run)
    section_history(run)
    section_future(run)
    section_retirement(run)
    section_ledger(run)
    if run.folder:
        st.success(f"Saved the plan, path summaries, the median path's daily ledger, a manifest and PNG review plots to "
                   f"`{run.folder}`.")
        with st.expander("Static PNG review plots"):
            for file in ("portfolio_history.png", "portfolio_future.png", "portfolio_distributions.png",
                         "retirement_range.png", "retirement_flows.png", "ledger.png"):
                if (run.folder / file).exists():
                    st.image(str(run.folder / file), caption=file.replace("_", " ").replace(".png", ""))
    with st.expander("Assumptions behind the rules"):
        for year, manifest in run.rules_manifest.items():
            st.markdown(f"**{year}**: " + "; ".join(f"`{name}`" for name in manifest["assumptions"]))


def main():
    st.set_page_config(page_title="Retirement planner", page_icon=":material/savings:", layout="wide")
    if "plan" not in st.session_state:
        st.session_state.plan, st.session_state.version, st.session_state.result = default_plan(), 0, None
    st.title("Retirement planner")
    st.caption("Australian resident, single person. A planning model, not financial advice.")
    message = st.session_state.pop("flash", None)
    if message:
        st.toast(message)
    sidebar()
    plan = st.session_state.plan
    tabs = st.tabs(["You", "Investments", "Retirement", "Assumptions", "Results"])
    with tabs[0]:
        inputs_you(plan)
    with tabs[1]:
        inputs_investments(plan)
    with tabs[2]:
        inputs_retirement(plan)
    with tabs[3]:
        inputs_assumptions(plan)
    with tabs[4]:
        results(plan)


main()
