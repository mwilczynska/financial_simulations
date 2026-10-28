"""Stage 1B daily generator comparison with bounded-memory no-flow accounting."""

from dataclasses import dataclass
from hashlib import sha256
import json
from io import BytesIO
from pathlib import Path
import tomllib

import numpy as np
import pandas as pd

from financial_simulations.data.datasets import load_datasets
from financial_simulations.dates import as_date
from financial_simulations.markets.resampling import (Sampler, complete_window_count, historical_draw,
                                                      integer, sample_indices)
from financial_simulations.portfolios.batch import compound_paths
from financial_simulations.runner import code_manifest
from financial_simulations.scenario import _keys, load_scenario


@dataclass(frozen=True)
class Comparison:
    scenario_file: Path
    horizons: tuple[int, ...]
    paths: int
    seeds: tuple[int, ...]
    block_lengths: tuple[int, ...]
    windows: tuple[dict, ...]
    batch_size: int
    trace_horizon: int
    trace_block_length: int
    calendar_file: Path | None
    manifest: dict


def load_comparison(path: str | Path) -> Comparison:
    path = Path(path).resolve()
    raw = path.read_bytes()
    config = tomllib.loads(raw.decode("utf-8"))
    _keys(config, {"comparison", "calibration"}, {"comparison", "calibration"}, "experiment")
    options, windows = config["comparison"], config["calibration"]
    required = {"scenario", "horizons", "paths", "seeds", "block_lengths", "trace_horizon", "trace_block_length"}
    _keys(options, required | {"batch_size", "calendar_file"}, required, "comparison")
    parsed = {}
    for key in ("horizons", "seeds", "block_lengths"):
        values = options[key]
        if not isinstance(values, list) or not values:
            raise ValueError(f"{key} must be a nonempty list.")
        parsed[key] = tuple(integer(v, key, 0 if key == "seeds" else 1) for v in values)
        if len(set(parsed[key])) != len(values):
            raise ValueError(f"{key} must contain distinct values.")
    if not isinstance(windows, list) or not windows:
        raise ValueError("Supply at least one calibration table.")
    canonical_windows = []
    for window in windows:
        _keys(window, {"name", "start", "end"}, {"name", "start", "end"}, "calibration")
        if not isinstance(window["name"], str) or not window["name"].strip():
            raise ValueError("Calibration names must be nonempty strings.")
        start, end = as_date(window["start"]).isoformat(), as_date(window["end"]).isoformat()
        if start > end:
            raise ValueError("Calibration start must not follow end.")
        canonical_windows.append({"name": window["name"], "start": start, "end": end})
    if len({w["name"] for w in canonical_windows}) != len(windows):
        raise ValueError("Calibration names must be distinct.")
    trace_horizon, trace_length = integer(options["trace_horizon"], "trace_horizon"), integer(options["trace_block_length"], "trace_block_length")
    if trace_horizon not in parsed["horizons"] or trace_length not in parsed["block_lengths"]:
        raise ValueError("Trace horizon and block length must be included in the comparison settings.")
    return Comparison((path.parent / options["scenario"]).resolve(), parsed["horizons"],
                      integer(options["paths"], "paths"), parsed["seeds"], parsed["block_lengths"],
                      tuple(canonical_windows), integer(options.get("batch_size", 64), "batch_size"),
                      trace_horizon, trace_length,
                      (path.parent / options["calendar_file"]).resolve() if "calendar_file" in options else None,
                      {"file": path.name, "sha256": sha256(raw).hexdigest(), "options": options,
                       "calibration": canonical_windows})


def autocorrelation(values, lag: int) -> float | None:
    values = np.asarray(values, dtype=float)
    if len(values) <= lag + 1:
        return None
    left, right = values[:-lag], values[lag:]
    left, right = left - left.mean(), right - right.mean()
    scale = np.linalg.norm(left) * np.linalg.norm(right)
    return float(left @ right / scale) if scale > 0 else None


def run_comparison(config: Comparison, output: str | Path) -> dict:
    scenario = load_scenario(config.scenario_file)
    if scenario.cash_flows or scenario.initial_value <= 0:
        raise ValueError("Stage 1B comparison requires positive opening investment and no dated cash flows.")
    base = load_datasets(scenario.data_root, scenario.portfolio.assets, scenario.start, scenario.end,
                         currency=scenario.portfolio.currency, file_format=scenario.file_format)
    if config.calendar_file is None:
        dates = base.path.dates
        calendar = {"policy": "shared_observed_accounting_template; not a future exchange-calendar forecast",
                    "source": base.manifest}
    else:
        raw = config.calendar_file.read_bytes()
        frame = pd.read_csv(BytesIO(raw), dtype=str)
        if list(frame.columns) != ["Date"]:
            raise ValueError("Target calendar CSV must have exactly one Date column.")
        dates = tuple(as_date(d) for d in frame["Date"])
        calendar = {"policy": "explicit_user_target_dates", "file": config.calendar_file.name,
                    "sha256": sha256(raw).hexdigest()}
    if len(dates) < max(config.horizons) + 1 or any(b <= a for a, b in zip(dates, dates[1:])):
        raise ValueError("Target calendar must be sorted, unique and cover every requested observation horizon.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"Date": dates[:max(config.horizons) + 1]}).to_csv(output / "target_calendar.csv", index=False, lineterminator="\n")
    summaries, outcomes, traces, diagnostics, correlations, inputs = [], [], [], [], [], []
    settings = [("historical_replay", None, None)]
    for seed in config.seeds:
        settings += [("independent", None, seed)]
        settings += [(method, length, seed) for method in ("moving_block", "stationary") for length in config.block_lengths]
    capital = scenario.initial_value + scenario.initial_cash
    case_id = 0
    for window_id, window in enumerate(config.windows):
        loaded = load_datasets(scenario.data_root, scenario.portfolio.assets, window["start"], window["end"],
                               currency=scenario.portfolio.currency, file_format=scenario.file_format)
        source = loaded.path
        n = len(source.returns)
        if max(config.block_lengths) > n:
            raise ValueError(f"Moving block length exceeds source observations in {window['name']}.")
        inputs.append({"name": window["name"], **loaded.manifest})
        for asset_id, asset in enumerate(source.assets):
            series = source.returns[:, asset_id]
            for lag in range(1, 22):
                diagnostics.append({"window": window["name"], "asset": asset, "lag": lag,
                                    "return_acf": autocorrelation(series, lag),
                                    "squared_return_acf": autocorrelation(series ** 2, lag)})
        for a, row in pd.DataFrame(source.returns, columns=source.assets).corr().iterrows():
            for b, value in row.items():
                correlations.append({"window": window["name"], "asset_a": a, "asset_b": b,
                                     "correlation": float(value) if np.isfinite(value) else None})
        for horizon in config.horizons:
            target = dates[:horizon + 1]
            complete = complete_window_count(n, horizon)
            for method, length, seed in settings:
                case_id += 1
                count = complete if method == "historical_replay" else config.paths
                metadata = {"case_id": case_id, "window": window["name"], "source_observations": n,
                            "horizon_observations": horizon, "method": method, "block_length": length,
                            "seed": seed, "paths": count, "complete_historical_windows": complete,
                            "target_opening": str(target[0]), "target_end": str(target[-1])}
                if count == 0:
                    summaries.append({**metadata, "status": "no_complete_window"})
                    continue
                trace_case = (window_id == 0 and horizon == config.trace_horizon and
                              (method == "historical_replay" or seed == config.seeds[0]) and
                              (length is None or length == config.trace_block_length))
                trace_ids = set((0, count // 2, count - 1) if method == "historical_replay" else range(min(count, 3))) if trace_case else set()
                terminal, drawdowns = [], []
                sampler = Sampler(method, length) if method != "historical_replay" else None
                for offset in range(0, count, config.batch_size):
                    ids = list(range(offset, min(count, offset + config.batch_size)))
                    draws = [historical_draw(n, horizon, i) if sampler is None else
                             sample_indices(n, horizon, sampler, seed=seed, path_id=i) for i in ids]
                    indices = np.stack([draw.indices for draw in draws])
                    wealth = compound_paths(source.returns[indices], target, scenario.portfolio,
                                            scenario.initial_value, initial_cash=scenario.initial_cash)
                    peaks = np.maximum.accumulate(wealth, axis=1)
                    ratios = np.divide(wealth, peaks, out=np.ones_like(wealth), where=peaks > 0)
                    maximum_dd = np.min(ratios - 1, axis=1)
                    terminal.extend(wealth[:, -1].tolist())
                    drawdowns.extend(maximum_dd.tolist())
                    for row_id, path_id in enumerate(ids):
                        outcomes.append({"case_id": case_id, "path_id": path_id,
                                         "terminal_value": float(wealth[row_id, -1]),
                                         "total_return": float(wealth[row_id, -1] / capital - 1),
                                         "max_drawdown": float(maximum_dd[row_id])})
                        if path_id in trace_ids:
                            draw = draws[row_id]
                            for step in range(horizon + 1):
                                donor = int(draw.indices[step - 1]) if step else None
                                traces.append({"case_id": case_id, "method": method, "path_id": path_id,
                                               "step": step, "target_date": str(target[step]),
                                               "source_previous_date": str(source.dates[donor]) if step else None,
                                               "source_date": str(source.dates[donor + 1]) if step else None,
                                               "donor_index": donor,
                                               "block_start": bool(draw.block_start[step - 1]) if step else False,
                                               "wrapped": bool(draw.wrapped[step - 1]) if step else False,
                                               "value": float(wealth[row_id, step])})
                quantiles = np.quantile(terminal, [0.05, 0.5, 0.95], method="linear")
                summaries.append({**metadata, "status": "ok", "terminal_p05": float(quantiles[0]),
                                  "terminal_median": float(quantiles[1]), "terminal_p95": float(quantiles[2]),
                                  "fraction_terminal_below_initial": float(np.mean(np.asarray(terminal) < capital)),
                                  "median_max_drawdown": float(np.median(drawdowns))})
    tables = {"summary.csv": pd.DataFrame(summaries), "outcomes.csv": pd.DataFrame(outcomes),
              "traces.csv": pd.DataFrame(traces), "dependence.csv": pd.DataFrame(diagnostics),
              "correlations.csv": pd.DataFrame(correlations)}
    for filename, table in tables.items():
        table.to_csv(output / filename, index=False, lineterminator="\n")
    manifest = {"schema_version": 1, "model": "stage_1b_joint_daily_v1", "code": code_manifest(),
                "effective_settings": {"horizons": config.horizons, "paths_per_seed": config.paths,
                                       "seeds": config.seeds, "block_lengths": config.block_lengths,
                                       "batch_size": config.batch_size, "trace_horizon": config.trace_horizon,
                                       "trace_block_length": config.trace_block_length},
                "experiment": config.manifest, "scenario": scenario.manifest, "calendar": calendar,
                "calibration_inputs": inputs, "cases": len(summaries), "paths_evaluated": len(outcomes),
                "trace_paths": len({(r["case_id"], r["path_id"]) for r in traces}),
                "rng": "PCG64/SeedSequence v1: [seed, method_code, block_length_or_zero, horizon, path_id]",
                "interpretation": "Conditional empirical scenarios; overlapping replays are dependent. No model averaging.",
                "scope": "Nominal common currency; no dated flows, new financing, inflation/FX or retirement rules."}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    from financial_simulations.reporting.comparison import write_comparison_plots

    write_comparison_plots(output, tables, config, scenario)
    return manifest
