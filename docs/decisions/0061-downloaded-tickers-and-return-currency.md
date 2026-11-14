# ADR 0061: downloaded ASX and US tickers, and a return currency for the plan

Date: 2026-11-14.

Status: accepted; implemented and tested.

## Context

The planner offered 36 listed tickers, all US-dollar histories from `financial_datasets`, and applied their returns
to an Australian-dollar ledger as a stated proxy. The user asked for any ASX or US-listed ticker to be addable, for
the two markets to be distinguishable, for a toggle between AUD and USD, and for a downloaded ticker's full history
to be used. `financial_datasets` gained daily AUDUSD, EURUSD and GBPUSD spot series from 1970 on 2026-11-14, which
makes conversion possible over the listed tickers' whole history. The user's tracker script already downloads
prices with yfinance.

## Alternatives considered

1. **Add each ticker to `financial_datasets`.** Its fund build reconciles vendor cash with issuer records, runs a
   daily refresh and publishes the result. That suits a curated list, not a ticker a user types, and would put
   personal holdings in a public repository.
2. **Download inside a run.** Simple, but a run would depend on the network and on whatever the vendor returns that
   day, and could not be reproduced.
3. **Bare vendor symbols** (`SPY`, `VAS.AX`). Four listed dataset names are also US shares (`STT`, `ITT`, `LTT`,
   `COMM`), so a bare name would be ambiguous.
4. **Convert everything to AUD with no setting.** Removes the proxy but changes every existing plan's results and
   gives no way to reproduce them.
5. **Keep US-dollar returns unconverted and add ASX tickers beside them.** Mixes currencies in one portfolio.
6. **Read prices only, as the tracker script does** (`auto_adjust=True`). Gives total returns but not distributions,
   which the tax ledger needs.

## Decision

- Downloaded tickers are written with a market suffix: `.AX` (ASX, AUD) or `.US` (any US exchange, USD). Listed names
  stay bare and take precedence.
- A download is an explicit action (app button or command). It takes the vendor's longest daily history through
  yfinance with unadjusted prices and dividends, checks it, and stores it with a hash in an ignored local folder.
  Runs only read the store.
- The plan has `market.currency`, `"AUD"` or `"USD"`. Histories quoted in the other currency are converted with
  AUDUSD spot on shared dates; no rate is carried to a date without one.
- Schema version 4. Files of version 2 or 3 load as `"USD"`; new plans and the example plan default to `"AUD"`.
- The plan has an optional `franking` table (ticker to franked share), default zero.
- The sample remains the dates shared by all selected tickers.

## Reasons and evidence

- **User requirements:** any ASX or US ticker; an AUD/USD toggle; full downloaded history; existing plans to load as
  USD and new plans as AUD (confirmed 2026-11-14).
- **Verified facts:** the vendor reports `currency`, `symbol` and exchange in its history metadata, and returns
  close, adjusted close and dividends in consistent units (checked on `VAS.AX`, `VGS.AX`, `SPY.US`, `BRK-B.US` with
  yfinance 1.8.0). The AUDUSD series is US dollars per Australian dollar from 1970-01-02 (upstream methodology).
- **Engineering judgement:** the suffix convention; the tolerances that flag a disagreement between the adjusted
  close and recorded cash (0.002 on a dividend day, 0.0001 otherwise); the 253-day minimum, matching the loader; the
  15-year threshold for the app's short-window warning; same-date conversion, following the upstream guidance,
  despite the rate's earlier fixing time.
- **Uncertain:** how much the rate's timing distorts results beyond the daily statistic was not measured. Vendor
  histories were not compared with issuer records.

## Consequences

- Plans can hold ASX and US shares and funds, and results can be read in either currency.
- New plans give different results from the same inputs entered before this change, because US-dollar returns are
  now converted. Older files are unchanged until their currency is switched.
- A short-history ticker shortens the sampled window for the whole plan.
- Converted daily volatility is overstated by the rate's timing; mixed ASX and US portfolios understate same-day
  co-movement. Both are documented in the methodology and on the Method page.
- `yfinance` becomes an optional dependency. Yahoo can change or throttle its service; a failed download leaves the
  stored copy in place.
- Revisit if a hedged option is wanted (needs interest rates), if a close-aligned exchange rate becomes available,
  or if downloaded tickers need issuer reconciliation.

## Implementation and validation

Methodology: [downloaded tickers and the return currency](../methodology/downloaded-tickers-and-currency.md). Code:
`data/ticker_store.py`, `data/plan_markets.py`, `retirement/plan.py`, `retirement/run_plan.py`, `ui/inputs.py`,
`ui/method_page.py`. Tests: `tests/test_ticker_store.py` and the updated plan tests; 299 tests pass. Real downloads
and a small real plan in both currencies were run on 2026-11-14. PNG report subtitles and the Method and
Markets pages name the plan's currency. No saved-run format change was needed.
