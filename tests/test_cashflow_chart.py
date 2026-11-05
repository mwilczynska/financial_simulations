"""Cash-flow filtering must not change accounting values or leave lines fixing the scale."""

import pandas as pd
import pytest

alt = pytest.importorskip("altair")

from financial_simulations.ui.cashflow import ADDED_LABEL, NET_LABEL, cash_flow_chart


def test_focus_filters_all_layers_without_recomputing_total_or_fixing_scale():
    frame = pd.DataFrame({"FY ending": [2030, 2030, 2030], "Period": ["2030"] * 3,
                          "Flow": ["Spending", "Age Pension", "Investment returns"],
                          "Median": [-50, 10, 100], "P25": [-60, 0, 30], "P75": [-40, 20, 200]})
    # A separately computed median total deliberately differs from the sum of medians (60).
    net = pd.DataFrame({"FY ending": [2030], "Period": ["2030"], "Value": [77], "P25": [20], "P75": [130]})
    additions = pd.DataFrame({"FY ending": [2030], "Period": ["2030"], "AUD": [5]})
    colours = {"Spending": "#b76a42", "Age Pension": "#d08c2f", "Investment returns": "#9a8a2e"}
    chart = cash_flow_chart(frame, net, additions, colours, alt.X("FY ending:Q"), "Median per year",
                            {"hidden": ["Investment returns", NET_LABEL, ADDED_LABEL], "count": 1},
                            "focus", value="Median", spread=True)
    spec = chart.to_dict(validate=True)
    selection = spec["params"][0]
    assert selection["bind"] == "legend"
    assert selection["value"] == [{"Flow": "Spending"}, {"Flow": "Age Pension"}]
    # Bars, total, spread and additions all leave the y scale when hidden; only the zero rule is unfiltered.
    for index in (0, 2, 3, 4):
        layer = spec["layer"][index]
        assert layer["transform"] == [{"filter": {"param": selection["name"], "empty": False}}]
        assert "domain" not in layer["encoding"]["y"].get("scale", {})
    total_rows = spec["datasets"][spec["layer"][2]["data"]["name"]]
    assert total_rows[0]["Value"] == 77
    assert "Flow" not in net  # chart construction does not mutate the report frames


def test_hide_all_keeps_legend_and_uses_nonempty_placeholder_selection():
    frame = pd.DataFrame({"FY ending": [2030], "Period": ["2030"], "Flow": ["Spending"], "AUD": [-50]})
    net = pd.DataFrame({"FY ending": [2030], "Period": ["2030"], "Value": [-50]})
    additions = pd.DataFrame(columns=["FY ending", "Period", "AUD"])
    spec = cash_flow_chart(frame, net, additions, {"Spending": "#b76a42"}, alt.X("FY ending:Q"), "Annual",
                            {"hidden": ["Spending", NET_LABEL], "count": 2}, "empty").to_dict(validate=True)
    assert spec["params"][0]["value"] == [{"Flow": "(none)"}]
    assert spec["layer"][0]["encoding"]["color"]["scale"]["domain"] == ["Spending", NET_LABEL]
    assert len(spec["layer"]) == 3
