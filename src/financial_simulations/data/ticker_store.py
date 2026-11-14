"""Downloaded ticker histories: fetched once on request, checked, and stored locally.

A downloaded ticker is written with its market: ``VAS.AX`` for the ASX, ``SPY.US`` for a US exchange. The suffix
fixes the currency the vendor must report (AUD, USD) and keeps downloaded tickers apart from the curated datasets,
several of which share their letters with a US share (``STT``, ``ITT``, ``LTT``, ``COMM``).

Nothing here runs during a simulation. ``download`` is called from the app's button or the command line, and the
market loader only reads the stored files, so a run uses exactly the rows whose hash its manifest records.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
import sys
import time

import numpy as np
import pandas as pd


MARKETS = {"AX": ("ASX", "AUD"), "US": ("US exchange", "USD")}
MINIMUM_ROWS = 253
ATTEMPTS, TIMEOUT = 3, 60  # tries per download, and seconds allowed for each response
COLUMNS = ["Date", "Close", "Adj Close", "Dividend", "Total Return", "Distribution Return", "Status"]
# Yahoo's adjusted close differs from price change plus the dividend over the previous close by the product of the two
# (second order) and by rounding; a larger gap means the adjustment and the recorded cash disagree.
EVENT_TOLERANCE, QUIET_TOLERANCE = 2e-3, 1e-4
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9-]{0,9}\.(AX|US)")


def symbol_name(value: str) -> str:
    """A downloaded ticker's name, upper case with its market suffix."""
    name = value.strip().upper() if isinstance(value, str) else ""
    if not _SYMBOL.fullmatch(name):
        raise ValueError(f"Ticker {value!r} is unavailable: use a listed ticker, or write a downloaded one with its "
                         "market, such as VAS.AX (ASX) or SPY.US (US exchanges).")
    return name


def is_symbol(value) -> bool:
    return isinstance(value, str) and bool(_SYMBOL.fullmatch(value.strip().upper()))


def market(symbol: str) -> tuple[str, str]:
    """The market's name and currency for a downloaded ticker."""
    return MARKETS[symbol_name(symbol).rsplit(".", 1)[1]]


def vendor_symbol(symbol: str) -> str:
    """Yahoo writes ASX tickers with ``.AX`` and US tickers bare."""
    name = symbol_name(symbol)
    return name[:-3] if name.endswith(".US") else name


def store_root() -> Path:
    override = os.environ.get("FINANCIAL_SIMULATIONS_TICKERS")
    return Path(override) if override else Path(__file__).resolve().parents[3] / "data" / "local" / "tickers"


def stored_symbols(root: str | Path | None = None) -> tuple[str, ...]:
    root = Path(root) if root is not None else store_root()
    if not root.is_dir():
        return ()
    return tuple(sorted(p.stem for p in root.glob("*.csv") if is_symbol(p.stem) and p.with_suffix(".json").is_file()))


def stored_meta(symbol: str, root: str | Path | None = None) -> dict:
    root = Path(root) if root is not None else store_root()
    name = symbol_name(symbol)
    try:
        return json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{name} has not been downloaded. Add it on the Investments tab, or run "
                         f"`python -m financial_simulations.data.ticker_store {name}`.") from exc


def normalise(symbol: str, history: pd.DataFrame, info: dict) -> tuple[pd.DataFrame, dict]:
    """Check a vendor history and return the stored table and its description.

    ``history`` has one row per trading day with ``Close``, ``Adj Close`` and ``Dividends`` in consistent share units
    (Yahoo restates all three for later splits). The total return is the change in the adjusted close; the cash
    contribution is the dividend over the previous close. Rows without a price are dropped, never filled.
    """
    name = symbol_name(symbol)
    place, currency = market(name)
    if str(info.get("symbol", "")).upper() != vendor_symbol(name):
        raise ValueError(f"{name}: the vendor returned {info.get('symbol')!r}, not {vendor_symbol(name)}.")
    if info.get("currency") != currency:
        raise ValueError(f"{name}: quoted in {info.get('currency')}, but a {place} ticker must be in {currency}. "
                         "Check the market suffix.")
    missing = {"Close", "Adj Close", "Dividends"} - set(history.columns)
    if missing:
        raise ValueError(f"{name}: vendor history lacks {', '.join(sorted(missing))}.")
    index = pd.DatetimeIndex(history.index)
    index = (index.tz_localize(None) if index.tz is not None else index).normalize()
    frame = pd.DataFrame({"Close": pd.to_numeric(history["Close"], errors="coerce").to_numpy(dtype=float),
                          "Adj Close": pd.to_numeric(history["Adj Close"], errors="coerce").to_numpy(dtype=float),
                          "Dividend": pd.to_numeric(history["Dividends"], errors="coerce").fillna(0.0).to_numpy(dtype=float)},
                         index=index)
    priced = frame["Close"].notna() & frame["Adj Close"].notna()
    lost_cash = float(frame.loc[~priced, "Dividend"].sum())
    dropped = int((~priced).sum())
    frame = frame.loc[priced]
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{name}: vendor dates are not unique and increasing.")
    if len(frame) < MINIMUM_ROWS:
        raise ValueError(f"{name}: only {len(frame)} priced days; at least {MINIMUM_ROWS} are needed.")
    if not np.isfinite(frame.to_numpy()).all() or (frame[["Close", "Adj Close"]] <= 0).any().any() or (frame["Dividend"] < 0).any():
        raise ValueError(f"{name}: nonpositive price or negative dividend in the vendor history.")
    close, adjusted, dividend = (frame[c].to_numpy() for c in ("Close", "Adj Close", "Dividend"))
    total = np.r_[np.nan, adjusted[1:] / adjusted[:-1] - 1]
    cash = np.r_[0.0, dividend[1:] / close[:-1]]
    residual = np.r_[0.0, total[1:] - (close[1:] / close[:-1] - 1) - cash[1:]]
    paid = dividend > 0
    status = np.where(paid, np.where(np.abs(residual) > EVENT_TOLERANCE, "cash_event_disagrees_with_adjustment",
                                     "observed_cash_event"),
                      np.where(np.abs(residual) > QUIET_TOLERANCE, "adjustment_without_cash_event", "observed"))
    status[0] = "opening_price"
    # A dividend on the first row has no previous close, so its contribution is unknown and is left at zero.
    table = pd.DataFrame({"Date": frame.index.strftime("%Y-%m-%d"), "Close": close, "Adj Close": adjusted,
                          "Dividend": dividend, "Total Return": total, "Distribution Return": cash, "Status": status})
    counts = {str(k): int(v) for k, v in pd.Series(status).value_counts().items()}
    meta = {"symbol": name, "vendor_symbol": vendor_symbol(name), "market": place, "currency": currency,
            "exchange": info.get("fullExchangeName") or info.get("exchangeName") or "",
            "name": info.get("longName") or info.get("shortName") or "", "kind": info.get("instrumentType") or "",
            "first": table["Date"].iloc[0], "last": table["Date"].iloc[-1], "rows": len(table),
            "rows_without_price_dropped": dropped, "dividends_on_dropped_rows": lost_cash, "status_counts": counts,
            "largest_daily_move": float(np.nanmax(np.abs(total)))}
    return table, meta


def _yahoo(vendor: str) -> tuple[pd.DataFrame, dict, str]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ValueError("Downloading needs the yfinance package: pip install \"financial_simulations[download]\".") from exc
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # failures are reported here, once, in plain words
    problem = None
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(2.0 * attempt)
        ticker = yf.Ticker(vendor)
        try:
            # A long daily history is a large response; the library's 10-second default cuts it off on a slow line.
            history = ticker.history(period="max", interval="1d", auto_adjust=False, actions=True, timeout=TIMEOUT,
                                     raise_errors=True)
            info = dict(ticker.get_history_metadata() or {})
        except Exception as exc:  # yfinance raises many types for network, rate-limit and unknown-symbol failures
            problem = exc
            if any(word in str(exc).lower() for word in ("delisted", "not found", "no data", "no timezone")):
                break  # the vendor answered: there is no such ticker, so asking again will not help
            continue
        if history is not None and not history.empty:
            return history, info, f"Yahoo Finance chart data through yfinance {yf.__version__}"
        problem = "no rows returned"
    raise ValueError(f"{vendor}: Yahoo Finance returned no history ({str(problem).strip().splitlines()[0][:160]}). Check "
                     "the ticker and its market suffix, or try again if the connection is slow.")


def download(symbol: str, root: str | Path | None = None, fetch=None) -> dict:
    """Fetch the longest history the vendor has, check it and store it. Returns its description."""
    name = symbol_name(symbol)
    root = Path(root) if root is not None else store_root()
    history, info, source = (fetch or _yahoo)(vendor_symbol(name))
    table, meta = normalise(name, history, info)
    text = table.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    meta.update({"source": source, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "sha256": sha256(text.encode("utf-8")).hexdigest()})
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.csv").write_text(text, encoding="utf-8", newline="")
    (root / f"{name}.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    return meta


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("usage: python -m financial_simulations.data.ticker_store SYMBOL.AX|SYMBOL.US ...")
        return 2
    failed = 0
    for value in arguments:
        try:
            meta = download(value)
        except ValueError as exc:
            failed += 1
            print(f"{value}: {exc}")
            continue
        print(f"{meta['symbol']}: {meta['name'] or meta['kind']}, {meta['currency']}, {meta['first']} to {meta['last']}, "
              f"{meta['rows']:,} days; {meta['status_counts']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
