"""Local processed ticker histories for the retirement planner.

Custom tickers match the investment tracker. Fund tickers use the companion
distribution project's observed vendor total-return histories. Downloaded
tickers (``VAS.AX``, ``SPY.US``) are read from the local ticker store; nothing
is fetched here. Returns are measured in one currency, AUD or USD, and a
history quoted in the other is converted with the AUDUSD spot rate.
"""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.data.registry import resolve_asset
from financial_simulations.data.ticker_store import is_symbol, market, store_root, stored_meta, symbol_name
from financial_simulations.markets.path import MarketPath


CUSTOM_TICKERS = ("USLCAP", "GOLDPM", "LTT", "ITT", "STT", "COMM", "USLCAP3x",
                  "LTT3x", "ITT3x", "GOLDPM2x", "GLSTOCK", "GLBOND", "GLSTBOND",
                  "USLCAP2x", "GLSTOCK2x", "LTT2x", "ITT2x", "STT2x", "GLBOND2x")
FUND_TICKERS = ("SHY", "IEF", "TLT", "VT", "BND", "BWX", "ISHG", "BWZ",
                "UPRO", "TYD", "TMF", "GLD", "UGL", "DBC", "SSO", "UST", "UBT")
TICKERS = CUSTOM_TICKERS + FUND_TICKERS
_RESET = "daily-reset leverage; modelled from {base} until {year}, then the {fund} fund"
DESCRIPTIONS = {
    "USLCAP": "US large-company shares (S&P 500)",
    "USLCAP2x": "S&P 500 at 2× " + _RESET.format(base="USLCAP", year=2006, fund="SSO"),
    "USLCAP3x": "S&P 500 at 3× " + _RESET.format(base="USLCAP", year=2009, fund="UPRO"),
    "GLSTOCK": "Global shares, all countries; a modelled proxy, then the VT fund from 2008",
    "GLSTOCK2x": "Global shares at 2× " + _RESET.format(base="GLSTOCK", year="March 2026", fund="WLDU"),
    "STT": "Short-term US Treasury bonds, 1–3 years (like SHY)",
    "STT2x": "Short-term US Treasuries at 2× daily-reset leverage; modelled throughout, as no such fund exists",
    "ITT": "Intermediate-term US Treasury bonds, 7–10 years (like IEF)",
    "ITT2x": "Intermediate-term US Treasuries at 2× " + _RESET.format(base="ITT", year=2010, fund="UST"),
    "ITT3x": "Intermediate-term US Treasuries at 3× " + _RESET.format(base="ITT", year=2009, fund="TYD"),
    "LTT": "Long-term US Treasury bonds, 20+ years (like TLT)",
    "LTT2x": "Long-term US Treasuries at 2× " + _RESET.format(base="LTT", year=2010, fund="UBT"),
    "LTT3x": "Long-term US Treasuries at 3× " + _RESET.format(base="LTT", year=2009, fund="TMF"),
    "GLBOND": "Global bonds, currency unhedged; a modelled proxy, then a blend of the BND and BWX funds",
    "GLBOND2x": "Global bonds at 2× daily-reset leverage; modelled throughout, as no such fund exists",
    "GLSTBOND": "Global short-term government bonds, 1–3 years, currency unhedged; a modelled proxy, then a fund blend",
    "GOLDPM": "Gold; modelled until 2004, then the GLD fund",
    "GOLDPM2x": "Gold at 2× " + _RESET.format(base="the gold price", year=2008, fund="UGL"),
    "COMM": "Broad commodity futures with collateral interest (like DBC)",
    "SHY": "iShares 1–3 Year Treasury Bond ETF",
    "IEF": "iShares 7–10 Year Treasury Bond ETF",
    "TLT": "iShares 20+ Year Treasury Bond ETF",
    "VT": "Vanguard Total World Stock ETF",
    "BND": "Vanguard Total Bond Market ETF (US bonds)",
    "BWX": "SPDR Bloomberg International Treasury Bond ETF (non-US government bonds)",
    "ISHG": "iShares 1–3 Year International Treasury Bond ETF",
    "BWZ": "SPDR Bloomberg Short Term International Treasury Bond ETF",
    "UPRO": "ProShares UltraPro S&P 500 (3× daily)",
    "TYD": "Direxion Daily 7–10 Year Treasury Bull 3X",
    "TMF": "Direxion Daily 20+ Year Treasury Bull 3X",
    "GLD": "SPDR Gold Shares",
    "UGL": "ProShares Ultra Gold (2× daily)",
    "DBC": "Invesco DB Commodity Index Tracking Fund",
    "SSO": "ProShares Ultra S&P 500 (2× daily)",
    "UST": "ProShares Ultra 7–10 Year Treasury (2× daily)",
    "UBT": "ProShares Ultra 20+ Year Treasury (2× daily)",
}
_LOOKUP = {ticker.upper(): ticker for ticker in TICKERS}
_LOOKUP.update({"CMDTY": "COMM", "GOLD2X": "GOLDPM2x"})


CURRENCIES = ("AUD", "USD")
FX_FILE = "fx_aud_usd.csv"  # US dollars per Australian dollar


def ticker_name(value: str) -> str:
    """A listed ticker in the tracker's spelling, or a downloaded ticker with its market suffix."""
    if not isinstance(value, str):
        raise ValueError("Ticker must be text.")
    listed = _LOOKUP.get(value.strip().upper())
    return listed if listed is not None else symbol_name(value)


def native_currency(ticker: str) -> str:
    """The currency a ticker's history is quoted in: every listed ticker is in US dollars."""
    return market(ticker)[1] if is_symbol(ticker) else "USD"


def describe(ticker: str, ticker_root: str | Path | None = None) -> str:
    """One line on what a ticker is; a downloaded ticker gives the vendor's name and its market."""
    if ticker in DESCRIPTIONS:
        return DESCRIPTIONS[ticker]
    meta = stored_meta(ticker, ticker_root)
    return f"{meta['name'] or meta['kind'] or 'Downloaded history'} ({meta['exchange'] or meta['market']}, {meta['currency']})"


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


def plan_markets(plan: dict) -> PlanMarketData:
    """The histories a normalized plan selects, in the currency it measures returns in."""
    return load_plan_markets(plan["assets"], currency=plan["market"]["currency"])


def _stored(ticker: str, ticker_root: Path, hashes: dict):
    meta = stored_meta(ticker, ticker_root)
    raw = (ticker_root / f"{ticker}.csv").read_bytes()
    digest = sha256(raw).hexdigest()
    if digest != meta["sha256"]:
        raise ValueError(f"{ticker}: the stored history does not match its recorded hash; download it again.")
    hashes[f"tickers/{ticker}.csv"] = digest
    frame = pd.read_csv(BytesIO(raw))
    dates = _dates(frame["Date"], ticker)
    returns = _numeric(frame["Total Return"], f"{ticker} total returns", first_missing=True)
    if (returns[1:] <= -1).any():
        raise ValueError(f"{ticker}: invalid total return.")
    cash = _numeric(frame["Distribution Return"], f"{ticker} cash contributions")
    if (cash < 0).any():
        raise ValueError(f"{ticker}: negative cash distribution contribution.")
    return dates, np.r_[1.0, np.cumprod(1 + returns[1:])], cash, "downloaded vendor history", meta["status_counts"]


def _exchange_rate(root: Path, hashes: dict) -> pd.Series:
    """US dollars per Australian dollar on the days the source published a rate."""
    frame = _read(root / FX_FILE, hashes)
    rate = pd.Series(_numeric(frame["Close"], "AUDUSD rate"), index=_dates(frame["Date"], "AUDUSD"))
    if (rate <= 0).any():
        raise ValueError("AUDUSD: nonpositive exchange rate.")
    return rate


def load_plan_markets(tickers, root: str | Path | None = None, *, currency: str = "USD",
                      ticker_root: str | Path | None = None) -> PlanMarketData:
    """Load full ticker histories and their joint common-date return matrix in one currency.

    A history quoted in the other currency is converted with the AUDUSD spot rate on the dates both have: a level in
    US dollars divided by US dollars per Australian dollar is a level in Australian dollars. No rate is carried to a
    date without one; a step across such a date compounds the levels, as for any missing trading day.

    The annual income number is the mean sum of daily cash/preceding-price
    contributions over complete calendar years, in the ticker's own currency. It is only a planning proxy,
    not a buy-and-hold yield, tax allocation, or fresh return on top of TR.
    """
    if currency not in CURRENCIES:
        raise ValueError(f"Returns can be measured in {' or '.join(CURRENCIES)}, not {currency!r}.")
    names = tuple(ticker_name(value) for value in tickers)
    if not names or len(names) != len(set(names)):
        raise ValueError("Choose at least one unique ticker.")
    root = Path(root) if root is not None else processed_root()
    ticker_root = Path(ticker_root) if ticker_root is not None else store_root()
    hashes: dict[str, str] = {}
    fund_table = _read(root / "distributions" / "fund_prices.csv", hashes) if any(t in FUND_TICKERS for t in names) else None
    rate = _exchange_rate(root, hashes) if any(native_currency(t) != currency for t in names) else None
    histories, rows, income, source_info = {}, [], {}, {}
    for ticker in names:
        dates, levels, cash, source, quality = (_custom(ticker, root, hashes) if ticker in CUSTOM_TICKERS
                                                else _fund(ticker, fund_table) if ticker in FUND_TICKERS
                                                else _stored(ticker, ticker_root, hashes))
        full_years = _completed_years(dates)
        annual_cash = pd.Series(cash, index=dates).groupby(dates.year).sum()
        yield_proxy = float(annual_cash.loc[sorted(full_years)].mean()) if full_years else 0.0
        if not 0 <= yield_proxy < 1:
            raise ValueError(f"{ticker}: estimated income split outside supported range.")
        native, native_first, native_rows = native_currency(ticker), dates[0], len(dates)
        if native != currency:
            shared = dates.intersection(rate.index)
            if len(shared) < 253:
                raise ValueError(f"{ticker}: fewer than 252 returns on days with an AUDUSD rate.")
            own = pd.Series(levels, index=dates).loc[shared].to_numpy()
            quoted = rate.loc[shared].to_numpy()
            dates, levels = shared, own / quoted if currency == "AUD" else own * quoted
        elapsed = (dates[-1] - dates[0]).days
        if elapsed <= 0:
            raise ValueError(f"{ticker}: insufficient return history.")
        daily = levels[1:] / levels[:-1] - 1
        growth = levels / levels[0]
        rows.append({"Ticker": ticker, "Source": source, "Quoted in": native,
                     "First": dates[0].date(), "Last": dates[-1].date(),
                     "Observations": len(daily), "Full-sample CAGR": float(growth[-1] ** (365.25 / elapsed) - 1),
                     "Daily volatility, annualised": float(np.std(daily, ddof=1) * np.sqrt(252)),
                     "Maximum drawdown": float(np.min(growth / np.maximum.accumulate(growth) - 1)),
                     "Cash contribution proxy": yield_proxy, "Complete income years": len(full_years)})
        income[ticker] = yield_proxy
        histories[ticker] = pd.Series(levels, index=dates)
        source_info[ticker] = {"source": source, "quality_counts": {str(k): int(v) for k, v in quality.items()},
                               "first": str(dates[0].date()), "last": str(dates[-1].date()),
                               "quoted_in": native, "own_first": str(native_first.date()),
                               "dates_without_exchange_rate": native_rows - len(dates),
                               "complete_income_years": len(full_years)}
    common = histories[names[0]].index
    for ticker in names[1:]:
        common = common.intersection(histories[ticker].index)
    if len(common) < 253:
        raise ValueError("Selected tickers have fewer than 252 shared return observations; choose a compatible portfolio.")
    levels = np.column_stack([histories[ticker].loc[common].to_numpy() for ticker in names])
    returns = levels[1:] / levels[:-1] - 1
    path = MarketPath(tuple(common.date), names, returns, currency)
    manifest = {"currency": currency,
                "conversion": ("AUDUSD spot on shared dates; no rate carried to a date without one" if rate is not None
                               else "none: every ticker is quoted in this currency"),
                "calendar_policy": "common_dates", "common_first": str(common[0].date()),
                "common_last": str(common[-1].date()), "common_returns": len(returns),
                "dropped_dates": {ticker: int(len(histories[ticker]) - len(common)) for ticker in names},
                "inputs_sha256": hashes, "tickers": source_info,
                "cash_proxy_definition": "Mean sum of daily cash/preceding-price contributions in complete calendar years; not a buy-and-hold yield or tax allocation."}
    return PlanMarketData(path, pd.DataFrame(rows), income, manifest)
