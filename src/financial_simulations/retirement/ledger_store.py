"""Daily tax ledgers stored as Parquet: one row group per path, so one path reads back without the rest (ADR 0050).

Kept apart from ``saved_runs`` so that worker processes import only the ledger, plan and storage code, not the
plotting and reporting libraries.

A stored ledger set is three files in one folder:

- ``daily.parquet``: every path's daily ledger rows, with a ``path`` column, one row group per path;
- ``events.parquet``: every path's event log, likewise (a path with no events has no row group);
- ``years.json``: each path's financial-year records, outstanding liabilities, own columns and row groups.

Paths can have different columns (an event field that never occurs on one path is absent from its frame). Each file
uses the union of every path's columns, and each path reads back with only its own columns, in its own order.
"""

from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from financial_simulations.retirement.ledger import LedgerResult, run_ledger
from financial_simulations.retirement.plan import build_inputs
from financial_simulations.rules.au.parameters import UnsupportedRule
from financial_simulations.rules.au.tax import TaxAssessment


DAILY, EVENTS, YEARS = "daily.parquet", "events.parquet", "years.json"
COMPRESSION = "zstd"


def _plain(value):
    """JSON-ready copies of the ledger's yearly records: numpy scalars to Python, dataclasses to dicts."""
    if isinstance(value, TaxAssessment):
        return {"__tax_assessment__": _plain(asdict(value))}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _restore(value):
    if isinstance(value, dict):
        if set(value) == {"__tax_assessment__"}:
            return TaxAssessment(**_restore(value["__tax_assessment__"]))
        return {k: _restore(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_restore(v) for v in value]
    return value


def ledger_parts(path: int, result: LedgerResult) -> tuple[pa.Table, pa.Table, dict]:
    """One path's ledger as a daily table, an event table and its JSON-ready yearly records."""
    daily = result.daily.reset_index()
    daily.insert(0, "path", np.int32(path))
    events = result.events.copy()
    events.insert(0, "path", np.int32(path))
    record = {"annual": _plain(result.annual), "outstanding": _plain(result.outstanding),
              "daily_index": result.daily.index.name, "daily_index_dtype": str(result.daily.index.dtype),
              "daily_columns": list(result.daily.columns),
              "events_columns": list(result.events.columns)}
    return (pa.Table.from_pandas(daily, preserve_index=False), pa.Table.from_pandas(events, preserve_index=False),
            record)


def _schema(sources) -> pa.Schema:
    schemas = [pq.read_schema(s) if isinstance(s, (str, Path)) else s.schema for s in sources]
    return pa.unify_schemas([s.remove_metadata() for s in schemas], promote_options="permissive")


def _conform(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """``table`` with every column of ``schema`` (absent ones as nulls), in its order and types."""
    columns = [table.column(f.name) if f.name in table.column_names else pa.nulls(len(table), f.type) for f in schema]
    return pa.Table.from_arrays(columns, schema=schema.remove_metadata()).cast(schema.remove_metadata())


def write_ledgers(items, folder: str | Path) -> None:
    """Write ``items`` of ``(path, daily, events, record)`` as one stored ledger set in ``folder``.

    ``daily`` and ``events`` are Arrow tables or Parquet files holding one path each. Files are read twice, once
    for their columns and once to copy their rows, so memory stays at one path at a time.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    items = sorted(items, key=lambda item: item[0])
    records = {}
    for position, name in ((1, DAILY), (2, EVENTS)):
        sources = [item[position] for item in items]
        schema = _schema(sources)
        group = 0
        with pq.ParquetWriter(folder / name, schema, compression=COMPRESSION) as writer:
            for item, source in zip(items, sources):
                table = pq.read_table(source) if isinstance(source, (str, Path)) else source
                record = records.setdefault(item[0], dict(item[3]))
                if len(table):
                    writer.write_table(_conform(table, schema), row_group_size=len(table))
                    record[f"{name.split('.')[0]}_row_group"] = group
                    group += 1
                else:
                    record[f"{name.split('.')[0]}_row_group"] = None
    (folder / YEARS).write_text(json.dumps({"paths": {str(p): r for p, r in records.items()}}) + "\n", encoding="utf-8",
                                newline="\n")


class LedgerStore:
    """Read stored ledgers back one path at a time."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.records = {int(p): r for p, r in
                        json.loads((self.folder / YEARS).read_text(encoding="utf-8"))["paths"].items()}

    @property
    def paths(self) -> list[int]:
        return sorted(self.records)

    def __contains__(self, path) -> bool:
        return int(path) in self.records

    def _frame(self, name: str, group, columns) -> pd.DataFrame:
        if group is None:
            return pd.DataFrame(columns=columns)
        file = pq.ParquetFile(self.folder / name)
        try:
            return file.read_row_group(group).to_pandas()[columns]
        finally:
            file.close()

    def read(self, path: int) -> LedgerResult:
        record = self.records[int(path)]
        index = record["daily_index"]
        daily = self._frame(DAILY, record["daily_row_group"], [index, *record["daily_columns"]])
        # Parquet keeps timestamps in milliseconds at the coarsest; restore the ledger's own unit.
        daily[index] = daily[index].astype(record["daily_index_dtype"])
        daily = daily.set_index(index)
        events = self._frame(EVENTS, record["events_row_group"], record["events_columns"])
        return LedgerResult(daily, events, _restore(record["annual"]), _restore(record["outstanding"]))


def _store_chunk(plans, market, indices, paths, scratch):
    """Worker: run every strategy's ledger on several shared draws and write each one to ``scratch``.

    Returns ``(rule, path, record)`` triples; ``record`` is ``None`` for a path the model cannot calculate.
    """
    scratch = Path(scratch)
    out = []
    for path, rows in zip(paths, indices):
        returns = market.path.returns[rows]
        for plan in plans:
            rule = plan["spending"]["rule"]
            inputs, scenario, years, _ = build_inputs(plan, market=market, returns=returns)
            try:
                result = run_ledger(inputs, scenario, years)
            except UnsupportedRule:
                out.append((rule, path, None))
                continue
            daily, events, record = ledger_parts(path, result)
            target = scratch / rule
            target.mkdir(parents=True, exist_ok=True)
            pq.write_table(daily, target / f"{path}_daily.parquet", compression=COMPRESSION)
            pq.write_table(events, target / f"{path}_events.parquet", compression=COMPRESSION)
            out.append((rule, path, record))
    return out


def store_all_ledgers(plans, market, portfolios, folders: dict, scratch: Path, progress=None, workers=None) -> dict:
    """Re-run every retirement path's ledger for each strategy and store them in ``folders[rule]``.

    The draws are the run's own (``portfolios.indices``), so each stored ledger is the one the run summarised.
    Each worker writes its paths to ``scratch``; they are then merged into one ledger set per strategy and the
    scratch files removed. Returns the stored path count by rule. ``progress(done, total)`` counts ledgers.
    """
    from financial_simulations.retirement.paths import _POOL, _pool, _without_main_module, worker_count
    from concurrent.futures import as_completed
    from concurrent.futures.process import BrokenProcessPool

    count = plans[0]["market"]["retirement_paths"]
    total = count * len(plans)
    if workers is None:
        workers = worker_count(total)[0]
    chunks = [c for c in np.array_split(np.arange(count), min(count, max(1, workers * 3))) if len(c)]
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    out = []
    if workers == 1:
        for chunk in chunks:
            out += _store_chunk(plans, market, portfolios.indices[chunk], chunk.tolist(), scratch)
            if progress:
                progress(len(out), total)
    else:
        pool = _pool(workers)
        with _without_main_module():
            futures = [pool.submit(_store_chunk, plans, market, portfolios.indices[chunk], chunk.tolist(), scratch)
                       for chunk in chunks]
        try:
            for future in as_completed(futures):
                out += future.result()
                if progress:
                    progress(len(out), total)
        except BrokenProcessPool:
            _POOL.clear()
            raise
    stored = {}
    for plan in plans:
        rule = plan["spending"]["rule"]
        items = [(path, scratch / rule / f"{path}_daily.parquet", scratch / rule / f"{path}_events.parquet", record)
                 for r, path, record in out if r == rule and record is not None]
        write_ledgers(items, folders[rule])
        stored[rule] = len(items)
        for _, daily, events, _ in items:
            daily.unlink()
            events.unlink()
        if (scratch / rule).is_dir():
            (scratch / rule).rmdir()
    scratch.rmdir()
    return stored
