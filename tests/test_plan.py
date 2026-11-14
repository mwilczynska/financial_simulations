from datetime import date
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
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
    assert json.loads(plan_to_json(plan))["schema_version"] == 4
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
    assert plan["assumptions"] == {"cpi_annual": 0.025, "wage_growth_annual": 0.035}
    assert plan["outside"]["investment_balance"] == 0 and plan["pension"]["start_age"] == 0
    assert plan["market"]["block_length"] == 63


def test_build_inputs_maps_portfolios_and_derived_income_onto_ledger(processed_fixture):
    plan = default_plan()
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
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
    assert "measured in Australian dollars" in notes[0]


def test_horizon_runs_past_age_pension_age_with_the_age_pension(processed_fixture):
    plan = default_plan()
    plan["person"].update(date_of_birth="1962-03-01", homeowner=False, other_assets=25000.0)
    plan["pension"]["start_age"] = 0
    start, end, shortened = horizon(plan)
    assert end == date(2036, 6, 30) and not shortened  # ten years, through age 74
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    _, scenario, _, _ = build_inputs(plan, market=market)
    assert scenario.age_pension and not scenario.person.homeowner and scenario.person.other_assets == 25000
    plan["plan"]["years"] = 60
    assert horizon(plan)[1:] == (date(2072, 2, 29), True)  # the day before age 110 (2072 is a leap year)


def test_pension_before_super_access_starts_when_super_becomes_accessible(processed_fixture):
    plan = default_plan()
    plan["person"].update(date_of_birth="1966-05-10", retirement_age=65)
    plan["pension"]["start_age"] = 60
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    _, scenario, _, notes = build_inputs(plan, market=market)
    assert scenario.pension.commence == date(2031, 5, 10)  # 65th birthday, not the requested 60th
    assert any("transition-to-retirement" in note for note in notes)
    plan["person"]["retirement_age"] = 60
    _, scenario, _, notes = build_inputs(plan, market=market)
    assert scenario.pension.commence == date(2026, 7, 1)  # the plan start, already past age 60 and retirement
    assert not any("transition-to-retirement" in note for note in notes)


def test_portfolios_keep_shared_daily_draws_but_reflect_distinct_weights(processed_fixture):
    plan = quick_plan()
    plan["plan"]["years"] = 1
    plan["super"]["weights"] = {"COMM": 1.0}
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    compared = analyse_portfolios(plan, market, target_observations(plan, market))
    same_mix = default_plan()
    same_mix["plan"]["years"] = 1
    same_mix["market"]["paths"] = 16
    same_mix["super"]["weights"] = same_mix["outside"]["weights"].copy()
    control = analyse_portfolios(same_mix, market, target_observations(same_mix, market))
    assert (compared.indices == control.indices).all()
    outside = compared.outcomes.loc[compared.outcomes["Portfolio"] == "Outside super", "Terminal growth of 100"].to_numpy()
    inside = compared.outcomes.loc[compared.outcomes["Portfolio"] == "Inside super", "Terminal growth of 100"].to_numpy()
    assert (outside == control.outcomes.loc[control.outcomes["Portfolio"] == "Inside super", "Terminal growth of 100"].to_numpy()).all()
    assert (outside != inside).any()


@pytest.fixture(scope="module")
def quick_run(processed_fixture):
    """One three-path run without report files, with the progress messages it sent."""
    plan = quick_plan()
    plan["market"]["retirement_paths"] = 3
    seen = []
    run = run_plan(plan, None, market=load_plan_markets(plan["assets"], processed_fixture, currency="AUD"),
                   progress=lambda fraction, message: seen.append((fraction, message)))
    return run, seen


def test_command_line_runs_a_plan_file_and_writes_its_reports(tmp_path, monkeypatch, capsys, processed_fixture):
    from financial_simulations.cli import main

    monkeypatch.setenv("FINANCIAL_DATASETS_PROCESSED", str(processed_fixture))
    plan = quick_plan()
    file = tmp_path / "mine.toml"
    file.write_text(plan_to_toml(plan), encoding="utf-8")
    assert main(["plan", str(file), "--output", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)
    folder = Path(summary["folder"])
    assert summary["years_assessed"] == 10 and folder == tmp_path / "out" / "example-early-retirement"
    for name in ("portfolio_future.png", "retirement_range.png", "retirement_paths.csv", "asset_summary.csv", "manifest.json"):
        assert (folder / name).exists(), name
    assert load_plan_text((folder / "plan.toml").read_text(encoding="utf-8")) == plan
    assert not list(folder.glob("*.pdf"))


def test_run_results_reconcile_and_progress_covers_every_stage(quick_run):
    run, seen = quick_run
    assert len(run.portfolios.outcomes) == 48  # 16 shared paths for each portfolio and their combination
    assert len(run.retirement_paths) == 3 and "Wealth when super accessible" in run.retirement_paths
    yearly = run.retirement_annual
    flows = [c for c in yearly.columns if c.startswith("Flow: ")]
    assert "Flow: Spending" in flows and "Flow: Investment returns" in flows
    assert (yearly[flows].sum(axis=1) - yearly["Net change in wealth"]).abs().max() < 1e-4
    # Every path's monthly wealth is kept, and its median is the reported band.
    paths = run.wealth_paths
    assert paths["Path"].nunique() == 3
    assert paths.groupby("Date")["Total wealth"].median().to_numpy() == pytest.approx(run.retirement_bands["P50"].to_numpy())
    # Each path's account series add up to its total wealth.
    series = run.path_series
    assert series["Path"].nunique() == 3 and {"Outside super", "Super and pension", "Pension account"} <= set(series)
    total = series.groupby("Date")[["Outside super", "Super and pension"]].sum().sum(axis=1)
    assert total.to_numpy() == pytest.approx(paths.groupby("Date")["Total wealth"].sum().to_numpy())
    fractions = [f for f, _ in seen]
    assert fractions == sorted(fractions) and fractions[0] < 0.05 and fractions[-1] >= 0.95
    messages = " ".join(m for _, m in seen)
    for stage in ("Sampling market paths", "history", "future portfolio paths", "Daily tax ledgers", "saving"):
        assert stage in messages


@pytest.mark.skipif("sandbox." in tempfile.gettempdir().lower(),
                    reason="Streamlit AppTest stalls in this managed Windows sandbox; the local browser is used for UI validation")
def test_browser_app_runs_draws_every_page_and_saves_and_opens_results(tmp_path, monkeypatch, processed_fixture):
    pytest.importorskip("streamlit")
    pytest.importorskip("pyarrow")
    from pandas.testing import assert_frame_equal
    from streamlit.testing.v1 import AppTest
    from financial_simulations.retirement.saved_runs import list_saved_runs

    monkeypatch.setenv("FINANCIAL_DATASETS_PROCESSED", str(processed_fixture))
    monkeypatch.setenv("FINANCIAL_SIMULATIONS_WORKERS", "1")
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "src" / "financial_simulations" / "ui" / "app.py"),
                            default_timeout=120)
    app.run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["You", "Investments", "Retirement", "Assumptions"]  # the Plan page opens first
    # Before a run there are no results to save: both tick boxes in the plan menu are greyed out.
    assert app.checkbox(key="save_results_too").disabled and app.checkbox(key="save_full_ledgers").disabled
    app.number_input(key="retire__0").set_value(57)
    app.number_input(key="paths__0").set_value(16)
    app.number_input(key="retirement_paths__0").set_value(3).run()
    app.button(key="run_sidebar").click().run()
    assert not app.exception and not app.error
    assert len(app.session_state.result.portfolios.outcomes) == 48  # two portfolios and their combination
    assert app.session_state.plan["person"]["retirement_age"] == 57
    folder = tmp_path / "output" / "plans" / "example-early-retirement"
    assert (folder / "portfolio_future.png").exists() and (folder / "retirement_outcomes.png").exists()
    assert (folder / "retirement_markets.png").exists()
    assert app.session_state.plan["outside"]["rebalance"] == "annual"
    # A finished run opens the Outcomes page; only its open tab (Wealth) is drawn.
    assert app.session_state.page == "Outcomes"
    assert [t.label for t in app.tabs] == ["Wealth", "Risk over time", "Spending", "Age Pension", "Money in and out", "Tables"]
    assert len(app.get("vega_lite_chart")) == 2
    for tab in ("Risk over time", "Spending", "Age Pension", "Money in and out", "Tables"):
        app.session_state["outcome_tabs__0"] = tab
        app.run()
        assert not app.exception, tab
    for page in ("Markets", "Method", "Paths"):
        app.session_state["page"] = page
        app.run()
        assert not app.exception, page
    # One path opens on its markets, balances and flows stacked in one chart, under the market statistics table.
    assert [t.label for t in app.tabs] == ["Markets, wealth and money", "Transfers between accounts", "Year by year", "Event log"]
    assert len(app.get("vega_lite_chart")) == 1 and "CAGR" in app.dataframe[0].value
    for tab in ("Transfers between accounts", "Year by year", "Event log"):
        app.session_state["path_tabs__0"] = tab
        app.run()
        assert not app.exception, tab
    picker = app.selectbox(key="ledger_path__0")
    everyone = next(option for option in picker.options if option.startswith("Group: all paths"))
    assert picker.options.index(everyone) == 1  # straight after the median path
    picker.set_value(everyone).run()
    assert not app.exception and any(h.value.startswith("All paths (") for h in app.subheader)
    # A group has the same stacked view, from medians and averages across its paths.
    assert [t.label for t in app.tabs] == ["Markets, wealth and money", "Year by year"]
    assert len(app.get("vega_lite_chart")) == 1 and "CAGR" in app.dataframe[0].value
    app.session_state["group_tabs__0"] = "Year by year"
    app.run()
    assert not app.exception
    # The plan menu saves the results with the plan, and opens them again (ADR 0051).
    assert app.session_state.result.saved_from is None
    results, ledgers = app.checkbox(key="save_results_too"), app.checkbox(key="save_full_ledgers")
    assert not results.disabled and not results.value and ledgers.disabled  # every path's ledger needs results ticked
    results.check().run()
    ledgers = app.checkbox(key="save_full_ledgers")
    assert not ledgers.disabled and ledgers.value is False  # every path's ledger is opt-in
    ledgers.check().run()
    app.button(key="save_plan").click().run()
    assert not app.exception and not app.error
    assert (tmp_path / "plans" / "example-early-retirement.toml").exists()
    (row,) = list_saved_runs(tmp_path / "output" / "saved_runs")
    assert row["full_ledgers"] and row["retirement_paths"] == 3
    original = app.session_state.result
    app.button(key="open_saved").click().run()
    assert not app.exception and not app.error
    opened = app.session_state.result
    assert opened.saved_from.resolve() == row["folder"].resolve() and opened.saved_ledgers.paths == [0, 1, 2]
    assert app.session_state.page == "Outcomes" and app.session_state.plan_file is None
    assert_frame_equal(opened.retirement_paths, original.retirement_paths)
    app.session_state["page"] = "Paths"
    app.run()
    assert not app.exception
    # Changed inputs grey the results box out again: a plan file is never saved beside other inputs' results.
    app.session_state["page"] = "Plan"
    app.run()
    app.number_input(key=f"retirement_paths__{app.session_state.version}").set_value(4).run()
    app.run()  # the menu is drawn before the Plan page applies an edit, so it shows on the next rerun
    assert app.checkbox(key="save_results_too").disabled and not app.checkbox(key="save_results_too").value


def test_35_year_path_runs_to_the_end_with_monthly_bands(processed_fixture):
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
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    run = run_plan(plan, None, market=market)
    assert (run.result.daily.index[-1] - run.result.daily.index[0]).days >= 35 * 365 - 2
    assert len(run.retirement_bands) >= 35 * 12
    assert len(run.portfolios.paths) >= 2 * 35 * 12


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


def test_salary_sacrifice_percentage_adds_to_the_dollar_amount(processed_fixture):
    from financial_simulations.retirement.plan import sacrifice_per_year

    plan = default_plan()
    plan["employment"]["salary_sacrifice_per_year"] = 0.0
    plan["employment"]["salary_sacrifice_percent"] = 0.05
    assert sacrifice_per_year(plan) == pytest.approx(8000)
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    _, scenario, _, _ = build_inputs(plan, market=market)
    assert scenario.employment.salary_sacrifice_per_payday == pytest.approx(8000 / 26)
    plan["employment"]["salary_sacrifice_percent"] = 1.2
    with pytest.raises(PlanError, match="salary_sacrifice_percent: must be between 0 and 1"):
        normalize_plan(plan)


def test_salary_follows_wage_growth_unless_switched_off(processed_fixture):
    plan = default_plan()
    assert plan["employment"]["salary_indexed"] is True
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    _, scenario, _, _ = build_inputs(plan, market=market)
    assert scenario.employment.annual_growth == pytest.approx(plan["assumptions"]["wage_growth_annual"])
    plan["employment"]["salary_indexed"] = False
    _, scenario, _, _ = build_inputs(normalize_plan(plan), market=market)
    assert scenario.employment.annual_growth == 0.0


def test_fixed_outside_contribution_maps_to_paydays(processed_fixture):
    plan = default_plan()
    assert plan["outside"]["saving"] == "surplus"
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    _, scenario, _, _ = build_inputs(plan, market=market)
    assert scenario.outside_contribution_per_payday is None
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


def test_spending_rule_defaults_to_fixed_and_maps_to_the_ledger(processed_fixture):
    plan = default_plan()
    assert plan["spending"]["compare"] == ["fixed"] and plan["spending"]["minimum"] == 0
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    plan["spending"].update(compare=["guyton_klinger"], minimum=30000.0, maximum=90000.0, guardrail_band=0.25)
    with pytest.raises(PlanError, match="spending.retirement: market-responsive or compared strategies start from a"):
        normalize_plan(plan)
    plan["spending"].update(retirement="percent", retirement_percent=0.05)
    scenario = build_inputs(plan, market=market)[1]
    rule = scenario.spending_rule
    assert (rule.kind, rule.minimum, rule.maximum, rule.band, rule.step) == ("guyton_klinger", 30000.0, 90000.0, 0.25, 0.10)
    assert rule.start_rate == 0.05 and rule.bound_growth == plan["assumptions"]["cpi_annual"]
    assert scenario.retirement_spending == 1.0
    plan["spending"]["compare"] = ["vanguard"]
    run = run_plan({**plan, "market": {**plan["market"], "paths": 16, "retirement_paths": 2}}, None, market=market)
    assert (run.result.events["event"] == "spending_rule").any()
    plan["spending"]["compare"] = ["half"]
    with pytest.raises(PlanError, match="spending.compare: tick at least one of fixed, guyton_klinger, vanguard, percent"):
        normalize_plan(plan)


def test_compared_strategies_share_one_start_and_old_single_rules_still_load(processed_fixture):
    from financial_simulations.retirement.plan import plan_to_toml, strategy_plan

    plan = default_plan()
    plan["spending"].update(compare=["percent", "fixed", "guyton_klinger"], retirement="percent")
    plan = normalize_plan(plan)
    assert plan["spending"]["compare"] == ["fixed", "guyton_klinger", "percent"]  # in a fixed order
    assert 'compare = ["fixed", "guyton_klinger", "percent"]' in plan_to_toml(plan)
    assert "schema_version = 4" in plan_to_toml(plan) and "rule" not in plan["spending"]
    # Fixed spending compared with a market-responsive rule must start from the same percentage of wealth.
    with pytest.raises(PlanError, match="spending.retirement"):
        normalize_plan({**plan, "spending": {**plan["spending"], "compare": ["fixed", "vanguard"], "retirement": "same"}})
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    with pytest.raises(ValueError, match="pick one with strategy_plan"):
        build_inputs(plan, market=market)
    assert build_inputs(strategy_plan(plan, "fixed"), market=market)[1].spending_rule.start_rate == plan["spending"]["retirement_percent"]
    assert build_inputs(strategy_plan(plan, "percent"), market=market)[1].spending_rule.kind == "percent"
    with pytest.raises(ValueError, match="not one of the plan's compared strategies"):
        strategy_plan(plan, "vanguard")
    # A version 2 file with one rule loads as a one-strategy comparison.
    old = {**plan, "schema_version": 2, "spending": {"annual": 80000.0, "rule": "vanguard", "retirement": "percent"}}
    assert normalize_plan(old)["spending"]["compare"] == ["vanguard"]


def test_every_compared_strategy_runs_on_the_same_draws_and_writes_its_own_folder(tmp_path, processed_fixture):
    plan = default_plan()
    plan["spending"].update(compare=["fixed", "percent"], retirement="percent")
    plan["market"].update(paths=16, retirement_paths=2)
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    run = run_plan(plan, tmp_path, market=market)
    assert list(run.strategies) == ["fixed", "percent"] and run.strategies["fixed"] is run
    for rule, strategy in run.strategies.items():
        assert strategy.rule == rule and strategy.portfolios is run.portfolios and len(strategy.retirement_paths) == 2
    # Paired draws: spending is the same until retirement, so every strategy reaches it with the same wealth.
    reached = {rule: s.retirement_paths.set_index("Path")["Wealth at retirement"] for rule, s in run.strategies.items()}
    assert (reached["percent"] == reached["fixed"]).all()
    assert not run.strategies["fixed"].retirement_paths["Spending paid"].equals(
        run.strategies["percent"].retirement_paths["Spending paid"])
    folder = run.folder
    for rule in run.strategies:
        assert (folder / "strategies" / rule / "retirement_paths.csv").exists()
        assert (folder / "strategies" / rule / "retirement_range.png").exists()
    assert (folder / "portfolio_future.png").exists() and not (folder / "daily.csv").exists()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["spending_strategies"]["percent"]["folder"] == "strategies/percent"
    for name in ("comparison_summary.csv", "comparison_wealth.png", "comparison_spending.png"):
        assert (folder / name).exists()
    summary = pd.read_csv(folder / "comparison_summary.csv")
    assert list(summary.columns) == ["Measure", "Kind", "Fixed", "% of wealth"]
    # The same starting spending for every strategy, by construction.
    start = summary.loc[summary["Measure"] == "Starting retirement spending (median)"].iloc[0]
    assert start["Fixed"] == pytest.approx(start["% of wealth"])


def test_spending_rises_with_cpi_and_old_nominal_growth_becomes_a_real_change():
    from financial_simulations.retirement.plan import spending_growth

    plan = default_plan()
    assert plan["spending"]["real_change"] == 0 and spending_growth(plan) == pytest.approx(plan["assumptions"]["cpi_annual"])
    old = {**plan, "spending": {"annual": 80000.0, "annual_growth": 0.035, "retirement_annual": 60000.0, "rule": "fixed"},
           "assumptions": {**plan["assumptions"], "cpi_annual": 0.025}}
    migrated = normalize_plan(old)
    assert migrated["spending"]["real_change"] == pytest.approx(1.035 / 1.025 - 1)
    assert spending_growth(migrated) == pytest.approx(0.035)
    assert migrated["spending"]["retirement"] == "amount" and "annual_growth" not in migrated["spending"]
    same = normalize_plan({**old, "spending": {"annual": 80000.0, "annual_growth": 0.025, "rule": "vanguard"}})
    assert same["spending"]["real_change"] == 0 and same["spending"]["retirement"] == "percent"


def test_workers_start_with_one_maths_thread_and_the_parent_environment_is_restored(monkeypatch):
    import os
    from financial_simulations.retirement.paths import THREAD_LIMITS, _without_main_module

    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "8")
    with _without_main_module():
        assert all(os.environ[name] == "1" for name in THREAD_LIMITS)
    assert os.environ["OPENBLAS_NUM_THREADS"] == "8"


def test_all_paths_chart_draws_a_spread_of_funded_paths_and_every_ruin_path():
    pytest.importorskip("streamlit")
    import numpy as np
    import pandas as pd
    from financial_simulations.ui.app import SHOWN_PATHS, shown_paths

    months = pd.date_range("2026-07-31", periods=24, freq="ME")
    rows = [pd.DataFrame({"Date": months, "Path": p, "Status": "depleted" if p % 50 == 0 else "funded",
                          "Total wealth": np.linspace(1e6, 1e6 + 1000 * p, len(months))}) for p in range(700)]
    funded, depleted = shown_paths(pd.concat(rows, ignore_index=True))
    assert len(funded) == SHOWN_PATHS and depleted == list(range(0, 700, 50))
    # Spread evenly across ending wealth: the lowest and highest funded paths are both drawn.
    assert min(funded) == 1 and max(funded) == 699


def test_path_groups_rank_by_ending_wealth_and_keep_at_least_one_path():
    pytest.importorskip("streamlit")
    import pandas as pd
    from financial_simulations.ui.app import ending_percentiles, group_members, ordinal

    calculated = pd.DataFrame({"Path": range(200), "Ending wealth": [float((p * 37) % 200) for p in range(200)]})
    worst = calculated.sort_values("Ending wealth")["Path"].tolist()
    assert group_members(calculated, 0.0, 0.05) == worst[:10]
    assert group_members(calculated, 0.0, 0.001) == worst[:1]
    assert group_members(calculated, 0.99, 1.0) == worst[-2:]
    assert group_members(calculated, 0.45, 0.55) == worst[90:110]
    ranks = ending_percentiles(calculated)
    assert ranks[worst[0]] == pytest.approx(0.25) and ranks[worst[-1]] == pytest.approx(99.75)
    assert [ordinal(v) for v in (0.25, 2, 11, 21, 52.6, 99.75)] == ["1st", "2nd", "11th", "21st", "53rd", "99th"]


def test_future_calendar_keeps_the_history_density_and_extends_shorter_horizons():
    from financial_simulations.markets.calendar import observation_calendar, observations_per_year

    year = observation_calendar("2026-07-01", "2027-06-30", 252)
    # 364 days at 252 a year is 251.1 observations, not the 260 weekdays.
    assert year[0] == date(2026, 7, 1) and len(year) - 1 == pytest.approx(252 * 364 / 365.25, abs=1)
    assert all(d.weekday() < 5 for d in year[1:]) and all(a < b for a, b in zip(year, year[1:]))
    long = observation_calendar("2026-07-01", "2066-06-30", 246.85)
    short = observation_calendar("2026-07-01", "2027-06-30", 246.85)
    assert long[:len(short)] == short and long[len(short)] > short[-1]
    assert (len(long) - 1) / 40 == pytest.approx(246.85, abs=0.05)
    weekdays = tuple(pd.bdate_range("2026-07-02", "2027-06-30").date)
    assert observation_calendar("2026-07-01", "2027-06-30", 262) == (date(2026, 7, 1), *weekdays)
    assert observations_per_year(pd.bdate_range("2021-01-01", "2021-12-31").date) == pytest.approx(260 * 365.25 / 364)
    # A 10% CAGR calibrated over 252 observations grows about 10% a year on this calendar, not 10.33%.
    assert 1.1 ** ((len(year) - 1) / 252) - 1 == pytest.approx(0.10, abs=0.001)


def test_planner_paths_use_the_history_density_and_the_requested_end(processed_fixture):
    from financial_simulations.markets.calendar import observations_per_year

    plan = default_plan()
    plan["plan"].update(start_date="2028-07-01", years=1)  # ends Saturday 30 June 2029
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    path, scenario, _, _ = build_inputs(plan, market=market)
    assert path.dates == target_observations(plan, market)
    assert len(path.dates) - 1 == pytest.approx(observations_per_year(market.path.dates), abs=1)
    assert path.dates[-1] == date(2029, 6, 29) and scenario.end_date == date(2029, 6, 30)
    # The reference path compounds each ticker's CAGR per calendar day, whatever the calendar.
    cagr = market.asset_summary.set_index("Ticker").loc[list(path.assets), "Full-sample CAGR"].to_numpy()
    growth = np.prod(1 + path.returns, axis=0)
    assert growth == pytest.approx((1 + cagr) ** ((path.dates[-1] - path.dates[0]).days / 365.25))


def test_a_midyear_plan_start_requires_confirmed_year_to_date_amounts(processed_fixture):
    plan = default_plan()
    assert plan["year_to_date"]["entered"] is False and plan["year_to_date"]["labour_income"] == 0
    plan["plan"]["start_date"] = "2027-01-01"
    with pytest.raises(PlanError, match="year_to_date.entered"):
        normalize_plan(plan)
    plan["year_to_date"].update(entered=True, labour_income=52000, payg_withheld=11000, age_pension=0,
                                pending_employer_contributions=1200, prior_year_tax=-500)
    plan = normalize_plan(plan)
    assert load_plan_text(plan_to_toml(plan), "plan.toml") == plan
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    _, scenario, _, _ = build_inputs(plan, market=market)
    opening = scenario.opening_year
    assert opening.labour_income == 52000 and opening.payg_withheld == 11000
    assert opening.pending_contributions == ((date(2027, 1, 12), 1200.0, 0.0),)  # seven business days after the start
    assert opening.tax_due == ((date(2027, 1, 1), -500.0, "2025-26"),)  # 31 October has passed: due at the start


def test_a_1_july_plan_start_passes_last_years_tax_and_age_pension_split(processed_fixture):
    plan = default_plan()
    market = load_plan_markets(plan["assets"], processed_fixture, currency="AUD")
    assert build_inputs(plan, market=market)[1].opening_year is None
    plan["year_to_date"].update(prior_year_tax=2500, age_pension=1000)
    _, scenario, years, _ = build_inputs(normalize_plan(plan), market=market)
    opening = scenario.opening_year
    assert opening.tax_due == ((date(2026, 10, 31), 2500.0, "2025-26"),)
    rate = years["2026-27"]["age_pension_rate"]
    assert opening.age_pension_taxable == pytest.approx(1000 * (rate["basic"] + rate["supplement_taxable"]) / 1237.70)


def test_legacy_planning_age_still_loads_and_is_dropped():
    # ADR 0041 removed the portfolio-only withdrawal rates that planning_age controlled.
    plan = default_plan()
    plan["assumptions"]["planning_age"] = 95
    assert "planning_age" not in normalize_plan(plan)["assumptions"]


def test_mostly_zero_measures_report_share_and_median_among_affected():
    pytest.importorskip("streamlit")
    from financial_simulations.ui.app import affected

    assert affected([0, 0, 10, 30]) == "50.0% · $20"
    assert affected([0.0, 0.0]) == "None"
    assert affected([]) == "–"


def test_worker_count_honours_requests_and_limits_the_automatic_count(monkeypatch):
    from financial_simulations.retirement import paths

    monkeypatch.delenv("FINANCIAL_SIMULATIONS_WORKERS", raising=False)
    monkeypatch.setattr(paths.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(paths, "available_memory", lambda: 64 * 1024 ** 3)
    assert paths.worker_count(1000) == (32 - paths.CPU_HEADROOM, None)
    assert paths.worker_count(20) == (10, None)  # half the tasks
    assert paths.worker_count(4) == (1, None)  # starting workers would cost more than it saves
    assert paths.worker_count(1000, 6) == (6, None) and paths.worker_count(3, 6) == (3, None)
    monkeypatch.setenv("FINANCIAL_SIMULATIONS_WORKERS", "5")
    assert paths.worker_count(1000) == (5, None)
    monkeypatch.delenv("FINANCIAL_SIMULATIONS_WORKERS")
    # 5 GB available leaves room for (5 GB - 4 GB) / 200 MB = 5 workers, and the run says why.
    monkeypatch.setattr(paths, "available_memory", lambda: 5 * 1024 ** 3)
    workers, note = paths.worker_count(1000)
    assert workers == 5 and "5 worker processes instead of 28" in note
    monkeypatch.setattr(paths, "available_memory", lambda: None)
    assert paths.worker_count(1000) == (28, None)


@pytest.mark.skipif("sandbox." in tempfile.gettempdir().lower(),
                    reason="Streamlit AppTest stalls in this managed Windows sandbox; the local browser is used for UI validation")
def test_app_compares_ticked_strategies_and_ignores_a_stale_cores_choice(tmp_path, monkeypatch, processed_fixture):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("FINANCIAL_DATASETS_PROCESSED", str(processed_fixture))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "src" / "financial_simulations" / "ui" / "app.py"),
                            default_timeout=120)
    # A label left over from an earlier rerun once reached the worker count as text and crashed the page.
    app.session_state["calculation_cores"] = "Automatic (24 on this computer)"
    app.run()
    assert not app.exception
    app.checkbox(key="compare_vanguard__0").check().run()
    assert not app.exception
    assert app.session_state.plan["spending"]["compare"] == ["fixed", "vanguard"]
    assert app.session_state.plan["spending"]["retirement"] == "percent"
    assert any("about 2 times as long" in c.value for c in app.caption)
    app.number_input(key="paths__0").set_value(16)
    app.number_input(key="retirement_paths__0").set_value(3).run()
    app.button(key="run_sidebar").click().run()
    assert not app.exception and not app.error
    assert app.session_state.result.strategies["vanguard"].rule == "vanguard"
    # One strategy is drawn at a time (ADR 0046): the first, until another is picked (ADR 0047).
    app.session_state["page"] = "Paths"
    app.run()
    keys = {box.key for box in app.selectbox}
    assert "ledger_path_fixed__0" in keys and "ledger_path_vanguard__0" not in keys
    picker = app.selectbox(key="ledger_path_fixed__0")
    picker.set_value(picker.options[2]).run()
    app.session_state["strategy_pick__0"] = "vanguard"
    app.run()
    assert not app.exception
    assert app.selectbox(key="ledger_path_vanguard__0").value.startswith("Median ending wealth")
    app.session_state["strategy_pick__0"] = "fixed"
    app.run()
    assert app.selectbox(key="ledger_path_fixed__0").value == picker.options[2]  # each strategy keeps its choice
    assert not any("Session State API" in w.value for w in app.warning)
    app.session_state["page"] = "Compare"
    app.run()
    assert not app.exception
    assert app.selectbox(key="compare_flow__0").value == "Spending"
    app.selectbox(key="compare_flow__0").set_value("Income tax").run()
    app.toggle(key="compare_p10__0").set_value(True).run()
    assert not app.exception
    app.session_state["page"] = "Plan"
    app.run()
    for rule in ("fixed", "vanguard"):
        app.checkbox(key=f"compare_{rule}__0").uncheck().run()
    assert not app.exception and any(e.value == "Tick at least one strategy." for e in app.error)


def test_strategy_comparison_measures_follow_their_definitions():
    from types import SimpleNamespace
    from financial_simulations.retirement.strategy_results import (comparison_table, retired_spending, wealth_lines,
                                                                   yearly_medians)

    def run(spending, ending, shortfall, below):
        paths = pd.DataFrame({"Path": [0, 1, 2], "Status": ["funded"] * 3, "Starting retirement spending": [50.0] * 3,
                              "Lowest retired-year spending": spending, "Spending shortfall": shortfall,
                              "Years below start": below, "Ending wealth after tax owed": ending})
        paths["Status"] = ["depleted" if s > 0 else "funded" for s in shortfall]
        annual = pd.DataFrame({"Path": [0, 0, 1, 1, 2, 2], "FY ending": [2030, 2031] * 3,
                               "Full retired year": [False, True] * 3, "Spending paid": [1.0, 10.0, 1.0, 20.0, 1.0, 30.0],
                               "Shortfall": [0.0, 0.0, 0.0, 0.0, 0.0, shortfall[2]], "Age Pension": [0.0, 5.0, 0.0, 0.0, 0.0, 0.0],
                               "Flow: Spending": [-1.0, -10.0, -1.0, -20.0, -1.0, -30.0]})
        wealth = pd.DataFrame({"Date": pd.to_datetime(["2030-06-30"] * 3), "Path": [0, 1, 2], "Total wealth": [1.0, 2.0, 9.0]})
        return SimpleNamespace(retirement_paths=paths, retirement_annual=annual, wealth_paths=wealth, plan=default_plan())

    strategies = {"fixed": run([40.0, 50.0, 60.0], [0.0, 5.0, 9.0], [0.0, 0.0, 3.0], [0, 1, 1]),
                  "percent": run([10.0, 20.0, 30.0], [6.0, 7.0, 8.0], [0.0, 0.0, 0.0], [1, 1, 1])}
    table = comparison_table(strategies).set_index("Measure")
    # Outcome tiers count each path once (ADR 0048): path 2 ran out under fixed; path 0 drew a part Age Pension.
    assert table.loc["Paths that ran out", "fixed"] == pytest.approx(1 / 3) and table.loc["Paths that ran out", "percent"] == 0
    assert table.loc["Paths on a part Age Pension", "fixed"] == pytest.approx(1 / 3)
    assert table.loc["Average retired-year spending: median", "fixed"] == 20.0
    assert retired_spending(strategies["fixed"]).tolist() == [10.0, 20.0, 30.0]  # full retired years only
    assert table.loc["Spending over full retired years: median", "fixed"] == 20.0
    assert table.loc["Lowest retired year's spending: median", "percent"] == 20.0
    assert table.loc["Paths with any spending shortfall", "fixed"] == pytest.approx(1 / 3)
    assert table.loc["Paths that ever spent below the start", "percent"] == 1.0
    assert table.loc["Ending wealth after tax owed: median", "fixed"] == 5.0
    bars = yearly_medians(strategies)  # spending is an outflow, shown as a positive amount paid
    assert bars["FY ending"].tolist() == [2031, 2031] and bars["Value"].tolist() == [20.0, 20.0]
    assert len(yearly_medians(strategies, retired_only=False)) == 4
    lines = wealth_lines(strategies)
    assert lines.loc[lines["Strategy"] == "fixed", "Median"].item() == 2.0

