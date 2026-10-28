from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from financial_simulations.data.registry import resolve_asset
from financial_simulations.markets.parametric import fit_lognormal
from financial_simulations.markets.resampling import Sampler, historical_draw, sample_indices
from financial_simulations.markets.path import MarketPath
from financial_simulations.portfolios.engine import simulate_portfolio
from financial_simulations.studies import (holdout_summary, load_holdout, load_paired, pit, run_holdout,
                                           run_paired, series_statistics)


SPLICE = "2001-01-02"


def write_data(root, seed=0, perturb_after=None):
    """Three assets on business days; GOLDPM misses some dates; model flags before the splice."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2000-01-03", "2002-12-31")
    for asset, scale in (("GLSTOCK", 0.012), ("GLBOND", 0.004), ("GOLDPM", 0.009)):
        keep = np.ones(len(dates), dtype=bool)
        if asset == "GOLDPM":
            keep[rng.choice(np.arange(1, len(dates) - 1), 12, replace=False)] = False
        own = dates[keep]
        returns = rng.standard_t(5, len(own) - 1) * scale
        if perturb_after:
            returns[own[1:] >= pd.Timestamp(perturb_after)] *= -3
        levels = 100 * np.r_[1, np.cumprod(1 + returns)]
        flags = np.where(own < pd.Timestamp(SPLICE), "model_fixture", "observed_fixture")
        pd.DataFrame({"Date": own.strftime("%Y-%m-%d"), "Adj Close": levels, "Total Return": [np.nan, *(levels[1:] / levels[:-1] - 1)],
                      "Source": "synthetic", "Quality Flag": flags, "Source Notes": "test only"}).to_csv(
                          root / resolve_asset(asset).filename, index=False, lineterminator="\n")


COMMON = '''[study]
name = "Synthetic study"
initial_value = 1000.0
currency = "USD"
reference = "balanced"
[data]
root = "."
calendar_policy = "common_dates"
[[portfolios]]
name = "balanced"
rebalance = "annual"
weights = {GLSTOCK = 0.6, GLBOND = 0.4}
[[portfolios]]
name = "with gold"
rebalance = "buy_and_hold"
weights = {GLSTOCK = 0.5, GLBOND = 0.3, GOLDPM = 0.2}
'''


def paired_study(tmp_path, methods='["historical_replay", "stationary", "lognormal", "garch_fhs"]', batch=8):
    write_data(tmp_path)
    path = tmp_path / "paired.toml"
    path.write_text(COMMON + f'''[generators]
methods = {methods}
block_length = 5
paths = 12
seeds = [11]
batch_size = {batch}
observations_per_year = 252
diagnostic_paths = 6
[paired]
horizons = [20, 60]
calendar_window = "full"
[[windows]]
name = "full"
start = "2000-01-01"
end = "2002-12-31"
[[windows]]
name = "observed"
start = "{SPLICE}"
end = "2002-12-31"
provenance = "observed"
''', encoding="utf-8")
    return load_paired(path)


def test_paired_portfolios_share_draws_and_reconcile_through_the_full_ledger(tmp_path):
    study = paired_study(tmp_path)
    manifest = run_paired(study, tmp_path / "out")
    outcomes = pd.read_csv(tmp_path / "out" / "paired_outcomes.csv")
    summary = pd.read_csv(tmp_path / "out" / "paired_summary.csv")
    cases = summary.drop_duplicates("case_id").set_index("case_id")
    target = tuple(pd.to_datetime(pd.read_csv(tmp_path / "out" / "target_calendar.csv")["Date"]).dt.date)
    checked = set()
    for case_id, case in cases.iterrows():
        if case["status"] != "ok":
            continue
        window = next(w for w in study.windows if w["name"] == case["window"])
        source = study.base.load(window["start"], window["end"]).path
        horizon, n = int(case["horizon_observations"]), len(source.returns)
        for path_id in (0, int(case["paths"]) - 1):
            if case["method"] == "historical_replay":
                returns = source.returns[historical_draw(n, horizon, path_id).indices]
            elif case["method"] == "stationary":
                returns = source.returns[sample_indices(n, horizon, Sampler("stationary", 5), seed=11, path_id=path_id).indices]
            elif case["method"] == "lognormal":
                returns = fit_lognormal(source).draw(horizon, seed=11, path_id=path_id)
            else:
                continue
            row = outcomes[(outcomes["case_id"] == case_id) & (outcomes["path_id"] == path_id)].iloc[0]
            for portfolio in study.base.portfolios:
                columns = [source.assets.index(a) for a in portfolio.spec.assets]
                path = MarketPath(target[:horizon + 1], portfolio.spec.assets, returns[:, columns])
                ledger = simulate_portfolio(path, portfolio.spec, 1000.0).daily
                assert row[f"terminal__{portfolio.name}"] == pytest.approx(ledger["value"].iloc[-1], rel=1e-11)
            checked.add(case["method"])
    assert checked == {"historical_replay", "stationary", "lognormal"}
    differences = pd.read_csv(tmp_path / "out" / "paired_differences.csv")
    for _, row in differences.iterrows():
        case = outcomes[outcomes["case_id"] == row["case_id"]]
        wins = (case["terminal__with gold"] > case["terminal__balanced"]).mean()
        assert row["fraction_outperforms_reference"] == pytest.approx(wins)
        if row["method"] == "historical_replay":
            assert np.isnan(row["outperform_ci_low"])
        else:
            assert row["outperform_ci_low"] <= wins <= row["outperform_ci_high"]
    statistics = pd.read_csv(tmp_path / "out" / "window_statistics.csv")
    observed = statistics[statistics["window"] == "observed"]
    assert (observed["intervals_reconstructed"] == 0).all() and (observed["intervals_mixed"] == 0).all()
    assert statistics.loc[statistics["asset"] == "GLSTOCK", "multi_observation_intervals"].max() > 0
    diagnostics = pd.read_csv(tmp_path / "out" / "tail_diagnostics.csv")
    assert {"historical", "stationary", "lognormal", "garch_fhs"} == set(diagnostics["method"])
    assert manifest["paths_evaluated"] == len(outcomes)
    for name in ("paired_terminal", "paired_differences", "segment_statistics", "tail_diagnostics"):
        assert (tmp_path / "out" / f"{name}.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not list((tmp_path / "out").glob("*.pdf"))


def test_paired_outputs_do_not_depend_on_batch_size(tmp_path):
    study = paired_study(tmp_path)
    run_paired(study, tmp_path / "a")
    run_paired(replace(study, base=replace(study.base, generators=replace(study.base.generators, batch_size=1))), tmp_path / "b")
    for name in ("paired_outcomes.csv", "paired_summary.csv", "paired_differences.csv", "tail_diagnostics.csv"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_window_provenance_requirements_are_enforced(tmp_path):
    study = paired_study(tmp_path, methods='["stationary"]')
    windows = list(study.windows)
    windows[0] = {**windows[0], "provenance": "observed"}
    with pytest.raises(ValueError, match="not observed"):
        run_paired(replace(study, windows=tuple(windows)), tmp_path / "bad")
    windows[0] = {**windows[0], "end": "2000-12-29", "provenance": "reconstructed", "provenance_assets": ["GLSTOCK"]}
    run_paired(replace(study, windows=tuple(windows), calendar_window=windows[0]["name"]), tmp_path / "ok")


def holdout_study(tmp_path, root_seed=0, perturb_after=None):
    write_data(tmp_path, root_seed, perturb_after)
    path = tmp_path / "holdout.toml"
    path.write_text(COMMON + '''[generators]
methods = ["stationary", "lognormal", "garch_fhs"]
block_length = 5
paths = 16
seeds = [5]
batch_size = 16
observations_per_year = 252
initial_variance = "last_fitted"
[holdout]
horizons = [63, 300]
data_start = "2000-01-01"
data_end = "2002-12-31"
calibration_years = 1
mode = "rolling"
first_origin_year = 2001
step_years = 1
''', encoding="utf-8")
    return load_holdout(path)


def test_holdout_scores_realised_paths_without_using_future_data(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir(), second.mkdir()
    manifest = run_holdout(holdout_study(first), first / "out")
    # Changing returns after mid-2001 must not change the 2001 origin's 63-observation fold.
    run_holdout(holdout_study(second, perturb_after="2001-07-02"), second / "out")
    folds_a = pd.read_csv(first / "out" / "holdout_folds.csv")
    folds_b = pd.read_csv(second / "out" / "holdout_folds.csv")
    key = (folds_a["origin_year"] == 2001) & (folds_a["horizon_observations"] == 63)
    pd.testing.assert_frame_equal(folds_a[key].reset_index(drop=True), folds_b[key].reset_index(drop=True))
    later = (folds_a["origin_year"] == 2002) & (folds_a["status"] == "ok")
    assert not folds_a.loc[later, "realised_terminal"].equals(folds_b.loc[later, "realised_terminal"])
    assert manifest["scored_folds"] == 3 and manifest["incomplete_folds"] == 1
    assert folds_a.loc[(folds_a["origin_year"] == 2002) & (folds_a["horizon_observations"] == 300), "status"].iloc[0] == "incomplete_holdout"
    generated = pd.read_csv(first / "out" / "holdout_generated.csv")
    study = holdout_study(first)
    full = study.base.load(study.data_start, study.data_end).path
    for _, fold in folds_a[folds_a["status"] == "ok"].iterrows():
        values = generated[(generated["origin_date"] == fold["origin_date"]) & (generated["method"] == fold["method"])
                           & (generated["portfolio"] == fold["portfolio"]) & (generated["horizon_observations"] == fold["horizon_observations"])]
        assert len(values) == 16
        for metric in ("terminal", "max_drawdown", "realised_volatility"):
            assert fold[f"pit_{metric}"] == pytest.approx(pit(values[metric], fold[f"realised_{metric}"]))
        o = full.dates.index(pd.Timestamp(fold["origin_date"]).date())
        h = int(fold["horizon_observations"])
        portfolio = next(p for p in study.base.portfolios if p.name == fold["portfolio"])
        columns = [full.assets.index(a) for a in portfolio.spec.assets]
        ledger = simulate_portfolio(MarketPath(full.dates[o:o + h + 1], portfolio.spec.assets, full.returns[o:o + h, columns]),
                                    portfolio.spec, 1000.0).daily
        assert fold["realised_terminal"] == pytest.approx(ledger["value"].iloc[-1], rel=1e-11)
        if fold["origin_year"] == 2001:
            assert fold["calibration_start"] == "2000-01-03"
    summary = pd.read_csv(first / "out" / "holdout_summary.csv")
    assert set(summary["metric"]) == {"terminal", "max_drawdown", "realised_volatility"}
    for name in ("holdout_pit", "holdout_timeline"):
        assert (first / "out" / f"{name}.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_pit_summary_and_series_statistics_by_hand():
    assert pit([1, 2, 3, 4], 3) == pytest.approx(2.5 / 4)
    assert pit([1, 2], np.nan) is None
    folds = pd.DataFrame({"status": "ok", "horizon_observations": 252, "method": "m", "portfolio": "p",
                          "origin_year": [2000, 2001, 2002, 2003], "pit_terminal": [0.01, 0.5, 0.6, 0.99],
                          "pit_max_drawdown": np.nan, "pit_realised_volatility": np.nan})

    class Study:
        step_years = 1
        base = type("B", (), {"generators": type("G", (), {"observations_per_year": 252})})

    row = holdout_summary(folds, Study).iloc[0]
    assert row["central_90_coverage"] == 0.5 and row["fraction_pit_below_0_05"] == 0.25
    assert row["ks_distance_from_uniform"] == pytest.approx(0.25)
    stats = series_statistics(np.array([[0.01, -0.01, 0.01, -0.01]]), 252)
    assert stats["excess_kurtosis"] == pytest.approx(-2.0)
    assert stats["annual_volatility"] == pytest.approx(0.01 * np.sqrt(252))


@pytest.mark.parametrize("change, match", [
    (lambda s: s.replace('reference = "balanced"', 'reference = "missing"'), "reference"),
    (lambda s: s.replace('methods = ["stationary", "lognormal", "garch_fhs"]', 'methods = ["historical_replay"]'), "realised path"),
    (lambda s: s.replace("first_origin_year = 2001", "first_origin_year = 2000"), "calibration_years"),
    (lambda s: s.replace('mode = "rolling"', 'mode = "anchored"'), "rolling or expanding"),
])
def test_holdout_configuration_errors(tmp_path, change, match):
    holdout_study(tmp_path)
    path = tmp_path / "holdout.toml"
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_holdout(path)
