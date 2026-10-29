"""Run two illustrative 2026-27 single-person ledgers on a synthetic AUD market path.

The people, balances and market path are invented. Companion market data are
USD, and AUD conversion is deferred, so this is a mechanics demonstration,
not a projection. Outputs (CSV, JSON, PNG) go under output/stage2a-ledger.
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
from financial_simulations.runner import code_manifest


def synthetic_path(seed=2026):
    dates = tuple(pd.bdate_range("2026-07-01", "2027-06-30").date)
    rng = np.random.default_rng(seed)
    # Daily log returns with 7%/6% annual drift and 15%/14% volatility; illustrative only.
    drift, vol = np.array([0.07, 0.06]) / 252, np.array([0.15, 0.14]) / np.sqrt(252)
    returns = np.expm1(drift - vol ** 2 / 2 + vol * rng.standard_normal((len(dates) - 1, 2)))
    return MarketPath(dates, ("AUSHARES", "GLOBAL"), returns, "AUD")


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
    rules = load_ruleset("2026-27")
    path = synthetic_path()
    for name, (title, scenario) in SCENARIOS.items():
        result = run_ledger(path, scenario, {"2026-27": rules})
        write_ledger_report(result, Path(args.output) / name, title,
                            {"rules": rules.manifest(), "code": code_manifest(), "market": "synthetic AUD, seed 2026"})
        annual = result.annual[0]
        print(name, {"taxable_income": annual["assessment"].taxable_income, "net_tax": round(annual["assessment"].net_tax, 2),
                     "spending_paid": round(annual["spending_paid"], 2), "shortfall": round(annual["shortfall"], 2),
                     "end_total": round(result.daily["total"].iloc[-1], 2)})


if __name__ == "__main__":
    main()
