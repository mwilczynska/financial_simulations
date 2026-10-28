"""Run Stage 1A and persist the evidence needed to inspect the result."""

from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import subprocess

import pandas as pd

from financial_simulations import __version__
from financial_simulations.data.datasets import load_datasets
from financial_simulations.portfolios.engine import simulate_portfolio
from financial_simulations.reporting.baseline import period_summary, summary_statistics, write_report
from financial_simulations.reporting.plots import write_plots
from financial_simulations.scenario import Scenario


def code_manifest() -> dict:
    package = Path(__file__).resolve().parent
    digest = sha256()
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    root = package.parent.parent
    commit, dirty = None, None
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root,
                                    capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        pass
    dependencies = {}
    for name in ("numpy", "pandas", "matplotlib", "pyarrow", "pytest"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            pass
    return {"package_version": __version__, "python": platform.python_version(),
            "dependencies": dependencies, "git_commit": commit,
            "working_tree_dirty": dirty, "python_source_sha256": digest.hexdigest()}


def run_scenario(scenario: Scenario, output: str | Path, *, parquet: bool = False) -> dict:
    loaded = load_datasets(scenario.data_root, scenario.portfolio.assets, scenario.start,
                           scenario.end, currency=scenario.portfolio.currency, file_format=scenario.file_format,
                           calendar_policy=scenario.calendar_policy)
    result = simulate_portfolio(loaded.path, scenario.portfolio, scenario.initial_value,
                                scenario.cash_flows, initial_cash=scenario.initial_cash)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result.daily.to_csv(output / "daily.csv", lineterminator="\n")
    if parquet:
        result.daily.to_parquet(output / "daily.parquet")
    market_returns = pd.DataFrame(loaded.path.returns, columns=loaded.path.assets,
                                  index=pd.DatetimeIndex(loaded.path.dates[1:], name="Date"))
    market_returns.insert(0, "previous_valuation_date", [d.isoformat() for d in loaded.path.dates[:-1]])
    market_returns.to_csv(output / "market_returns.csv", lineterminator="\n")
    provenance = pd.concat(loaded.source_rows, names=["Asset", "Date"])
    provenance.to_csv(output / "source_observations.csv", lineterminator="\n")
    for frequency, filename in (("monthly", "monthly.csv"), ("annual", "annual.csv")):
        period_summary(result, frequency).to_csv(output / filename, index=False, lineterminator="\n")
    manifest = {
        "schema_version": 1, "model": "stage_1a_deterministic_daily_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "code": code_manifest(), "scenario": scenario.manifest, "data": loaded.manifest,
        "conventions": {
            "opening": "First selected valuation, with no opening return sample.",
            "event_order": "before flows; annual risky-holdings rebalance; return; after flows; cash sweep",
            "closed_market": "Cash ledger only; no forced sale, borrowing or retry of unmet withdrawals.",
            "cash_return": "Zero interest; initial reserve retained, pending deposits invested at next observation close.",
            "fees_and_distributions": "Only those embedded in supplied returns; no additional charges or income.",
            "annualisation": "Compounded time-weighted growth; actual elapsed calendar days / 365.25.",
            "random_generator": None,
        },
        "summary": summary_statistics(result),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n",
                                          encoding="utf-8", newline="\n")
    write_plots(output, result, scenario.name)
    write_report(output, result, manifest, scenario.name)
    return manifest
