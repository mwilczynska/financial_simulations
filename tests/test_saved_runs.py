"""Saved plan runs open with the same results, and stored path ledgers equal re-run ones (ADR 0050)."""

import json
from pathlib import Path
import tempfile

import numpy as np
from pandas.testing import assert_frame_equal
import pytest

pytest.importorskip("pyarrow")

from financial_simulations.data.plan_markets import load_plan_markets
from financial_simulations.retirement.ledger_store import LedgerStore, ledger_parts, write_ledgers
from financial_simulations.retirement.plan import default_plan
from financial_simulations.retirement.run_plan import ledger_for_path, run_plan
from financial_simulations.retirement.saved_runs import (SavedRunError, estimate_bytes, list_saved_runs, load_run,
                                                         save_run)


FRAMES = ("retirement_paths", "retirement_bands", "account_bands", "retirement_annual", "wealth_paths", "path_series")


def compared_plan():
    plan = default_plan()
    plan["spending"].update(compare=["fixed", "guyton_klinger"], retirement="percent")
    plan["market"].update(paths=16, retirement_paths=4)
    return plan


def same_ledger(a, b):
    assert_frame_equal(a.daily, b.daily)
    assert_frame_equal(a.events, b.events)
    assert a.annual == b.annual and a.outstanding == b.outstanding


@pytest.fixture
def compared_run(processed_fixture):
    plan = compared_plan()
    return run_plan(plan, None, market=load_plan_markets(plan["assets"], processed_fixture), workers=1)


def test_saved_run_opens_with_identical_results_for_every_strategy(tmp_path, compared_run):
    run = compared_run
    folder = save_run(run, tmp_path, workers=1, label="test")
    assert not list(tmp_path.glob(".*"))  # no partial folder is left behind
    back = load_run(folder)
    assert list(back.strategies) == list(run.strategies) and back.strategies["fixed"] is back
    assert back.saved_from == folder and back.saved_ledgers is None and back.folder is None
    for rule, original in run.strategies.items():
        loaded = back.strategies[rule]
        assert loaded.strategies is back.strategies and loaded.plan == original.plan and loaded.rule == rule
        assert loaded.representative_path == original.representative_path and loaded.notes == original.notes
        for name in FRAMES:
            assert_frame_equal(getattr(loaded, name), getattr(original, name), obj=name)
        same_ledger(loaded.result, original.result)
    assert (back.portfolios.indices == run.portfolios.indices).all() and back.portfolios.dates == run.portfolios.dates
    for name in ("historical", "paths", "outcomes", "summary"):
        assert_frame_equal(getattr(back.portfolios, name), getattr(run.portfolios, name), obj=name)
    assert back.market.path.dates == run.market.path.dates and (back.market.path.returns == run.market.path.returns).all()
    assert back.market.income_yields == run.market.income_yields and back.rules_manifest == run.rules_manifest
    # Any path re-run from the opened run is the path the run summarised.
    same_ledger(ledger_for_path(back.plan, back.market, back.portfolios, 2),
                ledger_for_path(run.plan, run.market, run.portfolios, 2))
    (row,) = list_saved_runs(tmp_path)
    assert row["folder"] == folder and row["label"] == "test" and row["strategies"] == ["fixed", "guyton_klinger"]
    assert not row["full_ledgers"] and row["retirement_paths"] == 4 and row["files"] == 23
    manifest = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert manifest["strategies"]["fixed"]["full_ledgers"] == 0 and manifest["code"]["python_source_sha256"]


def test_full_ledgers_are_optional_and_equal_the_re_run_ledgers(tmp_path, compared_run):
    run = compared_run
    folder = save_run(run, tmp_path, full_ledgers=True, workers=1)
    assert not (folder / "scratch").exists()
    back = load_run(folder)
    for rule, original in run.strategies.items():
        stored = back.strategies[rule].saved_ledgers
        assert stored.paths == [0, 1, 2, 3]
        for path in stored.paths:
            same_ledger(stored.read(path), ledger_for_path(original.plan, run.market, run.portfolios, path))
    assert list_saved_runs(tmp_path)[0]["full_ledgers"]
    base, ledgers = estimate_bytes(run.plan)
    assert base > 0 and ledgers > 0


def test_paths_with_different_columns_read_back_with_their_own(tmp_path, compared_run):
    """A union schema across paths must not add another path's event columns to a path's frames."""
    first = compared_run.result
    trimmed = type(first)(first.daily.drop(columns=first.daily.columns[-1]), first.events.iloc[:0, :3],
                          first.annual, first.outstanding)
    write_ledgers([(5, *ledger_parts(5, trimmed)), (7, *ledger_parts(7, first))], tmp_path)
    store = LedgerStore(tmp_path)
    same_ledger(store.read(7), first)
    back = store.read(5)
    assert list(back.daily.columns) == list(trimmed.daily.columns) and back.events.empty
    assert list(back.events.columns) == list(trimmed.events.columns)


def test_a_folder_without_a_manifest_is_not_a_saved_run(tmp_path):
    (tmp_path / "other").mkdir()
    assert list_saved_runs(tmp_path) == []
    with pytest.raises(SavedRunError):
        load_run(tmp_path / "other")
    assert np.isfinite(estimate_bytes(compared_plan())[0])


@pytest.mark.skipif("sandbox." in tempfile.gettempdir().lower(),
                    reason="Streamlit AppTest stalls in this managed Windows sandbox; the local browser is used for UI validation")
def test_browser_app_saves_and_opens_results(tmp_path, monkeypatch, processed_fixture):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("FINANCIAL_DATASETS_PROCESSED", str(processed_fixture))
    monkeypatch.setenv("FINANCIAL_SIMULATIONS_WORKERS", "1")
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "src" / "financial_simulations" / "ui" / "app.py"),
                            default_timeout=120)
    app.run()
    app.number_input(key="paths__0").set_value(16)
    app.number_input(key="retirement_paths__0").set_value(3).run()
    app.button(key="run_sidebar").click().run()
    assert not app.exception and app.session_state.result.saved_from is None
    assert app.checkbox(key="save_full_ledgers").value is False  # every path's ledger is opt-in
    app.checkbox(key="save_full_ledgers").check().run()
    app.button(key="save_results").click().run()
    assert not app.exception and not app.error
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
