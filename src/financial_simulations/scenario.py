"""Portable TOML scenarios, with paths relative to the scenario file."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import tomllib

from financial_simulations.data.optimiser import load_optimiser_portfolio
from financial_simulations.dates import as_date
from financial_simulations.portfolios.engine import CashFlow
from financial_simulations.portfolios.spec import PortfolioSpec


@dataclass(frozen=True)
class Scenario:
    name: str
    data_root: Path
    file_format: str
    start: str
    end: str
    initial_value: float
    initial_cash: float
    portfolio: PortfolioSpec
    cash_flows: tuple[CashFlow, ...]
    manifest: dict


def _keys(table: dict, allowed: set[str], required: set[str], context: str) -> None:
    if not isinstance(table, dict):
        raise ValueError(f"{context} must be a table.")
    unknown, missing = set(table) - allowed, required - set(table)
    if unknown or missing:
        raise ValueError(f"{context}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}.")


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path).resolve()
    raw = path.read_bytes()
    config = tomllib.loads(raw.decode("utf-8"))
    _keys(config, {"run", "data", "portfolio", "cash_flows"}, {"run", "data", "portfolio"}, "scenario")
    run, data, portfolio = config["run"], config["data"], config["portfolio"]
    _keys(run, {"name", "start", "end", "initial_value", "initial_cash", "currency", "rebalance"},
          {"name", "start", "end", "initial_value", "currency", "rebalance"}, "run")
    _keys(data, {"root", "format"}, {"root"}, "data")
    _keys(portfolio, {"weights", "optimiser"}, set(), "portfolio")
    if ("weights" in portfolio) == ("optimiser" in portfolio):
        raise ValueError("Choose exactly one manual weights table or optimiser selection.")
    source = {"adapter": "manual_weights"}
    if "weights" in portfolio:
        spec = PortfolioSpec(portfolio["weights"], run["rebalance"], run["currency"])
    else:
        selection = portfolio["optimiser"]
        _keys(selection, {"path", "rank"}, {"path", "rank"}, "portfolio.optimiser")
        imported = load_optimiser_portfolio(path.parent / selection["path"], rank=selection["rank"],
                                            rebalance=run["rebalance"], currency=run["currency"])
        spec, source = imported.portfolio, imported.manifest
    flows = []
    for entry in config.get("cash_flows", []):
        _keys(entry, {"date", "amount", "timing"}, {"date", "amount"}, "cash_flows")
        flows.append(CashFlow(entry["date"], entry["amount"], entry.get("timing", "after_return")))
    if not isinstance(run["name"], str) or not run["name"].strip():
        raise ValueError("Scenario name must be a nonempty string.")
    start, end = as_date(run["start"]).isoformat(), as_date(run["end"]).isoformat()
    if start > end:
        raise ValueError("Scenario start must not follow end.")
    manifest = {
        "file": path.name, "sha256": sha256(raw).hexdigest(), "name": run["name"],
        "start": start, "end": end, "currency": spec.currency,
        "initial_value": run["initial_value"], "initial_cash": run.get("initial_cash", 0.0),
        "weights": dict(spec.weights), "rebalance": spec.rebalance,
        "cash_flows": [{**asdict(flow), "date": flow.date.isoformat()} for flow in flows],
        "portfolio_source": source,
    }
    return Scenario(run["name"], (path.parent / data["root"]).resolve(), data.get("format", "csv"),
                    start, end, run["initial_value"], run.get("initial_cash", 0.0), spec,
                    tuple(flows), manifest)
