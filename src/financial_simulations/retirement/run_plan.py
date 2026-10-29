"""Run portfolio-first and retirement paths into one consolidated plan folder."""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.data.plan_markets import load_plan_markets
from financial_simulations.reporting.ledger import write_ledger_report
from financial_simulations.reporting.plan import write_plan_plots
from financial_simulations.retirement.analysis import analyse_portfolios, target_observations
from financial_simulations.retirement.ledger import LedgerResult, run_ledger
from financial_simulations.retirement.plan import build_inputs, normalize_plan, plan_to_toml, slug
from financial_simulations.runner import code_manifest
from financial_simulations.rules.au.parameters import UnsupportedRule


DEFAULT_ROOT = Path("output") / "plans"


@dataclass(frozen=True)
class PlanRun:
    plan: dict
    result: LedgerResult
    notes: list
    folder: Path | None
    rules_manifest: dict
    market: object
    portfolios: object
    retirement_paths: pd.DataFrame
    retirement_bands: pd.DataFrame
    representative_path: int


def run_plan(plan: dict, output_root: str | Path | None = DEFAULT_ROOT, *, market=None) -> PlanRun:
    """Resample entered portfolios, then run a daily tax ledger on shared draws."""
    plan = normalize_plan(plan)
    market = market or load_plan_markets(plan["assets"])
    target = target_observations(plan)
    portfolios = analyse_portfolios(plan, market, target)
    ledgers, outcomes, monthly = [], [], []
    notes = []
    years = None
    for i in range(plan["market"]["retirement_paths"]):
        path, scenario, years, path_notes = build_inputs(plan, market=market,
                                                        returns=portfolios.sampled_returns[i])
        if not notes:
            notes = path_notes
        try:
            result = run_ledger(path, scenario, years)
        except UnsupportedRule as exc:
            outcomes.append({"Path": i, "Status": "unsupported", "Reason": str(exc)})
            continue
        ledgers.append((i, result))
        daily = result.daily
        annual = result.annual
        shortfall = float(daily["shortfall"].sum())
        first_shortfall = daily.index[daily["shortfall"] > 0]
        outcomes.append({"Path": i, "Status": "complete", "Reason": "", "Ending wealth": float(daily["total"].iloc[-1]),
                         "Ending outside wealth": float(daily["cash"].iloc[-1] + daily["outside_investments"].iloc[-1]),
                         "Ending super and pension": float(daily["accumulation"].iloc[-1] + daily["pension"].iloc[-1]),
                         "Spending paid": float(daily["spending_paid"].sum()), "Spending shortfall": shortfall,
                         "First shortfall": str(first_shortfall[0].date()) if len(first_shortfall) else "",
                         "Personal tax assessed": float(sum(a["assessment"].net_tax + a["assessment"].division_293_tax for a in annual)),
                         "Fund tax": float(daily["fund_tax"].sum())})
        monthly.append(daily["total"].resample("ME").last().to_numpy())
    if not ledgers:
        reasons = sorted({row["Reason"] for row in outcomes})
        raise UnsupportedRule("No retirement path can be calculated: " + "; ".join(reasons))
    outcome_frame = pd.DataFrame(outcomes)
    complete = outcome_frame.loc[outcome_frame["Status"] == "complete"]
    median = float(complete["Ending wealth"].median())
    representative = min(ledgers, key=lambda item: abs(item[1].daily["total"].iloc[-1] - median))
    result = representative[1]
    months = result.daily["total"].resample("ME").last().index
    matrix = np.stack(monthly)
    q = np.quantile(matrix, [0.05, 0.25, 0.5, 0.75, 0.95], axis=0)
    retirement_bands = pd.DataFrame({"Date": months, "P05": q[0], "P25": q[1], "P50": q[2],
                                     "P75": q[3], "P95": q[4]})
    if len(complete) != len(outcome_frame):
        notes.append(f"{len(outcome_frame) - len(complete)} of {len(outcome_frame)} retirement draws reached an unsupported rule. Distribution bands use complete paths only; they are not unconditional risk estimates.")
    if len(complete) < 30:
        notes.append(f"Retirement bands use only {len(complete)} complete paths; tail percentiles and shortfall counts are especially noisy at this size.")
    rules = {fy: r.manifest() for fy, r in years.items()}
    folder = None
    if output_root is not None:
        folder = Path(output_root) / slug(plan["plan"]["name"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plan.toml").write_text(plan_to_toml(plan), encoding="utf-8", newline="\n")
        manifest = {"plan": plan["plan"], "notes": notes, "rules": rules, "code": code_manifest(),
                    "market": market.manifest, "sampler": {"method": "stationary", **plan["market"],
                                                             "target_calendar": "weekdays; not a holiday forecast",
                                                             "retirement_currency_convention": "USD returns applied as an explicit AUD proxy"},
                    "representative_path": representative[0]}
        write_ledger_report(result, folder, plan["plan"]["name"], manifest)
        for name, frame in (("asset_summary", market.asset_summary), ("portfolio_history", portfolios.historical),
                            ("portfolio_bands", portfolios.paths), ("portfolio_outcomes", portfolios.outcomes),
                            ("portfolio_annual", portfolios.annual_returns), ("retirement_paths", outcome_frame),
                            ("retirement_bands", retirement_bands)):
            frame.to_csv(folder / f"{name}.csv", index=False, lineterminator="\n")
        write_plan_plots(folder, plan, market, portfolios, outcome_frame, retirement_bands, result)
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    return PlanRun(plan, result, notes, folder, rules, market, portfolios, outcome_frame,
                   retirement_bands, representative[0])
