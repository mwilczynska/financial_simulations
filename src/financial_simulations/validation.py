"""Optional reconciliation with the trusted local companion implementation."""

import ast
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.data.datasets import load_datasets
from financial_simulations.data.registry import resolve_asset
from financial_simulations.portfolios.engine import simulate_portfolio
from financial_simulations.portfolios.spec import PortfolioSpec
from financial_simulations.reporting.baseline import summary_statistics
from financial_simulations.runner import code_manifest
from financial_simulations.scenario import Scenario


def reconcile_optimiser(scenario: Scenario, optimiser_root: str | Path, output: str | Path) -> dict:
    if scenario.cash_flows or scenario.initial_cash != 0 or scenario.initial_value <= 0:
        raise ValueError("Reconciliation requires positive starting investment, no cash flows and no initial cash.")
    module_path = Path(optimiser_root) / "portfolio_optimizer.py"
    spec = importlib.util.spec_from_file_location("stage1a_reference_optimiser", module_path)
    if spec is None or spec.loader is None:
        raise ValueError("Could not load the local reference optimiser.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    aliases = {resolve_asset(alias).identifier: alias for alias in module.CUSTOM_DATASETS}
    tickers = []
    for asset in scenario.portfolio.assets:
        if asset not in aliases:
            raise ValueError(f"Reference optimiser does not support {asset}.")
        ticker = aliases[asset]
        module.CUSTOM_DATASETS[ticker]["path"] = scenario.data_root / resolve_asset(asset).filename
        tickers.append(ticker)
    loaded = load_datasets(scenario.data_root, scenario.portfolio.assets, scenario.start, scenario.end,
                           currency=scenario.portfolio.currency, file_format=scenario.file_format,
                           calendar_policy=scenario.calendar_policy)
    reference_prices = module.load_prices(tickers, scenario.start, scenario.end)
    if tuple(t.date() for t in reference_prices.index) != loaded.path.dates:
        raise ValueError("The reference and this loader selected different observation dates.")
    returns = reference_prices.pct_change(fill_method=None).dropna()
    np.testing.assert_allclose(returns.to_numpy(), loaded.path.returns, rtol=1e-12, atol=1e-12)
    weights = np.array([list(scenario.portfolio.weights.values())])
    comparisons = {}
    for policy, function in (("annual", module.annual_rebalanced_values), ("buy_and_hold", module.buy_and_hold_values)):
        reference = function(returns, weights, scenario.initial_value)[:, 0]
        portfolio = PortfolioSpec(scenario.portfolio.weights, policy, scenario.portfolio.currency)
        result = simulate_portfolio(loaded.path, portfolio, scenario.initial_value)
        actual = result.daily.loc[returns.index, "value"].to_numpy()
        np.testing.assert_allclose(actual, reference, rtol=1e-10, atol=1e-7)
        comparisons[policy] = {
            "observations_compared": len(reference), "max_absolute_error": float(np.max(np.abs(actual - reference))),
            "max_relative_error": float(np.max(np.abs(actual - reference) / reference)),
            "final_value": float(actual[-1]), "passed": True,
        }
    report = {"scenario": scenario.manifest, "data": loaded.manifest, "code": code_manifest(),
              "reference_source_sha256": sha256(module_path.read_bytes()).hexdigest(),
              "tolerance": {"relative": 1e-10, "absolute": 1e-7}, "comparisons": comparisons,
              "scope": "Same inputs and daily accounting; not exported ranking statistics or future outcomes."}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "reconciliation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                                                encoding="utf-8", newline="\n")
    return report


def audit_tracker(scenario: Scenario, tracker_script: str | Path, output: str | Path) -> dict:
    """Compare selected local calculation functions without running the script.

    The caller explicitly supplies trusted local code. Imports, configuration,
    downloads, plotting and other top-level statements are not executed/copied.
    """
    if scenario.cash_flows or scenario.initial_cash != 0 or scenario.initial_value <= 0:
        raise ValueError("Tracker audit requires positive starting investment, no flows and no initial cash.")
    source = Path(tracker_script).read_bytes()
    tree = ast.parse(source.decode("utf-8-sig"))
    names = {"simulate_portfolio", "cagr", "twrr", "max_dd"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in functions} != names or any(node.decorator_list or node.args.defaults for node in functions):
        raise ValueError("Expected undecorated tracker calculation functions without default expressions.")
    namespace = {"np": np, "pd": pd, "math": math}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<local-tracker-calculations>", "exec"), namespace)
    loaded = load_datasets(scenario.data_root, scenario.portfolio.assets, scenario.start, scenario.end)
    returns = pd.DataFrame(loaded.path.returns, columns=loaded.path.assets,
                           index=pd.DatetimeIndex(loaded.path.dates[1:]))
    namespace.update(dates=returns.index, starting_value=scenario.initial_value, monthly_contribution=0)
    comparisons = {}
    for policy in ("annual", "buy_and_hold"):
        namespace["rebalance_annually"] = policy == "annual"
        legacy, _, _ = namespace["simulate_portfolio"](returns, list(scenario.portfolio.assets),
                                                       list(scenario.portfolio.weights.values()))
        spec = PortfolioSpec(scenario.portfolio.weights, policy, scenario.portfolio.currency)
        actual = simulate_portfolio(loaded.path, spec, scenario.initial_value)
        observed = actual.daily.loc[returns.index, "value"].to_numpy()
        shifted = np.concatenate(([scenario.initial_value], observed[:-1]))
        comparisons[policy] = {
            "observations": len(observed),
            "same_date_values_match": bool(np.allclose(legacy.to_numpy(), observed, rtol=1e-10, atol=1e-7)),
            "one_observation_shift_matches": bool(np.allclose(legacy.to_numpy(), shifted, rtol=1e-10, atol=1e-7)),
            "tracker_final_value": float(legacy.iloc[-1]), "engine_final_value": float(observed[-1]),
        }
        # Check reusable metric formulas on the same correctly dated value path.
        values = actual.daily["value"]
        namespace["n_years"] = (values.index[-1] - values.index[0]).days / 365.25
        reference_cagr = namespace["cagr"](values)
        stats = summary_statistics(actual)
        expected_cagr = stats["annualised_time_weighted_return"]
        np.testing.assert_allclose(reference_cagr, expected_cagr, rtol=1e-12, atol=1e-12)
        reference_dd = namespace["max_dd"](values)
        expected_dd = stats["max_time_weighted_drawdown"]
        np.testing.assert_allclose(reference_dd, expected_dd, rtol=1e-12, atol=1e-12)
        comparisons[policy]["cagr_and_drawdown_formulas_match_on_common_values"] = True
    # A deposit of 10 after a +10% return, followed by -10%, has TWR -1%.
    # Set a one-year metric horizon to expose the cumulative factor directly.
    namespace["n_years"] = 1.0
    example = pd.Series([100.0, 120.0, 108.0], index=pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]))
    tracker_flow_return = float(namespace["twrr"](example, [(example.index[1], 10.0)]))
    report = {
        "file": Path(tracker_script).name, "source_sha256": sha256(source).hexdigest(),
        "functions_reviewed": sorted(names), "top_level_script_executed": False,
        "comparisons": comparisons,
        "contribution_counterexample": {"values": [100, 120, 108], "deposit_after_first_return": 10,
                                         "expected_time_weighted_return": -0.01,
                                         "tracker_function_return_at_one_year_horizon": tracker_flow_return},
        "scope": "Calculation functions only; nominal aligned data, no contributions in historical comparison."
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "tracker-audit.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                                              encoding="utf-8", newline="\n")
    return report
