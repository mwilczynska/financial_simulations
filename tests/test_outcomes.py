from pathlib import Path
import tomllib

import pandas as pd
import pytest

from financial_simulations.reporting.palette import FLOW_COLOURS, STREAMLIT_THEME, TIER_COLOURS
from financial_simulations.retirement.flows import HOME_FLOWS, HOUSEHOLD, PROPERTY_FLOWS, TAXES, fold_tax_columns, fold_taxes
from financial_simulations.retirement.outcomes import (FULL_RATE_SHARE, TIERS, full_age_pension_by_year, group_spending,
                                                       path_groups, path_outcomes, state_shares, tier_shares, yearly_states)
from financial_simulations.retirement.plan import default_plan
from financial_simulations.rules.au.age_pension import maximum_rate
from financial_simulations.rules.au.parameters import load_ruleset


FULL = {2030: 30000.0, 2031: 30000.0, 2032: 30000.0}


def frames():
    """Five paths over three years, the last two retired: one per tier, and one depleted without a shortfall."""
    def path(number, status, pension, shortfall=(0.0, 0.0, 0.0), paid=(50.0, 40.0, 60.0), ending=100.0):
        rows = [{"Path": number, "FY ending": year, "Full retired year": year > 2030, "Spending paid": spend,
                 "Shortfall": short, "Age Pension": amount}
                for year, spend, short, amount in zip((2030, 2031, 2032), paid, shortfall, pension)]
        return {"Path": number, "Status": status, "Ending wealth": ending, "Lowest retired-year spending": min(paid[1:])}, rows

    built = [path(0, "funded", (0.0, 0.0, 0.0), ending=900.0),
             path(1, "funded", (0.0, 9000.0, 28000.0), ending=500.0),  # 28,000 is under 95% of 30,000
             path(2, "funded", (0.0, 12000.0, 28500.0), ending=300.0),  # 28,500 is exactly 95%: a full-rate year
             path(3, "depleted", (0.0, 30000.0, 30000.0), shortfall=(0.0, 5.0, 0.0), paid=(50.0, 35.0, 60.0), ending=0.0),
             path(4, "depleted", (0.0, 0.0, 0.0), ending=50.0),  # unpaid tax at the horizon, never a shortfall
             ({"Path": 5, "Status": "unsupported", "Ending wealth": float("nan")}, [])]
    return pd.DataFrame([b[0] for b in built]), pd.DataFrame([row for b in built for row in b[1]])


def test_each_path_takes_the_worst_tier_it_reached():
    paths, annual = frames()
    outcomes = path_outcomes(paths, annual, FULL).set_index("Path")
    assert list(outcomes.index) == [0, 1, 2, 3, 4]  # the unsupported path is left out
    assert outcomes["Outcome"].tolist() == [TIERS[0], TIERS[1], TIERS[2], TIERS[3], TIERS[3]]
    assert FULL_RATE_SHARE == 0.95
    assert outcomes["Full Age Pension years"].tolist() == [0, 0, 1, 2, 0]
    assert outcomes["Age Pension years"].tolist() == [0, 2, 2, 2, 0]
    # Spending paid averaged over the two full retired years; the shortfall year lowers path 3.
    assert outcomes["Average retired-year spending"].tolist() == [50.0, 50.0, 50.0, 47.5, 50.0]
    assert outcomes.loc[1, "Age Pension share of retired spending"] == pytest.approx(37000 / 100)
    assert tier_shares(outcomes.reset_index()).tolist() == [0.2, 0.2, 0.2, 0.4]


def test_yearly_states_hold_ruin_from_the_first_shortfall_and_sum_to_one():
    paths, annual = frames()
    outcomes = path_outcomes(paths, annual, FULL)
    states = yearly_states(outcomes, annual, FULL).set_index(["Path", "FY ending"])["State"]
    assert states.loc[3].tolist() == [TIERS[0], TIERS[3], TIERS[3]]  # ruin holds after the shortfall year
    assert states.loc[4].tolist() == [TIERS[0], TIERS[0], TIERS[3]]  # no shortfall: marked in its last year
    assert states.loc[2].tolist() == [TIERS[0], TIERS[1], TIERS[2]]
    shares = state_shares(states.reset_index())
    assert shares.groupby("FY ending")["Share"].sum().tolist() == pytest.approx([1.0, 1.0, 1.0])
    last = shares.loc[shares["FY ending"] == 2032].set_index("State")
    assert last["Share"].to_dict() == {TIERS[0]: 0.2, TIERS[1]: 0.2, TIERS[2]: 0.2, TIERS[3]: 0.4}
    assert last["Paths"].sum() == 5


def test_group_spending_covers_everyone_each_tier_and_the_ending_wealth_groups():
    paths, annual = frames()
    outcomes = path_outcomes(paths, annual, FULL)
    groups = path_groups(outcomes)
    assert list(groups)[:5] == ["All paths", *TIERS]
    assert groups["Ran out"] == [3, 4] and groups["Worst 10%"] == [3] and groups["Best 10%"] == [0]
    table = group_spending(outcomes, groups).set_index("Group")
    assert table.loc["All paths", "Paths"] == 5 and table.loc["All paths", "Median"] == 50.0
    assert table.loc["Ran out", "Median"] == pytest.approx(48.75) and table.loc["Ran out", "Share"] == 0.4
    assert table.loc["Ran out", "Kind"] == "Outcome" and table.loc["Worst 10%", "Kind"] == "Ending wealth"
    assert table.loc["Ran out", "P10"] <= table.loc["Ran out", "Median"] <= table.loc["Ran out", "P90"]


def test_full_age_pension_is_26_fortnights_of_the_projected_rate_in_todays_dollars():
    plan = default_plan()
    full = full_age_pension_by_year(plan)
    rules = load_ruleset("2026-27")
    assert full.loc[2027] == pytest.approx(26 * maximum_rate(rules))  # the opening year is not deflated
    # The basic rate follows wages and the supplements CPI, so in today's dollars the rate rises but by less than
    # the gap between wage growth and CPI.
    gap = (1 + plan["assumptions"]["wage_growth_annual"]) / (1 + plan["assumptions"]["cpi_annual"])
    assert full.loc[2027] < full.loc[2028] < full.loc[2027] * gap
    assert full.index.max() >= 2027 + plan["plan"]["years"]


def test_folded_taxes_keep_every_years_total():
    flows = pd.DataFrame([{"FY ending": year, "Flow": label, "AUD": sign * (i + 1.0) * year, "Opening": 1.0, "Closing": 2.0,
                           "Net change": 1.0, "Days": 250} for year in (2030, 2031)
                          for i, (_, label, sign) in enumerate(HOUSEHOLD)])
    folded = fold_taxes(flows)
    assert set(folded["Flow"]) == ({label for _, label, _ in HOUSEHOLD if label not in TAXES + PROPERTY_FLOWS + HOME_FLOWS}
                                   | {"Tax", "Investment property", "Home"})
    assert folded.groupby("FY ending")["AUD"].sum().tolist() == pytest.approx(flows.groupby("FY ending")["AUD"].sum().tolist())
    assert set(folded["Flow"]) <= set(FLOW_COLOURS)  # every drawn flow has a colour
    wide = pd.DataFrame({"Path": [0], "Flow: Spending": [-5.0], **{f"Flow: {name}": [-1.0] for name in TAXES}})
    assert fold_tax_columns(wide).to_dict("records") == [{"Path": 0, "Flow: Spending": -5.0, "Flow: Tax": -4.0}]
    wide = wide.assign(**{"Flow: Rent": [30.0], "Flow: Property costs": [-10.0]})
    assert fold_tax_columns(wide).to_dict("records") == [{"Path": 0, "Flow: Spending": -5.0, "Flow: Tax": -4.0,
                                                          "Flow: Investment property": 20.0}]


def test_the_streamlit_config_file_repeats_the_palette_theme():
    config = tomllib.loads((Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["theme"] == STREAMLIT_THEME
    assert list(TIER_COLOURS) == list(TIERS)
