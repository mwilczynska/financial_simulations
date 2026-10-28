from datetime import date

import numpy as np
import pytest

from financial_simulations.evaluation import EvaluationPanel, EvaluationSettings, drawdown_statistics, wilson_interval


def settings(**changes):
    return EvaluationSettings(**{"target_basis": "nominal", "target_multiple": 1.0,
                                 "target_annual_growth": 0.0, "confidence": 0.95, "max_panel_mb": 8, **changes})


def test_drawdown_depth_recovery_ties_and_right_censoring():
    dates = tuple(date(2020, 1, d) for d in range(1, 7))
    paths = [[100, 100, 80, 90, 100, 110], [100, 90, 95, 70, 80, 75], [100] * 6,
             [100, 80, 100, 90, 80, 70], [100, 0, 0, 0, 0, 0]]
    result = drawdown_statistics(paths, dates)
    np.testing.assert_allclose(result["max_drawdown"], [-0.2, -0.3, 0, -0.3, -1])
    assert list(result["max_drawdown_recovery_status"]) == ["recovered", "unrecovered", "no_drawdown", "unrecovered", "unrecovered"]
    assert result["max_drawdown_peak_date"][0] == "2020-01-02"
    assert result["max_drawdown_recovery_date"][0] == "2020-01-05"
    assert result["max_drawdown_recovery_date"][1] is None
    np.testing.assert_array_equal(result["max_drawdown_observed_duration_days"], [3, 5, 0, 3, 5])
    np.testing.assert_array_equal(result["longest_underwater_days"], [3, 5, 0, 3, 5])
    assert list(result["longest_underwater_includes_open_episode"]) == [False, True, False, True, True]


def test_calendar_carry_and_real_weekend_drawdown():
    dates = (date(2026, 10, 23), date(2026, 10, 26))
    panel = EvaluationPanel(1, dates, settings(target_basis="real"), 100, inflation=0.04)
    stats = panel.add([[100, 100]])
    assert stats["nominal_max_drawdown"][0] == 0
    assert stats["real_max_drawdown"][0] == pytest.approx(1.04 ** (-3 / 365.25) - 1)
    assert stats["real_max_drawdown_recovery_status"][0] == "unrecovered"
    assert stats["real_longest_underwater_days"][0] == 3
    series, summary = panel.finish(1, independent=True)
    assert list(series["is_observation"]) == [True, False, False, True]
    np.testing.assert_array_equal(series["nominal_median"], [100] * 4)
    assert series["real_median"].is_monotonic_decreasing
    assert summary["misses"] == 1 and summary["fraction_ci_low"] < 1
    assert summary["terminal_mean_mcse"] is None


def test_exact_quantiles_targets_and_no_replay_inference():
    dates = (date(2020, 1, 1), date(2020, 1, 3))
    panel = EvaluationPanel(3, dates, settings(), 100)
    panel.add([[100, 80], [100, 100]])
    panel.add([[100, 120]])
    series, summary = panel.finish(7, independent=False)
    np.testing.assert_allclose(series.iloc[-1][["nominal_p05", "nominal_median", "nominal_p95"]].to_numpy(dtype=float), [82, 100, 118])
    assert summary["misses"] == 1  # Meeting a target exactly is not a shortfall.
    assert summary["fraction_below_target"] == pytest.approx(1 / 3)
    assert summary["mean_target_gap"] == pytest.approx(20 / 3)
    assert summary["fraction_ci_low"] is None and summary["fraction_mcse"] is None
    assert summary["sampling_error_status"] == "dependent_replay_descriptive_only"


def test_wilson_known_example_extremes_and_sampling_precision():
    low, high = wilson_interval(13, 100, 0.95)
    assert low == pytest.approx(0.0775716743)
    assert high == pytest.approx(0.209803515)
    assert wilson_interval(0, 100, 0.95)[1] > 0
    assert wilson_interval(100, 100, 0.95)[0] < 1
    wide = wilson_interval(50, 100, 0.95)
    narrow = wilson_interval(200, 400, 0.95)
    assert narrow[1] - narrow[0] < wide[1] - wide[0]


def test_evaluation_error_boundaries_and_memory_guard():
    dates = (date(2020, 1, 1), date(2020, 1, 2))
    for change in ({"target_basis": "other"}, {"target_multiple": 0}, {"confidence": 1},
                   {"target_annual_growth": -1}, {"max_panel_mb": True}):
        with pytest.raises(ValueError):
            settings(**change)
    with pytest.raises(ValueError, match="inflation"):
        EvaluationPanel(1, dates, settings(target_basis="real"), 100)
    with pytest.raises(ValueError, match="max_panel_mb"):
        EvaluationPanel(1000000, dates, settings(max_panel_mb=1), 100)
    panel = EvaluationPanel(2, dates, settings(), 100)
    with pytest.raises(ValueError, match="incomplete"):
        panel.finish(1, independent=True)
    with pytest.raises(ValueError):
        panel.add([[0, 1]])
    with pytest.raises(ValueError):
        drawdown_statistics([[100, 90]], dates[::-1])
    with pytest.raises(ValueError):
        wilson_interval(11, 10, 0.95)
