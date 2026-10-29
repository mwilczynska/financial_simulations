"""Local processed ticker histories for the retirement planner.

Custom tickers match the investment tracker. Fund tickers use the companion
distribution project's observed vendor total-return histories. Nothing is
downloaded, and the USD histories are never described as observed AUD returns.
"""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.data.registry import resolve_asset
from financial_simulations.markets.path import MarketPath


CUSTOM_TICKERS = ("USLCAP", "GOLDPM", "LTT", "ITT", "STT", "COMM", "USLCAP3x",
                  "LTT3x", "ITT3x", "GOLDPM2x", "GLSTOCK", "GLBOND", "GLSTBOND")
FUND_TICKERS = ("SHY", "IEF", "TLT", "VT", "BND", "BWX", "ISHG", "BWZ",
                "UPRO", "TYD", "TMF", "GLD", "UGL", "DBC")
TICKERS = CUSTOM_TICKERS + FUND_TICKERS
_LOOKUP = {ticker.upper(): ticker for ticker in TICKERS}
_LOOKUP.update({"CMDTY": "COMM", "GOLD2X": "GOLDPM2x"})


def ticker_name(value: str) -> str:
    """Resolve a supported local ticker, retaining the tracker's display spelling."""
    if not isinstance(value, str):
        raise ValueError("Ticker must be text.")
    try:
        return _LOOKUP[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"Ticker {value!r} is unavailable in the local processed datasets.") from exc


def processed_root() -> Path:
    override = os.environ.get("FINANCIAL_DATASETS_PROCESSED")
    return Path(override) if override else Path(__file__).resolve().parents[3].parent / "financial_datasets" / "data" / "processed"


@dataclass(frozen=True)
class PlanMarketData:
    path: MarketPath
    asset_summary: pd.DataFrame
    income_yields: dict[str, float]
    manifest: dict


def _read(path: Path, hashes: dict) -> pd.DataFrame:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"Local processed data missing: {path.name}.") from exc
    hashes[path.name if path.parent.name != "distributions" else f"distributions/{path.name}"] = sha256(raw).hexdigest()
    return pd.read_csv(BytesIO(raw), low_memory=False)


def _dates(values, label: str) -> pd.DatetimeIndex:
    dates = pd.DatetimeIndex(pd.to_datetime(values, format="%Y-%m-%d", errors="raise"))
    if dates.hasnans or not dates.is_monotonic_increasing or not dates.is_unique:
        raise ValueError(f"{label}: dates must be nonempty, increasing and unique.")
    return dates


def _numeric(values, label: str, *, first_missing=False) -> np.ndarray:
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    check = arr[1:] if first_missing else arr
    if not np.isfinite(check).all():
        raise ValueError(f"{label}: missing or nonfinite numeric observations.")
    return arr


def _completed_years(dates: pd.DatetimeIndex) -> set[int]:
    years = set()
    for year, group in pd.Series(dates, index=dates).groupby(dates.year):
        if group.iloc[0].month == 1 and group.iloc[0].day <= 7 and group.iloc[-1].month == 12 and group.iloc[-1].day >= 24:
            years.add(int(year))
    return years


def _custom(ticker: str, root: Path, hashes: dict):
    asset = resolve_asset(ticker)
    file = root / asset.filename
    frame = _read(file, hashes)
    dates = _dates(frame["Date"], ticker)
    levels = _numeric(frame[asset.level_column], f"{ticker} total-return levels")
    published = _numeric(frame[asset.return_column], f"{ticker} total returns", first_missing=True)
    if (levels <= 0).any() or not np.allclose(levels[1:] / levels[:-1] - 1, published[1:], rtol=0, atol=1e-8):
        raise ValueError(f"{ticker}: processed total-return levels do not reconcile.")
    companion = _read(root / "distributions" / asset.filename, hashes)
    if not _dates(companion["Date"], f"{ticker} distributions").equals(dates):
        raise ValueError(f"{ticker}: distribution companion calendar differs from returns.")
    cash = _numeric(companion["Distribution Return"], f"{ticker} cash contributions")
    if (cash < 0).any():
        raise ValueError(f"{ticker}: negative cash distribution contribution.")
    return dates, levels, cash, "custom historical proxy", companion["Basis"].value_counts().to_dict()


def _fund(ticker: str, frame: pd.DataFrame):
    part = frame.loc[frame["Fund"] == ticker].copy()
    if part.empty:
        raise ValueError(f"{ticker}: no fund history in fund_prices.csv.")
    dates = _dates(part["Date"], ticker)
    returns = _numeric(part["Vendor Total Return"], f"{ticker} vendor total returns", first_missing=True)
    if (returns[1:] < -1).any():
        raise ValueError(f"{ticker}: invalid vendor total return.")
    levels = np.r_[1.0, np.cumprod(1 + returns[1:])]
    if not np.isfinite(levels).all() or (levels <= 0).any():
        raise ValueError(f"{ticker}: invalid compounded total-return levels.")
    cash = _numeric(part["Distribution Return"], f"{ticker} cash contributions")
    if (cash < 0).any():
        raise ValueError(f"{ticker}: negative cash distribution contribution.")
    return dates, levels, cash, "observed fund vendor history", part["Cash Status"].value_counts().to_dict()


def load_plan_markets(tickers, root: str | Path | None = None) -> PlanMarketData:
    """Load full ticker histories and their joint common-date return matrix.

    The annual income number is the mean sum of daily cash/preceding-price
    contributions over complete calendar years. It is only a planning proxy,
    not a buy-and-hold yield, tax allocation, or fresh return on top of TR.
    """
    names = tuple(ticker_name(value) for value in tickers)
    if not names or len(names) != len(set(names)):
        raise ValueError("Choose at least one unique ticker.")
    root = Path(root) if root is not None else processed_root()
    hashes: dict[str, str] = {}
    fund_table = _read(root / "distributions" / "fund_prices.csv", hashes) if any(t in FUND_TICKERS for t in names) else None
    histories, rows, income, source_info = {}, [], {}, {}
    for ticker in names:
        dates, levels, cash, source, quality = (_custom(ticker, root, hashes) if ticker in CUSTOM_TICKERS
                                                else _fund(ticker, fund_table))
        full_years = _completed_years(dates)
        annual_cash = pd.Series(cash, index=dates).groupby(dates.year).sum()
        yield_proxy = float(annual_cash.loc[sorted(full_years)].mean()) if full_years else 0.0
        if not 0 <= yield_proxy < 1:
            raise ValueError(f"{ticker}: estimated income split outside supported range.")
        elapsed = (dates[-1] - dates[0]).days
        if elapsed <= 0:
            raise ValueError(f"{ticker}: insufficient return history.")
        daily = levels[1:] / levels[:-1] - 1
        growth = levels / levels[0]
        rows.append({"Ticker": ticker, "Source": source, "First": dates[0].date(), "Last": dates[-1].date(),
                     "Observations": len(daily), "Full-sample CAGR": float(growth[-1] ** (365.25 / elapsed) - 1),
                     "Daily volatility, annualised": float(np.std(daily, ddof=1) * np.sqrt(252)),
                     "Maximum drawdown": float(np.min(growth / np.maximum.accumulate(growth) - 1)),
                     "Cash contribution proxy": yield_proxy, "Complete income years": len(full_years)})
        income[ticker] = yield_proxy
        histories[ticker] = pd.Series(levels, index=dates)
        source_info[ticker] = {"source": source, "quality_counts": {str(k): int(v) for k, v in quality.items()},
                               "first": str(dates[0].date()), "last": str(dates[-1].date()),
                               "complete_income_years": len(full_years)}
    common = histories[names[0]].index
    for ticker in names[1:]:
        common = common.intersection(histories[ticker].index)
    if len(common) < 253:
        raise ValueError("Selected tickers have fewer than 252 shared return observations; choose a compatible portfolio.")
    levels = np.column_stack([histories[ticker].loc[common].to_numpy() for ticker in names])
    returns = levels[1:] / levels[:-1] - 1
    path = MarketPath(tuple(common.date), names, returns, "USD")
    manifest = {"currency": "USD", "calendar_policy": "common_dates", "common_first": str(common[0].date()),
                "common_last": str(common[-1].date()), "common_returns": len(returns),
                "dropped_dates": {ticker: int(len(histories[ticker]) - len(common)) for ticker in names},
                "inputs_sha256": hashes, "tickers": source_info,
                "cash_proxy_definition": "Mean sum of daily cash/preceding-price contributions in complete calendar years; not a buy-and-hold yield or tax allocation."}
    return PlanMarketData(path, pd.DataFrame(rows), income, manifest)
