"""Run portfolio-first and retirement paths into one consolidated plan folder."""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.data.plan_markets import plan_markets
from financial_simulations.reporting.ledger import write_ledger_report
from financial_simulations.reporting.plan import (write_comparison_plots, write_outcome_plot, write_path_markets_plot,
                                                  write_portfolio_plots, write_retirement_plots)
from financial_simulations.retirement.path_markets import path_markets
from financial_simulations.retirement.analysis import QUANTILES, analyse_portfolios, target_observations
from financial_simulations.retirement.ledger import LedgerResult, run_ledger
from financial_simulations.retirement.paths import SERIES, run_ledgers, worker_count
from financial_simulations.retirement.plan import build_inputs, normalize_plan, plan_to_toml, slug, strategy_plan
from financial_simulations.runner import code_manifest
from financial_simulations.rules.au.parameters import UnsupportedRule


DEFAULT_ROOT = Path("output") / "plans"


@dataclass(frozen=True)
class PlanRun:
    """One spending strategy's results; the portfolio analysis and market are shared by every compared strategy."""

    plan: dict  # the normalized plan for the strategy that was run: spending.rule names it
    result: LedgerResult
    notes: list
    folder: Path | None  # the run's output folder (shared by every strategy)
    rules_manifest: dict
    market: object
    portfolios: object
    retirement_paths: pd.DataFrame
    retirement_bands: pd.DataFrame
    representative_path: int
    account_bands: pd.DataFrame
    retirement_annual: pd.DataFrame
    wealth_paths: pd.DataFrame | None = None
    path_series: pd.DataFrame | None = None  # every calculated path's month-end balances by account (today's dollars)
    # Every compared strategy's PlanRun by rule, in the plan's order, this one included. All share the same draws.
    strategies: dict | None = None
    # Set when the results were opened from a saved run (ADR 0050): every stored path ledger, if they were saved,
    # and the saved folder.
    saved_ledgers: object | None = None
    saved_from: Path | None = None

    @property
    def rule(self) -> str:
        return self.plan["spending"]["rule"]


# One strategy's output files. With several strategies they go in strategies/<rule>/ (ADR 0044), and the comparison
# files sit in the plan folder (ADR 0045).
STRATEGY_FILES = ("daily.csv", "events.csv", "annual.json", "ledger.png", "retirement_paths.csv", "retirement_bands.csv",
                  "retirement_annual.csv", "retirement_range.png", "retirement_flows.png", "retirement_outcomes.png",
                  "retirement_markets.png")
COMPARISON_FILES = ("comparison_summary.csv", "comparison_wealth.png", "comparison_spending.png")


def ledger_for_path(plan: dict, market, portfolios, path: int) -> LedgerResult:
    """Re-run the full daily tax ledger for one shared market draw (``plan`` names one strategy)."""
    inputs, scenario, years, _ = build_inputs(plan, market=market, returns=portfolios.returns_for(market, path))
    return run_ledger(inputs, scenario, years)


def _bands(dates, frame_rows, name) -> pd.DataFrame:
    q = np.quantile(np.stack(frame_rows), QUANTILES, axis=0)
    return pd.DataFrame({"Date": dates, "Series": name, "P05": q[0], "P25": q[1], "P50": q[2], "P75": q[3], "P95": q[4]})


def _strategy_run(run_for, summaries, notes, folder, rules, market, portfolios, strategies) -> PlanRun:
    """One strategy's bands, tables and representative ledger from its path summaries."""
    label = run_for["spending"]["rule"].replace("_", " ")
    outcome_frame = pd.DataFrame([s[0] for s in summaries])
    calculated = [s for s in summaries if s[1] is not None]
    if not calculated:
        reasons = sorted({row["Reason"] for row in outcome_frame.to_dict("records")})
        raise UnsupportedRule(f"No retirement path can be calculated for {label} spending: " + "; ".join(reasons))
    complete = outcome_frame.loc[outcome_frame["Status"] != "unsupported"]
    median = float(complete["Ending wealth"].median())
    representative = int(complete.iloc[(complete["Ending wealth"] - median).abs().argmin()]["Path"])
    result = ledger_for_path(run_for, market, portfolios, representative)
    months = result.daily["total"].resample("ME").last().index
    account_bands = pd.concat([_bands(months, [s[1][name] for s in calculated], name) for name, _ in SERIES], ignore_index=True)
    retirement_bands = account_bands.loc[account_bands["Series"] == "Total wealth"].drop(columns="Series").reset_index(drop=True)
    retirement_annual = pd.DataFrame([row for s in calculated for row in s[2]])
    # Every calculated path's month-end total wealth, for the all-paths chart.
    wealth_paths = pd.DataFrame({"Date": np.tile(months, len(calculated)),
                                 "Path": np.repeat([s[0]["Path"] for s in calculated], len(months)),
                                 "Status": np.repeat([s[0]["Status"] for s in calculated], len(months)),
                                 "Total wealth": np.concatenate([s[1]["Total wealth"] for s in calculated])})
    path_series = pd.DataFrame({"Date": np.tile(months, len(calculated)),
                                "Path": np.repeat([s[0]["Path"] for s in calculated], len(months)),
                                **{name: np.concatenate([s[1][name] for s in calculated]) for name, _ in SERIES}})
    notes = list(notes)
    unsupported = len(outcome_frame) - len(complete)
    if unsupported:
        reasons = "; ".join(sorted(set(outcome_frame.loc[outcome_frame["Status"] == "unsupported", "Reason"])))
        notes.append(f"{unsupported} of {len(outcome_frame)} retirement draws reached a rule this model does not support "
                     f"({reasons}). Bands and success rates use the other {len(complete)} paths, so they are conditional.")
    if len(complete) < 100:
        notes.append(f"Retirement results use {len(complete)} calculated paths; tail percentiles and shortfall rates move "
                     "noticeably between seeds below about 100 paths.")
    return PlanRun(run_for, result, notes, folder, rules, market, portfolios, outcome_frame, retirement_bands,
                   representative, account_bands, retirement_annual, wealth_paths, path_series, strategies)


def _clear_strategy_files(folder: Path) -> None:
    """Remove one strategy's files left by an earlier run, and the folder itself if that empties it."""
    for name in STRATEGY_FILES:
        (folder / name).unlink(missing_ok=True)
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()


def _write_strategy(run: PlanRun, folder: Path, manifest: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    write_ledger_report(run.result, folder, run.plan["plan"]["name"],
                        {**manifest, "spending_strategy": run.rule, "representative_path": run.representative_path,
                         "notes": run.notes})
    for name, frame in (("retirement_paths", run.retirement_paths), ("retirement_bands", run.account_bands),
                        ("retirement_annual", run.retirement_annual)):
        frame.to_csv(folder / f"{name}.csv", index=False, lineterminator="\n")
    write_retirement_plots(folder, run.plan, run.retirement_paths, run.retirement_bands, run.result)
    write_outcome_plot(folder, run.plan, run.retirement_paths, run.retirement_annual)
    write_path_markets_plot(folder, run.plan, *path_markets(run.plan, run.market, run.portfolios, run.representative_path),
                            run.representative_path)


def run_plan(plan: dict, output_root: str | Path | None = DEFAULT_ROOT, *, market=None, progress=None,
             workers: int | None = None) -> PlanRun:
    """Resample entered portfolios, then run every compared spending strategy's daily tax ledger on shared draws.

    Returns the first compared strategy's ``PlanRun``; ``strategies`` holds every strategy's, by rule. Each path's
    market draw is the same for every strategy, so differences between strategies come from the strategies alone.
    ``progress(fraction, message)`` reports each stage: portfolio sampling and compounding (0-35%), the daily tax
    ledgers (35-95%) and saving (95-100%). ``workers`` sets the number of ledger processes; ``None`` chooses
    automatically (``worker_count``).
    """
    tell = progress or (lambda fraction, message: None)
    plan = normalize_plan(plan)
    market = market or plan_markets(plan)
    if market.path.currency != plan["market"]["currency"]:
        raise ValueError(f"The supplied histories are in {market.path.currency}, but the plan measures returns in "
                         f"{plan['market']['currency']}.")
    target = target_observations(plan, market)
    portfolios = analyse_portfolios(plan, market, target, lambda f, m: tell(0.35 * f, m))
    cpi = plan["assumptions"]["cpi_annual"]
    plans = [strategy_plan(plan, rule) for rule in plan["spending"]["compare"]]
    _, _, years, notes = build_inputs(plans[0], market=market, returns=portfolios.returns_for(market, 0))
    paths = plan["market"]["retirement_paths"]
    workers, limited = worker_count(paths * len(plans), workers)
    if limited:
        notes.append(limited)
    tell(0.35, f"Starting the daily tax ledgers on {workers} worker process{'es' if workers != 1 else ''} (the first "
               "run also starts them, which takes a few seconds)")
    each = f" ({paths} paths × {len(plans)} strategies)" if len(plans) > 1 else " paths"
    ledgers = lambda done, total: tell(0.35 + 0.6 * done / total, f"Daily tax ledgers: {done} of {total}{each}")
    by_rule = run_ledgers(plans, market, portfolios, cpi, ledgers, workers)
    tell(0.95, "Summarising paths and saving reports")
    rules = {fy: r.manifest() for fy, r in years.items()}
    folder = Path(output_root) / slug(plan["plan"]["name"]) if output_root is not None else None
    strategies = {}
    for run_for in plans:
        rule = run_for["spending"]["rule"]
        strategies[rule] = _strategy_run(run_for, by_rule[rule], notes, folder, rules, market, portfolios, strategies)
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "plan.toml").write_text(plan_to_toml(plan), encoding="utf-8", newline="\n")
        manifest = {"plan": plan["plan"], "notes": notes, "rules": rules, "code": code_manifest(),
                    "market": market.manifest, "sampler": {"method": "stationary", **plan["market"],
                                                             "target_calendar": ("weekdays evenly thinned to the history's observations "
                                                                                 "per year; not a holiday forecast"),
                                                             "retirement_currency_convention": (
                                                                 "AUD returns; USD histories converted at AUDUSD spot"
                                                                 if market.path.currency == "AUD" else
                                                                 "USD returns applied as an explicit AUD proxy")}}
        for name, frame in (("asset_summary", market.asset_summary), ("portfolio_summary", portfolios.summary),
                            ("portfolio_history", portfolios.historical), ("portfolio_bands", portfolios.paths),
                            ("portfolio_outcomes", portfolios.outcomes)):
            frame.to_csv(folder / f"{name}.csv", index=False, lineterminator="\n")
        (folder / "portfolio_annual.csv").unlink(missing_ok=True)  # written by earlier versions; no longer calculated
        write_portfolio_plots(folder, plan, portfolios)
        # One strategy keeps the original layout; several each get strategies/<rule>/. Files from a run with the
        # other layout are removed so the folder never mixes the two.
        nested = folder / "strategies"
        if len(strategies) == 1:
            (run,) = strategies.values()
            for old in (nested.iterdir() if nested.is_dir() else ()):
                _clear_strategy_files(old)
            _clear_strategy_files(nested)
            for name in COMPARISON_FILES:
                (folder / name).unlink(missing_ok=True)
            _write_strategy(run, folder, manifest)
            manifest["spending_strategies"] = {run.rule: {"folder": ".", "representative_path": run.representative_path}}
        else:
            for name in STRATEGY_FILES:
                (folder / name).unlink(missing_ok=True)
            for old in (nested.iterdir() if nested.is_dir() else ()):
                if old.name not in strategies:
                    _clear_strategy_files(old)
            write_comparison_plots(folder, plan, strategies)
            manifest["spending_strategies"] = {}
            for rule, run in strategies.items():
                _write_strategy(run, nested / rule, manifest)
                manifest["spending_strategies"][rule] = {"folder": f"strategies/{rule}",
                                                         "representative_path": run.representative_path}
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8",
                                              newline="\n")
    return strategies[plans[0]["spending"]["rule"]]
