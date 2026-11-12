from datetime import date

import numpy as np
import pandas as pd
import pytest

from financial_simulations.retirement.path_markets import ONE_PORTFOLIO, compound, group_markets, path_markets, real_growth
from financial_simulations.retirement.plan import build_inputs, future_observations, normalize_plan
from financial_simulations.retirement.analysis import analyse_portfolios
from financial_simulations.data.plan_markets import load_plan_markets
from test_plan import quick_plan


def test_compound_rebalances_on_the_first_observation_of_a_calendar_year():
    dates = (date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 4), date(2027, 1, 5))
    returns = np.array([[1.0, 0.0], [0.0, 0.0], [0.5, 0.0]])
    weights = np.array([0.5, 0.5])
    # Drifting: the first holding doubles to 1.0, then rises by half: 1.5 + 0.5.
    assert compound(returns, dates, weights, False) == pytest.approx([1.0, 1.5, 1.5, 2.0])
    # Rebalanced before the 4 January return: 0.75 each, so the half rise applies to 0.75.
    assert compound(returns, dates, weights, True) == pytest.approx([1.0, 1.5, 1.5, 1.875])


def test_path_markets_matches_the_portfolio_analysis_for_the_same_path(monkeypatch, processed_fixture):
    monkeypatch.setenv("FINANCIAL_DATASETS_PROCESSED", str(processed_fixture))
    plan = normalize_plan(quick_plan())
    market = load_plan_markets(plan["assets"])
    portfolios = analyse_portfolios(plan, market, future_observations(plan, market))
    path = 3
    growth, stats = path_markets(plan, market, portfolios, path)
    assert list(growth.index) == [pd.Timestamp(d) for d in portfolios.dates] and (growth.iloc[0] == 1.0).all()
    by_series = stats.set_index("Series")
    tickers = list(market.path.assets)
    assert list(by_series.index[-len(tickers):]) == tickers and (by_series.loc[tickers, "Kind"] == "Ticker").all()
    # Each ticker is its own drawn daily returns compounded.
    drawn = portfolios.returns_for(market, path)
    assert growth[tickers[0]].iloc[-1] == pytest.approx(np.prod(1 + drawn[:, 0]))
    # The portfolios agree with the analysis that produced the plan's portfolio outcomes.
    outcomes = portfolios.outcomes.loc[portfolios.outcomes["Path"] == path].set_index("Portfolio")
    names = [n for n in by_series.index if by_series.loc[n, "Kind"] == "Portfolio"]
    for name in names:
        expected = outcomes.loc["Outside super" if name in (ONE_PORTFOLIO, "Outside super portfolio") else "Inside super"]
        assert by_series.loc[name, "CAGR after inflation"] == pytest.approx(expected["Annualised growth"])
        assert by_series.loc[name, "Volatility"] == pytest.approx(expected["Annualised volatility"])
        assert by_series.loc[name, "Worst drawdown"] == pytest.approx(expected["Maximum drawdown"])
        assert by_series.loc[name, "Growth of $1 after inflation"] == pytest.approx(expected["Terminal growth of 100"] / 100)
    cpi = plan["assumptions"]["cpi_annual"]
    real = real_growth(growth, cpi)
    assert real[names[0]].iloc[-1] == pytest.approx(by_series.loc[names[0], "Growth of $1 after inflation"])
    assert (by_series["CAGR"] > by_series["CAGR after inflation"]).all() == (cpi > 0)


def test_group_markets_of_one_path_is_that_path_and_medians_are_per_series(monkeypatch, processed_fixture):
    monkeypatch.setenv("FINANCIAL_DATASETS_PROCESSED", str(processed_fixture))
    plan = normalize_plan(quick_plan())
    market = load_plan_markets(plan["assets"])
    portfolios = analyse_portfolios(plan, market, future_observations(plan, market))
    growth, stats = path_markets(plan, market, portfolios, 3)
    months, alone = group_markets(plan, market, portfolios, [3])
    # A group of one path: the same statistics, and the path's own growth at the opening mark and each month end.
    assert list(alone["Series"]) == list(stats["Series"])
    for column in ("CAGR", "CAGR after inflation", "Volatility", "Worst drawdown", "Growth of $1 after inflation"):
        assert alone[column].to_numpy() == pytest.approx(stats[column].to_numpy())
    assert months.index[0] == growth.index[0] and months.index[-1] == growth.index[-1]
    assert months.to_numpy() == pytest.approx(growth.loc[months.index].to_numpy())
    # Several paths: each statistic is the median of the paths' own statistics.
    members = [0, 3, 5]
    _, group = group_markets(plan, market, portfolios, members)
    each = [path_markets(plan, market, portfolios, p)[1] for p in members]
    for column in ("CAGR", "Volatility", "Worst drawdown"):
        assert group[column].to_numpy() == pytest.approx(np.median([s[column].to_numpy() for s in each], axis=0))


def test_identical_portfolios_are_one_series(monkeypatch, processed_fixture):
    monkeypatch.setenv("FINANCIAL_DATASETS_PROCESSED", str(processed_fixture))
    plan = quick_plan()
    plan["super"]["weights"] = dict(plan["outside"]["weights"])
    plan["super"]["rebalance"] = plan["outside"]["rebalance"]
    plan = normalize_plan(plan)
    market = load_plan_markets(plan["assets"])
    portfolios = analyse_portfolios(plan, market, future_observations(plan, market))
    growth, stats = path_markets(plan, market, portfolios, 0)
    assert list(stats.loc[stats["Kind"] == "Portfolio", "Series"]) == [ONE_PORTFOLIO]
    assert list(growth.columns) == [ONE_PORTFOLIO, *market.path.assets]
