"""Portfolio-first daily bootstrap and retirement path summaries for a plan."""

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from financial_simulations.markets.resampling import Sampler, sample_indices
from financial_simulations.retirement.plan import horizon
from financial_simulations.rules.au.superannuation import birthday


PORTFOLIOS = (("Outside super", "outside"), ("Inside super", "super"))
COMBINED = "Combined"
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)


@dataclass(frozen=True)
class PortfolioAnalysis:
    dates: tuple
    indices: np.ndarray
    historical: pd.DataFrame
    paths: pd.DataFrame
    outcomes: pd.DataFrame
    annual_returns: pd.DataFrame
    summary: pd.DataFrame
    historical_annual: pd.DataFrame
    combined_shares: dict
    retirement_start: date

    def returns_for(self, market, path: int) -> np.ndarray:
        """The joint daily source returns drawn for one path (shared by every portfolio)."""
        return market.path.returns[self.indices[path]]


@dataclass(frozen=True)
class _Series:
    snapshots: np.ndarray
    drawdowns: np.ndarray
    terminal: np.ndarray
    volatility: np.ndarray
    max_drawdown: np.ndarray
    longest_underwater_days: np.ndarray


def _simulate(source, indices, dates, accounts, shares, snapshots) -> dict[str, _Series]:
    """Compound each account daily on shared donor rows; summarise without storing every day.

    ``accounts`` maps a name to ``(weights, rebalance)``. With ``rebalance`` the
    positions reset to the weights at pre-return values on the first return
    observation of each calendar year (the Stage 1 and tracker convention);
    otherwise weights drift. ``shares`` maps accounts to opening value shares of
    an unrebalanced combined series, or is empty. ``snapshots`` are positions in
    ``dates`` (0 is the opening mark) at which value and drawdown are recorded.
    """
    count, steps = indices.shape
    ordinals = np.array([d.toordinal() for d in dates])
    names = list(accounts) + ([COMBINED] if shares else [])
    positions = {n: np.broadcast_to(100 * w, (count, len(w))).copy() for n, (w, _) in accounts.items()}
    value = {n: np.full(count, 100.0) for n in names}
    peak = {n: np.full(count, 100.0) for n in names}
    peak_day = {n: np.full(count, ordinals[0]) for n in names}
    worst = {n: np.zeros(count) for n in names}
    underwater = {n: np.zeros(count, dtype=np.int64) for n in names}
    total, squares = {n: np.zeros(count) for n in names}, {n: np.zeros(count) for n in names}
    where = {pos: col for col, pos in enumerate(snapshots)}
    snap = {n: np.empty((count, len(snapshots))) for n in names}
    snap_dd = {n: np.empty((count, len(snapshots))) for n in names}
    if 0 in where:
        for n in names:
            snap[n][:, where[0]] = 100.0
            snap_dd[n][:, where[0]] = 0.0
    for step in range(steps):
        returns = source[indices[:, step]]
        new_year = dates[step + 1].year != dates[step].year
        updated = {}
        for n, (weights, rebalance) in accounts.items():
            if rebalance and new_year:
                positions[n] = positions[n].sum(axis=1, keepdims=True) * weights
            positions[n] *= 1 + returns
            updated[n] = positions[n].sum(axis=1)
        if shares:
            updated[COMBINED] = sum(share * updated[a] for a, share in shares.items())
        day = ordinals[step + 1]
        for n in names:
            new = updated[n]
            daily = new / value[n] - 1
            total[n] += daily
            squares[n] += daily * daily
            value[n] = new
            higher = new >= peak[n]
            peak[n] = np.where(higher, new, peak[n])
            peak_day[n] = np.where(higher, day, peak_day[n])
            drawdown = new / peak[n] - 1
            np.minimum(worst[n], drawdown, out=worst[n])
            np.maximum(underwater[n], day - peak_day[n], out=underwater[n])
            column = where.get(step + 1)
            if column is not None:
                snap[n][:, column] = new
                snap_dd[n][:, column] = drawdown
    result = {}
    for n in names:
        variance = (squares[n] - total[n] ** 2 / steps) / (steps - 1) if steps > 1 else np.zeros(count)
        result[n] = _Series(snap[n], snap_dd[n], value[n], np.sqrt(np.maximum(variance, 0) * 252), worst[n], underwater[n])
    return result


def _month_ends(dates) -> list[int]:
    series = pd.Series(np.arange(len(dates)), index=pd.DatetimeIndex(dates))
    return sorted({0, *series.resample("ME").last().to_numpy(dtype=int).tolist()})


def _calendar_years(dates, snapshots, values) -> list[tuple[int, np.ndarray]]:
    """Calendar-year returns between consecutive year-end snapshots; partial years are skipped."""
    marks = [(dates[0].year - 1, 0, dates[0])]
    for column, pos in enumerate(snapshots):
        if pos and dates[pos].month == 12 and (pos == len(dates) - 1 or dates[pos + 1].year != dates[pos].year):
            marks.append((dates[pos].year, column, dates[pos]))
    years = []
    for (_, before, start), (year, after, end) in zip(marks, marks[1:]):
        if (end - start).days >= 330:  # a partial opening calendar year is not an annual return
            years.append((year, values[:, after] / values[:, before] - 1))
    return years


def sustainable_withdrawal_rates(values: np.ndarray, start_column: int, growth: float) -> np.ndarray:
    """Largest first-year withdrawal (fraction of value at ``start_column``) each path can fund.

    Withdrawals are paid monthly at each later month-end snapshot, one twelfth
    of the annual amount, which steps up by ``growth`` every 12 months. With
    proportional sales the portfolio's growth factors do not depend on the
    withdrawals, so wealth stays nonnegative exactly when
    ``1 >= rate * sum_k (1 + growth) ** (k // 12) / 12 / G_k``; the constraint
    binds at the horizon. Pre-tax and without salary or contributions.
    """
    later = values[:, start_column + 1:] / values[:, [start_column]]
    if later.shape[1] < 12:
        return np.full(len(values), np.nan)
    steps = (1 + growth) ** (np.arange(later.shape[1]) // 12) / 12
    return 1 / (steps / later).sum(axis=1)


def retirement_start(plan: dict) -> date:
    start, _, _ = horizon(plan)
    return max(start, birthday(plan["person"]["date_of_birth"], plan["person"]["retirement_age"]))


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
                                       seed=plan["market"]["seed"], path_id=i).indices for i in range(count)]).astype(np.int32)
    accounts = {title: (np.array([plan[section]["weights"].get(t, 0.0) for t in market.path.assets]),
                        plan[section]["rebalance"] == "annual") for title, section in PORTFOLIOS}
    balances = {"Outside super": plan["outside"]["investment_balance"], "Inside super": plan["super"]["balance"]}
    shares = {a: b / sum(balances.values()) for a, b in balances.items()} if sum(balances.values()) > 0 else {}

    history_dates = tuple(market.path.dates)
    history_marks = _month_ends(history_dates)
    history = _simulate(market.path.returns, np.arange(len(market.path.returns))[None, :], history_dates, accounts, shares,
                        history_marks)
    future_marks = _month_ends(target_dates)
    month_ends = set(future_marks)
    retire = retirement_start(plan)
    retire_pos = int(np.searchsorted(np.array(target_dates), retire, side="right") - 1)
    if retire_pos not in future_marks:
        future_marks = sorted({*future_marks, retire_pos})
    future = _simulate(market.path.returns, indices, target_dates, accounts, shares, future_marks)

    historical, summaries, historical_annual = [], [], []
    hyears = (history_dates[-1] - history_dates[0]).days / 365.25
    for title, series in history.items():
        for column, pos in enumerate(history_marks):
            historical.append({"Date": history_dates[pos], "Portfolio": title, "Growth of 100": float(series.snapshots[0, column]),
                               "Drawdown": float(series.drawdowns[0, column])})
        years = _calendar_years(history_dates, history_marks, series.snapshots)
        returns = np.array([float(r[0]) for _, r in years])
        historical_annual += [{"Portfolio": title, "Year": year, "Return": float(r[0])} for year, r in years]
        summaries.append({"Portfolio": title, "CAGR": float((series.terminal[0] / 100) ** (1 / hyears) - 1),
                          "Volatility": float(series.volatility[0]), "Maximum drawdown": float(series.max_drawdown[0]),
                          "Longest drawdown (years)": float(series.longest_underwater_days[0] / 365.25),
                          "Worst calendar year": float(returns.min()) if len(returns) else np.nan,
                          "Best calendar year": float(returns.max()) if len(returns) else np.nan,
                          "Positive years": float((returns > 0).mean()) if len(returns) else np.nan,
                          "First": history_dates[0], "Last": history_dates[-1]})

    paths, outcomes, annual = [], [], []
    pyears = (target_dates[-1] - target_dates[0]).days / 365.25
    retire_column = future_marks.index(retire_pos)
    for title, series in future.items():
        cagr = np.power(series.terminal / 100, 1 / pyears) - 1
        swr = sustainable_withdrawal_rates(series.snapshots, retire_column, plan["spending"]["annual_growth"])
        for i in range(count):
            outcomes.append({"Portfolio": title, "Path": i, "Terminal growth of 100": float(series.terminal[i]),
                             "Annualised growth": float(cagr[i]), "Annualised volatility": float(series.volatility[i]),
                             "Maximum drawdown": float(series.max_drawdown[i]),
                             "Longest drawdown (years)": float(series.longest_underwater_days[i] / 365.25),
                             "Sustainable withdrawal rate": float(swr[i])})
        for column, pos in enumerate(future_marks):
            if pos not in month_ends:
                continue  # the retirement mark is only for withdrawal rates, not a month end
            q = np.quantile(series.snapshots[:, column], QUANTILES)
            dq = np.quantile(series.drawdowns[:, column], QUANTILES)
            paths.append({"Date": target_dates[pos], "Portfolio": title, "P05": q[0], "P25": q[1], "P50": q[2], "P75": q[3],
                          "P95": q[4], "Drawdown P05": dq[0], "Drawdown P50": dq[2]})
        for year, returns in _calendar_years(target_dates, future_marks, series.snapshots):
            annual += [{"Portfolio": title, "Path": i, "Year": int(year), "Return": float(v)} for i, v in enumerate(returns)]
    return PortfolioAnalysis(target_dates, indices, pd.DataFrame(historical), pd.DataFrame(paths), pd.DataFrame(outcomes),
                             pd.DataFrame(annual), pd.DataFrame(summaries), pd.DataFrame(historical_annual), shares, retire)


def target_observations(plan: dict) -> tuple:
    start, end, _ = horizon(plan)
    weekdays = tuple(pd.bdate_range(start, end).date)
    return weekdays if weekdays[0] == start else (start, *weekdays)
