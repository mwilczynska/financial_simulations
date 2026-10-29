from datetime import date
import json
from pathlib import Path

import pytest

from financial_simulations.retirement.plan import (PlanError, build_inputs, default_plan, horizon, load_plan_text,
                                                   normalize_plan, plan_to_json, plan_to_toml)
from financial_simulations.retirement.run_plan import run_plan


def test_example_plan_round_trips_through_toml_and_json():
    plan = default_plan()
    assert load_plan_text(plan_to_toml(plan), "plan.toml") == plan
    assert load_plan_text(plan_to_json(plan), "plan.json") == plan
    assert json.loads(plan_to_json(plan))["schema_version"] == 1


def test_validation_reports_every_problem_with_its_field_path():
    plan = default_plan()
    plan["person"]["date_of_birth"] = "15/09/1972"
    plan["outside"]["weights"] = {"AUSHARES": 0.4, "GLOBAL": 0.4}
    plan["outside"]["holdings"][0]["asset"] = "BONDS"
    plan["assets"].append(dict(plan["assets"][0]))
    plan["extra"] = {}
    with pytest.raises(PlanError) as error:
        normalize_plan(plan)
    problems = " | ".join(error.value.problems)
    for expected in ("person.date_of_birth: must be a date", "outside.weights: must sum to 1",
                     "outside.holdings[0].asset: unknown asset", "assets[2].name: duplicate asset", "extra: unknown section"):
        assert expected in problems
    with pytest.raises(PlanError, match="could not be read as TOML"):
        load_plan_text("[plan\nname=", "broken.toml")


def test_minimal_plan_gets_documented_defaults():
    plan = normalize_plan({"person": {"date_of_birth": "1980-01-01"}, "assets": [{"name": "SHARES"}],
                           "outside": {"weights": {"SHARES": 1.0}}})
    assert plan["plan"]["start_date"] == "2026-07-01" and plan["plan"]["years"] == 10
    assert plan["assumptions"] == {"cpi_annual": 0.025, "wage_growth_annual": 0.035}
    assert plan["assets"][0]["annual_return"] == 0.06 and plan["pension"]["start_age"] == 0


def test_build_inputs_maps_plan_fields_onto_the_ledger():
    path, scenario, years, notes = build_inputs(default_plan())
    assert path.currency == "AUD" and path.assets == ("AUSHARES", "GLOBAL")
    assert scenario.person.retirement_date == date(2027, 9, 15)  # 55th birthday
    assert scenario.employment.salary_sacrifice_per_payday == pytest.approx(400)
    assert scenario.super_units == {"AUSHARES": pytest.approx(195000), "GLOBAL": pytest.approx(455000)}
    assert scenario.pension.commence == date(2032, 9, 15)
    assert list(years)[0] == "2026-27" and list(years)[-1] == "2035-36"
    assert "deterministic assumed AUD" in notes[0]


def test_horizon_stops_before_the_age_pension_year():
    plan = default_plan()
    plan["person"]["date_of_birth"] = "1962-03-01"  # 67 on 2029-03-01
    plan["pension"]["start_age"] = 0
    start, end, shortened = horizon(plan)
    assert end == date(2028, 6, 30) and shortened
    plan["person"]["date_of_birth"] = "1959-01-01"
    with pytest.raises(PlanError, match="Age Pension age"):
        build_inputs(plan)


def test_run_plan_writes_one_consolidated_folder(tmp_path):
    run = run_plan(default_plan(), tmp_path)
    assert run.folder == tmp_path / "example-early-retirement"
    assert sorted(p.name for p in run.folder.iterdir()) == ["annual.json", "daily.csv", "events.csv", "ledger.png",
                                                             "manifest.json", "plan.toml"]
    assert load_plan_text((run.folder / "plan.toml").read_text(encoding="utf-8")) == default_plan()
    assert len(run.result.annual) == 10 and sum(a["shortfall"] for a in run.result.annual) == 0
    assert not list(run.folder.glob("*.pdf"))


def test_command_line_runs_a_plan_file(tmp_path, capsys):
    from financial_simulations.cli import main

    file = tmp_path / "mine.toml"
    file.write_text(plan_to_toml(default_plan()), encoding="utf-8")
    assert main(["plan", str(file), "--output", str(tmp_path / "out")]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["years_assessed"] == 10 and Path(summary["folder"]).is_dir()


def test_browser_app_runs_the_example_plan_headlessly(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "src" / "financial_simulations" / "ui" / "app.py"),
                            default_timeout=120)
    app.run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["You", "Investments", "Retirement", "Assumptions", "Results"]
    app.number_input(key="retire__0").set_value(57).run()
    assert app.session_state.plan["person"]["retirement_age"] == 57
    app.button(key="run_sidebar").click().run()
    assert not app.exception and not app.error
    labels = [m.label for m in app.metric]
    assert labels == ["Wealth at start", "Wealth at end (2036-06-30)", "Spending shortfall", "Personal tax assessed"]
    assert (tmp_path / "output" / "plans" / "example-early-retirement" / "plan.toml").exists()
    saved = load_plan_text((tmp_path / "output" / "plans" / "example-early-retirement" / "plan.toml").read_text(encoding="utf-8"))
    assert saved["person"]["retirement_age"] == 57
    next(b for b in app.button if b.label.startswith("Save to plans/")).click().run()
    assert (tmp_path / "plans" / "example-early-retirement.toml").exists()
