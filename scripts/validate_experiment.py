"""Run a daily comparison and audit saved paths and optional evaluation reports."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.comparison import load_comparison, run_comparison
from financial_simulations.data.datasets import load_datasets
from financial_simulations.evaluation import drawdown_statistics
from financial_simulations.markets.path import MarketPath
from financial_simulations.markets.assumptions import assumed_price_index
from financial_simulations.portfolios.engine import simulate_portfolio
from financial_simulations.scenario import load_scenario


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="scenarios/examples/comparison.toml")
    parser.add_argument("--output", default="output/stage1b")
    args = parser.parse_args()
    config = load_comparison(args.experiment)
    manifest = run_comparison(config, args.output)
    scenario = load_scenario(config.scenario_file)
    window = config.windows[0]
    source = load_datasets(scenario.data_root, scenario.portfolio.assets, window["start"], window["end"],
                           currency=scenario.portfolio.currency, file_format=scenario.file_format,
                           calendar_policy=scenario.calendar_policy).path
    output = Path(args.output)
    traces = pd.read_csv(output / "traces.csv")
    summary = pd.read_csv(output / "summary.csv")
    outcomes = pd.read_csv(output / "outcomes.csv")
    summary_index = summary.set_index("case_id")
    outcome_index = outcomes.set_index(["case_id", "path_id"])
    max_error, count = 0.0, 0
    for (case_id, path_id), group in traces.groupby(["case_id", "path_id"]):
        generated = group["method"].iloc[0] in ("lognormal", "garch_fhs")
        if generated:
            returns = group[[f"return_{a}" for a in source.assets]].iloc[1:].to_numpy()
            if group["donor_index"].notna().any() or group["source_date"].notna().any():
                raise AssertionError("Generated returns must not claim historical donor dates.")
        else:
            indices = group["donor_index"].iloc[1:].to_numpy(dtype=int)
            returns = source.returns[indices]
            expected_dates = [str(source.dates[i + 1]) for i in indices]
            if group["source_date"].iloc[1:].tolist() != expected_dates:
                raise AssertionError("Trace donor dates do not match source indices.")
        target = tuple(t.date() for t in pd.to_datetime(group["target_date"]))
        path = MarketPath(target, source.assets, returns, source.currency)
        result = simulate_portfolio(path, scenario.portfolio, scenario.initial_value, initial_cash=scenario.initial_cash)
        actual = result.daily.loc[pd.to_datetime(target), "value"].to_numpy()
        expected = group["value"].to_numpy()
        np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-7)
        if config.parametric:
            np.testing.assert_allclose(group["real_value"], actual / group["price_index"], rtol=1e-11, atol=1e-7)
        if config.evaluation:
            dates = tuple(result.daily.index.date)
            values = result.daily["value"].to_numpy()
            for prefix in ("nominal", "real") if config.parametric else ("nominal",):
                evaluated = values if prefix == "nominal" else values / assumed_price_index(dates, summary_index.loc[case_id, "inflation_annual"])
                statistics = drawdown_statistics([evaluated], dates)
                row = outcome_index.loc[(case_id, path_id)]
                for key in ("max_drawdown", "longest_underwater_days", "max_drawdown_observed_duration_days"):
                    np.testing.assert_allclose(row[f"{prefix}_{key}"], statistics[key][0], rtol=1e-11, atol=1e-10)
                if row[f"{prefix}_max_drawdown_recovery_status"] != statistics["max_drawdown_recovery_status"][0]:
                    raise AssertionError("Recovery status disagrees with the full-calendar path.")
        max_error = max(max_error, float(np.max(np.abs(actual - expected))))
        count += 1
    for _, case in summary.iterrows():
        actual_count = int((outcomes["case_id"] == case["case_id"]).sum())
        if actual_count != case["paths"]:
            raise AssertionError("Outcome count disagrees with case summary.")
        if case["method"] == "historical_replay":
            complete = max(0, int(case["source_observations"] - case["horizon_observations"] + 1))
            if complete != actual_count:
                raise AssertionError("Historical replay includes an incomplete or missing window.")
    paired = 0
    if config.parametric:
        generated = summary[summary["method"].isin(["lognormal", "garch_fhs"])]
        assumption_by_name = {a.name: a for a in config.parametric.assumptions}
        # Audit every identical nominal specification, regardless of its scenario name.
        for _, cases in generated.groupby(["window", "horizon_observations", "seed", "method"]):
            for i, left in enumerate(cases.itertuples()):
                a = assumption_by_name[left.assumption]
                for right in list(cases.itertuples())[i + 1:]:
                    b = assumption_by_name[right.assumption]
                    if a.mean_convention != b.mean_convention or a.annual_returns != b.annual_returns:
                        continue
                    lvalues = outcomes[outcomes["case_id"] == left.case_id].sort_values("path_id")
                    rvalues = outcomes[outcomes["case_id"] == right.case_id].sort_values("path_id")
                    np.testing.assert_array_equal(lvalues["terminal_value"], rvalues["terminal_value"])
                    dates = (left.target_opening, left.target_end)
                    ratio = assumed_price_index(dates, a.inflation_annual)[-1] / assumed_price_index(dates, b.inflation_annual)[-1]
                    np.testing.assert_allclose(rvalues["real_terminal_value"], lvalues["real_terminal_value"] * ratio)
                    paired += len(lvalues)
    if any(output.glob("*.pdf")):
        raise AssertionError("PNG plotting must not create PDFs.")
    evaluation = None
    if config.evaluation:
        series = pd.read_csv(output / "wealth_percentiles.csv")
        risks = pd.read_csv(output / "risk_summary.csv").set_index("case_id")
        for case_id, group in series.groupby("case_id"):
            case = summary_index.loc[case_id]
            observed = group["is_observation"]
            for suffix in ("p05", "median", "p95"):
                column = f"nominal_{suffix}"
                np.testing.assert_allclose(group[column], group[column].where(observed).ffill())
                np.testing.assert_allclose(group[column].iloc[-1], case[f"terminal_{suffix}"])
                if config.parametric:
                    np.testing.assert_allclose(group[f"real_{suffix}"], group[column] / group["price_index"])
            case_outcomes = outcomes[outcomes["case_id"] == case_id]
            risk = risks.loc[case_id]
            terminal = case_outcomes["real_terminal_value" if config.evaluation.target_basis == "real" else "terminal_value"]
            if risk["misses"] != int((terminal < risk["terminal_target"]).sum()):
                raise AssertionError("Reported target misses disagree with path outcomes.")
            if case["method"] == "historical_replay":
                if risk[["fraction_ci_low", "fraction_ci_high", "fraction_mcse", "terminal_mean_mcse"]].notna().any():
                    raise AssertionError("Dependent replay must not receive independent-sample inference.")
            elif not risk["fraction_ci_low"] <= risk["fraction_below_target"] <= risk["fraction_ci_high"]:
                raise AssertionError("Monte Carlo interval does not contain its estimated fraction.")
        evaluation = {"daily_percentile_rows": len(series), "cases_checked": len(risks),
                      "terminal_quantiles": "passed", "calendar_carry": "passed",
                      "real_deflation": "passed" if config.parametric else "not_requested",
                      "target_counts_and_interval_scope": "passed", "saved_path_recovery": "passed"}
    evidence = {"cases": manifest["cases"], "paths_evaluated": len(outcomes),
                "traces_reconciled": count, "max_trace_absolute_error": max_error,
                "trace_rtol": 1e-11, "trace_atol": 1e-7, "outcome_counts": "passed",
                "complete_replay_counts": "passed", "paired_assumption_paths_checked": paired,
                "evaluation": evaluation,
                "code": manifest["code"]}
    (output / "validation.json").write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n",
                                            encoding="utf-8", newline="\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
