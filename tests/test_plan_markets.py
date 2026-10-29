import pytest

from financial_simulations.data.plan_markets import load_plan_markets, ticker_name


def test_custom_ticker_full_sample_and_common_dates(processed_fixture):
    market = load_plan_markets(["USLCAP3x", "ITT3x"], processed_fixture)
    assert market.path.currency == "USD"
    assert market.path.assets == ("USLCAP3x", "ITT3x")
    assert market.manifest["dropped_dates"]["USLCAP3x"] == 1
    assert market.manifest["common_returns"] == len(market.path.dates) - 1
    assert market.asset_summary.loc[0, "Full-sample CAGR"] > 0
    assert market.income_yields["USLCAP3x"] > 0
    assert "distributions/us_large_cap_3x_sp500.csv" in market.manifest["inputs_sha256"]
    assert ticker_name("CMDTY") == "COMM"
    with pytest.raises(ValueError, match="unavailable"):
        ticker_name("SPY")


def test_observed_fund_ticker_uses_its_own_shorter_history(processed_fixture):
    market = load_plan_markets(["BND", "USLCAP3x"], processed_fixture)
    row = market.asset_summary.set_index("Ticker").loc["BND"]
    assert row["Source"] == "observed fund vendor history"
    assert row["Complete income years"] == 2
    assert market.income_yields["BND"] > 0
    assert market.manifest["common_first"] == "2020-01-01"
    assert market.path.returns.shape[1] == 2
