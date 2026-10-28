"""Import numeric weight columns; never evaluate exported executable syntax."""

import csv
from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
from pathlib import Path

from financial_simulations.portfolios.spec import PortfolioSpec


@dataclass(frozen=True)
class ImportedPortfolio:
    portfolio: PortfolioSpec
    manifest: dict


def load_optimiser_portfolio(
    path: str | Path, *, rank: int, rebalance: str, currency: str = "USD"
) -> ImportedPortfolio:
    """Select exactly one Rank; require the caller to supply missing run policy."""
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise ValueError("Select a positive integer optimiser rank.")
    path = Path(path)
    raw = path.read_bytes()
    reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
    columns = reader.fieldnames or []
    if len(set(columns)) != len(columns):
        raise ValueError("Optimiser CSV has duplicate headers.")
    weight_columns = [column for column in columns if column.endswith(" Weight")]
    if "Rank" not in columns or not weight_columns:
        raise ValueError("Expected Rank and explicit '<asset> Weight' columns.")
    matches = [row for row in reader if row["Rank"] == str(rank)]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one optimiser row for rank {rank}.")
    row = matches[0]
    portfolio = PortfolioSpec({column[:-7]: float(row[column]) for column in weight_columns}, rebalance, currency)
    return ImportedPortfolio(portfolio, {
        "adapter": "portfolio_optimisation_numeric_weights_v1", "file": path.name,
        "sha256": sha256(raw).hexdigest(), "rank": rank,
        "weight_columns": weight_columns,
        "policy_provenance": "Rebalancing and currency explicitly supplied by scenario; absent from CSV.",
        "exported_statistics_used_as_inputs": False,
    })
