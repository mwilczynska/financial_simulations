"""The stacked markets, wealth and money chart: a valid specification that stays cheap to hover (ADR 0056)."""

import json

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("altair")  # the app's packages are an optional install; without them this file is skipped
pytest.importorskip("streamlit")


def story():
    from financial_simulations.ui import charts

    days = pd.bdate_range("2026-07-01", "2030-06-28", name="Date")
    steps = np.arange(len(days))
    growth = pd.DataFrame({"Your portfolio": 1.0003 ** steps, "AAA": 1.0005 ** steps, "B.B": 0.9999 ** steps}, index=days)
    kinds = {"Your portfolio": "Portfolio", "AAA": "Ticker", "B.B": "Ticker"}
    colours = {"Your portfolio": "#111111", "AAA": "#2a78d6", "B.B": "#eb6834"}
    daily = pd.DataFrame({"cash": 1e4, "outside_investments": 2e5 + 50.0 * steps, "accumulation": 3e5, "pension": 0.0},
                         index=days)
    daily["total"] = daily.sum(axis=1)
    years = [2027, 2028, 2029, 2030]
    household = pd.DataFrame([{"FY ending": y, "Flow": flow, "AUD": amount, "Net change": 3e4}
                              for y in years for flow, amount in (("Take-home salary", 8e4), ("Spending", -5e4))])
    additions = pd.DataFrame({"FY ending": years, "AUD": 2e4})
    state = {"hidden": [], "count": 0}
    return charts.path_story(growth, kinds, colours, daily, household, additions, None, {"markets": state, "flows": state})


def test_story_chart_is_a_valid_specification_drawn_on_canvas():
    from financial_simulations.ui.theme import specification

    chart, views = story()
    spec = specification(chart, views, validate=True)  # the app skips Altair's validation for speed; this is the check
    assert spec["usermeta"] == {"embedOptions": {"renderer": "canvas"}}
    assert spec["config"]["legend"]["orient"] == "top"
    assert specification(chart, views) == spec


def test_story_chart_hover_uses_one_strip_per_month_and_sends_the_lines_once():
    from financial_simulations.ui.theme import specification

    spec = specification(*story())
    cursor = next(p for p in spec["params"] if p["name"].startswith("cursor_"))
    assert "nearest" not in cursor["select"] and len(cursor["views"]) == 3  # no nearest-point search in the browser
    for panel in spec["vconcat"]:
        targets = next(layer for layer in panel["layer"] if layer.get("name") in cursor["views"])
        assert targets["mark"]["type"] == "rect"
        strips = pd.DataFrame(spec["datasets"][targets["data"]["name"]])
        dates, starts, ends = (pd.to_datetime(strips[c]) for c in ("Date", "From", "To"))
        # The strips tile the plotted dates, and each month end sits inside its own strip.
        assert (starts.iloc[1:].to_numpy() == ends.iloc[:-1].to_numpy()).all()
        assert starts.iloc[0] == pd.Timestamp("2026-07-01") and ends.iloc[-1] == pd.Timestamp("2030-06-28")
        assert ((starts <= dates) & (dates <= ends)).all()
    lines = spec["vconcat"][0]["layer"][0]
    weekly = spec["datasets"][lines["data"]["name"]]
    assert set(weekly[0]) == {"Date", "g0", "g1", "g2"}  # one row per week; the browser folds it into series
    assert len(weekly) < 4 * 53 + 2
    assert json.loads(lines["transform"][1]["calculate"].split("[datum")[0]) == {"g0": "Your portfolio", "g1": "AAA",
                                                                                 "g2": "B.B"}
