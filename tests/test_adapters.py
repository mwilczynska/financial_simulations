from datetime import date

import numpy as np
import pandas as pd
import pytest

from financial_simulations.data.datasets import load_datasets
from financial_simulations.data.optimiser import load_optimiser_portfolio
from financial_simulations.data.registry import resolve_asset
from financial_simulations.markets.path import MarketPath
from financial_simulations.portfolios.spec import PortfolioSpec


def write_dataset(root, asset="GLSTOCK", dates=None, levels=None, **changes):
    dates = dates or ["2020-01-02", "2020-01-03", "2020-01-06"]
    levels = levels or [100.0, 110.0, 99.0]
    returns = [np.nan, *(b / a - 1 for a, b in zip(levels, levels[1:]))]
    frame = pd.DataFrame({"Date": dates, "Adj Close": levels,
                          "Total Return": returns, "Close": levels,
                          "Price Return": returns,
                          "Source": "synthetic fixture", "Quality Flag": "synthetic",
                          "Source Notes": "Small hand-calculated data, not copied source data."})
    for column, value in changes.items():
        frame[column] = value
    frame.to_csv(root / resolve_asset(asset).filename, index=False, lineterminator="\n")
    return frame


def test_levels_returns_anchor_and_provenance_are_preserved(tmp_path):
    source = write_dataset(tmp_path)
    loaded = load_datasets(tmp_path, ["GLSTOCK"], "2020-01-01", "2020-01-06")
    assert loaded.path.dates[0] == date(2020, 1, 2)
    np.testing.assert_allclose(loaded.path.returns[:, 0], [0.1, -0.1], atol=1e-15)
    assert len(loaded.source_rows["GLSTOCK"]) == len(source)
    assert loaded.manifest["inputs"][0]["quality_counts"] == {"synthetic": 3}
    assert len(loaded.manifest["inputs"][0]["sha256"]) == 64
    assert loaded.path.returns.flags.writeable is False


@pytest.mark.parametrize("changes", [
    {"Date": ["2020-01-02", "2020-01-02", "2020-01-06"]},
    {"Date": ["2020-01-03", "2020-01-02", "2020-01-06"]},
    {"Adj Close": [100, np.nan, 99]},
    {"Adj Close": [100, -1, 99]},
    {"Total Return": [np.nan, np.nan, -0.1]},
    {"Total Return": [np.nan, 0.2, -0.1]},
    {"Quality Flag": ["synthetic", None, "synthetic"]},
])
def test_bad_data_fails_instead_of_being_filled(tmp_path, changes):
    write_dataset(tmp_path, **changes)
    with pytest.raises(ValueError):
        load_datasets(tmp_path, ["GLSTOCK"], "2020-01-01", "2020-01-06")


def test_mismatched_calendars_fail(tmp_path):
    write_dataset(tmp_path)
    write_dataset(tmp_path, "GLBOND", dates=["2020-01-02", "2020-01-03", "2020-01-07"])
    with pytest.raises(ValueError, match="calendars differ"):
        load_datasets(tmp_path, ["GLSTOCK", "GLBOND"], "2020-01-01", "2020-01-07")


def test_price_total_return_difference_is_not_added_as_income(tmp_path):
    write_dataset(tmp_path, **{"Close": [100, 100, 100], "Price Return": [np.nan, 0, 0]})
    loaded = load_datasets(tmp_path, ["GLSTOCK"], "2020-01-01", "2020-01-06")
    assert np.prod(1 + loaded.path.returns[:, 0]) == pytest.approx(0.99)


def test_parquet_and_csv_equivalence(tmp_path):
    pytest.importorskip("pyarrow")
    frame = write_dataset(tmp_path)
    frame.to_parquet(tmp_path / "global_stocks.parquet", index=False)
    csv_data = load_datasets(tmp_path, ["GLSTOCK"], "2020-01-01", "2020-01-06")
    parquet_data = load_datasets(tmp_path, ["GLSTOCK"], "2020-01-01", "2020-01-06", file_format="parquet")
    np.testing.assert_array_equal(csv_data.path.returns, parquet_data.path.returns)


def test_numeric_optimiser_import_ignores_executable_text(tmp_path):
    path = tmp_path / "weights.csv"
    path.write_text('Rank,GLSTOCK Weight,COMM Weight,Existing Script Syntax\n'
                    '1,0.75,0.25,"raise RuntimeError(123)"\n', encoding="utf-8")
    imported = load_optimiser_portfolio(path, rank=1, rebalance="annual")
    assert dict(imported.portfolio.weights) == {"GLSTOCK": 0.75, "CMDTY": 0.25}
    assert not imported.manifest["exported_statistics_used_as_inputs"]
    with pytest.raises(ValueError, match="exactly one"):
        load_optimiser_portfolio(path, rank=2, rebalance="annual")


@pytest.mark.parametrize("weights", [{"GLSTOCK": 0.9}, {"GLSTOCK": -0.1, "GLBOND": 1.1},
                                      {"GLSTOCK": float("nan")}, {"COMM": 0.5, "CMDTY": 0.5},
                                      {"CPI": 1.0}, {"GLSTOCK": True}])
def test_invalid_portfolios_fail(weights):
    with pytest.raises(ValueError):
        PortfolioSpec(weights)


@pytest.mark.parametrize("weights", [None, "invalid table", []])
def test_malformed_weight_tables_are_input_errors(weights):
    with pytest.raises(ValueError, match="mapping"):
        PortfolioSpec(weights)


def test_aliases_currency_and_path_boundaries():
    assert resolve_asset("GOLDPM2x").identifier == "GOLD2X"
    assert resolve_asset("USLCAP3x").identifier == "USLCAP3X"
    with pytest.raises(ValueError, match="FX"):
        PortfolioSpec({"GLSTOCK": 1}, currency="AUD")
    with pytest.raises(ValueError, match="-100%"):
        MarketPath((date(2020, 1, 2), date(2020, 1, 3)), ("GLSTOCK",), [[-1.1]])
    with pytest.raises(ValueError, match="sorted"):
        MarketPath((date(2020, 1, 2), date(2020, 1, 2)), ("GLSTOCK",), [[0]])


def test_common_dates_recompute_spanning_returns_without_filling(tmp_path):
    write_dataset(tmp_path, dates=["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"],
                  levels=[100.0, 110.0, 99.0, 99.0])
    write_dataset(tmp_path, "GLBOND", dates=["2020-01-02", "2020-01-06", "2020-01-07", "2020-01-08"],
                  levels=[50.0, 55.0, 44.0, 44.0],
                  **{"Quality Flag": ["model_x", "model_x", "observed_y", "observed_y"]})
    loaded = load_datasets(tmp_path, ["GLSTOCK", "GLBOND"], "2020-01-01", "2020-01-08",
                           calendar_policy="common_dates")
    assert loaded.path.dates == (date(2020, 1, 2), date(2020, 1, 6), date(2020, 1, 7))
    # GLSTOCK's first kept interval compounds two observed source returns: 1.1 * 0.9 - 1.
    np.testing.assert_allclose(loaded.path.returns, [[-0.01, 0.1], [0.0, -0.2]], atol=1e-15)
    assert loaded.provenance["source_steps_GLSTOCK"].tolist() == [2, 1]
    assert loaded.provenance["source_steps_GLBOND"].tolist() == [1, 1]
    # Unrecognised fixture flags stay unclassified; a splice interval is mixed.
    assert loaded.provenance["provenance_GLBOND"].tolist() == ["reconstructed", "mixed"]
    assert loaded.provenance["provenance"].tolist() == ["mixed", "mixed"]
    assert loaded.manifest["source_dates_not_kept"] == {"GLSTOCK": 1, "GLBOND": 0}
    assert loaded.manifest["multi_observation_intervals"] == 1
    with pytest.raises(ValueError, match="calendar policy"):
        load_datasets(tmp_path, ["GLSTOCK"], "2020-01-01", "2020-01-08", calendar_policy="union")


def test_quality_flag_classification_uses_reviewed_prefixes():
    from financial_simulations.data.datasets import classify_quality_flag

    assert classify_quality_flag("observed_upro_etf_adjusted_total_return") == "observed"
    assert classify_quality_flag("model_3x_daily_reset_synthetic") == "reconstructed"
    assert classify_quality_flag("backcalculated_gsci_daily") == "reconstructed"
    assert classify_quality_flag("synthetic") == "unclassified"
