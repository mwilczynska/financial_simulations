"""Age Pension for one single person at normal (not transitional) rates.

Scope: a single Australian resident of at least 10 years, from Age Pension
age. The fortnightly rate is the maximum rate less the larger of the assets
test and income test reductions (Services Australia; DSS Social Security
Guide):

* **Maximum rate.** Basic rate plus pension supplement plus energy supplement.
* **Assets test.** Assessable assets above the full-pension limit (homeowner
  or non-homeowner) reduce the rate by ``taper_per_1000`` a fortnight per
  $1,000, pro rata. The principal home is exempt.
* **Income test.** Deemed income from financial assets plus assessable
  employment income after the Work Bonus, above the free area, reduces the
  rate by ``taper`` per dollar.

Deeming applies ``lower_rate`` to financial assets up to the threshold and
``upper_rate`` above it, whatever the assets actually earn. Financial assets
include cash, listed investments, account-based pensions and, from Age Pension
age, super in accumulation.

The taxable part of a payment is the basic rate plus the basic part of the
pension supplement, as a share of the maximum rate. A part pension is split in
the same proportion, which is an approximation: the law reduces the
components in a set order.

Not modelled: couples, transitional rates, Rent Assistance, the pension
loans and home equity schemes, the minimum pension supplement payable to part
pensioners in some cases, gifting and deprivation, and granny-flat interests.
"""

from dataclasses import dataclass

from financial_simulations.rules.au.parameters import RuleSet


FORTNIGHTS = 26


def deemed_income(financial_assets: float, rules: RuleSet) -> float:
    """Annual deemed income on financial assets (single)."""
    deeming = rules["deeming"]
    value = max(0.0, financial_assets)
    lower = min(value, deeming["threshold"])
    return lower * deeming["lower_rate"] + (value - lower) * deeming["upper_rate"]


@dataclass(frozen=True)
class PensionRate:
    """One fortnight's Age Pension and how it was worked out."""

    amount: float
    taxable: float
    maximum: float
    assets_reduction: float
    income_reduction: float
    assessed_assets: float
    assessed_income: float

    @property
    def binding_test(self) -> str:
        if self.amount <= 0:
            return "assets" if self.assets_reduction >= self.income_reduction else "income"
        return "assets" if self.assets_reduction > self.income_reduction else "income"


def maximum_rate(rules: RuleSet) -> float:
    rate = rules["age_pension_rate"]
    return rate["basic"] + rate["supplement"] + rate["energy"]


def fortnightly_rate(assets: float, financial_assets: float, employment_income: float, rules: RuleSet, *,
                     homeowner: bool = True) -> PensionRate:
    """The fortnightly Age Pension for assessable ``assets``, ``financial_assets`` to deem and the fortnight's
    ``employment_income`` already reduced by any Work Bonus."""
    rate, assets_test, income_test = rules["age_pension_rate"], rules["age_pension_assets_test"], rules["age_pension_income_test"]
    maximum = maximum_rate(rules)
    limit = assets_test["homeowner" if homeowner else "non_homeowner"]
    assets_reduction = max(0.0, assets - limit) / 1000 * assets_test["taper_per_1000"]
    income = deemed_income(financial_assets, rules) / FORTNIGHTS + max(0.0, employment_income)
    income_reduction = max(0.0, income - income_test["free_area"]) * income_test["taper"]
    amount = max(0.0, maximum - max(assets_reduction, income_reduction))
    taxable_share = (rate["basic"] + rate["supplement_taxable"]) / maximum
    return PensionRate(amount, amount * taxable_share, maximum, assets_reduction, income_reduction, assets, income)


def apply_work_bonus(employment_income: float, balance: float, rules: RuleSet) -> tuple[float, float]:
    """Credit this fortnight's Work Bonus, offset employment income from the balance and return
    (assessable employment income, new balance)."""
    work = rules["age_pension_income_test"]
    balance = min(balance + work["work_bonus_credit"], work["work_bonus_cap"])
    used = min(balance, max(0.0, employment_income))
    return employment_income - used, balance - used
