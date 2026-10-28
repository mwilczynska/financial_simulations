"""An opening valuation followed by daily observation-interval returns."""

from dataclasses import dataclass
from datetime import date

import numpy as np

from financial_simulations.dates import as_date


@dataclass(frozen=True)
class MarketPath:
    """returns[i] spans dates[i] to dates[i + 1]; no opening zero row."""

    dates: tuple[date, ...]
    assets: tuple[str, ...]
    returns: np.ndarray
    currency: str = "USD"

    def __post_init__(self) -> None:
        dates = tuple(as_date(value) for value in self.dates)
        assets = tuple(self.assets)
        if not dates or any(b <= a for a, b in zip(dates, dates[1:])):
            raise ValueError("Valuation dates must be nonempty, sorted and unique.")
        if not assets or len(set(assets)) != len(assets) or any(not a for a in assets):
            raise ValueError("Assets must be nonempty and unique.")
        if not isinstance(self.currency, str) or len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError("Declare a three-letter uppercase currency.")
        returns = np.array(self.returns, dtype=float, copy=True)
        if returns.shape != (len(dates) - 1, len(assets)):
            raise ValueError("Expected one return vector for each pair of valuation dates.")
        if not np.isfinite(returns).all() or (returns < -1).any():
            raise ValueError("Simple returns must be finite and at least -100%.")
        returns.setflags(write=False)
        object.__setattr__(self, "dates", dates)
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "returns", returns)
