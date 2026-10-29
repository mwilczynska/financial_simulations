"""A single editable plan file: every input a person sets, validated, importable and exportable.

A plan is a plain nested dictionary that round-trips through TOML or JSON.
``normalize_plan`` fills defaults and reports the field path of every problem,
so the browser form, the command line and hand-edited files all share one
format. ``build_inputs`` turns a valid plan into ledger inputs: a market path,
a ``LedgerScenario`` and projected rule sets.

Until AUD market data are added, a plan's market input is a deterministic AUD
path built from each asset's assumed annual total return. It is labelled as
such in every output.
"""

from copy import deepcopy
from datetime import date, timedelta
from importlib.resources import files
import json
from math import isfinite
import re
import tomllib

import numpy as np
import pandas as pd

from financial_simulations.dates import as_date
from financial_simulations.markets.path import MarketPath
from financial_simulations.retirement.ledger import (AssetIncome, Employment, LedgerScenario, Parcel, Pension, Person)
from financial_simulations.rules.au.parameters import financial_year_of, load_ruleset
from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets
from financial_simulations.rules.au.superannuation import birthday


SCHEMA_VERSION = 1
RULES_START = date(2026, 7, 1)


class PlanError(ValueError):
    """Every problem found in a plan, each prefixed with its field path."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


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
                self.problems.append(f"{path}.weights.{name}: unknown asset (define it under [[assets]])")
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
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
    known = {"schema_version", "plan", "person", "employment", "assets", "outside", "super", "spending", "pension", "assumptions"}
    c.problems += [f"{k}: unknown section" for k in raw if k not in known]
    if raw.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        c.problems.append(f"schema_version: this tool reads version {SCHEMA_VERSION}")
    def section(name):
        value = raw.get(name, {})
        if not isinstance(value, dict):
            c.problems.append(f"{name}: must be a table")
            return {}
        return value

    meta, person, employment = section("plan"), section("person"), section("employment")
    outside, super_, spending, pension, assumptions = (section(n) for n in ("outside", "super", "spending", "pension", "assumptions"))
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
                          "first_payday": c.day(employment, "first_payday", "employment", optional=True)}
    assets, names = [], set()
    entries = raw.get("assets", [])
    if not isinstance(entries, list) or not entries:
        c.problems.append("assets: define at least one [[assets]] entry")
        entries = []
    for i, entry in enumerate(entries):
        path = f"assets[{i}]"
        entry = entry if isinstance(entry, dict) else {}
        name = c.text(entry, "name", path)
        if name and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            c.problems.append(f"{path}.name: use letters, digits and underscores, starting with a letter")
        if name in names:
            c.problems.append(f"{path}.name: duplicate asset {name}")
        names.add(name)
        assets.append({"name": name, "label": entry.get("label", name) if isinstance(entry.get("label", name), str) else name,
                       "annual_return": c.number(entry, "annual_return", path, 0.06, low=-0.5, high=0.5),
                       "income_yield": c.number(entry, "income_yield", path, 0.0, low=0, high=0.5),
                       "franked_fraction": c.number(entry, "franked_fraction", path, 0.0, low=0, high=1)})
    plan["assets"] = assets
    holdings = []
    for i, entry in enumerate(outside.get("holdings", []) if isinstance(outside.get("holdings", []), list) else []):
        path = f"outside.holdings[{i}]"
        entry = entry if isinstance(entry, dict) else {}
        asset = entry.get("asset")
        if asset not in names:
            c.problems.append(f"{path}.asset: unknown asset {asset!r}")
        holdings.append({"asset": asset, "value": c.number(entry, "value", path, 0.0, low=0, high=1e9),
                         "cost_base": c.number(entry, "cost_base", path, 0.0, low=0, high=1e9),
                         "acquired": c.day(entry, "acquired", path)})
    plan["outside"] = {"cash": c.number(outside, "cash", "outside", 0.0, low=0, high=1e9),
                       "cash_buffer": c.number(outside, "cash_buffer", "outside", 0.0, low=0, high=1e9),
                       "weights": c.weights(outside, "outside", names), "holdings": holdings}
    plan["super"] = {"balance": c.number(super_, "balance", "super", 0.0, low=0, high=1e9),
                     "weights": c.weights(super_, "super", names),
                     "total_super_balance_prior_30_june": c.number(super_, "total_super_balance_prior_30_june", "super",
                                                                   super_.get("balance", 0.0), low=0, high=1e9)}
    if plan["super"]["balance"] > 0 and not plan["super"]["weights"]:
        c.problems.append("super.weights: required when the super balance is positive")
    plan["spending"] = {"annual": c.number(spending, "annual", "spending", 0.0, low=0, high=1e8),
                        "annual_growth": c.number(spending, "annual_growth", "spending", 0.0, low=-0.2, high=0.2)}
    plan["pension"] = {"start_age": c.number(pension, "start_age", "pension", 0, low=0, high=80),
                       "transfer_all": c.flag(pension, "transfer_all", "pension", True),
                       "amount": c.number(pension, "amount", "pension", 0.0, low=0, high=1e9)}
    plan["assumptions"] = {"cpi_annual": c.number(assumptions, "cpi_annual", "assumptions", 0.025, low=-0.1, high=0.2),
                           "wage_growth_annual": c.number(assumptions, "wage_growth_annual", "assumptions", 0.035, low=-0.1, high=0.2)}
    if not plan["outside"]["weights"]:
        c.problems.append("outside.weights: required; surplus cash and income are invested at these weights")
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
             f"schema_version = {SCHEMA_VERSION}", ""]
    for section in ("plan", "person", "employment", "outside", "super", "spending", "pension", "assumptions"):
        lines.append(f"[{section}]")
        for key, value in plan[section].items():
            if value is None or key == "holdings":
                continue
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
        if section == "outside":
            for holding in plan["outside"]["holdings"]:
                lines.append("[[outside.holdings]]")
                lines += [f"{k} = {_toml_value(v)}" for k, v in holding.items()]
                lines.append("")
        if section == "employment":
            for asset in plan["assets"]:
                lines.append("[[assets]]")
                lines += [f"{k} = {_toml_value(v)}" for k, v in asset.items()]
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


def build_inputs(plan: dict):
    """Market path, ledger scenario, rule sets and notes for a normalized plan."""
    plan = normalize_plan(plan)
    start, end, shortened = horizon(plan)
    if end <= start:
        raise PlanError(["person.date_of_birth: the person is already at or near Age Pension age; SAPTO and Age Pension are not modelled yet"])
    notes = ["Market returns are deterministic assumed AUD growth per asset (AUD market data not yet added)."]
    if shortened:
        notes.append(f"Horizon shortened to {end}: runs stop before the income year in which the person reaches Age Pension age.")
    names = [a["name"] for a in plan["assets"]]
    dates = tuple(pd.bdate_range(start, end).date)
    if dates[0] != start:
        dates = (start, *dates)
    daily = np.expm1(np.log1p(np.array([a["annual_return"] for a in plan["assets"]])) / 252)
    path = MarketPath(dates, tuple(names), np.tile(daily, (len(dates) - 1, 1)), "AUD")
    person = Person(plan["person"]["date_of_birth"],
                    retirement_date=birthday(plan["person"]["date_of_birth"], plan["person"]["retirement_age"]),
                    private_hospital_cover=plan["person"]["private_hospital_cover"])
    employment = None
    if plan["employment"]["annual_salary"] > 0:
        first = plan["employment"]["first_payday"] or next(d for d in pd.date_range(start, periods=7).date if d.weekday() == 3).isoformat()
        employment = Employment(plan["employment"]["annual_salary"], first, plan["employment"]["salary_sacrifice_per_year"] / 26)
    pension = None
    if plan["pension"]["start_age"] > 0:
        pension = Pension(max(start, birthday(plan["person"]["date_of_birth"], int(plan["pension"]["start_age"]))),
                          None if plan["pension"]["transfer_all"] else plan["pension"]["amount"])
    scenario = LedgerScenario(
        person, outside_cash=plan["outside"]["cash"], cash_buffer=plan["outside"]["cash_buffer"],
        outside_parcels=tuple(Parcel(h["asset"], h["value"], h["cost_base"], h["acquired"]) for h in plan["outside"]["holdings"] if h["value"] > 0),
        outside_weights=plan["outside"]["weights"],
        super_units={a: plan["super"]["balance"] * w for a, w in plan["super"]["weights"].items()},
        super_weights=plan["super"]["weights"],
        income={a["name"]: AssetIncome(a["income_yield"], a["franked_fraction"]) for a in plan["assets"]},
        employment=employment, annual_spending=plan["spending"]["annual"], spending_growth=plan["spending"]["annual_growth"],
        pension=pension, tsb_prior_30_june=plan["super"]["total_super_balance_prior_30_june"])
    years = project_rulesets(load_ruleset("2026-27"), financial_year_of(end),
                             ProjectionAssumptions(plan["assumptions"]["cpi_annual"], plan["assumptions"]["wage_growth_annual"]))
    return path, scenario, years, notes


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "plan"
