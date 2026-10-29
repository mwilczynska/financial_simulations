"""Australian resident individual income tax for one full income year.

Scope: full-year resident, single, no dependants, entitled to the full
tax-free threshold. A person eligible for the seniors and pensioners tax
offset (``sapto_eligible``) gets SAPTO on rebate income and the higher senior
Medicare levy low-income thresholds. Unsupported situations (foreign tax
beyond the $1,000 no-calculation limit) raise ``UnsupportedRule`` rather than
being approximated.

Capital gains carry a category. ``standard`` is an event before the 1 July
2027 reform. ``deferred`` is the pre-reform part of a gain on an asset held
on 30 June 2027 and realised later; it keeps the 50% discount when the
12-month test is met at the realisation event. ``post_reform`` is a gain
accruing from 1 July 2027 on an indexed cost base: it is never discounted
and enters the 30% minimum tax (Act No. 49, 2026).
"""

from dataclasses import dataclass, field
from datetime import date
from math import ceil, floor, isfinite

from financial_simulations.dates import as_date
from financial_simulations.rules.au.parameters import RuleSet, UnsupportedRule


def _amount(value, name, *, negative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    if value < 0 and not negative:
        raise ValueError(f"{name} must be nonnegative.")
    return float(value)


CATEGORIES = ("standard", "deferred", "post_reform")


def held_twelve_months(acquired, event) -> bool:
    """At least 12 months, excluding the acquisition and event days (ATO CGT discount)."""
    acquired, event = as_date(acquired), as_date(event)
    try:
        anniversary = acquired.replace(year=acquired.year + 1)
    except ValueError:  # acquired 29 February
        anniversary = date(acquired.year + 1, 3, 1)
    return event > anniversary


@dataclass(frozen=True)
class CapitalGainEvent:
    """One CGT event: gain (positive) or loss (negative) in AUD, with ownership dates and category."""

    acquired: date
    event: date
    amount: float
    category: str = "standard"

    def __post_init__(self):
        object.__setattr__(self, "acquired", as_date(self.acquired))
        object.__setattr__(self, "event", as_date(self.event))
        object.__setattr__(self, "amount", _amount(self.amount, "Capital gain", negative=True))
        if self.event < self.acquired:
            raise ValueError("A CGT event cannot precede acquisition.")
        if self.category not in CATEGORIES:
            raise ValueError(f"Capital gain category must be one of {CATEGORIES}.")

    @property
    def discount_eligible(self) -> bool:
        return self.category != "post_reform" and self.amount > 0 and held_twelve_months(self.acquired, self.event)


def quarter_number(day) -> int:
    day = as_date(day)
    return day.year * 4 + (day.month - 1) // 3


def indexation_factor(expenditure_day, event_day, cpi_annual) -> float:
    """CPI(event quarter) / CPI(expenditure quarter) on an assumed constant-growth CPI path.

    s960-275: rounded to 3 decimal places (half up); a factor of 1 or less
    gives no indexation.
    """
    quarters = quarter_number(event_day) - quarter_number(expenditure_day)
    factor = (1 + cpi_annual) ** (quarters / 4)
    factor = floor(factor * 1000 + 0.5) / 1000
    return factor if factor > 1 else 1.0


def post_reform_gain(cost, proceeds, expenditure_day, event_day, acquired, cpi_annual) -> float:
    """Gain or loss accruing from 1 July 2027: indexed cost base if held 12 months, never creating a loss.

    ``acquired`` is the original acquisition date: the 1 July 2027 deemed
    reacquisition is disregarded for the 12-month test.
    """
    factor = indexation_factor(expenditure_day, event_day, cpi_annual) if held_twelve_months(acquired, event_day) else 1.0
    if proceeds > cost * factor:
        return proceeds - cost * factor
    return min(0.0, proceeds - cost)


@dataclass(frozen=True)
class IncomeYear:
    """Inputs for one income year. Amounts are AUD; franked dividends are cash received."""

    labour_income: float = 0.0
    work_related_expenses: float = 0.0
    interest: float = 0.0
    unfranked_dividends: float = 0.0
    franked_dividends: float = 0.0
    franking_credits: float = 0.0
    other_assessable_income: float = 0.0
    foreign_income: float = 0.0
    foreign_tax_paid: float = 0.0
    capital_events: tuple[CapitalGainEvent, ...] = ()
    capital_losses_brought_forward: float = 0.0
    minimum_tax_exempt: bool = False
    deductible_super_contributions: float = 0.0
    other_deductions: float = 0.0
    excess_concessional_contributions: float = 0.0
    reportable_fringe_benefits: float = 0.0
    reportable_employer_super: float = 0.0
    low_tax_contributions: float = 0.0
    private_hospital_cover: bool = True
    sapto_eligible: bool = False

    def __post_init__(self):
        for name in ("labour_income", "work_related_expenses", "interest", "unfranked_dividends", "franked_dividends",
                     "franking_credits", "other_assessable_income", "foreign_income", "foreign_tax_paid",
                     "capital_losses_brought_forward", "deductible_super_contributions", "other_deductions",
                     "excess_concessional_contributions", "reportable_fringe_benefits", "reportable_employer_super",
                     "low_tax_contributions"):
            object.__setattr__(self, name, _amount(getattr(self, name), name))
        object.__setattr__(self, "capital_events", tuple(self.capital_events))
        if not all(isinstance(e, CapitalGainEvent) for e in self.capital_events):
            raise ValueError("Supply CapitalGainEvent objects.")


@dataclass(frozen=True)
class TaxAssessment:
    taxable_income: int
    net_capital_gain: float
    capital_losses_carried_forward: float
    work_related_deduction: float
    basic_tax: float
    lito: float
    wato: float
    excess_concessional_offset: float
    foreign_income_tax_offset: float
    income_tax_after_offsets: float
    minimum_tax_capital_gain: float
    capital_gains_minimum_tax: float
    medicare_levy: float
    medicare_levy_surcharge: float
    franking_offset: float
    net_tax: float
    division_293_tax: float
    lines: dict = field(default_factory=dict)
    sapto: float = 0.0


def net_capital_gain(events, losses_brought_forward, discount, *, with_minimum_tax_base=False):
    """Losses reduce post-reform gains, then other non-discount gains, then discountable gains.

    This is the taxpayer-favourable order the law permits: post-reform gains
    are undiscounted and attract the minimum tax. The discount applies to the
    remaining discountable gains, and unused losses carry forward. With
    ``with_minimum_tax_base``, also return the post-reform gains remaining
    after losses (the minimum tax capital gain, before gifts).
    """
    gains = [e for e in events if e.amount > 0]
    losses = -sum(e.amount for e in events if e.amount < 0) + losses_brought_forward
    pools = [sum(e.amount for e in gains if e.category == "post_reform"),
             sum(e.amount for e in gains if e.category != "post_reform" and not e.discount_eligible),
             sum(e.amount for e in gains if e.discount_eligible)]
    for i, pool in enumerate(pools):
        used = min(losses, pool)
        pools[i], losses = pool - used, losses - used
    result = (pools[0] + pools[1] + pools[2] * (1 - discount), losses)
    return (*result, pools[0]) if with_minimum_tax_base else result


def bracket_tax(taxable_income, thresholds, rates):
    tax = 0.0
    for i, (threshold, rate) in enumerate(zip(thresholds, rates)):
        upper = thresholds[i + 1] if i + 1 < len(thresholds) else float("inf")
        tax += max(0.0, min(taxable_income, upper) - threshold) * rate
    return tax


def low_income_tax_offset(taxable_income, lito):
    if taxable_income <= lito["first_threshold"]:
        return float(lito["maximum"])
    if taxable_income <= lito["second_threshold"]:
        return lito["maximum"] - lito["first_taper"] * (taxable_income - lito["first_threshold"])
    return max(0.0, lito["second_base"] - lito["second_taper"] * (taxable_income - lito["second_threshold"]))


def rebate_income(taxable_income, year: "IncomeYear") -> float:
    """ATO rebate income: taxable income plus reportable super contributions and reportable fringe benefits.

    Net investment losses are nil here, because a loss year has nil taxable income in this model. Reportable
    fringe benefits are taken at their full (non-exempt employer) amount.
    """
    return (taxable_income + year.reportable_employer_super + year.deductible_super_contributions
            + year.reportable_fringe_benefits)


def seniors_pensioners_offset(rebate, rules: RuleSet) -> float:
    """SAPTO for a single person: the maximum less 12.5c per dollar of rebate income above the shading-out
    threshold, rounded up to the whole dollar; nil at or above the cut-out threshold."""
    sapto = rules["sapto"]
    if rebate >= sapto["cut_out"]:
        return 0.0
    return float(max(0, ceil(round(sapto["maximum"] - sapto["taper"] * max(0.0, rebate - sapto["shade_out"]), 6))))


def medicare_levy(taxable_income, rules: RuleSet, *, senior=False):
    """Medicare levy with the low-income reduction; ``senior`` uses the thresholds for a person entitled to SAPTO."""
    if senior:
        lower, upper = rules["medicare_sapto_lower"], rules["medicare_sapto_upper"]
    else:
        lower, upper = rules["medicare_low_income_lower"], rules["medicare_low_income_upper"]
    full = rules["medicare_levy_rate"] * taxable_income
    if taxable_income <= lower:
        return 0.0
    return min(full, rules["medicare_low_income_shade_rate"] * (taxable_income - lower)) if taxable_income <= upper else full


def medicare_levy_surcharge(mls_income, surcharge_base, rules: RuleSet):
    rate = 0.0
    for threshold, tier in zip(rules["mls_single_thresholds"], rules["mls_rates"]):
        if mls_income > threshold:
            rate = tier
    return rate * surcharge_base


def assess(year: IncomeYear, rules: RuleSet, *, last_day=None) -> TaxAssessment:
    """Assess one resident income year. ``last_day`` bounds CGT event dates (defaults to year end)."""
    if year.foreign_tax_paid > 1000:
        raise UnsupportedRule("Foreign income tax offsets above the $1,000 no-calculation limit are not implemented.")
    reform = as_date(rules["cgt_reform_start"])
    for event in year.capital_events:
        if not rules.covers(event.event):
            raise ValueError(f"CGT event {event.event} is outside the {rules.financial_year} income year.")
        if (event.event >= reform) != (event.category != "standard"):
            raise ValueError("CGT events from 1 July 2027 must be deferred or post_reform; earlier events standard.")
        if event.event >= reform and "minimum_capital_gains_rate" not in rules.parameters:
            raise UnsupportedRule("This rule set has no minimum capital gains tax for post-reform events.")
    if year.franking_credits > 0 and year.franked_dividends <= 0:
        raise ValueError("Franking credits require franked dividends.")
    gain, losses_left, minimum_base = net_capital_gain(year.capital_events, year.capital_losses_brought_forward,
                                                       rules["cgt_discount_individual"], with_minimum_tax_base=True)
    standard = min(rules["standard_deduction_maximum"], year.labour_income)
    work_deduction = max(year.work_related_expenses, standard)
    assessable = (year.labour_income + year.interest + year.unfranked_dividends + year.franked_dividends
                  + year.franking_credits + year.other_assessable_income + year.foreign_income + gain
                  + year.excess_concessional_contributions)
    deductions = work_deduction + year.deductible_super_contributions + year.other_deductions
    # Taxable income is assessed in whole dollars; a loss year has nil taxable income here.
    taxable = max(0, floor(assessable - deductions))
    basic = bracket_tax(taxable, rules["resident_tax_thresholds"], rules["resident_tax_rates"])
    lito = low_income_tax_offset(taxable, rules["lito"])
    wato = 0.0
    if "wato" in rules.parameters and year.labour_income - work_deduction > rules["wato"]["net_labour_income_above"]:
        wato = float(rules["wato"]["amount"])
    excess_offset = rules["contributions_tax_rate"] * year.excess_concessional_contributions
    foreign_offset = year.foreign_tax_paid
    # SAPTO is non-refundable, like LITO: together they can reduce basic tax to nil but not below.
    sapto = seniors_pensioners_offset(rebate_income(taxable, year), rules) if year.sapto_eligible else 0.0
    after_offsets = max(0.0, basic - lito - wato - sapto - excess_offset - foreign_offset)
    # Division 119: 30% of the minimum tax capital gain less the basic tax attributable to it
    # (tax with and without the gain), rounded down to whole dollars. It is extra income tax,
    # added after offsets here.
    minimum_tax = 0.0
    minimum_base = min(minimum_base, float(taxable))
    if minimum_base > 0 and not year.minimum_tax_exempt:
        without = bracket_tax(max(0.0, taxable - minimum_base), rules["resident_tax_thresholds"], rules["resident_tax_rates"])
        # Round away floating-point noise below a cent before the statutory round-down.
        minimum_tax = max(0.0, floor(round(rules["minimum_capital_gains_rate"] * minimum_base - (basic - without), 6)))
    after_offsets += minimum_tax
    # Entitlement to at least $1 of SAPTO gives the higher senior Medicare low-income thresholds.
    levy = medicare_levy(taxable, rules, senior=sapto >= 1)
    surcharge = 0.0
    if not year.private_hospital_cover:
        mls_income = taxable + year.reportable_fringe_benefits + year.reportable_employer_super + year.deductible_super_contributions
        surcharge = medicare_levy_surcharge(mls_income, taxable + year.reportable_fringe_benefits, rules)
    division = rules["division_293"]
    income_293 = taxable + year.reportable_fringe_benefits
    div293 = division["rate"] * min(year.low_tax_contributions,
                                    max(0.0, income_293 + year.low_tax_contributions - division["threshold"]))
    net = after_offsets + levy + surcharge - year.franking_credits
    return TaxAssessment(taxable, gain, losses_left, work_deduction, basic, min(lito, basic), min(wato, max(0.0, basic - lito)),
                         excess_offset, foreign_offset, after_offsets, minimum_base, minimum_tax, levy, surcharge,
                         year.franking_credits, net,
                         div293, {"assessable_income": assessable, "deductions": deductions,
                                  "standard_deduction_available": standard, "income_for_division_293": income_293,
                                  "rebate_income": rebate_income(taxable, year), "sapto_entitlement": sapto},
                         min(sapto, max(0.0, basic - lito - wato)))
