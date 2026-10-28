"""Calendar-day evaluation, explicit targets and conditional Monte Carlo error."""

from dataclasses import asdict, dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

from financial_simulations.dates import as_date
from financial_simulations.markets.assumptions import assumed_price_index, rate
from financial_simulations.markets.resampling import integer
from financial_simulations.scenario import _keys


@dataclass(frozen=True)
class EvaluationSettings:
    target_basis: str
    target_multiple: float
    target_annual_growth: float
    confidence: float
    max_panel_mb: int

    def __post_init__(self):
        if self.target_basis not in {"nominal", "real"}:
            raise ValueError("Target basis must be nominal or real.")
        if rate(self.target_multiple, "target_multiple") <= 0:
            raise ValueError("Target multiple must be positive.")
        if rate(self.target_annual_growth, "target_annual_growth") <= -1:
            raise ValueError("Target annual growth must exceed -100%.")
        confidence_z(self.confidence)
        integer(self.max_panel_mb, "max_panel_mb")

    def manifest(self):
        return asdict(self)


def load_evaluation(options):
    required = {"target_basis", "target_multiple", "target_annual_growth", "confidence", "max_panel_mb"}
    _keys(options, required, required, "evaluation")
    return EvaluationSettings(**options)


def confidence_z(confidence):
    confidence = rate(confidence, "confidence")
    probability = (1 + confidence) / 2
    if not 0 < confidence < 1 or not probability < 1:
        raise ValueError("Confidence must be strictly between zero and one and numerically representable.")
    return NormalDist().inv_cdf(probability)


def wilson_interval(misses, paths, confidence):
    paths, misses = integer(paths, "paths"), integer(misses, "misses", 0)
    if misses > paths:
        raise ValueError("Misses cannot exceed paths.")
    z = confidence_z(confidence)
    p = misses / paths
    denominator = 1 + z * z / paths
    centre = (p + z * z / (2 * paths)) / denominator
    radius = z * np.sqrt(p * (1 - p) / paths + z * z / (4 * paths * paths)) / denominator
    return max(0.0, float(centre - radius)), min(1.0, float(centre + radius))


def _mean_and_mcse(values, independent):
    # Scaling avoids squaring currency amounts or overflowing a sum of finite values.
    scale = float(np.max(values))
    normalised = values / scale if scale else values
    mean = float(np.mean(normalised) * scale)
    se = float(np.std(normalised, ddof=1) * (scale / np.sqrt(len(values)))) if independent and len(values) > 1 else None
    return mean, se


def drawdown_statistics(wealth, dates):
    """Pathwise depths and elapsed-day durations, retaining unrecovered status."""
    values = np.asarray(wealth, dtype=float)
    dates = np.array([as_date(d) for d in dates], dtype="datetime64[D]")
    if (values.ndim != 2 or values.shape[1] != len(dates) or not len(dates)
            or not len(values) or not np.isfinite(values).all() or (values < 0).any()
            or (values[:, 0] <= 0).any() or (np.diff(dates).astype(int) <= 0).any()):
        raise ValueError("Drawdown requires finite nonnegative paths, positive opening wealth and sorted dates.")
    rows, columns = np.arange(len(values)), np.arange(len(dates))
    elapsed = (dates - dates[0]).astype(int)
    peaks = np.maximum.accumulate(values, axis=1)
    dd = values / peaks - 1
    latest_peak = np.maximum.accumulate(np.where(values >= peaks, columns, -1), axis=1)
    trough = np.argmin(dd, axis=1)
    peak = latest_peak[rows, trough]
    depth = dd[rows, trough]
    has_drawdown = depth < 0
    recovery_mask = (columns > trough[:, None]) & (values >= values[rows, peak][:, None])
    recovered = recovery_mask.any(axis=1) & has_drawdown
    recovery = recovery_mask.argmax(axis=1)
    end = np.where(recovered, recovery, len(dates) - 1)
    previous_peak = np.column_stack((np.zeros(len(values), dtype=int), latest_peak[:, :-1]))
    active = (dd < 0) | np.column_stack((np.zeros(len(values), dtype=bool), dd[:, :-1] < 0))
    durations = np.where(active, elapsed[columns] - elapsed[previous_peak], 0)
    longest = durations.max(axis=1)
    terminal_underwater = dd[:, -1] < 0
    terminal_duration = elapsed[-1] - elapsed[latest_peak[:, -1]]
    return {
        "max_drawdown": depth,
        "max_drawdown_peak_date": [str(dates[p]) if flag else None for p, flag in zip(peak, has_drawdown)],
        "max_drawdown_trough_date": [str(dates[t]) if flag else None for t, flag in zip(trough, has_drawdown)],
        "max_drawdown_recovery_date": [str(dates[r]) if flag else None for r, flag in zip(recovery, recovered)],
        "max_drawdown_recovery_status": np.where(~has_drawdown, "no_drawdown", np.where(recovered, "recovered", "unrecovered")),
        "max_drawdown_observed_duration_days": np.where(has_drawdown, elapsed[end] - elapsed[peak], 0),
        "longest_underwater_days": longest,
        "longest_underwater_includes_open_episode": terminal_underwater & (terminal_duration >= longest),
        "terminal_underwater": terminal_underwater,
    }


class EvaluationPanel:
    """One case's exact observation panel; daily values are account marks only."""

    def __init__(self, paths, observation_dates, settings, capital, inflation=None):
        paths = integer(paths, "paths")
        self.settings = settings
        self.observation_dates = tuple(as_date(d) for d in observation_dates)
        observations = np.array(self.observation_dates, dtype="datetime64[D]")
        if not len(observations) or (np.diff(observations).astype(int) <= 0).any():
            raise ValueError("Evaluation dates must be sorted, unique and nonempty.")
        if rate(capital, "capital") <= 0:
            raise ValueError("Evaluation requires positive opening capital.")
        if paths * len(observations) * 8 > settings.max_panel_mb * 1024 ** 2:
            raise ValueError("Exact evaluation panel exceeds max_panel_mb; raise the explicit limit or reduce the experiment.")
        self.wealth = np.empty((paths, len(observations)))
        self.filled = 0
        self.dates = tuple(pd.date_range(self.observation_dates[0], self.observation_dates[-1]).date)
        daily = np.array(self.dates, dtype="datetime64[D]")
        self.indices = np.searchsorted(observations, daily, side="right") - 1
        self.price_index = assumed_price_index(self.dates, inflation) if inflation is not None else None
        if settings.target_basis == "real" and self.price_index is None:
            raise ValueError("A real target requires an explicit assumed inflation scenario.")
        elapsed = (daily - daily[0]).astype(int) / 365.25
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            self.target = capital * settings.target_multiple * np.exp(np.log1p(settings.target_annual_growth) * elapsed)
        if not np.isfinite(self.target).all() or (self.target <= 0).any():
            raise ValueError("Target curve exceeds numeric range.")

    def add(self, wealth):
        values = np.asarray(wealth, dtype=float)
        if (values.ndim != 2 or values.shape[1] != self.wealth.shape[1] or not len(values)
                or self.filled + len(values) > len(self.wealth) or not np.isfinite(values).all()
                or (values < 0).any() or (values[:, 0] <= 0).any()):
            raise ValueError("Invalid evaluation batch or path count.")
        self.wealth[self.filled:self.filled + len(values)] = values
        self.filled += len(values)
        daily = values[:, self.indices]
        statistics = {f"nominal_{key}": value for key, value in drawdown_statistics(daily, self.dates).items()}
        if self.price_index is not None:
            real = daily / self.price_index
            statistics.update({f"real_{key}": value for key, value in drawdown_statistics(real, self.dates).items()})
        return statistics

    def finish(self, case_id, *, independent):
        if self.filled != len(self.wealth):
            raise ValueError("Evaluation panel is incomplete.")
        # Exact quantiles in column chunks avoid a second full-panel sorting copy.
        quantiles = np.empty((3, self.wealth.shape[1]))
        for start in range(0, self.wealth.shape[1], 128):
            quantiles[:, start:start + 128] = np.quantile(self.wealth[:, start:start + 128], [0.05, 0.5, 0.95], axis=0, method="linear")
        nominal = quantiles[:, self.indices]
        observed = set(self.observation_dates)
        frame = pd.DataFrame({"case_id": case_id, "date": [str(d) for d in self.dates],
                              "is_observation": [d in observed for d in self.dates],
                              "observation_step": self.indices})
        for i, suffix in enumerate(("p05", "median", "p95")):
            frame[f"nominal_{suffix}"] = nominal[i]
            if self.price_index is not None:
                frame[f"real_{suffix}"] = nominal[i] / self.price_index
        if self.price_index is not None:
            frame["price_index"] = self.price_index
        frame["target_basis"] = self.settings.target_basis
        frame["target_nominal"] = self.target * self.price_index if self.settings.target_basis == "real" else self.target
        if self.price_index is not None:
            frame["target_real"] = frame["target_nominal"] / self.price_index
        terminal = self.wealth[:, -1]
        if self.settings.target_basis == "real":
            terminal = terminal / self.price_index[-1]
        target = float(self.target[-1])
        misses = int(np.count_nonzero(terminal < target))
        n, p = len(terminal), misses / len(terminal)
        gaps = np.maximum(target - terminal, 0)
        mean, mean_se = _mean_and_mcse(terminal, independent)
        low, high = wilson_interval(misses, n, self.settings.confidence) if independent else (None, None)
        summary = {"case_id": case_id, "target_basis": self.settings.target_basis, "terminal_target": target,
                   "misses": misses, "paths": n, "fraction_below_target": p,
                   "mean_target_gap": _mean_and_mcse(gaps, False)[0],
                   "mean_gap_when_below_target": _mean_and_mcse(gaps[gaps > 0], False)[0] if misses else None,
                   "terminal_mean_in_target_units": mean,
                   "terminal_mean_mcse": mean_se,
                   "fraction_mcse": float(np.sqrt(p * (1 - p) / n)) if independent else None,
                   "fraction_ci_low": low, "fraction_ci_high": high,
                   "confidence": self.settings.confidence if independent else None,
                   "sampling_error_status": "conditional_independent_simulations" if independent else "dependent_replay_descriptive_only"}
        return frame, summary
