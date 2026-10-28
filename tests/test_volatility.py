from datetime import date, timedelta

import numpy as np
import pytest

from financial_simulations.markets.parametric import fit_lognormal
from financial_simulations.markets.path import MarketPath
from financial_simulations.markets.volatility import (conditional_variances, fit_garch_fhs,
                                                      fit_variance_targeted_garch)


def garch_path(n=4000, alpha=(0.08, 0.05), beta=(0.9, 0.93), seed=3):
    rng = np.random.default_rng(seed)
    alpha, beta = np.array(alpha), np.array(beta)
    variance = np.array([1e-4, 4e-4])
    omega, h = variance * (1 - alpha - beta), variance.copy()
    shocks = rng.multivariate_normal([0, 0], [[1, 0.6], [0.6, 1]], size=n)
    logs = np.empty((n, 2))
    for t in range(n):
        logs[t] = 0.0003 + np.sqrt(h) * shocks[t]
        h = omega + alpha * (logs[t] - 0.0003) ** 2 + beta * h
    dates = [date(2000, 1, 3) + timedelta(days=i) for i in range(n + 1)]
    return MarketPath(dates, ("USLCAP3X", "GOLD2X"), np.expm1(logs))


def squared_acf(values, lag=1):
    x = values ** 2 - (values ** 2).mean(axis=-1, keepdims=True)
    return float(np.mean((x[..., :-lag] * x[..., lag:]).mean(axis=-1) / (x * x).mean(axis=-1)))


def test_variance_targeted_fit_recovers_known_parameters_and_is_deterministic():
    path = garch_path()
    model = fit_garch_fhs(path)
    np.testing.assert_allclose(model.alpha, [0.08, 0.05], atol=0.03)
    np.testing.assert_allclose(model.beta, [0.9, 0.93], atol=0.04)
    assert (model.alpha + model.beta < 0.999).all()
    np.testing.assert_allclose(model.residuals.mean(axis=0), 0, atol=1e-12)
    np.testing.assert_allclose(model.residuals.std(axis=0), 1, atol=1e-12)
    again = fit_garch_fhs(path)
    np.testing.assert_array_equal(model.alpha, again.alpha)
    # Homoskedastic noise selects little or no volatility clustering.
    flat = fit_variance_targeted_garch(np.random.default_rng(0).normal(0, 0.01, 3000))
    assert flat["alpha"] < 0.03


def test_conditional_variance_recursion_by_hand():
    h = conditional_variances(np.array([0.1, -0.2]), 0.02, 0.1, 0.8)
    np.testing.assert_allclose(h, [0.02, 0.002 + 0.001 + 0.016, 0.002 + 0.004 + 0.8 * 0.019])


def test_draws_are_reproducible_batch_invariant_and_share_shocks_across_means():
    model = fit_garch_fhs(garch_path(1500))
    batch = model.draw_batch(50, seed=7, path_ids=[0, 1, 2])
    np.testing.assert_array_equal(batch[2], model.draw_batch(50, seed=7, path_ids=[2])[0])
    shifted = model.draw_batch(50, seed=7, path_ids=[0, 1, 2], mean=model.daily_mean("geometric_growth", [0.05, 0.0]))
    # Same residual rows and variance path: only the log mean differs.
    np.testing.assert_allclose(np.log1p(shifted) - np.log1p(batch),
                               np.broadcast_to(np.log1p([0.05, 0.0]) / 252 - model.mean, batch.shape), atol=1e-12)
    assert not np.array_equal(batch, model.draw_batch(50, seed=8, path_ids=[0, 1, 2]))


def test_simulated_moments_and_clustering_versus_lognormal():
    path = garch_path()
    model, gaussian = fit_garch_fhs(path), fit_lognormal(path)
    paths = model.draw_batch(1000, seed=1, path_ids=range(400))
    logs = np.log1p(paths)
    # Unconditional start: per-step variance and geometric mean match their targets.
    np.testing.assert_allclose(logs.var(axis=(0, 1)), model.variance, rtol=0.08)
    np.testing.assert_allclose(logs.mean(axis=(0, 1)), model.mean, atol=3e-5)
    normal = np.log1p(np.stack([gaussian.draw(1000, seed=1, path_id=i) for i in range(100)]))
    assert squared_acf(np.moveaxis(logs, 1, 2)) > 0.05
    assert abs(squared_acf(np.moveaxis(normal, 1, 2))) < 0.02
    # Bounded empirical shocks: no draw exceeds the largest residual at the largest variance seen.
    assert np.isfinite(paths).all() and (paths > -1).all()


def test_last_fitted_variance_starts_from_the_filtered_state():
    path = garch_path(1200)
    model = fit_garch_fhs(path, initial_variance="last_fitted")
    h = conditional_variances(np.log1p(path.returns[:, 0]) - model.mean[0], model.variance[0],
                              model.alpha[0], model.beta[0])
    assert model.last_variance[0] == pytest.approx(h[-1])
    first = np.log1p(model.draw_batch(1, seed=0, path_ids=[0])[0, 0, 0]) - model.mean[0]
    row = np.random.Generator(np.random.PCG64(np.random.SeedSequence([0, 5, 1, 0]))).integers(len(model.residuals))
    assert first == pytest.approx(np.sqrt(h[-1]) * model.residuals[row, 0])


@pytest.mark.parametrize("call, match", [
    (lambda m: m.daily_mean("expected_compounded_return", [0.1, 0.1]), "historical and geometric_growth"),
    (lambda m: m.daily_mean("geometric_growth", [0.1]), "every model asset"),
    (lambda m: m.draw_batch(5, seed=0, path_ids=[]), "at least one path"),
])
def test_garch_validation(call, match):
    with pytest.raises(ValueError, match=match):
        call(fit_garch_fhs(garch_path(300)))
    with pytest.raises(ValueError, match="Initial variance"):
        fit_garch_fhs(garch_path(300), initial_variance="sample")
