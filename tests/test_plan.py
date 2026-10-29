from datetime import date
import json
from pathlib import Path
import tempfile

import pytest

from financial_simulations.data.plan_markets import load_plan_markets
from financial_simulations.retirement.analysis import analyse_portfolios, target_observations
from financial_simulations.retirement.plan import (PlanError, build_inputs, default_plan, horizon, load_plan_text,
                                                   normalize_plan, plan_to_json, plan_to_toml)
from financial_simulations.retirement.run_plan import run_plan


def quick_plan():
    plan = default_plan()
    plan["market"]["paths"] = 16
    plan["market"]["retirement_paths"] = 1
    return plan


def test_example_plan_round_trips_through_toml_and_json():
    plan = default_plan()
    assert load_plan_text(plan_to_toml(plan), "plan.toml") == plan
    assert load_plan_text(plan_to_json(plan), "plan.json") == plan
    assert json.loads(plan_to_json(plan))["schema_version"] == 2
    assert plan["assets"] == ["USLCAP3x", "ITT3x", "GOLDPM2x", "COMM", "GLSTOCK"]
    assert plan["outside"]["weights"] == {"USLCAP3x": 0.4, "ITT3x": 0.2, "GOLDPM2x": 0.2, "COMM": 0.2}
    assert plan["super"]["weights"] == {"GLSTOCK": 1.0}


def test_validation_reports_every_problem_with_its_field_path():
    plan = default_plan()
    plan["person"]["date_of_birth"] = "15/09/1972"
    plan["outside"]["weights"] = {"USLCAP3x": 0.4, "ITT3x": 0.4}
    plan["super"]["weights"] = {"SPY": 1.0}
    plan["assets"].append("COMM")
    plan["extra"] = {}
    with pytest.raises(PlanError) as error:
        normalize_plan(plan)
    problems = " | ".join(error.value.problems)
    for expected in ("person.date_of_birth: must be a date", "outside.weights: must sum to 1",
                     "super.weights.SPY: ticker is not selected", "assets[5]: duplicate ticker", "extra: unknown section"):
        assert expected in problems
    with pytest.raises(PlanError, match="could not be read as TOML"):
        load_plan_text("[plan\nname=", "broken.toml")
    old = default_plan()
    old["schema_version"] = 1
    with pytest.raises(PlanError, match="reviewed conversion"):
        normalize_plan(old)


def test_minimal_plan_gets_documented_defaults():
    plan = normalize_plan({"person": {"date_of_birth": "1980-01-01"}, "assets": ["USLCAP"],
                           "outside": {"weights": {"USLCAP": 1.0}}, "super": {"weights": {"USLCAP": 1.0}}})
    assert plan["plan"]["start_date"] == "2026-07-01" and plan["plan"]["years"] == 10
    assert plan["assumptions"] == {"cpi_annual": 0.025, "wage_growth_annual": 0.035, "planning_age": 95}
    assert plan["outside"]["investment_balance"] == 0 and plan["pension"]["start_age"] == 0
    assert plan["market"]["block_length"] == 63


def test_build_inputs_maps_portfolios_and_derived_income_onto_ledger(processed_fixture):
    plan = default_plan()
    market = load_plan_markets(plan["assets"], processed_fixture)
    path, scenario, years, notes = build_inputs(plan, market=market)
    assert path.currency == "AUD" and path.assets == tuple(plan["assets"])
    assert scenario.person.retirement_date == date(2027, 9, 15)
    assert scenario.employment.salary_sacrifice_per_payday == pytest.approx(400)
    assert scenario.super_units["GLSTOCK"] == pytest.approx(650000)
    assert scenario.outside_parcels[0].cost_base == pytest.approx(132000)
    assert scenario.income["ITT3x"].annual_yield == pytest.approx(market.income_yields["ITT3x"])
    assert scenario.income["ITT3x"].franked_fraction == 0
    assert scenario.pension.commence == date(2032, 9, 15)
    assert list(years)[0] == "2026-27" and list(years)[-1] == "2035-36"
    assert "AUD proxy" in notes[0]


def test_horizon_stops_before_age_pension_year(processed_fixture):
    plan = default_plan()
    plan["person"]["date_of_birth"] = "1962-03-01"
    plan["pension"]["start_age"] = 0
    start, end, shortened = horizon(plan)
    assert end == date(2028, 6, 30) and shortened
    plan["person"]["date_of_birth"] = "1959-01-01"
    market = load_plan_markets(plan["assets"], processed_fixture)
    with pytest.raises(PlanError, match="Age Pension age"):
        build_inputs(plan, market=market)


def test_run_plan_writes_portfolio_and_retirement_reports(tmp_path, processed_fixture):
    plan = quick_plan()
    market = load_plan_markets(plan["assets"], processed_fixture)
    run = run_plan(plan, tmp_path, market=market)
    assert run.folder == tmp_path / "example-early-retirement"
    assert (run.folder / "portfolio_future.png").exists()
    assert (run.folder / "retirement_range.png").exists()
    assert (run.folder / "retirement_paths.csv").exists()
    assert (run.folder / "asset_summary.csv").exists()
    assert (run.folder / "manifest.json").exists()
    assert load_plan_text((run.folder / "plan.toml").read_text(encoding="utf-8")) == plan
    assert len(run.portfolios.outcomes) == 48  # 16 shared paths for each portfolio and their combination
    assert len(run.retirement_paths) == 1
    flows = [c for c in run.retirement_annual.columns if c.startswith("Flow: ")]
    assert "Flow: Spending" in flows and "Flow: Investment returns" in flows
    yearly = run.retirement_annual
    assert (yearly[flows].sum(axis=1) - yearly["Net change in wealth"]).abs().max() < 1e-4
    assert not list(run.folder.glob("*.pdf"))


def test_portfolios_keep_shared_daily_draws_but_reflect_distinct_weights(processed_fixture):
    plan = quick_plan()
    plan["plan"]["years"] = 1
    plan["super"]["weights"] = {"COMM": 1.0}
    market = load_plan_markets(plan["assets"], processed_fixture)
    compared = analyse_portfolios(plan, market, target_observations(plan))
    same_mix = default_plan()
    same_mix["plan"]["years"] = 1
    same_mix["market"]["paths"] = 16
    same_mix["super"]["weights"] = same_mix["outside"]["weights"].copy()
    control = analyse_portfolios(same_mix, market, target_observations(same_mix))
    assert (compared.indices == control.indices).all()
    outside = compared.outcomes.loc[compared.outcomes["Portfolio"] == "Outside super", "Terminal growth of 100"].to_numpy()
    inside = compared.outcomes.loc[compared.outcomes["Portfolio"] == "Inside super", "Terminal growth of 100"].to_numpy()
    assert (outside == control.outcomes.loc[control.outcomes["Portfolio"] == "Inside super", "Terminal growth of 100"].to_numpy()).all()
    assert (outside != inside).any()


def test_command_line_runs_a_plan_file(tmp_path, monkeypatch, capsys, processed_fixture):
    from financial_simulations.cli import main

    monkeypatch.setenv("FINANCIAL_DATASETS_PROCESSED", str(processed_fixture))
    file = tmp_path / "mine.toml"
    file.write_text(plan_to_toml(quick_plan()), encoding="utf-8")
    assert main(["plan", str(file), "--output", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["years_assessed"] == 10 and Path(summary["folder"]).is_dir()


@pytest.mark.skipif("sandbox." in tempfile.gettempdir().lower(),
                    reason="Streamlit AppTest stalls in this managed Windows sandbox; the local browser is used for UI validation")
def test_browser_app_runs_with_tickers_and_interactive_results(tmp_path, monkeypatch, processed_fixture):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("FINANCIAL_DATASETS_PROCESSED", str(processed_fixture))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "src" / "financial_simulations" / "ui" / "app.py"),
                            default_timeout=120)
    app.run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["You", "Investments", "Retirement", "Assumptions", "Results"]
    app.number_input(key="retire__0").set_value(57)
    app.number_input(key="paths__0").set_value(16)
    app.number_input(key="retirement_paths__0").set_value(3).run()
    app.button(key="run_sidebar").click().run()
    assert not app.exception and not app.error
    assert len(app.session_state.result.portfolios.outcomes) == 48  # two portfolios and their combination
    assert app.session_state.plan["person"]["retirement_age"] == 57
    assert (tmp_path / "output" / "plans" / "example-early-retirement" / "portfolio_future.png").exists()
    assert len(app.get("vega_lite_chart")) >= 15
    assert app.session_state.plan["outside"]["rebalance"] == "annual"


def test_35_year_path_and_plots_keep_yearly_summary_compact(tmp_path, processed_fixture):
    plan = quick_plan()
    plan["plan"]["years"] = 35
    plan["person"]["date_of_birth"] = "1995-01-01"
    plan["employment"]["annual_salary"] = 0
    plan["employment"]["salary_sacrifice_per_year"] = 0
    plan["outside"]["cash"] = 0
    plan["outside"]["cash_buffer"] = 0
    plan["outside"]["investment_balance"] = 1000
    plan["outside"]["opening_cost_base"] = 800
    plan["super"]["balance"] = 100
    plan["super"]["total_super_balance_prior_30_june"] = 100
    plan["spending"]["annual"] = 0
    plan["pension"]["start_age"] = 0
    market = load_plan_markets(plan["assets"], processed_fixture)
    run = run_plan(plan, tmp_path, market=market)
    assert (run.result.daily.index[-1] - run.result.daily.index[0]).days >= 35 * 365 - 2
    assert len(run.retirement_bands) >= 35 * 12
    assert len(run.portfolios.paths) >= 2 * 35 * 12
    assert (run.folder / "ledger.png").stat().st_size > 10000


def test_annual_rebalancing_is_the_default_and_harvests_dispersion():
    from financial_simulations.retirement.analysis import _simulate
    import numpy as np

    assert default_plan()["outside"]["rebalance"] == "annual"
    with pytest.raises(PlanError, match="outside.rebalance: must be one of annual, none"):
        normalize_plan({**default_plan(), "outside": {**default_plan()["outside"], "rebalance": "monthly"}})
    # The portfolio-accounting worked example: 50/50, +10% on each asset in turn across a year end.
    dates = (date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 4))
    source = np.array([[0.10, 0.0], [0.0, 0.10]])
    weights = np.array([0.5, 0.5])
    series = _simulate(source, np.array([[0, 1]]), dates, {"held": (weights, False), "rebalanced": (weights, True)},
                       {"held": 0.25, "rebalanced": 0.75}, [0, 2])
    assert series["held"].terminal[0] == pytest.approx(110.0)
    assert series["rebalanced"].terminal[0] == pytest.approx(110.25)
    # The combined series holds opening shares of each account without moving money between them.
    assert series["Combined"].terminal[0] == pytest.approx(0.25 * 110 + 0.75 * 110.25)
    assert series["held"].max_drawdown[0] == 0


def test_sustainable_withdrawal_rate_exhausts_wealth_exactly_at_the_horizon():
    from financial_simulations.retirement.analysis import sustainable_withdrawal_rates
    import numpy as np

    # Flat markets: 24 monthly withdrawals of rate/12, the second year 10% larger, use exactly the opening value.
    flat = np.full((1, 25), 100.0)
    rate = sustainable_withdrawal_rates(flat, 0, 0.10)[0]
    assert rate * (12 + 12 * 1.1) / 12 == pytest.approx(1.0)
    # Doubling immediately after the start halves what each later withdrawal costs.
    doubled = np.r_[100.0, np.full(24, 200.0)][None, :]
    assert sustainable_withdrawal_rates(doubled, 0, 0.0)[0] == pytest.approx(1.0)
    assert np.isnan(sustainable_withdrawal_rates(flat[:, :6], 0, 0.0)[0])


def test_salary_sacrifice_percentage_adds_to_the_dollar_amount(processed_fixture):
    from financial_simulations.retirement.plan import sacrifice_per_year

    plan = default_plan()
    plan["employment"]["salary_sacrifice_per_year"] = 0.0
    plan["employment"]["salary_sacrifice_percent"] = 0.05
    assert sacrifice_per_year(plan) == pytest.approx(8000)
    market = load_plan_markets(plan["assets"], processed_fixture)
    _, scenario, _, _ = build_inputs(plan, market=market)
    assert scenario.employment.salary_sacrifice_per_payday == pytest.approx(8000 / 26)
    plan["employment"]["salary_sacrifice_percent"] = 1.2
    with pytest.raises(PlanError, match="salary_sacrifice_percent: must be between 0 and 1"):
        normalize_plan(plan)


def test_run_progress_covers_every_stage_in_order(processed_fixture):
    plan = quick_plan()
    plan["market"]["retirement_paths"] = 2
    seen = []
    run_plan(plan, None, market=load_plan_markets(plan["assets"], processed_fixture),
             progress=lambda fraction, message: seen.append((fraction, message)))
    fractions = [f for f, _ in seen]
    assert fractions == sorted(fractions) and fractions[0] < 0.05 and fractions[-1] >= 0.95
    messages = " ".join(m for _, m in seen)
    for stage in ("Sampling market paths", "history", "future portfolio paths", "Daily tax ledgers", "saving"):
        assert stage in messages


def test_fixed_outside_contribution_maps_to_paydays_and_stops_at_retirement(processed_fixture):
    plan = default_plan()
    assert plan["outside"]["saving"] == "surplus"
    market = load_plan_markets(plan["assets"], processed_fixture)
    _, scenario, _, _ = build_inputs(plan, market=market)
    assert scenario.outside_contribution_per_payday is None and scenario.stop_investing_at_retirement
    plan["outside"]["saving"] = "fixed"
    plan["outside"]["contribution_per_year"] = 13000.0
    _, scenario, _, _ = build_inputs(plan, market=market)
    assert scenario.outside_contribution_per_payday == pytest.approx(500)
    assert scenario.outside_contribution_growth == pytest.approx(plan["assumptions"]["cpi_annual"])
    plan["outside"]["contribution_indexed"] = False
    assert build_inputs(plan, market=market)[1].outside_contribution_growth == 0
    plan["outside"]["saving"] = "sometimes"
    with pytest.raises(PlanError, match="outside.saving: must be one of surplus, fixed"):
        normalize_plan(plan)


def test_perpetual_withdrawal_rate_keeps_real_capital():
    from financial_simulations.retirement.analysis import perpetual_withdrawal_rates
    import numpy as np

    # 5% a year compounded monthly for 30 years with 2.5% inflation-indexed withdrawals and 2.5% inflation.
    months = 360
    values = 100 * 1.05 ** (np.arange(months + 1) / 12)
    rate = perpetual_withdrawal_rates(values[None, :], 0, 0.025, 0.025, 30)[0]
    steps = 1.025 ** (np.arange(months) // 12) / 12
    growth = values[1:] / 100
    ending = growth[-1] * (1 - rate * (steps / growth).sum())
    assert ending == pytest.approx(1.025 ** 30)
    flat = np.full((1, months + 1), 100.0)
    assert perpetual_withdrawal_rates(flat, 0, 0.0, 0.025, 30)[0] == 0


def test_run_keeps_every_paths_monthly_wealth(processed_fixture):
    plan = quick_plan()
    plan["market"]["retirement_paths"] = 3
    run = run_plan(plan, None, market=load_plan_markets(plan["assets"], processed_fixture))
    paths = run.wealth_paths
    assert paths["Path"].nunique() == 3
    median = paths.groupby("Date")["Total wealth"].median().to_numpy()
    assert median == pytest.approx(run.retirement_bands["P50"].to_numpy())
