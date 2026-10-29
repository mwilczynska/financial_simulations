"""Run two illustrative five-year single-person ledgers on a synthetic AUD market path.

The people, balances and market path are invented. Companion market data are
USD, and AUD conversion is deferred, so this is a mechanics demonstration,
not a projection. Years after 2026-27 use projected rule sets with an assumed
2.5% CPI and 3.5% wage growth. Outputs (CSV, JSON, PNG) go under
output/stage2a-ledger.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from financial_simulations.markets.path import MarketPath
from financial_simulations.reporting.ledger import write_ledger_report
from financial_simulations.retirement.ledger import (AssetIncome, Employment, LedgerScenario, Parcel, Pension, Person,
                                                     run_ledger)
from financial_simulations.rules.au.parameters import load_ruleset
from financial_simulations.rules.au.projection import ProjectionAssumptions, project_rulesets
from financial_simulations.runner import code_manifest


def synthetic_path():
    """Deterministic 7% and 6% annual total-return growth: a mechanics fixture, not a market model.

    Stochastic paths belong to the Stage 1 generators; a single random draw
    would make this demonstration depend on an arbitrary seed.
    """
    dates = tuple(pd.bdate_range("2026-07-01", "2031-06-30").date)
    daily = np.log1p(np.array([0.07, 0.06])) / 252
    return MarketPath(dates, ("AUSHARES", "GLOBAL"), np.tile(np.expm1(daily), (len(dates) - 1, 1)), "AUD")


SCENARIOS = {
    "early-retiree-bridge": ("Early retirement at 54: bridge funded outside super", LedgerScenario(
        Person("1972-09-15", retirement_date="2026-12-31", private_hospital_cover=True),
        outside_cash=15000, cash_buffer=10000,
        outside_parcels=(Parcel("AUSHARES", 250000, 180000, "2015-03-02"), Parcel("GLOBAL", 200000, 150000, "2018-08-01")),
        outside_weights={"AUSHARES": 0.5, "GLOBAL": 0.5}, super_units={"GLOBAL": 650000},
        super_weights={"GLOBAL": 1.0}, income={"AUSHARES": AssetIncome(0.04, 0.8), "GLOBAL": AssetIncome(0.02)},
        employment=Employment(160000, "2026-07-02", 400), annual_spending=75000, tsb_prior_30_june=650000)),
    "retiree-pension": ("Retired at 62: account-based pension and outside investments", LedgerScenario(
        Person("1964-08-20", retirement_date="2025-06-30"), outside_cash=20000, cash_buffer=15000,
        outside_parcels=(Parcel("AUSHARES", 150000, 120000, "2012-05-01"),), outside_weights={"AUSHARES": 1.0},
        super_units={"AUSHARES": 300000, "GLOBAL": 500000}, super_weights={"AUSHARES": 0.4, "GLOBAL": 0.6},
        income={"AUSHARES": AssetIncome(0.04, 0.8), "GLOBAL": AssetIncome(0.02)},
        annual_spending=65000, pension=Pension("2026-07-01"), tsb_prior_30_june=800000)),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/stage2a-ledger")
    args = parser.parse_args()
    assumptions = ProjectionAssumptions(cpi_annual=0.025, wage_growth_annual=0.035)
    years = project_rulesets(load_ruleset("2026-27"), "2030-31", assumptions)
    path = synthetic_path()
    for name, (title, scenario) in SCENARIOS.items():
        result = run_ledger(path, scenario, years)
        write_ledger_report(result, Path(args.output) / name, title,
                            {"rules": {fy: r.manifest() for fy, r in years.items()}, "projection": vars(assumptions),
                             "code": code_manifest(), "market": "deterministic synthetic AUD: 7% and 6% annual growth"})
        for annual in result.annual:
            a = annual["assessment"]
            print(name, annual["financial_year"], {"taxable_income": a.taxable_income, "net_tax": round(a.net_tax, 2),
                                                   "minimum_cgt": a.capital_gains_minimum_tax, "wato": a.wato,
                                                   "spending_paid": round(annual["spending_paid"], 2),
                                                   "shortfall": round(annual["shortfall"], 2)})
        print(name, "end total", round(result.daily["total"].iloc[-1], 2))


if __name__ == "__main__":
    main()
