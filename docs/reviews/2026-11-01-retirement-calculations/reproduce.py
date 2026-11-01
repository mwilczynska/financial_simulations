"""Synthetic historical review probes for revision a3b67a9.

Run from the repository root:
    python docs/reviews/2026-11-01-retirement-calculations/reproduce.py

Assertions confirm reviewed defects, not desired behaviour after correction.
All financial amounts and birth dates are synthetic. Fresh output is ignored;
the tracked evidence.json remains a snapshot of the reviewed revision.
"""
from datetime import date
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from financial_simulations.markets.path import MarketPath
from financial_simulations.retirement.ledger import AssetIncome, Employment, LedgerScenario, Parcel, Pension, Person, run_ledger
from financial_simulations.retirement.paths import _summarise
from financial_simulations.retirement.analysis import target_observations
from financial_simulations.retirement.plan import default_plan
from financial_simulations.retirement.real import flow_deflator, stock_deflator
from financial_simulations.rules.au.parameters import load_ruleset, UnsupportedRule
from financial_simulations.rules.au.projection import project_rulesets, ProjectionAssumptions
from financial_simulations.rules.au.tax import CapitalGainEvent, IncomeYear, assess

RULES = load_ruleset('2026-27')
YEARS = project_rulesets(RULES, '2028-29', ProjectionAssumptions(0, 0))
results = {}

def market(start, end, assets=('A',), daily=0.0):
    dates = tuple(pd.bdate_range(start, end).date)
    return MarketPath(dates, assets, np.full((len(dates)-1, len(assets)), daily), 'AUD')

def scenario(**kwargs):
    base = dict(person=Person('1965-01-01', '2025-01-01'), outside_weights={'A': 1.0}, super_weights={'A': 1.0})
    base.update(kwargs)
    return LedgerScenario(**base)

# Accumulation income tax survives in the annual assessment but disappears from wealth after transfer.
path = market('2026-07-01', '2027-06-30')
s = scenario(super_units={'A': 100000}, income={'A': AssetIncome(.04)}, pension=Pension('2027-04-01'))
r = run_ledger(path, s, YEARS)
results['fund_tax_after_transfer'] = {'assessed': r.annual[0]['accumulation_tax'], 'paid': r.daily.fund_tax.sum(),
                                      'outstanding': r.outstanding}
assert abs(r.annual[0]['accumulation_tax'] - 450) < 1e-6 and r.daily.fund_tax.sum() == 0

# Two instalments below the three-year cap fail because the second call adds the cumulative FY total again.
s = scenario(outside_cash=500000, cash_buffer=500000, non_concessional=(('2026-08-03', 200000), ('2026-09-01', 50000)))
try:
    run_ledger(path, s, YEARS)
except UnsupportedRule as exc:
    results['ncc_250000_below_390000_cap'] = str(exc)
else:
    raise AssertionError('Expected the reviewed NCC defect')

# A partial path invents a quarter-end distribution on its final observation.
s = scenario(person=Person('1980-01-01'), outside_parcels=(Parcel('A', 100000, 100000, '2025-01-01'),),
             income={'A': AssetIncome(.04)}, cash_buffer=100000)
short = run_ledger(market('2026-07-01', '2026-07-15'), s, YEARS)
long = run_ledger(market('2026-07-01', '2026-09-30'), s, YEARS)
results['partial_quarter'] = {'short_run_distribution_by_july_15': short.daily.distributions.sum(),
                              'long_run_distribution_by_july_15': long.daily.loc[:'2026-07-15'].distributions.sum()}
assert short.daily.distributions.sum() == 1000 and long.daily.loc[:'2026-07-15'].distributions.sum() == 0

# Calendar multiplies a 252-observation calibrated return on 260+ dates.
p = default_plan()
p['plan'].update(start_date='2026-07-01', years=1)
dates = target_observations(p)
steps = len(dates)-1
results['calendar'] = {'return_observations': steps, 'growth_for_10_percent_calibrated_cagr': 1.1**(steps/252)-1,
                       'forty_year_wealth_ratio_vs_252': 1.1**((steps/252-1)*40)}

p['plan'].update(start_date='2028-07-01', years=1)
dates = target_observations(p)
weekend_path = MarketPath(dates, ('A',), np.zeros((len(dates)-1,1)), 'AUD')
r = run_ledger(weekend_path, scenario(person=Person('1980-01-01'), super_units={'A':100000},
                                    income={'A':AssetIncome(.04)}), YEARS)
results['weekend_year_end'] = {'requested_end':'2029-06-30', 'actual_end':str(dates[-1]),
                              'annual_assessments':len(r.annual), 'fund_tax_paid':r.daily.fund_tax.sum(),
                              'unassessed':r.outstanding['unassessed_year']}

# The final sale creates a tax liability, but the path still reports funded and zero ending wealth.
s = scenario(outside_parcels=(Parcel('A', 120000, 0, '2020-01-01'),), annual_spending=120000)
r = run_ledger(path, s, YEARS)
summary = _summarise(0, r, date(2025,1,1), 0)[0]
results['terminal_liability'] = {'status': summary['Status'], 'ending_wealth': summary['Ending wealth'],
                                'unpaid_tax': summary['Unpaid tax'], 'assessed_not_due': r.outstanding['tax_liabilities']}
assert summary['Status'] == 'funded' and sum(x['amount'] for x in r.outstanding['tax_liabilities']) > 9000

# Claiming fortnightly salary sacrifice as absent from Centrelink employment income.
s = scenario(person=Person('1959-07-01', '2030-01-01'), outside_cash=10000, cash_buffer=100000,
             employment=Employment(26000, '2026-07-02', salary_sacrifice_per_payday=500), age_pension=True)
r = run_ledger(market('2026-07-01', '2026-07-16'), s, YEARS)
event = r.events.loc[r.events.event == 'age_pension'].iloc[0]
results['pension_employment_income'] = {'gross_fortnightly_wages': 1000, 'sacrifice': 500,
                                       'assessed_income_including_deeming': event.assessed_income}

# Starting a full-year salary projection in January drops the first half's tax history.
full = run_ledger(path, scenario(person=Person('1980-01-01'), employment=Employment(104000, '2026-07-02'),
                               payg_withholding=True), YEARS)
half = run_ledger(market('2027-01-01','2027-06-30'), scenario(person=Person('1980-01-01'),
                   employment=Employment(104000,'2026-07-02'), payg_withholding=True), YEARS)
results['midyear_tax'] = {'full_year_salary': full.annual[0]['assessment'].lines['assessable_income'],
                          'full_year_tax': full.annual[0]['assessment'].net_tax,
                          'january_start_salary': half.annual[0]['assessment'].lines['assessable_income'],
                          'january_start_tax': half.annual[0]['assessment'].net_tax,
                          'january_start_settlement': half.outstanding['tax_liabilities']}

# Contributions after age 75 are accepted by the ledger.
s = scenario(person=Person('1950-01-01', '2015-01-01'), outside_cash=100000, cash_buffer=100000,
             non_concessional=(('2026-08-03', 50000),), age_pension=True)
r = run_ledger(path, s, YEARS)
results['ncc_after_age_75'] = {'age': 76, 'accepted': r.annual[0]['non_concessional_contributions']}

# Reporting uses different deflators for the numerator and denominator of the same withdrawal rate.
start = date(2026,11,1)
mark = date(2027,6,30)
results['real_withdrawal_rate'] = {'nominal': .04,
   'reported_using_stepped_flow_and_daily_wealth': .04 * stock_deflator([mark], start, .1)[0] / flow_deflator([date(2027,7,1)],start,.1)[0]}

# Reordering assets changes distributions and tax on an economically identical portfolio.
def mixed(assets):
    return run_ledger(market('2026-07-01','2027-06-30',assets), scenario(person=Person('1980-01-01'),
         super_units={'A':80000,'B':20000}, super_weights={'A':.2,'B':.8},
         income={'A':AssetIncome(.04),'B':AssetIncome(.08)}), YEARS)
ab, ba = mixed(('A','B')), mixed(('B','A'))
results['asset_order'] = {'AB_tax': ab.daily.fund_tax.sum(), 'BA_tax': ba.daily.fund_tax.sum(),
                          'AB_end':ab.daily.total.iloc[-1], 'BA_end':ba.daily.total.iloc[-1]}

# The law requires deferred non-residential gains to absorb losses before post-reform gains.
events = (CapitalGainEvent('2020-01-01','2028-03-01',40000,'deferred'),
          CapitalGainEvent('2027-08-01','2028-03-01',10000,'post_reform'),
          CapitalGainEvent('2027-08-01','2028-03-01',-10000,'post_reform'))
a = assess(IncomeYear(capital_events=events), YEARS['2027-28'])
results['post_reform_loss_order'] = {'net_gain_actual': a.net_capital_gain, 'net_gain_required': 25000,
                                    'minimum_tax_base_actual': a.minimum_tax_capital_gain, 'minimum_tax_base_required':10000,
                                    'tax_actual': a.net_tax}

# A pension recipient with post-reform realised gains is not passed the statutory exemption.
pension_path = market('2027-07-01','2028-06-30')
values = pension_path.returns.copy()
values[0,0] = .5
pension_path = MarketPath(pension_path.dates, pension_path.assets, values, 'AUD')
s = scenario(person=Person('1955-01-01','2020-01-01'), age_pension=True,
             outside_parcels=(Parcel('A',100000,100000,'2027-07-01'),), annual_spending=60000)
r = run_ledger(pension_path, s, YEARS)
a = r.annual[0]['assessment']
results['age_pension_cgt_exemption'] = {'age_pension_received':r.annual[0]['age_pension'],
                                      'extra_minimum_tax_charged':a.capital_gains_minimum_tax,
                                      'extra_minimum_tax_required':0}
assert results['age_pension_cgt_exemption']['extra_minimum_tax_charged'] > 0

# A small post-reform gain leaves LITO unused when the minimum tax is added after offsets.
event = CapitalGainEvent('2027-08-01','2028-03-01',10000,'post_reform')
a = assess(IncomeYear(capital_events=(event,)), YEARS['2027-28'])
results['minimum_tax_offset_order'] = {'tax_actual':a.net_tax, 'basic_tax':a.basic_tax,
                                      'extra_tax':a.capital_gains_minimum_tax, 'lito_used':a.lito,
                                      'tax_if_lito_applied_to_total_income_tax':2300}

target = Path(__file__).resolve().parents[3] / 'output' / 'review-2026-11-01' / 'evidence.json'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(results, indent=2, default=str) + '\n', encoding='utf-8', newline='\n')
print(target.read_text(encoding='utf-8'))
