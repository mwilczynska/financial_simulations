"""Auditable single-person daily ledger: outside investments, taxed super and pensions in AUD.

Scope and conventions (see docs/methodology/retirement-ledger.md):

* Calendar days from the market path's opening date to its last date. Returns
  apply on observation days; every other cash event happens after the day's
  close. Events needing a sale (spending, tax, pension payments) roll forward
  to the next observation day.
* Estimated income mode: an asset's total return is split into a quarterly
  distribution, paid at the last observation of each calendar quarter and
  removed from the unit price, plus the remaining price return. Total return
  is never counted twice. Yields and franking are labelled assumptions.
* New money buys the target weights. Holdings drift between optional annual
  rebalances, which reset each account to its weights at pre-return values on
  the first return observation of each calendar year. Outside super a
  rebalance sells overweight parcels (oldest first) and realises CGT; inside
  super it is a unit switch. Funds are assumed not to realise gains (no fund
  CGT), so super rebalancing is untaxed.
* Salary is paid gross. Income tax is assessed at 30 June and settled on a
  configurable later date. With ``payg_withholding`` each payday withholds a
  26th of the estimated tax on a full year's salary, and the settlement pays
  or refunds only the balance. Tax that no
  account can fund is recorded as unpaid (``tax_unpaid``) and the run
  continues; ATO payment plans and the general interest charge are not
  modelled.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from math import isfinite

import pandas as pd

from financial_simulations.dates import as_date
from financial_simulations.markets.path import MarketPath
from financial_simulations.rules.au.parameters import RuleSet, UnsupportedRule, financial_year_of
from financial_simulations.rules.au.superannuation import (
    TransferBalanceAccount, access_date, add_business_days, age_on, apply_concessional, apply_non_concessional, birthday,
    concessional_cap, minimum_pension_payment, require_below_division_296, require_tax_free_benefits, super_guarantee)
from financial_simulations.rules.au.tax import CapitalGainEvent, IncomeYear, assess, post_reform_gain


TOLERANCE = 1e-6


def _money(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be a finite {'positive' if positive else 'nonnegative'} amount.")
    return float(value)


def _weights(weights, assets, name):
    if set(weights) - set(assets) or not weights or abs(sum(weights.values()) - 1) > 1e-10 or min(weights.values()) < 0:
        raise ValueError(f"{name} must be nonnegative weights over path assets summing to one.")
    return {a: float(weights.get(a, 0.0)) for a in assets}


@dataclass(frozen=True)
class AssetIncome:
    """Assumed income split of an asset's total return (estimated mode)."""

    annual_yield: float = 0.0
    franked_fraction: float = 0.0
    company_tax_rate: float = 0.30

    def __post_init__(self):
        if not 0 <= self.annual_yield < 1 or not 0 <= self.franked_fraction <= 1 or not 0 < self.company_tax_rate < 1:
            raise ValueError("Yield must be in [0, 1), franked fraction in [0, 1] and company tax rate in (0, 1).")


@dataclass(frozen=True)
class Parcel:
    """A CGT parcel. ``reform_value`` is its market value just before 1 July 2027, if held then."""

    asset: str
    units: float
    cost_base: float
    acquired: date
    reform_value: float | None = None

    def __post_init__(self):
        object.__setattr__(self, "acquired", as_date(self.acquired))
        _money(self.units, "Parcel units", positive=True)
        _money(self.cost_base, "Parcel cost base")
        if self.reform_value is not None:
            _money(self.reform_value, "Parcel 1 July 2027 market value")


@dataclass(frozen=True)
class Person:
    born: date
    retirement_date: date | None = None
    private_hospital_cover: bool = True

    def __post_init__(self):
        object.__setattr__(self, "born", as_date(self.born))
        if self.retirement_date is not None:
            object.__setattr__(self, "retirement_date", as_date(self.retirement_date))


@dataclass(frozen=True)
class Employment:
    """Fortnightly gross salary until the retirement date; salary sacrifice is per payday."""

    annual_salary: float
    first_payday: date
    salary_sacrifice_per_payday: float = 0.0
    contribution_lag_business_days: int = 7

    def __post_init__(self):
        object.__setattr__(self, "first_payday", as_date(self.first_payday))
        _money(self.annual_salary, "Annual salary")
        _money(self.salary_sacrifice_per_payday, "Salary sacrifice")
        if self.salary_sacrifice_per_payday > self.annual_salary / 26:
            raise ValueError("Salary sacrifice cannot exceed the gross payday salary.")


@dataclass(frozen=True)
class Pension:
    """Move ``amount`` into an account-based pension; None moves the whole balance up to the transfer balance cap."""

    commence: date
    amount: float | None = None

    def __post_init__(self):
        object.__setattr__(self, "commence", as_date(self.commence))
        if self.amount is not None:
            _money(self.amount, "Pension transfer", positive=True)


@dataclass(frozen=True)
class LedgerScenario:
    person: Person
    outside_cash: float = 0.0
    outside_parcels: tuple[Parcel, ...] = ()
    outside_weights: dict = field(default_factory=dict)
    cash_buffer: float = 0.0
    super_units: dict = field(default_factory=dict)
    super_weights: dict = field(default_factory=dict)
    income: dict = field(default_factory=dict)
    employment: Employment | None = None
    annual_spending: float = 0.0
    spending_growth: float = 0.0
    non_concessional: tuple[tuple[date, float], ...] = ()
    pension: Pension | None = None
    tax_settlement_month_day: tuple[int, int] = (10, 31)
    tsb_prior_30_june: float | None = None
    unused_concessional: dict = field(default_factory=dict)
    capital_losses_brought_forward: float = 0.0
    outside_rebalance: bool = False
    super_rebalance: bool = False
    # None invests all cash above the buffer; an amount invests only that much on each payday.
    outside_contribution_per_payday: float | None = None
    outside_contribution_growth: float = 0.0  # applied each 1 July, like spending growth
    stop_investing_at_retirement: bool = False
    cash_interest: float = 0.0  # annual effective rate on outside cash, credited daily and taxed as interest
    payg_withholding: bool = False
    retirement_spending: float | None = None  # annual spending from the retirement date (same base year), if different  # withhold estimated salary tax each payday; the assessment settles the balance


@dataclass
class _State:
    cash: float
    parcels: list
    outside_units: dict
    super_acc: dict
    super_pen: dict
    prices: dict
    tba: TransferBalanceAccount | None = None
    pension_minimum: float = 0.0
    pension_paid: float = 0.0
    liabilities: list = field(default_factory=list)
    pending: list = field(default_factory=list)
    fy: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LedgerResult:
    daily: pd.DataFrame
    events: pd.DataFrame
    annual: list
    outstanding: dict


def _last_observation_per(dates, key):
    last = {}
    for d in dates:
        last[key(d)] = d
    return set(last.values())


def _value(units, prices):
    total = 0.0
    for asset, held in units.items():
        if held:
            total += held * prices[asset]
    return total


def run_ledger(path: MarketPath, scenario: LedgerScenario, rules_by_year: dict) -> LedgerResult:
    """Run the daily ledger; unsupported rules or missing rule years raise ``UnsupportedRule``."""
    if path.currency != "AUD":
        raise ValueError("The retirement ledger accounts in AUD; convert or supply an AUD market path.")
    assets, person = path.assets, scenario.person
    start, end = path.dates[0], path.dates[-1]
    check = start
    while check <= end:
        if financial_year_of(check) not in rules_by_year:
            raise UnsupportedRule(f"No rule set for {financial_year_of(check)}; the ledger cannot run past {check - timedelta(days=1)}.")
        check = date(check.year + (check.month >= 7), 7, 1)
    day = start
    for fy, rules in rules_by_year.items():
        if rules.financial_year != fy:
            raise ValueError("rules_by_year keys must match each rule set's financial year.")
    income = {a: scenario.income.get(a, AssetIncome()) for a in assets}
    if set(scenario.super_units) - set(assets) or any(not 0 <= u < float("inf") for u in scenario.super_units.values()):
        raise ValueError("Super units must be nonnegative and over path assets.")
    reform = as_date(next(iter(rules_by_year.values()))["cgt_reform_start"])
    for parcel in scenario.outside_parcels:
        if parcel.asset not in assets or parcel.acquired > start:
            raise ValueError("Opening parcels must hold path assets acquired on or before the opening date.")
        if start > reform and parcel.acquired < reform and parcel.reform_value is None:
            raise ValueError("Parcels held on 30 June 2027 need their market value just before 1 July 2027.")
    # Without explicit weights, new money follows the opening holdings (opening unit prices are 1).
    opening_outside = {a: sum(p.units for p in scenario.outside_parcels if p.asset == a) for a in assets}
    outside_weights = _default_weights(scenario.outside_weights, opening_outside, assets, "Outside weights")
    super_weights = _default_weights(scenario.super_weights, scenario.super_units, assets, "Super weights")
    observations = {d: i for i, d in enumerate(path.dates)}
    rebalance_days = {d for previous, d in zip(path.dates, path.dates[1:]) if d.year != previous.year}
    quarter_ends = _last_observation_per(path.dates, lambda d: (d.year, (d.month - 1) // 3))
    month_ends = _last_observation_per(path.dates, lambda d: (d.year, d.month))
    state = _State(_money(scenario.outside_cash, "Outside cash"), list(scenario.outside_parcels), dict(opening_outside),
                   {a: float(scenario.super_units.get(a, 0.0)) for a in assets}, {a: 0.0 for a in assets},
                   {a: 1.0 for a in assets})
    events, rows, annual = [], [], []
    paydays = set()
    if scenario.employment:
        payday = scenario.employment.first_payday
        while payday <= end and (person.retirement_date is None or payday < person.retirement_date):
            if payday >= start:
                paydays.add(payday)
            payday += timedelta(days=14)
    nonconcessional = {}
    for when, amount in scenario.non_concessional:
        nonconcessional.setdefault(as_date(when), 0.0)
        nonconcessional[as_date(when)] += _money(amount, "Non-concessional contribution", positive=True)
    tsb_prior = scenario.tsb_prior_30_june
    if tsb_prior is None:
        tsb_prior = _value(state.super_acc, state.prices)
    unused, losses_bf, period = dict(scenario.unused_concessional), float(scenario.capital_losses_brought_forward), None
    spending_due, unpaid_tax = [], []
    if not -0.5 < scenario.cash_interest < 1:
        raise ValueError("Cash interest must be an annual rate between -50% and 100%.")
    daily_interest = (1 + scenario.cash_interest) ** (1 / 365.25) - 1
    saving_due = 0.0
    if scenario.outside_contribution_per_payday is not None:
        _money(scenario.outside_contribution_per_payday, "Outside contribution")
    access = access_date(person.born, next(iter(rules_by_year.values())), person.retirement_date)

    def log(kind, amount, account, **detail):
        events.append({"date": day, "event": kind, "account": account, "amount": float(amount), **detail})

    def start_year(rules):
        nonlocal unused
        if birthday(person.born, rules["age_pension_age"]) <= rules.end:
            raise UnsupportedRule(f"The person reaches Age Pension age by {rules.end}; SAPTO and Age Pension are not implemented.")
        cap = concessional_cap(rules, tsb_prior, unused)
        state.fy = {"rules": rules, "cap": cap, "concessional": 0.0, "non_concessional": 0.0, "labour": 0.0,
                    "sacrifice": 0.0, "unfranked": 0.0, "franked": 0.0, "credits": 0.0, "events": [],
                    "acc_income": 0.0, "acc_credits": 0.0, "pen_credits": 0.0, "spending": 0.0, "shortfall": 0.0,
                    "interest": 0.0, "withheld": 0.0, "withhold_per_pay": 0.0}
        if scenario.payg_withholding and scenario.employment:
            # Estimated tax on a full year's salary, spread over 26 paydays. Like PAYG it ignores investment
            # income and part-year work; the 30 June assessment settles any difference.
            employment = scenario.employment
            sacrifice = employment.salary_sacrifice_per_payday * 26
            concessional = rules["super_guarantee_rate"] * min(employment.annual_salary, rules["maximum_contribution_base"])
            estimate = assess(IncomeYear(labour_income=employment.annual_salary - sacrifice, reportable_employer_super=sacrifice,
                                         low_tax_contributions=concessional + sacrifice,
                                         private_hospital_cover=person.private_hospital_cover), rules)
            state.fy["withhold_per_pay"] = estimate.net_tax / 26
        if state.tba is not None:
            pension_value = _value(state.super_pen, state.prices)
            state.pension_minimum = minimum_pension_payment(pension_value, person.born, rules)
            state.pension_paid = 0.0

    def buy(units_map, weights, amount, account):
        if weights is None:
            raise ValueError(f"Supply {account} weights: there are no opening holdings to follow.")
        for asset, weight in weights.items():
            if weight > 0:
                units_map[asset] = units_map.get(asset, 0.0) + amount * weight / state.prices[asset]
        log("buy", amount, account)

    def buy_outside(amount, amounts=None, purpose="investment"):
        """Buy new parcels: ``amount`` at the target weights, or explicit per-asset ``amounts``."""
        if amounts is None:
            if outside_weights is None:
                raise ValueError("Supply outside weights: there are no opening holdings to follow.")
            amounts = {asset: amount * weight for asset, weight in outside_weights.items()}
        for asset, spend in amounts.items():
            if spend > 0:
                units = spend / state.prices[asset]
                state.parcels.append(Parcel(asset, units, spend, day))
                state.outside_units[asset] += units
        log("buy", sum(amounts.values()), "outside", purpose=purpose)

    def sell_outside(amount):
        """Sell proportionally across assets by value, oldest parcels first within each asset."""
        holdings = {a: state.outside_units[a] * state.prices[a] for a in assets}
        total = sum(holdings.values())
        amount = min(amount, total)
        if amount <= 0:
            return 0.0
        sell_parcels({a: amount * v / total for a, v in holdings.items()}, "withdrawal")
        return amount

    def sell_parcels(targets, purpose):
        """Sell ``targets`` (AUD by asset), oldest parcels first; record each CGT event."""
        remaining_parcels = []
        targets = dict(targets)
        sold_total = 0.0
        for parcel in sorted(state.parcels, key=lambda p: p.acquired):
            target = targets.get(parcel.asset, 0.0)
            value = parcel.units * state.prices[parcel.asset]
            if target <= TOLERANCE or value <= 0:
                remaining_parcels.append(parcel)
                continue
            sold = min(value, target)
            fraction = sold / value
            cost = parcel.cost_base * fraction
            if day < reform:
                gains = [CapitalGainEvent(parcel.acquired, day, sold - cost)]
            else:
                cpi = state.fy["rules"]["assumed_cpi_annual"]
                if parcel.reform_value is None:  # acquired from 1 July 2027
                    gains = [CapitalGainEvent(parcel.acquired, day, post_reform_gain(cost, sold, parcel.acquired, day,
                                                                                     parcel.acquired, cpi), "post_reform")]
                else:  # deemed sale just before, and reacquisition on, 1 July 2027
                    reacquired = parcel.reform_value * fraction
                    gains = [CapitalGainEvent(parcel.acquired, day, reacquired - cost, "deferred"),
                             CapitalGainEvent(parcel.acquired, day, post_reform_gain(reacquired, sold, reform, day,
                                                                                     parcel.acquired, cpi), "post_reform")]
            state.fy["events"].extend(gains)
            log("sale", sold, "outside", asset=parcel.asset, gain=sum(g.amount for g in gains), acquired=str(parcel.acquired),
                purpose=purpose, **{f"{g.category}_gain": g.amount for g in gains})
            targets[parcel.asset] = target - sold
            sold_total += sold
            if fraction < 1 - 1e-12:
                remaining_parcels.append(Parcel(parcel.asset, parcel.units * (1 - fraction), parcel.cost_base - cost, parcel.acquired,
                                                None if parcel.reform_value is None else parcel.reform_value * (1 - fraction)))
        state.parcels = remaining_parcels
        state.outside_units = {a: 0.0 for a in assets}
        for parcel in remaining_parcels:
            state.outside_units[parcel.asset] += parcel.units
        return sold_total

    def rebalance():
        """Reset accounts to target weights at pre-return values; outside sales realise CGT."""
        if scenario.outside_rebalance and outside_weights is not None:
            holdings = {a: state.outside_units[a] * state.prices[a] for a in assets}
            total = sum(holdings.values())
            excess = {a: holdings[a] - total * outside_weights[a] for a in assets}
            sells = {a: v for a, v in excess.items() if v > TOLERANCE}
            buys = {a: -v for a, v in excess.items() if v < -TOLERANCE}
            if sells and buys:
                proceeds = sell_parcels(sells, "rebalance")
                scale = proceeds / sum(buys.values())
                buy_outside(0.0, {a: v * scale for a, v in buys.items()}, "rebalance")
        if scenario.super_rebalance and super_weights is not None:
            for account, units_map in (("accumulation", state.super_acc), ("pension", state.super_pen)):
                total = _value(units_map, state.prices)
                if total > TOLERANCE:
                    for asset in assets:
                        units_map[asset] = total * super_weights[asset] / state.prices[asset]
                    log("rebalance", total, account)

    def sell_units(units_map, amount):
        value = _value(units_map, state.prices)
        amount = min(amount, value)
        if amount > 0:
            for asset in units_map:
                units_map[asset] *= 1 - amount / value
        return amount

    def pay_need(need, kind):
        """Waterfall: cash, outside sales, accessible accumulation, then extra pension payments."""
        paid = min(state.cash, need)
        state.cash -= paid
        rules = state.fy["rules"]
        if paid < need - TOLERANCE:
            proceeds = sell_outside(need - paid)
            paid += proceeds
        if paid < need - TOLERANCE and day >= access:
            require_tax_free_benefits(person.born, rules, day)
            lump = sell_units(state.super_acc, need - paid)
            if lump:
                flows["lump_sums"] += lump
                log("lump_sum", lump, "accumulation")
            paid += lump
        if paid < need - TOLERANCE and state.tba is not None:
            extra = sell_units(state.super_pen, need - paid)
            if extra:
                state.pension_paid += extra
                flows["pension_payments"] += extra
                log("pension_payment", extra, "pension", purpose=kind)
            paid += extra
        shortfall = need - paid
        if shortfall <= TOLERANCE:  # rounding residue from proportional sales, not an unmet need
            return paid, 0.0
        log("shortfall", shortfall, "outside", purpose=kind)
        return paid, shortfall

    start_year(rules_by_year[financial_year_of(start)])
    closing = None
    while day <= end:
        rules = rules_by_year[financial_year_of(day)]
        if (day.month, day.day) == (7, 1) and day != start:
            start_year(rules)
        if day == reform:
            # Market value just before 1 July 2027 is the 30 June close, before today's return.
            state.parcels = [Parcel(p.asset, p.units, p.cost_base, p.acquired, p.units * state.prices[p.asset])
                             if p.acquired < reform and p.reform_value is None else p for p in state.parcels]
            log("cgt_reform_valuation", sum(p.reform_value or 0.0 for p in state.parcels), "outside")
        flows = {k: 0.0 for k in ("market_pnl", "salary", "employer_contributions", "contributions_tax", "spending_paid",
                                  "shortfall", "tax_paid", "tax_unpaid", "fund_tax", "distributions", "pension_payments",
                                  "lump_sums", "interest")}
        # Nothing changes overnight, so the opening value is the previous close.
        opening = closing if closing is not None else (state.cash + _value(state.outside_units, state.prices)
                                                       + _value(state.super_acc, state.prices) + _value(state.super_pen, state.prices))
        if daily_interest and state.cash > 0:
            # Interest on the previous close's cash, credited every calendar day.
            interest = state.cash * daily_interest
            state.cash += interest
            state.fy["interest"] += interest
            flows["interest"] = interest
        observation = observations.get(day)
        if day in rebalance_days:
            rebalance()
        if observation:
            for i, asset in enumerate(assets):
                state.prices[asset] *= 1 + path.returns[observation - 1, i]
            flows["market_pnl"] = (state.cash + _value(state.outside_units, state.prices)
                                   + _value(state.super_acc, state.prices) + _value(state.super_pen, state.prices)
                                   - opening - flows["interest"])
        if day in quarter_ends:
            for asset in assets:
                q = income[asset].annual_yield / 4
                if q <= 0:
                    continue
                per_unit = q * state.prices[asset]
                state.prices[asset] -= per_unit
                spec = income[asset]
                credit_ratio = spec.company_tax_rate / (1 - spec.company_tax_rate)
                outside_units = state.outside_units[asset]
                if outside_units:
                    cash = per_unit * outside_units
                    state.cash += cash
                    state.fy["franked"] += cash * spec.franked_fraction
                    state.fy["unfranked"] += cash * (1 - spec.franked_fraction)
                    state.fy["credits"] += cash * spec.franked_fraction * credit_ratio
                    flows["distributions"] += cash
                    log("distribution", cash, "outside", asset=asset)
                for account, units_map in (("accumulation", state.super_acc), ("pension", state.super_pen)):
                    if units_map[asset]:
                        cash = per_unit * units_map[asset]
                        key = "acc" if account == "accumulation" else "pen"
                        if key == "acc":
                            state.fy["acc_income"] += cash
                        state.fy[f"{key}_credits"] += cash * spec.franked_fraction * credit_ratio
                        log("distribution", cash, account, asset=asset)
                        buy(units_map, super_weights, cash, account)
        if day in paydays:
            employment = scenario.employment
            gross = employment.annual_salary / 26
            sacrifice = employment.salary_sacrifice_per_payday
            sg = super_guarantee(gross, state.fy["labour"] + state.fy["sacrifice"], rules)
            state.cash += gross - sacrifice
            state.fy["labour"] += gross - sacrifice
            state.fy["sacrifice"] += sacrifice
            flows["salary"] += gross - sacrifice
            log("salary", gross - sacrifice, "outside", sacrifice=sacrifice, super_guarantee=sg)
            withheld = state.fy["withhold_per_pay"]
            if withheld > 0:
                state.cash -= withheld
                state.fy["withheld"] += withheld
                flows["tax_paid"] += withheld
                log("payg_withholding", withheld, "outside")
            if scenario.outside_contribution_per_payday:
                saving_due += (scenario.outside_contribution_per_payday
                               * (1 + scenario.outside_contribution_growth) ** _years_since(start, day))
            state.pending.append((add_business_days(day, employment.contribution_lag_business_days), sg + sacrifice, sacrifice))
        arrived = [p for p in state.pending if p[0] == day]
        state.pending = [p for p in state.pending if p[0] != day]
        for _, amount, sacrifice in arrived:
            state.fy["concessional"] += amount
            if state.fy["concessional"] > state.fy["cap"].available + TOLERANCE:
                raise UnsupportedRule("Concessional contributions exceed the available cap; excess contributions are not modelled.")
            tax = rules["contributions_tax_rate"] * amount
            flows["employer_contributions"] += amount
            flows["contributions_tax"] += tax
            log("concessional_contribution", amount, "accumulation", contributions_tax=tax, salary_sacrifice=sacrifice)
            buy(state.super_acc, super_weights, amount - tax, "accumulation")
        if day in nonconcessional:
            amount = nonconcessional.pop(day)
            if amount > state.cash + TOLERANCE:
                raise ValueError("Non-concessional contributions must be funded from outside cash on hand.")
            period = apply_non_concessional(state.fy["non_concessional"] + amount, rules, tsb_prior,
                                            _under_75(person.born, rules), period)
            state.fy["non_concessional"] += amount
            state.cash -= amount
            log("non_concessional_contribution", amount, "accumulation")
            buy(state.super_acc, super_weights, amount, "accumulation")
        if scenario.pension and day == scenario.pension.commence:
            if day < access:
                raise UnsupportedRule("An account-based pension needs an unrestricted condition of release; transition to retirement is not modelled.")
            require_tax_free_benefits(person.born, rules, day)
            balance = _value(state.super_acc, state.prices)
            account = state.tba or TransferBalanceAccount(rules["transfer_balance_cap"])
            # "Whole balance" moves as much as the transfer balance cap allows; the rest stays in accumulation.
            amount = min(balance, account.cap - account.balance) if scenario.pension.amount is None else scenario.pension.amount
            if amount > balance + TOLERANCE:
                raise ValueError("Pension transfer exceeds the accumulation balance.")
            state.tba = account.credit(amount)
            fraction = amount / balance if balance > 0 else 0.0
            for asset in assets:
                moved = state.super_acc[asset] * fraction
                state.super_acc[asset] -= moved
                state.super_pen[asset] += moved
            state.pension_minimum = minimum_pension_payment(amount, person.born, rules, commenced=day)
            state.pension_paid = 0.0
            log("pension_commencement", amount, "pension", transfer_balance=state.tba.balance, minimum=state.pension_minimum)
        if day == start or day.day == 1:
            base = scenario.annual_spending
            if (scenario.retirement_spending is not None and person.retirement_date is not None
                    and day >= person.retirement_date):
                base = scenario.retirement_spending
            spending_due.append((day, base * (1 + scenario.spending_growth) ** _years_since(start, day) / 12))
        if observation is not None:
            for when, need in [s for s in spending_due if s[1] > 0]:
                paid, short = pay_need(need, "spending")
                flows["spending_paid"] += paid
                flows["shortfall"] += short
                state.fy["spending"] += paid
                state.fy["shortfall"] += short
                log("spending", paid, "outside", requested=need, scheduled=str(when))
            spending_due = []
            due = [l for l in state.liabilities if l["due"] <= day]
            state.liabilities = [l for l in state.liabilities if l["due"] > day]
            for liability in due:
                if liability["amount"] >= 0:
                    paid, short = pay_need(liability["amount"], "tax")
                    if short > TOLERANCE:
                        # Every account is exhausted: record the debt and continue, without the general interest charge.
                        flows["tax_unpaid"] += short
                        unpaid_tax.append({"financial_year": liability["financial_year"], "due": str(day), "amount": short})
                    flows["tax_paid"] += paid
                else:
                    state.cash -= liability["amount"]
                    flows["tax_paid"] += liability["amount"]
                log("tax_settlement", liability["amount"], "outside", financial_year=liability["financial_year"])
            if state.tba is not None and day in month_ends:
                months_left = (rules.end.year - day.year) * 12 + rules.end.month - day.month + 1
                instalment = max(0.0, state.pension_minimum - state.pension_paid) / months_left
                if instalment > TOLERANCE:
                    paid = sell_units(state.super_pen, instalment)
                    state.pension_paid += paid
                    state.cash += paid
                    flows["pension_payments"] += paid
                    log("pension_payment", paid, "pension", purpose="minimum")
            # New money is invested at each observation close, after the day's needs: either all cash above the
            # buffer, or the scheduled payday contributions as far as cash above the buffer allows (no catch-up).
            investing = not (scenario.stop_investing_at_retirement and person.retirement_date is not None
                             and day >= person.retirement_date)
            available = state.cash - scenario.cash_buffer
            amount = available if scenario.outside_contribution_per_payday is None else min(saving_due, available)
            saving_due = 0.0
            if investing and amount > TOLERANCE:
                state.cash -= amount
                buy_outside(amount)
        if day == rules.end:
            fy = state.fy
            year = IncomeYear(labour_income=fy["labour"], interest=fy["interest"], unfranked_dividends=fy["unfranked"],
                              franked_dividends=fy["franked"],
                              franking_credits=fy["credits"], capital_events=tuple(fy["events"]),
                              capital_losses_brought_forward=losses_bf, reportable_employer_super=fy["sacrifice"],
                              low_tax_contributions=fy["concessional"],
                              private_hospital_cover=person.private_hospital_cover)
            assessment = assess(year, rules)
            losses_bf = assessment.capital_losses_carried_forward
            due = date(rules.end.year + (scenario.tax_settlement_month_day[0] <= 6), *scenario.tax_settlement_month_day)
            # Withholding already paid counts against the assessment; a negative balance is a refund.
            state.liabilities.append({"due": due, "amount": assessment.net_tax + assessment.division_293_tax - fy["withheld"],
                                      "financial_year": rules.financial_year})
            accumulation_tax = rules["fund_earnings_tax_rate"] * (fy["acc_income"] + fy["acc_credits"]) - fy["acc_credits"]
            if accumulation_tax > 0:
                flows["fund_tax"] += sell_units(state.super_acc, accumulation_tax)
            elif accumulation_tax < 0 and any(state.super_acc.values()):
                buy(state.super_acc, super_weights, -accumulation_tax, "accumulation")
                flows["fund_tax"] += accumulation_tax
            if fy["pen_credits"] > 0 and state.tba is not None:
                buy(state.super_pen, super_weights, fy["pen_credits"], "pension")
                flows["fund_tax"] -= fy["pen_credits"]
            log("fund_tax", flows["fund_tax"], "super", accumulation_income=fy["acc_income"])
            if (state.tba is not None and state.pension_paid < state.pension_minimum - TOLERANCE
                    and _value(state.super_pen, state.prices) > TOLERANCE):
                raise ArithmeticError("Pension minimum was not met by 30 June.")
            unused = apply_concessional(fy["concessional"], fy["cap"], unused, rules)
            tsb_prior = _value(state.super_acc, state.prices) + _value(state.super_pen, state.prices)
            require_below_division_296(tsb_prior, rules)
            annual.append({"financial_year": rules.financial_year, "assessment": assessment, "tax_due": str(due),
                           "concessional_contributions": fy["concessional"], "concessional_cap_available": fy["cap"].available,
                           "non_concessional_contributions": fy["non_concessional"], "accumulation_tax": accumulation_tax,
                           "pension_minimum": state.pension_minimum if state.tba else None,
                           "pension_paid": state.pension_paid if state.tba else None,
                           "total_super_balance_30_june": tsb_prior, "spending_paid": fy["spending"],
                           "shortfall": fy["shortfall"], "unused_concessional_after": dict(unused),
                           "transfer_balance": state.tba.balance if state.tba else None})
            log("assessment", assessment.net_tax, "outside", financial_year=rules.financial_year,
                taxable_income=assessment.taxable_income, division_293=assessment.division_293_tax)
        outside_value = _value(state.outside_units, state.prices)
        acc_value, pen_value = _value(state.super_acc, state.prices), _value(state.super_pen, state.prices)
        total = state.cash + outside_value + acc_value + pen_value
        expected = (opening + flows["market_pnl"] + flows["salary"] + flows["employer_contributions"] + flows["interest"]
                    - flows["contributions_tax"] - flows["spending_paid"] - flows["tax_paid"] - flows["fund_tax"])
        if abs(total - expected) > 1e-6 + 1e-11 * abs(expected):
            raise ArithmeticError(f"Ledger reconciliation failed on {day}: {total} != {expected}.")
        closing = total
        rows.append({"date": day, "is_observation": observation is not None, "cash": state.cash,
                     "outside_investments": outside_value, "accumulation": acc_value, "pension": pen_value,
                     "total": total, "super_accessible": day >= access, **flows,
                     "pending_contributions": sum(p[1] for p in state.pending),
                     "tax_liabilities": sum(l["amount"] for l in state.liabilities)})
        day += timedelta(days=1)
    daily = pd.DataFrame(rows).set_index("date")
    daily.index = pd.DatetimeIndex(daily.index, name="Date")
    last = day - timedelta(days=1)
    unassessed = None
    if last != state.fy["rules"].end:
        fy = state.fy
        unassessed = {"financial_year": fy["rules"].financial_year, "through": str(last), "labour_income": fy["labour"],
                      "franked_distributions": fy["franked"], "unfranked_distributions": fy["unfranked"],
                      "franking_credits": fy["credits"], "capital_gain_events": len(fy["events"]),
                      "net_realised_gains": sum(e.amount for e in fy["events"]),
                      "concessional_contributions": fy["concessional"], "accumulation_income": fy["acc_income"],
                      "interest": fy["interest"], "payg_withheld": fy["withheld"]}
    outstanding = {"tax_liabilities": [dict(l, due=str(l["due"])) for l in state.liabilities],
                   "unpaid_tax": unpaid_tax,
                   "unassessed_year": unassessed,
                   "pending_contributions": [{"due": str(d), "amount": a} for d, a, _ in state.pending],
                   "unscheduled_spending": [{"scheduled": str(d), "amount": a} for d, a in spending_due if a > 0],
                   "capital_losses_carried_forward": losses_bf, "unused_concessional": unused,
                   "total_super_balance_30_june": tsb_prior}
    return LedgerResult(daily, pd.DataFrame(events), annual, outstanding)


def _default_weights(weights, units, assets, name):
    if weights:
        return _weights(weights, assets, name)
    total = sum(units.values())
    return {a: units.get(a, 0.0) / total for a in assets} if total > 0 else None


def _years_since(start, day):
    """Whole financial years elapsed since the opening date's year; spending steps up each 1 July."""
    return int(financial_year_of(day)[:4]) - int(financial_year_of(start)[:4])


def _under_75(born, rules: RuleSet):
    # Under 75 at any time in the year means under 75 on 1 July.
    return age_on(born, rules.start) < 75
