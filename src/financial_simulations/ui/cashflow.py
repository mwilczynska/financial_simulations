"""Legend-filtered cash-flow charts; reporting values are supplied by the ledger UI."""

import json

import altair as alt
import pandas as pd


NET_LABEL = "Net change in wealth (line)"
ADDED_LABEL = "Added to outside investments (line)"
NET_COLOUR = "#19353a"
ADDED_COLOUR = "#0b7a8a"
FOCUS_FLOWS = ("Spending", "Age Pension", "Income tax", "Division 296 tax")


def flow_legend():
    """Keep the full ledger labels on desktop and concise, unclipped labels on phones."""
    short = {"Take-home salary": "Salary", "Super contributions": "Super contrib.",
             "Investment returns": "Returns", "Interest on cash": "Cash interest",
             "Contributions tax": "Contrib. tax", "Super fund tax": "Super tax",
             "Division 296 tax": "Div. 296 tax", NET_LABEL: "Net wealth change",
             ADDED_LABEL: "Savings invested"}
    labels = json.dumps(short)
    return alt.Legend(orient="bottom", title=None, columnPadding=8,
                      columns=alt.ExprRef(expr="width < 500 ? 2 : 4"),
                      labelLimit=alt.ExprRef(expr="width < 500 ? 95 : 210"),
                      labelExpr=f"width < 500 ? ({labels}[datum.label] || datum.label) : datum.label")


def flow_items(frame, additions, colours):
    return ([f for f in colours if f in set(frame["Flow"])] + [NET_LABEL]
            + ([ADDED_LABEL] if not additions.empty and additions["AUD"].abs().gt(1e-6).any() else []))


def cash_flow_chart(frame, net, additions, colours, x, title, state, name, *, value="AUD", spread=False):
    """Filter bars and all auxiliary lines together, then let Vega refit the y scale.

    ``frame`` contains one value per flow/year. ``net`` has a Value column and
    optionally P25/P75; additions has AUD. Neither medians nor means are
    recomputed here. Net change remains the total, never a sum of visible items.
    """
    items = flow_items(frame, additions, colours)
    palette = {**colours, NET_LABEL: NET_COLOUR, ADDED_LABEL: ADDED_COLOUR}
    colour = alt.Color("Flow:N", sort=items,
                       scale=alt.Scale(domain=items, range=[palette[f] for f in items]),
                       legend=flow_legend())
    shown = [item for item in items if item not in state["hidden"]] or ["(none)"]
    visible = alt.selection_point(name=f"show_{name}_{state['count']}", fields=["Flow"],
                                  bind="legend", toggle="true", empty=False, clear=False,
                                  value=[{"Flow": item} for item in shown])
    tooltip = [alt.Tooltip("Period:N", title="Year"), "Flow:N", alt.Tooltip(f"{value}:Q", format="$,.0f")]
    if spread:
        tooltip += [alt.Tooltip("P25:Q", title="25th percentile", format="$,.0f"),
                    alt.Tooltip("P75:Q", title="75th percentile", format="$,.0f")]
    bars = alt.Chart(frame).mark_bar(size=14).encode(
        x=x, y=alt.Y(f"sum({value}):Q", title=title, axis=alt.Axis(format="$,.0f")),
        color=colour, order="Flow:N", tooltip=tooltip).add_params(visible).transform_filter(visible)
    net = net.assign(Flow=NET_LABEL)
    net_tooltip = [alt.Tooltip("Period:N", title="Year"),
                   alt.Tooltip("Value:Q", title="Net change in wealth", format="$,.0f")]
    for field in ("Wealth at start of year", "Wealth at end of year"):
        if field in net:
            net_tooltip.append(alt.Tooltip(f"{field}:Q", format="$,.0f"))
    line = alt.Chart(net).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=30)).encode(
        x=x, y="Value:Q", color=colour, tooltip=net_tooltip).transform_filter(visible)
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#8a9892", strokeWidth=.7).encode(y="y:Q")
    layers = [bars, zero, line]
    if spread:
        layers.append(alt.Chart(net).mark_rule(strokeWidth=1.5).encode(
            x=x, y="P25:Q", y2="P75:Q", color=colour,
            tooltip=[*net_tooltip, alt.Tooltip("P25:Q", format="$,.0f"),
                     alt.Tooltip("P75:Q", format="$,.0f")]).transform_filter(visible))
    if ADDED_LABEL in items:
        layers.append(alt.Chart(additions.assign(Flow=ADDED_LABEL)).mark_line(
            strokeDash=[6, 3], strokeWidth=2, point=alt.OverlayMarkDef(shape="square", size=35)).encode(
                x=x, y="AUD:Q", color=colour,
                tooltip=[alt.Tooltip("Period:N", title="Year"),
                         alt.Tooltip("AUD:Q", title="Added to outside investments", format="$,.0f")]
            ).transform_filter(visible))
    return alt.layer(*layers).properties(height=460)
