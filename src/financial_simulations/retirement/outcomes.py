"""How each retirement path fared: outcome tiers, Age Pension reliance and average retirement spending (ADR 0048).

Risk of ruin alone misses the paths that never ran out but fell far enough to live on the Age Pension. Each
calculated path is therefore put in one of four tiers, the worst it reached:

* **Ran out**: the ledger's ``depleted`` status (unpaid spending or tax, or tax owed at the horizon that the money
  left cannot settle).
* **Full Age Pension**: funded, with at least one financial year paid ``FULL_RATE_SHARE`` or more of the maximum
  single rate. The maximum rate is paid only when both means tests reduce it by nothing, so assessable assets are
  below the full-pension limit: the path is close to ruin.
* **Part Age Pension**: funded and paid some Age Pension, never a full-rate year.
* **Self-funded**: funded and never paid any Age Pension.

The same four names label each path's state in each financial year (``yearly_states``), where *Ran out* means a
shortfall in that year or an earlier one.

Amounts are in today's dollars, as in ``paths._summarise``. A path's average retired-year spending is the mean of
*spending paid* over its full retired financial years, so shortfalls lower it.
"""

from datetime import date

import numpy as np
import pandas as pd

from financial_simulations.retirement.real import year_deflator
from financial_simulations.rules.au.age_pension import FORTNIGHTS, maximum_rate
from financial_simulations.rules.au.parameters import load_ruleset
from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets


TIERS = ("Self-funded", "Part Age Pension", "Full Age Pension", "Ran out")
# A year counts as full rate at 95% of 26 maximum fortnights: the first fortnights after a threshold moves, and
# rounding, can leave a full pensioner slightly under 26 times the rate.
FULL_RATE_SHARE = 0.95

# Groups of paths ranked by ending wealth: (name, lowest rank share, highest rank share).
PATH_GROUPS = (("Worst 1%", 0.0, 0.01), ("Worst 5%", 0.0, 0.05), ("Worst 10%", 0.0, 0.10),
               ("Middle 10% (45th to 55th percentile)", 0.45, 0.55), ("Best 10%", 0.90, 1.0), ("Best 1%", 0.99, 1.0))


def full_age_pension_by_year(plan: dict) -> pd.Series:
    """The maximum single Age Pension for a whole financial year, in today's dollars, by the year it ends in.

    Twenty-six fortnights of that year's projected maximum rate (basic rate indexed to wages, supplements to CPI,
    as the ledger pays it), deflated on the same financial-year step as the ledger's flows.
    """
    start = date.fromisoformat(plan["plan"]["start_date"])
    first = start.year if start.month >= 7 else start.year - 1
    last = first + int(plan["plan"]["years"]) + 1
    cpi = plan["assumptions"]["cpi_annual"]
    rules = project_rulesets(load_ruleset("2026-27"), f"{last}-{(last + 1) % 100:02d}",
                             ProjectionAssumptions(cpi, plan["assumptions"]["wage_growth_annual"]))
    return pd.Series({int(label[:4]) + 1: FORTNIGHTS * maximum_rate(rule) / year_deflator(int(label[:4]) + 1, start, cpi)
                      for label, rule in rules.items()}, name="Full Age Pension", dtype=float)


def yearly_states(paths: pd.DataFrame, annual: pd.DataFrame, full_rate) -> pd.DataFrame:
    """Each calculated path's state in each financial year: ``Path``, ``FY ending`` and ``State`` (one of ``TIERS``).

    *Ran out* is absorbing: it holds from the first year with a shortfall. A path that is ``depleted`` without any
    spending shortfall (unpaid tax, or tax owed at the horizon it cannot settle) is marked in its last year.
    """
    frame = annual[["Path", "FY ending", "Shortfall", "Age Pension"]].sort_values(["Path", "FY ending"]).reset_index(drop=True)
    short = frame.groupby("Path")["Shortfall"].cumsum() > 0
    depleted = set(paths.loc[paths["Status"] == "depleted", "Path"])
    last = frame.groupby("Path")["FY ending"].transform("max") == frame["FY ending"]
    short |= last & frame["Path"].isin(depleted)
    limit = FULL_RATE_SHARE * frame["FY ending"].map(pd.Series(full_rate, dtype=float))
    full = frame["Age Pension"] >= limit.fillna(np.inf)
    state = np.select([short, full, frame["Age Pension"] > 0], [TIERS[3], TIERS[2], TIERS[1]], TIERS[0])
    return frame[["Path", "FY ending"]].assign(State=state)


def state_shares(states: pd.DataFrame) -> pd.DataFrame:
    """The share of paths in each state in each financial year, every state present in every year."""
    counts = states.groupby(["FY ending", "State"]).size().unstack(fill_value=0).reindex(columns=list(TIERS), fill_value=0)
    shares = counts.div(counts.sum(axis=1), axis=0)
    long = shares.reset_index().melt("FY ending", var_name="State", value_name="Share")
    return long.assign(Paths=counts.reset_index().melt("FY ending")["value"].to_numpy())


def path_outcomes(paths: pd.DataFrame, annual: pd.DataFrame, full_rate) -> pd.DataFrame:
    """The calculated paths with their outcome tier, Age Pension reliance and average retired-year spending."""
    calculated = paths.loc[paths["Status"] != "unsupported"].copy()
    states = yearly_states(calculated, annual, full_rate)
    by_path = lambda series: calculated["Path"].map(series)
    full_years = states.loc[states["State"] == TIERS[2]].groupby("Path").size()
    paid_years = annual.loc[annual["Age Pension"] > 0].groupby("Path").size()
    retired = annual.loc[annual["Full retired year"]].groupby("Path")
    spending, pension = retired["Spending paid"].sum(), retired["Age Pension"].sum()
    calculated["Average retired-year spending"] = by_path(retired["Spending paid"].mean())
    calculated["Retired years"] = by_path(retired.size()).fillna(0).astype(int)
    calculated["Age Pension years"] = by_path(paid_years).fillna(0).astype(int)
    calculated["Full Age Pension years"] = by_path(full_years).fillna(0).astype(int)
    calculated["Age Pension share of retired spending"] = by_path((pension / spending.where(spending > 0)))
    calculated["Outcome"] = np.select([calculated["Status"] == "depleted", calculated["Full Age Pension years"] > 0,
                                       calculated["Age Pension years"] > 0], [TIERS[3], TIERS[2], TIERS[1]], TIERS[0])
    return calculated


def tier_shares(outcomes: pd.DataFrame) -> pd.Series:
    """The share of calculated paths in each tier, in ``TIERS`` order."""
    return outcomes["Outcome"].value_counts(normalize=True).reindex(list(TIERS), fill_value=0.0)


def ending_percentiles(calculated: pd.DataFrame) -> dict:
    """Each calculated path's ending-wealth percentile: (rank + 0.5) / count x 100, so ranks spread over 0 to 100."""
    ordered = calculated.sort_values("Ending wealth")["Path"].tolist()
    return {path: (i + 0.5) / len(ordered) * 100 for i, path in enumerate(ordered)}


def group_members(calculated: pd.DataFrame, low: float, high: float) -> list:
    """Paths whose ending-wealth rank falls in [low, high) of the calculated paths; always at least one."""
    ordered = calculated.sort_values("Ending wealth")["Path"].tolist()
    n = len(ordered)
    first = min(int(np.floor(round(low * n, 9))), n - 1)
    last = max(first + 1, int(np.ceil(round(high * n, 9))))
    return [int(p) for p in ordered[first:last]]


def path_groups(outcomes: pd.DataFrame) -> dict:
    """Named groups of paths: everyone, each outcome tier that has paths, then the ending-wealth groups."""
    groups = {"All paths": outcomes["Path"].astype(int).tolist()}
    for tier in TIERS:
        members = outcomes.loc[outcomes["Outcome"] == tier, "Path"].astype(int).tolist()
        if members:
            groups[tier] = members
    for name, low, high in PATH_GROUPS:
        groups[name] = group_members(outcomes, low, high)
    return groups


def group_spending(outcomes: pd.DataFrame, groups: dict | None = None) -> pd.DataFrame:
    """Average retired-year spending by group of paths: the median path and the 10th to 90th percentile range.

    One row per group with ``Paths``, ``Share``, ``Median``, ``P10``, ``P90`` (of each path's average retired-year
    spending), ``Lowest year (median)`` and ``Ending wealth (median)``. Groups with no retired year are left out.
    """
    rows = []
    for name, members in (groups or path_groups(outcomes)).items():
        part = outcomes.loc[outcomes["Path"].isin(members)]
        spending = part["Average retired-year spending"].dropna()
        if spending.empty:
            continue
        lowest = part["Lowest retired-year spending"].dropna() if "Lowest retired-year spending" in part else spending.iloc[:0]
        rows.append({"Group": name, "Kind": "All" if name == "All paths" else "Outcome" if name in TIERS else "Ending wealth",
                     "Paths": len(part), "Share": len(part) / len(outcomes),
                     "Median": float(spending.median()), "P10": float(spending.quantile(0.1)),
                     "P90": float(spending.quantile(0.9)),
                     "Lowest year (median)": float(lowest.median()) if len(lowest) else np.nan,
                     "Ending wealth (median)": float(part["Ending wealth"].median())})
    return pd.DataFrame(rows, columns=["Group", "Kind", "Paths", "Share", "Median", "P10", "P90", "Lowest year (median)",
                                       "Ending wealth (median)"])
