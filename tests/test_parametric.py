from datetime import date, timedelta

import numpy as np
import pytest

from financial_simulations.markets.parametric import LognormalModel, fit_lognormal
from financial_simulations.markets.path import MarketPath


def test_log_calibration_and_singular_covariance():
    logs = np.array([[0.01, 0.02], [-0.02, -0.04], [0.03, 0.06]])
    dates = tuple(date(2020, 1, 1) + timedelta(days=i) for i in range(4))
    model = fit_lognormal(MarketPath(dates, ("a", "b"), np.expm1(logs)))
    np.testing.assert_allclose(model.mean, logs.mean(axis=0))
    np.testing.assert_allclose(model.covariance, np.cov(logs, rowvar=False, ddof=1), atol=1e-18)
    sampled = np.log1p(model.draw(100, seed=7, path_id=0))
    np.testing.assert_allclose(sampled[:, 1], 2 * sampled[:, 0], atol=2e-9)
    assert not model.mean.flags.writeable and not model.factor.flags.writeable
    one = fit_lognormal(MarketPath(dates, ("a",), np.expm1(logs[:, :1])))
    assert one.covariance.shape == (1, 1)


def test_annual_mean_conventions_and_deterministic_compounding():
    model = LognormalModel(("a",), [0], [[0.04 / 252]])
    geometric = model.daily_mean("geometric_growth", [0.08])
    expected = model.daily_mean("expected_compounded_return", [0.08])
    arithmetic = model.daily_mean("annualised_daily_arithmetic", [0.08])
    assert np.expm1(252 * geometric[0]) == pytest.approx(0.08)
    assert np.expm1(252 * (expected[0] + model.covariance[0, 0] / 2)) == pytest.approx(0.08)
    assert 252 * model.simple_moments(arithmetic)[0][0] == pytest.approx(0.08)
    zero = LognormalModel(("a",), geometric, [[0]])
    path = zero.draw(252, seed=1, path_id=0)
    assert np.prod(1 + path) == pytest.approx(1.08)


def test_simulated_log_and_simple_moments_and_common_innovations():
    mean = np.array([0.0002, -0.0001])
    covariance = np.array([[0.0004, 0.00012], [0.00012, 0.0001]])
    model = LognormalModel(("a", "b"), mean, covariance)
    draws = model.draw(200000, seed=1729, path_id=0)
    logs = np.log1p(draws)
    np.testing.assert_allclose(logs.mean(axis=0), mean, atol=0.00012)
    np.testing.assert_allclose(np.cov(logs, rowvar=False), covariance, rtol=0.025)
    simple_mean, simple_cov = model.simple_moments()
    np.testing.assert_allclose(draws.mean(axis=0), simple_mean, atol=0.00012)
    np.testing.assert_allclose(np.cov(draws, rowvar=False), simple_cov, rtol=0.025)
    shifted = model.draw(200000, seed=1729, path_id=0, mean=mean + 0.001)
    np.testing.assert_allclose(np.log1p(shifted) - logs, 0.001, atol=1e-16)
    np.testing.assert_array_equal(draws, model.draw(200000, seed=1729, path_id=0))
    assert not np.array_equal(draws, model.draw(200000, seed=2718, path_id=0))


def test_parametric_error_boundaries():
    for covariance in ([[1, 2], [2, 1]], [[1, 0.1], [0, 1]], [[1, np.nan], [np.nan, 1]]):
        with pytest.raises(ValueError):
            LognormalModel(("a", "b"), [0, 0], covariance)
    with pytest.raises(ValueError):
        LognormalModel(("a",), [0], [[1]], True)
    model = LognormalModel(("a",), [0], [[0]])
    for value in (1000, -1000):
        with pytest.raises(ValueError, match="not clipped"):
            model.draw(1, seed=0, path_id=0, mean=[value])
    for convention, values in (("historical", [0]), ("geometric_growth", [-1]),
                               ("annualised_daily_arithmetic", [-252]), ("other", [0])):
        with pytest.raises(ValueError):
            model.daily_mean(convention, values)
    dates = (date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3))
    with pytest.raises(ValueError, match="above -100%"):
        fit_lognormal(MarketPath(dates, ("a",), np.array([[0.01], [-1]])))
