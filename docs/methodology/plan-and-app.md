# Plan files and the browser app

Date: 2026-10-28. Status: implemented. Decision:
[ADR 0016](../decisions/0016-plan-file-and-browser-app.md).

## One plan, three ways to edit it

A *plan* holds every input a person sets for the single-person retirement
ledger. It is a plain nested table (schema version 1) that round-trips
exactly through TOML and JSON:

| Section | Fields |
| --- | --- |
| `[plan]` | `name`, `start_date` (from 2026-07-01), `years` |
| `[person]` | `date_of_birth`, `retirement_age` (salary stops on this birthday), `private_hospital_cover` |
| `[employment]` | `annual_salary` (gross, excluding super), `salary_sacrifice_per_year`, optional `first_payday` |
| `[[assets]]` | `name` (code), `label`, `annual_return` (assumed AUD total return), `income_yield`, `franked_fraction` |
| `[outside]` | `cash`, `cash_buffer`, `weights` (mix for new money), `[[outside.holdings]]` with `asset`, `value`, `cost_base`, `acquired` |
| `[super]` | `balance`, `weights`, `total_super_balance_prior_30_june` |
| `[spending]` | `annual`, `annual_growth` |
| `[pension]` | `start_age` (0 = none), `transfer_all`, `amount` |
| `[assumptions]` | `cpi_annual`, `wage_growth_annual` |

There are three ways to edit a plan:

- **Browser app:** `financial-simulations ui` opens http://localhost:8501.
- **Command line:** `financial-simulations plan <file>`.
- **By hand:** edit the TOML or JSON file directly.

`normalize_plan` fills documented defaults and lists every problem with its
field path, for example `outside.weights: must sum to 1`. The
[example plan](../../src/financial_simulations/retirement/default_plan.toml)
is invented.

## The browser app

[app.py](../../src/financial_simulations/ui/app.py) is a local Streamlit app
(install the `ui` extra: `pip install -e ".[ui]"`). Its tabs are:

- **You:** name, date of birth, retirement age, hospital cover, salary and
  salary sacrifice.
- **Investments:** an editable asset table, current holdings with cost bases
  and purchase dates, cash, and the mixes outside and inside super.
- **Retirement:** spending and its growth, and when (and how much) to move
  into an account-based pension.
- **Assumptions:** start date, years, CPI and wage growth.
- **Results:**
  - headline wealth, shortfall and tax;
  - a stacked balances chart with hover values;
  - a year-by-year table;
  - CSV downloads and the saved folder location;
  - the list of assumed rule values.

The sidebar holds Run, **Import** (upload `.toml` or `.json`), **Export**
(download TOML or JSON), **Save to `plans/`**, **Open** a saved plan, and
**Reset** to the example. `plans/` is git-ignored, because plans hold
personal details. Errors from the rules (for example a pension before a
condition of release) are shown in plain language instead of a traceback.

## Outputs

Every run, from the app or `financial-simulations plan`, replaces one folder,
`output/plans/<plan-name>/`. It holds `plan.toml` (the exact inputs),
`daily.csv`, `events.csv`, `annual.json`, `ledger.png` and `manifest.json`
(notes, rule-set hashes and assumptions, and the code version). Research
outputs from Stage 1 stay in their own `output/` folders.

## Current limits

- **Market returns.** Until AUD market data and FX are added, returns are
  deterministic: each asset grows at its assumed annual return. Every run
  says so.
- **Horizon.** Runs end before the income year in which the person reaches
  Age Pension age (67), because SAPTO and Age Pension are not modelled. The
  app shortens longer horizons and explains why.
- **Simplifications.** Salary is constant in nominal terms. Spending is a
  fixed nominal amount that grows at the stated rate.

## Validation

`tests/test_plan.py` checks:

- TOML and JSON round trips;
- multi-problem error messages, defaults, and the mapping onto ledger
  inputs (retirement birthday, sacrifice per payday, super units, pension
  date);
- horizon shortening and rejection;
- the consolidated output folder and the command line;
- a headless browser-app run (Streamlit `AppTest`): edit the retirement age,
  run from the sidebar, check the metrics and saved `plan.toml`, then save
  to `plans/`.

The app was also checked by hand in the built-in browser on 2026-10-28:
inputs, run and results. That review replaced an unstacked default chart
with a stacked one in fixed account colours, and made the tab names and
metrics fit a narrow window.
