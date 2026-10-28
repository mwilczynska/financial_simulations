from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from financial_simulations.comparison import autocorrelation, load_comparison, run_comparison
from financial_simulations.data.datasets import load_datasets
from financial_simulations.portfolios.engine import simulate_portfolio
from financial_simulations.markets.path import MarketPath
from financial_simulations.scenario import load_scenario


def fixture(tmp_path):
    dates = pd.date_range("2020-01-02", periods=6)
    for name, returns in (("global_stocks", [0.1, -0.1, 0.05, 0, 0.02]),
                           ("global_bonds", [-0.05, 0.02, 0, 0.01, 0.01])):
        levels = 100 * np.r_[1, np.cumprod(1 + np.array(returns))]
        pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "Adj Close": levels,
                      "Total Return": [np.nan, *returns], "Source": "synthetic",
                      "Quality Flag": "synthetic", "Source Notes": "test only"}).to_csv(
                          tmp_path / f"{name}.csv", index=False, lineterminator="\n")
    (tmp_path / "scenario.toml").write_text('''[run]
name = "Synthetic comparison"
start = "2020-01-01"
end = "2020-01-08"
initial_value = 100.0
currency = "USD"
rebalance = "annual"
[data]
root = "."
[portfolio.weights]
GLSTOCK = 0.5
GLBOND = 0.5
''', encoding="utf-8")
    experiment = tmp_path / "experiment.toml"
    experiment.write_text('''[comparison]
scenario = "scenario.toml"
horizons = [2, 5]
paths = 4
seeds = [1729]
block_lengths = [2]
trace_horizon = 2
trace_block_length = 2
batch_size = 3
[[calibration]]
name = "full"
start = "2020-01-01"
end = "2020-01-08"
[[calibration]]
name = "short"
start = "2020-01-04"
end = "2020-01-08"
''', encoding="utf-8")
    return load_comparison(experiment)


def test_complete_comparison_batch_invariance_and_trace_reconstruction(tmp_path):
    config = fixture(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    manifest = run_comparison(config, first)
    other = run_comparison(replace(config, batch_size=1), second)
    assert other["effective_settings"]["batch_size"] == 1
    assert manifest["paths_evaluated"] == 55
    assert manifest["cases"] == 16
    for filename in ("summary.csv", "outcomes.csv", "traces.csv", "dependence.csv", "correlations.csv"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    summary = pd.read_csv(first / "summary.csv")
    no_replay = summary[(summary["window"] == "short") & (summary["method"] == "historical_replay")
                        & (summary["horizon_observations"] == 5)].iloc[0]
    assert no_replay["status"] == "no_complete_window"
    assert no_replay["paths"] == 0
    assert pd.isna(no_replay["terminal_median"])
    scenario = load_scenario(config.scenario_file)
    source = load_datasets(tmp_path, scenario.portfolio.assets, scenario.start, scenario.end).path
    traces = pd.read_csv(first / "traces.csv")
    for _, trace in traces.groupby(["case_id", "path_id"]):
        indices = trace["donor_index"].iloc[1:].to_numpy(dtype=int)
        target = tuple(t.date() for t in pd.to_datetime(trace["target_date"]))
        market = MarketPath(target, source.assets, source.returns[indices])
        result = simulate_portfolio(market, scenario.portfolio, 100)
        np.testing.assert_allclose(result.daily.loc[pd.to_datetime(target), "value"], trace["value"], atol=1e-12)
    from PIL import Image
    for name in ("terminal_wealth.png", "sample_paths.png", "dependence.png"):
        with Image.open(first / name) as image:
            assert image.format == "PNG" and image.width > 800
    assert not list(first.glob("*.pdf"))
    json.loads((first / "manifest.json").read_text(encoding="utf-8"))


def test_target_calendar_is_required_for_horizon_beyond_template(tmp_path):
    config = fixture(tmp_path)
    with pytest.raises(ValueError, match="Target calendar"):
        run_comparison(replace(config, horizons=(2, 8)), tmp_path / "bad")
    calendar = tmp_path / "future.csv"
    pd.DataFrame({"Date": pd.date_range("2027-01-04", periods=9).strftime("%Y-%m-%d")}).to_csv(calendar, index=False)
    result = run_comparison(replace(config, horizons=(2, 8), calendar_file=calendar), tmp_path / "future")
    assert result["calendar"]["policy"] == "explicit_user_target_dates"
    assert result["paths_evaluated"] == 54


def test_invalid_experiment_and_undefined_dependence(tmp_path):
    fixture(tmp_path)
    experiment = tmp_path / "experiment.toml"
    original = experiment.read_text(encoding="utf-8")
    for before, after in (("paths = 4", "paths = true"), ("seeds = [1729]", "seeds = [1, 1]"),
                          ("trace_horizon = 2", "trace_horizon = 9")):
        experiment.write_text(original.replace(before, after), encoding="utf-8")
        with pytest.raises(ValueError):
            load_comparison(experiment)
    assert autocorrelation([1, 1, 1, 1], 1) is None
    assert autocorrelation([1, 2], 1) is None
    assert autocorrelation(np.arange(10), 1) == pytest.approx(1)


def test_block_sampling_preserves_synthetic_serial_pattern_that_iid_breaks():
    from financial_simulations.markets.resampling import Sampler, sample_indices

    source = np.tile([0.02, -0.02], 1000)
    iid = sample_indices(len(source), 30000, Sampler("independent"), seed=42, path_id=0)
    assert abs(autocorrelation(source[iid.indices], 1)) < 0.03
    for method in ("moving_block", "stationary"):
        draw = sample_indices(len(source), 30000, Sampler(method, 20), seed=42, path_id=0)
        assert autocorrelation(source[draw.indices], 1) < -0.90


def test_parametric_grid_pairing_reconstruction_and_batch_invariance(tmp_path):
    from financial_simulations.markets.assumptions import assumed_price_index

    fixture(tmp_path)
    experiment = tmp_path / "experiment.toml"
    grid = '''
[parametric]
observations_per_year = 252
reference_inflation = 0.02
trace_assumption = "base"
[[assumptions]]
name = "historical"
mean_convention = "historical"
inflation_annual = 0.02
rationale = "Synthetic fitted benchmark"
[[assumptions]]
name = "base"
mean_convention = "expected_compounded_return"
inflation_annual = 0.02
rationale = "Synthetic base"
annual_returns = {GLSTOCK = 0.08, GLBOND = 0.03}
[[assumptions]]
name = "high_inflation"
mean_convention = "expected_compounded_return"
inflation_annual = 0.04
rationale = "Same nominal inputs, different assumed purchasing power"
annual_returns = {GLSTOCK = 0.08, GLBOND = 0.03}
'''
    experiment.write_text(experiment.read_text(encoding="utf-8") + grid, encoding="utf-8")
    config = load_comparison(experiment)
    first, second = tmp_path / "parametric", tmp_path / "parametric-other"
    manifest = run_comparison(config, first)
    run_comparison(replace(config, batch_size=1), second)
    assert manifest["model"] == "stage_1c_joint_daily_v1"
    assert manifest["cases"] == 28 and manifest["paths_evaluated"] == 103
    for filename in ("summary.csv", "outcomes.csv", "traces.csv", "calibration.json"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    summary = pd.read_csv(first / "summary.csv")
    outcomes = pd.read_csv(first / "outcomes.csv").merge(summary, on="case_id", suffixes=("", "_summary"))
    gaussian = outcomes[outcomes["method"] == "lognormal"]
    for _, group in gaussian.groupby(["window", "horizon_observations", "seed", "path_id"]):
        group = group.set_index("assumption")
        assert group.loc["base", "terminal_value"] == group.loc["high_inflation", "terminal_value"]
        assert group.loc["base", "real_terminal_value"] > group.loc["high_inflation", "real_terminal_value"]
        dates = tuple(pd.to_datetime(group.loc["base", ["target_opening", "target_end"]]).dt.date)
        ratio = assumed_price_index(dates, 0.02)[-1] / assumed_price_index(dates, 0.04)[-1]
        assert group.loc["high_inflation", "real_terminal_value"] == pytest.approx(group.loc["base", "real_terminal_value"] * ratio)
    scenario = load_scenario(config.scenario_file)
    traces = pd.read_csv(first / "traces.csv")
    for _, trace in traces.groupby(["case_id", "path_id"]):
        target = tuple(t.date() for t in pd.to_datetime(trace["target_date"]))
        returns = trace[[f"return_{a}" for a in scenario.portfolio.assets]].iloc[1:].to_numpy()
        ledger = simulate_portfolio(MarketPath(target, scenario.portfolio.assets, returns), scenario.portfolio, 100)
        np.testing.assert_allclose(ledger.daily.loc[pd.to_datetime(target), "value"], trace["value"], atol=1e-12)
        if trace["method"].iloc[0] == "lognormal":
            assert trace["donor_index"].isna().all()
            assert trace["source_date"].isna().all()
        np.testing.assert_allclose(trace["real_value"], trace["value"] / trace["price_index"])
    from PIL import Image
    with Image.open(first / "terminal_purchasing_power.png") as image:
        assert image.format == "PNG"
    assert not list(first.glob("*.pdf"))
