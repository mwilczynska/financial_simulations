"""One path's sampled markets: each ticker and each entered portfolio compounded daily, with summary statistics.

The daily returns are the joint donor rows drawn for the path (``PortfolioAnalysis.returns_for``), the same rows the
path's tax ledger ran on. Portfolios are compounded as ``analysis._simulate`` compounds them, so a portfolio's
statistics here equal that path's row in ``PortfolioAnalysis.outcomes``.
"""

import numpy as np
import pandas as pd

from financial_simulations.retirement.analysis import PORTFOLIOS
from financial_simulations.retirement.real import stock_deflator


PORTFOLIO, ASSET = "Portfolio", "Ticker"
ONE_PORTFOLIO = "Your portfolio"
TRADING_DAYS = 252  # the annualising convention of the portfolio analysis


def compound(returns: np.ndarray, dates, weights: np.ndarray, rebalance: bool) -> np.ndarray:
    """Value of $1 held at ``weights`` on each date (the first is the opening mark).

    With ``rebalance`` the holdings reset to the weights before the first return observation of each calendar
    year; otherwise the weights drift.
    """
    positions = np.asarray(weights, dtype=float).copy()
    values = np.empty(len(returns) + 1)
    values[0] = positions.sum()
    for step in range(len(returns)):
        if rebalance and dates[step + 1].year != dates[step].year:
            positions = positions.sum() * weights
        positions = positions * (1 + returns[step])
        values[step + 1] = positions.sum()
    return values


def path_markets(plan: dict, market, portfolios, path: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Growth of $1 on every observation date, and one row of statistics per series, for one path.

    The growth frame is nominal, indexed by date, with a column per series: the entered portfolios first, then
    each ticker. When the outside and super portfolios hold the same weights and rebalance alike they are one
    series. Statistics: nominal CAGR, CAGR after the plan's CPI assumption, annualised volatility of daily returns
    (sample standard deviation times the square root of 252), the deepest fall below a previous high, and the
    ending value of $1 in today's dollars.
    """
    returns = portfolios.returns_for(market, path)
    dates = tuple(portfolios.dates)
    tickers = tuple(market.path.assets)
    entered = {title: (np.array([plan[section]["weights"].get(t, 0.0) for t in tickers]),
                       plan[section]["rebalance"] == "annual") for title, section in PORTFOLIOS}
    (first, a), (second, b) = entered.items()
    if np.allclose(a[0], b[0]) and a[1] == b[1]:
        shown = {ONE_PORTFOLIO: a}
    else:
        shown = {f"{first} portfolio": a, f"{second} portfolio": b}
    growth = pd.DataFrame({name: compound(returns, dates, weights, rebalance) for name, (weights, rebalance) in shown.items()},
                          index=pd.DatetimeIndex(dates, name="Date"))
    for column, ticker in enumerate(tickers):
        growth[ticker] = np.concatenate(([1.0], np.cumprod(1 + returns[:, column])))
    years = (growth.index[-1] - growth.index[0]).days / 365.25
    prices = float(stock_deflator([growth.index[-1]], growth.index[0], plan["assumptions"]["cpi_annual"])[0])
    rows = []
    for name in growth:
        values = growth[name].to_numpy()
        daily = values[1:] / values[:-1] - 1
        row = {"Series": name, "Kind": PORTFOLIO if name in shown else ASSET,
               "CAGR": float(values[-1] ** (1 / years) - 1), "CAGR after inflation": float((values[-1] / prices) ** (1 / years) - 1),
               "Volatility": float(daily.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(daily) > 1 else 0.0,
               "Worst drawdown": float((values / np.maximum.accumulate(values) - 1).min()),
               "Growth of $1 after inflation": float(values[-1] / prices)}
        for title, (weights, _) in entered.items():
            row[f"{title} weight"] = float(weights[tickers.index(name)]) if name in tickers else np.nan
        rows.append(row)
    return growth, pd.DataFrame(rows)


def real_growth(growth: pd.DataFrame, cpi: float) -> pd.DataFrame:
    """The growth frame in today's dollars."""
    return growth.div(stock_deflator(growth.index, growth.index[0], cpi), axis=0)
