"""The app's look: page styles, the chart configuration and the small HTML pieces every page shares (ADR 0047).

Colours come from ``reporting.palette`` so the interactive charts and the PNG review plots match. Charts are drawn
through ``draw``, which applies one configuration (type, grid, axes, legend) instead of Streamlit's chart theme.
"""

from functools import lru_cache
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from financial_simulations.reporting.palette import (ACCENT, AXIS, GRID, INK, INK_SECONDARY, MUTED, NEUTRAL, PAGE, SURFACE,
                                                     TIER_COLOURS)


FONT = '"Source Sans", "Source Sans 3", "Source Sans Pro", system-ui, -apple-system, "Segoe UI", sans-serif'
# Chart heights: one size per role, so pages keep a steady rhythm.
TALL, MEDIUM, SHORT = 430, 340, 250

CSS = f"""
<style>
  [data-testid="stHeader"] {{ display: none; }}
  [data-testid="stMainBlockContainer"] {{ max-width: 1320px; padding: 0.75rem 2rem 4rem; }}
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {{ display: none; }}

  /* The bar that stays on screen: brand, pages, plan menu and Run. */
  /* Streamlit wraps the container, and an element only sticks inside its parent, so the wrapper is what sticks. */
  [data-testid="stLayoutWrapper"]:has(> .st-key-topbar) {{ position: sticky; top: 0; z-index: 99; background: {PAGE};
                                                          border-bottom: 1px solid {GRID}; }}
  .st-key-topbar {{ padding: 0.55rem 0 0.6rem; }}
  .brand {{ font-weight: 700; font-size: 1.08rem; letter-spacing: -0.01em; color: {INK}; line-height: 1.15; }}
  .brand small {{ display: block; font-weight: 400; font-size: 0.8rem; color: {INK_SECONDARY}; white-space: nowrap;
                  overflow: hidden; text-overflow: ellipsis; }}

  /* Cards: bordered containers and metric tiles sit on white, above the page plane. */
  [class*="st-key-card_"], [data-testid="stMetric"] {{ background: {SURFACE}; border-radius: 0.75rem; }}
  [class*="st-key-card_"] {{ border: 1px solid {GRID}; padding: 1.05rem 1.2rem 1.15rem;
                             box-shadow: 0 1px 2px rgba(11, 11, 11, 0.04); }}
  [data-testid="stMetric"] {{ border: 1px solid {GRID}; padding: 0.7rem 0.9rem; }}
  [data-testid="stMetricLabel"] p {{ color: {INK_SECONDARY}; font-size: 0.82rem; }}
  [data-testid="stMetricValue"] {{ letter-spacing: -0.01em; }}

  /* Room for the y axis of a stacked chart, whose panels are each given the container's full width. */
  .st-key-pathstorychart {{ padding-right: 104px; }}

  /* A tab's content is drawn only once it is open, so for a moment after a click its panel is empty. Without a
     minimum height the page would shorten and the browser would scroll up; with it the page stays where it was. */
  [data-testid="stTabPanel"] {{ min-height: 100vh; }}

  h1, h2, h3 {{ letter-spacing: -0.015em; }}
  .page-title {{ margin: 0.35rem 0 0.9rem; }}
  .page-title h1 {{ font-size: 1.6rem; font-weight: 650; margin: 0; padding: 0; color: {INK}; }}
  .page-title p {{ margin: 0.15rem 0 0; color: {INK_SECONDARY}; font-size: 0.95rem; max-width: 62rem; }}
  .chart-title {{ margin: 0 0 0.35rem; }}
  .chart-title b {{ display: block; font-size: 1.02rem; font-weight: 600; color: {INK}; }}
  .chart-title span {{ display: block; font-size: 0.86rem; color: {INK_SECONDARY}; max-width: 60rem; }}
  .key {{ display: flex; flex-wrap: wrap; gap: 0.2rem 1.1rem; font-size: 0.84rem; color: {INK_SECONDARY};
          margin: 0.1rem 0 0.35rem; }}
  .key i {{ display: inline-block; width: 0.72rem; height: 0.72rem; border-radius: 3px; margin-right: 0.4rem;
            vertical-align: -1px; }}
  .key i.line {{ height: 3px; width: 1.1rem; border-radius: 2px; vertical-align: 3px; }}

  /* The outcome headline: one bar split into the four tiers, and a tile for each. */
  .tier-bar {{ display: flex; gap: 2px; height: 28px; margin: 0.2rem 0 0.9rem; }}
  .tier-bar div {{ border-radius: 4px; min-width: 3px; color: #fff; font-size: 0.8rem; font-weight: 600;
                   padding: 0 0.5rem; line-height: 28px; overflow: hidden; white-space: nowrap; }}
  .tiers {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.8rem; }}
  .tier {{ border-top: 3px solid var(--c); padding-top: 0.55rem; }}
  .tier .name {{ font-size: 0.86rem; font-weight: 600; color: {INK}; }}
  .tier .value {{ font-size: 2.1rem; font-weight: 650; letter-spacing: -0.02em; color: {INK}; line-height: 1.15; }}
  .tier .note {{ font-size: 0.83rem; color: {INK_SECONDARY}; line-height: 1.35; }}
  .tier .count {{ font-size: 0.8rem; color: {MUTED}; }}
  @media (max-width: 760px) {{ .tiers {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}

  .empty {{ text-align: center; padding: 3.2rem 1rem 1.2rem; color: {INK_SECONDARY}; }}
  .empty b {{ display: block; font-size: 1.2rem; color: {INK}; margin-bottom: 0.3rem; }}
  .status {{ font-size: 0.8rem; color: {INK_SECONDARY}; text-align: right; line-height: 1.25; }}
  .status .dot {{ display: inline-block; width: 0.5rem; height: 0.5rem; border-radius: 50%; margin-right: 0.35rem; }}

  [data-testid="stCaptionContainer"] {{ color: {INK_SECONDARY}; }}
  [data-testid="stExpander"] details {{ background: {SURFACE}; }}
  [data-baseweb="tab-list"] {{ gap: 0.4rem; }}
  [data-testid="stVegaLiteChart"] {{ width: 100%; }}

  /* A chart's hover box: Streamlit stacks each figure's name above its value, which makes a long box that runs off
     the screen. Name and value share a line here, so the box is half the height. */
  #vg-tooltip-element.vg-tooltip {{ max-width: 34rem; }}
  #vg-tooltip-element.vg-tooltip td.key, #vg-tooltip-element.vg-tooltip td.value {{
    display: table-cell; width: auto; max-width: none; white-space: nowrap; font-size: 0.78rem; line-height: 1.25;
    padding-top: 1px; padding-bottom: 1px; vertical-align: baseline; }}
  #vg-tooltip-element.vg-tooltip td.key {{ text-align: left; padding-right: 0.9rem; }}
  #vg-tooltip-element.vg-tooltip td.value {{ text-align: right; font-variant-numeric: tabular-nums; }}
</style>
"""


def apply_styles():
    st.html(CSS)


def card(name):
    """A white, bordered container. ``name`` must be unique on the page."""
    return st.container(key=f"card_{name}")


def page_title(title, subtitle=None):
    st.html(f"<div class='page-title'><h1>{escape(title)}</h1>" + (f"<p>{subtitle}</p>" if subtitle else "") + "</div>")


def chart_title(title, subtitle=None):
    st.html(f"<div class='chart-title'><b>{escape(title)}</b>" + (f"<span>{subtitle}</span>" if subtitle else "") + "</div>")


def legend(items):
    """A chart key: ``(label, colour)`` swatches, or ``(label, colour, "line")`` for a line."""
    parts = []
    for label, colour, *kind in items:
        parts.append(f"<span><i class='{kind[0] if kind else ''}' style='background:{colour}'></i>{escape(label)}</span>")
    st.html(f"<div class='key'>{''.join(parts)}</div>")


def explain(text, label="How to read this"):
    """The long explanation of a chart, folded away under it."""
    with st.expander(label, icon=":material/help:"):
        st.markdown(text)


def empty_state(title, text):
    st.html(f"<div class='empty'><b>{escape(title)}</b>{text}</div>")


def tier_headline(shares, counts, notes):
    """The four outcome tiers as one split bar and a tile each; ``shares``, ``counts`` and ``notes`` are by tier."""
    bar = "".join(
        f"<div title='{escape(tier)}: {shares[tier]:.1%}' style='flex:{max(shares[tier], 0.0001):.4f} 1 0; "
        f"background:{TIER_COLOURS[tier]}'>{f'{shares[tier]:.0%}' if shares[tier] >= 0.06 else ''}</div>"
        for tier in shares.index if shares[tier] > 0)
    tiles = "".join(
        f"<div class='tier' style='--c:{TIER_COLOURS[tier]}'><div class='name'>{escape(tier)}</div>"
        f"<div class='value'>{shares[tier]:.1%}</div><div class='note'>{notes[tier]}</div>"
        f"<div class='count'>{counts[tier]:,} of {sum(counts.values()):,} paths</div></div>" for tier in shares.index)
    st.html(f"<div class='tier-bar'>{bar}</div><div class='tiers'>{tiles}</div>")


def configure(chart):
    """The one chart configuration: quiet axes and grid, the app's type, a legend above the plot."""
    return (chart.configure(background="transparent", font=FONT, padding={"left": 2, "right": 6, "top": 4, "bottom": 2})
            .configure_view(stroke=None)
            .configure_axis(labelColor=MUTED, titleColor=INK_SECONDARY, labelFontSize=12, titleFontSize=12,
                            titleFontWeight="normal", titlePadding=8, gridColor=GRID, gridOpacity=1, domainColor=AXIS,
                            tickColor=AXIS, tickSize=4, labelPadding=5)
            .configure_axisX(grid=False)
            .configure_axisY(domain=False, ticks=False)
            .configure_legend(orient="top", direction="horizontal", title=None, labelColor=INK_SECONDARY, labelFontSize=12,
                              symbolSize=110, symbolStrokeWidth=0, padding=0, offset=10, labelLimit=260, columnPadding=14)
            .configure_line(strokeWidth=2, strokeCap="round", strokeJoin="round")
            .configure_text(font=FONT, color=INK_SECONDARY))


def draw(chart, views=None, **options):
    """Show a chart. ``views`` maps a selection's name to the name prefixes of the views it belongs to, replacing
    Altair's own lists (see ``charts.path_story``)."""
    if views is None:
        st.altair_chart(configure(chart), theme=None, width="stretch", **options)
        return
    draw_specification(specification(chart, views), **options)


@lru_cache(maxsize=1)
def configuration():
    """The chart configuration as a plain dictionary, worked out once."""
    return configure(alt.Chart(pd.DataFrame({"x": [0]})).mark_point()).to_dict()["config"]


def specification(chart, views, validate=False):
    """A chart as a Vega-Lite dictionary with the app's configuration and each selection's views (``with_views``).

    Speed: the configuration is added to the dictionary, because each Altair ``configure_*`` call copies the whole
    chart, and Altair's schema validation is skipped unless ``validate`` is set (a test validates the stacked chart).
    """
    with alt.data_transformers.disable_max_rows():  # as st.altair_chart does: a 40-year weekly line is over the limit
        spec = chart.to_dict(validate=validate)
    spec["config"] = configuration()
    return with_views(spec, views)


def draw_specification(spec, **options):
    st.vega_lite_chart(spec, theme=None, width="stretch", **options)


def with_views(spec, views):
    """A chart specification with each named selection attached to the views whose names start with its prefixes."""
    names = []

    def walk(node):
        if isinstance(node, dict):
            if "mark" in node and "name" in node:
                names.append(node["name"])
            for part in ("layer", "vconcat", "hconcat", "concat"):
                for child in node.get(part, []):
                    walk(child)

    walk(spec)
    for param in spec.get("params", []):
        if param["name"] in views:
            param["views"] = [n for n in names if n.startswith(tuple(views[param["name"]]))]
    return spec


__all__ = ["ACCENT", "NEUTRAL", "TALL", "MEDIUM", "SHORT", "apply_styles", "card", "chart_title", "configure", "draw",
           "draw_specification", "specification", "empty_state", "explain", "legend", "page_title", "tier_headline"]
