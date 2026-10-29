import numpy as np
import pandas as pd
import pytest

from financial_simulations.data.registry import resolve_asset


@pytest.fixture
def processed_fixture(tmp_path):
    """Two full synthetic years of custom and fund daily observations."""
    root = tmp_path / "processed"
    distribution = root / "distributions"
    distribution.mkdir(parents=True)
    dates = pd.bdate_range("2020-01-01", "2021-12-31")
    for j, ticker in enumerate(("USLCAP3x", "ITT3x", "GOLDPM2x", "COMM", "GLSTOCK")):
        asset = resolve_asset(ticker)
        kept = dates.delete(60) if ticker == "ITT3x" else dates
        drift = 0.00015 if ticker == "GLSTOCK" else 0.0002 * (j + 1)
        returns = drift + 0.0005 * np.sin(np.arange(len(kept)) / 13 + j)
        levels = 100 * np.cumprod(1 + returns)
        frame = pd.DataFrame({"Date": kept.strftime("%Y-%m-%d"), "Adj Close": levels,
                              "Total Return": np.r_[np.nan, levels[1:] / levels[:-1] - 1]})
        frame.to_csv(root / asset.filename, index=False)
        cash = np.zeros(len(kept))
        cash[20::63] = 0.002 * (j + 1)
        pd.DataFrame({"Date": kept.strftime("%Y-%m-%d"), "Distribution Return": cash,
                      "Basis": "modeled"}).to_csv(distribution / asset.filename, index=False)
    fund_returns = np.full(len(dates), 0.00015)
    fund_returns[0] = np.nan
    pd.DataFrame({"Fund": "BND", "Date": dates.strftime("%Y-%m-%d"),
                  "Vendor Total Return": fund_returns,
                  "Distribution Return": np.where(np.arange(len(dates)) % 21 == 0, 0.001, 0.0),
                  "Cash Status": "observed_no_vendor_cash_event"}).to_csv(distribution / "fund_prices.csv", index=False)
    return root
