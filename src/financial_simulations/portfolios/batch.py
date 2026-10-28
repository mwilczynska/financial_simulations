"""Batched daily accounting, reconciled to the calendar-ledger engine."""

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

import numpy as np
import pandas as pd

from financial_simulations.dates import as_date
from financial_simulations.portfolios.engine import CashFlow
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


@dataclass(frozen=True)
class BatchLedger:
    """Account state at every mark: each observation and each dated-flow calendar day.

    Calendar days that are neither carry the previous mark, as in the full
    ledger, so only marks are stored: shape (paths, marks) per state array.
    """

    dates: tuple
    is_market_observation: np.ndarray
    rebalanced: np.ndarray
    contributions: np.ndarray
    withdrawals_requested: np.ndarray
    withdrawals_paid: np.ndarray
    cash: np.ndarray
    invested_value: np.ndarray
    value: np.ndarray

    @property
    def shortfall(self) -> np.ndarray:
        return np.maximum(0.0, self.withdrawals_requested[None, :] - self.withdrawals_paid)

    def calendar_values(self):
        """Expand marks to every calendar day by carrying the last mark."""
        days = tuple(pd.date_range(self.dates[0], self.dates[-1]).date)
        marks = np.array(self.dates, dtype="datetime64[D]")
        index = np.searchsorted(marks, np.array(days, dtype="datetime64[D]"), side="right") - 1
        return days, self.value[:, index]


def simulate_paths(returns, dates, portfolio: PortfolioSpec, initial_value: float,
                   cash_flows: Iterable[CashFlow] = (), *, initial_cash: float = 0.0) -> BatchLedger:
    """Many paths through the daily ledger's event order, sharing one schedule.

    Mirrors ``simulate_portfolio``: before-return flows; annual rebalance of
    risky holdings on a year's first observation; return; after-return flows;
    sweep of closed-date deposits at the next observation close. Withdrawals
    use cash, then proportional holdings on observation dates only; unmet
    amounts are recorded per path, never borrowed or retried.
    """
    returns = np.asarray(returns, dtype=float)
    dates = tuple(as_date(value) for value in dates)
    if not dates or any(b <= a for a, b in zip(dates, dates[1:])):
        raise ValueError("Account observation dates must be sorted, unique and nonempty.")
    if returns.ndim != 3 or returns.shape[1:] != (len(dates) - 1, len(portfolio.assets)):
        raise ValueError("Expected (paths, observations, portfolio assets) daily returns.")
    if not len(returns) or not np.isfinite(returns).all() or (returns < -1).any():
        raise ValueError("Daily simple returns must be finite and at least -100%, with at least one path.")
    for value in (initial_value, initial_cash):
        if isinstance(value, bool) or not isfinite(float(value)) or float(value) < 0:
            raise ValueError("Initial investment and cash must be finite and nonnegative.")
    scheduled = {}
    for event in cash_flows:
        if not isinstance(event, CashFlow):
            raise ValueError("Supply CashFlow objects.")
        if not dates[0] <= event.date <= dates[-1]:
            raise ValueError(f"Cash flow {event.date} falls outside the actual valuation horizon.")
        scheduled.setdefault((event.date, event.timing), []).append(event.amount)
    observations = {day: i for i, day in enumerate(dates)}
    marks = sorted(set(dates) | {day for day, _ in scheduled})
    paths, count = len(returns), len(marks)
    weights = np.asarray(list(portfolio.weights.values()))
    positions = np.broadcast_to(float(initial_value) * weights, (paths, len(weights))).copy()
    cash = np.full(paths, float(initial_cash))
    pending = np.zeros(paths)
    state = {name: np.empty((paths, count)) for name in ("paid", "cash", "invested", "value")}
    flags = {name: np.zeros(count, dtype=bool) for name in ("observation", "rebalanced")}
    contributions, requested = np.zeros(count), np.zeros(count)
    last_market_year = dates[0].year
    with np.errstate(over="raise", invalid="raise"):
        for mark, day in enumerate(marks):
            observation = observations.get(day)
            can_trade = observation is not None
            paid = np.zeros(paths)

            def process(timing):
                nonlocal positions, cash, pending
                for amount in scheduled.get((day, timing), []):
                    if amount >= 0:
                        contributions[mark] += amount
                        if can_trade:
                            positions = positions + amount * weights
                        else:
                            cash = cash + amount
                            pending = pending + amount
                        continue
                    needed = -amount
                    requested[mark] += needed
                    cash_payment = np.minimum(cash, needed)
                    cash = cash - cash_payment
                    pending = np.minimum(pending, cash)
                    payment = cash_payment
                    if can_trade:
                        invested = positions.sum(axis=1)
                        sale = np.where(needed > cash_payment, np.minimum(invested, needed - cash_payment), 0.0)
                        scale = np.divide(sale, invested, out=np.zeros(paths), where=invested > 0)
                        positions = positions * (1.0 - scale)[:, None]
                        payment = payment + sale
                    paid[:] += payment

            process("before_return")
            rebalanced = (can_trade and observation != 0 and portfolio.rebalance == "annual"
                          and day.year != last_market_year)
            if rebalanced:
                positions = positions.sum(axis=1, keepdims=True) * weights
            if can_trade:
                if observation != 0:
                    positions = positions * (1.0 + returns[:, observation - 1, :])
                last_market_year = day.year
            process("after_return")
            if can_trade and observation != 0:
                positions = positions + pending[:, None] * weights
                cash, pending = cash - pending, np.zeros(paths)
            invested = positions.sum(axis=1)
            state["paid"][:, mark], state["cash"][:, mark] = paid, cash
            state["invested"][:, mark], state["value"][:, mark] = invested, invested + cash
            flags["observation"][mark], flags["rebalanced"][mark] = can_trade, rebalanced
    if not np.isfinite(state["value"]).all():
        raise ValueError("Nonfinite batched account state.")
    for array in (*state.values(), *flags.values(), contributions, requested):
        array.setflags(write=False)
    return BatchLedger(tuple(marks), flags["observation"], flags["rebalanced"], contributions, requested,
                       state["paid"], state["cash"], state["invested"], state["value"])
