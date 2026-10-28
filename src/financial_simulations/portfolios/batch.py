"""Batched no-flow daily accounting, reconciled to the calendar-ledger engine."""

import numpy as np

from financial_simulations.dates import as_date
from financial_simulations.portfolios.spec import PortfolioSpec


def compound_paths(returns, dates, portfolio: PortfolioSpec, initial_value: float, *, initial_cash: float = 0.0):
    """Return opening plus every observation's wealth, retaining holding drift.

    Shape: (paths, observations, assets). Calendar-only days have no market
    movement in this no-flow/no-extra-cost scope; the full engine handles flows.
    """
    returns = np.asarray(returns, dtype=float)
    dates = tuple(as_date(value) for value in dates)
    if not dates or any(b <= a for a, b in zip(dates, dates[1:])):
        raise ValueError("Account observation dates must be sorted, unique and nonempty.")
    if returns.ndim != 3 or returns.shape[1:] != (len(dates) - 1, len(portfolio.assets)):
        raise ValueError("Expected (paths, observations, portfolio assets) daily returns.")
    if not np.isfinite(returns).all() or (returns < -1).any():
        raise ValueError("Daily simple returns must be finite and at least -100%.")
    for value in (initial_value, initial_cash):
        if isinstance(value, bool) or not np.isfinite(value) or value < 0:
            raise ValueError("Initial investment and retained cash must be finite and nonnegative.")
    weights = np.asarray(list(portfolio.weights.values()))
    positions = np.broadcast_to(initial_value * weights, (len(returns), len(weights))).copy()
    wealth = np.empty((len(returns), len(dates)))
    wealth[:, 0] = initial_value + initial_cash
    with np.errstate(over="raise", invalid="raise"):
        for step, day in enumerate(dates[1:]):
            if portfolio.rebalance == "annual" and day.year != dates[step].year:
                positions = positions.sum(axis=1, keepdims=True) * weights
            positions *= 1 + returns[:, step, :]
            wealth[:, step + 1] = positions.sum(axis=1) + initial_cash
    if not np.isfinite(wealth).all():
        raise ValueError("Nonfinite batched account state.")
    return wealth
