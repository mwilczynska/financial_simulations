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

from financial_simulations.retirement.plan import (PlanError, default_plan, load_plan_text, normalize_plan, plan_to_json,
                                                   plan_to_toml, slug)
from financial_simulations.retirement.run_plan import run_plan
from financial_simulations.rules.au.parameters import UnsupportedRule


PLANS_DIR = Path("plans")


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
    st.markdown(f"**{title}** (percent of new money; must total 100)")
    columns = st.columns(max(1, len(assets)))
    weights = {}
    for column, asset in zip(columns, assets):
        with column:
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
    st.subheader("Assets")
    st.caption("Name each asset you hold or might buy. Returns are assumed annual AUD total returns (until AUD market data are added); "
               "the income yield and franked share split each return into taxable distributions.")
    frame = pd.DataFrame(plan["assets"]).rename(columns={"annual_return": "annual_return_%", "income_yield": "income_yield_%",
                                                         "franked_fraction": "franked_%"})
    for column in ("annual_return_%", "income_yield_%", "franked_%"):
        frame[column] = frame[column] * 100
    edited = st.data_editor(frame, num_rows="dynamic", width="stretch", key=key("assets"), column_config={
        "name": st.column_config.TextColumn("Code", help="Letters, digits, underscores", required=True),
        "label": st.column_config.TextColumn("Description"),
        "annual_return_%": st.column_config.NumberColumn("Total return %/yr", format="%.2f"),
        "income_yield_%": st.column_config.NumberColumn("Income yield %/yr", format="%.2f"),
        "franked_%": st.column_config.NumberColumn("Franked %", format="%.0f", min_value=0, max_value=100)})
    plan["assets"] = [{"name": str(r["name"]).strip(), "label": str(r.get("label") or r["name"]),
                       "annual_return": float(r["annual_return_%"] or 0) / 100, "income_yield": float(r["income_yield_%"] or 0) / 100,
                       "franked_fraction": float(r["franked_%"] or 0) / 100}
                      for r in edited.to_dict("records") if isinstance(r.get("name"), str) and r["name"].strip()]
    names = [a["name"] for a in plan["assets"]]
    st.subheader("Outside super")
    a, b = st.columns(2)
    with a:
        plan["outside"]["cash"] = money("Cash today", plan["outside"]["cash"], "cash")
    with b:
        plan["outside"]["cash_buffer"] = money("Cash buffer kept uninvested", plan["outside"]["cash_buffer"], "buffer")
    st.markdown("**Current holdings** (value today, CGT cost base and purchase date)")
    holdings = pd.DataFrame(plan["outside"]["holdings"] or [{"asset": names[0] if names else "", "value": 0.0, "cost_base": 0.0,
                                                             "acquired": "2020-01-01"}])
    holdings["acquired"] = pd.to_datetime(holdings["acquired"]).dt.date
    edited = st.data_editor(holdings, num_rows="dynamic", width="stretch", key=key("holdings"), column_config={
        "asset": st.column_config.SelectboxColumn("Asset", options=names, required=True),
        "value": st.column_config.NumberColumn("Value today", format="%.0f", min_value=0),
        "cost_base": st.column_config.NumberColumn("Cost base", format="%.0f", min_value=0),
        "acquired": st.column_config.DateColumn("Acquired", format="YYYY-MM-DD")})
    plan["outside"]["holdings"] = [{"asset": r["asset"], "value": float(r["value"] or 0), "cost_base": float(r["cost_base"] or 0),
                                    "acquired": r["acquired"].isoformat() if hasattr(r["acquired"], "isoformat") else str(r["acquired"])}
                                   for r in edited.to_dict("records") if r.get("asset") and (r.get("value") or 0) > 0]
    plan["outside"]["weights"] = weights_editor("Outside investment mix", plan["outside"]["weights"], names, "outw")
    st.subheader("Super")
    a, b = st.columns(2)
    with a:
        plan["super"]["balance"] = money("Super balance today", plan["super"]["balance"], "super")
    with b:
        plan["super"]["total_super_balance_prior_30_june"] = money("Total super balance at last 30 June",
                                                                   plan["super"]["total_super_balance_prior_30_june"], "tsb",
                                                                   help="Sets this year's contribution caps.")
    plan["super"]["weights"] = weights_editor("Super investment mix", plan["super"]["weights"], names, "supw")


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
        x=alt.X("Date:T", title=None, axis=alt.Axis(format="%Y", tickCount="year")),
        y=alt.Y("balance:Q", stack="zero", title="AUD (nominal)", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Account:N", sort=[v[0] for v in ACCOUNTS.values()],
                        scale=alt.Scale(domain=[v[0] for v in ACCOUNTS.values()], range=[v[1] for v in ACCOUNTS.values()]),
                        legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), "Account:N", alt.Tooltip("balance:Q", format="$,.0f")],
    ).properties(height=320)


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
            with st.spinner("Running the daily ledger..."):
                st.session_state.result = run_plan(valid)
        except (UnsupportedRule, PlanError, ValueError, ArithmeticError) as exc:
            st.session_state.result = None
            st.error(f"The plan cannot run as specified: {exc}")
    run = st.session_state.result
    if run is None:
        st.info("Press Run plan to simulate. Results are saved to output/plans/<plan-name>/.")
        return
    for note in run.notes:
        st.warning(note)
    daily, annual = run.result.daily, run.result.annual
    shortfall = sum(a["shortfall"] for a in annual)
    tax = sum(a["assessment"].net_tax + a["assessment"].division_293_tax for a in annual)
    compact = lambda v: f"${v / 1e6:,.2f}m" if abs(v) >= 1e6 else f"${v:,.0f}"
    a, b = st.columns(2)
    a.metric("Wealth at start", compact(daily["total"].iloc[0]))
    b.metric(f"Wealth at end ({daily.index[-1].date()})", compact(daily["total"].iloc[-1]))
    a, b = st.columns(2)
    a.metric("Spending shortfall", compact(shortfall))
    b.metric("Personal tax assessed", compact(tax))
    st.subheader("Balances by account")
    st.altair_chart(balances_chart(daily), width="stretch")
    st.subheader("Year by year")
    rows = [{"Year": a["financial_year"], "Taxable income": a["assessment"].taxable_income, "Net tax": round(a["assessment"].net_tax),
             "Minimum CGT": a["assessment"].capital_gains_minimum_tax, "Concessional contributions": round(a["concessional_contributions"]),
             "Cap available": round(a["concessional_cap_available"]), "Pension paid": round(a["pension_paid"] or 0),
             "Spending paid": round(a["spending_paid"]), "Shortfall": round(a["shortfall"]),
             "Super at 30 June": round(a["total_super_balance_30_june"])} for a in annual]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    outstanding = run.result.outstanding
    if outstanding["tax_liabilities"] or outstanding["unassessed_year"]:
        st.caption(f"At the horizon: unpaid tax {[l['financial_year'] for l in outstanding['tax_liabilities']]}; "
                   f"unassessed year {(outstanding['unassessed_year'] or {}).get('financial_year')}.")
    if run.folder:
        st.success(f"Saved to `{run.folder}` (plan.toml, daily.csv, events.csv, annual.json, ledger.png, manifest.json).")
        st.image(str(run.folder / "ledger.png"))
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
