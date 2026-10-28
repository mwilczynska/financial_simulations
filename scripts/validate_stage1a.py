"""Reproduce local Stage 1A integration evidence; companion checkouts required."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.data.datasets import load_datasets
from financial_simulations.runner import code_manifest, run_scenario
from financial_simulations.scenario import load_scenario
from financial_simulations.validation import audit_tracker, reconcile_optimiser


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/validation")
    parser.add_argument("--tracker-script", help="Optional trusted local portfolio_plot17.py calculation audit.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    examples = root / "scenarios" / "examples"
    baseline = load_scenario(examples / "baseline.toml")
    first, second = output / "baseline", output / "baseline-repeated"
    manifest = run_scenario(baseline, first, parquet=True)
    run_scenario(baseline, second)
    repeated = {}
    for name in ("daily.csv", "market_returns.csv", "source_observations.csv", "monthly.csv", "annual.csv",
                 "wealth.png", "drawdown.png", "allocation.png"):
        digest = sha256((first / name).read_bytes()).hexdigest()
        if digest != sha256((second / name).read_bytes()).hexdigest():
            raise AssertionError(f"Repeated run differs: {name}")
        repeated[name] = digest
    csv = load_datasets(baseline.data_root, baseline.portfolio.assets, baseline.start, baseline.end)
    parquet = load_datasets(baseline.data_root, baseline.portfolio.assets, baseline.start, baseline.end,
                            file_format="parquet")
    if csv.path.dates != parquet.path.dates:
        raise AssertionError("CSV/Parquet observation dates differ.")
    np.testing.assert_allclose(csv.path.returns, parquet.path.returns, rtol=1e-10, atol=1e-10)
    daily_csv = pd.read_csv(first / "daily.csv", parse_dates=["Date"]).set_index("Date")
    daily_parquet = pd.read_parquet(first / "daily.parquet")
    # CSV and Arrow readers may choose different timestamp storage resolutions.
    daily_csv.index = daily_csv.index.as_unit("ns")
    daily_parquet.index = daily_parquet.index.as_unit("ns")
    pd.testing.assert_frame_equal(daily_csv, daily_parquet,
                                   check_exact=False, rtol=1e-12, atol=1e-9)
    np.testing.assert_allclose(daily_csv["value"], daily_csv["opening_value"] + daily_csv["market_pnl"]
                               + daily_csv["net_external_flow"], rtol=1e-11, atol=1e-9)
    np.testing.assert_allclose(daily_csv["value"], daily_csv.filter(like="holding_").sum(axis=1)
                               + daily_csv["cash"], rtol=1e-11, atol=1e-9)
    comparisons = {}
    for name in ("baseline", "equal_weight_baseline", "optimiser_baseline"):
        scenario = load_scenario(examples / f"{name}.toml")
        report = reconcile_optimiser(scenario, root.parent / "portfolio_optimisation", output / f"reconcile-{name}")
        comparisons[name] = report["comparisons"]
    cash_flows = run_scenario(load_scenario(examples / "cash_flows.toml"), output / "cash-flows")
    if cash_flows["summary"]["shortfall"] != 10:
        raise AssertionError("Cash-flow fixture must record a 10-unit closed-market shortfall.")
    if any(output.rglob("*.pdf")):
        raise AssertionError("Stage 1A outputs must not contain PDFs.")
    evidence = {
        "code": code_manifest(), "baseline": manifest["summary"],
        "csv_parquet_max_return_difference": float(np.abs(csv.path.returns - parquet.path.returns).max()),
        "repeatable_artifact_sha256": repeated, "reconciliation": comparisons,
        "cash_flow_example": cash_flows["summary"], "daily_accounting_invariants": "passed",
        "daily_csv_parquet_agreement": "passed", "pdf_outputs": 0,
    }
    if args.tracker_script:
        evidence["tracker_audit"] = audit_tracker(baseline, args.tracker_script, output / "tracker-audit")
    (output / "validation.json").write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n",
                                            encoding="utf-8", newline="\n")
    print(json.dumps(evidence, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
