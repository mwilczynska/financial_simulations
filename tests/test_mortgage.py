"""Home loan in the daily ledger and the plan (ADR 0052)."""

from datetime import date

import pandas as pd
import pytest

from financial_simulations.retirement.flows import account_flows, household_flows
from financial_simulations.data.plan_markets import load_plan_markets
from financial_simulations.retirement.ledger import Employment, Mortgage, Parcel, Person, run_ledger
from financial_simulations.retirement.plan import PlanError, build_inputs, default_plan, load_plan_text, normalize_plan, plan_to_toml

from test_ledger import YEARS, market, scenario_with


def _owed(result):
    return result.daily["mortgage"]


def test_required_repayment_is_the_fortnightly_annuity():
    assert Mortgage(260000, 0.0, 10, "2026-07-02").repayment == pytest.approx(1000)
    # $500,000 at 6% over 25 years: r = 0.06 / 26, n = 650 fortnights.
    r, n = 0.06 / 26, 650
    assert Mortgage(500000, 0.06, 25, "2026-07-02").repayment == pytest.approx(500000 * r / (1 - (1 + r) ** -n))
    with pytest.raises(ValueError):
        Mortgage(100000, 0.06, 25, "2026-07-02", extra_share=1.5)


def test_zero_rate_loan_is_repaid_in_equal_fortnightly_instalments_and_wealth_is_net_of_it():
    scenario = scenario_with(Person("1985-01-01"), employment=Employment(104000, "2026-07-02"),
                             mortgage=Mortgage(26000, 0.0, 1, "2026-07-02"))
    result = run_ledger(market(), scenario, YEARS)
    repaid = result.events[result.events["event"] == "mortgage_repayment"]
    assert len(repaid) == 26 and repaid["amount"].tolist() == pytest.approx([1000] * 26)
    assert _owed(result).iloc[:2].tolist() == pytest.approx([26000, 25000])  # the first repayment is on 2 July
    assert _owed(result).iloc[-1] == 0 and result.outstanding["mortgage"] == 0
    daily = result.daily
    assert daily["total"].to_numpy() == pytest.approx(
        (daily["cash"] + daily["outside_investments"] + daily["accumulation"] + daily["pension"] - daily["mortgage"]).to_numpy())
    # Salary not needed for the loan is invested: $104,000 of pay less $26,000 of repayments.
    assert daily["outside_investments"].iloc[-1] == pytest.approx(78000)
    assert daily["mortgage_interest"].sum() == 0


def test_interest_accrues_daily_is_charged_monthly_and_the_annuity_clears_the_loan():
    scenario = scenario_with(Person("1985-01-01"), employment=Employment(150000, "2026-07-02"),
                             mortgage=Mortgage(100000, 0.06, 1, "2026-07-02"))
    result = run_ledger(market(), scenario, YEARS)
    daily = result.daily
    # On the opening day (before any repayment) a day's interest at 6% / 365 is owed.
    first_day = daily.iloc[0]
    assert first_day["mortgage_interest"] == pytest.approx(100000 * 0.06 / 365)
    # 26 annuity payments at r = 6% / 26 clear the loan; daily accrual charged monthly differs from the annuity's
    # fortnightly compounding by a few dollars, so the final instalment is cut to what is owed.
    repaid = result.events[result.events["event"] == "mortgage_repayment"]
    assert _owed(result).iloc[-1] < 50
    assert repaid["amount"].sum() + _owed(result).iloc[-1] == pytest.approx(100000 + daily["mortgage_interest"].sum())
    # Interest paid in the year is about 6% on the average balance (a little over half the loan).
    assert 2500 < daily["mortgage_interest"].sum() < 3500


def test_extra_repayments_take_the_chosen_share_of_savings_until_the_loan_is_gone():
    def run(share):
        scenario = scenario_with(Person("1985-01-01"), employment=Employment(150000, "2026-07-02"), annual_spending=40000,
                                 mortgage=Mortgage(90000, 0.06, 25, "2026-07-02", extra_share=share))
        return run_ledger(market(), scenario, YEARS)

    none, half, everything = run(0.0), run(0.5), run(1.0)
    assert _owed(everything).iloc[-1] == 0 and _owed(half).iloc[-1] > 0 and _owed(none).iloc[-1] > _owed(half).iloc[-1]
    assert everything.daily["mortgage_interest"].sum() < half.daily["mortgage_interest"].sum() < none.daily["mortgage_interest"].sum()
    # With everything going to the loan nothing is invested until it is cleared, and investing resumes after.
    cleared = everything.daily.index[everything.daily["mortgage"] <= 0][0]
    assert everything.daily.loc[everything.daily.index < cleared, "outside_investments"].max() == 0
    assert everything.daily["outside_investments"].iloc[-1] > 0
    # Half: each extra repayment equals the amount invested the same day.
    events = half.events
    extras = events[events["event"] == "mortgage_extra_repayment"].groupby("date")["amount"].sum()
    bought = events[(events["event"] == "buy") & (events["account"] == "outside")].groupby("date")["amount"].sum()
    assert extras.to_numpy() == pytest.approx(bought.loc[extras.index].to_numpy())
    # Repaying the loan sooner leaves more net wealth with a zero market return: the interest saved.
    assert everything.daily["total"].iloc[-1] > none.daily["total"].iloc[-1]


def test_a_repayment_that_cannot_be_paid_is_a_shortfall_and_stays_on_the_loan():
    scenario = scenario_with(Person("1985-01-01"), outside_cash=3000, mortgage=Mortgage(100000, 0.06, 25, "2026-07-01"))
    result = run_ledger(market(), scenario, YEARS)
    required = Mortgage(100000, 0.06, 25, "2026-07-01").repayment
    assert result.daily["mortgage_repaid"].sum() == pytest.approx(3000)
    assert result.daily["shortfall"].sum() == pytest.approx(27 * required - 3000)
    assert result.annual[0]["shortfall"] == pytest.approx(27 * required - 3000)
    # Nothing was repaid beyond the cash, so the balance grew by the year's interest.
    assert _owed(result).iloc[-1] == pytest.approx(97000 + result.daily["mortgage_interest"].sum())


def test_money_in_and_out_reconciles_net_wealth_and_the_loan_is_an_account():
    scenario = scenario_with(Person("1980-01-01"), outside_cash=2000, cash_buffer=1000,
                             outside_parcels=(Parcel("GL", 50000, 40000, "2020-01-01"),),
                             employment=Employment(140000, "2026-07-02"), annual_spending=50000,
                             mortgage=Mortgage(300000, 0.055, 20, "2026-07-02", extra_share=0.3))
    result = run_ledger(market(seed=11), scenario, YEARS)
    household = household_flows(result.daily)
    for _, year in household.groupby("FY ending"):
        assert year["AUD"].sum() == pytest.approx(year["Net change"].iloc[0], abs=1e-4)
    interest = household.loc[household["Flow"] == "Mortgage interest", "AUD"].sum()
    assert interest == pytest.approx(-result.daily["mortgage_interest"].sum())
    loan = account_flows(result.daily, result.events).query("Account == 'Mortgage'").set_index("Flow")["AUD"]
    assert loan["Interest charged"] + loan["Repaid, net of redraws"] == pytest.approx(result.daily["mortgage"].iloc[-1] - 300000)


def test_the_age_pension_assets_test_counts_assets_without_deducting_the_home_loan():
    person = Person("1958-06-01", retirement_date="2020-01-01", homeowner=True)
    scenario = scenario_with(person, outside_cash=500, outside_parcels=(Parcel("GL", 500000, 500000, "2020-01-01"),),
                             annual_spending=40000, age_pension=True, mortgage=Mortgage(100000, 0.06, 10, "2026-07-01"))
    result = run_ledger(market(), scenario, YEARS)
    first = result.events[result.events["event"] == "age_pension"].iloc[0]
    before = result.daily.loc[pd.Timestamp(first["date"]) - pd.Timedelta(days=1)]
    assert first["assessed_assets"] == pytest.approx(before["total"] + before["mortgage"])


def test_plan_mortgage_section_validates_round_trips_and_builds_the_ledger_loan(processed_fixture):
    plan = default_plan()
    processed_fixture = load_plan_markets(plan["assets"], processed_fixture)
    assert plan["mortgage"] == {"balance": 0.0, "interest_rate": 0.06, "years": 25.0, "extra_share": 0.0}
    assert build_inputs(plan, market=processed_fixture)[1].mortgage is None
    plan["mortgage"].update(balance=400000.0, interest_rate=0.058, years=22.0, extra_share=0.25)
    assert load_plan_text(plan_to_toml(plan)) == normalize_plan(plan)
    scenario = build_inputs(plan, market=processed_fixture)[1]
    assert scenario.mortgage == Mortgage(400000.0, 0.058, 22.0, scenario.employment.first_payday, 0.25)
    with pytest.raises(PlanError, match="mortgage.balance"):
        normalize_plan({**plan, "person": {**plan["person"], "homeowner": False}})
    with pytest.raises(PlanError, match="mortgage.extra_share"):
        normalize_plan({**plan, "mortgage": {**plan["mortgage"], "extra_share": 2}})
    without_salary = {**plan, "employment": {**plan["employment"], "annual_salary": 0.0, "salary_sacrifice_per_year": 0.0,
                                             "salary_sacrifice_percent": 0.0}}
    assert build_inputs(without_salary, market=processed_fixture)[1].mortgage.first_repayment == date(2026, 7, 1)


def test_extra_repayments_can_be_redrawn_for_spending_so_paying_down_only_saves_interest():
    def run(share):
        scenario = scenario_with(Person("1985-01-01"), employment=Employment(150000, "2026-07-02"), annual_spending=40000,
                                 mortgage=Mortgage(90000, 0.06, 25, "2026-07-02", extra_share=share))
        return run_ledger(market(), scenario, YEARS)

    none, everything = run(0.0), run(1.0)
    # With no cash buffer every spare dollar goes off the loan, so monthly spending redraws it instead of falling short.
    assert (everything.events["event"] == "mortgage_redraw").any()
    assert everything.daily["shortfall"].sum() == pytest.approx(none.daily["shortfall"].sum())  # only the first month
    assert everything.daily["spending_paid"].sum() == pytest.approx(none.daily["spending_paid"].sum())
    # With a zero market return the only difference in net wealth is the interest saved.
    saved = none.daily["mortgage_interest"].sum() - everything.daily["mortgage_interest"].sum()
    assert everything.daily["total"].iloc[-1] - none.daily["total"].iloc[-1] == pytest.approx(saved)


def test_largest_fall_in_wealth_is_measured_before_loans():
    from financial_simulations.retirement.paths import largest_fall

    # Assets 100 -> 150 -> 90 -> 200 against a loan of 140, so total wealth is -40, 10, -50, 60.
    assets = pd.Series([100.0, 150.0, 90.0, 200.0])
    daily = pd.DataFrame({"total": assets - 140.0, "mortgage": 140.0, "property_loan": 0.0})
    assert largest_fall(daily) == pytest.approx(90 / 150 - 1)  # not -50 / 10 - 1 = -600%
    # Without a loan it is the fall of total wealth, and a path that only rises has no fall.
    assert largest_fall(pd.DataFrame({"total": assets})) == pytest.approx(-0.4)
    assert largest_fall(pd.DataFrame({"total": [0.0, 0.0, 5.0, 6.0]})) == 0.0
