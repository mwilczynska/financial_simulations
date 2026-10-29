"""Browser app for editing, importing, exporting and running a retirement plan.

Launch with ``financial-simulations ui`` (or ``streamlit run`` on this file).
The plan dictionary in session state is the single source of truth: every
tab edits it, the sidebar imports and exports it, and Run writes one folder,
output/plans/<plan-name>/.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from financial_simulations.data.plan_markets import CUSTOM_TICKERS, TICKERS, load_plan_markets
from financial_simulations.reporting.plan import wide_wealth_range
from financial_simulations.retirement.plan import (PlanError, default_plan, load_plan_text, normalize_plan, plan_to_json,
                                                   plan_to_toml, slug)
from financial_simulations.retirement.run_plan import run_plan
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
    st.subheader("Portfolio inside super")
    a, b = st.columns(2)
    with a:
        plan["super"]["balance"] = money("Super balance today", plan["super"]["balance"], "super")
    with b:
        plan["super"]["total_super_balance_prior_30_june"] = money("Total super balance at last 30 June",
                                                                   plan["super"]["total_super_balance_prior_30_june"], "tsb",
                                                                   help="Sets this year's contribution caps.")
    plan["super"]["weights"] = weights_editor("Inside-super portfolio", plan["super"]["weights"], names, "supw")


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
        pension["transfer_all"] = st.checkbox("Move the whole super balance into the pension", pension["transfer_all"], key=key("all"))
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
        plan["market"]["paths"] = int(st.number_input("Portfolio paths", 16, 512, int(plan["market"]["paths"]), 16,
                                                       key=key("paths")))
        plan["market"]["seed"] = int(st.number_input("Random seed", 0, 2147483647, int(plan["market"]["seed"]), 1,
                                                      key=key("seed")))
    with b:
        plan["market"]["retirement_paths"] = int(st.number_input("Daily retirement-ledger paths", 1, 128,
                                                                   int(plan["market"]["retirement_paths"]), 1,
                                                                   key=key("retirement_paths"),
                                                                   help="The first shared market draws are passed through tax, spending and super accounting."))
        plan["market"]["block_length"] = int(st.number_input("Average block length (trading observations)", 1, 1260,
                                                               int(plan["market"]["block_length"]), 1,
                                                               key=key("block_length")))


ACCOUNTS = {"cash": ("Cash", "#9a8a2e"), "outside_investments": ("Outside investments", "#126a63"),
            "accumulation": ("Super (accumulation)", "#386a98"), "pension": ("Account-based pension", "#8363a0")}


def balances_chart(daily):
    """Stacked month-end balances by account, in a fixed account order and colour."""
    import altair as alt

    monthly = daily[list(ACCOUNTS)].resample("ME").last().reset_index()
    long = monthly.melt("Date", var_name="account", value_name="balance")
    long["Account"] = long["account"].map(lambda a: ACCOUNTS[a][0])
    long["order"] = long["account"].map(list(ACCOUNTS).index)
    return alt.Chart(long).mark_area().encode(
        x=alt.X("Date:T", title=None, axis=alt.Axis(format="%Y", tickCount=8)),
        y=alt.Y("balance:Q", stack="zero", title="AUD (nominal)", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Account:N", sort=[v[0] for v in ACCOUNTS.values()],
                        scale=alt.Scale(domain=[v[0] for v in ACCOUNTS.values()], range=[v[1] for v in ACCOUNTS.values()]),
                        legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Account:N", alt.Tooltip("balance:Q", format="$,.0f")],
    ).properties(height=320).interactive()


def band_chart(frame, title, *, log=False, symlog=False, color="#126a63"):
    """Hoverable percentile bands with zoom and a sparse long-horizon year axis."""
    import altair as alt

    x = alt.X("Date:T", title=None, axis=alt.Axis(format="%Y", tickCount=8))
    scale = alt.Scale(type="symlog", constant=1000, zero=True) if symlog else alt.Scale(type="log" if log else "linear", zero=not log)
    if symlog:
        upper = float(frame["P95"].max())
        first_power = 4 if upper >= 1e6 else 3
        ticks = [0, *[10 ** power for power in range(first_power, 10) if 10 ** power <= upper]]
        labels = ("datum.value === 0 ? '$0' : datum.value >= 1000000 ? "
                  "'$' + datum.value / 1000000 + 'm' : '$' + datum.value / 1000 + 'k'")
        axis = alt.Axis(values=ticks, labelExpr=labels, labelOverlap=False)
    else:
        axis = alt.Axis(format="$,.0f")
    y = alt.Y("P05:Q", title=title, scale=scale, axis=axis)
    tooltip = [alt.Tooltip("Date:T", format="%b %Y"), *[alt.Tooltip(f"{q}:Q", format="$,.0f") for q in ("P05", "P25", "P50", "P75", "P95")]]
    base = alt.Chart(frame)
    outer = base.mark_area(opacity=0.13, color=color).encode(x=x, y=y, y2="P95:Q", tooltip=tooltip)
    inner = base.mark_area(opacity=0.27, color=color).encode(x=x, y="P25:Q", y2="P75:Q", tooltip=tooltip)
    median = base.mark_line(color=color, strokeWidth=2).encode(x=x, y="P50:Q", tooltip=tooltip)
    return alt.layer(outer, inner, median).properties(height=330).interactive()


def compact(value):
    return f"${value / 1e6:,.2f}m" if abs(value) >= 1e6 else f"${value:,.0f}"


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
            with st.spinner("Loading history, sampling portfolios and running the daily retirement ledgers..."):
                st.session_state.result = run_plan(valid, market=cached_market(tuple(valid["assets"])))
        except (UnsupportedRule, PlanError, ValueError, ArithmeticError) as exc:
            st.session_state.result = None
            st.error(f"The plan cannot run as specified: {exc}")
    run = st.session_state.result
    if run is None:
        st.info("Press Run plan to see the entered portfolios, their historical context, future return ranges and retirement outcomes.")
        return
    if plan_to_json(valid) != plan_to_json(run.plan):
        st.warning("Inputs have changed since this run. Press Run plan to refresh the results.")
    for note in run.notes:
        st.warning(note)
    import altair as alt

    st.header("1 · Portfolios entered")
    allocations = pd.DataFrame([{"Portfolio": label, "Ticker": ticker, "Weight %": 100 * weight}
                                for label, section in (("Outside super", "outside"), ("Inside super", "super"))
                                for ticker, weight in run.plan[section]["weights"].items()])
    a, b = st.columns([1, 2])
    with a:
        st.dataframe(allocations, width="stretch", hide_index=True,
                     column_config={"Weight %": st.column_config.NumberColumn(format="%.1f")})
    with b:
        chart = alt.Chart(allocations).mark_bar().encode(
            x=alt.X("Weight %:Q", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("Ticker:N", sort="-x"), color=alt.Color("Portfolio:N", scale=alt.Scale(range=["#126a63", "#386a98"])),
            tooltip=["Portfolio:N", "Ticker:N", alt.Tooltip("Weight %:Q", format=".1f")]).properties(height=max(180, 30 * len(allocations)))
        st.altair_chart(chart, width="stretch")
    st.caption(f"Shared calibration: {run.market.manifest['common_first']} to {run.market.manifest['common_last']} "
               f"({run.market.manifest['common_returns']:,} joint daily returns). Source calendars are intersected and returns are recomputed between shared observations.")
    asset_table = run.market.asset_summary.copy()
    for field in ("Full-sample CAGR", "Daily volatility, annualised", "Maximum drawdown", "Cash contribution proxy"):
        asset_table[field] *= 100
    st.dataframe(asset_table, width="stretch", hide_index=True,
                 column_config={field: st.column_config.NumberColumn(field + " %", format="%.2f") for field in
                                ("Full-sample CAGR", "Daily volatility, annualised", "Maximum drawdown", "Cash contribution proxy")})
    st.caption("CAGR compounds the full observed or reconstructed total-return sample. The cash proxy averages annual sums of daily cash contributions over complete years. It splits already included total return in the tax ledger; it is not added to growth. No Australian franking is inferred from these USD sources.")

    st.header("2 · Historical portfolio behaviour")
    st.dataframe(run.portfolios.summary.assign(**{"Historical CAGR": lambda x: x["Historical CAGR"] * 100,
                                                 "Historical volatility": lambda x: x["Historical volatility"] * 100,
                                                 "Historical max drawdown": lambda x: x["Historical max drawdown"] * 100}),
                 width="stretch", hide_index=True)
    history = run.portfolios.historical
    chart = alt.Chart(history).mark_line(strokeWidth=2).encode(
        x=alt.X("Date:T", axis=alt.Axis(format="%Y", tickCount=8)),
        y=alt.Y("Growth of 100:Q", scale=alt.Scale(type="log"), title="Growth of $100 · log scale"),
        color=alt.Color("Portfolio:N", scale=alt.Scale(range=["#126a63", "#386a98"])),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Portfolio:N", alt.Tooltip("Growth of 100:Q", format="$,.0f")]
    ).properties(height=340).interactive()
    st.altair_chart(chart, width="stretch")
    st.caption("This is a historical buy-and-hold calculation on the selected tickers' shared daily dates. The log axis keeps early and late decades visible. Reconstructed pre-fund history is a model, not observed fund performance.")

    st.header("3 · Future portfolio simulations")
    selected = st.selectbox("Portfolio to inspect", ["Outside super", "Inside super"], key=key("portfolio_result"))
    fan = run.portfolios.paths.loc[run.portfolios.paths["Portfolio"] == selected]
    st.altair_chart(band_chart(fan, "Growth of $100 · log scale", log=True,
                                 color="#126a63" if selected == "Outside super" else "#386a98"), width="stretch")
    st.caption("Shading shows the 5th–95th and 25th–75th percentile ranges; the line is the median at each month. Hover for values or scroll to zoom. These are conditional bootstrap scenarios, not a forecast or a guarantee. The future weekday calendar is only an accounting template.")
    outcomes = run.portfolios.outcomes
    st.subheader("Ending values and risk across paths")
    summary = outcomes.groupby("Portfolio").agg(
        paths=("Path", "count"), median_ending_100=("Terminal growth of 100", "median"),
        p05_ending_100=("Terminal growth of 100", lambda x: x.quantile(0.05)),
        p95_ending_100=("Terminal growth of 100", lambda x: x.quantile(0.95)),
        median_growth=("Annualised growth", "median"), median_volatility=("Annualised volatility", "median"),
        median_max_drawdown=("Maximum drawdown", "median")).reset_index()
    for field in ("median_growth", "median_volatility", "median_max_drawdown"):
        summary[field] *= 100
    st.dataframe(summary, width="stretch", hide_index=True)
    c1, c2 = st.columns(2)
    with c1:
        chart = alt.Chart(outcomes).mark_bar(opacity=0.75).encode(
            x=alt.X("Annualised growth:Q", bin=alt.Bin(maxbins=26), axis=alt.Axis(format=".0%")),
            y=alt.Y("count():Q", title="Paths"), color="Portfolio:N",
            tooltip=["Portfolio:N", "count():Q"]).properties(height=270).interactive()
        st.altair_chart(chart, width="stretch")
        st.caption("Each bar counts sampled paths by annualised growth from the opening to final date.")
    with c2:
        chart = alt.Chart(outcomes).mark_bar(opacity=0.75).encode(
            x=alt.X("Maximum drawdown:Q", bin=alt.Bin(maxbins=26), axis=alt.Axis(format=".0%")),
            y=alt.Y("count():Q", title="Paths"), color="Portfolio:N",
            tooltip=["Portfolio:N", "count():Q"]).properties(height=270).interactive()
        st.altair_chart(chart, width="stretch")
        st.caption("Maximum drawdown is the deepest fall from an earlier portfolio peak on each daily path.")
    if not run.portfolios.annual_returns.empty:
        annual_portfolio = run.portfolios.annual_returns.loc[run.portfolios.annual_returns["Portfolio"] == selected]
        qyear = annual_portfolio.groupby("Year")["Return"].quantile([0.05, 0.25, 0.5, 0.75, 0.95]).unstack().reset_index()
        qyear.columns = ["Year", "P05", "P25", "P50", "P75", "P95"]
        base = alt.Chart(qyear)
        annual_x = alt.X("Year:Q", scale=alt.Scale(domain=[int(qyear["Year"].min()), int(qyear["Year"].max())]),
                         axis=alt.Axis(format="d", tickCount=8))
        annual_tooltip = ["Year:Q", *[alt.Tooltip(f"{q}:Q", format=".1%") for q in ("P05", "P25", "P50", "P75", "P95")]]
        annual_color = "#126a63" if selected == "Outside super" else "#386a98"
        annual_y = lambda field: alt.Y(f"{field}:Q", title="Annual portfolio return", axis=alt.Axis(format=".0%"))
        annual_chart = alt.layer(
            base.mark_area(opacity=0.13, color=annual_color).encode(x=annual_x, y=annual_y("P05"), y2="P95:Q", tooltip=annual_tooltip),
            base.mark_area(opacity=0.27, color=annual_color).encode(x=annual_x, y=annual_y("P25"), y2="P75:Q", tooltip=annual_tooltip),
            base.mark_line(color=annual_color, strokeWidth=2).encode(x=annual_x, y=annual_y("P50"), tooltip=annual_tooltip)
        ).properties(height=260).interactive()
        st.altair_chart(annual_chart, width="stretch")
        st.caption("Full calendar years only. The annual bands summarize daily-compounded portfolio returns; the calculation itself stays daily.")

    st.header("4 · Retirement outcomes")
    complete = run.retirement_paths.loc[run.retirement_paths["Status"] == "complete"]
    failed = run.retirement_paths.loc[run.retirement_paths["Status"] != "complete"]
    a, b, c = st.columns(3)
    a.metric("Complete tax-ledger paths", f"{len(complete)} / {len(run.retirement_paths)}")
    b.metric("Median ending wealth", compact(complete["Ending wealth"].median()))
    c.metric("Paths with spending shortfall", f"{int((complete['Spending shortfall'] > 0).sum())} / {len(complete)}")
    if not failed.empty:
        st.warning("Some paths reached a rule this model does not support. Their reasons are listed in the path table; success counts among complete paths are conditional.")
    wide = wide_wealth_range(run.retirement_bands)
    st.altair_chart(band_chart(run.retirement_bands, "Wealth (AUD proxy" + (", log-like)" if wide else ")"),
                               symlog=wide), width="stretch")
    st.caption("The retirement fan uses the first shared market draws, with Australian tax, salary, spending and super rules applied day by day. Bands include only complete ledgers. "
               + ("The y-axis is linear from AUD 0 to AUD 1,000 and log-like above that, so both central paths and a very high upper path remain visible. " if wide else "")
               + "This is an AUD proxy until USD/AUD FX and Australian distribution tax components are available.")
    st.dataframe(run.retirement_paths, width="stretch", hide_index=True)
    daily, annual = run.result.daily, run.result.annual
    st.subheader(f"Representative daily ledger · path {run.representative_path}")
    st.caption("This complete path ends closest to median ending wealth. Its details illustrate accounting events; a median ending value does not make every intermediate date median.")
    a, b = st.columns(2)
    a.metric("Wealth at start", compact(daily["total"].iloc[0]))
    b.metric(f"Wealth at end ({daily.index[-1].date()})", compact(daily["total"].iloc[-1]))
    a, b = st.columns(2)
    a.metric("Spending shortfall on this path", compact(daily["shortfall"].sum()))
    b.metric("Personal tax assessed on this path", compact(sum(x["assessment"].net_tax + x["assessment"].division_293_tax for x in annual)))
    st.altair_chart(balances_chart(daily), width="stretch")
    st.caption("Month-end account balances show when wealth is accessible outside super and when accumulation moves into an account-based pension. Hover to inspect each account.")
    flows = daily[["salary", "employer_contributions", "pension_payments", "spending_paid", "shortfall", "tax_paid"]].resample("YE-JUN").sum().reset_index()
    flow_long = flows.melt("Date", var_name="Flow", value_name="AUD")
    flow_long = flow_long.groupby("Flow").filter(lambda group: group["AUD"].abs().max() > 1e-9)
    if flow_long.empty:
        st.info("No salary, spending, contribution, pension or tax cash flows in this path.")
    else:
        chart = alt.Chart(flow_long).mark_line(point=True).encode(
            x=alt.X("Date:T", axis=alt.Axis(format="%Y", tickCount=8)), y=alt.Y("AUD:Q", axis=alt.Axis(format="$,.0f")),
            color="Flow:N", tooltip=[alt.Tooltip("Date:T", format="FY ending %Y"), "Flow:N", alt.Tooltip("AUD:Q", format="$,.0f")]
        ).properties(height=310).interactive()
        st.altair_chart(chart, width="stretch")
    st.caption("Financial-year flows distinguish salary, super contributions, pension payments, spending actually paid, shortfall and settled tax. Tax assessment and payment can occur in different years.")
    rows = [{"Year": x["financial_year"], "Taxable income": x["assessment"].taxable_income,
             "Net tax": round(x["assessment"].net_tax), "Minimum CGT": x["assessment"].capital_gains_minimum_tax,
             "Concessional contributions": round(x["concessional_contributions"]),
             "Cap available": round(x["concessional_cap_available"]), "Pension paid": round(x["pension_paid"] or 0),
             "Spending paid": round(x["spending_paid"]), "Shortfall": round(x["shortfall"]),
             "Super at 30 June": round(x["total_super_balance_30_june"])} for x in annual]
    st.subheader("Year-by-year tax, super and spending")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    tax_frame = pd.DataFrame(rows).melt("Year", value_vars=["Taxable income", "Net tax", "Concessional contributions", "Cap available"], var_name="Measure", value_name="AUD")
    tax_frame["FY ending"] = tax_frame["Year"].str.slice(0, 4).astype(int) + 1
    tax_x = alt.X("FY ending:Q", scale=alt.Scale(domain=[int(tax_frame["FY ending"].min()), int(tax_frame["FY ending"].max())]),
                  axis=alt.Axis(format="d", tickCount=7))
    a, b = st.columns(2)
    for column, measures, heading in ((a, ["Taxable income", "Net tax"], "Personal tax"),
                                       (b, ["Concessional contributions", "Cap available"], "Super contribution cap")):
        with column:
            st.markdown(f"**{heading}**")
            part = tax_frame.loc[tax_frame["Measure"].isin(measures)]
            chart = alt.Chart(part).mark_line(point=True).encode(
                x=tax_x, y=alt.Y("AUD:Q", axis=alt.Axis(format="$,.0f")),
                color="Measure:N", tooltip=["Year:N", "Measure:N", alt.Tooltip("AUD:Q", format="$,.0f")]
            ).properties(height=280).interactive()
            st.altair_chart(chart, width="stretch")
    st.caption("Taxable income and assessed net tax use their own scale; contributions and the available concessional cap use a separate scale. Tax assessment and cash settlement can fall in different years.")
    outstanding = run.result.outstanding
    if outstanding["tax_liabilities"] or outstanding["unassessed_year"]:
        st.caption(f"At the horizon: unpaid tax {[l['financial_year'] for l in outstanding['tax_liabilities']]}; "
                   f"unassessed year {(outstanding['unassessed_year'] or {}).get('financial_year')}.")
    if run.folder:
        st.success(f"Saved plan, daily ledgers, path summaries, manifest and PNG review plots to `{run.folder}`.")
        with st.expander("Static PNG review plots"):
            for file in ("portfolio_history.png", "portfolio_future.png", "portfolio_terminal.png",
                         "retirement_range.png", "retirement_flows.png", "ledger.png"):
                st.image(str(run.folder / file), caption=file.replace("_", " ").replace(".png", ""))
    st.download_button("Download daily ledger (CSV)", daily.to_csv(), f"{slug(valid['plan']['name'])}-daily.csv", "text/csv")
    st.download_button("Download events (CSV)", run.result.events.to_csv(index=False), f"{slug(valid['plan']['name'])}-events.csv",
                       "text/csv")
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
