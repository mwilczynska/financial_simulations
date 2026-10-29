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
                                                   plan_to_toml, sacrifice_per_year, slug)
from financial_simulations.retirement.flows import account_flows, household_flows, milestones
from financial_simulations.retirement.paths import warm_pool
from financial_simulations.retirement.run_plan import ledger_for_path, run_plan
from financial_simulations.rules.au.parameters import UnsupportedRule, load_ruleset
from financial_simulations.rules.au.superannuation import age_on
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
                                            help="Paid fortnightly until retirement; constant in nominal terms.")
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
                   "Take-home pay less tax and spending, all invested.") + " Set this on the Investments tab; it stops at retirement.")
    if fixed and surplus > invested + 1:
        st.caption(f"About ${surplus - invested:,.0f} a year of leftover pay stays in cash (cash earns no interest in this model).")
    if fixed and plan["outside"]["contribution_per_year"] > max(surplus, 0) + 1:
        st.warning("The fixed outside contribution is more than is left after tax and spending; only what is available "
                   "above the cash buffer is invested each payday.")
    if concessional > rules["concessional_cap"]:
        st.warning(f"Super guarantee plus salary sacrifice (${concessional:,.0f}) is above the ${rules['concessional_cap']:,.0f} "
                   "concessional cap. Unless you have carried-forward unused cap, the run will stop with an excess-contributions message.")
    st.caption("How saving outside super works: each fortnight your salary after sacrifice goes into cash. Spending (monthly) "
               "and tax (each 31 October) are paid from it. Then either everything above the cash buffer, or your fixed "
               "contribution, buys the outside portfolio (choose on the Investments tab). New investing stops at "
               "retirement. The figures are first-year estimates before investment income; salary is constant in dollars.")


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
    st.caption("Contributions come out of your pay each fortnight and stop at your retirement date. After retirement no new "
               "money is invested: pension payments or super withdrawals not spent stay in cash. See the estimate on the You tab.")
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
                                                  "Inside super the switch is modelled without tax (funds are assumed not to realise gains).")


def inputs_retirement(plan):
    st.subheader("Spending")
    a, b = st.columns(2)
    with a:
        plan["spending"]["annual"] = money("Annual spending (AUD, first year)", plan["spending"]["annual"], "spend")
    with b:
        plan["spending"]["annual_growth"] = percent("Spending growth %/yr", plan["spending"]["annual_growth"], "spendg", low=-20, high=20,
                                                    help="Set equal to CPI to keep spending's buying power constant. "
                                                         "Spending is entered in today's dollars for the first year.")
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
        y=alt.Y("balance:Q", stack="zero", title="AUD (nominal)", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Account:N", sort=[v[0] for v in ACCOUNTS.values()],
                        scale=alt.Scale(domain=[v[0] for v in ACCOUNTS.values()], range=[v[1] for v in ACCOUNTS.values()]),
                        legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), *age_tooltip(long), "Account:N",
                 alt.Tooltip("balance:Q", title="Balance", format="$,.0f"), alt.Tooltip("Share:Q", title="Share of wealth", format=".0%"),
                 alt.Tooltip("Total:Q", title="Total wealth", format="$,.0f")],
    ).properties(height=530))


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


def all_paths_chart(paths, marks, outcomes=None):
    """Every path's total wealth as a faint grey line (overlaps darken); the path nearest the pointer is highlighted.

    All paths are drawn, because their overlap is the distribution. To keep the browser responsive the line layer
    carries only the four fields it needs, and hovering uses one invisible point per path per year (the nearest
    point picks the path) instead of every month, which keeps the hover index about twelve times smaller.
    """
    import altair as alt

    lines_frame = paths[["Date", "Path", "Status", "Total wealth"]]
    medians = lines_frame.groupby("Date")["Total wealth"].median()
    wide = float(lines_frame["Total wealth"].quantile(0.95)) > 20 * max(1000.0, float(medians.max()))
    count = lines_frame["Path"].nunique()
    opacity = min(0.45, max(0.04, 15 / count))
    y = alt.Y("Total wealth:Q", title="Total wealth (nominal AUD" + (", log-like)" if wide else ")"),
              scale=alt.Scale(type="symlog", constant=1000) if wide else alt.Scale(zero=True), axis=alt.Axis(format="$,.0f"))
    hover = alt.selection_point(fields=["Path"], on="pointerover", nearest=True, clear="pointerout", empty=False,
                                name="path_hover")
    x = alt.X("Date:T", title=None, axis=year_axis(lines_frame))
    lines = alt.Chart(lines_frame).mark_line().encode(
        x=x, y=y, detail="Path:N",
        color=alt.when(hover).then(alt.value("#0b3d45")).otherwise(
            alt.Color("Status:N", scale=alt.Scale(domain=["funded", "depleted"], range=["#4a4a4a", "#b23a3a"]),
                      legend=alt.Legend(orient="bottom", title=None))),
        opacity=alt.when(hover).then(alt.value(1.0)).when(alt.datum.Status == "depleted")
        .then(alt.value(min(0.7, opacity * 3))).otherwise(alt.value(opacity)),
        strokeWidth=alt.when(hover).then(alt.value(3.5)).otherwise(alt.value(1.0)))
    # Invisible yearly points (each June month end, plus each path's last month) carry the hover and tooltip.
    dates = pd.to_datetime(paths["Date"])
    yearly = paths.loc[(dates.dt.month == 6) | (dates == dates.max())]
    yearly = add_age(yearly)
    if outcomes is not None:
        keep = outcomes[["Path", "Ending wealth", "Spending shortfall", "First retired-year withdrawal rate"]]
        yearly = yearly.merge(keep, on="Path", how="left")
    extra = [alt.Tooltip(f, format=fmt, title=t) for f, fmt, t in
             (("Ending wealth:Q", "$,.0f", "Path's ending wealth"), ("Spending shortfall:Q", "$,.0f", "Path's spending shortfall"),
              ("First retired-year withdrawal rate:Q", ".1%", "Path's first retired-year withdrawal rate"))
             if f.split(":")[0] in yearly]
    points = alt.Chart(yearly).mark_point(opacity=0, size=80).encode(
        x="Date:T", y="Total wealth:Q",
        tooltip=[alt.Tooltip("Path:N", title="Path"), "Status:N", alt.Tooltip("Date:T", format="%b %Y"), *age_tooltip(yearly),
                 alt.Tooltip("Total wealth:Q", title="Wealth on this date", format="$,.0f"), *extra]).add_params(hover)
    median_frame = add_age(medians.reset_index())
    median = alt.Chart(median_frame).mark_line(color="#126a63", strokeWidth=3).encode(
        x="Date:T", y="Total wealth:Q",
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), *age_tooltip(median_frame),
                 alt.Tooltip("Total wealth:Q", title="Median of all paths", format="$,.0f")])
    # One flat layer: nesting a chart that owns a selection inside another layer duplicates its signals.
    ZOOM_COUNT[0] += 1
    zoom = alt.selection_interval(bind="scales", zoom="wheel![event.shiftKey]", name=f"zoom_{ZOOM_COUNT[0]}")
    layers = [lines.add_params(zoom), median, points]
    if marks is not None and not marks.empty:
        layers += [alt.Chart(marks).mark_rule(strokeDash=[4, 3], color="#5f6b73", strokeWidth=1.3).encode(
                       x="Date:T", tooltip=["Event:N", alt.Tooltip("Date:T", format="%d %b %Y")]),
                   alt.Chart(marks).mark_text(align="left", dx=4, fontSize=11, color="#3c474d").encode(
                       x="Date:T", y=alt.Y("Offset:Q", scale=None), text="Event:N")]
    return alt.layer(*layers).properties(height=620)


def ending_wealth_chart(calculated, marks_text=True):
    """Every path's ending wealth, sorted: hover a dot for its exact values; the median and 10th/90th are labelled."""
    import altair as alt

    # Vega-Lite field names cannot contain an apostrophe.
    frame = calculated.sort_values("Ending wealth").reset_index(drop=True).rename(
        columns={"Ending wealth, today's dollars": "Ending real"})
    frame["Rank"] = (np.arange(len(frame)) + 0.5) / len(frame)
    wide = float(frame["Ending wealth"].max()) > 20 * max(1000.0, float(frame["Ending wealth"].median()))
    y = alt.Y("Ending wealth:Q", title="Ending wealth (nominal AUD" + (", log-like)" if wide else ")"),
              scale=alt.Scale(type="symlog", constant=1000) if wide else alt.Scale(zero=True), axis=alt.Axis(format="$,.0f"))
    dots = alt.Chart(frame).mark_circle(size=70, opacity=0.85).encode(
        x=alt.X("Rank:Q", title="Paths ranked by ending wealth (share of paths below)", axis=alt.Axis(format=".0%", grid=True),
                scale=alt.Scale(domain=[0, 1])),
        y=y, color=alt.Color("Status:N", scale=alt.Scale(domain=["funded", "depleted"], range=["#126a63", "#b23a3a"]),
                             legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("Path:Q", format="d"), "Status:N", alt.Tooltip("Rank:Q", title="Share of paths below", format=".0%"),
                 alt.Tooltip("Ending wealth:Q", format="$,.0f"),
                 alt.Tooltip("Ending real:Q", title="In today's dollars", format="$,.0f"),
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
    """Say once, plainly, which numbers are in future dollars and which are adjusted for inflation."""
    cpi = plan["assumptions"]["cpi_annual"]
    with st.expander("Which numbers are adjusted for inflation?"):
        st.markdown(f"""
**Unless a number says "today's dollars", it is in nominal dollars**: the dollars of the date it refers to. A
nominal \\$1,000,000 in 20 years buys what about \\${1e6 / (1 + cpi) ** 20:,.0f} buys today at the assumed {cpi:.1%} CPI.

| Item | Treatment |
| --- | --- |
| Market returns, portfolio values, wealth bands, balances, tax | Nominal (USD total-return history applied as AUD) |
| "Ending wealth, today's dollars" and the "…in today's dollars" metric | Inflation adjusted: divided by (1 + CPI) per year |
| Spending | Grows each 1 July by your spending growth ({plan['spending']['annual_growth']:.1%}). Equal to CPI means constant buying power |
| Salary | Not indexed: the same dollar amount each year until retirement |
| Fixed yearly additions to outside investments | Indexed to CPI only if you tick the inflation box |
| Tax brackets and super caps after 2026-27 | Projected with the CPI and wage-growth assumptions |
| Withdrawal rates (section 3) | Withdrawals rise with spending growth; "lasts indefinitely" keeps the portfolio's value grown by CPI |
| Interest on cash | Nominal rate |
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
            st.markdown(f"Historical CAGR **{share(stats['CAGR'])}** · volatility **{share(stats['Volatility'])}** · "
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
    growth, cpi = plan["spending"]["annual_growth"], plan["assumptions"]["cpi_annual"]
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
later year withdraws the same amount grown by your spending growth ({growth:.1%} a year), so the money keeps its
buying power. Example: a 4% rate on \\$1,000,000 is \\$40,000 in the first year, about \\${40000 * (1 + growth):,.0f}
in the second, and so on. Withdrawals are taken monthly.

The planner tests every simulated market path from your retirement date ({portfolios.retirement_start}) for
{years:.0f} years, to age {age}. These paths are separate from the tax-ledger paths, because the ledger stops before
Age Pension age. For each path it solves two questions exactly:

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


def section_future(run):
    import altair as alt

    plan, portfolios, market = run.plan, run.portfolios, run.market
    st.header("3 · Future portfolio simulations")
    st.info("This section shows **investment returns only**: $100 put in each portfolio at the start and left alone. "
            "There are no yearly additions, salary contributions, withdrawals or tax here, so you can compare how the "
            "portfolios themselves behave. Your contributions, spending, tax and super rules are applied to these same "
            "market paths in sections 4 and 5. Values are nominal (not adjusted for inflation).")
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
5. **Statistics per path.** Ending value of \\$100; annualised growth over the calendar horizon; volatility
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
    marks = milestones(plan, portfolios.dates[0], portfolios.dates[-1])
    st.altair_chart(band_chart(fan, "Growth of $100 · log scale", log=True, color=PALETTE[selected], marks=marks),
                    width="stretch")
    st.caption("Dark band: middle half of paths (25th–75th percentile). Light band: 90% of paths (5th–95th). Line: "
               "median at each month. Dashed lines mark retirement, super access and the pension start. Hover for values; "
               "drag to pan, Shift+scroll to zoom, double-click to reset.")
    medians = portfolios.paths[["Date", "Portfolio", "P50"]]
    st.altair_chart(zoomable(alt.Chart(medians).mark_line(strokeWidth=2).encode(
        x=alt.X("Date:T", title=None, axis=year_axis(medians)),
        y=alt.Y("P50:Q", title="Median growth of $100", scale=alt.Scale(type="log", nice=False,
                domain=[float(medians["P50"].min()) * 0.95, float(medians["P50"].max()) * 1.05]), axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Portfolio:N", scale=scale_for(names), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Portfolio:N", alt.Tooltip("P50:Q", format="$,.0f")]
    ).properties(height=380)), width="stretch")
    st.caption("Median paths side by side, to compare the portfolios' central outcomes on the same draws.")
    dd = fan.rename(columns={"Drawdown P05": "Bad (5th pct)", "Drawdown P50": "Typical (median)"})
    dd = dd.melt("Date", value_vars=["Bad (5th pct)", "Typical (median)"], var_name="Path", value_name="Drawdown")
    st.altair_chart(zoomable(alt.Chart(dd).mark_line().encode(
        x=alt.X("Date:T", title=None, axis=year_axis(dd)), y=alt.Y("Drawdown:Q", title="Below previous peak", axis=alt.Axis(format=".0%")),
        strokeDash=alt.StrokeDash("Path:N", legend=alt.Legend(orient="bottom", title=None)), color=alt.value(PALETTE[selected]),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Path:N", alt.Tooltip("Drawdown:Q", format=".1%")]
    ).properties(height=360)), width="stretch")
    st.caption(f"{selected}: how far below its running peak the portfolio sits at each month end, for the median "
               "path and for the worst 5% of paths at that date.")

    st.subheader("Distributions across paths")
    outcomes = portfolios.outcomes
    a, b = st.columns(2)
    with a:
        st.altair_chart(overlay_histogram(outcomes, "Terminal growth of 100", "Ending value of $100 (log scale)", log=True, series=tuple(names)),
                        width="stretch")
        st.caption("Where $100 ends up at the horizon. Dashed lines are medians.")
        st.altair_chart(overlay_histogram(outcomes, "Annualised volatility", "Annualised volatility", series=tuple(names)), width="stretch")
        st.caption("Day-to-day variability of each path, annualised. Higher volatility means wider swings in wealth.")
    with b:
        st.altair_chart(overlay_histogram(outcomes, "Annualised growth", "Annualised growth", series=tuple(names)), width="stretch")
        st.caption("Compound growth per year over the whole horizon on each path.")
        st.altair_chart(overlay_histogram(outcomes, "Maximum drawdown", "Maximum drawdown", series=tuple(names)), width="stretch")
        st.caption("Deepest peak-to-trough fall on each path. −50% means the portfolio halved at some point.")
    withdrawal_rates_section(plan, portfolios, names)
    table = []
    for title in names:
        part = outcomes.loc[outcomes["Portfolio"] == title]
        t = percentile_table(part, {"Ending value of $100": ("Terminal growth of 100", "money"),
                                    "Annualised growth": ("Annualised growth", "percent"),
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
    if not portfolios.annual_returns.empty:
        annual = portfolios.annual_returns.loc[portfolios.annual_returns["Portfolio"] == selected]
        st.altair_chart(band_chart(quantile_bands(annual, "Year", "Return"), "Calendar-year return", percent=True,
                                   color=PALETTE[selected], x="Year:Q"), width="stretch")
        st.caption(f"{selected}: spread of each full calendar year's return across paths. Partial first and last years "
                   "are left out.")


FLOW_COLOURS = {"Take-home salary": "#126a63", "Super contributions": "#386a98", "Investment returns": "#9a8a2e",
                "Interest on cash": "#4f8f3a",
                "Spending": "#b76a42", "Income tax": "#8c2f2f", "Contributions tax": "#c2577a", "Super fund tax": "#8363a0"}


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


def typical_flows_section(annual, marks, paths):
    """Median money in and out each year across every calculated path, with the net change's middle half."""
    import altair as alt

    columns = [c for c in annual.columns if c.startswith("Flow: ")]
    if not columns:
        return
    st.subheader("Money in and out in a typical year, across all paths")
    long = annual.melt(["Path", "FY ending"], value_vars=columns, var_name="Flow", value_name="AUD")
    long["Flow"] = long["Flow"].str.replace("Flow: ", "", regex=False)
    stats = long.groupby(["FY ending", "Flow"])["AUD"].quantile([0.25, 0.5, 0.75]).unstack().reset_index()
    stats.columns = ["FY ending", "Flow", "P25", "Median", "P75"]
    stats = stats.groupby("Flow").filter(lambda g: g[["P25", "Median", "P75"]].abs().max().max() > 1e-6)
    stats["Period"] = stats["FY ending"].map(period_label)
    net = annual.groupby("FY ending")["Net change in wealth"].quantile([0.25, 0.5, 0.75]).unstack().reset_index()
    net.columns = ["FY ending", "P25", "Median", "P75"]
    net["Period"] = net["FY ending"].map(period_label)
    order = [f for f in FLOW_COLOURS if f in set(stats["Flow"])]
    domain = [int(annual["FY ending"].min()) - 0.6, int(annual["FY ending"].max()) + 0.6]
    x = alt.X("FY ending:Q", axis=fy_axis(annual), scale=alt.Scale(domain=domain, nice=False))
    additions = annual.groupby("FY ending")["Added to outside investments"].median().reset_index(name="AUD")         if "Added to outside investments" in annual else pd.DataFrame(columns=["FY ending", "AUD"])
    additions["Period"] = additions["FY ending"].map(period_label)
    y_domain = flow_domain(stats, "Median", (net["P25"], net["P75"], additions["AUD"] if len(additions) else [0.0]))
    bars = alt.Chart(stats).mark_bar(size=16).encode(
        x=x, y=alt.Y("Median:Q", stack=True, title="Median AUD per year", axis=alt.Axis(format="$,.0f"),
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
                                    alt.Tooltip("Median:Q", title="Median net change in wealth", format="$,.0f"),
                                    alt.Tooltip("P25:Q", title="25th percentile", format="$,.0f"),
                                    alt.Tooltip("P75:Q", title="75th percentile", format="$,.0f")])
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#5f6b73").encode(y="y:Q")
    added = additions_layer(additions, x)
    layers = [bars, zero, spread, line] + ([added] if added is not None else [])
    st.altair_chart(with_milestones(alt.layer(*layers).properties(height=670), marks, "Position:Q"), width="stretch")
    st.caption(f"Each bar is the **median across all {paths} calculated paths** of that flow in that year: take-home "
               "salary, super contributions and investment returns above zero; spending, income tax, contributions tax "
               "and super fund tax below. The black line is the median net change in total wealth, with whiskers "
               "showing the middle half of paths (25th to 75th percentile). Hover a bar for its 25th and 75th "
               "percentiles. The dashed teal line with squares is the median amount **added to outside investments** from your "
               "pay each year; it moves money from cash into the portfolio, so it is not a bar and does not change total "
               "wealth, and it stops at retirement. Medians do not add up, so the bars do not sum exactly to the median net change; "
               "investment returns vary most between paths. Section 5 shows one path whose bars add up exactly.")


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
    marks = milestones(plan, run.result.daily.index[0].date(), run.result.daily.index[-1].date())
    st.subheader("Wealth over time")
    names = list(dict.fromkeys(run.account_bands["Series"]))
    choice = st.radio("Show", names, horizontal=True, key=key("wealth_series"))
    bands = run.account_bands.loc[run.account_bands["Series"] == choice]
    wide = wide_wealth_range(bands)
    st.altair_chart(band_chart(bands, f"{choice} (AUD proxy" + (", log-like)" if wide else ")"), symlog=wide, marks=marks),
                    width="stretch")
    st.caption(f"Month-end {choice.lower()} across the {len(calculated)} calculated paths, nominal dollars: dark band the "
               "middle half, light band 90% of paths, line the median. Dashed vertical lines mark retirement, when super "
               "becomes accessible and when the pension starts. "
               + ("The axis is linear up to $1,000 and logarithmic above, so a very high upper tail does not flatten "
                  "the median. " if wide else "")
               + "Total wealth includes super that may not yet be accessible.")
    if getattr(run, "wealth_paths", None) is not None:
        st.subheader("Wealth over time on every path")
        st.altair_chart(all_paths_chart(run.wealth_paths, marks, calculated), width="stretch")
        st.caption(f"All {len(calculated)} calculated paths are drawn. "
                   + f"Each faint grey line is one path's total wealth at each month end "
                   "(nominal). Lines are translucent, so where many paths overlap the grey darkens: the darkest areas are "
                   "where most paths went. The teal line is the median at each month; red lines are depleted paths. Point at "
                   "a line to highlight that whole path and see its value, your age, and its ending wealth, shortfall and "
                   "withdrawal rate; the path number can be opened in section 5.")
    st.subheader("Ending wealth on every path")
    st.altair_chart(ending_wealth_chart(calculated), width="stretch")
    st.caption(f"Each dot is one path's total wealth on {run.result.daily.index[-1].date()}, sorted from lowest (left) to "
               "highest (right); the horizontal position is the share of paths that ended lower. Hover a dot for its "
               "exact ending wealth, the same in today's dollars, the split between outside super and super, and any "
               "spending shortfall. Red dots are depleted paths. Dashed lines label the 10th percentile, median and 90th "
               "percentile.")
    annual = run.retirement_annual.copy()
    annual["Period"] = annual["FY ending"].map(period_label)
    typical_flows_section(annual, marks, len(calculated))
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
wealth that year (spending paid plus personal tax paid) divided by your **total** wealth on that 1 July, outside and
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
total wealth; spending grows at {plan['spending']['annual_growth']:.1%} a year.
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
        "Ending wealth": ("Ending wealth", "money"), "Ending wealth, today's dollars": ("Ending wealth, today's dollars", "money"),
        "Ending outside wealth": ("Ending outside wealth", "money"), "Ending super and pension": ("Ending super and pension", "money"),
        "Wealth at retirement": ("Wealth at retirement", "money"), "Spending shortfall": ("Spending shortfall", "money"),
        "Personal tax assessed": ("Personal tax assessed", "money"), "Fund tax": ("Fund tax", "money"),
        "Pension payments": ("Pension payments", "money"), "Pension balance at start": ("Pension balance at start", "money"),
        "First retired-year withdrawal rate": ("First retired-year withdrawal rate", "percent"),
        "Highest withdrawal rate": ("Highest withdrawal rate", "percent"),
        "Largest fall in total wealth": ("Largest fall in wealth", "percent")})
    st.dataframe(ranges, width="stretch", hide_index=True, height=fit(ranges))
    st.caption("Percentiles across calculated paths. Each column is a separate ranking, so a row's 5th percentile "
               "and another row's 5th percentile usually come from different paths.")
    with st.expander(f"Every path ({len(paths)})"):
        table = paths.copy()
        for field in ("First retired-year withdrawal rate", "Highest withdrawal rate", "Median withdrawal rate",
                      "Largest fall in wealth"):
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
                                                          "Median withdrawal rate", "Largest fall in wealth")}})
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
    marks = milestones(run.plan, daily.index[0].date(), daily.index[-1].date())
    drawdown = float((daily["total"] / daily["total"].cummax() - 1).min())
    a, b, c, d, e = st.columns(5)
    a.metric("Wealth at start", compact(daily["total"].iloc[0]))
    b.metric(f"Wealth at {daily.index[-1].date()}", compact(daily["total"].iloc[-1]))
    c.metric("Spending shortfall", compact(daily["shortfall"].sum()))
    d.metric("Tax (personal + fund)", compact(sum(x["assessment"].net_tax + x["assessment"].division_293_tax for x in annual)
                                              + daily["fund_tax"].sum()))
    e.metric("Largest fall in wealth", share(drawdown),
             help="Deepest fall of total wealth below its previous high on this path. Unlike a portfolio drawdown it "
                  "includes spending, so it keeps falling in retirement even in flat markets.")
    st.altair_chart(with_milestones(balances_chart(daily), marks), width="stretch")
    st.caption("Month-end balances by account, stacked. Watch outside money fund spending until super becomes "
               "accessible, then the move from accumulation into the pension. Dashed lines mark the life events.")

    st.subheader("Money in and out on this path, before and during retirement")
    household = household_flows(daily)
    household["Period"] = household["FY ending"].map(period_label)
    shown = household.groupby("Flow").filter(lambda g: g["AUD"].abs().max() > 1e-6)
    colours = FLOW_COLOURS
    order = [f for f in colours if f in set(shown["Flow"])]
    x = alt.X("FY ending:Q", axis=fy_axis(household), scale=alt.Scale(
        domain=[int(household["FY ending"].min()) - 0.6, int(household["FY ending"].max()) + 0.6], nice=False))
    moves = account_flows(daily, result.events)
    additions = (moves.loc[moves["Flow"] == "Savings invested"].groupby("FY ending")["AUD"].sum()
                 .reindex(sorted(household["FY ending"].unique()), fill_value=0.0).reset_index(name="AUD"))
    additions["Period"] = additions["FY ending"].map(period_label)
    y_domain = flow_domain(shown, "AUD", (household["Net change"], additions["AUD"]))
    bars = alt.Chart(shown).mark_bar(size=16).encode(
        x=x, y=alt.Y("sum(AUD):Q", title="AUD per year", axis=alt.Axis(format="$,.0f"),
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
               "is what was **added to outside investments** from your pay that year: it moves money from cash into the "
               "portfolio, so it is drawn as a line rather than a bar, and it stops at retirement. Above zero: take-home salary, "
               "employer and salary-sacrifice contributions into super, and investment returns in good years. Below zero: "
               "spending, income tax, the 15% contributions tax, super fund tax and investment losses in bad years. The black "
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
        rows.append({"Year": period(end_year), "Age at 30 June": age_on(born, date(end_year, 6, 30)),
                     "Taxable income": x["assessment"].taxable_income,
                     "Net tax": x["assessment"].net_tax + x["assessment"].division_293_tax,
                     "Net capital gain": x["assessment"].net_capital_gain,
                     "Concessional contributions": x["concessional_contributions"], "Cap available": x["concessional_cap_available"],
                     "Spending paid": x["spending_paid"], "Shortfall": x["shortfall"],
                     "Pension minimum": x["pension_minimum"] or 0.0, "Pension paid": x["pension_paid"] or 0.0,
                     "Transfer balance": x["transfer_balance"] or 0.0, "Super at 30 June": x["total_super_balance_30_june"],
                     "FY ending": end_year})
    st.subheader("Year by year")
    frame = pd.DataFrame(rows)
    st.dataframe(frame.drop(columns="FY ending"), width="stretch", hide_index=True, height=fit(frame),
                 column_config={"Year": st.column_config.TextColumn("Year (1 July – 30 June)", pinned=True),
                                "Age at 30 June": st.column_config.NumberColumn(format="%d"),
                                **{c: money_column(c) for c in frame.columns if c not in ("Year", "Age at 30 June", "FY ending")}})
    st.caption("Australian tax and super run on financial years from 1 July to 30 June; each row is one of those years. "
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
