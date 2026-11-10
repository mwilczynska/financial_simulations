"""Session helpers and number formatting shared by every page of the browser app."""

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from financial_simulations.data.plan_markets import load_plan_markets


PLANS_DIR = Path("plans")
MONEY = "$%,d"


def key(name):
    # Widgets are re-created from the plan whenever a new plan is loaded.
    return f"{name}__{st.session_state.version}"


def sticky(name, default):
    """A widget key whose value survives the runs that do not draw the widget.

    Only the open page and tab are drawn, and Streamlit forgets a widget's value on any run that does not draw it.
    ``keep_sticky`` re-assigns every registered value at the top of each run, which makes it ordinary session state.
    The starting value is set here, never passed to the widget, so Streamlit does not warn that it was set twice.
    """
    widget = key(name)
    st.session_state.setdefault("_sticky", set()).add(widget)
    if widget not in st.session_state:
        st.session_state[widget] = default
    return widget


def sticky_choice(name, options, default=None):
    """``sticky`` for a widget that picks from ``options``: a stored value no longer offered falls back."""
    options = list(options)
    widget = sticky(name, default if default in options else options[0])
    if st.session_state[widget] not in options:
        st.session_state[widget] = default if default in options else options[0]
    return widget


# Widgets with fixed keys whose choice must outlive the page that draws them.
KEPT = ("calculation_cores", "plan_tabs")


def keep_sticky():
    for widget in KEPT:
        if widget in st.session_state:
            st.session_state[widget] = st.session_state[widget]
    for widget in list(st.session_state.get("_sticky", ())):
        if widget in st.session_state:
            st.session_state[widget] = st.session_state[widget]
        else:
            st.session_state["_sticky"].discard(widget)


def result_key(run, name):
    """A key for one strategy's results: each compared strategy keeps its own choices (its paths differ)."""
    return name if len(run.strategies or {}) <= 1 else f"{name}_{run.rule}"


def load_into_session(plan, message):
    st.session_state.plan = plan
    st.session_state.version += 1
    st.session_state.result = None
    st.session_state.flash = message
    st.session_state.page = "Plan"
    st.session_state.pop("_sticky", None)


def cached_market(tickers):
    cache = st.session_state.setdefault("market_cache", {})
    if tickers not in cache:
        cache[tickers] = load_plan_markets(tickers)
    return cache[tickers]


def calculation_cores():
    """The *Calculation cores* choice: a number of worker processes, or ``None`` for automatic."""
    chosen = st.session_state.get("calculation_cores")
    return chosen if isinstance(chosen, int) and chosen > 0 else None


def compact(value):
    if value is None or not np.isfinite(value):
        return "–"
    return f"${value / 1e6:,.2f}m" if abs(value) >= 1e6 else f"${value:,.0f}"


def dollars(value):
    """``compact`` for Markdown: two unescaped dollar signs in one string would render as maths."""
    return compact(value).replace("$", "\\$")


def share(value, digits=1):
    return "–" if value is None or not np.isfinite(value) else f"{value:.{digits}%}"


def affected(values):
    """A measure that is zero on most paths: the share of paths above zero and the median among those paths.

    The median over every path is often exactly $0 and hides the paths where it matters (ADR 0040).
    """
    values = pd.Series(values, dtype=float).dropna()
    hit = values.loc[values > 0]
    if values.empty:
        return "–"
    return "None" if hit.empty else f"{share(len(hit) / len(values))} · {compact(float(hit.median()))}"


def ordinal(value):
    n = int(round(value))
    n = min(max(n, 1), 99)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def plural(count, noun):
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def fit(frame, most=None):
    """A table height that shows every row without an inner scroll bar (up to ``most`` rows)."""
    return 38 + 35 * (len(frame) if most is None else min(len(frame), most))


def money_column(label, help=None):
    return st.column_config.NumberColumn(label, format=MONEY, help=help)


def percent_column(label, help=None, digits=1):
    return st.column_config.NumberColumn(label, format=f"%.{digits}f%%", help=help)


def percentile_table(frame, measures):
    """One row per measure, columns 5th to 95th percentile across paths, each formatted for its unit."""
    rows = []
    for label, (field, kind) in measures.items():
        values = frame[field].dropna() if field in frame else pd.Series(dtype=float)
        if values.empty:
            continue
        q = values.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).to_numpy()
        fmt = compact if kind == "money" else share if kind == "percent" else (lambda v: f"{v:,.1f}")
        rows.append({"Measure": label, **{name: fmt(v) for name, v in zip(("5th", "25th", "Median", "75th", "95th"), q)}})
    return pd.DataFrame(rows)
