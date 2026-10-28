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


def test_evaluation_reports_are_exact_and_do_not_change_market_paths(tmp_path):
    from financial_simulations.evaluation import EvaluationSettings, drawdown_statistics

    config = fixture(tmp_path)
    plain = tmp_path / "plain"
    run_comparison(config, plain)
    evaluated = replace(config, evaluation=EvaluationSettings("nominal", 1.0, 0.0, 0.95, 8))
    first, second = tmp_path / "evaluated", tmp_path / "evaluated-small"
    manifest = run_comparison(evaluated, first)
    run_comparison(replace(evaluated, batch_size=1), second)
    assert manifest["model"] == "stage_1d_evaluation_v1"
    assert manifest["evaluation_cases"] == 15  # One unavailable replay case stays unavailable.
    for filename in ("wealth_percentiles.csv", "risk_summary.csv", "outcomes.csv"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    old = pd.read_csv(plain / "outcomes.csv")
    outcomes = pd.read_csv(first / "outcomes.csv")
    pd.testing.assert_frame_equal(old, outcomes[old.columns])
    summary = pd.read_csv(first / "summary.csv")
    series = pd.read_csv(first / "wealth_percentiles.csv")
    risks = pd.read_csv(first / "risk_summary.csv")
    for _, case in summary[summary["status"] == "ok"].iterrows():
        final = series[series["case_id"] == case["case_id"]].iloc[-1]
        assert final["nominal_median"] == pytest.approx(case["terminal_median"])
        risk = risks[risks["case_id"] == case["case_id"]].iloc[0]
        paths = outcomes[outcomes["case_id"] == case["case_id"]]
        assert risk["misses"] == int((paths["terminal_value"] < 100).sum())
        assert risk["fraction_below_target"] == pytest.approx(case["fraction_terminal_below_initial"])
        if case["method"] == "historical_replay":
            assert pd.isna(risk["fraction_ci_low"]) and pd.isna(risk["terminal_mean_mcse"])
        else:
            assert risk["fraction_ci_low"] <= risk["fraction_below_target"] <= risk["fraction_ci_high"]
    traces = pd.read_csv(first / "traces.csv")
    for (case_id, path_id), trace in traces.groupby(["case_id", "path_id"]):
        stats = drawdown_statistics([trace["value"].to_numpy()], trace["target_date"])
        row = outcomes[(outcomes["case_id"] == case_id) & (outcomes["path_id"] == path_id)].iloc[0]
        assert row["nominal_max_drawdown"] == pytest.approx(stats["max_drawdown"][0])
        assert row["nominal_max_drawdown_recovery_status"] == stats["max_drawdown_recovery_status"][0]
    from PIL import Image
    for filename in ("wealth_percentiles_nominal.png", "terminal_distribution.png", "target_shortfall.png", "drawdown_recovery.png"):
        with Image.open(first / filename) as image:
            assert image.format == "PNG"
    assert not list(first.glob("*.pdf"))


def test_real_calendar_evaluation_reconciles_to_full_daily_ledger(tmp_path):
    from financial_simulations.evaluation import drawdown_statistics
    from financial_simulations.markets.assumptions import assumed_price_index

    fixture(tmp_path)
    experiment = tmp_path / "experiment.toml"
    original = experiment.read_text(encoding="utf-8")
    original = original.replace('batch_size = 3', 'batch_size = 3\ncalendar_file = "calendar.csv"')
    pd.DataFrame({"Date": ["2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]}).to_csv(tmp_path / "calendar.csv", index=False)
    experiment.write_text(original + '''
[parametric]
observations_per_year = 252
reference_inflation = 0.02
trace_assumption = "base"
[[assumptions]]
name = "base"
mean_convention = "geometric_growth"
inflation_annual = 0.04
rationale = "Synthetic real evaluation"
annual_returns = {GLSTOCK = 0.05, GLBOND = 0.02}
[evaluation]
target_basis = "real"
target_multiple = 1.0
target_annual_growth = 0.0
confidence = 0.95
max_panel_mb = 8
''', encoding="utf-8")
    config = load_comparison(experiment)
    output = tmp_path / "real-evaluation"
    manifest = run_comparison(config, output)
    assert manifest["paths_evaluated"] == 71
    scenario = load_scenario(config.scenario_file)
    summary = pd.read_csv(output / "summary.csv").set_index("case_id")
    traces = pd.read_csv(output / "traces.csv")
    outcomes = pd.read_csv(output / "outcomes.csv").set_index(["case_id", "path_id"])
    for (case_id, path_id), group in traces.groupby(["case_id", "path_id"]):
        target = tuple(t.date() for t in pd.to_datetime(group["target_date"]))
        returns = group[[f"return_{a}" for a in scenario.portfolio.assets]].iloc[1:].to_numpy()
        ledger = simulate_portfolio(MarketPath(target, scenario.portfolio.assets, returns), scenario.portfolio, 100).daily
        dates = tuple(ledger.index.date)
        real = ledger["value"].to_numpy() / assumed_price_index(dates, summary.loc[case_id, "inflation_annual"])
        expected = drawdown_statistics([real], dates)
        row = outcomes.loc[(case_id, path_id)]
        assert row["real_max_drawdown"] == pytest.approx(expected["max_drawdown"][0])
        assert row["real_max_drawdown_observed_duration_days"] == expected["max_drawdown_observed_duration_days"][0]
        assert row["real_max_drawdown_recovery_status"] == expected["max_drawdown_recovery_status"][0]
    series = pd.read_csv(output / "wealth_percentiles.csv")
    for _, group in series.groupby("case_id"):
        assert list(group["is_observation"].iloc[:4]) == [True, False, False, True]
        assert group["nominal_median"].iloc[0] == group["nominal_median"].iloc[2]
        assert group["real_median"].iloc[0] > group["real_median"].iloc[2]
    risks = pd.read_csv(output / "risk_summary.csv")
    for _, risk in risks.iterrows():
        assert risk["fraction_below_target"] == pytest.approx(summary.loc[risk["case_id"], "fraction_real_terminal_below_initial"])
    assert (output / "wealth_percentiles_real.png").is_file()


def test_garch_cases_share_shocks_reconcile_and_label_deflator_twins(tmp_path):
    from financial_simulations.reporting.comparison import _label

    fixture(tmp_path)
    experiment = tmp_path / "experiment.toml"
    grid = '''
[parametric]
observations_per_year = 252
reference_inflation = 0.02
trace_assumption = "base"
[volatility]
model = "garch_fhs"
[[assumptions]]
name = "base"
mean_convention = "geometric_growth"
inflation_annual = 0.02
rationale = "Synthetic base"
annual_returns = {GLSTOCK = 0.08, GLBOND = 0.03}
[[assumptions]]
name = "high_inflation"
mean_convention = "geometric_growth"
inflation_annual = 0.04
rationale = "Same nominal inputs"
annual_returns = {GLSTOCK = 0.08, GLBOND = 0.03}
'''
    experiment.write_text(experiment.read_text(encoding="utf-8") + grid, encoding="utf-8")
    config = load_comparison(experiment)
    first, second = tmp_path / "garch", tmp_path / "garch-other"
    manifest = run_comparison(config, first)
    run_comparison(replace(config, batch_size=1), second)
    assert manifest["model"] == "stage_1c_joint_daily_garch_fhs_v1"
    for filename in ("summary.csv", "outcomes.csv", "traces.csv", "calibration.json"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    summary = pd.read_csv(first / "summary.csv")
    garch = summary[summary["method"] == "garch_fhs"]
    assert len(garch) and set(garch["nominal_paths_match"].dropna()) == {"base"}
    twin = garch[garch["assumption"] == "high_inflation"].iloc[0]
    assert _label(twin) == "GARCH-FHS: high inflation (deflator only)"
    outcomes = pd.read_csv(first / "outcomes.csv").merge(summary, on="case_id")
    for _, group in outcomes[outcomes["method"] == "garch_fhs"].groupby(["window", "horizon_observations", "path_id"]):
        assert group["terminal_value"].nunique() == 1
    traces = pd.read_csv(first / "traces.csv")
    scenario = load_scenario(config.scenario_file)
    garch_traces = traces[traces["method"] == "garch_fhs"]
    assert len(garch_traces) and garch_traces["donor_index"].isna().all()
    for _, trace in garch_traces.groupby(["case_id", "path_id"]):
        target = tuple(t.date() for t in pd.to_datetime(trace["target_date"]))
        returns = trace[[f"return_{a}" for a in scenario.portfolio.assets]].iloc[1:].to_numpy()
        ledger = simulate_portfolio(MarketPath(target, scenario.portfolio.assets, returns), scenario.portfolio, 100)
        np.testing.assert_allclose(ledger.daily.loc[pd.to_datetime(target), "value"], trace["value"], atol=1e-12)
    calibration = json.loads((first / "calibration.json").read_text(encoding="utf-8"))
    assert calibration[0]["garch_fhs"]["model"] == "garch11_variance_targeted_fhs_v1"
    bad = experiment.read_text(encoding="utf-8").replace('mean_convention = "geometric_growth"\ninflation_annual = 0.04',
                                                           'mean_convention = "expected_compounded_return"\ninflation_annual = 0.04')
    experiment.write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError, match="historical or geometric_growth"):
        load_comparison(experiment)
