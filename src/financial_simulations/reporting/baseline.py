"""Portable baseline report and summaries reconciled to the daily ledger."""

from base64 import b64encode
from html import escape
import json
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.portfolios.engine import PortfolioResult


def period_summary(result: PortfolioResult, frequency: str) -> pd.DataFrame:
    if frequency not in ("monthly", "annual"):
        raise ValueError("Summary frequency must be monthly or annual.")
    periods = result.daily.index.to_period("M" if frequency == "monthly" else "Y")
    rows = []
    for period, group in result.daily.groupby(periods, sort=True):
        flows = group["net_external_flow"].sum()
        pnl = group["market_pnl"].sum()
        opening, closing = group["opening_value"].iloc[0], group["value"].iloc[-1]
        if not np.isclose(closing, opening + flows + pnl, rtol=1e-11, atol=1e-8):
            raise ArithmeticError("Report does not reconcile to the daily ledger.")
        rows.append({
            "period": str(period), "first_date": group.index[0].date().isoformat(),
            "last_date": group.index[-1].date().isoformat(),
            "partial_period": (group.index[0].date() != period.start_time.date()
                               or group.index[-1].date() != period.end_time.date()),
            "opening_value": float(opening), "closing_value": float(closing),
            "market_pnl": float(pnl), "contributions": float(group["contributions"].sum()),
            "withdrawals_paid": float(group["withdrawals_paid"].sum()),
            "shortfall": float(group["shortfall"].sum()),
            "time_weighted_return": float((1 + group["performance_return"].dropna()).prod() - 1),
        })
    return pd.DataFrame(rows)


def summary_statistics(result: PortfolioResult) -> dict:
    daily = result.daily
    growth = (1 + daily["performance_return"].fillna(0.0)).cumprod().to_numpy()
    years = (daily.index[-1] - daily.index[0]).days / 365.25
    return {
        "currency": result.portfolio.currency, "basis": "nominal; supplied total returns; no additional fees or tax",
        "opening_date": daily.index[0].date().isoformat(), "last_date": daily.index[-1].date().isoformat(),
        "return_observations": int(daily["performance_return"].count()), "calendar_marks": len(daily),
        "initial_capital": result.initial_value + result.initial_cash,
        "final_value": float(daily["value"].iloc[-1]),
        "contributions": float(daily["contributions"].sum()),
        "withdrawals_paid": float(daily["withdrawals_paid"].sum()),
        "shortfall": float(daily["shortfall"].sum()),
        "time_weighted_return": float(growth[-1] - 1),
        "annualised_time_weighted_return": float(growth[-1] ** (1 / years) - 1) if years > 0 else None,
        "max_time_weighted_drawdown": float(np.min(growth / np.maximum.accumulate(growth) - 1)),
    }


def _plot_image(output: Path, filename: str, description: str) -> str:
    encoded = b64encode((output / filename).read_bytes()).decode("ascii")
    return f'<img src="data:image/png;base64,{encoded}" alt="{escape(description)}">'


def write_report(output: Path, result: PortfolioResult, manifest: dict, title: str) -> None:
    stats = manifest["summary"]
    mix = ", ".join(f"{asset} {weight:.1%}" for asset, weight in result.portfolio.weights.items())
    cards = "".join(f"<div><span>{label}</span><strong>{value}</strong></div>" for label, value in (
        ("Final nominal value", f"{stats['final_value']:,.2f} {escape(stats['currency'])}"),
        ("Time-weighted return", f"{stats['time_weighted_return']:.2%}"),
        ("Maximum time-weighted drawdown", f"{stats['max_time_weighted_drawdown']:.2%}"),
        ("Unfunded withdrawals", f"{stats['shortfall']:,.2f} {escape(stats['currency'])}"),
    ))
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>
body{{font:16px/1.6 system-ui,sans-serif;color:#172a2d;background:#f6f5f0;margin:0}}
main{{max-width:1100px;margin:3rem auto;padding:0 2rem}}h1{{font-size:2.4rem;line-height:1.2}}
.metrics{{display:flex;flex-wrap:wrap;gap:2rem;margin:2rem 0}}.metrics span{{display:block;font-size:.85rem}}
strong{{font-size:1.35rem}}img{{width:100%;height:auto;margin:1rem 0}}a{{color:#126a63}}
table{{border-collapse:collapse;width:100%;background:white;font-size:.85rem}}
th,td{{padding:.6rem;text-align:right;border-bottom:1px solid #ddd}}.table{{overflow:auto}}
details{{margin:2rem 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}}
</style></head><body><main><p>FINANCIAL SIMULATIONS · STAGE 1A</p><h1>{escape(title)}</h1>
<p>{escape(mix)}. Policy: {escape(result.portfolio.rebalance)}.</p>
<p>{stats['opening_date']} to {stats['last_date']}; {stats['return_observations']:,} daily return observations.
This is a deterministic historical baseline. Amounts are nominal {escape(stats['currency'])};
tax, Australian inflation, FX conversion and additional fees are outside this baseline.</p>
<section class="metrics">{cards}</section>
{_plot_image(output, 'wealth.png', 'Daily nominal account wealth and net capital supplied')}
{_plot_image(output, 'drawdown.png', 'Daily drawdown from the prior time-weighted performance peak')}
{_plot_image(output, 'allocation.png', 'Daily account allocation including retained cash')}
<p>PNG plots are generated directly from the daily ledger. Closed-market marks are carried
account valuations. All daily marks and source return observations are retained in the files.</p>
<h2>Annual accounting</h2><p>Partial periods are labelled. Returns compound daily performance;
deposits and withdrawals are reported separately from investment gains.</p>
<div class="table">{period_summary(result, 'annual').round(6).to_html(index=False, escape=True, border=0)}</div>
<h2>Inspect this run</h2><p><a href="wealth.png">Wealth plot</a> ·
<a href="drawdown.png">Drawdown plot</a> · <a href="allocation.png">Allocation plot</a> ·
<a href="daily.csv">Daily ledger</a> ·
<a href="market_returns.csv">Market returns</a> · <a href="source_observations.csv">Source observations</a> ·
<a href="monthly.csv">Monthly summary</a> · <a href="annual.csv">Annual summary</a> ·
<a href="manifest.json">Manifest</a></p>
<p>Trading-date contributions buy target proportions without resetting existing holdings.
Withdrawals use cash then proportional sales. On other dates only cash can be paid;
shortfalls are recorded without borrowing or automatic retry. Cash awaiting investment
is invested after the next observation's return. Annual rebalances occur before the
first return observation in each new calendar year. Initial cash is a separate
reserve, retained until spent; all cash earns zero interest in this baseline.</p>
<details><summary>Inputs, conventions and reproducibility</summary>
<pre>{escape(json.dumps(manifest, indent=2, allow_nan=False))}</pre></details>
</main></body></html>'''
    (output / "report.html").write_text(html, encoding="utf-8", newline="\n")
