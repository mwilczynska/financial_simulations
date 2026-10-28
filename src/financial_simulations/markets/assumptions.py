"""Persistent scenario-grid inputs; assumed inflation is separate from observed CPI."""

from dataclasses import asdict, dataclass
from numbers import Real

import numpy as np

from financial_simulations.data.registry import resolve_asset
from financial_simulations.dates import as_date
from financial_simulations.markets.resampling import integer
from financial_simulations.scenario import _keys


def rate(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    return float(value)


@dataclass(frozen=True)
class Assumption:
    name: str
    mean_convention: str
    annual_returns: dict | None
    inflation_annual: float
    rationale: str

    def daily_mean(self, model):
        if self.annual_returns is None:
            return model.daily_mean(self.mean_convention)
        if set(self.annual_returns) != set(model.assets):
            raise ValueError(f"Assumption {self.name} must specify exactly the portfolio's assets.")
        return model.daily_mean(self.mean_convention, [self.annual_returns[a] for a in model.assets])


@dataclass(frozen=True)
class ParametricSettings:
    observations_per_year: int
    reference_inflation: float
    trace_assumption: str
    assumptions: tuple[Assumption, ...]

    def manifest(self):
        return asdict(self)


def load_assumptions(options, cases):
    _keys(options, {"observations_per_year", "reference_inflation", "trace_assumption"},
          {"observations_per_year", "reference_inflation", "trace_assumption"}, "parametric")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Supply at least one assumptions table.")
    assumptions = []
    for case in cases:
        required = {"name", "mean_convention", "inflation_annual", "rationale"}
        _keys(case, required | {"annual_returns"}, required, "assumptions")
        for key in ("name", "rationale"):
            if not isinstance(case[key], str) or not case[key].strip():
                raise ValueError(f"Assumption {key} must be a nonempty string.")
        convention = case["mean_convention"]
        if convention not in {"historical", "geometric_growth", "expected_compounded_return", "annualised_daily_arithmetic"}:
            raise ValueError("Unknown annual mean convention.")
        annual = case.get("annual_returns")
        if convention == "historical":
            if annual is not None:
                raise ValueError("Historical means do not take annual return overrides.")
        else:
            if not isinstance(annual, dict) or not annual:
                raise ValueError("Nonhistorical assumptions require annual_returns per asset.")
            canonical = {}
            for asset, value in annual.items():
                identifier = resolve_asset(asset).identifier
                if identifier in canonical:
                    raise ValueError("Duplicate asset aliases in annual return assumptions.")
                canonical[identifier] = rate(value, "Annual return")
            annual = canonical
        inflation = rate(case["inflation_annual"], "inflation_annual")
        if inflation <= -1:
            raise ValueError("Assumed inflation must exceed -100%.")
        assumptions.append(Assumption(case["name"], convention, annual, inflation, case["rationale"]))
    names = [case.name for case in assumptions]
    if len(set(names)) != len(names) or options["trace_assumption"] not in names:
        raise ValueError("Assumption names must be distinct and include trace_assumption.")
    reference = rate(options["reference_inflation"], "reference_inflation")
    if reference <= -1:
        raise ValueError("Reference inflation must exceed -100%.")
    return ParametricSettings(integer(options["observations_per_year"], "observations_per_year"),
                              reference, options["trace_assumption"], tuple(assumptions))


def assumed_price_index(dates, inflation_annual):
    """Opening-price units on elapsed calendar days / 365.25, never observed CPI."""
    dates = tuple(as_date(d) for d in dates)
    inflation = rate(inflation_annual, "inflation_annual")
    if not dates or inflation <= -1 or any(b <= a for a, b in zip(dates, dates[1:])):
        raise ValueError("Price-index dates must be nonempty/sorted/unique and inflation above -100%.")
    elapsed = np.array([(d - dates[0]).days for d in dates]) / 365.25
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        values = np.exp(np.log1p(inflation) * elapsed)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Assumed price index exceeds numeric range.")
    return values
