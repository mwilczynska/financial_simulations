"""Static review images for the interactive planner's portfolio and ledger steps."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
import numpy as np
import pandas as pd

from financial_simulations.reporting.palette import (ADDED_COLOUR, BLUE, FLOW_COLOURS, NET_COLOUR, PORTFOLIO_COLOURS,
                                                     TIER_COLOURS)
from financial_simulations.retirement.flows import account_flows, fold_taxes, household_flows, milestones
from financial_simulations.retirement.real import real_daily, real_events


# The app's colours (ADR 0047): the PNG plots and the interactive charts use one palette.
COLORS = PORTFOLIO_COLOURS


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
        fig, ax = _figure("Historical portfolio growth", f"Full shared sample; {plan['market']['currency']} total returns; each account's rebalancing policy; reconstructed periods included")
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
        fig.text(0.10, 0.90, f"{plan['market']['paths']} shared stationary-bootstrap draws; growth of $100 in today's dollars; {plan['market']['currency']} returns", fontsize=9, color="#536369")
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
        subtitle = f"{complete} of {total} daily tax-ledger paths calculated; today's dollars ({'AUD' if plan['market']['currency'] == 'AUD' else 'AUD proxy from USD returns'}); unsupported draws excluded"
        if wide:
            subtitle += "\nLog-like y-axis above $1,000 keeps central paths visible beside the upper tail"
        fig, ax = _figure("Retirement wealth range", subtitle)
        dates = pd.to_datetime(retirement_bands["Date"])
        ax.fill_between(dates, retirement_bands["P05"], retirement_bands["P95"], color=BLUE, alpha=0.13, label="5th–95th percentile")
        ax.fill_between(dates, retirement_bands["P25"], retirement_bands["P75"], color=BLUE, alpha=0.25, label="25th–75th percentile")
        ax.plot(dates, retirement_bands["P50"], color=BLUE, linewidth=1.7, label="Median")
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
        flows = fold_taxes(household_flows(daily, inflation=True))
        fig, ax = _figure("Money in and out each year",
                          "Path nearest median ending wealth; today's dollars; years end 30 June; in above zero, out below; "
                          "line = net change in wealth\nTax = income tax, contributions tax, super fund tax and "
                          "Division 296 tax")
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
        ax.plot(years, net, color=NET_COLOUR, marker="o", markersize=3, linewidth=1.6, label="Net change in wealth")
        moves = account_flows(daily, real_events(representative.events, daily.index[0], cpi))
        added = moves.loc[moves["Flow"] == "Savings invested"].groupby("FY ending")["AUD"].sum().reindex(years, fill_value=0)
        if added.abs().max() > 1e-6:
            ax.plot(years, added, color=ADDED_COLOUR, linestyle="--", marker="s", markersize=4, linewidth=1.6,
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


def write_path_markets_plot(output: Path, plan, growth, stats, path):
    """Write the representative path's markets: growth of $1 for each portfolio and ticker, with its statistics.

    The same lines and figures as the top panel and table of the app's single-path view (ADR 0049). ``growth`` and
    ``stats`` come from ``path_markets``.
    """
    from financial_simulations.reporting.palette import TICKER_COLOURS, portfolio_line_colours
    from financial_simulations.retirement.path_markets import PORTFOLIO, real_growth

    real = real_growth(growth, plan["assumptions"]["cpi_annual"])
    tickers = {t: TICKER_COLOURS[i % len(TICKER_COLOURS)] for i, t in enumerate(plan["assets"])}
    # Three portfolios when a combined one leads the two entered.
    portfolio_colours = iter(portfolio_line_colours((stats["Kind"] == PORTFOLIO).sum()))
    with matplotlib.rc_context({"font.family": "DejaVu Sans"}):
        fig, ax = _figure("Markets on the path nearest median ending wealth",
                          f"Path {path}: growth of $1 invested on the first day, today's dollars, log scale\n"
                          "Legend: growth per year before inflation (CAGR) · volatility of daily returns, annualised "
                          "· worst drawdown")
        for row in stats.to_dict("records"):
            portfolio = row["Kind"] == PORTFOLIO
            ax.plot(real.index, real[row["Series"]], color=next(portfolio_colours) if portfolio else tickers[row["Series"]],
                    linewidth=2.2 if portfolio else 1.0, zorder=3 if portfolio else 2,
                    label=f"{row['Series']}: {row['CAGR']:.1%} · {row['Volatility']:.0%} · {row['Worst drawdown']:.0%}")
        ax.axhline(1, color="#5f6b73", linewidth=0.8, linestyle=":")
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}" if v >= 1 else f"${v:g}"))
        ax.set_ylabel("Growth of $1, today's dollars (log scale)")
        _years(ax, list(real.index))
        for _, mark in milestones(plan, real.index[0].date(), real.index[-1].date()).iterrows():
            ax.axvline(mark["Date"], color="#5f6b73", linestyle="--", linewidth=1)
            ax.text(mark["Date"], ax.get_ylim()[1], " " + mark["Event"], fontsize=8, color="#3c474d", va="top")
        ax.xaxis.grid(True, alpha=0.22)
        fig.subplots_adjust(bottom=0.27)
        ax.legend(frameon=False, ncol=3, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.09))
        fig.savefig(Path(output) / "retirement_markets.png")


def write_outcome_plot(output: Path, plan, retirement_paths, retirement_annual):
    """Write one strategy's path outcomes: the share of paths in each state each year, and average retirement
    spending by group of paths (ADR 0048). The same figures as the app's Outcomes page."""
    from financial_simulations.retirement.outcomes import (TIERS, full_age_pension_by_year, group_spending, path_outcomes,
                                                           state_shares, tier_shares, yearly_states)

    output = Path(output)
    full_rate = full_age_pension_by_year(plan)
    outcomes = path_outcomes(retirement_paths, retirement_annual, full_rate)
    shares = state_shares(yearly_states(outcomes, retirement_annual, full_rate))
    overall = tier_shares(outcomes)
    spending = group_spending(outcomes)
    with matplotlib.rc_context({"font.family": "DejaVu Sans"}):
        fig = Figure(figsize=(11, 8.6 if len(spending) else 5.5), dpi=150, facecolor="#f9f9f7")
        axes = fig.subplots(2 if len(spending) else 1, 1, squeeze=False,
                            gridspec_kw={"height_ratios": [1.15, 1]} if len(spending) else None)[:, 0]
        fig.subplots_adjust(left=0.27, right=0.97, top=0.86, bottom=0.08, hspace=0.42)
        fig.text(0.06, 0.955, "How the paths fared", fontsize=16, fontweight="bold", color="#19353a")
        fig.text(0.06, 0.915, f"{len(outcomes)} calculated paths, by the worst they reached: "
                 + "; ".join(f"{tier.lower()} {overall[tier]:.0%}" for tier in TIERS), fontsize=9, color="#536369")
        ax = axes[0]
        years = sorted(shares["FY ending"].unique())
        wide = shares.pivot(index="FY ending", columns="State", values="Share").reindex(years)
        # Worst state at the bottom, so the trouble grows up from the axis.
        order = list(reversed(TIERS))
        ax.stackplot(years, [wide[tier].to_numpy() for tier in order], colors=[TIER_COLOURS[tier] for tier in order],
                     labels=order, linewidth=0.6, edgecolor="#f9f9f7")
        ax.set_xlim(years[0], years[-1])
        ax.set_ylim(0, 1)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
        ax.set_ylabel("Share of paths")
        ax.set_title("State of every path in each year ending 30 June (ran out holds from the first shortfall)",
                     fontsize=10, loc="left", color="#19353a")
        for _, mark in milestones(plan, date_of(years[0]), date_of(years[-1])).iterrows():
            ax.axvline(mark["Position"], color="#5f6b73", linestyle="--", linewidth=1)
            ax.text(mark["Position"], 1.0, " " + mark["Event"], fontsize=8, color="#3c474d", va="top")
        ax.set_facecolor("#f9f9f7")
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, ncol=4, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.09))
        if len(spending):
            ax = axes[1]
            rows = spending.iloc[::-1].reset_index(drop=True)
            colours = [TIER_COLOURS.get(name, BLUE) for name in rows["Group"]]
            ax.hlines(rows.index, rows["P10"], rows["P90"], colors=colours, linewidth=5, alpha=0.35)
            ax.scatter(rows["Median"], rows.index, color=colours, s=46, zorder=3)
            ax.set_yticks(rows.index, [f"{g} ({n})" for g, n in zip(rows["Group"], rows["Paths"])], fontsize=8)
            ax.set_xlim(left=0)
            ax.xaxis.set_major_formatter(FuncFormatter(_money))
            ax.grid(axis="x", alpha=0.22)
            ax.set_axisbelow(True)
            ax.set_title("Average spending paid per retired year, today's dollars: median path and 10th to 90th "
                         "percentile", fontsize=10, loc="left", color="#19353a")
            ax.set_facecolor("#f9f9f7")
            ax.spines[["top", "right"]].set_visible(False)
        fig.savefig(output / "retirement_outcomes.png")


def date_of(fy_ending):
    """30 June of a financial year, for placing life events on a year axis."""
    from datetime import date

    return date(int(fy_ending), 6, 30)


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
