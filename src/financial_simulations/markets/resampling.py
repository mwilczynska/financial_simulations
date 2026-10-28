"""Joint daily-row sampling with explicit block boundaries and donor indices."""

from dataclasses import dataclass

import numpy as np

from financial_simulations.markets.path import MarketPath


_METHOD_CODES = {"independent": 1, "moving_block": 2, "stationary": 3}


def integer(value: int, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}.")
    return int(value)


@dataclass(frozen=True)
class Sampler:
    method: str
    block_length: int | None = None

    def __post_init__(self) -> None:
        if self.method not in _METHOD_CODES:
            raise ValueError("Choose independent, moving_block or stationary sampling.")
        if self.method == "independent":
            if self.block_length is not None:
                raise ValueError("Independent sampling has no block length.")
        else:
            integer(self.block_length, "block_length")


@dataclass(frozen=True)
class Draw:
    indices: np.ndarray
    block_start: np.ndarray
    wrapped: np.ndarray


def _draw(indices, starts, wrapped) -> Draw:
    arrays = (np.asarray(indices, dtype=np.int64), np.asarray(starts, dtype=bool), np.asarray(wrapped, dtype=bool))
    for array in arrays:
        array.setflags(write=False)
    return Draw(*arrays)


def complete_window_count(observations: int, horizon: int) -> int:
    return max(0, integer(observations, "observations", 0) - integer(horizon, "horizon") + 1)


def historical_draw(observations: int, horizon: int, start: int) -> Draw:
    count = complete_window_count(observations, horizon)
    start = integer(start, "start", 0)
    if start >= count:
        raise ValueError("Historical replay requires a complete contiguous window; stitching is not replay.")
    starts = np.zeros(horizon, dtype=bool)
    starts[0] = True
    return _draw(np.arange(start, start + horizon), starts, np.zeros(horizon, dtype=bool))


def sample_indices(observations: int, horizon: int, sampler: Sampler, *, seed: int, path_id: int) -> Draw:
    """PCG64/SeedSequence per path; batch size and execution order are irrelevant.

    Stream key v1: [seed, method code, block length or 0, horizon, path_id].
    Weights are absent, so portfolio comparisons can reuse identical draws.
    """
    observations, horizon = integer(observations, "observations"), integer(horizon, "horizon")
    seed, path_id = integer(seed, "seed", 0), integer(path_id, "path_id", 0)
    length = sampler.block_length or 0
    if sampler.method == "moving_block" and length > observations:
        raise ValueError("Moving blocks must fit within the source observations.")
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(
        [seed, _METHOD_CODES[sampler.method], length, horizon, path_id])))
    if sampler.method == "independent" or length == 1:
        return _draw(rng.integers(observations, size=horizon), np.ones(horizon, dtype=bool),
                     np.zeros(horizon, dtype=bool))
    indices = np.empty(horizon, dtype=np.int64)
    starts, wrapped = np.zeros(horizon, dtype=bool), np.zeros(horizon, dtype=bool)
    cursor = 0
    while cursor < horizon:
        if sampler.method == "moving_block":
            start, run = int(rng.integers(observations - length + 1)), length
        else:
            start, run = int(rng.integers(observations)), int(rng.geometric(1 / length))
        count = min(run, horizon - cursor)
        donor = start + np.arange(count)
        indices[cursor:cursor + count] = donor % observations
        starts[cursor] = True
        if sampler.method == "stationary":
            wrapped[cursor:cursor + count] = (donor > 0) & (donor % observations == 0)
        cursor += count
    return _draw(indices, starts, wrapped)


def sampled_path(source: MarketPath, draw: Draw, target_dates) -> MarketPath:
    """Map whole donor return vectors onto a separately declared account calendar."""
    indices = np.asarray(draw.indices)
    if indices.ndim != 1 or not np.issubdtype(indices.dtype, np.integer):
        raise ValueError("Donor indices must be a one-dimensional integer array.")
    if len(target_dates) != len(indices) + 1 or (indices < 0).any() or (indices >= len(source.returns)).any():
        raise ValueError("Donor indices and target calendar must match a valid source path.")
    return MarketPath(tuple(target_dates), source.assets, source.returns[indices], source.currency)
