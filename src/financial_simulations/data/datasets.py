"""Load published levels and provenance without filling or thinning observations."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from financial_simulations.data.registry import resolve_asset
from financial_simulations.dates import as_date
from financial_simulations.markets.path import MarketPath


@dataclass(frozen=True)
class LoadedMarketData:
    path: MarketPath
    levels: pd.DataFrame
    source_rows: dict[str, pd.DataFrame]
    manifest: dict


def load_datasets(
    root: str | Path,
    assets: Sequence[str],
    start: str,
    end: str,
    *,
    currency: str = "USD",
    file_format: str = "csv",
) -> LoadedMarketData:
    """Require identical observation dates within the inclusive requested window.

    The first selected level is an opening mark. Returns are recomputed from
    consecutive levels, checked against published returns (rounding tolerance
    1e-8), and never inferred from price/total-return differences.
    """
    start_date, end_date = as_date(start), as_date(end)
    if start_date > end_date:
        raise ValueError("Start must be on or before end.")
    if file_format not in ("csv", "parquet"):
        raise ValueError("Choose csv or parquet.")
    definitions = [resolve_asset(identifier) for identifier in assets]
    if not definitions or len({a.identifier for a in definitions}) != len(definitions):
        raise ValueError("Select nonempty, unique canonical assets.")
    rows, metadata = {}, []
    dates = None
    for asset in definitions:
        if asset.currency != currency:
            raise ValueError(f"{asset.identifier} requires an explicit FX conversion to {currency}.")
        filename = Path(asset.filename).with_suffix(f".{file_format}").name
        raw = (Path(root) / filename).read_bytes()
        frame = pd.read_csv(BytesIO(raw)) if file_format == "csv" else pd.read_parquet(BytesIO(raw))
        required = {"Date", asset.level_column, asset.return_column, "Source", "Quality Flag", "Source Notes"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{filename}: missing required columns {sorted(missing)}.")
        index = pd.DatetimeIndex(pd.to_datetime(frame["Date"], format="%Y-%m-%d", errors="raise"))
        if index.hasnans or index.tz is not None or not index.equals(index.normalize()):
            raise ValueError(f"{filename}: expected calendar dates.")
        if not index.is_unique or not index.is_monotonic_increasing:
            raise ValueError(f"{filename}: dates must be sorted and unique.")
        frame = frame.set_index(index.rename("Date")).drop(columns="Date")
        frame = frame.loc[str(start_date):str(end_date)].copy()
        if len(frame) < 2:
            raise ValueError(f"{filename}: at least two valuations are required in the selected window.")
        levels = pd.to_numeric(frame[asset.level_column], errors="raise").to_numpy(dtype=float)
        published = pd.to_numeric(frame[asset.return_column], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(levels).all() or (levels <= 0).any():
            raise ValueError(f"{filename}: total-return levels must be finite and positive.")
        recomputed = levels[1:] / levels[:-1] - 1.0
        if not np.isfinite(published[1:]).all() or not np.allclose(recomputed, published[1:], rtol=0, atol=1e-8):
            raise ValueError(f"{filename}: published returns do not reconcile with adjacent levels (1e-8 tolerance).")
        if frame[["Source", "Quality Flag"]].isna().any().any():
            raise ValueError(f"{filename}: source and quality provenance are required on every row.")
        if dates is not None and not frame.index.equals(dates):
            raise ValueError(
                f"{filename}: observation calendars differ. Choose an aligned window; "
                "Stage 1A does not drop observations or fill missing returns."
            )
        dates = frame.index
        rows[asset.identifier] = frame
        metadata.append({
            **asset.metadata(), "file": filename, "sha256": sha256(raw).hexdigest(),
            "selected_rows": len(frame), "first_valuation": frame.index[0].date().isoformat(),
            "last_valuation": frame.index[-1].date().isoformat(),
            "quality_counts": {str(k): int(v) for k, v in frame["Quality Flag"].value_counts().items()},
            "sources": sorted(str(s) for s in frame["Source"].unique()),
        })
    levels_frame = pd.DataFrame({a.identifier: rows[a.identifier][a.level_column].astype(float) for a in definitions})
    path = MarketPath(
        tuple(timestamp.date() for timestamp in levels_frame.index),
        tuple(a.identifier for a in definitions),
        levels_frame.to_numpy()[1:] / levels_frame.to_numpy()[:-1] - 1.0,
        currency,
    )
    return LoadedMarketData(path, levels_frame, rows, {
        "adapter": "financial_datasets_strict_v1", "currency": currency,
        "requested_start": str(start_date), "requested_end": str(end_date),
        "calendar_policy": "identical_source_observation_dates; no filling or inner join",
        "opening_date": str(path.dates[0]), "last_date": str(path.dates[-1]),
        "return_observations": len(path.returns), "inputs": metadata,
    })
