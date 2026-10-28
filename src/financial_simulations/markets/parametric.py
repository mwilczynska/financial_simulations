"""Correlated daily Gaussian log returns with explicit annual mean conventions."""

from dataclasses import dataclass

import numpy as np

from financial_simulations.markets.path import MarketPath
from financial_simulations.markets.resampling import integer


def _finite(values, name):
    array = np.array(values, dtype=float, copy=True)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite.")
    return array


@dataclass(frozen=True)
class LognormalModel:
    """Moments are per observation; covariance is in natural-log return units."""

    assets: tuple[str, ...]
    mean: np.ndarray
    covariance: np.ndarray
    observations_per_year: int = 252

    def __post_init__(self):
        assets = tuple(self.assets)
        mean, covariance = _finite(self.mean, "Log means"), _finite(self.covariance, "Log covariance")
        size = len(assets)
        if not size or len(set(assets)) != size or mean.shape != (size,) or covariance.shape != (size, size):
            raise ValueError("Distinct assets, one mean per asset and a square covariance are required.")
        integer(self.observations_per_year, "observations_per_year")
        scale = max(float(np.max(np.abs(covariance))), np.finfo(float).tiny)
        tolerance = 100 * size * np.finfo(float).eps * scale
        if np.max(np.abs(covariance - covariance.T)) > tolerance:
            raise ValueError("Log covariance must be symmetric.")
        covariance = (covariance + covariance.T) / 2
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        if eigenvalues.min() < -tolerance:
            raise ValueError("Log covariance must be positive semidefinite.")
        correction = float(max(0, -eigenvalues.min()))
        factor = eigenvectors * np.sqrt(np.maximum(eigenvalues, 0))
        effective_covariance = factor @ factor.T
        for array in (mean, effective_covariance, factor):
            array.setflags(write=False)
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "mean", mean)
        object.__setattr__(self, "covariance", effective_covariance)
        object.__setattr__(self, "factor", factor)
        object.__setattr__(self, "eigenvalue_correction", correction)

    def daily_mean(self, convention="historical", annual_returns=None):
        if convention == "historical":
            if annual_returns is not None:
                raise ValueError("Historical means do not take annual return overrides.")
            return self.mean.copy()
        annual = _finite(annual_returns, "Annual return assumptions")
        if annual.shape != self.mean.shape:
            raise ValueError("Supply an annual return assumption for every model asset.")
        basis = self.observations_per_year
        variance = np.diag(self.covariance)
        if convention in {"geometric_growth", "expected_compounded_return"}:
            if (annual <= -1).any():
                raise ValueError("Annual growth must exceed -100%.")
            mean = np.log1p(annual) / basis
            return mean if convention == "geometric_growth" else mean - variance / 2
        if convention == "annualised_daily_arithmetic":
            if (annual <= -basis).any():
                raise ValueError("Annualised daily arithmetic mean divided by the basis must exceed -100%.")
            return np.log1p(annual / basis) - variance / 2
        raise ValueError(f"Unknown mean convention: {convention}")

    def simple_moments(self, mean=None):
        mean = self.mean if mean is None else _finite(mean, "Daily log means")
        if mean.shape != self.mean.shape:
            raise ValueError("Supply one daily log mean per asset.")
        with np.errstate(over="raise", invalid="raise"):
            try:
                gross = np.exp(mean + np.diag(self.covariance) / 2)
                return gross - 1, np.outer(gross, gross) * np.expm1(self.covariance)
            except FloatingPointError as error:
                raise ValueError("Implied simple-return moments exceed numeric range.") from error

    def draw(self, horizon, *, seed, path_id, mean=None):
        horizon = integer(horizon, "horizon")
        seed, path_id = integer(seed, "seed", 0), integer(path_id, "path_id", 0)
        mean = self.mean if mean is None else _finite(mean, "Daily log means")
        if mean.shape != self.mean.shape:
            raise ValueError("Supply one daily log mean per asset.")
        # Deliberately excludes mean/inflation/weights so assumption comparisons share innovations.
        rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, 4, horizon, path_id])))
        log_returns = mean + rng.standard_normal((horizon, len(self.assets))) @ self.factor.T
        with np.errstate(over="ignore", invalid="ignore"):
            returns = np.expm1(log_returns)
        if not np.isfinite(returns).all() or (returns <= -1).any():
            raise ValueError("Generated gross returns exceed numeric range; returns were not clipped.")
        return returns

    def manifest(self):
        simple_mean, simple_covariance = self.simple_moments()
        return {"assets": self.assets, "observations_per_year": self.observations_per_year,
                "fitted_daily_log_mean": self.mean.tolist(), "daily_log_covariance": self.covariance.tolist(),
                "sampling_factor": self.factor.tolist(), "negative_eigenvalue_correction": self.eigenvalue_correction,
                "implied_daily_simple_mean": simple_mean.tolist(),
                "implied_daily_simple_covariance": simple_covariance.tolist(), "covariance_ddof": 1}


def fit_lognormal(path: MarketPath, observations_per_year=252) -> LognormalModel:
    if len(path.returns) < 2 or (path.returns <= -1).any():
        raise ValueError("Log-return calibration requires at least two observations and returns above -100%.")
    logs = np.log1p(path.returns)
    return LognormalModel(path.assets, logs.mean(axis=0), np.atleast_2d(np.cov(logs, rowvar=False, ddof=1)),
                          observations_per_year)
