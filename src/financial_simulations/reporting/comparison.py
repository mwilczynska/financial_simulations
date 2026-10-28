"""Static PNGs for separate empirical generators and their sensitivities."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter, LogLocator, NullFormatter, NullLocator
import numpy as np


def _label(row):
    method = row["method"]
    if method == "historical_replay":
        return "Complete replay"
    if method == "independent":
        return "Independent rows"
    prefix = "Moving" if method == "moving_block" else "Stationary"
    return f"{prefix} L={int(row['block_length'])}"


def write_comparison_plots(output: Path, tables: dict, config, scenario):
    summary, traces, dependence = tables["summary.csv"], tables["traces.csv"], tables["dependence.csv"]
    windows = [w["name"] for w in config.windows]
    colors = ("#126a63", "#b76a42", "#8363a0", "#386a98")
    mix = " | ".join(f"{asset} {weight:.0%}" for asset, weight in scenario.portfolio.weights.items())
    portfolio_label = f"{mix} | {scenario.portfolio.rebalance.replace('_', ' ')} | opening {scenario.initial_value + scenario.initial_cash:,.0f} {scenario.portfolio.currency}"
    with matplotlib.rc_context({"font.family": "DejaVu Sans", "font.size": 9}):
        figure = Figure(figsize=(6 * len(windows), 3.5 * len(config.horizons) + 1.3), dpi=150,
                        facecolor="#fafaf7")
        axes = figure.subplots(len(config.horizons), len(windows), squeeze=False)
        figure.subplots_adjust(left=0.18 if len(windows) == 1 else 0.12, right=0.97,
                               top=0.81, bottom=0.09, hspace=0.45, wspace=0.60)
        figure.suptitle("Generator and assumption sensitivity", fontsize=17, fontweight="bold", x=0.05, ha="left", y=0.98)
        figure.text(0.05, 0.94, "Dots: median terminal wealth | Bars: 5th-95th sample percentiles | Seeds shown separately", color="#536369")
        figure.text(0.05, 0.91, portfolio_label, color="#536369", fontsize=9)
        handles = [Line2D([], [], color="#778287", marker="o", label="Replay windows")]
        handles += [Line2D([], [], color=colors[i % len(colors)], marker="o", label=f"Seed {seed}")
                    for i, seed in enumerate(config.seeds)]
        figure.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.05, 0.89),
                      ncol=min(5, len(handles)), frameon=False, fontsize=8)
        for r, horizon in enumerate(config.horizons):
            for c, window in enumerate(windows):
                ax = axes[r, c]
                subset = summary[(summary["window"] == window) & (summary["horizon_observations"] == horizon)].copy()
                subset["label"] = subset.apply(_label, axis=1)
                labels = list(dict.fromkeys(subset["label"]))
                for _, row in subset.iterrows():
                    y = labels.index(row["label"])
                    if row["status"] != "ok":
                        ax.text(0.02, y, "No complete window", transform=ax.get_yaxis_transform(), color="#8c5144")
                        continue
                    historical = row["method"] == "historical_replay"
                    seed_id = config.seeds.index(int(row["seed"])) if not historical else 0
                    y += 0 if historical else (seed_id - (len(config.seeds) - 1) / 2) * 0.18
                    color = "#778287" if historical else colors[seed_id % len(colors)]
                    ax.plot([row["terminal_p05"], row["terminal_p95"]], [y, y], color=color, linewidth=1.6)
                    ax.plot(row["terminal_median"], y, "o", color=color, markersize=4)
                ax.set_yticks(range(len(labels)), labels)
                ax.set_ylim(len(labels) - 0.5, -0.5)
                ok = subset[subset["status"] == "ok"]
                if not ok.empty and (ok["terminal_p05"] > 0).all():
                    ax.set_xscale("log")
                    ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5), numticks=5))
                    ax.xaxis.set_minor_locator(NullLocator())
                    ax.xaxis.set_minor_formatter(NullFormatter())
                ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x / 1e6:g}m" if x >= 1e6 else f"{x / 1000:g}k" if x >= 1000 else f"{x:g}"))
                ax.set_title(f"{window} | {horizon:,} observations", fontsize=11)
                ax.set_xlabel(f"Terminal nominal {scenario.portfolio.currency} ({ax.get_xscale()} scale)", fontsize=8)
                ax.grid(axis="x", alpha=0.2)
                ax.spines[["top", "right"]].set_visible(False)
        figure.text(0.05, 0.025, "Shared accounting-calendar template. Replay windows overlap; these are conditional scenarios, not retirement probabilities.", fontsize=8)
        figure.savefig(output / "terminal_wealth.png")

        figure = Figure(figsize=(12, 8), dpi=150, facecolor="#fafaf7")
        axes = figure.subplots(2, 2).ravel()
        figure.subplots_adjust(left=0.09, right=0.97, top=0.81, bottom=0.11, hspace=0.45, wspace=0.25)
        figure.suptitle("Traceable individual paths", fontsize=17, fontweight="bold", x=0.07, ha="left", y=0.97)
        figure.text(0.07, 0.91, f"{windows[0]} | {config.trace_horizon:,} observations | block methods L={config.trace_block_length} | seed={config.seeds[0]}")
        figure.text(0.07, 0.875, portfolio_label, fontsize=9, color="#536369")
        for ax, method in zip(axes, ("historical_replay", "independent", "moving_block", "stationary")):
            subset = traces[traces["method"] == method] if not traces.empty else traces
            for color_id, (path_id, group) in enumerate(subset.groupby("path_id")):
                ax.plot(group["step"], group["value"], linewidth=1.2, color=colors[color_id % len(colors)], label=f"Path {path_id}")
            if subset.empty:
                ax.text(0.5, 0.5, "No complete replay window", ha="center", transform=ax.transAxes)
            elif (subset["value"] > 0).all():
                ax.set_yscale("log")
                ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5), numticks=5))
                ax.yaxis.set_minor_locator(NullLocator())
                ax.yaxis.set_minor_formatter(NullFormatter())
            ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))
            ax.set_title(method.replace("_", " ").title())
            ax.set_xlabel("Return observation")
            ax.set_ylabel(f"Nominal {scenario.portfolio.currency} ({ax.get_yscale()} scale)")
            if not subset.empty:
                ax.legend(fontsize=8, frameon=False)
            ax.grid(alpha=0.2)
            ax.spines[["top", "right"]].set_visible(False)
        figure.text(0.07, 0.035, "Each line is one realizable sampled path, not a percentile band. Donor rows and block boundaries are saved in traces.csv.", fontsize=8)
        figure.savefig(output / "sample_paths.png")

        figure = Figure(figsize=(6 * len(windows), 7.5), dpi=150, facecolor="#fafaf7")
        axes = figure.subplots(2, len(windows), squeeze=False)
        figure.subplots_adjust(left=0.09, right=0.97, top=0.84, bottom=0.12, hspace=0.45, wspace=0.3)
        figure.suptitle("Source dependence diagnostics", fontsize=17, fontweight="bold", x=0.07, ha="left", y=0.97)
        figure.text(0.07, 0.91, "Lag correlations in daily returns and squared daily returns; calibration inputs, not a validated block-length rule")
        for col, window in enumerate(windows):
            subset = dependence[dependence["window"] == window]
            for row, column in enumerate(("return_acf", "squared_return_acf")):
                ax = axes[row, col]
                for i, (asset, group) in enumerate(subset.groupby("asset", sort=False)):
                    ax.plot(group["lag"], group[column], label=asset, color=colors[i % len(colors)], linewidth=1.3)
                ax.axhline(0, color="#8b989b", linewidth=0.7)
                ax.set_title(f"{window}: {'returns' if row == 0 else 'squared returns'}")
                ax.set_xlabel("Lag in trading observations")
                ax.set_xlim(1, 21)
                ax.xaxis.set_major_locator(FixedLocator([1, 5, 10, 15, 21]))
                ax.set_ylabel("Correlation")
                all_values = dependence[column].dropna().to_numpy(dtype=float)
                low, high = (min(0, float(all_values.min())), max(0, float(all_values.max()))) if len(all_values) else (-0.1, 0.1)
                padding = max(0.03, (high - low) * 0.15)
                ax.set_ylim(max(-1, low - padding), min(1, high + padding))
                ax.grid(alpha=0.2)
                ax.spines[["top", "right"]].set_visible(False)
        handles, labels = axes[0, 0].get_legend_handles_labels()
        figure.legend(handles, labels, loc="lower center", ncol=min(len(labels), 6), frameon=False)
        figure.savefig(output / "dependence.png")
