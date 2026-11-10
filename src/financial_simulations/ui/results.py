"""What every results page shares: the run's derived frames, the strategy picker and the plan-in-brief text."""

from datetime import date
from types import SimpleNamespace

import streamlit as st

from financial_simulations.retirement.flows import fold_tax_columns, milestones
from financial_simulations.retirement.outcomes import (full_age_pension_by_year, path_groups, path_outcomes, state_shares,
                                                       yearly_states)
from financial_simulations.retirement.strategy_results import STRATEGY_NAMES
from financial_simulations.rules.au.parameters import load_ruleset
from financial_simulations.rules.au.superannuation import access_date, age_on, birthday
from financial_simulations.ui.state import key, sticky_choice
from financial_simulations.ui.theme import empty_state, page_title


def derived(run):
    """One strategy's outcome tiers, yearly states, path groups and life events, worked out once per run."""
    cache = st.session_state.setdefault("derived", {})
    if id(run) not in cache:
        full_rate = full_age_pension_by_year(run.plan)
        outcomes = path_outcomes(run.retirement_paths, run.retirement_annual, full_rate)
        states = yearly_states(outcomes, run.retirement_annual, full_rate)
        daily = run.result.daily
        born = date.fromisoformat(run.plan["person"]["date_of_birth"])
        annual = fold_tax_columns(run.retirement_annual)
        cache[id(run)] = SimpleNamespace(
            full_rate=full_rate, outcomes=outcomes, states=states, shares=state_shares(states),
            groups=path_groups(outcomes), annual=annual, born=born,
            start=daily.index[0].date(), end=daily.index[-1].date(), end_age=age_on(born, daily.index[-1].date()),
            start_wealth=float(daily["total"].iloc[0]),
            marks=milestones(run.plan, daily.index[0].date(), daily.index[-1].date()),
            pension_from=birthday(born.isoformat(), load_ruleset("2026-27")["age_pension_age"]))
    return cache[id(run)]


def no_results(title):
    page_title(title)
    empty_state("No results yet", "Press <b style='display:inline;font-size:inherit'>Run plan</b> to simulate your plan "
                                  "across many market paths.")


def header(run, title, subtitle):
    """The page title and, when strategies are compared, the strategy picker. Returns the chosen strategy's run."""
    strategies = run.strategies or {run.rule: run}
    if len(strategies) == 1:
        page_title(title, subtitle)
        return run
    left, right = st.columns([1.6, 1], vertical_alignment="center")
    with left:
        page_title(title, subtitle)
    with right:
        rules = list(strategies)
        chosen = st.segmented_control("Spending strategy", rules, format_func=STRATEGY_NAMES.get, required=True,
                                      key=sticky_choice("strategy_pick", rules, rules[0]), width="stretch")
    return strategies[chosen or rules[0]]


def strategy_text(plan):
    """A plain statement of how retirement spending is set and paid."""
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
    return (f"You retire on {retire:%d %B %Y} (age {person['retirement_age']}). Retirement spending starts at {start}. {how}"
            + (f" Limits: {' and '.join(bounds)} a year (today's dollars, rising with inflation)." if bounds else "")
            + f"\n\n**Where it comes from:** cash first, then your outside investments (selling the holdings with the "
            f"smallest taxable gain first, with capital gains tax), then super from {access:%d %B %Y}"
            + (f", with your super moved into an account-based pension on "
               f"{max(birthday(born.isoformat(), pension), access):%d %B %Y} paying at least the legal minimum"
               if pension else "")
            + ". From 67 the means-tested Age Pension adds income when your assets and income are low enough.")


def kept_tabs(name, labels):
    """Tracked tabs whose open tab survives a visit to another page. Only the open tab should be drawn."""
    widget = key(name)
    st.session_state.setdefault("_sticky", set()).add(widget)
    if st.session_state.get(widget) not in labels:
        st.session_state.pop(widget, None)
    return st.tabs(labels, key=widget, on_change="rerun")
