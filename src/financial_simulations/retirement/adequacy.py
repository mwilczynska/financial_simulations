"""Retirement adequacy summaries from existing daily-ledger reports (ADR 0047)."""

import numpy as np
import pandas as pd


OUTCOME_COLOURS = {
    "Funded without Age Pension": "#126a63",
    "Funded with Age Pension": "#b58232",
    "Spending or tax shortfall": "#b34b46",
}


def path_adequacy(paths: pd.DataFrame, annual: pd.DataFrame, start_date) -> pd.DataFrame:
    """One row per supported path, preserving zero-spending years and missing horizons.

    Pension receipt is observed support, not a counterfactual test of whether a
    path would fail without it. Final-year receipt may cover a partial year.
    """
    result = paths.loc[paths["Status"] != "unsupported"].copy().set_index("Path")
    received = result["Age Pension received"].gt(0)
    result["Outcome"] = np.where(
        result["Status"].eq("depleted"), "Spending or tax shortfall",
        np.where(received, "Funded with Age Pension", "Funded without Age Pension"),
    )
    # The legacy flag checks retirement and the final day, but not a mid-year
    # simulation start. Explicitly exclude that first partial financial year.
    begins = pd.to_datetime((annual["FY ending"] - 1).astype(str) + "-07-01")
    retired = annual.loc[annual["Full retired year"] & (begins >= pd.Timestamp(start_date))
                         & annual["Path"].isin(result.index)]
    grouped = retired.groupby("Path")["Spending paid"]
    result["Full retired years"] = grouped.count().reindex(result.index, fill_value=0)
    result["Average annual retirement spending"] = grouped.mean().reindex(result.index)
    final = annual.sort_values("FY ending").groupby("Path").tail(1).set_index("Path")
    result["Age Pension in final year"] = final["Age Pension"].reindex(result.index)
    return result.reset_index()


def spending_by_group(adequacy: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight mean of path means, plus their median and lower decile.

    Wealth-ranked groups use the same nearest-rank convention as the explorer.
    Risk groups are disjoint; wealth-ranked groups overlap them deliberately.
    """
    ranked = adequacy.sort_values("Ending wealth")
    n = len(ranked)
    groups = [("All calculated paths", adequacy)]
    groups.extend((label, adequacy.loc[adequacy["Outcome"] == label]) for label in OUTCOME_COLOURS)
    for label, low, high in (("Worst 10% by ending wealth", 0, .1),
                             ("Middle 10% by ending wealth", .45, .55),
                             ("Best 10% by ending wealth", .9, 1)):
        first = min(int(np.floor(round(low * n, 9))), max(0, n - 1))
        last = max(first + 1, int(np.ceil(round(high * n, 9))))
        groups.append((label, ranked.iloc[first:last]))
    rows = []
    for label, group in groups:
        values = group["Average annual retirement spending"].dropna()
        rows.append({"Path group": label, "Paths": len(group), "Paths with full retired years": len(values),
                     "Average per year": values.mean(), "Median path average": values.median(),
                     "10th percentile path average": values.quantile(.1) if len(values) else np.nan})
    return pd.DataFrame(rows)
