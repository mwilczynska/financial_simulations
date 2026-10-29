"""Today's dollars: the planner's results deflated by the CPI assumption.

Today's dollars are dollars of the plan's opening date. A balance on date ``d``
is divided by ``(1 + cpi) ** ((d - start).days / 365.25)``. Money that flows
during a financial year (salary, spending, tax, returns) is divided by
``(1 + cpi) ** n``, where ``n`` is the number of whole financial years since
the opening year. That is the step on which spending is indexed each 1 July,
so spending that keeps its buying power shows the same amount every year, and a
withdrawal rate (a year's flows over wealth on its 1 July) is unchanged.

Prices keep rising inside a year while flows are stepped, so real wealth
changes by more than the sum of real flows. ``household_flows`` reports that
difference as the ``Inflation`` flow: the buying power wealth lost that year.

The ledger itself stays nominal, because tax law works in nominal dollars.
Only reporting is converted.
"""

from datetime import date

import numpy as np
import pandas as pd


STOCKS = ("cash", "outside_investments", "accumulation", "pension", "total", "pending_contributions", "tax_liabilities")
FLOWS = ("market_pnl", "salary", "employer_contributions", "contributions_tax", "spending_paid", "shortfall", "tax_paid",
         "tax_unpaid", "fund_tax", "distributions", "pension_payments", "lump_sums", "interest")


def _fy_end(day) -> int:
    return day.year + (day.month >= 7)


def stock_deflator(dates, start, cpi: float) -> np.ndarray:
    """Price level on each date relative to ``start``: divide a balance by it."""
    days = (pd.DatetimeIndex(dates) - pd.Timestamp(start)).days.to_numpy()
    return (1 + cpi) ** (days / 365.25)


def flow_deflator(dates, start, cpi: float) -> np.ndarray:
    """Price step for money flowing on each date: whole financial years since the opening year."""
    years = np.array([_fy_end(d) for d in pd.DatetimeIndex(dates)]) - _fy_end(pd.Timestamp(start))
    return (1 + cpi) ** years


def year_deflator(fy_ending: int, start, cpi: float) -> float:
    """Price step for a whole financial year, given the calendar year it ends in."""
    return (1 + cpi) ** (int(fy_ending) - _fy_end(pd.Timestamp(start)))


def real_daily(daily: pd.DataFrame, cpi: float) -> pd.DataFrame:
    """A ledger's daily frame in today's dollars (dollars of its first day)."""
    start = daily.index[0]
    real = daily.copy()
    stocks = [c for c in STOCKS if c in real]
    flows = [c for c in FLOWS if c in real]
    real[stocks] = real[stocks].div(stock_deflator(real.index, start, cpi), axis=0)
    real[flows] = real[flows].div(flow_deflator(real.index, start, cpi), axis=0)
    return real


def real_events(events: pd.DataFrame, start, cpi: float) -> pd.DataFrame:
    """Event amounts in today's dollars, each on its date's financial-year step (for yearly transfer totals)."""
    if events.empty:
        return events
    real = events.copy()
    real["amount"] = real["amount"] / flow_deflator(pd.to_datetime(real["date"]), start, cpi)
    return real


def real_on(amount: float, day: date, start, cpi: float) -> float:
    """One balance on ``day`` in today's dollars."""
    return float(amount / stock_deflator([day], start, cpi)[0])
