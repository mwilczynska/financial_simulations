"""Portfolio-first daily bootstrap and retirement path summaries for a plan."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from financial_simulations.markets.resampling import Sampler, sample_indices
from financial_simulations.retirement.plan import horizon


PORTFOLIOS = (("Outside super", "outside"), ("Inside super", "super"))


@dataclass(frozen=True)
class PortfolioAnalysis:
    dates: tuple
    sampled_returns: np.ndarray
    historical: pd.DataFrame
    paths: pd.DataFrame
    outcomes: pd.DataFrame
    annual_returns: pd.DataFrame
    summary: pd.DataFrame


def _wealth(returns: np.ndarray, dates, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Buy and hold at daily resolution; return path wealth and daily return."""
    count, steps, assets = returns.shape
    positions = np.broadcast_to(100 * weights, (count, assets)).copy()
    wealth = np.empty((count, steps + 1))
    wealth[:, 0] = 100
    for step in range(steps):
        positions *= 1 + returns[:, step, :]
        wealth[:, step + 1] = positions.sum(axis=1)
    daily = wealth[:, 1:] / wealth[:, :-1] - 1
    return wealth, daily


def _month_indices(dates) -> np.ndarray:
    series = pd.Series(np.arange(len(dates)), index=pd.DatetimeIndex(dates))
    return np.r_[0, series.resample("ME").last().to_numpy(dtype=int)]


def analyse_portfolios(plan: dict, market, target_dates) -> PortfolioAnalysis:
    """Use identical joint donor rows for each entered portfolio.

    The stationary bootstrap's length counts source return observations.
    Business weekdays are a future ledger template, not a holiday forecast.
    """
    target_dates = tuple(target_dates)
    count = plan["market"]["paths"]
    steps = len(target_dates) - 1
    sampler = Sampler("stationary", plan["market"]["block_length"])
    indices = np.stack([sample_indices(len(market.path.returns), steps, sampler,
                                       seed=plan["market"]["seed"], path_id=i).indices for i in range(count)])
    sampled = market.path.returns[indices]
    monthly = _month_indices(target_dates)
    historical_months = _month_indices(market.path.dates)
    paths, outcomes, annual, summaries, historical = [], [], [], [], []
    for title, section in PORTFOLIOS:
        weights = np.array([plan[section]["weights"].get(ticker, 0.0) for ticker in market.path.assets])
        wealth, daily = _wealth(sampled, target_dates, weights)
        hwealth, hdaily = _wealth(market.path.returns[None, :, :], market.path.dates, weights)
        hwealth = hwealth[0]
        for pos in historical_months:
            historical.append({"Date": market.path.dates[pos], "Portfolio": title, "Growth of 100": float(hwealth[pos])})
        years = (market.path.dates[-1] - market.path.dates[0]).days / 365.25
        h_cagr = float((hwealth[-1] / hwealth[0]) ** (1 / years) - 1)
        h_vol = float(np.std(hdaily[0], ddof=1) * np.sqrt(252))
        h_dd = float(np.min(hwealth / np.maximum.accumulate(hwealth) - 1))
        summaries.append({"Portfolio": title, "Historical CAGR": h_cagr, "Historical volatility": h_vol,
                          "Historical max drawdown": h_dd, "Historical first": market.path.dates[0],
                          "Historical last": market.path.dates[-1]})
        drawdown = wealth / np.maximum.accumulate(wealth, axis=1) - 1
        pyears = (target_dates[-1] - target_dates[0]).days / 365.25
        cagr = np.power(wealth[:, -1] / 100, 1 / pyears) - 1
        vol = np.std(daily, axis=1, ddof=1) * np.sqrt(252)
        for i in range(count):
            outcomes.append({"Portfolio": title, "Path": i, "Terminal growth of 100": float(wealth[i, -1]),
                             "Annualised growth": float(cagr[i]), "Annualised volatility": float(vol[i]),
                             "Maximum drawdown": float(drawdown[i].min())})
        for pos in monthly:
            values = wealth[:, pos]
            q = np.quantile(values, [0.05, 0.25, 0.5, 0.75, 0.95])
            paths.append({"Date": target_dates[pos], "Portfolio": title, "P05": q[0], "P25": q[1],
                          "P50": q[2], "P75": q[3], "P95": q[4]})
        date_index = pd.DatetimeIndex(target_dates)
        for year, locations in pd.Series(np.arange(len(date_index)), index=date_index).groupby(date_index.year):
            end = int(locations.iloc[-1])
            begin = int(locations.iloc[0]) - 1
            if begin < 0:
                begin = 0
            span = (target_dates[end] - target_dates[begin]).days
            if span < 330:  # partial opening or closing calendar year, not an annual return
                continue
            returns_year = wealth[:, end] / wealth[:, begin] - 1
            for i, value in enumerate(returns_year):
                annual.append({"Portfolio": title, "Path": i, "Year": int(year), "Return": float(value)})
    return PortfolioAnalysis(target_dates, sampled, pd.DataFrame(historical), pd.DataFrame(paths),
                             pd.DataFrame(outcomes), pd.DataFrame(annual), pd.DataFrame(summaries))


def target_observations(plan: dict) -> tuple:
    start, end, _ = horizon(plan)
    weekdays = tuple(pd.bdate_range(start, end).date)
    return weekdays if weekdays[0] == start else (start, *weekdays)
