from datetime import date

import numpy as np
import pandas as pd
import pytest

from financial_simulations.markets.path import MarketPath
from financial_simulations.markets.resampling import (Sampler, complete_window_count, historical_draw,
                                                      sample_indices, sampled_path)
from financial_simulations.portfolios.batch import compound_paths
from financial_simulations.portfolios.engine import simulate_portfolio
from financial_simulations.portfolios.spec import PortfolioSpec


def test_complete_replay_never_stitches_or_uses_partial_windows():
    assert complete_window_count(5, 3) == 3
    assert complete_window_count(5, 6) == 0
    assert complete_window_count(0, 1) == 0
    np.testing.assert_array_equal(historical_draw(5, 3, 2).indices, [2, 3, 4])
    with pytest.raises(ValueError, match="complete"):
        historical_draw(5, 3, 3)


@pytest.mark.parametrize("sampler", [Sampler("independent"), Sampler("moving_block", 4), Sampler("stationary", 4)])
def test_joint_rows_and_rng_streams_survive_order_and_batch_changes(sampler):
    source = MarketPath(tuple(date(2020, 1, i) for i in range(1, 11)), ("GLSTOCK", "GLBOND"),
                         np.column_stack([np.arange(9) / 100, -np.arange(9) / 100]))
    target = tuple(date(2021, 1, i) for i in range(1, 10))
    draws = {i: sample_indices(9, 8, sampler, seed=7, path_id=i) for i in (2, 0, 1)}
    for i in range(3):
        repeated = sample_indices(9, 8, sampler, seed=7, path_id=i)
        np.testing.assert_array_equal(repeated.indices, draws[i].indices)
        market = sampled_path(source, repeated, target)
        np.testing.assert_array_equal(market.returns, source.returns[repeated.indices])
        np.testing.assert_array_equal(market.returns[:, 0], -market.returns[:, 1])
        assert not repeated.indices.flags.writeable
    assert not np.array_equal(draws[0].indices, draws[1].indices)


def test_moving_blocks_are_contiguous_nonwrapping_and_final_block_is_truncated():
    draw = sample_indices(19, 103, Sampler("moving_block", 7), seed=1729, path_id=0)
    assert np.flatnonzero(draw.block_start).tolist() == list(range(0, 103, 7))
    assert not draw.wrapped.any()
    for start in range(0, 103, 7):
        assert np.all(np.diff(draw.indices[start:start + 7]) == 1)
    with pytest.raises(ValueError, match="fit"):
        sample_indices(3, 5, Sampler("moving_block", 4), seed=0, path_id=0)


def test_stationary_blocks_geometric_restarts_and_circular_wraps():
    draw = sample_indices(7, 50000, Sampler("stationary", 8), seed=123, path_id=4)
    continuation = ~draw.block_start[1:]
    np.testing.assert_array_equal(draw.indices[1:][continuation], (draw.indices[:-1][continuation] + 1) % 7)
    assert draw.wrapped.any()
    assert not np.any(draw.wrapped & draw.block_start)
    assert abs(draw.block_start.mean() - 1 / 8) < 0.01
    assert np.max(np.abs(np.bincount(draw.indices, minlength=7) / len(draw.indices) - 1 / 7)) < 0.015


def test_length_one_stationary_and_independent_are_uniform_joint_draws():
    for sampler in (Sampler("stationary", 1), Sampler("independent")):
        draw = sample_indices(5, 30000, sampler, seed=42, path_id=0)
        assert draw.block_start.all()
        assert not draw.wrapped.any()
        assert np.max(np.abs(np.bincount(draw.indices) / len(draw.indices) - 0.2)) < 0.012


@pytest.mark.parametrize("policy", ["annual", "buy_and_hold"])
@pytest.mark.parametrize("cash", [0.0, 20.0])
def test_batch_accounting_matches_full_ledger_across_calendar_boundary(policy, cash):
    dates = (date(2020, 12, 30), date(2020, 12, 31), date(2021, 1, 4), date(2021, 1, 5))
    returns = np.array([[[0.1, 0], [0, 0.1], [-0.1, 0.2]], [[-1, 0.1], [0.2, -0.1], [0, -1]]])
    spec = PortfolioSpec({"GLSTOCK": 0.5, "GLBOND": 0.5}, policy)
    wealth = compound_paths(returns, dates, spec, 100, initial_cash=cash)
    for i, matrix in enumerate(returns):
        path = MarketPath(dates, spec.assets, matrix)
        result = simulate_portfolio(path, spec, 100, initial_cash=cash)
        np.testing.assert_allclose(wealth[i], result.daily.loc[pd.to_datetime(dates), "value"], rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize("method,length", [("unknown", None), ("independent", 2), ("stationary", 0), ("moving_block", True)])
def test_bad_sampler_configuration_fails(method, length):
    with pytest.raises(ValueError):
        Sampler(method, length)


def test_bad_horizons_seeds_dates_and_returns_fail():
    for kwargs in ({"seed": -1, "path_id": 0}, {"seed": 0, "path_id": True}):
        with pytest.raises(ValueError):
            sample_indices(10, 5, Sampler("independent"), **kwargs)
    spec = PortfolioSpec({"GLSTOCK": 1})
    with pytest.raises(ValueError):
        compound_paths(np.array([[[-1.1]]]), (date(2020, 1, 1), date(2020, 1, 2)), spec, 100)
    with pytest.raises(ValueError):
        complete_window_count(5, 0)
