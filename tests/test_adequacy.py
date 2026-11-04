"""Independent arithmetic and boundary checks for the retirement overview."""

import numpy as np
import pandas as pd
import pytest

from financial_simulations.retirement.adequacy import path_adequacy, spending_by_group


def fixture_frames():
    paths = pd.DataFrame({"Path": [0, 1, 2, 3], "Status": ["funded", "funded", "depleted", "unsupported"],
                          "Age Pension received": [0, 20, 50, 100], "Ending wealth": [300, 200, 100, 0]})
    annual = pd.DataFrame([
        (0, 2027, False, 900, 0), (0, 2028, True, 60, 0), (0, 2029, True, 40, 0),
        (1, 2028, True, 30, 20), (1, 2029, False, 999, 0),
        (2, 2028, True, 20, 20), (2, 2029, True, 0, 30),
        (3, 2028, True, 5000, 100),
    ], columns=["Path", "FY ending", "Full retired year", "Spending paid", "Age Pension"])
    return paths, annual


def test_cohorts_are_disjoint_and_shortfall_takes_priority_over_support():
    paths, annual = fixture_frames()
    result = path_adequacy(paths, annual, "2026-07-01").set_index("Path")
    assert list(result.index) == [0, 1, 2]
    assert result["Outcome"].tolist() == ["Funded without Age Pension", "Funded with Age Pension", "Spending or tax shortfall"]
    assert result["Average annual retirement spending"].tolist() == [50, 30, 10]
    assert result["Full retired years"].tolist() == [2, 1, 2]
    assert result["Age Pension in final year"].tolist() == [0, 0, 30]


def test_group_mean_weights_paths_equally_and_counts_missing_years():
    paths, annual = fixture_frames()
    result = path_adequacy(paths, annual, "2026-07-01")
    table = spending_by_group(result).set_index("Path group")
    assert table.loc["All calculated paths", "Average per year"] == 30  # not the pooled-year mean of 32
    assert table.loc["All calculated paths", "Median path average"] == 30
    assert table.loc["All calculated paths", "10th percentile path average"] == pytest.approx(14)
    assert table.loc["Worst 10% by ending wealth", "Average per year"] == 10
    assert table.loc["Best 10% by ending wealth", "Average per year"] == 50


def test_no_full_retired_years_is_missing_not_zero_and_partial_start_is_excluded():
    paths, annual = fixture_frames()
    result = path_adequacy(paths, annual, "2028-01-01").set_index("Path")
    assert result.loc[0, "Average annual retirement spending"] == 40  # excludes FY ending 2028
    assert np.isnan(result.loc[1, "Average annual retirement spending"])
    assert result.loc[1, "Full retired years"] == 0
    assert result.loc[2, "Average annual retirement spending"] == 0
    table = spending_by_group(result.reset_index()).set_index("Path group")
    assert table.loc["All calculated paths", "Paths"] == 3
    assert table.loc["All calculated paths", "Paths with full retired years"] == 2
    assert table.loc["All calculated paths", "Average per year"] == 20


def test_empty_supported_cohort_and_png_exports(tmp_path):
    from financial_simulations.reporting.plan import write_adequacy_plots

    paths, annual = fixture_frames()
    result = path_adequacy(paths.iloc[3:], annual, "2026-07-01")
    assert result.empty
    assert spending_by_group(result)["Average per year"].isna().all()
    write_adequacy_plots(tmp_path, paths, annual, "2026-07-01")
    assert (tmp_path / "retirement_adequacy.png").stat().st_size > 1000
    assert (tmp_path / "retirement_spending_groups.png").stat().st_size > 1000
    saved = pd.read_csv(tmp_path / "path_adequacy.csv")
    assert saved["Average annual retirement spending"].tolist() == [50, 30, 10]
