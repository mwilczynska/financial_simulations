from datetime import date

import numpy as np
import pandas as pd
import pytest

from financial_simulations.markets.path import MarketPath
from financial_simulations.retirement.ledger import (AssetIncome, Employment, LedgerScenario, Parcel, Pension, Person,
                                                     run_ledger)
from financial_simulations.rules.au.parameters import UnsupportedRule, load_ruleset
from financial_simulations.rules.au.superannuation import add_business_days
from financial_simulations.rules.au.tax import IncomeYear, assess


RULES = load_ruleset("2026-27")
YEARS = {"2026-27": RULES}


def scenario_with(*args, **kwargs):
    kwargs.setdefault("outside_weights", {"GL": 1.0})
    kwargs.setdefault("super_weights", {"GL": 1.0})
    return LedgerScenario(*args, **kwargs)


def market(start="2026-07-01", end="2027-06-30", returns=0.0, assets=("AU", "GL"), seed=None):
    dates = tuple(pd.bdate_range(start, end).date)
    values = np.full((len(dates) - 1, len(assets)), returns)
    if seed is not None:
        values = np.random.default_rng(seed).normal(0.0004, 0.01, values.shape)
    return MarketPath(dates, assets, values, "AUD")


def test_salary_super_guarantee_timing_contributions_tax_and_assessment():
    result = run_ledger(market(), scenario_with(Person("1985-01-01"), super_units={"GL": 100000},
                                                 employment=Employment(104000, "2026-07-02")), YEARS)
    events = result.events
    salary = events[events["event"] == "salary"]
    contributions = events[events["event"] == "concessional_contribution"]
    assert len(salary) == 26 and salary["amount"].sum() == pytest.approx(104000)
    # Each payday's $480 SG reaches the fund 7 business days later, less 15% contributions tax.
    expected = [add_business_days(d, 7) for d in salary["date"]]
    assert list(contributions["date"]) == expected
    assert contributions["amount"].sum() == pytest.approx(26 * 480)
    assert result.daily["accumulation"].iloc[-1] == pytest.approx(100000 + 26 * 408)
    annual = result.annual[0]
    reference = assess(IncomeYear(labour_income=104000, low_tax_contributions=12480), RULES)
    assert annual["assessment"].net_tax == pytest.approx(reference.net_tax)
    assert result.outstanding["tax_liabilities"] == [{"due": "2027-10-31", "amount": pytest.approx(reference.net_tax),
                                                      "financial_year": "2026-27"}]
    assert result.outstanding["unused_concessional"] == {"2026-27": pytest.approx(32500 - 12480)}
    # Salary above the zero cash buffer is invested in new parcels on each payday.
    assert result.daily["outside_investments"].iloc[-1] == pytest.approx(104000)


def test_late_june_contributions_fall_in_the_next_financial_year():
    result = run_ledger(market(), scenario_with(Person("1985-01-01"), employment=Employment(104000, "2026-07-09")), YEARS)
    assert result.annual[0]["concessional_contributions"] == pytest.approx(25 * 480)
    assert result.outstanding["pending_contributions"] == [{"due": "2027-07-05", "amount": pytest.approx(480)}]


def test_account_based_pension_minimum_paid_monthly_and_surplus_invested():
    scenario = scenario_with(Person("1965-03-01", retirement_date="2025-12-31"), super_units={"GL": 500000},
                              pension=Pension("2026-07-01"))
    result = run_ledger(market(), scenario, YEARS)
    annual = result.annual[0]
    assert annual["pension_minimum"] == 20000 and annual["pension_paid"] == pytest.approx(20000)
    assert annual["transfer_balance"] == 500000
    payments = result.events[result.events["event"] == "pension_payment"]
    assert len(payments) == 12 and payments["amount"].iloc[0] == pytest.approx(20000 / 12)
    assert result.daily["pension"].iloc[-1] == pytest.approx(480000)
    assert result.daily["outside_investments"].iloc[-1] == pytest.approx(20000)
    assert annual["assessment"].taxable_income == 0  # tax-free pension at 61


def test_mid_year_pension_commencement_is_pro_rated():
    scenario = scenario_with(Person("1965-03-01", retirement_date="2025-12-31"), super_units={"GL": 250000},
                              pension=Pension("2027-01-01"))
    annual = run_ledger(market(), scenario, YEARS).annual[0]
    assert annual["pension_minimum"] == 4960  # $10,000 x 181/365 = $4,958.90, rounded to $10
    assert annual["pension_paid"] == pytest.approx(4960)


def test_bridge_shortfall_when_super_is_preserved_and_spending_rolls_to_trading_days():
    scenario = scenario_with(Person("1980-05-01", retirement_date="2026-06-30"), outside_cash=10000,
                              super_units={"GL": 300000}, annual_spending=24000)
    result = run_ledger(market(), scenario, YEARS)
    assert result.annual[0]["spending_paid"] == pytest.approx(10000)
    assert result.annual[0]["shortfall"] == pytest.approx(14000)
    assert not result.daily["super_accessible"].any()
    assert result.daily["accumulation"].iloc[-1] == pytest.approx(300000)
    spending = result.events[result.events["event"] == "spending"].set_index("scheduled")
    assert spending.loc["2026-08-01", "date"] == date(2026, 8, 3)  # Saturday -> Monday


def test_accessible_accumulation_funds_spending_after_outside_assets():
    scenario = scenario_with(Person("1965-03-01", retirement_date="2025-12-31"), outside_cash=3000,
                              super_units={"GL": 100000}, annual_spending=12000)
    result = run_ledger(market(), scenario, YEARS)
    assert result.annual[0]["shortfall"] == 0
    assert result.events[result.events["event"] == "lump_sum"]["amount"].sum() == pytest.approx(9000)
    assert result.daily["accumulation"].iloc[-1] == pytest.approx(91000)


def test_franked_distributions_preserve_total_return_and_refund_credits():
    scenario = scenario_with(Person("1985-01-01"), outside_parcels=(Parcel("AU", 100000, 100000, "2026-07-01"),),
                              outside_weights={"AU": 1.0}, income={"AU": AssetIncome(0.04, 1.0)})
    result = run_ledger(market(), scenario, YEARS)
    distributions = result.events[(result.events["event"] == "distribution")]
    assert distributions["amount"].sum() == pytest.approx(4000)
    assert result.daily["total"].iloc[-1] == pytest.approx(100000)
    assessment = result.annual[0]["assessment"]
    assert assessment.franking_offset == pytest.approx(4000 * 0.3 / 0.7)
    assert assessment.net_tax == pytest.approx(-4000 * 0.3 / 0.7)


def test_outside_sales_realise_discounted_gains_and_reduce_cost_base():
    scenario = scenario_with(Person("1985-01-01"), outside_parcels=(Parcel("AU", 50000, 25000, "2020-01-01"),),
                              annual_spending=12000)
    result = run_ledger(market(), scenario, YEARS)
    sales = result.events[result.events["event"] == "sale"]
    assert len(sales) == 12 and sales["gain"].sum() == pytest.approx(6000)
    assert result.annual[0]["assessment"].net_capital_gain == pytest.approx(3000)
    assert result.daily["outside_investments"].iloc[-1] == pytest.approx(38000)


def test_fund_tax_on_accumulation_income_and_pension_franking_refund():
    accumulation = run_ledger(market(), scenario_with(Person("1985-01-01"), super_units={"GL": 200000},
                                                       income={"GL": AssetIncome(0.04)}), YEARS)
    assert accumulation.annual[0]["accumulation_tax"] == pytest.approx(1200)
    assert accumulation.daily["accumulation"].iloc[-1] == pytest.approx(198800)
    pension = run_ledger(market(), scenario_with(Person("1965-03-01", retirement_date="2025-12-31"),
                                                  super_units={"AU": 200000}, super_weights={"AU": 1.0},
                                                  income={"AU": AssetIncome(0.04, 1.0)}, pension=Pension("2026-07-01")), YEARS)
    events = pension.events
    paid = events[(events["event"] == "distribution") & (events["account"] == "pension")]["amount"].sum()
    # Retirement-phase earnings are exempt, so the fund refunds every franking credit to the pension.
    assert events[events["event"] == "fund_tax"]["amount"].iloc[0] == pytest.approx(-paid * 0.3 / 0.7)
    assert pension.annual[0]["accumulation_tax"] == 0
    assert pension.daily["pension"].iloc[-1] == pytest.approx(200000 - 8000 + paid * 0.3 / 0.7)


def test_random_market_ledger_reconciles_and_buy_and_hold_compounds_exactly():
    path = market(seed=4)
    result = run_ledger(path, scenario_with(Person("1985-01-01"), super_units={"GL": 100000}), YEARS)
    assert result.daily["accumulation"].iloc[-1] == pytest.approx(100000 * np.prod(1 + path.returns[:, 1]), rel=1e-12)
    busy = scenario_with(Person("1966-03-01", retirement_date="2026-09-30"), outside_cash=5000, cash_buffer=2000,
                          outside_parcels=(Parcel("AU", 40000, 30000, "2019-01-01"),), outside_weights={"AU": 0.6, "GL": 0.4},
                          super_units={"GL": 400000}, income={"AU": AssetIncome(0.04, 0.7), "GL": AssetIncome(0.02)},
                          employment=Employment(150000, "2026-07-02", 400), annual_spending=70000,
                          pension=Pension("2026-10-01", 300000))
    run_ledger(path, busy, YEARS)  # raises ArithmeticError if any day fails to reconcile


def test_non_concessional_bring_forward_and_cap_failures():
    scenario = scenario_with(Person("1985-01-01"), outside_cash=500000, cash_buffer=500000,
                              non_concessional=(("2026-08-03", 200000),), super_units={"GL": 100000})
    result = run_ledger(market(), scenario, YEARS)
    assert result.annual[0]["non_concessional_contributions"] == 200000
    over = scenario_with(Person("1985-01-01"), outside_cash=500000, cash_buffer=500000,
                          non_concessional=(("2026-08-03", 400000),))
    with pytest.raises(UnsupportedRule, match="non-concessional"):
        run_ledger(market(), over, YEARS)
    sacrifice = scenario_with(Person("1985-01-01"), employment=Employment(260000, "2026-07-02", 2000))
    with pytest.raises(UnsupportedRule, match="Concessional"):
        run_ledger(market(), sacrifice, YEARS)


def test_unsupported_horizons_access_and_currency_fail_explicitly():
    with pytest.raises(UnsupportedRule, match="2027-28"):
        run_ledger(market(end="2027-07-15"), scenario_with(Person("1985-01-01")), YEARS)
    with pytest.raises(UnsupportedRule, match="condition of release"):
        run_ledger(market(), scenario_with(Person("1985-01-01"), super_units={"GL": 1000}, pension=Pension("2026-07-01")), YEARS)
    usd = MarketPath(market().dates, ("AU", "GL"), market().returns, "USD")
    with pytest.raises(ValueError, match="AUD"):
        run_ledger(usd, scenario_with(Person("1985-01-01")), YEARS)
    with pytest.raises(UnsupportedRule, match="Division 296"):
        run_ledger(market(), scenario_with(Person("1985-01-01"), super_units={"GL": 3_100_000}), YEARS)


def test_ledger_report_writes_csv_json_and_png_without_pdf(tmp_path):
    import json

    from financial_simulations.reporting.ledger import write_ledger_report

    scenario = scenario_with(Person("1965-03-01", retirement_date="2025-12-31"), super_units={"GL": 100000},
                             annual_spending=6000, pension=Pension("2026-07-01"))
    result = run_ledger(market(), scenario, YEARS)
    write_ledger_report(result, tmp_path, "Synthetic ledger", {"rules": RULES.manifest()})
    summary = json.loads((tmp_path / "annual.json").read_text(encoding="utf-8"))
    assert summary["annual"][0]["financial_year"] == "2026-27"
    assert summary["manifest"]["rules"]["assumptions"]
    assert len(pd.read_csv(tmp_path / "daily.csv")) == 365
    assert (tmp_path / "ledger.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not list(tmp_path.glob("*.pdf"))
