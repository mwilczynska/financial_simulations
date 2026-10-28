from datetime import date

import numpy as np
import pytest

from financial_simulations.markets.path import MarketPath
from financial_simulations.portfolios.engine import CashFlow, simulate_portfolio
from financial_simulations.portfolios.spec import PortfolioSpec


def path(dates, returns, assets=("GLSTOCK",)):
    return MarketPath(tuple(date.fromisoformat(d) for d in dates), assets, returns)


def test_compounding_daily_observations_and_calendar_marks():
    market = path(["2020-01-02", "2020-01-03", "2020-01-06"], [[0.1], [-0.1]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100)
    np.testing.assert_allclose(result.daily["value"], [100, 110, 110, 110, 99])
    assert result.daily["is_market_observation"].sum() == 3
    assert result.daily["performance_return"].count() == 2
    np.testing.assert_allclose(market.returns[:, 0], [0.1, -0.1])


@pytest.mark.parametrize("timing, expected", [("after_return", 108), ("before_return", 108.9)])
def test_hand_calculated_cash_flow_timing(timing, expected):
    market = path(["2020-01-02", "2020-01-03", "2020-01-06"], [[0.1], [-0.1]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100,
                                [CashFlow(date(2020, 1, 3), 10, timing)])
    assert result.daily["value"].iloc[-1] == pytest.approx(expected)


@pytest.mark.parametrize("policy, expected", [("annual", 110.25), ("buy_and_hold", 110)])
def test_new_year_rebalance_before_first_return_and_holdings_drift(policy, expected):
    market = path(["2020-12-30", "2020-12-31", "2021-01-04"], [[0.1, 0], [0, 0.1]],
                  ("GLSTOCK", "GLBOND"))
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 0.5, "GLBOND": 0.5}, policy), 100)
    assert result.daily.loc["2020-12-31", "holding_GLSTOCK"] == pytest.approx(55)
    assert result.daily["value"].iloc[-1] == pytest.approx(expected)
    assert result.daily["rebalanced"].sum() == (1 if policy == "annual" else 0)


def test_same_year_is_not_implicitly_rebalanced_daily():
    market = path(["2020-01-02", "2020-01-03", "2020-01-06"], [[0.1, 0], [0, 0.1]],
                  ("GLSTOCK", "GLBOND"))
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 0.5, "GLBOND": 0.5}), 100)
    assert result.daily["value"].iloc[-1] == pytest.approx(110)
    assert not result.daily["rebalanced"].any()


def test_weekend_deposit_is_cash_until_next_observation_close():
    market = path(["2020-01-03", "2020-01-06"], [[0.1]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100,
                                [CashFlow(date(2020, 1, 4), 10)])
    assert result.daily.loc["2020-01-04", "cash"] == 10
    assert result.daily.loc["2020-01-05", "value"] == 110
    assert result.daily.loc["2020-01-06", "value"] == pytest.approx(120)
    assert result.daily.loc["2020-01-06", "cash"] == 0


def test_closed_market_withdrawal_records_shortfall_without_future_sale():
    market = path(["2020-01-03", "2020-01-06"], [[0]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100,
                                [CashFlow(date(2020, 1, 4), -15)], initial_cash=10)
    assert result.daily.loc["2020-01-04", "withdrawals_paid"] == 10
    assert result.daily.loc["2020-01-04", "shortfall"] == 5
    assert result.daily["value"].iloc[-1] == 100
    assert result.daily["withdrawals_paid"].sum() == 10


def test_initial_cash_is_a_retained_reserve_not_automatically_invested():
    market = path(["2020-01-02", "2020-01-03", "2020-01-06"], [[0.1], [0.1]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100, initial_cash=20)
    np.testing.assert_allclose(result.daily["cash"], 20)
    assert result.daily["value"].iloc[-1] == pytest.approx(141)


def test_weekend_cash_sale_uses_reserve_first_and_invests_only_pending_deposit():
    market = path(["2020-01-03", "2020-01-06"], [[0]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100,
                                [CashFlow(date(2020, 1, 4), 30), CashFlow(date(2020, 1, 5), -10)],
                                initial_cash=20)
    assert result.daily["cash"].iloc[-1] == 10
    assert result.daily["invested_value"].iloc[-1] == 130


def test_insufficient_trading_day_assets_are_depleted_without_borrowing():
    market = path(["2020-01-02", "2020-01-03", "2020-01-06"], [[0.1], [0.2]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100,
                                [CashFlow(date(2020, 1, 3), -150)])
    assert result.daily.loc["2020-01-03", "withdrawals_paid"] == pytest.approx(110)
    assert result.daily.loc["2020-01-03", "shortfall"] == pytest.approx(40)
    assert result.daily["value"].iloc[-1] == 0


def test_deposits_buy_target_mix_without_rebalancing_existing_holdings():
    market = path(["2020-01-02", "2020-01-03", "2020-01-06"], [[1, 0], [0, 0]],
                  ("GLSTOCK", "GLBOND"))
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 0.5, "GLBOND": 0.5}), 100,
                                [CashFlow(date(2020, 1, 3), 20)])
    assert result.daily.loc["2020-01-03", "holding_GLSTOCK"] == 110
    assert result.daily.loc["2020-01-03", "holding_GLBOND"] == 60


def test_same_date_same_phase_order_is_preserved():
    market = path(["2020-01-03", "2020-01-06"], [[0]])
    spec = PortfolioSpec({"GLSTOCK": 1})
    deposit, withdrawal = CashFlow(date(2020, 1, 4), 20), CashFlow(date(2020, 1, 4), -20)
    funded = simulate_portfolio(market, spec, 100, [deposit, withdrawal])
    unfunded = simulate_portfolio(market, spec, 100, [withdrawal, deposit])
    assert funded.daily["shortfall"].sum() == 0
    assert unfunded.daily["shortfall"].sum() == 20


def test_zero_return_accounting_and_complete_loss_then_new_deposit():
    market = path(["2020-01-02", "2020-01-03", "2020-01-06"], [[0], [0]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100,
                                [CashFlow(date(2020, 1, 3), 20), CashFlow(date(2020, 1, 6), -30)])
    assert result.daily["value"].iloc[-1] == 90
    np.testing.assert_allclose(result.daily["value"], result.daily["opening_value"]
                               + result.daily["market_pnl"] + result.daily["net_external_flow"])
    loss = path(["2020-01-02", "2020-01-03", "2020-01-06"], [[-1], [0.5]])
    result = simulate_portfolio(loss, PortfolioSpec({"GLSTOCK": 1}), 100,
                                [CashFlow(date(2020, 1, 6), 10)])
    assert result.daily["value"].iloc[-1] == 10


def test_single_opening_mark_and_daily_reset_toy_example():
    opening = path(["2020-01-02"], np.empty((0, 1)))
    assert simulate_portfolio(opening, PortfolioSpec({"GLSTOCK": 1}), 100).daily["value"].iloc[0] == 100
    levered = path(["2020-01-02", "2020-01-03", "2020-01-06"], [[0.3], [-0.3]], ("USLCAP3X",))
    assert simulate_portfolio(levered, PortfolioSpec({"USLCAP3X": 1}), 100).daily["value"].iloc[-1] == pytest.approx(91)


def test_account_validation():
    market = path(["2020-01-02", "2020-01-03"], [[0]])
    with pytest.raises(ValueError, match="outside"):
        simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100, [CashFlow(date(2020, 1, 4), 10)])
    with pytest.raises(ValueError, match="nonnegative"):
        simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), -1)
    with pytest.raises(ValueError, match="match"):
        simulate_portfolio(market, PortfolioSpec({"GLBOND": 1}), 100)
    with pytest.raises(ValueError, match="timing"):
        CashFlow(date(2020, 1, 2), 10, "unknown")
