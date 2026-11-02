from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

from financial_simulations.markets.path import MarketPath
from financial_simulations.retirement.ledger import AssetIncome, LedgerScenario, Parcel, Pension, Person, run_ledger
from financial_simulations.rules.au.parameters import UnsupportedRule, load_ruleset
from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets
from financial_simulations.rules.au.tax import (CapitalGainEvent, IncomeYear, assess, indexation_factor,
                                                net_capital_gain, post_reform_gain)


BASE = load_ruleset("2026-27")
ASSUMED = ProjectionAssumptions(cpi_annual=0.025, wage_growth_annual=0.035)
YEARS = project_rulesets(BASE, "2030-31", ASSUMED)


def test_projected_rule_sets_apply_enacted_changes_and_statutory_increments():
    assert list(YEARS) == ["2026-27", "2027-28", "2028-29", "2029-30", "2030-31"]
    assert YEARS["2026-27"] is BASE
    later = YEARS["2027-28"]
    assert later.start == date(2027, 7, 1) and later.end == date(2028, 6, 30)
    assert later["resident_tax_rates"][0] == 0.14 and later.parameters["resident_tax_rates"].status == "enacted"
    assert later["resident_tax_thresholds"] == BASE["resident_tax_thresholds"]  # unindexed in law
    # $32,500 x 1.035^n rounded down to $2,500: $33,637, $34,815, then $36,034 -> $35,000.
    assert [YEARS[y]["concessional_cap"] for y in ("2027-28", "2028-29", "2029-30")] == [32500, 32500, 35000]
    assert YEARS["2029-30"]["non_concessional_cap"] == 140000
    assert YEARS["2029-30"]["maximum_contribution_base"] == 291660
    # $2.1m x 1.025^n rounded down to $100,000: $2.15m -> $2.1m, $2.21m -> $2.2m.
    assert [YEARS[y]["transfer_balance_cap"] for y in ("2027-28", "2028-29")] == [2100000, 2200000]
    assert YEARS["2028-29"]["bring_forward"]["three_year_below"] == 2200000 - 2 * 130000
    assert YEARS["2028-29"]["division_296"]["large_balance"] == 3150000
    assert later["medicare_low_income_lower"] == BASE["medicare_low_income_lower"]
    statuses = {name: p.status for name, p in later.parameters.items()}
    assert statuses["concessional_cap"] == "projected" and statuses["medicare_low_income_lower"] == "assumption"
    assert {"assumed_cpi_annual", "assumed_wage_growth_annual", "wato"} <= set(later.manifest()["assumptions"])
    assert len({r.sha256 for r in YEARS.values()}) == len(YEARS)
    with pytest.raises(ValueError):
        ProjectionAssumptions(0.9, 0.03)


def test_indexation_factor_quarters_rounding_and_floor():
    assert indexation_factor("2027-07-01", "2029-07-15", 0.025) == 1.051  # 1.025^2 = 1.050625
    assert indexation_factor("2027-07-01", "2027-09-30", 0.025) == 1.0  # same quarter
    assert indexation_factor("2027-07-01", "2029-07-15", -0.01) == 1.0  # no indexation at or below 1


def test_post_reform_gain_indexes_cost_and_never_creates_a_loss():
    assert post_reform_gain(100000, 120000, "2027-07-01", "2029-07-15", "2020-01-01", 0.025) == pytest.approx(14900)
    assert post_reform_gain(100000, 103000, "2027-07-01", "2029-07-15", "2020-01-01", 0.025) == 0
    assert post_reform_gain(100000, 95000, "2027-07-01", "2029-07-15", "2020-01-01", 0.025) == -5000
    # Held under 12 months from original acquisition: no indexation.
    assert post_reform_gain(100000, 120000, "2028-09-01", "2029-07-15", "2028-09-01", 0.025) == 20000


def test_minimum_tax_on_post_reform_gains():
    rules = YEARS["2027-28"]
    post = CapitalGainEvent("2027-08-01", "2028-03-01", 100000, "post_reform")
    result = assess(IncomeYear(capital_events=(post,)), rules)
    # 30% x $100,000 less 2027-28 basic tax on $100,000 ($3,752 + $16,500).
    assert result.taxable_income == 100000 and result.capital_gains_minimum_tax == 9748
    assert assess(IncomeYear(capital_events=(post,), minimum_tax_exempt=True), rules).capital_gains_minimum_tax == 0
    high = assess(IncomeYear(labour_income=201000, capital_events=(post,)), rules)
    assert high.capital_gains_minimum_tax == 0  # marginal rates already exceed 30%
    mixed = assess(IncomeYear(capital_events=(CapitalGainEvent("2020-01-01", "2028-03-01", 40000, "deferred"),
                                              CapitalGainEvent("2020-01-01", "2028-03-01", 10000, "post_reform"))), rules)
    # Deferred gain keeps the discount (20,000); tax attributable to the 10,000 post gain is 1,652 - 252.
    assert mixed.net_capital_gain == pytest.approx(30000) and mixed.capital_gains_minimum_tax == 1600
    losses = assess(IncomeYear(capital_events=(post, CapitalGainEvent("2027-08-01", "2028-03-01", -100000, "post_reform"))), rules)
    assert losses.minimum_tax_capital_gain == 0


def test_reform_year_losses_reduce_deferred_gains_before_post_reform_gains():
    rules = YEARS["2027-28"]
    deferred = CapitalGainEvent("2020-01-01", "2028-03-01", 40000, "deferred")
    post = CapitalGainEvent("2020-01-01", "2028-03-01", 10000, "post_reform")
    loss = CapitalGainEvent("2027-08-01", "2028-03-01", -10000, "post_reform")
    # s102-5 step 1: deferred non-residential gains first. (40,000 - 10,000) x 50% + 10,000 = 25,000.
    gain, left, base = net_capital_gain((deferred, post, loss), 0, 0.5, with_minimum_tax_base=True)
    assert gain == pytest.approx(25000) and left == 0 and base == pytest.approx(10000)
    # Step 2: carried-forward losses follow the same category order.
    assert net_capital_gain((deferred, post), 10000, 0.5, with_minimum_tax_base=True) == pytest.approx((25000, 0, 10000))
    # Within the deferred category the favourable choice reduces non-discount deferred gains first.
    short = CapitalGainEvent("2027-06-01", "2028-03-01", 5000, "deferred")
    assert not short.discount_eligible
    assert net_capital_gain((short, deferred, post, loss), 0, 0.5)[0] == pytest.approx(35000 * 0.5 + 10000)
    # Losses beyond the deferred gains reduce the post-reform gains and the minimum tax base.
    small = CapitalGainEvent("2020-01-01", "2028-03-01", 10000, "deferred")
    assert net_capital_gain((small, post), 15000, 0.5, with_minimum_tax_base=True) == pytest.approx((5000, 0, 5000))
    result = assess(IncomeYear(capital_events=(deferred, post, loss)), rules)
    assert result.net_capital_gain == pytest.approx(25000) and result.minimum_tax_capital_gain == pytest.approx(10000)


def test_non_refundable_offsets_reduce_the_minimum_tax():
    rules = YEARS["2027-28"]
    post = CapitalGainEvent("2027-08-01", "2028-03-01", 10000, "post_reform")
    # Treasury explainer: offsets can reduce the minimum tax. Basic tax nil, extra tax $3,000, LITO $700.
    alone = assess(IncomeYear(capital_events=(post,)), rules)
    assert alone.basic_tax == 0 and alone.capital_gains_minimum_tax == 3000
    assert alone.lito == 700 and alone.income_tax_after_offsets == 2300 and alone.net_tax == 2300
    # SAPTO (full $2,230 at $10,000 rebate income) is non-refundable: it leaves $70.
    senior = assess(IncomeYear(capital_events=(post,), sapto_eligible=True), rules)
    assert senior.sapto == 2230 and senior.income_tax_after_offsets == pytest.approx(70)
    # LITO and WATO together. $30,000 labour less the $1,000 standard deduction plus the gain: $39,000.
    worker = assess(IncomeYear(labour_income=30000, capital_events=(post,)), rules)
    assert worker.capital_gains_minimum_tax == 1600 and worker.lito == pytest.approx(625) and worker.wato == 250
    assert worker.income_tax_after_offsets == pytest.approx(worker.basic_tax + 1600 - 625 - 250)
    # Franking credits stay refundable after the non-refundable offsets.
    franked = assess(IncomeYear(franked_dividends=7000, franking_credits=3000, capital_events=(post,)), rules)
    assert franked.capital_gains_minimum_tax == 2748 and franked.income_tax_after_offsets == pytest.approx(3000 - 700)
    assert franked.net_tax == pytest.approx(franked.income_tax_after_offsets + franked.medicare_levy - 3000)


def test_working_australians_tax_offset_from_2027_28():
    rules = YEARS["2027-28"]
    assert assess(IncomeYear(labour_income=50000), rules).wato == 250
    assert assess(IncomeYear(labour_income=19000), rules).wato == 0  # net labour income $18,000
    assert assess(IncomeYear(labour_income=50000), BASE).wato == 0


def market(start="2026-07-01", end="2029-06-30", daily=0.0003):
    dates = tuple(pd.bdate_range(start, end).date)
    return MarketPath(dates, ("AU", "GL"), np.full((len(dates) - 1, 2), daily), "AUD")


def test_multi_year_ledger_values_parcels_at_reform_and_splits_later_gains():
    path = market(end="2029-07-02")  # include 30 June 2029, a Saturday, so 2028-29 is assessed
    scenario = LedgerScenario(Person("1975-03-01", retirement_date="2026-06-30"),
                              outside_parcels=(Parcel("AU", 100000, 60000, "2015-01-05"),), outside_weights={"AU": 1.0},
                              annual_spending=30000)
    result = run_ledger(path, scenario, YEARS)
    events = result.events
    valuation = events[events["event"] == "cgt_reform_valuation"].iloc[0]
    assert valuation["date"] == date(2027, 7, 1)
    assert valuation["amount"] == pytest.approx(result.daily.loc["2027-06-30", "outside_investments"])
    assert [a["financial_year"] for a in result.annual] == ["2026-27", "2027-28", "2028-29"]
    later = events[(events["event"] == "sale") & (events["date"] >= date(2027, 7, 1))]
    assert later["deferred_gain"].gt(0).all() and later["post_reform_gain"].ge(0).all()
    # Each later sale: deferred + post gain + indexation relief = proceeds - original cost.
    year = result.annual[1]["assessment"]
    assert year.minimum_tax_capital_gain == pytest.approx(later[later["date"] <= date(2028, 6, 30)]["post_reform_gain"].sum())
    settlements = events[events["event"] == "tax_settlement"]
    assert list(settlements["date"]) == [date(2027, 11, 1), date(2028, 10, 31)]  # Sunday due date rolls to Monday
    assert result.outstanding["tax_liabilities"][0]["financial_year"] == "2028-29"
    partial = result.outstanding["unassessed_year"]
    assert partial["financial_year"] == "2029-30" and partial["through"] == "2029-07-02"
    assert run_ledger(market(), scenario, YEARS).outstanding["unassessed_year"]["financial_year"] == "2028-29"


def test_multi_year_pension_minimum_resets_each_1_july_and_age_pension_age_stops_runs():
    scenario = LedgerScenario(Person("1964-08-01", retirement_date="2025-12-31"), super_units={"GL": 500000},
                              super_weights={"GL": 1.0}, outside_weights={"GL": 1.0}, pension=Pension("2026-07-01"))
    result = run_ledger(market(end="2028-06-30"), scenario, YEARS)
    first, second = result.annual
    assert first["pension_minimum"] == 20000
    assert second["pension_minimum"] == pytest.approx(round(0.04 * result.daily.loc["2027-06-30", "pension"] / 10) * 10)
    assert second["pension_paid"] == pytest.approx(second["pension_minimum"])
    with pytest.raises(UnsupportedRule, match="Age Pension age"):
        run_ledger(market(end="2028-06-30"), LedgerScenario(Person("1961-01-01")), YEARS)
    with pytest.raises(ValueError, match="market value just before 1 July 2027"):
        run_ledger(market(start="2027-08-02"), LedgerScenario(Person("1975-03-01"),
                   outside_parcels=(Parcel("AU", 10, 5, "2020-01-01"),)), YEARS)


@pytest.mark.parametrize("born, other_assets, exempt", [
    ("1955-01-01", 0, True),            # part Age Pension all year
    ("1955-01-01", 5_000_000, False),   # Age Pension age, but the means test pays nil
    ("1961-06-10", 0, True),            # first payment on 24 June 2028, inside the year
    ("1961-06-20", 0, False),           # first payment on 4 July 2028, after the year
])
def test_ledger_exempts_minimum_tax_only_when_age_pension_is_received(born, other_assets, exempt):
    dates = tuple(pd.bdate_range("2027-07-01", "2028-06-30").date)
    returns = np.zeros((len(dates) - 1, 1))
    returns[0, 0] = 0.5  # a post-reform gain on a parcel bought on 1 July 2027
    path = MarketPath(dates, ("AU",), returns, "AUD")
    scenario = LedgerScenario(Person(born, retirement_date="2020-01-01", other_assets=other_assets),
                              outside_parcels=(Parcel("AU", 100000, 100000, "2027-07-01"),),
                              outside_weights={"AU": 1.0}, annual_spending=60000, age_pension=True)
    year = run_ledger(path, scenario, YEARS).annual[0]
    assessment = year["assessment"]
    assert (year["age_pension"] > 0) == exempt
    assert assessment.minimum_tax_capital_gain > 0
    assert (assessment.capital_gains_minimum_tax == 0) == exempt


def test_a_weekend_30_june_horizon_is_still_assessed():
    # 30 June 2029 is a Saturday: the last observation is Friday 29 June, the accounting end is the 30th.
    dates = (date(2028, 7, 1), *pd.bdate_range("2028-07-01", "2029-06-30").date)  # Saturday opening mark
    path = MarketPath(dates, ("AU",), np.zeros((len(dates) - 1, 1)), "AUD")
    scenario = LedgerScenario(Person("1980-01-01"), super_units={"AU": 100000}, super_weights={"AU": 1.0},
                              income={"AU": AssetIncome(0.04)}, end_date="2029-06-30")
    result = run_ledger(path, scenario, YEARS)
    assert dates[-1] == date(2029, 6, 29) and result.daily.index[-1] == pd.Timestamp("2029-06-30")
    assert [a["financial_year"] for a in result.annual] == ["2028-29"]
    assert result.outstanding["unassessed_year"] is None
    # Four 1% distributions taxed at 15% as they accrue (about $600); no return is invented for the weekend.
    assert result.daily["fund_tax"].sum() == pytest.approx(0.15 * sum(1000 * 0.9985 ** q for q in range(4)))
    assert result.annual[0]["accumulation_tax"] == pytest.approx(result.daily["fund_tax"].sum())
    assert not result.daily.loc["2029-06-30", "is_observation"] and result.daily.loc["2029-06-30", "market_pnl"] == 0
    without = run_ledger(path, replace(scenario, end_date=None), YEARS)
    assert without.annual == [] and without.outstanding["unassessed_year"]["financial_year"] == "2028-29"
    with pytest.raises(ValueError, match="within a week"):
        run_ledger(path, replace(scenario, end_date="2029-07-10"), YEARS)


def test_bring_forward_counts_this_years_total_against_the_opening_period():
    from financial_simulations.rules.au.superannuation import BringForward, apply_non_concessional

    opening = BringForward(2026, 3, 390000, 250000)  # triggered in 2026-27 with $250,000
    rules = YEARS["2027-28"]
    assert apply_non_concessional(50000, rules, 0, True, opening) == BringForward(2026, 3, 390000, 300000)
    # A second payment this year: the year's total of $90,000 against the same opening state.
    assert apply_non_concessional(90000, rules, 0, True, opening) == BringForward(2026, 3, 390000, 340000)
    with pytest.raises(UnsupportedRule, match="Excess non-concessional"):
        apply_non_concessional(150000, rules, 0, True, opening)
