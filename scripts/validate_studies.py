"""Audit Stage 1D studies and the batched cash-flow engine against the full daily ledger.

Runs (or with --reuse, reads) the paired and holdout studies, then independently
regenerates sampled paths through public generator functions and the
single-path ledger, recomputes summaries and PIT values, and reconciles
batched cash-flow accounting on bootstrapped companion data.
"""

import argparse
from datetime import date
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from financial_simulations import studies
from financial_simulations.data.datasets import load_datasets
from financial_simulations.markets.parametric import fit_lognormal
from financial_simulations.markets.path import MarketPath
from financial_simulations.markets.resampling import Sampler, historical_draw, sample_indices
from financial_simulations.portfolios.batch import simulate_paths
from financial_simulations.portfolios.engine import CashFlow, simulate_portfolio
from financial_simulations.runner import code_manifest
from financial_simulations.scenario import load_scenario


def regenerate(method, source, settings, horizon, seed, path_id, garch=None, lognormal=None):
    n = len(source.returns)
    if method == "historical_replay":
        return source.returns[historical_draw(n, horizon, path_id).indices]
    if method in ("independent", "moving_block", "stationary"):
        sampler = Sampler(method, None if method == "independent" else settings.block_length)
        return source.returns[sample_indices(n, horizon, sampler, seed=seed, path_id=path_id).indices]
    if method == "lognormal":
        return lognormal.draw(horizon, seed=seed, path_id=path_id)
    return garch.draw_batch(horizon, seed=seed, path_ids=[path_id])[0]


def ledger_metrics(returns, dates, portfolio, assets, initial):
    columns = [assets.index(a) for a in portfolio.spec.assets]
    daily = simulate_portfolio(MarketPath(dates, portfolio.spec.assets, returns[:, columns]), portfolio.spec, initial).daily
    values = daily.loc[pd.to_datetime(dates), "value"].to_numpy()
    return values[-1], float(np.min(values / np.maximum.accumulate(values) - 1))


def audit_paired(path, output, reuse):
    study = studies.load_paired(path)
    if not reuse:
        studies.run_paired(study, output)
    base, settings = study.base, study.base.generators
    outcomes = pd.read_csv(output / "paired_outcomes.csv")
    summary = pd.read_csv(output / "paired_summary.csv")
    differences = pd.read_csv(output / "paired_differences.csv")
    statistics = pd.read_csv(output / "window_statistics.csv")
    target = tuple(pd.to_datetime(pd.read_csv(output / "target_calendar.csv")["Date"]).dt.date)
    checked, max_error = 0, 0.0
    for window in study.windows:
        loaded = base.load(window["start"], window["end"])
        studies.check_provenance(window, loaded)
        for asset in loaded.path.assets:
            row = statistics[(statistics["window"] == window["name"]) & (statistics["asset"] == asset)].iloc[0]
            counts = loaded.provenance[f"provenance_{asset}"].value_counts()
            for label in ("observed", "reconstructed", "mixed", "unclassified"):
                if int(row[f"intervals_{label}"]) != int(counts.get(label, 0)):
                    raise AssertionError("Window provenance counts disagree with the adapter.")
        source = loaded.path
        lognormal = fit_lognormal(source, settings.observations_per_year) if "lognormal" in settings.methods else None
        garch = settings.volatility.fit(source, settings.observations_per_year) if "garch_fhs" in settings.methods else None
        cases = summary[(summary["window"] == window["name"]) & (summary["status"] == "ok")].drop_duplicates("case_id")
        for case in cases.itertuples():
            horizon = int(case.horizon_observations)
            seed = None if pd.isna(case.seed) else int(case.seed)
            for path_id in sorted({0, int(case.paths) // 2, int(case.paths) - 1}):
                returns = regenerate(case.method, source, settings, horizon, seed, path_id, garch, lognormal)
                row = outcomes[(outcomes["case_id"] == case.case_id) & (outcomes["path_id"] == path_id)].iloc[0]
                for portfolio in base.portfolios:
                    terminal, drawdown = ledger_metrics(returns, target[:horizon + 1], portfolio, source.assets, base.initial_value)
                    np.testing.assert_allclose(row[f"terminal__{portfolio.name}"], terminal, rtol=1e-10)
                    np.testing.assert_allclose(row[f"max_drawdown__{portfolio.name}"], drawdown, rtol=1e-10, atol=1e-12)
                    max_error = max(max_error, abs(row[f"terminal__{portfolio.name}"] - terminal) / terminal)
                checked += 1
    for row in summary[summary["status"] == "ok"].itertuples():
        values = outcomes.loc[outcomes["case_id"] == row.case_id, f"terminal__{row.portfolio}"]
        np.testing.assert_allclose(row.terminal_median, np.quantile(values, 0.5))
    for row in differences.itertuples():
        case = outcomes[outcomes["case_id"] == row.case_id]
        wins = (case[f"terminal__{row.portfolio}"] > case[f"terminal__{row.reference}"]).mean()
        np.testing.assert_allclose(row.fraction_outperforms_reference, wins)
    if any(output.glob("*.pdf")):
        raise AssertionError("PNG plotting must not create PDFs.")
    return {"cases": int(summary["case_id"].nunique()), "paths_evaluated": len(outcomes),
            "paths_regenerated_through_full_ledger": checked, "portfolios_per_path": len(base.portfolios),
            "max_terminal_relative_error": max_error, "summary_quantiles": "passed",
            "paired_fractions": "passed", "window_provenance": "passed"}


def audit_holdout(path, output, reuse):
    study = studies.load_holdout(path)
    if not reuse:
        studies.run_holdout(study, output)
    base, settings = study.base, study.base.generators
    folds = pd.read_csv(output / "holdout_folds.csv")
    generated = pd.read_csv(output / "holdout_generated.csv")
    full = base.load(study.data_start, study.data_end).path
    scored = folds[folds["status"] == "ok"]
    regenerated = 0
    origins = sorted(scored["origin_date"].unique())
    sampled = set(origins[::10]) | {origins[-1]}
    for origin_date, group in scored.groupby("origin_date"):
        o = full.dates.index(date.fromisoformat(origin_date))
        s = full.dates.index(date.fromisoformat(group["calibration_start"].iloc[0]))
        if not s < o:
            raise AssertionError("Calibration must end at the origin.")
        source = MarketPath(full.dates[s:o + 1], full.assets, full.returns[s:o], full.currency)
        fitted = studies.FittedGenerators(source, settings) if origin_date in sampled else None
        for fold in group.itertuples():
            h = int(fold.horizon_observations)
            portfolio = next(p for p in base.portfolios if p.name == fold.portfolio)
            terminal, drawdown = ledger_metrics(full.returns[o:o + h], full.dates[o:o + h + 1], portfolio, full.assets, base.initial_value)
            np.testing.assert_allclose(fold.realised_terminal, terminal, rtol=1e-10)
            np.testing.assert_allclose(fold.realised_max_drawdown, drawdown, rtol=1e-10, atol=1e-12)
            values = generated[(generated["origin_date"] == origin_date) & (generated["method"] == fold.method)
                               & (generated["portfolio"] == fold.portfolio) & (generated["horizon_observations"] == h)]
            for metric in ("terminal", "max_drawdown", "realised_volatility"):
                np.testing.assert_allclose(getattr(fold, f"pit_{metric}"), studies.pit(values[metric], getattr(fold, f"realised_{metric}")))
            if fitted:
                returns = regenerate(fold.method, source, settings, h, int(fold.seed), 0, fitted.garch, fitted.lognormal)
                terminal, _ = ledger_metrics(returns, full.dates[o:o + h + 1], portfolio, full.assets, base.initial_value)
                np.testing.assert_allclose(values.loc[values["path_id"] == 0, "terminal"].iloc[0], terminal, rtol=1e-10)
                regenerated += 1
    if any(output.glob("*.pdf")):
        raise AssertionError("PNG plotting must not create PDFs.")
    return {"scored_fold_rows": len(scored), "origins": len(origins), "realised_paths_reconciled": len(scored),
            "pit_recomputed": "passed", "generated_paths_regenerated": regenerated,
            "calibration_before_origin": "passed"}


def audit_batched_flows(scenario_path):
    scenario = load_scenario(scenario_path)
    source = load_datasets(scenario.data_root, scenario.portfolio.assets, scenario.start, scenario.end,
                           currency=scenario.portfolio.currency, file_format=scenario.file_format,
                           calendar_policy=scenario.calendar_policy).path
    horizon = 2520
    dates = source.dates[:horizon + 1]
    returns = np.stack([source.returns[sample_indices(len(source.returns), horizon, Sampler("stationary", 63),
                                                      seed=99, path_id=i).indices] for i in range(64)])
    months = pd.date_range(dates[0], dates[-1], freq="MS").date
    flows = [CashFlow(day, 1000.0) for day in months]
    flows += [CashFlow(day.replace(day=15), -5000.0, "before_return") for day in months if day.month % 3 == 0]
    flows.append(CashFlow(dates[-3], -1e7))
    ledger = simulate_paths(returns, dates, scenario.portfolio, scenario.initial_value, flows, initial_cash=500.0)
    days, values = ledger.calendar_values()
    max_error = 0.0
    for path_id in range(len(returns)):
        full = simulate_portfolio(MarketPath(dates, scenario.portfolio.assets, returns[path_id]), scenario.portfolio,
                                  scenario.initial_value, flows, initial_cash=500.0).daily
        np.testing.assert_allclose(values[path_id], full["value"], rtol=1e-12, atol=1e-8)
        np.testing.assert_allclose(ledger.shortfall[path_id], full.loc[pd.to_datetime(ledger.dates), "shortfall"], rtol=1e-12, atol=1e-8)
        max_error = max(max_error, float(np.max(np.abs(values[path_id] - full["value"].to_numpy()))))
    # Throughput: 1,000 paths over a 50-year business-day grid with monthly flows.
    long_dates = tuple(pd.bdate_range("2030-01-01", periods=12601).date)
    long_returns = np.stack([source.returns[sample_indices(len(source.returns), 12600, Sampler("stationary", 63),
                                                           seed=7, path_id=i).indices] for i in range(1000)])
    long_flows = [CashFlow(day, 500.0) for day in pd.date_range(long_dates[0], long_dates[-1], freq="MS").date]
    start = time.perf_counter()
    simulate_paths(long_returns, long_dates, scenario.portfolio, scenario.initial_value, long_flows)
    batched = time.perf_counter() - start
    start = time.perf_counter()
    for i in range(3):
        simulate_portfolio(MarketPath(long_dates, scenario.portfolio.assets, long_returns[i]), scenario.portfolio,
                           scenario.initial_value, long_flows)
    per_path = (time.perf_counter() - start) / 3
    return {"paths": len(returns), "horizon_observations": horizon, "dated_flows": len(flows),
            "calendar_days": len(days), "max_calendar_value_absolute_error": max_error, "rtol": 1e-12,
            "throughput_paths": 1000, "throughput_observations": 12600, "throughput_flows": len(long_flows),
            "batched_seconds": round(batched, 2), "full_ledger_seconds_per_path": round(per_path, 2),
            "full_ledger_extrapolated_seconds_for_1000_paths": round(per_path * 1000, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paired", default="scenarios/examples/paired.toml")
    parser.add_argument("--paired-output", default="output/stage1d-paired")
    parser.add_argument("--holdout", default="scenarios/examples/holdout.toml")
    parser.add_argument("--holdout-output", default="output/stage1d-holdout")
    parser.add_argument("--flows-scenario", default="scenarios/examples/baseline.toml")
    parser.add_argument("--reuse", action="store_true", help="Audit existing study outputs instead of rerunning them.")
    args = parser.parse_args()
    evidence = {"paired": audit_paired(args.paired, Path(args.paired_output), args.reuse),
                "holdout": audit_holdout(args.holdout, Path(args.holdout_output), args.reuse),
                "batched_flows": audit_batched_flows(args.flows_scenario), "code": code_manifest()}
    Path("output").mkdir(exist_ok=True)
    (Path("output") / "stage1d-studies-validation.json").write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n",
                                                                     encoding="utf-8", newline="\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
