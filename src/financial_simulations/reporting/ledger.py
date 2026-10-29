"""CSV, JSON and static PNG outputs for a single-path retirement ledger."""

from dataclasses import asdict
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd


ACCOUNTS = (("cash", "Outside cash", "#9a8a2e"), ("outside_investments", "Outside investments", "#126a63"),
            ("accumulation", "Super accumulation", "#386a98"), ("pension", "Account-based pension", "#8363a0"))


def _annual_rows(result):
    rows = []
    for year in result.annual:
        assessment = asdict(year["assessment"])
        rows.append({**{k: v for k, v in year.items() if k != "assessment"},
                     **{f"tax_{k}": v for k, v in assessment.items() if k != "lines"}})
    return rows


def write_ledger_report(result, output, title, manifest=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result.daily.to_csv(output / "daily.csv", lineterminator="\n")
    result.events.to_csv(output / "events.csv", index=False, lineterminator="\n")
    summary = {"annual": _annual_rows(result), "outstanding": result.outstanding, "manifest": manifest or {}}
    (output / "annual.json").write_text(json.dumps(summary, indent=2, default=str, allow_nan=False) + "\n",
                                        encoding="utf-8", newline="\n")
    daily = result.daily
    with matplotlib.rc_context({"font.family": "DejaVu Sans", "font.size": 9}):
        figure = Figure(figsize=(12, 9.5), dpi=150, facecolor="#fafaf7")
        top, bottom = figure.subplots(2, 1, height_ratios=(3, 2))
        figure.subplots_adjust(left=0.09, right=0.97, top=0.86, bottom=0.11, hspace=0.35)
        figure.suptitle(title, fontsize=16, fontweight="bold", x=0.035, ha="left", y=0.97)
        figure.text(0.035, 0.925, "Daily account balances (AUD, nominal) | synthetic market input | tax liabilities settle after 30 June",
                    color="#536369")
        stack = np.vstack([daily[column].to_numpy() for column, _, _ in ACCOUNTS])
        top.stackplot(daily.index, stack, labels=[label for _, label, _ in ACCOUNTS],
                      colors=[color for _, _, color in ACCOUNTS], alpha=0.9)
        accessible = daily.index[daily["super_accessible"].to_numpy()]
        if len(accessible):
            top.axvline(accessible[0], color="#8c5144", linestyle="--", linewidth=1)
            top.annotate("super accessible", (accessible[0], top.get_ylim()[1] * 0.95), color="#8c5144", fontsize=8,
                         xytext=(4, 0), textcoords="offset points")
        top.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k"))
        top.set_ylabel("Balance")
        top.legend(loc="upper left", ncol=4, frameon=False, fontsize=8, bbox_to_anchor=(0, 1.12))
        columns = (("salary", "Salary (cash)", "#126a63", 1), ("employer_contributions", "Concessional contributions", "#386a98", 1),
                   ("pension_payments", "Pension payments", "#8363a0", 1), ("lump_sums", "Super lump sums", "#5b6770", 1),
                   ("spending_paid", "Spending paid", "#b76a42", -1), ("shortfall", "Spending shortfall", "#8c2f2f", -1))
        quarterly = daily.index[-1] - daily.index[0] > pd.Timedelta(days=760)
        monthly = daily[[c for c, *_ in columns]].resample("QS-JUL" if quarterly else "MS").sum()
        x = np.arange(len(monthly))
        width = 0.8 / len(columns)
        for i, (column, label, color, sign) in enumerate(columns):
            bottom.bar(x + (i - (len(columns) - 1) / 2) * width, sign * monthly[column], width, label=label, color=color)
        bottom.axhline(0, color="#8b989b", linewidth=0.7)
        bottom.set_xticks(x, [d.strftime("%b %y") for d in monthly.index], fontsize=7, rotation=90 if quarterly else 0)
        bottom.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k"))
        bottom.set_ylabel("Quarterly flow" if quarterly else "Monthly flow")
        bottom.legend(loc="upper left", ncol=6, frameon=False, fontsize=8, bbox_to_anchor=(0, 1.18))
        for ax in (top, bottom):
            ax.grid(axis="y", alpha=0.2)
            ax.spines[["top", "right"]].set_visible(False)
        annual = result.annual[-1]
        assessment = annual["assessment"]
        tax = f"net tax {assessment.net_tax:,.0f}" if assessment.net_tax >= 0 else f"refund {-assessment.net_tax:,.0f}"
        figure.text(0.035, 0.02, f"{annual['financial_year']}: taxable income {assessment.taxable_income:,} | {tax} "
                    f"settles {annual['tax_due']} | concessional {annual['concessional_contributions']:,.0f} "
                    f"of {annual['concessional_cap_available']:,.0f} cap | shortfall {annual['shortfall']:,.0f}", fontsize=8)
        figure.savefig(output / "ledger.png")
