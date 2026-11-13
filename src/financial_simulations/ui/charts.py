"""Chart builders for the browser app. Each returns an Altair chart; ``theme.draw`` styles and shows it.

Shared conventions: time runs on the x axis as dates or as financial years ending 30 June; amounts are today's
dollars; dashed vertical lines mark retirement, super access and the pension start; drag pans and Shift+scroll zooms.
"""

from datetime import date
import warnings

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from financial_simulations.reporting.palette import (ACCOUNT_COLOURS, MORTGAGE_COLOUR, PROPERTY_COLOUR,
                                                     PROPERTY_LOAN_COLOUR, ADDED_COLOUR, AXIS, BLUE, FLOW_COLOURS, INK,
                                                     INK_SECONDARY, MUTED, NET_COLOUR, PORTFOLIO_COLOURS, SERIES, SURFACE,
                                                     TIER_COLOURS)
from financial_simulations.retirement.outcomes import TIERS
from financial_simulations.rules.au.superannuation import age_on
from financial_simulations.ui.state import compact
from financial_simulations.ui.theme import MEDIUM, SHORT, TALL


YEAR_TITLE = "Year ending 30 June"
BORN = {"date": None}  # the current plan's birth date, set before results are drawn, for "Age" in tooltips
ZOOM_COUNT = [0]
SHOWN_PATHS = 300  # funded paths drawn; every path that ran out is drawn as well
ADDED_LABEL, NET_LABEL = "Added to outside investments (line)", "Net change in wealth (line)"
BAND_NAMES = {"P05": "5th percentile (1 in 20 paths lower)", "P25": "25th percentile", "P50": "Median",
              "P75": "75th percentile", "P95": "95th percentile (1 in 20 paths higher)"}


def zoomable(chart):
    """Drag to pan and Shift+scroll to zoom; plain scrolling keeps scrolling the page."""
    # Explicit unique names: auto-generated ones can collide in layered charts ("Duplicate signal name").
    ZOOM_COUNT[0] += 1
    zoom = alt.selection_interval(bind="scales", zoom="wheel![event.shiftKey]", name=f"zoom_{ZOOM_COUNT[0]}")
    if isinstance(chart, alt.LayerChart):
        chart.layer[0] = chart.layer[0].add_params(zoom)
        return chart
    return chart.add_params(zoom)


def year_axis(frame, field="Date"):
    span = (pd.to_datetime(frame[field]).max() - pd.to_datetime(frame[field]).min()).days / 365.25
    return alt.Axis(format="%Y", tickCount=max(4, min(12, int(span / (5 if span >= 25 else 2 if span >= 12 else 1)))),
                    labelOverlap=True)


def fy_axis(frame, field="FY ending"):
    years = frame[field]
    step = 5 if years.nunique() >= 25 else 2 if years.nunique() >= 12 else 1
    return alt.Axis(format="d", values=[y for y in range(int(years.min()), int(years.max()) + 1) if y % step == 0 or step == 1],
                    title=YEAR_TITLE)


def fy_scale(frame, field="FY ending", pad=0.6):
    return alt.Scale(domain=[int(frame[field].min()) - pad, int(frame[field].max()) + pad], nice=False)


def money_axis(**options):
    """Dollar ticks, compact from $10,000 up ($250k, $1.5m)."""
    return alt.Axis(labelExpr="datum.value === 0 ? '$0' : abs(datum.value) >= 1e6 ? (datum.value < 0 ? '-$' : '$') + "
                              "format(abs(datum.value) / 1e6, '~f') + 'm' : abs(datum.value) >= 1e4 ? "
                              "(datum.value < 0 ? '-$' : '$') + format(abs(datum.value) / 1e3, '~f') + 'k' : "
                              "(datum.value < 0 ? '-$' : '$') + format(abs(datum.value), ',.0f')", **options)


def log_axis(low, high, **options):
    """A dollar axis for a log scale: a tick at each power of ten (and at 3 times it when the range is short)."""
    powers = range(int(np.floor(np.log10(max(low, 1e-9)))), int(np.ceil(np.log10(high))) + 1)
    steps = (1, 3) if len(powers) <= 4 else (1,)
    ticks = [m * 10.0 ** p for p in powers for m in steps if low <= m * 10.0 ** p <= high]
    return alt.Axis(values=ticks, format="$,.0f", **options)


def symlog_axis(upper):
    """A dollar axis for a symlog scale: $0 and powers of ten, labelled $1k, $10k, ... $1m."""
    first_power = 4 if upper >= 1e6 else 3
    ticks = [0, *[10 ** power for power in range(first_power, 13) if 10 ** power <= upper]]
    labels = ("datum.value === 0 ? '$0' : datum.value >= 1000000 ? "
              "'$' + datum.value / 1000000 + 'm' : '$' + datum.value / 1000 + 'k'")
    return alt.Axis(values=ticks, labelExpr=labels, labelOverlap=False)


def add_age(frame, field="Date"):
    """Add an Age column (whole years on that date, or at 30 June for a financial year) when a birth date is known."""
    born = BORN["date"]
    if born is None or field not in frame:
        return frame
    frame = frame.copy()
    if field == "FY ending":
        days = [date(int(y), 6, 30) for y in frame[field]]
    else:
        days = [pd.Timestamp(d).date() for d in frame[field]]
    frame["Age"] = [age_on(born, d) if d >= born else None for d in days]
    return frame


def age_tooltip(frame):
    return [alt.Tooltip("Age:Q", title="Your age", format="d")] if "Age" in frame else []


def period(end_year):
    """Plain wording for an Australian financial year, e.g. 2027 -> 'Jul 2026 – Jun 2027'."""
    return f"Jul {int(end_year) - 1} – Jun {int(end_year)}"


def period_label(end_year):
    """A financial year for tooltips, with the person's age at its 30 June when known."""
    born = BORN["date"]
    text = period(end_year)
    return f"{text} (age {age_on(born, date(int(end_year), 6, 30))} at 30 June)" if born else text


def milestone_layers(marks, x="Date:T"):
    """Dashed vertical lines and labels for life events, as layers for a flat layered chart."""
    if marks is None or marks.empty:
        return []
    return [alt.Chart(marks).mark_rule(strokeDash=[4, 3], color=MUTED, strokeWidth=1).encode(
                x=x, tooltip=["Event:N", alt.Tooltip("Date:T", format="%d %b %Y")]),
            alt.Chart(marks).mark_text(align="left", dx=5, fontSize=11, color=INK_SECONDARY).encode(
                x=x, y=alt.Y("Offset:Q", scale=None), text="Event:N")]


def with_milestones(chart, marks, x="Date:T"):
    layers = milestone_layers(marks, x)
    return alt.layer(chart, *layers) if layers else chart


def zero_rule():
    return alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=AXIS).encode(y="y:Q")


def quantile_bands(frame, by, field):
    q = frame.groupby(by)[field].quantile([0.05, 0.25, 0.5, 0.75, 0.95]).unstack().reset_index()
    q.columns = [by, "P05", "P25", "P50", "P75", "P95"]
    if by == "FY ending":
        q["Period"] = q[by].map(period_label)
    return q


def band_chart(frame, title, *, log=False, symlog=False, color=BLUE, percent=False, x="Date:T", marks=None, height=MEDIUM):
    """Hoverable percentile bands (5th-95th, 25th-75th, median) with zoom and optional life-event lines."""
    if x == "Date:T":
        xs = alt.X("Date:T", title=None, axis=year_axis(frame))
    else:
        field = x.split(":")[0]
        xs = alt.X(x, scale=fy_scale(frame, field, 0.5),
                   axis=fy_axis(frame, field) if field == "FY ending" else alt.Axis(format="d", title=None))
    if symlog:
        scale, axis = alt.Scale(type="symlog", constant=1000, zero=True), symlog_axis(float(frame["P95"].max()))
    elif log:
        low, high = float(frame["P05"].min()) * 0.9, float(frame["P95"].max()) * 1.1
        scale, axis = alt.Scale(type="log", domain=[low, high], nice=False), log_axis(low, high)
    else:
        scale, axis = alt.Scale(zero=True), alt.Axis(format=".0%") if percent else money_axis()
    number = ".1%" if percent else "$,.0f"
    y = alt.Y("P05:Q", title=title, scale=scale, axis=axis)
    frame = add_age(frame, "Date" if x == "Date:T" else x.split(":")[0])
    when = (alt.Tooltip("Date:T", format="%b %Y") if x == "Date:T" else
            alt.Tooltip("Period:N", title="Year") if "Period" in frame else alt.Tooltip(x, format="d"))
    tooltip = [when, *age_tooltip(frame), *[alt.Tooltip(f"{q}:Q", title=BAND_NAMES[q], format=number) for q in BAND_NAMES]]
    base = alt.Chart(frame)
    outer = base.mark_area(opacity=0.14, color=color).encode(x=xs, y=y, y2="P95:Q", tooltip=tooltip)
    inner = base.mark_area(opacity=0.26, color=color).encode(x=xs, y="P25:Q", y2="P75:Q", tooltip=tooltip)
    median = base.mark_line(color=color, strokeWidth=2).encode(x=xs, y="P50:Q", tooltip=tooltip)
    chart = zoomable(alt.layer(outer, inner, median).properties(height=height))
    if marks is not None:
        if x != "Date:T":  # keep event labels inside the financial-year domain
            field = x.split(":")[0]
            marks = marks.loc[marks["Position"].between(frame[field].min() - 0.5, frame[field].max() + 0.5)]
        chart = with_milestones(chart, marks, "Date:T" if x == "Date:T" else "Position:Q")
    return chart


def accounts(daily):
    """Balances by account in a fixed order, with any loans as negative balances, and their labels and colours.

    The accounts are assets, then an investment property's value; each loan column appears only when something is
    owed on the path, so the sum of a row is total wealth net of the loans.
    """
    colours = dict(ACCOUNT_COLOURS)
    frame = daily[list(ACCOUNT_COLOURS)].copy()
    if "property_value" in daily and (daily["property_value"] > 0.005).any():
        colours["property_value"] = PROPERTY_COLOUR
        frame["property_value"] = daily["property_value"]
    for column, colour in (("mortgage", MORTGAGE_COLOUR), ("property_loan", PROPERTY_LOAN_COLOUR)):
        if column in daily and (daily[column] > 0.005).any():
            colours[column] = colour
            frame[column] = -daily[column]
    return frame, colours


def balances_chart(daily, height=MEDIUM, x=None, zoom=True, **axis):
    """Stacked month-end balances by account, in a fixed account order and colour; a mortgage stacks below zero.

    ``x`` replaces the date encoding and ``zoom=False`` leaves zooming to the caller, for a panel of a stacked chart.
    """
    frame, colours = accounts(daily)
    labels = [v[0] for v in colours.values()]
    monthly = frame.resample("ME").last().reset_index()
    long = monthly.melt("Date", var_name="account", value_name="balance")
    long["Account"] = long["account"].map(lambda a: colours[a][0])
    long["order"] = long["account"].map(list(colours).index)
    long["Total"] = long.groupby("Date")["balance"].transform("sum")
    long["Share"] = long["balance"] / long["Total"].where(long["Total"] > 0)
    long = add_age(long)
    chart, _ = toggle(alt.Chart(long).mark_area(stroke=SURFACE, strokeWidth=1).encode(
        x=x if x is not None else alt.X("Date:T", title=None, axis=year_axis(long)),
        y=alt.Y("balance:Q", stack="zero", title="Today's dollars", axis=money_axis(**axis)),
        color=alt.Color("Account:N", sort=labels, scale=alt.Scale(domain=labels, range=[v[1] for v in colours.values()])),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), *age_tooltip(long), "Account:N",
                 alt.Tooltip("balance:Q", title="Balance", format="$,.0f"),
                 alt.Tooltip("Share:Q", title="Share of wealth", format=".0%"),
                 alt.Tooltip("Total:Q", title="Total wealth", format="$,.0f")],
    ).properties(height=height), "Account", labels, "accounts")
    return zoomable(chart) if zoom else chart


def shown_paths(paths):
    """Paths to draw: every depleted path, and up to SHOWN_PATHS funded paths spread evenly across ending wealth.

    Spacing by ending-wealth rank keeps the sample's spread the same as the full set's, so the grey density is a
    fair picture of the distribution while the browser handles a bounded number of lines.
    """
    ending = paths.sort_values("Date").groupby("Path").agg(Status=("Status", "first"), End=("Total wealth", "last"))
    depleted = ending.index[ending["Status"] == "depleted"].tolist()
    funded = ending.loc[ending["Status"] != "depleted"].sort_values("End")
    if len(funded) > SHOWN_PATHS:
        funded = funded.iloc[np.unique(np.linspace(0, len(funded) - 1, SHOWN_PATHS).round().astype(int))]
    return funded.index.tolist(), depleted


# How each tier's lines are drawn in the all-paths image: (line width, opacity for a few lines, for many lines).
TIER_LINES = {TIERS[0]: (0.9, 0.4, 0.08), TIERS[1]: (1.0, 0.8, 0.35), TIERS[2]: (1.2, 0.9, 0.5), TIERS[3]: (1.3, 0.9, 0.4)}


def paths_image(paths, by_tier, first, last, top, wide):
    """The drawn paths as one transparent PNG data URL, in the chart's exact (linear or symlog) space.

    ``by_tier`` maps each outcome tier to its drawn paths. Self-funded paths are translucent grey, so overlaps darken
    where most paths went; the Age Pension tiers and the paths that ran out are drawn over them in their colours.
    """
    import base64
    import io

    from matplotlib.collections import LineCollection
    from matplotlib.figure import Figure
    from PIL import Image

    fig = Figure(figsize=(14, 6), dpi=120)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.patch.set_alpha(0)
    span = (last - first) or pd.Timedelta(days=1)

    def transform(values):
        # Vega's symlog with constant C maps y to sign(y) * log1p(|y| / C); reproduce it so pixels line up.
        return np.sign(values) * np.log1p(np.abs(values) / 1000) if wide else values

    groups = dict(tuple(paths.groupby("Path", sort=False)))
    for tier in TIERS:
        chosen = by_tier.get(tier, [])
        width, few, many = TIER_LINES[tier]
        # About 45 overlapping lines reach full darkness, so a large group is drawn lighter and does not hide the rest.
        alpha = float(np.clip(45 * few / max(len(chosen), 1), many, few))
        # Timedelta division, not raw integers: pandas may store the dates in microseconds rather than nanoseconds.
        segments = [np.column_stack((((pd.to_datetime(groups[p]["Date"]) - first) / span).to_numpy(dtype=float),
                                     transform(groups[p]["Total wealth"].to_numpy()))) for p in chosen]
        if segments:
            ax.add_collection(LineCollection(segments, colors="#3d3d3d" if tier == TIERS[0] else TIER_COLOURS[tier],
                                             linewidths=width, alpha=alpha))
    ax.set_xlim(0, 1)
    ax.set_ylim(transform(np.array([0.0]))[0], transform(np.array([top]))[0])
    rendered = io.BytesIO()
    fig.savefig(rendered, format="png", transparent=True)
    # A 256-colour palette keeps the transparency and is several times smaller than full-colour RGBA.
    rendered.seek(0)
    buffer = io.BytesIO()
    Image.open(rendered).quantize(256, method=Image.Quantize.FASTOCTREE).save(buffer, format="png", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def all_paths_chart(paths, marks, outcomes, shown=TIERS, cache_key=None, log=True, height=TALL):
    """Many paths' total wealth, coloured by outcome tier.

    Speed: the drawn lines are one server-rendered image, cached per result and choice, so the browser never draws
    hundreds of lines. Hover data are the drawn paths only, quarterly for the highlighted line and yearly for the
    pointer targets, and the chart uses the canvas renderer. Returns the chart, the number of paths drawn by tier
    and the number of paths clipped off a linear axis.
    """
    tier_of = outcomes.set_index("Path")["Outcome"]
    medians = paths.groupby("Date")["Total wealth"].median()  # from every path, drawn or not
    funded, depleted = shown_paths(paths)
    # Every path that ran out or reached the full Age Pension is drawn; the rest are the evenly spread sample.
    chosen = sorted(set(funded) | set(depleted) | set(tier_of.index[tier_of == TIERS[2]]))
    by_tier = {tier: [p for p in chosen if tier_of.get(p) == tier] for tier in TIERS if tier in shown}
    drawn_paths = [p for members in by_tier.values() for p in members]
    drawn = paths.loc[paths["Path"].isin(drawn_paths), ["Date", "Path", "Total wealth"]]
    wide = log  # symlog: logarithmic above $1,000 and linear below, so paths at $0 still plot
    # On a linear axis the top stops just above the 97.5th percentile of the paths' peaks, so a few runaway paths do
    # not squash the band where most paths sit; about one path in forty is clipped. The log axis shows every path.
    peaks = (drawn if len(drawn) else paths).groupby("Path")["Total wealth"].max()
    top = (float(peaks.max()) * 1.02 if log
           else min(float(peaks.max()) * 1.02, float(peaks.quantile(0.975)) * 1.05)) or 1.0
    clipped = int((peaks > top).sum())
    first, last = pd.Timestamp(paths["Date"].min()), pd.Timestamp(paths["Date"].max())
    cache = st.session_state.setdefault("paths_image_cache", {})
    cache_key = (cache_key, top, wide, tuple(by_tier))
    if cache_key[0] is None or cache_key not in cache:
        if len(cache) > 12:
            cache.clear()
        cache[cache_key] = paths_image(drawn, by_tier, first, last, top, wide)
    y_scale = (alt.Scale(type="symlog", constant=1000, domain=[0, top], nice=False) if wide
               else alt.Scale(domain=[0, top], nice=False))
    y_title = "Total wealth, today's dollars" + (" · log scale" if wide else "")
    y_axis = symlog_axis(top) if wide else money_axis()
    y = alt.Y("Total wealth:Q", title=y_title, scale=y_scale, axis=y_axis)
    x = alt.X("Date:T", title=None, axis=year_axis(paths), scale=alt.Scale(domain=[first.isoformat(), last.isoformat()]))
    # The image's left edge must use the same field name as the shared x encoding ("Date"), or it is never placed.
    image = pd.DataFrame({"url": [cache[cache_key]], "Date": [first.isoformat()],
                          "x2": [last.isoformat()], "y": [top], "y2": [0.0]})
    lines = alt.Chart(image).mark_image(aspect=False, align="left", baseline="top").encode(
        x=x, x2="x2:T", y=alt.Y("y:Q", scale=y_scale, title=y_title, axis=y_axis), y2="y2:Q", url="url:N")
    median_frame = add_age(medians.reset_index())
    median = alt.Chart(median_frame).mark_line(color=BLUE, strokeWidth=2.5, clip=True).encode(
        x=x, y=y,
        tooltip=[alt.Tooltip("Date:T", format="%b %Y"), *age_tooltip(median_frame),
                 alt.Tooltip("Total wealth:Q", title="Median of all paths", format="$,.0f")])
    layers = [lines, median]
    if len(drawn):
        hover = alt.selection_point(fields=["Path"], on="pointerover", nearest=True, clear="pointerout", empty=False,
                                    name="path_hover")
        # Compact hover data: dates as plain strings, whole dollars, and per-path facts joined in the browser.
        dates = pd.to_datetime(drawn["Date"])

        def compact_rows(frame):
            return frame.assign(Date=pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d"),
                                **{"Total wealth": frame["Total wealth"].round()})

        quarterly = compact_rows(drawn.loc[dates.dt.month.isin([3, 6, 9, 12]) | (dates == dates.max()) | (dates == dates.min())])
        highlight = alt.Chart(quarterly).transform_filter(hover).mark_line(strokeWidth=3, color=INK, clip=True).encode(
            x=x, y=y, detail="Path:N")
        yearly = compact_rows(add_age(drawn.loc[(dates.dt.month == 6) | (dates == dates.max())]))
        facts = [("Outcome", None, "Outcome"), ("Ending wealth", "$,.0f", "Ending wealth"),
                 ("Average retired-year spending", "$,.0f", "Average spending per retired year"),
                 ("Age Pension received", "$,.0f", "Age Pension received"), ("Age Pension first paid", None, "Age Pension first paid"),
                 ("Spending shortfall", "$,.0f", "Spending shortfall"), ("First shortfall", None, "Money first ran short")]
        facts = [f for f in facts if f[0] in outcomes]
        info = outcomes.loc[outcomes["Path"].isin(drawn_paths), ["Path", *[f[0] for f in facts]]]
        info = info.assign(**{f[0]: info[f[0]].round() for f in facts if f[1]})
        points = alt.Chart(yearly).transform_lookup(
            lookup="Path", from_=alt.LookupData(info, "Path", [c for c in info.columns if c != "Path"])
        ).mark_point(opacity=0, size=80, clip=True).encode(
            x=x, y=y,
            tooltip=[alt.Tooltip("Path:N", title="Path"), alt.Tooltip("Date:T", format="%b %Y"), *age_tooltip(yearly),
                     alt.Tooltip("Total wealth:Q", title="Wealth on this date", format="$,.0f"),
                     *[alt.Tooltip(f"{name}:Q", format=fmt, title=title) if fmt else alt.Tooltip(f"{name}:N", title=title)
                       for name, fmt, title in facts]]).add_params(hover)
        layers += [highlight, points]
        # A marker where each drawn path first ran short, and where each first received the Age Pension.
        for field, tiers, mark in (("First shortfall", (TIERS[3],), {"shape": "cross", "size": 80, "color": TIER_COLOURS[TIERS[3]]}),
                                   ("Age Pension first paid", (TIERS[1], TIERS[2]), {"shape": "circle", "size": 26})):
            if field not in outcomes:
                continue
            members = [p for tier in tiers for p in by_tier.get(tier, [])]
            events = outcomes.loc[outcomes["Path"].isin(members) & (outcomes[field] != ""), ["Path", "Outcome", field]]
            if events.empty:
                continue
            events = events.assign(Date=pd.to_datetime(events[field]) + pd.offsets.MonthEnd(0))
            events = add_age(events.merge(drawn, on=["Path", "Date"], how="left").dropna())
            colour = ({} if "color" in mark else
                      {"color": alt.Color("Outcome:N", legend=None, scale=alt.Scale(domain=list(TIERS),
                                                                                   range=[TIER_COLOURS[t] for t in TIERS]))})
            layers.append(alt.Chart(events).mark_point(filled=True, opacity=0.95, stroke=SURFACE, strokeWidth=0.8, clip=True, **mark)
                          .encode(x=x, y=y, **colour,
                                  tooltip=[alt.Tooltip("Path:N", title="Path"), alt.Tooltip(f"{field}:N", title=field),
                                           *age_tooltip(events),
                                           alt.Tooltip("Total wealth:Q", title="Wealth that month", format="$,.0f")]))
    # One flat layer: nesting a chart that owns a selection inside another layer duplicates its signals.
    ZOOM_COUNT[0] += 1
    zoom = alt.selection_interval(bind="scales", zoom="wheel![event.shiftKey]", name=f"zoom_{ZOOM_COUNT[0]}")
    layers[0] = lines.add_params(zoom)
    layers += milestone_layers(marks)
    chart = alt.layer(*layers).properties(height=height, usermeta={"embedOptions": {"renderer": "canvas"}})
    return chart, {tier: len(members) for tier, members in by_tier.items()}, clipped


def states_chart(shares, marks, height=MEDIUM):
    """The share of paths in each outcome state in each financial year, as stacked areas with the worst at the bottom."""
    frame = add_age(shares, "FY ending")
    frame = frame.assign(Period=frame["FY ending"].map(period_label), order=frame["State"].map(list(reversed(TIERS)).index))
    # No fixed y domain: with every state shown the stack reaches 100%, and hiding Self-funded in the legend lets
    # the axis close in on the states that need attention.
    chart, _ = toggle(alt.Chart(frame).mark_area(stroke=SURFACE, strokeWidth=1).encode(
        x=alt.X("FY ending:Q", axis=fy_axis(frame), scale=fy_scale(frame, pad=0)),
        y=alt.Y("Share:Q", stack="zero", title="Share of paths", axis=alt.Axis(format=".0%"), scale=alt.Scale(nice=False)),
        color=alt.Color("State:N", sort=list(reversed(TIERS)), legend=alt.Legend(symbolType="square"),
                        scale=alt.Scale(domain=list(reversed(TIERS)), range=[TIER_COLOURS[t] for t in reversed(TIERS)])),
        order=alt.Order("order:Q"),
        # Self-funded is the quiet background; the three states that need attention keep their full colour.
        opacity=alt.condition(alt.datum.State == TIERS[0], alt.value(0.4), alt.value(1)),
        tooltip=[alt.Tooltip("Period:N", title="Year"), "State:N", alt.Tooltip("Share:Q", title="Share of paths", format=".1%"),
                 alt.Tooltip("Paths:Q", format=",d")]).properties(height=height), "State", list(reversed(TIERS)), "states")
    inside = marks.loc[marks["Position"].between(frame["FY ending"].min(), frame["FY ending"].max())] if len(marks) else marks
    return with_milestones(chart, inside, "Position:Q")


def group_spending_chart(groups):
    """Average retired-year spending by group: a dot at the median path over a bar from the 10th to 90th percentile."""
    frame = groups.assign(Label=[f"{g}  ·  {n:,}" for g, n in zip(groups["Group"], groups["Paths"])],
                          Colour=[TIER_COLOURS.get(g, INK if g == "All paths" else BLUE) for g in groups["Group"]],
                          Text=groups["Median"].map(compact))
    y = alt.Y("Label:N", sort=frame["Label"].tolist(), title=None,
              axis=alt.Axis(labelLimit=320, labelColor=INK_SECONDARY, labelFontSize=12.5, domain=False, ticks=False))
    tooltip = ["Group:N", alt.Tooltip("Paths:Q", format=",d"), alt.Tooltip("Share:Q", title="Share of paths", format=".1%"),
               alt.Tooltip("Median:Q", title="Median path's average spending", format="$,.0f"),
               alt.Tooltip("P10:Q", title="10th percentile", format="$,.0f"),
               alt.Tooltip("P90:Q", title="90th percentile", format="$,.0f"),
               alt.Tooltip("Lowest year (median):Q", title="Lowest year (median path)", format="$,.0f")]
    base = alt.Chart(frame)
    x = alt.X("P10:Q", title="Average spending paid per retired year, today's dollars", axis=money_axis(grid=True, tickCount=7),
              scale=alt.Scale(domain=[0, float(frame["P90"].max()) * 1.12], nice=False))
    span = base.mark_bar(height=10, opacity=0.3, cornerRadius=5).encode(
        x=x, x2="P90:Q", y=y, color=alt.Color("Colour:N", scale=None), tooltip=tooltip)
    dot = base.mark_point(filled=True, size=130, opacity=1, stroke=SURFACE, strokeWidth=2).encode(
        x="Median:Q", y=y, color=alt.Color("Colour:N", scale=None), tooltip=tooltip)
    text = base.mark_text(align="left", dx=10, fontSize=12, color=INK).encode(x="P90:Q", y=y, text="Text:N")
    return alt.layer(span, dot, text).properties(height=30 * len(frame) + 10)


def flow_domain(frame, field, extra=()):
    """A y domain that fits diverging stacked bars (positives and negatives stack separately) and any lines."""
    by_year = frame.groupby("FY ending")[field]
    top = max([float(by_year.apply(lambda v: v[v > 0].sum()).max()), *[float(np.nanmax(e)) for e in extra], 0.0])
    low = min([float(by_year.apply(lambda v: v[v < 0].sum()).min()), *[float(np.nanmin(e)) for e in extra], 0.0])
    pad = 0.08 * (top - low or 1.0)
    return [low - pad, top + pad]


def flow_colour(items, palette=None):
    palette = {**FLOW_COLOURS, NET_LABEL: NET_COLOUR, ADDED_LABEL: ADDED_COLOUR, **(palette or {})}
    return alt.Color("Flow:N", sort=items, scale=alt.Scale(domain=items, range=[palette[f] for f in items]),
                     legend=alt.Legend(columns=5, symbolType="square"))


def additions_layer(frame, x, value="AUD", color=None):
    """Money moved from pay into outside investments: a dashed line, because it does not change total wealth.

    ``color`` optionally encodes a ``Flow`` column so the line joins a chart's legend.
    """
    frame = frame.loc[frame[value].abs() > 1e-6]
    if frame.empty:
        return None
    return alt.Chart(frame).mark_line(color=ADDED_COLOUR, strokeDash=[5, 3], strokeWidth=2,
                                      point=alt.OverlayMarkDef(shape="square", size=36, color=ADDED_COLOUR, filled=True)).encode(
        x=x, y=f"{value}:Q",
        **({"color": color} if color is not None else {}),
        tooltip=[alt.Tooltip("Period:N", title="Year"),
                 alt.Tooltip(f"{value}:Q", title="Added to outside investments", format="$,.0f")])


def hideable(chart, field, names, state, key):
    """Let legend clicks toggle each item; hidden items stay in the legend, faded, and leave the y scale.

    The chart's colour scale needs a fixed domain so hidden items keep their legend entries. Returns the chart and
    the selection, which other layers can filter on so their legend entries hide them too.
    """
    # The selection holds the items shown. Vega-Lite fades legend entries outside a legend-bound selection, so
    # hidden items fade; each click toggles one item in or out. The count in the name makes each reset a new spec.
    # Show none selects a placeholder rather than nothing: an empty selection would leave the legend unfaded.
    shown = [n for n in names if n not in state["hidden"]] or ["(none)"]
    # Only clicks on this field's own legend count. Vega-Lite's plain legend binding listens to every click in the
    # chart, so in a chart with two such legends a click on one would toggle the other's last item back.
    clicks = alt.LegendStreamBinding(
        legend=f"click[event.item && event.item.mark.name && indexof(event.item.mark.name, '{field}_legend') === 0]")
    visible = alt.selection_point(name=f"show_{key}_{state['count']}", fields=[field], bind=clicks, toggle="true",
                                  empty=False, clear=False, value=[{field: n} for n in shown])
    return chart.add_params(visible).transform_filter(visible), visible


def toggle(chart, field, names, key):
    """Legend clicks hide and show a chart's items, with every item shown to start (see ``hideable``)."""
    return hideable(chart, field, names, {"hidden": [], "count": 0}, key)


def flow_bars(frame, x, value, title, items, *, domain=None, tooltip=(), size=14):
    """Stacked money in (above zero) and out (below) bars by flow, in the fixed flow order and colours.

    Legend clicks hide and show a flow.
    """
    scale = alt.Scale(domain=domain, nice=False) if domain else alt.Undefined
    return toggle(alt.Chart(frame).mark_bar(size=size, stroke=SURFACE, strokeWidth=0.6).encode(
        x=x, y=alt.Y(f"{value}:Q", stack=True, title=title, axis=money_axis(), scale=scale),
        color=flow_colour(items), order=alt.Order("Flow:N"),
        tooltip=[alt.Tooltip("Period:N", title="Year"), "Flow:N", *tooltip]), "Flow", items, "flows")[0]


def cursor_layers(frame, x, cursor, tooltip):
    """A vertical hairline at the month nearest the pointer, with that month's figures as the tooltip.

    The same ``cursor`` selection in several panels moves the hairline in all of them at once.
    """
    targets = (alt.Chart(frame).mark_point(opacity=0, size=1).encode(x=x, tooltip=tooltip).add_params(cursor)
               .properties(name="cursor_targets_0"))
    line = alt.Chart(frame).mark_rule(color=INK_SECONDARY, strokeWidth=1).encode(x=x).transform_filter(cursor)
    return [targets, line]


def flow_items(household, additions):
    """The flows with any money on this path, in their fixed order, and the legend items (the two lines included)."""
    largest = household.groupby("Flow")["AUD"].apply(lambda v: v.abs().max())
    order = [f for f in FLOW_COLOURS if largest.get(f, 0.0) > 1e-6]
    return order, order + [NET_LABEL] + ([ADDED_LABEL] if (additions["AUD"].abs() > 1e-6).any() else [])


def fy_span(end_year, first, last, inset=0.16):
    """A financial year's bar on a date axis: its start and end inside the plotted dates, inset, and its midpoint."""
    start, end = max(pd.Timestamp(int(end_year) - 1, 7, 1), first), min(pd.Timestamp(int(end_year), 6, 30), last)
    pad = (end - start) * inset
    return start + pad, end - pad, start + (end - start) / 2


def path_story(growth, kinds, colours, daily, household, additions, marks, states, heights=(300, 250, 330), group=False):
    """One path in three panels on one date axis: markets, balances by account, and money in and out.

    ``growth`` is the path's growth of $1 in today's dollars by series (``kinds`` names each a portfolio or a
    ticker); ``daily`` the ledger in today's dollars; ``household`` the yearly flows with taxes folded;
    ``additions`` the yearly amounts added to outside investments. ``states`` holds the legend state of the markets
    and flows panels. The panels share the x scale, so a drag or Shift+scroll moves all three, and one hairline
    follows the pointer through all three. With ``group`` the frames summarise a group of paths (median growth
    and balances at month ends, average flows) and the axis titles say so.

    Returns the chart and, by selection name, the name prefixes of the views each selection belongs to. Altair
    lists every selection of a layered panel against every layer that has one, which defines some twice
    ("Duplicate signal name"), so ``theme.draw`` writes the right lists into the specification. Prefixes, because
    Altair renumbers the end of a view's name.
    """
    first, last = daily.index[0], daily.index[-1]
    # Month ends, with the last one pulled back to the final day so the hairline stays on the plot.
    months = pd.DatetimeIndex([min(m, last) for m in daily["total"].resample("ME").last().index], name="Date")
    stamp = pd.DataFrame({"Date": months})
    span_frame = pd.DataFrame({"Date": [first, last]})
    axis = year_axis(span_frame)

    def x(field="Date"):
        return alt.X(f"{field}:T", title=None, axis=axis, scale=alt.Scale(domain=[first.isoformat(), last.isoformat()]))

    ZOOM_COUNT[0] += 1
    zoom = alt.selection_interval(bind="scales", encodings=["x"], zoom="wheel![event.shiftKey]", name=f"zoom_{ZOOM_COUNT[0]}")
    cursor = alt.selection_point(name=f"cursor_{ZOOM_COUNT[0]}", fields=["Date"], nearest=True, on="pointerover",
                                 clear="pointerout", empty=False)
    when = [alt.Tooltip("Date:T", title="Month", format="%b %Y")]
    wide = 64  # the same room for every panel's y labels, so the plot areas line up

    # Markets: weekly points draw every crash a monthly line would smooth, at a fifth of the daily rows.
    names = list(growth.columns)
    weekly = pd.concat([growth.iloc[:1], growth.resample("W").last().dropna(how="all")])
    weekly = weekly.loc[~weekly.index.duplicated()].rename_axis("Date").reset_index()
    long = weekly.melt("Date", var_name="Series", value_name="Growth")
    long["Kind"] = long["Series"].map(kinds)
    # A log axis draws a grid line at every tick; only exact 1, 2, 3 and 5 multiples of a power of ten are labelled
    # (a short range has ticks such as 1.2 and 1.4, which would otherwise all read "$1").
    mantissa = "(datum.value / pow(10, floor(log(datum.value) / LN10 + 1e-9)))"
    money = (f"abs({mantissa} - round({mantissa})) > 1e-6 || indexof([1, 2, 3, 5], round({mantissa})) < 0 ? '' : "
             "'$' + (datum.value < 1 ? format(datum.value, '~g') : format(datum.value, ',.0f'))")
    lines, visible = hideable(alt.Chart(long).mark_line(clip=True).encode(
        x=x(), y=alt.Y("Growth:Q", scale=alt.Scale(type="log", nice=False, padding=10),
                       title=("Median growth" if group else "Growth") + " of $1, today's dollars · log scale",
                       axis=alt.Axis(labelExpr=money, minExtent=wide)),
        color=alt.Color("Series:N", sort=names, scale=alt.Scale(domain=names, range=[colours[n] for n in names]),
                        legend=alt.Legend(symbolType="stroke", symbolStrokeWidth=3, symbolSize=260, columns=8)),
        size=alt.Size("Kind:N", legend=None, scale=alt.Scale(domain=sorted(set(kinds.values())),
                                                            range=[3 if k == "Portfolio" else 1.4 for k in sorted(set(kinds.values()))]))),
        "Series", names, states["markets"], "path_markets")
    lines = lines.add_params(zoom).properties(name="story_markets_0")
    monthly = growth.reindex(months, method="ffill")
    market_months = add_age(stamp.assign(**{f"s{i}": monthly[n].to_numpy() for i, n in enumerate(names)}))
    start_line = alt.Chart(pd.DataFrame({"y": [1.0]})).mark_rule(color=AXIS, strokeDash=[2, 3]).encode(y="y:Q")
    markets = alt.layer(lines, start_line, *milestone_layers(marks), *cursor_layers(
        market_months, x(), cursor, [*when, *age_tooltip(market_months),
                                     *[alt.Tooltip(f"s{i}:Q", title=n, format="$,.2f") for i, n in enumerate(names)]])
    ).properties(height=heights[0])

    # Wealth: the stacked balances.
    balances, colours = accounts(daily)
    balances = balances.reindex(months, method="ffill")
    wealth_months = add_age(stamp.assign(Total=balances.sum(axis=1).to_numpy(),
                                         **{f"a{i}": balances[a].to_numpy() for i, a in enumerate(colours)}))
    rules = milestone_layers(marks)[:1]
    areas = balances_chart(daily, x=x(), zoom=False, minExtent=wide).add_params(zoom).properties(name="story_wealth_0")
    wealth = alt.layer(areas, *rules, *cursor_layers(
        wealth_months, x(), cursor, [*when, *age_tooltip(wealth_months),
                                     alt.Tooltip("Total:Q", title="Total wealth", format="$,.0f"),
                                     *[alt.Tooltip(f"a{i}:Q", title=v[0], format="$,.0f")
                                       for i, v in enumerate(colours.values())]])
    ).properties(height=heights[1])

    # Money in and out: one bar per financial year, as wide as the year on the date axis.
    spans = {year: fy_span(year, first, last) for year in sorted(household["FY ending"].unique())}

    def placed(frame):
        return frame.assign(Start=frame["FY ending"].map(lambda y: spans[y][0]), End=frame["FY ending"].map(lambda y: spans[y][1]),
                            Mid=frame["FY ending"].map(lambda y: spans[y][2]), Period=frame["FY ending"].map(period_label))

    order, items = flow_items(household, additions)
    shown = placed(household.loc[household["Flow"].isin(order)])
    net = placed(household.drop_duplicates("FY ending")).assign(Flow=NET_LABEL)
    additions = placed(additions).assign(Flow=ADDED_LABEL)
    colour = flow_colour(items)
    bars, showing = hideable(alt.Chart(shown).mark_bar(stroke=SURFACE, strokeWidth=0.6, clip=True).encode(
        x=x("Start"), x2="End:T", y=alt.Y("sum(AUD):Q", title=("Average per" if group else "Per") + " year, today's dollars",
                                          axis=money_axis(minExtent=wide)),
        color=colour, order=alt.Order("Flow:N")), "Flow", items, states["flows"], "path_flows")
    bars = bars.add_params(zoom).properties(name="story_flows_0")
    net_line = alt.Chart(net).mark_line(color=INK, strokeWidth=2, clip=True, point=alt.OverlayMarkDef(color=INK, size=30)).encode(
        x=x("Mid"), y="Net change:Q", color=colour).transform_filter(showing)
    added = additions_layer(additions, x("Mid"), color=colour)
    table = shown.pivot_table(index="FY ending", columns="Flow", values="AUD", aggfunc="sum").reindex(columns=order).fillna(0.0)
    year_of = months.year + (months.month >= 7)
    by_year = net.set_index("FY ending")
    flow_months = stamp.assign(Period=[period_label(y) for y in year_of],
                               Net=by_year["Net change"].reindex(year_of).to_numpy(),
                               Added=additions.set_index("FY ending")["AUD"].reindex(year_of).to_numpy(),
                               **{f"f{i}": table[f].reindex(year_of).to_numpy() for i, f in enumerate(order)})
    flows = alt.layer(bars, zero_rule(), net_line, *([added.transform_filter(showing)] if added is not None else []),
                      *rules, *cursor_layers(flow_months, x(), cursor, [
                          alt.Tooltip("Period:N", title="Year"),
                          alt.Tooltip("Net:Q", title="Net change in wealth", format="$,.0f"),
                          *[alt.Tooltip(f"f{i}:Q", title=f, format="$,.0f") for i, f in enumerate(order)],
                          *([alt.Tooltip("Added:Q", title="Added to outside investments", format="$,.0f")]
                            if ADDED_LABEL in items else [])])
                      ).properties(height=heights[2])

    def titled(panel, text):
        return panel.properties(title=alt.Title(text, anchor="start", fontSize=13, fontWeight=600, color=INK, offset=6))

    markets = titled(markets, "Markets · medians across the group" if group else "Markets")
    wealth = titled(wealth, "Wealth · median balances" if group else "Wealth")
    flows = titled(flows, "Money in and out · average across the group" if group else "Money in and out")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # Altair notes that the shared selections are merged, as intended
        chart = (alt.vconcat(markets, wealth, flows, spacing=22)
                 .resolve_scale(x="shared", color="independent", size="independent"))
    panels = ("story_markets_", "story_wealth_", "story_flows_")
    return chart, {zoom.name: panels, cursor.name: ("cursor_targets_",), visible.name: panels[:1], showing.name: panels[2:],
                   "show_accounts_0": panels[1:2]}


def allocation_pie(weights, tickers):
    """Donut of one portfolio's weights: percentages on the slices, fixed colours per ticker."""
    colour = {t: SERIES[i % len(SERIES)] for i, t in enumerate(tickers)}
    labels = weights["Label"].tolist()
    scale = alt.Scale(domain=labels, range=[colour[t] for t in weights["Ticker"]])
    base = alt.Chart(weights).encode(theta=alt.Theta("Weight:Q", stack=True), order=alt.Order("Weight:Q", sort="descending"))
    slices = base.mark_arc(innerRadius=48, outerRadius=84, stroke=SURFACE, strokeWidth=2, cornerRadius=3).encode(
        color=alt.Color("Label:N", scale=scale, sort=labels, legend=None),
        tooltip=["Ticker:N", alt.Tooltip("Weight:Q", format=".1%"),
                 *([alt.Tooltip("Amount:Q", title="Value today", format="$,.0f")] if "Amount" in weights else [])])
    text = base.mark_text(radius=66, fontSize=12, fontWeight="bold", color="#ffffff").encode(
        text=alt.Text("Weight:Q", format=".0%"))
    return (slices + text).properties(height=190)


def ticker_colours(tickers):
    return {t: SERIES[i % len(SERIES)] for i, t in enumerate(tickers)}


def overlay_histogram(frame, field, title, *, series, log=False, percent=True, height=SHORT):
    """Several distributions on one axis: unstacked, translucent bars with a median rule each."""
    part = frame.loc[frame["Portfolio"].isin(series), ["Portfolio", field]].dropna().copy()
    value = field
    if log:
        part = part.loc[part[field] > 0]
        part["log_value"] = np.log10(part[field])
        value = "log_value"
    scale = alt.Scale(domain=list(series), range=[PORTFOLIO_COLOURS[n] for n in series])
    ticks = [np.log10(v) for v in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6)]
    axis = (alt.Axis(labelExpr="'$' + format(pow(10, datum.value), ',.0f')", title=title, values=ticks) if log
            else alt.Axis(format=".0%" if percent else ",.2f", title=title))
    bars, visible = toggle(alt.Chart(part).mark_bar(opacity=0.45, binSpacing=0).encode(
        x=alt.X(f"{value}:Q", bin=alt.Bin(maxbins=40), axis=axis),
        y=alt.Y("count():Q", stack=None, title="Paths"),
        color=alt.Color("Portfolio:N", scale=scale, legend=alt.Legend(symbolType="square")),
        tooltip=["Portfolio:N", alt.Tooltip("count():Q", title="Paths in this bar"),
                 *([] if log else [alt.Tooltip(f"{value}:Q", bin=alt.Bin(maxbins=40), title="Range",
                                               format=".1%" if percent else ",.2f")])]), "Portfolio", list(series), "portfolios")
    rules = alt.Chart(part).transform_filter(visible).mark_rule(strokeDash=[5, 3], strokeWidth=2).encode(
        x=f"median({value}):Q", color=alt.Color("Portfolio:N", scale=scale, legend=None),
        tooltip=["Portfolio:N", alt.Tooltip(f"median({field}):Q", title="Median",
                                            format="$,.0f" if log else ".1%" if percent else ",.2f")])
    return zoomable(alt.layer(bars, rules).properties(height=height))
