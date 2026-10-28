from datetime import date, timedelta

import numpy as np
import pytest

from financial_simulations.markets.path import MarketPath
from financial_simulations.portfolios.batch import simulate_paths
from financial_simulations.portfolios.engine import CashFlow, simulate_portfolio
from financial_simulations.portfolios.spec import PortfolioSpec


def calendar(rng, count):
    """Observation dates with weekends, random holidays and a year boundary."""
    day, dates = date(2019, 12, 20), []
    while len(dates) < count:
        if day.weekday() < 5 and rng.random() > 0.08:
            dates.append(day)
        day += timedelta(days=1)
    return tuple(dates)


def random_flows(rng, dates, count):
    span = (dates[-1] - dates[0]).days
    flows = []
    for _ in range(count):
        day = dates[0] + timedelta(days=int(rng.integers(span + 1)))
        amount = float(rng.choice([-1, 1]) * rng.uniform(1, 400))
        flows.append(CashFlow(day, amount, str(rng.choice(["before_return", "after_return"]))))
    # Same-day, same-phase order and an oversized withdrawal exercise depletion.
    flows += [CashFlow(dates[3], 50.0), CashFlow(dates[3], -75.0), CashFlow(dates[-2], -1e6, "before_return")]
    return flows


@pytest.mark.parametrize("policy", ["annual", "buy_and_hold"])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_batched_flows_match_full_ledger_on_every_mark_and_calendar_day(policy, seed):
    rng = np.random.default_rng(seed)
    dates = calendar(rng, 60)
    portfolio = PortfolioSpec({"GLSTOCK": 0.5, "GLBOND": 0.3, "GOLDPM": 0.2}, policy)
    returns = rng.normal(0.0, 0.03, size=(7, len(dates) - 1, 3))
    returns[2, 10] = -1.0  # complete loss on one path before later deposits
    flows = random_flows(rng, dates, 25)
    ledger = simulate_paths(returns, dates, portfolio, 1000.0, flows, initial_cash=40.0)
    days, calendar_values = ledger.calendar_values()
    marks = np.array(ledger.dates, dtype="datetime64[D]")
    for path_id in range(len(returns)):
        full = simulate_portfolio(MarketPath(dates, portfolio.assets, returns[path_id]), portfolio,
                                  1000.0, flows, initial_cash=40.0).daily
        assert tuple(full.index.date) == days
        np.testing.assert_allclose(calendar_values[path_id], full["value"], rtol=1e-12, atol=1e-9)
        at_marks = full.loc[marks.astype("datetime64[ns]")]
        np.testing.assert_allclose(ledger.cash[path_id], at_marks["cash"], rtol=1e-12, atol=1e-9)
        np.testing.assert_allclose(ledger.withdrawals_paid[path_id], at_marks["withdrawals_paid"], rtol=1e-12, atol=1e-9)
        np.testing.assert_allclose(ledger.shortfall[path_id], at_marks["shortfall"], rtol=1e-12, atol=1e-9)
        np.testing.assert_array_equal(ledger.rebalanced, at_marks["rebalanced"].to_numpy(dtype=bool))
        np.testing.assert_allclose(ledger.contributions, at_marks["contributions"])
        # Every calendar day without an observation or flow carries the previous mark.
        unmarked = ~full.index.isin(marks.astype("datetime64[ns]"))
        assert not (full.loc[unmarked, ["contributions", "withdrawals_requested"]].to_numpy()).any()
    assert ledger.shortfall[:, ledger.dates.index(dates[-2])].min() > 0


def test_batched_no_flow_paths_need_only_observation_marks():
    dates = (date(2020, 12, 31), date(2021, 1, 4), date(2021, 1, 5))
    portfolio = PortfolioSpec({"GLSTOCK": 0.5, "GLBOND": 0.5})
    returns = np.array([[[0.1, 0.0], [0.0, 0.1]]])
    ledger = simulate_paths(returns, dates, portfolio, 100.0)
    assert ledger.dates == dates
    np.testing.assert_allclose(ledger.value[0], [100.0, 105.0, 110.0])
    assert ledger.rebalanced.tolist() == [False, True, False]


@pytest.mark.parametrize("kwargs, match", [
    ({"returns": np.zeros((0, 2, 1))}, "at least one path"),
    ({"returns": np.full((1, 2, 1), -1.5)}, "at least -100%"),
    ({"flows": [CashFlow(date(2021, 2, 1), 1.0)]}, "outside the actual valuation horizon"),
    ({"flows": [(date(2021, 1, 4), 1.0)]}, "CashFlow objects"),
    ({"initial": -1.0}, "nonnegative"),
])
def test_batched_flow_validation(kwargs, match):
    dates = (date(2021, 1, 4), date(2021, 1, 5), date(2021, 1, 6))
    with pytest.raises(ValueError, match=match):
        simulate_paths(kwargs.get("returns", np.zeros((1, 2, 1))), dates, PortfolioSpec({"GLSTOCK": 1.0}),
                       kwargs.get("initial", 100.0), kwargs.get("flows", ()))
