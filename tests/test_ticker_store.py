"""Downloaded tickers and currency conversion, on synthetic histories: no test touches the network."""

import json

import numpy as np
import pandas as pd
import pytest

from financial_simulations.data import ticker_store
from financial_simulations.data.plan_markets import describe, load_plan_markets, native_currency, ticker_name
from financial_simulations.retirement.plan import PlanError, build_inputs, default_plan, normalize_plan, plan_to_toml


DATES = pd.bdate_range("2020-01-01", "2021-12-31")


def vendor_history(dividend_days=(40, 103), growth=0.0004):
    """A price that grows steadily and pays 1% of the previous close on each dividend day."""
    close = 50 * np.cumprod(np.full(len(DATES), 1 + growth))
    dividend = np.zeros(len(DATES))
    total = np.full(len(DATES), growth)
    for day in dividend_days:
        dividend[day] = 0.01 * close[day - 1]
        total[day] += 0.01
    adjusted = close[-1] * np.cumprod(1 + total) / np.prod(1 + total)
    return pd.DataFrame({"Close": close, "Adj Close": adjusted, "Dividends": dividend},
                        index=DATES.tz_localize("Australia/Sydney"))


def fetcher(currency="AUD", history=None):
    def fetch(vendor):
        info = {"symbol": vendor, "currency": currency, "fullExchangeName": "ASX", "longName": "Example Fund",
                "instrumentType": "ETF"}
        return (vendor_history() if history is None else history), info, "synthetic vendor"
    return fetch


@pytest.fixture()
def stores(processed_fixture, tmp_path):
    """The processed fixture with a moving exchange rate, and a ticker store holding one ASX and one US ticker."""
    root = tmp_path / "processed"
    (root / "distributions").mkdir(parents=True)
    for file in processed_fixture.rglob("*.csv"):
        (root / file.relative_to(processed_fixture)).write_bytes(file.read_bytes())
    kept = DATES.delete([30, 31])  # two days without a published rate
    rate = 0.7 * np.cumprod(1 + 0.0003 * np.cos(np.arange(len(kept)) / 9))
    pd.DataFrame({"Date": kept.strftime("%Y-%m-%d"), "Close": rate}).to_csv(root / "fx_aud_usd.csv", index=False)
    tickers = tmp_path / "tickers"
    ticker_store.download("vas.ax", tickers, fetch=fetcher("AUD"))
    ticker_store.download("SPY.US", tickers, fetch=fetcher("USD"))
    return root, tickers, pd.Series(rate, index=kept)


def test_names_carry_their_market_and_listed_names_win():
    assert ticker_name("vas.ax") == "VAS.AX" and ticker_name("brk-b.us") == "BRK-B.US"
    assert ticker_name("STT") == "STT" and ticker_name("stt.us") == "STT.US"  # the dataset, and the US share
    assert ticker_store.vendor_symbol("SPY.US") == "SPY" and ticker_store.vendor_symbol("VAS.AX") == "VAS.AX"
    assert native_currency("VAS.AX") == "AUD" and native_currency("SPY.US") == "USD" and native_currency("VT") == "USD"
    for bad in ("SPY", "VAS", "VAS.L", "../x.AX", ".AX", "TOOLONGTICKER.US"):
        with pytest.raises(ValueError, match="unavailable"):
            ticker_name(bad)


def test_download_stores_the_full_checked_history(tmp_path):
    meta = ticker_store.download("VAS.AX", tmp_path, fetch=fetcher())
    table = pd.read_csv(tmp_path / "VAS.AX.csv")
    assert meta["first"] == "2020-01-01" == table["Date"].iloc[0] and meta["rows"] == len(DATES)
    assert meta["status_counts"] == {"observed": len(DATES) - 3, "observed_cash_event": 2, "opening_price": 1}
    assert table["Total Return"].iloc[1:].sub(0.0004).abs().max() == pytest.approx(0.01, abs=1e-9)
    assert table["Distribution Return"].sum() == pytest.approx(0.02)
    assert json.loads((tmp_path / "VAS.AX.json").read_text())["sha256"] == meta["sha256"]
    assert ticker_store.stored_symbols(tmp_path) == ("VAS.AX",)
    assert describe("VAS.AX", tmp_path) == "Example Fund (ASX, AUD)"


def test_download_refuses_wrong_currency_symbol_or_short_history(tmp_path):
    with pytest.raises(ValueError, match="quoted in USD"):
        ticker_store.download("VAS.AX", tmp_path, fetch=fetcher("USD"))
    with pytest.raises(ValueError, match="at least 253"):
        ticker_store.download("VAS.AX", tmp_path, fetch=fetcher(history=vendor_history().iloc[:200]))
    with pytest.raises(ValueError, match="the vendor returned"):
        ticker_store.download("VAS.AX", tmp_path, fetch=lambda vendor: (vendor_history(), {"symbol": "XYZ.AX", "currency": "AUD"}, ""))
    assert ticker_store.stored_symbols(tmp_path) == ()


def test_rows_without_a_price_are_dropped_and_odd_adjustments_flagged(tmp_path):
    history = vendor_history()
    history.iloc[10, 0] = np.nan
    history.iloc[200:, 1] *= 0.97  # an adjustment with no recorded distribution
    meta = ticker_store.download("VAS.AX", tmp_path, fetch=fetcher(history=history))
    assert meta["rows"] == len(DATES) - 1 and meta["rows_without_price_dropped"] == 1
    assert meta["status_counts"]["adjustment_without_cash_event"] == 1


def test_a_changed_stored_file_is_refused(stores):
    root, tickers, _ = stores
    with open(tickers / "VAS.AX.csv", "a", encoding="utf-8") as file:
        file.write("\n")
    with pytest.raises(ValueError, match="recorded hash"):
        load_plan_markets(["VAS.AX"], root, currency="AUD", ticker_root=tickers)
    with pytest.raises(ValueError, match="has not been downloaded"):
        load_plan_markets(["VGS.AX"], root, currency="AUD", ticker_root=tickers)


def test_conversion_divides_or_multiplies_by_the_rate_on_shared_dates(stores):
    root, tickers, rate = stores
    names = ["VAS.AX", "SPY.US", "COMM"]
    aud = load_plan_markets(names, root, currency="AUD", ticker_root=tickers)
    usd = load_plan_markets(names, root, currency="USD", ticker_root=tickers)
    assert aud.path.currency == "AUD" and usd.path.currency == "USD"
    assert aud.path.dates == usd.path.dates == tuple(rate.index.date)  # the two days without a rate are absent
    step = rate.to_numpy()[1:] / rate.to_numpy()[:-1]
    # An Australian-dollar return times the rate's change is the US-dollar return, for every ticker and day.
    assert np.allclose((1 + aud.path.returns) * step[:, None], 1 + usd.path.returns, rtol=0, atol=1e-12)
    # A ticker already in the chosen currency keeps its own returns, compounded across the missing days.
    own = pd.read_csv(tickers / "VAS.AX.csv", index_col="Date")["Total Return"]
    own.index = pd.to_datetime(own.index)
    levels = (1 + own.fillna(0)).cumprod().loc[rate.index].to_numpy()
    assert np.allclose(aud.path.returns[:, 0], levels[1:] / levels[:-1] - 1, rtol=0, atol=1e-12)
    summary = aud.asset_summary.set_index("Ticker")
    assert list(summary["Quoted in"]) == ["AUD", "USD", "USD"]
    assert aud.income_yields == usd.income_yields and aud.income_yields["VAS.AX"] == pytest.approx(0.01)
    assert aud.manifest["tickers"]["SPY.US"]["dates_without_exchange_rate"] == 2
    assert "fx_aud_usd.csv" in aud.manifest["inputs_sha256"] and "tickers/VAS.AX.csv" in aud.manifest["inputs_sha256"]


def test_no_exchange_rate_is_read_when_every_ticker_is_in_the_chosen_currency(stores):
    root, tickers, _ = stores
    (root / "fx_aud_usd.csv").unlink()
    market = load_plan_markets(["SPY.US", "COMM"], root, currency="USD", ticker_root=tickers)
    assert market.manifest["conversion"].startswith("none") and len(market.path.dates) == len(DATES)
    with pytest.raises(ValueError, match="fx_aud_usd.csv"):
        load_plan_markets(["SPY.US"], root, currency="AUD", ticker_root=tickers)
    with pytest.raises(ValueError, match="AUD or USD"):
        load_plan_markets(["SPY.US"], root, currency="EUR", ticker_root=tickers)


def test_plan_currency_defaults_by_file_version_and_franking_reaches_the_ledger(stores):
    root, tickers, _ = stores
    plan = default_plan()
    assert plan["schema_version"] == 4 and plan["market"]["currency"] == "AUD" and plan["franking"] == {}
    old = {k: v for k, v in plan.items() if k != "franking"}
    old = {**old, "schema_version": 3, "market": {k: v for k, v in plan["market"].items() if k != "currency"}}
    assert normalize_plan(old)["market"]["currency"] == "USD"  # earlier files keep the returns they were run with
    with pytest.raises(PlanError, match="market.currency"):
        normalize_plan({**plan, "market": {**plan["market"], "currency": "EUR"}})
    plan["assets"] = ["VAS.AX", "COMM"]
    plan["outside"]["weights"] = {"VAS.AX": 0.5, "COMM": 0.5}
    plan["super"]["weights"] = {"VAS.AX": 1.0}
    plan["franking"] = {"VAS.AX": 0.8, "COMM": 0.0}
    with pytest.raises(PlanError, match="franking.SPY.US"):
        normalize_plan({**plan, "franking": {"SPY.US": 0.5}})
    with pytest.raises(PlanError, match="from 0 to 1"):
        normalize_plan({**plan, "franking": {"VAS.AX": 1.5}})
    text = plan_to_toml(plan)
    assert 'franking = {"VAS.AX" = 0.8}' in text and 'currency = "AUD"' in text
    market = load_plan_markets(plan["assets"], root, currency="AUD", ticker_root=tickers)
    scenario = build_inputs(plan, market=market)[1]
    assert scenario.income["VAS.AX"].franked_fraction == 0.8 and scenario.income["COMM"].franked_fraction == 0.0
