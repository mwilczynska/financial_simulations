from dataclasses import replace
from datetime import date

import pytest

from financial_simulations.rules.au.parameters import UnsupportedRule, financial_year_of, load_ruleset
from financial_simulations.rules.au.superannuation import (
    BringForward, TransferBalanceAccount, access_date, accumulation_earnings_tax, add_business_days, age_on,
    apply_concessional, apply_non_concessional, concessional_cap, minimum_pension_payment, non_concessional_available,
    preservation_age, require_below_division_296, require_tax_free_benefits, round_to_ten, super_guarantee)
from financial_simulations.rules.au.tax import (CapitalGainEvent, IncomeYear, assess, bracket_tax,
                                                low_income_tax_offset, medicare_levy, net_capital_gain)


RULES = load_ruleset("2026-27")


def test_rule_set_provenance_and_assumptions_are_explicit():
    assert RULES.start == date(2026, 7, 1) and RULES.end == date(2027, 6, 30)
    assert {p.name for p in RULES.assumptions()} == {"medicare_low_income_lower", "medicare_low_income_upper",
                                                     "medicare_sapto_lower", "medicare_sapto_upper", "sapto"}
    assert all(p.source in RULES.sources for p in RULES.parameters.values())
    assert len(RULES.manifest()["sha256"]) == 64
    assert financial_year_of("2026-06-30") == "2025-26" and financial_year_of("2026-07-01") == "2026-27"
    with pytest.raises(KeyError, match="no parameter"):
        RULES["missing"]


@pytest.mark.parametrize("income, tax", [(18200, 0), (45000, 4020), (135000, 31020), (190000, 51370), (200000, 55870)])
def test_resident_brackets_match_ato_cumulative_amounts(income, tax):
    # ATO 2026-27 table: $4,020 at $45,000; $31,020 at $135,000; $51,370 at $190,000.
    assert bracket_tax(income, RULES["resident_tax_thresholds"], RULES["resident_tax_rates"]) == pytest.approx(tax)


@pytest.mark.parametrize("income, offset", [(37500, 700), (40000, 575), (45000, 325), (66667, 0)])
def test_low_income_tax_offset_boundaries(income, offset):
    assert low_income_tax_offset(income, RULES["lito"]) == pytest.approx(offset, abs=0.01)


def test_medicare_levy_reproduces_ato_low_income_example_and_boundaries():
    assert medicare_levy(29000, RULES) == pytest.approx(98.90)  # ATO worked example (Angie)
    assert medicare_levy(28011, RULES) == 0
    assert medicare_levy(40000, RULES) == pytest.approx(800)


def test_medicare_levy_surcharge_reproduces_ato_example():
    # ATO 2026-27 example (Tom): $90,000 taxable income, $27,000 fringe benefits, no hospital cover.
    year = IncomeYear(labour_income=91000, work_related_expenses=1000, reportable_fringe_benefits=27000,
                      private_hospital_cover=False)
    result = assess(year, RULES)
    assert result.taxable_income == 90000
    assert result.medicare_levy_surcharge == pytest.approx(1170)


def test_salary_example_with_standard_deduction():
    result = assess(IncomeYear(labour_income=100000), RULES)
    assert result.work_related_deduction == 1000 and result.taxable_income == 99000
    assert result.basic_tax == pytest.approx(4020 + 0.30 * 54000)
    assert result.net_tax == pytest.approx(20220 + 1980)


@pytest.mark.parametrize("labour, expenses, deduction", [(60000, 400, 1000), (60000, 1500, 1500), (700, 0, 700), (0, 0, 0)])
def test_standard_deduction_is_reduced_by_claimed_expenses_and_limited_to_labour_income(labour, expenses, deduction):
    assert assess(IncomeYear(labour_income=labour, work_related_expenses=expenses), RULES).work_related_deduction == deduction


def test_cgt_discount_holding_period_excludes_acquisition_and_event_days():
    assert not CapitalGainEvent("2025-01-01", "2026-01-01", 100).discount_eligible
    assert CapitalGainEvent("2025-01-01", "2026-01-02", 100).discount_eligible
    assert CapitalGainEvent("2024-02-29", "2025-03-02", 100).discount_eligible
    assert not CapitalGainEvent("2024-02-29", "2025-03-01", 100).discount_eligible


def test_capital_losses_offset_non_discount_gains_first_then_carry_forward():
    events = (CapitalGainEvent("2020-01-01", "2026-08-01", 10000), CapitalGainEvent("2026-07-15", "2026-09-01", 2000),
              CapitalGainEvent("2021-01-01", "2026-10-01", -3000))
    gain, left = net_capital_gain(events, 0, 0.5)
    assert gain == pytest.approx(4500) and left == 0
    gain, left = net_capital_gain(events[2:], 500, 0.5)
    assert gain == 0 and left == pytest.approx(3500)


def test_franking_credits_are_refundable_and_division_293_uses_low_tax_contributions():
    refund = assess(IncomeYear(franked_dividends=7000, franking_credits=3000), RULES)
    assert refund.taxable_income == 10000 and refund.net_tax == pytest.approx(-3000)
    high = assess(IncomeYear(labour_income=241000, low_tax_contributions=30000), RULES)
    assert high.taxable_income == 240000 and high.division_293_tax == pytest.approx(3000)


def test_sapto_matches_the_ato_example_and_unlocks_the_senior_medicare_thresholds():
    from financial_simulations.rules.au.tax import seniors_pensioners_offset

    # ATO example: single pensioner, rebate income $39,000: $2,230 - 12.5% x ($39,000 - $34,919) = $1,719.875 -> $1,720.
    assert seniors_pensioners_offset(39000, RULES) == 1720
    assert seniors_pensioners_offset(34919, RULES) == 2230 and seniors_pensioners_offset(52759, RULES) == 0
    senior = assess(IncomeYear(other_assessable_income=39000, sapto_eligible=True), RULES)
    other = assess(IncomeYear(other_assessable_income=39000), RULES)
    assert senior.sapto == 1720 and senior.medicare_levy == 0  # below the $44,268 senior threshold
    assert other.sapto == 0 and other.medicare_levy == pytest.approx(780)
    assert senior.net_tax == pytest.approx(other.net_tax - 1720 - 780)
    # Rebate income adds reportable super contributions: salary sacrifice can remove SAPTO.
    sacrificed = assess(IncomeYear(other_assessable_income=39000, reportable_employer_super=20000, sapto_eligible=True), RULES)
    assert sacrificed.sapto == 0 and sacrificed.lines["rebate_income"] == 59000
    # SAPTO is non-refundable: it cannot take income tax below nil.
    low = assess(IncomeYear(other_assessable_income=22000, sapto_eligible=True), RULES)
    assert low.income_tax_after_offsets == 0 and low.sapto == pytest.approx(low.basic_tax - low.lito)


def test_unsupported_tax_situations_fail_explicitly():
    with pytest.raises(UnsupportedRule, match="1,000"):
        assess(IncomeYear(foreign_income=20000, foreign_tax_paid=3000), RULES)
    with pytest.raises(ValueError, match="outside"):
        assess(IncomeYear(capital_events=(CapitalGainEvent("2020-01-01", "2027-07-01", 5),)), RULES)
    reformed = replace(RULES, start=date(2027, 7, 1), end=date(2028, 6, 30), financial_year="2027-28")
    with pytest.raises(ValueError, match="deferred or post_reform"):
        assess(IncomeYear(capital_events=(CapitalGainEvent("2020-01-01", "2027-07-01", 5),)), reformed)
    with pytest.raises(UnsupportedRule, match="minimum capital gains"):
        assess(IncomeYear(capital_events=(CapitalGainEvent("2020-01-01", "2027-07-01", 5, "post_reform"),)), reformed)


@pytest.mark.parametrize("born, age", [("1959-12-31", 55), ("1964-06-30", 59), ("1964-07-01", 60), ("1990-01-01", 60)])
def test_preservation_age_table(born, age):
    assert preservation_age(born, RULES) == age


def test_ages_birthdays_and_access_dates():
    assert age_on("2000-02-29", "2001-02-28") == 0 and age_on("2000-02-29", "2001-03-01") == 1
    born = "1970-03-15"
    assert access_date(born, RULES) == date(2035, 3, 15)
    assert access_date(born, RULES, retired_on="2020-06-30") == date(2030, 3, 15)  # early retiree at 60
    assert access_date(born, RULES, retired_on="2032-01-01") == date(2032, 1, 1)
    assert access_date(born, RULES, retired_on="2036-01-01") == date(2035, 3, 15)
    with pytest.raises(UnsupportedRule):
        require_tax_free_benefits(born, RULES, "2029-12-31")
    require_tax_free_benefits(born, RULES, "2030-03-15")


def test_super_guarantee_payday_and_maximum_contribution_base():
    assert super_guarantee(10000, 0, RULES) == pytest.approx(1200)
    assert super_guarantee(10000, 265000, RULES) == pytest.approx(0.12 * 5830)
    assert super_guarantee(10000, 280000, RULES) == 0
    assert add_business_days("2026-07-03", 7) == date(2026, 7, 14)  # Friday payday


def test_concessional_carry_forward_requires_low_balance_and_expires_after_five_years():
    unused = {"2020-21": 5000, "2021-22": 10000, "2025-26": 2000}
    cap = concessional_cap(RULES, 400000, unused)
    assert cap.available == 32500 + 12000
    assert concessional_cap(RULES, 500000, unused).available == 32500
    # $7,500 above the general cap uses 2021-22 first; its $2,500 remainder then expires.
    assert apply_concessional(40000, cap, unused, RULES) == {"2025-26": 2000}
    assert apply_concessional(30000, cap, {}, RULES) == {"2026-27": 2500}
    with pytest.raises(UnsupportedRule):
        apply_concessional(44501, cap, unused, RULES)


@pytest.mark.parametrize("tsb, room, length", [(1_500_000, 390000, 3), (1_900_000, 260000, 2),
                                               (2_000_000, 130000, 1), (2_100_000, 0, 1)])
def test_non_concessional_bring_forward_thresholds(tsb, room, length):
    assert non_concessional_available(RULES, tsb, True, None) == (room, length)


def test_bring_forward_period_fixes_the_first_year_cap():
    period = apply_non_concessional(200000, RULES, 1_500_000, True, None)
    assert period == BringForward(2026, 3, 390000, 200000)
    later = replace(RULES, financial_year="2027-28")
    assert non_concessional_available(later, 1_700_000, True, period) == (190000, 0)
    assert apply_non_concessional(190000, later, 1_700_000, True, period).used == 390000
    assert non_concessional_available(RULES, 1_500_000, False, None) == (130000, 1)
    with pytest.raises(UnsupportedRule):
        apply_non_concessional(131000, RULES, 2_000_000, True, None)


def test_minimum_pension_payments_and_rounding():
    assert minimum_pension_payment(500000, "1959-05-01", RULES) == 25000  # age 67 at 1 July 2026
    # Commencing 1 January 2027 at 66: $12,500 x 181/365 = $6,198.63, rounded to $6,200.
    assert minimum_pension_payment(250000, "1960-09-01", RULES, commenced="2027-01-01") == 6200
    assert minimum_pension_payment(250000, "1960-09-01", RULES, commenced="2027-06-01") == 0
    # ATO 2019-20 example: $12,500 x 182/366 = $6,215; halved $3,107 is rounded to $3,110.
    leap = replace(RULES, start=date(2019, 7, 1), end=date(2020, 6, 30))
    assert minimum_pension_payment(250000, "1953-06-01", leap, commenced="2020-01-01") == 6220
    assert round_to_ten(12500 * 182 / 366 / 2) == 3110


def test_transfer_balance_division_296_and_fund_tax():
    account = TransferBalanceAccount(RULES["transfer_balance_cap"]).credit(2_000_000)
    with pytest.raises(UnsupportedRule):
        account.credit(200_000)
    assert account.debit(500_000).credit(600_000).balance == 2_100_000
    require_below_division_296(3_000_000, RULES)
    with pytest.raises(UnsupportedRule):
        require_below_division_296(3_000_001, RULES)
    tax = accumulation_earnings_tax(10000, 9000, 0, 1000, RULES)
    assert tax["taxable_earnings"] == pytest.approx(17000) and tax["tax"] == pytest.approx(1550)


def test_every_rule_parameter_and_assumption_is_documented_in_the_register():
    from pathlib import Path

    register = (Path(__file__).resolve().parents[1] / "docs" / "rules" / "au-2026-27.md").read_text(encoding="utf-8")
    missing = [name for name in RULES.parameters if f"`{name}`" not in register]
    assert not missing, f"Register is missing {missing}"
    for parameter in RULES.assumptions():
        row = next(line for line in register.splitlines() if f"`{parameter.name}`" in line)
        assert "Assumption" in row
    assert all(s["url"].startswith(("https://www.ato.gov.au/", "https://www.legislation.gov.au/", "https://www.servicesaustralia.gov.au/",
                                    "https://operational.servicesaustralia.gov.au/", "https://guides.dss.gov.au/",
                                    "https://clik.dva.gov.au/"))
               for s in RULES.sources.values())


def test_age_pension_assets_and_income_tests_match_published_figures():
    from financial_simulations.rules.au.age_pension import apply_work_bonus, deemed_income, fortnightly_rate, maximum_rate

    assert maximum_rate(RULES) == pytest.approx(1237.70)
    # Deeming: 1.75% on the first $66,800, 3.75% above.
    assert deemed_income(500000, RULES) == pytest.approx(66800 * 0.0175 + 433200 * 0.0375)
    # Homeowner with $500,000: assets test binds ($3 a fortnight per $1,000 over $333,000).
    homeowner = fortnightly_rate(500000, 500000, 0.0, RULES)
    assert homeowner.amount == pytest.approx(1237.70 - 167 * 3) and homeowner.binding_test == "assets"
    # Non-homeowner with $500,000: under the $600,000 limit, so the income test binds on deemed income.
    renter = fortnightly_rate(500000, 500000, 0.0, RULES, homeowner=False)
    deemed = deemed_income(500000, RULES) / 26
    assert renter.amount == pytest.approx(1237.70 - 0.5 * (deemed - 226)) and renter.binding_test == "income"
    # Published cut-offs: no pension at $745,750 of assets (homeowner) or $2,701.40 a fortnight of income.
    assert fortnightly_rate(745750, 0, 0.0, RULES).amount < 1 and fortnightly_rate(0, 0, 2701.40, RULES).amount == pytest.approx(0)
    # Taxable part: the basic rate and the basic pension supplement.
    full = fortnightly_rate(0, 0, 0.0, RULES)
    assert full.taxable == pytest.approx(1135.40 + 30.70)
    # Work Bonus: $300 credit a fortnight offsets employment income; unused credit accrues to $11,800.
    assert apply_work_bonus(500, 0.0, RULES) == (200, 0.0)
    assert apply_work_bonus(0, 11700, RULES) == (0, 11800)
