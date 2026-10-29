"""Taxed accumulation super and account-based pensions for one Australian individual.

Scope: a standard taxed defined-contribution fund, taxed elements only, and
benefits paid at age 60 or over (tax free). Defined benefits, untaxed
elements, transition-to-retirement streams, early access, excess-cap regimes
and Division 296 balances are rejected with ``UnsupportedRule``.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import floor

from financial_simulations.dates import as_date
from financial_simulations.rules.au.parameters import RuleSet, UnsupportedRule, financial_year_of


def birthday(born, years):
    """The date a person attains an age; 29 February birthdays fall on 1 March in common years."""
    born = as_date(born)
    try:
        return born.replace(year=born.year + years)
    except ValueError:
        return date(born.year + years, 3, 1)


def age_on(born, day) -> int:
    born, day = as_date(born), as_date(day)
    if day < born:
        raise ValueError("Age is undefined before birth.")
    age = day.year - born.year
    return age if day >= birthday(born, age) else age - 1


def preservation_age(born, rules: RuleSet) -> int:
    born = as_date(born)
    for before, age in rules["preservation_age"]:
        if born < as_date(before):
            return age
    raise ValueError("Preservation age table does not cover this birth date.")


def access_date(born, rules: RuleSet, retired_on=None) -> date:
    """First day preserved benefits are unrestricted for a taxed accumulation member.

    Unrestricted at 65; earlier on retirement after reaching preservation age.
    A person who stopped work earlier meets the retirement condition at
    preservation age, provided they intend never to work again (an input
    assumption). Retiring between preservation age and 65 releases from that day.
    """
    sixty_five = birthday(born, rules["unrestricted_access_age"])
    if retired_on is None:
        return sixty_five
    preserved_until = birthday(born, preservation_age(born, rules))
    return min(sixty_five, max(as_date(retired_on), preserved_until))


def require_tax_free_benefits(born, rules: RuleSet, day):
    """Benefits from a taxed fund are tax free from age 60; earlier payments are out of scope."""
    if age_on(born, day) < 60:
        raise UnsupportedRule("Super benefits before age 60 (low rate cap and tax components) are not implemented.")


def super_guarantee(qualifying_earnings, earnings_so_far_this_year, rules: RuleSet) -> float:
    """SG for one payday: rate x qualifying earnings, stopping at the annual maximum contribution base."""
    base = rules["maximum_contribution_base"]
    eligible = max(0.0, min(qualifying_earnings, base - earnings_so_far_this_year))
    return rules["super_guarantee_rate"] * eligible


def add_business_days(day, count) -> date:
    """Weekdays only; public holidays are not modelled, so this is the earliest legal deadline."""
    day = as_date(day)
    while count > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


@dataclass(frozen=True)
class ConcessionalCap:
    general: float
    carried_forward: float

    @property
    def available(self) -> float:
        return self.general + self.carried_forward


def _usable_unused(unused_by_year: dict, rules: RuleSet, first_year: int) -> dict:
    """Unused amounts accrued from 2018-19 within the five years before ``first_year``."""
    years = rules["carry_forward"]["years"]
    return {fy: v for fy, v in unused_by_year.items() if first_year - years <= int(fy[:4]) < first_year and int(fy[:4]) >= 2018}


def concessional_cap(rules: RuleSet, tsb_prior_30_june, unused_by_year: dict) -> ConcessionalCap:
    """General cap plus unused amounts from the previous five years if TSB was below $500,000.

    ``unused_by_year`` maps a financial-year label to its unused cap.
    """
    first = int(rules.financial_year[:4])
    usable = _usable_unused(unused_by_year, rules, first)
    carried = sum(usable.values()) if tsb_prior_30_june < rules["carry_forward"]["tsb_below"] else 0.0
    return ConcessionalCap(float(rules["concessional_cap"]), float(carried))


def apply_concessional(contributions, cap: ConcessionalCap, unused_by_year: dict, rules: RuleSet) -> dict:
    """Use carried-forward amounts oldest first after the general cap; contributions above the cap fail.

    Returns the unused history still usable from the next financial year.
    """
    if contributions > cap.available + 1e-9:
        raise UnsupportedRule("Excess concessional contributions are not modelled; reduce contributions to the cap.")
    first = int(rules.financial_year[:4])
    remaining = _usable_unused(unused_by_year, rules, first)
    over = max(0.0, contributions - cap.general)
    for fy in sorted(remaining):
        used = min(over, remaining[fy])
        remaining[fy] -= used
        over -= used
    remaining[rules.financial_year] = max(0.0, cap.general - contributions)
    return {fy: v for fy, v in _usable_unused(remaining, rules, first + 1).items() if v > 0}


@dataclass(frozen=True)
class BringForward:
    """An open bring-forward period: first financial-year start year, length and fixed total cap."""

    first_year: int
    years: int
    total_cap: float
    used: float


def non_concessional_available(rules: RuleSet, tsb_prior_30_june, under_75_in_year: bool,
                               period: BringForward | None) -> tuple[float, int]:
    """Room for this year's non-concessional contributions and the period length it would open.

    Within an open period, the remaining fixed total applies (later indexation
    does not). Otherwise the TSB at the prior 30 June sets 3-, 2- or 1-year
    room; at or above the transfer balance cap the cap is nil.
    """
    year = int(rules.financial_year[:4])
    if tsb_prior_30_june >= rules["transfer_balance_cap"]:
        return 0.0, 1
    if period and year < period.first_year + period.years:
        return max(0.0, period.total_cap - period.used), 0
    annual, rule = float(rules["non_concessional_cap"]), rules["bring_forward"]
    if not under_75_in_year:
        return annual, 1
    if tsb_prior_30_june < rule["three_year_below"]:
        return 3 * annual, 3
    if tsb_prior_30_june < rule["two_year_below"]:
        return 2 * annual, 2
    return annual, 1


def apply_non_concessional(contributions, rules: RuleSet, tsb_prior_30_june, under_75_in_year, period):
    """Return the bring-forward state after this year's contributions; excess contributions fail."""
    room, length = non_concessional_available(rules, tsb_prior_30_june, under_75_in_year, period)
    if contributions > room + 1e-9:
        raise UnsupportedRule("Excess non-concessional contributions are not modelled; reduce contributions to the cap.")
    year = int(rules.financial_year[:4])
    if length == 0:
        return BringForward(period.first_year, period.years, period.total_cap, period.used + contributions)
    if length > 1 and contributions > rules["non_concessional_cap"]:
        return BringForward(year, length, room, contributions)
    return None


def require_below_division_296(total_super_balance_30_june, rules: RuleSet):
    if total_super_balance_30_june > rules["division_296"]["large_balance"]:
        raise UnsupportedRule("Division 296 tax on balances above the large super balance threshold is not implemented.")


def minimum_drawdown_factor(age, rules: RuleSet) -> float:
    for below, factor in rules["minimum_drawdown"]:
        if age < below:
            return factor
    raise ValueError("Minimum drawdown table does not cover this age.")


def round_to_ten(amount) -> float:
    return float(floor(amount / 10 + 0.5) * 10)


def minimum_pension_payment(balance, born, rules: RuleSet, *, commenced=None) -> float:
    """Annual minimum for an account-based pension, rounded to the nearest $10.

    A full year uses the 1 July balance and age. A pension commencing during
    the year uses its commencement balance and age, pro-rated by days
    remaining including the commencement day over the days in the year. A
    pension commencing on or after 1 June needs no payment that year.
    """
    if commenced is None:
        return round_to_ten(balance * minimum_drawdown_factor(age_on(born, rules.start), rules))
    commenced = as_date(commenced)
    if not rules.covers(commenced):
        raise ValueError("Commencement must fall within the rule set's financial year.")
    if commenced.month == 6:
        return 0.0
    days_in_year = (rules.end - rules.start).days + 1
    remaining = (rules.end - commenced).days + 1
    annual = balance * minimum_drawdown_factor(age_on(born, commenced), rules)
    return round_to_ten(annual * remaining / days_in_year)


@dataclass(frozen=True)
class TransferBalanceAccount:
    """Personal transfer balance: credits for amounts moved into retirement phase, debits for commutations."""

    cap: float
    balance: float = 0.0

    def credit(self, amount) -> "TransferBalanceAccount":
        if self.balance + amount > self.cap + 1e-6:
            raise UnsupportedRule("An excess transfer balance is not modelled; keep retirement-phase transfers within the cap.")
        return TransferBalanceAccount(self.cap, self.balance + amount)

    def debit(self, amount) -> "TransferBalanceAccount":
        return TransferBalanceAccount(self.cap, max(0.0, self.balance - amount))


def accumulation_earnings_tax(income, gross_capital_gain, capital_losses, franking_credits, rules: RuleSet) -> dict:
    """Fund tax on accumulation-phase earnings: 15% after the one-third CGT discount, less franking credits.

    Losses offset gains before the discount; net capital losses carry forward.
    The result can be negative when franking credits exceed tax (a fund-level
    benefit credited to members).
    """
    net = max(0.0, gross_capital_gain - capital_losses)
    taxable = income + franking_credits + net * (1 - rules["cgt_discount_complying_fund"])
    return {"taxable_earnings": taxable, "tax": rules["fund_earnings_tax_rate"] * taxable - franking_credits,
            "capital_losses_carried_forward": max(0.0, capital_losses - gross_capital_gain)}


def contribution_financial_year(received) -> str:
    """Contributions count towards caps in the year the fund receives them."""
    return financial_year_of(received)
