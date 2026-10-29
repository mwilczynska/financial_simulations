"""Run portfolio-first and retirement paths into one consolidated plan folder."""

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.data.plan_markets import load_plan_markets
from financial_simulations.reporting.ledger import write_ledger_report
from financial_simulations.reporting.plan import write_plan_plots
from financial_simulations.retirement.analysis import QUANTILES, analyse_portfolios, target_observations
from financial_simulations.retirement.ledger import LedgerResult, run_ledger
from financial_simulations.retirement.plan import build_inputs, normalize_plan, plan_to_toml, slug
from financial_simulations.runner import code_manifest
from financial_simulations.rules.au.parameters import UnsupportedRule


DEFAULT_ROOT = Path("output") / "plans"
SERIES = (("Total wealth", ("cash", "outside_investments", "accumulation", "pension")),
          ("Outside super", ("cash", "outside_investments")),
          ("Super and pension", ("accumulation", "pension")),
          ("Pension account", ("pension",)))


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


def ledger_for_path(plan: dict, market, portfolios, path: int) -> LedgerResult:
    """Re-run the full daily tax ledger for one shared market draw."""
    inputs, scenario, years, _ = build_inputs(plan, market=market, returns=portfolios.returns_for(market, path))
    return run_ledger(inputs, scenario, years)


def _fy_start(day: date) -> date:
    return date(day.year if day.month >= 7 else day.year - 1, 7, 1)


def _summarise(path: int, result: LedgerResult, retire: date, cpi: float):
    """One path's outcome row, month-end account series and financial-year withdrawal rows."""
    daily, annual = result.daily, result.annual
    first, last = daily.index[0].date(), daily.index[-1].date()
    outside = daily["cash"] + daily["outside_investments"]
    totals = {name: daily[list(columns)].sum(axis=1) for name, columns in SERIES}
    monthly = {name: series.resample("ME").last().to_numpy() for name, series in totals.items()}
    shortfall_days = daily.index[daily["shortfall"] > 0]
    depleted = daily.index[(outside <= 1.0) & (daily.index.date > first)]
    years = (last - first).days / 365.25
    flows = daily[["spending_paid", "tax_paid", "shortfall", "pension_payments", "lump_sums"]].resample("YE-JUN").sum()
    rows = []
    for end, values in flows.iterrows():
        begin = _fy_start(end.date())
        before = daily.index[daily.index.date < begin]
        opening = float(daily["total"].iloc[0] if before.empty else daily["total"].loc[before[-1]])
        retired = begin >= retire and end.date() <= last
        withdrawal = float(values["spending_paid"] + max(values["tax_paid"], 0.0))
        rows.append({"Path": path, "Financial year": f"{begin.year}-{str(begin.year + 1)[2:]}", "FY ending": begin.year + 1,
                     "Full retired year": retired, "Wealth at 1 July": opening, "Spending paid": float(values["spending_paid"]),
                     "Tax paid": float(values["tax_paid"]), "Shortfall": float(values["shortfall"]),
                     "Pension payments": float(values["pension_payments"]), "Super lump sums": float(values["lump_sums"]),
                     "Withdrawal rate": withdrawal / opening if retired and opening > 1 else np.nan})
    retired_rates = [r["Withdrawal rate"] for r in rows if r["Full retired year"] and np.isfinite(r["Withdrawal rate"])]
    at_retirement = daily.loc[daily.index.date <= retire, "total"]
    unpaid = sum(item["amount"] for item in result.outstanding["unpaid_tax"])
    shortfall = float(daily["shortfall"].sum())
    pension_start = daily.index[daily["pension"] > 0]
    outcome = {"Path": path, "Status": "depleted" if shortfall > 0 or unpaid > 0 else "funded", "Reason": "",
               "Ending wealth": float(daily["total"].iloc[-1]),
               "Ending wealth, today's dollars": float(daily["total"].iloc[-1] / (1 + cpi) ** years),
               "Ending outside wealth": float(outside.iloc[-1]),
               "Ending super and pension": float(daily["accumulation"].iloc[-1] + daily["pension"].iloc[-1]),
               "Wealth at retirement": float(at_retirement.iloc[-1]) if len(at_retirement) else np.nan,
               "Spending paid": float(daily["spending_paid"].sum()), "Spending shortfall": shortfall,
               "Shortfall years": int(sum(r["Shortfall"] > 0 for r in rows)),
               "First shortfall": str(shortfall_days[0].date()) if len(shortfall_days) else "",
               "Outside money runs out": str(depleted[0].date()) if len(depleted) else "",
               "Unpaid tax": float(unpaid),
               "Personal tax assessed": float(sum(a["assessment"].net_tax + a["assessment"].division_293_tax for a in annual)),
               "Fund tax": float(daily["fund_tax"].sum()),
               "Pension payments": float(daily["pension_payments"].sum()),
               "Pension balance at start": float(daily["pension"].loc[pension_start[0]]) if len(pension_start) else 0.0,
               "First retired-year withdrawal rate": retired_rates[0] if retired_rates else np.nan,
               "Highest withdrawal rate": max(retired_rates) if retired_rates else np.nan,
               "Median withdrawal rate": float(np.median(retired_rates)) if retired_rates else np.nan}
    return outcome, monthly, rows


def _run_chunk(plan, market, indices, paths, retire, cpi):
    """Worker: run ledgers for several shared draws and keep only their summaries."""
    out = []
    for path, rows in zip(paths, indices):
        inputs, scenario, years, _ = build_inputs(plan, market=market, returns=market.path.returns[rows])
        try:
            result = run_ledger(inputs, scenario, years)
        except UnsupportedRule as exc:
            out.append(({"Path": path, "Status": "unsupported", "Reason": str(exc)}, None, []))
            continue
        out.append(_summarise(path, result, retire, cpi))
    return out


def _workers(count: int) -> int:
    configured = os.environ.get("FINANCIAL_SIMULATIONS_WORKERS")
    if configured:
        return max(1, int(configured))
    return 1 if count <= 4 else max(1, min(count // 2, (os.cpu_count() or 2) - 1, 12))


def _run_ledgers(plan, market, portfolios, cpi, progress=None):
    """Run the first ``retirement_paths`` draws, in worker processes when there are several."""
    count = plan["market"]["retirement_paths"]
    workers = _workers(count)
    chunks = [c for c in np.array_split(np.arange(count), min(count, max(1, workers * 3))) if len(c)]
    out = []
    if workers == 1:
        for chunk in chunks:
            out += _run_chunk(plan, market, portfolios.indices[chunk], chunk.tolist(), portfolios.retirement_start, cpi)
            if progress:
                progress(len(out), count)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_chunk, plan, market, portfolios.indices[chunk], chunk.tolist(),
                               portfolios.retirement_start, cpi) for chunk in chunks]
        for future in as_completed(futures):
            out += future.result()
            if progress:
                progress(len(out), count)
    return out


def _bands(dates, frame_rows, name) -> pd.DataFrame:
    q = np.quantile(np.stack(frame_rows), QUANTILES, axis=0)
    return pd.DataFrame({"Date": dates, "Series": name, "P05": q[0], "P25": q[1], "P50": q[2], "P75": q[3], "P95": q[4]})


def run_plan(plan: dict, output_root: str | Path | None = DEFAULT_ROOT, *, market=None, progress=None) -> PlanRun:
    """Resample entered portfolios, then run a daily tax ledger on shared draws.

    ``progress(done, total)`` is called as retirement ledgers finish.
    """
    plan = normalize_plan(plan)
    market = market or load_plan_markets(plan["assets"])
    target = target_observations(plan)
    portfolios = analyse_portfolios(plan, market, target)
    cpi = plan["assumptions"]["cpi_annual"]
    _, _, years, notes = build_inputs(plan, market=market, returns=portfolios.returns_for(market, 0))
    summaries = sorted(_run_ledgers(plan, market, portfolios, cpi, progress), key=lambda item: item[0]["Path"])
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
                   account_bands, retirement_annual)
