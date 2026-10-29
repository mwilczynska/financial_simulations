"""Static review images for the interactive planner's portfolio and ledger steps."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd


COLORS = {"Outside super": "#126a63", "Inside super": "#386a98", "Combined": "#b76a42"}


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


def write_plan_plots(output: Path, plan, market, portfolios, retirement_paths, retirement_bands, representative):
    """Write portfolio calibration, forward paths and retirement diagnostics."""
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
        fig.text(0.10, 0.90, f"{plan['market']['paths']} shared stationary-bootstrap draws; growth of $100; USD-return convention", fontsize=9, color="#536369")
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
        for ax, (field, label, log) in zip(axes.flat, (("Terminal growth of 100", "Ending value of $100 (log scale)", True),
                                                       ("Annualised growth", "Annualised growth", False),
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

        complete = int((retirement_paths["Status"] != "unsupported").sum())
        total = len(retirement_paths)
        wide = wide_wealth_range(retirement_bands)
        subtitle = f"{complete} of {total} daily tax-ledger paths calculated; nominal AUD proxy; unsupported draws excluded"
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
        ax.set_ylabel("Total wealth (AUD proxy" + ("; log-like scale)" if wide else ")"))
        ax.yaxis.set_major_formatter(FuncFormatter(_money))
        ax.set_ylim(bottom=0)
        _years(ax, dates)
        ax.legend(frameon=False, ncol=3, loc="upper left")
        fig.savefig(output / "retirement_range.png")

        annual = representative.daily[["salary", "spending_paid", "tax_paid", "employer_contributions", "pension_payments", "shortfall"]].resample("YE-JUN").sum()
        fig, ax = _figure("Annual cash flow stages", "Representative path nearest median ending wealth; payments summed by Australian financial year")
        drawn = 0
        for key, label, color in (("salary", "Salary", "#126a63"), ("spending_paid", "Spending", "#b76a42"),
                                  ("tax_paid", "Tax paid", "#8c5144"), ("employer_contributions", "Super contributions", "#386a98"),
                                  ("pension_payments", "Pension payments", "#8363a0"), ("shortfall", "Shortfall", "#8c2f2f")):
            if annual[key].abs().max() > 1e-9:
                ax.plot(annual.index, annual[key], label=label, color=color, linewidth=1.5)
                drawn += 1
        if not drawn:
            ax.text(0.5, 0.5, "No cash flows in this scenario", transform=ax.transAxes,
                    ha="center", va="center", color="#536369")
            ax.set_ylim(0, 1)
            ax.set_yticks([])
        ax.set_ylabel("AUD per financial year")
        if drawn:
            ax.yaxis.set_major_formatter(FuncFormatter(_money))
        _years(ax, annual.index)
        if drawn:
            ax.legend(frameon=False, ncol=3, fontsize=8, loc="upper left")
        fig.savefig(output / "retirement_flows.png")
