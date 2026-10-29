"""A single editable plan file: every input a person sets, validated, importable and exportable.

A plan is a plain nested dictionary that round-trips through TOML or JSON.
``normalize_plan`` fills defaults and reports the field path of every problem,
so the browser form, the command line and hand-edited files all share one
format. ``build_inputs`` turns a valid plan into ledger inputs: a market path,
a ``LedgerScenario`` and projected rule sets.

The planner loads ticker histories from local processed data. Portfolio paths
resample joint USD returns; until FX data exist, retirement paths explicitly
apply those returns as an AUD proxy rather than claiming an observed AUD series.
"""

from datetime import date, timedelta
from importlib.resources import files
import json
from math import isfinite
import re
import tomllib

import numpy as np
import pandas as pd

from financial_simulations.dates import as_date
from financial_simulations.data.plan_markets import load_plan_markets, ticker_name
from financial_simulations.markets.path import MarketPath
from financial_simulations.retirement.ledger import (AssetIncome, Employment, LedgerScenario, Parcel, Pension, Person,
                                                     SpendingRule)
from financial_simulations.rules.au.parameters import financial_year_of, load_ruleset
from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets
from financial_simulations.rules.au.superannuation import birthday


SCHEMA_VERSION = 2
RULES_START = date(2026, 7, 1)
REBALANCE = ("annual", "none")
SAVING = ("surplus", "fixed")
SPENDING_RULES = ("fixed", "guyton_klinger", "vanguard")


class PlanError(ValueError):
    """Every problem found in a plan, each prefixed with its field path."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))

    def __reduce__(self):  # keep the problem list intact across worker processes
        return PlanError, (self.problems,)


def default_plan() -> dict:
    raw = files("financial_simulations.retirement").joinpath("default_plan.toml").read_bytes()
    return normalize_plan(tomllib.loads(raw.decode("utf-8")))


class _Checker:
    def __init__(self):
        self.problems = []

    def number(self, table, key, path, default=None, *, low=None, high=None, integer=False):
        value = table.get(key, default)
        if value is None:
            self.problems.append(f"{path}.{key}: required")
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            self.problems.append(f"{path}.{key}: must be a number")
            return default
        if integer and int(value) != value:
            self.problems.append(f"{path}.{key}: must be a whole number")
        if (low is not None and value < low) or (high is not None and value > high):
            self.problems.append(f"{path}.{key}: must be between {low} and {high}")
        return int(value) if integer else float(value)

    def day(self, table, key, path, default=None, *, optional=False):
        value = table.get(key, default)
        if value is None:
            if not optional:
                self.problems.append(f"{path}.{key}: required (YYYY-MM-DD)")
            return None
        try:
            return as_date(value if not isinstance(value, date) else value).isoformat()
        except ValueError:
            self.problems.append(f"{path}.{key}: must be a date written YYYY-MM-DD")
            return None

    def text(self, table, key, path, default=None):
        value = table.get(key, default)
        if not isinstance(value, str) or not value.strip():
            self.problems.append(f"{path}.{key}: must be nonempty text")
            return default or ""
        return value.strip()

    def choice(self, table, key, path, default, options):
        value = table.get(key, default)
        if value not in options:
            self.problems.append(f"{path}.{key}: must be one of {', '.join(options)}")
            return default
        return value

    def flag(self, table, key, path, default):
        value = table.get(key, default)
        if not isinstance(value, bool):
            self.problems.append(f"{path}.{key}: must be true or false")
            return default
        return value

    def weights(self, table, path, assets):
        weights = table.get("weights", {})
        if not isinstance(weights, dict):
            self.problems.append(f"{path}.weights: must map asset names to fractions")
            return {}
        clean = {}
        for name, value in weights.items():
            if name not in assets:
                self.problems.append(f"{path}.weights.{name}: ticker is not selected under assets")
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                self.problems.append(f"{path}.weights.{name}: must be a nonnegative fraction")
            elif value > 0:
                clean[name] = float(value)
        if clean and abs(sum(clean.values()) - 1) > 1e-6:
            self.problems.append(f"{path}.weights: must sum to 1 (currently {sum(clean.values()):.4g})")
        return clean


def normalize_plan(raw: dict) -> dict:
    """Return a complete plan with defaults; raise ``PlanError`` listing every problem."""
    if not isinstance(raw, dict):
        raise PlanError(["plan: must be a table of sections"])
    c = _Checker()
    known = {"schema_version", "plan", "person", "employment", "assets", "outside", "super", "spending", "pension", "assumptions", "market"}
    c.problems += [f"{k}: unknown section" for k in raw if k not in known]
    if raw.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        c.problems.append(f"schema_version: this tool reads version {SCHEMA_VERSION}; version 1 holdings need a reviewed conversion to portfolio balances and tax positions")
    def section(name):
        value = raw.get(name, {})
        if not isinstance(value, dict):
            c.problems.append(f"{name}: must be a table")
            return {}
        return value

    meta, person, employment = section("plan"), section("person"), section("employment")
    outside, super_, spending, pension, assumptions, market = (section(n) for n in ("outside", "super", "spending", "pension", "assumptions", "market"))
    allowed = {"plan": {"name", "start_date", "years"},
               "person": {"date_of_birth", "retirement_age", "private_hospital_cover"},
               "employment": {"annual_salary", "salary_sacrifice_per_year", "salary_sacrifice_percent", "salary_indexed",
                              "first_payday"},
               "outside": {"cash", "cash_buffer", "investment_balance", "opening_cost_base", "opening_acquired", "weights",
                           "rebalance", "saving", "contribution_per_year", "contribution_indexed", "cash_interest"},
               "super": {"balance", "weights", "rebalance", "total_super_balance_prior_30_june"},
               "spending": {"annual", "annual_growth", "retirement_annual", "rule", "minimum", "guardrail_band",
                            "guardrail_step", "ceiling", "floor"},
               "pension": {"start_age", "transfer_all", "amount"},
               "assumptions": {"cpi_annual", "wage_growth_annual", "planning_age"},
               "market": {"paths", "retirement_paths", "seed", "block_length"}}
    for name, table in (("plan", meta), ("person", person), ("employment", employment), ("outside", outside),
                        ("super", super_), ("spending", spending), ("pension", pension),
                        ("assumptions", assumptions), ("market", market)):
        c.problems.extend(f"{name}.{key}: unknown field in schema version {SCHEMA_VERSION}"
                          for key in table if key not in allowed[name])
    plan = {"schema_version": SCHEMA_VERSION,
            "plan": {"name": c.text(meta, "name", "plan", "My plan"),
                     "start_date": c.day(meta, "start_date", "plan", RULES_START.isoformat()),
                     "years": c.number(meta, "years", "plan", 10, low=1, high=60, integer=True)}}
    if plan["plan"]["start_date"] and as_date(plan["plan"]["start_date"]) < RULES_START:
        c.problems.append("plan.start_date: rules start on 2026-07-01")
    plan["person"] = {"date_of_birth": c.day(person, "date_of_birth", "person"),
                      "retirement_age": c.number(person, "retirement_age", "person", 60, low=18, high=80, integer=True),
                      "private_hospital_cover": c.flag(person, "private_hospital_cover", "person", True)}
    plan["employment"] = {"annual_salary": c.number(employment, "annual_salary", "employment", 0.0, low=0, high=1e8),
                          "salary_sacrifice_per_year": c.number(employment, "salary_sacrifice_per_year", "employment", 0.0, low=0, high=1e7),
                          "salary_sacrifice_percent": c.number(employment, "salary_sacrifice_percent", "employment", 0.0, low=0, high=1),
                          "salary_indexed": c.flag(employment, "salary_indexed", "employment", True),
                          "first_payday": c.day(employment, "first_payday", "employment", optional=True)}
    if sacrifice_per_year(plan) > plan["employment"]["annual_salary"] + 1e-9:
        c.problems.append("employment: salary sacrifice (dollars plus percentage) cannot exceed the salary")
    assets, names = [], set()
    entries = raw.get("assets", [])
    if not isinstance(entries, list) or not entries:
        c.problems.append("assets: select at least one processed ticker")
        entries = []
    for i, entry in enumerate(entries):
        try:
            name = ticker_name(entry)
        except ValueError as exc:
            c.problems.append(f"assets[{i}]: {exc}")
            continue
        if name in names:
            c.problems.append(f"assets[{i}]: duplicate ticker {name}")
        names.add(name)
        assets.append(name)
    plan["assets"] = assets
    plan["outside"] = {"cash": c.number(outside, "cash", "outside", 0.0, low=0, high=1e9),
                       "cash_buffer": c.number(outside, "cash_buffer", "outside", 0.0, low=0, high=1e9),
                       "investment_balance": c.number(outside, "investment_balance", "outside", 0.0, low=0, high=1e9),
                       "opening_cost_base": c.number(outside, "opening_cost_base", "outside", 0.0, low=0, high=1e9),
                       "opening_acquired": c.day(outside, "opening_acquired", "outside", plan["plan"]["start_date"]),
                       "weights": c.weights(outside, "outside", names),
                       "rebalance": c.choice(outside, "rebalance", "outside", "annual", REBALANCE),
                       "saving": c.choice(outside, "saving", "outside", "surplus", SAVING),
                       "contribution_per_year": c.number(outside, "contribution_per_year", "outside", 0.0, low=0, high=1e8),
                       "contribution_indexed": c.flag(outside, "contribution_indexed", "outside", True),
                       "cash_interest": c.number(outside, "cash_interest", "outside", 0.03, low=-0.05, high=0.2)}
    if (plan["outside"]["opening_acquired"] and plan["plan"]["start_date"]
            and plan["outside"]["opening_acquired"] > plan["plan"]["start_date"]):
        c.problems.append("outside.opening_acquired: must be on or before plan.start_date")
    plan["super"] = {"balance": c.number(super_, "balance", "super", 0.0, low=0, high=1e9),
                     "weights": c.weights(super_, "super", names),
                     "rebalance": c.choice(super_, "rebalance", "super", "annual", REBALANCE),
                     "total_super_balance_prior_30_june": c.number(super_, "total_super_balance_prior_30_june", "super",
                                                                   super_.get("balance", 0.0), low=0, high=1e9)}
    if plan["super"]["balance"] > 0 and not plan["super"]["weights"]:
        c.problems.append("super.weights: required when the super balance is positive")
    plan["spending"] = {"annual": c.number(spending, "annual", "spending", 0.0, low=0, high=1e8),
                        "annual_growth": c.number(spending, "annual_growth", "spending", 0.0, low=-0.2, high=0.2)}
    # Spending once retired, in the same first-year dollars; defaults to the pre-retirement amount.
    plan["spending"]["retirement_annual"] = c.number(spending, "retirement_annual", "spending", plan["spending"]["annual"],
                                                     low=0, high=1e8)
    # How retirement spending responds to markets (see SpendingRule); "fixed" keeps the dollar schedule.
    plan["spending"].update({
        "rule": c.choice(spending, "rule", "spending", "fixed", SPENDING_RULES),
        "minimum": c.number(spending, "minimum", "spending", 0.0, low=0, high=1e8),
        "guardrail_band": c.number(spending, "guardrail_band", "spending", 0.20, low=0.01, high=0.9),
        "guardrail_step": c.number(spending, "guardrail_step", "spending", 0.10, low=0.01, high=0.9),
        "ceiling": c.number(spending, "ceiling", "spending", 0.05, low=0, high=0.9),
        "floor": c.number(spending, "floor", "spending", 0.025, low=0, high=0.9)})
    plan["pension"] = {"start_age": c.number(pension, "start_age", "pension", 0, low=0, high=80),
                       "transfer_all": c.flag(pension, "transfer_all", "pension", True),
                       "amount": c.number(pension, "amount", "pension", 0.0, low=0, high=1e9)}
    plan["assumptions"] = {"cpi_annual": c.number(assumptions, "cpi_annual", "assumptions", 0.025, low=-0.1, high=0.2),
                           "wage_growth_annual": c.number(assumptions, "wage_growth_annual", "assumptions", 0.035, low=-0.1, high=0.2),
                           "planning_age": c.number(assumptions, "planning_age", "assumptions", 95, low=60, high=110, integer=True)}
    plan["market"] = {"paths": c.number(market, "paths", "market", 1000, low=16, high=5000, integer=True),
                      "retirement_paths": c.number(market, "retirement_paths", "market", 100, low=1, high=2000, integer=True),
                      "seed": c.number(market, "seed", "market", 20261028, low=0, high=2147483647, integer=True),
                      "block_length": c.number(market, "block_length", "market", 63, low=1, high=1260, integer=True)}
    if not plan["outside"]["weights"]:
        c.problems.append("outside.weights: an outside-super portfolio is required for current and future investments")
    if not plan["super"]["weights"]:
        c.problems.append("super.weights: an inside-super portfolio is required for current and future contributions")
    if plan["market"]["retirement_paths"] > plan["market"]["paths"]:
        c.problems.append("market.retirement_paths: cannot exceed market.paths")
    if c.problems:
        raise PlanError(c.problems)
    return plan


# ------------------------------------------------------------------ files


def _toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"Cannot write {type(value).__name__} to TOML.")


def _toml_key(key):
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def plan_to_toml(plan: dict) -> str:
    """Write a normalized plan as readable TOML (tables, inline weight tables, arrays of tables)."""
    plan = normalize_plan(plan)
    lines = [f"# Retirement plan file, schema version {SCHEMA_VERSION}. Edit here or in the browser app.",
             f"schema_version = {SCHEMA_VERSION}", f"assets = {_toml_value(plan['assets'])}", ""]
    for section in ("plan", "person", "employment", "outside", "super", "spending", "pension", "assumptions", "market"):
        lines.append(f"[{section}]")
        for key, value in plan[section].items():
            if value is None:
                continue
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def plan_to_json(plan: dict) -> str:
    return json.dumps(normalize_plan(plan), indent=2) + "\n"


def load_plan_text(text: str, filename: str = "plan.toml") -> dict:
    """Parse TOML or JSON (by extension, then by content) and normalize."""
    try:
        raw = json.loads(text) if filename.lower().endswith(".json") else tomllib.loads(text)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PlanError([f"{filename}: could not be read as {'JSON' if filename.lower().endswith('.json') else 'TOML'} ({exc})"])
    return normalize_plan(raw)


# ------------------------------------------------------------------ ledger inputs


def latest_supported_end(plan: dict) -> date:
    """The day before the income year in which the person reaches Age Pension age (SAPTO is not modelled)."""
    pension_birthday = birthday(plan["person"]["date_of_birth"], load_ruleset()["age_pension_age"])
    first = pension_birthday.year if pension_birthday.month >= 7 else pension_birthday.year - 1
    return date(first, 6, 30)


def horizon(plan: dict) -> tuple[date, date, bool]:
    """Start, end and whether the requested end was shortened to the supported limit."""
    start = as_date(plan["plan"]["start_date"])
    requested = date(start.year + plan["plan"]["years"], start.month, start.day) - timedelta(days=1)
    limit = latest_supported_end(plan)
    return start, min(requested, limit), requested > limit


def build_inputs(plan: dict, *, market=None, returns=None):
    """Market path, ledger scenario, rule sets and notes for a normalized plan."""
    plan = normalize_plan(plan)
    start, end, shortened = horizon(plan)
    if end <= start:
        raise PlanError(["person.date_of_birth: the person is already at or near Age Pension age; SAPTO and Age Pension are not modelled yet"])
    market = market or load_plan_markets(plan["assets"])
    notes = ["Selected histories and cash contributions are USD. The retirement ledger applies sampled USD returns as an AUD proxy; FX and Australian tax distribution components are not yet available."]
    if shortened:
        notes.append(f"Horizon shortened to {end}: runs stop before the income year in which the person reaches Age Pension age.")
    names = plan["assets"]
    dates = tuple(pd.bdate_range(start, end).date)
    if dates[0] != start:
        dates = (start, *dates)
    if returns is None:
        rates = market.asset_summary.set_index("Ticker").loc[names, "Full-sample CAGR"].to_numpy()
        daily = np.expm1(np.log1p(rates) / 252)
        returns = np.tile(daily, (len(dates) - 1, 1))
        notes.append("This reference path uses each ticker's full-sample CAGR at a constant daily rate.")
    path = MarketPath(dates, tuple(names), returns, "AUD")
    person = Person(plan["person"]["date_of_birth"],
                    retirement_date=birthday(plan["person"]["date_of_birth"], plan["person"]["retirement_age"]),
                    private_hospital_cover=plan["person"]["private_hospital_cover"])
    employment = None
    if plan["employment"]["annual_salary"] > 0:
        first = plan["employment"]["first_payday"] or next(d for d in pd.date_range(start, periods=7).date if d.weekday() == 3).isoformat()
        growth = plan["assumptions"]["wage_growth_annual"] if plan["employment"]["salary_indexed"] else 0.0
        employment = Employment(plan["employment"]["annual_salary"], first, sacrifice_per_year(plan) / 26, annual_growth=growth)
    pension = None
    if plan["pension"]["start_age"] > 0:
        pension = Pension(max(start, birthday(plan["person"]["date_of_birth"], int(plan["pension"]["start_age"]))),
                          None if plan["pension"]["transfer_all"] else plan["pension"]["amount"])
    scenario = LedgerScenario(
        person, outside_cash=plan["outside"]["cash"], cash_buffer=plan["outside"]["cash_buffer"],
        outside_parcels=tuple(Parcel(ticker, plan["outside"]["investment_balance"] * weight,
                                     plan["outside"]["opening_cost_base"] * weight, plan["outside"]["opening_acquired"])
                              for ticker, weight in plan["outside"]["weights"].items() if plan["outside"]["investment_balance"] * weight > 0),
        outside_weights=plan["outside"]["weights"],
        super_units={a: plan["super"]["balance"] * w for a, w in plan["super"]["weights"].items()},
        super_weights=plan["super"]["weights"],
        income={ticker: AssetIncome(market.income_yields[ticker], 0.0) for ticker in names},
        employment=employment, annual_spending=plan["spending"]["annual"], spending_growth=plan["spending"]["annual_growth"],
        retirement_spending=plan["spending"]["retirement_annual"],
        spending_rule=SpendingRule(plan["spending"]["rule"], band=plan["spending"]["guardrail_band"],
                                   step=plan["spending"]["guardrail_step"], ceiling=plan["spending"]["ceiling"],
                                   floor=plan["spending"]["floor"], minimum=plan["spending"]["minimum"]),
        pension=pension, tsb_prior_30_june=plan["super"]["total_super_balance_prior_30_june"],
        outside_rebalance=plan["outside"]["rebalance"] == "annual", super_rebalance=plan["super"]["rebalance"] == "annual",
        outside_contribution_per_payday=(plan["outside"]["contribution_per_year"] / 26 if plan["outside"]["saving"] == "fixed"
                                         else None),
        outside_contribution_growth=plan["assumptions"]["cpi_annual"] if plan["outside"]["contribution_indexed"] else 0.0,
        stop_investing_at_retirement=True, cash_interest=plan["outside"]["cash_interest"], payg_withholding=True)
    years = project_rulesets(load_ruleset("2026-27"), financial_year_of(end),
                             ProjectionAssumptions(plan["assumptions"]["cpi_annual"], plan["assumptions"]["wage_growth_annual"]))
    return path, scenario, years, notes


def sacrifice_per_year(plan: dict) -> float:
    """Salary sacrificed to super each year: the dollar amount plus the percentage of salary."""
    employment = plan["employment"]
    return employment["salary_sacrifice_per_year"] + employment.get("salary_sacrifice_percent", 0.0) * employment["annual_salary"]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "plan"
