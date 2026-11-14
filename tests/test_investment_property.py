"""Investment property in the daily ledger and the plan (ADR 0054)."""

from math import floor

import pandas as pd
import pytest

from financial_simulations.data.plan_markets import load_plan_markets
from financial_simulations.retirement.flows import account_flows, fold_taxes, household_flows
from financial_simulations.retirement.ledger import (Employment, InvestmentProperty, Mortgage, Parcel, Person, SpendingRule,
                                                     run_ledger)
from financial_simulations.retirement.plan import PlanError, build_inputs, default_plan, load_plan_text, normalize_plan, plan_to_toml
from financial_simulations.rules.au.age_pension import fortnightly_rate
from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets

from test_ledger import RULES, YEARS, market, scenario_with


def example(**changes):
    """$750,000 property at $650 a week with $500,000 owed at 6% over 25 years (the methodology example)."""
    terms = dict(value=750000, weekly_rent=650, loan=Mortgage(500000, 0.06, 25, "2026-07-02"))
    return InvestmentProperty(**{**terms, **changes})


def worker(prop=None, **kwargs):
    kwargs.setdefault("employment", Employment(160000, "2026-07-02"))
    kwargs.setdefault("annual_spending", 75000)
    return scenario_with(Person("1980-01-01"), outside_cash=20000, investment_property=prop, **kwargs)


def test_rent_costs_growth_and_net_wealth():
    result = run_ledger(market(), worker(example()), YEARS)
    daily = result.daily
    assert daily["rent"].sum() == pytest.approx(12 * 650 * 52 / 12 * 0.9)  # $30,420: rent less 10%
    # The value grows by 4% a year in twelve equal monthly steps; costs are 1.5% a year of each month's opening value.
    assert daily["property_value"].iloc[-1] == pytest.approx(780000)
    month_values = 750000 * 1.04 ** (pd.RangeIndex(12) / 12)
    assert daily["property_costs"].sum() == pytest.approx(0.015 / 12 * month_values.to_numpy().sum())
    assert daily["property_growth"].sum() == pytest.approx(30000)
    repaid = result.events[result.events["event"] == "property_loan_repayment"]
    assert repaid["amount"].tolist() == pytest.approx([Mortgage(500000, 0.06, 25, "2026-07-02").repayment] * 26)
    assets = daily[["cash", "outside_investments", "accumulation", "pension"]].sum(axis=1)
    assert daily["spendable"].to_numpy() == pytest.approx((assets - daily["mortgage"]).to_numpy())
    assert daily["total"].to_numpy() == pytest.approx(
        (daily["spendable"] + daily["property_value"] - daily["property_loan"]).to_numpy())
    assert result.daily["shortfall"].sum() == 0


def test_money_in_and_out_reconciles_and_the_property_folds_into_one_flow():
    result = run_ledger(market(seed=3), worker(example(), mortgage=Mortgage(200000, 0.055, 20, "2026-07-02")), YEARS)
    household = household_flows(result.daily)
    for _, year in household.groupby("FY ending"):
        assert year["AUD"].sum() == pytest.approx(year["Net change"].iloc[0], abs=1e-4)
    folded = fold_taxes(household)
    assert "Investment property" in set(folded["Flow"]) and "Rent" not in set(folded["Flow"])
    assert folded["AUD"].sum() == pytest.approx(household["AUD"].sum())
    loan = account_flows(result.daily, result.events).query("Account == 'Investment loan'").set_index("Flow")["AUD"]
    assert loan["Interest charged"] + loan["Repaid"] == pytest.approx(result.daily["property_loan"].iloc[-1] - 500000)


def test_a_rental_loss_is_carried_forward_unless_it_may_offset_salary():
    none = run_ledger(market(), worker(), YEARS).annual[0]
    quarantined = run_ledger(market(), worker(example()), YEARS)
    offset = run_ledger(market(), worker(example(losses_offset_other_income=True)), YEARS).annual[0]
    year = quarantined.annual[0]
    loss = year["property_interest"] + year["property_costs"] - year["rent"]
    assert loss > 10000  # interest about $29,700 and costs about $11,500 against $30,420 of rent
    assert year["rental_loss_carried_forward"] == pytest.approx(loss) and year["rental_income_assessed"] == 0
    assert quarantined.outstanding["rental_loss_carried_forward"] == pytest.approx(loss)
    # Quarantined, the loss leaves salary taxed as without the property; offset, it reduces taxable income.
    assert year["assessment"].taxable_income == none["assessment"].taxable_income
    assert offset["assessment"].taxable_income == floor(none["assessment"].lines["assessable_income"]
                                                        - none["assessment"].lines["deductions"] - loss)
    assert offset["assessment"].net_tax < year["assessment"].net_tax


def test_a_carried_loss_reduces_later_rental_profit():
    years = project_rulesets(RULES, "2027-28", ProjectionAssumptions(0.025, 0.035))
    # Rent nearly doubles on 1 July 2027, turning the first year's loss into a profit.
    prop = example(rent_growth=0.9)
    result = run_ledger(market(end="2028-06-30"), worker(prop), years)
    first, second = result.annual
    carried = first["rental_loss_carried_forward"]
    profit = second["rent"] - second["property_interest"] - second["property_costs"]
    assert carried > 0 and profit > carried
    assert second["rental_loss_brought_forward"] == pytest.approx(carried)
    assert second["rental_income_assessed"] == pytest.approx(profit - carried)
    assert second["rental_loss_carried_forward"] == 0


def test_spending_rules_and_withdrawal_rates_leave_the_property_out():
    def run(prop):
        scenario = scenario_with(Person("1970-01-01", retirement_date="2026-07-01"), outside_cash=5000,
                                 outside_parcels=(Parcel("GL", 800000, 800000, "2020-01-01"),), annual_spending=40000,
                                 spending_rule=SpendingRule("percent", start_rate=0.04), investment_property=prop)
        return run_ledger(market(), scenario, YEARS)

    without, with_property = run(None), run(example(loan=None, weekly_rent=0, running_costs=0.0))
    start = lambda result: result.events[result.events["event"] == "spending_rule"].iloc[0]
    assert start(with_property)["wealth"] == pytest.approx(start(without)["wealth"]) == pytest.approx(805000)
    assert start(with_property)["amount"] == pytest.approx(0.04 * 805000)
    assert with_property.daily["total"].iloc[0] == pytest.approx(with_property.daily["spendable"].iloc[0] + 750000)


def test_unpaid_property_costs_and_repayments_are_shortfalls():
    scenario = scenario_with(Person("1985-01-01"), outside_cash=1000, investment_property=example(weekly_rent=0))
    result = run_ledger(market(), scenario, YEARS)
    assert result.daily["shortfall"].sum() > 40000  # a year of repayments and costs with almost no cash
    purposes = set(result.events.loc[result.events["event"] == "shortfall", "purpose"])
    assert {"property_loan", "property_costs"} <= purposes


def test_interest_only_repayments_then_the_annuity_over_the_rest_of_the_term():
    loan = Mortgage(400000, 0.06, 25, "2026-07-02", interest_only_years=0.5)
    assert loan.interest_only_repayment == pytest.approx(400000 * 0.06 / 26)
    r, n = 0.06 / 26, 650 - 13
    assert loan.repayment == pytest.approx(400000 * r / (1 - (1 + r) ** -n))
    result = run_ledger(market(), worker(example(loan=loan)), YEARS)
    paid = result.events.loc[result.events["event"] == "property_loan_repayment", "amount"].tolist()
    assert paid[:13] == pytest.approx([loan.interest_only_repayment] * 13)
    assert paid[13:] == pytest.approx([loan.repayment] * 13)
    with pytest.raises(ValueError):
        Mortgage(400000, 0.06, 1, "2026-07-02", interest_only_years=1)
    with pytest.raises(ValueError):
        InvestmentProperty(500000, 500, Mortgage(100000, 0.06, 25, "2026-07-02", extra_share=0.5))


def test_the_age_pension_counts_equity_and_net_rent():
    person = Person("1958-06-01", retirement_date="2020-01-01", homeowner=True)
    prop = example(loan=Mortgage(200000, 0.06, 10, "2026-07-01"))
    scenario = scenario_with(person, outside_cash=500, outside_parcels=(Parcel("GL", 100000, 100000, "2020-01-01"),),
                             annual_spending=30000, age_pension=True, investment_property=prop)
    result = run_ledger(market(), scenario, YEARS)
    first = result.events[result.events["event"] == "age_pension"].iloc[0]
    before = result.daily.loc[pd.Timestamp(first["date"]) - pd.Timedelta(days=1)]
    equity = before["property_value"] - before["property_loan"]
    assert first["assessed_assets"] == pytest.approx(before["spendable"] + equity)
    # Net rent at the current rent, costs and interest is income, on top of deemed income.
    deemed = fortnightly_rate(0.0, before["spendable"], 0.0, RULES).assessed_income
    net_rent = (650 * 52 * 0.9 - 0.015 * before["property_value"] - 0.06 * before["property_loan"]) / 26
    assert first["assessed_income"] == pytest.approx(deemed + net_rent)


def test_plan_section_validates_round_trips_and_builds_the_property(processed_fixture):
    plan = default_plan()
    processed_fixture = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    assert plan["investment_property"]["value"] == 0.0
    assert build_inputs(plan, market=processed_fixture)[1].investment_property is None
    plan["investment_property"].update(value=750000.0, weekly_rent=650.0, loan=500000.0)
    assert load_plan_text(plan_to_toml(plan)) == normalize_plan(plan)
    scenario = build_inputs(plan, market=processed_fixture)[1]
    prop = scenario.investment_property
    assert prop == InvestmentProperty(750000.0, 650.0, Mortgage(500000.0, 0.06, 25.0, scenario.employment.first_payday),
                                      growth=0.04, running_costs=0.015, rent_kept=0.9,
                                      rent_growth=plan["assumptions"]["cpi_annual"])
    with pytest.raises(PlanError, match="investment_property.value"):
        normalize_plan({**plan, "investment_property": {**plan["investment_property"], "value": 0.0}})
    with pytest.raises(PlanError, match="interest_only_years"):
        normalize_plan({**plan, "investment_property": {**plan["investment_property"], "interest_only_years": 12.0,
                                                       "years": 10.0}})
