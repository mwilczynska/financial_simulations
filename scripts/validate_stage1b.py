"""Run a Stage 1B/1C experiment and audit saved traces with the full daily ledger."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.comparison import load_comparison, run_comparison
from financial_simulations.data.datasets import load_datasets
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
                           currency=scenario.portfolio.currency, file_format=scenario.file_format).path
    output = Path(args.output)
    traces = pd.read_csv(output / "traces.csv")
    max_error, count = 0.0, 0
    for _, group in traces.groupby(["case_id", "path_id"]):
        gaussian = group["method"].iloc[0] == "lognormal"
        if gaussian:
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
        max_error = max(max_error, float(np.max(np.abs(actual - expected))))
        count += 1
    summary = pd.read_csv(output / "summary.csv")
    outcomes = pd.read_csv(output / "outcomes.csv")
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
        gaussian = summary[summary["method"] == "lognormal"]
        assumption_by_name = {a.name: a for a in config.parametric.assumptions}
        # Audit every identical nominal specification, regardless of its scenario name.
        for _, cases in gaussian.groupby(["window", "horizon_observations", "seed"]):
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
    evidence = {"cases": manifest["cases"], "paths_evaluated": len(outcomes),
                "traces_reconciled": count, "max_trace_absolute_error": max_error,
                "trace_rtol": 1e-11, "trace_atol": 1e-7, "outcome_counts": "passed",
                "complete_replay_counts": "passed", "paired_assumption_paths_checked": paired,
                "code": manifest["code"]}
    (output / "validation.json").write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n",
                                            encoding="utf-8", newline="\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
