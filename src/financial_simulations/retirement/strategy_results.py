"""Side-by-side summaries of compared spending strategies, shared by the app and the PNG review plots (ADR 0045).

Every strategy ran on the same market paths (ADR 0044), so a difference between two strategies' figures comes from
the strategies alone. Amounts are in today's dollars. Medians and percentiles are taken across paths separately for
each measure and each date or year, so they need not come from the same path.
"""

import numpy as np
import pandas as pd

from financial_simulations.retirement.flows import HOUSEHOLD


# Short names and fixed colours by strategy, never by rank. The four colours are the first four slots of the
# reference categorical palette and passed its validator (lightness, chroma, colour-vision separation) on a light
# surface; two are below 3:1 contrast, so every chart carries a legend and the statistics table.
STRATEGY_NAMES = {"fixed": "Fixed", "guyton_klinger": "Guyton–Klinger", "vanguard": "Vanguard", "percent": "% of wealth"}
STRATEGY_COLOURS = {"fixed": "#2a78d6", "guyton_klinger": "#eb6834", "vanguard": "#1baf7a", "percent": "#eda100"}

# Flows that leave wealth are shown as positive amounts paid; the others keep their sign.
OUTFLOWS = tuple(label for _, label, sign in HOUSEHOLD if sign < 0)
FLOW_CHOICES = tuple(label for _, label, _ in HOUSEHOLD) + ("Inflation",)
DEFAULT_FLOW = "Spending"


def _share(mask) -> float:
    return float(np.mean(mask)) if len(mask) else np.nan


def _quantile(values, q) -> float:
    values = pd.Series(values, dtype=float).dropna()
    return float(values.quantile(q)) if len(values) else np.nan


def retired_spending(run) -> pd.Series:
    """Each calculated path's total spending paid over its full retired financial years, today's dollars."""
    annual = run.retirement_annual
    if annual.empty:
        return pd.Series(dtype=float)
    retired = annual.loc[annual["Full retired year"]]
    totals = retired.groupby("Path")["Spending paid"].sum()
    return totals.reindex(annual["Path"].unique()).dropna()


# (measure, kind, how): kind is "money" or "share"; how computes the value from one strategy's PlanRun.
MEASURES = (
    ("Starting retirement spending (median)", "money",
     lambda run: _quantile(_calculated(run)["Starting retirement spending"], 0.5)),
    ("Spending over full retired years: median", "money", lambda run: _quantile(retired_spending(run), 0.5)),
    ("Spending over full retired years: 10th percentile", "money", lambda run: _quantile(retired_spending(run), 0.1)),
    ("Lowest retired year's spending: median", "money",
     lambda run: _quantile(_calculated(run)["Lowest retired-year spending"], 0.5)),
    ("Lowest retired year's spending: 10th percentile", "money",
     lambda run: _quantile(_calculated(run)["Lowest retired-year spending"], 0.1)),
    ("Paths with any spending shortfall", "share", lambda run: _share(_calculated(run)["Spending shortfall"] > 0)),
    ("Paths that ever spent below the start", "share", lambda run: _share(_calculated(run)["Years below start"] > 0)),
    ("Ending wealth after tax owed: median", "money",
     lambda run: _quantile(_calculated(run)["Ending wealth after tax owed"], 0.5)),
    ("Ending wealth after tax owed: 10th percentile", "money",
     lambda run: _quantile(_calculated(run)["Ending wealth after tax owed"], 0.1)),
)


def _calculated(run) -> pd.DataFrame:
    paths = run.retirement_paths
    return paths.loc[paths["Status"] != "unsupported"]


def comparison_table(strategies: dict) -> pd.DataFrame:
    """One row per measure, one column per strategy (by rule), plus the measure's kind."""
    rows = []
    for measure, kind, how in MEASURES:
        rows.append({"Measure": measure, "Kind": kind, **{rule: how(run) for rule, run in strategies.items()}})
    return pd.DataFrame(rows)


def wealth_lines(strategies: dict) -> pd.DataFrame:
    """Median and 10th-percentile total wealth at each month end, by strategy, today's dollars."""
    frames = []
    for rule, run in strategies.items():
        grouped = run.wealth_paths.groupby("Date")["Total wealth"]
        frame = pd.DataFrame({"Median": grouped.median(), "P10": grouped.quantile(0.1)}).reset_index()
        frames.append(frame.assign(Strategy=rule))
    return pd.concat(frames, ignore_index=True)


def yearly_medians(strategies: dict, flow: str = DEFAULT_FLOW, retired_only: bool = True) -> pd.DataFrame:
    """The median of one money in and out flow in each financial year, across paths, by strategy.

    Outflows (spending and taxes) are positive amounts paid. ``retired_only`` keeps full retired years, where the
    strategies differ; before retirement every strategy is the same.
    """
    column, sign = f"Flow: {flow}", -1.0 if flow in OUTFLOWS else 1.0
    frames = []
    for rule, run in strategies.items():
        annual = run.retirement_annual
        if column not in annual:
            continue
        if retired_only:
            annual = annual.loc[annual["Full retired year"]]
        medians = (sign * annual[column]).groupby(annual["FY ending"]).median()
        frames.append(pd.DataFrame({"FY ending": medians.index.astype(int), "Strategy": rule, "Value": medians.to_numpy()}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["FY ending", "Strategy", "Value"])


def available_flows(strategies: dict) -> list:
    """The flows any strategy recorded, in the money in and out order."""
    present = {c.removeprefix("Flow: ") for run in strategies.values() for c in run.retirement_annual.columns
               if c.startswith("Flow: ")}
    return [flow for flow in FLOW_CHOICES if flow in present]
