"""Long-only, fully invested target weights; cash is a separate ledger balance."""

from dataclasses import dataclass
from math import fsum, isfinite
from types import MappingProxyType
from typing import Mapping

from financial_simulations.data.registry import resolve_asset


@dataclass(frozen=True)
class PortfolioSpec:
    weights: Mapping[str, float]
    rebalance: str = "annual"
    currency: str = "USD"

    def __post_init__(self) -> None:
        canonical = {}
        for identifier, value in self.weights.items():
            asset = resolve_asset(identifier)
            if asset.identifier in canonical:
                raise ValueError(f"Duplicate aliases for {asset.identifier}.")
            if isinstance(value, bool):
                raise ValueError("Weights must be numeric fractions, not booleans.")
            weight = float(value)
            if not isfinite(weight) or weight < 0:
                raise ValueError("Weights must be finite and nonnegative.")
            if asset.currency != self.currency:
                raise ValueError(f"{identifier} is {asset.currency}; an explicit FX adapter is required.")
            canonical[asset.identifier] = weight
        total = fsum(canonical.values())
        if not canonical or abs(total - 1.0) > 1e-10:
            raise ValueError("Weights must sum to one; no discretionary normalisation is applied.")
        if self.rebalance not in ("annual", "buy_and_hold"):
            raise ValueError("Rebalance must be 'annual' or 'buy_and_hold'.")
        # Remove only floating-point summation noise within the declared tolerance.
        object.__setattr__(self, "weights", MappingProxyType({a: w / total for a, w in canonical.items()}))

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(self.weights)
