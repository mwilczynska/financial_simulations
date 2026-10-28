"""PNG evaluation reports; pointwise bands and Monte Carlo intervals stay distinct."""

from math import ceil

import matplotlib

matplotlib.use("Agg")

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, LogLocator, NullLocator
import numpy as np
import pandas as pd

from financial_simulations.reporting.comparison import _label


def _style(ax):
    ax.grid(alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)


def _money(value, _):
    return f"{value / 1e6:g}m" if abs(value) >= 1e6 else f"{value / 1000:g}k" if abs(value) >= 1000 else f"{value:g}"


def write_evaluation_plots(output, tables, series, config, scenario):
    summary, risks = tables["summary.csv"], tables["risk_summary.csv"]
    selected = summary[summary["case_id"].isin(series["case_id"].unique())]
    title = f"{config.windows[0]['name']} | {config.trace_horizon:,} return observations | generated seed {config.seeds[0]}"
    portfolio = " | ".join(f"{a} {w:.0%}" for a, w in scenario.portfolio.weights.items())
    caption = f"{title}\n{portfolio} | {scenario.portfolio.rebalance.replace('_', ' ')} | opening {scenario.initial_value + scenario.initial_cash:,.0f} {scenario.portfolio.currency}"
    with matplotlib.rc_context({"font.family": "DejaVu Sans", "font.size": 9}):
        for basis in ("nominal", "real") if config.parametric else ("nominal",):
            _wealth_bands(output, series, selected, caption, basis, scenario.portfolio.currency)
        _terminal_ecdf(output, tables["outcomes.csv"], selected, caption, bool(config.parametric), scenario.portfolio.currency)
        _shortfall(output, risks, summary, config, scenario)
        _drawdown(output, risks, selected, caption, bool(config.parametric))


def _wealth_bands(output, series, cases, caption, basis, currency):
    rows = ceil(len(cases) / 2)
    height = 3.0 * rows + 2
    figure = Figure(figsize=(14, height), dpi=150, facecolor="#fafaf7")
    axes = figure.subplots(rows, 2, squeeze=False, sharex=True, sharey=True).ravel()
    figure.subplots_adjust(left=0.08, right=0.97, top=1 - 1.55 / height, bottom=0.09, hspace=0.40, wspace=0.18)
    units = "Nominal" if basis == "nominal" else "Opening-price"
    figure.suptitle(f"{units} wealth through calendar time", x=0.045, ha="left", y=1 - 0.15 / height, fontsize=17, fontweight="bold")
    figure.text(0.045, 1 - 0.55 / height, caption, linespacing=1.6, fontsize=9, va="top")
    handles = [Patch(facecolor="#126a63", alpha=0.18, label="Pointwise 5th-95th percentiles"),
               Line2D([], [], color="#126a63", label="Pointwise median"),
               Line2D([], [], color="#ad623d", linestyle="--", label="Stated target in these units")]
    figure.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.04, 1 - 1.0 / height), ncol=3, frameon=False)
    for ax, (_, case) in zip(axes, cases.iterrows()):
        group = series[series["case_id"] == case["case_id"]]
        dates = pd.to_datetime(group["date"])
        x = (dates - dates.iloc[0]).dt.days.to_numpy() / 365.25
        ax.fill_between(x, group[f"{basis}_p05"].to_numpy(), group[f"{basis}_p95"].to_numpy(), color="#126a63", alpha=0.18)
        ax.plot(x, group[f"{basis}_median"], color="#126a63", linewidth=1.5)
        ax.plot(x, group[f"target_{basis}"], color="#ad623d", linewidth=1.0, linestyle="--")
        ax.set_title(_label(case), fontsize=11)
        ax.set_xlabel("Elapsed calendar years (365.25 days)")
        ax.set_ylabel(f"{units} {currency}")
        _style(ax)
    for ax in axes[len(cases):]:
        ax.set_visible(False)
    logarithmic = (series[f"{basis}_p05"] > 0).all()
    if logarithmic:
        axes[0].set_yscale("log")
        axes[0].yaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5), numticks=6))
        axes[0].yaxis.set_minor_locator(NullLocator())
    axes[0].yaxis.set_major_formatter(FuncFormatter(_money))
    figure.text(0.045, 0.035, f"Pointwise bands are not individual realizable paths. Complete examples are in sample_paths.png. Shared {'logarithmic' if logarithmic else 'linear'} wealth scale.", fontsize=8)
    figure.text(0.045, 0.018, "Calendar-only marks carry nominal account value; assumed inflation still accrues. These are conditional scenarios, not forecasts.", fontsize=8)
    figure.savefig(output / f"wealth_percentiles_{basis}.png")


def _terminal_ecdf(output, outcomes, cases, caption, real, currency):
    figure = Figure(figsize=(14, 6), dpi=150, facecolor="#fafaf7")
    bases = ("nominal", "real") if real else ("nominal",)
    axes = figure.subplots(1, len(bases), squeeze=False)[0]
    figure.subplots_adjust(left=0.07, right=0.97, top=0.77, bottom=0.29, wspace=0.20)
    figure.suptitle("Terminal wealth distributions", x=0.045, ha="left", y=0.97, fontsize=17, fontweight="bold")
    figure.text(0.045, 0.90, caption, linespacing=1.6, va="top")
    for ax, basis in zip(axes, bases):
        all_positive = True
        for i, (_, case) in enumerate(cases.iterrows()):
            column = "terminal_value" if basis == "nominal" else "real_terminal_value"
            values = np.sort(outcomes.loc[outcomes["case_id"] == case["case_id"], column].to_numpy())
            ax.step(np.r_[values[0], values], np.r_[0, np.arange(1, len(values) + 1) / len(values)],
                    where="post", label=_label(case), color=matplotlib.colormaps["tab10"](i % 10), linewidth=1.3)
            all_positive &= bool((values > 0).all())
        if all_positive:
            ax.set_xscale("log")
            ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5), numticks=6))
            ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(_money))
        ax.set_xlabel(f"{'Nominal' if basis == 'nominal' else 'Opening-price'} {currency} ({ax.get_xscale()} scale)")
        ax.set_ylabel("Cumulative fraction of paths")
        ax.set_ylim(0, 1.02)
        _style(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.055), ncol=4, frameon=False, fontsize=8)
    figure.text(0.045, 0.025, "Empirical CDFs, not density estimates. Replay windows overlap; generated cases are conditional on fitted inputs. Models are not averaged.", fontsize=8)
    figure.savefig(output / "terminal_distribution.png")


def _shortfall(output, risks, summary, config, scenario):
    windows = [w["name"] for w in config.windows]
    figure = Figure(figsize=(7 * len(windows), 4.0 * len(config.horizons) + 1.4), dpi=150, facecolor="#fafaf7")
    axes = figure.subplots(len(config.horizons), len(windows), squeeze=False)
    figure.subplots_adjust(left=0.23 if len(windows) == 1 else 0.17, right=0.97, top=0.82, bottom=0.085, hspace=0.45, wspace=0.85)
    setting = config.evaluation
    figure.suptitle("Missing the stated terminal target", x=0.04, ha="left", y=0.98, fontsize=17, fontweight="bold")
    figure.text(0.04, 0.945, f"Target: {setting.target_multiple:g} x opening {scenario.initial_value + scenario.initial_cash:,.0f} {scenario.portfolio.currency} | {setting.target_annual_growth:.1%} annual calendar growth | {setting.target_basis} units")
    figure.text(0.04, 0.917, f"Dots: below-target fractions | Bars: {setting.confidence:.0%} Wilson intervals for conditional Monte Carlo sampling error")
    colors = ("#126a63", "#b76a42", "#8363a0", "#386a98")
    handles = [Line2D([], [], color="#778287", marker="o", label="Replay: descriptive only")]
    handles += [Line2D([], [], color=colors[i % 4], marker="o", label=f"Seed {seed}") for i, seed in enumerate(config.seeds)]
    figure.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.035, 0.895), ncol=4, frameon=False, fontsize=8)
    indexed = risks.set_index("case_id")
    for r, horizon in enumerate(config.horizons):
        for c, window in enumerate(windows):
            ax = axes[r, c]
            cases = summary[(summary["window"] == window) & (summary["horizon_observations"] == horizon)]
            labels = list(dict.fromkeys(_label(row) for _, row in cases.iterrows()))
            for _, case in cases.iterrows():
                y = labels.index(_label(case))
                if case["status"] != "ok":
                    ax.text(0.02, y, "No complete window", transform=ax.get_yaxis_transform(), color="#8c5144")
                    continue
                row = indexed.loc[case["case_id"]]
                replay = case["method"] == "historical_replay"
                seed_id = 0 if replay else config.seeds.index(int(case["seed"]))
                y += 0 if replay else (seed_id - (len(config.seeds) - 1) / 2) * 0.18
                color = "#778287" if replay else colors[seed_id % 4]
                if not replay:
                    ax.plot([row["fraction_ci_low"], row["fraction_ci_high"]], [y, y], color=color, linewidth=1.5)
                ax.plot(row["fraction_below_target"], y, "o", color=color, markersize=4)
            ax.set_yticks(range(len(labels)), labels, fontsize=8)
            ax.set_ylim(len(labels) - 0.5, -0.5)
            ax.set_xlim(-0.015, 1.015)
            ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0%}"))
            ax.set_xlabel("Fraction with terminal wealth strictly below target")
            ax.set_title(f"{window} | {horizon:,} observations")
            _style(ax)
    figure.text(0.04, 0.035, "Intervals quantify generated-path sampling error only, excluding parameter uncertainty, calibration bias and model disagreement.", fontsize=8)
    figure.text(0.04, 0.018, "Replay fractions are over dependent overlapping windows. They receive no independent-sample interval. These are not retirement success rates.", fontsize=8)
    figure.savefig(output / "target_shortfall.png")


def _drawdown(output, risks, cases, caption, real):
    figure = Figure(figsize=(17, 8), dpi=150, facecolor="#fafaf7")
    axes = figure.subplots(1, 3, sharey=True)
    figure.subplots_adjust(left=0.18, right=0.97, top=0.79, bottom=0.17, wspace=0.22)
    figure.suptitle("Drawdown depth, time underwater and open recoveries", x=0.04, ha="left", y=0.97, fontsize=17, fontweight="bold")
    figure.text(0.04, 0.90, caption, linespacing=1.6, va="top")
    selected = risks.set_index("case_id").loc[cases["case_id"]]
    labels = [_label(row) for _, row in cases.iterrows()]
    bases = ("nominal", "real") if real else ("nominal",)
    for i, basis in enumerate(bases):
        y = np.arange(len(cases)) + (i - (len(bases) - 1) / 2) * 0.23
        color = ("#126a63", "#b76a42")[i]
        for ax, metric, scale in ((axes[0], "max_drawdown", 1), (axes[1], "longest_underwater_days", 365.25)):
            for j, (_, row) in enumerate(selected.iterrows()):
                ax.plot([row[f"{basis}_{metric}_p05"] / scale, row[f"{basis}_{metric}_p95"] / scale], [y[j], y[j]], color=color)
                ax.plot(row[f"{basis}_{metric}_median"] / scale, y[j], "o", color=color, markersize=4)
        axes[2].plot(selected[f"{basis}_unrecovered_fraction"], y, "o", color=color, label=basis.title(), markersize=4)
    axes[0].set_yticks(range(len(labels)), labels, fontsize=9)
    axes[0].set_ylim(len(labels) - 0.5, -0.5)
    axes[0].set_title("Maximum drawdown")
    axes[0].set_xlabel("Median and 5th-95th path percentiles")
    axes[0].xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0%}"))
    axes[1].set_title("Longest observed time underwater")
    axes[1].set_xlabel("Elapsed years; open episodes are lower bounds")
    axes[2].set_title("Maximum-DD episode still unrecovered")
    axes[2].set_xlabel("Fraction of paths at the horizon")
    axes[2].set_xlim(-0.015, 1.015)
    axes[2].xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0%}"))
    for ax in axes:
        _style(ax)
    handles, labels = axes[2].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.065), ncol=2, frameon=False)
    figure.text(0.04, 0.025, "Depth/duration bars describe path distributions, not confidence intervals. Unfinished recovery dates remain empty; their observed durations are censored.", fontsize=8)
    figure.savefig(output / "drawdown_recovery.png")
