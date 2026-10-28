"""GARCH(1,1) filtered historical simulation: clustered volatility, empirical joint shocks."""

from dataclasses import dataclass

import numpy as np

from financial_simulations.markets.path import MarketPath
from financial_simulations.markets.resampling import integer


INITIAL_VARIANCE = ("unconditional", "last_fitted")
MEAN_CONVENTIONS = ("historical", "geometric_growth")


def _negative_loglik(errors, variance, alpha, beta):
    """Gaussian quasi-likelihood up to constants, vectorised over parameter pairs."""
    omega = variance * (1.0 - alpha - beta)
    h = np.full(alpha.shape, variance)
    total = np.zeros(alpha.shape)
    for e in errors:
        total += np.log(h) + e * e / h
        h = omega + alpha * e * e + beta * h
    return 0.5 * total


def _grid(alpha, beta, cap):
    a, b = np.meshgrid(alpha, beta, indexing="ij")
    keep = (a >= 0) & (b >= 0) & (a + b <= cap)
    return a[keep], b[keep]


def fit_variance_targeted_garch(errors, cap=0.999):
    """Deterministic coarse-to-fine grid QML with variance targeting.

    omega = s^2 (1 - alpha - beta), with s^2 the sample variance (n - 1). The
    first conditional variance is s^2. Grids: 0.01, then 0.001 and 0.0001 steps
    around the incumbent; alpha <= 0.5 and alpha + beta <= cap.
    """
    errors = np.asarray(errors, dtype=float)
    if errors.ndim != 1 or len(errors) < 3 or not np.isfinite(errors).all():
        raise ValueError("GARCH fitting requires at least three finite demeaned log returns.")
    if not 0 < cap < 1:
        raise ValueError("Persistence cap must lie strictly between zero and one.")
    variance = float(np.var(errors, ddof=1))
    if variance <= 0:
        raise ValueError("GARCH fitting requires positive sample variance.")
    alpha, beta = _grid(np.arange(0, 0.5001, 0.01), np.arange(0, 1.0, 0.01), cap)
    for step in (None, 0.001, 0.0001):
        if step is not None:
            offsets = np.arange(-10, 11) * step
            alpha, beta = _grid(best[0] + offsets, best[1] + offsets, cap)
            keep = alpha <= 0.5
            alpha, beta = alpha[keep], beta[keep]
        loss = _negative_loglik(errors, variance, alpha, beta)
        i = int(np.argmin(loss))
        best = (float(alpha[i]), float(beta[i]), float(loss[i]))
    return {"alpha": round(best[0], 6), "beta": round(best[1], 6), "variance": variance,
            "negative_quasi_loglik": best[2],
            "at_bound": bool(best[0] >= 0.5 - 1e-12 or best[0] + best[1] >= cap - 1e-12 or best[0] <= 1e-12)}


def conditional_variances(errors, variance, alpha, beta):
    """h_1 = s^2 through h_{n+1}, the variance for the first unobserved step."""
    h = np.empty(len(errors) + 1)
    h[0] = variance
    omega = variance * (1 - alpha - beta)
    for t, e in enumerate(errors):
        h[t + 1] = omega + alpha * e * e + beta * h[t]
    return h


@dataclass(frozen=True)
class GarchFHSModel:
    """Per-asset GARCH(1,1) volatility with jointly resampled standardised residual rows.

    Moments are per observation in natural-log return units. Shocks are rows of
    empirical residuals, recentred and rescaled per asset to mean 0 and
    variance 1, so cross-asset dependence is the residuals' and support is
    bounded by the observed sample. There is no volatility spillover.
    """

    assets: tuple[str, ...]
    mean: np.ndarray
    variance: np.ndarray
    alpha: np.ndarray
    beta: np.ndarray
    residuals: np.ndarray
    last_variance: np.ndarray
    initial_variance: str
    observations_per_year: int
    fit: tuple[dict, ...]

    def __post_init__(self):
        if self.initial_variance not in INITIAL_VARIANCE:
            raise ValueError("Initial variance must be unconditional or last_fitted.")
        for array in (self.mean, self.variance, self.alpha, self.beta, self.residuals, self.last_variance):
            array.setflags(write=False)

    def daily_mean(self, convention="historical", annual_returns=None):
        if convention not in MEAN_CONVENTIONS:
            raise ValueError("GARCH-FHS supports historical and geometric_growth means only; "
                             "its exponential moments have no closed form.")
        if convention == "historical":
            if annual_returns is not None:
                raise ValueError("Historical means do not take annual return overrides.")
            return self.mean.copy()
        annual = np.array(annual_returns, dtype=float)
        if annual.shape != self.mean.shape or not np.isfinite(annual).all() or (annual <= -1).any():
            raise ValueError("Supply a finite annual growth assumption above -100% for every model asset.")
        return np.log1p(annual) / self.observations_per_year

    def draw_batch(self, horizon, *, seed, path_ids, mean=None):
        """Simple returns (paths, horizon, assets); stream [seed, 5, horizon, path_id]."""
        horizon, seed = integer(horizon, "horizon"), integer(seed, "seed", 0)
        path_ids = [integer(i, "path_id", 0) for i in path_ids]
        mean = self.mean if mean is None else np.asarray(mean, dtype=float)
        if mean.shape != self.mean.shape or not np.isfinite(mean).all() or not path_ids:
            raise ValueError("Supply one finite daily log mean per asset and at least one path.")
        # Deliberately excludes mean/inflation/weights so comparisons share shocks.
        rows = np.stack([np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, 5, horizon, i])))
                         .integers(len(self.residuals), size=horizon) for i in path_ids])
        shocks = self.residuals[rows]
        h = np.broadcast_to(self.variance if self.initial_variance == "unconditional" else self.last_variance,
                            (len(path_ids), len(self.assets))).copy()
        omega = self.variance * (1 - self.alpha - self.beta)
        logs = np.empty(shocks.shape)
        for t in range(horizon):
            innovation = np.sqrt(h) * shocks[:, t]
            logs[:, t] = mean + innovation
            h = omega + self.alpha * innovation * innovation + self.beta * h
        with np.errstate(over="ignore", invalid="ignore"):
            returns = np.expm1(logs)
        if not np.isfinite(returns).all() or (returns <= -1).any():
            raise ValueError("Generated gross returns exceed numeric range; returns were not clipped.")
        return returns

    def manifest(self):
        return {"model": "garch11_variance_targeted_fhs_v1", "assets": self.assets,
                "observations_per_year": self.observations_per_year, "initial_variance": self.initial_variance,
                "fitted_daily_log_mean": self.mean.tolist(), "unconditional_daily_log_variance": self.variance.tolist(),
                "alpha": self.alpha.tolist(), "beta": self.beta.tolist(),
                "persistence": (self.alpha + self.beta).tolist(),
                "last_fitted_daily_log_variance": self.last_variance.tolist(),
                "residual_rows": len(self.residuals),
                "standardised_residual_correlation": np.corrcoef(self.residuals, rowvar=False).tolist()
                if len(self.assets) > 1 else [[1.0]],
                "fit": list(self.fit)}


def fit_garch_fhs(path: MarketPath, observations_per_year=252, *, initial_variance="unconditional",
                  persistence_cap=0.999) -> GarchFHSModel:
    if len(path.returns) < 3 or (path.returns <= -1).any():
        raise ValueError("GARCH-FHS calibration requires at least three observations and returns above -100%.")
    logs = np.log1p(path.returns)
    mean = logs.mean(axis=0)
    errors = logs - mean
    fits, residuals, last = [], [], []
    for i, asset in enumerate(path.assets):
        fit = fit_variance_targeted_garch(errors[:, i], persistence_cap)
        h = conditional_variances(errors[:, i], fit["variance"], fit["alpha"], fit["beta"])
        z = errors[:, i] / np.sqrt(h[:-1])
        if not z.std() > 0:
            raise ValueError(f"{asset}: standardised residuals have no variation.")
        fits.append({"asset": asset, **fit, "raw_residual_mean": float(z.mean()), "raw_residual_std": float(z.std())})
        residuals.append((z - z.mean()) / z.std())
        last.append(h[-1])
    column = lambda key: np.array([f[key] for f in fits])
    return GarchFHSModel(path.assets, mean, column("variance"), column("alpha"), column("beta"),
                         np.column_stack(residuals), np.array(last), initial_variance,
                         integer(observations_per_year, "observations_per_year"), tuple(fits))


@dataclass(frozen=True)
class VolatilitySettings:
    model: str
    initial_variance: str
    persistence_cap: float

    def fit(self, path: MarketPath, observations_per_year: int) -> GarchFHSModel:
        return fit_garch_fhs(path, observations_per_year, initial_variance=self.initial_variance,
                             persistence_cap=self.persistence_cap)

    def manifest(self):
        return {"model": self.model, "initial_variance": self.initial_variance,
                "persistence_cap": self.persistence_cap,
                "rng": "PCG64/SeedSequence v1: [seed, 5, horizon, path_id]; residual rows shared across means"}


def load_volatility(options) -> VolatilitySettings:
    from financial_simulations.scenario import _keys

    _keys(options, {"model", "initial_variance", "persistence_cap"}, {"model"}, "volatility")
    if options["model"] != "garch_fhs":
        raise ValueError("The supported volatility model is garch_fhs.")
    initial = options.get("initial_variance", "unconditional")
    if initial not in INITIAL_VARIANCE:
        raise ValueError("Initial variance must be unconditional or last_fitted.")
    cap = options.get("persistence_cap", 0.999)
    if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not 0 < cap < 1:
        raise ValueError("Persistence cap must lie strictly between zero and one.")
    return VolatilitySettings("garch_fhs", initial, float(cap))
