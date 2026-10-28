"""Deterministic daily holdings and dated cash-flow accounting."""

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite
from typing import Iterable

import numpy as np
import pandas as pd

from financial_simulations.dates import as_date
from financial_simulations.markets.path import MarketPath
from financial_simulations.portfolios.spec import PortfolioSpec


@dataclass(frozen=True)
class CashFlow:
    date: date
    amount: float
    timing: str = "after_return"

    def __post_init__(self) -> None:
        object.__setattr__(self, "date", as_date(self.date))
        if isinstance(self.amount, bool) or not isfinite(float(self.amount)):
            raise ValueError("Cash-flow amounts must be finite numbers.")
        object.__setattr__(self, "amount", float(self.amount))
        if self.timing not in ("before_return", "after_return"):
            raise ValueError("Cash-flow timing must be before_return or after_return.")


@dataclass(frozen=True)
class PortfolioResult:
    daily: pd.DataFrame
    portfolio: PortfolioSpec
    initial_value: float
    initial_cash: float


def simulate_portfolio(
    path: MarketPath,
    portfolio: PortfolioSpec,
    initial_value: float,
    cash_flows: Iterable[CashFlow] = (),
    *,
    initial_cash: float = 0.0,
) -> PortfolioResult:
    """Mark every calendar day, applying returns only on supplied observations.

    Trading-date deposits buy target weights; sales use cash then proportional
    current holdings. On other dates only cash can fund a withdrawal. Unmet
    amounts are recorded, never borrowed or automatically retried. Closed-date
    deposits wait in cash until the next observation's close.
    """
    if path.assets != portfolio.assets or path.currency != portfolio.currency:
        raise ValueError("Market assets/order and currency must match the portfolio specification.")
    for value in (initial_value, initial_cash):
        if isinstance(value, bool) or not isfinite(float(value)) or float(value) < 0:
            raise ValueError("Initial investment and cash must be finite and nonnegative.")
    initial_value, initial_cash = float(initial_value), float(initial_cash)
    weights = np.array(list(portfolio.weights.values()))
    positions = initial_value * weights
    cash = initial_cash
    pending_investment = 0.0
    scheduled = {}
    for event in cash_flows:
        if not isinstance(event, CashFlow):
            raise ValueError("Supply CashFlow objects.")
        if not path.dates[0] <= event.date <= path.dates[-1]:
            raise ValueError(f"Cash flow {event.date} falls outside the actual valuation horizon.")
        scheduled.setdefault((event.date, event.timing), []).append(event)
    observations = {day: i for i, day in enumerate(path.dates)}
    day, final_day = path.dates[0], path.dates[-1]
    last_market_year = day.year
    previous_close = initial_value + initial_cash
    rows = []

    while day <= final_day:
        observation = observations.get(day)
        can_trade = observation is not None
        contributions = requested = paid = 0.0

        def process(timing: str) -> None:
            nonlocal positions, cash, pending_investment, contributions, requested, paid
            for event in scheduled.get((day, timing), []):
                if event.amount >= 0:
                    contributions += event.amount
                    if can_trade:
                        positions += event.amount * weights
                    else:
                        cash += event.amount
                        pending_investment += event.amount
                else:
                    needed = -event.amount
                    requested += needed
                    cash_payment = min(cash, needed)
                    cash -= cash_payment
                    pending_investment = min(pending_investment, cash)
                    payment = cash_payment
                    if can_trade and needed > cash_payment:
                        invested = float(positions.sum())
                        sale = min(invested, needed - cash_payment)
                        if invested > 0:
                            positions *= 1.0 - sale / invested
                        payment += sale
                    paid += payment

        process("before_return")
        rebalanced = can_trade and observation != 0 and portfolio.rebalance == "annual" and day.year != last_market_year
        if rebalanced:
            # Cash awaiting investment is swept at the close, not exposed early.
            positions = float(positions.sum()) * weights
        market_pnl = 0.0
        performance_return = np.nan
        if can_trade:
            if observation != 0:
                exposed_wealth = float(positions.sum()) + cash
                with np.errstate(over="raise", invalid="raise"):
                    market_pnl = float(positions @ path.returns[observation - 1])
                    positions *= 1.0 + path.returns[observation - 1]
                performance_return = market_pnl / exposed_wealth if exposed_wealth > 0 else 0.0
            last_market_year = day.year
        process("after_return")
        if can_trade and observation != 0 and pending_investment > 0:
            positions += pending_investment * weights
            cash -= pending_investment
            pending_investment = 0.0
        close = float(positions.sum()) + cash
        if not np.isfinite(positions).all() or not isfinite(close):
            raise ValueError(f"Nonfinite account state on {day}.")
        expected_close = previous_close + market_pnl + contributions - paid
        if not np.isclose(close, expected_close, rtol=1e-11, atol=1e-9):
            raise ArithmeticError(f"Account reconciliation failed on {day}.")
        rows.append({
            "date": day, "is_market_observation": can_trade,
            "opening_value": previous_close, "market_pnl": market_pnl,
            "contributions": contributions, "withdrawals_requested": requested,
            "withdrawals_paid": paid, "shortfall": max(0.0, requested - paid),
            "net_external_flow": contributions - paid,
            "cash": cash, "invested_value": float(positions.sum()), "value": close,
            "performance_return": performance_return, "rebalanced": rebalanced,
            **{f"holding_{asset}": float(position) for asset, position in zip(path.assets, positions)},
        })
        previous_close = close
        day += timedelta(days=1)
    daily = pd.DataFrame(rows).set_index("date")
    daily.index = pd.DatetimeIndex(daily.index, name="Date")
    return PortfolioResult(daily, portfolio, initial_value, initial_cash)
