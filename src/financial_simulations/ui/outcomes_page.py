"""The Outcomes page: how the paths fared, with ruin, Age Pension reliance and retirement spending up front."""

from datetime import date

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from financial_simulations.reporting.palette import BLUE, FLOW_COLOURS, INK, MAGENTA, TIER_COLOURS, YELLOW
from financial_simulations.retirement.outcomes import FULL_RATE_SHARE, TIERS, ending_percentiles, group_spending, tier_shares
from financial_simulations.retirement.strategy_results import STRATEGY_NAMES
from financial_simulations.rules.au.superannuation import age_on
from financial_simulations.ui import charts
from financial_simulations.ui.results import derived, header, kept_tabs, strategy_text
from financial_simulations.ui.state import (affected, compact, dollars, fit, key, money_column, percent_column,
                                            percentile_table, plural, result_key, share, sticky, sticky_choice)
from financial_simulations.ui.theme import MEDIUM, card, chart_title, draw, explain, legend, tier_headline


SHORT_HORIZON_AGE = 90  # ledger horizons ending before this age get a warning that ruin can come later
TIER_NOTES = {TIERS[0]: "Paid for everything and never drew the Age Pension.",
              TIERS[1]: "Never ran out, but wealth fell far enough to draw some Age Pension.",
              TIERS[2]: "Never ran out, but fell to the full Age Pension: close to ruin.",
              TIERS[3]: "Could not pay all spending or tax at some point."}
TABS = ("Wealth", "Risk over time", "Spending", "Age Pension", "Money in and out", "Tables")


def page(run):
    run = header(run, "Outcomes", None)
    d = derived(run)
    outcomes, plan = d.outcomes, run.plan
    paths = run.retirement_paths
    unsupported = int((paths["Status"] == "unsupported").sum())
    st.caption(f"{plural(len(outcomes), 'market path')} through the daily tax ledger, {d.start:%d %B %Y} to "
               f"{d.end:%d %B %Y} (age {d.end_age}). All amounts are in today's dollars."
               + (f" Strategy: {STRATEGY_NAMES[run.rule]}." if len(run.strategies or {}) > 1 else ""))
    for note in run.notes:
        st.warning(note)
    if unsupported:
        reasons = paths.loc[paths["Status"] == "unsupported", "Reason"].value_counts()
        st.warning(f"{plural(unsupported, 'path')} reached a rule this model does not support and are left out, so the "
                   "shares below are conditional on the others: "
                   + "; ".join(f"{count} × {reason}" for reason, count in reasons.items()))
    headline(run, d)
    tabs = kept_tabs(result_key(run, "outcome_tabs"), list(TABS))
    bodies = (wealth_tab, risk_tab, spending_tab, age_pension_tab, flows_tab, tables_tab)
    for tab, body in zip(tabs, bodies):
        if tab.open:
            with tab:
                body(run)


def headline(run, d):
    outcomes, plan = d.outcomes, run.plan
    shares = tier_shares(outcomes)
    counts = {tier: int((outcomes["Outcome"] == tier).sum()) for tier in TIERS}
    with card("headline"):
        chart_title("Will the money last?",
                    f"Every path, by the worst it reached before {d.end:%B %Y} (age {d.end_age}).")
        tier_headline(shares, counts, TIER_NOTES)
    if d.end_age < SHORT_HORIZON_AGE:
        st.warning(f"The simulation stops at age {d.end_age}, so these shares cover only the years to {d.end.year}: money "
                   f"can still run out later"
                   + (", and the Age Pension (from 67) is not reached" if d.pension_from > d.end else "")
                   + f". Raise *Years to simulate* (Plan, Assumptions) to run to age {SHORT_HORIZON_AGE} or beyond.")
    spending = outcomes["Average retired-year spending"].dropna()
    a, b, c, e = st.columns(4)
    a.metric("Average spending per retired year", compact(float(spending.median())) if len(spending) else "–",
             help="Each path's spending actually paid, averaged over its full retired financial years; this is the median "
                  "path. " + (f"One path in ten averaged less than {compact(float(spending.quantile(0.1)))}." if len(spending)
                              else "Retirement starts after the horizon."))
    b.metric("Median wealth at retirement", compact(outcomes["Wealth at retirement"].median()),
             help="Total wealth on your retirement date: cash, outside investments and super.")
    c.metric("Median ending wealth", compact(outcomes["Ending wealth after tax owed"].median()),
             help=f"At the horizon, less tax already incurred but not yet paid. Before that tax the median is "
                  f"{compact(outcomes['Ending wealth'].median())}.")
    e.metric("Bad case: ending wealth", compact(float(outcomes["Ending wealth after tax owed"].quantile(0.05))),
             help="The 5th percentile: one path in twenty ended lower than this.")
    with st.expander(f"Your plan in brief: {STRATEGY_NAMES[run.rule]} spending", icon=":material/description:"):
        st.markdown(strategy_text(plan))


@st.fragment
def wealth_tab(run):
    d = derived(run)
    outcomes = d.outcomes
    present = [tier for tier in TIERS if (outcomes["Outcome"] == tier).any()]
    with card("allpaths"):
        chart_title("Every path's wealth", "Total wealth at each month end. Pick the outcomes to draw; point at a line "
                                           "for that path's details.")
        left, right = st.columns([4, 1], vertical_alignment="center")
        with left:
            widget = sticky(result_key(run, "paths_shown"), present)
            st.session_state[widget] = [t for t in st.session_state[widget] if t in present]
            shown = st.pills("Outcomes to draw", present, selection_mode="multi", key=widget, label_visibility="collapsed")
        with right:
            log = st.toggle("Log scale", key=sticky(result_key(run, "all_paths_log"), True))
        chart, drawn, clipped = charts.all_paths_chart(run.wealth_paths, d.marks, outcomes, shown=tuple(shown),
                                                       cache_key=id(run), log=log)
        totals = outcomes["Outcome"].value_counts()
        legend([*[(f"{tier}: {drawn[tier]:,}" + (f" of {totals[tier]:,}" if drawn[tier] < totals[tier] else "") + " drawn",
                   "#6e6e6e" if tier == TIERS[0] else TIER_COLOURS[tier], "line") for tier in drawn],
                (f"Median of all {len(outcomes):,} paths", BLUE, "line")])
        draw(chart)
        explain(("Every calculated path is drawn. " if sum(drawn.values()) == len(outcomes) and len(shown) == len(present) else
                 "Every path that ran out or reached the full Age Pension is drawn. The others are a sample spread "
                 "evenly from the lowest to the highest ending wealth, so they show the same spread as all of them. ")
                + ((f"The {clipped} highest paths run" if clipped != 1 else "The highest path runs")
                   + " off the top: the linear axis stops there so the band where most paths sit stays readable. "
                   if clipped else "")
                + "Self-funded paths are translucent grey, so the grey darkens where most paths went. A coloured dot "
                  "marks the month a path first received the Age Pension, and a cross where a path first could not pay "
                  "spending or tax. A cross can sit well above \\$0, because total wealth includes super that was not "
                  "yet accessible: those paths ran out of outside money while waiting for super. The blue line is the "
                  "median of all paths at each month; no single path follows it. Point at a line to highlight that path "
                  "and see its outcome, ending wealth, average retirement spending and Age Pension; open its number on "
                  "the Paths page for the full ledger. Drag to pan, Shift+scroll to zoom, double-click to reset.")
    with card("bands"):
        names = list(dict.fromkeys(run.account_bands["Series"]))
        chart_title("Range of outcomes", "Median, middle half and 90% of paths at each month end.")
        left, right = st.columns([4, 1], vertical_alignment="center")
        with left:
            choice = st.segmented_control("Account", names, required=True, label_visibility="collapsed",
                                          key=sticky_choice(result_key(run, "wealth_series"), names, names[0]))
        with right:
            wide = st.toggle("Log scale", key=sticky(result_key(run, "wealth_bands_log"), True))
        bands = run.account_bands.loc[run.account_bands["Series"] == choice]
        draw(charts.band_chart(bands, f"{choice}, today's dollars" + (" · log scale" if wide else ""), symlog=wide,
                               marks=d.marks))
        explain("Dark band: the middle half of paths (25th to 75th percentile). Light band: 90% of paths (5th to 95th). "
                "Line: the median. The bands are worked out month by month, so no single path follows them. "
                + ("The axis is logarithmic above \\$1,000 and linear below, so \\$0 can be shown and a very high upper "
                   "tail does not flatten the median. " if wide else "")
                + "Total wealth includes super that may not yet be accessible.")


def ruin_metrics(run, d):
    """Risk of ruin and the measures around it."""
    outcomes = d.outcomes
    total = len(outcomes)
    depleted = outcomes.loc[outcomes["Status"] == "depleted"]
    access = d.marks.loc[d.marks["Event"].str.contains("Super accessible"), "Date"] if len(d.marks) else pd.Series(dtype="datetime64[ns]")
    first = pd.to_datetime(depleted["First shortfall"].replace("", None)).dropna()
    early = (first < access.iloc[0]).sum() if len(access) else 0
    ages = [age_on(d.born, day.date()) for day in first]
    start = d.start_wealth
    a, b, c, e = st.columns(4)
    a.metric(f"Risk of ruin to {d.end.year}", share(len(depleted) / total),
             help=f"Share of the {total} paths where some spending or tax could not be paid before {d.end}, or where "
                  "the tax owed at the horizon exceeds the money available to settle it.")
    b.metric("Ruin or full Age Pension", share(float(outcomes["Outcome"].isin(TIERS[2:]).mean())),
             help="Paths that ran out, plus paths that never ran out but fell far enough to be paid the full Age "
                  "Pension in at least one year: ruin and near ruin together.")
    c.metric("Median age money first ran short", f"{int(np.median(ages))}" if ages else "–",
             help="Among paths that ran short, the median age at the first unpaid spending.")
    e.metric("Ran short before super was accessible", share(early / total),
             help="Paths whose first shortfall came before super could be withdrawn: outside money alone was not "
                  "enough to bridge to the access date.")
    a, b, c, e = st.columns(4)
    a.metric("Outside money ever ran out", share(float((outcomes["Outside money runs out"] != "").mean())),
             help="Share of paths where cash and outside investments reached zero at some point (super may still "
                  "have been available).")
    b.metric("Ended with less than you started", share(float((outcomes["Ending wealth"] < start).mean())),
             help=f"Share of paths whose ending wealth was below the starting {compact(start)}.")
    c.metric("Ended below half of the start", share(float((outcomes["Ending wealth"] < 0.5 * start).mean())))
    e.metric("Median largest fall in wealth", share(float(outcomes["Largest fall in wealth"].median())),
             help="Each path's deepest fall of total wealth below its previous high; the median across paths. Unlike a "
                  "portfolio drawdown it includes spending, so it keeps falling in retirement even in flat markets.")


def tier_table(d):
    """One row per outcome tier: how many paths, and what those paths looked like."""
    outcomes, rows = d.outcomes, []
    for tier in TIERS:
        part = outcomes.loc[outcomes["Outcome"] == tier]
        if part.empty:
            continue
        first = pd.to_datetime(part["Age Pension first paid"].replace("", None)).dropna()
        ages = [age_on(d.born, day.date()) for day in first]
        years = part.loc[part["Age Pension years"] > 0, "Age Pension years"]
        rows.append({"Outcome": tier, "Paths": len(part), "Share of paths": 100 * len(part) / len(outcomes),
                     "Wealth at retirement": float(part["Wealth at retirement"].median()),
                     "Ending wealth": float(part["Ending wealth"].median()),
                     "Average retired-year spending": float(part["Average retired-year spending"].median()),
                     "Age Pension starts at age": float(np.median(ages)) if ages else None,
                     "Years on Age Pension": float(years.median()) if len(years) else None,
                     "Age Pension share of spending": 100 * float(part["Age Pension share of retired spending"].median())})
    return pd.DataFrame(rows)


@st.fragment
def risk_tab(run):
    d = derived(run)
    ruin_metrics(run, d)
    with card("states"):
        chart_title("Where the paths stand each year",
                    "The share of paths in each state in each financial year. The coloured area is the trouble: it "
                    "grows as paths fall onto the Age Pension or run short.")
        legend([(tier, TIER_COLOURS[tier]) for tier in reversed(TIERS)])
        draw(charts.states_chart(d.shares, d.marks))
        explain(f"Each path is in one state each financial year. **Ran out** holds from the first year with unpaid "
                f"spending onward, even if the path later recovers (for example once super becomes accessible). **Full "
                f"Age Pension** is a year paid at least {FULL_RATE_SHARE:.0%} of the maximum single rate, which happens "
                "only when assets are under the full-pension limit (about \\$333,000 for a homeowner today). **Part Age "
                "Pension** is any smaller amount, paid once assets fall below the cut-off (about \\$746,000 for a "
                "homeowner today). **Self-funded** years receive none, including every year before Age Pension age. A "
                "path can move back up: a market recovery can end a part pension. The headline tiles count each path "
                "once, by the worst state it ever reached, so they are at least as large as the final year here.")
    with card("tiers"):
        chart_title("What each outcome looked like", "Medians across the paths in each outcome; today's dollars.")
        table = tier_table(d)
        st.dataframe(table, hide_index=True, width="stretch", height=fit(table), column_config={
            "Paths": st.column_config.NumberColumn(format="%d"),
            "Share of paths": percent_column("Share of paths"),
            "Wealth at retirement": money_column("Wealth at retirement"), "Ending wealth": money_column("Ending wealth"),
            "Average retired-year spending": money_column("Average retired-year spending",
                                                          "Spending paid, averaged over the path's full retired years."),
            "Age Pension starts at age": st.column_config.NumberColumn(format="%.0f", help="Median age at the first payment."),
            "Years on Age Pension": st.column_config.NumberColumn(format="%.0f", help="Median number of financial years with any Age Pension."),
            "Age Pension share of spending": percent_column("Age Pension share of spending",
                                                            "Age Pension received over spending paid, across the path's "
                                                            "full retired years.", 0)})


@st.fragment
def spending_tab(run):
    d = derived(run)
    plan, outcomes, annual = run.plan, d.outcomes, d.annual
    spending = plan["spending"]
    starts = outcomes["Starting retirement spending"].dropna()
    if starts.empty:
        st.info("Retirement starts after the horizon, so there is no retirement spending to show.")
        return
    average = outcomes["Average retired-year spending"].dropna()
    lowest = outcomes["Lowest retired-year spending"].dropna()
    rates = outcomes["Starting withdrawal rate"].dropna()
    a, b, c, e = st.columns(4)
    a.metric("Starting spending (median)" if spending["retirement"] == "percent" else "Starting spending",
             compact(float(starts.median())),
             help=(f"{spending['retirement_percent']:.1%} of each path's total wealth on your retirement date. 5th to 95th "
                   f"percentile: {compact(float(starts.quantile(0.05)))} to {compact(float(starts.quantile(0.95)))}."
                   if spending["retirement"] == "percent" else
                   "Your first retired-year spending (the same on every path). As a share of wealth at retirement it is "
                   f"{share(float(rates.median()))} on the median path, and between {share(float(rates.quantile(0.05)))} "
                   f"and {share(float(rates.quantile(0.95)))} on 90% of paths."))
    b.metric("Average per retired year (median path)", compact(float(average.median())) if len(average) else "–",
             help="Each path's spending actually paid, averaged over its full retired financial years. 10th to 90th "
                  f"percentile: {compact(float(average.quantile(0.1)))} to {compact(float(average.quantile(0.9)))}."
                  if len(average) else None)
    c.metric("Paths that ever spent less than the start", share(float((outcomes["Years below start"] > 0).mean())),
             help="Share of paths with at least one full retired year in which spending paid was more than 1% below "
                  "the starting amount: a cut by the rule, or money running short.")
    e.metric("Bad case: lowest year's spending", compact(float(lowest.quantile(0.05))) if len(lowest) else "–",
             help="The 5th percentile, across paths, of each path's lowest full retired year of spending paid. One path "
                  "in twenty had a year at or below this.")
    groups = group_spending(outcomes, d.groups)
    if len(groups):
        with card("groupspend"):
            chart_title("Average spending in retirement, by group of paths",
                        "Dot: the group's median path. Bar: its 10th to 90th percentile. The number after each name is "
                        "the paths in the group.")
            draw(charts.group_spending_chart(groups))
            shown = groups.drop(columns="Kind").assign(Share=groups["Share"] * 100)
            with st.expander("The same figures as a table", icon=":material/table:"):
                st.dataframe(shown, hide_index=True, width="stretch", height=fit(shown), column_config={
                    "Paths": st.column_config.NumberColumn(format="%d"), "Share": percent_column("Share of paths"),
                    **{c: money_column(c) for c in ("Median", "P10", "P90", "Lowest year (median)", "Ending wealth (median)")},
                    "Median": money_column("Average spending: median path"), "P10": money_column("10th percentile"),
                    "P90": money_column("90th percentile")})
            explain("A path's average is its spending **actually paid**, in today's dollars, averaged over its full "
                    "retired financial years, so a shortfall or a cut by the spending rule lowers it. The outcome groups "
                    "are the headline tiles. The ending-wealth groups rank paths by wealth at the horizon; with a "
                    "market-responsive strategy the paths that end poorest are also the ones that spent least, while "
                    "with fixed spending every funded path spends the same and only the paths that ran short differ. "
                    "Pick any group or single path on the Paths page to see it year by year.")
    rows = annual.loc[annual["Full retired year"] & (annual["Spending paid"] > 0)]
    if not rows.empty:
        with card("spendbands"):
            chart_title("Spending paid in each retired year", "Median, middle half and 90% of paths.")
            draw(charts.band_chart(charts.quantile_bands(rows, "FY ending", "Spending paid"),
                                   "Spending paid per year, today's dollars", color=MAGENTA, x="FY ending:Q", marks=d.marks))
            explain("With fixed spending the band is flat until money runs short, and then it drops. With a "
                    "market-responsive rule the band widens as spending follows each path's markets: the rule trades a "
                    "lower risk of running out for spending that varies. Judge a rule on both: the outcomes above, and "
                    "how low spending goes here.")
    retired = annual.loc[annual["Full retired year"] & annual["Withdrawal rate"].notna()]
    if not retired.empty:
        with card("rates"):
            chart_title("Withdrawal rate in each retired year",
                        "Spending and tax paid, less Age Pension, over total wealth on 1 July.")
            draw(charts.band_chart(charts.quantile_bands(retired, "FY ending", "Withdrawal rate"), "Withdrawal rate",
                                   percent=True, color=MAGENTA, x="FY ending:Q", marks=d.marks))
            explain(f"""
**What it is.** For each financial year that starts after you retire, the money taken out of your wealth that year
(spending paid plus personal and Division 296 tax paid, less any Age Pension received) divided by your **total**
wealth on that 1 July, outside and inside super together. A rate of 5% means that year used 5% of what you had at
its start.

**How to use it.** A rate that stays roughly flat means wealth is keeping pace with spending; a rate that climbs
year after year means wealth is shrinking relative to spending, which is the warning sign. Watch the upper band
most: those are the paths where markets went badly.

**Limits.** Tax paid includes tax on investment income and capital gains; super that is not yet accessible counts in
total wealth; spending rises with inflation{"" if not plan['spending']['real_change'] else f" and {plan['spending']['real_change']:+.1%} a year in real terms"}.
""")


@st.fragment
def age_pension_tab(run):
    d = derived(run)
    outcomes, annual = d.outcomes, d.annual
    end_year = int(annual["FY ending"].max()) if len(annual) else 0
    if not len(annual) or d.pension_from > date(end_year, 6, 30):
        st.info(f"You reach Age Pension age on {d.pension_from:%d %B %Y}, after the horizon. Raise *Years to simulate* "
                "(Plan, Assumptions) to run past it.")
        return
    received = outcomes["Age Pension received"] > 0
    first = pd.to_datetime(outcomes.loc[received, "Age Pension first paid"])
    ages = [age_on(d.born, day.date()) for day in first]
    years = annual.loc[annual["FY ending"] > d.pension_from.year + (d.pension_from.month >= 7)]
    paid_years = years.loc[years["Age Pension"] > 0, "Age Pension"]
    full_now = float(d.full_rate.iloc[0]) if len(d.full_rate) else float("nan")
    a, b, c, e = st.columns(4)
    a.metric("Paths that receive any Age Pension", share(float(received.mean())),
             help="Share of paths paid at least one fortnight of Age Pension before the horizon, including paths that "
                  "also ran out.")
    b.metric("Paths that reach the full rate", share(float((outcomes["Full Age Pension years"] > 0).mean())),
             help=f"Share of paths with at least one financial year paid {FULL_RATE_SHARE:.0%} or more of the maximum "
                  "single rate, including paths that also ran out.")
    c.metric("Median age it starts", f"{int(np.median(ages))}" if ages else "–",
             help="Among paths that receive it, the median age at the first payment. Later than 67 means the assets "
                  "or income test paid nothing until wealth fell.")
    e.metric("Typical year's Age Pension", compact(float(paid_years.median())) if len(paid_years) else "–",
             help="Median Age Pension in the years it is paid. The full single rate is about "
                  f"{compact(full_now)} a year now.")
    paid = years.loc[years["Age Pension"] > 0]
    if len(paid):
        with card("apbands"):
            chart_title("Age Pension paid each year, among the paths receiving it",
                        "Median, middle half and 90% of the paths paid any Age Pension that year. Dashed line: the full "
                        "single rate.")
            bands = charts.quantile_bands(paid, "FY ending", "Age Pension")
            full = d.full_rate.rename_axis("FY ending").reset_index(name="Full rate")
            full = full.loc[full["FY ending"].between(bands["FY ending"].min(), bands["FY ending"].max())]
            full["Period"] = full["FY ending"].map(charts.period_label)
            line = alt.Chart(full).mark_line(color=INK, strokeDash=[5, 3], strokeWidth=1.5).encode(
                x="FY ending:Q", y="Full rate:Q",
                tooltip=[alt.Tooltip("Period:N", title="Year"),
                         alt.Tooltip("Full rate:Q", title="Full single rate for the year", format="$,.0f")])
            draw(alt.layer(charts.band_chart(bands, "Age Pension per year, today's dollars", color=YELLOW, x="FY ending:Q"),
                           line))
            explain("Only the paths paid some Age Pension in a year are counted in that year's bands; the *Risk over "
                    "time* tab shows how many that is. The full rate rises in today's dollars because its basic rate "
                    "is indexed to wages, which are assumed to grow faster than prices; a year can pay slightly more "
                    "than the line when it has 27 pension paydays. "
                    "The Age Pension rises as your own wealth falls: on paths where markets did badly it pays more, "
                    "which cushions late retirement. Paths with large balances get none until their assets fall below "
                    "the assets-test cut-off (about \\$746,000 for a homeowner today), and the full rate needs assets "
                    "under about \\$333,000. Rules follow Services Australia's single rates, assets and income tests and "
                    "deeming; see the methodology for what is approximated.")
    on_pension = outcomes.loc[received & (outcomes["Status"] != "depleted")]
    if len(on_pension):
        with card("apwho"):
            chart_title("The paths that lived on the Age Pension without running out",
                        f"{plural(len(on_pension), 'path')}: funded throughout, but low enough to be paid.")
            a, b, c, e = st.columns(4)
            a.metric("Median ending wealth", compact(float(on_pension["Ending wealth"].median())))
            b.metric("Median years on Age Pension", f"{on_pension['Age Pension years'].median():.0f}")
            c.metric("Median total received", compact(float(on_pension["Age Pension received"].median())))
            e.metric("Share of their retirement spending",
                     share(float(on_pension["Age Pension share of retired spending"].median()), 0),
                     help="Age Pension received over spending paid across each path's full retired years; the median.")


@st.fragment
def flows_tab(run):
    """Median money in and out each year across every calculated path, with the net change's middle half."""
    d = derived(run)
    annual, outcomes = d.annual.copy(), d.outcomes
    columns = [c for c in annual.columns if c.startswith("Flow: ")]
    if not columns:
        return
    a, b, c, e = st.columns(4)
    a.metric("Wealth at start", compact(d.start_wealth), help="The same on every path: your wealth today.")
    b.metric("Median wealth when super is accessible", compact(outcomes["Wealth when super accessible"].median()),
             help="Total wealth on the first day super can be withdrawn (preservation age and retirement), when that "
                  "is after the start.")
    c.metric("Median total tax", compact(float((outcomes["Personal tax assessed"] + outcomes["Fund tax"]
                                                + outcomes["Division 296 tax"]).median())),
             help="Each path's personal tax assessed, super fund tax and Division 296 tax over the horizon; the median "
                  "of those path totals.")
    e.metric("Division 296: paths · median", affected(outcomes["Division 296 tax"]),
             help="Share of paths whose total super balance passed the large balance threshold (3 million dollars, "
                  "CPI-indexed), then the median tax among those paths.")
    long = annual.melt(["Path", "FY ending"], value_vars=columns, var_name="Flow", value_name="AUD")
    long["Flow"] = long["Flow"].str.replace("Flow: ", "", regex=False)
    stats = long.groupby(["FY ending", "Flow"])["AUD"].quantile([0.25, 0.5, 0.75]).unstack().reset_index()
    stats.columns = ["FY ending", "Flow", "P25", "Median", "P75"]
    stats = stats.groupby("Flow").filter(lambda g: g[["P25", "Median", "P75"]].abs().max().max() > 1e-6)
    stats["Period"] = stats["FY ending"].map(charts.period_label)
    net = annual.groupby("FY ending")["Net change in wealth"].quantile([0.25, 0.5, 0.75]).unstack().reset_index()
    net.columns = ["FY ending", "P25", "Median", "P75"]
    net["Period"] = net["FY ending"].map(charts.period_label)
    wealth = [c for c in ("Wealth at start of year", "Wealth at end of year") if c in annual]
    if wealth:
        net = net.merge(annual.groupby("FY ending")[wealth].median().reset_index(), on="FY ending")
    order = [f for f in FLOW_COLOURS if f in set(stats["Flow"])]
    x = alt.X("FY ending:Q", axis=charts.fy_axis(annual), scale=charts.fy_scale(annual))
    additions = (annual.groupby("FY ending")["Added to outside investments"].median().reset_index(name="AUD")
                 if "Added to outside investments" in annual else pd.DataFrame(columns=["FY ending", "AUD"]))
    additions["Period"] = additions["FY ending"].map(charts.period_label)
    # The net change's middle half is in its tooltip, not drawn: in late years it is several times the bars' height
    # and would flatten them.
    domain = charts.flow_domain(stats, "Median", (net["Median"], additions["AUD"] if len(additions) else [0.0]))
    bars = charts.flow_bars(stats, x, "Median", "Median per year, today's dollars", order, domain=domain,
                            tooltip=[alt.Tooltip("Median:Q", format="$,.0f"),
                                     alt.Tooltip("P25:Q", title="25th percentile", format="$,.0f"),
                                     alt.Tooltip("P75:Q", title="75th percentile", format="$,.0f")])
    line = alt.Chart(net).mark_line(color=INK, strokeWidth=2, point=alt.OverlayMarkDef(color=INK, size=30)).encode(
        x=x, y="Median:Q", tooltip=[alt.Tooltip("Period:N", title="Year"),
                                    *[alt.Tooltip(f"{c}:Q", title="Median wealth at start", format="$,.0f")
                                      for c in wealth if c.endswith("start of year")],
                                    alt.Tooltip("Median:Q", title="Median net change in wealth", format="$,.0f"),
                                    alt.Tooltip("P25:Q", title="25th percentile", format="$,.0f"),
                                    alt.Tooltip("P75:Q", title="75th percentile", format="$,.0f"),
                                    *[alt.Tooltip(f"{c}:Q", title="Median wealth at end", format="$,.0f")
                                      for c in wealth if c.endswith("end of year")]])
    added = charts.additions_layer(additions, x)
    layers = [bars, charts.zero_rule(), line] + ([added] if added is not None else [])
    with card("typical"):
        chart_title("Money in and out in a typical year",
                    f"The median across all {len(outcomes):,} paths of each flow in each year: money in above zero, money "
                    "out below.")
        legend([("Median net change in wealth", INK, "line"),
                *([("Added to outside investments", charts.ADDED_COLOUR, "line")] if added is not None else [])])
        draw(charts.with_milestones(alt.layer(*layers).properties(height=MEDIUM + 60), d.marks, "Position:Q"))
        explain("Each bar is the median across paths of that flow in that year. **Tax** adds income tax, the 15% "
                "contributions tax, super fund tax and Division 296 tax; the yearly tables on the Paths page keep each "
                "one. **Inflation** (grey) is the buying power your wealth lost that year: in today's dollars, wealth "
                "that only kept pace with prices shows no gain. The black line is the median net change in total "
                "wealth; hover it for its 25th and 75th percentiles and the median wealth at the start and end of each "
                "year. The dashed line is the median amount added to outside investments from your pay "
                "each year, and after retirement from unspent pension payments and other spare cash; it moves money "
                "from cash into the portfolio, so it is not a bar. Medians do not add up, so the bars do not sum "
                "exactly to the median net change; investment returns vary most between paths. A single path on the "
                "Paths page has bars that add up exactly.")


@st.fragment
def tables_tab(run):
    d = derived(run)
    outcomes, paths = d.outcomes, run.retirement_paths
    with card("ranges"):
        chart_title("Outcome ranges", "Percentiles across the calculated paths. Each row is ranked on its own, so two "
                                      "rows' 5th percentiles usually come from different paths.")
        ranges = percentile_table(outcomes, {
            "Ending wealth": ("Ending wealth", "money"), "Ending wealth after tax owed": ("Ending wealth after tax owed", "money"),
            "Ending outside wealth": ("Ending outside wealth", "money"),
            "Ending super and pension": ("Ending super and pension", "money"),
            "Wealth at retirement": ("Wealth at retirement", "money"),
            "Average retired-year spending": ("Average retired-year spending", "money"),
            "Lowest retired year's spending": ("Lowest retired-year spending", "money"),
            "Spending shortfall": ("Spending shortfall", "money"),
            "Age Pension received": ("Age Pension received", "money"),
            "Personal tax assessed": ("Personal tax assessed", "money"), "Fund tax": ("Fund tax", "money"),
            "Division 296 tax": ("Division 296 tax", "money"),
            "Account-based pension payments": ("Pension payments", "money"),
            "First retired-year withdrawal rate": ("First retired-year withdrawal rate", "percent"),
            "Median withdrawal rate": ("Median withdrawal rate", "percent"),
            "Highest withdrawal rate": ("Highest withdrawal rate", "percent"),
            "Largest fall in total wealth": ("Largest fall in wealth", "percent")})
        st.dataframe(ranges, width="stretch", hide_index=True, height=fit(ranges))
    with card("everypath"):
        chart_title(f"Every path ({len(paths):,})", "Sorted from the worst ending wealth to the best. Path numbers are "
                                                    "positions in the shared draw sequence, not ranks.")
        table = outcomes.drop(columns=["Ending wealth, nominal"], errors="ignore")
        missing = paths.loc[paths["Status"] == "unsupported"]
        table = pd.concat([table, missing], ignore_index=True) if len(missing) else table
        ranks = ending_percentiles(outcomes)
        front = ["Path", "Outcome", "Ending wealth percentile", "Ending wealth", "Average retired-year spending",
                 "Age Pension received", "Age Pension years", "Spending shortfall"]
        table.insert(1, "Ending wealth percentile", table["Path"].map(ranks))
        table = table[front + [c for c in table.columns if c not in front and c != "Status"]]
        table = table.sort_values("Ending wealth percentile", na_position="last")
        rates = ("First retired-year withdrawal rate", "Highest withdrawal rate", "Median withdrawal rate",
                 "Largest fall in wealth", "Starting withdrawal rate", "Deepest cut below start",
                 "Age Pension share of retired spending")
        for field in rates:
            if field in table:
                table[field] = table[field] * 100
        money = ("Ending wealth", "Ending outside wealth", "Ending super and pension", "Ending wealth after tax owed",
                 "Tax owed at end", "Wealth at retirement", "Wealth when super accessible", "Spending paid",
                 "Spending shortfall", "Unpaid tax", "Personal tax assessed", "Fund tax", "Division 296 tax",
                 "Age Pension received", "Pension payments", "Pension balance at start", "Average retired-year spending",
                 "Starting retirement spending", "Lowest retired-year spending")
        st.dataframe(table, width="stretch", hide_index=True, height=420, column_config={
            "Path": st.column_config.NumberColumn("Path", format="%d", pinned=True),
            "Outcome": st.column_config.TextColumn("Outcome", pinned=True),
            "Ending wealth percentile": st.column_config.NumberColumn(
                "Percentile", format="%.0f",
                help="Where this path's ending wealth ranks among calculated paths: 1 is near the worst, 99 near the best."),
            **{field: money_column(field) for field in money},
            **{field: percent_column(field) for field in rates}})
        name = run.plan["plan"]["name"].lower().replace(" ", "-")
        st.download_button("Download every path (CSV)", outcomes.to_csv(index=False), f"{name}-paths.csv", "text/csv",
                           key=key(result_key(run, "download_paths")), icon=":material/download:")
