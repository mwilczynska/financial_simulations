"""Daily tax-ledger paths for a plan, run in reusable worker processes.

Kept apart from ``run_plan`` so that worker processes import only the ledger,
plan and rule code, not the plotting and reporting libraries.
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
import ctypes
from datetime import date
import os
import sys

import numpy as np
import pandas as pd

from financial_simulations.retirement.flows import account_flows, household_flows
from financial_simulations.retirement.ledger import LedgerResult, run_ledger
from financial_simulations.retirement.plan import build_inputs
from financial_simulations.retirement.real import flow_deflator, real_daily, real_events, stock_deflator, year_deflator
from financial_simulations.rules.au.parameters import UnsupportedRule


# Total wealth is net of the loans and includes an investment property (the ledger's ``total``); spendable wealth
# leaves the property and its loan out. The accounts are assets.
SERIES = (("Total wealth", ("total",)),
          ("Spendable wealth", ("spendable",)),
          ("Outside super", ("cash", "outside_investments")),
          ("Super and pension", ("accumulation", "pension")),
          ("Pension account", ("pension",)),
          ("Mortgage owed", ("mortgage",)),
          ("Investment property", ("property_value",)),
          ("Investment loan owed", ("property_loan",)))
# Series shown only when some path has something in them.
OPTIONAL_SERIES = ("Spendable wealth", "Mortgage owed", "Investment property", "Investment loan owed")


def _fy_start(day: date) -> date:
    return date(day.year if day.month >= 7 else day.year - 1, 7, 1)


def _summarise(path: int, result: LedgerResult, retire: date, cpi: float):
    """One path's outcome row, month-end account series and financial-year withdrawal rows.

    Every amount is in today's dollars (``real.py``); only ``Ending wealth, nominal`` is not.
    """
    nominal, annual = result.daily, result.annual
    daily = real_daily(nominal, cpi)
    first, last = daily.index[0].date(), daily.index[-1].date()
    dates = daily.index.date  # built once: each call converts the whole index
    step = lambda fy_ending: year_deflator(fy_ending, first, cpi)
    outside = daily["cash"] + daily["outside_investments"]
    totals = {name: daily[list(columns)].sum(axis=1) for name, columns in SERIES}
    monthly = {name: series.resample("ME").last().to_numpy() for name, series in totals.items()}
    shortfall_days = daily.index[daily["shortfall"] > 0]
    depleted = daily.index[(outside <= 1.0) & (dates > first)]
    flow_columns = ["spending_paid", "tax_paid", "division_296", "shortfall", "pension_payments", "lump_sums", "age_pension",
                    "mortgage_interest", "rent", "property_costs", "property_interest"]
    flows = daily[flow_columns].resample("YE-JUN").sum()
    # Withdrawal rates use nominal flows over nominal wealth: today's-dollar flows are deflated in whole financial-year
    # steps but wealth by exact days, so their ratio would not be the nominal rate (review finding 14).
    nominal_flows = nominal[flow_columns].resample("YE-JUN").sum()
    rows = []
    for end, values in flows.iterrows():
        begin = _fy_start(end.date())
        before = daily.index[dates < begin]
        opening = float(daily["total"].iloc[0] if before.empty else daily["total"].loc[before[-1]])
        # Withdrawal rates are over spendable wealth: an investment property's equity is never sold (ADR 0054).
        opening_nominal = float(nominal["spendable"].iloc[0] if before.empty else nominal["spendable"].loc[before[-1]])
        retired = begin >= retire and end.date() <= last
        # The draw on your own wealth: spending, tax (personal and Division 296), mortgage interest and an investment
        # property's interest and running costs, less the Age Pension and rent that paid part of them. Loan principal
        # repaid moves wealth from assets to a loan, so it is not a draw.
        n = nominal_flows.loc[end]
        withdrawal = max(0.0, float(n["spending_paid"] + max(n["tax_paid"], 0.0) + n["division_296"]
                                    + n["mortgage_interest"] + n["property_interest"] + n["property_costs"]
                                    - n["age_pension"] - n["rent"]))
        rows.append({"Path": path, "Financial year": f"{begin.year}-{str(begin.year + 1)[2:]}", "FY ending": begin.year + 1,
                     "Full retired year": retired, "Wealth at 1 July": opening, "Spending paid": float(values["spending_paid"]),
                     "Tax paid": float(values["tax_paid"]), "Shortfall": float(values["shortfall"]),
                     "Pension payments": float(values["pension_payments"]), "Super lump sums": float(values["lump_sums"]),
                     "Age Pension": float(values["age_pension"]), "Division 296": float(values["division_296"]),
                     "Mortgage interest": float(values["mortgage_interest"]), "Rent": float(values["rent"]),
                     "Property costs": float(values["property_costs"]),
                     "Investment loan interest": float(values["property_interest"]),
                     "Withdrawal rate": withdrawal / opening_nominal if retired and opening_nominal > 1 else np.nan})
    # Each year's money in and out on this path, so the app can show medians across paths.
    yearly = household_flows(daily, inflation=True)
    household = yearly.pivot_table(index="FY ending", columns="Flow", values="AUD", aggfunc="sum")
    totals = yearly.drop_duplicates("FY ending").set_index("FY ending")
    net = totals["Net change"]
    moves = account_flows(daily, real_events(result.events, first, cpi))
    added = moves.loc[moves["Flow"] == "Savings invested"].groupby("FY ending")["AUD"].sum()
    for row in rows:
        year = row["FY ending"]
        row.update({f"Flow: {flow}": float(household.loc[year, flow]) for flow in household.columns})
        row["Net change in wealth"] = float(net.loc[year])
        row["Wealth at start of year"] = float(totals.loc[year, "Opening"])
        row["Wealth at end of year"] = float(totals.loc[year, "Closing"])
        # A transfer from cash, not a change in total wealth, so it is kept apart from the flows above.
        row["Added to outside investments"] = float(added.get(year, 0.0))
    retired_rates = [r["Withdrawal rate"] for r in rows if r["Full retired year"] and np.isfinite(r["Withdrawal rate"])]
    spending = _retirement_spending(result, nominal, rows, retire, first, cpi)
    at_retirement = daily.loc[dates <= retire, "total"]
    accessible = daily.index[daily["super_accessible"].astype(bool)]
    unpaid = sum(item["amount"] / step(int(item["financial_year"][:4]) + 1) for item in result.outstanding["unpaid_tax"])
    shortfall = float(daily["shortfall"].sum())
    # Tax already incurred but not paid at the horizon: assessments not yet due (refunds count against them),
    # pending Division 296, unpaid debts and an estimate for an unassessed closing period. Nominal, at the end date.
    owed = result.outstanding
    owed_nominal = (sum(l["amount"] for l in owed["tax_liabilities"]) + sum(d["amount"] for d in owed["division_296"])
                    + sum(u["amount"] for u in owed["unpaid_tax"])
                    + (owed["unassessed_year"] or {}).get("estimated_tax", 0.0))
    end_row = nominal.iloc[-1]
    # Money that could settle it: outside wealth, the pension and accumulation if accessible at the end.
    available = (end_row["cash"] + end_row["outside_investments"] + end_row["pension"]
                 + (end_row["accumulation"] if bool(end_row["super_accessible"]) else 0.0))
    settles = owed_nominal <= available + 1.0
    end_price = float(stock_deflator([nominal.index[-1]], nominal.index[0], cpi)[0])
    pension_start = daily.index[daily["pension"] > 0]
    age_pension_paid = daily.index[daily["age_pension"] > 0]
    outcome = {"Path": path, "Status": "depleted" if shortfall > 0 or unpaid > 0 or not settles else "funded", "Reason": "",
               "Ending wealth": float(daily["total"].iloc[-1]),
               "Ending wealth, nominal": float(nominal["total"].iloc[-1]),
               "Tax owed at end": owed_nominal / end_price,
               "Ending wealth after tax owed": float(daily["total"].iloc[-1]) - owed_nominal / end_price,
               "Can settle tax owed at end": bool(settles),
               "Ending outside wealth": float(outside.iloc[-1]),
               "Ending super and pension": float(daily["accumulation"].iloc[-1] + daily["pension"].iloc[-1]),
               "Wealth at retirement": float(at_retirement.iloc[-1]) if len(at_retirement) else np.nan,
               # Total wealth on the first day super can be withdrawn, when that falls after the start.
               "Wealth when super accessible": (float(daily["total"].loc[accessible[0]])
                                                if len(accessible) and accessible[0] > daily.index[0] else np.nan),
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
               "Mortgage interest": float(daily["mortgage_interest"].sum()),
               "Mortgage owed at end": float(daily["mortgage"].iloc[-1]),
               "Mortgage paid off": _paid_off(daily["mortgage"]),
               "Property value at end": float(daily["property_value"].iloc[-1]),
               "Investment loan owed at end": float(daily["property_loan"].iloc[-1]),
               "Investment loan paid off": _paid_off(daily["property_loan"]),
               "Rent received": float(daily["rent"].sum()),
               "Property costs": float(daily["property_costs"].sum()),
               "Investment loan interest": float(daily["property_interest"].sum()),
               "Rental loss carried forward at end": owed["rental_loss_carried_forward"] / end_price,
               # The property is never sold; this shows what selling it could have covered when money first ran out.
               "Property equity when money ran out": (
                   float(daily["property_value"].loc[shortfall_days[0]] - daily["property_loan"].loc[shortfall_days[0]])
                   if len(shortfall_days) and daily["property_value"].iloc[0] > 0 else np.nan),
               "Pension payments": float(daily["pension_payments"].sum()),
               "Pension balance at start": float(daily["pension"].loc[pension_start[0]]) if len(pension_start) else 0.0,
               "Age Pension received": float(daily["age_pension"].sum()),
               "Age Pension first paid": str(age_pension_paid[0].date()) if len(age_pension_paid) else "",
               "First retired-year withdrawal rate": retired_rates[0] if retired_rates else np.nan,
               "Highest withdrawal rate": max(retired_rates) if retired_rates else np.nan,
               "Median withdrawal rate": float(np.median(retired_rates)) if retired_rates else np.nan,
               **spending}
    return outcome, monthly, rows


def _paid_off(owed: pd.Series) -> str:
    """The first day nothing is owed on a mortgage held at the start; empty without one or if never repaid."""
    if owed.iloc[0] <= 0:
        return ""
    clear = owed.index[owed.to_numpy() <= 0]
    return str(clear[0].date()) if len(clear) else ""


def _retirement_spending(result, nominal, rows, retire, first, cpi):
    """How retirement spending started and how low it went, in today's dollars.

    The starting amount is twelve times the first monthly spending need on or after the retirement date, and the
    starting rate is that annual amount over spendable wealth the day before. The lowest year is the smallest spending
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
    before = nominal.loc[nominal.index < when, "spendable"]
    wealth = float(before.iloc[-1]) if len(before) else float(nominal["spendable"].iloc[0])
    start = annual / float(flow_deflator([when], first, cpi)[0])
    retired = [r["Spending paid"] for r in rows if r["Full retired year"]]
    lowest = min(retired) if retired else np.nan
    return {"Starting retirement spending": start, "Starting withdrawal rate": annual / wealth if wealth > 0 else np.nan,
            "Lowest retired-year spending": lowest,
            "Deepest cut below start": min(0.0, lowest / start - 1) if retired and start > 0 else np.nan,
            "Years below start": int(sum(v < 0.99 * start for v in retired))}


def _run_chunk(plans, market, indices, paths, retire, cpi):
    """Worker: run every strategy's ledger on several shared draws and keep only their summaries.

    ``plans`` are one plan per compared strategy (``strategy_plan``); each path's draw is used by all of them, so the
    strategies are compared on identical markets. Returns ``(rule, summary)`` pairs.
    """
    out = []
    for path, rows in zip(paths, indices):
        returns = market.path.returns[rows]
        for plan in plans:
            rule = plan["spending"]["rule"]
            inputs, scenario, years, _ = build_inputs(plan, market=market, returns=returns)
            try:
                result = run_ledger(inputs, scenario, years)
            except UnsupportedRule as exc:
                out.append((rule, ({"Path": path, "Status": "unsupported", "Reason": str(exc)}, None, [])))
                continue
            out.append((rule, _summarise(path, result, retire, cpi)))
    return out


# Worker processes run below normal priority, so the rest of the computer stays responsive (ADR 0042). The automatic
# count leaves CPU_HEADROOM hardware threads free and keeps MEMORY_RESERVE of physical memory available.
CPU_HEADROOM = 4
MEMORY_RESERVE = 4 * 1024 ** 3
# Measured 2 November 2026: one worker running 50-year ledgers peaked at a 142 MB working set (123 MB committed).
WORKER_MEMORY = 200 * 1024 ** 2


def available_memory() -> int | None:
    """Physical memory available now, in bytes, or ``None`` where the system does not report it."""
    if sys.platform == "win32":
        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total_physical", ctypes.c_ulonglong),
                        ("available_physical", ctypes.c_ulonglong), ("total_page_file", ctypes.c_ulonglong),
                        ("available_page_file", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong),
                        ("available_virtual", ctypes.c_ulonglong), ("available_extended", ctypes.c_ulonglong)]

        status = Status()
        status.length = ctypes.sizeof(status)
        return int(status.available_physical) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None
    try:
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None


def worker_count(tasks: int, requested: int | None = None) -> tuple[int, str | None]:
    """Worker processes for ``tasks`` ledger paths, and a note when memory limited the automatic count.

    ``requested`` (the app's *Calculation cores*) or ``FINANCIAL_SIMULATIONS_WORKERS`` sets the count directly;
    it is never more than the number of tasks. Otherwise: one process for four tasks or fewer (starting workers
    costs more than it saves), else the smaller of half the tasks and the hardware threads less ``CPU_HEADROOM``,
    reduced if the workers would leave less than ``MEMORY_RESERVE`` of physical memory available.
    """
    configured = requested or os.environ.get("FINANCIAL_SIMULATIONS_WORKERS")
    if configured:
        return max(1, min(int(configured), tasks)), None
    if tasks <= 4:
        return 1, None
    workers = max(1, min(tasks // 2, (os.cpu_count() or 2) - CPU_HEADROOM))
    available = available_memory()
    if available is not None:
        fits = max(1, (available - MEMORY_RESERVE) // WORKER_MEMORY)
        if fits < workers:
            return int(fits), (f"Ran the daily ledgers on {fits} worker processes instead of {workers}: only "
                               f"{available / 1024 ** 3:.1f} GB of memory was available.")
    return workers, None


def automatic_workers(tasks: int = 1000) -> int:
    """The automatic worker count for a large run on this computer, for display."""
    return worker_count(tasks)[0]


def run_ledgers(plans, market, portfolios, cpi, progress=None, workers=None) -> dict:
    """Run the first ``retirement_paths`` draws for every strategy plan, in ``workers`` processes.

    ``plans`` holds one plan per compared strategy. Returns each strategy's path summaries, by rule, in path order.
    ``progress(done, total)`` counts ledgers (paths times strategies); ``workers=None`` uses ``worker_count``.
    """
    count = plans[0]["market"]["retirement_paths"]
    total = count * len(plans)
    if workers is None:
        workers = worker_count(total)[0]
    chunks = [c for c in np.array_split(np.arange(count), min(count, max(1, workers * 3))) if len(c)]
    out = []
    if workers == 1:
        for chunk in chunks:
            out += _run_chunk(plans, market, portfolios.indices[chunk], chunk.tolist(), portfolios.retirement_start, cpi)
            if progress:
                progress(len(out), total)
    else:
        pool = _pool(workers)
        with _without_main_module():  # workers start lazily inside submit
            futures = [pool.submit(_run_chunk, plans, market, portfolios.indices[chunk], chunk.tolist(),
                                   portfolios.retirement_start, cpi) for chunk in chunks]
        try:
            for future in as_completed(futures):
                out += future.result()
                if progress:
                    progress(len(out), total)
        except BrokenProcessPool:
            _POOL.clear()
            raise
    by_rule = {plan["spending"]["rule"]: [] for plan in plans}
    for rule, summary in out:
        by_rule[rule].append(summary)
    return {rule: sorted(summaries, key=lambda item: item[0]["Path"]) for rule, summaries in by_rule.items()}


_POOL: dict = {}


def _pool(workers: int) -> ProcessPoolExecutor:
    """A worker pool kept between runs: starting processes costs seconds, so later runs reuse them."""
    if _POOL.get("workers") != workers:
        if "pool" in _POOL:
            _POOL["pool"].shutdown(wait=False, cancel_futures=True)
        _POOL.update(workers=workers, pool=ProcessPoolExecutor(max_workers=workers, initializer=_below_normal_priority))
    return _POOL["pool"]


BELOW_NORMAL_PRIORITY_CLASS = 0x4000


def _below_normal_priority() -> None:
    """Worker start-up: yield the CPU to foreground programs whenever they need it."""
    try:
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(10)
    except (AttributeError, OSError):
        pass  # priority is a courtesy; the calculation is the same at any priority


def warm_pool(count: int = 100, requested: int | None = None) -> None:
    """Start the worker processes ahead of the first run (the browser app calls this when it loads)."""
    workers = worker_count(count, requested)[0]
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
