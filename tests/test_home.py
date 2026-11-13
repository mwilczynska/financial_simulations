"""The home's value and running costs, rent paid, and moving into an investment property (ADR 0055)."""

import pandas as pd
import pytest

from financial_simulations.data.plan_markets import load_plan_markets
from financial_simulations.retirement.flows import fold_taxes, household_flows
from financial_simulations.retirement.ledger import (Employment, Home, InvestmentProperty, Mortgage, Parcel, Person,
                                                     run_ledger)
from financial_simulations.retirement.plan import PlanError, build_inputs, default_plan, load_plan_text, normalize_plan, plan_to_toml
from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets

from test_ledger import RULES, YEARS, market, scenario_with


def worker(person=None, **kwargs):
    kwargs.setdefault("employment", Employment(160000, "2026-07-02"))
    kwargs.setdefault("annual_spending", 60000)
    return scenario_with(person or Person("1980-01-01"), outside_cash=20000, **kwargs)


def reconciles(result):
    for _, year in household_flows(result.daily).groupby("FY ending"):
        assert year["AUD"].sum() == pytest.approx(year["Net change"].iloc[0], abs=1e-4)


def test_home_costs_are_paid_before_spending_and_the_home_is_in_no_wealth_total():
    result = run_ledger(market(), worker(home=Home(1000000, 0.01, 0.04)), YEARS)
    daily = result.daily
    months = 1000000 * 1.04 ** (pd.RangeIndex(12) / 12)
    assert daily["home_costs"].sum() == pytest.approx(0.01 / 12 * months.to_numpy().sum())
    assert daily["home_value"].iloc[-1] == pytest.approx(1040000)
    assets = daily[["cash", "outside_investments", "accumulation", "pension"]].sum(axis=1)
    assert daily["total"].to_numpy() == pytest.approx(assets.to_numpy())
    reconciles(result)
    assert "Home" in set(fold_taxes(household_flows(result.daily))["Flow"])
    with pytest.raises(ValueError):
        run_ledger(market(), worker(Person("1980-01-01", homeowner=False), home=Home(500000)), YEARS)


def test_rent_paid_is_a_monthly_need_rising_each_july():
    years = project_rulesets(RULES, "2027-28", ProjectionAssumptions(0.03, 0.035))
    renter = Person("1980-01-01", homeowner=False)
    result = run_ledger(market(end="2028-06-30"), worker(renter, rent_paid_weekly=600, rent_paid_growth=0.03), years)
    paid = result.events[result.events["event"] == "rent_paid"]["amount"].to_numpy()
    assert paid[:12] == pytest.approx([600 * 52 / 12] * 12) and paid[12:] == pytest.approx([600 * 52 / 12 * 1.03] * 12)
    reconciles(result)
    with pytest.raises(ValueError):
        run_ledger(market(), worker(rent_paid_weekly=600), YEARS)  # a homeowner pays no rent


def test_moving_into_the_investment_property_makes_it_the_home():
    renter = Person("1980-01-01", homeowner=False)
    prop = InvestmentProperty(800000, 700, Mortgage(400000, 0.06, 25, "2026-07-02"), move_in="2027-01-01",
                              home_running_costs=0.01)
    result = run_ledger(market(), worker(renter, investment_property=prop, rent_paid_weekly=500), YEARS)
    daily, events = result.daily, result.events
    moved = pd.Timestamp("2027-01-01")
    before, after = daily.loc[daily.index < moved], daily.loc[daily.index >= moved]
    # Tenants' rent and the rent you pay stop; the home's running costs start.
    assert before["rent"].sum() > 0 and after["rent"].sum() == 0
    assert before["rent_paid"].sum() == pytest.approx(6 * 500 * 52 / 12) and after["rent_paid"].sum() == 0
    assert before["home_costs"].sum() == 0 and after["home_costs"].sum() > 0
    # The loan carries on as the home loan, and the value as the home's.
    owed = daily["property_loan"].loc[moved - pd.Timedelta(days=1)]
    assert daily.loc[moved, "property_loan"] == 0 and daily.loc[moved, "mortgage"] == pytest.approx(owed, rel=1e-3)
    assert daily.loc[moved, "home_value"] == pytest.approx(daily["property_value"].loc[moved - pd.Timedelta(days=1)])
    assert after["property_value"].max() == 0 and after["property_interest"].sum() == 0
    assert after["mortgage_interest"].sum() > 0
    # 26 fortnightly repayments in all: as the investment loan before the move, as the home loan after.
    kinds = events.loc[events["event"].isin(("property_loan_repayment", "mortgage_repayment")), "event"]
    assert len(kinds) == 26 and (kinds == "mortgage_repayment").sum() == 12
    # The home leaves total wealth on the move, and money in and out still adds up.
    assert daily.loc[moved, "property_moved_in"] == pytest.approx(daily.loc[moved, "home_value"])
    reconciles(result)


def test_after_moving_in_the_age_pension_uses_the_homeowner_limits_and_ignores_the_home():
    person = Person("1958-06-01", retirement_date="2020-01-01", homeowner=False)
    prop = InvestmentProperty(900000, 600, None, move_in="2026-08-01")
    scenario = scenario_with(person, outside_cash=500, outside_parcels=(Parcel("GL", 200000, 200000, "2020-01-01"),),
                             annual_spending=30000, age_pension=True, investment_property=prop)
    result = run_ledger(market(), scenario, YEARS)
    paid = result.events[result.events["event"] == "age_pension"]
    early = paid[pd.to_datetime(paid["date"]) < pd.Timestamp("2026-08-01")]
    late = paid[pd.to_datetime(paid["date"]) > pd.Timestamp("2026-08-01")]
    assert (early["assessed_assets"] > 900000).all()  # the let property counted
    assert (late["assessed_assets"] < 250000).all()  # the home does not
    assert late["amount"].iloc[0] > 0


def test_plan_home_rent_and_move_in_validate_round_trip_and_build(processed_fixture):
    plan = default_plan()
    processed_fixture = load_plan_markets(plan["assets"], processed_fixture)
    assert plan["home"] == {"value": 0.0, "running_costs": 0.01, "growth": 0.04} and plan["person"]["weekly_rent"] == 0
    plan["home"]["value"] = 900000.0
    assert load_plan_text(plan_to_toml(plan)) == normalize_plan(plan)
    assert build_inputs(plan, market=processed_fixture)[1].home == Home(900000.0, 0.01, 0.04)
    with pytest.raises(PlanError, match="home.value"):
        normalize_plan({**plan, "person": {**plan["person"], "homeowner": False}})
    renter = {**plan, "home": {**plan["home"], "value": 0.0},
              "person": {**plan["person"], "homeowner": False, "weekly_rent": 550.0},
              "investment_property": {**plan["investment_property"], "value": 700000.0, "weekly_rent": 600.0,
                                      "move_in_date": "2031-07-01"}}
    assert load_plan_text(plan_to_toml(renter)) == normalize_plan(renter)
    scenario = build_inputs(renter, market=processed_fixture)[1]
    assert scenario.rent_paid_weekly == 550 and scenario.investment_property.move_in.isoformat() == "2031-07-01"
    with pytest.raises(PlanError, match="weekly_rent"):
        normalize_plan({**renter, "person": {**renter["person"], "homeowner": True}})
    with pytest.raises(PlanError, match="move_in_date"):
        normalize_plan({**renter, "investment_property": {**renter["investment_property"], "move_in_date": "2026-07-01"}})
