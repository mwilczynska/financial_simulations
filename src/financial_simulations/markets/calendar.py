"""Future observation calendars at the sampled history's observation density."""

from datetime import date
from math import ceil

import pandas as pd


def observations_per_year(dates) -> float:
    """Return observations (returns) per 365.25 calendar days between the first and last date."""
    elapsed = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
    if len(dates) < 2 or elapsed <= 0:
        raise ValueError("An observation rate needs at least two dates on different days.")
    return (len(dates) - 1) * 365.25 / elapsed


def observation_calendar(start, end, per_year: float) -> tuple[date, ...]:
    """The opening mark ``start`` followed by future observation dates through ``end``.

    Each sampled return is one historical observation, so the future calendar
    keeps the history's density: weekdays are kept in order while the count
    stays within ceil(per_year x elapsed calendar days / 365.25). The dropped
    weekdays are evenly spread; they stand in for exchange holidays and dates
    missing from a joint history, and are not a holiday forecast. The result
    depends only on ``start`` and ``per_year``, so a longer horizon extends a
    shorter one. A density above the weekday rate keeps every weekday.
    """
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    dates, kept = [start], 0
    for day in pd.bdate_range(start, end).date:
        if day == start:
            continue
        if kept < ceil(per_year * (day - start).days / 365.25 - 1e-9):
            dates.append(day)
            kept += 1
    return tuple(dates)
