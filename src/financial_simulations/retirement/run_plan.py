"""Run portfolio-first and retirement paths into one consolidated plan folder."""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.data.plan_markets import load_plan_markets
from financial_simulations.reporting.ledger import write_ledger_report
from financial_simulations.reporting.plan import write_plan_plots
from financial_simulations.retirement.analysis import QUANTILES, analyse_portfolios, target_observations
from financial_simulations.retirement.ledger import LedgerResult, run_ledger
from financial_simulations.retirement.paths import SERIES, run_ledgers
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
    account_bands: pd.DataFrame
    retirement_annual: pd.DataFrame
    wealth_paths: pd.DataFrame | None = None


def ledger_for_path(plan: dict, market, portfolios, path: int) -> LedgerResult:
    """Re-run the full daily tax ledger for one shared market draw."""
    inputs, scenario, years, _ = build_inputs(plan, market=market, returns=portfolios.returns_for(market, path))
    return run_ledger(inputs, scenario, years)


def _bands(dates, frame_rows, name) -> pd.DataFrame:
    q = np.quantile(np.stack(frame_rows), QUANTILES, axis=0)
    return pd.DataFrame({"Date": dates, "Series": name, "P05": q[0], "P25": q[1], "P50": q[2], "P75": q[3], "P95": q[4]})


def run_plan(plan: dict, output_root: str | Path | None = DEFAULT_ROOT, *, market=None, progress=None) -> PlanRun:
    """Resample entered portfolios, then run a daily tax ledger on shared draws.

    ``progress(fraction, message)`` reports each stage: portfolio sampling and
    compounding (0-35%), the daily tax ledgers (35-95%) and saving (95-100%).
    """
    tell = progress or (lambda fraction, message: None)
    plan = normalize_plan(plan)
    market = market or load_plan_markets(plan["assets"])
    target = target_observations(plan)
    portfolios = analyse_portfolios(plan, market, target, lambda f, m: tell(0.35 * f, m))
    cpi = plan["assumptions"]["cpi_annual"]
    _, _, years, notes = build_inputs(plan, market=market, returns=portfolios.returns_for(market, 0))
    tell(0.35, "Starting the daily tax ledgers (the first run also starts worker processes, which takes a few seconds)")
    ledgers = lambda done, total: tell(0.35 + 0.6 * done / total, f"Daily tax ledgers: {done} of {total} paths")
    summaries = sorted(run_ledgers(plan, market, portfolios, cpi, ledgers), key=lambda item: item[0]["Path"])
    tell(0.95, "Summarising paths and saving reports")
    outcome_frame = pd.DataFrame([s[0] for s in summaries])
    calculated = [s for s in summaries if s[1] is not None]
    if not calculated:
        reasons = sorted({row["Reason"] for row in outcome_frame.to_dict("records")})
        raise UnsupportedRule("No retirement path can be calculated: " + "; ".join(reasons))
    complete = outcome_frame.loc[outcome_frame["Status"] != "unsupported"]
    median = float(complete["Ending wealth"].median())
    representative = int(complete.iloc[(complete["Ending wealth"] - median).abs().argmin()]["Path"])
    result = ledger_for_path(plan, market, portfolios, representative)
    months = result.daily["total"].resample("ME").last().index
    account_bands = pd.concat([_bands(months, [s[1][name] for s in calculated], name) for name, _ in SERIES], ignore_index=True)
    retirement_bands = account_bands.loc[account_bands["Series"] == "Total wealth"].drop(columns="Series").reset_index(drop=True)
    retirement_annual = pd.DataFrame([row for s in calculated for row in s[2]])
    # Every calculated path's month-end total wealth, for the all-paths chart.
    wealth_paths = pd.DataFrame({"Date": np.tile(months, len(calculated)),
                                 "Path": np.repeat([s[0]["Path"] for s in calculated], len(months)),
                                 "Status": np.repeat([s[0]["Status"] for s in calculated], len(months)),
                                 "Total wealth": np.concatenate([s[1]["Total wealth"] for s in calculated])})
    unsupported = len(outcome_frame) - len(complete)
    if unsupported:
        reasons = "; ".join(sorted(set(outcome_frame.loc[outcome_frame["Status"] == "unsupported", "Reason"])))
        notes.append(f"{unsupported} of {len(outcome_frame)} retirement draws reached a rule this model does not support "
                     f"({reasons}). Bands and success rates use the other {len(complete)} paths, so they are conditional.")
    if len(complete) < 100:
        notes.append(f"Retirement results use {len(complete)} calculated paths; tail percentiles and shortfall rates move "
                     "noticeably between seeds below about 100 paths.")
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
                    "representative_path": representative}
        write_ledger_report(result, folder, plan["plan"]["name"], manifest)
        for name, frame in (("asset_summary", market.asset_summary), ("portfolio_summary", portfolios.summary),
                            ("portfolio_history", portfolios.historical), ("portfolio_bands", portfolios.paths),
                            ("portfolio_outcomes", portfolios.outcomes), ("portfolio_annual", portfolios.annual_returns),
                            ("retirement_paths", outcome_frame), ("retirement_bands", account_bands),
                            ("retirement_annual", retirement_annual)):
            frame.to_csv(folder / f"{name}.csv", index=False, lineterminator="\n")
        write_plan_plots(folder, plan, market, portfolios, outcome_frame, retirement_bands, result)
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
    return PlanRun(plan, result, notes, folder, rules, market, portfolios, outcome_frame, retirement_bands, representative,
                   account_bands, retirement_annual, wealth_paths)
