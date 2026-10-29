from datetime import date

import numpy as np
import pandas as pd
import pytest

from financial_simulations.markets.path import MarketPath
from financial_simulations.retirement.ledger import LedgerScenario, Parcel, Pension, Person, run_ledger
from financial_simulations.rules.au.parameters import UnsupportedRule, load_ruleset
from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets
from financial_simulations.rules.au.tax import (CapitalGainEvent, IncomeYear, assess, indexation_factor,
                                                post_reform_gain)


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
