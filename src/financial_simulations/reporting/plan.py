"""Static review images for the interactive planner's portfolio and ledger steps."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd

from financial_simulations.retirement.flows import account_flows, household_flows, milestones
from financial_simulations.retirement.real import real_daily, real_events


COLORS = {"Outside super": "#126a63", "Inside super": "#386a98", "Combined": "#b76a42"}
FLOW_COLOURS = {"Take-home salary": "#126a63", "Super contributions": "#386a98", "Investment returns": "#9a8a2e",
                "Interest on cash": "#4f8f3a", "Age Pension": "#d08c2f",
                "Spending": "#b76a42", "Income tax": "#8c2f2f", "Contributions tax": "#c2577a", "Super fund tax": "#8363a0", "Division 296 tax": "#5b3f7a",
                "Inflation": "#9aa3a8"}


def _figure(title, subtitle, *, height=5.5):
    fig = Figure(figsize=(11, height), dpi=150, facecolor="#fafaf7")
    ax = fig.add_subplot(111)
    fig.subplots_adjust(left=0.10, right=0.97, top=0.76, bottom=0.15)
    fig.text(0.10, 0.94, title, fontsize=16, fontweight="bold", color="#19353a")
    fig.text(0.10, 0.865, subtitle, fontsize=9, color="#536369")
    ax.set_facecolor("#fafaf7")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.22)
    ax.set_axisbelow(True)
    return fig, ax


def _years(ax, dates):
    span = (max(dates) - min(dates)).days / 365.25
    base = 5 if span >= 25 else 2 if span >= 12 else 1
    ax.xaxis.set_major_locator(mdates.YearLocator(base=base))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(axis="x", labelrotation=0)
    ax.set_xlim(min(dates), max(dates))


def _money(value, _):
    if abs(value) >= 1e6:
        return f"${value / 1e6:,.1f}m"
    if abs(value) < 1e4 and abs(value) >= 1e3:
        return f"${value / 1e3:,.1f}k"
    if abs(value) >= 1e3:
        return f"${value / 1e3:,.0f}k"
    return f"${value:,.0f}"


def wide_wealth_range(bands: pd.DataFrame) -> bool:
    """Use a log-like display when an upper tail would flatten the median."""
    return float(bands["P95"].max()) > 20 * max(1000.0, float(bands["P50"].max()))


def write_portfolio_plots(output: Path, plan, portfolios):
    """Write portfolio calibration and forward paths, shared by every compared spending strategy."""
    output = Path(output)
    with matplotlib.rc_context({"font.family": "DejaVu Sans"}):
        fig, ax = _figure("Historical portfolio growth", "Full shared sample; USD total returns; each account's rebalancing policy; reconstructed periods included")
        for title, part in portfolios.historical.groupby("Portfolio", sort=False):
            ax.plot(pd.to_datetime(part["Date"]), part["Growth of 100"], label=title, color=COLORS[title], linewidth=1.5)
        ax.set_yscale("log")
        ax.set_ylabel("Growth of $100 (log scale)")
        _years(ax, pd.to_datetime(portfolios.historical["Date"]))
        ax.legend(frameon=False, loc="upper left")
        fig.savefig(output / "portfolio_history.png")

        groups = list(portfolios.paths.groupby("Portfolio", sort=False))
        fig = Figure(figsize=(11, 3.2 + 2.2 * len(groups)), dpi=150, facecolor="#fafaf7")
        axes = fig.subplots(len(groups), 1, sharex=True)
        fig.subplots_adjust(left=0.10, right=0.97, top=0.85, bottom=0.11, hspace=0.24)
        fig.text(0.10, 0.95, "Future portfolio growth ranges", fontsize=16, fontweight="bold", color="#19353a")
        fig.text(0.10, 0.90, f"{plan['market']['paths']} shared stationary-bootstrap draws; growth of $100 in today's dollars; USD-return convention", fontsize=9, color="#536369")
        for ax, (title, part) in zip(axes, groups):
            dates = pd.to_datetime(part["Date"])
            ax.fill_between(dates, part["P05"], part["P95"], color=COLORS[title], alpha=0.13, label="5th–95th percentile")
            ax.fill_between(dates, part["P25"], part["P75"], color=COLORS[title], alpha=0.25, label="25th–75th percentile")
            ax.plot(dates, part["P50"], color=COLORS[title], linewidth=1.7, label="Median")
            ax.set_yscale("log")
            ax.set_ylabel(f"{title}\nGrowth of $100 (log)")
            ax.yaxis.set_major_formatter(FuncFormatter(_money))
            ax.grid(axis="y", alpha=0.22)
            ax.spines[["top", "right"]].set_visible(False)
        _years(axes[-1], pd.to_datetime(portfolios.paths["Date"]))
        axes[0].legend(frameon=False, ncol=3, fontsize=8, loc="upper left")
        fig.savefig(output / "portfolio_future.png")

        fig = Figure(figsize=(11, 8.2), dpi=150, facecolor="#fafaf7")
        axes = fig.subplots(2, 2)
        fig.subplots_adjust(left=0.08, right=0.98, top=0.86, bottom=0.08, hspace=0.38, wspace=0.18)
        fig.text(0.08, 0.95, "Distributions across simulated paths", fontsize=16, fontweight="bold", color="#19353a")
        fig.text(0.08, 0.905, f"{plan['market']['paths']} shared daily paths; outside and inside super overlaid; "
                 "dashed lines are medians", fontsize=9, color="#536369")
        outcomes = portfolios.outcomes
        for ax, (field, label, log) in zip(axes.flat, (("Terminal growth of 100", "Ending value of $100, today's dollars (log)", True),
                                                       ("Annualised growth", "Annualised growth after inflation", False),
                                                       ("Annualised volatility", "Annualised daily volatility", False),
                                                       ("Maximum drawdown", "Maximum drawdown", False))):
            values = {t: outcomes.loc[outcomes["Portfolio"] == t, field].to_numpy() for t in ("Outside super", "Inside super")}
            pooled = np.concatenate(list(values.values()))
            bins = (np.geomspace(pooled.min(), pooled.max(), 31) if log and pooled.min() > 0
                    else np.linspace(pooled.min(), pooled.max(), 31))
            for title, data in values.items():
                ax.hist(data, bins=bins, color=COLORS[title], alpha=0.45, label=title)
                ax.axvline(np.median(data), color=COLORS[title], linestyle="--", linewidth=1.2)
            if log:
                ax.set_xscale("log")
                ax.xaxis.set_major_formatter(FuncFormatter(_money))
            else:
                ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
            ax.set_title(label, fontsize=10, loc="left", color="#19353a")
            ax.set_ylabel("Paths")
            ax.spines[["top", "right"]].set_visible(False)
            ax.set_facecolor("#fafaf7")
        axes[0, 0].legend(frameon=False, fontsize=8)
        fig.savefig(output / "portfolio_distributions.png")


def write_retirement_plots(output: Path, plan, retirement_paths, retirement_bands, representative):
    """Write one spending strategy's retirement wealth range and its representative path's money in and out."""
    output = Path(output)
    with matplotlib.rc_context({"font.family": "DejaVu Sans"}):
        complete = int((retirement_paths["Status"] != "unsupported").sum())
        total = len(retirement_paths)
        wide = wide_wealth_range(retirement_bands)
        subtitle = f"{complete} of {total} daily tax-ledger paths calculated; today's dollars (AUD proxy); unsupported draws excluded"
        if wide:
            subtitle += "\nLog-like y-axis above $1,000 keeps central paths visible beside the upper tail"
        fig, ax = _figure("Retirement wealth range", subtitle)
        dates = pd.to_datetime(retirement_bands["Date"])
        ax.fill_between(dates, retirement_bands["P05"], retirement_bands["P95"], color="#126a63", alpha=0.13, label="5th–95th percentile")
        ax.fill_between(dates, retirement_bands["P25"], retirement_bands["P75"], color="#126a63", alpha=0.25, label="25th–75th percentile")
        ax.plot(dates, retirement_bands["P50"], color="#126a63", linewidth=1.7, label="Median")
        if wide:
            ax.set_yscale("symlog", linthresh=1000)
            upper = float(retirement_bands["P95"].max())
            ax.set_yticks([0, *[10 ** power for power in range(3, 10) if 10 ** power <= upper]])
        ax.set_ylabel("Total wealth, today's dollars" + (" (log-like scale)" if wide else ""))
        ax.yaxis.set_major_formatter(FuncFormatter(_money))
        ax.set_ylim(bottom=0)
        _years(ax, dates)
        for _, mark in milestones(plan, dates.min().date(), dates.max().date()).iterrows():
            ax.axvline(mark["Date"], color="#5f6b73", linestyle="--", linewidth=1)
            ax.text(mark["Date"], ax.get_ylim()[1], " " + mark["Event"], fontsize=8, color="#3c474d", va="top")
        ax.xaxis.grid(True, alpha=0.22)
        fig.subplots_adjust(bottom=0.22)
        ax.legend(frameon=False, ncol=3, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.09))
        fig.savefig(output / "retirement_range.png")

        cpi = plan["assumptions"]["cpi_annual"]
        daily = real_daily(representative.daily, cpi)
        flows = household_flows(daily, inflation=True)
        fig, ax = _figure("Money in and out each year",
                          "Path nearest median ending wealth; today's dollars; years end 30 June; in above zero, out below; "
                          "line = net change in wealth")
        years = sorted(flows["FY ending"].unique())
        positive, negative = np.zeros(len(years)), np.zeros(len(years))
        for label, color in FLOW_COLOURS.items():
            values = flows.loc[flows["Flow"] == label].set_index("FY ending").reindex(years)["AUD"].fillna(0).to_numpy()
            if np.abs(values).max() <= 1e-6:
                continue
            bottom = np.where(values >= 0, positive, negative)
            ax.bar(years, values, bottom=bottom, width=0.7, color=color, label=label)
            positive += np.where(values >= 0, values, 0)
            negative += np.where(values < 0, values, 0)
        net = flows.drop_duplicates("FY ending").set_index("FY ending").reindex(years)["Net change"]
        ax.plot(years, net, color="#19353a", marker="o", markersize=3, linewidth=1.6, label="Net change in wealth")
        moves = account_flows(daily, real_events(representative.events, daily.index[0], cpi))
        added = moves.loc[moves["Flow"] == "Savings invested"].groupby("FY ending")["AUD"].sum().reindex(years, fill_value=0)
        if added.abs().max() > 1e-6:
            ax.plot(years, added, color="#0b7a8a", linestyle="--", marker="s", markersize=4, linewidth=1.6,
                    label="Added to outside investments (transfer)")
        ax.axhline(0, color="#5f6b73", linewidth=0.8)
        top, low = max(positive.max(), net.max(), added.max(), 1.0), min(negative.min(), net.min(), -1.0)
        ax.set_ylim(low - 0.08 * (top - low), top + 0.12 * (top - low))
        for _, mark in milestones(plan, daily.index[0].date(), daily.index[-1].date()).iterrows():
            ax.axvline(mark["Position"], color="#5f6b73", linestyle="--", linewidth=1)
            ax.text(mark["Position"], ax.get_ylim()[1], " " + mark["Event"], fontsize=8, color="#3c474d", va="top")
        ax.set_ylabel("Today's dollars per year (year ending 30 June)")
        ax.yaxis.set_major_formatter(FuncFormatter(_money))
        step = 5 if len(years) >= 25 else 2 if len(years) >= 12 else 1
        ax.set_xticks([y for y in years if y % step == 0 or step == 1])
        ax.xaxis.grid(True, alpha=0.22)
        fig.subplots_adjust(bottom=0.26)
        ax.legend(frameon=False, ncol=4, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.1))
        fig.savefig(output / "retirement_flows.png")


def write_comparison_plots(output: Path, plan, strategies: dict):
    """Write the compared strategies' wealth over time, yearly spending and summary table (ADR 0045)."""
    from financial_simulations.retirement.strategy_results import (DEFAULT_FLOW, STRATEGY_COLOURS, STRATEGY_NAMES,
                                                                   comparison_table, wealth_lines, yearly_medians)

    output = Path(output)
    table = comparison_table(strategies)
    table.rename(columns={r: STRATEGY_NAMES[r] for r in strategies}).to_csv(output / "comparison_summary.csv", index=False,
                                                                            lineterminator="\n")
    paths = len(next(iter(strategies.values())).retirement_paths)
    with matplotlib.rc_context({"font.family": "DejaVu Sans"}):
        lines = wealth_lines(strategies)
        fig, ax = _figure("Spending strategies: wealth over time",
                          f"Median (solid) and 10th percentile (dashed) total wealth across the same {paths} paths; "
                          "today's dollars")
        for rule in strategies:
            part = lines.loc[lines["Strategy"] == rule]
            dates = pd.to_datetime(part["Date"])
            ax.plot(dates, part["Median"], color=STRATEGY_COLOURS[rule], linewidth=1.8, label=STRATEGY_NAMES[rule])
            ax.plot(dates, part["P10"], color=STRATEGY_COLOURS[rule], linewidth=1.2, linestyle="--")
        ax.set_ylabel("Total wealth, today's dollars")
        ax.yaxis.set_major_formatter(FuncFormatter(_money))
        ax.set_ylim(bottom=0)
        dates = pd.to_datetime(lines["Date"])
        _years(ax, dates)
        for _, mark in milestones(plan, dates.min().date(), dates.max().date()).iterrows():
            ax.axvline(mark["Date"], color="#5f6b73", linestyle="--", linewidth=1)
            ax.text(mark["Date"], ax.get_ylim()[1], " " + mark["Event"], fontsize=8, color="#3c474d", va="top")
        fig.subplots_adjust(bottom=0.2)
        ax.legend(frameon=False, ncol=len(strategies), fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.08))
        fig.savefig(output / "comparison_wealth.png")

        bars = yearly_medians(strategies, DEFAULT_FLOW, retired_only=True)
        fig, ax = _figure("Spending strategies: spending each retired year",
                          f"Median spending paid across the same {paths} paths in each full retired financial year; "
                          "today's dollars")
        if not bars.empty:
            width = 0.84 / len(strategies)
            for i, rule in enumerate(strategies):
                part = bars.loc[bars["Strategy"] == rule]
                ax.bar(part["FY ending"] - 0.42 + (i + 0.5) * width, part["Value"], width=width * 0.88,
                       color=STRATEGY_COLOURS[rule], label=STRATEGY_NAMES[rule])
            years = sorted(bars["FY ending"].unique())
            step = 5 if len(years) >= 25 else 2 if len(years) >= 12 else 1
            ax.set_xticks([y for y in years if y % step == 0 or step == 1])
        ax.set_ylabel("Spending paid, today's dollars (year ending 30 June)")
        ax.yaxis.set_major_formatter(FuncFormatter(_money))
        fig.subplots_adjust(bottom=0.2)
        ax.legend(frameon=False, ncol=len(strategies), fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.08))
        fig.savefig(output / "comparison_spending.png")
