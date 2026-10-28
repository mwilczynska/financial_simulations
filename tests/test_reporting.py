from datetime import date
from html.parser import HTMLParser
import json

import numpy as np
import pandas as pd
import pytest

from financial_simulations.cli import main
from financial_simulations.markets.path import MarketPath
from financial_simulations.portfolios.engine import CashFlow, simulate_portfolio
from financial_simulations.portfolios.spec import PortfolioSpec
from financial_simulations.reporting.baseline import period_summary, summary_statistics
from financial_simulations.scenario import load_scenario


def test_periods_reconcile_to_daily_values_and_flows():
    market = MarketPath((date(2020, 1, 30), date(2020, 1, 31), date(2020, 2, 3)),
                         ("GLSTOCK",), np.array([[0.1], [-0.1]]))
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100,
                                [CashFlow(date(2020, 1, 31), 10)])
    monthly = period_summary(result, "monthly")
    assert monthly["closing_value"].tolist() == pytest.approx([120, 108])
    assert monthly["time_weighted_return"].tolist() == pytest.approx([0.1, -0.1])
    assert monthly["partial_period"].all()
    annual = period_summary(result, "annual")
    assert annual["time_weighted_return"].iloc[0] == pytest.approx(-0.01)
    assert annual["market_pnl"].iloc[0] == pytest.approx(-2)
    assert summary_statistics(result)["final_value"] == pytest.approx(108)
    assert summary_statistics(result)["max_time_weighted_drawdown"] == pytest.approx(-0.1)


def test_annualisation_uses_opening_date_and_elapsed_calendar_days():
    dates = tuple(t.date() for t in pd.date_range("2020-01-01", "2021-01-01", freq="B"))
    returns = np.zeros((len(dates) - 1, 1))
    returns[-1, 0] = 0.1
    market = MarketPath(dates, ("GLSTOCK",), returns)
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100)
    stats = summary_statistics(result)
    assert stats["annualised_time_weighted_return"] == pytest.approx(1.1 ** (365.25 / 366) - 1)
    assert period_summary(result, "annual")["partial_period"].tolist() == [False, True]


def test_short_period_annualisation_overflow_does_not_lose_valid_results():
    market = MarketPath((date(2020, 1, 2), date(2020, 1, 3)), ("GLSTOCK",), [[10.0]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100)
    stats = summary_statistics(result)
    assert stats["final_value"] == 1100
    assert stats["time_weighted_return"] == 10
    assert stats["annualised_time_weighted_return"] is None
    assert stats["annualised_return_status"] == "not_representable"
    assert json.loads(json.dumps(stats, allow_nan=False))["final_value"] == 1100


def test_cli_produces_portable_inspectable_artifacts(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    (data / "global_stocks.csv").write_text(
        "Date,Adj Close,Total Return,Source,Quality Flag,Source Notes\n"
        "2020-01-02,100,,synthetic,synthetic,hand calculation\n"
        "2020-01-03,110,0.1,synthetic,synthetic,hand calculation\n"
        "2020-01-06,99,-0.1,synthetic,synthetic,hand calculation\n", encoding="utf-8")
    config = tmp_path / "example.toml"
    config.write_text('''[run]
name = "Example <script>"
start = "2020-01-01"
end = "2020-01-06"
initial_value = 100.0
currency = "USD"
rebalance = "annual"
[data]
root = "data"
[portfolio.weights]
GLSTOCK = 1.0
''', encoding="utf-8")
    output = tmp_path / "report"
    assert main(["run", str(config), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["final_value"] == pytest.approx(99)
    for name in ("report.html", "daily.csv", "market_returns.csv", "source_observations.csv",
                 "monthly.csv", "annual.csv", "manifest.json", "wealth.png", "drawdown.png", "allocation.png"):
        assert (output / name).is_file()
    from PIL import Image
    for name in ("wealth.png", "drawdown.png", "allocation.png"):
        with Image.open(output / name) as image:
            assert image.format == "PNG"
            assert image.width >= 1200
            assert image.height >= 600
            assert np.asarray(image).std() > 1
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["return_observations"] == 2
    assert manifest["scenario"]["weights"] == {"GLSTOCK": 1}
    assert "Example &lt;script&gt;" in (output / "report.html").read_text(encoding="utf-8")
    html = (output / "report.html").read_text(encoding="utf-8")
    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                assert (output / dict(attrs)["href"]).is_file()
    Links().feed(html)
    assert not list(output.glob("*.pdf"))
    assert len(pd.read_csv(output / "market_returns.csv")) == 2
    assert len(pd.read_csv(output / "daily.csv")) == 5
    config.write_text(config.read_text(encoding="utf-8").replace('rebalance = "annual"',
                      'rebalance = "annual"\nadditional_fee = 0.01'), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown keys"):
        load_scenario(config)


def test_no_cash_flow_is_mistaken_for_investment_return():
    market = MarketPath((date(2020, 1, 2), date(2020, 1, 3)), ("GLSTOCK",), [[0]])
    result = simulate_portfolio(market, PortfolioSpec({"GLSTOCK": 1}), 100,
                                [CashFlow(date(2020, 1, 3), 1000)])
    stats = summary_statistics(result)
    assert stats["final_value"] == 1100
    assert stats["time_weighted_return"] == 0
    assert period_summary(result, "monthly")["market_pnl"].iloc[0] == 0
