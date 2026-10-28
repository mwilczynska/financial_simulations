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
    expected_correlation = covariance[0, 1] / np.sqrt(covariance[0, 0] * covariance[1, 1])
    assert np.corrcoef(logs, rowvar=False)[0, 1] == pytest.approx(expected_correlation, abs=0.015)
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


def test_only_roundoff_negative_eigenvalues_are_repaired_and_recorded():
    model = LognormalModel(("a", "b"), [0, 0], [[1, 0], [0, -1e-15]])
    assert model.eigenvalue_correction == pytest.approx(1e-15, abs=1e-20)
    assert np.linalg.eigvalsh(model.covariance).min() >= 0
    assert model.manifest()["negative_eigenvalue_correction"] > 0
    with pytest.raises(ValueError, match="positive semidefinite"):
        LognormalModel(("a", "b"), [0, 0], [[1, 0], [0, -1e-8]])


def test_assumed_price_index_uses_calendar_days_including_weekends():
    from financial_simulations.markets.assumptions import assumed_price_index

    dates = (date(2026, 10, 23), date(2026, 10, 26), date(2027, 10, 23))
    index = assumed_price_index(dates, 0.04)
    np.testing.assert_allclose(index, 1.04 ** (np.array([0, 3, 365]) / 365.25))
    np.testing.assert_array_equal(assumed_price_index(dates, 0), [1, 1, 1])
    assert assumed_price_index(dates, -0.02)[-1] < 1
    for rate in (-1, float("nan"), True):
        with pytest.raises(ValueError):
            assumed_price_index(dates, rate)
    with pytest.raises(ValueError):
        assumed_price_index(dates[::-1], 0.02)


def test_assumptions_validation_and_asset_aliases():
    from financial_simulations.markets.assumptions import load_assumptions

    options = {"observations_per_year": 252, "reference_inflation": 0.02, "trace_assumption": "base"}
    case = {"name": "base", "mean_convention": "geometric_growth", "inflation_annual": 0.02,
            "annual_returns": {"GOLDPM2x": 0.04}, "rationale": "Synthetic example"}
    settings = load_assumptions(options, [case])
    model = LognormalModel(("GOLD2X",), [0], [[0.01]])
    assert settings.assumptions[0].daily_mean(model)[0] == pytest.approx(np.log1p(0.04) / 252)
    for change in ({"annual_returns": {"GOLDPM2x": 0.04, "GOLD2X": 0.04}},
                   {"inflation_annual": -1}, {"rationale": ""}, {"mean_convention": "historical"},
                   {"annual_returns": {"GOLDPM2x": True}}):
        with pytest.raises(ValueError):
            load_assumptions(options, [{**case, **change}])
    with pytest.raises(ValueError, match="exactly"):
        settings.assumptions[0].daily_mean(LognormalModel(("GLBOND",), [0], [[0]]))
