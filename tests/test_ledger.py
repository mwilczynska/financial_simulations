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


def test_annual_rebalance_resets_weights_and_realises_outside_cgt():
    dates = tuple(pd.bdate_range("2026-12-28", "2027-01-08").date)
    returns = np.zeros((len(dates) - 1, 2))
    returns[0, 0] = 0.20  # AU rises 20% on 29 December, then the new year starts
    path = MarketPath(dates, ("AU", "GL"), returns, "AUD")
    opening = (Parcel("AU", 50000, 40000, "2019-01-01"), Parcel("GL", 50000, 50000, "2019-01-01"))
    kwargs = dict(outside_parcels=opening, outside_weights={"AU": 0.5, "GL": 0.5}, super_units={"AU": 50000, "GL": 50000},
                  super_weights={"AU": 0.5, "GL": 0.5})
    held = run_ledger(path, scenario_with(Person("1985-01-01"), **kwargs), YEARS)
    rebalanced = run_ledger(path, scenario_with(Person("1985-01-01"), outside_rebalance=True, super_rebalance=True, **kwargs),
                            YEARS)
    assert held.daily["total"].iloc[-1] == pytest.approx(rebalanced.daily["total"].iloc[-1])
    sales = rebalanced.events[(rebalanced.events["event"] == "sale") & (rebalanced.events["purpose"] == "rebalance")]
    # 60,000 AU and 50,000 GL reset to 55,000 each at the first 2027 observation (1 January in this weekday template): sell 5,000 AU with cost base 3,333.33.
    assert sales["date"].tolist() == [date(2027, 1, 1)]
    assert sales["amount"].sum() == pytest.approx(5000)
    assert sales["gain"].sum() == pytest.approx(5000 - 40000 / 60000 * 5000)
    assert "sale" not in set(held.events.get("event", ()))
    assert (rebalanced.events["event"] == "rebalance").sum() == 1  # accumulation units switch without tax


def test_unfundable_tax_is_recorded_as_unpaid_and_the_path_continues():
    from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets

    years = project_rulesets(RULES, "2027-28", ProjectionAssumptions(0.025, 0.035))
    path = market(end="2027-12-31")
    # Salary is spent in full, so nothing is left when the 2026-27 assessment falls due on 31 October 2027.
    result = run_ledger(path, scenario_with(Person("1985-01-01"), employment=Employment(120000, "2026-07-02"),
                                            annual_spending=120000), years)
    unpaid = result.outstanding["unpaid_tax"]
    assert len(unpaid) == 1 and unpaid[0]["financial_year"] == "2026-27" and unpaid[0]["amount"] > 0
    assert result.daily["tax_unpaid"].sum() == pytest.approx(unpaid[0]["amount"])
    assert result.daily.index[-1] == pd.Timestamp("2027-12-31")


def test_whole_balance_pension_transfer_stops_at_the_transfer_balance_cap():
    scenario = scenario_with(Person("1964-08-01", retirement_date="2025-12-31"), super_units={"GL": 2500000},
                             pension=Pension("2026-07-01"))
    result = run_ledger(market(), scenario, YEARS)
    commencement = result.events[result.events["event"] == "pension_commencement"].iloc[0]
    assert commencement["amount"] == pytest.approx(RULES["transfer_balance_cap"])
    assert result.daily["accumulation"].iloc[0] == pytest.approx(2500000 - RULES["transfer_balance_cap"])


def test_household_flows_reconcile_each_year_and_account_flows_track_transfers():
    from financial_simulations.retirement.flows import account_flows, household_flows

    path = market(seed=7)
    scenario = scenario_with(Person("1966-03-01", retirement_date="2026-09-30"), outside_cash=5000, cash_buffer=2000,
                             outside_parcels=(Parcel("GL", 40000, 30000, "2019-01-01"),), super_units={"GL": 400000},
                             employment=Employment(150000, "2026-07-02", 400), annual_spending=70000,
                             pension=Pension("2026-10-01", 300000))
    result = run_ledger(path, scenario, YEARS)
    household = household_flows(result.daily)
    for _, year in household.groupby("FY ending"):
        assert year["AUD"].sum() == pytest.approx(year["Net change"].iloc[0], abs=1e-4)
    assert household["Closing"].iloc[-1] == pytest.approx(result.daily["total"].iloc[-1])
    moves = account_flows(result.daily, result.events)
    transfer = moves.loc[moves["Flow"].isin(["Moved to pension", "Moved from super"]), "AUD"]
    assert transfer.sum() == pytest.approx(0) and transfer.max() == pytest.approx(300000)
    payments = moves.loc[moves["Flow"] == "Pension payments", "AUD"].sum()
    assert payments == pytest.approx(-result.daily["pension_payments"].sum())


def test_fixed_outside_contributions_then_surplus_cash_reinvested_from_retirement():
    person = Person("1985-01-01", retirement_date="2027-01-01")
    fixed = run_ledger(market(), scenario_with(person, employment=Employment(104000, "2026-07-02"), outside_cash=5000,
                                               cash_buffer=5000, outside_contribution_per_payday=500), YEARS)
    buys = fixed.events[(fixed.events["event"] == "buy") & (fixed.events["account"] == "outside")]
    when = pd.to_datetime(buys["date"])
    paydays = (fixed.events["event"] == "salary").sum()
    assert paydays == 14 and buys.loc[when < pd.Timestamp("2027-01-01"), "amount"].sum() == pytest.approx(500 * paydays)
    # Pay left in cash before retirement is reinvested on the retirement date, down to the buffer.
    later = buys.loc[when >= pd.Timestamp("2027-01-01")]
    assert later["date"].astype(str).tolist() == ["2027-01-01"]
    assert later["amount"].iloc[0] == pytest.approx(3500 * paydays)
    assert fixed.daily["outside_investments"].iloc[-1] == pytest.approx(4000 * paydays)
    assert fixed.daily["cash"].iloc[-1] == pytest.approx(5000)
    # An indexed contribution steps up on 1 July: 26 paydays of 100 in 2026-27, then 100 x 1.03 from July 2027.
    years = {"2026-27": RULES, "2027-28": RULES.derive("2027-28", {}, {})}
    indexed = run_ledger(market(end="2027-07-30"), scenario_with(Person("1985-01-01"), employment=Employment(104000, "2026-07-02"),
                                                                 outside_contribution_per_payday=100, outside_contribution_growth=0.03),
                         {"2026-27": RULES, **{k: v for k, v in years.items() if k != "2026-27"}})
    late = indexed.events[(indexed.events["event"] == "buy") & (indexed.events["account"] == "outside")
                          & (pd.to_datetime(indexed.events["date"]) >= pd.Timestamp("2027-07-01"))]
    assert late["amount"].tolist() == pytest.approx([103.0] * len(late)) and len(late) >= 2


def test_sales_take_the_lowest_taxable_gain_per_dollar_first():
    # Per dollar of proceeds: the loss parcel (-0.10), then the recent parcel held under 12 months (0.15, no
    # discount), then the old cheap parcel (0.60 halved by the discount to 0.30). Oldest-first would sell it first.
    old, recent, loss = date(2015, 3, 2), date(2026, 5, 1), date(2020, 1, 2)
    parcels = (Parcel("GL", 100000, 40000, old), Parcel("GL", 100000, 85000, recent), Parcel("GL", 100000, 110000, loss))
    result = run_ledger(market(), scenario_with(Person("1985-01-01"), outside_parcels=parcels, annual_spending=240000), YEARS)
    sales = result.events[result.events["event"] == "sale"]
    order = sales["acquired"].drop_duplicates().tolist()
    assert order == [str(loss), str(recent), str(old)]
    sold = sales.groupby("acquired")["amount"].sum()
    assert sold[str(loss)] == pytest.approx(100000) and sold[str(recent)] == pytest.approx(100000)
    assert sold[str(old)] == pytest.approx(40000)
    assert sales.loc[sales["acquired"] == str(old), "gain"].sum() == pytest.approx(40000 * 0.6)


def test_cash_earns_daily_interest_that_is_taxed_and_reconciles():
    result = run_ledger(market(), scenario_with(Person("1985-01-01"), outside_cash=100000, cash_buffer=100000,
                                                outside_contribution_per_payday=0.0, cash_interest=0.04), YEARS)
    days = len(result.daily)
    # With nothing swept into investments, cash compounds daily at 4% a year.
    assert result.daily["total"].iloc[-1] == pytest.approx(100000 * 1.04 ** (days / 365.25))
    interest = result.daily["interest"].sum()
    assert result.annual[0]["assessment"].taxable_income == pytest.approx(int(interest), abs=1)


def test_payg_withholding_spreads_salary_tax_and_settles_only_the_balance():
    path = market()
    plain = run_ledger(path, scenario_with(Person("1985-01-01"), employment=Employment(104000, "2026-07-02")), YEARS)
    withheld = run_ledger(path, scenario_with(Person("1985-01-01"), employment=Employment(104000, "2026-07-02"),
                                              payg_withholding=True), YEARS)
    events = withheld.events[withheld.events["event"] == "payg_withholding"]
    assessed = withheld.annual[0]["assessment"].net_tax
    assert len(events) == 26
    # Salary is the only income, so withholding equals the assessment and nothing is left to settle.
    assert events["amount"].sum() == pytest.approx(assessed)
    assert withheld.outstanding["tax_liabilities"][0]["amount"] == pytest.approx(0, abs=1e-6)
    assert plain.outstanding["tax_liabilities"][0]["amount"] == pytest.approx(assessed)
    assert withheld.daily["total"].iloc[-1] == pytest.approx(plain.daily["total"].iloc[-1] - assessed)


def test_salary_and_sacrifice_grow_each_first_of_july_and_withholding_follows():
    from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets

    years = project_rulesets(RULES, "2027-28", ProjectionAssumptions(0.025, 0.035))
    employment = Employment(104000, "2026-07-02", salary_sacrifice_per_payday=100, annual_growth=0.04)
    result = run_ledger(market(end="2028-06-30"), scenario_with(Person("1985-01-01"), employment=employment,
                                                                payg_withholding=True), years)
    salary = result.events[result.events["event"] == "salary"]
    first = salary[pd.to_datetime(salary["date"]) < pd.Timestamp("2027-07-01")]
    second = salary[pd.to_datetime(salary["date"]) >= pd.Timestamp("2027-07-01")]
    assert first["amount"].unique().tolist() == pytest.approx([4000 - 100])
    assert second["amount"].unique().tolist() == pytest.approx([(4000 - 100) * 1.04])
    assert second["sacrifice"].unique().tolist() == pytest.approx([104.0])
    withheld = result.events[result.events["event"] == "payg_withholding"]
    later = withheld[pd.to_datetime(withheld["date"]) >= pd.Timestamp("2027-07-01")]["amount"]
    # The second year's withholding is estimated on that year's grown salary and sacrifice.
    salary, sacrifice = 104000 * 1.04, 2600 * 1.04
    rules = years["2027-28"]
    estimate = assess(IncomeYear(labour_income=salary - sacrifice, reportable_employer_super=sacrifice,
                                 low_tax_contributions=rules["super_guarantee_rate"] * salary + sacrifice,
                                 private_hospital_cover=True), rules)
    assert later.unique().tolist() == pytest.approx([estimate.net_tax / 26])


def test_retirement_spending_replaces_working_spending_from_the_retirement_date():
    result = run_ledger(market(), scenario_with(Person("1966-03-01", retirement_date="2027-01-01"), outside_cash=200000,
                                                cash_buffer=200000, annual_spending=60000, retirement_spending=36000), YEARS)
    paid = result.events[result.events["event"] == "spending"]
    before = paid[pd.to_datetime(paid["date"]) < pd.Timestamp("2027-01-01")]["requested"]
    after = paid[pd.to_datetime(paid["date"]) >= pd.Timestamp("2027-01-01")]["requested"]
    assert before.unique().tolist() == pytest.approx([5000.0]) and after.unique().tolist() == pytest.approx([3000.0])


def _falling_market_rules(kind, minimum=0.0):
    from financial_simulations.retirement.ledger import SpendingRule
    from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets

    years = project_rulesets(RULES, "2028-29", ProjectionAssumptions(0.025, 0.035))
    path = market(end="2028-07-31", returns=-0.001)  # about -23% a year
    scenario = scenario_with(Person("1975-01-01", retirement_date="2026-01-01"), outside_cash=1000,
                             outside_parcels=(Parcel("GL", 1000000, 1000000, "2020-01-01"),), annual_spending=40000,
                             spending_growth=0.025, spending_rule=SpendingRule(kind, minimum=minimum))
    result = run_ledger(path, scenario, years)
    return result, result.events[result.events["event"] == "spending_rule"]


def _percent_start(kind, **rule):
    from financial_simulations.retirement.ledger import SpendingRule

    path = market(end="2027-06-30", returns=0.0)
    scenario = scenario_with(Person("1975-01-01", retirement_date="2026-09-15"), outside_cash=50000,
                             outside_parcels=(Parcel("GL", 950000, 950000, "2020-01-01"),), annual_spending=60000,
                             retirement_spending=1.0, spending_rule=SpendingRule(kind, start_rate=0.04, **rule))
    result = run_ledger(path, scenario, YEARS)
    return result, result.events[result.events["event"] == "spending"]


def test_a_percentage_start_sets_spending_from_wealth_on_the_retirement_date():
    result, paid = _percent_start("fixed")
    dates = pd.to_datetime(paid["scheduled"])
    assert paid.loc[dates < pd.Timestamp("2026-09-15"), "requested"].unique().tolist() == pytest.approx([5000.0])
    after = paid.loc[dates >= pd.Timestamp("2026-10-01"), "requested"]
    start = result.events[result.events["event"] == "spending_rule"].iloc[0]
    # 4% of total wealth on the first spending date once retired (1 October), a twelfth each month.
    assert start["withdrawal_rate"] == pytest.approx(0.04) and after.unique().tolist() == pytest.approx([start["amount"] / 12])
    assert 0.04 * 900000 < start["amount"] < 0.04 * 1000000


def test_a_maximum_caps_a_percentage_start():
    _, paid = _percent_start("percent", maximum=30000)
    after = paid.loc[pd.to_datetime(paid["scheduled"]) >= pd.Timestamp("2026-10-01"), "requested"]
    assert after.unique().tolist() == pytest.approx([2500.0])


def test_percent_of_wealth_rule_spends_the_starting_rate_of_wealth_each_first_of_july():
    from financial_simulations.retirement.ledger import SpendingRule
    from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets

    years = project_rulesets(RULES, "2028-29", ProjectionAssumptions(0.025, 0.035))
    scenario = scenario_with(Person("1975-01-01", retirement_date="2026-01-01"), outside_cash=1000,
                             outside_parcels=(Parcel("GL", 1000000, 1000000, "2020-01-01"),), annual_spending=1.0,
                             spending_growth=0.025, spending_rule=SpendingRule("percent", start_rate=0.04))
    result = run_ledger(market(end="2028-07-31", returns=-0.001), scenario, years)
    reviews = result.events[result.events["event"] == "spending_rule"]
    assert len(reviews) == 3 and reviews["withdrawal_rate"].tolist() == pytest.approx([0.04] * 3)
    assert reviews["amount"].iloc[2] < reviews["amount"].iloc[1] < reviews["amount"].iloc[0]


def test_guyton_klinger_cuts_after_the_withdrawal_rate_breaches_the_upper_guardrail():
    result, reviews = _falling_market_rules("guyton_klinger")
    first, second = reviews.iloc[0], reviews.iloc[1]
    assert first["action"] == "start" and first["amount"] == pytest.approx(40000 * 1.025)
    # A losing year with the rate above the start: no growth step, and the rate is still > 120% of the start: cut 10%.
    assert "no increase after a losing year" in second["action"] and "cut 10%" in second["action"]
    assert second["amount"] == pytest.approx(first["amount"] * 0.9)
    july = result.events[(result.events["event"] == "spending") & (pd.to_datetime(result.events["scheduled"]) == pd.Timestamp("2028-07-01"))]
    assert july["requested"].iloc[0] == pytest.approx(second["amount"] / 12)


def test_vanguard_limits_a_cut_to_the_floor_and_the_minimum_holds():
    _, reviews = _falling_market_rules("vanguard")
    first, second = reviews.iloc[0], reviews.iloc[1]
    assert second["amount"] == pytest.approx(first["amount"] * 1.025 * 0.975)
    assert "limited by floor" in second["action"]
    _, held = _falling_market_rules("vanguard", minimum=40000)
    assert held.iloc[1]["amount"] == pytest.approx(40000 * 1.025 ** 2) and "minimum" in held.iloc[1]["action"]


def test_todays_dollars_keep_cpi_indexed_spending_flat_and_flows_reconcile_with_inflation():
    from financial_simulations.retirement.flows import household_flows
    from financial_simulations.retirement.real import real_daily
    from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets

    years = project_rulesets(RULES, "2028-29", ProjectionAssumptions(0.025, 0.035))
    scenario = scenario_with(Person("1975-01-01", retirement_date="2026-01-01"), outside_cash=1000,
                             outside_parcels=(Parcel("GL", 1000000, 1000000, "2020-01-01"),), annual_spending=48000,
                             spending_growth=0.025)
    result = run_ledger(market(end="2029-06-30", returns=0.0003), scenario, years)
    real = real_daily(result.daily, 0.025)
    assert real["total"].iloc[0] == pytest.approx(result.daily["total"].iloc[0])
    last = result.daily.index[-1]
    assert real["total"].iloc[-1] == pytest.approx(result.daily["total"].iloc[-1] / 1.025 ** ((last - result.daily.index[0]).days / 365.25))
    flows = household_flows(real, inflation=True)
    spending = flows.loc[flows["Flow"] == "Spending"].set_index("FY ending")["AUD"]
    assert spending.tolist() == pytest.approx([-48000.0] * 3)
    by_year = flows.groupby("FY ending")
    assert (by_year["AUD"].sum() - by_year["Net change"].first()).abs().max() < 1e-6
    assert (flows.loc[flows["Flow"] == "Inflation", "AUD"] < 0).all()


def test_path_summary_reports_starting_spending_and_rate_in_todays_dollars():
    from financial_simulations.retirement.ledger import SpendingRule
    from financial_simulations.retirement.paths import _summarise

    path = market(end="2027-06-30", returns=0.0)
    scenario = scenario_with(Person("1975-01-01", retirement_date="2026-09-15"), outside_cash=50000,
                             outside_parcels=(Parcel("GL", 950000, 950000, "2020-01-01"),), annual_spending=60000,
                             retirement_spending=1.0, spending_rule=SpendingRule("fixed", start_rate=0.04))
    outcome, _, _ = _summarise(0, run_ledger(path, scenario, YEARS), date(2026, 9, 15), 0.025)
    assert outcome["Starting withdrawal rate"] == pytest.approx(0.04)
    assert 0.04 * 900000 < outcome["Starting retirement spending"] < 0.04 * 1000000


def test_age_pension_is_paid_fortnightly_means_tested_and_taxed_with_sapto():
    person = Person("1958-06-01", retirement_date="2020-01-01", homeowner=True, other_assets=10000)
    scenario = scenario_with(person, outside_cash=500, outside_parcels=(Parcel("GL", 500000, 500000, "2020-01-01"),),
                             annual_spending=40000, age_pension=True)
    result = run_ledger(market(), scenario, YEARS)
    paid = result.events[result.events["event"] == "age_pension"]
    assert len(paid) == 26
    first = paid.iloc[0]
    # Assets test on the previous close plus other assets: $3 a fortnight less per $1,000 over $333,000.
    before = result.daily["total"].loc[pd.Timestamp(first["date"]) - pd.Timedelta(days=1)]
    assert first["assessed_assets"] == pytest.approx(before + 10000)
    assert first["amount"] == pytest.approx(1237.70 - (first["assessed_assets"] - 333000) * 0.003)
    assert first["binding_test"] == "assets"
    # Spending runs wealth down, so later fortnights pay more.
    assert paid["amount"].iloc[-1] > first["amount"]
    year = result.annual[0]
    assert year["age_pension"] == pytest.approx(paid["amount"].sum())
    assert year["age_pension_taxable"] == pytest.approx(paid["amount"].sum() * (1135.40 + 30.70) / 1237.70)
    # Taxable income is just above the tax-free threshold: SAPTO is available but LITO already removes the tax.
    assert year["assessment"].lines["sapto_entitlement"] == 2230 and year["assessment"].net_tax <= 0
    assert result.daily["age_pension"].sum() == pytest.approx(paid["amount"].sum())


def test_without_the_age_pension_switch_the_ledger_still_stops_at_age_pension_age():
    person = Person("1958-06-01", retirement_date="2020-01-01")
    with pytest.raises(UnsupportedRule, match="age_pension=True"):
        run_ledger(market(), scenario_with(person, outside_cash=500000), YEARS)


def test_division_296_taxes_super_earnings_above_3m_and_is_released_from_super():
    from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets

    years = project_rulesets(RULES, "2028-29", ProjectionAssumptions(0.025, 0.035))
    scenario = scenario_with(Person("1985-01-01"), super_units={"GL": 4_000_000}, income={"GL": AssetIncome(0.04)},
                             tsb_prior_30_june=4_000_000)
    result = run_ledger(market(end="2028-12-31"), scenario, years)
    first = result.annual[0]
    earnings, reference = first["division_296_earnings"], first["division_296_reference_balance"]
    # 2026-27: only the 30 June 2027 balance counts. Earnings are the year's super distributions (no realised gains).
    assert earnings == pytest.approx(4_000_000 * 0.04, rel=0.02)
    percent = round((reference - 3_000_000) / reference * 100, 2)
    assert first["division_296_tax"] == pytest.approx(0.15 * earnings * percent / 100)
    # Released on 30 September 2028: the ATO requests fund reports from April 2028, then 84 days to pay.
    paid = result.events[(result.events["event"] == "division_296_payment") & (result.events["financial_year"] == "2026-27")]
    assert len(paid) == 1 and str(paid.iloc[0]["date"]) >= "2028-09-30"
    assert paid.iloc[0]["released_from_super"] == pytest.approx(first["division_296_tax"])
    assert result.daily.loc[:"2028-10-31", "division_296"].sum() == pytest.approx(first["division_296_tax"])
    # Below the threshold nothing is assessed.
    small = run_ledger(market(), scenario_with(Person("1985-01-01"), super_units={"GL": 2_000_000},
                                               income={"GL": AssetIncome(0.04)}), YEARS)
    assert small.annual[0]["division_296_tax"] == 0


def test_super_funds_realise_a_share_of_gains_taxed_in_accumulation_and_counted_for_division_296():
    from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets

    years = project_rulesets(RULES, "2027-28", ProjectionAssumptions(0.025, 0.035))
    path = market(end="2028-06-30", returns=0.0004)  # about 10% a year, all price growth
    base = dict(super_units={"GL": 4_000_000}, tsb_prior_30_june=4_000_000)
    none = run_ledger(path, scenario_with(Person("1985-01-01"), **base), years)
    some = run_ledger(path, scenario_with(Person("1985-01-01"), super_realised_gains=0.25, **base), years)
    first = some.annual[0]
    growth = none.annual[0]["total_super_balance_30_june"] - 4_000_000
    # A quarter of the year's unrealised gain is realised; fund tax is 15% after the one-third discount.
    assert first["super_realised_gains"] == pytest.approx(0.25 * growth, rel=1e-6)
    assert first["accumulation_tax"] == pytest.approx(0.15 * (2 / 3) * first["super_realised_gains"], rel=1e-6)
    # Division 296 earnings: the discounted gain scaled by the 2026-27 transitional factor of 0.2.
    assert first["division_296_earnings"] == pytest.approx(first["super_realised_gains"] * (2 / 3) * 0.2, rel=1e-6)
    assert none.annual[0]["division_296_tax"] == 0 and first["division_296_tax"] > 0
    # The realised part joins the cost base: the next year realises a quarter of the remaining and new gain only.
    second = some.annual[1]
    assert second["super_realised_gains"] < 0.25 * (second["total_super_balance_30_june"] - 4_000_000)
    with pytest.raises(ValueError, match="between 0 and 1"):
        run_ledger(path, scenario_with(Person("1985-01-01"), super_realised_gains=1.5, **base), years)
