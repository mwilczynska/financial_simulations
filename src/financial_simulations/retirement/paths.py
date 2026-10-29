"""Daily tax-ledger paths for a plan, run in reusable worker processes.

Kept apart from ``run_plan`` so that worker processes import only the ledger,
plan and rule code, not the plotting and reporting libraries.
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from datetime import date
import os
import sys

import numpy as np
import pandas as pd

from financial_simulations.retirement.flows import account_flows, household_flows
from financial_simulations.retirement.ledger import LedgerResult, run_ledger
from financial_simulations.retirement.plan import build_inputs
from financial_simulations.retirement.real import flow_deflator, real_daily, real_events, year_deflator
from financial_simulations.rules.au.parameters import UnsupportedRule


SERIES = (("Total wealth", ("cash", "outside_investments", "accumulation", "pension")),
          ("Outside super", ("cash", "outside_investments")),
          ("Super and pension", ("accumulation", "pension")),
          ("Pension account", ("pension",)))


def _fy_start(day: date) -> date:
    return date(day.year if day.month >= 7 else day.year - 1, 7, 1)


def _summarise(path: int, result: LedgerResult, retire: date, cpi: float):
    """One path's outcome row, month-end account series and financial-year withdrawal rows.

    Every amount is in today's dollars (``real.py``); only ``Ending wealth, nominal`` is not.
    """
    nominal, annual = result.daily, result.annual
    daily = real_daily(nominal, cpi)
    first, last = daily.index[0].date(), daily.index[-1].date()
    step = lambda fy_ending: year_deflator(fy_ending, first, cpi)
    outside = daily["cash"] + daily["outside_investments"]
    totals = {name: daily[list(columns)].sum(axis=1) for name, columns in SERIES}
    monthly = {name: series.resample("ME").last().to_numpy() for name, series in totals.items()}
    shortfall_days = daily.index[daily["shortfall"] > 0]
    depleted = daily.index[(outside <= 1.0) & (daily.index.date > first)]
    flows = daily[["spending_paid", "tax_paid", "shortfall", "pension_payments", "lump_sums", "age_pension"]].resample("YE-JUN").sum()
    rows = []
    for end, values in flows.iterrows():
        begin = _fy_start(end.date())
        before = daily.index[daily.index.date < begin]
        opening = float(daily["total"].iloc[0] if before.empty else daily["total"].loc[before[-1]])
        retired = begin >= retire and end.date() <= last
        # The draw on your own wealth: spending and tax, less the Age Pension that paid part of them.
        withdrawal = max(0.0, float(values["spending_paid"] + max(values["tax_paid"], 0.0) - values["age_pension"]))
        rows.append({"Path": path, "Financial year": f"{begin.year}-{str(begin.year + 1)[2:]}", "FY ending": begin.year + 1,
                     "Full retired year": retired, "Wealth at 1 July": opening, "Spending paid": float(values["spending_paid"]),
                     "Tax paid": float(values["tax_paid"]), "Shortfall": float(values["shortfall"]),
                     "Pension payments": float(values["pension_payments"]), "Super lump sums": float(values["lump_sums"]),
                     "Age Pension": float(values["age_pension"]),
                     "Withdrawal rate": withdrawal / opening if retired and opening > 1 else np.nan})
    # Each year's money in and out on this path, so the app can show medians across paths.
    yearly = household_flows(daily, inflation=True)
    household = yearly.pivot_table(index="FY ending", columns="Flow", values="AUD", aggfunc="sum")
    net = yearly.drop_duplicates("FY ending").set_index("FY ending")["Net change"]
    moves = account_flows(daily, real_events(result.events, first, cpi))
    added = moves.loc[moves["Flow"] == "Savings invested"].groupby("FY ending")["AUD"].sum()
    for row in rows:
        year = row["FY ending"]
        row.update({f"Flow: {flow}": float(household.loc[year, flow]) for flow in household.columns})
        row["Net change in wealth"] = float(net.loc[year])
        # A transfer from cash, not a change in total wealth, so it is kept apart from the flows above.
        row["Added to outside investments"] = float(added.get(year, 0.0))
    retired_rates = [r["Withdrawal rate"] for r in rows if r["Full retired year"] and np.isfinite(r["Withdrawal rate"])]
    spending = _retirement_spending(result, nominal, rows, retire, first, cpi)
    at_retirement = daily.loc[daily.index.date <= retire, "total"]
    unpaid = sum(item["amount"] / step(int(item["financial_year"][:4]) + 1) for item in result.outstanding["unpaid_tax"])
    shortfall = float(daily["shortfall"].sum())
    pension_start = daily.index[daily["pension"] > 0]
    age_pension_paid = daily.index[daily["age_pension"] > 0]
    outcome = {"Path": path, "Status": "depleted" if shortfall > 0 or unpaid > 0 else "funded", "Reason": "",
               "Ending wealth": float(daily["total"].iloc[-1]),
               "Ending wealth, nominal": float(nominal["total"].iloc[-1]),
               "Ending outside wealth": float(outside.iloc[-1]),
               "Ending super and pension": float(daily["accumulation"].iloc[-1] + daily["pension"].iloc[-1]),
               "Wealth at retirement": float(at_retirement.iloc[-1]) if len(at_retirement) else np.nan,
               "Largest fall in wealth": float((daily["total"] / daily["total"].cummax() - 1).min()),
               "Spending paid": float(daily["spending_paid"].sum()), "Spending shortfall": shortfall,
               "Shortfall years": int(sum(r["Shortfall"] > 0 for r in rows)),
               "First shortfall": str(shortfall_days[0].date()) if len(shortfall_days) else "",
               "Outside money runs out": str(depleted[0].date()) if len(depleted) else "",
               "Unpaid tax": float(unpaid),
               "Personal tax assessed": float(sum((a["assessment"].net_tax + a["assessment"].division_293_tax)
                                                  / step(int(a["financial_year"][:4]) + 1) for a in annual)),
               "Fund tax": float(daily["fund_tax"].sum()),
               "Division 296 tax": float(daily["division_296"].sum()),
               "Pension payments": float(daily["pension_payments"].sum()),
               "Pension balance at start": float(daily["pension"].loc[pension_start[0]]) if len(pension_start) else 0.0,
               "Age Pension received": float(daily["age_pension"].sum()),
               "Age Pension first paid": str(age_pension_paid[0].date()) if len(age_pension_paid) else "",
               "First retired-year withdrawal rate": retired_rates[0] if retired_rates else np.nan,
               "Highest withdrawal rate": max(retired_rates) if retired_rates else np.nan,
               "Median withdrawal rate": float(np.median(retired_rates)) if retired_rates else np.nan,
               **spending}
    return outcome, monthly, rows


def _retirement_spending(result, nominal, rows, retire, first, cpi):
    """How retirement spending started and how low it went, in today's dollars.

    The starting amount is twelve times the first monthly spending need on or after the retirement date, and the
    starting rate is that annual amount over total wealth the day before. The lowest year is the smallest spending
    actually paid in a full retired financial year (shortfalls lower it).
    """
    empty = {"Starting retirement spending": np.nan, "Starting withdrawal rate": np.nan,
             "Lowest retired-year spending": np.nan, "Deepest cut below start": np.nan, "Years below start": 0}
    events = result.events
    if events.empty or "scheduled" not in events:
        return empty
    needs = events.loc[events["event"] == "spending"]
    scheduled = pd.to_datetime(needs["scheduled"])
    after = needs.loc[scheduled >= pd.Timestamp(retire)]
    if after.empty:
        return empty
    when = pd.Timestamp(after["scheduled"].iloc[0])
    annual = 12 * float(after["requested"].iloc[0])
    before = nominal.loc[nominal.index < when, "total"]
    wealth = float(before.iloc[-1]) if len(before) else float(nominal["total"].iloc[0])
    start = annual / float(flow_deflator([when], first, cpi)[0])
    retired = [r["Spending paid"] for r in rows if r["Full retired year"]]
    lowest = min(retired) if retired else np.nan
    return {"Starting retirement spending": start, "Starting withdrawal rate": annual / wealth if wealth > 0 else np.nan,
            "Lowest retired-year spending": lowest,
            "Deepest cut below start": min(0.0, lowest / start - 1) if retired and start > 0 else np.nan,
            "Years below start": int(sum(v < 0.99 * start for v in retired))}


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


def run_ledgers(plan, market, portfolios, cpi, progress=None):
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
    pool = _pool(workers)
    with _without_main_module():  # workers start lazily inside submit
        futures = [pool.submit(_run_chunk, plan, market, portfolios.indices[chunk], chunk.tolist(),
                               portfolios.retirement_start, cpi) for chunk in chunks]
    try:
        for future in as_completed(futures):
            out += future.result()
            if progress:
                progress(len(out), count)
    except BrokenProcessPool:
        _POOL.clear()
        raise
    return out


_POOL: dict = {}


def _pool(workers: int) -> ProcessPoolExecutor:
    """A worker pool kept between runs: starting processes costs seconds, so later runs reuse them."""
    if _POOL.get("workers") != workers:
        if "pool" in _POOL:
            _POOL["pool"].shutdown(wait=False, cancel_futures=True)
        _POOL.update(workers=workers, pool=ProcessPoolExecutor(max_workers=workers))
    return _POOL["pool"]


def warm_pool(count: int = 100) -> None:
    """Start the worker processes ahead of the first run (the browser app calls this when it loads)."""
    workers = _workers(count)
    if workers > 1:
        pool = _pool(workers)
        with _without_main_module():
            for _ in range(2 * workers):
                pool.submit(_ready)  # each worker imports the ledger code before the first real task arrives


def _ready() -> int:
    return os.getpid()


THREAD_LIMITS = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


@contextmanager
def _without_main_module():
    """Stop spawned workers re-importing ``__main__``.

    On Windows a spawned worker re-runs the launching program's main module.
    Under the browser app that is the app script itself, so each worker re-ran
    the whole app (and tried to start pools of its own). Workers start lazily
    inside ``submit``, so every submission hides the main module; workers only
    need this module.
    """
    main = sys.modules.get("__main__")
    spec, path = getattr(main, "__spec__", None), getattr(main, "__file__", None)
    saved = {name: os.environ.get(name) for name in THREAD_LIMITS}
    try:
        # Workers inherit the environment at spawn. One maths-library thread each: by default OpenBLAS reserves a
        # buffer per CPU thread, which committed about 800 MB per worker on a 32-thread machine (64 MB with one).
        os.environ.update(THREAD_LIMITS)
        if main is not None:
            main.__spec__ = None
            if path is not None:
                del main.__file__
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if main is not None:
            main.__spec__ = spec
            if path is not None:
                main.__file__ = path
