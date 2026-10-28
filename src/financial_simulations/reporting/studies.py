"""Static PNGs for paired portfolios, source segments, tail diagnostics and holdouts."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter, NullLocator
import numpy as np


COLORS = ("#126a63", "#b76a42", "#8363a0", "#386a98", "#9a8a2e", "#5b6770")
BACKGROUND = "#fafaf7"
MUTED = "#536369"
NAMES = {"historical_replay": "Complete replay", "independent": "Independent rows", "moving_block": "Moving blocks",
         "stationary": "Stationary bootstrap", "lognormal": "Lognormal", "garch_fhs": "GARCH-FHS",
         "historical": "Historical sample"}


def _method_label(method, block_length=None):
    label = NAMES.get(method, method)
    if method in ("moving_block", "stationary") and block_length is not None and np.isfinite(block_length):
        label += f" L={int(block_length)}"
    return label


def _money(x, _):
    return f"{x / 1e6:g}m" if x >= 1e6 else f"{x / 1000:g}k" if x >= 1000 else f"{x:g}"


def _log_axis(ax, axis="x", low=None, high=None):
    getattr(ax, f"set_{axis}scale")("log")
    target = ax.xaxis if axis == "x" else ax.yaxis
    # Narrow ranges need intermediate ticks, or a panel can show a single label.
    ratio = high / low if low is not None and high is not None and low > 0 else np.inf
    subs = (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8) if ratio < 3 else (1, 1.5, 2, 3, 5, 7) if ratio < 6 else (1, 2, 5)
    target.set_major_locator(LogLocator(base=10, subs=subs, numticks=12))
    target.set_minor_locator(NullLocator())
    target.set_minor_formatter(NullFormatter())


def _tidy(ax, grid="x"):
    ax.grid(axis=grid, alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)


def _header(figure, title, subtitle, *, y=0.975, gap=0.04):
    figure.suptitle(title, fontsize=17, fontweight="bold", x=0.035, ha="left", y=y)
    figure.text(0.035, y - gap, subtitle, color=MUTED, fontsize=9)


def _case_rows(subset):
    rows = subset.drop_duplicates(["method", "seed"])
    several = rows["seed"].dropna().nunique() > 1
    return [(r.method, r.seed, _method_label(r.method, r.block_length)
             + (f" | seed {int(r.seed)}" if several and r.seed == r.seed else "")) for r in rows.itertuples()]


def write_paired_plots(output: Path, tables: dict, study):
    summary = tables["paired_summary.csv"]
    summary = summary[summary["status"] == "ok"]
    differences = tables["paired_differences.csv"]
    base = study.base
    windows, horizons = [w["name"] for w in study.windows], list(study.horizons)
    portfolios = [p.name for p in base.portfolios]
    with matplotlib.rc_context({"font.family": "DejaVu Sans", "font.size": 9}):
        figure = Figure(figsize=(6.4 * len(windows) + 1.5, 3.6 * len(horizons) + 1.8), dpi=150, facecolor=BACKGROUND)
        axes = figure.subplots(len(horizons), len(windows), squeeze=False)
        figure.subplots_adjust(left=0.12, right=0.98, top=0.84, bottom=0.08, hspace=0.5, wspace=0.62)
        _header(figure, "Paired portfolio outcomes on shared daily draws",
                f"Dots: median terminal wealth | Bars: 5th-95th path percentiles | Opening {base.initial_value:,.0f} {base.currency} nominal")
        handles = [Line2D([], [], color=COLORS[i % len(COLORS)], marker="o", label=name) for i, name in enumerate(portfolios)]
        figure.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.03, 0.915), ncol=len(handles), frameon=False)
        for r, horizon in enumerate(horizons):
            for c, window in enumerate(windows):
                ax = axes[r, c]
                subset = summary[(summary["window"] == window) & (summary["horizon_observations"] == horizon)]
                cases = _case_rows(subset)
                for y, (method, seed, _) in enumerate(cases):
                    rows = subset[(subset["method"] == method) & ((subset["seed"] == seed) | (subset["seed"].isna() & (seed != seed)))]
                    for i, name in enumerate(portfolios):
                        row = rows[rows["portfolio"] == name]
                        if row.empty:
                            continue
                        row = row.iloc[0]
                        offset = (i - (len(portfolios) - 1) / 2) * 0.2
                        color = COLORS[i % len(COLORS)]
                        ax.plot([row["terminal_p05"], row["terminal_p95"]], [y + offset] * 2, color=color, linewidth=1.5)
                        ax.plot(row["terminal_median"], y + offset, "o", color=color, markersize=3.5)
                ax.set_yticks(range(len(cases)), [label for *_, label in cases], fontsize=8)
                ax.set_ylim(len(cases) - 0.5, -0.5)
                if not subset.empty and (subset["terminal_p05"] > 0).all():
                    _log_axis(ax, "x", subset["terminal_p05"].min(), subset["terminal_p95"].max())
                ax.xaxis.set_major_formatter(FuncFormatter(_money))
                ax.axvline(base.initial_value, color="#a4adae", linewidth=0.8, linestyle="--")
                ax.set_title(f"{window} | {horizon:,} observations", fontsize=10)
                ax.set_xlabel(f"Terminal nominal {base.currency} ({ax.get_xscale()} scale)", fontsize=8)
                _tidy(ax)
        figure.text(0.035, 0.025, "Every portfolio in a row compounds the same draws | Replay windows overlap and are descriptive | Generators are not averaged", fontsize=8)
        figure.savefig(output / "paired_terminal.png")

        others = [p for p in portfolios if p != base.reference]
        figure = Figure(figsize=(6.4 * len(windows) + 1.5, 3.6 * len(horizons) + 1.8), dpi=150, facecolor=BACKGROUND)
        axes = figure.subplots(len(horizons), len(windows), squeeze=False)
        figure.subplots_adjust(left=0.12, right=0.98, top=0.84, bottom=0.08, hspace=0.5, wspace=0.62)
        _header(figure, f"Terminal wealth relative to {base.reference}",
                "Pathwise ratio W / W_reference on identical draws | Dots: median | Bars: 5th-95th path percentiles | Labels: share of paths ahead")
        handles = [Line2D([], [], color=COLORS[(i + 1) % len(COLORS)], marker="o", label=name) for i, name in enumerate(others)]
        figure.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.03, 0.915), ncol=len(handles), frameon=False)
        for r, horizon in enumerate(horizons):
            for c, window in enumerate(windows):
                ax = axes[r, c]
                subset = differences[(differences["window"] == window) & (differences["horizon_observations"] == horizon)]
                cases = _case_rows(subset)
                for y, (method, seed, _) in enumerate(cases):
                    rows = subset[(subset["method"] == method) & ((subset["seed"] == seed) | (subset["seed"].isna() & (seed != seed)))]
                    for i, name in enumerate(others):
                        row = rows[rows["portfolio"] == name]
                        if row.empty:
                            continue
                        row = row.iloc[0]
                        offset = (i - (len(others) - 1) / 2) * 0.28
                        color = COLORS[(i + 1) % len(COLORS)]
                        low, mid, high = np.exp(row[["log_wealth_ratio_p05", "log_wealth_ratio_median", "log_wealth_ratio_p95"]].to_numpy(dtype=float))
                        ax.plot([low, high], [y + offset] * 2, color=color, linewidth=1.5)
                        ax.plot(mid, y + offset, "o", color=color, markersize=3.5)
                        ax.annotate(f"{row['fraction_outperforms_reference']:.0%}", (high, y + offset), xytext=(4, -3),
                                    textcoords="offset points", fontsize=7, color=color)
                ax.set_yticks(range(len(cases)), [label for *_, label in cases], fontsize=8)
                ax.set_ylim(len(cases) - 0.5, -0.5)
                _log_axis(ax, "x", np.exp(subset["log_wealth_ratio_p05"].min()), np.exp(subset["log_wealth_ratio_p95"].max()))
                ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:g}x"))
                ax.axvline(1, color="#8b989b", linewidth=0.8)
                ax.set_title(f"{window} | {horizon:,} observations", fontsize=10)
                ax.set_xlabel("Terminal wealth ratio to reference (log scale)", fontsize=8)
                _tidy(ax)
        figure.text(0.035, 0.025, "Shares ahead are conditional on each generator; generated-path intervals are in paired_differences.csv. Ratios left of 1x trail the reference.", fontsize=8)
        figure.savefig(output / "paired_differences.png")

        _segment_plot(output, tables["window_statistics.csv"], study)
        _tail_plot(output, tables["tail_diagnostics.csv"], study)


def _segment_plot(output, statistics, study):
    windows = [w["name"] for w in study.windows]
    assets = list(dict.fromkeys(statistics["asset"]))
    metrics = [("annual_log_growth", "Annual log growth", lambda v, _: f"{v:.0%}"),
               ("annual_volatility", "Annual volatility", lambda v, _: f"{v:.0%}"),
               ("excess_kurtosis", "Excess kurtosis of daily log returns", lambda v, _: f"{v:g}"),
               ("worst_day", "Worst daily return", lambda v, _: f"{v:.0%}")]
    figure = Figure(figsize=(max(11, 1.2 * len(assets) + 3), 13), dpi=150, facecolor=BACKGROUND)
    axes = figure.subplots(len(metrics), 1)
    figure.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.08, hspace=0.45)
    scope = "; ".join(f"{w['name']}: {w['provenance']}" for w in study.windows)
    _header(figure, "Source-segment sensitivity of calibration inputs",
            f"Same assets calibrated on separate windows | Required provenance - {scope}", y=0.97)
    for ax, (metric, label, formatter) in zip(axes, metrics):
        for i, window in enumerate(windows):
            subset = statistics[statistics["window"] == window].set_index("asset").reindex(assets)
            x = np.arange(len(assets)) + (i - (len(windows) - 1) / 2) * (0.8 / len(windows))
            ax.bar(x, subset[metric].to_numpy(dtype=float), width=0.8 / len(windows) * 0.92,
                   color=COLORS[i % len(COLORS)], label=window)
        ax.set_xticks(range(len(assets)), assets, fontsize=8)
        ax.set_title(label, fontsize=10, loc="left")
        ax.yaxis.set_major_formatter(FuncFormatter(formatter))
        ax.axhline(0, color="#8b989b", linewidth=0.7)
        _tidy(ax, "y")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.03, 0.925), ncol=len(labels), frameon=False)
    scoped = "; ".join(f"{w['name']}: {', '.join(w['provenance_assets'])}" for w in study.windows
                       if w["provenance"] != "any" and len(w["provenance_assets"]) < len(assets))
    figure.text(0.035, 0.03, "Reconstructed rows are model series built by the dataset project, not observed fund history. "
                "Per-interval provenance counts are in window_statistics.csv.", fontsize=8)
    if scoped:
        figure.text(0.035, 0.015, f"Provenance is enforced only for scoped assets ({scoped}); other assets may mix segments.", fontsize=8)
    figure.savefig(output / "segment_statistics.png")


def _tail_plot(output, diagnostics, study):
    reference = next(p for p in study.base.portfolios if p.name == study.base.reference)
    series = [reference.name, *reference.spec.assets]
    windows = [w["name"] for w in study.windows]
    methods = ["historical", *[m for m in study.base.generators.methods if m != "historical_replay"]]
    metrics = [("excess_kurtosis", "Excess kurtosis", "{:.1f}"),
               ("squared_acf_sum_21", "Sum of squared-return ACF, lags 1-21", "{:.2f}"),
               ("rolling63_vol_p95", "95th pct of 63-observation realised volatility", "{:.0%}"),
               ("q001_day", "0.1% daily return quantile", "{:.0%}")]
    figure = Figure(figsize=(6.2 * len(windows) + 1, 13), dpi=150, facecolor=BACKGROUND)
    axes = figure.subplots(len(metrics), len(windows), squeeze=False)
    figure.subplots_adjust(left=0.07, right=0.98, top=0.87, bottom=0.08, hspace=0.6, wspace=0.25)
    _header(figure, "Leveraged-risk diagnostic: tails and volatility clustering",
            f"Historical daily series against generated paths ({study.base.generators.diagnostic_paths} paths x "
            f"{max(study.horizons):,} observations, first seed) | Portfolio: {reference.name}, then its holdings", y=0.97)
    for c, window in enumerate(windows):
        for r, (metric, label, fmt) in enumerate(metrics):
            ax = axes[r, c]
            subset = diagnostics[diagnostics["window"] == window]
            for i, method in enumerate(methods):
                rows = subset[subset["method"] == method].set_index("series").reindex(series)
                x = np.arange(len(series)) + (i - (len(methods) - 1) / 2) * (0.8 / len(methods))
                ax.bar(x, rows[metric].to_numpy(dtype=float), width=0.8 / len(methods) * 0.92,
                       color="#2f3b40" if method == "historical" else COLORS[i % len(COLORS)], label=_method_label(method))
            ax.set_xticks(range(len(series)), ["Portfolio", *series[1:]], fontsize=7)
            ax.set_title(f"{window}: {label}", fontsize=9, loc="left")
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _, fmt=fmt: fmt.format(v)))
            ax.axhline(0, color="#8b989b", linewidth=0.7)
            _tidy(ax, "y")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.03, 0.925), ncol=len(labels), frameon=False)
    figure.text(0.035, 0.03, "Dark bars: the calibration sample itself. A generator that matches it on these statistics reproduces "
                "the tail and clustering behaviour that drives daily-reset leverage losses.", fontsize=8)
    figure.savefig(output / "tail_diagnostics.png")


def write_holdout_plots(output: Path, tables: dict, study):
    folds = tables["holdout_folds.csv"]
    folds = folds[folds["status"] == "ok"]
    summary = tables["holdout_summary.csv"]
    reference = study.base.reference
    methods = list(study.base.generators.methods)
    horizons = list(study.horizons)
    metrics = [("terminal", "Terminal wealth"), ("max_drawdown", "Maximum drawdown"),
               ("realised_volatility", "Realised volatility")]
    basis = study.base.generators.observations_per_year
    with matplotlib.rc_context({"font.family": "DejaVu Sans", "font.size": 9}):
        figure = Figure(figsize=(5.2 * len(horizons) + 1, 12.5), dpi=150, facecolor=BACKGROUND)
        axes = figure.subplots(len(metrics), len(horizons), squeeze=False)
        figure.subplots_adjust(left=0.1, right=0.97, top=0.86, bottom=0.08, hspace=0.5, wspace=0.3)
        _header(figure, f"Rolling holdout calibration: {reference}",
                f"PIT = share of generated paths below the realised outcome | {study.mode} {study.calibration_years}-year calibration | "
                "Diagonal: a calibrated generator", y=0.97)
        for c, horizon in enumerate(horizons):
            for r, (metric, label) in enumerate(metrics):
                ax = axes[r, c]
                ax.plot([0, 1], [0, 1], color="#a4adae", linewidth=0.9, linestyle="--")
                for i, method in enumerate(methods):
                    values = np.sort(folds[(folds["horizon_observations"] == horizon) & (folds["method"] == method)
                                           & (folds["portfolio"] == reference)][f"pit_{metric}"].dropna().to_numpy(dtype=float))
                    if not len(values):
                        continue
                    row = summary[(summary["horizon_observations"] == horizon) & (summary["method"] == method)
                                  & (summary["portfolio"] == reference) & (summary["metric"] == metric)]
                    coverage = f" | 90% coverage {row['central_90_coverage'].iloc[0]:.0%}" if not row.empty else ""
                    ax.step(np.r_[0, values, 1], np.r_[0, np.arange(1, len(values) + 1) / len(values), 1], where="post",
                            color=COLORS[i % len(COLORS)], linewidth=1.4, label=_method_label(method) + coverage)
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.set_title(f"{label} | {horizon:,} observations", fontsize=10)
                ax.set_xlabel("PIT of realised outcome")
                ax.set_ylabel("Share of origins")
                ax.legend(fontsize=7, frameon=False, loc="upper left")
                _tidy(ax, "both")
        figure.text(0.035, 0.035, "A line above the diagonal near PIT 0 means realised values fell below most generated values more often than predicted; "
                    "steep rises at both ends mean the generated range was too narrow.", fontsize=8)
        figure.text(0.035, 0.02, "Drawdowns are negative, so a low drawdown PIT is a deeper realised drawdown. Overlapping holdouts are dependent.", fontsize=8)
        figure.savefig(output / "holdout_pit.png")

        figure = Figure(figsize=(13, 3.9 * len(horizons) + 1.6), dpi=150, facecolor=BACKGROUND)
        axes = figure.subplots(len(horizons), 1, squeeze=False)[:, 0]
        figure.subplots_adjust(left=0.08, right=0.98, top=0.82, bottom=0.1, hspace=0.45)
        _header(figure, f"Generated ranges against realised holdout growth: {reference}",
                f"Bars: 5th-95th generated percentiles of annualised growth per {basis} observations | Black dots: realised",
                y=0.97, gap=0.055)
        for ax, horizon in zip(axes, horizons):
            subset = folds[(folds["horizon_observations"] == horizon) & (folds["portfolio"] == reference)]
            scale = basis / horizon
            for i, method in enumerate(methods):
                rows = subset[subset["method"] == method]
                x = rows["origin_year"].to_numpy(dtype=float) + (i - (len(methods) - 1) / 2) * 0.22
                growth = lambda v: (np.asarray(v, dtype=float) / study.base.initial_value) ** scale - 1
                ax.vlines(x, growth(rows["generated_terminal_p05"]), growth(rows["generated_terminal_p95"]),
                          color=COLORS[i % len(COLORS)], linewidth=1.6, label=_method_label(method))
            realised = subset.drop_duplicates("origin_year")
            ax.plot(realised["origin_year"], (realised["realised_terminal"] / study.base.initial_value) ** scale - 1,
                    "o", color="#1d2326", markersize=3.5, label="Realised")
            ax.axhline(0, color="#8b989b", linewidth=0.7)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
            ax.set_title(f"{horizon:,}-observation holdouts by origin year", fontsize=10, loc="left")
            ax.set_ylabel("Annualised growth")
            _tidy(ax, "y")
        handles, labels = axes[0].get_legend_handles_labels()
        figure.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.03, 0.895), ncol=len(labels), frameon=False)
        figure.text(0.035, 0.025, "Each origin calibrates only on returns ending at or before it. Nominal USD; reconstructed history before 2006-2009.", fontsize=8)
        figure.savefig(output / "holdout_timeline.png")
