"""Presentation tokens and chart styling for the local planner.

No simulation values or chart domains are changed here. Semantic series colours
remain shared with the PNG reports; height depends on the chart's role.
"""

import altair as alt
import streamlit as st


CSS = """
<style>
/* Keep native controls, keyboard navigation and sidebar collapse behaviour. */
.stMainBlockContainer {max-width: 1440px; padding: 2.4rem 2.8rem 4rem;}
[data-testid="stSidebar"] {border-right: 1px solid #dce3dd;}
[data-testid="stSidebarUserContent"] {padding-top: 2rem;}
h1 {font-size: 2rem !important; letter-spacing: -.045em; font-weight: 650 !important;}
h2 {font-size: 1.4rem !important; letter-spacing: -.025em; padding-top: 1.1rem !important;}
h3 {font-size: 1.12rem !important; letter-spacing: -.015em;}
[data-testid="stCaptionContainer"] {color: #61716b; opacity: 1; line-height: 1.55;}
[data-testid="stMetric"] {border-top: 1px solid #dce3dd; padding: .85rem 0 .4rem;}
[data-testid="stMetricValue"] {font-size: 1.75rem; letter-spacing: -.04em; font-variant-numeric: tabular-nums;}
[data-testid="stMetricLabel"] p {font-size: .8rem; color: #61716b; white-space: normal;}
[role="tablist"] {gap: 1.5rem; border-bottom: 1px solid #dce3dd;}
[role="tab"] {padding: .6rem .1rem; transition: color 140ms ease;}
[role="tab"][aria-selected="true"] {font-weight: 650;}
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button {
    min-height: 2.65rem; transition: background-color 140ms ease, border-color 140ms ease;
}
[data-testid="stExpander"] {border-color: #dce3dd; box-shadow: none;}
[data-testid="stExpander"] summary {font-size: .88rem;}
[data-testid="stCheckbox"] label p {white-space: normal;}
[data-testid="stNumberInput"] input {font-variant-numeric: tabular-nums;}
[data-testid="stVegaLiteChart"] {padding: .5rem 0;}
.report-jumps {display: flex; flex-wrap: wrap; gap: .3rem 1.3rem; padding: .75rem 0;
    border-bottom: 1px solid #dce3dd; margin-bottom: .25rem;}
[data-testid="stElementContainer"]:has(> .stHtml > .report-jumps) {
    position: sticky; top: 3.75rem; z-index: 10; background: #fcfcfa;
}
.report-jumps a {font-size: .85rem; color: #405650; text-decoration: none; padding: .25rem 0;
    border-bottom: 2px solid transparent; transition: color 140ms ease, border-color 140ms ease;}
.report-jumps a:hover, .report-jumps a:focus-visible {color: #126a63; border-bottom-color: #126a63;}
h2, h3 {scroll-margin-top: 8.5rem !important;}
[data-testid="stButtonGroup"] button {font-size: .85rem;}
.planner-eyebrow {font-size: .7rem; letter-spacing: .16em; font-weight: 700; color: #126a63; margin: 0 0 .4rem;}
@media (max-width: 800px) {
    .stMainBlockContainer {padding: 3rem 1rem 3rem;}
    [role="tablist"] {gap: 1rem;}
    [data-testid="stMetricValue"] {font-size: 1.5rem;}
    h2, h3 {scroll-margin-top: 11rem !important;}
}
@media (prefers-reduced-motion: reduce) {
    [role="tab"], [data-testid="stButton"] button, [data-testid="stDownloadButton"] button,
    .report-jumps a {transition: none;}
}
</style>
"""


def install_design():
    """Apply the same restrained typography to widgets and all Vega-Lite plots."""
    st.html(CSS)
    alt.theme.register("retirement_planner", enable=True)(lambda: {
        "config": {
            "background": "#fcfcfa",
            "font": "Segoe UI, sans-serif",
            "view": {"stroke": None},
            "axis": {
                "labelColor": "#61716b", "titleColor": "#405650", "labelFontSize": 11,
                "titleFontSize": 11, "titleFontWeight": "normal", "titlePadding": 14,
                "domain": False, "ticks": False, "gridColor": "#dce3dd", "gridOpacity": 0.55,
                "labelPadding": 8, "labelLimit": 140,
            },
            "axisX": {"grid": False},
            "legend": {
                "orient": "bottom", "title": None, "labelColor": "#405650", "labelFontSize": 11,
                "padding": 12, "symbolStrokeWidth": 3, "labelLimit": 220,
            },
            "title": {"anchor": "start", "color": "#243c3b", "fontSize": 13, "offset": 18},
            "line": {"strokeWidth": 2},
        }
    })


def show_chart(chart, **kwargs):
    """Use our theme instead of Streamlit's automatic chart theme."""
    st.altair_chart(chart, theme=None, **kwargs)
