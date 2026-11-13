"""Save a finished plan run's results and open them again without re-running (ADR 0050).

A saved run is one folder per plan name, ``output/saved_runs/<plan-name>/``; saving again replaces it:

| File | Contents |
| --- | --- |
| ``run.json`` | Format version, when it was saved, the plan, notes, rules, code and market manifests, strategy index |
| ``plan.toml`` | The plan, readable on its own |
| ``market_returns.parquet`` | The joint daily history returns the paths were drawn from, by ticker |
| ``asset_summary.parquet`` | Each ticker's history statistics |
| ``portfolio_draws.npz`` | The future observation dates and every path's sampled history rows (delta-encoded) |
| ``portfolio_*.parquet`` | Portfolio history, bands, per-path outcomes and summary |
| ``strategies/<rule>/*.parquet`` | Per strategy: path outcomes, yearly rows, account bands, month-end balances by path |
| ``strategies/<rule>/representative/`` | The median path's full daily ledger (``ledger_store``) |
| ``strategies/<rule>/ledgers/`` | Optional: every calculated path's full daily ledger |

Everything is stored as computed: opening a saved run re-derives nothing that the run itself summarised, so the
results are those of the code and data that produced them, which ``run.json`` records.
"""

from dataclasses import replace
from datetime import date, datetime
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from financial_simulations.data.plan_markets import PlanMarketData
from financial_simulations.markets.path import MarketPath
from financial_simulations.retirement.analysis import PortfolioAnalysis
from financial_simulations.retirement.ledger_store import LedgerStore, ledger_parts, store_all_ledgers, write_ledgers
from financial_simulations.retirement.plan import plan_to_toml, slug
from financial_simulations.retirement.run_plan import PlanRun
from financial_simulations.runner import code_manifest


FORMAT = 1
DEFAULT_ROOT = Path("output") / "saved_runs"
PORTFOLIO_FRAMES = (("historical", "portfolio_history"), ("paths", "portfolio_bands"), ("outcomes", "portfolio_outcomes"),
                    ("summary", "portfolio_summary"))
STRATEGY_FRAMES = ("retirement_paths", "retirement_annual", "account_bands", "path_series")


class SavedRunError(ValueError):
    """A folder that is not a saved run this version can open, or cannot be replaced by one."""


def _parquet(frame: pd.DataFrame, file: Path) -> None:
    """Write ``frame``; its datetime columns' units go in the file's metadata, since Parquet has no seconds unit."""
    units = {c: str(t) for c, t in frame.dtypes.items() if str(t).startswith("datetime64")}
    table = pa.Table.from_pandas(frame, preserve_index=False)
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), b"datetime_dtypes": json.dumps(units)})
    pq.write_table(table, file, compression="zstd")


def _read(file: Path) -> pd.DataFrame:
    table = pq.read_table(file)
    frame = table.to_pandas()
    for column, dtype in json.loads((table.schema.metadata or {}).get(b"datetime_dtypes", b"{}")).items():
        frame[column] = frame[column].astype(dtype)
    return frame


def _json(value, file: Path) -> None:
    file.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")


def saved_folder(plan_name: str, root: str | Path = DEFAULT_ROOT) -> Path:
    """Where the results of the plan called ``plan_name`` are saved: one folder per plan name, like plan files."""
    return Path(root) / slug(plan_name)


def save_run(run: PlanRun, root: str | Path = DEFAULT_ROOT, *, full_ledgers: bool = False, progress=None,
             workers: int | None = None, label: str = "") -> Path:
    """Save ``run`` (any strategy's ``PlanRun``; every compared strategy is saved) and return its folder.

    With ``full_ledgers`` every calculated path's daily ledger is re-run on the run's own draws and stored too:
    about 1 MB per path per strategy for a 50-year plan; it can take longer than the run.
    ``progress(fraction, message)`` reports the stages.

    The folder is ``<root>/<plan-name>/``, so saving a plan's results again replaces its earlier save (ADR 0053). The
    new save is written under a hidden partial name first and replaces the old one only when complete, so an
    interrupted save leaves the earlier one as it was. A folder there that is not a saved run is never replaced.
    """
    tell = progress or (lambda fraction, message: None)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    strategies = run.strategies or {run.rule: run}
    first = next(iter(strategies.values()))
    when = datetime.now().astimezone()
    folder = saved_folder(first.plan["plan"]["name"], root)
    partial, old = root / f".{folder.name}.partial", root / f".{folder.name}.old"
    if old.exists() and not folder.exists():  # a save stopped between its two renames: put the earlier one back
        old.rename(folder)
    if folder.exists() and not (folder / "run.json").is_file():
        raise SavedRunError(f"{folder} exists but is not a saved run; move it before saving results there.")
    for leftover in (partial, old):  # an unfinished new save, or an earlier save already replaced
        shutil.rmtree(leftover, ignore_errors=True)
    partial.mkdir()
    try:
        tell(0.0, "Saving the market and portfolio results")
        market, portfolios = first.market, first.portfolios
        returns = pd.DataFrame(np.asarray(market.path.returns), columns=list(market.path.assets))
        returns.insert(0, "Date", list(market.path.dates[1:]))
        _parquet(returns, partial / "market_returns.parquet")
        _parquet(market.asset_summary, partial / "asset_summary.parquet")
        indices = np.asarray(portfolios.indices, dtype=np.int32)
        np.savez_compressed(partial / "portfolio_draws.npz",
                            dates=np.array([d.toordinal() for d in portfolios.dates], dtype=np.int32),
                            opening=market.path.dates[0].toordinal(), first=indices[:, :1],
                            steps=np.diff(indices, axis=1))
        for attribute, name in PORTFOLIO_FRAMES:
            _parquet(getattr(portfolios, attribute), partial / f"{name}.parquet")
        index = {}
        for n, (rule, each) in enumerate(strategies.items()):
            tell(0.1 + 0.1 * n / len(strategies), f"Saving the {rule.replace('_', ' ')} results")
            own = partial / "strategies" / rule
            own.mkdir(parents=True)
            for name in STRATEGY_FRAMES:
                frame = each.account_bands if name == "account_bands" else getattr(each, name)
                _parquet(frame, own / f"{name}.parquet")
            daily, events, record = ledger_parts(each.representative_path, each.result)
            write_ledgers([(each.representative_path, daily, events, record)], own / "representative")
            index[rule] = {"folder": f"strategies/{rule}", "representative_path": each.representative_path,
                           "notes": each.notes, "full_ledgers": 0}
        if full_ledgers:
            plans = [each.plan for each in strategies.values()]
            total = len(plans) * first.plan["market"]["retirement_paths"]

            def ledgers(done, count):
                tell(0.2 + 0.75 * done / count, f"Re-running and saving every path's daily ledger: {done} of {count}")

            tell(0.2, f"Re-running and saving every path's daily ledger: 0 of {total}")
            stored = store_all_ledgers(plans, market, portfolios,
                                       {rule: partial / "strategies" / rule / "ledgers" for rule in strategies},
                                       partial / "scratch", ledgers, workers)
            for rule, count in stored.items():
                index[rule]["full_ledgers"] = count
        tell(0.97, "Writing the manifest")
        (partial / "plan.toml").write_text(plan_to_toml(first.plan), encoding="utf-8", newline="\n")
        _json({"format": FORMAT, "saved_at": when.isoformat(timespec="seconds"), "label": label,
               "plan": first.plan, "rules": first.rules_manifest, "code": code_manifest(),
               "market": {"manifest": market.manifest, "income_yields": market.income_yields,
                          "currency": market.path.currency},
               "portfolios": {"combined_shares": portfolios.combined_shares,
                              "retirement_start": portfolios.retirement_start.isoformat()},
               "full_ledgers": bool(full_ledgers), "strategies": index}, partial / "run.json")
        if folder.exists():
            folder.rename(old)
        partial.rename(folder)
    except BaseException:
        if old.exists() and not folder.exists():
            old.rename(folder)
        shutil.rmtree(partial, ignore_errors=True)
        raise
    shutil.rmtree(old, ignore_errors=True)
    tell(1.0, "Saved")
    return folder


def _manifest(folder: Path) -> dict:
    file = Path(folder) / "run.json"
    if not file.is_file():
        raise SavedRunError(f"{folder} is not a saved run (no run.json).")
    manifest = json.loads(file.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise SavedRunError(f"{folder} was saved in format {manifest.get('format')}; this version opens format {FORMAT}.")
    return manifest


def _derived(own: Path, info: dict, plan: dict, base: dict) -> PlanRun:
    """One strategy's ``PlanRun`` from its stored frames; the bands and all-paths table come from them as in a run."""
    frames = {name: _read(own / f"{name}.parquet") for name in STRATEGY_FRAMES}
    outcomes, series = frames["retirement_paths"], frames["path_series"]
    bands = frames["account_bands"]
    retirement_bands = bands.loc[bands["Series"] == "Total wealth"].drop(columns="Series").reset_index(drop=True)
    status = outcomes.set_index("Path")["Status"]
    wealth = pd.DataFrame({"Date": series["Date"], "Path": series["Path"],
                           "Status": series["Path"].map(status).to_numpy(), "Total wealth": series["Total wealth"]})
    ledgers = LedgerStore(own / "ledgers") if (own / "ledgers").is_dir() else None
    return PlanRun(plan, LedgerStore(own / "representative").read(info["representative_path"]), info["notes"], None,
                   base["rules"], base["market"], base["portfolios"], outcomes, retirement_bands,
                   int(info["representative_path"]), bands, frames["retirement_annual"], wealth, series, None,
                   saved_ledgers=ledgers, saved_from=base["folder"])


def load_run(folder: str | Path) -> PlanRun:
    """Open a saved run: the first compared strategy's ``PlanRun``, with every strategy's in ``strategies``."""
    folder = Path(folder)
    manifest = _manifest(folder)
    plan = manifest["plan"]
    returns = _read(folder / "market_returns.parquet")
    with np.load(folder / "portfolio_draws.npz") as stored:  # closed at once, so the folder can be replaced later
        draws = {name: stored[name] for name in stored.files}
    dates = (date.fromordinal(int(draws["opening"])), *(d.date() if hasattr(d, "date") else d for d in returns["Date"]))
    assets = tuple(c for c in returns.columns if c != "Date")
    path = MarketPath(dates, assets, returns[list(assets)].to_numpy(dtype=float), manifest["market"]["currency"])
    market = PlanMarketData(path, _read(folder / "asset_summary.parquet"), manifest["market"]["income_yields"],
                            manifest["market"]["manifest"])
    indices = np.concatenate([draws["first"], draws["first"] + np.cumsum(draws["steps"], axis=1, dtype=np.int64)],
                             axis=1).astype(np.int32)
    frames = {attribute: _read(folder / f"{name}.parquet") for attribute, name in PORTFOLIO_FRAMES}
    portfolios = PortfolioAnalysis(tuple(date.fromordinal(int(d)) for d in draws["dates"]), indices,
                                   frames["historical"], frames["paths"], frames["outcomes"], frames["summary"],
                                   manifest["portfolios"]["combined_shares"],
                                   date.fromisoformat(manifest["portfolios"]["retirement_start"]))
    base = {"rules": manifest["rules"], "market": market, "portfolios": portfolios, "folder": folder}
    strategies = {}
    for rule, info in manifest["strategies"].items():
        own_plan = {**plan, "spending": {**plan["spending"], "rule": rule}}
        strategies[rule] = _derived(folder / info["folder"], info, own_plan, base)
    # As in a run, every strategy's PlanRun points to one shared dictionary that holds them all.
    linked = {}
    linked.update({rule: replace(each, strategies=linked) for rule, each in strategies.items()})
    return next(iter(linked.values()))


def list_saved_runs(root: str | Path = DEFAULT_ROOT) -> list[dict]:
    """Saved runs under ``root``, newest first: folder, plan name, when, paths, strategies, ledgers, size, files."""
    root = Path(root)
    rows = []
    for folder in (sorted(root.iterdir()) if root.is_dir() else ()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        try:
            manifest = _manifest(folder)
        except (SavedRunError, ValueError, OSError):
            continue
        files = [f for f in folder.rglob("*") if f.is_file()]
        rows.append({"folder": folder, "name": manifest["plan"]["plan"]["name"], "saved_at": manifest["saved_at"],
                     "label": manifest.get("label", ""), "paths": manifest["plan"]["market"]["paths"],
                     "retirement_paths": manifest["plan"]["market"]["retirement_paths"],
                     "strategies": list(manifest["strategies"]), "full_ledgers": manifest.get("full_ledgers", False),
                     "code": manifest.get("code", {}), "bytes": sum(f.stat().st_size for f in files),
                     "files": len(files)})
    return sorted(rows, key=lambda row: row["saved_at"], reverse=True)


# Measured 12-13 November 2026 on a 50-year plan (Parquet, zstd): month-end balances and yearly rows take about
# 0.58 kB per retirement path per strategy per year; one path's full daily ledger and events about 21 kB per year;
# the delta-encoded draws about 0.02 kB per market path per year; the market history and portfolio tables ~3 MB.
SUMMARY_BYTES_PER_PATH_YEAR = 580
LEDGER_BYTES_PER_PATH_YEAR = 21_000
DRAW_BYTES_PER_PATH_YEAR = 20
FIXED_BYTES = 3_000_000


def estimate_bytes(plan: dict) -> tuple[int, int]:
    """About how large a saved run of ``plan`` is: without, and in addition for, every path's full ledger."""
    from financial_simulations.retirement.plan import horizon

    start, end, _ = horizon(plan)
    years = (end - start).days / 365.25
    market = plan["market"]
    strategies = len(plan["spending"]["compare"])
    ledgers = market["retirement_paths"] * strategies
    base = FIXED_BYTES + years * (market["paths"] * DRAW_BYTES_PER_PATH_YEAR + ledgers * SUMMARY_BYTES_PER_PATH_YEAR
                                  + strategies * LEDGER_BYTES_PER_PATH_YEAR)  # each strategy's median-path ledger
    return int(base), int(ledgers * years * LEDGER_BYTES_PER_PATH_YEAR)


def code_changed(saved_code: dict) -> bool:
    """Whether the model's Python source differs from the code that produced a saved run."""
    return saved_code.get("python_source_sha256") != code_manifest()["python_source_sha256"]
