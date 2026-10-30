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
from financial_simulations.retirement.plan import (PlanError, default_plan, load_plan_text, normalize_plan, plan_to_json,
                                                   plan_to_toml, sacrifice_per_year, slug, spending_growth)
from financial_simulations.retirement.flows import account_flows, household_flows, milestones
from financial_simulations.retirement.paths import warm_pool
from financial_simulations.retirement.real import real_daily, real_events, year_deflator
from financial_simulations.retirement.run_plan import ledger_for_path, run_plan
from financial_simulations.rules.au.parameters import UnsupportedRule, load_ruleset
from financial_simulations.rules.au.superannuation import access_date, age_on, birthday
from financial_simulations.rules.au.tax import IncomeYear, assess


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


@st.cache_resource(show_spinner=False)
def start_ledger_workers(count):
    """Start the tax-ledger worker processes once per app server, so the first run does not wait for them."""
    warm_pool(count)
    return True


def request_run():
    st.session_state.run_requested = True


def run_requested_plan():
    """Run at the top of the page, so the progress bar shows at once whichever tab is open."""
    if not st.session_state.pop("run_requested", False):
        return
    try:
        valid = normalize_plan(st.session_state.plan)
    except PlanError:
        st.error("The plan has problems to fix before it can run; see the Results tab.")
        return
    try:
        st.session_state.result = run_with_progress(valid)
        st.session_state.ledger_cache = {}
        st.success("Run complete. Open the Results tab.")
    except (UnsupportedRule, PlanError, ValueError, ArithmeticError) as exc:
        st.session_state.result = None
        st.error(f"The plan cannot run as specified: {exc}")


def save_plan(valid, path):
    PLANS_DIR.mkdir(exist_ok=True)
    path.write_text(plan_to_toml(valid), encoding="utf-8", newline="\n")
    st.session_state.plan_file = path.name
    st.session_state.flash = f"Saved {path}."


def sidebar():
    """Run, then the plan's name and file (save, rename, open), then import/export and reset."""
    st.sidebar.button("Run plan", type="primary", width="stretch", key="run_sidebar", on_click=request_run)
    st.sidebar.caption("Results appear on the Results tab.")
    st.sidebar.header("Your plan")
    plan = st.session_state.plan
    plan["plan"]["name"] = st.sidebar.text_input("Plan name", plan["plan"]["name"], key=key("name"),
                                                 help="Also the file name: saving writes plans/<plan-name>.toml.")
    current = st.session_state.get("plan_file")
    try:
        valid = normalize_plan(plan)
    except PlanError:
        valid = None
        st.sidebar.info("Fix the highlighted problems before saving.")
    if valid is not None:
        target = PLANS_DIR / f"{slug(valid['plan']['name'])}.toml"
        st.sidebar.caption(f"Working on `{PLANS_DIR}/{current}`" if current else "Not saved yet.")
        renaming = current is not None and current != target.name and (PLANS_DIR / current).exists()
        a, b = st.sidebar.columns(2)
        if a.button("Save", width="stretch", key="save_plan",
                    help=f"Write {target}" + (", replacing it" if target.exists() else "")):
            save_plan(valid, target)
            st.rerun()
        if renaming and b.button("Rename", width="stretch", key="rename_plan",
                                 help=f"Save as {target.name} and remove {current}, so only the new name remains."):
            save_plan(valid, target)
            (PLANS_DIR / current).unlink()
            st.session_state.flash = f"Renamed {current} to {target.name}."
            st.rerun()
        if renaming:
            st.sidebar.caption(f"**Save** keeps `{current}` and writes `{target.name}` as a copy; **Rename** replaces it.")
        elif target.exists() and current != target.name:
            st.sidebar.warning(f"`{target.name}` already exists; Save will overwrite it.")
    saved = sorted(PLANS_DIR.glob("*.toml")) + sorted(PLANS_DIR.glob("*.json")) if PLANS_DIR.exists() else []
    if saved:
        names = [f.name for f in saved]
        choice = st.sidebar.selectbox("Open a saved plan", names, key=key(f"saved_{current}"),
                                      index=names.index(current) if current in names else 0)
        if st.sidebar.button("Open", width="stretch", key="open_plan"):
            chosen = PLANS_DIR / choice
            try:
                load_into_session(load_plan_text(chosen.read_text(encoding="utf-8"), chosen.name), f"Opened {chosen}.")
                st.session_state.plan_file = chosen.name
                st.rerun()
            except PlanError as exc:
                st.sidebar.error(str(exc))
    with st.sidebar.expander("Import or download a plan file"):
        upload = st.file_uploader("Import a plan (.toml or .json)", type=["toml", "json"], key=key("upload"))
        if upload is not None:
            try:
                load_into_session(load_plan_text(upload.getvalue().decode("utf-8"), upload.name), f"Imported {upload.name}.")
                st.session_state.plan_file = None
                st.rerun()
            except (PlanError, UnicodeDecodeError) as exc:
                st.error(f"Could not import {upload.name}: {exc}")
        if valid is not None:
            name = slug(valid["plan"]["name"])
            st.download_button("Download as TOML", plan_to_toml(valid), f"{name}.toml", "application/toml", width="stretch")
            st.download_button("Download as JSON", plan_to_json(valid), f"{name}.json", "application/json", width="stretch")
        st.caption("Downloads go to your browser's download folder, for sharing or backup. Save keeps plans in this app.")
    if st.sidebar.button("Start again from the example plan", width="stretch"):
        load_into_session(default_plan(), "Loaded the example plan.")
        st.session_state.plan_file = None
        st.rerun()
    st.sidebar.caption(f"Saved plans live in `{PLANS_DIR}/` (git-ignored). Runs write `output/plans/<plan-name>/`.")


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def date_fields(label, current, name, first_year, last_year):
    """Year, month and day fields: typing a year is quicker than paging a calendar back decades."""
    import calendar

    st.markdown(label)
    y, m, d = st.columns([1, 1.8, 0.9])
    year = int(y.number_input("Year", first_year, last_year, min(max(current.year, first_year), last_year), 1,
                              key=key(f"{name}_year")))
    month = MONTHS.index(m.selectbox("Month", MONTHS, index=current.month - 1, key=key(f"{name}_month"))) + 1
    last = calendar.monthrange(year, month)[1]
    day = int(d.number_input("Day", 1, last, min(current.day, last), 1, key=key(f"{name}_day")))
    return date(year, month, day).isoformat()


def birth_date_input(current):
    return date_fields("Date of birth", current, "born", 1930, 2010)


def inputs_you(plan):
    person, employment = plan["person"], plan["employment"]
    st.subheader("About you")
    a, b = st.columns(2)
    with a:
        person["date_of_birth"] = birth_date_input(date.fromisoformat(person["date_of_birth"]))
    with b:
        person["retirement_age"] = int(st.number_input("Planned retirement age", 18, 80, int(person["retirement_age"]), 1,
                                                       key=key("retire"), help="Salary stops on this birthday."))
        person["private_hospital_cover"] = st.checkbox("Private hospital cover (avoids Medicare levy surcharge)",
                                                       person["private_hospital_cover"], key=key("cover"))
    st.subheader("Work")
    a, b = st.columns(2)
    with a:
        employment["annual_salary"] = money("Gross annual salary (AUD, excluding super)", employment["annual_salary"], "salary",
                                            help="Paid fortnightly until retirement. This is this year's salary.")
        employment["salary_indexed"] = st.checkbox(
            f"Salary rises each year with wage growth ({plan['assumptions']['wage_growth_annual']:.1%}, set on the Assumptions tab)",
            employment.get("salary_indexed", True), key=key("salary_indexed"),
            help="Each 1 July salary and salary sacrifice rise by the wage-growth assumption. Untick to keep salary "
                 "the same dollar amount every year, which means a real pay cut each year.")
    with b:
        mode = st.radio("Salary sacrifice to super, on top of the 12% super guarantee", ["% of salary", "Dollars per year"],
                        index=0 if employment["salary_sacrifice_per_year"] == 0 else 1, horizontal=True, key=key("sacrifice_mode"))
        if mode == "% of salary":
            employment["salary_sacrifice_percent"] = percent("Salary sacrifice % of salary", employment["salary_sacrifice_percent"],
                                                             "sacrifice_pct", low=0, high=100, step=0.5)
            employment["salary_sacrifice_per_year"] = 0.0
        else:
            employment["salary_sacrifice_per_year"] = money("Salary sacrifice per year", employment["salary_sacrifice_per_year"],
                                                            "sacrifice")
            employment["salary_sacrifice_percent"] = 0.0
    work_summary(plan)


def work_summary(plan):
    """First-year estimate of where pay goes, using the 2026-27 rules."""
    employment = plan["employment"]
    salary = employment["annual_salary"]
    if salary <= 0:
        st.caption("No salary: spending is paid from cash, outside investments and, once accessible, super.")
        return
    rules = load_ruleset("2026-27")
    sacrifice = min(sacrifice_per_year(plan), salary)
    sg = rules["super_guarantee_rate"] * min(salary, rules["maximum_contribution_base"])
    concessional = sg + sacrifice
    tax = assess(IncomeYear(labour_income=salary - sacrifice, reportable_employer_super=sacrifice,
                            low_tax_contributions=concessional,
                            private_hospital_cover=plan["person"]["private_hospital_cover"]), rules)
    surplus = salary - sacrifice - tax.net_tax - tax.division_293_tax - plan["spending"]["annual"]
    fixed = plan["outside"]["saving"] == "fixed"
    invested = min(plan["outside"]["contribution_per_year"], max(surplus, 0)) if fixed else max(surplus, 0)
    a, b = st.columns(2)
    c, d = st.columns(2)
    a.metric("Into super per year", f"${concessional:,.0f}",
             help=f"Super guarantee ${sg:,.0f} (12%) plus salary sacrifice ${sacrifice:,.0f}, before 15% contributions tax.")
    b.metric("Concessional cap 2026-27", f"${rules['concessional_cap']:,.0f}",
             help="Contributions above the cap (plus any carried-forward unused cap) are not modelled; the run stops.")
    c.metric("Income tax, first year", f"${tax.net_tax + tax.division_293_tax:,.0f}",
             help="Estimated on salary less sacrifice, before investment income and capital gains.")
    d.metric("Added to outside investments", f"${invested:,.0f}/yr",
             help=("Your fixed contribution, limited to what is left after tax and spending." if fixed else
                   "Take-home pay less tax and spending, all invested.") + " Set this on the Investments tab; contributions from pay "
                   "stop at retirement, after which spare cash above the buffer is reinvested.")
    if fixed and surplus > invested + 1:
        st.caption(f"About ${surplus - invested:,.0f} a year of leftover pay stays in cash, earning the cash interest rate.")
    if fixed and plan["outside"]["contribution_per_year"] > max(surplus, 0) + 1:
        st.warning("The fixed outside contribution is more than is left after tax and spending; only what is available "
                   "above the cash buffer is invested each payday.")
    if concessional > rules["concessional_cap"]:
        st.warning(f"Super guarantee plus salary sacrifice (${concessional:,.0f}) is above the ${rules['concessional_cap']:,.0f} "
                   "concessional cap. Unless you have carried-forward unused cap, the run will stop with an excess-contributions message.")
    st.caption("How saving outside super works: each fortnight your salary after sacrifice goes into cash. Spending (monthly) "
               "and tax (each 31 October) are paid from it. Then either everything above the cash buffer, or your fixed "
               "contribution, buys the outside portfolio (choose on the Investments tab). From retirement, all cash "
               "above the buffer is reinvested instead. The figures are first-year estimates before investment income; "
               + ("salary rises with wage growth after that." if employment.get("salary_indexed", True)
                  else "salary stays the same dollar amount after that."))


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
    saving = st.radio("Yearly additions from your pay until retirement", ["surplus", "fixed"],
                      index=["surplus", "fixed"].index(plan["outside"]["saving"]), horizontal=True, key=key("saving"),
                      format_func={"surplus": "Add everything left after tax and spending",
                                   "fixed": "Add a fixed amount each year"}.get)
    plan["outside"]["saving"] = saving
    if saving == "fixed":
        plan["outside"]["contribution_per_year"] = money("Yearly addition to outside investments",
                                                         plan["outside"]["contribution_per_year"], "outside_contribution",
                                                         help="Invested in equal amounts each fortnightly payday. Leftover pay stays in cash.")
        plan["outside"]["contribution_indexed"] = st.checkbox(
            f"Increase it with inflation each 1 July ({plan['assumptions']['cpi_annual']:.1%} a year, the CPI assumption)",
            plan["outside"]["contribution_indexed"], key=key("contribution_indexed"))
    st.caption("Contributions come out of your pay each fortnight and stop at your retirement date. After retirement all cash "
               "above the buffer is reinvested in this portfolio, such as pension payments, distributions and interest you "
               "do not spend. See the estimate on the You tab.")
    a, b = st.columns(2)
    with a:
        plan["outside"]["cash"] = money("Cash today", plan["outside"]["cash"], "cash")
    with b:
        plan["outside"]["cash_buffer"] = money("Cash buffer kept uninvested", plan["outside"]["cash_buffer"], "buffer")
    plan["outside"]["cash_interest"] = percent("Interest on cash %/yr", plan["outside"]["cash_interest"], "cash_interest",
                                               low=-5, high=20, step=0.25,
                                               help="Assumed nominal rate on all outside cash, credited daily and taxed as income.")
    plan["outside"]["investment_balance"] = money("Investments today", plan["outside"]["investment_balance"], "outside_value")
    with st.expander("Opening tax position for outside investments"):
        st.caption("One aggregate cost base and acquisition date are allocated across the portfolio. This is an approximation if you bought at different times or prices.")
        plan["outside"]["opening_cost_base"] = money("Total cost base", plan["outside"]["opening_cost_base"], "outside_basis")
        plan["outside"]["opening_acquired"] = date_fields("Acquisition date used for the opening portfolio",
                                                          date.fromisoformat(plan["outside"]["opening_acquired"]), "acquired",
                                                          1950, date.fromisoformat(plan["plan"]["start_date"]).year)
    plan["outside"]["weights"] = weights_editor("Outside-super portfolio", plan["outside"]["weights"], names, "outw")
    plan["outside"]["rebalance"] = rebalance_choice(plan["outside"]["rebalance"], "outside_rebalance",
                                                    "Outside super each rebalance sells overweight holdings, which realises capital gains tax.")
    st.subheader("Portfolio inside super")
    a, b = st.columns(2)
    with a:
        plan["super"]["balance"] = money("Super balance today", plan["super"]["balance"], "super")
    with b:
        same = st.checkbox("Balance at last 30 June was the same", plan["super"]["total_super_balance_prior_30_june"]
                           == plan["super"]["balance"], key=key("tsb_same"),
                           help="The total super balance on the previous 30 June sets this year's contribution caps "
                                "(carry-forward and non-concessional). Untick only if it differed from today's balance.")
        if same:
            plan["super"]["total_super_balance_prior_30_june"] = plan["super"]["balance"]
        else:
            plan["super"]["total_super_balance_prior_30_june"] = money(
                "Total super balance at last 30 June", plan["super"]["total_super_balance_prior_30_june"], "tsb")
    plan["super"]["weights"] = weights_editor("Inside-super portfolio", plan["super"]["weights"], names, "supw")
    plan["super"]["rebalance"] = rebalance_choice(plan["super"]["rebalance"], "super_rebalance",
                                                  "Inside super the switch itself is untaxed; the fund's own trading is "
                                                  "covered by the realised-gains assumption below.")
    plan["super"]["realised_gains"] = percent(
        "Share of the fund's unrealised gains realised each year %", plan["super"]["realised_gains"], "super_realised",
        low=0, high=100, step=5.0,
        help="Super funds trade, so part of the growth in your balance is realised as capital gains each year. In "
             "accumulation these are taxed at 15% after the one-third discount (10% effective); in the pension they are "
             "tax-free. Both count towards Division 296 above a 3 million dollar balance. There is no published turnover "
             "figure for funds: 20% is an assumption (gains held about five years on average). 0% realises nothing "
             "and gives the lowest tax; 100% realises every year's gain.")


RULE_LABELS = {"fixed": "Fixed: the same buying power every year (default)", "guyton_klinger": "Guyton–Klinger guardrails",
               "vanguard": "Vanguard ceiling and floor", "percent": "A percentage of wealth each year"}
START_LABELS = {"same": "The same as now", "amount": "A different amount", "percent": "A percentage of wealth at retirement"}


def spending_rule_inputs(plan):
    """How retirement spending is set and how it responds to markets. Rules need a percentage start."""
    spending, cpi = plan["spending"], plan["assumptions"]["cpi_annual"]
    st.subheader("Spending in retirement")
    spending["rule"] = st.radio("How spending responds to markets", list(RULE_LABELS), index=list(RULE_LABELS).index(spending["rule"]),
                                format_func=RULE_LABELS.get, key=key("spending_rule"))
    fixed = spending["rule"] == "fixed"
    if fixed:
        spending["retirement"] = st.radio("Retirement spending starts at", list(START_LABELS),
                                          index=list(START_LABELS).index(spending["retirement"]), format_func=START_LABELS.get,
                                          horizontal=True, key=key("spend_start"))
    else:
        spending["retirement"] = "percent"
    if spending["retirement"] == "amount":
        spending["retirement_annual"] = money("Spending once retired (today's dollars a year)", spending["retirement_annual"],
                                              "spend_retired", help="Rises with inflation like spending now.")
    elif spending["retirement"] == "percent":
        spending["retirement_percent"] = percent(
            "Starting withdrawal rate: % of total wealth on your retirement date", spending["retirement_percent"],
            "spend_rate", low=0.1, high=50, step=0.1,
            help="Total wealth is cash, outside investments and super. Each simulated path reaches retirement with "
                 "different wealth, so each gets its own dollar amount; the results show the range in today's dollars.")
        st.caption("Each path's starting amount is this percentage of its own wealth on your retirement date, so it is "
                   "only known after the simulation runs. Section 4 of the results shows the range it produced. For "
                   "reference, Guyton and Klinger tested starting rates of about 5–5.5% with their guardrails; 4% is a "
                   "common rule of thumb for fixed spending over 30 years.")
    if fixed:
        how = {"same": "the amount above", "amount": "this amount",
               "percent": "that percentage of your wealth on your retirement date"}[spending["retirement"]]
        st.info(f"**Default: fixed spending.** You spend {how} in your first retired year, and after that the same "
                f"buying power every year, whatever the markets do. If markets fall, spending stays the same and takes a "
                "bigger share of what is left, which is how plans run out of money.")
    elif spending["rule"] == "guyton_klinger":
        st.info("**Guyton–Klinger guardrails** (Guyton and Klinger, 2006). On your retirement date spending starts at the "
                "starting rate above. Each 1 July after that, the *withdrawal rate* is that year's spending divided by "
                "total wealth:\n"
                "1. After a year in which your investments lost money, skip that year's inflation increase if the rate is "
                "above the start.\n"
                f"2. If the rate is more than {spending['guardrail_band']:.0%} above the start, **cut spending "
                f"{spending['guardrail_step']:.0%}**.\n"
                f"3. If it is more than {spending['guardrail_band']:.0%} below the start, **raise spending "
                f"{spending['guardrail_step']:.0%}**.\n\n"
                "In this planner's simulations it rarely runs out of money, but about one in five paths has a year more "
                "than 20% below the starting amount.")
        a, b = st.columns(2)
        with a:
            spending["guardrail_band"] = percent("Guardrail width %", spending["guardrail_band"], "gk_band", low=1, high=90,
                                                 step=1.0, help="How far the withdrawal rate can move from its start before "
                                                                "spending changes.")
        with b:
            spending["guardrail_step"] = percent("Change when a guardrail is hit %", spending["guardrail_step"], "gk_step", low=1,
                                                 high=90, step=1.0)
    elif spending["rule"] == "vanguard":
        st.info("**Vanguard ceiling and floor** (Jaconetti and colleagues, Vanguard, 2013). On your retirement date "
                "spending starts at the starting rate above. Each 1 July after that, spending aims for that rate times "
                f"your current wealth, but the change from last year (after inflation) is limited to **+{spending['ceiling']:.1%}** "
                f"and **−{spending['floor']:.1%}**, so cuts are small and gradual. In this planner's simulations cuts were "
                "gentler than Guyton–Klinger, but at a 5% start it ran out about as often as fixed spending.")
        a, b = st.columns(2)
        with a:
            spending["ceiling"] = percent("Largest yearly rise %", spending["ceiling"], "vg_ceiling", low=0, high=90, step=0.5)
        with b:
            spending["floor"] = percent("Largest yearly cut %", spending["floor"], "vg_floor", low=0, high=90, step=0.5)
    else:
        st.info("**A percentage of wealth each year.** On your retirement date and each 1 July after that, spending is "
                "the starting rate times your total wealth that day. It can never run out (bounded by the minimum "
                "below), but spending moves fully with the markets: a 30% fall cuts next year's spending by 30%. It is a "
                "useful reference for how much variability the other rules remove.")
    if not fixed:
        a, b = st.columns(2)
        with a:
            spending["minimum"] = money("Essential minimum, never cut below (today's dollars a year; 0 = none)",
                                        spending["minimum"], "spend_minimum",
                                        help="Rises with inflation. A higher minimum makes cuts shallower but raises the "
                                             "chance of running out.")
        with b:
            spending["maximum"] = money("Maximum, never spend more than (today's dollars a year; 0 = none)",
                                        spending["maximum"], "spend_maximum",
                                        help="Rises with inflation. Stops spending racing up on paths where markets do very well.")
        st.caption("Rules review spending once a year on 1 July after your retirement date, using total wealth "
                   "(cash, outside investments and super). Each review and its reason are in the event log in section 5.")


def inputs_retirement(plan):
    st.subheader("Spending")
    spending, cpi = plan["spending"], plan["assumptions"]["cpi_annual"]
    spending["annual"] = money("Spending now (today's dollars a year)", spending["annual"], "spend",
                               help="Everything you spend in a year, paid monthly from cash.")
    st.caption(f"All spending amounts are in **today's dollars**. Each 1 July they rise with inflation ({cpi:.1%} CPI, set "
               "on the Assumptions tab), so they buy the same every year.")
    spending_rule_inputs(plan)
    with st.expander("Spend more or less over time", expanded=spending["real_change"] != 0):
        spending["real_change"] = percent(
            "Real change in spending, % a year on top of inflation", spending["real_change"], "spend_real", low=-10, high=10,
            help="0 keeps buying power constant. Studies of retirees' actual spending find it tends to fall slowly "
                 "with age in real terms, by roughly 1% a year (the 'retirement spending smile'); −1% models that.")
        st.caption("This applies before and after retirement, and to the starting amount set by a percentage. The "
                   "essential minimum and maximum always rise with inflation only.")
    st.subheader("Account-based pension")
    pension = plan["pension"]
    a, b = st.columns(2)
    with a:
        pension["start_age"] = int(st.number_input("Start pension at age (0 = never)", 0, 80, int(pension["start_age"]), 1,
                                                   key=key("pension_age"),
                                                   help="Needs retirement and age 60 or over, or age 65. An earlier age "
                                                        "starts the pension when super becomes accessible."))
    with b:
        pension["transfer_all"] = st.checkbox("Move the whole super balance into the pension (up to the transfer balance cap)",
                                              pension["transfer_all"], key=key("all"))
        if not pension["transfer_all"]:
            pension["amount"] = money("Amount to move into the pension", pension["amount"], "pension_amount")
    st.caption("Before super is accessible, spending is paid from cash and outside investments; any gap is shown as a shortfall.")
    st.subheader("Age Pension (from age 67)")
    person = plan["person"]
    a, b = st.columns(2)
    with a:
        person["homeowner"] = st.checkbox("I own my home", person["homeowner"], key=key("homeowner"),
                                          help="Your home is exempt from the assets test. Non-homeowners have a higher "
                                               "assets limit ($600,000 instead of $333,000 for a full pension).")
    with b:
        person["other_assets"] = money("Other assessable assets (AUD)", person["other_assets"], "other_assets",
                                       help="Cars, caravans, home contents and other personal assets at what they would "
                                            "sell for. They count in the assets test but are not invested.")
    st.caption("From a fortnight after you turn 67 the planner works out the single Age Pension every fortnight: the "
               "lower of the assets test (everything you hold except your home) and the income test (deemed income on "
               "your investments and super, plus any wages after the Work Bonus). It is paid into cash and is partly "
               "taxable, and the seniors and pensioners tax offset applies. It assumes you have lived in Australia for "
               "at least 10 years and claim on time.")


def inputs_assumptions(plan):
    st.subheader("Horizon")
    a, b = st.columns(2)
    with a:
        plan["plan"]["start_date"] = st.date_input("Start date", date.fromisoformat(plan["plan"]["start_date"]), date(2026, 7, 1),
                                                   date(2040, 6, 30), key=key("start"), format="YYYY-MM-DD").isoformat()
    with b:
        plan["plan"]["years"] = int(st.number_input("Years to simulate", 1, 60, int(plan["plan"]["years"]), 1, key=key("years"),
                                                    help="Runs can go past Age Pension age; set this to reach your planning "
                                                         "age to see the whole retirement in the tax ledger."))
    st.subheader("Economic assumptions")
    a, b = st.columns(2)
    with a:
        plan["assumptions"]["cpi_annual"] = percent("CPI %/yr", plan["assumptions"]["cpi_annual"], "cpi", low=-10, high=20,
                                                    help="Indexes CGT cost bases from 1 July 2027 and CPI-linked thresholds.")
    with b:
        plan["assumptions"]["wage_growth_annual"] = percent("Wage growth %/yr", plan["assumptions"]["wage_growth_annual"], "wages",
                                                            low=-10, high=20, help="Raises salary each year (if ticked on the You tab) and indexes "
                                                                                     "contribution caps and MLS thresholds.")
    plan["assumptions"]["planning_age"] = int(st.number_input(
        "Plan retirement income to age", 60, 110, int(plan["assumptions"]["planning_age"]), 1, key=key("planning_age"),
        help="Sustainable withdrawal rates test whether the portfolios last from retirement to this age."))
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
        plan["market"]["block_length"] = int(st.number_input("Average block length (trading days)", 1, 1260,
                                                               int(plan["market"]["block_length"]), 1,
                                                               key=key("block_length"),
                                                               help="How long, on average, each copied run of history is."))
    with st.expander("What is the average block length?"):
        block = plan["market"]["block_length"]
        st.markdown(f"""
Each simulated future is stitched together from **runs of real history**. The simulator picks a random trading day in
the shared history and copies the following days in order (every ticker on the same day, so they move together as
they really did). After each day it either carries on with the next historical day or, with probability
1/{block}, jumps to a new random day and starts another run. Runs therefore last **{block} trading days on average**
(about {block / 21:.0f} months; there are roughly 252 trading days a year), some much shorter and some much longer.

**Why it matters.** Within a run, real patterns survive: a crash that unfolds over weeks, a volatile spell, a
recovery. Between runs, eras are mixed, so one path might go from 1987 to 2008 to 1975.
- **Longer blocks** (e.g. 252, one year) keep longer patterns such as multi-month bear markets and the way rates
  and stocks moved together for a while, but each path repeats larger chunks of the same history, so paths look
  more alike.
- **Shorter blocks** (e.g. 5–21) mix history more freely and give more variety, but break up longer crises and
  trends into pieces, which can understate how long bad stretches last.
- **1** draws every day independently, losing all short-term patterns; usually too optimistic about smooth paths.

63 days (about three months) is a common middle ground. If results change a lot between, say, 21 and 252, treat the
difference as part of the uncertainty.
""")


PALETTE = {"Outside super": "#126a63", "Inside super": "#386a98", "Combined": "#b76a42"}
ACCOUNTS = {"cash": ("Cash", "#9a8a2e"), "outside_investments": ("Outside investments", "#126a63"),
            "accumulation": ("Super (accumulation)", "#386a98"), "pension": ("Account-based pension", "#8363a0")}
MONEY = "$%,d"


ZOOM_COUNT = [0]


def zoomable(chart):
    """Drag to pan and Shift+scroll to zoom; plain scrolling keeps scrolling the page."""
    import altair as alt

    # Explicit unique names: auto-generated ones can collide in layered charts ("Duplicate signal name").
    ZOOM_COUNT[0] += 1
    zoom = alt.selection_interval(bind="scales", zoom="wheel![event.shiftKey]", name=f"zoom_{ZOOM_COUNT[0]}")
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
                    labelOverlap=True, grid=True, gridOpacity=0.35)


YEAR_TITLE = "Year ending 30 June"
BORN = {"date": None}  # the current plan's birth date, set before results are drawn, for "Age" in tooltips


def add_age(frame, field="Date"):
    """Add an Age column (whole years on that date, or at 30 June for a financial year) when a birth date is known."""
    born = BORN["date"]
    if born is None or field not in frame:
        return frame
    frame = frame.copy()
    if field == "FY ending":
        days = [date(int(y), 6, 30) for y in frame[field]]
    elif field == "Year":  # calendar years: age at 31 December
        days = [date(int(y), 12, 31) for y in frame[field]]
    else:
        days = [pd.Timestamp(d).date() for d in frame[field]]
    frame["Age"] = [age_on(born, d) if d >= born else None for d in days]
    return frame


def age_tooltip(frame):
    import altair as alt

    return [alt.Tooltip("Age:Q", title="Your age", format="d")] if "Age" in frame else []


def period(end_year):
    """Plain wording for an Australian financial year, e.g. 2027 -> 'Jul 2026 – Jun 2027'."""
    return f"Jul {int(end_year) - 1} – Jun {int(end_year)}"


def period_label(end_year):
    """A financial year for tooltips, with the person's age at its 30 June when known."""
    born = BORN["date"]
    text = period(end_year)
    return f"{text} (age {age_on(born, date(int(end_year), 6, 30))} at 30 June)" if born else text


def fy_axis(frame, field="FY ending"):
    import altair as alt

    years = frame[field]
    step = 5 if years.nunique() >= 25 else 2 if years.nunique() >= 12 else 1
    return alt.Axis(format="d", values=[y for y in range(int(years.min()), int(years.max()) + 1) if y % step == 0 or step == 1],
                    grid=True, gridOpacity=0.35, title=YEAR_TITLE)


def with_milestones(chart, marks, x="Date:T"):
    """Overlay dashed vertical lines and labels for life events on a time or financial-year chart."""
    import altair as alt

    if marks is None or marks.empty:
        return chart
    rule = alt.Chart(marks).mark_rule(strokeDash=[4, 3], color="#5f6b73", strokeWidth=1.3).encode(
        x=x, tooltip=["Event:N", alt.Tooltip("Date:T", format="%d %b %Y")])
    text = alt.Chart(marks).mark_text(align="left", dx=4, fontSize=11, color="#3c474d").encode(
        x=x, y=alt.Y("Offset:Q", scale=None), text="Event:N")
    return alt.layer(chart, rule, text)


def balances_chart(daily):
    """Stacked month-end balances by account, in a fixed account order and colour."""
    import altair as alt

    monthly = daily[list(ACCOUNTS)].resample("ME").last().reset_index()
    long = monthly.melt("Date", var_name="account", value_name="balance")
    long["Account"] = long["account"].map(lambda a: ACCOUNTS[a][0])
    long["order"] = long["account"].map(list(ACCOUNTS).index)
    long["Total"] = long.groupby("Date")["balance"].transform("sum")
    long["Share"] = long["balance"] / long["Total"].where(long["Total"] > 0)
    long = add_age(long)
    return zoomable(alt.Chart(long).mark_area().encode(
        x=alt.X("Date:T", title=None, axis=year_axis(long)),
        y=alt.Y("balance:Q", stack="zero", title="Today's dollars", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Account:N", sort=[v[0] for v in ACCOUNTS.values()],
                        scale=alt.Scale(domain=[v[0] for v in ACCOUNTS.values()], range=[v[1] for v in ACCOUNTS.values()]),
                        legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), *age_tooltip(long), "Account:N",
                 alt.Tooltip("balance:Q", title="Balance", format="$,.0f"), alt.Tooltip("Share:Q", title="Share of wealth", format=".0%"),
                 alt.Tooltip("Total:Q", title="Total wealth", format="$,.0f")],
    ).properties(height=530))


def symlog_axis(upper):
    """A dollar axis for a symlog scale: $0 and powers of ten, labelled $1k, $10k, ... $1m."""
    import altair as alt

    first_power = 4 if upper >= 1e6 else 3
    ticks = [0, *[10 ** power for power in range(first_power, 13) if 10 ** power <= upper]]
    labels = ("datum.value === 0 ? '$0' : datum.value >= 1000000 ? "
              "'$' + datum.value / 1000000 + 'm' : '$' + datum.value / 1000 + 'k'")
    return alt.Axis(values=ticks, labelExpr=labels, labelOverlap=False)


def band_chart(frame, title, *, log=False, symlog=False, color="#126a63", percent=False, x="Date:T", marks=None, height=520):
    """Hoverable percentile bands with zoom, a sparse long-horizon year axis and optional life-event lines."""
    import altair as alt

    if x == "Date:T":
        xs = alt.X("Date:T", title=None, axis=year_axis(frame))
    else:
        field = x.split(":")[0]
        xs = alt.X(x, scale=alt.Scale(domain=[int(frame[field].min()) - 0.5, int(frame[field].max()) + 0.5], nice=False),
                   axis=fy_axis(frame, field) if field == "FY ending" else alt.Axis(format="d", grid=True, gridOpacity=0.35,
                                                                                    title=None))
    if symlog:
        scale = alt.Scale(type="symlog", constant=1000, zero=True)
    elif log:
        scale = alt.Scale(type="log", domain=[float(frame["P05"].min()) * 0.9, float(frame["P95"].max()) * 1.1], nice=False)
    else:
        scale = alt.Scale(zero=True)
    if symlog:
        axis = symlog_axis(float(frame["P95"].max()))
    else:
        axis = alt.Axis(format=".0%" if percent else "$,.0f")
    number = ".1%" if percent else "$,.0f"
    y = alt.Y("P05:Q", title=title, scale=scale, axis=axis)
    frame = add_age(frame, "Date" if x == "Date:T" else x.split(":")[0])
    when = (alt.Tooltip("Date:T", format="%b %Y") if x == "Date:T" else
            alt.Tooltip("Period:N", title="Year") if "Period" in frame else alt.Tooltip(x, format="d"))
    names = {"P05": "5th percentile (1 in 20 paths lower)", "P25": "25th percentile", "P50": "Median",
             "P75": "75th percentile", "P95": "95th percentile (1 in 20 paths higher)"}
    tooltip = [when, *age_tooltip(frame), *[alt.Tooltip(f"{q}:Q", title=names[q], format=number) for q in names]]
    base = alt.Chart(frame)
    outer = base.mark_area(opacity=0.13, color=color).encode(x=xs, y=y, y2="P95:Q", tooltip=tooltip)
    inner = base.mark_area(opacity=0.27, color=color).encode(x=xs, y="P25:Q", y2="P75:Q", tooltip=tooltip)
    median = base.mark_line(color=color, strokeWidth=2).encode(x=xs, y="P50:Q", tooltip=tooltip)
    chart = zoomable(alt.layer(outer, inner, median).properties(height=height))
    if marks is not None:
        if x != "Date:T":  # keep event labels inside the financial-year domain
            field = x.split(":")[0]
            marks = marks.loc[marks["Position"].between(frame[field].min() - 0.5, frame[field].max() + 0.5)]
        chart = with_milestones(chart, marks, "Date:T" if x == "Date:T" else "Position:Q")
    return chart


def quantile_bands(frame, by, field):
    q = frame.groupby(by)[field].quantile([0.05, 0.25, 0.5, 0.75, 0.95]).unstack().reset_index()
    q.columns = [by, "P05", "P25", "P50", "P75", "P95"]
    if by == "FY ending":
        q["Period"] = q[by].map(period_label)
    return q


SHOWN_PATHS = 300  # funded paths drawn; every path that ran out is drawn as well
GREY, RED, MEDIAN = "#3d3d3d", "#c0392b", "#126a63"


def shown_paths(paths):
    """Paths to draw: every depleted path, and up to SHOWN_PATHS funded paths spread evenly across ending wealth.

    Spacing by ending-wealth rank keeps the sample's spread the same as the full set's, so the grey density is a
    fair picture of the distribution while the browser handles a bounded number of lines.
    """
    ending = paths.sort_values("Date").groupby("Path").agg(Status=("Status", "first"), End=("Total wealth", "last"))
    depleted = ending.index[ending["Status"] == "depleted"].tolist()
    funded = ending.loc[ending["Status"] != "depleted"].sort_values("End")
    if len(funded) > SHOWN_PATHS:
        funded = funded.iloc[np.unique(np.linspace(0, len(funded) - 1, SHOWN_PATHS).round().astype(int))]
    return funded.index.tolist(), depleted


def paths_image(paths, funded, depleted, first, last, top, wide):
    """The drawn paths as one transparent PNG data URL, in the chart's exact (linear or symlog) space.

    Grey funded paths are translucent, so overlaps darken where most paths went; paths that ran out are drawn on top
    in near-solid red.
    """
    import base64
    import io

    from matplotlib.collections import LineCollection
    from matplotlib.figure import Figure

    fig = Figure(figsize=(14, 7), dpi=120)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.patch.set_alpha(0)
    span = (last - first) or pd.Timedelta(days=1)

    def transform(values):
        # Vega's symlog with constant C maps y to sign(y) * log1p(|y| / C); reproduce it so pixels line up.
        return np.sign(values) * np.log1p(np.abs(values) / 1000) if wide else values

    groups = dict(tuple(paths.groupby("Path", sort=False)))
    # About 45 overlapping grey lines reach full darkness; a few red lines are near solid, many are lighter so
    # the red does not hide the grey distribution underneath.
    grey_alpha = float(np.clip(45 / max(len(funded), 1), 0.08, 0.4))
    red_alpha = float(np.clip(25 / max(len(depleted), 1), 0.3, 0.85))
    for chosen, colour, alpha, width in ((funded, GREY, grey_alpha, 0.9), (depleted, RED, red_alpha, 1.3)):
        # Timedelta division, not raw integers: pandas may store the dates in microseconds rather than nanoseconds.
        segments = [np.column_stack((((pd.to_datetime(groups[p]["Date"]) - first) / span).to_numpy(dtype=float),
                                     transform(groups[p]["Total wealth"].to_numpy()))) for p in chosen]
        if segments:
            ax.add_collection(LineCollection(segments, colors=colour, linewidths=width, alpha=alpha))
    ax.set_xlim(0, 1)
    ax.set_ylim(transform(np.array([0.0]))[0], transform(np.array([top]))[0])
    from PIL import Image

    rendered = io.BytesIO()
    fig.savefig(rendered, format="png", transparent=True)
    # A 256-colour palette keeps the transparency and is several times smaller than full-colour RGBA.
    rendered.seek(0)
    buffer = io.BytesIO()
    Image.open(rendered).quantize(256, method=Image.Quantize.FASTOCTREE).save(buffer, format="png", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def all_paths_chart(paths, marks, outcomes=None, cache_key=None, log=True):
    """Many paths' total wealth: translucent grey lines whose overlaps show the distribution, ruin paths in red.

    Speed: the drawn lines are one server-rendered image, cached per result, so the browser never draws hundreds
    of lines and a rerun does not repaint it. Hover data are the drawn paths only, quarterly for the highlighted
    line and yearly for the pointer targets, and the chart uses the canvas renderer.
    """
    import altair as alt

    medians = paths.groupby("Date")["Total wealth"].median()  # from every path, drawn or not
    funded, depleted = shown_paths(paths)
    drawn = paths.loc[paths["Path"].isin(funded + depleted), ["Date", "Path", "Status", "Total wealth"]]
    wide = log  # symlog: logarithmic above $1,000 and linear below, so paths at $0 still plot
    # On a linear axis the top stops just above the 97.5th percentile of the paths' peaks, so a few runaway paths do
    # not squash the band where most paths sit; about one path in forty is clipped. The log axis shows every path.
    peaks = drawn.groupby("Path")["Total wealth"].max()
    top = (float(peaks.max()) * 1.02 if log
           else min(float(peaks.max()) * 1.02, float(peaks.quantile(0.975)) * 1.05)) or 1.0
    clipped = int((peaks > top).sum())
    first, last = pd.Timestamp(paths["Date"].min()), pd.Timestamp(paths["Date"].max())
    cache = st.session_state.setdefault("paths_image_cache", {})
    cache_key = (cache_key, top, wide)
    if cache_key[0] is None or cache_key not in cache:
        cache.clear()  # only the current result's image is kept
        cache[cache_key] = paths_image(drawn, funded, depleted, first, last, top, wide)
    y_scale = (alt.Scale(type="symlog", constant=1000, domain=[0, top], nice=False) if wide
               else alt.Scale(domain=[0, top], nice=False))
    y_title = "Total wealth, today's dollars" + (" · log scale" if wide else "")
    y_axis = symlog_axis(top) if wide else alt.Axis(format="$,.0f")
    y = alt.Y("Total wealth:Q", title=y_title, scale=y_scale, axis=y_axis)
    x = alt.X("Date:T", title=None, axis=year_axis(drawn), scale=alt.Scale(domain=[first.isoformat(), last.isoformat()]))
    # The image's left edge must use the same field name as the shared x encoding ("Date"), or it is never placed.
    image = pd.DataFrame({"url": [cache[cache_key]], "Date": [first.isoformat()],
                          "x2": [last.isoformat()], "y": [top], "y2": [0.0]})
    lines = alt.Chart(image).mark_image(aspect=False, align="left", baseline="top").encode(
        x=x, x2="x2:T", y=alt.Y("y:Q", scale=y_scale, title=y_title, axis=y_axis), y2="y2:Q", url="url:N")
    hover = alt.selection_point(fields=["Path"], on="pointerover", nearest=True, clear="pointerout", empty=False,
                                name="path_hover")
    # Compact hover data: dates as plain strings, whole dollars, and per-path facts joined in the browser.
    dates = pd.to_datetime(drawn["Date"])

    def compact_rows(frame):
        return frame.assign(Date=pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d"),
                            **{"Total wealth": frame["Total wealth"].round()})

    quarterly = compact_rows(drawn.loc[dates.dt.month.isin([3, 6, 9, 12]) | (dates == dates.max()) | (dates == dates.min()),
                                       ["Date", "Path", "Total wealth"]])
    highlight = alt.Chart(quarterly).transform_filter(hover).mark_line(strokeWidth=3.5, color="#0b3d45", clip=True).encode(
        x=x, y=y, detail="Path:N")
    yearly = compact_rows(add_age(drawn.loc[(dates.dt.month == 6) | (dates == dates.max()), ["Date", "Path", "Total wealth"]]))
    info = drawn.drop_duplicates("Path")[["Path", "Status"]]
    if outcomes is not None:
        info = info.merge(outcomes[["Path", "Ending wealth", "Spending shortfall", "First shortfall",
                                    "First retired-year withdrawal rate"]], on="Path", how="left")
        info = info.assign(**{c: info[c].round() for c in ("Ending wealth", "Spending shortfall")})
    extra = [alt.Tooltip(f, format=fmt, title=t) if fmt else alt.Tooltip(f, title=t) for f, fmt, t in
             (("Ending wealth:Q", "$,.0f", "Path's ending wealth"), ("Spending shortfall:Q", "$,.0f", "Path's spending shortfall"),
              ("First shortfall:N", None, "Money first ran short"),
              ("First retired-year withdrawal rate:Q", ".1%", "Path's first retired-year withdrawal rate"))
             if f.split(":")[0] in info]
    points = alt.Chart(yearly).transform_lookup(
        lookup="Path", from_=alt.LookupData(info, "Path", [c for c in info.columns if c != "Path"])
    ).mark_point(opacity=0, size=80, clip=True).encode(
        x=x, y=y,
        tooltip=[alt.Tooltip("Path:N", title="Path"), "Status:N", alt.Tooltip("Date:T", format="%b %Y"), *age_tooltip(yearly),
                 alt.Tooltip("Total wealth:Q", title="Wealth on this date", format="$,.0f"), *extra]).add_params(hover)
    median_frame = add_age(medians.reset_index())
    median = alt.Chart(median_frame).mark_line(color=MEDIAN, strokeWidth=3, clip=True).encode(
        x=x, y=y,
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), *age_tooltip(median_frame),
                 alt.Tooltip("Total wealth:Q", title="Median of all paths", format="$,.0f")])
    layers = [lines, median, highlight, points]
    if outcomes is not None and depleted:
        # A red marker where each ruin path first ran short, at that month's wealth.
        ruined = outcomes.loc[outcomes["Path"].isin(depleted) & (outcomes["First shortfall"] != ""), ["Path", "First shortfall"]]
        if not ruined.empty:
            ruined = ruined.assign(Date=pd.to_datetime(ruined["First shortfall"]) + pd.offsets.MonthEnd(0))
            ruined = ruined.merge(drawn[["Path", "Date", "Total wealth"]], on=["Path", "Date"], how="left").dropna()
            ruined = add_age(ruined)
            layers.append(alt.Chart(ruined).mark_point(shape="cross", size=90, filled=True, color=RED, opacity=0.95).encode(
                x=x, y=y, tooltip=[alt.Tooltip("Path:N", title="Path"), alt.Tooltip("First shortfall:N", title="Money first ran short"),
                                   *age_tooltip(ruined)]))
    # One flat layer: nesting a chart that owns a selection inside another layer duplicates its signals.
    ZOOM_COUNT[0] += 1
    zoom = alt.selection_interval(bind="scales", zoom="wheel![event.shiftKey]", name=f"zoom_{ZOOM_COUNT[0]}")
    layers[0] = lines.add_params(zoom)
    if marks is not None and not marks.empty:
        layers += [alt.Chart(marks).mark_rule(strokeDash=[4, 3], color="#5f6b73", strokeWidth=1.3).encode(
                       x="Date:T", tooltip=["Event:N", alt.Tooltip("Date:T", format="%d %b %Y")]),
                   alt.Chart(marks).mark_text(align="left", dx=4, fontSize=11, color="#3c474d").encode(
                       x="Date:T", y=alt.Y("Offset:Q", scale=None), text="Event:N")]
    chart = alt.layer(*layers).properties(height=620, usermeta={"embedOptions": {"renderer": "canvas"}})
    return chart, len(funded), len(depleted), clipped


def ending_wealth_chart(calculated, marks_text=True):
    """Every path's ending wealth, sorted: hover a dot for its exact values; the median and 10th/90th are labelled."""
    import altair as alt

    # Vega-Lite field names cannot contain an apostrophe.
    frame = calculated.sort_values("Ending wealth").reset_index(drop=True).rename(
        columns={"Ending wealth, nominal": "Ending nominal"})
    frame["Rank"] = (np.arange(len(frame)) + 0.5) / len(frame)
    wide = float(frame["Ending wealth"].max()) > 20 * max(1000.0, float(frame["Ending wealth"].median()))
    y = alt.Y("Ending wealth:Q", title="Ending wealth, today's dollars" + (" (log-like)" if wide else ""),
              scale=alt.Scale(type="symlog", constant=1000) if wide else alt.Scale(zero=True), axis=alt.Axis(format="$,.0f"))
    dots = alt.Chart(frame).mark_circle(size=70, opacity=0.85).encode(
        x=alt.X("Rank:Q", title="Paths ranked by ending wealth (share of paths below)", axis=alt.Axis(format=".0%", grid=True),
                scale=alt.Scale(domain=[0, 1])),
        y=y, color=alt.Color("Status:N", scale=alt.Scale(domain=["funded", "depleted"], range=["#126a63", "#b23a3a"]),
                             legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("Path:Q", format="d"), "Status:N", alt.Tooltip("Rank:Q", title="Share of paths below", format=".0%"),
                 alt.Tooltip("Ending wealth:Q", title="Ending wealth, today's dollars", format="$,.0f"),
                 alt.Tooltip("Ending outside wealth:Q", title="Outside super", format="$,.0f"),
                 alt.Tooltip("Ending super and pension:Q", title="Super and pension", format="$,.0f"),
                 alt.Tooltip("Spending shortfall:Q", format="$,.0f")])
    points = pd.DataFrame([{"Rank": q, "Ending wealth": float(frame["Ending wealth"].quantile(q)),
                            "Label": f"{name}: {compact(float(frame['Ending wealth'].quantile(q)))}"}
                           for q, name in ((0.1, "10th pct"), (0.5, "Median"), (0.9, "90th pct"))])
    rules = alt.Chart(points).mark_rule(strokeDash=[4, 3], color="#5f6b73").encode(y="Ending wealth:Q")
    labels = alt.Chart(points).mark_text(align="left", x=8, dy=-8, fontSize=12, fontWeight="bold", color="#19353a").encode(
        y="Ending wealth:Q", text="Label:N")
    return zoomable(alt.layer(dots, rules, labels).properties(height=550))


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
    bars = alt.Chart(part).mark_bar(opacity=0.45 if len(series) > 2 else 0.5, binSpacing=0).encode(
        x=alt.X(f"{value}:Q", bin=alt.Bin(maxbins=40), axis=axis),
        y=alt.Y("count():Q", stack=None, title="Paths"),
        color=alt.Color("Portfolio:N", scale=scale_for(series),
                        legend=alt.Legend(orient="bottom", title=None, direction="vertical", labelLimit=200)),
        tooltip=["Portfolio:N", alt.Tooltip("count():Q", title="Paths in this bar"),
                 *([] if log else [alt.Tooltip(f"{value}:Q", bin=alt.Bin(maxbins=40), title="Range",
                                               format="$,.0f" if money else ".1%" if percent else ",.2f")])])
    rules = alt.Chart(part).mark_rule(strokeDash=[5, 3], strokeWidth=2).encode(
        x=f"median({value}):Q", color=alt.Color("Portfolio:N", scale=scale_for(series), legend=None),
        tooltip=["Portfolio:N", alt.Tooltip(f"median({field}):Q", title="Median",
                                            format="$,.0f" if (money or log) else ".1%" if percent else ",.2f")])
    return zoomable(alt.layer(bars, rules).properties(height=410))


def inflation_note(plan):
    """Say once, plainly, that results are in today's dollars, how they are converted and what is not."""
    cpi = plan["assumptions"]["cpi_annual"]
    with st.expander("All amounts are in today's dollars: what that means"):
        st.markdown(f"""
**Every amount in sections 3 to 5 is in today's dollars**: what it would buy on {plan['plan']['start_date']}, the
plan's start, at the assumed {cpi:.1%} CPI. So \\$90,000 in 2045 and \\$90,000 today mean the same standard of living,
and you can compare any two years directly. (A nominal \\$1,000,000 in 20 years is about
\\${1e6 / (1 + cpi) ** 20:,.0f} in today's dollars.)

| Item | How it is shown |
| --- | --- |
| Wealth, balances, ending wealth (sections 4 and 5) | Today's dollars: each balance divided by the price level on its date, (1 + CPI) to the power of years since the start |
| Money in and out each year: salary, spending, tax, returns | Today's dollars: each financial year divided by (1 + CPI) to the power of whole years since the start, the same step on which spending rises each 1 July |
| "Inflation" in the money in and out charts | The buying power your wealth lost that year, so each year's bars still add up to the change in wealth |
| Section 3: growth of \\$100, annualised growth, calendar-year returns | After inflation. Volatility and drawdowns use the nominal daily returns; inflation hardly changes them |
| Withdrawal rates | Ratios, so unaffected |
| Section 2: historical returns | **Nominal**: the source data have no history of inflation |
| Spending inputs | Today's dollars; rise each 1 July with CPI{"" if not plan['spending']['real_change'] else " and your real change"} |
| Salary | {"Rises each 1 July by wage growth (" + format(plan['assumptions']['wage_growth_annual'], '.1%') + "), so in today's dollars it grows by about the gap between wage growth and CPI" if plan['employment'].get('salary_indexed', True) else "Not indexed, so it falls each year in today's dollars"} |

The tax ledger itself runs in nominal dollars, because tax brackets, caps and the CGT discount are set in nominal
dollars. Only the reporting is converted. The event log and the CSV downloads in section 5 are the ledger's
nominal records.
""")


def run_with_progress(valid):
    bar = st.progress(0.0, text="Loading ticker histories · 0%")

    def progress(fraction, message):
        bar.progress(min(max(fraction, 0.0), 1.0), text=f"{message} · {fraction:.0%}")

    try:
        market = cached_market(tuple(valid["assets"]))
        return run_plan(valid, market=market, progress=progress)
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


TICKER_COLOURS = ["#126a63", "#386a98", "#b76a42", "#9a8a2e", "#8363a0", "#c2577a", "#4f8f3a", "#5f6b73", "#d08c2f", "#2f8fb5"]


def allocation_pie(weights, tickers):
    """Donut of one portfolio's weights: percentages on the slices, a ticker legend beside it, fixed colours per ticker."""
    import altair as alt

    colour = {t: TICKER_COLOURS[i % len(TICKER_COLOURS)] for i, t in enumerate(tickers)}
    labels = weights["Label"].tolist()
    scale = alt.Scale(domain=labels, range=[colour[t] for t in weights["Ticker"]])
    base = alt.Chart(weights).encode(theta=alt.Theta("Weight:Q", stack=True), order=alt.Order("Weight:Q", sort="descending"))
    slices = base.mark_arc(innerRadius=45, outerRadius=95, stroke="#ffffff", strokeWidth=2).encode(
        color=alt.Color("Label:N", scale=scale, sort=labels, legend=None),
        tooltip=["Ticker:N", alt.Tooltip("Weight:Q", format=".1%"),
                 *([alt.Tooltip("Amount:Q", title="Value today", format="$,.0f")] if "Amount" in weights else [])])
    text = base.mark_text(radius=70, fontSize=12, fontWeight="bold", color="#ffffff").encode(
        text=alt.Text("Weight:Q", format=".0%"))
    return (slices + text).properties(height=220)


def allocation_legend(weights, tickers):
    """The donut's key as coloured text, so legends of different lengths do not shift the charts."""
    colour = {t: TICKER_COLOURS[i % len(TICKER_COLOURS)] for i, t in enumerate(tickers)}
    return " &nbsp; ".join(f"<span style='color:{colour[t]}'>&#9632;</span> {t} {w:.0%}"
                           for t, w in zip(weights["Ticker"], weights["Weight"]))


def section_portfolios(run):
    import altair as alt

    st.header("1 · Your portfolios")
    plan = run.plan
    tickers = list(plan["assets"])
    cols = st.columns(2)
    for column, (title, section) in zip(cols, (("Outside super", "outside"), ("Inside super", "super"))):
        with column:
            balance = plan["outside"]["investment_balance"] if section == "outside" else plan["super"]["balance"]
            st.markdown(f"**{title}** · {compact(balance)}")
            st.caption("Rebalanced every January" if plan[section]["rebalance"] == "annual" else "Buy and hold")
            weights = pd.DataFrame([{"Ticker": t, "Weight": w, "Label": f"{t} {w:.0%}", "Amount": w * balance}
                                    for t, w in plan[section]["weights"].items()])
            st.altair_chart(allocation_pie(weights, tickers), width="stretch")
            st.markdown(allocation_legend(weights, tickers), unsafe_allow_html=True)
            stats = run.portfolios.summary.set_index("Portfolio").loc[title]
            st.markdown(f"Historical CAGR (nominal) **{share(stats['CAGR'])}** · volatility **{share(stats['Volatility'])}** · "
                        f"max drawdown **{share(stats['Maximum drawdown'])}**",
                        help=f"Whole portfolio, {stats['First']} to {stats['Last']}, measured daily. Max drawdown is the "
                             "deepest fall from a previous peak.")
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
    st.caption("Historical returns are **nominal**: the source data have no inflation history. Everything from section 3 "
               "on is in today's dollars.")
    history = run.portfolios.historical
    names = list(dict.fromkeys(history["Portfolio"]))
    growth = zoomable(alt.Chart(history).mark_line(strokeWidth=2).encode(
        x=alt.X("Date:T", title=None, axis=year_axis(history)),
        y=alt.Y("Growth of 100:Q", scale=alt.Scale(type="log"), title="Growth of $100 · log scale", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Portfolio:N", scale=scale_for(names), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Portfolio:N", alt.Tooltip("Growth of 100:Q", format="$,.0f")]
    ).properties(height=550))
    st.altair_chart(growth, width="stretch")
    st.caption("$100 invested at the start of the shared history, valued at each month end. On a log scale equal "
               "vertical distances are equal percentage changes, so a straight line means steady compound growth "
               "and early decades stay visible. Reconstructed pre-fund history is a model, not observed fund performance.")
    drawdown = zoomable(alt.Chart(history).mark_line(strokeWidth=1.3).encode(
        x=alt.X("Date:T", title=None, axis=year_axis(history)),
        y=alt.Y("Drawdown:Q", title="Below previous peak", axis=alt.Axis(format=".0%")),
        color=alt.Color("Portfolio:N", scale=scale_for(names), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Portfolio:N", alt.Tooltip("Drawdown:Q", format=".1%")]
    ).properties(height=380))
    st.altair_chart(drawdown, width="stretch")
    st.caption("How far each portfolio sat below its previous high at each month end (0% = at a new high). Deep and "
               "long dips are what a retiree has to live through while still withdrawing.")
    yearly = run.portfolios.historical_annual
    if not yearly.empty:
        bars = alt.Chart(yearly).mark_bar().encode(
            x=alt.X("Year:O", title=None, axis=alt.Axis(labelAngle=-90, values=[y for y in yearly["Year"].unique() if y % 5 == 0])),
            xOffset="Portfolio:N", y=alt.Y("Return:Q", title="Calendar-year return", axis=alt.Axis(format=".0%")),
            color=alt.Color("Portfolio:N", scale=scale_for(names), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["Year:O", "Portfolio:N", alt.Tooltip("Return:Q", format=".1%")]).properties(height=430)
        st.altair_chart(bars, width="stretch")
        st.caption("Return in each full calendar year. The spread between good and bad years is the sequence risk a "
                   "retirement plan has to absorb.")


def withdrawal_rates_section(plan, portfolios, names):
    """Two retirement withdrawal rates per portfolio path, with an explanation of what each answers."""
    outcomes = portfolios.outcomes
    st.subheader("How much could each portfolio pay out each year?")
    end = portfolios.planning_end
    if end is None:
        st.info("Retirement starts too close to the planning age for withdrawal rates; raise the planning age on the "
                "Assumptions tab.")
        return
    years = (end - portfolios.retirement_start).days / 365.25
    age = plan["assumptions"]["planning_age"]
    growth, cpi = spending_growth(plan), plan["assumptions"]["cpi_annual"]
    rows = []
    for title in names:
        part = outcomes.loc[outcomes["Portfolio"] == title]
        rows.append({"Portfolio": title,
                     f"Lasts to age {age}: cautious (5th pct)": share(part["Sustainable withdrawal rate"].quantile(0.05)),
                     f"Lasts to age {age}: median": share(part["Sustainable withdrawal rate"].median()),
                     "Lasts indefinitely: cautious (5th pct)": share(part["Perpetual withdrawal rate"].quantile(0.05)),
                     "Lasts indefinitely: median": share(part["Perpetual withdrawal rate"].median())})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    a, b = st.columns(2)
    with a:
        st.altair_chart(overlay_histogram(outcomes, "Sustainable withdrawal rate", f"Rate that lasts to age {age}", series=tuple(names)),
                        width="stretch")
    with b:
        st.altair_chart(overlay_histogram(outcomes, "Perpetual withdrawal rate", "Rate that lasts indefinitely", series=tuple(names)),
                        width="stretch")
    with st.expander("What these withdrawal rates mean", expanded=True):
        st.markdown(f"""
A **withdrawal rate** is the first year's withdrawal as a percentage of the portfolio on the day you retire. Each
later year withdraws the same amount in today's dollars (it rises with inflation{"" if not plan['spending']['real_change'] else f", plus your {plan['spending']['real_change']:+.1%} real change"}), so it
keeps its buying power. Example: a 4% rate on \\$1,000,000 is \\$40,000 a year in today's dollars. Withdrawals are
taken monthly.

The planner tests every simulated market path from your retirement date ({portfolios.retirement_start}) for
{years:.0f} years, to age {age}. These paths are separate from the tax-ledger paths: they are pre-tax and have no
Age Pension, so they test the portfolio alone. For each path it solves two questions exactly:

1. **Lasts to age {age}.** The highest rate at which the portfolio is spent down to exactly \\$0 on the last day.
   Nothing is left over, so this is the most aggressive way to read the result.
2. **Lasts indefinitely.** The highest rate that still leaves the portfolio worth at least what it started with in
   real terms (grown by {cpi:.1%} CPI) after {years:.0f} years. A portfolio in that state could keep paying the same
   real income forever, provided future returns were similar. This is the usual meaning of a "safe" or
   "perpetual" withdrawal rate for money held outside super, and it is always lower than the first rate.

**Reading the numbers.** The *median* is what half the market paths could do. The *cautious* figure is the
5th percentile, which 95% of paths could sustain. The cautious perpetual rate is the closest equivalent to the
"4% rule", which was derived for 30-year US stock and bond retirements.

**What is not included.**
- Tax. Outside super, distributions and capital gains are taxed. Pension-phase super earnings are tax free, but
  the transfer balance cap limits how much can move into the pension.
- The Age Pension, fees beyond those already in the return series, and any change in spending as you age.
- Super access rules. A rate for inside super assumes you could draw on it from retirement.

**Why it can look high.** These portfolios use reconstructed leveraged histories since 1970, which compounded
strongly. Resampling cannot produce a worse sequence than the worst stretch in that history, and a rate is only
as reliable as the assumption that the future resembles that history.
""")


# Widgets inside a fragment rerun only that fragment, so choosing an option does not redraw the whole results page
# (which jumped the browser back to the top while the page above re-rendered).
@st.fragment
def portfolio_detail(run, names):
    """The selected portfolio's fan, drawdowns and calendar-year returns."""
    import altair as alt

    plan, portfolios = run.plan, run.portfolios
    marks = milestones(plan, portfolios.dates[0], portfolios.dates[-1])
    selected = st.radio("Portfolio", names, horizontal=True, key=key("portfolio_result"))
    fan = portfolios.paths.loc[portfolios.paths["Portfolio"] == selected]
    st.altair_chart(band_chart(fan, "Growth of $100 in today's dollars · log scale", log=True, color=PALETTE[selected],
                               marks=marks),
                    width="stretch")
    st.caption("Dark band: middle half of paths (25th–75th percentile). Light band: 90% of paths (5th–95th). Line: "
               "median at each month. Dashed lines mark retirement, super access and the pension start. Hover for values; "
               "drag to pan, Shift+scroll to zoom, double-click to reset.")
    dd = fan.rename(columns={"Drawdown P05": "Bad (5th pct)", "Drawdown P50": "Typical (median)"})
    dd = dd.melt("Date", value_vars=["Bad (5th pct)", "Typical (median)"], var_name="Path", value_name="Drawdown")
    st.altair_chart(zoomable(alt.Chart(dd).mark_line().encode(
        x=alt.X("Date:T", title=None, axis=year_axis(dd)), y=alt.Y("Drawdown:Q", title="Below previous peak", axis=alt.Axis(format=".0%")),
        strokeDash=alt.StrokeDash("Path:N", legend=alt.Legend(orient="bottom", title=None)), color=alt.value(PALETTE[selected]),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Path:N", alt.Tooltip("Drawdown:Q", format=".1%")]
    ).properties(height=360)), width="stretch")
    st.caption(f"{selected}: how far below its running peak the portfolio sits at each month end, for the median "
               "path and for the worst 5% of paths at that date.")
    if not portfolios.annual_returns.empty:
        annual = portfolios.annual_returns.loc[portfolios.annual_returns["Portfolio"] == selected]
        st.altair_chart(band_chart(quantile_bands(annual, "Year", "Return"), "Calendar-year return after inflation", percent=True,
                                   color=PALETTE[selected], x="Year:Q"), width="stretch")
        st.caption(f"{selected}: spread of each full calendar year's return across paths. Partial first and last years "
                   "are left out.")


def section_future(run):
    import altair as alt

    plan, portfolios, market = run.plan, run.portfolios, run.market
    st.header("3 · Future portfolio simulations")
    st.info("This section shows **investment returns only**: $100 put in each portfolio at the start and left alone. "
            "There are no yearly additions, salary contributions, withdrawals or tax here, so you can compare how the "
            "portfolios themselves behave. Your contributions, spending, tax and super rules are applied to these same "
            "market paths in sections 4 and 5. Values are **in today's dollars**: each is deflated by the "
            f"{plan['assumptions']['cpi_annual']:.1%} CPI assumption, so growth shown is growth after inflation.")
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
5. **Statistics per path.** Ending value of \\$100 and annualised growth over the calendar horizon, both after
   inflation (deflated at the CPI assumption); volatility
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
    portfolio_detail(run, names)
    medians = portfolios.paths[["Date", "Portfolio", "P50"]]
    st.altair_chart(zoomable(alt.Chart(medians).mark_line(strokeWidth=2).encode(
        x=alt.X("Date:T", title=None, axis=year_axis(medians)),
        y=alt.Y("P50:Q", title="Median growth of $100, today's dollars", scale=alt.Scale(type="log", nice=False,
                domain=[float(medians["P50"].min()) * 0.95, float(medians["P50"].max()) * 1.05]), axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Portfolio:N", scale=scale_for(names), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Portfolio:N", alt.Tooltip("P50:Q", format="$,.0f")]
    ).properties(height=380)), width="stretch")
    st.caption("Median paths side by side, to compare the portfolios' central outcomes on the same draws.")

    st.subheader("Distributions across paths")
    outcomes = portfolios.outcomes
    a, b = st.columns(2)
    with a:
        st.altair_chart(overlay_histogram(outcomes, "Terminal growth of 100", "Ending value of $100, today's dollars (log scale)", log=True,
                                        series=tuple(names)),
                        width="stretch")
        st.caption("Where $100 ends up at the horizon, in today's dollars. Dashed lines are medians.")
        st.altair_chart(overlay_histogram(outcomes, "Annualised volatility", "Annualised volatility", series=tuple(names)), width="stretch")
        st.caption("Day-to-day variability of each path, annualised. Higher volatility means wider swings in wealth.")
    with b:
        st.altair_chart(overlay_histogram(outcomes, "Annualised growth", "Annualised growth after inflation", series=tuple(names)), width="stretch")
        st.caption("Compound growth per year over the whole horizon on each path, after inflation.")
        st.altair_chart(overlay_histogram(outcomes, "Maximum drawdown", "Maximum drawdown", series=tuple(names)), width="stretch")
        st.caption("Deepest peak-to-trough fall on each path. −50% means the portfolio halved at some point.")
    withdrawal_rates_section(plan, portfolios, names)
    table = []
    for title in names:
        part = outcomes.loc[outcomes["Portfolio"] == title]
        t = percentile_table(part, {"Ending value of $100 (today's dollars)": ("Terminal growth of 100", "money"),
                                    "Annualised growth after inflation": ("Annualised growth", "percent"),
                                    "Annualised volatility": ("Annualised volatility", "percent"),
                                    "Maximum drawdown": ("Maximum drawdown", "percent"),
                                    "Longest drawdown (years)": ("Longest drawdown (years)", "number"),
                                    "Withdrawal rate lasting to the planning age": ("Sustainable withdrawal rate", "percent"),
                                    "Withdrawal rate lasting indefinitely": ("Perpetual withdrawal rate", "percent")})
        t.insert(0, "Portfolio", title)
        table.append(t)
    table = pd.concat(table)
    st.dataframe(table, width="stretch", hide_index=True, height=fit(table))
    st.caption("Read across a row: 5% of paths fall below the 5th-percentile value, half below the median. For "
               "drawdowns the 5th percentile is the severe end.")


FLOW_COLOURS = {"Take-home salary": "#126a63", "Super contributions": "#386a98", "Investment returns": "#9a8a2e",
                "Interest on cash": "#4f8f3a", "Age Pension": "#d08c2f",
                "Spending": "#b76a42", "Income tax": "#8c2f2f", "Contributions tax": "#c2577a", "Super fund tax": "#8363a0", "Division 296 tax": "#5b3f7a",
                "Inflation": "#9aa3a8"}


def additions_layer(frame, x, value="AUD"):
    """Money moved from pay into outside investments: shown as a dashed line because it does not change total wealth."""
    import altair as alt

    frame = frame.loc[frame[value].abs() > 1e-6]
    if frame.empty:
        return None
    return alt.Chart(frame).mark_line(color="#0b7a8a", strokeDash=[6, 3], strokeWidth=2.5,
                                      point=alt.OverlayMarkDef(shape="square", size=60, color="#0b7a8a", filled=True)).encode(
        x=x, y=f"{value}:Q",
        tooltip=[alt.Tooltip("Period:N", title="Year"),
                 alt.Tooltip(f"{value}:Q", title="Added to outside investments (from pay)", format="$,.0f")])


def flow_domain(frame, field, extra=()):
    """A y domain that fits diverging stacked bars (positives and negatives stack separately) and any lines."""
    by_year = frame.groupby("FY ending")[field]
    top = max([float(by_year.apply(lambda v: v[v > 0].sum()).max()), *[float(np.nanmax(e)) for e in extra], 0.0])
    low = min([float(by_year.apply(lambda v: v[v < 0].sum()).min()), *[float(np.nanmin(e)) for e in extra], 0.0])
    pad = 0.08 * (top - low or 1.0)
    return [low - pad, top + pad]


def typical_flows_section(annual, marks, calculated, start_wealth):
    """Median money in and out each year across every calculated path, with the net change's middle half."""
    import altair as alt

    columns = [c for c in annual.columns if c.startswith("Flow: ")]
    if not columns:
        return
    paths = len(calculated)
    st.subheader("Money in and out in a typical year, across all paths")

    def median(column):
        return float(calculated[column].median()) if column in calculated and calculated[column].notna().any() else np.nan

    # The same figures as section 5's single path, as medians across paths (each median is taken on its own).
    w = st.columns(4)
    w[0].metric("Wealth at start", compact(start_wealth), help="The same on every path: your wealth today.")
    w[1].metric("Median wealth at retirement", compact(median("Wealth at retirement")),
                help="Total wealth on your retirement date, today's dollars.")
    w[2].metric("Median wealth when super becomes accessible", compact(median("Wealth when super accessible")),
                help="Total wealth on the first day super can be withdrawn (preservation age and retirement), when that "
                     "is after the start.")
    w[3].metric("Median ending wealth", compact(median("Ending wealth")))
    a, b, c, d = st.columns(4)
    a.metric("Median Age Pension received", compact(median("Age Pension received")))
    b.metric("Median spending shortfall", compact(median("Spending shortfall")))
    c.metric("Median tax (personal, fund, Division 296)",
             compact(float((calculated["Personal tax assessed"] + calculated["Fund tax"]
                            + calculated["Division 296 tax"]).median())),
             help="Each path's total tax over the horizon, in today's dollars; the median across paths.")
    d.metric("Median largest fall in wealth", share(median("Largest fall in wealth")),
             help="Each path's deepest fall of total wealth below its previous high; the median across paths. Unlike a "
                  "portfolio drawdown it includes spending, so it keeps falling in retirement even in flat markets.")
    long = annual.melt(["Path", "FY ending"], value_vars=columns, var_name="Flow", value_name="AUD")
    long["Flow"] = long["Flow"].str.replace("Flow: ", "", regex=False)
    stats = long.groupby(["FY ending", "Flow"])["AUD"].quantile([0.25, 0.5, 0.75]).unstack().reset_index()
    stats.columns = ["FY ending", "Flow", "P25", "Median", "P75"]
    stats = stats.groupby("Flow").filter(lambda g: g[["P25", "Median", "P75"]].abs().max().max() > 1e-6)
    stats["Period"] = stats["FY ending"].map(period_label)
    net = annual.groupby("FY ending")["Net change in wealth"].quantile([0.25, 0.5, 0.75]).unstack().reset_index()
    net.columns = ["FY ending", "P25", "Median", "P75"]
    net["Period"] = net["FY ending"].map(period_label)
    wealth = [c for c in ("Wealth at start of year", "Wealth at end of year") if c in annual]
    if wealth:
        net = net.merge(annual.groupby("FY ending")[wealth].median().reset_index(), on="FY ending")
    order = [f for f in FLOW_COLOURS if f in set(stats["Flow"])]
    domain = [int(annual["FY ending"].min()) - 0.6, int(annual["FY ending"].max()) + 0.6]
    x = alt.X("FY ending:Q", axis=fy_axis(annual), scale=alt.Scale(domain=domain, nice=False))
    additions = annual.groupby("FY ending")["Added to outside investments"].median().reset_index(name="AUD")         if "Added to outside investments" in annual else pd.DataFrame(columns=["FY ending", "AUD"])
    additions["Period"] = additions["FY ending"].map(period_label)
    y_domain = flow_domain(stats, "Median", (net["P25"], net["P75"], additions["AUD"] if len(additions) else [0.0]))
    bars = alt.Chart(stats).mark_bar(size=16).encode(
        x=x, y=alt.Y("Median:Q", stack=True, title="Median per year, today's dollars", axis=alt.Axis(format="$,.0f"),
                     scale=alt.Scale(domain=y_domain, nice=False)),
        color=alt.Color("Flow:N", sort=order, scale=alt.Scale(domain=order, range=[FLOW_COLOURS[f] for f in order]),
                        legend=alt.Legend(orient="bottom", title=None, columns=2, labelLimit=220)),
        tooltip=[alt.Tooltip("Period:N", title="Year"), "Flow:N", alt.Tooltip("Median:Q", format="$,.0f"),
                 alt.Tooltip("P25:Q", title="25th percentile", format="$,.0f"),
                 alt.Tooltip("P75:Q", title="75th percentile", format="$,.0f")])
    spread = alt.Chart(net).mark_errorbar(color="#19353a", thickness=1.5, ticks=True).encode(
        x=x, y=alt.Y("P25:Q", title=""), y2="P75:Q")
    line = alt.Chart(net).mark_line(color="#19353a", strokeWidth=2, point=alt.OverlayMarkDef(color="#19353a", size=40)).encode(
        x=x, y="Median:Q", tooltip=[alt.Tooltip("Period:N", title="Year"),
                                    *[alt.Tooltip(f"{c}:Q", title="Median wealth at start", format="$,.0f")
                                      for c in wealth if c.endswith("start of year")],
                                    alt.Tooltip("Median:Q", title="Median net change in wealth", format="$,.0f"),
                                    alt.Tooltip("P25:Q", title="25th percentile", format="$,.0f"),
                                    alt.Tooltip("P75:Q", title="75th percentile", format="$,.0f"),
                                    *[alt.Tooltip(f"{c}:Q", title="Median wealth at end", format="$,.0f")
                                      for c in wealth if c.endswith("end of year")]])
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#5f6b73").encode(y="y:Q")
    added = additions_layer(additions, x)
    layers = [bars, zero, spread, line] + ([added] if added is not None else [])
    st.altair_chart(with_milestones(alt.layer(*layers).properties(height=670), marks, "Position:Q"), width="stretch")
    st.caption(f"Each bar is the **median across all {paths} calculated paths** of that flow in that year: take-home "
               "salary, super contributions and investment returns above zero; spending, income tax, contributions tax "
               "and super fund tax below. **Inflation** (grey) is the buying power your wealth lost that year: in "
               "today's dollars, wealth that only kept pace with prices shows no gain. The black line is the median net "
               "change in total wealth, with whiskers "
               "showing the middle half of paths (25th to 75th percentile); hover it for the median wealth at the start "
               "and end of each year. Hover a bar for its 25th and 75th percentiles. The figures above the chart are "
               "medians across paths of section 5's single-path figures; each is a separate median, so they need not "
               "come from the same path. The dashed teal line with squares is the median amount **added to outside investments** from your "
               "pay each year, and after retirement from unspent pension payments and other spare cash; it moves money "
               "from cash into the portfolio, so it is not a bar and does not change total wealth. Medians do not add up, so the bars do not sum exactly to the median net change; "
               "investment returns vary most between paths. Section 5 shows one path whose bars add up exactly.")


def ruin_statistics(run, calculated, marks):
    """Risk of ruin and related measures for the tax-ledger paths, plus a to-95 estimate from the portfolio draws."""
    plan = run.plan
    end = run.result.daily.index[-1].date()
    total = len(calculated)
    depleted = calculated.loc[calculated["Status"] == "depleted"]
    born = date.fromisoformat(plan["person"]["date_of_birth"])
    access = marks.loc[marks["Event"].str.contains("Super accessible"), "Date"]
    first = pd.to_datetime(depleted["First shortfall"].replace("", None)).dropna()
    early = (first < access.iloc[0]).sum() if len(access) else 0
    ages = [age_on(born, d.date()) for d in first]
    outside_gone = (calculated["Outside money runs out"] != "").mean()
    a, b = st.columns(2)
    c, d = st.columns(2)
    a.metric(f"Risk of ruin to {end.year}", share(len(depleted) / total),
             help=f"Share of the {total} tax-ledger paths where some spending could not be paid, or tax could not be "
                  f"paid, before the horizon ({end}).")
    b.metric("Ran short before super was accessible", share(early / total),
             help="Paths whose first shortfall came before super could be withdrawn: outside money alone was not "
                  "enough to bridge to the access date.")
    c.metric("Median age money first ran short", f"{int(np.median(ages))}" if ages else "–",
             help="Among paths that ran short, the median age at the first unpaid spending.")
    d.metric("Outside money ever ran out", share(outside_gone),
             help="Share of paths where cash and outside investments reached zero at some point (super may still "
                  "have been available).")
    combined = run.portfolios.outcomes.loc[run.portfolios.outcomes["Portfolio"] == "Combined", "Sustainable withdrawal rate"]
    rate = calculated["First retired-year withdrawal rate"].median()
    age = plan["assumptions"]["planning_age"]
    if age_on(born, end) >= age - 1:
        st.caption(f"The tax ledger runs to {end} (age {age_on(born, end)}), so the risk of ruin above covers your "
                   f"retirement to your planning age of {age}, with tax and the Age Pension.")
    elif combined.notna().any() and np.isfinite(rate):
        estimate = float((combined < rate).mean())
        st.caption(f"**Estimated chance of running out by age {age}: {estimate:.0%}.** Your median first retired-year "
                   f"withdrawal is {rate:.1%} of wealth; in {estimate:.0%} of the combined portfolio's market paths from "
                   f"retirement to {age}, that rate (rising with inflation) would run the portfolio to zero. This is "
                   "a pre-tax, portfolio-only estimate that ignores the Age Pension and assumes fixed spending; the figures "
                   f"above come from the full tax ledger but stop at {end}. Set *Years to simulate* to reach age {age} to "
                   "replace this estimate with the ledger's own result."
                   + (" Your spending rule cuts spending when markets fall, so this estimate overstates your risk."
                      if plan["spending"]["rule"] != "fixed" else ""))


def ending_statistics(run, calculated):
    """Ending-wealth risk measures: how often wealth ended lower than it started, in today's dollars."""
    start = float(run.result.daily["total"].iloc[0])
    real = calculated["Ending wealth"]
    a, b = st.columns(2)
    c, d = st.columns(2)
    a.metric("Ended with less than you started", share(float((real < start).mean())),
             help=f"Share of paths whose ending wealth, in today's dollars, was below the starting {compact(start)}.")
    b.metric("Ended below half of the start", share(float((real < 0.5 * start).mean())))
    c.metric("Median ending wealth", compact(float(real.median())))
    rates = calculated["Median withdrawal rate"].dropna()
    if not rates.empty:
        w = st.columns(4)
        for column, (label, q, why) in zip(w, (("Withdrawal rate: median path", 0.5, "half of paths drew more"),
                                                ("Withdrawal rate: 90th percentile", 0.9, "one path in ten drew more"),
                                                ("Withdrawal rate: 95th percentile", 0.95, "one path in twenty drew more"),
                                                ("Withdrawal rate: 5th percentile", 0.05, "the gentlest paths"))):
            column.metric(label, share(float(rates.quantile(q))),
                          help="Each path's median withdrawal rate over its full retired years (spending plus tax, less "
                               f"Age Pension, over wealth on 1 July), ranked across paths: {why}. High rates are the bad "
                               "paths: wealth shrank, so the same spending took a bigger share.")
    d.metric("Bad case: 5th percentile", compact(float(real.quantile(0.05))),
             help="One path in twenty ended lower than this.")


def spending_section(plan, annual, calculated, marks):
    """How much was spent in retirement and how much it varied: the trade-off a spending rule makes against ruin."""
    spending = plan["spending"]
    dollars = lambda value: compact(value).replace("$", "\\$")  # two $ in one Markdown string would render as maths
    st.subheader("Spending in retirement")
    starts = calculated["Starting retirement spending"].dropna()
    if starts.empty:
        st.info("Retirement starts after the horizon, so there is no retirement spending to show.")
        return
    rule = RULE_LABELS[spending["rule"]]
    rates = calculated["Starting withdrawal rate"].dropna()
    lowest = calculated["Lowest retired-year spending"].dropna()
    cuts = calculated["Deepest cut below start"].dropna()
    a, b, c, d = st.columns(4)
    if spending["retirement"] == "percent":
        a.metric("Starting spending (median)", dollars(float(starts.median())),
                 help=f"{spending['retirement_percent']:.1%} of each path's total wealth on your retirement date, in today's "
                      f"dollars. 5th to 95th percentile: {dollars(float(starts.quantile(0.05)))} to "
                      f"{dollars(float(starts.quantile(0.95)))}.")
        b.metric("Starting spending, bad case", dollars(float(starts.quantile(0.05))),
                 help="The 5th percentile across paths: one path in twenty started retirement spending less than this, "
                      "because markets did badly before you retired. The full range is in the note below.")
    else:
        a.metric("Starting spending", dollars(float(starts.median())),
                 help="Your first retired-year spending in today's dollars (the same on every path).")
        b.metric("As % of wealth at retirement (median)", share(float(rates.median())),
                 help=f"Starting spending over each path's total wealth on your retirement date. 5th to 95th percentile: "
                      f"{share(float(rates.quantile(0.05)))} to {share(float(rates.quantile(0.95)))}; the high end is "
                      "paths where markets did badly before you retired.")
    has_years = not lowest.empty
    c.metric("Paths that ever spent less than the start", share(float((calculated["Years below start"] > 0).mean())),
             help="Share of paths with at least one full retired year in which spending paid was more than 1% below "
                  "the starting amount: a cut by the rule, or money running short.")
    d.metric("Bad case: lowest year's spending", dollars(float(lowest.quantile(0.05))) if has_years else "–",
             help="The 5th percentile, across paths, of each path's lowest full retired year of spending paid "
                  "(today's dollars). One path in twenty had a year at or below this.")
    if spending["retirement"] != "percent":
        st.caption(f"Your starting spending is **{share(float(rates.median()))} of wealth at retirement** on the median "
                   f"path, and between {share(float(rates.quantile(0.05)))} and {share(float(rates.quantile(0.95)))} on "
                   "90% of paths. Section 3's withdrawal rates show what rates portfolios like yours have sustained.")
    else:
        st.caption(f"A {spending['retirement_percent']:.1%} start produced **{dollars(float(starts.median()))} a year** "
                   f"on the median path, and between {dollars(float(starts.quantile(0.05)))} and "
                   f"{dollars(float(starts.quantile(0.95)))} on 90% of paths, all in today's dollars.")
    if has_years:
        st.caption(f"Deepest cut below the starting amount: median {share(float(cuts.median()))}, and "
                   f"{share(float(cuts.quantile(0.05)))} or worse on one path in twenty.")
    rows = annual.loc[annual["Full retired year"] & (annual["Spending paid"] > 0)]
    if not rows.empty:
        st.altair_chart(band_chart(quantile_bands(rows, "FY ending", "Spending paid"), "Spending paid per year, today's dollars",
                                   color="#b76a42", x="FY ending:Q", marks=marks), width="stretch")
    st.caption(f"Spending actually paid in each full retired year across paths, in today's dollars. Rule: **{rule}**. "
               "With fixed spending the band is flat until money runs short, and then it drops. With a rule the band "
               "widens as spending follows each path's markets: the rule trades a lower risk of running out for "
               "spending that varies. Judge a rule on both: the risk of ruin above, and how low spending goes here.")


def age_pension_section(plan, annual, calculated, marks):
    """How much Age Pension the paths received, and when it started: the safety net under late retirement."""
    st.subheader("Age Pension")
    born = date.fromisoformat(plan["person"]["date_of_birth"])
    eligible_from = birthday(born.isoformat(), load_ruleset("2026-27")["age_pension_age"])
    end_year = int(annual["FY ending"].max()) if not annual.empty else 0
    if not len(annual) or eligible_from > date(end_year, 6, 30):
        st.info(f"You reach Age Pension age on {eligible_from}, after the horizon. Set *Years to simulate* on the "
                "Assumptions tab to run past it.")
        return
    dollars = lambda value: compact(value).replace("$", "\\$")  # two $ in one Markdown string would render as maths
    received = calculated["Age Pension received"] > 0
    first = pd.to_datetime(calculated.loc[received, "Age Pension first paid"])
    ages = [age_on(born, d.date()) for d in first]
    years = annual.loc[annual["FY ending"] > eligible_from.year + (eligible_from.month >= 7)]
    paid_years = years.loc[years["Age Pension"] > 0, "Age Pension"]
    a, b, c, d = st.columns(4)
    a.metric("Paths that receive Age Pension", share(float(received.mean())),
             help="Share of paths paid at least one fortnight of Age Pension before the horizon.")
    b.metric("Median age it starts", f"{int(np.median(ages))}" if ages else "–",
             help="Among paths that receive it, the median age at the first payment. Later than 67 means the assets "
                  "or income test paid nothing until wealth fell.")
    c.metric("Typical year's Age Pension", dollars(float(paid_years.median())) if len(paid_years) else "–",
             help="Median Age Pension in the years it is paid, today's dollars. The full single rate is about "
                  f"{dollars(26 * 1237.70)} a year now.")
    d.metric("Total received (median path)", dollars(float(calculated["Age Pension received"].median())),
             help="Each path's Age Pension over the horizon, in today's dollars; the median across paths.")
    if len(years):
        st.altair_chart(band_chart(quantile_bands(years, "FY ending", "Age Pension"), "Age Pension per year, today's dollars",
                                   color="#d08c2f", x="FY ending:Q", marks=marks), width="stretch")
    st.caption("Age Pension paid each financial year from Age Pension age, across paths, in today's dollars (zero where the "
               "means test paid nothing). It rises as your own wealth falls: on paths where markets did badly it pays more, "
               "which cushions late retirement. Paths with large balances get none until their assets fall below the "
               "assets-test cut-off (about \\$746,000 for a homeowner today). Rules follow Services Australia's single "
               "rates, assets and income tests and deeming; see the methodology for what is approximated.")


@st.fragment
def wealth_bands(run, calculated, marks):
    """Wealth bands for the chosen account; a fragment so switching accounts redraws only this chart."""
    names = list(dict.fromkeys(run.account_bands["Series"]))
    choice = st.radio("Show", names, horizontal=True, key=key("wealth_series"))
    wide = st.toggle("Log scale", value=True, key=key("wealth_bands_log"))
    bands = run.account_bands.loc[run.account_bands["Series"] == choice]
    st.altair_chart(band_chart(bands, f"{choice}, today's dollars" + (" · log scale" if wide else ""), symlog=wide, marks=marks),
                    width="stretch")
    st.caption(f"Month-end {choice.lower()} across the {calculated} calculated paths, in today's dollars: dark band the "
               "middle half, light band 90% of paths, line the median. Dashed vertical lines mark retirement, when super "
               "becomes accessible and when the pension starts. "
               + ("The axis is logarithmic above \\$1,000 and linear below, so \\$0 can be shown and a very high "
                  "upper tail does not flatten the median; turn off Log scale for a linear axis. " if wide else "")
               + "Total wealth includes super that may not yet be accessible.")


def withdrawal_strategy(plan):
    """A plain statement of how retirement spending is set and paid, shown at the top of the retirement results."""
    spending, person = plan["spending"], plan["person"]
    born = date.fromisoformat(person["date_of_birth"])
    retire = birthday(born.isoformat(), person["retirement_age"])
    access = access_date(born.isoformat(), load_ruleset("2026-27"), retire)
    cpi = plan["assumptions"]["cpi_annual"]
    real = spending["real_change"]
    growth = f"rising with inflation at {cpi:.1%}" + (f" and {real:+.1%} a year in real terms" if real else "")
    start = {"same": f"the same level as now, **\\${spending['annual']:,.0f} a year**",
             "amount": f"**\\${spending['retirement_annual']:,.0f} a year**",
             "percent": f"**{spending['retirement_percent']:.1%} of your total wealth** on your retirement date"}[spending["retirement"]]
    rule = spending["rule"]
    if rule == "fixed":
        how = f"Then it keeps the same buying power, {growth} each 1 July, whatever markets do."
    elif rule == "guyton_klinger":
        how = (f"Then each 1 July the **Guyton–Klinger guardrails** apply: after a losing year the inflation rise is "
               f"skipped if your withdrawal rate is above its start; if the rate drifts more than "
               f"{spending['guardrail_band']:.0%} above its start spending is cut {spending['guardrail_step']:.0%}, and "
               f"more than {spending['guardrail_band']:.0%} below it spending is raised {spending['guardrail_step']:.0%}.")
    elif rule == "vanguard":
        how = (f"Then each 1 July the **Vanguard ceiling and floor** rule aims for the starting rate of your current "
               f"wealth, with each year's change limited to +{spending['ceiling']:.1%} and −{spending['floor']:.1%} "
               "after inflation.")
    else:
        how = "Then each 1 July spending is reset to the **same percentage of your total wealth**."
    bounds = []
    if rule != "fixed" and spending["minimum"]:
        bounds.append(f"never below \\${spending['minimum']:,.0f}")
    if rule != "fixed" and spending["maximum"]:
        bounds.append(f"never above \\${spending['maximum']:,.0f}")
    pension = int(plan["pension"]["start_age"])
    names = {"fixed": "fixed spending (the default)", "guyton_klinger": "Guyton–Klinger guardrails",
             "vanguard": "Vanguard ceiling and floor", "percent": "a percentage of wealth each year"}
    st.info(f"**Withdrawal strategy: {names[rule]}.** You retire on {retire:%d %B %Y} (age "
            f"{person['retirement_age']}). Retirement spending starts at {start}. {how}"
            + (f" Limits: {' and '.join(bounds)} a year (today's dollars, rising with inflation)." if bounds else "")
            + f"\n\n**Where it comes from:** cash first, then your outside investments (selling the holdings with the "
            f"smallest taxable gain first, with capital gains tax), then super from {access:%d %B %Y}"
            + (f", with your super moved into an account-based pension on "
               f"{max(birthday(born.isoformat(), pension), access):%d %B %Y} paying at least the legal minimum"
               if pension else "")
            + ". From 67 the means-tested Age Pension adds income when your assets and income are low enough. "
            "Change any of this on the Retirement tab.")


def section_retirement(run):
    import altair as alt

    plan, paths = run.plan, run.retirement_paths
    st.header("4 · Retirement outcomes")
    calculated = paths.loc[paths["Status"] != "unsupported"]
    withdrawal_strategy(plan)
    with st.expander("How these results were calculated (the broad strokes)", expanded=False):
        st.markdown(f"""
1. **Markets.** {plan['market']['paths']:,} possible futures are built by stitching together random stretches of
   real daily market history (section 3). The first **{len(paths)}** of them are used here. Each future applies the
   same market days to your outside-super and super portfolios.
2. **Your money, day by day.** For each future, a ledger follows every dollar from
   {run.result.daily.index[0].date()} to {run.result.daily.index[-1].date()}: pay comes in, spending goes out, what
   is left is invested, investments grow or fall with the market, and super receives your contributions.
3. **Retirement.** When your salary stops, spending follows the strategy above. It is paid from cash, then from
   outside investments, then from super once you can access it, and the account-based pension pays at least its
   legal minimum.
4. **Tax.** Australian tax is worked out each year as the law applies it: income tax and capital gains tax on
   your own investments, tax inside super, and the extra tax on super balances over 3 million dollars. Later years
   use thresholds projected with your inflation and wage assumptions.
5. **Government support.** From 67 the means-tested Age Pension is added when your assets and income are low
   enough, along with the seniors' tax offset.
6. **Results.** Everything is shown in today's dollars. A future **ran out** if any spending or tax could not be
   paid. The figures below summarise all the futures: medians, and the bad and good ends of the range.

These are resamples of the past, not forecasts. Section 5 shows a single future (or a group of them averaged) in
full, down to each payment. The project's methodology documents give every rule and its source.
""")
    funded = int((paths["Status"] == "funded").sum())
    depleted = int((paths["Status"] == "depleted").sum())
    unsupported = int((paths["Status"] == "unsupported").sum())
    a, b, c, d = st.columns(4)
    a.metric("Paths calculated", f"{len(calculated)} / {len(paths)}", help=f"{unsupported} unsupported")
    b.metric("Funded all spending", share(funded / len(calculated)) if len(calculated) else "–",
             help=f"{funded} funded, {depleted} depleted")
    c.metric("Median ending wealth", compact(calculated["Ending wealth"].median()),
             help=f"In today's dollars (deflated at the assumed {plan['assumptions']['cpi_annual']:.1%} CPI), at the horizon.")
    d.metric("Median wealth at retirement", compact(calculated["Wealth at retirement"].median()), help="Today's dollars.")
    a, b, c, d = st.columns(4)
    a.metric("Median first retired-year withdrawal", share(calculated["First retired-year withdrawal rate"].median()),
             help="Spending plus tax paid in the first full retired financial year, over wealth at its 1 July.")
    b.metric("Median highest withdrawal rate", share(calculated["Highest withdrawal rate"].median()),
             help="Each path's highest financial-year withdrawal rate while retired.")
    c.metric("Median total tax", compact(calculated["Personal tax assessed"].median() + calculated["Fund tax"].median()
                                         + calculated["Division 296 tax"].median()),
             help="Personal tax assessed, super fund tax and Division 296 tax over the horizon, each year in today's "
                  "dollars.")
    if (calculated["Division 296 tax"] > 0).any():
        d.metric("Paths paying Division 296", share(float((calculated["Division 296 tax"] > 0).mean())),
                 help="Share of paths whose total super balance passed the large balance threshold (3 million "
                      "dollars, CPI-indexed) in a year with super earnings. Earnings include the realised gains "
                      f"assumed on the Investments tab ({plan['super']['realised_gains']:.0%} a year).")
    if unsupported:
        reasons = paths.loc[paths["Status"] == "unsupported", "Reason"].value_counts()
        st.warning("Unsupported paths are excluded, so the shares above are conditional on the others: "
                   + "; ".join(f"{count} × {reason}" for reason, count in reasons.items()))
    marks = milestones(plan, run.result.daily.index[0].date(), run.result.daily.index[-1].date())
    st.subheader("Wealth over time")
    wealth_bands(run, len(calculated), marks)
    if getattr(run, "wealth_paths", None) is not None:
        st.subheader("Wealth over time across many paths")
        ruin_statistics(run, calculated, marks)
        log = st.toggle("Log scale", value=True, key=key("all_paths_log"))
        chart, grey, red, clipped = all_paths_chart(run.wealth_paths, marks, calculated, cache_key=id(run), log=log)
        total = run.wealth_paths["Path"].nunique()
        st.markdown(f"<span style='color:{GREY}'>&#9644;</span> {grey} of {total - red} paths that never ran out "
                    f"&nbsp; <span style='color:{RED}'>&#9644; &#10010;</span> all {red} paths that ran out, and where "
                    f"they first ran short &nbsp; <span style='color:{MEDIAN}'>&#9644;</span> median of all {total} paths",
                    unsafe_allow_html=True)
        st.altair_chart(chart, width="stretch")
        st.caption(("Every calculated path is drawn. " if grey + red == total else
                    f"{grey} of the {total - red} paths that never ran out are drawn, spread evenly from the lowest to "
                    "the highest ending wealth so they show the same spread as all of them; every path that ran out is "
                    "drawn. ")
                   + ((f"The {clipped} highest paths run" if clipped != 1 else "The highest path runs")
                      + " off the top: the axis stops there so the band where most paths "
                      "sit stays readable; the ending-wealth chart below shows them in full. "
                      if clipped else "")
                   + "Each grey line is one path's total wealth at each month end, in today's dollars. The lines are "
                   "translucent, so where many paths overlap the grey darkens: the darkest band is where most paths went. "
                   "Red lines are paths that ran out of money, and a red cross marks where each first could not pay "
                   "spending or tax. A cross can sit well above \\$0, because total wealth includes super that was not yet "
                   "accessible: those paths ran out of outside money while waiting for super. The teal "
                   "line is the median of all paths at each month. Point at a line to highlight that path and see its "
                   "value, your age, its ending wealth, shortfall and first retired-year withdrawal rate; the path "
                   "number can be opened in section 5.")
    st.subheader("Ending wealth on every path")
    ending_statistics(run, calculated)
    st.altair_chart(ending_wealth_chart(calculated), width="stretch")
    st.caption(f"Each dot is one path's total wealth on {run.result.daily.index[-1].date()}, sorted from lowest (left) to "
               "highest (right); the horizontal position is the share of paths that ended lower. Hover a dot for its "
               "exact ending wealth in today's dollars, the split between outside super and super, and any "
               "spending shortfall. Red dots are depleted paths. Dashed lines label the 10th percentile, median and 90th "
               "percentile.")
    annual = run.retirement_annual.copy()
    annual["Period"] = annual["FY ending"].map(period_label)
    typical_flows_section(annual, marks, calculated, float(run.result.daily["total"].iloc[0]))
    spending_section(plan, annual, calculated, marks)
    age_pension_section(plan, annual, calculated, marks)
    st.subheader("Withdrawal rate in each retired year")
    retired = annual.loc[annual["Full retired year"] & annual["Withdrawal rate"].notna()]
    if retired.empty:
        st.info("No full financial year after retirement falls inside the horizon, so there are no withdrawal rates.")
    else:
        rate_chart = band_chart(quantile_bands(retired, "FY ending", "Withdrawal rate"), "Withdrawal rate", percent=True,
                                color="#b76a42", x="FY ending:Q", marks=marks, height=600)
        combined = run.portfolios.outcomes.loc[run.portfolios.outcomes["Portfolio"] == "Combined"]
        age = plan["assumptions"]["planning_age"]
        if combined["Sustainable withdrawal rate"].notna().any():
            lasting = float(combined["Perpetual withdrawal rate"].quantile(0.05))
            to_age = float(combined["Sustainable withdrawal rate"].quantile(0.05))
            reference = pd.DataFrame([{"Rate": lasting, "Label": f"Cautious rate that lasts indefinitely {lasting:.1%}"},
                                      {"Rate": to_age, "Label": f"Cautious rate that lasts to age {age} {to_age:.1%}"}])
            rules = alt.Chart(reference).mark_rule(strokeWidth=2).encode(
                y="Rate:Q", strokeDash=alt.StrokeDash("Label:N", scale=alt.Scale(range=[[6, 3], [2, 2]]), legend=None),
                color=alt.Color("Label:N", scale=alt.Scale(range=["#8c2f2f", "#c2577a"]),
                                legend=alt.Legend(orient="bottom", title="Pre-tax reference lines", direction="vertical",
                                                  labelLimit=360, symbolType="stroke", symbolStrokeWidth=3)),
                tooltip=["Label:N", alt.Tooltip("Rate:Q", format=".1%")])
            rate_chart = alt.layer(rate_chart, rules)
        st.altair_chart(rate_chart, width="stretch")
        with st.expander("How to read the withdrawal rate", expanded=True):
            st.markdown(f"""
**What it is.** For each financial year (1 July to 30 June) that starts after you retire, the money taken out of your
wealth that year (spending paid plus personal tax paid, less any Age Pension received) divided by your **total** wealth on that 1 July, outside and
inside super together. A rate of 5% means that year used 5% of what you had at its start.

**What the bands show.** Each path has its own rate every year. The line is the median across paths; the dark band
the middle half; the light band 90% of paths. Upper paths are the ones where markets went badly, wealth shrank and
the same spending became a bigger share of it.

**How to use it.**
- A rate that stays roughly flat means wealth is keeping pace with spending; a rate that climbs year after year
  means wealth is shrinking relative to spending, which is the warning sign.
- Compare it with the red dotted lines, both from the combined portfolio in section 3 and both the 5th percentile
  (95% of market paths manage it): the rate that **lasts indefinitely** (keeps the portfolio's real value) and the
  rate that spends it down to zero at the planning age. Staying below the lower line is the cautious choice.
- Those lines are pre-tax, while this chart includes tax paid, so a rate here near a line leaves less margin than
  it appears.

**Limits.** Tax paid includes tax on investment income and capital gains; super that is not yet accessible counts in
total wealth; spending rises with inflation{"" if not plan['spending']['real_change'] else f" and {plan['spending']['real_change']:+.1%} a year in real terms"}.
""")
    stress = annual.groupby("FY ending").agg(**{"Paths with a shortfall": ("Shortfall", lambda x: (x > 0).mean())}).reset_index()
    stress["Period"] = stress["FY ending"].map(period_label)
    a, b = st.columns(2)
    with a:
        bars = alt.Chart(stress).mark_bar(color="#8c2f2f", size=14).encode(
            x=alt.X("FY ending:Q", axis=fy_axis(stress),
                    scale=alt.Scale(domain=[int(stress["FY ending"].min()) - 0.5, int(stress["FY ending"].max()) + 0.5], nice=False)),
            y=alt.Y("Paths with a shortfall:Q", axis=alt.Axis(format=".0%"),
                    scale=alt.Scale(domain=[0, max(0.1, float(stress["Paths with a shortfall"].max()) * 1.2)])),
            tooltip=[alt.Tooltip("Period:N", title="Year"), alt.Tooltip("Paths with a shortfall:Q", format=".1%")])
        st.altair_chart(with_milestones(bars.properties(height=430), marks, "Position:Q"), width="stretch")
        st.caption("Share of paths that could not pay all spending in each year. Shortfalls often cluster just before "
                   "super becomes accessible, when only outside money can pay.")
    with b:
        pensions = annual.loc[annual["Pension payments"] > 0]
        if pensions.empty:
            st.info("No account-based pension is paid in this plan (pension start age 0, or after the horizon).")
        else:
            st.altair_chart(band_chart(quantile_bands(pensions, "FY ending", "Pension payments"), "Pension payments per year",
                                       color="#8363a0", x="FY ending:Q", marks=marks), width="stretch")
            st.caption("Pension paid each year across paths: at least the age-based minimum, more when spending needs it "
                       "once outside money is used up.")
    st.subheader("Outcome ranges")
    ranges = percentile_table(calculated, {
        "Ending wealth": ("Ending wealth", "money"),
        "Ending outside wealth": ("Ending outside wealth", "money"), "Ending super and pension": ("Ending super and pension", "money"),
        "Wealth at retirement": ("Wealth at retirement", "money"), "Spending shortfall": ("Spending shortfall", "money"),
        "Personal tax assessed": ("Personal tax assessed", "money"), "Fund tax": ("Fund tax", "money"),
        "Division 296 tax": ("Division 296 tax", "money"), "Age Pension received": ("Age Pension received", "money"),
        "Pension payments": ("Pension payments", "money"), "Pension balance at start": ("Pension balance at start", "money"),
        "First retired-year withdrawal rate": ("First retired-year withdrawal rate", "percent"),
        "Highest withdrawal rate": ("Highest withdrawal rate", "percent"),
        "Largest fall in total wealth": ("Largest fall in wealth", "percent")})
    st.dataframe(ranges, width="stretch", hide_index=True, height=fit(ranges))
    st.caption("Percentiles across calculated paths, in today's dollars. Each column is a separate ranking, so a row's 5th percentile "
               "and another row's 5th percentile usually come from different paths.")
    with st.expander(f"Every path ({len(paths)})"):
        table = paths.drop(columns=["Ending wealth, nominal"], errors="ignore")
        ranks = ending_percentiles(calculated)
        table.insert(2, "Ending wealth percentile", table["Path"].map(ranks))
        table = table.sort_values("Ending wealth percentile", na_position="last")
        for field in ("First retired-year withdrawal rate", "Highest withdrawal rate", "Median withdrawal rate",
                      "Largest fall in wealth"):
            if field in table:
                table[field] *= 100
        money = ("Ending wealth", "Ending outside wealth", "Ending super and pension",
                 "Wealth at retirement", "Spending paid", "Spending shortfall", "Unpaid tax", "Personal tax assessed",
                 "Fund tax", "Division 296 tax", "Age Pension received", "Pension payments", "Pension balance at start")
        st.dataframe(table, width="stretch", hide_index=True, column_config={
            "Path": st.column_config.NumberColumn("Path", format="%d", pinned=True),
            "Status": st.column_config.TextColumn("Status", pinned=True),
            "Ending wealth percentile": st.column_config.NumberColumn(
                "Percentile", format="%.0f", pinned=True,
                help="Where this path's ending wealth ranks among calculated paths: 1 is near the worst, 99 near the best."),
            **{field: money_column(field) for field in money},
            **{field: percent_column(field) for field in ("First retired-year withdrawal rate", "Highest withdrawal rate",
                                                          "Median withdrawal rate", "Largest fall in wealth")}})
        st.caption("Amounts are in today's dollars, sorted from the worst ending wealth to the best. Path numbers are positions in the shared draw sequence (path 0 is the first draw), not ranks. "
                   "Scroll sideways for every column; hover a header for its full name.")


PATH_GROUPS = (("Worst 1%", 0.0, 0.01), ("Worst 5%", 0.0, 0.05), ("Worst 10%", 0.0, 0.10),
               ("Middle 10% (45th to 55th percentile)", 0.45, 0.55), ("Best 10%", 0.90, 1.0), ("Best 1%", 0.99, 1.0))


def ending_percentiles(calculated):
    """Each calculated path's ending-wealth percentile: (rank + 0.5) / count x 100, so ranks spread over 0 to 100."""
    ordered = calculated.sort_values("Ending wealth")["Path"].tolist()
    return {path: (i + 0.5) / len(ordered) * 100 for i, path in enumerate(ordered)}


def group_members(calculated, low, high):
    """Paths whose ending-wealth rank falls in [low, high) of the calculated paths; always at least one."""
    ordered = calculated.sort_values("Ending wealth")["Path"].tolist()
    n = len(ordered)
    first = min(int(np.floor(round(low * n, 9))), n - 1)
    last = max(first + 1, int(np.ceil(round(high * n, 9))))
    return [int(p) for p in ordered[first:last]]


def ordinal(value):
    n = int(round(value))
    n = min(max(n, 1), 99)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def averaged_paths(run, members, label):
    """A group of paths averaged month by month (balances) and year by year (flows), from the stored summaries."""
    import altair as alt

    plan, paths = run.plan, run.retirement_paths
    group = paths.loc[paths["Path"].isin(members)]
    st.subheader(f"{label} of paths ({len(members)} path{'s' if len(members) != 1 else ''})")
    if len(members) < 5:
        st.caption(f"Only {len(members)} path{'s' if len(members) != 1 else ''} in this group, so its average rests on very "
                   "few market sequences. Raise *Daily retirement-ledger paths* on the Assumptions tab (500 gives 5 paths "
                   "in the worst 1%) for a steadier picture.")
    a, b, c, d = st.columns(4)
    a.metric("Wealth at start", compact(float(run.result.daily["total"].iloc[0])))
    b.metric("Wealth at retirement (average)", compact(float(group["Wealth at retirement"].mean())))
    c.metric("Wealth when super becomes accessible (average)", compact(float(group["Wealth when super accessible"].mean()))
             if "Wealth when super accessible" in group and group["Wealth when super accessible"].notna().any() else "–")
    d.metric("Ending wealth (average)", compact(float(group["Ending wealth"].mean())))
    a, b, c, d = st.columns(4)
    a.metric("Paths in the group that ran out", share(float((group["Status"] == "depleted").mean())),
             help="Share of the group's paths with any unpaid spending or tax.")
    b.metric("Spending shortfall (average)", compact(float(group["Spending shortfall"].mean())))
    c.metric("Age Pension received (average)", compact(float(group["Age Pension received"].mean()))
             if "Age Pension received" in group else "–")
    d.metric("Withdrawal rate (average of path medians)", share(float(group["Median withdrawal rate"].mean())))
    series = run.path_series.loc[run.path_series["Path"].isin(members)] if run.path_series is not None else None
    marks = milestones(plan, run.result.daily.index[0].date(), run.result.daily.index[-1].date())
    if series is not None and not series.empty:
        mean = series.groupby("Date")[["Outside super", "Super and pension", "Pension account"]].mean()
        frame = pd.DataFrame({"cash": 0.0, "outside_investments": mean["Outside super"],
                              "accumulation": mean["Super and pension"] - mean["Pension account"],
                              "pension": mean["Pension account"]}, index=pd.DatetimeIndex(mean.index, name="Date"))
        st.altair_chart(with_milestones(balances_chart(frame), marks), width="stretch")
        st.caption("Average month-end balances of the group's paths by account, today's dollars (outside super combines "
                   "cash and investments). Averages smooth timing: paths that ran out did so in different years, so "
                   "the average falls gradually where each path fell sharply.")
    annual = run.retirement_annual.loc[run.retirement_annual["Path"].isin(members)]
    flows = [c for c in annual.columns if c.startswith("Flow: ")]
    if flows:
        yearly = annual.groupby("FY ending")[flows + ["Net change in wealth", "Added to outside investments"]].mean().reset_index()
        long = yearly.melt("FY ending", value_vars=flows, var_name="Flow", value_name="AUD")
        long["Flow"] = long["Flow"].str.replace("Flow: ", "", regex=False)
        long = long.groupby("Flow").filter(lambda g: g["AUD"].abs().max() > 1e-6)
        long["Period"] = long["FY ending"].map(period_label)
        yearly["Period"] = yearly["FY ending"].map(period_label)
        order = [f for f in FLOW_COLOURS if f in set(long["Flow"])]
        x = alt.X("FY ending:Q", axis=fy_axis(yearly), scale=alt.Scale(
            domain=[int(yearly["FY ending"].min()) - 0.6, int(yearly["FY ending"].max()) + 0.6], nice=False))
        domain = flow_domain(long, "AUD", (yearly["Net change in wealth"], yearly["Added to outside investments"]))
        bars = alt.Chart(long).mark_bar(size=16).encode(
            x=x, y=alt.Y("sum(AUD):Q", title="Average per year, today's dollars", axis=alt.Axis(format="$,.0f"),
                         scale=alt.Scale(domain=domain, nice=False)),
            color=alt.Color("Flow:N", sort=order, scale=alt.Scale(domain=order, range=[FLOW_COLOURS[f] for f in order]),
                            legend=alt.Legend(orient="bottom", title=None, columns=2, labelLimit=220)),
            tooltip=[alt.Tooltip("Period:N", title="Year"), "Flow:N", alt.Tooltip("AUD:Q", title="Average", format="$,.0f")])
        line = alt.Chart(yearly).mark_line(color="#19353a", strokeWidth=2, point=alt.OverlayMarkDef(color="#19353a", size=40)).encode(
            x=x, y="Net change in wealth:Q", tooltip=[alt.Tooltip("Period:N", title="Year"),
                                                     alt.Tooltip("Net change in wealth:Q", title="Average net change", format="$,.0f")])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#5f6b73").encode(y="y:Q")
        added = additions_layer(yearly.rename(columns={"Added to outside investments": "AUD"}), x)
        layers = [bars, zero, line] + ([added] if added is not None else [])
        st.subheader("Money in and out, averaged across the group")
        st.altair_chart(with_milestones(alt.layer(*layers).properties(height=600), marks, "Position:Q"), width="stretch")
        st.caption("Each bar is the average of that flow across the group's paths in that year, so the bars add up to the "
                   "average net change in wealth (black line). The dashed teal line is the average added to outside "
                   "investments from pay.")
        born = date.fromisoformat(plan["person"]["date_of_birth"])
        table = annual.groupby("FY ending")[[c for c in ("Wealth at 1 July", "Spending paid", "Shortfall", "Tax paid",
                                                          "Age Pension", "Pension payments", "Withdrawal rate")
                                             if c in annual]].mean().reset_index()
        table.insert(0, "Year", table["FY ending"].map(period))
        table.insert(1, "Age at 30 June", [age_on(born, date(int(y), 6, 30)) for y in table["FY ending"]])
        if "Withdrawal rate" in table:
            table["Withdrawal rate"] *= 100
        st.subheader("Year by year, averaged")
        st.dataframe(table.drop(columns="FY ending"), width="stretch", hide_index=True, height=fit(table),
                     column_config={"Year": st.column_config.TextColumn("Year (1 July – 30 June)", pinned=True),
                                    "Age at 30 June": st.column_config.NumberColumn(format="%d"),
                                    "Withdrawal rate": percent_column("Withdrawal rate"),
                                    **{c: money_column(c) for c in table.columns
                                       if c not in ("Year", "Age at 30 June", "FY ending", "Withdrawal rate")}})
        st.caption("Averages across the group's paths, today's dollars. Each path's daily ledger and event log are "
                   "available by picking it on its own.")


@st.fragment
def section_ledger(run):
    import altair as alt

    paths = run.retirement_paths
    calculated = paths.loc[paths["Status"] != "unsupported"].sort_values("Ending wealth")
    st.header("5 · One path in full: the daily ledger")
    st.markdown("Everything above summarises many paths. Here one path's daily ledger is shown in full, so you can "
                "see each salary payment, sale, tax bill and pension payment that produced its result.")
    ranks = ending_percentiles(calculated)
    choices = {f"Median ending wealth · path {run.representative_path}": run.representative_path}
    for label, low, high in PATH_GROUPS:
        members = group_members(calculated, low, high)
        choices[f"Average of the {label.lower()} · {len(members)} path{'s' if len(members) != 1 else ''}"] = members
    for _, row in calculated.iterrows():  # sorted from the worst ending wealth
        choices[f"Path {int(row['Path'])} · {ordinal(ranks[row['Path']])} percentile"] = int(row["Path"])
    picked = st.selectbox("Path to inspect", list(choices), key=key("ledger_path"))
    st.caption(f"The default is path {run.representative_path}: of the calculated paths, its ending wealth is closest "
               "to the median. The number is simply its position in the draw sequence. A median *ending* does not "
               "make every year median; the path may have had a bad start and a strong finish. The **averages** "
               "combine every path in a group, ranked by ending wealth, month by month and year by year: the worst 5% "
               "is what the bad outcomes typically look like, not one unlucky path. Single paths follow, from the "
               "worst to the best, tagged with their ending-wealth percentile.")
    if isinstance(choices[picked], list):
        averaged_paths(run, choices[picked], picked.split(" · ")[0])
        return
    path = choices[picked]
    with st.spinner(f"Running the daily ledger for path {path}..."):
        result = selected_ledger(run, path)
    cpi = run.plan["assumptions"]["cpi_annual"]
    daily, annual = real_daily(result.daily, cpi), result.annual
    start = daily.index[0]
    marks = milestones(run.plan, daily.index[0].date(), daily.index[-1].date())
    drawdown = float((daily["total"] / daily["total"].cummax() - 1).min())
    outcome = calculated.set_index("Path").loc[path]
    w = st.columns(4)
    w[0].metric("Wealth at start", compact(daily["total"].iloc[0]))
    w[1].metric("Wealth at retirement", compact(outcome["Wealth at retirement"]),
                help="Total wealth on your retirement date, today's dollars.")
    w[2].metric("Wealth when super becomes accessible", compact(outcome.get("Wealth when super accessible", np.nan)),
                help="Total wealth on the first day super can be withdrawn (preservation age and retirement), when that "
                     "is after the start.")
    w[3].metric(f"Wealth at {daily.index[-1].date()}", compact(daily["total"].iloc[-1]))
    a, b, c, d, e = st.columns(5)
    a.metric("Ending wealth percentile", ordinal(ranks[path]),
             help="Where this path's ending wealth ranks among calculated paths.")
    b.metric("Age Pension received", compact(daily["age_pension"].sum()) if "age_pension" in daily else "–")
    c.metric("Spending shortfall", compact(daily["shortfall"].sum()))
    d.metric("Tax (personal, fund, Division 296)", compact(sum((x["assessment"].net_tax + x["assessment"].division_293_tax)
                                                  / year_deflator(int(x["financial_year"][:4]) + 1, start, cpi) for x in annual)
                                              + daily["fund_tax"].sum() + daily["division_296"].sum()))
    e.metric("Largest fall in wealth", share(drawdown),
             help="Deepest fall of total wealth below its previous high on this path. Unlike a portfolio drawdown it "
                  "includes spending, so it keeps falling in retirement even in flat markets.")
    st.altair_chart(with_milestones(balances_chart(daily), marks), width="stretch")
    st.caption("Month-end balances by account in today's dollars, stacked. Watch outside money fund spending until super becomes "
               "accessible, then the move from accumulation into the pension. Dashed lines mark the life events.")

    st.subheader("Money in and out on this path, before and during retirement")
    household = household_flows(daily, inflation=True)
    household["Period"] = household["FY ending"].map(period_label)
    shown = household.groupby("Flow").filter(lambda g: g["AUD"].abs().max() > 1e-6)
    colours = FLOW_COLOURS
    order = [f for f in colours if f in set(shown["Flow"])]
    x = alt.X("FY ending:Q", axis=fy_axis(household), scale=alt.Scale(
        domain=[int(household["FY ending"].min()) - 0.6, int(household["FY ending"].max()) + 0.6], nice=False))
    moves = account_flows(daily, real_events(result.events, start, cpi))
    additions = (moves.loc[moves["Flow"] == "Savings invested"].groupby("FY ending")["AUD"].sum()
                 .reindex(sorted(household["FY ending"].unique()), fill_value=0.0).reset_index(name="AUD"))
    additions["Period"] = additions["FY ending"].map(period_label)
    y_domain = flow_domain(shown, "AUD", (household["Net change"], additions["AUD"]))
    bars = alt.Chart(shown).mark_bar(size=16).encode(
        x=x, y=alt.Y("sum(AUD):Q", title="Per year, today's dollars", axis=alt.Axis(format="$,.0f"),
                     scale=alt.Scale(domain=y_domain, nice=False)),
        color=alt.Color("Flow:N", sort=order, scale=alt.Scale(domain=order, range=[colours[f] for f in order]),
                        legend=alt.Legend(orient="bottom", title=None, columns=2, labelLimit=220)),
        order=alt.Order("Flow:N"),
        tooltip=[alt.Tooltip("Period:N", title="Year"), "Flow:N", alt.Tooltip("AUD:Q", format="$,.0f")])
    net = household.drop_duplicates("FY ending")
    line = alt.Chart(net).mark_line(color="#19353a", strokeWidth=2, point=alt.OverlayMarkDef(color="#19353a", size=40)).encode(
        x=x, y="Net change:Q", tooltip=[alt.Tooltip("Period:N", title="Year"), alt.Tooltip("Opening:Q", title="Wealth at start", format="$,.0f"),
                                         alt.Tooltip("Net change:Q", title="Net change in wealth", format="$,.0f"),
                                         alt.Tooltip("Closing:Q", title="Wealth at end", format="$,.0f")])
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#5f6b73").encode(y="y:Q")
    added = additions_layer(additions, x)
    layers = [bars, zero, line] + ([added] if added is not None else [])
    st.altair_chart(with_milestones(alt.layer(*layers).properties(height=670), marks, "Position:Q"), width="stretch")
    st.caption("Every dollar that changed your total wealth in each year, for this path. The dashed teal line with squares "
               "is what was **added to outside investments** that year, from your pay or, after retirement, from unspent "
               "pension payments and other spare cash: it moves money from cash into the portfolio, so it is drawn as a "
               "line rather than a bar. Above zero: take-home salary, "
               "employer and salary-sacrifice contributions into super, and investment returns in good years. Below zero: "
               "spending, income tax, the 15% contributions tax, super fund tax, investment losses in bad years and "
               "inflation (the buying power wealth lost that year; amounts are in today's dollars). The black "
               "line is the net change in total wealth, which equals the sum of the bars. Hover for amounts and the "
               "wealth at the start and end of each year. Before retirement salary carries spending; after it, spending is "
               "paid from investments and super.")
    if not moves.empty:
        st.markdown("**Money moving into and out of each account**")
        domain = [int(household["FY ending"].min()) - 0.6, int(household["FY ending"].max()) + 0.6]
        for account in ("Outside investments", "Super (accumulation)", "Account-based pension"):
            part = moves.loc[moves["Account"] == account].copy()
            if part.empty:
                st.caption(f"{account}: no transfers on this path.")
                continue
            part["Period"] = part["FY ending"].map(period_label)
            chart = alt.Chart(part).mark_bar(size=14).encode(
                x=alt.X("FY ending:Q", axis=fy_axis(household), scale=alt.Scale(domain=domain, nice=False)),
                y=alt.Y("sum(AUD):Q", title=account, axis=alt.Axis(format="$,.0f")),
                color=alt.Color("Flow:N", legend=alt.Legend(orient="right", title=None, labelLimit=220)),
                tooltip=[alt.Tooltip("Period:N", title="Year"), "Flow:N", alt.Tooltip("AUD:Q", format="$,.0f")])
            st.altair_chart(with_milestones(alt.layer(chart, zero).properties(height=340), marks, "Position:Q"),
                            width="stretch")
        st.caption("Transfers only, excluding investment growth. Outside investments receive your leftover pay and are "
                   "sold to pay spending and tax; super receives contributions (after the 15% tax), pays fund tax and "
                   "moves into the pension; the pension pays you at least the yearly minimum.")

    born = date.fromisoformat(run.plan["person"]["date_of_birth"])
    rows = []
    for x in annual:
        end_year = int(x["financial_year"][:4]) + 1
        flow = year_deflator(end_year, start, cpi)  # this year's amounts in today's dollars
        balance = (1 + cpi) ** ((pd.Timestamp(date(end_year, 6, 30)) - start).days / 365.25)
        rows.append({"Year": period(end_year), "Age at 30 June": age_on(born, date(end_year, 6, 30)),
                     "Taxable income": x["assessment"].taxable_income / flow,
                     "Net tax": (x["assessment"].net_tax + x["assessment"].division_293_tax) / flow,
                     "Net capital gain": x["assessment"].net_capital_gain / flow,
                     "Concessional contributions": x["concessional_contributions"] / flow,
                     "Cap available": x["concessional_cap_available"] / flow,
                     "Spending paid": x["spending_paid"] / flow, "Shortfall": x["shortfall"] / flow,
                     "Pension minimum": (x["pension_minimum"] or 0.0) / flow, "Pension paid": (x["pension_paid"] or 0.0) / flow,
                     "Age Pension": x.get("age_pension", 0.0) / flow, "SAPTO": x["assessment"].sapto / flow,
                     "Division 296 tax": x.get("division_296_tax", 0.0) / flow,
                     "Transfer balance": (x["transfer_balance"] or 0.0) / balance,
                     "Super at 30 June": x["total_super_balance_30_june"] / balance,
                     "FY ending": end_year})
    st.subheader("Year by year")
    frame = pd.DataFrame(rows)
    st.dataframe(frame.drop(columns="FY ending"), width="stretch", hide_index=True, height=fit(frame),
                 column_config={"Year": st.column_config.TextColumn("Year (1 July – 30 June)", pinned=True),
                                "Age at 30 June": st.column_config.NumberColumn(format="%d"),
                                **{c: money_column(c) for c in frame.columns if c not in ("Year", "Age at 30 June", "FY ending")}})
    st.caption("Amounts in today's dollars. Australian tax and super run on financial years from 1 July to 30 June; each row is one of those years. "
               "Taxable income includes realised capital gains after the discount; the pension columns show the "
               "legislated minimum and what was actually paid; the transfer balance counts amounts moved into the "
               "tax-free pension against the cap.")
    tax_frame = frame.melt(["FY ending", "Year"], value_vars=["Taxable income", "Net tax", "Net capital gain"], var_name="Measure", value_name="AUD")
    cap_frame = frame.melt(["FY ending", "Year"], value_vars=["Concessional contributions", "Cap available"], var_name="Measure", value_name="AUD")
    a, b = st.columns(2)
    for column, part, heading in ((a, tax_frame, "Personal tax"), (b, cap_frame, "Concessional contributions and cap")):
        with column:
            st.markdown(f"**{heading}**")
            chart = zoomable(alt.Chart(part).mark_line(point=True).encode(
                x=alt.X("FY ending:Q", axis=fy_axis(part), scale=alt.Scale(nice=False, domain=[
                    int(part["FY ending"].min()) - 0.5, int(part["FY ending"].max()) + 0.5])),
                y=alt.Y("AUD:Q", axis=alt.Axis(format="$,.0f")),
                color=alt.Color("Measure:N", legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["Year:N", "Measure:N", alt.Tooltip("AUD:Q", format="$,.0f")]).properties(height=430))
            st.altair_chart(with_milestones(chart, marks, "Position:Q"), width="stretch")
    st.caption("Left: income, realised gains and tax assessed each year. Right: concessional contributions against the "
               "cap available, which includes carried-forward unused cap when your balance allows it.")
    if (frame["Pension paid"] > 0).any():
        pension = frame.loc[frame["Pension paid"] > 0].melt(["FY ending", "Year"], value_vars=["Pension minimum", "Pension paid"],
                                                            var_name="Measure", value_name="AUD")
        st.markdown("**Account-based pension**")
        st.altair_chart(alt.Chart(pension).mark_bar().encode(
            x=alt.X("FY ending:O", title=YEAR_TITLE), xOffset="Measure:N", y=alt.Y("AUD:Q", axis=alt.Axis(format="$,.0f")),
            color=alt.Color("Measure:N", scale=alt.Scale(range=["#c9b8da", "#8363a0"]), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["Year:N", "Measure:N", alt.Tooltip("AUD:Q", format="$,.0f")]).properties(height=410), width="stretch")
        st.caption("The legislated minimum (a percentage of the 1 July balance that rises with age) against what was "
                   "paid. Payments above the minimum happen when spending needs them.")
    outstanding = result.outstanding
    if outstanding["tax_liabilities"] or outstanding["unassessed_year"] or outstanding["unpaid_tax"]:
        st.caption(f"At the horizon: tax not yet due {[l['financial_year'] for l in outstanding['tax_liabilities']]}; "
                   f"unpaid tax {[u['financial_year'] for u in outstanding['unpaid_tax']]}; partial year not yet assessed "
                   f"{(outstanding['unassessed_year'] or {}).get('financial_year')}.")
    with st.expander("Event log for this path (nominal dollars, as the ledger records them)"):
        events = result.events
        kinds = sorted(events["event"].unique())
        chosen = st.multiselect("Event types", kinds, default=[k for k in kinds if k not in ("buy", "distribution")],
                                key=key("event_types"))
        st.dataframe(events.loc[events["event"].isin(chosen)], width="stretch", hide_index=True,
                     column_config={"amount": money_column("amount")})
    name = slug(run.plan["plan"]["name"])
    a, b = st.columns(2)
    a.download_button("Download this path's daily ledger (CSV, nominal)", result.daily.to_csv(), f"{name}-path{path}-daily.csv", "text/csv")
    b.download_button("Download this path's events (CSV, nominal)", result.events.to_csv(index=False), f"{name}-path{path}-events.csv",
                      "text/csv")


def results(plan):
    try:
        valid = normalize_plan(plan)
    except PlanError as exc:
        st.error("The plan has problems to fix before it can run:")
        for problem in exc.problems:
            st.markdown(f"- `{problem}`")
        return
    st.button("Run plan", type="primary", on_click=request_run, key="run_results")
    run = st.session_state.result
    if run is None:
        st.info("Press Run plan to see your portfolios, their history and simulated futures, retirement outcomes "
                "across many market paths, and any single path's daily ledger.")
        return
    if not hasattr(run, "wealth_paths"):  # the newest PlanRun field; an old server's modules lack it
        # Streamlit reloads this page's code on change but not the simulation modules it imports.
        st.error("The planner code was updated while this app was running, so these results came from the old code. "
                 "Stop the app (Ctrl+C in its terminal) and start it again with `financial-simulations ui`, then "
                 "press Run plan.")
        return
    if plan_to_json(valid) != plan_to_json(run.plan):
        st.warning("Inputs have changed since this run. Press Run plan to refresh the results.")
    for note in run.notes:
        st.warning(note)
    BORN["date"] = date.fromisoformat(run.plan["person"]["date_of_birth"])
    inflation_note(run.plan)
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
    start_ledger_workers(st.session_state.plan["market"]["retirement_paths"])
    run_requested_plan()
    plan = st.session_state.plan
    # A keyed, tracked tab set keeps the open tab when a widget on it reruns the app.
    tabs = st.tabs(["You", "Investments", "Retirement", "Assumptions", "Results"], key="main_tabs", on_change="rerun")
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
