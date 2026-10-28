"""Static PNG plots from the daily ledger; no browser or PDF generation."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, PercentFormatter
import numpy as np

from financial_simulations.portfolios.engine import PortfolioResult


_PALETTE = ("#267d8d", "#8b9eae", "#d6ae4b", "#9272a4", "#6e9b64", "#bd765b")


def _figure(title: str, subtitle: str, *, height: float = 5.2):
    figure = Figure(figsize=(11, height), dpi=160, facecolor="#fafaf7")
    axes = figure.add_subplot(111)
    axes.set_facecolor("#fafaf7")
    figure.subplots_adjust(left=0.10, right=0.97, bottom=0.17, top=0.76)
    figure.text(0.10, 0.94, title, fontsize=17, fontweight="bold", color="#19353a")
    figure.text(0.10, 0.87, subtitle, fontsize=10, color="#536369")
    for name in ("top", "right"):
        axes.spines[name].set_visible(False)
    for name in ("left", "bottom"):
        axes.spines[name].set_color("#bcc5c5")
    axes.tick_params(colors="#536369", labelsize=9, length=0, pad=8)
    axes.grid(axis="y", color="#d9dfdd", linewidth=0.7)
    axes.set_axisbelow(True)
    locator = mdates.AutoDateLocator(minticks=3, maxticks=9)
    axes.xaxis.set_major_locator(locator)
    axes.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    figure.text(0.10, 0.035, "Financial Simulations | Stage 1A | Daily accounting", fontsize=8, color="#6c787b")
    return figure, axes


def write_plots(output: Path, result: PortfolioResult, title: str) -> None:
    """Use every daily mark in three independently viewable, full-resolution PNGs."""
    daily = result.daily
    dates = daily.index.to_pydatetime()
    subtitle = (f"{daily.index[0].date()} to {daily.index[-1].date()}  |  "
                f"{result.portfolio.currency} nominal  |  {result.portfolio.rebalance.replace('_', ' ')}")
    style = {"font.family": "DejaVu Sans", "savefig.facecolor": "#fafaf7"}
    with matplotlib.rc_context(style):
        figure, axes = _figure("Portfolio wealth", subtitle)
        capital = result.initial_value + result.initial_cash + daily["net_external_flow"].cumsum()
        axes.plot(dates, daily["value"], color="#126a63", linewidth=1.7, label="Account value")
        axes.plot(dates, capital, color="#8b989b", linestyle="--", linewidth=1.2, label="Net capital supplied")
        maximum = max(float(daily["value"].max()), float(capital.abs().max()), 1)
        scale = 1000 if maximum >= 10000 else 1
        axes.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / scale:,.0f}"))
        axes.set_ylabel(f"Value ({result.portfolio.currency}{', thousands' if scale == 1000 else ''})",
                        fontsize=10, color="#536369")
        axes.set_ylim(bottom=min(0, float(capital.min())))
        axes.legend(loc="upper left", frameon=False, fontsize=9)
        figure.text(0.10, 0.80, title, fontsize=9, color="#536369")
        figure.savefig(output / "wealth.png")

        growth = (1 + daily["performance_return"].fillna(0)).cumprod().to_numpy()
        drawdown = growth / np.maximum.accumulate(growth) - 1
        figure, axes = _figure("Investment drawdown", subtitle, height=4.6)
        axes.fill_between(dates, drawdown, 0, color="#bf6d5b", alpha=0.28, linewidth=0)
        axes.plot(dates, drawdown, color="#a34f42", linewidth=1.1)
        axes.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        axes.set_ylabel("Below previous performance peak", fontsize=10, color="#536369")
        axes.set_ylim(min(-0.02, float(drawdown.min()) * 1.1), 0.01)
        figure.text(0.10, 0.80, "Time-weighted performance; external cash flows excluded", fontsize=9, color="#536369")
        figure.savefig(output / "drawdown.png")

        names = [f"holding_{asset}" for asset in result.portfolio.assets] + ["cash"]
        balances = daily[names].to_numpy().T
        total = daily["value"].to_numpy()
        shares = np.divide(balances, total, out=np.full_like(balances, np.nan), where=total > 0)
        figure, axes = _figure("Portfolio allocation", subtitle)
        labels = [*result.portfolio.assets, "Cash"]
        legend_rows = (len(labels) + 5) // 6
        figure.subplots_adjust(top=0.70 - 0.035 * (legend_rows - 1))
        if (total > 0).any():
            axes.stackplot(dates, shares, labels=labels,
                           colors=[_PALETTE[i % len(_PALETTE)] for i in range(len(names) - 1)] + ["#ced3cf"],
                           linewidth=0)
        else:
            axes.text(0.5, 0.5, "No funded balance in this run", transform=axes.transAxes,
                      ha="center", color="#536369")
        axes.set_ylim(0, 1)
        axes.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        axes.set_ylabel("Share of account value", fontsize=10, color="#536369")
        if (total > 0).any():
            handles, legend_labels = axes.get_legend_handles_labels()
            figure.legend(handles, legend_labels, loc="upper left", bbox_to_anchor=(0.10, 0.77),
                          ncol=min(6, len(labels)), frameon=False, fontsize=8, borderaxespad=0)
        figure.text(0.10, 0.80, "Actual holdings drift between scheduled rebalances; empty balances are gaps",
                    fontsize=9, color="#536369")
        figure.savefig(output / "allocation.png")
