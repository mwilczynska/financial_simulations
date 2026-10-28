"""Stage 1D studies: paired portfolios, source segments, tail diagnostics and rolling holdouts.

Every portfolio in a case compounds the same joint daily return draws, so
portfolio differences are paired comparisons within one generator. Generators
are reported side by side and never averaged.
"""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import tomllib

import numpy as np
import pandas as pd

from financial_simulations.data.datasets import CALENDAR_POLICIES, load_datasets
from financial_simulations.data.registry import resolve_asset
from financial_simulations.dates import as_date
from financial_simulations.evaluation import wilson_interval
from financial_simulations.markets.parametric import fit_lognormal
from financial_simulations.markets.path import MarketPath
from financial_simulations.markets.resampling import (Sampler, complete_window_count, historical_draw,
                                                      integer, sample_indices)
from financial_simulations.markets.volatility import INITIAL_VARIANCE, VolatilitySettings
from financial_simulations.portfolios.batch import compound_paths
from financial_simulations.portfolios.spec import PortfolioSpec
from financial_simulations.runner import code_manifest
from financial_simulations.scenario import _keys


METHODS = ("historical_replay", "independent", "moving_block", "stationary", "lognormal", "garch_fhs")
GENERATED = ("lognormal", "garch_fhs")
PROVENANCE = ("any", "observed", "reconstructed")


@dataclass(frozen=True)
class NamedPortfolio:
    name: str
    spec: PortfolioSpec


@dataclass(frozen=True)
class GeneratorSettings:
    methods: tuple[str, ...]
    block_length: int
    paths: int
    seeds: tuple[int, ...]
    batch_size: int
    observations_per_year: int
    volatility: VolatilitySettings
    diagnostic_paths: int


@dataclass(frozen=True)
class StudyBase:
    name: str
    data_root: Path
    file_format: str
    calendar_policy: str
    currency: str
    initial_value: float
    portfolios: tuple[NamedPortfolio, ...]
    reference: str
    generators: GeneratorSettings
    manifest: dict

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(a for p in self.portfolios for a in p.spec.assets))

    def load(self, start, end):
        return load_datasets(self.data_root, self.assets, start, end, currency=self.currency,
                             file_format=self.file_format, calendar_policy=self.calendar_policy)


@dataclass(frozen=True)
class PairedStudy:
    base: StudyBase
    horizons: tuple[int, ...]
    calendar_window: str
    windows: tuple[dict, ...]


@dataclass(frozen=True)
class HoldoutStudy:
    base: StudyBase
    horizons: tuple[int, ...]
    data_start: str
    data_end: str
    calibration_years: int
    mode: str
    first_origin_year: int
    step_years: int


def _nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string.")
    return value


def _distinct_integers(values, name, minimum=1):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{name} must be a nonempty list.")
    parsed = tuple(integer(v, name, minimum) for v in values)
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{name} must contain distinct values.")
    return parsed


def _load_base(path: Path, config: dict, extra: set[str]) -> StudyBase:
    _keys(config, {"study", "data", "portfolios", "generators"} | extra,
          {"study", "data", "portfolios", "generators"} | extra, "study file")
    study, data, generators = config["study"], config["data"], config["generators"]
    _keys(study, {"name", "initial_value", "currency", "reference"}, {"name", "initial_value", "currency", "reference"}, "study")
    _keys(data, {"root", "format", "calendar_policy"}, {"root"}, "data")
    policy = data.get("calendar_policy", "strict")
    if policy not in CALENDAR_POLICIES or data.get("format", "csv") not in ("csv", "parquet"):
        raise ValueError("Choose a supported calendar policy and csv or parquet input.")
    value = study["initial_value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0:
        raise ValueError("Study initial_value must be a positive finite number.")
    if not isinstance(config["portfolios"], list) or len(config["portfolios"]) < 2:
        raise ValueError("A study compares at least two portfolios.")
    portfolios = []
    for entry in config["portfolios"]:
        _keys(entry, {"name", "rebalance", "weights"}, {"name", "rebalance", "weights"}, "portfolios")
        portfolios.append(NamedPortfolio(_nonempty(entry["name"], "Portfolio name"),
                                         PortfolioSpec(entry["weights"], entry["rebalance"], study["currency"])))
    names = [p.name for p in portfolios]
    if len(set(names)) != len(names) or study["reference"] not in names:
        raise ValueError("Portfolio names must be distinct and include the reference portfolio.")
    _keys(generators, {"methods", "block_length", "paths", "seeds", "batch_size", "observations_per_year",
                       "initial_variance", "persistence_cap", "diagnostic_paths"},
          {"methods", "block_length", "paths", "seeds", "observations_per_year"}, "generators")
    methods = generators["methods"]
    if not isinstance(methods, list) or not methods or len(set(methods)) != len(methods) or set(methods) - set(METHODS):
        raise ValueError(f"Generator methods must be distinct values from {METHODS}.")
    initial = generators.get("initial_variance", "unconditional")
    cap = generators.get("persistence_cap", 0.999)
    if initial not in INITIAL_VARIANCE or isinstance(cap, bool) or not isinstance(cap, (int, float)) or not 0 < cap < 1:
        raise ValueError("GARCH initial_variance must be unconditional or last_fitted, with 0 < persistence_cap < 1.")
    settings = GeneratorSettings(tuple(methods), integer(generators["block_length"], "block_length"),
                                 integer(generators["paths"], "paths"),
                                 _distinct_integers(generators["seeds"], "seeds", 0),
                                 integer(generators.get("batch_size", 64), "batch_size"),
                                 integer(generators["observations_per_year"], "observations_per_year"),
                                 VolatilitySettings("garch_fhs", initial, float(cap)),
                                 integer(generators.get("diagnostic_paths", 128), "diagnostic_paths"))
    raw = path.read_bytes()
    manifest = {"file": path.name, "sha256": sha256(raw).hexdigest(), "config": config}
    return StudyBase(study["name"], (path.parent / data["root"]).resolve(), data.get("format", "csv"), policy,
                     study["currency"], float(value), tuple(portfolios), study["reference"], settings, manifest)


def load_paired(path: str | Path) -> PairedStudy:
    path = Path(path).resolve()
    config = tomllib.loads(path.read_bytes().decode("utf-8"))
    base = _load_base(path, config, {"paired", "windows"})
    paired, windows = config["paired"], config["windows"]
    _keys(paired, {"horizons", "calendar_window"}, {"horizons", "calendar_window"}, "paired")
    if not isinstance(windows, list) or not windows:
        raise ValueError("Supply at least one calibration window.")
    parsed = []
    for window in windows:
        _keys(window, {"name", "start", "end", "provenance", "provenance_assets"}, {"name", "start", "end"}, "windows")
        start, end = as_date(window["start"]).isoformat(), as_date(window["end"]).isoformat()
        provenance = window.get("provenance", "any")
        scope = window.get("provenance_assets", list(base.assets))
        if start > end or provenance not in PROVENANCE or not isinstance(scope, list) or not scope:
            raise ValueError("Windows need ordered dates, any/observed/reconstructed provenance and a nonempty asset scope.")
        scope = [resolve_asset(a).identifier for a in scope]
        if set(scope) - set(base.assets):
            raise ValueError("Provenance assets must be held by a study portfolio.")
        parsed.append({"name": _nonempty(window["name"], "Window name"), "start": start, "end": end,
                       "provenance": provenance, "provenance_assets": scope})
    if len({w["name"] for w in parsed}) != len(parsed) or paired["calendar_window"] not in {w["name"] for w in parsed}:
        raise ValueError("Window names must be distinct and include calendar_window.")
    return PairedStudy(base, _distinct_integers(paired["horizons"], "horizons"), paired["calendar_window"], tuple(parsed))


def load_holdout(path: str | Path) -> HoldoutStudy:
    path = Path(path).resolve()
    config = tomllib.loads(path.read_bytes().decode("utf-8"))
    base = _load_base(path, config, {"holdout"})
    if "historical_replay" in base.generators.methods:
        raise ValueError("A holdout's realised path is the replay; choose resampling or parametric generators.")
    options = config["holdout"]
    keys = {"horizons", "data_start", "data_end", "calibration_years", "mode", "first_origin_year", "step_years"}
    _keys(options, keys, keys, "holdout")
    if options["mode"] not in ("rolling", "expanding"):
        raise ValueError("Holdout mode must be rolling or expanding.")
    start, end = as_date(options["data_start"]), as_date(options["data_end"])
    years = integer(options["calibration_years"], "calibration_years")
    first = integer(options["first_origin_year"], "first_origin_year", 1900)
    if start >= end or first - years < start.year:
        raise ValueError("The first origin needs calibration_years of history after data_start.")
    return HoldoutStudy(base, _distinct_integers(options["horizons"], "horizons"), start.isoformat(), end.isoformat(),
                        years, options["mode"], first, integer(options["step_years"], "step_years"))


class FittedGenerators:
    """Generators fitted on one source path; draws are independent of portfolio weights."""

    def __init__(self, source: MarketPath, settings: GeneratorSettings):
        self.source, self.settings = source, settings
        self.lognormal = fit_lognormal(source, settings.observations_per_year) if "lognormal" in settings.methods else None
        self.garch = settings.volatility.fit(source, settings.observations_per_year) if "garch_fhs" in settings.methods else None

    def cases(self, horizon):
        """(method, seed, path count) per case; replay has no seed and counts complete windows."""
        for method in self.settings.methods:
            if method == "historical_replay":
                yield method, None, complete_window_count(len(self.source.returns), horizon)
            else:
                for seed in self.settings.seeds:
                    yield method, seed, self.settings.paths

    def batches(self, method, seed, horizon, count):
        n = len(self.source.returns)
        if method == "moving_block" and self.settings.block_length > n:
            raise ValueError("Moving block length exceeds source observations.")
        sampler = None
        if method in ("independent", "moving_block", "stationary"):
            sampler = Sampler(method, None if method == "independent" else self.settings.block_length)
        for offset in range(0, count, self.settings.batch_size):
            ids = list(range(offset, min(count, offset + self.settings.batch_size)))
            if method == "lognormal":
                yield ids, np.stack([self.lognormal.draw(horizon, seed=seed, path_id=i) for i in ids])
            elif method == "garch_fhs":
                yield ids, self.garch.draw_batch(horizon, seed=seed, path_ids=ids)
            else:
                draws = [historical_draw(n, horizon, i) if sampler is None else
                         sample_indices(n, horizon, sampler, seed=seed, path_id=i) for i in ids]
                yield ids, self.source.returns[np.stack([d.indices for d in draws])]

    def manifest(self):
        return {"lognormal": self.lognormal.manifest() if self.lognormal else None,
                "garch_fhs": self.garch.manifest() if self.garch else None}


def _columns(assets, portfolio):
    return [assets.index(a) for a in portfolio.spec.assets]


def max_drawdowns(wealth):
    peaks = np.maximum.accumulate(wealth, axis=1)
    return np.min(np.divide(wealth, peaks, out=np.ones_like(wealth), where=peaks > 0) - 1, axis=1)


def realised_volatility(wealth, basis):
    with np.errstate(divide="ignore", invalid="ignore"):
        logs = np.diff(np.log(wealth), axis=1)
    return np.where(np.isfinite(logs).all(axis=1), logs.std(axis=1, ddof=1) * np.sqrt(basis), np.nan)


def _quantiles(values, prefix):
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    q = np.quantile(finite, [0.05, 0.5, 0.95], method="linear") if len(finite) else [np.nan] * 3
    return {f"{prefix}_p05": float(q[0]), f"{prefix}_median": float(q[1]), f"{prefix}_p95": float(q[2])}


def series_statistics(logs, basis):
    """Daily log-return distribution and clustering statistics for a (paths, steps) panel."""
    logs = np.atleast_2d(np.asarray(logs, dtype=float))
    flat = logs.ravel()
    centred = flat - flat.mean()
    variance = float(np.mean(centred ** 2))
    squared = logs ** 2 - (logs ** 2).mean(axis=1, keepdims=True)
    denominator = (squared ** 2).sum(axis=1)
    acf = np.array([np.divide((squared[:, :-lag] * squared[:, lag:]).sum(axis=1), denominator,
                              out=np.full(len(logs), np.nan), where=denominator > 0) for lag in range(1, 22)])
    defined = np.isfinite(acf).any(axis=1)
    window = min(63, logs.shape[1])
    cumulative = np.cumsum(np.pad(logs, ((0, 0), (1, 0))), axis=1)
    cumulative_sq = np.cumsum(np.pad(logs ** 2, ((0, 0), (1, 0))), axis=1)
    sums = cumulative[:, window:] - cumulative[:, :-window]
    sums_sq = cumulative_sq[:, window:] - cumulative_sq[:, :-window]
    rolling = np.sqrt(np.maximum(sums_sq / window - (sums / window) ** 2, 0) * basis)
    simple = np.expm1(flat)
    return {"observations": int(flat.size), "annual_log_growth": float(flat.mean() * basis),
            "annual_volatility": float(np.sqrt(variance * basis)),
            "volatility_drag": float((simple.mean() - flat.mean()) * basis),
            "skewness": float(np.mean(centred ** 3) / variance ** 1.5) if variance > 0 else None,
            "excess_kurtosis": float(np.mean(centred ** 4) / variance ** 2 - 3) if variance > 0 else None,
            "worst_day": float(simple.min()), "q001_day": float(np.quantile(simple, 0.001)),
            "q01_day": float(np.quantile(simple, 0.01)),
            "squared_acf_sum_21": float(np.nanmean(acf[defined], axis=1).sum()) if defined.all() else None,
            "rolling63_vol_p05": float(np.quantile(rolling, 0.05)),
            "rolling63_vol_p95": float(np.quantile(rolling, 0.95))}


def _window_statistics(name, loaded, basis):
    rows = []
    source, provenance = loaded.path, loaded.provenance
    for i, asset in enumerate(source.assets):
        logs = np.log1p(source.returns[:, i])
        counts = provenance[f"provenance_{asset}"].value_counts()
        rows.append({"window": name, "asset": asset, "opening": str(source.dates[0]), "last": str(source.dates[-1]),
                     **{f"intervals_{k}": int(counts.get(k, 0)) for k in ("observed", "reconstructed", "mixed", "unclassified")},
                     "multi_observation_intervals": int((provenance[f"source_steps_{asset}"] > 1).sum()),
                     **series_statistics(logs[None, :], basis)})
    correlations = pd.DataFrame(np.log1p(source.returns), columns=source.assets).corr()
    return rows, [{"window": name, "asset_a": a, "asset_b": b, "log_return_correlation": float(v)}
                  for a, row in correlations.iterrows() for b, v in row.items()]


def check_provenance(window, loaded):
    """Fail unless every return interval of every scoped asset has the required class."""
    if window["provenance"] == "any":
        return
    for asset in window["provenance_assets"]:
        labels = loaded.provenance[f"provenance_{asset}"]
        if not (labels == window["provenance"]).all():
            bad = labels[labels != window["provenance"]]
            raise ValueError(f"Window {window['name']}: {asset} has {len(bad)} intervals not {window['provenance']}, "
                             f"first {bad.index[0].date()} ({bad.iloc[0]}).")


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8", newline="\n")


def _save(output, tables):
    for filename, table in tables.items():
        table.to_csv(output / filename, index=False, lineterminator="\n")


def run_paired(study: PairedStudy, output: str | Path) -> dict:
    base, settings = study.base, study.base.generators
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    calendar_spec = next(w for w in study.windows if w["name"] == study.calendar_window)
    template = base.load(calendar_spec["start"], calendar_spec["end"]).path.dates
    if len(template) < max(study.horizons) + 1:
        raise ValueError("The calendar window must cover the longest horizon.")
    pd.DataFrame({"Date": template[:max(study.horizons) + 1]}).to_csv(output / "target_calendar.csv", index=False, lineterminator="\n")
    reference = next(p for p in base.portfolios if p.name == base.reference)
    others = [p for p in base.portfolios if p is not reference]
    outcomes, summaries, pairs, statistics, correlations, diagnostics, inputs, fits = [], [], [], [], [], [], [], []
    case_id = 0
    for window in study.windows:
        loaded = base.load(window["start"], window["end"])
        check_provenance(window, loaded)
        source = loaded.path
        inputs.append({"window": window, **loaded.manifest})
        rows, corr = _window_statistics(window["name"], loaded, settings.observations_per_year)
        statistics += rows
        correlations += corr
        generators = FittedGenerators(source, settings)
        fits.append({"window": window["name"], **generators.manifest()})
        for name, series in _historical_diagnostics(source, base, settings):
            diagnostics.append({"window": window["name"], "method": "historical", "series": name, **series})
        for horizon in study.horizons:
            target = template[:horizon + 1]
            for method, seed, count in generators.cases(horizon):
                case_id += 1
                metadata = {"case_id": case_id, "window": window["name"], "horizon_observations": horizon,
                            "method": method, "block_length": settings.block_length if method in ("moving_block", "stationary") else None,
                            "seed": seed, "paths": count, "source_observations": len(source.returns)}
                if count == 0:
                    summaries.append({**metadata, "portfolio": None, "status": "no_complete_window"})
                    continue
                terminal = {p.name: [] for p in base.portfolios}
                drawdown = {p.name: [] for p in base.portfolios}
                diagnostic_logs = {}
                diagnose = horizon == max(study.horizons) and method != "historical_replay" and seed == settings.seeds[0]
                for ids, returns in generators.batches(method, seed, horizon, count):
                    for portfolio in base.portfolios:
                        wealth = compound_paths(returns[:, :, _columns(source.assets, portfolio)], target,
                                                portfolio.spec, base.initial_value)
                        terminal[portfolio.name].extend(wealth[:, -1].tolist())
                        drawdown[portfolio.name].extend(max_drawdowns(wealth).tolist())
                        if diagnose and ids[0] < settings.diagnostic_paths:
                            keep = [k for k, i in enumerate(ids) if i < settings.diagnostic_paths]
                            diagnostic_logs.setdefault(portfolio.name, []).append(np.diff(np.log(wealth[keep]), axis=1))
                    if diagnose and ids[0] < settings.diagnostic_paths:
                        keep = [k for k, i in enumerate(ids) if i < settings.diagnostic_paths]
                        for a, asset in enumerate(source.assets):
                            diagnostic_logs.setdefault(asset, []).append(np.log1p(returns[keep, :, a]))
                for name, panels in diagnostic_logs.items():
                    diagnostics.append({"window": window["name"], "method": method, "series": name,
                                        **series_statistics(np.concatenate(panels), settings.observations_per_year)})
                frame = pd.DataFrame({"case_id": case_id, "path_id": range(count),
                                      **{f"terminal__{p}": v for p, v in terminal.items()},
                                      **{f"max_drawdown__{p}": v for p, v in drawdown.items()}})
                outcomes.append(frame)
                independent = method != "historical_replay"
                for portfolio in base.portfolios:
                    values = np.asarray(terminal[portfolio.name])
                    summaries.append({**metadata, "portfolio": portfolio.name, "status": "ok",
                                      **_quantiles(values, "terminal"),
                                      **_quantiles(drawdown[portfolio.name], "max_drawdown"),
                                      "fraction_below_initial": float(np.mean(values < base.initial_value))})
                ref_terminal, ref_dd = np.asarray(terminal[reference.name]), np.asarray(drawdown[reference.name])
                for other in others:
                    values, dd = np.asarray(terminal[other.name]), np.asarray(drawdown[other.name])
                    wins = int(np.count_nonzero(values > ref_terminal))
                    low, high = wilson_interval(wins, count, 0.95) if independent else (None, None)
                    with np.errstate(divide="ignore", invalid="ignore"):
                        ratio = np.log(values / ref_terminal)
                    pairs.append({**metadata, "portfolio": other.name, "reference": reference.name,
                                  "fraction_outperforms_reference": wins / count,
                                  "fraction_ties": float(np.mean(values == ref_terminal)),
                                  "outperform_ci_low": low, "outperform_ci_high": high,
                                  "sampling_error_status": "conditional_independent_simulations" if independent
                                  else "dependent_replay_descriptive_only",
                                  "nonfinite_log_ratios": int((~np.isfinite(ratio)).sum()),
                                  **_quantiles(ratio, "log_wealth_ratio"),
                                  "fraction_shallower_drawdown": float(np.mean(dd > ref_dd)),
                                  **_quantiles(dd - ref_dd, "drawdown_difference")})
    tables = {"paired_summary.csv": pd.DataFrame(summaries), "paired_differences.csv": pd.DataFrame(pairs),
              "window_statistics.csv": pd.DataFrame(statistics), "window_correlations.csv": pd.DataFrame(correlations),
              "tail_diagnostics.csv": pd.DataFrame(diagnostics)}
    _save(output, tables)
    pd.concat(outcomes, ignore_index=True).to_csv(output / "paired_outcomes.csv", index=False, lineterminator="\n")
    _write_json(output / "calibration.json", fits)
    manifest = {"schema_version": 1, "model": "stage_1d_paired_studies_v1", "code": code_manifest(),
                "study": base.manifest, "calendar_policy": base.calendar_policy,
                "target_calendar": {"window": study.calendar_window, "observations": max(study.horizons) + 1,
                                    "policy": "shared observed accounting template; not a future exchange calendar"},
                "inputs": inputs, "cases": case_id, "paths_evaluated": int(sum(len(f) for f in outcomes)),
                "rng": {"empirical": "PCG64/SeedSequence v1: [seed, method_code, block_length_or_zero, horizon, path_id]",
                        "lognormal": "[seed, 4, horizon, path_id]", "garch_fhs": "[seed, 5, horizon, path_id]"},
                "pairing": "All portfolios compound identical joint daily draws within each case.",
                "interpretation": "Conditional generator results; no model averaging. Replay windows overlap and are descriptive.",
                "scope": "Nominal common currency; no dated flows, inflation/FX or retirement rules."}
    _write_json(output / "manifest.json", manifest)
    from financial_simulations.reporting.studies import write_paired_plots

    write_paired_plots(output, tables, study)
    return manifest


def _historical_diagnostics(source, base, settings):
    for a, asset in enumerate(source.assets):
        yield asset, series_statistics(np.log1p(source.returns[None, :, a]), settings.observations_per_year)
    for portfolio in base.portfolios:
        wealth = compound_paths(source.returns[None][:, :, _columns(source.assets, portfolio)], source.dates,
                                portfolio.spec, base.initial_value)
        yield portfolio.name, series_statistics(np.diff(np.log(wealth), axis=1), settings.observations_per_year)


def pit(generated, realised):
    """Mid-rank probability integral transform of a realised value within generated values."""
    generated = np.asarray(generated, dtype=float)
    generated = generated[np.isfinite(generated)]
    if not len(generated) or not np.isfinite(realised):
        return None
    return float((np.count_nonzero(generated < realised) + 0.5 * np.count_nonzero(generated == realised)) / len(generated))


def holdout_origins(dates, study: HoldoutStudy):
    """Origin and calibration start per year; an origin is the year's first observation.

    Calibration uses returns ending at or before the origin; the holdout's
    returns all end after it. Rolling windows start at the first observation of
    the year calibration_years earlier; expanding windows at the data start.
    """
    ordinal = np.array(dates, dtype="datetime64[D]")
    rows = []
    year = study.first_origin_year
    while True:
        origin = int(np.searchsorted(ordinal, np.datetime64(date(year, 1, 1))))
        if origin >= len(dates) - 1:
            return rows
        start = 0 if study.mode == "expanding" else int(np.searchsorted(ordinal, np.datetime64(date(year - study.calibration_years, 1, 1))))
        rows.append({"origin_year": year, "origin": origin, "calibration_start": start})
        year += study.step_years


def _portfolio_provenance(provenance, portfolio, rows):
    labels = provenance.iloc[rows][[f"provenance_{a}" for a in portfolio.spec.assets]]
    return float((labels == "observed").all(axis=1).mean())


def run_holdout(study: HoldoutStudy, output: str | Path) -> dict:
    base, settings = study.base, study.base.generators
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    loaded = base.load(study.data_start, study.data_end)
    full = loaded.path
    basis = settings.observations_per_year
    folds, generated_rows, fits = [], [], []
    for origin in holdout_origins(full.dates, study):
        o, s = origin["origin"], origin["calibration_start"]
        complete = [h for h in study.horizons if o + h <= len(full.returns)]
        generators = FittedGenerators(MarketPath(full.dates[s:o + 1], full.assets, full.returns[s:o], full.currency),
                                      settings) if complete else None
        if generators:
            fits.append({"origin_date": str(full.dates[o]), "calibration_start": str(full.dates[s]), **generators.manifest()})
        for horizon in study.horizons:
            fold = {"horizon_observations": horizon, "origin_year": origin["origin_year"],
                    "origin_date": str(full.dates[o]), "calibration_start": str(full.dates[s]),
                    "calibration_observations": o - s}
            if horizon not in complete:
                folds.append({**fold, "status": "incomplete_holdout"})
                continue
            target = full.dates[o:o + horizon + 1]
            realised_returns = full.returns[None, o:o + horizon]
            realised = {}
            for portfolio in base.portfolios:
                wealth = compound_paths(realised_returns[:, :, _columns(full.assets, portfolio)], target,
                                        portfolio.spec, base.initial_value)
                realised[portfolio.name] = {"terminal": float(wealth[0, -1]), "max_drawdown": float(max_drawdowns(wealth)[0]),
                                            "realised_volatility": float(realised_volatility(wealth, basis)[0])}
            for method, seed, count in generators.cases(horizon):
                metrics = {p.name: {"terminal": [], "max_drawdown": [], "realised_volatility": []} for p in base.portfolios}
                for ids, returns in generators.batches(method, seed, horizon, count):
                    for portfolio in base.portfolios:
                        wealth = compound_paths(returns[:, :, _columns(full.assets, portfolio)], target,
                                                portfolio.spec, base.initial_value)
                        metrics[portfolio.name]["terminal"].extend(wealth[:, -1].tolist())
                        metrics[portfolio.name]["max_drawdown"].extend(max_drawdowns(wealth).tolist())
                        metrics[portfolio.name]["realised_volatility"].extend(realised_volatility(wealth, basis).tolist())
                for portfolio in base.portfolios:
                    row = {**fold, "status": "ok", "method": method, "seed": seed, "paths": count,
                           "block_length": settings.block_length if method in ("moving_block", "stationary") else None,
                           "portfolio": portfolio.name,
                           "calibration_observed_fraction": _portfolio_provenance(loaded.provenance, portfolio, range(s, o)),
                           "holdout_observed_fraction": _portfolio_provenance(loaded.provenance, portfolio, range(o, o + horizon))}
                    for metric, values in metrics[portfolio.name].items():
                        row[f"realised_{metric}"] = realised[portfolio.name][metric]
                        row.update(_quantiles(values, f"generated_{metric}"))
                        row[f"pit_{metric}"] = pit(values, realised[portfolio.name][metric])
                    folds.append(row)
                    generated_rows.append(pd.DataFrame({"horizon_observations": horizon, "origin_date": fold["origin_date"],
                                                        "method": method, "seed": seed, "portfolio": portfolio.name,
                                                        "path_id": range(count), **metrics[portfolio.name]}))
    folds = pd.DataFrame(folds)
    summary = holdout_summary(folds, study)
    tables = {"holdout_folds.csv": folds, "holdout_summary.csv": summary}
    _save(output, tables)
    pd.concat(generated_rows, ignore_index=True).to_csv(output / "holdout_generated.csv", index=False, lineterminator="\n")
    _write_json(output / "calibration.json", fits)
    manifest = {"schema_version": 1, "model": "stage_1d_rolling_holdout_v1", "code": code_manifest(),
                "study": base.manifest, "calendar_policy": base.calendar_policy, "data": loaded.manifest,
                "scored_folds": int(folds.loc[folds["status"] == "ok", ["horizon_observations", "origin_date"]].drop_duplicates().shape[0]),
                "incomplete_folds": int((folds["status"] == "incomplete_holdout").sum()),
                "generated_paths": int(sum(len(g) for g in generated_rows)),
                "pit": "Mid-rank F_generated(realised): (count below + 0.5 count equal) / paths.",
                "interpretation": ("Each origin calibrates only on returns ending at or before it and scores the following "
                                   "realised holdout. Overlapping holdouts are dependent; non-overlapping counts are reported. "
                                   "A calibrated generator gives roughly uniform PIT values; coverage is descriptive."),
                "scope": "Nominal common currency; no dated flows, inflation/FX or retirement rules."}
    _write_json(output / "manifest.json", manifest)
    from financial_simulations.reporting.studies import write_holdout_plots

    write_holdout_plots(output, tables, study)
    return manifest


def holdout_summary(folds: pd.DataFrame, study: HoldoutStudy) -> pd.DataFrame:
    rows = []
    scored = folds[folds["status"] == "ok"] if "status" in folds else folds.iloc[0:0]
    for (horizon, method, portfolio), group in scored.groupby(["horizon_observations", "method", "portfolio"], sort=False):
        # Holdouts of horizon/basis years overlap unless origins are at least that far apart.
        spacing = max(1, int(np.ceil(horizon / study.base.generators.observations_per_year / study.step_years)))
        group = group.sort_values("origin_year")
        for metric in ("terminal", "max_drawdown", "realised_volatility"):
            values = group[f"pit_{metric}"].dropna().to_numpy(dtype=float)
            if not len(values):
                continue
            ordered = np.sort(values)
            n = len(ordered)
            ks = float(max(np.max(np.arange(1, n + 1) / n - ordered), np.max(ordered - np.arange(n) / n)))
            rows.append({"horizon_observations": horizon, "method": method, "portfolio": portfolio, "metric": metric,
                         "folds": n, "non_overlapping_folds": int(len(values[::spacing])),
                         "mean_pit": float(values.mean()), "fraction_pit_below_0_05": float(np.mean(values < 0.05)),
                         "fraction_pit_above_0_95": float(np.mean(values > 0.95)),
                         "central_90_coverage": float(np.mean((values >= 0.05) & (values <= 0.95))),
                         "ks_distance_from_uniform": ks,
                         "non_overlapping_central_90_coverage": float(np.mean((values[::spacing] >= 0.05) & (values[::spacing] <= 0.95)))})
    return pd.DataFrame(rows)
