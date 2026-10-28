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


CALENDAR_POLICIES = ("strict", "common_dates")


@dataclass(frozen=True)
class LoadedMarketData:
    path: MarketPath
    levels: pd.DataFrame
    source_rows: dict[str, pd.DataFrame]
    manifest: dict
    # One row per return: provenance class and source observations spanned, per asset.
    provenance: pd.DataFrame | None = None


def classify_quality_flag(flag: str) -> str:
    """Observed or reconstructed by the upstream flag's reviewed prefix, else unclassified."""
    flag = str(flag)
    if flag.startswith("observed_"):
        return "observed"
    if flag.startswith(("model_", "backcalculated_")):
        return "reconstructed"
    return "unclassified"


def _return_provenance(frame: pd.DataFrame, kept: pd.DatetimeIndex) -> tuple[list[str], list[int]]:
    """Classify each kept interval from every source row it spans, both endpoints included."""
    classes = frame["Quality Flag"].map(classify_quality_flag).to_numpy()
    positions = frame.index.get_indexer(kept)
    labels, steps = [], []
    for left, right in zip(positions[:-1], positions[1:]):
        spanned = set(classes[left:right + 1])
        labels.append(spanned.pop() if len(spanned) == 1 else "mixed")
        steps.append(int(right - left))
    return labels, steps


def load_datasets(
    root: str | Path,
    assets: Sequence[str],
    start: str,
    end: str,
    *,
    currency: str = "USD",
    file_format: str = "csv",
    calendar_policy: str = "strict",
) -> LoadedMarketData:
    """Load an opening mark and returns recomputed from consecutive levels.

    ``strict`` requires identical observation dates within the inclusive window.
    ``common_dates`` keeps the dates every asset observes and recomputes each
    return between consecutive kept levels, so an interval can span more than
    one source observation; nothing is filled. Published returns are checked
    against each file's own adjacent levels (rounding tolerance 1e-8), and are
    never inferred from price/total-return differences.
    """
    start_date, end_date = as_date(start), as_date(end)
    if start_date > end_date:
        raise ValueError("Start must be on or before end.")
    if file_format not in ("csv", "parquet"):
        raise ValueError("Choose csv or parquet.")
    if calendar_policy not in CALENDAR_POLICIES:
        raise ValueError("Choose the strict or common_dates calendar policy.")
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
        if calendar_policy == "strict" and dates is not None and not frame.index.equals(dates):
            raise ValueError(
                f"{filename}: observation calendars differ. Choose an aligned window or the explicit "
                "common_dates policy; the strict policy does not drop observations or fill returns."
            )
        dates = frame.index if dates is None else dates.intersection(frame.index)
        rows[asset.identifier] = frame
        metadata.append({
            **asset.metadata(), "file": filename, "sha256": sha256(raw).hexdigest(),
            "selected_rows": len(frame), "first_valuation": frame.index[0].date().isoformat(),
            "last_valuation": frame.index[-1].date().isoformat(),
            "quality_counts": {str(k): int(v) for k, v in frame["Quality Flag"].value_counts().items()},
            "sources": sorted(str(s) for s in frame["Source"].unique()),
        })
    if len(dates) < 2:
        raise ValueError("At least two common valuation dates are required in the selected window.")
    levels_frame = pd.DataFrame({a.identifier: rows[a.identifier].loc[dates, a.level_column].astype(float)
                                 for a in definitions})
    provenance, removed = {}, {}
    for asset in definitions:
        frame = rows[asset.identifier]
        labels, steps = _return_provenance(frame, dates)
        provenance[f"provenance_{asset.identifier}"] = labels
        provenance[f"source_steps_{asset.identifier}"] = steps
        interior = frame.index[(frame.index >= dates[0]) & (frame.index <= dates[-1])]
        removed[asset.identifier] = int(len(interior.difference(dates)))
    provenance = pd.DataFrame(provenance, index=pd.DatetimeIndex(dates[1:], name="Date"))
    classes = provenance[[f"provenance_{a.identifier}" for a in definitions]]
    first = classes.iloc[:, 0]
    provenance.insert(0, "provenance", np.where(classes.eq(first, axis=0).all(axis=1), first, "mixed"))
    path = MarketPath(
        tuple(timestamp.date() for timestamp in levels_frame.index),
        tuple(a.identifier for a in definitions),
        levels_frame.to_numpy()[1:] / levels_frame.to_numpy()[:-1] - 1.0,
        currency,
    )
    manifest = {
        "adapter": "financial_datasets_strict_v1", "currency": currency,
        "requested_start": str(start_date), "requested_end": str(end_date),
        "calendar_policy": "identical_source_observation_dates; no filling or inner join",
        "opening_date": str(path.dates[0]), "last_date": str(path.dates[-1]),
        "return_observations": len(path.returns), "inputs": metadata,
        "return_provenance": {str(k): int(v) for k, v in provenance["provenance"].value_counts().items()},
    }
    if calendar_policy == "common_dates":
        multi = (provenance[[f"source_steps_{a.identifier}" for a in definitions]] > 1).any(axis=1)
        manifest.update(adapter="financial_datasets_common_dates_v1",
                        calendar_policy="common_source_observation_dates; returns recomputed between kept levels",
                        source_dates_not_kept=removed, multi_observation_intervals=int(multi.sum()))
    return LoadedMarketData(path, levels_frame, rows, manifest, provenance)
