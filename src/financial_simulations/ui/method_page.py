"""The Method page: what is modelled, the equations behind it and the assumptions the results rest on (ADR 0058).

The page is text, so it is kept as Markdown with ``[[name]]`` placeholders that ``fill`` replaces with figures from
the run on screen (its dates, path counts, block length, rule values). Maths is LaTeX between dollar signs, so a
literal dollar sign is written ``\\$`` and percentages stay outside the maths (``%`` starts a LaTeX comment).

The detailed, sourced documents are in ``docs/methodology``; this page is their summary for the person reading
results, and every figure on it is read from the plan, the market data or the rule sets, not typed in.
"""

from datetime import date
from math import sqrt
import re

import pandas as pd
import streamlit as st

from financial_simulations.markets.calendar import observations_per_year
from financial_simulations.retirement.real import year_deflator
from financial_simulations.retirement.strategy_results import STRATEGY_NAMES
from financial_simulations.rules.au.age_pension import FORTNIGHTS, maximum_rate
from financial_simulations.rules.au.parameters import load_ruleset
from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets
from financial_simulations.rules.au.superannuation import age_on, preservation_age
from financial_simulations.ui.theme import card, page_title


def fill(text: str, values: dict) -> str:
    """``text`` with each ``[[name]]`` replaced by ``values[name]``. An unknown name is an error, not a blank."""
    return re.sub(r"\[\[(\w+)\]\]", lambda match: str(values[match.group(1)]), text)


def money(value) -> str:
    """Whole dollars for Markdown: the dollar sign is escaped so that two of them are not read as maths."""
    return f"\\${value:,.0f}"


def percent(value, digits=1) -> str:
    return f"{value:.{digits}%}"


def projected_rules(plan: dict, through: str) -> dict:
    """The rule sets the ledger used, 2026-27 to ``through``, rebuilt from the plan's CPI and wage assumptions."""
    assumptions = ProjectionAssumptions(plan["assumptions"]["cpi_annual"], plan["assumptions"]["wage_growth_annual"])
    return project_rulesets(load_ruleset("2026-27"), through, assumptions)


def _plain(value) -> str:
    """A rule parameter's value as text for a table."""
    if isinstance(value, dict):
        return "; ".join(f"{name.replace('_', ' ')} {_plain(item)}" for name, item in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_plain(item) for item in value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return f"{value:,.4g}" if abs(value) < 1000 else f"{value:,.0f}"


def assumed_parameters(rules: dict) -> pd.DataFrame:
    """Every rule parameter that is assumed or projected in the last year, with its first and last values."""
    first, last = next(iter(rules.values())), list(rules.values())[-1]
    basis = {"assumption": "Assumed", "projected": "Projected"}
    rows = [{"Parameter": parameter.name.replace("_", " "), "Basis": basis[parameter.status],
             first.financial_year: _plain(first.parameters[parameter.name].value) if parameter.name in first.parameters else "–",
             last.financial_year: _plain(parameter.value), "How it is set": parameter.note}
            for parameter in last.assumptions()]
    return pd.DataFrame(rows)


def markdown_table(frame: pd.DataFrame) -> str:
    """A frame of text as a Markdown table, which wraps long cells where a data grid would cut them off."""
    lines = ["| " + " | ".join(frame.columns) + " |", "|" + " --- |" * len(frame.columns)]
    for row in frame.itertuples(index=False):
        lines.append("| " + " | ".join(str(cell).replace("$", "\\$").replace("|", "/") for cell in row) + " |")
    return "\n".join(lines)


def projection_table(rules: dict, start, cpi: float, homeowner: bool) -> str:
    """The thresholds that matter most to results: their value now, in the last year, and that in today's dollars."""
    first, last = next(iter(rules.values())), list(rules.values())[-1]
    prices = year_deflator(int(last.financial_year[:4]) + 1, start, cpi)
    limit = "homeowner" if homeowner else "non_homeowner"
    rows = [
        ("Top of the tax-free band", lambda r: r["resident_tax_thresholds"][0], "Fixed in dollars: the law has no indexation"),
        ("Start of the top tax rate", lambda r: r["resident_tax_thresholds"][-1], "Fixed in dollars"),
        ("Division 293 threshold", lambda r: r["division_293"]["threshold"], "Fixed in dollars"),
        ("Medicare levy low-income threshold", lambda r: r["medicare_low_income_lower"],
         "Set by Parliament each year; held at the latest published value"),
        ("Concessional contributions cap", lambda r: r["concessional_cap"], "Wage growth, in \\$2,500 steps"),
        ("Transfer balance cap", lambda r: r["transfer_balance_cap"], "CPI, in \\$100,000 steps"),
        ("Division 296 threshold", lambda r: r["division_296"]["large_balance"], "CPI, in \\$150,000 steps"),
        ("Full Age Pension, a year", lambda r: FORTNIGHTS * maximum_rate(r),
         "Basic rate with wage growth; supplement with CPI; energy supplement fixed"),
        ("Age Pension assets limit", lambda r: r["age_pension_assets_test"][limit], "CPI"),
        ("Deeming threshold", lambda r: r["deeming"]["threshold"], "CPI; the deeming rates stay as they are"),
    ]
    head = (f"| Rule | {first.financial_year} | {last.financial_year} | {last.financial_year}, today's dollars | "
            "How later years are set |")
    lines = [head, "| --- | ---: | ---: | ---: | --- |"]
    for name, value, how in rows:
        lines.append(f"| {name} | {money(value(first))} | {money(value(last))} | {money(value(last) / prices)} | {how} |")
    return "\n".join(lines)


def bracket_table(rules: dict) -> str:
    """The marginal scale in the first year and, where the run reaches it, from 2027-28."""
    first = next(iter(rules.values()))
    later = rules.get("2027-28")
    thresholds = first["resident_tax_thresholds"]
    head = f"| Taxable income | {first.financial_year} |" + (" From 2027-28 |" if later else "")
    lines = [head, "| --- | ---: |" + (" ---: |" if later else ""),
             f"| Up to {money(thresholds[0])} | nil |" + (" nil |" if later else "")]
    for i, low in enumerate(thresholds):
        band = f"{money(low)} to {money(thresholds[i + 1])}" if i + 1 < len(thresholds) else f"Over {money(low)}"
        lines.append(f"| {band} | {first['resident_tax_rates'][i]:.0%} |"
                     + (f" {later['resident_tax_rates'][i]:.0%} |" if later else ""))
    return "\n".join(lines)


def facts(run) -> dict:
    """Every figure the page's text quotes, read from the run."""
    plan, portfolios, market = run.plan, run.portfolios, run.market
    strategies = run.strategies or {run.rule: run}
    start, end = run.result.daily.index[0].date(), run.result.daily.index[-1].date()
    years = (end - start).days / 365.25
    cpi, wage = plan["assumptions"]["cpi_annual"], plan["assumptions"]["wage_growth_annual"]
    paths, ledgers = plan["market"]["paths"], len(run.retirement_paths)
    length = plan["market"]["block_length"]
    rows = market.manifest["common_returns"]
    history = pd.Timestamp(market.manifest["common_last"]) - pd.Timestamp(market.manifest["common_first"])
    history_years = history.days / 365.25
    steps = len(portfolios.dates) - 1
    keep = 1 - 1 / length
    summary = portfolios.summary.set_index("Portfolio")
    series = "Combined" if "Combined" in summary.index else summary.index[0]
    volatility = float(summary.loc[series, "Volatility"])
    rules = projected_rules(plan, list(run.rules_manifest)[-1])
    first, last = next(iter(rules.values())), list(rules.values())[-1]
    last_prices = year_deflator(int(last.financial_year[:4]) + 1, start, cpi)
    pension, assets_test = first["age_pension_rate"], first["age_pension_assets_test"]
    income_test, deeming, sapto, lito = first["age_pension_income_test"], first["deeming"], first["sapto"], first["lito"]
    homeowner, born = plan["person"]["homeowner"], date.fromisoformat(plan["person"]["date_of_birth"])
    opening_year = start.year if start.month >= 7 else start.year - 1
    limit = assets_test["homeowner" if homeowner else "non_homeowner"]
    taper = assets_test["taper_per_1000"] * FORTNIGHTS / 1000
    spending = plan["spending"]
    start_rule = {"same": "the same as before retirement",
                  "amount": f"{money(spending.get('retirement_annual', 0))} a year in today's dollars",
                  "percent": f"{percent(spending['retirement_percent'])} of spendable wealth on the retirement date"}
    estate, loan, home = plan["investment_property"], plan["mortgage"], plan["home"]
    holdings = [f"a home loan of {money(loan['balance'])}" if loan["balance"] > 0 else "",
                f"a home valued at {money(home['value'])}" if home["value"] > 0 else "",
                (f"an investment property valued at {money(estate['value'])}"
                 + (f" with {money(estate['loan'])} owed" if estate["loan"] > 0 else "")) if estate["value"] > 0 else "",
                f"rent of {money(plan['person']['weekly_rent'])} a week" if plan["person"]["weekly_rent"] > 0 else ""]
    holdings = [item for item in holdings if item]
    yields = "\n".join(f"| {ticker} | {percent(market.income_yields[ticker], 2)} |" for ticker in plan["assets"])
    return {
        "start": f"{start:%d %B %Y}", "end": f"{end:%d %B %Y}", "years": f"{years:.0f}",
        "age_end": age_on(born, end), "preservation": preservation_age(born, first),
        "tickers": len(plan["assets"]), "rows": f"{rows:,}", "first": market.manifest["common_first"],
        "last": market.manifest["common_last"], "history_years": f"{history_years:.0f}",
        "paths": f"{paths:,}", "ledgers": f"{ledgers:,}", "strategy_count": len(strategies),
        "strategy_names": ", ".join(STRATEGY_NAMES[rule] for rule in strategies),
        "ledger_runs": f"{ledgers * len(strategies):,}",
        "steps": f"{steps:,}", "length": length, "jump": percent(1 / length), "seed": plan["market"]["seed"],
        "blocks": f"{steps / length:,.0f}", "history_blocks": f"{rows / length:,.0f}",
        "keep_month": percent(keep ** 21, 0), "keep_year": percent(keep ** 252, 0),
        "density": f"{observations_per_year(market.path.dates):.0f}",
        "windows": f"{history_years / years:.1f}",
        "series": series.lower(), "volatility": percent(volatility, 0),
        "mean_error": f"{100 * volatility / sqrt(history_years):.1f}",
        "tail_paths": f"{0.05 * paths:,.0f}", "tail_paths_sd": f"{sqrt(paths * 0.05 * 0.95):.1f}",
        "tail_ledgers": f"{0.05 * ledgers:,.1f}", "tail_ledgers_sd": f"{sqrt(ledgers * 0.05 * 0.95):.1f}",
        "share_error_10": f"{100 * sqrt(0.1 * 0.9 / ledgers):.1f}", "share_error_50": f"{100 * sqrt(0.25 / ledgers):.1f}",
        "paths_error_10": f"{100 * sqrt(0.1 * 0.9 / paths):.1f}", "paths_error_50": f"{100 * sqrt(0.25 / paths):.1f}",
        "cpi": percent(cpi), "wage": percent(wage), "cash_interest": percent(plan["outside"]["cash_interest"]),
        "real_wage": percent((1 + wage) / (1 + cpi) - 1, 2), "buffer": money(plan["outside"]["cash_buffer"]),
        "realised": percent(plan["super"]["realised_gains"], 0),
        "nominal_million": money(1e6 / (1 + cpi) ** 20), "start_iso": plan["plan"]["start_date"],
        "yields": yields,
        "outside_rebalance": "every January" if plan["outside"]["rebalance"] == "annual" else "never (buy and hold)",
        "super_rebalance": "every January" if plan["super"]["rebalance"] == "annual" else "never (buy and hold)",
        "saving": ("all cash above the buffer" if plan["outside"]["saving"] == "surplus"
                   else f"{money(plan['outside']['contribution_per_year'])} a year, as far as cash above the buffer allows"),
        "start_rule": start_rule[spending["retirement"]],
        "real_change": percent(spending["real_change"]), "band": percent(spending["guardrail_band"], 0),
        "step": percent(spending["guardrail_step"], 0), "ceiling": percent(spending["ceiling"]),
        "floor": percent(spending["floor"]),
        "bounds": ("none" if not spending["minimum"] and not spending["maximum"] else
                   " and ".join(part for part in (f"a minimum of {money(spending['minimum'])}" if spending["minimum"] else "",
                                                  f"a maximum of {money(spending['maximum'])}" if spending["maximum"] else "")
                                if part) + " a year in today's dollars"),
        "brackets": bracket_table(rules), "projection": projection_table(rules, start, cpi, homeowner),
        "first_fy": first.financial_year, "last_fy": last.financial_year,
        "creep": percent(1 / last_prices, 0), "creep_years": int(last.financial_year[:4]) - opening_year,
        "cap": money(first["concessional_cap"]), "transfer_cap": money(first["transfer_balance_cap"]),
        "large": money(first["division_296"]["large_balance"]), "very_large": money(first["division_296"]["very_large_balance"]),
        "sg": percent(first["super_guarantee_rate"], 0), "lito": money(lito["maximum"]), "lito_out": money(lito["cut_out"]),
        "medicare_lower": money(first["medicare_low_income_lower"]),
        "division_293": money(first["division_293"]["threshold"]),
        "pension_fortnight": f"\\${maximum_rate(first):,.2f}", "pension_year": money(FORTNIGHTS * maximum_rate(first)),
        "pension_last": money(FORTNIGHTS * maximum_rate(last) / last_prices),
        "limit": money(limit), "tenure": "a homeowner" if homeowner else "a non-homeowner",
        "cut_off": money(round(limit + maximum_rate(first) / assets_test["taper_per_1000"] * 1000, -3)),
        "taper": percent(taper), "taper_dollars": f"\\${assets_test['taper_per_1000']:,.0f}",
        "free_area": money(income_test["free_area"]), "deeming_threshold": money(deeming["threshold"]),
        "deeming_low": percent(deeming["lower_rate"], 2), "deeming_high": percent(deeming["upper_rate"], 2),
        "income_taper": percent(income_test["taper"] * deeming["upper_rate"]),
        "taxable_share": percent((pension["basic"] + pension["supplement_taxable"]) / maximum_rate(first)),
        "sapto": money(sapto["maximum"]), "sapto_from": money(sapto["shade_out"]), "sapto_out": money(sapto["cut_out"]),
        "other_assets": money(plan["person"]["other_assets"]),
        "holdings": ("This plan has " + ", ".join(holdings) + "." if holdings else
                     "This plan has no home loan, home value, rent or investment property, so nothing on this tab affects "
                     "its results."),
        "property_growth": percent(estate["growth"]), "property_costs": percent(estate["running_costs"]),
        "loss_rule": ("reduces tax on other income (negative gearing)" if estate["losses_offset_salary"]
                      else "is carried forward against later rent"),
        "home_growth": percent(home["growth"]), "home_costs": percent(home["running_costs"]),
    }


OVERVIEW = r"""
#### What is modelled

One Australian tax resident's money from [[start]] to [[end]] ([[years]] years, to age [[age_end]]), one calendar day
at a time. The model is an accounting system with a single random input: the daily returns of the [[tickers]] selected
tickers. Given one sequence of returns, everything else follows from the plan and the tax rules with no further
randomness:

$$
x_d = F\big(x_{d-1},\ r_d;\ \text{plan},\ \text{rules}_{\mathrm{FY}(d)}\big)
$$

- $x_d$ is the ledger's state at the close of day $d$: cash, every parcel of investments held outside super, the super
  accumulation and pension accounts, any loans and property, and the tax year's running totals.
- $r_d$ is that day's return for each ticker (there is none on a day without trading).
- $F$ applies the day's events in a fixed order: interest, the market return, pay, contributions, spending, tax and, on
  30 June, the year's tax assessment under that financial year's rules.

A run repeats this for many return sequences and reports how the results are distributed.

| Stage | What it does | In this run |
| --- | --- | --- |
| 1. History | The tickers' daily total returns on the dates they share, as a matrix $R$ with one row per day | [[rows]] days × [[tickers]] tickers, [[first]] to [[last]] |
| 2. Resampling | A stationary block bootstrap of the rows of $R$ gives each path its returns | [[paths]] paths × [[steps]] trading days |
| 3. Portfolios | Each account's mix is compounded along every path, with no money in or out and no tax (the Markets page) | [[paths]] paths |
| 4. Ledger | The first paths go through the daily tax ledger, once for each spending strategy | [[ledgers]] paths × [[strategy_count]] ([[strategy_names]]) = [[ledger_runs]] ledgers |
| 5. Summaries | Amounts are converted to today's dollars, each path is classified, and percentiles are taken across paths | Outcomes, Paths and Compare pages |

#### What is random and what is fixed

| Input | Treatment | In this plan |
| --- | --- | --- |
| Daily returns of every ticker | **Random:** resampled from history | Mean block [[length]] trading days |
| Inflation (CPI) | Constant | [[cpi]] a year |
| Wage growth | Constant | [[wage]] a year |
| Interest on cash | Constant | [[cash_interest]] a year |
| Tax, super and Age Pension rules | [[first_fy]] law, carried forward by fixed rules | See *Tax and super* |
| Property values, rents and loan rates | Constant growth and rates | See *Property and loans* |
| Spending needs | Exactly what the strategy says | See *Spending strategies* |
| Length of life | Not modelled: every path runs to the same end date | To age [[age_end]] |

The spread of outcomes on every page is therefore **market risk only**, as history sampled it. Inflation surprises,
changes to the law, wages, health and how long you live are outside the model, so the real spread is wider than the
one shown. The *Assumptions* tab lists what each simplification does to the results.
"""

DOLLARS = r"""
#### Today's dollars

The ledger runs in **nominal** dollars, because tax brackets, caps and capital gains are defined in nominal dollars.
Results are then converted to dollars of [[start_iso]], the plan's start, at the constant CPI $c$ = [[cpi]]. Balances and
flows use different steps:

$$
\tilde{W}_d = \frac{W_d}{(1+c)^{(d - d_0)/365.25}}
\qquad\qquad
\tilde{f}_y = \frac{f_y}{(1+c)^{\,y - y_0}}
$$

- A **balance** $W_d$ on day $d$ is divided by the price level on that day.
- A **flow** $f_y$ during financial year $y$ (salary, spending, tax, returns) is divided by the price step for whole
  financial years since the opening year $y_0$. Spending is indexed on the same 1 July step, so spending that keeps
  its buying power shows the same amount every year.
- Prices keep rising inside a year while flows are stepped, so a year's change in real wealth is not the sum of its
  real flows. The difference is reported as an **Inflation** flow, $\Delta\tilde{W}_y - \sum \tilde{f}_y$: the buying
  power that wealth lost that year. With it, each year's bars add up exactly.

For scale, a nominal \$1,000,000 in 20 years is [[nominal_million]] in today's dollars.

| Item | How it is shown |
| --- | --- |
| Wealth and balances | Today's dollars, by date |
| Yearly money in and out | Today's dollars, by financial year |
| Simulated portfolio growth (Markets) | After inflation; volatility and drawdowns use nominal daily returns |
| Historical returns (Markets) | **Nominal**: the source data have no inflation history |
| Withdrawal rates | A ratio of nominal amounts in the same year, so unaffected |
| Event log and CSV downloads | The ledger's nominal records |
"""

MARKETS = r"""
#### Source history

The tickers' daily **total returns** (price change plus distributions, after fund fees and, for leveraged funds,
their financing costs) on the dates they all have: [[first]] to [[last]], [[history_years]] years. They form a matrix
$R$ with $n$ = [[rows]] rows and one column per ticker, where row $j$ holds every ticker's return on the same day. A
step across a date that some ticker lacks compounds the total-return levels between the shared dates; no zero return
is inserted. Returns are nominal and in US dollars.

#### Stationary block bootstrap

A simulated path is a sequence of row numbers $J_1, \dots, J_T$, one per future trading day ($T$ = [[steps]]), and its
returns are $r_t = R_{J_t}$. With mean block length $L$ = [[length]] and $p = 1/L$ (Politis and Romano, 1994):

$$
J_1 \sim \mathrm{Uniform}\{0,\dots,n-1\}, \qquad
J_{t+1} = \begin{cases}
(J_t + 1) \bmod n & \text{with probability } 1-p \\
\mathrm{Uniform}\{0,\dots,n-1\} & \text{with probability } p
\end{cases}
$$

So a path is a chain of blocks of consecutive history. Each block starts on a uniformly random day and has a geometric
length $K$, $P(K=k) = (1-p)^{k-1}p$, with mean $L$ and standard deviation $\sqrt{1-p}/p \approx L$. A path of this
length is about [[blocks]] blocks. The row number wraps from the end of the history to its start, which makes every row
equally likely at every step. Conditional on the history, the simulated series is stationary, hence the name.

| Property of the history | In the simulated paths |
| --- | --- |
| Each day's joint behaviour across tickers: correlations, joint crashes, fat tails | Kept exactly. Whole rows are drawn, never one ticker on its own |
| Each ticker's mean daily return | Kept in expectation: every row has probability $1/n$ |
| Dependence between days $h$ apart: momentum, volatility clustering | Autocovariance is multiplied by $(1-p)^h$, the chance both days are in one block: [[keep_month]] remains at one month and [[keep_year]] at one year |
| Dependence over several years: valuation cycles, mean reversion, interest-rate regimes | Lost. Stretches a few blocks apart are independent |
| Days more extreme than any in the history | Never occur. Bad stretches can repeat or join, though, so a path's drawdown can be deeper or longer than any in history |

**Why blocks.** Independent daily draws ($L=1$) would erase volatility clustering, and with it the drawdowns lasting
months that decide whether a retirement survives its first years. Longer blocks keep them but leave fewer distinct
pieces to draw from: the history holds about [[history_blocks]] non-overlapping blocks of this length. $L$ is a setting
(Plan, Assumptions), not an estimate, and no best value has been fitted. Because years are close to independent once
$L$ is well under a year, the spread of long-run outcomes grows roughly as it would for independent annual returns. If
real markets revert to the mean over many years, that overstates the long-run spread; if they trend through long
regimes, it understates it.

**Random numbers.** Path $k$ has its own stream, `PCG64(SeedSequence([seed, 3, L, T, k]))`, with seed [[seed]]. It
depends on nothing else, so path $k$ is the same sequence whatever the number of paths, the portfolio weights or the
spending strategy. Both accounts and every compared strategy see identical markets on path $k$, and the difference
between two strategies on a path is the strategy's effect alone. Changing $L$ or the horizon changes every path.

#### Future trading days

The history has [[density]] observations per year, fewer than the 261 weekdays (holidays, and dates missing from the
joint sample). The future calendar keeps weekdays in order while their count stays within that rate, so the dropped
days are spread evenly. One sampled row is applied per future trading day, which keeps expected growth and variance
per calendar year equal to the history's. The dates are a template for the ledger, not a forecast of holidays.

#### From ticker returns to a portfolio

With target weights $w$, the position in ticker $a$ starts at $100\,w_a$ and

$$
h_{t,a} = h'_{t-1,a}\,(1 + r_{t,a}), \qquad V_t = \sum_a h_{t,a}, \qquad
h'_{t-1} = \begin{cases}
V_{t-1}\,w & \text{on the first trading day of a calendar year, if rebalanced} \\
h_{t-1} & \text{otherwise}
\end{cases}
$$

In this plan the outside-super mix is rebalanced [[outside_rebalance]] and the super mix [[super_rebalance]]. The
Markets page reports, for each path or for the history,

$$
\text{CAGR} = \Big(\frac{V_T}{V_0}\Big)^{365.25/\text{days}} - 1, \qquad
\sigma = \mathrm{sd}\Big(\frac{V_t}{V_{t-1}} - 1\Big)\sqrt{252}, \qquad
\text{drawdown} = \min_t \Big(\frac{V_t}{\max_{s \le t} V_s} - 1\Big)
$$

**Why rebalancing shows up as extra growth.** A mix held at fixed weights $w$, with covariance matrix $\Sigma$ and
ticker variances $\sigma_a^2$, grows faster than the weighted average of its parts' growth rates by about

$$
\tfrac{1}{2}\Big(\sum_a w_a \sigma_a^2 - w^\top \Sigma\, w\Big) \ \ge\ 0
$$

a year, under continuous rebalancing. The term is large for volatile, weakly correlated holdings such as leveraged
funds, and annual rebalancing captures part of it. This is arithmetic, not a forecast, and the ledger taxes it outside
super: each January rebalance there is a sale with capital gains.

#### How precise the percentiles are

There are two separate errors.

**Simulation error** comes from the finite number of paths and shrinks as paths are added. The number of paths below
a true quantile $\alpha$ is Binomial$(N, \alpha)$, with standard deviation $\sqrt{N\alpha(1-\alpha)}$; a share
estimated as $\hat\pi$ from $M$ paths has standard error $\sqrt{\hat\pi(1-\hat\pi)/M}$.

| Results | Paths | Paths below the 5th percentile | Standard error of a 10% share | Of a 50% share |
| --- | ---: | ---: | ---: | ---: |
| Markets page | [[paths]] | [[tail_paths]] ± [[tail_paths_sd]] | [[paths_error_10]] points | [[paths_error_50]] points |
| Ledger: Outcomes, Paths, Compare | [[ledgers]] | [[tail_ledgers]] ± [[tail_ledgers_sd]] | [[share_error_10]] points | [[share_error_50]] points |

Compared strategies share their paths, so the error in the *difference* between two strategies is much smaller than
the error in either one's level.

**The history is one sample**, and more paths cannot fix that. Every path rearranges the same [[history_years]]-year
record, which holds only about [[windows]] non-overlapping periods as long as this plan. The record's average return is
carried into every path, but its uncertainty is not. As a rough guide, the standard error of a mean yearly log return
estimated from $Y$ years at volatility $\sigma$ is $\sigma/\sqrt{Y}$: for the [[series]] portfolio ([[volatility]]
volatility) that is about [[mean_error]] percentage points a year. Results are best read as "if the future is drawn
from this history", not as probabilities of what will happen.

*Reference: Politis, D. N. and Romano, J. P. (1994), The stationary bootstrap, Journal of the American Statistical
Association 89(428), 1303–1313.*
"""

LEDGER = r"""
#### State and three measures of wealth

The ledger runs in nominal Australian dollars on **every calendar day**. It holds cash $C$; every parcel bought outside
super (ticker, units, cost base, purchase date); units in super accumulation and in the account-based pension; a unit
price $P_a$ for each ticker, starting at 1; loans and property; and the tax year's running totals. From these:

$$
\begin{aligned}
\text{assets} \quad & A_d = C + \sum_a P_a\big(u^{\text{outside}}_a + u^{\text{accumulation}}_a + u^{\text{pension}}_a\big) \\
\text{spendable wealth} \quad & S_d = A_d - \text{home loan} \\
\text{total wealth} \quad & W_d = S_d + \text{investment property} - \text{its loan}
\end{aligned}
$$

The home is in neither measure. Spending strategies use $S$, because the model never sells the property.

#### One day, in order

| Step | When | What happens |
| --- | --- | --- |
| 1 | 1 July | The new year's rules apply; the spending strategy reviews spending against the 30 June close |
| 2 | Every day | Loans accrue interest. Cash earns $(1+i)^{1/365.25} - 1$, with $i$ = [[cash_interest]] a year, taxed as interest |
| 3 | First trading day of a calendar year | Accounts are rebalanced to their weights, before that day's return |
| 4 | Trading days | Every unit price moves: $P_a \leftarrow P_a(1 + r_{d,a})$ |
| 5 | Last trading day of a quarter | Distributions: part of each price is paid out as income (below) |
| 6 | Fortnightly paydays | Salary arrives less tax withheld; the employer's super contribution is queued |
| 7 | Fortnightly from age 67 | The Age Pension is assessed on the previous close and paid |
| 8 | Seven business days after payday | The contribution reaches the fund, which deducts 15% tax and buys units |
| 9 | First of the month | The month's spending falls due; rent and property costs likewise |
| 10 | Trading days | Amounts due are paid, in order: loan repayments, housing costs, spending, tax. Then the pension's minimum instalment (month end), then spare cash is invested |
| 11 | 30 June | The year's income tax, fund tax and Division 296 are assessed |
| 12 | Month end | Loans charge their accrued interest; property values grow |
| 13 | Every day | The books must balance (below) |

Returns apply only on trading days. A payment that needs a sale waits for the next trading day; no return is invented
for a weekend.

**The check.** At each day's close the ledger verifies

$$
A_d = A_{d-1} + \underbrace{\text{market gain} + \text{salary} + \text{contributions} + \text{interest} + \text{Age Pension} + \text{rent}}_{\text{money in}}
- \underbrace{\text{spending} + \text{taxes} + \text{housing and property costs} + \text{loan principal}}_{\text{money out}}
$$

to within $10^{-6} + 10^{-11}\lvert A_d\rvert$ dollars, and stops with an error otherwise. Each loan and the property
value are reconciled the same way. Buying, selling, distributions, pension payments and lump sums move money between
your own accounts, so they do not appear. The yearly *money in and out* charts are this identity summed over a year.

#### Income and growth: splitting the return

The source data give each ticker's total return, but tax treats income and growth differently: income is taxed every
year, growth only when sold. So each quarter a ticker pays out a fraction $y_a/4$ of its price as a distribution and
its price falls by the same amount, leaving the total return unchanged. $y_a$ is the ticker's historical cash
distribution rate, averaged over complete calendar years:

| Ticker | Income rate $y_a$ a year |
| --- | ---: |
[[yields]]

Outside super the distribution arrives as cash and is taxed at your marginal rate. Inside super it is reinvested
after 15% fund tax (nothing in the pension phase). No franking credits are assumed, because the sources are US funds
and indices. A higher $y_a$ means more tax paid along the way and less deferred.

#### Pay, tax withheld and saving

- **Salary** in financial year $m$ after the start is $\text{salary}_0\,(1+g)^m$, with $g$ = [[wage]], paid in 26
  fortnights until the retirement date. Salary sacrifice grows with it.
- **Tax withheld** each payday is 1/26 of the income tax on a full year of that salary alone. The 30 June assessment
  settles the rest (investment income, capital gains, part years) on 31 October, as a payment or a refund.
- **Super guarantee** is [[sg]] of pay up to the maximum contribution base.
- **Saving outside super:** each trading day the ledger invests [[saving]], buying a new parcel at the outside-super
  weights. The cash buffer is [[buffer]]. From the retirement date all cash above the buffer is always reinvested,
  including pension payments not yet spent.

#### Paying for something

Spending, tax and required repayments are each paid from the first source that has money:

1. cash;
2. extra repayments drawn back from the home loan (spending, tax and the home's costs only);
3. sales of outside investments, in proportion to each ticker's value;
4. a lump sum from super accumulation, once super is accessible;
5. an extra payment from the account-based pension.

Anything still unpaid is a **shortfall**. Preserved super cannot be touched, so a path can record a shortfall while
its total wealth is still positive: the gap between retiring and reaching super.

**Which parcels are sold.** Within a ticker, parcels are sold in ascending order of taxable gain per dollar of
proceeds,

$$
k = \frac{\text{taxable gain if the whole parcel were sold today}}{\text{its value today}}
$$

so losses go first, then high-cost parcels, and a gain that qualifies for the 50% discount counts at half. The tax
office allows this choice when records identify the units sold. The choice is made sale by sale; the model does not
plan sales across years or sell to harvest losses.

#### Super accounts

- **Accumulation** receives contributions and pays 15% tax on its income and realised gains (*Tax and super*).
- **Access** starts at the later of the retirement date and preservation age ([[preservation]]), and at 65 in any
  case.
- **Account-based pension.** At the pension start the balance moves across, up to the transfer balance cap; anything
  above the cap stays in accumulation. Pension earnings are untaxed.
- **Minimum payment.** Each 1 July the year's minimum is the balance times an age factor (4% under 65, 5% from 65,
  6% from 75, 7% from 80, 9% from 85, 11% from 90, 14% from 95), rounded to \$10. It is paid in equal monthly
  instalments into cash; cash above the buffer is then reinvested outside super.
"""

SPENDING = r"""
#### The spending schedule

Spending is entered in today's dollars and paid monthly. Its nominal growth is CPI compounded with the chosen real
change, $g_s = (1+c)(1+\delta) - 1$, with $c$ = [[cpi]] and $\delta$ = [[real_change]] here. In financial year $m$ after
the start the scheduled yearly amount is

$$
E_m = E_0\,(1+g_s)^m
$$

and each month pays $\phi\,E_m/12$. The factor $\phi$ is 1 until retirement; a strategy changes spending by changing
$\phi$. (Where a different retirement amount is entered, it replaces $E_0$ from the retirement date.) In this plan retirement spending starts at [[start_rule]], and the strategies run are: [[strategy_names]].

**Starting at a percentage.** With a starting rate $\rho_0$, on the first spending date on or after the retirement
date the ledger sets $\phi = \rho_0 S / E_m$, so yearly spending starts at $\rho_0$ times spendable wealth $S$ at the
previous close. Comparing strategies requires this start, so that every strategy begins from the same spending.

#### The yearly review

Each 1 July after retirement, with $S$ the spendable wealth at the 30 June close, $X = \phi E_m$ the amount planned for
the new year (which already includes the year's growth step), $X_{-1}$ last year's amount and $\rho = X/S$:

| Strategy | Rule |
| --- | --- |
| **Fixed** | No review. $X = \phi E_m$ whatever markets did |
| **% of wealth** | $X = \rho_0\,S$ |
| **Guyton–Klinger** | (1) If last year's market return was negative and $\rho > \rho_0$, skip this year's growth step: $X \leftarrow X/(1+g_s)$. (2) Then, with the new $\rho$: cut $X$ by $s$ if $\rho > \rho_0(1+b)$, or raise it by $s$ if $\rho < \rho_0(1-b)$. Here $b$ = [[band]], $s$ = [[step]] |
| **Vanguard** | Aim for $\rho_0 S$, but move at most a ceiling $u$ above or a floor $l$ below last year's amount after its growth step: $X = \min\big(\max(\rho_0 S,\ (1-l)(1+g_s)X_{-1}),\ (1+u)(1+g_s)X_{-1}\big)$. Here $u$ = [[ceiling]], $l$ = [[floor]] |

After any rule, $X$ is held between the minimum and maximum, if set (the minimum wins if they cross). Both are in
today's dollars and rise with CPI. This plan's bounds: [[bounds]].

Points that matter when reading results:

- **Wealth means spendable wealth** $S$: cash, outside investments and all super (including super not yet accessible)
  less any home loan. An investment property's equity is left out, because it is never sold.
- **"Last year's market return"** is the year's market gain in dollars across all accounts divided by $S$ at the start
  of the year. Contributions and withdrawals during the year are not adjusted for.
- **A rule sets the amount asked for.** What is actually paid can be less, when no accessible account has the money.
  Charts of spending show the amount paid.
- **Guyton–Klinger here is a simplified form** of Guyton and Klinger (2006). Their portfolio-management rule is not
  used, and the cut applies in every year (the original stops applying it in the last 15 years of a retirement).
- **The Vanguard rule** follows published descriptions of Vanguard's dynamic spending rule; the ceiling and floor apply
  to the change after the growth step, so with $\delta = 0$ they bound the yearly change in real spending.
- **Trade-off.** Fixed spending puts all market risk into wealth, and so into the chance of running out. The other
  rules move part of it into spending. A rule that spends less always ends with more, so compare risk, spending and
  ending wealth together (the Compare page).

*Reference: Guyton, J. T. and Klinger, W. J. (2006), Decision rules and maximum initial withdrawal rates, Journal of
Financial Planning, March 2006.*
"""

TAX = r"""
#### Personal income tax, assessed each 30 June

$$
\begin{aligned}
Y &= \max\big(0,\ \lfloor \text{assessable income} - \text{deductions} \rfloor\big) \\
\text{net tax} &= \max\big(0,\ T(Y) + T_{\min} - \text{offsets}\big) + \text{Medicare levy} + \text{surcharge}
\end{aligned}
$$

- **Assessable income:** salary after salary sacrifice, interest on cash, distributions from outside investments, the
  taxable part of any Age Pension, net rent and the net capital gain.
- **Deductions:** the standard work deduction (the lesser of \$1,000 and labour income), and a rental loss where the
  property's losses may offset other income.
- **$T(Y)$** is the marginal scale:

[[brackets]]

- **Offsets**, none refundable: the low income tax offset ([[lito]], tapering to nil at [[lito_out]]), the Working
  Australians Tax Offset from 2027-28 (\$250, an assumed amount within the legislated limit), and the seniors and
  pensioners offset from Age Pension age.
- **Medicare levy:** 2% of $Y$, phased in above [[medicare_lower]] at 10 cents in the dollar. The surcharge applies
  without private hospital cover.
- **Division 293:** a further 15% on concessional contributions, to the extent that $Y$ plus those contributions
  exceeds [[division_293]].
- $T_{\min}$ is the minimum tax on capital gains, below.

#### Capital gains outside super

Every purchase outside super is its own parcel with a cost base $b$. Selling value $v$ of it realises:

| Sale | Taxable gain |
| --- | --- |
| Before 1 July 2027 | $v - b$, halved if the parcel was held more than 12 months |
| From 1 July 2027, parcel bought earlier | A deferred gain $v^* - b$, still halved after 12 months, plus a post-reform gain $v - v^* I$ |
| From 1 July 2027, parcel bought later | A post-reform gain $v - b\,I$ |

$v^*$ is the parcel's value at the close of 30 June 2027, recorded by the ledger on that day. $I = (1+c)^{q/4}$,
rounded to three decimals, indexes the cost for $q$ quarters of the assumed CPI; it applies only after 12 months and
cannot create a loss. Post-reform gains get no discount, and with $G$ the post-reform gains left after losses they
carry a minimum tax,

$$
T_{\min} = \max\Big(0,\ \big\lfloor 0.30\,G - \big(T(Y) - T(Y - G)\big) \big\rfloor\Big),
$$

so that those gains bear at least 30%. It does not apply in a year in which any Age Pension is received. Losses are
applied first (to deferred gains before post-reform gains, as the amended law orders them) and unused losses carry
forward. These are the 2026 capital gains reforms as recorded in the project's rule register.

Sales happen for only two reasons: to pay for something when cash runs out, and the January rebalance. A rebalance
outside super is therefore a taxable event every year; inside super it is an untaxed switch.

#### Super

| Step | Rule in the model |
| --- | --- |
| Contributions | Super guarantee plus salary sacrifice. The fund deducts 15% on receipt |
| Concessional cap | [[cap]] in [[first_fy]], plus unused cap from the previous five years while total super is under \$500,000. A plan that would exceed the cap stops with an error; excess contributions are not modelled |
| Earnings, accumulation | Tax of $0.15 \times \big(\text{distributions} + \tfrac{2}{3}\,G^{\text{fund}}\big)$ a year |
| Earnings, pension | Untaxed |
| Withdrawals | Tax-free from age 60; earlier access is not modelled |
| Transfer balance cap | [[transfer_cap]] in [[first_fy]]: the most that can move into the pension |

**The fund's realised gains.** A unit price does not show when a fund sells assets, so the tax on its capital gains
has to be assumed. Each 30 June the model realises a share $\theta$ = [[realised]] of each account's accumulated
unrealised gain:

$$
G^{\text{fund}} = \theta\,\max(0,\ V - B), \qquad B \leftarrow B + G^{\text{fund}},
$$

where $V$ is the account's value and $B$ its running cost base (purchases add to it, withdrawals reduce it pro rata).
In accumulation two-thirds of the gain is taxed at 15%, so 10% of the realised gain. $\theta = 0$ never taxes gains in
the fund, a lower bound on tax; $\theta = 1$ taxes each year's gain as it arises. The opening balance is taken to
carry no unrealised gain.

**Division 296** (large balances). With $B^*$ the larger of the total super balance at the start and end of the year
(the end balance alone in 2026-27), thresholds $\theta_1$ = [[large]] and $\theta_2$ = [[very_large]], and $E$ the year's super earnings,

$$
\text{tax} = 0.15\,E\,\max\Big(0,\ \frac{B^* - \theta_1}{B^*}\Big) + 0.10\,E\,\max\Big(0,\ \frac{B^* - \theta_2}{B^*}\Big).
$$

$E$ is the year's distributions in both super accounts plus the discounted realised gain, the gain scaled by a
transitional factor that rises from 0.2 in 2026-27 to 1 from 2030-31. The tax therefore depends directly on
$\theta$. It is paid out of super on the 30 September fifteen months after the year ends, an assumed date.

#### Carrying the rules into later years

The ledger needs a rule set for every financial year to [[last_fy]], and only [[first_fy]] has published amounts.
Later years apply the changes already legislated (the 14% first rate, the capital gains reform), then each rule's own
indexation method at the plan's CPI ([[cpi]]) and wage growth ([[wage]]). Where the law has no indexation the amount
stays fixed in dollars:

[[projection]]

**Fixed brackets** are the projection choice with the largest effect over a long run. Income tax thresholds are not
indexed in law; Parliament changes them from time to time. The model does not guess those changes, so over [[creep_years]] years the
thresholds fall to [[creep]] of their present value in today's dollars while incomes and prices rise. Tax late in a
long run is therefore heavier than under any realistic path of future budgets. The direction is cautious: it
understates late-life spending power for someone with taxable income. Super pension payments after 60 are tax-free,
so the effect falls mainly on salary and on income and gains outside super.

Indexed amounts compound from the [[first_fy]] value at the assumed rate and are rounded down to the law's step, so a
projected cap can differ from the eventual published one by a step even if the assumed growth is right.
"""

AGE_PENSION = r"""
#### The payment

From age 67 the single Age Pension is assessed every fortnight on the previous day's closing balances:

$$
\begin{aligned}
\text{assets reduction} &= \tau\,\max(0,\ \text{assessed assets} - \text{limit}) \\
\text{income reduction} &= 0.5\,\max(0,\ \text{deemed income} + \text{wages after the Work Bonus} + \text{net rent} - \text{free area}) \\
\text{payment} &= \max\big(0,\ \text{maximum} - \max(\text{assets reduction},\ \text{income reduction})\big)
\end{aligned}
$$

| Input, [[first_fy]] | Value |
| --- | --- |
| Maximum rate | [[pension_fortnight]] a fortnight ([[pension_year]] a year): basic rate, pension supplement and energy supplement |
| Assets limit for [[tenure]] | [[limit]] |
| Assets taper $\tau$ | [[taper_dollars]] a fortnight per \$1,000 over the limit |
| Deemed income | [[deeming_low]] a year on the first [[deeming_threshold]] of financial assets and [[deeming_high]] on the rest, whatever they earned |
| Income free area | [[free_area]] a fortnight |

- **Assessed assets** are everything in the ledger (cash, outside investments and all super, which counts from Age
  Pension age), plus the other assets entered in the plan ([[other_assets]], held constant), plus equity in an
  investment property. The home is exempt and a home loan is not deducted.
- **Financial assets** for deeming are the ledger's accounts.
- **Tax.** [[taxable_share]] of each payment is assessable income (the basic rate and the taxable part of the
  supplement, as a share of the maximum). For a part pension this share is an approximation; the law reduces the
  components in a set order.

**Reading the tapers.** The assets test removes [[taper]] a year of every dollar between the limit and the cut-off
(about [[cut_off]] for [[tenure]]). Over that range an extra dollar of savings earns its return less [[taper]] a
year, so the Age Pension partly insures wealth in that band against market falls. Deeming removes at most
[[income_taper]] a year of each extra dollar, so the assets test takes over soon after the limit is passed and sets
the cut-off.

#### Seniors and pensioners tax offset

From the income year in which Age Pension age is reached, whether or not any pension is paid:

$$
\text{offset} = \max\big(0,\ \lceil m - 0.125\,\max(0,\ \text{rebate income} - s) \rceil\big)
$$

with $m$ = [[sapto]] and $s$ = [[sapto_from]]; it is nil from [[sapto_out]]. It is not refundable, and a person entitled
to any of it uses higher Medicare low-income thresholds. These are the latest published amounts (2025-26), held
unchanged.

#### Later years

The basic rate grows with wages, the supplement with CPI, and the limits, free area and deeming threshold with CPI.
Wages are assumed to outgrow prices by [[real_wage]] a year, so the full pension rises in today's dollars, from
[[pension_year]] a year to [[pension_last]] by [[last_fy]], while the asset limits stay level. The Age Pension
therefore matters more late in a long run than a constant-dollar reading would suggest.

#### Simplifications

- **One single person** at normal rates. No couple rates, Rent Assistance, concession cards or gifting rules.
- **Daily revaluation.** Assets are assessed at the previous close every fortnight. Centrelink revalues investments
  periodically, so real payments respond to markets with a lag.
- **One rate per financial year.** The law indexes rates on 20 March and 20 September; the model applies the
  September 2026 values from 1 July.
- **Claimed on time**, with the residence rules met.
- **Outcome tiers** (Outcomes page). A path that never ran out is on the *full Age Pension* if any financial year paid
  at least 95% of 26 maximum fortnights, on a *part Age Pension* if it was paid less, and *self-funded* if it was
  paid none. The 95% allows for the first fortnights after a threshold moves.
"""

PROPERTY = r"""
[[holdings]]

Property is the least developed part of the model. Loans and cash flows are accounted for exactly, but property
**values grow at a fixed rate on every market path**: there is no property risk and no link between property and
investment markets.

#### Loans

A loan of balance $B$ at yearly rate $i$ with $n$ fortnights left has the required repayment

$$
P = \frac{B\,r}{1 - (1+r)^{-n}}, \qquad r = \frac{i}{26},
$$

fixed in dollars. Interest accrues every calendar day at $B\,i/365$ and is added to the balance at each month end; a
repayment clears accrued interest first. The rate is fixed for the whole run and has no link to the market paths.

- **Home loan.** Its repayment is paid before spending. A chosen share of whatever would be invested outside super
  pays the loan down instead; those extra repayments can be drawn back to pay spending or tax before any investment
  is sold. Interest is not deductible. Total and spendable wealth are net of the loan.
- **Investment loan.** It can have interest-only years, during which each repayment is $B\,i/26$. It has no redraw.

A missed repayment is a shortfall and stays on the loan.

#### The home

With a value entered, running costs of [[home_costs]] of the value a year are paid monthly before spending, so a
spending strategy never cuts them, and the value grows at [[home_growth]] a year. The home is in **no** wealth total
and is exempt from the Age Pension assets test. A renter's rent is paid the same way and rises with CPI.

#### An investment property

Each month, with weekly rent $w$, value $V$, running-cost rate $\kappa$ = [[property_costs]] and growth $\gamma$ =
[[property_growth]]:

$$
\text{rent} = \frac{52\,w}{12} \times 0.9 \times (1+c)^m, \qquad
\text{costs} = \frac{\kappa V}{12}, \qquad
V \leftarrow V\,(1+\gamma)^{1/12}
$$

The 0.9 allows for vacancy and management, and $m$ counts financial years since the start.

- **Tax.** Each year's result is rent less interest less running costs less any loss carried forward. A profit is
  taxed as income. In this plan a loss [[loss_rule]]. Depreciation is not modelled.
- **Never sold.** There is no sale, so no capital gains tax, and a path that runs short of money cannot draw on the
  property. Its equity counts in total wealth but not in spendable wealth, which is why spending strategies ignore it.
  The Paths page reports the equity a path held when its money ran out.
- **Age Pension.** Equity (value less the loan) is an assessed asset, and net rent is income on top of deemed income.
- **Moving in.** On a chosen date the property becomes the home: rent stops, its loan becomes the home loan, and its
  value stays in total wealth as a transfer, not a gain.
"""

RESULTS = r"""
#### Classifying a path

A path **ran out** if any of these holds:

- some spending, housing cost or required repayment could not be paid (a shortfall);
- some tax could not be paid;
- the tax already incurred but not yet due at the end date exceeds the money available to settle it.

Otherwise it is funded, and its Age Pension receipts place it in a tier (*Age Pension* tab). The share that ran out
is $\hat\pi = (\text{paths that ran out})/M$ over the years simulated only; nothing is said about later years.

A path that reaches a rule the model does not implement (an excess transfer balance, for example) is set aside as
**unsupported** and reported in the run notes. Percentiles then describe the remaining paths.

#### Percentiles and bands

- **Bands are pointwise.** A band's value on a date is that percentile of all paths' values on that date. No single
  path follows a band, and a band is not a confidence interval for a whole path.
- **Each figure is its own percentile.** The median of spending and the median of ending wealth generally come from
  different paths, and medians of components do not add up to the median of their sum. Charts that must add up (money
  in and out for a group of paths) use averages and say so.
- **Mostly-zero measures** (Age Pension received, shortfall) are reported as the share of paths above zero and the
  median among those paths.
- **Percentiles interpolate linearly** between ranked paths.
- **The path shown by default** is the one whose ending wealth is nearest the median ending wealth. Its earlier years
  need not be typical.

#### Measures

**Withdrawal rate**, for each full financial year of retirement, from nominal amounts:

$$
\text{rate}_y = \frac{\max\big(0,\ \text{spending} + \text{tax} + \text{housing and property costs and interest} - \text{Age Pension} - \text{rent}\big)_y}{S_{\text{1 July}}}
$$

It is the net draw on your own money over spendable wealth at the start of the year. Loan principal is left out: it
moves wealth between an asset and a loan.

**Average retired-year spending** is a path's spending actually paid, averaged over its full retired financial
years, so shortfalls lower it.

**Tax owed at the end.** Tax is paid after it is incurred, so wealth at the end date still carries tax: assessments
not yet due, Division 296 not yet released, and the final part-year's estimated tax. The headline ending wealth is
net of it.

**Largest fall in wealth** is $\min_d \big(A_d / \max_{s \le d} A_s - 1\big)$ in today's dollars, where $A_d$ is
total wealth plus any home loan and investment loan still owed (wealth before loans). Total wealth can start below
zero when a loan is larger than the savings, and a fall from a peak near zero is not a meaningful percentage. Without
a loan $A_d$ is total wealth. It includes spending, not only market falls.

#### Precision

The *Markets* tab gives the simulation error for this run's path counts and explains why the history itself is the
larger uncertainty.
"""

ASSUMPTIONS = r"""
The model's main simplifications, what this plan uses, and which way each pushes the results. "Flatters" means results
look better than a fuller model would give; "cautious" the reverse. The directions are judgements, not measurements.

#### Markets

| Assumption | In this plan | Effect on results |
| --- | --- | --- |
| Future returns are drawn from the history's own returns | [[first]] to [[last]] | Sets the level of every result. The history's average return is carried forward in full, with no allowance for lower returns ahead |
| US-dollar returns are used as Australian-dollar returns | All tickers | Leaves out currency risk and any difference in average return from the exchange rate. Direction unclear |
| Nominal returns are deflated at a constant CPI | [[cpi]] | **Flatters** where the history includes high-inflation years: their nominal returns are deflated at only [[cpi]], so those stretches look better in real terms than they were |
| Dependence beyond the block length is lost | Mean block [[length]] days | Changes the long-run spread; direction unclear (*Markets*) |
| Leveraged and long-history tickers are modelled before their funds existed | Per ticker | Results inherit those reconstructions |
| No trading costs or spreads; fund fees are those already in the returns | | Flatters slightly |

#### Economy and rules

| Assumption | In this plan | Effect on results |
| --- | --- | --- |
| Inflation and wage growth are constant | [[cpi]] and [[wage]] | Understates the spread: no inflation shocks, and no link between inflation and markets |
| Interest on cash is constant | [[cash_interest]] | Small |
| Today's law continues, indexed by its own rules | To [[last_fy]] | Leaves out legislative change, in either direction |
| Income tax thresholds stay fixed in dollars | [[creep]] of today's real value by [[last_fy]] | **Cautious:** overstates tax late in the run |
| Each ticker's income is its historical cash distribution rate; no franking credits | See *Daily ledger* | Sets how much tax is paid yearly instead of deferred |
| The super fund realises a fixed share of its unrealised gains each year | [[realised]] | A higher share means more fund tax and more Division 296 |
| The opening outside balance is one parcel per ticker with one cost base and date | | Blurs the tax on early sales |
| The lowest-tax parcels are sold first | | Flatters relative to selling oldest first; needs parcel records |

#### Household

| Assumption | In this plan | Effect on results |
| --- | --- | --- |
| One person, taxed and means-tested as single | | A couple's tax, super caps and Age Pension differ materially |
| Work stops for good at the retirement age | | No part-time income, redundancy or early forced retirement |
| Spending follows the strategy exactly | [[strategy_names]] | No health or aged-care shocks, and no cutting back in a crisis under fixed spending |
| Every path runs to one end date | Age [[age_end]] | "Ran out" covers only the years simulated; no weighting by survival |
| The Age Pension is claimed on time and reassessed every fortnight on market values | | Real payments lag markets |
| Property values grow at a fixed rate and property is never sold | [[property_growth]] a year | Understates the spread of total wealth; a path short of money cannot use the equity |
"""


def _markdown(text, values):
    st.markdown(fill(text, values))


def page(run):
    plan = run.plan
    strategies = run.strategies or {run.rule: run}
    page_title("Method", "What the model is, the equations behind the results and the assumptions they rest on. Figures "
                         "in the text are this run's own.")
    values = facts(run)
    tabs = st.tabs(["Overview", "Markets", "Daily ledger", "Spending strategies", "Tax and super", "Age Pension",
                    "Property and loans", "Reading results", "Assumptions"])
    with tabs[0]:
        left, right = st.columns([1.25, 1], gap="medium")
        with left, card("overview"):
            _markdown(OVERVIEW, values)
        with right, card("dollars"):
            _markdown(DOLLARS, values)
    for tab, name, text in zip(tabs[1:], ("markets", "ledger", "spending", "tax", "agepension", "property", "results",
                                          "assumptions"),
                               (MARKETS, LEDGER, SPENDING, TAX, AGE_PENSION, PROPERTY, RESULTS, ASSUMPTIONS)):
        with tab, card(name):
            _markdown(text, values)
            if name == "tax":
                rules = projected_rules(plan, list(run.rules_manifest)[-1])
                with st.expander("Every assumed or projected rule value", icon=":material/gavel:"):
                    st.caption("Rule values that are not published law for their year: *assumed* (not yet set, or set "
                               "by Parliament each year, so held at the latest value) or *projected* (indexed by the "
                               "law's own method at the plan's CPI and wage growth). Everything else in the rule sets "
                               "is enacted law or the tax office's published indexed amount.")
                    st.markdown(markdown_table(assumed_parameters(rules)))
    if run.folder:
        nested = len(strategies) > 1
        with card("files"):
            st.subheader("Saved files")
            st.markdown(f"The plan, path summaries, the median path's daily ledger, a manifest and PNG review plots are in "
                        f"`{run.folder}`" + (", with each strategy's own files in `strategies/`." if nested else ".")
                        + " The full, sourced methodology and the decision records are in the project's "
                          "`docs/methodology` and `docs/decisions` folders.")
            with st.expander("PNG review plots", icon=":material/image:"):
                shared = ("portfolio_history.png", "portfolio_future.png", "portfolio_distributions.png") + \
                    (("comparison_wealth.png", "comparison_spending.png") if nested else ())
                files = [(run.folder / name, "") for name in shared]
                for rule in strategies:
                    own = run.folder / "strategies" / rule if nested else run.folder
                    files += [(own / name, f"{STRATEGY_NAMES[rule]}: " if nested else "")
                              for name in ("retirement_outcomes.png", "retirement_range.png", "retirement_markets.png",
                                           "retirement_flows.png", "ledger.png")]
                for file, prefix in files:
                    if file.exists():
                        st.image(str(file), caption=prefix + file.name.replace("_", " ").replace(".png", ""))
